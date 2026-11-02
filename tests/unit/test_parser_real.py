"""Parser hardening against the real NSB corpus: every case is a short excerpt of a real round.

The excerpts are inline copies (never read from .data/), so the default gate needs no corpus.
`scripts/corpus_report.py` runs the same parser over all rounds when they are extracted.
"""

import pytest

from cloudyreader.models import Fmt, Kind, Respelling
from cloudyreader.parser import extract_guides, parse

MC, SA = Fmt.MULTIPLE_CHOICE, Fmt.SHORT_ANSWER


def one(raw: str):
    questions = parse(raw)
    assert len(questions) == 1, questions
    return questions[0]


NUCLEUS = (
    "TOSS-UP\n\n1) LIFE SCIENCE Short Answer What organelle functions to isolate a human cell’s "
    "chromosomes\nfrom the cytoplasm?\n\nANSWER: NUCLEUS\n\n"
)
STATIC = (
    "BONUS\n\n2) PHYSICAL SCIENCE Multiple Choice Which of the following BEST describes the term "
    "static:\n\nW) stationary\nX) low\nY) constant\nZ) used\n\nANSWER: W) STATIONARY\n"
)
TIDES = (
    "TOSS-UP\n\n3) EARTH SCIENCE Short Answer What is the general name for the rising and falling "
    "of sea\nlevels in response to the forces exerted by the Moon and Sun?\n\nANSWER: TIDES\n"
)


# --- page noise: round titles, footers, rules --------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "ROUND 1",
        "ROUND 10A",
        "ROUND 1 A",
        "ROUND ROBIN 2",
        "ROUND ROBIN – ROUND 1",
        "DOUBLE ELIMINATION ROUND 1",
        "DOUBLE ELIMINATION – ROUND 3",
        "SINGLE ELIMINATION ROUND 3",
        "MIDDLE SCHOOL - ROUND 1A",
        "Middle School Set 1",
        "High School Set 7",
    ],
)
def test_round_title_before_the_first_header_is_not_a_question(title):
    q = one(f"{title}\n\n{NUCLEUS}")
    assert (q.kind, q.number, q.stem.startswith("What organelle")) == (Kind.TOSS_UP, 1, True)


@pytest.mark.parametrize(
    "footer",
    [
        "Middle School Round 1 Page 1",
        "2016 National Science Bowl® - Middle School Regional Events Page 1",
        "Round 2, Page 6",
        "Round 1A ~ Page 1",
        "2017 Middle School Regional NSB® PAGE 1",
        "DOUBLE ELIMINATION – ROUND 3 ~ Page 1",
        "Round 14 Page 9",
        "Double Elimination 1, Page 1",
        "Junior National Science Bowl Round Robin 1 Page 1",
        "2019 Regional Science Bowl – Round 10A Page 12",
        "2007 Middle School Regional Science Bowl –Round 1 Page 1",
    ],
)
def test_footer_between_questions_stays_out_of_the_answer(footer):
    first, second = parse(f"{STATIC}\n{footer}\n{TIDES}")
    assert first.answer == "W) STATIONARY"
    assert (second.kind, second.number) == (Kind.TOSS_UP, 3)
    assert len(parse(f"{STATIC}\n{footer}\n{TIDES}")) == 2


def test_footer_in_the_middle_of_a_stem_is_dropped():
    q = one("TOSS-UP\n\n4) MATH Short Answer How many degrees are in\nRound 1 Page 3\none-third?\n")
    assert q.stem == "How many degrees are in one-third?"


@pytest.mark.parametrize("rule", ["~" * 29, "*" * 18, "_" * 54, "-" * 30])
def test_rule_lines_between_questions_are_dropped(rule):
    first, second = parse(f"{STATIC}\n{rule}\n\n{TIDES}")
    assert first.answer == "W) STATIONARY"
    assert second.number == 3


def test_editorial_omission_note_is_not_a_question():
    raw = (
        "TOSS-UP\n\nThe toss-up and bonus for Question 8 have been omitted.\n\n"
        "2007 Middle School Regional Science Bowl – Round 7 Page 4\n"
        "TOSS-UP\n\n9) GENERAL SCIENCE Multiple Choice Which gas is lightest:\n"
        "W) H\nX) He\nY) O\nZ) N\n\nANSWER: W) H\n"
    )
    q = one(raw)
    assert (q.number, q.category, q.answer) == (9, "GENERAL SCIENCE", "W) H")


def test_header_with_only_a_page_footer_after_it_gives_no_question():
    assert parse("TOSS-UP\n\nRound 1 Page 3\n") == []


# --- label variants ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "number", "category", "fmt", "stem"),
    [
        (
            "1) Math – Short Answer What is the square of the binomial x – 11?",
            1,
            "Math",
            SA,
            "What is the square of the binomial x – 11?",
        ),
        (
            "2) Earth and Space – Multiple Choice What is the primary reason for erosion?",
            2,
            "Earth and Space",
            MC,
            "What is the primary reason for erosion?",
        ),
        (
            "2) Earth & Space – Short Answer What planet in our solar system has rings?",
            2,
            "Earth & Space",
            SA,
            "What planet in our solar system has rings?",
        ),
        (
            "3) Energy – Multiple Choice What type of battery is common?",
            3,
            "Energy",
            MC,
            "What type of battery is common?",
        ),
        (
            "5) EARTH AND SPACE SCIENCE Short Answer What is the name of the preserved remains?",
            5,
            "EARTH AND SPACE SCIENCE",
            SA,
            "What is the name of the preserved remains?",
        ),
        (
            "24) LIFE SCIENCE. Short Answer What are the respective scientific names?",
            24,
            "LIFE SCIENCE",
            SA,
            "What are the respective scientific names?",
        ),
        (
            "*1) GENERAL SCIENCE Multiple Choice Fungi are usually spread most effectively by:",
            1,
            "GENERAL SCIENCE",
            MC,
            "Fungi are usually spread most effectively by:",
        ),
        (
            "*12) PHYSICAL SCIENCE Multiple Choice Which of the following solutions conduct?",
            12,
            "PHYSICAL SCIENCE",
            MC,
            "Which of the following solutions conduct?",
        ),
        (
            "46 MATH Multiple Choice Assuming a year in a dog’s life is equivalent to 7 years",
            46,
            "MATH",
            MC,
            "Assuming a year in a dog’s life is equivalent to 7 years",
        ),
        (
            "17 LIFE SCIENCE Short Answer There are two main kinds of vaccines.",
            17,
            "LIFE SCIENCE",
            SA,
            "There are two main kinds of vaccines.",
        ),
        (
            "8 Energy Multiple Choice Scientists at SLAC have been using machine learning",
            8,
            "Energy",
            MC,
            "Scientists at SLAC have been using machine learning",
        ),
        (
            "12) ENERGYMultiple Choice Researchers are beginning to focus on butanol",
            12,
            "ENERGY",
            MC,
            "Researchers are beginning to focus on butanol",
        ),
        (
            "17) LIFE SCIENCE Mutliple Choice Among adult human beings",
            17,
            "LIFE SCIENCE",
            MC,
            "Among adult human beings",
        ),
        (
            "18) MATH Math Short Answer Find the product of 111 and 89.",
            18,
            "MATH",
            SA,
            "Find the product of 111 and 89.",
        ),
        (
            "8) Physical SCIENCE Short Answer According to the laws of entropy, all",
            8,
            "Physical SCIENCE",
            SA,
            "According to the laws of entropy, all",
        ),
        (
            "2) Energy – Artificial photosynthesis is being explored as a new type of energy.",
            2,
            "Energy",
            None,
            "Artificial photosynthesis is being explored as a new type of energy.",
        ),
        (
            "6) Physics – Short Answer A particle has a position function given by x.",
            6,
            "Physics",
            SA,
            "A particle has a position function given by x.",
        ),
    ],
)
def test_real_label_variants(line, number, category, fmt, stem):
    q = one(f"TOSS-UP\n\n{line}")
    assert (q.number, q.category, q.fmt, q.stem) == (number, category, fmt, stem)


def test_title_case_stem_start_is_not_a_category():
    q = one("TOSS-UP\n\n4) Energy is conserved in which kind of collision?")
    assert (q.category, q.fmt) == (None, None)
    assert q.stem == "Energy is conserved in which kind of collision?"


def test_stem_that_starts_like_a_label_without_a_number_stays_a_stem():
    q = one("TOSS-UP\n\n5 apples cost 7 dollars. Which is a Multiple Choice question?")
    assert (q.number, q.category, q.fmt) == (None, None, None)
    assert q.stem.startswith("5 apples cost 7 dollars.")


def test_label_on_the_line_after_the_header_with_category_and_format_apart():
    q = one("TOSS-UP\n\n16) MATHEMATICS\nShort Answer What is six times three?")
    assert (q.number, q.category, q.fmt, q.stem) == (
        16,
        "MATHEMATICS",
        SA,
        "What is six times three?",
    )


# --- fragments of stacked fractions before the label -------------------------------------------


@pytest.mark.parametrize(
    "fragment",
    ["4!", "1", "x8 x 4", ") –", "(15 x + 5 y )", "− 20 x 6 y 2 z 3", "𝑥 6 − 𝑥3", "5 3", "240,000"],
)
def test_layout_fragment_between_header_and_label_is_dropped(fragment):
    q = one(f"BONUS\n\n{fragment}\n3) MATHEMATICS Short Answer Simplify the ratio.\nANSWER: 1/30\n")
    assert (q.kind, q.number, q.category, q.stem, q.answer) == (
        Kind.BONUS,
        3,
        "MATHEMATICS",
        "Simplify the ratio.",
        "1/30",
    )


def test_one_fragment_line_does_not_create_an_extra_question():
    raw = (
        "TOSS-UP\n\n1) MATH Short Answer One?\nANSWER: 1\n\nBONUS\n\n5\n2) MATH Short Answer Two?\n"
    )
    assert [(q.number, q.stem) for q in parse(raw)] == [(1, "One?"), (2, "Two?")]


# --- numbered lists inside a header-opened stem ------------------------------------------------


def test_numbered_list_after_a_blank_line_stays_in_the_stem():
    q = one(
        "BONUS\n\n7) LIFE SCIENCE Short Answer Electron transport is a series of steps. By number, "
        "put the following steps in order.\n\n"
        "1) The electron-acceptor molecule transfers the electrons to photosystem I\n"
        "2) Ferrodoxin transfers the electrons to NADP+ to form NADPH\n"
        "3) In photosystem II, light excited electrons move from chlorophyll\n\n"
        "ANSWER: 3, 1, 4, 2\n"
    )
    assert q.number == 7
    assert q.stem.endswith(
        "2) Ferrodoxin transfers the electrons to NADP+ to form NADPH 3) In "
        "photosystem II, light excited electrons move from chlorophyll"
    )
    assert q.stem.count("1) The electron-acceptor") == 1
    assert q.answer == "3, 1, 4, 2"


@pytest.mark.parametrize(
    "item",
    ["1) a square is a regular polygon", "2) an equilateral triangle is equiangular"],
)
def test_lowercase_numbered_items_are_list_text_not_labels(item):
    q = one(f"TOSS-UP\n\n13) MATH Short Answer Name all of the following statements:\n\n{item}\n")
    assert q.number == 13
    assert q.stem.endswith(item)


def test_answer_continuation_that_starts_with_a_number_is_not_a_new_question():
    raw = (
        "BONUS\n\n5) ENERGY Short Answer Rank the sources.\n\n"
        "ANSWER: SOLAR, GEOTHERMAL, WIND, BIOFUELS, HYDROPOWER (ACCEPT: 5, 1, 3, 2,\n4)\n\n"
        "Round 14 Page 9\nTOSS-UP\n\n19) PHYSICAL SCIENCE Short Answer What principle?\n"
        "ANSWER: AUFBAU\n"
    )
    first, second = parse(raw)
    assert first.answer == "SOLAR, GEOTHERMAL, WIND, BIOFUELS, HYDROPOWER (ACCEPT: 5, 1, 3, 2, 4)"
    assert (second.number, second.answer) == (19, "AUFBAU")


# --- answer line variants ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "answer"),
    [
        ("ANSWER W) 3", "W) 3"),
        ("ANSWER : Z) x − 2", "Z) x − 2"),
        ("Answer: Y) 15", "Y) 15"),
        ("ANSWER:", None),
    ],
)
def test_real_answer_marker_variants(line, answer):
    assert one(f"TOSS-UP\n\n1) MATH Short Answer How many?\n\n{line}\n").answer == answer


def test_bare_answer_marker_takes_the_next_line_even_after_a_blank_line():
    q = one("TOSS-UP\n\n12) MATH Short Answer What is ten minus six?\n\nANSWER:\n\n4\n")
    assert q.answer == "4"


def test_answer_wrapping_two_lines_with_accept_notes():
    q = one(
        "BONUS\n\n3) MATH Short Answer Which meridians?\n\n"
        "ANSWER: LONGITUDES (ACCEPT: MERIDIANS)\n\n"
        "BONUS\n\n"
    )
    assert q.answer == "LONGITUDES (ACCEPT: MERIDIANS)"


def test_answer_text_wrapped_over_two_lines_is_joined():
    q = one(
        "BONUS\n\n3) GENERAL SCIENCE Short Answer What is the cause?\n\n"
        "ANSWER: THE PULL OF GRAVITY ON THE\nOCEAN (DO NOT ACCEPT: WIND)\n"
    )
    assert q.answer == "THE PULL OF GRAVITY ON THE OCEAN (DO NOT ACCEPT: WIND)"


# --- characters from PDF extraction ------------------------------------------------------------


def test_math_italic_letters_fold_to_plain_letters():
    q = one("TOSS-UP\n\n11) MATH Short Answer If |200 − 𝑥| = 10, find 𝑥 + 12.\nANSWER: 𝑦 =\n")
    assert q.stem == "If |200 − x| = 10, find x + 12."
    assert q.answer == "y ="


def test_replacement_character_is_dropped():
    q = one("BONUS\n\n32) MATH Short Answer Simplify (6 × 107 )�6 ×1011 � in all.\n")
    assert "�" not in q.stem
    assert q.stem == "Simplify (6 × 107 ) 6 ×1011 in all."


@pytest.mark.parametrize(
    ("glyph", "plain"),
    [("\uf0b0", "°"), ("\uf071", "θ"), ("\uf02d", "−"), ("\uf0d6", "√"), ("\uf0e0", "→")],
)
def test_symbol_font_private_use_glyphs_are_mapped(glyph, plain):
    q = one(f"TOSS-UP\n\n1) MATH Short Answer What is 45{glyph} in all?\n")
    assert q.stem == f"What is 45{plain} in all?"


def test_bracket_extension_private_use_pieces_are_dropped():
    q = one("TOSS-UP\n\n1) MATH Short Answer Solve \uf8eb 5 \uf8f6 now.\n")
    assert q.stem == "Solve 5 now."


# --- choices with swapped, mistyped or mixed-case labels ---------------------------------------


def test_swapped_choice_letters_keep_the_printed_letters():
    q = one(
        "TOSS-UP\n\n5) PHYSICAL SCIENCE Multiple Choice Which of the following is NOT true?\n\n"
        "W) a pot that boils faster has the hottest water\n"
        "Y) when water changes from a gas to a liquid, energy is released\n"
        "X) condensation is opposite to evaporation\n"
        "Z) absolute zero is where all thermal motion stops\n"
    )
    assert [(c.letter, c.text[:5]) for c in q.choices] == [
        ("W", "a pot"),
        ("Y", "when "),
        ("X", "conde"),
        ("Z", "absol"),
    ]
    assert q.stem == "Which of the following is NOT true?"


def test_mistyped_first_choice_letter_is_repaired():
    q = one(
        "TOSS-UP\n\n10) ENERGY Multiple Choice Which of the following types of light bulbs is "
        "most energy\nefficient?\n\nY) Fluorescent\nX) Incandescent\nY) Halogen\nZ) White L.E.D.\n"
        "\nANSWER: Z) WHITE L.E.D.\n"
    )
    assert [(c.letter, c.text) for c in q.choices] == [
        ("W", "Fluorescent"),
        ("X", "Incandescent"),
        ("Y", "Halogen"),
        ("Z", "White L.E.D."),
    ]


def test_lowercase_first_choice_marker_with_uppercase_rest():
    q = one(
        "BONUS\n9) LIFE SCIENCE Multiple Choice Which of the following cells would typically be "
        "capable of\nthe greatest amount of phagocytosis\n\nw) plasma cells\nX) lymphocytes\n"
        "Y) mast cells\nZ) macrophages\n\nANSWER: Z) MACROPHAGES\n"
    )
    assert [c.letter for c in q.choices] == ["W", "X", "Y", "Z"]
    assert q.choices[0].text == "plasma cells"
    assert q.stem.endswith("the greatest amount of phagocytosis")


def test_title_split_over_two_lines_is_noise():
    q = one(f"High School\nSet 7\n\n{NUCLEUS}")
    assert q.number == 1


# --- guides: phonetic respellings -------------------------------------------------------------


def stem_case(text: str, label: str = "13) Physical Science – Short Answer "):
    return one(f"TOSS-UP\n\n{label}{text}")


@pytest.mark.parametrize(
    ("text", "stem", "guides"),
    [
        (
            "The net torque [tork] on an object describes the rate of change of\nwhat quantity "
            "over time?",
            "The net torque on an object describes the rate of change of what quantity over time?",
            [("torque", "tork")],
        ),
        (
            "Researchers recently developed a device that can manufacture on demand "
            "technetium-99m [tek-NEE-shee-um 99 M], a radioactive isotope with a\nhalf-life of 6 "
            "hours.",
            "Researchers recently developed a device that can manufacture on demand "
            "technetium-99m, a radioactive isotope with a half-life of 6 hours.",
            [("technetium-99m", "tek-NEE-shee-um 99 M")],
        ),
        (
            "A population occupies a\ndifferent niche [NICH] from the parent group.",
            "A population occupies a different niche from the parent group.",
            [("niche", "NICH")],
        ),
        (
            "Researchers used the SLAC [slack] Synchrotron [SINK-row-\ntrawn] Radiation Light "
            "Source.",
            "Researchers used the SLAC Synchrotron Radiation Light Source.",
            [("SLAC", "slack"), ("Synchrotron", "SINK-row-trawn")],
        ),
        (
            "Humans are part of what phylum [FYE- lum]?",
            "Humans are part of what phylum?",
            [("phylum", "FYE-lum")],
        ),
        (
            "Theodor [Tee-o-door] Schwann and Matthias Schleiden [schli-\nden] are known for:",
            "Theodor Schwann and Matthias Schleiden are known for:",
            [("Theodor", "Tee-o-door"), ("Schleiden", "schli-den")],
        ),
        (
            "The Milky Way, Andromeda, and\nMaffei 1 [MAF-eye-one] are examples of systems.",
            "The Milky Way, Andromeda, and Maffei 1 are examples of systems.",
            [("Maffei 1", "MAF-eye-one")],
        ),
        (
            "KIN10 [kin-ten], a protein kinase [KYE-nayse], is responsible for sugar.",
            "KIN10, a protein kinase, is responsible for sugar.",
            [("KIN10", "kin-ten"), ("kinase", "KYE-nayse")],
        ),
        (
            "Which would be considered an autotroph\n(read as: AW-toh-trōef)?",
            "Which would be considered an autotroph?",
            [("autotroph", "AW-toh-trōef")],
        ),
        (
            "Which kind of bond is a pi [pie] bond, respectively, in carbon dioxide?",
            "Which kind of bond is a pi bond, respectively, in carbon dioxide?",
            [("pi", "pie")],
        ),
        (
            "Identify the rock: 1) Schist, 2) Gabbro, 3) Gneiss [nice].",
            "Identify the rock: 1) Schist, 2) Gabbro, 3) Gneiss.",
            [("Gneiss", "nice")],
        ),
        (
            "The Paleocene-Eocene [PAY-lee- uh-seen EE-uh-\nseen] Thermal Maximum was an event.",
            "The Paleocene-Eocene Thermal Maximum was an event.",
            [("Paleocene-Eocene", "PAY-lee-uh-seen EE-uh-seen")],
        ),
    ],
)
def test_real_phonetic_guides_in_a_stem(text, stem, guides):
    q = stem_case(text)
    assert q.stem == stem
    assert q.respellings == tuple(Respelling(s, r, "phonetic") for s, r in guides)


@pytest.mark.parametrize(
    ("line", "text", "guide"),
    [
        ("Z) Curium-258 [KYOOR-ee-uhm]", "Curium-258", ("Curium", "KYOOR-ee-uhm")),
        ("Z) Tay-Sachs [saks] disease", "Tay-Sachs disease", ("Sachs", "saks")),
        ("Z) Joule [jool]", "Joule", ("Joule", "jool")),
        ("Z) Arachnid (read as: ah-RAHK-nid)", "Arachnid", ("Arachnid", "ah-RAHK-nid")),
        (
            "Z) radiosonde (read as: RAY-de-oh-sond) balloons",
            "radiosonde balloons",
            ("radiosonde", "RAY-de-oh-sond"),
        ),
        (
            "Z) cotyledon (PRONOUNCED: KOT-ill-ee-don)",
            "cotyledon",
            ("cotyledon", "KOT-ill-ee-don"),
        ),
    ],
)
def test_real_phonetic_guides_in_a_choice(line, text, guide):
    q = one(f"BONUS\n\n7) LIFE SCIENCE Multiple Choice Which?\nW) a\nX) b\nY) c\n{line}")
    last = q.choices[-1]
    assert last.text == text
    assert last.respellings == (Respelling(*guide, "phonetic"),)


# --- guides: spelled letters ------------------------------------------------------------------


def test_dotted_letters_after_an_acronym_are_a_spell_guide():
    q = one(
        "BONUS\n\n12) Life Science – Short Answer FAD [F.A.D.] is a cofactor derived from what "
        "vitamin?\n"
    )
    assert q.stem == "FAD is a cofactor derived from what vitamin?"
    assert q.respellings == (Respelling("FAD", "F.A.D.", "spell"),)


def test_electron_configuration_choices_keep_their_core_and_spell_guide_goes():
    q = one(
        "TOSS-UP\n\n9) CHEMISTRY Multiple Choice Which is most stable?\n\n"
        "W) [He]2s1 [H-E-2-S-1]\nX) [He]2s2 [H-E-2-S-2]\nY) [He]2s22p5 [H-E-2-S-2-P-5]\n"
        "Z) [Ne]3s2\n"
    )
    assert [c.text for c in q.choices] == ["[He]2s1", "[He]2s2", "[He]2s22p5", "[Ne]3s2"]
    assert [c.respellings for c in q.choices] == [
        (Respelling("[He]2s1", "H-E-2-S-1", "spell"),),
        (Respelling("[He]2s2", "H-E-2-S-2", "spell"),),
        (Respelling("[He]2s22p5", "H-E-2-S-2-P-5", "spell"),),
        (),
    ]


def test_spelled_letters_that_do_not_match_the_word_before_stay_text():
    q = one("TOSS-UP\n\n5) BIOLOGY Short Answer Adenosine triphosphate [A-T-P] stores energy.")
    assert q.stem == "Adenosine triphosphate [A-T-P] stores energy."
    assert q.respellings == ()


# --- guides: say-as spoken forms --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "stem", "guides"),
    [
        (
            "Convert 4 2/7 [4 and two-sevenths] to an improper fraction.",
            "Convert 4 2/7 to an improper fraction.",
            [("4 2/7", "4 and two-sevenths")],
        ),
        (
            "Find g(1) [g of 1] when g(a) = 33𝑎−2 [g of a equals 3 to the power of\nthe quantity "
            "3 a minus 2].",
            "Find g(1) when g(a) = 33a−2.",
            [
                ("g(1)", "g of 1"),
                ("g(a) = 33a−2", "g of a equals 3 to the power of the quantity 3 a minus 2"),
            ],
        ),
        (
            "If a ≠ 0 (read as: a does not equal 0), what is the multiplicative\ninverse of a?",
            "If a ≠ 0, what is the multiplicative inverse of a?",
            [("a ≠ 0", "a does not equal 0")],
        ),
        (
            "The thickness must\nsatisfy: |t – 2| ≤ 0.001 [the absolute value of the quantity t "
            "minus 2 is less than or equal to\n0.001]. What is the maximum thickness t?",
            "The thickness must satisfy: |t – 2| ≤ 0.001. What is the maximum thickness t?",
            [
                (
                    "|t – 2| ≤ 0.001",
                    "the absolute value of the quantity t minus 2 is less than or equal to 0.001",
                )
            ],
        ),
        (
            "what nitrogenous base is added to the 3’ [3 prime] end of the new RNA strand?",
            "what nitrogenous base is added to the 3’ end of the new RNA strand?",
            [("3’", "3 prime")],
        ),
        (
            "In mice, black fur B [Big B] is dominant over white fur b [little\nb]. If a bb "
            "[little B little B] mouse is crossed with a Bb [big B little b] mouse, what?",
            "In mice, black fur B is dominant over white fur b. If a bb mouse is crossed with a "
            "Bb mouse, what?",
            [
                ("B", "Big B"),
                ("b", "little b"),
                ("bb", "little B little B"),
                ("Bb", "big B little b"),
            ],
        ),
        (
            "Which equation exemplifies: CH2S + 6 F2 → (read as: yields) CF4 + 2 HF + SF6?",
            "Which equation exemplifies: CH2S + 6 F2 → CF4 + 2 HF + SF6?",
            [("→", "yields")],
        ),
        (
            "If θ [theta] is an acute angle in a right triangle, what is it?",
            "If θ is an acute angle in a right triangle, what is it?",
            [("θ", "theta")],
        ),
    ],
)
def test_real_spoken_guides_in_a_stem(text, stem, guides):
    q = stem_case(text, "24) MATH Short Answer ")
    assert q.stem == stem
    assert q.respellings == tuple(Respelling(s, r, "spoken") for s, r in guides)


def test_spoken_guide_after_a_fragment_line_and_a_header():
    q = one(
        "BONUS\n\n4!\n3) MATHEMATICS Short Answer Simplify the ratio of the following factorial: "
        "6! (read as: 4\nfactorial divided by 6 factorial)\n\nANSWER: 1/30 (ACCEPT: 0.033)\n"
    )
    assert q.number == 3
    assert q.stem == "Simplify the ratio of the following factorial: 6!"
    assert q.respellings == (Respelling("6!", "4 factorial divided by 6 factorial", "spoken"),)
    assert q.answer == "1/30 (ACCEPT: 0.033)"


def test_spoken_guides_in_choices_symbols_and_the_bare_read_as_form():
    q = one(
        "TOSS-UP\n\n13) MATH Multiple Choice Which is a number?\n\nW) π [pi]\nX) -3\nY) 53\n"
        "Z) ∅ [Null set]\n"
    )
    assert [c.text for c in q.choices] == ["π", "-3", "53", "∅"]
    assert q.choices[0].respellings == (Respelling("π", "pi", "spoken"),)
    assert q.choices[3].respellings == (Respelling("∅", "Null set", "spoken"),)
    q = one(
        "TOSS-UP\n\n12) MATH Multiple Choice Which is greater than 1:\n\n"
        "W) –(–k)3 Read as: negative - open parenthesis - negative k - closed parenthesis - to "
        "the third power\nX) a\nY) b\nZ) c\n"
    )
    assert q.choices[0].text == "–(–k)3"
    assert q.choices[0].respellings == (
        Respelling(
            "–(–k)3",
            "negative - open parenthesis - negative k - closed parenthesis - to the third power",
            "spoken",
        ),
    )


def test_yields_without_an_arrow_stays_as_a_word():
    q = one(
        "TOSS-UP\n\n6) CHEMISTRY Multiple Choice Which reaction?\n\n"
        "W) Zn + HCl [yields] ZnCl 2 + H 2\nX) a\nY) b\nZ) c\n"
    )
    assert q.choices[0].text == "Zn + HCl yields ZnCl 2 + H 2"
    assert q.choices[0].respellings == ()


# --- brackets that are not guides, and moderator notes -----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Which atom has the configuration [Ne]3s2 in its ground state?",
        "Name the complex ion [Co(NH3)6]3+ in this salt.",
        "The concentration [H+] of the solution is 0.1 M.",
        "Which is [Xe] 6s15d104f14 as a configuration?",
    ],
)
def test_real_non_guide_brackets_stay_in_the_text(text):
    q = stem_case(text, "3) CHEMISTRY Short Answer ")
    assert q.stem == text
    assert q.respellings == ()


def test_moderator_note_in_a_stem_is_dropped_but_kept_in_the_answer():
    q = one(
        "TOSS-UP\n\n25) MATH Short Answer Solve the equation |x − 2| = 3 [NOTE: STUDENTS MUST GIVE "
        "BOTH ANSWERS]\n\nANSWER: x = -1 or x = 5 [must give both answers]\n"
    )
    assert q.stem == "Solve the equation |x − 2| = 3"
    assert q.answer == "x = -1 or x = 5 [must give both answers]"


def test_note_line_after_the_answer_stays_in_the_answer():
    q = one(
        "TOSS-UP\n\n25) MATH Short Answer Solve |x − 2| = 3\n\nANSWER: x = -1 or x = 5\n\n"
        "[NOTE: STUDENTS MUST GIVE BOTH ANSWERS]\n"
    )
    assert q.answer == "x = -1 or x = 5 [NOTE: STUDENTS MUST GIVE BOTH ANSWERS]"


def test_misspelled_answer_marker_still_ends_the_choices():
    q = one(
        "TOSS-UP\n\n10) Life Science – Multiple Choice Which of the following is a vascular plant?"
        "\n\nW) Spanish moss\nX) Oak tree\nY) Green algae\nZ) Fern lichen\n\nANWER: X) OAK TREE\n"
    )
    assert q.choices[3].text == "Fern lichen"
    assert q.answer == "X) OAK TREE"


def test_empty_answer_marker_in_the_source_gives_no_answer():
    q = one(
        "BONUS\n\n16) MATH Short Answer In right triangle ABC, angle A = 60°, angle C = 90°, and "
        "side AB = 10\ncentimeters. What is the length of side BC in centimeters?\n\nANSWER:\n\n"
        "Round 17 Page 8\n"
    )
    assert q.answer is None
    assert q.stem.endswith("What is the length of side BC in centimeters?")


# --- remaining branches: separators, dash-led stems, glued letters, formula tokens -------------


@pytest.mark.parametrize(
    "line",
    [
        "3) Math – Short Answer – What is six times three?",
        "3) MATH Short Answer - What is six times three?",
    ],
)
def test_separator_after_the_format_label_is_dropped(line):
    assert one(f"TOSS-UP\n\n{line}").stem == "What is six times three?"


def test_dash_after_a_known_word_with_a_lowercase_stem_is_not_a_label():
    q = one("TOSS-UP\n\n4) Energy – the capacity to do work – is measured in what unit?")
    assert (q.category, q.fmt) == (None, None)
    assert q.stem == "Energy – the capacity to do work – is measured in what unit?"


def test_letter_glued_to_a_period_is_not_a_choice_marker():
    q = one(
        "TOSS-UP\n\n3) PHYSICS Multiple Choice Which is true of X.rays and Y:00?\n"
        "W) a\nX) b\nY) c\nZ) d\n"
    )
    assert q.stem == "Which is true of X.rays and Y:00?"
    assert [c.letter for c in q.choices] == ["W", "X", "Y", "Z"]


def test_bare_number_after_an_answer_line_starts_the_next_question():
    qs = parse("TOSS-UP\n1) MATH Short Answer One?\nANSWER: 1\n2) What is two?\nANSWER: 2\n")
    assert [(q.number, q.stem, q.answer) for q in qs] == [
        (1, "One?", "1"),
        (2, "What is two?", "2"),
    ]


def test_greek_letter_beside_latin_letters_is_part_of_the_expression():
    q = one(
        "TOSS-UP\n\n12) MATH Short Answer If tanθ = 3/4, what is the cscθ [cosecant of theta] as a "
        "fraction?"
    )
    assert q.respellings == (Respelling("cscθ", "cosecant of theta", "spoken"),)
    assert q.stem == "If tanθ = 3/4, what is the cscθ as a fraction?"


def test_operator_token_with_a_lone_variable_is_part_of_the_expression():
    q = one(
        "TOSS-UP\n\n3) MATH Multiple Choice Which is the voltage?\n"
        "W) V/d\nX) eV/d [e V over d]\nY) a\nZ) b\n"
    )
    assert q.choices[1].respellings == (Respelling("eV/d", "e V over d", "spoken"),)
    assert q.choices[1].text == "eV/d"


def test_and_or_is_a_word_not_an_expression():
    q = one("TOSS-UP\n\n3) MATH Short Answer Is it red and/or [one or the other] blue?")
    assert q.respellings == ()
    assert q.stem == "Is it red and/or [one or the other] blue?"


def test_spoken_maths_without_a_printed_expression_is_said_in_place():
    q = one(
        "TOSS-UP\n\n19) MATH Short Answer Evaluate [the fraction with numerator 12 y and "
        "denominator 5 5x x]."
    )
    assert q.stem == "Evaluate the fraction with numerator 12 y and denominator 5 5x x."
    assert q.respellings == ()


def test_unclosed_and_doubled_brackets_from_the_source_are_repaired():
    q = one(
        "TOSS-UP\n\n10) Life Science – Short Answer Beta-galactosidase [[BAY-tah gah-lac-toh-SIGH-"
        "dase] is an enzyme that cleaves what disaccharide?"
    )
    assert q.respellings == (Respelling("Beta-galactosidase", "BAY-tah gah-lac-toh-SIGH-dase"),)
    q = one(
        "TOSS-UP\n\n9) LIFE SCIENCE Multiple Choice Which is the relay station?\n\nW) Cerebrum "
        "[SEH-reh-brum]\nX) Cerebellum [seh-reh-BELL-um]\nY) Thalamus [THAL-uh-mus\nZ) Medulla\n"
    )
    assert q.choices[2].text == "Thalamus"
    assert q.choices[2].respellings == (Respelling("Thalamus", "THAL-uh-mus"),)
    assert q.choices[3].text == "Medulla"


def test_several_word_guide_with_two_stressed_syllables_and_no_hyphen():
    q = one("TOSS-UP\n\n9) LIFE SCIENCE Short Answer Cri du Chat [KREE doo SHAT] syndrome is rare.")
    assert q.respellings == (Respelling("Cri du Chat", "KREE doo SHAT"),)
    assert q.stem == "Cri du Chat syndrome is rare."


def test_explicit_read_as_accepts_any_lone_word_as_a_pronunciation():
    q = one("TOSS-UP\n\n9) EARTH SCIENCE Short Answer Name the rock gneiss (read as: NYS).")
    assert q.respellings == (Respelling("gneiss", "NYS"),)
    assert q.stem == "Name the rock gneiss."


def test_number_words_with_hyphens_are_said_not_pronounced():
    q = one("TOSS-UP\n\n9) MATH Short Answer Add 3/7 [three-sevenths] to 1/7 [one-seventh].")
    assert [(r.surface, r.respelling, r.kind) for r in q.respellings] == [
        ("3/7", "three-sevenths", "spoken"),
        ("1/7", "one-seventh", "spoken"),
    ]


@pytest.mark.parametrize(
    ("text", "stem", "surface", "spoken"),
    [
        (
            "What is the chemical formula for copper(I) [copper-one] oxide?",
            "What is the chemical formula for copper(I) oxide?",
            "copper(I)",
            "copper-one",
        ),
        (
            "How many electrons does lead (II) [lead-two] have in total?",
            "How many electrons does lead (II) have in total?",
            "lead (II)",
            "lead-two",
        ),
    ],
)
def test_oxidation_state_guide_names_the_element_and_the_number(text, stem, surface, spoken):
    q = stem_case(text, "7) CHEMISTRY Short Answer ")
    assert q.stem == stem
    assert q.respellings == (Respelling(surface, spoken, "spoken"),)


@pytest.mark.parametrize(
    ("line", "text", "guide"),
    [
        (
            "Z) chelicerae (PRONOUNCED Chill-iss-er-ah)",
            "chelicerae",
            ("chelicerae", "Chill-iss-er-ah"),
        ),
        (
            "Z) Vestigial (pronounced VES-ti-\ngee-al) structures",
            "Vestigial structures",
            ("Vestigial", "VES-ti-gee-al"),
        ),
    ],
)
def test_pronounced_wrapper_without_a_colon(line, text, guide):
    q = one(f"TOSS-UP\n\n1) LIFE SCIENCE Multiple Choice Which?\nW) a\nX) b\nY) c\n{line}")
    assert q.choices[3].text == text
    assert q.choices[3].respellings == (Respelling(*guide, "phonetic"),)


def test_header_opened_question_splits_on_the_next_consecutive_number_after_a_blank_line():
    qs = parse("TOSS-UP\n1) What is two plus two?\n\n2) What is three plus three?\n")
    assert [(q.number, q.stem) for q in qs] == [
        (1, "What is two plus two?"),
        (2, "What is three plus three?"),
    ]


def test_header_with_the_number_on_its_own_line_counts_for_the_consecutive_rule():
    qs = parse("TOSS-UP 4) What is two plus two?\n\n5) What is three plus three?\n")
    assert [q.number for q in qs] == [4, 5]


# --- surfaces must be whole words of their text (found by running normalize on the corpus) ------


def test_half_open_interval_keeps_its_bracket_and_gets_no_stray_closer():
    q = one(
        "TOSS-UP\n\n5) MATH Multiple Choice Which is the interval notation:\n\n"
        "W) (–10, 5] (read as: open parenthesis, negative 10, comma, 5, close bracket)\n"
        "X) [–10, 5] (read as: open bracket, negative 10, comma, 5, close bracket)\n"
        "Y) [–10, 5) (read as: open bracket, negative 10, comma, 5, close parenthesis)\n"
        "Z) (–10, 5) (read as: open parenthesis, negative 10, comma, 5, close parenthesis)\n"
    )
    assert [c.text for c in q.choices] == ["(–10, 5]", "[–10, 5]", "[–10, 5)", "(–10, 5)"]
    assert q.choices[2].respellings == (
        Respelling("[–10, 5)", "open bracket, negative 10, comma, 5, close parenthesis", "spoken"),
    )


@pytest.mark.parametrize(
    "text",
    [
        "Y) [–10, 5)",
        "Y) [–10, 5) (note: if student interrupts, accept: “bracket, negative or minus 10, 5 "
        "parenthesis) (Solution: bracket for numbers included in the set)",
    ],
)
def test_an_unclosed_bracket_that_holds_maths_is_left_alone(text):
    assert extract_guides(text) == (text, ())


def test_letter_glued_to_a_removed_guide_gets_a_space():
    q = one(
        "TOSS-UP\n\n15) Energy – Multiple Choice Which?\nW) a\nX) Protein crystallography cannot "
        "study ligand [LIH-gund]binding\nY) b\nZ) c\n"
    )
    assert q.choices[1].text == "Protein crystallography cannot study ligand binding"
    assert q.choices[1].respellings == (Respelling("ligand", "LIH-gund"),)


def test_hyphen_after_a_removed_guide_stays():
    q = stem_case("A ligand [LIH-gund]-binding site is shown.", "9) LIFE SCIENCE Short Answer ")
    assert q.stem == "A ligand-binding site is shown."


def test_guide_between_the_parts_of_a_compound_covers_one_part_each():
    q = one(
        "TOSS-UP\n\n9) EARTH SCIENCE Multiple Choice Which period?\nW) a\nX) b\nY) c\n"
        "Z) Ordovician [OR-doh-VIH-shin]-Silurian [sihl-UR-ee-an]\n"
    )
    assert q.choices[3].text == "Ordovician-Silurian"
    assert [(r.surface, r.respelling) for r in q.choices[3].respellings] == [
        ("Ordovician", "OR-doh-VIH-shin"),
        ("Silurian", "sihl-UR-ee-an"),
    ]


def test_guide_after_a_long_compound_covers_the_last_part():
    q = one(
        "TOSS-UP\n\n19) LIFE SCIENCE Multiple Choice A peptide sequence with the amino acid "
        "composition\nproline-glycine [GLY-seen]-glycine-tyrosine [TY-ruh-seen] would have what "
        "percentage of\naromaticity?\nW) a\nX) b\nY) c\nZ) d\n"
    )
    assert q.stem.endswith(
        "proline-glycine-glycine-tyrosine would have what percentage of aromaticity?"
    )
    assert [(r.surface, r.respelling) for r in q.respellings] == [
        ("glycine", "GLY-seen"),
        ("tyrosine", "TY-ruh-seen"),
    ]


@pytest.mark.parametrize(
    ("text", "surface", "guide"),
    [
        (
            "They study alpha-catenin\n[KAT-ah-nin] and its ability to bind.",
            "catenin",
            "KAT-ah-nin",
        ),
        ("3) Gay-Lussac's [LOO-sax].", "Lussac's", "LOO-sax"),
        ("Tay-Sachs [saks] disease is rare.", "Sachs", "saks"),
        ("Tay-Sachs [TAY-saks] disease is rare.", "Tay-Sachs", "TAY-saks"),
        ("Name the poly-hydroxy-butyrate [BYOO-tur-ate].", "butyrate", "BYOO-tur-ate"),
        (
            "Which is sub-bituminous [sub-by-TYUH-mi-nuhs] coal?",
            "sub-bituminous",
            "sub-by-TYUH-mi-nuhs",
        ),
        ("Name D-alanine [AL-n-een].", "alanine", "AL-n-een"),
        ("Name the Saffir-Simpson [SAH-fur-SIMP-sun] scale.", "Saffir-Simpson", "SAH-fur-SIMP-sun"),
    ],
)
def test_compound_headword_is_the_part_the_guide_has_syllables_for(text, surface, guide):
    q = stem_case(text, "9) PHYSICAL SCIENCE Short Answer ")
    assert q.respellings == (Respelling(surface, guide),)


def test_a_marker_like_token_is_never_the_surface_of_a_say_as_guide():
    assert extract_guides("Y) 6 (read as: six)") == ("Y) 6", (Respelling("6", "six", "spoken"),))


# --- the last "(read as: ..." leftovers of the corpus -----------------------------------------


@pytest.mark.parametrize(
    ("line", "text", "guide"),
    [
        (
            "Z) Herbivore (read as: (H)URR-bi-vohr)",
            "Herbivore",
            ("Herbivore", "HURR-bi-vohr"),
        ),
        ("Z) Breccia (read as: BREH-ch(ee)ah)", "Breccia", ("Breccia", "BREH-cheeah")),
        (
            "Z) Nucleolus (read as: n(y)uh-KLEE-oh-lus)",
            "Nucleolus",
            ("Nucleolus", "nyuh-KLEE-oh-lus"),
        ),
        (
            "Z) Amphiboles (read as: AHM(P)-fi-bōels)",
            "Amphiboles",
            ("Amphiboles", "AHMP-fi-bōels"),
        ),
    ],
)
def test_an_optional_sound_in_parentheses_is_part_of_the_respelling(line, text, guide):
    q = one(f"TOSS-UP\n\n7) LIFE SCIENCE Multiple Choice Which?\nW) a\nX) b\nY) c\n{line}")
    assert q.choices[3].text == text
    assert q.choices[3].respellings == (Respelling(*guide, "phonetic"),)


def test_optional_sound_guide_in_a_stem_with_a_following_word_and_a_wrapped_hyphen():
    q = stem_case(
        "What is the most stable isotope of rutherfordium (read as: ruh-the(r)-\nFOHR-dee-uhm)?",
        "7) PHYSICAL SCIENCE Short Answer ",
    )
    assert q.stem == "What is the most stable isotope of rutherfordium?"
    assert q.respellings == (Respelling("rutherfordium", "ruh-ther-FOHR-dee-uhm"),)


@pytest.mark.parametrize(
    ("text", "stem"),
    [
        (
            "Simplify (read as: one third divided by one sixth)",
            "Simplify one third divided by one sixth",
        ),
        (
            "Express (read as: open parenthesis one fifth plus 3.4 close 2 parenthesis divided by "
            "two) as a fraction in lowest terms.",
            "Express open parenthesis one fifth plus 3.4 close 2 parenthesis divided by two as a "
            "fraction in lowest terms.",
        ),
        (
            "What is the center of the hyperbola (read as: the quantity x minus 3 squared over 25 "
            "minus the quantity y plus 1 squared over 49 equals 1)?",
            "What is the center of the hyperbola the quantity x minus 3 squared over 25 minus the "
            "quantity y plus 1 squared over 49 equals 1?",
        ),
        (
            "Evaluate: (read as: 10 factorial over the quantity 8 factorial times 8!3! 3 "
            "factorial).",
            "Evaluate: 10 factorial over the quantity 8 factorial times 8!3! 3 factorial.",
        ),
        ("the item (read as: x squared plus two x) was", "the item x squared plus two x was"),
        ("the item (read as: 1) was", "the item 1 was"),
    ],
)
def test_read_as_with_no_printed_expression_is_said_in_place(text, stem):
    q = stem_case(text, "20) MATH Short Answer ")
    assert q.stem == stem
    assert q.respellings == ()


def test_unit_word_after_the_expression_stays_out_of_the_surface():
    q = stem_case(
        "The radius of the Earth is approximately 6.4 x 106 meters (read as: 6.4 times 10 to the "
        "sixth). Giving your answer in scientific notation, what is it?",
        "11) MATH Short Answer ",
    )
    assert q.stem == (
        "The radius of the Earth is approximately 6.4 x 106 meters. Giving your answer in "
        "scientific notation, what is it?"
    )
    assert q.respellings == (Respelling("6.4 x 106", "6.4 times 10 to the sixth", "spoken"),)


def test_bare_read_as_whose_opening_parenthesis_was_lost_is_still_a_guide():
    q = stem_case(
        "What is the asymptote of the hyperbola -‐ = 1 25 49 read as: the quantity x minus 3 "
        "squared over 25 equals 1)?",
        "24) MATH Short Answer ",
    )
    assert q.stem == "What is the asymptote of the hyperbola -‐ = 1 25 49?"
    assert q.respellings == (
        Respelling("-‐ = 1 25 49", "the quantity x minus 3 squared over 25 equals 1", "spoken"),
    )


def test_read_as_whose_closing_parenthesis_was_lost_is_still_a_guide():
    q = stem_case(
        "Which of the following points lies on the curve with equation y = 2x3 |5x | + 3 (read as: "
        "y equals 2 x cubed minus the absolute value of 5 x plus 3?",
        "21) MATH Multiple Choice ",
    )
    assert (
        q.stem == "Which of the following points lies on the curve with equation y = 2x3 |5x | + 3?"
    )
    assert q.respellings == (
        Respelling(
            "y = 2x3 |5x | + 3",
            "y equals 2 x cubed minus the absolute value of 5 x plus 3",
            "spoken",
        ),
    )


def test_a_read_as_label_with_nothing_after_it_is_left_alone():
    assert extract_guides("Which is it? Read as:") == ("Which is it? Read as:", ())
    assert extract_guides("Which is it? Read as: )") == ("Which is it? Read as: )", ())


# --- review findings 1-3: answers that must stay silent, questions that must stay apart --------

LIFE_NO_NEWLINES = (
    "1) LIFE SCIENCE Multiple Choice Which is NOT part of the respiratory system? "
    "W) Pharynx X) Larynx Y) Esophagus Z) Trachea {marker} Y) ESOPHAGUS"
)


@pytest.mark.parametrize("marker", ["Answer:", "ANSWER:", "Answer :", "ANSWER：", "Answer："])
def test_inline_answer_marker_after_lost_newlines_ends_the_choices(marker):
    q = one(LIFE_NO_NEWLINES.format(marker=marker))
    assert q.answer == "Y) ESOPHAGUS"
    assert [c.text for c in q.choices] == ["Pharynx", "Larynx", "Esophagus", "Trachea"]


@pytest.mark.parametrize(
    "raw",
    [
        "TOSS-UP 1) PHYSICS Short Answer: What is a joule?",
        "1) PHYSICS Multiple Choice Short Answer: what unit? W) a X) b Y) c Z) d",
        "1) MATH Short answer: How many sides has a hexagon?",
    ],
)
def test_short_answer_label_is_not_an_inline_answer_marker(raw):
    q = one(raw)
    assert q.answer is None
    assert q.fmt is not None


@pytest.mark.parametrize(
    ("raw", "answer"),
    [
        (
            "1) PHYSICS Short Answer Give the SI base unit for each: 1) length; 2) mass; "
            "3) temperature; 4) time.\nANSWER: 1) LENGTH = METER, 2) MASS = KILOGRAM, "
            "3) TEMPERATURE = KELVIN,\n4) TIME = SECOND",
            "1) LENGTH = METER, 2) MASS = KILOGRAM, 3) TEMPERATURE = KELVIN, 4) TIME = SECOND",
        ),
        (
            "5) CHEMISTRY Short Answer Name two alkali metals.\nANSWER:\n1) SODIUM\n2) POTASSIUM",
            "1) SODIUM 2) POTASSIUM",
        ),
        (
            "TOSS-UP\n5) CHEMISTRY Multiple Choice Which?\nW) a\nX) b\nY) c\nZ) d\n"
            "ANSWER: Y) c\n1) because of the first reason\n2) because of the second reason",
            "Y) c 1) because of the first reason 2) because of the second reason",
        ),
    ],
)
def test_numbered_lines_after_the_answer_marker_stay_in_the_answer(raw, answer):
    q = one(raw)
    assert q.answer == answer


def test_next_consecutive_number_after_an_answer_still_starts_a_question():
    qs = parse("1) MATH Short Answer One?\nANSWER: 1\n2) What is two?\nANSWER: 2\n")
    assert [(q.number, q.answer) for q in qs] == [(1, "1"), (2, "2")]


def test_blank_line_then_any_number_after_an_answer_starts_a_question():
    qs = parse("3) MATH Short Answer Three?\nANSWER: 3\n\n7) What is seven?\nANSWER: 7\n")
    assert [(q.number, q.answer) for q in qs] == [(3, "3"), (7, "7")]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "EARTH SCIENCE Short Answer What is the outermost layer of the Earth?\n"
            "ANSWER: CRUST\n\n"
            "LIFE SCIENCE Short Answer What organelle makes ATP?\nANSWER: MITOCHONDRION",
            [(None, "EARTH SCIENCE", "CRUST"), (None, "LIFE SCIENCE", "MITOCHONDRION")],
        ),
        (
            "46 MATH Short Answer What is two plus two?\nANSWER: 4\n"
            "47 MATH Short Answer What is three plus three?\nANSWER: 6",
            [(46, "MATH", "4"), (47, "MATH", "6")],
        ),
        (
            "1) CHEMISTRY Short Answer What is the unit of energy?\nANSWER: JOULE\n\n"
            "2) pH is a measure of what property of a solution?\nANSWER: ACIDITY",
            [(1, "CHEMISTRY", "JOULE"), (2, None, "ACIDITY")],
        ),
        (
            "TOSS-UP\n1) BIOLOGY Multiple Choice Which?\nW) a\nX) b\nY) c\nZ) d\n\n"
            "PHYSICS Short Answer What is a joule?\nANSWER: UNIT OF ENERGY",
            [(1, "BIOLOGY", None), (None, "PHYSICS", "UNIT OF ENERGY")],
        ),
    ],
)
def test_every_pasted_question_is_its_own_question(raw, expected):
    qs = parse(raw)
    assert [(q.number, q.category, q.answer) for q in qs] == expected


def test_label_words_alone_after_an_answer_do_not_open_a_question():
    q = one("1) MATH Short Answer Name the format.\nANSWER: MULTIPLE CHOICE\nSHORT ANSWER")
    assert q.answer == "MULTIPLE CHOICE SHORT ANSWER"


def test_lowercase_numbered_list_in_an_open_stem_is_still_text():
    q = one("1) MATH Short Answer Name all of the following:\n\n1) a square\n2) a circle\n")
    assert q.stem.endswith("1) a square 2) a circle")


def test_lowercase_numbered_line_right_after_an_answer_stays_in_the_answer():
    q = one(
        "1) CHEMISTRY Short Answer What is the unit of energy?\nANSWER: JOULE\n"
        "2) because it is named for a physicist"
    )
    assert q.answer == "JOULE 2) because it is named for a physicist"


# --- review findings 4-7: surfaces of guides --------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "surface", "spoken"),
    [
        (
            "TOSS-UP\n\n2) MATH Multiple Choice Express in decimal form: 0.99 - (read as: 99 "
            "hun-DREDTHS minus\nthree fourths).\n",
            "0.99 -",
            "99 hun-DREDTHS minus three fourths",
        ),
        (
            "BONUS\n\n2) MATH Short Answer Simplify: 0.99 - 0.0099 (read as: 99 hun-DREDTHS minus "
            "99 ten\nthous-ANDTHS).\n",
            "0.99 - 0.0099",
            "99 hun-DREDTHS minus 99 ten thous-ANDTHS",
        ),
    ],
)
def test_spoken_reading_holding_a_respelled_word_is_a_say_as_guide(raw, surface, spoken):
    q = one(raw)
    assert q.respellings == (Respelling(surface, spoken, "spoken"),)
    assert surface in q.stem


def test_a_dangling_dash_is_never_the_surface_of_a_guide():
    q = stem_case("Take foo - (read as: FOO-bar) now.", "9) MATH Short Answer ")
    assert q.respellings == (Respelling("foo", "FOO-bar"),)
    assert q.stem == "Take foo - now."


@pytest.mark.parametrize(
    ("written", "text", "surface", "guide"),
    [
        ("Curium-258 [KYOOR-ee-uhm]", "Curium-258", "Curium", "KYOOR-ee-uhm"),
        ("L-alanine and D-alanine [AL-n-een]", "L-alanine and D-alanine", "alanine", "AL-n-een"),
        (
            "a non-Newtonian [noo-TOH-nee-un] fluid",
            "a non-Newtonian fluid",
            "Newtonian",
            "noo-TOH-nee-un",
        ),
        (
            "The Bence-Jones [BENS JOHNZ] protein",
            "The Bence-Jones protein",
            "Bence-Jones",
            "BENS JOHNZ",
        ),
        (
            "N-acetylglucosamine [N-ah-setil-glue-KOH-sah-meen]",
            "N-acetylglucosamine",
            "N-acetylglucosamine",
            "N-ah-setil-glue-KOH-sah-meen",
        ),
        (
            "technetium-99m [tek-NEE-shee-um 99 M]",
            "technetium-99m",
            "technetium-99m",
            "tek-NEE-shee-um 99 M",
        ),
        ("Tay-Sachs [TAY-saks] disease", "Tay-Sachs disease", "Tay-Sachs", "TAY-saks"),
        ("Tay-Sachs [saks] disease", "Tay-Sachs disease", "Sachs", "saks"),
        ("Hypotenuse-leg [hy-POT-n-oos]", "Hypotenuse-leg", "Hypotenuse", "hy-POT-n-oos"),
    ],
)
def test_a_compound_keeps_every_part_the_guide_does_not_respell(written, text, surface, guide):
    q = one(f"TOSS-UP\n\n7) CHEMISTRY Multiple Choice Which?\nW) a\nX) b\nY) c\nZ) {written}")
    assert q.choices[3].text == text
    assert q.choices[3].respellings == (Respelling(surface, guide),)


def test_determinant_matrix_is_not_a_unit_so_the_two_by_two_is_not_a_surface():
    q = one(
        "TOSS-UP\n\n−5 3\n10) MATH Short Answer What is the determinant of the 2 by 2 matrix � � "
        "[first row\n4 2\nnegative 5, 3 and second row 4, 2]?\n\nANSWER: -22\n"
    )
    assert q.respellings == ()
    assert q.stem == (
        "What is the determinant of the 2 by 2 matrix first row 4 2 negative 5, 3 and second row "
        "4, 2?"
    )


@pytest.mark.parametrize(
    ("text", "stem", "guides"),
    [
        (
            "approximately 5 meters (read as: five)",
            "approximately 5 meters five",
            (),
        ),
        (
            "about 6.4 x 106 meters (read as: 6.4 times 10 to the sixth) in all",
            "about 6.4 x 106 meters in all",
            (Respelling("6.4 x 106", "6.4 times 10 to the sixth", "spoken"),),
        ),
        (
            "of a 2 by 2 matrix (read as: two by two)",
            "of a 2 by 2 matrix two by two",
            (),
        ),
    ],
)
def test_only_a_real_unit_word_may_sit_between_an_expression_and_its_reading(text, stem, guides):
    q = stem_case(text, "11) MATH Short Answer ")
    assert (q.stem, q.respellings) == (stem, guides)


@pytest.mark.parametrize(
    ("raw", "text", "surface", "guide"),
    [
        (
            "5) EARTH AND SPACE Short Answer Which atmospheric element is converted into a\n"
            "bioavailable form through the Haber-Bosch process [HA-buhr BOSH]?\n",
            None,
            "Haber-Bosch",
            "HA-buhr BOSH",
        ),
        (
            "8) EARTH AND SPACE Short Answer What is the name for igneous rock [IG-nee-uhs] that "
            "cuts across the structure of adjoining rock?\n",
            None,
            "igneous",
            "IG-nee-uhs",
        ),
        (
            "TOSS-UP\n\n9) EARTH AND SPACE Multiple Choice Which?\nW) Kuiper Belt [KY-per]\n"
            "X) Oort Cloud\nY) c\nZ) d\n",
            "Kuiper Belt",
            "Kuiper",
            "KY-per",
        ),
    ],
)
def test_guide_attaches_to_the_word_it_respells_not_to_the_noun_after_it(raw, text, surface, guide):
    q = one(raw if raw.startswith(("TOSS", "BONUS")) else f"TOSS-UP\n\n{raw}")
    found = q.choices[0] if text else q
    assert found.respellings == (Respelling(surface, guide),)
    if text:
        assert found.text == text
    else:
        assert "process" in q.stem or "rock" in q.stem


@pytest.mark.parametrize(
    ("text", "surface", "guide"),
    [
        ("A self--made [self-MAYD] man", "self--made", "self-MAYD"),
        ("Grade A-1 [AY-wun] beef", "A-1", "AY-wun"),
    ],
)
def test_compound_without_a_usable_part_keeps_the_whole_token(text, surface, guide):
    q = stem_case(text, "3) MATH Short Answer ")
    assert q.respellings == (Respelling(surface, guide),)


def test_brackets_alone_before_a_reading_are_not_a_headword():
    q = stem_case("( ) (read as: FOO-bar) is odd.", "3) MATH Short Answer ")
    assert [r.kind for r in q.respellings] == ["spoken"]


# --- delta review: an answer list must survive any open question number -----------------------


@pytest.mark.parametrize("n", [1, 2, 5])
def test_numbered_answer_list_survives_any_open_question_number(n):
    q = one(
        f"TOSS-UP\n{n}) CHEMISTRY Short Answer Name the alkali metals.\nANSWER:\n"
        "1) SODIUM\n2) POTASSIUM\n3) LITHIUM"
    )
    assert q.number == n
    assert q.answer == "1) SODIUM 2) POTASSIUM 3) LITHIUM"


@pytest.mark.parametrize(
    "answer",
    [
        "ANSWER: 1) LENGTH = METER, 2) MASS = KILOGRAM,\n3) TEMPERATURE = KELVIN,\n"
        "4) TIME = SECOND",
        "ANSWER:\n1) Sodium\n2) Potassium\n3) Lithium",
        "ANSWER: THE LAWS OF MOTION ARE THREE\n2) NEWTON'S SECOND LAW STATES THAT FORCE EQUALS "
        "MASS TIMES ACCELERATION",
    ],
)
def test_short_or_all_caps_numbered_lines_stay_in_the_answer_at_any_number(answer):
    for n in (1, 2, 3):
        q = one(f"TOSS-UP\n{n}) PHYSICS Short Answer Name them.\n{answer}")
        assert q.answer == " ".join(answer.removeprefix("ANSWER:").split())


@pytest.mark.parametrize(
    "second",
    [
        "7) What is seven?",
        "2) Name the first prime number",
        "2) Which gas is a measure of what property of a solution?",
    ],
)
def test_a_line_that_reads_like_a_question_right_after_an_answer_starts_one(second):
    qs = parse(f"3) MATH Short Answer Three?\nANSWER: 3\n{second}\nANSWER: 7\n")
    assert [q.answer for q in qs] == ["3", "7"]
    assert qs[1].stem == second.split(") ", 1)[1]
