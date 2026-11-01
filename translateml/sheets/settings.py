"""Configuración del archivo de traducciones (config/sheets.json).

Formato, con una sección por tipo de archivo; el que se usa lo decide la extensión del archivo:

    {
        "file": "",                       // ruta por defecto (relativa a config/); --file la sustituye
        "xlsx": {                         // Multidioma.xlsx de Google Sheets
            "header_row": 0,              // 0 = sin fila de cabeceras
            "association": "text",        // "text" (inglés exacto) o "key" (columna KEY)
            "text_column": "C",           // letra; obligatoria sin cabeceras
            "key_header": "KEY", "text_header": "TEXT",   // opcionales, por defecto settings.json
            "position": "verified",       // celdas sin fórmula que referencie ENG (texto escrito a mano o
                                          // cualquier otra fórmula): "verified" = misma fila que en ENG si
                                          // la pestaña está alineada con ENG; "always" = misma fila sin
                                          // comprobar; "never" = no se usan
            "tabs": {"ESP": {"text_column": "D"}}          // ajustes por pestaña
        },
        "docx": {                         // multidioma.docx de Google Docs
            "tabs": null,                 // nombres de las pestañas en orden; null = orden de languages.json
            "numbering_pattern": "...",   // celdas que solo son numeración y se ignoran; "" = ninguna
            "paragraphs": true            // leer también los párrafos con texto fuera de las tablas
        }
    }

Se sigue aceptando el formato anterior, plano (las claves de "xlsx" en la raíz, "xlsx_file" y
"docx_tabs"), y "positional_fallback" (true = "always", false = "never") en lugar de "position".
Una clave desconocida es un error, para que una errata no pase desapercibida.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path as FilePath
from typing import Dict, List, Optional

from ..config import CONFIG_DIR
from .errors import SheetsConfigError

ASSOCIATIONS = ("key", "text")
POSITION_MODES = ("verified", "always", "never")
DEFAULT_NUMBERING = r"^\s*\d+\s*[.)]?\s*$"
_LETTER = re.compile(r"^[A-Za-z]{1,3}$")
_XLSX_KEYS = {"header_row", "association", "text_column", "key_header", "text_header", "position",
              "positional_fallback", "tabs"}
_TAB_KEYS = {"text_column", "text_header", "key_header"}
_DOCX_KEYS = {"tabs", "numbering_pattern", "paragraphs"}
_LEGACY_KEYS = _XLSX_KEYS | {"xlsx_file", "docx_tabs"}


@dataclass(frozen=True)
class TableLayout:
    """Cómo se interpretan las filas de una pestaña: dónde está el texto y cómo se asocia con ENG."""
    header_row: int
    key_header: str
    text_header: str
    association: str = "key"
    text_column: Optional[str] = None  # letra, para hojas sin cabeceras
    position: str = "verified"         # POSITION_MODES: si una celda sin referencia a ENG usa su fila
    tabs: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def text_header_for(self, tab: str) -> str:
        return self.tabs.get(tab, {}).get("text_header", self.text_header)

    def text_column_for(self, tab: str) -> Optional[str]:
        return self.tabs.get(tab, {}).get("text_column", self.text_column)

    def key_header_for(self, tab: str) -> str:
        return self.tabs.get(tab, {}).get("key_header", self.key_header)


@dataclass(frozen=True)
class DocxOptions:
    tabs: Optional[List[str]] = None
    numbering_pattern: str = DEFAULT_NUMBERING
    paragraphs: bool = True


@dataclass(frozen=True)
class SheetsConfig:
    file: Optional[FilePath]
    xlsx: TableLayout
    docx: DocxOptions = field(default_factory=DocxOptions)

    def require_file(self) -> FilePath:
        if self.file is None:
            raise SheetsConfigError("Indica el archivo con --xlsx RUTA/Multidioma.xlsx o --docx RUTA/multidioma.docx, "
                                    "o configura \"file\" en config/sheets.json.")
        return self.file


def load_sheets_config(key_header: str, text_header: str, file: Optional[FilePath] = None,
                       source_file: Optional[str] = None) -> SheetsConfig:
    """Las cabeceras KEY/TEXT por defecto son las mismas columnas del CSV (settings.json)."""
    file = FilePath(file or CONFIG_DIR / "sheets.json")
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SheetsConfigError(f"No se puede leer {file}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SheetsConfigError(f"{file} debe contener un objeto JSON.")
    raw = raw if ("xlsx" in raw or "docx" in raw or "file" in raw) else _from_legacy(raw)
    _check_keys(raw, {"file", "xlsx", "docx"}, "sheets.json")
    return SheetsConfig(file=_source_path(source_file, raw.get("file")),
                        xlsx=_table_layout(raw.get("xlsx", {}), key_header, text_header),
                        docx=_docx_options(raw.get("docx", {})))


def _from_legacy(raw: Dict) -> Dict:
    """Formato plano anterior -> formato por secciones."""
    _check_keys(raw, _LEGACY_KEYS, "sheets.json")
    nested: Dict = {"file": raw.get("xlsx_file", ""), "xlsx": {k: v for k, v in raw.items() if k in _XLSX_KEYS}}
    if raw.get("docx_tabs") is not None:
        nested["docx"] = {"tabs": raw["docx_tabs"]}
    return nested


def _table_layout(raw: Dict, key_header: str, text_header: str) -> TableLayout:
    _check_keys(raw, _XLSX_KEYS, "xlsx")
    header_row = raw.get("header_row", 1)
    if not isinstance(header_row, int) or header_row < 0:
        raise SheetsConfigError("xlsx.header_row debe ser 0 (sin cabeceras) o un número de fila.")
    association = raw.get("association", "key")
    if association not in ASSOCIATIONS:
        raise SheetsConfigError(f"xlsx.association debe ser uno de {ASSOCIATIONS}, no {association!r}")
    tabs = raw.get("tabs", {})
    if not isinstance(tabs, dict):
        raise SheetsConfigError("xlsx.tabs debe ser un objeto {pestaña: {ajustes}}.")
    for tab, options in tabs.items():
        _check_keys(options, _TAB_KEYS, f"xlsx.tabs.{tab}")
    letters = [raw.get("text_column")] + [t.get("text_column") for t in tabs.values()]
    for letter in letters:
        if letter is not None and not _LETTER.match(str(letter)):
            raise SheetsConfigError(f"text_column debe ser una letra de columna (A, B, C...), no {letter!r}")
    if header_row == 0 and not any(letters):
        raise SheetsConfigError("Sin fila de cabeceras (header_row 0) hay que indicar text_column (p. ej. \"C\").")
    return TableLayout(header_row=header_row, key_header=raw.get("key_header", key_header),
                       text_header=raw.get("text_header", text_header), association=association,
                       text_column=raw.get("text_column"), position=_position_mode(raw), tabs=tabs)


def _position_mode(raw: Dict) -> str:
    if "position" in raw and "positional_fallback" in raw:
        raise SheetsConfigError("xlsx: usa \"position\" o el antiguo \"positional_fallback\", no los dos.")
    if "positional_fallback" in raw:
        return "always" if raw["positional_fallback"] else "never"
    mode = raw.get("position", "verified")
    if mode not in POSITION_MODES:
        raise SheetsConfigError(f"xlsx.position debe ser uno de {POSITION_MODES}, no {mode!r}")
    return mode


def _docx_options(raw: Dict) -> DocxOptions:
    _check_keys(raw, _DOCX_KEYS, "docx")
    tabs = raw.get("tabs")
    if tabs is not None and (not isinstance(tabs, list) or not tabs
                             or not all(isinstance(t, str) and t.strip() for t in tabs)):
        raise SheetsConfigError("docx.tabs debe ser null o una lista de nombres de pestaña, p. ej. [\"ENG\", \"ESP\"].")
    pattern = raw.get("numbering_pattern", DEFAULT_NUMBERING)
    try:
        re.compile(pattern or "")
    except (re.error, TypeError) as exc:
        raise SheetsConfigError(f"docx.numbering_pattern no es una expresión regular válida: {exc}") from exc
    return DocxOptions(tabs=tabs, numbering_pattern=pattern or "", paragraphs=bool(raw.get("paragraphs", True)))


def _source_path(cli_value: Optional[str], configured: Optional[str]) -> Optional[FilePath]:
    if cli_value:
        return FilePath(cli_value).expanduser()
    configured = (configured or "").strip()
    if not configured:
        return None
    path = FilePath(configured).expanduser()
    return path if path.is_absolute() else (CONFIG_DIR / path).resolve()


def _check_keys(raw, allowed, where: str) -> None:
    if not isinstance(raw, dict):
        raise SheetsConfigError(f"{where} debe ser un objeto JSON.")
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise SheetsConfigError(f"{where}: claves desconocidas {', '.join(unknown)}. "
                                f"Claves válidas: {', '.join(sorted(allowed))}.")
