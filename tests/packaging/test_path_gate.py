"""Packaging: the pre-zip gate that keeps the build host's own paths out of a release app."""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from tests.packaging.test_build_app import bash_fn

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_app.sh"
HOST = {"HOME": "/home/testowner", "USER": "testowner"}  # a build host the planted paths name
# A data folder on an external volume, spelled in parts: the repo bans literal disk paths.
VOLUME_DATA = "/".join(["", "Volumes", "TestDisk", "remi", ".data"])


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A throwaway repo root holding a copy of the script, like test_build_app's fake_root."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "build_app.sh")
    (tmp_path / "build").mkdir()
    return tmp_path.resolve()


def app(root: Path) -> Path:
    contents = root / "dist" / "Cloudy Reader.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "MacOS" / "Cloudy Reader").write_text("#!/bin/sh\n")
    (contents / "Resources").mkdir()
    (contents / "Resources" / "lib.py").write_text("PATH = '/usr/lib'\n")
    return contents.parent


def gate(root: Path, bundle: Path, **env: str):
    return bash_fn(root, 'path_gate "$1"', str(bundle), PY=sys.executable, **(HOST | env))


def test_the_path_gate_passes_an_app_without_host_paths(root):
    result = gate(root, app(root))

    assert result.returncode == 0, result.stderr
    assert "build_app: path gate: no build host path in the app" in result.stdout


@pytest.mark.parametrize(
    "planted",
    [
        "file:///home/testowner/remi/x.tar.gz",  # the home folder
        "testowner",  # the user name
        f"file://{VOLUME_DATA}/models/x.tar.gz",  # the data folder
        "/".join(["file://", "Volumes", "TestDisk", "elsewhere"]),  # the volume it sits on
    ],
)
def test_the_path_gate_fails_on_a_host_path_in_a_raw_file(root, planted):
    bundle = app(root)
    record = bundle / "Contents" / "Resources" / "x-1.0.dist-info" / "direct_url.json"
    record.parent.mkdir()
    record.write_text(f'{{"url": "{planted}"}}')

    result = gate(root, bundle, CLOUDYREADER_DATA_DIR=VOLUME_DATA)

    assert result.returncode == 1
    out = result.stdout + result.stderr
    assert "Contents/Resources/x-1.0.dist-info/direct_url.json: 1 hit" in out
    assert "testowner" not in out and "TestDisk" not in out  # the file and a count only


def test_the_path_gate_fails_on_this_build_trees_own_path(root):
    bundle = app(root)
    record = bundle / "Contents" / "Resources" / "cloudyreader-0.0.2.dist-info" / "direct_url.json"
    record.parent.mkdir()
    record.write_text(f'{{"url": "file://{root}", "dir_info": {{"editable": true}}}}')

    result = gate(root, bundle)

    assert result.returncode == 1
    out = result.stdout + result.stderr
    assert "Contents/Resources/cloudyreader-0.0.2.dist-info/direct_url.json: 1 hit" in out
    assert str(root) not in out


def test_the_path_gate_reads_zip_members(root):
    bundle = app(root)
    library = bundle / "Contents" / "Resources" / "base_library.zip"
    with zipfile.ZipFile(library, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("site.pyc", b"\x00/home/testowner/x\x00")

    result = gate(root, bundle)

    assert result.returncode == 1
    assert "Contents/Resources/base_library.zip!site.pyc: 1 hit" in result.stdout + result.stderr


@pytest.mark.parametrize("planted", [True, False])
def test_the_path_gate_reads_the_pyz_inside_the_executables_pkg(root, tmp_path, planted):
    writers = pytest.importorskip("PyInstaller.archive.writers")  # the CI venv has no PyInstaller
    module = tmp_path / "_sysconfigdata__darwin_darwin.py"
    prefix = "/home/testowner/.local/share/uv/python/cpython-3.12" if planted else "/install"
    module.write_text(f"build_time_vars = {{'prefix': {prefix!r}}}\n")
    code = {module.stem: compile(module.read_text(), str(module), "exec")}
    pyz = tmp_path / "PYZ.pyz"
    writers.ZlibArchiveWriter(str(pyz), [(module.stem, str(module), "PYMODULE")], code)
    bundle = app(root)
    exe = bundle / "Contents" / "MacOS" / "Cloudy Reader"
    writers.CArchiveWriter(str(exe), [("PYZ.pyz", str(pyz), False, "z")], "Python")
    assert prefix.encode() not in exe.read_bytes()  # compressed: only a decompressing scan sees it

    result = gate(root, bundle)

    out = result.stdout + result.stderr
    if planted:
        assert result.returncode == 1
        assert "Contents/MacOS/Cloudy Reader!PYZ:_sysconfigdata__darwin_darwin: 1 hit" in out
    else:
        assert result.returncode == 0, out
