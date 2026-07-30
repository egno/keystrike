from random import Random

import pytest

from keystrike.application.build_lesson import BuildLesson
from keystrike.application.learn_budget_use_cases import GetDailyLearnBudget
from keystrike.application.prepare_practice import PreparePracticeSession
from keystrike.application.stats_use_cases import RebuildAggregates
from keystrike.domain.enums import Mode
from keystrike.domain.models import Keystroke, SessionResult, Settings
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS, CompositeLayoutRepository
from keystrike.infrastructure.paths import Paths
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeLanguageProvider,
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
    FakeWordListStore,
)


@pytest.fixture
def paths(tmp_path):
    return Paths(
        config_dir=tmp_path / "config", data_dir=tmp_path / "data", log_dir=tmp_path / "log",
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


def test_prepare_ensures_transitions_before_lesson():
    clock = FakeClock()
    session_repo = FakeSessionRepository()
    settings_repo = FakeSettingsRepository(Settings(alphabet_size=2))
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    cache = FakeAggregatesCache()
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
    rebuild = RebuildAggregates(repo=session_repo, cache=cache, settings_repo=settings_repo)
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
        rebuild_aggregates=rebuild,
    )

    prep = prepare()

    assert prep is not None
    cached = cache.get("qwerty")
    assert cached is not None
    assert cached.transitions
    assert prep.focus_reason is not None
    assert prep.focus_reason.endswith(" weak transition")


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


def test_prepare_uses_custom_toml_layout(paths):
    paths.layouts_dir.mkdir(parents=True)
    (paths.layouts_dir / "myown.toml").write_text(
        'name = "myown"\nlearn_order = "ab"\n\n'
        '[[keys]]\nchar = "a"\nrow = 1\ncol = 0\nfinger = "PINKY"\nhand = "L"\n\n'
        '[[keys]]\nchar = "b"\nrow = 1\ncol = 1\nfinger = "RING"\nhand = "L"\n',
        encoding="utf-8",
    )
    layout_repo = CompositeLayoutRepository(paths)
    settings_repo = FakeSettingsRepository(
        Settings(layout="myown", alphabet_size=2),
    )
    prepare = PreparePracticeSession(
        settings_repo=settings_repo,
        layout_repo=layout_repo,
        build_lesson=BuildLesson(
            layout_repo=layout_repo,
            aggregates_cache=FakeAggregatesCache(),
            settings_repo=settings_repo,
            language_provider=FakeLanguageProvider(),
            wordlist_store=FakeWordListStore(),
            rng=Random(0),
        ),
        get_daily_learn_budget=GetDailyLearnBudget(
            clock=FakeClock(),
            repo=FakeSessionRepository(),
            settings_repo=settings_repo,
        ),
    )

    prep = prepare()

    assert prep is not None
    assert prep.layout_obj is not None
    assert prep.layout_obj.name == "myown"
    assert prep.layout_obj.learn_order == (ord("a"), ord("b"))
    assert prep.lesson_heatmap is not None
