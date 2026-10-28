"""Carga y validación de la plantilla JSON original.

Además de los datos, se guarda el texto exacto del archivo y la posición de cada
literal de cadena. Así la reconstrucción sustituye únicamente esos literales y el
resto del archivo (formato, espacios, orden) queda byte a byte como el original.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path as FilePath
from typing import Any, Dict, Iterable, List, Tuple

from .jsonpath import Path, format_path, get_value

_BOM = b"\xef\xbb\xbf"
_WS = " \t\n\r"
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"', re.DOTALL)
_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_LITERALS = ("true", "false", "null")


class TemplateError(Exception):
    pass


@dataclass
class Template:
    file: FilePath
    text: str
    data: Any
    sha256: str
    bom: bool = False
    string_spans: Dict[Path, Tuple[int, int]] = field(default_factory=dict)
    value_spans: Dict[Path, Tuple[int, int]] = field(default_factory=dict)

    def render(self, replacements: Dict[Path, str], removals: Iterable[Path] = ()) -> str:
        """Texto del archivo con las cadenas indicadas sustituidas y los elementos de lista indicados
        eliminados (con su coma); el resto del archivo queda intacto, byte a byte."""
        unknown = [p for p in replacements if p not in self.string_spans]
        if unknown:
            raise TemplateError("Rutas sin literal de cadena: " + ", ".join(format_path(p) for p in unknown))
        edits: List[Tuple[int, int, str]] = []
        for path, value in replacements.items():
            if value != get_value(self.data, path):
                start, end = self.string_spans[path]
                edits.append((start, end, json.dumps(value, ensure_ascii=False)))
        edits += [(start, end, "") for start, end in self._removal_ranges(set(removals))]
        edits.sort()
        for (_, end, _), (start, _, _) in zip(edits, edits[1:]):
            if start < end:
                raise TemplateError("Cambios superpuestos en la plantilla.")
        parts: List[str] = []
        pos = 0
        for start, end, new in edits:
            parts.append(self.text[pos:start])
            parts.append(new)
            pos = end
        parts.append(self.text[pos:])
        return "".join(parts)

    def _removal_ranges(self, removals) -> List[Tuple[int, int]]:
        """Fragmentos de texto que eliminan cada tramo de elementos consecutivos de una lista."""
        by_parent: Dict[Path, List[int]] = {}
        for path in removals:
            if not path or not isinstance(path[-1], int) or path not in self.value_spans:
                raise TemplateError(f"Solo se pueden eliminar elementos de una lista: {format_path(path)}")
            by_parent.setdefault(path[:-1], []).append(path[-1])
        ranges = []
        for parent, indexes in by_parent.items():
            size = len(get_value(self.data, parent))
            indexes = sorted(set(indexes))
            runs = [[indexes[0], indexes[0]]]
            for index in indexes[1:]:
                if index == runs[-1][1] + 1:
                    runs[-1][1] = index
                else:
                    runs.append([index, index])
            spans = [self.value_spans[parent + (i,)] for i in range(size)]
            for first, last in runs:
                if last < size - 1:      # hasta el inicio del siguiente elemento (incluye la coma)
                    ranges.append((spans[first][0], spans[last + 1][0]))
                elif first > 0:          # al final: desde el fin del elemento anterior (incluye su coma)
                    ranges.append((spans[first - 1][1], spans[last][1]))
                else:                    # la lista entera
                    ranges.append((spans[first][0], spans[last][1]))
        return ranges

    def encode(self, text: str) -> bytes:
        return (_BOM if self.bom else b"") + text.encode("utf-8")


def load_template(file) -> Template:
    file = FilePath(file)
    try:
        raw = file.read_bytes()
    except OSError as exc:
        raise TemplateError(f"No se puede leer la plantilla {file}: {exc}") from exc
    bom = raw.startswith(_BOM)
    try:
        text = raw[len(_BOM):].decode("utf-8") if bom else raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TemplateError(f"La plantilla no está en UTF-8: {exc}") from exc
    data = parse_json(text, str(file))
    if not isinstance(data, (dict, list)):
        raise TemplateError("La plantilla debe contener un objeto o una lista JSON.")
    values = scan_value_spans(text)
    for path, (start, end) in values.items():
        if json.loads(text[start:end]) != get_value(data, path):
            raise TemplateError(f"Posición inconsistente para {format_path(path)}")
    spans = {path: span for path, span in values.items() if isinstance(get_value(data, path), str)}
    return Template(file=file, text=text, data=data, sha256=hashlib.sha256(raw).hexdigest(),
                    bom=bom, string_spans=spans, value_spans=values)


def parse_json(text: str, source: str = "JSON") -> Any:
    """json.loads que además rechaza claves duplicadas (json las perdería en silencio)."""
    def no_duplicates(pairs):
        seen = {}
        for key, value in pairs:
            if key in seen:
                raise TemplateError(f"{source}: clave duplicada {key!r}")
            seen[key] = value
        return seen

    try:
        return json.loads(text, object_pairs_hook=no_duplicates)
    except json.JSONDecodeError as exc:
        raise TemplateError(f"{source}: JSON no válido ({exc})") from exc


def scan_value_spans(text: str) -> Dict[Path, Tuple[int, int]]:
    """Posición (inicio, fin) de cada valor del JSON (objetos, listas y escalares), indexado por ruta."""
    spans: Dict[Path, Tuple[int, int]] = {}
    try:
        end = _scan_value(text, _skip(text, 0), (), spans)
    except (IndexError, ValueError) as exc:
        raise TemplateError(f"No se pudo analizar la posición de los textos: {exc}") from exc
    if _skip(text, end) != len(text):
        raise TemplateError("Contenido inesperado tras el JSON.")
    return spans


def _skip(text: str, i: int) -> int:
    while i < len(text) and text[i] in _WS:
        i += 1
    return i


def _expect(text: str, i: int, char: str) -> int:
    if text[i] != char:
        raise ValueError(f"se esperaba {char!r} en la posición {i}")
    return _skip(text, i + 1)


def _scan_value(text: str, i: int, path: Path, spans: Dict[Path, Tuple[int, int]]) -> int:
    end = _scan_inner(text, i, path, spans)
    spans[path] = (i, end)
    return end


def _scan_inner(text: str, i: int, path: Path, spans: Dict[Path, Tuple[int, int]]) -> int:
    char = text[i]
    if char == "{":
        i = _skip(text, i + 1)
        if text[i] == "}":
            return i + 1
        while True:
            match = _STRING.match(text, i)
            if not match:
                raise ValueError(f"clave esperada en la posición {i}")
            key = json.loads(match.group())
            i = _expect(text, _skip(text, match.end()), ":")
            i = _skip(text, _scan_value(text, i, path + (key,), spans))
            if text[i] == "}":
                return i + 1
            i = _expect(text, i, ",")
    if char == "[":
        i = _skip(text, i + 1)
        if text[i] == "]":
            return i + 1
        index = 0
        while True:
            i = _skip(text, _scan_value(text, i, path + (index,), spans))
            if text[i] == "]":
                return i + 1
            i = _expect(text, i, ",")
            index += 1
    if char == '"':
        match = _STRING.match(text, i)
        if not match:
            raise ValueError(f"cadena sin cerrar en la posición {i}")
        return match.end()
    for literal in _LITERALS:
        if text.startswith(literal, i):
            return i + len(literal)
    match = _NUMBER.match(text, i)
    if not match:
        raise ValueError(f"valor inesperado en la posición {i}")
    return match.end()
