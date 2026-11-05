"""Packaging: scripts/build_app.sh signs ad hoc only and stops when the bundle lacks its icon."""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.packaging.test_build_app import bash_fn

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_app.sh"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A throwaway repo root holding a copy of the script, like test_build_app's fake_root."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "build_app.sh")
    (tmp_path / "build").mkdir()
    return tmp_path.resolve()


# --- signing --------------------------------------------------------------------------------------


def test_sign_bundle_signs_ad_hoc_and_nothing_more(root: Path) -> None:
    bin_dir, args = root / "bin", root / "codesign.args"
    bin_dir.mkdir()
    (bin_dir / "codesign").write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" >"{args}"\n')
    (bin_dir / "codesign").chmod(0o755)
    app = root / "build" / "dist" / "Cloudy Reader.app"

    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    result = bash_fn(root, 'STAGE_APP="$1" && sign_bundle', str(app), PATH=path)

    assert result.returncode == 0, result.stderr
    assert args.read_text().splitlines() == ["--force", "--deep", "-s", "-", str(app)]


def test_script_never_uses_a_certificate_or_notarizes() -> None:
    code = [line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#")]
    signing = [line for line in code if re.search(r"\bcodesign\b.*\s(-s|--sign)\s", line)]

    assert signing and all(" -s - " in line for line in signing)
    assert not [line for line in code if re.search(r"notarytool|altool|stapler|--options", line)]


# --- check_bundle ---------------------------------------------------------------------------------


def stage(root: Path, icon: bytes = b"voice", **keys: str | None) -> Path:
    """A staged bundle whose Info.plist holds the keys check_bundle reads (None drops one)."""
    app = root / "build" / "dist" / "Cloudy Reader.app"
    (app / "Contents" / "Resources").mkdir(parents=True)
    plist = {
        "CFBundleIconFile": "AppIcon.icns",
        "CFBundleShortVersionString": "0.0.1",
        "LSMinimumSystemVersion": "26.0",
    } | keys
    plist = {k: v for k, v in plist.items() if v is not None}
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(plist))
    (app / "Contents" / "Resources" / "AppIcon.icns").write_bytes(icon)
    return app


def chosen_icon(root: Path) -> Path:
    icon = root / "assets" / "icons" / "cloud-voice" / "AppIcon.icns"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"voice")
    return icon


def check_bundle(root: Path, app: Path, icon: Path | str) -> subprocess.CompletedProcess[str]:
    return bash_fn(root, 'STAGE_APP="$1" ICON_PATH="$2" && check_bundle', str(app), str(icon))


def test_check_bundle_reports_version_macos_and_icon(root: Path) -> None:
    result = check_bundle(root, stage(root), chosen_icon(root))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == (
        "build_app: Info.plist: version 0.0.1, macOS 26.0 or later, icon AppIcon.icns"
    )


def test_check_bundle_fails_without_the_icon_file(root: Path) -> None:
    app = stage(root)
    (app / "Contents" / "Resources" / "AppIcon.icns").unlink()

    result = check_bundle(root, app, chosen_icon(root))

    assert result.returncode == 1
    assert "not in Contents/Resources: AppIcon.icns" in result.stderr


def test_check_bundle_fails_when_the_icon_is_not_the_chosen_one(root: Path) -> None:
    result = check_bundle(root, stage(root, icon=b"generic"), chosen_icon(root))

    assert result.returncode == 1
    assert "differs from" in result.stderr


def test_check_bundle_fails_when_no_icon_is_named(root: Path) -> None:
    result = check_bundle(root, stage(root, CFBundleIconFile=None), chosen_icon(root))

    assert result.returncode == 1
    assert "names no CFBundleIconFile" in result.stderr


def test_check_bundle_fails_on_an_invalid_plist(root: Path) -> None:
    app = stage(root)
    (app / "Contents" / "Info.plist").write_text("<plist><dict><key>broken")

    result = check_bundle(root, app, chosen_icon(root))

    assert result.returncode == 1
    assert "invalid" in result.stderr


def test_check_bundle_takes_pyinstallers_icon_when_none_was_chosen(root: Path) -> None:
    app = stage(root, CFBundleIconFile="icon-windowed.icns")
    (app / "Contents" / "Resources" / "icon-windowed.icns").write_bytes(b"generic")

    assert check_bundle(root, app, "").returncode == 0
