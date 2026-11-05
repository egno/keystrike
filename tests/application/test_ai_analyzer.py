from __future__ import annotations

from dataclasses import replace

import pytest

from keystrike.application.ai_analyzer import RESPONSE_SCHEMA, AiAnalyzer, parse_response
from keystrike.domain.ai_models import AiAnalysis, AiSettings
from keystrike.domain.enums import Finger, Hand, Mode
from keystrike.domain.models import Bigram, Keystroke, KeyTally, SessionResult, SessionStats
from tests.fakes import (
    FakeAiAnalysisStore,
    FakeAiSettingsRepository,
    FakeChat,
    FakeKeystrokeArchive,
    FakeSettingsRepository,
)

A, S, T, H, D, Z = (ord(c) for c in "asthdz")
KNOWN = frozenset({A, S, T, H})
ON = AiSettings(provider="ollama")


def _session(
    session_id: str = "s1",
    *,
    layout: str = "qwerty",
    unlocked: tuple[int, ...] = (A, S, D, Z),
) -> SessionResult:
    return SessionResult(
        schema_version=5,
        session_id=session_id,
        started_at=1.0,
        duration_ns=60_000_000_000,
        layout=layout,
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(A, S),
        focus_key=A,
        total_keystrokes=10,
        correct_keystrokes=8,
        cpm=200.0,
        unlocked_keys=unlocked,
        key_confidence={A: 0.9, S: 0.4},
        target_speed_cpm=300,
        stats=SessionStats(
            keys={
                A: KeyTally(samples=4, time_ns=800_000_000, errors=0, attempts=4),
                S: KeyTally(samples=3, time_ns=900_000_000, errors=3, attempts=6),
                T: KeyTally(samples=1, time_ns=100_000_000, errors=1, attempts=2),  # locked
                ord(" "): KeyTally(samples=1, time_ns=1, errors=0, attempts=1),
            },
            transitions={Bigram(A, S): KeyTally(samples=2, time_ns=1, errors=2, attempts=4)},
        ),
    )


def _analyzer(
    chat: FakeChat,
    *,
    ai: AiSettings = ON,
    store: FakeAiAnalysisStore | None = None,
    archive: FakeKeystrokeArchive | None = None,
) -> AiAnalyzer:
    return AiAnalyzer(
        FakeAiSettingsRepository(ai),
        FakeSettingsRepository(),
        lambda _settings: chat,
        store=store,
        archive=archive,
        wall_epoch=lambda: 123.0,
    )


def test_ai_is_off_by_default():
    assert AiSettings().enabled is False
    assert _analyzer(FakeChat(), ai=AiSettings()).enabled() is False


def test_parse_valid_reply():
    reply = (
        '{"summary": " Slow on s. ", "focus_key": "s", "focus_pair": "as",'
        ' "rest_keys": ["a"], "emphasis_keys": ["s", "t"]}'
    )
    analysis = parse_response(reply, KNOWN)
    assert analysis.summary == "Slow on s."
    assert analysis.focus_key == S
    assert analysis.focus_pair == Bigram(A, S)
    assert analysis.rest_keys == (A,)
    assert analysis.emphasis_keys == (S, T)
    assert not analysis.failed


def test_parse_tolerates_fences_and_chatter():
    reply = 'Sure!\n```json\n{"summary": "ok", "focus_key": "a"}\n```\nHope that helps.'
    assert parse_response(reply, KNOWN).focus_key == A


def test_parse_pair_as_list():
    assert parse_response('{"focus_pair": ["t", "h"]}', KNOWN).focus_pair == Bigram(T, H)


def test_parse_drops_unknown_or_malformed_fields_but_keeps_the_rest():
    reply = (
        '{"summary": 5, "focus_key": 115, "focus_pair": "aa",'
        ' "rest_keys": "abc", "emphasis_keys": ["z", "s", "s", 7, "ab"]}'
    )
    analysis = parse_response(reply, KNOWN)
    assert analysis.summary == ""
    assert analysis.focus_key is None  # integers are not accepted, only characters
    assert analysis.focus_pair is None  # same key twice
    assert analysis.rest_keys == ()
    assert analysis.emphasis_keys == (S,)  # unknown "z", duplicates and junk dropped


def test_parse_caps_list_length():
    known = frozenset(range(ord("a"), ord("a") + 10))
    reply = '{"emphasis_keys": ["a","b","c","d","e","f","g"]}'
    assert len(parse_response(reply, known).emphasis_keys) == 5


def test_parse_never_rests_a_protected_or_emphasized_key():
    reply = '{"rest_keys": ["a", "s", "t"], "emphasis_keys": ["s"]}'
    analysis = parse_response(reply, KNOWN, protected=frozenset({T}))
    assert analysis.rest_keys == (A,)
    assert analysis.emphasis_keys == (S,)


@pytest.mark.parametrize("reply", ["", "no json here", "[1, 2]", '{"summary": ', "null"])
def test_parse_rejects_non_object_replies(reply: str):
    with pytest.raises(ValueError):  # noqa: PT011 - JSONDecodeError is a ValueError
        parse_response(reply, KNOWN)


async def test_analyze_success_is_layout_bound_and_stored():
    store = FakeAiAnalysisStore()
    analyzer = _analyzer(FakeChat('{"summary": "go", "focus_key": "s"}'), store=store)
    analysis = await analyzer.analyze("qwerty", [_session()])
    assert analysis.focus_key == S
    assert (analysis.layout, analysis.created_at) == ("qwerty", 123.0)
    assert analyzer.suggestion("qwerty") == analysis
    assert analyzer.suggestion("colemak") is None
    assert store.by_layout["qwerty"] == analysis


async def test_requests_structured_output():
    chat = FakeChat("{}")
    await _analyzer(chat).analyze("qwerty", [_session()])
    assert chat.schemas == [RESPONSE_SCHEMA]


async def test_prompt_describes_course_and_hides_locked_and_whitespace_keys():
    chat = FakeChat("{}")
    await _analyzer(chat).analyze("qwerty", [_session()])
    _system, user = chat.prompts[0]
    assert "Goal: 300 CPM (200 ms per key)." in user
    assert "Unlocked keys, in learning order: a s d z" in user
    assert "Newest key (being learned now): z" in user
    assert "'s': 50% errors (3/6), 300 ms, confidence 0.40" in user
    assert "'as': 2 errors / 4 attempts" in user
    assert "'t'" not in user  # locked
    assert "' '" not in user


async def test_keys_rank_by_error_rate_not_raw_error_count():
    session = _session(unlocked=(A, S))
    stats = SessionStats(
        keys={
            A: KeyTally(samples=90, time_ns=90_000_000, errors=5, attempts=100),  # 5%
            S: KeyTally(samples=5, time_ns=5_000_000, errors=4, attempts=9),  # 44%
        }
    )
    chat = FakeChat("{}")
    await _analyzer(chat).analyze("qwerty", [replace(session, stats=stats)])
    user = chat.prompts[0][1]
    assert user.index("'s':") < user.index("'a':")


async def test_prompt_includes_mistypes_and_finger_errors_from_the_archive():
    archive = FakeKeystrokeArchive()
    wrong = Keystroke(S, D, 0, correct=False, finger=Finger.RING, hand=Hand.L)
    right = Keystroke(S, S, 1, correct=True, finger=Finger.RING, hand=Hand.L)
    archive.save("s1", [wrong, wrong, right, right])
    chat = FakeChat("{}")
    await _analyzer(chat, archive=archive).analyze("qwerty", [_session()])
    user = chat.prompts[0][1]
    assert "'s' typed as 'd': 2 times" in user
    assert "left ring finger: 50% (2/4)" in user


async def test_failure_keeps_the_previous_good_analysis():
    chat = FakeChat('{"focus_key": "s"}')
    analyzer = _analyzer(chat)
    good = await analyzer.analyze("qwerty", [_session()])
    chat.error = TimeoutError()
    failed = await analyzer.analyze("qwerty", [_session()])
    assert failed.failed
    assert "TimeoutError" in failed.error
    assert analyzer.suggestion("qwerty") == good


async def test_analyze_unparseable_reply_is_a_failure():
    analyzer = _analyzer(FakeChat("I cannot help with that"))
    assert (await analyzer.analyze("qwerty", [_session()])).failed
    assert analyzer.suggestion("qwerty") is None


async def test_suggestion_survives_a_restart_through_the_store():
    store = FakeAiAnalysisStore()
    await _analyzer(FakeChat('{"focus_key": "s"}'), store=store).analyze("qwerty", [_session()])
    fresh = _analyzer(FakeChat(), store=store)
    suggestion = fresh.suggestion("qwerty")
    assert suggestion is not None
    assert suggestion.focus_key == S


async def test_summary_only_analysis_is_shown_but_not_used_to_steer():
    analyzer = _analyzer(FakeChat('{"summary": "fine"}'))
    analysis = await analyzer.analyze("qwerty", [_session()])
    assert analysis.summary == "fine"
    assert not analysis.actionable
    assert analyzer.suggestion("qwerty") is None


async def test_disabled_never_calls_the_provider():
    chat = FakeChat('{"focus_key": "s"}')
    analysis = await _analyzer(chat, ai=AiSettings()).analyze("qwerty", [_session()])
    assert analysis.failed
    assert chat.prompts == []


async def test_suggestion_hidden_once_ai_is_switched_off_and_forget_clears_store():
    store = FakeAiAnalysisStore()
    repo = FakeAiSettingsRepository(ON)
    analyzer = AiAnalyzer(
        repo, FakeSettingsRepository(), lambda _s: FakeChat('{"focus_key": "s"}'), store=store
    )
    await analyzer.analyze("qwerty", [_session()])
    repo.settings = AiSettings()
    assert analyzer.suggestion("qwerty") is None
    analyzer.forget()
    assert store.by_layout == {}
    repo.settings = ON
    assert analyzer.suggestion("qwerty") is None


async def test_no_usable_stats_is_not_a_failure_and_skips_the_provider():
    chat = FakeChat("{}")
    analysis = await _analyzer(chat).analyze("qwerty", [])
    assert not analysis.failed
    assert analysis.summary
    assert chat.prompts == []


async def test_client_factory_error_degrades_gracefully():
    def boom(_settings: AiSettings) -> FakeChat:
        raise ValueError("unsupported AI provider 'mystery'")

    analyzer = AiAnalyzer(FakeAiSettingsRepository(ON), FakeSettingsRepository(), boom)
    assert (await analyzer.analyze("qwerty", [_session()])).failed


def test_actionable_requires_a_steering_field():
    assert not AiAnalysis(summary="x").actionable
    assert AiAnalysis(rest_keys=(A,)).actionable
    assert not AiAnalysis(focus_key=A, error="boom").actionable
