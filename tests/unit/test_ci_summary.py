"""scripts/ci_summary.py: the Markdown a CI run writes to its step summary, on canned XML.

Every file here is a small hand-made JUnit or coverage.py report; nothing runs pytest.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

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


# --- annotations: which tests failed, in a place a reader can fetch without logs ---------------


def failing(
    name: str,
    *,
    cls: str = "tests.unit.test_x",
    kind: str = "failure",
    message: str = "assert 1 == 2",
    text: str = "",
) -> str:
    return (
        f'<testcase classname={quoteattr(cls)} name={quoteattr(name)} time="0.01">'
        f"<{kind} message={quoteattr(message)}>{escape(text)}</{kind}></testcase>"
    )


def report(*cases: str, tests: int | None = None) -> str:
    count = len(cases) if tests is None else tests
    return junit(suite(count, failures=len(cases)) + "".join(cases) + "</testsuite>")


def annotate(summary, tmp_path: Path, junit_xml: str | None, *, cov=None, floor=None) -> list[str]:
    for rel in ("tests/unit/test_x.py", "tests/unit/test_c.py", "cloudyreader/mod.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x\n", encoding="utf-8")
    junit_path = (
        write(tmp_path, "junit.xml", junit_xml) if junit_xml is not None else tmp_path / "no.xml"
    )
    cov_path = write(tmp_path, "coverage.xml", cov) if cov is not None else tmp_path / "no-cov.xml"
    return summary.annotations(junit_path, cov_path, floor=floor, root=tmp_path)


def test_a_failed_test_gets_its_id_the_crash_line_and_the_first_line_of_the_message(
    summary, tmp_path: Path
) -> None:
    body = failing(
        "test_a",
        message="assert 1 == 2\n + where 1 = f()",
        text=(
            "def test_a():\n>   assert 1 == 2\nE   assert 1 == 2\n\n"
            "tests/unit/test_x.py:5: AssertionError"
        ),
    )

    assert annotate(summary, tmp_path, report(body)) == [
        "::error title=test failed,file=tests/unit/test_x.py,line=5"
        "::tests.unit.test_x.test_a: assert 1 == 2"
    ]


def test_an_errored_test_counts_like_a_failed_one(summary, tmp_path: Path) -> None:
    body = failing("test_s", kind="error", message='failed on setup with "RuntimeError: x"')

    [line] = annotate(summary, tmp_path, report(body))

    assert line.endswith('::tests.unit.test_x.test_s: failed on setup with "RuntimeError: x"')


def test_without_a_crash_line_the_test_module_comes_from_the_class_name(
    summary, tmp_path: Path
) -> None:
    body = failing("test_c", cls="tests.unit.test_x.TestThing", message="boom")

    assert annotate(summary, tmp_path, report(body)) == [
        "::error title=test failed,file=tests/unit/test_x.py"
        "::tests.unit.test_x.TestThing.test_c: boom"
    ]


def test_a_collection_error_names_its_module_from_the_name(summary, tmp_path: Path) -> None:
    body = failing("tests.unit.test_c", cls="", kind="error", message="collection failure")

    assert annotate(summary, tmp_path, report(body)) == [
        "::error title=test failed,file=tests/unit/test_c.py::tests.unit.test_c: collection failure"
    ]


def test_the_last_frame_inside_the_repo_wins_and_outside_frames_are_skipped(
    summary, tmp_path: Path
) -> None:
    text = (
        "tests/unit/test_x.py:5: in test_a\n"
        "cloudyreader/mod.py:30: in f\n"
        ".venv/lib/python3.12/site-packages/lib.py:99: in g\n"
        "/elsewhere/other.py:7: ValueError\n"
    )

    [line] = annotate(summary, tmp_path, report(failing("test_a", text=text)))

    assert line.startswith("::error title=test failed,file=cloudyreader/mod.py,line=30::")


def test_an_absolute_path_inside_the_repo_is_made_relative(summary, tmp_path: Path) -> None:
    text = f"{tmp_path}/tests/unit/test_x.py:9: AssertionError"

    [line] = annotate(summary, tmp_path, report(failing("test_a", text=text)))

    assert line.startswith("::error title=test failed,file=tests/unit/test_x.py,line=9::")


def test_with_no_known_file_the_annotation_has_no_file_or_line(summary, tmp_path: Path) -> None:
    body = failing("test_z", cls="unknown.mod", message="boom")

    assert annotate(summary, tmp_path, report(body)) == [
        "::error title=test failed::unknown.mod.test_z: boom"
    ]


@pytest.mark.parametrize(("count", "extra"), [(10, 0), (11, 1), (25, 15)])
def test_at_most_ten_errors_then_one_notice_with_the_rest(
    summary, tmp_path: Path, count: int, extra: int
) -> None:
    cases = [failing(f"test_{i}") for i in range(count)]

    lines = annotate(summary, tmp_path, report(*cases))

    assert sum(line.startswith("::error title=test failed") for line in lines) == min(count, 10)
    notices = [line for line in lines if line.startswith("::notice")]
    if extra:
        assert len(notices) == 1
        assert notices[0].startswith("::notice title=more failed tests::")
        assert f"{extra} more failed test" in notices[0]
    else:
        assert notices == []


def test_one_more_failure_is_singular(summary, tmp_path: Path) -> None:
    lines = annotate(summary, tmp_path, report(*[failing(f"test_{i}") for i in range(11)]))

    assert "1 more failed test;" in lines[-1]


def test_escaping_keeps_repo_text_from_forming_a_second_command(summary, tmp_path: Path) -> None:
    sneaky = failing("test_a\r\n::error::injected", message="100% sure\n::error::second")

    lines = annotate(summary, tmp_path, report(sneaky))

    assert len(lines) == 1
    assert "\n" not in lines[0] and "\r" not in lines[0]
    assert "test_a%0D%0A::error::injected: 100%25 sure" in lines[0]


def test_property_values_escape_colon_comma_percent_and_line_breaks(summary) -> None:
    assert summary.escape_property("a:b,c%\r\n") == "a%3Ab%2Cc%25%0D%0A"
    assert summary.escape_data("a:b,c%\r\n") == "a:b,c%25%0D%0A"


def test_a_long_first_line_is_cut_to_300_characters(summary, tmp_path: Path) -> None:
    [line] = annotate(summary, tmp_path, report(failing("test_a", message="x" * 500)))

    message = line.split("::", 2)[2].split(": ", 1)[1]
    assert len(message) == 300 and message.endswith("...")


@pytest.mark.parametrize("xml", [None, "", report(tests=0)], ids=["missing", "empty", "no tests"])
def test_a_missing_or_empty_report_is_one_error(summary, tmp_path: Path, xml) -> None:
    lines = annotate(summary, tmp_path, xml)

    assert len(lines) == 1
    assert lines[0].startswith("::error title=no test report::")


def test_a_clean_report_prints_nothing(summary, tmp_path: Path) -> None:
    clean = junit(suite(3) + case("a") + "</testsuite>")
    ok = coverage((100, 90), ("a.py", 100, 90))

    assert annotate(summary, tmp_path, clean, cov=ok, floor=75.0) == []


def test_coverage_under_the_floor_is_one_error_and_at_the_floor_is_none(summary, tmp_path) -> None:
    clean = junit(suite(3) + case("a") + "</testsuite>")

    under = annotate(summary, tmp_path, clean, cov=coverage((100, 70)), floor=75.0)
    at = annotate(summary, tmp_path, clean, cov=coverage((100, 75)), floor=75.0)

    # GitHub reads %25 as a percent sign, so the message carries it escaped.
    assert under == [
        "::error title=coverage::coverage 70.00%25 is below the floor of 75%25 (70 of 100 lines)"
    ]
    assert at == []


def test_no_floor_or_no_coverage_report_means_no_coverage_annotation(summary, tmp_path) -> None:
    clean = junit(suite(3) + case("a") + "</testsuite>")

    assert annotate(summary, tmp_path, clean, cov=coverage((100, 10)), floor=None) == []
    assert annotate(summary, tmp_path, clean, cov=None, floor=75.0) == []


def test_the_default_floor_is_the_makefile_value_and_the_environment_overrides_it(
    summary, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    makefile = tmp_path / "Makefile"
    makefile.write_text("A ?= 1\nCOV_MIN ?= 80\nB ?= 2\n", encoding="utf-8")
    monkeypatch.delenv("COV_MIN", raising=False)

    assert summary.default_floor(makefile) == 80.0
    monkeypatch.setenv("COV_MIN", "90")
    assert summary.default_floor(makefile) == 90.0
    monkeypatch.setenv("COV_MIN", "not a number")
    assert summary.default_floor(makefile) == 80.0
    monkeypatch.delenv("COV_MIN")
    assert summary.default_floor(tmp_path / "absent") is None
    makefile.write_text("nothing here\n", encoding="utf-8")
    assert summary.default_floor(makefile) is None


def test_the_repo_makefile_has_a_floor_the_script_can_read(summary, monkeypatch) -> None:
    monkeypatch.delenv("COV_MIN", raising=False)

    assert 1 <= summary.default_floor(SCRIPT.parent.parent / "Makefile") <= 100


def test_annotate_mode_prints_only_commands_and_exits_zero(
    summary, tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    annotate(summary, tmp_path, report(failing("test_a")))  # builds the files and junit.xml

    code = summary.main(
        ["--junit", "junit.xml", "--coverage", "absent.xml", "--annotate", "--floor", "75"]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("::error title=test failed")
    assert "###" not in out


def test_script_prints_annotations_isolated(tmp_path: Path) -> None:
    (tmp_path / "tests/unit").mkdir(parents=True)
    (tmp_path / "tests/unit/test_x.py").write_text("x\n", encoding="utf-8")
    write(
        tmp_path,
        "junit.xml",
        report(failing("test_a", text="tests/unit/test_x.py:3: AssertionError")),
    )

    run = subprocess.run(
        [
            sys.executable,
            "-I",
            str(SCRIPT),
            "--junit",
            "junit.xml",
            "--coverage",
            "c.xml",
            "--annotate",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0
    assert "::error title=test failed,file=tests/unit/test_x.py,line=3::" in run.stdout


def test_a_command_without_properties_still_escapes_its_message(summary) -> None:
    assert summary._command("notice", "50%\nnext") == "::notice::50%25%0Anext"


def test_a_failure_with_no_message_and_no_text_is_still_named(summary, tmp_path: Path) -> None:
    body = failing("test_a", message="", text="")

    assert annotate(summary, tmp_path, report(body)) == [
        "::error title=test failed,file=tests/unit/test_x.py::tests.unit.test_x.test_a"
    ]
