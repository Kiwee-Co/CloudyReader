"""Fetch the pinned assets in assets.lock.json; nothing is used before its SHA256 matches.

Usage: python -I scripts/fetch_assets.py [--group G] [--voices ID ...] [--check|--verify|--paths]
Stdlib only. Each download lands in its own new temp dir, then moves into its dest dir.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "assets.lock.json"
DATA = ROOT / ".data"
MANIFEST = DATA / "downloads.tsv"
CHUNK = 1 << 20
ATTEMPTS = 3
GROUPS = ("models", "voices", "kokoro", "chatterbox_turbo", "qwen3_tts")
ENGINE_GROUPS = ("chatterbox_turbo", "qwen3_tts")
DEST_ROOTS = ("voices", "models")
# Pickle-capable formats can run code when loaded; the lock must never list them. Every group
# but "models" holds plain data only; engine groups a narrower set.
PICKLE_SUFFIXES = (".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".bin")
DATA_SUFFIXES = (".onnx", ".json", ".safetensors", ".txt")
ENGINE_SUFFIXES = (".safetensors", ".json", ".txt")
SAFE_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"/resolve/[0-9a-f]{40}/")


class FetchError(Exception):
    """An asset is missing, invalid, or cannot be fetched safely."""


class HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise FetchError(f"refusing non-HTTPS redirect to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_entry(asset: object) -> bool:
    """The rules of cloudyreader.prefetch._safe_entry, kept identical by a parity test: this
    script stays stdlib-only and runs without the project installed."""
    if not isinstance(asset, dict):
        return False
    name, group, url, sha256, dest = (
        asset.get(k) for k in ("name", "group", "url", "sha256", "dest")
    )
    size = asset.get("size")
    if not all(isinstance(value, str) for value in (name, group, url, sha256, dest)):
        return False
    parts = PurePosixPath(dest).parts
    suffixes = ENGINE_SUFFIXES if group in ENGINE_GROUPS else DATA_SUFFIXES
    return (
        https_url(url)
        and group in GROUPS
        and SHA256.fullmatch(sha256) is not None
        and type(size) is int
        and size > 0
        and SAFE_PART.fullmatch(name) is not None
        and not name.lower().endswith(PICKLE_SUFFIXES)
        and (group == "models" or name.lower().endswith(suffixes))
        and len(parts) >= 2
        and parts[0] == ".data"
        and parts[1] in DEST_ROOTS
        and all(SAFE_PART.fullmatch(part) for part in parts[1:])
        and (group not in ENGINE_GROUPS or engine_place(group, parts, url))
    )


def https_url(url: str) -> bool:
    try:
        split = urlsplit(url)
    except ValueError:
        return False
    no_userinfo = split.username is None and split.password is None
    return url.startswith("https://") and bool(split.hostname) and no_userinfo


def engine_place(group: str, parts: tuple[str, ...], url: str) -> bool:
    """.data/models/<group> or ONE sub-folder below it, from a URL pinned to a commit."""
    in_place = parts[1:3] == ("models", group) and len(parts) <= 4
    return in_place and COMMIT.search(urlsplit(url).path) is not None


def validate(asset: object) -> None:
    if not safe_entry(asset):
        name = asset.get("name") if isinstance(asset, dict) else None
        raise FetchError(f"invalid entry in {LOCK.name}: {name!r}")


def voice_id(asset: dict) -> str:
    return asset["name"].split(".")[0]


def load(groups: list[str], voices: list[str]) -> list[dict]:
    assets = json.loads(LOCK.read_text())["assets"]
    for asset in assets:
        validate(asset)
    unknown = set(voices) - {voice_id(a) for a in assets if a["group"] == "voices"}
    if unknown:
        raise FetchError(f"not in {LOCK.name}: {' '.join(sorted(unknown))} (add url, sha256, size)")
    picked = [a for a in assets if not groups or a["group"] in groups]
    return [a for a in picked if not voices or a["group"] != "voices" or voice_id(a) in voices]


def target(asset: dict) -> Path:
    return ROOT / asset["dest"] / asset["name"]


def rel(asset: dict) -> str:
    return f"{asset['dest']}/{asset['name']}"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def state(asset: dict, deep: bool) -> str:
    path = target(asset)
    if not path.is_file():
        return "missing"
    if path.stat().st_size != asset["size"]:
        return "invalid"
    if deep and sha256_of(path) != asset["sha256"]:
        return "invalid"
    return "ok"


def stream(asset: dict, part: Path) -> str:
    opener = urllib.request.build_opener(HttpsOnlyRedirects)
    request = urllib.request.Request(asset["url"], headers={"User-Agent": "cloudyreader-fetch/0.1"})
    for attempt in range(1, ATTEMPTS + 1):
        digest, size = hashlib.sha256(), 0
        try:
            with opener.open(request, timeout=60) as resp, part.open("wb") as out:
                while chunk := resp.read(CHUNK):
                    size += len(chunk)
                    if size > asset["size"]:
                        raise FetchError(f"{asset['name']}: exceeds pinned size {asset['size']}")
                    digest.update(chunk)
                    out.write(chunk)
            if size != asset["size"]:
                raise OSError(f"short read: {size} of {asset['size']} bytes")
            return digest.hexdigest()
        except OSError as exc:  # URLError is an OSError; client errors are final.
            final = isinstance(exc, urllib.error.HTTPError) and exc.code < 500
            if final or attempt == ATTEMPTS:
                raise FetchError(f"{asset['name']}: download failed: {exc}") from exc
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def download(asset: dict) -> str:
    DATA.mkdir(exist_ok=True)
    # A new empty dir per artifact, on the dest filesystem so the final move is atomic.
    tmp_dir = Path(tempfile.mkdtemp(prefix=".fetch-", dir=DATA))
    part = tmp_dir / asset["name"]
    try:
        digest = stream(asset, part)
        if digest != asset["sha256"]:
            raise FetchError(f"{asset['name']}: SHA256 {digest} != pinned {asset['sha256']}")
        target(asset).parent.mkdir(parents=True, exist_ok=True)
        os.replace(part, target(asset))
    finally:
        part.unlink(missing_ok=True)
        tmp_dir.rmdir()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with MANIFEST.open("a") as fh:
        fh.write(f"{stamp}\t{asset['url']}\t{digest}\t{rel(asset)}\n")
    return digest


def fetch(assets: list[dict], offline: bool) -> int:
    fetched = 0
    for asset in assets:
        status = state(asset, deep=True)
        if status == "ok":
            print(f"ok       {rel(asset)}")
            continue
        if status == "invalid":
            raise FetchError(f"{rel(asset)} fails its size or SHA256; inspect, remove, re-run")
        if offline:
            raise FetchError(f"{rel(asset)} is missing and OFFLINE=1")
        print(f"fetched  {rel(asset)} sha256={download(asset)}")
        fetched += 1
    print(f"{len(assets)} asset(s): {len(assets) - fetched} already valid, {fetched} fetched")
    return 0


def report(assets: list[dict], deep: bool, paths: bool) -> int:
    bad = 0
    for asset in assets:
        status = state(asset, deep)
        bad += status != "ok"
        if not paths:
            print(f"{status:<8} {rel(asset)}")
        elif status == "ok":
            print(target(asset))
        else:
            print(f"{status}: {rel(asset)}", file=sys.stderr)
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--group", action="append", choices=GROUPS)
    parser.add_argument("--voices", nargs="+", default=[], metavar="ID")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="read-only: presence and size")
    mode.add_argument("--verify", action="store_true", help="read-only: presence and SHA256")
    mode.add_argument("--paths", action="store_true", help="print verified absolute paths")
    parser.add_argument("--offline", action="store_true", default=os.environ.get("OFFLINE") == "1")
    args = parser.parse_args()
    try:
        assets = load(args.group or [], args.voices)
        if args.check or args.verify or args.paths:
            return report(assets, deep=not args.check, paths=args.paths)
        return fetch(assets, args.offline)
    except FetchError as exc:
        print(f"fetch_assets: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
