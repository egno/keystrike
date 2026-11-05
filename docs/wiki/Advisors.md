# Advisors

After each practice session, an **advisor** can recommend what the next lesson
should practice. The adaptive engine still decides which keys unlock and what
the focus is. An advisor can only **nudge** it, and the core checks every
nudge. This page explains what the advice means, how much to trust it, and how
to write your own advisor.

See [Focus states](Focus-States) for the HUD labels and
[Confidence tuning](Confidence-Tuning) for the engine behind them.

## Choosing an advisor

Open **Settings** and pick one under *Advisor*.

| Advisor | Runs | Sends data off the device? |
| --- | --- | --- |
| **Rules (local)** — the default | On your device | No |
| **Off** | — | No |
| **LLM** (plugin `keystrike-ai`) | On a server you choose | **Yes** — Keystrike asks you to confirm once |

Choices are stored in `advisors.toml` on this device. They are **not** synced.

### Test advisor (`Ctrl+T`)

`Ctrl+T` on the Settings screen runs the advisor you have selected in the form
on built-in **sample data**. It saves nothing, and it uses the values in the
form, not the saved ones.

- **Success:** the status line under the advisor settings shows the advisor's
  name and its summary, for example
  `Rules (local): ok — n is slower than your goal — it gets extra practice.`
- **Failure:** `Failed: <error>`. It shows a bad setting (for example an
  invalid endpoint) or an error from the advisor (for example a timeout).
- **Limit:** 30 seconds.
- **Off:** with "Off" selected it asks you to choose an advisor first.
- **Use:** to check a plugin's settings, such as the LLM endpoint and model,
  before you save them.
- **Sample data:** it is synthetic (six unlocked letters, a goal of 343 ms per
  key, and `n` and `o` slower than that), not your practice. The advice you see
  is not about your typing.
- **Privacy:** an advisor that sends data off the device (the LLM plugin) sends
  the sample data to the server you configured, not your practice data.

The footer shows it as "Test advisor" when the advisor settings are available.

## Reading the advice

The panel under the practice area starts with a line that names the advisor
(`Advisor: Rules (local)`), so you always know who is speaking. This matters
when you switch advisors: advice is kept per advisor, and an old advisor's advice
is never shown as the new one's. It then shows one line per recommendation:

```
Advisor: Rules (local)
You typed f instead of a 9 times in 90 presses — practice a and f.
Tell apart: a / f (confusion, 9 of 90)
Practice more: m (speed, 31 of 52)
Practice more: s (speed, 27 of 49)
Ease up on: e (mastered, 73 of 74)
```

Each line is `what (reason, events of presses)`.

| Recommendation | What it does to the next lesson |
| --- | --- |
| **Focus** (a key or a pair) | Moves the focus. Only among the candidates the engine allows at that stage: any key not cleared yet; then only the newest key's gate pairs; then any unlocked key or pair. |
| **Practice more** | Raises the sampling weight of one key, up to ×1.5. |
| **Ease up on** | Lowers it, down to ×0.7. Only for mastered keys. Never the focus key or the newest key. |
| **Tell apart** | Favours words that contain **both** keys of a mixed-up pair (for example `a` and `f`). Up to a fifth of the lesson's words are reserved for them. It never changes the focus. |

| Reason | Meaning |
| --- | --- |
| `accuracy` | Errors on the key. |
| `speed` | Correct, but slower than your goal. |
| `confusion` | Another key was typed instead. |
| `mastered` | Fast and accurate. |

When nothing needs practice the panel says **On track**.

The panel shows the advice that already steers the lesson as soon as practice
opens, so it is not empty until you finish a session. With an advisor on but no
advice yet (a new layout, or a first run), it says "No advice yet — it appears
after your first session."

## How much to trust it

- **Errors count once per position.** The cursor stays on a character after a
  mistake, so a stumble of three wrong keys is one error, not three.
- **Evidence floor.** A recommendation needs at least **2 events** and
  **10 presses**. Anything weaker is dropped. A contrast ("Tell apart") needs
  **3 events** seen in at least **2 sessions**.
- **Speed is the median.** A key is slow when its typical press (the median
  of the timed presses, recent sessions weighing more) is over the goal. The
  first press of a session, the press after a space, the first press after an
  error and key rollover (under 30 ms) are not timed. The evidence
  (`speed, 31 of 52`) is the timed presses over the goal.
- **Weak evidence, weak effect.** The effect scales with the events, up to
  full strength at **5 events**. A mistype seen twice gives 40% of the push.
- **Recent sessions count more.** Each older session weighs 15% less than the
  next newer one. The default is `recency_decay = 0.85` in `advisors.toml`
  (a number above 0 up to 1; `1.0` weighs all the sessions in the window the
  same). The counts in the panel (`5 of 99`) are exact. Recency decides what
  comes first and how strong a recommendation is: a mistype you stopped making
  fades, a new one counts at once, and a recent error stops a key from being
  eased.
- **One key per line.** "Practice more" and "Ease up on" name one key each,
  with that key's own evidence.
- **Budget.** At most a third of your unlocked keys can be emphasized, and the
  same for eased keys, so advice cannot cancel itself out. The weakest lines
  are dropped whole.
- **Margins.** The rules advisor does not emphasize or ease a key whose speed is
  within 5% of your goal, so advice does not flip between sessions.
- **No unlock is ever delayed.** The engine decides unlocks and scores your
  typing as usual. Advice only changes which keys and words you see.
- **Timing.** The advisor runs after the session. A fast advisor steers the
  **next** lesson. A slow one (an LLM) takes longer than 150 ms, so it steers
  the lesson after.

The HUD shows the advisor's name when it moved the focus: `rules wk`,
`llm rev`. Each session's stored row records `advice_source` and
`advice_kinds`, so you can compare progress per advisor later.

## The built-in rules advisor

Deterministic and local. It looks at:

- **The weakest key:** the key with the highest recent error rate becomes the
  focus, if that rate is at least 8%.
- **Repeated mistypes:** a *tell apart* for a mistype seen at least 3 times,
  in at least 2 sessions, with at least one in the newer half of your recent
  sessions. Two events are not enough.
- **Slow keys:** a *practice more* for each key whose typical (median) press is
  more than 5% over your goal. It needs at least 20 timed presses from at least
  2 sessions.
- **The weakest finger:** a *practice more* for each key of the finger with a
  clearly higher error rate. Each key needs its own evidence (at least 2 errors
  in 10 presses). The finger's total is never copied onto a key.
- **Mastered keys:** an *ease up on* for each key that is fast (median at or
  below 95% of the goal), accurate (recent errors under 2%) and mastered. Never
  the newest key. Between 95% and 105% of the goal, a key gets no advice.

The rules advisor writes no summary. The core writes one sentence about the
recommendation with the strongest evidence, and only when it has at least 3
events. When nothing needs practice it says **On track**.

You can tune how fast old sessions fade in `advisors.toml`:

```toml
active = "rules"
confirmed_off_device = []
recency_decay = 0.85   # above 0, at most 1; 1.0 = every session weighs the same
```

## Privacy

- Raw keystroke files (`raw_keystrokes/`) are kept **locally**, only for the
  sessions in the confidence window and only while the chosen advisor needs
  them. Each starts with a header line (`session_id`, `layout`, `started_at`,
  `ended_at`).
- The core has **no network code for advice**. A test checks this. Word-list
  import and git sync use the network only when you start them.
- An advisor that sends data off the device is marked, and Keystrike asks you
  to confirm once before it starts. This is a notice, not a sandbox: **a plugin
  runs in the same process and can do anything Python can. Installing it means
  trusting it.**

## The LLM plugin

`keystrike-ai` (in `packages/keystrike-ai`) asks an Ollama or OpenAI-compatible
server. It is not on PyPI yet: install it from a clone (`uv sync`, or
`pip install ./packages/keystrike-ai`).

| Setting | Default | Notes |
| --- | --- | --- |
| Provider | `ollama` | `ollama`, or `openai` |
| Model | `llama3.2` | |
| Endpoint | `http://localhost:11434` | Ollama root, or the `/v1` base URL |

The API key (OpenAI-compatible servers) is read from `KEYSTRIKE_AI_API_KEY`
and never written to a file. An old `ai.toml` from the earlier AI coach is read
once as these settings.

The model only names keys. The **evidence comes from your data**, not from the
model: a key the model emphasizes but that has fewer than 2 errors is dropped.

## Writing a plugin

A plugin is a Python package. It declares an entry point:

```toml
[project.entry-points."keystrike.advisors"]
mine = "my_advisor"
```

and a module that imports only `keystrike.plugin_api`:

```python
from keystrike.plugin_api import (
    AdvisorCapabilities, AdvisorSpec, Evidence, Kind, LessonAdvice,
    Reason, Recommendation, error_rate_ranked,
)

API_VERSION = 2

async def advise(ctx):  # ctx: AdvisorContext, read-only
    worst, tally = error_rate_ranked(ctx.digest.keys)[0]
    return LessonAdvice(
        summary="",
        recommendations=(
            Recommendation(
                Kind.EMPHASIZE, (worst,), Reason.ACCURACY, strength=0.7,
                evidence=Evidence(tally.errors, tally.attempts),
            ),
        ),
    )

def register(registry):
    registry.register(AdvisorSpec(
        name="mine", label="My advisor",
        capabilities=AdvisorCapabilities(needs_keystrokes=False,
                                         sends_data_off_device=False),
        settings=(), create=lambda cfg: advise,
    ))
```

- An advisor is an `async` function from an `AdvisorContext` to a
  `LessonAdvice`. The context carries the per-key and per-pair tallies, the
  course state, the mistypes and per-finger errors, the layout's key positions,
  `coverage` (how many sessions each part covers) and `session_weights`. Use the
  exact counts (`digest.keys`) as `evidence`, and the recency-weighted ones
  (`digest.recent`, `Confusion.recency`) to rank and to set `strength`.
- Set `needs_keystrokes=True` to receive raw keystrokes. Set
  `sends_data_off_device=True` if your code sends data anywhere. Keystrike
  then asks the user to confirm.
- Settings are `SettingField`s. Keystrike draws the form, so a plugin never
  imports Textual.
- A plugin whose `API_VERSION` differs from Keystrike's is skipped, and the
  reason is shown in Settings. A plugin that raises is isolated: practice
  continues and the last good advice stays.
- Always give `evidence`. The core drops a recommendation with fewer than 2
  events or 10 presses, and a `CONTRAST` with fewer than 3 events in 2
  sessions (`Evidence.event_sessions`).
- `EMPHASIZE` and `EASE` take exactly one key, with that key's own evidence.
- Leave `summary` empty to let the core write it from your validated
  recommendations; text you write is kept.
- `digest.timing` (one `KeyTiming` per key) and `digest.space` give the
  speed from the raw streams: classify on `recent_median_ms`, and use
  `over_goal` of `presses` as the evidence.

Design notes: [docs/ADVISOR-PLUGINS.md](https://github.com/egno/keystrike/blob/main/docs/ADVISOR-PLUGINS.md)
and [docs/ADVICE-PROTOCOL.md](https://github.com/egno/keystrike/blob/main/docs/ADVICE-PROTOCOL.md).
Dev script `scripts/replay_advice.py` replays stored sessions through an
advisor and compares the advised keys with the others, before and after.
