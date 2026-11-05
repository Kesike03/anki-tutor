"""Conversation browser with search, readable grouping, and profile backups."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from aqt.qt import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    Qt,
)

try:
    from .authoring_style import apply_dialog_style
except ImportError:
    from authoring_style import apply_dialog_style


def _when(timestamp: int) -> str:
    try:
        return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


class HistoryDialog(QDialog):
    def __init__(self, panel) -> None:
        super().__init__(panel.mw)
        self.panel = panel
        self.entries: dict[int, dict] = {}
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(820, 620)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemDoubleClicked.connect(self._open)
        layout.addWidget(self.tree, 3)
        self.meta = QLabel()
        self.meta.setWordWrap(True)
        self.meta.setObjectName("authoringHint")
        layout.addWidget(self.meta)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(130)
        layout.addWidget(self.preview, 2)
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
        apply_dialog_style(self, panel.mw, panel.config)
        self._translate()
        self.refresh()

    def _translate(self) -> None:
        text = self.panel.text
        self.setWindowTitle(text("history_manager"))
        self.search.setPlaceholderText(text("history_search"))
        self.tree.setHeaderLabels([
            text("conversation"), text("message_count"), text("history_updated"),
        ])
        self.open_button.setText(text("history_open"))
        self.delete_button.setText(text("delete_conversation"))
        self.delete_card_button.setText(text("delete_card"))
        self.delete_all_button.setText(text("delete_all"))
        self.import_button.setText(text("import_history"))
        self.export_button.setText(text("export_history"))
        self.empty.setText(text("history_empty"))

    def refresh(self) -> None:
        text = self.panel.text
        self.tree.clear()
        self.preview.clear()
        self.meta.clear()
        self.entries.clear()
        entries = self.panel.store.list_conversations() if self.panel.store else []
        needle = self.search.text().strip().casefold()
        if needle:
            entries = [
                entry for entry in entries
                if needle in " ".join((
                    entry.get("title", ""),
                    entry.get("card_label", ""),
                    entry.get("deck_name", ""),
                )).casefold()
            ]
        entries.sort(key=lambda entry: (entry["updated_at"], entry["id"]), reverse=True)
        groups = {}
        for entry in entries:
            card_id = entry["card_id"]
            if card_id not in groups:
                group = QTreeWidgetItem(self.tree)
                label = (
                    text("home_collection_chat") if card_id == 0
                    else " · ".join(filter(None, (entry["deck_name"], entry["card_label"])))
                )
                group.setText(0, label)
                group.setToolTip(0, text("home_collection_chat") if card_id == 0 else text("card", id=card_id))
                group.setData(0, Qt.ItemDataRole.UserRole, (card_id, None))
                group.setExpanded(True)
                groups[card_id] = group
            item = QTreeWidgetItem(groups[card_id])
            item.setText(0, entry["title"])
            item.setText(1, str(entry["message_count"]))
            item.setText(2, _when(entry["updated_at"]))
            item.setToolTip(0, entry["title"])
            item.setData(0, Qt.ItemDataRole.UserRole, (card_id, entry["id"]))
            self.entries[entry["id"]] = entry
        self.empty.setVisible(not entries)
        self.export_button.setEnabled(bool(entries))
        self.delete_all_button.setEnabled(bool(entries))
        self._update_actions()

    def _selection(self) -> tuple[int | None, int | None]:
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else (None, None)

    def _update_actions(self, *_args) -> None:
        card_id, conversation_id = self._selection()
        entry = self.entries.get(conversation_id) if conversation_id else None
        if entry:
            meta = " · ".join(filter(None, (
                entry.get("deck_name"), entry.get("card_label"),
                _when(entry.get("updated_at")),
                self.panel.text("messages", count=entry.get("message_count", 0)),
            )))
            self.meta.setText(meta)
            self.preview.setPlainText(
                "\n\n".join(
                    f"{self.panel.text('you' if message['role'] == 'user' else 'tutor')}: "
                    f"{message['content']}"
                    for message in self.panel.store.messages(conversation_id)
                )
            )
        else:
            self.meta.clear()
            self.preview.clear()
        self.open_button.setEnabled(conversation_id is not None and card_id is not None)
        self.delete_button.setEnabled(conversation_id is not None)
        self.delete_card_button.setEnabled(card_id is not None)

    def _open(self, item, _column) -> None:
        card_id, conversation_id = item.data(0, Qt.ItemDataRole.UserRole)
        if conversation_id is None:
            return
        if card_id == 0:
            self.panel.open_collection_conversation(conversation_id)
        else:
            self.panel.open_card_conversation(card_id, conversation_id)
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
