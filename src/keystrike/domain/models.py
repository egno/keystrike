from dataclasses import dataclass, field

from .enums import Finger, Hand, Mode


@dataclass(frozen=True, slots=True)
class Keystroke:
    codepoint: int      # target char (0 if user typed past end)
    typed: int          # actual char typed
    t_ns: int           # monotonic ns since session start
    correct: bool


@dataclass(frozen=True, slots=True)
class SessionResult:
    schema_version: int
    session_id: str
    started_at: float               # unix epoch
    duration_ns: int
    layout: str
    mode: Mode
    lesson_alphabet: tuple[int, ...]
    focus_key: int | None
    total_keystrokes: int
    correct_keystrokes: int
    lang: str = "en"


@dataclass(frozen=True, slots=True)
class KeyStats:
    codepoint: int
    samples: int
    mean_time_ns: float
    error_count: int
    last_seen: float


@dataclass(frozen=True, slots=True)
class TransitionStats:
    prev_cp: int
    next_cp: int
    samples: int
    mean_time_ns: float
    error_count: int
    last_seen: float


@dataclass(frozen=True, slots=True)
class LayoutAggregates:
    keys: dict[int, KeyStats]
    transitions: dict[str, TransitionStats] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LessonKey:
    codepoint: int
    unlocked: bool
    confidence: float
    is_focus: bool


@dataclass(frozen=True, slots=True)
class LessonState:
    layout: str
    keys: tuple[LessonKey, ...]
    alphabet_size: int
    target_speed_cpm: int


@dataclass(frozen=True, slots=True)
class KeyPos:
    codepoint: int
    row: int
    col: int
    finger: Finger
    hand: Hand
    shifted: bool = False


@dataclass(frozen=True, slots=True)
class Layout:
    name: str
    keys: dict[int, KeyPos]
    learn_order: tuple[int, ...]
    ortholinear: bool = False  # no row stagger — affects only how Stats renders the heatmap


@dataclass(frozen=True, slots=True)
class Settings:
    schema_version: int = 1
    layout: str = "qwerty"
    target_speed_cpm: int = 300         # 60 wpm
    alphabet_size: int = 16             # letters force-unlocked from cold start
    lang: str = "en"
    code_language: str = "python"
    freeform_path: str | None = None
    learn_daily_minutes: int = 10        # adaptive mode cap per calendar day; 0 = unlimited
