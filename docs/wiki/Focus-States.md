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
| `cal` | **Calibrating** — not enough presses yet for full confidence weight. Confidence ramps linearly until `min_confidence_attempts` (keys) or `min_transition_confidence_attempts` (bigrams) is reached. |
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
5. **Confidence** — min(speed, accuracy), scaled by attempt count during calibration. Goal is 1.0 for mastery.

## Key vs transition focus

**Key focus** applies while any unlocked key is below the performance skill
threshold (see `blocks_transition_focus` in the codebase). The lesson
emphasizes the weakest unlocked key by ramped confidence, adjusted for review
urgency.

**Transition focus** applies when every unlocked key meets the skill threshold
(performance without attempt ramp). Keys still gathering presses show `cal` but
no longer block bigram focus. The lesson then emphasizes the weakest measured
cross-key bigram among unlocked keys. Same-key repeats (double letters) never
count as transitions.

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
