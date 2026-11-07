"""Voice listing order: engines in the owner's order, best grade first inside each engine."""

from __future__ import annotations

import dataclasses
import random
import typing
from pathlib import Path

import pytest

from cloudyreader.engines import kokoro
from cloudyreader.engines.kokoro import VOICE_GRADES, KokoroEngine
from cloudyreader.models import VoiceInfo
from cloudyreader.rotation import RotationMode, VoiceRotator
from cloudyreader.tts import TtsService
from cloudyreader.voice_meta import ENGINE_ORDER, engine_rank, grade_score, voice_sort_key


def row(
    key: str, quality: str = "", *, name: str = "", installed: bool = True, language: str = "en-US"
) -> VoiceInfo:
    engine, _, vid = key.partition(":")
    reason = "" if installed else "not downloaded yet"
    return VoiceInfo(key, engine, name or vid, language, quality, 1, installed, None, reason)


HEART = row("kokoro:af_heart", "A", name="Heart (female)")
BELLA = row("kokoro:af_bella", "A-", name="Bella (female)")
ADAM = row("kokoro:am_adam", "F+", name="Adam (male)")
BUILTIN = row(
    "chatterbox_turbo:builtin", "4-bit", name="Chatterbox Turbo (built-in)", language="en"
)
RYAN = row("qwen3_tts:ryan", "8-bit", name="Ryan (male)", language="en")
AIDEN = row("qwen3_tts:aiden", "8-bit", name="Aiden (male)")
LESSAC = row("piper:en_US-lessac-medium", "medium", name="lessac")
PIPER_RYAN = row("piper:en_US-ryan-medium", "medium", name="ryan")
PIPER_HIGH = row("piper:en_US-libritts-high", "high", name="libritts")
PIPER_LOW = row("piper:en_US-kathleen-low", "low", name="kathleen")


def keys(voices) -> list[str]:
    return [voice.key for voice in voices]


def ordered(voices) -> list[str]:
    return keys(sorted(voices, key=voice_sort_key))


def dimmed(voice: VoiceInfo) -> VoiceInfo:
    return dataclasses.replace(voice, installed=False, reason="not downloaded yet")


class Listing:
    """A TtsEngine that lists fixed rows, or only placeholders while it is unavailable."""

    def __init__(self, key: str, rows=(), *, placeholders=None) -> None:
        self.key = key
        self.rows = list(rows)
        self.placeholders = placeholders

    def available(self) -> bool:
        return self.placeholders is None

    def voices(self) -> list[VoiceInfo]:
        return list(self.rows)

    def placeholder_voices(self) -> list[VoiceInfo]:
        return list(self.placeholders or ())

    def synthesize(self, script, voice, opts, out_wav):
        raise AssertionError("listing order never synthesizes")


@pytest.fixture
def kokoro_rows(tmp_path, monkeypatch) -> list[VoiceInfo]:
    """The real rows KokoroEngine lists: every graded voice with its published grade."""
    monkeypatch.setattr(kokoro, "_supported_platform", lambda: True)
    return KokoroEngine(tmp_path, all_voices=True).voices()


# --- the macOS tier and the precision field -------------------------------------------------------

MAC_PREMIUM = row("macos:daniel", "Premium", name="Daniel", language="en-GB")
MAC_ENHANCED = row("macos:samantha", "Enhanced", name="Samantha")
MAC_STANDARD = row("macos:alex", "Standard", name="Alex")


def test_macos_tiers_rank_premium_then_enhanced_then_standard():
    scores = [grade_score(v) for v in (MAC_PREMIUM, MAC_ENHANCED, MAC_STANDARD)]

    assert scores == sorted(scores, reverse=True) and len(set(scores)) == 3
    assert ordered([MAC_STANDARD, MAC_PREMIUM, MAC_ENHANCED]) == keys(
        [MAC_PREMIUM, MAC_ENHANCED, MAC_STANDARD]
    )


def test_macos_voices_list_after_every_other_engine():
    voices = [MAC_PREMIUM, LESSAC, HEART, MAC_STANDARD, RYAN]

    assert ordered(voices) == keys([HEART, RYAN, LESSAC, MAC_PREMIUM, MAC_STANDARD])


@pytest.mark.parametrize("voice", [HEART, LESSAC, PIPER_HIGH, MAC_ENHANCED, RYAN])
def test_the_rank_reads_the_tier_never_the_precision(voice):
    labelled = dataclasses.replace(voice, precision="bf16 or whatever the label says")

    assert grade_score(labelled) == grade_score(voice)
    assert voice_sort_key(labelled) == voice_sort_key(voice)


# --- the engine order ----------------------------------------------------------------------------


def test_engine_order_is_the_owners_and_names_every_engine():
    assert ENGINE_ORDER == ("kokoro", "chatterbox_turbo", "qwen3_tts", "piper")
    # Drift guard: an engine added to VoiceInfo.engine needs a place in the order.
    engines = typing.get_args(typing.get_type_hints(VoiceInfo)["engine"])
    assert sorted(ENGINE_ORDER) == sorted(engines)
    assert [engine_rank(engine) for engine in ENGINE_ORDER] == [0, 1, 2, 3]
    assert engine_rank("espeak") == engine_rank("") == len(ENGINE_ORDER)


def test_engines_list_in_the_owners_order_whatever_the_input_order():
    voices = [PIPER_HIGH, AIDEN, HEART, BUILTIN, RYAN, PIPER_LOW, BELLA]
    expected = [HEART, BELLA, BUILTIN, AIDEN, RYAN, PIPER_HIGH, PIPER_LOW]
    rng = random.Random(7)

    for _ in range(5):
        rng.shuffle(voices)
        assert ordered(voices) == keys(expected)


# --- grades inside an engine ---------------------------------------------------------------------


def test_every_graded_kokoro_voice_ranks_with_a_first_and_f_plus_last(kokoro_rows):
    assert len(kokoro_rows) == len(VOICE_GRADES)
    assert all(grade_score(voice) is not None for voice in kokoro_rows)

    listed = sorted(kokoro_rows, key=voice_sort_key)

    assert (listed[0].key, listed[0].quality) == ("kokoro:af_heart", "A")
    assert (listed[-1].key, listed[-1].quality) == ("kokoro:am_adam", "F+")
    scores = [grade_score(voice) for voice in listed]
    assert scores == sorted(scores, reverse=True)


def test_voices_of_one_grade_sort_by_display_name(kokoro_rows):
    listed = sorted(kokoro_rows, key=voice_sort_key)

    def names(grade: str) -> list[str]:
        return [voice.name.partition(" ")[0] for voice in listed if voice.quality == grade]

    assert names("C+") == ["Aoede", "Fenrir", "Kore", "Michael", "Puck", "Sarah"]
    assert names("D") == [
        "Alice",
        "Daniel",
        "Echo",
        "Eric",
        "Jessica",
        "Liam",
        "Lily",
        "Onyx",
        "River",
    ]


def test_the_grade_ladder_parses_from_a_down_to_f_minus():
    ladder = ["A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F+", "F", "F-"]

    scores = [grade_score(row("kokoro:af_x", grade)) for grade in ladder]

    assert None not in scores
    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) == len(scores)
    assert grade_score(row("kokoro:af_x", " b+ ")) == grade_score(row("kokoro:af_x", "B+"))


def test_piper_tiers_rank_high_medium_low_x_low():
    voices = [
        row(f"piper:en_US-v{i}-{q}", q) for i, q in enumerate(["low", "x_low", "high", "medium"])
    ]

    assert [voice.quality for voice in sorted(voices, key=voice_sort_key)] == [
        "high",
        "medium",
        "low",
        "x_low",
    ]


def test_other_engines_are_ungraded_and_sort_by_display_name():
    assert [grade_score(voice) for voice in (BUILTIN, RYAN, AIDEN)] == [None, None, None]
    assert grade_score(row("espeak:en", "A")) is None  # a grade letter counts on Kokoro only
    assert ordered([RYAN, AIDEN]) == [AIDEN.key, RYAN.key]
    # Casefolded: plain string order would put "Beta" before "alpha".
    beta, alpha = row("qwen3_tts:b", name="Beta (male)"), row("qwen3_tts:a", name="alpha (female)")
    assert ordered([beta, alpha]) == [alpha.key, beta.key]


@pytest.mark.parametrize(
    ("odd", "graded"),
    [
        (row("kokoro:af_odd", "excellent", name="Aaa (female)"), [HEART, ADAM]),
        (row("kokoro:af_odd", "E", name="Aaa (female)"), [HEART, ADAM]),
        (row("kokoro:af_odd", "A++", name="Aaa (female)"), [HEART, ADAM]),
        (row("kokoro:af_odd", "", name="Aaa (female)"), [HEART, ADAM]),
        (row("piper:en_US-odd-ultra", "ultra", name="aaa"), [PIPER_HIGH, PIPER_LOW]),
    ],
    ids=["word", "E", "A++", "empty", "piper"],
)
def test_an_unknown_grade_string_ranks_last_in_its_engine(odd, graded):
    assert grade_score(odd) is None
    assert ordered([odd, *reversed(graded)]) == [*keys(graded), odd.key]


@pytest.mark.parametrize(
    "odd", [None, object(), dataclasses.replace(LESSAC, quality=None)], ids=["none", "obj", "q"]
)
def test_odd_input_has_no_grade_instead_of_raising(odd):
    assert grade_score(odd) is None


def test_equal_keys_keep_their_listed_order():
    first = row("piper:en_US-x-medium", "medium", name="x")
    twin = dataclasses.replace(first, path=Path("/elsewhere"))  # same sort key, another row

    assert sorted([first, twin], key=voice_sort_key) == [first, twin]
    assert sorted([twin, first], key=voice_sort_key) == [twin, first]


# --- TtsService.voices() -------------------------------------------------------------------------


def test_tts_lists_engines_in_the_owners_order_best_first_with_placeholders_inside(tmp_path):
    service = TtsService(
        [
            Listing("piper", [PIPER_LOW, LESSAC, PIPER_HIGH]),
            Listing("kokoro", [ADAM, HEART, BELLA]),
            Listing("chatterbox_turbo", placeholders=[dimmed(BUILTIN)]),
            Listing("qwen3_tts", [RYAN, AIDEN]),
        ],
        tmp_path,
    )

    listed = service.voices()

    assert keys(listed) == keys(
        [HEART, BELLA, ADAM, BUILTIN, AIDEN, RYAN, PIPER_HIGH, LESSAC, PIPER_LOW]
    )
    assert [voice.installed for voice in listed].count(False) == 1  # the dimmed Chatterbox row
    assert next(voice for voice in listed if voice.installed) == HEART  # a new user's default


def test_without_kokoro_the_best_installed_piper_voice_leads(tmp_path):
    service = TtsService(
        [
            Listing("piper", [LESSAC, PIPER_HIGH]),
            Listing("qwen3_tts", placeholders=[dimmed(RYAN), dimmed(AIDEN)]),
        ],
        tmp_path,
    )

    listed = service.voices()

    assert keys(listed) == [AIDEN.key, RYAN.key, PIPER_HIGH.key, LESSAC.key]
    assert next(voice for voice in listed if voice.installed) == PIPER_HIGH


def test_tts_keeps_unknown_engines_last_in_registration_order(tmp_path):
    zeta_b, zeta_a = row("zeta:b", name="b"), row("zeta:a", name="a")
    espeak = row("espeak:a", name="a")
    service = TtsService(
        [
            Listing("zeta", [zeta_b, zeta_a]),
            Listing("piper", [LESSAC]),
            Listing("espeak", [espeak]),
            Listing("kokoro", [HEART]),
        ],
        tmp_path,
    )

    assert keys(service.voices()) == [HEART.key, LESSAC.key, zeta_a.key, zeta_b.key, espeak.key]


def test_tts_keeps_rows_with_equal_keys_in_the_engines_order(tmp_path):
    first = row("piper:en_US-x-medium", "medium", name="x")
    twin = dataclasses.replace(first, path=Path("/elsewhere"))

    assert TtsService([Listing("piper", [twin, first])], tmp_path).voices() == [twin, first]


def test_round_robin_follows_the_listing_order(tmp_path):
    service = TtsService(
        [
            Listing("piper", [PIPER_RYAN, LESSAC]),
            Listing("kokoro", [BELLA, HEART]),
            Listing("chatterbox_turbo", [BUILTIN]),
            Listing("qwen3_tts", [RYAN, AIDEN]),
        ],
        tmp_path,
    )
    voices = service.voices()
    rotator = VoiceRotator(RotationMode.ROUND_ROBIN)

    picks = [rotator.next_voice(voices).key for _ in range(6)]

    # Chatterbox never rotates; everyone else in listing order, the best voice first.
    assert picks == keys([HEART, BELLA, AIDEN, RYAN, LESSAC, PIPER_RYAN])
