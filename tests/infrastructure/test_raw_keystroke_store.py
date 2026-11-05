from __future__ import annotations

import json
from pathlib import Path

from keystrike.domain.enums import Finger, Hand
from keystrike.domain.models import Keystroke
from keystrike.infrastructure.raw_keystroke_store import RawKeystrokeStore

_KEYS = [
    Keystroke(codepoint=97, typed=97, t_ns=123_456_789, correct=True, finger=Finger.PINKY),
    Keystroke(codepoint=115, typed=100, t_ns=2**53 + 1, correct=False),
]


def test_round_trip_preserves_exact_values(tmp_path: Path):
    store = RawKeystrokeStore(tmp_path / "raw")
    store.save("sid", _KEYS)
    assert store.load(["sid"]) == {"sid": _KEYS}


def test_directory_is_created_lazily(tmp_path: Path):
    target = tmp_path / "raw"
    store = RawKeystrokeStore(target)
    assert not target.exists()
    store.save("sid", _KEYS)
    assert (target / "sid.jsonl").is_file()


def test_missing_sessions_are_skipped(tmp_path: Path):
    assert RawKeystrokeStore(tmp_path).load(["nope"]) == {}


def test_corrupt_rows_are_skipped(tmp_path: Path):
    store = RawKeystrokeStore(tmp_path)
    store.save("sid", _KEYS)
    path = tmp_path / "sid.jsonl"
    path.write_text(path.read_text() + "{broken\n" + '{"target": 1}\n', encoding="utf-8")
    assert store.load(["sid"])["sid"] == _KEYS


def test_unknown_finger_name_loads_as_none(tmp_path: Path):
    (tmp_path / "sid.jsonl").write_text(
        '{"target": 97, "typed": 97, "t_ns": 1, "correct": true, "finger": "TOE"}\n',
        encoding="utf-8",
    )
    assert RawKeystrokeStore(tmp_path).load(["sid"])["sid"][0].finger is None


def test_hand_round_trips(tmp_path: Path):
    keys = [Keystroke(97, 97, 1, correct=True, finger=Finger.PINKY, hand=Hand.L)]
    store = RawKeystrokeStore(tmp_path / "raw")
    store.save("sid", keys)
    assert store.load(["sid"]) == {"sid": keys}


def test_prune_keeps_only_listed_sessions_and_clear_removes_all(tmp_path: Path):
    store = RawKeystrokeStore(tmp_path / "raw")
    for sid in ("a", "b", "c"):
        store.save(sid, _KEYS)
    store.prune({"b"})
    assert set(store.load(["a", "b", "c"])) == {"b"}
    store.clear()
    assert store.load(["b"]) == {}
    RawKeystrokeStore(tmp_path / "missing").clear()  # no directory: no error


def test_first_line_describes_the_session_and_readers_skip_it(tmp_path: Path):
    store = RawKeystrokeStore(tmp_path)
    store.save(
        "sid", _KEYS, layout="colemak", started_at=1_700_000_000.5, ended_at=1_700_000_060.25
    )
    first = json.loads((tmp_path / "sid.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first == {
        "session_id": "sid",
        "layout": "colemak",
        "started_at": 1_700_000_000.5,
        "ended_at": 1_700_000_060.25,
    }
    assert store.load(["sid"]) == {"sid": _KEYS}  # the header is not a keystroke


def test_files_without_a_header_still_load(tmp_path: Path):
    (tmp_path / "old.jsonl").write_text(
        '{"target": 97, "typed": 97, "t_ns": 1, "correct": true}\n', encoding="utf-8"
    )
    assert len(RawKeystrokeStore(tmp_path).load(["old"])["old"]) == 1
