"""LLM advisor plugin for keystrike. Registered through the
`keystrike.advisors` entry point; imports only `keystrike.plugin_api`."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

from keystrike.plugin_api import (
    Advisor,
    AdvisorCapabilities,
    AdvisorContext,
    AdvisorRegistry,
    AdvisorSpec,
    LessonAdvice,
    SettingField,
)

from .clients import (
    API_KEY_ENV,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    PROVIDERS,
    ChatClient,
    make_chat_client,
)
from .prompt import RESPONSE_SCHEMA, SYSTEM_PROMPT, build_user_prompt, parse_response

API_VERSION = 2

NAME = "llm"
DEFAULT_MODEL = "llama3.2"
DEFAULT_ENDPOINTS = {
    PROVIDER_OLLAMA: "http://localhost:11434",
    PROVIDER_OPENAI: "http://localhost:8080/v1",
}


def llm_advisor(client: ChatClient) -> Advisor:
    """An advisor around a chat client (a closure: no base class)."""

    async def advise(ctx: AdvisorContext) -> LessonAdvice:
        raw = await client.chat(SYSTEM_PROMPT, build_user_prompt(ctx), schema=RESPONSE_SCHEMA)
        return parse_response(raw, ctx)

    return advise


def create_llm_advisor(cfg: Mapping[str, str]) -> Advisor:
    provider = cfg.get("provider", PROVIDER_OLLAMA).strip()
    model = cfg.get("model", DEFAULT_MODEL).strip()
    endpoint = cfg.get("endpoint", "").strip() or DEFAULT_ENDPOINTS.get(provider, "")
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown LLM provider {provider!r}.")
    if not model:
        raise ValueError("LLM model is required.")
    parsed = urlparse(endpoint)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("LLM endpoint must be an http(s) URL.")
    return llm_advisor(make_chat_client(provider, endpoint, model))


SPEC = AdvisorSpec(
    name=NAME,
    label="LLM (Ollama / OpenAI-compatible)",
    capabilities=AdvisorCapabilities(needs_keystrokes=True, sends_data_off_device=True),
    settings=(
        SettingField("provider", "Provider", PROVIDER_OLLAMA, choices=PROVIDERS),
        SettingField("model", "Model", DEFAULT_MODEL),
        SettingField(
            "endpoint",
            "Endpoint",
            DEFAULT_ENDPOINTS[PROVIDER_OLLAMA],
            env_hint=API_KEY_ENV,
        ),
    ),
    create=create_llm_advisor,
)


def register(registry: AdvisorRegistry) -> None:
    registry.register(SPEC)
