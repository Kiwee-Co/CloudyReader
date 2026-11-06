"""Packaging (P9): the engine Make targets."""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"


def make(*args: str) -> subprocess.CompletedProcess[str]:
    # UV=false: should a recipe ever get past its checks here, it fails instead of running uv.
    return subprocess.run(
        ["make", "--no-print-directory", "-C", str(ROOT), "UV=false", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def recipe(target: str) -> str:
    """The rule line and recipe lines of one Makefile target, as written."""
    lines = MAKEFILE.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    end = next((i for i in range(start + 1, len(lines)) if not lines[i].startswith("\t")), None)
    return "\n".join(lines[start:end])


# --- Makefile -------------------------------------------------------------------------------------


def test_make_help_lists_pin_engine_and_smoke_engines():
    result = make("help")

    assert result.returncode == 0, result.stderr
    rows = {line.split()[0]: line for line in result.stdout.splitlines() if line.strip()}
    assert "ENGINE=" in rows["pin-engine"] and "never in ci" in rows["pin-engine"]
    assert "never in ci" in rows["smoke-engines"]
    assert "chatterbox_turbo" in rows["ENGINE"]
    assert rows["ENGINES"].endswith("(default: auto)")
    assert "ENGINES=auto|0|1" in rows["app"]


def test_engine_targets_never_run_in_make_ci():
    dry = make("-n", "ci")  # prints every command of check, test and precommit; runs none

    assert dry.returncode == 0, dry.stderr
    for name in ("pin-engine", "smoke-engines", "pin_engine_assets", "live_smoke_engines"):
        assert name not in dry.stdout


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((), "usage: make pin-engine ENGINE=chatterbox_turbo|qwen3_tts"),
        (("ENGINE=bogus",), "ENGINE must be chatterbox_turbo or qwen3_tts (got 'bogus')"),
    ],
)
def test_pin_engine_needs_a_known_engine(args, message):
    result = make("pin-engine", *args)  # stops at the check, before any network

    assert result.returncode != 0
    assert message in result.stderr


def test_engine_targets_run_their_scripts_frozen_and_offline():
    pin, smoke = recipe("pin-engine"), recipe("smoke-engines")

    assert "$(UV_RUN) $(PYTHON) scripts/pin_engine_assets.py $(ENGINE) --write --install" in pin
    assert "$(UV_RUN) $(PYTHON) scripts/live_smoke_engines.py" in smoke
    assert "UV_RUN = $(UV) run --frozen --offline" in MAKEFILE.read_text()
    # Both use the repo's .data, like `make run`: the pin installs there, the smoke reads there.
    export = next(
        line for line in MAKEFILE.read_text().splitlines() if "export CLOUDYREADER_DATA_DIR" in line
    )
    assert {"pin-engine", "smoke-engines"} <= set(export.split(":", 1)[0].split())


def test_make_app_hands_engines_to_the_build_script():
    app = recipe("app")

    assert 'ENGINES="$(ENGINES)"' in app
    assert "ENGINES must be auto, 0 or 1 (got '$(ENGINES)')" in app


def test_release_leaves_the_engines_out_even_when_asked_for_them():
    dry = make("-n", "release", "VERSION=0.0.1", "ENGINES=auto")  # prints the commands, runs none

    assert dry.returncode == 0, dry.stderr
    builds = [line for line in dry.stdout.splitlines() if "bash scripts/build_app.sh;" in line]
    assert builds and all('ENGINES="0"' in line for line in builds)


def test_real_engine_tests_are_marked_model_and_slow():
    module = importlib.import_module("tests.engines_real.test_engines_real")

    assert {mark.name for mark in module.pytestmark} == {"model", "slow"}
