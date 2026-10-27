import dataclasses
import json
from pathlib import Path
from unittest import mock

from translateml.config import load_settings
from translateml.extraction import load_profile

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures" / "pixi"
REAL_TEMPLATES = sorted(FIXTURES.glob("g*/info.json"))
PROFILE = load_profile(load_settings().profiles_dir / "pixi_info.json")
# Las pruebas no dependen de qué idiomas habilite el proyecto: usan ENG, ESP y DEU.
TEST_SETTINGS = dataclasses.replace(load_settings(), languages_file=ROOT / "fixtures" / "languages-3.json")


def test_settings():
    """Sustituye la configuración del proyecto por TEST_SETTINGS mientras dura el bloque."""
    return mock.patch("translateml.cli.load_settings", return_value=TEST_SETTINGS)


# Plantilla sintética con lo que no aparece en todas las reales: anidamiento distinto,
# claves desconocidas, texto visible fuera de las reglas y una sección ausente (payLines).
SYNTHETIC = {
    "fontName": "altehaasgrotesk bold",
    "background": {"path": "info1_png", "offset": "0,-20"},
    "intro": {"caption": "Welcome to the game"},
    "rules": {
        "settings": {"titles": {"font": {"color": "rgb(1,2,3)"}}},
        "pages": [
            {
                "titles": [{"text": "GAME RULES", "color": "rgb(1,1,1)", "align": "left", "offset": "0,294"}],
                "items": {"lines": [
                    "• Play up to 50 lines. ",
                    "",
                    "   ##sym_11.png##pays anywhere.",
                    "{fixedJackpot}• Jackpot text",
                    "    6 ##sym_12.png##.",
                ]},
            },
            {
                "titles": [{"text": "GAME RULES"}],
                "blocks": [{"items": {"lines": ["• Nested line"]}}],
                "note": "Ask the dealer",
                "visible": True,
                "count": 3,
                "extra": None,
            },
        ],
    },
    "payTables": [{
        "titles": [
            {"text": "TREE OF\nLIGHT", "tag": "SCATTER", "size": 30},
            {"text": "OF A KIND"},
            {"text": "OF A KIND"},
        ],
        "images": [{"src": "sym_2.png", "scale": 0.35}],
    }],
}


def write_synthetic(directory: Path, data=SYNTHETIC) -> Path:
    file = directory / "info.json"
    file.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    return file
