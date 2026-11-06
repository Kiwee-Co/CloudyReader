"""scripts/live_smoke_engines.py: the probe units, per-voice numbers and verdicts, on fake engines.

No weights and no mlx: fake engines write small WAVs through a fake backend whose render calls the
smoke records, so it can tell a unit said alone from one that needed the repeat fallback.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import re
import runpy
import sys
import types
import wave
from array import array
from collections.abc import Callable
from pathlib import Path

import pytest

from cloudyreader.config import load_settings
from cloudyreader.models import Audio, RenderOptions, SpokenScript, VoiceInfo

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "live_smoke_engines.py"
FIXTURE_02 = (
    ROOT / "tests" / "fixtures" / "questions" / "02-life-science-respiratory-respelling-mc.txt"
)
ENGINE_MODULES = ("cloudyreader.engines.chatterbox_turbo", "cloudyreader.engines.qwen3_tts")
RATE = 24_000


def _load():
    # scripts/ is not a package, so import the file by path.
    spec = importlib.util.spec_from_file_location("live_smoke_engines", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["live_smoke_engines"] = module  # dataclasses resolve annotations through it
    spec.loader.exec_module(module)
    return module


smoke = _load()
UNITS = [unit.text for unit in smoke.short_units()]


def label(text: str) -> str:
    return smoke.label(text)


def write_wav(path: Path, seconds: float, peak: float) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(array("h", [int(peak * 32767)] * int(seconds * RATE)).tobytes())


def natural(text: str) -> tuple[float, float]:
    """A plausible reading: about 14 characters a second, at least 0.4 s, peak 0.6."""
    return max(0.4, len(text) / 14), 0.6


class FakeBackend:
    def render(self, text: str, voice: str, *, seed: int, budget_s: float):
        return [], RATE

    def close(self) -> None:
        pass


@dataclasses.dataclass
class FakeEngine:
    """Says each text alone, or through the repeat fallback, or fails, as `ladder` asks."""

    key: str = "chatterbox_turbo"
    reason: str | None = None
    voice_ids: tuple[str, ...] = ("builtin",)
    speak: Callable[[str], tuple[float, float]] = natural  # text -> (seconds, peak); may raise
    ladder: dict[str, str] = dataclasses.field(default_factory=dict)  # text -> fallback | fail
    backend: FakeBackend = dataclasses.field(default_factory=FakeBackend)
    outputs: list[Path] = dataclasses.field(default_factory=list)
    closed: int = 0

    @property
    def unavailable_reason(self) -> str | None:
        return self.reason

    def available(self) -> bool:
        return self.reason is None

    def voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(f"{self.key}:{v}", self.key, v.title(), "en", "4-bit", 1, True)  # type: ignore[arg-type]
            for v in self.voice_ids
        ]

    def synthesize(
        self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions, out_wav: Path
    ) -> Audio:
        (segment,) = script.segments
        text, step = segment.text, self.ladder.get(segment.text)
        self.backend.render(text, voice.key, seed=0, budget_s=2.0)
        if step:
            self.backend.render(text, voice.key, seed=1, budget_s=2.0)
            if step == "fail":
                raise RuntimeError(f"could not say {text!r}")
            self.backend.render(" ".join([text] * 3), voice.key, seed=2, budget_s=6.0)
        seconds, peak = self.speak(text)
        write_wav(out_wav, seconds, peak)
        self.outputs.append(out_wav)
        return Audio(out_wav, RATE, seconds, False)

    def close(self) -> None:
        self.closed += 1


def run(capsys, engines, tmp_path: Path) -> tuple[int, str]:
    settings = load_settings({"CLOUDYREADER_DATA_DIR": str(tmp_path / "data")})
    code = smoke.main(engines=engines, settings=settings)
    return code, capsys.readouterr().out


def verdict(out: str) -> list[str]:
    return out.split("== verdict ==\n", 1)[1].splitlines()


def unit_line(out: str, text: str) -> str:
    (line,) = [line for line in out.splitlines() if line[9:].startswith(f"{label(text):<20} ")]
    return line


# --- what the probe says --------------------------------------------------------------------------


def test_short_unit_probe_covers_letters_header_phrases_and_one_word_choices():
    assert smoke.FIXTURE_02 == FIXTURE_02.read_bytes().decode("utf-8")  # a word-for-word copy
    units = smoke.short_units()

    assert len(units) == 12
    assert UNITS[:3] == ["Question number one.", "Life Science.", "Multiple choice."]
    assert UNITS[3].startswith("Which of the following is NOT part of")  # the stem
    assert UNITS[4::2] == ["W.", "X.", "Y.", "Z."]
    assert UNITS[5::2] == ["Pharynx", "Larynx", "Esophagus", "Trachea"]
    assert all(unit.overrides for unit in units[5::2])  # each carries the paste's respelling
    assert all(unit.pause_after_ms == 0 for unit in units)  # the unit alone, not its pause


def test_three_sentences_with_the_hard_words_in_both_respelling_styles():
    texts = dict(smoke.SENTENCES)

    assert list(texts) == ["plain", "numbers", "hyphen", "joined"]
    assert "-" in texts["hyphen"] and texts["hyphen"].replace("-", "") == texts["joined"]


@pytest.mark.parametrize(
    ("text", "seconds", "peak", "problem"),
    [
        ("W.", 0.4, 0.5, None),
        ("W.", 1.95, 0.5, "too long"),  # a runaway: 1.9 x max(1.0 s, characters / 14)
        ("W.", 0.05, 0.5, "too short"),  # under 0.1 s: nothing was said
        ("W.", 0.4, 0.005, "silent"),
        ("x" * 140, 18.0, 0.5, None),  # estimate 10 s, runaway at 19 s
        ("x" * 140, 19.5, 0.5, "too long"),
        ("x" * 140, 2.0, 0.5, "too short"),  # a long text under a quarter of its estimate
    ],
)
def test_check_flags_runaway_short_and_silent_audio(text, seconds, peak, problem):
    found = smoke.check(text, seconds, peak)

    assert found is None if problem is None else problem in found


# --- per voice ------------------------------------------------------------------------------------


def test_each_voice_reports_load_audio_wall_rtf_and_peak_rss(tmp_path, capsys):
    engine = FakeEngine(key="qwen3_tts", voice_ids=("ryan", "aiden"))

    code, out = run(capsys, [engine], tmp_path)

    assert code == 0
    for voice in ("qwen3_tts:ryan", "qwen3_tts:aiden"):
        block = out.split(f"== {voice} ", 1)[1].split("\n== ", 1)[0]
        assert re.search(r"^load +first call .* \d+\.\d\d s$", block, re.M)
        for text in [*UNITS, *dict(smoke.SENTENCES)]:
            pattern = rf"^HELD +{re.escape(label(text))} +alone +\d+\.\d\d s audio, .* RTF \d"
            assert re.search(pattern, block, re.M), text
        assert re.search(r"peak RSS [\d,]+ MB", block)
    assert engine.closed == 2  # closed after each voice, so each one loads from cold
    assert [line for line in verdict(out) if line.startswith("HELD")] == verdict(out)[:2]


def test_each_short_unit_reports_alone_fallback_or_fail(tmp_path, capsys):
    engine = FakeEngine(ladder={"W.": "fallback", "X.": "fail"})

    _, out = run(capsys, [engine], tmp_path)

    assert re.match(r"HELD +W\. +fallback +\d+\.\d\d s audio, .*3 tries$", unit_line(out, "W."))
    assert re.match(r"BROKEN +X\. +fail .*failed: RuntimeError", unit_line(out, "X."))
    assert re.match(r"HELD +Y\. +alone +.*1 try$", unit_line(out, "Y."))
    (line,) = verdict(out)[:1]
    assert "short units 11/12 (1 by fallback)" in line
    assert line.endswith("fails: X.")


class Opaque(FakeEngine):
    """An engine that keeps its backend to itself: the smoke cannot watch its render calls."""

    def synthesize(
        self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions, out_wav: Path
    ) -> Audio:
        (segment,) = script.segments
        seconds, peak = self.speak(segment.text)
        write_wav(out_wav, seconds, peak)
        return Audio(out_wav, RATE, seconds, False)


def test_the_path_is_unknown_when_the_engine_shows_no_backend(tmp_path, capsys):
    engine = Opaque()
    engine.backend = None  # type: ignore[assignment]

    _, out = run(capsys, [engine], tmp_path)

    assert re.match(r"HELD +W\. +\? +\d", unit_line(out, "W."))
    assert not unit_line(out, "W.").endswith("try")  # no count without a backend to watch


def test_live_smoke_engines_prints_no_url_and_writes_only_to_a_temp_dir(
    tmp_path, monkeypatch, capsys
):
    scratch, cwd = tmp_path / "tmp", tmp_path / "cwd"
    scratch.mkdir()
    cwd.mkdir()
    monkeypatch.setattr(smoke.tempfile, "tempdir", str(scratch))
    monkeypatch.chdir(cwd)

    def leaky(text: str) -> tuple[float, float]:
        if text == "Z.":
            raise RuntimeError("could not reach https://weights.example/model.safetensors")
        return natural(text)

    engine = FakeEngine(speak=leaky)
    absent = smoke.Absent("qwen3_tts", "see http://docs.example/why")

    code, out = run(capsys, [engine, absent], tmp_path)

    assert code == 0
    assert "://" not in out and "weights.example" not in out and "docs.example" not in out
    assert engine.outputs and all(scratch in path.parents for path in engine.outputs)
    assert not any(scratch.iterdir())  # the temp dir is gone afterwards
    assert not any(cwd.iterdir()) and not (tmp_path / "data").exists()


def raises(text: str) -> tuple[float, float]:
    raise RuntimeError("model exploded")


class BadVoices(FakeEngine):
    def voices(self) -> list[VoiceInfo]:
        raise OSError("weights unreadable")


class NotAnEngine:
    key = "chatterbox_turbo"


CASES = {
    "all good": (lambda: [FakeEngine()], "HELD     chatterbox_turbo:builtin"),
    "every render raises": (
        lambda: [FakeEngine(speak=raises)],
        "BROKEN   chatterbox_turbo:builtin",
    ),
    "unavailable": (
        lambda: [FakeEngine(reason="not downloaded yet")],
        "NO DATA  chatterbox_turbo  not downloaded yet",
    ),
    "module absent": (
        lambda: [smoke.Absent("qwen3_tts", "engine module not in this tree")],
        "NO DATA  qwen3_tts  engine module not in this tree",
    ),
    "runaway letter": (
        lambda: [FakeEngine(speak=lambda t: (3.0, 0.6) if t == "W." else natural(t))],
        "BROKEN   chatterbox_turbo:builtin",
    ),
    "silent": (
        lambda: [FakeEngine(speak=lambda t: (1.0, 0.0))],
        "BROKEN   chatterbox_turbo:builtin",
    ),
    "no installed voice": (
        lambda: [FakeEngine(voice_ids=())],
        "NO DATA  chatterbox_turbo  no installed voice",
    ),
    "voices raise": (
        lambda: [BadVoices()],
        "BROKEN   chatterbox_turbo  voices() failed: OSError",
    ),
    "not an engine": (lambda: [NotAnEngine()], "BROKEN   chatterbox_turbo  "),
    "no engines": (lambda: [], "RESULT: no engine voice to test"),
}


@pytest.mark.parametrize("case", CASES)
def test_live_smoke_engines_always_exits_0_and_prints_verdict_lines(case, tmp_path, capsys):
    make_engines, expected = CASES[case]

    code, out = run(capsys, make_engines(), tmp_path)

    assert code == 0
    lines = verdict(out)
    assert any(line.startswith(expected) for line in lines), out
    assert lines[-1].startswith("RESULT: ")
    assert all(re.match(r"(HELD|BROKEN|NO DATA) +\S", line) for line in lines[:-1])


def test_a_runaway_unit_is_named_in_the_verdict(tmp_path, capsys):
    engine = FakeEngine(speak=lambda t: (3.0, 0.6) if t == "Multiple choice." else natural(t))

    _, out = run(capsys, [engine], tmp_path)

    (line,) = [line for line in verdict(out) if line.startswith("BROKEN")]
    assert line.endswith("fails: Multiple choice.")
    assert verdict(out)[-1] == "RESULT: 1 of 1 engine voices did not hold. Paste this whole output."


def test_a_crash_outside_any_engine_still_exits_0(tmp_path, capsys, monkeypatch):
    def broken_units():
        raise ValueError("fixture unreadable")

    monkeypatch.setattr(smoke, "short_units", broken_units)

    code, out = run(capsys, [FakeEngine()], tmp_path)

    assert code == 0
    assert verdict(out)[0] == "BROKEN   smoke  unexpected ValueError: fixture unreadable"


# --- which engines run by default ----------------------------------------------------------------


def test_default_engines_come_from_the_engine_modules(tmp_path, monkeypatch):
    settings = load_settings({"CLOUDYREADER_DATA_DIR": str(tmp_path)})
    for name in ENGINE_MODULES:
        monkeypatch.setitem(sys.modules, name, None)  # importing a None entry raises ImportError

    absent = smoke.load_engines(settings)

    assert [(a.key, a.reason) for a in absent] == [
        ("chatterbox_turbo", "engine module not in this tree"),
        ("qwen3_tts", "engine module not in this tree"),
    ]

    chatterbox = types.ModuleType(ENGINE_MODULES[0])
    chatterbox.supported = lambda: None  # type: ignore[attr-defined]
    chatterbox.ChatterboxTurboEngine = lambda s: ("engine for", s)  # type: ignore[attr-defined]
    qwen = types.ModuleType(ENGINE_MODULES[1])
    qwen.supported = lambda: "needs Apple Silicon"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, ENGINE_MODULES[0], chatterbox)
    monkeypatch.setitem(sys.modules, ENGINE_MODULES[1], qwen)

    made, held_back = smoke.load_engines(settings)

    assert made == ("engine for", settings)
    assert (held_back.key, held_back.reason) == ("qwen3_tts", "needs Apple Silicon")

    qwen.supported = lambda: None  # type: ignore[attr-defined]  # no class: it fails to start
    _, broken = smoke.load_engines(settings)
    assert (broken.key, broken.state) == ("qwen3_tts", "BROKEN")
    assert broken.reason.startswith("could not start: AttributeError")


def test_run_as_a_script_is_offline_and_exits_0(monkeypatch, capsys):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    for name in ENGINE_MODULES:
        monkeypatch.setitem(sys.modules, name, None)

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    assert exc.value.code == 0
    assert "NO DATA  chatterbox_turbo  engine module not in this tree" in capsys.readouterr().out
    assert os.environ["HF_HUB_OFFLINE"] == os.environ["TRANSFORMERS_OFFLINE"] == "1"
