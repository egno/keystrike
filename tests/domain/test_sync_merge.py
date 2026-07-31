import pytest

from keystrike.domain.sync_merge import (
    SessionIndexEntry,
    decide_settings_winner,
    index_layouts,
    index_session_ids,
    plan_layouts_to_copy,
    plan_missing_sessions,
    settings_epoch_from_toml,
)

# Valid 26-character ULIDs for testing (Crockford base32 alphabet)
_VALID_ULID_A = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
_VALID_ULID_B = "01ARZ3NDEKTSV4RRFFQ69G5FBV"
_VALID_ULID_C = "01ARZ3NDEKTSV4RRFFQ69G5FCV"


def _entry(
    sid: str, started_at: float = 1_700_000_000.0, layout: str = "qwerty"
) -> SessionIndexEntry:
    return SessionIndexEntry(session_id=sid, layout=layout, started_at=started_at)


def test_index_session_ids_extracts_ids():
    entries = [_entry(_VALID_ULID_A), _entry(_VALID_ULID_B)]
    assert index_session_ids(entries) == {_VALID_ULID_A, _VALID_ULID_B}


def test_index_layouts_extracts_distinct_layouts():
    entries = [
        _entry(_VALID_ULID_A, layout="qwerty"),
        _entry(_VALID_ULID_B, layout="dvorak"),
        _entry(_VALID_ULID_C, layout="qwerty"),
    ]
    assert index_layouts(entries) == {"qwerty", "dvorak"}


def test_plan_missing_sessions_skips_ids_already_local():
    remote_entries = [_entry(_VALID_ULID_A), _entry(_VALID_ULID_B)]
    remote_lines = [f'{{"session_id": "{_VALID_ULID_A}"}}', f'{{"session_id": "{_VALID_ULID_B}"}}']

    plans = plan_missing_sessions(
        local_session_ids={_VALID_ULID_A},
        remote_entries=remote_entries,
        remote_lines=remote_lines,
    )

    assert [p.session_id for p in plans] == [_VALID_ULID_B]
    assert plans[0].index_line == f'{{"session_id": "{_VALID_ULID_B}"}}'
    assert plans[0].filename == f"{_VALID_ULID_B}.jsonl"


def test_plan_missing_sessions_derives_month_from_started_at():
    started_at = 1_700_000_000.0  # 2023-11-14 ~
    remote_entries = [_entry(_VALID_ULID_B, started_at=started_at)]
    remote_lines = ["line"]

    plans = plan_missing_sessions(
        local_session_ids=set(),
        remote_entries=remote_entries,
        remote_lines=remote_lines,
    )

    assert plans[0].month == "2023-11"


def test_plan_missing_sessions_ignores_duplicate_remote_entries():
    remote_entries = [_entry(_VALID_ULID_A), _entry(_VALID_ULID_A)]
    remote_lines = ["first", "second"]

    plans = plan_missing_sessions(
        local_session_ids=set(),
        remote_entries=remote_entries,
        remote_lines=remote_lines,
    )

    assert [p.session_id for p in plans] == [_VALID_ULID_A]
    assert plans[0].index_line == "first"


def test_settings_epoch_prefers_updated_at_field():
    raw = 'layout = "qwerty"\nupdated_at = "2024-06-01T00:00:00+00:00"\n'
    epoch = settings_epoch_from_toml(raw, mtime=0.0)
    assert epoch > 0.0
    assert epoch != 0.0


def test_settings_epoch_falls_back_to_mtime_when_no_updated_at():
    raw = 'layout = "qwerty"\n'
    assert settings_epoch_from_toml(raw, mtime=123.0) == 123.0


def test_settings_epoch_handles_naive_and_zulu_timestamps():
    naive = settings_epoch_from_toml('updated_at = "2024-01-01T00:00:00"\n', mtime=0.0)
    zulu = settings_epoch_from_toml('updated_at = "2024-01-01T00:00:00Z"\n', mtime=0.0)
    assert naive == zulu


def test_decide_settings_winner_none_when_neither_exists():
    winner = decide_settings_winner(
        local_exists=False,
        remote_exists=False,
        local_epoch=0.0,
        remote_epoch=0.0,
    )
    assert winner == "none"


def test_decide_settings_winner_local_when_remote_missing():
    winner = decide_settings_winner(
        local_exists=True,
        remote_exists=False,
        local_epoch=5.0,
        remote_epoch=0.0,
    )
    assert winner == "local"


def test_decide_settings_winner_remote_when_local_missing():
    winner = decide_settings_winner(
        local_exists=False,
        remote_exists=True,
        local_epoch=0.0,
        remote_epoch=5.0,
    )
    assert winner == "remote"


def test_decide_settings_winner_prefers_newer_epoch():
    assert (
        decide_settings_winner(
            local_exists=True,
            remote_exists=True,
            local_epoch=10.0,
            remote_epoch=20.0,
        )
        == "remote"
    )
    assert (
        decide_settings_winner(
            local_exists=True,
            remote_exists=True,
            local_epoch=20.0,
            remote_epoch=10.0,
        )
        == "local"
    )


def test_decide_settings_winner_ties_favor_local():
    winner = decide_settings_winner(
        local_exists=True,
        remote_exists=True,
        local_epoch=10.0,
        remote_epoch=10.0,
    )
    assert winner == "local"


def test_plan_layouts_to_copy_returns_names_missing_from_dest():
    missing = plan_layouts_to_copy(
        source_names={"qwerty.toml", "dvorak.toml"},
        dest_names={"qwerty.toml"},
    )
    assert missing == {"dvorak.toml"}


def test_plan_layouts_to_copy_empty_when_nothing_missing():
    missing = plan_layouts_to_copy(
        source_names={"qwerty.toml"},
        dest_names={"qwerty.toml", "dvorak.toml"},
    )
    assert missing == set()


def test_session_index_entry_rejects_path_traversal_session_id():
    """Path traversal attempts in session_id are rejected at domain layer."""
    with pytest.raises(ValueError, match="26 characters"):
        SessionIndexEntry.from_dict(
            {
                "session_id": "../../etc/passwd",
                "layout": "qwerty",
                "started_at": 1_700_000_000.0,
            }
        )


def test_session_index_entry_rejects_session_id_with_slashes():
    """Forward slashes in session_id are rejected."""
    with pytest.raises(ValueError, match="26 characters"):
        SessionIndexEntry.from_dict(
            {
                "session_id": "ABC/DEF0123456789ABCDEF",
                "layout": "qwerty",
                "started_at": 1_700_000_000.0,
            }
        )


def test_session_index_entry_rejects_session_id_wrong_length():
    """Session IDs must be exactly 26 characters (ULID length)."""
    with pytest.raises(ValueError, match="26 characters"):
        SessionIndexEntry.from_dict(
            {
                "session_id": "ABC",
                "layout": "qwerty",
                "started_at": 1_700_000_000.0,
            }
        )


def test_session_index_entry_rejects_session_id_invalid_chars():
    """Session IDs must only contain Crockford base32 alphabet."""
    with pytest.raises(ValueError, match="invalid characters"):
        SessionIndexEntry.from_dict(
            {
                "session_id": "ABC!DEF0123456789ABCDEFGHI",  # '!' is invalid, 26 chars total
                "layout": "qwerty",
                "started_at": 1_700_000_000.0,
            }
        )


def test_session_index_entry_accepts_valid_ulid():
    """Valid 26-char ULIDs with only base32 alphabet are accepted."""
    entry = SessionIndexEntry.from_dict(
        {
            "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "layout": "qwerty",
            "started_at": 1_700_000_000.0,
        }
    )
    assert entry.session_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
