"""Configuración del programa (config/settings.json) y de los idiomas (config/languages.json)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path as FilePath
from typing import List, Optional

CONFIG_DIR = FilePath(__file__).resolve().parent.parent / "config"
MISSING_POLICIES = ("keep_source", "error")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Language:
    code: str        # código interno
    name: str
    tab: Optional[str]  # pestaña en Multidioma.xlsx (ENG, ESP, DEU...)
    folder: str      # carpeta de salida
    enabled: bool


@dataclass(frozen=True)
class Languages:
    source: str
    items: List[Language]

    def get(self, code: str) -> Language:
        for language in self.items:
            if language.code == code:
                return language
        raise ConfigError(f"Idioma desconocido {code!r}. Configurados: {[l.code for l in self.items]}")

    @property
    def enabled(self) -> List[Language]:
        return [l for l in self.items if l.enabled]


@dataclass(frozen=True)
class Settings:
    profiles_dir: FilePath
    languages_file: FilePath
    output_root: FilePath
    output_filename: str
    missing_translation_policy: str
    key_column: str
    text_column: str


def load_settings(directory: FilePath = CONFIG_DIR) -> Settings:
    directory = FilePath(directory)
    raw = _read(directory / "settings.json")
    policy = raw.get("missing_translation_policy", "keep_source")
    if policy not in MISSING_POLICIES:
        raise ConfigError(f"missing_translation_policy debe ser uno de {MISSING_POLICIES}, no {policy!r}")
    return Settings(
        profiles_dir=(directory / raw.get("profiles_dir", "profiles")).resolve(),
        languages_file=(directory / raw.get("languages_file", "languages.json")).resolve(),
        output_root=(directory / raw.get("output_root", "../output")).resolve(),
        output_filename=raw.get("output_filename", "info.json"),
        missing_translation_policy=policy,
        key_column=raw.get("key_column", "KEY"),
        text_column=raw.get("text_column", "TEXT"),
    )


_FOLDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def load_languages(file: FilePath) -> Languages:
    """Lee languages.json y comprueba que cada idioma se pueda procesar sin ambigüedad.

    Código interno, pestaña del .xlsx y carpeta de salida son independientes. Un idioma
    habilitado necesita pestaña; la carpeta debe ser un nombre simple (nunca una ruta).
    """
    file = FilePath(file)
    raw = _read(file)
    items = []
    for index, entry in enumerate(raw.get("languages", []), start=1):
        code = str(entry.get("code") or "").strip()
        if not code or any(c.isspace() for c in code):
            raise ConfigError(f"{file.name}: el idioma n.º {index} no tiene un 'code' válido.")
        tab = entry.get("tab")
        tab = str(tab).strip() if tab is not None and str(tab).strip() else None
        folder = str(entry.get("folder") or code).strip()
        if not _FOLDER.match(folder):
            raise ConfigError(f"{file.name}: la carpeta {folder!r} de {code} debe ser un nombre simple "
                              "(letras, números, '.', '-', '_'), no una ruta.")
        enabled = entry.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ConfigError(f"{file.name}: 'enabled' de {code} debe ser true o false.")
        if enabled and not tab:
            raise ConfigError(f"{file.name}: {code} está habilitado pero no tiene 'tab' (pestaña del .xlsx).")
        items.append(Language(code=code, name=entry.get("name", code), tab=tab, folder=folder, enabled=enabled))
    if not items:
        raise ConfigError(f"{file.name}: no hay idiomas configurados.")
    for attr, normalize in (("code", str), ("folder", str.lower), ("tab", str.lower)):
        seen = {}
        for position, language in enumerate(items):
            value = getattr(language, attr)
            if not value:
                continue
            first = seen.setdefault(normalize(value), position)
            if first != position:
                raise ConfigError(f"{file.name}: {items[first].code} y {language.code} comparten '{attr}' ({value!r}).")
    languages = Languages(source=raw.get("source", ""), items=items)
    source = languages.get(languages.source)
    if not source.enabled:
        raise ConfigError(f"{file.name}: el idioma de origen {source.code} debe estar habilitado.")
    return languages


def _read(file: FilePath) -> dict:
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"No se puede leer {file}: {exc}") from exc
