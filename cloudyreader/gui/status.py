"""The status bar: a message after its tone icon, and the elided labels that share its line."""

from __future__ import annotations

import enum

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QHelpEvent, QPainter, QPaintEvent, QPalette, QResizeEvent
from PySide6.QtWidgets import QLabel, QStatusBar, QStyle, QStyleOption, QToolTip, QWidget

from cloudyreader.gui import tokens
from cloudyreader.gui.widgets import tabular, text_style

_LEFT_CENTER = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


class Tone(enum.Enum):
    """How serious a status message is. Never shown by color alone: the text says it too."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


_TONE_ICONS = {
    Tone.WARNING: QStyle.StandardPixmap.SP_MessageBoxWarning,
    Tone.ERROR: QStyle.StandardPixmap.SP_MessageBoxCritical,
}


class ElidedLabel(QLabel):
    """A one-line label that gives up width first: short of room it elides at the end, and its
    tooltip then shows the whole text above the tooltip it was given."""

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def is_elided(self) -> bool:
        return self.fontMetrics().horizontalAdvance(self.text()) > self.contentsRect().width()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        role = QPalette.ColorRole.WindowText
        align = self.alignment()  # set it right-aligned, and the text stays beside what follows
        self.style().drawItemText(painter, rect, align, self.palette(), True, text, role)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            if self.is_elided():
                whole = "\n".join(text for text in (self.text(), self.toolTip()) if text)
                QToolTip.showText(event.globalPos(), whole, self)
                return True
        return super().event(event)


class StatusBar(QStatusBar):
    """QStatusBar that draws its message after a tone icon, at the window margin, elided.

    showMessage() and currentMessage() work as usual; show_message() also sets the tone.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tone = Tone.INFO
        self._cluster: QWidget | None = None
        self.setFont(tabular(text_style(tokens.TEXT_CALLOUT_PT)))  # "Playing 2.4 s." holds still
        self.setSizeGripEnabled(False)  # macOS windows resize from any edge; no grip to make room
        self.setMinimumHeight(tokens.STATUS_LINE_HEIGHT)
        # Permanent widgets (the busy bar) keep the window margin; the message starts at it.
        self.setContentsMargins(tokens.MARGIN, 0, tokens.MARGIN, 0)
        self.messageChanged.connect(self._on_message_changed)

    @property
    def tone(self) -> Tone:
        return self._tone

    def add_cluster(self, cluster: QWidget) -> None:
        """Add a permanent widget that yields width to the message: the message gets what it
        needs, up to MESSAGE_MIN_SHARE of the line, and the cluster the rest."""
        self._cluster = cluster
        self.addPermanentWidget(cluster)
        self._cap_cluster()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._cap_cluster()

    def _message_width(self) -> int:
        """The width the message needs whole: its icon, then its text; 0 with no message."""
        if not self.currentMessage():
            return 0
        icon = (
            tokens.STATUS_ICON_SIZE + tokens.INDICATOR_SPACING if self._tone in _TONE_ICONS else 0
        )
        return icon + self.fontMetrics().horizontalAdvance(self.currentMessage())

    def _cap_cluster(self) -> None:
        if self._cluster is not None:
            area = self.contentsRect().width()
            keep = min(self._message_width(), area * tokens.MESSAGE_MIN_SHARE)
            self._cluster.setMaximumWidth(max(0, int(area - keep) - tokens.GROUP_SPACING))

    def show_message(self, text: str, tone: Tone = Tone.INFO) -> None:
        self._tone = tone
        self.showMessage(text)
        self._cap_cluster()  # a tone icon needs room too
        self.update()  # showMessage() repaints only when the text itself changes

    def _on_message_changed(self, text: str) -> None:
        if not text:
            self._tone = Tone.INFO
        self._cap_cluster()

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
