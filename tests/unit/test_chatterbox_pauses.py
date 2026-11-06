"""Chatterbox Turbo keeps the owner's pauses: exact digital silence after every letter, stem and
choice, however a segment is chunked.

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
from cloudyreader.engines.chatterbox_turbo import ChatterboxTurboEngine
from cloudyreader.engines.mlxkit import ModelSlot
from cloudyreader.models import RenderOptions, Segment, SpokenScript
from cloudyreader.normalize import CHOICE_PAUSE_MS, LETTER_PAUSE_MS, STEM_PAUSE_MS
from tests.unit.pause_probe import mc_script, read_samples, silent_runs

RATE = 24_000
LETTER = re.compile(r"[WXYZ]\.")
FILES = {"conds.safetensors": b"built-in voice", "model.safetensors": b"quantized weights"}


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
def engine(tmp_path: Path) -> ChatterboxTurboEngine:
    settings = Settings(tmp_path, tmp_path / "cache", tmp_path / "voices", tmp_path / "models")
    folder = settings.models_dir / "chatterbox_turbo"
    folder.mkdir(parents=True)
    for rel, data in FILES.items():
        (folder / rel).write_bytes(data)
    pins = tuple(PinnedFile(r, len(d), hashlib.sha256(d).hexdigest()) for r, d in FILES.items())
    return ChatterboxTurboEngine(
        settings,
        ToneBackend(),
        pinned=Pinned(pins, "0" * 40),
        assess=lambda: Assessment("ready", "", 0, True),
        slot=ModelSlot(capacity=1),
    )


def test_every_letter_stem_and_choice_ends_in_exact_silence(
    engine: ChatterboxTurboEngine, tmp_path: Path
) -> None:
    script, questions = mc_script()
    segments = script.segments

    engine.synthesize(script, engine.voices()[0], RenderOptions(), tmp_path / "out.wav")

    rate, samples = read_samples(tmp_path / "out.wav")
    assert rate == RATE

    def n(ms: int) -> int:
        return rate * ms // 1000

    paused = [i for i, segment in enumerate(segments) if segment.pause_after_ms > 0]
    assert all(segments[i].pause_after_ms >= 250 for i in paused)  # all visible to the probe
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
    # Every call holds one segment's text at most: each letter is said on its own.
    assert {"W.", "X.", "Y.", "Z."} <= set(engine.backend.texts)


def test_a_chunked_stem_keeps_its_whole_pause_and_only_short_gaps_inside(
    engine: ChatterboxTurboEngine, tmp_path: Path
) -> None:
    stem = " ".join(
        f"Clue {n}: this stem goes on about cells, enzymes and energy." for n in range(12)
    )
    script = SpokenScript(
        (Segment(stem, STEM_PAUSE_MS), Segment("W.", LETTER_PAUSE_MS), Segment("Pharynx"))
    )

    engine.synthesize(script, engine.voices()[0], RenderOptions(), tmp_path / "out.wav")

    rate, samples = read_samples(tmp_path / "out.wav")
    chunks = len(engine.backend.texts) - 2
    assert chunks >= 3
    assert silent_runs(samples, rate, min_ms=250) == [
        rate * STEM_PAUSE_MS // 1000,
        rate * LETTER_PAUSE_MS // 1000,
    ]
    # The 120 ms gaps sit between the stem's own chunks only, never in place of a pause.
    assert silent_runs(samples, rate, min_ms=100) == [
        *[rate * 120 // 1000] * (chunks - 1),
        rate * STEM_PAUSE_MS // 1000,
        rate * LETTER_PAUSE_MS // 1000,
    ]
