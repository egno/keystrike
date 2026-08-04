# Confidence tuning

Keystrike's adaptive engine uses per-key **skill** (min(speed, accuracy) without
attempt ramp) plus an attempt floor to decide which keys unlock, and **confidence**
(skill scaled by how much you've practiced) for focus, HUD labels, and heatmap
coloring. Settings on this page control how aggressively the engine trusts your
recent performance and how strongly it biases lesson text toward the current
focus key or bigram.

Edit `{config_dir}/settings.toml` directly (see [Git sync](Git-sync) for the
path on your OS). These fields are **not** on the Settings screen — saving
layout, speed, or other UI settings will not change them.

## Settings

| Setting | `settings.toml` key | Default | What it does |
| --- | --- | --- | --- |
| Confidence session window | `confidence_session_window` | `10` | How many recent sessions are replayed into rolling per-key stats used for skill, unlocks, focus, and the heatmap. |
| Min key attempts | `min_confidence_attempts` | `10` | Minimum presses on a key before its confidence reaches full weight. Below this, confidence ramps linearly (fewer attempts → lower score). |
| Min bigram attempts | `min_transition_confidence_attempts` | `4` | Same ramp for letter-pair (transition) confidence. Default is lower because bigrams are practiced less often than single keys. |
| Focus char boost | `focus_char_boost` | `3.0` | Multiplier on the focus key's char weight when building lesson sampling weights. |
| Focus word boost | `focus_word_boost` | `3.0` | Extra multiplier on dictionary/Markov words that contain the focus character. |
| Focus bigram word boost | `focus_bigram_word_boost` | `4.0` | Extra multiplier on words containing the focus letter pair (when transition focus is active). |
| Focus transition boost | `focus_transition_boost` | `4.0` | Multiplier on the focus bigram's transition weight. |
| Focus weak extra boost | `focus_weak_extra_boost` | `1.5` | Additional multiplier when focus confidence is below 1.0 (weak key or weak transition). |
| Lesson word count | `lesson_word_count` | `12` | Words generated per practice lesson. |
| Focus word min fraction | `focus_word_min_fraction` | `0.6` | When focus is weak, at least this fraction of lesson words must match the focus key or bigram (ceiling). |
| Max word repeats | `max_word_repeats` | `2` | Maximum times the same word may appear in one generated lesson. |
| Generated word min length | `generated_word_min_len` | `2` | Minimum length for Markov-generated words (dictionary import still filters 3–10). |
| Generated word max length | `generated_word_max_len` | `4` | Maximum length for Markov-generated words. |

Valid ranges: window and both attempt floors are **1–100**. Boost multipliers should be **≥ 1.0**. `lesson_word_count` should be **≥ 1**. `focus_word_min_fraction` should be in **(0.0, 1.0]**. `max_word_repeats` should be **≥ 1**. `generated_word_min_len` and `generated_word_max_len` should be **≥ 1** with min ≤ max (invalid pairs are clamped at lesson build time).

Confidence uses **min(speed, accuracy)**, not their product: a key must be both
fast enough and accurate enough to read as mastered. Speed is `target_ms /
actual_ms`; accuracy is correct attempts ÷ total attempts.

Confidence uses **min(speed, accuracy)**, not their product: a key must be both
fast enough and accurate enough to read as mastered. Speed is `target_ms /
actual_ms`; accuracy is correct attempts ÷ total attempts.

Example (defaults shown):

```toml
confidence_session_window = 10
min_confidence_attempts = 10
min_transition_confidence_attempts = 4
focus_char_boost = 3.0
focus_word_boost = 3.0
focus_bigram_word_boost = 4.0
focus_transition_boost = 4.0
focus_weak_extra_boost = 1.5
lesson_word_count = 12
focus_word_min_fraction = 0.6
max_word_repeats = 2
generated_word_min_len = 2
generated_word_max_len = 4
```

## What each setting affects

**Session window** — Confidence is computed from aggregates over your last *N*
sessions (per layout), not your entire history. Within that window, **recent
sessions count more** than older ones (exponential decay, default 0.7 per step
back), so a bad or good last session moves confidence faster than the flat
average of all window sessions. A longer window smooths noise but reacts slowly;
a shorter window tracks recent form but can under-sample rare keys and block
unlocks until those keys appear often enough in recent drills.

**Min key attempts** — Prevents a lucky fast streak from reading as mastery.
Until you've pressed a key at least this many times (within the windowed
stats), its confidence is scaled down. Higher values mean slower unlocks and
more conservative focus selection; `1` effectively disables the ramp.

**Min bigram attempts** — Same idea for prev→next letter pairs. Transition
focus and bigram-weighted lesson text use this floor. Keeping it lower than the
key floor (default 4 vs 10) matches how sparse bigram data is in normal
practice.

## Unlocks and focus

The first **N** keys in layout `learn_order` are always unlocked, where **N** is
**Letters unlocked up front** in Settings (`alphabet_size`; see
[README — Settings](https://github.com/egno/keystrike#settings)). Each further
key in `learn_order` unlocks only when **every** currently unlocked key meets the
skill threshold (default 1.0: min(speed, accuracy) without attempt ramp) **and**
has at least `min_confidence_attempts` presses in the session window. Ramped
confidence still drives HUD labels (`cal` vs `wk`) and focus weighting.

Beyond solo-key mastery, the most-recently-unlocked key's bigrams with its
peers also gate the next key: it needs at least one measured cross-key pair,
and its single *weakest* measured pair must clear `transition_threshold`
(`domain.unlock.compute_unlocked`'s `transitions` argument, wired from
`build_lesson`/`session_use_cases` via `newest_key_clears_transition_gate`).
This is deliberately bounded to one pair, not every peer combination, so the
bar doesn't grow with alphabet depth — and an untouched peer pair never
counts against it, only pairs that have actually been typed at least once.
A `transition_stall_attempts_cap` (`domain.unlock.default_transition_stall_attempts_cap`,
3× the transition calibration floor by default) releases a specific pair
that's been drilled past the cap without clearing threshold, so one stubborn
bigram can't block progression forever.

**Focus selection** is letter-first: while any unlocked key is below performance
skill (`blocks_transition_focus`), the lesson emphasizes the weakest unlocked
**key** (by ramped confidence, with review urgency). Transition (bigram) focus
activates when every unlocked key meets the skill threshold (speed and accuracy
without the attempt ramp), even if some keys are still calibrating on press
count; then the weakest measured cross-key bigram among unlocked keys drives
focus — unless the most-recently-practiced unlocked key has no measured
transitions of its own yet, in which case its weakest unmeasured pair takes
priority instead (`newest_key_unmeasured_pairs`), so a freshly-mastered key
gets bigram focus before older, merely-weak measured pairs. This unmeasured-pair
fallback is what fires when no transition data exists at all, as long as the
newest practiced key has a practiced peer to pair with — only when it has no
such peer (or nothing's been practiced yet) does focus fall further back to
the weakest key.

### Transition stats

Same-key / double-letter bigrams are never aggregated into session stats, stored
in the stats cache, or used in unlock checks — including the transition gate
above. Only cross-key pairs (e.g. `th`, `he`) participate in transition
confidence, focus selection, the unlock gate, and bigram-weighted lesson
text. Transition sampling weights apply to **measured** unlocked
cross-key bigrams; other unmeasured pairs keep the generator default (1.0) —
except pairs between the most-recently-*practiced* unlocked key and other
already-practiced unlocked keys, which get an explicit zero-attempt weight
(`transition_practice_weight(0.0, ...) * coverage_deficit_factor(0, ...)`,
12.0 at default settings) instead of 1.0, so a newly-mastered key's bigrams
show up in generated text right away rather than waiting on chance. This
stops as soon as any of that key's pairs gets measured data — see
`domain.focus.newest_key_unmeasured_pairs`, the single source of truth for
this "newest key" candidate set shared by focus selection and lesson
weighting.

## Tradeoffs

- **Window too short** — Rare keys in your unlocked set may never accumulate
  enough samples in the window; unlocks stall and the heatmap looks empty for
  those keys even if you've typed them in older sessions.
- **Window too long** — Stale mistakes and old slow timings linger; focus and
  unlocks lag behind your current ability.
- **Min attempts too low** — One good session can inflate confidence and unlock
  the next key before accuracy and speed are stable (Keybr-style progression
  expects both).
- **Min attempts too high** — Progress feels grindy; focus stays on keys you've
  already typed many times.
- **Transition floor** — Raise it if bigram focus switches too eagerly on thin
  data; lower it if weak pairs never get targeted.
- **Coverage deficit** — Lesson sampling multiplies char (and transition)
  weights by a session-scale boost when in-window attempts are below
  `min_confidence_attempts` (peaking at zero attempts). This is separate
  from performance weakness (`practice_weight`) and day-scale review urgency;
  it helps large unlocked sets get enough window samples without widening the
  session window. There is no settings knob — the boost is fixed in code
  (`coverage_deficit_factor` in `domain/focus.py`).

## Large alphabet (40+ keys)

With the default session window (`10`) and lesson length (`12`), each practice
session only touches a fraction of a 40–50 key unlocked set. Keys can drop out
of the rolling window or stay below `min_confidence_attempts`, which stalls
the next unlock and leaves heatmap gaps even when you are typing well.
**Coverage-deficit weighting** (above) addresses much of this automatically;
defaults may suffice once you have been practicing for a while.

If unlocks still feel stuck or the heatmap looks sparse, widen the window and
lesson manually in `{config_dir}/settings.toml` (these fields are **not** on
the Settings screen):

```toml
confidence_session_window = 18
lesson_word_count = 20
```

Starting points for 40–50 unlocked keys:

| Knob | Default | Large-alphabet starting point |
| --- | --- | --- |
| `confidence_session_window` | `10` | `15`–`20` |
| `lesson_word_count` | `12` | `18`–`24` |

**Tradeoffs:**

- **Wider window** — More keys stay represented in rolling stats, but
  confidence reacts more slowly to recent form (see [window too long](#tradeoffs)
  above).
- **Longer lessons** — More keys sampled per session, but each drill takes
  longer.
- **`focus_word_min_fraction`** — Lower slightly (e.g. `0.5`) if strict focus
  quotas make generated text repetitive at large N; raising it keeps weak-focus
  keys more prominent at the cost of variety.

After edits, run a practice session or open Stats so aggregates rebuild. See
[Focus states](Focus-States) for how key vs transition focus interacts with
calibration at scale.

## Related docs

- [Focus states](Focus-States) — compact HUD labels and practice-screen metrics.
- [Word lists](Word-Lists) — optional dictionary drills (same confidence engine).
- [Git sync](Git-sync) — settings (including these fields) sync with your repo.
