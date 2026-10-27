"""Perfiles de extracción: qué rutas son traducibles y qué se considera técnico.

Los perfiles son archivos JSON en config/profiles. El motor no conoce ninguna
sección concreta de los juegos; todo lo específico vive aquí.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path as FilePath
from typing import Any, FrozenSet, List, Optional, Pattern, Tuple

from ..jsonpath import Path, expand, parse_path

MODES = ("value", "recursive")


class ProfileError(Exception):
    pass


@dataclass(frozen=True)
class Selector:
    id: str
    raw: str
    path: Path
    mode: str


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    detect_any: Tuple[Path, ...]
    selectors: Tuple[Selector, ...]
    text_keys: FrozenSet[str]
    technical_keys: FrozenSet[str]
    technical_values: Tuple[Pattern, ...]
    protected_tokens: Pattern
    protected_prefix: Pattern
    protected_suffix: Pattern

    def matches(self, data: Any) -> bool:
        return any(next(expand(data, path), None) is not None for path in self.detect_any)


def load_profile(file) -> Profile:
    file = FilePath(file)
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
        selectors = []
        for item in raw["include"]:
            mode = item.get("mode", "value")
            if mode not in MODES:
                raise ProfileError(f"Modo desconocido {mode!r} en {item}")
            selectors.append(Selector(id=item["id"], raw=item["select"], path=parse_path(item["select"]), mode=mode))
        ids = [s.id for s in selectors]
        if len(ids) != len(set(ids)):
            raise ProfileError("Hay identificadores de regla repetidos.")
        return Profile(
            name=raw["name"],
            description=raw.get("description", ""),
            detect_any=tuple(parse_path(p) for p in raw.get("detect", {}).get("any_of", [])),
            selectors=tuple(selectors),
            text_keys=frozenset(raw.get("text_keys", [])),
            technical_keys=frozenset(raw.get("technical_keys", [])),
            technical_values=tuple(re.compile(p) for p in raw.get("technical_values", [])),
            protected_tokens=re.compile("|".join(f"(?:{p})" for p in raw.get("protected_tokens", [])) or r"(?!)"),
            protected_prefix=re.compile(raw.get("protected_prefix", r"^\s*")),
            protected_suffix=re.compile(raw.get("protected_suffix", r"\s*$")),
        )
    except (OSError, ValueError, KeyError, re.error) as exc:
        raise ProfileError(f"Perfil no válido {file}: {exc!r}") from exc


def load_profiles(directory) -> List[Profile]:
    return [load_profile(f) for f in sorted(FilePath(directory).glob("*.json"))]


def select_profile(data: Any, profiles: List[Profile], name: Optional[str] = None) -> Profile:
    if name:
        for profile in profiles:
            if profile.name == name:
                return profile
        raise ProfileError(f"No existe el perfil {name!r}. Disponibles: {[p.name for p in profiles]}")
    matching = [p for p in profiles if p.matches(data)]
    if not matching:
        raise ProfileError("Ningún perfil reconoce esta plantilla. Indica uno con --profile o crea uno nuevo.")
    if len(matching) > 1:
        raise ProfileError(f"Varios perfiles reconocen la plantilla: {[p.name for p in matching]}. Usa --profile.")
    return matching[0]
