import pytest
from textual.app import App
from textual.widgets import Input, Select, Static

from keystrike.application.session_use_cases import GetKeystrokesPerWord
from keystrike.application.settings_use_cases import UpdateSettings
from keystrike.application.wordlist_use_cases import (
    DEFAULT_WORDLIST_URL,
    ClearWordList,
    GetWordListCacheStatus,
    ImportWordList,
)
from keystrike.domain.enums import Mode, TargetSpeedUnit
from keystrike.domain.models import SessionResult, Settings, WordGenBounds
from keystrike.infrastructure.layout_repo import BUNDLED_LAYOUTS
from keystrike.presentation.screens.settings import SettingsScreen
from keystrike.presentation.services import SettingsServices
from tests.fakes import (
    FakeLayoutRepository,
    FakeSessionRepository,
    FakeSettingsRepository,
    FakeWordListStore,
)


def _build_screen(
    *,
    wordlist_store: FakeWordListStore | None = None,
    settings: Settings | None = None,
    session_repo: FakeSessionRepository | None = None,
):
    settings_repo = FakeSettingsRepository(settings or Settings())
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    store = wordlist_store or FakeWordListStore()
    update_settings = UpdateSettings(repo=settings_repo)
    import_wordlist = ImportWordList(store=store, settings_repo=settings_repo)
    clear_wordlist = ClearWordList(settings_repo=settings_repo)
    get_wordlist_cache_status = GetWordListCacheStatus(store=store)
    screen = SettingsScreen(
        services=SettingsServices(
            settings_repo=settings_repo,
            layout_repo=layout_repo,
            update_settings=update_settings,
            import_wordlist=import_wordlist,
            clear_wordlist=clear_wordlist,
            get_wordlist_cache_status=get_wordlist_cache_status,
            get_keystrokes_per_word=GetKeystrokesPerWord(
                repo=session_repo or FakeSessionRepository()
            ),
        ),
    )
    return screen, settings_repo, store


@pytest.mark.asyncio
async def test_settings_screen_refreshes_alphabet_size_on_resume():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo, _store = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()

        settings_repo.save(Settings(alphabet_size=22))
        screen.on_screen_resume()
        await pilot.pause()

        assert app.screen.query_one("#settings-alphabet-size", Input).value == "22"


@pytest.mark.asyncio
async def test_settings_screen_refreshes_layout_select_on_resume():
    app = App()
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    settings_repo = FakeSettingsRepository(Settings())
    store = FakeWordListStore()
    screen = SettingsScreen(
        services=SettingsServices(
            settings_repo=settings_repo,
            layout_repo=layout_repo,
            update_settings=UpdateSettings(repo=settings_repo),
            import_wordlist=ImportWordList(store=store, settings_repo=settings_repo),
            clear_wordlist=ClearWordList(settings_repo=settings_repo),
            get_wordlist_cache_status=GetWordListCacheStatus(store=store),
        ),
    )
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        layout_repo.layouts["myown"] = BUNDLED_LAYOUTS["dvorak"]
        screen.on_screen_resume()
        await pilot.pause()

        layout_select = app.screen.query_one("#settings-layout", Select)
        option_values = sorted(v for _, v in layout_select._options if isinstance(v, str))
        assert "myown" in option_values


@pytest.mark.asyncio
async def test_save_persists_changes_and_pops_screen():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo, _store = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-speed-unit", Select).value = TargetSpeedUnit.CPM
        await pilot.pause()  # the unit switch converts the shown goal; overwrite it next
        app.screen.query_one("#settings-speed", Input).value = "400"
        app.screen.query_one("#settings-layout", Select).value = "dvorak"
        app.screen.query_one("#settings-alphabet-size", Input).value = "20"
        app.screen.query_one("#settings-learn-daily-minutes", Input).value = "15"
        await pilot.pause()

        await pilot.press("ctrl+s")
        await pilot.pause()

        assert settings_repo.settings.target_speed == 400
        assert settings_repo.settings.target_speed_unit == TargetSpeedUnit.CPM
        assert settings_repo.settings.layout == "dvorak"
        assert settings_repo.settings.alphabet_size == 20
        assert settings_repo.settings.learn_daily_minutes == 15
        assert settings_repo.settings.confidence_session_window == (
            Settings().confidence_session_window
        )
        assert app.screen_stack[-1] is not screen


@pytest.mark.asyncio
async def test_save_persists_custom_layout_from_dropdown():
    app = App()
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    layout_repo.layouts["myown"] = BUNDLED_LAYOUTS["dvorak"]
    settings_repo = FakeSettingsRepository(Settings())
    store = FakeWordListStore()
    screen = SettingsScreen(
        services=SettingsServices(
            settings_repo=settings_repo,
            layout_repo=layout_repo,
            update_settings=UpdateSettings(repo=settings_repo),
            import_wordlist=ImportWordList(store=store, settings_repo=settings_repo),
            clear_wordlist=ClearWordList(settings_repo=settings_repo),
            get_wordlist_cache_status=GetWordListCacheStatus(store=store),
        ),
    )
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-layout", Select).value = "myown"
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert settings_repo.settings.layout == "myown"
        assert app.screen_stack[-1] is not screen


@pytest.mark.asyncio
async def test_save_rejects_non_integer_speed():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo, _store = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-speed", Input).value = "not-a-number"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert settings_repo.settings.target_speed == Settings().target_speed
        assert app.screen_stack[-1] is screen


@pytest.mark.asyncio
async def test_save_rejects_non_positive_speed():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo, _store = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-speed", Input).value = "0"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert settings_repo.settings.target_speed == Settings().target_speed
        assert app.screen_stack[-1] is screen


@pytest.mark.asyncio
async def test_save_rejects_negative_alphabet_size():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo, _store = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-alphabet-size", Input).value = "-1"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert settings_repo.settings.alphabet_size == Settings().alphabet_size
        assert app.screen_stack[-1] is screen


@pytest.mark.asyncio
async def test_cancel_discards_changes():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo, _store = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-speed", Input).value = "999"
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert settings_repo.settings.target_speed == Settings().target_speed
        assert app.screen_stack[-1] is not screen


@pytest.mark.asyncio
async def test_save_keeps_wpm_goal_in_wpm():
    app = App()
    async with app.run_test() as pilot:
        screen, settings_repo, _store = _build_screen()
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-speed", Input).value = "80"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert settings_repo.settings.target_speed == 80
        assert settings_repo.settings.target_speed_unit == TargetSpeedUnit.WPM
        assert app.screen_stack[-1] is not screen


@pytest.mark.asyncio
async def test_loads_goal_in_its_own_unit():
    app = App()
    screen, _repo, _store = _build_screen(
        settings=Settings(target_speed=75, target_speed_unit=TargetSpeedUnit.WPM),
        session_repo=FakeSessionRepository([_measured_header(0, cpm=250.0, wpm=50.0)]),
    )
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        assert app.screen.query_one("#settings-speed", Input).value == "75"
        assert app.screen.query_one("#settings-speed-unit", Select).value == TargetSpeedUnit.WPM


@pytest.mark.asyncio
async def test_unit_switch_converts_with_typical_rate_without_sessions():
    app = App()
    screen, _repo, _store = _build_screen(
        settings=Settings(
            target_speed=60,
            target_speed_unit=TargetSpeedUnit.WPM,
            word_gen=WordGenBounds(min_len=3, max_len=10),
        ),
    )
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        unit = app.screen.query_one("#settings-speed-unit", Select)
        speed = app.screen.query_one("#settings-speed", Input)
        unit.value = TargetSpeedUnit.CPM
        await pilot.pause()
        assert speed.value == "450"  # 60 x (6.5 letters + 1 space)
        unit.value = TargetSpeedUnit.WPM
        await pilot.pause()
        assert speed.value == "60"


@pytest.mark.asyncio
async def test_unit_switch_converts_with_measured_rate():
    """With saved sessions, the WPM <-> CPM rate is their measured cpm / wpm."""
    app = App()
    screen, settings_repo, _store = _build_screen(
        settings=Settings(target_speed=60, target_speed_unit=TargetSpeedUnit.WPM),
        session_repo=FakeSessionRepository(
            [_measured_header(i, cpm=250.0, wpm=50.0) for i in range(3)]
        ),
    )
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-speed-unit", Select).value = TargetSpeedUnit.CPM
        await pilot.pause()
        assert app.screen.query_one("#settings-speed", Input).value == "300"  # 60 x 5.0

        await pilot.press("ctrl+s")
        await pilot.pause()

        assert settings_repo.settings.target_speed == 300
        assert settings_repo.settings.target_speed_unit == TargetSpeedUnit.CPM


def _measured_header(i: int, *, cpm: float, wpm: float) -> SessionResult:
    return SessionResult(
        schema_version=5,
        session_id=f"s{i}",
        started_at=float(i),
        duration_ns=60_000_000_000,
        layout=Settings().layout,
        mode=Mode.ADAPTIVE,
        lesson_alphabet=(),
        focus_key=None,
        total_keystrokes=0,
        correct_keystrokes=0,
        words_completed=10,
        cpm=cpm,
        wpm=wpm,
    )


@pytest.mark.asyncio
async def test_wordlist_url_prefills_default_when_empty():
    app = App()
    screen, _settings_repo, _store = _build_screen()
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        url_input = app.screen.query_one("#settings-wordlist-url", Input)
        assert url_input.value == DEFAULT_WORDLIST_URL
        status = str(app.screen.query_one("#settings-wordlist-status", Static).content)
        assert "Markov" in status


@pytest.mark.asyncio
async def test_save_does_not_persist_wordlist_url():
    app = App()
    screen, settings_repo, _store = _build_screen()
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-wordlist-url", Input).value = DEFAULT_WORDLIST_URL
        app.screen.query_one("#settings-speed-unit", Select).value = TargetSpeedUnit.CPM
        await pilot.pause()  # the unit switch converts the shown goal; overwrite it next
        app.screen.query_one("#settings-speed", Input).value = "400"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert settings_repo.settings.wordlist_url == ""
        assert settings_repo.settings.target_speed == 400


@pytest.mark.asyncio
async def test_import_uses_default_url_when_field_empty():
    app = App()
    store = FakeWordListStore(by_url={DEFAULT_WORDLIST_URL: ["hello", "world"]})
    screen, settings_repo, _store = _build_screen(wordlist_store=store)
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-wordlist-url", Input).value = ""
        await pilot.press("ctrl+i")
        await pilot.pause()

        assert settings_repo.settings.wordlist_url == DEFAULT_WORDLIST_URL
        assert app.screen.query_one("#settings-wordlist-url", Input).value == DEFAULT_WORDLIST_URL
        status = str(app.screen.query_one("#settings-wordlist-status", Static).content)
        assert "Imported 2 words." in status


@pytest.mark.asyncio
async def test_import_prefilled_default_url():
    app = App()
    store = FakeWordListStore(by_url={DEFAULT_WORDLIST_URL: ["hello", "world"]})
    screen, settings_repo, _store = _build_screen(wordlist_store=store)
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        await pilot.press("ctrl+i")
        await pilot.pause()

        assert settings_repo.settings.wordlist_url == DEFAULT_WORDLIST_URL
        status = str(app.screen.query_one("#settings-wordlist-status", Static).content)
        assert "Imported 2 words." in status


@pytest.mark.asyncio
async def test_import_shows_error_on_wordlist_error():
    app = App()
    store = FakeWordListStore(download_error=OSError("network down"))
    screen, settings_repo, _store = _build_screen(wordlist_store=store)
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        app.screen.query_one("#settings-wordlist-url", Input).value = "https://example.com/w.txt"
        await pilot.press("ctrl+i")
        await pilot.pause()

        error = str(app.screen.query_one("#settings-error", Static).content)
        assert "network down" in error
        assert settings_repo.settings.wordlist_url == ""


@pytest.mark.asyncio
async def test_saved_url_without_cache_shows_markov_status():
    app = App()
    url = "https://example.com/words.txt"
    settings_repo = FakeSettingsRepository(Settings(wordlist_url=url))
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    store = FakeWordListStore()
    screen = SettingsScreen(
        services=SettingsServices(
            settings_repo=settings_repo,
            layout_repo=layout_repo,
            update_settings=UpdateSettings(repo=settings_repo),
            import_wordlist=ImportWordList(store=store, settings_repo=settings_repo),
            clear_wordlist=ClearWordList(settings_repo=settings_repo),
            get_wordlist_cache_status=GetWordListCacheStatus(store=store),
        ),
    )
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        status = str(app.screen.query_one("#settings-wordlist-status", Static).content)
        assert "Not cached" in status


@pytest.mark.asyncio
async def test_clear_removes_wordlist_and_uses_markov():
    app = App()
    url = "https://example.com/words.txt"
    settings_repo = FakeSettingsRepository(Settings(wordlist_url=url))
    layout_repo = FakeLayoutRepository(dict(BUNDLED_LAYOUTS))
    store = FakeWordListStore(by_url={url: ["hello"]})
    screen = SettingsScreen(
        services=SettingsServices(
            settings_repo=settings_repo,
            layout_repo=layout_repo,
            update_settings=UpdateSettings(repo=settings_repo),
            import_wordlist=ImportWordList(store=store, settings_repo=settings_repo),
            clear_wordlist=ClearWordList(settings_repo=settings_repo),
            get_wordlist_cache_status=GetWordListCacheStatus(store=store),
        ),
    )
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        await pilot.press("ctrl+x")
        await pilot.pause()

        assert settings_repo.settings.wordlist_url == ""
        assert app.screen.query_one("#settings-wordlist-url", Input).value == DEFAULT_WORDLIST_URL
        status = str(app.screen.query_one("#settings-wordlist-status", Static).content)
        assert "Markov" in status
