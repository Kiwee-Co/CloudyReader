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


ACRONYMS = [
    ("ATP", "A T P"),
    ("ADP and AMP", "A D P and A M P"),
    ("GTP", "G T P"),
    ("DNA", "D N A"),
    ("RNA", "R N A"),
    ("mRNA", "m R N A"),
    ("tRNA", "t R N A"),
    ("rRNA", "r R N A"),
    ("cAMP", "c A M P"),
    ("NADH", "N A D H"),
    ("NADPH", "N A D P H"),
    ("PCR", "P C R"),
    ("HIV", "H I V"),
    ("UV light", "U V light"),
    ("CFC", "C F C"),
    ("LED", "L E D"),
    ("DNA's helix", "D N A's helix"),
    ("DNA-binding", "D N A-binding"),
    ("HIV, DNA and ATP", "H I V, D N A and A T P"),
    # A plural keeps the letter's apostrophe so the engine says "pees", not "P s".
    ("ATPs", "A T P's"),
    ("LEDs", "L E D's"),
    # The oxidized coenzymes carry a charge.
    ("NAD+", "N A D plus"),
    ("NADP+", "N A D P plus"),
]


@pytest.mark.parametrize(("raw", "spoken"), ACRONYMS)
def test_acronyms_are_spelled(raw: str, spoken: str) -> None:
    assert speak_formulas(raw) == spoken
    assert both(raw) == spoken


LETTERS_AND_DIGITS = [
    ("BRCA1", "B R C A one"),
    ("TP53", "T P fifty-three"),
    ("CD4", "C D four"),
    ("SAR11", "S A R eleven"),
    ("PRC2", "P R C two"),
    ("CA1", "C A one"),
    ("FE2", "F E two"),
    ("G3P", "G three P"),
    ("E3SM", "E three S M"),
    ("AK47", "A K forty-seven"),
    ("WW2", "W W two"),
    ("MP3", "M P three"),
]


@pytest.mark.parametrize(("raw", "spoken"), LETTERS_AND_DIGITS)
def test_capitals_with_digits_are_spelled_with_number_words(raw: str, spoken: str) -> None:
    assert speak_formulas(raw) == spoken
    assert both(raw) == spoken


def test_a_charge_after_capitals_and_digits_is_spoken() -> None:
    assert speak_formulas("FE2+ and NH4+") == "F E two plus and N H four plus"
    assert speak_formulas("PRC2") == "P R C two"


def test_a_syllable_of_a_respelling_is_not_an_acronym() -> None:
    assert speak_formulas("core-UN-dum") == "core-UN-dum"
    assert speak_formulas("UV-B and DNA-binding") == "U V-B and D N A-binding"
    assert speak_formulas("anti-DNA antibodies") == "anti-D N A antibodies"


def test_p_protein_names() -> None:
    assert speak_formulas("p53") == "p fifty-three"
    assert speak_formulas("p21") == "p twenty-one"
    assert speak_formulas("the p53 protein") == "the p fifty-three protein"
    assert speak_formulas("p53-dependent") == "p fifty-three-dependent"


GENE_SYMBOLS = (
    "CFTR HBB DMD APOE HTT MYC KRAS HRAS NRAS EGFR PTEN SRY ACTB GAPDH LDLR HEXA VHL ABO".split()
)


@pytest.mark.parametrize("symbol", GENE_SYMBOLS)
def test_gene_symbols_are_spelled(symbol: str) -> None:
    assert speak_formulas(f"the {symbol} gene") == f"the {' '.join(symbol)} gene"


# Ordinary words, words made of capitals, names with a digit and pH are not spelled.
NOT_ACRONYMS = [
    "US",
    "IS",
    "OF",
    "HOW",
    "NO",
    "NOT",
    "ANSWER",
    "THE",
    "TOSS-UP",
    "BONUS",
    "NASA",
    "LASER",
    "COVID19",
    "pH",
    "Vitamin A1 and Q10",
    "the P450 enzyme",
    "mp3 and p. 53",
    "p5 and p530 and pp53",
    "p value",
    "Page 3 of 12",
]


@pytest.mark.parametrize("text", NOT_ACRONYMS)
def test_ordinary_words_are_not_spelled_as_acronyms(text: str) -> None:
    assert speak_formulas(text) == text


# R5: an acronym or gene symbol is said as letters, never swapped for what it stands for.
R5_ACRONYMS = {
    "ATP": ["adenosine", "triphosphate", "energy"],
    "DNA": ["deoxyribonucleic", "acid", "genetic"],
    "TP53": ["tumor", "suppressor", "protein"],
    "BRCA1": ["breast", "cancer"],
    "NADH": ["nicotinamide", "dinucleotide"],
    "PCR": ["polymerase", "chain", "reaction"],
    "CFTR": ["cystic", "fibrosis", "regulator"],
    "p53": ["tumor", "guardian"],
}


@pytest.mark.parametrize(("symbol", "names"), R5_ACRONYMS.items())
def test_acronym_is_never_replaced_by_a_name(symbol: str, names: list[str]) -> None:
    spoken = both(symbol).lower()
    for name in names:
        assert name not in spoken
    assert re.fullmatch(r"[A-Za-z' -]+", both(symbol))


# The six golden cases that need acronym spelling (05, 07, 08, 09, 12 and 45).
ACRONYM_GOLDEN = [
    (
        "During DNA replication, which enzyme joins the Okazaki fragments into a strand?",
        "During D N A replication, which enzyme joins the Okazaki fragments into a strand?",
    ),
    (
        "Mutations in the gene TP53, which encodes the protein p53, are found in cancers. "
        "What term describes the cell death that p53 can trigger?",
        "Mutations in the gene T P fifty-three, which encodes the protein p fifty-three, are "
        "found in cancers. What term describes the cell death that p fifty-three can trigger?",
    ),
    (
        "ATP synthase uses a gradient of which ion to drive the phosphorylation of ADP?",
        "A T P synthase uses a gradient of which ion to drive the phosphorylation of A D P?",
    ),
    (
        "Which organelle is the main site of ATP production in eukaryotic cells?",
        "Which organelle is the main site of A T P production in eukaryotic cells?",
    ),
    ("BRCA1", "B R C A one"),
    ("CFTR", "C F T R"),
    ("HBB", "H B B"),
    ("DMD", "D M D"),
]


@pytest.mark.parametrize(("raw", "spoken"), ACRONYM_GOLDEN)
def test_golden_acronym_cases(raw: str, spoken: str) -> None:
    assert both(raw) == spoken


# Real excerpts: PDF text flattens "x squared" to "x2" and "(x - 5) squared" to "(x - 5)2".
FLAT_POWERS = [
    ("x2 + 3y", "x squared plus 3y"),
    (f"(x {EN_DASH} 5)2", "(x minus 5) squared"),
    (f"5x2 {EN_DASH} x {EN_DASH} 12yz2 + 9", "5 x squared minus x minus 12 y z squared plus 9"),
    ("9xy2 + 4", "9 x y squared plus 4"),
    ("4πr2", "4 pi r squared"),
    ("x3", "x cubed"),
    ("x4", "x to the fourth"),
    ("E=mc2", "E equals m c squared"),
    ("(a + b)2", "(a plus b) squared"),
    ("f(x)2", "f(x) squared"),
    # Real excerpts with h as a variable: "2h" is not two hours, and "x2 close" is not prose.
    (f"h2 + 2h {EN_DASH} 120", "h squared plus 2h minus 120"),
    ("6h = 36 + n", "6h equals 36 plus n"),
    (
        f"open parenthesis 36 {EN_DASH} x2 close parenthesis",
        "open parenthesis 36 minus x squared close parenthesis",
    ),
]


@pytest.mark.parametrize(("raw", "spoken"), FLAT_POWERS)
def test_flattened_powers(raw: str, spoken: str) -> None:
    assert both(raw) == spoken
    assert both(spoken) == spoken


# Names with a digit, subscript pairs, a bare 1, and an answer note keep the digit.
@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("x1 and x2", "x1 and x2"),
        ("(x1, y1) and (x2, y2)", "(x1, y1) and (x2, y2)"),
        ("a1 and a2", "a1 and a2"),
        ("G1 and G2", "G1 and G2"),
        ("F2 generation", "F two generation"),
        ("Q10 and KIN10", "Q10 and K I N ten"),
        ("mp3 and p53x", "mp3 and p53x"),
        ("x1", "x1"),
        ("(Solution: x2 + 3)", "(Solution: x2 plus 3)"),
        ("(1)2 and (see Figure 1)2", "(1)2 and (see Figure 1)2"),
        (
            "Ca(OH)2 and (NH4)2SO4",
            "C A open parenthesis O H close parenthesis two and "
            "open parenthesis N H four close parenthesis two S O four",
        ),
    ],
)
def test_digits_that_are_not_powers_stay(raw: str, spoken: str) -> None:
    assert both(raw) == spoken


# Item 2: a size is "N by M". The same token with no such noun is a power ("ANSWER: 4x4" is 4x^4).
@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("a 2x2 matrix", "a 2 by 2 matrix"),
        ("a 3x3 Punnett square", "a 3 by 3 Punnett square"),
        ("a 4x4 grid", "a 4 by 4 grid"),
        ("a 10x10 board", "a 10 by 10 board"),
        ("2X2 table", "2 by 2 table"),
        ("two 2x3 matrices", "two 2 by 3 matrices"),
        ("the 3x3 magic square", "the 3 by 3 magic square"),
        # A bare "square" takes no dimensions: these are 4x^2 and 9x^2.
        ("Is 4x2 a perfect square?", "Is 4 x squared a perfect square?"),
        ("Is 9x2 a perfect square trinomial?", "Is 9 x squared a perfect square trinomial?"),
        # No dimension noun: a power, as before.
        ("ANSWER: 4x4", "ANSWER: 4 x to the fourth"),
        ("2x2 + 3x", "2 x squared plus 3x"),
        ("a 2x2 plus 3x matrix", "a 2 x squared plus 3x matrix"),
    ],
)
def test_a_size_is_not_a_power(raw: str, spoken: str) -> None:
    assert both(raw) == spoken


def test_poh_is_spelled_because_the_voice_drops_its_h() -> None:
    # Measured through the Piper voice: "pOH" came out "pee oh". "pH" and NSB, STP, NMR, CSF,
    # TNT and CCC are already read letter by letter, so they stay as written.
    assert speak_formulas("What is the pOH?") == "What is the p O H?"
    for text in ["pH", "NSB", "STP", "NMR", "CSF", "TNT", "CCC"]:
        assert speak_formulas(text) == text


# A dash flattened into a power of ten is the exponent's sign. The last four are real corpus lines
# (Round-10A #239, Round-9A choices, Round-17A answer).
TEN_POWERS = [
    (f"Kw = 10{EN_DASH}14", "Kw equals ten to the minus fourteen"),
    (f"[H+] = 10{EN_DASH}3 M", "H plus equals ten to the minus three molar"),
    (f"pH = {EN_DASH}log 10{EN_DASH}3", "pH equals minus log ten to the minus three"),
    (f"10{EN_DASH}3 = 0.001", "ten to the minus three equals 0.001"),
    (f"Kw = 10{EN_DASH}14.", "Kw equals ten to the minus fourteen."),
    (f"Kw = 10{MINUS}14", "Kw equals ten to the minus fourteen"),
    (
        f"the concentration of hydroxide ions is 10 {EN_DASH}4 molar?",
        "the concentration of hydroxide ions is ten to the minus four molar?",
    ),
    (f"10 {EN_DASH}16", "ten to the minus sixteen"),
    (f"10 {EN_DASH}13", "ten to the minus thirteen"),
    (f"10 {EN_DASH}10", "ten to the minus ten"),
    (f"10 {EN_DASH}7", "ten to the minus seven"),
    (f"ANSWER: 10 {EN_DASH}16", "ANSWER: ten to the minus sixteen"),
    (f"10 {MINUS}7", "ten to the minus seven"),
    (f"[H+] = 10{EN_DASH}12 M", "H plus equals ten to the minus twelve molar"),
]


@pytest.mark.parametrize(("raw", "spoken"), TEN_POWERS)
def test_a_flattened_power_of_ten_with_a_negative_exponent(raw: str, spoken: str) -> None:
    assert both(raw) == spoken
    assert both(spoken) == spoken


# A range beside a range word, a subtraction with spaces, and a hyphen range stay as written.
@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        (f"ages 10{EN_DASH}14", f"ages 10{EN_DASH}14"),
        (f"10{EN_DASH}15 minutes", f"10{EN_DASH}15 minutes"),
        (f"grades 10{EN_DASH}12", f"grades 10{EN_DASH}12"),
        (f"between 10{EN_DASH}14 and 20", f"between 10{EN_DASH}14 and 20"),
        # A tight 10-N with no cue (N of two digits, no "=", no unit) is a range, not 10^-N.
        (f"pH 10{EN_DASH}12", f"pH 10{EN_DASH}12"),
        (
            f"Questions 10{EN_DASH}12 refer to the graph.",
            f"Questions 10{EN_DASH}12 refer to the graph.",
        ),
        (f"Store it at 10{EN_DASH}15 °C.", f"Store it at 10{EN_DASH}15 degrees Celsius."),
        (f"It grows 10{EN_DASH}12 cm long.", f"It grows 10{EN_DASH}12 centimeters long."),
        (f"10 {EN_DASH} 4", f"10 {EN_DASH} 4"),
        ("10-14 days", "10-14 days"),
        (f"10 {EN_DASH} 4 = 6", "10 minus 4 equals 6"),
        (f"3.28 × 10{EN_DASH}10", "three point two eight times ten to the minus ten"),
    ],
)
def test_ranges_and_subtractions_beside_a_ten_stay(raw: str, spoken: str) -> None:
    assert both(raw) == spoken


def test_equations_with_a_wingdings_arrow_and_a_fraction_slash() -> None:
    grave_a, slash = "\u00e0", "\u2044"
    assert both(f"reaction: 2CaO {grave_a} 2Ca + O2") == (
        "reaction: two C A O yields two C A plus O two"
    )
    assert both(f"Mg + ZnBr2 {grave_a} Zn + MgBr2") == (
        "M G plus Z N B R two yields Z N plus M G B R two"
    )
    assert both(f"(3 times the square root of 3) {slash} 4") == (
        "(3 times the square root of 3) over 4"
    )


def test_a_word_after_a_charge_word_is_not_a_formula_on_a_second_pass() -> None:
    once = speak_formulas("CONCENTRATION OF H+ IONS)")
    assert once == "CONCENTRATION OF H plus IONS)"
    assert speak_formulas(once) == once
    # An equation partner of up to three symbols is still spelled.
    assert speak_formulas("NO + O3 → NO2 + O2") == "N O plus O three yields N O two plus O two"
    assert speak_formulas("KOH + HCl") == "K O H plus H C L"


def test_speak_formulas_is_idempotent() -> None:
    text = (
        "Ca(OH)2 and H2SO4 give Ca2+ and SO4 2-, so [H+] rises to 6.02 × 10^23 per x^2. "
        "NAD+ makes ATPs; TP53, p53 and mRNA stay letters. Cu(s) + HCl(aq) technetium-99m"
    )
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
        "H two O, and A T P.",
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
