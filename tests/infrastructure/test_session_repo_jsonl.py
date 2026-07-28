import pytest

from keystrike.domain.enums import Mode
from keystrike.domain.models import Keystroke, SessionResult
from keystrike.infrastructure.paths import Paths
from keystrike.infrastructure.session_repo_jsonl import JsonlSessionRepository


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
        mode=Mode.FREE,
        lesson_alphabet=(ord("a"), ord("b")),
        focus_key=None,
        total_keystrokes=2,
        correct_keystrokes=2,
    )


def test_round_trip_single_session(paths):
    repo = JsonlSessionRepository(paths)
    header = _header()
    repo.save_header(header)
    repo.append_keystroke(header.session_id, header.started_at,
                           Keystroke(codepoint=ord("a"), typed=ord("a"), t_ns=0, correct=True))
    repo.append_keystroke(header.session_id, header.started_at,
                           Keystroke(codepoint=ord("b"), typed=ord("b"), t_ns=100, correct=True))

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


def test_keystroke_before_header_still_recoverable(paths):
    # Real flow: append happens per keystroke (with started_at), save_header runs at end.
    repo = JsonlSessionRepository(paths)
    header = _header(sid="S2")
    repo.append_keystroke(header.session_id, header.started_at,
                           Keystroke(codepoint=ord("x"), typed=ord("x"), t_ns=0, correct=True))
    repo.save_header(header)

    repo2 = JsonlSessionRepository(paths)
    list(repo2.iter_headers("qwerty"))
    ks = list(repo2.load_keystrokes("S2"))
    assert len(ks) == 1
