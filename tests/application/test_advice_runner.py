from __future__ import annotations

import asyncio

import pytest

from keystrike.application.advice_runner import AdviceRunner
from keystrike.application.advisor_registry import AdvisorRegistry
from keystrike.application.stats_use_cases import GetHistory
from keystrike.domain.advice import (
    EMPTY_ADVICE,
    NOT_ENOUGH_DATA,
    AdvisorCapabilities,
    AdvisorConfig,
    AdvisorContext,
    AdvisorSpec,
    Kind,
    LessonAdvice,
)
from keystrike.domain.enums import Finger, Hand, Mode
from keystrike.domain.models import Bigram, Keystroke, KeyTally, SessionResult, SessionStats
from tests.advice_helpers import advice, rec
from tests.fakes import (
    FakeAdviceStore,
    FakeAdvisorConfigRepository,
    FakeKeystrokeArchive,
    FakeSessionRepository,
    FakeSettingsRepository,
)

A, S, T, D, Z = (ord(c) for c in "astdz")


def _focus(a: LessonAdvice) -> int | None:
    recs = a.of_kind(Kind.FOCUS)
    return recs[0].keys[0] if recs else None


def _session(session_id: str = "s1", started: float = 1.0) -> SessionResult:
    return SessionResult(
        schema_version=5,
        session_id=session_id,
        started_at=started,
        duration_ns=60_000_000_000,
        layout="qwerty",
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(A, S),
        focus_key=A,
        total_keystrokes=10,
        correct_keystrokes=8,
        cpm=200.0,
        unlocked_keys=(A, S, D),
        key_confidence={A: 0.9, S: 0.4},
        target_speed_cpm=300,
        stats=SessionStats(
            keys={
                A: KeyTally(samples=4, time_ns=800_000_000, errors=0, attempts=4),
                S: KeyTally(samples=3, time_ns=900_000_000, errors=3, attempts=6),
                T: KeyTally(samples=1, time_ns=100_000_000, errors=1, attempts=2),  # locked
            },
            transitions={Bigram(A, S): KeyTally(samples=2, time_ns=1, errors=2, attempts=4)},
        ),
    )


class _Advisor:
    def __init__(self, advice: LessonAdvice = EMPTY_ADVICE, error: Exception | None = None):
        self.advice = advice
        self.error = error
        self.contexts: list[AdvisorContext] = []

    async def __call__(self, ctx: AdvisorContext) -> LessonAdvice:
        self.contexts.append(ctx)
        if self.error is not None:
            raise self.error
        return self.advice


class _Gated(_Advisor):
    def __init__(self, advice: LessonAdvice) -> None:
        super().__init__(advice)
        self.gate = asyncio.Event()

    async def __call__(self, ctx: AdvisorContext) -> LessonAdvice:
        self.contexts.append(ctx)
        await self.gate.wait()
        return self.advice


def _runner(
    advisor: _Advisor | None,
    *,
    name: str = "fake",
    keystrokes: bool = False,
    sessions: list[SessionResult] | None = None,
    store: FakeAdviceStore | None = None,
    archive: FakeKeystrokeArchive | None = None,
    config: FakeAdvisorConfigRepository | None = None,
) -> AdviceRunner:
    registry = AdvisorRegistry()
    if advisor is not None:
        registry.register(
            AdvisorSpec(
                name=name,
                label="Fake",
                capabilities=AdvisorCapabilities(needs_keystrokes=keystrokes),
                settings=(),
                create=lambda _cfg: advisor,
            )
        )
    repo = FakeSessionRepository()
    for s in sessions if sessions is not None else [_session()]:
        repo.save_header(s)
    return AdviceRunner(
        registry=registry,
        config_repo=config or FakeAdvisorConfigRepository(AdvisorConfig(active=name)),
        store=store if store is not None else FakeAdviceStore(),
        archive=archive if archive is not None else FakeKeystrokeArchive(),
        history=GetHistory(repo=repo),
        settings_repo=FakeSettingsRepository(),
        wall_epoch=lambda: 123.0,
    )


async def test_request_validates_tags_and_stores_the_advice():
    advisor = _Advisor(
        LessonAdvice(
            source="forged",
            created_at=1.0,
            summary="Slow on s",
            recommendations=(
                rec(Kind.FOCUS, S),
                rec(Kind.EMPHASIZE, S),
                rec(Kind.EMPHASIZE, T),  # T is locked
                rec(Kind.EASE, D),  # D is the newest unlocked key
            ),
        )
    )
    store = FakeAdviceStore()
    runner = _runner(advisor, store=store)
    result = await runner.request("qwerty")
    assert (result.source, result.created_at) == ("fake", 123.0)  # advisors cannot forge these
    assert [(r.kind, r.keys) for r in result.recommendations] == [
        (Kind.FOCUS, (S,)),
        (Kind.EMPHASIZE, (S,)),
    ]
    assert result.recommendations[0].applied == 1.0  # the core set the effective strength
    assert store.get("qwerty", "fake") == result
    assert runner.current("qwerty") == result


async def test_context_has_digest_limited_to_unlocked_keys():
    advisor = _Advisor()
    await _runner(advisor).request("qwerty")
    ctx = advisor.contexts[0]
    assert set(ctx.digest.keys) == {A, S}  # T is locked
    assert ctx.course.unlocked == (A, S, D)
    assert ctx.keystrokes == {}  # the advisor did not ask for raw keystrokes


async def test_keystrokes_and_insights_only_for_advisors_that_need_them():
    wrong = Keystroke(S, D, 0, correct=False, finger=Finger.RING, hand=Hand.L)
    right = Keystroke(S, S, 0, correct=True, finger=Finger.RING, hand=Hand.L)
    stream = [wrong, right, Keystroke(A, A, 0, correct=True), wrong, right] * 2
    archive = FakeKeystrokeArchive()
    archive.save("s1", stream)
    advisor = _Advisor()
    await _runner(advisor, keystrokes=True, archive=archive).request("qwerty")
    ctx = advisor.contexts[0]
    assert "s1" in ctx.keystrokes
    assert ctx.insights.confusions[0].target == S

    plain = _Advisor()
    await _runner(plain, keystrokes=False, archive=archive).request("qwerty")
    assert plain.contexts[0].keystrokes == {}
    assert plain.contexts[0].insights.is_empty


async def test_exceptions_are_isolated_and_the_last_good_advice_stays():
    store = FakeAdviceStore()
    good = _Advisor(advice(rec(Kind.FOCUS, S)))
    runner = _runner(good, store=store)
    first = await runner.request("qwerty")
    good.error = ConnectionRefusedError()
    failed = await runner.request("qwerty")
    assert failed.failed
    assert "ConnectionRefusedError" in failed.error
    assert runner.current("qwerty") == first
    assert store.get("qwerty", "fake") == first


async def test_create_error_message_is_shown():
    def bad(_cfg):
        raise ValueError("model is required")

    registry = AdvisorRegistry()
    registry.register(AdvisorSpec("bad", "Bad", AdvisorCapabilities(), (), create=bad))
    runner = _runner(None)
    runner.registry = registry
    runner.config_repo = FakeAdvisorConfigRepository(AdvisorConfig(active="bad"))
    result = await runner.request("qwerty")
    assert result.error == "model is required"


async def test_no_usable_stats_is_not_a_failure_and_skips_the_advisor():
    advisor = _Advisor(advice(rec(Kind.FOCUS, S)))
    runner = _runner(advisor, sessions=[])
    result = await runner.request("qwerty")
    assert not result.failed
    assert result.summary == NOT_ENOUGH_DATA
    assert advisor.contexts == []
    assert runner.current("qwerty") == EMPTY_ADVICE


async def test_off_never_calls_anything():
    advisor = _Advisor(advice(rec(Kind.FOCUS, S)))
    runner = _runner(advisor, config=FakeAdvisorConfigRepository(AdvisorConfig(active="off")))
    assert not runner.enabled()
    assert await runner.request("qwerty") == EMPTY_ADVICE
    assert advisor.contexts == []
    assert runner.current("qwerty") == EMPTY_ADVICE


async def test_a_removed_plugin_turns_advice_off():
    runner = _runner(_Advisor(), config=FakeAdvisorConfigRepository(AdvisorConfig(active="gone")))
    assert runner.active_name() == "off"
    assert runner.current("qwerty") == EMPTY_ADVICE


async def test_advice_is_kept_per_layout_and_advisor():
    store = FakeAdviceStore()
    other = advice(rec(Kind.FOCUS, A), source="other")
    store.put("qwerty", other)
    runner = _runner(_Advisor(advice(rec(Kind.FOCUS, S))), store=store)
    assert runner.current("qwerty") == EMPTY_ADVICE  # "other" advice is not used
    await runner.request("qwerty")
    assert _focus(runner.current("qwerty")) == S
    assert runner.current("colemak") == EMPTY_ADVICE


async def test_advice_survives_a_restart_through_the_store():
    store = FakeAdviceStore()
    await _runner(_Advisor(advice(rec(Kind.FOCUS, S))), store=store).request("qwerty")
    fresh = _runner(_Advisor(), store=store)
    assert _focus(fresh.current("qwerty")) == S


async def test_forget_clears_memory_and_store():
    store = FakeAdviceStore()
    runner = _runner(_Advisor(advice(rec(Kind.FOCUS, S))), store=store)
    await runner.request("qwerty")
    runner.forget()
    assert runner.current("qwerty") == EMPTY_ADVICE
    assert store.by_key == {}


async def test_slow_advisor_is_not_cancelled_and_waiting_callers_share_one_follow_up():
    advisor = _Gated(advice(rec(Kind.FOCUS, S)))
    runner = _runner(advisor)
    waiters = [asyncio.create_task(runner.request("qwerty")) for _ in range(4)]
    await asyncio.sleep(0.05)
    # a caller that stops waiting must not cancel the request
    impatient = asyncio.create_task(runner.request("qwerty"))
    done, _ = await asyncio.wait({impatient}, timeout=0.01)
    assert not done
    assert len(advisor.contexts) == 1  # one request in flight, the rest queued
    advisor.gate.set()
    results = await asyncio.gather(*waiters, impatient)
    assert len(advisor.contexts) == 2  # the first one finished, plus one follow-up
    assert all(_focus(r) == S for r in results)


async def test_a_fast_advisor_finishes_inside_the_budget_and_a_slow_one_does_not():
    fast = _runner(_Advisor(advice(rec(Kind.FOCUS, S))))
    task = asyncio.create_task(fast.request("qwerty"))
    done, _ = await asyncio.wait({task}, timeout=fast.budget_s)
    assert done
    assert _focus(fast.current("qwerty")) == S

    slow_advisor = _Gated(advice(rec(Kind.FOCUS, S)))
    slow = _runner(slow_advisor)
    task = asyncio.create_task(slow.request("qwerty"))
    done, _ = await asyncio.wait({task}, timeout=slow.budget_s)
    assert not done
    assert slow.current("qwerty") == EMPTY_ADVICE  # the next lesson uses the previous advice
    slow_advisor.gate.set()
    await task
    assert _focus(slow.current("qwerty")) == S  # and the lesson after uses the new one


@pytest.mark.parametrize("needs", [True, False])
def test_capabilities_follow_the_active_advisor(needs: bool):
    runner = _runner(_Advisor(), keystrokes=needs)
    assert runner.capabilities().needs_keystrokes is needs


async def test_the_runner_builds_the_context_with_the_decay_from_the_config():
    advisor = _Advisor()
    config = FakeAdvisorConfigRepository(AdvisorConfig(active="fake", recency_decay=0.5))
    sessions = [_session("a", 2.0), _session("b", 1.0), _session("c", 0.5)]
    await _runner(advisor, config=config, sessions=sessions).request("qwerty")
    assert advisor.contexts[0].session_weights == (1.0, 0.5, 0.25)
    assert advisor.contexts[0].digest.recent  # the recency-weighted tallies are there


async def test_a_decay_of_one_gives_equal_weights():
    advisor = _Advisor()
    config = FakeAdvisorConfigRepository(AdvisorConfig(active="fake", recency_decay=1.0))
    sessions = [_session("a", 2.0), _session("b", 1.0)]
    await _runner(advisor, config=config, sessions=sessions).request("qwerty")
    assert advisor.contexts[0].session_weights == (1.0, 1.0)


def test_label_is_the_display_name_of_the_advisor():
    runner = _runner(_Advisor())
    assert runner.label() == "Fake"  # the active advisor
    assert runner.label("fake") == "Fake"
    assert runner.label("off") == "Off"
    assert runner.label("removed-plugin") == "removed-plugin"  # no longer registered: as it is


def test_label_follows_a_switch_to_off():
    runner = _runner(_Advisor(), config=FakeAdvisorConfigRepository(AdvisorConfig(active="off")))
    assert runner.label() == "Off"
