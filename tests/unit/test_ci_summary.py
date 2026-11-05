"""scripts/ci_summary.py: the Markdown a CI run writes to its step summary, on canned XML.

Every file here is a small hand-made JUnit or coverage.py report; nothing runs pytest.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_summary.py"


@pytest.fixture
def summary(monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("ci_summary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses looks its module up in sys.modules while it builds the script's classes.
    monkeypatch.setitem(sys.modules, "ci_summary", module)
    spec.loader.exec_module(module)
    return module


def junit(*suites: str) -> str:
    return f'<?xml version="1.0"?><testsuites>{"".join(suites)}</testsuites>'


def suite(tests: int, failures: int = 0, errors: int = 0, skipped: int = 0, time: float = 1.5):
    return (
        f'<testsuite name="pytest" tests="{tests}" failures="{failures}" errors="{errors}" '
        f'skipped="{skipped}" time="{time}">'
    )


def case(name: str, kind: str = "", cls: str = "tests.unit.test_x") -> str:
    inner = f'<{kind} message="boom"/>' if kind else ""
    return f'<testcase classname="{cls}" name="{name}" time="0.01">{inner}</testcase>'


def coverage(total: tuple[int, int], *files: tuple[str, int, int]) -> str:
    """total and each file are (valid lines, covered lines); line elements are generated."""
    classes = ""
    for name, valid, covered in files:
        lines = "".join(f'<line number="{i}" hits="{int(i < covered)}"/>' for i in range(valid))
        classes += f'<class name="{name}" filename="{name}"><lines>{lines}</lines></class>'
    valid, covered = total
    return (
        f'<?xml version="1.0"?><coverage lines-valid="{valid}" lines-covered="{covered}">'
        f"<packages><package name='p'><classes>{classes}</classes></package></packages></coverage>"
    )


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --- JUnit -----------------------------------------------------------------------------------


def test_junit_totals_passed_failed_skipped_and_time(summary, tmp_path: Path) -> None:
    xml = junit(suite(10, failures=1, errors=2, skipped=3, time=65.14) + "</testsuite>")
    result = summary.read_junit(write(tmp_path, "j.xml", xml))
    assert (result.tests, result.passed, result.failed, result.errors, result.skipped) == (
        10,
        4,
        1,
        2,
        3,
    )
    assert result.seconds == pytest.approx(65.14)


def test_junit_sums_suites_and_accepts_a_bare_testsuite_root(summary, tmp_path: Path) -> None:
    two = junit(suite(4) + "</testsuite>", suite(6, skipped=1) + "</testsuite>")
    assert summary.read_junit(write(tmp_path, "a.xml", two)).tests == 10
    bare = f'<?xml version="1.0"?>{suite(7)}</testsuite>'
    assert summary.read_junit(write(tmp_path, "b.xml", bare)).tests == 7


def test_junit_lists_at_most_twenty_bad_tests_and_counts_the_rest(summary, tmp_path: Path) -> None:
    body = "".join(case(f"test_{i}", "failure") for i in range(25))
    xml = junit(suite(25, failures=25) + body + "</testsuite>")
    text = summary.render(summary.read_junit(write(tmp_path, "j.xml", xml)), None, top=5)
    assert text.count("- `tests.unit.test_x.test_") == 20
    assert "- and 5 more" in text


def test_junit_collects_failing_and_erroring_test_ids(summary, tmp_path: Path) -> None:
    body = case("test_a") + case("test_b", "failure") + case("test_c", "error", "tests.gui.test_w")
    xml = junit(suite(3, failures=1, errors=1) + body + "</testsuite>")
    result = summary.read_junit(write(tmp_path, "j.xml", xml))
    assert result.bad == ["tests.unit.test_x.test_b", "tests.gui.test_w.test_c"]


def test_junit_unreadable_inputs_give_none(summary, tmp_path: Path) -> None:
    assert summary.read_junit(tmp_path / "absent.xml") is None
    assert summary.read_junit(write(tmp_path, "bad.xml", "<testsuites>")) is None


# --- coverage --------------------------------------------------------------------------------


def test_coverage_total_and_per_file_percent(summary, tmp_path: Path) -> None:
    xml = coverage((30, 27), ("pkg/a.py", 10, 10), ("pkg/b.py", 20, 17))
    result = summary.read_coverage(write(tmp_path, "c.xml", xml))
    assert result.percent == pytest.approx(90.0)
    assert [(f.name, f.valid, f.covered) for f in result.files] == [
        ("pkg/a.py", 10, 10),
        ("pkg/b.py", 20, 17),
    ]


def test_coverage_without_totals_sums_the_files(summary, tmp_path: Path) -> None:
    xml = coverage((0, 0), ("a.py", 4, 2)).replace('lines-valid="0" lines-covered="0"', "")
    assert summary.read_coverage(write(tmp_path, "c.xml", xml)).percent == pytest.approx(50.0)


def test_coverage_unreadable_inputs_give_none(summary, tmp_path: Path) -> None:
    assert summary.read_coverage(tmp_path / "absent.xml") is None
    assert summary.read_coverage(write(tmp_path, "bad.xml", "<coverage>")) is None


# --- rendering -------------------------------------------------------------------------------


def test_render_shows_the_test_table(summary, tmp_path: Path) -> None:
    xml = junit(
        suite(10, failures=1, skipped=3, time=65.14) + case("t", "failure") + "</testsuite>"
    )
    text = summary.render(summary.read_junit(write(tmp_path, "j.xml", xml)), None, top=5)
    assert "| 10 | 6 | 1 | 0 | 3 | 65.1 s |" in text
    assert "- `tests.unit.test_x.t`" in text


def test_render_lists_files_below_full_coverage_lowest_first_and_counts_the_rest(
    summary, tmp_path: Path
) -> None:
    xml = coverage(
        (40, 30),
        ("full.py", 10, 10),
        ("mid.py", 10, 8),
        ("low.py", 20, 12),
    )
    text = summary.render(None, summary.read_coverage(write(tmp_path, "c.xml", xml)), top=5)
    assert "Total: **75.00%** (30 of 40 lines)" in text
    assert text.index("low.py") < text.index("mid.py")
    assert "| `low.py` | 20 | 8 | 60.00% |" in text
    assert "full.py" not in text
    assert "1 file at 100%" in text


def test_render_truncates_the_file_list_at_top(summary, tmp_path: Path) -> None:
    files = [(f"f{i}.py", 10, i) for i in range(5)]
    xml = coverage((50, 10), *files)
    text = summary.render(None, summary.read_coverage(write(tmp_path, "c.xml", xml)), top=2)
    assert "`f0.py`" in text and "`f1.py`" in text and "`f2.py`" not in text
    assert "3 more files below 100%" in text


def test_render_all_files_at_full_coverage(summary, tmp_path: Path) -> None:
    xml = coverage((20, 20), ("a.py", 10, 10), ("b.py", 10, 10))
    text = summary.render(None, summary.read_coverage(write(tmp_path, "c.xml", xml)), top=5)
    assert "All 2 files at 100%" in text


def test_render_escapes_markdown_in_names(summary, tmp_path: Path) -> None:
    xml = coverage((10, 5), ("we|ird`name.py", 10, 5))
    text = summary.render(None, summary.read_coverage(write(tmp_path, "c.xml", xml)), top=5)
    assert "| `we\\|ird'name.py` |" in text


def test_render_notes_a_missing_report(summary) -> None:
    text = summary.render(None, None, top=5)
    assert "No JUnit report was written" in text
    assert "No coverage report was written" in text


# --- command line ----------------------------------------------------------------------------


def test_main_prints_markdown_and_exits_zero_even_when_files_are_missing(
    summary, tmp_path: Path, capsys
) -> None:
    code = summary.main(
        ["--junit", str(tmp_path / "no.xml"), "--coverage", str(tmp_path / "no2.xml")]
    )
    assert code == 0
    assert "No JUnit report was written" in capsys.readouterr().out


def test_script_runs_isolated_and_writes_to_stdout(tmp_path: Path) -> None:
    junit_path = write(tmp_path, "j.xml", junit(suite(2) + "</testsuite>"))
    cov_path = write(tmp_path, "c.xml", coverage((10, 10), ("a.py", 10, 10)))
    run = subprocess.run(
        [
            sys.executable,
            "-I",
            str(SCRIPT),
            "--junit",
            str(junit_path),
            "--coverage",
            str(cov_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0
    assert "| 2 | 2 | 0 | 0 | 0 | 1.5 s |" in run.stdout
    assert "Total: **100.00%**" in run.stdout


def test_reports_with_a_dtd_are_refused(summary, tmp_path: Path) -> None:
    xml = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><testsuites/>'
    assert summary.read_junit(write(tmp_path, "d.xml", xml)) is None
    assert summary.read_coverage(write(tmp_path, "e.xml", xml)) is None
