"""Every voice label fits the closed pop-up, with room to spare, at every window size."""

import dataclasses

import pytest
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QStyle,
    QStyleOptionComboBox,
    QWidget,
)

from cloudyreader.gui import tokens
from cloudyreader.gui.fake_service import ENGINE_FAKE_VOICES, MACOS_FAKE_VOICES
from cloudyreader.gui.voice_picker import VoicePicker
from cloudyreader.voice_meta import voice_label
from tests.voice_table import real_voices

HEADROOM = 0.9  # the longest label takes at most this share of the text field


@pytest.fixture
def table(tmp_path, monkeypatch):
    """Every real voice as if it were installed, plus the macOS system voices."""
    rows = [
        dataclasses.replace(v, installed=True, reason="")
        for v in real_voices(tmp_path, monkeypatch)
    ]
    return [*rows, *MACOS_FAKE_VOICES]


@pytest.fixture
def picker(qtbot, mac_style):
    host = QWidget()
    qtbot.addWidget(host)
    form = QFormLayout(host)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)  # as the window
    widget = VoicePicker(host)
    widget.add_rows(form)
    widget.set_voices(ENGINE_FAKE_VOICES)
    host.show()
    widget.combo.resize(widget.combo.sizeHint())
    yield widget  # the host lives as long as the fixture


def text_field_width(picker) -> int:
    combo = picker.combo
    option = QStyleOptionComboBox()
    combo.initStyleOption(option)
    field = combo.style().subControlRect(
        QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxEditField, combo
    )
    return field.width()


def test_every_label_fits_the_text_field_with_room_to_spare(picker, table):
    metrics = picker.combo.fontMetrics()
    widths = {v.key: metrics.horizontalAdvance(voice_label(v)) for v in table}
    field = text_field_width(picker)

    widest = max(widths, key=widths.get)
    assert widths[widest] <= field * HEADROOM, (widest, widths[widest], field)


def test_the_pop_up_fits_the_form_at_the_minimum_window(picker):
    # The widest label of the form column is "Rotation:"; margins on both sides, one gap.
    label = QLabel("Rotation:").sizeHint().width()
    room = tokens.WINDOW_MIN_SIZE[0] - 2 * tokens.MARGIN - label - tokens.CONTROL_SPACING

    assert picker.combo.sizeHint().width() <= room
