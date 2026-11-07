"""Design tokens: color pairs meet WCAG 2.2 in every appearance, spacing sits on the 8 pt grid."""

import pytest
from PySide6.QtGui import QColor

from cloudyreader.gui import theme, tokens

# Text view backgrounds per appearance: what Qt reports for QPalette.Base on macOS, plus
# NSColor.textBackgroundColor in Dark Mode. A placeholder must pass on every one of them.
LIGHT_TEXT_BACKGROUNDS = ("#ffffff",)
DARK_TEXT_BACKGROUNDS = ("#171717", "#1e1e1e")
LIGHT_TEXT, DARK_TEXT = "#000000", "#ffffff"
AA_NORMAL_TEXT = 4.5
AA_UI_PART = 3.0  # WCAG 2.2 1.4.11: control boundaries and focus indicators
AAA_NORMAL_TEXT = 7.0  # increased contrast aims here for text
# System colors the custom surfaces sit on (design spec 2.1): Qt 6.12 on macOS with the color
# scheme set to Light, then Dark. The card is QPalette.Base; the window is QPalette.Window.
WINDOW = {"LIGHT": "#ececec", "DARK": "#323232"}
CARD = {"LIGHT": "#ffffff", "DARK": "#171717"}
# A disabled pop-up's dimmed bezel as AppKit draws it: the "Loading voices…" placeholder sits on it.
BEZEL = {"LIGHT": "#f6f6f6", "DARK": "#4c4c4c"}
LOOKS = {
    "light": theme.Appearance(dark=False, high_contrast=False),
    "dark": theme.Appearance(dark=True, high_contrast=False),
    "hc-light": theme.Appearance(dark=False, high_contrast=True),
    "hc-dark": theme.Appearance(dark=True, high_contrast=True),
}


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


def role_pairs():
    """Each appearance's roles against what they sit on (design spec 3.1), with their floor."""
    for name, look in LOOKS.items():
        roles, key = theme.roles(look), "DARK" if look.dark else "LIGHT"
        window, card, panel = WINDOW[key], CARD[key], roles.panel_fill
        text = AAA_NORMAL_TEXT if look.high_contrast else AA_NORMAL_TEXT
        glyph = AA_NORMAL_TEXT if look.high_contrast else AA_UI_PART
        yield name, "placeholder", roles.placeholder, card, AA_NORMAL_TEXT  # capped: see below
        for surface in (card, panel, window):  # script, menu headers, About, status
            yield name, "secondary", roles.secondary_text, surface, text
        yield name, "field-placeholder", roles.field_placeholder, BEZEL[key], text
        yield name, "card-border", roles.card_border, window, AA_UI_PART
        yield name, "card-border", roles.card_border, card, AA_UI_PART
        if roles.panel_border is not None:
            yield name, "panel-border", roles.panel_border, panel, AA_UI_PART
        for surface in (window, card, panel):  # the accent alone misses 3:1 in Dark Mode
            yield name, "focus-inner", roles.focus_inner, surface, AA_UI_PART
        yield name, "warning-glyph", roles.warning, window, glyph
        yield name, "error-glyph", roles.error, window, glyph


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
    pytest.param(front, back, floor, id=f"{look}-{role}-on-{back}")
    for look, role, front, back, floor in role_pairs()
] + [
    pytest.param(front, back, floor, id=f"{front}-on-{back}") for front, back, floor in BRAND_PAIRS
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
        (tokens.PLACEHOLDER_HC_LIGHT, LIGHT_TEXT_BACKGROUNDS),
        (tokens.PLACEHOLDER_HC_DARK, DARK_TEXT_BACKGROUNDS),
    ],
)
def test_placeholder_text_meets_aa_on_its_background(placeholder, backgrounds):
    for background in backgrounds:
        assert contrast(placeholder, background) >= AA_NORMAL_TEXT, background


@pytest.mark.parametrize(
    ("placeholder", "text"),
    [
        (tokens.PLACEHOLDER_LIGHT, LIGHT_TEXT),
        (tokens.PLACEHOLDER_DARK, DARK_TEXT),
        (tokens.PLACEHOLDER_HC_LIGHT, LIGHT_TEXT),
        (tokens.PLACEHOLDER_HC_DARK, DARK_TEXT),
    ],
)
def test_placeholder_still_reads_as_a_hint_not_as_typed_text(placeholder, text):
    # This cap is why increased contrast cannot lift a placeholder to 7:1: no gray is 7:1 from
    # the background and 3:1 from the text at once.
    assert contrast(placeholder, text) >= 3.0


def test_spacing_follows_the_24_16_8_rhythm():
    assert tokens.MARGIN == tokens.SECTION_SPACING == 24
    assert tokens.CONTROL_SPACING < tokens.GROUP_SPACING < tokens.RELATED_SPACING
    assert tokens.RELATED_SPACING < tokens.SECTION_SPACING


@pytest.mark.parametrize(
    "name",
    [
        "MARGIN",
        "SECTION_SPACING",
        "RELATED_SPACING",
        "GROUP_SPACING",
        "CONTROL_SPACING",
        "CARD_PADDING",
        "PANEL_PADDING",
        "SECTION_HEADER_GAP",
        "ABOUT_ICON_GAP",
        "ABOUT_LINE_GAP",
        "ABOUT_WIDTH",
        "ABOUT_ICON_SIZE",
        "STATUS_LINE_HEIGHT",
        "STATUS_ICON_SIZE",
        "PROGRESS_BAR_WIDTH",
    ],
)
def test_layout_tokens_sit_on_the_4_pt_half_step(name):
    assert getattr(tokens, name) % 4 == 0


def test_margins_gaps_and_window_sizes_sit_on_the_8_pt_grid():
    steps = (tokens.MARGIN, tokens.SECTION_SPACING, tokens.RELATED_SPACING)
    sizes = (*tokens.WINDOW_MIN_SIZE, *tokens.WINDOW_DEFAULT_SIZE)

    assert [value % 8 for value in (*steps, *sizes)] == [0] * (len(steps) + len(sizes))


def test_type_ramp_is_the_macos_title3_body_callout_and_section_styles():
    ramp = (tokens.TEXT_QUESTION_PT, tokens.TEXT_BODY_PT, tokens.TEXT_CALLOUT_PT)

    assert (*ramp, tokens.TEXT_SECTION_PT) == (15, 13, 12, 11)
    assert tokens.TEXT_TITLE_PT == tokens.TEXT_QUESTION_PT  # Title 3, semibold in the About panel


def test_the_focus_ring_stays_concentric_with_its_control():
    widths = tokens.FOCUS_INNER_WIDTH + tokens.FOCUS_OUTER_WIDTH

    assert widths == tokens.FOCUS_RADIUS_EXTRA


def test_the_message_keeps_a_share_of_the_status_line():
    assert 0 < tokens.MESSAGE_MIN_SHARE < 1


@pytest.mark.parametrize("retired", ["TEXT_INSET", "BUSY_BAR_WIDTH"])
def test_retired_tokens_are_gone(retired):
    assert not hasattr(tokens, retired)


def test_corners_ease_in_with_the_system_smoothing():
    assert 0 < tokens.CORNER_SMOOTHING < 1


@pytest.mark.parametrize(
    "points",
    [
        tokens.GLYPH_WARNING_OUTLINE,
        tokens.GLYPH_WARNING_BAR,
        (tokens.GLYPH_WARNING_DOT,),
        tokens.GLYPH_ERROR_BAR,
        (tokens.GLYPH_ERROR_CENTER, tokens.GLYPH_ERROR_DOT),
    ],
)
def test_status_glyph_points_stay_inside_their_box(points):
    for x, y in points:
        assert 0 <= x <= tokens.GLYPH_BOX and 0 <= y <= tokens.GLYPH_BOX


def test_the_error_circle_and_the_dots_fit_their_box():
    x, y = tokens.GLYPH_ERROR_CENTER
    radius = tokens.GLYPH_ERROR_RADIUS + tokens.STATUS_GLYPH_STROKE / 2

    assert radius <= min(x, y, tokens.GLYPH_BOX - x, tokens.GLYPH_BOX - y)
    assert 0 < tokens.GLYPH_DOT_RADIUS < tokens.STATUS_GLYPH_STROKE
