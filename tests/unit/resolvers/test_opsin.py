"""OpsinResolver: batching, name hygiene, status mapping, and crash containment.

The default gate fakes the JVM (`subprocess.run`); the `java` tests run the bundled jar for real.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Literal

import jdk4py
import pytest

from cloudyreader.models import Resolution
from cloudyreader.resolvers import opsin
from cloudyreader.resolvers.opsin import OpsinResolver

LOGGER = "cloudyreader.resolvers.opsin"


@dataclass
class Call:
    cmd: list[str]
    kwargs: dict
    names: list[str]  # lines of the names file as the JVM would have read them


class FakeJvm:
    """Stands in for `subprocess.run`: OPSIN answers one stdout line per input line."""

    def __init__(self) -> None:
        self.answers: dict[str, str] = {}  # name -> SMILES; an unknown name answers ""
        self.stdout: str | None = None  # replaces the whole stdout when set
        self.returncode = 0
        self.error: BaseException | None = None  # raised instead of answering
        self.calls: list[Call] = []

    def __call__(self, cmd, **kwargs):
        # The names file lives in a temp dir that is gone once the call returns.
        names = Path(cmd[-1]).read_text(encoding="utf-8").splitlines()
        self.calls.append(Call(list(cmd), kwargs, names))
        if self.error is not None:
            raise self.error
        if self.stdout is None:
            self.stdout = "".join(f"{self.answers.get(name, '')}\n" for name in names)
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout.encode(), b"")


@pytest.fixture
def jvm(monkeypatch: pytest.MonkeyPatch) -> FakeJvm:
    fake = FakeJvm()
    monkeypatch.setattr(opsin.subprocess, "run", fake)
    return fake


def ok(query: str, smiles: str) -> Resolution:
    return Resolution(query, "iupac", smiles, {"smiles": smiles}, "opsin", "ok")


def miss(query: str, status: Literal["not_found", "timeout", "error"] = "not_found") -> Resolution:
    return Resolution(query, "iupac", None, {}, "opsin", status)


def test_empty_batch_returns_empty_and_starts_no_jvm(jvm):
    assert OpsinResolver().resolve_batch([]) == {}
    assert jvm.calls == []


@pytest.mark.parametrize("blank", ["", "   ", " \n\t "])
def test_blank_name_is_not_found_without_a_jvm_start(jvm, blank):
    assert OpsinResolver().resolve_batch([blank]) == {blank: miss(blank)}
    assert jvm.calls == []


def test_parsed_name_becomes_an_ok_resolution(jvm):
    jvm.answers = {"2-methylpropan-1-ol": "CC(CO)C"}
    result = OpsinResolver().resolve_batch(["2-methylpropan-1-ol"])
    assert result == {"2-methylpropan-1-ol": ok("2-methylpropan-1-ol", "CC(CO)C")}


def test_unparseable_name_is_not_found_and_neighbours_keep_their_answers(jvm):
    jvm.answers = {"ethanol": "CCO", "propan-1-ol": "CCCO"}
    result = OpsinResolver().resolve_batch(["ethanol", "qwerty nonsense", "propan-1-ol"])
    assert result == {
        "ethanol": ok("ethanol", "CCO"),
        "qwerty nonsense": miss("qwerty nonsense"),
        "propan-1-ol": ok("propan-1-ol", "CCCO"),
    }


def test_whole_batch_costs_one_jvm_start(jvm):
    names = ["ethanol", "propan-1-ol", "butan-1-ol"]
    OpsinResolver().resolve_batch(names)
    assert len(jvm.calls) == 1
    assert jvm.calls[0].names == names


def test_names_are_stripped_and_deduped_but_result_keys_are_the_inputs(jvm):
    jvm.answers = {"ethanol": "CCO"}
    result = OpsinResolver().resolve_batch(["  ethanol\n", "ethanol", "ethanol"])
    assert jvm.calls[0].names == ["ethanol"]
    assert result == {"  ethanol\n": ok("  ethanol\n", "CCO"), "ethanol": ok("ethanol", "CCO")}


def test_line_break_inside_a_name_cannot_shift_the_answers(jvm):
    # The CLI reads one name per line: a stray break would pair every later SMILES with the
    # wrong name.
    jvm.answers = {"sodium chloride": "[Na+].[Cl-]", "ethanol": "CCO"}
    result = OpsinResolver().resolve_batch(["sodium\r\nchloride", "ethanol"])
    assert jvm.calls[0].names == ["sodium chloride", "ethanol"]
    assert result["sodium\r\nchloride"].canonical == "[Na+].[Cl-]"
    assert result["ethanol"].canonical == "CCO"


def test_blank_names_are_left_out_of_the_batch_but_keep_a_result(jvm):
    jvm.answers = {"ethanol": "CCO"}
    result = OpsinResolver().resolve_batch(["", "ethanol"])
    assert jvm.calls[0].names == ["ethanol"]
    assert result == {"": miss(""), "ethanol": ok("ethanol", "CCO")}


def test_timeout_marks_every_name_and_forwards_the_budget(jvm, caplog):
    jvm.error = subprocess.TimeoutExpired(cmd="java", timeout=3.5)
    names = ["ethanol", "propan-1-ol"]
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = OpsinResolver().resolve_batch(names, timeout_s=3.5)
    assert result == {name: miss(name, "timeout") for name in names}
    assert jvm.calls[0].kwargs["timeout"] == 3.5
    assert "timed out" in caplog.text


def test_default_budget_is_twenty_seconds(jvm):
    OpsinResolver().resolve_batch(["ethanol"])
    assert jvm.calls[0].kwargs["timeout"] == 20.0


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("java"),
        PermissionError("jar"),
        OSError("exec format"),
        RuntimeError("boom"),
    ],
)
def test_crash_never_raises_and_is_status_error(jvm, caplog, error):
    jvm.error = error
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = OpsinResolver().resolve_batch(["ethanol"])
    assert result == {"ethanol": miss("ethanol", "error")}
    assert "failed" in caplog.text


def test_nonzero_exit_is_status_error_even_with_output(jvm):
    jvm.returncode = 1
    jvm.answers = {"ethanol": "CCO"}  # output of a crashed JVM is not trusted
    assert OpsinResolver().resolve_batch(["ethanol"]) == {"ethanol": miss("ethanol", "error")}


@pytest.mark.parametrize("stdout", ["", "CCO\nCCCO\n", "CCO\nCCCO\nCCCCO\nC\n"])
def test_answer_count_mismatch_is_status_error_for_all(jvm, caplog, stdout):
    # A misaligned answer would attach a SMILES to the wrong name, so none is trusted.
    jvm.stdout = stdout
    names = ["ethanol", "propan-1-ol", "butan-1-ol"]
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = OpsinResolver().resolve_batch(names)
    assert result == {name: miss(name, "error") for name in names}
    assert "answer(s) for 3 name(s)" in caplog.text


def test_failed_batch_still_answers_blank_names_as_not_found(jvm):
    jvm.error = subprocess.TimeoutExpired(cmd="java", timeout=1)
    result = OpsinResolver().resolve_batch(["", "ethanol"], timeout_s=1)
    assert result == {"": miss(""), "ethanol": miss("ethanol", "timeout")}


@pytest.mark.parametrize("installed", [False, True], ids=["no-py2opsin", "py2opsin-without-jar"])
def test_missing_runtime_degrades_to_error_without_a_jvm_start(
    jvm, monkeypatch, tmp_path, installed
):
    spec = ModuleSpec("py2opsin", None, is_package=True)
    spec.submodule_search_locations = [str(tmp_path)]  # a package folder holding no jar
    monkeypatch.setattr(opsin.importlib.util, "find_spec", lambda name: spec if installed else None)
    assert OpsinResolver().resolve_batch(["ethanol"]) == {"ethanol": miss("ethanol", "error")}
    assert jvm.calls == []


def test_bundled_jre_runs_by_absolute_path_and_environ_stays_untouched(jvm, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    environ_before = dict(os.environ)
    OpsinResolver().resolve_batch(["ethanol"])
    cmd = jvm.calls[0].cmd
    assert cmd[:2] == [str(jdk4py.JAVA), "-jar"]
    assert Path(cmd[2]).is_file()
    assert cmd[3] == "-osmi"
    assert dict(os.environ) == environ_before


def test_names_file_lives_in_a_fresh_temp_dir_and_is_removed(jvm, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    OpsinResolver().resolve_batch(["ethanol"])
    names_file = Path(jvm.calls[0].cmd[-1])
    assert names_file.parent != tmp_path
    assert not names_file.exists()
    assert list(tmp_path.iterdir()) == []  # py2opsin's default would leave a file in the CWD


def test_resolution_carries_only_a_smiles_never_a_name(jvm):
    # R5: a resolved or common name must never reach the speech path ("NaHCO3" is never
    # "baking soda"), so the resolution holds a SMILES and nothing else.
    jvm.answers = {"sodium hydrogencarbonate": "C(O)([O-])=O.[Na+]"}
    res = OpsinResolver().resolve_batch(["sodium hydrogencarbonate"])["sodium hydrogencarbonate"]
    assert res.query == "sodium hydrogencarbonate"
    assert set(res.ids) == {"smiles"}
    assert res.canonical == res.ids["smiles"] == "C(O)([O-])=O.[Na+]"


@pytest.mark.java
def test_real_jar_resolves_a_batch_in_one_jvm_start():
    names = ["2-methylpropan-1-ol", "1,2-dichloroethane", "qwerty zxcv nonsense"]
    result = OpsinResolver().resolve_batch(names, timeout_s=60.0)
    assert [result[name].status for name in names] == ["ok", "ok", "not_found"]
    assert result["2-methylpropan-1-ol"].canonical == "CC(CO)C"
    assert result["1,2-dichloroethane"].canonical == "ClCCCl"
    assert result["qwerty zxcv nonsense"].canonical is None


@pytest.mark.java
def test_real_jvm_is_killed_when_the_budget_runs_out():
    # A JVM cannot start and parse inside 50 ms, so this always hits the kill path.
    result = OpsinResolver().resolve_batch(["ethanol"], timeout_s=0.05)
    assert result == {"ethanol": miss("ethanol", "timeout")}
