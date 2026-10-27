"""Archivos intermedios e informes: manifest, CSV de revisión, auditoría y JSON generados."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path as FilePath
from typing import Any, Dict, List

from .extraction.extractor import Extraction, TextUnit
from .jsonpath import format_path
from .template import Template

MANIFEST_FORMAT = "translateml.manifest/1"


class ManifestError(Exception):
    pass


def write_json(file: FilePath, data: Any) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def manifest_data(template: Template, extraction: Extraction, game: str, next_key: int) -> Dict[str, Any]:
    """Asociación interna clave -> ruta. La administra el programa; Data no la necesita.

    `next_key` es el siguiente número de clave libre: las claves de textos eliminados no se reutilizan.
    """
    return {
        "format": MANIFEST_FORMAT,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "game": game,
        "next_key": next_key,
        "template": {"file": str(template.file.resolve()), "sha256": template.sha256},
        "profile": extraction.profile,
        "units": [
            {"key": u.key, "path": format_path(u.path), "path_tokens": list(u.path), "rule": u.rule,
             "prefix": u.prefix, "text": u.text, "suffix": u.suffix, "tokens": u.tokens, "source": u.source}
            for u in extraction.units
        ],
    }


def load_manifest(file: FilePath) -> Dict[str, Any]:
    try:
        data = json.loads(FilePath(file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"No se puede leer el manifest {file}: {exc}") from exc
    if data.get("format") != MANIFEST_FORMAT:
        raise ManifestError(f"{file} no es un manifest de translateML ({MANIFEST_FORMAT}).")
    return data


def units_from_manifest(manifest: Dict[str, Any]) -> List[TextUnit]:
    return [TextUnit(key=u["key"], path=tuple(u["path_tokens"]), rule=u["rule"], source=u["source"],
                     prefix=u["prefix"], text=u["text"], suffix=u["suffix"], tokens=u["tokens"])
            for u in manifest["units"]]


def extraction_report(extraction: Extraction) -> Dict[str, Any]:
    kinds: Dict[str, int] = {}
    for item in extraction.skipped:
        kinds[item.kind] = kinds.get(item.kind, 0) + 1
    return {
        "profile": extraction.profile,
        "texts": len(extraction.units),
        "texts_by_rule": extraction.rules_found,
        "rules_not_present": extraction.rules_missing,
        "preserved_without_translation": kinds,
        "preserved": [{"path": format_path(s.path), "rule": s.rule, "kind": s.kind, "value": s.value}
                      for s in extraction.skipped],
        "audit": [{"path": format_path(a.path), "value": a.value, "reason": a.reason} for a in extraction.audit],
    }


def write_review_csv(file: FilePath, units: List[TextUnit], key_column: str, text_column: str) -> None:
    """CSV para revisar o editar. Data trabaja con la columna de texto; el resto es informativo."""
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([key_column, text_column, "PATH", "PREFIX", "SUFFIX"])
        for unit in units:
            writer.writerow([unit.key, unit.text, format_path(unit.path), unit.prefix, unit.suffix])


def write_texts_csv(file: FilePath, texts: Dict[str, str], key_column: str, text_column: str) -> None:
    """Textos de un idioma (clave -> texto) en el formato que acepta `rebuild --texts`."""
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([key_column, text_column])
        writer.writerows(sorted(texts.items()))


def read_texts_csv(file: FilePath, key_column: str, text_column: str) -> Dict[str, str]:
    try:
        with FilePath(file).open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = {key_column, text_column} - set(reader.fieldnames or [])
            if missing:
                raise ManifestError(f"{file}: faltan las columnas {sorted(missing)}")
            texts: Dict[str, str] = {}
            for row in reader:
                key = (row[key_column] or "").strip()
                if not key:
                    continue
                if key in texts:
                    raise ManifestError(f"{file}: la clave {key} aparece más de una vez")
                texts[key] = row[text_column] or ""
            return texts
    except OSError as exc:
        raise ManifestError(f"No se puede leer {file}: {exc}") from exc
