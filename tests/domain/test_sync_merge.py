from keystrike.domain.sync_merge import (
    decide_settings_winner,
    index_layouts,
    index_session_ids,
    plan_layouts_to_copy,
    plan_missing_sessions,
    settings_epoch_from_toml,
)


def _entry(
    sid: str, started_at: float = 1_700_000_000.0, layout: str = "qwerty"
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": sid,
        "started_at": started_at,
        "duration_ns": 1,
        "layout": layout,
        "mode": "adaptive",
        "lesson_alphabet": [97],
        "focus_key": None,
        "total_keystrokes": 1,
        "correct_keystrokes": 1,
    }


def test_index_session_ids_extracts_ids():
    entries = [_entry("A"), _entry("B")]
    assert index_session_ids(entries) == {"A", "B"}


def test_index_layouts_extracts_distinct_layouts():
    entries = [
        _entry("A", layout="qwerty"),
        _entry("B", layout="dvorak"),
        _entry("C", layout="qwerty"),
    ]
    assert index_layouts(entries) == {"qwerty", "dvorak"}


def test_plan_missing_sessions_skips_ids_already_local():
    remote_entries = [_entry("A"), _entry("B")]
    remote_lines = ['{"session_id": "A"}', '{"session_id": "B"}']

    plans = plan_missing_sessions(
        local_session_ids={"A"},
        remote_entries=remote_entries,
        remote_lines=remote_lines,
    )

    assert [p.session_id for p in plans] == ["B"]
    assert plans[0].index_line == '{"session_id": "B"}'
    assert plans[0].filename == "B.jsonl"


def test_plan_missing_sessions_derives_month_from_started_at():
    started_at = 1_700_000_000.0  # 2023-11-14 ~
    remote_entries = [_entry("B", started_at=started_at)]
    remote_lines = ["line"]

    plans = plan_missing_sessions(
        local_session_ids=set(),
        remote_entries=remote_entries,
        remote_lines=remote_lines,
    )

    assert plans[0].month == "2023-11"


def test_plan_missing_sessions_ignores_duplicate_remote_entries():
    remote_entries = [_entry("A"), _entry("A")]
    remote_lines = ["first", "second"]

    plans = plan_missing_sessions(
        local_session_ids=set(),
        remote_entries=remote_entries,
        remote_lines=remote_lines,
    )

    assert [p.session_id for p in plans] == ["A"]
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
