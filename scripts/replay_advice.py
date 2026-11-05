#!/usr/bin/env python3
"""Dev-only: replay stored sessions through an advisor and check whether its
advice was followed by improvement.

For each session in a layout's history, the script rebuilds the context the
advisor would have seen (the newest `--window` sessions up to that point, with
their raw keystroke streams), runs the advisor, validates the advice with the
core rules, and then looks at the next `--horizon` sessions that have raw
streams.

It compares two groups of keys, before and after the advice:

- **advised** keys: named in a `focus`, `focus_pair`, `emphasize` or `contrast`
  recommendation;
- **other** keys: the remaining unlocked keys.

The number to read is the *difference of differences*:

    (advised after - advised before) - (other after - other before)

A negative error-rate change means the advised keys improved more than the
others. The script prints a standard error next to every change. A change
smaller than about two standard errors is noise. With few sessions it almost
always is.

It only reads data. It never writes the advice cache or any session file, so
it is safe to run on your real practice history.

Usage:
    uv run python scripts/replay_advice.py [--layout NAME] [--advisor rules]
        [--window N] [--horizon 3] [--min-history 3] [--decay 1.0 0.85 0.7]
        [--config-dir DIR --data-dir DIR] [--allow-off-device] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from keystrike.advisors import rules
from keystrike.application.advisor_context import build_advisor_context
from keystrike.application.advisor_registry import AdvisorRegistry
from keystrike.domain.advice import Advisor, Kind, validate_advice
from keystrike.domain.keystroke_insights import first_attempts
from keystrike.domain.models import KeyPos, Keystroke, SessionResult
from keystrike.infrastructure.advisor_config_toml import TomlAdvisorConfigRepository
from keystrike.infrastructure.layout_repo import CompositeLayoutRepository
from keystrike.infrastructure.paths import Paths, default_paths
from keystrike.infrastructure.plugin_loader import load_plugins
from keystrike.infrastructure.raw_keystroke_store import RawKeystrokeStore
from keystrike.infrastructure.session_repo_jsonl import JsonlSessionRepository
from keystrike.infrastructure.settings_repo_toml import TomlSettingsRepository

# Kinds whose keys count as "advised". EASE is left out on purpose: easing a
# key is not a request to practice it.
ADVISED_KINDS = (Kind.FOCUS, Kind.FOCUS_PAIR, Kind.EMPHASIZE, Kind.CONTRAST)
MIN_POSITIONS_FOR_RATE = 1


@dataclass(slots=True)
class Cell:
    """Position and error counts, and time of correct first attempts."""

    positions: int = 0
    errors: int = 0
    time_ns: int = 0
    timed: int = 0

    def add(self, other: Cell) -> None:
        self.positions += other.positions
        self.errors += other.errors
        self.time_ns += other.time_ns
        self.timed += other.timed

    @property
    def error_rate(self) -> float:
        return self.errors / self.positions if self.positions else 0.0

    @property
    def mean_ms(self) -> float:
        return self.time_ns / self.timed / 1e6 if self.timed else 0.0

    def rate_variance(self) -> float:
        """Variance of the error rate (binomial)."""
        if not self.positions:
            return 0.0
        p = self.error_rate
        return p * (1.0 - p) / self.positions


def position_cells(streams: Iterable[Sequence[Keystroke]], keys: frozenset[int]) -> Cell:
    """Count the positions of `keys` in `streams`. A position is one target
    character; only its first attempt counts, so retries after an error are not
    new positions. The time of a correct first attempt is the gap since the
    keystroke before it."""
    cell = Cell()
    for stream in streams:
        firsts = {id(ks) for ks in first_attempts(stream)}
        for i, ks in enumerate(stream):
            if id(ks) not in firsts or ks.codepoint not in keys:
                continue
            cell.positions += 1
            if not ks.correct:
                cell.errors += 1
            elif i > 0:
                cell.time_ns += ks.t_ns - stream[i - 1].t_ns
                cell.timed += 1
    return cell


@dataclass(slots=True)
class Point:
    """One advice, and what happened to the keys it did and did not name."""

    session_id: str
    summary: str
    kinds: tuple[str, ...]
    advised: tuple[int, ...]
    others: tuple[int, ...]
    advised_before: Cell
    advised_after: Cell
    others_before: Cell
    others_after: Cell


@dataclass(slots=True)
class Totals:
    points: int = 0
    skipped: dict[str, int] = field(default_factory=dict[str, int])
    advised_before: Cell = field(default_factory=Cell)
    advised_after: Cell = field(default_factory=Cell)
    others_before: Cell = field(default_factory=Cell)
    others_after: Cell = field(default_factory=Cell)
    kinds: dict[str, int] = field(default_factory=dict[str, int])


def _skip(totals: Totals, reason: str) -> None:
    totals.skipped[reason] = totals.skipped.get(reason, 0) + 1


async def replay(
    sessions: Sequence[SessionResult],
    streams: dict[str, list[Keystroke]],
    advisor: Advisor,
    *,
    needs_keystrokes: bool,
    window: int,
    horizon: int,
    min_history: int,
    layout_keys: dict[int, KeyPos] | None = None,
    recency_decay: float = 1.0,
) -> tuple[list[Point], Totals]:
    """Replay `sessions` (oldest first) through `advisor`. Only the stored
    data is read; nothing is written. `recency_decay` is the weight ratio
    between a session and the next older one in each context (1.0 = equal)."""
    points: list[Point] = []
    totals = Totals()
    for i in range(len(sessions)):
        if i + 1 < min_history:
            _skip(totals, "not enough history")
            continue
        history = list(reversed(sessions[max(0, i + 1 - window) : i + 1]))  # newest first
        history_streams = {
            s.session_id: streams[s.session_id] for s in history if s.session_id in streams
        }
        ctx = build_advisor_context(
            sessions[i].layout,
            history,
            history_streams if needs_keystrokes else {},
            layout_keys,
            recency_decay=recency_decay,
        )
        if ctx.digest.is_empty:
            _skip(totals, "no data")
            continue
        advice = validate_advice(await advisor(ctx), ctx.course)
        advised = frozenset(k for r in advice.of_kind(*ADVISED_KINDS) for k in r.keys)
        if not advised:
            _skip(totals, "no advised keys")
            continue
        future = [
            streams[s.session_id]
            for s in sessions[i + 1 : i + 1 + horizon]
            if s.session_id in streams
        ]
        if not future or not history_streams:
            _skip(totals, "no raw streams before or after")
            continue
        others = frozenset(ctx.course.unlocked) - advised
        point = Point(
            session_id=sessions[i].session_id,
            summary=advice.summary,
            kinds=tuple(dict.fromkeys(r.kind.value for r in advice.recommendations)),
            advised=tuple(sorted(advised)),
            others=tuple(sorted(others)),
            advised_before=position_cells(history_streams.values(), advised),
            advised_after=position_cells(future, advised),
            others_before=position_cells(history_streams.values(), others),
            others_after=position_cells(future, others),
        )
        points.append(point)
        totals.points += 1
        totals.advised_before.add(point.advised_before)
        totals.advised_after.add(point.advised_after)
        totals.others_before.add(point.others_before)
        totals.others_after.add(point.others_after)
        for kind in point.kinds:
            totals.kinds[kind] = totals.kinds.get(kind, 0) + 1
    return points, totals


@dataclass(frozen=True, slots=True)
class Change:
    value: float
    stderr: float

    @property
    def noise(self) -> bool:
        return abs(self.value) < 2 * self.stderr


def error_rate_change(before: Cell, after: Cell) -> Change:
    return Change(
        after.error_rate - before.error_rate,
        math.sqrt(before.rate_variance() + after.rate_variance()),
    )


def difference_of_differences(totals: Totals) -> Change:
    advised = error_rate_change(totals.advised_before, totals.advised_after)
    others = error_rate_change(totals.others_before, totals.others_after)
    return Change(advised.value - others.value, math.sqrt(advised.stderr**2 + others.stderr**2))


def speed_change(before: Cell, after: Cell) -> float:
    """Change in mean ms per correct first attempt (negative = faster)."""
    return after.mean_ms - before.mean_ms


def _pct(change: Change) -> str:
    flag = "  (within noise)" if change.noise else ""
    return f"{change.value * 100:+.1f} pts ± {change.stderr * 100:.1f}{flag}"


def render_comparison(
    runs: list[tuple[float, list[Point], Totals]], *, layout: str, advisor: str
) -> str:
    """One line per recency decay: how the difference of differences moves."""
    lines = [
        f"Replay of {advisor!r} on {layout!r}, one run per recency decay.",
        "(1.0 = every session in the window weighs the same; smaller = older sessions fade.)",
        "",
        f"{'decay':>6}  {'points':>6}  difference of differences (advised - others)",
    ]
    for decay, _points, totals in runs:
        if not totals.points:
            lines.append(f"{decay:>6.2f}  {0:>6}  nothing to compare")
            continue
        lines.append(
            f"{decay:>6.2f}  {totals.points:>6}  {_pct(difference_of_differences(totals))}"
        )
    lines += [
        "",
        "Negative means the advised keys improved more than the others. Differences",
        "between decays smaller than the standard error are noise; with few sessions",
        "they almost always are.",
    ]
    return "\n".join(lines)


def render(
    points: list[Point], totals: Totals, *, layout: str, advisor: str, decay: float = 1.0
) -> str:
    lines = [
        f"Replay of {advisor!r} on {layout!r} (recency decay {decay:g}): "
        f"{totals.points} advice point(s) used."
    ]
    if totals.skipped:
        skipped = ", ".join(f"{n} {why}" for why, n in sorted(totals.skipped.items()))
        lines.append(f"Skipped: {skipped}.")
    if totals.kinds:
        lines.append("Kinds: " + ", ".join(f"{k} x{n}" for k, n in sorted(totals.kinds.items())))
    if not points:
        lines.append("Nothing to compare yet: it needs sessions with raw keystroke files.")
        return "\n".join(lines)
    lines.append("")
    lines.append(
        f"{'session':<10} {'adv before':>11} {'adv after':>10} "
        f"{'oth before':>11} {'oth after':>10}  kinds"
    )
    for p in points:
        lines.append(
            f"{p.session_id[:8]:<10} "
            f"{p.advised_before.error_rate * 100:>5.1f}% /{p.advised_before.positions:<4} "
            f"{p.advised_after.error_rate * 100:>4.1f}% /{p.advised_after.positions:<4} "
            f"{p.others_before.error_rate * 100:>5.1f}% /{p.others_before.positions:<4} "
            f"{p.others_after.error_rate * 100:>4.1f}% /{p.others_after.positions:<4} "
            + ",".join(p.kinds)
        )
    adv = error_rate_change(totals.advised_before, totals.advised_after)
    oth = error_rate_change(totals.others_before, totals.others_after)
    did = difference_of_differences(totals)
    lines += [
        "",
        f"Advised keys: error rate {_pct(adv)}  "
        f"({totals.advised_before.positions} -> {totals.advised_after.positions} positions)",
        f"Other keys:   error rate {_pct(oth)}  "
        f"({totals.others_before.positions} -> {totals.others_after.positions} positions)",
        f"Difference of differences (advised - others): {_pct(did)}",
        f"Speed (ms per correct first attempt): advised "
        f"{speed_change(totals.advised_before, totals.advised_after):+.0f}, "
        f"others {speed_change(totals.others_before, totals.others_after):+.0f}",
        "",
        "Negative means the advised keys improved more than the others.",
        "The same session can appear in several windows, and the advised keys are "
        "chosen because they were weak (they tend to improve anyway), so treat "
        "this as a sanity check, not as proof.",
    ]
    return "\n".join(lines)


def _paths(args: argparse.Namespace) -> Paths:
    base = default_paths()
    return Paths(
        config_dir=Path(args.config_dir) if args.config_dir else base.config_dir,
        data_dir=Path(args.data_dir) if args.data_dir else base.data_dir,
        log_dir=base.log_dir,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--layout", help="layout to replay (default: the current one)")
    parser.add_argument("--advisor", help="advisor name (default: the active one)")
    parser.add_argument("--window", type=int, help="sessions per context (default: from settings)")
    parser.add_argument("--horizon", type=int, default=3, help="sessions to look at after advice")
    parser.add_argument(
        "--min-history", type=int, default=3, help="sessions before the first advice"
    )
    parser.add_argument(
        "--decay",
        type=float,
        nargs="+",
        help=(
            "recency decay (weight ratio between a session and the next older one; "
            "1.0 = equal weights). Give several to compare them. Default: from advisors.toml"
        ),
    )
    parser.add_argument("--config-dir")
    parser.add_argument("--data-dir")
    parser.add_argument(
        "--allow-off-device",
        action="store_true",
        help="allow an advisor that sends data off the device (one request per advice point)",
    )
    parser.add_argument("--json", action="store_true", help="print the numbers as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = _paths(args)
    settings = TomlSettingsRepository(paths).load()
    config = TomlAdvisorConfigRepository(paths).load()
    registry = AdvisorRegistry()
    rules.register(registry)
    for error in load_plugins(registry):
        print(f"plugin: {error}", file=sys.stderr)
    name = args.advisor or (config.active if registry.has(config.active) else rules.NAME)
    if name == "off" or not registry.has(name):
        print(f"No advisor to replay: {name!r}.", file=sys.stderr)
        return 2
    spec = registry.get(name)
    if spec.capabilities.sends_data_off_device and not args.allow_off_device:
        print(
            f"{name!r} sends practice data off the device. "
            "Pass --allow-off-device to replay it anyway.",
            file=sys.stderr,
        )
        return 2
    layout = args.layout or settings.layout
    window = args.window or settings.confidence_session_window
    sessions = sorted(
        JsonlSessionRepository(paths).iter_headers(layout), key=lambda s: s.started_at
    )
    streams = RawKeystrokeStore(paths.raw_keystrokes_dir).load([s.session_id for s in sessions])
    try:
        layout_keys = dict(CompositeLayoutRepository(paths).get(layout).keys)
    except (KeyError, OSError, ValueError):
        layout_keys = {}
    advisor = spec.create(config.section(name))
    decays = args.decay or [config.recency_decay]
    runs: list[tuple[float, list[Point], Totals]] = []
    for decay in decays:
        points, totals = asyncio.run(
            replay(
                sessions,
                streams,
                advisor,
                needs_keystrokes=spec.capabilities.needs_keystrokes,
                window=window,
                horizon=args.horizon,
                min_history=args.min_history,
                layout_keys=layout_keys,
                recency_decay=decay,
            )
        )
        runs.append((decay, points, totals))
    if args.json:
        print(
            json.dumps(
                {
                    "layout": layout,
                    "advisor": name,
                    "runs": [
                        {
                            "decay": decay,
                            "points": [asdict(p) for p in points],
                            "difference_of_differences": asdict(difference_of_differences(totals)),
                        }
                        for decay, points, totals in runs
                    ],
                },
                indent=2,
            )
        )
        return 0
    if len(runs) == 1:
        decay, points, totals = runs[0]
        print(render(points, totals, layout=layout, advisor=name, decay=decay))
    else:
        print(render_comparison(runs, layout=layout, advisor=name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
