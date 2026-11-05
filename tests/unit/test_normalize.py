"""Normalizer tests: header convention, pauses, overrides, R2 answer rule, R5 no-substitution."""

import re
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from cloudyreader import normalize, respell
from cloudyreader.models import (
    Choice,
    Fmt,
    Kind,
    Override,
    Question,
    RenderOptions,
    Resolution,
    Respelling,
)
from cloudyreader.normalize import ScriptNormalizer
from cloudyreader.parser import QuestionParser, parse

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "questions"
GOLDEN_DIR = ROOT / "tests" / "golden"
SAMPLES = ROOT / ".data" / "samples"
SPOKEN = yaml.safe_load((GOLDEN_DIR / "spoken_cases.yaml").read_text("utf-8"))["cases"]
PARSED = {
    c["id"]: c
    for c in yaml.safe_load((GOLDEN_DIR / "parse_cases.yaml").read_text("utf-8"))["cases"]
}

NO_RESOLUTIONS: dict[str, Resolution] = {}
DEFAULT = RenderOptions()
READ = RenderOptions(read_answer=True)


class FakeLexicon:
    """Token table with the real Lexicon surface: lookup, iupac, warnings."""

    def __init__(
        self,
        words: dict[str, str] | None = None,
        iupac: dict[str, str] | None = None,
        warnings: tuple[str, ...] = (),
    ) -> None:
        self.words = {k.casefold(): v for k, v in (words or {}).items()}
        self.names = iupac or {}
        self.warnings = warnings
        self.queried: list[str] = []

    def lookup(self, token: str) -> Override | None:
        self.queried.append(token)
        ipa = self.words.get(token.casefold())
        return None if ipa is None else Override(token, ipa, "lexicon")

    def iupac(self, name: str) -> Override | None:
        ipa = self.names.get(name)
        return None if ipa is None else Override(name, ipa, "iupac")


def make(
    lexicon: FakeLexicon | None = None,
    formulas: Callable[[str], str] | None = None,
    units: Callable[[str], str] | None = None,
    to_ipa: Callable[[str], str | None] | None = None,
) -> ScriptNormalizer:
    return ScriptNormalizer(
        lexicon or FakeLexicon(),  # type: ignore[arg-type]
        speak_formulas=formulas or (lambda t: t),
        speak_units=units or (lambda t: t),
        to_ipa=to_ipa or (lambda r: f"<{r}>"),
    )


def question(
    stem: str = "What is it?",
    *,
    kind: Kind | None = None,
    number: int | None = None,
    category: str | None = None,
    fmt: Fmt | None = None,
    choices: tuple[Choice, ...] = (),
    answer: str | None = None,
    respellings: tuple[Respelling, ...] = (),
) -> Question:
    return Question(kind, number, category, fmt, stem, choices, answer, "", respellings)


def abcd(*texts: str) -> tuple[Choice, ...]:
    return tuple(Choice(letter, t) for letter, t in zip("WXYZ", texts, strict=True))  # type: ignore[arg-type]


def script(*questions: Question, norm: ScriptNormalizer | None = None, opts=DEFAULT, res=None):
    return (norm or make()).to_script(questions, res or NO_RESOLUTIONS, opts)


def texts(s) -> list[str]:
    return [seg.text for seg in s.segments]


def pauses(s) -> list[int]:
    return [seg.pause_after_ms for seg in s.segments]


# --- header convention -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "number", "category", "fmt", "expected"),
    [
        (
            Kind.TOSS_UP,
            2,
            "EARTH SCIENCE",
            Fmt.MULTIPLE_CHOICE,
            ["Toss-up number two.", "Earth Science.", "Multiple choice."],
        ),
        (
            Kind.BONUS,
            23,
            "BIOLOGY",
            Fmt.SHORT_ANSWER,
            ["Bonus number twenty-three.", "Biology.", "Short answer."],
        ),
        (Kind.TOSS_UP, None, "MATH", None, ["Toss-up.", "Math."]),
        (Kind.BONUS, None, None, None, ["Bonus."]),
        (None, 3, None, None, ["Question number three."]),
        (
            None,
            3,
            "ENERGY",
            Fmt.SHORT_ANSWER,
            ["Question number three.", "Energy.", "Short answer."],
        ),
        (None, None, "PHYSICS", Fmt.SHORT_ANSWER, ["Physics.", "Short answer."]),
        (None, None, None, Fmt.MULTIPLE_CHOICE, ["Multiple choice."]),
        (None, None, None, None, []),
        (None, 0, None, None, ["Question number zero."]),
    ],
)
def test_header_segments(kind, number, category, fmt, expected):
    s = script(question(kind=kind, number=number, category=category, fmt=fmt))
    assert texts(s)[:-1] == expected
    assert texts(s)[-1] == "What is it?"


def test_header_pauses():
    q = question(kind=Kind.TOSS_UP, number=2, category="EARTH SCIENCE", fmt=Fmt.MULTIPLE_CHOICE)
    s = script(q)
    assert pauses(s) == [400, 300, 500, 0]


@pytest.mark.parametrize(
    ("category", "spoken"),
    [
        ("EARTH AND SPACE SCIENCE", "Earth and Space Science."),
        ("LIFE SCIENCE", "Life Science."),
        ("Earth Science", "Earth Science."),
        ("ARTS & SCIENCES", "Arts and Sciences."),
        ("OPTICS OF THE EYE", "Optics of the Eye."),
    ],
)
def test_category_is_title_cased(category, spoken):
    assert texts(script(question(category=category)))[0] == spoken


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (1, "one"),
        (11, "eleven"),
        (20, "twenty"),
        (21, "twenty-one"),
        (99, "ninety-nine"),
        (100, "one hundred"),
        (101, "one hundred one"),
        (342, "three hundred forty-two"),
        (1000, "one thousand"),
        (2025, "two thousand twenty-five"),
        (12000, "twelve thousand"),
    ],
)
def test_number_words(n, words):
    assert texts(script(question(kind=Kind.BONUS, number=n)))[0] == f"Bonus number {words}."


# --- brief examples: segments, pauses, choices -----------------------------------------------


def test_brief_example_multiple_choice():
    q = question(
        "The source of energy is:",
        kind=Kind.TOSS_UP,
        number=2,
        category="EARTH SCIENCE",
        fmt=Fmt.MULTIPLE_CHOICE,
        choices=abcd("tidal motion", "the Earth’s rotation", "convection", "remnant magnetism"),
    )
    s = script(q)
    assert texts(s) == [
        "Toss-up number two.",
        "Earth Science.",
        "Multiple choice.",
        "The source of energy is:",
        "W.",
        "tidal motion",
        "X.",
        "the Earth’s rotation",
        "Y.",
        "convection",
        "Z.",
        "remnant magnetism",
    ]
    assert pauses(s) == [400, 300, 500, 700, 300, 400, 300, 400, 300, 400, 300, 400]
    assert s.text() == " ".join(texts(s))
    assert s.text().endswith(
        "is: W. tidal motion X. the Earth’s rotation Y. convection Z. remnant magnetism"
    )


def test_short_answer_has_no_choice_segments_and_no_stem_pause():
    s = script(question("Name it.", fmt=Fmt.SHORT_ANSWER))
    assert texts(s) == ["Short answer.", "Name it."]
    assert pauses(s) == [500, 0]


def test_markers_are_always_dot_style():
    s = script(question("Pick.", choices=abcd("a", "b", "c", "d")))
    assert texts(s)[1::2] == ["W.", "X.", "Y.", "Z."]


def test_no_questions_gives_empty_script():
    s = script()
    assert (s.segments, s.warnings, s.text()) == ((), (), "")


# --- choice letters: own segment, exact pause in every engine ---------------------------------

CHOICES = ["W.", "a", "X.", "b", "Y.", "c", "Z.", "d"]
CHOICE_PAUSES = [300, 400] * 4


def test_pause_values():
    paused = (normalize.STEM_PAUSE_MS, normalize.LETTER_PAUSE_MS, normalize.CHOICE_PAUSE_MS)
    assert paused == (700, 300, 400)


def test_each_choice_is_its_letter_then_its_text():
    s = script(question("Pick.", choices=abcd("tides", "convection", "rotation", "dust")))
    assert texts(s) == ["Pick.", "W.", "tides", "X.", "convection", "Y.", "rotation", "Z.", "dust"]
    assert pauses(s) == [700, *CHOICE_PAUSES]
    assert s.text() == "Pick. W. tides X. convection Y. rotation Z. dust"


def test_choice_overrides_stay_on_the_text_segment():
    lex = FakeLexicon({"larynx": "LEX"})
    q = question(
        "Pick.",
        choices=(
            Choice("W", "Pharynx", (Respelling("Pharynx", "FAR-ingks"),)),
            Choice("X", "Larynx"),
            Choice("Y", "c"),
            Choice("Z", "d"),
        ),
    )
    s = script(q, norm=make(lex))
    assert [(seg.text, seg.pause_after_ms, seg.overrides) for seg in s.segments[1:5]] == [
        ("W.", 300, ()),
        ("Pharynx", 400, (Override("Pharynx", "<FAR-ingks>", "respelling"),)),
        ("X.", 300, ()),
        ("Larynx", 400, (Override("Larynx", "LEX", "lexicon"),)),
    ]


@pytest.mark.parametrize("empty", ["", "[2]"], ids=["blank", "footnote-only"])
def test_a_choice_without_text_is_its_letter_with_the_choice_pause(empty):
    s = script(question("Pick.", choices=abcd("a", empty, "c", "d")))
    assert texts(s) == ["Pick.", "W.", "a", "X.", "Y.", "c", "Z.", "d"]
    assert pauses(s) == [700, 300, 400, 400, 300, 400, 300, 400]


def test_letter_pauses_with_several_questions_in_one_paste():
    mc = question("One?", choices=abcd("a", "b", "c", "d"))
    sa = question("Two?", fmt=Fmt.SHORT_ANSWER)
    s = script(mc, sa, mc)
    assert texts(s) == ["One?", *CHOICES, "Short answer.", "Two?", "One?", *CHOICES]
    assert pauses(s) == [700, *CHOICE_PAUSES[:-1], 1500, 500, 1500, 700, *CHOICE_PAUSES]


def test_the_answer_lead_follows_the_last_choice_text():
    q = question("Which?", choices=abcd("a", "b", "c", "d"), answer="Y) ESOPHAGUS")
    s = script(q, opts=READ)
    assert texts(s)[-3:] == ["Z.", "d", "Answer. Y. Esophagus."]
    assert pauses(s)[-3:] == [300, 5000, 0]


# --- several questions -----------------------------------------------------------------------


def test_gap_between_questions_is_on_the_last_segment():
    a = question("One?", kind=Kind.TOSS_UP, number=1)
    b = question("Two?", choices=abcd("a", "b", "c", "d"))
    c = question("Three?", kind=Kind.BONUS, number=3)
    s = script(a, b, c)
    assert texts(s)[:2] == ["Toss-up number one.", "One?"]
    assert pauses(s) == [400, 1500, 700, *CHOICE_PAUSES[:-1], 1500, 400, 0]
    assert texts(s)[-1] == "Three?"


def test_questions_keep_reading_order():
    s = script(question("First?"), question("Second?"), question("Third?"))
    assert texts(s) == ["First?", "Second?", "Third?"]


# --- R2: the answer ---------------------------------------------------------------------------


def test_answer_is_never_spoken_by_default():
    q = question("Which?", choices=abcd("a", "b", "c", "d"), answer="Y) ESOPHAGUS")
    s = script(q)
    assert "sophagus" not in s.text().lower()
    assert "answer" not in s.text().lower()


def test_answer_is_spoken_with_read_answer():
    q = question("Which?", choices=abcd("a", "b", "c", "d"), answer="Y) ESOPHAGUS")
    s = script(q, opts=READ)
    assert texts(s)[-1] == "Answer. Y. Esophagus."
    assert pauses(s)[-2:] == [5000, 0]


def test_answer_gap_before_the_next_question():
    a = question("One?", answer="LIGASE")
    b = question("Two?")
    s = script(a, b, opts=READ)
    assert texts(s) == ["One?", "Answer. Ligase.", "Two?"]
    assert pauses(s) == [5000, 1500, 0]


@pytest.mark.parametrize(
    ("answer", "spoken"),
    [
        ("ESOPHAGUS", "Answer. Esophagus."),
        ("X: 7", "Answer. X. 7."),
        ("Y. MITOCHONDRION", "Answer. Y. Mitochondrion."),
        ("Y)Velocity", "Answer. Y. Velocity."),
        ("w) igneous", "Answer. W. igneous."),
        ("y) Igneous", "Answer. Y. Igneous."),
        ("LIGASE ACCEPT: ENZYME", "Answer. Ligase."),
        ("LIGASE ACCEPT: ENZYME DO NOT ACCEPT: POLYMERASE", "Answer. Ligase."),
        ("ESOPHAGUS (ACCEPT: GULLET)", "Answer. Esophagus."),
        ("2 (Solution: 52 plus 122 equals c2; c equals 13)", "Answer. 2."),
        ("18 OHMS (must give units)", "Answer. 18 Ohms."),
        ("–6, 12 (must give both answers)", "Answer. –6, 12."),
        ("ELLIPSE (ALSO ACCEPT ELLIPTICAL)", "Answer. Ellipse."),
        ("VENUS (Also accept Uranus)", "Answer. Venus."),
        ("MUSTARD", "Answer. Mustard."),
        ("12.5 Grams/Milliliter (Accept 12.5 Grams/CM3)", "Answer. 12.5 Grams/Milliliter."),
        ("5 (accept 2)", "Answer. 5."),
        ("9 (Accept “9 to 1,” “9:1,” or “9 over 1”)", "Answer. 9."),
        ("Students (Note: Students Must Give Both Terms)", "Answer. Students."),
        ("X (note: if student interrupts,", "Answer. X."),
        ("PHOTON (NOTE: ANY VARIABLE IS FINE)", "Answer. Photon."),
        ("MATRIX (SOLUTION: none) (ACCEPT: X)", "Answer. Matrix."),
        ("SOLUTION", "Answer. Solution."),
        ("ACCEPTOR", "Answer. Acceptor."),
        ("PROMPT RADIATION", "Answer. Prompt Radiation."),
        ("NOTE", "Answer. Note."),
        ("NOTES (MUSICAL)", "Answer. Notes (Musical)."),
        ("Y) ESOPHAGUS (do not accept: gullet)", "Answer. Y. Esophagus."),
        ("ACCEPTANCE", "Answer. Acceptance."),
        ("6 NEWTONS", "Answer. 6 Newtons."),
        ("Is it done?", "Answer. Is it done?"),
        ("0.42", "Answer. 0.42."),
    ],
)
def test_answer_text(answer, spoken):
    assert texts(script(question("Q?", answer=answer), opts=READ))[-1] == spoken


def test_answer_guide_is_applied_not_spoken():
    s = script(question("Q?", answer="TROPONIN [TROH-puh-nin]"), opts=READ)
    assert texts(s)[-1] == "Answer. Troponin."
    assert s.segments[-1].overrides == (Override("Troponin", "<TROH-puh-nin>", "respelling"),)
    mixed = script(question("Q?", answer="Troponin [TROH-puh-nin]"), opts=READ)
    assert mixed.segments[-1].overrides == (Override("Troponin", "<TROH-puh-nin>", "respelling"),)


def test_answer_all_caps_words_left_by_the_formula_stage_stay_unchanged():
    spelled = make(formulas=lambda t: t.replace("DNA", "D N A"))
    s = script(question("Q?", answer="DNA LIGASE"), norm=spelled, opts=READ)
    assert texts(s)[-1] == "Answer. D N A Ligase."


def test_answer_that_is_only_a_note_adds_nothing():
    s = script(question("Q?", answer="ACCEPT: LIGASE"), opts=READ)
    assert texts(s) == ["Q?"]
    assert pauses(s) == [0]


def test_missing_answer_adds_nothing_with_read_answer():
    assert texts(script(question("Q?", answer=None), opts=READ)) == ["Q?"]


# --- stage order: formulas, units, brackets --------------------------------------------------


def test_units_then_formulas_on_stem_choices_and_answer():
    calls: list[str] = []

    def formulas(text: str) -> str:
        calls.append(f"f:{text}")
        return text.upper()

    def units(text: str) -> str:
        calls.append(f"u:{text}")
        return text + "!"

    q = question("stem", choices=abcd("a", "b", "c", "d"), answer="ans")
    s = script(q, norm=make(formulas=formulas, units=units), opts=READ)
    assert calls[:2] == ["u:stem", "f:stem!"]
    assert texts(s)[0] == "STEM!"
    assert texts(s)[1:3] == ["W.", "A!"]  # the letter skips the stages
    assert len(calls) == 2 * 6


def test_footnote_markers_are_dropped_before_the_formula_stage():
    seen: list[str] = []
    norm = make(formulas=lambda t: seen.append(t) or t)
    s = script(
        question("[4] The Great Barrier Reef [1] is large.[2] See word[3] and [H+]."), norm=norm
    )
    assert seen[0] == "The Great Barrier Reef is large. See word and [H+]."
    assert "[" not in s.text()
    assert "]" not in s.text()


def test_bracketed_integer_in_math_is_left_for_the_formula_stage():
    seen: list[str] = []
    norm = make(formulas=lambda t: seen.append(t) or t)
    script(question("Then rate = k[1]^2 holds."), norm=norm)
    assert seen[0] == "Then rate = k[1]^2 holds."


def test_leftover_brackets_never_reach_the_engine():
    s = script(question("The interval [0, 1] and [NaCl] and ]x[ hold."))
    assert "[" not in s.text() and "]" not in s.text()
    assert s.text() == "The interval 0, 1 and NaCl and x hold."


def test_whitespace_is_normalized_in_the_output():
    s = script(question("a   b\t c"), norm=make(formulas=lambda t: t.replace("b", "  b  ")))
    assert s.text() == "a b c"


# --- respelling overrides ---------------------------------------------------------------------


def test_stem_and_choice_respellings_become_overrides_on_their_segments():
    q = question(
        "The Okazaki fragments join.",
        respellings=(Respelling("Okazaki", "oh-kuh-ZAH-kee"),),
        choices=(
            Choice("W", "Pharynx", (Respelling("Pharynx", "FAR-ingks"),)),
            Choice("X", "Larynx"),
            Choice("Y", "Esophagus", (Respelling("Esophagus", "i-SOF-uh-guhs"),)),
            Choice("Z", "Trachea"),
        ),
    )
    s = script(q)
    by_text = {seg.text: seg.overrides for seg in s.segments}
    assert by_text["The Okazaki fragments join."] == (
        Override("Okazaki", "<oh-kuh-ZAH-kee>", "respelling"),
    )
    assert by_text["Pharynx"] == (Override("Pharynx", "<FAR-ingks>", "respelling"),)
    assert by_text["Larynx"] == ()
    assert by_text["Esophagus"] == (Override("Esophagus", "<i-SOF-uh-guhs>", "respelling"),)
    assert by_text["W."] == by_text["X."] == by_text["Y."] == by_text["Z."] == ()
    assert s.warnings == ()
    assert "FAR" not in s.text()


def test_multi_word_respelling_is_one_override():
    q = question(
        "In the Krebs cycle runs.", respellings=(Respelling("Krebs cycle", "KREBZ SY-kul"),)
    )
    ov = script(q).segments[0].overrides
    assert ov == (Override("Krebs cycle", "<KREBZ SY-kul>", "respelling"),)


def test_real_respell_module_is_the_default_converter():
    q = question(
        "x",
        choices=(
            Choice("W", "Pharynx", (Respelling("Pharynx", "FAR-ingks"),)),
            Choice("X", "b"),
            Choice("Y", "c"),
            Choice("Z", "d"),
        ),
    )
    norm = ScriptNormalizer(FakeLexicon(), speak_formulas=lambda t: t, speak_units=lambda t: t)  # type: ignore[arg-type]
    (ov,) = norm.to_script([q], NO_RESOLUTIONS, DEFAULT).segments[2].overrides
    assert ov.ipa == respell.to_ipa("FAR-ingks")


def test_unconvertible_respelling_speaks_the_word_plain_and_warns():
    q = question("The Pharynx here.", respellings=(Respelling("Pharynx", "???"),))
    s = script(q, norm=make(to_ipa=lambda r: None))
    assert s.segments[0].overrides == ()
    assert s.segments[0].text == "The Pharynx here."
    assert len(s.warnings) == 1
    assert "Pharynx" in s.warnings[0] and "???" in s.warnings[0]


def test_respelling_surface_absent_from_the_text_warns():
    q = question("The throat here.", respellings=(Respelling("Pharynx", "FAR-ingks"),))
    s = script(q)
    assert s.segments[0].overrides == ()
    assert len(s.warnings) == 1 and "Pharynx" in s.warnings[0]


def test_phonetic_surface_is_shielded_from_every_later_stage():
    norm = make(formulas=lambda t: t.replace("Pharynx", "throat"), units=str.upper)
    q = question("The Pharynx here.", respellings=(Respelling("Pharynx", "FAR-ingks"),))
    seg = script(q, norm=norm).segments[0]
    assert seg.text == "THE Pharynx HERE."
    assert seg.overrides == (Override("Pharynx", "<FAR-ingks>", "respelling"),)


SPELL_KIN10 = {"formulas": lambda t: t.replace("KIN10", "K I N ten")}


def test_phonetic_surface_is_not_spelled_as_an_acronym():
    q = question("The KIN10 gene.", respellings=(Respelling("KIN10", "kin-ten"),))
    seg = script(q, norm=make(**SPELL_KIN10)).segments[0]
    assert seg.text == "The KIN10 gene."
    assert seg.overrides == (Override("KIN10", "<kin-ten>", "respelling"),)


def test_phonetic_surface_without_ipa_gets_the_normal_stages():
    q = question("The KIN10 gene.", respellings=(Respelling("KIN10", "kin-ten"),))
    s = script(q, norm=make(to_ipa=lambda r: None, **SPELL_KIN10))
    assert s.segments[0].text == "The K I N ten gene."
    assert len(s.warnings) == 1 and "KIN10" in s.warnings[0]


def test_longer_surface_wins_over_a_word_inside_it():
    q = question(
        "The Krebs cycle and the cell cycle.",
        respellings=(Respelling("cycle", "SY-kul"), Respelling("Krebs cycle", "KREBZ SY-kul")),
    )
    seg = script(q).segments[0]
    assert seg.text == "The Krebs cycle and the cell cycle."
    assert seg.overrides == (
        Override("cycle", "<SY-kul>", "respelling"),
        Override("Krebs cycle", "<KREBZ SY-kul>", "respelling"),
    )


def test_duplicate_warnings_are_reported_once():
    qs = [question("A Pharynx.", respellings=(Respelling("Pharynx", "???"),))] * 3
    s = make(to_ipa=lambda r: None).to_script(qs, NO_RESOLUTIONS, DEFAULT)
    assert len(s.warnings) == 1


def test_alternative_pronunciation_is_the_converters_business():
    seen: list[str] = []
    q = question("Pecan nut.", respellings=(Respelling("Pecan", "pi-KAHN or PEE-kan"),))
    script(q, norm=make(to_ipa=lambda r: seen.append(r) or "x"))
    assert seen == ["pi-KAHN or PEE-kan"]


# --- guide kinds: phonetic, spoken, spell -----------------------------------------------------


def say_as(surface: str, words: str, kind: str = "spoken") -> Respelling:
    return Respelling(surface, words, kind)  # type: ignore[arg-type]


def test_spoken_guide_replaces_only_the_occurrence_it_followed():
    q = question("Find g(1) when g(a) = 3a. What is g(1)?", respellings=(say_as("g(1)", "g of 1"),))
    seg = script(q).segments[0]
    assert seg.text == "Find g of 1 when g(a) = 3a. What is g(1)?"
    assert seg.overrides == ()


@pytest.mark.parametrize(
    ("stem", "guide", "spoken"),
    [
        ("Add 4 2/7 to 1.", say_as("4 2/7", "4 and two-sevenths"), "Add 4 and two-sevenths to 1."),
        ("A → B runs.", say_as("→", "yields"), "A yields B runs."),
        (
            "So (–10, 5] holds.",
            say_as("(–10, 5]", "open parenthesis"),
            "So open parenthesis holds.",
        ),
    ],
)
def test_spoken_guide_forms(stem, guide, spoken):
    assert script(question(stem, respellings=(guide,))).segments[0].text == spoken


def test_say_as_words_skip_the_formula_and_unit_stages():
    shout = make(formulas=str.upper)
    q = question("Find g(1) now.", respellings=(say_as("g(1)", "g of 1"),))
    assert script(q, norm=shout).segments[0].text == "FIND g of 1 NOW."


@pytest.mark.parametrize(
    ("surface", "content", "spoken"),
    [
        ("FAD", "F.A.D.", "F A D"),
        ("[He]2s1", "H-E-2-S-1", "H E two S one"),
        ("AuNPs", "A. U. N. P’s", "A U N P’s"),
        ("H2S", "H-2-S", "H two S"),
        ("2s22p6", "H-E-2-S-22-P-6", "H E two S twenty-two P six"),
    ],
)
def test_spell_guide_replaces_the_surface_with_its_letters(surface, content, spoken):
    q = question(f"The {surface} here.", respellings=(say_as(surface, content, "spell"),))
    seg = script(q).segments[0]
    assert seg.text == f"The {spoken} here."
    assert seg.overrides == ()


WORDS_Y = "y equals open x2 parenthesis 24 x minus 36 close parenthesis over x squared"


@pytest.mark.parametrize(
    ("stem", "guides", "spoken"),
    [
        pytest.param(
            "Consider the equation: y =. When y = 3, find x.",
            (say_as("y =", WORDS_Y),),
            f"Consider the equation: {WORDS_Y}. When y = 3, find x.",
            id="corpus-y-equals-keeps-the-condition",
        ),
        pytest.param(
            "g(1) now and g(1) later",
            (say_as("g(1)", "g of 1"),),
            "g of 1 now and g(1) later",
            id="one-guide-one-occurrence",
        ),
        pytest.param(
            "g(1) now and g(1) later",
            (say_as("g(1)", "g of 1"), say_as("g(1)", "g of 1")),
            "g of 1 now and g of 1 later",
            id="same-guide-printed-twice-takes-both",
        ),
        pytest.param(
            "x then x",
            (say_as("x", "ex"), say_as("x", "why")),
            "ex then why",
            id="two-guides-take-the-occurrences-in-order",
        ),
        pytest.param(
            "genotypes DD and Dd, so the Dd genotype",
            (
                say_as("DD", "big D big D"),
                say_as("Dd", "big D little d"),
                say_as("Dd", "big D little d"),
            ),
            "genotypes big D big D and big D little d, so the big D little d genotype",
            id="corpus-genotypes",
        ),
        pytest.param(
            "x and xx and x",
            (say_as("x", "ex"),),
            "ex and xx and x",
            id="longer-word-is-not-an-occurrence",
        ),
    ],
)
def test_a_say_as_guide_replaces_one_occurrence(stem, guides, spoken):
    s = script(question(stem, respellings=guides))
    assert s.segments[0].text == spoken
    assert s.warnings == ()


def test_the_exact_corpus_input_keeps_the_condition_with_the_real_stages(real_normalizer):
    q = question(
        "Consider the following equation: y =. When y = 3, what are the possible values for x?",
        kind=Kind.BONUS,
        number=4,
        category="MATH",
        fmt=Fmt.SHORT_ANSWER,
        respellings=(say_as("y =", WORDS_Y),),
    )
    s = real_normalizer.to_script([q], NO_RESOLUTIONS, DEFAULT)
    assert texts(s)[-1] == (
        f"Consider the following equation: {WORDS_Y}. "
        "When y equals 3, what are the possible values for x?"
    )


def test_the_exact_corpus_paste_keeps_the_condition_end_to_end(real_normalizer):
    raw = (
        "BONUS\n4) MATH Short Answer Consider the following equation: y = [y equals open x2 "
        "parenthesis 24 x minus 36 close parenthesis over x squared]. When y = 3, what are the "
        "possible values for x?\n\nANSWER: 6 AND 2\n"
    )
    s = real_normalizer.to_script(parse(raw), NO_RESOLUTIONS, DEFAULT)
    assert texts(s)[-1].endswith(f"{WORDS_Y}. When y equals 3, what are the possible values for x?")
    assert texts(s)[-1].count("open x2") == 1


def test_a_phonetic_guide_covers_every_occurrence_and_a_repeat_adds_nothing():
    guide = Respelling("Pharynx", "FAR-ingks")
    s = script(question("The Pharynx and the Pharynx.", respellings=(guide, guide)))
    assert s.segments[0].text == "The Pharynx and the Pharynx."
    assert s.segments[0].overrides == (Override("Pharynx", "<FAR-ingks>", "respelling"),)
    assert s.warnings == ()


def test_say_as_guide_whose_surface_is_gone_warns_and_leaves_the_text():
    s = script(question("Nothing here.", respellings=(say_as("g(1)", "g of 1"),)))
    assert s.segments[0].text == "Nothing here."
    assert len(s.warnings) == 1 and "g(1)" in s.warnings[0]


@pytest.mark.parametrize("kind", ["spoken", "spell"])
def test_say_as_guide_without_words_warns_and_leaves_the_text(kind):
    s = script(question("The x here.", respellings=(say_as("x", "[] .", kind),)))
    assert s.segments[0].text == "The x here."
    assert len(s.warnings) == 1 and "no words" in s.warnings[0]


def test_say_as_surface_inside_a_longer_word_is_not_replaced():
    s = script(question("The xray and x.", respellings=(say_as("x", "ex"),)))
    assert s.segments[0].text == "The xray and ex."


def test_say_as_words_never_carry_brackets():
    q = question("Take x here.", respellings=(say_as("x", "see [H+](aq) now"),))
    text = script(q).segments[0].text
    assert "](" not in text and "[" not in text and "]" not in text


def test_guides_of_every_kind_on_choices():
    q = question(
        "Pick.",
        choices=(
            Choice("W", "FAD", (say_as("FAD", "F.A.D.", "spell"),)),
            Choice("X", "g(1)", (say_as("g(1)", "g of 1"),)),
            Choice("Y", "Pharynx", (Respelling("Pharynx", "FAR-ingks"),)),
            Choice("Z", "d"),
        ),
    )
    s = script(q)
    assert texts(s)[1:] == ["W.", "F A D", "X.", "g of 1", "Y.", "Pharynx", "Z.", "d"]
    assert all(seg.overrides == () for seg in s.segments[1::2])  # letters carry none
    assert s.segments[2].overrides == s.segments[4].overrides == ()
    assert s.segments[6].overrides == (Override("Pharynx", "<FAR-ingks>", "respelling"),)


def test_a_phonetic_guide_next_to_a_say_as_guide_keeps_both_working():
    q = question(
        "The Pharynx and g(1) run.",
        respellings=(Respelling("Pharynx", "FAR-ingks"), say_as("g(1)", "g of 1")),
    )
    seg = script(q).segments[0]
    assert seg.text == "The Pharynx and g of 1 run."
    assert seg.overrides == (Override("Pharynx", "<FAR-ingks>", "respelling"),)


def test_answer_with_a_spell_guide_is_read_as_letters():
    s = script(question("Q?", answer="FAD [F.A.D.]"), opts=READ)
    assert texts(s)[-1] == "Answer. F A D."


@pytest.mark.parametrize(
    ("answer", "spoken"),
    [
        ("3 [NOTE: STUDENTS MUST GIVE BOTH ANSWERS]", "Answer. 3."),
        ("MERCURY [must give both answers]", "Answer. Mercury."),
        ("X) FOO [Note: see rules] (ACCEPT: BAR)", "Answer. X. Foo."),
    ],
)
def test_moderator_notes_in_an_answer_are_never_spoken(answer, spoken):
    assert texts(script(question("Q?", answer=answer), opts=READ))[-1] == spoken


# --- Override contract: whole-word surface, no pause punctuation ------------------------------


def whole_word(surface: str, text: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(surface) + r"(?!\w)", text) is not None


def contract_problems(spoken_script) -> list[str]:
    problems = []
    for seg in spoken_script.segments:
        if re.search(r"[\[\]]", seg.text):
            problems.append(f"bracket in {seg.text!r}")
        for ov in seg.overrides:
            if not whole_word(ov.surface, seg.text):
                problems.append(f"{ov.surface!r} is not a whole word of {seg.text!r}")
            if re.search(r"[.;:,!?—…\"()“”\[\]{}]", ov.ipa):
                problems.append(f"punctuation in the IPA of {ov.surface!r}: {ov.ipa!r}")
    return problems


def test_respelling_surface_must_be_a_whole_word():
    q = question("Many Pharynxes here.", respellings=(Respelling("Pharynx", "FAR-ingks"),))
    s = script(q)
    assert s.segments[0].overrides == ()
    assert len(s.warnings) == 1 and "Pharynx" in s.warnings[0]


def test_lexicon_words_touching_digits_or_letters_are_not_overrides():
    lex = FakeLexicon({"mol": "mɑl"})
    s = script(question("About mol2 and 3mol and mol."), norm=make(lex))
    assert s.segments[0].overrides == (Override("mol", "mɑl", "lexicon"),)
    assert lex.queried.count("mol") == 1


def test_ipa_with_pause_punctuation_is_dropped_with_a_warning():
    q = question(
        "The Pharynx and joule and ethanol.", respellings=(Respelling("Pharynx", "FAR-ingks"),)
    )
    lex = FakeLexicon({"joule": "dʒ,ul"}, iupac={"ethanol": "ɛθ;ɑl"})
    s = script(q, norm=make(lex, to_ipa=lambda r: "fa.rɪŋks"), res=iupac_res("ethanol"))
    assert s.segments[0].overrides == ()
    assert len(s.warnings) == 3
    assert all("punctuation" in w for w in s.warnings)


@pytest.mark.parametrize("case", SPOKEN, ids=[c["id"] for c in SPOKEN])
def test_overrides_hold_the_contract_in_every_golden_case(case, real_normalizer):
    fixture = case.get("fixture", case["id"])
    questions = parse((FIXTURES / f"{fixture}.txt").read_bytes().decode("utf-8"))
    opts = RenderOptions(**case.get("options", {}))
    assert contract_problems(real_normalizer.to_script(questions, NO_RESOLUTIONS, opts)) == []


@pytest.mark.slow
@pytest.mark.skipif(
    not (SAMPLES.is_dir() and any(SAMPLES.rglob("*.txt"))), reason=f"no corpus at {SAMPLES}"
)
def test_overrides_hold_the_contract_on_the_real_corpus(real_normalizer):
    parser = QuestionParser()
    problems = []
    for path in sorted(SAMPLES.rglob("*.txt")):
        for q in parser.parse(path.read_text("utf-8", errors="replace")):
            found = contract_problems(real_normalizer.to_script([q], NO_RESOLUTIONS, READ))
            problems += [f"{path.name} #{q.number}: {p}" for p in found]
    assert problems == [], f"{len(problems)} problems, first: {problems[:5]}"


@pytest.mark.parametrize("word", ["lead", "iron", "water", "glucose", "sodium", "salt"])
def test_opsin_ok_for_a_plain_word_changes_nothing(word):
    norm = ScriptNormalizer()
    q = question(f"Which is {word}?")
    res = {word: Resolution(word, "iupac", None, {}, "opsin", "ok")}
    assert norm.to_script([q], res, DEFAULT) == norm.to_script([q], NO_RESOLUTIONS, DEFAULT)


def test_real_lexicon_builds_an_iupac_override_and_keeps_the_text():
    name = "2-methylpropan-1-ol"
    q = question(f"Which is {name}?")
    s = ScriptNormalizer().to_script([q], iupac_res(name), DEFAULT)
    assert s.segments[0].text == f"Which is {name}?"
    assert [(o.surface, o.source) for o in s.segments[0].overrides] == [(name, "iupac")]
    assert contract_problems(s) == []


# --- acronyms and gene symbols are spelled by the formula stage -------------------------------


def test_real_stages_spell_acronyms_in_stem_choices_and_answer():
    q = question(
        "Does DNA bind p53?", choices=abcd("ATP", "BRCA1", "NOT", "NASA"), answer="DNA LIGASE"
    )
    s = ScriptNormalizer().to_script([q], NO_RESOLUTIONS, READ)
    assert texts(s) == [
        "Does D N A bind p fifty-three?",
        "W.",
        "A T P",
        "X.",
        "B R C A one",
        "Y.",
        "NOT",
        "Z.",
        "NASA",
        "Answer. D N A Ligase.",
    ]


# --- lexicon overrides ------------------------------------------------------------------------


def test_lexicon_hit_becomes_an_override_with_the_text_unchanged():
    lex = FakeLexicon({"joule": "ˈdʒul", "Avogadro": "ˌɑvoʊˈɡɑdɹoʊ"})
    q = question("The joule and Avogadro’s number, the Joule again.")
    s = script(q, norm=make(lex))
    assert s.segments[0].text == "The joule and Avogadro’s number, the Joule again."
    assert set(s.segments[0].overrides) == {
        Override("joule", "ˈdʒul", "lexicon"),
        Override("Joule", "ˈdʒul", "lexicon"),
        Override("Avogadro", "ˌɑvoʊˈɡɑdɹoʊ", "lexicon"),
    }


def test_lexicon_is_asked_once_per_distinct_word_and_skips_one_letter_words():
    lex = FakeLexicon()
    script(question("A cat and a cat sat on x."), norm=make(lex))
    assert sorted(lex.queried) == ["and", "cat", "on", "sat"]


def test_lexicon_hits_inside_hyphenated_words():
    lex = FakeLexicon({"boltzmann": "ˈboʊltsmɑn"})
    s = script(question("The Stefan-Boltzmann law."), norm=make(lex))
    assert s.segments[0].overrides == (Override("Boltzmann", "ˈboʊltsmɑn", "lexicon"),)


def test_respelling_wins_over_the_lexicon_for_the_same_word():
    lex = FakeLexicon({"pharynx": "LEX", "larynx": "LEX2"})
    q = question("Pharynx and larynx.", respellings=(Respelling("Pharynx", "FAR-ingks"),))
    s = script(q, norm=make(lex))
    assert set(s.segments[0].overrides) == {
        Override("Pharynx", "<FAR-ingks>", "respelling"),
        Override("larynx", "LEX2", "lexicon"),
    }
    assert "Pharynx" not in lex.queried


def test_words_inside_a_respelled_phrase_are_not_looked_up():
    lex = FakeLexicon({"cycle": "LEX", "krebs": "LEX"})
    q = question("The Krebs cycle runs.", respellings=(Respelling("Krebs cycle", "KREBZ SY-kul"),))
    s = script(q, norm=make(lex))
    assert [o.source for o in s.segments[0].overrides] == ["respelling"]


def test_lexicon_warnings_ride_on_the_script():
    s = script(question("x"), norm=make(FakeLexicon(warnings=("user lexicon bad.json ignored",))))
    assert s.warnings == ("user lexicon bad.json ignored",)


def test_default_lexicon_is_the_bundled_one():
    norm = ScriptNormalizer(speak_formulas=lambda t: t, speak_units=lambda t: t)
    s = norm.to_script([question("The asthenosphere flows.")], NO_RESOLUTIONS, DEFAULT)
    assert [(o.surface, o.source) for o in s.segments[0].overrides] == [
        ("asthenosphere", "lexicon")
    ]


# --- IUPAC overrides and R5 -------------------------------------------------------------------


def iupac_res(
    name: str, status="ok", kind="iupac", canonical="isobutanol"
) -> dict[str, Resolution]:
    return {name: Resolution(name, kind, canonical, {}, "opsin", status)}  # type: ignore[arg-type]


def test_iupac_resolution_adds_an_iupac_override_and_keeps_the_text():
    name = "2-methylpropan-1-ol"
    lex = FakeLexicon(iupac={name: "IPA"})
    q = question("Which is isobutyl alcohol?", choices=abcd("butan-1-ol", name, "a", "b"))
    s = script(q, norm=make(lex), res=iupac_res(name))
    assert texts(s)[3:5] == ["X.", name]
    assert s.segments[4].overrides == (Override(name, "IPA", "iupac"),)
    assert s.segments[2].overrides == s.segments[3].overrides == ()
    assert "isobutanol" not in s.text()


def test_iupac_name_is_shielded_from_the_formula_and_unit_stages():
    name = "2-methylpropan-1-ol"
    lex = FakeLexicon(iupac={name: "IPA"})
    digits = str.maketrans("0123456789", "ABCDEFGHIJ")
    norm = make(lex, formulas=lambda t: t.translate(digits), units=lambda t: t.replace("is", "IS"))
    s = script(question(f"It is {name} or 3."), norm=norm, res=iupac_res(name))
    assert s.segments[0].text == f"It IS {name} or D."
    assert s.segments[0].overrides == (Override(name, "IPA", "iupac"),)


@pytest.mark.parametrize("status", ["not_found", "timeout", "offline", "error"])
def test_iupac_resolution_that_did_not_succeed_changes_nothing(status):
    name = "2-methylpropan-1-ol"
    lex = FakeLexicon(iupac={name: "IPA"})
    norm = make(lex, formulas=lambda t: t.replace("1", "one"))
    s = script(question(f"It is {name}."), norm=norm, res=iupac_res(name, status))
    assert s.segments[0].text == "It is 2-methylpropan-one-ol."
    assert s.segments[0].overrides == ()


def test_iupac_name_the_lexicon_cannot_build_is_spoken_as_text():
    name = "2-methylpropan-1-ol"
    s = script(question(f"It is {name}."), norm=make(FakeLexicon()), res=iupac_res(name))
    assert s.segments[0].text == f"It is {name}."
    assert s.segments[0].overrides == ()


def test_iupac_name_absent_from_the_text_adds_no_override():
    lex = FakeLexicon(iupac={"ethanol": "IPA"})
    s = script(question("Nothing here."), norm=make(lex), res=iupac_res("ethanol"))
    assert s.segments[0].overrides == ()


def test_iupac_name_inside_a_longer_word_is_left_alone():
    lex = FakeLexicon(iupac={"ethanol": "IPA"})
    s = script(question("Ethanolamine, ethanol."), norm=make(lex), res=iupac_res("ethanol"))
    assert s.segments[0].overrides == (Override("ethanol", "IPA", "iupac"),)
    assert s.segments[0].text == "Ethanolamine, ethanol."


def test_longer_iupac_name_wins_over_a_name_inside_it():
    lex = FakeLexicon(iupac={"1,2-dichloroethane": "LONG", "dichloroethane": "SHORT"})
    res = iupac_res("1,2-dichloroethane") | iupac_res("dichloroethane")
    s = script(question("It is 1,2-dichloroethane."), norm=make(lex), res=res)
    assert s.segments[0].overrides == (Override("1,2-dichloroethane", "LONG", "iupac"),)


@pytest.mark.parametrize("kind", ["chemical", "protein", "gene", "iupac"])
@pytest.mark.parametrize("canonical", ["sodium bicarbonate", "baking soda", "BRCA1 protein", None])
def test_r5_a_resolved_name_never_reaches_the_speech(kind, canonical):
    q = question(
        "Is NaHCO3 present, and what about BRCA1?",
        choices=abcd("NaHCO3", "BRCA1", "water", "none"),
        answer="NaHCO3",
    )
    plain = script(q, opts=READ)
    res = {
        "NaHCO3": Resolution("NaHCO3", kind, canonical, {"cid": "516892"}, "pubchem", "ok"),
        "BRCA1": Resolution("BRCA1", kind, canonical, {"uniprot": "P38398"}, "uniprot", "ok"),
    }
    resolved = script(q, opts=READ, res=res)
    assert resolved.text() == plain.text()
    assert resolved.segments == plain.segments
    for leaked in ("sodium bicarbonate", "baking soda", "BRCA1 protein", "bicarbonate"):
        assert leaked not in resolved.text()


def test_r5_with_the_real_lexicon_and_an_unrelated_canonical_name():
    norm = ScriptNormalizer(speak_formulas=lambda t: t, speak_units=lambda t: t)
    q = question("What is NaHCO3?")
    res = {"NaHCO3": Resolution("NaHCO3", "chemical", "sodium bicarbonate", {}, "pubchem", "ok")}
    a = norm.to_script([q], res, DEFAULT)
    b = norm.to_script([q], NO_RESOLUTIONS, DEFAULT)
    assert a == b
    assert "sodium" not in a.text().lower()


def test_normalizer_does_not_mutate_its_input():
    q = question("Pharynx [x]", respellings=(Respelling("Pharynx", "FAR-ingks"),))
    before = repr(q)
    script(q)
    assert repr(q) == before


# --- golden spoken cases ---------------------------------------------------------------------


def fold(text: str) -> str:
    quotes = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}
    return " ".join(text.translate(str.maketrans(quotes)).split())


def check_segments(items: list[dict], script_segments) -> None:
    assert len(items) == len(script_segments), [s.text for s in script_segments]
    for item, seg in zip(items, script_segments, strict=True):
        if "text" in item:
            assert fold(seg.text) == fold(item["text"])
        if "starts_with" in item:
            assert fold(seg.text).startswith(fold(item["starts_with"])), seg.text
        if "pause_ms" in item:
            assert seg.pause_after_ms == item["pause_ms"], seg.text


def check_spoken(case: dict, script, raw_respellings: list[str], *, multiple_choice: bool) -> None:
    spoken = script.text()
    folded = fold(spoken)
    if "exact" in case:
        assert folded == fold(case["exact"])
    if "starts_with" in case:
        assert folded.startswith(fold(case["starts_with"]))
    if "ends_with" in case:
        assert folded.endswith(fold(case["ends_with"]))
    if "segments" in case:
        check_segments(case["segments"], script.segments)
    lowered, at = folded.lower(), 0
    for item in case.get("in_order", []):
        needle = fold(item).lower()
        hit = lowered.find(needle, at)
        assert hit >= 0, f"in_order: {item!r} not found after offset {at} in {folded!r}"
        at = hit + len(needle)
    for item in case.get("must_contain", []):
        assert fold(item).lower() in lowered, f"must_contain: {item!r}"
    for group in case.get("must_contain_any", []):
        assert any(fold(m).lower() in lowered for m in group), f"must_contain_any: {group}"
    forbidden = [*case.get("must_not_contain", []), "[", "]", "ANSWER"]
    forbidden += [r for r in raw_respellings if any(c.isupper() for c in r)]
    if multiple_choice:
        forbidden += ["W)", "X)", "Y)", "Z)"]
    for item in forbidden:
        # Whitespace-only items (tab, NBSP, double space) are checked on the raw script.
        haystack, needle = (spoken, item) if not item.strip() else (folded, fold(item))
        assert needle not in haystack, f"must_not_contain: {item!r} in {spoken!r}"


@pytest.fixture(scope="module")
def real_normalizer() -> ScriptNormalizer:
    return ScriptNormalizer()


@pytest.mark.parametrize("case", SPOKEN, ids=[c["id"] for c in SPOKEN])
def test_golden_spoken_case(case, real_normalizer):
    fixture = case.get("fixture", case["id"])
    opts = RenderOptions(**case.get("options", {}))
    questions = parse((FIXTURES / f"{fixture}.txt").read_bytes().decode("utf-8"))
    script_ = real_normalizer.to_script(questions, NO_RESOLUTIONS, opts)
    parsed = PARSED[fixture].get("questions", [PARSED[fixture]])
    check_spoken(
        case,
        script_,
        [r["respelling"] for q in parsed for r in q["respellings"]],
        multiple_choice=any(q["choices"] for q in parsed),
    )
    assert all(seg.text for seg in script_.segments)


def test_every_golden_case_names_a_real_fixture():
    for case in SPOKEN:
        assert (FIXTURES / f"{case.get('fixture', case['id'])}.txt").exists(), case["id"]


def test_golden_harness_catches_a_violation():
    class Seg:
        def __init__(self, text, pause):
            self.text, self.pause_after_ms = text, pause

    class Script:
        segments = (Seg("a", 400), Seg("b", 0))

        def text(self):
            return "a b"

    with pytest.raises(AssertionError):
        check_spoken({"must_not_contain": ["b"]}, Script(), [], multiple_choice=False)
    with pytest.raises(AssertionError):
        check_spoken({"in_order": ["b", "a"]}, Script(), [], multiple_choice=False)
    with pytest.raises(AssertionError):
        check_spoken(
            {"segments": [{"text": "a", "pause_ms": 300}]}, Script(), [], multiple_choice=False
        )
    with pytest.raises(AssertionError):  # a pause-only item still pins its pause
        check_spoken(
            {"segments": [{"pause_ms": 300}, {"text": "b"}]}, Script(), [], multiple_choice=False
        )
    check_spoken(
        {"segments": [{"text": "a", "pause_ms": 400}, {"starts_with": "b"}]},
        Script(),
        [],
        multiple_choice=False,
    )
    check_spoken(
        {"segments": [{"pause_ms": 400}, {"pause_ms": 0}]}, Script(), [], multiple_choice=False
    )
    assert fold("a  b\u00a0c") == "a b c"
