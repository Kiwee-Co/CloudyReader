"""Packaging (R1): the lean bundle, its voice audit, its self-tests, the release zip and DMG."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

from cloudyreader.config import load_settings
from cloudyreader.frozen import link_bundled_assets
from cloudyreader.prefetch import find_lock
from tests.packaging.test_build_app import bash_fn

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_app.sh"
ZIP = "Cloudy-Reader-0.0.1-macos-arm64.zip"
DMG = "Cloudy-Reader-0.0.1-macos-arm64.dmg"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A throwaway repo root holding a copy of the script, like test_build_app's fake_root."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "build_app.sh")
    shutil.copy(ROOT / "assets.lock.json", tmp_path / "assets.lock.json")
    (tmp_path / "dist").mkdir()
    (tmp_path / "build").mkdir()
    return tmp_path.resolve()


def host_assets(root: Path) -> None:
    """A Piper voice and a Kokoro model, as the build host keeps them in its data folder."""
    voices = root / "data" / "voices"
    voices.mkdir(parents=True)
    for name in ("en_US-a-medium.onnx", "en_US-a-medium.onnx.json"):
        (voices / name).write_text(name)
    kokoro = root / "data" / "models" / "kokoro"
    (kokoro / "voices").mkdir(parents=True)
    (kokoro / "kokoro-v1_0.safetensors").write_bytes(b"weights")
    (kokoro / "voices" / "af_heart.safetensors").write_bytes(b"voice")


# --- the lean bundle -----------------------------------------------------------------------------


def staged_assets(root: Path, bundle_voices: str) -> list[str]:
    host_assets(root)
    snippet = (
        'STAGE_APP="$ROOT/build/dist/Cloudy Reader.app"; KOKORO=1; '
        'KOKORO_DIR="$CLOUDYREADER_DATA_DIR/models/kokoro"; '
        'mkdir -p "$STAGE_APP/Contents/Resources" && find_voices && add_assets && '
        'cd "$STAGE_APP/Contents/Resources" && find assets | sort'
    )
    result = bash_fn(root, snippet, BUNDLE_VOICES=bundle_voices)
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def test_lean_add_assets_ships_only_the_lock(root):
    assert staged_assets(root, "0") == ["assets", "assets/assets.lock.json"]


def test_full_add_assets_still_bundles_the_voices_and_kokoro(root):
    listed = staged_assets(root, "1")

    assert "assets/assets.lock.json" in listed
    assert "assets/voices/en_US-a-medium.onnx" in listed
    assert "assets/models/kokoro/voices/af_heart.safetensors" in listed


@pytest.mark.parametrize("value", ["2", "yes", "true"])
def test_bundle_voices_must_be_0_or_1(root, value):
    result = bash_fn(root, "resolve_bundle_voices", BUNDLE_VOICES=value)

    assert result.returncode == 1
    assert f"BUNDLE_VOICES must be 0 or 1, got '{value}'" in result.stderr


def test_a_lean_bundle_links_nothing_and_still_finds_its_lock(tmp_path):
    resources = tmp_path / "Cloudy Reader.app" / "Contents" / "Resources"
    (resources / "assets").mkdir(parents=True)
    lock = resources / "assets" / "assets.lock.json"
    lock.write_text(json.dumps({"version": 1, "assets": []}))
    settings = load_settings({"CLOUDYREADER_DATA_DIR": str(tmp_path / "data")})

    assert link_bundled_assets(settings, resources_dir=resources) == []
    assert not (tmp_path / "data").exists()  # no folder made, nothing linked
    assert find_lock(resources_dir=resources, root=tmp_path / "checkout") == lock


# --- the voice audit ----------------------------------------------------------------------------


def bundle(root: Path, *extra: str) -> Path:
    """A lean bundle tree: the lock, piper's two diacritizer models, some package code."""
    app = root / "build" / "dist" / "Cloudy Reader.app"
    for rel in (
        "Contents/Resources/assets/assets.lock.json",
        "Contents/Resources/piper/hebrew/nakdimon.onnx",
        "Contents/Resources/piper/tashkeel/model.onnx",
        "Contents/Resources/spacy/lang/en/stop_words.py",
        *extra,
    ):
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_bytes(b"x")
    return app


def test_audit_passes_a_lean_bundle(root):
    result = bash_fn(root, 'audit_voices "$1"', str(bundle(root)))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["build_app: voice audit: no voice binary in the bundle"]


@pytest.mark.parametrize(
    "rel",
    [
        "Contents/Resources/assets/voices/en_US-lessac-medium.onnx",
        "Contents/Resources/assets/models/kokoro/voices/af_heart.safetensors",
        "Contents/Resources/stray/en_US-amy-medium.onnx.json",
        "Contents/Resources/mlx_audio/tts/models/kokoro/kokoro-v1_0.safetensors",
        "Contents/Resources/somewhere/model.onnx",
    ],
)
def test_audit_fails_on_any_voice_binary_and_names_it(root, rel):
    result = bash_fn(root, 'audit_voices "$1"', str(bundle(root, rel)))

    assert result.returncode == 1
    assert "voice binaries in the bundle" in result.stderr
    assert rel in result.stderr


def test_audit_fails_on_an_empty_voices_or_models_folder(root):
    app = bundle(root)
    (app / "Contents" / "Resources" / "assets" / "models").mkdir()

    result = bash_fn(root, 'audit_voices "$1"', str(app))

    assert result.returncode == 1
    assert "Contents/Resources/assets/models" in result.stderr


# --- the self-tests of a lean bundle -------------------------------------------------------------


def test_the_seeded_data_folder_links_the_host_voices_and_kokoro(root):
    host_assets(root)
    seeded = root / "build" / "seeded"
    snippet = (
        'KOKORO_DIR="$CLOUDYREADER_DATA_DIR/models/kokoro" && find_voices && '
        'seed_selftest_data "$1"'
    )

    result = bash_fn(root, snippet, str(seeded))

    assert result.returncode == 0, result.stderr
    voice = seeded / "voices" / "en_US-a-medium.onnx"
    assert voice.is_symlink() and voice.resolve() == root / "data" / "voices" / voice.name
    assert (seeded / "voices" / "en_US-a-medium.onnx.json").is_symlink()
    assert (seeded / "models" / "kokoro").resolve() == root / "data" / "models" / "kokoro"


FAKE_APP = r"""#!/bin/bash
# --version prints FAKE_VERSION (the bundled metadata). --self-test: PASS with a voice in the data
# folder, else the documented no-voice result.
if [[ ${1:-} == --version ]]; then echo "Cloudy Reader ${FAKE_VERSION:-0.0.1}"; exit 0; fi
if ls "$CLOUDYREADER_DATA_DIR"/voices/*.onnx >/dev/null 2>&1; then echo PASS; exit 0; fi
no_voice="FAIL: no Piper voice installed"
case ${FAKE_MODE:-documented} in
  documented) echo "voices    0 found, no Piper voice"; echo "$no_voice" >&2; exit 2 ;;
  crash) echo "Traceback (most recent call last):" >&2; echo "$no_voice" >&2; exit 2 ;;
  silent) exit 2 ;;
  zero) exit 0 ;;
esac
"""


def fake_app(root: Path, version: str = "0.0.1") -> Path:
    app = root / "dist" / "Cloudy Reader.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "Cloudy Reader").write_text(FAKE_APP)
    (app / "Contents" / "MacOS" / "Cloudy Reader").chmod(0o755)
    plist = {
        "CFBundleExecutable": "Cloudy Reader",
        "CFBundleShortVersionString": version,
        "LSMinimumSystemVersion": "26.2",
    }
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(plist))
    (app / "Contents" / "Resources" / "assets").mkdir(parents=True)
    (app / "Contents" / "Resources" / "assets" / "assets.lock.json").write_text("{}")
    return app


@pytest.mark.parametrize(
    ("mode", "problem"),
    [
        ("documented", None),
        ("crash", "printed a traceback"),
        ("silent", "did not print 'FAIL: no Piper voice installed'"),
        ("zero", "exited 0, expected 2 (no voice installed)"),
    ],
)
def test_the_empty_data_run_must_report_no_voice_without_a_traceback(root, mode, problem):
    app = fake_app(root)

    result = bash_fn(
        root, 'APP_NAME="Cloudy Reader"; self_test_no_voice "$1"', str(app), FAKE_MODE=mode
    )

    if problem is None:
        assert result.returncode == 0, result.stderr
        assert "no voice installed, exit 2, as documented" in result.stdout
    else:
        assert result.returncode == 1
        assert problem in result.stderr


# --- make release ---------------------------------------------------------------------------------


def test_release_zip_name_and_checksum_format(root):
    zip_path = root / "dist" / ZIP
    zip_path.write_bytes(b"zip bytes")

    result = bash_fn(
        root, 'APP_NAME="Cloudy Reader"; release_name 0.0.1 && write_checksum "$1"', str(zip_path)
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ZIP
    digest = hashlib.sha256(b"zip bytes").hexdigest()
    assert (root / "dist" / f"{ZIP}.sha256").read_text() == f"{digest}  {ZIP}\n"


def stub_codesign(root: Path) -> tuple[str, Path]:
    """A codesign that records its arguments and passes: the fake app has no real signature."""
    bin_dir, args = root / "bin", root / "codesign.args"
    bin_dir.mkdir()
    (bin_dir / "codesign").write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" >>"{args}"\n')
    (bin_dir / "codesign").chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}", args


# Stand-ins for the DMG steps where a test is about the zip: a real image takes about 10 s.
NO_DMG = 'make_dmg() { echo image >"$2"; }; check_dmg() { :; }; '


def test_release_zips_checksums_and_verifies_the_extracted_copy(root):
    host_assets(root)
    fake_app(root)
    path, args = stub_codesign(root)

    result = bash_fn(root, f'APP_NAME="Cloudy Reader"; {NO_DMG}release_main 0.0.1', PATH=path)

    assert result.returncode == 0, result.stderr
    names = zipfile.ZipFile(root / "dist" / ZIP).namelist()
    assert "Cloudy Reader.app/Contents/MacOS/Cloudy Reader" in names
    assert not [n for n in names if re.search(r"(^|/)(__MACOSX|\.DS_Store|\._)", n)]
    digest = hashlib.sha256((root / "dist" / ZIP).read_bytes()).hexdigest()
    assert (root / "dist" / f"{ZIP}.sha256").read_text() == f"{digest}  {ZIP}\n"
    verify = args.read_text().splitlines()
    assert verify[:3] == ["--verify", "--deep", "--strict"]
    assert re.fullmatch(
        rf"{re.escape(str(root))}/build/release-check\.\w+/Cloudy Reader\.app", verify[3]
    )
    out = result.stdout
    assert f"release: {ZIP}: version 0.0.1, macOS 26.2 or later" in out
    assert "release: the extracted copy's --version prints Cloudy Reader 0.0.1" in out
    assert "build_app: voice audit: no voice binary in the bundle" in out
    assert "release: the extracted copy passes codesign, the voice audit and the self-test" in out
    assert re.search(rf"release: {re.escape(str(root / 'dist' / ZIP))} \([\d.]+ MB\)", out)


def test_release_needs_the_extracted_copy_to_print_its_version(root):
    host_assets(root)
    fake_app(root)  # Info.plist says 0.0.1, but the bundled metadata below is stale
    path, _ = stub_codesign(root)

    result = bash_fn(
        root, 'APP_NAME="Cloudy Reader"; release_main 0.0.1', PATH=path, FAKE_VERSION="0.1.0"
    )

    assert result.returncode == 1
    assert (
        "the extracted copy's --version prints 'Cloudy Reader 0.1.0', not 'Cloudy Reader 0.0.1'"
        in result.stderr
    )


def fake_venv(root: Path) -> None:
    """A build venv whose python prints FAKE_META as cloudyreader's version; fails without it."""
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/bash\n[[ -n ${FAKE_META:-} ]] || exit 1\necho "$FAKE_META"\n')
    python.chmod(0o755)


@pytest.mark.parametrize(
    ("meta", "problem"),
    [
        ("0.0.1", None),
        ("0.1.0", "metadata says 0.1.0, not 0.0.1"),
        ("", "metadata says none, not 0.0.1"),
    ],
)
def test_release_preflight_needs_the_build_venv_metadata_at_version(root, meta, problem):
    fake_venv(root)

    result = bash_fn(root, "release_preflight 0.0.1", FAKE_META=meta)

    if problem is None:
        assert result.returncode == 0, result.stderr
        assert "release: the build venv's cloudyreader metadata says 0.0.1" in result.stdout
    else:
        assert result.returncode == 1
        assert problem in result.stderr and "run the sync step first" in result.stderr


def test_the_script_runs_the_preflight_as_its_own_step(root):
    fake_venv(root)
    env = {k: v for k, v in os.environ.items() if k != "KOKORO"} | {"FAKE_META": "0.0.2"}

    done = subprocess.run(
        ["/bin/bash", str(root / "scripts" / "build_app.sh"), "release-preflight", "0.0.1"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert done.returncode == 1
    assert "metadata says 0.0.2, not 0.0.1" in done.stderr


def test_make_release_checks_the_venv_before_it_builds():
    lines = (ROOT / "Makefile").read_text().splitlines()
    start = lines.index(next(line for line in lines if line.startswith("release:")))
    recipe = [line.strip() for line in lines[start + 1 : start + 4]]

    assert recipe[0].endswith('bash scripts/build_app.sh release-preflight "$(VERSION)"')
    assert "app BUNDLE_VOICES=0 OFFLINE=1 ICON=cloud-atom KOKORO=1" in recipe[1]
    assert recipe[2].endswith('bash scripts/build_app.sh release "$(VERSION)"')


@pytest.mark.parametrize(
    ("version", "message"),
    [
        ("v0.0.1", "VERSION must look like 1.2.3, got 'v0.0.1'"),
        ("0.0.2", "the app says version 0.0.1, not 0.0.2"),
    ],
)
def test_release_refuses_a_version_the_app_does_not_carry(root, version, message):
    host_assets(root)
    fake_app(root)
    path, _ = stub_codesign(root)

    result = bash_fn(root, f'APP_NAME="Cloudy Reader"; release_main {version}', PATH=path)

    assert result.returncode == 1
    assert message in result.stderr


def test_release_keeps_a_previous_artifact_by_moving_it_aside(root):
    host_assets(root)
    fake_app(root)
    path, _ = stub_codesign(root)
    (root / "dist" / ZIP).write_bytes(b"older build")
    (root / "dist" / DMG).write_bytes(b"older image")

    result = bash_fn(root, f'APP_NAME="Cloudy Reader"; {NO_DMG}release_main 0.0.1', PATH=path)

    assert result.returncode == 0, result.stderr
    kept = list((root / "build").glob(f"trash.*/{ZIP}"))
    assert [p.read_bytes() for p in kept] == [b"older build"]
    kept = list((root / "build").glob(f"trash.*/{DMG}"))
    assert [p.read_bytes() for p in kept] == [b"older image"]


# --- the release DMG -----------------------------------------------------------------------------


def mounted_under(root: Path) -> list[str]:
    """Mounts whose mount point lies under root: no test may leave one behind."""
    table = subprocess.run(["mount"], capture_output=True, text=True, check=True).stdout
    return [line for line in table.splitlines() if str(root) in line]


def test_release_names_the_dmg_beside_the_zip(root):
    snippet = 'APP_NAME="Cloudy Reader"; release_name 0.0.1 dmg && echo && release_name 0.0.1'

    assert bash_fn(root, snippet).stdout.splitlines() == [DMG, ZIP]


@pytest.fixture(scope="session")
def real_dmg_host(tmp_path_factory):
    """Skip the real-tool DMG tests where this host cannot make even a tiny image (a CI VM)."""
    probe = tmp_path_factory.mktemp("dmg-probe").resolve()
    (probe / "scripts").mkdir()
    shutil.copy(SCRIPT, probe / "scripts" / "build_app.sh")
    (probe / "build").mkdir()
    (probe / "stage").mkdir()
    (probe / "stage" / "file").write_text("probe")

    result = bash_fn(probe, 'create_dmg "$ROOT/stage" "$ROOT/probe.dmg" probe')

    if result.returncode != 0:
        pytest.skip("this host cannot make a DMG: " + " ".join(result.stderr.split())[-300:])


@pytest.mark.slow
def test_release_writes_a_dmg_of_the_zips_app_and_checks_it(root, real_dmg_host):
    host_assets(root)
    fake_app(root)
    path, args = stub_codesign(root)

    result = bash_fn(root, 'APP_NAME="Cloudy Reader"; release_main 0.0.1', PATH=path)

    assert result.returncode == 0, result.stderr
    digest = hashlib.sha256((root / "dist" / DMG).read_bytes()).hexdigest()
    assert (root / "dist" / f"{DMG}.sha256").read_text() == f"{digest}  {DMG}\n"
    out = result.stdout
    volume = "volume Cloudy Reader holds the app and an Applications link"
    assert f"release: {DMG}: verified; {volume}" in out
    assert (
        f"release: {DMG}: its app passes codesign, --version and the voice audit, "
        "and matches the zip's copy" in out
    )
    assert re.search(rf"release: {re.escape(str(root / 'dist' / DMG))} \([\d.]+ MB\)", out)
    assert any("/build/dmg-mount." in line for line in args.read_text().splitlines())
    assert not mounted_under(root)


@pytest.mark.slow
def test_check_dmg_fails_and_still_ejects_the_volume(root, real_dmg_host):
    fake_app(root)
    path, _ = stub_codesign(root)
    snippet = (
        'APP_NAME="Cloudy Reader"; app="$ROOT/dist/Cloudy Reader.app"; '
        'make_dmg "$app" "$ROOT/dist/t.dmg" && '
        'chmod 600 "$app/Contents/Info.plist" && '  # now the zip's copy differs in one mode
        'check_dmg "$ROOT/dist/t.dmg" "$app" 0.0.1 "$(fresh_dir data)"'
    )

    result = bash_fn(root, snippet, PATH=path)

    assert result.returncode == 1
    assert "t.dmg: its app differs from the zip's copy" in result.stderr
    assert not mounted_under(root)


@pytest.mark.slow
def test_the_dmg_falls_back_to_hdiutil_where_diskutil_has_no_image_verb(root, real_dmg_host):
    fake_app(root)
    path, _ = stub_codesign(root)
    old = root / "bin" / "old-diskutil"
    old.write_text('#!/bin/bash\n[[ ${1:-} == image ]] && exit 1\nexec /usr/sbin/diskutil "$@"\n')
    old.chmod(0o755)
    snippet = (
        'APP_NAME="Cloudy Reader"; app="$ROOT/dist/Cloudy Reader.app"; '
        'make_dmg "$app" "$ROOT/dist/t.dmg" && '
        'check_dmg "$ROOT/dist/t.dmg" "$app" 0.0.1 "$(fresh_dir data)"'
    )

    result = bash_fn(root, snippet, PATH=path, DISKUTIL=str(old))

    assert result.returncode == 0, result.stderr
    assert "release: t.dmg made with hdiutil (this macOS has no diskutil image)" in result.stdout
    assert not mounted_under(root)


def write_tool(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)


def fake_dmg_tools(
    root: Path, macos: str, diskutil: str, hdiutil: str
) -> tuple[dict[str, str], Path]:
    """A sw_vers, diskutil and hdiutil that log their calls; the env that puts them first."""
    bin_dir, calls = root / "fakebin", root / "calls.log"
    bin_dir.mkdir()
    note = f'echo "$(basename "$0") $*" >>"{calls}"\n'
    write_tool(
        bin_dir / "sw_vers",
        f"[[ ${{1:-}} == -productVersion ]] && echo {macos} && exit 0\n"
        'exec /usr/bin/sw_vers "$@"\n',
    )
    write_tool(bin_dir / "diskutil", note + diskutil)
    write_tool(bin_dir / "hdiutil", note + hdiutil)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "DISKUTIL": str(bin_dir / "diskutil"),
        "HDIUTIL": str(bin_dir / "hdiutil"),
    }
    return env, calls


MAKE_T_DMG = (
    'APP_NAME="Cloudy Reader"; make_dmg "$ROOT/dist/Cloudy Reader.app" "$ROOT/dist/t.dmg" 0.0.1'
)
TOUCH_LAST = 'touch "${@: -1}"\n'  # what a tool that made the image leaves: the file named last
# macOS 15 as the CI runner showed it: `diskutil image ... --help` exits 0, the verb is absent.
MACOS_15_DISKUTIL = (
    '[[ " $* " == *" --help "* ]] && exit 0\n'
    "echo 'diskutil: did not recognize verb \"image\"' >&2\nexit 1\n"
)


def test_the_dmg_uses_hdiutil_before_macos_26_even_when_diskutil_answers_help(root):
    fake_app(root)
    env, calls = fake_dmg_tools(root, "15.7.1", MACOS_15_DISKUTIL, TOUCH_LAST)

    result = bash_fn(root, MAKE_T_DMG, **env)

    assert result.returncode == 0, result.stderr
    assert "release: t.dmg made with hdiutil (this macOS has no diskutil image)" in result.stdout
    recorded = calls.read_text().splitlines()
    assert any(" -fs APFS -format ULFO " in line for line in recorded if "hdiutil create" in line)
    assert not any("image create" in line for line in recorded)


def test_the_dmg_uses_diskutil_image_from_macos_26(root):
    fake_app(root)
    diskutil = '[[ " $* " == *" --help "* ]] && exit 0\n' + TOUCH_LAST
    env, calls = fake_dmg_tools(root, "26.1", diskutil, "exit 1\n")

    result = bash_fn(root, MAKE_T_DMG, **env)

    assert result.returncode == 0, result.stderr
    recorded = calls.read_text().splitlines()
    assert any(
        "diskutil image create from --format ULFO --volumeName Cloudy Reader /" in line
        for line in recorded
    )
    assert not any(line.startswith("hdiutil") for line in recorded)


def test_a_failed_dmg_creation_prints_the_tools_own_message(root):
    fake_app(root)
    hdiutil = "echo 'hdiutil: create failed - Resource busy' >&2\nexit 1\n"
    env, _ = fake_dmg_tools(root, "15.7.1", MACOS_15_DISKUTIL, hdiutil)

    result = bash_fn(root, MAKE_T_DMG, **env)

    assert result.returncode == 1
    assert "hdiutil: create failed - Resource busy" in result.stderr
    assert "could not make t.dmg (log: build/dmg-create.log)" in result.stderr


FAKE_DISKUTIL = r"""#!/bin/bash
# `info -plist PATH`: a volume named FAKE_VOLUME on a disk whose bus is FAKE_BUS. Nothing else.
[[ ${1:-} == info && ${2:-} == -plist ]] || exit 1
printf '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
printf '<key>VolumeName</key><string>%s</string>' "${FAKE_VOLUME:-}"
printf '<key>BusProtocol</key><string>%s</string></dict></plist>\n' "${FAKE_BUS:-Disk Image}"
"""


def fake_diskutil(root: Path) -> str:
    fake = root / "fake-diskutil"
    fake.write_text(FAKE_DISKUTIL)
    fake.chmod(0o755)
    return str(fake)


@pytest.mark.parametrize(
    ("change", "volume", "message"),
    [
        (None, "Cloudy Reader", None),
        ("styled", "Cloudy Reader", None),  # dmgbuild's window layout and art
        ("README", "Cloudy Reader", "t.dmg: unexpected README on its volume"),
        ("no-link", "Cloudy Reader", "t.dmg: no Applications link to /Applications"),
        ("bad-link", "Cloudy Reader", "t.dmg: no Applications link to /Applications"),
        (None, "Cloudy Reader 0.0.1", "its volume is named 'Cloudy Reader 0.0.1', not 'Cloudy"),
    ],
)
def test_the_dmg_volume_holds_only_the_app_its_link_and_icon(root, change, volume, message):
    mnt = root / "volume"
    (mnt / "Cloudy Reader.app" / "Contents").mkdir(parents=True)
    (mnt / ".VolumeIcon.icns").write_bytes(b"icon")
    if change == "styled":
        (mnt / ".DS_Store").write_bytes(b"layout")
        (mnt / ".background.tiff").write_bytes(b"art")
    if change == "README":
        (mnt / "README").write_text("hi")
    if change != "no-link":
        (mnt / "Applications").symlink_to("/Applications" if change != "bad-link" else "/tmp")

    result = bash_fn(
        root,
        'APP_NAME="Cloudy Reader"; check_volume "$1" t.dmg',
        str(mnt),
        DISKUTIL=fake_diskutil(root),
        FAKE_VOLUME=volume,
    )

    if message is None:
        assert result.returncode == 0, result.stderr
        assert "release: t.dmg: verified; volume Cloudy Reader holds the app" in result.stdout
    else:
        assert result.returncode == 1
        assert message in result.stderr


ATTACHED = (
    "/dev/disk12  \tGUID_partition_scheme\n/dev/disk12s1\tApple_APFS\n"
    "/dev/disk13  \tApple_APFS_Container\n/dev/disk13s1\tApple_APFS_Volume\t/tmp/m\n"
)


@pytest.mark.parametrize(
    ("output", "bus", "device"),
    [(ATTACHED, "Disk Image", "/dev/disk12"), (ATTACHED, "Apple Fabric", None), ("", None, None)],
)
def test_only_a_confirmed_disk_image_may_be_ejected(root, output, bus, device):
    env = {"DISKUTIL": fake_diskutil(root)} | ({"FAKE_BUS": bus} if bus else {})

    result = bash_fn(root, 'image_device "$1"', output, **env)

    if device:
        assert result.returncode == 0, result.stderr
        assert result.stdout == f"{device}\n"
    else:
        assert result.returncode != 0
        assert result.stdout == ""


FAKE_PY = r"""#!/bin/bash
# The build venv's Python: has dmgbuild when FAKE_DMGBUILD=1, and "runs" dmg_layout.py by writing
# its arguments to FAKE_OUT and a stand-in image to the DMG path.
if [[ $1 == -I && $2 == -c ]]; then [[ ${FAKE_DMGBUILD:-0} == 1 ]]; exit; fi
if [[ $1 == -I && $2 == */packaging/dmg_layout.py ]]; then
  shift 2; printf '%s\n' "$@" >"$FAKE_OUT"; echo image >"$2"; exit 0
fi
exit 1
"""


@pytest.mark.parametrize("dmgbuild", ["1", "0"])
def test_make_dmg_styles_the_window_when_the_build_venv_has_dmgbuild(root, dmgbuild):
    fake_app(root)
    python = root / "fake-python"
    python.write_text(FAKE_PY)
    python.chmod(0o755)
    snippet = (
        'APP_NAME="Cloudy Reader"; create_dmg() { echo "plain image named $3"; }; '
        'make_dmg "$ROOT/dist/Cloudy Reader.app" "$ROOT/dist/t.dmg"'
    )
    out = root / "layout.args"

    result = bash_fn(root, snippet, PY=str(python), FAKE_DMGBUILD=dmgbuild, FAKE_OUT=str(out))

    assert result.returncode == 0, result.stderr
    if dmgbuild == "1":
        app, dmg = out.read_text().splitlines()[:2]
        assert re.fullmatch(rf"{re.escape(str(root))}/build/dmg-stage\.\w+/Cloudy Reader\.app", app)
        assert dmg == str(root / "dist" / "t.dmg")
        assert "release: t.dmg: the window styled by dmgbuild" in result.stdout
    else:
        assert not out.exists()
        assert "plain image named Cloudy Reader" in result.stdout
        assert "release: t.dmg is plain: dmgbuild is not in the build venv" in result.stdout


def test_release_preflight_needs_the_dmg_tools(root):
    fake_venv(root)

    result = bash_fn(root, "release_preflight 0.0.1", FAKE_META="0.0.1", HDIUTIL="no-hdiutil")

    assert result.returncode == 1
    assert "no-hdiutil not found: the release DMG needs it" in result.stderr


# --- the figures a publish step reads ------------------------------------------------------------


PLANNING_APP = r"""#!/bin/bash
# A built app in the plan probe: logs its probe env, then prints FAKE_PLAN, or a skip and exit 3.
printf '%s\n' "$CLOUDYREADER_PROBE" "$CLOUDYREADER_DATA_DIR" "$CLOUDYREADER_OFFLINE" >"$FAKE_ARGS"
if [[ -n ${FAKE_SKIP:-} ]]; then
  echo "plan: skips $FAKE_SKIP" >&2
  exit 3
fi
if [[ -n ${FAKE_FAIL:-} ]]; then
  echo "plan: failed: $FAKE_FAIL" >&2
  exit 2
fi
echo "${FAKE_PLAN-3046503217}"
"""


def release_files(root: Path) -> int:
    """A dist app that answers the plan probe, the zip and the DMG beside it, each with its hash.

    Returns the app's regular-file bytes: the APP_BYTES the figures step must write."""
    contents = root / "dist" / "Cloudy Reader.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "MacOS" / "Cloudy Reader").write_text(PLANNING_APP)
    (contents / "MacOS" / "Cloudy Reader").chmod(0o755)
    (contents / "a").write_bytes(b"abc")
    (contents / "link").symlink_to("a")  # a link counts nothing
    for name, data in ((ZIP, b"zip bytes"), (DMG, b"dmg image bytes")):
        (root / "dist" / name).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        (root / "dist" / f"{name}.sha256").write_text(f"{digest}  {name}\n")
    return 3 + len(PLANNING_APP.encode())


def figures(root: Path, out: Path, **env: str) -> subprocess.CompletedProcess[str]:
    inherited = {k: v for k, v in os.environ.items() if k not in ("OUT", "APP_NAME")}
    args = {"FAKE_ARGS": str(root / "plan.args")}
    return subprocess.run(
        ["/bin/bash", str(root / "scripts" / "build_app.sh"), "figures", "0.0.1", str(out)],
        capture_output=True,
        text=True,
        check=False,
        env=inherited | args | env,
    )


def test_figures_writes_six_plain_lines_once_every_file_matches(root):
    app_bytes = release_files(root)
    out = root / "figures.txt"

    result = figures(root, out)

    assert result.returncode == 0, result.stderr
    assert out.read_text().splitlines() == [
        f"APP_BYTES={app_bytes}",
        "ZIP_BYTES=9",
        f"SHA256={hashlib.sha256(b'zip bytes').hexdigest()}",
        "DMG_BYTES=15",
        f"DMG_SHA256={hashlib.sha256(b'dmg image bytes').hexdigest()}",
        "DOWNLOAD_BYTES=3046503217",
    ]
    probe, data, offline = (root / "plan.args").read_text().splitlines()
    assert (probe, offline) == ("plan", "1")  # the app's own plan, with no network
    assert re.fullmatch(rf"{re.escape(str(root))}/build/figures-data\.\w+", data)
    assert not any(Path(data).iterdir())  # an empty data folder: a first launch


@pytest.mark.parametrize("plan", ["0", "", "Traceback (most recent call last):"])
def test_figures_writes_nothing_when_the_first_launch_plan_downloads_nothing(root, plan):
    release_files(root)
    out = root / "figures.txt"

    result = figures(root, out, FAKE_PLAN=plan)

    assert result.returncode == 1
    assert "the first-launch plan downloads nothing" in result.stderr
    assert not out.exists()


def test_figures_stop_when_this_mac_skips_a_group_the_app_holds(root):
    release_files(root)
    out = root / "figures.txt"
    skipped = "kokoro: not enough disk space: needs 1.5 GB, 0.9 GB free"

    result = figures(root, out, FAKE_SKIP=skipped)

    assert result.returncode == 1
    assert f"plan: skips {skipped}" in result.stderr
    assert "so DOWNLOAD_BYTES would undercount" in result.stderr
    assert not out.exists()


def test_figures_stop_with_the_reason_when_the_plan_probe_fails(root):
    release_files(root)
    out = root / "figures.txt"

    result = figures(root, out, FAKE_FAIL="OSError: lock unreadable")

    assert result.returncode == 1
    assert "plan: failed: OSError: lock unreadable" in result.stderr
    assert "the app's plan probe exited 2" in result.stderr
    assert not out.exists()


def test_figures_writes_nothing_when_a_file_disagrees_with_its_checksum(root):
    release_files(root)
    (root / "dist" / DMG).write_bytes(b"changed")
    out = root / "figures.txt"

    result = figures(root, out)

    assert result.returncode == 1
    assert f"{DMG} does not match its .sha256" in result.stderr
    assert not out.exists()


DMG_TOOLS = {"dmgbuild": "1.6.7", "ds-store": "1.3.3", "mac-alias": "2.2.3"}


def test_the_dmg_tools_are_pinned_build_only_wheels():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())

    packaging = project["dependency-groups"]["packaging"]
    assert {f"{name}=={version}" for name, version in DMG_TOOLS.items()} <= set(packaging)
    assert sorted(project["tool"]["uv"]["no-build-package"]) == sorted(DMG_TOOLS)
    runtime = " ".join(project["project"]["dependencies"])
    assert not [name for name in DMG_TOOLS if name in runtime]  # build only, never in the app
    locked = {p["name"]: p for p in lock["package"] if p["name"] in DMG_TOOLS}
    assert {name: p["version"] for name, p in locked.items()} == DMG_TOOLS
    for package in locked.values():  # a hash-pinned wheel from public PyPI for each
        assert package["source"] == {"registry": "https://pypi.org/simple"}
        assert package["wheels"]
        assert all(wheel["hash"].startswith("sha256:") for wheel in package["wheels"])
