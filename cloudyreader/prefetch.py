"""Background download of the pinned voices in assets.lock.json: HTTPS only, SHA-256 checked."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import platform
import re
import stat
import sys
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from cloudyreader import engine_catalog
from cloudyreader.config import Settings
from cloudyreader.engine_catalog import ENGINE_SUFFIXES
from cloudyreader.frozen import bundle_resources_dir

log = logging.getLogger(__name__)

LOCK_NAME = "assets.lock.json"
# Under settings.data_dir, never beside a dest: build_app.sh copies models/kokoro whole.
STAGE_DIR = ".prefetch"
CHUNK = 1 << 20
ATTEMPTS = 3
MAX_HOPS = 5
PROGRESS_INTERVAL_S = 0.1
STALE_PART_S = 24 * 3600
TIMEOUT = httpx.Timeout(30, connect=10)
HEADERS = {"Accept-Encoding": "identity", "User-Agent": "cloudyreader-prefetch/0.1"}

GROUPS = ("models", "voices", "kokoro", "chatterbox_turbo", "qwen3_tts")  # all a lock may name
# Fetch order; the NER model ("models") is never fetched.
FETCHED = {"voices": 0, "kokoro": 1, "chatterbox_turbo": 2, "qwen3_tts": 3}
VOICE_GROUPS = ("voices", "kokoro")
ENGINE_GROUPS = ("chatterbox_turbo", "qwen3_tts")  # each lives in models_dir/<group>
DEST_ROOTS = ("voices", "models")  # .data/<root>/... maps onto Settings.voices_dir / models_dir
# Pickle-capable formats can run code when loaded; fetched files are plain data formats only.
PICKLE_SUFFIXES = (".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".bin")
DATA_SUFFIXES = (".onnx", ".json", ".safetensors", ".txt")  # engine groups: ENGINE_SUFFIXES
DISK_FACTOR = engine_catalog.DISK_FACTOR  # engine groups need missing bytes x this + DISK_MARGIN
DISK_MARGIN = engine_catalog.DISK_MARGIN
KOKORO_REASON = "needs an Apple Silicon Mac with the Kokoro packages"

_SAFE_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"/resolve/[0-9a-f]{40}/")  # an engine URL names the exact commit
_URL = re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)

Outcome = Literal["nothing", "offline", "complete", "partial", "cancelled"]


class PrefetchError(Exception):
    """A download was refused or failed; `retry` marks a failure worth another attempt."""

    def __init__(self, message: str, *, retry: bool = False) -> None:
        super().__init__(message)
        self.retry = retry


class _Cancelled(Exception):
    """The caller set `cancel`."""


@dataclass(frozen=True)
class PrefetchProgress:
    file: str  # the asset's file name, never a URL
    done_bytes: int  # finished files plus the current file's partial bytes
    total_bytes: int
    files_done: int  # files fetched OK
    files_total: int
    # The file's lock group and that group's share of this run. Left out of ==, so an
    # event still equals one built from the five whole-run fields.
    group: str = field(default="", compare=False)
    group_done_bytes: int = field(default=0, compare=False)
    group_total_bytes: int = field(default=0, compare=False)


@dataclass(frozen=True)
class PrefetchResult:
    outcome: Outcome
    files: int = 0  # files fetched and installed by this run
    failed: tuple[str, ...] = ()  # asset file names
    skipped: tuple[str, ...] = ()  # reasons, e.g. "conflict: <path>"


@dataclass(frozen=True)
class Asset:
    name: str
    group: str
    url: str = field(repr=False)  # kept out of repr so a logged Asset never shows a URL
    sha256: str
    size: int
    path: Path  # where the file is installed


@dataclass(frozen=True)
class PrefetchPlan:
    assets: tuple[Asset, ...]  # missing files, in fetch order
    conflicts: tuple[Path, ...] = ()  # present with another size: never touched
    skipped: tuple[str, ...] = ()

    @property
    def total_bytes(self) -> int:
        return sum(asset.size for asset in self.assets)


def find_lock(*, resources_dir: Path | None = None, root: Path | None = None) -> Path | None:
    """The bundled lock of a frozen app first, then the source checkout's; None when neither."""
    resources = resources_dir if resources_dir is not None else bundle_resources_dir()
    source = root if root is not None else Path(__file__).resolve().parents[1]
    candidates = [resources / "assets" / LOCK_NAME] if resources is not None else []
    candidates.append(source / LOCK_NAME)
    return next((path for path in candidates if path.is_file()), None)


def load_assets(lock_path: Path, settings: Settings) -> tuple[Asset, ...]:
    """Every fetched file of the lock, in fetch order. One bad entry rejects the whole lock."""
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PrefetchError(f"unreadable ({type(exc).__name__})") from exc
    version = data.get("version") if isinstance(data, dict) else None
    if version != 1 or isinstance(version, bool):
        raise PrefetchError("version is not 1")
    entries = data.get("assets")
    if not isinstance(entries, list):
        raise PrefetchError("no asset list")
    for index, item in enumerate(entries):
        if not _safe_entry(item):  # the index only: a hostile entry's text is never logged
            raise PrefetchError(f"entry {index} is unsafe or malformed")
    assets = (_asset(item, settings) for item in entries if item["group"] in FETCHED)
    return tuple(sorted(assets, key=_fetch_order))


def _safe_entry(item: Any) -> bool:
    """The same rules as scripts/fetch_assets.py safe_entry (a parity test holds them together)."""
    if not isinstance(item, dict):
        return False
    name, group, url, sha256, dest = (
        item.get(k) for k in ("name", "group", "url", "sha256", "dest")
    )
    size = item.get("size")
    if not all(isinstance(value, str) for value in (name, group, url, sha256, dest)):
        return False
    parts = PurePosixPath(dest).parts
    return (
        _https_url(url)
        and group in GROUPS
        and _SHA256.fullmatch(sha256) is not None
        and type(size) is int
        and size > 0
        and _SAFE_PART.fullmatch(name) is not None
        and not name.lower().endswith(PICKLE_SUFFIXES)
        and (group not in FETCHED or name.lower().endswith(_suffixes(group)))
        and len(parts) >= 2
        and parts[0] == ".data"
        and parts[1] in DEST_ROOTS
        and all(_SAFE_PART.fullmatch(part) for part in parts[1:])
        and (group not in ENGINE_GROUPS or _engine_place(group, parts, url))
    )


def _suffixes(group: str) -> tuple[str, ...]:
    return ENGINE_SUFFIXES if group in ENGINE_GROUPS else DATA_SUFFIXES


def _engine_place(group: str, parts: tuple[str, ...], url: str) -> bool:
    """models_dir/<group> or ONE sub-folder below it, from a URL pinned to a commit."""
    in_place = parts[1:3] == ("models", group) and len(parts) <= 4
    return in_place and _COMMIT.search(urlsplit(url).path) is not None


def _https_url(url: str) -> bool:
    try:
        split = urlsplit(url)
    except ValueError:
        return False
    no_userinfo = split.username is None and split.password is None
    return url.startswith("https://") and bool(split.hostname) and no_userinfo


def _asset(item: dict[str, Any], settings: Settings) -> Asset:
    root, *rest = PurePosixPath(item["dest"]).parts[1:]
    base = settings.voices_dir if root == "voices" else settings.models_dir
    path = base.joinpath(*rest, item["name"])
    return Asset(item["name"], item["group"], item["url"], item["sha256"], item["size"], path)


def _fetch_order(asset: Asset) -> tuple[int, bool, int]:
    # Configs before models: a Piper .onnx or the Kokoro model without its config is unusable.
    # Kokoro voices (one level deeper) come after the model they need.
    return FETCHED[asset.group], not asset.name.endswith(".json"), len(asset.path.parts)


def _state(asset: Asset) -> Literal["missing", "present", "conflict"]:
    try:
        info = asset.path.stat()  # follows symlinks: a link into the bundle counts by its target
    except FileNotFoundError:
        return "missing"  # absent, or a dangling symlink
    except OSError:
        return "conflict"
    return "present" if stat.S_ISREG(info.st_mode) and info.st_size == asset.size else "conflict"


def kokoro_supported() -> bool:
    """An Apple Silicon Mac with every Kokoro backend package installed."""
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return False
    try:
        from cloudyreader.engines.kokoro import BACKEND_MODULES  # numpy loads only when asked

        return all(importlib.util.find_spec(name) is not None for name in BACKEND_MODULES)
    except (ImportError, ValueError):
        return False


def open_https(
    client: httpx.Client,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    max_hops: int = MAX_HOPS,
) -> httpx.Response:
    """GET `url` as a stream, following at most `max_hops` redirects by hand, each HTTPS only.

    The caller closes the response; `response.history` holds the redirects that led to it.
    Raises PrefetchError (its message never holds a URL) or httpx.TransportError.
    """
    sent = {**HEADERS, **(headers or {})}
    target = _parse(url, "URL")
    history: list[httpx.Response] = []
    while True:
        request = client.build_request("GET", target, headers=sent, timeout=TIMEOUT)
        response = client.send(request, stream=True, follow_redirects=False)
        if not response.is_redirect:
            response.history = history
            return response
        response.close()
        if len(history) == max_hops:
            raise PrefetchError(f"more than {max_hops} redirects")
        history.append(response)
        target = _parse(str(response.url.join(response.headers["Location"])), "redirect")


def _parse(url: str, what: str) -> httpx.URL:
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise PrefetchError(f"refused a malformed {what}") from exc
    if parsed.scheme != "https" or not parsed.host:
        raise PrefetchError(f"refused a non-HTTPS {what}")
    return parsed


def _describe(exc: BaseException) -> str:
    """Type and message with every URL masked: a redirect target can carry a signed token."""
    text = _URL.sub("<url>", str(exc))
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _check_dir(directory: Path) -> None:
    """Refuse a directory that resolves into an app bundle: writing there breaks its signature."""
    try:
        resolved = directory.resolve()
    except (OSError, RuntimeError) as exc:
        raise PrefetchError(f"cannot resolve {directory} ({type(exc).__name__})") from exc
    if any(part.lower().endswith(".app") for part in resolved.parts):
        raise PrefetchError(f"{directory} lies inside an app bundle")


def _make_dir(directory: Path, *, mode: int = 0o777) -> Path:
    _check_dir(directory)
    directory.mkdir(mode=mode, parents=True, exist_ok=True)
    return directory


@dataclass
class _Job:
    """The mutable state of one run."""

    progress: Callable[[PrefetchProgress], None] | None
    cancel: threading.Event
    files: int = 0
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    total: int = 0
    count: int = 0
    base: int = 0  # bytes of the files already finished, fetched or not
    current: int = 0  # most bytes of the current file any attempt wrote: progress never drops
    group_total: dict[str, int] = field(default_factory=dict)
    group_base: dict[str, int] = field(default_factory=dict)
    asset: Asset | None = None  # the file in flight
    last_emit: float = 0.0
    warned: bool = False

    def result(self, outcome: Outcome) -> PrefetchResult:
        return PrefetchResult(outcome, self.files, tuple(self.failed), tuple(self.skipped))

    def finish(self, asset: Asset) -> None:
        """Count `asset` as done, fetched or not, so progress still ends at the total."""
        self.base += asset.size
        self.group_base[asset.group] = self.group_base.get(asset.group, 0) + asset.size
        self.current = 0

    def emit(self, asset: Asset, *, force: bool = False) -> None:
        if self.progress is None:
            return
        now = time.monotonic()
        if not force and now - self.last_emit < PROGRESS_INTERVAL_S:
            return
        self.last_emit = now
        group = asset.group
        event = PrefetchProgress(
            asset.name,
            self.base + self.current,
            self.total,
            self.files,
            self.count,
            group,
            self.group_base.get(group, 0) + self.current,
            self.group_total.get(group, 0),
        )
        try:
            self.progress(event)
        except Exception:
            if not self.warned:
                self.warned = True
                log.warning("voice download: progress callback failed; ignoring it", exc_info=True)


class VoicePrefetch:
    """Fetches the missing files of the lock's FETCHED groups into the user's data folders.

    Seams: `groups` limits the run; `ready` maps a group to a check that returns why it cannot
    download here (asked only when that group misses a file); `free_bytes` measures free disk.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        lock_path: Path | None = None,
        client: httpx.Client | None = None,
        kokoro_ready: Callable[[], bool] | None = None,
        retry_delay_s: float = 2.0,
        groups: Sequence[str] | None = None,
        ready: Mapping[str, Callable[[], str | None]] | None = None,
        free_bytes: Callable[[Path], int] | None = None,
    ) -> None:
        self._settings = settings
        self._lock_path = lock_path
        self._client = client
        self._retry_delay_s = retry_delay_s
        self._groups = tuple(FETCHED) if groups is None else tuple(groups)
        kokoro = kokoro_ready or kokoro_supported
        checks: dict[str, Callable[[], str | None]] = {
            "kokoro": lambda: None if kokoro() else KOKORO_REASON
        }
        for group in ENGINE_GROUPS:  # looked up at call time, so tests can swap the catalog
            checks[group] = lambda group=group: engine_catalog.ready_reason(group)
        self._ready = checks | dict(ready or {})
        self._free_bytes = free_bytes

    @property
    def _stage(self) -> Path:
        return self._settings.data_dir / STAGE_DIR

    def plan(self, groups: Sequence[str] | None = None) -> PrefetchPlan:
        """What `run` would fetch. Reads the lock and stats files; no network, no writes."""
        wanted = set(self._groups if groups is None else groups)
        lock = self._lock_path or find_lock()
        if lock is None or not lock.is_file():
            return PrefetchPlan((), skipped=(f"no {LOCK_NAME}",))
        try:
            assets = load_assets(lock, self._settings)  # checks every entry, then we filter
        except PrefetchError as exc:
            log.warning("voice download: %s rejected: %s; nothing is downloaded", lock, exc)
            return PrefetchPlan((), skipped=(f"invalid {LOCK_NAME}: {exc}",))
        missing: list[Asset] = []
        conflicts: list[Path] = []
        for asset in assets:
            if asset.group not in wanted:
                continue
            state = _state(asset)
            if state == "missing":
                missing.append(asset)
            elif state == "conflict":
                log.warning(
                    "voice download: %s is not the pinned %d bytes; left untouched",
                    asset.path,
                    asset.size,
                )
                conflicts.append(asset.path)
        skipped = [f"conflict: {path}" for path in conflicts]
        for group in FETCHED:
            need = sum(a.size for a in missing if a.group == group)
            reason = (self._ready_reason(group) or self._room_reason(group, need)) if need else None
            if reason:  # a group that cannot use its files never downloads them
                missing = [a for a in missing if a.group != group]
                skipped.append(f"{group}: {reason}")
                log.info("voice download: %s skipped: %s", group, reason)
        return PrefetchPlan(tuple(missing), tuple(conflicts), tuple(skipped))

    def _ready_reason(self, group: str) -> str | None:
        check = self._ready.get(group)
        if check is None:
            return None
        try:
            return check()
        except Exception as exc:
            log.warning("voice download: the %s check failed: %s", group, _describe(exc))
            return f"check failed ({type(exc).__name__})"

    def _room_reason(self, group: str, missing_bytes: int) -> str | None:
        """For an engine group: a models folder that takes files, and the disk for them."""
        if group not in ENGINE_GROUPS:
            return None  # voices and Kokoro keep their old behavior
        folder = self._settings.models_dir / group
        return engine_catalog.write_reason(folder) or engine_catalog.space_reason(
            folder, missing_bytes, self._free_bytes
        )

    def _label(self, asset: Asset) -> str:
        """How a failed file is reported: its name, or "<group>/<rel>" for an engine file."""
        if asset.group not in ENGINE_GROUPS:
            return asset.name
        rel = asset.path.relative_to(self._settings.models_dir / asset.group)
        return f"{asset.group}/{rel.as_posix()}"

    def run(
        self,
        progress: Callable[[PrefetchProgress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> PrefetchResult:
        """Fetch every missing file. Blocking, safe on any thread, never raises."""
        if self._settings.offline:
            return PrefetchResult("offline")  # before any request or directory
        job = _Job(progress, cancel if cancel is not None else threading.Event())
        try:
            return self._run(job)
        except Exception as exc:  # the thread must end with a result, whatever went wrong
            frames = "".join(traceback.format_tb(exc.__traceback__))  # code lines, no URL values
            log.error("voice download stopped: %s\n%s", _describe(exc), frames)
            if job.asset is not None:
                job.failed.append(self._label(job.asset))
            return job.result("partial")

    def _run(self, job: _Job) -> PrefetchResult:
        if job.cancel.is_set():
            return PrefetchResult("cancelled")
        self._sweep()
        plan = self.plan()
        job.skipped.extend(plan.skipped)
        if not plan.assets:
            return job.result("nothing")
        job.total, job.count = plan.total_bytes, len(plan.assets)
        for asset in plan.assets:
            job.group_total[asset.group] = job.group_total.get(asset.group, 0) + asset.size
        log.info("voice download: %d file(s), %.1f MB", job.count, job.total / 1e6)
        client = self._client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
        checked: set[str] = set()
        blocked: set[str] = set()
        try:
            for asset in plan.assets:
                if job.cancel.is_set():
                    return job.result("cancelled")
                group = asset.group
                if group in ENGINE_GROUPS and group not in checked:
                    checked.add(group)  # the room may have gone to the groups before this one
                    reason = self._room_reason(group, job.group_total[group])
                    if reason:
                        blocked.add(group)
                        job.skipped.append(f"{group}: {reason}")
                        log.info("voice download: %s skipped: %s", group, reason)
                if group in blocked:
                    job.finish(asset)
                    continue
                job.asset, job.current = asset, 0
                job.emit(asset, force=True)
                done = self._fetch(client, asset, job)
                if done == "fetched":
                    job.files += 1
                elif done == "failed":
                    job.failed.append(self._label(asset))
                else:
                    job.skipped.append(f"exists: {asset.path}")
                job.asset = None
                job.finish(asset)
                job.emit(asset, force=True)
        except _Cancelled:
            return job.result("cancelled")
        finally:
            if client is not self._client:
                client.close()
        return job.result("partial" if job.failed else "complete")

    def _fetch(
        self, client: httpx.Client, asset: Asset, job: _Job
    ) -> Literal["fetched", "failed", "exists"]:
        """One file, with retries for transient failures. Raises _Cancelled.

        One .part serves every attempt, so a retry can resume it with a Range request; it is
        removed when this call ends, so no part outlives the run.
        """
        try:
            _check_dir(asset.path.parent)  # before any byte moves
        except PrefetchError as exc:
            log.warning("voice download: %s refused: %s", self._label(asset), exc)
            return "failed"
        part: Path | None = None
        try:
            attempt = 0
            while True:
                attempt += 1
                try:
                    if part is None:
                        part = _make_dir(self._stage, mode=0o700) / f"{uuid.uuid4().hex}.part"
                    return "fetched" if self._attempt(client, asset, part, job) else "exists"
                except PrefetchError as exc:
                    retry, reason = exc.retry, str(exc)
                except httpx.TransportError as exc:  # connect, read, timeouts, broken streams
                    retry, reason = True, _describe(exc)
                except OSError as exc:  # the local disk: another attempt would fail the same way
                    retry, reason = False, _describe(exc)
                label = self._label(asset)
                if not retry or attempt == ATTEMPTS:
                    log.warning("voice download: %s failed: %s", label, reason)
                    return "failed"
                log.info("voice download: %s attempt %d failed: %s", label, attempt, reason)
                if job.cancel.wait(self._retry_delay_s * attempt):
                    raise _Cancelled
        finally:
            if part is not None:
                part.unlink(missing_ok=True)

    def _attempt(self, client: httpx.Client, asset: Asset, part: Path, job: _Job) -> bool:
        """GET into the part (resuming it when it holds bytes), check size and SHA-256, move it
        in. False: the file appeared meanwhile."""
        offset = _part_size(part)
        if not 0 < offset < asset.size:
            offset = 0  # nothing to resume, or a full part whose check failed: start over
        range_header = {"Range": f"bytes={offset}-"} if offset else None
        response = open_https(client, asset.url, headers=range_header)
        try:
            if offset and not (response.status_code == 206 and _continues(response, asset, offset)):
                if response.status_code in (206, 416):  # the range came back wrong or refused
                    response.close()
                    response = open_https(client, asset.url)
                offset = 0  # a 200 carries the whole file; any other status fails below
            if not offset:
                _check_response(response, asset)
            self._stream(response, asset, part, offset, job)
        finally:
            response.close()
        _make_dir(asset.path.parent)
        if asset.path.exists():  # someone else installed it meanwhile; follows symlinks
            log.info("voice download: %s appeared meanwhile; left as is", asset.path)
            return False
        os.replace(part, asset.path)  # never opens dest: a dangling symlink is replaced
        log.info("voice download: fetched %s", self._label(asset))
        return True

    def _stream(
        self, response: httpx.Response, asset: Asset, part: Path, offset: int, job: _Job
    ) -> None:
        """Write the body into the part after its first `offset` bytes, hashing the whole file."""
        digest = hashlib.sha256()
        if offset:
            with os.fdopen(os.open(part, os.O_RDONLY | os.O_NOFOLLOW), "rb") as kept:
                while block := kept.read(CHUNK):  # re-read: the disk is what gets moved in
                    digest.update(block)
            out = os.fdopen(os.open(part, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW), "ab")
        else:
            part.unlink(missing_ok=True)
            out = part.open("xb")
        written = offset
        with out:
            for chunk in response.iter_raw(CHUNK):
                if job.cancel.is_set():
                    raise _Cancelled
                written += len(chunk)
                if written > asset.size:
                    raise PrefetchError(f"more bytes than the pinned {asset.size}")
                out.write(chunk)
                digest.update(chunk)
                job.current = max(job.current, written)
                job.emit(asset)
            out.flush()
            os.fsync(out.fileno())  # a crash must not leave a short file under the real name
        if written != asset.size:
            raise PrefetchError(f"short read: {written} of {asset.size} bytes", retry=True)
        if digest.hexdigest() != asset.sha256:
            raise PrefetchError("SHA-256 does not match the lock")

    def _sweep(self) -> None:
        """Remove .part files a crashed run left in the stage dir more than a day ago."""
        stage = self._stage
        if stage.is_symlink() or not stage.is_dir():
            return
        cutoff = time.time() - STALE_PART_S
        try:
            for part in stage.glob("*.part"):
                info = part.lstat()
                if stat.S_ISREG(info.st_mode) and info.st_mtime < cutoff:
                    part.unlink()
        except OSError as exc:
            log.info("voice download: stale part sweep stopped: %s", _describe(exc))


def _check_response(response: httpx.Response, asset: Asset) -> None:
    """Fail before the body is read when the status or the announced length is wrong."""
    status = response.status_code
    if status != 200:
        raise PrefetchError(f"HTTP {status}", retry=status == 429 or status >= 500)
    length = response.headers.get("Content-Length")
    if length is not None and length.strip() != str(asset.size):
        raise PrefetchError(f"Content-Length is not the pinned {asset.size}")


def _continues(response: httpx.Response, asset: Asset, offset: int) -> bool:
    """A 206 that holds exactly bytes `offset` to the end of the pinned file."""
    expected = f"bytes {offset}-{asset.size - 1}/{asset.size}"
    length = response.headers.get("Content-Length")
    exact = length is None or length.strip() == str(asset.size - offset)
    return response.headers.get("Content-Range", "").strip() == expected and exact


def _part_size(part: Path) -> int:
    """Bytes in our own part; 0 when there is none (or something else sits at its path)."""
    try:
        info = part.lstat()
    except FileNotFoundError:
        return 0
    return info.st_size if stat.S_ISREG(info.st_mode) else 0
