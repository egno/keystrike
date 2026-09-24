"""Build docs/assets/demo.gif from a seeded, simulated Keystrike run.

Drives the real app (with the test fakes for clock/storage) through a
deterministic typist who is fast on the home row, slow and error-prone on a
few keys, and improves over ~16 sessions. Then screenshots Home, a lesson in
progress, Stats (trends + heatmap), one letter's detail, and Settings.

Requires pillow + cairosvg (one-off: `uv pip install pillow cairosvg`).
On macOS `brew install cairo`; the script finds the Homebrew library itself.
"""

from __future__ import annotations

import asyncio
import io
import os
import random
import sys
from pathlib import Path
from typing import cast

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))  # `tests.*` fakes and the fully-wired test app

from tests.fakes import FakeClock  # noqa: E402
from tests.presentation.test_practice_screen import (  # noqa: E402
    _build_app,  # pyright: ignore[reportPrivateUsage]
)
from textual.pilot import Pilot  # noqa: E402

from keystrike.presentation.screens.practice import PracticeScreen  # noqa: E402

_OUT = _ROOT / "docs/assets/demo.gif"
_FRAME_MS = 5_000
_TERMINAL = (80, 24)
_SEED_SESSIONS = 16
_MID_LESSON_FRACTION = 0.45  # how much of the lesson is typed in the practice frame

# Textual key names for the non-letter characters a lesson can contain.
_KEY_NAMES = {" ": "space", ",": "comma", ".": "full_stop", ";": "semicolon", "/": "slash"}

_HOME_ROW = set("asdfghjkl")
_WEAK_KEYS = {"r": 2.0, "u": 1.8, "w": 1.6}  # slower and error-prone throughout
# Per-keystroke seconds before jitter/improvement. Tuned against the default
# 100 WPM goal (120 ms/char) so the final heatmap mixes green, yellow and red.
_BASE_S = {"home": 0.16, "other": 0.26}
_SPEEDUP_PER_SESSION = 0.97
_SLIP_P = {"weak": 0.25, "other": 0.04}
_SLIP_DECAY_PER_SESSION = 0.95


def _setup_cairo_path() -> None:
    if sys.platform != "darwin" or "DYLD_LIBRARY_PATH" in os.environ:
        return
    # `brew install cairo` does not always link libcairo into /opt/homebrew/lib.
    for brew_lib in (Path("/opt/homebrew/opt/cairo/lib"), Path("/opt/homebrew/lib")):
        if (brew_lib / "libcairo.2.dylib").is_file():
            os.environ["DYLD_LIBRARY_PATH"] = str(brew_lib)
            return


class _Typist:
    """Deterministic keystroke timing/error model that improves per session."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self.session = 0

    def delay_ns(self, char: str) -> int:
        base = _BASE_S["home"] if char in _HOME_ROW or char == " " else _BASE_S["other"]
        base *= _WEAK_KEYS.get(char, 1.0)
        base *= _SPEEDUP_PER_SESSION**self.session  # gets faster over time
        jitter = self._rng.uniform(0.8, 1.25)
        return int(base * jitter * 1e9)

    def slips(self, char: str) -> bool:
        p = _SLIP_P["weak"] if char in _WEAK_KEYS else _SLIP_P["other"]
        return self._rng.random() < p * _SLIP_DECAY_PER_SESSION**self.session

    def wrong_key(self, char: str) -> str:
        pool = [c for c in "asdfghjklqwertyuiopzxcvbnm" if c != char]
        return self._rng.choice(pool)


def _key(char: str) -> str:
    return _KEY_NAMES.get(char, char)


def _lesson_text(screen: object) -> str:
    assert isinstance(screen, PracticeScreen)
    return screen._session.target_text  # pyright: ignore[reportPrivateUsage]


async def _type(pilot: Pilot[None], clock: FakeClock, typist: _Typist, text: str) -> None:
    for char in text:
        if typist.slips(char) and char != " ":
            clock.advance(typist.delay_ns(char))
            await pilot.press(_key(typist.wrong_key(char)))
        clock.advance(typist.delay_ns(char))
        await pilot.press(_key(char))


async def _seed_and_capture() -> list[str]:
    app, clock, repo, _settings = _build_app()
    rng = random.Random(7)
    typist = _Typist(rng)
    svgs: list[str] = []

    async with app.run_test(size=_TERMINAL) as pilot:
        await pilot.press("enter")  # Home → Practice
        await pilot.pause()
        for i in range(_SEED_SESSIONS):
            typist.session = i
            clock.wall += 6 * 60  # sessions a few minutes apart, all "today"
            await _type(pilot, clock, typist, _lesson_text(app.screen))
            await pilot.pause()
            assert len(repo.headers) == i + 1, "lesson did not finish"

        # Frame: a lesson in progress with a slip already made.
        typist.session = _SEED_SESSIONS
        text = _lesson_text(app.screen)
        cut = int(len(text) * _MID_LESSON_FRACTION)
        await _type(pilot, clock, typist, text[:cut])
        await pilot.pause()
        practice_svg = app.export_screenshot()

        await pilot.press("escape")  # abort the in-progress lesson → Home
        await pilot.pause()
        svgs.append(app.export_screenshot())  # Home
        svgs.append(practice_svg)

        await pilot.press("s")
        await pilot.pause()
        svgs.append(app.export_screenshot())  # Stats overview
        await pilot.press("r")
        await pilot.pause()
        svgs.append(app.export_screenshot())  # Letter detail for a weak key
        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("o")
        await pilot.pause()
        svgs.append(app.export_screenshot())  # Settings
        await pilot.press("escape")
        await pilot.pause()

    svgs.append(svgs[0])  # loop back to Home
    return svgs


def main() -> None:
    _setup_cairo_path()
    import cairosvg  # noqa: PLC0415  (needs DYLD_LIBRARY_PATH set first)
    from PIL import Image  # noqa: PLC0415

    svgs = asyncio.run(_seed_and_capture())
    frames: list[Image.Image] = []
    for svg in svgs:
        png = cast("bytes", cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=720))
        frames.append(Image.open(io.BytesIO(png)).convert("P", palette=Image.Palette.ADAPTIVE))

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        _OUT,
        save_all=True,
        append_images=frames[1:],
        duration=_FRAME_MS,
        loop=0,
        optimize=True,
    )
    print(f"wrote {_OUT} ({_OUT.stat().st_size // 1024} KiB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
