# Advisor plugins — design

Status: **proposed** (not implemented). Branch: `refactor/advisor-plugins`.
Replaces the built-in AI coach (`AiAnalyzer`, commit `93d297c`) with a
general advice system. Any advisor — hardcoded rules, a small local ML
model, an LLM — plugs into the same interface.

The design follows the ArjanCodes approach that `PLAN.md` §2 already uses:
Protocols over base classes, functions over one-method classes, composition
over inheritance, dependency injection instead of global state, creation
apart from use, small interfaces. The plugin mechanism is his
registry + loader + `register()` pattern, with Python entry points for
discovery.

## 1. Goals

1. **The core stays fully local.** The core package never sends practice
   data off the device. Code that does so lives only in a plugin that the
   user installs on purpose.
2. **Any kind of advisor.** Rules, ML and LLM advisors use one interface.
   The core does not know which kind is active.
3. **Advice can never harm the course.** No advisor can delay an unlock,
   push weights out of bounds, or name a locked key. The core enforces
   this, not the plugin.
4. **Useful without plugins.** The core ships a rules advisor.
5. **Plugins stay small.** A plugin computes advice from data. It does not
   draw UI, schedule work, store files, or depend on Textual.

## 2. Non-goals (for now)

- **More than one active advisor.** The user picks one. The API allows
  merging later (§11) without a change.
- **UI widgets from plugins.** The core draws everything.
- **Sandboxing.** Plugins run in the same process. Installing a plugin is
  the trust decision (§8).
- **A compatibility layer for old plugin APIs.** One version number,
  checked at load time.

## 3. Overview

```
            ┌──────────────── core (keystrike) ────────────────────────────┐
 session    │  FinishSession ──► AdviceRunner ──► build_advisor_context()  │
 finished ──┼─►                     │                  │                   │
            │                       │      AdvisorContext (read-only data) │
            │                       ▼                  ▼                   │
            │                 active Advisor  ◄── AdvisorRegistry          │
            │                 (a function)          ▲     ▲                │
            │                       │               │     │ register()     │
            │                LessonAdvice           │  advisors/rules.py   │
            │                       ▼               │                      │
            │            validate_advice() (pure)   │                      │
            │                       ▼          plugin_loader (entry points)│
            │                  AdviceStore          │                      │
            │                       ▼               │                      │
 next       │  BuildLesson ──► apply_advice() (pure: tie-breaker, bounds)  │
 lesson ◄───┤                                                              │
            └───────────────────────────────────────┼──────────────────────┘
                                                    │ register()
                              ┌─────────────────────┴───────┐
                              │ plugins: keystrike-ai (LLM),│
                              │ keystrike-ml, third parties │
                              └─────────────────────────────┘
```

**The core owns** feature extraction, validation, the tie-breaker rule,
scheduling, time budgets, error isolation, persistence, privacy controls,
and all UI.

**An advisor owns** one thing: turning an `AdvisorContext` into a
`LessonAdvice`.

## 4. Domain types (`domain/advice.py`)

Plain frozen dataclasses and one type alias. Stdlib only, like all of
`domain/`.

```python
Advisor = Callable[[AdvisorContext], Awaitable[LessonAdvice]]
"""An advisor is a function. A stateless advisor (rules) is a plain
`async def`; an advisor with state (an LLM client, a loaded model) is a
closure or a callable object. No base class."""


@dataclass(frozen=True, slots=True)
class CourseState:
    unlocked: tuple[int, ...]          # learning order; last = newest key
    target_cpm: int
    confidence: Mapping[int, float]

    @property
    def newest(self) -> int | None: ...


@dataclass(frozen=True, slots=True)
class AdvisorContext:
    """Everything an advisor may read. Built by the core; read-only."""

    layout: str
    sessions: tuple[SessionResult, ...]       # newest first, confidence window
    course: CourseState
    insights: KeystrokeInsights               # mistypes, errors per finger
    keystrokes: Mapping[str, Sequence[Keystroke]]   # empty unless needs_keystrokes


@dataclass(frozen=True, slots=True)
class LessonAdvice:
    """What an advisor returns. Codepoints only."""

    source: str = ""                  # advisor name; set by the runner
    summary: str = ""
    focus_key: int | None = None
    focus_pair: Bigram | None = None
    emphasis_keys: tuple[int, ...] = ()
    rest_keys: tuple[int, ...] = ()
    created_at: float = 0.0           # set by the runner

    @property
    def actionable(self) -> bool: ...


EMPTY_ADVICE = LessonAdvice()


@dataclass(frozen=True, slots=True)
class AdvisorCapabilities:
    needs_keystrokes: bool = False        # core keeps raw keystrokes only if True
    sends_data_off_device: bool = False   # core asks for explicit opt-in if True


@dataclass(frozen=True, slots=True)
class SettingField:
    """One config value an advisor needs. The core draws the form from
    these, so plugins never import Textual."""

    name: str
    label: str
    default: str = ""
    choices: tuple[str, ...] = ()   # non-empty: a select instead of a text input
    env_hint: str = ""              # e.g. "KEYSTRIKE_AI_API_KEY"; shown, never stored


@dataclass(frozen=True, slots=True)
class AdvisorSpec:
    """How to create an advisor. Kept apart from the advisor itself:
    creation (config parsing, client set-up) is not use."""

    name: str                       # "rules", "llm", "ml"; also the HUD tag
    label: str                      # Settings screen
    capabilities: AdvisorCapabilities
    settings: tuple[SettingField, ...]
    create: Callable[[Mapping[str, str]], Advisor]
    """Parse and validate the advisor's own config section. Raise
    `ValueError` on bad config; the core shows the message."""
```

### Pure functions that keep advice safe

Also in `domain/advice.py`. Both functions are always called by the core
on every advice, whatever the source.

```python
@dataclass(frozen=True, slots=True)
class FocusChoices:
    """What advice may pick as focus at the engine's current stage."""
    keys: frozenset[int]
    pairs: frozenset[Bigram] | None    # None = any pair of `keys`


def validate_advice(advice: LessonAdvice, course: CourseState) -> LessonAdvice:
    """Keep unlocked keys only; at most 5 keys per list; no key on both
    lists; never rest the newest key; summary at most 200 characters."""


def apply_advice(progress: LessonProgress, advice: LessonAdvice,
                 choices: FocusChoices) -> LessonProgress:
    """Tie-breaker: move the focus only inside `choices`. Weights are
    multiplied by fixed, bounded factors (emphasis 1.5, rest 0.7); the
    focus key and the newest key are never rested."""
```

`FocusChoices` comes from the engine stage (today `_coach_choices` in
`build_lesson.py`):

| Engine stage (`select_lesson_focus`) | Advice may pick |
| --- | --- |
| 1. Some unlocked keys not cleared | any uncleared key; no pairs |
| 2. Newest key's gate pairs block | only those gate pairs |
| 3–4. Review / weakest key | any unlocked key or pair |

Every stage must finish before the next unlock, so reordering work inside a
stage never delays an unlock.

### Null Object

Per `PLAN.md` §4 ("Null Objects over `X | None`"), "Off" is an advisor:

```python
async def null_advisor(_ctx: AdvisorContext) -> LessonAdvice:
    return EMPTY_ADVICE

NULL_ADVISOR_SPEC = AdvisorSpec(name="off", label="Off", capabilities=AdvisorCapabilities(),
                                settings=(), create=lambda _cfg: null_advisor)
```

## 5. Registry and loader (the plugin mechanism)

### `application/advisor_registry.py`

```python
class AdvisorRegistry:
    """Name → AdvisorSpec. Created once in app.py and passed in; never a
    module-level global."""

    def __init__(self) -> None:
        self._specs: dict[str, AdvisorSpec] = {NULL_ADVISOR_SPEC.name: NULL_ADVISOR_SPEC}

    def register(self, spec: AdvisorSpec) -> None:
        """Raise ValueError on a duplicate name."""

    def specs(self) -> list[AdvisorSpec]: ...
    def get(self, name: str) -> AdvisorSpec:
        """Unknown name → NULL_ADVISOR_SPEC (a removed plugin turns advice off)."""
```

### `plugin_api.py` — the public facade

The only module that plugins may import. It re-exports the types in §4, the
`AdvisorRegistry` type, the shared helpers in §6, and:

```python
PLUGIN_API_VERSION = 1

class PluginModule(Protocol):
    API_VERSION: int
    def register(self, registry: AdvisorRegistry) -> None: ...
```

Change `PLUGIN_API_VERSION` on any change that breaks plugins.

### `infrastructure/plugin_loader.py`

```python
ENTRY_POINT_GROUP = "keystrike.advisors"

def load_plugins(registry: AdvisorRegistry) -> list[str]:
    """Import every entry-point module, check API_VERSION, call register().
    A failing plugin is skipped; return its error so the UI can show it."""
```

A plugin package declares itself in its own `pyproject.toml`:

```toml
[project.entry-points."keystrike.advisors"]
llm = "keystrike_ai"
```

and its module is:

```python
# keystrike_ai/__init__.py
from keystrike.plugin_api import AdvisorCapabilities, AdvisorSpec, SettingField

API_VERSION = 1

def register(registry) -> None:
    registry.register(AdvisorSpec(
        name="llm", label="LLM (Ollama / OpenAI-compatible)",
        capabilities=AdvisorCapabilities(needs_keystrokes=True, sends_data_off_device=True),
        settings=(SettingField("provider", "Provider", "ollama", choices=("ollama", "openai")),
                  SettingField("model", "Model", "llama3.2"),
                  SettingField("endpoint", "Endpoint", "http://localhost:11434",
                               env_hint="KEYSTRIKE_AI_API_KEY")),
        create=create_llm_advisor,
    ))
```

### Built-in advisors use the same path

`advisors/rules.py` has a `register(registry)` function too. `app.py`
calls it before `load_plugins`. So the plugin path runs on every start,
not only when a plugin is installed.

## 6. Shared feature extraction

Advisors must not rebuild the same features. The core builds them once
per request, in `build_advisor_context()` (application layer):

- **Per-key and per-pair digest** across the window, limited to unlocked
  keys (today `_Digest` in `ai_analyzer.py`).
- **Course state** from the latest session header.
- **Keystroke insights** (`domain/keystroke_insights.py`): repeated
  mistypes and errors per finger. Built only when raw keystrokes exist.

`plugin_api` re-exports small helpers (`error_rate_ranked(keys)`,
`format_char(cp)`) so that an LLM prompt and a rules advisor sort keys in
the same way.

## 7. Running advice (`application/advice_runner.py`)

`AdviceRunner` is built from parts passed in (composition). No subclass.

```python
@dataclass(slots=True)
class AdviceRunner:
    registry: AdvisorRegistry
    config_repo: AdvisorConfigRepository     # domain/protocols.py
    store: AdviceStore                       # domain/protocols.py
    archive: KeystrokeArchive                # domain/protocols.py
    history: GetHistory
    wall_epoch: Callable[[], float]
    budget_s: float = 0.15

    def capabilities(self) -> AdvisorCapabilities: ...
    async def request(self, layout: str) -> LessonAdvice: ...
    def current(self, layout: str) -> LessonAdvice: ...   # for BuildLesson
    def forget(self) -> None: ...
```

Rules the runner enforces:

1. **One request at a time.** A session that finishes during a request
   marks one follow-up request. Several such sessions still give one
   follow-up. Requests are never cancelled, so a slow advisor always
   answers. (Already the behavior of `PracticeScreen` today; it moves here.)
2. **Time budget.** After a session, the practice screen awaits
   `request()` for at most `budget_s` before it builds the next lesson.
   - Fast advisors (rules, ML) finish in time: their advice steers the
     **next** lesson.
   - Slow advisors (LLM) go over the budget: the next lesson uses the
     previous advice, and the new advice steers the lesson after.

   The wait uses `asyncio.shield`, so the timeout does not cancel the
   request. `PracticeScreen._finish_session` becomes `async` for this.
3. **Error isolation.** Any exception from `create` or from the advisor
   becomes a failed result for the panel. Practice continues, and the last
   good advice stays in effect.
4. **Validation.** Every result goes through `validate_advice` before
   anyone sees or stores it.
5. **Persistence.** The last good advice is stored per **(layout,
   advisor name)**. When the user switches advisors, the old advice is not
   used.
6. **Source tag.** The runner sets `source` and `created_at`; advisors
   cannot forge them.

## 8. Privacy and trust

- **Raw keystrokes.** `FinishSession` writes them to the archive only if
  the active advisor has `needs_keystrokes`. Otherwise it clears the
  archive. Retention: the sessions in each layout's confidence window
  (today's rule).
- **Opt-in for data sent off the device.** Selecting an advisor with
  `sends_data_off_device` shows a one-time notice. The notice says what is
  sent (per-key statistics, mistypes, errors per finger) and asks to
  confirm. The confirmation is stored per advisor name.
- **The capability flags cannot be enforced.** Plugin code runs in the
  core's process and can do anything Python can. The docs say this plainly:
  installing a plugin means trusting it.
- **The core has no network code for advice.** It is enforced by test (§10).
  Word-list import and git sync still use the network; both run only when
  the user starts them.

## 9. Configuration and UI

- **`advisors.toml`** in the config directory. Not in the git-sync set
  (`sync_git._SYNC_REL_PATHS`), so each device decides for itself.

  ```toml
  active = "rules"
  confirmed_off_device = ["llm"]

  [llm]
  provider = "ollama"
  model = "llama3.2"
  endpoint = "http://localhost:11434"
  ```

  Each section is a plain `str → str` mapping. The plugin's `create`
  parses it into its own typed config.
- **Secrets** never go into the file. A `SettingField.env_hint` tells the
  user which environment variable to set.
- **Settings screen:** a select for the active advisor (from
  `registry.specs()`), then a form drawn from the active spec's
  `settings`. `Ctrl+T` runs one request against sample data and shows the
  result or the error.
- **Advice panel** (`presentation/widgets/advice_panel.py`) draws a
  `LessonAdvice`: summary, focus, "Practice more", "Ease up on".
- **HUD tag:** `FocusReason.advisor: str | None` replaces
  `FocusReason.coach: bool`. The HUD shows the advisor name before the
  reason: `rules wk`, `llm rev`.
- **Session header:** a new optional field, `advice_source`, records which
  advisor steered the lesson. It is written only when set, like
  `focus_pair`, so old rows read back unchanged. Later the Stats screen can
  compare progress per advisor.

## 10. Layers and enforced rules

```
src/keystrike/
  domain/advice.py                  types + validate_advice / apply_advice (pure)
  domain/keystroke_insights.py      (exists)
  domain/protocols.py               + AdviceStore, AdvisorConfigRepository
  application/advisor_registry.py
  application/advice_runner.py
  application/advisor_context.py    build_advisor_context()
  advisors/rules.py                 built-in advisor
  infrastructure/plugin_loader.py
  infrastructure/advice_store.py    cache/advice.json
  infrastructure/advisor_config_toml.py
  plugin_api.py                     public facade
  presentation/widgets/advice_panel.py
packages/keystrike-ai/              LLM advisor plugin (separate distribution)
  src/keystrike_ai/{__init__,clients,prompt}.py
```

New rules in `tests/test_architecture.py`:

| Rule | Why |
| --- | --- |
| `advisors/` imports only `domain` and `plugin_api` | built-ins are held to the plugin rules |
| `plugin_api.py` imports only `domain` and `application` | a thin facade, no I/O |
| `packages/*` import only `keystrike.plugin_api` from `keystrike` | plugins cannot depend on internals |
| the core imports no `urllib`, `http`, `socket` except `wordlist_*` and `sync_*` modules | "fully local" is checked, not promised |

## 11. Later: more than one advisor

Not built now. When needed:
- Order advisors by priority.
- **Focus:** the first advisor whose pick is inside `FocusChoices`.
- **Weights:** multiply the factors, then clip to the same bounds.
- **Summary:** show each advisor's summary, tagged with its source.

The `Advisor` type and `LessonAdvice` do not change.

## 12. Testing

- **Pure functions** (`validate_advice`, `apply_advice`, insights):
  table tests, no fakes needed.
- **Runner:** fake advisors (plain `async def`), `FakeAdviceStore`,
  `FakeKeystrokeArchive`. Cases:
  - slow advisor: no cancellation, one follow-up request
  - budget: a fast advisor steers the next lesson; a slow one does not
  - errors: exceptions are isolated and the last good advice stays
  - keys: forged or locked keys are dropped
- **Loader:** a fake `entry_points` returning test modules. Cases: a good
  plugin, an API version mismatch, a `register` that raises, a duplicate
  name.
- **Rules advisor:** golden tests on fixed contexts.
- **Plugin package:** its own tests (clients with a fake `urlopen`, as
  today), plus a contract test from the core that every registered spec
  returns a valid `LessonAdvice` on a sample context within its budget.

## 13. Migration from the current AI coach

| Now (`93d297c`) | After |
| --- | --- |
| `domain/ai_models.py`: `AiAnalysis` | `domain/advice.py`: `LessonAdvice` |
| `domain/ai_models.py`: `AiSettings` | `[llm]` section in `advisors.toml` |
| `application/ai_analyzer.py` | runner + context → core; prompt + parsing → plugin |
| `application/ai_settings_use_cases.py` | `UpdateAdvisorConfig`, `TestAdvisor` (core, generic) |
| `infrastructure/ai_clients.py` | `keystrike_ai/clients.py` |
| `infrastructure/ai_settings_repo_toml.py` | `advisor_config_toml.py` (reads `ai.toml` once, migrates) |
| `infrastructure/ai_analysis_store.py` | `advice_store.py`, keyed by (layout, advisor) |
| `build_lesson._coach_choices`, `_apply_ai_*` | `domain/advice.py` (`FocusChoices`, `apply_advice`) |
| `FocusReason.coach: bool` | `FocusReason.advisor: str \| None` |
| `presentation/widgets/ai_panel.py` | `advice_panel.py` |
| scheduling in `PracticeScreen` | `AdviceRunner` |

Steps. Each one leaves the full suite passing:

1. **Domain types and pure functions.** Add `domain/advice.py`; move
   `FocusChoices` / `apply_advice` out of `build_lesson.py`; rename
   `AiAnalysis` → `LessonAdvice`, `coach` → `advisor`.
2. **Registry, loader, facade.** Add `AdvisorRegistry`, `plugin_api.py`,
   `plugin_loader.py`, the Null advisor.
3. **Runner.** Add `AdviceRunner` with the scheduling from
   `PracticeScreen`, and the time budget. Wrap the current LLM code as an
   in-repo advisor registered through `register()`.
4. **Rules advisor.** Add `advisors/rules.py`. Make it the default.
5. **Generic settings UI.** Add `advisors.toml`, the form drawn from
   `SettingField`, and the opt-in notice.
6. **Extract the plugin.** Move the LLM advisor to `packages/keystrike-ai`
   (uv workspace). Add the architecture rules in §10.
7. **Record the source.** Add `advice_source` to the session header.
8. **Docs.** Update the README, the wiki and the CHANGELOG.

## 14. Rules advisor (first version)

Deterministic, about 50 lines, no dependencies:

- **Focus:** the key with the highest shrunk error rate
  (`errors / (attempts + 3)`). Leave it to the engine if no key clears a
  minimum rate (for example 8 %).
- **Emphasis:**
  - both keys of each repeated mistype (`s` typed as `d` → `s`, `d`)
  - the keys of the finger with the highest error rate, if it is clearly
    above the average
- **Rest:** keys with confidence ≥ 1.0 and an error rate below 2 %. Never
  the newest key.
- **Summary:** one sentence from a template, for example
  "You often type d for s — practice s and d."

## 15. Risks

| Risk | Handling |
| --- | --- |
| Plugin API locks in early mistakes | Keep it small (one function type, one spec); version number; no compatibility layer before 1.0 of the API |
| A plugin slows down every start | Load plugins once; `create` runs only for the active advisor |
| A plugin blocks the event loop | Document that blocking work must use `asyncio.to_thread`; the time budget limits the damage only for the post-session wait |
| Two packages drift apart | One repo (uv workspace), shared CI, contract test from the core |
| Rules advisor on by default changes lessons for current users | Its effect is bounded by `apply_advice`; mention it in the CHANGELOG; "Off" is one select away |

## 16. Open decisions

1. **Default advisor:** `rules` (proposed) or `off`.
2. **Plugin package name:** `keystrike-ai` (proposed) or `keystrike-llm`.
3. **Time budget value:** 150 ms (proposed). Should the user be able to
   change it?
