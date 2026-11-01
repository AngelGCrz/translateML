"""Lectura de multidioma.docx (Google Docs con una pestaña por idioma) y generación de ENG/ESP/DEU.

Solo usa la biblioteca estándar: estas pruebas no dependen de openpyxl.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from translateml.cli import main
from translateml.config import load_languages
from translateml.sheets.docx import DocxDocument
from translateml.sheets.inspect import inspect_spreadsheet
from translateml.sheets.errors import SheetsConfigError, SheetsReadError, SheetsStructureError
from translateml.sheets.settings import DocxOptions, load_sheets_config
from translateml.sheets.sources import open_source
from tests.docx_builder import write_docx
from tests.helpers import REAL_TEMPLATES, test_settings, write_synthetic

GAME = "g999"


def run(*args):
    with test_settings(), redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
        code = main(list(args))
    return code, out.getvalue() + err.getvalue()


def paytable(t):
    return [[t("TREE OF\nLIGHT"), t("OF A KIND")]]


def rules(t):
    return [["", t("GAME RULES")], ["1", t("Play up to 50 lines.")], ["2", t("Jackpot text")]]


ES = {"TREE OF\nLIGHT": "ÁRBOL DE\nLUZ", "OF A KIND": "DE UN TIPO", "GAME RULES": "REGLAS DEL JUEGO",
      "Play up to 50 lines.": "Juega hasta 50 líneas.", "Jackpot text": "Texto del jackpot"}


def section(t):
    return ["PAYTABLE", paytable(t), rules(t)]


class DocxReaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_sections_are_tabs_in_order_and_cells_are_rows(self):
        file = write_docx(self.dir / "multidioma.docx", [section(lambda s: s), section(lambda s: ES.get(s, s))])
        doc = DocxDocument(file, ["ENG", "ESP"])
        self.assertEqual(doc.tabs(), ["ENG", "ESP"])
        rows = [r[0] for r in doc.read("ESP")]
        self.assertEqual(rows, ["PAYTABLE", "ÁRBOL DE\nLUZ", "DE UN TIPO", "", "REGLAS DEL JUEGO",
                                "", "Juega hasta 50 líneas.", "", "Texto del jackpot"])  # numeración vacía
        self.assertEqual(doc.read("ESP", formulas=True)[0], [""])
        self.assertEqual(doc.labels("ESP")[6], "tabla 2, fila 2, celda 2")
        self.assertIsNone(doc.alignment_problem("ESP", "ENG"))
        self.assertEqual(len(doc.sha256), 64)

    def test_section_count_must_match_the_tab_names(self):
        file = write_docx(self.dir / "multidioma.docx", [section(lambda s: s)] * 3)
        with self.assertRaisesRegex(SheetsStructureError, r'3 pestañas .* 2 nombres.*"docx": \{"tabs"'):
            DocxDocument(file, ["ENG", "ESP"])

    def test_structure_differences_and_invalid_files(self):
        changed = section(lambda s: s)[:2] + [rules(lambda s: s)[:2]]
        file = write_docx(self.dir / "multidioma.docx", [section(lambda s: s), changed])
        doc = DocxDocument(file, ["ENG", "ESP"])
        self.assertIn("elemento 3", doc.alignment_problem("ESP", "ENG"))
        with self.assertRaisesRegex(SheetsStructureError, "no tiene la pestaña 'DEU'"):
            doc.read("DEU")
        bad = self.dir / "bad.docx"
        bad.write_text("no es un zip")
        with self.assertRaises(SheetsReadError):
            DocxDocument(bad, ["ENG"])
        other = self.dir / "multidioma.txt"
        other.write_text("x")
        with self.assertRaisesRegex(SheetsReadError, "no es un .docx"):
            DocxDocument(other, ["ENG"])


    def test_options_control_numbering_and_paragraphs(self):
        file = write_docx(self.dir / "multidioma.docx", [section(lambda s: s)])
        keep_numbers = DocxDocument(file, ["ENG"], DocxOptions(numbering_pattern=""))
        self.assertEqual([r[0] for r in keep_numbers.read("ENG")][5:7], ["1", "Play up to 50 lines."])
        tables_only = DocxDocument(file, ["ENG"], DocxOptions(paragraphs=False))
        self.assertEqual(tables_only.read("ENG")[0], ["TREE OF\nLIGHT"])


class SourceConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def load(self, raw, source_file=None):
        file = self.dir / "sheets.json"
        file.write_text(json.dumps(raw), encoding="utf-8")
        return load_sheets_config("KEY", "TEXT", file=file, source_file=source_file)

    def test_sections_per_format_and_legacy_flat_format(self):
        config = self.load({"xlsx": {"header_row": 0, "text_column": "C", "association": "text"},
                            "docx": {"tabs": ["ENG", "ESP"], "paragraphs": False}})
        self.assertEqual((config.xlsx.text_column, config.xlsx.association), ("C", "text"))
        self.assertEqual(config.docx, DocxOptions(tabs=["ENG", "ESP"], paragraphs=False))
        legacy = self.load({"header_row": 0, "text_column": "C", "docx_tabs": ["ENG"], "xlsx_file": "/tmp/M.xlsx"})
        self.assertEqual((legacy.xlsx.text_column, legacy.docx.tabs, str(legacy.file)), ("C", ["ENG"], "/tmp/M.xlsx"))

    def test_invalid_settings_are_clear_errors(self):
        with self.assertRaisesRegex(SheetsConfigError, "docx: claves desconocidas tab"):
            self.load({"docx": {"tab": ["ENG"]}})
        with self.assertRaisesRegex(SheetsConfigError, "numbering_pattern"):
            self.load({"docx": {"numbering_pattern": "("}})
        with self.assertRaisesRegex(SheetsConfigError, "claves desconocidas xlsx_fil"):
            self.load({"xlsx_fil": "x"})

    def test_reader_is_chosen_by_extension(self):
        languages = load_languages(Path(__file__).parent / "fixtures" / "languages-3.json")
        docx = write_docx(self.dir / "multidioma.docx", [section(lambda s: s)] * 2)
        source = open_source(self.load({"docx": {"tabs": ["ENG", "ESP"]}}, str(docx)), languages)
        self.assertEqual((source.FORMAT, source.tabs()), ("docx", ["ENG", "ESP"]))
        other = self.dir / "multidioma.pdf"
        other.write_text("x")
        with self.assertRaisesRegex(SheetsReadError, "formato no admitido"):
            open_source(self.load({}, str(other)), languages)


class DocxFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        (tmp / "tpl").mkdir()
        self.template = write_synthetic(tmp / "tpl")
        self.out = tmp / "out"
        self.manifest = str(self.out / "manifest.json")
        self.docx = tmp / "multidioma.docx"
        self.config = tmp / "sheets.json"
        self.config.write_text(json.dumps({"docx_tabs": ["ENG", "ESP", "DEU"]}), encoding="utf-8")
        self.assertEqual(run("extract", str(self.template), "--out", str(self.out), "--name", GAME)[0], 0)

    def build(self, *extra):
        return run("xlsx", "--sheets-config", str(self.config), "build", self.manifest, "--docx", str(self.docx), *extra)

    def test_generates_from_language_tabs(self):
        deu = section(lambda s: "DE")
        deu[2] = deu[2][:2]  # DEU con una fila menos: estructura distinta, no se asocia nada
        write_docx(self.docx, [section(lambda s: s), section(lambda s: ES.get(s, s)), deu])
        code, output = self.build()
        self.assertEqual(code, 1, output)
        self.assertEqual((self.out / "eng" / "info.json").read_bytes(), self.template.read_bytes())
        esp = json.loads((self.out / "esp" / "info.json").read_text(encoding="utf-8"))
        pages = esp["rules"]["pages"]
        self.assertEqual([pages[0]["titles"][0]["text"], pages[1]["titles"][0]["text"]], ["REGLAS DEL JUEGO"] * 2)
        self.assertEqual(pages[0]["items"]["lines"][0], "• Juega hasta 50 líneas. ")
        self.assertEqual(pages[0]["items"]["lines"][3], "{fixedJackpot}• Texto del jackpot")
        self.assertEqual([t["text"] for t in esp["payTables"][0]["titles"]], ["ÁRBOL DE\nLUZ", "DE UN TIPO", "DE UN TIPO"])

        report = json.loads((self.out / "xlsx-build-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["source"]["format"], "docx")
        self.assertEqual(report["languages"]["esp"]["status"], "generated")
        self.assertNotIn("warning", report["languages"]["esp"])
        self.assertEqual(report["languages"]["esp"]["association"], {"position": 5})
        self.assertEqual(report["languages"]["deu"]["status"], "error")
        self.assertIn("structure_mismatch", report["languages"]["deu"]["errors"][0])
        cells = [p["cell"] for p in report["eng_problems"]]
        self.assertIn("ENG (párrafo antes de la tabla 1)", cells)  # "PAYTABLE" no está en la plantilla

    def test_inspect_reports_structure_differences(self):
        deu = section(lambda s: "DE")
        deu[2] = deu[2][:2]
        write_docx(self.docx, [section(lambda s: s), section(lambda s: ES.get(s, s)), deu])
        languages = load_languages(Path(__file__).parent / "fixtures" / "languages-3.json")
        source = DocxDocument(self.docx, ["ENG", "ESP", "DEU"])
        report = inspect_spreadsheet(source, source.layout, languages.enabled, languages.get("eng"))
        self.assertIsNone(report["languages"]["esp"]["alignment_problem"])
        self.assertIn("elemento 3", report["languages"]["deu"]["alignment_problem"])
        self.assertTrue(any("DEU: estructura distinta" in tip for tip in report["recommendations"]))

    def test_generate_accepts_docx(self):
        write_docx(self.docx, [section(lambda s: s), section(lambda s: ES.get(s, s)), section(lambda s: s)])
        code, output = run("generate", str(self.template), "--out", str(self.out), "--sheets-config", str(self.config),
                           "--docx", str(self.docx))
        self.assertEqual(code, 0, output)
        self.assertEqual(sorted(p.parent.name for p in self.out.glob("*/info.json")), ["deu", "eng", "esp"])
        code, output = run("docx", "--sheets-config", str(self.config), "languages", "--file", str(self.docx))
        self.assertEqual(code, 0, output)
        self.assertIn("en el .docx", output)


@unittest.skipUnless(os.environ.get("TRANSLATEML_REAL_DOCX"), "define TRANSLATEML_REAL_DOCX con la ruta del archivo real")
class RealDocxTest(unittest.TestCase):
    """Integración con el multidioma.docx real (g490) usando config/sheets.json; no modifica el archivo."""

    def test_builds_g490_from_real_file(self):
        real = Path(os.environ["TRANSLATEML_REAL_DOCX"]).expanduser()
        before = real.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            g490 = next(f for f in REAL_TEMPLATES if f.parent.name == "g490")
            self.assertEqual(run("extract", str(g490), "--out", str(out))[0], 0)
            with redirect_stdout(io.StringIO()) as log:
                code = main(["xlsx", "build", str(out / "manifest.json"), "--docx", str(real)])
            self.assertEqual(code, 0, log.getvalue())
            report = json.loads((out / "xlsx-build-report.json").read_text(encoding="utf-8"))
            self.assertEqual((out / "eng" / "info.json").read_bytes(), g490.read_bytes())
            self.assertGreater(report["languages"]["esp"]["applied"], 30)
        self.assertEqual(real.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
