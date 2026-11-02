"""Application entry: build the QApplication, show the main window, run the event loop."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from cloudyreader.gui.main_window import MainWindow
from cloudyreader.gui.names import APP_NAME, ORG_NAME
from cloudyreader.models import AudioPlayer, ReaderService

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def dev_icon_path(root: Path | None = None) -> Path | None:
    """The icon named in assets/icons/default.txt, for a source checkout. None when frozen."""
    if getattr(sys, "frozen", False):
        return None  # the bundle's AppIcon.icns applies
    icons = (PROJECT_ROOT if root is None else root) / "assets" / "icons"
    try:
        lines = (icons / "default.txt").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    name = next((line.strip() for line in lines if line.strip()), "")
    if not name or Path(name).name != name or name in {".", ".."}:
        return None  # a bare directory name only: never a path out of assets/icons
    path = icons / name / "icon_512.png"
    return path if path.is_file() else None


def run(service: ReaderService, player: AudioPlayer, argv: Sequence[str] = ()) -> int:
    """Show the window and block until it closes. Returns the process exit code."""
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
    window.show()
    window.raise_()  # started from a terminal, the window would open behind it
    window.activateWindow()
    code = app.exec()
    # quit() can end the loop with the window still open: close it so audio stops and no stray
    # quit stays pending (deleting a visible window after exec() would leave one behind).
    window.close()
    return code
