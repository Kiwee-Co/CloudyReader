"""macOS system voices through /usr/bin/say: the voices installed on this Mac, nothing to download.

MacosEngine lists the English voices `say --voice=?` prints, minus the novelty voices, and reads a
whole script in one `say` run: the text goes in on stdin with each pause as an embedded
`[[slnc ms]]` command, and a 24 kHz 16-bit mono WAV comes out in a private temporary folder. The
tier is part of the listed name ("Ava (Premium)", "Samantha (Enhanced)"); any other is Standard.
"""

from __future__ import annotations

import logging
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloudyreader.engines.mlxkit import (
    SAMPLE_RATE,
    EngineError,
    EngineUnavailable,
    EngineWarnings,
    speakable,
)
from cloudyreader.models import Audio, RenderOptions, SpokenScript, VoiceInfo

log = logging.getLogger(__name__)

KEY = "macos"
TITLE = "macOS"
SAY = "/usr/bin/say"
# The child's whole environment: no proxy variable reaches it, and say reads UTF-8 without a locale.
ENV = {"PATH": "/usr/bin:/bin"}
DATA_FORMAT = f"LEI16@{SAMPLE_RATE}"
DEFAULT_WPM = 175  # say's rate without --rate: Samantha, Daniel and Eddy measure the same at 175
SPEED_RANGE = (0.5, 2.0)
LIST_TIMEOUT_S = 15.0
SYNTH_TIMEOUT_S = 30.0  # plus SYNTH_S_PER_CHAR per character: say renders about 20x real time
SYNTH_S_PER_CHAR = 0.01
NOVELTY = frozenset(
    {
        "Albert",
        "Bad News",
        "Bahh",
        "Bells",
        "Boing",
        "Bubbles",
        "Cellos",
        "Good News",
        "Jester",
        "Organ",
        "Superstar",
        "Trinoids",
        "Whisper",
        "Wobble",
        "Zarvox",
    }
)
RESPELLING_STYLE = "hyphen"
# Bump when the text prep or the WAV handling changes: cached WAVs of older code are not reused.
_RENDER_REVISION = 1
# `<name> <locale> # <sample>`: the locale is the last word before the first " #".
_LINE = re.compile(r"(?P<name>\S.*?)\s+(?P<locale>[a-z]{2,3}(?:[_-][A-Za-z0-9]+)*)\s+#.*")
_TIER = re.compile(r" \((Enhanced|Premium)\)$")
# say runs [[...]] as a command; pasted text keeps single brackets, which it reads as nothing.
_OPEN, _CLOSE = re.compile(r"\[{2,}"), re.compile(r"\]{2,}")
_ENDS = ".!?:;,"
_CLOSERS = "\"')]”’"


@dataclass(frozen=True)
class SystemVoice:
    """One line of `say --voice=?`: the name say takes back, and the voice's locale."""

    name: str  # "Samantha", "Ava (Premium)", "Eddy (English (US))"
    locale: str  # "en_US", "it_IT", "ar_001"

    @property
    def base(self) -> str:
        """The voice's own name, without its tier or language: "Ava", "Eddy"."""
        return self.name.partition(" (")[0]

    @property
    def tier(self) -> str:
        match = _TIER.search(self.name)
        return match.group(1) if match else "Standard"

    @property
    def language(self) -> str:
        return self.locale.replace("_", "-")

    @property
    def offered(self) -> bool:
        """English and not a novelty voice: a voice the Voice menu lists."""
        return self.language.partition("-")[0].lower() == "en" and self.base not in NOVELTY


def parse_listing(text: str) -> list[SystemVoice]:
    """The voices of a `say --voice=?` listing, in its order; a line of another shape is skipped."""
    found = (_LINE.fullmatch(line) for line in text.splitlines())
    return [SystemVoice(m["name"], m["locale"]) for m in found if m]


def _hard_word_warning(words: Sequence[str]) -> str:
    named = ", ".join(words[:3]) + (f" and {len(words) - 3} more" if len(words) > 3 else "")
    count = f"{len(words)} hard words use" if len(words) > 1 else "1 hard word uses"
    return f"{TITLE} cannot take IPA: {count} the printed spelling ({named})"


def _finish(text: str) -> str:
    """End on punctuation, so each segment is its own sentence, as it is in the other engines."""
    core = text.rstrip(_CLOSERS)
    return text if core and core[-1] in _ENDS else text + "."


def say_text(script: SpokenScript) -> tuple[str, list[str]]:
    """The text say reads from stdin, each pause an `[[slnc ms]]` after its segment, plus the
    warnings the text prep implies, in first-seen order."""
    parts: list[str] = []
    hard: list[str] = []
    lost: list[str] = []
    for segment in script.segments:
        spoken = speakable(segment, style=RESPELLING_STYLE)
        hard += [w for w in spoken.unspoken if w not in hard]
        lost += [w for w in spoken.missing if w not in lost]
        text = " ".join(_CLOSE.sub("]", _OPEN.sub("[", spoken.text)).split())
        if text:
            parts.append(_finish(text))
        if segment.pause_after_ms > 0:
            parts.append(f"[[slnc {segment.pause_after_ms}]]")
    warnings = [_hard_word_warning(hard)] if hard else []
    warnings += [f"{TITLE}: override for {w!r} not found in the segment text" for w in lost]
    return " ".join(parts), warnings


def _voice_info(voice: SystemVoice) -> VoiceInfo:
    return VoiceInfo(
        key=f"{KEY}:{voice.name}",
        engine=KEY,
        name=voice.base,
        language=voice.language,
        quality=voice.tier,
        num_speakers=1,
        installed=True,
    )


def _read_speech(path: Path, name: str) -> bytes:
    """The frames say wrote: mono 16-bit at SAMPLE_RATE, and not all silence."""
    try:
        with wave.open(str(path), "rb") as wav:
            shape = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate())
            frames = wav.readframes(wav.getnframes())
    except (OSError, EOFError, wave.Error) as exc:
        raise EngineError(f"say wrote no readable audio for {name}: {exc}") from exc
    if shape != (1, 2, SAMPLE_RATE):
        channels, width, rate = shape
        raise EngineError(
            f"say wrote {channels} channel(s), {8 * width}-bit, {rate} Hz for {name}; "
            f"expected mono 16-bit {SAMPLE_RATE} Hz"
        )
    if not frames.strip(b"\x00"):
        raise EngineError(f"the {TITLE} voice {name} produced no sound")
    return frames


class MacosEngine:
    """TtsEngine over the system voices: one `say` lists them, one `say` per reading speaks."""

    key = KEY

    def __init__(
        self, *, say: str | os.PathLike[str] | None = None, popen: Callable[..., Any] | None = None
    ) -> None:
        self._say = os.fspath(say if say is not None else SAY)
        self._popen = popen if popen is not None else subprocess.Popen  # tests inject a fake say
        self.version = f"macos-say@{platform.mac_ver()[0] or 'unknown'}+r{_RENDER_REVISION}"
        self.unavailable_reason: str | None = None
        self._warnings = EngineWarnings()
        self._lock = threading.Lock()  # the listing runs once
        self._listed: tuple[SystemVoice, ...] | None = None
        self._children_lock = threading.Lock()
        self._children: dict[Any, bool] = {}  # running say -> cancel() killed it

    # --- availability -------------------------------------------------------------------------

    def available(self) -> bool:
        self.unavailable_reason = self._reason()
        return self.unavailable_reason is None

    def _reason(self) -> str | None:
        if sys.platform != "darwin":
            return f"{TITLE} voices need macOS"
        if not os.access(self._say, os.X_OK):
            return f"{self._say} not found"
        return None

    # --- voices -------------------------------------------------------------------------------

    def voices(self) -> list[VoiceInfo]:
        """The offered voices, listed once per engine: a voice installed later shows at restart."""
        return [_voice_info(voice) for voice in self._offered()]

    def _offered(self) -> tuple[SystemVoice, ...]:
        with self._lock:
            if self._listed is None:
                self._listed = ()  # never listed again on failure: each reading would wait for it
                listing = self._run([self._say, "--voice=?"], timeout=LIST_TIMEOUT_S)
                found = parse_listing(listing.decode("utf-8", "replace"))
                self._listed = tuple(voice for voice in found if voice.offered)
            return self._listed

    def _voice_name(self, voice: VoiceInfo) -> str:
        """The say name of an offered voice. Any other name is refused: say would read it with
        the default voice instead."""
        engine, _, name = voice.key.partition(":")
        if voice.engine != KEY or engine != KEY:
            raise ValueError(f"not a {TITLE} voice: {voice.key!r}")
        if not self.available():
            raise EngineUnavailable(self.unavailable_reason or f"{TITLE} voices are unavailable")
        if name not in {offered.name for offered in self._offered()}:
            raise ValueError(f"not a {TITLE} voice: {voice.key!r}")
        return name

    # --- text prep ----------------------------------------------------------------------------

    def script_warnings(self, script: SpokenScript, voice: VoiceInfo) -> tuple[str, ...]:
        """What synthesis will paper over; the same strings as `last_warnings`."""
        return tuple(say_text(script)[1])

    @property
    def last_warnings(self) -> list[str]:
        """Warnings of the calling thread's latest `synthesize`."""
        return self._warnings.snapshot()

    # --- synthesis ----------------------------------------------------------------------------

    def _speed(self, speed: float) -> float:
        if not (math.isfinite(speed) and speed > 0):
            raise ValueError(f"speed must be a positive number, got {speed!r}")
        low, high = SPEED_RANGE
        clamped = min(max(speed, low), high)
        if clamped != speed:
            self._warnings.add(f"{TITLE}: speed {speed:g} clamped to {clamped:g}")
        return clamped

    def synthesize(
        self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions, out_wav: Path
    ) -> Audio:
        """Write the script as a 24 kHz 16-bit mono WAV, read in one say run."""
        self._warnings.reset()
        name = self._voice_name(voice)
        speed = self._speed(opts.speed)
        if opts.speaker_id is not None:
            self._warnings.add(
                f"{TITLE}: speaker {opts.speaker_id} ignored; each voice has one speaker"
            )
        text, warnings = say_text(script)
        for message in warnings:
            self._warnings.add(message)
        # At 1.0 say keeps the voice's own rate, which follows the user's speaking-rate setting.
        rate = [] if speed == 1.0 else [f"--rate={round(DEFAULT_WPM * speed)}"]
        folder = Path(tempfile.mkdtemp(prefix="cloudyreader-say-"))  # mode 0700
        try:
            speech = folder / "speech.wav"
            argv = [
                self._say,
                f"--voice={name}",
                f"--output-file={speech}",
                "--file-format=WAVE",
                f"--data-format={DATA_FORMAT}",
                *rate,
                "--input-file=-",
            ]
            timeout = SYNTH_TIMEOUT_S + SYNTH_S_PER_CHAR * len(text)
            self._run(argv, timeout=timeout, data=text.encode("utf-8"))
            frames = _read_speech(speech, name)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        with wave.open(str(out_wav), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(frames)
        return Audio(out_wav, SAMPLE_RATE, len(frames) / 2 / SAMPLE_RATE, cache_hit=False)

    def _run(self, argv: list[str], *, timeout: float, data: bytes = b"") -> bytes:
        """Run say from an argv list (never a shell) in ENV; its stdout. A timeout or cancel()
        kills it."""
        try:
            proc = self._popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(ENV),
            )
        except OSError as exc:
            raise EngineUnavailable(f"cannot run {argv[0]}: {exc}") from exc
        with self._children_lock:
            self._children[proc] = False
        try:
            out, err = proc.communicate(data, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise EngineError(f"{TITLE} speech took longer than {timeout:.0f} s") from None
        finally:
            with self._children_lock:
                cancelled = self._children.pop(proc, False)
            if proc.returncode is None:  # an exception left it running
                proc.kill()
                proc.wait()
        if cancelled:
            raise EngineError(f"{TITLE} speech was cancelled")
        if proc.returncode != 0:
            detail = err.decode("utf-8", "replace").strip().splitlines()
            reason = f": {detail[0][:200]}" if detail else ""
            raise EngineError(f"say failed (exit {proc.returncode}){reason}")
        return out

    def cancel(self) -> None:
        """Kill every say this engine runs; the call that started it raises EngineError."""
        with self._children_lock:
            running = list(self._children)
            self._children.update(dict.fromkeys(running, True))
        for proc in running:
            with suppress(OSError):
                proc.kill()
