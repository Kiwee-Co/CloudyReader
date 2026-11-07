"""The status bar: a message after its tone glyph, and the elided labels that share its line."""

from __future__ import annotations

import enum
import re

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QHelpEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QPolygonF,
    QResizeEvent,
)
from PySide6.QtWidgets import QLabel, QStatusBar, QStyle, QStyleOption, QToolTip, QWidget

from cloudyreader.gui import theme, tokens
from cloudyreader.gui.widgets import tabular, text_style

_LEFT_CENTER = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_MB, _GB = 10**6, 10**9  # decimal units, as Finder counts them


class Tone(enum.Enum):
    """How serious a status message is. Never shown by color alone: the text says it too."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


_GLYPH_TONES = frozenset({Tone.WARNING, Tone.ERROR})  # information shows no glyph
_TONE_WORDS = {Tone.WARNING: "Warning", Tone.ERROR: "Error"}


def paint_tone_glyph(painter: QPainter, rect: QRect | QRectF, tone: Tone, color: QColor) -> None:
    """Draw the tone's line glyph in rect: a triangle for a warning, a circle for an error, each
    around an exclamation mark. Two shapes, so the tone never rests on color alone."""
    if tone not in _GLYPH_TONES:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    box = QRectF(rect)
    painter.translate(box.topLeft())
    scale = box.width() / tokens.GLYPH_BOX  # the geometry is drawn on the GLYPH_BOX grid
    painter.scale(scale, scale)
    pen = QPen(color, tokens.STATUS_GLYPH_STROKE)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if tone is Tone.WARNING:
        painter.drawPolygon(QPolygonF([QPointF(*point) for point in tokens.GLYPH_WARNING_OUTLINE]))
        bar, dot = tokens.GLYPH_WARNING_BAR, tokens.GLYPH_WARNING_DOT
    else:
        radius = tokens.GLYPH_ERROR_RADIUS
        painter.drawEllipse(QPointF(*tokens.GLYPH_ERROR_CENTER), radius, radius)
        bar, dot = tokens.GLYPH_ERROR_BAR, tokens.GLYPH_ERROR_DOT
    painter.drawLine(QPointF(*bar[0]), QPointF(*bar[1]))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QPointF(*dot), tokens.GLYPH_DOT_RADIUS, tokens.GLYPH_DOT_RADIUS)
    painter.restore()


def size_text(size: int) -> str:
    """A byte count as Finder says it: "330 MB", and "2.0 GB" from a thousand megabytes on."""
    megabytes = round(size / _MB)
    return f"{size / _GB:.1f} GB" if megabytes >= _GB // _MB else f"{megabytes} MB"


def download_variants(title: str, percent: int, done: int, total: int) -> tuple[str, str, str]:
    """The download label's wordings, longest first: short of room it drops the sizes, then the
    verb. Under a gigabyte the unit is said once: "139 of 330 MB", else "829 MB of 2.0 GB"."""
    whole, part = size_text(total), size_text(done)
    if whole.endswith(" MB"):
        part = part.removesuffix(" MB")
    running = f"Downloading {title}… {percent}%"
    return f"{running} ({part} of {whole})", running, f"{title} {percent}%"


def _named(text: str, tone: Tone) -> str:
    """The message as VoiceOver names it: with its tone word, unless the text starts with it."""
    word = _TONE_WORDS.get(tone)
    if word is None or not text or re.match(rf"(\d+ )?{word}s?\b", text, re.IGNORECASE):
        return text  # "Warning: …" and "2 warnings: …" say it already
    return f"{word}: {text}"


class ElidedLabel(QLabel):
    """A one-line label that gives up width first: short of room it elides at the end, and its
    tooltip then shows the whole text above the tooltip it was given.

    set_variants() gives it shorter wordings of its text: it shows the longest that fits whole
    and elides only the shortest. text() stays the longest; a later setText() drops them.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._variants: tuple[str, ...] = ()

    def set_variants(self, longest: str, *shorter: str) -> None:
        super().setText(longest)
        self._variants = (longest, *shorter)

    def setText(self, text: str) -> None:
        self._variants = ()  # a plain text has no shorter wordings
        super().setText(text)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def shown_text(self) -> str:
        """What the label paints: the longest wording that fits, else the shortest, elided."""
        room, metrics = self.contentsRect().width(), self.fontMetrics()
        wordings = self._variants or (self.text(),)
        # Fit as the painter does: an integer advance can round a slightly wider text down.
        cuts = [metrics.elidedText(text, Qt.TextElideMode.ElideRight, room) for text in wordings]
        whole = (cut for cut, text in zip(cuts, wordings, strict=True) if cut == text)
        return next(whole, cuts[-1])

    def is_elided(self) -> bool:
        return self.shown_text() != self.text()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self.contentsRect()
        text = self.shown_text()
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
    """QStatusBar that draws its message after a tone glyph, at the window margin, elided.

    showMessage() and currentMessage() work as usual; show_message() also sets the tone.
    Information reads quietly in the secondary ink; set_roles() gives the appearance's colors.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tone = Tone.INFO
        self._cluster: QWidget | None = None
        self._roles = theme.roles(theme.current())  # until the window passes its appearance
        self.setFont(tabular(text_style(tokens.TEXT_CALLOUT_PT)))  # "Playing 2.4 s." holds still
        self.setSizeGripEnabled(False)  # macOS windows resize from any edge; no grip to make room
        self.setMinimumHeight(tokens.STATUS_LINE_HEIGHT)
        # Permanent widgets (the busy bar) keep the window margin; the message starts at it.
        self.setContentsMargins(tokens.MARGIN, 0, tokens.MARGIN, 0)
        self.messageChanged.connect(self._on_message_changed)

    @property
    def tone(self) -> Tone:
        return self._tone

    def set_roles(self, roles: theme.Roles) -> None:
        self._roles = roles
        self.update()

    def ink(self) -> QColor:
        """Information is quiet, in the secondary ink; a warning or an error, in the text color."""
        if self._tone is Tone.INFO:
            return QColor(self._roles.secondary_text)
        return self.palette().color(QPalette.ColorRole.WindowText)

    def glyph_color(self) -> QColor:
        """The warning or the error role; information has no glyph, so no valid color."""
        if self._tone is Tone.WARNING:
            return QColor(self._roles.warning)
        if self._tone is Tone.ERROR:
            return QColor(self._roles.error)
        return QColor()

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
            tokens.STATUS_ICON_SIZE + tokens.INDICATOR_SPACING if self._tone in _GLYPH_TONES else 0
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
        self._cap_cluster()  # a tone glyph needs room too
        self.setAccessibleName(_named(text, tone))  # the same text in a new tone sends no signal
        self.update()  # showMessage() repaints only when the text itself changes

    def _on_message_changed(self, text: str) -> None:
        if not text:
            self._tone = Tone.INFO
        self._cap_cluster()
        self.setAccessibleName(_named(text, self._tone))

    def message_layout(self) -> tuple[QRect, QRect, str]:
        """The icon rect (null for INFO), the text rect, and the message elided to fit it."""
        area = self.contentsRect()
        right = area.right()
        for child in self.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            if not child.isHidden():  # a permanent widget, or the size grip
                right = min(right, child.geometry().left() - tokens.GROUP_SPACING)
        left, icon_rect = area.left(), QRect()
        if self._tone in _GLYPH_TONES:
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
        if icon_rect.isValid():
            paint_tone_glyph(painter, icon_rect, self._tone, self.glyph_color())
        painter.setPen(self.ink())
        painter.drawText(text_rect, _LEFT_CENTER, text)
