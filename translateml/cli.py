"""Interfaz de línea de comandos.

  python3 -m translateml analyze  PLANTILLA            resumen de estructura, reglas y auditoría
  python3 -m translateml extract  PLANTILLA            manifest, CSV de revisión e informe
  python3 -m translateml rebuild  MANIFEST [--texts CSV] [--lang eng]
  python3 -m translateml verify   PLANTILLA [...]      extrae y reconstruye el inglés en memoria
  python3 -m translateml generate PLANTILLA --xlsx F   extract + xlsx build en un solo paso
  python3 -m translateml xlsx {inspect,export,build} ...      Multidioma.xlsx local (ver sheets/commands.py)
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path as FilePath
from typing import List, Optional

from .config import ConfigError, Settings, load_settings
from .export import (ManifestError, extraction_report, load_manifest, manifest_data, read_merges_csv, read_texts_csv,
                     units_from_manifest, write_json, write_review_csv)
from .extraction import Extraction, ProfileError, extract, load_profiles, select_profile
from .jsonpath import format_path
from .keys import reconcile
from .pipeline import build_language, enabled_language, load_manifest_template
from .rebuild import rebuild
from .sheets import commands as sheets_commands
from .sheets.errors import SheetsError
from .sheets.settings import load_sheets_config
from . import __version__
from .template import Template, TemplateError, load_template
from .validation import validate_output

_GAME_ID = re.compile(r"^g\d+$")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="translateml", description="Textos multidioma para info.json de juegos PixiJS.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    generate_cmd = commands.add_parser("generate", help="Extrae la plantilla y genera todos los idiomas desde el .xlsx.")
    generate_cmd.add_argument("template", help="info.json inglés del juego.")
    generate_cmd.add_argument("--xlsx", help="Multidioma.xlsx (por defecto, xlsx_file de config/sheets.json).")
    generate_cmd.add_argument("--lang", help="Idiomas separados por comas (por defecto, todos los habilitados).")
    generate_cmd.add_argument("--name", help="Nombre del juego (por defecto, la carpeta gNNN de la ruta).")
    generate_cmd.add_argument("--out", help="Carpeta de resultados (por defecto output/<juego>).")
    generate_cmd.add_argument("--profile")
    generate_cmd.add_argument("--sheets-config", help="Otra configuración de la hoja (por defecto, config/sheets.json).")

    analyze_cmd = commands.add_parser("analyze", help="Analiza una plantilla sin escribir archivos.")
    analyze_cmd.add_argument("template")
    analyze_cmd.add_argument("--profile")

    extract_cmd = commands.add_parser("extract", help="Extrae los textos a un formato revisable.")
    extract_cmd.add_argument("template")
    extract_cmd.add_argument("--profile")
    extract_cmd.add_argument("--name", help="Nombre del juego (por defecto, la carpeta gNNN de la ruta).")
    extract_cmd.add_argument("--out", help="Carpeta de resultados (por defecto output/<juego>).")
    extract_cmd.add_argument("--fresh-keys", action="store_true",
                             help="Ignora el manifest anterior y numera las claves desde T0001.")

    rebuild_cmd = commands.add_parser("rebuild", help="Reconstruye el JSON de un idioma desde el manifest.")
    rebuild_cmd.add_argument("manifest")
    rebuild_cmd.add_argument("--texts", help="CSV con las columnas de clave y texto (por defecto, los textos del manifest).")
    rebuild_cmd.add_argument("--lang", help="Código interno del idioma (por defecto, el idioma de origen).")
    rebuild_cmd.add_argument("--out", help="Carpeta de resultados (por defecto, la del manifest).")

    verify_cmd = commands.add_parser("verify", help="Comprueba que extraer y reconstruir no altera la plantilla.")
    verify_cmd.add_argument("templates", nargs="+")
    verify_cmd.add_argument("--profile")

    sheets_commands.register(commands)

    for stream in (sys.stdout, sys.stderr):
        # Una consola sin UTF-8 (Windows) no debe interrumpir la ejecución por un texto en japonés o tailandés.
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        handlers = {"analyze": cmd_analyze, "extract": cmd_extract, "rebuild": cmd_rebuild, "verify": cmd_verify,
                    "xlsx": sheets_commands.run, "generate": cmd_generate}
        return handlers[args.command](args, settings)
    except (ConfigError, TemplateError, ProfileError, ManifestError, SheetsError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _load(path: str, settings: Settings, profile_name: Optional[str]):
    template = load_template(path)
    profile = select_profile(template.data, load_profiles(settings.profiles_dir), profile_name)
    return template, profile, extract(template.data, profile)


def _game_name(template: Template) -> str:
    for part in reversed(template.file.resolve().parts):
        if _GAME_ID.match(part):
            return part
    return template.file.stem


def _print_summary(template: Template, extraction: Extraction) -> None:
    data = template.data
    print(f"Plantilla: {template.file}")
    print(f"Perfil: {extraction.profile}")
    if isinstance(data, dict):
        print(f"Secciones: {', '.join(data)}")
    print(f"Textos traducibles: {len(extraction.units)}")
    for rule, count in extraction.rules_found.items():
        print(f"  - {rule}: {count}")
    for selector in extraction.rules_missing:
        print(f"  - regla sin ubicación en esta plantilla: {selector}")
    kinds = Counter(s.kind for s in extraction.skipped)
    if kinds:
        print("Conservados sin traducir: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    print(f"Auditoría (revisar reglas): {len(extraction.audit)}")
    for item in extraction.audit:
        print(f"  ? {format_path(item.path)} = {item.value!r} ({item.reason})")


def cmd_analyze(args, settings: Settings) -> int:
    template, _, extraction = _load(args.template, settings, args.profile)
    _print_summary(template, extraction)
    return 0


def cmd_extract(args, settings: Settings) -> int:
    extract_to(args.template, settings, args.profile, args.name, args.out, args.fresh_keys)
    return 0


def cmd_generate(args, settings: Settings) -> int:
    config = load_sheets_config(settings.key_column, settings.text_column, file=args.sheets_config, xlsx_file=args.xlsx)
    config.require_xlsx()
    out = extract_to(args.template, settings, args.profile, args.name, args.out, fresh_keys=False)
    print("")
    return sheets_commands.build(out / "manifest.json", settings, config, args.lang)


def extract_to(template_path: str, settings: Settings, profile_name: Optional[str], name: Optional[str],
               out: Optional[str], fresh_keys: bool) -> FilePath:
    """Extrae la plantilla y escribe manifest, CSV e informes. Conserva las claves del manifest anterior."""
    template, _, extraction = _load(template_path, settings, profile_name)
    out = FilePath(out) if out else settings.output_root / (name or _game_name(template))
    game = name or _game_name(template)
    next_key = len(extraction.units) + 1
    changes = None
    previous_file = out / "manifest.json"
    if previous_file.is_file() and not fresh_keys:
        previous = load_manifest(previous_file)
        if previous["profile"] == extraction.profile:
            game = name or previous.get("game") or game
            changes = reconcile(units_from_manifest(previous), extraction.units, previous.get("next_key", 1))
            next_key = changes.next_key
    write_json(out / "manifest.json", manifest_data(template, extraction, game, next_key))
    write_json(out / "extraction-report.json", extraction_report(extraction))
    write_review_csv(out / "extracted.csv", extraction.units, settings.key_column, settings.text_column)
    _print_summary(template, extraction)
    files = "manifest.json, extracted.csv, extraction-report.json"
    if changes is not None:
        write_json(out / "key-changes.json", changes.as_dict())
        files += ", key-changes.json"
        print("Claves respecto al manifest anterior: " + ", ".join(f"{k}={v}" for k, v in changes.summary().items()))
    print(f"\nResultados en {out}: {files}")
    return out


def cmd_rebuild(args, settings: Settings) -> int:
    manifest_file = FilePath(args.manifest)
    language = enabled_language(settings, args.lang)
    _, template, profile, units = load_manifest_template(manifest_file, settings)
    if args.texts:
        texts = read_texts_csv(FilePath(args.texts), settings.key_column, settings.text_column)
        unknown = sorted(set(texts) - {u.key for u in units})
        if unknown:
            raise ManifestError(f"Claves que no existen en el manifest: {', '.join(unknown[:10])}")
    else:
        texts = {u.key: u.text for u in units}
    merges = read_merges_csv(FilePath(args.texts), settings.key_column) if args.texts else {}
    unknown = sorted({k for first, rest in merges.items() for k in [first] + rest} - {u.key for u in units})
    if unknown:
        raise ManifestError(f"Claves de MERGED que no existen en el manifest: {', '.join(unknown[:10])}")
    out = FilePath(args.out) if args.out else manifest_file.parent
    return build_language(template, profile, units, texts, language, settings, out, merges=merges)[0]


def cmd_verify(args, settings: Settings) -> int:
    failures = 0
    for path in args.templates:
        template, profile, extraction = _load(path, settings, args.profile)
        result = rebuild(template, extraction.units, {u.key: u.text for u in extraction.units}, profile)
        errors = validate_output(template, result.text, result.changes)
        identical = template.encode(result.text) == template.file.read_bytes()
        ok = not errors and not result.changes and not result.issues and identical
        failures += not ok
        print(f"{'OK  ' if ok else 'FALLO'} {path}: {len(extraction.units)} textos, "
              f"{'idéntico byte a byte' if identical else 'NO idéntico'}")
        for message in errors + [f"{i.key} {i.path}: {i.kind}" for i in result.issues]:
            print(f"      {message}")
    return 1 if failures else 0
