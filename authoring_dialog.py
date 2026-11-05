"""Review-first dialogs for saving replies, notes, and generated cards."""

from __future__ import annotations

import traceback

from aqt.qt import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QTimer,
    QVBoxLayout,
)

try:
    from . import authoring
    from .authoring_client import AuthoringRunner
    from .authoring_style import apply_dialog_style
    from .context import readable_text
    from .i18n import resolve_language, tr
    from .safe_write import SafeWriter
except ImportError:
    import authoring
    from authoring_client import AuthoringRunner
    from authoring_style import apply_dialog_style
    from context import readable_text
    from i18n import resolve_language, tr
    from safe_write import SafeWriter


ADDON = __name__.split(".")[0]


def _refresh_anki(mw) -> None:
    try:
        mw.reset()
    except Exception:
        pass


def _config(mw) -> dict:
    return dict(mw.addonManager.getConfig(ADDON) or {})


def _language(config: dict) -> str:
    return resolve_language(config.get("language", "auto"))


class FieldWriteDialog(QDialog):
    """Base dialog for a single field write with preview and undo."""

    def __init__(self, mw, card, config: dict, title: str, hint: str, content: str = "", parent=None) -> None:
        super().__init__(parent or mw)
        self.mw = mw
        self.card = card
        self.config = config
        self.language = _language(config)
        self.note = card.note()
        self.notetype = card.note_type()
        self.receipt = None
        self._filling = True
        self.setWindowTitle(title)
        self.resize(720, 680)
        layout = QVBoxLayout(self)
        title_label = QLabel(title)
        title_label.setObjectName("authoringTitle")
        layout.addWidget(title_label)
        hint_label = QLabel(hint)
        hint_label.setWordWrap(True)
        hint_label.setObjectName("authoringHint")
        layout.addWidget(hint_label)
        layout.addWidget(QLabel(self._t("authoring_content")))
        self.content_edit = QPlainTextEdit()
        self.content_edit.setPlainText(content)
        self.content_edit.setMinimumHeight(160)
        self.content_edit.textChanged.connect(self._refresh_warnings)
        layout.addWidget(self.content_edit, 1)
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel(self._t("authoring_target_field")))
        self.field_combo = QComboBox()
        self.field_combo.addItems(list(self.note.keys()))
        self.field_combo.currentIndexChanged.connect(self._field_changed)
        target_row.addWidget(self.field_combo, 1)
        target_row.addWidget(QLabel(self._t("authoring_insert")))
        self.insert_combo = QComboBox()
        self.insert_combo.addItem(self._t("authoring_append"), "after")
        self.insert_combo.addItem(self._t("authoring_prepend"), "before")
        self.insert_combo.addItem(self._t("authoring_replace"), "replace")
        self.insert_combo.currentIndexChanged.connect(self._refresh_warnings)
        target_row.addWidget(self.insert_combo, 1)
        layout.addLayout(target_row)
        self.current_label = QLabel(self._t("authoring_current_content"))
        self.current_label.setObjectName("authoringHint")
        layout.addWidget(self.current_label)
        self.current_view = QPlainTextEdit()
        self.current_view.setReadOnly(True)
        self.current_view.setMaximumHeight(78)
        layout.addWidget(self.current_view)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setObjectName("authoringWarning")
        layout.addWidget(self.warning_label)
        self.status = QLabel()
        self.status.setObjectName("authoringHint")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._extra_buttons(buttons)
        self.undo_button = QPushButton(self._t("authoring_undo"))
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self._undo)
        buttons.addWidget(self.undo_button)
        self.save_button = QPushButton(self._t("authoring_save"))
        self.save_button.setObjectName("authoringPrimary")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)
        close = QPushButton(self._t("authoring_close"))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        safe = authoring.safe_target_field(self.notetype)
        index = self.field_combo.findText(safe)
        if index >= 0:
            self.field_combo.setCurrentIndex(index)
        self._filling = False
        apply_dialog_style(self, self.mw, self.config)
        self._field_changed()

    def _t(self, key: str, **values) -> str:
        try:
            return tr(self.language, key, **values)
        except KeyError:
            return key

    def _error_text(self, error: str) -> str:
        known = {
            "missing_key", "missing_model", "invalid_host", "invalid_path",
            "invalid_response", "empty_response", "pdf_not_supported",
        }
        return self._t(error) if error in known else error

    def _extra_buttons(self, layout) -> None:
        return

    def _field_changed(self, _index: int = 0) -> None:
        if self._filling:
            return
        field = self.field_combo.currentText()
        names = list(self.note.keys())
        self.current_view.setPlainText(authoring.html_to_text(self.note[field]) if field in names else "")
        self._refresh_warnings()

    def _refresh_warnings(self, *_args) -> None:
        if self._filling:
            return
        warnings = []
        field = self.field_combo.currentText()
        if field in authoring.front_fields(self.notetype):
            warnings.append(self._t("authoring_front_warning"))
        if self.insert_combo.currentData() == "replace":
            warnings.append(self._t("authoring_replace_warning"))
        self.warning_label.setText("\n".join(warnings))
        self.warning_label.setVisible(bool(warnings))

    def _compose(self) -> tuple[str, str, str]:
        field = self.field_combo.currentText()
        names = list(self.note.keys())
        before = self.note[field] if field in names else ""
        content = authoring.markdown_to_html(self.content_edit.toPlainText().strip())
        if not authoring.plain_text(content):
            raise authoring.AuthoringError(self._t("authoring_no_changes"))
        mode = self.insert_combo.currentData()
        if mode == "before" and before.strip():
            after = content + "<br><br>" + before
        elif mode == "replace" or not before.strip():
            after = content
        else:
            after = before + "<br><br>" + content
        if after == before:
            raise authoring.AuthoringError(self._t("authoring_no_changes"))
        return field, before, after

    def _save(self) -> None:
        try:
            field, before, after = self._compose()
            if self.insert_combo.currentData() == "replace" and authoring.plain_text(before):
                answer = QMessageBox.question(
                    self, self.windowTitle(), self._t("authoring_replace_warning"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            change = authoring.FieldChange(int(self.note.id), field, before, after)
            self.receipt = SafeWriter(self.mw.col).apply_fields([change])
            self.save_button.setEnabled(False)
            self.undo_button.setEnabled(self.receipt.undoable)
            self.status.setText(self._t("authoring_saved"))
            _refresh_anki(self.mw)
        except Exception as error:
            QMessageBox.warning(self, self.windowTitle(), str(error))

    def _undo(self) -> None:
        if not self.receipt or not self.receipt.undoable:
            return
        try:
            self.receipt.undo(self.mw.col)
            self.receipt = None
            self.undo_button.setEnabled(False)
            self.save_button.setEnabled(True)
            self.status.setText(self._t("authoring_undone"))
            self._field_changed()
            _refresh_anki(self.mw)
        except Exception as error:
            QMessageBox.warning(self, self.windowTitle(), str(error))

    def reject(self) -> None:
        if getattr(self, "runner", None):
            self.runner.abort()
        super().reject()


class SaveReplyDialog(FieldWriteDialog):
    def __init__(self, mw, card, config: dict, content: str, parent=None) -> None:
        language = _language(config)
        title = tr(language, "authoring_save_reply_title")
        hint = tr(language, "authoring_edit_hint")
        super().__init__(mw, card, config, title, hint, content, parent)


class ConversationNotesDialog(FieldWriteDialog):
    def __init__(
        self, mw, card, config: dict, messages: list[dict],
        parent=None, usage_store=None,
    ) -> None:
        self.messages = messages
        self.usage_store = usage_store
        self.card_content = authoring.card_text(card, readable_text)
        self.runner = None
        language = _language(config)
        super().__init__(
            mw, card, config,
            tr(language, "authoring_notes_title"),
            tr(language, "authoring_auto_note"),
            "", parent,
        )
        QTimer.singleShot(0, self._generate)

    def _extra_buttons(self, layout) -> None:
        self.generate_button = QPushButton(self._t("authoring_regenerate"))
        self.generate_button.clicked.connect(self._generate)
        layout.addWidget(self.generate_button)

    def _generate(self) -> None:
        if self.runner:
            self.runner.abort()
        system, user = authoring.notes_messages(self.card_content, self.messages)
        self.content_edit.setReadOnly(True)
        self.status.setText(self._t("authoring_loading"))
        self.runner = AuthoringRunner(
            self.config, self, source="conversation_notes",
            usage_callback=self._record_usage,
        )
        self.runner.job_finished.connect(self._generated)
        self.runner.start([{"id": 1, "system": system, "user": user}])

    def _record_usage(self, payload: dict) -> None:
        if self.usage_store is None:
            return
        try:
            self.usage_store.record(
                payload["usage"], model=payload.get("model", ""),
                mode=payload.get("mode", ""), source=payload.get("source", "conversation_notes"),
            )
        except Exception:
            traceback.print_exc()

    def _generated(self, _job_id: int, text: str, error: str) -> None:
        self.content_edit.setReadOnly(False)
        if error:
            self.status.setText(f"{self._t('authoring_generate_failed')} {self._error_text(error)}")
            return
        self.content_edit.setPlainText(text.strip())
        self.status.setText(self._t("authoring_generated"))


class ConversationCardsDialog(QDialog):
    def __init__(
        self, mw, card, config: dict, messages: list[dict],
        parent=None, usage_store=None,
    ) -> None:
        super().__init__(parent or mw)
        self.mw = mw
        self.usage_store = usage_store
        self.col = mw.col
        self.card = card
        self.config = config
        self.language = _language(config)
        self.messages = messages
        self.card_content = authoring.card_text(card, readable_text)
        self.runner = None
        self.receipt = None
        self._filling = False
        self.setWindowTitle(self._t("authoring_cards_title"))
        self.resize(980, 760)
        self._build()
        self._load_models()
        self._load_decks()
        apply_dialog_style(self, self.mw, self.config)
        QTimer.singleShot(0, self._generate)

    def _t(self, key: str, **values) -> str:
        try:
            return tr(self.language, key, **values)
        except KeyError:
            return key

    def _error_text(self, error: str) -> str:
        known = {
            "missing_key", "missing_model", "invalid_host", "invalid_path",
            "invalid_response", "empty_response", "pdf_not_supported",
        }
        return self._t(error) if error in known else error


    def _build(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel(self._t("authoring_cards_title"))
        title.setObjectName("authoringTitle")
        layout.addWidget(title)
        hint = QLabel(self._t("authoring_cards_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("authoringHint")
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(QLabel(self._t("authoring_note_type")))
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        row.addWidget(self.model_combo, 1)
        row.addWidget(QLabel(self._t("authoring_deck")))
        self.deck_combo = QComboBox()
        row.addWidget(self.deck_combo, 1)
        row.addWidget(QLabel(self._t("authoring_count")))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 10)
        self.count_spin.setValue(3)
        row.addWidget(self.count_spin)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel(self._t("authoring_extra")))
        self.extra_edit = QLineEdit()
        row.addWidget(self.extra_edit, 1)
        self.generate_button = QPushButton(self._t("authoring_generate_cards"))
        self.generate_button.clicked.connect(self._generate)
        row.addWidget(self.generate_button)
        layout.addLayout(row)
        self.table = QTableWidget(0, 1)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        layout.addWidget(self.table, 1)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setObjectName("authoringWarning")
        layout.addWidget(self.warning_label)
        self.status = QLabel()
        self.status.setObjectName("authoringHint")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.undo_button = QPushButton(self._t("authoring_undo"))
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self._undo)
        buttons.addWidget(self.undo_button)
        self.add_button = QPushButton(self._t("authoring_add_cards"))
        self.add_button.setObjectName("authoringPrimary")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._add)
        buttons.addWidget(self.add_button)
        close = QPushButton(self._t("authoring_close"))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _load_models(self) -> None:
        self.models = {}
        try:
            for model in self.col.models.all():
                self.models[str(model.get("name", "Note type"))] = model
        except Exception:
            model = self.card.note_type()
            self.models[str(model.get("name", "Note type"))] = model
        names = list(self.models)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(names)
        current = str(self.card.note_type().get("name", ""))
        if current in names:
            self.model_combo.setCurrentText(current)
        self.model_combo.blockSignals(False)
        self._model_changed()

    def _load_decks(self) -> None:
        current = ""
        try:
            current = self.col.decks.name(getattr(self.card, "odid", 0) or self.card.did)
            names = [entry.name for entry in self.col.decks.all_names_and_ids()]
        except Exception:
            names = [current] if current else []
        self.deck_combo.addItems(names)
        if current:
            self.deck_combo.setCurrentText(current)

    def _model_changed(self, _index: int = 0) -> None:
        model = self.models.get(self.model_combo.currentText()) or {}
        fields = authoring.model_fields(model)
        if getattr(self, "_cards", None):
            self._cards = []
            self.table.setRowCount(0)
            self.add_button.setEnabled(False)
        headers = [self._t("authoring_apply")] + fields + [self._t("authoring_source_quote")]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 48)

    def _generate(self) -> None:
        if self.runner:
            self.runner.abort()
        model = self.models.get(self.model_combo.currentText())
        if not model:
            QMessageBox.warning(self, self.windowTitle(), self._t("authoring_parse_failed"))
            return
        system, user = authoring.cards_messages(
            self.card_content, self.messages, model,
            self.count_spin.value(), self.extra_edit.text(),
        )
        self.generate_button.setEnabled(False)
        self.status.setText(self._t("authoring_loading"))
        self.runner = AuthoringRunner(
            self.config, self, source="conversation_cards",
            usage_callback=self._record_usage,
        )
        self.runner.job_finished.connect(self._generated)
        self.runner.start([{
            "id": 1, "system": system, "user": user,
            "schema": authoring.cards_schema(authoring.model_fields(model)),
        }])

    def _record_usage(self, payload: dict) -> None:
        if self.usage_store is None:
            return
        try:
            self.usage_store.record(
                payload["usage"], model=payload.get("model", ""),
                mode=payload.get("mode", ""), source=payload.get("source", "conversation_cards"),
            )
        except Exception:
            traceback.print_exc()

    def _generated(self, _job_id: int, text: str, error: str) -> None:
        self.generate_button.setEnabled(True)
        if error:
            self.status.setText(f"{self._t('authoring_generate_failed')} {self._error_text(error)}")
            return
        model = self.models.get(self.model_combo.currentText()) or {}
        fields = authoring.model_fields(model)
        try:
            cards, warnings = authoring.parse_cards(
                text, fields, authoring.is_cloze(model),
                authoring.cloze_field(model), self.count_spin.value(),
            )
        except Exception as exception:
            self.status.setText(self._t("authoring_parse_failed") + " " + str(exception))
            return
        self._cards = cards
        self._warnings = warnings
        self._fill_table(fields)
        self.status.setText(self._t("authoring_generated"))
        self.warning_label.setText("\n".join(warnings[:8]))
        self.warning_label.setVisible(bool(warnings))
        self.add_button.setEnabled(bool(cards))

    def _fill_table(self, fields: list[str]) -> None:
        self._filling = True
        self.table.setRowCount(0)
        for card in self._cards:
            row = self.table.rowCount()
            self.table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, check)
            for index, name in enumerate(fields, 1):
                self.table.setItem(row, index, QTableWidgetItem(authoring.plain_text(card.fields.get(name, ""))))
            self.table.setItem(row, len(fields) + 1, QTableWidgetItem(card.source_quote))
        self._filling = False

    def _selected_cards(self):
        model = self.models.get(self.model_combo.currentText()) or {}
        fields = authoring.model_fields(model)
        selected = []
        for row, card in enumerate(getattr(self, "_cards", [])):
            item = self.table.item(row, 0)
            if not item or item.checkState() != Qt.CheckState.Checked:
                continue
            values = {}
            for index, name in enumerate(fields, 1):
                cell = self.table.item(row, index)
                text = cell.text() if cell else ""
                if text.strip():
                    values[name] = authoring.markdown_to_html(text)
            if values:
                selected.append(authoring.CardDraft(values, card.source_quote))
        return selected

    def _add(self) -> None:
        selected = self._selected_cards()
        if not selected:
            QMessageBox.warning(self, self.windowTitle(), self._t("authoring_cards_empty"))
            return
        model = self.models.get(self.model_combo.currentText())
        deck_id = self.col.decks.id_for_name(self.deck_combo.currentText())
        if not model or deck_id is None:
            QMessageBox.warning(self, self.windowTitle(), self._t("authoring_add_failed"))
            return
        try:
            self.receipt = SafeWriter(self.col).add_notes(selected, model, deck_id)
            self.add_button.setEnabled(False)
            self.undo_button.setEnabled(self.receipt.undoable)
            self.status.setText(self._t("authoring_add_summary", count=len(selected)))
            _refresh_anki(self.mw)
        except Exception as error:
            traceback.print_exc()
            QMessageBox.warning(self, self.windowTitle(), str(error))

    def _undo(self) -> None:
        if not self.receipt or not self.receipt.undoable:
            return
        try:
            self.receipt.undo(self.col)
            self.receipt = None
            self.undo_button.setEnabled(False)
            self.add_button.setEnabled(True)
            self.status.setText(self._t("authoring_undone"))
            _refresh_anki(self.mw)
        except Exception as error:
            QMessageBox.warning(self, self.windowTitle(), str(error))

    def reject(self) -> None:
        if self.runner:
            self.runner.abort()
        super().reject()
