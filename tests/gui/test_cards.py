"""The question card and the spoken-script panel: a primary surface and a recessed one."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout

from cloudyreader.gui import tokens
from tests.gui.test_tokens import AA_UI_PART, CARD, WINDOW, contrast

LOOKS = [(Qt.ColorScheme.Light, "LIGHT"), (Qt.ColorScheme.Dark, "DARK")]


def inset(card) -> int:
    margins = card.layout().contentsMargins()
    assert margins.left() == margins.top() == margins.right() == margins.bottom()
    return margins.left()


def test_the_question_sits_frameless_in_its_card(window):
    card, view = window.question_card, window.question_edit

    assert view.parentWidget() is card
    assert view.frameShape() == QFrame.Shape.NoFrame
    assert not view.viewport().autoFillBackground()  # the card's fill shows through


def test_the_question_text_sits_card_padding_from_the_card_edge(window):
    card, view = window.question_card, window.question_edit

    assert inset(card) + view.document().documentMargin() == tokens.CARD_PADDING
    corner = view.viewport().mapTo(card, QPoint(0, 0))
    assert (corner.x(), corner.y()) == (inset(card), inset(card))


def test_the_view_keeps_its_square_corners_inside_the_rounded_ones(window):
    # A corner point d in from both edges is inside the arc when d > r (1 - 1/sqrt 2).
    clear = tokens.CARD_RADIUS * (1 - 2**-0.5) + tokens.BORDER_WIDTH

    assert inset(window.question_card) > clear


def test_the_question_text_is_15_points(window):
    body = QApplication.font().pointSizeF()
    ratio = tokens.TEXT_QUESTION_PT / tokens.TEXT_BODY_PT

    assert window.question_edit.font().pointSizeF() == pytest.approx(body * ratio)


def test_the_card_shows_at_least_three_lines(window):
    line = QFontMetricsF(window.question_edit.font()).lineSpacing()

    shown = window.question_card.minimumHeight() - 2 * tokens.CARD_PADDING

    assert shown >= tokens.QUESTION_MIN_LINES * line


def test_the_card_keeps_the_question_stretch(window):
    layout = window.centralWidget().layout()
    assert isinstance(layout, QVBoxLayout)

    assert layout.stretch(layout.indexOf(window.question_card)) == 3


def test_a_click_on_the_padding_reaches_the_question(window):
    card = window.question_card

    assert card.focusProxy() is window.question_edit
    assert card.focusPolicy() == Qt.FocusPolicy.ClickFocus  # never a stop of its own on Tab


@pytest.mark.parametrize(("scheme", "look"), LOOKS)
def test_the_outline_follows_the_appearance_and_meets_3_to_1(window, scheme, look):
    QGuiApplication.styleHints().colorSchemeChanged.emit(scheme)
    border = window.question_card.border

    assert border == QColor(getattr(tokens, f"CARD_BORDER_{look}"))
    assert contrast(border.name(), WINDOW[look]) >= AA_UI_PART
    assert contrast(border.name(), CARD[look]) >= AA_UI_PART


def test_the_fill_is_the_system_text_background(qapp, window):
    original = qapp.palette()
    tinted = QPalette(original)
    tinted.setColor(QPalette.ColorRole.Base, QColor("#123456"))
    try:
        qapp.setPalette(tinted)
        qapp.processEvents()

        assert window.question_card.fill.name() == "#123456"  # read when painted: it follows
    finally:
        qapp.setPalette(original)
        qapp.processEvents()


def test_the_card_paints_a_rounded_outline_around_its_fill(window):
    card = window.question_card
    image = card.grab().toImage()
    middle = image.height() // 2

    assert image.pixelColor(0, middle) == card.border  # the outline, all of it inside
    assert image.pixelColor(tokens.BORDER_WIDTH, middle) == card.fill
    assert image.pixelColor(image.width() // 2, image.height() - 2) == card.fill
    assert image.pixelColor(0, 0) != card.border  # the corner is rounded off


# --- the spoken-script panel -----------------------------------------------------------------


def secondary_palette(view) -> tuple[str, str]:
    palette = view.palette()
    return (
        palette.color(QPalette.ColorRole.Text).name(),
        palette.color(QPalette.ColorRole.PlaceholderText).name(),
    )


def test_the_script_sits_frameless_in_a_panel_without_an_outline(window):
    panel, view = window.script_panel, window.script_view

    assert view.parentWidget() is panel
    assert view.frameShape() == QFrame.Shape.NoFrame
    assert not view.viewport().autoFillBackground()
    assert panel.border is None


def test_the_panel_shows_at_least_two_lines(window):
    line = QFontMetricsF(window.script_view.font()).lineSpacing()

    shown = window.script_panel.minimumHeight() - 2 * tokens.PANEL_PADDING

    assert shown >= tokens.SCRIPT_MIN_LINES * line


@pytest.mark.parametrize(("scheme", "look"), LOOKS)
def test_the_panel_fill_and_secondary_text_come_from_the_tokens_at_aa(window, scheme, look):
    QGuiApplication.styleHints().colorSchemeChanged.emit(scheme)
    fill = window.script_panel.fill.name()
    secondary = QColor(getattr(tokens, f"TEXT_SECONDARY_{look}")).name()

    assert fill == QColor(getattr(tokens, f"PANEL_{look}")).name()
    assert secondary_palette(window.script_view) == (secondary, secondary)  # the hint as well
    assert contrast(secondary, fill) >= 4.5


def test_the_panel_shows_and_hides_with_the_script(qtbot, window):
    panel = window.script_panel
    assert panel.isVisible()  # open from the start

    window.script_toggle.click()
    assert panel.isHidden()

    window.script_toggle.click()
    assert panel.isVisible()
    assert window.script_view.isVisible()


def test_the_panel_paints_its_fill_and_no_outline(window):
    panel = window.script_panel
    image = panel.grab().toImage()
    middle = image.height() // 2

    assert image.pixelColor(0, middle) == panel.fill
    assert image.pixelColor(image.width() // 2, middle) == panel.fill
    assert image.pixelColor(0, 0) != panel.fill  # the corner is rounded off
