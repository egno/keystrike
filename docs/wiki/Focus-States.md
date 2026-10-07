# Focus states

During adaptive practice, Keystrike picks one **focus** — a single key or a
letter pair (bigram) — and biases lesson text toward it. The HUD and practice
screen show compact labels; this page explains what they mean.

See [Confidence tuning](Confidence-Tuning) for how focus is selected and how
confidence thresholds interact with unlocks.

## HUD labels

The practice HUD shows `Focus: <key or pair> · <reason>`.

| Short | Full meaning |
| --- | --- |
| `wk` | **Weak** — confidence is below the mastery goal (default 1.0). The key or pair needs more deliberate practice. |
| `cal` | **Calibrating** — not enough presses yet for full confidence weight. Confidence ramps linearly until `[unlock].min_confidence_attempts` (keys) or `[unlock].min_transition_confidence_attempts` (bigrams) is reached. |
| `rev` | **Review** — confidence meets the goal, but the key or pair has not been practiced recently. Review urgency pushes it back into focus before it fades. |

For **transition focus**, the HUD shows the two-letter pair (e.g. `eo`) instead
of a single key; the reason suffix is still `wk`, `cal`, or `rev`.

Examples:

- `Focus: t · cal` — key **t** is the focus; still calibrating (fewer than the minimum attempts).
- `Focus: eo · wk` — bigram **e→o** is the focus; transition confidence is below goal.

## Practice note (bottom line)

Below the keyboard heatmap, a single compact line repeats the focus subject,
reason, and live metrics:

`t · cal 9/10 · 1.59 · 100% · 0.90`

Reading left to right:

1. **Subject** — focus key (`t`) or bigram (`at`).
2. **Reason** — `wk`, `cal`, or `rev`. Calibrating adds press progress (`9/10`).
3. **Speed** — target timing ÷ actual timing for the focus key or pair.
4. **Accuracy** — correct attempts ÷ total attempts (percent).
5. **Confidence** — min(speed, accuracy score), scaled by attempt count during calibration. The accuracy score is accuracy ÷ 95%, capped at 1.0, so 95% accuracy already counts in full. Goal is 1.0 for mastery.

## How focus is chosen

Focus follows one ordered list of rules. The first rule that has candidates
picks the focus (`select_lesson_focus` in `domain/focus.py`):

1. **Keys first.** If any unlocked key has not cleared (skill below 1.0 or
   fewer presses than `[unlock].min_confidence_attempts`), the weakest such
   key is the focus. Never-typed keys count as not cleared.
2. **The unlock gate.** If the next letter waits on the newest key's pair
   cohort, the weakest pair of that cohort that is not ready is the focus.
3. **Weak pairs.** Otherwise, the pair that is not cleared and has the highest
   (1 − confidence) × language frequency is the focus. Pairs that do not occur
   in the language are skipped. Same-key repeats (double letters) never count.
4. **Review.** When everything has cleared, the most overdue key or pair
   (by review urgency) is the focus.
5. **Fallback.** Otherwise, the weakest key.

## Focus stays put until it clears

In rules 1–3, the last lesson's focus is kept while it is still a candidate
of that rule. So a key or pair keeps the focus lesson-over-lesson until it
clears both skill and its attempt floor — the same bar unlocks use.

A focus that does not clear after 3× its attempt floor in the session window
(30 presses for a key, 12 for a pair, by default) is **stalled**. It goes back
into the pool, so the weakest candidate is picked again from all of them.

The last focus comes from the last saved session: `focus_key`, plus
`focus_pair` when the focus was a pair.

## Heatmap underline

The underlined key(s) on the practice heatmap match the HUD focus:

- One key underlined — key focus.
- Two keys underlined — transition focus (both letters of the pair).

Underline color: cyan when confidence ≥ 1.0, plain underline when still weak.
Keys due for review also get a magenta urgency underline on top of their
confidence color.

## Related docs

- [Confidence tuning](Confidence-Tuning) — session window, attempt floors, focus boosts.
- [Typing pedagogy](https://github.com/egno/keystrike/wiki/Typing-Pedagogy) — why weak-key and spaced review matter.
