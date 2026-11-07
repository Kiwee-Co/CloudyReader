"""The main window from top to bottom (design spec 5.1): the question, its Spoken script right under
it, the form, the button row, then the status bar, on the 24, 16 and 8 pt rhythm."""

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QFormLayout, QHBoxLayout, QWidget

from cloudyreader.gui import tokens

LIBRITTS = "piper:en_US-libritts-high"
TALLER = 100  # points added to the window height in the resize tests


@pytest.fixture(params=["default", "macOS"])
def styled(request, make_window):
    """The window in the offscreen default style and in the macOS style it runs with."""
    if request.param == "macOS":
        request.getfixturevalue("mac_style")
    return make_window()


def rect(window, widget: QWidget) -> QRect:
    """Where the layout put a widget, in the central widget's coordinates."""
    return QRect(widget.mapTo(window.centralWidget(), QPoint(0, 0)), widget.size())


def bottom(r: QRect) -> int:
    return r.y() + r.height()  # QRect.bottom() is one pixel short of the edge


def form(window) -> QRect:
    return window.centralWidget().findChild(QFormLayout).geometry()


def button_row(window) -> QHBoxLayout:
    rows = window.centralWidget().findChildren(QHBoxLayout)
    return next(row for row in rows if row.indexOf(window.speak_button) >= 0)


def settle(qtbot, window, height: int) -> None:
    window.resize(window.width(), height)
    qtbot.waitUntil(lambda: window.height() == height)
    QApplication.processEvents()  # the layout runs on a posted request


def test_the_parts_stack_in_reading_order_on_the_rhythm(styled):
    card, toggle = rect(styled, styled.question_card), rect(styled, styled.script_toggle)
    panel, row = rect(styled, styled.script_panel), button_row(styled).geometry()

    assert card.topLeft() == QPoint(tokens.MARGIN, tokens.MARGIN)
    assert toggle.y() == bottom(card) + tokens.RELATED_SPACING
    assert panel.y() == bottom(toggle) + tokens.CONTROL_SPACING
    assert form(styled).y() == bottom(panel) + tokens.SECTION_SPACING
    assert row.y() == bottom(form(styled)) + tokens.SECTION_SPACING
    assert bottom(row) == styled.centralWidget().height() - tokens.MARGIN


def test_the_card_and_the_panel_span_the_content_width(styled):
    width = styled.centralWidget().width() - 2 * tokens.MARGIN

    for surface in (styled.question_card, styled.script_panel):
        assert (rect(styled, surface).x(), surface.width()) == (tokens.MARGIN, width)


def test_the_button_row_holds_repeat_stop_and_speak_trailing(styled):
    row = button_row(styled)
    widgets = [row.itemAt(i).widget() for i in range(row.count()) if row.itemAt(i).widget()]
    repeat, stop, speak = (rect(styled, b) for b in widgets)

    assert widgets == [styled.repeat_button, styled.stop_button, styled.speak_button]
    assert speak.x() + speak.width() == styled.centralWidget().width() - tokens.MARGIN
    assert stop.x() + stop.width() + tokens.GROUP_SPACING == speak.x()
    assert repeat.x() + repeat.width() + tokens.GROUP_SPACING == stop.x()
    assert repeat.width() == stop.width() == speak.width()
    assert styled.speak_button.isDefault()


def test_voice_and_rotation_share_one_width(styled):
    voice, rotation = styled.voice_picker.combo, styled.rotation_combo

    assert voice.width() == rotation.width()
    assert rotation.width() >= max(voice.sizeHint().width(), rotation.sizeHint().width())


def test_the_spoken_script_is_open_at_start(window):
    assert window.script_toggle.isChecked()
    assert window.script_panel.isVisible()
    assert window.script_view.isVisible()


def test_spare_height_splits_three_to_two_between_the_card_and_the_panel(qtbot, styled):
    card, panel = styled.question_card.height(), styled.script_panel.height()
    share = TALLER * tokens.QUESTION_STRETCH / (tokens.QUESTION_STRETCH + tokens.SCRIPT_STRETCH)

    settle(qtbot, styled, styled.height() + TALLER)

    assert styled.question_card.height() - card == pytest.approx(share, abs=1)
    assert styled.script_panel.height() - panel == pytest.approx(TALLER - share, abs=1)


def test_collapsed_the_panel_leaves_no_gap_and_the_card_takes_its_room(qtbot, styled):
    card, panel = styled.question_card.height(), styled.script_panel.height()
    assert styled.script_toggle.isChecked()

    styled.script_toggle.click()
    qtbot.waitUntil(lambda: styled.question_card.height() > card)

    assert styled.script_panel.isHidden()
    assert form(styled).y() == bottom(rect(styled, styled.script_toggle)) + tokens.SECTION_SPACING
    assert styled.question_card.height() == card + panel + tokens.CONTROL_SPACING
    settle(qtbot, styled, styled.height() + TALLER)
    assert styled.question_card.height() == card + panel + tokens.CONTROL_SPACING + TALLER


@pytest.mark.parametrize("speaker", [False, True], ids=["one speaker", "speaker row"])
def test_the_minimum_size_holds_the_open_script(qtbot, styled, speaker):
    if speaker:
        styled.voice_picker.select_voice(LIBRITTS)
        qtbot.waitUntil(styled.voice_picker.speaker_spin.isVisible)
    hint = styled.minimumSizeHint()
    # Offscreen draws the menu bar in the window; on macOS it sits at the top of the screen.
    menu = styled.menuBar().height() if styled.menuBar().isVisible() else 0

    assert styled.script_view.isVisible()
    assert hint.width() <= tokens.WINDOW_MIN_SIZE[0]
    assert hint.height() - menu <= tokens.WINDOW_MIN_SIZE[1]
