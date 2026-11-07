"""The design-language pieces of widgets.py: continuous corners, the cards, the ring, the header."""

import math

import pytest
from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QColor, QFont, QPainterPath
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QWidget

from cloudyreader.gui import tokens, widgets
from cloudyreader.gui.widgets import Card, DisclosureButton, FocusRing, continuous_rect

RECT = QRectF(0, 0, 200, 100)
RADIUS = 10.0


def rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def outline(path: QPainterPath, steps: int = 2000) -> list[QPointF]:
    return [path.pointAtPercent(i / steps) for i in range(steps)]


def toward_center(point: QPointF, distance: float) -> QPointF:
    """The point moved this far toward RECT's center: just inside the path it lies on."""
    center = RECT.center()
    dx, dy = center.x() - point.x(), center.y() - point.y()
    length = math.hypot(dx, dy)
    return QPointF(point.x() + dx / length * distance, point.y() + dy / length * distance)


def test_a_continuous_rect_fills_exactly_its_rect():
    assert continuous_rect(RECT, RADIUS).boundingRect() == RECT


def test_a_zero_radius_gives_a_plain_rect():
    path = continuous_rect(RECT, 0)

    assert path.boundingRect() == RECT
    assert path.contains(QPointF(0.5, 0.5))  # the corner itself is filled


def test_a_continuous_rect_touches_every_edge_at_its_middle():
    path = continuous_rect(RECT, RADIUS)
    middles = [QPointF(100, 0.2), QPointF(199.8, 50), QPointF(100, 99.8), QPointF(0.2, 50)]

    assert all(path.contains(point) for point in middles)
    assert not path.contains(QPointF(0.5, 0.5))  # the corner is rounded off


def test_continuous_corners_sit_between_the_circular_ones_of_r_and_1_6_r():
    path = continuous_rect(RECT, RADIUS)
    inner = rounded(RECT, RADIUS * (1 + tokens.CORNER_SMOOTHING))
    outer = rounded(RECT, RADIUS)

    for point in outline(path):
        assert outer.contains(toward_center(point, 0.05)), point
        assert not inner.contains(toward_center(point, -0.05)), point


def test_a_continuous_corner_cuts_deeper_than_a_circular_one():
    path, circle = continuous_rect(RECT, RADIUS), rounded(RECT, RADIUS)
    near = [QPointF(0.8 * RADIUS, 0.03 * RADIUS), QPointF(200 - 0.8 * RADIUS, 100 - 0.03 * RADIUS)]

    for point in near:  # the circle still fills it; the eased corner has already left the edge
        assert circle.contains(point) and not path.contains(point), point


def test_without_smoothing_the_corners_are_circular(monkeypatch):
    monkeypatch.setattr(tokens, "CORNER_SMOOTHING", 0.0)
    circle = rounded(RECT, RADIUS)

    for point in outline(continuous_rect(RECT, RADIUS)):
        assert circle.contains(toward_center(point, 0.05)), point
        assert not circle.contains(toward_center(point, -0.05)), point


def test_a_radius_too_big_for_the_rect_still_fits_it():
    small = QRectF(0, 0, 20, 12)

    assert continuous_rect(small, RADIUS).boundingRect() == small


def test_the_card_takes_its_padding_and_keeps_the_text_inside_the_corners(qapp):
    question = Card(QPlainTextEdit(), padding=tokens.CARD_PADDING)
    script = Card(QPlainTextEdit(), padding=tokens.PANEL_PADDING)

    for card, padding in ((question, tokens.CARD_PADDING), (script, tokens.PANEL_PADDING)):
        inset = card.layout().contentsMargins().left()
        assert inset + card.view.document().documentMargin() == padding
        assert inset > tokens.CARD_RADIUS * (1 - 2**-0.5) + tokens.BORDER_WIDTH


def test_the_card_defaults_to_the_question_padding(qapp):
    card = Card(QPlainTextEdit())

    assert card.layout().contentsMargins().left() + card.view.document().documentMargin() == (
        tokens.CARD_PADDING
    )


def test_the_card_paints_its_continuous_rect(qapp, monkeypatch):
    calls = []

    def spy(rect, radius):
        calls.append((rect, radius))
        return continuous_rect(rect, radius)

    monkeypatch.setattr(widgets, "continuous_rect", spy)
    card = Card(QPlainTextEdit())
    card.set_colors(QColor("#ffffff"), QColor("#818186"))
    card.setFixedSize(120, 64)  # under the text view's own minimum, so the size is ours
    card.grab()

    half = tokens.BORDER_WIDTH / 2
    assert calls == [(QRectF(0, 0, 120, 64).adjusted(half, half, -half, -half), RADIUS - half)]


def test_the_focus_ring_paints_two_concentric_continuous_rects(qapp, monkeypatch):
    calls = []

    def spy(rect, radius):
        calls.append((rect, radius))
        return continuous_rect(rect, radius)

    monkeypatch.setattr(widgets, "continuous_rect", spy)
    parent = QWidget()
    ring = FocusRing(parent)
    ring._radius = tokens.CARD_RADIUS
    reach = tokens.FOCUS_RADIUS_EXTRA
    ring.setGeometry(QRect(0, 0, 100 + 2 * reach, 50 + 2 * reach))
    ring.grab()

    edge = QRectF(reach, reach, 100, 50)
    inner, outer = tokens.FOCUS_INNER_WIDTH, tokens.FOCUS_OUTER_WIDTH
    middles = (inner / 2, inner + outer / 2)
    expected = [(edge.adjusted(-m, -m, m, m), tokens.CARD_RADIUS + m) for m in middles]
    assert calls == expected


def test_the_spoken_script_header_is_a_semibold_body_title(qapp):
    button = DisclosureButton("Spoken script")
    body = QApplication.font().pointSizeF()

    assert button.font().weight() == QFont.Weight.DemiBold
    assert button.font().pointSizeF() == pytest.approx(body)
    assert button.sizeHint().width() >= button.fontMetrics().horizontalAdvance("Spoken script")
