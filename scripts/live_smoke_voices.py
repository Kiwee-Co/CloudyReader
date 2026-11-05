"""Live smoke test for the voice download. Run it yourself, outside the agent sandbox.

Usage: uv run python -I scripts/live_smoke_voices.py
Asks for byte 0 of every voice and Kokoro file pinned in assets.lock.json, over HTTPS with each
redirect followed by hand, and compares the size the server reports with the pin. Then fetches
the small files (each Piper .onnx.json, config.json, af_heart.safetensors: about 0.55 MB) into a
new temp dir, SHA-256 checked, and deletes them. Prints file names, statuses and byte counts,
never a URL or a host. Always exits 0: read the verdict, not the exit status.
"""

from __future__ import annotations

import dataclasses
import json
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from cloudyreader.config import DATA_DIR_ENV, Settings, load_settings
from cloudyreader.prefetch import (
    FETCHED,
    TIMEOUT,
    Asset,
    PrefetchError,
    PrefetchResult,
    VoicePrefetch,
    find_lock,
    load_assets,
    open_https,
)

SMALL = ("config.json", "af_heart.safetensors")  # plus every Piper .onnx.json
RETRY_DELAY_S = 2.0
_RANGE_TOTAL = re.compile(r"bytes 0-0/(\d+)")


@dataclass(frozen=True)
class Probe:
    """What the server said about one pinned file."""

    asset: Asset
    state: str  # HELD, BROKEN or NO DATA
    detail: str

    def line(self) -> str:
        return f"{self.state:<8} {self.asset.name:<36} {self.detail}"


def reported_size(response: httpx.Response) -> int | None:
    """The whole file's size, from a 206's Content-Range or a 200's Content-Length."""
    if response.status_code == 206:
        match = _RANGE_TOTAL.fullmatch(response.headers.get("Content-Range", "").strip())
        return int(match.group(1)) if match else None
    if response.status_code == 200:
        length = response.headers.get("Content-Length", "").strip()
        return int(length) if length.isdigit() else None
    return None


def probe(client: httpx.Client, asset: Asset) -> Probe:
    try:
        response = open_https(client, asset.url, headers={"Range": "bytes=0-0"})
    except PrefetchError as exc:  # a redirect came and was refused; the message holds no URL
        return Probe(asset, "BROKEN", str(exc))
    except httpx.TransportError as exc:
        return Probe(asset, "NO DATA", f"no response ({type(exc).__name__})")
    response.close()  # the body is never read: a server that ignores Range sends the whole file
    size = reported_size(response)
    shown = "?" if size is None else str(size)
    detail = (
        f"HTTP {response.status_code}, {len(response.history)} hop(s), "
        f"{shown} of {asset.size} bytes"
    )
    return Probe(asset, "HELD" if size == asset.size else "BROKEN", detail)


def small_lock(lock: Path, scratch: Path) -> tuple[Path, list[str]]:
    """A copy of the lock with only the small voice and Kokoro files; its path and their names."""
    entries = json.loads(lock.read_text(encoding="utf-8"))["assets"]
    keep = [
        e
        for e in entries
        if e["group"] in FETCHED and (e["name"].endswith(".onnx.json") or e["name"] in SMALL)
    ]
    path = scratch / "small.lock.json"
    path.write_text(json.dumps({"version": 1, "assets": keep}), encoding="utf-8")
    return path, [e["name"] for e in keep]


def verdict_state(held: int, broken: int, total: int) -> str:
    """HELD: all true. PARTIAL: some. BROKEN: none, but answers came. NO DATA: no answer at all."""
    if held == total:
        return "HELD"
    if held:
        return "PARTIAL"
    return "BROKEN" if broken else "NO DATA"


def verdict_line(
    scope: str, label: str, held: int, broken: int, total: int, fails: Sequence[str]
) -> str:
    tail = f"  fails: {', '.join(fails)}" if fails else ""
    return f"{verdict_state(held, broken, total):<8} {scope:<8} {label}  {held}/{total}{tail}"


def verdict(
    probes: Sequence[Probe], names: Sequence[str], result: PrefetchResult | None
) -> list[str]:
    held = sum(1 for p in probes if p.state == "HELD")
    broken = sum(1 for p in probes if p.state == "BROKEN")
    fails = [p.asset.name for p in probes if p.state != "HELD"]
    label = "each pinned file reports its pinned size"
    lines = [verdict_line("probes", label, held, broken, len(probes), fails)]
    if result is None:
        lines.append(f"{'NO DATA':<8} {'download':<8} skipped: no probe got an answer")
    else:
        failed = [name for name in names if name in result.failed]
        label = "the small files arrive with their pinned SHA-256"
        lines.append(verdict_line("download", label, result.files, len(failed), len(names), failed))
    bad = sum(1 for line in lines if not line.startswith("HELD"))
    summary = "RESULT: every check held."
    if not held and not broken:
        summary = "RESULT: no HTTP response at all. Check network, proxy and sandbox, then rerun."
    elif bad:
        summary = f"RESULT: {bad} of {len(lines)} checks did not hold. Paste this whole output."
    return [*lines, summary]


def main(*, settings: Settings | None = None) -> int:
    lock = find_lock()
    if lock is None:
        print(f"{'NO DATA':<8} {'lock':<8} no assets.lock.json found")
        return 0
    with tempfile.TemporaryDirectory(
        prefix="cloudyreader-smoke-voices-", ignore_cleanup_errors=True
    ) as tmp:
        scratch = Path(tmp)
        if settings is None:
            # Defaults only: CLOUDYREADER_DATA_DIR and CLOUDYREADER_OFFLINE must not steer this.
            settings = load_settings({DATA_DIR_ENV: str(scratch / "data")})
        settings = dataclasses.replace(settings, offline=False)
        try:
            assets = load_assets(lock, settings)
        except PrefetchError as exc:
            print(f"{'BROKEN':<8} {'lock':<8} {lock.name} rejected: {exc}")
            return 0
        print(
            f"cloudyreader voice smoke: byte 0 of {len(assets)} pinned files, then the small "
            "files into a temp dir; no URL or host is printed"
        )
        result: PrefetchResult | None = None
        names: list[str] = []
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
            probes = []
            for asset in assets:
                probes.append(probe(client, asset))
                print(probes[-1].line(), flush=True)
            if any(p.state != "NO DATA" for p in probes):
                small, names = small_lock(lock, scratch)
                fetch = VoicePrefetch(
                    settings,
                    lock_path=small,
                    client=client,
                    kokoro_ready=lambda: True,  # the files are checked here, not used
                    retry_delay_s=RETRY_DELAY_S,
                )
                result = fetch.run()
    print("\n== verdict ==")
    print("\n".join(verdict(probes, names, result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
