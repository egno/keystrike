from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Footer, Static

from keystrike.application.settings_use_cases import CycleLayout
from keystrike.domain.enums import PracticeSource
from keystrike.domain.protocols import SettingsRepository


def _hero_text(layout: str, has_freeform: bool) -> str:
    free_hint = "Press [bold]f[/] to practice your own text." if has_freeform else (
        "[dim]Set a freeform_path in Settings to unlock free-text practice.[/]"
    )
    return (
        "[bold cyan]keystrike[/]\n"
        "[dim]offline typing tutor[/]\n\n"
        f"Layout: [bold]{layout}[/]  (press [bold]l[/] to switch)\n\n"
        "Press [bold]Enter[/] for an adaptive lesson (keybr-style).\n"
        "Press [bold]p[/] to practice a fixed sample text.\n"
        "Press [bold]c[/] to practice Python code.\n"
        f"{free_hint}\n"
        "Press [bold]s[/] for Stats, [bold]o[/] for Settings, [bold]Ctrl+Q[/] to quit."
    )


class HomeScreen(Screen[None]):
    DEFAULT_CSS = """
    HomeScreen {
        align: center middle;
    }
    HomeScreen > #home-hero {
        width: auto;
        height: auto;
        padding: 2 4;
        text-align: center;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "practice_adaptive", "Adaptive"),
        Binding("p", "practice_sample", "Sample text"),
        Binding("c", "practice_code", "Code"),
        Binding("f", "practice_free", "Free text"),
        Binding("s", "open_stats", "Stats"),
        Binding("o", "open_settings", "Settings"),
        Binding("l", "cycle_layout", "Switch layout"),
        Binding("ctrl+q", "quit_app", "Quit", priority=True),
    ]

    class StartPractice(Message):
        def __init__(self, source: PracticeSource) -> None:
            self.source = source
            super().__init__()

    class OpenStats(Message):
        pass

    class OpenSettings(Message):
        pass

    def __init__(self, *, settings_repo: SettingsRepository, cycle_layout: CycleLayout) -> None:
        super().__init__()
        self._settings_repo = settings_repo
        self._cycle_layout = cycle_layout

    def compose(self) -> ComposeResult:
        yield Static(self._render_hero(), id="home-hero")
        yield Footer()

    def on_screen_resume(self) -> None:
        self._refresh_hero()

    def _render_hero(self) -> str:
        settings = self._settings_repo.load()
        return _hero_text(settings.layout, bool(settings.freeform_path))

    def _refresh_hero(self) -> None:
        self.query_one("#home-hero", Static).update(self._render_hero())

    def action_practice_adaptive(self) -> None:
        self.post_message(self.StartPractice(source=PracticeSource.ADAPTIVE))

    def action_practice_sample(self) -> None:
        self.post_message(self.StartPractice(source=PracticeSource.SAMPLE))

    def action_practice_code(self) -> None:
        self.post_message(self.StartPractice(source=PracticeSource.CODE))

    def action_practice_free(self) -> None:
        self.post_message(self.StartPractice(source=PracticeSource.FREE))

    def action_open_stats(self) -> None:
        self.post_message(self.OpenStats())

    def action_open_settings(self) -> None:
        self.post_message(self.OpenSettings())

    def action_cycle_layout(self) -> None:
        self._cycle_layout()
        self._refresh_hero()

    def action_quit_app(self) -> None:
        self.app.exit()
