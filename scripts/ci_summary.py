"""Markdown summary of a pytest run, for a GitHub step summary. Standard library only.

It reads the JUnit XML and the coverage.py XML that CI writes and prints Markdown on stdout. A
missing or unreadable report becomes a note in the summary: the summary must never hide the run.

Usage: python3 scripts/ci_summary.py --junit PATH --coverage PATH [--top N]  (default N: 25)
Exit 0 always, except 2 on a usage error.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

_SHOWN_BAD = 20


@dataclass
class JUnit:
    tests: int
    failed: int
    errors: int
    skipped: int
    seconds: float
    bad: list[str] = field(default_factory=list)  # failing and erroring test ids

    @property
    def passed(self) -> int:
        return max(self.tests - self.failed - self.errors - self.skipped, 0)


@dataclass
class FileCoverage:
    name: str
    valid: int
    covered: int

    @property
    def percent(self) -> float:
        return 100.0 if self.valid == 0 else self.covered / self.valid * 100


@dataclass
class Coverage:
    valid: int
    covered: int
    files: list[FileCoverage]

    @property
    def percent(self) -> float:
        return 100.0 if self.valid == 0 else self.covered / self.valid * 100


def _root(path: Path) -> ET.Element | None:
    """The parsed report, or None. A DTD is refused: entity expansion hides there."""
    try:
        data = path.read_bytes()
        if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
            return None
        return ET.fromstring(data)
    except (OSError, ET.ParseError):
        return None


def read_junit(path: Path) -> JUnit | None:
    root = _root(path)
    if root is None:
        return None
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = JUnit(0, 0, 0, 0, 0.0)
    for suite in suites:
        total.tests += int(suite.get("tests", 0))
        total.failed += int(suite.get("failures", 0))
        total.errors += int(suite.get("errors", 0))
        total.skipped += int(suite.get("skipped", 0))
        total.seconds += float(suite.get("time", 0))
    for case in root.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            total.bad.append(f"{case.get('classname', '')}.{case.get('name', '')}".strip("."))
    return total


def read_coverage(path: Path) -> Coverage | None:
    root = _root(path)
    if root is None:
        return None
    files = []
    for cls in root.iter("class"):
        hits = [int(line.get("hits", 0)) for line in cls.iter("line")]
        files.append(FileCoverage(cls.get("filename", ""), len(hits), sum(h > 0 for h in hits)))
    valid, covered = root.get("lines-valid"), root.get("lines-covered")
    if valid is None or covered is None:
        return Coverage(sum(f.valid for f in files), sum(f.covered for f in files), files)
    return Coverage(int(valid), int(covered), files)


def _md(text: str) -> str:
    """Text safe inside a table cell or code span: no backtick, pipe, or line break."""
    flat = " ".join(text.split()).replace("`", "'").replace("|", "\\|")
    return flat[:200]


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _tests(junit: JUnit | None) -> list[str]:
    if junit is None:
        return ["### Tests", "", "No JUnit report was written: the run stopped before pytest did."]
    lines = [
        "### Tests",
        "",
        "| Tests | Passed | Failed | Errors | Skipped | Time |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {junit.tests} | {junit.passed} | {junit.failed} | {junit.errors} | {junit.skipped} "
        f"| {junit.seconds:.1f} s |",
    ]
    if junit.bad:
        lines += ["", "Failing or erroring tests:", ""]
        lines += [f"- `{_md(test)}`" for test in junit.bad[:_SHOWN_BAD]]
        if len(junit.bad) > _SHOWN_BAD:
            lines.append(f"- and {len(junit.bad) - _SHOWN_BAD} more")
    return lines


def _coverage(cov: Coverage | None, top: int) -> list[str]:
    if cov is None:
        return ["### Coverage", "", "No coverage report was written: pytest did not finish."]
    lines = [
        "### Coverage",
        "",
        f"Total: **{cov.percent:.2f}%** ({cov.covered} of {cov.valid} lines)",
        "",
    ]
    partial = sorted(
        (f for f in cov.files if f.covered < f.valid), key=lambda f: (f.percent, -f.valid, f.name)
    )
    full = len(cov.files) - len(partial)
    if not partial:
        return [*lines, f"All {_plural(full, 'file')} at 100%."]
    lines += ["| File | Lines | Missed | Cover |", "| --- | ---: | ---: | ---: |"]
    for item in partial[:top]:
        lines.append(
            f"| `{_md(item.name)}` | {item.valid} | {item.valid - item.covered} "
            f"| {item.percent:.2f}% |"
        )
    if len(partial) > top:
        lines += ["", f"{_plural(len(partial) - top, 'more file')} below 100%."]
    return [*lines, "", f"{_plural(full, 'file')} at 100%."]


def render(junit: JUnit | None, cov: Coverage | None, *, top: int) -> str:
    return "\n".join([*_tests(junit), "", *_coverage(cov, top), ""])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--junit", type=Path, required=True, help="the JUnit XML pytest wrote")
    parser.add_argument("--coverage", type=Path, required=True, help="the coverage.py XML report")
    parser.add_argument("--top", type=int, default=25, help="files listed, lowest coverage first")
    args = parser.parse_args(argv)
    sys.stdout.write(render(read_junit(args.junit), read_coverage(args.coverage), top=args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
