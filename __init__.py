"""Anki Tutor add-on entry point."""

from aqt import gui_hooks, mw

from .browser_tools import register as register_browser_tools
from .panel import TutorPanel

_panel = None


def _on_main_window_ready() -> None:
    global _panel
    if _panel is None:
        _panel = TutorPanel(mw)
        _panel.open_profile()


def _on_profile_open() -> None:
    if _panel is not None:
        _panel.open_profile()


def _on_profile_close() -> None:
    if _panel is not None:
        _panel.close_profile()


def _on_question(card) -> None:
    if _panel is not None:
        _panel.set_answer_visible(False)
        _panel.show_card(card)


def _on_answer(card) -> None:
    if _panel is not None:
        _panel.set_answer_visible(True)
        _panel.show_card(card)


def _on_state_change(new_state, old_state) -> None:
    if _panel is not None and new_state != "review":
        _panel.leave_review()


def _on_addon_install(manager, module) -> None:
    if _panel is not None and module == manager.addonFromModule(__name__):
        _panel.close_profile()


gui_hooks.main_window_did_init.append(_on_main_window_ready)
gui_hooks.profile_did_open.append(_on_profile_open)
gui_hooks.profile_will_close.append(_on_profile_close)
gui_hooks.reviewer_did_show_question.append(_on_question)
gui_hooks.reviewer_did_show_answer.append(_on_answer)
gui_hooks.state_did_change.append(_on_state_change)
mw.addonManager.setWebExports(__name__, r"web/.*")
register_browser_tools()
if hook := getattr(gui_hooks, "addon_manager_will_install_addon", None):
    hook.append(_on_addon_install)
