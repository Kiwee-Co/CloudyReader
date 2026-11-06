"""cloudyreader/engines/bundle_probe.py: one line per engine import and the Qwen gate's file."""

from __future__ import annotations

import importlib.machinery
import json
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


# --- CLOUDYREADER_PROBE=plan: the first-launch download, as the built app counts it -------------


def planned(monkeypatch, capsys, assets: int, skipped: tuple[str, ...]):
    """plan_main over a stand-in plan of `assets` bytes and `skipped` reasons."""
    from cloudyreader import prefetch

    files = (
        prefetch.Asset(f"f{n}", "voices", "", "0" * 64, 1, Path(f"f{n}")) for n in range(assets)
    )
    plan = prefetch.PrefetchPlan(tuple(files), skipped=skipped)
    monkeypatch.setattr(prefetch.VoicePrefetch, "plan", lambda self: plan)
    rc = bundle_probe.plan_main()
    out, err = capsys.readouterr()
    return rc, out.splitlines(), err.splitlines()


def test_plan_probe_prints_the_bytes_a_first_launch_downloads(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CLOUDYREADER_DATA_DIR", str(tmp_path))

    assert planned(monkeypatch, capsys, 3, ()) == (0, ["3"], [])


def test_plan_probe_leaves_out_a_group_this_build_lacks(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CLOUDYREADER_DATA_DIR", str(tmp_path))
    lacks = ("chatterbox_turbo: not in this build", "qwen3_tts: not in this build")

    rc, out, err = planned(monkeypatch, capsys, 2, lacks)

    assert (rc, out) == (0, ["2"])  # a lean app never offers them, so it never downloads them
    assert err == [f"plan: leaves out {reason}" for reason in lacks]


def test_plan_probe_fails_when_this_mac_skips_a_group_the_app_holds(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CLOUDYREADER_DATA_DIR", str(tmp_path))
    skipped = ("chatterbox_turbo: not in this build", "kokoro: not enough disk space")

    rc, out, err = planned(monkeypatch, capsys, 2, skipped)

    assert (rc, out) == (3, [])  # the figure would undercount a first launch elsewhere
    assert err == [
        "plan: leaves out chatterbox_turbo: not in this build",
        f"plan: skips {skipped[1]}",
    ]


def test_plan_probe_reads_the_real_lock_with_an_empty_data_folder(monkeypatch, capsys, tmp_path):
    from cloudyreader import prefetch

    root = Path(__file__).resolve().parents[2]
    real = json.loads((root / "assets.lock.json").read_text())
    voices = [asset for asset in real["assets"] if asset["group"] == "voices"]  # never gated
    lock = tmp_path / "assets.lock.json"
    lock.write_text(json.dumps(real | {"assets": voices}, indent=2))
    monkeypatch.setattr(prefetch, "find_lock", lambda **kwargs: lock)
    monkeypatch.setenv("CLOUDYREADER_DATA_DIR", str(tmp_path / "data"))

    assert bundle_probe.plan_main() == 0
    assert capsys.readouterr().out == f"{sum(asset['size'] for asset in voices)}\n"
    assert not (tmp_path / "data").exists()  # the plan writes nothing


def test_plan_probe_fails_closed_on_any_plan_error(monkeypatch, capsys, tmp_path):
    from cloudyreader import prefetch

    def broken(self):
        raise OSError("lock unreadable")

    monkeypatch.setattr(prefetch.VoicePrefetch, "plan", broken)
    monkeypatch.setenv("CLOUDYREADER_DATA_DIR", str(tmp_path))

    assert bundle_probe.plan_main() == 2
    out, err = capsys.readouterr()
    assert out == ""  # no number at all, so the figures step writes no file
    assert err == "plan: failed: OSError: lock unreadable\n"


def test_plan_probe_never_opens_a_connection(monkeypatch, capsys, tmp_path):
    import httpx

    from cloudyreader import prefetch

    def no_network(*args, **kwargs):
        raise AssertionError("the plan probe must stay offline")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(prefetch, "open_https", no_network)
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(prefetch, "find_lock", lambda **kwargs: root / "assets.lock.json")
    monkeypatch.setenv("CLOUDYREADER_DATA_DIR", str(tmp_path / "data"))

    assert bundle_probe.plan_main() in (0, 3)  # 3 where this test venv lacks the kokoro extra
    assert not (tmp_path / "data").exists()  # and writes nothing
