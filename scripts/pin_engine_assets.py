"""Pin one TTS engine's model files into assets.lock.json. Run it yourself, outside the sandbox.

Usage: make pin-engine ENGINE=chatterbox_turbo
   or: .venv/bin/python scripts/pin_engine_assets.py ENGINE [--rev REV] [--write] [--install]
Resolves REV (default main) to a commit with the Hugging Face model API and lists the repo. Keeps
.safetensors, .json and .txt files with safe names, at most one folder deep, and lists every other
file as skipped. Downloads each kept file from its commit-pinned URL into a new temp dir under
.data (HTTPS-only redirects, a size cap, a free-disk check), then checks its size and SHA-256
against the LFS oid and the research table in engine_catalog.SPECS. Prints names, statuses, byte
counts and hashes, never a URL, a host or a token. --write replaces only this engine's entries in
assets.lock.json; --install also moves the verified files into .data/models/ENGINE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

from cloudyreader.engine_catalog import DISK_FACTOR, DISK_MARGIN, ENGINE_SUFFIXES, SPECS

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "assets.lock.json"
DATA = ROOT / ".data"
API = "https://huggingface.co/api/models"
HUB = "https://huggingface.co"
# Formats that can run code when loaded or imported: listed loudly, never pinned.
CODE_SUFFIXES = (".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".bin", ".npy", ".npz", ".py")
CODE_REASON = "can run code when loaded, never pinned"
MAX_FILE_BYTES = 4 << 30
MAX_JSON_BYTES = 8 << 20
MAX_HOPS = 5
MAX_PAGES = 20
CHUNK = 1 << 20
TIMEOUT_S = 60
HEADERS = {"User-Agent": "cloudyreader-pin/0.1", "Accept-Encoding": "identity"}
_REDIRECTS = (301, 302, 303, 307, 308)
_SAFE_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_HIDDEN = re.compile(r"\.[A-Za-z0-9._-]+")
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_REV = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_NEXT = re.compile(r'<([^>]*)>\s*;\s*rel="?next"?')


class PinError(Exception):
    """The pin cannot finish safely: the lock and the installed files stay as they were."""


@dataclass(frozen=True)
class Reply:
    """One HTTP response with redirects not followed; header names are lower case."""

    status: int
    headers: Mapping[str, str]
    stream: Any  # read(n) and close()


Transport = Callable[[str, Mapping[str, str]], Reply]


@dataclass(frozen=True)
class RemoteFile:
    path: str  # POSIX path in the repo = PinnedFile.rel under models_dir/<engine>
    size: int
    lfs_sha256: str | None

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name


@dataclass(frozen=True)
class Verified:
    file: RemoteFile
    sha256: str
    staged: Path


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """open_https follows redirects itself, so it can refuse HTTP and count the hops."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urllib_transport(url: str, headers: Mapping[str, str]) -> Reply:
    opener = urllib.request.build_opener(_NoRedirects)
    try:
        resp = opener.open(urllib.request.Request(url, headers=dict(headers)), timeout=TIMEOUT_S)
    except urllib.error.HTTPError as exc:  # unfollowed redirects and error statuses
        resp = exc
    except OSError as exc:  # its text can name the host: show the class only
        raise PinError(f"network error: {type(exc).__name__}") from exc
    return Reply(resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp)


def open_https(transport: Transport, url: str, headers: Mapping[str, str]) -> Reply:
    """GET `url`, following at most MAX_HOPS redirects, each to HTTPS. The caller closes it."""
    for _ in range(MAX_HOPS + 1):
        if urlsplit(url).scheme != "https":
            raise PinError("refused a redirect that leaves HTTPS")
        reply = transport(url, headers)
        if reply.status not in _REDIRECTS:
            return reply
        reply.stream.close()
        location = reply.headers.get("location", "")
        if not location:
            raise PinError(f"HTTP {reply.status} redirect without a Location")
        url = urljoin(url, location)
    raise PinError(f"more than {MAX_HOPS} redirects")


def get_json(transport: Transport, url: str) -> tuple[Any, Mapping[str, str]]:
    reply = open_https(transport, url, {**HEADERS, "Accept": "application/json"})
    try:
        if reply.status != 200:
            raise PinError(f"model API: HTTP {reply.status}")
        blob = reply.stream.read(MAX_JSON_BYTES + 1)
    finally:
        reply.stream.close()
    if len(blob) > MAX_JSON_BYTES:
        raise PinError("model API reply is too large")
    try:
        return json.loads(blob), reply.headers
    except ValueError as exc:
        raise PinError("model API reply is not JSON") from exc


def resolve_commit(transport: Transport, repo: str, rev: str) -> str:
    data, _ = get_json(transport, f"{API}/{repo}/revision/{quote(rev, safe='')}")
    sha = data.get("sha") if isinstance(data, dict) else None
    if not isinstance(sha, str) or not _COMMIT.fullmatch(sha):
        raise PinError("the model API returned no commit for that revision")
    return sha


def list_tree(transport: Transport, repo: str, commit: str) -> list[Any]:
    """Every entry of the repo at `commit`, following the API's next-page links."""
    base = f"{API}/{repo}/tree/{commit}"
    url, entries = f"{base}?recursive=true", []
    for _ in range(MAX_PAGES):
        data, headers = get_json(transport, url)
        if not isinstance(data, list):
            raise PinError("unexpected tree listing")
        entries += data
        found = _NEXT.search(headers.get("link", ""))
        if found is None:
            return entries
        url = urljoin(url, found.group(1))
        if not url.startswith(f"{base}?"):
            raise PinError("unexpected pagination link")
    raise PinError(f"the tree listing has more than {MAX_PAGES} pages")


def skip_reason(path: str) -> str | None:
    """Why a repo file is not pinned; None = pin it."""
    parts = path.split("/")
    if not all(_SAFE_PART.fullmatch(p) or _HIDDEN.fullmatch(p) for p in parts):
        return "unsafe name"
    if any(_HIDDEN.fullmatch(p) for p in parts):
        return "hidden file"
    lower = path.lower()
    if lower.endswith(CODE_SUFFIXES):
        return CODE_REASON
    if not lower.endswith(ENGINE_SUFFIXES):
        return "not a data file"
    if len(parts) > 2:
        return "more than one folder deep"
    return None


def select(entries: Sequence[Any]) -> tuple[list[RemoteFile], list[str]]:
    """The files to pin, small files first, and one line for each file that is not pinned."""
    keep: list[RemoteFile] = []
    lines: list[str] = []
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise PinError(f"tree entry #{index} is malformed")
        if item.get("type") != "file":
            continue
        path, size = item.get("path"), item.get("size")
        if not isinstance(path, str) or type(size) is not int or size < 0:
            raise PinError(f"tree entry #{index} is malformed")
        reason = skip_reason(path)
        if reason == "unsafe name":  # a hostile name is never printed
            lines.append(_line("skipped", f"tree entry #{index}: unsafe name, not shown"))
        elif reason is not None:
            lines.append(
                _line("SKIPPED" if reason == CODE_REASON else "skipped", f"{path}: {reason}")
            )
        elif size == 0:
            lines.append(_line("skipped", f"{path}: empty"))
        elif size > MAX_FILE_BYTES:
            raise PinError(f"{path}: {size:,} B is over the {MAX_FILE_BYTES:,} B cap per file")
        else:
            keep.append(RemoteFile(path, size, _lfs_sha256(item, path, size)))
    keep.sort(key=lambda f: (f.size, f.path))
    return keep, lines


def _lfs_sha256(item: Mapping[str, Any], path: str, size: int) -> str | None:
    lfs = item.get("lfs")
    if lfs is None:
        return None
    oid = lfs.get("oid") if isinstance(lfs, dict) else None
    if not isinstance(oid, str) or not _SHA256.fullmatch(oid) or lfs.get("size") != size:
        raise PinError(f"{path}: malformed LFS record")
    return oid


def size_drift(
    files: Sequence[RemoteFile], expect: Mapping[str, tuple[int, str | None]]
) -> list[str]:
    listed = {f.path: f for f in files}
    lines = []
    for rel, (size, _) in sorted(expect.items()):
        found = listed.get(rel)
        if found is None:
            lines.append(
                _line("DRIFT", f"{rel}: in the research table, not pinnable at this commit")
            )
        elif found.size != size:
            said = f"{found.size:,} B, the research table says {size:,} B"
            lines.append(_line("DRIFT", f"{rel}: {said}"))
    return lines


def hash_drift(
    verified: Sequence[Verified], expect: Mapping[str, tuple[int, str | None]]
) -> list[str]:
    lines = []
    for item in verified:
        want = expect.get(item.file.path, (0, None))[1]
        if want is not None and want != item.sha256:
            said = f"sha256 {item.sha256[:12]}, the research table says {want[:12]}"
            lines.append(_line("DRIFT", f"{item.file.path}: {said}"))
    return lines


def resolve_url(repo: str, commit: str, path: str) -> str:
    return f"{HUB}/{repo}/resolve/{commit}/{quote(path)}"


def download(transport: Transport, url: str, file: RemoteFile, part: Path) -> str:
    """Stream one file into `part`, a new file, and return its SHA-256."""
    reply = open_https(transport, url, HEADERS)
    try:
        if reply.status != 200:
            raise PinError(f"{file.path}: HTTP {reply.status}")
        length = reply.headers.get("content-length")
        if length is not None and length.strip() != str(file.size):
            raise PinError(f"{file.path}: Content-Length differs from the {file.size:,} B listed")
        digest, got = hashlib.sha256(), 0
        with part.open("xb") as out:
            while chunk := reply.stream.read(CHUNK):
                got += len(chunk)
                if got > file.size:
                    raise PinError(f"{file.path}: more bytes than the {file.size:,} B listed")
                digest.update(chunk)
                out.write(chunk)
    finally:
        reply.stream.close()
    if got != file.size:
        raise PinError(f"{file.path}: got {got:,} of {file.size:,} B")
    return digest.hexdigest()


def lock_entry(group: str, repo: str, commit: str, item: Verified) -> dict[str, Any]:
    folder = PurePosixPath(item.file.path).parent  # "." vanishes from the dest
    return {
        "name": item.file.name,
        "group": group,
        "url": resolve_url(repo, commit, item.file.path),
        "sha256": item.sha256,
        "size": item.file.size,
        "dest": str(PurePosixPath(".data", "models", group, folder)),
    }


def show_fragment(entries: Sequence[Mapping[str, Any]]) -> None:
    total = sum(e["size"] for e in entries)
    url = "--write adds each url: resolve/<commit>/<path>"
    print(_line("lock", f"{len(entries)} entries, {total:,} B ({url})"))
    for entry in entries:
        print("  " + json.dumps({k: v for k, v in entry.items() if k != "url"}))


def write_lock(lock_path: Path, group: str, entries: Sequence[Mapping[str, Any]]) -> None:
    """Replace `group`'s entries; every other byte stays (the lock is json.dumps(indent=2))."""
    text = lock_path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise PinError(f"{lock_path.name} is not JSON; nothing written") from exc
    if not (
        isinstance(data, dict) and data.get("version") == 1 and isinstance(data.get("assets"), list)
    ):
        raise PinError(f"{lock_path.name} is not a version 1 asset lock; nothing written")
    if _canonical(data) != text:
        raise PinError(
            f"{lock_path.name} is not in the json.dumps(indent=2) layout; nothing written"
        )
    assets = data["assets"]
    mine = [i for i, a in enumerate(assets) if _group(a) == group]
    rest = [a for a in assets if _group(a) != group]
    if mine:
        at = mine[0]  # in place of the old entries
    else:
        order = ["models", "voices", "kokoro", *SPECS]
        at = next(
            (i for i, a in enumerate(rest) if _rank(_group(a), order) > _rank(group, order)),
            len(rest),
        )
    data["assets"] = [*rest[:at], *entries, *rest[at:]]
    fd, tmp = tempfile.mkstemp(prefix=f".{lock_path.name}.", suffix=".tmp", dir=lock_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(_canonical(data))
        os.chmod(tmp, lock_path.stat().st_mode & 0o777)
        os.replace(tmp, lock_path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def install_files(
    verified: Sequence[Verified], entries: Sequence[Mapping[str, Any]], data_dir: Path, group: str
) -> list[str]:
    """Move the verified files into place; report files the pin does not list."""
    targets = [data_dir.joinpath(*PurePosixPath(e["dest"]).parts[1:], e["name"]) for e in entries]
    for item, target in zip(verified, targets, strict=True):  # check all before moving any
        if target.is_symlink():
            raise PinError(f"{item.file.path}: the installed copy is a symlink; nothing installed")
        if _inside_app(target.parent):  # a symlinked folder can still lead into a bundle
            raise PinError(
                f"{item.file.path}: its folder is inside an app bundle; nothing installed"
            )
    lines = []
    for item, target in zip(verified, targets, strict=True):
        if target.is_file() and target.stat().st_size == item.file.size:
            with target.open("rb") as fh:
                if hashlib.file_digest(fh, "sha256").hexdigest() == item.sha256:
                    lines.append(_line("kept", f"{item.file.path}: already installed"))
                    continue
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(item.staged, target)
        lines.append(_line("installed", f"{item.file.path}: {item.file.size:,} B"))
    pinned = {item.file.path for item in verified}
    for rel in _files_under(data_dir / "models" / group):
        if rel not in pinned:
            lines.append(_line("stale", f"{rel}: not in this pin; move it out of the folder"))
    return lines


def pin(
    spec: Any,
    *,
    rev: str,
    write: bool,
    install: bool,
    transport: Transport,
    lock_path: Path,
    data_dir: Path,
    free_bytes: Callable[[Path], int],
) -> int:
    try:
        return _pin(spec, rev, write, install, transport, lock_path, data_dir, free_bytes)
    except PinError as exc:
        print(f"pin_engine_assets: {exc}", file=sys.stderr)
    except OSError as exc:  # local disk trouble: no URL can be in it
        print(f"pin_engine_assets: {type(exc).__name__}: {exc.strerror or exc}", file=sys.stderr)
    return 1


def _pin(
    spec: Any,
    rev: str,
    write: bool,
    install: bool,
    transport: Transport,
    lock_path: Path,
    data_dir: Path,
    free_bytes: Callable[[Path], int],
) -> int:
    if not _REPO.fullmatch(spec.repo) or not _REV.fullmatch(rev):
        raise PinError("bad repo id or revision")
    commit = resolve_commit(transport, spec.repo, rev)
    print(_line("pin", f"{spec.engine}: {spec.repo} at {rev} = commit {commit}"))
    files, skipped = select(list_tree(transport, spec.repo, commit))
    for text in skipped:
        print(text)
    if not files:
        raise PinError("nothing to pin: no .safetensors, .json or .txt file")
    expect = dict(spec.expect)
    for file in files:
        if expect and file.path not in expect:
            print(_line("new", f"{file.path}: not in the research table"))
    _stop_on(size_drift(files, expect), "nothing downloaded")
    if _inside_app(data_dir):
        raise PinError("the data folder is inside an app bundle; nothing downloaded")
    data_dir.mkdir(parents=True, exist_ok=True)
    need = int(sum(f.size for f in files) * DISK_FACTOR) + DISK_MARGIN
    free = free_bytes(data_dir)
    if free < need:
        raise PinError(f"not enough disk space: needs {need:,} B, {free:,} B free")
    # On the data volume, so --install is a rename; removed whatever happens.
    stage = Path(tempfile.mkdtemp(prefix=".pin-", dir=data_dir))
    parts: list[Path] = []
    try:
        verified = []
        for index, file in enumerate(files):
            parts.append(stage / f"{index:03d}-{file.name}")
            digest = download(transport, resolve_url(spec.repo, commit, file.path), file, parts[-1])
            if file.lfs_sha256 is not None and digest != file.lfs_sha256:
                raise PinError(f"{file.path}: SHA-256 does not match the LFS oid; stopped")
            print(_line("ok", f"{file.path}: {file.size:,} B, sha256 {digest[:12]}"))
            verified.append(Verified(file, digest, parts[-1]))
        _stop_on(hash_drift(verified, expect), "nothing written")
        entries = [lock_entry(spec.engine, spec.repo, commit, item) for item in verified]
        show_fragment(entries)
        if write:
            write_lock(lock_path, spec.engine, entries)
            replaced = f"{len(entries)} {spec.engine} entries replace the old ones"
            print(_line("wrote", f"{lock_path.name}: {replaced}"))
        if install:
            for text in install_files(verified, entries, data_dir, spec.engine):
                print(text)
    finally:
        for part in parts:
            part.unlink(missing_ok=True)
        stage.rmdir()
    return 0


def _stop_on(drift: Sequence[str], what: str) -> None:
    for text in drift:
        print(text)
    if drift:
        raise PinError(f"{len(drift)} difference(s) from the research table; {what}")


def _line(status: str, text: str) -> str:
    return f"{status:<8} {text}"


def _canonical(data: Any) -> str:
    return json.dumps(data, indent=2) + "\n"


def _group(asset: Any) -> Any:
    return asset.get("group") if isinstance(asset, dict) else None


def _rank(group: Any, order: Sequence[str]) -> int:
    return order.index(group) if group in order else len(order)


def _inside_app(path: Path) -> bool:
    parts = path.resolve().parts
    return any(
        a.endswith(".app") and b == "Contents" for a, b in zip(parts, parts[1:], strict=False)
    )


def _files_under(folder: Path) -> list[str]:
    found: list[str] = []
    for top, dirs, files in os.walk(folder):
        here = Path(top).relative_to(folder)
        dirs[:] = sorted(d for d in dirs if _SAFE_PART.fullmatch(d))
        found += [(here / f).as_posix() for f in files if _SAFE_PART.fullmatch(f)]
    return sorted(found)


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: Transport = urllib_transport,
    lock_path: Path = LOCK,
    data_dir: Path = DATA,
    free_bytes: Callable[[Path], int] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("engine", choices=list(SPECS), metavar="ENGINE", help=" or ".join(SPECS))
    parser.add_argument("--rev", default="main", help="branch, tag or commit (default: main)")
    parser.add_argument("--write", action="store_true", help="replace its entries in the lock")
    parser.add_argument("--install", action="store_true", help="move the files into the data dir")
    args = parser.parse_args(argv)
    return pin(
        SPECS[args.engine],
        rev=args.rev,
        write=args.write,
        install=args.install,
        transport=transport,
        lock_path=lock_path,
        data_dir=data_dir,
        free_bytes=free_bytes or (lambda path: shutil.disk_usage(path).free),
    )


if __name__ == "__main__":
    sys.exit(main())
