from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from keystrike.domain.session import Session
from keystrike.presentation.theme import (
    STYLE_CORRECT,
    STYLE_CORRECTED,
    STYLE_CURRENT,
    STYLE_PENDING,
    STYLE_WRONG,
)


def render_typing_text(session: Session) -> Text:
    """Render target text with per-char styling based on session state."""
    target = session.target_text
    cursor = session.position

    # Everything before the cursor is "correct" (wrong chars never advance it);
    # positions that needed at least one correction are dimmed differently so
    # the user can see what tripped them up. The char at the cursor is
    # "current", unless the last keystroke was wrong, in which case it's shown
    # as an inline error marker. Everything after is "pending".
    text = Text(no_wrap=False)

    last_ks = session.keystrokes[-1] if session.keystrokes else None
    last_was_wrong = last_ks is not None and not last_ks.correct and cursor < len(target)

    for i, ch in enumerate(target):
        display = ch if ch != " " else "·"
        if i < cursor:
            style = STYLE_CORRECTED if i in session.error_positions else STYLE_CORRECT
            text.append(display, style)
        elif i == cursor:
            if last_was_wrong:
                text.append(display, STYLE_WRONG)
            else:
                text.append(display, STYLE_CURRENT)
        else:
            text.append(display, STYLE_PENDING)

    return text


class TypingArea(Widget):
    DEFAULT_CSS = """
    TypingArea {
        padding: 1 2;
        height: auto;
    }
    TypingArea > #typing-text {
        height: auto;
    }
    """

    def __init__(self, session: Session) -> None:
        super().__init__()
        self._session = session

    def compose(self) -> ComposeResult:
        yield Static(render_typing_text(self._session), id="typing-text")

    def refresh_display(self) -> None:
        static = self.query_one("#typing-text", Static)
        static.update(render_typing_text(self._session))
