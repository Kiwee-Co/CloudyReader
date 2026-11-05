"""Voice gender and accent: Kokoro ids encode them, Piper voices and engine presets use tables."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from cloudyreader.models import VoiceInfo

log = logging.getLogger(__name__)

Gender = Literal["female", "male"]


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
