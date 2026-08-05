import pytest

from keystrike.domain.enums import Mode
from keystrike.domain.models import Keystroke, SessionResult
from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.session_repo_jsonl import JsonlSessionRepository, _session_file

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


def test_round_trip_single_session(paths):
    repo = JsonlSessionRepository(paths)
    header = _header()
    repo.save_header(header)
    repo.append_keystroke(
        header.session_id,
        header.started_at,
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
    )
    repo.append_keystroke(
        header.session_id,
        header.started_at,
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100, correct=True),
    )

    # Fresh repo instance — read must survive across process restart.
    repo2 = JsonlSessionRepository(paths)
    headers = list(repo2.iter_headers("qwerty"))
    assert len(headers) == 1
    assert headers[0].session_id == _VALID_ULID_A

    keystrokes = list(repo2.load_keystrokes(_VALID_ULID_A))
    assert len(keystrokes) == 2
    assert keystrokes[0].codepoint == ord("a")
    assert keystrokes[1].t_ns == 100


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


def test_keystrokes_persisted_with_header_at_finish(paths):
    repo = JsonlSessionRepository(paths)
    header = _header(sid=_VALID_ULID_B)
    k = Keystroke(codepoint=ord("x"), typed=ord("x"), t_ns=0, correct=True)
    repo.append_keystroke(header.session_id, header.started_at, k)
    repo.save_header(header)

    repo2 = JsonlSessionRepository(paths)
    list(repo2.iter_headers("qwerty"))
    ks = list(repo2.load_keystrokes(_VALID_ULID_B))
    assert len(ks) == 1


def test_append_keystrokes_bulk_writes_all_in_one_open(paths):
    repo = JsonlSessionRepository(paths)
    header = _header(sid=_VALID_ULID_C)
    keystrokes = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100, correct=True),
        Keystroke(codepoint=ord("c"), typed=ord("c"), t_ns=200, correct=False),
    ]
    repo.append_keystrokes(header.session_id, header.started_at, keystrokes)
    repo.save_header(header)

    repo2 = JsonlSessionRepository(paths)
    list(repo2.iter_headers("qwerty"))
    ks = list(repo2.load_keystrokes(_VALID_ULID_C))
    assert [k.codepoint for k in ks] == [ord("a"), ord("b"), ord("c")]
    assert ks[2].correct is False


def test_corrupt_keystroke_line_is_skipped_not_fatal(paths):
    repo = JsonlSessionRepository(paths)
    header = _header(sid=_VALID_ULID_F)
    repo.append_keystroke(
        header.session_id,
        header.started_at,
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
    )
    with _session_file(paths, header).open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
        fh.write('{"codepoint": 1}\n')  # valid JSON, missing required fields
    repo.append_keystroke(
        header.session_id,
        header.started_at,
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100, correct=True),
    )
    repo.save_header(header)

    repo2 = JsonlSessionRepository(paths)
    ks = list(repo2.load_keystrokes(_VALID_ULID_F))
    assert [k.codepoint for k in ks] == [ord("a"), ord("b")]


def test_load_keystrokes_scan_fallback_when_sessions_dir_missing(tmp_path):
    empty_paths = Paths(
        config_dir=tmp_path / "config2",
        data_dir=tmp_path / "data2",
        log_dir=tmp_path / "logs2",
    )
    repo = JsonlSessionRepository(empty_paths)
    # Use a valid ULID that doesn't exist in the repo
    assert list(repo.load_keystrokes(_VALID_ULID_A)) == []


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


def test_path_traversal_session_id_rejected_in_append_keystrokes(paths):
    """Regression: path-traversal session_id should be rejected in append_keystrokes."""
    repo = JsonlSessionRepository(paths)
    with pytest.raises(ValueError, match=r"session_id.*26 characters"):
        repo.append_keystrokes(
            session_id="../../evil",
            started_at=1_700_000_000.0,
            keystrokes=[],
        )


def test_path_traversal_session_id_rejected_in_load_keystrokes(paths):
    """Regression: path-traversal session_id should be rejected in load_keystrokes."""
    repo = JsonlSessionRepository(paths)
    with pytest.raises(ValueError, match=r"session_id.*26 characters"):
        list(repo.load_keystrokes("../../evil"))


def test_invalid_chars_session_id_rejected_in_append_keystrokes(paths):
    """Regression: session_id with invalid characters should be rejected."""
    repo = JsonlSessionRepository(paths)
    with pytest.raises(ValueError, match="invalid characters"):
        repo.append_keystrokes(
            session_id="01ARZ3NDEKTSV4RRFFQ69G5F!V",  # '!' is not Crockford base32
            started_at=1_700_000_000.0,
            keystrokes=[],
        )
