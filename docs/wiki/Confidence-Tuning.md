# Confidence tuning

Keystrike's adaptive engine uses **confidence** — speed × accuracy, scaled by how
much you've practiced — to decide which keys unlock, which key or bigram gets
focus, and how the stats heatmap colors each key. Three settings control how
aggressively the engine trusts your recent performance.

Edit `{config_dir}/settings.toml` directly (see [Git sync](Git-sync) for the
path on your OS). These three fields are **not** on the Settings screen — saving
layout, speed, or other UI settings will not change them.

## Settings

| Setting | `settings.toml` key | Default | What it does |
| --- | --- | --- | --- |
| Confidence session window | `confidence_session_window` | `10` | How many recent sessions are replayed into rolling per-key stats used for confidence, unlocks, focus, and the heatmap. |
| Min key attempts | `min_confidence_attempts` | `10` | Minimum presses on a key before its confidence reaches full weight. Below this, confidence ramps linearly (fewer attempts → lower score). |
| Min bigram attempts | `min_transition_confidence_attempts` | `4` | Same ramp for letter-pair (transition) confidence. Default is lower because bigrams are practiced less often than single keys. |

Valid ranges: window and both attempt floors are **1–100**.

Example (defaults shown):

```toml
confidence_session_window = 10
min_confidence_attempts = 10
min_transition_confidence_attempts = 4
```

## What each setting affects

**Session window** — Confidence is computed from aggregates over your last *N*
sessions (per layout), not your entire history. A longer window smooths noise but
reacts slowly; a shorter window tracks recent form but can under-sample rare keys
and block unlocks until those keys appear often enough in recent drills.

**Min key attempts** — Prevents a lucky fast streak from reading as mastery.
Until you've pressed a key at least this many times (within the windowed
stats), its confidence is scaled down. Higher values mean slower unlocks and
more conservative focus selection; `1` effectively disables the ramp.

**Min bigram attempts** — Same idea for prev→next letter pairs. Transition
focus and bigram-weighted lesson text use this floor. Keeping it lower than the
key floor (default 4 vs 10) matches how sparse bigram data is in normal
practice.

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

After changing the session window, run a practice session or open Stats so
aggregates rebuild from the new window size.

## Related docs

- [Word lists](Word-Lists) — optional dictionary drills (same confidence engine).
- [Git sync](Git-sync) — settings (including these fields) sync with your repo.
