"""Build docs/assets/demo.gif from presentation snapshot SVGs.

Run after `uv sync --group snapshot` and
`pytest tests/presentation/test_snapshots.py --snapshot-update`.

Requires pillow + cairosvg (one-off: `uv pip install pillow cairosvg`).
On macOS with Homebrew cairo: `DYLD_LIBRARY_PATH=/opt/homebrew/lib`.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import cairosvg
from PIL import Image

_ROOT = Path(__file__).resolve().parent.parent
_SNAPSHOTS = _ROOT / "tests/presentation/__snapshots__/test_snapshots"
_OUT = _ROOT / "docs/assets/demo.gif"

_FRAME_MS = 10_000  # ~10 s per frame in the README demo GIF

_FRAMES = (
    "test_home_screen_snapshot.svg",
    "test_practice_screen_snapshot.svg",
    "test_stats_screen_snapshot.svg",
    "test_settings_screen_snapshot.svg",
    "test_home_screen_snapshot.svg",
)


def _svg_to_image(path: Path) -> Image.Image:
    png = cairosvg.svg2png(url=str(path), output_width=720)
    return Image.open(io.BytesIO(png)).convert("P", palette=Image.ADAPTIVE)


def main() -> None:
    if sys.platform == "darwin" and "DYLD_LIBRARY_PATH" not in os.environ:
        brew_lib = Path("/opt/homebrew/lib")
        if brew_lib.is_dir():
            os.environ["DYLD_LIBRARY_PATH"] = str(brew_lib)

    frames: list[Image.Image] = []
    for name in _FRAMES:
        svg = _SNAPSHOTS / name
        if not svg.is_file():
            raise SystemExit(f"missing snapshot: {svg}")
        frames.append(_svg_to_image(svg))

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        _OUT,
        save_all=True,
        append_images=frames[1:],
        duration=_FRAME_MS,
        loop=0,
        optimize=True,
    )
    print(f"wrote {_OUT} ({_OUT.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
