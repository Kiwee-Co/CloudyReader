"""Pixel goldens of the custom-painted surfaces, without text, at 2x in the four appearances.

A change that moves these pixels updates the PNGs on purpose, and someone looks at them:
CLOUDYREADER_UPDATE_GOLDENS=1 pytest tests/gui/test_goldens.py rewrites them.
"""

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QRegion
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from cloudyreader.gui import theme, tokens
from cloudyreader.gui.widgets import Card, FocusRing
from tests.gui.test_tokens import CARD, LOOKS

GOLDENS = Path(__file__).parent / "goldens"
UPDATE = os.environ.get("CLOUDYREADER_UPDATE_GOLDENS") == "1"
SCALE = 2
SIZE = (120, 64)
LEVELS = 8  # a channel may drift this far (antialiasing)
SHARE = 0.01  # on at most this share of the pixels
ACCENT = "#0a60ff"  # the system blue as Qt reports it on macOS: the ring's outer stroke
FORMAT = QImage.Format.Format_ARGB32


def render(widget: QWidget, width: int, height: int) -> QImage:
    """The widget's own paint on transparency: no window background, no children."""
    image = QImage(width * SCALE, height * SCALE, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(SCALE)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    widget.render(painter, QPoint(), QRegion(), QWidget.RenderFlag(0))
    painter.end()
    return image.convertToFormat(FORMAT)


def card(look: theme.Appearance, kind: str) -> QImage:
    roles = theme.roles(look)
    surface = Card(QPlainTextEdit())
    if kind == "question":  # the system Base fill, pinned to the value Qt reports
        surface.set_colors(
            QColor(CARD["DARK" if look.dark else "LIGHT"]), QColor(roles.card_border)
        )
    else:
        border = None if roles.panel_border is None else QColor(roles.panel_border)
        surface.set_colors(QColor(roles.panel_fill), border)
    surface.setFixedSize(*SIZE)  # under the text view's own minimum: the same on every Mac
    return render(surface, *SIZE)


def ring(look: theme.Appearance) -> QImage:
    parent = QWidget()
    overlay = FocusRing(parent)
    overlay.set_dark(look.dark)
    palette = overlay.palette()
    palette.setColor(QPalette.ColorRole.Accent, QColor(ACCENT))
    overlay.setPalette(palette)
    overlay._radius = tokens.CARD_RADIUS  # as track() sets it for a card
    reach = tokens.FOCUS_RADIUS_EXTRA
    width, height = SIZE[0] + 2 * reach, SIZE[1] + 2 * reach
    overlay.setGeometry(QRect(0, 0, width, height))
    overlay.show()  # the ring hides itself until a surface has focus
    return render(overlay, width, height)


def drift(first: QImage, second: QImage) -> float:
    """The share of pixels with a channel more than LEVELS apart; 1.0 for another size."""
    if first.size() != second.size():
        return 1.0
    a, b = first.convertToFormat(FORMAT), second.convertToFormat(FORMAT)
    stride, width = a.bytesPerLine(), a.width() * 4
    bits_a, bits_b = bytes(a.constBits()), bytes(b.constBits())
    off = 0
    for row in range(a.height()):
        line_a = bits_a[row * stride : row * stride + width]
        line_b = bits_b[row * stride : row * stride + width]
        for pixel in range(0, width, 4):
            channels = zip(line_a[pixel : pixel + 4], line_b[pixel : pixel + 4], strict=True)
            if any(abs(x - y) > LEVELS for x, y in channels):
                off += 1
    return off / (a.width() * a.height())


CASES = [
    pytest.param(f"{kind}-{name}", look, kind, id=f"{kind}-{name}")
    for name, look in LOOKS.items()
    for kind in ("question", "panel", "ring")
]


@pytest.mark.parametrize(("name", "look", "kind"), CASES)
def test_the_surface_matches_its_golden(qapp, name, look, kind):
    image = ring(look) if kind == "ring" else card(look, kind)
    path = GOLDENS / f"{name}.png"
    if UPDATE:
        GOLDENS.mkdir(exist_ok=True)
        image.save(str(path))
    golden = QImage(str(path))

    assert not golden.isNull(), (
        f"missing golden {path.name}: run with CLOUDYREADER_UPDATE_GOLDENS=1"
    )
    assert drift(image, golden) <= SHARE


def test_the_drift_measure_tells_a_moved_shape_from_the_same_one(qapp):
    look = LOOKS["light"]
    same, other = card(look, "question"), card(LOOKS["dark"], "question")

    assert drift(same, card(look, "question")) == 0
    assert drift(same, other) > SHARE
