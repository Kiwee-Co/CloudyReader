"""KokoroEngine: render, voices, availability, WAV output (fake backend), real model (lean venv)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from cloudyreader.engines import kokoro
from cloudyreader.engines.kokoro import (
    RECOMMENDED_VOICES,
    SAMPLE_RATE,
    InProcessBackend,
    KokoroEngine,
    KokoroError,
    KokoroUnavailable,
)
from cloudyreader.models import Override, RenderOptions, Segment, SpokenScript, VoiceInfo

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = Path(
    os.environ.get(
        "CLOUDYREADER_KOKORO_SNAPSHOT",
        ROOT
        / ".cache/spike-kokoro/hf/hub/models--mlx-community--Kokoro-82M-bf16/snapshots"
        / "a71e4d38b236d968966a2002c4c895dbd12b1c3c",
    )
)
# Same torch-free set as the `kokoro` extra: spaCy 3.7.5, numpy 1.26.4, en_core_web_sm 3.7.1.
KOKORO_PYTHON = Path(
    os.environ.get(
        "CLOUDYREADER_KOKORO_PYTHON", ROOT / ".cache/spike-kokoro/.venv-lean37/bin/python"
    )
)
PHARYNX = Override("Pharynx", "ˈfæɹɪŋks", "respelling")


class FakeBackend:
    """10 ms of constant audio per input character, so durations are exact."""

    def __init__(self, rate: int = SAMPLE_RATE, level: float = 0.25) -> None:
        self.calls: list[tuple[str, str, float]] = []
        self.rate = rate
        self.level = level
        self.closed = False
        self.last_skipped: list[str] = []

    def synthesize_line(self, text: str, voice: str, speed: float) -> tuple[np.ndarray, int]:
        self.calls.append((text, voice, speed))
        return np.full(len(text) * self.rate // 100, self.level, dtype=np.float32), self.rate

    def close(self) -> None:
        self.closed = True


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def models_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tiny fake snapshot whose SHA256 pins replace the real ones."""
    snap = tmp_path / "models" / "kokoro"
    (snap / "voices").mkdir(parents=True)
    files = {"config.json": b'{"vocab": {}}', "kokoro-v1_0.safetensors": b"weights"}
    for rel, data in files.items():
        (snap / rel).write_bytes(data)
    voices = {}
    for vid in ("af_heart", "bf_emma", "am_adam"):
        data = f"voice {vid}".encode()
        (snap / "voices" / f"{vid}.safetensors").write_bytes(data)
        voices[vid] = _sha(data)
    monkeypatch.setattr(kokoro, "MODEL_SHA256", {rel: _sha(d) for rel, d in files.items()})
    monkeypatch.setattr(kokoro, "VOICE_SHA256", {**kokoro.VOICE_SHA256, **voices})
    monkeypatch.setattr(kokoro, "_supported_platform", lambda: True)
    return tmp_path / "models"


@pytest.fixture
def engine(models_dir: Path) -> KokoroEngine:
    return KokoroEngine(models_dir, FakeBackend())


def _voice(engine: KokoroEngine, vid: str = "af_heart") -> VoiceInfo:
    return next(v for v in engine.voices() if v.key == f"kokoro:{vid}")


def _read_wav(path: Path) -> tuple[list[int], np.ndarray]:
    with wave.open(str(path)) as w:
        fmt = [w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()]
        return fmt, np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


# --- render -----------------------------------------------------------------------------------


def test_override_survives_to_misaki_markup(engine: KokoroEngine) -> None:
    # Regression: an Override must reach Kokoro as [surface](/misaki/), mapped from IPA.
    seg = Segment("W. Pharynx.", 400, (PHARYNX,))
    assert engine.render(seg, _voice(engine)) == "W. [Pharynx](/fˈæɹɪŋks/)."


def test_render_without_overrides_returns_text(engine: KokoroEngine) -> None:
    assert engine.render(Segment("Earth Science."), _voice(engine)) == "Earth Science."


def test_render_longest_surface_first_and_whole_words(engine: KokoroEngine) -> None:
    seg = Segment(
        "Sodium chloride, chloride ions, and laryngitis; Larynx.",
        overrides=(
            Override("chloride", "ˈklɔɹaɪd", "lexicon"),
            Override("Sodium chloride", "ˈsoʊdiəm ˈklɔɹaɪd", "lexicon"),
            Override("Larynx", "ˈlæɹɪŋks", "respelling"),
        ),
    )
    assert engine.render(seg, _voice(engine)) == (
        "[Sodium chloride](/sˈOdiəm klˈɔɹId/), [chloride](/klˈɔɹId/) ions, and laryngitis; "
        "[Larynx](/lˈæɹɪŋks/)."
    )
    assert engine.last_warnings == []


def test_render_unglues_a_mass_number_from_the_markup(engine: KokoroEngine) -> None:
    # Regression: spaCy keeps "Strontium-90" one token, so misaki shifted later overrides.
    seg = Segment(
        "Strontium-90 and glucose-6-phosphate; Potassium-argon dating.",
        overrides=(
            Override("Strontium", "ˈstɹɑnʃiəm", "lexicon"),
            Override("glucose", "ˈɡlukoʊs", "lexicon"),
            Override("phosphate", "ˈfɑsfeɪt", "lexicon"),
            Override("Potassium", "pəˈtæsiəm", "lexicon"),
        ),
    )
    assert engine.render(seg, _voice(engine)) == (
        "[Strontium](/stɹˈɑnʃiəm/) 90 and [glucose](/ɡlˈukOs/) 6-[phosphate](/fˈɑsfAt/); "
        "[Potassium](/pətˈæsiəm/)-argon dating."
    )


def test_render_drops_rejected_symbols_with_warning(engine: KokoroEngine) -> None:
    seg = Segment("Pharynx", overrides=(Override("Pharynx", "ˈfæɹ-ɪŋks", "respelling"),))
    assert engine.render(seg, _voice(engine)) == "[Pharynx](/fˈæɹɪŋks/)"
    assert len(engine.last_warnings) == 1 and "'-'" in engine.last_warnings[0]


def test_render_speaks_surface_plain_when_nothing_maps(engine: KokoroEngine) -> None:
    seg = Segment("Pharynx", overrides=(Override("Pharynx", "--", "respelling"),))
    assert engine.render(seg, _voice(engine)) == "Pharynx"
    assert any("no usable phonemes" in w for w in engine.last_warnings)


def test_render_warns_when_surface_missing(engine: KokoroEngine) -> None:
    seg = Segment("Larynx.", overrides=(PHARYNX,))
    assert engine.render(seg, _voice(engine)) == "Larynx."
    assert any("not found" in w for w in engine.last_warnings)


def test_render_rejects_bracketed_surface(engine: KokoroEngine) -> None:
    seg = Segment("[H+] ions", overrides=(Override("[H+]", "eɪtʃ", "lexicon"),))
    assert engine.render(seg, _voice(engine)) == "[H+] ions"
    assert any("bracket" in w for w in engine.last_warnings)


def test_render_neutralizes_link_syntax_in_plain_text(engine: KokoroEngine) -> None:
    # misaki would read "[H+](aq)" as markup and silently drop "(aq)".
    assert engine.render(Segment("[H+](aq) forms"), _voice(engine)) == "[H+] (aq) forms"


# --- voices -----------------------------------------------------------------------------------


def test_voices_lists_recommended_first(engine: KokoroEngine) -> None:
    voices = engine.voices()
    assert [v.key for v in voices] == [f"kokoro:{v}" for v in RECOMMENDED_VOICES]
    assert RECOMMENDED_VOICES == (
        "af_heart",
        "af_bella",
        "bf_emma",
        "am_michael",
        "am_fenrir",
        "am_puck",
    )
    heart, emma = voices[0], voices[2]
    assert (heart.engine, heart.language, heart.quality, heart.num_speakers) == (
        "kokoro",
        "en-US",
        "A",
        1,
    )
    assert heart.installed and heart.path is not None and heart.path.name == "af_heart.safetensors"
    assert emma.language == "en-GB" and emma.installed
    assert not voices[1].installed and voices[1].path is None  # af_bella file not in fake snapshot


def test_voices_all_voices_flag(models_dir: Path) -> None:
    keys = [v.key for v in KokoroEngine(models_dir, FakeBackend(), all_voices=True).voices()]
    assert keys[:6] == [f"kokoro:{v}" for v in RECOMMENDED_VOICES]
    assert len(keys) == 28 and len(set(keys)) == 28 and "kokoro:am_adam" in keys


def test_every_voice_names_the_bf16_weights_and_keeps_its_grade(models_dir: Path) -> None:
    voices = KokoroEngine(models_dir, FakeBackend(), all_voices=True).voices()

    assert {v.precision for v in voices} == {"bf16"}  # KOKORO_REPO is Kokoro-82M-bf16
    assert next(v for v in voices if v.key == "kokoro:af_heart").quality == "A"  # the rank's input


def test_voices_empty_off_apple_silicon(engine: KokoroEngine, monkeypatch) -> None:
    monkeypatch.setattr(kokoro, "_supported_platform", lambda: False)
    assert engine.voices() == []


# --- available ----------------------------------------------------------------------------------


def test_available_with_verified_snapshot(engine: KokoroEngine) -> None:
    assert engine.available() and engine.unavailable_reason is None


def test_unavailable_off_apple_silicon(engine: KokoroEngine, monkeypatch) -> None:
    monkeypatch.setattr(kokoro, "_supported_platform", lambda: False)
    assert not engine.available()
    assert "Apple Silicon" in (engine.unavailable_reason or "")


def test_unavailable_when_weights_hash_differs(models_dir: Path) -> None:
    (models_dir / "kokoro" / "kokoro-v1_0.safetensors").write_bytes(b"tampered")
    eng = KokoroEngine(models_dir, FakeBackend())
    assert not eng.available()
    assert "SHA256 mismatch" in (eng.unavailable_reason or "")


def test_unavailable_when_snapshot_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(kokoro, "_supported_platform", lambda: True)
    eng = KokoroEngine(tmp_path, FakeBackend())
    assert not eng.available()
    assert "missing" in (eng.unavailable_reason or "")


def test_unavailable_when_backend_packages_missing(models_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(kokoro, "BACKEND_MODULES", ("cloudyreader_no_such_module_xyz",))
    eng = KokoroEngine(models_dir)  # default in-process backend
    assert isinstance(eng.backend, InProcessBackend)
    assert not eng.available()
    assert "cloudyreader_no_such_module_xyz" in (eng.unavailable_reason or "")


def test_hash_checked_once_per_file(engine: KokoroEngine, models_dir: Path) -> None:
    assert engine.available()
    (models_dir / "kokoro" / "kokoro-v1_0.safetensors").write_bytes(b"changed later")
    assert engine.available()  # verified files are cached for the process lifetime


# --- synthesize ---------------------------------------------------------------------------------


def test_synthesize_writes_wav_with_pauses(engine: KokoroEngine, tmp_path: Path) -> None:
    script = SpokenScript((Segment("Life Science.", 300), Segment("W. Pharynx.", 0, (PHARYNX,))))
    out = tmp_path / "out" / "q.wav"
    audio = engine.synthesize(script, _voice(engine), RenderOptions(speed=1.25), out)
    backend = engine.backend
    assert isinstance(backend, FakeBackend)
    assert backend.calls == [
        ("Life Science.", "af_heart", 1.25),
        ("W. [Pharynx](/fˈæɹɪŋks/).", "af_heart", 1.25),
    ]
    first = len("Life Science.") * SAMPLE_RATE // 100
    second = len("W. [Pharynx](/fˈæɹɪŋks/).") * SAMPLE_RATE // 100
    pause = SAMPLE_RATE * 300 // 1000
    fmt, pcm = _read_wav(out)
    assert fmt == [24000, 1, 2, first + pause + second]
    assert (audio.wav_path, audio.sample_rate, audio.cache_hit) == (out, 24000, False)
    assert audio.duration_s == pytest.approx((first + pause + second) / 24000)
    assert not pcm[first : first + pause].any()
    assert pcm[0] == round(0.25 * 32767)


def test_synthesize_splits_lines_and_handles_silent_segment(
    engine: KokoroEngine, tmp_path: Path
) -> None:
    script = SpokenScript((Segment("Line one.\n\nLine two."), Segment("", 500)))
    audio = engine.synthesize(script, _voice(engine), RenderOptions(), tmp_path / "a.wav")
    assert [c[0] for c in engine.backend.calls] == ["Line one.", "Line two."]
    assert audio.duration_s == pytest.approx((9 + 9) / 100 + 0.5)


def test_synthesize_clips_loud_audio(models_dir: Path, tmp_path: Path) -> None:
    eng = KokoroEngine(models_dir, FakeBackend(level=3.0))
    eng.synthesize(
        SpokenScript((Segment("Hi."),)), _voice(eng), RenderOptions(), tmp_path / "c.wav"
    )
    _, pcm = _read_wav(tmp_path / "c.wav")
    assert pcm.max() == 32767


def test_synthesize_clamps_speed_with_warning(engine: KokoroEngine, tmp_path: Path) -> None:
    script = SpokenScript((Segment("Hi."),))
    engine.synthesize(script, _voice(engine), RenderOptions(speed=9.0), tmp_path / "s.wav")
    assert engine.backend.calls[0][2] == 2.0
    assert any("speed" in w for w in engine.last_warnings)


def test_synthesize_reports_words_the_backend_skipped(engine: KokoroEngine, tmp_path) -> None:
    engine.backend.last_skipped = ["Xyzzy"]
    engine.synthesize(
        SpokenScript((Segment("Xyzzy."),)), _voice(engine), RenderOptions(), tmp_path / "k.wav"
    )
    assert any("Xyzzy" in w for w in engine.last_warnings)


@pytest.mark.parametrize(
    "key", ["piper:en_US-lessac-medium", "kokoro:../../evil", "kokoro:af_x.safetensors"]
)
def test_synthesize_rejects_unknown_voice(engine: KokoroEngine, tmp_path: Path, key: str) -> None:
    voice = VoiceInfo(key, "kokoro", "x", "en-US", "A", 1, True)
    with pytest.raises(ValueError, match="voice"):
        engine.synthesize(
            SpokenScript((Segment("Hi."),)), voice, RenderOptions(), tmp_path / "x.wav"
        )


def test_synthesize_refuses_when_unavailable(engine: KokoroEngine, monkeypatch, tmp_path) -> None:
    voice = _voice(engine)
    monkeypatch.setattr(kokoro, "_supported_platform", lambda: False)
    with pytest.raises(KokoroUnavailable, match="Apple Silicon"):
        engine.synthesize(
            SpokenScript((Segment("Hi."),)), voice, RenderOptions(), tmp_path / "x.wav"
        )


def test_synthesize_refuses_tampered_voice(
    engine: KokoroEngine, models_dir: Path, tmp_path
) -> None:
    voice = _voice(engine)
    (models_dir / "kokoro" / "voices" / "af_heart.safetensors").write_bytes(b"evil")
    with pytest.raises(KokoroUnavailable, match="af_heart"):
        engine.synthesize(
            SpokenScript((Segment("Hi."),)), voice, RenderOptions(), tmp_path / "x.wav"
        )


def test_synthesize_rejects_unexpected_sample_rate(models_dir: Path, tmp_path: Path) -> None:
    eng = KokoroEngine(models_dir, FakeBackend(rate=22050))
    with pytest.raises(KokoroError, match="22050"):
        eng.synthesize(
            SpokenScript((Segment("Hi."),)), _voice(eng), RenderOptions(), tmp_path / "r.wav"
        )


def test_close_releases_backend(engine: KokoroEngine) -> None:
    engine.close()
    assert engine.backend.closed


def test_engine_identity(engine: KokoroEngine) -> None:
    assert engine.key == "kokoro"
    assert "a71e4d38" in engine.version


@pytest.mark.parametrize(
    ("plat", "machine", "expected"),
    [("darwin", "arm64", True), ("darwin", "x86_64", False), ("linux", "arm64", False)],
)
def test_supported_platform(monkeypatch, plat: str, machine: str, expected: bool) -> None:
    monkeypatch.setattr(kokoro.sys, "platform", plat)
    monkeypatch.setattr(kokoro.platform, "machine", lambda: machine)
    assert kokoro._supported_platform() is expected


# --- InProcessBackend without MLX (fake modules) ------------------------------------------------


class _FakeResult:
    def __init__(self, text: str) -> None:
        self.phonemes = f"ps({text})"
        self.audio = np.ones((1, 240), dtype=np.float32)
        self.tokens = [
            types.SimpleNamespace(text="Xyzzy", phonemes=""),
            types.SimpleNamespace(text=".", phonemes="."),
        ]


class _FakePipeline:
    instances: list[dict] = []

    def __init__(self, **kwargs) -> None:
        _FakePipeline.instances.append(kwargs)

    def __call__(self, text, voice, speed, split_pattern):
        assert split_pattern is None
        yield _FakeResult(text)
        yield _FakeResult(text + "2")


@pytest.fixture
def fake_mlx(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    state = types.SimpleNamespace(cache_limit=None, cleared=0, loaded=[], spacy_ok=True)
    mx = types.ModuleType("mlx.core")
    mx.set_cache_limit = lambda n: setattr(state, "cache_limit", n)
    mx.clear_cache = lambda: setattr(state, "cleared", state.cleared + 1)
    mlx = types.ModuleType("mlx")
    mlx.core = mx
    utils = types.ModuleType("mlx_audio.tts.utils")

    def load_model(path, model_type):
        state.loaded.append((path, model_type))
        return types.SimpleNamespace(sample_rate=24000)

    utils.load_model = load_model
    pipeline = types.ModuleType("mlx_audio.tts.models.kokoro.pipeline")
    pipeline.KokoroPipeline = _FakePipeline
    spacy = types.ModuleType("spacy")
    spacy.util = types.SimpleNamespace(is_package=lambda name: state.spacy_ok)
    for name, mod in {
        "mlx": mlx,
        "mlx.core": mx,
        "mlx_audio": types.ModuleType("mlx_audio"),
        "mlx_audio.tts": types.ModuleType("mlx_audio.tts"),
        "mlx_audio.tts.utils": utils,
        "mlx_audio.tts.models": types.ModuleType("mlx_audio.tts.models"),
        "mlx_audio.tts.models.kokoro": types.ModuleType("mlx_audio.tts.models.kokoro"),
        "mlx_audio.tts.models.kokoro.pipeline": pipeline,
        "spacy": spacy,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    _FakePipeline.instances.clear()
    return state


def test_in_process_backend_drives_pipeline(fake_mlx, tmp_path: Path) -> None:
    backend = InProcessBackend(tmp_path, cache_limit_bytes=123)
    audio, rate = backend.synthesize_line("Hello.", "bf_emma", 1.1)
    assert rate == 24000 and audio.shape == (480,) and audio.dtype == np.float32
    assert backend.last_phonemes == ["ps(Hello.)", "ps(Hello.2)"]
    assert backend.last_skipped == ["Xyzzy", "Xyzzy"]
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert fake_mlx.loaded == [(tmp_path, "kokoro")] and fake_mlx.cache_limit == 123
    assert fake_mlx.cleared == 1
    assert _FakePipeline.instances[0]["lang_code"] == "b"
    backend.synthesize_line("Again.", "bf_emma", 1.0)
    backend.synthesize_line("US.", "af_heart", 1.0)
    assert [i["lang_code"] for i in _FakePipeline.instances] == [
        "b",
        "a",
    ]  # one pipeline per accent
    assert len(fake_mlx.loaded) == 1  # model loaded once
    backend.close()
    assert fake_mlx.cleared == 4


def test_in_process_backend_requires_spacy_model(fake_mlx, tmp_path: Path) -> None:
    fake_mlx.spacy_ok = False  # misaki would otherwise pip-install en_core_web_sm at runtime
    with pytest.raises(KokoroUnavailable, match="en_core_web_sm"):
        InProcessBackend(tmp_path).synthesize_line("Hi.", "af_heart", 1.0)


def test_in_process_backend_rejects_unsafe_voice(fake_mlx, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="voice"):
        InProcessBackend(tmp_path).synthesize_line("Hi.", "voices/af_heart.safetensors", 1.0)


def test_in_process_backend_without_mlx(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "mlx_audio", None)  # import fails like on a non-MLX venv
    monkeypatch.setitem(sys.modules, "mlx", None)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    with pytest.raises(KokoroUnavailable, match="not installed"):
        InProcessBackend(tmp_path).synthesize_line("Hi.", "af_heart", 1.0)
    InProcessBackend(tmp_path).close()  # closing an unloaded backend is a no-op


# --- real model through the lean Kokoro venv ----------------------------------------------------

_REAL_SCRIPT = textwrap.dedent(
    """
    import json, sys, wave
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from cloudyreader.engines.kokoro import KokoroEngine
    from cloudyreader.models import Override, RenderOptions, Segment, SpokenScript

    eng = KokoroEngine(Path(sys.argv[2]))
    seen = []
    line = eng.backend.synthesize_line
    def record(text, voice, speed):
        out = line(text, voice, speed)
        seen.extend(eng.backend.last_phonemes)
        return out
    eng.backend.synthesize_line = record
    ok = eng.available()
    voice = eng.voices()[0]
    ov = Override("Pharynx", "ˈfæɹɪŋks", "respelling")
    segments = (Segment("Life Science.", 300), Segment("W. Pharynx. X. Larynx.", 0, (ov,)))
    script = SpokenScript(segments)
    res = {"available": ok, "reason": eng.unavailable_reason, "voice": voice.key}
    for speed in (1.0, 1.5):
        out = Path(sys.argv[3]) / f"speed{speed}.wav"
        audio = eng.synthesize(script, voice, RenderOptions(speed=speed), out)
        with wave.open(str(out)) as w:
            fmt = [w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()]
        res[str(speed)] = {"fmt": fmt, "duration": audio.duration_s}
    res["phonemes"] = seen
    res["warnings"] = eng.last_warnings
    eng.close()
    print("RESULT " + json.dumps(res, ensure_ascii=False))
    """
)


@pytest.mark.model
@pytest.mark.skipif(not KOKORO_PYTHON.exists(), reason="lean Kokoro venv not present")
@pytest.mark.skipif(not (SNAPSHOT / "kokoro-v1_0.safetensors").is_file(), reason="no snapshot")
def test_real_kokoro_keeps_override_phonemes(tmp_path: Path) -> None:
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "kokoro").symlink_to(SNAPSHOT, target_is_directory=True)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    proc = subprocess.run(
        [
            str(KOKORO_PYTHON),
            "-I",
            "-W",
            "ignore",
            "-c",
            _REAL_SCRIPT,
            str(ROOT),
            str(tmp_path / "models"),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
        check=False,
    )
    line = next((x for x in proc.stdout.splitlines() if x.startswith("RESULT ")), None)
    assert line, proc.stdout[-2000:] + proc.stderr[-2000:]
    res = json.loads(line[len("RESULT ") :])
    assert res["available"], res["reason"]
    assert res["voice"] == "kokoro:af_heart"
    # Returned phonemes prove the override reached the model verbatim (default is fˈɛɹɪŋks).
    assert res["phonemes"][:2] == ["lˈIf sˈIəns.", "dˈʌbᵊlju fˈæɹɪŋks. ˈɛks lˈɛɹɪŋks."]
    normal, fast = res["1.0"], res["1.5"]
    assert normal["fmt"][:3] == [24000, 1, 2] and fast["fmt"][:3] == [24000, 1, 2]
    assert normal["duration"] == pytest.approx(normal["fmt"][3] / 24000)
    assert 2.5 < normal["duration"] < 8.0  # about 4 s of speech plus the 300 ms pause
    assert fast["duration"] < normal["duration"] * 0.8
    assert res["warnings"] == []
