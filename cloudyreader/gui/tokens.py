"""Layout, type, color, and timing tokens: the only GUI file that holds raw numbers.

Spacing follows the macOS HIG (Layout): 20 pt window margins and gaps between groups, 12 pt
between push buttons, 8 pt between a label and its control or between stacked rows.
"""

MARGIN = 20
SECTION_SPACING = 20
GROUP_SPACING = 12
CONTROL_SPACING = 8
TEXT_INSET = 6  # document margin inside text views; Qt's default is 4

WINDOW_MIN_SIZE = (560, 480)
WINDOW_DEFAULT_SIZE = (680, 620)
SCRIPT_MIN_HEIGHT = 96
VOICE_COMBO_MIN_CHARS = 24
BUSY_BAR_WIDTH = 96
ABOUT_ICON_SIZE = 64  # the size Qt's own About box uses
STATUS_ICON_SIZE = 16
DISCLOSURE_SIZE = 13  # NSButton's disclosure triangle at regular control size
INDICATOR_SPACING = 6  # between a small icon or disclosure triangle and its text

# Type ramp: macOS text styles in points (HIG Typography). Fonts scale from the system font.
TEXT_BODY_PT = 13
TEXT_CALLOUT_PT = 12

# Placeholder text per appearance. The system color is 25% alpha, under 2:1 on a text view;
# these meet WCAG AA 4.5:1 there and stay 3:1 apart from typed text (tests/gui/test_tokens.py).
PLACEHOLDER_LIGHT = "#6e6e73"
PLACEHOLDER_DARK = "#8e8e93"

# AudioPlayer has no end-of-playback callback, so the window polls is_playing at this interval.
PLAYBACK_POLL_MS = 150
