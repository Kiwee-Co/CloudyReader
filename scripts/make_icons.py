"""Render the Cloudy Reader app-icon candidates and build each AppIcon.icns.

Usage: python -I scripts/make_icons.py [--only NAME] [--out DIR]
Per design <name> it writes <out>/<name>/icon_1024.png, icon_512.png, AppIcon.iconset/ (the 10
sizes `iconutil` wants) and AppIcon.icns, then <out>/preview.png, a contact sheet of all designs.
--only limits the per-design files; preview.png always shows every design.
<out>/default.txt is kept by hand: the design the app build uses when ICON is unset.
PySide6 only (QPainter, offscreen) plus macOS `iconutil`. No randomness: reruns give the same PNGs.
"""

import argparse
import math
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QTransform,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "assets" / "icons"

CANVAS = 1024
BODY = 824  # Apple's macOS icon grid: the shape fills 824 px, the rest is room for the shadow
RADIUS = 185
INSET = (CANVAS - BODY) / 2
BODY_RECT = QRectF(INSET, INSET, BODY, BODY)
# Where the symbol sits: about 70% of the body, a little high because the shadow weighs it down.
SYMBOL_BOX = QRectF(512 - 320, 512 - 262, 640, 500)
# `iconutil` wants 16..512 at 1x and 2x, named exactly like this.
ICONSET = tuple(
    (f"icon_{size}x{size}{'@2x' if retina else ''}.png", size * (2 if retina else 1))
    for size in (16, 32, 128, 256, 512)
    for retina in (False, True)
)
PREVIEW_SMALL = (128, 64, 32, 16)
SMALL_MAX = 32  # sizes up to this use the bolder drawing: thin strokes vanish below 1 px
SMALL_HEFT = 1.45

_app: QGuiApplication | None = None


@dataclass(frozen=True)
class Layer:
    """One piece of a symbol, in free symbol space; `fit` scales and centers the whole set.

    style: "solid" white with a shadow, "soft" translucent white, "ghost" fainter still,
    "knock" background showing through.
    """

    path: QPainterPath
    style: str = "solid"


@dataclass(frozen=True)
class Design:
    name: str
    summary: str
    stops: tuple[str, ...]  # background gradient, top-left to bottom-right
    shade: str  # tint of the symbol's shadow
    layers: Callable[[float], list[Layer]]  # heft: 1 normally, SMALL_HEFT for tiny sizes


@dataclass(frozen=True)
class Rendered:
    master: QImage  # CANVAS px, drawn at normal heft
    small: QImage  # CANVAS px, heftier, scaled down for sizes up to SMALL_MAX

    def at(self, size: int) -> QImage:
        return resized(self.small if size <= SMALL_MAX else self.master, size)


# --- Qt plumbing ----------------------------------------------------------------------------------


def ensure_app() -> None:
    """QGuiApplication is needed for fonts; reuse one if a test already made it."""
    global _app
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QGuiApplication(sys.argv[:1])


@contextmanager
def painting(image: QImage) -> Iterator[QPainter]:
    painter = QPainter(image)
    painter.setRenderHints(
        QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
    )
    try:
        yield painter
    finally:
        painter.end()


def blank(size: int, fmt: QImage.Format = QImage.Format.Format_ARGB32_Premultiplied) -> QImage:
    image = QImage(size, size, fmt)
    image.fill(Qt.GlobalColor.transparent)
    return image


def rgba(hex_color: str, alpha: float = 1.0) -> QColor:
    color = QColor(hex_color)
    color.setAlphaF(alpha)
    return color


def mix(a: QColor, b: QColor, share: float) -> QColor:
    """`share` of b blended into a."""
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * share,
        a.greenF() + (b.greenF() - a.greenF()) * share,
        a.blueF() + (b.blueF() - a.blueF()) * share,
    )


def vertical(top: float, bottom: float, *stops: tuple[float, QColor]) -> QLinearGradient:
    gradient = QLinearGradient(0, top, 0, bottom)
    for at, color in stops:
        gradient.setColorAt(at, color)
    return gradient


# --- shapes ---------------------------------------------------------------------------------------


def squircle(rect: QRectF, radius: float, smoothing: float = 0.6) -> QPainterPath:
    """Square with continuous (iOS-style) corners, built like Figma's corner smoothing."""
    reach = min((1 + smoothing) * radius, rect.width() / 2)  # how far a corner runs along an edge
    smooth = reach / radius - 1
    arc_deg = 90 * (1 - smooth)
    chord = math.sin(math.radians(arc_deg / 2)) * radius * math.sqrt(2)  # x and y span of the arc
    tail = radius * math.tan(math.radians((90 - arc_deg) / 4))
    c = tail * math.cos(math.radians(45 * smooth))
    d = c * math.tan(math.radians(45 * smooth))
    b = (reach - chord - c - d) / 3
    a = 2 * b

    # One top-right corner, rotated three times: easing curve, circular arc, easing curve.
    x0, y0 = rect.right() - reach, rect.top()
    ax, ay = x0 + a + b + c, y0 + d
    corner = QPainterPath(QPointF(x0, y0))
    corner.cubicTo(x0 + a, y0, x0 + a + b, y0, ax, ay)
    off = radius * math.cos(math.radians(arc_deg / 2)) / math.sqrt(2)
    cx, cy = ax + chord / 2 - off, ay + chord / 2 + off  # circle centre, on the corner diagonal
    circle = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)
    corner.arcTo(circle, 45 + arc_deg / 2, -arc_deg)
    bx, by = ax + chord, ay + chord
    corner.cubicTo(bx + d, by + c, bx + d, by + b + c, bx + d, by + a + b + c)

    centre = rect.center()
    path = QPainterPath()
    for quarter in range(4):
        turn = QTransform().translate(centre.x(), centre.y()).rotate(90 * quarter)
        path.connectPath(turn.translate(-centre.x(), -centre.y()).map(corner))
    path.closeSubpath()
    return path


def grown(path: QPainterPath, d: float) -> QPainterPath:
    """`path` pushed out (d > 0) or pulled in (d < 0) by |d| px all around."""
    if d == 0:
        return path
    stroker = QPainterPathStroker()
    stroker.setWidth(2 * abs(d))
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    ring = stroker.createStroke(path)
    return path.united(ring) if d > 0 else path.subtracted(ring)


def rounded(path: QPainterPath, r: float) -> QPainterPath:
    """Round every convex corner: pull the shape in by r, then push it out again.

    Keep the input a plain polygon. These boolean ops slow down sharply with segment count.
    """
    return grown(grown(path, -r), r)


def stroke(path: QPainterPath, width: float) -> QPainterPath:
    """Round-capped outline of a line, as a fillable shape."""
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroker.createStroke(path)


def line(x1: float, y1: float, x2: float, y2: float, width: float) -> QPainterPath:
    path = QPainterPath(QPointF(x1, y1))
    path.lineTo(x2, y2)
    return stroke(path, width)


def disc(cx: float, cy: float, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


def union(paths: Sequence[QPainterPath]) -> QPainterPath:
    result = QPainterPath()
    for path in paths:
        result = result.united(path)
    return result


Puff = tuple[float, float, float]  # centre x, centre y, radius


def cloud_parts(
    h: float, radii: Sequence[float] = (0.26, 0.46, 0.34), overlap: float = 0.84
) -> tuple[list[Puff], QRectF]:
    """Three lobes (small left, big middle, medium right) on a flat base, h tall, origin top-left.

    Lobes rest on the base line and the big one touches the top. Neighbours sit `overlap` x (r + r)
    apart: lower is rounder, higher cuts deeper notches between lobes.
    """
    r1, r2, r3 = (share * h for share in radii)
    left_y, mid_y, right_y = h - r1, r2, h - r3
    mid_x = r1 + math.sqrt((overlap * (r1 + r2)) ** 2 - (mid_y - left_y) ** 2)
    right_x = mid_x + math.sqrt((overlap * (r2 + r3)) ** 2 - (right_y - mid_y) ** 2)
    top = min(left_y, right_y)
    base = QRectF(r1, top, right_x - r1, h - top)
    return [(r1, left_y, r1), (mid_x, mid_y, r2), (right_x, right_y, r3)], base


def blob(puffs: Sequence[Puff], base: QRectF) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)  # overlapping shapes must merge, not cancel out
    path.addRect(base)
    for cx, cy, r in puffs:
        path.addEllipse(QPointF(cx, cy), r, r)
    return path.simplified()


def arc(
    centre: QPointF, radius: float, half_span: float, width: float, axis: float = 0
) -> QPainterPath:
    """Arc around the direction `axis` degrees above due right, spanning 2 x half_span degrees."""
    box = QRectF(centre.x() - radius, centre.y() - radius, 2 * radius, 2 * radius)
    path = QPainterPath()
    path.arcMoveTo(box, axis + half_span)
    path.arcTo(box, axis + half_span, -2 * half_span)
    return stroke(path, width)


def top_edge(puffs: Sequence[Puff], base: QRectF, x: float) -> float:
    """Highest outline point (smallest y) of the cloud at x."""
    ys = [cy - math.sqrt(r * r - (x - cx) ** 2) for cx, cy, r in puffs if abs(x - cx) <= r]
    if base.left() <= x <= base.right():
        ys.append(base.top())
    return min(ys)


# --- the four designs -----------------------------------------------------------------------------


def voice_layers(heft: float) -> list[Layer]:
    """White cloud; three sound-wave arcs leave its right lobe, rising a little."""
    puffs, base = cloud_parts(300, (0.24, 0.44, 0.30), 0.74)
    cx, cy, r = puffs[2]
    waves = [
        arc(QPointF(cx, cy), r + 38 + (66 + 22 * (heft - 1)) * i, 34, 38 * heft, axis=22)
        for i in range(3)
    ]
    return [Layer(blob(puffs, base)), *(Layer(wave) for wave in waves)]


def book_layers(heft: float) -> list[Layer]:
    """Cloud whose underside is an open book: split pages, a smile-curved edge, a cover below."""

    def smile(u: float, drop: float = 0) -> float:  # bottom edge at distance u from the spine
        return 150 - 55 * (u / 310) ** 2 + drop

    crown = ((-226, 14, 80), (-128, -38, 100), (0, -72, 128), (124, -42, 96), (226, 12, 80))
    pages = [disc(*puff) for puff in crown]
    for side in (-1, 1):  # two page bodies, 14 px apart at the spine
        body = QPainterPath(QPointF(side * 7, -10))
        for u in range(7, 307, 12):
            body.lineTo(side * u, smile(u))
        body.lineTo(side * 306, smile(306))
        body.lineTo(side * 306, -10)
        body.closeSubpath()
        pages.append(rounded(body, 30))

    cover = QPainterPath(QPointF(-306, smile(306, 34)))
    for u in range(-300, 301, 12):
        cover.lineTo(u, smile(abs(u), 34))
    spine = line(0, 8, 0, 240, 14)  # slit from inside the crown down through the pages
    layers = [Layer(union(pages).subtracted(spine)), Layer(stroke(cover, 24 * heft), "soft")]
    for side in (-1, 1) if heft == 1 else ():  # text lines are too fine for tiny sizes
        for y, reach in ((38, 190), (84, 130)):
            layers.append(Layer(line(side * 70, y, side * (70 + reach), y, 15), "knock"))
    return layers


def atom_layers(heft: float) -> list[Layer]:
    """Speech-bubble cloud with a tail; a nucleus and two electron orbits knocked out of it."""
    h = 360
    puffs, base = cloud_parts(h, (0.28, 0.48, 0.36), 0.82)
    x = puffs[0][2]
    tail = QPainterPath(QPointF(x + 20, h - 40))
    tail.quadTo(x + 30, h + 70, x - 90, h + 125)
    tail.quadTo(x + 110, h + 105, x + 200, h - 20)
    tail.closeSubpath()
    centre = QPointF(puffs[1][0], 215)
    layers = [Layer(union([blob(puffs, base), tail]))]
    for turn in (35, -35):
        flip = QTransform().translate(centre.x(), centre.y()).rotate(turn)
        orbit = QPainterPath()
        orbit.addEllipse(QPointF(0, 0), 152, 53)
        layers.append(Layer(stroke(flip.map(orbit), 22 * heft), "knock"))
        electron = flip.map(QPointF(152 * turn / 35, 0))
        layers.append(Layer(disc(electron.x(), electron.y(), 20 * heft), "knock"))
    layers.append(Layer(disc(centre.x(), centre.y(), 34 * heft), "knock"))
    return layers


def wave_layers(heft: float) -> list[Layer]:
    """Equalizer bars whose tops trace a cloud."""
    puffs, base = cloud_parts(300, (0.30, 0.50, 0.38), 0.92)
    span = puffs[2][0] + puffs[2][2]
    count, width = (11, 38) if heft == 1 else (7, 58)
    pitch = (span - width) / (count - 1)
    grow = QTransform().translate(span / 2, 300).scale(1.07, 1.07).translate(-span / 2, -300)
    layers = [Layer(grow.map(blob(puffs, base)), "ghost")]
    for i in range(count):
        x = width / 2 + i * pitch
        top = min(top_edge(puffs, base, x), 300 - 1.3 * width)
        bar = QPainterPath()
        bar.addRoundedRect(QRectF(x - width / 2, top, width, 300 - top), width / 2, width / 2)
        layers.append(Layer(bar))
    return layers


DESIGNS = (
    Design(
        "cloud-voice",
        "White cloud with three sound-wave arcs on a sky-blue gradient.",
        ("#7DD1FF", "#3F9CF3", "#2D6BDC"),
        "#0F2F7A",
        voice_layers,
    ),
    Design(
        "cloud-book",
        "Cloud whose underside is an open book, on indigo to teal.",
        ("#5B4EE0", "#2E85C6", "#10B5A4"),
        "#14235E",
        book_layers,
    ),
    Design(
        "cloud-atom",
        "Speech-bubble cloud with a nucleus and two electron orbits, on deep blue to violet.",
        ("#1B3EA8", "#5A3FD0", "#9440E6"),
        "#150F55",
        atom_layers,
    ),
    Design(
        "cloud-wave",
        "Cloud built from equalizer bars on a coral to magenta gradient.",
        ("#FF8F5C", "#F2527A", "#CF2E92"),
        "#6A0F4A",
        wave_layers,
    ),
)


# --- rendering ------------------------------------------------------------------------------------


def blur_samples(sigma: float, count: int = 120) -> list[tuple[float, float, float]]:
    """Gaussian kernel as (dx, dy, weight) points on a sunflower spiral; weights sum to 1."""
    golden = math.pi * (3 - math.sqrt(5))
    points = []
    for k in range(count):
        r = 2.6 * sigma * math.sqrt((k + 0.5) / count)
        points.append(
            (r * math.cos(k * golden), r * math.sin(k * golden), math.exp(-((r / sigma) ** 2) / 2))
        )
    total = sum(weight for _, _, weight in points)
    return [(dx, dy, weight / total) for dx, dy, weight in points]


def soft_shadow(path: QPainterPath, sigma: float, alpha: float, tint: QColor, dy: float) -> QImage:
    """16-bit layer with a Gaussian-blurred copy of path, dy lower.

    The blur is the path drawn once per kernel sample and summed. 16 bits because each sample's
    alpha is tiny and 8-bit storage would round it away.
    """
    layer = blank(CANVAS, QImage.Format.Format_RGBA64_Premultiplied)
    color = QColor(tint)
    with painting(layer) as p:
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        p.setPen(Qt.PenStyle.NoPen)
        for ox, oy, weight in blur_samples(sigma):
            color.setAlphaF(alpha * weight)
            p.setBrush(color)
            p.setTransform(QTransform.fromTranslate(ox, oy + dy))
            p.drawPath(path)
    return layer


def body_gradient(design: Design) -> QLinearGradient:
    gradient = QLinearGradient(
        BODY_RECT.left() + 0.15 * BODY,
        BODY_RECT.top(),
        BODY_RECT.right() - 0.15 * BODY,
        BODY_RECT.bottom(),
    )
    last = len(design.stops) - 1
    for i, stop in enumerate(design.stops):
        gradient.setColorAt(i / last, QColor(stop))
    return gradient


def draw_body(p: QPainter, design: Design) -> None:
    body = squircle(BODY_RECT, RADIUS)
    p.drawImage(0, 0, soft_shadow(body, 12, 0.42, QColor(0, 0, 0), dy=14))
    p.fillPath(body, body_gradient(design))
    p.save()
    p.setClipPath(body)
    top, clear = BODY_RECT.top(), rgba("#FFFFFF", 0)
    p.fillRect(BODY_RECT, vertical(top, top + 0.5 * BODY, (0, rgba("#FFFFFF", 0.20)), (1, clear)))
    rim = vertical(top, top + 0.32 * BODY, (0, rgba("#FFFFFF", 0.62)), (1, clear))
    # Centered on the edge and clipped to the body, so only the inner 3 px show.
    p.setPen(QPen(rim, 6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(body)
    p.restore()


def fit(layers: Sequence[Layer], box: QRectF) -> QTransform:
    bounds = QRectF()
    for layer in layers:
        bounds = bounds.united(layer.path.boundingRect())
    scale = min(box.width() / bounds.width(), box.height() / bounds.height())
    return (
        QTransform()
        .translate(box.center().x(), box.center().y())
        .scale(scale, scale)
        .translate(-bounds.center().x(), -bounds.center().y())
    )


def draw_symbol(p: QPainter, design: Design, heft: float) -> None:
    layers = design.layers(heft)
    turn = fit(layers, SYMBOL_BOX)
    placed = [Layer(turn.map(layer.path), layer.style) for layer in layers]
    solid = union([layer.path for layer in placed if layer.style == "solid"])
    p.drawImage(0, 0, soft_shadow(solid, 10, 0.30, QColor(design.shade), dy=16))
    bounds = solid.boundingRect()
    white = QColor(255, 255, 255)
    tint = mix(white, QColor(design.stops[-1]), 0.20)
    fills = {
        "solid": vertical(bounds.top(), bounds.bottom(), (0, white), (1, tint)),
        "soft": rgba("#FFFFFF", 0.55),
        "ghost": rgba("#FFFFFF", 0.26),
        "knock": body_gradient(design),
    }
    for layer in placed:
        p.fillPath(layer.path, fills[layer.style])


def render(design: Design, heft: float) -> QImage:
    image = blank(CANVAS)
    with painting(image) as p:
        draw_body(p, design)
        draw_symbol(p, design, heft)
    return image


def render_design(design: Design) -> Rendered:
    return Rendered(render(design, 1.0), render(design, SMALL_HEFT))


def resized(master: QImage, size: int) -> QImage:
    if size == master.width():
        return master
    return master.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


# --- output ---------------------------------------------------------------------------------------


def save_png(image: QImage, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path), "PNG"):
        raise OSError(f"cannot write {path}")


def build_icns(iconset: Path, icns: Path) -> None:
    iconutil = shutil.which("iconutil")
    if iconutil is None:
        raise FileNotFoundError("iconutil not found: it ships with macOS")
    cmd = [iconutil, "-c", "icns", "-o", str(icns), str(iconset)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"iconutil failed: {(done.stderr or done.stdout).strip()}")


def write_design(design: Design, rendered: Rendered, out: Path) -> Path:
    folder = out / design.name
    save_png(rendered.master, folder / "icon_1024.png")
    save_png(rendered.at(512), folder / "icon_512.png")
    iconset = folder / "AppIcon.iconset"
    for filename, size in ICONSET:
        save_png(rendered.at(size), iconset / filename)
    build_icns(iconset, folder / "AppIcon.icns")
    return folder


def contact_sheet(rendered: dict[str, Rendered]) -> QImage:
    """Every design at 256 px and 128/64/32/16 px, on a light strip over a dark one."""
    column, strip, big = 400, 520, 256
    names = list(rendered)
    sheet = QImage(column * len(names), strip * 2, QImage.Format.Format_ARGB32_Premultiplied)
    title, caption = QFont("Helvetica Neue"), QFont("Helvetica Neue")
    title.setPixelSize(24)
    title.setWeight(QFont.Weight.DemiBold)
    caption.setPixelSize(12)
    with painting(sheet) as p:
        for row, (paper, ink) in enumerate((("#F3F3F6", "#1D1D1F"), ("#1C1C1F", "#F2F2F7"))):
            top = row * strip
            p.fillRect(0, top, sheet.width(), strip, QColor(paper))
            for col, name in enumerate(names):
                mid = col * column + column // 2
                p.setPen(QColor(ink))
                p.setFont(title)
                label = QRectF(col * column, top + 18, column, 34)
                p.drawText(label, Qt.AlignmentFlag.AlignCenter, name)
                p.drawImage(mid - big // 2, top + 62, rendered[name].at(big))
                x = mid - (sum(PREVIEW_SMALL) + 24 * (len(PREVIEW_SMALL) - 1)) // 2
                p.setFont(caption)
                for size in PREVIEW_SMALL:
                    p.drawImage(x, top + 344 + (128 - size), rendered[name].at(size))
                    cell = QRectF(x - 12, top + 478, size + 24, 18)
                    p.drawText(cell, Qt.AlignmentFlag.AlignCenter, str(size))
                    x += size + 24
    return sheet


def build(out: Path, only: str | None = None) -> int:
    ensure_app()
    designs = [d for d in DESIGNS if only in (None, d.name)]
    rendered = {d.name: render_design(d) for d in DESIGNS}
    try:
        for design in designs:
            print(f"{design.name} -> {write_design(design, rendered[design.name], out)}")
    except (OSError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 2
    save_png(contact_sheet(rendered), out / "preview.png")
    print(f"preview -> {out / 'preview.png'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    names = [d.name for d in DESIGNS]
    parser = argparse.ArgumentParser(
        description="Render the Cloudy Reader app-icon candidates.",
        epilog="\n".join(f"{d.name}: {d.summary}" for d in DESIGNS),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--only", choices=names, metavar="NAME", help=f"one of {', '.join(names)}")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output dir (assets/icons)")
    args = parser.parse_args(argv)
    return build(args.out, args.only)


if __name__ == "__main__":
    sys.exit(main())
