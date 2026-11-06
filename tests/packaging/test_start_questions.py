"""Packaging: START_QUESTIONS bundles the test-fixture questions in a dev build, never a release."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from cloudyreader.start_question import BUNDLED_DIR
from tests.packaging.test_build_app import bash_fn
from tests.packaging.test_build_engines import spec
from tests.packaging.test_build_warnings import FAKE_PYINSTALLER
from tests.packaging.test_engines_ship import recipe
from tests.packaging.test_release import NO_DMG, NO_GATE, fake_app, host_assets, stub_codesign

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_app.sh"
FIXTURES = ROOT / "tests" / "fixtures"
# What a parent make hands its children; a test's own make must not inherit the gate's overrides.
MAKE_ENV = ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL", "START_QUESTIONS")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A throwaway repo root holding a copy of the script, like test_build_app's fake_root."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "build_app.sh")
    shutil.copy(ROOT / "assets.lock.json", tmp_path / "assets.lock.json")
    (tmp_path / "dist").mkdir()
    (tmp_path / "build").mkdir()
    return tmp_path.resolve()


# --- packaging/CloudyReader.spec ------------------------------------------------------------------


def bundled(seen: dict) -> list[tuple[str, str]]:
    """The data entries the spec put under the bundled copy's folder."""
    return [entry for entry in seen["Analysis"]["datas"] if entry[1].split("/")[0] == BUNDLED_DIR]


def test_the_spec_bundles_every_fixture_file_with_the_switch(monkeypatch):
    seen = spec(monkeypatch, CR_START_QUESTIONS="1")

    questions = sorted((FIXTURES / "questions").glob("*.txt"))
    want = [(str(path), f"{BUNDLED_DIR}/questions") for path in questions]
    want.append((str(FIXTURES / "tossup_earth_science.txt"), BUNDLED_DIR))
    assert bundled(seen) == want
    assert len(questions) > 1 and all(Path(src).is_file() for src, _ in want)
    assert all(src.endswith(".txt") for src, _ in bundled(seen))
    # Inside the bundle a file is named by its folder only: no build path goes in.
    assert all(not dest.startswith("/") for _, dest in want)


def test_the_spec_bundles_only_the_txt_files(monkeypatch, tmp_path):
    # Finder leaves a git-ignored .DS_Store in tests/fixtures: it must never reach the app.
    (tmp_path / "packaging").mkdir()
    for rel in ("pyproject.toml", "packaging/CloudyReader.spec", "packaging/min_macos.py"):
        shutil.copy(ROOT / rel, tmp_path / rel)
    fixtures = tmp_path / "tests" / "fixtures"
    (fixtures / "questions").mkdir(parents=True)
    for rel in (
        "questions/01.txt",
        "questions/.DS_Store",
        "questions/notes.md",
        ".DS_Store",
        "other.txt",
        "tossup_earth_science.txt",
    ):
        (fixtures / rel).write_text("x")
    monkeypatch.setattr(
        "tests.packaging.test_build_engines.SPEC", tmp_path / "packaging" / "CloudyReader.spec"
    )

    seen = spec(monkeypatch, CR_START_QUESTIONS="1")

    assert bundled(seen) == [
        (str(fixtures / "questions" / "01.txt"), f"{BUNDLED_DIR}/questions"),
        (str(fixtures / "tossup_earth_science.txt"), BUNDLED_DIR),
    ]


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"CR_START_QUESTIONS": "0"},
        {"CR_START_QUESTIONS": "yes"},
        # A release build: the engines on, START_QUESTIONS=0 as build_app.sh hands it over.
        {"CR_KOKORO": "1", "CR_ENGINES": "1", "CR_START_QUESTIONS": "0"},
    ],
)
def test_the_spec_bundles_no_fixture_otherwise(monkeypatch, env):
    monkeypatch.delenv("CR_START_QUESTIONS", raising=False)

    seen = spec(monkeypatch, **env)

    assert bundled(seen) == []
    assert not [src for src, _ in seen["Analysis"]["datas"] if "fixtures" in src]


# --- scripts/build_app.sh -------------------------------------------------------------------------


def resolve(root: Path, *value: str) -> subprocess.CompletedProcess[str]:
    env = {"START_QUESTIONS": value[0]} if value else {}
    return bash_fn(
        root, 'resolve_start_questions && echo "START_QUESTIONS=$START_QUESTIONS"', **env
    )


def test_the_build_script_alone_bundles_no_fixture(root, monkeypatch):
    monkeypatch.delenv("START_QUESTIONS", raising=False)

    for result in (resolve(root), resolve(root, "")):  # unset or empty: the default
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["START_QUESTIONS=0"]


@pytest.mark.parametrize("value", ["0", "1"])
def test_the_build_script_takes_0_or_1(root, value):
    result = resolve(root, value)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"START_QUESTIONS={value}"]


@pytest.mark.parametrize("value", ["yes", "true", "2"])
def test_the_build_script_refuses_anything_else(root, value):
    result = resolve(root, value)

    assert result.returncode == 1
    assert f"START_QUESTIONS must be 0 or 1, got '{value}'" in result.stderr


@pytest.mark.parametrize("value", ["0", "1"])
def test_build_bundle_hands_the_switch_to_the_spec(root, value):
    fake = root / "fake"
    fake.mkdir()
    (fake / "lines").write_text("")
    (fake / "pyinstaller").write_text(FAKE_PYINSTALLER)
    (fake / "pyinstaller").chmod(0o755)
    snippet = (
        'PY="$1"; PYI=("$2"); ENTRY=app; KOKORO=0; ENTRY_SCRIPT=launcher.py; ICON_PATH=; '
        'APP_NAME="Cloudy Reader"; SPEC=CloudyReader.spec; '
        'STAGE_APP="$ROOT/build/dist/$APP_NAME.app"; resolve_start_questions && build_bundle'
    )

    result = bash_fn(
        root,
        snippet,
        sys.executable,
        str(fake / "pyinstaller"),
        FAKE_OUT=str(fake),
        START_QUESTIONS=value,
    )

    assert result.returncode == 0, result.stderr
    assert f"CR_START_QUESTIONS={value}" in (fake / "env").read_text().splitlines()


def test_the_release_audit_passes_a_bundle_without_fixtures(root):
    result = bash_fn(root, 'audit_start_questions "$1"', str(fake_app(root)))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "build_app: start-question audit: no test-fixture question in the bundle"
    ]


@pytest.mark.parametrize(
    "rel", [f"Contents/Resources/{BUNDLED_DIR}", f"Contents/Frameworks/{BUNDLED_DIR}"]
)
def test_the_release_audit_fails_on_bundled_fixtures(root, rel):
    app = fake_app(root)
    (app / rel).parent.mkdir(parents=True, exist_ok=True)
    (app / rel).symlink_to("elsewhere")  # even a dangling link counts

    result = bash_fn(root, 'audit_start_questions "$1"', str(app))

    assert result.returncode == 1
    assert f"test-fixture questions in the bundle (a release ships none): {rel}" in result.stderr


def test_release_refuses_a_dev_build_that_bundles_the_fixtures(root):
    host_assets(root)
    app = fake_app(root)
    (app / "Contents" / "Resources" / BUNDLED_DIR / "questions").mkdir(parents=True)
    (app / "Contents" / "Resources" / BUNDLED_DIR / "questions" / "01.txt").write_text("x")
    path, _ = stub_codesign(root)

    result = bash_fn(
        root, f'APP_NAME="Cloudy Reader"; {NO_GATE}{NO_DMG}release_main 0.0.1', PATH=path
    )

    assert result.returncode == 1
    assert "test-fixture questions in the bundle (a release ships none)" in result.stderr
    assert not list((root / "dist").glob("*.dmg"))


# --- Makefile -------------------------------------------------------------------------------------


def make(*args: str) -> subprocess.CompletedProcess[str]:
    # UV=false: should a recipe ever get past its checks here, it fails instead of running uv.
    env = {k: v for k, v in os.environ.items() if k not in MAKE_ENV}
    return subprocess.run(
        ["make", "--no-print-directory", "-C", str(ROOT), "UV=false", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def builds(dry: subprocess.CompletedProcess[str]) -> list[str]:
    """The build_app.sh calls a dry run printed: `make -n` prints commands and runs none."""
    assert dry.returncode == 0, dry.stderr
    return [line for line in dry.stdout.splitlines() if "bash scripts/build_app.sh;" in line]


def test_make_app_bundles_the_fixtures_by_default():
    [build] = builds(make("-n", "app"))

    assert 'START_QUESTIONS="1"' in build


def test_make_app_start_questions_0_bundles_none():
    [build] = builds(make("-n", "app", "START_QUESTIONS=0"))

    assert 'START_QUESTIONS="0"' in build


@pytest.mark.parametrize("asked", [(), ("START_QUESTIONS=1",)])
def test_make_release_never_bundles_the_fixtures(asked):
    lines = builds(make("-n", "release", "VERSION=0.0.1", *asked))

    assert lines and all('START_QUESTIONS="0"' in line for line in lines)


def test_make_app_checks_the_switch_and_hands_it_to_the_build_script():
    app = recipe("app")

    assert "START_QUESTIONS must be 0 or 1 (got '$(START_QUESTIONS)')" in app
    assert 'START_QUESTIONS="$(START_QUESTIONS)"' in app
    assert "START_QUESTIONS=0" in recipe("release")


def test_make_help_documents_the_switch():
    result = make("help")

    assert result.returncode == 0, result.stderr
    rows = {line.split()[0]: line for line in result.stdout.splitlines() if line.strip()}
    assert rows["START_QUESTIONS"].endswith("(default: 1)")
    assert "START_QUESTIONS=1|0" in rows["app"]
