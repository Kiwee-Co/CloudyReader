"""Button row and form alignment: one width for the playback group, one edge for the form."""

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QStyle,
    QStyleOptionButton,
    QStyleOptionComboBox,
)

TOLERANCE = 0.5  # points

LAYOUT_ITEMS = {
    QComboBox: (QStyleOptionComboBox, QStyle.SubElement.SE_ComboBoxLayoutItem),
    QCheckBox: (QStyleOptionButton, QStyle.SubElement.SE_CheckBoxLayoutItem),
}


def visible_left(window, widget) -> int:
    """The left edge the style draws, which can sit inside the widget: its layout item rect."""
    option_class, element = LAYOUT_ITEMS[type(widget)]
    option = option_class()
    widget.initStyleOption(option)
    drawn = widget.style().subElementRect(element, option, widget)
    return widget.mapTo(window, drawn.topLeft()).x()


def label_right(window, text: str) -> int:
    label = next(w for w in window.findChildren(QLabel) if w.text() == text)
    return label.mapTo(window, QPoint(label.width(), 0)).x()


def check_form_edges(window) -> None:
    fields = [window.voice_picker.combo, window.rotation_combo, window.read_answer_check]
    lefts = [visible_left(window, field) for field in fields]
    rights = [label_right(window, text) for text in ("Voice:", "Rotation:", "Options:")]

    assert max(lefts) - min(lefts) <= TOLERANCE, lefts
    assert max(rights) - min(rights) <= TOLERANCE, rights


def check_playback_widths(window) -> None:
    playback = (window.repeat_button, window.stop_button, window.speak_button)

    widths = {button.width() for button in playback}

    assert widths == {max(button.sizeHint().width() for button in playback)}
    assert window.speak_button.isDefault()


def test_the_playback_buttons_share_the_widest_labels_width(window):
    check_playback_widths(window)


def test_in_the_macos_style_the_playback_widths_differ_until_shared(mac_style, make_window):
    # Fusion gives every short push button one minimum width; macOS sizes each to its label.
    window = make_window()

    hints = {b.sizeHint().width() for b in (window.repeat_button, window.stop_button)}

    assert len(hints) == 2
    check_playback_widths(window)


def test_the_form_fields_and_labels_share_one_edge(window):
    check_form_edges(window)


def test_in_the_macos_style_the_drawn_edges_line_up_too(mac_style, make_window):
    # macOS draws a popup inside its widget, 3 pt in; a container or a box layout around the
    # Voice popup would push its drawn edge that far right of the Rotation popup's.
    window = make_window()
    combo = window.voice_picker.combo

    assert visible_left(window, combo) > combo.mapTo(window, QPoint(0, 0)).x()
    check_form_edges(window)


@pytest.mark.parametrize("multi", [False, True])
def test_the_speaker_row_sits_under_the_popup_only_when_it_shows(window, multi):
    picker = window.voice_picker
    if multi:
        picker.select_voice("piper:en_US-libritts-high")

    assert picker.speaker_spin.isVisible() is multi
    assert picker.speaker_label.isVisible() is multi
    if multi:
        assert picker.speaker_spin.y() > picker.combo.y()
        assert label_right(window, "Speaker:") == label_right(window, "Voice:")
