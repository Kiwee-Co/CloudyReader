"""Fakes for GUI development and tests: no synthesis, no network, no audio device."""

from __future__ import annotations

import math
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from cloudyreader.models import Audio, Reading, RenderOptions, Segment, SpokenScript, VoiceInfo
from cloudyreader.prefetch import PrefetchProgress, PrefetchResult

FAKE_VOICES: tuple[VoiceInfo, ...] = (
    VoiceInfo(
        "piper:en_US-lessac-medium",
        "piper",
        "Lessac",
        "en-US",
        "medium",
        1,
        True,
        precision="medium",
    ),
    VoiceInfo(
        "piper:en_US-amy-medium", "piper", "Amy", "en-US", "medium", 1, True, precision="medium"
    ),
    VoiceInfo(
        "piper:en_GB-alan-medium", "piper", "Alan", "en-GB", "medium", 1, True, precision="medium"
    ),
    VoiceInfo(
        "piper:en_US-libritts-high",
        "piper",
        "LibriTTS",
        "en-US",
        "high",
        904,
        True,
        precision="high",
    ),
    VoiceInfo("kokoro:af_heart", "kokoro", "Heart", "en-US", "A", 1, True, precision="bf16"),
    VoiceInfo("kokoro:am_michael", "kokoro", "Michael", "en-US", "C+", 1, False, precision="bf16"),
)
# The engine rows a Mac with Apple Silicon lists: one dimmed row that says why, two ready voices.
ENGINE_FAKE_VOICES: tuple[VoiceInfo, ...] = (
    *FAKE_VOICES,
    VoiceInfo(
        "chatterbox_turbo:builtin",
        "chatterbox_turbo",
        "Chatterbox Turbo (built-in)",
        "en",
        "4-bit",
        1,
        False,
        reason="not downloaded yet",
        precision="4-bit",
    ),
    VoiceInfo(
        "qwen3_tts:ryan", "qwen3_tts", "Ryan (male)", "en", "8-bit", 1, True, precision="8-bit"
    ),
    VoiceInfo(
        "qwen3_tts:aiden", "qwen3_tts", "Aiden (male)", "en-US", "8-bit", 1, True, precision="8-bit"
    ),
)
# The macOS system voices: nothing to download, a tier for a precision, listed after every engine.
MACOS_FAKE_VOICES: tuple[VoiceInfo, ...] = (
    VoiceInfo("macos:Daniel", "macos", "Daniel", "en-GB", "Premium", 1, True, precision="Premium"),
    VoiceInfo(
        "macos:Samantha", "macos", "Samantha", "en-US", "Enhanced", 1, True, precision="Enhanced"
    ),
    VoiceInfo("macos:Alex", "macos", "Alex", "en-US", "Standard", 1, True, precision="Standard"),
)

_FAKE_WAV = Path(tempfile.gettempdir()) / "cloudyreader-fake.wav"  # never opened
_GATE_TIMEOUT_S = 10.0  # a forgotten gate must fail a test, not hang it
_CANCEL_POLL_S = 0.01  # a held prefetch checks its cancel event this often


@dataclass(frozen=True)
class PrepareCall:
    raw: str
    voice_key: str
    opts: RenderOptions
    thread: threading.Thread


class FakeReaderService:
    """ReaderService that echoes the paste back as a script. Knobs are plain attributes."""

    def __init__(
        self,
        voices: Sequence[VoiceInfo] = FAKE_VOICES,
        *,
        delay_s: float = 0.0,
        duration_s: float = 2.0,
        warnings: Sequence[str] = (),
        error: Exception | None = None,
        gate: threading.Event | None = None,
        voices_delay_s: float = 0.0,
        voices_error: Exception | None = None,
        voices_gate: threading.Event | None = None,
        prefetch_result: PrefetchResult | None = None,
        prefetch_events: Sequence[PrefetchProgress] = (),
        prefetch_gate: threading.Event | None = None,
        prefetch_delay_s: float = 0.0,
        prefetch_error: Exception | None = None,
        prefetch_installs: Sequence[str] = (),
        load_hint: str | None = None,
    ) -> None:
        self.voice_list = list(voices)
        self.delay_s = delay_s
        self.duration_s = duration_s
        self.warnings = tuple(warnings)
        self.error = error
        self.gate = gate  # prepare() blocks until set: lets a test hold the worker mid-flight
        self.voices_delay_s = voices_delay_s
        self.voices_error = voices_error
        self.voices_gate = voices_gate  # the same hold for voices(), like a slow model hash
        # The download hook exists only once a result or an error is set: inert by default.
        self.prefetch_result = prefetch_result
        self.prefetch_events = tuple(prefetch_events)
        self.prefetch_gate = prefetch_gate  # holds the run after its first event (or at start)
        self.prefetch_delay_s = prefetch_delay_s
        self.prefetch_error = prefetch_error
        self.prefetch_installs = tuple(prefetch_installs)  # keys installed as the run starts
        self.load_hint_text = load_hint  # said until prepare() succeeds once with that voice
        self.load_hint_calls: list[tuple[str, threading.Thread]] = []
        self._prepared: set[str] = set()
        self.calls: list[PrepareCall] = []
        self.voices_threads: list[threading.Thread] = []
        self.prefetch_threads: list[threading.Thread] = []

    def voices(self) -> list[VoiceInfo]:
        self.voices_threads.append(threading.current_thread())
        if self.voices_gate is not None and not self.voices_gate.wait(_GATE_TIMEOUT_S):
            raise TimeoutError("fake voices gate was never released")
        time.sleep(self.voices_delay_s)
        if self.voices_error is not None:
            raise self.voices_error
        return list(self.voice_list)

    def prepare(self, raw: str, voice_key: str, opts: RenderOptions) -> Reading:
        self.calls.append(PrepareCall(raw, voice_key, opts, threading.current_thread()))
        if self.gate is not None and not self.gate.wait(_GATE_TIMEOUT_S):
            raise TimeoutError("fake gate was never released")
        time.sleep(self.delay_s)
        if self.error is not None:
            raise self.error
        self._prepared.add(voice_key)  # its model is resident now
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        script = SpokenScript(tuple(Segment(text=line) for line in lines))
        audio = Audio(_FAKE_WAV, 22_050, self.duration_s, cache_hit=False)
        return Reading((), script, (), {}, audio, warnings=self.warnings)

    @property
    def load_hint(self) -> Callable[[str], str | None] | None:
        """The first-use hint hook, or None (the default) like a service that has none."""
        return None if self.load_hint_text is None else self._load_hint

    def _load_hint(self, voice_key: str) -> str | None:
        self.load_hint_calls.append((voice_key, threading.current_thread()))
        return None if voice_key in self._prepared else self.load_hint_text

    @property
    def prefetch_voices(self) -> Callable[..., PrefetchResult] | None:
        """The download hook, or None (the default) like a service that has none."""
        if self.prefetch_result is None and self.prefetch_error is None:
            return None
        return self._prefetch

    def _prefetch(
        self,
        progress: Callable[[PrefetchProgress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> PrefetchResult:
        self.prefetch_threads.append(threading.current_thread())
        time.sleep(self.prefetch_delay_s)
        if self.prefetch_error is not None:
            raise self.prefetch_error
        cancelled = PrefetchResult("cancelled")
        if cancel is not None and cancel.is_set():
            return cancelled
        installs = set(self.prefetch_installs)  # files land before their progress event
        self.voice_list = [
            replace(v, installed=True) if v.key in installs else v for v in self.voice_list
        ]
        for index, event in enumerate(self.prefetch_events or (None,)):
            if cancel is not None and cancel.is_set():
                return cancelled
            if event is not None and progress is not None:
                progress(event)
            if index == 0 and not self._hold(cancel):
                return cancelled
        return self.prefetch_result or PrefetchResult("nothing")

    def _hold(self, cancel: threading.Event | None) -> bool:
        """Wait at prefetch_gate. False when cancel comes first."""
        if self.prefetch_gate is None:
            return True
        deadline = time.monotonic() + _GATE_TIMEOUT_S
        while not self.prefetch_gate.wait(_CANCEL_POLL_S):
            if cancel is not None and cancel.is_set():
                return False
            if time.monotonic() > deadline:
                raise TimeoutError("fake prefetch gate was never released")
        return True


class FakePlayer:
    """AudioPlayer that records calls. Playback lasts until finish() unless real_time is set."""

    def __init__(self, *, real_time: bool = False, error: Exception | None = None) -> None:
        self.played: list[Audio] = []
        self.play_threads: list[threading.Thread] = []
        self.stop_calls = 0
        self.replay_calls = 0
        self.error = error
        self._real_time = real_time
        self._last: Audio | None = None
        self._playing = False
        self._deadline = math.inf

    def play(self, audio: Audio) -> None:
        if self.error is not None:
            raise self.error
        self.played.append(audio)
        self.play_threads.append(threading.current_thread())
        self._start(audio)

    def stop(self) -> None:
        self.stop_calls += 1
        self._playing = False

    def replay(self) -> bool:
        self.replay_calls += 1
        if self.error is not None:
            raise self.error
        if self._last is None:
            return False
        self._start(self._last)
        return True

    @property
    def is_playing(self) -> bool:
        return self._playing and time.monotonic() < self._deadline

    def finish(self) -> None:
        """Simulate playback reaching the end of the audio."""
        self._playing = False

    def _start(self, audio: Audio) -> None:
        self._last = audio
        self._playing = True
        self._deadline = time.monotonic() + audio.duration_s if self._real_time else math.inf


class FakeClipboard:
    """Stands in for QClipboard so tests never touch the real pasteboard."""

    def __init__(self, text: str = "") -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text


def main() -> int:  # pragma: no cover - manual dev run
    from cloudyreader.gui.app import run

    return run(FakeReaderService(delay_s=1.0, voices_delay_s=1.5), FakePlayer(real_time=True))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
