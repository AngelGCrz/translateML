"""Configuración de la hoja de cálculo local (config/sheets.json)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path as FilePath
from typing import Dict, Optional

from ..config import CONFIG_DIR
from .errors import SheetsConfigError

ASSOCIATIONS = ("key", "text")
_LETTER = re.compile(r"^[A-Za-z]{1,3}$")


@dataclass(frozen=True)
class SheetsConfig:
    xlsx_file: Optional[FilePath]
    header_row: int
    key_header: str
    text_header: str
    positional_fallback: bool
    association: str = "key"
    text_column: Optional[str] = None  # letra, para hojas sin cabeceras
    tabs: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def text_header_for(self, tab: str) -> str:
        return self.tabs.get(tab, {}).get("text_header", self.text_header)

    def text_column_for(self, tab: str) -> Optional[str]:
        return self.tabs.get(tab, {}).get("text_column", self.text_column)

    def key_header_for(self, tab: str) -> str:
        return self.tabs.get(tab, {}).get("key_header", self.key_header)

    def require_xlsx(self) -> FilePath:
        if self.xlsx_file is None:
            raise SheetsConfigError("Indica el archivo con --xlsx RUTA/Multidioma.xlsx o configura xlsx_file "
                                    "en config/sheets.json.")
        return self.xlsx_file


def load_sheets_config(key_header: str, text_header: str, file: Optional[FilePath] = None,
                       xlsx_file: Optional[str] = None) -> SheetsConfig:
    """Las cabeceras KEY/TEXT por defecto son las mismas columnas del CSV (settings.json)."""
    file = FilePath(file or CONFIG_DIR / "sheets.json")
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SheetsConfigError(f"No se puede leer {file}: {exc}") from exc
    header_row = int(raw.get("header_row", 1))
    if header_row < 0:
        raise SheetsConfigError("header_row debe ser 0 (sin cabeceras) o mayor.")
    association = raw.get("association", "key")
    if association not in ASSOCIATIONS:
        raise SheetsConfigError(f"association debe ser uno de {ASSOCIATIONS}, no {association!r}")
    letters = [raw.get("text_column")] + [t.get("text_column") for t in raw.get("tabs", {}).values()]
    for letter in letters:
        if letter is not None and not _LETTER.match(str(letter)):
            raise SheetsConfigError(f"text_column debe ser una letra de columna (A, B, C...), no {letter!r}")
    if header_row == 0 and not any(letters):
        raise SheetsConfigError("Sin fila de cabeceras (header_row 0) hay que indicar text_column (p. ej. \"C\").")
    configured = (raw.get("xlsx_file") or "").strip()
    if xlsx_file:
        path: Optional[FilePath] = FilePath(xlsx_file).expanduser()
    elif configured:
        path = FilePath(configured).expanduser()
        path = path if path.is_absolute() else (CONFIG_DIR / path).resolve()
    else:
        path = None
    return SheetsConfig(
        xlsx_file=path,
        header_row=header_row,
        key_header=raw.get("key_header", key_header),
        text_header=raw.get("text_header", text_header),
        positional_fallback=bool(raw.get("positional_fallback", False)),
        association=association,
        text_column=raw.get("text_column"),
        tabs=raw.get("tabs", {}),
    )
