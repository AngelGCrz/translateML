"""Subcomandos `translateml xlsx ...`: Multidioma.xlsx descargado de Google Sheets, sin conexión.

  inspect --xlsx F                 estructura del archivo (solo lectura)
  export  MANIFEST [--xlsx F]      textos con su clave para pegar en la pestaña ENG de la hoja
  build   MANIFEST --xlsx F        asocia, valida y genera <idioma>/info.json con su informe
El .xlsx nunca se modifica.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path as FilePath
from typing import Dict, List

from ..config import ConfigError, Language, Settings, load_languages
from ..export import write_json, write_texts_csv
from ..pipeline import build_language, enabled_language, load_manifest_template
from ..rebuild import NEWLINES, PREFIX, TOKENS
from .association import (STRUCTURAL, Association, Problem, associate, check_against_manifest, index_eng,
                          index_eng_by_text, sheet_key)
from .errors import SheetsStructureError
from .inspect import inspect_spreadsheet
from .settings import SheetsConfig, load_sheets_config
from .table import a1_cell, load_table
from .xlsx import XlsxWorkbook, missing_tab_message, suggest_tab

MARKER_KINDS = (TOKENS, PREFIX, NEWLINES)


def register(commands) -> None:
    xlsx = commands.add_parser("xlsx", help="Traducciones desde Multidioma.xlsx (descargado de Google Sheets).")
    xlsx.add_argument("--sheets-config", help="Otra configuración de la hoja (por defecto, config/sheets.json).")
    sub = xlsx.add_subparsers(dest="xlsx_command", required=True)

    inspect = sub.add_parser("inspect", help="Describe pestañas, cabeceras y fórmulas del .xlsx.")
    inspect.add_argument("--xlsx", help="Ruta del .xlsx (por defecto, xlsx_file de config/sheets.json).")

    export = sub.add_parser("export", help="Genera las filas KEY/TEXT para la pestaña ENG de la hoja.")
    export.add_argument("manifest")
    export.add_argument("--xlsx", help="Compara con este .xlsx y genera solo las filas que faltan.")

    languages = sub.add_parser("languages", help="Idiomas configurados y si su pestaña existe en el .xlsx.")
    languages.add_argument("--xlsx")

    build = sub.add_parser("build", help="Genera los info.json de cada idioma desde el .xlsx.")
    build.add_argument("manifest")
    build.add_argument("--xlsx")
    build.add_argument("--lang", help="Idiomas separados por comas (por defecto, todos los habilitados).")


def run(args, settings: Settings) -> int:
    config = load_sheets_config(settings.key_column, settings.text_column, file=args.sheets_config, xlsx_file=args.xlsx)
    handlers = {"inspect": _inspect, "export": _export, "build": _build, "languages": _languages}
    return handlers[args.xlsx_command](args, settings, config)


def _languages(args, settings: Settings, config: SheetsConfig) -> int:
    """Estado de los idiomas: los habilitados sin pestaña harían fallar `build`."""
    languages = load_languages(settings.languages_file)
    tabs = XlsxWorkbook(config.xlsx_file).tabs() if config.xlsx_file else None
    print(f"{'código':9s} {'nombre':22s} {'pestaña':9s} {'carpeta':9s} {'estado':14s} {'en el .xlsx' if tabs is not None else ''}")
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
            print(f"Pestañas del .xlsx sin idioma configurado: {', '.join(extra)}")
        if blocking:
            print(f"ERROR: habilitados sin pestaña en el .xlsx: {', '.join(blocking)}. 'xlsx build' fallaría para ellos.")
    print(f"{len(languages.enabled)} de {len(languages.items)} idiomas habilitados. Para añadir uno, pon "
          "\"enabled\": true en config/languages.json cuando su pestaña exista en la hoja.")
    return 1 if blocking else 0


def _inspect(args, settings: Settings, config: SheetsConfig) -> int:
    languages = load_languages(settings.languages_file)
    workbook = XlsxWorkbook(config.require_xlsx())
    report = inspect_spreadsheet(workbook, config, languages.enabled, languages.get(languages.source))
    report = {"file": str(workbook.file.resolve()), "sha256": workbook.sha256, **report}
    target = settings.output_root / "xlsx-inspect.json"
    write_json(target, report)
    print(json.dumps({k: v for k, v in report.items() if k != "recommendations"}, ensure_ascii=False, indent=2))
    for tip in report["recommendations"]:
        print(f"- {tip}")
    print(f"\nInforme: {target}")
    return 0


def _game(manifest: Dict, manifest_file: FilePath) -> str:
    return manifest.get("game") or manifest_file.resolve().parent.name


def _eng_index(workbook: XlsxWorkbook, config: SheetsConfig, source: Language, game: str, units):
    if not source.tab or source.tab not in workbook.tabs():
        raise SheetsStructureError("Pestaña de origen: " + missing_tab_message(workbook.file.name, source.tab, workbook.tabs()))
    table = load_table(workbook, source.tab, config.header_row)
    letter = config.text_column_for(source.tab)
    if config.association == "text":
        return index_eng_by_text(table, units, config.text_header_for(source.tab), letter)
    eng = index_eng(table, config.key_header_for(source.tab), config.text_header_for(source.tab), game, letter)
    if eng.key_col is None:
        raise SheetsStructureError(
            f"La pestaña {source.tab} no tiene la columna '{config.key_header_for(source.tab)}', así que sus textos no "
            "se pueden relacionar con la plantilla sin adivinar. Pega en ENG las columnas KEY y TEXT de "
            "eng-sheet.csv (translateml xlsx export) y vuelve a descargar el archivo.")
    return eng


def _export(args, settings: Settings, config: SheetsConfig) -> int:
    manifest_file = FilePath(args.manifest)
    manifest, _, _, units = load_manifest_template(manifest_file, settings)
    game = _game(manifest, manifest_file)
    out = manifest_file.parent
    key_header, text_header = settings.key_column, settings.text_column
    _write_rows(out / "eng-sheet.csv", key_header, text_header, [(sheet_key(game, u.key), u.text) for u in units])
    print(f"{len(units)} textos -> {out / 'eng-sheet.csv'} (columnas {key_header}, {text_header}; "
          "la clave la gestiona el programa y Data no debe editarla)")
    if config.xlsx_file is None:
        return 0

    workbook = XlsxWorkbook(config.xlsx_file)
    languages = load_languages(settings.languages_file)
    eng = _eng_index(workbook, config, languages.get(languages.source), game, units)
    new = [u for u in units if u.key not in eng.rows and u.key not in eng.duplicates]
    changed = [{"key": sheet_key(game, u.key), "cell": f"{eng.table.title}!{_cell(eng, u.key)}",
                "sheet": eng.texts[u.key], "template": u.text}
               for u in units if u.key in eng.rows and eng.texts[u.key] != u.text]
    manifest_keys = {u.key for u in units}
    obsolete = [{"key": sheet_key(game, k), "cell": f"{eng.table.title}!{_cell(eng, k)}", "text": eng.texts[k]}
                for k in eng.rows if k not in manifest_keys]
    _write_rows(out / "eng-new-rows.csv", key_header, text_header, [(sheet_key(game, u.key), u.text) for u in new])
    report = {"xlsx": str(workbook.file.resolve()), "new": [sheet_key(game, u.key) for u in new], "changed": changed,
              "obsolete": obsolete, "problems": [vars(p) for p in eng.problems]}
    write_json(out / "eng-sheet-report.json", report)
    print(f"Comparado con {workbook.file.name}: {len(new)} nuevos (eng-new-rows.csv, para añadir al final de ENG sin "
          f"mover filas), {len(changed)} con inglés distinto, {len(obsolete)} obsoletos, {len(eng.problems)} problemas. "
          f"Detalle: {out / 'eng-sheet-report.json'}")
    return 1 if any(p.kind in STRUCTURAL for p in eng.problems) else 0


def _cell(eng, key: str) -> str:
    return a1_cell(eng.rows[key], eng.text_col)


def _write_rows(file: FilePath, key_header: str, text_header: str, rows) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([key_header, text_header])
        writer.writerows(rows)


def _build(args, settings: Settings, config: SheetsConfig) -> int:
    return build(FilePath(args.manifest), settings, config, args.lang)


def build(manifest_file: FilePath, settings: Settings, config: SheetsConfig, lang=None) -> int:
    """Asocia las traducciones del .xlsx con el manifest y genera <idioma>/info.json con su informe."""
    manifest, template, profile, units = load_manifest_template(manifest_file, settings)
    game = _game(manifest, manifest_file)
    out = manifest_file.parent
    languages = load_languages(settings.languages_file)
    source = languages.get(languages.source)
    targets = _target_languages(lang, settings)
    workbook = XlsxWorkbook(config.require_xlsx())
    eng = _eng_index(workbook, config, source, game, units)
    tabs = workbook.tabs()

    report: Dict = {
        "status": "ok",
        "xlsx": {"file": str(workbook.file.resolve()), "sha256": workbook.sha256},
        "template": str(template.file), "game": game, "association": config.association,
        "extracted_texts": len(units),
        "pending_review": _pending_review(out),
        "eng_problems": [vars(p) for p in eng.problems],
        "languages": {},
    }
    for problem in eng.problems:
        print(f"  {'!' if problem.kind in STRUCTURAL else '~'} {problem.cell or ''} {problem.key or ''}: "
              f"{problem.kind} - {problem.detail}")
    failed = False
    for language in targets:
        if language.code == source.code:
            entry = _build_source(template, profile, units, eng, language, settings, out)
        elif not language.tab or language.tab not in tabs:
            entry = {"tab": language.tab, "status": "error",
                     "errors": [missing_tab_message(workbook.file.name, language.tab, tabs)
                                + f" No se asocia ninguna traducción de {language.code}."]}
        else:
            entry = _build_translation(workbook, template, profile, units, eng, language, config, settings, out, game)
        report["languages"][language.code] = entry
        failed |= entry["status"] != "generated"
        _print_entry(language, entry)

    report["status"] = "error" if failed else ("warnings" if any(
        e.get("missing") or e.get("marker_issues") or e.get("problems") or e.get("same_as_english")
        for e in report["languages"].values()) else "ok")
    target = out / "xlsx-build-report.json"
    write_json(target, report)
    print(f"Estado: {report['status']}. Informe: {target}")
    return 1 if failed else 0


def _build_source(template, profile, units, eng, language: Language, settings: Settings, out: FilePath) -> Dict:
    """El idioma de origen es la plantilla tal cual; se informa si ENG del .xlsx difiere de ella."""
    code, rebuilt = build_language(template, profile, units, {u.key: u.text for u in units}, language, settings, out,
                                   quiet=True)
    _, problems = check_against_manifest(units, eng, Association(eng.table.title))
    differences = [vars(p) for p in problems if p.kind not in ("missing", "not_in_sheet")]
    return {"tab": language.tab, "status": "generated" if code == 0 else "error", "output": rebuilt["output"],
            "applied": 0, "missing": [], "marker_issues": [], "problems": differences,
            "errors": rebuilt["validation_errors"]}


def _build_translation(workbook, template, profile, units, eng, language: Language, config: SheetsConfig,
                       settings: Settings, out: FilePath, game: str) -> Dict:
    try:
        table = load_table(workbook, language.tab, config.header_row)
        association = associate(table, eng, game, config.key_header_for(language.tab),
                                config.text_header_for(language.tab), config.positional_fallback,
                                config.text_column_for(language.tab))
    except SheetsStructureError as exc:
        return {"tab": language.tab, "status": "error", "errors": [str(exc)]}
    usable, problems = check_against_manifest(units, eng, association)
    all_problems: List[Problem] = association.problems + problems
    structural = [p for p in eng.problems + all_problems if p.kind in STRUCTURAL]
    entry: Dict = {"tab": language.tab, "association": dict(association.methods),
                   "problems": [vars(p) for p in all_problems if p.kind not in ("missing", "not_in_sheet")]}
    if association.methods.get("position"):
        entry["warning"] = (f"{association.methods['position']} traducciones asociadas por posición "
                            "(positional_fallback activado).")
    if structural:
        entry.update(status="error", errors=[f"{p.kind}: {p.cell or p.key or ''} {p.detail}" for p in structural])
        return entry
    code, rebuilt = build_language(template, profile, units, usable, language, settings, out, quiet=True)
    rejected = {i["key"] for i in rebuilt["issues"] if i["blocking"] and i["kind"] != "missing"}
    applied = {k: v for k, v in usable.items() if k not in rejected}
    write_texts_csv(out / "sheets" / f"{language.code}.csv", applied, settings.key_column, settings.text_column)
    source_text = {u.key: u.text for u in units}
    entry.update(status="generated" if code == 0 else "error", output=rebuilt["output"], applied=len(applied),
                 same_as_english=[k for k, v in sorted(applied.items()) if v == source_text[k]],
                 missing=[u.key for u in units if u.key not in applied],
                 marker_issues=[i for i in rebuilt["issues"] if i["kind"] in MARKER_KINDS],
                 errors=rebuilt["validation_errors"])
    return entry


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


def _target_languages(codes, settings: Settings) -> List[Language]:
    languages = load_languages(settings.languages_file)
    if codes:
        return [enabled_language(settings, code.strip()) for code in codes.split(",") if code.strip()]
    if not languages.enabled:
        raise ConfigError("No hay idiomas habilitados en languages.json.")
    return languages.enabled
