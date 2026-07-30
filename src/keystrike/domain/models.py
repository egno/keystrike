from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import NamedTuple

from .enums import Finger, Hand, Mode, TargetSpeedUnit


@dataclass(frozen=True, slots=True)
class Keystroke:
    codepoint: int  # target char (0 if user typed past end)
    typed: int  # actual char typed
    t_ns: int  # monotonic ns since session start
    correct: bool


def _empty_key_confidence() -> dict[int, float]:
    return {}


@dataclass(frozen=True, slots=True)
class SessionResult:
    schema_version: int
    session_id: str
    started_at: float  # unix epoch
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
    # Left as a plain (mutable-in-place) dict rather than MappingProxyType-wrapped
    # like Layout.keys/LayoutAggregates: infrastructure.session_repo_jsonl's
    # `asdict(header)` deep-copies every field, and copy.deepcopy cannot pickle
    # a mappingproxy. Freezing this one would break header persistence.
    key_confidence: dict[int, float] = field(default_factory=_empty_key_confidence)
    target_speed_cpm: int = 0  # goal active at finish; 0 = legacy sessions


@dataclass(frozen=True, slots=True)
class KeyStats:
    codepoint: int
    samples: int
    mean_time_ns: float
    error_count: int
    last_seen: float
    attempt_count: int = 0


class Bigram(NamedTuple):
    """A directed pair of codepoints: the key pressed before, then the key
    pressed after. The value-type key for `TransitionStats` maps, replacing
    the old ad-hoc `chr(prev) + chr(next)` string keys."""

    prev_cp: int
    next_cp: int

    def chars(self) -> str:
        """Display form, e.g. `Bigram(ord("a"), ord("b")).chars() == "ab"`."""
        return chr(self.prev_cp) + chr(self.next_cp)


@dataclass(frozen=True, slots=True)
class TransitionStats:
    prev_cp: int
    next_cp: int
    samples: int
    mean_time_ns: float
    error_count: int
    last_seen: float
    attempt_count: int = 0


def _empty_transitions() -> dict[Bigram, TransitionStats]:
    return {}


@dataclass(frozen=True, slots=True)
class LayoutAggregates:
    keys: Mapping[int, KeyStats]
    transitions: Mapping[Bigram, TransitionStats] = field(default_factory=_empty_transitions)

    def __post_init__(self) -> None:
        # Freezing the dataclass only blocks attribute rebinding — wrap the
        # dict fields too so in-place mutation of their contents also raises.
        object.__setattr__(self, "keys", MappingProxyType(dict(self.keys)))
        object.__setattr__(self, "transitions", MappingProxyType(dict(self.transitions)))


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
    keys: Mapping[int, KeyPos]
    learn_order: tuple[int, ...]
    ortholinear: bool = False  # no row stagger — affects only how Stats renders the heatmap

    def __post_init__(self) -> None:
        object.__setattr__(self, "keys", MappingProxyType(dict(self.keys)))


@dataclass(frozen=True, slots=True)
class Settings:
    schema_version: int = 1
    layout: str = "qwerty"
    target_speed_cpm: int = 300  # ~46 wpm at typical generated word length
    target_speed_unit: TargetSpeedUnit = TargetSpeedUnit.WPM
    alphabet_size: int = 16  # letters force-unlocked from cold start
    confidence_session_window: int = 10  # sessions in rolling stats for confidence
    min_confidence_attempts: int = 10  # presses before key confidence reaches full weight
    min_transition_confidence_attempts: int = 4  # lower floor — bigrams are sparser
    focus_char_boost: float = 3.0  # char weight multiplier for focus key
    focus_word_boost: float = 3.0  # wordlist/Markov boost when focus char present
    focus_bigram_word_boost: float = 4.0  # word boost when focus bigram present
    focus_transition_boost: float = 4.0  # transition weight multiplier for focus pair
    focus_weak_extra_boost: float = 1.5  # extra multiplier when focus confidence < 1.0
    lang: str = "en"
    learn_daily_minutes: int = 10  # adaptive mode daily goal (minutes); 0 = no goal
    wordlist_url: str = ""  # non-empty + cached file → real words; else Markov
    updated_at: str | None = None  # ISO-8601 UTC; sync LWW


@dataclass(frozen=True, slots=True)
class SyncStatusReport:
    configured: bool
    remote_url: str | None
    git_status: str
    local_sessions: int
    clone_sessions: int
    only_local: int
    only_clone: int
