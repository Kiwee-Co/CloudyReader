"""The two-tone focus ring around the text views; native controls keep the system's own ring."""

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QWidget

from cloudyreader.gui import tokens
from tests.gui.test_tokens import AA_UI_PART, CARD, WINDOW, contrast

REACH = tokens.FOCUS_RADIUS_EXTRA


@pytest.fixture
def active(qtbot, window):
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    return window


def ring(window):
    return window._focus_ring  # private on purpose: the overlay has no public face


def ringed(window, frame: QWidget) -> QRect:
    """Where the ring must sit around frame: its edge, plus both strokes outside it."""
    corner = frame.mapTo(window.centralWidget(), QPoint(0, 0))
    return QRect(corner, frame.size()).adjusted(-REACH, -REACH, REACH, REACH)


def focus(qtbot, widget) -> None:
    widget.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(widget.hasFocus)


def test_the_question_card_gets_the_ring_outside_its_edge(qtbot, active):
    focus(qtbot, active.question_edit)

    assert ring(active).isVisible()
    assert ring(active).geometry() == ringed(active, active.question_card)


def test_tab_takes_the_ring_off_for_a_native_control(qtbot, active):
    focus(qtbot, active.question_edit)

    qtbot.keyClick(active.question_edit, Qt.Key.Key_Tab)

    assert active.voice_picker.combo.hasFocus()
    assert ring(active).isHidden()


def test_the_script_view_gets_the_ring_once_shown(qtbot, active):
    active.script_toggle.click()
    focus(qtbot, active.script_view)

    assert ring(active).isVisible()
    assert ring(active).geometry() == ringed(active, active.script_view)


def test_the_ring_follows_its_surface_when_the_window_resizes(qtbot, active):
    focus(qtbot, active.question_edit)

    active.resize(active.width() + 40, active.height() + 30)
    qtbot.waitUntil(lambda: ring(active).geometry() == ringed(active, active.question_card))


def test_an_inactive_window_shows_no_ring_like_macos(qtbot, active):
    focus(qtbot, active.question_edit)
    other = QWidget()
    qtbot.addWidget(other)
    other.show()
    other.activateWindow()
    qtbot.waitUntil(lambda: not active.isActiveWindow())

    assert ring(active).isHidden()

    active.activateWindow()
    qtbot.waitUntil(ring(active).isVisible)


def test_the_text_views_drop_the_native_ring_so_none_gets_two(window):
    for view in (window.question_edit, window.script_view):
        assert not view.testAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect)


@pytest.mark.parametrize(
    ("scheme", "look"), [(Qt.ColorScheme.Light, "LIGHT"), (Qt.ColorScheme.Dark, "DARK")]
)
def test_the_inner_stroke_follows_the_appearance_and_meets_3_to_1(window, scheme, look):
    QGuiApplication.styleHints().colorSchemeChanged.emit(scheme)
    inner = ring(window).inner_color.name()

    assert inner == QColor(getattr(tokens, f"FOCUS_INNER_{look}")).name()
    assert contrast(inner, WINDOW[look]) >= AA_UI_PART
    assert contrast(inner, CARD[look]) >= AA_UI_PART


def test_the_ring_paints_the_contrast_stroke_inside_the_accent(qtbot, active):
    focus(qtbot, active.question_edit)
    image = ring(active).grab().toImage()
    middle = image.height() // 2
    palette = ring(active).palette()

    assert image.pixelColor(REACH - tokens.FOCUS_INNER_WIDTH, middle) == ring(active).inner_color
    assert image.pixelColor(0, middle) == palette.color(QPalette.ColorRole.Accent)
    # grab() fills what the ring leaves unpainted with the window color: inside the edge.
    assert image.pixelColor(REACH, middle) == palette.color(QPalette.ColorRole.Window)


def test_the_surface_shows_through_the_ring(qtbot, active):
    focus(qtbot, active.question_edit)
    view = active.question_edit.viewport()
    inside = view.mapTo(active.centralWidget(), QPoint(1, view.height() // 2))

    image = active.centralWidget().grab().toImage()

    assert image.pixelColor(inside) == view.palette().color(QPalette.ColorRole.Base)
