"""Inspección de la estructura real del archivo de traducciones (solo lectura).

Responde a lo necesario antes de generar: qué pestañas y cabeceras existen, si hay columna
de clave, si las fórmulas tienen su valor guardado, cómo obtiene cada pestaña de traducción
su texto de ENG (misma fila, otra fila, rango matricial o sin referencia) y, en formatos que
se asocian por posición (.docx), si cada pestaña tiene la misma estructura que ENG.
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List

from ..config import Language
from .settings import TableLayout
from .table import Table, column_index, column_letter, load_table, references


def inspect_spreadsheet(workbook, layout: TableLayout, languages: List[Language], source: Language) -> Dict:
    tabs = workbook.tabs()
    report: Dict = {"tabs": list(tabs), "languages": {}, "recommendations": []}
    eng = None
    if source.tab in tabs:
        eng = load_table(workbook, source.tab, layout.header_row)
        report["languages"][source.code] = _describe(eng, layout, source.tab)
    else:
        report["recommendations"].append(f"Falta la pestaña de origen {source.tab}.")
    for language in languages:
        if language.code == source.code:
            continue
        if language.tab not in tabs:
            report["languages"][language.code] = {"tab": language.tab, "exists": False}
            report["recommendations"].append(f"Falta la pestaña {language.tab} ({language.code}).")
            continue
        table = load_table(workbook, language.tab, layout.header_row)
        info = _describe(table, layout, language.tab)
        if layout.position == "verified" and eng is not None:
            info["alignment_problem"] = workbook.alignment_problem(language.tab, source.tab)
        if eng is not None and info["text_column"] is not None and _text_col(eng, layout, source.tab) is not None:
            info["formulas"] = _formula_links(table, _text_col(table, layout, language.tab),
                                              eng, _text_col(eng, layout, source.tab))
        report["languages"][language.code] = info
    report["recommendations"] += _recommend(report, layout, source, getattr(workbook, "position_only", False))
    return report


def _text_col(table: Table, layout: TableLayout, tab: str):
    letter = layout.text_column_for(tab)
    return column_index(letter) if letter else table.column(layout.text_header_for(tab))


def _describe(table: Table, layout: TableLayout, tab: str) -> Dict:
    key_col = table.column(layout.key_header_for(tab))
    text_col = _text_col(table, layout, tab)
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


def _recommend(report: Dict, layout: TableLayout, source: Language, position_only: bool) -> List[str]:
    tips = []
    eng = report["languages"].get(source.code, {})
    if eng.get("exists") and eng.get("text_column") is None:
        tips.append(f"{source.tab} no tiene la columna '{layout.text_header_for(source.tab)}'. Configura "
                    "text_header (o header_row 0 y text_column si la hoja no tiene cabeceras) en config/sheets.json.")
    if eng.get("exists") and eng.get("key_column") is None and layout.association == "key":
        tips.append(f"{source.tab} no tiene columna '{layout.key_header}': las traducciones no se pueden asociar con la "
                    "plantilla. Importa en ENG las columnas KEY y TEXT de eng-sheet.csv ('xlsx export').")
    for code, info in report["languages"].items():
        counts = info.get("formulas", {}).get("counts", {})
        if counts.get("formula_other_row"):
            tips.append(f"{info['tab']}: hay fórmulas que apuntan a otra fila de {source.tab}; se asociarán por la "
                        "referencia de la fórmula, no por posición.")
        problem = info.get("alignment_problem")
        if position_only and problem:
            tips.append(f"{info['tab']}: estructura distinta de {source.tab} ({problem}); ese idioma no se generará.")
        unlinked = counts.get("static_value", 0) + counts.get("formula_without_eng_reference", 0)
        if unlinked and not position_only and not (layout.association == "key" and info.get("key_column")):
            tips.append(f"{info['tab']}: {unlinked} celdas con texto o fórmula sin referencia a {source.tab}; "
                        f"{_position_outcome(layout, problem, info['tab'], source.tab)}.")
        if info.get("formulas_without_saved_value"):
            tips.append(f"{info['tab']}: {info['formulas_without_saved_value']} fórmulas sin valor guardado. openpyxl no "
                        "calcula fórmulas: vuelve a descargar el .xlsx desde Google Sheets cuando hayan terminado de "
                        "calcularse.")
    return tips


def _position_outcome(layout: TableLayout, problem, tab: str, eng_tab: str) -> str:
    if layout.position == "always":
        return "se asociarán por su fila sin comprobar (\"position\": \"always\")"
    if layout.position == "verified" and not problem:
        return f"se asociarán por su fila: {tab} está alineada con {eng_tab}"
    reason = problem or "\"position\" es \"never\""
    return (f"no se usarán ({reason}). Añade una columna '{layout.key_header}' en {tab} o deja sus filas alineadas "
            f"con {eng_tab}")
