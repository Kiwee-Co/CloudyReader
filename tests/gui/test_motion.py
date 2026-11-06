"""Reduce Motion: the AppKit read never raises, and the busy bar stays still when it is on."""

import sys
import threading

import pytest
from PySide6.QtCore import Qt

from cloudyreader.gui import main_window, motion


def broken() -> bool:
    raise OSError("no AppKit here")


@pytest.mark.parametrize(("reader", "expected"), [(lambda: True, True), (lambda: 0, False)])
def test_the_setting_is_what_the_reader_says(reader, expected):
    assert motion.reduce_motion(reader) is expected


def test_a_failed_read_is_off_and_never_raises():
    assert motion.reduce_motion(broken) is False


def test_off_macos_nothing_is_read(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    assert motion.reduce_motion(broken) is False  # the reader would raise: it is never called


def test_a_missing_runtime_library_is_off(monkeypatch):
    monkeypatch.setattr(motion.ctypes.util, "find_library", lambda _name: None)

    assert motion.reduce_motion() is False


def test_the_real_read_answers_without_raising():
    assert isinstance(motion.reduce_motion(), bool)


# --- the window ------------------------------------------------------------------------------


@pytest.fixture
def setting(monkeypatch):
    """Reduce Motion as the window reads it: flip `on` to change what the system says."""

    class Setting:
        on = True

    monkeypatch.setattr(main_window, "reduce_motion", lambda: Setting.on)
    return Setting


def hold_reading(qtbot, request, window) -> None:
    window._service.gate = gate = threading.Event()  # private on purpose: the fake's own knob
    request.addfinalizer(gate.set)
    window.question_edit.setPlainText("What is H2O?")
    window.speak_button.click()
    qtbot.waitUntil(lambda: window._busy, timeout=2000)


def test_with_reduce_motion_on_preparing_shows_without_the_busy_bar(
    qtbot, make_window, request, setting
):
    window = make_window()

    hold_reading(qtbot, request, window)

    assert window.statusBar().currentMessage() == "Preparing…"
    assert window.busy_bar.isHidden()


def test_with_reduce_motion_off_the_busy_bar_shows_as_before(qtbot, make_window, request, setting):
    setting.on = False
    window = make_window()

    hold_reading(qtbot, request, window)

    assert window.busy_bar.isVisible()


def test_the_setting_is_read_again_when_the_app_becomes_active(
    qtbot, qapp, make_window, request, setting
):
    setting.on = False
    window = make_window()
    hold_reading(qtbot, request, window)
    assert window.busy_bar.isVisible()

    setting.on = True
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    assert window.busy_bar.isHidden()

    setting.on = False
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
    assert window.busy_bar.isHidden()  # only becoming active reads it
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    assert window.busy_bar.isVisible()
