"""Live Spoken script: the panel's text follows the question box, built off the UI thread.

Each change restarts a single-shot timer. When the box rests, one job builds the script on the
window's one-worker pool. A request number makes the latest change win: an older job that has not
started is skipped, and an older result is dropped.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, SignalInstance

from cloudyreader.models import RenderOptions

log = logging.getLogger(__name__)

_QUEUED = Qt.ConnectionType.QueuedConnection
# The normalizer is quadratic in one long token: a bigger paste would hold the worker for minutes,
# and Speak and Quit wait behind it. Past this the panel shows the blank result instead.
MAX_PREVIEW_CHARS = 20_000


class _Latest:
    """The newest request number: bumped on the UI thread, read on the worker (an int is atomic)."""

    number = 0


class _Built(QObject):
    done = Signal(int, str)  # request number, script text


class _Preview(QRunnable):
    """Builds one script on the worker and reports it by queued signal."""

    def __init__(
        self,
        latest: _Latest,
        compute: Callable[[str, RenderOptions], str],
        raw: str,
        opts: RenderOptions,
        done: SignalInstance,
    ) -> None:
        super().__init__()
        self._latest = latest
        self._number = latest.number  # the request this job answers
        self._compute = compute
        self._raw = raw
        self._opts = opts
        self._done = done

    def run(self) -> None:
        if self._number != self._latest.number:
            return  # a newer change came while this job waited behind another: nobody will look
        try:
            text = self._compute(self._raw, self._opts)
        except Exception:  # bad input must empty the panel, never reach the user
            log.warning("spoken script preview failed", exc_info=True)
            text = ""
        try:
            self._done.emit(self._number, text)
        except RuntimeError:  # the window, and the signals object with it, is already gone
            log.debug("script preview dropped: the window is gone")


class LiveScript(QObject):
    """Rebuilds the Spoken script from the question box, off the UI thread.

    `compute(raw, opts)` returns the panel text and runs on `pool`, the window's one-worker pool,
    so it never overlaps the service's other calls. Create this after the pool: the pool is then
    destroyed first and waits for a running job. Call `schedule` and `cancel` on the UI thread.
    """

    script_ready = Signal(str)  # the panel's text; "" shows its placeholder

    def __init__(
        self,
        compute: Callable[[str, RenderOptions], str],
        pool: QThreadPool,
        *,
        debounce_ms: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._compute = compute
        self._pool = pool
        self._latest = _Latest()
        self._request = ("", RenderOptions())  # the latest change, read when the timer fires
        self._built = _Built(self)
        self._built.done.connect(self._deliver, _QUEUED)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self._fire)

    def schedule(self, raw: str, opts: RenderOptions) -> None:
        """The question or an option changed: preview once it has rested for the debounce."""
        self._latest.number += 1
        self._request = (raw, opts)
        self._timer.start()  # a running timer restarts, so a burst ends in one job

    def cancel(self) -> None:
        """Drop the waiting change and any result on its way: Speak's script owns the panel."""
        self._latest.number += 1
        self._timer.stop()

    def _fire(self) -> None:
        raw, opts = self._request
        if len(raw) > MAX_PREVIEW_CHARS or not raw.strip():
            self.script_ready.emit("")  # nothing to build, or too much: the placeholder shows
            return
        self._pool.start(_Preview(self._latest, self._compute, raw, opts, self._built.done))

    def _deliver(self, number: int, text: str) -> None:
        if number == self._latest.number:
            self.script_ready.emit(text)
