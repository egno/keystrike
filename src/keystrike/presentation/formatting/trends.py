"""Rich-markup sparkline/trend-line formatting for stats and practice screens.

Pure display logic: no I/O, no use cases — just numeric-values-in,
Rich-markup-strings-out. Lives in presentation because it renders to Rich
markup, not because it needs a screen.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from keystrike.application.session_use_cases import (
    SessionStatsBaseline,
    compute_accuracy,
    compute_wpm,
)
from keystrike.domain.confidence import target_ms_per_char
from keystrike.domain.models import SessionResult
from keystrike.presentation.theme import (
    STYLE_DELTA_IMPROVE,
    STYLE_DELTA_REGRESS,
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


def _assemble_metric_line(
    label_text: str,
    session_part: str,
    spark_text: str,
    values_part: str,
    *,
    color: str,
    suffix: str,
) -> str:
    line = (
        f"[bold {color}]{label_text}[/]{session_part}"
        f"{_colored_sparkline(spark_text, color)}  "
        f"[dim {color}]{values_part}[/]"
    )
    if suffix:
        line += f"  {suffix}"
    return line


def _format_metric_trend_line_grid(
    label: str,
    color: str,
    values: Sequence[float],
    spark: str,
    *,
    format_value: Callable[[float], str] | None = None,
    suffix: str = "",
    spark_width: int = 20,
) -> str:
    """Fixed-width columns for side-by-side blocks; session count omitted
    (the enclosing block header already shows it)."""
    if not values:
        return ""
    fmt = format_value or _default_metric_value
    label_text = label.ljust(_GRID_LABEL_WIDTH)
    spark_text = spark.ljust(spark_width)
    latest_str = fmt(values[-1])
    peak_str = fmt(max(values))
    values_part = f"latest {latest_str:>{_GRID_VALUE_WIDTH}}  peak {peak_str:>{_GRID_VALUE_WIDTH}}"
    return _assemble_metric_line(
        label_text, "  ", spark_text, values_part, color=color, suffix=suffix
    )


def _format_confidence_trend_line_grid(values: Sequence[float], *, spark_width: int = 20) -> str:
    return _format_metric_trend_line_grid(
        "confidence",
        STYLE_TREND_CONFIDENCE,
        values,
        value_sparkline(values),
        spark_width=spark_width,
    )


def _format_key_confidence_trend_line_grid(
    headers: Sequence[SessionResult],
    codepoint: int,
    *,
    limit: int = 20,
    current_target_speed_cpm: int = 0,
    cumulative: float | None = None,
    spark_width: int = 20,
) -> str:
    # The enclosing block's title already names the key, so the line itself
    # drops the key name to avoid repeating it.
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
    suffix = ""
    if cumulative is not None:
        suffix = f"[dim {STYLE_TREND_CONFIDENCE}]cumulative {cumulative:.2f}[/]"
    return _format_metric_trend_line_grid(
        "confidence",
        STYLE_TREND_CONFIDENCE,
        values,
        spark,
        suffix=suffix,
        spark_width=spark_width,
    )


def _format_key_speed_trend_line_grid(values: Sequence[float], *, spark_width: int = 20) -> str:
    return _format_metric_trend_line_grid(
        "speed",
        STYLE_TREND_SPEED,
        values,
        value_sparkline(values),
        spark_width=spark_width,
    )


def _format_key_accuracy_trend_line_grid(values: Sequence[float], *, spark_width: int = 20) -> str:
    pct_values = [v * 100 for v in values]
    return _format_metric_trend_line_grid(
        "accuracy",
        STYLE_TREND_ACCURACY,
        pct_values,
        value_sparkline(pct_values),
        format_value=lambda v: f"{v:.1f}%",
        spark_width=spark_width,
    )


def _assemble_trend_block(
    title: str,
    session_count: int,
    conf_line: str,
    speed_values: Sequence[float],
    accuracy_values: Sequence[float],
    *,
    spark_width: int,
) -> str:
    header = f"[bold]{title}[/]"
    if not session_count:
        return ""
    header += f" ({session_count} sessions)"
    lines = [
        header,
        conf_line,
        _format_key_speed_trend_line_grid(speed_values, spark_width=spark_width),
        _format_key_accuracy_trend_line_grid(accuracy_values, spark_width=spark_width),
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
    spark_width = limit
    ordered = _recent(headers, limit)
    session_count = len(ordered) if ordered else max(len(speed_values), len(accuracy_values), 0)
    conf_line = _format_key_confidence_trend_line_grid(
        headers,
        codepoint,
        limit=limit,
        current_target_speed_cpm=current_target_speed_cpm,
        cumulative=cumulative,
        spark_width=spark_width,
    )
    return _assemble_trend_block(
        title,
        session_count,
        conf_line,
        speed_values,
        accuracy_values,
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
    spark_width = limit
    session_count = max(len(confidence_values), len(speed_values), len(accuracy_values), 0)
    conf_line = _format_confidence_trend_line_grid(
        confidence_values,
        spark_width=spark_width,
    )
    return _assemble_trend_block(
        title,
        session_count,
        conf_line,
        speed_values,
        accuracy_values,
        spark_width=spark_width,
    )


def _format_metric_delta(
    current: float,
    previous: float,
    *,
    suffix: str = "",
) -> str:
    delta = current - previous
    if round(abs(delta), 1) == 0:
        return ""
    color = STYLE_DELTA_IMPROVE if delta > 0 else STYLE_DELTA_REGRESS
    arrow = "↑" if delta > 0 else "↓"
    return f" [{color}]{arrow}{abs(delta):.1f}{suffix}[/]"


def format_session_stats_line(
    result: SessionResult,
    *,
    baseline: SessionStatsBaseline | None = None,
) -> str:
    wpm = compute_wpm(result)
    acc = compute_accuracy(result) * 100
    duration = result.duration_ns / 1e9
    wpm_delta = ""
    acc_delta = ""
    if baseline is not None:
        wpm_delta = _format_metric_delta(wpm, baseline.wpm)
        acc_delta = _format_metric_delta(
            acc,
            baseline.accuracy_pct,
            suffix="%",
        )
    return (
        f"Last: WPM [bold]{wpm:5.1f}[/]{wpm_delta}  "
        f"Acc [bold]{acc:5.1f}%[/]{acc_delta}  "
        f"Time [bold]{duration:5.1f}s[/]"
    )
