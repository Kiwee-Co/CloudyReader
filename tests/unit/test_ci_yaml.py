"""scripts/ci_yaml.py: strict YAML parse of the tracked files under .github/, on small git repos."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_yaml.py"
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
GOOD = "name: ci\non:\n  push:\n    branches: [main]\njobs:\n  a:\n    runs-on: x\n"


@pytest.fixture
def check(monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("ci_yaml", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "ci_yaml", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[..., Path]:
    def git(root: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(root), *args], check=True, env=CLEAN_ENV, capture_output=True
        )

    def make(files: dict[str, str]) -> Path:
        root = tmp_path / "repo"
        root.mkdir()
        git(root, "init", "-q")
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        git(root, "add", "-A")
        return root

    return make


def test_valid_files_pass_and_other_files_are_ignored(check, make_repo) -> None:
    root = make_repo(
        {
            ".github/workflows/ci.yml": GOOD,
            ".github/dependabot.yaml": "version: 2\n",
            ".github/notes.md": "a: b: c: [\n",
            "elsewhere/bad.yml": "a: [\n",
        }
    )
    assert check.problems(root) == []


def test_empty_file_is_valid(check, make_repo) -> None:
    assert check.problems(make_repo({".github/workflows/e.yml": ""})) == []


def test_syntax_error_reports_file_and_line(check, make_repo) -> None:
    root = make_repo({".github/workflows/x.yml": "a: 1\nb: [1, 2\nc: 3\n"})
    [problem] = check.problems(root)
    assert problem.path == ".github/workflows/x.yml"
    assert problem.line >= 2


def test_duplicate_key_is_rejected_with_its_line(check, make_repo) -> None:
    root = make_repo({".github/workflows/x.yml": "jobs:\n  a: 1\n  b: 2\n  a: 3\n"})
    [problem] = check.problems(root)
    assert (problem.path, problem.line) == (".github/workflows/x.yml", 4)
    assert "duplicate key" in problem.message


def test_duplicate_key_in_a_nested_mapping_is_rejected(check, make_repo) -> None:
    root = make_repo(
        {".github/workflows/x.yml": "on:\n  push:\n    branches: [a]\n    branches: [b]\n"}
    )
    assert [p.line for p in check.problems(root)] == [4]


def test_the_same_key_in_different_mappings_is_fine(check, make_repo) -> None:
    root = make_repo({".github/workflows/x.yml": "a:\n  name: 1\nb:\n  name: 2\n"})
    assert check.problems(root) == []


def test_every_bad_file_is_reported(check, make_repo) -> None:
    root = make_repo({".github/a.yml": "x: [\n", ".github/workflows/b.yaml": "k: 1\nk: 2\n"})
    assert sorted(p.path for p in check.problems(root)) == [
        ".github/a.yml",
        ".github/workflows/b.yaml",
    ]


def test_main_exit_codes_and_output(check, make_repo, capsys) -> None:
    good = make_repo({".github/workflows/ci.yml": GOOD})
    assert check.main(["--root", str(good)]) == 0
    assert "1 file" in capsys.readouterr().out


def test_main_prints_one_line_per_problem(check, tmp_path: Path, make_repo, capsys) -> None:
    root = make_repo({".github/workflows/x.yml": "k: 1\nk: 2\n"})
    assert check.main(["--root", str(root)]) == 1
    assert ".github/workflows/x.yml:2: duplicate key 'k'" in capsys.readouterr().out


def test_main_rejects_a_missing_root_and_a_non_repo(check, tmp_path: Path, capsys) -> None:
    assert check.main(["--root", str(tmp_path / "absent")]) == 2
    assert "no such folder" in capsys.readouterr().err
    assert check.main(["--root", str(tmp_path)]) == 2
    assert "git ls-files failed" in capsys.readouterr().err


def test_script_runs_with_the_interpreter_that_has_yaml(make_repo) -> None:
    root = make_repo({".github/workflows/x.yml": "k: 1\nk: 2\n"})
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 1
    assert "duplicate key" in run.stdout


def test_multi_document_files_are_checked_document_by_document(check, make_repo) -> None:
    root = make_repo({".github/workflows/x.yml": "a: 1\n---\nb: 1\nb: 2\n"})
    assert [p.line for p in check.problems(root)] == [4]


def test_a_reused_anchor_does_not_repeat_a_report(check, make_repo) -> None:
    root = make_repo({".github/workflows/x.yml": "base: &b\n  k: 1\n  k: 2\nuse: *b\n"})
    assert [p.line for p in check.problems(root)] == [3]


def test_a_file_that_is_not_utf8_is_reported_not_raised(check, make_repo) -> None:
    root = make_repo({".github/workflows/x.yml": "a: 1\n"})
    (root / ".github/workflows/x.yml").write_bytes(b"a: \xff\xfe\n")
    [problem] = check.problems(root)
    assert "cannot be read" in problem.message


def test_main_reports_a_missing_git_binary(check, tmp_path: Path, capsys, monkeypatch) -> None:
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(check.subprocess, "run", no_git)
    assert check.main(["--root", str(tmp_path)]) == 2
    assert "cannot run git" in capsys.readouterr().err
