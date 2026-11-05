"""scripts/ci_guards.py: each guard on small git repos, and the command line.

Fixture text that would trip a guard is built from pieces, so this file passes the guards too.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_guards.py"
VENDOR = "apple." + "com"
VOLUMES = "/Vol" + "umes/"
USERS = "/Us" + "ers/"
ALLOWED_FILE = "tests/integration/test_nsb_corpus.py"
ALLOWED_LINES = (
    f'    assert "{VOLUMES}" not in err and "{USERS}" not in err',
    f'    assert "{VOLUMES}" not in text and "{USERS}" not in text',
)
TRIGGER = "pull_request" + "_target"
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


@pytest.fixture
def guards(monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("ci_guards", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses looks its module up in sys.modules while it builds the script's classes.
    monkeypatch.setitem(sys.modules, "ci_guards", module)
    spec.loader.exec_module(module)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return module


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[..., Path]:
    def git(root: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(root), *args], check=True, env=CLEAN_ENV, capture_output=True
        )

    def make(files: dict[str, str | bytes], *, tracked: bool = True) -> Path:
        root = tmp_path / "repo"
        root.mkdir()
        git(root, "init", "-q")
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content if isinstance(content, bytes) else content.encode())
        if tracked:
            git(root, "add", "-A")
        return root

    return make


def found(guards, name: str, root: Path) -> list[tuple[str, int]]:
    return [(p.path, p.line) for p in guards.GUARDS[name](root)]


# --- vendor-domain ---------------------------------------------------------------------------


def test_vendor_domain_passes_a_clean_repo(guards, make_repo) -> None:
    root = make_repo({"README.md": "hello\n", "src/a.py": "x = 1\n"})
    assert found(guards, "vendor-domain", root) == []


@pytest.mark.parametrize("text", [VENDOR, VENDOR.upper(), "see https://www." + VENDOR + "/x"])
def test_vendor_domain_finds_the_domain_in_any_case(guards, make_repo, text: str) -> None:
    root = make_repo({"notes.md": f"one\n{text}\nthree\n"})
    assert found(guards, "vendor-domain", root) == [("notes.md", 2)]


def test_vendor_domain_skips_binary_and_untracked_files(guards, make_repo) -> None:
    root = make_repo({"blob.bin": b"\x00\x01" + VENDOR.encode(), "ok.txt": "fine\n"})
    (root / "later.txt").write_text(VENDOR)
    assert found(guards, "vendor-domain", root) == []


def test_vendor_domain_message_never_echoes_the_domain(guards, make_repo) -> None:
    root = make_repo({"notes.md": VENDOR + "\n"})
    [problem] = guards.GUARDS["vendor-domain"](root)
    assert VENDOR not in problem.message


# --- lock-hosts ------------------------------------------------------------------------------

GOOD_LOCK = (
    'source = { registry = "https://pypi.org/simple" }\n'
    'wheels = [{ url = "https://files.pythonhosted.org/packages/a/b/c.whl" }]\n'
    'url = "https://github.com/explosion/spacy-models/releases/download/x.whl"\n'
)


def test_lock_hosts_passes_public_hosts_only(guards, make_repo) -> None:
    assert found(guards, "lock-hosts", make_repo({"uv.lock": GOOD_LOCK})) == []


def test_lock_hosts_reports_each_other_host_once_with_its_first_line(guards, make_repo) -> None:
    lock = GOOD_LOCK + 'a = "https://mirror.example/simple"\nb = "https://mirror.example/x"\n'
    lock += 'c = "http://pypi.org/simple"\n'
    root = make_repo({"uv.lock": lock})
    assert found(guards, "lock-hosts", root) == [("uv.lock", 4), ("uv.lock", 6)]


def test_lock_hosts_names_the_host_in_the_message(guards, make_repo) -> None:
    root = make_repo({"uv.lock": 'a = "https://mirror.example/simple"\n'})
    [problem] = guards.GUARDS["lock-hosts"](root)
    assert "https://mirror.example" in problem.message


def test_lock_hosts_fails_when_the_lock_is_missing(guards, make_repo) -> None:
    root = make_repo({"README.md": "x\n"})
    assert found(guards, "lock-hosts", root) == [("uv.lock", 1)]


# --- disk-paths ------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [VOLUMES, USERS])
def test_disk_paths_finds_a_machine_path(guards, make_repo, path: str) -> None:
    root = make_repo({"docs/a.md": f"ok\nrun {path}me/project\n"})
    assert found(guards, "disk-paths", root) == [("docs/a.md", 2)]


def test_disk_paths_allows_exactly_the_two_known_lines(guards, make_repo) -> None:
    body = "def test():\n" + "\n".join(ALLOWED_LINES) + "\n"
    assert found(guards, "disk-paths", make_repo({ALLOWED_FILE: body})) == []


def test_disk_paths_allowance_is_tied_to_the_file(guards, make_repo) -> None:
    root = make_repo({"tests/other.py": ALLOWED_LINES[0] + "\n"})
    assert found(guards, "disk-paths", root) == [("tests/other.py", 1)]


def test_disk_paths_allowance_does_not_cover_other_lines_of_that_file(guards, make_repo) -> None:
    body = ALLOWED_LINES[0] + "\n" + f'    where = "{USERS}me"\n'
    assert found(guards, "disk-paths", make_repo({ALLOWED_FILE: body})) == [(ALLOWED_FILE, 2)]


def test_disk_paths_handles_a_colon_in_a_file_name(guards, make_repo) -> None:
    root = make_repo({"odd:name.txt": f"x\n{VOLUMES}y\n"})
    assert found(guards, "disk-paths", root) == [("odd:name.txt", 2)]


# --- workflow-triggers -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        f"on:\n  {TRIGGER}:\n    types: [opened]\n",
        f"on: [push, {TRIGGER}]\n",
        f"on: {TRIGGER}\n",
    ],
)
def test_workflow_triggers_flags_the_privileged_trigger(guards, make_repo, text: str) -> None:
    root = make_repo({".github/workflows/x.yml": text})
    assert found(guards, "workflow-triggers", root)[0][0] == ".github/workflows/x.yml"


def test_workflow_triggers_ignores_comments_and_other_files(guards, make_repo) -> None:
    root = make_repo(
        {
            ".github/workflows/ok.yaml": f"on: push  # never {TRIGGER}\n# {TRIGGER}\n",
            "docs/note.md": f"{TRIGGER}\n",
            ".github/workflows/readme.txt": TRIGGER + "\n",
        }
    )
    assert found(guards, "workflow-triggers", root) == []


def test_workflow_triggers_reports_the_line(guards, make_repo) -> None:
    root = make_repo({".github/workflows/x.yml": f"name: x\non:\n  {TRIGGER}:\n"})
    assert found(guards, "workflow-triggers", root) == [(".github/workflows/x.yml", 3)]


# --- annotations -----------------------------------------------------------------------------


def test_annotation_escapes_what_could_inject_a_workflow_command(guards) -> None:
    problem = guards.Problem("a,b:c\n.txt", 7, "100% bad\r\nline")
    assert guards.annotation("disk-paths", problem) == (
        "::error file=a%2Cb%3Ac%0A.txt,line=7,title=disk-paths::100%25 bad%0D%0Aline"
    )


# --- command line ----------------------------------------------------------------------------


def test_main_passes_a_clean_repo_and_runs_every_guard(guards, make_repo, capsys) -> None:
    root = make_repo({"uv.lock": GOOD_LOCK})
    assert guards.main(["--root", str(root)]) == 0
    out = capsys.readouterr().out
    for name in guards.GUARDS:
        assert f"ok    {name}" in out


def test_main_fails_with_one_line_per_problem_and_keeps_going(guards, make_repo, capsys) -> None:
    root = make_repo({"uv.lock": GOOD_LOCK, "a.md": VENDOR, "b.md": f"{VOLUMES}x"})
    assert guards.main(["--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "a.md:1: [vendor-domain]" in out
    assert "b.md:1: [disk-paths]" in out
    assert "ok    lock-hosts" in out
    assert VENDOR not in out


def test_main_runs_only_the_named_guards(guards, make_repo, capsys) -> None:
    root = make_repo({"a.md": VENDOR})
    assert guards.main(["--root", str(root), "disk-paths"]) == 0
    assert "vendor-domain" not in capsys.readouterr().out


def test_main_rejects_an_unknown_guard(guards, make_repo, capsys) -> None:
    root = make_repo({"a.md": "x\n"})
    assert guards.main(["--root", str(root), "nope"]) == 2
    assert "unknown guard nope" in capsys.readouterr().err


def test_main_rejects_a_missing_root(guards, tmp_path, capsys) -> None:
    assert guards.main(["--root", str(tmp_path / "absent")]) == 2
    assert "no such folder" in capsys.readouterr().err


def test_main_reports_a_tool_failure_outside_a_git_repo(guards, tmp_path, capsys) -> None:
    assert guards.main(["--root", str(tmp_path), "vendor-domain"]) == 2
    assert "git grep failed" in capsys.readouterr().err


def test_main_prints_annotations_only_inside_github_actions(
    guards, make_repo, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo({"a.md": VENDOR})
    guards.main(["--root", str(root), "vendor-domain"])
    assert "::error" not in capsys.readouterr().out
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    guards.main(["--root", str(root), "vendor-domain"])
    assert "::error file=a.md,line=1,title=vendor-domain::" in capsys.readouterr().out


def test_main_reports_a_listing_failure_outside_a_git_repo(guards, tmp_path, capsys) -> None:
    assert guards.main(["--root", str(tmp_path), "workflow-triggers"]) == 2
    assert "git ls-files failed" in capsys.readouterr().err


def test_main_reports_a_missing_git_binary(guards, tmp_path, capsys, monkeypatch) -> None:
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(guards.subprocess, "run", no_git)
    assert guards.main(["--root", str(tmp_path), "vendor-domain"]) == 2
    assert "cannot run git" in capsys.readouterr().err


def test_script_runs_isolated_the_way_make_guards_runs_it(make_repo) -> None:
    root = make_repo({"uv.lock": GOOD_LOCK, "a.md": VENDOR})
    run = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 1
    assert "a.md:1: [vendor-domain]" in run.stdout
