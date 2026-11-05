"""AdviceRunner: schedules the active advisor, isolates its errors, validates
and stores its advice. Built from parts passed in (composition).

Rules the runner enforces (docs/ADVISOR-PLUGINS.md §7):

1. One request at a time. Sessions that finish during a request give one
   follow-up request. Requests are never cancelled, so a slow advisor
   always answers.
2. Any exception from `create` or from the advisor becomes a failed
   result; practice continues and the last good advice stays in effect.
3. Every result goes through `validate_advice` before anyone sees it.
4. The last good advice is kept per (layout, advisor name).
5. The runner sets `source` and `created_at`; advisors cannot forge them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

from keystrike.application.advisor_context import build_advisor_context
from keystrike.application.advisor_registry import AdvisorRegistry
from keystrike.application.stats_use_cases import GetHistory
from keystrike.domain.advice import (
    EMPTY_ADVICE,
    NOT_ENOUGH_DATA,
    NULL_ADVISOR_NAME,
    Advisor,
    AdvisorCapabilities,
    AdvisorSpec,
    LessonAdvice,
    validate_advice,
)
from keystrike.domain.models import KeyPos, Keystroke
from keystrike.domain.null_adapters import NULL_LAYOUT_REPOSITORY
from keystrike.domain.protocols import (
    AdviceStore,
    AdvisorConfigRepository,
    KeystrokeArchive,
    LayoutRepository,
    SettingsRepository,
)

logger = logging.getLogger(__name__)

DEFAULT_BUDGET_S = 0.15


@dataclass(slots=True)
class AdviceRunner:
    registry: AdvisorRegistry
    config_repo: AdvisorConfigRepository
    store: AdviceStore
    archive: KeystrokeArchive
    history: GetHistory
    settings_repo: SettingsRepository
    layout_repo: LayoutRepository = NULL_LAYOUT_REPOSITORY
    wall_epoch: Callable[[], float] = lambda: 0.0
    # How long the practice screen waits for `request()` before it builds the
    # next lesson. A fast advisor steers the next lesson; a slow one, the
    # lesson after.
    budget_s: float = DEFAULT_BUDGET_S
    _advisors: dict[tuple[str, tuple[tuple[str, str], ...]], Advisor] = field(
        default_factory=dict[tuple[str, tuple[tuple[str, str], ...]], Advisor], init=False
    )
    _latest: dict[tuple[str, str], LessonAdvice | None] = field(
        default_factory=dict[tuple[str, str], LessonAdvice | None], init=False
    )
    _task: asyncio.Task[LessonAdvice] | None = field(default=None, init=False)
    _pending: str | None = field(default=None, init=False)

    # -- the active advisor ---------------------------------------------------

    def _active_spec(self) -> AdvisorSpec:
        return self.registry.get(self.config_repo.load().active)

    def active_name(self) -> str:
        return self._active_spec().name

    def label(self, source: str = "") -> str:
        """The display name of the advisor `source` (the active one when empty).
        A name that is no longer registered is shown as it is."""
        if not source:
            return self._active_spec().label
        return self.registry.get(source).label if self.registry.has(source) else source

    def enabled(self) -> bool:
        return self.active_name() != NULL_ADVISOR_NAME

    def capabilities(self) -> AdvisorCapabilities:
        return self._active_spec().capabilities

    def _advisor(self, spec: AdvisorSpec) -> Advisor:
        section: Mapping[str, str] = self.config_repo.load().section(spec.name)
        key = (spec.name, tuple(sorted(section.items())))
        advisor = self._advisors.get(key)
        if advisor is None:
            advisor = spec.create(section)
            self._advisors = {k: v for k, v in self._advisors.items() if k[0] != spec.name}
            self._advisors[key] = advisor
        return advisor

    # -- reading advice -------------------------------------------------------

    def current(self, layout: str) -> LessonAdvice:
        """The advice to steer the next `layout` lesson with: the last good
        advice of the active advisor, or empty advice (for `BuildLesson`)."""
        name = self.active_name()
        if name == NULL_ADVISOR_NAME:
            return EMPTY_ADVICE
        return self._last_good(layout, name) or EMPTY_ADVICE

    def _last_good(self, layout: str, name: str) -> LessonAdvice | None:
        key = (layout, name)
        if key not in self._latest:
            try:
                self._latest[key] = self.store.get(layout, name)
            except OSError:
                self._latest[key] = None
        return self._latest[key]

    def forget(self) -> None:
        """Drop every kept advice (advice was turned off)."""
        self._latest.clear()
        try:
            self.store.clear()
        except OSError as exc:
            logger.warning("could not clear stored advice: %s", exc)

    # -- requesting advice ----------------------------------------------------

    async def request(self, layout: str) -> LessonAdvice:
        """Ask the active advisor about `layout`. Never raises. Callers may
        stop waiting (`asyncio.wait` with a timeout); the request goes on."""
        self._pending = layout
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._drain())
        return await asyncio.shield(self._task)

    async def _drain(self) -> LessonAdvice:
        result = EMPTY_ADVICE
        while self._pending is not None:
            layout, self._pending = self._pending, None
            result = await self._run(layout)
        return result

    async def _run(self, layout: str) -> LessonAdvice:
        spec = self._active_spec()
        if spec.name == NULL_ADVISOR_NAME:
            return EMPTY_ADVICE
        now = self.wall_epoch()
        try:
            advisor = self._advisor(spec)
        except ValueError as exc:
            return LessonAdvice(source=spec.name, error=str(exc), created_at=now)
        except Exception as exc:
            logger.warning("advisor %s could not be created: %s", spec.name, exc)
            return self._failed(spec, exc, now)
        try:
            window = max(1, self.settings_repo.load().confidence_session_window)
            sessions = await asyncio.to_thread(self.history, layout, window)
            streams: Mapping[str, list[Keystroke]] = {}
            if spec.capabilities.needs_keystrokes:
                streams = await asyncio.to_thread(
                    self._load_streams, [s.session_id for s in sessions]
                )
            decay = self.config_repo.load().recency_decay
            ctx = build_advisor_context(
                layout, sessions, streams, self._layout_keys(layout), recency_decay=decay
            )
            if ctx.digest.is_empty:
                return LessonAdvice(source=spec.name, summary=NOT_ENOUGH_DATA, created_at=now)
            advice = await advisor(ctx)
            advice = validate_advice(advice, ctx.course)
        except Exception as exc:
            logger.warning("advisor %s failed: %s", spec.name, exc)
            return self._failed(spec, exc, now)
        advice = replace(advice, source=spec.name, created_at=now, error="")
        self._latest[(layout, spec.name)] = advice
        try:
            await asyncio.to_thread(self.store.put, layout, advice)
        except OSError as exc:
            logger.warning("could not store advice: %s", exc)
        return advice

    @staticmethod
    def _failed(spec: AdvisorSpec, exc: Exception, now: float) -> LessonAdvice:
        return LessonAdvice(
            source=spec.name,
            error=f"{spec.label} unavailable ({type(exc).__name__})",
            created_at=now,
        )

    def _layout_keys(self, layout: str) -> Mapping[int, KeyPos]:
        try:
            return self.layout_repo.get(layout).keys
        except (KeyError, OSError, ValueError):
            return {}

    def _load_streams(self, session_ids: list[str]) -> dict[str, list[Keystroke]]:
        try:
            return self.archive.load(session_ids)
        except OSError:
            return {}
