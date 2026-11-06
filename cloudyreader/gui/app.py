"""Application entry: build the QApplication, show the main window, run the event loop."""

from __future__ import annotations

import logging
import plistlib
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from cloudyreader.frozen import bundle_resources_dir
from cloudyreader.gui.main_window import MainWindow
from cloudyreader.gui.names import APP_NAME, ORG_NAME
from cloudyreader.models import AudioPlayer, ReaderService
from cloudyreader.start_question import pick_start_question

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _bare_name(name: object) -> str | None:
    """`name` when it is one file name; None for a path, '.' or '..': never out of its folder."""
    if not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."}:
        return None
    return name


def dev_icon_path(root: Path | None = None) -> Path | None:
    """The icon named in assets/icons/default.txt, for a source checkout. None when frozen."""
    if getattr(sys, "frozen", False):
        return None  # the bundle's AppIcon.icns applies
    icons = (PROJECT_ROOT if root is None else root) / "assets" / "icons"
    try:
        lines = (icons / "default.txt").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    name = _bare_name(next((line.strip() for line in lines if line.strip()), ""))
    if name is None:
        return None
    path = icons / name / "icon_512.png"
    return path if path.is_file() else None


def bundle_icon_path(resources: Path | None = None) -> Path | None:
    """The icon file Info.plist names (CFBundleIconFile) in a frozen .app. None elsewhere.

    The icon is cosmetic, so a malformed bundle means no icon, never a failed start.
    """
    try:
        if resources is None:
            resources = bundle_resources_dir()
            if resources is None:
                return None
        with (resources.parent / "Info.plist").open("rb") as file:
            info = plistlib.load(file)
        name = _bare_name(info.get("CFBundleIconFile") if isinstance(info, dict) else None)
        if name is None:
            return None
        path = resources / (name if Path(name).suffix else f"{name}.icns")  # the suffix is optional
        return path if path.is_file() else None
    except Exception:  # plistlib alone raises AttributeError, IndexError, ExpatError, ValueError
        log.debug("no app icon from the bundle at %s", resources, exc_info=True)
        return None


def run(
    service: ReaderService,
    player: AudioPlayer,
    argv: Sequence[str] = (),
    *,
    start_question: Callable[[], str | None] = pick_start_question,
) -> int:
    """Show the window and block until it closes. Returns the process exit code.

    `start_question` gives the text for the empty question box, or None for none.
    """
    # No setStyle and no style sheet: the platform default is the native macOS look.
    app = QApplication.instance()
    if app is None:
        app = QApplication(["cloudyreader", *argv])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)  # with the app name, QSettings derives its location
    icon_path = dev_icon_path()
    if icon_path is not None:
        # On macOS this is also the Dock icon. An unreadable file yields a null icon: no change.
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow(service, player)
    # Only the app shows a start question: a test fixture from a checkout or a dev build. A
    # release carries no fixtures, so its box starts empty.
    question = start_question()
    if question is not None:
        window.show_start_question(question)
    bundle_icon = bundle_icon_path()
    if bundle_icon is not None:
        # Only for the About box: the Dock shows the bundle icon already, and a macOS title bar
        # shows a window icon only for a document window.
        window.setWindowIcon(QIcon(str(bundle_icon)))
    window.show()
    window.raise_()  # started from a terminal, the window would open behind it
    window.activateWindow()
    code = app.exec()
    # quit() can end the loop with the window still open: close it so audio stops and no stray
    # quit stays pending (deleting a visible window after exec() would leave one behind).
    window.close()
    return code
