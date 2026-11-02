import gc
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QApplication

from cloudyreader.gui.app import dev_icon_path, run
from cloudyreader.gui.fake_service import FakePlayer, FakeReaderService
from cloudyreader.gui.names import APP_NAME, ORG_NAME
from cloudyreader.models import Audio


@pytest.fixture(autouse=True)
def _event_loop_guard(qapp):
    """run() blocks in exec(): a failsafe quit turns a hang into a failed test.

    Afterwards leave a clean loop state for the tests that follow.
    """
    failsafe = QTimer()
    failsafe.setSingleShot(True)
    failsafe.timeout.connect(qapp.quit)
    failsafe.start(10_000)
    yield
    failsafe.stop()
    qapp.setWindowIcon(QIcon())
    gc.collect()  # destroy windows that run() left to the garbage collector
    QTimer.singleShot(0, qapp.quit)
    qapp.exec()  # exec() clears any quit a destroyed window left pending


def test_run_shows_the_window_and_returns_the_exit_code(qapp):
    seen = {}

    def probe():
        seen["titles"] = [w.windowTitle() for w in QApplication.topLevelWidgets() if w.isVisible()]
        qapp.quit()

    QTimer.singleShot(50, probe)

    code = run(FakeReaderService(), FakePlayer(), argv=())

    assert code == 0
    assert seen["titles"] == ["Cloudy Reader"]


def test_run_names_the_app_for_the_user_and_for_settings(qapp):
    qapp.setApplicationName("before")
    qapp.setApplicationDisplayName("before")
    qapp.setOrganizationName("before")
    QTimer.singleShot(0, qapp.quit)

    run(FakeReaderService(), FakePlayer())

    assert qapp.applicationName() == "Cloudy Reader"
    assert qapp.applicationDisplayName() == "Cloudy Reader"
    assert qapp.organizationName() == "CloudyReader"  # QSettings key: no space
    assert (APP_NAME, ORG_NAME) == ("Cloudy Reader", "CloudyReader")


def test_run_persists_choices_through_the_default_settings(qapp):
    def probe():
        window = next(w for w in QApplication.topLevelWidgets() if w.isVisible())

        def pick_a_voice_then_quit():
            window.voice_picker.select_voice("piper:en_US-amy-medium")
            qapp.quit()

        if window.loading_voices:  # the list loads on a worker thread
            window.voices_settled.connect(pick_a_voice_then_quit)
        else:
            pick_a_voice_then_quit()

    QTimer.singleShot(50, probe)

    run(FakeReaderService(), FakePlayer())

    assert QSettings().value("voice") == "piper:en_US-amy-medium"


def test_run_closes_the_window_and_stops_audio_when_the_loop_ends_without_closing_it(qapp):
    player = FakePlayer()
    seen = {}

    def probe():
        seen["window"] = next(w for w in QApplication.topLevelWidgets() if w.isVisible())
        player.play(Audio(Path("x.wav"), 22_050, 1.0, cache_hit=False))
        qapp.exit(0)  # unlike quit(), exit() leaves windows open

    QTimer.singleShot(50, probe)

    run(FakeReaderService(), player)

    assert not seen["window"].isVisible()
    assert player.stop_calls == 1


_CHILD = """
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import cloudyreader.gui.app as app_module
from cloudyreader.gui.fake_service import FakePlayer, FakeReaderService


def probe():
    app = QApplication.instance()
    print("RESULT", app.style().objectName(), app.applicationName())
    app.quit()


class Window(app_module.MainWindow):
    def __init__(self, *args, **kwargs):  # runs once the QApplication exists
        super().__init__(*args, **kwargs)
        QTimer.singleShot(50, probe)


app_module.MainWindow = Window
sys.exit(app_module.run(FakeReaderService(), FakePlayer(), argv=sys.argv[1:]))
"""


def test_run_creates_the_app_and_forwards_argv_to_qt():
    # A fresh process: inside pytest a QApplication already exists, so run() would reuse it.
    done = subprocess.run(
        [sys.executable, "-c", _CHILD, "-style", "windows"],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert done.returncode == 0, done.stderr
    assert "RESULT windows Cloudy Reader" in done.stdout


# --- dev-mode icon ---------------------------------------------------------------------------


def make_icon_tree(root: Path, name: str = "cloud") -> Path:
    icons = root / "assets" / "icons"
    (icons / name).mkdir(parents=True)
    (icons / "default.txt").write_text(f"{name}\n")
    png = icons / name / "icon_512.png"
    image = QImage(16, 16, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(png))
    return png


def run_once(qapp):
    QTimer.singleShot(0, qapp.quit)
    run(FakeReaderService(), FakePlayer())


def test_dev_icon_path_finds_the_default_icon(qapp, tmp_path):
    png = make_icon_tree(tmp_path)

    assert dev_icon_path(tmp_path) == png


def test_dev_icon_path_is_none_without_assets(tmp_path):
    assert dev_icon_path(tmp_path) is None


def test_dev_icon_path_is_none_when_the_named_icon_is_missing(qapp, tmp_path):
    make_icon_tree(tmp_path).unlink()

    assert dev_icon_path(tmp_path) is None


def test_dev_icon_path_skips_blank_lines_and_trims_the_name(qapp, tmp_path):
    png = make_icon_tree(tmp_path)
    (tmp_path / "assets/icons/default.txt").write_text("\n  cloud  \nother\n")

    assert dev_icon_path(tmp_path) == png


@pytest.mark.parametrize(
    ("default_txt", "planted"),
    [
        ("", None),
        ("\n\n", None),
        # Each escaping name gets a real icon at its target, so only the name check can refuse it.
        ("..", "assets/icons/../icon_512.png"),
        ("../outside", "assets/outside/icon_512.png"),
        ("ABSOLUTE", "elsewhere/icon_512.png"),
    ],
)
def test_dev_icon_path_rejects_an_empty_or_escaping_default_name(
    qapp, tmp_path, default_txt, planted
):
    png = make_icon_tree(tmp_path)
    if planted is not None:
        target = tmp_path / planted
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(png, target)
    if default_txt == "ABSOLUTE":
        default_txt = str(tmp_path / "elsewhere")
    (tmp_path / "assets/icons/default.txt").write_text(default_txt)

    assert dev_icon_path(tmp_path) is None


def test_dev_icon_path_is_none_when_frozen(qapp, tmp_path, monkeypatch):
    make_icon_tree(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)  # the bundle's AppIcon.icns applies

    assert dev_icon_path(tmp_path) is None


def test_run_sets_the_dev_icon(qapp, tmp_path, monkeypatch):
    make_icon_tree(tmp_path)
    monkeypatch.setattr("cloudyreader.gui.app.PROJECT_ROOT", tmp_path)

    run_once(qapp)

    assert not qapp.windowIcon().isNull()


def test_run_sets_no_icon_when_frozen(qapp, tmp_path, monkeypatch):
    make_icon_tree(tmp_path)
    monkeypatch.setattr("cloudyreader.gui.app.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    run_once(qapp)

    assert qapp.windowIcon().isNull()


def test_run_ignores_a_missing_icon_silently(qapp, tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("cloudyreader.gui.app.PROJECT_ROOT", tmp_path)

    run_once(qapp)

    assert qapp.windowIcon().isNull()
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_run_ignores_an_unreadable_icon(qapp, tmp_path, monkeypatch):
    make_icon_tree(tmp_path).write_bytes(b"not a png")
    monkeypatch.setattr("cloudyreader.gui.app.PROJECT_ROOT", tmp_path)

    run_once(qapp)

    assert qapp.windowIcon().isNull()
