import datetime as dt
from random import Random

import pytest
from textual.widgets import Static

from keystrike.application.build_lesson import BuildLesson
from keystrike.application.learn_budget_use_cases import GetDailyLearnBudget
from keystrike.application.prepare_practice import PreparePracticeSession
from keystrike.application.session_use_cases import (
    FinishSession,
    RecordKeystroke,
    StartSession,
)
from keystrike.application.settings_use_cases import CycleLayout, UpdateSettings
from keystrike.application.stats_use_cases import (
    GetAggregateMetricTrends,
    GetHeatmap,
    GetHistory,
    GetKeyMetricTrends,
    RebuildAggregates,
)
from keystrike.application.wordlist_use_cases import (
    ClearWordList,
    GetWordListCacheStatus,
    ImportWordList,
)
from keystrike.domain.enums import Mode, SessionState
from keystrike.domain.models import Keystroke, SessionResult, Settings
from keystrike.domain.session import LEARN_IDLE_PAUSE_NS, active_typing_duration_ns, is_typing_idle
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from keystrike.presentation.screens.home import HomeScreen
from keystrike.presentation.screens.practice import PracticeScreen
from keystrike.presentation.screens.settings import SettingsScreen
from keystrike.presentation.screens.stats import StatsScreen
from keystrike.presentation.textual_app import KeystrikeApp
from keystrike.presentation.widgets.hud import HUD
from keystrike.presentation.widgets.kb_heatmap import KbHeatmap
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeIdGenerator,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
    FakeWordListStore,
)

_TZ = dt.timezone(dt.timedelta(hours=3))


def _build_app(
    *,
    clock: FakeClock | None = None,
    settings: Settings | None = None,
    session_repo: FakeSessionRepository | None = None,
) -> tuple[KeystrikeApp, FakeClock, FakeSessionRepository, FakeSettingsRepository]:
    clock = clock or FakeClock(
        wall=dt.datetime(2026, 7, 28, 12, 0, tzinfo=_TZ).timestamp(),
    )
    id_gen = FakeIdGenerator()
    session_repo = session_repo or FakeSessionRepository()
    settings_repo = FakeSettingsRepository(settings or Settings())
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    cache = FakeAggregatesCache()
    wordlist_store = FakeWordListStore()
    build_lesson = BuildLesson(
        layout_repo=layout_repo,
        aggregates_cache=cache,
        settings_repo=settings_repo,
        language_provider=FakeLanguageProvider(),
        wordlist_store=wordlist_store,
        rng=Random(0),
    )
    get_daily_learn_budget = GetDailyLearnBudget(
        clock=clock, repo=session_repo, settings_repo=settings_repo, tz=_TZ,
    )
    rebuild_aggregates = RebuildAggregates(
        repo=session_repo, cache=cache, settings_repo=settings_repo,
    )
    prepare_practice = PreparePracticeSession(
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        build_lesson=build_lesson,
        get_daily_learn_budget=get_daily_learn_budget,
        rebuild_aggregates=rebuild_aggregates,
    )

    app = KeystrikeApp(
        clock=clock,
        start=StartSession(clock=clock, id_gen=id_gen),
        record=RecordKeystroke(clock=clock),
        finish=FinishSession(
            clock=clock,
            repo=session_repo,
            settings_repo=settings_repo,
            layout_repo=layout_repo,
        ),
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        prepare_practice=prepare_practice,
        rebuild_aggregates=rebuild_aggregates,
        get_heatmap=GetHeatmap(cache=cache, settings_repo=settings_repo),
        get_history=GetHistory(repo=session_repo),
        get_key_metric_trends=GetKeyMetricTrends(
            repo=session_repo,
            settings_repo=settings_repo,
        ),
        get_aggregate_metric_trends=GetAggregateMetricTrends(
            repo=session_repo,
            settings_repo=settings_repo,
        ),
        get_daily_learn_budget=get_daily_learn_budget,
        cycle_layout=CycleLayout(settings_repo=settings_repo, layout_repo=layout_repo),
        update_settings=UpdateSettings(repo=settings_repo),
        import_wordlist=ImportWordList(store=wordlist_store, settings_repo=settings_repo),
        clear_wordlist=ClearWordList(settings_repo=settings_repo),
        get_wordlist_cache_status=GetWordListCacheStatus(store=wordlist_store),
    )
    return app, clock, session_repo, settings_repo


@pytest.mark.asyncio
async def test_app_launches_types_and_persists_session():
    app, clock, session_repo, _ = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)
        target = practice._session.target_text
        clock.advance(100_000_000)
        await pilot.press("space" if target[0] == " " else target[0])
        await pilot.pause()
        assert len(session_repo.headers) == 0  # session not finished yet
        assert session_repo.keystrokes == {}
        assert isinstance(app.screen, PracticeScreen)
        assert app.screen._session.position >= 1


@pytest.mark.asyncio
async def test_leading_space_tab_ignored_before_first_keystroke():
    app, _clock, _repo, _ = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)

        await pilot.press("tab")
        await pilot.pause()
        if practice._session.target_text[0] != " ":
            await pilot.press("space")
            await pilot.pause()

        assert practice._session.typing_started_at_ns is None
        assert practice._session.keystrokes == []
        assert practice._session.position == 0


@pytest.mark.asyncio
async def test_stats_screen_reachable_from_home():
    app, _clock, _repo, _settings = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, StatsScreen)


@pytest.mark.asyncio
async def test_settings_screen_reachable_from_home():
    app, _clock, _repo, _settings = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)


@pytest.mark.asyncio
async def test_stats_are_isolated_per_layout():
    app, clock, session_repo, settings_repo = _build_app(settings=Settings(layout="qwerty"))
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)
        target = practice._session.target_text
        for ch in target:
            clock.advance(100_000_000)
            await pilot.press("space" if ch == " " else ch)
            await pilot.pause()
        assert any(h.layout == "qwerty" for h in session_repo.headers)
        app.pop_screen()
        await pilot.pause()

        await pilot.press("l")
        await pilot.pause()
        assert settings_repo.settings.layout != "qwerty"
        await pilot.press("s")
        await pilot.pause()
        trends_text = str(app.screen.query_one("#stats-trends", Static).content)
        assert "No sessions yet" in trends_text


@pytest.mark.asyncio
async def test_adaptive_allowed_when_daily_learn_goal_reached():
    noon = dt.datetime(2026, 7, 28, 12, 0, tzinfo=_TZ).timestamp()
    header = SessionResult(
        schema_version=1,
        session_id="s1",
        started_at=noon,
        duration_ns=10 * 60 * 1_000_000_000,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(),
        focus_key=ord("e"),
        total_keystrokes=1,
        correct_keystrokes=1,
    )
    session_repo = FakeSessionRepository()
    session_repo.save_header(header)
    app, _clock, _repo, _settings = _build_app(session_repo=session_repo)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, PracticeScreen)


@pytest.mark.asyncio
async def test_adaptive_practice_shows_weak_key_focus_note():
    clock = FakeClock(wall=1_700_000_000.0)
    session_repo = FakeSessionRepository()
    session_repo.save_header(
        SessionResult(
            schema_version=3,
            session_id="s1",
            started_at=clock.wall_epoch(),
            duration_ns=60_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(ord("a"), ord("s")),
            focus_key=ord("s"),
            total_keystrokes=4,
            correct_keystrokes=3,
        ),
    )
    session_repo.keystrokes["s1"] = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("s"), typed=ord("s"), t_ns=100_000_000, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=500_000_000, correct=True),
        Keystroke(codepoint=ord("s"), typed=ord("x"), t_ns=600_000_000, correct=False),
    ]
    app, _clock, _repo, _settings = _build_app(
        clock=clock,
        settings=Settings(alphabet_size=2),
        session_repo=session_repo,
    )
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)
        note = str(practice.query_one("#focus-note", Static).content)
        assert "(weak)" in note
        assert "[bold]a[/]" in note
        assert "weak transition" not in note
        assert "speed " in note
        assert "accuracy " in note


@pytest.mark.asyncio
async def test_adaptive_practice_focus_note_shows_speed_and_accuracy():
    app, _clock, _repo, _settings = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)
        note = str(practice.query_one("#focus-note", Static).content)
        if practice._focus_reason:
            assert "speed " in note
            assert "accuracy " in note
            assert "confidence " in note
    app, _clock, _repo, _settings = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)
        assert practice._session.mode is Mode.ADAPTIVE
        assert practice._session.focus_key is not None
        assert practice._session.target_text


@pytest.mark.asyncio
async def test_adaptive_practice_shows_active_keys_widget():
    app, _clock, _repo, _settings = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.query(KbHeatmap)


@pytest.mark.asyncio
async def test_adaptive_shows_last_session_stats_after_completion():
    app, clock, session_repo, _ = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)
        target = practice._session.target_text
        for ch in target:
            clock.advance(100_000_000)
            await pilot.press("space" if ch == " " else ch)
            await pilot.pause()
        assert len(session_repo.headers) == 1
        last_stats = str(practice.query_one("#last-session-stats", Static).content)
        assert "Last: WPM" in last_stats
        assert "Keys" not in last_stats
        assert practice._session.position == 0
        assert practice._session.target_text


@pytest.mark.asyncio
async def test_adaptive_shows_session_deltas_after_second_completion():
    app, clock, session_repo, _ = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)

        async def complete_current(*, ms_per_key: int) -> None:
            target = practice._session.target_text
            for ch in target:
                clock.advance(ms_per_key * 1_000_000)
                await pilot.press("space" if ch == " " else ch)
                await pilot.pause()

        await complete_current(ms_per_key=100)
        first_stats = str(practice.query_one("#last-session-stats", Static).content)
        assert "↑" not in first_stats
        assert "↓" not in first_stats

        await complete_current(ms_per_key=50)
        assert len(session_repo.headers) == 2
        last_stats = str(practice.query_one("#last-session-stats", Static).content)
        assert "[green]" in last_stats
        assert "↑" in last_stats


@pytest.mark.asyncio
async def test_escape_returns_to_home_and_cancels_session():
    app, _clock, session_repo, _settings = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)

        await pilot.press("escape")
        await pilot.pause()

        assert practice._session.state is SessionState.CANCELLED
        assert session_repo.headers == []
        assert session_repo.keystrokes == {}
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_learn_timer_pauses_while_idle_on_practice_screen():
    app, clock, _repo, _settings_repo = _build_app(
        settings=Settings(learn_daily_minutes=10),
    )
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)
        target = practice._session.target_text

        clock.advance(100_000_000)
        await pilot.press("space" if target[0] == " " else target[0])
        await pilot.pause()
        clock.advance(2_000_000_000)
        await pilot.press("space" if target[1] == " " else target[1])
        await pilot.pause()

        clock.advance(LEARN_IDLE_PAUSE_NS + 3_000_000_000)
        practice.query_one(HUD).refresh_display()
        await pilot.pause()

        elapsed = active_typing_duration_ns(practice._session, clock.now_ns())
        assert elapsed == 7_000_000_000  # 2s between keys + 5s idle cap, not 10s wall

        hud_text = str(practice.query_one("#hud-text", Static).content)
        assert "Learn:" in hud_text
        assert "0.1[/]/10" in hud_text


@pytest.mark.asyncio
async def test_hud_learn_dims_while_idle_on_practice_screen():
    app, clock, _repo, _settings = _build_app(
        settings=Settings(learn_daily_minutes=10),
    )
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)
        target = practice._session.target_text

        clock.advance(100_000_000)
        await pilot.press("space" if target[0] == " " else target[0])
        await pilot.pause()
        assert not is_typing_idle(practice._session, clock.now_ns())

        clock.advance(LEARN_IDLE_PAUSE_NS + 1_000_000_000)
        practice.query_one(HUD).refresh_display()
        await pilot.pause()
        assert is_typing_idle(practice._session, clock.now_ns())
        hud_text = str(practice.query_one("#hud-text", Static).content)
        assert "[dim]   Learn:" in hud_text

        clock.advance(100_000_000)
        await pilot.press("space" if target[1] == " " else target[1])
        await pilot.pause()
        assert not is_typing_idle(practice._session, clock.now_ns())
        hud_text = str(practice.query_one("#hud-text", Static).content)
        assert "[dim]   Learn:" not in hud_text
        assert "Learn:" in hud_text
