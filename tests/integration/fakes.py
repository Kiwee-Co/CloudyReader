"""Fakes for every pipeline stage: they record calls and never touch network, audio or a model."""

from __future__ import annotations

import dataclasses
import itertools
import re
import threading
import time
import wave
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloudyreader.config import Settings
from cloudyreader.models import (
    Audio,
    Choice,
    EntitySpan,
    Fmt,
    Kind,
    Question,
    RenderOptions,
    Resolution,
    Respelling,
    Segment,
    SpokenScript,
    VoiceInfo,
)
from cloudyreader.pipeline import Pipeline

# Paths that do not exist: a fake-based test that touches the disk by mistake fails loudly.
SETTINGS = Settings(
    *(Path("/nonexistent") / name for name in ("data", "cache", "voices", "models"))
)

VOICE_A, VOICE_B, VOICE_C = "piper:fake-a", "piper:fake-b", "kokoro:fake-c"
VOICES = (
    VoiceInfo(VOICE_A, "piper", "Fake A", "en-US", "medium", 1, True, Path("/nonexistent/a.onnx")),
    VoiceInfo(VOICE_B, "piper", "Fake B", "en-US", "medium", 1, True, Path("/nonexistent/b.onnx")),
    VoiceInfo(VOICE_C, "kokoro", "Fake C", "en-US", "high", 1, False),
)

EARTH_RAW = (
    "TOSS-UP\n"
    "2) EARTH SCIENCE Multiple Choice The source of energy for the movements of\n"
    "crustal plates is currently thought to be the result of:\n"
    "W) tidal motion that produces a net westward movement of landmasses\n"
    "X) the pulling apart of the poles resulting from the Earth’s rotation\n"
    "Y) convection currents produced within the mantle\n"
    "Z) remnant magnetism\n"
)
EARTH = Question(
    Kind.TOSS_UP,
    2,
    "EARTH SCIENCE",
    Fmt.MULTIPLE_CHOICE,
    "The source of energy for the movements of crustal plates is currently thought to be the "
    "result of:",
    (
        Choice("W", "tidal motion that produces a net westward movement of landmasses"),
        Choice("X", "the pulling apart of the poles resulting from the Earth’s rotation"),
        Choice("Y", "convection currents produced within the mantle"),
        Choice("Z", "remnant magnetism"),
    ),
    None,
    EARTH_RAW,
)

LIFE_RAW = (
    "1) LIFE SCIENCE Multiple Choice Which of the following is NOT part of the human respiratory\n"
    "system?\n"
    "W) Pharynx [FAR-ingks]\n"
    "X) Larynx [LAR-ingks]\n"
    "Y) Esophagus [i-SOF-uh-guhs]\n"
    "Z) Trachea [TRAY-kee-uh]\n"
    "ANSWER: Y) ESOPHAGUS\n"
)
LIFE = Question(
    None,
    1,
    "LIFE SCIENCE",
    Fmt.MULTIPLE_CHOICE,
    "Which of the following is NOT part of the human respiratory system?",
    (
        Choice("W", "Pharynx", (Respelling("Pharynx", "FAR-ingks"),)),
        Choice("X", "Larynx", (Respelling("Larynx", "LAR-ingks"),)),
        Choice("Y", "Esophagus", (Respelling("Esophagus", "i-SOF-uh-guhs"),)),
        Choice("Z", "Trachea", (Respelling("Trachea", "TRAY-kee-uh"),)),
    ),
    "Y) ESOPHAGUS",
    LIFE_RAW,
)

BAKING_RAW = "5) CHEMISTRY Short Answer Name the compound with the formula NaHCO3.\n"
BAKING = Question(
    Kind.TOSS_UP,
    5,
    "CHEMISTRY",
    Fmt.SHORT_ANSWER,
    "Name the compound with the formula NaHCO3.",
    (),
    None,
    BAKING_RAW,
)


def collapsed(log: Sequence[str]) -> list[str]:
    """The call log with runs of the same call merged: six detect() calls read as one."""
    return [name for name, _ in itertools.groupby(log)]


def wait_until(condition: Callable[[], object], timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.005)
    return True


class FakeParser:
    """Returns the questions it was built with, whatever the paste says."""

    def __init__(self, questions: Sequence[Question], log: list[str]) -> None:
        self.questions = list(questions)
        self.raws: list[str] = []
        self.error: Exception | None = None
        self._log = log

    def parse(self, raw: str) -> list[Question]:
        self._log.append("parse")
        self.raws.append(raw)
        if self.error is not None:
            raise self.error
        return list(self.questions)


class FakeDetector:
    """Tags every occurrence of a vocabulary term. Has no `preload`, like a plain detector."""

    def __init__(
        self, log: list[str], vocab: Mapping[str, str] | None = None, source: str = "ner"
    ) -> None:
        self.vocab = {"NaHCO3": "formula", "mantle": "other"} if vocab is None else dict(vocab)
        self.source = source
        self.texts: list[str] = []
        self.error: Exception | None = None
        self._log = log

    def detect(self, text: str) -> list[EntitySpan]:
        self._log.append("detect")
        self.texts.append(text)
        if self.error is not None:
            raise self.error
        spans = [
            EntitySpan(m.start(), m.end(), m.group(), label, self.source)  # type: ignore[arg-type]
            for term, label in self.vocab.items()
            for m in re.finditer(re.escape(term), text)
        ]
        return sorted(spans, key=lambda span: span.start)


class PreloadingDetector(FakeDetector):
    """A detector whose `preload` blocks on `gate` and can fail, to prove nobody waits for it."""

    def __init__(
        self,
        log: list[str],
        *,
        gate: threading.Event | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__(log)
        self.started = threading.Event()
        self.finished = threading.Event()
        self.preload_thread: threading.Thread | None = None
        self._gate = gate
        self._error = error

    def preload(self) -> None:
        self.preload_thread = threading.current_thread()
        self.started.set()
        try:
            if self._gate is not None:
                self._gate.wait(5)
            if self._error is not None:
                raise self._error
        finally:
            self.finished.set()


class FakeResolver:
    """Resolves every span. `canonical` invents the common name a real source would return."""

    def __init__(
        self, log: list[str], name: str, canonical: Mapping[str, str] | None = None
    ) -> None:
        self.canonical = dict(canonical or {})
        self.calls: list[tuple[list[EntitySpan], float]] = []
        self.error: Exception | None = None
        self._log = log
        self._name = name

    def resolve_many(
        self, spans: Sequence[EntitySpan], *, timeout_s: float
    ) -> dict[str, Resolution]:
        self._log.append(self._name)
        self.calls.append((list(spans), timeout_s))
        if self.error is not None:
            raise self.error
        return {
            span.text: Resolution(
                span.text,
                "chemical",
                self.canonical.get(span.text, f"common name of {span.text}"),
                {"cid": "1"},
                "pubchem",
                "ok",
            )
            for span in spans
        }


class FakeNormalizer:
    """A trimmed spoken-script convention: stem, choices, answer only on request, 1500 ms gaps."""

    def __init__(self, log: list[str], warnings: Sequence[str] = ()) -> None:
        self.calls: list[tuple[list[Question], dict[str, Resolution], RenderOptions]] = []
        self.script: SpokenScript | None = None
        self.error: Exception | None = None
        self._log = log
        self._warnings = tuple(warnings)

    def to_script(
        self,
        questions: Sequence[Question],
        resolutions: Mapping[str, Resolution],
        opts: RenderOptions,
    ) -> SpokenScript:
        self._log.append("normalize")
        self.calls.append((list(questions), dict(resolutions), opts))
        if self.error is not None:
            raise self.error
        segments: list[Segment] = []
        for index, question in enumerate(questions):
            group = [Segment(question.stem, 700 if question.choices else 0)]
            group += [Segment(f"{c.letter}. {c.text}", 400) for c in question.choices]
            if opts.read_answer and question.answer:
                group.append(Segment(f"Answer. {question.answer}.", 0))
            if index < len(questions) - 1:
                group[-1] = dataclasses.replace(group[-1], pause_after_ms=1500)
            segments += group
        self.script = SpokenScript(tuple(segments), warnings=self._warnings)
        return self.script


@dataclass(frozen=True)
class SynthCall:
    script: SpokenScript
    voice: VoiceInfo
    opts: RenderOptions


class FakeTts:
    """Stands in for TtsService without a cache: every synthesize() is recorded."""

    def __init__(self, log: list[str], voices: Sequence[VoiceInfo] = VOICES) -> None:
        self.voice_list = list(voices)
        self.calls: list[SynthCall] = []
        self.error: Exception | None = None
        self.audio = Audio(Path("/nonexistent/fake.wav"), 22_050, 1.0, False)
        self._log = log

    def voices(self) -> list[VoiceInfo]:
        self._log.append("voices")
        return list(self.voice_list)

    def synthesize(self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions) -> Audio:
        self._log.append("synthesize")
        self.calls.append(SynthCall(script, voice, opts))
        if self.error is not None:
            raise self.error
        return self.audio


class WarningTts(FakeTts):
    """Adds both engine-note hooks: `script_warnings()` and `last_warnings`, set by synthesize()."""

    def __init__(
        self, log: list[str], warnings: Sequence[str] = (), last: Sequence[str] = ()
    ) -> None:
        super().__init__(log)
        self.warnings = tuple(warnings)
        self.noted = tuple(last)
        self.last_warnings: list[str] = ["stale note from an earlier synthesis"]
        self.error_on_warnings: Exception | None = None

    def synthesize(self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions) -> Audio:
        audio = super().synthesize(script, voice, opts)
        self.last_warnings = list(self.noted)
        return audio

    def script_warnings(self, script: SpokenScript, voice: VoiceInfo) -> tuple[str, ...]:
        if self.error_on_warnings is not None:
            raise self.error_on_warnings
        return self.warnings


class CountingEngine:
    """A TtsEngine for the real TtsService: writes 0.1 s of silence and counts calls."""

    key = "piper"

    def __init__(self, voices: Sequence[VoiceInfo] = VOICES[:2]) -> None:
        self.voice_list = list(voices)
        self.calls: list[SpokenScript] = []

    def available(self) -> bool:
        return True

    def voices(self) -> list[VoiceInfo]:
        return list(self.voice_list)

    def synthesize(
        self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions, out_wav: Path
    ) -> Audio:
        self.calls.append(script)
        rate = 8000
        with wave.open(str(out_wav), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(b"\x00\x00" * (rate // 10))
        return Audio(out_wav, rate, 0.1, False)


@dataclass
class Rig:
    pipeline: Pipeline
    log: list[str]
    parser: FakeParser
    detector: FakeDetector
    resolver: FakeResolver
    offline_resolver: FakeResolver
    normalizer: FakeNormalizer
    tts: Any


def make_rig(
    *,
    questions: Sequence[Question] = (EARTH,),
    settings: Settings = SETTINGS,
    log: list[str] | None = None,
    detector: FakeDetector | None = None,
    tts: Any = None,
    normalizer: Any = None,
    canonical: Mapping[str, str] | None = None,
    script_warnings: Sequence[str] = (),
    with_offline_resolver: bool = True,
) -> Rig:
    log = [] if log is None else log
    parser = FakeParser(questions, log)
    detector = detector or FakeDetector(log)
    resolver = FakeResolver(log, "resolve", canonical)
    offline_resolver = FakeResolver(log, "offline-resolve", canonical)
    normalizer = normalizer or FakeNormalizer(log, script_warnings)
    tts = tts or FakeTts(log)
    pipeline = Pipeline(
        parser=parser,
        detector=detector,
        resolver=resolver,
        normalizer=normalizer,
        tts=tts,
        settings=settings,
        offline_resolver=offline_resolver if with_offline_resolver else None,
    )
    return Rig(pipeline, log, parser, detector, resolver, offline_resolver, normalizer, tts)
