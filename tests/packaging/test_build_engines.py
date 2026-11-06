"""Packaging (P9): the ENGINES switch of build_app.sh, its engine probe, the spec, the launcher."""

from __future__ import annotations

import importlib.util
import json
import runpy
import shutil
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tests.packaging.test_build_app import bash_fn

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_app.sh"
SPEC = ROOT / "packaging" / "CloudyReader.spec"
LAUNCHER = ROOT / "packaging" / "launcher.py"
ENGINE_PACKAGES = (
    "mlx_audio.tts.models.chatterbox_turbo",
    "mlx_audio.tts.models.qwen3_tts",
    "transformers.models.auto",
    "transformers.models.qwen2",
    "transformers.models.gpt2",
)
# The app's engine modules: engine_catalog imports them by name, so the spec must list them.
ENGINE_MODULES = ("cloudyreader.engines.chatterbox_turbo", "cloudyreader.engines.qwen3_tts")
# What transformers checks at import (blueprint section 6: the first real probe may add more).
METADATA = (
    "transformers",
    "tokenizers",
    "huggingface-hub",
    "safetensors",
    "regex",
    "packaging",
    "tqdm",
    "numpy",
    "pyyaml",
    "filelock",
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A throwaway repo root holding a copy of the script, like test_build_app's fake_root."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "build_app.sh")
    (tmp_path / "build").mkdir()
    return tmp_path.resolve()


# --- packaging/launcher.py ------------------------------------------------------------------------


def load_launcher() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("cloudyreader_launcher", LAUNCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("value", "runs"),
    [(None, "app"), ("", "app"), ("1", "app"), ("Engines", "app"), ("engines", "probe")],
)
def test_launcher_runs_the_probe_only_when_asked(monkeypatch, value, runs):
    for name, result in (
        ("cloudyreader.__main__", "app"),
        ("cloudyreader.engines.bundle_probe", "probe"),
    ):
        module = types.ModuleType(name)
        module.main = lambda result=result: result  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, name, module)
    if value is None:
        monkeypatch.delenv("CLOUDYREADER_PROBE", raising=False)
    else:
        monkeypatch.setenv("CLOUDYREADER_PROBE", value)

    assert load_launcher().run() == runs


def test_launcher_exits_with_what_it_ran(monkeypatch):
    probe = types.ModuleType("cloudyreader.engines.bundle_probe")
    probe.main = lambda: 3  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cloudyreader.engines.bundle_probe", probe)
    monkeypatch.setenv("CLOUDYREADER_PROBE", "engines")

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(LAUNCHER), run_name="__main__")

    assert exc.value.code == 3


# --- scripts/build_app.sh: which engines go in --------------------------------------------------


def resolve(root: Path, engines: str, kokoro: str, *pinned: str):
    """resolve_engines over a lock whose assets carry the voice groups plus `pinned` groups."""
    assets = [{"group": group} for group in ("voices", "kokoro", *pinned)]
    (root / "assets.lock.json").write_text(json.dumps({"version": 1, "assets": assets}))
    snippet = 'KOKORO="$1" PY="$2" && resolve_engines && echo "BUILD_ENGINES=$BUILD_ENGINES"'
    return bash_fn(root, snippet, kokoro, sys.executable, ENGINES=engines)


def build_staged(root: Path, engines: str, build_engines: str, probe_passes: bool):
    """build_staged with stand-ins: each build prints its CR_ENGINES; the probe passes or not."""
    snippet = (
        'build_bundle() { echo "build CR_ENGINES=$BUILD_ENGINES"; }; '
        f"probe_engines() {{ echo probed; return {0 if probe_passes else 1}; }}; "
        f"BUILD_ENGINES={build_engines} && build_staged && "
        'echo "engines in: $BUILD_ENGINES"'
    )
    return bash_fn(root, snippet, ENGINES=engines)


def test_resolve_engines_auto_needs_kokoro_pinned_weights_and_a_passing_probe(root):
    for pinned in (("chatterbox_turbo",), ("qwen3_tts",), ("chatterbox_turbo", "qwen3_tts")):
        assert resolve(root, "auto", "1", *pinned).stdout.splitlines()[-1] == "BUILD_ENGINES=1"
    skipped = resolve(root, "auto", "0", "chatterbox_turbo")
    assert skipped.stdout.splitlines()[-1] == "BUILD_ENGINES=0"
    assert "engines: not tried: they ride the kokoro extra (KOKORO=0)" in skipped.stdout
    unpinned = resolve(root, "auto", "1")
    assert unpinned.returncode == 0, unpinned.stderr
    assert unpinned.stdout.splitlines() == [
        "build_app: engines: not tried: assets.lock.json pins no engine weights (make pin-engine)",
        "BUILD_ENGINES=0",
    ]

    kept = build_staged(root, "auto", "1", probe_passes=True)
    assert kept.returncode == 0, kept.stderr
    assert kept.stdout.splitlines() == [
        "build CR_ENGINES=1",
        "probed",
        "build_app: engines: the probe passed: engines stay in",
        "engines in: 1",
    ]

    dropped = build_staged(root, "auto", "1", probe_passes=False)
    assert dropped.returncode == 0, dropped.stderr
    assert dropped.stdout.splitlines() == [
        "build CR_ENGINES=1",
        "probed",
        "build_app: engines: the probe failed (above): rebuilding without them",
        "build CR_ENGINES=0",
        "engines in: 0",
    ]


@pytest.mark.parametrize(
    ("engines", "kokoro", "built"),
    [("0", "1", "BUILD_ENGINES=0"), ("0", "0", "BUILD_ENGINES=0"), ("1", "1", "BUILD_ENGINES=1")],
)
def test_resolve_engines_0_never_and_1_always(root, engines, kokoro, built):
    result = resolve(root, engines, kokoro)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == built


@pytest.mark.parametrize(
    ("engines", "kokoro", "message"),
    [
        ("1", "0", "ENGINES=1 needs KOKORO=1: the engines ride the kokoro extra"),
        ("yes", "1", "ENGINES must be auto, 0 or 1, got 'yes'"),
    ],
)
def test_resolve_engines_refuses_what_cannot_build(root, engines, kokoro, message):
    result = resolve(root, engines, kokoro)

    assert result.returncode == 1
    assert message in result.stderr


def test_engines_1_dies_when_the_probe_fails_and_0_never_probes(root):
    forced = build_staged(root, "1", "1", probe_passes=False)
    assert forced.returncode == 1
    assert "ENGINES=1 but the engine probe failed (log: build/engines-probe.log)" in forced.stderr
    assert forced.stdout.splitlines() == ["build CR_ENGINES=1", "probed"]

    never = build_staged(root, "0", "0", probe_passes=True)
    assert never.stdout.splitlines() == ["build CR_ENGINES=0", "engines in: 0"]


FAKE_APP = r"""#!/bin/bash
{
  echo "CLOUDYREADER_PROBE=$CLOUDYREADER_PROBE"
  echo "CLOUDYREADER_OFFLINE=$CLOUDYREADER_OFFLINE"
  echo "HF_HUB_OFFLINE=$HF_HUB_OFFLINE"
} >"$PROBE_ENV_OUT"
echo "ok transformers"
if [[ -n ${PROBE_FAIL:-} ]]; then echo "FAIL $PROBE_FAIL: ModuleNotFoundError: gone"; exit 1; fi
echo "ok tokenizers"
"""


def test_probe_engines_runs_the_staged_app_offline_and_shows_the_failing_imports(root):
    macos = root / "build" / "dist" / "Cloudy Reader.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (macos / "Cloudy Reader").write_text(FAKE_APP)
    (macos / "Cloudy Reader").chmod(0o755)
    snippet = 'APP_NAME="Cloudy Reader"; STAGE_APP="$ROOT/build/dist/$APP_NAME.app"; probe_engines'
    env_out = root / "probe-env.txt"

    passed = bash_fn(root, snippet, PROBE_ENV_OUT=str(env_out))
    assert passed.returncode == 0, passed.stderr
    assert env_out.read_text().splitlines() == [
        "CLOUDYREADER_PROBE=engines",
        "CLOUDYREADER_OFFLINE=1",
        "HF_HUB_OFFLINE=1",
    ]
    assert "FAIL" not in passed.stdout

    failed = bash_fn(root, snippet, PROBE_ENV_OUT=str(env_out), PROBE_FAIL="tokenizers")
    assert failed.returncode == 1
    assert "build_app:   FAIL tokenizers: ModuleNotFoundError: gone" in failed.stdout.splitlines()
    assert "ok transformers" not in failed.stdout  # only the failing imports are shown
    assert "full output: build/engines-probe.log" in failed.stdout
    assert "ok transformers" in (root / "build" / "engines-probe.log").read_text()


# --- scripts/build_app.sh: bundle growth --------------------------------------------------------


def test_engine_growth_sums_only_the_engines_own_folders(root):
    contents = root / "Cloudy Reader.app" / "Contents"
    sizes = {
        "Resources/transformers/models/qwen2/modeling_qwen2.py": 1_000_000,  # ships with Kokoro
        "Frameworks/tokenizers/tokenizers.abi3.so": 2_000_000,  # ships with Kokoro
        "Resources/mlx_audio/tts/models/chatterbox_turbo/chatterbox_turbo.py": 300_000,
        "Resources/mlx_audio/tts/models/qwen3_tts/speech_tokenizer.py": 700_000,
        "Resources/mlx_audio/tts/models/kokoro/kokoro.py": 9_000_000,  # not an engine folder
    }
    for rel, size in sizes.items():
        (contents / rel).parent.mkdir(parents=True, exist_ok=True)
        (contents / rel).write_bytes(bytes(size))
    mirror = contents / "Frameworks" / "mlx_audio" / "tts" / "models" / "qwen3_tts"
    mirror.mkdir(parents=True)
    (mirror / "speech_tokenizer.py").symlink_to(
        "../../../../../Resources/mlx_audio/tts/models/qwen3_tts/speech_tokenizer.py"
    )

    result = bash_fn(root, 'engine_growth "$1"', str(contents))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "build_app: engine folders: 1.0 MB in 3 folders",
        "build_app:       0.0 MB  Frameworks/mlx_audio/tts/models/qwen3_tts",  # symlinks only
        "build_app:       0.3 MB  Resources/mlx_audio/tts/models/chatterbox_turbo",
        "build_app:       0.7 MB  Resources/mlx_audio/tts/models/qwen3_tts",
    ]


# --- packaging/CloudyReader.spec ------------------------------------------------------------------


def spec(monkeypatch: pytest.MonkeyPatch, **env: str) -> dict[str, Any]:
    """Run the spec on stand-ins for PyInstaller; what each hook helper and Analysis received."""
    seen: dict[str, Any] = {"collect_all": [], "collect_submodules": [], "copy_metadata": []}

    def collect_all(package: str, **kw: Any) -> tuple[list, list, list]:
        seen["collect_all"].append(package)
        return [], [], []

    def collect_submodules(package: str, **kw: Any) -> list[str]:
        seen["collect_submodules"].append(package)
        return [f"{package}.sub"]

    def copy_metadata(dist: str, **kw: Any) -> list[tuple[str, str]]:
        seen["copy_metadata"].append(dist)
        return []

    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_all = collect_all  # type: ignore[attr-defined]
    hooks.collect_submodules = collect_submodules  # type: ignore[attr-defined]
    hooks.copy_metadata = copy_metadata  # type: ignore[attr-defined]
    hooks.collect_data_files = lambda package, **kw: []  # type: ignore[attr-defined]
    for name in ("PyInstaller", "PyInstaller.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    for key in ("CR_ENTRY", "CR_APP_NAME", "CR_ICON", "CR_KOKORO", "CR_ENGINES"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    toc = types.SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    def recorder(kind: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            seen[kind] = kwargs
            return toc

        return call

    namespace = {"SPECPATH": str(SPEC.parent)}
    namespace |= {k: recorder(k) for k in ("Analysis", "PYZ", "EXE", "COLLECT", "BUNDLE")}
    exec(compile(SPEC.read_text(), str(SPEC), "exec"), namespace)
    return seen


def test_spec_collects_the_engine_modules_with_engines_and_kokoro(monkeypatch):
    seen = spec(monkeypatch, CR_KOKORO="1", CR_ENGINES="1")

    hidden = seen["Analysis"]["hiddenimports"]
    assert all(f"{package}.sub" in hidden for package in ENGINE_PACKAGES)
    assert set(ENGINE_MODULES) <= set(hidden)  # the catalog imports them by name only
    assert "tokenizers" in seen["collect_all"]
    assert set(METADATA) <= set(seen["copy_metadata"])


@pytest.mark.parametrize("env", [{"CR_KOKORO": "1"}, {"CR_ENGINES": "1"}, {}])
def test_spec_leaves_the_engines_out_otherwise(monkeypatch, env):
    seen = spec(monkeypatch, **env)

    assert not set(ENGINE_PACKAGES) & set(seen["collect_submodules"])
    assert not set(ENGINE_MODULES) & set(seen["Analysis"]["hiddenimports"])
    assert "tokenizers" not in seen["collect_all"]
    assert "safetensors" not in seen["copy_metadata"]
