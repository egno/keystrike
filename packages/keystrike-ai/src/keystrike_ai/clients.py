"""LLM chat clients for the LLM advisor, over stdlib urllib (no extra
dependency). Each blocking request runs in a worker thread."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, Protocol, cast
from urllib.parse import urlparse

PROVIDER_OLLAMA = "ollama"
# Any server with an OpenAI-style `/chat/completions` route: llama.cpp,
# LM Studio, vLLM, Ollama's `/v1`, or a hosted API.
PROVIDER_OPENAI = "openai"
PROVIDERS = (PROVIDER_OLLAMA, PROVIDER_OPENAI)

HTTP_TIMEOUT_S = 60.0
# Low temperature: the advisor must return the same kind of JSON every time.
_TEMPERATURE = 0.2
# Read only from the environment, never from a settings file (those can be
# synced or shared).
API_KEY_ENV = "KEYSTRIKE_AI_API_KEY"
_HTTP_BAD_REQUEST = 400
_HTTP_UNPROCESSABLE = 422


class ChatClient(Protocol):
    """One request/response exchange with an LLM. `schema` is a JSON Schema
    the reply should follow; clients pass it to servers that support
    structured output and ignore it otherwise."""

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        schema: Mapping[str, Any] | None = None,
    ) -> str: ...


def _check_endpoint(endpoint: str) -> str:
    if urlparse(endpoint).scheme not in ("http", "https"):
        raise ValueError(f"AI endpoint must be an http(s) URL, got {endpoint!r}")
    return endpoint.rstrip("/")


def _post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float,
) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get(data: Any, *path: str | int) -> Any:
    node = data
    for step in path:
        if isinstance(step, int):
            if not isinstance(node, list) or len(cast("list[Any]", node)) <= step:
                return None
            node = cast("list[Any]", node)[step]
        else:
            if not isinstance(node, dict):
                return None
            node = cast("dict[str, Any]", node).get(step)
    return node


class OllamaClient:
    """Ollama `/api/chat`. Passes `schema` as `format`, so the server
    constrains the reply to it (Ollama 0.5+)."""

    def __init__(self, endpoint: str, model: str, timeout: float = HTTP_TIMEOUT_S) -> None:
        self._url = _check_endpoint(endpoint) + "/api/chat"
        self._model = model
        self._timeout = timeout

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        schema: Mapping[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": _TEMPERATURE},
        }
        if schema is not None:
            payload["format"] = dict(schema)
        return await asyncio.to_thread(self._post, payload)

    def _post(self, payload: dict[str, Any]) -> str:
        data = _post_json(self._url, payload, timeout=self._timeout)
        content = _get(data, "message", "content")
        if not isinstance(content, str):
            raise ValueError("unexpected Ollama response shape")
        return content


class OpenAiCompatibleClient:
    """`POST {endpoint}/chat/completions`, as served by llama.cpp, LM Studio,
    vLLM, Ollama's `/v1` and hosted APIs. Asks for `json_schema` structured
    output; if the server rejects that request, retries once without it."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str = "",
        timeout: float = HTTP_TIMEOUT_S,
    ) -> None:
        self._url = _check_endpoint(endpoint) + "/chat/completions"
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        schema: Mapping[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": _TEMPERATURE,
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "advice", "schema": dict(schema)},
            }
        return await asyncio.to_thread(self._post, payload)

    def _post(self, payload: dict[str, Any]) -> str:
        try:
            data = _post_json(self._url, payload, headers=self._headers, timeout=self._timeout)
        except urllib.error.HTTPError as exc:
            if "response_format" not in payload or exc.code not in (
                _HTTP_BAD_REQUEST,
                _HTTP_UNPROCESSABLE,
            ):
                raise
            # Server without structured-output support: the prompt still
            # asks for JSON, and the parser tolerates extra text.
            plain = {k: v for k, v in payload.items() if k != "response_format"}
            data = _post_json(self._url, plain, headers=self._headers, timeout=self._timeout)
        content = _get(data, "choices", 0, "message", "content")
        if not isinstance(content, str):
            raise ValueError("unexpected chat-completions response shape")
        return content


def make_chat_client(provider: str, endpoint: str, model: str) -> ChatClient:
    if provider == PROVIDER_OLLAMA:
        return OllamaClient(endpoint=endpoint, model=model)
    if provider == PROVIDER_OPENAI:
        return OpenAiCompatibleClient(
            endpoint=endpoint, model=model, api_key=os.environ.get(API_KEY_ENV, "")
        )
    raise ValueError(f"unsupported provider {provider!r}")


__all__ = [
    "API_KEY_ENV",
    "PROVIDERS",
    "ChatClient",
    "OllamaClient",
    "OpenAiCompatibleClient",
    "make_chat_client",
]
