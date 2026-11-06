"""The release DMG window, after docs-ia's spec section 7, and the styled image built from it.

build_app.sh runs this file with the build venv's Python when dmgbuild is installed there:
`python -I packaging/dmg_layout.py APP DMG [ICON]`. The constants live here until
cloudyreader/gui/tokens.py carries the DMG_* tokens; a test then asserts that both agree.
"""

from __future__ import annotations

import math
import struct
import sys
import tempfile
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

VOLUME_NAME = "Cloudy Reader"
WINDOW_RECT = ((200, 120), (640, 400))  # where on the screen; the content size, in points
ICON_SIZE = 128
TEXT_SIZE = 13
APP_CENTER = (176, 190)  # icon centers, from the top-left corner of the content
APPLICATIONS_CENTER = (464, 190)
ARROW = ((272, 190), (368, 190))  # tail, tip
ARROW_STROKE = 3.0  # round caps
ARROW_HEAD = 12.0  # the head's width across the shaft
# DMG_LABEL_BAND: Finder draws labels black in Light Mode and white in Dark Mode; this flat color
# gives both 4.58:1, the most one color can give both.
BACKGROUND = "#7A63D6"
ARROW_COLOR = "#FFFFFF"


def rgb(color: str) -> tuple[int, int, int]:
    """'#RRGGBB' as three 0 to 255 values."""
    value = int(color.removeprefix("#"), 16)
    return value >> 16, value >> 8 & 0xFF, value & 0xFF


def luminance(color: str) -> float:
    """WCAG 2 relative luminance."""

    def linear(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG 2 contrast ratio of two colors, 1 to 21."""
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _segments() -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """The arrow as three strokes in points: the shaft and the two sides of a 90-degree head."""
    tail, (x, y) = ARROW
    side = ARROW_HEAD / 2
    return [(tail, (x, y)), ((x, y), (x - side, y - side)), ((x, y), (x - side, y + side))]


def _distance(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _png(width: int, height: int, rows: Sequence[bytes], dpi: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    per_meter = round(dpi / 0.0254)
    raw = b"".join(b"\x00" + row for row in rows)  # filter type 0 on every row
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            chunk(b"pHYs", struct.pack(">IIB", per_meter, per_meter, 1)),
            chunk(b"IDAT", zlib.compress(raw, 9)),
            chunk(b"IEND", b""),
        )
    )


def render(scale: int) -> bytes:
    """The background art as an RGB PNG: the flat field and the white arrow, `scale` px per pt."""
    (_, (width_pt, height_pt)) = WINDOW_RECT
    width, height = width_pt * scale, height_pt * scale
    field, ink = rgb(BACKGROUND), rgb(ARROW_COLOR)
    rows = [bytearray(bytes(field) * width) for _ in range(height)]
    segments, radius = _segments(), ARROW_STROKE / 2
    xs = [x for segment in segments for x, _ in segment]
    ys = [y for segment in segments for _, y in segment]
    left, right = int((min(xs) - radius) * scale) - 1, int((max(xs) + radius) * scale) + 2
    top, bottom = int((min(ys) - radius) * scale) - 1, int((max(ys) + radius) * scale) + 2
    for py in range(max(0, top), min(height, bottom)):
        row = rows[py]
        for px in range(max(0, left), min(width, right)):
            x, y = (px + 0.5) / scale, (py + 0.5) / scale  # the pixel's center, in points
            gap = min(_distance(x, y, a, b) for a, b in segments) - radius
            alpha = max(0.0, min(1.0, 0.5 - gap * scale))  # one pixel of antialiased edge
            if alpha:
                row[3 * px : 3 * px + 3] = bytes(
                    round(f + (i - f) * alpha) for f, i in zip(field, ink, strict=True)
                )
    return _png(width, height, rows, dpi=72 * scale)


def settings(app: Path, icon: Path | None, background: Path) -> dict[str, Any]:
    """dmgbuild's settings as a dict: dmgbuild exec's a settings .py file, so none is written."""
    return {
        "format": "ULFO",
        "filesystem": "APFS",
        "files": [str(app)],
        "symlinks": {"Applications": "/Applications"},
        "icon": str(icon) if icon else None,
        "background": str(background),  # background@2x.png beside it joins as one HiDPI TIFF
        "window_rect": WINDOW_RECT,
        "default_view": "icon-view",
        "show_status_bar": False,
        "show_tab_view": False,
        "show_toolbar": False,
        "show_pathbar": False,
        "show_sidebar": False,
        "icon_size": ICON_SIZE,
        "text_size": TEXT_SIZE,
        "label_pos": "bottom",
        "icon_locations": {app.name: APP_CENTER, "Applications": APPLICATIONS_CENTER},
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in (2, 3):
        print("usage: dmg_layout.py APP DMG [ICON]", file=sys.stderr)
        return 2
    app, dmg = Path(args[0]), Path(args[1])
    icon = Path(args[2]) if len(args) == 3 and args[2] else None
    import dmgbuild  # the build venv's packaging group; build_app.sh checks for it first

    with tempfile.TemporaryDirectory(prefix="dmg-art.") as art:
        background = Path(art) / "background.png"
        background.write_bytes(render(1))
        (Path(art) / "background@2x.png").write_bytes(render(2))
        dmgbuild.build_dmg(str(dmg), VOLUME_NAME, settings=settings(app, icon, background))
    return 0


if __name__ == "__main__":  # pragma: no cover - build_app.sh runs it as a script
    raise SystemExit(main())
