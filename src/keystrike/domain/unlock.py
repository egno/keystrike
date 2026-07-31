"""Key-unlock policy: which keys in `learn_order` are currently unlocked,
gated on per-key skill and attempt floor (§6 of PLAN.md). Bigrams affect focus
and lesson text, not which letters open next."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .confidence import MIN_CONFIDENCE_ATTEMPTS, attempts_of, skill_of
from .models import KeyStats


def _key_meets_unlock_threshold(
    codepoint: int,
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    threshold: float,
    min_attempts: int,
) -> bool:
    """Performance (skill) and evidence (attempts) — ramp affects display only."""
    key_stats = stats.get(codepoint)
    if key_stats is None:
        return False
    return (
        skill_of(codepoint, stats, target) >= threshold and attempts_of(key_stats) >= min_attempts
    )


def compute_unlocked(
    learn_order: Sequence[int],
    alphabet_size: int,
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    threshold: float = 1.0,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
) -> tuple[int, ...]:
    """The first `alphabet_size` keys are always unlocked; each further key in
    `learn_order` unlocks only once every currently-unlocked key meets skill
    ``threshold`` with at least ``min_attempts`` presses in window."""
    forced_count = min(alphabet_size, len(learn_order))
    unlocked = list(learn_order[:forced_count])
    for codepoint in learn_order[forced_count:]:
        if not all(
            _key_meets_unlock_threshold(
                k,
                stats,
                target,
                threshold=threshold,
                min_attempts=min_attempts,
            )
            for k in unlocked
        ):
            break
        unlocked.append(codepoint)
    return tuple(unlocked)
