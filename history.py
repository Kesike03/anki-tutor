"""Conversation browser with profile-local backup and cleanup actions."""

import json
from pathlib import Path

from aqt.qt import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    Qt,
)


class HistoryDialog(QDialog):
    def __init__(self, panel) -> None:
        super().__init__(panel.mw)
        self.panel = panel
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(640, 460)
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Card / conversation", "Messages"])
        self.tree.setAlternatingRowColors(True)
        self.tree.itemDoubleClicked.connect(self._open)
        layout.addWidget(self.tree)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(85)
        layout.addWidget(self.preview)
        self.empty = QLabel()
        layout.addWidget(self.empty)
        row = QHBoxLayout()
        self.open_button = QPushButton()
        self.open_button.clicked.connect(self._open_selected)
        row.addWidget(self.open_button)
        self.delete_button = QPushButton()
        self.delete_button.clicked.connect(self._delete_selected)
        row.addWidget(self.delete_button)
        self.delete_card_button = QPushButton()
        self.delete_card_button.clicked.connect(self._delete_card)
        row.addWidget(self.delete_card_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.import_button = QPushButton()
        self.import_button.clicked.connect(self._import)
        row.addWidget(self.import_button)
        self.export_button = QPushButton()
        self.export_button.clicked.connect(self._export)
        row.addWidget(self.export_button)
        row.addStretch(1)
        self.delete_all_button = QPushButton()
        self.delete_all_button.clicked.connect(self._delete_all)
        row.addWidget(self.delete_all_button)
        layout.addLayout(row)
        self.tree.currentItemChanged.connect(self._update_actions)
        self.refresh()

    def refresh(self) -> None:
        text = self.panel.text
        self.setWindowTitle(text("history_manager"))
        self.tree.setHeaderLabels([text("conversation"), text("message_count")])
        self.open_button.setText(text("reveal"))
        self.delete_button.setText(text("delete_conversation"))
        self.delete_card_button.setText(text("delete_card"))
        self.delete_all_button.setText(text("delete_all"))
        self.import_button.setText(text("import_history"))
        self.export_button.setText(text("export_history"))
        self.empty.setText(text("history_empty"))
        self.tree.clear()
        self.preview.clear()
        entries = self.panel.store.list_conversations() if self.panel.store else []
        cards = {}
        for entry in entries:
            card_id = entry["card_id"]
            if card_id not in cards:
                card = QTreeWidgetItem(self.tree)
                card.setText(0, " | ".join(filter(None, (entry["deck_name"], entry["card_label"]))))
                card.setToolTip(0, text("card", id=card_id))
                card.setData(0, Qt.ItemDataRole.UserRole, (card_id, None))
                card.setExpanded(True)
                cards[card_id] = card
            item = QTreeWidgetItem(cards[card_id])
            item.setText(0, entry["title"])
            item.setText(1, str(entry["message_count"]))
            item.setData(0, Qt.ItemDataRole.UserRole, (card_id, entry["id"]))
        self.empty.setVisible(not entries)
        self.export_button.setEnabled(bool(entries))
        self.delete_all_button.setEnabled(bool(entries))
        self._update_actions()

    def _selection(self) -> tuple[int | None, int | None]:
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else (None, None)

    def _update_actions(self, *_args) -> None:
        card_id, conversation_id = self._selection()
        self.preview.setPlainText(
            "\n\n".join(
                f"{self.panel.text('you' if message['role'] == 'user' else 'tutor')}: {message['content']}"
                for message in self.panel.store.messages(conversation_id)
            ) if conversation_id is not None and self.panel.store is not None else ""
        )
        self.open_button.setEnabled(
            conversation_id is not None and self.panel.card is not None
            and self.panel.card.id == card_id
        )
        self.delete_button.setEnabled(conversation_id is not None)
        self.delete_card_button.setEnabled(card_id is not None)

    def _open(self, item, _column) -> None:
        card_id, conversation_id = item.data(0, Qt.ItemDataRole.UserRole)
        if conversation_id is not None and self.panel.card is not None and self.panel.card.id == card_id:
            self.panel.open_conversation(card_id, conversation_id)
            self.hide()

    def _open_selected(self) -> None:
        item = self.tree.currentItem()
        if item:
            self._open(item, 0)

    def _confirm(self, key: str) -> bool:
        return QMessageBox.question(
            self, self.panel.text("history_manager"), self.panel.text(key)
        ) == QMessageBox.StandardButton.Yes

    def _deleted(self, ids: set[int]) -> None:
        self.panel.history_changed(ids)
        self.refresh()

    def _delete_selected(self) -> None:
        _, conversation_id = self._selection()
        if conversation_id is not None and self._confirm("confirm_delete"):
            self.panel.store.delete(conversation_id)
            self._deleted({conversation_id})

    def _delete_card(self) -> None:
        card_id, _ = self._selection()
        if card_id is not None and self._confirm("confirm_delete_card"):
            ids = {entry["id"] for entry in self.panel.store.list_conversations(card_id)}
            self.panel.store.delete_card(card_id)
            self._deleted(ids)

    def _delete_all(self) -> None:
        if self._confirm("confirm_delete_all"):
            ids = {entry["id"] for entry in self.panel.store.list_conversations()}
            self.panel.store.delete_all()
            self._deleted(ids)

    def _export(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, self.panel.text("export_history"), "anki-tutor-history.json", "JSON (*.json)"
        )
        if filename:
            try:
                Path(filename).write_text(
                    json.dumps(self.panel.store.export_data(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                QMessageBox.warning(self, self.windowTitle(), self.panel.text("file_error"))

    def _import(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, self.panel.text("import_history"), "", "JSON (*.json)"
        )
        if filename:
            try:
                backup = json.loads(Path(filename).read_text(encoding="utf-8"))
                added, skipped = self.panel.store.import_data(backup)
            except (OSError, ValueError, UnicodeError, TypeError):
                QMessageBox.warning(self, self.windowTitle(), self.panel.text("file_error"))
                return
            self.panel.history_changed()
            self.refresh()
            QMessageBox.information(
                self, self.windowTitle(), self.panel.text("import_result", added=added, skipped=skipped)
            )
