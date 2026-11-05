"""Browser-driven batch field generation with preview, diff, and undo."""

from __future__ import annotations

import json
import traceback
from pathlib import Path

from aqt.qt import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from . import authoring
    from .authoring_client import AuthoringRunner
    from .authoring_style import apply_dialog_style
    from .i18n import resolve_language, tr
    from .safe_write import SafeWriter
except ImportError:
    import authoring
    from authoring_client import AuthoringRunner
    from authoring_style import apply_dialog_style
    from i18n import resolve_language, tr
    from safe_write import SafeWriter


ADDON = __name__.split(".")[0]


def _refresh_anki(mw) -> None:
    try:
        mw.reset()
    except Exception:
        pass


def _model_for_note(col, note) -> dict | None:
    for name in ("note_type", "model"):
        getter = getattr(note, name, None)
        if callable(getter):
            try:
                value = getter()
            except Exception:
                continue
            if isinstance(value, dict):
                return value
    mid = int(getattr(note, "mid", 0) or 0)
    if mid and hasattr(col, "models"):
        try:
            return col.models.get(mid)
        except Exception:
            return None
    return None


def _note_label(note, limit: int = 90) -> str:
    try:
        values = [authoring.plain_text(note[name]) for name in note.keys()]
    except Exception:
        values = []
    text = next((value for value in values if value), "")
    return text[:limit] or f"Note {getattr(note, 'id', '')}"


class BulkFillDialog(QDialog):
    def __init__(
        self, mw, note_ids: list[int], config: dict | None = None,
        parent=None, usage_store=None,
    ) -> None:
        super().__init__(parent or mw)
        self.mw = mw
        self.usage_store = usage_store
        self.col = mw.col
        self.config = dict(config or mw.addonManager.getConfig(ADDON) or {})
        self.language = resolve_language(self.config.get("language", "auto"))
        self.notes = []
        self.skipped_notes = 0
        self.models = {}
        self.model_names = []
        self.model_notes = {}
        self.mapping_rows = []
        self.changes: list[authoring.FieldChange] = []
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self.receipt = None
        self.runner = None
        self._filling = False
        self._detail_row = -1
        self._load_notes(note_ids)
        self.setWindowTitle(self._t("bulk_fill_title"))
        self.resize(1040, 780)
        self._build()
        self._load_recipes()
        self._model_changed()

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

    def _load_notes(self, note_ids: list[int]) -> None:
        seen = set()
        for note_id in note_ids:
            if note_id in seen:
                continue
            seen.add(note_id)
            try:
                note = self.col.get_note(note_id)
            except Exception:
                self.skipped_notes += 1
                continue
            model = _model_for_note(self.col, note)
            if not model:
                self.skipped_notes += 1
                continue
            name = str(model.get("name", "Basic"))
            self.notes.append(note)
            self.model_notes.setdefault(name, []).append(note)
            if name not in self.models:
                self.models[name] = model
                self.model_names.append(name)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_setup())
        self.pages.addWidget(self._build_preview())
        layout.addWidget(self.pages)
        self.setLayout(layout)
        apply_dialog_style(self, self.mw, self.config)

    def _build_setup(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 14)
        title = QLabel(self._t("bulk_fill_title"))
        title.setObjectName("authoringTitle")
        layout.addWidget(title)
        hint = QLabel(self._t("bulk_fill_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("authoringHint")
        layout.addWidget(hint)

        top = QHBoxLayout()
        top.addWidget(QLabel(self._t("authoring_note_type")))
        self.model_combo = QComboBox()
        self.model_combo.addItems(self.model_names)
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        top.addWidget(self.model_combo, 1)
        self.count_label = QLabel()
        top.addWidget(self.count_label)
        top.addWidget(QLabel(self._t("authoring_recipe")))
        self.recipe_combo = QComboBox()
        self.recipe_combo.currentIndexChanged.connect(self._recipe_changed)
        top.addWidget(self.recipe_combo, 1)
        self.save_recipe_button = QPushButton(self._t("authoring_save_recipe"))
        self.save_recipe_button.clicked.connect(self._save_recipe)
        top.addWidget(self.save_recipe_button)
        self.delete_recipe_button = QPushButton(self._t("authoring_delete_recipe"))
        self.delete_recipe_button.clicked.connect(self._delete_recipe)
        top.addWidget(self.delete_recipe_button)
        self.import_recipe_button = QPushButton(self._t("import_history"))
        self.import_recipe_button.clicked.connect(self._import_recipes)
        top.addWidget(self.import_recipe_button)
        self.export_recipe_button = QPushButton(self._t("export_history"))
        self.export_recipe_button.clicked.connect(self._export_recipes)
        top.addWidget(self.export_recipe_button)
        layout.addLayout(top)

        self.fields_label = QLabel()
        self.fields_label.setWordWrap(True)
        self.fields_label.setObjectName("authoringHint")
        layout.addWidget(self.fields_label)

        layout.addWidget(QLabel(self._t("authoring_system_prompt")))
        self.system_edit = QPlainTextEdit()
        self.system_edit.setPlaceholderText(self._t("authoring_system_placeholder"))
        self.system_edit.setFixedHeight(78)
        layout.addWidget(self.system_edit)

        layout.addWidget(QLabel(self._t("authoring_user_prompt")))
        self.user_edit = QPlainTextEdit()
        self.user_edit.setPlaceholderText(self._t("authoring_user_placeholder"))
        self.user_edit.setFixedHeight(88)
        layout.addWidget(self.user_edit)

        mapping_row = QHBoxLayout()
        mapping_row.addWidget(QLabel(self._t("authoring_output_mapping")))
        mapping_row.addStretch(1)
        add_button = QPushButton(self._t("authoring_add_mapping"))
        add_button.clicked.connect(lambda: self._add_mapping())
        mapping_row.addWidget(add_button)
        layout.addLayout(mapping_row)

        self.mapping_scroll = QScrollArea()
        self.mapping_scroll.setWidgetResizable(True)
        self.mapping_scroll.setMinimumHeight(118)
        self.mapping_host = QWidget()
        self.mapping_layout = QVBoxLayout(self.mapping_host)
        self.mapping_layout.setContentsMargins(0, 0, 0, 0)
        self.mapping_layout.setSpacing(4)
        self.mapping_layout.addStretch(1)
        self.mapping_scroll.setWidget(self.mapping_host)
        layout.addWidget(self.mapping_scroll, 1)

        self.setup_status = QLabel()
        self.setup_status.setWordWrap(True)
        self.setup_status.setObjectName("authoringHint")
        layout.addWidget(self.setup_status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(self._t("authoring_cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.generate_button = QPushButton(self._t("authoring_generate"))
        self.generate_button.setObjectName("authoringPrimary")
        self.generate_button.clicked.connect(self._generate)
        buttons.addWidget(self.generate_button)
        layout.addLayout(buttons)
        return page

    def _build_preview(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 14)
        title = QLabel(self._t("authoring_preview"))
        title.setObjectName("authoringTitle")
        layout.addWidget(title)
        hint = QLabel(self._t("authoring_preview_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("authoringHint")
        layout.addWidget(hint)
        self.preview_table = QTableWidget(0, 6)
        self.preview_table.setHorizontalHeaderLabels([
            self._t("authoring_apply"),
            self._t("authoring_note"),
            self._t("authoring_field"),
            self._t("authoring_before"),
            self._t("authoring_after"),
            self._t("authoring_status"),
        ])
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.preview_table.setColumnWidth(0, 52)
        self.preview_table.setColumnWidth(2, 120)
        self.preview_table.setColumnWidth(5, 110)
        self.preview_table.itemChanged.connect(self._table_changed)
        self.preview_table.currentCellChanged.connect(self._show_detail)
        layout.addWidget(self.preview_table, 2)

        detail_row = QHBoxLayout()
        detail_label = QLabel(self._t("authoring_editable_preview"))
        detail_row.addWidget(detail_label)
        detail_row.addStretch(1)
        self.detail_status = QLabel()
        self.detail_status.setObjectName("authoringHint")
        detail_row.addWidget(self.detail_status)
        layout.addLayout(detail_row)
        self.detail_edit = QPlainTextEdit()
        self.detail_edit.setPlaceholderText(self._t("authoring_edit_hint"))
        self.detail_edit.setFixedHeight(94)
        self.detail_edit.textChanged.connect(self._detail_changed)
        layout.addWidget(self.detail_edit)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setObjectName("authoringWarning")
        layout.addWidget(self.warning_label)
        self.preview_status = QLabel()
        self.preview_status.setWordWrap(True)
        self.preview_status.setObjectName("authoringHint")
        layout.addWidget(self.preview_status)
        buttons = QHBoxLayout()
        back = QPushButton(self._t("authoring_back"))
        back.clicked.connect(self._back)
        buttons.addWidget(back)
        self.select_all = QCheckBox(self._t("authoring_select_all"))
        self.select_all.setChecked(True)
        self.select_all.toggled.connect(self._set_all_checked)
        buttons.addWidget(self.select_all)
        buttons.addStretch(1)
        self.undo_button = QPushButton(self._t("authoring_undo"))
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self._undo)
        buttons.addWidget(self.undo_button)
        self.apply_button = QPushButton(self._t("authoring_apply"))
        self.apply_button.setObjectName("authoringPrimary")
        self.apply_button.clicked.connect(self._apply)
        buttons.addWidget(self.apply_button)
        close = QPushButton(self._t("authoring_close"))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        return page

    def _load_recipes(self) -> None:
        self.recipes = []
        raw = self.config.get("authoring_recipes", [])
        if isinstance(raw, list):
            for value in raw:
                try:
                    self.recipes.append(authoring.BulkRecipe.from_dict(value))
                except authoring.AuthoringError:
                    continue
        self.recipe_combo.blockSignals(True)
        self.recipe_combo.clear()
        self.recipe_combo.addItem(self._t("authoring_no_recipe"), -1)
        for index, recipe in enumerate(self.recipes):
            self.recipe_combo.addItem(recipe.name or f"Recipe {index + 1}", index)
        self.recipe_combo.setCurrentIndex(0)
        self.recipe_combo.blockSignals(False)

    def _recipe_changed(self, _index: int) -> None:
        index = self.recipe_combo.currentData()
        if index is None or index < 0 or index >= len(self.recipes):
            return
        recipe = self.recipes[index]
        if recipe.note_type:
            target = self.model_combo.findText(recipe.note_type)
            if target >= 0:
                self.model_combo.setCurrentIndex(target)
        self.system_edit.setPlainText(recipe.system_prompt)
        self.user_edit.setPlainText(recipe.user_prompt)
        for row, key, _combo in list(self.mapping_rows):
            row.setParent(None)
            row.deleteLater()
        self.mapping_rows.clear()
        for key, target in recipe.mapping.items():
            self._add_mapping(key, target)

    def _save_recipe(self) -> None:
        name, accepted = QInputDialog.getText(
            self, self._t("authoring_save_recipe"), self._t("authoring_recipe_name")
        )
        name = name.strip()
        if not accepted or not name:
            return
        recipe = authoring.BulkRecipe(
            name=name,
            note_type=self.model_combo.currentText(),
            system_prompt=self.system_edit.toPlainText().strip(),
            user_prompt=self.user_edit.toPlainText().strip(),
            mapping=self._mapping_values(),
        )
        self.recipes = [item for item in self.recipes if item.name != name]
        self.recipes.append(recipe)
        self.config["authoring_recipes"] = [item.to_dict() for item in self.recipes]
        self.mw.addonManager.writeConfig(ADDON, self.config)
        self._load_recipes()
        self.recipe_combo.setCurrentIndex(self.recipe_combo.findText(name))

    def _delete_recipe(self) -> None:
        index = self.recipe_combo.currentData()
        if index is None or index < 0:
            return
        recipe = self.recipes[index]
        if QMessageBox.question(
            self, self._t("authoring_delete_recipe"),
            self._t("authoring_delete_recipe_confirm", name=recipe.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.recipes = [item for item in self.recipes if item.name != recipe.name]
        self.config["authoring_recipes"] = [item.to_dict() for item in self.recipes]
        self.mw.addonManager.writeConfig(ADDON, self.config)
        self._load_recipes()

    def _import_recipes(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, self._t("import_history"), "", "JSON (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            raw = payload.get("recipes") if isinstance(payload, dict) else payload
            if not isinstance(raw, list):
                raise ValueError("Invalid recipe file")
            imported = [authoring.BulkRecipe.from_dict(value) for value in raw]
        except Exception:
            QMessageBox.warning(self, self._t("bulk_fill_title"), self._t("file_error"))
            return
        by_name = {recipe.name: recipe for recipe in self.recipes}
        for recipe in imported:
            if recipe.name:
                by_name[recipe.name] = recipe
        self.recipes = list(by_name.values())
        self.config["authoring_recipes"] = [recipe.to_dict() for recipe in self.recipes]
        self.mw.addonManager.writeConfig(ADDON, self.config)
        self._load_recipes()

    def _export_recipes(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self, self._t("export_history"), "anki-tutor-recipes.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            payload = {
                "format": "anki-tutor-recipes",
                "version": 1,
                "recipes": [recipe.to_dict() for recipe in self.recipes],
            }
            Path(path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            QMessageBox.warning(self, self._t("bulk_fill_title"), self._t("file_error"))

    def _model_changed(self, _index: int = 0) -> None:
        name = self.model_combo.currentText()
        model = self.models.get(name) or {}
        self.fields = authoring.model_fields(model)
        notes = self.model_notes.get(name, [])
        self.count_label.setText(self._t("authoring_note_count", count=len(notes)))
        self.fields_label.setText(
            self._t("authoring_fields", fields=", ".join(self.fields) or self._t("authoring_none"))
        )
        for _row, _key, combo in self.mapping_rows:
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self.fields)
            if current in self.fields:
                combo.setCurrentText(current)
            combo.blockSignals(False)
        if not self.mapping_rows and self.fields:
            self._add_mapping("text", authoring.safe_target_field(model))

    def _add_mapping(self, key: str = "", target: str = "") -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        key_edit = QLineEdit(key)
        key_edit.setPlaceholderText(self._t("authoring_output_key"))
        key_edit.setMaximumWidth(240)
        layout.addWidget(key_edit)
        combo = QComboBox()
        combo.addItems(self.fields)
        if target in self.fields:
            combo.setCurrentText(target)
        layout.addWidget(combo, 1)
        remove = QToolButton()
        remove.setText("−")
        remove.setToolTip(self._t("authoring_remove_mapping"))
        remove.clicked.connect(lambda: self._remove_mapping(row))
        layout.addWidget(remove)
        self.mapping_layout.insertWidget(self.mapping_layout.count() - 1, row)
        self.mapping_rows.append((row, key_edit, combo))

    def _remove_mapping(self, row: QWidget) -> None:
        for entry in list(self.mapping_rows):
            if entry[0] is row:
                self.mapping_rows.remove(entry)
                row.setParent(None)
                row.deleteLater()
                return

    def _mapping_values(self) -> dict[str, str]:
        result = {}
        for _row, key_edit, combo in self.mapping_rows:
            key = key_edit.text().strip()
            target = combo.currentText().strip()
            if key and target:
                result[key] = target
        return result

    def _generate(self) -> None:
        if not self.notes:
            QMessageBox.warning(self, self._t("bulk_fill_title"), self._t("authoring_no_notes"))
            return
        mapping = self._mapping_values()
        if not mapping:
            QMessageBox.warning(self, self._t("bulk_fill_title"), self._t("authoring_need_mapping"))
            return
        if len(set(mapping.values())) != len(mapping):
            QMessageBox.warning(self, self._t("bulk_fill_title"), self._t("authoring_duplicate_target"))
            return
        unknown = authoring.unknown_placeholders(self.user_edit.toPlainText(), self.fields)
        if unknown:
            self.setup_status.setText(
                self._t("authoring_unknown_placeholders", names=", ".join(unknown))
            )
        else:
            self.setup_status.clear()
        model_name = self.model_combo.currentText()
        notes = self.model_notes.get(model_name, [])
        system = authoring.bulk_system_prompt(self.system_edit.toPlainText(), list(mapping))
        template = self.user_edit.toPlainText().strip() or self._t("authoring_default_prompt")
        jobs = []
        for note in notes:
            values = {name: str(note[name]) for name in note.keys()}
            user_prompt = authoring.bulk_user_message(template, values)
            jobs.append({
                "id": int(note.id),
                "note": note,
                "system": system,
                "user": user_prompt,
                "schema": authoring.bulk_schema(list(mapping)),
            })
        if not jobs:
            QMessageBox.warning(self, self._t("bulk_fill_title"), self._t("authoring_empty_prompt"))
            return
        self._jobs = {job["id"]: job for job in jobs}
        self._active_mapping = mapping
        self.receipt = None
        self.apply_button.setEnabled(True)
        self.undo_button.setEnabled(False)
        self.changes = []
        self.failures = []
        self.warnings = []
        self.generate_button.setEnabled(False)
        self.setup_status.setText(self._t("authoring_generating"))
        self._set_progress(0, len(jobs))
        self.runner = AuthoringRunner(
            self.config, self, concurrency=3, source="bulk_fill",
            usage_callback=self._record_usage,
        )
        self.runner.job_finished.connect(self._job_finished)
        self.runner.all_finished.connect(self._all_finished)
        self.runner.start(jobs)

    def _record_usage(self, payload: dict) -> None:
        if self.usage_store is None:
            return
        try:
            self.usage_store.record(
                payload["usage"], model=payload.get("model", ""),
                mode=payload.get("mode", ""), source=payload.get("source", "bulk_fill"),
            )
        except Exception:
            traceback.print_exc()

    def _set_progress(self, value: int, total: int) -> None:
        if not hasattr(self, "progress"):
            self.progress = QProgressBar()
            self.progress.setMaximum(total)
            self.layout().addWidget(self.progress)
        self.progress.setMaximum(total)
        self.progress.setValue(value)

    def _job_finished(self, note_id: int, text: str, error: str) -> None:
        job = self._jobs.get(note_id)
        if not job:
            return
        note = job["note"]
        if error:
            self.failures.append(f"{_note_label(note)}: {self._error_text(error)}")
        else:
            try:
                values, warnings = authoring.parse_bulk_response(text, list(self._active_mapping))
                self.warnings.extend(warnings)
                front = authoring.front_fields(
                    self.models.get(self.model_combo.currentText(), {})
                )
                for key, target in self._active_mapping.items():
                    if target in front:
                        self.warnings.append(self._t("authoring_field_used_on_front"))
                    value = values.get(key, "").strip()
                    if not value:
                        self.warnings.append(f"{_note_label(note)}: empty output for {key}")
                        continue
                    before = note[target] if target in list(note.keys()) else ""
                    self.changes.append(authoring.FieldChange(
                        int(note.id), target, before, authoring.safe_html(value),
                        label=_note_label(note),
                    ))
            except Exception as exception:
                self.failures.append(f"{_note_label(note)}: {exception}")
        done = len(self._jobs) - len(self.runner.queue) - len(self.runner.active)
        self._set_progress(done, len(self._jobs))

    def _all_finished(self) -> None:
        self.generate_button.setEnabled(True)
        if hasattr(self, "progress"):
            self.progress.setValue(self.progress.maximum())
        if not self.changes and not self.failures:
            QMessageBox.warning(self, self._t("bulk_fill_title"), self._t("authoring_no_results"))
            return
        self._fill_preview()
        self.pages.setCurrentIndex(1)
        self.preview_status.setText(
            self._t("authoring_results", fields=len(self.changes), notes=len(self._jobs))
        )
        warnings = list(self.warnings)
        if self.failures:
            warnings.extend(self.failures)
        self.warning_label.setText("\n".join(warnings[:8]))
        self.warning_label.setVisible(bool(warnings))

    def _fill_preview(self) -> None:
        self._filling = True
        self.preview_table.setRowCount(0)
        for change in self.changes:
            row = self.preview_table.rowCount()
            self.preview_table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked)
            self.preview_table.setItem(row, 0, check)
            note_item = QTableWidgetItem(change.label)
            note_item.setToolTip(change.label)
            self.preview_table.setItem(row, 1, note_item)
            self.preview_table.setItem(row, 2, QTableWidgetItem(change.field))
            before_item = QTableWidgetItem(authoring.plain_text(change.before))
            before_item.setToolTip(authoring.plain_text(change.before))
            self.preview_table.setItem(row, 3, before_item)
            after_item = QTableWidgetItem(authoring.plain_text(change.after))
            after_item.setToolTip(authoring.plain_text(change.after))
            self.preview_table.setItem(row, 4, after_item)
            self.preview_table.setItem(row, 5, QTableWidgetItem(change.error or self._t("authoring_ready")))
        self._filling = False
        if self.changes:
            self.preview_table.selectRow(0)
            self._show_detail(0, 0, -1, -1)

    def _table_changed(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != 0:
            return
        # The check state is read directly in _apply; no model mutation needed.

    def _set_all_checked(self, checked: bool) -> None:
        self._filling = True
        for row in range(self.preview_table.rowCount()):
            item = self.preview_table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._filling = False

    def _show_detail(self, row: int, _column: int = 0, _previous_row: int = -1, _previous_column: int = -1) -> None:
        if row < 0 or row >= len(self.changes):
            self.detail_edit.clear()
            self._detail_row = -1
            return
        self._detail_row = row
        self._filling = True
        self.detail_edit.setPlainText(authoring.html_to_text(self.changes[row].after))
        self._filling = False
        self.detail_status.setText(self.changes[row].label)

    def _detail_changed(self) -> None:
        if self._filling or self._detail_row < 0 or self._detail_row >= len(self.changes):
            return
        change = self.changes[self._detail_row]
        change.after = authoring.markdown_to_html(self.detail_edit.toPlainText())
        self._filling = True
        item = self.preview_table.item(self._detail_row, 4)
        if item:
            item.setText(authoring.plain_text(change.after))
            item.setToolTip(authoring.plain_text(change.after))
        self._filling = False

    def _apply(self) -> None:
        selected = []
        for row, change in enumerate(self.changes):
            item = self.preview_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked and change.changed:
                selected.append(change)
        if not selected:
            QMessageBox.warning(self, self._t("bulk_fill_title"), self._t("authoring_nothing_selected"))
            return
        try:
            self.receipt = SafeWriter(self.col).apply_fields(selected)
            for change in selected:
                change.error = ""
                row = self.changes.index(change)
                item = self.preview_table.item(row, 5)
                if item:
                    item.setText(self._t("authoring_applied"))
            self.apply_button.setEnabled(False)
            self.undo_button.setEnabled(self.receipt.undoable)
            self.preview_status.setText(self._t("authoring_applied_summary", fields=len(selected)))
            panel = getattr(self.mw, "_anki_tutor_panel", None)
            if panel is not None:
                panel._set_last_write(self.receipt)
            _refresh_anki(self.mw)
        except Exception as error:
            traceback.print_exc()
            QMessageBox.warning(self, self._t("bulk_fill_title"), str(error))

    def _undo(self) -> None:
        if not self.receipt or not self.receipt.undoable:
            return
        try:
            self.receipt.undo(self.col)
            panel = getattr(self.mw, "_anki_tutor_panel", None)
            if panel is not None and panel.last_write is self.receipt:
                panel.last_write = None
                panel.undo_write_button.hide()
            self.receipt = None
            self.undo_button.setEnabled(False)
            self.apply_button.setEnabled(True)
            self.preview_status.setText(self._t("authoring_undone"))
            _refresh_anki(self.mw)
        except Exception as error:
            QMessageBox.warning(self, self._t("bulk_fill_title"), str(error))

    def _back(self) -> None:
        self.pages.setCurrentIndex(0)

    def reject(self) -> None:
        if self.runner:
            self.runner.abort()
        super().reject()
