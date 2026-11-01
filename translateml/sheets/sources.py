"""Archivos de traducciones: interfaz común y elección del lector por extensión.

Cualquier formato se presenta al resto del programa como pestañas con filas de texto (`Source`),
de modo que la asociación con la plantilla (association.py) no sabe de qué archivo vienen.
Para añadir un formato: una clase que cumpla `Source` y una entrada en `READERS`.
"""
from __future__ import annotations

from pathlib import Path as FilePath
from typing import Callable, Dict, List, Optional, Protocol, Set, Tuple

from ..config import Languages
from .docx import DocxDocument
from .errors import SheetsReadError
from .settings import SheetsConfig, TableLayout
from .xlsx import XlsxWorkbook


class Source(Protocol):
    FORMAT: str                 # "xlsx", "docx"
    file: FilePath
    sha256: str
    layout: TableLayout         # cómo interpretar las filas de cada pestaña
    positions_verified: bool    # True si alignment_problem garantiza que la posición es fiable

    def tabs(self) -> List[str]: ...

    def read(self, tab: str, formulas: bool = False) -> List[List[str]]: ...

    def missing_values(self, tab: str) -> Set[Tuple[int, int]]: ...

    def labels(self, tab: str) -> Optional[List[str]]:
        """Ubicación legible de cada fila, o None para usar la referencia de celda (ESP!C5)."""

    def alignment_problem(self, tab: str, source_tab: str) -> Optional[str]:
        """Por qué las filas de `tab` no pueden relacionarse por posición con `source_tab`, o None."""


def _open_xlsx(file: FilePath, config: SheetsConfig, languages: Languages) -> Source:
    return XlsxWorkbook(file, config.xlsx)


def _open_docx(file: FilePath, config: SheetsConfig, languages: Languages) -> Source:
    # Google Docs no exporta el nombre de las pestañas: se nombran por orden.
    names = config.docx.tabs or [language.tab for language in languages.items if language.tab]
    return DocxDocument(file, names, config.docx)


READERS: Dict[str, Callable[[FilePath, SheetsConfig, Languages], Source]] = {
    ".xlsx": _open_xlsx,
    ".xlsm": _open_xlsx,
    ".docx": _open_docx,
}


def open_source(config: SheetsConfig, languages: Languages) -> Source:
    file = config.require_file()
    reader = READERS.get(file.suffix.lower())
    if reader is None:
        raise SheetsReadError(f"{file.name}: formato no admitido. Usa un .xlsx descargado de Google Sheets "
                              "(Archivo > Descargar > Microsoft Excel) o un .docx de Google Docs "
                              "(Archivo > Descargar > Microsoft Word).")
    return reader(file, config, languages)
