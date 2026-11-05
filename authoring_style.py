"""Shared Anki-native styling for authoring dialogs."""

from __future__ import annotations

from aqt.qt import QPalette
from aqt.theme import theme_manager


def apply_dialog_style(widget, mw, config: dict) -> None:
    palette = mw.app.palette()
    bg = palette.color(QPalette.ColorRole.Window)
    surface = palette.color(QPalette.ColorRole.Base)
    text = palette.color(QPalette.ColorRole.WindowText)
    muted = palette.color(QPalette.ColorRole.PlaceholderText)
    border = palette.color(QPalette.ColorRole.Mid)
    accent = palette.color(QPalette.ColorRole.Highlight)
    font = max(11, min(22, int(config.get("font_size", 14))))
    warning = "#f59e0b" if theme_manager.night_mode else "#b45309"
    warning_bg = "#3a2a08" if theme_manager.night_mode else "#fff7e6"
    widget.setStyleSheet(f"""
        QDialog {{ background: {bg.name()}; color: {text.name()}; font-size: {font}px; }}
        QLabel {{ color: {text.name()}; }}
        QLabel#authoringTitle {{ font-size: {font + 3}px; font-weight: 700; }}
        QLabel#authoringHint {{ color: {muted.name()}; font-size: {max(10, font - 2)}px; }}
        QLabel#authoringWarning {{ color: {warning}; background: {warning_bg};
            border: 1px solid {warning}; border-radius: 5px; padding: 6px 8px; }}
        QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QTableWidget {{
            background: {surface.name()}; color: {text.name()};
            border: 1px solid {border.name()}; border-radius: 5px; padding: 4px;
        }}
        QTableWidget {{ gridline-color: {border.name()}; selection-background-color: {accent.name()}; }}
        QHeaderView::section {{ background: {bg.name()}; color: {muted.name()};
            border: 0; border-bottom: 1px solid {border.name()}; padding: 5px; font-weight: 600; }}
        QPushButton {{ border: 1px solid {border.name()}; border-radius: 5px;
            padding: 5px 12px; background: {surface.name()}; color: {text.name()}; }}
        QPushButton:hover {{ border-color: {accent.name()}; }}
        QPushButton:disabled {{ color: {muted.name()}; }}
        QPushButton#authoringPrimary {{ background: {accent.name()}; color: white;
            border: 0; font-weight: 600; }}
        QToolButton {{ border: 0; border-radius: 4px; padding: 3px 5px; color: {muted.name()}; }}
        QToolButton:hover {{ background: {surface.name()}; color: {text.name()}; }}
    """)
