"""Layout and timing tokens: the only GUI file that holds raw numbers.

Spacing follows the macOS HIG (Layout): 20 pt window margins, 8 pt between related controls.
"""

MARGIN = 20
GROUP_SPACING = 12
CONTROL_SPACING = 8

WINDOW_MIN_SIZE = (560, 480)
WINDOW_DEFAULT_SIZE = (680, 620)
SCRIPT_MIN_HEIGHT = 96
VOICE_COMBO_MIN_CHARS = 24
BUSY_BAR_WIDTH = 96
ABOUT_ICON_SIZE = 64  # the size Qt's own About box uses

# AudioPlayer has no end-of-playback callback, so the window polls is_playing at this interval.
PLAYBACK_POLL_MS = 150
