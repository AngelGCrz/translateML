"""Lectura de solo lectura de un .docx multidioma descargado de Google Docs (multidioma.docx).

Google Docs exporta cada pestaña del documento como una sección de Word, en el mismo orden, pero
no guarda el nombre de la pestaña. Cada sección recibe el nombre que le toca por orden (ver
sources.py); si el número de secciones no coincide con el de nombres es un error: nunca se adivina
qué sección es qué idioma.

Cada sección se presenta como una pestaña de una sola columna (A), para reutilizar la asociación
de la hoja de cálculo por texto (LAYOUT):
- cada celda de tabla es una fila; sus párrafos se unen con saltos de línea, como una celda de hoja
  con varias líneas;
- cada párrafo con texto fuera de las tablas es una fila (DocxOptions.paragraphs);
- una celda que solo es numeración ("1", "2.", "3)") queda vacía (DocxOptions.numbering_pattern).
Las traducciones se relacionan con ENG por posición (misma celda de la misma tabla). Para que no sea
una suposición, cada pestaña debe tener exactamente la misma estructura que la de origen
(`alignment_problem`). El archivo se lee entero en memoria con la biblioteca estándar y no se escribe.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path as FilePath
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .errors import SheetsReadError, SheetsStructureError
from .settings import DocxOptions, TableLayout
from .tabs import missing_tab_message

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_PARAGRAPH, _TABLE, _ROW, _CELL = _W + "p", _W + "tbl", _W + "tr", _W + "tc"
_SECTION_BREAK = f"{_W}pPr/{_W}sectPr"

# Una columna de texto, sin cabeceras, asociada por texto exacto y por posición verificada.
LAYOUT = TableLayout(header_row=0, key_header="", text_header="", association="text", text_column="A",
                     position="verified")


@dataclass
class _Tab:
    """Una sección del documento ya aplanada en filas."""
    rows: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)  # "tabla 2, fila 3, celda 2"
    shape: List[str] = field(default_factory=list)   # descripción de cada bloque, para comparar estructuras

    def add(self, text: str, label: str) -> None:
        self.rows.append(text)
        self.labels.append(label)


class DocxDocument:
    FORMAT = "docx"
    layout = LAYOUT
    # Todas las celdas se relacionan por posición: si la estructura no coincide, no se usa la pestaña.
    position_only = True

    def __init__(self, file, tab_names: Sequence[str], options: DocxOptions = DocxOptions()):
        self.file = FilePath(file)
        self.options = options
        self._numbering = re.compile(options.numbering_pattern) if options.numbering_pattern else None
        body = self._read_body()
        sections = _sections(body)
        names = list(tab_names)
        if len(sections) != len(names):
            raise SheetsStructureError(
                f"{self.file.name} tiene {len(sections)} pestañas (secciones) y hay {len(names)} nombres configurados "
                f"({', '.join(names)}). Google Docs no guarda el nombre de cada pestaña al exportar a .docx, así que se "
                "identifican por orden: indica en config/sheets.json \"docx\": {\"tabs\": [...]} con los nombres en el "
                "orden de las pestañas del documento.")
        self._tabs: Dict[str, _Tab] = {name: self._flatten(blocks) for name, blocks in zip(names, sections)}

    # --- interfaz Source -------------------------------------------------------------------------

    def tabs(self) -> List[str]:
        return list(self._tabs)

    def read(self, tab: str, formulas: bool = False) -> List[List[str]]:
        """Filas de una sola columna. Un .docx no tiene fórmulas: con formulas=True todo es vacío."""
        return [["" if formulas else text] for text in self._tab(tab).rows]

    def missing_values(self, tab: str) -> Set[Tuple[int, int]]:
        return set()

    def labels(self, tab: str) -> List[str]:
        return list(self._tab(tab).labels)

    def alignment_problem(self, tab: str, source_tab: str) -> Optional[str]:
        """Primera diferencia de estructura entre `tab` y la pestaña de origen, o None si son iguales."""
        mine, theirs = self._tab(tab).shape, self._tab(source_tab).shape
        for position, (a, b) in enumerate(zip(mine, theirs), start=1):
            if a != b:
                return f"elemento {position}: {source_tab} tiene {b} y {tab} tiene {a}"
        if len(mine) != len(theirs):
            return f"{source_tab} tiene {len(theirs)} elementos (tablas y párrafos con texto) y {tab} tiene {len(mine)}"
        return None

    # --- lectura ---------------------------------------------------------------------------------

    def _read_body(self):
        if not self.file.is_file():
            raise SheetsReadError(f"No existe el archivo {self.file}.")
        if self.file.suffix.lower() != ".docx":
            raise SheetsReadError(f"{self.file.name} no es un .docx. Descárgalo desde Google Docs con "
                                  "Archivo > Descargar > Microsoft Word (.docx).")
        self.sha256 = hashlib.sha256(self.file.read_bytes()).hexdigest()
        try:
            with zipfile.ZipFile(self.file) as archive:
                body = ET.fromstring(archive.read("word/document.xml")).find(_W + "body")
        except (zipfile.BadZipFile, KeyError, OSError, ET.ParseError) as exc:
            raise SheetsReadError(f"No se pudo leer {self.file.name} como DOCX: {exc}") from exc
        if body is None:
            raise SheetsReadError(f"{self.file.name} no tiene cuerpo de documento.")
        return body

    def _tab(self, tab: str) -> _Tab:
        if tab not in self._tabs:
            raise SheetsStructureError(missing_tab_message(self.file.name, tab, list(self._tabs)))
        return self._tabs[tab]

    def _flatten(self, blocks) -> _Tab:
        tab, tables = _Tab(), 0
        for block in blocks:
            if block.tag == _PARAGRAPH and self.options.paragraphs:
                text = _paragraph_text(block)
                if text.strip():
                    tab.add(text, f"párrafo antes de la tabla {tables + 1}")
                    tab.shape.append("un párrafo")
            elif block.tag == _TABLE:
                tables += 1
                sizes = self._add_table(block, f"tabla {tables}", tab)
                tab.shape.append(f"una tabla de {len(sizes)} filas con {sizes} celdas")
        return tab

    def _add_table(self, table, name: str, tab: _Tab) -> List[int]:
        """Añade cada celda como una fila (y las tablas anidadas detrás). Devuelve las celdas por fila."""
        sizes = []
        for r, row in enumerate(table.findall(_ROW), start=1):
            cells = row.findall(_CELL)
            sizes.append(len(cells))
            for c, cell in enumerate(cells, start=1):
                where = f"{name}, fila {r}, celda {c}"
                tab.add(self._cell_text(cell), where)
                for n, nested in enumerate(cell.findall(_TABLE), start=1):
                    sizes.extend(self._add_table(nested, f"{where}, tabla {n}", tab))
        return sizes

    def _cell_text(self, cell) -> str:
        text = "\n".join(_paragraph_text(p) for p in cell.findall(_PARAGRAPH)).strip("\n")
        return "" if self._numbering and self._numbering.match(text) else text


def _sections(body) -> List[list]:
    """Bloques del cuerpo agrupados por sección (un párrafo con sectPr cierra la suya), sin secciones vacías."""
    sections, current = [], []
    for block in body:
        if block.tag == _W + "sectPr":
            continue
        current.append(block)
        if block.tag == _PARAGRAPH and block.find(_SECTION_BREAK) is not None:
            sections.append(current)
            current = []
    sections.append(current)
    return [s for s in sections if any(b.tag == _TABLE or _paragraph_text(b).strip() for b in s)]


def _paragraph_text(paragraph) -> str:
    parts = []
    for element in paragraph.iter():
        if element.tag == _W + "t":
            parts.append(element.text or "")
        elif element.tag in (_W + "br", _W + "cr"):
            parts.append("\n")
        elif element.tag == _W + "tab":
            parts.append("\t")
    return "".join(parts)
