"""Pure confidence math for keybr-style progression.

Used by the M2 Stats heatmap and the M3 adaptive engine's key-unlock / focus-
selection logic (§6 of PLAN.md).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import KeyStats


def target_ms_per_char(target_speed_cpm: int) -> float:
    return 60_000.0 / target_speed_cpm


def key_confidence(target_ms_per_char: float, mean_time_ns: float) -> float:
    """Speed confidence = target / actual. > 1.0 is above target, < 1.0 is below."""
    if mean_time_ns <= 0:
        return 0.0
    return target_ms_per_char / (mean_time_ns / 1e6)


def accuracy_of(key_stats: KeyStats) -> float:
    """Fraction of attempts on this key that were correct. 0.0 for a key with
    no correct attempts yet, including one that's been missed but never hit."""
    total = key_stats.samples + key_stats.error_count
    return key_stats.samples / total if total > 0 else 0.0


def confidence_of(
    codepoint: int, stats: Mapping[int, KeyStats], target: float, recover_keys: bool,
) -> float:
    """Confidence for one key: historical peak (`recover_keys=True`, so a bad
    recent session doesn't un-recommend an already-mastered key) or live,
    recomputed from the current target. 0.0 for a never-practiced key.

    Speed confidence is scaled by accuracy so a key typed fast but frequently
    wrong doesn't read as mastered (accuracy-first: see docs/research/typing-pedagogy.md).
    """
    key_stats = stats.get(codepoint)
    if key_stats is None:
        return 0.0
    if recover_keys:
        return key_stats.peak_confidence
    return key_confidence(target, key_stats.mean_time_ns) * accuracy_of(key_stats)


def compute_unlocked(
    learn_order: Sequence[int],
    alphabet_size: float,
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    recover_keys: bool,
    threshold: float = 1.0,
) -> tuple[int, ...]:
    """The first `round(alphabet_size * len(learn_order))` keys are always
    unlocked; each further key in `learn_order` unlocks only once every
    currently-unlocked key meets `threshold`."""
    forced_count = round(alphabet_size * len(learn_order))
    unlocked = list(learn_order[:forced_count])
    for codepoint in learn_order[forced_count:]:
        if not all(confidence_of(k, stats, target, recover_keys) >= threshold for k in unlocked):
            break
        unlocked.append(codepoint)
    return tuple(unlocked)


def select_focus(
    unlocked: Sequence[int], stats: Mapping[int, KeyStats], target: float, recover_keys: bool,
) -> int:
    """The weakest unlocked key — the one a lesson should emphasize."""
    return min(unlocked, key=lambda cp: confidence_of(cp, stats, target, recover_keys))
