import tempfile
import unittest
from pathlib import Path

from usage import UsageStore


class UsageStoreTests(unittest.TestCase):
    def test_usage_aggregation_and_message_attachment(self):
        with tempfile.TemporaryDirectory() as directory:
            store = UsageStore(Path(directory), "profile/collection.anki2")
            event = store.record(
                {"input": 100, "output": 20, "total": 120, "cached": 30},
                model="gpt-test", mode="chat", source="chat",
                conversation_id=7,
            )
            store.record(
                {"input": 50, "output": 10, "total": 60},
                model="gpt-test", mode="chat", source="bulk_fill",
            )
            store.attach([event], 99)
            summary = store.summary()
            self.assertEqual(summary["requests"], 2)
            self.assertEqual(summary["total"], 180)
            self.assertEqual(summary["input"], 150)
            self.assertEqual(summary["output"], 30)
            self.assertEqual(summary["cached"], 30)
            models = store.by_model()
            self.assertEqual(models[0]["model"], "gpt-test")
            self.assertEqual(models[0]["total"], 180)
            self.assertTrue(store.by_day())
            self.assertEqual(store.message_usage(99)["total"], 120)
            self.assertEqual(len(store.recent()), 2)
            store.close()

    def test_empty_store(self):
        with tempfile.TemporaryDirectory() as directory:
            store = UsageStore(Path(directory), "empty/collection.anki2")
            self.assertEqual(store.summary()["requests"], 0)
            self.assertEqual(store.by_model(), [])
            self.assertIsNone(store.message_usage(1))
            store.close()


if __name__ == "__main__":
    unittest.main()
