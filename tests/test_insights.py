import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import insights


class DB:
    def all(self, sql, *args):
        if "COUNT(*) FROM cards" in sql:
            return [[4]]
        if "ease > 1" in sql and "revlog" in sql:
            return [[10, 8]]
        if "SUM(CASE WHEN ease = 1" in sql:
            return [[5, 2]]
        if "GROUP BY cid" in sql:
            return [[1, 2], [2, 1]]
        return []


class Note:
    def __init__(self, tags):
        self.tags = tags


class Card:
    def __init__(self, card_id, lapses, factor, tags, difficulty=None):
        self.id = card_id
        self.nid = card_id + 100
        self.lapses = lapses
        self.factor = factor
        self.reps = 8
        self.ivl = 3
        self.memory_state = SimpleNamespace(difficulty=difficulty) if difficulty else None
        self._note = Note(tags)

    def note(self):
        return self._note

    def current_deck_id(self):
        return 1

    def render_output(self):
        return SimpleNamespace(
            question_text=f"<b>Question {self.id}</b>",
            answer_text=f"Answer {self.id}",
        )


class Collection:
    def __init__(self):
        self.cards = {
            1: Card(1, 5, 1800, ["leech", "spanish"], 8.5),
            2: Card(2, 2, 2300, ["verbs"], None),
        }
        self.db = DB()
        self.decks = SimpleNamespace(name=lambda _did: "Spanish")

    def find_cards(self, query):
        if query == "is:due":
            return [1, 2]
        if query == "is:new":
            return [3]
        if query == "is:learn":
            return [4]
        if query == "is:leech":
            return [1]
        if query.startswith("prop:lapses"):
            return [1, 2]
        if query.startswith("rated:"):
            return [1, 2]
        if query == "":
            return list(self.cards)
        return []

    def get_card(self, card_id):
        return self.cards[card_id]


class InsightsTests(unittest.TestCase):
    def test_analyze_and_brief(self):
        result = insights.analyze(
            Collection(), now=datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
        )
        self.assertEqual((result.due, result.new, result.learning), (2, 1, 1))
        self.assertEqual(result.total, 4)
        self.assertEqual(result.reviews_30d, 10)
        self.assertAlmostEqual(result.retention_30d, 0.8)
        self.assertEqual(result.today_again, 2)
        self.assertEqual(len(result.weak_cards), 2)
        self.assertEqual(result.weak_cards[0].card_id, 1)
        self.assertIn("leech", result.weak_cards[0].reasons)
        self.assertEqual(result.weak_decks[0].name, "Spanish")
        self.assertTrue(any(area.name == "spanish" for area in result.weak_tags))
        text = insights.brief(result)
        self.assertIn("not a review order", text)
        self.assertIn("Question 1", text)
        self.assertIn("Weak tags", text)

    def test_context_text_contains_actionable_shape(self):
        result = insights.analyze(Collection(), now=datetime(2026, 11, 5, tzinfo=timezone.utc))
        text = result.context_text()
        self.assertIn("due now", text)
        self.assertIn("Weak decks", text)
        self.assertIn("Weak-card examples", text)


if __name__ == "__main__":
    unittest.main()
