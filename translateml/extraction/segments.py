"""Separación entre el texto editable y los elementos protegidos.

Un valor como "{fixedJackpot}• Each ##sym_1.png##pays " se divide en:
  prefix = "{fixedJackpot}• "     (lo restaura el programa)
  text   = "Each ##sym_1.png##pays" (lo ve Data; los marcadores internos se validan)
  suffix = " "                     (lo restaura el programa)
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import List

from .rules import Profile

KIND_TEXT = "text"
KIND_LAYOUT = "layout"          # "", solo espacios o solo elementos protegidos
KIND_NO_LETTERS = "no_letters"  # números y signos, p. ej. "13+\n11-12"
KIND_TECHNICAL = "technical"    # color, coordenada, recurso, identificador

_LETTER = re.compile(r"[^\W\d_]")


@dataclass(frozen=True)
class Segment:
    prefix: str
    text: str
    suffix: str

    def join(self) -> str:
        return self.prefix + self.text + self.suffix


def split(value: str, profile: Profile) -> Segment:
    prefix = profile.protected_prefix.match(value).group(0)
    rest = value[len(prefix):]
    suffix = profile.protected_suffix.search(rest).group(0) if rest else ""
    return Segment(prefix, rest[:len(rest) - len(suffix)], suffix)


def tokens(text: str, profile: Profile) -> List[str]:
    return sorted(m.group(0) for m in profile.protected_tokens.finditer(text))


def token_difference(expected: List[str], actual: List[str]) -> str:
    """Descripción de los marcadores perdidos o añadidos; cadena vacía si coinciden."""
    missing = Counter(expected) - Counter(actual)
    extra = Counter(actual) - Counter(expected)
    parts = []
    if missing:
        parts.append("faltan " + ", ".join(sorted(missing.elements())))
    if extra:
        parts.append("sobran " + ", ".join(sorted(extra.elements())))
    return "; ".join(parts)


def classify(value: str, profile: Profile) -> str:
    if not value.strip():
        return KIND_LAYOUT
    if any(p.search(value) for p in profile.technical_values):
        return KIND_TECHNICAL
    text = split(value, profile).text
    if not text:
        return KIND_LAYOUT
    if not _LETTER.search(profile.protected_tokens.sub("", text)):
        return KIND_NO_LETTERS
    return KIND_TEXT
