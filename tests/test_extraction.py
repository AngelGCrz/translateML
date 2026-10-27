import unittest

from translateml.extraction import extract
from translateml.jsonpath import format_path, nearest_key
from translateml.template import load_template
from tests.helpers import PROFILE, REAL_TEMPLATES, SYNTHETIC


def by_path(extraction):
    return {format_path(u.path): u for u in extraction.units}


class SyntheticExtractionTest(unittest.TestCase):
    def setUp(self):
        self.extraction = extract(SYNTHETIC, PROFILE)
        self.units = by_path(self.extraction)

    def test_extracts_only_configured_texts(self):
        self.assertEqual(sorted(self.units), sorted([
            "rules.pages[0].titles[0].text",
            "rules.pages[0].items.lines[0]",
            "rules.pages[0].items.lines[2]",
            "rules.pages[0].items.lines[3]",
            "rules.pages[1].titles[0].text",
            "rules.pages[1].blocks[0].items.lines[0]",
            "payTables[0].titles[0].text",
            "payTables[0].titles[1].text",
            "payTables[0].titles[2].text",
        ]))

    def test_keys_are_generated_in_document_order(self):
        keys = [u.key for u in self.extraction.units]
        self.assertEqual(keys, [f"T{i:04d}" for i in range(1, len(keys) + 1)])
        self.assertEqual(self.extraction.units[0].path, ("rules", "pages", 0, "titles", 0, "text"))

    def test_repeated_titles_keep_separate_keys(self):
        first, second = self.units["payTables[0].titles[1].text"], self.units["payTables[0].titles[2].text"]
        self.assertEqual(first.text, second.text)
        self.assertNotEqual(first.key, second.key)
        rules = [self.units["rules.pages[0].titles[0].text"], self.units["rules.pages[1].titles[0].text"]]
        self.assertNotEqual(rules[0].key, rules[1].key)

    def test_protected_elements_are_split_off(self):
        line = self.units["rules.pages[0].items.lines[0]"]
        self.assertEqual((line.prefix, line.text, line.suffix), ("• ", "Play up to 50 lines.", " "))
        indented = self.units["rules.pages[0].items.lines[2]"]
        self.assertEqual((indented.prefix, indented.text), ("   ", "##sym_11.png##pays anywhere."))
        self.assertEqual(indented.tokens, ["##sym_11.png##"])
        jackpot = self.units["rules.pages[0].items.lines[3]"]
        self.assertEqual((jackpot.prefix, jackpot.text), ("{fixedJackpot}• ", "Jackpot text"))
        self.assertEqual(self.units["payTables[0].titles[0].text"].text, "TREE OF\nLIGHT")
        for unit in self.extraction.units:
            self.assertEqual(unit.prefix + unit.text + unit.suffix, unit.source)

    def test_technical_fields_are_not_extracted(self):
        technical = {"color", "align", "offset", "tag", "src", "path", "fontName", "size", "scale"}
        for unit in self.extraction.units:
            self.assertNotIn(nearest_key(unit.path), technical)
        audited = {format_path(a.path) for a in self.extraction.audit}
        self.assertNotIn("payTables[0].titles[0].tag", audited)
        self.assertNotIn("fontName", audited)

    def test_layout_strings_are_preserved_not_exported(self):
        kinds = {format_path(s.path): s.kind for s in self.extraction.skipped}
        self.assertEqual(kinds["rules.pages[0].items.lines[1]"], "layout")
        self.assertEqual(kinds["rules.pages[0].items.lines[4]"], "no_letters")

    def test_audit_reports_uncovered_visible_strings(self):
        audited = {format_path(a.path) for a in self.extraction.audit}
        self.assertEqual(audited, {"intro.caption", "rules.pages[1].note", "rules.pages[0].items.lines[4]"})

    def test_missing_sections_are_reported_not_invented(self):
        self.assertEqual(self.extraction.rules_missing, ["payLines[*].titles[*].text"])
        self.assertEqual(self.extraction.rules_found["payline_titles"], 0)


class RealTemplatesExtractionTest(unittest.TestCase):
    EXPECTED = {
        "g402": {"rules_pages": 65, "paytable_titles": 9, "payline_titles": 2},
        "g475": {"rules_pages": 24, "paytable_titles": 0, "payline_titles": 0},
        "g490": {"rules_pages": 44, "paytable_titles": 7, "payline_titles": 1},
        "g500": {"rules_pages": 46, "paytable_titles": 3, "payline_titles": 0},
    }

    def test_counts_per_rule(self):
        for file in REAL_TEMPLATES:
            with self.subTest(game=file.parent.name):
                extraction = extract(load_template(file).data, PROFILE)
                self.assertEqual(extraction.rules_found, self.EXPECTED[file.parent.name])

    def test_only_text_keys_and_lossless_split(self):
        for file in REAL_TEMPLATES:
            with self.subTest(game=file.parent.name):
                extraction = extract(load_template(file).data, PROFILE)
                for unit in extraction.units:
                    self.assertIn(nearest_key(unit.path), PROFILE.text_keys)
                    self.assertEqual(unit.prefix + unit.text + unit.suffix, unit.source)
                    self.assertTrue(unit.text and unit.text == unit.text.strip())

    def test_g475_has_only_rules(self):
        extraction = extract(load_template(REAL_TEMPLATES[1]).data, PROFILE)
        self.assertEqual(sorted(extraction.rules_missing), ["payLines[*].titles[*].text", "payTables[*].titles[*].text"])


if __name__ == "__main__":
    unittest.main()
