"""Fakes for GUI development and tests: no synthesis, no network, no audio device."""

from __future__ import annotations

import math
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cloudyreader.models import Audio, Reading, RenderOptions, Segment, SpokenScript, VoiceInfo

FAKE_VOICES: tuple[VoiceInfo, ...] = (
    VoiceInfo("piper:en_US-lessac-medium", "piper", "Lessac", "en-US", "medium", 1, True),
    VoiceInfo("piper:en_US-amy-medium", "piper", "Amy", "en-US", "medium", 1, True),
    VoiceInfo("piper:en_GB-alan-medium", "piper", "Alan", "en-GB", "medium", 1, True),
    VoiceInfo("piper:en_US-libritts-high", "piper", "LibriTTS", "en-US", "high", 904, True),
    VoiceInfo("kokoro:af_heart", "kokoro", "Heart", "en-US", "high", 1, True),
    VoiceInfo("kokoro:am_michael", "kokoro", "Michael", "en-US", "high", 1, False),
)

_FAKE_WAV = Path(tempfile.gettempdir()) / "cloudyreader-fake.wav"  # never opened
_GATE_TIMEOUT_S = 10.0  # a forgotten gate must fail a test, not hang it


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
        self.calls: list[PrepareCall] = []
        self.voices_threads: list[threading.Thread] = []

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
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        script = SpokenScript(tuple(Segment(text=line) for line in lines))
        audio = Audio(_FAKE_WAV, 22_050, self.duration_s, cache_hit=False)
        return Reading((), script, (), {}, audio, warnings=self.warnings)


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
