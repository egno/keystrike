"""Visual regression tests (desktop only — sync with `uv sync --group snapshot`)."""

from tests.presentation.test_practice_screen import _build_app


def test_home_screen_snapshot(snap_compare):
    app, *_ = _build_app()
    assert snap_compare(app, terminal_size=(80, 24))


def test_practice_screen_snapshot(snap_compare):
    app, *_ = _build_app()

    async def run_before(pilot) -> None:
        await pilot.press("enter")
        await pilot.pause()

    assert snap_compare(app, terminal_size=(80, 24), run_before=run_before)


def test_stats_screen_snapshot(snap_compare):
    app, *_ = _build_app()

    async def run_before(pilot) -> None:
        await pilot.press("s")
        await pilot.pause()

    assert snap_compare(app, terminal_size=(80, 24), run_before=run_before)


def test_settings_screen_snapshot(snap_compare):
    app, *_ = _build_app()

    async def run_before(pilot) -> None:
        await pilot.press("o")
        await pilot.pause()

    assert snap_compare(app, terminal_size=(80, 24), run_before=run_before)
