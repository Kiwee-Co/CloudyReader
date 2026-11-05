"""Fractions read as spoken words, never as "slash": the stage alone and the real normalizer."""

import re

import pytest

from cloudyreader import normalize
from cloudyreader.models import Choice, Fmt, Kind, Override, Question, RenderOptions, Respelling
from cloudyreader.normalize import ScriptNormalizer
from cloudyreader.spoken_fractions import fold_glyphs, speak_fractions

MINUS = "−"
EN_DASH = "–"


class NoHardWords:
    """A lexicon with no entries unless given some, so only the speech stages change the text."""

    warnings: tuple[str, ...] = ()

    def __init__(self, words: dict[str, str] | None = None) -> None:
        self.words = words or {}

    def lookup(self, token: str) -> Override | None:
        ipa = self.words.get(token)
        return None if ipa is None else Override(token, ipa, "lexicon")

    def iupac(self, name: str) -> Override | None:
        return None


def stem_segment(text: str, lexicon: NoHardWords | None = None, respellings=()):
    q = Question(None, None, None, None, text, (), None, text, tuple(respellings))
    norm = ScriptNormalizer(lexicon or NoHardWords())  # type: ignore[arg-type]
    return norm.to_script([q], {}, RenderOptions()).segments[0]


def spoken(text: str) -> str:
    """The text the voice gets for a stem, through the real unit, fraction and formula stages."""
    return stem_segment(text).text


OWNER = [
    ("1/7", "one seventh"),
    ("3/9", "three ninths"),
    ("2/51", "two fifty-firsts"),
    ("5/8", "five eighths"),
]
HALVES_AND_QUARTERS = [
    ("1/2", "one half"),
    ("3/2", "three halves"),
    ("0/2", "zero halves"),
    ("1/4", "one quarter"),
    ("3/4", "three quarters"),
    ("9/4", "nine quarters"),
]
ORDINALS = [
    ("22/7", "twenty-two sevenths"),
    ("1/3", "one third"),
    ("2/3", "two thirds"),
    ("0/7", "zero sevenths"),
    ("5/12", "five twelfths"),
    ("1/20", "one twentieth"),
    ("3/21", "three twenty-firsts"),
    ("2/22", "two twenty-seconds"),
    ("42/45", "forty-two forty-fifths"),
    ("1/99", "one ninety-ninth"),
]
POWERS_OF_TEN = [
    ("1/10", "one tenth"),
    ("7/10", "seven tenths"),
    ("1/100", "one hundredth"),
    ("3/100", "three hundredths"),
    ("1/1000", "one thousandth"),
    ("3/1000", "three thousandths"),
]
OVER = [
    ("1/0", "one over zero"),
    ("5/1", "five over one"),
    ("1/101", "one over one hundred one"),
    ("4/105", "four over one hundred five"),
    ("2/500", "two over five hundred"),
    ("1/10000", "one over ten thousand"),
    ("355/113", "three hundred fifty-five over one hundred thirteen"),
]
OTHER_SLASHES = [
    ("1⁄2", "one half"),  # fraction slash, as PDF text has it
    ("3∕4", "three quarters"),  # division slash
]
MIXED = [
    ("2 1/2", "two and one half"),
    ("1 3/4", "one and three quarters"),
    ("2-1/2", "two and one half"),
    ("34 2/7", "thirty-four and two sevenths"),
    ("1 5/12", "one and five twelfths"),
    ("3 1/100", "three and one hundredth"),
    ("2 1/101", "two and one over one hundred one"),
    ("a 3-1/2-inch pipe", "a three and one half-inch pipe"),
    # An improper fraction after a whole number is two numbers.
    ("2 3/2", "2 three halves"),
    ("1 5/5", "1 five fifths"),
]
GLYPHS = [
    ("½", "one half"),
    ("¼", "one quarter"),
    ("¾", "three quarters"),
    ("⅓", "one third"),
    ("⅔", "two thirds"),
    ("⅕", "one fifth"),
    ("⅖", "two fifths"),
    ("⅗", "three fifths"),
    ("⅘", "four fifths"),
    ("⅙", "one sixth"),
    ("⅚", "five sixths"),
    ("⅐", "one seventh"),
    ("⅛", "one eighth"),
    ("⅜", "three eighths"),
    ("⅝", "five eighths"),
    ("⅞", "seven eighths"),
    ("⅑", "one ninth"),
    ("⅒", "one tenth"),
    ("↉", "zero thirds"),
]
GLUED_GLYPHS = [
    ("2½", "two and one half"),
    ("1½ hours", "one and one half hours"),
    ("2⅔ pizzas", "two and two thirds pizzas"),
    ("2 ¾", "two and three quarters"),
    ("x½", "x one half"),
]
SUFFIXES = [
    ("1/7th", "one seventh"),
    ("2/3rds", "two thirds"),
    ("1/10th", "one tenth"),
    ("1/60TH", "one sixtieth"),
    ("4/15ths", "four fifteenths"),
    ("1/2nd", "one half"),
    ("1/4th", "one quarter"),
    ("1 1/3rd", "one and one third"),
    ("1/360th", "one over three hundred sixty"),
]
BOUNDARIES = [
    ("1/2.", "one half."),
    ("(1/2)", "(one half)"),
    ("1/2%", "one half%"),
    ("1/2-inch", "one half-inch"),
    ("1/2,", "one half,"),
    ("[1/2]", "[one half]"),
    ("1/2; 3/4? 5/8:", "one half; three quarters? five eighths:"),
    ("1/4, 1/2, 2, or 4 times", "one quarter, one half, 2, or 4 times"),
]
SPEAK = [
    *OWNER,
    *HALVES_AND_QUARTERS,
    *ORDINALS,
    *POWERS_OF_TEN,
    *OVER,
    *OTHER_SLASHES,
    *MIXED,
    *GLYPHS,
    *GLUED_GLYPHS,
    *SUFFIXES,
    *BOUNDARIES,
]
# A letter, a decimal point, a thousands comma, another slash or a space beside it: not a fraction.
KEPT = [
    "m/s",
    "mol/L",
    "and/or",
    "N/A",
    "t1/2",
    "x/2",
    "1/2x",
    "1/2bh",
    "is1/3",
    "2/3πr",
    "1.5/2",
    "1/2.5",
    "62.8/4",
    "3/9/2024",
    "1/2/3",
    "1,000/3",
    "3/1,000",
    "1/1,800th",
    "3 / 4",
    "3 /4",
    "3/ 4",
    "01/02",
    "1/02",
    "1/" + "9" * 10,
    "1/" + "9" * 5000,  # far past int()'s digit limit: left alone, never a crash
]


@pytest.mark.parametrize(("raw", "words"), OWNER)
def test_the_owner_examples_are_read_as_fractions(raw, words):
    assert speak_fractions(raw) == words
    assert spoken(f"What is {raw} of 49?") == f"What is {words} of 49?"


@pytest.mark.parametrize(("raw", "words"), SPEAK)
def test_speak_fractions(raw, words):
    assert speak_fractions(raw) == words


@pytest.mark.parametrize("raw", KEPT)
def test_a_slash_that_is_no_plain_fraction_stays(raw):
    assert speak_fractions(raw) == raw


def test_a_long_denominator_still_reads_over():
    assert speak_fractions("1/123456789") == (
        "one over one hundred twenty-three million four hundred fifty-six thousand "
        "seven hundred eighty-nine"
    )


@pytest.mark.parametrize(
    ("raw", "folded"),
    [
        ("½", "1/2"),
        ("2½", "2 1/2"),
        ("x½y", "x 1/2 y"),
        ("-½", "-1/2"),
        ("⅟", "⅟"),  # "1/" alone is no fraction
    ],
)
def test_fold_glyphs(raw, folded):
    assert fold_glyphs(raw) == folded


# --- through the real normalizer --------------------------------------------------------------


@pytest.mark.parametrize(("raw", "words"), [*HALVES_AND_QUARTERS, *MIXED, *GLYPHS, *SUFFIXES])
def test_the_normalizer_reads_each_form(raw, words):
    assert spoken(f"It is {raw} here.") == f"It is {words} here."


@pytest.mark.parametrize(
    ("raw", "words"),
    [
        ("-1/2", "minus one half"),
        (f"{EN_DASH}3/7", "minus three sevenths"),
        (f"{MINUS}2 1/2", "minus two and one half"),
        ("-½", "minus one half"),
        ("x = -1/2", "x equals minus one half"),
        ("x < -1/3 or x > 2/5", "x is less than minus one third or x is greater than two fifths"),
    ],
)
def test_a_negative_fraction_says_minus(raw, words):
    assert spoken(raw) == words


@pytest.mark.parametrize("sign", ["-", EN_DASH, MINUS])
@pytest.mark.parametrize("frame", ["ANSWER: {}", "y = {}", "({}, 2)"])
def test_a_sign_reads_as_it_does_on_a_plain_number(sign, frame):
    plain = spoken(frame.format(f"{sign}3"))
    assert spoken(frame.format(f"{sign}3/7")) == plain.replace("3", "three sevenths", 1)


@pytest.mark.parametrize(
    ("raw", "words"),
    [
        ("It is 1/2.", "It is one half."),
        ("a 1/2% rise", "a one half percent rise"),
        ("a 1/2-inch pipe", "a one half-inch pipe"),
        ("66 ½° North", "sixty-six and one half degrees North"),
        ("Is it 1/7 + 3/9?", "Is it one seventh plus three ninths?"),
        ("x^1/2", "x to the power of one half"),
    ],
)
def test_the_normalizer_reads_fractions_in_context(raw, words):
    assert spoken(raw) == words


@pytest.mark.parametrize(
    ("raw", "today"),
    [
        ("A speed of 5 m/s.", "A speed of 5 meters per second."),
        ("A concentration in mol/L.", "A concentration in moles per liter."),
        ("Pick one and/or the other.", "Pick one and/or the other."),
        ("On 3/9/2024 it rained.", "On 3/9/2024 it rained."),
        ("The ratio 1.5/2 holds.", "The ratio 1.5/2 holds."),
        ("What is 3 / 4 of 8?", "What is 3 over 4 of 8?"),
        ("The half-life t1/2 and x/2.", "The half-life t1/2 and x/2."),
    ],
)
def test_the_normalizer_keeps_what_is_no_fraction(raw, today):
    assert spoken(raw) == today


def test_a_whole_question_reads_its_fractions_in_every_part():
    q = Question(
        Kind.TOSS_UP,
        7,
        "MATH",
        Fmt.MULTIPLE_CHOICE,
        "Which is closest to 1/7 + 3/9 when you add 2 1/2 and ¾?",
        (
            Choice("W", "2/51"),
            Choice("X", "5/8 of a mile"),
            Choice("Y", "1 3/4"),
            Choice("Z", "22/7"),
        ),
        "X) 5/8 of a mile",
        "",
    )
    norm = ScriptNormalizer(NoHardWords())  # type: ignore[arg-type]
    script = norm.to_script([q], {}, RenderOptions(read_answer=True))
    letter, choice = normalize.LETTER_PAUSE_MS, normalize.CHOICE_PAUSE_MS

    assert [(s.text, s.pause_after_ms) for s in script.segments] == [
        ("Toss-up number seven.", normalize.HEADER_PAUSE_MS),
        ("Math.", normalize.CATEGORY_PAUSE_MS),
        ("Multiple choice.", normalize.FORMAT_PAUSE_MS),
        (
            "Which is closest to one seventh plus three ninths when you add two and one half "
            "and three quarters?",
            normalize.STEM_PAUSE_MS,
        ),
        ("W.", letter),
        ("two fifty-firsts", choice),
        ("X.", letter),
        ("five eighths of a mile", choice),
        ("Y.", letter),
        ("one and three quarters", choice),
        ("Z.", letter),
        ("twenty-two sevenths", normalize.ANSWER_LEAD_MS),
        ("Answer. X. five eighths of a mile.", 0),
    ]
    assert letter == 300


@pytest.mark.parametrize(
    ("answer", "read"),
    [
        ("25/3 (ACCEPT: 8 1/3)", "Answer. twenty-five thirds."),
        ("W) 1/4", "Answer. W. one quarter."),
        ("1/60TH", "Answer. one sixtieth."),
        (f"{EN_DASH}3/7", "Answer. minus three sevenths."),
    ],
)
def test_the_answer_reads_its_fraction(answer, read):
    q = Question(None, None, None, None, "What is it?", (), answer, "")
    norm = ScriptNormalizer(NoHardWords())  # type: ignore[arg-type]
    script = norm.to_script([q], {}, RenderOptions(read_answer=True))
    assert script.segments[-1].text == read


def test_fraction_words_take_the_lexicon_path():
    segment = stem_segment("Add 1/7 to it.", NoHardWords({"seventh": "ˈsɛvənθ"}))
    assert segment.text == "Add one seventh to it."
    assert segment.overrides == (Override("seventh", "ˈsɛvənθ", "lexicon"),)


def test_a_say_as_guide_still_wins_over_the_fraction_reading():
    guide = Respelling("4 2/7", "4 and two-sevenths", "spoken")
    segment = stem_segment("Convert 4 2/7 to an improper fraction.", respellings=[guide])
    assert segment.text == "Convert 4 and two-sevenths to an improper fraction."


def test_a_fraction_inside_a_say_as_guide_is_read_too():
    # Real round (Sample-Set-8 Round-13-A): the guide's own words hold a fraction.
    guide = Respelling("24x =", "2 to the 4x power equals 1/16", "spoken")
    segment = stem_segment("Solve 24x = for x.", respellings=[guide])
    assert segment.text == "Solve 2 to the 4x power equals one sixteenth for x."


def test_no_fraction_is_ever_read_as_slash():
    """Regression: every voice reads a raw "/" as "slash", so none may reach it."""
    texts = [spoken(f"It is {raw} here.") for raw, _ in SPEAK]
    texts += [spoken(raw) for raw in ("-1/2", f"{EN_DASH}3/7", "2½", "1⁄2 of 3∕4")]
    leaks = [t for t in texts if re.search(r"slash|[/⁄∕]", t, re.IGNORECASE)]
    assert leaks == []
