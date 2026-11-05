"""Extract text from the NSB sample-question PDFs into a git-ignored cache.

Usage: python -I scripts/extract_samples.py [--src DIR] [--dst DIR] [--force]
Source: --src, else $CLOUDYREADER_SAMPLES_SRC; one is required. It is read-only: nothing is ever
written under it. Output mirrors <set>/<name>.txt; outputs newer than their PDF are skipped.
Needs poppler's pdftotext (`brew install poppler`). Stdlib only.
"""

import argparse
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DST = ROOT / ".data" / "samples"
# -layout, not default or -raw: default mode prints the tail of the stem before its head (571 of
# 11267 stems) when "N) Category - Format" is a separate table cell; -raw glues the page footer
# onto the last ANSWER line. -nopgbrk drops form feeds, which splitlines() treats as line breaks.
PDFTOTEXT_ARGS = ("-layout", "-nopgbrk", "-enc", "UTF-8")
TIMEOUT_S = 60


def find_pdfs(src: Path) -> list[Path]:
    """Every *.pdf under src, sorted, without walking hidden dirs such as .git."""
    found: list[Path] = []
    for root, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        found += [Path(root) / f for f in sorted(files) if f.lower().endswith(".pdf")]
    return found


def tidy(text: str) -> str:
    """Collapse -layout column padding; keep at most one blank line between blocks."""
    kept: list[str] = []
    for line in (" ".join(raw.split()) for raw in text.splitlines()):
        if line or (kept and kept[-1]):
            kept.append(line)
    return "\n".join(kept).strip() + "\n"


def extract_one(pdftotext: str, pdf: Path, out: Path, force: bool) -> tuple[str, str]:
    """Return ("ok" | "skipped" | "failed", detail)."""
    if not force and out.exists() and out.stat().st_mtime >= pdf.stat().st_mtime:
        return "skipped", ""
    cmd = [pdftotext, *PDFTOTEXT_ARGS, str(pdf), "-"]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_S, check=False)
        text = done.stdout.decode("utf-8")
    except subprocess.TimeoutExpired:
        return "failed", f"pdftotext timed out after {TIMEOUT_S}s"
    except (OSError, UnicodeDecodeError) as exc:
        return "failed", str(exc)
    if done.returncode != 0:
        return "failed", done.stderr.decode("utf-8", "replace").strip() or f"exit {done.returncode}"
    if not text.strip():
        return "failed", "no text layer"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(tidy(text), encoding="utf-8")
    os.replace(tmp, out)
    return "ok", ""


def run(src: Path, dst: Path, force: bool = False) -> int:
    pdftotext = shutil.which("pdftotext")
    if pdftotext is None:
        print("pdftotext not found: brew install poppler", file=sys.stderr)
        return 2
    src, dst = src.resolve(), dst.resolve()
    if not src.is_dir():
        print(f"source dir not found: {src}", file=sys.stderr)
        return 2
    if dst == src or src in dst.parents:
        print(f"refusing to write under the read-only source: {dst}", file=sys.stderr)
        return 2
    pdfs = find_pdfs(src)
    outs = [dst / pdf.relative_to(src).with_suffix(".txt") for pdf in pdfs]
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as pool:
        jobs = zip(pdfs, outs, strict=True)
        results = list(pool.map(lambda job: extract_one(pdftotext, *job, force), jobs))
    counts = {"ok": 0, "failed": 0, "skipped": 0}
    for pdf, (status, detail) in zip(pdfs, results, strict=True):
        counts[status] += 1
        if status == "failed":
            print(f"FAILED {pdf.relative_to(src)}: {detail}", file=sys.stderr)
    print(f"ok={counts['ok']} failed={counts['failed']} skipped={counts['skipped']} -> {dst}")
    return 1 if counts["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract NSB sample-question PDFs to text.")
    parser.add_argument(
        "--src",
        type=Path,
        default=os.environ.get("CLOUDYREADER_SAMPLES_SRC") or None,
        help="PDF tree (read-only); default $CLOUDYREADER_SAMPLES_SRC",
    )
    parser.add_argument(
        "--dst", type=Path, default=DEFAULT_DST, help="cache dir (default .data/samples)"
    )
    parser.add_argument("--force", action="store_true", help="re-extract up-to-date outputs too")
    args = parser.parse_args(argv)
    if args.src is None:
        parser.error("no PDF tree: pass --src DIR or set CLOUDYREADER_SAMPLES_SRC")
    return run(args.src, args.dst, args.force)


if __name__ == "__main__":
    sys.exit(main())
