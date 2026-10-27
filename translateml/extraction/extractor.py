"""Motor genérico de extracción: aplica un perfil a la plantilla y registra cada texto con su ruta."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from ..jsonpath import Path, expand, get_value, nearest_key, walk_scalars
from .rules import Profile
from .segments import KIND_NO_LETTERS, KIND_TECHNICAL, KIND_TEXT, classify, split, tokens


@dataclass
class TextUnit:
    """Un texto traducible. `key` la genera el programa y no depende del contenido."""
    key: str
    path: Path
    rule: str
    source: str
    prefix: str
    text: str
    suffix: str
    tokens: List[str]


@dataclass
class Skipped:
    """Cadena dentro de una regla que se conserva sin traducir."""
    path: Path
    rule: str
    kind: str
    value: str


@dataclass
class AuditItem:
    """Cadena que podría ser texto visible y que ninguna regla cubre."""
    path: Path
    value: str
    reason: str


@dataclass
class Extraction:
    profile: str
    units: List[TextUnit] = field(default_factory=list)
    skipped: List[Skipped] = field(default_factory=list)
    audit: List[AuditItem] = field(default_factory=list)
    rules_found: Dict[str, int] = field(default_factory=dict)
    rules_missing: List[str] = field(default_factory=list)

    @property
    def covered(self) -> Set[Path]:
        return {u.path for u in self.units} | {s.path for s in self.skipped}


def extract(data: Any, profile: Profile) -> Extraction:
    result = Extraction(profile=profile.name)
    order = {path: index for index, (path, _) in enumerate(walk_scalars(data))}
    found: Dict[Path, TextUnit] = {}
    handled: Set[Path] = set()

    def take(path: Path, value: str, rule: str) -> None:
        handled.add(path)
        kind = classify(value, profile)
        if kind != KIND_TEXT:
            result.skipped.append(Skipped(path, rule, kind, value))
            if kind == KIND_NO_LETTERS:
                result.audit.append(AuditItem(path, value, "visible pero sin letras; se conserva igual en todos los idiomas"))
            return
        segment = split(value, profile)
        found[path] = TextUnit("", path, rule, value, segment.prefix, segment.text, segment.suffix,
                               tokens(segment.text, profile))

    for selector in profile.selectors:
        roots = list(expand(data, selector.path))
        result.rules_found[selector.id] = 0
        if not roots:
            result.rules_missing.append(selector.raw)
            continue
        for root in roots:
            if selector.mode == "value":
                candidates = [(root, get_value(data, root))]
            else:
                candidates = list(walk_scalars(get_value(data, root), root))
            for path, value in candidates:
                if path in handled or not isinstance(value, str):
                    continue
                relative = path[len(root):] if selector.mode == "recursive" else ()
                if any(k in profile.technical_keys for k in relative if isinstance(k, str)):
                    continue
                if selector.mode == "recursive" and nearest_key(path) not in profile.text_keys:
                    handled.add(path)
                    result.audit.append(AuditItem(path, value, f"clave '{nearest_key(path)}' sin clasificar dentro de {selector.raw}"))
                    continue
                take(path, value, selector.id)
                result.rules_found[selector.id] += path in found

    result.units = sorted(found.values(), key=lambda u: order[u.path])
    for number, unit in enumerate(result.units, start=1):
        unit.key = f"T{number:04d}"
    result.skipped.sort(key=lambda s: order[s.path])
    result.audit.extend(_audit_uncovered(data, profile, handled))
    result.audit.sort(key=lambda a: order[a.path])
    return result


def _audit_uncovered(data: Any, profile: Profile, handled: Set[Path]) -> List[AuditItem]:
    """Cadenas fuera de las reglas que parecen texto visible (ni clave ni valor técnicos)."""
    items = []
    for path, value in walk_scalars(data):
        if path in handled or not isinstance(value, str):
            continue
        if any(k in profile.technical_keys for k in path if isinstance(k, str)):
            continue
        kind = classify(value, profile)
        if kind == KIND_TEXT:
            items.append(AuditItem(path, value, "posible texto visible fuera de las reglas"))
        elif kind != KIND_TECHNICAL and nearest_key(path) in profile.text_keys and value.strip():
            items.append(AuditItem(path, value, f"clave de texto '{nearest_key(path)}' fuera de las reglas"))
    return items
