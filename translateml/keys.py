"""Estabilidad de las claves internas entre extracciones.

Sin esto, cada extracción numera de nuevo T0001, T0002... y una línea añadida a la
plantilla desplazaría todas las claves siguientes, asociando las traducciones de la
hoja a textos equivocados. Aquí se reutilizan las claves del manifest anterior.

Se busca la alineación que conserva el orden de documento y maximiza una puntuación:
- mismo texto (y misma regla): 4 puntos, +1 si además está en la misma ruta;
- texto distinto en la misma ruta: 1 punto (texto modificado);
- cualquier otro par no se empareja.
Así, una línea insertada no desplaza las claves siguientes, un texto editado conserva
su clave, y los textos repetidos se asocian por su posición relativa y no solo por su
contenido. Lo no emparejado son textos nuevos (claves nuevas, nunca reutilizadas) o eliminados.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .extraction.extractor import TextUnit
from .jsonpath import format_path

KEY_PREFIX = "T"


@dataclass
class KeyChanges:
    unchanged: List[str] = field(default_factory=list)
    modified: List[Dict[str, str]] = field(default_factory=list)
    moved: List[Dict[str, str]] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    removed: List[Dict[str, str]] = field(default_factory=list)
    next_key: int = 1

    def summary(self) -> Dict[str, int]:
        return {"unchanged": len(self.unchanged), "modified": len(self.modified), "moved": len(self.moved),
                "added": len(self.added), "removed": len(self.removed)}

    def as_dict(self) -> Dict:
        return {"summary": self.summary(), "modified": self.modified, "moved": self.moved,
                "added": self.added, "removed": self.removed}


def key_number(key: str) -> int:
    return int(key[len(KEY_PREFIX):])


def format_key(number: int) -> str:
    return f"{KEY_PREFIX}{number:04d}"


def _score(old: TextUnit, new: TextUnit) -> int:
    if old.rule != new.rule:
        return 0
    if old.text == new.text:
        return 5 if old.path == new.path else 4
    return 1 if old.path == new.path else 0


def _align(previous: List[TextUnit], current: List[TextUnit]) -> Dict[int, int]:
    """Índice en `current` -> índice en `previous` de la alineación de mayor puntuación."""
    n, m = len(previous), len(current)
    best = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row, below = best[i], best[i + 1]
        for j in range(m - 1, -1, -1):
            value = max(below[j], row[j + 1])
            score = _score(previous[i], current[j])
            if score:
                value = max(value, score + below[j + 1])
            row[j] = value
    pairs: Dict[int, int] = {}
    i = j = 0
    while i < n and j < m:
        score = _score(previous[i], current[j])
        if score and best[i][j] == score + best[i + 1][j + 1]:
            pairs[j] = i
            i, j = i + 1, j + 1
        elif best[i][j] == best[i + 1][j]:
            i += 1
        else:
            j += 1
    return pairs


def reconcile(previous: List[TextUnit], current: List[TextUnit], next_key: int) -> KeyChanges:
    """Asigna a `current` las claves de `previous` cuando representan la misma ubicación."""
    next_key = max([next_key] + [key_number(u.key) + 1 for u in previous])
    pairs = _align(previous, current)
    changes = KeyChanges()
    for j, unit in enumerate(current):
        if j not in pairs:
            unit.key = format_key(next_key)
            next_key += 1
            changes.added.append(unit.key)
            continue
        old = previous[pairs[j]]
        unit.key = old.key
        if old.text != unit.text:
            changes.modified.append({"key": unit.key, "path": format_path(unit.path), "old": old.text, "new": unit.text})
        elif old.path != unit.path:
            changes.moved.append({"key": unit.key, "old_path": format_path(old.path), "new_path": format_path(unit.path)})
        else:
            changes.unchanged.append(unit.key)
    used = set(pairs.values())
    changes.removed = [{"key": u.key, "path": format_path(u.path), "text": u.text}
                       for i, u in enumerate(previous) if i not in used]
    changes.next_key = next_key
    return changes
