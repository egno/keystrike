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


def confidence_of(codepoint: int, stats: Mapping[int, KeyStats], target: float) -> float:
    """Live confidence for one key, recomputed from the current target so a
    stale historical best can't vouch for a key that isn't actually being
    typed accurately/quickly right now (Keybr gates unlock on clearing
    thresholds "on the current set"; see docs/research/typing-pedagogy.md).
    0.0 for a never-practiced key.

    Speed confidence is scaled by accuracy so a key typed fast but frequently
    wrong doesn't read as mastered (accuracy-first: see docs/research/typing-pedagogy.md).
    """
    key_stats = stats.get(codepoint)
    if key_stats is None:
        return 0.0
    return key_confidence(target, key_stats.mean_time_ns) * accuracy_of(key_stats)


def compute_unlocked(
    learn_order: Sequence[int],
    alphabet_size: int,
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    threshold: float = 1.0,
) -> tuple[int, ...]:
    """The first `alphabet_size` keys are always unlocked; each further key in
    `learn_order` unlocks only once every currently-unlocked key meets
    `threshold`."""
    forced_count = min(alphabet_size, len(learn_order))
    unlocked = list(learn_order[:forced_count])
    for codepoint in learn_order[forced_count:]:
        if not all(confidence_of(k, stats, target) >= threshold for k in unlocked):
            break
        unlocked.append(codepoint)
    return tuple(unlocked)


def practice_weight(confidence: float, *, max_bias: float = 3.0) -> float:
    """Sampling weight for practice-text generation: a weak key (confidence 0)
    gets `1 + max_bias` the weight of a mastered key (confidence >= 1.0), so
    generated text is deliberately concentrated on weak keys rather than
    treating every unlocked key as equally likely to appear (see "Deliberate
    practice targeting weak points" in docs/research/typing-pedagogy.md).
    Capped at confidence 1.0 so an already-fast key doesn't get pushed below
    baseline weight just for being unusually fast."""
    return 1.0 + max_bias * (1.0 - min(confidence, 1.0))


def select_focus(unlocked: Sequence[int], stats: Mapping[int, KeyStats], target: float) -> int:
    """The weakest unlocked key — the one a lesson should emphasize."""
    return min(unlocked, key=lambda cp: confidence_of(cp, stats, target))
