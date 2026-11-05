"""The dev-only replay script: pure counting, the replay loop, and the CLI on
a temporary data directory. The script is loaded by path (`scripts/` is not a
package)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from keystrike.domain.advice import AdvisorContext, Kind, LessonAdvice
from keystrike.domain.enums import Mode
from keystrike.domain.models import Keystroke, KeyTally, SessionResult, SessionStats
from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.raw_keystroke_store import RawKeystrokeStore
from keystrike.infrastructure.session_repo_jsonl import JsonlSessionRepository
from tests.advice_helpers import advice, rec

_SCRIPT = Path(__file__).parent.parent / "scripts" / "replay_advice.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("replay_advice", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["replay_advice"] = module
    spec.loader.exec_module(module)
    return module


replay_mod = _load()

A, S, D = ord("a"), ord("s"), ord("d")


def _ks(target: int, typed: int | None = None, t_ns: int = 0) -> Keystroke:
    typed = target if typed is None else typed
    return Keystroke(target, typed, t_ns, correct=typed == target)


def test_position_cells_count_a_stumble_once_and_skip_retries():
    # s is typed wrong twice before it is right: one position, one error
    stream = [_ks(A, t_ns=0), _ks(S, D, 100), _ks(S, A, 200), _ks(S, t_ns=300), _ks(A, t_ns=400)]
    cell = replay_mod.position_cells([stream], frozenset({A, S}))
    assert (cell.positions, cell.errors) == (3, 1)
    # only the last a is timed: the first has no keystroke before it, the s was wrong
    assert cell.timed == 1


def test_position_cells_time_is_the_gap_to_the_previous_keystroke():
    stream = [_ks(A, t_ns=0), _ks(S, t_ns=250_000_000)]
    cell = replay_mod.position_cells([stream], frozenset({S}))
    assert cell.mean_ms == pytest.approx(250.0)


def test_position_cells_ignore_other_keys_and_empty_streams():
    cell = replay_mod.position_cells([[_ks(A)], []], frozenset({S}))
    assert (cell.positions, cell.errors, cell.mean_ms) == (0, 0, 0.0)


def test_change_is_noise_below_two_standard_errors():
    big = replay_mod.Change(-0.10, 0.02)
    small = replay_mod.Change(-0.03, 0.02)
    assert not big.noise
    assert small.noise


def _header(sid: str, started: float, *, layout: str = "qwerty") -> SessionResult:
    return SessionResult(
        schema_version=5,
        session_id=sid,
        started_at=started,
        duration_ns=1,
        layout=layout,
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(A, S, D),
        focus_key=A,
        total_keystrokes=10,
        correct_keystrokes=8,
        unlocked_keys=(A, S, D),
        key_confidence={A: 1.0, S: 0.5, D: 1.0},
        target_speed_cpm=200,
        stats=SessionStats(
            keys={
                A: KeyTally(samples=20, time_ns=20 * 250_000_000, errors=4, attempts=24),
                S: KeyTally(samples=20, time_ns=20 * 250_000_000, errors=0, attempts=20),
                D: KeyTally(samples=20, time_ns=20 * 250_000_000, errors=0, attempts=20),
            }
        ),
    )


def _stream(a_errors: int, n: int = 20) -> list[Keystroke]:
    """`n` positions of a, s and d; the first `a_errors` a's are stumbled once."""
    out: list[Keystroke] = []
    t = 0
    for i in range(n):
        for target in (A, S, D):
            t += 250_000_000
            if target == A and i < a_errors:
                out.append(_ks(A, S, t))
                t += 250_000_000
            out.append(_ks(A if target == A else target, t_ns=t))
    return out


class _AdviseA:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, ctx: AdvisorContext) -> LessonAdvice:
        self.calls += 1
        return advice(rec(Kind.EMPHASIZE, A, events=5, opportunities=50))


async def test_replay_compares_advised_keys_with_the_others_before_and_after():
    # a is weak in the early sessions and fixed later; s and d never change
    errors_by_session = [8, 8, 8, 1, 1, 1]
    sessions = [_header(f"s{i}", float(i)) for i in range(6)]
    streams = {f"s{i}": _stream(n) for i, n in enumerate(errors_by_session)}
    advisor = _AdviseA()
    points, totals = await replay_mod.replay(
        sessions, streams, advisor, needs_keystrokes=False, window=10, horizon=2, min_history=3
    )
    assert advisor.calls >= 1
    assert totals.points == len(points) >= 1
    assert totals.kinds == {"emphasize": len(points)}
    assert all(p.advised == (A,) for p in points)
    assert all(set(p.others) == {S, D} for p in points)
    did = replay_mod.difference_of_differences(totals)
    assert did.value < 0  # the advised key improved, the others did not
    assert totals.others_before.errors == 0


async def test_replay_skips_what_it_cannot_compare():
    sessions = [_header(f"s{i}", float(i)) for i in range(4)]
    advisor = _AdviseA()
    points, totals = await replay_mod.replay(
        sessions, {}, advisor, needs_keystrokes=False, window=10, horizon=2, min_history=3
    )
    assert points == []
    assert totals.skipped["not enough history"] == 2
    assert totals.skipped["no raw streams before or after"] == 2


async def test_an_advisor_with_no_advised_keys_is_skipped():
    async def quiet(_ctx: AdvisorContext) -> LessonAdvice:
        return LessonAdvice(summary="On track")

    sessions = [_header(f"s{i}", float(i)) for i in range(5)]
    streams = {f"s{i}": _stream(1) for i in range(5)}
    points, totals = await replay_mod.replay(
        sessions, streams, quiet, needs_keystrokes=False, window=10, horizon=2, min_history=3
    )
    assert points == []
    assert totals.skipped["no advised keys"] == 3


async def test_ease_is_not_an_advised_key():
    async def ease_only(_ctx: AdvisorContext) -> LessonAdvice:
        return advice(rec(Kind.EASE, D, events=40, opportunities=40))

    sessions = [_header(f"s{i}", float(i)) for i in range(5)]
    streams = {f"s{i}": _stream(1) for i in range(5)}
    points, _ = await replay_mod.replay(
        sessions, streams, ease_only, needs_keystrokes=False, window=10, horizon=2, min_history=3
    )
    assert points == []


async def test_the_replay_only_gives_streams_to_advisors_that_need_them():
    seen: list[int] = []

    async def spy(ctx: AdvisorContext) -> LessonAdvice:
        seen.append(len(ctx.keystrokes))
        return LessonAdvice()

    sessions = [_header(f"s{i}", float(i)) for i in range(5)]
    streams = {f"s{i}": _stream(1) for i in range(5)}
    await replay_mod.replay(
        sessions, streams, spy, needs_keystrokes=False, window=10, horizon=2, min_history=3
    )
    await replay_mod.replay(
        sessions, streams, spy, needs_keystrokes=True, window=10, horizon=2, min_history=3
    )
    assert seen[:3] == [0, 0, 0]
    assert all(n > 0 for n in seen[3:])


def _paths(tmp_path: Path) -> Paths:
    return Paths(config_dir=tmp_path / "cfg", data_dir=tmp_path / "data", log_dir=tmp_path / "log")


def _args(paths: Paths, *extra: str) -> list[str]:
    return ["--config-dir", str(paths.config_dir), "--data-dir", str(paths.data_dir), *extra]


def _write(paths: Paths, layout: str = "qwerty") -> None:
    for d in (paths.config_dir, paths.data_dir, paths.sessions_dir, paths.cache_dir):
        d.mkdir(parents=True, exist_ok=True)
    repo = JsonlSessionRepository(paths)
    store = RawKeystrokeStore(paths.raw_keystrokes_dir)
    for i in range(8):
        header = _header(f"01ARZ3NDEKTSV4RRFFQ69G5F{i:02d}"[:26], float(i), layout=layout)
        repo.save_header(header)
        store.save(header.session_id, _stream(6 if i < 4 else 1))


def test_cli_prints_a_report_and_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    paths = _paths(tmp_path)
    _write(paths)
    before = sorted(p.name for p in tmp_path.rglob("*") if p.is_file())
    code = replay_mod.main(_args(paths, "--layout", "qwerty"))
    out = capsys.readouterr().out
    assert code == 0
    assert "Replay of 'rules' on 'qwerty'" in out
    assert "Difference of differences" in out
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == before  # read-only
    assert not paths.advice_file.exists()


def test_cli_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    paths = _paths(tmp_path)
    _write(paths)
    code = replay_mod.main(_args(paths, "--layout", "qwerty", "--json"))
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["advisor"] == "rules"
    assert "difference_of_differences" in data["runs"][0]


def test_cli_refuses_an_advisor_that_sends_data_off_the_device(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    paths = _paths(tmp_path)
    _write(paths)
    code = replay_mod.main(_args(paths, "--advisor", "llm"))
    assert code == 2
    assert "--allow-off-device" in capsys.readouterr().err


def test_cli_rejects_off_and_unknown_advisors(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    paths = _paths(tmp_path)
    _write(paths)
    for name in ("off", "ghost"):
        code = replay_mod.main(_args(paths, "--advisor", name))
        assert code == 2
    assert "No advisor to replay" in capsys.readouterr().err


async def test_the_replay_passes_the_recency_decay_to_the_context():
    seen: list[tuple[float, ...]] = []

    async def spy(ctx: AdvisorContext) -> LessonAdvice:
        seen.append(ctx.session_weights)
        return LessonAdvice()

    sessions = [_header(f"s{i}", float(i)) for i in range(5)]
    await replay_mod.replay(
        sessions,
        {},
        spy,
        needs_keystrokes=False,
        window=10,
        horizon=2,
        min_history=3,
        recency_decay=0.5,
    )
    assert seen[0] == (1.0, 0.5, 0.25)  # three sessions of history, newest first
    assert seen[-1] == (1.0, 0.5, 0.25, 0.125, 0.0625)


def test_cli_compares_several_decays(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    paths = _paths(tmp_path)
    _write(paths)
    code = replay_mod.main(_args(paths, "--layout", "qwerty", "--decay", "1.0", "0.7", "0.5"))
    out = capsys.readouterr().out
    assert code == 0
    assert "one run per recency decay" in out
    assert all(f"{d:>6.2f}" in out for d in (1.0, 0.7, 0.5))


def test_cli_json_has_one_run_per_decay(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    paths = _paths(tmp_path)
    _write(paths)
    replay_mod.main(_args(paths, "--layout", "qwerty", "--decay", "1.0", "0.5", "--json"))
    data = json.loads(capsys.readouterr().out)
    assert [run["decay"] for run in data["runs"]] == [1.0, 0.5]


def test_cli_uses_the_decay_from_the_config_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    paths = _paths(tmp_path)
    _write(paths)
    paths.advisors_file.write_text('active = "rules"\nrecency_decay = 0.6\n', encoding="utf-8")
    replay_mod.main(_args(paths, "--layout", "qwerty"))
    assert "recency decay 0.6" in capsys.readouterr().out
