"""Optional TTS engines: what each needs, and whether it can run or download here. Stdlib only."""

from __future__ import annotations

import importlib
import logging
import math
import os
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

from cloudyreader.config import Settings

if TYPE_CHECKING:
    from cloudyreader.engines.mlxkit import ModelFiles

log = logging.getLogger(__name__)

TITLES: Mapping[str, str] = MappingProxyType(
    {
        "voices": "Piper voices",
        "kokoro": "Kokoro",
        "chatterbox_turbo": "Chatterbox Turbo",
        "qwen3_tts": "Qwen3-TTS",
        "macos": "macOS",
    }
)
# Engine lock entries: these suffixes only; dest .data/models/<engine> or ONE safe sub-folder.
ENGINE_SUFFIXES = (".safetensors", ".json", ".txt")
DISK_FACTOR = 1.1  # free disk must hold the missing bytes times this, plus DISK_MARGIN
DISK_MARGIN = 1 << 30

# Reasons; a prefetch skip reads "<group>: <reason>".
NOT_IN_BUILD = "not in this build"
NOT_PINNED = "no files pinned in assets.lock.json"
NOT_DOWNLOADED = "not downloaded yet"
OFFLINE = "offline: not downloaded"
NOT_WRITABLE = "the models folder is not writable"
LOW_DISK = "not enough disk space"

Readiness = tuple[str | None, str | None]  # (hard reason: no row at all, gate reason: dimmed rows)


@dataclass(frozen=True)
class PinnedFile:
    rel: str  # POSIX path under models_dir/<engine>
    size: int
    sha256: str


@dataclass(frozen=True)
class Pinned:
    files: tuple[PinnedFile, ...]
    revision: str  # the 40-hex commit in the lock URLs; "" when none


@dataclass(frozen=True)
class EngineSpec:
    engine: str  # = lock group = VoiceInfo.engine = models_dir/<engine>/
    title: str
    repo: str
    voices: tuple[str, ...]
    license: str
    credit: str
    # rel -> (size, sha256 or None): seeds the pin script's drift check.
    expect: Mapping[str, tuple[int, str | None]] = field(hash=False)


@dataclass(frozen=True)
class Assessment:
    state: Literal["ready", "missing", "blocked", "broken"]
    reason: str  # "" when ready
    missing_bytes: int
    listable: bool  # False: the picker shows no row for this engine


SPECS: Mapping[str, EngineSpec] = MappingProxyType(
    {
        "chatterbox_turbo": EngineSpec(
            engine="chatterbox_turbo",
            title=TITLES["chatterbox_turbo"],
            repo="mlx-community/chatterbox-turbo-4bit",
            voices=("builtin",),
            license="MIT",
            credit="Resemble AI (upstream retired in August 2026); MLX build by mlx-community",
            # The research digest gives only hash prefixes (model 59603c7f, conds df9ad2c5).
            expect=MappingProxyType(
                {
                    "model.safetensors": (414_992_166, None),
                    "conds.safetensors": (164_884, None),
                }
            ),
        ),
        "qwen3_tts": EngineSpec(
            engine="qwen3_tts",
            title=TITLES["qwen3_tts"],
            repo="mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
            voices=("ryan", "aiden"),
            license="Apache-2.0",
            credit="Alibaba Qwen team; MLX build by mlx-community",
            # The Hugging Face tree at main (research digest section 4): LFS files carry their
            # sha256; small files have none published. README.md and .gitattributes are skipped.
            expect=MappingProxyType(
                {
                    "model.safetensors": (
                        1_286_743_170,
                        "3bcb2c4a127e6243e81a30b7126c7865f686d3559de4f938e5d3b150c6a9560d",
                    ),
                    "speech_tokenizer/model.safetensors": (
                        682_293_092,
                        "836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258",
                    ),
                    "config.json": (6_058, None),
                    "generation_config.json": (245, None),
                    "model.safetensors.index.json": (71_447, None),
                    "merges.txt": (1_671_839, None),
                    "vocab.json": (2_776_833, None),
                    "tokenizer_config.json": (7_344, None),
                    "preprocessor_config.json": (127, None),
                    "speech_tokenizer/config.json": (2_336, None),
                    "speech_tokenizer/configuration.json": (76, None),
                    "speech_tokenizer/preprocessor_config.json": (234, None),
                }
            ),
        ),
    }
)


_MODULES = {engine: f"cloudyreader.engines.{engine}" for engine in SPECS}
_COMMIT = re.compile(r"/resolve/([0-9a-f]{40})/")
_HARD: dict[tuple[str, Any], str | None] = {}  # supported() per engine module object


def readiness(engine: str) -> Readiness:
    """(hard, gate) reasons from the engine module's supported() and gate(), imported here.

    supported() is asked once per module object, gate() on every call (its reason can clear).
    A module this build lacks is NOT_IN_BUILD; a check that raises blocks only its engine.
    """
    name = _MODULES.get(engine)
    if name is None:
        return f"unknown engine {engine!r}", None
    try:
        module = importlib.import_module(name)
        key = (engine, module)
        if key not in _HARD:
            _HARD[key] = module.supported()
        hard = _HARD[key]
        return (hard, None) if hard else (None, module.gate())
    except ImportError:
        return NOT_IN_BUILD, None
    except Exception as exc:
        log.warning("engine check for %s failed: %s", engine, exc, exc_info=True)
        return f"engine check failed ({type(exc).__name__})", None


def ready_reason(group: str) -> str | None:
    """Why an engine group cannot download here (hard reason, then gate), else None."""
    hard, gate = readiness(group)
    return hard or gate


def write_reason(models_dir: Path) -> str | None:
    """NOT_WRITABLE when the nearest existing folder of `models_dir` cannot take new files."""
    base = _nearest_existing(Path(models_dir))
    return None if base.is_dir() and os.access(base, os.W_OK | os.X_OK) else NOT_WRITABLE


def space_reason(
    models_dir: Path, missing_bytes: int, free_bytes: Callable[[Path], int] | None = None
) -> str | None:
    """A LOW_DISK reason unless free space holds missing_bytes x DISK_FACTOR + DISK_MARGIN.

    `free_bytes` measures the nearest existing folder (default: shutil.disk_usage). A disk that
    cannot be measured blocks nothing: the download itself then fails file by file.
    """
    base = _nearest_existing(Path(models_dir))
    need = math.ceil(missing_bytes * DISK_FACTOR) + DISK_MARGIN
    try:
        free = (free_bytes or _disk_free)(base)
    except OSError as exc:
        log.info("cannot measure free space at %s: %s", base, exc)
        return None
    if free >= need:
        return None
    return f"{LOW_DISK}: needs {_gb(need, math.ceil)}, {_gb(free, math.floor)} free"


def _disk_free(path: Path) -> int:
    return shutil.disk_usage(path).free


def _gb(size: int, rounding: Callable[[float], int]) -> str:
    """Decimal GB, one digit. The need rounds up and the free space down, so the two differ."""
    return f"{rounding(size / 1e8) / 10:.1f} GB"


def _nearest_existing(path: Path) -> Path:
    return next((p for p in (path, *path.parents) if _exists(p)), Path(path.anchor or "."))


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:  # an unreadable parent: look further up
        return False


def pinned(settings: Settings, engine: str, *, lock_path: Path | None = None) -> Pinned:
    """The engine's files in the lock (find_lock() by default). Empty when none or rejected."""
    from cloudyreader import prefetch  # httpx loads with it: never at this module's import

    lock = lock_path or prefetch.find_lock()
    if engine not in SPECS or lock is None or not lock.is_file():
        return Pinned((), "")
    try:
        assets = prefetch.load_assets(lock, settings)
    except prefetch.PrefetchError:
        return Pinned((), "")  # the startup run logs why the lock was rejected
    folder = settings.models_dir / engine
    mine = [a for a in assets if a.group == engine]
    files = tuple(PinnedFile(a.path.relative_to(folder).as_posix(), a.size, a.sha256) for a in mine)
    commits = {m.group(1) for a in mine if (m := _COMMIT.search(urlsplit(a.url).path))}
    return Pinned(files, commits.pop() if len(commits) == 1 else "")


def assess(
    settings: Settings,
    engine: str,
    *,
    lock_path: Path | None = None,
    free_bytes: Callable[[Path], int] | None = None,
    ready: Callable[[], Readiness] | None = None,
) -> Assessment:
    """Where the engine stands: ready, missing, blocked, or broken, with the reason to show.

    Order: hard reason (no row), nothing pinned (dormant, no row), gate, damaged files, then
    missing files (offline, not writable, low disk, or simply not downloaded yet), else ready.
    Stat only: the SHA-256 check belongs to the engine's first load.
    """
    hard, gate = ready() if ready is not None else readiness(engine)
    if hard:
        return Assessment("blocked", hard, 0, False)
    pins = pinned(settings, engine, lock_path=lock_path)
    if not pins.files:
        return Assessment("blocked", NOT_PINNED, 0, False)
    folder = settings.models_dir / engine
    files = _model_files(folder, pins.files)
    missing = sum(f.size for f in files.missing())
    if gate:
        return Assessment("blocked", gate, missing, True)
    damage = files.damage()
    if damage:
        return Assessment("broken", f"damaged: {damage}", missing, True)
    if not missing:
        return Assessment("ready", "", 0, True)
    if settings.offline:
        return Assessment("missing", OFFLINE, missing, True)
    room = write_reason(folder) or space_reason(folder, missing, free_bytes)
    if room:
        return Assessment("blocked", room, missing, True)
    return Assessment("missing", NOT_DOWNLOADED, missing, True)


def _model_files(folder: Path, files: tuple[PinnedFile, ...]) -> ModelFiles:
    from cloudyreader.engines.mlxkit import ModelFiles  # numpy: only once an engine is pinned

    return ModelFiles(folder, files)


def is_actionable(reason: str) -> bool:
    """A disk or write reason, bare or as a "<group>: <reason>" skip: worth a status-bar line."""
    group, sep, rest = reason.partition(": ")
    if sep and group in TITLES:
        reason = rest
    return reason == NOT_WRITABLE or reason.startswith(f"{LOW_DISK}: ")
