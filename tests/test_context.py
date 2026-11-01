import unittest
import base64
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from context import ImageContextError, build_system_prompt, collect_card_images, readable_text


class FakeDatabase:
    def all(self, query, card_id):
        assert "FROM revlog WHERE cid = ?" in query
        assert card_id == 42
        return [(1700000000000, 1, 1, 0, 2500, 800, 0), (1700000100000, 3, 5, 1, 2500, 1200, 1)]


class FakeDecks:
    def name(self, deck_id):
        return "Languages::Spanish" if deck_id == 10 else "Filtered"

    def config_dict_for_deck_id(self, deck_id):
        assert deck_id == 10
        return {"name": "Daily", "new": {"delays": [1, 10]}, "rev": {"maxIvl": 36500}, "lapse": {}, "fsrs": True}


class FakeCard:
    id = 42
    did = 12
    type = 2
    queue = 2
    due = 20
    ivl = 5
    factor = 2500
    reps = 2
    lapses = 1
    left = 0
    desired_retention = 0.9
    memory_state = SimpleNamespace(stability=2.5, difficulty=6.0)

    def current_deck_id(self):
        return 10

    def render_output(self):
        return SimpleNamespace(question_text="<style>.hidden{display:none}</style><div>What is <b>hola</b>?<br><img alt='picture' src='x.png'></div>", answer_text="<div>Hello</div><script>alert('x')</script>")

    def note_type(self):
        return {"name": "Basic"}

    def template(self):
        return {"name": "Front to back"}

    def note(self):
        return SimpleNamespace(tags=["greeting"])


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.card = FakeCard()
        self.collection = SimpleNamespace(db=FakeDatabase(), decks=FakeDecks())

    def test_html_is_readable_without_script_or_css(self):
        text = readable_text("<style>x</style><div>Hi<br>there <img src='photo.jpg'></div><script>bad()</script>")
        self.assertEqual(text, "Hi\nthere [Image: photo.jpg]")

    def test_all_selected_context_is_included(self):
        selected = dict.fromkeys(("context_front", "context_back", "context_deck", "context_schedule", "context_history"), True)
        prompt = build_system_prompt(self.card, self.collection, selected)
        for expected in ("What is hola?", "[Image: picture]", "Hello", "Languages::Spanish", "Daily", "fsrs_memory", "Total recorded reviews: 2", "rating=Again", "rating=Good"):
            self.assertIn(expected, prompt)
        self.assertNotIn("alert(", prompt)
        self.assertNotIn(".hidden", prompt)

    def test_unselected_sections_are_omitted(self):
        prompt = build_system_prompt(self.card, self.collection, {"context_front": True})
        self.assertIn("What is hola?", prompt)
        self.assertNotIn("Card back:", prompt)
        self.assertNotIn("Review history:", prompt)
        self.assertNotIn("Scheduling:", prompt)

    def test_custom_system_prompt(self):
        prompt = build_system_prompt(self.card, self.collection, {"system_prompt": "Teach in Spanish."})
        self.assertTrue(prompt.startswith("Teach in Spanish."))
        self.assertNotIn("You are a helpful assistant", prompt)

    def test_local_images_are_deduplicated_and_respect_selected_sides(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory)
            (media / "front.png").write_bytes(b"front image")
            (media / "back.jpg").write_bytes(b"back image")
            render = SimpleNamespace(
                question_text="<img src='front.png'>",
                answer_text="<img src='front.png'><img src='back.jpg'><img src='../outside.png'>",
            )
            card = SimpleNamespace(render_output=lambda: render)
            col = SimpleNamespace(media=SimpleNamespace(dir=lambda: str(media)))
            selected = {"context_front": True, "context_back": True, "context_images": True}
            images = collect_card_images(card, col, selected)
            self.assertEqual([image["name"] for image in images], ["front.png", "back.jpg"])
            self.assertEqual(base64.b64decode(images[0]["data"]), b"front image")
            selected["context_back"] = False
            self.assertEqual(len(collect_card_images(card, col, selected)), 1)
            selected["context_images"] = False
            self.assertEqual(collect_card_images(card, col, selected), [])
            selected["context_images"] = True
            with patch("context.IMAGE_LIMIT", 5), self.assertRaisesRegex(ImageContextError, "image_error"):
                collect_card_images(card, col, selected)

    def test_data_uri_images(self):
        render = SimpleNamespace(
            question_text="<img src='data:image/png;base64,cGljdHVyZQ=='>",
            answer_text="",
        )
        card = SimpleNamespace(render_output=lambda: render)
        col = SimpleNamespace(media=SimpleNamespace(dir=lambda: "unused"))
        images = collect_card_images(card, col, {"context_front": True})
        self.assertEqual(images[0]["data"], "cGljdHVyZQ==")
        self.assertEqual(readable_text(render.question_text), "[Image: embedded image]")


if __name__ == "__main__":
    unittest.main()
