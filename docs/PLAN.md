# keystrike — Development Plan & Handoff

> **For raphex:** This is the master plan and the current state of the project.
> Sections 1–4 describe what keystrike is and how it's designed; section 5 tells
> you exactly where things stand and what to pick up next. Read section 5 first
> if you just want to start coding. Small post-milestone fixes are logged in
> `docs/CHANGELOG.md` (newest first) rather than here, to keep this section
> from growing unbounded — check it for the detail behind anything §5
> mentions only in passing.

---

## 1. Vision

`keystrike` is an **offline, cross-platform, terminal-based typing tutor** built
in Python + Textual. It is inspired by [keybr.com](https://www.keybr.com/): the
same confidence-based adaptive engine (weakness targeting, key unlocking,
Markov-generated drills), plus a code-typing mode, free practice on user text
files, and per-layout stats — all local, no network, no cloud.

**Locked with the user (do not renegotiate without asking):**
- Python 3.12+, Textual, raw-mode per-keystroke input.
- MIT license, minimal deps — Textual, `platformdirs`, `typer`. Persistence
  uses stdlib `json` + dataclasses (no Pydantic, no msgspec).
- v1 languages: **English only**. `LanguageProvider` protocol lets
  Russian/German drop in later.
- Layouts: bundled QWERTY / Dvorak / Colemak / Colemak Mod-DH (ortholinear),
  **plus** user-loadable custom layouts from `<config>/keystrike/layouts/*.toml`.
- Lesson modes v1: adaptive (keybr port), code (Python), free (file-backed).

## 2. Architecture (ports-and-adapters, ArjanCodes lens)

Four layers, one direction of dependency:
`presentation → application → domain ← infrastructure`.

- **`domain/`** — dataclasses, enums, protocols, pure functions. Zero
  third-party imports beyond stdlib. This is where the keybr algorithm lives.
- **`application/`** — use cases orchestrating the domain (`StartSession`,
  `RecordKeystroke`, `FinishSession`, `BuildLesson`, `RebuildAggregates`).
  Depends on domain protocols only.
- **`infrastructure/`** — adapters implementing domain protocols
  (`JsonlSessionRepository`, `TomlSettingsRepository`,
  `FileAggregatesCache`, `MonotonicClock`, `UlidGenerator`,
  `CompositeLayoutRepository`, `BundledLanguageProvider`).
- **`presentation/`** — Textual `App` + screens + widgets + Typer CLI.
  Receives use cases via constructor injection.

Wiring happens exactly once in `src/keystrike/app.py` (composition root) —
no globals, no scattered `Path` reads, no repo instances outside adapters.

## 3. Package layout (target — some items unimplemented, see §5)

```
keystrike/
├── pyproject.toml
├── README.md
├── LICENSE
├── PLAN.md                                # this file
├── src/keystrike/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                             # Typer entry
│   ├── app.py                             # Composition root
│   ├── domain/
│   │   ├── models.py                      # frozen dataclasses: Keystroke, SessionResult, KeyStats, LessonKey, LessonState, Settings, KeyPos, Layout
│   │   ├── session.py                     # Session (the one mutable entity) + BACKSPACE [DONE]
│   │   ├── enums.py                       # Mode, PracticeSource, Finger, Hand, SessionState
│   │   ├── protocols.py                   # Clock, IdGenerator, SessionRepository, SettingsRepository, LayoutRepository, LanguageProvider, CodeSnippetProvider, AggregatesCache, FreeformTextProvider, StatsRebuilder, LearningRateEstimator
│   │   ├── null_adapters.py               # NullSessionRepository, NullStatsRebuilder, NullLearningRateEstimator [DONE]
│   │   ├── aggregate.py                   # pure: Keystroke → KeyStats rollup [DONE]
│   │   ├── confidence.py                  # pure: key_confidence, confidence_of, select_focus, compute_unlocked [DONE]
│   │   ├── generator.py                   # pure: AdaptiveGenerator (Markov + focus letter) [DONE]
│   │   ├── markov.py                      # TransitionTable value object + sampler [DONE]
│   │   ├── regression.py                  # pure: polynomial fit, estimate_sessions_to_goal [DONE]
│   │   └── code_lesson.py                 # pure: select_snippet (focus-char-weighted) [DONE]
│   ├── application/
│   │   ├── session_use_cases.py           # StartSession, RecordKeystroke, FinishSession, AbortSession [DONE]
│   │   ├── settings_use_cases.py          # UpdateSettings, CycleLayout [DONE]
│   │   ├── build_lesson.py                # BuildLesson, BuildCodeLesson (shared _lesson_progress) [DONE]
│   │   └── stats_use_cases.py             # RebuildAggregates, GetHeatmap, GetHistory, GetLearningRate [DONE]
│   ├── infrastructure/
│   │   ├── paths.py                       # platformdirs wrapper [DONE]
│   │   ├── clock.py                       # MonotonicClock [DONE]
│   │   ├── id_gen.py                      # UlidGenerator [DONE]
│   │   ├── atomic_write.py                # POSIX+Windows atomic replace [DONE]
│   │   ├── session_repo_jsonl.py          # JsonlSessionRepository [DONE]
│   │   ├── settings_repo_toml.py          # TomlSettingsRepository [DONE]
│   │   ├── aggregates_cache.py            # FileAggregatesCache [DONE]
│   │   ├── layout_repo.py                 # CompositeLayoutRepository [DONE]
│   │   ├── layout_toml.py                 # TOML → Layout parser [DONE]
│   │   ├── bundled_layouts/{qwerty,dvorak,colemak,colemak_dh}.py + _grid.py [DONE]
│   │   ├── freeform.py                    # FileFreeformTextProvider [DONE]
│   │   ├── code_generators/python.py      # PythonCodeGenerator (bundled snippet corpus) [DONE]
│   │   └── languages/
│   │       ├── __init__.py                # BundledLanguageProvider [DONE]
│   │       └── data/en_markov.json.gz     # ~22 KB order-2 transitions [DONE]
│   └── presentation/
│       ├── textual_app.py                 # KeystrikeApp [DONE]
│       ├── theme.py                       # color roles [DONE]
│       ├── screens/{home,practice,results}.py [DONE]
│       ├── screens/{stats,settings}.py    [DONE]
│       └── widgets/{typing_area,hud}.py   [DONE — HUD now shows sessions-to-goal]
│       └── widgets/kb_heatmap.py [DONE] (key_progress.py still deferred, see M5)
├── scripts/
│   └── build_markov.py                    # dev-only, regenerates data/*.json.gz [DONE]
└── tests/
    ├── conftest.py                        # pytest fixtures
    ├── fakes.py                           # in-memory fakes for every domain protocol
    ├── test_architecture.py               # layering fitness functions [DONE]
    ├── domain/                            # pure-function tests
    ├── application/                       # use-case tests with fakes
    ├── infrastructure/                    # real-filesystem tests in tmp_path
    └── presentation/                      # textual pilot.press tests
```

## 4. Conventions

- **Data model**: value objects are `frozen=True, slots=True` dataclasses. Only
  `Session` (the running one, in `domain/session.py`) is mutable — it's a
  domain *entity*, not a value object, which is why it lives next to the
  frozen ones instead of in `application/`.
- **Protocols for every I/O boundary.** New I/O? Add a `Protocol` in
  `domain/protocols.py` first, then implement in `infrastructure/`.
- **Null Objects over `X | None` + scattered `is not None` checks.** Optional
  collaborators (e.g. `SessionRepository`, the stats-rebuild callback) get an
  inert default implementation in `domain/null_adapters.py`, not a `None`
  default plus a conditional in the use case body.
- **Every *write* to Settings goes through an application use case**
  (`UpdateSettings`, `CycleLayout` in `application/settings_use_cases.py`),
  never straight from a Screen to `SettingsRepository.save()`. Screens may
  still *read* a repository directly (that's not a business decision).
- **Fakes over mocks.** In-memory adapters live in `tests/fakes.py`. Domain
  and application tests use fakes; only infrastructure tests touch the real
  filesystem via `tmp_path`.
- **No new deps without asking.** Deps posture is locked (see §1). If you
  genuinely need a new dep, propose it in a commit message first.
- **No comments explaining *what* code does.** Only *why*, when non-obvious.
  Well-named identifiers do the rest.
- **Composition root only in `app.py`.** Screens/widgets receive
  dependencies via `__init__` — never construct repos or read `Path()`
  themselves. `tests/test_architecture.py` enforces the layering rule
  (`presentation → application → domain ← infrastructure`) automatically —
  run it (or the full suite) after moving code between layers.

### Tooling

- `uv sync --no-dev` — runtime deps only (textual, typer, platformdirs).
- `uv sync` — runtime + `dev` group (pytest, pyright, …; pure Python,
  Android-safe).
- `uv sync --all-groups` — also `lint` group (Ruff; desktop only).
- `uv run keystrike run` — launch the TUI.
- `uv run pytest -q` — tests.
- `uv run pyright` — strict type check (relaxed for `tests/`).
- `uv run ruff check` / `uv run ruff format` — lint + format (needs
  `--all-groups` or `--group lint`).

Ruff, pyright, and pytest must be green before commit (Ruff on desktop only).

## 5. Current status (as of this handoff)

### What works right now

- **M1 shipped.** `uv run keystrike run` opens the Home screen, Practice
  captures keystrokes raw via `on_key`, HUD updates at 10 Hz, Results screen
  on completion. Backspace rewinds without double-counting; wrong chars
  don't advance the cursor.
- **M2 shipped end-to-end (a–e all done).** 78 tests pass; `ruff check` and
  `pyright` (strict) are both fully clean.
  - **M2a** — persistence layer: `domain/aggregate.py`,
    `infrastructure/session_repo_jsonl.py`, `settings_repo_toml.py`,
    `aggregates_cache.py`, `atomic_write.py`. All lint/type findings from the
    prior handoff (PLW2901, PLC0415, reportArgumentType, reportOperatorIssue)
    are fixed.
  - **M2b** — `infrastructure/bundled_layouts/{qwerty,dvorak,colemak}.py`
    (built via a shared `_grid.py` helper: real QWERTY/Dvorak/Colemak key
    positions, finger/hand by physical column, learn_order by English letter
    frequency), `layout_toml.py` (TOML → `Layout` parser with descriptive
    `file: keys[i].field ...` errors), `layout_repo.py`
    (`CompositeLayoutRepository`, bundled takes priority on name collision).
    Verified live: dropping a hand-written `<config>/keystrike/layouts/*.toml`
    is picked up by `list_available()`/`get()` without code changes.
  - **M2c** — `application/stats_use_cases.py` (`RebuildAggregates`,
    `GetHeatmap` — confidence = target_ms_per_char / mean_ms_per_key,
    `GetHistory`), `presentation/widgets/kb_heatmap.py` (3-row ASCII grid,
    color by confidence), `presentation/screens/stats.py`.
  - **M2d** — `infrastructure/freeform.py` (`FileFreeformTextProvider`,
    paragraph-preserving wrap), `domain/protocols.py` gained
    `FreeformTextProvider`. `presentation/screens/home.py` rewritten with a
    real menu (Enter=sample practice, f=free practice, s=Stats, o=Settings,
    l=cycle layout) and `presentation/screens/settings.py` (layout/theme
    `Select`s, target-speed/freeform-path `Input`s, Ctrl+S save / Esc cancel).
  - **M2e** — `app.py` composition root now builds all real adapters via
    `default_paths()` + `ensure_dirs()` and wires them into `KeystrikeApp`.
    `KeystrikeApp` routes `HomeScreen` messages to Practice/Stats/Settings.
    Fixed a real bug found during end-to-end verification: `ResultsScreen`'s
    Enter/Escape used to call `app.exit()` (quitting the whole app) instead
    of returning to Home — changed to `action_back_to_home` /
    `self.app.pop_screen()`, `q`/`Ctrl+Q` still quit.

  End-to-end verification performed (isolated `XDG_*` temp dirs, driven via
  `Pilot`): Home → Practice → Results → Home with no crash; finishing a
  session persists a header + keystroke JSONL and Stats immediately shows
  real WPM/accuracy for that layout; switching layout via `l` shows an empty
  history on the new layout (per-layout isolation confirmed); a hand-written
  custom layout TOML is discovered without a restart.

### M2 verification checklist — all done

- [x] `uv run pytest -q && uv run ruff check && uv run pyright` — all green on
  macOS (Linux/Windows CI matrix still deferred to M5).
- [x] `uv run keystrike run` end-to-end: Home → Practice → Results → back to
  Home without crashes.
- [x] Session appears under `<data>/sessions/YYYY-MM/{ulid}.jsonl` and its
  header appears in `<data>/sessions/index.jsonl` after finishing a session.
- [x] Switching layout on Home changes which per-layout heatmap/history shows
  on Stats (confirmed empty-history isolation on the unused layout).
- [x] Dropping a hand-written layout TOML into `<config>/keystrike/layouts/`
  makes it selectable without restart (v1 restart-on-add was the fallback
  plan, but it turned out not to be needed — `CompositeLayoutRepository`
  re-globs the directory on every call).

### ArjanCodes-lens architecture review — findings fixed

A full-codebase review against the M2 state turned up 5 findings + 3 minors,
all fixed before M3 began (95 tests passing at that point) — see
`docs/CHANGELOG.md`.

### M3 — Adaptive engine: shipped

`domain/markov.py` (`TransitionTable` with order-2 sampling + backoff to
shorter contexts, filtered to the unlocked alphabet), `domain/generator.py`
(`AdaptiveGenerator`: word length 3–10, `p_stop = min(1, 1.3**length/max_len)`,
focus letter guaranteed via injection if the Markov walk didn't produce it),
`domain/confidence.py` (`confidence_of`, `compute_unlocked`, `select_focus` —
faithful to §6 below), `application/build_lesson.py` (`BuildLesson` ties
layout + stats + settings + language provider into a `Lesson(text, state)`),
`infrastructure/languages/` (`BundledLanguageProvider`, gzip+JSON), and
`scripts/build_markov.py` (dev-only — builds the order-2 table from
macOS's `/usr/share/dict/words`, ~211k words filtered to common lowercase
entries → 636 contexts → ~22 KB gzipped; rerun it if the corpus or `ORDER`
changes).

Wired into presentation: Home's `Enter` now starts an **adaptive** lesson
(was sample-text practice — that moved to `p`); `KeystrikeApp` calls
`BuildLesson` and passes the resulting `focus_key` through
`StartSession`/`PracticeScreen` so it round-trips into the persisted
`SessionResult.focus_key`.

Verified end-to-end through the real composition root (`build()`, isolated
`XDG_*` dirs): first adaptive lesson on a cold-start layout unlocks
`round(alphabet_size * len(learn_order))` keys and focuses the weakest one
(`'e'`, first in the frequency-based learn order); after completing it,
opening a second adaptive lesson picks a *different* focus key (`'u'`),
confirming the `RebuildAggregates → BuildLesson` feedback loop actually reads
back real persisted performance, not stale/cached data.

### M4 — Code mode + regression predictor: shipped

`domain/regression.py` — polynomial least-squares fit with **no numpy**
(deps are locked, see §1): normal equations solved via Gaussian elimination
with partial pivoting, degree chosen by sample count (linear ≤10, quadratic
11–20, cubic >20, capped at the last 30 samples).
`estimate_sessions_to_goal(recent_time_ns, target_time_ns)` fits the trend and
returns how many more attempts until it crosses the target, `0` if already
there, or `None` if flat/worsening/no data.

`domain/aggregate.py` gained `per_key_deltas()` — the chronological
inter-keystroke timing sequence per codepoint that `aggregate_session` already
computed internally but only reduced to a mean; regression needs the raw
sequence, so this was factored out and reused rather than duplicated.
`application/stats_use_cases.py` gained `GetLearningRate(layout, codepoint)`,
which reads the last 10 sessions' raw deltas for that key and feeds them to
`estimate_sessions_to_goal`. Wired into `presentation/widgets/hud.py`: the HUD
now shows `Goal[<focus char>]: ~N sessions` (or `learning…` before there's
enough data) whenever the practice session has a focus key (adaptive or code
mode) — computed once at `PracticeScreen` construction, not per keystroke.

`domain/code_lesson.py` (`select_snippet`) + `infrastructure/code_generators/
python.py` (`PythonCodeGenerator`, 10 original hand-written snippets — real
library/stdlib source was deliberately avoided to sidestep any licensing
question) implement code mode. **Scope decision**: code mode does *not* reuse
M3's hard alphabet-filter approach, because Python syntax has mandatory
characters (`():=_[]"`) that aren't part of any `Layout.learn_order` — a
strict filter would reject nearly every real snippet. Instead
`select_snippet` weight-picks by how often the snippet contains the focus
char (`snippet.count(focus_char) + 1`), so unlock/focus state still comes
from the exact same `compute_unlocked`/`select_focus` logic as English mode
(factored out to `_lesson_progress()`, shared by `BuildLesson` and the new
`BuildCodeLesson` in `application/build_lesson.py`) — it just doesn't gate
which literal characters can appear in the practice text.
**Second scope decision**: snippets are flattened to a single line
(indentation stripped, lines joined by one space) rather than adding
multi-line/Enter-key typing support — that would have been a materially
larger UI change (cursor rendering across lines, a new key binding, revisiting
every offset-based render/test assumption in `typing_area.py`) than this
milestone's stated scope. Revisit if real multi-line code practice is wanted.

Home gained a `c` binding (Code) alongside `Enter` (Adaptive), `p` (Sample),
`f` (Free). Verified end-to-end through the real composition root: `c` builds
a real flattened Python snippet, HUD shows `Goal[e]: learning…` on a fresh
layout, session completes and shows up correctly in Stats (codepoints outside
the 26-letter+punctuation heatmap grid — like `(`, `:`, `_` — are aggregated
and persisted fine; they just don't render on the 3-row ASCII keyboard, which
only ever drew the letter/punctuation grid).

### Fourth bundled layout: Colemak Mod-DH (ortholinear)

`infrastructure/bundled_layouts/colemak_dh.py` — wired into
`layout_repo.BUNDLED_LAYOUTS` alongside qwerty/dvorak/colemak. Needed
`Layout.ortholinear: bool` (a rendering hint only — no effect on
finger/hand assignment or adaptive-engine math) so the Stats heatmap renders
aligned columns instead of a staggered stairstep; see `docs/CHANGELOG.md` for
both entries.

### Small fixes since M4

Timer-doesn't-start-until-first-keystroke, backspace disabled in Adaptive
mode, and the accuracy-aware confidence fix — see `docs/CHANGELOG.md` for
each; not repeated here to keep this section from growing unbounded.

### M5 — Release: shipped (1.0.0)

- Snapshot tests in optional `snapshot` group (`pytest-textual-snapshot`; kept
  out of default `dev` — pulls `jinja2` → `markupsafe`, no Android wheels).
- PyPI publish (`uv tool install keystrike`); `pyproject.toml` metadata updated
  (author, `egno/keystrike` URLs, Production/Stable classifier).
- README with demo GIF (`docs/assets/demo.gif`), Windows Terminal setup docs.
- Linux/Windows/macOS CI matrix (Python 3.12/3.13) + snapshot job on macOS.
- `presentation/widgets/key_progress.py` still deferred — heatmap covers the
  per-key view for v1.

## 6. Keybr algorithm — cheat sheet

Pre-researched from `github.com/aradzie/keybr.com`. Reuse this — do not
re-investigate. Every § below is now implemented: Confidence/Unlock/Focus
letter/Text generation as of M3 (`domain/confidence.py`, `markov.py`,
`generator.py`, `application/build_lesson.py`); Learning-rate and Code mode
as of M4 (`domain/regression.py`, `code_lesson.py`,
`infrastructure/code_generators/python.py`) — see the scope decisions noted
above for where code mode deliberately diverges from a literal reading of
"same adaptive alphabet".

- **Confidence**: `confidence = target_speed_ms_per_char / mean_time_ns_per_key`.
  Ratio > 1.0 = above target; < 1.0 = below.
- **Unlock**: iterate `keyboard_order(layout)` (row-weighted: home row, then
  top row, then everything else — see docs/research/typing-pedagogy.md);
  force-include the first `alphabet_size` keys (a literal count, capped at
  `len(order)`), then unlock next only when
  `all(confidence[k] >= threshold for k in unlocked)`. Confidence is always
  live (recomputed from current speed+accuracy), never a stored historical
  peak.
- **Focus letter**: `min(unlocked, key=confidence)`. Injected into at least
  one generated word.
- **Text generation**: Markov chain over order-2 transitions filtered to
  `alphabet`. Termination `p_stop = min(1, 1.3**length / max_len)`. Reject
  words with length ∉ `[min_len, max_len]` (max 5 retries).
- **Learning-rate**: polynomial fit (linear ≤10, quadratic 11–20, cubic >20
  samples) over last 30 per-key samples → estimate sessions-to-goal.
- **Code mode**: same adaptive alphabet, pluggable per-language generator.

Full research report in the conversation transcript that spawned this plan;
if you need to re-read it, check `~/.claude/plans/quiet-snuggling-aurora.md`.

---

**Handoff note**: this project uses ArjanCodes-style clean architecture
throughout — layered directories, protocols for I/O, DI in constructors,
fakes over mocks in tests. Keep it that way. When in doubt, prefer moving
logic *up* toward the domain and *away* from Textual.
