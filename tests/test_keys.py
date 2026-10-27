import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from translateml.cli import main
from translateml.extraction import extract
from translateml.keys import reconcile
from translateml.jsonpath import format_path
from tests.helpers import PROFILE, SYNTHETIC, write_synthetic


def keys_by_path(units):
    return {format_path(u.path): u.key for u in units}


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.before = extract(SYNTHETIC, PROFILE).units
        self.data = copy.deepcopy(SYNTHETIC)

    def reextract(self):
        units = extract(self.data, PROFILE).units
        return units, reconcile(self.before, units, len(self.before) + 1)

    def test_unchanged_template_keeps_all_keys(self):
        units, changes = self.reextract()
        self.assertEqual([u.key for u in units], [u.key for u in self.before])
        self.assertEqual(changes.summary()["unchanged"], len(units))

    def test_inserted_line_does_not_shift_following_keys(self):
        self.data["rules"]["pages"][0]["items"]["lines"].insert(0, "• A brand new rule.")
        units, changes = self.reextract()
        texts = [u.text for u in self.before]
        old = {u.text: u.key for u in self.before if texts.count(u.text) == 1}
        for unit in units:
            if unit.text in old:
                self.assertEqual(unit.key, old[unit.text], unit.text)
        self.assertEqual(changes.added, ["T0010"])
        self.assertEqual(len(changes.moved), 3)  # tres líneas cambian de índice

    def test_modified_text_keeps_key_and_is_reported(self):
        self.data["payTables"][0]["titles"][1]["text"] = "OF ANY KIND"
        units, changes = self.reextract()
        self.assertEqual(keys_by_path(units), keys_by_path(self.before))
        self.assertEqual([(m["key"], m["old"], m["new"]) for m in changes.modified], [("T0008", "OF A KIND", "OF ANY KIND")])

    def test_repeated_titles_keep_their_own_keys(self):
        del self.data["payTables"][0]["titles"][0]
        units, changes = self.reextract()
        kinds = [u.key for u in units if u.text == "OF A KIND"]
        self.assertEqual(kinds, ["T0008", "T0009"])
        self.assertEqual([r["key"] for r in changes.removed], ["T0007"])

    def test_removed_keys_are_not_reused(self):
        del self.data["payTables"][0]["titles"][2]
        units, changes = self.reextract()
        self.assertEqual(changes.next_key, 10)
        self.data["payTables"][0]["titles"].append({"text": "NEW TITLE"})
        later = extract(self.data, PROFILE).units
        changes = reconcile(units, later, changes.next_key)
        self.assertEqual(changes.added, ["T0010"])


class ExtractCommandKeysTest(unittest.TestCase):
    def test_second_extract_reuses_keys_from_previous_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            template_dir, out = tmp / "tpl", tmp / "out"
            template_dir.mkdir()
            file = write_synthetic(template_dir)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["extract", str(file), "--out", str(out), "--name", "g999"]), 0)
                data = copy.deepcopy(SYNTHETIC)
                data["rules"]["pages"][0]["titles"].insert(0, {"text": "INTRO"})
                write_synthetic(template_dir, data)
                self.assertEqual(main(["extract", str(file), "--out", str(out)]), 0)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["game"], "g999")
            self.assertEqual(manifest["units"][0]["text"], "INTRO")
            self.assertEqual(manifest["units"][0]["key"], "T0010")
            self.assertEqual(manifest["units"][1]["key"], "T0001")
            changes = json.loads((out / "key-changes.json").read_text(encoding="utf-8"))
            self.assertEqual(changes["added"], ["T0010"])


if __name__ == "__main__":
    unittest.main()
