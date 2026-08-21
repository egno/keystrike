"""Rich-markup sparkline/trend-line formatting for stats and practice screens.

Pure display logic: no I/O, no use cases — just numeric-values-in,
Rich-markup-strings-out. Lives in presentation because it renders to Rich
markup, not because it needs a screen.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from keystrike.application.session_queries import compute_accuracy, compute_wpm
from keystrike.application.session_use_cases import SessionStatsBaseline
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
_DEFAULT_TREND_LIMIT = 20  # recent-sessions window, and matching sparkline width


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
    limit: int = _DEFAULT_TREND_LIMIT,
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
    limit: int = _DEFAULT_TREND_LIMIT,
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
    limit: int = _DEFAULT_TREND_LIMIT,
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
        limit=limit,
    )


def _colored_sparkline(spark: str, color: str) -> str:
    return f"[{color}]{spark}[/]" if spark else ""


def _default_metric_value(value: float) -> str:
    return f"{value:.2f}"


_GRID_LABEL_WIDTH = 10
_GRID_VALUE_WIDTH = 8


@dataclass(frozen=True, slots=True)
class MetricLineSpec:
    """One metric's inputs to `_format_metric_trend_line_grid` -- bundled so
    the three near-identical per-metric callers (confidence/speed/accuracy)
    thread one object instead of the same six positional/keyword args.

    No `spark` field: the sparkline is always `value_sparkline(values)`, so
    it can't be built from a different series than `values` shows."""

    label: str
    color: str
    values: Sequence[float]
    format_value: Callable[[float], str] | None = None
    suffix: str = ""
    spark_width: int = _DEFAULT_TREND_LIMIT


def _format_metric_trend_line_grid(spec: MetricLineSpec) -> str:
    """Fixed-width columns for side-by-side blocks; session count omitted
    (the enclosing block header already shows it)."""
    if not spec.values:
        return ""
    fmt = spec.format_value or _default_metric_value
    label_text = spec.label.ljust(_GRID_LABEL_WIDTH)
    spark_text = value_sparkline(spec.values).ljust(spec.spark_width)
    latest_str = fmt(spec.values[-1])
    peak_str = fmt(max(spec.values))
    values_part = f"latest {latest_str:>{_GRID_VALUE_WIDTH}}  peak {peak_str:>{_GRID_VALUE_WIDTH}}"
    line = (
        f"[bold {spec.color}]{label_text}[/]  "
        f"{_colored_sparkline(spark_text, spec.color)}  "
        f"[dim {spec.color}]{values_part}[/]"
    )
    if spec.suffix:
        line += f"  {spec.suffix}"
    return line


def _format_confidence_trend_line_grid(
    values: Sequence[float], *, spark_width: int = _DEFAULT_TREND_LIMIT
) -> str:
    return _format_metric_trend_line_grid(
        MetricLineSpec("confidence", STYLE_TREND_CONFIDENCE, values, spark_width=spark_width)
    )


def _format_key_confidence_trend_line_grid(
    headers: Sequence[SessionResult],
    codepoint: int,
    *,
    limit: int = _DEFAULT_TREND_LIMIT,
    current_target_speed_cpm: int = 0,
    cumulative: float | None = None,
    spark_width: int = _DEFAULT_TREND_LIMIT,
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
    suffix = ""
    if cumulative is not None:
        suffix = f"[dim {STYLE_TREND_CONFIDENCE}]cumulative {cumulative:.2f}[/]"
    return _format_metric_trend_line_grid(
        MetricLineSpec(
            "confidence",
            STYLE_TREND_CONFIDENCE,
            values,
            suffix=suffix,
            spark_width=spark_width,
        )
    )


def _format_key_speed_trend_line_grid(
    values: Sequence[float], *, spark_width: int = _DEFAULT_TREND_LIMIT
) -> str:
    return _format_metric_trend_line_grid(
        MetricLineSpec("speed", STYLE_TREND_SPEED, values, spark_width=spark_width)
    )


def _format_key_accuracy_trend_line_grid(
    values: Sequence[float], *, spark_width: int = _DEFAULT_TREND_LIMIT
) -> str:
    pct_values = [v * 100 for v in values]
    return _format_metric_trend_line_grid(
        MetricLineSpec(
            "accuracy",
            STYLE_TREND_ACCURACY,
            pct_values,
            format_value=lambda v: f"{v:.1f}%",
            spark_width=spark_width,
        )
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
    if not session_count:
        return ""
    lines = [
        f"[bold]{title}[/] ({session_count} sessions)",
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
    limit: int = _DEFAULT_TREND_LIMIT,
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
    speed_values: Sequence[float] | None = None,
    accuracy_values: Sequence[float] | None = None,
    limit: int = _DEFAULT_TREND_LIMIT,
) -> str:
    """Trend block for layout-wide (or other pre-computed) confidence values.

    `speed_values`/`accuracy_values` are omittable -- callers with only a
    confidence series (e.g. `format_focus_confidence_trend_line`) don't need
    to fake up empty sequences just to signal "not applicable"."""
    speed_values = speed_values or ()
    accuracy_values = accuracy_values or ()
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
