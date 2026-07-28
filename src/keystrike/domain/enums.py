from enum import IntEnum, StrEnum


class Mode(StrEnum):
    ADAPTIVE = "adaptive"


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
