"""Choice letters pause alike in every engine: exact digital silence in the WAV (fake voices)."""

from __future__ import annotations

import hashlib
import json
import re
import wave
from pathlib import Path

import numpy as np
import pytest

from cloudyreader.engines import kokoro
from cloudyreader.engines.kokoro import SAMPLE_RATE as KOKORO_RATE
from cloudyreader.engines.kokoro import KokoroEngine
from cloudyreader.engines.piper import PiperEngine
from cloudyreader.models import RenderOptions, SpokenScript, VoiceInfo
from cloudyreader.normalize import (
    CHOICE_PAUSE_MS,
    LETTER_PAUSE_MS,
    STEM_PAUSE_MS,
    ScriptNormalizer,
)
from cloudyreader.parser import parse

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "questions"
PASTES = ["02-life-science-respiratory-respelling-mc", "62-multi-crlf-respellings-formulas-three"]
PIPER_RATE = 22050
SYMBOLS = " ,.!?:;ˈˌːabdefhiklmnoprstuvwzæɑɔəɛɪɹɡŋʃʊʌθðɚ"  # as test_piper_engine.py
LETTER = re.compile(r"[WXYZ]\.")


class FakeChunk:
    def __init__(self, samples: np.ndarray) -> None:
        self.sample_rate = PIPER_RATE
        self.audio_int16_bytes = samples.tobytes()


class FakePiperVoice:
    """piper.PiperVoice stand-in, as in test_piper_engine.py: constant sound per sentence."""

    def synthesize(self, text: str, syn_config: object = None):
        for sentence in (s.strip() for s in text.split(".")):
            if sentence:
                yield FakeChunk(np.full(len(sentence) * 10, 1000, dtype=np.int16))


class FakeKokoroBackend:
    """KokoroBackend stand-in, as in test_kokoro_engine.py: 10 ms of constant sound per char."""

    last_skipped: tuple[str, ...] = ()

    def synthesize_line(self, text: str, voice: str, speed: float) -> tuple[np.ndarray, int]:
        return np.full(len(text) * KOKORO_RATE // 100, 0.25, dtype=np.float32), KOKORO_RATE

    def close(self) -> None:
        pass


def piper_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[PiperEngine, VoiceInfo]:
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "en_US-fake-medium.onnx").write_bytes(b"not a real model")
    config = {
        "audio": {"sample_rate": PIPER_RATE, "quality": "medium"},
        "espeak": {"voice": "en-us"},
        "inference": {"noise_scale": 0.667, "length_scale": 1.0, "noise_w": 0.8},
        "phoneme_type": "espeak",
        "phoneme_id_map": {s: [i] for i, s in enumerate(SYMBOLS)},
        "num_symbols": len(SYMBOLS),
        "num_speakers": 1,
        "speaker_id_map": {},
        "language": {"code": "en_US"},
    }
    (voices / "en_US-fake-medium.onnx.json").write_text(json.dumps(config), encoding="utf-8")
    engine = PiperEngine(voices, loader=lambda model, config: FakePiperVoice())
    (voice,) = engine.voices()
    return engine, voice


def kokoro_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[KokoroEngine, VoiceInfo]:
    snap = tmp_path / "models" / "kokoro"
    (snap / "voices").mkdir(parents=True)
    files = {"config.json": b'{"vocab": {}}', "kokoro-v1_0.safetensors": b"weights"}
    for rel, data in files.items():
        (snap / rel).write_bytes(data)
    (snap / "voices" / "af_heart.safetensors").write_bytes(b"voice af_heart")
    sha = {rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()}
    heart = hashlib.sha256(b"voice af_heart").hexdigest()
    monkeypatch.setattr(kokoro, "MODEL_SHA256", sha)
    monkeypatch.setattr(kokoro, "VOICE_SHA256", {**kokoro.VOICE_SHA256, "af_heart": heart})
    monkeypatch.setattr(kokoro, "_supported_platform", lambda: True)
    engine = KokoroEngine(tmp_path / "models", FakeKokoroBackend())
    return engine, next(v for v in engine.voices() if v.key == "kokoro:af_heart")


@pytest.fixture(params=["piper", "kokoro"])
def engine_and_voice(request, tmp_path, monkeypatch):
    build = piper_engine if request.param == "piper" else kokoro_engine
    return build(tmp_path, monkeypatch)


@pytest.fixture(scope="module")
def normalizer() -> ScriptNormalizer:
    return ScriptNormalizer()


def read_samples(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path), "rb") as wav:
        return wav.getframerate(), np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")


def silent_runs(samples: np.ndarray) -> list[int]:
    """Lengths of the runs of exact digital silence (sample == 0), in order."""
    edges = np.flatnonzero(np.diff(np.concatenate(([0], samples == 0, [0])).astype(np.int8)))
    return (edges[1::2] - edges[::2]).tolist()


def silence_after(script: SpokenScript, samples: np.ndarray) -> list[int]:
    """Samples of exact silence after each segment. The fakes never emit a zero sample, so the
    runs of zeros are the pauses, in order, one per segment whose pause is not 0."""
    paused = [i for i, seg in enumerate(script.segments) if seg.pause_after_ms > 0]
    runs = silent_runs(samples)
    assert len(runs) == len(paused), [script.segments[i].text for i in paused]
    after = [0] * len(script.segments)
    for i, run in zip(paused, runs, strict=True):
        after[i] = run
    return after


@pytest.mark.parametrize("fixture", PASTES)
def test_every_letter_stem_and_choice_ends_in_exact_silence(
    fixture, engine_and_voice, normalizer, tmp_path
):
    engine, voice = engine_and_voice
    questions = parse((FIXTURES / f"{fixture}.txt").read_bytes().decode("utf-8"))
    script = normalizer.to_script(questions, {}, RenderOptions())

    engine.synthesize(script, voice, RenderOptions(), tmp_path / "out.wav")

    rate, samples = read_samples(tmp_path / "out.wav")
    after = silence_after(script, samples)
    segments = script.segments

    def ms(pause: int) -> int:
        return rate * pause // 1000

    assert after == [ms(seg.pause_after_ms) for seg in segments]  # exactly the scripted pauses
    letters = [i for i, seg in enumerate(segments) if LETTER.fullmatch(seg.text)]
    multiple_choice = sum(1 for q in questions if q.choices)
    assert multiple_choice >= 1
    assert "".join(segments[i].text[0] for i in letters) == "WXYZ" * multiple_choice
    for i in letters:
        assert after[i] >= ms(LETTER_PAUSE_MS), f"after letter {segments[i].text}"
        assert not LETTER.fullmatch(segments[i + 1].text)  # the choice text comes next
        assert after[i + 1] >= ms(CHOICE_PAUSE_MS), f"after choice {segments[i + 1].text!r}"
    for i in (i - 1 for i in letters if segments[i].text == "W."):
        assert after[i] >= ms(STEM_PAUSE_MS), f"after stem {segments[i].text!r}"
