import unittest

import authoring
from safe_write import SafeWriter


def notetype():
    return {
        "name": "Vocabulary",
        "type": 0,
        "flds": [{"name": "Word"}, {"name": "Definition"}, {"name": "Extra"}],
        "tmpls": [{"qfmt": "{{Word}}", "afmt": "{{FrontSide}}<hr>{{Definition}}"}],
    }


class Note:
    def __init__(self, note_id, fields):
        self.id = note_id
        self._fields = dict(fields)
        self.tags = []

    def keys(self):
        return list(self._fields)

    def __getitem__(self, name):
        return self._fields[name]

    def __setitem__(self, name, value):
        self._fields[name] = value

    def __contains__(self, name):
        return name in self._fields

    def note_type(self):
        return notetype()


class Card:
    def __init__(self, note):
        self.id = 1
        self.did = 1
        self._note = note

    def note(self):
        return self._note


class Collection:
    def __init__(self):
        self.notes = {1: Note(1, {"Word": "hola", "Definition": "", "Extra": "old"})}
        self.next_id = 2
        self.added = []
        self.updated = []
        self.removed = []

    def get_note(self, note_id):
        return self.notes[note_id]

    def get_card(self, _card_id):
        return Card(self.notes[1])

    def update_note(self, note):
        self.updated.append(note.id)

    def new_note(self, _model):
        return Note(0, {"Word": "", "Definition": "", "Extra": ""})

    def add_note(self, note, deck_id):
        note.id = self.next_id
        self.next_id += 1
        self.notes[note.id] = note
        self.added.append((note.id, deck_id))
        return note.id

    def remove_notes(self, note_ids):
        self.removed.extend(note_ids)
        for note_id in note_ids:
            self.notes.pop(note_id, None)

    def remove_cards_and_orphaned_notes(self, card_ids):
        for _card_id in card_ids:
            self.notes.pop(1, None)

    @property
    def models(self):
        class Models:
            @staticmethod
            def get(_mid):
                return notetype()

            @staticmethod
            def by_name(_name):
                return notetype()

        return Models()


class AuthoringTests(unittest.TestCase):
    def test_safe_html_strips_scripts_and_attributes(self):
        value = '<b onclick="bad()">bold</b><script>alert(1)</script><img src=x>'
        self.assertEqual(authoring.safe_html(value), "<b>bold</b>")
        self.assertEqual(authoring.safe_html("a\nb"), "a<br>b")

    def test_markdown_subset(self):
        value = "## Title\n\n- one\n- two\n\n**bold** and `code`"
        result = authoring.markdown_to_html(value)
        self.assertIn("<h2>Title</h2>", result)
        self.assertIn("<ul><li>one</li><li>two</li></ul>", result)
        self.assertIn("<strong>bold</strong>", result)
        self.assertIn("<code>code</code>", result)

    def test_bulk_prompt_and_response(self):
        template = "Write a definition for {Word} in {Language}."
        rendered = authoring.render_prompt(template, {"Word": "hola"})
        self.assertEqual(rendered, "Write a definition for hola in {Language}.")
        self.assertEqual(authoring.unknown_placeholders(template, ["Word"]), ["Language"])
        values, warnings = authoring.parse_bulk_response(
            '```json\n{"definition":"a greeting","_warnings":["check"]}\n```',
            ["definition"],
        )
        self.assertEqual(values, {"definition": "a greeting"})
        self.assertEqual(warnings, ["check"])
        with self.assertRaises(authoring.AuthoringError):
            authoring.parse_bulk_response('{"other":"x"}', ["definition"])

    def test_safe_target_field_avoids_front(self):
        self.assertEqual(authoring.safe_target_field(notetype()), "Extra")
        self.assertEqual(authoring.front_fields(notetype()), {"Word"})

    def test_parse_cards_validates_fields_cloze_and_duplicates(self):
        model = notetype()
        text = (
            '{"cards":['
            '{"fields":{"Word":"hola","Definition":"hello"},"source_quote":"hola = hello"},'
            '{"fields":{"Word":"hola","Definition":"hello"},"source_quote":"again"}'
            '],"warnings":[]}'
        )
        cards, warnings = authoring.parse_cards(
            text, authoring.model_fields(model), False, "", 5
        )
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].fields["Definition"], "hello")
        self.assertTrue(any("duplicate" in warning.lower() for warning in warnings))

        cloze_model = {
            "name": "Cloze",
            "type": 1,
            "flds": [{"name": "Text"}, {"name": "Extra"}],
            "tmpls": [{"qfmt": "{{cloze:Text}}", "afmt": "{{cloze:Text}}"}],
        }
        cards, warnings = authoring.parse_cards(
            '{"cards":[{"fields":{"Text":"The {{c1::capital}} is Paris"}}]}',
            authoring.model_fields(cloze_model), True,
            authoring.cloze_field(cloze_model), 5,
        )
        self.assertEqual(len(cards), 1)
        self.assertTrue(cards[0].fields["Text"].startswith("The "))

    def test_recipe_round_trip(self):
        recipe = authoring.BulkRecipe.from_dict({
            "name": "Definitions",
            "note_type": "Vocabulary",
            "system_prompt": "Be concise.",
            "user_prompt": "Define {Word}",
            "mapping": {"definition": "Definition"},
        })
        self.assertEqual(authoring.BulkRecipe.from_dict(recipe.to_dict()), recipe)
        self.assertEqual(recipe.mapping, {"definition": "Definition"})


class SafeWriteTests(unittest.TestCase):
    def test_field_changes_and_undo(self):
        col = Collection()
        original = col.get_note(1)["Extra"]
        change = authoring.FieldChange(1, "Extra", original, "new value")
        receipt = SafeWriter(col).apply_fields([change])
        self.assertEqual(col.get_note(1)["Extra"], "new value")
        self.assertEqual(col.updated, [1])
        receipt.undo(col)
        self.assertEqual(col.get_note(1)["Extra"], original)

    def test_added_notes_undo(self):
        col = Collection()
        draft = authoring.CardDraft({"Word": "gato", "Definition": "cat", "Extra": ""})
        receipt = SafeWriter(col).add_notes([draft], {}, 7)
        self.assertEqual(col.added, [(2, 7)])
        receipt.undo(col)
        self.assertEqual(col.removed, [2])
        self.assertNotIn(2, col.notes)

    def test_deleted_card_can_be_recreated(self):
        col = Collection()
        original = dict(col.get_note(1)._fields)
        receipt = SafeWriter(col).delete_cards([1])
        self.assertNotIn(1, col.notes)
        receipt.undo(col)
        restored = next(note for note in col.notes.values() if note["Word"] == original["Word"])
        self.assertEqual(restored._fields["Definition"], original["Definition"])

    def test_apply_edit_action(self):
        col = Collection()
        action = {"type": "edit_card", "card_id": 1, "fields": {"Definition": "a greeting"}}
        original = col.get_note(1)["Definition"]
        receipt = SafeWriter(col).apply_action(action, 1, "Vocabulary")
        self.assertEqual(col.get_note(1)["Definition"], "a greeting")
        receipt.undo(col)
        self.assertEqual(col.get_note(1)["Definition"], original)


if __name__ == "__main__":
    unittest.main()
