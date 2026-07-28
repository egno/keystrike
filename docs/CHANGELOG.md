# Changelog

Post-milestone fixes and refinements, newest first, one entry per change. Full
rationale lives in commit history/diffs — these are pointers, not narratives.
Milestone-level feature work (what shipped in M1–M4, the keybr algorithm
design) stays in `PLAN.md` §5/§6.

## Unreleased

- Git-backed backup sync (CLI-only, opt-in): `keystrike sync init|pull|push|status`.
  Union-merge sessions by `session_id`, settings last-write-wins via `updated_at`
  (or mtime fallback), layouts copied on pull/push; `cache/` excluded — pull
  triggers aggregate rebuild. See `PLAN.md` §5 "Deferred → Git-backed backup".

## 1.0.0 — first stable release

- Adaptive-only practice flow (keybr-style confidence engine, Markov drills,
  per-layout stats, daily learn budget, four bundled layouts + custom TOML).
- PyPI package (`uv tool install keystrike`); version and metadata finalized.
- README with demo GIF, Windows Terminal setup notes, install/usage docs.
- CI matrix on macOS, Linux, and Windows (Python 3.12/3.13); snapshot tests in
  optional `snapshot` dependency group (`pytest-textual-snapshot`).

## ArjanCodes-lens architecture review — 6 findings fixed

Full-codebase review after M4 (adaptive, code, daily learn budget, HUD): session
prep orchestration moved from `presentation/textual_app.py` into
`application/prepare_practice.py` (`PreparePracticeSession`, `SessionPrep`) so
Path reads and lesson-building logic leave presentation; new
`test_presentation_has_no_path_reads` fitness function enforces it. HUD and
PracticeScreen now use `NULL_DAILY_LEARN_BUDGET` instead of
`DailyLearnBudgetProvider | None` plus scattered `is not None` checks.
`GetLearningRate` was wired in `app.py` but never passed to the HUD — restored
`Goal[<focus>]: ~N sessions` / `learning…` via `LearningRateEstimator` injection
into PracticeScreen. StatsScreen and KeystrikeApp now depend on
`StatsRebuilder` protocol (matching PracticeScreen) instead of concrete
`RebuildAggregates`. Sample text constant moved to composition root (`app.py`).

## Removed Theme/Recover keys/Keyboard order settings; Alphabet size is now a letter count

These three Settings toggles were redundant — each only ever needs one
answer, so the choice was made permanent instead of user-configurable.
`theme` was dead code (never read to switch any rendering/styling) — removed
outright. `keyboard_order` is now always on: `build_lesson.py` always calls
`keyboard_order(layout)` (row-weighted unlock order), since it's the
literature- and convention-backed choice (docs/research/typing-pedagogy.md,
"Row-order vs. finger-order"); the frequency-order path and `Settings.theme`
are gone. `recover_keys` is now always "live": `confidence_of`/
`compute_unlocked`/`select_focus` dropped the `recover_keys` param and the
historical-peak branch, matching Keybr's actual "clears thresholds on the
*current* set" gate rather than trusting a stale best-ever score. Since
nothing reads a historical peak anymore, `KeyStats.peak_confidence` and its
plumbing (`_stamp_peak_confidence`, `aggregate.py`'s `max()` merge, the cache
JSON field) were deleted; `RebuildAggregates` no longer needs a
`settings_repo` dependency. `alphabet_size` changed from a `0.0-1.0` fraction
of the learn order to a plain `int` count of letters force-unlocked from
cold start (default `16`); `compute_unlocked` now does
`min(alphabet_size, len(learn_order))` instead of
`round(alphabet_size * len(learn_order))`. Existing `settings.toml` files
with an old fractional `alphabet_size` (e.g. `0.5`) will read back as `0`
under the new `int()` cast — re-save the Settings screen once to fix.

## Confidence now folds in accuracy

`confidence_of`'s live branch, `_stamp_peak_confidence` (feeds
`peak_confidence`/`recover_keys=True`), and `GetHeatmap` all scored a key
purely on speed vs. target — `KeyStats.error_count` was tracked but never
read, so a key typed fast but frequently wrong could read as "confident"
and unlock the next key prematurely. Added `accuracy_of(key_stats)` in
`domain/confidence.py` (`samples / (samples + error_count)`), multiplied
into speed-confidence at all three sites. See
`docs/research/typing-pedagogy.md` ("Gap found in current implementation").

## Backspace disabled in Adaptive mode

`RecordKeystroke`'s `BACKSPACE` branch now only rewinds `session.position`
when `session.mode is not Mode.ADAPTIVE` — matches keybr.com: the confidence
engine needs an honest record of what happened at each key, and the error is
already captured via `session.error_positions`. Free/Sample/Code modes are
unaffected.

## Timer doesn't start until the first keystroke

HUD elapsed time (and `SessionResult.duration_ns`) used to count from
`PracticeScreen` construction, penalizing WPM for time spent reading the
prompt. Added `Session.typing_started_at_ns`, set on the first non-backspace
keystroke; `RecordKeystroke`, `FinishSession`, and the live HUD now measure
from there instead of `started_at_ns`.

## Stats page adapted for ortholinear layouts

`kb_heatmap.py`'s ASCII grid was hardcoded to QWERTY-style row-stagger
indentation, which is wrong for ortholinear boards. Added
`Layout.ortholinear: bool` (rendering hint only, no effect on finger/hand
assignment or adaptive-engine math); `render_heatmap()` skips the per-row
indent when set, `layout_toml.py` parses an optional `ortholinear` field for
custom layouts (defaults `False`).

## Fourth bundled layout: Colemak Mod-DH (ortholinear)

`infrastructure/bundled_layouts/colemak_dh.py`, verified against the
authoritative `ColemakMods/mod-dh` matrix scan codes (not reconstructed from
memory) — D/H move off home row to the bottom row's inner columns, G
reclaims QWERTY's home-row column. Dedicated tests assert both facts rather
than just that the layout loads.

## ArjanCodes-lens architecture review — 5 findings + 3 minors fixed

Full-codebase review at the M2→M3 boundary: Settings/layout writes moved out
of Screens into `application/settings_use_cases.py`; a dead-import lint hack
in `typing_area.py` was masking a missing `STYLE_CORRECTED` feature (fixed via
`Session.error_positions`); `X | None` optional-dependency checks replaced
with Null Objects (`domain/null_adapters.py`); `HomeScreen.StartPractice`'s
stringly-typed source became `PracticeSource` StrEnum; the confidence formula
moved from `GetHeatmap` into `domain/confidence.py`. Also caught while wiring
`recover_keys`: `KeyStats.peak_confidence` was hardcoded to `0.0` and never
actually computed — `RebuildAggregates` now stamps it per session before
`combine()`'s `max()` reduction.
