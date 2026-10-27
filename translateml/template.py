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
from typing import Any, Dict, List, Tuple

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

    def render(self, replacements: Dict[Path, str]) -> str:
        """Texto del archivo con las cadenas indicadas sustituidas; lo demás queda intacto."""
        unknown = [p for p in replacements if p not in self.string_spans]
        if unknown:
            raise TemplateError("Rutas sin literal de cadena: " + ", ".join(format_path(p) for p in unknown))
        parts: List[str] = []
        pos = 0
        for path, (start, end) in sorted(
            ((p, self.string_spans[p]) for p in replacements), key=lambda item: item[1][0]
        ):
            if replacements[path] == get_value(self.data, path):
                continue
            parts.append(self.text[pos:start])
            parts.append(json.dumps(replacements[path], ensure_ascii=False))
            pos = end
        parts.append(self.text[pos:])
        return "".join(parts)

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
    spans = scan_string_spans(text)
    for path, (start, end) in spans.items():
        if json.loads(text[start:end]) != get_value(data, path):
            raise TemplateError(f"Posición inconsistente para {format_path(path)}")
    return Template(file=file, text=text, data=data, sha256=hashlib.sha256(raw).hexdigest(),
                    bom=bom, string_spans=spans)


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


def scan_string_spans(text: str) -> Dict[Path, Tuple[int, int]]:
    """Posición (inicio, fin) de cada literal de cadena que es un valor, indexado por ruta."""
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
        spans[path] = (i, match.end())
        return match.end()
    for literal in _LITERALS:
        if text.startswith(literal, i):
            return i + len(literal)
    match = _NUMBER.match(text, i)
    if not match:
        raise ValueError(f"valor inesperado en la posición {i}")
    return match.end()
