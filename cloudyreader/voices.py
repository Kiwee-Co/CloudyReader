"""Piper voice library: installed scan, cached HF catalog, md5-checked download."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx

from cloudyreader.models import VoiceInfo

_LOG = logging.getLogger(__name__)

CATALOG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
FILE_URL_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
KEY_PREFIX = "piper:"

# A voice name becomes a file name: letters and digits (Unicode: `pt_PT-tugão-medium` exists),
# no separators, no leading dot.
_SAFE_NAME = re.compile(r"[^\W_][\w.-]*")
_MD5 = re.compile(r"[0-9a-f]{32}")

Downloader = Callable[[str, Path], None]  # streams url into dest; raises VoiceDownloadError


class VoiceError(RuntimeError):
    """A voice or the voice catalog is unusable."""


class VoiceDownloadError(VoiceError):
    """A download failed or its content did not match the catalog."""


def is_safe_name(name: str) -> bool:
    return _SAFE_NAME.fullmatch(name) is not None


class HttpDownloader:
    """Streams a URL to a file, following the CDN redirects Hugging Face answers with."""

    def __init__(self, client: httpx.Client | None = None, *, timeout_s: float = 60.0) -> None:
        self._client = client
        self._timeout_s = timeout_s

    def __call__(self, url: str, dest: Path) -> None:
        try:
            if self._client is not None:
                self._fetch(self._client, url, dest)
            else:
                with httpx.Client(timeout=self._timeout_s) as client:
                    self._fetch(client, url, dest)
        except httpx.HTTPError as exc:
            raise VoiceDownloadError(f"download failed for {url}: {exc}") from exc

    @staticmethod
    def _fetch(client: httpx.Client, url: str, dest: Path) -> None:
        with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            with dest.open("wb") as out:
                for chunk in response.iter_bytes(1 << 20):
                    out.write(chunk)


def scan_installed(voices_dir: Path) -> list[VoiceInfo]:
    """Voices that have both `<name>.onnx` and `<name>.onnx.json`, sorted by name."""
    found = (_read_installed(model) for model in sorted(Path(voices_dir).glob("*.onnx")))
    return [voice for voice in found if voice is not None]


def _read_installed(model: Path) -> VoiceInfo | None:
    key = model.name.removesuffix(".onnx")
    config_path = model.with_name(model.name + ".json")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("config is not a JSON object")
    except (OSError, ValueError) as exc:
        _LOG.warning("skipping voice %s: unusable config %s (%s)", key, config_path.name, exc)
        return None
    return _voice(
        key,
        name=None,
        language_code=_dig(config, "language", "code"),
        quality=_dig(config, "audio", "quality"),
        num_speakers=config.get("num_speakers"),
        path=model,
    )


def _voice(
    key: str,
    *,
    name: str | None,
    language_code: str | None,
    quality: str | None,
    num_speakers: Any,
    path: Path | None,
) -> VoiceInfo:
    stem_language, stem_name, stem_quality = _split_key(key)
    return VoiceInfo(
        key=f"{KEY_PREFIX}{key}",
        engine="piper",
        name=name or stem_name,
        language=(language_code or stem_language).replace("_", "-"),
        quality=quality or stem_quality,
        num_speakers=num_speakers if isinstance(num_speakers, int) and num_speakers > 0 else 1,
        installed=path is not None,
        path=path,
    )


def _split_key(key: str) -> tuple[str, str, str]:
    """`en_US-lessac-medium` -> (`en_US`, `lessac`, `medium`); other shapes degrade gracefully."""
    language, _, rest = key.partition("-")
    name, _, quality = rest.rpartition("-")
    if not name:
        return language, rest or key, ""
    return language, name, quality


def _dig(mapping: dict[str, Any], *path: str) -> str | None:
    node: Any = mapping
    for step in path:
        node = node.get(step) if isinstance(node, dict) else None
    return node if isinstance(node, str) and node else None


def _parse_catalog(raw: bytes, source: object) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise VoiceError(f"voice catalog {source} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise VoiceError(f"voice catalog {source} must be a JSON object")
    return data


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)  # the catalog publishes md5; integrity only
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_catalog_path(path: str) -> bool:
    parts = path.split("/")
    return not (path.startswith("/") or "\\" in path or "\0" in path) and all(
        part not in {"", ".", ".."} for part in parts
    )


def _download_plan(name: str, entry: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(file name, url, md5) for the config, then the model. Rejects anything that could escape."""
    files = entry.get("files")
    if not isinstance(files, dict):
        raise VoiceError(f"catalog entry for {name} has no file list")
    for path in files:
        if not _safe_catalog_path(path):
            raise VoiceError(f"unsafe file path {path!r} in the catalog entry for {name}")
    plan = []
    for file_name in (f"{name}.onnx.json", f"{name}.onnx"):  # model last: it marks "installed"
        match = next((p for p in files if PurePosixPath(p).name == file_name), None)
        if match is None:
            raise VoiceError(f"catalog entry for {name} lists no {file_name}")
        digest = files[match].get("md5_digest") if isinstance(files[match], dict) else None
        if not isinstance(digest, str) or not _MD5.fullmatch(digest.lower()):
            raise VoiceError(f"catalog has no valid md5 digest for {file_name}")
        plan.append((file_name, FILE_URL_BASE + quote(match), digest.lower()))
    return plan


@contextmanager
def _staging(parent: Path) -> Iterator[Path]:
    """A private directory beside the target. Only its own contents are removed on exit."""
    stage = Path(tempfile.mkdtemp(prefix=".download-", dir=parent))
    try:
        yield stage
    finally:
        with suppress(OSError):
            for leftover in stage.iterdir():
                with suppress(OSError):
                    leftover.unlink()
            stage.rmdir()


class VoiceManager:
    """Lists, catalogs and downloads Piper voices in `voices_dir`."""

    def __init__(
        self,
        voices_dir: Path,
        catalog_path: Path | None = None,
        *,
        downloader: Downloader | None = None,
    ) -> None:
        self._dir = Path(voices_dir)
        # Same cache name `piper.download_voices` uses.
        self._catalog_path = Path(catalog_path) if catalog_path else self._dir / "voices.json"
        self._download = downloader or HttpDownloader()

    def installed(self) -> list[VoiceInfo]:
        return scan_installed(self._dir)

    def catalog(self) -> list[VoiceInfo]:
        """Voices in the cached catalog, `installed` marked. Empty when nothing is cached."""
        entries = self._read_catalog() or {}
        found = (self._catalog_voice(key, entry) for key, entry in entries.items())
        return [voice for voice in found if voice is not None]

    def refresh_catalog(self) -> list[VoiceInfo]:
        """Fetch the live catalog into the cache. A bad payload leaves the old cache in place."""
        self._catalog_path.parent.mkdir(parents=True, exist_ok=True)
        with _staging(self._catalog_path.parent) as stage:
            fetched = stage / "voices.json"
            self._download(CATALOG_URL, fetched)
            _parse_catalog(fetched.read_bytes(), CATALOG_URL)
            os.replace(fetched, self._catalog_path)
        return self.catalog()

    def download(self, key: str) -> VoiceInfo:
        """Install a catalog voice (`piper:<name>` or `<name>`); every file is md5-checked first."""
        name = key.removeprefix(KEY_PREFIX)
        if not is_safe_name(name):
            raise VoiceError(f"invalid voice key {key!r}")
        entries = self._read_catalog()
        if entries is None:
            raise VoiceError(f"no voice catalog at {self._catalog_path}; call refresh_catalog()")
        if name not in entries:
            raise VoiceError(f"unknown voice {key!r}")
        plan = _download_plan(name, entries[name])
        self._dir.mkdir(parents=True, exist_ok=True)
        with _staging(self._dir) as stage:
            for file_name, url, expected in plan:
                self._download(url, stage / file_name)
                actual = _md5(stage / file_name)
                if actual != expected:
                    raise VoiceDownloadError(
                        f"md5 mismatch for {file_name}: catalog {expected}, downloaded {actual}"
                    )
            for file_name, _, _ in plan:
                os.replace(stage / file_name, self._dir / file_name)
        voice = _read_installed(self._dir / f"{name}.onnx")
        if voice is None:
            raise VoiceDownloadError(f"{name} downloaded but its config is unusable")
        return voice

    def _read_catalog(self) -> dict[str, Any] | None:
        try:
            raw = self._catalog_path.read_bytes()
        except FileNotFoundError:
            return None
        return _parse_catalog(raw, self._catalog_path)

    def _catalog_voice(self, key: str, entry: Any) -> VoiceInfo | None:
        if not isinstance(entry, dict) or not is_safe_name(key):
            _LOG.warning("skipping malformed catalog entry %r", key)
            return None
        model = self._dir / f"{key}.onnx"
        installed = model.exists() and model.with_name(model.name + ".json").exists()
        name = entry.get("name")
        return _voice(
            key,
            name=name if isinstance(name, str) else None,
            language_code=_dig(entry, "language", "code"),
            quality=entry.get("quality") if isinstance(entry.get("quality"), str) else None,
            num_speakers=entry.get("num_speakers"),
            path=model if installed else None,
        )
