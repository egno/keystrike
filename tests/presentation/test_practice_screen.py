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
from keystrike.application.stats_use_cases import GetHeatmap, GetHistory, RebuildAggregates
from keystrike.domain.enums import Mode, SessionState
from keystrike.domain.models import SessionResult, Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from keystrike.presentation.screens.home import HomeScreen
from keystrike.presentation.screens.practice import PracticeScreen
from keystrike.presentation.screens.settings import SettingsScreen
from keystrike.presentation.screens.stats import StatsScreen
from keystrike.presentation.textual_app import KeystrikeApp
from keystrike.presentation.widgets.kb_heatmap import KbHeatmap
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeIdGenerator,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
)

_TZ = dt.timezone(dt.timedelta(hours=3))


def _build_app(
    *,
    clock: FakeClock | None = None,
    settings: Settings | None = None,
    headers: list[SessionResult] | None = None,
) -> tuple[KeystrikeApp, FakeClock, FakeSessionRepository, FakeSettingsRepository]:
    clock = clock or FakeClock(
        wall=dt.datetime(2026, 7, 28, 12, 0, tzinfo=_TZ).timestamp(),
    )
    id_gen = FakeIdGenerator()
    session_repo = FakeSessionRepository(headers=headers or [])
    settings_repo = FakeSettingsRepository(settings or Settings())
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    cache = FakeAggregatesCache()
    build_lesson = BuildLesson(
        layout_repo=layout_repo,
        aggregates_cache=cache,
        settings_repo=settings_repo,
        language_provider=FakeLanguageProvider(),
        rng=Random(0),
    )
    get_daily_learn_budget = GetDailyLearnBudget(
        clock=clock, repo=session_repo, settings_repo=settings_repo, tz=_TZ,
    )
    prepare_practice = PreparePracticeSession(
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        build_lesson=build_lesson,
        get_daily_learn_budget=get_daily_learn_budget,
    )

    app = KeystrikeApp(
        clock=clock,
        start=StartSession(clock=clock, id_gen=id_gen),
        record=RecordKeystroke(clock=clock, repo=session_repo),
        finish=FinishSession(clock=clock, repo=session_repo),
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        prepare_practice=prepare_practice,
        rebuild_aggregates=RebuildAggregates(repo=session_repo, cache=cache),
        get_heatmap=GetHeatmap(cache=cache, settings_repo=settings_repo),
        get_history=GetHistory(repo=session_repo),
        get_daily_learn_budget=get_daily_learn_budget,
        cycle_layout=CycleLayout(settings_repo=settings_repo, layout_repo=layout_repo),
        update_settings=UpdateSettings(repo=settings_repo),
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
        assert isinstance(app.screen, PracticeScreen)
        assert app.screen._session.position >= 1


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
        history_text = str(app.screen.query_one("#stats-history", Static).content)
        assert "No sessions yet" in history_text


@pytest.mark.asyncio
async def test_adaptive_blocked_when_daily_learn_limit_reached():
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
    app, _clock, _repo, _settings = _build_app(headers=[header])
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_adaptive_practice_generates_lesson_text_for_focus_key():
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
        assert practice._session.position == 0
        assert practice._session.target_text


@pytest.mark.asyncio
async def test_escape_returns_to_home_and_cancels_session():
    app, _clock, _repo, _settings = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)

        await pilot.press("escape")
        await pilot.pause()

        assert practice._session.state is SessionState.CANCELLED
        assert isinstance(app.screen, HomeScreen)
