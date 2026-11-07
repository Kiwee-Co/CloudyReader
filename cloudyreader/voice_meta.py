"""Voice gender, accent, listing order and menu text: Kokoro ids, Piper tables and tiers."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
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
_MACOS_TIERS: Mapping[str, int] = {"premium": 2, "enhanced": 1, "standard": 0}


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
    if engine == "macos":
        return _MACOS_TIERS.get(quality.strip().lower())
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


# --- Menu text: one label per voice, so every surface says the same thing ----------------------

LABEL_SEPARATOR = " · "  # between the fields of a label; the comma stays inside the brackets
NOT_DOWNLOADED = "not downloaded yet"
ROW_REASON_MAX = 34  # a dimmed row keeps this much of its reason; its tooltip keeps all of it
ENGINE_TITLES: Mapping[str, str] = MappingProxyType(
    {
        "kokoro": "Kokoro",
        "chatterbox_turbo": "Chatterbox Turbo",
        "qwen3_tts": "Qwen3-TTS",
        "piper": "Piper",
        "macos": "macOS",
    }
)
# Region -> (short form in the label, spoken form). A region missing here shows as its own code,
# so a new macOS voice never needs an edit.
_ACCENTS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "US": ("US", "American"),
        "GB": ("UK", "British"),
        "AU": ("AU", "Australian"),
        "CA": ("CA", "Canadian"),
        "IE": ("IE", "Irish"),
        "IN": ("IN", "Indian"),
        "NZ": ("NZ", "New Zealand"),
        "ZA": ("ZA", "South African"),
        "SCOTLAND": ("Scotland", "Scottish"),
    }
)
_GENDER_SUFFIX = re.compile(r"\s*\((?:fe)?male\)$", re.IGNORECASE)


def engine_title(engine: str) -> str:
    return ENGINE_TITLES.get(engine, engine.replace("_", " ").title())


def accent_of(language: str) -> tuple[str, str] | None:
    """(short, spoken) accent of "en-US" or "en_GB"; None for a bare "en": never a guess."""
    region = language.replace("_", "-").partition("-")[2].upper()
    return _ACCENTS.get(region, (region, region)) if region else None


def _name_of(voice: VoiceInfo) -> tuple[str, bool]:
    """The voice's own name, and whether it only echoes its engine ("Chatterbox Turbo (built-in)").

    The gender suffix goes (the label says it once); a lower-case Piper id is title-cased.
    """
    name = _GENDER_SUFFIX.sub("", voice.name).replace("_", " ").strip()
    title = engine_title(voice.engine)
    rest = name[len(title) :]
    if name.casefold().startswith(title.casefold()) and (not rest or rest[0] in " ("):
        return rest.strip(" ()").capitalize() or title, True
    if name.islower():
        name = " ".join(word.capitalize() for word in name.split())
    return name, False


def display_name(voice: VoiceInfo) -> str:
    return _name_of(voice)[0]


def precision_of(voice: VoiceInfo) -> str:
    """The model's own format. Without one, the tier; a Kokoro grade is never a precision."""
    if voice.precision:
        return voice.precision
    return "" if _GRADE.fullmatch(voice.quality.strip().upper()) else voice.quality


def row_reason(voice: VoiceInfo) -> str:
    """What a dimmed row says: the reason up to its first colon when it is long, then cut."""
    reason = voice.reason or NOT_DOWNLOADED
    short = reason if len(reason) <= ROW_REASON_MAX else reason.partition(": ")[0]
    return short if len(short) <= ROW_REASON_MAX else short[: ROW_REASON_MAX - 1].rstrip() + "…"


def voice_label(voice: VoiceInfo) -> str:
    """`Heart (US, female) · Kokoro · bf16`, and ` — <reason>` after it when not installed.

    Accent and gender show only where known. The text is the row of the pop-up list and the
    closed pop-up button alike. It never holds a grade letter.
    """
    profile = profile_of(voice)
    accent = accent_of(voice.language)
    known = (accent[0] if accent else "", profile.gender if profile else "")
    detail = ", ".join(part for part in known if part)
    name = display_name(voice)
    fields = (
        f"{name} ({detail})" if detail else name,
        engine_title(voice.engine),
        precision_of(voice),
    )
    label = LABEL_SEPARATOR.join(field for field in fields if field)
    return label if voice.installed else f"{label} — {row_reason(voice)}"


def spoken_label(voice: VoiceInfo) -> str:
    """The same facts for VoiceOver and a tooltip: no dot, accents as words."""
    profile = profile_of(voice)
    accent = accent_of(voice.language)
    english = voice.language.replace("_", "-").partition("-")[0].lower() == "en"
    accent_said = "" if accent is None else f"{accent[1]} English" if english else accent[1]
    said = ", ".join(fact for fact in (accent_said, profile.gender if profile else "") if fact)
    tail = ", ".join(fact for fact in (engine_title(voice.engine), precision_of(voice)) if fact)
    name = display_name(voice)
    text = f"{name}, {said}. {tail}." if said else f"{name}. {tail}."
    return text if voice.installed else f"{text} Not available: {voice.reason or NOT_DOWNLOADED}."


def voice_phrase(voice: VoiceInfo) -> str:
    """A voice inside a sentence: `Heart (female, Kokoro)`. Gender is what rotation picks by and
    the engine tells two Ryans apart; an engine's only voice is just the engine."""
    name, echoes_engine = _name_of(voice)
    title = engine_title(voice.engine)
    if echoes_engine:
        return title
    profile = profile_of(voice)
    return (
        f"{name} ({', '.join(part for part in (profile.gender if profile else '', title) if part)})"
    )


def unique_labels(voices: Sequence[VoiceInfo]) -> dict[str, str]:
    """key -> label, and no two labels alike: a clash adds the voice's id after the label."""
    labels = {voice.key: voice_label(voice) for voice in voices}
    seen = Counter(labels.values())
    return {
        key: f"{label} [{key.partition(':')[2]}]" if seen[label] > 1 else label
        for key, label in labels.items()
    }
