import json
import tempfile
import unittest
from pathlib import Path

from translateml.jsonpath import expand, format_path, get_value, parse_path, walk_scalars
from translateml.template import TemplateError, load_template
from tests.helpers import REAL_TEMPLATES


class JsonPathTest(unittest.TestCase):
    def test_format_and_parse_round_trip(self):
        path = ("rules", "pages", 0, "items", "lines", 12)
        self.assertEqual(format_path(path), "rules.pages[0].items.lines[12]")
        self.assertEqual(parse_path("rules.pages[0].items.lines[12]"), path)
        self.assertEqual(parse_path("payTables[*].titles[*].text"), ("payTables", "*", "titles", "*", "text"))

    def test_invalid_selector(self):
        for text in ("", "a..b", "a[x]", "a[0"):
            with self.assertRaises(ValueError):
                parse_path(text)

    def test_expand_only_existing_paths(self):
        data = {"payTables": [{"titles": [{"text": "A"}, {"text": "B"}]}, {"images": []}]}
        found = list(expand(data, parse_path("payTables[*].titles[*].text")))
        self.assertEqual(found, [("payTables", 0, "titles", 0, "text"), ("payTables", 0, "titles", 1, "text")])
        self.assertEqual(list(expand(data, parse_path("payLines[*].titles[*].text"))), [])


class TemplateTest(unittest.TestCase):
    def test_real_templates_spans_cover_every_string(self):
        self.assertEqual(len(REAL_TEMPLATES), 4)
        for file in REAL_TEMPLATES:
            with self.subTest(file=file.parent.name):
                template = load_template(file)
                strings = {p for p, v in walk_scalars(template.data) if isinstance(v, str)}
                self.assertEqual(set(template.string_spans), strings)
                self.assertEqual(template.render({}), template.text)

    def test_render_replaces_only_the_literal(self):
        template = load_template(REAL_TEMPLATES[0])
        path = next(iter(template.string_spans))
        start, end = template.string_spans[path]
        rendered = template.render({path: 'Nuevo "texto"\n'})
        self.assertEqual(rendered[:start], template.text[:start])
        self.assertTrue(rendered.endswith(template.text[end:]))
        self.assertEqual(get_value(json.loads(rendered), path), 'Nuevo "texto"\n')

    def test_rejects_duplicate_keys_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "info.json"
            file.write_text('{"rules": {"pages": []}, "rules": {}}', encoding="utf-8")
            with self.assertRaisesRegex(TemplateError, "duplicada"):
                load_template(file)
            file.write_text('{"rules": ', encoding="utf-8")
            with self.assertRaises(TemplateError):
                load_template(file)

    def test_bom_and_escapes_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "info.json"
            raw = b'\xef\xbb\xbf{"t": {"text": "caf\\u00e9 \\"x\\""}, "n": [1.50, -2e3, true, null]}'
            file.write_bytes(raw)
            template = load_template(file)
            self.assertTrue(template.bom)
            self.assertEqual(template.encode(template.render({})), raw)


if __name__ == "__main__":
    unittest.main()
