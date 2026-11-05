"""The app icon in a frozen .app: the Dock shows the bundle icon, the About box reuses it."""

import gc
import logging
import plistlib
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QApplication

import cloudyreader.gui.app as app_module
from cloudyreader.gui.app import bundle_icon_path, run
from cloudyreader.gui.fake_service import FakePlayer, FakeReaderService
from cloudyreader.gui.main_window import MainWindow


@pytest.fixture(autouse=True)
def _event_loop_guard(qapp):
    """run() blocks in exec(): a failsafe quit turns a hang into a failed test."""
    failsafe = QTimer()
    failsafe.setSingleShot(True)
    failsafe.timeout.connect(qapp.quit)
    failsafe.start(10_000)
    yield
    failsafe.stop()
    qapp.setWindowIcon(QIcon())
    gc.collect()
    QTimer.singleShot(0, qapp.quit)
    qapp.exec()


def make_bundle(root: Path, icon_file: object = "AppIcon.icns", *, write_icon: bool = True) -> Path:
    """A fake Contents/ with Info.plist and Resources/; returns the Resources folder."""
    resources = root / "Cloudy Reader.app" / "Contents" / "Resources"
    resources.mkdir(parents=True)
    info = {"CFBundleName": "Cloudy Reader"}
    if icon_file is not None:
        info["CFBundleIconFile"] = icon_file
    (resources.parent / "Info.plist").write_bytes(plistlib.dumps(info))
    if write_icon:
        image = QImage(64, 64, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.blue)
        assert image.save(str(resources / "AppIcon.icns"), "ICNS")
    return resources


def test_bundle_icon_is_the_file_info_plist_names(qapp, tmp_path):
    resources = make_bundle(tmp_path)

    assert bundle_icon_path(resources) == resources / "AppIcon.icns"


def test_bundle_icon_name_without_an_extension_means_icns(qapp, tmp_path):
    resources = make_bundle(tmp_path, "AppIcon")

    assert bundle_icon_path(resources) == resources / "AppIcon.icns"


@pytest.mark.parametrize("icon_file", [None, "", "..", 42, "Missing.icns"])
def test_bundle_icon_is_none_for_a_missing_or_unusable_name(qapp, tmp_path, icon_file):
    resources = make_bundle(tmp_path, icon_file)

    assert bundle_icon_path(resources) is None


def test_bundle_icon_name_must_not_leave_resources(qapp, tmp_path):
    resources = make_bundle(tmp_path, "../AppIcon.icns")
    (resources.parent / "AppIcon.icns").write_bytes((resources / "AppIcon.icns").read_bytes())

    assert bundle_icon_path(resources) is None


def test_bundle_icon_is_none_without_an_info_plist(tmp_path):
    assert bundle_icon_path(tmp_path) is None


@pytest.mark.parametrize("content", [b"<plist><dict><key>broken", b"\x00\x01garbage", b"<plist/>"])
def test_bundle_icon_is_none_for_an_unreadable_info_plist(qapp, tmp_path, content):
    resources = make_bundle(tmp_path)
    (resources.parent / "Info.plist").write_bytes(content)

    assert bundle_icon_path(resources) is None


def test_bundle_icon_is_none_for_a_plist_that_is_not_a_dictionary(qapp, tmp_path):
    resources = make_bundle(tmp_path)
    (resources.parent / "Info.plist").write_bytes(plistlib.dumps(["AppIcon.icns"]))

    assert bundle_icon_path(resources) is None


def test_bundle_icon_is_none_outside_a_frozen_app(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert bundle_icon_path() is None


@pytest.mark.parametrize(
    "info_plist",
    [
        b"<plist><date>x</date></plist>",  # plistlib raised AttributeError
        b"<plist><key>x</key></plist>",  # plistlib raised IndexError
        plistlib.dumps({"CFBundleIconFile": "A" * 300 + ".icns"}),  # is_file(): ENAMETOOLONG
    ],
)
def test_a_malformed_bundle_means_no_icon_and_a_debug_note(qapp, tmp_path, caplog, info_plist):
    resources = make_bundle(tmp_path)
    (resources.parent / "Info.plist").write_bytes(info_plist)

    with caplog.at_level(logging.DEBUG, logger=app_module.__name__):
        assert bundle_icon_path(resources) is None

    assert [r.levelno for r in caplog.records if r.name == app_module.__name__] == [logging.DEBUG]


def test_a_failing_bundle_lookup_means_no_icon(monkeypatch):
    def broken():
        raise OSError("bundle moved")

    monkeypatch.setattr(app_module, "bundle_resources_dir", broken)

    assert bundle_icon_path() is None


def window_icon_states(qapp) -> dict[str, bool]:
    """Run the app once; report whether the window and the app carry an icon."""
    seen = {}

    def probe():
        window = next(
            w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow) and w.isVisible()
        )
        seen["window"] = not window.windowIcon().isNull()
        seen["app"] = not qapp.windowIcon().isNull()
        qapp.quit()

    QTimer.singleShot(0, probe)
    run(FakeReaderService(), FakePlayer())
    return seen


def test_frozen_run_gives_the_bundle_icon_to_the_window_not_the_dock(qapp, tmp_path, monkeypatch):
    resources = make_bundle(tmp_path / "bundle")
    monkeypatch.setattr(app_module, "PROJECT_ROOT", tmp_path)  # no dev icon here
    monkeypatch.setattr(app_module, "bundle_resources_dir", lambda: resources)

    assert window_icon_states(qapp) == {"window": True, "app": False}


def test_frozen_run_still_starts_when_the_icon_lookup_fails(qapp, tmp_path, monkeypatch):
    resources = make_bundle(tmp_path / "bundle")
    (resources.parent / "Info.plist").write_bytes(b"<plist><key>x</key></plist>")
    monkeypatch.setattr(app_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(app_module, "bundle_resources_dir", lambda: resources)

    assert window_icon_states(qapp) == {"window": False, "app": False}  # shown, just no icon


def test_source_run_sets_no_window_icon_of_its_own(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "PROJECT_ROOT", tmp_path)

    assert window_icon_states(qapp) == {"window": False, "app": False}
