"""Pure confidence math for keybr-style progression.

Used by the M2 Stats heatmap and the M3 adaptive engine's key-unlock / focus-
selection logic (§6 of PLAN.md).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import KeyStats, TransitionStats

_SECONDS_PER_DAY = 86_400.0
_REVIEW_URGENCY_FULL_DAYS = 3.0


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


def review_urgency(last_seen: float, now: float) -> float:
    """How urgently a key needs re-testing before forgetting (0.0-1.0).

    ponytail: fixed day-scale ramp, not per-key ACT-R decay; upgrade to
    SlimStampen-style individual half-life once we have enough per-key history.
    """
    if last_seen <= 0 or now <= last_seen:
        return 0.0
    elapsed_days = (now - last_seen) / _SECONDS_PER_DAY
    if elapsed_days < 1.0:
        return 0.0
    if elapsed_days >= _REVIEW_URGENCY_FULL_DAYS:
        return 1.0
    return (elapsed_days - 1.0) / 2.0


def transition_accuracy_of(transition_stats: TransitionStats) -> float:
    total = transition_stats.samples + transition_stats.error_count
    return transition_stats.samples / total if total > 0 else 0.0


def transition_confidence(target_ms_per_char: float, mean_time_ns: float) -> float:
    if mean_time_ns <= 0:
        return 0.0
    return key_confidence(target_ms_per_char, mean_time_ns)


def transition_confidence_of(
    prev_cp: int,
    next_cp: int,
    stats: Mapping[str, TransitionStats],
    target: float,
) -> float:
    """Live confidence for one bigram transition. 0.0 when never practiced."""
    transition_stats = stats.get(chr(prev_cp) + chr(next_cp))
    if transition_stats is None:
        return 0.0
    return (
        transition_confidence(target, transition_stats.mean_time_ns)
        * transition_accuracy_of(transition_stats)
    )


def transition_practice_weight(
    confidence: float,
    *,
    max_bias: float = 3.0,
    urgency: float = 0.0,
    review_bias: float = 1.0,
) -> float:
    """Sampling weight for a prev→next pair — mirrors `practice_weight`."""
    return practice_weight(
        confidence,
        max_bias=max_bias,
        urgency=urgency,
        review_bias=review_bias,
    )


def practice_weight(
    confidence: float,
    *,
    max_bias: float = 3.0,
    urgency: float = 0.0,
    review_bias: float = 1.0,
) -> float:
    """Sampling weight for practice-text generation: a weak key (confidence 0)
    gets `1 + max_bias` the weight of a mastered key (confidence >= 1.0), so
    generated text is deliberately concentrated on weak keys rather than
    treating every unlocked key as equally likely to appear (see "Deliberate
    practice targeting weak points" in docs/research/typing-pedagogy.md).
    Capped at confidence 1.0 so an already-fast key doesn't get pushed below
    baseline weight just for being unusually fast.

    `urgency` (from `review_urgency`) multiplies weight so stale-but-mastered
    keys still appear in generated text."""
    base = 1.0 + max_bias * (1.0 - min(confidence, 1.0))
    return base * (1.0 + review_bias * urgency)


def _focus_score(
    codepoint: int,
    stats: Mapping[int, KeyStats],
    target: float,
    now: float,
    *,
    review_penalty: float,
) -> float:
    key_stats = stats.get(codepoint)
    urgency = review_urgency(key_stats.last_seen if key_stats else 0.0, now)
    return confidence_of(codepoint, stats, target) * (1.0 - review_penalty * urgency)


def select_focus(
    unlocked: Sequence[int],
    stats: Mapping[int, KeyStats],
    target: float,
    now: float,
    *,
    review_penalty: float = 0.5,
) -> int:
    """The unlocked key a lesson should emphasize — weakest by confidence, but
    stale keys are treated as weaker so high-confidence keys due for review
    still surface (SlimStampen-style spacing; see typing-pedagogy.md)."""
    return min(
        unlocked,
        key=lambda cp: _focus_score(cp, stats, target, now, review_penalty=review_penalty),
    )


def _transition_focus_score(
    prev_cp: int,
    next_cp: int,
    stats: Mapping[str, TransitionStats],
    target: float,
    now: float,
    *,
    review_penalty: float,
) -> float:
    key = chr(prev_cp) + chr(next_cp)
    t_stats = stats.get(key)
    urgency = review_urgency(t_stats.last_seen if t_stats else 0.0, now)
    confidence = transition_confidence_of(prev_cp, next_cp, stats, target)
    return confidence * (1.0 - review_penalty * urgency)


def select_focus_transition(
    unlocked: Sequence[int],
    transitions: Mapping[str, TransitionStats],
    target: float,
    now: float,
    *,
    review_penalty: float = 0.5,
) -> tuple[int, int] | None:
    """Weakest unlocked bigram by transition confidence; None when no transition data."""
    if not transitions:
        return None
    pairs = [(prev, nxt) for prev in unlocked for nxt in unlocked]
    if not pairs:
        return None
    return min(
        pairs,
        key=lambda p: _transition_focus_score(
            p[0], p[1], transitions, target, now, review_penalty=review_penalty,
        ),
    )


def focus_key_from_transition(_prev_cp: int, next_cp: int) -> int:
    """Endpoint key to mark as lesson focus for a transition-driven bigram."""
    return next_cp
