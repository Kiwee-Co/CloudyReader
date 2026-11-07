"""Layout, type, color, and timing tokens: the only GUI file that holds raw numbers.

Spacing sits on an 8 pt grid with 4 pt half steps: 24 pt window margins and gaps between groups,
16 pt between a surface and the header that belongs to it, 12 pt between push buttons (HIG
Buttons), 8 pt between a label and its control or between stacked rows.
This module imports nothing, so packaging scripts can read the brand and DMG values without Qt.
"""

MARGIN = 24
SECTION_SPACING = 24
RELATED_SPACING = 16  # the question card to the Spoken script header
GROUP_SPACING = 12
CONTROL_SPACING = 8
CARD_PADDING = 16  # inside the question card: the hero gets the most air
PANEL_PADDING = 12  # inside the script panel
CARD_RADIUS = 10  # the question card, the script panel and their focus ring
CORNER_SMOOTHING = 0.6  # how far a continuous corner eases into its edges: the iOS and macOS curve
BORDER_WIDTH = 1  # the question card's outline
# The focus ring sits outside the control edge: a contrast stroke, then the accent. Its outer
# radius is the control's plus FOCUS_RADIUS_EXTRA, the width of both, so the two stay concentric.
FOCUS_INNER_WIDTH = 1
FOCUS_OUTER_WIDTH = 2
FOCUS_RADIUS_EXTRA = 3

WINDOW_MIN_SIZE = (560, 480)
WINDOW_DEFAULT_SIZE = (680, 640)
# The question card shows at least QUESTION_MIN_LINES, the script panel SCRIPT_MIN_LINES: both keep
# the 480 pt minimum window whole with the script open and the Speaker row shown.
QUESTION_MIN_LINES = 3
SCRIPT_MIN_LINES = 2
SCRIPT_MIN_HEIGHT = 96  # the panel's floor until the window sizes it by SCRIPT_MIN_LINES
QUESTION_STRETCH = 3  # how the spare height splits between the question card and the panel
SCRIPT_STRETCH = 2
VOICE_COMBO_MIN_CHARS = 32  # 362 pt: the longest supported label shows whole when closed
STATUS_LINE_HEIGHT = 28
PROGRESS_BAR_WIDTH = 120  # the download bar and the busy bar
MESSAGE_MIN_SHARE = 0.5  # the status message gets the room it needs, up to this share of the line
SECTION_HEADER_GAP = 8  # above each engine header in the Voice menu but the first
ABOUT_WIDTH = 300  # the About panel, at least; wider when its description needs it
ABOUT_ICON_SIZE = 64  # the system About panel's icon
ABOUT_ICON_GAP = 16  # the icon to the app name
ABOUT_LINE_GAP = 4  # the app name to the version
ABOUT_TEXT_MIN_WIDTH = 280  # the alert-style About box: its one-line description fits
STATUS_ICON_SIZE = 16
DISCLOSURE_SIZE = 13  # NSButton's disclosure triangle at regular control size
INDICATOR_SPACING = 6  # between a small icon or disclosure triangle and its text

# Status tone glyphs: line drawings on a GLYPH_BOX grid, scaled to STATUS_ICON_SIZE. Two shapes,
# so the tone never rests on color alone: a triangle for a warning, a circle for an error.
GLYPH_BOX = 16
STATUS_GLYPH_STROKE = 1.5
GLYPH_WARNING_OUTLINE = ((8, 2.2), (14.6, 13.6), (1.4, 13.6))
GLYPH_WARNING_BAR = ((8, 6.2), (8, 9.4))
GLYPH_WARNING_DOT = (8, 11.5)
GLYPH_ERROR_CENTER = (8, 8)
GLYPH_ERROR_RADIUS = 6.5
GLYPH_ERROR_BAR = ((8, 4.6), (8, 8.4))
GLYPH_ERROR_DOT = (8, 10.9)
GLYPH_DOT_RADIUS = 0.95

# Type ramp: macOS text styles in points (HIG Typography). Fonts scale from the system font.
TEXT_QUESTION_PT = 15  # Title 3: the question, the text users read along
TEXT_TITLE_PT = 15  # Title 3, semibold: the About panel's app name
TEXT_BODY_PT = 13
TEXT_CALLOUT_PT = 12
TEXT_SECTION_PT = 11  # Subheadline: Voice menu engine headers (semibold), the About version

# Colors per appearance: light, dark, and both under increased contrast (HC). theme.py picks the
# set; tests/gui/test_tokens.py checks every pair against WCAG 2.2, 7:1 for HC text.
# Placeholder text: the system color is 25% alpha, under 2:1 on a text view; these meet 4.5:1
# there and stay 3:1 apart from typed text, which caps the HC pair below 7:1.
PLACEHOLDER_LIGHT = "#6e6e73"
PLACEHOLDER_DARK = "#8e8e93"
PLACEHOLDER_HC_LIGHT = "#5e5e63"
PLACEHOLDER_HC_DARK = "#8e8e93"
# Spoken script, Voice menu headers, the About lines. The system secondary label is 3.95:1 on white.
TEXT_SECONDARY_LIGHT = "#5e5e63"
TEXT_SECONDARY_DARK = "#aeaeb2"
TEXT_SECONDARY_HC_LIGHT = "#3a3a3c"
TEXT_SECONDARY_HC_DARK = "#e5e5ea"
PANEL_LIGHT = "#e0e0e0"  # the script panel: 5% black over the window
PANEL_DARK = "#3e3e3e"  # 6% white over the window
PANEL_HC_LIGHT = "#d6d6d6"
PANEL_HC_DARK = "#474747"
# The lightest outline that keeps 3:1 on the window, with a margin for system drift.
CARD_BORDER_LIGHT = "#818186"
CARD_BORDER_DARK = "#858589"
CARD_BORDER_HC_LIGHT = "#545458"  # increased contrast outlines the script panel too
CARD_BORDER_HC_DARK = "#aeaeb2"
# The focus ring's inner stroke carries 3:1 where the system accent cannot (2.52:1 in Dark Mode).
FOCUS_INNER_LIGHT = "#1d1d1f"
FOCUS_INNER_DARK = "#f5f5f7"
# Tone glyphs in the status bar: 3:1 on the window as a graphic needs, 4.5:1 under HC.
TONE_WARNING_LIGHT = "#b25f00"
TONE_WARNING_DARK = "#f5a524"
TONE_WARNING_HC_LIGHT = "#8a4600"
TONE_WARNING_HC_DARK = "#ffc266"
TONE_ERROR_LIGHT = "#c8262c"
TONE_ERROR_DARK = "#ff6961"
TONE_ERROR_HC_LIGHT = "#a3121a"
TONE_ERROR_HC_DARK = "#ff8f87"
# The placeholder of a disabled pop-up ("Loading voices…") on its dimmed bezel, #f6f6f6 / #4c4c4c.
FIELD_PLACEHOLDER_LIGHT = "#5e5e63"
FIELD_PLACEHOLDER_DARK = "#d1d1d6"
FIELD_PLACEHOLDER_HC_LIGHT = "#3a3a3c"
FIELD_PLACEHOLDER_HC_DARK = "#f2f2f7"

# Brand: the site's --cr-* colors (site/src/styles/custom.css), for the About panel and the DMG.
BRAND_BLUE_DEEP = "#1b3ea8"
BRAND_VIOLET = "#5a3fd0"
BRAND_VIOLET_BRIGHT = "#7d6bf2"
BRAND_NAVY = "#150f55"
BRAND_LAVENDER = "#d4cbfb"
BRAND_LAVENDER_PALE = "#e6e0fb"

# DMG installer window. Finder draws icon labels black in Light Mode and white in Dark Mode on
# art that cannot change: this band gives both 4.58:1, the most one color can.
DMG_LABEL_BAND = "#7a63d6"
DMG_ICON_SIZE = 128
DMG_TEXT_PT = 13

# AudioPlayer has no end-of-playback callback, so the window polls is_playing at this interval.
PLAYBACK_POLL_MS = 150
SCRIPT_DEBOUNCE_MS = 150  # the live script waits this long after the last change to the box
