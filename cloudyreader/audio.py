"""Non-blocking WAV playback through macOS `afplay`: no audio library, no device handling."""

from __future__ import annotations

import subprocess
import threading
from contextlib import suppress

from cloudyreader.models import Audio

AFPLAY = "/usr/bin/afplay"
_STOP_TIMEOUT_S = 2


class AudioError(RuntimeError):
    """afplay is missing or could not start."""


class AfplayPlayer:
    """AudioPlayer that runs `afplay` on the WAV: one clip at a time, replayable."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._last: Audio | None = None

    def play(self, audio: Audio) -> None:
        with self._lock:
            self._start(audio)

    def stop(self) -> None:
        with self._lock:
            self._end_clip()

    def replay(self) -> bool:
        with self._lock:
            if self._last is None:
                return False
            self._start(self._last)
            return True

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def _start(self, audio: Audio) -> None:
        path = audio.wav_path
        if not path.is_file():
            raise FileNotFoundError(f"WAV not found: {path}")
        self._end_clip()
        try:
            # Absolute, so a relative name starting with "-" can never read as an afplay option.
            self._proc = subprocess.Popen([AFPLAY, str(path.absolute())])
        except OSError as exc:
            raise AudioError(f"cannot run {AFPLAY}: {exc}") from exc
        self._last = audio

    def _end_clip(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            with suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=_STOP_TIMEOUT_S)
