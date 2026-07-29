from dataclasses import dataclass, field

from .enums import Finger, Hand, Mode, TargetSpeedUnit


@dataclass(frozen=True, slots=True)
class Keystroke:
    codepoint: int      # target char (0 if user typed past end)
    typed: int          # actual char typed
    t_ns: int           # monotonic ns since session start
    correct: bool


def _empty_key_confidence() -> dict[int, float]:
    return {}


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
    words_completed: int = 0
    lang: str = "en"
    unlocked_keys: tuple[int, ...] = ()
    key_confidence: dict[int, float] = field(default_factory=_empty_key_confidence)
    target_speed_cpm: int = 0  # goal active at finish; 0 = legacy sessions


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


def _empty_transitions() -> dict[str, TransitionStats]:
    return {}


@dataclass(frozen=True, slots=True)
class LayoutAggregates:
    keys: dict[int, KeyStats]
    transitions: dict[str, TransitionStats] = field(default_factory=_empty_transitions)


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
    target_speed_cpm: int = 300         # ~46 wpm at typical generated word length
    target_speed_unit: TargetSpeedUnit = TargetSpeedUnit.WPM
    alphabet_size: int = 16             # letters force-unlocked from cold start
    lang: str = "en"
    learn_daily_minutes: int = 10        # adaptive mode daily goal (minutes); 0 = no goal
    wordlist_url: str = ""               # non-empty + cached file → real words; else Markov
    updated_at: str | None = None          # ISO-8601 UTC; sync LWW


@dataclass(frozen=True, slots=True)
class SyncStatusReport:
    configured: bool
    remote_url: str | None
    git_status: str
    local_sessions: int
    clone_sessions: int
    only_local: int
    only_clone: int
