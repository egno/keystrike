from random import Random

from keystrike.application.build_lesson import BuildCodeLesson, BuildLesson
from keystrike.application.learn_budget_use_cases import GetDailyLearnBudget
from keystrike.application.prepare_practice import PreparePracticeSession
from keystrike.domain.enums import Mode, PracticeSource
from keystrike.domain.models import SessionResult, Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeCodeSnippetProvider,
    FakeFreeformTextProvider,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
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
            rng=Random(0),
        ),
        build_code_lesson=BuildCodeLesson(
            layout_repo=layout_repo,
            aggregates_cache=cache,
            settings_repo=settings_repo,
            code_provider=FakeCodeSnippetProvider(),
            rng=Random(0),
        ),
        freeform_provider=FakeFreeformTextProvider(text_by_path={"/tmp/x.txt": "custom text"}),
        get_daily_learn_budget=get_daily_learn_budget,
        sample_text="sample paragraph",
    )


def test_prepare_sample_uses_sample_text():
    prep = _prepare()(
        PracticeSource.SAMPLE,
    )
    assert prep is not None
    assert prep.target_text == "sample paragraph"
    assert prep.mode is Mode.FREE
    assert prep.focus_key is None


def test_prepare_adaptive_builds_lesson():
    prep = _prepare()(PracticeSource.ADAPTIVE)
    assert prep is not None
    assert prep.mode is Mode.ADAPTIVE
    assert prep.focus_key is not None
    assert prep.layout_obj is not None
    assert prep.lesson_heatmap is not None


def test_prepare_code_builds_snippet():
    prep = _prepare()(PracticeSource.CODE)
    assert prep is not None
    assert prep.mode is Mode.CODE
    assert prep.focus_key is not None


def test_prepare_free_uses_freeform_path_when_set():
    prepare = _prepare(settings=Settings(freeform_path="/tmp/x.txt"))
    prep = prepare(PracticeSource.FREE)
    assert prep is not None
    assert prep.target_text == "custom text"


def test_prepare_adaptive_returns_none_when_daily_limit_reached():
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
            rng=Random(0),
        ),
        build_code_lesson=BuildCodeLesson(
            layout_repo=layout_repo,
            aggregates_cache=cache,
            settings_repo=settings_repo,
            code_provider=FakeCodeSnippetProvider(),
            rng=Random(0),
        ),
        freeform_provider=FakeFreeformTextProvider(),
        get_daily_learn_budget=GetDailyLearnBudget(
            clock=clock, repo=session_repo, settings_repo=settings_repo,
        ),
        sample_text="sample",
    )
    assert prepare(PracticeSource.ADAPTIVE) is None
