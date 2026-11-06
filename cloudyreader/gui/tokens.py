"""Layout, type, color, and timing tokens: the only GUI file that holds raw numbers.

Spacing follows the macOS HIG (Layout): 20 pt window margins and gaps between groups, 12 pt
between push buttons, 8 pt between a label and its control or between stacked rows.
This module imports nothing, so packaging scripts can read the brand and DMG values without Qt.
"""

MARGIN = 20
SECTION_SPACING = 20
GROUP_SPACING = 12
CONTROL_SPACING = 8
CARD_PADDING = 12  # inside the question card and the script panel
CARD_RADIUS = 8
BORDER_WIDTH = 1  # the question card's outline
# The focus ring sits outside the control edge: a contrast stroke, then the accent. Its outer
# radius is the control's plus FOCUS_RADIUS_EXTRA, the width of both, so the two stay concentric.
FOCUS_INNER_WIDTH = 1
FOCUS_OUTER_WIDTH = 2
FOCUS_RADIUS_EXTRA = 3

WINDOW_MIN_SIZE = (560, 480)
WINDOW_DEFAULT_SIZE = (680, 620)
# The question card shows at least this many lines: three keep the 480 pt minimum window whole
# with the spoken script open, where four would need 496 pt.
QUESTION_MIN_LINES = 3
SCRIPT_MIN_HEIGHT = 96
VOICE_COMBO_MIN_CHARS = 24
STATUS_LINE_HEIGHT = 28
PROGRESS_BAR_WIDTH = 120  # the download bar and the busy bar
MESSAGE_MIN_SHARE = 0.5  # the status message gets the room it needs, up to this share of the line
SECTION_HEADER_GAP = 8  # above each engine header in the Voice menu but the first
ABOUT_ICON_SIZE = 64  # the size Qt's own About box uses
ABOUT_TEXT_MIN_WIDTH = 280  # the one-line description fits without a wrap
STATUS_ICON_SIZE = 16
DISCLOSURE_SIZE = 13  # NSButton's disclosure triangle at regular control size
INDICATOR_SPACING = 6  # between a small icon or disclosure triangle and its text

# Type ramp: macOS text styles in points (HIG Typography). Fonts scale from the system font.
TEXT_QUESTION_PT = 15  # Title 3: the question, the text users read along
TEXT_BODY_PT = 13
TEXT_CALLOUT_PT = 12
TEXT_SECTION_PT = 11  # semibold engine headers in the Voice menu

# Colors per appearance, each pair checked against WCAG 2.2 AA in tests/gui/test_tokens.py.
# Placeholder text: the system color is 25% alpha, under 2:1 on a text view; these meet 4.5:1
# there and stay 3:1 apart from typed text.
PLACEHOLDER_LIGHT = "#6e6e73"
PLACEHOLDER_DARK = "#8e8e93"
# Spoken script and Voice menu headers. The system secondary label color is 3.95:1 on white.
TEXT_SECONDARY_LIGHT = "#5e5e63"
TEXT_SECONDARY_DARK = "#aeaeb2"
PANEL_LIGHT = "#e0e0e0"  # the script panel: 5% black over the window
PANEL_DARK = "#3e3e3e"  # 6% white over the window
CARD_BORDER_LIGHT = "#7c7c80"
CARD_BORDER_DARK = "#8e8e93"
# The focus ring's inner stroke carries 3:1 where the system accent cannot (2.52:1 in Dark Mode).
FOCUS_INNER_LIGHT = "#1d1d1f"
FOCUS_INNER_DARK = "#f5f5f7"

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
