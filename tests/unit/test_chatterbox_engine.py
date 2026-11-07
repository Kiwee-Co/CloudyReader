"""ChatterboxTurboEngine and MlxChatterboxBackend against fakes; a tripwire on mlx-audio's source.

Real inference cannot run here: the engine runs against FakeBackend, the backend against fake
`mlx.core` and `mlx_audio.tts.utils` modules in sys.modules. Real audio is the owner's smoke run.
The pause contract on a real multiple-choice script is test_chatterbox_pauses.py.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import types
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cloudyreader import engine_catalog
from cloudyreader.config import Settings
from cloudyreader.engine_catalog import Assessment, Pinned, PinnedFile
from cloudyreader.engines import chatterbox_turbo as ct
from cloudyreader.engines import mlxkit
from cloudyreader.engines.chatterbox_turbo import (
    ChatterboxTurboEngine,
    MlxChatterboxBackend,
    gate,
    supported,
    token_cap,
)
from cloudyreader.engines.letter_clips import LetterClips
from cloudyreader.engines.mlxkit import EngineError, EngineUnavailable, ModelSlot
from cloudyreader.models import Override, RenderOptions, Segment, SpokenScript, VoiceInfo
from cloudyreader.normalize import LETTER_PAUSE_MS
from tests.unit.pause_probe import mc_script

ROOT = Path(__file__).resolve().parents[2]
RATE = 24_000
LEVEL = 0.25
PCM_LEVEL = 8192  # rint(0.25 * 32767)
REV = "0123456789abcdef0123456789abcdef01234567"
VOICE_KEY = "chatterbox_turbo:builtin"
# The mlx-audio 0.6.3 RECORD entry of the audited file (blueprint section 0). A bump fails here
# on purpose: re-audit the pickle, torch and download sites, then update both values.
RECORD_HASH = "FWFlfS0cG7BVbrWkzzWNZT9K1FVk4WIzgJIvc-dL37o"
RECORD_SIZE = 49_928
FILES = {
    "config.json": b'{"model_type": "chatterbox_turbo"}',
    "conds.safetensors": b"built-in voice",
    "merges.txt": b"#version: 0.2",
    "model.safetensors": b"quantized weights",
    "tokenizer_config.json": b"{}",
    "vocab.json": b"{}",
}
READY = Assessment("ready", "", 0, True)
BUILTIN = VoiceInfo(
    VOICE_KEY, "chatterbox_turbo", "Chatterbox Turbo (built-in)", "en", "4-bit", 1, True
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def samples(seconds: float) -> int:
    return round(seconds * RATE)


def fake_len(text: str) -> int:
    """Samples FakeBackend returns for `text`: 10 ms per character, never under 0.3 s."""
    return samples(max(0.3, len(text) / 100))


def three_copies() -> np.ndarray:
    """What a model says for "Z. Z. Z.": three 0.3 s copies with 0.2 s of quiet between."""
    tone = np.full(samples(0.3), LEVEL, dtype=np.float32)
    gap = np.zeros(samples(0.2), dtype=np.float32)
    return np.concatenate([tone, gap, tone, gap, tone])


class FakeBackend:
    """A constant tone, 10 ms per character and at least 0.3 s, so it never reads as a failed
    render. `plan[text]` scripts the next calls: seconds of tone, an exception, or samples."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, float]] = []
        self.plan: dict[str, list[float | Exception | np.ndarray]] = {}
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
        return audio.astype(np.float32), self.rate

    def close(self) -> None:
        self.closed = True
        self.loaded = False

    @property
    def texts(self) -> list[str]:
        return [call[0] for call in self.calls]


def install(settings: Settings, files: dict[str, bytes] = FILES) -> Pinned:
    """Write `files` into the engine folder and pin them, the way the startup run leaves them."""
    model_dir = settings.models_dir / "chatterbox_turbo"
    model_dir.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
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
def engine(settings: Settings, backend: FakeBackend) -> ChatterboxTurboEngine:
    pinned = install(settings)
    return ChatterboxTurboEngine(
        settings,
        backend,
        pinned=pinned,
        assess=lambda: READY,
        slot=ModelSlot(capacity=1),
        clips=LetterClips(None),  # every letter reaches the fake model; clip tests bring their own
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
    engine: ChatterboxTurboEngine,
    out: Path,
    *segments: Segment,
    opts: RenderOptions | None = None,
) -> np.ndarray:
    voice = engine.voices()[0]
    audio = engine.synthesize(SpokenScript(tuple(segments)), voice, opts or RenderOptions(), out)
    pcm = read_wav(out)
    assert audio.wav_path == out
    assert audio.sample_rate == RATE
    assert audio.duration_s == pytest.approx(len(pcm) / RATE)
    assert audio.cache_hit is False
    return pcm


# --- voices and availability ----------------------------------------------------------------------


def test_voices_lists_the_builtin_voice(engine: ChatterboxTurboEngine, settings: Settings) -> None:
    assert engine.available() is True
    assert engine.unavailable_reason is None
    assert engine.voices() == [
        VoiceInfo(
            key=VOICE_KEY,
            engine="chatterbox_turbo",
            name="Chatterbox Turbo (built-in)",
            language="en",
            quality="4-bit",
            num_speakers=1,
            installed=True,
            path=settings.models_dir / "chatterbox_turbo",
            reason="",
            precision="4-bit",
        )
    ]
    assert engine.placeholder_voices() == []
    assert engine.key == "chatterbox_turbo"
    assert gate() is None


def lock_with(path: Path, pinned: Pinned) -> Path:
    """An asset lock whose chatterbox_turbo entries are `pinned` (commit-pinned URLs)."""
    assets = [
        {
            "name": Path(pin.rel).name,
            "group": "chatterbox_turbo",
            "url": "https://huggingface.co/mlx-community/chatterbox-turbo-4bit/resolve/"
            f"{REV}/{pin.rel}",
            "sha256": pin.sha256,
            "size": pin.size,
            "dest": ".data/models/chatterbox_turbo",
        }
        for pin in pinned.files
    ]
    path.write_text(json.dumps({"description": "test", "version": 1, "assets": assets}))
    return path


@pytest.mark.parametrize(
    ("case", "expected", "listed"),
    [
        ("platform", "needs an Apple Silicon Mac (arm64)", False),
        ("packages", "backend packages missing: mlx_audio", False),
        ("not pinned", engine_catalog.NOT_PINNED, False),
        ("missing", engine_catalog.NOT_DOWNLOADED, True),
        ("wrong size", "model.safetensors", True),
        ("unpinned safetensors", "extra.safetensors", True),
        ("forbidden suffix", "weights.bin", True),
        ("conds.pt", "conds.pt", True),
    ],
)
def test_unavailable_reasons(
    case: str,
    expected: str,
    listed: bool,
    settings: Settings,
    tmp_path: Path,
    backend: FakeBackend,
) -> None:
    pinned = install(settings)
    model_dir = settings.models_dir / "chatterbox_turbo"
    hard: str | None = None
    if case in ("platform", "packages"):
        hard = expected
    elif case == "not pinned":
        pinned = Pinned((), "")
    elif case == "missing":
        (model_dir / "model.safetensors").unlink()
    elif case == "wrong size":
        (model_dir / "model.safetensors").write_bytes(b"short")
    elif case == "unpinned safetensors":
        (model_dir / "extra.safetensors").write_bytes(b"x")
    elif case == "forbidden suffix":
        (model_dir / "weights.bin").write_bytes(b"x")
    else:
        (model_dir / "conds.pt").write_bytes(b"x")
    lock = lock_with(tmp_path / "assets.lock.json", pinned)

    def assess() -> Assessment:
        return engine_catalog.assess(
            settings,
            "chatterbox_turbo",
            lock_path=lock,
            free_bytes=lambda path: 1 << 40,
            ready=lambda: (hard, None),
        )

    engine = ChatterboxTurboEngine(settings, backend, pinned=pinned, assess=assess)

    assert engine.available() is False
    assert expected in (engine.unavailable_reason or "")
    assert engine.voices() == []
    rows = engine.placeholder_voices()
    if listed:
        assert [row.reason for row in rows] == [engine.unavailable_reason]
    else:  # a hard blocker or an unpinned engine lists nothing
        assert rows == []
    with pytest.raises(EngineUnavailable):
        engine.synthesize(SpokenScript((Segment("Hi."),)), BUILTIN, RenderOptions(), tmp_path / "x")
    assert backend.calls == []


def test_supported_asks_mlx_support_without_importing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, ...], str]] = []

    def support(modules: tuple[str, ...], subpackage: str) -> str | None:
        calls.append((tuple(modules), subpackage))
        return "not in this build"

    monkeypatch.setattr(ct, "mlx_support", support)
    assert supported() == "not in this build"
    assert calls == [
        (("mlx", "mlx_audio", "transformers"), "mlx_audio.tts.models.chatterbox_turbo")
    ]
    assert gate() is None


def test_placeholder_rows_carry_the_reason_and_hard_blockers_list_nothing(
    settings: Settings, backend: FakeBackend
) -> None:
    pinned = install(settings)
    state = {"now": Assessment("missing", "not downloaded yet", 415_000_000, True)}
    engine = ChatterboxTurboEngine(settings, backend, pinned=pinned, assess=lambda: state["now"])

    (row,) = engine.placeholder_voices()
    assert (row.key, row.installed, row.path, row.reason, row.precision) == (
        VOICE_KEY,
        False,
        None,
        "not downloaded yet",
        "4-bit",
    )
    assert engine.voices() == []
    assert engine.available() is False
    assert engine.unavailable_reason == "not downloaded yet"

    state["now"] = Assessment("blocked", "needs an Apple Silicon Mac (arm64)", 0, False)
    assert engine.placeholder_voices() == []
    assert engine.voices() == []

    state["now"] = Assessment("broken", "", 0, True)  # a state without a reason still says why
    assert engine.placeholder_voices()[0].reason == "Chatterbox Turbo is unavailable"


def test_hash_is_checked_before_first_load_and_a_mismatch_is_sticky(
    settings: Settings, backend: FakeBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pinned = install(settings)
    weights = settings.models_dir / "chatterbox_turbo" / "model.safetensors"
    weights.write_bytes(b"QUANTIZED WEIGHTS")  # same size as the pin: only a hash can tell
    verify_calls: list[Path] = []
    original = mlxkit.ModelFiles.verify

    def counting(self: mlxkit.ModelFiles) -> str | None:
        verify_calls.append(self.model_dir)
        return original(self)

    monkeypatch.setattr(mlxkit.ModelFiles, "verify", counting)
    engine = ChatterboxTurboEngine(settings, backend, pinned=pinned, assess=lambda: READY)
    voice = engine.voices()[0]
    script = SpokenScript((Segment("Hello there."),))

    assert engine.available() is True
    assert verify_calls == []  # listing never hashes

    with pytest.raises(
        EngineUnavailable, match=r"^damaged: SHA-256 mismatch for model\.safetensors"
    ):
        engine.synthesize(script, voice, RenderOptions(), tmp_path / "a.wav")
    assert backend.calls == []  # the check runs before the first load
    assert len(verify_calls) == 1
    assert engine.available() is False
    assert engine.unavailable_reason == "damaged: SHA-256 mismatch for model.safetensors"
    (row,) = engine.placeholder_voices()
    assert row.reason == engine.unavailable_reason

    with pytest.raises(EngineUnavailable, match="damaged"):
        engine.synthesize(script, voice, RenderOptions(), tmp_path / "b.wav")
    assert len(verify_calls) == 1  # sticky: no second hash of unchanged files

    weights.unlink()  # gone: the stale mismatch no longer applies, the assessment decides
    assert engine.available() is True
    weights.write_bytes(FILES["model.safetensors"])  # repaired: new mtime, so hash again
    os.utime(weights, ns=(1, 1))
    assert engine.available() is True
    engine.synthesize(script, voice, RenderOptions(), tmp_path / "c.wav")
    assert len(verify_calls) == 2
    engine.synthesize(script, voice, RenderOptions(), tmp_path / "d.wav")
    assert len(verify_calls) == 2  # verified once for this file state
    assert backend.texts == ["Hello there."]  # the second reading was memoized


def test_foreign_or_unknown_voices_are_refused(
    engine: ChatterboxTurboEngine, tmp_path: Path
) -> None:
    script = SpokenScript((Segment("Hello."),))
    kokoro = VoiceInfo("kokoro:af_heart", "kokoro", "Heart", "en-US", "A", 1, True)
    other = VoiceInfo("chatterbox_turbo:clone", "chatterbox_turbo", "x", "en", "4-bit", 1, True)
    for voice in (kokoro, other):
        with pytest.raises(ValueError, match="not a Chatterbox Turbo voice"):
            engine.synthesize(script, voice, RenderOptions(), tmp_path / "x.wav")


# --- synthesis ------------------------------------------------------------------------------------


def test_synthesize_writes_24k_mono_16bit(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    first, second = "Which gas is most abundant in air?", "Nitrogen."
    pcm = speak(engine, tmp_path / "out.wav", Segment(first, 700), Segment(second, 250))

    assert runs(pcm) == [
        (PCM_LEVEL, fake_len(first)),
        (0, samples(0.7)),
        (PCM_LEVEL, fake_len(second)),
        (0, samples(0.25)),
    ]
    assert backend.texts == [first, second]
    assert all(voice == "builtin" for _, voice, _, _ in backend.calls)
    assert engine.last_warnings == []


def test_no_backend_call_ever_holds_the_text_of_two_segments(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    # No pause at all between the first two: still two calls, never "Ox. Yes."
    speak(engine, tmp_path / "a.wav", Segment("Ox.", 0), Segment("Yes.", 250), Segment("No."))
    assert backend.texts == ["Ox.", "Yes.", "No."]

    backend.calls.clear()
    script, _ = mc_script()  # a real multiple-choice script: letters, one-word choices
    engine.synthesize(script, engine.voices()[0], RenderOptions(), tmp_path / "b.wav")
    spoken, _ = engine._prepare(script)
    assert backend.texts
    for text in backend.texts:
        assert any(text in segment for segment in spoken), text
    # Each letter said on its own, by name.
    assert {"double you.", "ecks.", "Why.", "Z."} <= set(backend.texts)


def test_each_choice_letter_reaches_the_model_as_words_for_its_name(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    letters = [Segment(f"{c}.", LETTER_PAUSE_MS) for c in "WXYZ"]
    pcm = speak(engine, tmp_path / "out.wav", *letters, Segment("Answer. W. Pharynx."))

    # Said alone, "W." trailed off into other words and "Y." came out as "yeah" (ASR-checked).
    assert backend.texts == ["double you.", "ecks.", "Why.", "Z.", "Answer. W. Pharynx."]
    pause = (0, samples(LETTER_PAUSE_MS / 1000))
    assert runs(pcm)[:8] == [(PCM_LEVEL, samples(0.3)), pause] * 4  # pauses unchanged


def test_a_segment_split_into_many_chunks_keeps_its_full_trailing_pause(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    stem = " ".join(
        f"Clause {n} of a very long stem names enzymes, membranes and gradients." for n in range(9)
    )
    pcm = speak(engine, tmp_path / "out.wav", Segment(stem, 700), Segment("Z.", 300))

    chunks = backend.texts[:-1]
    assert len(chunks) >= 3 and backend.texts[-1] == "Z."
    expected: list[tuple[int, int]] = []
    for index, chunk in enumerate(chunks):
        if index:
            expected.append((0, samples(0.12)))  # INTER_CHUNK_MS, only between its own chunks
        expected.append((PCM_LEVEL, fake_len(chunk)))
    expected += [(0, samples(0.7)), (PCM_LEVEL, fake_len("Z.")), (0, samples(0.3))]
    assert runs(pcm) == expected  # the whole 700 ms after the last chunk, then the letter


def test_a_short_unit_falls_back_to_repeat_and_crop(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.plan["Z."] = [RuntimeError("too short"), 5.0]  # a crash, then a runaway take
    backend.plan["Z. Z. Z."] = [three_copies()]
    pcm = speak(engine, tmp_path / "out.wav", Segment("Z.", 300), Segment("Nitrogen"))

    seeds = [mlxkit.seed_for(VOICE_KEY, "Z.", attempt) for attempt in range(3)]
    assert [(text, seed) for text, _, seed, _ in backend.calls[:3]] == [
        ("Z.", seeds[0]),
        ("Z.", seeds[1]),
        ("Z. Z. Z.", seeds[2]),
    ]
    # The first copy, cut in the middle of the first quiet gap; then the letter's own pause.
    assert runs(pcm) == [
        (PCM_LEVEL, samples(0.3)),
        (0, samples(0.1) + samples(0.3)),
        (PCM_LEVEL, fake_len("Nitrogen")),
    ]
    assert engine.last_warnings == []


def test_a_unit_the_model_cannot_say_names_it(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.plan["Z."] = [RuntimeError("boom")] * 2
    backend.plan["Z. Z. Z."] = [RuntimeError("boom")]
    with pytest.raises(EngineError, match=r"^Chatterbox Turbo could not say 'Z\.'; try another"):
        speak(engine, tmp_path / "out.wav", Segment("Z."))
    assert backend.texts == ["Z.", "Z.", "Z. Z. Z."]


def test_a_chunk_that_keeps_running_away_raises(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    text = "Mitochondria make most of the energy a cell uses."
    backend.plan[text] = [60.0, 60.0, 60.0]
    with pytest.raises(EngineError, match="^Chatterbox Turbo could not say 'Mitochondria"):
        speak(engine, tmp_path / "out.wav", Segment(text))
    seeds = [seed for _, _, seed, _ in backend.calls]
    assert seeds == [mlxkit.seed_for(VOICE_KEY, text, n) for n in range(3)]  # never repeated

    backend.calls.clear()
    backend.plan[text] = [60.0]  # the second seed reads it properly
    pcm = speak(engine, tmp_path / "ok.wav", Segment(text))
    assert len(backend.calls) == 2
    assert runs(pcm) == [(PCM_LEVEL, fake_len(text))]


def test_a_load_failure_is_not_retried(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.plan["Z."] = [EngineUnavailable("Chatterbox Turbo could not load its tokenizer")]
    with pytest.raises(EngineUnavailable, match="tokenizer"):
        speak(engine, tmp_path / "out.wav", Segment("Z."))
    assert backend.texts == ["Z."]


def test_short_units_are_memoized_until_close(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    long = "Photosynthesis turns light into chemical energy in the chloroplasts of plant cells."
    backend.plan[long] = [4.0, 4.0]  # over 3 s of audio: rendered every time
    segments = (Segment("W.", 300), Segment("X.", 300), Segment("W.", 300), Segment(long))

    first = speak(engine, tmp_path / "a.wav", *segments)
    second = speak(engine, tmp_path / "b.wav", *segments)

    assert backend.texts == ["double you.", "ecks.", long, long]
    assert np.array_equal(first, second)
    engine.close()
    speak(engine, tmp_path / "c.wav", Segment("W."))
    assert backend.texts.count("double you.") == 2  # close() drops the memo with the model


def test_long_text_is_chunked_in_order(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    sentences = [
        f"Sentence number {n} talks about cells, enzymes, and the energy they need to divide."
        for n in range(1, 15)
    ]
    text = " ".join(sentences)
    assert len(text) > 1000
    pcm = speak(engine, tmp_path / "out.wav", Segment(text, 400))

    chunks = backend.texts
    assert len(chunks) >= 4
    assert all(len(chunk) <= 280 for chunk in chunks)
    assert " ".join(chunks).split() == text.split()  # every word, in order
    expected: list[tuple[int, int]] = []
    for index, chunk in enumerate(chunks):
        if index:
            expected.append((0, samples(0.12)))  # INTER_CHUNK_MS between chunks of one segment
        expected.append((PCM_LEVEL, fake_len(chunk)))
    expected.append((0, samples(0.4)))
    assert runs(pcm) == expected


def test_brackets_are_stripped_and_warned_once(
    engine: ChatterboxTurboEngine,
    backend: FakeBackend,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger=ct.__name__):
        pcm = speak(
            engine,
            tmp_path / "out.wav",
            Segment("The [laugh] cue is not a sound here.", 300),
            Segment("[H+] ions make a solution acidic."),
            Segment("[ ]", 200),  # nothing left to say: the pause stays
        )

    assert backend.texts == [
        "The laugh cue is not a sound here.",
        "H+ ions make a solution acidic.",
    ]
    assert engine.last_warnings == [ct.BRACKET_WARNING]
    assert [r.getMessage() for r in caplog.records] == [ct.BRACKET_WARNING]  # logged once
    assert runs(pcm)[-1] == (0, samples(0.2))


def test_speed_and_speaker_are_reported_not_applied(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    text = "Speed and speaker are fixed."
    plain = speak(engine, tmp_path / "a.wav", Segment(text))
    assert engine.last_warnings == []

    changed = speak(
        engine, tmp_path / "b.wav", Segment(text), opts=RenderOptions(speed=1.5, speaker_id=3)
    )

    assert np.array_equal(plain, changed)
    assert engine.last_warnings == [
        "Chatterbox Turbo: speed 1.5 is not supported; read at 1.0",
        "Chatterbox Turbo: speaker 3 ignored; it has one voice",
    ]


def test_hard_word_warning_equals_script_warning(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
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
        "Chatterbox Turbo cannot take IPA: 4 hard words use the printed spelling "
        "(troponin, esophagus, Okazaki and 1 more)"
    )
    assert engine.last_warnings == [warning]
    assert engine.script_warnings(script, voice) == (warning,)
    assert "far-ingks" in backend.texts[0].lower()  # the respelling is said as written
    assert "troponin" in backend.texts[0]  # printed spelling for IPA-only words

    one = SpokenScript((Segment("Okazaki fragments.", 0, overrides[2:3]),))
    assert engine.script_warnings(one, voice) == (
        "Chatterbox Turbo cannot take IPA: 1 hard word uses the printed spelling (Okazaki)",
    )
    lost = SpokenScript((Segment("No such word here.", 0, (respelled,)),))
    assert engine.script_warnings(lost, voice) == (
        "Chatterbox Turbo: override for 'Pharynx' not found in the segment text",
    )


def test_a_script_over_the_limit_is_refused(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    text = "word " * (mlxkit.MAX_SCRIPT_CHARS // 5 + 1)
    with pytest.raises(EngineError, match="reads at most"):
        speak(engine, tmp_path / "out.wav", Segment(text))
    assert backend.calls == []


def test_a_backend_rate_other_than_24k_is_an_error(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.rate = 22_050
    with pytest.raises(EngineError, match="22050 Hz, expected 24000 Hz"):
        speak(engine, tmp_path / "out.wav", Segment("Rate check, please."))


def test_an_empty_script_writes_an_empty_wav(engine: ChatterboxTurboEngine, tmp_path: Path) -> None:
    out = tmp_path / "out.wav"
    audio = engine.synthesize(SpokenScript(()), engine.voices()[0], RenderOptions(), out)
    assert audio.duration_s == 0
    assert read_wav(out).size == 0


def test_version_and_voice_version_parts(
    settings: Settings, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    pinned = install(settings)
    monkeypatch.setattr(ct.importlib.metadata, "version", lambda name: "0.6.3")
    engine = ChatterboxTurboEngine(settings, backend, pinned=pinned, assess=lambda: READY)

    tail = f"+mlx-audio-0.6.3+t0.8k1000p0.95r1.2+r{ct._RENDER_REVISION}"
    assert engine.version == f"chatterbox-turbo-4bit@01234567{tail}"
    lines = "\n".join(sorted(f"{rel}:{sha(data)}" for rel, data in FILES.items()))
    fp12 = hashlib.sha256(lines.encode()).hexdigest()[:12]
    assert engine.voice_version(engine.voices()[0]) == f"builtin:{fp12}"

    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(ct.importlib.metadata, "version", missing)
    bare = ChatterboxTurboEngine(settings, backend, pinned=Pinned((), ""), assess=lambda: READY)
    assert bare.version.startswith("chatterbox-turbo-4bit@norev+mlx-audio-n/a+")
    assert bare.voice_version(BUILTIN) != engine.voice_version(BUILTIN)


def test_load_hint_until_the_model_is_resident_and_close(
    engine: ChatterboxTurboEngine, backend: FakeBackend, tmp_path: Path
) -> None:
    assert engine.load_hint() == "loading Chatterbox Turbo (first use only)"
    speak(engine, tmp_path / "out.wav", Segment("Load me."))
    assert engine.load_hint() is None
    engine.close()
    assert backend.closed is True
    assert engine.load_hint() == "loading Chatterbox Turbo (first use only)"


def test_token_cap_is_the_budget_at_25_tokens_a_second_clamped() -> None:
    assert token_cap(2.0) == 100  # render_text's floor budget: 50 tokens, raised to 100
    assert token_cap(4.9) == 123  # ceil
    assert token_cap(9.88) == 247  # not 248 from 247.00000000000003
    assert token_cap(10.0) == 250
    assert token_cap(32.0) == 800
    assert token_cap(40.0) == 800


# --- backend: fake mlx modules ----------------------------------------------------------------


class FakeResult:
    def __init__(self, audio: np.ndarray) -> None:
        self.audio = audio


class FakeModel:
    sample_rate = RATE

    def __init__(self, *, tokenizer: object = "tokenizer", conds: object = "conds") -> None:
        self.tokenizer = tokenizer
        self._conds = conds
        self.generate_calls: list[tuple[str, dict[str, Any]]] = []

    def generate(self, text: str, **kwargs: Any):
        self.generate_calls.append((text, kwargs))
        print("tqdm-like noise")  # quiet() must swallow model chatter
        yield FakeResult(np.full(100, 0.5, dtype=np.float32))
        yield FakeResult(np.full(50, -0.5, dtype=np.float32))


def _unreachable_download(**kwargs: Any) -> str:
    raise AssertionError("the offline guard must replace this before the model code runs")


class FakeMlx:
    """Installs fake `mlx.core` and `mlx_audio.tts.utils`; records what the backend does."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, model: FakeModel | None = None) -> None:
        self.model = model or FakeModel()
        self.loads: list[tuple[Any, dict[str, Any], dict[str, str | None]]] = []
        self.seeds: list[int] = []
        self.clears = 0
        self.s3_error: BaseException | None = None
        self.hub_during_load: Any = None

        core = types.ModuleType("mlx.core")
        core.random = types.SimpleNamespace(seed=self.seeds.append)  # type: ignore[attr-defined]
        core.clear_cache = self._clear  # type: ignore[attr-defined]
        mlx = types.ModuleType("mlx")
        mlx.core = core  # type: ignore[attr-defined]
        utils = types.ModuleType("mlx_audio.tts.utils")
        utils.load_model = self._load_model  # type: ignore[attr-defined]
        tts = types.ModuleType("mlx_audio.tts")
        tts.utils = utils  # type: ignore[attr-defined]
        package = types.ModuleType("mlx_audio")
        package.tts = tts  # type: ignore[attr-defined]
        # The real huggingface_hub comes with the kokoro extra, which CI does not install.
        self.hub = types.ModuleType("huggingface_hub")
        self.hub.hf_hub_download = _unreachable_download  # type: ignore[attr-defined]
        self.hub.snapshot_download = _unreachable_download  # type: ignore[attr-defined]
        for name, module in {
            "mlx": mlx,
            "mlx.core": core,
            "mlx_audio": package,
            "mlx_audio.tts": tts,
            "mlx_audio.tts.utils": utils,
            "huggingface_hub": self.hub,
        }.items():
            monkeypatch.setitem(sys.modules, name, module)

    def _clear(self) -> None:
        self.clears += 1

    def _load_model(self, model_path: Any, **kwargs: Any) -> FakeModel:
        env = {name: os.environ.get(name) for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}
        self.loads.append((model_path, kwargs, env))
        print("loading noise")
        # What post_load_hook does for the S3 tokenizer: try the Hub, log and go on.
        self.hub_during_load = self.hub.hf_hub_download
        try:
            self.hub.hf_hub_download(
                repo_id="mlx-community/S3TokenizerV2", filename="model.safetensors"
            )
        except Exception as exc:  # noqa: BLE001 - mirrors the upstream catch-all
            self.s3_error = exc
        return self.model


def test_backend_passes_a_path_and_loads_under_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeMlx(monkeypatch)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    backend = MlxChatterboxBackend(tmp_path / "chatterbox_turbo", slot=ModelSlot(capacity=1))
    assert backend.loaded is False

    audio, rate = backend.render("Hello there.", "builtin", seed=7, budget_s=2.0)
    backend.render("Again.", "builtin", seed=8, budget_s=5.0)

    (path, kwargs, env), *more = fake.loads
    assert more == []  # loaded once
    assert isinstance(path, Path) and path == tmp_path / "chatterbox_turbo"
    assert kwargs == {"model_type": "chatterbox_turbo"}
    assert env["HF_HUB_OFFLINE"] == "1"  # loaded under the offline guard
    assert os.environ.get("HF_HUB_OFFLINE") is None  # and the guard restored the environment
    assert rate == RATE
    assert audio.dtype == np.float32
    assert audio.tolist() == [0.5] * 100 + [-0.5] * 50
    assert fake.seeds == [7, 8]
    assert fake.clears == 2  # after every chunk
    assert backend.loaded is True
    assert capsys.readouterr().out == ""  # model prints and tqdm bars are swallowed

    with pytest.raises(ValueError, match="unknown Chatterbox Turbo voice"):
        backend.render("Hi.", "clone", seed=1, budget_s=2.0)

    backend.close()
    assert backend.loaded is False
    assert fake.clears == 3


def test_generate_gets_one_chunk_split_pattern_none_and_no_ref_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeMlx(monkeypatch)
    backend = MlxChatterboxBackend(tmp_path, slot=ModelSlot(capacity=1))
    text = "Chunks arrive one at a time. The engine splits them, never mlx-audio."

    backend.render(text, "builtin", seed=1, budget_s=4.9)

    ((sent, kwargs),) = fake.model.generate_calls
    assert sent == text
    assert kwargs == {
        "temperature": 0.8,
        "top_k": 1000,
        "top_p": 0.95,
        "repetition_penalty": 1.2,
        "max_tokens": 123,  # ceil(25 x 4.9)
        "split_pattern": None,
        "stream": False,
    }
    assert "ref_audio" not in kwargs  # never voice cloning


def test_s3_tokenizer_download_is_blocked_and_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def real_download(**kwargs: Any) -> str:  # stands in for the network
        calls.append(kwargs)
        return str(tmp_path / "model.safetensors")

    fake = FakeMlx(monkeypatch)
    monkeypatch.setattr(fake.hub, "hf_hub_download", real_download)
    backend = MlxChatterboxBackend(tmp_path, slot=ModelSlot(capacity=1))

    audio, _ = backend.render("Blocked, then ignored.", "builtin", seed=3, budget_s=2.0)

    assert calls == []  # the Hub was never asked
    assert isinstance(fake.s3_error, EngineUnavailable)  # the guard's stub raised in the load
    assert fake.hub_during_load is not real_download
    assert fake.hub.hf_hub_download is real_download  # restored after the load
    assert audio.size == 150  # and the voice still speaks


@pytest.mark.parametrize(
    ("model", "message"),
    [
        (FakeModel(tokenizer=None), "could not load its tokenizer"),
        (FakeModel(conds=None), "could not load its built-in voice"),
    ],
)
def test_backend_refuses_a_half_loaded_model(
    model: FakeModel, message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeMlx(monkeypatch, model)
    backend = MlxChatterboxBackend(tmp_path, slot=ModelSlot(capacity=1))

    with pytest.raises(EngineUnavailable, match=message):
        backend.render("Hello.", "builtin", seed=1, budget_s=2.0)
    assert backend.loaded is False
    assert model.generate_calls == []


def test_backend_load_errors_become_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeMlx(monkeypatch)

    def broken(model_path: Any, **kwargs: Any) -> FakeModel:
        raise FileNotFoundError("conds.safetensors not found")

    sys.modules["mlx_audio.tts.utils"].load_model = broken  # type: ignore[attr-defined]
    backend = MlxChatterboxBackend(tmp_path, slot=ModelSlot(capacity=1))
    with pytest.raises(EngineUnavailable, match="could not load its model: conds.safetensors"):
        backend.render("Hello.", "builtin", seed=1, budget_s=2.0)
    assert fake.loads == []

    monkeypatch.setitem(sys.modules, "mlx_audio.tts.utils", None)  # import fails
    with pytest.raises(EngineUnavailable, match="backend not installed"):
        backend.render("Hello.", "builtin", seed=1, budget_s=2.0)


def test_the_slot_evicts_the_resident_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeMlx(monkeypatch)
    slot = ModelSlot(capacity=1)
    backend = MlxChatterboxBackend(tmp_path, slot=slot)
    backend.render("First.", "builtin", seed=1, budget_s=2.0)
    other: list[str] = []

    slot.acquire("qwen3_tts", lambda: other.append("closed"))  # another engine loads

    assert backend.loaded is False
    backend.render("Second.", "builtin", seed=2, budget_s=2.0)
    assert len(fake.loads) == 2
    assert other == ["closed"]  # and our load evicted it in turn
    backend.close()


def test_a_load_another_thread_finished_is_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeMlx(monkeypatch)

    class RacingSlot(ModelSlot):
        def __enter__(self) -> ModelSlot:  # the other thread loaded while we waited
            backend._model, backend._mx = fake.model, sys.modules["mlx.core"]
            return super().__enter__()

    backend = MlxChatterboxBackend(tmp_path, slot=RacingSlot(capacity=1))
    audio, _ = backend.render("Raced.", "builtin", seed=1, budget_s=2.0)

    assert fake.loads == []
    assert audio.size == 150


# --- source tripwire and import weight ------------------------------------------------------


def _chatterbox_source() -> Path:
    spec = importlib.util.find_spec("mlx_audio")  # a top-level spec executes nothing
    if spec is None or spec.origin is None:
        pytest.skip("mlx-audio is not installed")
    return Path(spec.origin).parent / "tts" / "models" / "chatterbox_turbo" / "chatterbox_turbo.py"


def _risky_sites(tree: ast.Module) -> set[tuple[str, str]]:
    """(enclosing function, construct) for every pickle, torch or Hub download site.

    A static scan of mlx-audio's source text: nothing here imports or loads pickle or torch."""
    sites: set[tuple[str, str]] = set()

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                inner = f"{scope}.{child.name}" if scope else child.name
            if isinstance(child, ast.Import):
                for alias in child.names:
                    if alias.name.split(".")[0] in ("pickle", "torch", "huggingface_hub"):
                        sites.add((inner, f"import {alias.name}"))
            elif isinstance(child, ast.ImportFrom) and child.module:
                if child.module.split(".")[0] in ("pickle", "torch", "huggingface_hub"):
                    names = ",".join(alias.name for alias in child.names)
                    sites.add((inner, f"from {child.module} import {names}"))
            elif isinstance(child, ast.Call):
                name = ast.unparse(child.func)
                if name.split(".")[-1] in ("snapshot_download", "hf_hub_download") or name in (
                    "pickle.load",
                    "pickle.loads",
                    "torch.load",
                ):
                    sites.add((inner, f"call {name}"))
            visit(child, inner)

    visit(tree, "")
    return sites


def test_mlx_audio_tripwire() -> None:
    source = _chatterbox_source()
    data = source.read_bytes()
    record = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    assert (record, len(data)) == (RECORD_HASH, RECORD_SIZE), "mlx-audio changed: re-audit it"

    tree = ast.parse(data)
    assert _risky_sites(tree) == {
        ("Conditionals.save", "import pickle"),
        ("Conditionals.load", "import pickle"),
        ("Conditionals.load", "call pickle.load"),
        ("ChatterboxTurboTTS.post_load_hook", "from huggingface_hub import hf_hub_download"),
        ("ChatterboxTurboTTS.post_load_hook", "call hf_hub_download"),
        ("ChatterboxTurboTTS.from_local", "import torch"),
        ("ChatterboxTurboTTS.from_local", "call torch.load"),
        ("ChatterboxTurboTTS.from_pretrained", "from huggingface_hub import snapshot_download"),
        ("ChatterboxTurboTTS.from_pretrained", "call snapshot_download"),
    }
    tokenizer_loads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "AutoTokenizer.from_pretrained"
    ]
    assert len(tokenizer_loads) == 2
    assert all(
        keyword.arg != "trust_remote_code" for node in tokenizer_loads for keyword in node.keywords
    )
    # The engine reaches only load_model(Path) and generate: never the pickle or torch loaders.
    engine_source = Path(ct.__file__).read_text()
    for name in ("from_local", "from_pretrained", "Conditionals", "prepare_conditionals"):
        assert name not in engine_source


def test_import_loads_no_mlx_transformers_huggingface_hub_torch() -> None:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import cloudyreader.engines.chatterbox_turbo as m\n"
        f"assert m.__file__.startswith({str(ROOT)!r}), m.__file__\n"
        "heavy = ('mlx', 'mlx_audio', 'transformers', 'huggingface_hub', 'torch')\n"
        "loaded = [name for name in heavy if name in sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, cwd=ROOT
    )
    assert result.returncode == 0, result.stderr
