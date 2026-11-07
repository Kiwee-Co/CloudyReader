"""The status bar's tone glyphs: line shapes from tokens.py, in each appearance's role colors."""

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from cloudyreader.gui import status, theme, tokens
from cloudyreader.gui.status import StatusBar, Tone, paint_tone_glyph
from tests.gui.test_tokens import LOOKS

GOLDENS = Path(__file__).parent / "goldens"
SCALE = 2  # drawn for a Retina display, where a 1.5 pt stroke is three pixels
MARGIN = 4  # room around the box: any ink that leaves the box lands here
# Antialiasing drifts a little between Qt builds; a wrong shape or color moves far more pixels.
TOLERANCE_SHARE, TOLERANCE_LEVELS = 0.01, 8
GLYPH_ROLE = {Tone.WARNING: "warning", Tone.ERROR: "error"}
CASES = [
    pytest.param(tone, name, id=f"{tone.value}-{name}") for tone in GLYPH_ROLE for name in LOOKS
]


def role_color(tone: Tone, name: str) -> QColor:
    return QColor(getattr(theme.roles(LOOKS[name]), GLYPH_ROLE[tone]))


def render(tone: Tone, color: QColor, margin: int = 0) -> QImage:
    """The glyph alone on a transparent 2x canvas: its 16 pt box, plus margin on every side."""
    side = (tokens.STATUS_ICON_SIZE + 2 * margin) * SCALE
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(SCALE)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    box = QRect(margin, margin, tokens.STATUS_ICON_SIZE, tokens.STATUS_ICON_SIZE)
    paint_tone_glyph(painter, box, tone, color)
    painter.end()
    return image


def inked(image: QImage) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 0
    ]


def differing_share(image: QImage, golden: QImage) -> float:
    """The share of pixels where some channel differs by more than TOLERANCE_LEVELS."""
    first = image.convertToFormat(QImage.Format.Format_ARGB32)
    second = golden.convertToFormat(QImage.Format.Format_ARGB32)
    assert (first.width(), first.height()) == (second.width(), second.height())
    differ = 0
    for y in range(first.height()):
        for x in range(first.width()):
            a, b = first.pixelColor(x, y), second.pixelColor(x, y)
            channels = zip(a.getRgb(), b.getRgb(), strict=True)
            differ += any(abs(p - q) > TOLERANCE_LEVELS for p, q in channels)
    return differ / (first.width() * first.height())


@pytest.mark.parametrize(("tone", "name"), CASES)
def test_each_glyph_draws_inside_its_16_pt_box(qapp, tone, name):
    image = render(tone, role_color(tone, name), MARGIN)
    low, high = MARGIN * SCALE, (MARGIN + tokens.STATUS_ICON_SIZE) * SCALE

    pixels = inked(image)

    assert pixels  # not blank
    assert all(low <= x < high and low <= y < high for x, y in pixels)


@pytest.mark.parametrize(("tone", "name"), CASES)
def test_each_glyph_matches_its_golden(qapp, tone, name):
    image = render(tone, role_color(tone, name))
    golden_path = GOLDENS / f"tone-glyph-{tone.value}-{name}.png"
    if os.environ.get("CLOUDYREADER_UPDATE_GOLDENS") == "1":  # as tests/gui/test_goldens.py does
        image.save(str(golden_path))

    golden = QImage(str(golden_path))

    assert not golden.isNull(), golden_path
    assert differing_share(image, golden) <= TOLERANCE_SHARE


def test_the_two_shapes_differ_so_the_tone_never_rests_on_color(qapp):
    ink = QColor(tokens.TEXT_SECONDARY_LIGHT)  # one color for both: only the shape tells them apart

    warning, error = render(Tone.WARNING, ink), render(Tone.ERROR, ink)

    assert differing_share(warning, error) > 10 * TOLERANCE_SHARE


def test_information_draws_no_glyph(qapp):
    assert inked(render(Tone.INFO, QColor(tokens.TEXT_SECONDARY_LIGHT), MARGIN)) == []


@pytest.mark.parametrize(("tone", "name"), CASES)
def test_the_glyph_takes_its_tone_role_in_every_appearance(qtbot, tone, name):
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.set_roles(theme.roles(LOOKS[name]))

    bar.show_message("Some status text", tone)

    assert bar.glyph_color() == role_color(tone, name)


def test_information_has_no_glyph_color(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)

    bar.show_message("Stopped.")

    assert not bar.glyph_color().isValid()


@pytest.mark.parametrize("tone", list(GLYPH_ROLE))
def test_the_status_bar_paints_the_glyph_in_its_box_and_role_color(qtbot, monkeypatch, tone):
    drawn = []
    monkeypatch.setattr(
        status,
        "paint_tone_glyph",
        lambda _painter, rect, tone, color: drawn.append((QRect(rect), tone, QColor(color))),
    )
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.resize(400, tokens.STATUS_LINE_HEIGHT)
    bar.set_roles(theme.roles(LOOKS["dark"]))
    bar.show_message("Some status text", tone)

    bar.grab()

    icon, _text, _elided = bar.message_layout()
    assert drawn == [(icon, tone, role_color(tone, "dark"))]
