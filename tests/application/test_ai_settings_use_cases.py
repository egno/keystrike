from __future__ import annotations

import pytest

from keystrike.application.ai_settings_use_cases import (
    AiSettingsValidationError,
    CheckAiConnection,
    UpdateAiSettings,
)
from keystrike.domain.ai_models import AiSettings
from tests.fakes import FakeAiSettingsRepository, FakeChat, FakeKeystrokeArchive


def test_saves_trimmed_settings():
    repo = FakeAiSettingsRepository()
    UpdateAiSettings(repo=repo)(AiSettings(provider="ollama", model=" m ", endpoint=" http://h "))
    assert repo.settings == AiSettings(provider="ollama", model="m", endpoint="http://h")


@pytest.mark.parametrize(
    "settings",
    [
        AiSettings(provider="mystery"),
        AiSettings(provider="ollama", model=""),
        AiSettings(provider="ollama", endpoint="file:///etc"),
        AiSettings(provider="openai", endpoint="http://"),
    ],
)
def test_rejects_invalid_settings(settings: AiSettings):
    repo = FakeAiSettingsRepository()
    with pytest.raises(AiSettingsValidationError):
        UpdateAiSettings(repo=repo)(settings)
    assert repo.settings == AiSettings()


def test_turning_off_deletes_local_data():
    archive = FakeKeystrokeArchive()
    archive.save("s1", [])
    forgotten: list[bool] = []
    update = UpdateAiSettings(
        repo=FakeAiSettingsRepository(AiSettings(provider="ollama")),
        archive=archive,
        forget_analyses=lambda: forgotten.append(True),
    )
    update(AiSettings(provider="", endpoint="anything"))  # endpoint unchecked when off
    assert archive.saved == {}
    assert forgotten == [True]


async def test_check_connection_reports_success_and_failure():
    chat = FakeChat('{"summary": "ok"}')
    check = CheckAiConnection(client_factory=lambda _s: chat)
    assert "replied" in await check(AiSettings(provider="ollama"))
    chat.reply = "nope"
    with pytest.raises(ValueError):  # noqa: PT011
        await check(AiSettings(provider="ollama"))
    with pytest.raises(AiSettingsValidationError):
        await check(AiSettings())
