"""Native-looking pieces the main window needs that Qt does not draw well on macOS."""

from __future__ import annotations

import enum

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QPlainTextEdit,
    QStatusBar,
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


def text_style(points: int) -> QFont:
    """The system font at one step of the type ramp, scaled with the system body size."""
    font = QFont(QApplication.font())
    font.setPointSizeF(font.pointSizeF() * points / tokens.TEXT_BODY_PT)
    return font


class Tone(enum.Enum):
    """How serious a status message is. Never shown by color alone: the text says it too."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


_TONE_ICONS = {
    Tone.WARNING: QStyle.StandardPixmap.SP_MessageBoxWarning,
    Tone.ERROR: QStyle.StandardPixmap.SP_MessageBoxCritical,
}


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
        self.setFont(text_style(tokens.TEXT_BODY_PT))  # tool buttons default to the small font
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

    It paints the fill and, when it has one, the outline. The view inside has no frame and no
    background of its own, so the fill shows through; its text sits CARD_PADDING from the edge.
    The card shows and hides with its view, so callers keep toggling the view alone.
    """

    def __init__(self, view: QPlainTextEdit, parent: QWidget | None = None) -> None:
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
        view.document().setDocumentMargin(tokens.CARD_PADDING - inset)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # a click on the padding edits too
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
        painter.drawRoundedRect(rect, radius, radius)


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
            painter.drawRoundedRect(edge.adjusted(-middle, -middle, middle, middle), radius, radius)


class StatusBar(QStatusBar):
    """QStatusBar that draws its message after a tone icon, at the window margin, elided.

    showMessage() and currentMessage() work as usual; show_message() also sets the tone.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tone = Tone.INFO
        self.setFont(text_style(tokens.TEXT_CALLOUT_PT))
        self.setSizeGripEnabled(False)  # macOS windows resize from any edge; no grip to make room
        # Permanent widgets (the busy bar) keep the window margin; the message starts at it.
        self.setContentsMargins(tokens.MARGIN, 0, tokens.MARGIN, 0)
        self.messageChanged.connect(self._on_message_changed)

    @property
    def tone(self) -> Tone:
        return self._tone

    def show_message(self, text: str, tone: Tone = Tone.INFO) -> None:
        self._tone = tone
        self.showMessage(text)
        self.update()  # showMessage() repaints only when the text itself changes

    def _on_message_changed(self, text: str) -> None:
        if not text:
            self._tone = Tone.INFO

    def message_layout(self) -> tuple[QRect, QRect, str]:
        """The icon rect (null for INFO), the text rect, and the message elided to fit it."""
        area = self.contentsRect()
        right = area.right()
        for child in self.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            if not child.isHidden():  # a permanent widget, or the size grip
                right = min(right, child.geometry().left() - tokens.GROUP_SPACING)
        left, icon_rect = area.left(), QRect()
        if self._tone in _TONE_ICONS:
            size = tokens.STATUS_ICON_SIZE
            icon_rect = QRect(left, area.center().y() - size // 2, size, size)
            left = icon_rect.right() + 1 + tokens.INDICATOR_SPACING
        text_rect = QRect(left, area.top(), max(0, right - left + 1), area.height())
        elided = self.fontMetrics().elidedText(
            self.currentMessage(), Qt.TextElideMode.ElideRight, text_rect.width()
        )
        return icon_rect, text_rect, elided

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_PanelStatusBar, option, painter, self)
        if not self.currentMessage():
            return
        icon_rect, text_rect, text = self.message_layout()
        if icon_rect.isValid():  # full-color system alert badges: legible in both appearances
            self.style().standardIcon(_TONE_ICONS[self._tone], None, self).paint(painter, icon_rect)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.drawText(text_rect, _LEFT_CENTER, text)
