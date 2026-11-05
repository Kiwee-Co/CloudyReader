"""Engine data model (P6a): Override.respelling, VoiceInfo.reason and the four engine names."""

import dataclasses
import typing

import pytest

from cloudyreader.models import Override, RenderOptions, Segment, SpokenScript, VoiceInfo
from cloudyreader.tts import _digest

IPA = "ˈfæɹɪŋks"
PLAIN = Override("Pharynx", IPA, "respelling")
GUIDED = Override("Pharynx", IPA, "respelling", respelling="far-ingks")
VOICE = VoiceInfo("piper:en_US-lessac-medium", "piper", "lessac", "en-US", "medium", 1, True)


def test_override_field_order_is_surface_ipa_source_respelling():
    # Every three-argument Override(...) call in the codebase relies on the trailing default.
    names = [f.name for f in dataclasses.fields(Override)]
    assert names == ["surface", "ipa", "source", "respelling"]
    assert PLAIN.respelling == ""
    assert Override("Pharynx", IPA, "respelling", "far-ingks").respelling == "far-ingks"


def test_respelling_is_ignored_by_equality_and_hash():
    assert PLAIN == GUIDED
    assert hash(PLAIN) == hash(GUIDED)
    assert len({PLAIN, GUIDED}) == 1
    assert Segment("Pharynx", 400, (PLAIN,)) == Segment("Pharynx", 400, (GUIDED,))
    # The three original fields still decide equality.
    assert Override("Pharynx", IPA, "lexicon", respelling="far-ingks") != GUIDED
    assert Override("pharynx", IPA, "respelling", respelling="far-ingks") != GUIDED
    with pytest.raises(dataclasses.FrozenInstanceError):
        GUIDED.respelling = "fair-inks"


def test_asdict_includes_respelling_so_the_cache_key_changes():
    assert dataclasses.asdict(PLAIN) == {
        "surface": "Pharynx",
        "ipa": IPA,
        "source": "respelling",
        "respelling": "",
    }
    segment = dataclasses.asdict(Segment("Pharynx", 400, (GUIDED,)))
    assert segment["overrides"][0]["respelling"] == "far-ingks"

    def key(override: Override) -> str:
        script = SpokenScript((Segment("Pharynx", 400, (override,)),))
        return _digest(script, VOICE, RenderOptions(), "engine@1")

    # Equal overrides that a plain-text engine says differently get their own cache entries.
    assert key(PLAIN) != key(GUIDED)
    assert key(GUIDED) == key(Override("Pharynx", IPA, "respelling", respelling="far-ingks"))


def test_voiceinfo_reason_trails_with_an_empty_default():
    names = [f.name for f in dataclasses.fields(VoiceInfo)]
    assert names == [
        "key",
        "engine",
        "name",
        "language",
        "quality",
        "num_speakers",
        "installed",
        "path",
        "reason",
    ]
    assert VOICE.reason == ""
    row = VoiceInfo(
        "qwen3_tts:ryan",
        "qwen3_tts",
        "Ryan (male)",
        "en",
        "8-bit",
        1,
        False,
        None,
        "not downloaded yet",
    )
    assert row.reason == "not downloaded yet"
    assert row.path is None


def test_voiceinfo_engine_literal_names_four_engines():
    engines = typing.get_args(typing.get_type_hints(VoiceInfo)["engine"])
    assert engines == ("piper", "kokoro", "chatterbox_turbo", "qwen3_tts")
