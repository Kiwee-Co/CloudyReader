"""Parser tests: golden fixtures plus explicit cases for every header, marker and guide variant."""

import re
from pathlib import Path

import pytest
import yaml

from cloudyreader.models import Fmt, Kind, Respelling
from cloudyreader.parser import QuestionParser, extract_guides, parse

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "questions"
GOLDEN = yaml.safe_load((ROOT / "tests" / "golden" / "parse_cases.yaml").read_text("utf-8"))[
    "cases"
]

EARTH = (
    "TOSS-UP\n"
    "2) EARTH SCIENCE Multiple Choice The source of energy for the movements of\n"
    "crustal plates is currently thought to be the result of:\n"
    "W) tidal motion that produces a net westward movement of landmasses\n"
    "X) the pulling apart of the poles resulting from the Earth’s rotation\n"
    "Y) convection currents produced within the mantle\n"
    "Z) remnant magnetism\n"
)
LIFE = (
    "1) LIFE SCIENCE Multiple Choice Which of the following is NOT part of the human respiratory\n"
    "system?\n"
    "W) Pharynx [FAR-ingks]\n"
    "X) Larynx [LAR-ingks]\n"
    "Y) Esophagus [i-SOF-uh-guhs]\n"
    "Z) Trachea [TRAY-kee-uh]\n"
    "ANSWER: Y) ESOPHAGUS\n"
)


def one(raw: str):
    questions = parse(raw)
    assert len(questions) == 1, questions
    return questions[0]


def strip_guides(text: str, guides: list[str]) -> str:
    for guide in guides:
        text = re.sub(r"\s*\[" + re.escape(guide) + r"\]", "", text)
    return text


def pairs(q) -> list[tuple[str, str]]:
    found = [*q.respellings, *(r for c in q.choices for r in c.respellings)]
    return [(r.surface, r.respelling) for r in found]


# --- golden fixtures -------------------------------------------------------------------------


def check_question(q, exp: dict) -> None:
    guides = [r["respelling"] for r in exp["respellings"]]
    assert q.number == exp["number"]
    assert q.kind == (None if exp["kind"] is None else Kind(exp["kind"]))
    assert (q.category or "").lower() == (exp["category"] or "").lower()
    assert (q.fmt.value if q.fmt else None) == exp["fmt"]
    assert q.stem == strip_guides(exp["stem"], guides)
    assert {c.letter: c.text for c in q.choices} == {
        k: strip_guides(v, guides) for k, v in exp["choices"].items()
    }
    assert pairs(q) == [(r["surface"], r["respelling"]) for r in exp["respellings"]]
    assert q.answer == exp["answer"]


@pytest.mark.parametrize("case", GOLDEN, ids=[c["id"] for c in GOLDEN])
def test_golden_case(case):
    raw = (FIXTURES / f"{case['id']}.txt").read_bytes().decode("utf-8")
    questions = parse(raw)
    expected = case.get("questions", [case])
    assert len(questions) == len(expected)
    for q, exp in zip(questions, expected, strict=True):
        check_question(q, exp)


def test_every_fixture_has_a_golden_case():
    ids = {c["id"] for c in GOLDEN}
    assert {p.stem for p in FIXTURES.glob("[0-9][0-9]-*.txt")} <= ids


# --- brief examples and basic shape ----------------------------------------------------------


def test_brief_example_toss_up():
    q = one(EARTH)
    assert (q.kind, q.number, q.category, q.fmt) == (
        Kind.TOSS_UP,
        2,
        "EARTH SCIENCE",
        Fmt.MULTIPLE_CHOICE,
    )
    assert q.stem == (
        "The source of energy for the movements of crustal plates is currently thought to be "
        "the result of:"
    )
    assert [c.letter for c in q.choices] == ["W", "X", "Y", "Z"]
    assert q.choices[1].text == "the pulling apart of the poles resulting from the Earth’s rotation"
    assert q.answer is None


def test_brief_example_respelling_and_answer():
    q = one(LIFE)
    assert q.kind is None
    assert q.number == 1
    assert q.answer == "Y) ESOPHAGUS"
    assert q.stem == "Which of the following is NOT part of the human respiratory system?"
    assert [c.text for c in q.choices] == ["Pharynx", "Larynx", "Esophagus", "Trachea"]
    assert q.choices[0].respellings == (Respelling("Pharynx", "FAR-ingks"),)
    assert q.respellings == ()


def test_module_function_matches_class():
    assert parse(LIFE) == QuestionParser().parse(LIFE)


def test_raw_is_the_question_slice():
    first, second = parse(
        "TOSS-UP\n1) BIOLOGY Short Answer One?\nANSWER: A\nBONUS\n2) BIOLOGY Short Answer Two?\n"
    )
    assert first.raw == "TOSS-UP\n1) BIOLOGY Short Answer One?\nANSWER: A"
    assert second.raw == "BONUS\n2) BIOLOGY Short Answer Two?"


@pytest.mark.parametrize("raw", ["", "   ", "\n\n", "\ufeff", "TOSS-UP", "BONUS\n\n", "ANSWER: X"])
def test_nothing_to_read_gives_no_questions(raw):
    assert parse(raw) == []


# --- header, number, category, format --------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "kind"),
    [
        ("TOSS-UP", Kind.TOSS_UP),
        ("toss-up", Kind.TOSS_UP),
        ("Toss Up", Kind.TOSS_UP),
        ("TOSSUP", Kind.TOSS_UP),
        ("BONUS", Kind.BONUS),
        ("Bonus", Kind.BONUS),
        ("bonus:", Kind.BONUS),
        ("TOSS-UP:", Kind.TOSS_UP),
    ],
)
def test_header_kinds(header, kind):
    q = one(f"{header}\n3) PHYSICS Short Answer What is a joule?")
    assert q.kind is kind
    assert q.number == 3
    assert q.stem == "What is a joule?"


def test_header_and_number_on_one_line():
    q = one("BONUS 18) MATH Short Answer What is six times three?")
    assert (q.kind, q.number, q.category, q.stem) == (
        Kind.BONUS,
        18,
        "MATH",
        "What is six times three?",
    )


def test_bonus_word_inside_a_stem_is_not_a_header():
    q = one("Bonus points are awarded for which kind of answer?")
    assert q.kind is None
    assert q.stem == "Bonus points are awarded for which kind of answer?"


def test_no_header_no_number():
    q = one("PHYSICS Short Answer What is a joule?")
    assert (q.kind, q.number, q.category, q.fmt) == (None, None, "PHYSICS", Fmt.SHORT_ANSWER)


def test_bare_stem_is_a_question():
    q = one("What is a joule?")
    assert (q.kind, q.number, q.category, q.fmt, q.choices) == (None, None, None, None, ())
    assert q.stem == "What is a joule?"


def test_bare_stem_with_caps_start_keeps_every_word():
    q = one("DNA is made of which sugar?")
    assert q.category is None
    assert q.stem == "DNA is made of which sugar?"


def test_number_only_with_known_category_and_no_label():
    q = one("5) BIOLOGY What is mitosis?")
    assert (q.number, q.category, q.fmt, q.stem) == (5, "BIOLOGY", None, "What is mitosis?")


def test_multi_word_category_as_pasted():
    q = one("TOSS-UP\n19) EARTH AND SPACE SCIENCE Short Answer What is a star?")
    assert q.category == "EARTH AND SPACE SCIENCE"


@pytest.mark.parametrize(
    ("label", "fmt"),
    [
        ("Multiple Choice", Fmt.MULTIPLE_CHOICE),
        ("multiple choice", Fmt.MULTIPLE_CHOICE),
        ("MULTIPLE CHOICE", Fmt.MULTIPLE_CHOICE),
        ("Multiple-Choice", Fmt.MULTIPLE_CHOICE),
        ("Short Answer", Fmt.SHORT_ANSWER),
        ("short answer", Fmt.SHORT_ANSWER),
        ("SHORT-ANSWER", Fmt.SHORT_ANSWER),
        ("Short Answer:", Fmt.SHORT_ANSWER),
    ],
)
def test_format_label_variants(label, fmt):
    q = one(f"4) CHEMISTRY {label} What is an ion?")
    assert q.fmt is fmt
    assert q.category == "CHEMISTRY"
    assert q.stem == "What is an ion?"


def test_dash_and_own_line_label():
    q = one("TOSS-UP\n8) PHYSICS – Short Answer\nWhat is a farad?")
    assert (q.category, q.fmt, q.stem) == ("PHYSICS", Fmt.SHORT_ANSWER, "What is a farad?")


@pytest.mark.parametrize(
    ("head", "category"),
    [
        ("TOSS-UP\n1) Life Science – Short Answer", "Life Science"),
        ("BONUS 4) Earth and Space Science Short Answer", "Earth and Space Science"),
        ("2) Physics Short Answer", "Physics"),
        ("TOSS-UP\nChemistry - Short Answer", "Chemistry"),
    ],
)
def test_title_case_category_with_a_header(head, category):
    q = one(f"{head} What is a joule?")
    assert (q.category, q.fmt, q.stem) == (category, Fmt.SHORT_ANSWER, "What is a joule?")


@pytest.mark.parametrize(
    "raw",
    [
        "Life Science Short Answer What is a joule?",
        "3) Which gas is a Multiple Choice question?",
        "2) What is Short Answer?",
        "BONUS\nwhat is a short answer about?",
    ],
)
def test_title_case_category_needs_a_header_and_capitalised_words(raw):
    q = one(raw)
    assert q.category is None
    assert q.fmt is None


def test_number_with_a_trailing_dot_in_the_header():
    q = one("TOSS-UP 3.\nPHYSICS Short Answer What is a joule?")
    assert (q.number, q.category) == (3, "PHYSICS")


def test_label_inside_a_stem_is_not_a_label():
    q = one("Which of the following is a Multiple Choice question?")
    assert q.fmt is None
    assert q.stem == "Which of the following is a Multiple Choice question?"


def test_format_label_without_category():
    q = one("3) Multiple Choice Which gas is lightest?\nW) H\nX) He\nY) O\nZ) N")
    assert (q.number, q.category, q.fmt) == (3, None, Fmt.MULTIPLE_CHOICE)


def test_decimal_at_start_is_not_a_number():
    q = one("0.3 is the frequency of which allele?")
    assert q.number is None
    assert q.stem == "0.3 is the frequency of which allele?"


# --- whitespace and hard wraps ---------------------------------------------------------------


def test_crlf_nbsp_tabs_and_double_spaces():
    raw = (
        "TOSS-UP \r\n7)\t CHEMISTRY\xa0 Multiple  Choice  What\xa0is   an\tion?\r\n"
        "W)\xa0 a\r\nX)  b\r\nY)\tc\r\nZ) d \r\n"
    )
    q = one(raw)
    assert (q.number, q.category, q.stem) == (7, "CHEMISTRY", "What is an ion?")
    assert [c.text for c in q.choices] == ["a", "b", "c", "d"]
    assert "\r" not in q.raw


def test_curly_quotes_and_symbols_are_kept():
    q = one("BONUS\n2) BIOLOGY Short Answer Darwin’s “survival” ΔU = 6.02 × 10^23 − x²?")
    assert q.stem == "Darwin’s “survival” ΔU = 6.02 × 10^23 − x²?"


def test_bom_and_blank_lines_around_the_paste():
    q = one(
        "\ufeff\n\n  TOSS-UP  \n\n   16) ENERGY Short Answer Name the unit of power.\n"
        "\n   ANSWER: WATT\n\n"
    )
    assert (q.kind, q.number, q.answer) == (Kind.TOSS_UP, 16, "WATT")


def test_hard_wrap_joins_with_one_space():
    q = one("1) MATH Short Answer What is\nthe sum of\n   two and   three?")
    assert q.stem == "What is the sum of two and three?"


@pytest.mark.parametrize(
    ("wrapped", "joined"),
    [
        ("the respira-\ntory system", "the respiratory system"),
        ("the respira-\ntory, gases", "the respiratory, gases"),
        ("Hardy-\nWeinberg law", "Hardy-Weinberg law"),
        ("fructose-6-\nphosphate", "fructose-6-phosphate"),
        ("2-\nmethylpropan-1-ol", "2-methylpropan-1-ol"),
        ("butan-\n1-ol", "butan-1-ol"),
        ("father-and-\nson team", "father-and-son team"),
        ("x-\nrays", "x-rays"),
        ("the half-\nlife of", "the half-life of"),
        ("a well-\nknown fact", "a well-known fact"),
        ("a spaced -\ndash", "a spaced - dash"),
        ("an em—\ndash", "an em— dash"),
    ],
)
def test_hyphen_at_line_break(wrapped, joined):
    assert one(f"1) MATH Short Answer {wrapped}").stem == joined


# --- choices ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "markers",
    [
        ["W)", "X)", "Y)", "Z)"],
        ["w)", "x)", "y)", "z)"],
        ["W.", "X.", "Y.", "Z."],
        ["W:", "X:", "Y:", "Z:"],
        ["w.", "x.", "y.", "z."],
    ],
)
def test_marker_styles(markers):
    lines = [f"{m} choice {n}" for m, n in zip(markers, "abcd", strict=True)]
    q = one("2) MATH Multiple Choice Pick one.\n" + "\n".join(lines))
    assert [(c.letter, c.text) for c in q.choices] == [
        ("W", "choice a"),
        ("X", "choice b"),
        ("Y", "choice c"),
        ("Z", "choice d"),
    ]
    assert q.stem == "Pick one."


def test_glued_marker_text():
    q = one(
        "2) PHYSICS Multiple Choice Pick.\nW)Speed\nX)Distance\nY)Velocity\nZ)Mass\n"
        "ANSWER: Y)Velocity"
    )
    assert [c.text for c in q.choices] == ["Speed", "Distance", "Velocity", "Mass"]
    assert q.answer == "Y)Velocity"


def test_choice_text_wraps_across_lines():
    q = one("2) MATH Multiple Choice Pick.\nW) first\nline\nX) b\nY) c\nZ) d")
    assert q.choices[0].text == "first line"


def test_inline_choices_on_one_line():
    q = one(
        "TOSS-UP\n12) LIFE SCIENCE Multiple Choice How many? W) 23 X) 46 Y) 48 Z) 92\nANSWER: X) 46"
    )
    assert [c.text for c in q.choices] == ["23", "46", "48", "92"]
    assert q.stem == "How many?"
    assert q.answer == "X) 46"


def test_parenthesised_letter_in_stem_is_not_a_marker():
    q = one(
        "2) MATH Multiple Choice In the figure, point (X) lies on the line. W) 3 X) 4 Y) 5 Z) 6"
    )
    assert q.stem == "In the figure, point (X) lies on the line."
    assert [c.text for c in q.choices] == ["3", "4", "5", "6"]


def test_initials_in_stem_with_paren_markers():
    q = one(
        "BONUS\n14) PHYSICS Multiple Choice The father-and-son team of\n"
        "W. H. Bragg and W. L. Bragg shared the prize.\n"
        "W) X-rays\nX) Neutrons\nY) Alpha particles\nZ) Visible light\n"
    )
    assert q.stem == "The father-and-son team of W. H. Bragg and W. L. Bragg shared the prize."
    assert q.choices[0].text == "X-rays"


def test_initials_in_stem_with_dot_markers():
    q = one(
        "The father-and-son team of\nW. H. Bragg and W. L. Bragg shared the prize.\n"
        "W. X-rays\nX. Neutrons\nY. Alpha particles\nZ. Visible light"
    )
    assert q.stem == "The father-and-son team of W. H. Bragg and W. L. Bragg shared the prize."
    assert [c.text for c in q.choices] == ["X-rays", "Neutrons", "Alpha particles", "Visible light"]


def test_genus_abbreviation_in_stem_is_not_a_marker():
    q = one(
        "Which bacterium, Y. pestis, caused the plague?\n"
        "W. Yersinia\nX. Vibrio\nY. Listeria\nZ. Shigella"
    )
    assert q.stem == "Which bacterium, Y. pestis, caused the plague?"
    assert [c.text for c in q.choices] == ["Yersinia", "Vibrio", "Listeria", "Shigella"]


def test_markers_out_of_order_or_partial_are_not_choices():
    q = one("2) MATH Short Answer Which of X) or Y) is larger, W) or Z)?")
    assert q.choices == ()
    assert q.stem == "Which of X) or Y) is larger, W) or Z)?"


def test_short_answer_has_no_choices():
    q = one("3) BIOLOGY Short Answer Name the enzyme.\nANSWER: LIGASE")
    assert q.choices == ()


# --- answer ----------------------------------------------------------------------------------


def test_answer_with_accept_lines_joins_everything():
    q = one(
        "TOSS-UP\n5) LIFE SCIENCE Short Answer Which enzyme?\n"
        "ANSWER: DNA LIGASE\nACCEPT: LIGASE\nDO NOT ACCEPT: DNA POLYMERASE\n"
    )
    assert q.answer == "DNA LIGASE ACCEPT: LIGASE DO NOT ACCEPT: DNA POLYMERASE"
    assert q.stem == "Which enzyme?"


@pytest.mark.parametrize(
    ("line", "answer"),
    [
        ("ANSWER: 6", "6"),
        ("Answer: 6", "6"),
        ("answer:6", "6"),
        ("ANSWER 6", "6"),
        ("  ANSWER:\t6  ", "6"),
        ("ANSWER:\n6", "6"),
    ],
)
def test_answer_marker_variants(line, answer):
    assert one(f"1) MATH Short Answer How many?\n{line}").answer == answer


def test_answer_glued_after_choices_on_one_line():
    q = one("1) MATH Multiple Choice Pick.\nW) a X) b Y) c Z) d ANSWER: Y) c")
    assert [c.text for c in q.choices] == ["a", "b", "c", "d"]
    assert q.answer == "Y) c"


def test_answer_word_in_a_stem_is_not_a_marker():
    q = one("1) MATH Short Answer Answer the question: what is two plus two?\nANSWER: 4")
    assert q.stem == "Answer the question: what is two plus two?"
    assert q.answer == "4"


def test_empty_answer_is_none():
    assert one("1) MATH Short Answer How many?\nANSWER:").answer is None


# --- several questions ----------------------------------------------------------------------


def test_several_questions_with_headers():
    raw = (
        "TOSS-UP\n1) MATH Short Answer One?\nANSWER: 1\n"
        "BONUS\n2) MATH Short Answer Two?\nANSWER: 2\n"
        "TOSS-UP 3) MATH Short Answer Three?"
    )
    qs = parse(raw)
    assert [(q.kind, q.number, q.stem, q.answer) for q in qs] == [
        (Kind.TOSS_UP, 1, "One?", "1"),
        (Kind.BONUS, 2, "Two?", "2"),
        (Kind.TOSS_UP, 3, "Three?", None),
    ]


def test_several_questions_numbers_only_after_answers():
    qs = parse(LIFE + EARTH.replace("TOSS-UP\n", "") + "3) Which gas is lightest?\nANSWER: H")
    assert [q.number for q in qs] == [1, 2, 3]
    assert qs[0].answer == "Y) ESOPHAGUS"
    assert qs[1].answer is None
    assert len(qs[1].choices) == 4


def test_numbers_without_answers_split_on_a_strong_head():
    qs = parse("1) MATH Short Answer One?\n2) MATH Short Answer Two?\n")
    assert [q.stem for q in qs] == ["One?", "Two?"]


def test_numbered_line_without_a_head_stays_in_an_open_stem():
    q = one("1) MATH Short Answer Rank these:\n2) first\n3) second")
    assert q.stem == "Rank these: 2) first 3) second"


def test_numbered_list_inside_a_stem_line_is_not_a_boundary():
    qs = parse(
        "1) CHEMISTRY Short Answer Rank these from smallest to largest: "
        "1) atom 2) nucleus 3) quark.\n"
        "ANSWER: QUARK, NUCLEUS, ATOM\n"
        "2) BIOLOGY Short Answer Name the organelle that makes ATP."
    )
    assert [q.number for q in qs] == [1, 2]
    assert qs[0].stem == "Rank these from smallest to largest: 1) atom 2) nucleus 3) quark."
    assert qs[0].answer == "QUARK, NUCLEUS, ATOM"


def test_bare_number_after_a_blank_line_starts_a_question():
    qs = parse("1) MATH Short Answer One?\n\n2) What is two?\n\n3) What is three?")
    assert [(q.number, q.stem) for q in qs] == [
        (1, "One?"),
        (2, "What is two?"),
        (3, "What is three?"),
    ]


def test_blank_line_does_not_split_a_question():
    q = one("TOSS-UP\n\n   16) ENERGY Short Answer Name it.\n\n   ANSWER: WATT\n")
    assert (q.number, q.answer) == (16, "WATT")


# --- respelling guides -----------------------------------------------------------------------


def test_stem_guide_is_stripped_and_recorded():
    q = one("3) BIOLOGY Short Answer The Okazaki [oh-kuh-ZAH-kee] fragments join.")
    assert q.stem == "The Okazaki fragments join."
    assert q.respellings == (Respelling("Okazaki", "oh-kuh-ZAH-kee"),)


def test_multi_word_guide_takes_that_many_words():
    q = one("3) BIOLOGY Short Answer In the Krebs cycle [KREBZ SY-kul] take place.")
    assert q.stem == "In the Krebs cycle take place."
    assert q.respellings == (Respelling("Krebs cycle", "KREBZ SY-kul"),)


def test_hyphenated_headword_counts_hyphen_units():
    q = one("Michaelis-Menten [mi-KAY-lis MEN-tun] kinetics describe enzyme rates.")
    assert q.respellings == (Respelling("Michaelis-Menten", "mi-KAY-lis MEN-tun"),)
    q = one("A population in Hardy-Weinberg\n[HAR-dee WYN-berg] equilibrium.")
    assert q.respellings == (Respelling("Hardy-Weinberg", "HAR-dee WYN-berg"),)
    assert q.stem == "A population in Hardy-Weinberg equilibrium."


def test_headword_falls_back_to_one_token():
    q = one("big Pharynx [FAR-ingks LAR-ingks TRAY-kee-uh] is next.")
    assert q.respellings[0].surface == "Pharynx"
    assert q.stem == "big Pharynx is next."


def test_possessive_after_the_bracket_attaches_to_the_word():
    q = one("According to Le Chatelier [luh shat-el-YAY]’s principle, add more.")
    assert q.stem == "According to Le Chatelier’s principle, add more."
    assert q.respellings == (Respelling("Le Chatelier", "luh shat-el-YAY"),)


def test_guide_glued_to_the_word_and_punctuation_after():
    q = one("Pharynx[FAR-ingks], larynx [LAR-ingks].")
    assert q.stem == "Pharynx, larynx."
    assert [r.surface for r in q.respellings] == ["Pharynx", "larynx"]


@pytest.mark.parametrize(
    "bracket",
    [
        "[H+]",
        "[Ca2+]",
        "[1]",
        "[OH-]",
        "[NH3]",
        "[A]",
        "[ES]",
        "[0, 1]",
        "[DNA]",
        "[ATP]",
        "[NaCl]",
        "[NaOH]",
        "[CO]",
        "[NASA]",
        "[A-T-P]",
        "[Krebs cycle]",
        "[see note]",
        "[-ingks]",
        "[ingks-]",
        "[]",
    ],
)
def test_brackets_that_are_not_guides_stay_as_text(bracket):
    q = one(f"The substance {bracket} is present.")
    assert q.stem == f"The substance {bracket} is present."
    assert q.respellings == ()


@pytest.mark.parametrize(
    "bracket", ["[JOOL]", "[buh-nan-uh]", "[pi-KAHN or PEE-kan]", "[FOS-foh-FRUK-toh-KY-nays]"]
)
def test_brackets_that_are_guides_are_removed(bracket):
    q = one(f"The pecan {bracket} is a nut.")
    assert q.stem == "The pecan is a nut."
    assert len(q.respellings) == 1
    assert q.respellings[0].respelling == bracket[1:-1]


@pytest.mark.parametrize(
    ("written", "guide"),
    [
        ("SLAC [slack] runs", "slack"),
        ("the phylum [FYE- lum] runs", "FYE-lum"),
        ("the phylum [FYE - lum] runs", "FYE-lum"),
        ("the fovea (read as: FOE-vee-ah) runs", "FOE-vee-ah"),
        ("the fovea (Read As: foe-vee-ah) runs", "foe-vee-ah"),
        ("the cotyledon (PRONOUNCED: KOT-ill-ee-don) runs", "KOT-ill-ee-don"),
        ("the Oort cloud [ort] runs", "ort"),
    ],
)
def test_real_world_guide_forms(written, guide):
    q = one(f"1) MATH Short Answer {written}")
    assert [r.respelling for r in q.respellings] == [guide]
    assert "[" not in q.stem and "(" not in q.stem
    assert q.stem.endswith(" runs") and " runs runs" not in q.stem


@pytest.mark.parametrize(
    "written",
    [
        "the item [sic] was",
        "the item [aq] was",
        "the item [see note] was",
        "the item (also read as: 3) was",
    ],
)
def test_lowercase_brackets_that_are_notes_stay_text(written):
    q = one(f"1) MATH Short Answer {written}")
    assert q.respellings == ()
    assert q.stem == written


def test_star_before_the_number_is_ignored():
    q = one("TOSS-UP\n*7) MATH Short Answer What is two plus two?\nANSWER: 4")
    assert (q.number, q.category, q.stem) == (7, "MATH", "What is two plus two?")


@pytest.mark.parametrize(
    "footer",
    [
        "Middle School Round 1 Page 3",
        "PAGE 4",
        "High School Round 12A Page 10",
        "007 Middle School Regional Science Bowl – Round 7 Page 4",
        "~~~~~~",
        "*****",
        "_____",
    ],
)
def test_page_footers_and_rules_are_dropped(footer):
    q = one(f"1) MATH Short Answer What is\n{footer}\ntwo plus two?\nANSWER: 4")
    assert q.stem == "What is two plus two?"


def test_alternative_pronunciations_keep_the_full_bracket_text():
    q = one("Pecan [pi-KAHN or PEE-kan] is a nut.")
    assert q.respellings == (Respelling("Pecan", "pi-KAHN or PEE-kan"),)


def test_bracket_not_directly_after_a_word_is_not_a_guide():
    q = one("[FAR-ingks] starts the line, and so, [LAR-ingks] follows a comma, (x) [TRAY-kee-uh].")
    assert q.respellings == ()
    assert "[FAR-ingks]" in q.stem


def test_choice_guides_and_stem_guides_stay_apart():
    q = one(
        "1) LIFE SCIENCE Multiple Choice The Krebs cycle [KREBZ SY-kul] is in which place?\n"
        "W) Matrix [MAY-triks]\nX) Cytosol\nY) Nucleus [NOO-klee-us]\nZ) Golgi"
    )
    assert q.respellings == (Respelling("Krebs cycle", "KREBZ SY-kul"),)
    assert [c.respellings for c in q.choices] == [
        (Respelling("Matrix", "MAY-triks"),),
        (),
        (Respelling("Nucleus", "NOO-klee-us"),),
        (),
    ]
    assert [c.text for c in q.choices] == ["Matrix", "Cytosol", "Nucleus", "Golgi"]


def test_answer_line_guides_stay_in_the_answer():
    q = one("1) LIFE SCIENCE Short Answer Which protein?\nANSWER: TROPONIN [TROH-puh-nin]")
    assert q.answer == "TROPONIN [TROH-puh-nin]"
    assert q.respellings == ()


def test_stem_with_both_guide_and_concentration_bracket():
    q = one(
        "The sarcoplasmic reticulum [sar-koh-PLAZ-mik ri-TIK-yuh-lum] releases Ca2+ "
        "and raises [Ca2+]."
    )
    assert q.stem == "The sarcoplasmic reticulum releases Ca2+ and raises [Ca2+]."
    assert q.respellings == (
        Respelling("sarcoplasmic reticulum", "sar-koh-PLAZ-mik ri-TIK-yuh-lum"),
    )


@pytest.mark.parametrize(
    "raw",
    [
        "[[[",
        "]]] [",
        "W) X) Y) Z)",
        "TOSS-UP\nTOSS-UP\nBONUS",
        "1)\n2)\n3)",
        "ANSWER:\nANSWER:",
        "\x00\x01\x02",
        "W)" * 50,
        "[FAR-ingks]" * 20,
    ],
)
def test_odd_input_never_raises(raw):
    assert isinstance(parse(raw), list)


def test_extract_guides_is_public():
    text, guides = extract_guides("The Pharynx [FAR-ingks] and [H+].")
    assert text == "The Pharynx and [H+]."
    assert guides == (Respelling("Pharynx", "FAR-ingks"),)


def test_pdf_symbol_font_glyphs_are_mapped_or_dropped():
    q = one("1) CHEMISTRY Short Answer N2 + 3H2 \uf0e0 what? \uf8eb 2 \uf8f6 \ufffd x")
    assert q.stem == "N2 + 3H2 \u2192 what? 2 x"
