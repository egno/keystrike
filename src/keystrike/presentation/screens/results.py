from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import Footer, Static

from keystrike.application.session_use_cases import compute_accuracy, compute_wpm
from keystrike.domain.models import SessionResult


class ResultsScreen(Screen[None]):
    DEFAULT_CSS = """
    ResultsScreen {
        align: center middle;
    }
    ResultsScreen > #results-text {
        width: auto;
        height: auto;
        padding: 2 4;
        text-align: center;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit_app", "Quit"),
        Binding("ctrl+q", "quit_app", "Quit", priority=True),
        Binding("enter", "back_to_home", "Continue"),
        Binding("escape", "back_to_home", "Close"),
    ]

    def __init__(self, result: SessionResult) -> None:
        super().__init__()
        self._result = result

    def compose(self) -> ComposeResult:
        r = self._result
        wpm = compute_wpm(r)
        acc = compute_accuracy(r) * 100
        duration = r.duration_ns / 1e9
        lines = [
            "[bold green]Session complete[/]",
            "",
            f"WPM       [bold]{wpm:6.1f}[/]",
            f"Accuracy  [bold]{acc:5.1f}%[/]",
            f"Duration  [bold]{duration:5.1f}s[/]",
            f"Keys      [bold]{r.total_keystrokes}[/] "
            f"([green]{r.correct_keystrokes} correct[/])",
            "",
            "[dim]Press Enter to continue, q to quit[/]",
        ]
        yield Static("\n".join(lines), id="results-text")
        yield Footer()

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_back_to_home(self) -> None:
        self.app.pop_screen()
