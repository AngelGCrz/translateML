"""Motor de reconstrucción: inserta textos en la plantilla original sin tocar nada más."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from .extraction.extractor import TextUnit
from .extraction.rules import Profile
from .extraction.segments import split, token_difference, tokens
from .jsonpath import Path, format_path, get_value, set_value
from .template import Template

MISSING = "missing"
TOKENS = "token_mismatch"
NEWLINES = "newline_count"
PREFIX = "prefix_in_text"


@dataclass
class Issue:
    key: str
    path: str
    kind: str
    detail: str
    blocking: bool  # True: se conservó el texto original en esa ubicación


@dataclass
class RebuildResult:
    text: str
    data: Any
    changes: Dict[Path, str] = field(default_factory=dict)
    issues: List[Issue] = field(default_factory=list)
    removals: List[Path] = field(default_factory=list)  # líneas de continuación unidas a la anterior

    @property
    def missing(self) -> List[Issue]:
        return [i for i in self.issues if i.blocking]


def rebuild(template: Template, units: List[TextUnit], texts: Mapping[str, str], profile: Profile,
            merges: Optional[Mapping[str, List[str]]] = None) -> RebuildResult:
    """`texts` asocia la clave de cada unidad con el texto editable (sin prefijo ni sufijo).

    `merges` une frases que en la plantilla ocupan varias líneas: clave de la primera línea ->
    claves de sus continuaciones. La traducción completa va en la primera línea (con su prefijo y
    el sufijo de la última) y las continuaciones se eliminan de la lista. Si la traducción no es
    válida, la frase entera queda en inglés y no se elimina nada.

    Si falta un texto o pierde marcadores protegidos se conserva el original y se informa;
    nunca se inserta null, una cadena vacía ni un texto inventado.
    """
    merges = merges or {}
    by_key = {u.key: u for u in units}
    continuations = {key for rest in merges.values() for key in rest}
    replacements: Dict[Path, str] = {}
    removals: List[Path] = []
    issues: List[Issue] = []
    for unit in units:
        if unit.key in continuations:
            continue
        group = [unit] + [by_key[k] for k in merges.get(unit.key, [])]
        where = format_path(unit.path)
        text = texts.get(unit.key)
        if text is None or not text.strip():
            issues.append(Issue(unit.key, where, MISSING, "sin texto", True))
            continue
        # Data ve el texto sin prefijo ni sufijo; si escribe una viñeta o espacios, se descartan
        # y se restauran los del original. Un marcador que solo existe en su texto se conserva.
        segment = split(text, profile)
        cut = len(segment.prefix)
        for match in profile.protected_tokens.finditer(segment.prefix):
            if match.group(0) not in unit.prefix:
                cut = match.start()
                break
        dropped = segment.prefix[:cut].strip()
        if dropped:
            issues.append(Issue(unit.key, where, PREFIX,
                                f"se ignoró {dropped!r} al inicio; el programa restaura {unit.prefix!r}", False))
        text = segment.prefix[cut:] + segment.text
        if not text:
            issues.append(Issue(unit.key, where, MISSING, "solo contiene elementos protegidos", True))
            continue
        difference = token_difference(sorted(t for u in group for t in u.tokens), tokens(text, profile))
        if difference:
            issues.append(Issue(unit.key, where, TOKENS, difference, True))
            continue
        if len(group) == 1 and text.count("\n") != unit.text.count("\n"):
            issues.append(Issue(unit.key, where, NEWLINES,
                                f"{unit.text.count(chr(10))} saltos de línea en el original, {text.count(chr(10))} en el texto", False))
        value = unit.prefix + text + group[-1].suffix
        if value != unit.source:
            replacements[unit.path] = value
        removals += [u.path for u in group[1:]]

    data = apply_changes(template.data, replacements, removals)
    return RebuildResult(text=template.render(replacements, removals), data=data, changes=replacements,
                         issues=issues, removals=removals)


def apply_changes(original: Any, replacements: Mapping[Path, str], removals: List[Path]) -> Any:
    """Copia de `original` con los textos sustituidos y los elementos de lista eliminados."""
    data = copy.deepcopy(original)
    for path, value in replacements.items():
        set_value(data, path, value)
    by_list: Dict[Path, List[int]] = {}
    for path in removals:
        by_list.setdefault(path[:-1], []).append(path[-1])
    for parent, indexes in by_list.items():
        target = get_value(data, parent)
        for index in sorted(set(indexes), reverse=True):  # de atrás hacia delante: los índices siguen válidos
            del target[index]
    return data
