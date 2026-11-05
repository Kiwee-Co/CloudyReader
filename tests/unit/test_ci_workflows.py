"""The CI workflow against the rules it must keep: triggers, permissions, pins, and the `ci` gate.

These read .github/workflows/ci.yml as data. They stand in for what actionlint and zizmor check,
and they run on every test job, so an edit that breaks a rule fails here first.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
JOBS = ("guards", "lint", "pre-commit", "test", "docs", "lock")
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+)(?P<rest>.*)$")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_NOTE = re.compile(r"^\s+# v\d+\.\d+\.\d+\s*$")


def load() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def triggers(doc: dict) -> dict:
    return doc[True] if True in doc else doc["on"]  # YAML 1.1 reads the key `on` as true


def steps(job: str) -> list[dict]:
    return load()["jobs"][job]["steps"]


def test_only_the_ci_workflow_exists() -> None:
    assert sorted(p.name for p in WORKFLOWS.iterdir()) == ["ci.yml"]


def test_job_ids_and_visible_names_match() -> None:
    jobs = load()["jobs"]
    assert set(jobs) == {*JOBS, "ci"}
    assert all(job["name"] == job_id for job_id, job in jobs.items())


def test_triggers_are_push_to_main_pull_request_and_manual_runs_without_path_filters() -> None:
    on = triggers(load())
    assert on == {"push": {"branches": ["main"]}, "pull_request": None, "workflow_dispatch": None}


def test_default_permissions_are_read_only_and_no_job_widens_them() -> None:
    doc = load()
    assert doc["permissions"] == {"contents": "read"}
    assert all("permissions" not in job for job in doc["jobs"].values())


def test_concurrency_cancels_pull_request_runs_only() -> None:
    concurrency = load()["concurrency"]
    assert "github.ref" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


def test_every_job_has_a_timeout_and_a_pinned_runner() -> None:
    for job_id, job in load()["jobs"].items():
        assert isinstance(job["timeout-minutes"], int), job_id
        assert not job["runs-on"].endswith("-latest"), job_id
    assert load()["jobs"]["test"]["runs-on"] == "macos-15"


def test_every_uses_line_is_a_full_commit_sha_with_a_version_note() -> None:
    lines = [m for line in CI.read_text().splitlines() if (m := USES.match(line))]
    assert lines, "no uses: lines found"
    for match in lines:
        assert PINNED.match(match["ref"]), match["ref"]
        assert VERSION_NOTE.match(match["rest"]), match["ref"]


def test_run_blocks_never_hold_an_expression() -> None:
    for job_id, job in load()["jobs"].items():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), f"{job_id}: {step.get('name')}"


def test_no_secrets_no_privileged_trigger_and_no_environment_file_writes() -> None:
    text = CI.read_text(encoding="utf-8")
    for needle in ("secrets.", "pull_request" + "_target", "GITHUB_ENV", "GITHUB_PATH"):
        assert needle not in text, needle


def test_every_checkout_drops_the_token() -> None:
    for job_id, job in load()["jobs"].items():
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False, job_id


def test_tool_pins_are_exact_versions_and_none_is_left_open() -> None:
    env = load()["env"]
    assert set(env) == {"SHELLCHECK_PY", "ACTIONLINT_PY", "ZIZMOR"}
    for name, value in env.items():
        assert re.fullmatch(r"\d+(\.\d+){1,3}", value), f"{name}={value!r}"
    assert "PIN_ME" not in CI.read_text(encoding="utf-8")


def test_the_gate_job_needs_every_other_job_and_always_runs() -> None:
    job = load()["jobs"]["ci"]
    assert sorted(job["needs"]) == sorted(JOBS)
    assert job["if"] == "always()"
    pairs = re.findall(r"(\S+)=\$\{\{ needs\.(\S+)\.result \}\}", job["env"]["RESULTS"])
    assert sorted(pairs) == sorted((name, name) for name in JOBS)


def results(**overrides: str) -> str:
    """A RESULTS value: every job success, except the ones named (underscore for a hyphen)."""
    return " ".join(f"{job}={overrides.get(job.replace('-', '_'), 'success')}" for job in JOBS)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (results(), 0),
        (results(lint="failure"), 1),
        (results(pre_commit="failure"), 1),
        (results(test="cancelled"), 1),
        (results(docs="skipped"), 1),
        ("", 0),
    ],
)
def test_the_gate_script_fails_unless_every_result_is_success(value: str, code: int) -> None:
    script = load()["jobs"]["ci"]["steps"][0]["run"]
    run = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        env={"RESULTS": value, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == code, run.stdout


def test_the_test_job_runs_the_make_gate_offline_and_writes_both_reports() -> None:
    job = load()["jobs"]["test"]
    assert job["env"]["QT_QPA_PLATFORM"] == "offscreen"
    assert job["env"]["CLOUDYREADER_OFFLINE"] == "1"
    gate = next(s for s in job["steps"] if s.get("name") == "Test gate (make test)")
    assert gate["run"].splitlines()[-1] == "make test"
    assert "--junitxml=" in gate["run"] and "--cov-report=xml:" in gate["run"]


def test_the_docs_job_checks_the_source_before_the_jekyll_build() -> None:
    names = [s.get("name") for s in steps("docs")]
    assert names.index("Check the site source") < names.index("Build with Jekyll")


def test_every_setup_uv_step_pins_the_same_uv_version() -> None:
    versions = {
        s["with"]["version"]
        for job in load()["jobs"].values()
        for s in job["steps"]
        if s.get("uses", "").startswith("astral-sh/setup-uv@")
    }
    assert versions == {"0.9.28"}


def test_make_ci_runs_the_guards_first_and_make_guards_calls_the_script() -> None:
    plan = subprocess.run(
        ["make", "-n", "ci"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    assert plan.index("scripts/ci_guards.py") < plan.index("ruff check") < plan.index("pytest")
    assert (
        "python3 -I"
        in subprocess.run(
            ["make", "-n", "guards"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    )


def test_job_env_never_uses_the_runner_context() -> None:
    # GitHub offers `runner` to steps only; a job-level env that names it is rejected.
    doc = load()
    assert "runner." not in str(doc.get("env", {}))
    for job_id, job in doc["jobs"].items():
        assert "runner." not in str(job.get("env", {})), job_id


def test_tool_commands_pin_the_python_so_uv_fetches_no_second_interpreter() -> None:
    for job_id, job in load()["jobs"].items():
        for step in job["steps"]:
            for line in step.get("run", "").splitlines():
                if re.search(r"\b(uvx|uv tool install)\b", line):
                    assert '--python "$(cat .python-version)"' in line, f"{job_id}: {line}"


def test_the_reports_are_uploaded_even_after_a_failure_and_kept_fourteen_days() -> None:
    job = load()["jobs"]["test"]
    upload = next(
        s for s in job["steps"] if s.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["if"] == "${{ !cancelled() }}"
    assert upload["with"]["retention-days"] == 14
    assert upload["with"]["path"] == "${{ runner.temp }}/reports"
    gate = next(s for s in job["steps"] if s.get("name") == "Test gate (make test)")
    assert 'REPORT_DIR="$RUNNER_TEMP/reports"' in gate["run"]
