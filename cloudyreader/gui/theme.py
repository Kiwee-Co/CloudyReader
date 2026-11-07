"""The color roles of each appearance: light or dark, standard or increased contrast.

roles() is pure data over tokens.py, so tests compute every contrast ratio from it. current()
reads the appearance from Qt's style hints. Native controls keep the system's own colors.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPalette, QStyleHints

from cloudyreader.gui import tokens


@dataclass(frozen=True)
class Appearance:
    dark: bool = False
    high_contrast: bool = False


@dataclass(frozen=True)
class Roles:
    """The colors the custom-painted parts use, as hex strings."""

    placeholder: str
    secondary_text: str
    panel_fill: str
    card_border: str
    panel_border: str | None  # only increased contrast outlines the script panel
    focus_inner: str
    warning: str  # the status bar's tone glyphs
    error: str
    field_placeholder: str  # a disabled pop-up's placeholder on its dimmed bezel


def roles(look: Appearance) -> Roles:
    suffix = ("HC_" if look.high_contrast else "") + ("DARK" if look.dark else "LIGHT")

    def token(name: str) -> str:
        return str(getattr(tokens, f"{name}_{suffix}"))

    border = token("CARD_BORDER")
    return Roles(
        placeholder=token("PLACEHOLDER"),
        secondary_text=token("TEXT_SECONDARY"),
        panel_fill=token("PANEL"),
        card_border=border,
        panel_border=border if look.high_contrast else None,
        focus_inner=tokens.FOCUS_INNER_DARK if look.dark else tokens.FOCUS_INNER_LIGHT,
        warning=token("TONE_WARNING"),
        error=token("TONE_ERROR"),
        field_placeholder=token("FIELD_PLACEHOLDER"),
    )


def current(hints: QStyleHints | None = None) -> Appearance:
    """The system's appearance now: the application's style hints unless a test passes its own."""
    if hints is None:
        hints = QGuiApplication.styleHints()
    scheme = hints.colorScheme()
    if scheme == Qt.ColorScheme.Unknown:  # no word from the platform: judge the background
        # The application's: a child's palette can update after a window hears of the change.
        base = QGuiApplication.palette().color(QPalette.ColorRole.Base)
        scheme = Qt.ColorScheme.Dark if base.lightness() < 128 else Qt.ColorScheme.Light
    accessibility = getattr(hints, "accessibility", None)  # Qt 6.10 and later
    preference = accessibility().contrastPreference() if callable(accessibility) else None
    high = preference == Qt.ContrastPreference.HighContrast
    return Appearance(dark=scheme == Qt.ColorScheme.Dark, high_contrast=high)
