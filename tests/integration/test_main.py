"""Entry point: --help/--version stay light, --offline, --self-test, the frozen-app asset hook."""

from __future__ import annotations

import importlib.metadata
import math
import os
import platform
import re
import struct
import subprocess
import sys
import types
import wave
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cloudyreader import __main__ as entry
from cloudyreader.models import Audio, Reading, RenderOptions, SpokenScript, VoiceInfo

SERVICE = object()
EXIT_CODE = 7
PIPER = VoiceInfo("piper:fake-a", "piper", "A", "en-US", "medium", 1, True)
KOKORO = VoiceInfo("kokoro:fake", "kokoro", "K", "en-US", "high", 1, True)


@pytest.fixture
def events() -> list[str]:
    """Call order across the fakes: "link" (asset hook) and "build" (service)."""
    return []


# --- the GUI path -----------------------------------------------------------------------------


@dataclass
class Wired:
    data_dir: Any
    seen: dict[str, Any] = field(default_factory=dict)
    player_cls: type = object


@pytest.fixture
def wired(monkeypatch, tmp_path, events) -> Wired:
    """Fake the three things main() reaches for, and pin the environment it reads."""
    monkeypatch.setenv("CLOUDYREADER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOUDYREADER_OFFLINE", "0")  # recorded, so --offline cannot leak out
    monkeypatch.delattr(sys, "frozen", raising=False)
    rig = Wired(tmp_path)

    def build(settings):
        events.append("build")
        rig.seen["settings"] = settings
        return SERVICE

    class Player:
        pass

    def run(service, player, *, argv=()):
        rig.seen["run"] = (service, player, list(argv))
        return EXIT_CODE

    rig.player_cls = Player
    audio = types.ModuleType("cloudyreader.audio")
    audio.AfplayPlayer = Player
    app = types.ModuleType("cloudyreader.gui.app")
    app.run = run
    monkeypatch.setattr(entry, "build_default_service", build)
    monkeypatch.setitem(sys.modules, "cloudyreader.audio", audio)
    monkeypatch.setitem(sys.modules, "cloudyreader.gui.app", app)
    return rig


def test_main_wires_settings_service_player_and_gui(wired):
    assert entry.main([]) == EXIT_CODE

    assert wired.seen["settings"].data_dir == wired.data_dir
    assert wired.seen["settings"].offline is False
    service, player, argv = wired.seen["run"]
    assert service is SERVICE
    assert isinstance(player, wired.player_cls)
    assert argv == []


def test_offline_flag_reaches_the_settings_and_the_environment(wired):
    entry.main(["--offline"])

    assert wired.seen["settings"].offline is True
    assert os.environ["CLOUDYREADER_OFFLINE"] == "1"


def test_offline_environment_works_without_the_flag(wired, monkeypatch):
    monkeypatch.setenv("CLOUDYREADER_OFFLINE", "1")

    entry.main([])

    assert wired.seen["settings"].offline is True


def test_arguments_main_does_not_know_go_to_the_gui(wired):
    entry.main(["--offline", "-style", "fusion"])

    assert wired.seen["run"][2] == ["-style", "fusion"]


def test_a_prefix_of_our_flags_is_not_ours(wired):
    entry.main(["--off", "--self"])  # Qt may grow options like these: they pass through

    assert wired.seen["settings"].offline is False
    assert wired.seen["run"][2] == ["--off", "--self"]


def test_argv_defaults_to_sys_argv(wired, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["cloudyreader", "--offline"])

    entry.main()

    assert wired.seen["settings"].offline is True


# --- --help and --version ---------------------------------------------------------------------


def run_python(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # -I like `make run`: no cwd or PYTHON* variables, so only the installed package is imported.
    # A private HOME and data dir: if a flag ever fell through to the real app, it would still
    # not touch the user's files (the timeout then ends the child).
    env = {**os.environ, "HOME": str(tmp_path), "CLOUDYREADER_DATA_DIR": str(tmp_path / "data")}
    return subprocess.run(
        [sys.executable, "-I", *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )


@pytest.mark.parametrize(
    ("flag", "expected"), [("--help", "usage: cloudyreader"), ("--version", "Cloudy Reader ")]
)
def test_info_flags_load_no_qt_models_or_audio(tmp_path, flag, expected):
    code = (
        "import sys\n"
        "from cloudyreader.__main__ import main\n"
        "try:\n"
        f"    main([{flag!r}])\n"
        "except SystemExit as exc:\n"
        "    status = exc.code\n"
        "heavy = [m for m in ('PySide6', 'spacy', 'piper', 'sounddevice') if m in sys.modules]\n"
        "print('STATUS', status, 'HEAVY', heavy)\n"
    )

    done = run_python(tmp_path, "-c", code)

    assert done.returncode == 0, done.stderr
    assert expected in done.stdout
    assert "STATUS 0 HEAVY []" in done.stdout


def test_help_lists_every_flag(tmp_path):
    done = run_python(tmp_path, "-m", "cloudyreader", "--help")

    assert done.returncode == 0, done.stderr
    assert "usage: cloudyreader" in done.stdout
    for flag in ("--offline", "--self-test", "--version"):
        assert flag in done.stdout


def test_python_dash_m_cloudyreader_version(tmp_path):
    done = run_python(tmp_path, "-m", "cloudyreader", "--version")

    assert done.returncode == 0, done.stderr
    assert done.stdout == f"Cloudy Reader {importlib.metadata.version('cloudyreader')}\n"


def test_version_comes_from_the_shared_app_version_helper(monkeypatch, capsys):
    monkeypatch.setattr(entry, "app_version", lambda: "9.9.9")

    with pytest.raises(SystemExit) as stop:
        entry.main(["--version"])

    assert stop.value.code == 0
    assert capsys.readouterr().out == "Cloudy Reader 9.9.9\n"


# --- the frozen app's asset hook --------------------------------------------------------------


@pytest.fixture
def frozen(monkeypatch, events) -> SimpleNamespace:
    """sys.frozen set, and a fake cloudyreader.frozen that records when and with what it ran."""
    rig = SimpleNamespace(calls=[], module=types.ModuleType("cloudyreader.frozen"))

    def link(settings):
        events.append("link")
        rig.calls.append(settings)

    rig.module.link_bundled_assets = link
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setitem(sys.modules, "cloudyreader.frozen", rig.module)
    return rig


def test_a_frozen_app_links_its_assets_before_building_the_service(wired, frozen, events):
    assert entry.main([]) == EXIT_CODE

    assert events == ["link", "build"]
    assert frozen.calls == [wired.seen["settings"]]


def test_a_source_run_never_touches_the_frozen_hook(wired, events, monkeypatch):
    module = types.ModuleType("cloudyreader.frozen")
    module.link_bundled_assets = lambda settings: events.append("link")
    monkeypatch.setitem(sys.modules, "cloudyreader.frozen", module)

    entry.main([])

    assert events == ["build"]


def test_a_frozen_app_without_the_hook_module_still_starts(wired, monkeypatch, caplog):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setitem(sys.modules, "cloudyreader.frozen", None)  # `import` now raises

    with caplog.at_level("WARNING", logger="cloudyreader.__main__"):
        assert entry.main([]) == EXIT_CODE

    assert "bundled assets" in caplog.text


def test_a_failing_hook_is_logged_and_the_app_still_starts(wired, frozen, caplog):
    def broken(settings):
        raise PermissionError("read-only home")

    frozen.module.link_bundled_assets = broken

    with caplog.at_level("WARNING", logger="cloudyreader.__main__"):
        assert entry.main([]) == EXIT_CODE

    assert "bundled assets" in caplog.text and "read-only home" in caplog.text


# --- --self-test ------------------------------------------------------------------------------


def write_wav(path: Path, *, seconds: float = 4.0, amplitude: int = 8000, rate: int = 8000) -> Path:
    tone = (
        int(amplitude * math.sin(2 * math.pi * 440 * i / rate)) for i in range(int(rate * seconds))
    )
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(struct.pack("<h", sample) for sample in tone))
    return path


def write_8bit_wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(8000)
        wav.writeframes(b"\x80" * 32000)
    return path


def write_garbage(path: Path) -> Path:
    path.write_bytes(b"this is not a wav file")
    return path


class SelfTestService:
    """What --self-test uses of a service: voices(), prepare() and entity_mode()."""

    def __init__(self, wav: Path, voices=(KOKORO, PIPER)) -> None:
        self.wav = wav
        self.voice_list = list(voices)
        self.prepared: list[tuple[str, str, RenderOptions]] = []
        self.error: Exception | None = None

    def voices(self) -> list[VoiceInfo]:
        return list(self.voice_list)

    def prepare(self, raw: str, voice_key: str, opts: RenderOptions) -> Reading:
        self.prepared.append((raw, voice_key, opts))
        if self.error is not None:
            raise self.error
        return Reading((), SpokenScript(()), (), {}, Audio(self.wav, 8000, 4.0, False))

    def entity_mode(self) -> str:
        return "ner"


@pytest.fixture
def selftest(monkeypatch, tmp_path, events) -> SimpleNamespace:
    monkeypatch.setenv("CLOUDYREADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CLOUDYREADER_OFFLINE", "0")
    monkeypatch.delattr(sys, "frozen", raising=False)
    # A self-test must never reach the player or the window: importing either now raises.
    monkeypatch.setitem(sys.modules, "cloudyreader.audio", None)
    monkeypatch.setitem(sys.modules, "cloudyreader.gui.app", None)
    rig = SimpleNamespace(service=SelfTestService(write_wav(tmp_path / "ok.wav")), built=[])

    def build(settings):
        events.append("build")
        rig.built.append(settings)
        return rig.service

    monkeypatch.setattr(entry, "build_default_service", build)
    return rig


def test_self_test_passes_and_prints_the_report(selftest, capsys):
    assert entry.main(["--self-test"]) == 0

    out = capsys.readouterr().out
    assert f"python    {platform.python_version()}" in out
    assert re.search(r"^packages\s+.*piper-tts .*spacy ", out, re.MULTILINE)
    assert re.search(r"^voices\s+2 found, using piper:fake-a$", out, re.MULTILINE)
    assert re.search(r"^entities\s+ner$", out, re.MULTILINE)
    assert re.search(r"^audio\s+4\.0 s, peak 0\.2\d$", out, re.MULTILINE)
    assert re.search(r"^wall\s+\d+\.\d s$", out, re.MULTILINE)
    assert out.splitlines()[-1] == "PASS"


def test_self_test_reads_the_sample_with_the_first_piper_voice(selftest):
    entry.main(["--self-test"])

    ((raw, key, opts),) = selftest.service.prepared
    assert raw == entry.SELF_TEST_PASTE
    assert raw.startswith("TOSS-UP\n2) EARTH SCIENCE Multiple Choice The source of energy")
    assert key == "piper:fake-a"  # not kokoro:fake, which is listed first
    assert opts == RenderOptions()


def test_self_test_builds_an_offline_service_over_a_throwaway_cache(selftest, tmp_path):
    entry.main(["--self-test"])

    (settings,) = selftest.built
    assert settings.offline is True
    assert settings.data_dir == tmp_path / "data"  # voices and models still come from here
    assert settings.cache_dir != tmp_path / "data" / "cache"
    assert not settings.cache_dir.exists()  # and the throwaway cache is gone again


def test_self_test_links_a_frozen_apps_assets_first(selftest, frozen, events):
    assert entry.main(["--self-test"]) == 0

    assert events == ["link", "build"]


def test_self_test_says_unknown_when_the_service_cannot_report_its_entity_mode(selftest, capsys):
    selftest.service.entity_mode = None

    assert entry.main(["--self-test"]) == 0

    assert re.search(r"^entities\s+unknown$", capsys.readouterr().out, re.MULTILINE)


def test_self_test_reports_n_a_for_a_package_without_metadata(selftest, monkeypatch, capsys):
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)

    assert entry.main(["--self-test"]) == 0

    assert "piper-tts n/a" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("make_wav", "reason"),
    [
        pytest.param(lambda p: write_wav(p, seconds=1.0), "too short", id="short"),
        pytest.param(lambda p: write_wav(p, amplitude=0), "too quiet", id="silent"),
        pytest.param(lambda p: write_wav(p, amplitude=200), "too quiet", id="quiet"),
        pytest.param(lambda p: p, "WAV missing", id="missing"),
        pytest.param(write_8bit_wav, "16-bit", id="8-bit"),
        pytest.param(write_garbage, "WAV unreadable", id="corrupt"),
    ],
)
def test_self_test_fails_on_bad_audio(selftest, tmp_path, capsys, make_wav, reason):
    selftest.service.wav = make_wav(tmp_path / "bad.wav")

    assert entry.main(["--self-test"]) == 1

    captured = capsys.readouterr()
    assert reason in captured.err
    assert "PASS" not in captured.out


def test_self_test_exits_2_without_a_piper_voice(selftest, capsys):
    selftest.service.voice_list = [KOKORO]

    assert entry.main(["--self-test"]) == 2

    assert selftest.service.prepared == []
    assert "no Piper voice installed" in capsys.readouterr().err


def test_self_test_exits_1_when_the_read_raises(selftest, capsys):
    selftest.service.error = RuntimeError("onnx exploded")

    assert entry.main(["--self-test"]) == 1

    assert "RuntimeError: onnx exploded" in capsys.readouterr().err


def test_self_test_exits_1_when_the_service_cannot_be_built(selftest, monkeypatch, capsys):
    def broken(settings):
        raise ImportError("piper is missing from the bundle")

    monkeypatch.setattr(entry, "build_default_service", broken)

    assert entry.main(["--self-test"]) == 1

    assert "piper is missing from the bundle" in capsys.readouterr().err
