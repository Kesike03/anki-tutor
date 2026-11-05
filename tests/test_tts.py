import sys
import types
import unittest

try:
    from PyQt6.QtCore import QObject, pyqtSignal
except ImportError:
    QObject = None
    pyqtSignal = None

if QObject is not None and "aqt" not in sys.modules:
    aqt = types.ModuleType("aqt")
    qt = types.ModuleType("aqt.qt")
    qt.QObject = QObject
    qt.pyqtSignal = pyqtSignal
    sys.modules["aqt"] = aqt
    sys.modules["aqt.qt"] = qt


@unittest.skipIf(QObject is None, "PyQt6 is not installed")
class TTSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tts import prepare_text
        cls.prepare_text = staticmethod(prepare_text)

    def test_prepare_text(self):
        value = "**bold** `code` [link](https://example.com) $x+1$"
        cleaned = self.prepare_text(value)
        self.assertIn("bold", cleaned)
        self.assertIn("code", cleaned)
        self.assertIn("link", cleaned)
        self.assertNotIn("https://", cleaned)
        self.assertNotIn("$x+1$", cleaned)

    def test_code_blocks_are_skipped(self):
        cleaned = self.prepare_text("Hello\n```python\nprint(1)\n```\nWorld")
        self.assertEqual(cleaned, "Hello World")

    def test_code_and_math_can_be_kept(self):
        cleaned = self.prepare_text("Hello `code` $x+1$", skip_code=False, skip_math=False)
        self.assertIn("code", cleaned)
        self.assertIn("x+1", cleaned)
        self.assertNotIn("$", cleaned)

    def test_long_text_is_bounded(self):
        cleaned = self.prepare_text("x" * 20000)
        self.assertLess(len(cleaned), 12100)
        self.assertTrue(cleaned.endswith("..."))


if __name__ == "__main__":
    unittest.main()
