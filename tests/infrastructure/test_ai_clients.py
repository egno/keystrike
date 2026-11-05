from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from keystrike.domain.ai_models import AiSettings
from keystrike.infrastructure import ai_clients
from keystrike.infrastructure.ai_clients import (
    API_KEY_ENV,
    OllamaClient,
    OpenAiCompatibleClient,
    make_chat_client,
)

SCHEMA = {"type": "object"}


class _Server:
    """Stands in for `urllib.request.urlopen`; records each request."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.requests: list[urllib.request.Request] = []

    def body(self, i: int) -> dict[str, Any]:
        data = self.requests[i].data
        assert isinstance(data, bytes)
        return json.loads(data)

    def __call__(self, request: urllib.request.Request, timeout: float) -> io.BytesIO:
        _ = timeout
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(json.dumps(reply).encode())


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "bad", {}, None)  # type: ignore[arg-type]


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    def install(*replies: Any) -> _Server:
        fake = _Server(*replies)
        monkeypatch.setattr(ai_clients.urllib.request, "urlopen", fake)
        return fake

    return install


async def test_ollama_sends_schema_as_format_and_low_temperature(server):
    srv = server({"message": {"content": "{}"}})
    reply = await OllamaClient("http://h:11434/", "m").chat("sys", "user", schema=SCHEMA)
    assert reply == "{}"
    assert srv.requests[0].full_url == "http://h:11434/api/chat"
    body = srv.body(0)
    assert body["format"] == SCHEMA
    assert body["options"]["temperature"] == pytest.approx(0.2)
    assert body["stream"] is False


async def test_ollama_rejects_unexpected_shape(server):
    server({"error": "model not found"})
    with pytest.raises(ValueError, match="shape"):
        await OllamaClient("http://h", "m").chat("s", "u")


async def test_openai_client_uses_json_schema_and_bearer_key(server):
    srv = server({"choices": [{"message": {"content": "{}"}}]})
    client = OpenAiCompatibleClient("http://h/v1", "m", api_key="k")
    assert await client.chat("s", "u", schema=SCHEMA) == "{}"
    assert srv.requests[0].full_url == "http://h/v1/chat/completions"
    assert srv.requests[0].get_header("Authorization") == "Bearer k"
    assert srv.body(0)["response_format"]["json_schema"]["schema"] == SCHEMA


async def test_openai_client_retries_without_schema_when_rejected(server):
    srv = server(_http_error(400), {"choices": [{"message": {"content": "ok"}}]})
    assert await OpenAiCompatibleClient("http://h/v1", "m").chat("s", "u", schema=SCHEMA) == "ok"
    assert "response_format" not in srv.body(1)
    assert srv.requests[0].get_header("Authorization") is None


async def test_openai_client_does_not_retry_other_errors(server):
    server(_http_error(500))
    with pytest.raises(urllib.error.HTTPError):
        await OpenAiCompatibleClient("http://h/v1", "m").chat("s", "u", schema=SCHEMA)


@pytest.mark.parametrize("cls", [OllamaClient, OpenAiCompatibleClient])
def test_clients_only_accept_http_endpoints(cls):
    with pytest.raises(ValueError, match="http"):
        cls("file:///etc/passwd", "m")


def test_factory_reads_api_key_from_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(API_KEY_ENV, "secret")
    client = make_chat_client(AiSettings(provider="openai", endpoint="http://h/v1"))
    assert isinstance(client, OpenAiCompatibleClient)
    assert isinstance(make_chat_client(AiSettings(provider="ollama")), OllamaClient)
    with pytest.raises(ValueError, match="unsupported"):
        make_chat_client(AiSettings(provider="x"))
