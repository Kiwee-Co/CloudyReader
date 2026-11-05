"""Design tokens: color pairs meet WCAG 2.2 AA, spacing follows the macOS HIG (Layout)."""

import pytest
from PySide6.QtGui import QColor

from cloudyreader.gui import tokens

# Text view backgrounds per appearance: what Qt reports for QPalette.Base on macOS, plus
# NSColor.textBackgroundColor in Dark Mode. A placeholder must pass on every one of them.
LIGHT_TEXT_BACKGROUNDS = ("#ffffff",)
DARK_TEXT_BACKGROUNDS = ("#171717", "#1e1e1e")
LIGHT_TEXT, DARK_TEXT = "#000000", "#ffffff"
AA_NORMAL_TEXT = 4.5


def luminance(hex_color: str) -> float:
    """WCAG 2.2 relative luminance of an sRGB color."""

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    color = QColor(hex_color)
    assert color.isValid(), hex_color
    r, g, b = (linear(c) for c in (color.redF(), color.greenF(), color.blueF()))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(first: str, second: str) -> float:
    hi, lo = sorted((luminance(first), luminance(second)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_contrast_matches_the_wcag_reference_values():
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)


@pytest.mark.parametrize(
    ("placeholder", "backgrounds"),
    [
        (tokens.PLACEHOLDER_LIGHT, LIGHT_TEXT_BACKGROUNDS),
        (tokens.PLACEHOLDER_DARK, DARK_TEXT_BACKGROUNDS),
    ],
)
def test_placeholder_text_meets_aa_on_its_background(placeholder, backgrounds):
    for background in backgrounds:
        assert contrast(placeholder, background) >= AA_NORMAL_TEXT, background


@pytest.mark.parametrize(
    ("placeholder", "text"),
    [(tokens.PLACEHOLDER_LIGHT, LIGHT_TEXT), (tokens.PLACEHOLDER_DARK, DARK_TEXT)],
)
def test_placeholder_still_reads_as_a_hint_not_as_typed_text(placeholder, text):
    assert contrast(placeholder, text) >= 3.0


def test_spacing_follows_the_hig_layout_rhythm():
    assert tokens.MARGIN == tokens.SECTION_SPACING == 20
    assert tokens.CONTROL_SPACING < tokens.GROUP_SPACING < tokens.SECTION_SPACING


def test_type_ramp_is_the_macos_body_and_callout_styles():
    assert (tokens.TEXT_BODY_PT, tokens.TEXT_CALLOUT_PT) == (13, 12)
