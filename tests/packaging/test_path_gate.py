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
COOKIE = b"MEI\x0c\x0b\x0a\x0b\x0e"  # PyInstaller's CArchive cookie
# A clean PYZ: one module and a namespace package, which holds no data by design.
CLEAN = {"_sysconfigdata__darwin_darwin": "build_time_vars = {'prefix': '/install'}\n", "ns": None}
UNCOVERED = "read no PYZ module in the PKG of Contents/MacOS/Cloudy Reader"
NOT_PROVEN = "the path gate cannot prove the app clean"


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


def frozen(bundle: Path, src: Path, modules: dict | None, hooks: dict | None = None) -> Path:
    """Makes the app's executable a PyInstaller one: a PKG holding a PYZ of modules (name to
    source, None for a namespace package; no PYZ when modules is None) and compressed hooks."""
    writers = pytest.importorskip("PyInstaller.archive.writers")  # the CI venv has no PyInstaller
    entries = []
    if modules is not None:
        listed, code = [], {}
        for name, text in modules.items():
            if text is None:
                listed.append((name, "-", "PYMODULE"))
                continue
            (src / f"{name}.py").write_text(text)
            listed.append((name, str(src / f"{name}.py"), "PYMODULE"))
            code[name] = compile(text, f"{name}.py", "exec")
        writers.ZlibArchiveWriter(str(src / "PYZ.pyz"), listed, code)
        entries.append(("PYZ.pyz", str(src / "PYZ.pyz"), False, "z"))
    for name, text in (hooks or {}).items():
        (src / f"{name}.py").write_text(text)
        entries.append((name, str(src / f"{name}.py"), True, "s"))
    exe = bundle / "Contents" / "MacOS" / "Cloudy Reader"
    writers.CArchiveWriter(str(exe), entries, "Python")
    return exe


def gate(root: Path, bundle: Path, **env: str):
    return bash_fn(root, 'path_gate "$1"', str(bundle), **({"PY": sys.executable} | HOST | env))


def test_the_path_gate_passes_a_frozen_app_without_host_paths(root, tmp_path):
    bundle = app(root)
    frozen(bundle, tmp_path, CLEAN, hooks={"pyi_rth_clean": "P = '/opt/remi'\n"})

    result = gate(root, bundle)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "path gate: no build host path in the app (1 PYZ module(s) read)" in result.stdout


def test_the_path_gate_fails_an_app_whose_executable_has_no_pkg(root):
    result = gate(root, app(root))  # a shell script: no PKG, so no PYZ module was read

    assert result.returncode == 1
    assert UNCOVERED in result.stdout
    assert NOT_PROVEN in result.stderr


@pytest.mark.parametrize("archive", ["unknown-cookie", "no-pyz", "empty-pyz"])
def test_the_path_gate_fails_when_the_pkg_gives_no_pyz_module(root, tmp_path, archive):
    bundle = app(root)
    leaky = {"_sysconfigdata__darwin_darwin": "build_time_vars = {'prefix': '/home/testowner'}\n"}
    modules = {"unknown-cookie": leaky, "no-pyz": None, "empty-pyz": {}}[archive]
    exe = frozen(bundle, tmp_path, modules, hooks={"pyi_rth_clean": "P = '/opt/remi'\n"})
    if archive == "unknown-cookie":  # rel-sec's M13: one changed cookie byte hid a leaky PYZ
        exe.write_bytes(exe.read_bytes().replace(COOKIE, b"MEX" + COOKIE[3:]))

    result = gate(root, bundle)

    assert result.returncode == 1
    assert UNCOVERED in result.stdout
    assert NOT_PROVEN in result.stderr


# The build venv's Python with one PyInstaller reader's extract() returning None, not bytes.
NO_BYTES_PYTHON = r"""#!/bin/bash
shift 2  # -I -: the gate's script comes on stdin
exec "$REAL_PY" -I -c '
import os, sys
from PyInstaller.archive import readers
from PyInstaller.loader import pyimod01_archive
kinds = {"pkg": readers.CArchiveReader, "pyz": pyimod01_archive.ZlibArchiveReader}
kinds[os.environ["BREAK"]].extract = lambda self, name, raw=False: None
exec(compile(sys.stdin.read(), "path_gate", "exec"))
' "$@"
"""


@pytest.mark.parametrize("reader", ["pkg", "pyz"])
def test_the_path_gate_fails_on_an_entry_that_yields_no_bytes(root, tmp_path, reader):
    bundle = app(root)
    frozen(bundle, tmp_path, CLEAN)
    python = tmp_path / "python"
    python.write_text(NO_BYTES_PYTHON)
    python.chmod(0o755)

    result = gate(root, bundle, PY=str(python), REAL_PY=sys.executable, BREAK=reader)

    assert result.returncode == 1
    assert "cannot scan Contents/MacOS/Cloudy Reader (TypeError)" in result.stdout
    assert NOT_PROVEN in result.stderr


def test_the_path_gate_fails_closed_on_a_pkg_it_cannot_parse(root):
    bundle = app(root)
    exe = bundle / "Contents" / "MacOS" / "Cloudy Reader"
    exe.write_bytes(b"#!/bin/sh\n" + COOKIE + b"\x00" * 8)  # the cookie, then no archive

    result = gate(root, bundle)

    assert result.returncode == 1
    assert "cannot scan Contents/MacOS/Cloudy Reader (" in result.stdout
    assert NOT_PROVEN in result.stderr


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


@pytest.mark.parametrize("planted", [True, False])
def test_the_path_gate_reads_a_compressed_entry_of_the_executables_pkg(root, tmp_path, planted):
    where = "/home/testowner/remi" if planted else "/opt/remi"
    bundle = app(root)  # a run-time hook sits in the PKG itself, not in the PYZ
    exe = frozen(bundle, tmp_path, CLEAN, hooks={"pyi_rth_paths": f"ROOT = {where!r}\n"})
    assert where.encode() not in exe.read_bytes()  # compressed: only a decompressing scan sees it

    result = gate(root, bundle)

    out = result.stdout + result.stderr
    if planted:
        assert result.returncode == 1
        assert "Contents/MacOS/Cloudy Reader!PKG:pyi_rth_paths: 1 hit" in out
    else:
        assert result.returncode == 0, out
