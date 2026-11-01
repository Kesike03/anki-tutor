import tempfile
import unittest
from pathlib import Path

from attachments import AttachmentError, load_files
from harness import extract_plan, validate_action


class HarnessTests(unittest.TestCase):
    def test_proposed_actions_are_parsed_and_validated(self):
        answer = 'I can make the card.\n```anki-actions\n{"actions":[{"type":"add_card","front":"hola","back":"hello","deck":"Spanish"}]}\n```'
        visible, actions = extract_plan(answer)
        self.assertEqual(visible, "I can make the card.")
        self.assertEqual(actions[0]["type"], "add_card")
        self.assertEqual(extract_plan("Just a question."), ("Just a question.", None))
        for action in (
            {"type": "delete_card", "card_id": -1},
            {"type": "set_review_options", "changes": {"rev.perDay": "infinite"}},
            {"type": "update_anything", "value": "unsafe"},
        ):
            with self.assertRaises(ValueError):
                validate_action(action)

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


if __name__ == "__main__":
    unittest.main()
