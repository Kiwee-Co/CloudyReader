"""The Spoken script follows the question box (design spec 5.4): built offline, off the UI thread,
once the box rests; the script Speak builds replaces it."""

import threading

from PySide6.QtWidgets import QApplication

from cloudyreader.gui import tokens
from cloudyreader.gui.fake_service import FakeReaderService
from cloudyreader.models import Segment, SpokenScript

SETTLE_MS = 3 * tokens.SCRIPT_DEBOUNCE_MS  # long enough for any waiting preview to land


class Marked(FakeReaderService):
    """A preview that reads apart from Speak's script, so a test can tell which one shows."""

    def preview_script(self, raw, opts):
        super().preview_script(raw, opts)
        return SpokenScript((Segment(text=f"preview of {raw}"),))


class NoPreview(FakeReaderService):
    preview_script = None  # a service without the hook


def script(window) -> str:
    return window.script_view.toPlainText()


def speak(qtbot, window) -> None:
    with qtbot.waitSignal(window.reading_played, timeout=5000):
        window.speak_button.click()


def test_the_script_follows_the_question_off_the_ui_thread(qtbot, window, service):
    window.question_edit.setPlainText("alpha\nbeta")

    qtbot.waitUntil(lambda: script(window) == "alpha beta")

    (call,) = service.preview_calls
    assert call.thread is not threading.main_thread()
    assert service.calls == []  # a preview never synthesizes


def test_a_burst_of_edits_builds_one_preview(qtbot, window, service):
    for text in ("a", "ab", "abc"):
        window.question_edit.setPlainText(text)

    qtbot.waitUntil(lambda: script(window) == "abc")
    qtbot.wait(SETTLE_MS)

    assert [call.raw for call in service.preview_calls] == ["abc"]


def test_read_answer_rebuilds_the_script_with_the_option(qtbot, window, service):
    window.question_edit.setPlainText("q")
    qtbot.waitUntil(lambda: len(service.preview_calls) == 1)

    window.read_answer_check.setChecked(True)

    qtbot.waitUntil(lambda: len(service.preview_calls) == 2)
    assert [call.opts.read_answer for call in service.preview_calls] == [False, True]


def test_an_emptied_box_shows_the_placeholder_without_a_preview(qtbot, window, service):
    window.question_edit.setPlainText("q")
    qtbot.waitUntil(lambda: script(window) == "q")

    window.question_edit.clear()

    qtbot.waitUntil(lambda: script(window) == "")
    assert len(service.preview_calls) == 1


def test_speak_before_the_box_rests_shows_speaks_own_script(qtbot, make_window):
    service = Marked()
    window = make_window(service=service)
    window.question_edit.setPlainText("q")

    speak(qtbot, window)
    qtbot.wait(SETTLE_MS)

    assert script(window) == "q"
    assert service.preview_calls == []


def test_a_failed_preview_leaves_the_panel_empty_and_says_nothing(qtbot, make_window):
    service = FakeReaderService(preview_error=ValueError("bad paste"))
    window = make_window(service=service)
    window.question_edit.setPlainText("q")

    qtbot.waitUntil(lambda: len(service.preview_calls) == 1)
    qtbot.wait(SETTLE_MS)

    assert script(window) == ""
    assert window.statusBar().currentMessage() == ""
    assert QApplication.activeModalWidget() is None


def test_without_the_hook_the_script_waits_for_speak(qtbot, make_window):
    window = make_window(service=NoPreview())
    window.question_edit.setPlainText("q")
    qtbot.wait(SETTLE_MS)
    assert script(window) == ""

    speak(qtbot, window)

    assert script(window) == "q"


def test_closing_drops_a_waiting_preview(qtbot, window, service):
    window.question_edit.setPlainText("q")

    window.close()
    qtbot.wait(SETTLE_MS)

    assert service.preview_calls == []


def test_a_change_after_close_builds_no_preview(qtbot, window, service):
    window.close()

    window.question_edit.setPlainText("q")
    qtbot.wait(SETTLE_MS)

    assert service.preview_calls == []
