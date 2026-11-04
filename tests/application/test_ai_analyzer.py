from __future__ import annotations

import pytest

from keystrike.application.ai_analyzer import (
    AiAnalyzer,
    OllamaClient,
    default_client_factory,
    parse_response,
)
from keystrike.domain.enums import Mode
from keystrike.domain.models import Bigram, KeyTally, SessionResult, SessionStats, Settings
from tests.fakes import FakeSettingsRepository

A, S, T, H = ord("a"), ord("s"), ord("t"), ord("h")
KNOWN = frozenset({A, S, T, H})


def _session(session_id: str = "s1") -> SessionResult:
    return SessionResult(
        schema_version=5,
        session_id=session_id,
        started_at=1.0,
        duration_ns=60_000_000_000,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(A, S),
        focus_key=A,
        total_keystrokes=10,
        correct_keystrokes=8,
        cpm=200.0,
        stats=SessionStats(
            keys={
                A: KeyTally(samples=4, time_ns=800_000_000, errors=0, attempts=4),
                S: KeyTally(samples=3, time_ns=900_000_000, errors=3, attempts=6),
                ord(" "): KeyTally(samples=1, time_ns=1, errors=0, attempts=1),
            },
            transitions={Bigram(A, S): KeyTally(samples=2, time_ns=1, errors=2, attempts=4)},
        ),
    )


class FakeChat:
    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.prompts: list[tuple[str, str]] = []

    async def chat(self, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append((system_prompt, user_prompt))
        if self.error is not None:
            raise self.error
        return self.reply


def _analyzer(chat: FakeChat, *, provider: str = "ollama") -> AiAnalyzer:
    repo = FakeSettingsRepository(Settings(ai_provider=provider))
    return AiAnalyzer(repo, client_factory=lambda _settings: chat)


def test_ai_is_off_by_default():
    assert Settings().ai_enabled is False
    assert AiAnalyzer(FakeSettingsRepository()).enabled() is False


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


@pytest.mark.parametrize("reply", ["", "no json here", "[1, 2]", '{"summary": ', "null"])
def test_parse_rejects_non_object_replies(reply: str):
    with pytest.raises(ValueError):  # noqa: PT011 - JSONDecodeError is a ValueError
        parse_response(reply, KNOWN)


async def test_analyze_success_sets_latest_and_suggestion():
    chat = FakeChat('{"summary": "go", "focus_key": "s"}')
    analyzer = _analyzer(chat)
    analysis = await analyzer.analyze([_session()])
    assert analysis.focus_key == S
    assert analyzer.latest is analysis
    assert analyzer.suggestion() is analysis


async def test_prompt_uses_characters_and_hides_whitespace_keys():
    chat = FakeChat("{}")
    await _analyzer(chat).analyze([_session()])
    _system, user = chat.prompts[0]
    assert "'s': 3 errors / 6 attempts" in user
    assert "'as': 2 errors / 4 attempts" in user
    assert "' '" not in user


async def test_analyze_failure_is_reported_not_raised():
    analyzer = _analyzer(FakeChat(error=ConnectionRefusedError("down")))
    analysis = await analyzer.analyze([_session()])
    assert analysis.failed
    assert "ConnectionRefusedError" in analysis.error
    assert analyzer.latest is None
    assert analyzer.suggestion() is None


async def test_analyze_unparseable_reply_is_a_failure():
    analyzer = _analyzer(FakeChat("I cannot help with that"))
    assert (await analyzer.analyze([_session()])).failed


async def test_failure_clears_previous_suggestion():
    chat = FakeChat('{"focus_key": "s"}')
    analyzer = _analyzer(chat)
    await analyzer.analyze([_session()])
    assert analyzer.suggestion() is not None
    chat.error = TimeoutError()
    await analyzer.analyze([_session()])
    assert analyzer.suggestion() is None


async def test_disabled_never_calls_the_provider():
    chat = FakeChat('{"focus_key": "s"}')
    analysis = await _analyzer(chat, provider="").analyze([_session()])
    assert analysis.failed
    assert chat.prompts == []


async def test_suggestion_hidden_once_ai_is_switched_off():
    chat = FakeChat('{"focus_key": "s"}')
    repo = FakeSettingsRepository(Settings(ai_provider="ollama"))
    analyzer = AiAnalyzer(repo, client_factory=lambda _settings: chat)
    await analyzer.analyze([_session()])
    repo.settings = Settings(ai_provider="")
    assert analyzer.suggestion() is None


async def test_no_usable_stats_is_not_a_failure_and_skips_the_provider():
    chat = FakeChat("{}")
    analysis = await _analyzer(chat).analyze([])
    assert not analysis.failed
    assert analysis.summary
    assert chat.prompts == []


async def test_unsupported_provider_degrades_gracefully():
    repo = FakeSettingsRepository(Settings(ai_provider="mystery"))
    analysis = await AiAnalyzer(repo).analyze([_session()])
    assert analysis.failed


def test_ollama_client_only_accepts_http_endpoints():
    with pytest.raises(ValueError, match="http"):
        OllamaClient("file:///etc/passwd", "m")
    OllamaClient("http://localhost:11434", "m")


def test_default_client_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="unsupported"):
        default_client_factory(Settings(ai_provider="x"))
