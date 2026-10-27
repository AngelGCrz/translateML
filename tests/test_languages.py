"""Etapa 4: configuración de los 18 idiomas y generación con todos habilitados."""
import copy
import dataclasses
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from translateml.cli import main
from translateml.config import ConfigError, load_languages, load_settings
from tests.helpers import write_synthetic
from tests.xlsx_builder import F, google_formula, write_xlsx

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

REPO_LANGUAGES = json.loads((Path(__file__).resolve().parent / "fixtures" / "languages-3.json").read_text(encoding="utf-8"))
TEXT_MODE = Path(__file__).resolve().parent / "fixtures" / "sheets-text-mode.json"


def languages_file(directory: Path, change=None, enable_all=False) -> Path:
    data = copy.deepcopy(REPO_LANGUAGES)
    if enable_all:
        for language in data["languages"]:
            language["enabled"] = True
    if change:
        change(data)
    file = directory / "languages.json"
    file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return file


class LanguagesConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_repository_config_has_18_independent_languages(self):
        languages = load_languages(load_settings().languages_file)
        self.assertEqual(len(languages.items), 18)
        self.assertTrue(languages.get(languages.source).enabled)
        self.assertEqual(languages.get("zh-hans").folder, "zh-hans")
        self.assertEqual({l.code for l in languages.items}, {
            "eng", "esp", "deu", "ell", "fra", "ido", "ita", "jpn", "kmb", "krs", "mly", "por", "rus", "tha",
            "tur", "vie", "zh-hans", "zh-hant"})

    def test_tab_code_and_folder_can_differ(self):
        def change(data):
            data["languages"][1].update(tab="Español (revisado)", folder="es-ES")
        languages = load_languages(languages_file(self.dir, change))
        esp = languages.get("esp")
        self.assertEqual((esp.code, esp.tab, esp.folder), ("esp", "Español (revisado)", "es-ES"))

    def test_invalid_configurations_are_rejected(self):
        cases = {
            "pestaña": lambda d: d["languages"][4].update(tab=None, enabled=True),
            "nombre simple": lambda d: d["languages"][4].update(folder="../fra"),
            "comparten 'tab'": lambda d: d["languages"][4].update(tab="esp"),
            "comparten 'folder'": lambda d: d["languages"][4].update(folder="ESP"),
            "comparten 'code'": lambda d: d["languages"][4].update(code="ita"),
            "true o false": lambda d: d["languages"][4].update(enabled="yes"),
            "origen": lambda d: d["languages"][0].update(enabled=False),
            "code": lambda d: d["languages"][4].update(code=" "),
        }
        for message, change in cases.items():
            with self.subTest(message):
                with self.assertRaisesRegex(ConfigError, message):
                    load_languages(languages_file(self.dir, change))


def run(settings, *args):
    with mock.patch("translateml.cli.load_settings", return_value=settings), \
            redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
        code = main(list(args))
    return code, out.getvalue() + err.getvalue()


# Traducciones de prueba con escrituras distintas; "GAME RULES" en el idioma real cuando es conocido.
NATIVE_RULES = {"esp": "REGLAS DEL JUEGO", "deu": "SPIELREGELN", "ell": "ΚΑΝΟΝΕΣ ΠΑΙΧΝΙΔΙΟΥ", "jpn": "ゲームルール",
                "krs": "게임 규칙", "rus": "ПРАВИЛА ИГРЫ", "tha": "กฎของเกม", "zh-hans": "游戏规则", "zh-hant": "遊戲規則"}


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl no está instalado")
class EighteenLanguagesFlowTest(unittest.TestCase):
    ENG = ["GAME RULES", "Play up to 50 lines.", "Jackpot text", "TREE OF\nLIGHT", "OF A KIND",
           "##sym_11.png##pays anywhere."]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        (tmp / "tpl").mkdir()
        self.template = write_synthetic(tmp / "tpl")
        self.out = tmp / "out"
        self.xlsx = tmp / "Multidioma.xlsx"
        self.languages = load_languages(languages_file(tmp, enable_all=True))
        self.settings = dataclasses.replace(load_settings(), languages_file=tmp / "languages.json")
        self.assertEqual(run(self.settings, "extract", str(self.template), "--out", str(self.out), "--name", "g999")[0], 0)

    def translation(self, code, text):
        if text == "GAME RULES":
            return NATIVE_RULES.get(code, f"{code.upper()} RULES")
        if "##" in text:
            return f"{code}: ##sym_11.png## {code}"
        return f"{text} ({code})"

    def workbook(self, rename=None, broken=None):
        tabs = {"ENG": [["", "", t] for t in self.ENG]}
        for language in self.languages.items:
            if language.code == "eng":
                continue
            rows = []
            for r, text in enumerate(self.ENG, start=1):
                value = self.translation(language.code, text)
                if broken == language.code and "##" in text:
                    value = value.replace("##sym_11.png##", "#sym_11.png#")
                rows.append(["", "", F(google_formula(f'GOOGLETRANSLATE(ENG!C{r},"en","x")', value), value)])
            tabs[(rename or {}).get(language.tab, language.tab)] = rows
        write_xlsx(self.xlsx, tabs)

    def build(self, *extra):
        return run(self.settings, "xlsx", "--sheets-config", str(TEXT_MODE), "build", str(self.out / "manifest.json"),
                   "--xlsx", str(self.xlsx), *extra)

    def test_generates_all_18_languages(self):
        self.workbook(broken="tha")
        code, output = self.build()
        self.assertEqual(code, 0, output)
        report = json.loads((self.out / "xlsx-build-report.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["languages"]), 18)
        self.assertTrue(all(e["status"] == "generated" for e in report["languages"].values()))
        self.assertEqual((self.out / "eng" / "info.json").read_bytes(), self.template.read_bytes())
        for language in self.languages.items:
            data = json.loads((self.out / language.folder / "info.json").read_text(encoding="utf-8"))
            if language.code == "eng":
                continue
            rules = data["rules"]["pages"]
            self.assertEqual(rules[0]["titles"][0]["text"], self.translation(language.code, "GAME RULES"))
            self.assertEqual(rules[1]["titles"][0]["text"], self.translation(language.code, "GAME RULES"))
            self.assertEqual(rules[0]["items"]["lines"][0], f"• Play up to 50 lines. ({language.code}) ")
            self.assertEqual(rules[0]["items"]["lines"][3], f"{{fixedJackpot}}• Jackpot text ({language.code})")
            expected = "   ##sym_11.png##pays anywhere." if language.code == "tha" else \
                f"   {language.code}: ##sym_11.png## {language.code}"
            self.assertEqual(rules[0]["items"]["lines"][2], expected)
            self.assertEqual(data["payTables"][0]["titles"][0]["tag"], "SCATTER")
        jpn = json.loads((self.out / "jpn" / "info.json").read_text(encoding="utf-8"))
        self.assertEqual(jpn["rules"]["pages"][0]["titles"][0]["text"], "ゲームルール")
        self.assertIn("ゲームルール", (self.out / "jpn" / "info.json").read_text(encoding="utf-8"),
                      "los caracteres no ASCII se escriben tal cual, sin \\u")
        self.assertEqual([i["kind"] for i in report["languages"]["tha"]["marker_issues"]], ["token_mismatch"])
        self.assertEqual(report["languages"]["jpn"]["same_as_english"], [])

    def test_translation_identical_to_english_is_flagged(self):
        original = self.translation
        self.translation = lambda code, text: text if (code == "ido" and text == "OF A KIND") else original(code, text)
        self.workbook()
        code, output = self.build("--lang", "ido")
        self.assertEqual(code, 0, output)
        report = json.loads((self.out / "xlsx-build-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["languages"]["ido"]["same_as_english"], ["T0008", "T0009"])
        self.assertIn("idénticas al inglés", output)

    def test_tab_with_different_case_is_reported_with_a_suggestion(self):
        self.workbook(rename={"ITA": "Ita"})
        code, output = self.build()
        self.assertEqual(code, 1)
        self.assertIn("¿Es 'Ita'?", output)
        self.assertFalse((self.out / "ita" / "info.json").exists())
        self.assertTrue((self.out / "fra" / "info.json").exists())
        code, output = run(self.settings, "xlsx", "--sheets-config", str(TEXT_MODE), "languages", "--xlsx", str(self.xlsx))
        self.assertEqual(code, 1)
        self.assertIn("no (¿Ita?)", output)
        self.assertIn("habilitados sin pestaña en el .xlsx: ita", output)

    def test_only_selected_languages(self):
        self.workbook()
        code, output = self.build("--lang", "jpn,zh-hant")
        self.assertEqual(code, 0, output)
        self.assertEqual(sorted(p.name for p in self.out.iterdir() if (p / "info.json").exists()), ["jpn", "zh-hant"])


if __name__ == "__main__":
    unittest.main()
