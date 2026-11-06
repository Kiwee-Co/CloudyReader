"""Shared helpers for the MLX plain-text engines (Chatterbox Turbo, Qwen3-TTS).

Numpy only at import: mlx, mlx-audio, transformers, huggingface_hub and torch are never imported
here, so listing voices stays cheap and a venv without the `kokoro` extra can import this module.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import stat
import sys
import threading
import wave
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, redirect_stderr, redirect_stdout, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

import numpy as np

from cloudyreader.frozen import is_frozen

if TYPE_CHECKING:
    from importlib.machinery import ModuleSpec
    from types import ModuleType

    from cloudyreader.engine_catalog import PinnedFile
    from cloudyreader.models import Segment

log = logging.getLogger(__name__)

SAMPLE_RATE = 24_000
MAX_SCRIPT_CHARS = 8_000
INTER_CHUNK_MS = 120
MIN_EST_S = 1.0
RUNAWAY = 1.9  # audio this many times the estimate means the model kept going past the text
SHORT_CHARS = 24  # a shorter unit falls back to repeat-and-crop; also the engines' min_chars
MEMO_MAX_S = 3.0  # render_text memoizes units this short: letters and header phrases repeat
MEMO_LIMIT = 256  # units per memo; the least recently used goes first
BIG_RAM = 24 << 30  # from this much RAM, two engine models stay resident
# Pickle-capable formats: never loaded, and one in the model folder marks it damaged.
FORBIDDEN_SUFFIXES = (".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".bin")


class EngineError(RuntimeError):
    """An MLX engine could not produce audio. str(exc) reaches the status bar."""


class EngineUnavailable(EngineError):
    """An MLX engine cannot run: platform, packages, missing or damaged files, or a gate."""


class TextBackend(Protocol):
    def render(
        self, text: str, voice: str, *, seed: int, budget_s: float
    ) -> tuple[np.ndarray, int]:
        """Return (mono float32 samples in [-1, 1], sample rate) for one chunk of plain text."""
        ...

    def close(self) -> None: ...


# --- model files -------------------------------------------------------------------------------

_DIGESTS: dict[tuple[str, int, int, int, int], str] = {}  # file state -> SHA-256, per process
_DIGESTS_LOCK = threading.Lock()


def _sha256_file(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _digest(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino)
    with _DIGESTS_LOCK:
        known = _DIGESTS.get(key)
    if known is None:
        known = _sha256_file(path)  # outside the lock: a 2 GB file takes seconds
        with _DIGESTS_LOCK:
            _DIGESTS[key] = known
    return known


def _entries(root: Path) -> Iterator[Path]:
    """Every file, folder and link under root, never following a link; sorted per folder."""
    for folder, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(dirs + files):
            yield Path(folder, name)


def _absent(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError:  # a parent is a file: damage(), not a pending download
        return False
    return False


class ModelFiles:
    """The pinned files of one engine under `model_dir`: stat checks and a memoized SHA-256."""

    def __init__(self, model_dir: Path, files: Sequence[PinnedFile]) -> None:
        self.model_dir = Path(model_dir)
        self.files = tuple(files)

    def _path(self, pinned: PinnedFile) -> Path | None:
        """model_dir/rel, or None for a name that could leave the folder."""
        parts = pinned.rel.split("/")
        if "\\" in pinned.rel or any(part in ("", ".", "..") for part in parts):
            return None
        return self.model_dir.joinpath(*parts)

    def missing(self) -> tuple[PinnedFile, ...]:
        """Stat only: the pinned files not on disk yet (download pending, not damage)."""
        return tuple(f for f in self.files if (path := self._path(f)) is not None and _absent(path))

    def damage(self) -> str | None:
        """Stat only: the first defect other than a missing file, else None. Symlinks, unsafe
        names, pickle-capable suffixes, unpinned *.safetensors in the folder, wrong sizes."""
        pinned: dict[Path, PinnedFile] = {}
        for f in self.files:
            if (path := self._path(f)) is None:
                return f"unsafe file name {f.rel!r}"
            pinned[path] = f
        if self.model_dir.is_symlink():
            return "the model folder is a symlink"
        # load_weights globs the folder, so a stray file is as dangerous as a bad pinned one.
        for path in _entries(self.model_dir):
            rel = path.relative_to(self.model_dir).as_posix()
            suffix = path.suffix.lower()
            if path.is_symlink():
                return f"{rel} is a symlink"
            if suffix in FORBIDDEN_SUFFIXES:
                return f"unexpected pickle-capable file {rel}"
            if suffix == ".safetensors" and path not in pinned:
                return f"unpinned weights {rel}"
        for path, f in pinned.items():
            try:
                st = path.lstat()
            except FileNotFoundError:
                continue  # not downloaded yet: missing(), not damage
            except NotADirectoryError:
                return f"{f.rel} is not a file"
            if not stat.S_ISREG(st.st_mode):
                return f"{f.rel} is not a file"
            if st.st_size != f.size:
                return f"wrong size for {f.rel} ({st.st_size:,} B, expected {f.size:,} B)"
        return None

    def problem(self) -> str | None:
        """Stat only: damage() first, then the first missing file; None = all present and sized."""
        if (damage := self.damage()) is not None:
            return damage
        missing = self.missing()
        return f"{missing[0].rel} is missing" if missing else None

    def verify(self) -> str | None:
        """problem(), then the SHA-256 of each pinned file; None = all match. Digests are memoized
        per process by file state (path, size, mtime, ctime, inode): an unchanged file is hashed
        once, and a mismatch stays until the file changes."""
        if (problem := self.problem()) is not None:
            return problem
        for f in self.files:
            if _digest(self.model_dir / f.rel) != f.sha256.lower():
                return f"SHA-256 mismatch for {f.rel}"
        return None


# --- text --------------------------------------------------------------------------------------

_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*$")
_CLAUSE_END = re.compile(r"[;:,][\"'”’)\]]*$")
# Preferred breaks, strongest first; the last level makes every word a run of its own.
_BREAKS: tuple[Callable[[str], object], ...] = (
    _SENTENCE_END.search,
    _CLAUSE_END.search,
    lambda word: True,
)


def _runs(words: list[str], ends: Callable[[str], object]) -> Iterator[list[str]]:
    run: list[str] = []
    for word in words:
        run.append(word)
        if ends(word):
            yield run
            run = []
    if run:
        yield run


def _split(words: list[str], level: int, max_chars: int) -> list[str]:
    """Pieces of at most max_chars, broken at the strongest level that fits, packed greedily."""
    joined = " ".join(words)
    if len(joined) <= max_chars:
        return [joined]
    if level == len(_BREAKS):  # one word longer than max_chars
        return [joined[i : i + max_chars] for i in range(0, len(joined), max_chars)]
    pieces: list[str] = []
    for run in _runs(words, _BREAKS[level]):
        for piece in _split(run, level + 1, max_chars):
            if pieces and len(pieces[-1]) + 1 + len(piece) <= max_chars:
                pieces[-1] += " " + piece
            else:
                pieces.append(piece)
    return pieces


def chunk_text(text: str, *, max_chars: int, min_chars: int = 0) -> list[str]:
    """Split ONE segment's text into chunks of at most max_chars, every word kept in order.

    Breaks at sentence ends, then at `;:,`, then at spaces (a longer word is cut). A chunk shorter
    than min_chars joins its neighbor in this text, so a chunk may run past max_chars by up to two
    such fragments. Needs 0 <= min_chars <= max_chars // 2. Never call it on joined segments:
    nothing merges across a segment's pause.
    """
    if not isinstance(text, str):
        raise TypeError(f"chunk_text takes one segment's text, got {type(text).__name__}")
    if max_chars < 1 or not 0 <= min_chars <= max_chars // 2:
        raise ValueError(
            f"chunk_text needs max_chars >= 1 and 0 <= min_chars <= max_chars // 2, "
            f"got max_chars={max_chars}, min_chars={min_chars}"
        )
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    for chunk in _split(words, 0, max_chars):
        if chunks and (len(chunk) < min_chars or len(chunks[-1]) < min_chars):
            chunks[-1] += " " + chunk
        else:
            chunks.append(chunk)
    return chunks


def est_seconds(text: str, chars_per_s: float = 14.0) -> float:
    """Expected speech length of `text`, at least MIN_EST_S."""
    if chars_per_s <= 0:
        raise ValueError(f"chars_per_s must be positive, got {chars_per_s}")
    return max(MIN_EST_S, len(" ".join(text.split())) / chars_per_s)


def seed_for(voice_key: str, text: str, attempt: int = 0) -> int:
    """Deterministic 32-bit seed per (voice, text, attempt): the same reading sounds the same."""
    # ASCII-escaped JSON hashes any str, even one holding a lone surrogate from a bad paste.
    blob = json.dumps([voice_key, text, attempt]).encode("ascii")
    return int.from_bytes(hashlib.sha256(blob).digest()[:4], "big")


# --- audio -------------------------------------------------------------------------------------


def write_pcm16(path: Path, samples: np.ndarray, rate: int = SAMPLE_RATE) -> None:
    """Write mono 16-bit PCM WAV; samples are clipped to [-1, 1], NaN becomes silence."""
    if rate <= 0:
        raise ValueError(f"sample rate must be positive, got {rate}")
    mono = np.squeeze(np.asarray(samples, dtype=np.float32))
    if mono.ndim > 1:
        raise ValueError(f"write_pcm16 takes mono samples, got shape {np.shape(samples)}")
    clean = np.nan_to_num(mono.reshape(-1), nan=0.0, posinf=1.0, neginf=-1.0)
    pcm = np.rint(np.clip(clean, -1.0, 1.0) * 32767.0).astype("<i2")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(int(rate))
        out.writeframes(pcm.tobytes())


def silence(ms: int, rate: int = SAMPLE_RATE) -> np.ndarray:
    """Exactly round(rate * ms / 1000) float32 zeros."""
    if ms < 0:
        raise ValueError(f"silence needs ms >= 0, got {ms}")
    return np.zeros(round(rate * ms / 1000), dtype=np.float32)


# --- short units -------------------------------------------------------------------------------

_FRAME_MS = 10
_GAP_MS = 100  # a pause between two spoken copies; a stop inside a word is shorter
_QUIET = 0.1  # a gap frame sits at least 20 dB under the speech level
_FADE_MS = 5
_SHOWN = 32  # characters of a unit quoted in an error


def crop_first_repeat(samples: np.ndarray, rate: int, copies: int = 3) -> np.ndarray | None:
    """The first of `copies` spoken copies of one unit, cut in the middle of the quietest gap
    near where that copy should end, with a 5 ms fade out. None when there is no clear gap."""
    if copies < 2:
        raise ValueError(f"crop_first_repeat needs copies >= 2, got {copies}")
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    frame = max(1, rate * _FRAME_MS // 1000)
    count = len(audio) // frame
    if count < 3 * copies:
        return None
    frames = audio[: count * frame].reshape(count, frame).astype(np.float64)
    rms = np.sqrt(np.mean(np.square(frames), axis=1))
    level = float(np.percentile(rms, 90))  # the speech level
    if level <= 0.0:
        return None
    quiet = rms <= _QUIET * level
    edges = np.flatnonzero(np.diff(np.concatenate(([0], quiet, [0])).astype(np.int8)))
    expected = count / copies  # frames per copy
    gaps = [
        (float(rms[start:end].mean()), start - end, start, end)  # quietest, longest, earliest
        for start, end in zip(edges[::2], edges[1::2], strict=True)
        if (end - start) * _FRAME_MS >= _GAP_MS
        and 0.5 * expected <= (start + end) / 2 < 1.5 * expected
        and not quiet[:start].all()  # speech before it: not a leading silence
    ]
    if not gaps:
        return None
    _, _, start, end = min(gaps)
    first = audio[: (start + end) * frame // 2].copy()
    fade = min(len(first), rate * _FADE_MS // 1000)
    first[len(first) - fade :] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return first


def _attempt(
    backend: TextBackend,
    text: str,
    voice_id: str,
    *,
    seed: int,
    est: float,
    title: str,
    errors: list[Exception],
) -> tuple[np.ndarray, int] | None:
    """One render: (samples, rate), or None when it raised, gave under 0.1 s, or ran away.
    EngineUnavailable passes through: another seed cannot help. The text is never logged."""
    try:
        samples, rate = backend.render(text, voice_id, seed=seed, budget_s=max(2.0, 2 * est))
    except EngineUnavailable:
        raise
    except Exception as exc:  # one bad generation: the next attempt may do
        log.info("%s: a render attempt raised %s", title, type(exc).__name__)
        errors.append(exc)
        return None
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    seconds = len(audio) / rate if rate > 0 else 0.0
    if seconds < 0.1 or seconds >= RUNAWAY * est:
        log.info("%s: a render attempt gave %.2f s for a %.2f s estimate", title, seconds, est)
        return None
    return audio, rate


def render_text(
    backend: TextBackend,
    voice_key: str,
    voice_id: str,
    text: str,
    *,
    title: str,
    chars_per_s: float = 14.0,
    memo: dict | None = None,
) -> tuple[np.ndarray, int]:
    """Audio for one chunk of one segment, through the short-unit ladder.

    The chunk alone with attempts 0 and 1, plus attempt 2 when it has SHORT_CHARS or more
    characters. A shorter unit then goes out as three copies with attempt 2, and
    crop_first_repeat keeps the first; no carrier word is ever spoken. Else EngineError. Audio of
    MEMO_MAX_S or less is memoized in `memo` by (voice_key, text), read-only, the least recently
    used dropped past MEMO_LIMIT.
    """
    unit = " ".join(text.split())
    if not unit:
        raise ValueError("render_text needs some text to say")
    key = (voice_key, unit)
    if memo is not None and key in memo:
        memo[key] = memo.pop(key)  # now the most recently used
        return memo[key]
    est = est_seconds(unit, chars_per_s)
    short = len(unit) < SHORT_CHARS
    errors: list[Exception] = []
    result = None
    for attempt in range(2 if short else 3):
        seed = seed_for(voice_key, unit, attempt)
        result = _attempt(backend, unit, voice_id, seed=seed, est=est, title=title, errors=errors)
        if result is not None:
            break
    if result is None and short:
        # A stop after each copy makes the model pause there, where the crop cuts.
        copy = unit if _SENTENCE_END.search(unit) else unit + "."
        seed = seed_for(voice_key, unit, 2)
        said = " ".join([copy] * 3)
        repeated = _attempt(
            backend, said, voice_id, seed=seed, est=3 * est, title=title, errors=errors
        )
        if repeated is not None:
            first = crop_first_repeat(*repeated)
            if first is not None and len(first) >= 0.1 * repeated[1]:
                result = (first, repeated[1])
    if result is None:
        shown = unit if len(unit) <= _SHOWN else unit[: _SHOWN - 1].rstrip() + "…"
        cause = errors[-1] if errors else None
        raise EngineError(f"{title} could not say {shown!r}; try another voice") from cause
    samples, rate = result
    if memo is None or len(samples) > MEMO_MAX_S * rate:
        return samples, rate
    kept = samples.copy()
    kept.flags.writeable = False  # shared by every later reading of this unit
    memo[key] = (kept, rate)
    while len(memo) > MEMO_LIMIT:
        del memo[next(iter(memo))]
    return memo[key]


# --- pronunciation -----------------------------------------------------------------------------

_STYLES = ("hyphen", "join", "space")
_UNSAID = re.compile(r"[^\w\s'’-]|_")  # a respelling keeps letters, digits, spaces, ' and -


@dataclass(frozen=True)
class Speakable:
    text: str  # the segment text, each respelled override replaced by its respelling
    unspoken: tuple[str, ...]  # IPA-only override surfaces in the text: said as printed
    missing: tuple[str, ...] = ()  # override surfaces not found in the segment text


def _say(respelling: str, style: str) -> str:
    said = _UNSAID.sub("", respelling.lower())
    if style == "join":
        said = said.replace("-", "")
    elif style == "space":
        said = said.replace("-", " ")
    return " ".join(said.split())


def speakable(
    segment: Segment, *, style: Literal["hyphen", "join", "space"] = "hyphen"
) -> Speakable:
    """Plain text for an engine without IPA input: whole words, longest surface first.

    A respelling is lowercased; hyphens, spaces and apostrophes stay, other punctuation goes.
    `style` treats its hyphens: "hyphen" keeps them, "join" drops them, "space" makes them spaces.
    """
    if style not in _STYLES:
        raise ValueError(f"style must be one of {_STYLES}, got {style!r}")
    surfaces: dict[str, None] = {}  # every override surface, in order
    said: dict[str, str] = {}  # surface -> respelling to say instead
    for ov in segment.overrides:
        if not ov.surface:
            continue
        surfaces.setdefault(ov.surface)
        if ov.surface not in said and (spoken := _say(ov.respelling, style)):
            said[ov.surface] = spoken
    if not surfaces:
        return Speakable(segment.text, ())
    # One pass: a respelling is never matched again by a shorter surface.
    words = "|".join(re.escape(s) for s in sorted(surfaces, key=len, reverse=True))
    found: set[str] = set()

    def swap(match: re.Match[str]) -> str:
        found.add(match.group())
        return said.get(match.group(), match.group())

    text = re.sub(rf"(?<!\w)(?:{words})(?!\w)", swap, segment.text)
    return Speakable(
        text,
        tuple(s for s in surfaces if s in found and s not in said),
        tuple(s for s in surfaces if s not in found),
    )


# --- packages ----------------------------------------------------------------------------------


def _apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def _find_spec(name: str, path: Sequence[str] | None) -> ModuleSpec | None:
    """What the import system would find for `name` on `path`. Runs no module code."""
    for finder in sys.meta_path:
        find = getattr(finder, "find_spec", None)
        if find is None or isinstance(finder, _PatchOnLoad):
            continue
        try:
            spec = find(name, path)
        except (ImportError, ValueError):
            continue
        if spec is not None:
            return spec
    return None


def _present(name: str) -> bool:
    """Whether `name` can be imported, decided without importing it or its parents."""
    if name in sys.modules:
        return sys.modules[name] is not None
    parts = name.split(".")
    path: list[str] | None = None  # where the next part is searched; None = sys.path
    for depth in range(1, len(parts) + 1):
        prefix = ".".join(parts[:depth])
        if prefix in sys.modules:
            module = sys.modules[prefix]
            if module is None:
                return False
            locations = getattr(module, "__path__", None)
        else:
            spec = _find_spec(prefix, path)
            if spec is None:
                return False
            locations = spec.submodule_search_locations
        if depth < len(parts):
            if locations is None:
                return False
            path = list(locations)
    return True


def mlx_support(modules: Sequence[str], subpackage: str) -> str | None:
    """Hard reason the MLX backend cannot exist here, else None. Never imports anything.

    `modules` are top-level packages (find_spec only). `subpackage` is a full dotted name such as
    "mlx_audio.tts.models.chatterbox_turbo" (slashes also work), located on its parent's path:
    find_spec on a dotted name would import mlx_audio.tts, which imports mlx.core.
    Reasons: "needs an Apple Silicon Mac (arm64)", "backend packages missing: a, b" (a source
    run), "not in this build" (no model subpackage, or any missing package inside an .app).
    """
    if not _apple_silicon():
        return "needs an Apple Silicon Mac (arm64)"
    missing = [m for m in modules if not _present(m)]
    if missing and not is_frozen():
        return f"backend packages missing: {', '.join(missing)}"
    if missing or not _present(subpackage.replace("/", ".")):  # an .app built without engines
        return "not in this build"
    return None


# --- warnings ----------------------------------------------------------------------------------


class EngineWarnings:
    """Notes for the calling thread's latest synthesize(), deduplicated, in order."""

    def __init__(self) -> None:
        self._local = threading.local()

    def _items(self) -> list[str]:
        items = getattr(self._local, "items", None)
        if items is None:
            items = self._local.items = []
        return items

    def reset(self) -> None:
        self._local.items = []

    def add(self, message: str) -> None:
        items = self._items()
        if message not in items:
            items.append(message)

    def snapshot(self) -> list[str]:
        return list(self._items())


# --- guards ------------------------------------------------------------------------------------

_DOWNLOADS = ("snapshot_download", "hf_hub_download")
# Every module a download function is reached through, by the names it is bound to there.
_BINDINGS: dict[str, tuple[str, ...]] = {
    "huggingface_hub": _DOWNLOADS,
    "huggingface_hub.file_download": ("hf_hub_download",),
    "huggingface_hub._snapshot_download": ("snapshot_download",),
    "mlx_audio.utils": ("snapshot_download",),
}
_HUB_CONSTANTS = "huggingface_hub.constants"
_OFFLINE_ENV = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
_ABSENT = object()


def _blocked(name: str) -> Callable[..., Any]:
    def stub(*args: object, **kwargs: object) -> Any:
        raise EngineUnavailable(f"{name} is blocked: engine models load only from local files")

    stub.__name__ = stub.__qualname__ = f"blocked_{name}"
    return stub


class _OfflinePatch:
    """One guard's module changes, undone in reverse order."""

    def __init__(self) -> None:
        self._stubs = {name: _blocked(name) for name in _DOWNLOADS}
        self._saved: list[tuple[ModuleType, str, object]] = []

    def apply(self, name: str, module: ModuleType) -> None:
        if name == _HUB_CONSTANTS:
            self._set(module, "HF_HUB_OFFLINE", True)
        for attr in _BINDINGS.get(name, ()):
            self._set(module, attr, self._stubs[attr])

    def _set(self, module: ModuleType, attr: str, value: object) -> None:
        # vars(), not getattr(): reading a lazy huggingface_hub attribute would import it.
        self._saved.append((module, attr, vars(module).get(attr, _ABSENT)))
        setattr(module, attr, value)

    def undo(self) -> None:
        for module, attr, old in reversed(self._saved):
            if old is _ABSENT:
                vars(module).pop(attr, None)
            else:
                setattr(module, attr, old)
        self._saved.clear()


_ACTIVE: list[_OfflinePatch] = []  # guards in effect, outermost first


class _LoadThenPatch:
    """Loader wrapper: runs the module with its real loader, then applies the active guards."""

    def __init__(self, name: str, loader: Any) -> None:
        self._name = name
        self._loader = loader

    def create_module(self, spec: ModuleSpec) -> ModuleType | None:
        return self._loader.create_module(spec)

    def exec_module(self, module: ModuleType) -> None:
        module.__loader__ = self._loader  # the module never sees the wrapper
        if module.__spec__ is not None:
            module.__spec__.loader = self._loader
        self._loader.exec_module(module)
        for patch in _ACTIVE:
            patch.apply(self._name, module)


class _PatchOnLoad:
    """Meta path finder, present while a guard is: a watched module first imported inside the
    guard is patched as soon as its code has run, before anyone can call into it."""

    def find_spec(
        self, name: str, path: Sequence[str] | None = None, target: object = None
    ) -> ModuleSpec | None:
        if name != _HUB_CONSTANTS and name not in _BINDINGS:
            return None
        spec = _find_spec(name, path)
        if spec is not None and hasattr(spec.loader, "exec_module"):
            spec.loader = _LoadThenPatch(name, spec.loader)
        return spec


_HOOK = _PatchOnLoad()


@contextmanager
def offline_guard() -> Iterator[None]:
    """No Hugging Face download while model code runs; every change is undone on exit.

    Sets HF_HUB_OFFLINE and TRANSFORMERS_OFFLINE, huggingface_hub.constants.HF_HUB_OFFLINE, and
    replaces snapshot_download and hf_hub_download (in huggingface_hub, its defining modules and
    mlx_audio.utils) with stubs raising EngineUnavailable. A module first imported inside the
    guard is patched as it loads, and keeps what it bound then. One thread at a time: hold SLOT.
    """
    patch = _OfflinePatch()
    saved_env = {name: os.environ.get(name) for name in _OFFLINE_ENV}
    try:
        os.environ.update(dict.fromkeys(_OFFLINE_ENV, "1"))
        for name in (_HUB_CONSTANTS, *_BINDINGS):
            if (module := sys.modules.get(name)) is not None:
                patch.apply(name, module)
        _ACTIVE.append(patch)
        if len(_ACTIVE) == 1:
            sys.meta_path.insert(0, _HOOK)
        yield
    finally:
        if patch in _ACTIVE:
            _ACTIVE.remove(patch)
        if not _ACTIVE:
            with suppress(ValueError):
                sys.meta_path.remove(_HOOK)
        patch.undo()
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@contextmanager
def quiet() -> Iterator[None]:
    """Discard what model code prints to stdout and stderr (prints, tqdm bars)."""
    with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
        yield


# --- resident models ---------------------------------------------------------------------------


def _ram_bytes() -> int:
    """Physical memory, or 0 when the system will not say (then one slot)."""
    try:
        return max(0, os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (ValueError, OSError):
        return 0


class ModelSlot:
    """At most `capacity` engine models resident; None means 2 with BIG_RAM or more, else 1.
    acquire() before a load closes the oldest other owner past capacity; release() forgets an
    owner that unloaded itself. `with slot:` serializes loads. A close callback runs without the
    slot's bookkeeping lock held."""

    def __init__(self, capacity: int | None = None, *, ram_bytes: int | None = None) -> None:
        if capacity is None:
            ram = _ram_bytes() if ram_bytes is None else ram_bytes
            capacity = 2 if ram >= BIG_RAM else 1
        if capacity < 1:
            raise ValueError(f"ModelSlot capacity must be at least 1, got {capacity}")
        self.capacity = capacity
        self._lock = threading.Lock()  # bookkeeping only
        self._load = threading.RLock()  # `with slot:`
        self._owners: dict[str, Callable[[], None]] = {}  # oldest first

    def acquire(self, owner: str, close: Callable[[], None]) -> None:
        with self._lock:
            self._owners.pop(owner, None)
            self._owners[owner] = close  # newest last: never closed by its own acquire
            evicted: list[tuple[str, Callable[[], None]]] = []
            while len(self._owners) > self.capacity:
                oldest = next(iter(self._owners))
                evicted.append((oldest, self._owners.pop(oldest)))
        for name, close_old in evicted:
            try:
                close_old()
            except Exception:  # a model that fails to unload must not block the next one
                log.warning("could not close engine model %r", name, exc_info=True)

    def release(self, owner: str) -> None:
        with self._lock:
            self._owners.pop(owner, None)

    def __enter__(self) -> ModelSlot:
        self._load.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self._load.release()


SLOT = ModelSlot()
