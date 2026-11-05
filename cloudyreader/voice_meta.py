"""Voice gender, accent and listing order: Kokoro ids and grades, Piper tables and tiers."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from cloudyreader.models import VoiceInfo

log = logging.getLogger(__name__)

Gender = Literal["female", "male"]

# The owner's quality order of the engine headings. An engine missing here lists after these.
ENGINE_ORDER = ("kokoro", "chatterbox_turbo", "qwen3_tts", "piper")

# Kokoro quality is the published grade (A down to F-): letter x 3, plus 1 for "+", minus 1 for "-".
_GRADE = re.compile(r"([A-DF])([+-]?)")
_LETTER_SCORE: Mapping[str, int] = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
_SIGN_SCORE: Mapping[str, int] = {"+": 1, "": 0, "-": -1}
_PIPER_TIERS: Mapping[str, int] = {"high": 3, "medium": 2, "low": 1, "x_low": 0}


@dataclass(frozen=True)
class VoiceProfile:
    gender: Gender
    accent: str  # VoiceInfo.language: "en-US" | "en-GB" | "en" (no region: never "US only")


# UNVERIFIED: the upstream guess for the 5 voices in assets.lock.json; nobody has checked them by
# ear yet. Keys are voice ids without "piper:". A Piper voice missing here never rotates.
PIPER_GENDERS: Mapping[str, Gender] = MappingProxyType(
    {
        "en_US-lessac-medium": "female",
        "en_US-amy-medium": "female",
        "en_US-ryan-medium": "male",
        "en_GB-alan-medium": "male",
        "en_GB-jenny_dioco-medium": "female",
    }
)

# UNVERIFIED by ear: the upstream names of the presets, keyed by engine id, then voice id without
# "<engine>:". Chatterbox Turbo stays empty (never rotates) until the owner confirms its voice.
ENGINE_GENDERS: Mapping[str, Mapping[str, Gender]] = MappingProxyType(
    {
        "qwen3_tts": MappingProxyType({"ryan": "male", "aiden": "male"}),
        "chatterbox_turbo": MappingProxyType({}),
    }
)

# The id shape KokoroEngine accepts. First letter a/b = US/UK English, second f/m = gender.
_KOKORO_ID = re.compile(r"[ab][fm]_[a-z]+")
_KOKORO_GENDER: Mapping[str, Gender] = {"f": "female", "m": "male"}


def profile_of(voice: VoiceInfo) -> VoiceProfile | None:
    """Gender and accent of an English voice; None when either is unknown. Never raises."""
    key = getattr(voice, "key", None)
    accent = getattr(voice, "language", None)
    if not isinstance(key, str) or not isinstance(accent, str):
        return None
    if accent.partition("-")[0] != "en":
        return None
    engine, _, vid = key.partition(":")
    gender: Gender | None = None
    if engine == "kokoro" and _KOKORO_ID.fullmatch(vid):
        gender = _KOKORO_GENDER[vid[1]]
    elif engine == "piper":
        gender = PIPER_GENDERS.get(vid)
    elif engine in ENGINE_GENDERS:
        gender = ENGINE_GENDERS[engine].get(vid)
    if gender is None:
        log.debug("no known gender for voice %s: it never rotates", key)
        return None
    return VoiceProfile(gender, accent)


def engine_rank(engine: str) -> int:
    """Position of `engine` in ENGINE_ORDER; an unknown engine ranks after every known one."""
    return ENGINE_ORDER.index(engine) if engine in ENGINE_ORDER else len(ENGINE_ORDER)


def grade_score(voice: VoiceInfo) -> int | None:
    """Quality inside the voice's engine, higher is better. None: ungraded or an unknown string."""
    quality = getattr(voice, "quality", None)
    if not isinstance(quality, str):
        return None
    engine = getattr(voice, "engine", None)
    if engine == "kokoro":
        grade = _GRADE.fullmatch(quality.strip().upper())
        return 3 * _LETTER_SCORE[grade[1]] + _SIGN_SCORE[grade[2]] if grade else None
    if engine == "piper":
        return _PIPER_TIERS.get(quality.strip().lower())
    return None


def voice_sort_key(voice: VoiceInfo) -> tuple[int, float, str, str]:
    """Listing order: engine (ENGINE_ORDER), best grade first, ungraded last, then name, key."""
    score = grade_score(voice)
    return (
        engine_rank(voice.engine),
        math.inf if score is None else -score,
        voice.name.casefold(),
        voice.key,
    )
