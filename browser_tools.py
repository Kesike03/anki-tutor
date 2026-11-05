"""Browser menu integration for batch authoring."""

from __future__ import annotations

from aqt import gui_hooks, mw
from aqt.qt import QAction, QMenu, QMessageBox

from .bulk_fill import BulkFillDialog
from .i18n import resolve_language, tr

ADDON = __name__.split(".")[0]


def _config() -> dict:
    return dict(mw.addonManager.getConfig(ADDON) or {})


def _selected_note_ids(browser) -> list[int]:
    try:
        return list(browser.selectedNotes())
    except Exception:
        return []


def open_bulk_fill(browser) -> None:
    note_ids = _selected_note_ids(browser)
    if not note_ids:
        language = resolve_language(_config().get("language", "auto"))
        QMessageBox.information(browser, "Anki Tutor", tr(language, "authoring_no_notes"))
        return
    panel = getattr(browser.mw, "_anki_tutor_panel", None)
    usage = getattr(panel, "usage", None)
    dialog = BulkFillDialog(
        browser.mw, note_ids, _config(), parent=browser, usage_store=usage
    )
    dialog.exec()


def _add_browser_menu(browser) -> None:
    form = getattr(browser, "form", None)
    bar = getattr(form, "menubar", None)
    if bar is None and hasattr(browser, "menuBar"):
        bar = browser.menuBar()
    if bar is None:
        return
    for action in bar.actions():
        if action.text() == "Anki Tutor" and action.menu() is not None:
            menu = action.menu()
            break
    else:
        menu = QMenu("Anki Tutor", browser)
        bar.addMenu(menu)
    menu.clear()
    language = resolve_language(_config().get("language", "auto"))
    fill = QAction(tr(language, "bulk_fill_title"), browser)
    fill.triggered.connect(lambda _checked=False, current=browser: open_bulk_fill(current))
    menu.addAction(fill)


def _add_context_menu(browser, menu) -> None:
    if not _selected_note_ids(browser):
        return
    language = resolve_language(_config().get("language", "auto"))
    action = QAction("Anki Tutor: " + tr(language, "bulk_fill_title"), menu)
    action.triggered.connect(lambda _checked=False, current=browser: open_bulk_fill(current))
    menu.addSeparator()
    menu.addAction(action)


def register() -> None:
    if hasattr(gui_hooks, "browser_menus_did_init"):
        gui_hooks.browser_menus_did_init.append(_add_browser_menu)
    if hasattr(gui_hooks, "browser_will_show_context_menu"):
        gui_hooks.browser_will_show_context_menu.append(_add_context_menu)
