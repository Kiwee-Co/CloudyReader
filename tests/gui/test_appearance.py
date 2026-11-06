"""Live appearance: the custom-painted parts follow light and dark at once, with no restart."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

from cloudyreader.gui import tokens

ROLE = QPalette.ColorRole


def token(name: str, look: str) -> str:
    return QColor(getattr(tokens, f"{name}_{look}")).name()


def expected(look: str) -> dict[str, str]:
    return {
        "question placeholder": token("PLACEHOLDER", look),
        "card outline": token("CARD_BORDER", look),
        "panel fill": token("PANEL", look),
        "script text": token("TEXT_SECONDARY", look),
        "script placeholder": token("TEXT_SECONDARY", look),
        "voice menu headers": token("TEXT_SECONDARY", look),
        "focus ring inner stroke": token("FOCUS_INNER", look),
    }


def painted(window) -> dict[str, str]:
    script = window.script_view.palette()
    header = window.voice_picker.combo.model().item(0)
    return {
        "question placeholder": window.question_edit.palette().color(ROLE.PlaceholderText).name(),
        "card outline": window.question_card.border.name(),
        "panel fill": window.script_panel.fill.name(),
        "script text": script.color(ROLE.Text).name(),
        "script placeholder": script.color(ROLE.PlaceholderText).name(),
        "voice menu headers": header.foreground().color().name(),
        "focus ring inner stroke": window._focus_ring.inner_color.name(),  # private: an overlay
    }


def drawn(window) -> dict[str, str]:
    """The colors the parts paint now: the outline's edge and the panel's middle, grabbed."""
    card = window.question_card.grab().toImage()
    panel = window.script_panel.grab().toImage()
    return {
        "card outline": card.pixelColor(0, card.height() // 2).name(),
        "panel fill": panel.pixelColor(panel.width() // 2, panel.height() // 2).name(),
    }


def test_a_scheme_switch_repaints_every_custom_part_without_a_restart(window):
    window.script_toggle.click()
    hints = QGuiApplication.styleHints()

    for scheme, look in ((Qt.ColorScheme.Dark, "DARK"), (Qt.ColorScheme.Light, "LIGHT")):
        hints.colorSchemeChanged.emit(scheme)
        assert painted(window) == expected(look)
        assert drawn(window) == {k: expected(look)[k] for k in ("card outline", "panel fill")}


def test_the_focus_ring_strokes_in_the_new_appearance(qtbot, window):
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.question_edit.setFocus()
    qtbot.waitUntil(window.question_edit.hasFocus)
    ring = window._focus_ring  # private on purpose: the overlay has no public face

    QGuiApplication.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    image = ring.grab().toImage()

    edge = tokens.FOCUS_RADIUS_EXTRA - tokens.FOCUS_INNER_WIDTH
    assert image.pixelColor(QPoint(edge, image.height() // 2)).name() == token(
        "FOCUS_INNER", "DARK"
    )


def test_a_new_system_palette_alone_reapplies_the_tokens(make_window, qapp):
    # What a switch to Dark Mode brings even before, or without, a color scheme signal.
    window = make_window()
    assert painted(window) == expected("LIGHT")
    original = qapp.palette()
    dark = QPalette(original)
    dark.setColor(ROLE.Base, QColor("#171717"))
    try:
        qapp.setPalette(dark)
        qapp.processEvents()

        assert painted(window) == expected("DARK")
    finally:
        qapp.setPalette(original)
        qapp.processEvents()

    assert painted(window) == expected("LIGHT")
