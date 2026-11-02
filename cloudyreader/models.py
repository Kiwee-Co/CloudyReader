"""Shared contracts for cloudyreader.

Single writer: stream S0b. Everyone else imports, never edits.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal, Protocol


# The contract pins `(str, Enum)`: StrEnum (ruff UP042) would change str() and format() output.
class Kind(str, Enum):  # noqa: UP042
    TOSS_UP = "toss-up"
    BONUS = "bonus"


class Fmt(str, Enum):  # noqa: UP042
    MULTIPLE_CHOICE = "multiple-choice"
    SHORT_ANSWER = "short-answer"


@dataclass(frozen=True)
class Respelling:
    """Pasted guide such as `Pharynx [FAR-ingks]`: surface='Pharynx', respelling='FAR-ingks'.
    Phonetic: CAPS = stressed syllable, '-' = syllable break, ' ' = word break. See `kind`."""

    surface: str
    respelling: str
    # phonetic: syllable respelling, spoken via IPA (FAR-ingks, jool, Tee-o-door).
    # spoken: say-as words instead of the expression ("4 2/7 [4 and two-sevenths]", "[yields]").
    # spell: letters to spell out ("[F.A.D.]", "[H-E-2-S-1]").
    kind: Literal["phonetic", "spoken", "spell"] = "phonetic"


@dataclass(frozen=True)
class Choice:
    letter: Literal["W", "X", "Y", "Z"]
    text: str  # guides removed, whitespace-normalized
    respellings: tuple[Respelling, ...] = ()


@dataclass(frozen=True)
class Question:
    kind: Kind | None
    number: int | None
    category: str | None  # as pasted, e.g. "EARTH SCIENCE"
    fmt: Fmt | None
    stem: str  # lines joined, whitespace-normalized, guides removed
    choices: tuple[Choice, ...]
    answer: str | None  # text after "ANSWER:"; never spoken unless RenderOptions.read_answer
    raw: str
    respellings: tuple[Respelling, ...] = ()  # guides found in the stem


@dataclass(frozen=True)
class EntitySpan:
    start: int
    end: int
    text: str
    label: Literal["chemical", "formula", "protein", "gene", "other"]
    source: str  # "ner" | "regex"


@dataclass(frozen=True)
class Resolution:
    query: str
    kind: str  # "chemical" | "iupac" | "protein" | "gene"
    canonical: str | None
    ids: Mapping[str, str]
    source: str  # "opsin" | "pubchem" | "uniprot" | "cache" | "lexicon"
    status: Literal["ok", "not_found", "timeout", "offline", "error"]


@dataclass(frozen=True)
class Override:
    """Exact pronunciation of `surface` inside Segment.text. `ipa` is neutral General American IPA:
    primary stress mark before the stressed syllable, no length marks, stressed NURSE = ɜɹ. Engines
    convert to their own layout (Piper: to_piper_layout; Kokoro: the misaki mapper)."""

    surface: str
    ipa: str
    source: str  # "respelling" | "lexicon" | "iupac"


@dataclass(frozen=True)
class Segment:
    text: str
    pause_after_ms: int = 0
    overrides: tuple[Override, ...] = ()


@dataclass(frozen=True)
class SpokenScript:
    segments: tuple[Segment, ...]
    warnings: tuple[str, ...] = ()

    def text(self) -> str:
        return " ".join(s.text for s in self.segments)


@dataclass(frozen=True)
class VoiceInfo:
    key: str  # "piper:en_US-lessac-medium" | "kokoro:af_heart"
    engine: Literal["piper", "kokoro"]
    name: str
    language: str  # "en-US"
    quality: str  # "medium" | "high" | ...
    num_speakers: int
    installed: bool
    path: Path | None = None


@dataclass(frozen=True)
class RenderOptions:
    read_answer: bool = False
    speed: float = 1.0
    online_lookups: bool = True
    speaker_id: int | None = None


@dataclass(frozen=True)
class Audio:
    wav_path: Path
    sample_rate: int
    duration_s: float
    cache_hit: bool


@dataclass(frozen=True)
class Reading:
    questions: tuple[Question, ...]
    script: SpokenScript
    entities: tuple[EntitySpan, ...]
    resolutions: Mapping[str, Resolution]  # keyed by EntitySpan.text
    audio: Audio
    warnings: tuple[str, ...] = ()


class Parser(Protocol):
    def parse(self, raw: str) -> list[Question]: ...


class EntityDetector(Protocol):
    def detect(self, text: str) -> list[EntitySpan]: ...


class Resolver(Protocol):
    def resolve_many(
        self, spans: Sequence[EntitySpan], *, timeout_s: float
    ) -> dict[str, Resolution]: ...  # keyed by span.text


class Normalizer(Protocol):
    def to_script(
        self,
        questions: Sequence[Question],
        resolutions: Mapping[str, Resolution],
        opts: RenderOptions,
    ) -> SpokenScript: ...


class TtsEngine(Protocol):
    key: str  # "piper" | "kokoro"

    def available(self) -> bool: ...
    def voices(self) -> list[VoiceInfo]: ...
    def synthesize(
        self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions, out_wav: Path
    ) -> Audio: ...  # writes 16-bit mono WAV to out_wav


class AudioPlayer(Protocol):
    def play(self, audio: Audio) -> None: ...  # non-blocking
    def stop(self) -> None: ...
    def replay(self) -> bool: ...  # False when nothing has played yet
    @property
    def is_playing(self) -> bool: ...


class ReaderService(Protocol):
    def voices(self) -> list[VoiceInfo]: ...
    def prepare(self, raw: str, voice_key: str, opts: RenderOptions) -> Reading: ...  # blocking
