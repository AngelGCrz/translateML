"""Asociación entre las filas de la hoja y las claves internas del manifest.

Cada fila de ENG se relaciona con las claves de la plantilla de una de dos formas
(`association` en config/sheets.json):
- "key": una columna de clave generada por el programa ("g490:T0001", ver `xlsx export`);
- "text": el texto inglés exacto de la fila. Un texto repetido en la plantilla ("GAME RULES")
  recibe la misma traducción en todas sus ubicaciones. Una frase que en la plantilla ocupa varias
  líneas seguidas se asocia a todas ellas (en la celda puede ir en una sola línea o con saltos de
  línea en los mismos puntos). Su traducción se reparte por sus propios saltos de línea si tiene los
  mismos; si no, la frase completa va en la primera línea y las continuaciones se eliminan. Nunca se
  corta por longitud. Las filas sin coincidencia exacta se informan y no se usan.
Las pestañas de traducción se asocian con las filas de ENG, por orden de preferencia:
  1. por su propia columna de clave, si existe;
  2. por la referencia de su fórmula a ENG (=GOOGLETRANSLATE(ENG!B5; ...) -> fila 5 de ENG),
     incluidas fórmulas matriciales sobre un rango (ENG!B2:B) y la forma en que Google Sheets
     exporta sus funciones (__xludf.DUMMYFUNCTION("GOOGLETRANSLATE(ENG!B5,...)"));
  3. por posición (misma fila que en ENG) solo si positional_fallback está activado
     explícitamente; si no, una celda sin referencia es un error, nunca una suposición.
Se descarta cualquier asociación ambigua: una clave repetida o dos filas con traducciones distintas
para el mismo texto.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ..extraction.extractor import TextUnit
from ..jsonpath import format_path
from .table import Table, cell_name, column_index, is_error_value, references, required_column

KEY_SEPARATOR = ":"
_KEY = re.compile(r"^T\d{4,}$")
# Problemas que hacen que la asociación de toda la pestaña no sea fiable.
STRUCTURAL = {"duplicate_key", "invalid_key", "ambiguous", "no_cached_value"}
MAX_SENTENCE_LINES = 4


def sheet_key(game: str, key: str) -> str:
    return f"{game}{KEY_SEPARATOR}{key}"


@dataclass
class Problem:
    kind: str
    detail: str
    key: Optional[str] = None
    cell: Optional[str] = None
    blocking: bool = True  # True: esa clave no se usa


@dataclass
class EngIndex:
    """Filas de ENG que pertenecen a este juego, por clave interna (sin el prefijo del juego)."""
    table: Table
    key_col: Optional[int]
    text_col: int
    rows: Dict[str, int] = field(default_factory=dict)
    texts: Dict[str, str] = field(default_factory=dict)
    keys_by_row: Dict[int, List[str]] = field(default_factory=dict)
    # Frases de varias líneas: fila -> grupos de claves (una por línea de la plantilla, en orden).
    line_groups: Dict[int, List[List[str]]] = field(default_factory=dict)
    mode: str = "key"
    unkeyed_rows: List[int] = field(default_factory=list)  # filas con texto y sin clave
    other_games: int = 0
    duplicates: Set[str] = field(default_factory=set)
    problems: List[Problem] = field(default_factory=list)


def text_column(table: Table, header: str, letter: Optional[str]) -> int:
    """Columna de texto por letra configurada (hojas sin cabeceras) o por nombre de cabecera."""
    return column_index(letter) if letter else required_column(table, header)


def index_eng(table: Table, key_header: str, text_header: str, game: str, text_letter: Optional[str] = None) -> EngIndex:
    index = EngIndex(table, table.column(key_header), text_column(table, text_header, text_letter))
    prefix = sheet_key(game, "")
    seen: Dict[str, List[int]] = {}
    for row in table.data_rows():
        raw = table.value(row, index.key_col).strip() if index.key_col is not None else ""
        if not raw:
            if table.value(row, index.text_col).strip():
                index.unkeyed_rows.append(row)
            continue
        if not raw.startswith(prefix):
            index.other_games += 1
            continue
        key = raw[len(prefix):]
        if not _KEY.match(key):
            index.problems.append(Problem("invalid_key", f"clave con formato no válido: {raw!r}",
                                          cell=cell_name(table, row, index.key_col)))
            continue
        seen.setdefault(key, []).append(row)
    for key, rows in seen.items():
        if len(rows) > 1:
            cells = ", ".join(cell_name(table, r, index.key_col) for r in rows)
            index.problems.append(Problem("duplicate_key", f"la clave {sheet_key(game, key)} aparece en {cells}", key))
            index.duplicates.add(key)
            continue
        index.rows[key] = rows[0]
        index.texts[key] = table.value(rows[0], index.text_col)
        index.keys_by_row[rows[0]] = [key]
    return index


def index_eng_by_text(table: Table, units: List[TextUnit], text_header: str, text_letter: Optional[str]) -> EngIndex:
    """Relaciona cada fila de ENG con las claves cuyo texto editable es idéntico.

    Se ignoran los espacios al principio y al final de la celda: en la plantilla forman parte de la
    sangría o del sufijo protegido, que el programa restaura, no del texto que traduce Data.
    Primero se asignan las filas que coinciden con una línea; después, las frases de varias líneas
    cuyas líneas no tengan ya fila propia (una línea nunca recibe dos traducciones distintas).
    """
    index = EngIndex(table, None, text_column(table, text_header, text_letter), mode="text")
    by_text: Dict[str, List[TextUnit]] = {}
    for unit in units:
        by_text.setdefault(unit.text, []).append(unit)
    pending = []
    for row in table.data_rows():
        text = table.value(row, index.text_col).strip()
        if not text:
            continue
        matches = by_text.get(text)
        if not matches:
            pending.append((row, text))
            continue
        index.keys_by_row[row] = [u.key for u in matches]
        for unit in matches:
            index.rows.setdefault(unit.key, row)
            index.texts[unit.key] = text
    exact = set(index.rows)

    for row, text in pending:
        where = cell_name(table, row, index.text_col)
        lines = split_lines(text)
        if len(lines) > 1:
            groups = [g for g in _consecutive_groups(units, len(lines)) if [u.text for u in g] == lines]
        else:
            groups = _spanning_groups(units, text)
        free = [g for g in groups if not any(u.key in exact for u in g)]
        if free:
            index.line_groups[row] = [[u.key for u in g] for g in free]
            for group in free:
                for unit in group:
                    index.rows.setdefault(unit.key, row)
                    index.texts[unit.key] = unit.text
        elif groups:
            taken = sorted({u.key for g in groups for u in g if u.key in exact})
            index.problems.append(Problem(
                "sentence_overlaps_rows", f"la frase ocupa varias líneas de la plantilla, pero {', '.join(taken)} ya "
                "tiene su propia fila en la hoja; se usa esa fila y esta no", cell=where, blocking=False))
        elif len(lines) > 1:
            index.problems.append(Problem(
                "not_in_template", f"las {len(lines)} líneas de la celda no coinciden con líneas consecutivas de la "
                f"plantilla: {' ⏎ '.join(lines)!r}", cell=where, blocking=False))
        else:
            index.problems.append(Problem("not_in_template", f"ningún texto de la plantilla es exactamente {text!r}",
                                          cell=where, blocking=False))
    index.problems.sort(key=lambda p: (len(p.cell or ""), p.cell or ""))
    return index


def split_lines(text: str) -> List[str]:
    """Trozos de una celda separados por saltos de línea, sin espacios exteriores ni trozos vacíos."""
    return [part.strip() for part in re.split(r"\r?\n", text) if part.strip()]


def _consecutive_groups(units: List[TextUnit], size: int):
    """Grupos de `size` líneas seguidas de una misma lista de la plantilla (p. ej. items.lines)."""
    for start in range(len(units) - size + 1):
        group = units[start:start + size]
        if len({u.path[:-1] for u in group}) == 1:
            yield group


def _spanning_groups(units: List[TextUnit], text: str) -> List[List[TextUnit]]:
    """Grupos de líneas consecutivas de una misma lista cuyo texto unido con un espacio es `text`."""
    for size in range(2, MAX_SENTENCE_LINES + 1):
        groups = [g for g in _consecutive_groups(units, size) if " ".join(u.text for u in g) == text]
        if groups:
            return groups
    return []


@dataclass
class Association:
    tab: str
    texts: Dict[str, str] = field(default_factory=dict)
    cells: Dict[str, str] = field(default_factory=dict)
    methods: Counter = field(default_factory=Counter)
    problems: List[Problem] = field(default_factory=list)
    # Frases unidas: clave de la primera línea -> claves de las líneas de continuación que se eliminan.
    merges: Dict[str, List[str]] = field(default_factory=dict)


def associate(table: Table, eng: EngIndex, game: str, key_header: str, text_header: str,
              positional_fallback: bool, text_letter: Optional[str] = None) -> Association:
    """Traducciones de una pestaña (valores calculados) por clave interna."""
    result = Association(table.title)
    text_col = text_column(table, text_header, text_letter)
    key_col = table.column(key_header) if eng.mode == "key" else None
    prefix = sheet_key(game, "")
    found: Dict[str, List[Tuple[int, str]]] = {}
    array: Optional[Tuple[int, int, Optional[int]]] = None  # (fila ancla, fila inicial en ENG, fila final)

    for row in table.data_rows():
        value = table.value(row, text_col)
        where = cell_name(table, row, text_col)
        if key_col is not None:
            raw = table.value(row, key_col).strip()
            if not raw.startswith(prefix):
                if not raw and value.strip():
                    result.problems.append(Problem("no_key", "texto sin clave en esta pestaña", cell=where, blocking=False))
                continue
            key, method = raw[len(prefix):], "key"
            if key not in eng.rows:
                result.problems.append(Problem("unknown_key", f"la clave {raw} no existe en {eng.table.title}", key, where))
                continue
        else:
            eng_row, method, detail, array = _source_row(table, row, text_col, eng, array, positional_fallback)
            if eng_row is None:
                if value.strip():
                    result.problems.append(Problem("unlinked", detail, cell=where))
                continue
            groups = eng.line_groups.get(eng_row)
            if groups:
                _split_translation(table, row, text_col, value, groups, found, result)
                result.methods[method] += 1
                continue
            keys = eng.keys_by_row.get(eng_row)
            if not keys:
                continue  # fila de ENG que no corresponde a ningún texto de la plantilla
            for key in keys:
                found.setdefault(key, []).append((row, value))
            result.methods[method] += 1
            continue
        found.setdefault(key, []).append((row, value))
        result.methods[method] += 1

    formulas = sum(1 for row in table.data_rows() if table.is_formula(row, text_col))
    unsaved = sum(1 for row, col in table.uncached if col == text_col and row > table.header_row)
    if formulas and unsaved == formulas:
        result.problems.append(Problem(
            "no_cached_value", f"ninguna de las {formulas} fórmulas de {table.title} tiene valor guardado. openpyxl no "
            "calcula fórmulas: vuelve a descargar el archivo desde Google Sheets (Archivo > Descargar > .xlsx) "
            "cuando hayan terminado de calcularse", cell=table.title))

    for key, rows in found.items():
        if len({value for _, value in rows}) > 1:
            cells = ", ".join(cell_name(table, r, text_col) for r, _ in rows)
            result.problems.append(Problem("ambiguous", f"varias filas con traducciones distintas para el mismo texto: {cells}", key))
            continue
        row, value = rows[0]
        where = cell_name(table, row, text_col)
        if (row, text_col) in table.uncached:
            # openpyxl no distingue "sin valor guardado" de "resultado vacío": se trata como faltante.
            result.problems.append(Problem("empty_formula_result",
                                           "la fórmula no tiene valor guardado o su resultado está vacío", key, where))
        elif is_error_value(value):
            result.problems.append(Problem("formula_error", f"la celda muestra {value.strip()!r}", key, where))
        elif value and not value.strip():
            result.problems.append(Problem("whitespace_only", "la traducción solo contiene espacios", key, where))
        elif value:
            result.texts[key] = value
            result.cells[key] = where
    return result


def _split_translation(table: Table, row: int, col: int, value: str, groups: List[List[str]],
                       found: Dict[str, List[Tuple[int, str]]], result: "Association") -> None:
    """Reparte la traducción de una frase de varias líneas.

    Con los mismos saltos de línea que la plantilla, cada trozo va a su línea. Si no, la frase completa
    va en la primera línea y las continuaciones se eliminan (`merges`); nunca se corta por longitud.
    """
    keys = [key for group in groups for key in group]
    if (row, col) in table.uncached or is_error_value(value) or not value.strip():
        for key in keys:  # vacía o con error: se informa por clave en la comprobación general
            found.setdefault(key, []).append((row, value))
        return
    parts = split_lines(value)
    for group in groups:
        if len(parts) == len(group):
            for key, part in zip(group, parts):
                found.setdefault(key, []).append((row, part))
        else:
            found.setdefault(group[0], []).append((row, " ".join(parts)))
            result.merges[group[0]] = group[1:]


def _source_row(table: Table, row: int, col: int, eng: EngIndex, array, positional_fallback: bool):
    """Fila de ENG de la que procede la celda. Devuelve (fila, método, detalle, estado matricial)."""
    eng_tab = eng.table.title
    formula = table.formula(row, col)
    if formula.startswith("="):
        refs = references(formula, eng_tab)
        if len(refs) > 1:
            return None, "formula", f"la fórmula referencia varias celdas de {eng_tab}: {formula}", None
        if len(refs) == 1:
            ref = refs[0]
            if ref.col != eng.text_col or ref.row is None:
                return None, "formula", f"la fórmula no usa la columna de texto de {eng_tab}: {formula}", None
            if ref.is_range:
                return ref.row, "array_formula", "", (row, ref.row, ref.end_row)
            return ref.row, "formula", "", None
    if array is not None:
        anchor, start, end = array
        eng_row = start + (row - anchor)
        if end is None or eng_row <= end:
            return eng_row, "array_formula", "", array
    if positional_fallback:
        return row, "position", "", None
    return None, "position", (f"no se puede saber a qué texto de {eng_tab} corresponde: la celda no tiene fórmula "
                              f"que referencie {eng_tab}. Añade una columna de clave en esta pestaña o, si sus filas "
                              f"coinciden siempre con {eng_tab}, activa positional_fallback en config/sheets.json"), None


def check_against_manifest(units: List[TextUnit], eng: EngIndex, association: Association):
    """Traducciones utilizables y problemas: textos sin sincronizar, faltantes u obsoletos."""
    usable: Dict[str, str] = {}
    problems: List[Problem] = []
    manifest_keys = {u.key for u in units}
    continuation = {key: first for first, rest in association.merges.items() for key in rest}
    for unit in units:
        if unit.key in continuation:
            if continuation[unit.key] not in association.texts:
                problems.append(Problem("missing", "sin traducción", unit.key))
            continue  # la cubre la traducción completa de la primera línea
        if unit.key in eng.duplicates:
            problems.append(Problem("duplicate_key", f"la clave está repetida en {eng.table.title}", unit.key))
        elif unit.key not in eng.rows:
            hint = "añádelo desde eng-new-rows.csv ('xlsx export')" if eng.mode == "key" else "ninguna fila tiene este texto exacto"
            problems.append(Problem("not_in_sheet", f"{eng.table.title}: {hint}", unit.key))
        elif eng.texts[unit.key] != unit.text:
            cell = cell_name(eng.table, eng.rows[unit.key], eng.text_col)
            problems.append(Problem("eng_out_of_sync",
                                    f"el inglés de {cell} no coincide con la plantilla; la traducción podría ser de otro texto",
                                    unit.key, cell))
        elif unit.key not in association.texts:
            problems.append(Problem("missing", "sin traducción", unit.key))
        else:
            usable[unit.key] = association.texts[unit.key]
    for key in sorted(set(association.texts) - manifest_keys):
        problems.append(Problem("obsolete", "traducción de un texto que ya no está en la plantilla", key,
                                association.cells.get(key), blocking=False))
    return usable, problems

