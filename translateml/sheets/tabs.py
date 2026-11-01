"""Mensajes sobre pestañas comunes a todos los formatos (.xlsx, .docx)."""
from __future__ import annotations

import difflib
from typing import List, Optional


def suggest_tab(name: str, tabs: List[str]) -> Optional[str]:
    """Pestaña existente que probablemente sea `name` (otras mayúsculas, espacios o una errata)."""
    by_lower = {t.strip().lower(): t for t in tabs}
    if name.strip().lower() in by_lower:
        return by_lower[name.strip().lower()]
    close = difflib.get_close_matches(name, tabs, n=1, cutoff=0.75)
    return close[0] if close else None


def missing_tab_message(file_name: str, tab: str, tabs: List[str]) -> str:
    hint = suggest_tab(tab, tabs)
    hint = f" ¿Es {hint!r}? Si es así, corrige 'tab' en config/languages.json." if hint else ""
    return f"{file_name} no tiene la pestaña {tab!r} (pestañas: {', '.join(tabs)}).{hint}"
