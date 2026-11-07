"""Native-looking pieces the main window needs that Qt does not draw well on macOS."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QPlainTextEdit,
    QStyle,
    QStyleOption,
    QStyleOptionFocusRect,
    QStylePainter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cloudyreader.gui import tokens

_LEFT_CENTER = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_FOLLOW = {QEvent.Type.FocusIn, QEvent.Type.FocusOut, QEvent.Type.Move, QEvent.Type.Resize}
_FOLLOW |= {QEvent.Type.Show, QEvent.Type.Hide}
_SHOWN = {QEvent.Type.ShowToParent, QEvent.Type.HideToParent}  # a child shown or hidden itself
_TABULAR = QFont.Tag("tnum")  # OpenType tabular figures: every digit one width
# Each corner of a continuous rect, clockwise: where it sits on the rect, then the unit steps of
# the edge running into it and of the edge running out of it.
_CORNERS = (
    ("topRight", (1, 0), (0, 1)),
    ("bottomRight", (0, 1), (-1, 0)),
    ("bottomLeft", (-1, 0), (0, -1)),
    ("topLeft", (0, -1), (1, 0)),
)


def text_style(points: int) -> QFont:
    """The system font at one step of the type ramp, scaled with the system body size."""
    font = QFont(QApplication.font())
    font.setPointSizeF(font.pointSizeF() * points / tokens.TEXT_BODY_PT)
    return font


def tabular(font: QFont) -> QFont:
    """The font with tabular figures, so a number that counts up does not jitter."""
    font = QFont(font)
    font.setFeature(_TABULAR, 1)
    return font


def _unit(dx: float, dy: float, fallback: tuple[int, int]) -> tuple[float, float]:
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length else fallback


def continuous_rect(rect: QRectF, radius: float) -> QPainterPath:
    """A rounded rect whose corners ease into its edges (continuous curvature), as macOS draws.

    Each corner is a cubic, a short circular arc (itself a cubic) and a cubic, after Figma's
    corner-smoothing construction, over (1 + CORNER_SMOOTHING) * radius of both edges. A rect
    too small for that gives up smoothing first, then radius. CORNER_SMOOTHING 0 is circular.
    """
    path = QPainterPath()
    span = min((1 + tokens.CORNER_SMOOTHING) * radius, min(rect.width(), rect.height()) / 2)
    if radius <= 0 or span <= 0:
        path.addRect(rect)
        return path
    smoothing = max(0.0, min(tokens.CORNER_SMOOTHING, span / radius - 1))
    radius = min(radius, span)
    arc = math.radians(90 * (1 - smoothing))  # the circular part of each corner
    arc_length = math.sin(arc / 2) * radius * math.sqrt(2)
    ease = math.radians(45 * smoothing)
    c = radius * math.tan(ease / 2) * math.cos(ease)
    d = c * math.tan(ease)
    b = (span - arc_length - c - d) / 3
    a = 2 * b
    handle = 4 / 3 * math.tan(arc / 4) * radius  # a cubic's best fit to a circular arc
    for index, (name, (ux, uy), (vx, vy)) in enumerate(_CORNERS):
        corner = getattr(rect, name)()

        def at(back: float, on: float, k: QPointF = corner, u=(ux, uy), v=(vx, vy)) -> QPointF:
            """back along the incoming edge from the corner, then on along the outgoing one."""
            return QPointF(k.x() - u[0] * back + v[0] * on, k.y() - u[1] * back + v[1] * on)

        start, eased_in, eased_out = at(span, 0), at(span - a - b, 0), at(0, span - a - b)
        arc_in, arc_out = at(span - a - b - c, d), at(d, span - a - b - c)
        if index == 0:
            path.moveTo(start)
        else:
            path.lineTo(start)
        path.cubicTo(at(span - a, 0), eased_in, arc_in)
        tx, ty = _unit(arc_in.x() - eased_in.x(), arc_in.y() - eased_in.y(), (ux, uy))
        sx, sy = _unit(eased_out.x() - arc_out.x(), eased_out.y() - arc_out.y(), (vx, vy))
        path.cubicTo(
            QPointF(arc_in.x() + tx * handle, arc_in.y() + ty * handle),
            QPointF(arc_out.x() - sx * handle, arc_out.y() - sy * handle),
            arc_out,
        )
        path.cubicTo(eased_out, at(0, span - a), at(0, span))
    path.closeSubpath()
    return path


class DisclosureButton(QToolButton):
    """A disclosure triangle beside its label, like NSButton's disclosure bezel.

    QMacStyle frames every QToolButton outside a toolbar, auto-raise or not, so this one paints
    the style's own branch indicator (the native triangle on macOS) and the label itself.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setAutoRaise(True)
        title = text_style(tokens.TEXT_BODY_PT)  # tool buttons default to the small font
        title.setWeight(QFont.Weight.DemiBold)  # a section title, as in Finder's Get Info window
        self.setFont(title)
        self.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect)  # QMacStyle's focus ring
        self.toggled.connect(self._sync_arrow)
        self._sync_arrow(False)

    def _sync_arrow(self, expanded: bool) -> None:
        self.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        pad = self.style().pixelMetric(QStyle.PixelMetric.PM_FocusFrameVMargin, None, self)
        width = tokens.DISCLOSURE_SIZE + tokens.INDICATOR_SPACING
        width += metrics.horizontalAdvance(self.text())
        return QSize(width, max(tokens.DISCLOSURE_SIZE, metrics.height()) + 2 * pad)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QStylePainter(self)
        size = tokens.DISCLOSURE_SIZE
        option = QStyleOption()
        option.initFrom(self)
        option.rect = QRect(0, (self.height() - size) // 2, size, size)
        option.state |= QStyle.StateFlag.State_Children
        if self.isChecked():
            option.state |= QStyle.StateFlag.State_Open
        painter.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorBranch, option)
        text_rect = self.rect().adjusted(size + tokens.INDICATOR_SPACING, 0, 0, 0)
        painter.drawItemText(
            text_rect,
            _LEFT_CENTER,
            self.palette(),
            self.isEnabled(),
            self.text(),
            QPalette.ColorRole.WindowText,
        )
        if self.hasFocus():  # styles other than macOS draw their focus frame here
            focus = QStyleOptionFocusRect()
            focus.initFrom(self)
            painter.drawPrimitive(QStyle.PrimitiveElement.PE_FrameFocusRect, focus)


class Card(QWidget):
    """A rounded surface around one text view: the question card or the spoken-script panel.

    It paints the fill and, when it has one, the outline, on continuous corners. The view inside
    has no frame and no background of its own, so the fill shows through; its text sits padding
    from the edge: CARD_PADDING for the question, PANEL_PADDING for the script.
    The card shows and hides with its view, so callers keep toggling the view alone.
    """

    def __init__(
        self,
        view: QPlainTextEdit,
        parent: QWidget | None = None,
        *,
        padding: int = tokens.CARD_PADDING,
    ) -> None:
        super().__init__(parent)
        self.view = view
        self._fill: QColor | None = None  # None: the system's text background, QPalette.Base
        self._border: QColor | None = None
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.viewport().setAutoFillBackground(False)
        # Half the radius keeps the view's square corners, and a scroll bar, inside the rounded
        # ones and clear of the outline; the document margin adds the rest of the padding.
        inset = tokens.CARD_RADIUS // 2
        layout = QVBoxLayout(self)
        layout.setContentsMargins(inset, inset, inset, inset)
        layout.addWidget(view)
        view.document().setDocumentMargin(padding - inset)
        # Never a Tab stop of its own: Qt tabs into a proxied widget wherever the chain holds
        # it, which wrapped Tab from Speak into the script, so a click forwards instead.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFocusProxy(view)
        if view.isHidden():
            self.hide()
        view.installEventFilter(self)

    @property
    def fill(self) -> QColor:
        if self._fill is None:
            return self.palette().color(QPalette.ColorRole.Base)
        return QColor(self._fill)

    @property
    def border(self) -> QColor | None:
        return None if self._border is None else QColor(self._border)

    def set_colors(self, fill: QColor | None, border: QColor | None = None) -> None:
        self._fill, self._border = fill, border
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.view.setFocus(Qt.FocusReason.MouseFocusReason)  # a click on the padding edits too
        super().mousePressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.view and event.type() in _SHOWN:
            self.setVisible(event.type() == QEvent.Type.ShowToParent)
        return False

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect, radius = QRectF(self.rect()), float(tokens.CARD_RADIUS)
        if self._border is None:
            painter.setPen(Qt.PenStyle.NoPen)
        else:  # a stroke straddles its path: move it in by half, so all of it shows
            half = tokens.BORDER_WIDTH / 2
            rect, radius = rect.adjusted(half, half, -half, -half), radius - half
            painter.setPen(QPen(self._border, tokens.BORDER_WIDTH))
        painter.setBrush(self.fill)
        painter.drawPath(continuous_rect(rect, radius))


class FocusRing(QWidget):
    """A two-tone focus ring around a custom surface: a contrast stroke, then the accent.

    The system accent alone is 2.52:1 on a dark window, under the 3:1 a focus indicator needs, so
    the inner stroke carries the contrast. Native controls keep the native ring: this one rings
    only the surfaces track() names, drawn outside their edge, above their siblings.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._frames: dict[QWidget, tuple[QWidget, int]] = {}  # focus widget: frame, radius
        self._radius = 0
        self._inner = QColor(tokens.FOCUS_INNER_LIGHT)
        self.hide()

    @property
    def inner_color(self) -> QColor:
        return QColor(self._inner)

    def track(self, focus: QWidget, frame: QWidget, radius: int = 0) -> None:
        """Ring frame, whose corners have radius, while focus has the keyboard focus."""
        focus.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)  # one ring, not two
        for watched in (focus, frame):
            watched.installEventFilter(self)
        self._frames[focus] = (frame, radius)
        self._follow()

    def set_dark(self, dark: bool) -> None:
        self._inner = QColor(tokens.FOCUS_INNER_DARK if dark else tokens.FOCUS_INNER_LIGHT)
        self.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in _FOLLOW:
            self._follow()
        return False

    def _follow(self) -> None:
        focused = next((f for f in self._frames if f.hasFocus()), None)
        frame, self._radius = self._frames[focused] if focused is not None else (None, 0)
        parent = self.parentWidget()
        if frame is None or parent is None or not frame.isVisible():
            self.hide()
            return
        reach = tokens.FOCUS_RADIUS_EXTRA  # both strokes, outside the frame's edge
        corner = frame.mapTo(parent, QPoint(0, 0))
        self.setGeometry(QRect(corner, frame.size()).adjusted(-reach, -reach, reach, reach))
        self.raise_()
        self.show()
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inner, outer, reach = (
            tokens.FOCUS_INNER_WIDTH,
            tokens.FOCUS_OUTER_WIDTH,
            tokens.FOCUS_RADIUS_EXTRA,
        )
        edge = QRectF(self.rect()).adjusted(reach, reach, -reach, -reach)
        accent = self.palette().color(QPalette.ColorRole.Accent)  # follows the system accent
        # Each stroke by its center line's distance past the frame's edge; radii grow with it.
        strokes = ((self._inner, inner, inner / 2), (accent, outer, inner + outer / 2))
        for color, width, middle in strokes:
            painter.setPen(QPen(color, width))
            radius = self._radius + middle
            painter.drawPath(
                continuous_rect(edge.adjusted(-middle, -middle, middle, middle), radius)
            )
