"""Render the documentation figures in site/public/img as vector SVG from the live app window.

Usage, with the app's own environment so the figures show the current UI:
  uv run --frozen --offline --project <repo> python scripts/make_doc_snapshots.py --out <dir>

Qt lays out the real MainWindow and About box without showing them: on macOS with the native style
(the cocoa platform), elsewhere on `offscreen`. The service is the GUI fake (no network, no audio)
fed the real voice catalog and the real parser and normalizer; settings go to a temp folder.
QSvgGenerator cannot capture the native macOS style, so each control is drawn here as vector
shapes from its live geometry and font. Colors come from the live palette and tokens.py, plus
control fills sampled from native renders. Popup menus are drawn from the combo box's real items.
A window figure shows the content only, with square corners: the site draws the window frame.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import os
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any
from xml.sax.saxutils import escape, quoteattr

os.environ.setdefault("QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM", "1")  # no Dock icon
sys.dont_write_bytecode = True  # never leave .pyc files in the app checkout

from PySide6.QtCore import QPoint, QRectF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QAction,
    QColor,
    QFont,
    QFontMetricsF,
    QIcon,
    QKeySequence,
    QPainterPath,
    QPalette,
    QTextCursor,
    QTextLayout,
)
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QWidget,
)

import cloudyreader  # noqa: E402

ROOT = Path(cloudyreader.__file__).resolve().parents[1]  # the checkout the app code comes from
FONT = (
    "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', Helvetica, Arial, "
    "sans-serif"
)
MENU_ROW = 22.0  # macOS menu metrics: row height, padding, corner, text and tail insets
MENU_PAD = 5.0
MENU_RADIUS = 8.0
MENU_TEXT = 21.0
MENU_TAIL = 24.0
GAP = 18.0  # between stacked status strips
CALLOUT_BAND = 36.0  # empty band above a status strip where its numbered markers sit
LESSAC = "piper:en_US-lessac-medium"
HEART = "kokoro:af_heart"  # the top voice: where the Voice menu opens on a fresh install
MISSING = "kokoro:am_adam"  # the one voice shown as not installed: the last Kokoro row, in view
SQ1_LESSAC_S = 19.3  # how long SQ1 plays with lessac, answer line off, in a measured run
SQ1_HEART_S = 24.9  # the same with Heart
PLAYING = f"Playing {SQ1_LESSAC_S:.1f} s."  # the status while a window figure reads SQ1
ROUND = {"stroke_linecap": "round", "stroke_linejoin": "round"}
# SQ1 of the manual plan, written for the manual: every window figure shows this paste.
MANUAL_QUESTION = (
    "TOSS-UP\n"
    "1) CHEMISTRY Multiple Choice Which gas forms when sodium bicarbonate, NaHCO3, reacts with "
    "acetic acid?\n"
    "W) Oxygen\nX) Hydrogen\nY) Carbon dioxide\nZ) Nitrogen\n"
    "ANSWER: Y) CARBON DIOXIDE"
)
# A malformed respelling (all syllables in capitals gives no stress): the normalizer warns.
GUIDE_QUESTION = (
    "TOSS-UP\n"
    "3) EARTH AND SPACE Short Answer What green mineral, olivine [OL-UH-VEEN], is common in "
    "Earth's upper mantle?\n"
    "ANSWER: OLIVINE"
)


# --- SVG writing -------------------------------------------------------------------------------


def num(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def attrs(**values: object) -> str:
    out = []
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, float | int) and not isinstance(value, bool):
            value = num(value)
        out.append(f" {key.rstrip('_').replace('_', '-')}={quoteattr(str(value))}")
    return "".join(out)


def paint(color: QColor, kind: str = "fill") -> dict[str, object]:
    alpha = round(color.alphaF(), 3)
    return {kind: color.name(), f"{kind}_opacity": alpha if alpha < 1 else None}


def rgba(hex_color: str, alpha: float = 1.0) -> QColor:
    color = QColor(hex_color)
    color.setAlphaF(alpha)
    return color


def text_paint(color: QColor) -> dict[str, object]:
    """A text color as SVG attributes: opacity, not fill-opacity, which sips ignores on text."""
    alpha = round(color.alphaF(), 3)
    return {"fill": color.name(), "opacity": alpha if alpha < 1 else None}


def rect_attrs(r: QRectF, radius: float = 0) -> str:
    return attrs(x=r.x(), y=r.y(), width=r.width(), height=r.height(), rx=radius or None)


class Svg:
    """One figure: a viewBox in points, a title and description, defs, and drawing elements."""

    def __init__(self, width: float, height: float, title: str, desc: str) -> None:
        self.width, self.height, self.title, self.desc = width, height, title, desc
        self.scale = 1.0  # display size over viewBox: 2 shows a small panel at twice its size
        self.origin = (0.0, 0.0)  # viewBox corner: a crop draws the whole window, shows a part
        self._defs: list[str] = []
        self._body: list[str] = []
        self._ids = itertools.count(1)

    def uid(self, stem: str) -> str:
        return f"{stem}{next(self._ids)}"

    def define(self, element: str) -> None:
        self._defs.append(element)

    def add(self, element: str) -> None:
        self._body.append(element)

    def rect(self, r: QRectF, radius: float = 0, **kw: object) -> None:
        self.add(f"<rect{rect_attrs(r, radius)}{attrs(**kw)}/>")

    def path(self, d: str, **kw: object) -> None:
        self.add(f"<path{attrs(d=d, **kw)}/>")

    def circle(self, cx: float, cy: float, r: float, **kw: object) -> None:
        self.add(f"<circle{attrs(cx=cx, cy=cy, r=r, **kw)}/>")

    def text(self, x: float, y: float, value: str, **kw: object) -> None:
        # Text takes opacity, not fill-opacity: some renderers, sips among them, ignore the latter.
        if "fill_opacity" in kw:
            kw["opacity"] = kw.pop("fill_opacity")
        self.add(f"<text{attrs(x=x, y=y, **kw)}>{escape(value)}</text>")

    def clip(self, inner: str) -> str:
        cid = self.uid("clip")
        self.define(f'<clipPath id="{cid}">{inner}</clipPath>')
        return cid

    def blur(self, deviation: float) -> str:
        fid = self.uid("blur")
        self.define(
            f'<filter id="{fid}" x="-30%" y="-30%" width="160%" height="160%">'
            f'<feGaussianBlur stdDeviation="{num(deviation)}"/></filter>'
        )
        return fid

    def gradient(self, stops: Sequence[tuple[float, QColor]], **kw: object) -> str:
        """A linear gradient, top to bottom unless x1/y1/x2/y2 say otherwise."""
        gid = self.uid("grad")
        parts = []
        for at, color in stops:
            alpha = color.alphaF()
            stop = attrs(
                offset=at, stop_color=color.name(), stop_opacity=alpha if alpha < 1 else None
            )
            parts.append(f"<stop{stop}/>")
        line = {"x1": 0, "y1": 0, "x2": 0, "y2": 1, **kw}
        self.define(f"<linearGradient{attrs(id=gid, **line)}>{''.join(parts)}</linearGradient>")
        return gid

    def xml(self) -> str:
        w, h = num(self.width), num(self.height)
        shown_w, shown_h = num(self.width * self.scale), num(self.height * self.scale)
        defs = f"<defs>{''.join(self._defs)}</defs>\n" if self._defs else ""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{shown_w}" height="{shown_h}" '
            f'viewBox="{num(self.origin[0])} {num(self.origin[1])} {w} {h}" role="img" '
            'aria-labelledby="title desc" '
            f"font-family={quoteattr(FONT)}>\n"
            f'<title id="title">{escape(self.title)}</title>\n'
            f'<desc id="desc">{escape(self.desc)}</desc>\n'
            f"{defs}" + "\n".join(self._body) + "\n</svg>\n"
        )


def qpath_d(path: QPainterPath) -> str:
    """SVG path data for a QPainterPath: moves, lines, and cubic curves."""

    def pt(e: Any) -> str:
        return f"{round(e.x, 1):g} {round(e.y, 1):g}"

    out, i, kinds = [], 0, QPainterPath.ElementType
    while i < path.elementCount():
        e = path.elementAt(i)
        if e.type == kinds.MoveToElement:
            out.append(f"M{pt(e)}")
            i += 1
        elif e.type == kinds.LineToElement:
            out.append(f"L{pt(e)}")
            i += 1
        else:  # a CurveToElement, then its two CurveToDataElements
            out.append(f"C{pt(e)} {pt(path.elementAt(i + 1))} {pt(path.elementAt(i + 2))}")
            i += 3
    return "".join(out)


def fill_rule(path: QPainterPath) -> str | None:
    return "evenodd" if path.fillRule() == Qt.FillRule.OddEvenFill else None


# --- colors per appearance ---------------------------------------------------------------------


@dataclass(frozen=True)
class Look:
    """Colors for one appearance; text and backgrounds come from the live palette."""

    dark: bool
    window: QColor
    label: QColor
    disabled: QColor
    base: QColor
    placeholder: QColor
    field_edge: QColor
    field_top: QColor
    control: QColor
    control_edge: QColor
    control_shine: QColor
    control_shadow: QColor
    control_off: QColor
    default: QColor
    cap_top: QColor
    cap_bottom: QColor
    accent: QColor
    box: QColor
    box_edge: QColor
    chevron: QColor
    separator: QColor
    track: QColor
    menu: QColor
    menu_edge: QColor
    window_edge: QColor
    shadow: QColor
    warning: QColor
    error: QColor
    ink: QColor  # captions outside the app's own chrome


# Sampled from 2x native renders of this window (light, then dark); errors and warnings are the
# system red and yellow.
_SAMPLED = {
    False: {
        "field_edge": QColor("#B6B6B6"),
        "field_top": QColor("#8E8E8E"),
        "control": QColor("#FFFFFF"),
        "control_edge": rgba("#000000", 0.13),
        "control_shine": rgba("#FFFFFF", 0),
        "control_shadow": rgba("#000000", 0.24),
        "control_off": QColor("#F5F5F5"),
        "default": QColor("#077EFF"),
        "cap_top": QColor("#2690FF"),
        "cap_bottom": QColor("#047DFF"),
        "accent": QColor("#077EFF"),
        "box": QColor("#FFFFFF"),
        "box_edge": rgba("#000000", 0.18),
        "chevron": QColor("#ACACAC"),
        "separator": QColor("#838383"),
        "track": QColor("#E0E0E0"),
        "menu": QColor("#F6F6F6"),
        "menu_edge": rgba("#000000", 0.14),
        "window_edge": rgba("#000000", 0.2),
        "shadow": rgba("#000000", 0.3),
        "warning": QColor("#FFCC00"),
        "error": QColor("#FF3B30"),
    },
    True: {
        "field_edge": QColor("#101010"),
        "field_top": QColor("#0D0D0D"),
        "control": QColor("#656565"),
        "control_edge": rgba("#000000", 0.25),
        "control_shine": rgba("#FFFFFF", 0.14),
        "control_shadow": rgba("#000000", 0.25),
        "control_off": QColor("#4B4B4B"),
        "default": QColor("#1560D2"),
        "cap_top": QColor("#177AE4"),
        "cap_bottom": QColor("#156FCF"),
        "accent": QColor("#1C6CDC"),
        "box": QColor("#5E5E5E"),
        "box_edge": rgba("#000000", 0.3),
        "chevron": QColor("#B2B2B2"),
        "separator": QColor("#838383"),
        "track": QColor("#474747"),
        "menu": QColor("#2B2B2B"),
        "menu_edge": rgba("#FFFFFF", 0.16),
        "window_edge": rgba("#FFFFFF", 0.14),
        "shadow": rgba("#000000", 0.55),
        "warning": QColor("#FFD60A"),
        "error": QColor("#FF453A"),
    },
}


def look_for(dark: bool, palette: QPalette | None) -> Look:
    """The appearance's colors: the live palette when the platform applied it, else its values."""
    from cloudyreader.gui import tokens

    ink = "#FFFFFF" if dark else "#000000"
    window = QColor("#323232" if dark else "#ECECEC")
    base = QColor("#171717" if dark else "#FFFFFF")
    label, disabled = rgba(ink, 0.85), rgba(ink, 0.25)
    if palette is not None:
        role = QPalette.ColorRole
        window, base = palette.color(role.Window), palette.color(role.Base)
        label = palette.color(QPalette.ColorGroup.Active, role.WindowText)
        disabled = palette.color(QPalette.ColorGroup.Disabled, role.WindowText)
    placeholder = QColor(tokens.PLACEHOLDER_DARK if dark else tokens.PLACEHOLDER_LIGHT)
    return Look(
        dark=dark,
        window=window,
        label=label,
        disabled=disabled,
        base=base,
        placeholder=placeholder,
        ink=rgba(ink, 0.85),
        **_SAMPLED[dark],
    )


# --- the live app ------------------------------------------------------------------------------


class Env:
    """The QApplication, a temp folder, the real voice catalog, and helpers to drive windows."""

    def __init__(self, platform: str, *, engines: bool = False) -> None:
        argv = ["make_doc_snapshots", "-platform", platform]
        self.app = QApplication.instance() or QApplication(argv)
        self.tmp = Path(tempfile.mkdtemp(prefix="cloudyreader-docs-"))
        # Every QSettings the app makes lands here, never in the user's preferences.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(self.tmp))
        self.app.setApplicationName("Cloudy Reader")
        self.app.setOrganizationName("CloudyReaderDocs")
        icon = ROOT / "assets" / "icons" / "cloud-atom" / "icon_512.png"
        if icon.is_file():  # what a source checkout shows in the About box
            self.app.setWindowIcon(QIcon(str(icon)))
        self.voices = real_voices(self.tmp)
        if engines:  # the 0.0.2 catalog: Chatterbox Turbo and Qwen3-TTS rows among the voices
            self.voices = with_engine_rows(self.voices)
        self.service_class = doc_service_class()
        self._ids = itertools.count(1)
        # Every figure shows the busy bar where the app does by default, whatever this Mac's
        # Reduce Motion setting is.
        from cloudyreader.gui import main_window

        main_window.reduce_motion = lambda: False

    def scheme(self, dark: bool) -> Look:
        wanted = Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light
        self.app.styleHints().setColorScheme(wanted)
        for _ in range(10):
            self.app.processEvents()
        applied = self.app.styleHints().colorScheme() == wanted
        return look_for(dark, self.app.palette() if applied else None)

    def pump(self, until: Callable[[], bool], what: str, timeout_s: float = 15.0) -> None:
        deadline = time.monotonic() + timeout_s
        while not until():
            if time.monotonic() > deadline:
                raise TimeoutError(f"the window never reached: {what}")
            self.app.processEvents()
            time.sleep(0.005)

    @contextmanager
    def window(
        self,
        *,
        rotation: str | None = None,
        voices: Sequence[Any] | None = None,
        saved_voice: str = LESSAC,
        **knobs: object,
    ) -> Iterator[tuple[Any, Any]]:
        """A shown-offscreen MainWindow with its voices listed, and its fake service.

        voices replaces the full catalog, as at a first launch with nothing downloaded yet.
        """
        from cloudyreader.gui.fake_service import FakeClipboard, FakePlayer
        from cloudyreader.gui.main_window import MainWindow

        path = self.tmp / f"window{next(self._ids)}.ini"
        settings = QSettings(str(path), QSettings.Format.IniFormat)
        settings.setValue("voice", saved_voice)
        if rotation is not None:
            settings.setValue("voice_rotation", rotation)
        listed = self.voices if voices is None else list(voices)
        service = self.service_class(voices=listed, **knobs)
        win = MainWindow(service, FakePlayer(), settings=settings, clipboard=FakeClipboard())
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        win.show()
        try:
            self.pump(lambda: not win.loading_voices, "voices listed")
            yield win, service
        finally:
            win.close()  # cancels a held download: it reports nothing after this
            for gate in (service.gate, service.prefetch_gate):
                if gate is not None:
                    gate.set()
            # Deleting the window waits for its pool; a job still held there would need the GIL.
            win._pool.waitForDone(10_000)
            win.deleteLater()
            self.app.processEvents()

    def speak(self, win: Any, text: str) -> None:
        played: list[object] = []
        win.reading_played.connect(played.append)
        win.question_edit.setPlainText(text)
        win.speak_action.trigger()
        self.pump(lambda: bool(played), "a reading plays")

    def hold_reading(self, win: Any, service: Any) -> None:
        """Start a reading that waits in prepare(); window() releases it. The busy bar shows,
        unless a download bar does: the window shows one bar at a time."""
        busy: list[bool] = []
        win.busy_changed.connect(busy.append)
        service.gate = threading.Event()
        win.question_edit.setPlainText(sample_question())
        win.speak_action.trigger()
        self.pump(lambda: True in busy, "a reading in preparation")


def real_voices(tmp: Path) -> list[Any]:
    """The voices the app lists once every pinned voice is in: their real names and order.

    Piper voices come from a scan of stand-in files named as in assets.lock.json, Kokoro voices
    from the engine's own table. One Kokoro voice stays not installed, as after a failed download.
    The order is the app's own sort key, the one TtsService.voices() lists them by.
    """
    from cloudyreader.engines.kokoro import RECOMMENDED_VOICES, VOICE_GRADES, KokoroEngine
    from cloudyreader.voice_meta import voice_sort_key
    from cloudyreader.voices import scan_installed

    folder = tmp / "voices"
    folder.mkdir()
    lock = json.loads((ROOT / "assets.lock.json").read_text(encoding="utf-8"))
    for asset in lock["assets"]:
        if asset["group"] == "voices" and asset["name"].endswith(".onnx"):
            stem = asset["name"].removesuffix(".onnx")
            language, _, rest = stem.partition("-")
            config = {
                "language": {"code": language},
                "audio": {"quality": rest.rpartition("-")[2]},
                "num_speakers": 1,
            }
            (folder / asset["name"]).write_bytes(b"")
            (folder / f"{asset['name']}.json").write_text(json.dumps(config))
    engine = KokoroEngine(tmp / "kokoro", all_voices=True)
    ids = [*RECOMMENDED_VOICES, *(v for v in VOICE_GRADES if v not in RECOMMENDED_VOICES)]
    kokoro = [engine._voice_info(vid) for vid in ids]  # what voices() lists on Apple Silicon
    voices = scan_installed(folder) + [replace(v, installed=v.key != MISSING) for v in kokoro]
    return sorted(voices, key=voice_sort_key)


def doc_service_class() -> type:
    from cloudyreader.gui.fake_service import FakeReaderService
    from cloudyreader.lexicon import Lexicon
    from cloudyreader.normalize import ScriptNormalizer
    from cloudyreader.parser import QuestionParser

    normalizer = ScriptNormalizer(Lexicon.load())

    class DocService(FakeReaderService):
        """The GUI fake with the real parser and normalizer, so the spoken script is genuine."""

        def prepare(self, raw: str, voice_key: str, opts: Any) -> Any:
            reading = super().prepare(raw, voice_key, opts)
            questions = QuestionParser().parse(raw)
            script = normalizer.to_script(questions, {}, opts)
            return replace(reading, questions=tuple(questions), script=script)

    return DocService


def sample_question() -> str:
    """The paste every window figure shows: SQ1, the manual's own sample question."""
    return MANUAL_QUESTION


# --- drawing the widgets -----------------------------------------------------------------------


def baseline(top: float, height: float, font: QFont) -> float:
    metrics = QFontMetricsF(font)
    return top + (height - metrics.height()) / 2 + metrics.ascent()


def font_kw(font: QFont) -> dict[str, object]:
    weight = font.weight()
    weight = weight.value if hasattr(weight, "value") else int(weight)
    tabular = font.featureValue(QFont.Tag("tnum")) == 1  # digits of one width, as the app sets
    return {
        "font_size": font.pointSizeF(),
        "font_weight": weight if weight != 400 else None,
        "style": "font-variant-numeric:tabular-nums" if tabular else None,
    }


def pts(*xy: float) -> str:
    """'x y' pairs for path data."""
    return " ".join(num(v) for v in xy)


class Canvas:
    """Draws a live widget tree into an Svg at an offset, as macOS controls in an active window."""

    def __init__(self, svg: Svg, look: Look, root: QWidget, dx: float, dy: float) -> None:
        self.svg, self.look, self.root, self.dx, self.dy = svg, look, root, dx, dy
        self.icon_painter: Callable[[QRectF], None] | None = None

    def geo(self, widget: QWidget) -> QRectF:
        corner = widget.mapTo(self.root, QPoint(0, 0))
        return QRectF(corner.x() + self.dx, corner.y() + self.dy, widget.width(), widget.height())

    def tree(self, parent: QWidget) -> None:
        for child in parent.children():
            if isinstance(child, QWidget) and not child.isWindow() and child.isVisibleTo(self.root):
                self.widget(child)

    def widget(self, w: QWidget) -> None:
        from cloudyreader.gui.widgets import Card, DisclosureButton, StatusBar

        if isinstance(w, Card):
            self.card(w)
            self.tree(w)  # its text view, frameless: the card is its surface
        elif isinstance(w, QPlainTextEdit):
            self.field(w)
        elif isinstance(w, QComboBox):
            self.popup(w)
        elif isinstance(w, QCheckBox):
            self.checkbox(w)
        elif isinstance(w, DisclosureButton):
            self.disclosure(w)
        elif isinstance(w, QPushButton):
            self.button(w)
        elif isinstance(w, QProgressBar):
            self.progress(w)
        elif isinstance(w, QLabel):
            self.label(w)
        elif isinstance(w, StatusBar):
            self.status_bar(w)
            self.tree(w)  # its permanent widgets: the download label and bar, the busy bar
        else:
            self.tree(w)

    def bezel(self, r: QRectF, fill: QColor, *, edge: bool = True, radius: float = 5.5) -> None:
        """A control bezel: soft shadow below, 0.5 pt edge, and in Dark Mode a top shine."""
        look, svg = self.look, self.svg
        svg.rect(r.translated(0, 0.6), radius, **paint(look.control_shadow))
        svg.rect(r, radius, **paint(fill))
        if not edge:
            return
        inset = r.adjusted(0.25, 0.25, -0.25, -0.25)
        svg.rect(inset, radius, fill="none", stroke_width=0.5, **paint(look.control_edge, "stroke"))
        if look.dark:
            shine = f"M{pts(r.left() + radius, r.top() + 0.75)}H{num(r.right() - radius)}"
            svg.path(shine, stroke_width=0.5, **paint(look.control_shine, "stroke"))

    def button(self, b: QPushButton) -> None:
        opt = QStyleOptionButton()
        b.initStyleOption(opt)
        item = b.style().subElementRect(QStyle.SubElement.SE_PushButtonLayoutItem, opt, b)
        r = QRectF(item).translated(self.geo(b).topLeft())
        on = b.isEnabled()
        primary = on and b.isDefault()
        look = self.look
        fill = look.default if primary else (look.control if on else look.control_off)
        self.bezel(r, fill, edge=not primary)
        color = QColor("#FFFFFF") if primary else (look.label if on else look.disabled)
        y = baseline(r.top(), r.height(), b.font())
        kw = {"text_anchor": "middle", **font_kw(b.font()), **paint(color)}
        self.svg.text(r.center().x(), y, b.text(), **kw)

    def popup_bezel(self, c: QComboBox) -> QRectF:
        """The drawn popup button inside the widget, as measured on native renders."""
        g = self.geo(c)
        return QRectF(g.left() + 5.5, g.top() + 4, g.width() - 12, 20.5)

    def popup(self, c: QComboBox) -> None:
        r, look, svg = self.popup_bezel(c), self.look, self.svg
        on = c.isEnabled()
        self.bezel(r, look.control if on else look.control_off)
        cap = QRectF(r.right() - 18.5, r.top() + 2, 15.5, r.height() - 4)
        top, bottom = (look.cap_top, look.cap_bottom) if on else (look.disabled, look.disabled)
        svg.rect(cap, 4, fill=f"url(#{svg.gradient([(0, top), (1, bottom)])})")
        cx, cy = cap.center().x(), cap.center().y()
        chevrons = f"M{pts(cx - 3, cy - 1.5)}l3 -2.8l3 2.8M{pts(cx - 3, cy + 1.5)}l3 2.8l3 -2.8"
        svg.path(chevrons, fill="none", stroke="#FFFFFF", stroke_width=1.5, **ROUND)
        text = c.currentText() or c.placeholderText()
        color = look.label if on and c.currentIndex() >= 0 else look.disabled
        y = baseline(r.top(), r.height(), c.font())
        svg.text(r.left() + 9, y, text, **font_kw(c.font()), **paint(color))

    def checkbox(self, c: QCheckBox) -> None:
        opt = QStyleOptionButton()
        c.initStyleOption(opt)
        style, g, look, svg = c.style(), self.geo(c), self.look, self.svg
        ind = style.subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, c)
        box = QRectF(g.left() + ind.left() + 1.5, g.top() + ind.center().y() - 6.5, 14, 14)
        if c.isChecked():
            svg.rect(box, 3.5, **paint(look.accent))
            x, y = box.left(), box.top()
            check = f"M{pts(x + 3.4, y + 7.4)}L{pts(x + 6, y + 10)}L{pts(x + 10.6, y + 4.4)}"
            svg.path(check, fill="none", stroke="#FFFFFF", stroke_width=1.9, **ROUND)
        else:
            svg.rect(box.translated(0, 0.5), 3.5, **paint(look.control_shadow))
            svg.rect(box, 3.5, **paint(look.box))
            edge = box.adjusted(0.25, 0.25, -0.25, -0.25)
            svg.rect(edge, 3.5, fill="none", stroke_width=0.5, **paint(look.box_edge, "stroke"))
        content = style.subElementRect(QStyle.SubElement.SE_CheckBoxContents, opt, c)
        y = baseline(g.top(), g.height(), c.font())
        svg.text(g.left() + content.left(), y, c.text(), **font_kw(c.font()), **paint(look.label))

    def disclosure(self, d: Any) -> None:
        from cloudyreader.gui import tokens

        g, size = self.geo(d), tokens.DISCLOSURE_SIZE
        x, y = g.left(), g.top() + (g.height() - size) / 2
        if d.isChecked():
            shape = f"M{pts(x + 3, y + 4.5)}L{pts(x + 6.5, y + 8.5)}L{pts(x + 10, y + 4.5)}"
        else:
            shape = f"M{pts(x + 4.5, y + 3)}L{pts(x + 8.5, y + 6.5)}L{pts(x + 4.5, y + 10)}"
        stroke = paint(self.look.chevron, "stroke")
        self.svg.path(shape, fill="none", stroke_width=1.6, **stroke, **ROUND)
        tx, ty = x + size + tokens.INDICATOR_SPACING, baseline(g.top(), g.height(), d.font())
        self.svg.text(tx, ty, d.text(), **font_kw(d.font()), **paint(self.look.label))

    def card(self, c: Any) -> None:
        """The question card or the script panel: a rounded fill, outlined when it has one."""
        from cloudyreader.gui import tokens

        r, radius, border = self.geo(c), float(tokens.CARD_RADIUS), c.border
        if border is None:
            self.svg.rect(r, radius, **paint(c.fill))
            return
        half = tokens.BORDER_WIDTH / 2  # the stroke sits inside the card's edge, as painted
        inset = r.adjusted(half, half, -half, -half)
        stroke = {"stroke_width": tokens.BORDER_WIDTH, **paint(border, "stroke")}
        self.svg.rect(inset, radius - half, **paint(c.fill), **stroke)

    def field(self, e: QPlainTextEdit) -> None:
        from cloudyreader.gui.widgets import Card

        look, svg, g = self.look, self.svg, self.geo(e)
        if not isinstance(e.parentWidget(), Card):  # a plain field draws its own sunken frame
            frame = g.adjusted(0.5, 0.5, -0.5, -0.5)
            svg.rect(frame, stroke_width=1, **paint(look.base), **paint(look.field_edge, "stroke"))
            top_edge = f"M{pts(g.left() + 1, g.top() + 0.5)}H{num(g.right() - 1)}"
            svg.path(top_edge, stroke_width=1, **paint(look.field_top, "stroke"))
        view = self.geo(e.viewport())
        clip = svg.clip(f"<rect{rect_attrs(view)}/>")
        doc, lines = e.document(), []
        # The window gives each view its colors: the text, or the placeholder while it is empty.
        role = QPalette.ColorRole.PlaceholderText if doc.isEmpty() else QPalette.ColorRole.Text
        if doc.isEmpty():
            r = e.cursorRect(QTextCursor(doc))
            y = view.top() + r.top() + QFontMetricsF(e.font()).ascent()
            where = attrs(x=view.left() + r.left(), y=y)
            lines.append(f"<text{where}>{escape(e.placeholderText())}</text>")
        block = doc.firstBlock()
        while block.isValid() and not doc.isEmpty():
            layout = block.layout()
            for i in range(layout.lineCount()):
                line = layout.lineAt(i)
                start = line.textStart()
                chunk = block.text()[start : start + line.textLength()].rstrip()
                if not chunk:
                    continue
                cursor = QTextCursor(doc)
                cursor.setPosition(block.position() + start)
                r = e.cursorRect(cursor)
                where = attrs(x=view.left() + r.left(), y=view.top() + r.top() + line.ascent())
                lines.append(f"<text{where}>{escape(chunk)}</text>")
            block = block.next()
        ink = text_paint(e.palette().color(role))
        group = attrs(clip_path=f"url(#{clip})", **font_kw(e.font()), **ink)
        svg.add(f"<g{group}>" + "".join(lines) + "</g>")

    def label(self, label: QLabel) -> None:
        r = QRectF(label.contentsRect()).translated(self.geo(label).topLeft())
        pixmap = label.pixmap()
        if pixmap is not None and not pixmap.isNull():
            if self.icon_painter is not None:
                size = pixmap.deviceIndependentSize()
                box = QRectF(0, 0, size.width(), size.height())
                box.moveCenter(r.center())
                self.icon_painter(box)
            return
        from cloudyreader.gui.widgets import ElidedLabel

        if isinstance(label, ElidedLabel):  # one line, cut at its end when short of room
            text = label.fontMetrics().elidedText(
                label.text(), Qt.TextElideMode.ElideRight, label.contentsRect().width()
            )
            self.paragraph(text, label.font(), r, label.alignment(), False)
        elif label.text():
            self.paragraph(label.text(), label.font(), r, label.alignment(), label.wordWrap())

    def paragraph(self, text: str, font: QFont, r: QRectF, align: Any, wrap: bool) -> None:
        """Text laid out by Qt, one <text> per line, placed as QLabel aligns it."""
        rows: list[tuple[str, float, float]] = []  # text, line top, ascent
        height = 0.0
        for para in text.split("\n"):
            layout = QTextLayout(para, font)
            layout.beginLayout()
            while (line := layout.createLine()).isValid():
                line.setLineWidth(r.width() if wrap else 1e6)
                start = line.textStart()
                rows.append(
                    (para[start : start + line.textLength()].rstrip(), height, line.ascent())
                )
                height += line.height()
            layout.endLayout()
        flag = Qt.AlignmentFlag
        y0 = r.top()
        if align & flag.AlignVCenter:
            y0 += (r.height() - height) / 2
        elif align & flag.AlignBottom:
            y0 += r.height() - height
        anchor, x = None, r.left()
        if align & flag.AlignRight:
            anchor, x = "end", r.right()
        elif align & flag.AlignHCenter:
            anchor, x = "middle", r.center().x()
        kw = {"text_anchor": anchor, **font_kw(font), **paint(self.look.label)}
        for chunk, top, ascent in rows:
            self.svg.text(x, y0 + top + ascent, chunk, **kw)

    def progress(self, bar: QProgressBar) -> None:
        g, svg, look = self.geo(bar), self.svg, self.look
        track = QRectF(g.left(), g.center().y() - 3, g.width(), 6)
        svg.rect(track, 3, **paint(look.track))
        span = bar.maximum() - bar.minimum()
        if span > 0:  # determinate: the share done, in the accent color
            share = (bar.value() - bar.minimum()) / span
            done = QRectF(track.left(), track.top(), max(6.0, track.width() * share), 6)
            svg.rect(done, 3, **paint(look.accent))
        else:  # indeterminate: one still frame of its moving highlight
            glow = QRectF(track.left() + 0.18 * track.width(), track.top(), 0.34 * track.width(), 6)
            svg.rect(glow, 3, opacity=0.55, **paint(look.accent))

    def status_bar(self, bar: Any) -> None:
        g, look, svg = self.geo(bar), self.look, self.svg
        svg.path(
            f"M{pts(g.left(), g.top() + 0.25)}H{num(g.right())}",
            stroke_width=0.5,
            **paint(look.separator, "stroke"),
        )
        if not bar.currentMessage():
            return
        icon, text_rect, elided = bar.message_layout()
        if icon.isValid():
            self.tone_icon(QRectF(icon).translated(g.topLeft()), bar.tone.value)
        t = QRectF(text_rect).translated(g.topLeft())
        y = baseline(t.top(), t.height(), bar.font())
        svg.text(t.left(), y, elided, **font_kw(bar.font()), **paint(look.label))

    def tone_icon(self, r: QRectF, tone: str) -> None:
        """The status bar's warning triangle or error disc, drawn as the system alert badges."""
        x, y, svg = r.left(), r.top(), self.svg
        if tone == "warning":
            color = self.look.warning
            triangle = f"M{pts(x + 8, y + 2)}L{pts(x + 14.6, y + 14)}H{num(x + 1.4)}Z"
            svg.path(
                triangle,
                stroke=color.name(),
                stroke_width=2,
                stroke_linejoin="round",
                **paint(color),
            )
            ink = rgba("#000000", 0.85)
        else:
            svg.circle(x + 8, y + 8, 7.5, **paint(self.look.error))
            ink = QColor("#FFFFFF")
        svg.rect(QRectF(x + 7.2, y + 4.6, 1.6, 5.6), 0.8, **paint(ink))
        svg.circle(x + 8, y + 12.2, 0.95, **paint(ink))


# --- window content and menus -----------------------------------------------------------------


def draw_content(
    svg: Svg, look: Look, widget: QWidget, *, icon: Callable[[QRectF], None] | None = None
) -> QRectF:
    """A window's content at the origin: square corners, no title bar, no shadow."""
    r = QRectF(0, 0, widget.width(), widget.height())
    svg.rect(r, **paint(look.window))
    clip = svg.clip(f"<rect{rect_attrs(r)}/>")
    svg.add(f'<g clip-path="url(#{clip})">')
    canvas = Canvas(svg, look, widget, 0, 0)
    canvas.icon_painter = icon
    canvas.tree(widget)
    svg.add("</g>")
    return r


@dataclass(frozen=True)
class MenuItem:
    text: str
    enabled: bool
    header: QFont | None = None  # a section header's own font; None for a choice
    ink: QColor | None = None  # a section header's own color


def combo_items(combo: QComboBox) -> list[MenuItem]:
    """A popup's rows: choices, and section headers in the font and color their rows carry."""
    model, items = combo.model(), []
    for i in range(combo.count()):
        index = model.index(i, combo.modelColumn())
        flags = model.flags(index)
        font = index.data(Qt.ItemDataRole.FontRole)
        brush = index.data(Qt.ItemDataRole.ForegroundRole)
        header = flags == Qt.ItemFlag.NoItemFlags and isinstance(font, QFont)
        ink = brush.color() if header and brush is not None else None
        enabled = bool(flags & Qt.ItemFlag.ItemIsEnabled)
        items.append(MenuItem(combo.itemText(i), enabled, font if header else None, ink))
    return items


def section_gap(items: Sequence[MenuItem], i: int) -> float:
    """The space above a section header, as the app's menu leaves it: none atop the menu."""
    from cloudyreader.gui import tokens

    return tokens.SECTION_HEADER_GAP if items[i].header is not None and i > 0 else 0.0


def row_heights(items: Sequence[MenuItem], font: QFont) -> list[float]:
    """A choice is MENU_ROW high; a section header is as much lower as its font, plus its gap."""
    body = QFontMetricsF(font).height()
    return [
        MENU_ROW
        if item.header is None
        else MENU_ROW * QFontMetricsF(item.header).height() / body + section_gap(items, i)
        for i, item in enumerate(items)
    ]


def menu_rect(button: QRectF, items: Sequence[MenuItem], current: int, font: QFont) -> QRectF:
    """Where macOS opens a popup button's menu: the current item over the button."""
    widths = [QFontMetricsF(item.header or font).horizontalAdvance(item.text) for item in items]
    width = max(max(widths) + MENU_TEXT + MENU_TAIL, button.width() + MENU_TEXT - 9)
    heights = row_heights(items, font)
    top = button.top() - MENU_PAD - sum(heights[:current]) - (MENU_ROW - button.height()) / 2
    return QRectF(button.left() + 9 - MENU_TEXT, top, width, 2 * MENU_PAD + sum(heights))


def draw_menu(
    svg: Svg,
    look: Look,
    r: QRectF,
    items: Sequence[MenuItem],
    marks: tuple[int, int],
    font: QFont,
    bounds: QRectF,
) -> list[int]:
    """A popup menu over the content; marks = (checked item, item under the pointer).

    A menu taller than the content stops at its edge with a scroll arrow, as macOS does at a
    screen edge. Section headers are drawn as the app draws them: their own font and color, a
    gap above, never lit. Returns the indexes of the items in view.
    """
    current, hover = marks
    top, bottom = max(r.top(), bounds.top() + 4), min(r.bottom(), bounds.bottom() - 4)
    body = QRectF(r.left(), top, r.width(), bottom - top)
    blur = svg.blur(9)
    svg.rect(body.translated(0, 6), MENU_RADIUS, filter=f"url(#{blur})", **paint(look.shadow))
    edge = paint(look.menu_edge, "stroke")
    svg.rect(body, MENU_RADIUS, stroke_width=0.5, **paint(look.menu), **edge)
    first = body.top() + (MENU_ROW if top > r.top() else MENU_PAD) - 0.01
    last = body.bottom() - (MENU_ROW if bottom < r.bottom() else MENU_PAD) + 0.01
    shown, y = [], r.top() + MENU_PAD
    for i, (item, height) in enumerate(zip(items, row_heights(items, font), strict=True)):
        row, y = QRectF(r.left(), y, r.width(), height), y + height
        if row.top() < first or row.bottom() > last:
            continue
        shown.append(i)
        if item.header is not None:
            text = row.adjusted(0, section_gap(items, i), 0, 0)  # the text sits below its gap
            ink = item.ink or look.label
            base = baseline(text.top(), text.height(), item.header)
            svg.text(row.left() + MENU_TEXT, base, item.text, **font_kw(item.header), **paint(ink))
            continue
        lit = i == hover and item.enabled
        if lit:
            svg.rect(row.adjusted(5, 0, -5, 0), 5, **paint(look.accent))
        ink = QColor("#FFFFFF") if lit else (look.label if item.enabled else look.disabled)
        if i == current:
            mark = f"M{pts(row.left() + 7.5, row.center().y())}l3 3l6 -7"
            svg.path(mark, fill="none", stroke_width=1.6, **paint(ink, "stroke"), **ROUND)
        base = baseline(row.top(), row.height(), font)
        svg.text(row.left() + MENU_TEXT, base, item.text, **font_kw(font), **paint(ink))
    cx = body.center().x()
    if top > r.top():
        arrow_y = body.top() + MENU_ROW / 2
        svg.path(f"M{pts(cx - 5, arrow_y + 2.5)}l5 -5l5 5z", **paint(look.label))
    if bottom < r.bottom():
        arrow_y = body.bottom() - MENU_ROW / 2
        svg.path(f"M{pts(cx - 5, arrow_y - 2.5)}l5 5l5 -5z", **paint(look.label))
    return shown


# --- the logo ----------------------------------------------------------------------------------


def load_icon_designer() -> ModuleType:
    """scripts/make_icons.py of the app checkout: the logo reuses its exact shapes."""
    spec = importlib.util.spec_from_file_location("make_icons", ROOT / "scripts" / "make_icons.py")
    if spec is None or spec.loader is None:
        raise FileNotFoundError(ROOT / "scripts" / "make_icons.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Logo:
    """The cloud-atom app icon as vector paths, from the geometry scripts/make_icons.py draws."""

    def __init__(self) -> None:
        icons = load_icon_designer()
        self.design = next(d for d in icons.DESIGNS if d.name == "cloud-atom")
        self.canvas, self.body_rect = icons.CANVAS, icons.BODY_RECT
        self.body = icons.squircle(icons.BODY_RECT, icons.RADIUS)
        layers = self.design.layers(1.0)
        turn = icons.fit(layers, icons.SYMBOL_BOX)
        placed = [icons.Layer(turn.map(layer.path), layer.style) for layer in layers]
        self.solid = icons.union([layer.path for layer in placed if layer.style == "solid"])
        self.knocks = [layer.path for layer in placed if layer.style == "knock"]
        self.tint = icons.mix(QColor("#FFFFFF"), QColor(self.design.stops[-1]), 0.20)

    def draw(self, svg: Svg, box: QRectF) -> None:
        """The icon with its 1024 px canvas mapped onto box: body, gloss, rim, and symbol."""
        b, design = self.body_rect, self.design
        top, user = b.top(), {"gradientUnits": "userSpaceOnUse"}
        last = len(design.stops) - 1
        stops = [(i / last, QColor(stop)) for i, stop in enumerate(design.stops)]
        ends = {"x1": b.left() + 0.15 * b.width(), "y1": top, "x2": b.right() - 0.15 * b.width()}
        body_fill = svg.gradient(stops, **ends, y2=b.bottom(), **user)
        clear = rgba("#FFFFFF", 0)
        gloss_stops = [(0, rgba("#FFFFFF", 0.20)), (1, clear)]
        gloss = svg.gradient(gloss_stops, y1=top, y2=top + 0.5 * b.height(), **user)
        rim = svg.gradient(
            [(0, rgba("#FFFFFF", 0.62)), (1, clear)], y1=top, y2=top + 0.32 * b.height(), **user
        )
        bounds = self.solid.boundingRect()
        white_stops = [(0, QColor("#FFFFFF")), (1, self.tint)]
        white = svg.gradient(white_stops, y1=bounds.top(), y2=bounds.bottom(), **user)
        body_d = qpath_d(self.body)
        clip = svg.clip(f'<path d="{body_d}"/>')
        shadow, glow = svg.blur(12), svg.blur(10)
        scale = num(box.width() / self.canvas)
        svg.add(f'<g transform="translate({num(box.left())} {num(box.top())}) scale({scale})">')
        svg.path(
            body_d,
            fill="#000000",
            fill_opacity=0.42,
            transform="translate(0 14)",
            filter=f"url(#{shadow})",
        )
        svg.path(body_d, fill=f"url(#{body_fill})")
        svg.add(f'<g clip-path="url(#{clip})">')
        svg.rect(b, fill=f"url(#{gloss})")
        svg.path(body_d, fill="none", stroke=f"url(#{rim})", stroke_width=6)
        svg.add("</g>")
        solid_d, rule = qpath_d(self.solid), fill_rule(self.solid)
        svg.path(
            solid_d,
            fill=design.shade,
            fill_opacity=0.30,
            fill_rule=rule,
            transform="translate(0 16)",
            filter=f"url(#{glow})",
        )
        svg.path(solid_d, fill=f"url(#{white})", fill_rule=rule)
        for knock in self.knocks:
            svg.path(qpath_d(knock), fill=f"url(#{body_fill})", fill_rule=fill_rule(knock))
        svg.add("</g>")


# --- the figures -------------------------------------------------------------------------------


def appearance(dark: bool) -> str:
    return "Dark Mode" if dark else "Light Mode"


def fig_window(env: Env, look: Look) -> Svg:
    with env.window(duration_s=SQ1_LESSAC_S) as (win, _service):
        env.speak(win, sample_question())
        win.script_toggle.setChecked(True)
        env.pump(lambda: win.statusBar().currentMessage() == PLAYING, "playing status")
        desc = (
            f"The main window in {appearance(look.dark)}: a pasted toss-up question, the voice "
            "lessac, the Rotation row set to No rotation, the spoken script shown, and the status "
            f"{PLAYING}"
        )
        svg = Svg(win.width(), win.height(), "Cloudy Reader main window", desc)
        draw_content(svg, look, win)
    return svg


def fig_menu(env: Env, look: Look, which: str, *, top: bool = False) -> Svg:
    """A popup menu open over the window. top: the Voice menu at Heart, the first voice listed."""
    with env.window() as (win, _service):
        win.question_edit.setPlainText(sample_question())
        if top:
            win.voice_picker.select_voice(HEART)
        env.app.processEvents()
        combo = win.voice_picker.combo if which == "voices" else win.rotation_combo
        items, current = combo_items(combo), combo.currentIndex()
        if top:
            hover = current  # macOS opens the menu with the pointer on the current item
        elif which == "voices":
            hover = next(i for i, item in enumerate(items) if item.text.startswith("Heart"))
        else:
            hover = next(i for i, item in enumerate(items) if item.text == "Random shuffle")
        probe = Canvas(Svg(1, 1, "", ""), look, win, 0, 0)
        menu = menu_rect(probe.popup_bezel(combo), items, current, combo.font())
        if top:
            title = "Voice menu, top of the list"
            desc = (
                f"The Voice menu open in {appearance(look.dark)} at its top: the Kokoro heading, "
                "then the highest-graded voices, starting with Heart (female) (en-US, A), and a "
                "scroll arrow where the list goes on."
            )
        elif which == "voices":
            title = "Voice menu"
            desc = (
                f"The Voice menu open in {appearance(look.dark)}: the end of the Kokoro list, best "
                "first, names with their gender, one voice dimmed because it is not installed, "
                "then the Piper voices under their engine name, and a scroll arrow where the list "
                "goes on."
            )
        else:
            title = "Rotation menu"
            desc = (
                f"The Rotation menu open in {appearance(look.dark)}: No rotation, Round robin, "
                "Random shuffle, US only (random shuffle), Men only, and Women only."
            )
        svg = Svg(win.width(), win.height(), title, desc)
        bounds = draw_content(svg, look, win)
        shown = draw_menu(svg, look, menu, items, (current, hover), combo.font(), bounds)
        # A voice row that is dimmed (not installed, or not downloaded yet) must stay in view.
        dimmed = [i for i in shown if not items[i].enabled and items[i].header is None]
        if which == "voices" and not top and not dimmed:
            raise RuntimeError(f"{MISSING} is out of view: pick a voice higher in the menu")
    return svg


def status_strip(svg: Svg, look: Look, win: Any, y: float, caption: str | None) -> float:
    """The window's status bar as a square strip, under a caption if one is given.

    Returns the next free y. A strip figure of its own passes no caption: the page writes it.
    """
    bar = win.statusBar()
    if caption is not None:
        svg.text(0, y + 13, caption, font_size=12, font_weight=600, **paint(look.ink))
        y += 22
    r = QRectF(0, y, win.width(), bar.height())
    svg.rect(r, **paint(look.window))
    clip = svg.clip(f"<rect{rect_attrs(r)}/>")
    svg.add(f'<g clip-path="url(#{clip})">')
    origin = bar.mapTo(win, QPoint(0, 0))
    Canvas(svg, look, win, -origin.x(), y - origin.y()).widget(bar)
    svg.add("</g>")
    edge = r.adjusted(0.25, 0.25, -0.25, -0.25)
    svg.rect(edge, fill="none", stroke_width=0.5, **paint(look.window_edge, "stroke"))
    return y + bar.height() + GAP


def download_event(
    percent: int = 42, file: str = "af_bella.safetensors", files_done: int = 12
) -> Any:
    """A progress report at percent of every voice file in assets.lock.json."""
    from cloudyreader.prefetch import PrefetchProgress

    lock = json.loads((ROOT / "assets.lock.json").read_text(encoding="utf-8"))
    sizes = [a["size"] for a in lock["assets"] if a["group"] in ("voices", "kokoro")]
    total = sum(sizes)
    done = -(-total * percent // 100)  # rounded up, so the window's floored percent reads it
    return PrefetchProgress(file, done, total, files_done, len(sizes))


def download_knobs(event: Any) -> dict[str, object]:
    """A fake download that reports one event and then holds, so its widgets stay up."""
    from cloudyreader.prefetch import PrefetchResult

    return {
        "prefetch_result": PrefetchResult("complete", files=1),
        "prefetch_events": [event],
        "prefetch_gate": threading.Event(),
    }


def fig_download(env: Env, look: Look) -> Svg:
    from cloudyreader.prefetch import PrefetchResult

    svg = Svg(1, 1, "Voice download progress", "")
    y, width = 0.0, 0.0
    captions = ("Downloading voices", "Downloading voices while a reading is prepared")
    for busy, caption in zip((False, True), captions, strict=True):
        knobs = {
            "prefetch_result": PrefetchResult("complete", files=1),
            "prefetch_events": [download_event()],
            "prefetch_gate": threading.Event(),
        }
        with env.window(**knobs) as (win, service):
            env.pump(lambda w=win: not w.prefetch_label.isHidden(), "download progress")
            if busy:
                env.hold_reading(win, service)
            y = status_strip(svg, look, win, y, caption)
            width = win.width()
    svg.width, svg.height = width, y - GAP
    svg.desc = (
        f"The status bar in {appearance(look.dark)} while voices download: Downloading voices 42% "
        "with its progress bar; then the same with Preparing in the message."
    )
    return svg


def fig_states(env: Env, look: Look) -> Svg:
    from cloudyreader import prefetch, rotation
    from cloudyreader.gui.widgets import Tone

    svg = Svg(1, 1, "Status bar states", "")
    y = 0.0
    with env.window() as (win, _service):
        y = status_strip(svg, look, win, y, "Ready")
        width = win.width()
    round_robin = str(rotation.RotationMode.ROUND_ROBIN)
    with env.window(rotation=round_robin, duration_s=SQ1_HEART_S) as (win, service):
        env.hold_reading(win, service)
        y = status_strip(svg, look, win, y, "Preparing, with voice rotation on")
        service.gate.set()
        env.pump(lambda: win.statusBar().currentMessage().startswith("Playing"), "playing")
        y = status_strip(svg, look, win, y, "Playing")
    partial = prefetch.PrefetchResult(
        "partial", failed=(f"{MISSING.partition(':')[2]}.safetensors",)
    )
    with env.window(prefetch_result=partial) as (win, _service):
        env.pump(lambda: win.statusBar().tone is Tone.WARNING, "warning")
        y = status_strip(svg, look, win, y, "Warning")
    error = ValueError(f"voice {MISSING!r} is not installed")  # the pipeline's own wording
    with env.window(error=error) as (win, _service):
        win.question_edit.setPlainText(sample_question())
        win.speak_action.trigger()
        env.pump(lambda: win.statusBar().tone is Tone.ERROR, "error")
        y = status_strip(svg, look, win, y, "Error")
    svg.width, svg.height = width, y - GAP
    svg.desc = (
        f"The status bar in {appearance(look.dark)}: ready and empty; preparing with the rotated "
        "voice named; playing with that voice named; a warning that some voices could not be "
        "downloaded; and an error."
    )
    return svg


def fig_about(env: Env, look: Look, logo: Logo) -> Svg:
    with env.window() as (win, _service):
        shown: list[QMessageBox] = []
        original = QMessageBox.show

        def hidden_show(box: QMessageBox) -> None:
            box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
            shown.append(box)
            original(box)

        QMessageBox.show = hidden_show  # type: ignore[method-assign]
        try:
            win.about_action.trigger()
        finally:
            QMessageBox.show = original  # type: ignore[method-assign]
        box = shown[0]
        env.app.processEvents()
        desc = (
            f"The About panel in {appearance(look.dark)}: the app icon, the name Cloudy Reader, "
            "the version, a one-line description, and an OK button."
        )
        svg = Svg(box.width(), box.height(), "About Cloudy Reader", desc)
        svg.scale = 2  # a 251-point panel reads too small at its own size beside the text
        draw_content(svg, look, box, icon=lambda r: logo.draw(svg, r))
        box.close()
    return svg


# --- manual figures: first launch, the window tour, status strips, the Reading menu ------------

Marker = dict[str, object]


def marker(n: int, part: str, svg: Svg, x: float, y: float) -> Marker:
    """One numbered callout for the Figure component: its centre in percent of the figure."""
    return {
        "n": n,
        "part": part,
        "x": round(100 * x / svg.width, 2),
        "y": round(100 * y / svg.height, 2),
    }


def write_callouts(out: Path, name: str, markers: Sequence[Marker]) -> None:
    """The sidecar of a figure: light and dark share it, so the markers never drift."""
    path = out / f"{name}.callouts.json"
    body = {"image": name, "callouts": list(markers)}
    path.write_text(json.dumps(body, indent=4) + "\n", encoding="utf-8")  # .prettierrc: JSON uses 4
    print(f"{path.name:34} {len(markers)} callouts")


def button_rect(canvas: Canvas, b: QPushButton) -> QRectF:
    """A push button's drawn bezel, as Canvas.button draws it."""
    opt = QStyleOptionButton()
    b.initStyleOption(opt)
    item = b.style().subElementRect(QStyle.SubElement.SE_PushButtonLayoutItem, opt, b)
    return QRectF(item).translated(canvas.geo(b).topLeft())


def check_text_right(canvas: Canvas, c: QCheckBox) -> float:
    opt = QStyleOptionButton()
    c.initStyleOption(opt)
    content = c.style().subElementRect(QStyle.SubElement.SE_CheckBoxContents, opt, c)
    return (
        canvas.geo(c).left() + content.left() + QFontMetricsF(c.font()).horizontalAdvance(c.text())
    )


def fig_first_launch(env: Env, look: Look) -> Svg:
    """The first start: nothing downloaded yet, so no voice, while the download runs."""
    event = download_event(4, "en_US-lessac-medium.onnx", files_done=5)  # the 5 configs are in
    with env.window(voices=[], **download_knobs(event)) as (win, _service):
        env.pump(lambda: not win.prefetch_label.isHidden(), "download progress")
        env.pump(lambda: win.statusBar().currentMessage() == "No voice is installed.", "no voice")
        desc = (
            f"The main window in {appearance(look.dark)} at its first start: an empty question "
            "box with its hint, the Voice menu dimmed with No voice installed, Speak and Speak "
            "Clipboard dimmed, and the status No voice is installed. with a warning icon, beside "
            "Downloading voices… 4% and its progress bar."
        )
        svg = Svg(win.width(), win.height(), "Cloudy Reader at first start", desc)
        draw_content(svg, look, win)
    return svg


def fig_window_tour(env: Env, look: Look) -> tuple[Svg, list[Marker]]:
    """The main window during a reading, with markers for its eight parts."""
    from cloudyreader.gui import tokens

    with env.window(duration_s=SQ1_LESSAC_S) as (win, _service):
        env.speak(win, sample_question())
        win.script_toggle.setChecked(True)
        env.pump(lambda: win.statusBar().currentMessage() == PLAYING, "playing status")
        desc = (
            f"The main window in {appearance(look.dark)} during a reading: the question box, the "
            "Voice and Rotation menus, the two options, the Paste and Speak Clipboard buttons, "
            "the Repeat, Stop, and Speak buttons, the Spoken script, and the status bar."
        )
        svg = Svg(win.width(), win.height(), "The parts of the Cloudy Reader window", desc)
        draw_content(svg, look, win)
        c = Canvas(svg, look, win, 0, 0)
        question = c.geo(win.question_card)
        voice = c.popup_bezel(win.voice_picker.combo)
        rotation = c.popup_bezel(win.rotation_combo)
        checks = (win.read_answer_check, win.online_lookups_check)
        options_x = max(check_text_right(c, check) for check in checks) + 18
        options_y = sum(c.geo(check).center().y() for check in checks) / 2
        paste, speak = button_rect(c, win.paste_button), button_rect(c, win.speak_button)
        toggle = c.geo(win.script_toggle)
        toggle_text = QFontMetricsF(win.script_toggle.font()).horizontalAdvance(
            win.script_toggle.text()
        )
        toggle_x = toggle.left() + tokens.DISCLOSURE_SIZE + tokens.INDICATOR_SPACING + toggle_text
        bar = c.geo(win.statusBar())
        markers = [
            marker(1, "question box", svg, question.right(), question.bottom()),
            marker(2, "Voice menu", svg, voice.right() + 18, voice.center().y()),
            marker(3, "Rotation menu", svg, rotation.right() + 18, rotation.center().y()),
            marker(4, "options", svg, options_x, options_y),
            marker(5, "Paste and Speak Clipboard", svg, paste.left(), paste.top()),
            marker(6, "Repeat, Stop, and Speak", svg, speak.right(), speak.top()),
            marker(7, "Spoken script", svg, toggle_x + 18, toggle.center().y()),
            marker(8, "status bar", svg, bar.right() - 32, bar.center().y()),
        ]
    return svg, markers


def fig_strip(look: Look, win: Any, title: str, desc: str, *, band: float = 0) -> Svg:
    """The status bar alone; band leaves room above it for numbered markers."""
    svg = Svg(win.width(), band + win.statusBar().height(), title, desc)
    status_strip(svg, look, win, band, None)
    return svg


def fig_download_progress(env: Env, look: Look) -> Svg:
    with env.window(**download_knobs(download_event())) as (win, _service):
        env.pump(lambda: not win.prefetch_label.isHidden(), "download progress")
        desc = (
            f"The status bar in {appearance(look.dark)} during the voice download: Downloading "
            "voices… 42% and a progress bar."
        )
        return fig_strip(look, win, "Voice download progress", desc)


def fig_status_busy(env: Env, look: Look) -> tuple[Svg, list[Marker]]:
    """A reading prepared during the download: the three parts of a busy status bar. The window
    shows one bar at a time, so the busy bar stays hidden beside the download bar."""
    with env.window(**download_knobs(download_event())) as (win, service):
        env.pump(lambda: not win.prefetch_label.isHidden(), "download progress")
        env.hold_reading(win, service)
        desc = (
            f"The status bar in {appearance(look.dark)} while a reading is prepared during the "
            "voice download: Preparing… on the left, then Downloading voices… 42% with its "
            "progress bar on the right."
        )
        svg = fig_strip(look, win, "A busy status bar", desc, band=CALLOUT_BAND)
        bar = win.statusBar()
        origin = bar.mapTo(win, QPoint(0, 0))
        c = Canvas(svg, look, win, -origin.x(), CALLOUT_BAND - origin.y())
        _icon, text, _elided = bar.message_layout()
        message = QRectF(text).translated(c.geo(bar).topLeft())
        y = CALLOUT_BAND / 2
        markers = [
            marker(1, "message", svg, message.left() + 12, y),
            marker(2, "download label", svg, c.geo(win.prefetch_label).center().x(), y),
            marker(3, "download progress bar", svg, c.geo(win.prefetch_bar).center().x(), y),
        ]
    return svg, markers


def fig_status_warning(env: Env, look: Look) -> Svg:
    from cloudyreader.gui.widgets import Tone
    from cloudyreader.prefetch import PrefetchResult

    partial = PrefetchResult("partial", failed=(f"{MISSING.partition(':')[2]}.safetensors",))
    with env.window(prefetch_result=partial) as (win, _service):
        env.pump(lambda: win.statusBar().tone is Tone.WARNING, "warning")
        desc = (
            f"The status bar in {appearance(look.dark)} with a warning: the warning icon, then "
            "Some voices could not be downloaded. They are tried again at the next start."
        )
        return fig_strip(look, win, "A status bar warning", desc)


def fig_guide_warning(env: Env, look: Look) -> Svg:
    """The warning a malformed pronunciation guide raises, from the real normalizer."""
    with env.window() as (win, _service):
        env.speak(win, GUIDE_QUESTION)
        env.pump(lambda: win.statusBar().currentMessage().startswith("Warning:"), "guide warning")
        message = win.statusBar().currentMessage()
        desc = f"The status bar in {appearance(look.dark)} with a warning icon and: {message}"
        return fig_strip(look, win, "A pronunciation guide warning", desc)


# --- 0.0.2 engine states: Chatterbox Turbo and Qwen3-TTS (branch pause and later) -------------

QWEN_RYAN = "qwen3_tts:ryan"
LOAD_HINT = "loading Chatterbox Turbo (first use only)"


def engine_rows() -> list[Any]:
    """The GUI fake's engine rows: Chatterbox Turbo dimmed with its reason, Ryan, Aiden."""
    from cloudyreader.gui.fake_service import ENGINE_FAKE_VOICES, FAKE_VOICES

    return list(ENGINE_FAKE_VOICES[len(FAKE_VOICES) :])


def with_engine_rows(voices: Sequence[Any]) -> list[Any]:
    """The catalog with the engine rows, in the order TtsService.voices() lists them."""
    from cloudyreader.voice_meta import voice_sort_key

    return sorted([*voices, *engine_rows()], key=voice_sort_key)


def engine_catalog(env: Env) -> list[Any]:
    """Every pinned voice plus the engine rows, whether or not --engines is on."""
    folder = env.tmp / f"engines{next(env._ids)}"
    folder.mkdir()  # real_voices() makes its voices folder inside, without parents
    return with_engine_rows(real_voices(folder))


def fig_voices_engines(env: Env, look: Look) -> Svg:
    """The Voice menu open at Ryan: the engine groups between Kokoro and Piper."""
    with env.window(voices=engine_catalog(env), saved_voice=QWEN_RYAN) as (win, _service):
        win.question_edit.setPlainText(sample_question())
        env.app.processEvents()
        combo = win.voice_picker.combo
        items, current = combo_items(combo), combo.currentIndex()
        probe = Canvas(Svg(1, 1, "", ""), look, win, 0, 0)
        menu = menu_rect(probe.popup_bezel(combo), items, current, combo.font())
        desc = (
            f"The Voice menu open in {appearance(look.dark)} at Ryan (male): the end of the "
            "Kokoro list, the Chatterbox Turbo heading with its built-in voice dimmed and the "
            "reason not downloaded yet, the Qwen3-TTS heading with Ryan and Aiden, then Piper."
        )
        svg = Svg(win.width(), win.height(), "Voice menu with the engine groups", desc)
        bounds = draw_content(svg, look, win)
        draw_menu(svg, look, menu, items, (current, current), combo.font(), bounds)
    return svg


def engine_event(percent: int = 42) -> Any:
    """A report inside the Qwen3-TTS group, as the startup run sends it for an engine."""
    from cloudyreader.prefetch import PrefetchProgress

    group_total = 1_973 * 10**6
    group_done = -(-group_total * percent // 100)  # rounded up: the floored percent reads it
    return PrefetchProgress(
        "model.safetensors",
        2_100 * 10**6,
        3_050 * 10**6,
        44,
        64,
        group="qwen3_tts",
        group_done_bytes=group_done,
        group_total_bytes=group_total,
    )


def fig_download_engine(env: Env, look: Look) -> Svg:
    with env.window(**download_knobs(engine_event())) as (win, _service):
        env.pump(lambda: not win.prefetch_label.isHidden(), "engine download progress")
        desc = (
            f"The status bar in {appearance(look.dark)} while an engine downloads: "
            f"{win.prefetch_label.text()} and the group's progress bar."
        )
        return fig_strip(look, win, "Engine download progress", desc)


def fig_voice_note(env: Env, look: Look) -> Svg:
    """The saved voice is a dimmed engine row: the window falls back and says why, once."""
    catalog = [
        replace(v, installed=False, reason="not downloaded yet") if v.key == QWEN_RYAN else v
        for v in engine_catalog(env)
    ]
    with env.window(voices=catalog, saved_voice=QWEN_RYAN) as (win, _service):
        env.pump(lambda: "is not ready" in win.statusBar().currentMessage(), "saved-voice note")
        message = win.statusBar().currentMessage()
        desc = f"The status bar in {appearance(look.dark)} at start: {message}"
        return fig_strip(look, win, "Saved voice not ready", desc)


def fig_engine_skip(env: Env, look: Look) -> Svg:
    """An engine download skipped for disk space: a warning at the end of the run."""
    from cloudyreader.engine_catalog import LOW_DISK
    from cloudyreader.gui.widgets import Tone
    from cloudyreader.prefetch import PrefetchResult

    reason = f"qwen3_tts: {LOW_DISK}: needs 3.2 GB, 1.1 GB free"
    with env.window(prefetch_result=PrefetchResult("nothing", skipped=(reason,))) as (win, _):
        env.pump(lambda: win.statusBar().tone is Tone.WARNING, "skip warning")
        message = win.statusBar().currentMessage()
        desc = f"The status bar in {appearance(look.dark)} with a warning icon and: {message}"
        return fig_strip(look, win, "Engine download skipped", desc)


def fig_load_hint(env: Env, look: Look) -> Svg:
    """The first reading with an engine voice: Preparing… names the model it loads."""
    with env.window(load_hint=LOAD_HINT) as (win, service):
        env.hold_reading(win, service)
        desc = (
            f"The status bar in {appearance(look.dark)} during a first reading: "
            f"{win.statusBar().currentMessage()} with the busy bar."
        )
        return fig_strip(look, win, "First use of an engine", desc)


def crop(svg: Svg, area: QRectF) -> None:
    """Show only area of what svg draws: the viewBox moves, the drawing stays whole."""
    svg.origin = (area.left(), area.top())
    svg.width, svg.height = area.width(), area.height()


def fig_rotation_fallback(env: Env, look: Look) -> Svg:
    """Men only with no installed male voice: the reading uses the selected voice and says so."""
    from cloudyreader.rotation import RotationMode
    from cloudyreader.voice_meta import profile_of

    def not_male(voice: Any) -> bool:
        profile = profile_of(voice)
        return profile is None or profile.gender != "male"

    women = [v for v in env.voices if not_male(v)]
    with env.window(rotation=str(RotationMode.MEN_SHUFFLE), voices=women) as (win, _service):
        env.speak(win, sample_question())
        env.pump(lambda: win.statusBar().currentMessage().startswith("No installed"), "fallback")
        message = win.statusBar().currentMessage()
        desc = f"The status bar in {appearance(look.dark)} with a warning icon and: {message}"
        return fig_strip(look, win, "Rotation found no voice", desc)


def fig_script_formula(env: Env, look: Look) -> Svg:
    """The Spoken script view after SQ1: NaHCO3 reads N A H C O three."""
    with env.window(duration_s=SQ1_LESSAC_S) as (win, _service):
        env.speak(win, sample_question())
        win.script_toggle.setChecked(True)
        env.pump(lambda: win.statusBar().currentMessage() == PLAYING, "playing status")
        desc = (
            f"The Spoken script in {appearance(look.dark)} after a reading: the question as the "
            "voice says it, with NaHCO3 written as N A H C O three."
        )
        svg = Svg(win.width(), win.height(), "The spoken script", desc)
        draw_content(svg, look, win)
        c = Canvas(svg, look, win, 0, 0)
        area = c.geo(win.script_toggle).united(c.geo(win.script_panel)).adjusted(-12, -10, 12, 12)
        crop(svg, area)
    return svg


def fig_options(env: Env, look: Look) -> tuple[Svg, list[Marker]]:
    """The two options as they start: Read answer line off, Online lookups on."""
    with env.window() as (win, _service):
        desc = (
            f"The two options in {appearance(look.dark)}: Read answer line, not selected, and "
            "Online lookups, selected."
        )
        svg = Svg(win.width(), win.height(), "The options", desc)
        svg.scale = 2  # a two-row crop reads too small at its own size
        draw_content(svg, look, win)
        c = Canvas(svg, look, win, 0, 0)
        checks = (win.read_answer_check, win.online_lookups_check)
        right = max(check_text_right(c, check) for check in checks)
        label = next(w for w in win.findChildren(QLabel) if w.text() == "Options:")
        rows = c.geo(checks[0]).united(c.geo(checks[1])).united(c.geo(label))
        area = QRectF(
            rows.left() - 12, rows.top() - 4, right + 60 - rows.left(), rows.height() + 12
        )
        crop(svg, area)
        markers = [
            marker(
                n,
                check.text(),
                svg,
                check_text_right(c, check) + 18 - area.left(),
                c.geo(check).center().y() - area.top(),
            )
            for n, check in enumerate(checks, start=1)
        ]
    return svg, markers


def mac_keys(action: QAction) -> str:
    """The shortcut as a macOS menu draws it: Qt writes Return as ↵, the menu as ↩."""
    native = action.shortcuts()[0].toString(QKeySequence.SequenceFormat.NativeText)
    return native.replace("↵", "↩")


def fig_reading_menu(env: Env, look: Look) -> Svg:
    """The menu bar with the Reading menu open, drawn from the window's own actions."""
    with env.window() as (win, _service):
        env.speak(win, sample_question())  # a reading plays: all four commands are on
        actions = [win.speak_action, win.speak_clipboard_action, None, win.repeat_action]
        actions.append(win.stop_action)
        font = QFont(win.font())
        bold = QFont(font)
        bold.setBold(True)
        metrics, bold_metrics = QFontMetricsF(font), QFontMetricsF(bold)
        titles = [("Cloudy Reader", bold), ("File", font), ("Edit", font)]
        titles += [("Reading", font), ("Window", font)]
        rows = [(a.text(), mac_keys(a), a.isEnabled()) if a else None for a in actions]
        text_w = max(metrics.horizontalAdvance(r[0]) for r in rows if r)
        keys_w = max(metrics.horizontalAdvance(r[1]) for r in rows if r)
        bar_h, sep_h = 24.0, 11.0
        x, spans = 14.0, []
        for title, f in titles:
            w = (bold_metrics if f is bold else metrics).horizontalAdvance(title)
            spans.append((title, f, x, w))
            x += w + 20
        reading = next(s for s in spans if s[0] == "Reading")
        menu_w = MENU_TEXT + text_w + 36 + keys_w + 16
        menu_h = 2 * MENU_PAD + sum(MENU_ROW if r else sep_h for r in rows)
        menu = QRectF(reading[2] - 10, bar_h + 3, menu_w, menu_h)
        width, height = max(x, menu.right() + 24), menu.bottom() + 24
        desc = (
            f"The menu bar in {appearance(look.dark)} with the Reading menu open: Speak ⌘↩, "
            "Speak Clipboard ⇧⌘V, then Repeat ⌘R and Stop ⌘."
        )
        svg = Svg(width, height, "The Reading menu", desc)
        svg.rect(QRectF(0, 0, width, bar_h), **paint(look.menu))
        svg.path(
            f"M0 {num(bar_h - 0.25)}H{num(width)}",
            stroke_width=0.5,
            **paint(look.separator, "stroke"),
        )
        for title, f, left, w in spans:
            if title == "Reading":
                lit = QRectF(left - 7, 3, w + 14, bar_h - 6)
                svg.rect(lit, 5, **paint(rgba(look.label.name(), 0.12)))
            y = baseline(0, bar_h, f)
            svg.text(left, y, title, **font_kw(f), **paint(look.label))
        blur = svg.blur(9)
        svg.rect(menu.translated(0, 6), MENU_RADIUS, filter=f"url(#{blur})", **paint(look.shadow))
        edge = paint(look.menu_edge, "stroke")
        svg.rect(menu, MENU_RADIUS, stroke_width=0.5, **paint(look.menu), **edge)
        secondary = rgba(look.label.name(), 0.5)
        y = menu.top() + MENU_PAD
        for row in rows:
            if row is None:
                mid = y + sep_h / 2
                line = f"M{pts(menu.left() + 10, mid)}H{num(menu.right() - 10)}"
                svg.path(line, stroke_width=1, **paint(look.separator, "stroke"))
                y += sep_h
                continue
            text, keys, on = row
            ink = look.label if on else look.disabled
            base = baseline(y, MENU_ROW, font)
            svg.text(menu.left() + MENU_TEXT, base, text, **font_kw(font), **paint(ink))
            svg.text(
                menu.right() - 16,
                base,
                keys,
                text_anchor="end",
                **font_kw(font),
                **paint(secondary if on else look.disabled),
            )
            y += MENU_ROW
    return svg


def fig_logo(logo: Logo) -> Svg:
    desc = (
        "A rounded square with a deep blue to violet gradient and a white speech-bubble cloud "
        "with an atom: a nucleus and two electron orbits."
    )
    svg = Svg(256, 256, "Cloudy Reader app icon", desc)
    logo.draw(svg, QRectF(0, 0, 256, 256))
    return svg


@dataclass(frozen=True)
class Ink:
    """The pipeline diagram's colors for one appearance."""

    text: QColor
    soft: QColor
    paper: QColor
    local: QColor
    net: QColor
    edge: QColor
    net_edge: QColor
    arrow: QColor


def diagram_ink(dark: bool) -> Ink:
    if dark:
        return Ink(
            rgba("#FFFFFF", 0.88),
            rgba("#FFFFFF", 0.62),
            QColor("#1C1C1E"),
            QColor("#2C2C2E"),
            QColor("#10263F"),
            rgba("#FFFFFF", 0.22),
            QColor("#409CFF"),
            rgba("#FFFFFF", 0.55),
        )
    return Ink(
        QColor("#1D1D1F"),
        QColor("#3A3A3C"),
        QColor("#FFFFFF"),
        QColor("#F2F2F7"),
        QColor("#EAF3FF"),
        rgba("#000000", 0.18),
        QColor("#0A64D6"),
        rgba("#000000", 0.5),
    )


class Diagram:
    """Boxes and arrows for the pipeline figure."""

    def __init__(self, svg: Svg, ink: Ink) -> None:
        self.svg, self.ink = svg, ink
        self.head = svg.uid("arrow")
        tip = attrs(**paint(ink.arrow))
        svg.define(
            f'<marker id="{self.head}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0 0L10 5L0 10z"{tip}/></marker>'
        )

    def box(self, r: QRectF, title: str, lines: Sequence[str] = (), *, net: bool = False) -> QRectF:
        ink, svg = self.ink, self.svg
        style = {"stroke_width": 1.2, "stroke_dasharray": "5 4"} if net else {"stroke_width": 1}
        edge = paint(ink.net_edge if net else ink.edge, "stroke")
        svg.rect(r, 10, **paint(ink.net if net else ink.local), **edge, **style)
        if title:
            title_ink = ink.net_edge if net else ink.text
            svg.text(
                r.left() + 14,
                r.top() + 24,
                title,
                font_size=14,
                font_weight=600,
                **paint(title_ink),
            )
        for i, text in enumerate(lines):
            svg.text(r.left() + 14, r.top() + 44 + 17 * i, text, font_size=12, **paint(ink.soft))
        return r

    def link(
        self, start: tuple[float, float], end: tuple[float, float], *, dashed: bool = False
    ) -> None:
        self.svg.path(
            f"M{pts(*start)}L{pts(*end)}",
            fill="none",
            stroke_width=1.5,
            stroke_dasharray="4 4" if dashed else None,
            marker_end=f"url(#{self.head})",
            **paint(self.ink.arrow, "stroke"),
        )


def fig_pipeline(dark: bool) -> Svg:
    """How a pasted question becomes sound: cloudyreader/pipeline.py and the modules it calls."""
    ink = diagram_ink(dark)
    desc = (
        "A pasted question goes through the parser, entity detection, and name lookups: the "
        "lexicon and a local cache, then OPSIN on the Mac, then PubChem or UniProt over HTTPS "
        "unless offline. Then the normalizer, respelling to IPA, a Piper or Kokoro voice, the WAV "
        "cache, and the afplay player. Missing voice files download once at start over HTTPS "
        "unless offline. --offline or CLOUDYREADER_OFFLINE=1 stops the lookups and the voice "
        "download; Online lookups off stops only PubChem and UniProt. Everything else runs on the "
        "Mac."
    )
    svg = Svg(980, 540, "Cloudy Reader reading pipeline", desc)
    svg.rect(QRectF(0, 0, 980, 540), 16, **paint(ink.paper))
    d = Diagram(svg, ink)
    svg.text(32, 44, "From pasted text to sound", font_size=18, font_weight=700, **paint(ink.text))
    svg.rect(
        QRectF(640, 32, 18, 14), 4, stroke_width=1, **paint(ink.local), **paint(ink.edge, "stroke")
    )
    svg.text(664, 44, "on the Mac", font_size=12, **paint(ink.soft))
    legend = {"stroke_width": 1.2, "stroke_dasharray": "3 3"}
    svg.rect(
        QRectF(760, 32, 18, 14), 4, **paint(ink.net), **paint(ink.net_edge, "stroke"), **legend
    )
    svg.text(784, 44, "network (HTTPS)", font_size=12, **paint(ink.soft))
    q = d.box(QRectF(32, 70, 160, 78), "Question text", ["pasted, or from", "the clipboard"])
    p = d.box(QRectF(232, 70, 160, 78), "Parser", ["toss-up or bonus,", "category, choices"])
    e = d.box(
        QRectF(432, 70, 200, 78), "Entity detection", ["scispaCy CRAFT model", "plus regexes"]
    )
    lookups = ["1. lexicon, then the local", "    cache (SQLite)", "2. OPSIN (Java, on the Mac)"]
    k = d.box(QRectF(672, 70, 276, 160), "Name lookups", lookups)
    d.box(QRectF(686, 172, 248, 44), "3. PubChem or UniProt", net=True)
    n_lines = [
        "lexicon, units, formulas, choices;",
        "the answer line only when",
        "Read answer line is on",
    ]
    n = d.box(QRectF(672, 270, 276, 96), "Normalizer", n_lines)
    r = d.box(
        QRectF(432, 270, 200, 96), "Respelling to IPA", ["Bracket guides to IPA;", "Kokoro: misaki"]
    )
    v = d.box(
        QRectF(232, 270, 160, 96),
        "Voice",
        ["Piper (espeak-ng) or", "Kokoro (Apple", "Silicon only)"],
    )
    c = d.box(
        QRectF(32, 270, 160, 96), "WAV cache", ["one file per script,", "voice, speed, speaker"]
    )
    pl = d.box(QRectF(32, 400, 160, 56), "Player", ["afplay"])
    dl = d.box(
        QRectF(232, 400, 260, 56), "Voice download at start", ["missing pinned voices"], net=True
    )
    switch = [
        "--offline or CLOUDYREADER_OFFLINE=1:",
        "no name lookups and no voice download",
        "Online lookups off:",
        "no PubChem or UniProt; voices still download",
    ]
    d.box(QRectF(512, 400, 436, 112), "Offline switches", switch)
    mid = lambda box: box.center().y()  # noqa: E731
    d.link((q.right(), mid(q)), (p.left(), mid(p)))
    d.link((p.right(), mid(p)), (e.left(), mid(e)))
    d.link((e.right(), mid(e)), (k.left(), mid(e)))
    d.link((k.center().x(), k.bottom()), (n.center().x(), n.top()))
    d.link((n.left(), mid(n)), (r.right(), mid(r)))
    d.link((r.left(), mid(r)), (v.right(), mid(v)))
    d.link((v.left(), mid(v)), (c.right(), mid(c)))
    d.link((c.center().x(), c.bottom()), (pl.center().x(), pl.top()))
    d.link((dl.center().x() - 50, dl.top()), (v.center().x(), v.bottom()), dashed=True)
    return svg


def legend(svg: Svg, ink: Ink, x: float, y: float) -> None:
    """The local and network swatches of the diagrams."""
    swatch = {"stroke_width": 1, **paint(ink.local), **paint(ink.edge, "stroke")}
    svg.rect(QRectF(x, y, 18, 14), 4, **swatch)
    svg.text(x + 24, y + 12, "on the Mac", font_size=12, **paint(ink.soft))
    net = {"stroke_width": 1.2, "stroke_dasharray": "3 3"}
    svg.rect(
        QRectF(x + 120, y, 18, 14), 4, **paint(ink.net), **paint(ink.net_edge, "stroke"), **net
    )
    svg.text(x + 144, y + 12, "network (HTTPS)", font_size=12, **paint(ink.soft))


def step_number(svg: Svg, ink: Ink, box: QRectF, n: int) -> None:
    """A numbered disc at a box's left edge, for diagrams read in order."""
    cx, cy = box.left() + 24, box.top() + 19
    svg.circle(cx, cy, 11, **paint(ink.net_edge))
    svg.text(
        cx, cy + 4.5, str(n), text_anchor="middle", font_size=13, font_weight=700, fill="#FFFFFF"
    )


def numbered_box(
    d: Diagram, r: QRectF, n: int, title: str, lines: Sequence[str], *, net: bool = False
) -> QRectF:
    """A diagram box whose title follows a step number."""
    d.box(r, "", net=net)
    svg, ink = d.svg, d.ink
    step_number(svg, ink, r, n)
    title_ink = ink.net_edge if net else ink.text
    svg.text(r.left() + 44, r.top() + 24, title, font_size=14, font_weight=600, **paint(title_ink))
    for i, text in enumerate(lines):
        svg.text(r.left() + 44, r.top() + 44 + 17 * i, text, font_size=12, **paint(ink.soft))
    return r


def arrow_label(svg: Svg, ink: Ink, x: float, y: float, text: str, anchor: str = "middle") -> None:
    """A label on the paper beside an arrow."""
    svg.text(x, y, text, text_anchor=anchor, font_size=12, **paint(ink.soft))


def fig_network(dark: bool) -> Svg:
    """What leaves the Mac: one name to PubChem or UniProt, voice files from Hugging Face."""
    ink = diagram_ink(dark)
    desc = (
        "The Mac, with the question box and a voice, and three outside services: a name lookup "
        "sends one detected name to PubChem or UniProt, and the voice download requests voice "
        "files from Hugging Face. --offline or CLOUDYREADER_OFFLINE=1 stops both; Online lookups "
        "off stops only the name lookups. Everything else stays on the Mac."
    )
    width, height = 520, 458
    svg = Svg(width, height, "What uses the network", desc)
    svg.rect(QRectF(0, 0, width, height), 16, **paint(ink.paper))
    d = Diagram(svg, ink)
    svg.text(32, 44, "What uses the network", font_size=18, font_weight=700, **paint(ink.text))
    legend(svg, ink, 32, 60)
    mac = QRectF(32, 92, 456, 138)
    svg.rect(mac, 12, stroke_width=1, **paint(ink.paper), **paint(ink.edge, "stroke"))
    svg.text(46, 114, "Your Mac", font_size=14, font_weight=600, **paint(ink.text))
    question = d.box(QRectF(48, 126, 276, 84), "Question box", ["the pasted question"])
    voice = d.box(QRectF(340, 126, 132, 84), "Voice", ["Piper or Kokoro"])
    top = 300
    pubchem = d.box(QRectF(48, top, 130, 64), "PubChem", ["chemical names"], net=True)
    uniprot = d.box(QRectF(194, top, 130, 64), "UniProt", ["proteins, genes"], net=True)
    hub = d.box(QRectF(340, top, 132, 64), "Hugging Face", ["voice files"], net=True)
    for service in (pubchem, uniprot):
        x = service.center().x()
        d.link((x, question.bottom()), (x, service.top()), dashed=True)
    arrow_label(
        svg, ink, (pubchem.center().x() + uniprot.center().x()) / 2, 262, "one detected name"
    )
    d.link((hub.center().x(), hub.top()), (hub.center().x(), voice.bottom()), dashed=True)
    arrow_label(svg, ink, hub.center().x() + 8, 262, "voice files", anchor="start")
    d.box(QRectF(32, 386, 456, 52), "", [])
    note = [
        "Offline mode (--offline or CLOUDYREADER_OFFLINE=1) stops both.",
        "Online lookups off stops only the name lookups.",
    ]
    for i, text in enumerate(note):
        svg.text(46, 406 + 17 * i, text, font_size=12, **paint(ink.soft))
    return svg


def fig_stages(dark: bool) -> Svg:
    """A reading in five steps, in the reader's words; only the lookup step can use the network."""
    ink = diagram_ink(dark)
    steps = [
        ("Clean up and parse", ["find the question, its category, and its choices"], 64),
        ("Find names", ["chemicals, proteins, and genes in the text"], 64),
        ("Look up names", ["the OPSIN check runs on the Mac;"], 112),
        ("Build the spoken script", ["formulas, units, symbols, and guides become words"], 64),
        ("Speak with a local voice", ["Piper or Kokoro, on your Mac"], 64),
    ]
    desc = (
        "A vertical flow of five steps from pasted text to sound: clean up and parse, find names, "
        "look up names, build the spoken script, and speak with a local voice. In the lookup "
        "step the OPSIN check runs on the Mac; PubChem and UniProt are online and optional."
    )
    width, top, gap = 460, 92, 26
    height = top + sum(h for *_, h in steps) + gap * (len(steps) - 1) + 28
    svg = Svg(width, height, "From pasted text to sound", desc)
    svg.rect(QRectF(0, 0, width, height), 16, **paint(ink.paper))
    d = Diagram(svg, ink)
    svg.text(32, 44, "From pasted text to sound", font_size=18, font_weight=700, **paint(ink.text))
    legend(svg, ink, 32, 60)
    y, boxes = float(top), []
    for n, (title, lines, h) in enumerate(steps, start=1):
        box = numbered_box(d, QRectF(32, y, 396, h), n, title, lines)
        if n == 3:  # the online part sits inside the step: optional, and the only network use
            inner = QRectF(box.left() + 44, box.top() + 56, box.width() - 60, 40)
            d.box(inner, "", net=True)
            svg.text(
                inner.left() + 12,
                inner.top() + 25,
                "PubChem and UniProt are online and optional",
                font_size=12,
                font_weight=600,
                **paint(ink.net_edge),
            )
        boxes.append(box)
        y += h + gap
    for a, b in itertools.pairwise(boxes):
        d.link((a.center().x(), a.bottom()), (b.center().x(), b.top()))
    return svg


def fig_install_flow(dark: bool) -> Svg:
    """The first open of a downloaded copy, as four steps. Not a picture of macOS itself."""
    ink = diagram_ink(dark)
    steps = [
        ("Download the zip", ["from the Download page"]),
        ("Move Cloudy Reader to Applications", ["unzip it, then drag the app into Applications"]),
        ("Open it", ["macOS blocks the first open of this app"]),
        ("Click Open Anyway in Privacy & Security", ["System Settings > Privacy & Security"]),
    ]
    desc = (
        "Four steps of the first open: download the zip, move Cloudy Reader to Applications, "
        "open it, then click Open Anyway in System Settings > Privacy & Security."
    )
    width, top, h, gap = 460, 60, 64, 26
    height = top + len(steps) * h + (len(steps) - 1) * gap + 28
    svg = Svg(width, height, "Install and first open", desc)
    svg.rect(QRectF(0, 0, width, height), 16, **paint(ink.paper))
    d = Diagram(svg, ink)
    svg.text(32, 40, "Install and first open", font_size=18, font_weight=700, **paint(ink.text))
    boxes = [
        numbered_box(d, QRectF(32, top + i * (h + gap), 396, h), i + 1, title, lines)
        for i, (title, lines) in enumerate(steps)
    ]
    for a, b in itertools.pairwise(boxes):
        d.link((a.center().x(), a.bottom()), (b.center().x(), b.top()))
    return svg


# --- main --------------------------------------------------------------------------------------

FIGURES = (
    "logo",
    "pipeline",
    "window",
    "about",
    "voices",
    "rotation",
    "download",
    "status-states",
    "window-first-launch",
    "window-tour",
    "voices-top",
    "download-progress",
    "status-busy-download",
    "status-warning",
    "status-guide-warning",
    "menu-reading",
    "network-use",
    "reading-stages",
    "install-flow",
    "status-rotation-fallback",
    "script-formula",
    "options",
    "voices-engines",
    "download-engine",
    "status-voice-note",
    "status-engine-skip",
    "status-load-hint",
)


def write(svg: Svg, out: Path, name: str) -> None:
    path = out / f"{name}.svg"
    path.write_text(svg.xml(), encoding="utf-8")
    print(f"{path.name:34} {path.stat().st_size / 1024:6.1f} KB")


def build(out: Path, platform: str, only: Sequence[str], *, engines: bool = False) -> int:
    out.mkdir(parents=True, exist_ok=True)
    env = Env(platform, engines=engines)
    logo = Logo()
    if "logo" in only:
        write(fig_logo(logo), out, "logo")
    diagrams: dict[str, Callable[[bool], Svg]] = {
        "pipeline": fig_pipeline,
        "network-use": fig_network,
        "reading-stages": fig_stages,
        "install-flow": fig_install_flow,
    }
    for name, draw in diagrams.items():
        if name in only:
            for dark in (False, True):
                write(draw(dark), out, f"{name}-{'dark' if dark else 'light'}")
    makers: dict[str, Callable[[Look], Svg]] = {
        "window": lambda look: fig_window(env, look),
        "about": lambda look: fig_about(env, look, logo),
        "voices": lambda look: fig_menu(env, look, "voices"),
        "rotation": lambda look: fig_menu(env, look, "rotation"),
        "download": lambda look: fig_download(env, look),
        "status-states": lambda look: fig_states(env, look),
        "window-first-launch": lambda look: fig_first_launch(env, look),
        "voices-top": lambda look: fig_menu(env, look, "voices", top=True),
        "download-progress": lambda look: fig_download_progress(env, look),
        "status-warning": lambda look: fig_status_warning(env, look),
        "status-guide-warning": lambda look: fig_guide_warning(env, look),
        "menu-reading": lambda look: fig_reading_menu(env, look),
        "status-rotation-fallback": lambda look: fig_rotation_fallback(env, look),
        "script-formula": lambda look: fig_script_formula(env, look),
        "voices-engines": lambda look: fig_voices_engines(env, look),
        "download-engine": lambda look: fig_download_engine(env, look),
        "status-voice-note": lambda look: fig_voice_note(env, look),
        "status-engine-skip": lambda look: fig_engine_skip(env, look),
        "status-load-hint": lambda look: fig_load_hint(env, look),
    }
    # Figures with numbered markers: one sidecar each, from the light pass.
    marked: dict[str, Callable[[Look], tuple[Svg, list[Marker]]]] = {
        "window-tour": lambda look: fig_window_tour(env, look),
        "status-busy-download": lambda look: fig_status_busy(env, look),
        "options": lambda look: fig_options(env, look),
    }
    for dark in (False, True):
        look = env.scheme(dark)
        theme = "dark" if dark else "light"
        for name, make in makers.items():
            if name in only:
                write(make(look), out, f"{name}-{theme}")
        for name, make_marked in marked.items():
            if name in only:
                svg, markers = make_marked(look)
                write(svg, out, f"{name}-{theme}")
                if not dark:
                    write_callouts(out, name, markers)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the docs figures as vector SVG.")
    parser.add_argument("--out", type=Path, default=Path("site/public/img"), help="output folder")
    default = "cocoa" if sys.platform == "darwin" else "offscreen"
    parser.add_argument(
        "--platform",
        choices=("cocoa", "offscreen"),
        default=default,
        help=f"Qt platform for the layout (default here: {default}); windows are never shown",
    )
    parser.add_argument("--only", nargs="+", choices=FIGURES, default=list(FIGURES))
    parser.add_argument(
        "--engines",
        action="store_true",
        help="list the Chatterbox Turbo and Qwen3-TTS rows too (0.0.2); the 0.0.1 manual omits it",
    )
    args = parser.parse_args(argv)
    return build(args.out, args.platform, args.only, engines=args.engines)


if __name__ == "__main__":
    sys.exit(main())
