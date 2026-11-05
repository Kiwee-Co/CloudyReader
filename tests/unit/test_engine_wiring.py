"""Engine wiring: optional engines after Kokoro, placeholder rows, reasons, load hints, genders."""

from __future__ import annotations

import dataclasses
import platform
import subprocess
import sys
import types
from pathlib import Path

import pytest

from cloudyreader import tts
from cloudyreader.config import Settings, load_settings
from cloudyreader.models import RenderOptions, Segment, SpokenScript, VoiceInfo
from cloudyreader.pipeline import Pipeline, _engines, _optional_engines, build_default_service
from cloudyreader.rotation import RotationMode, VoiceRotator
from cloudyreader.tts import EngineUnavailableError, TtsService
from cloudyreader.voice_meta import ENGINE_GENDERS, VoiceProfile, profile_of

ROOT = Path(__file__).resolve().parents[2]
KOKORO = "cloudyreader.engines.kokoro"
CHATTERBOX = "cloudyreader.engines.chatterbox_turbo"
QWEN = "cloudyreader.engines.qwen3_tts"
# Paths that do not exist: a fake-based test that touches the disk by mistake fails loudly.
SETTINGS = Settings(
    *(Path("/nonexistent") / name for name in ("data", "cache", "voices", "models"))
)
OPTS = RenderOptions()
SCRIPT = SpokenScript((Segment("Which gas do plants take in?", 300),))

LESSAC = VoiceInfo("piper:en_US-lessac-medium", "piper", "Lessac", "en-US", "medium", 1, True)
PIPER_RYAN = VoiceInfo("piper:en_US-ryan-medium", "piper", "Ryan", "en-US", "medium", 1, True)
HEART = VoiceInfo("kokoro:af_heart", "kokoro", "Heart (female)", "en-US", "A", 1, True)
GEORGE = VoiceInfo("kokoro:bm_george", "kokoro", "George (male)", "en-GB", "C", 1, True)
BUILTIN = VoiceInfo(
    "chatterbox_turbo:builtin",
    "chatterbox_turbo",
    "Chatterbox Turbo (built-in)",
    "en",
    "4-bit",
    1,
    True,
)
RYAN = VoiceInfo("qwen3_tts:ryan", "qwen3_tts", "Ryan (male)", "en", "8-bit", 1, True)
AIDEN = VoiceInfo("qwen3_tts:aiden", "qwen3_tts", "Aiden (male)", "en-US", "8-bit", 1, True)


def not_ready(voice: VoiceInfo, reason: str) -> VoiceInfo:
    return dataclasses.replace(voice, installed=False, reason=reason)


def keys(voices) -> list[str]:
    return [voice.key for voice in voices]


# --- fake engine modules -------------------------------------------------------------------------


class OptionalEngine:
    """The section 2 constructor, no model: it records the settings it was built with."""

    key = ""
    rows: tuple[VoiceInfo, ...] = ()

    def __init__(self, settings, backend=None, *, pinned=None, assess=None, slot=None) -> None:
        self.settings = settings

    def available(self) -> bool:
        return True

    def voices(self) -> list[VoiceInfo]:
        return list(self.rows)

    def synthesize(self, script, voice, opts, out_wav):
        raise AssertionError("the wiring tests never synthesize")


class FakeChatterbox(OptionalEngine):
    key = "chatterbox_turbo"
    rows = (BUILTIN,)


class FakeQwen(OptionalEngine):
    key = "qwen3_tts"
    rows = (RYAN, AIDEN)


class FakeKokoro(OptionalEngine):
    key = "kokoro"
    rows = (HEART,)

    def __init__(self, models_dir, backend=None, *, all_voices=False) -> None:
        super().__init__(None)
        self.all_voices = all_voices


class Exploding(OptionalEngine):
    def __init__(self, settings, *args, **kwargs) -> None:
        raise RuntimeError("engine constructor blew up")


def module(name: str, **attrs: object) -> types.ModuleType:
    mod = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(mod, attr, value)
    return mod


def broken_module(name: str, error: Exception) -> types.ModuleType:
    def explode(attr: str) -> object:  # PEP 562: every class lookup raises
        raise error

    return module(name, __getattr__=explode)


@pytest.fixture
def arm64(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "machine", lambda: "arm64")


@pytest.fixture
def fake_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kokoro, Chatterbox Turbo and Qwen3-TTS modules that load no MLX."""
    monkeypatch.setitem(sys.modules, KOKORO, module(KOKORO, KokoroEngine=FakeKokoro))
    monkeypatch.setitem(
        sys.modules, CHATTERBOX, module(CHATTERBOX, ChatterboxTurboEngine=FakeChatterbox)
    )
    monkeypatch.setitem(sys.modules, QWEN, module(QWEN, Qwen3TtsEngine=FakeQwen))


# --- registration --------------------------------------------------------------------------------


def test_engines_helper_still_returns_piper_and_kokoro_only(arm64, fake_engines, tmp_path):
    settings = load_settings({"CLOUDYREADER_DATA_DIR": str(tmp_path)})

    assert keys(_engines(settings)) == ["piper", "kokoro"]


def test_optional_engines_follow_kokoro_on_arm64(arm64, fake_engines, monkeypatch, tmp_path):
    settings = load_settings({"CLOUDYREADER_DATA_DIR": str(tmp_path), "CLOUDYREADER_OFFLINE": "1"})

    optional = _optional_engines(settings)

    assert keys(optional) == ["chatterbox_turbo", "qwen3_tts"]
    assert all(engine.settings is settings for engine in optional)

    entities = pytest.importorskip("cloudyreader.entities")
    monkeypatch.setattr(entities.SciEntityDetector, "preload", lambda self: None)  # no model load
    registered: list[str] = []

    class SpyService(TtsService):
        def __init__(self, engines, cache_dir) -> None:
            registered.extend(engine.key for engine in engines)
            super().__init__(engines, cache_dir)

    monkeypatch.setattr(tts, "TtsService", SpyService)
    service = build_default_service(settings)

    assert registered == ["piper", "kokoro", "chatterbox_turbo", "qwen3_tts"]  # the picker order
    assert keys(service.voices()) == [HEART.key, BUILTIN.key, RYAN.key, AIDEN.key]


def test_optional_engines_absent_off_apple_silicon(monkeypatch, caplog):
    looked_up: list[str] = []

    def record(attr: str) -> object:
        looked_up.append(attr)
        raise AttributeError(attr)

    for name in (CHATTERBOX, QWEN):
        monkeypatch.setitem(sys.modules, name, module(name, __getattr__=record))
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")

    with caplog.at_level("DEBUG", logger="cloudyreader.pipeline"):
        assert _optional_engines(SETTINGS) == []

    assert looked_up == []  # not even imported
    assert caplog.records == []


FAILURES = {
    # failure: (module factory, log level); a missing module is the normal Release A state for Qwen
    "missing": (lambda name, attr: None, "INFO"),
    "import error": (
        lambda name, attr: broken_module(name, ImportError("No module named 'mlx_audio'")),
        "INFO",
    ),
    "crash on import": (
        lambda name, attr: broken_module(name, RuntimeError("bad wheel")),
        "WARNING",
    ),
    "no such class": (lambda name, attr: module(name), "WARNING"),
    "constructor raises": (lambda name, attr: module(name, **{attr: Exploding}), "WARNING"),
}


@pytest.mark.parametrize("failure", FAILURES)
@pytest.mark.parametrize(
    ("name", "attr", "survivor"),
    [
        (CHATTERBOX, "ChatterboxTurboEngine", "qwen3_tts"),
        (QWEN, "Qwen3TtsEngine", "chatterbox_turbo"),
    ],
)
def test_a_failing_or_missing_engine_module_leaves_the_others(
    arm64, fake_engines, monkeypatch, caplog, failure, name, attr, survivor
):
    factory, level = FAILURES[failure]
    monkeypatch.setitem(sys.modules, name, factory(name, attr))

    with caplog.at_level("INFO", logger="cloudyreader.pipeline"):
        engines = _optional_engines(SETTINGS)

    assert keys(engines) == [survivor]
    assert [(r.levelname, name in r.getMessage()) for r in caplog.records] == [(level, True)]


def test_importing_pipeline_and_tts_loads_no_engine_module():
    # Engine modules import lazily inside _optional_engines: the GUI must start without MLX.
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import cloudyreader.pipeline, cloudyreader.tts\n"
        "heavy = ('numpy', 'mlx', 'mlx_audio', 'transformers', 'huggingface_hub', 'torch',\n"
        f"         {KOKORO!r}, {CHATTERBOX!r}, {QWEN!r})\n"
        "loaded = [m for m in heavy if m in sys.modules]\n"
        "assert not loaded, loaded\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


# --- TtsService: placeholder rows, reasons, load hints --------------------------------------------


class PlainEngine:
    """A TtsEngine without the optional hooks, as Piper and the test_tts fakes are."""

    def __init__(self, key: str, *, rows=(), ready: bool = True) -> None:
        self.key = key
        self.rows = tuple(rows)
        self.ready = ready

    def available(self) -> bool:
        return self.ready

    def voices(self) -> list[VoiceInfo]:
        return list(self.rows)

    def synthesize(self, script, voice, opts, out_wav):
        raise AssertionError("an unavailable engine is never called")


class HookedEngine(PlainEngine):
    """Adds the section 2 hooks: placeholder rows, `unavailable_reason`, `load_hint`."""

    def __init__(self, key: str, *, placeholders=(), reason=None, hint=None, **kwargs) -> None:
        super().__init__(key, **kwargs)
        self.placeholders = tuple(placeholders)
        self.reason = reason
        self.hint = hint
        self.unavailable_reason: str | None = None
        self.listed = 0

    def available(self) -> bool:
        self.unavailable_reason = None if self.ready else self.reason  # set here, as Kokoro does
        return self.ready

    def voices(self) -> list[VoiceInfo]:
        self.listed += 1
        return super().voices()

    def placeholder_voices(self) -> list[VoiceInfo]:
        return list(self.placeholders)

    def load_hint(self) -> str | None:
        return self.hint


def test_tts_lists_placeholder_rows_of_an_unavailable_engine_as_not_installed(tmp_path):
    waiting = "waiting for a Qwen3 decoder fix"
    claims_installed = dataclasses.replace(AIDEN, reason=waiting)  # an engine bug: still dimmed
    qwen = HookedEngine(
        "qwen3_tts",
        rows=(RYAN, AIDEN),
        placeholders=(not_ready(RYAN, waiting), claims_installed),
        ready=False,
    )
    service = TtsService([PlainEngine("piper", rows=(LESSAC,)), qwen], tmp_path)

    listed = service.voices()

    assert [(v.key, v.installed, v.reason) for v in listed] == [
        (LESSAC.key, True, ""),
        (RYAN.key, False, waiting),
        (AIDEN.key, False, waiting),
    ]
    assert qwen.listed == 0  # an unavailable engine is never asked for its real rows

    qwen.ready = True  # the weights landed: the real rows replace the placeholders

    assert [(v.key, v.installed) for v in service.voices()] == [
        (LESSAC.key, True),
        (RYAN.key, True),
        (AIDEN.key, True),
    ]


def test_tts_still_hides_an_unavailable_engine_without_the_hook(tmp_path):
    kokoro = PlainEngine("kokoro", rows=(HEART,), ready=False)

    assert TtsService([PlainEngine("piper", rows=(LESSAC,)), kokoro], tmp_path).voices() == [LESSAC]


def test_a_raising_engine_hides_only_its_own_rows(tmp_path, caplog):
    def explode() -> list[VoiceInfo]:
        raise OSError("models folder vanished")

    qwen = HookedEngine("qwen3_tts", ready=False)
    qwen.placeholder_voices = explode
    chatterbox = HookedEngine("chatterbox_turbo")
    chatterbox.available = explode
    service = TtsService([qwen, chatterbox, PlainEngine("piper", rows=(LESSAC,))], tmp_path)

    with caplog.at_level("WARNING", logger="cloudyreader.tts"):
        assert service.voices() == [LESSAC]

    assert "qwen3_tts" in caplog.text and "chatterbox_turbo" in caplog.text
    assert "models folder vanished" in caplog.text


def test_engine_unavailable_error_appends_the_reason(tmp_path):
    qwen = HookedEngine("qwen3_tts", ready=False, reason="waiting for a Qwen3 decoder fix")
    service = TtsService([qwen], tmp_path)
    head = r"^TTS engine 'qwen3_tts' is unavailable \(voice qwen3_tts:ryan\)"

    with pytest.raises(EngineUnavailableError, match=head + ": waiting for a Qwen3 decoder fix$"):
        service.synthesize(SCRIPT, RYAN, OPTS)

    for silent in (None, ""):
        qwen.reason = silent
        with pytest.raises(EngineUnavailableError, match=head + "$"):
            service.synthesize(SCRIPT, RYAN, OPTS)


def test_tts_load_hint_asks_the_engine(tmp_path):
    first_use = "loading Chatterbox Turbo (first use only)"
    chatterbox = HookedEngine("chatterbox_turbo", rows=(BUILTIN,), hint=first_use)
    service = TtsService([PlainEngine("piper", rows=(LESSAC,)), chatterbox], tmp_path)

    assert service.load_hint(BUILTIN) == first_use
    assert service.load_hint(LESSAC) is None  # an engine without the hook
    assert service.load_hint(RYAN) is None  # no engine registered for the voice

    chatterbox.hint = None  # the model is resident now

    assert service.load_hint(BUILTIN) is None


# --- Pipeline: the voice error and the load hint -------------------------------------------------


class ListingTts:
    """A SpeechService without the optional hooks."""

    def __init__(self, rows) -> None:
        self.rows = list(rows)

    def voices(self) -> list[VoiceInfo]:
        return list(self.rows)

    def synthesize(self, script, voice, opts):
        raise AssertionError("a voice that is not ready never reaches synthesize")


def reader(service) -> Pipeline:
    # Only the voice lookup runs: any other stage would fail on object().
    unused = object()
    return Pipeline(
        parser=unused,
        detector=unused,
        resolver=unused,
        normalizer=unused,
        tts=service,
        settings=SETTINGS,
    )


def test_find_voice_error_carries_the_reason():
    pipeline = reader(ListingTts([not_ready(RYAN, "not downloaded yet"), not_ready(HEART, "")]))

    with pytest.raises(
        ValueError, match=r"^voice 'qwen3_tts:ryan' is not installed: not downloaded yet$"
    ):
        pipeline.prepare("Which gas do plants take in?", RYAN.key, OPTS)
    with pytest.raises(ValueError, match=r"^voice 'kokoro:af_heart' is not installed$"):
        pipeline.prepare("Which gas do plants take in?", HEART.key, OPTS)


def test_pipeline_load_hint_names_the_first_use_load_and_never_raises(tmp_path, caplog):
    first_use = "loading Chatterbox Turbo (first use only)"
    chatterbox = HookedEngine("chatterbox_turbo", rows=(BUILTIN,), hint=first_use)
    qwen = HookedEngine(
        "qwen3_tts",
        placeholders=(not_ready(RYAN, "not downloaded yet"),),
        ready=False,
        hint="loading Qwen3-TTS (first use only)",
    )
    pipeline = reader(TtsService([chatterbox, qwen], tmp_path))

    assert pipeline.load_hint(BUILTIN.key) == first_use
    assert pipeline.load_hint(RYAN.key) is None  # a dimmed row: prepare() refuses it first
    assert pipeline.load_hint("piper:nope") is None
    chatterbox.hint = ""
    assert pipeline.load_hint(BUILTIN.key) is None

    def explode() -> str:
        raise OSError("stat failed")

    chatterbox.load_hint = explode
    with caplog.at_level("WARNING", logger="cloudyreader.pipeline"):
        assert pipeline.load_hint(BUILTIN.key) is None

    assert "stat failed" in caplog.text
    assert reader(ListingTts([BUILTIN])).load_hint(BUILTIN.key) is None  # no hook on the service


# --- genders and rotation ------------------------------------------------------------------------


def test_qwen_presets_are_male_and_chatterbox_never_rotates():
    assert {engine: dict(table) for engine, table in ENGINE_GENDERS.items()} == {
        "qwen3_tts": {"ryan": "male", "aiden": "male"},
        "chatterbox_turbo": {},
    }
    with pytest.raises(TypeError):
        ENGINE_GENDERS["qwen3_tts"]["vivian"] = "female"
    with pytest.raises(TypeError):
        ENGINE_GENDERS["kokoro"] = {}

    assert profile_of(RYAN) == VoiceProfile("male", "en")
    assert profile_of(AIDEN) == VoiceProfile("male", "en-US")
    assert profile_of(BUILTIN) is None  # gender unconfirmed: it never rotates
    assert profile_of(dataclasses.replace(RYAN, key="qwen3_tts:vivian")) is None
    assert profile_of(dataclasses.replace(RYAN, language="zh-CN")) is None
    for mode in RotationMode:
        assert BUILTIN.key not in keys(VoiceRotator(mode).pool([BUILTIN, RYAN, AIDEN]))


def test_men_only_pool_includes_qwen_and_us_only_skips_ryan():
    voices = [LESSAC, PIPER_RYAN, HEART, GEORGE, BUILTIN, RYAN, AIDEN]

    men = VoiceRotator(RotationMode.MEN_SHUFFLE).pool(voices)
    us = VoiceRotator(RotationMode.US_SHUFFLE).pool(voices)

    assert keys(men) == [PIPER_RYAN.key, GEORGE.key, RYAN.key, AIDEN.key]
    assert keys(us) == [LESSAC.key, PIPER_RYAN.key, HEART.key, AIDEN.key]  # Ryan is plain "en"
    placeholders = [not_ready(RYAN, "not downloaded yet"), not_ready(AIDEN, "not downloaded yet")]
    for mode in RotationMode:
        assert VoiceRotator(mode).pool(placeholders) == []
