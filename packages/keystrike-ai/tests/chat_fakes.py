from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class FakeChat:
    """Scripted ChatClient: returns `reply` (or raises `error`) and records
    every request."""

    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.prompts: list[tuple[str, str]] = []
        self.schemas: list[Mapping[str, Any] | None] = []

    @property
    def calls(self) -> int:
        return len(self.prompts)

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        schema: Mapping[str, Any] | None = None,
    ) -> str:
        self.prompts.append((system_prompt, user_prompt))
        self.schemas.append(schema)
        if self.error is not None:
            raise self.error
        return self.reply
