import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from translateml.cli import main
from tests.helpers import REAL_TEMPLATES, test_settings


def run(*args):
    with test_settings(), redirect_stdout(io.StringIO()) as out:
        code = main(list(args))
    return code, out.getvalue()


class CliFlowTest(unittest.TestCase):
    """Etapa 1 completa: extraer, exportar a CSV y reconstruir desde el formato intermedio."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.template = REAL_TEMPLATES[0]
        code, _ = run("extract", str(self.template), "--out", str(self.out))
        self.assertEqual(code, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_extract_writes_intermediate_files(self):
        for name in ("manifest.json", "extracted.csv", "extraction-report.json"):
            self.assertTrue((self.out / name).is_file(), name)
        with (self.out / "extracted.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 76)
        self.assertEqual(rows[0]["KEY"], "T0001")

    def test_rebuild_english_copy_from_csv_is_identical(self):
        code, _ = run("rebuild", str(self.out / "manifest.json"), "--texts", str(self.out / "extracted.csv"))
        self.assertEqual(code, 0)
        self.assertEqual((self.out / "eng" / "info.json").read_bytes(), self.template.read_bytes())

    def test_rebuild_with_edited_csv_changes_one_text(self):
        csv_file = self.out / "extracted.csv"
        with csv_file.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["TEXT"] = "HADA"
        with csv_file.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        code, _ = run("rebuild", str(self.out / "manifest.json"), "--texts", str(csv_file), "--lang", "esp")
        self.assertEqual(code, 0)
        original = json.loads(self.template.read_text(encoding="utf-8"))
        generated = json.loads((self.out / "esp" / "info.json").read_text(encoding="utf-8"))
        original["payTables"][0]["titles"][0]["text"] = "HADA"
        self.assertEqual(generated, original)

    def test_disabled_language_is_refused(self):
        with test_settings(), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = main(["rebuild", str(self.out / "manifest.json"), "--lang", "fra"])
        self.assertIn("no está habilitado", err.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse((self.out / "fra").exists())

    def test_verify_all_real_templates(self):
        code, output = run("verify", *map(str, REAL_TEMPLATES))
        self.assertEqual(code, 0, output)


if __name__ == "__main__":
    unittest.main()
