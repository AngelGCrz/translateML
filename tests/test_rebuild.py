import json
import tempfile
import unittest
from pathlib import Path

from translateml.extraction import extract
from translateml.jsonpath import format_path, get_value, walk_scalars
from translateml.rebuild import MISSING, NEWLINES, PREFIX, TOKENS, rebuild
from translateml.template import load_template
from translateml.validation import validate_output
from tests.helpers import PROFILE, REAL_TEMPLATES, write_synthetic


def source_texts(extraction):
    return {u.key: u.text for u in extraction.units}


class RoundTripTest(unittest.TestCase):
    def test_english_rebuild_is_byte_identical(self):
        for file in REAL_TEMPLATES:
            with self.subTest(game=file.parent.name):
                template = load_template(file)
                extraction = extract(template.data, PROFILE)
                result = rebuild(template, extraction.units, source_texts(extraction), PROFILE)
                self.assertEqual(result.changes, {})
                self.assertEqual(result.issues, [])
                self.assertEqual(template.encode(result.text), file.read_bytes())
                self.assertEqual(validate_output(template, result.text, result.changes), [])


class TranslationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.template = load_template(write_synthetic(Path(self.tmp.name)))
        self.extraction = extract(self.template.data, PROFILE)
        self.units = {format_path(u.path): u for u in self.extraction.units}

    def tearDown(self):
        self.tmp.cleanup()

    def run_with(self, **overrides):
        texts = source_texts(self.extraction)
        for path, text in overrides.items():
            texts[self.units[path].key] = text
        return rebuild(self.template, self.extraction.units, texts, PROFILE)

    def changed_paths(self, result):
        generated = json.loads(result.text)
        original = dict(walk_scalars(self.template.data))
        return {format_path(p) for p, v in walk_scalars(generated) if original[p] != v}

    def test_single_replacement_changes_only_that_location(self):
        path = "payTables[0].titles[1].text"
        result = self.run_with(**{path: "DE UN TIPO"})
        self.assertEqual(self.changed_paths(result), {path})
        self.assertEqual(get_value(json.loads(result.text), ("payTables", 0, "titles", 2, "text")), "OF A KIND")
        self.assertEqual(validate_output(self.template, result.text, result.changes), [])

    def test_prefix_suffix_and_tokens_are_restored(self):
        result = self.run_with(**{
            "rules.pages[0].items.lines[0]": "Juega hasta 50 líneas.",
            "rules.pages[0].items.lines[2]": "##sym_11.png##paga en cualquier posición.",
            "rules.pages[0].items.lines[3]": "Texto del jackpot",
        })
        lines = json.loads(result.text)["rules"]["pages"][0]["items"]["lines"]
        self.assertEqual(lines, ["• Juega hasta 50 líneas. ", "", "   ##sym_11.png##paga en cualquier posición.",
                                 "{fixedJackpot}• Texto del jackpot", "    6 ##sym_12.png##."])
        self.assertEqual(result.issues, [])

    def test_missing_translation_keeps_english_and_is_reported(self):
        path = "rules.pages[0].titles[0].text"
        texts = source_texts(self.extraction)
        texts[self.units[path].key] = "   "
        del texts[self.units["payTables[0].titles[0].text"].key]
        result = rebuild(self.template, self.extraction.units, texts, PROFILE)
        self.assertEqual(self.changed_paths(result), set())
        self.assertEqual({(i.path, i.kind) for i in result.missing},
                         {(path, MISSING), ("payTables[0].titles[0].text", MISSING)})
        self.assertNotIn("null", result.text.split('"text"')[1][:10])

    def test_lost_symbol_marker_is_rejected(self):
        path = "rules.pages[0].items.lines[2]"
        result = self.run_with(**{path: "paga en cualquier posición."})
        self.assertEqual(self.changed_paths(result), set())
        self.assertEqual([(i.path, i.kind, i.blocking) for i in result.issues], [(path, TOKENS, True)])

    def test_bullet_typed_by_data_is_not_duplicated(self):
        path = "rules.pages[0].items.lines[0]"
        result = self.run_with(**{path: "• Juega hasta 50 líneas."})
        self.assertEqual(json.loads(result.text)["rules"]["pages"][0]["items"]["lines"][0], "• Juega hasta 50 líneas. ")
        self.assertEqual([i.kind for i in result.issues], [PREFIX])

    def test_leading_placeholder_in_translation_is_kept(self):
        data = {"rules": {"pages": [{"items": {"lines": ["Win {amount} now"]}}]}}
        template = load_template(write_synthetic(Path(self.tmp.name), data))
        extraction = extract(template.data, PROFILE)
        result = rebuild(template, extraction.units, {"T0001": "{amount} jetzt gewinnen"}, PROFILE)
        self.assertEqual(json.loads(result.text)["rules"]["pages"][0]["items"]["lines"][0], "{amount} jetzt gewinnen")
        self.assertEqual(result.issues, [])

    def test_newline_change_is_a_warning(self):
        result = self.run_with(**{"payTables[0].titles[0].text": "ÁRBOL DE LUZ"})
        self.assertEqual([(i.kind, i.blocking) for i in result.issues], [(NEWLINES, False)])
        self.assertEqual(self.changed_paths(result), {"payTables[0].titles[0].text"})

    def test_validation_detects_unexpected_changes(self):
        tampered = self.template.text.replace('"rgb(1,1,1)"', '"rgb(9,9,9)"')
        self.assertTrue(validate_output(self.template, tampered, {}))
        self.assertTrue(validate_output(self.template, "{", {}))


if __name__ == "__main__":
    unittest.main()
