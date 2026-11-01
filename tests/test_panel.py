"""Offscreen UI smoke test using a small Anki shim and a local HTTP server."""

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


os.environ["QT_QPA_PLATFORM"] = "offscreen"
try:
    from PyQt6 import QtCore, QtGui, QtWidgets
except ImportError:
    QtCore = None


class FakeAddons:
    def __init__(self):
        root = Path(__file__).resolve().parents[1]
        self.config = json.loads((root / "config.json").read_text(encoding="utf-8"))

    def getConfig(self, _module):
        return dict(self.config)

    def writeConfig(self, _module, config):
        self.config = dict(config)


def load_panel():
    anki = types.ModuleType("anki")
    anki.lang = types.ModuleType("anki.lang")
    anki.lang.current_lang = "en_US"
    sys.modules.update({"anki": anki, "anki.lang": anki.lang})
    aqt = types.ModuleType("aqt")
    aqt.qt = types.ModuleType("aqt.qt")
    aqt.theme = types.ModuleType("aqt.theme")
    aqt.webview = types.ModuleType("aqt.webview")
    class FakeWeb(QtWidgets.QWidget):
        def stdHtml(self, *args, **kwargs):
            self.html = (args, kwargs)

        def eval(self, code):
            self.last_js = code

    aqt.webview.AnkiWebView = FakeWeb
    aqt.theme.theme_manager = SimpleNamespace(night_mode=False)
    aqt.gui_hooks = SimpleNamespace(theme_did_change=[])
    for name in (
        "QCheckBox", "QComboBox", "QDockWidget", "QEvent", "QFrame", "QHBoxLayout",
        "QLabel", "QLineEdit", "QMessageBox", "QPlainTextEdit", "QPushButton",
        "QScrollArea", "QSizePolicy", "QStackedWidget", "QStyle", "QTextEdit",
        "QTimer", "QToolButton", "QUrl", "QVBoxLayout", "QWidget", "Qt",
        "QColor", "QPalette", "QTreeWidget", "QTreeWidgetItem", "QDialog",
        "QFileDialog",
    ):
        for source in (QtWidgets, QtCore, QtGui):
            if hasattr(source, name):
                setattr(aqt.qt, name, getattr(source, name))
                break
    sys.modules.update({"aqt": aqt, "aqt.qt": aqt.qt, "aqt.theme": aqt.theme,
                        "aqt.webview": aqt.webview})
    root = Path(__file__).resolve().parents[1]
    package = types.ModuleType("anki_tutor")
    package.__path__ = [str(root)]
    sys.modules["anki_tutor"] = package
    spec = importlib.util.spec_from_file_location("anki_tutor.panel", root / "panel.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["anki_tutor.panel"] = module
    spec.loader.exec_module(module)
    return module.TutorPanel


@unittest.skipIf(QtCore is None, "PyQt6 is not installed")
class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.Panel = load_panel()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.media = Path(self.directory.name)
        self.mw = QtWidgets.QMainWindow()
        self.mw.app = self.app
        self.mw.form = SimpleNamespace(menuView=QtWidgets.QMenu(self.mw))
        self.mw.pm = SimpleNamespace(collectionPath=lambda: str(self.media / "collection.anki2"))
        self.mw.addonManager = FakeAddons()
        self.mw.col = SimpleNamespace(
            decks=SimpleNamespace(name=lambda _id: "Vocabulary", config_dict_for_deck_id=lambda _id: {}),
            db=SimpleNamespace(all=lambda *_args: []),
            media=SimpleNamespace(dir=lambda: str(self.media)),
        )
        self.panel = self.Panel(self.mw)
        self.panel.open_profile()

    def tearDown(self):
        self.panel.close_profile()
        self.mw.close()
        self.directory.cleanup()

    def card(self, id):
        return SimpleNamespace(
            id=id,
            current_deck_id=lambda: 1,
            did=1,
            render_output=lambda: SimpleNamespace(question_text="<b>Hello</b>", answer_text="Hola"),
            note_type=lambda: {"name": "Basic"},
            template=lambda: {"name": "Forward"},
            note=lambda: SimpleNamespace(tags=[]),
            type=2, queue=2, due=1, ivl=2, factor=2500, reps=1, lapses=0,
            left=0, desired_retention=None, memory_state=None,
        )

    def test_panel_local_request_and_card_switch(self):
        captured = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = json.dumps({"choices": [{"message": {"content": "It is a greeting."}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.panel.host_input.setText(f"http://127.0.0.1:{server.server_port}")
            self.panel.key_input.setText("test-key")
            self.panel.prompt_input.setPlainText("Custom tutor instructions")
            self.panel.show_card(self.card(101))
            self.panel.composer.setPlainText("Translate the front")
            self.panel._send()
            self.panel.show_card(self.card(102))
            deadline = time.monotonic() + 5
            while self.panel.pending and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertFalse(self.panel.pending)
            self.assertEqual(captured[0]["messages"][0]["content"].split("\n")[0], "Custom tutor instructions")
            first_id = self.panel.store.active(101)
            self.assertEqual(self.panel.store.messages(first_id)[-1]["content"], "It is a greeting.")
            self.assertIsNone(self.panel.store.active(102))
            self.panel.show_card(self.card(101))
            self.assertTrue(self.panel.covered)
            self.panel._reveal()
            self.assertFalse(self.panel.covered)
            self.panel.language_combo.setCurrentIndex(self.panel.language_combo.findData("zh"))
            self.assertEqual(self.panel.clear_button.toolTip(), "清空对话")
            with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Yes):
                self.panel._clear_chat()
            self.assertIsNone(self.panel.store.active(101))
            self.assertIsNone(self.panel.store.context(first_id))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_floating_panel_can_dock_back_to_right(self):
        self.mw.setCentralWidget(QtWidgets.QWidget())
        self.mw.resize(1100, 720)
        self.mw.show()
        self.app.processEvents()

        self.panel.setFloating(True)
        self.app.processEvents()
        self.assertTrue(self.panel.isFloating())
        self.assertTrue(self.panel.dock_button.isVisible())
        self.assertEqual(self.panel.dock_button.toolTip(), "Dock to Anki")

        self.panel.dock_button.click()
        self.app.processEvents()
        self.assertFalse(self.panel.isFloating())
        self.assertEqual(self.mw.dockWidgetArea(self.panel), QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
        self.assertFalse(self.panel.dock_button.isVisible())

    def test_two_conversations_and_anki_language(self):
        import anki.lang

        anki.lang.current_lang = "zh_CN"
        self.panel._translate()
        self.assertEqual(self.panel.clear_button.toolTip(), "清空对话")
        self.panel.show_card(self.card(101))
        self.panel._new_conversation()
        first = self.panel.conversation_id
        self.panel.store.add_user_message(first, "First question", "Tutor prompt", [])
        self.panel._new_conversation()
        second = self.panel.conversation_id
        self.assertNotEqual(first, second)
        self.panel.conversation_combo.setCurrentIndex(self.panel.conversation_combo.findData(first))
        self.assertEqual(self.panel.conversation_id, first)
        self.panel._show_history()
        self.assertEqual(self.panel.history_dialog.tree.topLevelItemCount(), 1)
        self.assertEqual(self.panel.history_dialog.tree.topLevelItem(0).childCount(), 2)
        self.panel.history_dialog.hide()
        anki.lang.current_lang = "en_US"


if __name__ == "__main__":
    unittest.main()
