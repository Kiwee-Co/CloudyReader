"""Packaging (R1): the lean bundle, its voice audit, its self-tests, and the release zip."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
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


def test_release_zips_checksums_and_verifies_the_extracted_copy(root):
    host_assets(root)
    fake_app(root)
    path, args = stub_codesign(root)

    result = bash_fn(root, 'APP_NAME="Cloudy Reader"; release_main 0.0.1', PATH=path)

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

    result = bash_fn(root, 'APP_NAME="Cloudy Reader"; release_main 0.0.1', PATH=path)

    assert result.returncode == 0, result.stderr
    kept = list((root / "build").glob(f"trash.*/{ZIP}"))
    assert [p.read_bytes() for p in kept] == [b"older build"]
