"""Offscreen render smoke: every screen in both appearances draws, fits, and clips no text.

No pixel goldens: each screen must draw, show its controls, and give every text control at least
its minimum size hint at the window's minimum size, where a smaller widget would cut its text.
"""

import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QLabel,
    QMessageBox,
    QWidget,
)

from cloudyreader.gui import tokens
from cloudyreader.gui.fake_service import ENGINE_FAKE_VOICES, FakeReaderService
from cloudyreader.prefetch import PrefetchProgress, PrefetchResult

MB = 10**6
QUESTION = (
    "TOSS-UP\n1) CHEMISTRY Short Answer Which gas forms when sodium bicarbonate reacts with "
    "acetic acid?\nANSWER: CARBON DIOXIDE"
)
WARNING = "No pronunciation for respelling [OL-UH-VEEN]: 'olivine' is spoken plain."
APPEARANCES = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}
SHOWN = (
    "question_edit",
    "voice_picker.combo",
    "rotation_combo",
    "read_answer_check",
    "online_lookups_check",
    "repeat_button",
    "stop_button",
    "speak_button",
    "script_toggle",
    "script_view",
)


def control(window, path: str):
    target = window
    for name in path.split("."):
        target = getattr(target, name)
    return target


def clipped(root: QWidget) -> list[str]:
    """Visible text controls smaller than their minimum size hint: they would cut their text."""
    cut = []
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, QLabel | QAbstractButton | QComboBox):
            continue
        hint = widget.minimumSizeHint()
        if widget.isVisibleTo(root) and (
            widget.width() < hint.width() or widget.height() < hint.height()
        ):
            name = widget.accessibleName() or getattr(widget, "text", lambda: "")()
            cut.append(f"{type(widget).__name__} {name!r} {widget.size()} < {hint}")
    return cut


def assert_draws(widget: QWidget) -> None:
    pixmap = widget.grab()
    assert not pixmap.isNull()
    assert pixmap.size() == widget.size() * pixmap.devicePixelRatio()


def speak(qtbot, window, signal="reading_played") -> None:
    window.question_edit.setPlainText(QUESTION)
    with qtbot.waitSignal(getattr(window, signal), timeout=5000):
        window.speak_button.click()


def held_download(request, event: PrefetchProgress, **knobs) -> FakeReaderService:
    gate = threading.Event()
    request.addfinalizer(gate.set)  # before the window closes: its thread must not wait long
    result = PrefetchResult("nothing")
    return FakeReaderService(
        prefetch_gate=gate, prefetch_events=[event], prefetch_result=result, **knobs
    )


def hold_reading(qtbot, request, window) -> None:
    window._service.gate = gate = threading.Event()  # private on purpose: the fake's own knob
    request.addfinalizer(gate.set)
    window.question_edit.setPlainText(QUESTION)
    window.speak_button.click()
    qtbot.waitUntil(lambda: window._busy, timeout=2000)


def idle(make_window, qtbot, request):
    return make_window()


def reading(make_window, qtbot, request):
    window = make_window()
    speak(qtbot, window)
    window.script_toggle.setChecked(True)
    return window


def preparing(make_window, qtbot, request):
    window = make_window()
    hold_reading(qtbot, request, window)
    return window


def first_launch(make_window, qtbot, request):
    event = PrefetchProgress("en_US-lessac-medium.onnx", 4 * MB, 100 * MB, 0, 10)
    window = make_window(service=held_download(request, event, voices=[]))
    qtbot.waitUntil(window.prefetch_label.isVisible, timeout=5000)
    return window


def engine_download_while_preparing(make_window, qtbot, request):
    event = PrefetchProgress(
        "model.safetensors",
        1_489 * MB,
        3_050 * MB,
        1,
        64,
        group="chatterbox_turbo",
        group_done_bytes=176 * MB,
        group_total_bytes=420 * MB,
    )
    window = make_window(service=held_download(request, event, load_hint="loading Chatterbox"))
    qtbot.waitUntil(window.prefetch_label.isVisible, timeout=5000)
    hold_reading(qtbot, request, window)
    return window


def error(make_window, qtbot, request):
    window = make_window(service=FakeReaderService(error=RuntimeError("voice is not installed")))
    speak(qtbot, window, "error_occurred")
    return window


def warning(make_window, qtbot, request):
    window = make_window(service=FakeReaderService(warnings=(WARNING,)))
    speak(qtbot, window)
    return window


WINDOW_SCREENS = {
    screen.__name__: screen
    for screen in (
        idle,
        reading,
        preparing,
        first_launch,
        engine_download_while_preparing,
        error,
        warning,
    )
}


@pytest.fixture(params=list(APPEARANCES))
def appearance(request) -> Qt.ColorScheme:
    return APPEARANCES[request.param]


def at_minimum_size(qtbot, window) -> None:
    """The minimum size of the content: macOS puts the menu bar at the top of the screen, but
    the offscreen platform draws it in the window, so it gets its own height on top."""
    width, height = tokens.WINDOW_MIN_SIZE
    bar = window.menuBar()
    height += bar.height() if bar.isVisible() else 0
    window.resize(width, height)
    qtbot.waitUntil(lambda: (window.width(), window.height()) == (width, height))
    QApplication.processEvents()  # the status bar lays out its permanent widgets


def check_window(qtbot, window, scheme: Qt.ColorScheme) -> None:
    QGuiApplication.styleHints().colorSchemeChanged.emit(scheme)
    at_minimum_size(qtbot, window)

    assert_draws(window)
    assert [path for path in SHOWN if not control(window, path).isVisible()] == []
    assert clipped(window) == []


@pytest.mark.parametrize("screen", list(WINDOW_SCREENS))
def test_every_window_state_draws_whole_at_the_minimum_size(
    qtbot, make_window, request, screen, appearance
):
    check_window(qtbot, WINDOW_SCREENS[screen](make_window, qtbot, request), appearance)


@pytest.mark.parametrize("screen", ["reading", "first_launch", "engine_download_while_preparing"])
def test_the_widest_states_fit_the_minimum_size_in_the_macos_style(
    qtbot, make_window, request, mac_style, screen
):
    window = WINDOW_SCREENS[screen](make_window, qtbot, request)

    check_window(qtbot, window, Qt.ColorScheme.Light)


def test_each_state_shows_its_own_parts(qtbot, make_window, request):
    assert reading(make_window, qtbot, request).script_view.isVisible()
    assert preparing(make_window, qtbot, request).busy_bar.isVisible()
    window = first_launch(make_window, qtbot, request)
    assert window.prefetch_label.isVisible()
    assert window.prefetch_bar.isVisible()


def test_the_about_panel_draws_whole(qtbot, window, appearance):
    QGuiApplication.styleHints().colorSchemeChanged.emit(appearance)
    window.about_action.trigger()
    box = window.findChild(QMessageBox)
    qtbot.waitUntil(box.isVisible)
    try:
        assert_draws(box)
        assert clipped(box) == []
        texts = [label.text() for label in box.findChildren(QLabel) if label.isVisible()]
        assert "Cloudy Reader" in texts
        assert any("Reads National Science Bowl questions aloud." in text for text in texts)
        assert [b.text() for b in box.findChildren(QAbstractButton) if b.isVisible()] == ["OK"]
    finally:
        box.close()


@pytest.mark.parametrize("path", ["voice_picker.combo", "rotation_combo"])
def test_each_popup_menu_draws_every_row_whole(qtbot, make_window, path, appearance):
    window = make_window(service=FakeReaderService(voices=ENGINE_FAKE_VOICES))
    QGuiApplication.styleHints().colorSchemeChanged.emit(appearance)
    combo = control(window, path)
    view = combo.view()
    combo.showPopup()
    try:
        qtbot.waitUntil(view.isVisible)
        assert_draws(view.window())
        model, column = combo.model(), combo.modelColumn()
        widest = max(
            view.sizeHintForIndex(model.index(row, column)).width()
            for row in range(model.rowCount())
        )
        assert view.viewport().width() >= widest
    finally:
        combo.hidePopup()
