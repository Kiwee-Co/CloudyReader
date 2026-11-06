"""Markdown summary and failure annotations of a pytest run. Standard library only.

It reads the JUnit XML and the coverage.py XML that CI writes. By default it prints Markdown for a
step summary. With --annotate it prints GitHub workflow commands instead: one error per failed
test (at most 10, then a notice with the rest), one if the report is missing, one if coverage is
under the floor. A missing or unreadable report never fails the step: it must not hide the run.

Usage: python3 scripts/ci_summary.py --junit PATH --coverage PATH [--top N] [--annotate [--floor P]]
Exit 0 always, except 2 on a usage error.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

_SHOWN_BAD = 20
_ANNOTATED = 10  # failed tests that get an annotation of their own
_LINE_WIDTH = 300  # characters of the first failure line that an annotation keeps
# A traceback line "tests/unit/test_x.py:5: AssertionError": the last one that is ours is the crash.
_LOCATION = re.compile(r"^(?P<path>[^\s:][^:\n]*\.py):(?P<line>\d+): ", re.MULTILINE)
_NOT_OURS = {"site-packages", ".venv", ".cache", ".."}


@dataclass
class Failure:
    test: str  # classname.name, as in JUnit.bad
    module: str  # the dotted path to try as a file when the text names no location
    message: str  # the first line of the failure message
    text: str  # the failure text: the traceback, which ends at the crash location


@dataclass
class JUnit:
    tests: int
    failed: int
    errors: int
    skipped: int
    seconds: float
    bad: list[str] = field(default_factory=list)  # failing and erroring test ids
    failures: list[Failure] = field(default_factory=list)

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
        child = next((c for c in (case.find("failure"), case.find("error")) if c is not None), None)
        if child is None:
            continue
        classname, name = case.get("classname", ""), case.get("name", "")
        total.bad.append(f"{classname}.{name}".strip("."))
        total.failures.append(
            Failure(total.bad[-1], classname or name, _first_line(child), child.text or "")
        )
    return total


def _first_line(element: ET.Element) -> str:
    """The first non-empty line of a failure's message, else of its text, cut to a fixed width."""
    for source in (element.get("message") or "", element.text or ""):
        for line in source.splitlines():
            if line.strip():
                line = line.strip()
                return line if len(line) <= _LINE_WIDTH else line[: _LINE_WIDTH - 3] + "..."
    return ""


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


def escape_data(text: str) -> str:
    """The message of a workflow command: % and line breaks would end or split the command."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(text: str) -> str:
    return escape_data(text).replace(":", "%3A").replace(",", "%2C")


def _command(level: str, message: str, **properties: object) -> str:
    shown = ",".join(
        f"{key}={escape_property(str(value))}"
        for key, value in properties.items()
        if value is not None
    )
    head = f"::{level} {shown}" if shown else f"::{level}"
    return f"{head}::{escape_data(message)}"


def _repo_file(root: Path, raw: str) -> str | None:
    """raw as a path inside the repository that exists, else None: no venv, no outside path."""
    path = Path(raw)
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            return None
    if _NOT_OURS & set(path.parts) or not (root / path).is_file():
        return None
    return path.as_posix()


def _locate(root: Path, failure: Failure) -> tuple[str, int | None] | None:
    for match in reversed(list(_LOCATION.finditer(failure.text))):
        if found := _repo_file(root, match["path"]):
            return found, int(match["line"])
    parts = failure.module.split(".") if failure.module else []
    while parts:
        if found := _repo_file(root, "/".join(parts) + ".py"):
            return found, None
        parts.pop()
    return None


def annotations(
    junit_path: Path, coverage_path: Path, *, floor: float | None, root: Path
) -> list[str]:
    """Workflow commands for a run that went wrong; none for a clean run."""
    lines: list[str] = []
    junit = read_junit(junit_path)
    if junit is None:
        message = f"no JUnit report at {junit_path}: pytest did not finish"
        lines.append(_command("error", message, title="no test report"))
    elif junit.tests == 0:
        message = f"the JUnit report at {junit_path} holds no tests"
        lines.append(_command("error", message, title="no test report"))
    else:
        for failure in junit.failures[:_ANNOTATED]:
            where = _locate(root, failure)
            message = f"{failure.test}: {failure.message}" if failure.message else failure.test
            file, line = where if where else (None, None)
            lines.append(_command("error", message, title="test failed", file=file, line=line))
        extra = len(junit.failures) - _ANNOTATED
        if extra > 0:
            message = f"{_plural(extra, 'more failed test')}; junit.xml in the artifact lists all"
            lines.append(_command("notice", message, title="more failed tests"))
    cov = read_coverage(coverage_path)
    if cov is not None and floor is not None and cov.percent < floor:
        message = f"coverage {cov.percent:.2f}% is below the floor of {floor:g}%"
        lines.append(
            _command("error", f"{message} ({cov.covered} of {cov.valid} lines)", title="coverage")
        )
    return lines


def default_floor(makefile: Path) -> float | None:
    """COV_MIN as `make test` reads it: the environment first, then the Makefile's default."""
    try:
        return float(os.environ["COV_MIN"])
    except (KeyError, ValueError):
        pass
    try:
        text = makefile.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^COV_MIN\s*\??=\s*(\d+(?:\.\d+)?)\s*$", text, re.MULTILINE)
    return float(match[1]) if match else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--junit", type=Path, required=True, help="the JUnit XML pytest wrote")
    parser.add_argument("--coverage", type=Path, required=True, help="the coverage.py XML report")
    parser.add_argument("--top", type=int, default=25, help="files listed, lowest coverage first")
    parser.add_argument("--annotate", action="store_true", help="print annotations, not Markdown")
    parser.add_argument(
        "--floor", type=float, help="coverage floor for --annotate; default COV_MIN"
    )
    args = parser.parse_args(argv)
    if args.annotate:
        makefile = Path(__file__).resolve().parents[1] / "Makefile"
        floor = default_floor(makefile) if args.floor is None else args.floor
        found = annotations(args.junit, args.coverage, floor=floor, root=Path.cwd())
        sys.stdout.write("".join(f"{line}\n" for line in found))
        return 0
    sys.stdout.write(render(read_junit(args.junit), read_coverage(args.coverage), top=args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
