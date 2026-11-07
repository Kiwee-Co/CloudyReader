import os

import pytest

# Headless Qt for every test: no window ever opens. Override from the shell if needed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _no_real_say(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test runs the real /usr/bin/say: the macOS engine finds none unless a test passes one."""
    monkeypatch.setattr("cloudyreader.engines.macos.SAY", "/nonexistent/say")
