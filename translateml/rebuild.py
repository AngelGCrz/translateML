"""Motor de reconstrucción: inserta textos en la plantilla original sin tocar nada más."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

from .extraction.extractor import TextUnit
from .extraction.rules import Profile
from .extraction.segments import split, token_difference, tokens
from .jsonpath import Path, format_path, set_value
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

    @property
    def missing(self) -> List[Issue]:
        return [i for i in self.issues if i.blocking]


def rebuild(template: Template, units: List[TextUnit], texts: Mapping[str, str], profile: Profile) -> RebuildResult:
    """`texts` asocia la clave de cada unidad con el texto editable (sin prefijo ni sufijo).

    Si falta un texto o pierde marcadores protegidos se conserva el original y se informa;
    nunca se inserta null, una cadena vacía ni un texto inventado.
    """
    replacements: Dict[Path, str] = {}
    issues: List[Issue] = []
    for unit in units:
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
        difference = token_difference(unit.tokens, tokens(text, profile))
        if difference:
            issues.append(Issue(unit.key, where, TOKENS, difference, True))
            continue
        if text.count("\n") != unit.text.count("\n"):
            issues.append(Issue(unit.key, where, NEWLINES,
                                f"{unit.text.count(chr(10))} saltos de línea en el original, {text.count(chr(10))} en el texto", False))
        value = unit.prefix + text + unit.suffix
        if value != unit.source:
            replacements[unit.path] = value

    data = copy.deepcopy(template.data)
    for path, value in replacements.items():
        set_value(data, path, value)
    return RebuildResult(text=template.render(replacements), data=data, changes=replacements, issues=issues)
