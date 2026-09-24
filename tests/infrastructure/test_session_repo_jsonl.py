import json
from dataclasses import replace

import pytest

from keystrike.domain.enums import Mode
from keystrike.domain.models import Bigram, KeyTally, SessionResult, SessionStats
from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.session_repo_jsonl import JsonlSessionRepository

# Valid 26-character ULIDs for testing (Crockford base32 alphabet)
_VALID_ULID_A = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
_VALID_ULID_B = "01ARZ3NDEKTSV4RRFFQ69G5FBV"
_VALID_ULID_C = "01ARZ3NDEKTSV4RRFFQ69G5FCV"
_VALID_ULID_D = "01ARZ3NDEKTSV4RRFFQ69G5FDV"
_VALID_ULID_E = "01ARZ3NDEKTSV4RRFFQ69G5FEV"
_VALID_ULID_F = "01ARZ3NDEKTSV4RRFFQ69G5FFV"


@pytest.fixture
def paths(tmp_path):
    p = Paths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    for d in (p.config_dir, p.data_dir, p.log_dir, p.sessions_dir, p.cache_dir):
        d.mkdir(parents=True, exist_ok=True)
    return p


def _header(sid: str = _VALID_ULID_A, layout: str = "qwerty", started_at: float = 1_700_000_000.0):
    return SessionResult(
        schema_version=1,
        session_id=sid,
        started_at=started_at,
        duration_ns=1_000_000_000,
        layout=layout,
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(ord("a"), ord("b")),
        focus_key=None,
        total_keystrokes=2,
        correct_keystrokes=2,
    )


def _stats() -> SessionStats:
    return SessionStats(
        keys={ord("a"): KeyTally(0, 0, 0, 1), ord("b"): KeyTally(1, 100, 0, 1)},
        transitions={Bigram(ord("a"), ord("b")): KeyTally(1, 100, 0, 1)},
    )


def test_round_trip_single_session(paths):
    repo = JsonlSessionRepository(paths)
    header = replace(_header(), stats=_stats())
    repo.save_header(header)

    # Fresh repo instance — read must survive across process restart.
    repo2 = JsonlSessionRepository(paths)
    headers = list(repo2.iter_headers("qwerty"))
    assert len(headers) == 1
    assert headers[0].session_id == _VALID_ULID_A
    assert headers[0] == header
    assert headers[0].stats.keys[ord("b")] == KeyTally(1, 100, 0, 1)
    assert headers[0].stats.transitions[Bigram(ord("a"), ord("b"))] == KeyTally(1, 100, 0, 1)


def test_iter_headers_filters_by_layout(paths):
    repo = JsonlSessionRepository(paths)
    repo.save_header(_header(sid=_VALID_ULID_A, layout="qwerty"))
    repo.save_header(_header(sid=_VALID_ULID_B, layout="dvorak"))
    repo.save_header(_header(sid=_VALID_ULID_C, layout="qwerty"))

    qwerty = [h.session_id for h in JsonlSessionRepository(paths).iter_headers("qwerty")]
    assert qwerty == [_VALID_ULID_A, _VALID_ULID_C]


def test_round_trip_unlocked_keys(paths):
    repo = JsonlSessionRepository(paths)
    header = SessionResult(
        schema_version=2,
        session_id=_VALID_ULID_C,
        started_at=1_700_000_000.0,
        duration_ns=1_000_000_000,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(ord("a"),),
        focus_key=None,
        total_keystrokes=1,
        correct_keystrokes=1,
        unlocked_keys=(ord("a"), ord("s"), ord("d")),
    )
    repo.save_header(header)

    headers = list(JsonlSessionRepository(paths).iter_headers("qwerty"))
    assert headers[0].unlocked_keys == (ord("a"), ord("s"), ord("d"))


def test_round_trip_key_confidence(paths):
    repo = JsonlSessionRepository(paths)
    header = SessionResult(
        schema_version=3,
        session_id=_VALID_ULID_D,
        started_at=1_700_000_000.0,
        duration_ns=1_000_000_000,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(ord("a"),),
        focus_key=ord("a"),
        total_keystrokes=1,
        correct_keystrokes=1,
        unlocked_keys=(ord("a"), ord("s")),
        key_confidence={ord("a"): 0.85, ord("s"): 1.2},
    )
    repo.save_header(header)

    headers = list(JsonlSessionRepository(paths).iter_headers("qwerty"))
    assert headers[0].key_confidence == {ord("a"): 0.85, ord("s"): 1.2}


def test_legacy_header_without_key_confidence_defaults_empty(paths):
    repo = JsonlSessionRepository(paths)
    repo.save_header(_header())

    headers = list(JsonlSessionRepository(paths).iter_headers("qwerty"))
    assert headers[0].key_confidence == {}


def test_legacy_header_without_unlocked_keys_defaults_empty(paths):
    repo = JsonlSessionRepository(paths)
    repo.save_header(_header())

    headers = list(JsonlSessionRepository(paths).iter_headers("qwerty"))
    assert headers[0].unlocked_keys == ()


def test_legacy_header_without_target_speed_cpm_defaults_zero(paths):
    repo = JsonlSessionRepository(paths)
    repo.save_header(_header())

    headers = list(JsonlSessionRepository(paths).iter_headers("qwerty"))
    assert headers[0].target_speed_cpm == 0


def test_round_trip_target_speed_cpm(paths):
    repo = JsonlSessionRepository(paths)
    header = SessionResult(
        schema_version=3,
        session_id=_VALID_ULID_E,
        started_at=1_700_000_000.0,
        duration_ns=1_000_000_000,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(ord("a"),),
        focus_key=ord("a"),
        total_keystrokes=1,
        correct_keystrokes=1,
        target_speed_cpm=400,
    )
    repo.save_header(header)

    headers = list(JsonlSessionRepository(paths).iter_headers("qwerty"))
    assert headers[0].target_speed_cpm == 400


def test_round_trip_generated_word_bounds(paths):
    repo = JsonlSessionRepository(paths)
    header = SessionResult(
        schema_version=4,
        session_id=_VALID_ULID_F,
        started_at=1_700_000_000.0,
        duration_ns=1_000_000_000,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(ord("a"),),
        focus_key=ord("a"),
        total_keystrokes=1,
        correct_keystrokes=1,
        generated_min_len=3,
        generated_max_len=8,
    )
    repo.save_header(header)

    headers = list(JsonlSessionRepository(paths).iter_headers("qwerty"))
    assert headers[0].generated_min_len == 3
    assert headers[0].generated_max_len == 8


def test_legacy_header_without_generated_word_bounds_defaults(paths):
    repo = JsonlSessionRepository(paths)
    repo.save_header(_header())

    headers = list(JsonlSessionRepository(paths).iter_headers("qwerty"))
    assert headers[0].generated_min_len == 2
    assert headers[0].generated_max_len == 4


def test_corrupt_index_line_is_skipped_not_fatal(paths):
    repo = JsonlSessionRepository(paths)
    repo.save_header(_header(sid=_VALID_ULID_A))
    with paths.sessions_index.open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
        fh.write('{"schema_version": 1}\n')  # valid JSON, missing required fields
    repo.save_header(_header(sid=_VALID_ULID_B))

    headers = [h.session_id for h in JsonlSessionRepository(paths).iter_headers("qwerty")]
    assert headers == [_VALID_ULID_A, _VALID_ULID_B]


def test_stats_row_is_compact_positional_tallies(paths):
    repo = JsonlSessionRepository(paths)
    repo.save_header(replace(_header(sid=_VALID_ULID_B), stats=_stats()))

    row = json.loads(paths.sessions_index.read_text(encoding="utf-8").splitlines()[0])
    assert row["stats"] == {
        "keys": {"97": [0, 0, 0, 1], "98": [1, 100, 0, 1]},
        "pairs": {"97,98": [1, 100, 0, 1]},
    }


def test_empty_stats_are_omitted_from_row_and_read_back_empty(paths):
    repo = JsonlSessionRepository(paths)
    repo.save_header(_header(sid=_VALID_ULID_C))

    row = json.loads(paths.sessions_index.read_text(encoding="utf-8").splitlines()[0])
    assert "stats" not in row
    headers = list(JsonlSessionRepository(paths).iter_headers("qwerty"))
    assert headers[0].stats.is_empty


def test_legacy_row_without_stats_reads_as_empty_stats(paths):
    with paths.sessions_index.open("a", encoding="utf-8") as fh:
        fh.write(
            f'{{"schema_version": 4, "session_id": "{_VALID_ULID_D}", "layout": "qwerty", '
            '"started_at": 1700000000.0, "duration_ns": 1000000000, "mode": "adaptive", '
            '"lesson_alphabet": [], "focus_key": null, "total_keystrokes": 0, '
            '"correct_keystrokes": 0}\n'
        )
    headers = list(JsonlSessionRepository(paths).iter_headers("qwerty"))
    assert headers[0].session_id == _VALID_ULID_D
    assert headers[0].stats.is_empty


@pytest.mark.parametrize(
    "stats_json",
    [
        '{"keys": {"97": [1, 2]}}',  # tally with the wrong arity
        '{"keys": 5}',  # keys is not an object
        '{"pairs": [1, 2]}',  # pairs is not an object
        '{"pairs": {"97": [1, 1, 0, 1]}}',  # bigram key without a comma
        '"nope"',  # stats is not an object
    ],
)
def test_malformed_stats_skip_the_row_not_the_index(paths, stats_json):
    repo = JsonlSessionRepository(paths)
    repo.save_header(_header(sid=_VALID_ULID_A))
    with paths.sessions_index.open("a", encoding="utf-8") as fh:
        fh.write(
            f'{{"schema_version": 5, "session_id": "{_VALID_ULID_E}", "layout": "qwerty", '
            '"started_at": 1700000000.0, "duration_ns": 1000000000, "mode": "adaptive", '
            '"lesson_alphabet": [], "focus_key": null, "total_keystrokes": 0, '
            f'"correct_keystrokes": 0, "stats": {stats_json}}}\n'
        )
    repo.save_header(_header(sid=_VALID_ULID_B))

    headers = [h.session_id for h in JsonlSessionRepository(paths).iter_headers("qwerty")]
    assert headers == [_VALID_ULID_A, _VALID_ULID_B]


def test_replace_all_headers_rewrites_index_in_place(paths):
    repo = JsonlSessionRepository(paths)
    a = replace(_header(sid=_VALID_ULID_A, started_at=1.0), stats=_stats())
    b = replace(_header(sid=_VALID_ULID_B, started_at=2.0), stats=_stats())
    repo.save_header(a)
    repo.save_header(b)

    repo.replace_all_headers([replace(a, stats=SessionStats()), b])

    headers = list(JsonlSessionRepository(paths).iter_all_headers())
    assert [h.session_id for h in headers] == [_VALID_ULID_A, _VALID_ULID_B]
    assert headers[0].stats.is_empty
    assert headers[1] == b
    assert len(paths.sessions_index.read_text(encoding="utf-8").splitlines()) == 2


def test_path_traversal_session_id_rejected_in_header_parse(paths):
    """Regression: path-traversal session_id like '../../evil' should be rejected."""
    repo = JsonlSessionRepository(paths)
    # Write an index line with a malicious session_id
    with paths.sessions_index.open("a", encoding="utf-8") as fh:
        fh.write(
            '{"schema_version": 1, "session_id": "../../evil", "layout": "qwerty", '
            '"started_at": 1700000000.0, "duration_ns": 1000000000, "mode": "ADAPTIVE", '
            '"lesson_alphabet": [], "focus_key": null, "total_keystrokes": 0, '
            '"correct_keystrokes": 0, "lang": "en"}\n'
        )

    # The malicious line should be skipped during parsing
    headers = list(repo.iter_all_headers())
    assert len(headers) == 0


def test_invalid_chars_session_id_rejected_in_header_parse(paths):
    """Regression: session_id with invalid characters should be rejected."""
    repo = JsonlSessionRepository(paths)
    with paths.sessions_index.open("a", encoding="utf-8") as fh:
        fh.write(
            '{"schema_version": 1, "session_id": "01ARZ3NDEKTSV4RRFFQ69G5F!V", '
            '"layout": "qwerty", "started_at": 1700000000.0, "duration_ns": 1000000000, '
            '"mode": "adaptive", "lesson_alphabet": [], "focus_key": null, '
            '"total_keystrokes": 0, "correct_keystrokes": 0}\n'
        )
    assert list(repo.iter_all_headers()) == []
