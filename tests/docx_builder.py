"""Generador mínimo de archivos .docx para las pruebas, con la forma que exporta Google Docs.

Cada pestaña del documento es una sección de Word (el último párrafo de la sección lleva sectPr) y
el nombre de la pestaña no se guarda. Bloques de una sección:
- str -> párrafo (un "\\n" dentro es un salto de línea w:br);
- lista de filas (listas de celdas) -> tabla; un "\\n" en una celda separa párrafos.
Entre bloques se añaden párrafos vacíos, como en el archivo real.
"""
import zipfile
from pathlib import Path
from typing import List
from xml.sax.saxutils import escape

NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SECT = '<w:sectPr><w:pgSz w:h="16838" w:w="11906"/></w:sectPr>'


def _run(text: str) -> str:
    parts = text.split("\n")
    runs = "<w:br/>".join(f'<w:t xml:space="preserve">{escape(p)}</w:t>' for p in parts)
    return f"<w:r><w:rPr/>{runs}</w:r>" if text else ""


def _paragraph(text: str, last: bool = False) -> str:
    props = f"<w:pPr>{SECT}</w:pPr>" if last else "<w:pPr/>"
    return f"<w:p>{props}{_run(text)}</w:p>"


def _table(rows: List[list]) -> str:
    body = []
    for row in rows:
        cells = "".join("<w:tc><w:tcPr/>" + "".join(_paragraph(p) for p in str(c).split("\n")) + "</w:tc>" for c in row)
        body.append(f"<w:tr>{cells}</w:tr>")
    return f"<w:tbl><w:tblPr/>{''.join(body)}</w:tbl>"


def write_docx(file: Path, sections: List[list]) -> Path:
    body = []
    for s, blocks in enumerate(sections):
        for block in blocks:
            body.append(_paragraph(block) if isinstance(block, str) else _table(block))
            body.append(_paragraph(""))
        if s < len(sections) - 1:
            body.append(_paragraph("", last=True))
    xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{NS}"><w:body>'
           f'{"".join(body)}{SECT}</w:body></w:document>')
    with zipfile.ZipFile(file, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/>'
                         '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                         '</Types>')
        archive.writestr("_rels/.rels",
                         '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                         'Target="word/document.xml"/></Relationships>')
        archive.writestr("word/document.xml", xml)
    return file
