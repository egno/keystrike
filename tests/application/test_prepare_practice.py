from random import Random

from keystrike.application.build_lesson import BuildLesson
from keystrike.application.learn_budget_use_cases import GetDailyLearnBudget
from keystrike.application.prepare_practice import PreparePracticeSession
from keystrike.domain.enums import Mode
from keystrike.domain.models import SessionResult, Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
    FakeWordListStore,
)


def _prepare(*, settings: Settings | None = None) -> PreparePracticeSession:
    clock = FakeClock()
    session_repo = FakeSessionRepository()
    settings_repo = FakeSettingsRepository(settings or Settings())
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    cache = FakeAggregatesCache()
    get_daily_learn_budget = GetDailyLearnBudget(
        clock=clock, repo=session_repo, settings_repo=settings_repo,
    )
    return PreparePracticeSession(
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        build_lesson=BuildLesson(
            layout_repo=layout_repo,
            aggregates_cache=cache,
            settings_repo=settings_repo,
            language_provider=FakeLanguageProvider(),
            wordlist_store=FakeWordListStore(),
            rng=Random(0),
        ),
        get_daily_learn_budget=get_daily_learn_budget,
    )


def test_prepare_adaptive_builds_lesson():
    prep = _prepare()()
    assert prep is not None
    assert prep.mode is Mode.ADAPTIVE
    assert prep.focus_key is not None
    assert prep.layout_obj is not None
    assert prep.lesson_heatmap is not None


def test_prepare_adaptive_still_builds_lesson_when_daily_goal_reached():
    clock = FakeClock(wall=1_700_000_000.0)
    session_repo = FakeSessionRepository()
    settings_repo = FakeSettingsRepository(Settings(learn_daily_minutes=10))
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    cache = FakeAggregatesCache()

    session_repo.headers.append(
        SessionResult(
            schema_version=1,
            session_id="s1",
            started_at=clock.wall_epoch(),
            duration_ns=10 * 60 * 1_000_000_000,
            layout="qwerty",
            mode=Mode.ADAPTIVE,
            lesson_alphabet=(),
            focus_key=ord("e"),
            total_keystrokes=1,
            correct_keystrokes=1,
        ),
    )
    prepare = PreparePracticeSession(
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        build_lesson=BuildLesson(
            layout_repo=layout_repo,
            aggregates_cache=cache,
            settings_repo=settings_repo,
            language_provider=FakeLanguageProvider(),
            wordlist_store=FakeWordListStore(),
            rng=Random(0),
        ),
        get_daily_learn_budget=GetDailyLearnBudget(
            clock=clock, repo=session_repo, settings_repo=settings_repo,
        ),
    )
    prep = prepare()
    assert prep is not None
    assert prep.mode is Mode.ADAPTIVE
