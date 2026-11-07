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

        def set_bridge_command(self, handler, context):
            self.bridge = handler

    aqt.webview.AnkiWebView = FakeWeb
    aqt.theme.theme_manager = SimpleNamespace(night_mode=False)
    aqt.gui_hooks = SimpleNamespace(theme_did_change=[])
    for name in (
        "QCheckBox", "QComboBox", "QDockWidget", "QEvent", "QFrame", "QHBoxLayout",
        "QLabel", "QLineEdit", "QMessageBox", "QPlainTextEdit", "QPushButton",
        "QScrollArea", "QSizePolicy", "QStackedWidget", "QStyle", "QTextEdit",
        "QTimer", "QToolButton", "QUrl", "QVBoxLayout", "QWidget", "Qt",
        "QColor", "QPalette", "QTreeWidget", "QTreeWidgetItem", "QDialog",
        "QFileDialog", "QInputDialog", "QListWidget", "QListWidgetItem", "QApplication",
        "QBuffer", "QIODevice", "QImage", "QSpinBox", "QAbstractItemView",
        "QHeaderView", "QProgressBar", "QTableWidget", "QTableWidgetItem",
        "QObject", "QDialogButtonBox", "QGroupBox", "QFormLayout", "QGridLayout",
        "QDoubleSpinBox", "QTabWidget",
    ):
        for source in (QtWidgets, QtCore, QtGui):
            if hasattr(source, name):
                setattr(aqt.qt, name, getattr(source, name))
                break
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
    aqt.qt.QObject = QObject
    aqt.qt.pyqtSignal = pyqtSignal
    aqt.qt.QNetworkAccessManager = QNetworkAccessManager
    aqt.qt.QNetworkReply = QNetworkReply
    aqt.qt.QNetworkRequest = QNetworkRequest
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

    def test_dragged_file_becomes_an_attachment(self):
        self.panel.show_card(self.card(101))
        image = QtGui.QImage(4, 4, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("red"))
        path = self.media / "drag.png"
        self.assertTrue(image.save(str(path)))
        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(str(path))])
        self.panel.composer.insertFromMimeData(mime)
        self.assertEqual(len(self.panel.attachments), 1)
        self.assertEqual(self.panel.attachments[0]["kind"], "image")
        self.assertEqual(self.panel.attachments[0]["name"], "drag.png")

    def test_attachment_removal_selects_and_deletes_the_right_file(self):
        self.panel.show_card(self.card(101))
        first = self.media / "first.png"
        second = self.media / "second.png"
        for path in (first, second):
            path.write_bytes(b"image")
        self.panel._attach_paths([str(first), str(second)])
        self.assertEqual(self.panel.attachment_list.count(), 2)
        self.assertEqual(self.panel.attachment_list.currentRow(), 1)
        self.panel.attachment_list.setCurrentRow(0)
        self.panel._remove_attachment()
        self.assertEqual([item["name"] for item in self.panel.attachments], ["second.png"])
        self.assertEqual(self.panel.attachment_list.currentRow(), 0)
        self.panel.attachment_list.setCurrentRow(-1)
        self.panel.remove_attachment_button.click()
        self.assertEqual(self.panel.attachments, [])
        self.assertFalse(self.panel.attachment_list.isVisible())

    def test_action_response_is_dispatched_and_followed_up(self):
        captured = []
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                if len(requests) == 1:
                    content = 'Done.\n```anki-actions\n{"actions":[{"type":"delete_card","card_id":1}]}\n```\nThe action is waiting for your confirmation.'
                else:
                    content = "The requested change is complete."
                body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
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
            self.panel.show_card(self.card(101))
            self.panel._ask_action_approval = lambda actions, *_: True
            self.panel._execute_actions = lambda actions, *_: captured.extend(actions) or "1. delete_card: applied"
            self.panel.composer.setPlainText("Delete this card")
            self.panel._send()
            deadline = time.monotonic() + 5
            while self.panel.pending and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertEqual(captured[0]["type"], "delete_card")
            self.assertEqual(len(requests), 2)
            final = self.panel.store.messages(self.panel.conversation_id)[-1]["content"]
            self.assertEqual(final, "The requested change is complete.")
            instructions = requests[0]["messages"][0]["content"]
            self.assertIn("Hidden user settings:", instructions)
            self.assertIn("USER_CONFIRMATION_REQUIRED", instructions)
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
        self.app.processEvents()
        self.assertTrue(self.panel.isFloating())
        self.assertTrue(self.panel.dock_button.isVisible())
        self.assertEqual(self.panel.dock_button.toolTip(), "Dock to Anki")
        self.assertGreaterEqual(self.panel.width(), 600)
        self.assertGreaterEqual(self.panel.height(), 480)
        self.assertEqual(self.panel.minimumWidth(), 420)

        self.panel.dock_button.click()
        self.app.processEvents()
        self.app.processEvents()
        self.assertFalse(self.panel.isFloating())
        self.assertEqual(self.mw.dockWidgetArea(self.panel), QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
        self.assertFalse(self.panel.dock_button.isVisible())
        self.assertEqual(self.panel.minimumWidth(), 240)
        self.assertLessEqual(self.panel.width(), 500)

    def test_settings_open_as_dialog_and_font_size_applies(self):
        self.panel._open_settings()
        self.assertIsNotNone(self.panel.settings_dialog)
        self.assertIs(self.panel.settings_tabs.parent(), self.panel.settings_dialog)
        self.assertTrue(self.panel.settings_dialog.isVisible())
        self.assertEqual(self.panel.settings_tabs.count(), 4)
        self.assertIs(self.panel.settings_tabs.widget(3), self.panel.usage_page)
        self.assertEqual(self.panel.usage_page.range_combo.count(), 5)
        self.assertEqual(self.panel.usage_page.range_combo.itemData(1), 1)
        self.panel.font_size_spin.setValue(20)
        self.assertEqual(self.panel.config["font_size"], 20)
        self.assertEqual(self.panel._applied_font_size, 20)
        self.assertIn("font-size: 20px", self.panel.styleSheet())
        self.panel.tts_rate_spin.setValue(0.2)
        self.assertAlmostEqual(self.panel.config["tts_rate"], 0.2)
        self.panel.tts_skip_code_check.setChecked(False)
        self.assertFalse(self.panel.config["tts_skip_code"])
        self.panel.settings_dialog.close()

    def test_settings_dialog_survives_profile_reopen(self):
        self.panel._open_settings()
        self.panel.close_profile()
        self.panel.open_profile()
        self.panel._open_settings()
        self.assertIsNotNone(self.panel.settings_dialog)
        self.assertIs(self.panel.settings_tabs.parent(), self.panel.settings_dialog)
        self.panel.settings_dialog.close()


    def test_authoring_dialogs_open_and_write_with_undo(self):
        from authoring_dialog import SaveReplyDialog
        from bulk_fill import BulkFillDialog

        model = {
            "name": "Vocabulary",
            "type": 0,
            "flds": [{"name": "Front"}, {"name": "Back"}, {"name": "Extra"}],
            "tmpls": [{"qfmt": "{{Front}}", "afmt": "{{Back}}"}],
        }

        class Note:
            def __init__(self):
                self.id = 55
                self._values = {"Front": "hola", "Back": "hello", "Extra": ""}
                self.tags = []

            def keys(self):
                return list(self._values)

            def note_type(self):
                return model

            def __getitem__(self, name):
                return self._values[name]

            def __setitem__(self, name, value):
                self._values[name] = value

            def __contains__(self, name):
                return name in self._values

        note = Note()
        card = SimpleNamespace(
            id=1, did=1, note=lambda: note, note_type=lambda: model,
            current_deck_id=lambda: 1,
        )
        self.mw.col.get_note = lambda _note_id: note
        self.mw.col.update_note = lambda _note: None
        dialog = SaveReplyDialog(self.mw, card, self.panel.config, "Study note", parent=self.mw)
        dialog.field_combo.setCurrentText("Extra")
        dialog._save()
        self.assertIn("Study note", note["Extra"])
        self.assertTrue(dialog.undo_button.isEnabled())
        dialog._undo()
        self.assertEqual(note["Extra"], "")
        dialog.close()

        bulk = BulkFillDialog(self.mw, [55], self.panel.config, parent=self.mw)
        self.assertEqual(bulk.model_combo.currentText(), "Vocabulary")
        self.assertEqual(bulk.fields, ["Front", "Back", "Extra"])
        bulk.close()


    def test_bulk_fill_generates_previews_and_applies_undo(self):
        from bulk_fill import BulkFillDialog

        model = {
            "name": "Vocabulary",
            "type": 0,
            "flds": [{"name": "Front"}, {"name": "Back"}, {"name": "Extra"}],
            "tmpls": [{"qfmt": "{{Front}}", "afmt": "{{Back}}"}],
        }

        class Note:
            def __init__(self):
                self.id = 77
                self._values = {"Front": "hola", "Back": "hello", "Extra": ""}
                self.tags = []

            def keys(self):
                return list(self._values)

            def note_type(self):
                return model

            def __getitem__(self, name):
                return self._values[name]

            def __setitem__(self, name, value):
                self._values[name] = value

            def __contains__(self, name):
                return name in self._values

        note = Note()
        self.mw.col.get_note = lambda _note_id: note
        self.mw.col.update_note = lambda _note: None

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                body = json.dumps({"choices": [{"message": {
                    "content": '{"definition":"a greeting","warnings":[]}'
                }}]}).encode()
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
            self.panel._save_settings()
            dialog = BulkFillDialog(self.mw, [77], self.panel.config, parent=self.mw)
            dialog.mapping_rows[0][1].setText("definition")
            dialog.mapping_rows[0][2].setCurrentText("Extra")
            dialog.user_edit.setPlainText("Define {Front}")
            dialog._generate()
            deadline = time.monotonic() + 5
            while dialog.pages.currentIndex() == 0 and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertEqual(dialog.pages.currentIndex(), 1)
            self.assertEqual(len(dialog.changes), 1)
            dialog._apply()
            self.assertEqual(note["Extra"], "a greeting")
            dialog._undo()
            self.assertEqual(note["Extra"], "")
            dialog.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


    def test_conversation_cards_dialog_generates_and_adds(self):
        from authoring_dialog import ConversationCardsDialog

        model = {
            "name": "Vocabulary", "type": 0,
            "flds": [{"name": "Front"}, {"name": "Back"}, {"name": "Extra"}],
            "tmpls": [{"qfmt": "{{Front}}", "afmt": "{{Back}}"}],
        }

        class Note:
            def __init__(self, note_id=0):
                self.id = note_id
                self._values = {"Front": "hola", "Back": "hello", "Extra": ""}
                self.tags = []

            def keys(self):
                return list(self._values)

            def __getitem__(self, name):
                return self._values[name]

            def __setitem__(self, name, value):
                self._values[name] = value

            def __contains__(self, name):
                return name in self._values

        note = Note(88)
        card = SimpleNamespace(
            id=1, did=1, note=lambda: note, note_type=lambda: model,
            current_deck_id=lambda: 1,
        )
        added = []
        self.mw.col.models = SimpleNamespace(all=lambda: [model], get=lambda _mid: model, by_name=lambda _name: model)
        self.mw.col.decks = SimpleNamespace(
            name=lambda _did: "Vocabulary",
            all_names_and_ids=lambda: [SimpleNamespace(name="Vocabulary")],
            id_for_name=lambda _name: 1,
        )
        self.mw.col.new_note = lambda _model: Note()
        self.mw.col.add_note = lambda current, deck_id: (setattr(current, "id", 90 + len(added)), added.append(deck_id), current.id)[2]
        self.mw.col.remove_notes = lambda ids: [added.clear() for _ in ids]

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                content = json.dumps({
                    "cards": [{"fields": {
                        "Front": "gato", "Back": "cat", "Extra": "animal",
                    }, "source_quote": "gato means cat"}],
                    "warnings": [],
                })
                body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
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
            self.panel._save_settings()
            dialog = ConversationCardsDialog(
                self.mw, card, self.panel.config,
                [{"role": "user", "content": "Make a card"}], parent=self.mw,
            )
            deadline = time.monotonic() + 5
            while not getattr(dialog, "_cards", None) and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertEqual(len(dialog._cards), 1)
            dialog._add()
            self.assertEqual(added, [1])
            dialog._undo()
            self.assertEqual(added, [])
            dialog.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


    def test_collection_home_and_collection_chat(self):
        self.panel._refresh_home(force=True)
        self.assertEqual(self.panel.pages.currentWidget(), self.panel.home_view)
        self.assertIn("0", self.panel.home_view.summary.text())
        self.panel._start_collection_chat("What is due today?")
        self.assertTrue(self.panel.collection_chat_open)
        self.assertIsNone(self.panel.card)
        self.assertEqual(self.panel.conversation_id, self.panel.store.active(0))
        self.assertEqual(self.panel.composer.toPlainText(), "What is due today?")
        prompt = self.panel._collection_prompt()
        self.assertIn("Anki collection snapshot", prompt)
        self.panel._show_home()
        self.assertFalse(self.panel.collection_chat_open)
        self.assertEqual(self.panel.pages.currentWidget(), self.panel.home_view)
        self.assertIsNone(self.panel.conversation_id)


    def test_collection_chat_sends_collection_context(self):
        captured = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = json.dumps({"choices": [{"message": {"content": "Three decks."}}]}).encode()
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
            self.panel._save_settings()
            self.panel._start_collection_chat("What is due?")
            self.panel._send()
            deadline = time.monotonic() + 5
            while self.panel.pending and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertFalse(self.panel.pending)
            instructions = captured[0]["messages"][0]["content"]
            self.assertIn("COLLECTION MODE", instructions)
            self.assertIn("Anki collection snapshot", instructions)
            self.assertIn("Three decks.", self.panel.store.messages(self.panel.store.active(0))[-1]["content"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


    def test_weak_areas_dialog_opens(self):
        from insights_dialog import WeakAreasDialog

        dialog = WeakAreasDialog(self.panel)
        self.assertIsNotNone(dialog.table)
        self.assertEqual(dialog.table.columnCount(), 6)
        dialog.close()


    def test_open_card_conversation_loads_card_and_navigates(self):
        card = self.card(101)
        self.mw.col.get_card = lambda _card_id: card
        conversation = self.panel.store.create(101, "Hello", "Vocabulary")
        self.panel.store.add_user_message(conversation, "Question", "Prompt", [])
        self.panel.store.append(conversation, "assistant", "Answer")
        opened = []
        self.panel._open_card_in_browser = lambda current: opened.append(current.id)
        self.panel.open_card_conversation(101, conversation)
        self.assertEqual(self.panel.card.id, 101)
        self.assertEqual(self.panel.conversation_id, conversation)
        self.assertEqual(opened, [101])
        self.assertEqual(self.panel.store.messages(conversation)[-1]["content"], "Answer")


    def test_return_to_review_card_after_collection_chat(self):
        self.panel.show_card(self.card(101))
        collection = self.panel.store.create_collection()
        self.panel.store.add_user_message(collection, "Deck question", "Prompt", [])
        self.panel.open_collection_conversation(collection)
        self.assertIsNone(self.panel.card)
        self.assertEqual(self.panel.review_card.id, 101)
        self.panel._return_to_review_card()
        self.assertEqual(self.panel.card.id, 101)
        self.assertFalse(self.panel.collection_chat_open)


    def test_chat_records_token_usage_on_assistant_message(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                body = json.dumps({
                    "choices": [{"message": {"content": "Hello there."}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                }).encode()
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
            self.panel.show_card(self.card(101))
            self.panel.composer.setPlainText("Hello")
            self.panel._send()
            deadline = time.monotonic() + 5
            while self.panel.pending and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            message = self.panel.store.messages(self.panel.store.active(101))[-1]
            usage = self.panel.usage.message_usage(message["id"])
            self.assertEqual(usage["total"], 12)
            self.assertIn("usage", self.panel.chat_web.last_js)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


    def test_conversation_titles_are_hidden_before_answer(self):
        self.panel.set_answer_visible(False)
        self.panel.show_card(self.card(101))
        self.assertTrue(self.panel.conversation_bar.isHidden())
        self.panel.set_answer_visible(True)
        self.assertFalse(self.panel.conversation_bar.isHidden())


    def test_api_history_timestamps_are_optional(self):
        history = [{"role": "user", "content": "Hello", "created_at": 1700000000}]
        self.panel.config["context_timestamps"] = True
        stamped = self.panel._api_history(history)
        self.assertRegex(stamped[0]["content"], r"^\[\d{4}-\d{2}-\d{2} ")
        self.panel.config["context_timestamps"] = False
        plain = self.panel._api_history(history)
        self.assertEqual(plain[0]["content"], "Hello")

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
        history = self.panel.history_dialog
        self.assertEqual(history.tree.topLevelItemCount(), 1)
        self.assertEqual(history.tree.topLevelItem(0).childCount(), 2)
        history.search.setText("First")
        self.assertEqual(history.tree.topLevelItem(0).childCount(), 1)
        history.search.clear()
        self.assertEqual(history.tree.topLevelItem(0).childCount(), 2)
        history.hide()
        anki.lang.current_lang = "en_US"


if __name__ == "__main__":
    unittest.main()
