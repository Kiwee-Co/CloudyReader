"""Silence probe for the pause contract tests of the MLX engines (P2, P3).

Copies of P0's helpers in test_choice_pauses.py, so the engine tests never wait for that file.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from cloudyreader.models import Question, RenderOptions, SpokenScript
from cloudyreader.normalize import ScriptNormalizer
from cloudyreader.parser import parse

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "questions"
PASTES = ("02-life-science-respiratory-respelling-mc", "62-multi-crlf-respellings-formulas-three")


def read_samples(path: Path) -> tuple[int, np.ndarray]:
    """(rate, int16 samples) of a mono 16-bit WAV."""
    with wave.open(str(path), "rb") as wav:
        return wav.getframerate(), np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")


def silent_runs(samples: np.ndarray, rate: int, min_ms: int = 250) -> list[int]:
    """Lengths, in samples, of the runs of exact digital silence (sample == 0) lasting min_ms or
    more, in order. The floor keeps the 120 ms between the chunks of one segment out."""
    zero = np.asarray(samples) == 0
    edges = np.flatnonzero(np.diff(np.concatenate(([0], zero, [0])).astype(np.int8)))
    runs = (edges[1::2] - edges[::2]).tolist()
    return [run for run in runs if run * 1000 >= min_ms * rate]


def mc_script() -> tuple[SpokenScript, list[Question]]:
    """The real parser and ScriptNormalizer on fixtures 02 and 62, read as one paste."""
    questions = [
        question
        for name in PASTES
        for question in parse((FIXTURES / f"{name}.txt").read_bytes().decode("utf-8"))
    ]
    return ScriptNormalizer().to_script(questions, {}, RenderOptions()), questions
