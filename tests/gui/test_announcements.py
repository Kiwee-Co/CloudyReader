"""Status announcements for VoiceOver (behavior fix B): errors assertive, warnings and the download
outcome polite, every other message silent; the announced text is the status message itself."""

import threading

import pytest
from PySide6.QtGui import QAccessible

from cloudyreader.gui.fake_service import FAKE_VOICES, FakeReaderService
from cloudyreader.prefetch import PrefetchResult
from cloudyreader.rotation import RotationMode

ASSERTIVE = QAccessible.AnnouncementPoliteness.Assertive
POLITE = QAccessible.AnnouncementPoliteness.Polite
ALAN = "piper:en_GB-alan-medium"  # the one male voice among the fakes
PARTIAL = "Some voices could not be downloaded. They are tried again at the next start."
FALLBACK = "No installed voice matches “Men only”; using the selected voice."


@pytest.fixture
def heard(monkeypatch):
    """Every announcement the window posts, as (text, politeness)."""
    events: list[tuple[str, QAccessible.AnnouncementPoliteness]] = []

    def spy(event) -> None:
        if event.type() == QAccessible.Event.Announcement:
            events.append((event.message(), event.politeness()))

    monkeypatch.setattr(QAccessible, "updateAccessibility", spy)
    return events


def status(window) -> str:
    return window.statusBar().currentMessage()


def speak(qtbot, window, signal="reading_played") -> None:
    window.question_edit.setPlainText("What is H2O?")
    with qtbot.waitSignal(getattr(window, signal), timeout=5000):
        window.speak_button.click()


def finish_download(qtbot, make_window, result: PrefetchResult):
    gate = threading.Event()
    window = make_window(service=FakeReaderService(prefetch_gate=gate, prefetch_result=result))
    with qtbot.waitSignal(window.prefetch_finished, timeout=5000):
        gate.set()
    return window


def test_an_error_is_announced_assertively(qtbot, make_window, heard):
    window = make_window(service=FakeReaderService(error=RuntimeError("voice file missing")))
    heard.clear()

    speak(qtbot, window, "error_occurred")

    assert heard == [(status(window), ASSERTIVE)]
    assert status(window) == "Error: voice file missing"


def test_the_same_error_twice_is_announced_twice(qtbot, make_window, heard):
    window = make_window(service=FakeReaderService(error=RuntimeError("voice file missing")))
    heard.clear()

    speak(qtbot, window, "error_occurred")
    speak(qtbot, window, "error_occurred")

    assert heard == [(status(window), ASSERTIVE)] * 2


def test_a_reading_warning_is_announced_politely_once(qtbot, make_window, heard):
    window = make_window(service=FakeReaderService(warnings=("no pronunciation for 'xyz'",)))
    heard.clear()

    speak(qtbot, window)

    assert heard == [(status(window), POLITE)]
    assert status(window) == "Warning: no pronunciation for 'xyz'"


def test_the_rotation_fallback_is_announced_politely_once(qtbot, make_window, heard):
    window = make_window(
        service=FakeReaderService(voices=[v for v in FAKE_VOICES if v.key != ALAN])
    )
    combo = window.rotation_combo
    combo.setCurrentIndex(combo.findData(str(RotationMode.MEN_SHUFFLE)))
    heard.clear()

    speak(qtbot, window)  # it shows while preparing and stays: one announcement

    assert heard == [(FALLBACK, POLITE)]
    assert status(window) == FALLBACK


def test_a_partial_download_is_announced_politely(qtbot, make_window, heard):
    window = finish_download(qtbot, make_window, PrefetchResult("partial", failed=("a.onnx",)))

    assert heard == [(PARTIAL, POLITE)]
    assert status(window) == PARTIAL


def test_a_complete_download_is_announced_politely(qtbot, make_window, heard):
    window = finish_download(qtbot, make_window, PrefetchResult("complete", files=1))

    assert heard == [("Voices downloaded.", POLITE)]
    assert status(window) == "Voices downloaded."


def test_playing_and_stopped_stay_silent(qtbot, window, heard):
    speak(qtbot, window)
    window.stop_button.click()

    assert status(window) == "Stopped."
    assert heard == []


def test_a_missing_voice_at_start_is_announced_politely(make_window, heard):
    window = make_window(service=FakeReaderService(voices=[]))

    assert heard == [("No voice is installed.", POLITE)]
    assert status(window) == "No voice is installed."
