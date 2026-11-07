"""Contract tests for cloudyreader.models: immutability, enum values, defaults, protocol shapes."""

import dataclasses
import inspect
import typing
from pathlib import Path

import pytest

from cloudyreader import models
from cloudyreader.models import (
    Audio,
    Choice,
    EntitySpan,
    Fmt,
    Kind,
    Override,
    Question,
    Reading,
    RenderOptions,
    Resolution,
    Respelling,
    Segment,
    SpokenScript,
    VoiceInfo,
)

PHARYNX = Respelling("Pharynx", "FAR-ingks")
OVERRIDE = Override("Pharynx", "fˈæɹɪŋks", "respelling")
SEGMENT = Segment("Pharynx", 400, (OVERRIDE,))
SCRIPT = SpokenScript((SEGMENT,))
AUDIO = Audio(Path("out.wav"), 22050, 1.5, False)
VOICE = VoiceInfo("piper:en_US-lessac-medium", "piper", "lessac", "en-US", "medium", 1, True)

# One instance per dataclass in the module; test_instances_cover_every_dataclass keeps it complete.
INSTANCES = [
    PHARYNX,
    Choice("W", "Pharynx", (PHARYNX,)),
    Question(
        Kind.TOSS_UP, 1, "LIFE SCIENCE", Fmt.MULTIPLE_CHOICE, "Stem", (), "Y) ESOPHAGUS", "raw"
    ),
    EntitySpan(0, 4, "NaCl", "formula", "regex"),
    Resolution("water", "chemical", "oxidane", {"cid": "962"}, "pubchem", "ok"),
    OVERRIDE,
    SEGMENT,
    SCRIPT,
    VOICE,
    RenderOptions(),
    AUDIO,
    Reading((), SCRIPT, (), {}, AUDIO),
]


def test_voice_info_precision_comes_last_and_defaults_to_empty():
    names = [field.name for field in dataclasses.fields(VoiceInfo)]

    assert names[-2:] == ["reason", "precision"]  # old positional and keyword calls stay valid
    assert VOICE.precision == ""
    assert dataclasses.replace(VOICE, precision="medium").precision == "medium"


@pytest.mark.parametrize("instance", INSTANCES, ids=lambda i: type(i).__name__)
def test_dataclasses_reject_mutation(instance):
    first_field = dataclasses.fields(instance)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, first_field, None)


def test_instances_cover_every_dataclass():
    declared = {
        obj
        for _, obj in inspect.getmembers(models, inspect.isclass)
        if dataclasses.is_dataclass(obj) and obj.__module__ == models.__name__
    }
    assert declared == {type(instance) for instance in INSTANCES}


@pytest.mark.parametrize("cls", sorted({type(i) for i in INSTANCES}, key=lambda c: c.__name__))
def test_annotations_resolve_at_runtime(cls):
    # `from __future__ import annotations` hides a name that is only imported for type checking.
    typing.get_type_hints(cls)


def test_kind_values():
    assert {k.name: k.value for k in Kind} == {"TOSS_UP": "toss-up", "BONUS": "bonus"}


def test_fmt_values():
    assert {f.name: f.value for f in Fmt} == {
        "MULTIPLE_CHOICE": "multiple-choice",
        "SHORT_ANSWER": "short-answer",
    }


def test_enums_equal_their_plain_string_values():
    # The golden YAML files carry the plain strings.
    assert Kind("toss-up") is Kind.TOSS_UP
    assert Kind.BONUS == "bonus"
    assert Fmt("short-answer") is Fmt.SHORT_ANSWER
    assert Fmt.MULTIPLE_CHOICE == "multiple-choice"


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        ((), ""),
        (("Toss-up.",), "Toss-up."),
        (("Toss-up number two.", "Earth Science."), "Toss-up number two. Earth Science."),
        (("A", "B", "C"), "A B C"),
    ],
)
def test_spoken_script_text_joins_segments_with_single_spaces(texts, expected):
    script = SpokenScript(tuple(Segment(t, 700, (OVERRIDE,)) for t in texts))
    assert script.text() == expected


def test_optional_fields_default_to_empty():
    question = Question(None, None, None, None, "stem", (), None, "stem")
    assert question.respellings == ()
    assert Choice("W", "x").respellings == ()
    assert Segment("x").pause_after_ms == 0
    assert Segment("x").overrides == ()
    assert SpokenScript(()).warnings == ()
    assert VOICE.path is None
    assert Reading((), SCRIPT, (), {}, AUDIO).warnings == ()


def test_respelling_kind_defaults_to_phonetic():
    assert PHARYNX.kind == "phonetic"
    assert Respelling("Pharynx", "FAR-ingks") == Respelling("Pharynx", "FAR-ingks", "phonetic")


def test_respelling_kind_is_the_last_field():
    # Every two-argument Respelling(...) call in the codebase relies on the default.
    assert [f.name for f in dataclasses.fields(Respelling)] == ["surface", "respelling", "kind"]


def test_respelling_kind_declares_exactly_three_values():
    declared = typing.get_args(typing.get_type_hints(Respelling)["kind"])
    assert declared == ("phonetic", "spoken", "spell")
    for kind in declared:
        assert Respelling("4 2/7", "4 and two-sevenths", kind).kind == kind


def test_respelling_kind_cannot_be_reassigned():
    with pytest.raises(dataclasses.FrozenInstanceError):
        PHARYNX.kind = "spell"


def test_render_options_defaults():
    opts = RenderOptions()
    assert opts.read_answer is False  # R2: the ANSWER line stays silent unless asked
    assert opts.speed == 1.0
    assert opts.online_lookups is True
    assert opts.speaker_id is None


@pytest.mark.parametrize(
    ("protocol", "method", "params"),
    [
        (models.Parser, "parse", ["self", "raw"]),
        (models.EntityDetector, "detect", ["self", "text"]),
        (models.Resolver, "resolve_many", ["self", "spans", "timeout_s"]),
        (models.Normalizer, "to_script", ["self", "questions", "resolutions", "opts"]),
        (models.TtsEngine, "available", ["self"]),
        (models.TtsEngine, "voices", ["self"]),
        (models.TtsEngine, "synthesize", ["self", "script", "voice", "opts", "out_wav"]),
        (models.AudioPlayer, "play", ["self", "audio"]),
        (models.AudioPlayer, "stop", ["self"]),
        (models.AudioPlayer, "replay", ["self"]),
        (models.ReaderService, "voices", ["self"]),
        (models.ReaderService, "prepare", ["self", "raw", "voice_key", "opts"]),
    ],
)
def test_protocol_method_signatures(protocol, method, params):
    assert list(inspect.signature(getattr(protocol, method)).parameters) == params


def test_resolve_many_timeout_is_keyword_only():
    param = inspect.signature(models.Resolver.resolve_many).parameters["timeout_s"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_audio_player_is_playing_is_a_property():
    assert isinstance(models.AudioPlayer.is_playing, property)
