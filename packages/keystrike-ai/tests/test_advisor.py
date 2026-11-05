from __future__ import annotations

import pytest
from chat_fakes import FakeChat

from keystrike.plugin_api import (
    PLUGIN_API_VERSION,
    AdviceDigest,
    AdvisorContext,
    AdvisorRegistry,
    CourseState,
    KeystrokeInsights,
    KeyTally,
    Kind,
)
from keystrike_ai import API_VERSION, SPEC, create_llm_advisor, llm_advisor, register
from keystrike_ai.prompt import RESPONSE_SCHEMA

A, S = ord("a"), ord("s")


def _ctx() -> AdvisorContext:
    return AdvisorContext(
        layout="qwerty",
        sessions=(),
        course=CourseState(unlocked=(A, S), target_cpm=200, confidence={}),
        digest=AdviceDigest(
            keys={
                A: KeyTally(samples=3, time_ns=9, errors=0, attempts=3),
                S: KeyTally(samples=3, time_ns=9, errors=3, attempts=6),
            }
        ),
        insights=KeystrokeInsights(),
    )


def test_plugin_declares_the_current_api_version():
    assert API_VERSION == PLUGIN_API_VERSION


def test_spec_says_it_sends_data_off_the_device():
    assert SPEC.name == "llm"
    assert SPEC.capabilities.sends_data_off_device
    assert SPEC.capabilities.needs_keystrokes
    assert [f.name for f in SPEC.settings] == ["provider", "model", "endpoint"]
    assert SPEC.settings[0].choices == ("ollama", "openai")


def test_register_adds_the_spec():
    registry = AdvisorRegistry()
    register(registry)
    assert registry.get("llm") is SPEC


async def test_advisor_asks_for_structured_output_and_parses_the_reply():
    chat = FakeChat('{"summary": "go", "focus_key": "s", "emphasis_keys": ["a", "z"]}')
    advice = await llm_advisor(chat)(_ctx())
    assert chat.schemas == [RESPONSE_SCHEMA]
    assert [(r.kind, r.keys) for r in advice.recommendations] == [
        (Kind.FOCUS, (S,)),
        (Kind.EMPHASIZE, (A,)),  # "z" is not a key it was shown
    ]


async def test_a_failing_client_raises_so_the_core_can_isolate_it():
    with pytest.raises(TimeoutError):
        await llm_advisor(FakeChat(error=TimeoutError()))(_ctx())


async def test_an_unparseable_reply_raises():
    with pytest.raises(ValueError):  # noqa: PT011
        await llm_advisor(FakeChat("no json"))(_ctx())


@pytest.mark.parametrize(
    ("cfg", "message"),
    [
        ({"provider": "mystery"}, "provider"),
        ({"provider": "ollama", "model": " "}, "model"),
        ({"provider": "ollama", "endpoint": "ftp://x"}, "endpoint"),
    ],
)
def test_create_rejects_bad_config_with_a_message(cfg: dict[str, str], message: str):
    with pytest.raises(ValueError, match=message):
        create_llm_advisor(cfg)


def test_create_uses_the_provider_default_endpoint_and_model():
    assert callable(create_llm_advisor({}))
    assert callable(create_llm_advisor({"provider": "openai"}))
