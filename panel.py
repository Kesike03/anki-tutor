"""Anki's docked conversation interface and asynchronous network client."""

import json
import traceback
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from aqt.qt import (
    QCheckBox,
    QColor,
    QComboBox,
    QDockWidget,
    QEvent,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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

from .context import SYSTEM_PROMPT, ImageContextError, build_system_prompt, collect_card_images
from .i18n import LANGUAGES, tr
from .protocols import DEFAULTS, ProtocolError, build_request, parse_response, provider_error
from .storage import ConversationStore


class Composer(QTextEdit):
    def __init__(self, send, parent=None) -> None:
        super().__init__(parent)
        self._send = send
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


@dataclass
class PendingRequest:
    reply: QNetworkReply
    mode: str
    api_key: str


class TutorPanel(QDockWidget):
    def __init__(self, mw) -> None:
        super().__init__("Anki Tutor", mw)
        self.mw = mw
        self.config = mw.addonManager.getConfig(__name__) or {}
        self.config["language"] = self.config.get("language") if self.config.get("language") in LANGUAGES else "en"
        self._last_mode = self.config.get("api_mode", "chat")
        if self._last_mode not in DEFAULTS:
            self._last_mode = "chat"
        self.store = None
        self.card = None
        self.covered = False
        self.drafts: dict[int, str] = {}
        self.errors: dict[int, str] = {}
        self.pending: dict[int, PendingRequest] = {}
        self.network = QNetworkAccessManager(self)

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
        return self.config["language"]

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
        layout.addWidget(header)

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
        for code, name in LANGUAGES.items():
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.language))
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

        self.chat_scroll = QScrollArea()
        self.chat_scroll.setObjectName("tutorChatScroll")
        self.chat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chat_scroll.setWidgetResizable(True)
        self.chat_content = QWidget()
        self.chat_content.setObjectName("tutorChatContent")
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.setContentsMargins(14, 14, 14, 14)
        self.chat_layout.setSpacing(12)
        self.chat_scroll.setWidget(self.chat_content)
        self.chat_scroll.viewport().installEventFilter(self)
        self.pages.addWidget(self.chat_scroll)
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
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 10, 12, 12)
        footer_layout.setSpacing(8)
        self.composer = Composer(self._send)
        self.composer.setObjectName("tutorComposer")
        self.composer.setMinimumHeight(64)
        self.composer.setMaximumHeight(112)
        self.composer.textChanged.connect(self._update_send_button)
        footer_layout.addWidget(self.composer, 1)
        self.send_button = QToolButton()
        self.send_button.setObjectName("tutorSend")
        self.send_button.setIcon(self._icon(QStyle.StandardPixmap.SP_ArrowForward))
        self.send_button.clicked.connect(self._send)
        footer_layout.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignBottom)
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
        for name, label in self.field_labels.items():
            label.setText(self.text(name))
        self.key_action.setToolTip(self.text("show_key" if self.key_input.echoMode() == QLineEdit.EchoMode.Password else "hide_key"))
        self.context_title.setText(self.text("context"))
        self.context_note.setText(self.text("next_chat"))
        self.prompt_label.setText(self.text("system_prompt"))
        self.reset_prompt_button.setText(self.text("reset_prompt"))
        for name, checkbox in self.checks.items():
            checkbox.setText(self.text(name))
        self.empty_label.setText(self.text("empty" if self.card is None else "new_chat"))
        self.cover_label.setText(self.text("old_chat"))
        self.reveal_button.setText(self.text("reveal"))
        self.retry_button.setText(self.text("retry"))
        self.composer.setPlaceholderText(self.text("placeholder"))
        self.composer.setToolTip(self.text("input_tip"))
        self.send_button.setToolTip(self.text("send"))
        self.send_button.setAccessibleName(self.text("send"))
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
        self.mw.addonManager.writeConfig(__name__, self.config)

    def open_profile(self) -> None:
        self.close_profile()
        if self.mw.col is not None:
            self.store = ConversationStore(
                Path(__file__).parent / "user_files", self.mw.pm.collectionPath()
            )
        self._refresh()

    def close_profile(self) -> None:
        self.leave_review()
        for card_id in list(self.pending):
            self._cancel_request(card_id)
        if self.store is not None:
            self.store.close()
            self.store = None
        self.drafts.clear()
        self.errors.clear()
        self._refresh()

    def leave_review(self) -> None:
        if self.card is not None:
            self.drafts[self.card.id] = self.composer.toPlainText()
        self.card = None
        self.covered = False
        self.composer.clear()
        self._refresh()

    def show_card(self, card) -> None:
        if self.store is None:
            return
        if self.card is not None and self.card.id == card.id:
            self.card = card
            self._refresh()
            return
        if self.card is not None:
            self.drafts[self.card.id] = self.composer.toPlainText()
        self.card = card
        self.composer.setPlainText(self.drafts.get(card.id, ""))
        self.covered = bool(self.store.messages(card.id))
        self._refresh()
        self._render_messages()

    def _refresh(self) -> None:
        card = self.card
        available = card is not None and self.store is not None
        messages = self.store.messages(card.id) if available else []
        self.clear_button.setEnabled(bool(messages))
        self.composer.setEnabled(available)
        self._update_send_button()
        self.empty_label.setText(self.text("new_chat" if available else "empty"))
        if not available:
            self.detail.setText("")
            self.pages.setCurrentWidget(self.empty_page)
            self.error_bar.hide()
            return
        count = len(messages)
        deck_name = self.mw.col.decks.name(card.current_deck_id())
        status = self.text("thinking") if card.id in self.pending else self.text("messages", count=count)
        self.detail.setText(f"{deck_name} | {status}")
        self.detail.setToolTip(self.text("card", id=card.id))
        self.cover_count.setText(self.text("messages", count=count))
        self.pages.setCurrentWidget(self.cover_page if self.covered else self.chat_scroll if count else self.empty_page)
        error = self.errors.get(card.id, "")
        self.error_bar.setVisible(bool(error))
        self.error_label.setText(error)
        can_retry = bool(error and messages and messages[-1]["role"] == "user")
        self.retry_button.setVisible(can_retry and card.id not in self.pending)

    def _update_send_button(self) -> None:
        self.send_button.setEnabled(
            self.card is not None
            and self.store is not None
            and self.card.id not in self.pending
            and bool(self.composer.toPlainText().strip())
        )

    def _reveal(self) -> None:
        self.covered = False
        self._refresh()
        self._render_messages()

    def _render_messages(self) -> None:
        while self.chat_layout.count():
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if self.card is None or self.store is None or self.covered:
            return
        for message in self.store.messages(self.card.id):
            self._add_message(message["role"], message["content"])
        if self.card.id in self.pending:
            self._add_message("assistant", self.text("thinking"))
        self.chat_layout.addStretch(1)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _add_message(self, role: str, content: str) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        bubble = QFrame()
        bubble.setObjectName("tutorBubble")
        bubble.setProperty("role", role)
        bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        bubble.setMaximumWidth(max(200, self.chat_scroll.viewport().width() - 48))
        body = QVBoxLayout(bubble)
        body.setContentsMargins(12, 9, 12, 10)
        body.setSpacing(4)
        name = QLabel(self.text("you" if role == "user" else "tutor"))
        name.setObjectName("tutorRole")
        body.addWidget(name)
        text = QLabel()
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setText(content)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setWordWrap(True)
        text.setMinimumWidth(0)
        body.addWidget(text)
        if role == "user":
            row_layout.addStretch(1)
            row_layout.addWidget(bubble)
        else:
            row_layout.addWidget(bubble)
            row_layout.addStretch(1)
        self.chat_layout.addWidget(row)

    def eventFilter(self, object, event) -> bool:
        if object is self.chat_scroll.viewport() and event.type() == QEvent.Type.Resize:
            width = max(200, event.size().width() - 48)
            for bubble in self.chat_content.findChildren(QFrame, "tutorBubble"):
                bubble.setMaximumWidth(width)
        return super().eventFilter(object, event)

    def _scroll_to_bottom(self) -> None:
        bar = self.chat_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _clear_chat(self) -> None:
        if self.card is None or self.store is None:
            return
        if QMessageBox.question(self, self.text("clear"), self.text("confirm_clear")) != QMessageBox.StandardButton.Yes:
            return
        card_id = self.card.id
        self._cancel_request(card_id)
        self.store.clear(card_id)
        self.errors.pop(card_id, None)
        self.drafts.pop(card_id, None)
        self.composer.clear()
        self.covered = False
        self._refresh()
        self._render_messages()

    def _send(self) -> None:
        if self.card is None or self.store is None or self.card.id in self.pending:
            return
        message = self.composer.toPlainText().strip()
        if not message:
            return
        self._request(message)

    def _retry(self) -> None:
        if self.card is None or self.store is None or self.card.id in self.pending:
            return
        history = self.store.messages(self.card.id)
        if history and history[-1]["role"] == "user":
            self._request(None)

    def _request(self, new_message: str | None) -> None:
        self._save_settings()
        card_id = self.card.id
        history = self.store.messages(card_id)
        if new_message is not None:
            history.append({"role": "user", "content": new_message})
        try:
            saved_context = self.store.context(card_id)
            if saved_context is None:
                prompt = build_system_prompt(self.card, self.mw.col, self.config)
                images = collect_card_images(self.card, self.mw.col, self.config)
            else:
                prompt, images = saved_context
            spec = build_request(self.config, prompt, history, images)
        except (ProtocolError, ImageContextError) as error:
            self.errors[card_id] = self.text(str(error))
            self._refresh()
            if str(error) in ("missing_key", "missing_model"):
                self.settings_button.setChecked(True)
                self._toggle_settings(True)
            return
        except Exception:
            traceback.print_exc()
            self.errors[card_id] = self.text("context_error")
            self._refresh()
            return

        request = QNetworkRequest(QUrl(spec.url))
        request.setTransferTimeout(90000)
        for name, value in spec.headers.items():
            request.setRawHeader(name.encode("ascii"), value.encode("utf-8"))
        reply = self.network.post(request, json.dumps(spec.body, ensure_ascii=False).encode("utf-8"))
        self.pending[card_id] = PendingRequest(reply, self.config["api_mode"], self.config["api_key"])
        reply.finished.connect(lambda: self._on_reply(card_id, reply))
        if new_message is not None:
            self.store.add_user_message(card_id, new_message, prompt, images)
            self.composer.clear()
            self.drafts.pop(card_id, None)
        self.errors.pop(card_id, None)
        self.covered = False
        self.settings_button.setChecked(False)
        self._toggle_settings(False)
        self._refresh()
        self._render_messages()

    def _cancel_request(self, card_id: int) -> None:
        pending = self.pending.pop(card_id, None)
        if pending is not None:
            pending.reply.abort()

    def _on_reply(self, card_id: int, reply: QNetworkReply) -> None:
        pending = self.pending.get(card_id)
        reply.deleteLater()
        if pending is None or pending.reply is not reply or self.store is None:
            return
        del self.pending[card_id]
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        try:
            data = json.loads(bytes(reply.readAll()).decode("utf-8"))
        except (UnicodeError, ValueError):
            data = None
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
            else:
                error = ""
                self.store.append(card_id, "assistant", answer)
        if error:
            for key in (pending.api_key, self.config.get("api_key", "")):
                if key:
                    error = error.replace(key, "[redacted]")
            self.errors[card_id] = f"{self.text('failed')}: {error}"
        else:
            self.errors.pop(card_id, None)
        if self.card is not None and self.card.id == card_id:
            self._refresh()
            self._render_messages()

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
            QWidget#tutorRoot, QWidget#tutorPage, QWidget#tutorChatContent,
            QStackedWidget#tutorPages, QScrollArea#tutorChatScroll,
            QScrollArea#tutorSettingsScroll {{ background: {bg}; color: {text}; }}
            QFrame#tutorHeader, QFrame#tutorFooter, QWidget#tutorSettings {{
                background: {bg}; color: {text};
            }}
            QFrame#tutorHeader {{ border-bottom: 1px solid {border}; }}
            QFrame#tutorFooter {{ border-top: 1px solid {border}; }}
            QLabel#tutorHeading {{ color: {text}; font-size: 14px; font-weight: 600; }}
            QLabel#tutorDetail, QLabel#tutorEmpty {{ color: {muted}; font-size: 12px; }}
            QLabel#tutorFieldLabel, QLabel#tutorSectionLabel {{ color: {muted}; font-size: 11px; font-weight: 600; }}
            QToolButton#tutorTool {{ border: 0; background: transparent; border-radius: 4px;
                padding: 5px; min-width: 26px; min-height: 26px; }}
            QToolButton#tutorTool:hover, QToolButton#tutorTool:checked {{ background: {user}; }}
            QPushButton#tutorLinkButton {{ border: 0; background: transparent;
                color: {accent}; padding: 4px; }}
            QFrame#tutorBubble {{ border-radius: 5px; background: {surface};
                border: 1px solid {border}; color: {text}; }}
            QFrame#tutorBubble[role="user"] {{ background: {user}; border-color: {user}; }}
            QFrame#tutorBubble QLabel, QFrame#tutorError QLabel {{ color: {text}; }}
            QFrame#tutorBubble QLabel#tutorRole {{ color: {accent}; font-size: 11px; font-weight: 600; }}
            QToolButton#tutorSend {{ min-width: 30px; min-height: 30px; }}
            QFrame#tutorError {{ background: {danger}; color: {text}; }}
        """)
