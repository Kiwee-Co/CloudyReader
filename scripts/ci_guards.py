"""Repository guards for CI and `make guards`. Standard library plus git; no venv needed.

Guards: vendor-domain (no tracked file names the vendor's own domain), lock-hosts (uv.lock names
public hosts only), disk-paths (no machine path in a tracked file), workflow-triggers (no
workflow uses the privileged pull_request_target trigger).

Usage: python3 scripts/ci_guards.py [--root DIR] [GUARD ...]  (default: every guard)
Exit 0 when all pass, 1 with one "path:line: [guard] problem" line each, 2 on a usage or git error.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Problem:
    path: str
    line: int
    message: str


class GuardError(RuntimeError):
    """The check could not run (git missing, not a repository): a tool failure, not a finding."""


# Patterns and paths are split or escaped, so this file never matches its own guards.
_VENDOR = r"apple\." + "com"
_DISK = "/(Volumes|Users)/"
_VOLUMES, _USERS = "/Vol" + "umes/", "/Us" + "ers/"
_PUBLIC_HOSTS = frozenset(
    {"https://pypi.org", "https://files.pythonhosted.org", "https://github.com"}
)
_HOST = re.compile(r'https?://[^/" ]+')
_TRIGGER = re.compile(r"\bpull_request" r"_target\b")
_YAML_COMMENT = re.compile(r"(^|\s)#.*$")
# The only disk paths a tracked file may hold: two assertions that a path is absent from output.
_ALLOWED_DISK_LINES = frozenset(
    {
        (
            "tests/integration/test_nsb_corpus.py",
            f'assert "{_VOLUMES}" not in err and "{_USERS}" not in err',
        ),
        (
            "tests/integration/test_nsb_corpus.py",
            f'assert "{_VOLUMES}" not in text and "{_USERS}" not in text',
        ),
    }
)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise GuardError(f"cannot run git: {exc}") from exc


def _grep(
    root: Path, pattern: str, *, extended: bool = False, ignore_case: bool = False
) -> list[tuple[str, int, str]]:
    """(path, line, text) of every line of a tracked text file that matches; git grep -z."""
    flags = ["-z", "-n", "-I", *(["-E"] if extended else []), *(["-i"] if ignore_case else [])]
    done = _git(root, "grep", *flags, "-e", pattern, "--")
    if done.returncode == 1:
        return []
    if done.returncode != 0:
        raise GuardError(f"git grep failed ({done.returncode}): {done.stderr.strip()}")
    hits = []
    for record in done.stdout.split("\n"):
        path, first, rest = record.partition("\0")
        number, second, text = rest.partition("\0")
        if first and second and number.isdigit():
            hits.append((path, int(number), text))
    return hits


def vendor_domain(root: Path) -> list[Problem]:
    """The text of a hit is never echoed, so the log does not repeat the domain."""
    message = "names the vendor's own domain; remove it"
    return [
        Problem(path, line, message) for path, line, _ in _grep(root, _VENDOR, ignore_case=True)
    ]


def lock_hosts(root: Path) -> list[Problem]:
    """A hosted runner reaches public hosts only; every other host in uv.lock is a problem."""
    try:
        text = (root / "uv.lock").read_text(encoding="utf-8")
    except OSError:
        return [Problem("uv.lock", 1, "is missing or unreadable")]
    first: dict[str, int] = {}
    for number, line in enumerate(text.split("\n"), start=1):
        for host in _HOST.findall(line):
            if host.lower() not in _PUBLIC_HOSTS:
                first.setdefault(host, number)
    return [
        Problem("uv.lock", number, f"host {host} is not public; relock against pypi.org")
        for host, number in first.items()
    ]


def disk_paths(root: Path) -> list[Problem]:
    message = "names a disk path of one machine; use a relative path or a placeholder"
    return [
        Problem(path, line, message)
        for path, line, text in _grep(root, _DISK, extended=True)
        if (path, text.strip()) not in _ALLOWED_DISK_LINES
    ]


def workflow_triggers(root: Path) -> list[Problem]:
    """Comments are skipped; any other mention of the trigger counts, wherever it stands."""
    listing = _git(root, "ls-files", "-z", "--", ".github/workflows")
    if listing.returncode != 0:
        raise GuardError(f"git ls-files failed ({listing.returncode}): {listing.stderr.strip()}")
    problems = []
    for rel in filter(None, listing.stdout.split("\0")):
        if not rel.endswith((".yml", ".yaml")):
            continue
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.split("\n"), start=1):
            if _TRIGGER.search(_YAML_COMMENT.sub("", line)):
                problems.append(Problem(rel, number, "uses a privileged trigger; use pull_request"))
    return problems


GUARDS: dict[str, Callable[[Path], list[Problem]]] = {
    "vendor-domain": vendor_domain,
    "lock-hosts": lock_hosts,
    "disk-paths": disk_paths,
    "workflow-triggers": workflow_triggers,
}


def annotation(guard: str, problem: Problem) -> str:
    """A GitHub error annotation; escaping stops repo text from injecting a workflow command."""

    def escape(value: str, *, prop: bool = False) -> str:
        value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        return value.replace(":", "%3A").replace(",", "%2C") if prop else value

    file, title = escape(problem.path, prop=True), escape(guard, prop=True)
    return f"::error file={file},line={problem.line},title={title}::{escape(problem.message)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("guards", nargs="*", metavar="GUARD", help=f"one of: {', '.join(GUARDS)}")
    default = Path(__file__).resolve().parent.parent
    parser.add_argument("--root", type=Path, default=default, help="the repository to check")
    args = parser.parse_args(argv)
    unknown = [name for name in args.guards if name not in GUARDS]
    if unknown:
        print(
            f"ci_guards: unknown guard {', '.join(unknown)}; use {', '.join(GUARDS)}",
            file=sys.stderr,
        )
        return 2
    if not args.root.is_dir():
        print(f"ci_guards: no such folder: {args.root}", file=sys.stderr)
        return 2
    github = os.environ.get("GITHUB_ACTIONS") == "true"
    failed = 0
    for name in args.guards or GUARDS:
        try:
            problems = GUARDS[name](args.root.resolve())
        except GuardError as exc:
            print(f"ci_guards: {name}: {exc}", file=sys.stderr)
            return 2
        for problem in problems:
            print(f"{problem.path}:{problem.line}: [{name}] {problem.message}")
            if github:
                print(annotation(name, problem))
        print(
            f"{'FAIL' if problems else 'ok  '}  {name}"
            + (f" ({len(problems)})" if problems else "")
        )
        failed += bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
