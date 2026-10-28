"""Comando clean: borra resultados de output/ y nada más."""
import dataclasses
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from translateml.cli import main
from translateml.config import CONFIG_DIR
from tests.helpers import TEST_SETTINGS, write_synthetic


class CleanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        self.output = tmp / "output"
        self.settings = dataclasses.replace(TEST_SETTINGS, output_root=self.output)
        (tmp / "tpl").mkdir()
        self.template = write_synthetic(tmp / "tpl")
        for game in ("g100", "g200"):
            self.assertEqual(self.run_cli("extract", str(self.template), "--name", game)[0], 0)
            (self.output / game / "esp").mkdir()
            (self.output / game / "esp" / "info.json").write_text("{}", encoding="utf-8")
        (self.output / "xlsx-inspect.json").write_text("{}", encoding="utf-8")

    def run_cli(self, *args, settings=None, stdin_tty=False):
        with mock.patch("translateml.cli.load_settings", return_value=settings or self.settings), \
                mock.patch("sys.stdin.isatty", return_value=stdin_tty), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = main(list(args))
        return code, out.getvalue() + err.getvalue()

    def names(self):
        return sorted(str(p.relative_to(self.output)) for p in self.output.rglob("*"))

    def test_clean_one_game(self):
        code, output = self.run_cli("clean", "g100", "--yes")
        self.assertEqual(code, 0, output)
        self.assertFalse((self.output / "g100").exists())
        self.assertTrue((self.output / "g200" / "esp" / "info.json").exists())
        self.assertTrue((self.output / "xlsx-inspect.json").exists())
        self.assertTrue(self.template.exists())

    def test_clean_everything(self):
        code, output = self.run_cli("clean", "--yes")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.names(), [])
        self.assertTrue(self.output.is_dir())
        self.assertIn("No hay nada", self.run_cli("clean", "--yes")[1])

    def test_keep_manifest_preserves_keys(self):
        code, output = self.run_cli("clean", "--keep-manifest", "--yes")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.names(), ["g100", "g100/manifest.json", "g200", "g200/manifest.json"])
        self.assertEqual(self.run_cli("extract", str(self.template), "--name", "g100")[0], 0)
        changes = json.loads((self.output / "g100" / "key-changes.json").read_text(encoding="utf-8"))
        self.assertEqual(changes["summary"]["unchanged"], 9)

    def test_requires_confirmation(self):
        before = self.names()
        code, output = self.run_cli("clean")
        self.assertEqual(code, 2)
        self.assertIn("--yes", output)
        with mock.patch("builtins.input", return_value="n"):
            code, output = self.run_cli("clean", stdin_tty=True)
        self.assertEqual(code, 1)
        self.assertEqual(self.names(), before)
        with mock.patch("builtins.input", return_value="s"):
            self.assertEqual(self.run_cli("clean", "g200", stdin_tty=True)[0], 0)
        self.assertFalse((self.output / "g200").exists())

    def test_refuses_unsafe_targets(self):
        before = self.names()
        for game in ("../tpl", "..", "a/b"):
            with self.subTest(game=game):
                self.assertEqual(self.run_cli("clean", game, "--yes")[0], 2)
        # Aunque la protección fallara, esta prueba no puede borrar nada: el borrado está desactivado.
        no_delete = mock.patch("translateml.cli.shutil.rmtree", side_effect=AssertionError("rmtree"))
        no_unlink = mock.patch("pathlib.Path.unlink", side_effect=AssertionError("unlink"))
        for root in (CONFIG_DIR.parent, Path.home(), Path("/")):
            with self.subTest(root=root), no_delete, no_unlink:
                code, output = self.run_cli("clean", "--yes", settings=dataclasses.replace(self.settings, output_root=root))
                self.assertEqual(code, 2)
                self.assertIn("no es una carpeta de resultados segura", output)
        self.assertEqual(self.names(), before)


if __name__ == "__main__":
    unittest.main()
