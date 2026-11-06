"""Qwen3-TTS keeps the owner's pauses: exact digital silence after every letter, stem and choice.

The real parser and ScriptNormalizer build the script (fixtures 02 and 62); a fake backend returns a
constant 0.25 tone of at least 0.3 s per call, so every run of zeros in the WAV is a scripted pause.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pytest

from cloudyreader.config import Settings
from cloudyreader.engine_catalog import Assessment, Pinned, PinnedFile
from cloudyreader.engines.mlxkit import ModelSlot
from cloudyreader.engines.qwen3_decoder import DecoderGate
from cloudyreader.engines.qwen3_tts import Qwen3TtsEngine
from cloudyreader.models import RenderOptions
from cloudyreader.normalize import CHOICE_PAUSE_MS, LETTER_PAUSE_MS, STEM_PAUSE_MS
from tests.unit.pause_probe import mc_script, read_samples, silent_runs

RATE = 24_000
LETTER = re.compile(r"[WXYZ]\.")
FILES = {
    "model.safetensors": b"8-bit talker weights",
    "speech_tokenizer/model.safetensors": b"codec",
}


class ToneBackend:
    """A constant 0.25 tone, 10 ms per character and never under 0.3 s: never an exact zero."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.loaded = False

    def render(
        self, text: str, voice: str, *, seed: int, budget_s: float
    ) -> tuple[np.ndarray, int]:
        self.texts.append(text)
        self.loaded = True
        return np.full(max(round(0.3 * RATE), len(text) * RATE // 100), 0.25, np.float32), RATE

    def close(self) -> None:
        self.loaded = False


@pytest.fixture
def engine(tmp_path: Path) -> Qwen3TtsEngine:
    settings = Settings(tmp_path, tmp_path / "cache", tmp_path / "voices", tmp_path / "models")
    for rel, data in FILES.items():
        (settings.models_dir / "qwen3_tts" / rel).parent.mkdir(parents=True, exist_ok=True)
        (settings.models_dir / "qwen3_tts" / rel).write_bytes(data)
    pins = tuple(PinnedFile(r, len(d), hashlib.sha256(d).hexdigest()) for r, d in FILES.items())
    return Qwen3TtsEngine(
        settings,
        ToneBackend(),
        pinned=Pinned(pins, "0" * 40),
        assess=lambda: Assessment("ready", "", 0, True),
        slot=ModelSlot(),
        decoder=lambda: DecoderGate("patch", "test"),
    )


@pytest.mark.parametrize("voice", [0, 1], ids=["ryan", "aiden"])
def test_every_letter_stem_and_choice_ends_in_exact_silence(
    voice: int, engine: Qwen3TtsEngine, tmp_path: Path
) -> None:
    script, questions = mc_script()
    segments = script.segments

    engine.synthesize(script, engine.voices()[voice], RenderOptions(), tmp_path / "out.wav")

    rate, samples = read_samples(tmp_path / "out.wav")
    assert rate == RATE

    def n(ms: int) -> int:
        return rate * ms // 1000

    paused = [i for i, segment in enumerate(segments) if segment.pause_after_ms >= 250]
    runs = silent_runs(samples, rate, min_ms=250)
    assert runs == [n(segments[i].pause_after_ms) for i in paused]  # exactly the scripted pauses
    after = dict(zip(paused, runs, strict=True))
    letters = [i for i, segment in enumerate(segments) if LETTER.fullmatch(segment.text)]
    multiple_choice = sum(1 for question in questions if question.choices)
    assert multiple_choice >= 1
    assert "".join(segments[i].text[0] for i in letters) == "WXYZ" * multiple_choice
    for i in letters:
        assert after[i] == n(LETTER_PAUSE_MS), f"after letter {segments[i].text}"
        assert not LETTER.fullmatch(segments[i + 1].text)  # the choice text comes next
        assert after[i + 1] >= n(CHOICE_PAUSE_MS), f"after choice {segments[i + 1].text!r}"
    for i in (i - 1 for i in letters if segments[i].text == "W."):
        assert after[i] >= n(STEM_PAUSE_MS), f"after stem {segments[i].text!r}"
    # Every call carries one segment's text at most: a letter is always said on its own.
    assert sum(text in ("W.", "X.", "Y.", "Z.") for text in engine.backend.texts) >= 4
