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
AA_UI_PART = 3.0  # WCAG 2.2 1.4.11: control boundaries and focus indicators
# System colors the custom surfaces sit on (design spec 2.1): Qt 6.12 on macOS with the color
# scheme set to Light, then Dark. The card is QPalette.Base; the window is QPalette.Window.
WINDOW = {"LIGHT": "#ececec", "DARK": "#323232"}
CARD = {"LIGHT": "#ffffff", "DARK": "#171717"}
PENDING = pytest.mark.xfail(raises=AttributeError, strict=True, reason="work item 2 adds it")


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


def color(ref: str) -> str:
    """A hex reference as is, else the token of that name."""
    return ref if ref.startswith("#") else getattr(tokens, ref)


def pairs_per_appearance():
    for look in ("LIGHT", "DARK"):
        window, card, panel = WINDOW[look], CARD[look], f"PANEL_{look}"
        yield f"TEXT_SECONDARY_{look}", card, AA_NORMAL_TEXT  # spoken script, menu headers
        yield f"TEXT_SECONDARY_{look}", panel, AA_NORMAL_TEXT
        yield f"CARD_BORDER_{look}", window, AA_UI_PART
        yield f"CARD_BORDER_{look}", card, AA_UI_PART
        for surface in (window, card, panel):  # the accent alone misses 3:1 in Dark Mode
            yield f"FOCUS_INNER_{look}", surface, AA_UI_PART


# The site's brand colors and the DMG label band, each against the ink it carries or sits on.
BRAND_PAIRS = [
    ("BRAND_BLUE_DEEP", "#ffffff", AA_NORMAL_TEXT),
    ("BRAND_VIOLET", "#ffffff", AA_NORMAL_TEXT),
    ("BRAND_VIOLET_BRIGHT", "#000000", AA_NORMAL_TEXT),
    ("BRAND_NAVY", "#ffffff", AA_NORMAL_TEXT),
    ("BRAND_LAVENDER", "#000000", AA_NORMAL_TEXT),
    ("BRAND_LAVENDER_PALE", "#000000", AA_NORMAL_TEXT),
    ("DMG_LABEL_BAND", "#000000", AA_NORMAL_TEXT),  # Finder draws labels black in Light Mode
    ("DMG_LABEL_BAND", "#ffffff", AA_NORMAL_TEXT),  # and white in Dark Mode
]
SPEC_PAIRS = [
    pytest.param(front, back, floor, id=f"{front}-on-{back}", marks=PENDING)
    for front, back, floor in [*pairs_per_appearance(), *BRAND_PAIRS]
]


def test_contrast_matches_the_wcag_reference_values():
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)


@pytest.mark.parametrize(("front", "back", "floor"), SPEC_PAIRS)
def test_every_token_pair_of_the_design_spec_meets_wcag_aa(front, back, floor):
    assert contrast(color(front), color(back)) >= floor


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
