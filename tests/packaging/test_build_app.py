"""Packaging: scripts/build_app.sh safety, the PyInstaller spec contract, and a built bundle."""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import sys
import tomllib
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_app.sh"
SPEC = ROOT / "packaging" / "CloudyReader.spec"
BUILT_APP = ROOT / "dist" / "Cloudy Reader.app"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


# --- scripts/build_app.sh ------------------------------------------------------------------------


def test_script_parses_with_macos_bash() -> None:
    # Make runs recipes with /bin/bash, which is bash 3.2 on macOS.
    subprocess.run(["/bin/bash", "-n", str(SCRIPT)], check=True)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_script_is_shellcheck_clean() -> None:
    subprocess.run(["shellcheck", "-s", "bash", str(SCRIPT)], check=True)


@pytest.fixture
def fake_root(tmp_path: Path) -> Path:
    """A copy of the script in a throwaway repo root, so move_aside guards tmp_path instead."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "build_app.sh")
    shutil.copy(ROOT / "assets.lock.json", tmp_path / "assets.lock.json")
    (tmp_path / "dist").mkdir()
    (tmp_path / "build").mkdir()
    return tmp_path.resolve()


def bash_fn(root: Path, snippet: str, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Source the script copy under `root` (defines functions, runs nothing), then `snippet`."""
    inherited = {
        k: v for k, v in os.environ.items() if k not in ("KOKORO", "CLOUDYREADER_DATA_DIR")
    }
    full_env = inherited | {"CLOUDYREADER_DATA_DIR": str(root / "data"), **env}
    return subprocess.run(
        ["/bin/bash", "-c", f'source "$1/scripts/build_app.sh" && shift && {snippet}', "bash"]
        + [str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        env=full_env,
    )


def move_aside(root: Path, target: str) -> subprocess.CompletedProcess[str]:
    return bash_fn(root, 'move_aside "$1"', target)


def trash_dirs(root: Path) -> list[Path]:
    return sorted((root / "build").glob("trash.*"))


def test_script_never_deletes_recursively() -> None:
    # CLAUDE.md Command Execution Safety check 1: no `rm -r`/`rm -rf`/`rm -fr`, in any spelling.
    text = SCRIPT.read_text()
    assert not re.search(r"\brm\s+(-\w*[rR]|--recursive)", text)
    assert not re.search(r"\brm\s", text), "the script moves old output aside, never deletes"


def test_rerun_moves_the_old_bundle_aside(fake_root: Path) -> None:
    app = fake_root / "dist" / "Cloudy Reader.app"
    for build in ("first", "second"):
        (app / "Contents").mkdir(parents=True)
        locked = app / "Contents" / "build.txt"
        locked.write_text(build)
        locked.chmod(0o444)
        (app / "Contents").chmod(0o555)  # read-only inside: a rename does not care

        result = move_aside(fake_root, str(app))

        assert result.returncode == 0, result.stderr
        assert not app.exists()
        assert "make clean-app frees build/" in result.stdout

    kept = [t / "Cloudy Reader.app" / "Contents" / "build.txt" for t in trash_dirs(fake_root)]
    assert sorted(k.read_text() for k in kept) == ["first", "second"]


def test_move_aside_inside_build(fake_root: Path) -> None:
    work = fake_root / "build" / "work"
    work.mkdir()
    assert move_aside(fake_root, str(work)).returncode == 0
    assert not work.exists() and (trash_dirs(fake_root)[0] / "work").is_dir()


def test_move_aside_missing_target_is_fine(fake_root: Path) -> None:
    assert move_aside(fake_root, str(fake_root / "dist" / "nothing.app")).returncode == 0
    assert trash_dirs(fake_root) == []


@pytest.mark.parametrize("rel", ["dist", "build", "dist/..", "dist/.", "elsewhere/file.txt"])
def test_move_aside_refuses_outside_dist_and_build(fake_root: Path, rel: str) -> None:
    (fake_root / "elsewhere").mkdir()
    (fake_root / "elsewhere" / "file.txt").write_text("keep")

    result = move_aside(fake_root, str(fake_root / rel))

    assert result.returncode == 1
    assert "refusing to move" in result.stderr
    assert (fake_root / "dist").is_dir() and (fake_root / "elsewhere" / "file.txt").exists()
    assert trash_dirs(fake_root) == []


def test_move_aside_refuses_a_symlinked_way_out(fake_root: Path, tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (fake_root / "dist" / "out").symlink_to(outside, target_is_directory=True)
    (outside / "victim.app").mkdir()

    result = move_aside(fake_root, str(fake_root / "dist" / "out" / "victim.app"))

    assert result.returncode == 1
    assert (outside / "victim.app").is_dir()


def test_move_aside_moves_only_the_link(fake_root: Path, tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-target"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    link = fake_root / "dist" / "link.app"
    link.symlink_to(outside, target_is_directory=True)

    assert move_aside(fake_root, str(link)).returncode == 0
    assert not link.is_symlink() and (outside / "keep.txt").exists()
    assert (trash_dirs(fake_root)[0] / "link.app").is_symlink()


def test_fresh_dir_gives_each_run_its_own_folder(fake_root: Path) -> None:
    result = bash_fn(fake_root, "fresh_dir selftest-data && fresh_dir selftest-data")

    first, second = (Path(line) for line in result.stdout.splitlines())
    assert first != second
    for folder in (first, second):
        assert folder.parent == fake_root / "build" and folder.is_dir()
        assert folder.name.startswith("selftest-data.") and not any(folder.iterdir())


def write_voice(voices: Path, name: str, *, config: bool = True) -> None:
    voices.mkdir(parents=True, exist_ok=True)
    (voices / f"{name}.onnx").write_bytes(b"onnx")
    if config:
        (voices / f"{name}.onnx.json").write_text("{}")


def test_find_voices_without_voices_says_make_voices(fake_root: Path) -> None:
    result = bash_fn(fake_root, "find_voices")

    assert result.returncode == 1
    assert "(run: make voices)" in result.stderr


def test_find_voices_needs_the_onnx_json(fake_root: Path) -> None:
    write_voice(fake_root / "data" / "voices", "en_US-lonely-medium", config=False)
    assert "(run: make voices)" in bash_fn(fake_root, "find_voices").stderr


def test_find_voices_reads_cloudyreader_data_dir(fake_root: Path) -> None:
    write_voice(fake_root / "data" / "voices", "en_US-lessac-medium")
    write_voice(fake_root / "data" / "voices", "en_US-lonely-medium", config=False)

    result = bash_fn(fake_root, 'find_voices && printf "%s\\n" "${VOICES[@]}"')

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [str(fake_root / "data/voices/en_US-lessac-medium.onnx")]


def test_kokoro_1_without_model_says_make_kokoro(fake_root: Path) -> None:
    result = bash_fn(fake_root, "resolve_kokoro", KOKORO="1")

    assert result.returncode == 1
    assert "(run: make kokoro)" in result.stderr


def test_kokoro_1_with_incomplete_model_says_make_kokoro(fake_root: Path) -> None:
    (fake_root / "data" / "models" / "kokoro").mkdir(parents=True)
    (fake_root / "data" / "models" / "kokoro" / "config.json").write_text("{}")

    snippet = 'PY="$1" && resolve_kokoro'
    result = bash_fn(fake_root, snippet, str(ROOT / ".venv" / "bin" / "python"), KOKORO="1")

    assert result.returncode == 1
    assert "does not match assets.lock.json (run: make kokoro)" in result.stderr


def test_kokoro_auto_without_model_builds_piper_only(fake_root: Path) -> None:
    result = bash_fn(fake_root, 'resolve_kokoro && echo "KOKORO=$KOKORO"', KOKORO="auto")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "KOKORO=0"
    assert "building without Kokoro" in result.stdout


def test_kokoro_rejects_other_values(fake_root: Path) -> None:
    result = bash_fn(fake_root, "resolve_kokoro", KOKORO="yes")

    assert result.returncode == 1
    assert "KOKORO must be auto, 0 or 1" in result.stderr


def write_icon(root: Path, name: str) -> Path:
    icns = root / "assets" / "icons" / name / "AppIcon.icns"
    icns.parent.mkdir(parents=True)
    icns.write_bytes(b"icns")
    return icns


def resolve_icon(root: Path, icon: str) -> subprocess.CompletedProcess[str]:
    return bash_fn(root, 'resolve_icon && echo "ICON_PATH=$ICON_PATH"', ICON=icon)


def test_icon_parameter_overrides_default_txt(fake_root: Path) -> None:
    write_icon(fake_root, "cloud-voice")
    atom = write_icon(fake_root, "cloud-atom")
    (fake_root / "assets" / "icons" / "default.txt").write_text("cloud-voice\n")

    result = resolve_icon(fake_root, "cloud-atom")

    assert result.stdout.splitlines()[-1] == f"ICON_PATH={atom}"


def test_empty_icon_reads_default_txt(fake_root: Path) -> None:
    voice = write_icon(fake_root, "cloud-voice")
    (fake_root / "assets" / "icons" / "default.txt").write_text("cloud-voice\n")

    assert resolve_icon(fake_root, "").stdout.splitlines()[-1] == f"ICON_PATH={voice}"


def test_plain_make_app_uses_the_chosen_icon() -> None:
    # The user picked cloud-voice: `make app` with no ICON must build it (reads the real repo).
    result = resolve_icon(ROOT, "")

    assert result.returncode == 0, result.stderr
    icon = ROOT / "assets" / "icons" / "cloud-voice" / "AppIcon.icns"
    assert result.stdout.splitlines()[-1] == f"ICON_PATH={icon}"
    assert icon.is_file()


def test_missing_icon_falls_back_to_pyinstaller_default(fake_root: Path) -> None:
    result = resolve_icon(fake_root, "cloud-missing")

    assert result.returncode == 0
    assert "AppIcon.icns is missing" in result.stdout
    assert result.stdout.splitlines()[-1] == "ICON_PATH="


@pytest.mark.parametrize("icon", ["../secrets", "a/b", ".hidden"])
def test_icon_must_be_a_plain_folder_name(fake_root: Path, icon: str) -> None:
    result = resolve_icon(fake_root, icon)

    assert result.returncode == 1
    assert "must be a folder name under assets/icons/" in result.stderr


# --- packaging/CloudyReader.spec -----------------------------------------------------------------


def run_spec(monkeypatch: pytest.MonkeyPatch, **env: str) -> dict[str, dict[str, Any]]:
    """Execute the spec against stand-ins for PyInstaller's API; returns each call's kwargs."""
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_all = lambda package, **kw: ([], [], [])  # type: ignore[attr-defined]
    hooks.collect_data_files = lambda package, **kw: []  # type: ignore[attr-defined]
    hooks.collect_submodules = lambda package, **kw: []  # type: ignore[attr-defined]
    hooks.copy_metadata = lambda dist, **kw: []  # type: ignore[attr-defined]
    for name in ("PyInstaller", "PyInstaller.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    for key in ("CR_ENTRY", "CR_APP_NAME", "CR_ICON", "CR_KOKORO"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    calls: dict[str, dict[str, Any]] = {}

    def recorder(kind: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            calls[kind] = {"args": args, **kwargs}
            return types.SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

        return call

    namespace = {"SPECPATH": str(SPEC.parent)}
    namespace |= {k: recorder(k) for k in ("Analysis", "PYZ", "EXE", "COLLECT", "BUNDLE")}
    exec(compile(SPEC.read_text(), str(SPEC), "exec"), namespace)
    return calls


def test_spec_info_plist_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = run_spec(monkeypatch)["BUNDLE"]

    assert bundle["name"] == "Cloudy Reader.app"
    assert bundle["bundle_identifier"] == "com.cloudyreader.CloudyReader"
    assert bundle["icon"] is None  # PyInstaller's default icon
    assert bundle["info_plist"] == {
        "CFBundleName": "Cloudy Reader",
        "CFBundleDisplayName": "Cloudy Reader",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHumanReadableCopyright": "Copyright © 2026 the Cloudy Reader authors.",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "LSMinimumSystemVersion": "11.0",  # the floor: the stand-in Analysis collects no binaries
        "LSApplicationCategoryType": "public.app-category.education",
    }


def test_spec_builds_a_windowed_arm64_app(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = run_spec(monkeypatch)

    assert calls["EXE"]["name"] == "Cloudy Reader"  # becomes CFBundleExecutable
    assert calls["EXE"]["console"] is False
    assert calls["EXE"]["target_arch"] == "arm64"
    assert calls["EXE"]["argv_emulation"] is False
    assert calls["EXE"]["exclude_binaries"] is True  # one folder, not one file
    assert calls["Analysis"]["args"][0] == [str(ROOT / "packaging" / "launcher.py")]


def test_spec_follows_build_inputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    icon = tmp_path / "AppIcon.icns"
    calls = run_spec(monkeypatch, CR_APP_NAME="Cloudy Dev", CR_ICON=str(icon), CR_ENTRY="probe.py")

    assert calls["BUNDLE"]["name"] == "Cloudy Dev.app"
    assert calls["BUNDLE"]["icon"] == str(icon)
    assert calls["BUNDLE"]["info_plist"]["CFBundleDisplayName"] == "Cloudy Dev"
    assert calls["Analysis"]["args"][0] == ["probe.py"]


def test_spec_without_kokoro_ships_no_mlx_and_no_scispacy(monkeypatch: pytest.MonkeyPatch) -> None:
    analysis = run_spec(monkeypatch)["Analysis"]

    for module in ("scispacy", "sklearn", "scipy", "mlx", "mlx_audio", "misaki", "pytest"):
        assert module in analysis["excludes"]
    assert analysis["module_collection_mode"] == {}


def test_spec_leaves_onnxruntime_tools_out(monkeypatch: pytest.MonkeyPatch) -> None:
    # Its export tools import Hugging Face transformers (~100 MB with deps), unused by Piper.
    analysis = run_spec(monkeypatch)["Analysis"]

    for module in ("onnxruntime.transformers", "onnxruntime.quantization", "onnxruntime.tools"):
        assert module in analysis["excludes"]


def test_spec_with_kokoro_keeps_mlx_audio_files(monkeypatch: pytest.MonkeyPatch) -> None:
    analysis = run_spec(monkeypatch, CR_KOKORO="1")["Analysis"]

    assert analysis["module_collection_mode"] == {"mlx_audio": "pyz+py"}
    for module in ("mlx", "mlx_audio", "misaki", "scipy"):
        assert module not in analysis["excludes"]
    assert "mlx_audio.tts.utils" in analysis["hiddenimports"]


# --- a bundle that `make app` built ---------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(not BUILT_APP.is_dir(), reason="no dist/Cloudy Reader.app: run `make app`")
def test_built_bundle_is_named_signed_and_carries_assets() -> None:
    contents = BUILT_APP / "Contents"
    plist = plistlib.loads((contents / "Info.plist").read_bytes())
    assert plist["CFBundleName"] == plist["CFBundleDisplayName"] == "Cloudy Reader"
    assert plist["CFBundleIdentifier"] == "com.cloudyreader.CloudyReader"
    assert (contents / "MacOS" / plist["CFBundleExecutable"]).is_file()
    assert (contents / "Resources" / plist["CFBundleIconFile"]).is_file()

    voices = sorted((contents / "Resources" / "assets" / "voices").glob("*.onnx"))
    assert voices and all(Path(f"{v}.json").is_file() for v in voices)
    java = contents / "Frameworks" / "jdk4py" / "java-runtime" / "bin" / "java"
    assert java.is_file() and java.stat().st_mode & 0o111

    verify = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(BUILT_APP)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stderr
