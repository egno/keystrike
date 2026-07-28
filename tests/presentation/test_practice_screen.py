from random import Random

import pytest
from textual.widgets import Static

from keystrike.application.build_lesson import BuildCodeLesson, BuildLesson
from keystrike.application.session_use_cases import (
    FinishSession,
    RecordKeystroke,
    StartSession,
)
from keystrike.application.settings_use_cases import CycleLayout, UpdateSettings
from keystrike.application.stats_use_cases import (
    GetHeatmap,
    GetHistory,
    GetLearningRate,
    RebuildAggregates,
)
from keystrike.domain.enums import Mode
from keystrike.domain.models import Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from keystrike.presentation.screens.practice import PracticeScreen
from keystrike.presentation.screens.settings import SettingsScreen
from keystrike.presentation.screens.stats import StatsScreen
from keystrike.presentation.textual_app import KeystrikeApp
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeCodeSnippetProvider,
    FakeFreeformTextProvider,
    FakeIdGenerator,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
)


def _build_app(
    *, clock: FakeClock | None = None, settings: Settings | None = None,
) -> tuple[KeystrikeApp, FakeClock, FakeSessionRepository, FakeSettingsRepository]:
    clock = clock or FakeClock()
    id_gen = FakeIdGenerator()
    session_repo = FakeSessionRepository()
    settings_repo = FakeSettingsRepository(settings or Settings())
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    cache = FakeAggregatesCache()

    app = KeystrikeApp(
        clock=clock,
        start=StartSession(clock=clock, id_gen=id_gen),
        record=RecordKeystroke(clock=clock, repo=session_repo),
        finish=FinishSession(clock=clock, repo=session_repo),
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        rebuild_aggregates=RebuildAggregates(
            repo=session_repo, cache=cache, settings_repo=settings_repo,
        ),
        get_heatmap=GetHeatmap(cache=cache, settings_repo=settings_repo),
        get_history=GetHistory(repo=session_repo),
        get_learning_rate=GetLearningRate(repo=session_repo, settings_repo=settings_repo),
        freeform_provider=FakeFreeformTextProvider(),
        cycle_layout=CycleLayout(settings_repo=settings_repo, layout_repo=layout_repo),
        update_settings=UpdateSettings(repo=settings_repo),
        build_lesson=BuildLesson(
            layout_repo=layout_repo,
            aggregates_cache=cache,
            settings_repo=settings_repo,
            language_provider=FakeLanguageProvider(),
            rng=Random(0),
        ),
        build_code_lesson=BuildCodeLesson(
            layout_repo=layout_repo,
            aggregates_cache=cache,
            settings_repo=settings_repo,
            code_provider=FakeCodeSnippetProvider(),
            rng=Random(0),
        ),
        sample_text="hi",
    )
    return app, clock, session_repo, settings_repo


@pytest.mark.asyncio
async def test_app_launches_types_and_persists_session():
    app, clock, session_repo, _ = _build_app()
    async with app.run_test() as pilot:
        # Home screen visible; press "p" to start a sample-text practice session.
        await pilot.press("p")
        await pilot.pause()
        clock.advance(100_000_000)
        await pilot.press("h")
        clock.advance(100_000_000)
        await pilot.press("i")
        await pilot.pause()
        # Now on ResultsScreen — the finished session's header was persisted.
        assert len(session_repo.headers) == 1
        assert session_repo.headers[0].layout == "qwerty"
        await pilot.press("enter")


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
        await pilot.press("p")
        await pilot.pause()
        clock.advance(100_000_000)
        await pilot.press("h")
        clock.advance(100_000_000)
        await pilot.press("i")
        await pilot.pause()
        await pilot.press("enter")  # back to Home from Results
        await pilot.pause()

        assert settings_repo.settings.layout == "qwerty"
        assert any(h.layout == "qwerty" for h in session_repo.headers)

        # Switch to a different layout and open Stats — it should show no history.
        await pilot.press("l")
        await pilot.pause()
        assert settings_repo.settings.layout != "qwerty"
        await pilot.press("s")
        await pilot.pause()
        history_text = str(app.screen.query_one("#stats-history", Static).content)
        assert "No sessions yet" in history_text


@pytest.mark.asyncio
async def test_adaptive_practice_generates_lesson_text_for_focus_key():
    app, _clock, _repo, _settings = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("enter")  # adaptive
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)
        assert practice._mode is Mode.ADAPTIVE
        assert practice._session.focus_key is not None
        assert practice._target_text


@pytest.mark.asyncio
async def test_code_practice_generates_snippet_text_for_focus_key():
    app, _clock, _repo, _settings = _build_app()
    async with app.run_test() as pilot:
        await pilot.press("c")  # code
        await pilot.pause()
        practice = app.screen
        assert isinstance(practice, PracticeScreen)
        assert practice._mode is Mode.CODE
        assert practice._session.focus_key is not None
        assert practice._target_text in FakeCodeSnippetProvider().snippets()
