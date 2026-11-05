"""Token usage dashboard embedded in the settings tabs."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from aqt.qt import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    Qt,
)

try:
    from .authoring_style import apply_dialog_style
except ImportError:
    from authoring_style import apply_dialog_style


def _number(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _when(timestamp: int) -> str:
    try:
        return datetime.fromtimestamp(int(timestamp) / 1000).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


class TokenUsagePage(QWidget):
    def __init__(self, panel) -> None:
        super().__init__()
        self.panel = panel
        self.store = None
        self.setObjectName("tutorUsagePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(9)
        top = QHBoxLayout()
        self.range_combo = QComboBox()
        self.range_combo.addItem("", 0)
        self.range_combo.addItem("", 1)
        self.range_combo.addItem("", 7)
        self.range_combo.addItem("", 30)
        self.range_combo.addItem("", 90)
        self.range_combo.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.range_combo, 1)
        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        self.export_button = QPushButton()
        self.export_button.clicked.connect(self._export)
        top.addWidget(self.export_button)
        layout.addLayout(top)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("tutorHomeSummary")
        layout.addWidget(self.summary)
        self.status = QLabel()
        self.status.setObjectName("authoringHint")
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        self.model_table = self._table()
        self.day_table = self._table()
        self.recent_table = self._table()
        self.tabs.addTab(self.model_table, "")
        self.tabs.addTab(self.day_table, "")
        self.tabs.addTab(self.recent_table, "")
        layout.addWidget(self.tabs, 1)
        self._translate()
        apply_dialog_style(self, panel.mw, panel.config)

    @staticmethod
    def _table() -> QTableWidget:
        table = QTableWidget(0, 0)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def _translate(self) -> None:
        text = self.panel.text
        self.range_combo.setItemText(0, text("usage_range_all"))
        self.range_combo.setItemText(1, text("usage_range_24h"))
        self.range_combo.setItemText(2, text("usage_range_7"))
        self.range_combo.setItemText(3, text("usage_range_30"))
        self.range_combo.setItemText(4, text("usage_range_90"))
        self.refresh_button.setText(text("usage_refresh"))
        self.export_button.setText(text("usage_export"))
        self.tabs.setTabText(0, text("usage_models"))
        self.tabs.setTabText(1, text("usage_daily"))
        self.tabs.setTabText(2, text("usage_recent"))
        self.model_table.setHorizontalHeaderLabels([
            text("usage_model"), text("usage_requests"), text("usage_input"),
            text("usage_output"), text("usage_total"), text("usage_cached"),
            text("usage_share"),
        ])
        self.day_table.setHorizontalHeaderLabels([
            text("usage_date"), text("usage_requests"), text("usage_input"),
            text("usage_output"), text("usage_total"), text("usage_cached"),
        ])
        self.recent_table.setHorizontalHeaderLabels([
            text("usage_time"), text("usage_source"), text("usage_model"),
            text("usage_input"), text("usage_output"), text("usage_total"),
        ])
        self.summary.setText(text("usage_empty"))

    def retranslate(self) -> None:
        self._translate()

    def set_store(self, store) -> None:
        self.store = store
        self.refresh()

    def _days(self) -> int:
        return int(self.range_combo.currentData() or 0)

    def refresh(self, *_args) -> None:
        text = self.panel.text
        if self.store is None:
            self.summary.setText(text("usage_empty"))
            self.status.clear()
            self._fill(self.model_table, [])
            self._fill(self.day_table, [])
            self._fill(self.recent_table, [])
            return
        days = self._days()
        data = self.store.summary(days)
        self.summary.setText(text(
            "usage_summary", requests=_number(data["requests"]),
            total=_number(data["total"]), input=_number(data["input"]),
            output=_number(data["output"]), cached=_number(data["cached"]),
            models=_number(data["models"]),
        ))
        models = self.store.by_model(days)
        model_total = sum(row["total"] for row in models)
        model_rows = []
        for row in models:
            share = f"{row['total'] / model_total * 100:.1f}%" if model_total else "0%"
            model_rows.append([
                row["model"], _number(row["requests"]), _number(row["input"]),
                _number(row["output"]), _number(row["total"]), _number(row["cached"]),
                share,
            ])
        self._fill(self.model_table, model_rows)
        self._fill(self.day_table, [
            [
                row["date"], _number(row["requests"]), _number(row["input"]),
                _number(row["output"]), _number(row["total"]), _number(row["cached"]),
            ]
            for row in self.store.by_day(days)
        ])
        self._fill(self.recent_table, [
            [
                _when(row["created_at"]), row["source"] or "-", row["model"] or "-",
                _number(row["input"]), _number(row["output"]), _number(row["total"]),
            ]
            for row in self.store.recent(days, 100)
        ])
        self.status.setText(text("usage_data_hint"))

    @staticmethod
    def _fill(table: QTableWidget, rows: list[list[str]]) -> None:
        table.setRowCount(0)
        for values in rows:
            row = table.rowCount()
            table.insertRow(row)
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, column, item)

    def _export(self) -> None:
        if self.store is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, self.panel.text("usage_export"), "anki-tutor-token-usage.csv", "CSV (*.csv)"
        )
        if not filename:
            return
        try:
            with Path(filename).open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    "created_at", "model", "mode", "source", "input_tokens",
                    "output_tokens", "total_tokens", "cached_tokens",
                    "conversation_id", "message_id",
                ])
                for row in self.store.csv_rows(self._days()):
                    writer.writerow([
                        _when(row["created_at"]), row["model"], row["mode"], row["source"],
                        row["input"], row["output"], row["total"], row["cached"],
                        row["conversation_id"] or "", row["message_id"] or "",
                    ])
            self.status.setText(self.panel.text("usage_exported"))
        except OSError as error:
            QMessageBox.warning(self, self.panel.text("usage_title"), str(error))
