"""cloudyreader.engine_catalog: specs, titles, pins, readiness, write and space checks, assess()."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import subprocess
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

from cloudyreader import engine_catalog
from cloudyreader.config import Settings
from cloudyreader.engine_catalog import (
    DISK_FACTOR,
    DISK_MARGIN,
    ENGINE_SUFFIXES,
    LOW_DISK,
    NOT_DOWNLOADED,
    NOT_IN_BUILD,
    NOT_PINNED,
    NOT_WRITABLE,
    OFFLINE,
    SPECS,
    TITLES,
    Assessment,
    Pinned,
    PinnedFile,
    assess,
    is_actionable,
    pinned,
    readiness,
    ready_reason,
    space_reason,
    write_reason,
)

ROOT = Path(__file__).resolve().parents[2]
REV = "0123456789abcdef0123456789abcdef01234567"
GATE = "waiting for a Qwen3 decoder fix"
PLENTY = 1 << 50


def body(rel: str) -> bytes:
    return (rel.encode() + b"\n") * 5


def engine_entry(engine: str, rel: str, *, rev: str = REV) -> dict:
    sub, _, name = rel.rpartition("/")
    data = body(rel)
    return {
        "name": name,
        "group": engine,
        "url": f"https://files.example/{engine}/resolve/{rev}/{rel}",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "dest": f".data/models/{engine}" + (f"/{sub}" if sub else ""),
    }


VOICE = {
    "name": "en_US-a-medium.onnx.json",
    "group": "voices",
    "url": "https://files.example/voices/en_US-a-medium.onnx.json",
    "sha256": hashlib.sha256(b"voice").hexdigest(),
    "size": 5,
    "dest": ".data/voices",
}
QWEN = ["config.json", "merges.txt", "model.safetensors", "speech_tokenizer/model.safetensors"]
QWEN_BYTES = sum(len(body(rel)) for rel in QWEN)


def size_of(*rels: str) -> int:
    return sum(len(body(rel)) for rel in rels)


def free(amount: int):
    return lambda path: amount


def ready_with(hard: str | None = None, gate: str | None = None):
    return lambda: (hard, gate)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    return Settings(data, data / "cache", data / "voices", data / "models")


@pytest.fixture
def lock(tmp_path: Path) -> Path:
    path = tmp_path / "assets.lock.json"
    entries = [VOICE, *(engine_entry("qwen3_tts", rel) for rel in QWEN)]
    path.write_text(json.dumps({"version": 1, "assets": entries}))
    return path


def install(settings: Settings, engine: str, rel: str) -> Path:
    path = settings.models_dir / engine / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body(rel))
    return path


class FakeFiles:
    """mlxkit.ModelFiles as far as assess() uses it: missing() by stat, damage() as told."""

    def __init__(self, folder: Path, files, damage: str | None) -> None:
        self.folder, self.files, self._damage = folder, tuple(files), damage

    def missing(self) -> tuple[PinnedFile, ...]:
        return tuple(f for f in self.files if not (self.folder / f.rel).exists())

    def damage(self) -> str | None:
        return self._damage


@pytest.fixture
def model_files(monkeypatch: pytest.MonkeyPatch):
    """Swap mlxkit.ModelFiles for FakeFiles; returns a setter for the damage text."""
    state: dict = {"damage": None, "made": []}

    def make(folder: Path, files) -> FakeFiles:
        state["made"].append((folder, tuple(f.rel for f in files)))
        return FakeFiles(folder, files, state["damage"])

    monkeypatch.setattr(engine_catalog, "_model_files", make)
    return state


@pytest.fixture
def read_only(settings: Settings) -> Iterator[Path]:
    if os.geteuid() == 0:
        pytest.skip("root can write anywhere")
    settings.models_dir.mkdir(parents=True)
    settings.models_dir.chmod(0o500)
    yield settings.models_dir
    settings.models_dir.chmod(0o700)


def fake_engine(monkeypatch: pytest.MonkeyPatch, engine: str, **attrs) -> types.ModuleType:
    name = f"cloudyreader.engines.{engine}"
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


# --- specs and titles -----------------------------------------------------------------------------


def test_specs_name_chatterbox_first_then_qwen() -> None:
    assert list(SPECS) == ["chatterbox_turbo", "qwen3_tts"]
    chatterbox, qwen = SPECS["chatterbox_turbo"], SPECS["qwen3_tts"]
    assert (chatterbox.engine, chatterbox.title, chatterbox.voices) == (
        "chatterbox_turbo",
        "Chatterbox Turbo",
        ("builtin",),
    )
    assert (qwen.engine, qwen.title, qwen.voices) == ("qwen3_tts", "Qwen3-TTS", ("ryan", "aiden"))
    assert chatterbox.repo == "mlx-community/chatterbox-turbo-4bit"
    assert qwen.repo == "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"
    assert (chatterbox.license, qwen.license) == ("MIT", "Apache-2.0")
    assert all("mlx-community" in spec.credit for spec in SPECS.values())


def test_titles_cover_every_downloaded_group_in_order() -> None:
    assert dict(TITLES) == {
        "voices": "Piper voices",
        "kokoro": "Kokoro",
        "chatterbox_turbo": "Chatterbox Turbo",
        "qwen3_tts": "Qwen3-TTS",
    }
    assert all(TITLES[engine] == spec.title for engine, spec in SPECS.items())


def test_expect_holds_the_researched_sizes_and_lfs_hashes() -> None:
    qwen = SPECS["qwen3_tts"].expect
    assert sum(size for size, _ in qwen.values()) == 1_973_572_801  # 12 files, the repo tree
    assert qwen["model.safetensors"] == (
        1_286_743_170,
        "3bcb2c4a127e6243e81a30b7126c7865f686d3559de4f938e5d3b150c6a9560d",
    )
    assert qwen["speech_tokenizer/model.safetensors"][0] == 682_293_092
    assert qwen["vocab.json"] == (2_776_833, None) and qwen["merges.txt"] == (1_671_839, None)
    assert SPECS["chatterbox_turbo"].expect == {
        "model.safetensors": (414_992_166, None),
        "conds.safetensors": (164_884, None),
    }
    for spec in SPECS.values():
        for rel, (size, sha) in spec.expect.items():
            assert size > 0 and rel.endswith(ENGINE_SUFFIXES)
            assert sha is None or len(sha) == 64
    with pytest.raises(TypeError):
        SPECS["qwen3_tts"].expect["model.safetensors"] = (1, None)  # read-only


# --- pinned ---------------------------------------------------------------------------------------


def test_pinned_lists_the_engine_files_and_the_commit(settings: Settings, lock: Path) -> None:
    pins = pinned(settings, "qwen3_tts", lock_path=lock)

    assert pins.revision == REV
    by_rel = {f.rel: f for f in pins.files}
    assert sorted(by_rel) == sorted(QWEN)
    rel = "speech_tokenizer/model.safetensors"
    assert by_rel[rel] == PinnedFile(rel, len(body(rel)), hashlib.sha256(body(rel)).hexdigest())
    assert pinned(settings, "chatterbox_turbo", lock_path=lock) == Pinned((), "")


def test_pinned_uses_the_lock_find_lock_returns(
    settings: Settings, lock: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cloudyreader import prefetch

    monkeypatch.setattr(prefetch, "find_lock", lambda **kwargs: lock)
    assert len(pinned(settings, "qwen3_tts").files) == 4
    monkeypatch.setattr(prefetch, "find_lock", lambda **kwargs: None)
    assert pinned(settings, "qwen3_tts") == Pinned((), "")


def test_a_rejected_or_missing_lock_pins_nothing(settings: Settings, tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"version": 1, "assets": [engine_entry("qwen3_tts", "x.py")]}))

    assert pinned(settings, "qwen3_tts", lock_path=bad) == Pinned((), "")
    assert pinned(settings, "qwen3_tts", lock_path=tmp_path / "absent.json") == Pinned((), "")


def test_mixed_commits_give_no_revision(settings: Settings, tmp_path: Path) -> None:
    path = tmp_path / "mixed.json"
    entries = [
        engine_entry("qwen3_tts", "config.json"),
        engine_entry("qwen3_tts", "model.safetensors", rev="f" * 40),
    ]
    path.write_text(json.dumps({"version": 1, "assets": entries}))

    pins = pinned(settings, "qwen3_tts", lock_path=path)

    assert (len(pins.files), pins.revision) == (2, "")


def test_the_real_lock_pins_nothing_or_matches_the_specs(settings: Settings) -> None:
    for engine, spec in SPECS.items():
        pins = pinned(settings, engine, lock_path=ROOT / "assets.lock.json")
        if not pins.files:
            assert pins.revision == ""  # dormant until the owner pins the engine
            continue
        assert len(pins.revision) == 40
        for item in pins.files:
            size, sha = spec.expect.get(item.rel, (item.size, None))
            assert item.size == size and (sha is None or item.sha256 == sha)


# --- readiness ------------------------------------------------------------------------------------


def test_readiness_asks_the_engine_module(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_engine(monkeypatch, "qwen3_tts", supported=lambda: None, gate=lambda: GATE)
    fake_engine(monkeypatch, "chatterbox_turbo", supported=lambda: "needs arm64", gate=lambda: None)

    assert readiness("qwen3_tts") == (None, GATE)
    assert readiness("chatterbox_turbo") == ("needs arm64", None)
    assert (ready_reason("qwen3_tts"), ready_reason("chatterbox_turbo")) == (GATE, "needs arm64")


def test_supported_is_asked_once_per_module_and_gate_every_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    gates = iter([GATE, None])
    fake_engine(
        monkeypatch,
        "qwen3_tts",
        supported=lambda: calls.append("supported"),
        gate=lambda: calls.append("gate") or next(gates),
    )

    assert readiness("qwen3_tts") == (None, GATE)
    assert readiness("qwen3_tts") == (None, None)  # the gate cleared
    assert calls == ["supported", "gate", "gate"]
    fake_engine(monkeypatch, "qwen3_tts", supported=lambda: "fresh module", gate=lambda: None)
    assert readiness("qwen3_tts") == ("fresh module", None)


def test_an_engine_module_this_build_lacks_is_a_hard_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "cloudyreader.engines.qwen3_tts", None)  # `import` raises

    assert readiness("qwen3_tts") == (NOT_IN_BUILD, None)
    assert ready_reason("qwen3_tts") == NOT_IN_BUILD
    assert readiness("f5_tts") == ("unknown engine 'f5_tts'", None)


@pytest.mark.parametrize("where", ["supported", "gate", "import"])
def test_a_failing_engine_check_blocks_only_that_engine(
    where: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken() -> str | None:
        raise RuntimeError("bad install")

    if where == "import":
        monkeypatch.setattr(engine_catalog.importlib, "import_module", lambda name: broken())
    else:
        checks = {"supported": lambda: None, "gate": lambda: None} | {where: broken}
        fake_engine(monkeypatch, "qwen3_tts", **checks)

    assert readiness("qwen3_tts") == ("engine check failed (RuntimeError)", None)
    assert "qwen3_tts" in caplog.text


# --- write and space ------------------------------------------------------------------------------


def test_write_reason_reads_the_nearest_existing_folder(
    settings: Settings, read_only: Path
) -> None:
    assert write_reason(settings.models_dir / "qwen3_tts") == NOT_WRITABLE
    assert write_reason(settings.models_dir) == NOT_WRITABLE
    read_only.chmod(0o700)
    assert write_reason(settings.models_dir / "qwen3_tts" / "speech_tokenizer") is None


def test_a_file_where_the_models_folder_should_be_is_not_writable(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True)
    settings.models_dir.write_bytes(b"not a folder")

    assert write_reason(settings.models_dir / "qwen3_tts") == NOT_WRITABLE


def need(missing: int) -> int:
    return math.ceil(missing * DISK_FACTOR) + DISK_MARGIN


def test_the_disk_rule_is_missing_bytes_x_1_1_plus_1_gib(settings: Settings) -> None:
    missing = 1_973_572_801

    assert space_reason(settings.models_dir, missing, free(need(missing))) is None
    reason = space_reason(settings.models_dir, missing, free(need(missing) - 1))
    assert reason == "not enough disk space: needs 3.3 GB, 3.2 GB free"
    assert reason.startswith(f"{LOW_DISK}: ")


def test_the_disk_reason_rounds_the_need_up_and_the_free_space_down(settings: Settings) -> None:
    reason = space_reason(settings.models_dir, 2_000_000_000, free(1_190_000_000))

    assert reason == "not enough disk space: needs 3.3 GB, 1.1 GB free"


def test_free_space_is_asked_on_the_nearest_existing_folder(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[Path] = []
    settings.data_dir.mkdir(parents=True)

    def measure(path: Path) -> int:
        asked.append(path)
        return PLENTY

    assert space_reason(settings.models_dir / "qwen3_tts", 10, measure) is None
    assert asked == [settings.data_dir]
    usage = types.SimpleNamespace(total=0, used=0, free=0)
    monkeypatch.setattr(engine_catalog.shutil, "disk_usage", lambda path: usage)
    assert space_reason(settings.models_dir, 10).startswith(LOW_DISK)  # default: disk_usage
    assert not settings.models_dir.exists()  # checks never make a folder


def test_a_disk_that_cannot_be_measured_blocks_nothing(settings: Settings) -> None:
    def broken(path: Path) -> int:
        raise PermissionError(13, "Permission denied", str(path))

    assert space_reason(settings.models_dir, 10, broken) is None


def test_an_unreadable_folder_on_the_way_is_passed_over(settings: Settings) -> None:
    if os.geteuid() == 0:
        pytest.skip("root reads everything")
    locked = settings.data_dir / "locked"
    locked.mkdir(parents=True)
    locked.chmod(0o000)  # stat below it fails with EACCES, not ENOENT
    try:
        assert write_reason(locked / "models" / "qwen3_tts") == NOT_WRITABLE
        assert space_reason(locked / "models", 10, lambda path: PLENTY) is None
    finally:
        locked.chmod(0o700)


# --- assess ---------------------------------------------------------------------------------------


CASES = {
    "ready": dict(files=QWEN, expect=Assessment("ready", "", 0, True)),
    "missing": dict(files=(), expect=Assessment("missing", NOT_DOWNLOADED, QWEN_BYTES, True)),
    "offline": dict(
        files=(), offline=True, expect=Assessment("missing", OFFLINE, QWEN_BYTES, True)
    ),
    "hard": dict(
        files=QWEN, hard="needs arm64", expect=Assessment("blocked", "needs arm64", 0, False)
    ),
    "gate": dict(files=(), gate=GATE, expect=Assessment("blocked", GATE, QWEN_BYTES, True)),
    "disk": dict(
        files=QWEN[:2],
        free=0,
        expect=Assessment(
            "blocked",
            "not enough disk space: needs 1.1 GB, 0.0 GB free",
            size_of(*QWEN[2:]),
            True,
        ),
    ),
    "broken": dict(
        files=QWEN[:1],
        damage="wrong size: config.json",
        expect=Assessment("broken", "damaged: wrong size: config.json", size_of(*QWEN[1:]), True),
    ),
    "dormant": dict(files=(), dormant=True, expect=Assessment("blocked", NOT_PINNED, 0, False)),
}


@pytest.mark.parametrize("case", list(CASES))
def test_assess_states(case: str, settings: Settings, lock: Path, model_files) -> None:
    spec = CASES[case]
    model_files["damage"] = spec.get("damage")
    for rel in spec["files"]:
        install(settings, "qwen3_tts", rel)
    if spec.get("dormant"):
        lock.write_text(json.dumps({"version": 1, "assets": [VOICE]}))
    if spec.get("offline"):
        settings = dataclasses.replace(settings, offline=True)

    result = assess(
        settings,
        "qwen3_tts",
        lock_path=lock,
        free_bytes=free(spec.get("free", PLENTY)),
        ready=ready_with(spec.get("hard"), spec.get("gate")),
    )

    assert result == spec["expect"]


def test_assess_write(settings: Settings, lock: Path, model_files, read_only: Path) -> None:
    result = assess(settings, "qwen3_tts", lock_path=lock, free_bytes=free(0), ready=ready_with())

    assert result == Assessment("blocked", NOT_WRITABLE, QWEN_BYTES, True)  # write before disk


def test_assess_hands_the_engine_folder_and_every_pinned_file_to_model_files(
    settings: Settings, lock: Path, model_files
) -> None:
    assess(settings, "qwen3_tts", lock_path=lock, free_bytes=free(PLENTY), ready=ready_with())

    ((folder, rels),) = model_files["made"]
    assert folder == settings.models_dir / "qwen3_tts"
    assert sorted(rels) == sorted(QWEN)


def test_assess_asks_the_engine_module_by_default(
    settings: Settings, lock: Path, model_files, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_engine(monkeypatch, "qwen3_tts", supported=lambda: None, gate=lambda: GATE)

    result = assess(settings, "qwen3_tts", lock_path=lock, free_bytes=free(PLENTY))

    assert result == Assessment("blocked", GATE, QWEN_BYTES, True)


def test_a_hard_reason_or_a_dormant_engine_never_loads_model_files(
    settings: Settings, lock: Path, model_files
) -> None:
    assess(settings, "qwen3_tts", lock_path=lock, ready=ready_with(hard="needs arm64"))
    assess(settings, "chatterbox_turbo", lock_path=lock, ready=ready_with())

    assert model_files["made"] == []


def test_the_default_model_files_come_from_mlxkit(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[tuple] = []

    class ModelFiles:
        def __init__(self, model_dir: Path, files) -> None:
            made.append((model_dir, tuple(files)))

    fake = types.ModuleType("cloudyreader.engines.mlxkit")
    fake.ModelFiles = ModelFiles
    monkeypatch.setitem(sys.modules, "cloudyreader.engines.mlxkit", fake)
    files = (PinnedFile("model.safetensors", 3, "0" * 64),)

    assert isinstance(engine_catalog._model_files(settings.models_dir, files), ModelFiles)
    assert made == [(settings.models_dir, files)]


def test_assess_with_the_real_model_files(settings: Settings, lock: Path) -> None:
    pytest.importorskip("numpy")  # mlxkit's one import
    folder = settings.models_dir / "qwen3_tts"
    for rel in QWEN:
        install(settings, "qwen3_tts", rel)
    args = {"lock_path": lock, "free_bytes": free(PLENTY), "ready": ready_with()}

    assert assess(settings, "qwen3_tts", **args) == Assessment("ready", "", 0, True)
    (folder / "stray.safetensors").write_bytes(b"x")
    stray = assess(settings, "qwen3_tts", **args)
    assert (stray.state, stray.reason) == ("broken", "damaged: unpinned weights stray.safetensors")
    (folder / "stray.safetensors").unlink()
    (folder / "merges.txt").unlink()
    missing = Assessment("missing", NOT_DOWNLOADED, size_of("merges.txt"), True)
    assert assess(settings, "qwen3_tts", **args) == missing


# --- is_actionable --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "actionable"),
    [
        (NOT_WRITABLE, True),
        ("not enough disk space: needs 3.3 GB, 1.1 GB free", True),
        ("qwen3_tts: not enough disk space: needs 3.3 GB, 1.1 GB free", True),
        ("chatterbox_turbo: the models folder is not writable", True),
        (GATE, False),
        ("qwen3_tts: waiting for a Qwen3 decoder fix", False),
        ("kokoro: needs an Apple Silicon Mac with the Kokoro packages", False),
        (OFFLINE, False),
        (NOT_IN_BUILD, False),
        ("conflict: /tmp/x", False),
        ("", False),
    ],
)
def test_is_actionable(reason: str, actionable: bool) -> None:
    assert is_actionable(reason) is actionable


# --- import weight --------------------------------------------------------------------------------


def test_catalog_imports_only_the_stdlib() -> None:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "before = set(sys.modules)\n"
        "import cloudyreader.engine_catalog as catalog\n"
        f"assert catalog.__file__.startswith({str(ROOT)!r}), catalog.__file__\n"
        "tops = {name.partition('.')[0] for name in set(sys.modules) - before}\n"
        "foreign = sorted(t for t in tops if t not in sys.stdlib_module_names)\n"
        "assert foreign == ['cloudyreader'], foreign\n"
        "assert not [m for m in sys.modules if m.startswith('cloudyreader.engines')]\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
