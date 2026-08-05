from enum import Enum, IntEnum, StrEnum, auto


class Mode(StrEnum):
    ADAPTIVE = "adaptive"


# Modes retired when code-practice/freeform/sample-text modes were dropped in
# favor of adaptive-only drills. Old persisted sessions still carry these
# strings, so they need to keep resolving to something valid.
_LEGACY_MODES = frozenset({"free", "code", "sample"})


def migrate_legacy_mode(raw: str) -> Mode:
    """Map a persisted mode string to the current `Mode` enum, translating
    retired legacy modes (from pre-adaptive-only builds) to `Mode.ADAPTIVE`.

    This is a data-migration policy decision, not a persistence-format
    concern, so it lives in the domain layer rather than in a repository
    adapter.
    """
    if raw in _LEGACY_MODES:
        return Mode.ADAPTIVE
    return Mode(raw)


class Finger(IntEnum):
    PINKY = 1
    RING = 2
    MIDDLE = 3
    INDEX = 4
    THUMB = 5


class Hand(StrEnum):
    L = "L"
    R = "R"


class SessionState(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


class TargetSpeedUnit(StrEnum):
    WPM = "wpm"
    CPM = "cpm"


class FocusKind(Enum):
    """Why the adaptive engine picked today's lesson focus. Replaces the old
    ad-hoc strings ("weak", "review", f"{pair} weak transition", ...) that
    presentation code had to parse via substring/suffix matching."""

    KEY_WEAK = auto()
    KEY_CALIBRATING = auto()
    KEY_REVIEW = auto()
    TRANSITION_WEAK = auto()
    TRANSITION_CALIBRATING = auto()
    TRANSITION_REVIEW = auto()
