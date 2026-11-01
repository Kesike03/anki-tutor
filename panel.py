"""Anki's docked conversation interface and asynchronous network client."""

import base64
import json
import traceback
from dataclasses import dataclass
from pathlib import Path

import anki.lang
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from aqt.qt import (
    QApplication,
    QBuffer,
    QCheckBox,
    QColor,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QIODevice,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPalette,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QTextEdit,
    QTimer,
    QToolButton,
    QUrl,
    QVBoxLayout,
    QWidget,
    Qt,
)
from aqt.theme import theme_manager
from aqt.webview import AnkiWebView

from .context import SYSTEM_PROMPT, ImageContextError, build_system_prompt, collect_card_images
from .attachments import AttachmentError, load_files, local_file_references
from .harness import describe, execute, extract_plan, extract_queries, instructions_for, run_queries
from .i18n import LANGUAGES, tr
from .protocols import DEFAULTS, ProtocolError, build_request, parse_response, provider_error
from .history import HistoryDialog
from .storage import ConversationStore


class Composer(QTextEdit):
    def __init__(self, send, attach_paths=None, attach_image=None, parent=None) -> None:
        super().__init__(parent)
        self._send = send
        self._attach_paths = attach_paths
        self._attach_image = attach_image
        self.setAcceptDrops(True)
        self._composing = False

    def inputMethodEvent(self, event) -> None:
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event) -> None:
        if not self._composing and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._send()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _local_paths(mime) -> list[str]:
        return [
            url.toLocalFile() for url in mime.urls()
            if url.isLocalFile() and url.toLocalFile()
        ]

    def canInsertFromMimeData(self, source) -> bool:
        return bool(source.hasImage() or self._local_paths(source)) or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:
        paths = self._local_paths(source)
        if paths and self._attach_paths:
            self._attach_paths(paths)
            return
        if source.hasImage() and self._attach_image:
            self._attach_image(source.imageData())
            return
        super().insertFromMimeData(source)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasImage() or self._local_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        paths = self._local_paths(event.mimeData())
        if paths and self._attach_paths:
            self._attach_paths(paths)
            event.acceptProposedAction()
            return
        if event.mimeData().hasImage() and self._attach_image:
            self._attach_image(event.mimeData().imageData())
            event.acceptProposedAction()
            return
        super().dropEvent(event)


MAX_AGENT_ROUNDS = 6


@dataclass
class PendingRequest:
    reply: QNetworkReply | None
    mode: str
    api_key: str
    user_id: int
    card_id: int
    deck_name: str
    messages: list[dict]
    system_prompt: str
    images: list[dict]
    rounds: int = 0


class TutorPanel(QDockWidget):
    def __init__(self, mw) -> None:
        super().__init__("Anki Tutor", mw)
        self.mw = mw
        self.config = mw.addonManager.getConfig(__name__) or {}
        if self.config.get("language") == "en" and not self.config.get("language_mode_migrated"):
            self.config["language"] = "auto"
        self.config["language_mode_migrated"] = True
        self.config["language"] = self.config.get("language") if self.config.get("language") in (*LANGUAGES, "auto") else "auto"
        self._last_mode = self.config.get("api_mode", "chat")
        if self._last_mode not in DEFAULTS:
            self._last_mode = "chat"
        self.store = None
        self.card = None
        self.conversation_id = None
        self.covered = False
        self.drafts: dict[tuple[int, int | None], str] = {}
        self.attachment_drafts: dict[tuple[int, int | None], list[dict]] = {}
        self.attachments: list[dict] = []
        self.errors: dict[int, str] = {}
        self.pending: dict[int, PendingRequest] = {}
        self.network = QNetworkAccessManager(self)
        self.history_dialog = None

        self.setObjectName("ankiTutorDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(300)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._setup_ui()
        self._translate()
        self._apply_theme()
        self._refresh()
        if not mw.restoreDockWidget(self):
            mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self)
            mw.resizeDocks([self], [410], Qt.Orientation.Horizontal)
        self.topLevelChanged.connect(self._floating_changed)
        self._floating_changed(self.isFloating())
        getattr(mw.form, "menuView", mw.menuBar()).addAction(self.toggleViewAction())

        from aqt import gui_hooks

        gui_hooks.theme_did_change.append(self._apply_theme)

    @property
    def language(self) -> str:
        chosen = self.config.get("language", "auto")
        if chosen != "auto":
            return chosen
        locale = anki.lang.current_lang.lower().replace("_", "-")
        if locale.startswith(("zh-tw", "zh-hk", "zh-mo", "zh-hant")):
            return "en"
        system = locale.split("-")[0]
        return system if system in LANGUAGES else "en"

    def text(self, key: str, **values) -> str:
        return tr(self.language, key, **values)

    def _icon(self, name: QStyle.StandardPixmap):
        return self.style().standardIcon(name)

    def _setup_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("tutorRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame(root)
        header.setObjectName("tutorHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(16, 12, 12, 10)
        header_row.setSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.heading = QLabel()
        self.heading.setObjectName("tutorHeading")
        self.detail = QLabel()
        self.detail.setObjectName("tutorDetail")
        self.detail.setWordWrap(True)
        self.detail.setMinimumWidth(0)
        titles.addWidget(self.heading)
        titles.addWidget(self.detail)
        header_row.addLayout(titles, 1)
        self.dock_button = QToolButton()
        self.dock_button.setIcon(self._icon(QStyle.StandardPixmap.SP_TitleBarNormalButton))
        self.dock_button.setObjectName("tutorTool")
        self.dock_button.clicked.connect(self._dock_to_main)
        self.dock_button.hide()
        header_row.addWidget(self.dock_button)
        self.settings_button = QToolButton()
        self.settings_button.setIcon(self._icon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.settings_button.setCheckable(True)
        self.settings_button.setObjectName("tutorTool")
        self.settings_button.clicked.connect(self._toggle_settings)
        header_row.addWidget(self.settings_button)
        self.clear_button = QToolButton()
        self.clear_button.setIcon(self._icon(QStyle.StandardPixmap.SP_DialogDiscardButton))
        self.clear_button.setObjectName("tutorTool")
        self.clear_button.clicked.connect(self._clear_chat)
        header_row.addWidget(self.clear_button)
        self.history_button = QToolButton()
        self.history_button.setIcon(self._icon(QStyle.StandardPixmap.SP_FileDialogListView))
        self.history_button.setObjectName("tutorTool")
        self.history_button.clicked.connect(self._show_history)
        header_row.addWidget(self.history_button)
        layout.addWidget(header)

        conversation_bar = QFrame(root)
        conversation_bar.setObjectName("tutorConversationBar")
        conversation_row = QHBoxLayout(conversation_bar)
        conversation_row.setContentsMargins(12, 6, 12, 6)
        conversation_row.setSpacing(6)
        self.conversation_combo = QComboBox()
        self.conversation_combo.setMinimumWidth(0)
        self.conversation_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed,
        )
        self.conversation_combo.currentIndexChanged.connect(self._select_conversation)
        conversation_row.addWidget(self.conversation_combo, 1)
        self.new_button = QToolButton()
        self.new_button.setIcon(self._icon(QStyle.StandardPixmap.SP_FileDialogNewFolder))
        self.new_button.setObjectName("tutorTool")
        self.new_button.clicked.connect(self._new_conversation)
        conversation_row.addWidget(self.new_button)
        layout.addWidget(conversation_bar)
        self.conversation_bar = conversation_bar

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("tutorSettingsScroll")
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setMaximumHeight(345)
        self.settings_scroll.setVisible(False)
        settings_content = QWidget()
        settings_content.setObjectName("tutorSettings")
        settings_layout = QVBoxLayout(settings_content)
        settings_layout.setContentsMargins(16, 12, 16, 16)
        settings_layout.setSpacing(6)

        self.field_labels = {}
        self.mode_combo = QComboBox()
        for title, mode in (
            ("OpenAI Chat Completions", "chat"),
            ("OpenAI Responses", "responses"),
            ("Claude Messages", "claude"),
            ("Google Gemini", "gemini"),
        ):
            self.mode_combo.addItem(title, mode)
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(self._last_mode))
        self._add_field(settings_layout, "mode", self.mode_combo)

        self.key_input = QLineEdit(self.config.get("api_key", ""))
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_action = self.key_input.addAction(
            self._icon(QStyle.StandardPixmap.SP_DialogOpenButton),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self.key_action.triggered.connect(self._toggle_key)
        self._add_field(settings_layout, "api_key", self.key_input)
        self.host_input = QLineEdit(self.config.get("api_host", DEFAULTS[self._last_mode][0]))
        self._add_field(settings_layout, "host", self.host_input)
        self.path_input = QLineEdit(self.config.get("api_path", DEFAULTS[self._last_mode][1]))
        self._add_field(settings_layout, "path", self.path_input)
        self.model_input = QLineEdit(self.config.get("model", DEFAULTS[self._last_mode][2]))
        self._add_field(settings_layout, "model", self.model_input)
        self.language_combo = QComboBox()
        self.language_combo.addItem("Follow Anki", "auto")
        for code, name in LANGUAGES.items():
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.config["language"]))
        self._add_field(settings_layout, "language", self.language_combo)

        prompt_row = QHBoxLayout()
        self.prompt_label = QLabel()
        self.prompt_label.setObjectName("tutorFieldLabel")
        prompt_row.addWidget(self.prompt_label)
        prompt_row.addStretch(1)
        self.reset_prompt_button = QPushButton()
        self.reset_prompt_button.setObjectName("tutorLinkButton")
        self.reset_prompt_button.clicked.connect(self._reset_prompt)
        prompt_row.addWidget(self.reset_prompt_button)
        settings_layout.addLayout(prompt_row)
        self.prompt_input = QPlainTextEdit()
        self.prompt_input.setObjectName("tutorPrompt")
        self.prompt_input.setPlainText(self.config.get("system_prompt", SYSTEM_PROMPT))
        self.prompt_input.setFixedHeight(85)
        settings_layout.addWidget(self.prompt_input)

        self.context_title = QLabel()
        self.context_title.setObjectName("tutorSectionLabel")
        settings_layout.addSpacing(8)
        settings_layout.addWidget(self.context_title)
        self.context_note = QLabel()
        self.context_note.setObjectName("tutorDetail")
        settings_layout.addWidget(self.context_note)
        self.checks = {}
        for key in ("front", "back", "images", "deck", "schedule", "history"):
            check = QCheckBox()
            check.setChecked(self.config.get(f"context_{key}", True))
            settings_layout.addWidget(check)
            self.checks[key] = check
        settings_layout.addSpacing(8)
        self.auto_approve_check = QCheckBox()
        self.auto_approve_check.setChecked(self.config.get("auto_approve_actions", False))
        self.auto_approve_check.toggled.connect(self._save_settings)
        settings_layout.addWidget(self.auto_approve_check)
        self.settings_scroll.setWidget(settings_content)
        layout.addWidget(self.settings_scroll)

        self.pages = QStackedWidget()
        self.pages.setObjectName("tutorPages")
        self.empty_page = self._center_page()
        self.empty_label = QLabel()
        self.empty_label.setObjectName("tutorEmpty")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_page.layout().addWidget(self.empty_label)
        self.empty_page.layout().addStretch(1)
        self.pages.addWidget(self.empty_page)

        self.cover_page = self._center_page()
        self.cover_label = QLabel()
        self.cover_label.setObjectName("tutorEmpty")
        self.cover_label.setWordWrap(True)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_count = QLabel()
        self.cover_count.setObjectName("tutorDetail")
        self.cover_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reveal_button = QPushButton()
        self.reveal_button.setObjectName("tutorPrimary")
        self.reveal_button.clicked.connect(self._reveal)
        self.cover_page.layout().addWidget(self.cover_label)
        self.cover_page.layout().addWidget(self.cover_count)
        self.cover_page.layout().addWidget(self.reveal_button)
        self.cover_page.layout().addStretch(1)
        self.pages.addWidget(self.cover_page)

        self.chat_web = AnkiWebView(parent=self)
        self.chat_web.setObjectName("tutorChatWeb")
        self.chat_web.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.chat_web.set_bridge_command(self._chat_command, self)
        self.chat_web.stdHtml(
            '<div id="thread"></div>',
            css=["/_addons/anki_tutor/web/chat.css"],
            js=["/_addons/anki_tutor/web/vendor/markdown-it.min.js",
                "/_anki/js/mathjax.js",
                "/_addons/anki_tutor/web/mathjax-config.js",
                "/_anki/js/vendor/mathjax/tex-chtml-full.js",
                "/_addons/anki_tutor/web/chat.js"],
            context=self,
        )
        self.pages.addWidget(self.chat_web)
        layout.addWidget(self.pages, 1)

        self.error_bar = QFrame()
        self.error_bar.setObjectName("tutorError")
        error_layout = QHBoxLayout(self.error_bar)
        error_layout.setContentsMargins(12, 8, 12, 8)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        error_layout.addWidget(self.error_label, 1)
        self.retry_button = QPushButton()
        self.retry_button.clicked.connect(self._retry)
        error_layout.addWidget(self.retry_button)
        layout.addWidget(self.error_bar)
        self.error_bar.hide()

        footer = QFrame()
        footer.setObjectName("tutorFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(12, 10, 12, 12)
        footer_layout.setSpacing(5)
        attachment_row = QHBoxLayout()
        self.attachment_list = QListWidget()
        self.attachment_list.setObjectName("tutorAttachmentList")
        self.attachment_list.setFixedHeight(55)
        self.attachment_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.attachment_list.hide()
        attachment_row.addWidget(self.attachment_list, 1)
        self.remove_attachment_button = QToolButton()
        self.remove_attachment_button.setIcon(self._icon(QStyle.StandardPixmap.SP_DialogDiscardButton))
        self.remove_attachment_button.clicked.connect(self._remove_attachment)
        self.remove_attachment_button.hide()
        attachment_row.addWidget(self.remove_attachment_button)
        footer_layout.addLayout(attachment_row)
        composer_row = QHBoxLayout()
        composer_row.setSpacing(8)
        self.composer = Composer(self._send, self._attach_paths, self._attach_image)
        self.composer.setObjectName("tutorComposer")
        self.composer.setMinimumHeight(64)
        self.composer.setMaximumHeight(112)
        self.composer.textChanged.connect(self._update_send_button)
        composer_row.addWidget(self.composer, 1)
        self.attach_button = QToolButton()
        self.attach_button.setText("+")
        self.attach_button.setObjectName("tutorTool")
        self.attach_button.clicked.connect(self._choose_attachments)
        composer_row.addWidget(self.attach_button, 0, Qt.AlignmentFlag.AlignBottom)
        self.send_button = QToolButton()
        self.send_button.setObjectName("tutorSend")
        self.send_button.setIcon(self._icon(QStyle.StandardPixmap.SP_ArrowForward))
        self.send_button.clicked.connect(self._send)
        composer_row.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignBottom)
        footer_layout.addLayout(composer_row)
        layout.addWidget(footer)
        self.setWidget(root)

        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        for widget in (self.key_input, self.host_input, self.path_input, self.model_input):
            widget.editingFinished.connect(self._save_settings)
        for check in self.checks.values():
            check.toggled.connect(self._save_settings)
        self.prompt_save_timer = QTimer(self)
        self.prompt_save_timer.setSingleShot(True)
        self.prompt_save_timer.setInterval(500)
        self.prompt_save_timer.timeout.connect(self._save_settings)
        self.prompt_input.textChanged.connect(self.prompt_save_timer.start)

    @staticmethod
    def _center_page() -> QWidget:
        page = QWidget()
        page.setObjectName("tutorPage")
        column = QVBoxLayout(page)
        column.setContentsMargins(26, 20, 26, 20)
        column.setSpacing(12)
        column.addStretch(1)
        return page

    def _add_field(self, layout, name: str, widget: QWidget) -> None:
        label = QLabel()
        label.setObjectName("tutorFieldLabel")
        layout.addWidget(label)
        layout.addWidget(widget)
        self.field_labels[name] = label

    def _translate(self) -> None:
        self.setWindowTitle(self.text("title"))
        self.toggleViewAction().setText(self.text("title"))
        self.heading.setText(self.text("title"))
        self.dock_button.setToolTip(self.text("dock"))
        self.dock_button.setAccessibleName(self.text("dock"))
        self.settings_button.setToolTip(self.text("hide_settings" if self.settings_button.isChecked() else "view_settings"))
        self.settings_button.setAccessibleName(self.text("settings"))
        self.clear_button.setToolTip(self.text("clear"))
        self.clear_button.setAccessibleName(self.text("clear"))
        self.history_button.setToolTip(self.text("history_manager"))
        self.history_button.setAccessibleName(self.text("history_manager"))
        self.new_button.setToolTip(self.text("new_conversation"))
        self.new_button.setAccessibleName(self.text("new_conversation"))
        self.conversation_combo.setAccessibleName(self.text("conversation"))
        self.language_combo.setItemText(0, self.text("auto_language"))
        for name, label in self.field_labels.items():
            label.setText(self.text(name))
        self.key_action.setToolTip(self.text("show_key" if self.key_input.echoMode() == QLineEdit.EchoMode.Password else "hide_key"))
        self.context_title.setText(self.text("context"))
        self.context_note.setText(self.text("next_chat"))
        self.prompt_label.setText(self.text("system_prompt"))
        self.reset_prompt_button.setText(self.text("reset_prompt"))
        for name, checkbox in self.checks.items():
            checkbox.setText(self.text(name))
        self.auto_approve_check.setText(self.text("auto_approve"))
        self.auto_approve_check.setToolTip(self.text("auto_approve_tip"))
        self.empty_label.setText(self.text("empty" if self.card is None else "new_chat"))
        self.cover_label.setText(self.text("old_chat"))
        self.reveal_button.setText(self.text("reveal"))
        self.retry_button.setText(self.text("retry"))
        self.composer.setPlaceholderText(self.text("placeholder"))
        self.composer.setToolTip(self.text("input_tip"))
        self.send_button.setToolTip(self.text("send"))
        self.send_button.setAccessibleName(self.text("send"))
        self.attach_button.setToolTip(self.text("attach"))
        self.attach_button.setAccessibleName(self.text("attach"))
        self.remove_attachment_button.setToolTip(self.text("remove_attachment"))
        if self.history_dialog is not None:
            self.history_dialog.refresh()
        self._refresh()

    def _toggle_settings(self, checked: bool) -> None:
        self.settings_scroll.setVisible(checked)
        self.settings_button.setToolTip(self.text("hide_settings" if checked else "view_settings"))

    def _floating_changed(self, floating: bool) -> None:
        self.dock_button.setVisible(floating)

    def _dock_to_main(self) -> None:
        self.mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self)
        self.setFloating(False)
        self.show()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.settings_scroll.setMaximumHeight(max(140, min(345, self.height() // 2)))

    def _toggle_key(self) -> None:
        visible = self.key_input.echoMode() == QLineEdit.EchoMode.Password
        self.key_input.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        self.key_action.setToolTip(self.text("hide_key" if visible else "show_key"))

    def _reset_prompt(self) -> None:
        self.prompt_input.setPlainText(SYSTEM_PROMPT)
        self._save_settings()

    def _mode_changed(self) -> None:
        mode = self.mode_combo.currentData()
        if mode == self._last_mode:
            return
        old_defaults = DEFAULTS[self._last_mode]
        new_defaults = DEFAULTS[mode]
        for widget, old, new in zip(
            (self.host_input, self.path_input, self.model_input), old_defaults, new_defaults
        ):
            if widget.text().strip() == old:
                widget.setText(new)
        self._last_mode = mode
        self._save_settings()

    def _language_changed(self) -> None:
        self._save_settings()
        self._translate()
        self._render_messages()

    def _save_settings(self) -> None:
        self.config.update(
            api_mode=self.mode_combo.currentData(),
            api_key=self.key_input.text(),
            api_host=self.host_input.text().strip(),
            api_path=self.path_input.text().strip(),
            model=self.model_input.text().strip(),
            language=self.language_combo.currentData(),
            system_prompt=self.prompt_input.toPlainText(),
        )
        for name, check in self.checks.items():
            self.config[f"context_{name}"] = check.isChecked()
        self.config["auto_approve_actions"] = self.auto_approve_check.isChecked()
        self.mw.addonManager.writeConfig(__name__, self.config)

    def open_profile(self) -> None:
        self.close_profile()
        if self.mw.col is not None:
            self.store = ConversationStore(
                Path(__file__).parent / "user_files", self.mw.pm.collectionPath()
            )
        self._translate()
        self._refresh()

    def close_profile(self) -> None:
        self.leave_review()
        for conversation_id in list(self.pending):
            self._cancel_request(conversation_id)
        if self.store is not None:
            self.store.close()
            self.store = None
        self.drafts.clear()
        self.attachment_drafts.clear()
        self.attachments.clear()
        self.errors.clear()
        if self.history_dialog is not None:
            self.history_dialog.close()
            self.history_dialog = None
        self._refresh()

    def _draft_key(self) -> tuple[int, int | None]:
        return self.card.id, self.conversation_id

    def _save_draft(self) -> None:
        if self.card is not None:
            self.drafts[self._draft_key()] = self.composer.toPlainText()
            self.attachment_drafts[self._draft_key()] = list(self.attachments)

    def _load_draft(self) -> None:
        self.composer.setPlainText(self.drafts.get(self._draft_key(), ""))
        self.attachments = list(self.attachment_drafts.get(self._draft_key(), []))
        self._refresh_attachments()

    def _refresh_attachments(self, select_index: int | None = None) -> None:
        previous = self.attachment_list.currentRow()
        self.attachment_list.clear()
        for item in self.attachments:
            list_item = QListWidgetItem(item["name"])
            list_item.setToolTip(f"{item['name']} ({item.get('kind', 'file')})")
            self.attachment_list.addItem(list_item)
        visible = bool(self.attachments)
        self.attachment_list.setVisible(visible)
        self.remove_attachment_button.setVisible(visible)
        self.remove_attachment_button.setEnabled(visible)
        if visible:
            if select_index is None:
                select_index = previous if previous >= 0 else len(self.attachments) - 1
            self.attachment_list.setCurrentRow(
                max(0, min(select_index, len(self.attachments) - 1))
            )
        self._update_send_button()

    def _choose_attachments(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, self.text("attach"))
        if paths:
            self._attach_paths(paths)

    def _attach_paths(self, paths: list[str]) -> None:
        previous_count = len(self.attachments)
        try:
            self.attachments = load_files(paths, self.attachments)
        except (AttachmentError, OSError) as error:
            QMessageBox.warning(self, self.text("attach"), f"{self.text('attachment_error')}: {error}")
        self._refresh_attachments(
            len(self.attachments) - 1 if len(self.attachments) > previous_count else None
        )

    def _attach_image(self, image) -> None:
        if image is None or image.isNull():
            return
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            return
        data = bytes(buffer.data())
        if sum(len(item.get("data", "")) * 3 // 4 for item in self.attachments) + len(data) > 20 * 1024 * 1024:
            QMessageBox.warning(self, self.text("attach"), self.text("attachment_error"))
            return
        self.attachments.append({
            "name": f"pasted-image-{len(self.attachments) + 1}.png",
            "kind": "image", "mime": "image/png",
            "data": base64.b64encode(data).decode("ascii"),
        })
        self._refresh_attachments(len(self.attachments) - 1)

    def _remove_attachment(self) -> None:
        if not self.attachments:
            return
        index = self.attachment_list.currentRow()
        if index < 0:
            index = len(self.attachments) - 1
        self.attachments.pop(index)
        self._save_draft()
        self._refresh_attachments(min(index, len(self.attachments) - 1))

    def leave_review(self) -> None:
        self._save_draft()
        self.card = None
        self.conversation_id = None
        self.covered = False
        self.composer.clear()
        self.attachments = []
        self._refresh_attachments()
        self._refresh()

    def show_card(self, card) -> None:
        if self.store is None:
            return
        if self.card is not None and self.card.id == card.id:
            self.card = card
            self._refresh()
            return
        self._save_draft()
        self.card = card
        self.store.update_card(card.id, self._card_label(card), self.mw.col.decks.name(card.current_deck_id()))
        self.conversation_id = self.store.active(card.id)
        self._load_draft()
        self.covered = bool(self.conversation_id and self.store.messages(self.conversation_id))
        self._refresh_conversations()
        self._refresh()
        self._render_messages()

    def _card_label(self, card) -> str:
        from .context import readable_text

        try:
            text = readable_text(card.render_output().question_text)
        except Exception:
            text = ""
        return " ".join(text.split())[:90] or self.text("card", id=card.id)

    def _refresh_conversations(self) -> None:
        self.conversation_combo.blockSignals(True)
        self.conversation_combo.clear()
        if self.card is not None and self.store is not None:
            entries = self.store.list_conversations(self.card.id)
            if not entries:
                self.conversation_combo.addItem(self.text("new_conversation"), None)
            for entry in entries:
                self.conversation_combo.addItem(entry["title"], entry["id"])
            index = self.conversation_combo.findData(self.conversation_id)
            self.conversation_combo.setCurrentIndex(index)
        self.conversation_combo.blockSignals(False)

    def _select_conversation(self, index: int) -> None:
        if self.card is None or self.store is None or index < 0:
            return
        conversation_id = self.conversation_combo.itemData(index)
        if conversation_id == self.conversation_id:
            return
        self._save_draft()
        self.conversation_id = conversation_id
        self.store.select(self.card.id, conversation_id)
        self._load_draft()
        self.covered = False
        self._refresh()
        self._render_messages()

    def _new_conversation(self) -> None:
        if self.card is None or self.store is None:
            return
        if self.conversation_id is not None and not self.store.messages(self.conversation_id):
            self.composer.setFocus()
            return
        initial_draft = self.composer.toPlainText() if self.conversation_id is None else ""
        initial_attachments = list(self.attachments) if self.conversation_id is None else []
        self._save_draft()
        if self.conversation_id is None:
            self.drafts.pop(self._draft_key(), None)
            self.attachment_drafts.pop(self._draft_key(), None)
        self.conversation_id = self.store.create(
            self.card.id, self._card_label(self.card),
            self.mw.col.decks.name(self.card.current_deck_id()),
        )
        self.composer.setPlainText(initial_draft)
        self.attachments = initial_attachments
        self._refresh_attachments()
        self.covered = False
        self._refresh_conversations()
        self._refresh()
        self._render_messages()

    def _show_history(self) -> None:
        if self.store is None:
            return
        if self.history_dialog is None:
            self.history_dialog = HistoryDialog(self)
        self.history_dialog.refresh()
        self.history_dialog.show()
        self.history_dialog.raise_()
        self.history_dialog.activateWindow()

    def open_conversation(self, card_id: int, conversation_id: int) -> None:
        if self.store is None:
            return
        self.store.select(card_id, conversation_id)
        if self.card is not None and self.card.id == card_id:
            self._save_draft()
            self.conversation_id = conversation_id
            self._load_draft()
            self.covered = False
            self._refresh_conversations()
            self._refresh()
            self._render_messages()

    def history_changed(self, deleted: set[int] | None = None) -> None:
        previous_id = self.conversation_id
        for conversation_id in deleted or set():
            self._cancel_request(conversation_id)
            self.errors.pop(conversation_id, None)
            for key in list(self.drafts):
                if key[1] == conversation_id:
                    del self.drafts[key]
                    self.attachment_drafts.pop(key, None)
        if self.card is not None and self.store is not None:
            self.conversation_id = self.store.active(self.card.id)
            if self.conversation_id != previous_id:
                self.covered = bool(self.conversation_id and self.store.messages(self.conversation_id))
                self._load_draft()
        self._refresh_conversations()
        self._refresh()
        self._render_messages()

    def _refresh(self) -> None:
        card = self.card
        available = card is not None and self.store is not None
        messages = self.store.messages(self.conversation_id) if available and self.conversation_id else []
        self.conversation_bar.setVisible(available)
        self.new_button.setEnabled(available)
        self.conversation_combo.setEnabled(available and self.conversation_id is not None)
        self.clear_button.setEnabled(available and self.conversation_id is not None)
        self.composer.setEnabled(available)
        self.attach_button.setEnabled(available)
        self._update_send_button()
        self.empty_label.setText(self.text("new_chat" if available else "empty"))
        if not available:
            self.detail.setText("")
            self.pages.setCurrentWidget(self.empty_page)
            self.error_bar.hide()
            return
        count = len(messages)
        deck_name = self.mw.col.decks.name(card.current_deck_id())
        status = self.text("thinking") if self.conversation_id in self.pending else self.text("messages", count=count)
        self.detail.setText(f"{deck_name} | {status}")
        self.detail.setToolTip(self.text("card", id=card.id))
        self.cover_count.setText(self.text("messages", count=count))
        self.pages.setCurrentWidget(self.cover_page if self.covered else self.chat_web if count else self.empty_page)
        error = self.errors.get(self.conversation_id, "")
        self.error_bar.setVisible(bool(error))
        self.error_label.setText(error)
        can_retry = bool(error and messages and messages[-1]["role"] == "user")
        self.retry_button.setVisible(can_retry and self.conversation_id not in self.pending)

    def _update_send_button(self) -> None:
        self.send_button.setEnabled(
            self.card is not None
            and self.store is not None
            and self.conversation_id not in self.pending
            and bool(self.composer.toPlainText().strip() or self.attachments)
        )

    def _reveal(self) -> None:
        self.covered = False
        self._refresh()
        self._render_messages()

    def _render_messages(self) -> None:
        messages = (
            self.store.messages(self.conversation_id)
            if self.store is not None and self.conversation_id is not None and not self.covered else []
        )
        messages = [
            {**message, "attachments": [
                {"name": attachment["name"], "kind": attachment["kind"]}
                for attachment in message.get("attachments", [])
            ]} for message in messages
        ]
        if self.conversation_id in self.pending and not self.covered:
            messages.append({"role": "assistant", "content": self.text("thinking")})
        palette = self.mw.app.palette()
        theme = {
            "bg": palette.color(QPalette.ColorRole.Window).name(),
            "surface": palette.color(QPalette.ColorRole.Base).name(),
            "text": palette.color(QPalette.ColorRole.WindowText).name(),
            "muted": palette.color(QPalette.ColorRole.PlaceholderText).name(),
            "border": palette.color(QPalette.ColorRole.Mid).name(),
            "user": self._user_color(),
        }
        payload = {
            "messages": messages, "you": self.text("you"), "tutor": self.text("tutor"),
            "labels": {key: self.text(key) for key in (
                "copy", "regenerate", "edit_message", "previous_branch", "next_branch"
            )},
            "busy": self.conversation_id in self.pending, "theme": theme,
        }
        self.chat_web.eval(f"window.renderTutorMessages({json.dumps(payload, ensure_ascii=False)});")

    def _chat_command(self, command: str) -> None:
        if not command.startswith("tutor:") or self.store is None or self.conversation_id is None or self.covered:
            return
        try:
            _, action, value = command.split(":", 2)
            message_id = int(value)
            if message_id not in {message["id"] for message in self.store.messages(self.conversation_id)}:
                return
            message = self.store.message(self.conversation_id, message_id)
        except (ValueError, KeyError):
            return
        if action == "copy" and message["role"] == "assistant":
            QApplication.clipboard().setText(message["content"])
        elif self.conversation_id not in self.pending:
            if action in ("prev", "next"):
                if self.store.adjacent_branch(self.conversation_id, message_id, -1 if action == "prev" else 1):
                    self._refresh()
                    self._render_messages()
            elif action == "regen" and message["role"] == "assistant":
                parent = self.store.message(self.conversation_id, message["parent_id"])
                if parent["role"] == "user":
                    self._request(None, target_user_id=parent["id"])
            elif action == "edit" and message["role"] == "user":
                content, accepted = QInputDialog.getMultiLineText(
                    self, self.text("edit_message"), self.text("edit_message"), message["content"]
                )
                if accepted and (content.strip() or message["attachments"]):
                    edited_id = self.store.fork_user(self.conversation_id, message_id, content.strip())
                    self._refresh()
                    self._render_messages()
                    self._request(None, target_user_id=edited_id)

    def _user_color(self) -> str:
        palette = self.mw.app.palette()
        base = palette.color(QPalette.ColorRole.Base)
        highlight = palette.color(QPalette.ColorRole.Highlight)
        return QColor(
            round(base.red() * 0.86 + highlight.red() * 0.14),
            round(base.green() * 0.86 + highlight.green() * 0.14),
            round(base.blue() * 0.86 + highlight.blue() * 0.14),
        ).name()

    def _clear_chat(self) -> None:
        if self.card is None or self.store is None or self.conversation_id is None:
            return
        if QMessageBox.question(self, self.text("clear"), self.text("confirm_clear")) != QMessageBox.StandardButton.Yes:
            return
        old_id = self.conversation_id
        self.store.delete(old_id)
        self.history_changed({old_id})

    def _send(self) -> None:
        if self.card is None or self.store is None or self.conversation_id in self.pending:
            return
        message = self.composer.toPlainText().strip()
        message, paths = local_file_references(message)
        if paths:
            try:
                self.attachments = load_files(paths, self.attachments)
            except (AttachmentError, OSError) as error:
                QMessageBox.warning(self, self.text("attach"), f"{self.text('attachment_error')}: {error}")
            self._refresh_attachments()
        if not message and not self.attachments:
            return
        self._request(message or self.text("attachment_only"), attachments=list(self.attachments))

    def _retry(self) -> None:
        if self.card is None or self.store is None or self.conversation_id is None or self.conversation_id in self.pending:
            return
        history = self.store.messages(self.conversation_id)
        if history and history[-1]["role"] == "user":
            self._request(None, target_user_id=history[-1]["id"])

    def _request(
        self, new_message: str | None, attachments: list[dict] | None = None,
        target_user_id: int | None = None,
    ) -> None:
        self._save_settings()
        if self.conversation_id in self.pending:
            return
        if self.conversation_id is None:
            self._new_conversation()
        conversation_id = self.conversation_id
        history = (
            self.store.history_until(conversation_id, target_user_id)
            if target_user_id is not None else self.store.messages(conversation_id)
        )
        if target_user_id is not None:
            if not history or history[-1]["role"] != "user":
                return
        if new_message is not None:
            history.append({"role": "user", "content": new_message, "attachments": attachments or []})
        try:
            saved_context = self.store.context(conversation_id)
            if saved_context is None:
                prompt = build_system_prompt(self.card, self.mw.col, self.config)
                images = collect_card_images(self.card, self.mw.col, self.config)
            else:
                prompt, images = saved_context
            system_prompt = prompt + "\n\n" + instructions_for(self.card, self.mw.col, self.config)
            build_request(self.config, system_prompt, history, images)
        except (ProtocolError, ImageContextError) as error:
            key = str(error)
            self.errors[conversation_id] = self.text(key) if key in ("missing_key", "missing_model", "invalid_host", "invalid_path", "invalid_response", "image_error", "pdf_not_supported") else key
            self._refresh()
            if str(error) in ("missing_key", "missing_model"):
                self.settings_button.setChecked(True)
                self._toggle_settings(True)
            return
        except Exception:
            traceback.print_exc()
            self.errors[conversation_id] = self.text("context_error")
            self._refresh()
            return

        if new_message is not None:
            target_user_id = self.store.add_user_message(
                conversation_id, new_message, prompt, images, attachments
            )
            self.composer.clear()
            self.attachments.clear()
            self.attachment_drafts.pop(self._draft_key(), None)
            self._refresh_attachments()
            self.drafts.pop(self._draft_key(), None)
        if target_user_id is None:
            return
        pending = PendingRequest(
            None, self.config["api_mode"], self.config["api_key"], target_user_id,
            self.card.id, self.mw.col.decks.name(self.card.current_deck_id()),
            history, system_prompt, images,
        )
        self.pending[conversation_id] = pending
        self.errors.pop(conversation_id, None)
        self.covered = False
        self.settings_button.setChecked(False)
        self._toggle_settings(False)
        self._refresh_conversations()
        self._refresh()
        self._render_messages()
        if not self._post_pending(conversation_id, pending):
            return

    def _post_pending(self, conversation_id: int, pending: PendingRequest) -> bool:
        try:
            spec = build_request(
                self.config, pending.system_prompt, pending.messages, pending.images
            )
        except (ProtocolError, ImageContextError) as error:
            self.pending.pop(conversation_id, None)
            key = str(error)
            self.errors[conversation_id] = self.text(key) if key in (
                "missing_key", "missing_model", "invalid_host", "invalid_path",
                "invalid_response", "image_error", "pdf_not_supported",
            ) else key
            if key in ("missing_key", "missing_model"):
                self.settings_button.setChecked(True)
                self._toggle_settings(True)
            self._refresh()
            return False
        except Exception:
            traceback.print_exc()
            self.pending.pop(conversation_id, None)
            self.errors[conversation_id] = self.text("context_error")
            self._refresh()
            return False
        request = QNetworkRequest(QUrl(spec.url))
        request.setTransferTimeout(90000)
        for name, value in spec.headers.items():
            request.setRawHeader(name.encode("ascii"), value.encode("utf-8"))
        reply = self.network.post(request, json.dumps(spec.body, ensure_ascii=False).encode("utf-8"))
        pending.reply = reply
        reply.finished.connect(lambda: self._on_reply(conversation_id, reply))
        return True

    def _cancel_request(self, conversation_id: int) -> None:
        pending = self.pending.pop(conversation_id, None)
        if pending is not None and pending.reply is not None:
            pending.reply.abort()

    def _on_reply(self, conversation_id: int, reply: QNetworkReply) -> None:
        pending = self.pending.get(conversation_id)
        reply.deleteLater()
        if pending is None or pending.reply is not reply or self.store is None:
            return
        pending.reply = None
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        try:
            data = json.loads(bytes(reply.readAll()).decode("utf-8"))
        except (UnicodeError, ValueError):
            data = None
        error = ""
        if status is not None and int(status) >= 300:
            error = provider_error(int(status), data)
        elif reply.error() == QNetworkReply.NetworkError.TimeoutError:
            error = self.text("timeout")
        elif reply.error() != QNetworkReply.NetworkError.NoError:
            error = reply.errorString()
        else:
            try:
                answer = parse_response(pending.mode, data)
            except ProtocolError as exception:
                error = self.text(str(exception))
        if error:
            self.pending.pop(conversation_id, None)
            self._show_pending_error(conversation_id, pending, error)
            return
        self._handle_agent_reply(conversation_id, pending, answer)

    def _show_pending_error(self, conversation_id: int, pending: PendingRequest, error: str) -> None:
        for key in (pending.api_key, self.config.get("api_key", "")):
            if key:
                error = error.replace(key, "[redacted]")
        self.errors[conversation_id] = f"{self.text('failed')}: {error}"
        if self.conversation_id == conversation_id:
            self._refresh()
            self._render_messages()

    def _handle_agent_reply(
        self, conversation_id: int, pending: PendingRequest, raw: str
    ) -> None:
        if self.store is None:
            return
        try:
            visible, queries = extract_queries(raw)
        except ValueError as error:
            self.pending.pop(conversation_id, None)
            self._show_pending_error(conversation_id, pending, str(error))
            return
        if queries:
            if pending.rounds >= MAX_AGENT_ROUNDS:
                self._finish_pending(conversation_id, pending, visible, "agent_limit")
                return
            pending.rounds += 1
            results = run_queries(
                self.mw.col, queries, pending.card_id, pending.deck_name
            )
            pending.messages.extend([
                {"role": "assistant", "content": raw},
                {"role": "user", "content":
                    "Anki query results:\n" + results +
                    "\n\nContinue the task. Use another query or anki-actions block if needed; "
                    "otherwise give the final answer."},
            ])
            self._show_agent_progress(conversation_id)
            self._post_pending(conversation_id, pending)
            return
        try:
            visible, actions = extract_plan(raw)
        except ValueError as error:
            self.pending.pop(conversation_id, None)
            self._show_pending_error(conversation_id, pending, str(error))
            return
        if actions:
            if pending.rounds >= MAX_AGENT_ROUNDS:
                self._finish_pending(conversation_id, pending, visible, "agent_limit")
                return
            pending.rounds += 1
            approved = self.config.get("auto_approve_actions", False) or self._ask_action_approval(
                actions, pending.card_id, pending.deck_name
            )
            if not approved:
                self._finish_pending(
                    conversation_id, pending,
                    (visible + "\n\n" + self.text("action_cancelled")).strip(),
                )
                return
            results = self._execute_actions(actions, pending.card_id, pending.deck_name)
            pending.messages.extend([
                {"role": "assistant", "content": raw},
                {"role": "user", "content":
                    "Anki action results:\n" + results +
                    "\n\nReview whether the user's request is fully complete and correct. "
                    "If more work is needed, use another query/action block; otherwise give "
                    "a concise final answer. Do not repeat actions that already succeeded."},
            ])
            self._show_agent_progress(conversation_id)
            self._post_pending(conversation_id, pending)
            return
        self._finish_pending(conversation_id, pending, visible)

    def _show_agent_progress(self, conversation_id: int) -> None:
        if self.conversation_id == conversation_id:
            self._refresh()
            self._render_messages()

    def _finish_pending(
        self, conversation_id: int, pending: PendingRequest,
        visible: str, fallback: str = "action_success",
    ) -> None:
        self.pending.pop(conversation_id, None)
        if self.store is None:
            return
        text = (visible or "").strip() or self.text(fallback)
        visible_ids = {message["id"] for message in self.store.messages(conversation_id)}
        self.store.append_branch(
            conversation_id, pending.user_id, "assistant", text,
            select=pending.user_id in visible_ids,
        )
        self.errors.pop(conversation_id, None)
        if self.conversation_id == conversation_id:
            self._refresh_conversations()
            self._refresh()
            self._render_messages()

    def _ask_action_approval(
        self, actions: list[dict], card_id: int, deck_name: str
    ) -> bool:
        if self.config.get("auto_approve_actions", False):
            return True
        box = QMessageBox(self.mw)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.text("title"))
        box.setTextFormat(Qt.TextFormat.PlainText)
        details = "\n".join(
            f"{index}. {describe(action, card_id, deck_name)}"
            for index, action in enumerate(actions, 1)
        )
        box.setText(self.text("action_confirm") + "\n\n" + details)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _execute_actions(
        self, actions: list[dict], card_id: int, deck_name: str
    ) -> str:
        results = []
        for index, action in enumerate(actions, 1):
            try:
                execute(self.mw.col, action, card_id, deck_name)
                results.append(f"{index}. {action['type']}: applied")
            except Exception as error:
                results.append(f"{index}. {action['type']}: failed: {error}")
        try:
            self.mw.reset()
        except Exception:
            traceback.print_exc()
        return "\n".join(results)

    def _apply_theme(self) -> None:
        palette = self.mw.app.palette()
        bg_color = palette.color(QPalette.ColorRole.Window)
        surface_color = palette.color(QPalette.ColorRole.Base)
        accent_color = palette.color(QPalette.ColorRole.Highlight)
        text = palette.color(QPalette.ColorRole.WindowText).name()
        muted = palette.color(QPalette.ColorRole.PlaceholderText).name()
        border = palette.color(QPalette.ColorRole.Mid).name()
        bg, surface, accent = bg_color.name(), surface_color.name(), accent_color.name()

        def mix(first: QColor, second: QColor, weight: float) -> str:
            return QColor(
                round(first.red() * (1 - weight) + second.red() * weight),
                round(first.green() * (1 - weight) + second.green() * weight),
                round(first.blue() * (1 - weight) + second.blue() * weight),
            ).name()

        user = mix(surface_color, accent_color, 0.13 if not theme_manager.night_mode else 0.24)
        danger = mix(bg_color, QColor("#d85a53"), 0.15)
        self.setStyleSheet(f"""
            QWidget#tutorRoot, QWidget#tutorPage, QStackedWidget#tutorPages,
            QScrollArea#tutorSettingsScroll {{ background: {bg}; color: {text}; }}
            QFrame#tutorHeader, QFrame#tutorFooter, QWidget#tutorSettings {{
                background: {bg}; color: {text};
            }}
            QFrame#tutorHeader {{ border-bottom: 1px solid {border}; }}
            QFrame#tutorConversationBar {{ background: {bg}; border-bottom: 1px solid {border}; }}
            QFrame#tutorFooter {{ border-top: 1px solid {border}; }}
            QLabel#tutorHeading {{ color: {text}; font-size: 14px; font-weight: 600; }}
            QLabel#tutorDetail, QLabel#tutorEmpty {{ color: {muted}; font-size: 12px; }}
            QLabel#tutorFieldLabel, QLabel#tutorSectionLabel {{ color: {muted}; font-size: 11px; font-weight: 600; }}
            QToolButton#tutorTool {{ border: 0; background: transparent; border-radius: 4px;
                padding: 5px; min-width: 26px; min-height: 26px; }}
            QToolButton#tutorTool:hover, QToolButton#tutorTool:checked {{ background: {user}; }}
            QPushButton#tutorLinkButton {{ border: 0; background: transparent;
                color: {accent}; padding: 4px; }}
            QListWidget#tutorAttachmentList {{ background: {surface}; color: {text};
                border: 1px solid {border}; border-radius: 4px; padding: 2px; }}
            QListWidget#tutorAttachmentList::item {{ padding: 3px 5px; }}
            QListWidget#tutorAttachmentList::item:selected {{
                background: {accent}; color: {surface};
            }}
            QFrame#tutorError QLabel {{ color: {text}; }}
            QToolButton#tutorSend {{ min-width: 30px; min-height: 30px; }}
            QFrame#tutorError {{ background: {danger}; color: {text}; }}
        """)
        self._render_messages()
