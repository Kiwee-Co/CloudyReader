"""The start question: one test-fixture question, at random, for the empty question box."""

from __future__ import annotations

import logging
import random
import shutil
import sys
from pathlib import Path

import pytest

from cloudyreader import start_question
from cloudyreader.parser import parse
from cloudyreader.start_question import (
    BUNDLED_DIR,
    CHECKOUT_FIXTURES,
    MAX_BYTES,
    fixtures_dir,
    pick_start_question,
    sample_questions,
    well_formed,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
TOSSUP = FIXTURES / "tossup_earth_science.txt"
FILES = [*sorted((FIXTURES / "questions").glob("*.txt")), TOSSUP]
GOOD = "TOSS-UP\n1) PHYSICS Short Answer What is the SI unit of force?\nANSWER: NEWTON\n"
PAIR = (
    "TOSS-UP\n2) MATH Short Answer What is 2 + 2?\nANSWER: 4\n"
    "BONUS\n2) MATH Short Answer What is 3 + 3?\nANSWER: 6\n"
)


class Chooser:
    """A stand-in for random.Random: records what it was offered, returns one item by index."""

    def __init__(self, index: int) -> None:
        self.index = index
        self.offered: list[str] = []

    def choice(self, seq: list[str]) -> str:
        self.offered = list(seq)
        return seq[self.index]


def fixture_folder(root: Path, files: dict[str, str | bytes]) -> Path:
    """A fixtures folder under root: each relative name holds its text (or bytes)."""
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return root


def bundle(root: Path, *, with_copy: bool) -> Path:
    """A fake "Cloudy Reader.app" under root; its bundled copy holds GOOD when with_copy."""
    contents = root / "Cloudy Reader.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "MacOS" / "Cloudy Reader").write_text("")
    (contents / "Resources").mkdir()
    if with_copy:
        fixture_folder(contents / "Resources" / BUNDLED_DIR, {"questions/01-good.txt": GOOD})
    return contents / "MacOS" / "Cloudy Reader"


def frozen_as(monkeypatch: pytest.MonkeyPatch, executable: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))


# --- where the fixtures are ----------------------------------------------------------------------


def test_a_checkout_reads_its_own_tests_fixtures():
    assert CHECKOUT_FIXTURES == FIXTURES
    assert fixtures_dir() == FIXTURES


def test_a_frozen_dev_app_reads_its_bundled_copy(monkeypatch, tmp_path):
    frozen_as(monkeypatch, bundle(tmp_path, with_copy=True))

    folder = fixtures_dir()

    assert folder is not None
    assert folder.resolve() == (tmp_path / "Cloudy Reader.app/Contents/Resources/start_questions")
    assert pick_start_question(random.Random(0)) == GOOD.strip()


def test_a_frozen_release_app_finds_none_even_beside_a_checkout(monkeypatch, tmp_path):
    frozen_as(monkeypatch, bundle(tmp_path, with_copy=False))

    assert FIXTURES.is_dir()  # the checkout's copy is right here, and still not used
    assert fixtures_dir() is None
    assert pick_start_question(random.Random(0)) is None


def test_a_frozen_executable_outside_an_app_finds_none(monkeypatch, tmp_path):
    executable = tmp_path / "bin" / "cloudyreader"
    executable.parent.mkdir()
    executable.write_text("")
    frozen_as(monkeypatch, executable)

    assert fixtures_dir() is None


def test_no_question_when_the_folder_is_missing_or_empty(monkeypatch, tmp_path):
    assert pick_start_question(random.Random(0), tmp_path / "missing") is None
    (tmp_path / "empty" / "questions").mkdir(parents=True)
    assert pick_start_question(random.Random(0), tmp_path / "empty") is None

    monkeypatch.setattr(start_question, "CHECKOUT_FIXTURES", tmp_path / "missing")
    assert fixtures_dir() is None
    assert pick_start_question() is None


# --- which questions ---------------------------------------------------------------------------

CHOICES = "W) Crust\nX) Mantle\nY) Outer core\nZ) Inner core"
SA = "TOSS-UP\n4) ENERGY Short Answer What is the SI unit of power?\nANSWER: WATT"


def mc(choices: str = CHOICES) -> str:
    """A multiple-choice paste with these choice lines."""
    stem = "BONUS\n3) EARTH SCIENCE Multiple Choice Which layer of Earth is liquid?"
    return f"{stem}\n{choices}\nANSWER: Y) OUTER CORE"


def test_the_rule_keeps_a_clean_paste():
    no_answer = mc().rsplit("\n", 1)[0]
    no_break = mc(CHOICES.replace(") ", ")\u00a0"))  # a no-break space looks like a space
    stem_only = "What gas do plants take in during photosynthesis?"
    for block in (mc(), SA, no_answer, no_break, stem_only):
        [question] = parse(block)
        assert well_formed(question), block


@pytest.mark.parametrize(
    ("layout", "block"),
    [
        ("a tab between tokens", SA.replace("SI unit", "SI\tunit")),
        ("a run of two spaces", SA.replace("SI unit", "SI  unit")),
        ("trailing spaces", SA.replace("power?", "power?   ")),
        ("an indented line", SA.replace("\nANSWER", "\n   ANSWER")),
        ("a blank line", SA.replace("\nANSWER", "\n\nANSWER")),
        ("lowercase markers", mc("w) Crust\nx) Mantle\ny) Outer core\nz) Inner core")),
        ("dot markers", mc("W. Crust\nX. Mantle\nY. Outer core\nZ. Inner core")),
        ("colon markers", mc("W: Crust\nX: Mantle\nY: Outer core\nZ: Inner core")),
        ("markers without a space", mc("W)Crust\nX)Mantle\nY)Outer core\nZ)Inner core")),
        ("choices on one line", mc("W) Crust X) Mantle Y) Outer core Z) Inner core")),
        ("choices out of order", mc("W) Crust\nY) Mantle\nX) Outer core\nZ) Inner core")),
    ],
)
def test_the_rule_drops_a_parser_stress_layout(layout, block):
    [question] = parse(block)

    assert question.choices or "Multiple" not in block, layout  # the parser still reads them
    assert not well_formed(question), layout


def test_a_choiceless_question_needs_its_stem():
    [question] = parse("W) a\nX) b\nY) c\nZ) d")

    assert not question.stem
    assert not well_formed(question)


def test_each_file_and_index_pair_is_one_candidate(tmp_path):
    folder = fixture_folder(
        tmp_path,
        {"questions/01.txt": PAIR, "questions/02.txt": GOOD, "tossup_earth_science.txt": GOOD},
    )

    halves = [question.raw for question in parse(PAIR)]

    # A file of two questions gives two candidates; the same text in two files counts twice.
    assert sample_questions(folder) == [*halves, GOOD.strip(), GOOD.strip()]
    assert all(len(parse(half)) == 1 for half in halves)


def test_the_real_folder_offers_its_well_formed_questions_in_file_order():
    questions = sample_questions(FIXTURES)

    expected = [
        question.raw
        for path in FILES
        for question in parse(path.read_text(encoding="utf-8"))
        if well_formed(question)
    ]
    assert questions == expected
    assert len(questions) >= 40  # most fixtures are clean pastes; the count itself may move
    assert all(len(parse(text)) == 1 for text in questions)  # each is one question's own block


def test_the_pick_is_one_uniform_choice_over_every_candidate():
    questions = sample_questions(FIXTURES)
    chooser = Chooser(-1)

    picked = pick_start_question(chooser, FIXTURES)  # type: ignore[arg-type]

    assert chooser.offered == questions  # every (file, index) pair once: not one per file
    assert picked == questions[-1]


def test_a_seeded_pick_is_deterministic():
    first = pick_start_question(random.Random(7), FIXTURES)

    assert first in sample_questions(FIXTURES)
    assert pick_start_question(random.Random(7), FIXTURES) == first


def test_seeded_picks_cover_every_eligible_question(tmp_path):
    folder = fixture_folder(
        tmp_path,
        {
            "questions/01.txt": GOOD,
            "questions/02.txt": PAIR,
            "tossup_earth_science.txt": GOOD.replace("force", "work"),
        },
    )
    rng = random.Random(2026)

    picks = {pick_start_question(rng, folder) for _ in range(200)}

    assert picks == set(sample_questions(folder))
    assert len(picks) == 4  # GOOD, the two halves of PAIR, and the top-level file


def test_ineligible_fixtures_are_skipped(tmp_path):
    folder = fixture_folder(
        tmp_path,
        {
            "questions/.DS_Store": b"\x00\x00\x00\x01Bud1\x00",
            "questions/01-good.txt": GOOD,
            "questions/02-empty.txt": "",
            "questions/03-blank.txt": "  \n\t\n",
            "questions/04-noise.txt": "ROUND ROBIN 2\n~~~~~~~~~~\nPage 3\n",
            "questions/05-choices-only.txt": "W) a\nX) b\nY) c\nZ) d\n",
            "questions/06-not-utf8.txt": b"TOSS-UP\n1) What is \xff\xfe?\n",
            "questions/07-huge.txt": GOOD.replace("force", "x" * MAX_BYTES),
            "questions/08-notes.md": GOOD.replace("force", "energy"),
            "questions/sub/09-nested.txt": GOOD.replace("force", "power"),
            "questions/11-tabs.txt": GOOD.replace("SI unit", "SI\tunit"),
            "other.txt": GOOD.replace("force", "charge"),
            ".DS_Store": b"\x00\x00\x00\x01Bud1\x00",
        },
    )
    (folder / "questions" / "10-folder.txt").mkdir()

    assert sample_questions(folder) == [GOOD.strip()]


def test_a_fixture_the_parser_fails_on_is_skipped_with_a_warning(monkeypatch, tmp_path, caplog):
    folder = fixture_folder(tmp_path, {"questions/01-bad.txt": "BAD", "questions/02.txt": GOOD})
    real = start_question.parse

    def parse_or_fail(text: str):
        if text == "BAD":
            raise ValueError("parser bug")
        return real(text)

    monkeypatch.setattr(start_question, "parse", parse_or_fail)

    with caplog.at_level(logging.WARNING, logger="cloudyreader.start_question"):
        assert sample_questions(folder) == [GOOD.strip()]
    assert "01-bad.txt" in caplog.text


def test_a_broken_fixture_folder_means_no_question_never_an_error(monkeypatch, tmp_path, caplog):
    def broken(folder: Path) -> list[str]:
        raise PermissionError("no access")

    monkeypatch.setattr(start_question, "sample_questions", broken)

    with caplog.at_level(logging.WARNING, logger="cloudyreader.start_question"):
        assert pick_start_question(random.Random(0), tmp_path) is None
    assert "no start question" in caplog.text


def test_the_bundled_copy_keeps_the_fixture_layout(tmp_path):
    copy = tmp_path / BUNDLED_DIR
    (copy / "questions").mkdir(parents=True)
    for path in FILES[:-1]:
        shutil.copy(path, copy / "questions")
    shutil.copy(TOSSUP, copy)

    assert sample_questions(copy) == sample_questions(FIXTURES)
