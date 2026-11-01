"""Subcomandos `translateml xlsx ...` (alias `translateml docx ...`), sin conexión.

  inspect   [--file F]             estructura del archivo (solo lectura)
  languages [--file F]             idiomas configurados y si su pestaña existe
  export    MANIFEST [--file F]    textos con su clave para pegar en la pestaña ENG de la hoja
  build     MANIFEST [--file F]    asocia, valida y genera <idioma>/info.json con su informe
F es Multidioma.xlsx (Google Sheets) o multidioma.docx (Google Docs); --xlsx y --docx son sinónimos de
--file y el formato se decide por la extensión (sources.py). El archivo nunca se modifica.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path as FilePath
from typing import Dict, List, Optional, Tuple

from ..config import ConfigError, Language, Languages, Settings, load_languages
from ..export import write_json, write_texts_csv
from ..pipeline import build_language, enabled_language, load_manifest_template
from ..rebuild import NEWLINES, PREFIX, TOKENS
from .association import (STRUCTURAL, Association, EngIndex, Problem, associate, check_against_manifest, index_eng,
                          index_eng_by_text, sheet_key)
from .errors import SheetsStructureError
from .inspect import inspect_spreadsheet
from .settings import SheetsConfig, load_sheets_config
from .sources import Source, open_source
from .table import cell_name, load_table
from .tabs import missing_tab_message, suggest_tab

MARKER_KINDS = (TOKENS, PREFIX, NEWLINES)
BUILD_REPORT = "xlsx-build-report.json"
INSPECT_REPORT = "xlsx-inspect.json"
FILE_HELP = ("Multidioma.xlsx o multidioma.docx descargado de Google (por defecto, \"file\" de config/sheets.json). "
             "El formato se decide por la extensión.")


# --- línea de comandos ---------------------------------------------------------------------------

def add_file_option(parser, help_text: str = FILE_HELP) -> None:
    parser.add_argument("--file", "--xlsx", "--docx", dest="file", metavar="ARCHIVO", help=help_text)


def register(commands) -> None:
    parser = commands.add_parser("xlsx", aliases=["docx"],
                                 help="Traducciones desde Multidioma.xlsx (Google Sheets) o multidioma.docx (Google Docs).")
    parser.add_argument("--sheets-config", help="Otra configuración (por defecto, config/sheets.json).")
    sub = parser.add_subparsers(dest="source_command", required=True)

    add_file_option(sub.add_parser("inspect", help="Describe pestañas, columnas y estructura del archivo."))
    add_file_option(sub.add_parser("languages", help="Idiomas configurados y si su pestaña existe en el archivo."))

    export = sub.add_parser("export", help="Genera las filas KEY/TEXT para la pestaña ENG de la hoja.")
    export.add_argument("manifest")
    add_file_option(export, "Compara con este archivo y genera solo las filas que faltan.")

    build_cmd = sub.add_parser("build", help="Genera los info.json de cada idioma desde el archivo.")
    build_cmd.add_argument("manifest")
    add_file_option(build_cmd)
    build_cmd.add_argument("--lang", help="Idiomas separados por comas (por defecto, todos los habilitados).")


def load_config(args, settings: Settings) -> SheetsConfig:
    return load_sheets_config(settings.key_column, settings.text_column, file=args.sheets_config, source_file=args.file)


def run(args, settings: Settings) -> int:
    config = load_config(args, settings)
    handlers = {"inspect": _inspect, "export": _export, "build": _build, "languages": _languages}
    return handlers[args.source_command](args, settings, config)


# --- inspect / languages / export ----------------------------------------------------------------

def _languages(args, settings: Settings, config: SheetsConfig) -> int:
    """Estado de los idiomas: los habilitados sin pestaña harían fallar `build`."""
    languages = load_languages(settings.languages_file)
    source = open_source(config, languages) if config.file else None
    tabs = source.tabs() if source else None
    where = f"en el .{source.FORMAT}" if source else ""
    print(f"{'código':9s} {'nombre':22s} {'pestaña':9s} {'carpeta':9s} {'estado':14s} {where}")
    blocking = []
    for language in languages.items:
        state = "origen" if language.code == languages.source else ("habilitado" if language.enabled else "deshabilitado")
        found = ""
        if tabs is not None:
            if language.tab in tabs:
                found = "sí"
            else:
                hint = suggest_tab(language.tab, tabs) if language.tab else None
                found = f"no (¿{hint}?)" if hint else "no"
                if language.enabled:
                    blocking.append(language.code)
        print(f"{language.code:9s} {language.name[:22]:22s} {(language.tab or '-'):9s} {language.folder:9s} {state:14s} {found}")
    if tabs is not None:
        configured = {l.tab for l in languages.items}
        extra = [t for t in tabs if t not in configured]
        if extra:
            print(f"Pestañas {where} sin idioma configurado: {', '.join(extra)}")
        if blocking:
            print(f"ERROR: habilitados sin pestaña {where}: {', '.join(blocking)}. 'build' fallaría para ellos.")
    print(f"{len(languages.enabled)} de {len(languages.items)} idiomas habilitados. Para añadir uno, pon "
          "\"enabled\": true en config/languages.json cuando su pestaña exista en el archivo.")
    return 1 if blocking else 0


def _inspect(args, settings: Settings, config: SheetsConfig) -> int:
    languages = load_languages(settings.languages_file)
    source = open_source(config, languages)
    report = inspect_spreadsheet(source, source.layout, languages.enabled, languages.get(languages.source))
    report = {"file": str(source.file.resolve()), "format": source.FORMAT, "sha256": source.sha256, **report}
    target = settings.output_root / INSPECT_REPORT
    write_json(target, report)
    print(json.dumps({k: v for k, v in report.items() if k != "recommendations"}, ensure_ascii=False, indent=2))
    for tip in report["recommendations"]:
        print(f"- {tip}")
    print(f"\nInforme: {target}")
    return 0


def _export(args, settings: Settings, config: SheetsConfig) -> int:
    manifest_file = FilePath(args.manifest)
    manifest, _, _, units = load_manifest_template(manifest_file, settings)
    game = _game(manifest, manifest_file)
    out = manifest_file.parent
    key_header, text_header = settings.key_column, settings.text_column
    _write_rows(out / "eng-sheet.csv", key_header, text_header, [(sheet_key(game, u.key), u.text) for u in units])
    print(f"{len(units)} textos -> {out / 'eng-sheet.csv'} (columnas {key_header}, {text_header}; "
          "la clave la gestiona el programa y Data no debe editarla)")
    if config.file is None:
        return 0

    languages = load_languages(settings.languages_file)
    source = open_source(config, languages)
    eng = _eng_index(source, languages.get(languages.source), game, units)

    def location(key: str) -> str:
        return cell_name(eng.table, eng.rows[key], eng.text_col)

    new = [u for u in units if u.key not in eng.rows and u.key not in eng.duplicates]
    changed = [{"key": sheet_key(game, u.key), "cell": location(u.key), "sheet": eng.texts[u.key], "template": u.text}
               for u in units if u.key in eng.rows and eng.texts[u.key] != u.text]
    manifest_keys = {u.key for u in units}
    obsolete = [{"key": sheet_key(game, k), "cell": location(k), "text": eng.texts[k]}
                for k in eng.rows if k not in manifest_keys]
    _write_rows(out / "eng-new-rows.csv", key_header, text_header, [(sheet_key(game, u.key), u.text) for u in new])
    report = {"source": _source_info(source), "new": [sheet_key(game, u.key) for u in new], "changed": changed,
              "obsolete": obsolete, "problems": [vars(p) for p in eng.problems]}
    write_json(out / "eng-sheet-report.json", report)
    print(f"Comparado con {source.file.name}: {len(new)} nuevos (eng-new-rows.csv, para añadir al final de ENG sin "
          f"mover filas), {len(changed)} con inglés distinto, {len(obsolete)} obsoletos, {len(eng.problems)} problemas. "
          f"Detalle: {out / 'eng-sheet-report.json'}")
    return 1 if any(p.kind in STRUCTURAL for p in eng.problems) else 0


def _write_rows(file: FilePath, key_header: str, text_header: str, rows) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([key_header, text_header])
        writer.writerows(rows)


# --- build ---------------------------------------------------------------------------------------

@dataclass
class _Build:
    """Lo común a todos los idiomas de una generación."""
    source: Source
    eng: EngIndex
    template: object
    profile: object
    units: list
    game: str
    out: FilePath
    settings: Settings

    @property
    def layout(self):
        return self.source.layout


def _build(args, settings: Settings, config: SheetsConfig) -> int:
    return build(FilePath(args.manifest), settings, config, args.lang)


def build(manifest_file: FilePath, settings: Settings, config: SheetsConfig, lang: Optional[str] = None) -> int:
    """Asocia las traducciones del archivo con el manifest y genera <idioma>/info.json con su informe."""
    manifest, template, profile, units = load_manifest_template(manifest_file, settings)
    game = _game(manifest, manifest_file)
    languages = load_languages(settings.languages_file)
    targets = _target_languages(lang, settings, languages)
    origin = languages.get(languages.source)
    source = open_source(config, languages)
    ctx = _Build(source, _eng_index(source, origin, game, units), template, profile, units, game,
                 manifest_file.parent, settings)

    report: Dict = {
        "status": "ok",
        "source": _source_info(source),
        "template": str(template.file), "game": game, "association": source.layout.association,
        "extracted_texts": len(units),
        "pending_review": _pending_review(ctx.out),
        "eng_problems": [vars(p) for p in ctx.eng.problems],
        "languages": {},
    }
    for problem in ctx.eng.problems:
        print(f"  {'!' if problem.kind in STRUCTURAL else '~'} {problem.cell or ''} {problem.key or ''}: "
              f"{problem.kind} - {problem.detail}")
    for language in targets:
        if language.code == origin.code:
            entry = _build_source_language(ctx, language)
        else:
            entry = _build_translation(ctx, language)
        report["languages"][language.code] = entry
        _print_entry(language, entry)

    entries = report["languages"].values()
    failed = any(e["status"] != "generated" for e in entries)
    warned = any(e.get("missing") or e.get("marker_issues") or e.get("problems") or e.get("same_as_english")
                 for e in entries)
    report["status"] = "error" if failed else ("warnings" if warned else "ok")
    target = ctx.out / BUILD_REPORT
    write_json(target, report)
    print(f"Estado: {report['status']}. Informe: {target}")
    return 1 if failed else 0


def _eng_index(source: Source, origin: Language, game: str, units) -> EngIndex:
    """Filas de la pestaña de origen relacionadas con las claves de la plantilla."""
    tab, layout = origin.tab, source.layout
    if not tab or tab not in source.tabs():
        raise SheetsStructureError("Pestaña de origen: " + missing_tab_message(source.file.name, tab, source.tabs()))
    table = load_table(source, tab, layout.header_row)
    letter = layout.text_column_for(tab)
    if layout.association == "text":
        return index_eng_by_text(table, units, layout.text_header_for(tab), letter)
    eng = index_eng(table, layout.key_header_for(tab), layout.text_header_for(tab), game, letter)
    if eng.key_col is None:
        raise SheetsStructureError(
            f"La pestaña {tab} no tiene la columna '{layout.key_header_for(tab)}', así que sus textos no "
            "se pueden relacionar con la plantilla sin adivinar. Pega en ENG las columnas KEY y TEXT de "
            "eng-sheet.csv (translateml xlsx export) y vuelve a descargar el archivo.")
    return eng


def _build_source_language(ctx: _Build, language: Language) -> Dict:
    """El idioma de origen es la plantilla tal cual; se informa si su pestaña difiere de ella."""
    code, rebuilt = build_language(ctx.template, ctx.profile, ctx.units, {u.key: u.text for u in ctx.units}, language,
                                   ctx.settings, ctx.out, quiet=True)
    _, problems = check_against_manifest(ctx.units, ctx.eng, Association(ctx.eng.table.title))
    differences = [vars(p) for p in problems if p.kind not in ("missing", "not_in_sheet")]
    return {"tab": language.tab, "status": "generated" if code == 0 else "error", "output": rebuilt["output"],
            "applied": 0, "missing": [], "marker_issues": [], "problems": differences,
            "errors": rebuilt["validation_errors"]}


def _build_translation(ctx: _Build, language: Language) -> Dict:
    layout, tab = ctx.layout, language.tab
    if not tab or tab not in ctx.source.tabs():
        return {"tab": tab, "status": "error", "errors": [
            missing_tab_message(ctx.source.file.name, tab, ctx.source.tabs())
            + f" No se asocia ninguna traducción de {language.code}."]}
    allow_position, misalignment = _position_check(ctx, tab)
    if misalignment and ctx.source.position_only:
        return {"tab": tab, "status": "error", "errors": [_structure_error(ctx, language, misalignment)]}
    try:
        association = associate(load_table(ctx.source, tab, layout.header_row), ctx.eng, ctx.game,
                                layout.key_header_for(tab), layout.text_header_for(tab), allow_position,
                                layout.text_column_for(tab))
    except SheetsStructureError as exc:
        return {"tab": tab, "status": "error", "errors": [str(exc)]}

    usable, problems = check_against_manifest(ctx.units, ctx.eng, association)
    all_problems: List[Problem] = association.problems + problems
    if misalignment and any(p.kind == "unlinked" for p in association.problems):
        origin = ctx.eng.table.title
        all_problems.insert(0, Problem(
            "position_not_verified", f"las celdas sin fórmula que referencie {origin} no se usan porque las filas de "
            f"{tab} pueden no corresponder a las de {origin}: {misalignment}", cell=tab, blocking=False))
    structural = [p for p in ctx.eng.problems + all_problems if p.kind in STRUCTURAL]
    entry: Dict = {"tab": tab, "association": dict(association.methods),
                   "problems": [vars(p) for p in all_problems if p.kind not in ("missing", "not_in_sheet")]}
    by_position = association.methods.get("position")
    if by_position and layout.position == "always":
        entry["warning"] = f"{by_position} traducciones asociadas por posición sin comprobar (\"position\": \"always\")."
    if structural:
        entry.update(status="error", errors=[f"{p.kind}: {p.cell or p.key or ''} {p.detail}" for p in structural])
        return entry

    merges = {k: v for k, v in association.merges.items() if k in usable}
    code, rebuilt = build_language(ctx.template, ctx.profile, ctx.units, usable, language, ctx.settings, ctx.out,
                                   quiet=True, merges=merges)
    rejected = {i["key"] for i in rebuilt["issues"] if i["blocking"] and i["kind"] != "missing"}
    applied = {k: v for k, v in usable.items() if k not in rejected}
    merges = {k: v for k, v in merges.items() if k in applied}
    write_texts_csv(ctx.out / "sheets" / f"{language.code}.csv", applied, ctx.settings.key_column,
                    ctx.settings.text_column, merges)
    covered = set(applied) | {k for rest in merges.values() for k in rest}
    source_text = {u.key: u.text for u in ctx.units}
    entry.update(status="generated" if code == 0 else "error", output=rebuilt["output"], applied=len(applied),
                 merged_lines=rebuilt["merged_lines"],
                 same_as_english=[k for k, v in sorted(applied.items()) if v == source_text[k]],
                 missing=[u.key for u in ctx.units if u.key not in covered],
                 marker_issues=[i for i in rebuilt["issues"] if i["kind"] in MARKER_KINDS],
                 errors=rebuilt["validation_errors"])
    return entry


def _position_check(ctx: _Build, tab: str) -> Tuple[bool, Optional[str]]:
    """Si las celdas sin referencia a ENG pueden usar su fila y, si no, por qué (layout.position)."""
    mode = ctx.layout.position
    if mode != "verified":
        return mode == "always", None
    detail = ctx.source.alignment_problem(tab, ctx.eng.table.title)
    return detail is None, detail


def _structure_error(ctx: _Build, language: Language, detail: str) -> str:
    origin = ctx.eng.table.title
    return (f"structure_mismatch: la pestaña {language.tab} no tiene la misma estructura que {origin} ({detail}). "
            f"Sus textos se relacionan por posición, así que no se asocia ninguna traducción de {language.code}: "
            f"deja las mismas tablas, filas y celdas que en {origin}.")


# --- utilidades ----------------------------------------------------------------------------------

def _source_info(source: Source) -> Dict:
    return {"file": str(source.file.resolve()), "format": source.FORMAT, "sha256": source.sha256}


def _game(manifest: Dict, manifest_file: FilePath) -> str:
    return manifest.get("game") or manifest_file.resolve().parent.name


def _print_entry(language: Language, entry: Dict) -> None:
    if entry["status"] != "generated":
        print(f"{language.code} ({entry.get('tab')}): NO GENERADO")
        for error in entry.get("errors", []):
            print(f"  ERROR {error}")
        return
    print(f"{language.code} ({entry.get('tab')}): {entry['applied']} traducciones aplicadas, "
          f"{len(entry['missing'])} faltantes (se conserva el inglés), {len(entry['marker_issues'])} avisos de "
          f"marcadores, {len(entry['problems'])} otros avisos -> {entry['output']}")
    if entry.get("warning"):
        print(f"  AVISO {entry['warning']}")
    if entry.get("same_as_english"):
        print(f"  ~ {len(entry['same_as_english'])} traducciones idénticas al inglés (revisar si son correctas): "
              f"{', '.join(entry['same_as_english'])}")
    for issue in entry["marker_issues"]:
        print(f"  {'!' if issue['blocking'] else '~'} {issue['key']} {issue['path']}: {issue['kind']} - {issue['detail']}")
    for problem in entry["problems"]:
        print(f"  {'!' if problem['blocking'] else '~'} {problem.get('key') or ''} {problem.get('cell') or ''}: "
              f"{problem['kind']} - {problem['detail']}")


def _pending_review(out: FilePath) -> int:
    try:
        return len(json.loads((out / "extraction-report.json").read_text(encoding="utf-8")).get("audit", []))
    except (OSError, ValueError):
        return 0


def _target_languages(codes: Optional[str], settings: Settings, languages: Languages) -> List[Language]:
    if codes:
        return [enabled_language(settings, code.strip()) for code in codes.split(",") if code.strip()]
    if not languages.enabled:
        raise ConfigError("No hay idiomas habilitados en languages.json.")
    return languages.enabled
