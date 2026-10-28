import copy
import json
import tempfile
import unittest
from pathlib import Path

from translateml.config import load_settings
from translateml.extraction import extract
from translateml.rebuild import TOKENS, rebuild
from translateml.sheets.association import associate, check_against_manifest, index_eng, index_eng_by_text
from translateml.sheets.errors import SheetsStructureError
from translateml.sheets.table import Table, column_index, column_letter, load_table, references
from tests.fake_sheets import F, FakeSheets
from tests.helpers import PROFILE, SYNTHETIC, TEST_SETTINGS, write_synthetic
from tests.xlsx_builder import google_formula

GAME = "g999"
UNITS = extract(SYNTHETIC, PROFILE).units
TEXTS = {u.key: u.text for u in UNITS}
ES = {
    "T0001": "REGLAS DEL JUEGO", "T0002": "Juega hasta 50 líneas.",
    "T0003": "##sym_11.png##paga en cualquier posición.", "T0004": "Texto del jackpot",
    "T0005": "REGLAS DEL JUEGO", "T0006": "Línea anidada", "T0007": "ÁRBOL DE\nLUZ",
    "T0008": "DE UN TIPO", "T0009": "DEL MISMO TIPO",
}


def eng_rows(units=UNITS):
    return [["KEY", "TEXT"]] + [[f"{GAME}:{u.key}", u.text] for u in units]


def translate_formula(row, eng_row=None):
    return f'=GOOGLETRANSLATE(ENG!B{eng_row or row};"en";"es")'


def esp_rows(translations=ES, units=UNITS):
    """Pestaña de traducción como la usa Data: una fórmula por fila que apunta a la misma fila de ENG."""
    return [["TEXT"]] + [[F(translate_formula(r), translations.get(u.key, ""))] for r, u in enumerate(units, start=2)]


def tables(fake, tab="ESP"):
    eng = index_eng(load_table(fake, "ENG", 1), "KEY", "TEXT", GAME)
    return eng, load_table(fake, tab, 1)


class TableTest(unittest.TestCase):
    def test_column_letters(self):
        for index, letters in [(0, "A"), (25, "Z"), (26, "AA"), (701, "ZZ"), (702, "AAA")]:
            self.assertEqual(column_letter(index), letters)
            self.assertEqual(column_index(letters), index)

    def test_formula_references(self):
        refs = references('=GOOGLETRANSLATE(ENG!$B$5;"en";"es")&\'ENG\'!C2&OTHER!B1', "ENG")
        self.assertEqual([(r.col, r.row, r.is_range) for r in refs], [(1, 5, False), (2, 2, False)])
        (array,) = references("=ARRAYFORMULA(GOOGLETRANSLATE(eng!B2:B;\"en\";\"de\"))", "ENG")
        self.assertEqual((array.col, array.row, array.end_row, array.is_range), (1, 2, None, True))

    def test_repeated_header_is_rejected(self):
        with self.assertRaisesRegex(SheetsStructureError, "repetida"):
            Table("ENG", 1, [["TEXT", "text"]], [["TEXT", "text"]])


class AssociationTest(unittest.TestCase):
    def test_reads_three_tabs_and_uses_computed_values(self):
        fake = FakeSheets({"ENG": eng_rows(), "ESP": esp_rows(), "DEU": esp_rows({"T0001": "SPIELREGELN"})})
        eng = index_eng(load_table(fake, "ENG", 1), "KEY", "TEXT", GAME)
        self.assertEqual(eng.texts, TEXTS)
        for tab, expected in (("ESP", ES), ("DEU", {"T0001": "SPIELREGELN"})):
            association = associate(load_table(fake, tab, 1), eng, GAME, "KEY", "TEXT", True)
            self.assertEqual(association.texts, expected)
            self.assertEqual(dict(association.methods), {"formula": len(UNITS)})
            self.assertFalse(any(t.startswith("=") for t in association.texts.values()))

    def test_repeated_titles_map_to_their_own_keys(self):
        eng, table = tables(FakeSheets({"ENG": eng_rows(), "ESP": esp_rows()}))
        texts = associate(table, eng, GAME, "KEY", "TEXT", True).texts
        self.assertEqual((texts["T0008"], texts["T0009"]), ("DE UN TIPO", "DEL MISMO TIPO"))
        self.assertEqual((texts["T0001"], texts["T0005"]), ("REGLAS DEL JUEGO", "REGLAS DEL JUEGO"))

    def test_formula_reference_wins_over_position(self):
        # ESP ordenada al revés: cada fórmula sigue apuntando a su fila de ENG.
        rows = [["TEXT"]] + [[F(translate_formula(0, eng_row=r), ES[u.key])]
                             for r, u in reversed(list(enumerate(UNITS, start=2)))]
        eng, table = tables(FakeSheets({"ENG": eng_rows(), "ESP": rows}))
        self.assertEqual(associate(table, eng, GAME, "KEY", "TEXT", True).texts, ES)

    def test_key_column_in_translation_tab(self):
        rows = [["TEXT", "KEY"]] + [[ES[u.key], f"{GAME}:{u.key}"] for u in reversed(UNITS)]
        rows.append(["huérfana", f"{GAME}:T0999"])
        eng, table = tables(FakeSheets({"ENG": eng_rows(), "ESP": rows}))
        association = associate(table, eng, GAME, "KEY", "TEXT", True)
        self.assertEqual(association.texts, ES)
        self.assertEqual([p.kind for p in association.problems], ["unknown_key"])

    def test_array_formula_and_positional_values(self):
        values = [ES[u.key] for u in UNITS]
        array = [["TEXT"], [F('=ARRAYFORMULA(GOOGLETRANSLATE(ENG!B2:B;"en";"es"))', values[0])]] + [[v] for v in values[1:]]
        eng, table = tables(FakeSheets({"ENG": eng_rows(), "ESP": array}))
        association = associate(table, eng, GAME, "KEY", "TEXT", False)
        self.assertEqual(association.texts, ES)
        self.assertEqual(dict(association.methods), {"array_formula": len(UNITS)})

        static = [["TEXT"]] + [[v] for v in values]
        eng, table = tables(FakeSheets({"ENG": eng_rows(), "ESP": static}))
        self.assertEqual(associate(table, eng, GAME, "KEY", "TEXT", True).texts, ES)
        strict = associate(table, eng, GAME, "KEY", "TEXT", False)
        self.assertEqual(strict.texts, {})
        self.assertEqual({p.kind for p in strict.problems}, {"unlinked"})

    def test_ambiguous_and_error_cells_are_not_used(self):
        rows = esp_rows()
        rows[2] = [F(translate_formula(0, eng_row=2), "otra")]  # fila 3 apunta también a la fila 2 de ENG
        rows[4] = [F(translate_formula(5), "#N/A")]
        rows[5] = [F(translate_formula(6), "Loading...")]
        eng, table = tables(FakeSheets({"ENG": eng_rows(), "ESP": rows}))
        association = associate(table, eng, GAME, "KEY", "TEXT", True)
        kinds = sorted((p.kind, p.key) for p in association.problems)
        self.assertEqual(kinds, [("ambiguous", "T0001"), ("formula_error", "T0004"), ("formula_error", "T0005")])
        self.assertNotIn("T0001", association.texts)
        self.assertNotIn("T0002", association.texts)  # su fila quedó sin fórmula propia

    def test_missing_out_of_sync_and_obsolete(self):
        eng_data = eng_rows() + [[f"{GAME}:T0050", "Old rule"]]
        eng_data[2][1] = "Play up to 40 lines."  # Data cambió el inglés de T0002
        translations = dict(ES, T0050="Regla antigua")
        del translations["T0006"]
        units_plus = UNITS + [copy.copy(UNITS[0])]
        units_plus[-1].key = "T0050"
        fake = FakeSheets({"ENG": eng_data, "ESP": esp_rows(translations, units_plus)})
        eng, table = tables(fake)
        association = associate(table, eng, GAME, "KEY", "TEXT", True)
        usable, problems = check_against_manifest(UNITS, eng, association)
        kinds = {(p.kind, p.key, p.blocking) for p in problems}
        self.assertEqual(kinds, {("eng_out_of_sync", "T0002", True), ("missing", "T0006", True),
                                 ("obsolete", "T0050", False)})
        self.assertNotIn("T0002", usable)

    def test_protected_markers_are_validated(self):
        broken = dict(ES, T0003="## sym_11.png ## paga en cualquier posición.")
        eng, table = tables(FakeSheets({"ENG": eng_rows(), "ESP": esp_rows(broken)}))
        usable, _ = check_against_manifest(UNITS, eng, associate(table, eng, GAME, "KEY", "TEXT", True))
        with tempfile.TemporaryDirectory() as tmp:
            from translateml.template import load_template
            template = load_template(write_synthetic(Path(tmp)))
            result = rebuild(template, UNITS, usable, PROFILE)
        self.assertEqual([(i.key, i.kind) for i in result.issues if i.blocking], [("T0003", TOKENS)])
        generated = json.loads(result.text)["rules"]["pages"][0]["items"]["lines"]
        self.assertEqual(generated[2], "   ##sym_11.png##pays anywhere.")
        self.assertEqual(generated[3], "{fixedJackpot}• Texto del jackpot")

    def test_duplicate_key_in_eng_is_ambiguous(self):
        rows = eng_rows() + [[f"{GAME}:T0001", "GAME RULES"]]
        eng = index_eng(load_table(FakeSheets({"ENG": rows}), "ENG", 1), "KEY", "TEXT", GAME)
        self.assertIn("T0001", eng.duplicates)
        self.assertNotIn("T0001", eng.rows)


class LocalFileAssociationTest(unittest.TestCase):
    """Casos propios de un .xlsx descargado: fórmulas exportadas por Google y valores no guardados."""

    def test_google_exported_formula_is_linked_by_its_reference(self):
        rows = [["TEXT"]] + [[F(google_formula(f'GOOGLETRANSLATE(ENG!B{r},"en","es")', ES[u.key]), ES[u.key])]
                             for r, u in reversed(list(enumerate(UNITS, start=2)))]
        eng, table = tables(FakeSheets({"ENG": eng_rows(), "ESP": rows}))
        association = associate(table, eng, GAME, "KEY", "TEXT", False)
        self.assertEqual(association.texts, ES)
        self.assertEqual(dict(association.methods), {"formula": len(UNITS)})

    def test_formula_without_saved_value(self):
        rows = esp_rows()
        rows[1] = [F(translate_formula(2), None)]
        eng, table = tables(FakeSheets({"ENG": eng_rows(), "ESP": rows}))
        association = associate(table, eng, GAME, "KEY", "TEXT", False)
        self.assertEqual([(p.kind, p.key, p.cell) for p in association.problems], [("empty_formula_result", "T0001", "ESP!A2")])
        self.assertNotIn("T0001", association.texts)
        rows = [["TEXT"]] + [[F(translate_formula(r), None)] for r in range(2, len(UNITS) + 2)]
        eng, table = tables(FakeSheets({"ENG": eng_rows(), "ESP": rows}))
        kinds = [p.kind for p in associate(table, eng, GAME, "KEY", "TEXT", False).problems]
        self.assertEqual(kinds.count("no_cached_value"), 1)

    def test_whitespace_only_differs_from_empty(self):
        rows = esp_rows()
        rows[1] = [F(translate_formula(2), "   ")]
        rows[2] = [F(translate_formula(3), "")]
        eng, table = tables(FakeSheets({"ENG": eng_rows(), "ESP": rows}))
        association = associate(table, eng, GAME, "KEY", "TEXT", False)
        self.assertEqual([(p.kind, p.key) for p in association.problems], [("whitespace_only", "T0001")])
        self.assertNotIn("T0002", association.texts)
        usable, problems = check_against_manifest(UNITS, eng, association)
        self.assertIn(("missing", "T0002"), {(p.kind, p.key) for p in problems})

    def test_static_values_are_not_linked_by_position_unless_configured(self):
        static = [["TEXT"]] + [[ES[u.key]] for u in UNITS]
        eng, table = tables(FakeSheets({"ENG": eng_rows(), "ESP": static}))
        association = associate(table, eng, GAME, "KEY", "TEXT", False)
        self.assertEqual(association.texts, {})
        self.assertIn("columna de clave", association.problems[0].detail)

    def test_invalid_keys_in_eng_are_reported(self):
        rows = eng_rows() + [[f"{GAME}:row-7", "Bad"], [f"{GAME}:", "Empty key"]]
        eng = index_eng(load_table(FakeSheets({"ENG": rows}), "ENG", 1), "KEY", "TEXT", GAME)
        self.assertEqual([p.kind for p in eng.problems], ["invalid_key", "invalid_key"])
        self.assertEqual(eng.texts, TEXTS)


class TextAssociationTest(unittest.TestCase):
    """Hoja sin claves ni cabeceras (como el Multidioma real): ENG se relaciona por texto inglés exacto."""

    def eng(self, texts):
        rows = [["", "", "SECTION"]] + [["", str(i), t] for i, t in enumerate(texts, start=1)]
        return rows, index_eng_by_text(load_table(FakeSheets({"ENG": rows}), "ENG", 0), UNITS, "TEXT", "C")

    def test_exact_text_maps_to_every_location(self):
        _, eng = self.eng(["GAME RULES", "OF A KIND", "Nested line"])
        self.assertEqual(eng.keys_by_row, {2: ["T0001", "T0005"], 3: ["T0008", "T0009"], 4: ["T0006"]})
        self.assertEqual([(p.kind, p.cell) for p in eng.problems], [("not_in_template", "ENG!C1")])

    def test_outer_spaces_in_the_cell_are_ignored(self):
        _, eng = self.eng(["Play up to 50 lines. ", "  Nested line", "OF  A KIND"])
        self.assertEqual(eng.keys_by_row, {2: ["T0002"], 3: ["T0006"]})
        self.assertEqual([(p.kind, p.cell) for p in eng.problems], [("not_in_template", "ENG!C1"), ("not_in_template", "ENG!C4")])

    def test_sentence_in_one_cell_maps_to_its_template_lines(self):
        for text in ("Play up to 50 lines. ##sym_11.png##pays anywhere.",
                     "Play up to 50 lines.\n##sym_11.png##pays anywhere.",
                     "  Play up to 50 lines. \r\n  ##sym_11.png##pays anywhere.\n"):
            with self.subTest(text=text):
                _, eng = self.eng([text])
                self.assertEqual(eng.line_groups, {2: [["T0002", "T0003"]]})
                self.assertEqual(eng.texts, {"T0002": "Play up to 50 lines.", "T0003": "##sym_11.png##pays anywhere."})
                self.assertEqual([p.kind for p in eng.problems], ["not_in_template"])  # solo el rótulo SECTION
        _, eng = self.eng(["Play up to 50 lines.\nJackpot text"])  # no son líneas seguidas
        self.assertEqual(eng.line_groups, {})
        self.assertEqual([p.kind for p in eng.problems][-1], "not_in_template")

    def test_a_line_with_its_own_row_is_not_merged(self):
        _, eng = self.eng(["Play up to 50 lines. ##sym_11.png##pays anywhere.", "Play up to 50 lines."])
        self.assertEqual(eng.line_groups, {})
        self.assertEqual(eng.keys_by_row, {3: ["T0002"]})
        self.assertEqual([(p.kind, p.cell) for p in eng.problems],
                         [("not_in_template", "ENG!C1"), ("sentence_overlaps_rows", "ENG!C2")])

    def test_translation_is_split_or_merged(self):
        rows, eng = self.eng(["Play up to 50 lines. ##sym_11.png##pays anywhere."])
        cases = {
            "Juega hasta 50 líneas.\n##sym_11.png##paga en cualquier posición.":
                ({"T0002": "Juega hasta 50 líneas.", "T0003": "##sym_11.png##paga en cualquier posición."}, {}),
            "Juega hasta 50 líneas. ##sym_11.png##paga en cualquier posición.":
                ({"T0002": "Juega hasta 50 líneas. ##sym_11.png##paga en cualquier posición."}, {"T0002": ["T0003"]}),
            "Juega hasta 50 líneas.\n##sym_11.png##paga\nen cualquier posición.":
                ({"T0002": "Juega hasta 50 líneas. ##sym_11.png##paga en cualquier posición."}, {"T0002": ["T0003"]}),
        }
        for value, (texts, merges) in cases.items():
            with self.subTest(value=value):
                esp = [["", "", "SECCIÓN"], ["", "1", F("=ENG!C2", value)]]
                association = associate(load_table(FakeSheets({"ENG": rows, "ESP": esp}), "ESP", 0), eng, GAME, "KEY",
                                        "TEXT", False, "C")
                self.assertEqual((association.texts, association.merges), (texts, merges))
                usable, problems = check_against_manifest(UNITS, eng, association)
                self.assertNotIn("T0003", {p.key for p in problems if p.kind == "missing"})

    def test_translations_follow_formulas_and_conflicts_are_ambiguous(self):
        rows, eng = self.eng(["GAME RULES", "Nested line", "GAME RULES"])
        esp = [["", "", "SECCIÓN"], ["", "1", F("=ENG!C2", "REGLAS")], ["", "2", F("=ENG!C3", "Línea")],
               ["", "3", F("=ENG!C4", "REGLAS")]]
        fake = FakeSheets({"ENG": rows, "ESP": esp})
        association = associate(load_table(fake, "ESP", 0), eng, GAME, "KEY", "TEXT", False, "C")
        self.assertEqual(association.texts, {"T0001": "REGLAS", "T0005": "REGLAS", "T0006": "Línea"})
        self.assertEqual([(p.kind, p.cell) for p in association.problems], [("unlinked", "ESP!C1")])

        esp[3] = ["", "3", F("=ENG!C4", "NORMAS")]
        association = associate(load_table(FakeSheets({"ENG": rows, "ESP": esp}), "ESP", 0), eng, GAME, "KEY", "TEXT",
                                False, "C")
        self.assertEqual(sorted((p.kind, p.key) for p in association.problems if p.kind == "ambiguous"),
                         [("ambiguous", "T0001"), ("ambiguous", "T0005")])


class InspectTest(unittest.TestCase):
    def test_describes_tabs_columns_and_formula_links(self):
        from translateml.config import load_languages
        from translateml.sheets.inspect import inspect_spreadsheet
        from translateml.sheets.settings import load_sheets_config

        languages = load_languages(TEST_SETTINGS.languages_file)
        deu = [["TEXT"]] + [[F(translate_formula(0, eng_row=3), "x")], ["manual"]]
        fake = FakeSheets({"ENG": eng_rows(), "ESP": esp_rows(), "DEU": deu, "Notas": [["a"]]})
        config = load_sheets_config("KEY", "TEXT", file=Path(__file__).parent / "fixtures" / "sheets-key-mode.json")
        report = inspect_spreadsheet(fake, config, languages.enabled, languages.get("eng"))
        self.assertEqual(report["tabs"], ["ENG", "ESP", "DEU", "Notas"])
        self.assertEqual((report["languages"]["eng"]["key_column"], report["languages"]["eng"]["text_column"]), ("A", "B"))
        self.assertEqual(report["languages"]["esp"]["formulas"]["counts"], {"formula_same_row": len(UNITS)})
        self.assertEqual(report["languages"]["deu"]["formulas"]["counts"], {"formula_other_row": 1, "static_value": 1})
        self.assertEqual(len(report["recommendations"]), 2)


if __name__ == "__main__":
    unittest.main()
