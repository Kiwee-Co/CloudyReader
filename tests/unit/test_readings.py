"""Readings a science moderator gives that the stages alone missed, through the real normalizer."""

import pytest

from cloudyreader.models import Question, RenderOptions
from cloudyreader.normalize import ScriptNormalizer

EN_DASH = "–"


class NoHardWords:
    """A lexicon with no entries, so only the speech stages change the text."""

    warnings: tuple[str, ...] = ()

    def lookup(self, token: str) -> None:
        return None

    def iupac(self, name: str) -> None:
        return None


def spoken(text: str) -> str:
    q = Question(None, None, None, None, text, (), None, text)
    norm = ScriptNormalizer(NoHardWords())  # type: ignore[arg-type]
    return norm.to_script([q], {}, RenderOptions()).segments[0].text


# --- ranges -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "words"),
    [
        # A tight en dash between two ascending numbers is a range, with or without a unit.
        (f"5{EN_DASH}10 grams", "5 to 10 grams"),
        (f"5{EN_DASH}10%", "5 to 10 percent"),
        (f"2018{EN_DASH}2020", "2018 to 2020"),
        (f"1.5{EN_DASH}2.5 m", "1.5 to 2.5 meters"),
        (f"1,000{EN_DASH}2,000 years", "1,000 to 2,000 years"),
        (f"pages 5{EN_DASH}10", "pages 5 to 10"),
        (f"pH 2{EN_DASH}3", "pH 2 to 3"),
        # The formula stage reads a power of ten first; a tight 10-N left over is a range.
        (f"pH 10{EN_DASH}12", "pH 10 to 12"),
        (f"Questions 10{EN_DASH}12 refer to it.", "Questions 10 to 12 refer to it."),
        (f"10{EN_DASH}15 °C", "10 to 15 degrees Celsius"),
        # Spaced, or with an ASCII hyphen, it takes a range noun or a unit after it.
        (f"5 {EN_DASH} 10 minutes", "5 to 10 minutes"),
        ("W) 15-16 years", "W) 15 to 16 years"),
        ("10-14 days", "10 to 14 days"),
        ("5-10 g", "5 to 10 grams"),
        ("about 200-250 million years", "about 200 to 250 million years"),
        # Scientific notation: a range of magnitudes, not a subtraction.
        (f"10^3{EN_DASH}10^4", "ten cubed to ten to the fourth"),
        (
            f"1×10^3{EN_DASH}5×10^3 Pa",
            "one times ten to the third to five times ten to the third pascals",
        ),
    ],
)
def test_a_range_reads_to(raw, words):
    assert spoken(raw) == words


@pytest.mark.parametrize(
    ("raw", "today"),
    [
        # No range noun or unit: a hyphen stays a hyphen (a pH span, a name, a label).
        ("pH 5-7", "pH 5-7"),
        ("2-methylbutane", "2-methylbutane"),
        ("5-10", "5-10"),
        ("W) 10 - 30", "W) 10 - 30"),
        ("ages 5 - 10", "ages 5 - 10"),
        # A spaced en dash with nothing after it may be a subtraction; a label is no range.
        (f"What is 83 {EN_DASH} 19?", f"What is 83 {EN_DASH} 19?"),
        (f"18 {EN_DASH} 2.049", f"18 {EN_DASH} 2.049"),
        (f"Round 3 {EN_DASH} 10 points", f"Round 3 {EN_DASH} 10 points"),
        # Descending: a flattened exponent (7^-1) or a time span the dash cannot tell.
        (f"7{EN_DASH}1", f"7{EN_DASH}1"),
        (f"open 9am {EN_DASH} 5pm daily", f"open 9am {EN_DASH} 5pm daily"),
        (f"30{EN_DASH}60{EN_DASH}90 triangle", f"30{EN_DASH}60{EN_DASH}90 triangle"),
        # Exponents and subtractions keep the reading they had.
        (f"Kw = 10{EN_DASH}14", "Kw equals ten to the minus fourteen"),
        (f"5 × 10{EN_DASH}4", "five times ten to the minus four"),
        (f"8 {EN_DASH} 3 = 5", "8 minus 3 equals 5"),
        (f"x^2 {EN_DASH} 12", "x squared minus 12"),
        (f"10^4 {EN_DASH} 10^3", "ten to the fourth minus ten cubed"),
    ],
)
def test_what_is_no_range_keeps_its_reading(raw, today):
    assert spoken(raw) == today
