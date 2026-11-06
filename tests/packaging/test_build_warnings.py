"""Packaging: `make app` prints no PyInstaller warning except a counted allowlist of benign ones."""

from __future__ import annotations

import shutil
import subprocess
import sys
import sysconfig
import types
from pathlib import Path

import pytest

from tests.packaging.test_build_app import bash_fn
from tests.packaging.test_bundle_metadata import spec_calls

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_app.sh"
HOOKS = ROOT / "packaging" / "hooks"
SITE = Path(sysconfig.get_paths()["purelib"])


# --- packaging/CloudyReader.spec ------------------------------------------------------------------


def test_spec_prunes_submodules_that_import_absent_packages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collected = spec_calls(monkeypatch)["collect_all"]

    keep = collected["catalogue"]["filter_submodules"]
    assert not keep("catalogue._importlib_metadata")  # backport for Python < 3.8, imports zipp
    keep = collected["piper"]["filter_submodules"]
    assert not keep("piper.train") and not keep("piper.train.vits.monotonic_align")  # torch
    assert keep("piper.voice") and keep("piper.trainer")
    assert not keep("spacy.tests.lang.en")  # test suites stay out, as before


def test_spec_drops_sounddevice_and_dateutils_windows_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = spec_calls(monkeypatch)

    assert "sounddevice" not in calls["collect_all"]  # a lone module: collect_all only warned
    assert "dateutil.tz.win" in calls["Analysis"]["excludes"]  # loads user32 via ctypes


def test_spec_loads_the_override_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    assert spec_calls(monkeypatch)["Analysis"]["hookspath"] == [str(HOOKS)]
    assert sorted(p.name for p in HOOKS.glob("hook-*.py")) == [
        "hook-pycparser.py",
        "hook-scipy.special._ufuncs.py",
    ]


# --- packaging/hooks ------------------------------------------------------------------------------


def as_version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def upstream(rel: str) -> Path:
    """An installed upstream hook; skips when the packaging group (PyInstaller) is not synced."""
    hook = SITE / rel
    if not hook.is_file():
        pytest.skip(f"no {rel}: sync the packaging group (make app does)")
    return hook


def run_hook(
    monkeypatch: pytest.MonkeyPatch,
    hook: Path,
    packages: dict[str, Path],
    versions: dict[str, str],
) -> list[str]:
    """A hook file's hiddenimports, run against stand-ins for PyInstaller's hook API."""

    def get_package_paths(name: str) -> tuple[str, str]:
        return str(packages[name].parent), str(packages[name])

    def is_module_satisfies(requirement: str) -> bool:
        name, op, version = requirement.split()
        assert op == ">="
        return as_version(versions[name]) >= as_version(version)

    api = types.ModuleType("PyInstaller.utils.hooks")
    api.get_package_paths = get_package_paths  # type: ignore[attr-defined]
    api.is_module_satisfies = is_module_satisfies  # type: ignore[attr-defined]
    for name in ("PyInstaller", "PyInstaller.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", api)
    namespace: dict[str, object] = {}
    exec(compile(hook.read_text(), str(hook), "exec"), namespace)
    return list(namespace["hiddenimports"])  # type: ignore[call-overload]


def fake_package(root: Path, name: str, *files: str) -> Path:
    for rel in files:
        (root / name / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / name / rel).write_bytes(b"")
    return root / name


def test_pycparser_hook_drops_the_ply_tables_pycparser_3_lacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pkg = fake_package(tmp_path, "pycparser", "c_lexer.py", "c_parser.py")

    assert run_hook(monkeypatch, HOOKS / "hook-pycparser.py", {"pycparser": pkg}, {}) == []


def test_pycparser_hook_matches_contribs_while_the_tables_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pkg = fake_package(tmp_path, "pycparser", "lextab.py", "yacctab.py")
    contrib = upstream("_pyinstaller_hooks_contrib/stdhooks/hook-pycparser.py")

    ours = run_hook(monkeypatch, HOOKS / "hook-pycparser.py", {"pycparser": pkg}, {})
    assert ours == run_hook(monkeypatch, contrib, {}, {})


def test_scipy_hook_drops_cdflib_that_scipy_1_17_lacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pkg = fake_package(tmp_path, "scipy", "special/_ufuncs_cxx.so", "special/_special_ufuncs.so")
    hook = HOOKS / "hook-scipy.special._ufuncs.py"

    hidden = run_hook(monkeypatch, hook, {"scipy": pkg}, {"scipy": "1.17.1"})

    assert hidden == ["scipy.special._ufuncs_cxx", "scipy.special._special_ufuncs"]


@pytest.mark.parametrize("version", ["1.12.0", "1.13.0", "1.14.0", "1.17.1"])
def test_scipy_hook_matches_pyinstallers_while_cdflib_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, version: str
) -> None:
    pkg = fake_package(tmp_path, "scipy", "special/_cdflib.cpython-312-darwin.so")
    theirs = upstream("PyInstaller/hooks/hook-scipy.special._ufuncs.py")
    inputs = ({"scipy": pkg}, {"scipy": version})

    ours = run_hook(monkeypatch, HOOKS / "hook-scipy.special._ufuncs.py", *inputs)
    assert ours == run_hook(monkeypatch, theirs, *inputs)


# --- scripts/build_app.sh: the PyInstaller call -------------------------------------------------

FAKE_PYINSTALLER = r"""#!/bin/bash
if [[ $1 == --version ]]; then echo 6.22.3; exit 0; fi
printf '%s\n' "$@" >"$FAKE_OUT/args"
env >"$FAKE_OUT/env"
while [[ $# -gt 0 ]]; do [[ $1 == --distpath ]] && dist=$2; shift; done
mkdir -p "$dist/$CR_APP_NAME.app/Contents/MacOS"
printf '#!/bin/sh\n' >"$dist/$CR_APP_NAME.app/Contents/MacOS/$CR_APP_NAME"
chmod +x "$dist/$CR_APP_NAME.app/Contents/MacOS/$CR_APP_NAME"
cat "$FAKE_OUT/lines"
exit "${FAKE_EXIT:-0}"
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A throwaway repo root holding a copy of the script, like test_build_app's fake_root."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "build_app.sh")
    (tmp_path / "build").mkdir()
    return tmp_path.resolve()


def build_bundle(
    root: Path, lines: list[str], exit_code: int = 0
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run build_bundle with a fake PyInstaller that prints `lines` and exits `exit_code`."""
    fake = root / "fake"
    fake.mkdir()
    (fake / "lines").write_text("".join(f"{line}\n" for line in lines))
    (fake / "pyinstaller").write_text(FAKE_PYINSTALLER)
    (fake / "pyinstaller").chmod(0o755)
    snippet = (
        'PY="$1"; PYI=("$2"); ENTRY=app; KOKORO=0; ENTRY_SCRIPT=launcher.py; ICON_PATH=; '
        'APP_NAME="Cloudy Reader"; SPEC=CloudyReader.spec; '
        'STAGE_APP="$ROOT/build/dist/$APP_NAME.app"; build_bundle'
    )
    env = {"FAKE_OUT": str(fake), "FAKE_EXIT": str(exit_code)}
    return bash_fn(root, snippet, sys.executable, str(fake / "pyinstaller"), **env), fake


def test_build_bundle_hides_only_the_allowlisted_warnings(root: Path) -> None:
    lines = [
        "62079 WARNING: Library ntdll required via ctypes not found",
        "62147 WARNING: Library libcudart.so required via ctypes not found",
        "62150 WARNING: Library libcudart.so required via ctypes not found here",  # not exact
        '60129 WARNING: Hidden import "pycparser.lextab" not found!',
        "61000 ERROR: something broke",
        "Traceback (most recent call last):",
    ]

    result, fake = build_bundle(root, lines)

    assert result.returncode == 0, result.stderr
    shown = result.stdout.splitlines()
    assert [line for line in shown if not line.startswith("build_app:")] == lines[2:]
    hidden = "2 known-benign PyInstaller warnings hidden; full log: build/pyinstaller.log"
    assert f"build_app: {hidden}" in shown
    assert (root / "build" / "pyinstaller.log").read_text().splitlines() == lines
    env = set((fake / "env").read_text().splitlines())
    assert {"TRANSFORMERS_VERBOSITY=error", "TRANSFORMERS_NO_ADVISORY_WARNINGS=1"} <= env
    assert "HF_HUB_OFFLINE=1" in env
    args = (fake / "args").read_text().splitlines()
    assert args[args.index("--log-level") + 1] == "WARN"  # never ERROR: real warnings still show


def test_build_bundle_stops_and_names_the_log_when_pyinstaller_fails(root: Path) -> None:
    result, _ = build_bundle(root, ["61000 ERROR: spec raised"], exit_code=3)

    assert result.returncode == 1
    assert "61000 ERROR: spec raised" in result.stdout
    assert "PyInstaller exited 3 (log: build/pyinstaller.log)" in result.stderr


def test_build_bundle_makes_the_build_folder_a_fresh_clone_lacks(root: Path) -> None:
    (root / "build").rmdir()

    result, _ = build_bundle(root, ["60000 INFO: done"])

    assert result.returncode == 0, result.stderr
    assert (root / "build" / "pyinstaller.log").read_text() == "60000 INFO: done\n"


def test_each_allowlisted_warning_says_why() -> None:
    block = SCRIPT.read_text().split("BENIGN_WARNINGS=(\n", 1)[1].split("\n)\n", 1)[0]
    lines = [line.strip() for line in block.splitlines()]
    entries = [i for i, line in enumerate(lines) if line.startswith('"')]

    assert entries and all(i > 0 and lines[i - 1].startswith("#") for i in entries)
