"""Native-looking pieces the main window needs that Qt does not draw well on macOS."""

from __future__ import annotations

import enum

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFont, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QStatusBar,
    QStyle,
    QStyleOption,
    QStyleOptionFocusRect,
    QStylePainter,
    QToolButton,
    QWidget,
)

from cloudyreader.gui import tokens

_LEFT_CENTER = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


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
