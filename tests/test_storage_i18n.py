import tempfile
import unittest
import json
from pathlib import Path

from i18n import LANGUAGES, STRINGS, tr
from storage import ConversationStore


class StorageTests(unittest.TestCase):
    def test_card_and_profile_isolation_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            store = ConversationStore(path, "profile-a/collection.anki2")
            store.append(101, "user", "Question")
            store.append(101, "assistant", "Answer")
            images = [{"name": "image.png", "mime": "image/png", "data": "cGljdHVyZQ=="}]
            store.add_user_message(102, "Other card", "Original prompt", images)
            store.close()

            reopened = ConversationStore(path, "profile-a/collection.anki2")
            self.assertEqual(reopened.messages(101), [
                {"role": "user", "content": "Question"},
                {"role": "assistant", "content": "Answer"},
            ])
            reopened.clear(101)
            self.assertEqual(reopened.messages(101), [])
            self.assertEqual(reopened.messages(102)[0]["content"], "Other card")
            reopened.add_user_message(102, "Second question", "New prompt", [])
            self.assertEqual(reopened.context(102), ("Original prompt", images))
            reopened.clear(102)
            self.assertIsNone(reopened.context(102))
            reopened.close()

            second_profile = ConversationStore(path, "profile-b/collection.anki2")
            self.assertEqual(second_profile.messages(102), [])
            second_profile.close()

    def test_translations_have_every_interface_key(self):
        reference = set(STRINGS["en"])
        self.assertEqual(len(LANGUAGES), 6)
        for language in LANGUAGES:
            self.assertEqual(set(STRINGS[language]), reference, language)
            self.assertEqual(tr(language, "messages", count=3).count("3"), 1)
            self.assertIn("101", tr(language, "card", id=101))
        self.assertEqual(tr("unknown", "send"), "Send")

    def test_packaged_default_matches_source_prompt(self):
        from context import SYSTEM_PROMPT

        config_path = Path(__file__).resolve().parents[1] / "config.json"
        self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["system_prompt"], SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
