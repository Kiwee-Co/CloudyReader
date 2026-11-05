"""Packaging: the bundle's Info.plist, its icon, its ad-hoc signature, and its oldest macOS."""

from __future__ import annotations

import filecmp
import importlib.util
import os
import plistlib
import struct
import subprocess
import sys
import tomllib
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "packaging" / "CloudyReader.spec"
ICONS = ROOT / "assets" / "icons"
BUILT_APP = ROOT / "dist" / "Cloudy Reader.app"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
COPYRIGHT = "Copyright © 2026 the Cloudy Reader authors."
# The icns element for each iconset slot: 16, 32, 128, 256 and 512 points, at 1x and 2x.
ICNS_SLOTS = {
    "ic04": 16,
    "ic11": 32,
    "ic05": 32,
    "ic12": 64,
    "ic07": 128,
    "ic13": 256,
    "ic08": 256,
    "ic14": 512,
    "ic09": 512,
    "ic10": 1024,
}
PNG = b"\x89PNG\r\n\x1a\n"
ARM64, X86_64 = 0x0100000C, 0x01000007


def _load_min_macos() -> types.ModuleType:
    # packaging/ is no package, and PyPI's `packaging` owns the name: import the file by path.
    spec = importlib.util.spec_from_file_location("min_macos", ROOT / "packaging" / "min_macos.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


min_macos = _load_min_macos()


# --- packaging/min_macos.py -----------------------------------------------------------------------


def packed(version: str) -> int:
    x, y, z = (int(part) for part in f"{version}.0.0".split(".")[:3])
    return x << 16 | y << 8 | z


def thin(
    minos: str = "26.0",
    sdk: str = "26.0",
    *,
    old: bool = False,
    platform: int = 1,
    cpu: int = ARM64,
) -> bytes:
    """A 64-bit Mach-O header with one LC_BUILD_VERSION (or, old, LC_VERSION_MIN_MACOSX)."""
    if old:
        command = struct.pack("<IIII", 0x24, 16, packed(minos), packed(sdk))
    else:
        command = struct.pack("<IIIIII", 0x32, 24, platform, packed(minos), packed(sdk), 0)
    return struct.pack("<IIIIIIII", 0xFEEDFACF, cpu, 0, 6, 1, len(command), 0, 0) + command


def fat(*slices: tuple[int, bytes]) -> bytes:
    """A universal binary: each (cputype, thin Mach-O) slice on its own 4 KiB page."""
    table = b"".join(
        struct.pack(">IIIII", cpu, 0, 4096 * (i + 1), len(blob), 12)
        for i, (cpu, blob) in enumerate(slices)
    )
    head = (struct.pack(">II", 0xCAFEBABE, len(slices)) + table).ljust(4096, b"\0")
    return head + b"".join(blob.ljust(4096, b"\0") for _, blob in slices)


def write(folder: Path, name: str, data: bytes) -> Path:
    path = folder / name
    path.write_bytes(data)
    return path


def test_min_macos_is_the_newest_binarys_minimum(tmp_path: Path) -> None:
    files = [
        write(tmp_path, "QtCore.abi3.so", thin("26.0")),
        write(tmp_path, "QtCore", thin("14.4")),
        write(tmp_path, "java", thin("11.0")),
    ]
    assert min_macos.min_macos(files) == "26.0"


def test_min_macos_reads_the_older_version_min_command(tmp_path: Path) -> None:
    assert min_macos.min_macos([write(tmp_path, "old.so", thin("12.3", old=True))]) == "12.3"


def test_min_macos_keeps_a_patch_level(tmp_path: Path) -> None:
    assert min_macos.min_macos([write(tmp_path, "mlx.so", thin("26.2.1"))]) == "26.2.1"


def test_min_macos_never_goes_below_the_floor(tmp_path: Path) -> None:
    assert min_macos.min_macos([write(tmp_path, "a.so", thin("10.13"))], floor="11.0") == "11.0"
    assert min_macos.min_macos([], floor="11.0") == "11.0"


def test_min_macos_reads_the_arm64_slice_of_a_universal_binary(tmp_path: Path) -> None:
    both = fat((X86_64, thin("27.0", cpu=X86_64)), (ARM64, thin("26.0")))
    assert min_macos.min_macos([write(tmp_path, "u.so", both)]) == "26.0"
    intel = fat((X86_64, thin("15.0", cpu=X86_64)))
    assert min_macos.min_macos([write(tmp_path, "i.so", intel)]) == "15.0"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"plain text",
        b"\xca\xfe\xba\xbe\x00\x00\x00\x41" + bytes(64),  # Java class file: fat magic, version 65
        thin("26.0")[:40],  # truncated inside the load command
        thin("26.0", platform=2),  # iOS
        fat((ARM64, thin("26.0")))[:30],  # truncated slice table
    ],
)
def test_min_macos_ignores_what_is_no_macos_binary(tmp_path: Path, data: bytes) -> None:
    assert min_macos.min_macos([write(tmp_path, "file", data)], floor="11.0") == "11.0"


def test_min_macos_skips_paths_it_cannot_read(tmp_path: Path) -> None:
    assert min_macos.min_macos([tmp_path / "missing.so", tmp_path], floor="11.0") == "11.0"


def test_read_versions_gives_minos_and_sdk(tmp_path: Path) -> None:
    path = write(tmp_path, "exe", thin("11.0", "15.5"))
    assert min_macos.read_versions(path) == [((11, 0, 0), (15, 5, 0))]


def test_read_versions_stops_at_malformed_load_commands(tmp_path: Path) -> None:
    good = thin("26.0")
    short = good[:16] + struct.pack("<I", 2) + good[20:]  # claims two commands, holds one
    assert min_macos.read_versions(write(tmp_path, "a", short)) == [((26, 0, 0), (26, 0, 0))]
    head = struct.pack("<IIIIIIII", 0xFEEDFACF, ARM64, 0, 6, 2, 8, 0, 0)
    zero = head + struct.pack("<II", 0x19, 0)  # cmdsize 0 ends the scan
    assert min_macos.read_versions(write(tmp_path, "b", zero)) == []


# --- packaging/CloudyReader.spec ------------------------------------------------------------------


def spec_calls(
    monkeypatch: pytest.MonkeyPatch, binaries: list[tuple[str, str, str]] | None = None
) -> dict[str, dict[str, Any]]:
    """Run the spec on stand-ins for PyInstaller's API whose Analysis collects `binaries`.

    calls["collect_all"] maps each package the spec collects to the keywords it passed.
    """
    calls: dict[str, dict[str, Any]] = {"collect_all": {}}

    def collect_all(package: str, **kw: Any) -> tuple[list, list, list]:
        calls["collect_all"][package] = kw
        return [], [], []

    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_all = collect_all  # type: ignore[attr-defined]
    hooks.collect_data_files = lambda package, **kw: []  # type: ignore[attr-defined]
    hooks.collect_submodules = lambda package, **kw: []  # type: ignore[attr-defined]
    hooks.copy_metadata = lambda dist, **kw: []  # type: ignore[attr-defined]
    for name in ("PyInstaller", "PyInstaller.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    for key in ("CR_ENTRY", "CR_APP_NAME", "CR_ICON", "CR_KOKORO"):
        monkeypatch.delenv(key, raising=False)
    toc = types.SimpleNamespace(pure=[], scripts=[], binaries=binaries or [], datas=[])

    def recorder(kind: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            calls[kind] = {"args": args, **kwargs}
            return toc

        return call

    namespace = {"SPECPATH": str(SPEC.parent)}
    namespace |= {k: recorder(k) for k in ("Analysis", "PYZ", "EXE", "COLLECT", "BUNDLE")}
    exec(compile(SPEC.read_text(), str(SPEC), "exec"), namespace)
    return calls


def test_spec_min_macos_follows_the_collected_binaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    qt = write(tmp_path, "QtCore.abi3.so", thin("26.0"))
    java = write(tmp_path, "java", thin("11.0"))
    model = write(tmp_path, "model.onnx", b"onnx")
    toc = [
        ("PySide6/QtCore.abi3.so", str(qt), "EXTENSION"),
        ("jdk4py/java-runtime/bin/java", str(java), "BINARY"),
        ("assets/model.onnx", str(model), "DATA"),
    ]

    plist = spec_calls(monkeypatch, toc)["BUNDLE"]["info_plist"]

    assert plist["LSMinimumSystemVersion"] == "26.0"


def test_spec_min_macos_without_binaries_is_the_bootloaders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert spec_calls(monkeypatch)["BUNDLE"]["info_plist"]["LSMinimumSystemVersion"] == "11.0"


def test_spec_sets_the_copyright_and_leaves_dark_mode_and_the_dock_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plist = spec_calls(monkeypatch)["BUNDLE"]["info_plist"]

    assert plist["NSHumanReadableCopyright"] == COPYRIGHT
    assert "NSRequiresAquaSystemAppearance" not in plist  # True would force the light look
    assert not {"LSUIElement", "LSBackgroundOnly"} & plist.keys()  # both hide the Dock icon


# --- assets/icons ---------------------------------------------------------------------------------


def icns_entries(path: Path) -> dict[str, bytes]:
    data = path.read_bytes()
    assert data[:4] == b"icns" and int.from_bytes(data[4:8], "big") == len(data)
    entries, at = {}, 8
    while at < len(data):
        size = int.from_bytes(data[at + 4 : at + 8], "big")
        entries[data[at : at + 4].decode("latin-1")] = data[at + 8 : at + size]
        at += size
    return entries


@pytest.mark.parametrize("name", sorted(p.parent.name for p in ICONS.glob("*/AppIcon.icns")))
def test_icns_holds_every_size_at_1x_and_2x(name: str) -> None:
    entries = icns_entries(ICONS / name / "AppIcon.icns")

    assert set(ICNS_SLOTS) <= entries.keys()
    for kind, px in ICNS_SLOTS.items():
        data = entries[kind]
        if data[:8] == PNG:
            assert struct.unpack(">II", data[16:24]) == (px, px), kind
        else:  # iconutil stores the 16 and 32 px slots as RLE-packed ARGB
            assert data[:4] == b"ARGB", kind


# --- a bundle that `make app` built ---------------------------------------------------------------

needs_built_app = pytest.mark.skipif(
    not BUILT_APP.is_dir(), reason="no dist/Cloudy Reader.app: run `make app`"
)


def built_plist() -> dict[str, Any]:
    return plistlib.loads((BUILT_APP / "Contents" / "Info.plist").read_bytes())


@pytest.mark.slow
@needs_built_app
def test_built_info_plist_is_valid_and_complete() -> None:
    lint = subprocess.run(
        ["plutil", "-lint", str(BUILT_APP / "Contents" / "Info.plist")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert lint.returncode == 0, lint.stdout

    plist = built_plist()
    assert plist["CFBundleName"] == plist["CFBundleDisplayName"] == "Cloudy Reader"
    assert plist["CFBundleIdentifier"] == "com.cloudyreader.CloudyReader"
    assert plist["CFBundlePackageType"] == "APPL"
    assert plist["CFBundleShortVersionString"] == plist["CFBundleVersion"] == VERSION
    assert plist["NSHumanReadableCopyright"] == COPYRIGHT
    assert plist["NSHighResolutionCapable"] is True
    assert plist["LSApplicationCategoryType"] == "public.app-category.education"
    assert not plist.get("NSRequiresAquaSystemAppearance", False)
    assert not plist.get("LSUIElement", False) and not plist.get("LSBackgroundOnly", False)


@pytest.mark.slow
@needs_built_app
def test_built_bundle_carries_one_of_our_icons() -> None:
    bundled = BUILT_APP / "Contents" / "Resources" / built_plist()["CFBundleIconFile"]
    ours = {p.read_bytes() for p in ICONS.glob("*/AppIcon.icns")}

    assert bundled.read_bytes() in ours, "not an assets/icons design: PyInstaller's generic icon?"


@pytest.mark.slow
@needs_built_app
def test_built_bundle_carries_the_default_cloud_atom_icon() -> None:
    # The user's pick; test_build_app pins that assets/icons/default.txt names it.
    bundled = BUILT_APP / "Contents" / "Resources" / "AppIcon.icns"
    atom = ICONS / "cloud-atom" / "AppIcon.icns"

    assert filecmp.cmp(bundled, atom, shallow=False), f"{bundled} differs from {atom}"


@pytest.mark.slow
@needs_built_app
def test_built_min_macos_is_what_its_newest_binary_needs() -> None:
    files = [Path(folder) / name for folder, _, names in os.walk(BUILT_APP) for name in names]

    assert built_plist()["LSMinimumSystemVersion"] == min_macos.min_macos(files)


@pytest.mark.slow
@needs_built_app
def test_built_executable_keeps_dark_mode_and_is_signed_ad_hoc() -> None:
    exe = BUILT_APP / "Contents" / "MacOS" / built_plist()["CFBundleExecutable"]
    sdks = [sdk for _, sdk in min_macos.read_versions(exe)]
    # macOS turns dark mode on for an executable linked against the 10.14 SDK or later.
    assert sdks and min(sdks) >= (10, 14, 0)

    info = subprocess.run(
        ["codesign", "-dv", str(BUILT_APP)], capture_output=True, text=True, check=False
    )
    assert info.returncode == 0, info.stderr
    assert "Signature=adhoc" in info.stderr


@pytest.mark.slow
@needs_built_app
@pytest.mark.usefixtures("qapp")
def test_built_bundle_lets_the_about_box_load_its_icon() -> None:
    # The frozen About box shows the Info.plist icon through Qt's icns plugin; without the
    # plugin it shows none, silently. Imported here: only this test needs the GUI side.
    from PySide6.QtGui import QIcon

    from cloudyreader.frozen import bundle_resources_dir
    from cloudyreader.gui.app import bundle_icon_path

    contents = BUILT_APP / "Contents"
    resources = bundle_resources_dir(contents / "MacOS" / built_plist()["CFBundleExecutable"])
    icon = bundle_icon_path(resources)
    assert icon == contents / "Resources" / "AppIcon.icns"
    assert not QIcon(str(icon)).pixmap(64, 64).isNull()  # the About box's icon size

    # PyInstaller's PySide6 runtime hook sets QT_PLUGIN_PATH to Frameworks/PySide6/Qt/plugins.
    plugin = contents / "Frameworks/PySide6/Qt/plugins/imageformats/libqicns.dylib"
    assert min_macos.read_versions(plugin), "no Qt icns plugin: the About box shows no icon"
    for qt in ("QtCore", "QtGui"):  # the plugin's @rpath, @loader_path/../../../.., is Frameworks
        assert (contents / "Frameworks" / qt).is_file()
