"""Read-only weak-area report with local meta-learning guidance."""

from __future__ import annotations

from aqt.qt import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    Qt,
)

try:
    from . import insights
    from .authoring_style import apply_dialog_style
except ImportError:
    import insights
    from authoring_style import apply_dialog_style


class WeakAreasDialog(QDialog):
    def __init__(self, panel, initial=None) -> None:
        super().__init__(panel.mw)
        self.panel = panel
        self.insights = initial
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle(panel.text("weak_title"))
        self.resize(900, 680)
        layout = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setObjectName("authoringTitle")
        layout.addWidget(self.title)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.retention = QLabel()
        self.retention.setObjectName("authoringHint")
        layout.addWidget(self.retention)
        self.focus_title = QLabel()
        self.focus_title.setObjectName("authoringHint")
        layout.addWidget(self.focus_title)
        self.focus = QLabel()
        self.focus.setWordWrap(True)
        self.focus.setObjectName("tutorHomeFocus")
        layout.addWidget(self.focus)
        self.areas = QLabel()
        self.areas.setWordWrap(True)
        self.areas.setObjectName("authoringHint")
        layout.addWidget(self.areas)
        self.table = QTableWidget(0, 6)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("authoringHint")
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.copy_button = QPushButton()
        self.copy_button.clicked.connect(self._copy)
        buttons.addWidget(self.copy_button)
        self.ask_button = QPushButton()
        self.ask_button.setObjectName("authoringPrimary")
        self.ask_button.clicked.connect(self._ask)
        buttons.addWidget(self.ask_button)
        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self._refresh)
        buttons.addWidget(self.refresh_button)
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.status = QLabel()
        self.status.setObjectName("authoringHint")
        layout.addWidget(self.status)
        apply_dialog_style(self, panel.mw, panel.config)
        self._translate()
        self._refresh()

    def _translate(self) -> None:
        text = self.panel.text
        self.title.setText(text("weak_title"))
        self.focus_title.setText(text("home_focus"))
        self.copy_button.setText(text("weak_copy"))
        self.ask_button.setText(text("weak_ask"))
        self.refresh_button.setText(text("weak_refresh"))
        self.close_button.setText(text("weak_close"))
        self.note.setText(text("weak_analysis"))
        self.table.setHorizontalHeaderLabels([
            text("weak_card"), text("weak_deck"), text("weak_lapses"),
            text("weak_ease"), text("weak_interval"), text("weak_reason"),
        ])

    def _refresh(self) -> None:
        try:
            self.insights = insights.analyze(self.panel.mw.col)
        except Exception:
            self.insights = None
        self._render()

    def _render(self) -> None:
        text = self.panel.text
        if self.insights is None:
            self.summary.setText(text("home_analysis_failed"))
            self.retention.clear()
            self.focus.clear()
            self.areas.clear()
            self.table.setRowCount(0)
            self.status.clear()
            return
        data = self.insights
        self.summary.setText(text(
            "weak_summary", due=data.due, new=data.new, learning=data.learning
        ))
        retention = (
            text("home_retention_value", value=round(data.retention_30d * 100))
            if data.retention_30d is not None else text("home_retention_unknown")
        )
        self.retention.setText(
            f"{text('weak_retention', value=retention)} ? "
            f"{text('home_leeches')}: {data.leeches} ? "
            f"{text('home_today')}: {text('home_today_reviews', count=data.today_reviews)}"
        )
        focus = []
        if data.leeches:
            focus.append(f"{text('home_leeches')}: {data.leeches}")
        if data.retention_30d is not None and data.retention_30d < 0.85:
            focus.append(text("weak_retention", value=retention))
        if data.weak_tags:
            focus.append(", ".join(area.name for area in data.weak_tags[:6]))
        if data.today_again:
            focus.append(text("home_today_again", count=data.today_again))
        if not focus:
            focus = [text("weak_not_enough")]
        self.focus.setText("\n".join(focus))
        areas = []
        if data.weak_decks:
            areas.append("Decks: " + ", ".join(f"{a.name} ({a.count})" for a in data.weak_decks))
        if data.weak_tags:
            areas.append("Tags: " + ", ".join(f"{a.name} ({a.count})" for a in data.weak_tags))
        self.areas.setText("\n".join(areas))
        self.table.setRowCount(0)
        for card in data.weak_cards:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                card.front,
                card.deck,
                str(card.lapses),
                str(card.ease),
                str(card.interval),
                ", ".join(card.reasons),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(card.back if column == 0 else value)
                self.table.setItem(row, column, item)
        if not data.weak_cards:
            self.status.setText(text("weak_empty"))
        else:
            self.status.setText(text("weak_hint"))
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def _copy(self) -> None:
        if self.insights is None:
            return
        QApplication.clipboard().setText(insights.brief(self.insights))
        self.status.setText(self.panel.text("weak_brief_copied"))

    def _ask(self) -> None:
        if self.insights is None:
            return
        self.panel._ask_collection_brief(self.insights)
        self.hide()
