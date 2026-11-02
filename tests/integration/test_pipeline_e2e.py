"""One real read, nothing faked: parser, NER model, resolvers, normalizer, Piper voice, WAV cache.

Needs the voice and the model (`make voices`, `make models`). Offline, with a tripwire on HTTP,
and no audio is ever played.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import wave
from array import array
from pathlib import Path

import httpx
import pytest

from cloudyreader.config import load_settings
from cloudyreader.models import RenderOptions
from cloudyreader.pipeline import build_default_service

from .fakes import BAKING_RAW, EARTH_RAW, LIFE_RAW

ROOT = Path(__file__).resolve().parents[2]
VOICES_DIR = ROOT / ".data" / "voices"
VOICE = "piper:en_US-lessac-medium"
SOURCES = (
    "parser",
    "entities",
    "lexicon",
    "normalize",
    "tts",
    "engines.piper",
    "resolvers.chain",
    "resolvers.pubchem",
    "resolvers.uniprot",
)
MISSING = [name for name in SOURCES if importlib.util.find_spec(f"cloudyreader.{name}") is None]

pytestmark = [
    pytest.mark.voice,
    pytest.mark.model,
    pytest.mark.slow,
    pytest.mark.skipif(bool(MISSING), reason=f"modules not written yet: {', '.join(MISSING)}"),
    pytest.mark.skipif(
        not (VOICES_DIR / "en_US-lessac-medium.onnx").exists(), reason="run `make voices`"
    ),
    pytest.mark.skipif(
        importlib.util.find_spec("en_ner_craft_md") is None, reason="run `make models`"
    ),
]


@pytest.fixture
def no_http(monkeypatch):
    """Any HTTP request fails the test, even when the code under test swallows the error."""
    sent: list[str] = []

    def refuse(self, request, **kwargs):
        sent.append(str(request.url))
        raise AssertionError("an offline read sent an HTTP request")

    monkeypatch.setattr(httpx.Client, "send", refuse)
    yield sent
    assert sent == []


@pytest.fixture
def service(tmp_path, no_http):
    env = {"CLOUDYREADER_DATA_DIR": str(tmp_path / "data"), "CLOUDYREADER_OFFLINE": "1"}
    settings = dataclasses.replace(load_settings(env), voices_dir=VOICES_DIR)
    return build_default_service(settings)


def read_wav(path: Path) -> tuple[int, int, float, array]:
    with wave.open(str(path), "rb") as wav:
        frames = wav.readframes(wav.getnframes())
        return (
            wav.getnchannels(),
            wav.getsampwidth(),
            wav.getnframes() / wav.getframerate(),
            array("h", frames),
        )


def test_the_sample_question_is_read_end_to_end(service):
    reading = service.prepare(EARTH_RAW, VOICE, RenderOptions())

    channels, width, seconds, samples = read_wav(reading.audio.wav_path)
    assert (channels, width) == (1, 2)
    assert seconds > 3
    assert seconds == pytest.approx(reading.audio.duration_s, abs=0.05)
    assert max(map(abs, samples)) > 1000  # speech, not silence
    assert reading.audio.cache_hit is False
    assert reading.script.text().startswith("Toss-up number two. Earth Science. Multiple choice.")
    assert reading.questions[0].number == 2
    assert reading.warnings == ()


def test_a_repeat_paste_comes_from_the_wav_cache(service):
    first = service.prepare(EARTH_RAW, VOICE, RenderOptions())
    second = service.prepare(EARTH_RAW, VOICE, RenderOptions())

    assert (first.audio.cache_hit, second.audio.cache_hit) == (False, True)
    assert second.audio.wav_path == first.audio.wav_path


def test_respellings_play_cleanly_and_the_answer_adds_speech_only_on_request(service):
    quiet = service.prepare(LIFE_RAW, VOICE, RenderOptions())
    loud = service.prepare(LIFE_RAW, VOICE, RenderOptions(read_answer=True))

    assert quiet.warnings == () and loud.warnings == ()  # no IPA symbol the voice cannot say
    assert "Answer." not in quiet.script.text()
    assert loud.audio.duration_s > quiet.audio.duration_s + 4  # the 5 s pause plus the answer


def test_r5_the_formula_is_spoken_and_never_replaced_by_a_name(service):
    reading = service.prepare(BAKING_RAW, VOICE, RenderOptions())

    spoken = reading.script.text().lower()
    assert "baking" not in spoken and "bicarbonate" not in spoken
    assert reading.audio.wav_path.exists()
