"""TtsService: engine registry, content-addressed WAV cache, error paths (FakeEngine only)."""

from __future__ import annotations

import dataclasses
import re
import threading
import time
import wave
from pathlib import Path

import pytest

from cloudyreader.models import Audio, Override, RenderOptions, Segment, SpokenScript, VoiceInfo
from cloudyreader.tts import EngineUnavailableError, TtsError, TtsService

RATE = 8000


def voice(key: str = "piper:fake-voice", engine: str = "piper") -> VoiceInfo:
    return VoiceInfo(key, engine, "fake", "en-US", "medium", 1, True, Path("/nonexistent.onnx"))


SCRIPT = SpokenScript(
    (
        Segment("Pharynx is a word.", 400, (Override("Pharynx", "ˈfɑɹɪŋks", "respelling"),)),
        Segment("Second.", 0),
    ),
    warnings=("upstream note",),
)
OPTS = RenderOptions()


class FakeEngine:
    """Writes 0.1 s of silence and counts calls; stands in for piper or kokoro."""

    def __init__(
        self,
        key: str = "piper",
        *,
        version: str | None = "fake-1",
        available: bool = True,
        voices: tuple[VoiceInfo, ...] = (),
        delay_s: float = 0.0,
    ) -> None:
        self.key = key
        if version is not None:
            self.version = version
        self.is_available = available
        self.listed = voices
        self.delay_s = delay_s
        self.calls: list[tuple[SpokenScript, VoiceInfo, RenderOptions, Path]] = []
        self.fail: Exception | None = None

    def available(self) -> bool:
        return self.is_available

    def voices(self) -> list[VoiceInfo]:
        if self.fail is not None:
            raise self.fail
        return list(self.listed)

    def synthesize(self, script, voice, opts, out_wav: Path) -> Audio:
        self.calls.append((script, voice, opts, out_wav))
        time.sleep(self.delay_s)
        if self.fail is not None:
            out_wav.write_bytes(b"partial")  # a crash mid-write must not reach the cache
            raise self.fail
        with wave.open(str(out_wav), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            wav.writeframes(b"\x00\x00" * (RATE // 10))
        return Audio(out_wav, RATE, 0.1, False)


class WarningEngine(FakeEngine):
    """Adds the optional warning hooks the way PiperEngine and KokoroEngine expose them."""

    warnings: tuple[str, ...] = ()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.last_warnings: list[str] = []

    def synthesize(self, script, voice, opts, out_wav: Path) -> Audio:
        self.last_warnings = list(self.warnings)
        return super().synthesize(script, voice, opts, out_wav)

    def script_warnings(self, script, voice) -> tuple[str, ...]:
        return self.warnings


class VersionedEngine(FakeEngine):
    """Adds the optional per-voice fingerprint hook."""

    voice_stamp = "v1"

    def voice_version(self, voice: VoiceInfo) -> str:
        return f"{voice.key}:{self.voice_stamp}"


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache"


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def service(engine: FakeEngine, cache_dir: Path) -> TtsService:
    return TtsService([engine], cache_dir)


# --- voices ----------------------------------------------------------------------------------


def test_voices_aggregates_the_available_engines_in_order(cache_dir):
    piper = FakeEngine("piper", voices=(voice("piper:a"), voice("piper:b")))
    kokoro = FakeEngine("kokoro", voices=(voice("kokoro:af", "kokoro"),))
    service = TtsService([piper, kokoro], cache_dir)

    assert [v.key for v in service.voices()] == ["piper:a", "piper:b", "kokoro:af"]


def test_voices_skips_an_unavailable_engine(cache_dir):
    piper = FakeEngine("piper", voices=(voice("piper:a"),))
    kokoro = FakeEngine("kokoro", available=False, voices=(voice("kokoro:af", "kokoro"),))

    assert [v.key for v in TtsService([piper, kokoro], cache_dir).voices()] == ["piper:a"]


def test_voices_keeps_going_when_one_engine_raises_and_logs_it(cache_dir, caplog):
    broken = FakeEngine("kokoro")
    broken.fail = RuntimeError("model file corrupt")
    piper = FakeEngine("piper", voices=(voice("piper:a"),))

    with caplog.at_level("WARNING", logger="cloudyreader.tts"):
        found = TtsService([broken, piper], cache_dir).voices()

    assert [v.key for v in found] == ["piper:a"]
    assert "kokoro" in caplog.text and "model file corrupt" in caplog.text


def test_duplicate_engine_keys_are_rejected(cache_dir):
    with pytest.raises(ValueError, match="piper"):
        TtsService([FakeEngine("piper"), FakeEngine("piper")], cache_dir)


# --- cache hit and miss ----------------------------------------------------------------------


def test_first_synthesis_is_a_miss_and_lands_in_the_cache(service, engine, cache_dir):
    audio = service.synthesize(SCRIPT, voice(), OPTS)

    assert audio.cache_hit is False
    assert (audio.sample_rate, audio.duration_s) == (RATE, pytest.approx(0.1))
    assert audio.wav_path.parent == cache_dir
    assert re.fullmatch(r"[0-9a-f]{64}\.wav", audio.wav_path.name)
    assert audio.wav_path.exists()
    assert len(engine.calls) == 1
    assert [p.name for p in cache_dir.iterdir()] == [audio.wav_path.name]  # no temp left


def test_the_engine_never_writes_straight_into_the_final_cache_path(service, engine):
    audio = service.synthesize(SCRIPT, voice(), OPTS)

    assert engine.calls[0][3] != audio.wav_path


def test_second_identical_request_is_a_hit_without_an_engine_call(service, engine):
    first = service.synthesize(SCRIPT, voice(), OPTS)
    second = service.synthesize(SCRIPT, voice(), OPTS)

    assert second.cache_hit is True
    assert len(engine.calls) == 1
    assert second.wav_path == first.wav_path
    assert (second.sample_rate, second.duration_s) == (RATE, pytest.approx(0.1))


def test_a_new_service_over_the_same_cache_dir_hits_too(engine, cache_dir):
    TtsService([engine], cache_dir).synthesize(SCRIPT, voice(), OPTS)
    other = FakeEngine()

    again = TtsService([other], cache_dir).synthesize(SCRIPT, voice(), OPTS)

    assert again.cache_hit is True and other.calls == []


def test_corrupt_cache_entry_is_regenerated(service, engine):
    first = service.synthesize(SCRIPT, voice(), OPTS)
    first.wav_path.write_bytes(b"this is not a wav file")

    again = service.synthesize(SCRIPT, voice(), OPTS)

    assert again.cache_hit is False
    assert len(engine.calls) == 2
    with wave.open(str(again.wav_path)) as wav:
        assert wav.getnframes() == RATE // 10


def test_engine_failure_leaves_no_cache_entry_and_no_temp_file(service, engine, cache_dir):
    engine.fail = RuntimeError("onnx exploded")

    with pytest.raises(RuntimeError, match="onnx exploded"):
        service.synthesize(SCRIPT, voice(), OPTS)

    assert list(cache_dir.iterdir()) == []
    engine.fail = None
    assert service.synthesize(SCRIPT, voice(), OPTS).cache_hit is False  # retry works


def test_identical_concurrent_requests_synthesize_once(cache_dir):
    slow = FakeEngine(delay_s=0.15)
    service = TtsService([slow], cache_dir)
    results: list[Audio] = []

    def run() -> None:
        results.append(service.synthesize(SCRIPT, voice(), OPTS))

    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(slow.calls) == 1
    assert sorted(a.cache_hit for a in results) == [False, True, True]


# --- cache key -------------------------------------------------------------------------------


def key_of(service: TtsService, script=SCRIPT, v=None, opts=OPTS) -> str:
    return service.cache_key(script, v or voice(), opts)


def test_cache_key_is_a_stable_sha256(cache_dir):
    one = key_of(TtsService([FakeEngine()], cache_dir))
    two = key_of(TtsService([FakeEngine()], cache_dir / "elsewhere"))

    assert re.fullmatch(r"[0-9a-f]{64}", one)
    assert one == two


def test_cache_key_survives_text_that_is_not_valid_unicode(service):
    broken = SpokenScript((Segment("lone surrogate \ud800 from a bad paste", 0),))

    assert re.fullmatch(r"[0-9a-f]{64}", key_of(service, broken))


def with_text(script: SpokenScript, text: str) -> SpokenScript:
    first = dataclasses.replace(script.segments[0], text=text)
    return dataclasses.replace(script, segments=(first, *script.segments[1:]))


def with_first(script: SpokenScript, **changes) -> SpokenScript:
    first = dataclasses.replace(script.segments[0], **changes)
    return dataclasses.replace(script, segments=(first, *script.segments[1:]))


@pytest.mark.parametrize(
    ("label", "change"),
    [
        ("segment text", lambda s: (with_text(s, "Larynx is a word."), voice(), OPTS)),
        ("pause", lambda s: (with_first(s, pause_after_ms=401), voice(), OPTS)),
        (
            "override ipa",
            lambda s: (
                with_first(s, overrides=(Override("Pharynx", "fˈæɹɪŋks", "respelling"),)),
                voice(),
                OPTS,
            ),
        ),
        ("override removed", lambda s: (with_first(s, overrides=()), voice(), OPTS)),
        (
            "segment order",
            lambda s: (dataclasses.replace(s, segments=s.segments[::-1]), voice(), OPTS),
        ),
        ("voice", lambda s: (s, voice("piper:other-voice"), OPTS)),
        ("speed", lambda s: (s, voice(), RenderOptions(speed=1.25))),
        ("speaker", lambda s: (s, voice(), RenderOptions(speaker_id=3))),
    ],
)
def test_cache_key_changes_with_anything_that_changes_the_audio(service, label, change):
    script, v, opts = change(SCRIPT)

    assert key_of(service, script, v, opts) != key_of(service), label


def test_cache_key_changes_with_the_engine_version(cache_dir):
    old = key_of(TtsService([FakeEngine(version="1")], cache_dir))
    new = key_of(TtsService([FakeEngine(version="2")], cache_dir))

    assert old != new


def test_cache_key_changes_when_the_engine_reports_a_new_voice_version(cache_dir):
    engine = VersionedEngine()
    service = TtsService([engine], cache_dir)
    before = key_of(service)

    engine.voice_stamp = "v2"

    assert key_of(service) != before


def test_replacing_a_voice_misses_the_cache(cache_dir):
    engine = VersionedEngine()
    service = TtsService([engine], cache_dir)
    service.synthesize(SCRIPT, voice(), OPTS)
    assert service.synthesize(SCRIPT, voice(), OPTS).cache_hit is True

    engine.voice_stamp = "v2"  # the voice files changed on disk

    assert service.synthesize(SCRIPT, voice(), OPTS).cache_hit is False
    assert len(engine.calls) == 2


def test_cache_key_falls_back_to_the_engine_key_without_a_version(cache_dir):
    assert key_of(TtsService([FakeEngine(version=None)], cache_dir))


@pytest.mark.parametrize(
    "change",
    [
        lambda s: dataclasses.replace(s, warnings=("another note",)),
        lambda s: dataclasses.replace(s, warnings=()),
    ],
)
def test_cache_key_ignores_script_warnings(service, change):
    assert key_of(service, change(SCRIPT)) == key_of(service)


@pytest.mark.parametrize(
    "opts", [RenderOptions(read_answer=True), RenderOptions(online_lookups=False)]
)
def test_cache_key_ignores_options_that_only_shape_the_script(service, opts):
    assert key_of(service, opts=opts) == key_of(service)


def test_cache_key_treats_integer_and_float_speed_alike(service):
    assert key_of(service, opts=RenderOptions(speed=1)) == key_of(
        service, opts=RenderOptions(speed=1.0)
    )


# --- engine selection ------------------------------------------------------------------------


def test_voice_is_routed_to_the_engine_named_by_voice_engine(cache_dir):
    piper, kokoro = FakeEngine("piper"), FakeEngine("kokoro")
    service = TtsService([piper, kokoro], cache_dir)

    service.synthesize(SCRIPT, voice("kokoro:af_heart", "kokoro"), OPTS)

    assert piper.calls == [] and len(kokoro.calls) == 1


def test_unknown_engine_raises_a_clear_error(service, engine):
    with pytest.raises(EngineUnavailableError, match="kokoro"):
        service.synthesize(SCRIPT, voice("kokoro:af_heart", "kokoro"), OPTS)

    assert engine.calls == []


def test_unavailable_engine_raises_a_clear_error_and_is_not_called(cache_dir):
    off = FakeEngine("kokoro", available=False)
    service = TtsService([off], cache_dir)

    with pytest.raises(EngineUnavailableError, match="kokoro.*unavailable"):
        service.synthesize(SCRIPT, voice("kokoro:af_heart", "kokoro"), OPTS)

    assert off.calls == []


def test_engine_errors_are_tts_errors():
    assert issubclass(EngineUnavailableError, TtsError)
    assert issubclass(TtsError, RuntimeError)


def test_a_cache_hit_still_requires_an_available_engine(cache_dir):
    first = FakeEngine()
    TtsService([first], cache_dir).synthesize(SCRIPT, voice(), OPTS)
    first.is_available = False

    with pytest.raises(EngineUnavailableError):
        TtsService([first], cache_dir).synthesize(SCRIPT, voice(), OPTS)


# --- engine warnings -------------------------------------------------------------------------


def test_script_warnings_come_from_the_engine(cache_dir):
    engine = WarningEngine()
    engine.warnings = ("piper: dropped IPA symbol 'ɝ'",)

    result = TtsService([engine], cache_dir).script_warnings(SCRIPT, voice())

    assert result == ("piper: dropped IPA symbol 'ɝ'",)


def test_script_warnings_are_empty_for_an_engine_without_the_hook(service):
    assert service.script_warnings(SCRIPT, voice()) == ()


def test_script_warnings_need_an_available_engine(cache_dir):
    with pytest.raises(EngineUnavailableError):
        TtsService([WarningEngine(available=False)], cache_dir).script_warnings(SCRIPT, voice())


# --- last_warnings ---------------------------------------------------------------------------


def test_last_warnings_are_empty_before_any_synthesis(cache_dir):
    assert TtsService([WarningEngine()], cache_dir).last_warnings == []


def test_last_warnings_carry_the_engine_notes_after_a_miss(cache_dir):
    engine = WarningEngine()
    engine.warnings = ("piper: dropped IPA symbol 'ɝ'",)
    service = TtsService([engine], cache_dir)

    service.synthesize(SCRIPT, voice(), OPTS)

    assert service.last_warnings == ["piper: dropped IPA symbol 'ɝ'"]


def test_last_warnings_are_empty_after_a_cache_hit(cache_dir):
    engine = WarningEngine()
    engine.warnings = ("a note",)
    service = TtsService([engine], cache_dir)
    service.synthesize(SCRIPT, voice(), OPTS)

    again = service.synthesize(SCRIPT, voice(), OPTS)

    assert again.cache_hit is True
    assert service.last_warnings == []  # script_warnings() still reports them on a hit


def test_last_warnings_are_cleared_when_the_next_synthesis_fails(cache_dir):
    engine = WarningEngine()
    engine.warnings = ("a note",)
    service = TtsService([engine], cache_dir)
    service.synthesize(SCRIPT, voice(), OPTS)
    engine.fail = RuntimeError("onnx exploded")

    with pytest.raises(RuntimeError):
        service.synthesize(with_text(SCRIPT, "A different text."), voice(), OPTS)

    assert service.last_warnings == []


def test_last_warnings_are_empty_for_an_engine_without_them(service):
    service.synthesize(SCRIPT, voice(), OPTS)

    assert service.last_warnings == []


def test_last_warnings_are_a_copy(cache_dir):
    engine = WarningEngine()
    engine.warnings = ("a note",)
    service = TtsService([engine], cache_dir)
    service.synthesize(SCRIPT, voice(), OPTS)

    service.last_warnings.append("tampered")

    assert service.last_warnings == ["a note"]


def test_last_warnings_belong_to_the_thread_that_synthesized(cache_dir):
    engine = WarningEngine()
    engine.warnings = ("a note",)
    service = TtsService([engine], cache_dir)
    seen: dict[str, list[str]] = {}

    def worker() -> None:
        service.synthesize(SCRIPT, voice(), OPTS)
        seen["worker"] = service.last_warnings

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert seen["worker"] == ["a note"]
    assert service.last_warnings == []  # this thread never synthesized
