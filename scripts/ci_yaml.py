"""Strict YAML parse of the tracked files under .github/. Needs PyYAML (the dev group has it).

PyYAML takes a repeated mapping key without a word: the last value wins. This check refuses it.
It composes the node graph and builds no objects, so no YAML tag can run code.

Usage: python scripts/ci_yaml.py [--root DIR]
Exit 0 when every file parses, 1 with one "path:line: problem" line each, 2 on a usage or git error.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Problem:
    path: str
    line: int
    message: str


class GitError(RuntimeError):
    """git could not list the files: a tool failure, not a finding."""


def _repeated_keys(root: yaml.Node) -> list[tuple[int, str]]:
    """(line, key) of every repeated scalar key in every mapping under root, in line order."""
    found: list[tuple[int, str]] = []
    stack, visited = [root], set()
    while stack:
        node = stack.pop()
        if id(node) in visited:  # an anchor can reach one node twice
            continue
        visited.add(id(node))
        if isinstance(node, yaml.MappingNode):
            keys = set()
            for key, value in node.value:
                if isinstance(key, yaml.ScalarNode):
                    if (key.tag, key.value) in keys:
                        found.append((key.start_mark.line + 1, key.value))
                    keys.add((key.tag, key.value))
                stack += [key, value]
        elif isinstance(node, yaml.SequenceNode):
            stack += node.value
    return sorted(found)


def yaml_files(root: Path) -> list[str]:
    try:
        listing = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", ".github"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise GitError(f"cannot run git: {exc}") from exc
    if listing.returncode != 0:
        raise GitError(f"git ls-files failed ({listing.returncode}): {listing.stderr.strip()}")
    return [rel for rel in listing.stdout.split("\0") if rel.endswith((".yml", ".yaml"))]


def check_file(root: Path, rel: str) -> list[Problem]:
    try:
        with (root / rel).open(encoding="utf-8") as handle:
            documents = [doc for doc in yaml.compose_all(handle, Loader=yaml.SafeLoader) if doc]
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        text = str(getattr(exc, "problem", None) or exc).splitlines()[0]
        return [Problem(rel, mark.line + 1 if mark else 1, text)]
    except (OSError, UnicodeDecodeError) as exc:
        return [Problem(rel, 1, f"cannot be read: {exc}")]
    return [
        Problem(rel, line, f"duplicate key {key!r}")
        for doc in documents
        for line, key in _repeated_keys(doc)
    ]


def problems(root: Path) -> list[Problem]:
    return [p for rel in yaml_files(root) for p in check_file(root, rel)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default = Path(__file__).resolve().parent.parent
    parser.add_argument("--root", type=Path, default=default, help="the repository to check")
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"ci_yaml: no such folder: {args.root}", file=sys.stderr)
        return 2
    try:
        files = yaml_files(args.root)
    except GitError as exc:
        print(f"ci_yaml: {exc}", file=sys.stderr)
        return 2
    found = [p for rel in files for p in check_file(args.root, rel)]
    for problem in found:
        print(f"{problem.path}:{problem.line}: {problem.message}")
    if found:
        return 1
    print(f"ci_yaml: {len(files)} file{'' if len(files) == 1 else 's'} parsed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
