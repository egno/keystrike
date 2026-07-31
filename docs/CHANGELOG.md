# Changelog

Post-milestone fixes and refinements, newest first, one entry per change. Full
rationale lives in commit history/diffs — these are pointers, not narratives.
Milestone-level feature work (what shipped in M1–M4, the keybr algorithm
design) stays in `PLAN.md` §5/§6.

## 1.3.0

- Weak-focus lessons guarantee a configurable fraction of words match the focus
  key or bigram (default 60%); remaining quota filled via Markov when the wordlist
  pool is too small.
- Focus-pool words sampled without replacement; per-lesson repeat cap (default 2)
  limits streaks like repeated `toe` on tiny alphabets.
- Lesson tuning in `settings.toml`: `lesson_word_count`, `focus_word_min_fraction`,
  `max_word_repeats`; documented on `Confidence-Tuning` wiki.
- Aggregate cache: stop rebuilding on every access when transitions are empty but
  already computed (`transitions_computed` on load).
- Edge cases: clamp invalid fraction/word-count settings; repeat cap on confident
  focus path; graceful fallback when vocabulary ceiling hit on small alphabets.

## 1.2.3

- HUD Learn segment: activity (dim when paused or not started) and goal (green when
  daily limit reached) are independent — e.g. dim green when goal reached but idle.
- Lesson text colors: untyped white, typed grey42; wrong key bold red; tripped keys dim yellow.
- Practice "Last" row: WPM, accuracy, and time only (removed redundant Keys count).
- Typing cursor uses bold underline on the target character instead of a block.
- Practice "Last" row shows WPM and accuracy deltas vs the recency-weighted
  `confidence_session_window` baseline (green ↑ / red ↓), not just the prior session.
- Stats screen: single `#stats-trends` widget with unified `format_metric_trend_block`
  (overview: Layout + Focus blocks; key drill-down: per-key grid — same format as letter stats).
- Stats overview shows layout-wide confidence, speed, and accuracy in a titled grid block;
  focus-key confidence in the same grid format below (tracks the current focus
  letter across sessions, matching letter drill-down); WPM trend row and session history removed.
- Stats screen layout: title → trends → heatmap caption → heatmap.
- Stats heatmap hint: press a key for letter stats, Esc to return.
- Practice text wraps at word boundaries (`·` dividers, no visible gap); lines break
  at words, not mid-word, using the widget width.
- Learn timer pauses after 5s idle (no keystrokes) and resumes on the next key;
  idle time does not count toward the daily learn goal.
- Practice focus note shows speed ratio and accuracy % alongside confidence
  (e.g. `speed 0.85, accuracy 92.0%, confidence 0.45 / 1.00`).
- Confidence uses min(speed, accuracy) instead of their product — fast-but-sloppy
  or slow-but-accurate keys no longer compensate each other for unlocks/focus.
- Windowed aggregates recency-weight speed, accuracy, and attempt counts (decay
  0.7 per session back); recent sessions move confidence faster than older ones.

## 1.2.2

- Confidence tuning settings: session window, min key attempts, and min bigram
  attempts in `settings.toml` only; wiki page `Confidence-Tuning`.
- Round confidence scores to two decimals so unlocks, focus labels, heatmap, and
  practice focus notes stay aligned.

## 1.2.1

- Stats confidence trends normalize stored snapshots to the current goal speed;
  persist `target_speed_cpm` on session finish; heatmap caption clarifies live
  vs historical goal.
- Practice focus UX: weak keys keep yellow/red on the heatmap (not cyan); focus
  note below keyboard shows actual vs goal confidence.
- CI: pin `NO_COLOR=1` for snapshot tests so baselines match across environments.

## 1.2.0

- Optional word-list import: Settings URL field + Import button; cached lists drive
  lesson words when alphabet-compatible, Markov fallback otherwise
  (`application/wordlist_use_cases.py`, `infrastructure/wordlist_store.py`).
- Daily learn goal is HUD-only — practice no longer stops when the goal is reached;
  `PreparePracticeSession` and `PracticeScreen` removed the hard limit gate; HUD always
  shows used/limit.
- README: "Why it works" section with pedagogy wiki link; daily goal vs limit wording;
  git-sync FAQ pointer. Wiki: `Typing-Pedagogy`, `Git-sync`, `Home` index pages.

## 1.1.0

- Git-backed backup sync (CLI-only, opt-in): `keystrike sync init|pull|push|status`.
  Union-merge sessions by `session_id`, settings last-write-wins via `updated_at`
  (or mtime fallback), layouts copied on pull/push; `cache/` excluded — pull
  triggers aggregate rebuild.
- CI fixes: snapshot tests excluded from default pytest; pyright clean on all
  platforms; snapshot baselines pinned to GitHub Actions macOS runner.
- Packaging: PyPI-friendly README (absolute demo GIF URL), lean sdist excludes,
  `pipx install` documented.

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
