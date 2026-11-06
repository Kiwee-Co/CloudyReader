"""A random test-fixture question for the empty question box at start.

A source checkout reads its own tests/fixtures. A dev build (`make app`, START_QUESTIONS=1) carries
a copy of the same `*.txt` files in Contents/Resources/start_questions; a release build carries
none, so its box starts empty. Every well-formed question, one per (file, index) pair, is one
candidate, and each is equally likely: a file of three questions weighs three times one of one.
The box gets the question's own block (Question.raw), its ANSWER line included.
"""

from __future__ import annotations

import logging
import random
import re
from pathlib import Path

from cloudyreader.frozen import bundle_resources_dir, is_frozen
from cloudyreader.models import Question
from cloudyreader.parser import parse

log = logging.getLogger(__name__)

BUNDLED_DIR = "start_questions"  # under a dev build's Contents/Resources: the spec writes it
CHECKOUT_FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
TOSSUP = "tossup_earth_science.txt"
MAX_BYTES = 16_384  # a pasted question is a few hundred bytes: a far larger file is no paste
_SPACE_RUN = re.compile(r"[^\S\n]{2,}")  # two or more spaces, tabs or no-break spaces in a row
_CHOICE_LINE = re.compile(r"([WXYZ])\)[^\S\n]\S")  # the space may be a no-break one: it looks alike


def fixtures_dir() -> Path | None:
    """The fixtures folder: a frozen app's bundled copy, else the checkout's. None when absent."""
    if is_frozen():  # never the checkout's: a frozen app reads only what it carries
        resources = bundle_resources_dir()
        folder = None if resources is None else resources / BUNDLED_DIR
    else:
        folder = CHECKOUT_FIXTURES
    return folder if folder is not None and folder.is_dir() else None


def well_formed(question: Question) -> bool:
    """True for a block that reads as a clean paste; the fixtures' parser-stress layouts do not.

    It has a stem, no tab, no run of two or more spaces, no indented or blank line, and each
    choice on its own line, in order, opening with an uppercase `W) `, `X) `, `Y) ` or `Z) `.
    """
    block = question.raw
    lines = block.split("\n")
    if not question.stem or "\t" in block or _SPACE_RUN.search(block):
        return False
    if any(not line.strip() or line[:1].isspace() for line in lines):
        return False
    starts = [match[1] for line in lines if (match := _CHOICE_LINE.match(line))]
    return not question.choices or starts == list("WXYZ")


def _questions_in(path: Path) -> list[str]:
    """The block of each well-formed question in one fixture; none for an empty, oversized or
    non-UTF-8 file."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return []
        questions = parse(path.read_text(encoding="utf-8"))
    except Exception:  # unreadable, not UTF-8, or a parser bug: only this file is skipped
        log.warning("start question: skipped %s", path.name, exc_info=True)
        return []
    return [question.raw for question in questions if well_formed(question)]


def sample_questions(folder: Path) -> list[str]:
    """Every candidate, one per (file, index) pair: questions/*.txt in name order, then TOSSUP."""
    paths = [*sorted((folder / "questions").glob("*.txt")), folder / TOSSUP]
    return [block for path in paths if path.is_file() for block in _questions_in(path)]


def pick_start_question(rng: random.Random | None = None, folder: Path | None = None) -> str | None:
    """One candidate of sample_questions, each equally likely; None when there is none.

    `folder` defaults to fixtures_dir(). A sample is a courtesy: a broken folder means an empty
    box, never a failed start.
    """
    try:
        folder = fixtures_dir() if folder is None else folder
        questions = [] if folder is None else sample_questions(folder)
    except Exception:
        log.warning("no start question: the fixtures cannot be read", exc_info=True)
        return None
    if not questions:
        return None
    return (random.Random() if rng is None else rng).choice(questions)
