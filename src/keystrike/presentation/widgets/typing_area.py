from rich.text import Text
from textual._cells import cell_len
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
    STYLE_WRONG_CURRENT,
)

WORD_DIVIDER = "·"


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
        if i < cursor:
            style = STYLE_CORRECTED if i in session.error_positions else STYLE_CORRECT
        elif i == cursor:
            style = STYLE_WRONG_CURRENT if last_was_wrong else STYLE_CURRENT
        else:
            style = STYLE_PENDING
        text.append(WORD_DIVIDER if ch == " " else ch, style)

    return text


def _word_chunks(plain: str) -> list[str]:
    """Split display plain text into word· chunks."""
    chunks: list[str] = []
    start = 0
    while start < len(plain):
        dot = plain.find(WORD_DIVIDER, start)
        if dot == -1:
            chunks.append(plain[start:])
            break
        chunks.append(plain[start : dot + 1])
        start = dot + 1
    return chunks


def wrap_typing_text(text: Text, width: int) -> Text:
    """Insert hard newlines at · word boundaries for Textual display width."""
    if width <= 0 or "\n" in text.plain:
        return text

    chunks = _word_chunks(text.plain)
    if len(chunks) <= 1:
        return text

    lines: list[list[str]] = [[]]
    line_len = 0
    for chunk in chunks:
        chunk_len = cell_len(chunk)
        if chunk_len > width:
            if lines[-1]:
                lines.append([])
                line_len = 0
            lines[-1].append(chunk)
            lines.append([])
            line_len = 0
            continue
        if line_len and line_len + chunk_len > width:
            lines.append([])
            line_len = 0
        lines[-1].append(chunk)
        line_len += chunk_len

    if lines and not lines[-1]:
        lines.pop()
    if len(lines) <= 1:
        return text

    breaks: list[int] = []
    offset = 0
    for line_chunks in lines[:-1]:
        offset += sum(len(chunk) for chunk in line_chunks)
        breaks.append(offset)

    wrapped = Text()
    for index, part in enumerate(text.divide(breaks)):
        if index:
            wrapped.append("\n")
        wrapped.append(part)
    return wrapped


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

    def on_mount(self) -> None:
        self.call_after_refresh(self.refresh_display)

    def on_resize(self) -> None:
        self.refresh_display()

    def _render_text(self) -> Text:
        text = render_typing_text(self._session)
        static = self.query_one("#typing-text", Static)
        width = static.content_region.width
        if width > 0:
            text = wrap_typing_text(text, width)
        return text

    def refresh_display(self) -> None:
        static = self.query_one("#typing-text", Static)
        static.update(self._render_text())

    def set_session(self, session: Session) -> None:
        self._session = session
        self.refresh_display()
