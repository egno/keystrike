import pytest

from keystrike.domain.enums import Mode
from keystrike.domain.models import Keystroke, SessionResult
from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.session_repo_jsonl import JsonlSessionRepository, _session_file


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


def _header(sid: str = "S1", layout: str = "qwerty", started_at: float = 1_700_000_000.0):
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
    assert headers[0].session_id == "S1"

    keystrokes = list(repo2.load_keystrokes("S1"))
    assert len(keystrokes) == 2
    assert keystrokes[0].codepoint == ord("a")
    assert keystrokes[1].t_ns == 100


def test_iter_headers_filters_by_layout(paths):
    repo = JsonlSessionRepository(paths)
    repo.save_header(_header(sid="A", layout="qwerty"))
    repo.save_header(_header(sid="B", layout="dvorak"))
    repo.save_header(_header(sid="C", layout="qwerty"))

    qwerty = [h.session_id for h in JsonlSessionRepository(paths).iter_headers("qwerty")]
    assert qwerty == ["A", "C"]


def test_round_trip_unlocked_keys(paths):
    repo = JsonlSessionRepository(paths)
    header = SessionResult(
        schema_version=2,
        session_id="S3",
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
        session_id="S4",
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
        session_id="S5",
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


def test_corrupt_index_line_is_skipped_not_fatal(paths):
    repo = JsonlSessionRepository(paths)
    repo.save_header(_header(sid="A"))
    with paths.sessions_index.open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
        fh.write('{"schema_version": 1}\n')  # valid JSON, missing required fields
    repo.save_header(_header(sid="B"))

    headers = [h.session_id for h in JsonlSessionRepository(paths).iter_headers("qwerty")]
    assert headers == ["A", "B"]


def test_keystrokes_persisted_with_header_at_finish(paths):
    repo = JsonlSessionRepository(paths)
    header = _header(sid="S2")
    k = Keystroke(codepoint=ord("x"), typed=ord("x"), t_ns=0, correct=True)
    repo.append_keystroke(header.session_id, header.started_at, k)
    repo.save_header(header)

    repo2 = JsonlSessionRepository(paths)
    list(repo2.iter_headers("qwerty"))
    ks = list(repo2.load_keystrokes("S2"))
    assert len(ks) == 1


def test_append_keystrokes_bulk_writes_all_in_one_open(paths):
    repo = JsonlSessionRepository(paths)
    header = _header(sid="S3")
    keystrokes = [
        Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True),
        Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100, correct=True),
        Keystroke(codepoint=ord("c"), typed=ord("c"), t_ns=200, correct=False),
    ]
    repo.append_keystrokes(header.session_id, header.started_at, keystrokes)
    repo.save_header(header)

    repo2 = JsonlSessionRepository(paths)
    list(repo2.iter_headers("qwerty"))
    ks = list(repo2.load_keystrokes("S3"))
    assert [k.codepoint for k in ks] == [ord("a"), ord("b"), ord("c")]
    assert ks[2].correct is False


def test_corrupt_keystroke_line_is_skipped_not_fatal(paths):
    repo = JsonlSessionRepository(paths)
    header = _header(sid="S6")
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
    ks = list(repo2.load_keystrokes("S6"))
    assert [k.codepoint for k in ks] == [ord("a"), ord("b")]


def test_load_keystrokes_scan_fallback_when_sessions_dir_missing(tmp_path):
    empty_paths = Paths(
        config_dir=tmp_path / "config2",
        data_dir=tmp_path / "data2",
        log_dir=tmp_path / "logs2",
    )
    repo = JsonlSessionRepository(empty_paths)
    assert list(repo.load_keystrokes("does-not-exist")) == []
