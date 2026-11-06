"""Real engine weights: each installed engine voice renders a lone letter and a sentence.

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
from cloudyreader.models import RenderOptions, Segment, SpokenScript

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


def test_each_voice_renders_a_letter_and_a_sentence_as_24k_mono_speech(engine, tmp_path):
    for voice in engine.voices():
        for n, text in enumerate(TEXTS):
            out = tmp_path / f"{voice.key.replace(':', '-')}-{n}.wav"
            audio = engine.synthesize(SpokenScript((Segment(text),)), voice, RenderOptions(), out)

            rate, channels, seconds, peak = measure(audio.wav_path)
            # The engines' estimate and runaway rule: about 14 characters a second, at least
            # 0.6 s; a runaway passes 1.9 x that, and a tiny unit may run to 1.2 s.
            est = max(0.6, len(text) / 14)
            assert (rate, channels) == (24_000, 1)
            assert 0.25 * est <= seconds <= max(1.2, 1.9 * est), (voice.key, text, seconds)
            assert peak > 0.01, (voice.key, text, peak)
