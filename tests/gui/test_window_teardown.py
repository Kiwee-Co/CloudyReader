"""Closing the window as a worker job ends must not hang: the app's quit path.

Deleting a QThreadPool waits for its running job while the deleting thread holds the GIL, which
a Python job needs to finish. The probe runs in a child process, so a hang fails this test after
a timeout instead of stopping the suite.
"""

import subprocess
import sys
from pathlib import Path

import pytest

PROBE = Path(__file__).with_name("window_teardown_probe.py")
ROOT = Path(__file__).resolve().parents[2]
ROUNDS = 3
TIMEOUT_S = 20


@pytest.mark.slow
def test_closing_as_a_reading_ends_never_hangs(tmp_path):
    command = [sys.executable, "-I", "-B", str(PROBE), str(ROOT), str(tmp_path), str(ROUNDS)]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        pytest.fail(f"deleting the window deadlocked: no exit in {TIMEOUT_S} s")

    assert (done.returncode, done.stdout.strip()) == (0, "ok"), done.stderr
