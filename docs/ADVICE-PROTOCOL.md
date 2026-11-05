# Advice protocol v2

Status: **implemented** in 2.3 (Phase A of the review, §1b). Builds on `ADVISOR-PLUGINS.md`. That document defines how
advisors plug in. This one defines **what they say** and **how the core uses
it** to prepare the next session. `PLUGIN_API_VERSION` is 2.

## 1. Why

In v1 an advice had four loose fields: `focus_key`, `focus_pair`,
`emphasis_keys`, `rest_keys`. The core gave each a fixed effect. I read the
raw keystroke files on one device (6 files, 546 positions, 18 with an error,
layout `colemak_dh`) and checked the digest of the last 10 sessions. The
sample is small, so read the numbers as hints.

| # | Finding | Evidence | Gap in v1 |
| --- | --- | --- | --- |
| 1 | Confusions are neighbouring keys. | `r→s`, `s→t`, `n→m`, `i→o`: same hand, same home row. | Advice spoke about letters, not key positions. |
| 2 | Every reported confusion is thin. | Each has 2 events in 77–123 presses. "You often type i for e" rested on 2 events. | Advice carried no evidence. Two events looked like twenty. |
| 3 | Speed is a median under the goal with a slow tail (see §1b). | 10 raw sessions, 974 positions, goal 290 ms: median press 257 ms, mean 297 ms. A few slow presses pull the mean up. Per-key means mislead (`n`: median 208 ms, mean 280 ms). The press after a space looks fast (median 168 ms), because the space absorbs the pause to plan the next word: `m` has a median of 291 ms over all intervals, but 354 ms when the previous key is not a space. | v1 and the first v2 judged speed on the mean, and counted every correct press of a slow key as a "slow" event ("529 of 551"). |
| 4 | The emphasis list was too big to matter. | `e i o n m` is 5 of 9 unlocked keys at ×1.5. Weights are relative, so the effect mostly cancels. | No budget. |
| 5 | The windows differ. | The digest covers 10 sessions. Only 6 have raw files. | The context did not say which sessions each part covers. |

### A correction: errors are counted per position

The cursor does **not** advance on an error. The retry after a wrong key
has the same target. So 28 wrong keystrokes were only 18 error *positions*,
and one stumble could be three wrong keys in a row (`t` typed as `g`, `i`,
`o`). The first draft of this design counted keystrokes, and it found
"doubled letters cause 31% of errors" (10 of 47 `ee`/`nn`/`tt` pairs).
**That was an artifact.** 28 of the 47 "doubled" pairs were retries. The 19
real doubled letters had 0 errors. So:

- There is **no `REPEAT` kind**. The data does not support it.
- `keystroke_insights` now counts one attempt and at most one error per
  position (retries are skipped). Before, a three-key stumble counted as three
  mistypes.
- The engine's stored tallies (`tally_session`) still count every keystroke.
  That is its own convention and is not changed here.

### 1b. Corrections from the review

A second analysis on 10 raw sessions proposed more changes. Two independent
reviews checked it against the raw files. These claims were **wrong or
weaker than stated**, and the design does not use them:

- **Space is 12% of timed presses, not 22%.** 110 of 943 correct timed
  presses. The first count included transitions to or from a space. Its
  median (359 ms) is stable in every session.
- **The hand-switch gap is mostly tail.** Means 315 ms against 274 ms, but
  the medians are similar (256 ms against 242 ms, letters only). Every space
  press is also recorded as the left hand. This is not a property of hand
  switching.
- **The slowdown after an error is not significant.** 63 presses, mean
  341 ms. Random samples of 63 correct presses give a 95% range of
  256–344 ms. The windows also overlap.
- **The "tail" threshold of 2 x the goal is arbitrary.** Over 1.5 x the goal,
  14% of presses carry 78% of the excess; over 3 x, 1.6% carry 19%. The share
  depends on the cut. "56% of the excess time" is also not time that can be
  recovered.
- **A slow transition cannot be told from a slow word** with a small
  alphabet (10 keys): each pair comes from a few words.
- **Many comparisons, one learner, 10 sessions.** Seven findings over dozens
  of keys and pairs. Read every number as a hint.

What holds: the median press is under the goal and the mean is pulled up by
a tail; intervals after a space must be excluded; most confusions are thin.
So Phase A changes how the evidence is measured and shown (§3b, §5). The new
interventions wait (§13).

## 2. Goals and non-goals

Goals:

1. **Say why.** Every recommendation has a reason and evidence. The panel
   shows both.
2. **Weak evidence has weak effect.** The core scales the effect by the
   evidence, not by how sure the advisor sounds.
3. **A real effect when advice is strong.** A budget stops advice from
   diluting itself.
4. **Keep the guarantees of v1.** Advice never delays an unlock, never names
   a locked key, never moves weights out of bounds. The core enforces this.

Non-goals: a `pace` kind, a `REPEAT` kind (§1), pooled evidence for a class
of keys (§5), merging several advisors, and a compatibility layer for v1
plugins. The loader rejects them with a clear message. A `drill_pair` kind
and text-only hints are deferred (§13).

## 3. Types (`domain/advice.py`)

```python
class Reason(StrEnum):
    ACCURACY, SPEED, CONFUSION, MASTERED

class Kind(StrEnum):
    FOCUS        # keys = (key,)
    FOCUS_PAIR   # keys = (previous, next)
    EMPHASIZE    # keys = (key,): practice it more
    EASE         # keys = (key,): practice it less; reason MASTERED
    CONTRAST     # keys = (target, typed)

@dataclass(frozen=True, slots=True)
class Evidence:
    events: int          # errors, slow presses, mistypes; for MASTERED: correct presses
    opportunities: int   # presses that could have shown it
    sessions: int = 0    # sessions the numbers cover
    event_sessions: int | None = None  # sessions the events come from (None = unknown)

@dataclass(frozen=True, slots=True)
class Recommendation:
    kind: Kind
    keys: tuple[int, ...]
    reason: Reason
    strength: float = 0.5        # 0..1, the advisor's priority
    evidence: Evidence = NO_EVIDENCE
    applied: float = 0.0         # effective strength; set by the core

@dataclass(frozen=True, slots=True)
class LessonAdvice:
    source: str = ""             # set by the runner
    summary: str = ""
    recommendations: tuple[Recommendation, ...] = ()
    created_at: float = 0.0      # set by the runner
    error: str = ""
```

**One key per recommendation.** `EMPHASIZE` and `EASE` carry exactly one
key. An advisor that wants three keys emphasized returns three
recommendations, each with **the key's own evidence**. Evidence pooled over
a class of keys (for example all keys of one finger) is not allowed: it
would let thin evidence on each key clear the floor together.

**No `note`.** `Recommendation.note` is removed. It went stale when the
budget trimmed keys, and the panel did not show it. The panel builds each
line from kind, keys, reason and evidence, and the core writes the summary
(§5).

`AdvisorContext` gains `layout_keys` (row, column, hand and finger of each
key), `coverage` (`digest_sessions`, `stream_sessions`), and `session_weights`
(the recency weight of each session, newest first; see §3a). `plugin_api` adds
`neighbors(layout_keys, key)`: keys on the same hand within one row and one
column.

### 3a. Recency

Older sessions should count less. Session `i` (0 = the newest) weighs
`decay ** i`. The default decay is **0.85**: the weight halves after about 4
sessions, and the 10th session weighs about 0.23. A decay of 1.0 weighs every
session the same (the behaviour before recency). The value lives in
`advisors.toml` as `recency_decay`, a number above 0 and at most 1; anything
else means the default.

The **exact counts stay the evidence.** Recency only decides what to rank
first and how strong a recommendation is:

| Part of the context | Exact (evidence) | Recency-weighted |
| --- | --- | --- |
| Per-key tallies | `digest.keys` | `digest.recent` (`RecentTally`, floats: `mean_ms`, `error_rate`) |
| Mistypes | `Confusion.count`, `.sessions` (streams it occurs in), `.newest_half` (its events in the newer half of the streams, the first `ceil(n / 2)`) | `Confusion.recent_count`, and `Confusion.recency` (the recent share, 0..1) |
| Timing | `KeyTiming.presses`, `.over_goal`, `.tail`, `.median_ms` | `KeyTiming.recent_median_ms` |
| Per-finger errors | `FingerErrors.errors`, `.attempts` | `.recent_errors`, `.recent_attempts`, `.recent_error_rate` |
| Which sessions | `sessions` | `session_weights` |

Recency fields are `None` when there is no recency information. They then mean
"full weight", so a plain context behaves like the equal-weight case.
`course` (unlocked keys, confidence, goal) comes from the latest session, as
before.

### 3b. Timing (`domain/timing.py`)

The core times each key from the raw streams and puts the result in
`digest.timing` (one `KeyTiming` per unlocked key) and `digest.space` (the
space press, on its own; lessons cannot target it). Both are empty without
streams.

```python
@dataclass(frozen=True, slots=True)
class KeyTiming:
    presses: int             # eligible intervals
    over_goal: int           # intervals above the goal
    tail: int                # intervals above 2 x the goal (TAIL_FACTOR)
    median_ms: float         # exact median over the window
    recent_median_ms: float  # weighted median: session i weighs decay ** i
    sessions: int            # streams that gave at least one interval
```

An interval is the time from the previous position's first attempt to this
position's first attempt. Only **eligible** intervals count:

1. This first attempt is correct.
2. It is not the first press of the session.
3. It is not the first press after an error: the previous position's first
   attempt was correct. (The retries and the recovery sit in that interval.)
4. The previous target is not a space. The space absorbs the pause for
   planning the next word, so the next key looks fast.
5. The target is not a space. The space is reported in `digest.space`.
6. The interval is at least 30 ms (`MIN_INTERVAL_MS`). Shorter is key
   rollover.

`digest.space` uses rules 1–3 and 6. With a goal of 0, `over_goal` and
`tail` are 0. The counts are exact (evidence); `recent_median_ms` uses the
same session weights as the rest of the context (§3a) and is for
classification. The 2 x cut of `tail` is arbitrary (§1b): no rule depends on
it. `plugin_api` exports `KeyTiming`, `eligible_intervals`, `key_timings` and
`weighted_median`.

`MASTERED` is a fourth reason that the first draft did not have. `EASE` needs
a reason, and "fast and accurate" is not `ACCURACY` or `SPEED`.

## 4. What each kind means

| Kind | Effect on the next lesson | Never |
| --- | --- | --- |
| `FOCUS`, `FOCUS_PAIR` | Moves the focus, only inside `FocusChoices` (v1 rule). Pairs come first, strongest first. | Delays an unlock. |
| `EMPHASIZE` | Raises key weights. | Names a locked key. |
| `EASE` | Lowers key weights. | Eases the focus key, the newest key, or a key whose confidence is below 1.0. |
| `CONTRAST` | Boosts words that contain **both** keys and reserves some lesson words for them. | Changes the focus. |

## 5. Core rules (pure, in `domain/advice.py`)

`validate_advice(advice, course)` runs on every advice.

1. **Drop what is not allowed.** A locked key, the wrong arity (`FOCUS`,
   `EMPHASIZE` and `EASE` take one key; `FOCUS_PAIR` and `CONTRAST` two
   different keys), `EASE` without reason `MASTERED`, an `EASE` of the newest
   key or of a key with confidence below 1.0. A recommendation is dropped
   whole. Keys are never trimmed.
2. **Check the evidence.** It needs `events >= 2` and `opportunities >= 10`.
   For `EASE` the events are correct presses, so it needs only the
   opportunities and some events. A `CONTRAST` needs more: `events >= 3`
   (`CONTRAST_MIN_EVENTS`) seen in `event_sessions >= 2`
   (`CONTRAST_MIN_EVENT_SESSIONS`; unknown counts as 0). Three is a
   conservative guardrail, not a proof of a stable confusion. A
   recommendation with zero effective strength is dropped.
3. **Set `applied`.** `strength * min(1, events / 5)`. Five events give full
   weight. Two events give 40% of it.
4. **Apply the budget.** Per kind (`EMPHASIZE`, then `EASE`): keep only the
   strongest recommendation of each key, then the `ceil(unlocked / 3)`
   recommendations with the highest `applied`. With one key each, dropping a
   recommendation is the same as dropping a key, and the evidence stays true.
5. **Cap the lists.** At most 5 recommendations per kind, and 200 characters
   of summary.
6. **Write the summary.** Only when the advisor's own summary is empty (an
   LLM's free text stays), the core sets it with `render_summary` from the
   validated recommendations. A failed advice is not changed.

`render_summary` takes the strongest (by `applied`) non-`EASE`
recommendation with at least 3 events. Two events never lead:

| Kind | Summary |
| --- | --- |
| `CONTRAST` | You typed f instead of a 9 times in 90 presses — practice a and f. |
| `FOCUS` | s needs the most work: 4 errors in 40 presses. |
| `FOCUS_PAIR` | ns needs the most work: 4 errors in 30 presses. |
| `EMPHASIZE` (`SPEED`) | m is slower than your goal — it gets extra practice. |
| `EMPHASIZE` (`ACCURACY`) | r has more errors than the others — it gets extra practice. |

Without such a recommendation: when every recommendation is `EASE` (or
there are none), the summary is `ON_TRACK`, "On track — nothing needs extra
practice."; else (only weak evidence) it is empty. Keys are written with
`format_char`.

Validation is idempotent: `applied` is recomputed from `strength`, and a
rendered summary is kept.

`weigh_advice` maps `applied` to a factor:

```
EMPHASIZE: 1 + 0.5 * applied     # 1.0 .. 1.5
EASE:      1 - 0.3 * applied     # 1.0 .. 0.7
```

A key in several recommendations takes the factor farthest from 1.0. The
focus key and the newest key are never eased. `apply_focus_advice` reads the
strongest allowed `FOCUS` or `FOCUS_PAIR`.

## 6. Preparing the session

`BuildLesson` runs these steps:

1. Build the lesson progress and the focus (engine).
2. Apply `FOCUS` / `FOCUS_PAIR` inside `FocusChoices`.
3. Compute the engine weights.
4. Apply `EMPHASIZE` / `EASE` factors (`weigh_advice`).
5. Add word boosts for `CONTRAST` (`word_boosts`).
6. Generate the text.

Steps 4 and 5 run after the focus is final. Nothing here changes which keys
unlock.

A `CONTRAST (t, y)` becomes `WordBoost(needs_all={t, y}, factor=1+applied,
min_words)` in `LessonWeighting.word_boosts`. The generator multiplies a
word's weight by `factor` when the word matches (the same place where the
focus word boosts work). Then it reserves `min_words` words:
`min_words = min(round(applied * word_count / 5), 20% of the lesson)`. It
replaces only words that carry no focus, so the focus guarantees stay true.
It takes dictionary words first, then Markov words. When no word matches (a
small alphabet), the lesson stays as it is: a missing word is not an error.

`Lesson.advice_kinds` lists the kinds that shaped the lesson. A focus kind
counts only when the focus really moved. It goes to the session header as
`advice_kinds`, together with `advice_source`. It is written only when set,
so old rows read back unchanged.

## 7. Raw keystroke files

Each file starts with a header line (`session_id`, `layout`, `started_at`,
`ended_at`). The oldest files have none. The reader treats a missing header
as unknown, never as an error. The runner loads streams for the **same
sessions** as the digest and reports both counts in `Coverage`.

## 8. The rules advisor

Same ideas as v1, now with evidence and reasons:

- `FOCUS` (`ACCURACY`): the key with the highest *recent* shrunk error rate,
  if it is at least 8%. The evidence is the exact count.
- `CONTRAST` (`CONFUSION`): one per mistype with at least 3 events in at
  least 2 sessions, and at least 1 event in the newer half of the streams.
  (The only two contrasts that passed a plain floor of 3 on the review data
  had no event in the last 5 sessions.)
- `EMPHASIZE` (`SPEED`): one per key whose **recent median** of eligible
  intervals (§3b) is above 105% of the goal, with at least 20 presses from at
  least 2 sessions. The evidence is the over-goal intervals of the eligible
  intervals (`over_goal` of `presses`). There is no tail-count gate.
- `EMPHASIZE` (`ACCURACY`): one per key of the finger with a clearly higher
  error rate, each with the key's own errors and attempts. A key whose own
  evidence is too thin is left out.
- `EASE` (`MASTERED`): one per key with confidence at least 1.0, error rate
  under 2%, and a recent median at or below **95%** of the goal. Never the
  newest key, and never a key without timing.
- **Recency.** Rankings, speed and error rates use the recency-weighted
  numbers (§3a). A `CONTRAST` has `strength = 0.8 * recency`, so a mistype you
  stopped making fades while its exact count stays visible as evidence. A
  mastered key is eased only if its **recent** error rate is under 2%, so one
  new error stops the easing at once.
- **Margins.** Between 95% and 105% of the goal a key is neither emphasized
  nor eased, so advice does not flip from one session to the next when a key
  wobbles around the goal.
- **Only recommendations the core would keep are returned.** The advisor uses
  the core's own evidence bar (`effective_strength`), so it does not return
  advice that is dropped anyway.
- **No summary of its own.** The core writes it (§5).

On the first 6 raw sessions (§1), the advisor before Phase A gave four weak
`CONTRAST` recommendations (2 events each), a `SPEED` emphasis for `s` and
`m` judged on the mean, a weak `ACCURACY` emphasis for `r`, and an `EASE` for
`a`. With Phase A the two-event contrasts are gone, and speed is judged on
the recent median with the intervals after a space excluded. The sample
context behind `Ctrl+T` has timing too (the goal is 343 ms; `n` and `o` are
slower), so the test shows speed advice.

## 9. The LLM plugin

`keystrike-ai` (API version 2) keeps the same JSON reply. The plugin maps it:

- `focus_key` → `FOCUS`, `focus_pair` → `FOCUS_PAIR`, `emphasis_keys` →
  one `EMPHASIZE` per key, `rest_keys` → one `EASE` per key, each with the
  key's own evidence from the digest.
- The model's `summary` is kept as it is. The core writes a summary only when
  it is empty.
- **The evidence comes from the digest, not from the model.** A key that the
  model emphasizes but that has fewer than 2 errors has no evidence and the
  core drops it.
- **Speed uses the same rule as the rules advisor.** An emphasized key is a
  `SPEED` recommendation when its recency-weighted median is above 105% of the
  goal, from at least 20 clean presses in at least 2 sessions
  (`digest.timing`). Its evidence is the over-goal presses of the clean presses.
  Not on the mean: a few long pauses pull the mean up. Without timing (no raw
  streams) a key stays an `ACCURACY` recommendation; there is no guess from the
  mean.
- The prompt says how many sessions the tallies and the mistype data cover,
  and lists the speed per key (median of clean presses, goal, presses over the
  goal; slowest first).

The plugin does not use recency yet: it sends the exact numbers and gives its
recommendations fixed strengths. (The context carries `session_weights` and
`digest.recent` for a future version.)

The reply schema has no `contrast` list yet, so the plugin never sends
`CONTRAST`.

## 10. Migration

| Item | Change |
| --- | --- |
| `PLUGIN_API_VERSION` | 1 → 2. The loader rejects version 1 plugins with a clear message. |
| `LessonAdvice` | Four fields replaced by `recommendations`. |
| `advice.json` | Rows have `"version": 3`: no `note`, and the evidence list may have a fourth number, `event_sessions`. Rows of version 1 or 2 (and of the format before versions) are ignored, and the next advice replaces them. |
| `Recommendation.note` | Removed. The core renders the panel lines and the summary. |
| `EMPHASIZE`, `EASE` | Exactly one key. Other arities are dropped. |
| `AdviceDigest` | New `timing` and `space` (§3b). |
| Session header | New optional `advice_kinds`. |
| `AdvicePanel` | Shows each recommendation with its reason and evidence: `Focus: s (accuracy, 3 of 40)`. |

## 11. Checking the advice: the replay script

`scripts/replay_advice.py` replays stored sessions through an advisor and
checks whether the advice was followed by improvement. It is read-only: it
never writes the advice cache or a session file.

For each session it rebuilds the context (the newest `--window` sessions with
their raw streams), runs the advisor, validates the advice, and looks at the
next `--horizon` sessions that have raw streams. It compares the **advised**
keys (`focus`, `focus_pair`, `emphasize`, `contrast`) with the **other**
unlocked keys, before and after, and prints the difference of differences with
a standard error. A change under two standard errors is flagged as noise.

```
uv run python scripts/replay_advice.py [--layout NAME] [--advisor rules]
    [--window N] [--horizon 3] [--min-history 3] [--decay 1.0 0.85 0.7] [--json]
```

`--decay` takes several values and prints one line per decay, so you can
compare recency settings on your own history. Without it the script uses
`recency_decay` from `advisors.toml`.

An advisor that sends data off the device needs `--allow-off-device`. The
numbers are a sanity check, not proof: advised keys are weak by construction,
so they tend to improve anyway, and windows overlap. On the 6 raw sessions
available today it gave -3.1 ± 1.6 points, which is within noise.

## 12. Open decisions

1. **Thresholds.** `events >= 2`, `opportunities >= 10`, full weight at 5
   events. From one small sample; tune with `advice_kinds` data.
2. **Emphasis range.** 1.0–1.5 and 0.7–1.0, the v1 extremes.
3. **Word reserve.** Up to 20% of the lesson for `CONTRAST`.
4. **`SPEED` evidence.** Resolved in Phase A: the events are over-goal
   eligible intervals, not all correct presses.
5. **Engine tallies.** They count retries as attempts. Counting per position
   would change the confidence engine, which is out of scope here.
6. **The decay value.** 0.85 is a guess (half-weight after about 4 sessions).
   On the first 10 raw sessions the replay showed 1.0, 0.85, 0.7 and 0.5 within
   about one standard error of each other, so the data cannot choose yet. Tune
   it with `--decay` as raw sessions accumulate.
7. **Two-direction confusions.** Waits for replay data from more sessions.

## 13. Deferred (Phase B)

These ideas came out of the same analysis. They wait until a **forward
comparison** shows a benefit: run them on new sessions against the Phase A
baseline, and measure accuracy and total time, including correction time. A
replay of old sessions is not enough: it cannot show a benefit from words the
learner never typed, and its windows overlap.

- **`drill_pair`** (keys = previous, next; an ordered, contiguous pair,
  doubled letters included). Safeguards:
  - word boosts only, inside a reserve like the `CONTRAST` one;
  - it never touches transition tallies or gate weights (transition
    confidence gates unlocks);
  - a unit test that the unlock state is identical with and without the
    drill;
  - bounded combined boosts (`CONTRAST` and `drill_pair` together);
  - focus coverage is protected; no forced nonsense words when no word has
    the pair.
- **Hints** (text only, no effect on lessons): structured (metric,
  denominator, window), rendered by core templates, outside the budget and
  the evidence scaling, at most one shown, and never the summary below the
  evidence floor. Descriptive only, for example the median space interval
  with its coverage; no diagnosis.
- **Pooled observations** (for example "16 of 22 errors are neighbour
  slips"): at most a hint that states the numerator and denominator. Never a
  recommendation, and never a reason to select keys.
