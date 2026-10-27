"""Errores de la lectura de la hoja de cálculo local (Multidioma.xlsx), con mensajes que indican qué hacer."""


class SheetsError(Exception):
    pass


class SheetsConfigError(SheetsError):
    pass


class SheetsReadError(SheetsError):
    """El archivo no existe, no es un XLSX válido o no se puede leer."""


class SheetsStructureError(SheetsError):
    """Faltan pestañas o columnas, o hay datos ambiguos (claves o cabeceras repetidas)."""
