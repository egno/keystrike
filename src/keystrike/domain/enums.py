from enum import IntEnum, StrEnum


class Mode(StrEnum):
    ADAPTIVE = "adaptive"
    CODE = "code"
    FREE = "free"


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
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


class PracticeSource(StrEnum):
    """Where a practice session's target text comes from — chosen on Home."""

    SAMPLE = "sample"
    FREE = "free"
    ADAPTIVE = "adaptive"
    CODE = "code"
