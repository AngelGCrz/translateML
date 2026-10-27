"""Generador mínimo de archivos .xlsx para las pruebas.

openpyxl no puede guardar el valor calculado de una fórmula, y eso es justo lo que contiene
un XLSX descargado de Google Sheets. Aquí se escribe el XML directamente:
- texto -> cadena en línea;
- F(formula, valor) -> fórmula con su valor guardado (valor None: sin valor guardado);
- E(valor) -> celda de error (#N/A...).
Las funciones propias de Google se exportan como en Google Sheets:
=IFERROR(__xludf.DUMMYFUNCTION("GOOGLETRANSLATE(ENG!B2,""en"",""es"")"),"Hola").
"""
import zipfile
from collections import namedtuple
from pathlib import Path
from typing import Dict, List
from xml.sax.saxutils import escape

from translateml.sheets.table import column_letter

F = namedtuple("F", "formula value")
E = namedtuple("E", "value")


def google_formula(inner: str, cached: str) -> str:
    """Fórmula tal como la exporta Google Sheets para una función solo de Google."""
    quoted = inner.replace('"', '""')
    return f'=IFERROR(__xludf.DUMMYFUNCTION("{quoted}"),"{cached.replace(chr(34), chr(34) * 2)}")'


def _cell(ref: str, value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, F):
        formula = escape(value.formula[1:] if value.formula.startswith("=") else value.formula)
        if value.value is None:
            return f'<c r="{ref}"><f>{formula}</f></c>'
        return f'<c r="{ref}" t="str"><f>{formula}</f><v>{escape(str(value.value))}</v></c>'
    if isinstance(value, E):
        return f'<c r="{ref}" t="e"><v>{escape(value.value)}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"><v>{value}</v></c>'
    space = ' xml:space="preserve"' if str(value) != str(value).strip() or "\n" in str(value) else ""
    return f'<c r="{ref}" t="inlineStr"><is><t{space}>{escape(str(value))}</t></is></c>'


def _sheet(rows: List[list]) -> str:
    body = []
    for r, row in enumerate(rows, start=1):
        cells = "".join(_cell(f"{column_letter(c)}{r}", v) for c, v in enumerate(row))
        body.append(f'<row r="{r}">{cells}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(body)}</sheetData></worksheet>')


def write_xlsx(file: Path, tabs: Dict[str, List[list]]) -> Path:
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    sheets = "".join(f'<sheet name="{escape(t)}" sheetId="{i}" r:id="rId{i}"/>' for i, t in enumerate(tabs, start=1))
    rels = "".join(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>'
                   for i in range(1, len(tabs) + 1))
    overrides = "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
                        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(tabs) + 1))
    with zipfile.ZipFile(file, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/>'
                         '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                         f'{overrides}</Types>')
        archive.writestr("_rels/.rels",
                         '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{ns}" '
                                            f'xmlns:r="{rel}"><sheets>{sheets}</sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels",
                         '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         f'{rels}</Relationships>')
        for i, rows in enumerate(tabs.values(), start=1):
            archive.writestr(f"xl/worksheets/sheet{i}.xml", _sheet(rows))
    return file
