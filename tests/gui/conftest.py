import os

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QStyleFactory

from cloudyreader.gui.fake_service import FakePlayer, FakeReaderService

# Forced, not defaulted: a GUI test must never open a real window.
# Qt reads it when the QApplication starts, so setting it after the imports is early enough.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
GATES = ("gate", "voices_gate", "prefetch_gate", "preview_gate")  # the fake's holds, by knob


def open_gates(service) -> None:
    """Release every job the fake still holds: a closing window waits for its worker."""
    for name in GATES:
        gate = getattr(service, name, None)
        if gate is not None:
            gate.set()


@pytest.fixture(autouse=True)
def _isolated_default_settings(tmp_path_factory):
    """Point the default QSettings scope at a temp dir so no test can write the user's prefs."""
    path = str(tmp_path_factory.mktemp("qsettings"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, path)


@pytest.fixture(autouse=True)
def _motion_as_usual(monkeypatch):
    """Reduce Motion off, whatever this Mac says, so the busy bar shows where tests expect it."""
    monkeypatch.setattr("cloudyreader.gui.main_window.reduce_motion", lambda: False)


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "gui.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def service():
    return FakeReaderService()


@pytest.fixture
def player():
    return FakePlayer()


@pytest.fixture
def make_window(qtbot, service, player, settings):
    """Build a shown MainWindow; override any collaborator by keyword."""

    def build(
        *,
        service=service,
        player=player,
        settings=settings,
        rotator=None,
        wait_for_voices=True,
    ):
        from cloudyreader.gui.main_window import MainWindow

        win = MainWindow(service, player, settings=settings, rotator=rotator)
        # pytest-qt closes the window before any finalizer runs: open the gates first.
        qtbot.addWidget(win, before_close_func=lambda _win: open_gates(service))
        win.show()
        if wait_for_voices:  # the list loads on a worker thread
            qtbot.waitUntil(lambda: not win.loading_voices, timeout=5000)
        return win

    return build


@pytest.fixture
def window(make_window):
    return make_window()


@pytest.fixture
def mac_style(qapp):
    """The style the app runs with on macOS, for the duration of one test: its layout margins
    and metrics are what the window must fit and align with."""
    native = QStyleFactory.create("macOS")
    if native is None:
        pytest.skip("the macOS style exists only on macOS")
    default = qapp.style().name()
    try:
        QApplication.setStyle(native)
        yield native
    finally:  # the next test gets the default style back, even after a failed setup
        QApplication.setStyle(QStyleFactory.create(default))
