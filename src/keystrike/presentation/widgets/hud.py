from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from keystrike.domain.protocols import Clock
from keystrike.domain.session import Session


def _format_goal_segment(session: Session, sessions_to_goal: int | None) -> str:
    if session.focus_key is None:
        return ""
    focus_char = chr(session.focus_key)
    goal_text = f"~{sessions_to_goal} sessions" if sessions_to_goal is not None else "learning…"
    return f"   Goal[{focus_char}]: [bold]{goal_text}[/]"


def _format_hud(session: Session, elapsed_ns: int, sessions_to_goal: int | None) -> str:
    minutes = elapsed_ns / 1e9 / 60.0
    wpm = (session.correct_count / 5.0) / minutes if minutes > 0 else 0.0
    accuracy = (session.correct_count / session.total_count) if session.total_count else 1.0
    elapsed_s = elapsed_ns / 1e9
    return (
        f"WPM: [bold]{wpm:5.1f}[/]   "
        f"Acc: [bold]{accuracy * 100:5.1f}%[/]   "
        f"Time: [bold]{elapsed_s:5.1f}s[/]   "
        f"Keys: [bold]{session.total_count}[/]"
        f"{_format_goal_segment(session, sessions_to_goal)}"
    )


class HUD(Widget):
    DEFAULT_CSS = """
    HUD {
        padding: 0 2;
        height: 1;
        color: $accent;
    }
    """

    def __init__(self, session: Session, clock: Clock, sessions_to_goal: int | None = None) -> None:
        super().__init__()
        self._session = session
        self._clock = clock
        self._sessions_to_goal = sessions_to_goal

    def compose(self) -> ComposeResult:
        yield Static(_format_hud(self._session, 0, self._sessions_to_goal), id="hud-text")

    def on_mount(self) -> None:
        self.set_interval(0.1, self.refresh_display)

    def refresh_display(self) -> None:
        started = self._session.typing_started_at_ns
        elapsed = (self._clock.now_ns() - started) if started is not None else 0
        static = self.query_one("#hud-text", Static)
        static.update(_format_hud(self._session, elapsed, self._sessions_to_goal))
