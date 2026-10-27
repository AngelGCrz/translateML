"""Rutas dentro de un JSON: representación, formato, selectores con comodín y acceso."""
from __future__ import annotations

import re
from typing import Any, Iterator, Tuple, Union

Key = Union[str, int]
Path = Tuple[Key, ...]

WILDCARD = "*"
_SEGMENT = re.compile(r"(?:^|\.)([^.\[\]]+)|\[(\d+|\*)\]")


def format_path(path: Path) -> str:
    """('rules', 'pages', 0, 'text') -> 'rules.pages[0].text'"""
    out = ""
    for key in path:
        if isinstance(key, int):
            out += f"[{key}]"
        elif key == WILDCARD:
            out += "[*]"
        else:
            out += f".{key}" if out else key
    return out


def parse_path(text: str) -> Path:
    """'payTables[*].titles[0].text' -> ('payTables', '*', 'titles', 0, 'text')"""
    tokens = []
    pos = 0
    for match in _SEGMENT.finditer(text):
        if match.start() != pos:
            break
        name, index = match.groups()
        if name is not None:
            tokens.append(name)
        else:
            tokens.append(WILDCARD if index == WILDCARD else int(index))
        pos = match.end()
    if pos != len(text) or not tokens:
        raise ValueError(f"Ruta no válida: {text!r}")
    return tuple(tokens)


def expand(node: Any, selector: Path, prefix: Path = ()) -> Iterator[Path]:
    """Rutas concretas que existen en `node` y coinciden con `selector`."""
    if not selector:
        yield prefix
        return
    head, rest = selector[0], selector[1:]
    if head == WILDCARD:
        if isinstance(node, list):
            children = enumerate(node)
        elif isinstance(node, dict):
            children = node.items()
        else:
            return
        for key, child in children:
            yield from expand(child, rest, prefix + (key,))
    elif isinstance(head, int):
        if isinstance(node, list) and 0 <= head < len(node):
            yield from expand(node[head], rest, prefix + (head,))
    elif isinstance(node, dict) and head in node:
        yield from expand(node[head], rest, prefix + (head,))


def get_value(node: Any, path: Path) -> Any:
    for key in path:
        node = node[key]
    return node


def set_value(node: Any, path: Path, value: Any) -> None:
    parent = get_value(node, path[:-1])
    parent[path[-1]] = value


def walk_scalars(node: Any, prefix: Path = ()) -> Iterator[Tuple[Path, Any]]:
    """Recorre en orden de documento todos los valores escalares (str, número, bool, null)."""
    if isinstance(node, dict):
        for key, child in node.items():
            yield from walk_scalars(child, prefix + (key,))
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from walk_scalars(child, prefix + (index,))
    else:
        yield prefix, node


def nearest_key(path: Path) -> Union[str, None]:
    """Última clave de objeto de la ruta: ('items', 'lines', 3) -> 'lines'."""
    for key in reversed(path):
        if isinstance(key, str):
            return key
    return None
