"""Rich-markup sparkline/trend-line formatting for stats and practice screens.

Pure display logic: no I/O, no use cases — just numeric-values-in,
Rich-markup-strings-out. Lives in presentation because it renders to Rich
markup, not because it needs a screen.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from keystrike.application.session_use_cases import compute_wpm
from keystrike.domain.confidence import target_ms_per_char
from keystrike.domain.models import SessionResult
from keystrike.presentation.theme import (
    STYLE_TREND_ACCURACY,
    STYLE_TREND_CONFIDENCE,
    STYLE_TREND_SPEED,
)

_SPARK = "▁▂▃▄▅▆▇█"


def _recent(headers: Sequence[SessionResult], limit: int) -> list[SessionResult]:
    """The most recent ``limit`` headers, oldest→newest."""
    return sorted(headers, key=lambda h: h.started_at)[-limit:]


def value_sparkline(values: Sequence[float]) -> str:
    """Unicode sparkline for numeric values, oldest→newest."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        level = len(_SPARK) - 1 if hi > 0 else 0
        return _SPARK[level] * len(values)
    span = hi - lo
    return "".join(
        _SPARK[min(len(_SPARK) - 1, int((v - lo) / span * (len(_SPARK) - 1)))] for v in values
    )


def wpm_sparkline(headers: Sequence[SessionResult], *, limit: int = 20) -> str:
    """Unicode sparkline of WPM per session, oldest→newest."""
    ordered = _recent(headers, limit)
    if not ordered:
        return ""
    return value_sparkline([compute_wpm(h) for h in ordered])


def _display_confidence(
    stored_conf: float,
    stored_target_cpm: int,
    current_target_cpm: int,
) -> float:
    if stored_target_cpm <= 0 or current_target_cpm <= 0:
        return stored_conf
    return stored_conf * (
        target_ms_per_char(current_target_cpm) / target_ms_per_char(stored_target_cpm)
    )


def focus_confidence_values(
    headers: Sequence[SessionResult],
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
) -> list[float]:
    ordered = _recent(headers, limit)
    return [
        _display_confidence(
            h.key_confidence.get(h.focus_key, 0.0) if h.focus_key is not None else 0.0,
            h.target_speed_cpm,
            current_target_speed_cpm,
        )
        for h in ordered
    ]


def focus_confidence_sparkline(
    headers: Sequence[SessionResult],
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
) -> str:
    """Unicode sparkline of focus-key confidence per session, oldest→newest."""
    values = focus_confidence_values(
        headers,
        limit=limit,
        current_target_speed_cpm=current_target_speed_cpm,
    )
    if not values:
        return ""
    return value_sparkline(values)


def key_confidence_values(
    headers: Sequence[SessionResult],
    codepoint: int,
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
) -> list[float]:
    ordered = _recent(headers, limit)
    return [
        _display_confidence(
            h.key_confidence.get(codepoint, 0.0),
            h.target_speed_cpm,
            current_target_speed_cpm,
        )
        for h in ordered
    ]


def key_confidence_sparkline(
    headers: Sequence[SessionResult],
    codepoint: int,
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
) -> str:
    values = key_confidence_values(
        headers,
        codepoint,
        limit=limit,
        current_target_speed_cpm=current_target_speed_cpm,
    )
    if not values:
        return ""
    return value_sparkline(values)


def char_label(codepoint: int) -> str:
    ch = chr(codepoint)
    return ch if ch.isprintable() and not ch.isspace() else f"U+{codepoint:04X}"


def _focus_char_label(focus_key: int | None) -> str:
    if focus_key is None:
        return "?"
    return char_label(focus_key)


def format_wpm_trend_line(headers: Sequence[SessionResult], *, limit: int = 20) -> str:
    ordered = _recent(headers, limit)
    if not ordered:
        return ""
    wpms = [compute_wpm(h) for h in ordered]
    spark = wpm_sparkline(headers, limit=limit)
    return (
        f"[bold]WPM trend[/] ({len(wpms)} sessions)  {spark}  "
        f"[dim]latest {wpms[-1]:.0f}  peak {max(wpms):.0f}[/]"
    )


def format_focus_confidence_trend_line(
    headers: Sequence[SessionResult],
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
) -> str:
    ordered = _recent(headers, limit)
    if not ordered:
        return ""
    focus_key = ordered[-1].focus_key
    if focus_key is None:
        return ""
    values = key_confidence_values(
        headers,
        focus_key,
        limit=limit,
        current_target_speed_cpm=current_target_speed_cpm,
    )
    label = _focus_char_label(focus_key)
    return format_aggregate_metric_trend_block(
        title=f"Focus '{label}'",
        confidence_values=values,
        speed_values=[],
        accuracy_values=[],
        limit=limit,
    )


def _colored_sparkline(spark: str, color: str) -> str:
    return f"[{color}]{spark}[/]" if spark else ""


def _default_metric_value(value: float) -> str:
    return f"{value:.2f}"


_GRID_LABEL_WIDTH = 10
_GRID_VALUE_WIDTH = 8


def _format_metric_trend_line(
    label: str,
    color: str,
    values: Sequence[float],
    spark: str,
    *,
    format_value: Callable[[float], str] | None = None,
    suffix: str = "",
    grid: bool = False,
    spark_width: int = 20,
) -> str:
    if not values:
        return ""
    # `grid` is the single mode switch: grid layout packs sparklines/values into
    # fixed-width columns for side-by-side blocks and omits the session count
    # (the block header already shows it); inline layout does the opposite.
    fmt = format_value or _default_metric_value
    label_text = label.ljust(_GRID_LABEL_WIDTH) if grid else label
    spark_text = spark.ljust(spark_width) if grid else spark
    session_part = "  " if grid else f" ({len(values)} sessions)  "
    latest_str = fmt(values[-1])
    peak_str = fmt(max(values))
    if grid:
        values_part = (
            f"latest {latest_str:>{_GRID_VALUE_WIDTH}}  peak {peak_str:>{_GRID_VALUE_WIDTH}}"
        )
    else:
        values_part = f"latest {latest_str}  peak {peak_str}"
    line = (
        f"[bold {color}]{label_text}[/]{session_part}"
        f"{_colored_sparkline(spark_text, color)}  "
        f"[dim {color}]{values_part}[/]"
    )
    if suffix:
        line += f"  {suffix}"
    return line


def format_confidence_trend_line(
    values: Sequence[float],
    *,
    grid: bool = False,
    spark_width: int = 20,
) -> str:
    return _format_metric_trend_line(
        "confidence",
        STYLE_TREND_CONFIDENCE,
        values,
        value_sparkline(values),
        grid=grid,
        spark_width=spark_width,
    )


def format_key_confidence_trend_line(
    headers: Sequence[SessionResult],
    codepoint: int,
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
    cumulative: float | None = None,
    grid: bool = False,
    spark_width: int = 20,
) -> str:
    # In grid layout the enclosing block's title already names the key, so the
    # line itself drops the key name to avoid repeating it; inline layout has
    # no such title, so the line names the key itself.
    ordered = _recent(headers, limit)
    if not ordered:
        return ""
    values = key_confidence_values(
        headers,
        codepoint,
        limit=limit,
        current_target_speed_cpm=current_target_speed_cpm,
    )
    spark = key_confidence_sparkline(
        headers,
        codepoint,
        limit=limit,
        current_target_speed_cpm=current_target_speed_cpm,
    )
    char = char_label(codepoint)
    label = "confidence" if grid else f"'{char}' confidence"
    suffix = ""
    if cumulative is not None:
        suffix = f"[dim {STYLE_TREND_CONFIDENCE}]cumulative {cumulative:.2f}[/]"
    return _format_metric_trend_line(
        label,
        STYLE_TREND_CONFIDENCE,
        values,
        spark,
        suffix=suffix,
        grid=grid,
        spark_width=spark_width,
    )


def format_key_speed_trend_line(
    values: Sequence[float],
    *,
    grid: bool = False,
    spark_width: int = 20,
) -> str:
    return _format_metric_trend_line(
        "speed",
        STYLE_TREND_SPEED,
        values,
        value_sparkline(values),
        grid=grid,
        spark_width=spark_width,
    )


def format_key_accuracy_trend_line(
    values: Sequence[float],
    *,
    grid: bool = False,
    spark_width: int = 20,
) -> str:
    pct_values = [v * 100 for v in values]
    return _format_metric_trend_line(
        "accuracy",
        STYLE_TREND_ACCURACY,
        pct_values,
        value_sparkline(pct_values),
        format_value=lambda v: f"{v:.1f}%",
        grid=grid,
        spark_width=spark_width,
    )


def _assemble_trend_block(
    title: str,
    session_count: int,
    conf_line: str,
    speed_values: Sequence[float],
    accuracy_values: Sequence[float],
    *,
    grid: bool,
    spark_width: int,
) -> str:
    header = f"[bold]{title}[/]"
    if not session_count:
        return ""
    header += f" ({session_count} sessions)"
    lines = [
        header,
        conf_line,
        format_key_speed_trend_line(speed_values, grid=grid, spark_width=spark_width),
        format_key_accuracy_trend_line(accuracy_values, grid=grid, spark_width=spark_width),
    ]
    return "\n".join(line for line in lines if line)


def format_key_metric_trend_block(
    title: str,
    *,
    headers: Sequence[SessionResult],
    codepoint: int,
    speed_values: Sequence[float],
    accuracy_values: Sequence[float],
    limit: int = 20,
    current_target_speed_cpm: int = 0,
    cumulative: float | None = None,
) -> str:
    """Trend block for a single key: confidence line driven by session headers."""
    grid = True
    spark_width = limit
    ordered = _recent(headers, limit)
    session_count = len(ordered) if ordered else max(len(speed_values), len(accuracy_values), 0)
    conf_line = format_key_confidence_trend_line(
        headers,
        codepoint,
        limit=limit,
        current_target_speed_cpm=current_target_speed_cpm,
        cumulative=cumulative,
        grid=grid,
        spark_width=spark_width,
    )
    return _assemble_trend_block(
        title,
        session_count,
        conf_line,
        speed_values,
        accuracy_values,
        grid=grid,
        spark_width=spark_width,
    )


def format_aggregate_metric_trend_block(
    title: str,
    *,
    confidence_values: Sequence[float],
    speed_values: Sequence[float],
    accuracy_values: Sequence[float],
    limit: int = 20,
) -> str:
    """Trend block for layout-wide (or other pre-computed) confidence values."""
    grid = True
    spark_width = limit
    session_count = max(len(confidence_values), len(speed_values), len(accuracy_values), 0)
    conf_line = format_confidence_trend_line(
        confidence_values,
        grid=grid,
        spark_width=spark_width,
    )
    return _assemble_trend_block(
        title,
        session_count,
        conf_line,
        speed_values,
        accuracy_values,
        grid=grid,
        spark_width=spark_width,
    )
