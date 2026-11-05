"""Collection home view for the main Anki window."""

from __future__ import annotations

from aqt.qt import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class HomeView(QWidget):
    def __init__(self, panel) -> None:
        super().__init__()
        self.panel = panel
        self.setObjectName("tutorHome")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("tutorHomeScroll")
        content = QWidget()
        content.setObjectName("tutorHomeContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 18)
        layout.setSpacing(9)
        self.title = QLabel()
        self.title.setObjectName("tutorHomeTitle")
        layout.addWidget(self.title)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("tutorDetail")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)
        self.summary = QLabel()
        self.summary.setObjectName("tutorHomeSummary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.retention = QLabel()
        self.retention.setObjectName("tutorHomeMetric")
        layout.addWidget(self.retention)
        self.weak_title = QLabel()
        self.weak_title.setObjectName("tutorSectionLabel")
        layout.addWidget(self.weak_title)
        self.weak_summary = QLabel()
        self.weak_summary.setObjectName("tutorDetail")
        self.weak_summary.setWordWrap(True)
        layout.addWidget(self.weak_summary)
        self.ask_button = QPushButton()
        self.ask_button.setObjectName("tutorHomePrimary")
        self.ask_button.clicked.connect(self.panel._start_collection_chat)
        layout.addWidget(self.ask_button)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.weak_button = QPushButton()
        self.weak_button.setObjectName("tutorHomeAction")
        self.weak_button.clicked.connect(self.panel._show_weak_areas)
        row.addWidget(self.weak_button)
        self.stats_button = QPushButton()
        self.stats_button.setObjectName("tutorHomeAction")
        self.stats_button.clicked.connect(self.panel._ask_for_stats)
        row.addWidget(self.stats_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.recent_notes_button = QPushButton()
        self.recent_notes_button.setObjectName("tutorHomeAction")
        self.recent_notes_button.clicked.connect(self.panel._ask_recent_notes)
        row.addWidget(self.recent_notes_button)
        self.history_button = QPushButton()
        self.history_button.setObjectName("tutorHomeAction")
        self.history_button.clicked.connect(self.panel._show_history)
        row.addWidget(self.history_button)
        self.refresh_button = QPushButton()
        self.refresh_button.setObjectName("tutorHomeAction")
        self.refresh_button.clicked.connect(lambda: self.panel._refresh_home(force=True))
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.focus_title = QLabel()
        self.focus_title.setObjectName("tutorSectionLabel")
        layout.addWidget(self.focus_title)
        self.focus = QLabel()
        self.focus.setObjectName("tutorHomeFocus")
        self.focus.setWordWrap(True)
        layout.addWidget(self.focus)
        self.focus_note = QLabel()
        self.focus_note.setObjectName("tutorDetail")
        self.focus_note.setWordWrap(True)
        layout.addWidget(self.focus_note)
        self.recent_title = QLabel()
        self.recent_title.setObjectName("tutorSectionLabel")
        layout.addWidget(self.recent_title)
        self.recent = QLabel()
        self.recent.setObjectName("tutorDetail")
        self.recent.setWordWrap(True)
        layout.addWidget(self.recent)
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self._translate()

    def _translate(self) -> None:
        text = self.panel.text
        self.title.setText(text("home_study_home"))
        self.subtitle.setText(text("home_subtitle"))
        self.weak_title.setText(text("home_weak_title"))
        self.ask_button.setText(text("home_ask"))
        self.weak_button.setText(text("home_weak_button"))
        self.stats_button.setText(text("home_stats"))
        self.recent_notes_button.setText(text("home_recent_notes"))
        self.history_button.setText(text("home_history"))
        self.refresh_button.setText(text("home_refresh"))
        self.focus_title.setText(text("home_focus"))
        self.focus_note.setText(text("home_focus_note"))
        self.recent_title.setText(text("home_recent"))
        self.retention.setText(text("home_loading"))
        self.weak_summary.setText("")
        self.focus.setText("")
        self.recent.setText("")

    def refresh(self, insights, recent: list[dict]) -> None:
        text = self.panel.text
        if insights is None:
            self.summary.setText(text("home_analysis_failed"))
            self.retention.setText("")
            self.weak_summary.setText("")
            self.focus.setText("")
        else:
            self.summary.setText(text(
                "home_summary", due=insights.due, new=insights.new,
                learning=insights.learning,
            ))
            retention = (
                text("home_retention_value", value=round(insights.retention_30d * 100))
                if insights.retention_30d is not None
                else text("home_retention_unknown")
            )
            self.retention.setText(
                f"{text('home_retention')}: {retention} ? "
                f"{text('home_leeches')}: {insights.leeches} ? "
                f"{text('home_today')}: {text('home_today_reviews', count=insights.today_reviews)}"
            )
            if insights.weak_cards:
                self.weak_summary.setText(text(
                    "home_weak_hint", cards=len(insights.weak_cards),
                    decks=len(insights.weak_decks), tags=len(insights.weak_tags),
                ))
            else:
                self.weak_summary.setText(text("home_weak_empty"))
            focus = []
            if insights.leeches:
                focus.append(f"{text('home_leeches')}: {insights.leeches}")
            if insights.weak_tags:
                focus.append(", ".join(area.name for area in insights.weak_tags[:5]))
            if insights.today_again:
                focus.append(text("home_today_again", count=insights.today_again))
            self.focus.setText(" ? ".join(focus) or text("home_weak_empty"))
        if recent:
            lines = []
            for entry in recent[:4]:
                label = entry.get("title") or entry.get("card_label") or ""
                if entry.get("card_id") == 0:
                    label = f"{text('home_collection_chat')}: {label}"
                if label:
                    lines.append(label)
            self.recent.setText("\n".join(lines))
        else:
            self.recent.setText(text("home_no_recent"))

    def retranslate(self) -> None:
        self._translate()
