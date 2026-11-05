import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QProgressBar

from cloudyreader.gui import tokens
from cloudyreader.gui.widgets import DisclosureButton, StatusBar, Tone, text_style


@pytest.fixture
def disclosure(qtbot):
    button = DisclosureButton("Spoken script")
    qtbot.addWidget(button)
    button.show()
    return button


@pytest.fixture
def status(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.resize(400, 24)
    bar.show()
    return bar


# --- type ramp -------------------------------------------------------------------------------


def test_text_style_scales_the_system_font_along_the_ramp(qapp):
    body = text_style(tokens.TEXT_BODY_PT)
    callout = text_style(tokens.TEXT_CALLOUT_PT)

    assert body.family() == callout.family() == QApplication.font().family()
    assert body.pointSizeF() == pytest.approx(QApplication.font().pointSizeF())
    ratio = tokens.TEXT_CALLOUT_PT / tokens.TEXT_BODY_PT
    assert callout.pointSizeF() == pytest.approx(body.pointSizeF() * ratio)


# --- disclosure button -----------------------------------------------------------------------


def test_disclosure_starts_collapsed_and_checkable(disclosure):
    assert disclosure.isCheckable()
    assert not disclosure.isChecked()
    assert disclosure.arrowType() == Qt.ArrowType.RightArrow


def test_disclosure_arrow_follows_the_checked_state(disclosure):
    disclosure.click()
    assert disclosure.arrowType() == Qt.ArrowType.DownArrow

    disclosure.click()
    assert disclosure.arrowType() == Qt.ArrowType.RightArrow


def test_disclosure_label_uses_the_body_style_not_the_small_tool_button_font(disclosure):
    assert disclosure.font().pointSizeF() == pytest.approx(QApplication.font().pointSizeF())


def test_disclosure_is_sized_for_its_indicator_and_label(disclosure):
    hint = disclosure.sizeHint()
    text_width = disclosure.fontMetrics().horizontalAdvance(disclosure.text())

    assert hint.width() >= tokens.DISCLOSURE_SIZE + text_width
    assert hint.height() >= max(tokens.DISCLOSURE_SIZE, disclosure.fontMetrics().height())
    assert disclosure.minimumSizeHint() == hint


def test_disclosure_asks_for_the_macos_focus_ring(disclosure):
    assert disclosure.testAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect)


@pytest.mark.parametrize(
    ("checked", "enabled", "focused"), [(False, True, False), (True, False, True)]
)
def test_disclosure_paints_in_every_state(disclosure, checked, enabled, focused):
    disclosure.setChecked(checked)
    disclosure.setEnabled(enabled)
    if focused:
        disclosure.setFocus()

    pixmap = disclosure.grab()

    assert not pixmap.isNull()
    assert pixmap.size() == disclosure.size() * pixmap.devicePixelRatio()


# --- status bar ------------------------------------------------------------------------------


def test_status_message_carries_its_tone(status):
    status.show_message("Error: boom", Tone.ERROR)

    assert status.currentMessage() == "Error: boom"
    assert status.tone is Tone.ERROR


def test_status_tone_defaults_to_info(status):
    status.show_message("Stopped.")

    assert status.tone is Tone.INFO


def test_clearing_the_message_resets_the_tone(status):
    status.show_message("Warning: odd", Tone.WARNING)

    status.clearMessage()

    assert status.tone is Tone.INFO


def test_same_text_with_a_new_tone_still_updates_the_tone(status):
    status.show_message("No voice is installed.")
    status.show_message("No voice is installed.", Tone.WARNING)

    assert status.tone is Tone.WARNING


@pytest.mark.parametrize(
    ("tone", "has_icon"), [(Tone.INFO, False), (Tone.WARNING, True), (Tone.ERROR, True)]
)
def test_only_warnings_and_errors_get_an_icon(status, tone, has_icon):
    status.show_message("text", tone)

    icon_rect, _text_rect, _text = status.message_layout()

    assert icon_rect.isValid() is has_icon


def test_message_starts_at_the_window_margin(status):
    status.show_message("Stopped.")

    _icon, text_rect, _text = status.message_layout()

    assert text_rect.left() == tokens.MARGIN


def test_text_follows_the_icon(status):
    status.show_message("Error: boom", Tone.ERROR)

    icon_rect, text_rect, _text = status.message_layout()

    assert icon_rect.left() == tokens.MARGIN
    assert icon_rect.size() == QSize(tokens.STATUS_ICON_SIZE, tokens.STATUS_ICON_SIZE)
    assert text_rect.left() > icon_rect.right()


def test_long_messages_are_elided_not_clipped(status):
    status.show_message("Error: " + "very long detail " * 40, Tone.ERROR)

    _icon, text_rect, text = status.message_layout()

    assert text.endswith("…")
    assert status.fontMetrics().horizontalAdvance(text) <= text_rect.width()


def test_message_stops_short_of_a_permanent_widget(status):
    busy = QProgressBar()
    busy.setFixedWidth(96)
    status.addPermanentWidget(busy)
    status.show_message("Preparing…")
    status.layout().activate()

    _icon, text_rect, _text = status.message_layout()

    assert text_rect.right() < busy.geometry().left()


def test_permanent_widgets_keep_the_window_margin(status):
    busy = QProgressBar()
    busy.setFixedWidth(96)
    status.addPermanentWidget(busy)
    status.layout().activate()

    assert not status.isSizeGripEnabled()
    assert status.width() - busy.geometry().right() - 1 == tokens.MARGIN


@pytest.mark.parametrize("tone", list(Tone))
def test_status_bar_paints_every_tone(status, tone):
    status.show_message("Some status text", tone)

    assert not status.grab().isNull()


def test_status_bar_paints_without_a_message(status):
    assert not status.grab().isNull()
