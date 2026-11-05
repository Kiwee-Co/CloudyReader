"""The check-only hooks of .pre-commit-config.yaml: each regex on lines it must and must not hit.

The patterns come from the config itself, so an edit there is tested here. Forbidden text is
built from pieces, so this file passes its own hooks.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".pre-commit-config.yaml"
CHECK_HOOKS = (
    "trailing-whitespace",
    "end-of-file",
    "merge-conflict",
    "private-key",
    "vendor-domain",
    "disk-paths",
    "shellcheck",
)
VENDOR = "apple." + "com"
VOLUMES = "/Vol" + "umes/"
USERS = "/Us" + "ers/"
KEY_HEAD = "-----BEGIN "
MARK = "<" * 7


def hooks() -> dict[str, dict]:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}


def search(hook_id: str, text: str) -> bool:
    """True when pre-commit's pygrep would flag text: per line, or whole file with --multiline."""
    hook = hooks()[hook_id]
    args = hook.get("args", [])
    flags = re.IGNORECASE if "--ignore-case" in args else 0
    if "--multiline" in args:
        return (
            re.search(hook["entry"].encode(), text.encode(), flags | re.MULTILINE | re.DOTALL)
            is not None
        )
    pattern = re.compile(hook["entry"].encode(), flags)
    return any(pattern.search(line) for line in text.encode().splitlines(keepends=True))


def test_only_local_hooks_and_every_check_hook_is_present() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert [repo["repo"] for repo in config["repos"]] == ["local"]
    assert set(CHECK_HOOKS) <= set(hooks())


@pytest.mark.parametrize("hook_id", CHECK_HOOKS)
def test_check_hooks_only_read_files_of_their_kind(hook_id: str) -> None:
    hook = hooks()[hook_id]
    assert hook["language"] in ("pygrep", "system")
    assert hook.get("types") in (["text"], ["shell"])


@pytest.mark.parametrize(
    ("hook_id", "bad", "good"),
    [
        ("trailing-whitespace", "x = 1  \n", "x = 1\n"),
        ("trailing-whitespace", "tab\t\n", "  indented\n"),
        ("trailing-whitespace", "last line  ", "last line\n"),
        ("end-of-file", "no newline", "newline\n"),
        ("end-of-file", "a\nb", "a\nb\n"),
        ("end-of-file", "a\n\nb", ""),
        ("merge-conflict", f"{MARK} HEAD\n", "a <<< b\n"),
        ("merge-conflict", ">" * 7 + " branch\n", "=======\n"),
        ("merge-conflict", MARK + "\n", "x " + MARK + "\n"),
        ("private-key", f"{KEY_HEAD}RSA PRIVATE KEY-----\n", f"{KEY_HEAD}CERTIFICATE-----\n"),
        ("private-key", f"{KEY_HEAD}PRIVATE KEY-----\n", "PRIVATE KEY\n"),
        ("private-key", f"{KEY_HEAD}OPENSSH PRIVATE KEY-----\n", f"{KEY_HEAD}PUBLIC KEY-----\n"),
        ("private-key", f"{KEY_HEAD}PGP PRIVATE KEY BLOCK-----\n", "-----BEGIN\n"),
        ("vendor-domain", f"see {VENDOR}\n", "see example.com\n"),
        ("vendor-domain", f"see {VENDOR.upper()}\n", "apple pie\n"),
        ("disk-paths", f"cd {VOLUMES}me\n", "cd /volumes-ok\n"),
        ("disk-paths", f"cd {USERS}me\n", "cd ~/me\n"),
    ],
)
def test_pattern_hits_the_bad_line_and_spares_the_good_one(
    hook_id: str, bad: str, good: str
) -> None:
    assert search(hook_id, bad), f"{hook_id} missed {bad!r}"
    assert not search(hook_id, good), f"{hook_id} flagged {good!r}"


def test_the_config_does_not_trip_its_own_hooks() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    for hook_id in CHECK_HOOKS:
        if hooks()[hook_id]["language"] == "pygrep":
            assert not search(hook_id, text), f"{hook_id} matches .pre-commit-config.yaml"


@pytest.mark.parametrize(
    ("hook_id", "path", "excluded"),
    [
        ("trailing-whitespace", "tests/fixtures/questions/48-x.txt", True),
        ("trailing-whitespace", "tests/golden/corpus/entities.tsv", True),
        ("trailing-whitespace", "docs/assets/fonts/OFL.txt", True),
        ("trailing-whitespace", "scripts/ci_guards.py", False),
        ("end-of-file", "docs/CNAME", True),
        ("end-of-file", "docs/CNAME.md", False),
        ("disk-paths", "tests/integration/test_nsb_corpus.py", True),
        ("disk-paths", "tests/integration/test_other.py", False),
    ],
)
def test_exclusions_are_narrow(hook_id: str, path: str, excluded: bool) -> None:
    pattern = hooks()[hook_id].get("exclude")
    assert (re.search(pattern, path) is not None) is excluded
