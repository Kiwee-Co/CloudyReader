"""Qwen3TtsEngine and MlxQwenBackend against fakes; a tripwire on mlx-audio's Qwen3-TTS source.

Real inference cannot run here: the engine runs against FakeBackend, the backend against fake
`mlx.core` and `mlx_audio` modules in sys.modules. Real audio is the owner's smoke run.
"""

from __future__ import annotations

import ast
import base64
import functools
import hashlib
import importlib.metadata
import importlib.util
import os
import subprocess
import sys
import types
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from cloudyreader import engine_catalog
from cloudyreader.config import Settings
from cloudyreader.engine_catalog import Assessment, Pinned, PinnedFile
from cloudyreader.engines import mlxkit
from cloudyreader.engines import qwen3_decoder as qd
from cloudyreader.engines import qwen3_tts as qt
from cloudyreader.engines.mlxkit import EngineError, EngineUnavailable, ModelSlot
from cloudyreader.engines.qwen3_decoder import WAITING, DecoderGate
from cloudyreader.engines.qwen3_tts import (
    MlxQwenBackend,
    Qwen3TtsEngine,
    finish,
    gate,
    neutralize,
    supported,
    token_cap,
)
from cloudyreader.models import Override, RenderOptions, Segment, SpokenScript, VoiceInfo

ROOT = Path(__file__).resolve().parents[2]
RATE = 24_000
LEVEL = 0.25
PCM_LEVEL = 8192  # rint(0.25 * 32767)
MIN_TAKE_S = 0.3  # FakeBackend never returns less: render_text treats under 0.1 s as a failure
REV = "0123456789abcdef0123456789abcdef01234567"
# The mlx-audio 0.6.3 RECORD entry of the audited Qwen3-TTS model file. A bump fails here on
# purpose: re-audit the tokenizer load and the download sites, then update both values.
RECORD_HASH = "zyZP9R-hbCMsyl3tPOBSr29PETfRNxuGup9OKhpSbwo"
RECORD_SIZE = 113_843
FILES = {
    "config.json": b'{"model_type": "qwen3_tts"}',
    "generation_config.json": b'{"temperature": 0.9}',
    "merges.txt": b"#version: 0.2",
    "model.safetensors": b"8-bit talker weights",
    "speech_tokenizer/config.json": b"{}",
    "speech_tokenizer/model.safetensors": b"codec weights",
    "tokenizer_config.json": b"{}",
    "vocab.json": b"{}",
}
READY = Assessment("ready", "", 0, True)
PATCH = DecoderGate("patch", "mlx-audio 0.6.3 decoder: window patched in")
BLOCKED = DecoderGate("blocked", f"{WAITING} (unknown decoder Ab12Cd34)")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def samples(seconds: float) -> int:
    return round(seconds * RATE)


def fake_len(text: str) -> int:
    """Samples FakeBackend returns for `text`: 10 ms per character, at least MIN_TAKE_S."""
    return samples(max(MIN_TAKE_S, len(text) / 100))


class FakeBackend:
    """Constant 0.25 audio (fake_len); `plan[text]` scripts the attempts: seconds, an array or
    an exception."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, float]] = []
        self.plan: dict[str, list[float | np.ndarray | Exception]] = {}
        self.rate = RATE
        self.loaded = False
        self.closed = False

    def render(
        self, text: str, voice: str, *, seed: int, budget_s: float
    ) -> tuple[np.ndarray, int]:
        self.calls.append((text, voice, seed, budget_s))
        self.loaded = True
        audio = np.full(fake_len(text), LEVEL, dtype=np.float32)
        if steps := self.plan.get(text):
            step = steps.pop(0)
            if isinstance(step, Exception):
                raise step
            audio = step if isinstance(step, np.ndarray) else np.full(samples(step), LEVEL)
        return np.asarray(audio, dtype=np.float32), self.rate

    def close(self) -> None:
        self.closed = True
        self.loaded = False

    @property
    def texts(self) -> list[str]:
        return [call[0] for call in self.calls]


def install(settings: Settings, files: dict[str, bytes] = FILES) -> Pinned:
    """Write `files` into the engine folder and pin them, the way the startup run leaves them."""
    model_dir = settings.models_dir / "qwen3_tts"
    for rel, data in files.items():
        (model_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (model_dir / rel).write_bytes(data)
    pins = tuple(PinnedFile(rel, len(data), sha(data)) for rel, data in sorted(files.items()))
    return Pinned(pins, REV)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        voices_dir=tmp_path / "voices",
        models_dir=tmp_path / "models",
    )


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def engine(settings: Settings, backend: FakeBackend) -> Qwen3TtsEngine:
    return Qwen3TtsEngine(
        settings,
        backend,
        pinned=install(settings),
        assess=lambda: READY,
        slot=ModelSlot(),
        decoder=lambda: PATCH,
    )


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (RATE, 1, 2)
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")


def runs(pcm: np.ndarray) -> list[tuple[int, int]]:
    """(value, length) runs: FakeBackend audio is PCM_LEVEL, silence is 0."""
    out: list[tuple[int, int]] = []
    for value in pcm.tolist():
        if out and out[-1][0] == value:
            out[-1] = (value, out[-1][1] + 1)
        else:
            out.append((value, 1))
    return out


def speak(
    engine: Qwen3TtsEngine,
    out: Path,
    *segments: Segment,
    opts: RenderOptions | None = None,
    voice: int = 0,
) -> np.ndarray:
    chosen = engine.voices()[voice]
    audio = engine.synthesize(SpokenScript(tuple(segments)), chosen, opts or RenderOptions(), out)
    pcm = read_wav(out)
    assert audio.wav_path == out
    assert audio.sample_rate == RATE
    assert audio.duration_s == pytest.approx(len(pcm) / RATE)
    assert audio.cache_hit is False
    return pcm


RYAN = VoiceInfo("qwen3_tts:ryan", "qwen3_tts", "Ryan (male)", "en", "8-bit", 1, True)


# --- voices and availability ----------------------------------------------------------------------


def test_voices_lists_ryan_and_aiden(engine: Qwen3TtsEngine, settings: Settings) -> None:
    folder = settings.models_dir / "qwen3_tts"

    assert engine.available() is True
    assert engine.unavailable_reason is None
    assert engine.voices() == [
        VoiceInfo("qwen3_tts:ryan", "qwen3_tts", "Ryan (male)", "en", "8-bit", 1, True, folder),
        VoiceInfo(
            "qwen3_tts:aiden", "qwen3_tts", "Aiden (male)", "en-US", "8-bit", 1, True, folder
        ),
    ]
    assert engine.placeholder_voices() == []
    assert engine.key == "qwen3_tts"


@pytest.mark.parametrize(
    ("assessment", "listed"),
    [
        (Assessment("blocked", "Qwen3-TTS needs an Apple Silicon Mac (arm64)", 0, False), False),
        (Assessment("blocked", engine_catalog.NOT_PINNED, 0, False), False),
        (Assessment("blocked", BLOCKED.reason, 0, True), True),
        (Assessment("missing", engine_catalog.NOT_DOWNLOADED, 1_973_572_801, True), True),
        (Assessment("missing", engine_catalog.OFFLINE, 1_973_572_801, True), True),
        (Assessment("blocked", engine_catalog.NOT_WRITABLE, 1_973_572_801, True), True),
        (Assessment("broken", "damaged: model.safetensors has the wrong size", 0, True), True),
    ],
)
def test_unavailable_reasons(
    assessment: Assessment, listed: bool, settings: Settings, backend: FakeBackend, tmp_path: Path
) -> None:
    engine = Qwen3TtsEngine(
        settings,
        backend,
        pinned=install(settings),
        assess=lambda: assessment,
        decoder=lambda: PATCH,
    )

    assert engine.available() is False
    assert engine.unavailable_reason == assessment.reason
    assert engine.voices() == []
    rows = engine.placeholder_voices()
    if listed:
        assert [(row.key, row.reason, row.installed) for row in rows] == [
            ("qwen3_tts:ryan", assessment.reason, False),
            ("qwen3_tts:aiden", assessment.reason, False),
        ]
    else:  # a hard blocker or an unpinned engine lists nothing
        assert rows == []
    with pytest.raises(EngineUnavailable, match="."):
        engine.synthesize(SpokenScript((Segment("Hi."),)), RYAN, RenderOptions(), tmp_path / "x")
    assert backend.calls == []


def test_the_default_assess_and_pins_come_from_the_catalog(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[Any, str]] = []

    def pinned(s: Settings, engine: str, **kwargs: Any) -> Pinned:
        asked.append((s, engine))
        return Pinned((), "")

    monkeypatch.setattr(engine_catalog, "pinned", pinned)
    engine = Qwen3TtsEngine(settings, decoder=lambda: PATCH)

    assert asked == [(settings, "qwen3_tts")]
    assert isinstance(engine._assess, functools.partial)
    assert engine._assess.func is engine_catalog.assess
    assert engine._assess.args == (settings, "qwen3_tts")
    assert isinstance(engine.backend, MlxQwenBackend)
    assert engine.backend.model_dir == settings.models_dir / "qwen3_tts"


def test_supported_asks_mlx_support_without_importing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, ...], str]] = []

    def support(modules: tuple[str, ...], subpackage: str) -> str | None:
        calls.append((tuple(modules), subpackage))
        return "not in this build"

    monkeypatch.setattr(qt, "mlx_support", support)
    monkeypatch.setattr(qt.sys, "platform", "darwin")
    monkeypatch.setattr(qt.platform, "machine", lambda: "arm64")
    assert supported() == "not in this build"
    assert calls == [(("mlx", "mlx_audio", "transformers"), "mlx_audio.tts.models.qwen3_tts")]

    monkeypatch.setattr(qt.platform, "machine", lambda: "x86_64")
    assert supported() == "Qwen3-TTS needs an Apple Silicon Mac (arm64)"
    assert len(calls) == 1


def test_gate_reports_the_decoder_reason_only_while_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"gate": BLOCKED}
    monkeypatch.setattr(qt, "decoder_gate", lambda: state["gate"])
    assert gate() == BLOCKED.reason

    state["gate"] = PATCH
    assert gate() is None
    state["gate"] = DecoderGate("upstream", "fixed")
    assert gate() is None


def test_available_is_false_while_the_decoder_gate_blocks(
    settings: Settings, backend: FakeBackend, tmp_path: Path
) -> None:
    state = {"gate": BLOCKED}
    engine = Qwen3TtsEngine(
        settings,
        backend,
        pinned=install(settings),
        assess=lambda: READY,
        decoder=lambda: state["gate"],
    )

    assert engine.available() is False
    assert engine.unavailable_reason == BLOCKED.reason
    assert [row.reason for row in engine.placeholder_voices()] == [BLOCKED.reason] * 2
    with pytest.raises(EngineUnavailable, match="waiting for a Qwen3 decoder fix"):
        engine.synthesize(SpokenScript((Segment("Hi."),)), RYAN, RenderOptions(), tmp_path / "x")
    assert backend.calls == []

    state["gate"] = PATCH
    assert engine.available() is True
    assert engine.placeholder_voices() == []


def test_placeholder_rows_carry_the_reason_and_hard_blockers_list_nothing(
    settings: Settings, backend: FakeBackend
) -> None:
    state = {"now": Assessment("missing", "not downloaded yet", 1_973_572_801, True)}
    engine = Qwen3TtsEngine(
        settings,
        backend,
        pinned=install(settings),
        assess=lambda: state["now"],
        decoder=lambda: PATCH,
    )

    ryan, aiden = engine.placeholder_voices()
    assert (ryan.key, ryan.name, ryan.installed, ryan.path, ryan.reason) == (
        "qwen3_tts:ryan",
        "Ryan (male)",
        False,
        None,
        "not downloaded yet",
    )
    assert (aiden.key, aiden.language, aiden.reason) == ("qwen3_tts:aiden", "en-US", ryan.reason)
    assert engine.voices() == []

    state["now"] = Assessment("blocked", "Qwen3-TTS needs an Apple Silicon Mac (arm64)", 0, False)
    assert engine.placeholder_voices() == []

    state["now"] = Assessment("broken", "", 0, True)  # a state without a reason still says why
    assert engine.placeholder_voices()[0].reason == "Qwen3-TTS is unavailable"


def test_hash_is_checked_before_first_load_and_a_mismatch_is_sticky(
    settings: Settings, backend: FakeBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pinned = install(settings)
    weights = settings.models_dir / "qwen3_tts" / "speech_tokenizer" / "model.safetensors"
    weights.write_bytes(b"CODEC WEIGHTS")  # same size as the pin: only a hash can tell
    verify_calls: list[Path] = []
    original = mlxkit.ModelFiles.verify

    def counting(self: mlxkit.ModelFiles) -> str | None:
        verify_calls.append(self.model_dir)
        return original(self)

    monkeypatch.setattr(mlxkit.ModelFiles, "verify", counting)
    engine = Qwen3TtsEngine(
        settings, backend, pinned=pinned, assess=lambda: READY, decoder=lambda: PATCH
    )
    voice = engine.voices()[0]
    script = SpokenScript((Segment("Hello there."),))

    assert engine.available() is True
    assert verify_calls == []  # listing never hashes

    with pytest.raises(EngineUnavailable, match=r"^damaged: .*model\.safetensors"):
        engine.synthesize(script, voice, RenderOptions(), tmp_path / "a.wav")
    assert backend.calls == []  # the check runs before the first load
    assert engine.available() is False
    assert (engine.unavailable_reason or "").startswith("damaged: ")
    assert engine.placeholder_voices()[0].reason == engine.unavailable_reason

    with pytest.raises(EngineUnavailable, match="damaged"):
        engine.synthesize(script, voice, RenderOptions(), tmp_path / "b.wav")
    assert len(verify_calls) == 1  # sticky: no second hash of unchanged files

    weights.write_bytes(FILES["speech_tokenizer/model.safetensors"])  # repaired: new mtime
    os.utime(weights, ns=(1, 1))
    assert engine.available() is True
    engine.synthesize(script, voice, RenderOptions(), tmp_path / "c.wav")
    engine.synthesize(script, voice, RenderOptions(), tmp_path / "d.wav")
    assert len(verify_calls) == 2  # verified once for this file state
    assert backend.texts == ["Hello there."]  # the second reading was memoized

    weights.unlink()  # a new file state: hashed again before the next load
    with pytest.raises(EngineUnavailable, match=r"^damaged: "):
        engine.synthesize(script, voice, RenderOptions(), tmp_path / "e.wav")
    assert len(verify_calls) == 3


def test_foreign_or_unknown_voices_are_refused(engine: Qwen3TtsEngine, tmp_path: Path) -> None:
    script = SpokenScript((Segment("Hello."),))
    kokoro = VoiceInfo("kokoro:af_heart", "kokoro", "Heart", "en-US", "A", 1, True)
    clone = VoiceInfo("qwen3_tts:clone", "qwen3_tts", "x", "en", "8-bit", 1, True)
    for voice in (kokoro, clone):
        with pytest.raises(ValueError, match="not a Qwen3-TTS voice"):
            engine.synthesize(script, voice, RenderOptions(), tmp_path / "x.wav")


# --- synthesis ------------------------------------------------------------------------------------


def test_synthesize_writes_24k_mono_16bit(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    first, second = "Which gas is most abundant in air?", "Nitrogen."
    pcm = speak(engine, tmp_path / "out.wav", Segment(first, 700), Segment(second, 250), voice=1)

    assert runs(pcm) == [
        (PCM_LEVEL, fake_len(first)),
        (0, samples(0.7)),
        (PCM_LEVEL, fake_len(second)),
        (0, samples(0.25)),
    ]
    assert backend.texts == [first, second]
    assert {voice for _, voice, _, _ in backend.calls} == {"aiden"}
    assert engine.last_warnings == []


def test_no_backend_call_ever_holds_the_text_of_two_segments(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    segments = (
        Segment("Which gas is most abundant?", 700),
        Segment("W.", 300),
        Segment("Nitrogen", 400),
        Segment("X.", 0),  # no pause at all: still its own call, never "X. Oxygen."
        Segment("Oxygen", 0),
    )
    pcm = speak(engine, tmp_path / "out.wav", *segments)

    said = ["Which gas is most abundant?", "W.", "Nitrogen.", "X.", "Oxygen."]
    assert backend.texts == said  # one call per segment, each ending on terminal punctuation
    assert runs(pcm) == [
        (PCM_LEVEL, fake_len(said[0])),
        (0, samples(0.7)),
        (PCM_LEVEL, fake_len("W.")),
        (0, samples(0.3)),
        (PCM_LEVEL, fake_len(said[2])),
        (0, samples(0.4)),
        (PCM_LEVEL, fake_len("X.") + fake_len("Oxygen.")),
    ]


def test_a_segment_split_into_many_chunks_keeps_its_full_trailing_pause(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    sentences = [
        f"Sentence number {n} talks about cells, enzymes, and the energy they need to divide"
        for n in range(1, 15)
    ]
    text = "; ".join(sentences)
    assert len(text) > 1000
    pcm = speak(engine, tmp_path / "out.wav", Segment(text, 700), Segment("W.", 300))

    chunks = backend.texts[:-1]
    assert len(chunks) >= 4
    assert all(len(chunk) <= qt.MAX_CHUNK_CHARS + qt.MIN_CHUNK_CHARS + 1 for chunk in chunks)
    assert all(chunk[-1] in ".!?" for chunk in chunks)  # a trailing ; or , became a period

    def words(said: str) -> list[str]:
        return [word.rstrip(".,;") for word in said.split()]

    assert words(" ".join(chunks)) == words(text)  # every word, in order
    expected: list[tuple[int, int]] = []
    for index, chunk in enumerate(chunks):
        if index:
            expected.append((0, samples(0.12)))  # INTER_CHUNK_MS between chunks of one segment
        expected.append((PCM_LEVEL, fake_len(chunk)))
    expected += [(0, samples(0.7)), (PCM_LEVEL, fake_len("W.")), (0, samples(0.3))]
    assert runs(pcm) == expected


def test_a_short_unit_falls_back_to_repeat_and_crop(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    burst, gap = np.full(samples(0.3), LEVEL), np.zeros(samples(0.25))
    repeated = np.concatenate([burst, gap, burst, gap, burst]).astype(np.float32)
    backend.plan["W."] = [60.0, RuntimeError("short input")]  # both lone takes fail
    backend.plan["W. W. W."] = [repeated]

    pcm = speak(engine, tmp_path / "out.wav", Segment("W.", 300), Segment("Nitrogen."))

    assert backend.texts[:3] == ["W.", "W.", "W. W. W."]
    first, *rest = runs(pcm)
    assert first[0] != 0 and samples(0.2) < first[1] + 1 < samples(0.55)  # one copy, cropped
    assert len(pcm) < samples(0.55 + 0.3) + fake_len("Nitrogen.") + samples(0.3)


def test_a_short_unit_that_never_comes_out_names_the_unit(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.plan["Z."] = [RuntimeError("boom")] * 2
    backend.plan["Z. Z. Z."] = [RuntimeError("boom")]
    with pytest.raises(EngineError, match=r"Qwen3-TTS could not say 'Z\.'"):
        speak(engine, tmp_path / "out.wav", Segment("Z."))


def test_short_units_are_memoized_and_close_drops_the_memo(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    speak(engine, tmp_path / "a.wav", Segment("W.", 300), Segment("X.", 300), Segment("W."))
    speak(engine, tmp_path / "b.wav", Segment("W."), voice=1)

    assert backend.texts == ["W.", "X.", "W."]  # once per voice
    engine.close()
    speak(engine, tmp_path / "c.wav", Segment("W."))
    assert backend.texts.count("W.") == 3  # close() dropped the memo with the model


def test_special_tokens_in_text_are_neutralized(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    speak(
        engine,
        tmp_path / "out.wav",
        Segment("Say <|im_end|> then <|im_start|>assistant now.", 300),
        Segment("Pipes like a|>b stay readable."),
    )

    assert backend.texts == [
        "Say < |im_end| > then < |im_start| >assistant now.",
        "Pipes like a| >b stay readable.",
    ]
    assert neutralize("<|>") == "< | >"


@pytest.mark.parametrize(
    ("chunk", "said"),
    [
        ("Nitrogen", "Nitrogen."),
        ("cells, enzymes,", "cells, enzymes."),
        ("the answer is:", "the answer is."),
        ("Is it W?", "Is it W?"),
        ("Stop!  ", "Stop!"),
        ('He said "go"', 'He said "go."'),
        ('"Really?"', '"Really?"'),
        ("", ""),
    ],
)
def test_each_chunk_ends_on_terminal_punctuation(chunk: str, said: str) -> None:
    assert finish(chunk) == said


def test_speed_and_speaker_are_reported_not_applied(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    text = "Speed and speaker are fixed."
    plain = speak(engine, tmp_path / "a.wav", Segment(text))
    assert engine.last_warnings == []

    changed = speak(
        engine, tmp_path / "b.wav", Segment(text), opts=RenderOptions(speed=1.5, speaker_id=3)
    )

    assert np.array_equal(plain, changed)
    assert engine.last_warnings == [
        "Qwen3-TTS: speed 1.5 is not supported; read at 1.0",
        "Qwen3-TTS: speaker 3 ignored; each voice has one speaker",
    ]


@pytest.mark.parametrize("count", [1, 2, 3, 4, 6])
def test_warnings_and_load_hint_read_like_chatterbox_turbo(count: int) -> None:
    from cloudyreader.engines import chatterbox_turbo as ct

    words = ["troponin", "esophagus", "Okazaki", "ubiquitin", "pharynx", "larynx"][:count]

    def generic(text: str, title: str) -> str:
        return text.replace(title, "<Engine>")

    ours, theirs = qt._hard_word_warning(words), ct._hard_word_warning(words)
    assert generic(ours, qt.TITLE) == generic(theirs, ct.TITLE)  # only the engine name differs
    assert generic(qt.LOAD_HINT, qt.TITLE) == generic(ct.LOAD_HINT, ct.TITLE)
    assert qt.LOAD_HINT == "loading Qwen3-TTS (first use only)"
    expected = {
        3: "Qwen3-TTS cannot take IPA: 3 hard words use the printed spelling "
        "(troponin, esophagus, Okazaki)",
        6: "Qwen3-TTS cannot take IPA: 6 hard words use the printed spelling "
        "(troponin, esophagus, Okazaki and 3 more)",
    }
    if count in expected:
        assert ours == expected[count]


def test_hard_word_warning_equals_script_warning(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    words = ["troponin", "esophagus", "Okazaki", "ubiquitin"]
    overrides = tuple(Override(w, "ˈwɝd", "lexicon") for w in words)
    respelled = Override("Pharynx", "ˈfæɹɪŋks", "respelling", respelling="FAR-ingks")
    segment = Segment(
        "Pharynx, troponin, esophagus, Okazaki and ubiquitin.", 0, (respelled, *overrides)
    )
    script = SpokenScript((segment, Segment("Okazaki fragments.", 0, overrides[2:3])))
    voice = engine.voices()[0]

    engine.synthesize(script, voice, RenderOptions(), tmp_path / "out.wav")
    warning = (
        "Qwen3-TTS cannot take IPA: 4 hard words use the printed spelling "
        "(troponin, esophagus, Okazaki and 1 more)"
    )
    assert engine.last_warnings == [warning]
    assert engine.script_warnings(script, voice) == (warning,)
    assert "far-ingks" in backend.texts[0].lower()  # the respelling is said as written
    assert "troponin" in backend.texts[0]  # printed spelling for IPA-only words

    one = SpokenScript((Segment("Okazaki fragments.", 0, overrides[2:3]),))
    assert engine.script_warnings(one, voice) == (
        "Qwen3-TTS cannot take IPA: 1 hard word uses the printed spelling (Okazaki)",
    )
    lost = SpokenScript((Segment("No such word here.", 0, (respelled,)),))
    assert engine.script_warnings(lost, voice) == (
        "Qwen3-TTS: override for 'Pharynx' not found in the segment text",
    )


def test_a_script_over_the_limit_is_refused(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    text = "word " * (mlxkit.MAX_SCRIPT_CHARS // 5 + 1)
    with pytest.raises(EngineError, match="reads at most"):
        speak(engine, tmp_path / "out.wav", Segment(text))
    assert backend.calls == []


def test_a_wrong_rate_or_bad_samples_from_the_backend(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.rate = 22_050
    with pytest.raises(EngineError, match="22050 Hz, expected 24000 Hz"):
        speak(engine, tmp_path / "out.wav", Segment("Rate check, please, for this voice."))

    bad = np.concatenate([[np.nan, np.inf, -np.inf], np.full(samples(0.5), 0.5)])
    engine.backend = types.SimpleNamespace(  # NaN and inf must not reach the PCM writer
        render=lambda text, voice, *, seed, budget_s: (bad.astype(np.float32), RATE),
        close=lambda: None,
        loaded=True,
    )
    pcm = speak(engine, tmp_path / "nan.wav", Segment("Sanitized samples for this test."))
    assert pcm[:3].tolist() == [0, 32767, -32767]
    assert set(pcm[3:].tolist()) == {16384}


def test_a_segment_without_speakable_text_still_gets_its_pause(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    out = tmp_path / "out.wav"
    audio = engine.synthesize(
        SpokenScript((Segment("", 250),)), engine.voices()[0], RenderOptions(), out
    )
    assert audio.duration_s == pytest.approx(0.25)
    assert runs(read_wav(out)) == [(0, samples(0.25))]
    assert backend.calls == []
    empty = engine.synthesize(SpokenScript(()), engine.voices()[0], RenderOptions(), out)
    assert empty.duration_s == 0


def test_version_and_voice_version_parts(
    settings: Settings, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    pinned = install(settings)
    monkeypatch.setattr(qt.importlib.metadata, "version", lambda name: "0.6.3")
    engine = Qwen3TtsEngine(
        settings, backend, pinned=pinned, assess=lambda: READY, decoder=lambda: PATCH
    )

    assert engine.version == (
        "qwen3-tts-0.6b-customvoice-8bit@01234567+mlx-audio-0.6.3+t0.9k50p1.0r1.05"
        f"+dec-patch+r{qt._RENDER_REVISION}"
    )
    lines = "\n".join(sorted(f"{rel}:{sha(data)}" for rel, data in FILES.items()))
    fp12 = hashlib.sha256(lines.encode()).hexdigest()[:12]
    ryan, aiden = engine.voices()
    assert (engine.voice_version(ryan), engine.voice_version(aiden)) == (
        f"ryan:{fp12}",
        f"aiden:{fp12}",
    )

    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(qt.importlib.metadata, "version", missing)
    bare = Qwen3TtsEngine(
        settings, backend, pinned=Pinned((), ""), assess=lambda: READY, decoder=lambda: PATCH
    )
    assert bare.version.startswith("qwen3-tts-0.6b-customvoice-8bit@norev+mlx-audio-n/a+")
    assert bare.voice_version(ryan) != engine.voice_version(ryan)


@pytest.mark.parametrize("mode", ["upstream", "patch", "blocked"])
def test_version_names_the_decoder_mode(
    mode: str, settings: Settings, backend: FakeBackend
) -> None:
    engine = Qwen3TtsEngine(
        settings,
        backend,
        pinned=install(settings),
        assess=lambda: READY,
        decoder=lambda: DecoderGate(mode, "x"),  # type: ignore[arg-type]
    )
    assert f"+dec-{mode}+" in engine.version
    assert engine.decoder_mode == mode


def test_load_hint_until_the_model_is_resident_and_close(
    engine: Qwen3TtsEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    assert engine.load_hint() == "loading Qwen3-TTS (first use only)"
    speak(engine, tmp_path / "out.wav", Segment("Load me."))
    assert engine.load_hint() is None
    engine.close()
    assert backend.closed is True
    assert engine.load_hint() == "loading Qwen3-TTS (first use only)"


def test_token_cap_is_12_5_per_second_of_budget_clamped() -> None:
    assert token_cap(1.0) == 64
    assert token_cap(5.12) == 64  # not 65: float noise is rounded away
    assert token_cap(8.0) == 100
    assert token_cap(9.81) == 123  # ceil
    assert token_cap(163.84) == 2048
    assert token_cap(300.0) == 2048


# --- backend: fake mlx modules ----------------------------------------------------------------


class FakeResult:
    def __init__(self, audio: np.ndarray) -> None:
        self.audio = audio


class FakeModel:
    sample_rate = RATE

    def __init__(self, *, tokenizer: object = "tokenizer", speech: object = "speech") -> None:
        self.tokenizer = tokenizer
        self.speech_tokenizer = speech
        self.calls: list[dict[str, Any]] = []

    def generate_custom_voice(self, **kwargs: Any):
        self.calls.append(kwargs)
        print("generation noise")  # quiet() must swallow model chatter
        yield FakeResult(np.full(100, 0.5, dtype=np.float32))
        yield FakeResult(np.full(50, -0.5, dtype=np.float32))


def _decoder_class() -> type:
    """A numpy DecoderTransformer: each layer averages the frames its mask allows (default:
    every past frame, like mlx-audio 0.6.3's plain causal mask)."""

    class DecoderTransformer:
        def __init__(self, config: Any) -> None:
            self.config = config
            self.layers = [None] * config.num_hidden_layers

        def __call__(self, inputs_embeds: Any, mask: Any = None, cache: Any = None) -> Any:
            x = np.asarray(inputs_embeds, dtype=np.float64)
            frames = x.shape[1]
            allowed = np.tril(np.ones((frames, frames), bool)) if mask is None else mask
            weights = np.asarray(allowed, dtype=np.float64)
            for _ in self.layers:
                x = np.tanh(x + (weights @ x[0])[None] / weights.sum(axis=1)[None, :, None])
            return x

    return DecoderTransformer


class FakeMlx:
    """Installs fake `mlx.core` and `mlx_audio` modules; records what the backend does."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, model: FakeModel | None = None) -> None:
        self.model = model or FakeModel()
        self.events: list[str] = []
        self.loads: list[tuple[Any, dict[str, Any], str | None]] = []
        self.seeds: list[int] = []
        self.clears = 0
        self.decoder = _decoder_class()

        core = types.ModuleType("mlx.core")
        core.random = SimpleNamespace(seed=self.seeds.append)  # type: ignore[attr-defined]
        core.clear_cache = self._clear  # type: ignore[attr-defined]
        core.array = np.asarray  # type: ignore[attr-defined]
        core.arange = np.arange  # type: ignore[attr-defined]
        core.float32 = np.float32  # type: ignore[attr-defined]
        utils = types.ModuleType("mlx_audio.tts.utils")
        utils.load_model = self._load_model  # type: ignore[attr-defined]
        config = types.ModuleType(qd._CONFIG)
        config.Qwen3TTSTokenizerDecoderConfig = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
        tokenizer = types.ModuleType(qd._TARGET)
        tokenizer.DecoderTransformer = self.decoder  # type: ignore[attr-defined]
        modules = {
            "mlx": types.ModuleType("mlx"),
            "mlx.core": core,
            "mlx_audio": types.ModuleType("mlx_audio"),
            "mlx_audio.tts": types.ModuleType("mlx_audio.tts"),
            "mlx_audio.tts.utils": utils,
            "mlx_audio.tts.models": types.ModuleType("mlx_audio.tts.models"),
            "mlx_audio.tts.models.qwen3_tts": types.ModuleType("mlx_audio.tts.models.qwen3_tts"),
            qd._CONFIG: config,
            qd._TARGET: tokenizer,
        }
        for name, module in modules.items():
            monkeypatch.setitem(sys.modules, name, module)

    def _clear(self) -> None:
        self.clears += 1

    def _load_model(self, model_path: Any, **kwargs: Any) -> FakeModel:
        self.events.append("load")
        self.loads.append((model_path, kwargs, os.environ.get("HF_HUB_OFFLINE")))
        print("loading noise")
        return self.model


def test_backend_passes_a_path_and_loads_under_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeMlx(monkeypatch)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    backend = MlxQwenBackend(tmp_path / "qwen3_tts", slot=ModelSlot(), decoder=lambda: PATCH)
    assert backend.loaded is False

    audio, rate = backend.render("Hello there.", "ryan", seed=7, budget_s=2.0)
    backend.render("Again.", "aiden", seed=8, budget_s=5.0)

    (path, kwargs, offline), *more = fake.loads
    assert more == []  # loaded once
    assert isinstance(path, Path) and path == tmp_path / "qwen3_tts"
    assert kwargs == {"model_type": "qwen3_tts"}
    assert offline == "1"  # loaded under the offline guard
    assert os.environ.get("HF_HUB_OFFLINE") is None  # and the guard restored the environment
    assert rate == RATE
    assert audio.dtype == np.float32
    assert audio.tolist() == [0.5] * 100 + [-0.5] * 50
    assert fake.seeds == [7, 8]
    assert fake.clears == 2  # after every chunk
    assert backend.loaded is True
    assert capsys.readouterr().out == ""  # model prints are swallowed
    assert "torch" not in sys.modules

    with pytest.raises(ValueError, match="unknown Qwen3-TTS voice"):
        backend.render("Hi.", "vivian", seed=1, budget_s=1.0)

    backend.close()
    assert backend.loaded is False
    assert fake.clears == 3


def test_generate_custom_voice_gets_explicit_sampling_and_no_instruct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeMlx(monkeypatch)
    backend = MlxQwenBackend(tmp_path, slot=ModelSlot(), decoder=lambda: PATCH)

    backend.render("Which planet is largest?", "aiden", seed=1, budget_s=9.81)

    assert fake.model.calls == [
        {
            "text": "Which planet is largest?",
            "speaker": "Aiden",
            "language": "english",
            "temperature": 0.9,
            "max_tokens": 123,  # ceil(12.5 x 9.81)
            "top_k": 50,
            "top_p": 1.0,
            "repetition_penalty": 1.05,
            "stream": False,
        }
    ]  # never instruct, ref_audio or ref_text


def test_backend_applies_the_patch_before_load_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeMlx(monkeypatch)
    real_patch, real_probe = qt.apply_decoder_patch, qt.window_probe

    def patch(gate_: DecoderGate) -> None:
        fake.events.append(f"patch:{gate_.mode}")
        real_patch(gate_)

    def probe() -> bool:
        fake.events.append("probe")
        return real_probe()

    monkeypatch.setattr(qt, "apply_decoder_patch", patch)
    monkeypatch.setattr(qt, "window_probe", probe)
    backend = MlxQwenBackend(tmp_path, slot=ModelSlot(), decoder=lambda: PATCH)

    backend.render("Patched first.", "ryan", seed=1, budget_s=2.0)

    assert fake.events == ["patch:patch", "probe", "load"]
    assert getattr(fake.decoder.__call__, "__wrapped__", None) is not None  # the class is banded


def test_backend_runs_the_window_probe_after_apply_and_before_load(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "upstream" skips the patch, but this fake decoder still has the bug: the probe must catch it.
    fake = FakeMlx(monkeypatch)
    upstream = DecoderGate("upstream", "")
    backend = MlxQwenBackend(
        settings.models_dir / "qwen3_tts", slot=ModelSlot(), decoder=lambda: upstream
    )
    engine = Qwen3TtsEngine(
        settings, backend, pinned=install(settings), assess=lambda: READY, decoder=lambda: upstream
    )
    voice = engine.voices()[0]
    script = SpokenScript((Segment("Hello."),))

    with pytest.raises(EngineUnavailable, match=r"decoder window check failed"):
        engine.synthesize(script, voice, RenderOptions(), tmp_path / "a.wav")
    assert fake.loads == []  # the probe ran before load_model, which never ran
    assert backend.loaded is False
    assert engine.available() is False
    assert engine.unavailable_reason == qt.WINDOW_FAILED
    assert engine.unavailable_reason.startswith(WAITING)
    with pytest.raises(EngineUnavailable, match="window check failed"):
        backend.render("Again.", "ryan", seed=2, budget_s=1.0)
    assert fake.loads == []  # sticky


def test_a_probe_that_cannot_build_its_decoder_keeps_it_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeMlx(monkeypatch)
    del sys.modules[qd._CONFIG].Qwen3TTSTokenizerDecoderConfig
    backend = MlxQwenBackend(tmp_path, slot=ModelSlot(), decoder=lambda: PATCH)

    with pytest.raises(EngineUnavailable, match="window check failed"):
        backend.render("Hello.", "ryan", seed=1, budget_s=1.0)
    assert fake.loads == []


@pytest.mark.parametrize(
    ("model", "message"),
    [
        (FakeModel(tokenizer=None), "Qwen3-TTS could not load its tokenizer"),
        (FakeModel(speech=None), "Qwen3-TTS could not load its speech tokenizer"),
    ],
)
def test_tokenizer_or_speech_tokenizer_missing_after_load_makes_it_unavailable(
    model: FakeModel,
    message: str,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeMlx(monkeypatch, model)
    backend = MlxQwenBackend(
        settings.models_dir / "qwen3_tts", slot=ModelSlot(), decoder=lambda: PATCH
    )
    engine = Qwen3TtsEngine(
        settings, backend, pinned=install(settings), assess=lambda: READY, decoder=lambda: PATCH
    )
    voice = engine.voices()[0]
    script = SpokenScript((Segment("Hello."),))

    with pytest.raises(EngineUnavailable, match=message):
        engine.synthesize(script, voice, RenderOptions(), tmp_path / "a.wav")
    assert backend.loaded is False
    assert model.calls == []
    assert engine.available() is False
    assert engine.unavailable_reason == message
    assert [row.reason for row in engine.placeholder_voices()] == [message, message]
    with pytest.raises(EngineUnavailable, match=message):
        engine.synthesize(script, voice, RenderOptions(), tmp_path / "b.wav")
    assert len(fake.loads) == 1


def test_backend_load_errors_become_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeMlx(monkeypatch)

    def broken(model_path: Any, **kwargs: Any) -> FakeModel:
        raise FileNotFoundError("speech_tokenizer/config.json not found")

    sys.modules["mlx_audio.tts.utils"].load_model = broken  # type: ignore[attr-defined]
    backend = MlxQwenBackend(tmp_path, slot=ModelSlot(), decoder=lambda: PATCH)
    with pytest.raises(EngineUnavailable, match="could not load its model: speech_tokenizer"):
        backend.render("Hello.", "ryan", seed=1, budget_s=1.0)
    assert fake.loads == []
    assert backend.refused is None  # a load error is not sticky: the files may be repaired

    monkeypatch.setitem(sys.modules, "mlx_audio.tts.utils", None)  # import fails
    with pytest.raises(EngineUnavailable, match="backend not installed"):
        backend.render("Hello.", "ryan", seed=1, budget_s=1.0)


def test_a_blocked_gate_stops_the_load_before_mlx_is_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "mlx.core", None)  # would raise if the backend got that far
    backend = MlxQwenBackend(tmp_path, slot=ModelSlot(), decoder=lambda: BLOCKED)

    with pytest.raises(EngineUnavailable, match=r"^waiting for a Qwen3 decoder fix"):
        backend.render("Hello.", "ryan", seed=1, budget_s=1.0)


def test_the_slot_evicts_the_resident_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeMlx(monkeypatch)
    slot = ModelSlot(capacity=1)
    backend = MlxQwenBackend(tmp_path, slot=slot, decoder=lambda: PATCH)
    backend.render("First.", "ryan", seed=1, budget_s=1.0)
    other: list[str] = []

    slot.acquire("chatterbox_turbo", lambda: other.append("closed"))  # another engine loads

    assert backend.loaded is False
    backend.render("Second.", "ryan", seed=2, budget_s=1.0)
    assert len(fake.loads) == 2
    assert other == ["closed"]  # and our load evicted it in turn
    backend.close()


# --- real mlx, source tripwire and import weight --------------------------------------------

_REAL_GATE = """
import sys
sys.path.insert(0, sys.argv[1])
try:
    import mlx.core
    import mlx_audio.tts.models.qwen3_tts.speech_tokenizer
except Exception as exc:
    print("SKIP", type(exc).__name__, exc)
    raise SystemExit(0)
from cloudyreader.engines.qwen3_decoder import apply_decoder_patch, decoder_gate, window_probe

before = window_probe()
current = decoder_gate()
apply_decoder_patch(current)
print("RESULT", current.mode, before, window_probe())
"""


@pytest.mark.slow
@pytest.mark.skipif(importlib.util.find_spec("mlx") is None, reason="needs mlx")
@pytest.mark.skipif(importlib.util.find_spec("mlx_audio") is None, reason="needs mlx-audio")
def test_real_gate_patch_and_probe_on_the_installed_mlx_audio() -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-c", _REAL_GATE, str(ROOT)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    lines = result.stdout.splitlines()
    if skip := next((x for x in lines if x.startswith("SKIP ")), None):
        pytest.skip(skip)
    line = next((x for x in lines if x.startswith("RESULT ")), None)
    assert line, result.stdout[-2000:] + result.stderr[-2000:]
    _, mode, before, after = line.split()

    assert mode in ("patch", "upstream")  # the locked mlx-audio is never blocked
    assert after == "True"  # the window holds on the installed class after the gate's action
    if mode == "patch":
        assert before == "False"  # and mlx-audio 0.6.3 as shipped fails the probe


def _qwen_source() -> Path:
    spec = importlib.util.find_spec("mlx_audio")  # a top-level spec executes nothing
    if spec is None or spec.origin is None:
        pytest.skip("mlx-audio is not installed")
    return Path(spec.origin).parent / "tts" / "models" / "qwen3_tts" / "qwen3_tts.py"


def test_mlx_audio_tripwire() -> None:
    source = _qwen_source()
    data = source.read_bytes()
    record = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    assert (record, len(data)) == (RECORD_HASH, RECORD_SIZE), "mlx-audio changed: re-audit it"

    tree = ast.parse(data)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not imported & {"pickle", "torch", "huggingface_hub"}
    assert not [c for c in calls if c.split(".")[-1] in ("snapshot_download", "hf_hub_download")]
    tokenizer_loads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "AutoTokenizer.from_pretrained"
    ]
    assert len(tokenizer_loads) == 1
    assert all(keyword.arg != "trust_remote_code" for keyword in tokenizer_loads[0].keywords)
    # The engine reaches only load_model(Path) and generate_custom_voice: never cloning.
    engine_source = Path(qt.__file__).read_text()
    for name in ("ref_audio", "ref_text", "voice_clone", "voice_design", "from_pretrained"):
        assert name not in engine_source


def test_import_loads_no_mlx_transformers_huggingface_hub_torch() -> None:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import cloudyreader.engines.qwen3_tts as m\n"
        f"assert m.__file__.startswith({str(ROOT)!r}), m.__file__\n"
        "m.supported(); m.gate()\n"
        "heavy = ('mlx', 'mlx_audio', 'transformers', 'huggingface_hub', 'torch')\n"
        "loaded = [name for name in heavy if name in sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
