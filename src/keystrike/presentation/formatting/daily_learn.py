"""Rich-markup formatting for the daily learn-time budget.

Pure display logic: no I/O, no use cases — just a `DailyLearnDisplay` in,
a markup string out. Shared by the home screen's hero text and the practice
HUD so they can't drift on how the used/limit fragment reads.
"""

from __future__ import annotations

from keystrike.domain.daily_learn import DailyLearnDisplay


def format_daily_learn_minutes(display: DailyLearnDisplay) -> str:
    """`used/limit min` fragment -- callers own the surrounding label and
    coloring."""
    return f"[bold]{display.used_minutes:.1f}[/]/{display.limit_minutes:g} min"
