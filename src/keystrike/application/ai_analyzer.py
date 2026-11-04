"""AiAnalyzer: ask an LLM coach for suggestions based on recent sessions.

Opt-in (`Settings.ai_provider`); nothing leaves the machine unless a provider
is configured. The model answers with plain characters; this module maps them
onto codepoints and drops anything that did not appear in the sessions it was
shown, so a hallucinated reply can never steer a lesson at an unknown key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any, Protocol, cast
from urllib.parse import urlparse

from keystrike.domain.ai_models import AiAnalysis
from keystrike.domain.models import Bigram, KeyTally, SessionResult, Settings
from keystrike.domain.protocols import SettingsRepository

logger = logging.getLogger(__name__)

_MAX_SUMMARY_CHARS = 200
_MAX_KEY_LIST = 5
_PROMPT_TOP_KEYS = 8
_PROMPT_TOP_PAIRS = 5
_HTTP_TIMEOUT_S = 60.0
_PAIR_LEN = 2

_SYSTEM_PROMPT = (
    "You are a typing coach analyzing recent practice sessions. "
    "Respond with ONLY a JSON object, no markdown and no extra text:\n"
    "{\n"
    '  "summary": "one sentence of actionable feedback",\n'
    '  "focus_key": "single character, or null",\n'
    '  "focus_pair": "two characters, e.g. \\"th\\", or null",\n'
    '  "rest_keys": ["characters to practice a bit less"],\n'
    '  "emphasis_keys": ["characters to practice more next session"]\n'
    "}\n"
    "Rules:\n"
    "- Use the actual characters shown in the data, never numeric codes.\n"
    "- focus_key: the single key that needs the most work.\n"
    "- focus_pair: the key pair with the most errors, or null.\n"
    "- rest_keys and emphasis_keys: at most 5 characters each.\n"
)


class ChatClient(Protocol):
    async def chat(self, system_prompt: str, user_prompt: str) -> str: ...


ClientFactory = Callable[[Settings], ChatClient]


class OllamaClient:
    """Ollama `/api/chat` over stdlib urllib (no extra dependency); the blocking
    request runs in a worker thread."""

    def __init__(self, endpoint: str, model: str, timeout: float = _HTTP_TIMEOUT_S) -> None:
        if urlparse(endpoint).scheme not in ("http", "https"):
            raise ValueError(f"AI endpoint must be an http(s) URL, got {endpoint!r}")
        self._url = endpoint.rstrip("/") + "/api/chat"
        self._model = model
        self._timeout = timeout

    async def chat(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        }
        return await asyncio.to_thread(self._post, payload)

    def _post(self, payload: dict[str, Any]) -> str:
        request = urllib.request.Request(
            self._url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            data: Any = json.loads(response.read().decode("utf-8"))
        content: Any = None
        if isinstance(data, dict):
            message = cast("dict[str, Any]", data).get("message")
            if isinstance(message, dict):
                content = cast("dict[str, Any]", message).get("content")
        if not isinstance(content, str):
            raise ValueError("unexpected Ollama response shape")
        return content


def default_client_factory(settings: Settings) -> ChatClient:
    if settings.ai_provider == "ollama":
        return OllamaClient(endpoint=settings.ai_endpoint, model=settings.ai_model)
    raise ValueError(f"unsupported AI provider {settings.ai_provider!r}")


def _show(cp: int) -> str:
    return chr(cp)


def _merge(tallies: dict[Any, KeyTally], key: Any, tally: KeyTally) -> None:
    old = tallies.get(key)
    if old is None:
        tallies[key] = tally
        return
    tallies[key] = KeyTally(
        samples=old.samples + tally.samples,
        time_ns=old.time_ns + tally.time_ns,
        errors=old.errors + tally.errors,
        attempts=old.attempts + tally.attempts,
    )


def _visible(cp: int) -> bool:
    ch = chr(cp)
    return ch.isprintable() and not ch.isspace()


class _Digest:
    """Per-key / per-pair tallies merged across the sessions shown to the model."""

    def __init__(self, sessions: Sequence[SessionResult]) -> None:
        self.keys: dict[int, KeyTally] = {}
        self.pairs: dict[Bigram, KeyTally] = {}
        for session in sessions:
            for cp, tally in session.stats.keys.items():
                if _visible(cp):
                    _merge(self.keys, cp, tally)
            for pair, tally in session.stats.transitions.items():
                if _visible(pair.prev_cp) and _visible(pair.next_cp):
                    _merge(self.pairs, pair, tally)

    @property
    def known(self) -> frozenset[int]:
        return frozenset(self.keys)

    def is_empty(self) -> bool:
        return not self.keys


def _build_user_prompt(sessions: Sequence[SessionResult], digest: _Digest) -> str:
    lines = [f"Last {len(sessions)} session(s):"]
    for i, s in enumerate(sessions, 1):
        accuracy = s.correct_keystrokes / s.total_keystrokes if s.total_keystrokes else 0.0
        lines.append(f"- session {i}: {s.cpm:.0f} CPM, {accuracy:.0%} accuracy")

    def key_order(item: tuple[int, KeyTally]) -> tuple[int, float]:
        _, t = item
        mean_ms = t.time_ns / t.samples / 1e6 if t.samples else 0.0
        return (-t.errors, -mean_ms)

    lines.append("Keys (worst first):")
    for cp, t in sorted(digest.keys.items(), key=key_order)[:_PROMPT_TOP_KEYS]:
        mean_ms = t.time_ns / t.samples / 1e6 if t.samples else 0.0
        lines.append(
            f"- '{_show(cp)}': {t.errors} errors / {t.attempts} attempts, {mean_ms:.0f} ms"
        )
    worst_pairs = sorted(digest.pairs.items(), key=lambda kv: -kv[1].errors)[:_PROMPT_TOP_PAIRS]
    worst_pairs = [(p, t) for p, t in worst_pairs if t.errors > 0]
    if worst_pairs:
        lines.append("Key pairs with errors:")
        for pair, t in worst_pairs:
            lines.append(
                f"- '{_show(pair.prev_cp)}{_show(pair.next_cp)}': "
                f"{t.errors} errors / {t.attempts} attempts"
            )
    return "\n".join(lines)


def _as_cp(value: Any, known: frozenset[int]) -> int | None:
    if isinstance(value, str) and len(value) == 1 and ord(value) in known:
        return ord(value)
    return None


def _as_cp_list(value: Any, known: frozenset[int]) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    out: list[int] = []
    for item in cast("list[Any]", value):
        cp = _as_cp(item, known)
        if cp is not None and cp not in out:
            out.append(cp)
    return tuple(out[:_MAX_KEY_LIST])


def _as_pair(value: Any, known: frozenset[int]) -> Bigram | None:
    chars: list[Any]
    if isinstance(value, str) and len(value) == _PAIR_LEN:
        chars = list(value)
    elif isinstance(value, list) and len(cast("list[Any]", value)) == _PAIR_LEN:
        chars = list(cast("list[Any]", value))
    else:
        return None
    first, second = _as_cp(chars[0], known), _as_cp(chars[1], known)
    if first is None or second is None or first == second:
        return None
    return Bigram(first, second)


def _extract_json_object(text: str) -> Any:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start : end + 1])


def parse_response(text: str, known: frozenset[int]) -> AiAnalysis:
    """Parse a model reply. Invalid individual fields are dropped; a reply that
    is not a JSON object raises `ValueError`."""
    parsed = _extract_json_object(text)
    if not isinstance(parsed, dict):
        raise ValueError("reply is not a JSON object")
    data = cast("dict[str, Any]", parsed)
    summary: Any = data.get("summary")
    return AiAnalysis(
        summary=summary.strip()[:_MAX_SUMMARY_CHARS] if isinstance(summary, str) else "",
        focus_key=_as_cp(data.get("focus_key"), known),
        focus_pair=_as_pair(data.get("focus_pair"), known),
        rest_keys=_as_cp_list(data.get("rest_keys"), known),
        emphasis_keys=_as_cp_list(data.get("emphasis_keys"), known),
    )


class AiAnalyzer:
    """Analyzes recent session tallies and produces coaching suggestions.

    `latest` holds the most recent successful analysis; `suggestion()` is what
    `BuildLesson` reads when composing the next lesson."""

    def __init__(
        self,
        settings_repo: SettingsRepository,
        client_factory: ClientFactory = default_client_factory,
    ) -> None:
        self._settings_repo = settings_repo
        self._client_factory = client_factory
        self.latest: AiAnalysis | None = None

    def enabled(self) -> bool:
        return self._settings_repo.load().ai_enabled

    def window(self) -> int:
        return self._settings_repo.load().confidence_session_window

    def suggestion(self) -> AiAnalysis | None:
        """The latest usable analysis, or None if AI is off or nothing is ready."""
        if self.latest is None or self.latest.failed or not self.enabled():
            return None
        return self.latest

    async def analyze(self, sessions: Sequence[SessionResult]) -> AiAnalysis:
        """Analyze `sessions` (most recent first, already windowed by the caller).

        Never raises: failures come back as an `AiAnalysis` with `error` set."""
        settings = self._settings_repo.load()
        if not settings.ai_enabled:
            return AiAnalysis(error="AI analysis is disabled")
        digest = _Digest(sessions)
        if digest.is_empty():
            self.latest = None
            return AiAnalysis(summary="Not enough data yet — keep practicing.")
        try:
            client = self._client_factory(settings)
            raw = await client.chat(_SYSTEM_PROMPT, _build_user_prompt(sessions, digest))
            analysis = parse_response(raw, digest.known)
        except Exception as exc:
            logger.warning("AI analysis failed: %s", exc)
            self.latest = None
            return AiAnalysis(error=f"AI analysis unavailable ({type(exc).__name__})")
        self.latest = analysis
        return analysis


__all__ = [
    "AiAnalyzer",
    "ChatClient",
    "ClientFactory",
    "OllamaClient",
    "default_client_factory",
    "parse_response",
]
