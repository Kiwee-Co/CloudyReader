"""Render the documentation figures in docs/assets/img as vector SVG from the live app window.

Usage, with the app's own environment so the figures show the current UI:
  uv run --frozen --offline --project <repo> python scripts/make_doc_snapshots.py --out docs/assets/img

Qt lays out the real MainWindow and About box offscreen: on macOS with the native style (the cocoa
platform, windows never shown), elsewhere on `offscreen`. The service is the GUI fake (no network,
no audio) fed the real voice catalog and the real parser and normalizer; settings go to a temp folder.
QSvgGenerator cannot capture the native macOS style, so each control is drawn here as vector shapes
from its live geometry and font. Colors come from the live palette and tokens.py, plus control fills
sampled from native renders. Popup menus are drawn from the combo box's real items.
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
from xml.sax.saxutils import escape, quoteattr

os.environ.setdefault("QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM", "1")  # no Dock icon

from PySide6.QtCore import QPoint, QRectF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QFontMetricsF,
    QIcon,
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
FONT = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', Helvetica, Arial, sans-serif"
MARGIN = 28.0  # room around a window for its shadow
TITLE_BAR = 28.0
WINDOW_RADIUS = 10.0
MENU_ROW, MENU_PAD, MENU_RADIUS, MENU_TEXT, MENU_TAIL = 22.0, 5.0, 8.0, 21.0, 24.0
LESSAC = "piper:en_US-lessac-medium"
MISSING = "kokoro:bm_daniel"  # the one voice shown as not installed
LIGHTS = (("#FF5F57", "#E0443E"), ("#FEBC2E", "#DEA123"), ("#28C840", "#1AAB29"))


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


class Svg:
    """One figure: a viewBox in points, a title and description, defs, and drawing elements."""

    def __init__(self, width: float, height: float, title: str, desc: str) -> None:
        self.width, self.height, self.title, self.desc = width, height, title, desc
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
        rx = radius or None
        self.add(
            f"<rect{attrs(x=r.x(), y=r.y(), width=r.width(), height=r.height(), rx=rx, **kw)}/>"
        )

    def path(self, d: str, **kw: object) -> None:
        self.add(f"<path{attrs(d=d, **kw)}/>")

    def circle(self, cx: float, cy: float, r: float, **kw: object) -> None:
        self.add(f"<circle{attrs(cx=cx, cy=cy, r=r, **kw)}/>")

    def text(self, x: float, y: float, value: str, **kw: object) -> None:
        self.add(f"<text{attrs(x=x, y=y, **kw)}>{escape(value)}</text>")

    def blur(self, deviation: float) -> str:
        fid = self.uid("blur")
        self.define(
            f'<filter id="{fid}" x="-30%" y="-30%" width="160%" height="160%">'
            f'<feGaussianBlur stdDeviation="{num(deviation)}"/></filter>'
        )
        return fid

    def gradient(
        self, stops: Sequence[tuple[float, QColor]], x1=0.0, y1=0.0, x2=0.0, y2=1.0, **kw
    ) -> str:
        gid = self.uid("grad")
        parts = "".join(
            f"<stop{attrs(offset=at, stop_color=c.name(), stop_opacity=c.alphaF() if c.alphaF() < 1 else None)}/>"
            for at, c in stops
        )
        self.define(
            f"<linearGradient{attrs(id=gid, x1=x1, y1=y1, x2=x2, y2=y2, **kw)}>{parts}</linearGradient>"
        )
        return gid

    def xml(self) -> str:
        w, h = num(self.width), num(self.height)
        defs = f"<defs>{''.join(self._defs)}</defs>\n" if self._defs else ""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"'
            f' role="img" aria-labelledby="title desc" font-family={quoteattr(FONT)}>\n'
            f'<title id="title">{escape(self.title)}</title>\n'
            f'<desc id="desc">{escape(self.desc)}</desc>\n'
            f"{defs}" + "\n".join(self._body) + "\n</svg>\n"
        )


def qpath_d(path: QPainterPath, digits: int = 1) -> str:
    """SVG path data for a QPainterPath (moves, lines, cubic curves)."""

    def pt(e) -> str:
        return f"{round(e.x, digits):g} {round(e.y, digits):g}"

    out, i, kinds = [], 0, QPainterPath.ElementType
    while i < path.elementCount():
        e = path.elementAt(i)
        if e.type == kinds.MoveToElement:
            out.append(f"M{pt(e)}")
            i += 1
        elif e.type == kinds.LineToElement:
            out.append(f"L{pt(e)}")
            i += 1
        else:  # CurveToElement, then two CurveToDataElement
            out.append(f"C{pt(e)} {pt(path.elementAt(i + 1))} {pt(path.elementAt(i + 2))}")
            i += 3
    return "".join(out)


# --- colors per appearance ---------------------------------------------------------------------


@dataclass(frozen=True)
class Look:
    """Colors for one appearance. Text and backgrounds come from the live palette."""

    dark: bool
    window: QColor
    label: QColor
    disabled: QColor
    base: QColor
    text: QColor
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
    ink: QColor  # captions and diagram text outside the app's own chrome


def look_for(dark: bool, palette: QPalette | None) -> Look:
    """The appearance's colors. Control fills are sampled from native renders of this window."""
    from cloudyreader.gui import tokens

    if dark:
        fallback = ("#323232", rgba("#FFFFFF", 0.85), rgba("#FFFFFF", 0.25), "#171717")
    else:
        fallback = ("#ECECEC", rgba("#000000", 0.85), rgba("#000000", 0.25), "#FFFFFF")
    window, label, disabled, base = (QColor(c) for c in fallback)
    if palette is not None:  # the platform applied this appearance: take its own colors
        active, off, role = (
            QPalette.ColorGroup.Active,
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole,
        )
        window, base = palette.color(role.Window), palette.color(role.Base)
        label, disabled = (
            palette.color(active, role.WindowText),
            palette.color(off, role.WindowText),
        )
    text = QColor(label)
    if dark:
        return Look(
            True, window, label, disabled, base, text, QColor(tokens.PLACEHOLDER_DARK),
            QColor("#101010"), QColor("#0D0D0D"), QColor("#656565"), rgba("#000000", 0.25),
            rgba("#FFFFFF", 0.14), rgba("#000000", 0.25), QColor("#4B4B4B"), QColor("#1560D2"),
            QColor("#177AE4"), QColor("#156FCF"), QColor("#1C6CDC"), QColor("#5E5E5E"),
            rgba("#000000", 0.3), QColor("#B2B2B2"), QColor("#838383"), QColor("#474747"),
            QColor("#2B2B2B"), rgba("#FFFFFF", 0.16), rgba("#FFFFFF", 0.14), rgba("#000000", 0.55),
            QColor("#FFD60A"), QColor("#FF453A"), rgba("#FFFFFF", 0.85),
        )  # fmt: skip
    return Look(
        False, window, label, disabled, base, text, QColor(tokens.PLACEHOLDER_LIGHT),
        QColor("#B6B6B6"), QColor("#8E8E8E"), QColor("#FFFFFF"), rgba("#000000", 0.13),
        rgba("#FFFFFF", 0), rgba("#000000", 0.24), QColor("#F5F5F5"), QColor("#077EFF"),
        QColor("#2690FF"), QColor("#047DFF"), QColor("#077EFF"), QColor("#FFFFFF"),
        rgba("#000000", 0.18), QColor("#ACACAC"), QColor("#838383"), QColor("#E0E0E0"),
        QColor("#F6F6F6"), rgba("#000000", 0.14), rgba("#000000", 0.2), rgba("#000000", 0.3),
        QColor("#FFCC00"), QColor("#FF3B30"), rgba("#000000", 0.85),
    )  # fmt: skip


# --- the live app ------------------------------------------------------------------------------


class Env:
    """The QApplication, a temp folder, the real voice catalog, and helpers to drive windows."""

    def __init__(self, platform: str) -> None:
        argv = ["make_doc_snapshots", "-platform", platform]
        self.app = QApplication.instance() or QApplication(argv)
        self.tmp = Path(tempfile.mkdtemp(prefix="cloudyreader-docs-"))
        # Every QSettings the app makes lands here, never in the user's preferences.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(self.tmp))
        self.app.setApplicationName("Cloudy Reader")
        self.app.setOrganizationName("CloudyReaderDocs")
        icon = ROOT / "assets" / "icons" / "cloud-atom" / "icon_512.png"
        if icon.is_file():  # what a source run shows in the About box
            self.app.setWindowIcon(QIcon(str(icon)))
        self.voices = real_voices(self.tmp)
        self._ids = itertools.count(1)

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
    def window(self, *, rotation: str | None = None, **knobs: object) -> Iterator[tuple]:
        from cloudyreader.gui.fake_service import FakeClipboard, FakePlayer
        from cloudyreader.gui.main_window import MainWindow

        settings = QSettings(
            str(self.tmp / f"window{next(self._ids)}.ini"), QSettings.Format.IniFormat
        )
        settings.setValue("voice", LESSAC)
        if rotation is not None:
            settings.setValue("voice_rotation", rotation)
        service = DocService(voices=self.voices, **knobs)
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

    def speak(self, win: QWidget, text: str) -> None:
        played: list[object] = []
        win.reading_played.connect(played.append)
        win.question_edit.setPlainText(text)
        win.speak_action.trigger()
        self.pump(lambda: bool(played), "a reading plays")


def real_voices(tmp: Path) -> list:
    """The voices the app lists once every pinned voice is in: the real names and order.

    Piper voices are scanned from stand-in files named as in assets.lock.json; Kokoro voices come
    from the engine's own table. One Kokoro voice stays not installed, as after a failed download.
    """
    from cloudyreader.engines.kokoro import RECOMMENDED_VOICES, VOICE_GRADES, KokoroEngine
    from cloudyreader.voices import scan_installed

    folder = tmp / "voices"
    folder.mkdir()
    lock = json.loads((ROOT / "assets.lock.json").read_text(encoding="utf-8"))
    for asset in lock["assets"]:
        if asset["group"] == "voices" and asset["name"].endswith(".onnx"):
            stem = asset["name"].removesuffix(".onnx")
            language, _, rest = stem.partition("-")
            config = {"language": {"code": language}, "audio": {"quality": rest.rpartition("-")[2]}}
            (folder / asset["name"]).write_bytes(b"")
            (folder / f"{asset['name']}.json").write_text(json.dumps({**config, "num_speakers": 1}))
    engine = KokoroEngine(tmp / "kokoro", all_voices=True)
    ids = [*RECOMMENDED_VOICES, *(v for v in VOICE_GRADES if v not in RECOMMENDED_VOICES)]
    kokoro = [engine._voice_info(vid) for vid in ids]  # what voices() lists on Apple Silicon
    return scan_installed(folder) + [replace(v, installed=v.key != MISSING) for v in kokoro]


def _doc_service_class() -> type:
    from cloudyreader.gui.fake_service import FakeReaderService
    from cloudyreader.lexicon import Lexicon
    from cloudyreader.normalize import ScriptNormalizer
    from cloudyreader.parser import QuestionParser

    normalizer = ScriptNormalizer(Lexicon.load())

    class _DocService(FakeReaderService):
        """The GUI fake with the real parser and normalizer, so the spoken script is genuine."""

        def prepare(self, raw, voice_key, opts):
            reading = super().prepare(raw, voice_key, opts)
            questions = QuestionParser().parse(raw)
            script = normalizer.to_script(questions, {}, opts)
            return replace(reading, questions=tuple(questions), script=script)

    return _DocService


class _LazyService:
    _cls: type | None = None

    def __call__(self, **knobs: object):
        if _LazyService._cls is None:
            _LazyService._cls = _doc_service_class()
        return _LazyService._cls(**knobs)


DocService = _LazyService()


# --- drawing the widgets -----------------------------------------------------------------------


def baseline(top: float, height: float, font: QFont) -> float:
    metrics = QFontMetricsF(font)
    return top + (height - metrics.height()) / 2 + metrics.ascent()


def font_kw(font: QFont) -> dict[str, object]:
    weight = font.weight()
    weight = weight.value if hasattr(weight, "value") else int(weight)
    return {"font_size": font.pointSizeF(), "font_weight": weight if weight != 400 else None}


class Canvas:
    """Draws one live widget tree into an Svg at an offset, as macOS controls in an active window."""

    def __init__(self, svg: Svg, look: Look, root: QWidget, dx: float, dy: float) -> None:
        self.svg, self.look, self.root, self.dx, self.dy = svg, look, root, dx, dy
        self.icon_painter: Callable[[QRectF], None] | None = None

    def geo(self, widget: QWidget) -> QRectF:
        corner = widget.mapTo(self.root, QPoint(0, 0))
        return QRectF(corner.x() + self.dx, corner.y() + self.dy, widget.width(), widget.height())

    def tree(self, parent: QWidget) -> None:
        for child in parent.children():
            if isinstance(child, QWidget) and child.isVisibleTo(self.root) and not child.isWindow():
                self.widget(child)

    def widget(self, w: QWidget) -> None:
        from cloudyreader.gui.widgets import DisclosureButton, StatusBar

        if isinstance(w, QPlainTextEdit):
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
            self.tree(w)  # its permanent widgets: download label and bar, busy bar
        else:
            self.tree(w)

    # Plain bezels: a 0.5 pt edge, a soft shadow below, an inner top shine in Dark Mode.
    def bezel(self, r: QRectF, fill: QColor, radius: float = 5.5, edge: bool = True) -> None:
        look, svg = self.look, self.svg
        svg.rect(r.translated(0, 0.6), radius, **paint(look.control_shadow))
        svg.rect(r, radius, **paint(fill))
        if edge:
            inset = r.adjusted(0.25, 0.25, -0.25, -0.25)
            svg.rect(
                inset, radius, fill="none", **paint(look.control_edge, "stroke"), stroke_width=0.5
            )
        if look.dark and edge:
            x0, x1, y = r.left() + radius, r.right() - radius, r.top() + 0.75
            svg.path(
                f"M{num(x0)} {num(y)}H{num(x1)}",
                **paint(look.control_shine, "stroke"),
                stroke_width=0.5,
            )

    def button(self, b: QPushButton) -> None:
        opt = QStyleOptionButton()
        b.initStyleOption(opt)
        item = b.style().subElementRect(QStyle.SubElement.SE_PushButtonLayoutItem, opt, b)
        r = QRectF(item).translated(self.geo(b).topLeft())
        on = b.isEnabled()
        primary = on and b.isDefault()
        fill = (
            self.look.default if primary else (self.look.control if on else self.look.control_off)
        )
        self.bezel(r, fill, edge=not primary)
        color = QColor("#FFFFFF") if primary else (self.look.label if on else self.look.disabled)
        y = baseline(r.top(), r.height(), b.font())
        self.svg.text(
            r.center().x(), y, b.text(), text_anchor="middle", **font_kw(b.font()), **paint(color)
        )

    def popup(self, c: QComboBox) -> None:
        r = self.popup_bezel(c)
        look, svg = self.look, self.svg
        self.bezel(r, look.control if c.isEnabled() else look.control_off)
        cap = QRectF(r.right() - 18.5, r.top() + 2, 15.5, r.height() - 4)
        top, bottom = (look.cap_top, look.cap_bottom) if c.isEnabled() else (look.disabled,) * 2
        gid = svg.gradient([(0, top), (1, bottom)])
        svg.rect(cap, 4, fill=f"url(#{gid})")
        cx, cy = cap.center().x(), cap.center().y()
        chevrons = f"M{num(cx - 3)} {num(cy - 1.5)}l3 -2.8l3 2.8M{num(cx - 3)} {num(cy + 1.5)}l3 2.8l3 -2.8"
        svg.path(chevrons, fill="none", stroke="#FFFFFF", stroke_width=1.5, stroke_linecap="round",
                 stroke_linejoin="round")  # fmt: skip
        text = c.currentText() or c.placeholderText()
        color = look.label if c.isEnabled() and c.currentIndex() >= 0 else look.disabled
        y = baseline(r.top(), r.height(), c.font())
        svg.text(r.left() + 9, y, text, **font_kw(c.font()), **paint(color))

    def popup_bezel(self, c: QComboBox) -> QRectF:
        """The drawn popup button inside the widget: measured on native renders of this window."""
        g = self.geo(c)
        return QRectF(g.left() + 5.5, g.top() + 4, g.width() - 12, 20.5)

    def checkbox(self, c: QCheckBox) -> None:
        opt = QStyleOptionButton()
        c.initStyleOption(opt)
        style, g = c.style(), self.geo(c)
        ind = style.subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, c)
        box = QRectF(g.left() + ind.left() + 1.5, g.top() + ind.center().y() + 0.5 - 7, 14, 14)
        look, svg = self.look, self.svg
        if c.isChecked():
            svg.rect(box, 3.5, **paint(look.accent))
            x, y = box.left(), box.top()
            check = f"M{num(x + 3.4)} {num(y + 7.4)}L{num(x + 6)} {num(y + 10)}L{num(x + 10.6)} {num(y + 4.4)}"
            svg.path(check, fill="none", stroke="#FFFFFF", stroke_width=1.9, stroke_linecap="round",
                     stroke_linejoin="round")  # fmt: skip
        else:
            svg.rect(box.translated(0, 0.5), 3.5, **paint(look.control_shadow))
            svg.rect(box, 3.5, **paint(look.box))
            svg.rect(box.adjusted(0.25, 0.25, -0.25, -0.25), 3.5, fill="none",
                     **paint(look.box_edge, "stroke"), stroke_width=0.5)  # fmt: skip
        content = style.subElementRect(QStyle.SubElement.SE_CheckBoxContents, opt, c)
        y = baseline(g.top(), g.height(), c.font())
        svg.text(g.left() + content.left(), y, c.text(), **font_kw(c.font()), **paint(look.label))

    def disclosure(self, d: QWidget) -> None:
        from cloudyreader.gui import tokens

        g, size = self.geo(d), tokens.DISCLOSURE_SIZE
        x, y = g.left(), g.top() + (g.height() - size) / 2
        if d.isChecked():
            shape = f"M{num(x + 3)} {num(y + 4.5)}L{num(x + 6.5)} {num(y + 8.5)}L{num(x + 10)} {num(y + 4.5)}"
        else:
            shape = f"M{num(x + 4.5)} {num(y + 3)}L{num(x + 8.5)} {num(y + 6.5)}L{num(x + 4.5)} {num(y + 10)}"
        self.svg.path(shape, fill="none", **paint(self.look.chevron, "stroke"), stroke_width=1.6,
                      stroke_linecap="round", stroke_linejoin="round")  # fmt: skip
        tx = x + size + tokens.INDICATOR_SPACING
        ty = baseline(g.top(), g.height(), d.font())
        self.svg.text(tx, ty, d.text(), **font_kw(d.font()), **paint(self.look.label))

    def field(self, e: QPlainTextEdit) -> None:
        look, svg, g = self.look, self.svg, self.geo(e)
        svg.rect(g.adjusted(0.5, 0.5, -0.5, -0.5), **paint(look.base), **paint(look.field_edge, "stroke"),
                 stroke_width=1)  # fmt: skip
        svg.path(f"M{num(g.left() + 1)} {num(g.top() + 0.5)}H{num(g.right() - 1)}",
                 **paint(look.field_top, "stroke"), stroke_width=1)  # fmt: skip
        view = self.geo(e.viewport())
        clip = svg.uid("clip")
        svg.define(
            f'<clipPath id="{clip}"><rect{attrs(x=view.x(), y=view.y(), width=view.width(), height=view.height())}/></clipPath>'
        )
        lines: list[str] = []
        doc = e.document()
        if doc.isEmpty():
            r = e.cursorRect(QTextCursor(doc))
            y = view.top() + r.top() + QFontMetricsF(e.font()).ascent()
            text = escape(e.placeholderText())
            lines.append(
                f"<text{attrs(x=view.left() + r.left(), y=y, **paint(look.placeholder))}>{text}</text>"
            )
        block = doc.firstBlock()
        while block.isValid() and not doc.isEmpty():
            layout = block.layout()
            for i in range(layout.lineCount()):
                line = layout.lineAt(i)
                cursor = QTextCursor(doc)
                cursor.setPosition(block.position() + line.textStart())
                r = e.cursorRect(cursor)
                chunk = block.text()[
                    line.textStart() : line.textStart() + line.textLength()
                ].rstrip()
                if chunk:
                    y = view.top() + r.top() + line.ascent()
                    lines.append(
                        f"<text{attrs(x=view.left() + r.left(), y=y)}>{escape(chunk)}</text>"
                    )
            block = block.next()
        kw = {**font_kw(e.font()), **paint(look.text)}
        svg.add(f'<g clip-path="url(#{clip})"{attrs(**kw)}>' + "".join(lines) + "</g>")

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
        if not label.text():
            return
        self.paragraph(label.text(), label.font(), r, label.alignment(), label.wordWrap())

    def paragraph(
        self, text: str, font: QFont, r: QRectF, align: Qt.AlignmentFlag, wrap: bool
    ) -> None:
        rows: list[tuple[str, float, float, float]] = []  # text, x offset, top, ascent
        top = 0.0
        for para in text.split("\n"):
            layout = QTextLayout(para, font)
            layout.beginLayout()
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(r.width() if wrap else 1e6)
                chunk = para[line.textStart() : line.textStart() + line.textLength()].rstrip()
                rows.append((chunk, line.naturalTextWidth(), top, line.ascent()))
                top += line.height()
            layout.endLayout()
        y0 = r.top()
        if align & Qt.AlignmentFlag.AlignVCenter:
            y0 += (r.height() - top) / 2
        elif align & Qt.AlignmentFlag.AlignBottom:
            y0 += r.height() - top
        anchor, x = "start", r.left()
        if align & Qt.AlignmentFlag.AlignRight:
            anchor, x = "end", r.right()
        elif align & Qt.AlignmentFlag.AlignHCenter:
            anchor, x = "middle", r.center().x()
        for chunk, _width, row_top, ascent in rows:
            self.svg.text(x, y0 + row_top + ascent, chunk, text_anchor=anchor if anchor != "start" else None,
                          **font_kw(font), **paint(self.look.label))  # fmt: skip

    def progress(self, bar: QProgressBar) -> None:
        g = self.geo(bar)
        track = QRectF(g.left(), g.center().y() - 3, g.width(), 6)
        self.svg.rect(track, 3, **paint(self.look.track))
        span = bar.maximum() - bar.minimum()
        if span > 0:  # determinate: the share done, in the accent color
            share = (bar.value() - bar.minimum()) / span
            self.svg.rect(QRectF(track.left(), track.top(), max(6.0, track.width() * share), 6), 3,
                          **paint(self.look.accent))  # fmt: skip
        else:  # indeterminate: one still frame of the moving highlight
            glow = QRectF(track.left() + track.width() * 0.18, track.top(), track.width() * 0.34, 6)
            self.svg.rect(glow, 3, **paint(self.look.accent), opacity=0.55)

    def status_bar(self, bar: QWidget) -> None:
        g, look, svg = self.geo(bar), self.look, self.svg
        svg.path(f"M{num(g.left())} {num(g.top() + 0.25)}H{num(g.right())}",
                 **paint(look.separator, "stroke"), stroke_width=0.5)  # fmt: skip
        if not bar.currentMessage():
            return
        icon, text_rect, elided = bar.message_layout()
        origin = g.topLeft()
        if icon.isValid():
            self.tone_icon(QRectF(icon).translated(origin), bar.tone.value)
        t = QRectF(text_rect).translated(origin)
        svg.text(t.left(), baseline(t.top(), t.height(), bar.font()), elided, **font_kw(bar.font()),
                 **paint(look.label))  # fmt: skip

    def tone_icon(self, r: QRectF, tone: str) -> None:
        x, y, svg = r.left(), r.top(), self.svg
        if tone == "warning":
            tri = f"M{num(x + 8)} {num(y + 2)}L{num(x + 14.6)} {num(y + 14)}H{num(x + 1.4)}Z"
            svg.path(tri, **paint(self.look.warning), stroke=self.look.warning.name(), stroke_width=2,
                     stroke_linejoin="round")  # fmt: skip
            ink = rgba("#000000", 0.85)
        else:
            svg.circle(x + 8, y + 8, 7.5, **paint(self.look.error))
            ink = QColor("#FFFFFF")
        svg.rect(QRectF(x + 7.2, y + 4.6, 1.6, 5.6), 0.8, **paint(ink))
        svg.circle(x + 8, y + 12.2, 0.95, **paint(ink))


# --- window chrome, menus, the logo ------------------------------------------------------------


def window_frame(svg: Svg, look: Look, r: QRectF, title: str, *, buttons: int = 3) -> str:
    """Shadow, body, edge and title bar of a window; returns a clip id for its content."""
    blur = svg.blur(14 if not look.dark else 18)
    svg.rect(r.translated(0, 10), WINDOW_RADIUS, **paint(look.shadow), filter=f"url(#{blur})")
    svg.rect(r, WINDOW_RADIUS, **paint(look.window))
    clip = svg.uid("win")
    svg.define(
        f'<clipPath id="{clip}"><rect{attrs(x=r.x(), y=r.y(), width=r.width(), height=r.height(), rx=WINDOW_RADIUS)}/></clipPath>'
    )
    for i, (fill, edge) in enumerate(LIGHTS):
        cx = r.left() + 20 + 20 * i
        if i < buttons:
            svg.circle(cx, r.top() + 14, 6, fill=fill, stroke=edge, stroke_width=0.5)
        else:  # dimmed, as on a panel that cannot be minimized or zoomed
            svg.circle(cx, r.top() + 14, 6, **paint(look.control_off), **paint(look.control_edge, "stroke"),
                       stroke_width=0.5)  # fmt: skip
    if title:
        svg.text(r.center().x(), r.top() + 18.5, title, text_anchor="middle", font_size=13,
                 font_weight=600, **paint(look.label))  # fmt: skip
    return clip


def window_edge(svg: Svg, look: Look, r: QRectF) -> None:
    svg.rect(r.adjusted(0.25, 0.25, -0.25, -0.25), WINDOW_RADIUS, fill="none",
             **paint(look.window_edge, "stroke"), stroke_width=0.5)  # fmt: skip


def draw_window(svg: Svg, look: Look, win: QWidget, x: float, y: float) -> Canvas:
    outer = QRectF(x, y, win.width(), TITLE_BAR + win.height())
    clip = window_frame(svg, look, outer, win.windowTitle())
    svg.add(f'<g clip-path="url(#{clip})">')
    canvas = Canvas(svg, look, win, x, y + TITLE_BAR)
    canvas.tree(win)
    svg.add("</g>")
    window_edge(svg, look, outer)
    return canvas


@dataclass(frozen=True)
class MenuItem:
    text: str
    enabled: bool


def combo_items(combo: QComboBox) -> list[MenuItem]:
    model = combo.model()
    return [
        MenuItem(
            combo.itemText(i), bool(model.flags(model.index(i, 0)) & Qt.ItemFlag.ItemIsEnabled)
        )
        for i in range(combo.count())
    ]


def menu_rect(button: QRectF, items: Sequence[MenuItem], current: int, font: QFont) -> QRectF:
    """Where macOS opens a popup button's menu: the current item lies over the button."""
    metrics = QFontMetricsF(font)
    width = max(metrics.horizontalAdvance(item.text) for item in items) + MENU_TEXT + MENU_TAIL
    width = max(width, button.width() + MENU_TEXT - 9)
    top = button.top() - MENU_PAD - current * MENU_ROW - (MENU_ROW - button.height()) / 2
    return QRectF(button.left() + 9 - MENU_TEXT, top, width, 2 * MENU_PAD + MENU_ROW * len(items))


def draw_menu(svg: Svg, look: Look, r: QRectF, items: Sequence[MenuItem], current: int,
              hover: int, font: QFont) -> None:  # fmt: skip
    blur = svg.blur(9)
    svg.rect(r.translated(0, 6), MENU_RADIUS, **paint(look.shadow), filter=f"url(#{blur})")
    svg.rect(
        r, MENU_RADIUS, **paint(look.menu), **paint(look.menu_edge, "stroke"), stroke_width=0.5
    )
    for i, item in enumerate(items):
        row = QRectF(r.left(), r.top() + MENU_PAD + i * MENU_ROW, r.width(), MENU_ROW)
        lit = i == hover and item.enabled
        if lit:
            svg.rect(row.adjusted(5, 0, -5, 0), 5, **paint(look.accent))
        ink = QColor("#FFFFFF") if lit else (look.label if item.enabled else look.disabled)
        if i == current:
            x, y = row.left() + 7.5, row.center().y()
            svg.path(f"M{num(x)} {num(y)}l3 3l6 -7", fill="none", **paint(ink, "stroke"), stroke_width=1.6,
                     stroke_linecap="round", stroke_linejoin="round")  # fmt: skip
        svg.text(row.left() + MENU_TEXT, baseline(row.top(), row.height(), font), item.text,
                 **font_kw(font), **paint(ink))  # fmt: skip


def load_icon_designer() -> ModuleType:
    """scripts/make_icons.py of the app checkout: the logo reuses its exact shapes."""
    spec = importlib.util.spec_from_file_location("make_icons", ROOT / "scripts" / "make_icons.py")
    if spec is None or spec.loader is None:
        raise FileNotFoundError("scripts/make_icons.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Logo:
    """The cloud-atom app icon as vector paths, from the same geometry as scripts/make_icons.py."""

    def __init__(self) -> None:
        icons = load_icon_designer()
        self.design = next(d for d in icons.DESIGNS if d.name == "cloud-atom")
        self.canvas, body_rect = icons.CANVAS, icons.BODY_RECT
        self.body_rect, self.body = body_rect, icons.squircle(body_rect, icons.RADIUS)
        layers = self.design.layers(1.0)
        turn = icons.fit(layers, icons.SYMBOL_BOX)
        placed = [icons.Layer(turn.map(layer.path), layer.style) for layer in layers]
        self.solid = icons.union([layer.path for layer in placed if layer.style == "solid"])
        self.knocks = [layer.path for layer in placed if layer.style == "knock"]
        self.tint = icons.mix(QColor("#FFFFFF"), QColor(self.design.stops[-1]), 0.20)

    def draw(self, svg: Svg, box: QRectF) -> None:
        """The icon scaled into box, its 1024 px canvas mapped onto the box."""
        scale = box.width() / self.canvas
        b, top = self.body_rect, self.body_rect.top()
        last = len(self.design.stops) - 1
        stops = [(i / last, QColor(stop)) for i, stop in enumerate(self.design.stops)]
        body_fill = svg.gradient(stops, b.left() + 0.15 * b.width(), b.top(), b.right() - 0.15 * b.width(),
                                 b.bottom(), gradientUnits="userSpaceOnUse")  # fmt: skip
        gloss = svg.gradient([(0, rgba("#FFFFFF", 0.20)), (1, rgba("#FFFFFF", 0))], 0, top, 0,
                             top + 0.5 * b.height(), gradientUnits="userSpaceOnUse")  # fmt: skip
        rim = svg.gradient([(0, rgba("#FFFFFF", 0.62)), (1, rgba("#FFFFFF", 0))], 0, top, 0,
                           top + 0.32 * b.height(), gradientUnits="userSpaceOnUse")  # fmt: skip
        bounds = self.solid.boundingRect()
        white = svg.gradient([(0, QColor("#FFFFFF")), (1, self.tint)], 0, bounds.top(), 0, bounds.bottom(),
                             gradientUnits="userSpaceOnUse")  # fmt: skip
        clip = svg.uid("body")
        body_d = qpath_d(self.body)
        svg.define(f'<clipPath id="{clip}"><path d="{body_d}"/></clipPath>')
        shadow, glow = svg.blur(12), svg.blur(10)
        svg.add(
            f'<g transform="translate({num(box.left())} {num(box.top())}) scale({num(scale)})">'
        )
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
        solid_d = qpath_d(self.solid)
        rule = "evenodd" if self.solid.fillRule() == Qt.FillRule.OddEvenFill else None
        svg.path(solid_d, fill=self.design.shade, fill_opacity=0.30, fill_rule=rule, transform="translate(0 16)",
                 filter=f"url(#{glow})")  # fmt: skip
        svg.path(solid_d, fill=f"url(#{white})", fill_rule=rule)
        for knock in self.knocks:
            krule = "evenodd" if knock.fillRule() == Qt.FillRule.OddEvenFill else None
            svg.path(qpath_d(knock), fill=f"url(#{body_fill})", fill_rule=krule)
        svg.add("</g>")


# --- the figures -------------------------------------------------------------------------------


def sample_question() -> str:
    """The toss-up the app's own self-test reads."""
    from cloudyreader.__main__ import SELF_TEST_PASTE

    return SELF_TEST_PASTE.strip()


def appearance(dark: bool) -> str:
    return "Dark Mode" if dark else "Light Mode"


def fig_window(env: Env, look: Look) -> Svg:
    with env.window() as (win, _service):
        env.speak(win, sample_question())
        win.script_toggle.setChecked(True)
        env.pump(lambda: win.statusBar().currentMessage() == "Playing 2.0 s.", "playing status")
        w, h = win.width() + 2 * MARGIN, win.height() + TITLE_BAR + 2 * MARGIN
        svg = Svg(w, h, "Cloudy Reader main window",
                  f"The main window in {appearance(look.dark)}: a pasted toss-up question, the voice "
                  "Lessac, the Rotation row set to No rotation, the spoken script shown, and the "
                  "status Playing 2.0 s.")  # fmt: skip
        draw_window(svg, look, win, MARGIN, MARGIN)
    return svg


def fig_menu(env: Env, look: Look, which: str) -> Svg:
    with env.window() as (win, _service):
        win.question_edit.setPlainText(sample_question())
        env.app.processEvents()
        combo = win.voice_picker.combo if which == "voices" else win.rotation_combo
        items = combo_items(combo)
        current = combo.currentIndex()
        hover = (
            next(i for i, it in enumerate(items) if it.text.startswith("Heart"))
            if which == "voices"
            else 2
        )
        probe = Canvas(Svg(1, 1, "", ""), look, win, MARGIN, MARGIN + TITLE_BAR)
        button = probe.popup_bezel(combo)
        menu = menu_rect(button, items, current, combo.font())
        shift = max(0.0, MARGIN - menu.top())  # room above a menu that opens past the window top
        bottom = max(MARGIN + TITLE_BAR + win.height(), menu.bottom()) + shift + MARGIN
        width = max(win.width() + 2 * MARGIN, menu.right() + MARGIN)
        if which == "voices":
            title = "Voice menu"
            desc = (f"The Voice menu open in {appearance(look.dark)}: Piper and Kokoro voices under their "
                    "engine names, Kokoro names with their gender, and one Kokoro voice dimmed because it "
                    "is not installed.")  # fmt: skip
        else:
            title = "Rotation menu"
            desc = (f"The Rotation menu open in {appearance(look.dark)}: No rotation, Round robin, Random "
                    "shuffle, US only (random shuffle), Men only, and Women only.")  # fmt: skip
        svg = Svg(width, bottom, title, desc)
        draw_window(svg, look, win, MARGIN, MARGIN + shift)
        draw_menu(svg, look, menu.translated(0, shift), items, current, hover, combo.font())
    return svg


def status_strip(svg: Svg, look: Look, win: QWidget, y: float, caption: str) -> float:
    """The window's status bar as a strip with a caption above it; returns the next free y."""
    bar = win.statusBar()
    svg.text(MARGIN, y + 13, caption, font_size=12, font_weight=600, **paint(look.ink))
    y += 22
    r = QRectF(MARGIN, y, win.width(), bar.height())
    blur = svg.blur(6)
    svg.rect(r.translated(0, 3), 8, **paint(look.shadow), opacity=0.5, filter=f"url(#{blur})")
    svg.rect(r, 8, **paint(look.window))
    clip = svg.uid("strip")
    svg.define(
        f'<clipPath id="{clip}"><rect{attrs(x=r.x(), y=r.y(), width=r.width(), height=r.height(), rx=8)}/></clipPath>'
    )
    svg.add(f'<g clip-path="url(#{clip})">')
    origin = bar.mapTo(win, QPoint(0, 0))
    canvas = Canvas(svg, look, win, MARGIN - origin.x(), y - origin.y())
    canvas.widget(bar)
    svg.add("</g>")
    svg.rect(r.adjusted(0.25, 0.25, -0.25, -0.25), 8, fill="none", **paint(look.window_edge, "stroke"),
             stroke_width=0.5)  # fmt: skip
    return y + bar.height() + 18


def download_event():
    from cloudyreader.prefetch import PrefetchProgress

    lock = json.loads((ROOT / "assets.lock.json").read_text(encoding="utf-8"))
    sizes = [a["size"] for a in lock["assets"] if a["group"] in ("voices", "kokoro")]
    total = sum(sizes)
    return PrefetchProgress("af_bella.safetensors", total * 42 // 100, total, 12, len(sizes))


def hold_reading(env: Env, win: QWidget, service: object) -> None:
    """Start a reading that waits in prepare(), so the busy bar shows; the window releases it."""
    service.gate = threading.Event()
    win.question_edit.setPlainText(sample_question())
    win.speak_action.trigger()
    env.pump(lambda: not win.busy_bar.isHidden(), "busy bar")


def fig_download(env: Env, look: Look) -> Svg:
    from cloudyreader.prefetch import PrefetchResult

    svg = Svg(1, 1, "", "")
    y, width = MARGIN, 0.0
    captions = ("Downloading voices", "Downloading voices while a reading is prepared")
    for busy, caption in zip((False, True), captions, strict=True):
        knobs = {"prefetch_result": PrefetchResult("complete", files=1),
                 "prefetch_events": [download_event()], "prefetch_gate": threading.Event()}  # fmt: skip
        with env.window(**knobs) as (win, service):
            env.pump(lambda w=win: not w.prefetch_label.isHidden(), "download progress")
            if busy:
                hold_reading(env, win, service)
            y = status_strip(svg, look, win, y, caption)
            width = win.width() + 2 * MARGIN
    svg.width, svg.height = width, y - 18 + MARGIN
    svg.title = "Voice download progress"
    svg.desc = (f"The status bar in {appearance(look.dark)} while voices download: Downloading voices "
                "42% with its progress bar, and the same with the busy bar beside it while a reading "
                "is prepared.")  # fmt: skip
    return svg


def fig_states(env: Env, look: Look) -> Svg:
    from cloudyreader.gui.widgets import Tone
    from cloudyreader.prefetch import PrefetchResult
    from cloudyreader.rotation import RotationMode

    svg = Svg(1, 1, "", "")
    y = MARGIN
    with env.window() as (win, _service):  # ready
        y = status_strip(svg, look, win, y, "Ready")
        width = win.width() + 2 * MARGIN
    with env.window(rotation=str(RotationMode.ROUND_ROBIN)) as (win, service):
        hold_reading(env, win, service)
        y = status_strip(svg, look, win, y, "Preparing, with voice rotation on")
        service.gate.set()
        env.pump(lambda: win.statusBar().currentMessage().startswith("Playing"), "playing")
        y = status_strip(svg, look, win, y, "Playing")
    partial = PrefetchResult("partial", failed=("bm_daniel.safetensors",))
    with env.window(prefetch_result=partial) as (win, _service):
        env.pump(lambda: win.statusBar().tone is Tone.WARNING, "warning")
        y = status_strip(svg, look, win, y, "Warning")
    with env.window(error=ValueError(f"voice {MISSING!r} is not installed")) as (win, _service):
        win.question_edit.setPlainText(sample_question())
        win.speak_action.trigger()
        env.pump(lambda: win.statusBar().tone is Tone.ERROR, "error")
        y = status_strip(svg, look, win, y, "Error")
    svg.width, svg.height = width, y - 18 + MARGIN
    svg.title = "Status bar states"
    svg.desc = (f"The status bar in {appearance(look.dark)}: ready and empty; preparing with the rotated "
                "voice named; playing with that voice named; a warning that some voices could not be "
                "downloaded; and an error.")  # fmt: skip
    return svg


def fig_about(env: Env, look: Look, logo: Logo) -> Svg:
    with env.window() as (win, _service):
        shown: list[QMessageBox] = []
        original = QMessageBox.show

        def hidden_show(box: QMessageBox) -> None:
            box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
            shown.append(box)
            original(box)

        QMessageBox.show = hidden_show
        try:
            win.about_action.trigger()
        finally:
            QMessageBox.show = original
        box = shown[0]
        env.app.processEvents()
        box.adjustSize()
        env.app.processEvents()
        w, h = box.width() + 2 * MARGIN, box.height() + TITLE_BAR + 2 * MARGIN
        svg = Svg(w, h, "About Cloudy Reader",
                  f"The About panel in {appearance(look.dark)}: the app icon, the name Cloudy Reader, "
                  "the version, a one-line description, and an OK button.")  # fmt: skip
        outer = QRectF(MARGIN, MARGIN, box.width(), TITLE_BAR + box.height())
        clip = window_frame(svg, look, outer, "", buttons=1)
        svg.add(f'<g clip-path="url(#{clip})">')
        canvas = Canvas(svg, look, box, MARGIN, MARGIN + TITLE_BAR)
        canvas.icon_painter = lambda r: logo.draw(svg, r)
        canvas.tree(box)
        svg.add("</g>")
        window_edge(svg, look, outer)
        box.close()
    return svg


def fig_logo(logo: Logo) -> Svg:
    svg = Svg(256, 256, "Cloudy Reader app icon",
              "A rounded square with a deep blue to violet gradient and a white speech-bubble cloud "
              "with an atom: a nucleus and two electron orbits.")  # fmt: skip
    logo.draw(svg, QRectF(0, 0, 256, 256))
    return svg


def fig_pipeline(dark: bool) -> Svg:
    """How a pasted question becomes sound, from cloudyreader/pipeline.py and the modules it calls."""
    ink = rgba("#FFFFFF", 0.88) if dark else rgba("#1D1D1F", 1)
    soft = rgba("#FFFFFF", 0.62) if dark else rgba("#3A3A3C", 1)
    paper = QColor("#1C1C1E") if dark else QColor("#FFFFFF")
    local_fill = QColor("#2C2C2E") if dark else QColor("#F2F2F7")
    net_fill = QColor("#10263F") if dark else QColor("#EAF3FF")
    edge = rgba("#FFFFFF", 0.22) if dark else rgba("#000000", 0.18)
    net_edge = QColor("#409CFF") if dark else QColor("#0A64D6")
    arrow = rgba("#FFFFFF", 0.55) if dark else rgba("#000000", 0.5)
    svg = Svg(980, 470, "Cloudy Reader reading pipeline",
              "A pasted question goes through the parser, entity detection, and name lookups (a local "
              "cache and OPSIN, then PubChem or UniProt over the network unless offline), the normalizer, "
              "respelling to IPA, a Piper or Kokoro voice, the WAV cache, and the afplay player. Voice "
              "files download once at start over the network unless offline. Everything else runs on "
              "the Mac.")  # fmt: skip
    svg.rect(QRectF(0, 0, 980, 470), 16, **paint(paper))
    head = svg.uid("arrow")
    svg.define(f'<marker id="{head}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
               f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"{attrs(**paint(arrow))}/></marker>')  # fmt: skip

    def box(
        x: float, y: float, w: float, h: float, title: str, lines: Sequence[str], net: bool = False
    ) -> QRectF:
        r = QRectF(x, y, w, h)
        svg.rect(r, 10, **paint(net_fill if net else local_fill), **paint(net_edge if net else edge, "stroke"),
                 stroke_width=1.2 if net else 1, stroke_dasharray="5 4" if net else None)  # fmt: skip
        svg.text(x + 14, y + 24, title, font_size=14, font_weight=600, **paint(ink))
        for i, text in enumerate(lines):
            svg.text(x + 14, y + 44 + 17 * i, text, font_size=12, **paint(soft))
        return r

    def link(x1: float, y1: float, x2: float, y2: float, dashed: bool = False) -> None:
        svg.path(f"M{num(x1)} {num(y1)}L{num(x2)} {num(y2)}", fill="none", **paint(arrow, "stroke"),
                 stroke_width=1.5, stroke_dasharray="4 4" if dashed else None, marker_end=f"url(#{head})")  # fmt: skip

    svg.text(32, 44, "From pasted text to sound", font_size=18, font_weight=700, **paint(ink))
    q = box(32, 70, 160, 78, "Question text", ["pasted or from", "the clipboard"])
    p = box(232, 70, 160, 78, "Parser", ["toss-up or bonus,", "category, choices"])
    d = box(432, 70, 200, 78, "Entity detection", ["scispaCy CRAFT model", "plus regexes"])
    lk = box(
        672,
        70,
        276,
        150,
        "Name lookups",
        ["1. lexicon skip, then the", "    cache (SQLite)", "2. OPSIN (Java, on the Mac)"],
    )
    net = box(688, 166, 244, 42, "", [], net=True)
    svg.text(net.left() + 12, net.top() + 26, "3. PubChem or UniProt (HTTPS)", font_size=12, font_weight=600,
             **paint(net_edge))  # fmt: skip
    n = box(
        672,
        264,
        276,
        96,
        "Normalizer",
        ["lexicon, units, formulas,", "answer choices, bracket", "respellings"],
    )
    r = box(432, 264, 200, 96, "Respelling to IPA", ["NSB brackets to IPA;", "Kokoro: misaki IPA"])
    t = box(232, 264, 160, 96, "Voice", ["Piper (espeak-ng)", "or Kokoro (Apple", "Silicon only)"])
    c = box(32, 264, 160, 96, "WAV cache", ["one file per script,", "voice, speed, speaker"])
    pl = box(32, 390, 160, 54, "Player", ["afplay"])
    dl = box(
        232, 390, 260, 54, "Voice download at start", ["missing pinned voices (HTTPS)"], net=True
    )
    link(q.right(), q.center().y(), p.left(), p.center().y())
    link(p.right(), p.center().y(), d.left(), d.center().y())
    link(d.right(), d.center().y(), lk.left(), d.center().y())
    link(lk.center().x(), lk.bottom(), n.center().x(), n.top())
    link(n.left(), n.center().y(), r.right(), r.center().y())
    link(r.left(), r.center().y(), t.right(), t.center().y())
    link(t.left(), t.center().y(), c.right(), c.center().y())
    link(c.center().x(), c.bottom(), pl.center().x(), pl.top())
    link(dl.center().x() - 40, dl.top(), t.center().x(), t.bottom(), dashed=True)
    sw = QRectF(512, 390, 436, 54)
    svg.rect(sw, 10, fill="none", **paint(edge, "stroke"), stroke_width=1)
    svg.text(
        sw.left() + 14, sw.top() + 22, "Offline switch", font_size=14, font_weight=600, **paint(ink)
    )
    svg.text(sw.left() + 14, sw.top() + 40, "--offline, CLOUDYREADER_OFFLINE=1, or Online lookups off: "
             "no HTTPS", font_size=12, **paint(soft))  # fmt: skip
    legend_y = 44
    svg.rect(
        QRectF(640, legend_y - 12, 18, 14),
        4,
        **paint(local_fill),
        **paint(edge, "stroke"),
        stroke_width=1,
    )
    svg.text(664, legend_y, "on the Mac", font_size=12, **paint(soft))
    svg.rect(QRectF(760, legend_y - 12, 18, 14), 4, **paint(net_fill), **paint(net_edge, "stroke"), stroke_width=1.2,
             stroke_dasharray="3 3")  # fmt: skip
    svg.text(784, legend_y, "network (HTTPS)", font_size=12, **paint(soft))
    return svg


FIGURES = ("logo", "window", "about", "voices", "rotation", "download", "status-states", "pipeline")


def write(svg: Svg, out: Path, name: str) -> None:
    path = out / f"{name}.svg"
    path.write_text(svg.xml(), encoding="utf-8")
    print(f"{path.name:24} {path.stat().st_size / 1024:6.1f} KB")


def build(out: Path, platform: str, only: Sequence[str]) -> int:
    out.mkdir(parents=True, exist_ok=True)
    env = Env(platform)
    logo = Logo()
    if "logo" in only:
        write(fig_logo(logo), out, "logo")
    if "pipeline" in only:
        write(fig_pipeline(False), out, "pipeline")
        write(fig_pipeline(True), out, "pipeline-dark")
    makers: dict[str, Callable[[Look], Svg]] = {
        "window": lambda look: fig_window(env, look),
        "about": lambda look: fig_about(env, look, logo),
        "voices": lambda look: fig_menu(env, look, "voices"),
        "rotation": lambda look: fig_menu(env, look, "rotation"),
        "download": lambda look: fig_download(env, look),
        "status-states": lambda look: fig_states(env, look),
    }
    for dark in (False, True):
        look = env.scheme(dark)
        for name, make in makers.items():
            if name in only:
                write(make(look), out, f"{name}-{'dark' if dark else 'light'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the docs figures as vector SVG.")
    parser.add_argument("--out", type=Path, default=Path("docs/assets/img"), help="output folder")
    default = "cocoa" if sys.platform == "darwin" else "offscreen"
    parser.add_argument("--platform", choices=("cocoa", "offscreen"), default=default,
                        help=f"Qt platform for layout (default here: {default}; windows are never shown)")  # fmt: skip
    parser.add_argument(
        "--only", nargs="+", choices=FIGURES, default=list(FIGURES), help="figures to render"
    )
    args = parser.parse_args(argv)
    return build(args.out, args.platform, args.only)


if __name__ == "__main__":
    sys.exit(main())
