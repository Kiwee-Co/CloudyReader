"""Engine headers in the Voice menu: menu section headers, not voices dimmed like the rest."""

import pytest
from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QApplication,
    QFormLayout,
    QStyleOptionViewItem,
    QWidget,
)

from cloudyreader.gui import theme, tokens
from cloudyreader.gui.fake_service import ENGINE_FAKE_VOICES
from cloudyreader.gui.voice_picker import VoicePicker, _SectionHeader

TITLES = ["Piper", "Kokoro", "Chatterbox Turbo", "Qwen3-TTS"]
LIBRITTS = "piper:en_US-libritts-high"  # the last Piper voice
HEART = "kokoro:af_heart"  # the first Kokoro voice


@pytest.fixture
def picker(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    widget = VoicePicker(host)
    widget.add_rows(QFormLayout(host))
    widget.set_voices(ENGINE_FAKE_VOICES)
    host.show()
    yield widget  # the host lives as long as the fixture: qtbot keeps only a weak reference


def items(picker) -> list:
    model = picker.combo.model()
    return [model.item(row) for row in range(model.rowCount())]


def headers(picker) -> list:
    return [item for item in items(picker) if item.data(Qt.ItemDataRole.UserRole) is None]


def voices(picker) -> list:
    return [item for item in items(picker) if item.data(Qt.ItemDataRole.UserRole) is not None]


def test_headers_can_be_neither_selected_nor_focused(picker):
    assert [h.text() for h in headers(picker)] == TITLES
    assert {h.flags() for h in headers(picker)} == {Qt.ItemFlag.NoItemFlags}


def test_the_keyboard_steps_over_a_header(qtbot, picker):
    picker.select_voice(LIBRITTS)

    qtbot.keyClick(picker.combo, Qt.Key.Key_Down)
    assert picker.voice_key() == HEART

    qtbot.keyClick(picker.combo, Qt.Key.Key_Up)
    assert picker.voice_key() == LIBRITTS


def test_a_header_reads_to_voiceover_as_the_engine_voices(picker):
    texts = [h.data(Qt.ItemDataRole.AccessibleTextRole) for h in headers(picker)]

    assert texts == [f"{title} voices" for title in TITLES]


def test_headers_are_11_point_semibold_in_the_secondary_color(picker):
    section = QApplication.font().pointSizeF() * tokens.TEXT_SECTION_PT / tokens.TEXT_BODY_PT

    for header in headers(picker):
        assert header.font().pointSizeF() == pytest.approx(section)
        assert header.font().weight() == QFont.Weight.DemiBold
        assert header.foreground().color() == QColor(tokens.TEXT_SECONDARY_LIGHT)


@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("high", [False, True])
def test_the_header_color_follows_the_appearance(picker, dark, high):
    roles = theme.roles(theme.Appearance(dark=dark, high_contrast=high))
    picker.set_roles(roles)
    assert {h.foreground().color().name() for h in headers(picker)} == {
        QColor(roles.secondary_text).name()
    }

    picker.set_voices(ENGINE_FAKE_VOICES)  # a rebuild keeps the current color
    assert headers(picker)[0].foreground().color() == QColor(roles.secondary_text)


def test_installed_voice_rows_keep_the_menus_own_look_and_dimmed_ones_take_the_secondary_ink(
    picker,
):
    ink = QColor(tokens.TEXT_SECONDARY_LIGHT)
    for item in voices(picker):
        assert item.data(Qt.ItemDataRole.FontRole) is None
        if item.isEnabled():
            assert item.data(Qt.ItemDataRole.ForegroundRole) is None
        else:
            assert item.foreground().color() == ink  # a reason a person reads, not a faint gray
    dimmed = "Built-in · Chatterbox Turbo · 4-bit — not downloaded yet"
    assert dimmed in [item.text() for item in voices(picker)]


class RecordingMenu(QAbstractItemDelegate):
    """Stands in for the menu's own delegate: records what each row asks of it."""

    def __init__(self) -> None:
        super().__init__()
        self.painted: list[tuple[int, QRect]] = []

    def paint(self, painter, option, index) -> None:
        self.painted.append((index.row(), QRect(option.rect)))

    def sizeHint(self, option, index) -> QSize:
        return QSize(100, 22)


def row_index(picker, text: str) -> QModelIndex:
    model = picker.combo.model()
    return next(model.index(r, 0) for r in range(model.rowCount()) if model.item(r).text() == text)


def delegate_kinds(picker) -> list[bool]:
    view = picker.combo.view()
    model = picker.combo.model()
    rows = range(model.rowCount())
    return [isinstance(view.itemDelegateForIndex(model.index(r, 0)), _SectionHeader) for r in rows]


def test_only_header_rows_get_the_section_delegate(picker):
    is_header = [item.data(Qt.ItemDataRole.UserRole) is None for item in items(picker)]

    assert delegate_kinds(picker) == is_header


def test_a_rebuild_moves_the_section_delegate_with_the_headers(picker):
    by_key = {v.key: v for v in ENGINE_FAKE_VOICES}
    picker.set_voices([by_key[k] for k in ("piper:en_US-lessac-medium", HEART, "qwen3_tts:ryan")])

    assert delegate_kinds(picker) == [True, False, True, False, True, False]


def test_the_header_delegate_hands_the_row_to_the_menus_own_below_the_gap(picker):
    menu = RecordingMenu()
    view = picker.combo.view()
    view.setItemDelegate(menu)  # the menu's own delegate: voice rows go to it directly
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 50, 100, 30)

    for text, gap in (("Piper", 0), ("Kokoro", tokens.SECTION_HEADER_GAP)):
        index = row_index(picker, text)
        header = view.itemDelegateForIndex(index)
        header.paint(None, option, index)
        assert header.sizeHint(option, index) == QSize(100, 22 + gap)

    assert [rect for _row, rect in menu.painted] == [
        QRect(0, 50, 100, 30),  # the first row of the menu: no gap above it
        QRect(0, 50 + tokens.SECTION_HEADER_GAP, 100, 30 - tokens.SECTION_HEADER_GAP),
    ]
    assert (
        view.itemDelegateForIndex(row_index(picker, "Heart (US, female) · Kokoro · bf16")) is menu
    )


def darkest(image, rect: QRect) -> QColor:
    inside = rect.intersected(image.rect())
    pixels = (
        image.pixelColor(x, y)
        for x in range(inside.left(), inside.right() + 1)
        for y in range(inside.top(), inside.bottom() + 1)
    )
    return min(pixels, key=lambda color: color.lightness())


def test_the_open_menu_draws_headers_in_the_secondary_color(qtbot, picker):
    view = picker.combo.view()
    picker.combo.showPopup()
    try:
        qtbot.waitUntil(view.isVisible)
        menu = view.window()  # the popup paints the menu background behind the rows
        image = menu.grab().toImage()

        def drawn(text: str) -> QRect:
            rect = view.visualRect(row_index(picker, text))
            return rect.translated(view.viewport().mapTo(menu, rect.topLeft()) - rect.topLeft())

        first, header, voice = (
            drawn("Piper"),
            drawn("Kokoro"),
            drawn("Heart (US, female) · Kokoro · bf16"),
        )

        assert header.height() == first.height() + tokens.SECTION_HEADER_GAP
        ink = darkest(image, header)
        secondary = QColor(tokens.TEXT_SECONDARY_LIGHT)
        assert abs(ink.lightness() - secondary.lightness()) <= 8  # its full-coverage pixels
        assert darkest(image, voice).lightness() < ink.lightness()  # voices keep the label ink
    finally:
        picker.combo.hidePopup()
