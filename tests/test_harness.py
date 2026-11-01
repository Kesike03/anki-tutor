import tempfile
import unittest
from pathlib import Path

from types import SimpleNamespace

from attachments import AttachmentError, load_files, local_file_references
from harness import extract_plan, extract_queries, instructions_for, validate_action


class HarnessTests(unittest.TestCase):
    def test_proposed_actions_are_parsed_and_validated(self):
        answer = 'I can make the card.\n```anki-actions\n{"actions":[{"type":"add_card","front":"hola","back":"hello","deck":"Spanish"}]}\n```'
        visible, actions = extract_plan(answer)
        self.assertEqual(visible, "I can make the card.")
        self.assertEqual(actions[0]["type"], "add_card")
        middle = 'Let me update it.\n```anki-actions\n{"actions":[{"type":"delete_card","card_id":3}]}\n```\nI will wait for your confirmation.'
        visible, actions = extract_plan(middle)
        self.assertEqual(visible, "Let me update it.\n\nI will wait for your confirmation.")
        self.assertEqual(actions[0]["type"], "delete_card")
        self.assertEqual(extract_plan("Just a question."), ("Just a question.", None))
        generic = 'Change queued.\n```json\n{"actions":[{"type":"delete_card","card_id":2}]}\n```\nConfirm it in Anki.'
        self.assertEqual(extract_plan(generic)[1][0]["type"], "delete_card")
        for action in (
            {"type": "delete_card", "card_id": -1},
            {"type": "set_review_options", "changes": {"rev.perDay": "infinite"}},
            {"type": "update_anything", "value": "unsafe"},
        ):
            with self.assertRaises(ValueError):
                validate_action(action)

    def test_queries_and_hidden_permission_context(self):
        answer = 'Let me inspect.\n```anki-query\n{"queries":[{"tool":"search_cards","query":"is:due","limit":5}]}\n```\nOne moment.'
        visible, queries = extract_queries(answer)
        self.assertEqual(queries[0]["tool"], "search_cards")
        self.assertEqual(visible, "Let me inspect.\n\nOne moment.")
        card = SimpleNamespace(
            id=7, current_deck_id=lambda: 1,
            note_type=lambda: {"name": "Basic"},
            note=lambda: SimpleNamespace(keys=lambda: ["Front", "Back"]),
        )
        col = SimpleNamespace(
            decks=SimpleNamespace(
                name=lambda _id: "Default",
                all_names_and_ids=lambda: [SimpleNamespace(name="Default")],
            ),
            models=SimpleNamespace(all_names_and_ids=lambda: [SimpleNamespace(name="Basic")]),
        )
        prompt = instructions_for(card, col, {"auto_approve_actions": True})
        self.assertIn("DIRECT_WRITE_ALLOWED", prompt)
        self.assertIn('"auto_approve_actions": true', prompt)
        prompt = instructions_for(card, col, {"auto_approve_actions": False})
        self.assertIn("USER_CONFIRMATION_REQUIRED", prompt)

    def test_attachment_types(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "diagram.png"
            image.write_bytes(b"png")
            document = root / "chapter.pdf"
            document.write_bytes(b"pdf")
            text = root / "notes.md"
            text.write_text("study", encoding="utf-8")
            result = load_files([str(image), str(document), str(text)])
            self.assertEqual([file["kind"] for file in result], ["image", "pdf", "text"])
            unsupported = root / "unrecognized.bin"
            unsupported.write_bytes(b"binary")
            with self.assertRaises(AttachmentError):
                load_files([str(unsupported)])
            cleaned, paths = local_file_references(f"{image.as_uri()} 你看得到吗？")
            self.assertEqual(cleaned, "你看得到吗？")
            self.assertEqual(paths, [str(image)])
            cleaned, paths = local_file_references(f"查看 {image} 这张图")
            self.assertEqual(paths, [str(image)])
            self.assertEqual(cleaned, "查看 这张图")


if __name__ == "__main__":
    unittest.main()
