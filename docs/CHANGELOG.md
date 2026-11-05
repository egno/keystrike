# Changelog

Post-milestone fixes and refinements, newest first, one entry per change. Full
rationale lives in commit history/diffs — these are pointers, not narratives.
Milestone-level feature work (what shipped in M1–M4, the keybr algorithm
design) stays in `PLAN.md` §5/§6.

## 2.3.0

- **Advice protocol v2** — advisors now return typed recommendations, and the
  next lesson is prepared from them. Design: `docs/ADVICE-PROTOCOL.md`.
  `PLUGIN_API_VERSION` is 2.
  - A `Recommendation` has a kind (`focus`, `focus_pair`, `emphasize`, `ease`,
    `contrast`), a reason (`accuracy`, `speed`, `confusion`, `mastered`), a
    strength and **evidence** (events of opportunities). The core drops weak
    evidence (under 2 events or 10 presses) and scales the effect by it: 2
    events give 40% of the push, 5 give all of it.
  - A budget keeps emphasis honest: at most a third of the unlocked keys can
    be emphasized, and the same for eased keys. `ease` needs a mastered key.
  - `contrast (target, typed)` boosts words that contain both keys and
    reserves up to 20% of the lesson for them (`WordBoost` in
    `LessonWeighting`). It never changes the focus.
  - The context carries `coverage` (sessions behind the tallies and behind
    the raw streams), the layout's key positions, and `neighbors()`. The
    panel shows `Focus: s (accuracy, 3 of 40)`.
  - **Fix:** `keystroke_insights` counts one attempt and at most one error per
    position. The cursor does not advance on an error, so a stumble of three
    wrong keys used to count as three mistypes.
  - **Rules advisor tuning.** The summary names the recommendation with the
    strongest evidence, and two events never lead it. A key about at the goal
    (95%–105%) is neither emphasized nor eased, so advice does not flip between
    sessions. When nothing needs practice, the summary is "On track". The
    advisor returns only what the core would keep.
  - **The panel names the advisor.** The first line is `Advisor: <label>`
    (for example `Rules (local)`), also while it thinks, while it waits for the
    first advice, and when it fails. `AdviceRunner.label()` gives the display name.
  - **Advice on the first screen.** The practice screen shows the stored advice
    that steers the lesson as soon as it opens. With an advisor on but no advice
    yet, it says when advice comes. With the advisor off, the panel stays empty.
  - **Recency decay.** Older sessions weigh less: session `i` weighs
    `recency_decay ** i` (default 0.85, set in `advisors.toml`; 1.0 = equal).
    The exact counts stay the evidence; recency decides the ranking and the
    strength (`digest.recent`, `Confusion.recency`, `recent_*` on finger
    stats). A mistype you stopped making fades, a new one counts at once, and a
    recent error stops a key from being eased. `build_advisor_context` takes
    `recency_decay`, and `session_weights` is in the context.
  - **`scripts/replay_advice.py`** (dev-only, read-only) replays stored
    sessions through an advisor and compares advised keys with the others
    before and after, with a standard error. `--decay 1.0 0.85 0.7` compares
    recency settings. See `docs/ADVICE-PROTOCOL.md` §11.
  - The session header records `advice_kinds` next to `advice_source`.
  - `advice.json` rows are versioned; an old row is ignored until the next
    advice.
  - **Honest evidence (review fixes).** A second analysis of 10 raw sessions
    was checked by two reviews; its errors are listed in
    `docs/ADVICE-PROTOCOL.md` §1b. What changed:
    - **Timing from the raw streams.** `domain/timing.py` times each key on
      *eligible* intervals only (correct first attempts; not the first press
      of a session, the first press after an error, the press after a space,
      or a rollover under 30 ms). `digest.timing` holds a `KeyTiming` per
      unlocked key (`presses`, `over_goal`, `tail`, `median_ms`,
      `recent_median_ms`, `sessions`); the space is in `digest.space`.
    - **Speed on the recent median.** The rules advisor flags a key above
      105% of the goal (at least 20 presses from 2 sessions) and eases one at
      or below 95%. The evidence is over-goal presses, not all correct presses
      ("529 of 551" is gone).
    - **Follow-ups.** The `Ctrl+T` sample context has per-key timing, so the
      rules advisor shows speed advice on it. The LLM plugin judges speed with
      the same recency-weighted median rule (no longer the mean), takes the
      speed evidence from `digest.timing`, and its prompt lists the speed per
      key.
    - **One key per recommendation.** `emphasize` and `ease` name one key; the
      budget keeps the strongest per key and drops whole recommendations.
      `Recommendation.note` is removed. Pooled finger evidence is gone: each
      key carries its own.
    - **The core writes the summary** (`render_summary`) when the advisor
      leaves it empty; an LLM's own text stays.
    - **Contrast floor.** A `contrast` needs 3 events in 2 sessions
      (`Evidence.event_sessions`); the rules advisor also needs one in the
      newer half of the streams (`Confusion.sessions`, `.newest_half`).
    - `advice.json` rows are version 3; older rows are ignored.
    - `drill_pair`, hints and pooled observations are deferred, with
      safeguards (`docs/ADVICE-PROTOCOL.md` §13).

- **Advisor plugins** — the AI coach is replaced by a general advice system.
  An advisor (rules, a local model, an LLM) is a function from an
  `AdvisorContext` to a `LessonAdvice`. Design: `docs/ADVISOR-PLUGINS.md`.
  - **Core** keeps validation, the tie-breaker rule, scheduling, time
    budget, error isolation, persistence and all UI. `domain/advice.py`:
    `validate_advice` (unlocked keys only, at most 5 per list, never rest the
    newest key), `apply_focus_advice` and `weigh_advice` (focus only inside
    `FocusChoices`; fixed weights 1.5 / 0.7). `AdviceRunner` runs one request
    at a time, never cancels it, and waits 150 ms before the next lesson: a
    fast advisor steers the next lesson, a slow one the lesson after.
  - **Plugins** register through the `keystrike.advisors` entry point
    (`plugin_loader`) and import only `keystrike.plugin_api`
    (`PLUGIN_API_VERSION = 1`). A failing plugin is skipped and its error is
    shown in Settings. Architecture tests enforce the import rules and that the
    core has no network code outside word-list and sync modules.
  - **Rules advisor** (`advisors/rules.py`) is the new **default**: local,
    deterministic, uses mistypes, the worst finger and shrunk error rates.
    Its effect is bounded like any advice. "Off" is one select away.
  - **LLM advisor** moved to the separate package `packages/keystrike-ai`
    (uv workspace). It sends data off the device, so Keystrike asks you to
    confirm once. Old `ai.toml` is read once as its settings.
  - **Settings** — a select for the advisor and a form drawn from its
    `SettingField`s; `Ctrl+T` runs it on sample data. Stored in the unsynced
    `advisors.toml`.
  - **HUD** — `FocusReason.advisor` replaces `FocusReason.coach`: the tag is
    the advisor's name (`rules wk`, `llm rev`) instead of `ai wk`.
  - **Session header** — new optional `advice_source` records which advisor
    steered the lesson. It is written only when set, so old rows read back
    unchanged.
  - Each raw keystroke file (`raw_keystrokes/<session id>.jsonl`) starts with
    a header line: `session_id`, `layout`, and wall-clock `started_at` /
    `ended_at` (unix epoch). `t_ns` stays relative (active typing time).
    Readers skip the header, and old files without it still load.
  - Advice is kept per layout **and** advisor in `cache/advice.json`
    (replaces `ai_coach.json`). Raw keystrokes are kept only while the active
    advisor needs them.
  - Deviations from the design: `apply_advice` is split into pure domain
    functions plus a thin step in `build_lesson` (the domain cannot import
    `LessonProgress`); `AdvisorContext` also carries the shared `digest`;
    a failed `LessonAdvice` carries an `error` string instead of a separate
    result type; `plugin_loader` checks `PLUGIN_API_VERSION` from
    `domain.advice` (infrastructure cannot import `plugin_api`).

## 2.2.5

- **Fewer saved pairs** — `FinishSession` saves pair tallies only for the
  newest key's gate cohort and the lesson's focus pair, so a session row
  stays small as the alphabet grows. Pairs with a space are never tallied
  (`is_excluded_transition`, replaces `is_same_key_transition`). Focus
  selection drops the weak-pair rule and pair review: a pair is the focus
  only through the unlock gate. Lesson pair weights cover the gate cohort
  only.
- **Shorter tallies** — session rows store key and pair tallies as
  `stats.keys_avg` / `stats.pairs_avg`, `[samples, avg_ms, errors, attempts]`
  with the mean time in whole ms (`session_repo_jsonl`). Older `stats.keys` /
  `stats.pairs` rows (time as a sum in ns) still read.

## 2.2.4

- **History retention** — the session index keeps, per layout, the newest
  `max(20, 2 * confidence_session_window - 1)` rows plus every row from the
  current local day; older rows are deleted (`domain/retention.py`,
  `PruneSessionHistory`, replaces `PruneSessionStats`). It runs at startup
  and stats retention still applies to the kept rows. Git sync prunes each
  merged index — local after a pull, the clone before a push
  (`KeptSessionIds`, `sync_merge_io.prune_index`). The rule is monotone, so a
  device with old rows cannot bring pruned sessions back. Rows stay in the
  sync repo's git history.

## 2.2.3

- **Speed goal fixed in its own unit** — `Settings.target_speed` keeps the
  goal as entered, in `target_speed_unit` (replaces `target_speed_cpm`;
  older settings files migrate at load, a WPM goal at the typical rate). A
  WPM goal becomes the CPM that confidence uses through `goal_cpm`
  (`domain/generator.py`) and `session_queries.target_speed_cpm`, so it
  follows the measured rate. Switching the unit in settings converts the
  shown value.
- **Measured WPM ↔ CPM rate** — each session header saves its real `cpm`
  (lesson chars typed, spaces included, per minute) and `wpm`
  (`SessionResult`, set in `FinishSession`; 0 for legacy rows).
  `session_queries.keystrokes_per_word` is Σcpm / Σwpm over the layout's
  last `confidence_session_window` sessions with at least
  `MIN_RATE_WORDS` (5) words. With none, it falls back to
  `typical_keystrokes_per_word` (word-length midpoint + 1 space) — the old
  `typical_chars_per_word` left the space out, so typing at goal speed
  showed a session WPM below the goal WPM. `compute_wpm` returns the saved
  `wpm` when set; the legacy estimate now counts spaces and uses the
  session's stored word bounds.

## 2.2.2

- **Stats speed in the goal's unit** — the stats screen speed line shows
  `wpm` or `cpm`, following `Settings.target_speed_unit`, instead of the
  ratio to the goal. Speed trends are already normalized to the current
  goal, so ratio × goal CPM is the actual CPM; WPM divides by
  `typical_chars_per_word` (`presentation/formatting/trends.py`,
  `speed_value_formatter`). With no goal, it shows the plain ratio.

## 2.2.1

- **Lowering the letter count relearns the closed keys** — `UpdateSettings`
  records an `AlphabetCut` (time, new size) in `Settings.alphabet_cuts` when
  `alphabet_size` goes down, then rebuilds every layout's aggregates.
  `RebuildAggregates` and `FinishSession` drop the closed keys' tallies, and
  every bigram that touches them, from sessions before the cut
  (`domain/alphabet_cut.py`). A reopened key starts with no stats, so it goes
  through key focus and its gate pairs again before the next key opens.
- **One key per unlock** — `compute_unlocked` opens at most one key past
  `alphabet_size` per call. Before, keys with old mastered stats all opened
  at once.

## 2.2.0

- **One focus ladder** — `select_lesson_focus` (`domain/focus.py`) replaces
  `select_focus`, `select_focus_transition`, `remedial_focus` and the
  newest-key unmeasured-pair fallback. Order: keys not cleared, unlock-gate
  cohort pairs, weak pairs by (1 − confidence) × language frequency
  (`TransitionTable.pair_weight`), then review. Each rule keeps the last
  lesson's focus until it clears or stalls at 3× its attempt floor
  (`domain.confidence.stall_attempts_cap`, moved from `domain.unlock`).
  Removed: the lesson WPM gate (`remedial_focus`) and the review penalty in
  focus scoring. Sessions now save `focus_pair` when the focus was a pair
  (written only when set, still schema 5; old rows read back unchanged).
- **Attempt floors count real presses** — `combine_sessions` now sums
  `attempt_count` over the window without recency weights; speed and accuracy
  keep theirs. Weighted attempts settled at about 3.24 × presses per lesson,
  so a key or cohort pair with 2–3 presses per lesson never reached
  `min_confidence_attempts` (10) or the transition stall cap (12) and blocked
  the next letter. The aggregates cache moves to `schema_version` 2; older
  cache files read as a miss and rebuild from the session rows (session rows
  are unchanged).
- **Accuracy is scored against 95%, not 100%** — skill and confidence use
  `min(speed, min(1, accuracy / ACCURACY_TARGET))` with
  `ACCURACY_TARGET = 0.95` (`domain/confidence.py`), so one typo no longer
  needs about 199 clean presses before a key clears. Recency-weighted errors
  stay fractional instead of being rounded, so one typo in the previous
  lesson counts as 0.7. The transition gate now calls the same
  `clears_threshold` rule as key unlock and focus. HUD and Stats still show
  raw accuracy.

## 2.1.0

- **Session store: per-session stats instead of keystroke logs** — a finished
  session no longer writes `sessions/<YYYY-MM>/<ulid>.jsonl`. Its keystrokes
  are reduced at finish time to per-key and per-bigram tallies
  (`SessionResult.stats`, `[samples, time_ns, errors, attempts]`) stored on the
  `index.jsonl` row (schema 5). `combine_sessions` merges those tallies, so
  heatmap, unlock, focus and trend numbers are unchanged. On first start the
  app folds every existing keystroke log into its index row and deletes the
  month directories (`infrastructure/session_migration.py`). Git sync appends
  index rows only; a legacy remote row is upgraded from the clone's keystroke
  log on import.
- **Stats retention** — at startup, sessions older than the newest
  `2 * confidence_session_window - 1` per layout (the furthest the trend
  replay can reach) drop their tallies but keep their history row
  (`domain/retention.py`, `PruneSessionStats`). This is irreversible:
  raising `confidence_session_window` later only widens the window for
  sessions recorded after the change, and trend lines for the older ones
  read as empty. Migration and pruning run from `app.startup()`, called by
  the CLI before the TUI or a sync command starts — not inside the builders.

## 2.0.0

- **Breaking: `settings.toml` schema** — unlock (`min_confidence_attempts`,
  `min_transition_confidence_attempts`, `gating_bigram_limit`), focus-boost
  (`focus_char_boost`, `focus_word_boost`, `focus_bigram_word_boost`,
  `focus_transition_boost`, `focus_weak_extra_boost`, `focus_word_min_fraction`),
  and generated-word-length (`generated_word_min_len`, `generated_word_max_len`)
  fields moved off the top-level table into `[unlock]`, `[focus]`, and
  `[word_gen]` respectively (see `Settings.unlock` / `.focus` / `.word_gen` in
  `domain/models.py`). A settings file written by an older version keeps
  loading — unrecognized top-level keys are ignored and missing nested tables
  fall back to defaults — but any customized values there need re-entering
  under the new tables. New knob: `[unlock].next_letter_unlock_threshold`
  (default `1.0`), previously hardcoded. See `Confidence-Tuning` wiki for the
  full mapping.
- **Breaking: HUD no longer ticks live** — accuracy and daily-learn-minutes in
  the practice HUD are now a fixed snapshot taken when the lesson's fresh word
  set is built; they no longer update while typing and no longer dim on
  idle. They next refresh when the following lesson starts. (Previously
  documented as "live accuracy" — see README's Practice section.)
- **Alphabet-size sync moved to lesson build** — persisting a mastery-driven
  `alphabet_size` bump now happens once, right before `BuildLesson` generates
  the next lesson's text, instead of immediately when the previous session
  finishes; avoids a status jump between finishing a session and the next
  fresh word set appearing.
- Fixed a duplicate-word sampling bug in focus-word selection: `pool.index(word)`
  could remove the wrong occurrence of a repeated word, silently weakening the
  per-lesson repeat cap; sampling now tracks the drawn index directly.
- Fixed `settings.toml` writing to corrupt on values containing raw control
  characters (e.g. a stray newline) — `escape_toml_string` now escapes the
  full C0/DEL range, not just `\` and `"`.
- Fixed a bug where a boolean in an integer settings field (e.g. a hand-edited
  `alphabet_size: true`) silently coerced to `1`/`0` instead of falling back
  to the default.
- Fixed the aggregates cache to treat a genuinely corrupt cache file as a
  cache miss without also swallowing bugs in the downstream aggregate
  computation.

## 1.3.1

- **Skill vs confidence split** — unlocks and transition gating use per-key
  **skill** (min(speed, accuracy) without attempt ramp) plus attempt floors;
  **confidence** (skill scaled by practice volume) drives HUD labels, heatmap
  coloring, and focus weighting. Calibrating keys no longer block bigram focus.
- **Bigram progression** — newest-key cohort gates the next letter; deficient
  cohort bigrams get guaranteed lesson slots and prioritized practice after solo
  keys clear; transition focus when measured keys are ready but bigrams lag.
- **Dictionary vs Markov bounds** — imported words filter on dictionary length
  (3–10); Markov fill and WPM math use `generated_word_min_len` /
  `generated_word_max_len` (default 2–4).
- **Word-list focus drill** — resample real dictionary words for focus bigrams
  instead of splicing characters into imported words.
- **Heatmap and focus UX** — skill-based heatmap without lesson-sampling bias;
  calibrating focus display fixes.
- Wiki: new **Focus states** page; **Confidence tuning** updated for skill/confidence
  split, sticky focus, transition gate, and lesson WPM gate.

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
