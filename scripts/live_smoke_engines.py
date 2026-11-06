"""Engine smoke test on the installed weights. Run it yourself: `make smoke-engines`.

Each installed Chatterbox Turbo and Qwen3-TTS voice: the first call (model load), the 12 short units
of fixture 02 (said alone, by the repeat fallback, or failed), then three fixed sentences.

Lines give audio length, wall time, RTF and sample peak; each voice adds its peak RSS. No network,
no URL printed, files only in a temp dir. Always exits 0: read the verdict, not the exit status.
"""

from __future__ import annotations

import dataclasses
import importlib
import itertools
import os
import re
import resource
import sys
import tempfile
import time
import wave
from array import array
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloudyreader.config import Settings, load_settings
from cloudyreader.models import RenderOptions, Segment, SpokenScript, VoiceInfo
from cloudyreader.normalize import ScriptNormalizer
from cloudyreader.parser import parse

# tests/fixtures/questions/02-life-science-respiratory-respelling-mc.txt, word for word (a test
# pins it): its 12 segments are the header, category, format, stem, 4 letters and 4 choices.
FIXTURE_02 = (
    "1) LIFE SCIENCE Multiple Choice Which of the following is NOT part of the human respiratory\n"
    "system?\n"
    "W) Pharynx [FAR-ingks]\n"
    "X) Larynx [LAR-ingks]\n"
    "Y) Esophagus [i-SOF-uh-guhs]\n"
    "Z) Trachea [TRAY-kee-uh]\n"
    "ANSWER: Y) ESOPHAGUS\n"
)
# The third sentence twice: the paste's respellings as written (hyphenated), then joined up.
SENTENCES = (
    ("plain", "Which layer of the Earth lies directly beneath the crust?"),
    ("numbers", "A two point five kilogram cart accelerates at three meters per second squared."),
    (
        "hyphen",
        "The ih-sof-uh-gus moves food, troh-puh-nin binds calcium, oh-kuh-zah-kee fragments form.",
    ),
    ("joined", "The ihsofuhgus moves food, trohpuhnin binds calcium, ohkuhzahkee fragments form."),
)
WARMUP = "Ready."
ENGINE_MODULES = (
    ("chatterbox_turbo", "cloudyreader.engines.chatterbox_turbo", "ChatterboxTurboEngine"),
    ("qwen3_tts", "cloudyreader.engines.qwen3_tts", "Qwen3TtsEngine"),
)
# The engines' own rules (blueprint section 4): estimate max(1.0 s, characters / 14); a runaway
# reaches 1.9 x that; under 0.1 s nothing was said. Texts of 24+ characters may not run short.
CHARS_PER_S, MIN_EST_S, RUNAWAY, MIN_AUDIO_S, SHORT_CHARS = 14.0, 1.0, 1.9, 0.1, 24
SHORT = 0.25  # a long text under a quarter of its estimate lost words
SILENT_PEAK = 0.01
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")


@dataclass(frozen=True)
class Absent:
    """An engine that cannot run here, and why: NO DATA, or BROKEN when it failed to start."""

    key: str
    reason: str
    state: str = "NO DATA"


@dataclass(frozen=True)
class Render:
    label: str
    path: str  # alone, fallback, fail; ? when the engine shows no backend to watch
    tries: int | None
    audio_s: float
    wall_s: float
    peak: float
    problem: str | None

    def line(self) -> str:
        state = "BROKEN" if self.problem else "HELD"
        rtf = self.wall_s / self.audio_s if self.audio_s else 0.0
        text = (
            f"{state:<8} {self.label:<20} {self.path:<8} {self.audio_s:.2f} s audio, "
            f"{self.wall_s:.2f} s wall, RTF {rtf:.2f}, peak {self.peak:.2f}"
        )
        if self.tries is not None:
            text += f", {self.tries} {'try' if self.tries == 1 else 'tries'}"
        return f"{text}  {self.problem}" if self.problem else text


class Recorder:
    """Records the texts an engine's backend renders: a unit that needed the repeat fallback
    shows as a later call holding the first call's text two or more times."""

    def __init__(self, engine: Any) -> None:
        self.calls: list[str] = []
        self.active = False
        backend = getattr(engine, "backend", None)
        render = getattr(backend, "render", None)
        if not callable(render):
            return

        def recorded(text: str, *args: Any, **kwargs: Any) -> Any:
            self.calls.append(text)
            return render(text, *args, **kwargs)

        try:
            backend.render = recorded  # type: ignore[union-attr]
        except (AttributeError, TypeError):  # slots or a read-only attribute: watch nothing
            return
        self.active = True

    def path(self, start: int, failed: bool) -> tuple[str, int | None]:
        calls = self.calls[start:]
        if not self.active:
            return ("fail" if failed else "?"), None
        if failed:
            return "fail", len(calls)
        first = calls[0] if calls else ""
        repeated = first and any(call.count(first) >= 2 for call in calls[1:])
        return ("fallback" if repeated else "alone"), len(calls)


def redact(text: str) -> str:
    return _URL.sub("<url>", text)


def describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {redact(str(exc))}"


def label(text: str) -> str:
    return text if len(text) <= 20 else f"{text[:19]}…"


def short_units() -> tuple[Segment, ...]:
    """Fixture 02 as the app speaks it, each segment alone: no trailing pause to time."""
    script = ScriptNormalizer().to_script(parse(FIXTURE_02), {}, RenderOptions())
    return tuple(dataclasses.replace(segment, pause_after_ms=0) for segment in script.segments)


def check(text: str, seconds: float, peak: float) -> str | None:
    """Why a rendering of `text` did not hold (runaway, cut short, silent), or None."""
    est = max(MIN_EST_S, len(text) / CHARS_PER_S)
    if seconds >= RUNAWAY * est:
        return f"too long: {seconds:.2f} s, a runaway at {RUNAWAY * est:.2f} s"
    floor = MIN_AUDIO_S if len(text) < SHORT_CHARS else SHORT * est
    if seconds < floor:
        return f"too short: {seconds:.2f} s, expected about {est:.2f} s"
    if peak < SILENT_PEAK:
        return f"silent: peak {peak:.3f}"
    return None


def measure(path: Path) -> tuple[float, float]:
    """Seconds and sample peak (0 to 1 of full scale) of a 16-bit WAV."""
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit samples, got {wav.getsampwidth() * 8}-bit")
        rate, frames = wav.getframerate(), wav.getnframes()
        samples = array("h", wav.readframes(frames))
    if sys.byteorder == "big":
        samples.byteswap()
    return frames / rate, max(map(abs, samples), default=0) / 32768


def peak_rss_mb() -> int:
    """This process's peak resident set size: ru_maxrss counts bytes on macOS, KiB on Linux."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1 << 20) if sys.platform == "darwin" else peak / 1024)


def render(
    engine: Any, voice: VoiceInfo, name: str, segment: Segment, out: Path, recorder: Recorder
) -> Render:
    start, started = len(recorder.calls), time.perf_counter()
    try:
        engine.synthesize(SpokenScript((segment,)), voice, RenderOptions(), out)
        wall = time.perf_counter() - started
        seconds, peak = measure(out)
    except Exception as exc:  # one bad unit is a finding, not the end of the run
        path, tries = recorder.path(start, failed=True)
        wall = time.perf_counter() - started
        return Render(name, path, tries, 0.0, wall, 0.0, f"failed: {describe(exc)}")
    path, tries = recorder.path(start, failed=False)
    return Render(name, path, tries, seconds, wall, peak, check(segment.text, seconds, peak))


def smoke_voice(
    engine: Any,
    voice: VoiceInfo,
    units: Sequence[Segment],
    scratch: Path,
    names: Iterator[int],
    recorder: Recorder,
) -> str:
    """One voice from a cold model: renders every probe, prints each line, returns its verdict."""
    print(f"\n== {voice.key} ({voice.name}) ==", flush=True)

    def out() -> Path:
        return scratch / f"{next(names):03d}.wav"

    warm = render(engine, voice, "load", Segment(WARMUP), out(), recorder)
    if warm.problem:
        print(
            f"{'load':<8} first call failed after {warm.wall_s:.2f} s: {warm.problem}", flush=True
        )
    else:
        print(
            f"{'load':<8} first call (model load and {WARMUP!r}): {warm.wall_s:.2f} s", flush=True
        )
    probes = [(label(unit.text), unit) for unit in units]
    probes += [(name, Segment(text)) for name, text in SENTENCES]
    renders = []
    for name, segment in probes:
        renders.append(render(engine, voice, name, segment, out(), recorder))
        print(renders[-1].line(), flush=True)
    rss = peak_rss_mb()
    print(f"{'info':<8} peak RSS {rss:,} MB after this voice", flush=True)
    try:
        engine.close()  # so the next voice loads from cold and its first call is a real load
    except Exception as exc:
        print(f"{'info':<8} close() failed: {describe(exc)}", flush=True)
    shorts, sentences = renders[: len(units)], renders[len(units) :]
    fails = [r.label for r in (warm, *renders) if r.problem]
    fallbacks = sum(1 for r in shorts if r.path == "fallback" and not r.problem)
    audio = sum(r.audio_s for r in sentences)
    rtf = sum(r.wall_s for r in sentences) / audio if audio else 0.0
    by_fallback = f" ({fallbacks} by fallback)" if fallbacks else ""
    line = (
        f"{'BROKEN' if fails else 'HELD':<8} {voice.key}  "
        f"short units {sum(not r.problem for r in shorts)}/{len(shorts)}{by_fallback}, "
        f"sentences {sum(not r.problem for r in sentences)}/{len(sentences)}, "
        f"load {warm.wall_s:.1f} s, RTF {rtf:.2f}, peak RSS {rss:,} MB"
    )
    return f"{line}  fails: {', '.join(fails)}" if fails else line


def smoke_engine(
    engine: Any, units: Sequence[Segment], scratch: Path, names: Iterator[int]
) -> list[str]:
    """The verdict lines of one engine: one per installed voice, else one saying why none ran."""
    key = getattr(engine, "key", type(engine).__name__)
    if isinstance(engine, Absent):
        return [f"{engine.state:<8} {key}  {redact(engine.reason)}"]
    try:
        if not engine.available():
            return [f"{'NO DATA':<8} {key}  {redact(engine.unavailable_reason or 'unavailable')}"]
        try:
            voices = [voice for voice in engine.voices() if voice.installed]
        except Exception as exc:
            return [f"{'BROKEN':<8} {key}  voices() failed: {describe(exc)}"]
        if not voices:
            return [f"{'NO DATA':<8} {key}  no installed voice"]
        recorder = Recorder(engine)
        return [smoke_voice(engine, voice, units, scratch, names, recorder) for voice in voices]
    except Exception as exc:  # an engine that breaks the contract must not end the run
        return [f"{'BROKEN':<8} {key}  unexpected {describe(exc)}"]


def load_engines(settings: Settings) -> list[Any]:
    """Each engine from its module, or an Absent saying why it cannot run in this tree."""
    engines: list[Any] = []
    for key, module_name, class_name in ENGINE_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            engines.append(Absent(key, "engine module not in this tree"))
            continue
        try:
            reason = module.supported()
            engines.append(Absent(key, reason) if reason else getattr(module, class_name)(settings))
        except Exception as exc:
            engines.append(Absent(key, f"could not start: {describe(exc)}", "BROKEN"))
    return engines


def summary(lines: Sequence[str]) -> str:
    tested = [line for line in lines if not line.startswith("NO DATA")]
    bad = sum(1 for line in tested if line.startswith("BROKEN"))
    if not tested:
        return "RESULT: no engine voice to test. Install one first: make pin-engine ENGINE=<name>"
    if not bad:
        return "RESULT: every engine voice held."
    return f"RESULT: {bad} of {len(tested)} engine voices did not hold. Paste this whole output."


def main(*, engines: Sequence[Any] | None = None, settings: Settings | None = None) -> int:
    print(
        "cloudyreader engine smoke: installed weights only, renders into a temp dir; "
        "no network call, no URL or host printed"
    )
    lines: list[str] = []
    try:
        units = short_units()
        if engines is None:
            # The engines guard their own loads; these keep any stray Hugging Face call off too.
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            engines = load_engines(dataclasses.replace(settings or load_settings(), offline=True))
        with tempfile.TemporaryDirectory(
            prefix="cloudyreader-smoke-engines-", ignore_cleanup_errors=True
        ) as tmp:
            names = itertools.count()
            for engine in engines:
                lines += smoke_engine(engine, units, Path(tmp), names)
    except Exception as exc:  # always exit 0: report it in the verdict instead
        lines.append(f"{'BROKEN':<8} smoke  unexpected {describe(exc)}")
    print("\n== verdict ==")
    print("\n".join([*lines, summary(lines)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
