"""cloudyreader/engines/bundle_probe.py: one line per engine import and the Qwen gate's file."""

from __future__ import annotations

import importlib.machinery
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from cloudyreader.engines import bundle_probe

IMPORTS = (
    "transformers",
    "tokenizers",
    "transformers.models.auto",
    "transformers.models.qwen2",
    "transformers.models.gpt2",
    "mlx_audio.tts.models.chatterbox_turbo",
    "mlx_audio.tts.models.qwen3_tts",
)
GATE = "qwen3_tts speech_tokenizer.py"
DECODER = "cloudyreader.engines.qwen3_decoder"
ENGINES = ("chatterbox_turbo", "qwen3_tts")
SUPPORTED = tuple(f"{engine} supported()" for engine in ENGINES)


@pytest.fixture
def fakes(monkeypatch, tmp_path) -> Path:
    """Every probed module as a stub; mlx_audio as a package that holds the gate's file."""
    package = tmp_path / "mlx_audio"
    source = package / "tts" / "models" / "qwen3_tts" / "speech_tokenizer.py"
    source.parent.mkdir(parents=True)
    source.write_text("# decoder\n")
    spec = importlib.machinery.ModuleSpec("mlx_audio", None, is_package=True)
    spec.submodule_search_locations = [str(package)]
    mlx_audio = types.ModuleType("mlx_audio")
    mlx_audio.__spec__ = spec
    monkeypatch.setitem(sys.modules, "mlx_audio", mlx_audio)
    for name in IMPORTS:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    for engine in ENGINES:
        module = types.ModuleType(f"cloudyreader.engines.{engine}")
        module.supported = lambda: None  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setitem(sys.modules, DECODER, None)  # the probe's own lookup, not the gate's
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    return source


def test_bundle_probe_reports_each_import_and_fails_on_a_missing_one(fakes, monkeypatch, capsys):
    assert bundle_probe.main([]) == 0
    assert capsys.readouterr().out.splitlines() == [
        *(f"ok {name}" for name in SUPPORTED),
        *(f"ok {name}" for name in IMPORTS),
        f"ok {GATE}",
    ]
    assert os.environ["HF_HUB_OFFLINE"] == "1"  # set before the first import

    monkeypatch.setitem(sys.modules, "transformers.models.qwen2", None)  # its import now fails

    assert bundle_probe.main([]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[5].startswith("FAIL transformers.models.qwen2: ModuleNotFoundError: ")
    assert [line for line in lines if line.startswith("FAIL")] == [lines[5]]  # the rest still ran


def test_bundle_probe_fails_when_an_engine_is_not_supported(fakes, monkeypatch, capsys):
    qwen3 = sys.modules["cloudyreader.engines.qwen3_tts"]
    monkeypatch.setattr(qwen3, "supported", lambda: "not in this build")

    assert bundle_probe.main([]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == [f"ok {SUPPORTED[0]}", f"FAIL {SUPPORTED[1]}: not in this build"]
    assert len(lines) == 2 + len(IMPORTS) + 1  # the imports and the gate still ran

    def broken() -> str | None:
        raise RuntimeError("no finder")

    monkeypatch.setattr(sys.modules["cloudyreader.engines.chatterbox_turbo"], "supported", broken)
    monkeypatch.setitem(sys.modules, "cloudyreader.engines.qwen3_tts", None)  # import fails

    assert bundle_probe.main([]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"FAIL {SUPPORTED[0]}: RuntimeError: no finder"
    assert lines[1].startswith(f"FAIL {SUPPORTED[1]}: ModuleNotFoundError: ")


def test_bundle_probe_asks_supported_before_any_probed_import(fakes, monkeypatch, capsys):
    calls: list[str] = []
    real_import = importlib.import_module

    def record(name: str, package: str | None = None):
        calls.append(name)
        return real_import(name, package)

    def asked(engine: str):
        return lambda: calls.append(f"{engine}.supported()")  # append returns None: supported

    for engine in ENGINES:
        module = sys.modules[f"cloudyreader.engines.{engine}"]
        monkeypatch.setattr(module, "supported", asked(engine))
    monkeypatch.setattr(importlib, "import_module", record)

    assert bundle_probe.main([]) == 0
    first_probed = calls.index(IMPORTS[0])
    assert [call for call in calls[:first_probed] if call.endswith(".supported()")] == [
        f"{engine}.supported()" for engine in ENGINES
    ]  # the app asks supported() before mlx_audio loads, so the probe does too


def test_bundle_probe_fails_without_the_qwen_gate_file(fakes, capsys):
    fakes.unlink()

    assert bundle_probe.main([]) == 1
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"FAIL {GATE}: not found where the Qwen gate looks for it"
    )


def test_bundle_probe_uses_the_qwen_gates_own_lookup_when_present(fakes, monkeypatch, capsys):
    decoder = types.ModuleType(DECODER)
    decoder.decoder_source = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, DECODER, decoder)

    assert bundle_probe.main([]) == 1  # the file exists, but the gate says it cannot find it
    assert capsys.readouterr().out.splitlines()[-1].startswith(f"FAIL {GATE}: ")

    decoder.decoder_source = lambda: fakes  # type: ignore[attr-defined]
    assert bundle_probe.main([]) == 0


def test_bundle_probe_fails_when_mlx_audio_is_absent(fakes, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "mlx_audio", None)

    assert bundle_probe.main([]) == 1
    assert capsys.readouterr().out.splitlines()[-1].startswith(f"FAIL {GATE}: ")


def test_importing_the_probe_loads_no_heavy_module():
    code = (
        "import sys, cloudyreader.engines.bundle_probe\n"
        "heavy = {'numpy', 'mlx', 'transformers', 'tokenizers', 'huggingface_hub', 'torch'}\n"
        "print(sorted(heavy & {name.split('.')[0] for name in sys.modules}))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=os.environ
    )

    assert done.stdout.strip() == "[]"
