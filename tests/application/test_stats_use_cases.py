from keystrike.application.stats_use_cases import (
    GetHeatmap,
    GetHistory,
    GetLearningRate,
    RebuildAggregates,
)
from keystrike.domain.confidence import CONFIDENCE_SESSION_WINDOW, MIN_CONFIDENCE_ATTEMPTS
from keystrike.domain.enums import Mode
from keystrike.domain.models import KeyStats, Keystroke, LayoutAggregates, SessionResult, Settings
from tests.fakes import FakeAggregatesCache, FakeSessionRepository, FakeSettingsRepository


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
    result = rebuild("qwerty")

    assert set(result) == {ord("a")}
    assert result[ord("a")].samples == 2
    cached = cache.get("qwerty")
    assert cached is not None
    assert cached.keys == result
    assert cache.get("dvorak") is None


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

    result = RebuildAggregates(
        repo=repo, cache=cache, settings_repo=FakeSettingsRepository(),
    )("qwerty")

    assert ord("a") in result
    assert ord("z") not in result
    assert result[ord("a")].samples == CONFIDENCE_SESSION_WINDOW


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

    result = RebuildAggregates(repo=repo, cache=cache, settings_repo=settings_repo)("qwerty")

    assert ord("z") not in result
    assert result[ord("a")].samples == window


def test_get_heatmap_empty_cache_returns_empty_view():
    cache = FakeAggregatesCache()
    settings_repo = FakeSettingsRepository()
    get_heatmap = GetHeatmap(cache=cache, settings_repo=settings_repo)
    view = get_heatmap("qwerty")
    assert view.confidence == {}
    assert view.urgency == {}


def test_get_heatmap_confidence_ratio(monkeypatch):
    cache = FakeAggregatesCache()
    settings_repo = FakeSettingsRepository(Settings(target_speed_cpm=300))
    repo = FakeSessionRepository()
    now = 1_700_000_000.0
    monkeypatch.setattr("keystrike.application.stats_use_cases.time.time", lambda: now)
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
        repo=repo, cache=cache, settings_repo=FakeSettingsRepository(),
    )("qwerty")

    get_heatmap = GetHeatmap(cache=cache, settings_repo=settings_repo)
    view = get_heatmap("qwerty")

    # target_ms_per_char = 60000/300 = 200ms; mean_time = 200ms → confidence == 1.0
    assert view.confidence[ord("a")] == 1.0
    assert view.urgency[ord("a")] == 0.0


def test_get_heatmap_urgency_from_last_seen(monkeypatch):
    cache = FakeAggregatesCache()
    settings_repo = FakeSettingsRepository(Settings(target_speed_cpm=300))
    now = 1_000_000.0
    monkeypatch.setattr("keystrike.application.stats_use_cases.time.time", lambda: now)
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

    view = GetHeatmap(cache=cache, settings_repo=settings_repo)("qwerty")

    assert view.urgency[ord("a")] == 1.0


def test_get_learning_rate_no_data_returns_none():
    repo = FakeSessionRepository()
    settings_repo = FakeSettingsRepository()
    get_rate = GetLearningRate(repo=repo, settings_repo=settings_repo)
    assert get_rate("qwerty", ord("a")) is None


def test_get_learning_rate_reads_deltas_across_sessions_chronologically():
    repo = FakeSessionRepository()
    settings_repo = FakeSettingsRepository(Settings(target_speed_cpm=300))  # target 200ms

    for i, delta_ms in enumerate([300, 250, 210]):
        session_id = f"s{i}"
        repo.save_header(_header(session_id, started_at=float(i)))
        repo.keystrokes[session_id] = [
            Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
            Keystroke(
                codepoint=ord("a"), typed=ord("a"), t_ns=delta_ms * 1_000_000, correct=True,
            ),
        ]

    get_rate = GetLearningRate(repo=repo, settings_repo=settings_repo)
    result = get_rate("qwerty", ord("a"))

    assert result is not None
    assert result > 0


def test_get_learning_rate_already_at_target_returns_zero():
    repo = FakeSessionRepository()
    settings_repo = FakeSettingsRepository(Settings(target_speed_cpm=300))  # target 200ms

    for i, delta_ms in enumerate([200, 190]):
        session_id = f"s{i}"
        repo.save_header(_header(session_id, started_at=float(i)))
        repo.keystrokes[session_id] = [
            Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
            Keystroke(
                codepoint=ord("a"), typed=ord("a"), t_ns=delta_ms * 1_000_000, correct=True,
            ),
        ]

    get_rate = GetLearningRate(repo=repo, settings_repo=settings_repo)
    assert get_rate("qwerty", ord("a")) == 0


def test_get_history_sorted_newest_first_and_limited():
    repo = FakeSessionRepository()
    for i in range(5):
        repo.save_header(_header(f"s{i}", started_at=float(i)))

    get_history = GetHistory(repo=repo)
    history = get_history("qwerty", limit=3)

    assert [h.session_id for h in history] == ["s4", "s3", "s2"]
