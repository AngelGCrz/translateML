"""Validación de los JSON generados frente a la plantilla original."""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from .jsonpath import Path, format_path
from .rebuild import apply_changes
from .template import Template, TemplateError, parse_json


def compare_structure(original: Any, generated: Any, allowed: Dict[Path, str], path: Path = ()) -> List[str]:
    """Diferencias entre ambos JSON, salvo los cambios de texto permitidos en `allowed`."""
    if type(original) is not type(generated):
        return [f"{format_path(path) or '(raíz)'}: tipo {type(original).__name__} -> {type(generated).__name__}"]
    if isinstance(original, dict):
        if list(original) != list(generated):
            return [f"{format_path(path) or '(raíz)'}: propiedades distintas o en otro orden"]
        errors: List[str] = []
        for key in original:
            errors += compare_structure(original[key], generated[key], allowed, path + (key,))
        return errors
    if isinstance(original, list):
        if len(original) != len(generated):
            return [f"{format_path(path) or '(raíz)'}: {len(original)} elementos -> {len(generated)}"]
        errors = []
        for index, (a, b) in enumerate(zip(original, generated)):
            errors += compare_structure(a, b, allowed, path + (index,))
        return errors
    if path in allowed:
        return [] if generated == allowed[path] else [f"{format_path(path)}: no contiene el texto esperado"]
    return [] if original == generated else [f"{format_path(path)}: valor modificado {original!r} -> {generated!r}"]


def validate_output(template: Template, text: str, changes: Dict[Path, str], removals: Sequence[Path] = ()) -> List[str]:
    """Comprueba que `text` es JSON válido y que solo cambian las rutas de `changes` y desaparecen
    las líneas de `removals` (continuaciones de frases unidas); todo lo demás debe ser idéntico."""
    try:
        generated = parse_json(text, "JSON generado")
    except TemplateError as exc:
        return [str(exc)]
    if removals:
        errors = compare_structure(apply_changes(template.data, changes, list(removals)), generated, {})
    else:
        errors = compare_structure(template.data, generated, changes)
    if not changes and not removals and text != template.text:
        errors.append("Sin cambios de texto, pero el archivo no es idéntico a la plantilla.")
    return errors
