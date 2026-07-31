from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import NamedTuple

from .enums import Finger, Hand, Mode, TargetSpeedUnit

# Tuning defaults shared with domain.confidence / domain.focus and mirrored as
# Settings fields below. Declared here — the lowest-level domain module, with
# no dependents to create a cycle — as the single source of truth so the two
# sets of numbers can't silently drift apart.
CONFIDENCE_SESSION_WINDOW = 10
MIN_CONFIDENCE_ATTEMPTS = 10
MIN_TRANSITION_CONFIDENCE_ATTEMPTS = 4
FOCUS_CHAR_BOOST = 3.0
FOCUS_WORD_BOOST = 3.0
FOCUS_BIGRAM_WORD_BOOST = 4.0
FOCUS_TRANSITION_BOOST = 4.0
FOCUS_WEAK_EXTRA_BOOST = 1.5
LESSON_WORD_COUNT = 12
FOCUS_WORD_MIN_FRACTION = 0.6
MAX_WORD_REPEATS = 2


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
    key_confidence: Mapping[int, float] = field(default_factory=_empty_key_confidence)
    target_speed_cpm: int = 0  # goal active at finish; 0 = legacy sessions

    def __post_init__(self) -> None:
        # Freezing the dataclass only blocks attribute rebinding — wrap the
        # dict field too so in-place mutation of its contents also raises.
        # infrastructure.session_repo_jsonl's header serialization builds its
        # own plain dict rather than routing this mappingproxy through
        # dataclasses.asdict/copy.deepcopy (which can't pickle a mappingproxy).
        object.__setattr__(self, "key_confidence", MappingProxyType(dict(self.key_confidence)))


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
    # False when loaded from a pre-transition cache file that omitted ``transitions``.
    transitions_computed: bool = True

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
    confidence_session_window: int = CONFIDENCE_SESSION_WINDOW  # sessions in rolling stats
    min_confidence_attempts: int = MIN_CONFIDENCE_ATTEMPTS  # presses before full weight
    min_transition_confidence_attempts: int = MIN_TRANSITION_CONFIDENCE_ATTEMPTS  # bigrams sparser
    focus_char_boost: float = FOCUS_CHAR_BOOST  # char weight multiplier for focus key
    focus_word_boost: float = FOCUS_WORD_BOOST  # wordlist/Markov boost when focus char present
    focus_bigram_word_boost: float = FOCUS_BIGRAM_WORD_BOOST  # word boost when focus bigram present
    focus_transition_boost: float = FOCUS_TRANSITION_BOOST  # transition weight multiplier
    focus_weak_extra_boost: float = FOCUS_WEAK_EXTRA_BOOST  # extra multiplier when confidence < 1.0
    lang: str = "en"
    learn_daily_minutes: int = 10  # adaptive mode daily goal (minutes); 0 = no goal
    lesson_word_count: int = LESSON_WORD_COUNT  # words per generated practice lesson
    focus_word_min_fraction: float = FOCUS_WORD_MIN_FRACTION  # weak-focus word quota fraction
    max_word_repeats: int = MAX_WORD_REPEATS  # per-word repeat cap in generated lessons
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
