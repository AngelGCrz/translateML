"""Libro simulado en memoria con la misma interfaz de lectura que XlsxWorkbook."""
from collections import namedtuple
from typing import Dict, List

from translateml.sheets.errors import SheetsStructureError

# Celda con fórmula: `formula` es lo escrito y `value` lo que Google muestra al calcularla.
F = namedtuple("F", "formula value")


class FakeSheets:
    def __init__(self, tabs: Dict[str, List[list]]):
        self.grid = {title: [list(row) for row in rows] for title, rows in tabs.items()}

    def tabs(self):
        return list(self.grid)

    def missing_values(self, tab):
        return {(r, c) for r, row in enumerate(self.grid[tab], start=1)
                for c, cell in enumerate(row) if isinstance(cell, F) and cell.value is None}

    def read(self, tab, formulas=False):
        if tab not in self.grid:
            raise SheetsStructureError(f"No existe la pestaña {tab}.")
        rows = []
        for row in self.grid[tab]:
            cells = [(c.formula if formulas else (c.value or "")) if isinstance(c, F) else str(c) for c in row]
            while cells and cells[-1] == "":
                cells.pop()  # como XlsxWorkbook: sin celdas vacías finales
            rows.append(cells)
        while rows and not rows[-1]:
            rows.pop()
        return rows

    def column(self, tab, col):
        return [row[col] if col < len(row) else "" for row in self.grid[tab]]
