"""speak_formulas: chemical formulas, ions, scientific notation and exponents to words.

Conventions pinned here (they also satisfy tests/golden/spoken_cases.yaml):
- Element symbols are spelled as upper-case letters (Na -> "N A"), counts as number words.
- Parentheses in a formula are "open parenthesis" / "close parenthesis".
- A charge is its number word then plus/minus ("Ca2+" -> "C A two plus"); charge 1 has no number.
- Positive exponents are ordinals ("to the twenty-third"), negative ones "to the minus <cardinal>".
- A formula is NEVER replaced by a name (rule R5): the output holds letters and number words only.
"""

from __future__ import annotations

import re

import pytest

from cloudyreader.formulas import speak_formulas
from cloudyreader.units import load_entries, speak_units

MINUS = "−"
EN_DASH = "\u2013"
PRIVATE_USE = "\uf0e0"
REPLACEMENT = "\ufffd"
ITALIC_X = "\U0001d465"


def both(text: str) -> str:
    """The pipeline order: units first, then formulas."""
    return speak_formulas(speak_units(text))


FORMULAS = [
    ("H2O", "H two O"),
    ("CO2", "C O two"),
    ("H2SO4", "H two S O four"),
    ("NaCl", "N A C L"),
    ("HCl", "H C L"),
    ("NaOH", "N A O H"),
    ("KOH", "K O H"),
    ("CaO", "C A O"),
    ("CaS", "C A S"),
    ("C6H12O6", "C six H twelve O six"),
    ("C12H22O11", "C twelve H twenty-two O eleven"),
    ("NaHCO3", "N A H C O three"),
    ("CH3COOH", "C H three C O O H"),
    ("O2", "O two"),
    ("N2", "N two"),
    ("O3", "O three"),
    ("H5N1", "H five N one"),
    # Parentheses convention: spoken out loud, so Ca(OH)2 is never confused with CaOH2.
    ("Ca(OH)2", "C A open parenthesis O H close parenthesis two"),
    ("Al2(SO4)3", "A L two open parenthesis S O four close parenthesis three"),
    ("CO", "C O"),
]


@pytest.mark.parametrize(("raw", "spoken"), FORMULAS)
def test_formulas(raw: str, spoken: str) -> None:
    assert speak_formulas(raw) == spoken


@pytest.mark.parametrize(("raw", "spoken"), FORMULAS)
def test_formula_keeps_surrounding_text_and_punctuation(raw: str, spoken: str) -> None:
    assert speak_formulas(f"Water, {raw}, has") == f"Water, {spoken}, has"
    assert speak_formulas(f"is {raw}.") == f"is {spoken}."


IONS = [
    ("Na+", "N A plus"),
    ("Cl-", "C L minus"),
    (f"Cl{MINUS}", "C L minus"),
    ("OH-", "O H minus"),
    ("H+", "H plus"),
    ("Fe3+", "F E three plus"),
    ("Ca2+", "C A two plus"),
    ("NH4+", "N H four plus"),
    ("H3O+", "H three O plus"),
    ("SO4 2-", "S O four two minus"),
    ("SO4^2-", "S O four two minus"),
    ("SO42-", "S O four two minus"),
    ("CO32-", "C O three two minus"),
    ("Cr2O72-", "C R two O seven two minus"),
    ("PO4^3-", "P O four three minus"),
    ("Ba²⁺", "B A two plus"),
    ("SO₄²⁻", "S O four two minus"),
    ("BaSO₄", "B A S O four"),
    ("Mg^{2+}", "M G two plus"),
    # Wrong ions the questions use as distractors are spoken as written.
    ("Na-", "N A minus"),
    ("Cl+", "C L plus"),
    ("Na2+", "N A two plus"),
    ("Cl2-", "C L two minus"),
]


@pytest.mark.parametrize(("raw", "spoken"), IONS)
def test_ions(raw: str, spoken: str) -> None:
    assert speak_formulas(raw) == spoken
    assert speak_formulas(f"the ion {raw} and") == f"the ion {spoken} and"


def test_ion_pair_from_a_choice() -> None:
    assert speak_formulas("Na+ and Cl-") == "N A plus and C L minus"
    assert speak_formulas("Na+ and Cl2-") == "N A plus and C L two minus"


def test_polyatomic_ion_with_a_trailing_period() -> None:
    text = "Give the name of the polyatomic ion SO4 2-."
    assert speak_formulas(text) == "Give the name of the polyatomic ion S O four two minus."


REACTIONS = [
    ("N2 + 3H2 ⇌ 2NH3", "N two plus three H two is in equilibrium with two N H three"),
    ("2H2 + O2 → 2H2O", "two H two plus O two yields two H two O"),
    ("2 NaCl → 2 Na + Cl2", "2 N A C L yields 2 N A plus C L two"),
    ("A → products", "A yields products"),
    ("NO + O3 → NO2 + O2", "N O plus O three yields N O two plus O two"),
    ("N + H ⇌ NH", "N plus H is in equilibrium with N H"),
    ("H2 + O2 -> H2O", "H two plus O two yields H two O"),
    ("Zn + 2 H+ → Zn2+ + H2", "Z N plus 2 H plus yields Z N two plus plus H two"),
]


@pytest.mark.parametrize(("raw", "spoken"), REACTIONS)
def test_reactions(raw: str, spoken: str) -> None:
    assert speak_formulas(raw) == spoken


# Ordinary words and acronyms made of element symbols are not formulas.
NOT_FORMULAS = [
    "As",
    "He said it",
    "In",
    "No",
    "I",
    "US",
    "Be",
    "At",
    "HOW many are there",
    "WHICH of these IS correct",
    "ALL OF THE ABOVE",
    "NO net change",
    "IN",
    "P- and S-waves",
    "N- and C-terminal ends",
    "As-is and In-depth",
    "H-bond and O-ring",
    "pH is 7",
    "mRNA and tRNA",
    "HIV, DNA and ATP",
    "X-ray and 5K run",
    "Vitamin A1 and Q10",
    "Pb-206 decays",
    "the P450 enzyme",
    "see [1] for more",
    "Fe is iron",
    "Mercury and Hg",
]


@pytest.mark.parametrize("text", NOT_FORMULAS)
def test_ordinary_words_are_left_alone(text: str) -> None:
    assert speak_formulas(text) == text


SCIENTIFIC = [
    ("6.02 × 10^23", "six point oh two times ten to the twenty-third"),
    ("6.02 x 10^23", "six point oh two times ten to the twenty-third"),
    ("6.02 times 10^23", "six point oh two times ten to the twenty-third"),
    ("1.6 × 10^-19", "one point six times ten to the minus nineteen"),
    (f"1.6 × 10^{MINUS}19", "one point six times ten to the minus nineteen"),
    ("1.6 × 10⁻¹⁹", "one point six times ten to the minus nineteen"),
    ("9.1 × 10^-31", "nine point one times ten to the minus thirty-one"),
    ("1 × 10^-7", "one times ten to the minus seven"),
    ("3.00 × 10^8", "three point oh oh times ten to the eighth"),
    ("2 × 10^2", "two times ten to the second"),
    ("2 × 10^3", "two times ten to the third"),
    ("10^-3", "ten to the minus three"),
    ("10^23", "ten to the twenty-third"),
]


@pytest.mark.parametrize(("raw", "spoken"), SCIENTIFIC)
def test_scientific_notation(raw: str, spoken: str) -> None:
    assert speak_formulas(raw) == spoken


EXPONENTS = [
    ("x^2", "x squared"),
    ("x^3", "x cubed"),
    ("x^4", "x to the fourth"),
    ("x^n", "x to the n"),
    ("ax^2", "a x squared"),
    ("b^2", "b squared"),
    ("(a+b)^2", "(a+b) squared"),
    ("s^-1", "s to the minus one"),
    ("2^10", "two to the tenth"),
    ("e^(-kt)", "e to the power of (-kt)"),
    ("x²", "x squared"),
]


@pytest.mark.parametrize(("raw", "spoken"), EXPONENTS)
def test_exponents(raw: str, spoken: str) -> None:
    assert speak_formulas(raw) == spoken


RATIOS = [
    ("L/g", "L over g"),
    ("(L/g)", "(L over g)"),
    ("v/c", "v over c"),
    ("(x + 1) / 2a", "(x plus 1) over 2a"),
    ("N/A", "N/A"),
    ("and/or", "and/or"),
    ("km/h", "km/h"),
]


@pytest.mark.parametrize(("raw", "spoken"), RATIOS)
def test_ratios(raw: str, spoken: str) -> None:
    assert speak_formulas(raw) == spoken


BRACKETS = [
    ("[H+]", "H plus"),
    ("[OH-]", "O H minus"),
    ("[Ca2+]", "C A two plus"),
    ("the concentration [Ca2+].", "the concentration C A two plus."),
    ("rate = k[A]. If", "rate = k A. If"),
    ("[NH3]^2", "N H three squared"),
    ("K = [NH3]^2 / ([N2][H2]^3)", "K = N H three squared over (N two times H two cubed)"),
]


@pytest.mark.parametrize(("raw", "spoken"), BRACKETS)
def test_concentration_brackets(raw: str, spoken: str) -> None:
    assert speak_formulas(raw) == spoken


def test_number_word_base_is_not_spelled_letter_by_letter() -> None:
    # Regression: "H2^3" becomes "H two^3"; the base "two" must not turn into "t w o".
    assert speak_formulas("[H2]^3") == "H two cubed"
    assert speak_formulas("[NH3]^2") == "N H three squared"


def test_footnote_brackets_are_not_ours() -> None:
    assert speak_formulas("The Reef [1] is large") == "The Reef [1] is large"


def test_electron_and_dot_in_hydrates() -> None:
    assert speak_formulas("Cu2+ + 2e-") == "C U two plus plus 2 e minus"
    assert speak_formulas("e- and e+") == "e minus and e plus"
    assert speak_formulas("CuSO4·5H2O") == "C U S O four dot five H two O"


def test_e_dash_inside_words_is_not_an_electron() -> None:
    assert speak_formulas("e-mail and re-enter") == "e-mail and re-enter"


# Rule R5: entity resolution only picks HOW a token is said. A formula is never swapped for a
# substance name, so the answer ("baking soda", "water", "salt") is never leaked.
R5_CASES = {
    "NaHCO3": ["baking", "soda", "bicarbonate", "sodium"],
    "H2O": ["water", "hydrogen", "oxygen"],
    "NaCl": ["salt", "sodium", "chloride"],
    "C6H12O6": ["glucose", "sugar", "carbon"],
    "CO2": ["carbon", "dioxide"],
    "Ca(OH)2": ["lime", "calcium", "hydroxide"],
    "H2SO4": ["sulfuric", "acid", "sulphuric"],
    "SO4 2-": ["sulfate", "sulphate"],
    "Fe3+": ["iron", "ferric"],
    "NH3": ["ammonia", "nitrogen"],
}


@pytest.mark.parametrize(("formula", "names"), R5_CASES.items())
def test_formula_is_never_replaced_by_a_name(formula: str, names: list[str]) -> None:
    spoken = speak_formulas(f"The compound {formula} is common.").lower()
    for name in names:
        assert name not in spoken
    # Only the surrounding prose is lower case; the formula itself is letters and number words.
    body = speak_formulas(formula)
    assert re.fullmatch(r"[A-Za-z -]+", body)


def test_every_element_symbol_speaks_as_its_letters() -> None:
    elements = load_entries("elements")
    assert len(elements) == 118
    for symbol, entry in elements.items():
        assert speak_formulas(f"{symbol}2") == f"{entry['spoken_symbol']} two"
        assert entry["spoken_symbol"].isupper()


def test_unit_symbols_that_look_like_formulas_stay_units() -> None:
    # GeV is Ge + V and TeV is Te + V, but after a number they are units (units run first).
    assert speak_formulas("7 TeV") == "7 TeV"
    assert both("7 TeV") == "7 tera electron volts"
    assert both("2 GeV") == "2 giga electron volts"


# Real PDF artifacts from the sample rounds. The exponent is flattened into the base.
FLATTENED_EXPONENTS = [
    ("4.56 × 1011", "four point five six times ten to the eleventh"),
    ("6 × 103", "six times ten to the third"),
    ("6.023 × 1023", "six point oh two three times ten to the twenty-third"),
    ("6 ×1011", "six times ten to the eleventh"),
    ("5 × 1014", "five times ten to the fourteenth"),
    (
        f"0.000328 × 10{EN_DASH}6",
        "zero point oh oh oh three two eight times ten to the minus six",
    ),
    (f"3.28 × 10{EN_DASH}10", "three point two eight times ten to the minus ten"),
    (f"8 × 10{MINUS}3", "eight times ten to the minus three"),
    ("7.5 × 10-14", "seven point five times ten to the minus fourteen"),
    (
        "The number 4.56 × 1011 has how many zeroes?",
        "The number four point five six times ten to the eleventh has how many zeroes?",
    ),
    ("about 4 × 105.", "about four times ten to the fifth."),
]


@pytest.mark.parametrize(("raw", "spoken"), FLATTENED_EXPONENTS)
def test_flattened_exponents(raw: str, spoken: str) -> None:
    assert speak_formulas(raw) == spoken
    assert both(raw) == spoken  # units run first and must leave the exponent sign alone


# No mantissa, or digits that start with zero: an ordinary number.
NOT_EXPONENTS = [
    "2 × 1000",
    "30 × 100",
    "5 × 10",
    "2 × 1005",
    "10A × 6B",
    "6 × 10 apples",
    f"3 × 10 {EN_DASH} 4",
    "the year 1066",
]


@pytest.mark.parametrize("text", NOT_EXPONENTS)
def test_numbers_that_only_look_like_exponents_are_left_alone(text: str) -> None:
    assert speak_formulas(text) == text


def test_flattened_exponent_after_a_unit_pass() -> None:
    assert both("6.4 × 106 m") == "six point four times ten to the sixth meters"
    assert both("2 × 1000 m") == "2 times 1000 meters"


# Isotopes start like ions ("Cl-36", "I-131"): a digit after the sign means no charge.
ISOTOPES = [
    "Cl-36",
    "I-131",
    "F-18",
    "Cs-137",
    "C-14",
    "Sr-90",
    "Pb-206",
    f"Cl{MINUS}36",
    f"I{EN_DASH}131",
    "Br-82 decays",
    "P-32 and S-35",
]


@pytest.mark.parametrize("text", ISOTOPES)
def test_isotope_notation_is_not_an_ion(text: str) -> None:
    assert speak_formulas(text) == text
    assert both(text) == text


def test_the_same_symbols_are_ions_without_the_digits() -> None:
    assert speak_formulas("Cl- ions and I- ions") == "C L minus ions and I minus ions"
    assert speak_formulas("F- and Br-") == "F minus and B R minus"
    assert speak_formulas("Ca^+2 and SO4^-2 and Fe^{3+}") == (
        "C A two plus and S O four two minus and F E three plus"
    )


# Spaced subscripts through the formula stage, from real excerpts.
SPACED = [
    ("H 2 O", "H two O"),
    ("C 6 H 12 O 2", "C six H twelve O two"),
    ("CO 2", "C O two"),
    ("the sulfate ion, SO 4 2-?", "the sulfate ion, S O four two minus?"),
    ("NH 3", "N H three"),
    ("Fe 2 O 3", "F E two O three"),
    ("CH 3 OH", "C H three O H"),
    ("NO 2 molecules", "N O two molecules"),
    ("Ca(OH) 2", "C A open parenthesis O H close parenthesis two"),
    ("Mg(NO 3 ) 2", "M G open parenthesis N O three close parenthesis two"),
    (
        "2C 4 H 10 + 13O 2 → 8CO 2 + 10H 2 O",
        "two C four H ten plus thirteen O two yields eight C O two plus ten H two O",
    ),
    ("ANSWER: OXYGEN (ACCEPT: O 2 )", "ANSWER: OXYGEN (ACCEPT: O two )"),
    ("which has the formula N 2 O?", "which has the formula N two O?"),
    ("What is the IUPAC name of AgNO 3 ?", "What is the IUPAC name of A G N O three ?"),
]


@pytest.mark.parametrize(("raw", "spoken"), SPACED)
def test_spaced_subscripts(raw: str, spoken: str) -> None:
    assert speak_formulas(raw) == spoken
    assert both(raw) == spoken


def test_boyles_law_subscripts() -> None:
    assert speak_formulas("P 1 V 1 = P 2 V 2") == "P one V one = P two V two"
    assert both("P 1 V 1 = P 2 V 2") == "P one V one equals P two V two"


@pytest.mark.parametrize(
    "text",
    [
        "OF 2",
        "ANSWER: IF N IS A MULTIPLE OF 2, THEN N + 1",
        "IN 3.2 SECONDS",
        "In 6 years from now",
        "Na 25 mg",
        "I 2 hours",
        "Middle School Round 7 Page 8",
    ],
)
def test_prose_next_to_a_number_is_not_spelled(text: str) -> None:
    # The formula stage adds nothing to what the unit stage already said.
    assert both(text) == speak_units(text)
    assert not any(part in both(text) for part in ("N A ", "I N ", "O F "))


def test_hydrate_bullet_is_a_dot() -> None:
    assert speak_formulas("MgSO4•7H2O") == "M G S O four dot seven H two O"
    assert speak_formulas("CuSO4·5H2O") == "C U S O four dot five H two O"
    assert both("or MgSO4•7H2O (read as") == "or M G S O four dot seven H two O (read as"
    # A list bullet is not a hydrate dot.
    assert speak_formulas("• Item one") == "• Item one"
    assert speak_formulas("5 • 3") == "5 • 3"


STATE_SYMBOLS = [
    ("Cu(s)", "C U solid"),
    ("2K(s) + 2H2O(l) → 2KOH(aq) + H2(g)", ""),
    ("CuSO4(aq)", "C U S O four aqueous"),
    ("AgCl (s)", "A G C L solid"),
    ("NaNO 3(aq)", "N A N O three aqueous"),
    ("CUSO4(AQ) + 2NAOH(AQ)", "C U S O four aqueous + 2NAOH(AQ)"),
    ("Na+(aq) and Cl-(aq)", "N A plus aqueous and C L minus aqueous"),
]


@pytest.mark.parametrize(("raw", "spoken"), [c for c in STATE_SYMBOLS if c[1]])
def test_state_symbols_are_words(raw: str, spoken: str) -> None:
    assert speak_formulas(raw).replace(" plus ", " + ") == spoken.replace(" plus ", " + ")


def test_state_symbols_in_a_full_equation() -> None:
    assert speak_formulas("2K(s) + 2H2O(l) → 2KOH(aq) + H2(g)") == (
        "two K solid plus two H two O liquid yields two K O H aqueous plus H two gas"
    )


@pytest.mark.parametrize(
    "text",
    ["answer(s) are due", "the (S)-isomer and (R)-isomer", "In (s) the", "word(l)", "pick(g) one"],
)
def test_state_symbol_lookalikes_are_untouched(text: str) -> None:
    assert speak_formulas(text) == text


def test_bracketed_bare_element_is_spelled_not_read_as_a_word() -> None:
    assert speak_formulas("[He]2s22p2") == "H E 2s22p2"
    assert speak_formulas("[Ar]3d10") == "A R 3d10"
    assert speak_formulas("[A] and [H]") == "A and H"


def test_syllable_of_a_hyphenated_respelling_is_not_a_formula() -> None:
    assert speak_formulas("my-OH-sis") == "my-OH-sis"
    assert speak_formulas("[my-OH-sis]?") == "[my-OH-sis]?"
    assert speak_formulas("OH- ions") == "O H minus ions"
    assert speak_formulas("the OH group") == "the O H group"


def test_scientific_e_notation_is_not_an_electron() -> None:
    for text in ["1e-3", "6.02e+23", "e-mail", "re-enter", "e-commerce"]:
        assert speak_formulas(text) == text


def test_private_use_and_replacement_glyphs_are_left_alone() -> None:
    assert speak_formulas(f"H2O{PRIVATE_USE}") == f"H two O{PRIVATE_USE}"
    assert speak_formulas(f"{PRIVATE_USE} x {REPLACEMENT}") == f"{PRIVATE_USE} x {REPLACEMENT}"
    assert speak_formulas(f"x^2{PRIVATE_USE}") == f"x squared{PRIVATE_USE}"


def test_math_italics_fold_to_plain_letters() -> None:
    assert speak_formulas(f"{ITALIC_X}^2") == "x squared"
    assert both(f"{ITALIC_X} = 5") == "x equals 5"


def test_no_spaced_formula_is_ever_named() -> None:
    spoken = both("ANSWER: WATER (ACCEPT: H 2 O) and CO 2 and NaCl").lower()
    for name in ["hydrogen", "oxygen", "dioxide", "carbon", "sodium", "chloride", "salt"]:
        assert name not in spoken


def test_speak_formulas_is_idempotent() -> None:
    text = "Ca(OH)2 and H2SO4 give Ca2+ and SO4 2-, so [H+] rises to 6.02 × 10^23 per x^2."
    once = speak_formulas(text)
    assert speak_formulas(once) == once


# Golden spoken_cases.yaml: stems after the header, through the pipeline order units -> formulas.
GOLDEN_STEMS = [
    (
        "Water, H2O, has a bent molecular geometry. What type of intermolecular force is "
        "primarily responsible for its unusually high boiling point?",
        "Water, H two O, has a bent molecular geometry. What type of intermolecular force is "
        "primarily responsible for its unusually high boiling point?",
    ),
    (
        "Carbon dioxide, CO2, is a major greenhouse gas. Which layer of Earth's atmosphere "
        "contains most of its CO2 and nearly all of its weather?",
        "Carbon dioxide, C O two, is a major greenhouse gas. Which layer of Earth's atmosphere "
        "contains most of its C O two and nearly all of its weather?",
    ),
    (
        "Cellular respiration oxidizes glucose, C6H12O6, to produce CO2, H2O, and ATP.",
        "Cellular respiration oxidizes glucose, C six H twelve O six, to produce C O two, "
        "H two O, and ATP.",
    ),
    (
        "When solid NaCl dissolves in water, which of the following pairs of ions is produced?",
        "When solid N A C L dissolves in water, which of the following pairs of ions is produced?",
    ),
    (
        "Gypsum is a mineral built from Ca2+ and SO4 2- ions along with water of hydration. "
        "Give the name of the polyatomic ion SO4 2-.",
        "Gypsum is a mineral built from C A two plus and S O four two minus ions along with "
        "water of hydration. Give the name of the polyatomic ion S O four two minus.",
    ),
    (
        "What are the products of the complete neutralization of Ca(OH)2 with H2SO4?",
        "What are the products of the complete neutralization of C A open parenthesis O H close "
        "parenthesis two with H two S O four?",
    ),
    (
        "Ethene reacts with chlorine gas, Cl2, to produce 1,2-dichloroethane.",
        "Ethene reacts with chlorine gas, C L two, to produce 1,2-dichloroethane.",
    ),
    (
        "Avogadro's number is approximately 6.02 × 10^23 per mole. Approximately how many "
        "helium atoms are in 0.5 mole of helium gas?",
        "Avogadro's number is approximately six point oh two times ten to the twenty-third per "
        "mole. Approximately how many helium atoms are in 0.5 mole of helium gas?",
    ),
    (
        "A 2 kg block is accelerated at 3 m/s^2 by a single net force.",
        "A 2 kilograms block is accelerated at 3 meters per second squared by a single net force.",
    ),
    (
        "One electron volt, eV, is approximately equal to how many joules?",
        "One electron volt, electron volts, is approximately equal to how many joules?",
    ),
    (
        "1.6 × 10^-19 and 1.6 × 10^-10 and 6.02 × 10^23 and 9.1 × 10^-31",
        "one point six times ten to the minus nineteen and one point six times ten to the minus "
        "ten and six point oh two times ten to the twenty-third and nine point one times ten "
        "to the minus thirty-one",
    ),
    (
        f"According to the first law of thermodynamics, ΔU = Q {MINUS} W. If a gas absorbs 500 "
        "joules of heat, what is ΔU, in joules?",
        "According to the first law of thermodynamics, delta U equals Q minus W. If a gas "
        "absorbs 500 joules of heat, what is delta U, in joules?",
    ),
    (
        "The period of a simple pendulum is T = 2π√(L/g). If the length L is quadrupled",
        "The period of a simple pendulum is T equals 2 pi square root of (L over g). If the "
        "length L is quadrupled",
    ),
    (
        f"Which gives the solutions of x^2 {MINUS} 5x + 6 = 0?",
        "Which gives the solutions of x squared minus 5x plus 6 equals 0?",
    ),
    (
        f"x = {MINUS}2 and x = {MINUS}3",
        "x equals minus 2 and x equals minus 3",
    ),
    (
        f"The solutions of ax^2 + bx + c = 0 are given by "
        f"x = ({MINUS}b ± √(b^2 {MINUS} 4ac)) / 2a. "
        f"What is the common name for the quantity b^2 {MINUS} 4ac?",
        "The solutions of a x squared plus bx plus c equals 0 are given by x equals (minus b "
        "plus or minus square root of (b squared minus 4ac)) over 2a. What is the common name "
        "for the quantity b squared minus 4ac?",
    ),
    (
        f"The standard enthalpy change, ΔH, is approximately {MINUS}890 kJ/mol. What word "
        "describes any reaction that has a negative ΔH?",
        "The standard enthalpy change, delta H, is approximately minus 890 kilojoules per "
        "mole. What word describes any reaction that has a negative delta H?",
    ),
    (
        "temperature of about 5800 K. According to the law",
        "temperature of about 5800 kelvins. According to the law",
    ),
    (
        "have a band gap of about 1.1 eV. What word describes a material",
        "have a band gap of about 1.1 electron volts. What word describes a material",
    ),
    (
        "A sample of gas is at a temperature of 300 K. What is this temperature in °C, rounded "
        "to the nearest whole number?",
        "A sample of gas is at a temperature of 300 kelvins. What is this temperature in "
        "degrees Celsius, rounded to the nearest whole number?",
    ),
    (
        "What is the pH of a neutral aqueous solution at 25 °C?",
        "What is the pH of a neutral aqueous solution at 25 degrees Celsius?",
    ),
    (
        "N2 + 3H2 ⇌ 2NH3",
        "N two plus three H two is in equilibrium with two N H three",
    ),
    (
        "K = [NH3]^2 / ([N2][H2]^3)",
        "K equals N H three squared over (N two times H two cubed)",
    ),
    (
        "In pure water at 25 °C, the concentrations [H+] and [OH-] are equal. What is the value "
        "of [H+], in mol/L, to one significant figure?",
        "In pure water at 25 degrees Celsius, the concentrations H plus and O H minus are equal. "
        "What is the value of H plus, in moles per liter, to one significant figure?",
    ),
    (
        "releases Ca2+ and raises the cytosolic concentration [Ca2+]. To which",
        "releases C A two plus and raises the cytosolic concentration C A two plus. To which",
    ),
    (
        "For the first-order reaction A → products, the rate law is rate = k[A]. If the "
        "concentration [A] is doubled",
        "For the first-order reaction A yields products, the rate law is rate equals k A. If "
        "the concentration A is doubled",
    ),
    (
        "Barium ions, Ba²⁺, react with SO₄²⁻ ions in solution to form BaSO₄.",
        "Barium ions, B A two plus, react with S O four two minus ions in solution to form "
        "B A S O four.",
    ),
    (
        "Which of these is NOT part of 2 H+ and Na- and Cl+?",
        "Which of these is NOT part of 2 H plus and N A minus and C L plus?",
    ),
]


@pytest.mark.parametrize(("raw", "spoken"), GOLDEN_STEMS)
def test_golden_stems_through_the_pipeline(raw: str, spoken: str) -> None:
    assert both(raw) == spoken


# None of the raw symbols the golden file forbids may survive the pipeline.
FORBIDDEN_RAW = ["^", "×", "±", "√", "π", "Δ", "⇌", "→", "°", "²", "⁺", "⁻", "₄", "[", "]"]


@pytest.mark.parametrize(("raw", "_"), GOLDEN_STEMS)
def test_no_raw_symbol_survives(raw: str, _: str) -> None:
    out = both(raw)
    for symbol in FORBIDDEN_RAW:
        assert symbol not in out
    assert "  " not in out


@pytest.mark.parametrize(
    "text",
    [
        "A 2 kg block is accelerated at 3 m/s^2 by a single net force.",
        "temperature of about 5800 K. According to the law",
        "a band gap of about 1.1 eV.",
        "Avogadro's number is approximately 6.02 × 10^23 per mole.",
        "N2 + 3H2 ⇌ 2NH3",
        "Water, H2O, has a bent geometry.",
    ],
)
def test_order_does_not_matter_for_the_common_cases(text: str) -> None:
    assert speak_units(speak_formulas(text)) == speak_formulas(speak_units(text))
