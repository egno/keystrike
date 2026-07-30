"""Pure confidence math for keybr-style progression.

Used by the M2 Stats heatmap and the M3 adaptive engine's key-unlock / focus-
selection logic (§6 of PLAN.md).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import KeyStats, TransitionStats

_SECONDS_PER_DAY = 86_400.0
_REVIEW_URGENCY_FULL_DAYS = 3.0
# Confidence, unlocks, focus, and heatmap use aggregates from this many sessions.
CONFIDENCE_SESSION_WINDOW = 10
# Exponential decay per session step when merging windowed stats (most recent = 1.0).
# ponytail: fixed constant; upgrade to settings if users want tunable recency bias.
SESSION_RECENCY_DECAY = 0.7
# Raw min(speed, accuracy) confidence ramps linearly until this many attempts per key.
MIN_CONFIDENCE_ATTEMPTS = 10
# Bigrams are sparser — lower floor so transition focus reflects measured weakness.
MIN_TRANSITION_CONFIDENCE_ATTEMPTS = 4
# Confidence scores are rounded before thresholds, focus, heatmap, and UI.
CONFIDENCE_DECIMALS = 2
# Defaults for Settings and generator call sites; tunable via settings.toml.
FOCUS_CHAR_BOOST = 3.0
FOCUS_WORD_BOOST = 3.0
FOCUS_BIGRAM_WORD_BOOST = 4.0
FOCUS_TRANSITION_BOOST = 4.0
FOCUS_WEAK_EXTRA_BOOST = 1.5


def round_confidence(value: float) -> float:
    """Round confidence for comparisons and display so they stay aligned."""
    return round(value, CONFIDENCE_DECIMALS)


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


def key_attempts(key_stats: KeyStats) -> int:
    return key_stats.attempt_count


def transition_attempts(transition_stats: TransitionStats) -> int:
    return transition_stats.attempt_count


def is_same_key_transition(prev_cp: int, next_cp: int) -> bool:
    """Same physical key twice (e.g. ee, ss) — excluded from transition analysis."""
    return prev_cp == next_cp


def confidence_sample_factor(
    attempts: int,
    *,
    minimum: int = MIN_CONFIDENCE_ATTEMPTS,
) -> float:
    """Ramp toward full confidence as attempts accumulate (ponytail: linear;
    upgrade to Wilson interval or similar if sparse keys still feel jumpy)."""
    if minimum <= 0:
        return 1.0
    if attempts <= 0:
        return 0.0
    return min(1.0, attempts / minimum)


def confidence_of(
    codepoint: int,
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
) -> float:
    """Live confidence for one key from aggregated stats (typically the last
    `CONFIDENCE_SESSION_WINDOW` sessions, recency-weighted), recomputed from the
    current target.
    0.0 for a never-practiced key.

    Confidence is min(speed, accuracy) so fast-but-sloppy or slow-but-accurate
    cannot read as mastered. Both must clear the bar. Scaled down until
    `MIN_CONFIDENCE_ATTEMPTS` presses on the key so a lucky first session
    can't read as mastered (see docs/research/typing-pedagogy.md).
    """
    key_stats = stats.get(codepoint)
    if key_stats is None:
        return 0.0
    raw = min(
        key_confidence(target, key_stats.mean_time_ns),
        accuracy_of(key_stats),
    )
    return round_confidence(
        raw * confidence_sample_factor(key_attempts(key_stats), minimum=min_attempts),
    )


def _measured_transitions_meet_threshold(
    unlocked: Sequence[int],
    transitions: Mapping[str, TransitionStats],
    target: float,
    *,
    threshold: float,
    min_attempts: int,
) -> bool:
    """True when every measured bigram among unlocked keys meets threshold."""
    for prev in unlocked:
        for nxt in unlocked:
            if is_same_key_transition(prev, nxt):
                continue
            if chr(prev) + chr(nxt) not in transitions:
                continue
            if (
                transition_confidence_of(
                    prev, nxt, transitions, target, min_attempts=min_attempts,
                )
                < threshold
            ):
                return False
    return True


def compute_unlocked(
    learn_order: Sequence[int],
    alphabet_size: int,
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    threshold: float = 1.0,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
    transitions: Mapping[str, TransitionStats] | None = None,
    min_transition_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
) -> tuple[int, ...]:
    """The first `alphabet_size` keys are always unlocked; each further key in
    `learn_order` unlocks only once every currently-unlocked key and every
    measured bigram among them meets `threshold`."""
    forced_count = min(alphabet_size, len(learn_order))
    unlocked = list(learn_order[:forced_count])
    for codepoint in learn_order[forced_count:]:
        if not all(
            confidence_of(k, stats, target, min_attempts=min_attempts) >= threshold
            for k in unlocked
        ):
            break
        if (
            transitions is not None
            and not _measured_transitions_meet_threshold(
                unlocked,
                transitions,
                target,
                threshold=threshold,
                min_attempts=min_transition_attempts,
            )
        ):
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
    *,
    min_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
) -> float:
    """Live confidence for one bigram transition. 0.0 when never practiced."""
    transition_stats = stats.get(chr(prev_cp) + chr(next_cp))
    if transition_stats is None:
        return 0.0
    raw = min(
        transition_confidence(target, transition_stats.mean_time_ns),
        transition_accuracy_of(transition_stats),
    )
    return round_confidence(
        raw * confidence_sample_factor(
            transition_attempts(transition_stats),
            minimum=min_attempts,
        ),
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
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
) -> float:
    key_stats = stats.get(codepoint)
    urgency = review_urgency(key_stats.last_seen if key_stats else 0.0, now)
    return (
        confidence_of(codepoint, stats, target, min_attempts=min_attempts)
        * (1.0 - review_penalty * urgency)
    )


def has_weak_unlocked_key(
    unlocked: Sequence[int],
    stats: Mapping[int, KeyStats],
    target: float,
    *,
    threshold: float = 1.0,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
) -> bool:
    """True when any unlocked key is below mastery threshold."""
    return any(
        confidence_of(cp, stats, target, min_attempts=min_attempts) < threshold
        for cp in unlocked
    )


def select_focus(
    unlocked: Sequence[int],
    stats: Mapping[int, KeyStats],
    target: float,
    now: float,
    *,
    review_penalty: float = 0.5,
    min_attempts: int = MIN_CONFIDENCE_ATTEMPTS,
) -> int:
    """The unlocked key a lesson should emphasize — weakest by confidence, but
    stale keys are treated as weaker so high-confidence keys due for review
    still surface (SlimStampen-style spacing; see typing-pedagogy.md)."""
    return min(
        unlocked,
        key=lambda cp: _focus_score(
            cp, stats, target, now, review_penalty=review_penalty, min_attempts=min_attempts,
        ),
    )


def _transition_focus_score(
    prev_cp: int,
    next_cp: int,
    stats: Mapping[str, TransitionStats],
    target: float,
    now: float,
    *,
    review_penalty: float,
    min_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
) -> float:
    key = chr(prev_cp) + chr(next_cp)
    t_stats = stats.get(key)
    urgency = review_urgency(t_stats.last_seen if t_stats else 0.0, now)
    confidence = transition_confidence_of(
        prev_cp, next_cp, stats, target, min_attempts=min_attempts,
    )
    return confidence * (1.0 - review_penalty * urgency)


def select_focus_transition(
    unlocked: Sequence[int],
    transitions: Mapping[str, TransitionStats],
    target: float,
    now: float,
    *,
    review_penalty: float = 0.5,
    min_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS,
) -> tuple[int, int] | None:
    """Weakest unlocked bigram by transition confidence; None when no transition data."""
    if not transitions:
        return None
    pairs = [
        (prev, nxt)
        for prev in unlocked
        for nxt in unlocked
        if not is_same_key_transition(prev, nxt)
        and chr(prev) + chr(nxt) in transitions
    ]
    if not pairs:
        return None
    return min(
        pairs,
        key=lambda p: _transition_focus_score(
            p[0],
            p[1],
            transitions,
            target,
            now,
            review_penalty=review_penalty,
            min_attempts=min_attempts,
        ),
    )


def focus_key_from_transition(_prev_cp: int, next_cp: int) -> int:
    """Endpoint key to mark as lesson focus for a transition-driven bigram."""
    return next_cp
