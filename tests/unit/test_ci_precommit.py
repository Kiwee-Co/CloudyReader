"""The check-only hooks of .pre-commit-config.yaml: each regex on lines it must and must not hit.

The patterns come from the config itself, so an edit there is tested here. Forbidden text is
built from pieces, so this file passes its own hooks.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
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
        ("end-of-file", "site/public/CNAME", True),
        ("end-of-file", "site/public/CNAME.md", False),
        ("trailing-whitespace", "site/public/CNAME", True),
        ("disk-paths", "tests/integration/test_nsb_corpus.py", True),
        ("disk-paths", "tests/integration/test_other.py", False),
    ],
)
def test_exclusions_are_narrow(hook_id: str, path: str, excluded: bool) -> None:
    pattern = hooks()[hook_id].get("exclude")
    assert (re.search(pattern, path) is not None) is excluded


# --- prettier and markdownlint: a ratchet, so only files that are clean today are enforced ------

FORMAT_HOOKS = ("prettier", "markdownlint")
CLEAN_TODAY = (
    ".github/workflows/ci.yml",
    ".markdownlint.json",
    ".pre-commit-config.yaml",
    "CHANGELOG.md",
    "docs/_config.yml",
    "docs/developer/contributing.md",
    "docs/manual/faq.md",
)


def tracked() -> list[str]:
    done = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [rel for rel in done.stdout.split("\0") if rel]


def exclude_pattern(hook_id: str) -> str | None:
    """The hook's exclude baseline; None once the reformat commit has deleted it."""
    return hooks()[hook_id].get("exclude")


@pytest.mark.parametrize("hook_id", FORMAT_HOOKS)
def test_format_hooks_run_the_local_tool_over_the_right_file_kinds(hook_id: str) -> None:
    hook = hooks()[hook_id]
    assert hook["language"] == "system"
    assert hook["entry"].split()[0] == hook_id
    kinds = hook.get("types_or") or hook.get("types")
    assert {"markdown", "mdx"} <= set(kinds), "identify tags .mdx as mdx, not markdown"


def test_prettier_checks_without_writing_and_covers_markdown_mdx_yaml_and_json() -> None:
    hook = hooks()["prettier"]
    assert hook["entry"] == "prettier --check"
    assert set(hook["types_or"]) == {"markdown", "mdx", "yaml", "json"}


@pytest.mark.parametrize("hook_id", FORMAT_HOOKS)
def test_files_that_are_clean_today_are_never_excluded(hook_id: str) -> None:
    baseline = exclude_pattern(hook_id)
    if baseline is None:
        return
    for path in CLEAN_TODAY:
        assert not re.search(baseline, path), f"{hook_id} excludes {path}"


@pytest.mark.parametrize("hook_id", FORMAT_HOOKS)
def test_every_exclude_entry_still_names_a_tracked_file(hook_id: str) -> None:
    baseline = exclude_pattern(hook_id)
    if baseline is None:
        return
    body = baseline.strip().removeprefix("(?x)^(").removesuffix(")$")
    entries = [e.strip() for e in body.replace("\n", " ").split(" | ") if e.strip()]
    assert entries, f"{hook_id} excludes nothing: delete the exclude key"
    files = tracked()
    for entry in entries:
        regex = re.compile(entry.strip("| \n"))
        assert any(regex.fullmatch(path) for path in files), f"{hook_id}: no file matches {entry}"


def test_tool_written_and_fixture_data_stay_out_of_prettier() -> None:
    patterns = ("assets.lock.json", "cloudyreader/data/*.json", "tests/golden/*.yaml")
    ignored = (ROOT / ".prettierignore").read_text(encoding="utf-8").splitlines()
    files = tracked()
    for pattern in patterns:
        assert pattern in ignored, f".prettierignore lacks {pattern}"
        assert any(fnmatch.fnmatch(path, pattern) for path in files), f"{pattern} names no file"


def test_the_site_package_files_are_kept_out_of_prettier() -> None:
    # The files arrive with the site, so this checks the entries, not that the files exist yet.
    ignored = (ROOT / ".prettierignore").read_text(encoding="utf-8").splitlines()
    for pattern in ("site/package.json", "site/package-lock.json"):
        assert pattern in ignored, f".prettierignore lacks {pattern}"
