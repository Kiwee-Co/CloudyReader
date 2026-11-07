"""The About panel: laid out like the system one, a centered column with no buttons."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import QDialog, QLabel, QLayout, QVBoxLayout, QWidget

from cloudyreader.gui import tokens
from cloudyreader.gui.widgets import tabular, text_style

_CENTER = Qt.AlignmentFlag.AlignHCenter


def _label(text: str, font: QFont) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)  # a name or version is never markup
    label.setFont(font)
    return label


class AboutPanel(QDialog):
    """The About window: app icon, name, version and a one-line description, centered.

    No buttons: the close button, Escape or Command-W closes it. It is never modal and deletes
    itself on close, so its owner holds one at a time and drops it on `finished`.
    """

    def __init__(
        self, name: str, version: str, description: str, icon: QIcon, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {name}")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(tokens.MARGIN,) * 4)
        layout.setSpacing(0)
        # Height to content, and no resizing: the system panel has neither.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        # Created in reading order: VoiceOver walks the children in this order.
        self.icon_label: QLabel | None = None
        if not icon.isNull():
            self.icon_label = QLabel()
            self.icon_label.setAccessibleName(f"{name} icon")
            self.icon_label.setPixmap(icon.pixmap(tokens.ABOUT_ICON_SIZE, tokens.ABOUT_ICON_SIZE))
            layout.addWidget(self.icon_label, 0, _CENTER)
            layout.addSpacing(tokens.ABOUT_ICON_GAP)
        title = text_style(tokens.TEXT_TITLE_PT)
        title.setWeight(QFont.Weight.DemiBold)
        self.name_label = _label(name, title)
        layout.addWidget(self.name_label, 0, _CENTER)
        layout.addSpacing(tokens.ABOUT_LINE_GAP)
        section = text_style(tokens.TEXT_SECTION_PT)
        self.version_label = _label(f"Version {version}", tabular(section))
        self.version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.version_label, 0, _CENTER)
        layout.addSpacing(tokens.GROUP_SPACING)
        self.description_label = _label(description, section)
        # The widest label sets the panel's width: this one fills the column of an ABOUT_WIDTH
        # panel, and a longer description widens the panel instead of wrapping.
        self.description_label.setMinimumWidth(tokens.ABOUT_WIDTH - 2 * tokens.MARGIN)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.description_label, 0, _CENTER)
        QShortcut(QKeySequence("Ctrl+W"), self, self.close)  # Command-W, as File > Close Window

    def set_secondary(self, color: QColor) -> None:
        """The version and description in the appearance's secondary text color."""
        palette = QPalette()  # fresh, so every other role keeps following the system
        palette.setColor(QPalette.ColorRole.WindowText, color)
        for label in (self.version_label, self.description_label):
            label.setPalette(palette)
