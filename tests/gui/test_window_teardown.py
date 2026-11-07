"""Closing the window as a worker job ends must not hang: the app's quit path.

Deleting a QThreadPool waits for its running job while the deleting thread holds the GIL, which
a Python job needs to finish. The probe runs in a child process, so a hang fails this test after
a timeout instead of stopping the suite.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

PROBE = Path(__file__).with_name("window_teardown_probe.py")
ROOT = Path(__file__).resolve().parents[2]
ROUNDS = 3
TIMEOUT_S = 20
HIDE_WAIT_S = 2  # how long the held job waits for the window to go before it gives up


@pytest.mark.slow
def test_closing_as_a_reading_ends_never_hangs(tmp_path):
    command = [sys.executable, "-I", "-B", str(PROBE), str(ROOT), str(tmp_path), str(ROUNDS)]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        pytest.fail(f"deleting the window deadlocked: no exit in {TIMEOUT_S} s")

    assert (done.returncode, done.stdout.strip()) == (0, "ok"), done.stderr


def test_closing_hides_the_window_before_it_waits_for_the_worker(qtbot, window, service):
    gate = service.gate = threading.Event()
    window.question_edit.setPlainText("q")
    window.speak_button.click()
    qtbot.waitUntil(lambda: bool(service.calls))  # the reading waits at its gate
    hidden_while_held = []

    def release() -> None:  # its own thread: close() blocks this one until the job ends
        deadline = time.monotonic() + HIDE_WAIT_S
        while window.isVisible() and time.monotonic() < deadline:
            time.sleep(0.01)
        hidden_while_held.append(not window.isVisible())
        gate.set()

    releaser = threading.Thread(target=release)
    releaser.start()
    window.close()
    releaser.join(TIMEOUT_S)

    assert hidden_while_held == [True]  # a long first-use reading must not freeze the window
