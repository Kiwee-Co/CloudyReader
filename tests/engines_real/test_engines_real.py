"""Real engine weights: each installed engine voice renders a lone letter and a sentence, then
each choice letter followed by its exact pause, and plays the shipped clip of each lone letter.

Run by hand: `pytest -m model tests/engines_real`. Skips when the engine module, Apple Silicon
support, or the downloaded weights are missing.
"""

from __future__ import annotations

import dataclasses
import wave
from array import array
from pathlib import Path

import pytest

from cloudyreader.config import load_settings
from cloudyreader.engines import letter_clips, mlxkit
from cloudyreader.models import RenderOptions, Segment, SpokenScript
from cloudyreader.normalize import LETTER_PAUSE_MS

pytestmark = [pytest.mark.model, pytest.mark.slow]

# key: module, engine class, the voice keys it must list once installed
ENGINES = {
    "chatterbox_turbo": (
        "cloudyreader.engines.chatterbox_turbo",
        "ChatterboxTurboEngine",
        {"chatterbox_turbo:builtin"},
    ),
    "qwen3_tts": (
        "cloudyreader.engines.qwen3_tts",
        "Qwen3TtsEngine",
        {"qwen3_tts:ryan", "qwen3_tts:aiden"},
    ),
}
TEXTS = ("W.", "Which layer of the Earth lies directly beneath the crust?")
# One render test per voice, so a voice that fails hides no other voice.
VOICES = sorted((key, voice) for key, (_, _, voices) in ENGINES.items() for voice in voices)


def measure(path: Path) -> tuple[int, int, float, float]:
    """Sample rate, channels, seconds and sample peak (0 to 1) of a 16-bit WAV."""
    with wave.open(str(path), "rb") as wav:
        assert wav.getsampwidth() == 2, f"{path.name}: not 16-bit"
        rate, channels, frames = wav.getframerate(), wav.getnchannels(), wav.getnframes()
        samples = array("h", wav.readframes(frames))
    return rate, channels, frames / rate, max(map(abs, samples), default=0) / 32768


@pytest.fixture(params=sorted(ENGINES))
def engine(request):
    module_name, class_name, _ = ENGINES[request.param]
    module = pytest.importorskip(module_name, reason=f"{request.param}: module not in this tree")
    reason = module.supported()
    if reason:
        pytest.skip(f"{request.param}: {reason}")
    engine = getattr(module, class_name)(dataclasses.replace(load_settings(), offline=True))
    if not engine.available():
        pytest.skip(f"{request.param}: {engine.unavailable_reason}")
    yield engine
    engine.close()


def test_an_installed_engine_lists_its_voices(engine):
    installed = {voice.key for voice in engine.voices() if voice.installed}

    assert installed == ENGINES[engine.key][2]


@pytest.mark.parametrize(
    ("engine", "voice_key"), VOICES, ids=[voice for _, voice in VOICES], indirect=["engine"]
)
def test_each_voice_renders_a_letter_and_a_sentence_as_24k_mono_speech(engine, voice_key, tmp_path):
    voice = {v.key: v for v in engine.voices()}[voice_key]
    for n, text in enumerate(TEXTS):
        out = tmp_path / f"{voice.key.replace(':', '-')}-{n}.wav"
        audio = engine.synthesize(SpokenScript((Segment(text),)), voice, RenderOptions(), out)

        rate, channels, seconds, peak = measure(audio.wav_path)
        # render_text's own rule: the estimate (about 14 characters a second, at least
        # MIN_EST_S), and a render of RUNAWAY times it or more counts as a runaway.
        est = mlxkit.est_seconds(text)
        assert (rate, channels) == (24_000, 1)
        assert 0.25 * est <= seconds < mlxkit.RUNAWAY * est, (voice.key, text, seconds)
        assert peak > 0.01, (voice.key, text, peak)


@pytest.mark.parametrize(
    ("engine", "voice_key"), VOICES, ids=[voice for _, voice in VOICES], indirect=["engine"]
)
def test_each_voice_says_each_choice_letter_alone_then_its_exact_pause(engine, voice_key, tmp_path):
    voice = {v.key: v for v in engine.voices()}[voice_key]
    pause = 24_000 * LETTER_PAUSE_MS // 1000
    est = mlxkit.MIN_EST_S  # a letter is one short unit, whatever words it is said in
    for letter in ("W.", "X.", "Y.", "Z."):  # as the normalizer writes a choice letter
        out = tmp_path / f"{voice.key.replace(':', '-')}-{letter[0]}.wav"
        script = SpokenScript((Segment(letter, LETTER_PAUSE_MS),))
        audio = engine.synthesize(script, voice, RenderOptions(), out)

        rate, channels, seconds, peak = measure(audio.wav_path)
        with wave.open(str(audio.wav_path), "rb") as wav:
            tail = array("h", wav.readframes(wav.getnframes()))[-pause:]
        speech = seconds - LETTER_PAUSE_MS / 1000
        assert (rate, channels) == (24_000, 1)
        assert 0.25 * est <= speech < mlxkit.RUNAWAY * est, (voice.key, letter, speech)
        assert peak > 0.01, (voice.key, letter, peak)
        assert len(tail) == pause and not any(tail), (voice.key, letter)  # exact silence


@pytest.mark.parametrize(
    ("engine", "voice_key"), VOICES, ids=[voice for _, voice in VOICES], indirect=["engine"]
)
def test_each_voice_plays_exactly_its_shipped_clip_for_a_lone_letter(engine, voice_key, tmp_path):
    voice = {v.key: v for v in engine.voices()}[voice_key]
    folder = letter_clips.clips_dir() / engine.key / voice_key.partition(":")[2]
    pause = bytes(2 * 24_000 * LETTER_PAUSE_MS // 1000)
    for letter in "WXYZ":
        with wave.open(str(folder / f"{letter}.wav"), "rb") as wav:
            clip = wav.readframes(wav.getnframes())
        out = tmp_path / f"{voice.key.replace(':', '-')}-{letter}.wav"
        script = SpokenScript((Segment(f"{letter}.", LETTER_PAUSE_MS),))
        engine.synthesize(script, voice, RenderOptions(), out)

        with wave.open(str(out), "rb") as wav:
            assert wav.readframes(wav.getnframes()) == clip + pause, (voice.key, letter)
