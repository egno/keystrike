"""Shared key bindings — one place for cross-screen conventions."""

from textual.binding import Binding, BindingType

BACK = Binding("escape", "back", "Back", priority=True)
BACK_Q = Binding("q", "back", "Back")
QUIT = Binding("ctrl+q", "quit_app", "Quit", priority=True)
SAVE = Binding("ctrl+s", "save", "Save", priority=True)

BACK_BINDINGS: list[BindingType] = [BACK, BACK_Q]
