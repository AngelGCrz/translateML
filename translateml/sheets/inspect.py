"""Inspección de la estructura real de Multidioma.xlsx (solo lectura).

Responde a lo necesario antes de generar: qué pestañas y cabeceras existen, si hay columna
de clave, si las fórmulas tienen su valor guardado y cómo obtiene cada pestaña de traducción
su texto de ENG (misma fila, otra fila, rango matricial o sin referencia).
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List

from ..config import Language
from .settings import SheetsConfig
from .table import Table, column_index, column_letter, load_table, references


def inspect_spreadsheet(workbook, config: SheetsConfig, languages: List[Language], source: Language) -> Dict:
    tabs = workbook.tabs()
    report: Dict = {"tabs": list(tabs), "languages": {}, "recommendations": []}
    eng = None
    if source.tab in tabs:
        eng = load_table(workbook, source.tab, config.header_row)
        report["languages"][source.code] = _describe(eng, config, source.tab)
    else:
        report["recommendations"].append(f"Falta la pestaña de origen {source.tab}.")
    for language in languages:
        if language.code == source.code:
            continue
        if language.tab not in tabs:
            report["languages"][language.code] = {"tab": language.tab, "exists": False}
            report["recommendations"].append(f"Falta la pestaña {language.tab} ({language.code}).")
            continue
        table = load_table(workbook, language.tab, config.header_row)
        info = _describe(table, config, language.tab)
        if eng is not None and info["text_column"] is not None and _text_col(eng, config, source.tab) is not None:
            info["formulas"] = _formula_links(table, _text_col(table, config, language.tab),
                                              eng, _text_col(eng, config, source.tab))
        report["languages"][language.code] = info
    report["recommendations"] += _recommend(report, config, source)
    return report


def _text_col(table: Table, config: SheetsConfig, tab: str):
    letter = config.text_column_for(tab)
    return column_index(letter) if letter else table.column(config.text_header_for(tab))


def _describe(table: Table, config: SheetsConfig, tab: str) -> Dict:
    key_col = table.column(config.key_header_for(tab))
    text_col = _text_col(table, config, tab)
    rows = list(table.data_rows())
    return {
        "tab": tab, "exists": True,
        "headers": {h: column_letter(c) for h, c in sorted(table.headers.items(), key=lambda i: i[1])},
        "key_column": column_letter(key_col) if key_col is not None else None,
        "text_column": column_letter(text_col) if text_col is not None else None,
        "data_rows": len(rows), "last_row": table.last_row,
        "non_empty_texts": sum(1 for r in rows if text_col is not None and table.value(r, text_col).strip()),
        "formulas_without_saved_value": len(table.uncached),
    }


def _formula_links(table: Table, col: int, eng: Table, eng_text_col) -> Dict:
    """Cómo se relaciona cada celda de traducción con ENG."""
    kinds: Counter = Counter()
    samples: Dict[str, List[str]] = {}
    for row in table.data_rows():
        formula = table.formula(row, col)
        if not formula.strip():
            kind = "empty"
        elif not formula.startswith("="):
            kind = "static_value"
        else:
            refs = references(formula, eng.title)
            if not refs:
                kind = "formula_without_eng_reference"
            elif len(refs) > 1:
                kind = "formula_multiple_eng_references"
            elif refs[0].is_range:
                kind = "array_formula_over_eng_range"
            elif refs[0].col != eng_text_col:
                kind = "formula_other_eng_column"
            elif refs[0].row == row:
                kind = "formula_same_row"
            else:
                kind = "formula_other_row"
        kinds[kind] += 1
        if kind != "empty" and len(samples.setdefault(kind, [])) < 3:
            samples[kind].append(f"{column_letter(col)}{row}: {formula[:120]}")
    return {"counts": dict(kinds), "samples": samples}


def _recommend(report: Dict, config: SheetsConfig, source: Language) -> List[str]:
    tips = []
    eng = report["languages"].get(source.code, {})
    if eng.get("exists") and eng.get("text_column") is None:
        tips.append(f"{source.tab} no tiene la columna '{config.text_header_for(source.tab)}'. Configura "
                    "text_header (o header_row 0 y text_column si la hoja no tiene cabeceras) en config/sheets.json.")
    if eng.get("exists") and eng.get("key_column") is None and config.association == "key":
        tips.append(f"{source.tab} no tiene columna '{config.key_header}': las traducciones no se pueden asociar con la "
                    "plantilla. Importa en ENG las columnas KEY y TEXT de eng-sheet.csv ('xlsx export').")
    for code, info in report["languages"].items():
        counts = info.get("formulas", {}).get("counts", {})
        if counts.get("formula_other_row"):
            tips.append(f"{info['tab']}: hay fórmulas que apuntan a otra fila de {source.tab}; se asociarán por la "
                        "referencia de la fórmula, no por posición.")
        if (counts.get("static_value") or counts.get("formula_without_eng_reference")) and info.get("key_column") is None \
                and config.association == "key":
            how = ("se asociarán por posición (misma fila) porque positional_fallback está activado"
                   if config.positional_fallback else
                   "no se pueden asociar: añade una columna "
                   f"'{config.key_header}' en {info['tab']} o activa positional_fallback si sus filas coinciden con {source.tab}")
            tips.append(f"{info['tab']}: hay valores sin referencia a {source.tab}; {how}.")
        if info.get("formulas_without_saved_value"):
            tips.append(f"{info['tab']}: {info['formulas_without_saved_value']} fórmulas sin valor guardado. openpyxl no "
                        "calcula fórmulas: vuelve a descargar el .xlsx desde Google Sheets cuando hayan terminado de "
                        "calcularse.")
    return tips
