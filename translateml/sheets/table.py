"""Representación de una pestaña leída: valores calculados, fórmulas y cabeceras."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .errors import SheetsStructureError

# Referencias a otra pestaña: ENG!B5, 'ENG'!$B$5, ENG!B2:B, ENG!B2:B200
_REFERENCE = re.compile(
    r"(?:'((?:[^']|'')+)'|([A-Za-z0-9_]+))!\$?([A-Za-z]{1,3})\$?(\d+)?(?::\$?([A-Za-z]{1,3})\$?(\d+)?)?")
# Valores de error y estados intermedios que Google Sheets muestra en lugar del resultado.
ERROR_VALUES = {"#N/A", "#REF!", "#VALUE!", "#ERROR!", "#NAME?", "#DIV/0!", "#NUM!", "#NULL!", "Loading...", "Cargando..."}


def column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def column_index(letters: str) -> int:
    index = 0
    for char in letters.upper():
        index = index * 26 + ord(char) - 64
    return index - 1


def a1_cell(row: int, col: int) -> str:
    return f"{column_letter(col)}{row}"


@dataclass(frozen=True)
class Reference:
    tab: str
    col: int
    row: Optional[int]          # None en rangos de columna completa (ENG!B:B)
    end_col: Optional[int] = None
    end_row: Optional[int] = None

    @property
    def is_range(self) -> bool:
        return self.end_col is not None


def references(formula: str, tab: str) -> List[Reference]:
    """Referencias de una fórmula a la pestaña `tab` (sin distinguir mayúsculas)."""
    found = []
    for match in _REFERENCE.finditer(formula):
        quoted, plain, col, row, end_col, end_row = match.groups()
        name = quoted.replace("''", "'") if quoted is not None else plain
        if name.lower() != tab.lower():
            continue
        found.append(Reference(name, column_index(col), int(row) if row else None,
                               column_index(end_col) if end_col else None, int(end_row) if end_row else None))
    return found


@dataclass
class Table:
    title: str
    header_row: int
    values: List[List[str]]
    formulas: List[List[str]]
    uncached: Set[Tuple[int, int]] = field(default_factory=set)  # fórmulas sin valor guardado

    def __post_init__(self):
        headers: Dict[str, int] = {}
        for col, name in enumerate(self.row_values(self.header_row)):
            key = name.strip().lower()
            if not key:
                continue
            if key in headers:
                raise SheetsStructureError(f"Pestaña {self.title}: la cabecera '{name.strip()}' está repetida "
                                           f"(columnas {column_letter(headers[key])} y {column_letter(col)}).")
            headers[key] = col
        self.headers = headers

    def column(self, header: str) -> Optional[int]:
        return self.headers.get(header.strip().lower())

    def row_values(self, row: int) -> List[str]:
        return self.values[row - 1] if 0 < row <= len(self.values) else []

    def value(self, row: int, col: int) -> str:
        cells = self.row_values(row)
        return cells[col] if col < len(cells) else ""

    def formula(self, row: int, col: int) -> str:
        """Contenido de la celda tal como se escribió; las fórmulas empiezan por '='."""
        cells = self.formulas[row - 1] if 0 < row <= len(self.formulas) else []
        return cells[col] if col < len(cells) else ""

    def is_formula(self, row: int, col: int) -> bool:
        return self.formula(row, col).startswith("=")

    @property
    def last_row(self) -> int:
        """Última fila con algún contenido (0 si está vacía)."""
        for row in range(max(len(self.values), len(self.formulas)), 0, -1):
            if any(c.strip() for c in self.row_values(row)) or any(
                    c.strip() for c in (self.formulas[row - 1] if row <= len(self.formulas) else [])):
                return row
        return 0

    def data_rows(self) -> range:
        return range(self.header_row + 1, self.last_row + 1)

    @property
    def next_free_column(self) -> int:
        return max(self.headers.values(), default=-1) + 1


def load_table(workbook, tab: str, header_row: int) -> Table:
    return Table(tab, header_row, workbook.read(tab), workbook.read(tab, formulas=True), workbook.missing_values(tab))


def required_column(table: Table, header: str) -> int:
    col = table.column(header)
    if col is None:
        found = ", ".join(repr(h) for h in table.row_values(table.header_row) if h.strip()) or "ninguna"
        raise SheetsStructureError(f"La pestaña {table.title} no tiene la columna '{header}' en la fila "
                                   f"{table.header_row}. Cabeceras encontradas: {found}.")
    return col


def is_error_value(value: str) -> bool:
    return value.strip() in ERROR_VALUES


def cell_name(table: Table, row: int, col: int) -> str:
    return f"{table.title}!{a1_cell(row, col)}"
