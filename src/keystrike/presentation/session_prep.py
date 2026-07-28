from collections.abc import Callable
from dataclasses import dataclass

from keystrike.domain.enums import Mode
from keystrike.domain.models import Layout

PrepareNextSession = Callable[[], "SessionPrep | None"]


@dataclass(frozen=True, slots=True)
class SessionPrep:
    target_text: str
    layout: str
    mode: Mode
    focus_key: int | None
    layout_obj: Layout | None
    lesson_heatmap: dict[int, float] | None
