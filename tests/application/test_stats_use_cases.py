from keystrike.application.stats_use_cases import (
    GetAggregateMetricTrends,
    GetHeatmap,
    GetHistory,
    GetKeyMetricTrends,
    GetOrRebuildAggregates,
    RebuildAggregates,
)
from keystrike.domain.aggregate import session_recency_weights
from keystrike.domain.confidence import (
    CONFIDENCE_SESSION_WINDOW,
    MIN_CONFIDENCE_ATTEMPTS,
    SESSION_RECENCY_DECAY,
)
from keystrike.domain.enums import Mode
from keystrike.domain.models import (
    Bigram,
    KeyStats,
    Keystroke,
    LayoutAggregates,
    SessionResult,
    Settings,
    TransitionStats,
)
from tests.fakes import (
    FakeAggregatesCache,
    FakeClock,
    FakeSessionRepository,
    FakeSettingsRepository,
)


def _header(session_id: str, started_at: float, layout: str = "qwerty") -> SessionResult:
    return SessionResult(
        schema_version=1,
        session_id=session_id,
        started_at=started_at,
        duration_ns=1_000_000_000,
        layout=layout,
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(ord("a"), ord("b")),
        focus_key=None,
        total_keystrokes=2,
        correct_keystrokes=2,
    )


def test_rebuild_aggregates_uses_confidence_session_window():
    repo = FakeSessionRepository()
    cache = FakeAggregatesCache()

    h1 = _header("s1", 1_700_000_000.0)
    repo.save_header(h1)
    repo.keystrokes["s1"] = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=100_000_000, correct=True),
    ]
    h2 = _header("s2", 1_700_000_100.0)
    repo.save_header(h2)
    repo.keystrokes["s2"] = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=200_000_000, correct=True),
    ]
    # Different layout — must not be mixed in.
    other = _header("s3", 1_700_000_200.0, layout="dvorak")
    repo.save_header(other)
    repo.keystrokes["s3"] = [
        Keystroke(codepoint=ord("z"), typed=ord("z"), t_ns=0, correct=True),
    ]

    rebuild = RebuildAggregates(repo=repo, cache=cache, settings_repo=FakeSettingsRepository())
    assert rebuild("qwerty") is None

    cached = cache.get("qwerty")
    assert cached is not None
    assert set(cached.keys) == {ord("a")}
    assert cached.keys[ord("a")].samples == 2
    assert cache.get("dvorak") is None


def test_rebuild_aggregates_populates_transitions():
    repo = FakeSessionRepository()
    cache = FakeAggregatesCache()
    repo.save_header(_header("s1", 1_700_000_000.0))
    repo.keystrokes["s1"] = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100_000_000, correct=True),
    ]

    RebuildAggregates(
        repo=repo,
        cache=cache,
        settings_repo=FakeSettingsRepository(),
    )("qwerty")

    cached = cache.get("qwerty")
    assert cached is not None
    ab = cached.transitions.get(Bigram(ord("a"), ord("b")))
    assert ab is not None
    assert ab.samples == 1
    assert ab.mean_time_ns == 100_000_000.0


def test_rebuild_aggregates_excludes_same_key_transitions():
    repo = FakeSessionRepository()
    cache = FakeAggregatesCache()
    repo.save_header(_header("s1", 1_700_000_000.0))
    repo.keystrokes["s1"] = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=100_000_000, correct=True),
        Keystroke(codepoint=ord("e"), typed=ord("e"), t_ns=200_000_000, correct=True),
        Keystroke(codepoint=ord("e"), typed=ord("e"), t_ns=300_000_000, correct=True),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=400_000_000, correct=True),
    ]

    RebuildAggregates(
        repo=repo,
        cache=cache,
        settings_repo=FakeSettingsRepository(),
    )("qwerty")

    cached = cache.get("qwerty")
    assert cached is not None
    assert Bigram(ord("a"), ord("a")) not in cached.transitions
    assert Bigram(ord("e"), ord("e")) not in cached.transitions
    assert cached.transitions.get(Bigram(ord("a"), ord("e"))) is not None
    assert cached.transitions.get(Bigram(ord("e"), ord("b"))) is not None


def test_ensure_skips_when_cache_has_transitions():
    repo = FakeSessionRepository()
    cache = FakeAggregatesCache(
        by_layout={
            "qwerty": LayoutAggregates(
                keys={ord("a"): KeyStats(ord("a"), 1, 100_000_000.0, 0, 1.0, attempt_count=1)},
                transitions={
                    Bigram(ord("a"), ord("b")): TransitionStats(
                        ord("a"),
                        ord("b"),
                        1,
                        100_000_000.0,
                        0,
                        1.0,
                        attempt_count=1,
                    ),
                },
            ),
        },
    )
    rebuild = RebuildAggregates(
        repo=repo,
        cache=cache,
        settings_repo=FakeSettingsRepository(),
    )
    ensure = GetOrRebuildAggregates(repo=repo, cache=cache, rebuild=rebuild)

    keys = ensure("qwerty")

    cached = cache.get("qwerty")
    assert cached is not None
    assert keys == cached.keys
    assert cached.transitions


def test_ensure_rebuilds_when_transitions_missing_but_sessions_exist():
    repo = FakeSessionRepository()
    cache = FakeAggregatesCache(
        by_layout={
            "qwerty": LayoutAggregates(
                keys={ord("a"): KeyStats(ord("a"), 1, 100_000_000.0, 0, 1.0, attempt_count=1)},
                transitions={},
            ),
        },
    )
    repo.save_header(_header("s1", 1_700_000_000.0))
    repo.keystrokes["s1"] = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100_000_000, correct=True),
    ]
    rebuild = RebuildAggregates(
        repo=repo,
        cache=cache,
        settings_repo=FakeSettingsRepository(),
    )
    ensure = GetOrRebuildAggregates(repo=repo, cache=cache, rebuild=rebuild)

    ensure("qwerty")

    cached = cache.get("qwerty")
    assert cached is not None
    assert cached.transitions.get(Bigram(ord("a"), ord("b"))) is not None


def test_rebuild_aggregates_drops_sessions_outside_window():
    repo = FakeSessionRepository()
    cache = FakeAggregatesCache()

    for i in range(CONFIDENCE_SESSION_WINDOW + 1):
        session_id = f"s{i}"
        repo.save_header(_header(session_id, started_at=float(i)))
        repo.keystrokes[session_id] = [
            Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
            Keystroke(
                codepoint=ord("a"),
                typed=ord("a"),
                t_ns=(100 + i * 10) * 1_000_000,
                correct=True,
            ),
        ]
    # Only session 0 typed "z" — outside the window once s{N} exists.
    repo.keystrokes["s0"].append(
        Keystroke(codepoint=ord("z"), typed=ord("z"), t_ns=300_000_000, correct=True),
    )

    RebuildAggregates(
        repo=repo,
        cache=cache,
        settings_repo=FakeSettingsRepository(),
    )("qwerty")
    cached = cache.get("qwerty")
    assert cached is not None
    result = cached.keys

    assert ord("a") in result
    assert ord("z") not in result
    weights = session_recency_weights(CONFIDENCE_SESSION_WINDOW, decay=SESSION_RECENCY_DECAY)
    assert result[ord("a")].attempt_count == round(2 * sum(weights))


def test_rebuild_aggregates_respects_settings_window():
    repo = FakeSessionRepository()
    cache = FakeAggregatesCache()
    window = 3
    settings_repo = FakeSettingsRepository(Settings(confidence_session_window=window))

    for i in range(window + 2):
        session_id = f"s{i}"
        repo.save_header(_header(session_id, started_at=float(i)))
        repo.keystrokes[session_id] = [
            Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
            Keystroke(
                codepoint=ord("a"),
                typed=ord("a"),
                t_ns=100_000_000,
                correct=True,
            ),
        ]
    repo.keystrokes["s0"].append(
        Keystroke(codepoint=ord("z"), typed=ord("z"), t_ns=100_000_000, correct=True),
    )

    RebuildAggregates(repo=repo, cache=cache, settings_repo=settings_repo)("qwerty")
    cached = cache.get("qwerty")
    assert cached is not None
    result = cached.keys

    assert ord("z") not in result
    weights = session_recency_weights(window, decay=SESSION_RECENCY_DECAY)
    assert result[ord("a")].attempt_count == round(2 * sum(weights))


def test_get_heatmap_empty_cache_returns_empty_view():
    cache = FakeAggregatesCache()
    settings_repo = FakeSettingsRepository()
    get_heatmap = GetHeatmap(cache=cache, settings_repo=settings_repo, clock=FakeClock())
    view = get_heatmap("qwerty")
    assert view.confidence == {}
    assert view.urgency == {}


def test_get_heatmap_confidence_ratio():
    cache = FakeAggregatesCache()
    settings_repo = FakeSettingsRepository(Settings(target_speed_cpm=300))
    repo = FakeSessionRepository()
    now = 1_700_000_000.0
    header = _header("s1", now)
    repo.save_header(header)
    repo.keystrokes["s1"] = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        *[
            Keystroke(
                codepoint=ord("a"),
                typed=ord("a"),
                t_ns=i * 200_000_000,
                correct=True,
            )
            for i in range(1, MIN_CONFIDENCE_ATTEMPTS)
        ],
    ]
    RebuildAggregates(
        repo=repo,
        cache=cache,
        settings_repo=FakeSettingsRepository(),
    )("qwerty")

    get_heatmap = GetHeatmap(cache=cache, settings_repo=settings_repo, clock=FakeClock(wall=now))
    view = get_heatmap("qwerty")

    # target_ms_per_char = 60000/300 = 200ms; mean_time = 200ms → confidence == 1.0
    assert view.confidence[ord("a")] == 1.0
    assert view.urgency[ord("a")] == 0.0


def test_get_heatmap_urgency_from_last_seen():
    cache = FakeAggregatesCache()
    settings_repo = FakeSettingsRepository(Settings(target_speed_cpm=300))
    now = 1_000_000.0
    cache.put(
        "qwerty",
        LayoutAggregates(
            keys={
                ord("a"): KeyStats(
                    codepoint=ord("a"),
                    samples=10,
                    mean_time_ns=200_000_000.0,
                    error_count=0,
                    last_seen=now - 3 * 86_400.0,
                ),
            },
        ),
    )

    view = GetHeatmap(cache=cache, settings_repo=settings_repo, clock=FakeClock(wall=now))("qwerty")

    assert view.urgency[ord("a")] == 1.0


def test_get_history_sorted_newest_first_and_limited():
    repo = FakeSessionRepository()
    for i in range(5):
        repo.save_header(_header(f"s{i}", started_at=float(i)))

    get_history = GetHistory(repo=repo)
    history = get_history("qwerty", limit=3)

    assert [h.session_id for h in history] == ["s4", "s3", "s2"]


def test_get_key_metric_trends_tracks_speed_and_accuracy():
    repo = FakeSessionRepository()
    settings_repo = FakeSettingsRepository(Settings(target_speed_cpm=300))  # target 200ms

    repo.save_header(_header("s1", 1.0))
    repo.keystrokes["s1"] = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(
            codepoint=ord("a"),
            typed=ord("a"),
            t_ns=400_000_000,
            correct=True,
        ),
    ]
    repo.save_header(_header("s2", 2.0))
    repo.keystrokes["s2"] = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(
            codepoint=ord("a"),
            typed=ord("a"),
            t_ns=200_000_000,
            correct=True,
        ),
    ]

    get_trends = GetKeyMetricTrends(repo=repo, settings_repo=settings_repo)
    speeds, accuracies = get_trends("qwerty", ord("a"))

    assert len(speeds) == 2
    assert len(accuracies) == 2
    assert speeds[0] < speeds[1]  # 400ms then 200ms vs 200ms target
    assert accuracies == [1.0, 1.0]


def test_get_key_metric_trends_reflects_errors_in_accuracy():
    repo = FakeSessionRepository()
    settings_repo = FakeSettingsRepository(Settings(target_speed_cpm=300))

    repo.save_header(_header("s1", 1.0))
    repo.keystrokes["s1"] = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("a"), typed=ord("x"), t_ns=100_000_000, correct=False),
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=200_000_000, correct=True),
    ]

    get_trends = GetKeyMetricTrends(repo=repo, settings_repo=settings_repo)
    _, accuracies = get_trends("qwerty", ord("a"))

    assert accuracies == [0.5]


def test_get_key_metric_trends_normalizes_speed_to_current_goal():
    repo = FakeSessionRepository()
    settings_repo = FakeSettingsRepository(Settings(target_speed_cpm=600))

    header = SessionResult(
        schema_version=3,
        session_id="s1",
        started_at=1.0,
        duration_ns=1_000_000_000,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(ord("a"),),
        focus_key=None,
        total_keystrokes=2,
        correct_keystrokes=2,
        target_speed_cpm=300,
    )
    repo.save_header(header)
    repo.keystrokes["s1"] = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(
            codepoint=ord("a"),
            typed=ord("a"),
            t_ns=200_000_000,
            correct=True,
        ),
    ]

    get_trends = GetKeyMetricTrends(repo=repo, settings_repo=settings_repo)
    speeds, _ = get_trends("qwerty", ord("a"), current_target_speed_cpm=600)

    assert speeds == [0.5]  # 1.0 at 300 cpm → 0.5 at 600 cpm


def test_get_key_metric_trends_limits_to_confidence_session_window():
    window = 3
    settings_repo = FakeSettingsRepository(
        Settings(confidence_session_window=window, target_speed_cpm=300),
    )
    repo = FakeSessionRepository()

    for i in range(window + 5):
        session_id = f"s{i}"
        repo.save_header(_header(session_id, float(i)))
        repo.keystrokes[session_id] = [
            Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
            Keystroke(
                codepoint=ord("a"),
                typed=ord("a"),
                t_ns=200_000_000,
                correct=True,
            ),
        ]

    get_trends = GetKeyMetricTrends(repo=repo, settings_repo=settings_repo)
    speeds, accuracies = get_trends("qwerty", ord("a"))

    assert len(speeds) == window
    assert len(accuracies) == window


def test_get_aggregate_metric_trends_aggregates_all_keys():
    repo = FakeSessionRepository()
    settings_repo = FakeSettingsRepository(Settings(target_speed_cpm=300))

    repo.save_header(_header("s1", 1.0))
    repo.keystrokes["s1"] = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(
            codepoint=ord("a"),
            typed=ord("a"),
            t_ns=400_000_000,
            correct=True,
        ),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=500_000_000, correct=True),
        Keystroke(
            codepoint=ord("b"),
            typed=ord("x"),
            t_ns=600_000_000,
            correct=False,
        ),
    ]

    get_trends = GetAggregateMetricTrends(repo=repo, settings_repo=settings_repo)
    confidences, speeds, accuracies = get_trends("qwerty")

    assert len(confidences) == 1
    assert len(speeds) == 1
    assert len(accuracies) == 1
    assert speeds[0] > 0
    assert confidences[0] > 0
    assert accuracies == [0.67]  # 2 timing samples, 1 error across keys
