"""theme.py: the color roles of each appearance come from tokens.py; current() reads Qt's hints."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

from cloudyreader.gui import theme, tokens

LIGHT = theme.Appearance(dark=False, high_contrast=False)
DARK = theme.Appearance(dark=True, high_contrast=False)
HC_LIGHT = theme.Appearance(dark=False, high_contrast=True)
HC_DARK = theme.Appearance(dark=True, high_contrast=True)
SUFFIXES = [(LIGHT, "LIGHT"), (DARK, "DARK"), (HC_LIGHT, "HC_LIGHT"), (HC_DARK, "HC_DARK")]
ROLE_TOKENS = {
    "placeholder": "PLACEHOLDER",
    "secondary_text": "TEXT_SECONDARY",
    "panel_fill": "PANEL",
    "card_border": "CARD_BORDER",
    "warning": "TONE_WARNING",
    "error": "TONE_ERROR",
    "field_placeholder": "FIELD_PLACEHOLDER",
}


@pytest.mark.parametrize(("look", "suffix"), SUFFIXES, ids=[s for _, s in SUFFIXES])
def test_each_role_is_the_token_of_its_appearance(look, suffix):
    roles = theme.roles(look)

    for role, token in ROLE_TOKENS.items():
        assert getattr(roles, role) == getattr(tokens, f"{token}_{suffix}"), role


@pytest.mark.parametrize(("look", "suffix"), SUFFIXES, ids=[s for _, s in SUFFIXES])
def test_only_increased_contrast_outlines_the_script_panel(look, suffix):
    expected = getattr(tokens, f"CARD_BORDER_{suffix}") if look.high_contrast else None

    assert theme.roles(look).panel_border == expected


@pytest.mark.parametrize("look", [LIGHT, DARK, HC_LIGHT, HC_DARK])
def test_the_focus_ring_inner_stroke_follows_light_and_dark(look):
    expected = tokens.FOCUS_INNER_DARK if look.dark else tokens.FOCUS_INNER_LIGHT

    assert theme.roles(look).focus_inner == expected


def test_every_role_is_a_valid_color():
    for look, _ in SUFFIXES:
        for role, value in vars(theme.roles(look)).items():
            assert value is None or QColor(value).isValid(), (look, role)


class _Accessibility:
    def __init__(self, preference: Qt.ContrastPreference) -> None:
        self._preference = preference

    def contrastPreference(self) -> Qt.ContrastPreference:
        return self._preference


class _Hints:
    """The two style hints current() reads, set by the test."""

    def __init__(self, scheme: Qt.ColorScheme, preference: Qt.ContrastPreference) -> None:
        self._scheme = scheme
        self._accessibility = _Accessibility(preference)

    def colorScheme(self) -> Qt.ColorScheme:
        return self._scheme

    def accessibility(self) -> _Accessibility:
        return self._accessibility


@pytest.mark.parametrize(
    ("scheme", "preference", "expected"),
    [
        (Qt.ColorScheme.Light, Qt.ContrastPreference.NoPreference, LIGHT),
        (Qt.ColorScheme.Dark, Qt.ContrastPreference.NoPreference, DARK),
        (Qt.ColorScheme.Light, Qt.ContrastPreference.HighContrast, HC_LIGHT),
        (Qt.ColorScheme.Dark, Qt.ContrastPreference.HighContrast, HC_DARK),
    ],
)
def test_current_reads_the_color_scheme_and_the_contrast_preference(
    qapp, scheme, preference, expected
):
    assert theme.current(_Hints(scheme, preference)) == expected


@pytest.mark.parametrize(("base", "dark"), [("#171717", True), ("#ffffff", False)])
def test_an_unknown_scheme_is_judged_by_the_base_color(qapp, monkeypatch, base, dark):
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Base, QColor(base))
    monkeypatch.setattr(QGuiApplication, "palette", staticmethod(lambda: palette))
    hints = _Hints(Qt.ColorScheme.Unknown, Qt.ContrastPreference.NoPreference)

    assert theme.current(hints).dark is dark


def test_hints_without_contrast_support_read_as_standard_contrast(qapp):
    class OldHints:
        def colorScheme(self) -> Qt.ColorScheme:
            return Qt.ColorScheme.Dark

    assert theme.current(OldHints()) == DARK


def test_current_defaults_to_the_application_style_hints(qapp):
    assert isinstance(theme.current(), theme.Appearance)
