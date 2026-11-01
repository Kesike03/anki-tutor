import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from context import SYSTEM_PROMPT
from i18n import LANGUAGES, STRINGS, tr
from storage import ConversationStore


class StorageTests(unittest.TestCase):
    def test_multiple_conversations_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            store = ConversationStore(path, "profile-a/collection.anki2")
            first = store.create(101, "What is it?", "Vocabulary")
            images = [{"name": "image.png", "mime": "image/png", "data": "cGljdHVyZQ=="}]
            store.add_user_message(first, "First question", "Original prompt", images)
            store.append(first, "assistant", "First answer")
            second = store.create(101, "What is it?", "Vocabulary")
            store.add_user_message(second, "Second question", "Another prompt", [])
            self.assertNotEqual(first, second)
            self.assertEqual(store.active(101), second)
            store.select(101, first)
            self.assertEqual(store.context(first), ("Original prompt", images))
            self.assertEqual(len(store.list_conversations(101)), 2)
            backup = store.export_data()
            self.assertNotIn("api_key", json.dumps(backup))
            store.close()

            reopened = ConversationStore(path, "profile-a/collection.anki2")
            self.assertEqual(reopened.messages(first)[-1]["content"], "First answer")
            self.assertEqual(reopened.active(101), first)
            self.assertEqual(reopened.import_data(backup), (0, 2))
            reopened.delete_card(101)
            self.assertEqual(reopened.list_conversations(), [])
            self.assertEqual(reopened.import_data(backup), (2, 0))
            self.assertEqual(reopened.import_data(backup), (0, 2))
            self.assertEqual(len(reopened.list_conversations(101)), 2)
            reopened.delete_all()
            self.assertIsNone(reopened.active(101))
            reopened.close()

            second_profile = ConversationStore(path, "profile-b/collection.anki2")
            self.assertEqual(second_profile.list_conversations(), [])
            second_profile.close()

    def test_old_profile_migrates_without_losing_messages_or_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            store = ConversationStore(path, "legacy/collection.anki2")
            database = store.path
            store.close()
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, card_id INTEGER, role TEXT, content TEXT, created_at INTEGER)")
            connection.execute("CREATE TABLE contexts (card_id INTEGER PRIMARY KEY, system_prompt TEXT, images_json TEXT)")
            connection.execute("INSERT INTO messages VALUES (1, 44, 'user', 'Old question', 1)")
            connection.execute("INSERT INTO messages VALUES (2, 44, 'assistant', 'Old answer', 2)")
            connection.execute("INSERT INTO contexts VALUES (44, 'Old prompt', '[]')")
            connection.execute("PRAGMA user_version = 0")
            connection.commit()
            connection.close()
            migrated = ConversationStore(path, "legacy/collection.anki2")
            conversation = migrated.active(44)
            self.assertEqual(migrated.messages(conversation)[-1]["content"], "Old answer")
            self.assertEqual(migrated.context(conversation), ("Old prompt", []))
            migrated.close()

    def test_invalid_import_does_not_change_data(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(Path(directory), "profile/collection.anki2")
            backup = {"format": "anki-tutor-history", "version": 1,
                      "conversations": [{"uuid": "bad", "card_id": "wrong"}]}
            with self.assertRaises(ValueError):
                store.import_data(backup)
            self.assertEqual(store.list_conversations(), [])
            store.close()

    def test_branches_restore_their_own_followups_and_attachments(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(Path(directory), "branch/collection.anki2")
            conversation = store.create(17, "Front", "Deck")
            attachment = [{"name": "note.txt", "kind": "text", "mime": "text/plain", "data": "aGVsbG8="}]
            user = store.add_user_message(conversation, "Question", "Tutor", [], attachment)
            answer_a = store.append_branch(conversation, user, "assistant", "Answer A")
            store.append_branch(conversation, answer_a, "user", "Follow-up A")
            answer_b = store.append_branch(conversation, user, "assistant", "Answer B")
            store.append_branch(conversation, answer_b, "user", "Follow-up B")
            self.assertEqual([row["content"] for row in store.messages(conversation)],
                             ["Question", "Answer B", "Follow-up B"])
            store.select_branch(conversation, answer_a)
            self.assertEqual([row["content"] for row in store.messages(conversation)],
                             ["Question", "Answer A", "Follow-up A"])
            edited = store.fork_user(conversation, user, "Edited question")
            store.append_branch(conversation, edited, "assistant", "New answer")
            self.assertEqual(store.messages(conversation)[0]["attachments"], attachment)
            self.assertEqual(store.messages(conversation)[-1]["content"], "New answer")
            backup = store.export_data()
            store.delete_all()
            self.assertEqual(store.import_data(backup), (1, 0))
            restored = store.active(17)
            self.assertEqual(store.messages(restored)[-1]["content"], "New answer")
            original_user = store.messages(restored)[0]
            store.select_branch(restored, store.connection.execute(
                "SELECT id FROM chat_messages WHERE conversation_id = ? AND content = 'Question'", (restored,)
            ).fetchone()[0])
            self.assertEqual(store.messages(restored)[0]["content"], "Question")
            store.close()

    def test_translations_have_every_interface_key(self):
        reference = set(STRINGS["en"])
        self.assertEqual(len(LANGUAGES), 6)
        for language in LANGUAGES:
            self.assertEqual(set(STRINGS[language]), reference, language)
            self.assertEqual(tr(language, "messages", count=3).count("3"), 1)
            self.assertIn("101", tr(language, "card", id=101))
        self.assertEqual(tr("unknown", "send"), "Send")

    def test_packaged_default_matches_source_prompt(self):
        config_path = Path(__file__).resolve().parents[1] / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["system_prompt"], SYSTEM_PROMPT)
        self.assertEqual(config["language"], "auto")


if __name__ == "__main__":
    unittest.main()
