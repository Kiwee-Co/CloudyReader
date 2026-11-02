"""speak_units: quantities and math symbols to words, driven by data/units.json and symbols.json."""

from __future__ import annotations

import pytest

from cloudyreader.units import (
    Symbol,
    Tables,
    UnitName,
    cardinal,
    collapse_spaced_formulas,
    decimal_words,
    fold_compat,
    normalize_scripts,
    ordinal,
    prepare_text,
    speak_symbols,
    speak_units,
)

MINUS = "−"


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "zero"),
        (7, "seven"),
        (12, "twelve"),
        (20, "twenty"),
        (23, "twenty-three"),
        (100, "one hundred"),
        (101, "one hundred one"),
        (890, "eight hundred ninety"),
        (1000, "one thousand"),
        (5800, "five thousand eight hundred"),
        (1_000_000, "one million"),
        (-3, "minus three"),
    ],
)
def test_cardinal(n: int, words: str) -> None:
    assert cardinal(n) == words


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (1, "first"),
        (2, "second"),
        (3, "third"),
        (4, "fourth"),
        (5, "fifth"),
        (8, "eighth"),
        (9, "ninth"),
        (12, "twelfth"),
        (20, "twentieth"),
        (21, "twenty-first"),
        (23, "twenty-third"),
        (31, "thirty-first"),
        (100, "one hundredth"),
        (101, "one hundred first"),
    ],
)
def test_ordinal(n: int, words: str) -> None:
    assert ordinal(n) == words


@pytest.mark.parametrize(
    ("number", "words"),
    [
        ("6.02", "six point oh two"),
        ("0.5", "zero point five"),
        ("3.00", "three point oh oh"),
        ("1,000", "one thousand"),
        ("9.1", "nine point one"),
        ("10", "ten"),
    ],
)
def test_decimal_words(number: str, words: str) -> None:
    assert decimal_words(number) == words


@pytest.mark.parametrize(
    ("raw", "ascii_text"),
    [
        ("m/s²", "m/s^2"),
        ("10⁻¹⁹", "10^-19"),
        ("SO₄²⁻", "SO4^2-"),
        ("Ba²⁺", "Ba^2+"),
        ("plain text", "plain text"),
    ],
)
def test_normalize_scripts(raw: str, ascii_text: str) -> None:
    assert normalize_scripts(raw) == ascii_text


QUANTITIES = [
    ("5 m/s", "5 meters per second"),
    ("1 m/s", "1 meter per second"),
    ("9.8 m/s^2", "9.8 meters per second squared"),
    ("9.8 m/s²", "9.8 meters per second squared"),
    ("37 °C", "37 degrees Celsius"),
    ("37°C", "37 degrees Celsius"),
    ("1 °C", "1 degree Celsius"),
    ("98.6 °F", "98.6 degrees Fahrenheit"),
    ("890 kJ/mol", "890 kilojoules per mole"),
    (f"{MINUS}890 kJ/mol", "minus 890 kilojoules per mole"),
    ("2.5 g/mL", "2.5 grams per milliliter"),
    ("1 g/mL", "1 gram per milliliter"),
    ("10 μm", "10 micrometers"),
    ("10 µm", "10 micrometers"),
    ("100 Ω", "100 ohms"),
    ("100 Ω", "100 ohms"),
    ("1.1 eV", "1.1 electron volts"),
    ("1 eV", "1 electron volt"),
    ("2 atm", "2 atmospheres"),
    ("5 ppm", "5 parts per million"),
    ("5800 K", "5800 kelvins"),
    ("2 kg", "2 kilograms"),
    ("0.5 mol", "0.5 moles"),
    ("1 mol", "1 mole"),
    ("5 min", "5 minutes"),
    ("1 h", "1 hour"),
    ("3 s", "3 seconds"),
    ("2 M HCl", "2 molar HCl"),
    ("50%", "50 percent"),
    ("90°", "90 degrees"),
    ("a 10-mL sample", "a 10-milliliter sample"),
    ("1,000 m", "1,000 meters"),
    ("5m", "5 meters"),
    ("3 A", "3 amperes"),
    ("2 N", "2 newtons"),
    ("154 pm", "154 picometers"),
    ("5 kPa.", "5 kilopascals."),
    # Regression: a sentence-final unit followed by a capitalised word is not an initial.
    ("about 5800 K. According to", "about 5800 kelvins. According to"),
    ("at 300 K. What is", "at 300 kelvins. What is"),
    ("7 TeV", "7 tera electron volts"),
    # R5: the symbol is spoken as letters, never as a substance name (mercury).
    ("760 mmHg", "760 millimeters of H G"),
    ("1.6 × 10^-19 J", "1.6 times 10^-19 joules"),
    ("1.6 × 10⁻¹⁹ J", "1.6 times 10^-19 joules"),
]


@pytest.mark.parametrize(("raw", "spoken"), QUANTITIES)
def test_quantities(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken


def test_plural_follows_the_number_not_the_symbol() -> None:
    assert speak_units("A 2 kg block at 3 m/s^2.") == (
        "A 2 kilograms block at 3 meters per second squared."
    )


# Attached single letters, decades, time of day and plain words are not units.
UNTOUCHED = [
    "He said 5 or more",
    "The 2N cell divides",
    "Only 3A matters here",
    "During the 1960s it grew",
    "Meet at 5 pm.",
    "Draw a bar graph with min and max",
    "Shown in bar charts",
    "Cl- and Br- ions",
    "In 1915 W. H. Bragg won",
    "Meet at 11:30 pm.",
    "The L/g ratio",
    "x is 2 times y",
]


@pytest.mark.parametrize("text", UNTOUCHED)
def test_not_a_unit_is_left_alone(text: str) -> None:
    assert speak_units(text) == text


def test_ion_with_coefficient_is_not_henries() -> None:
    out = speak_units("Zn + 2 H+ → Zn2+ + H2")
    assert "2 H+" in out
    assert "henr" not in out


BARE = [
    ("What is the value, in mol/L, to one", "What is the value, in moles per liter, to one"),
    ("One electron volt, eV, is", "One electron volt, electron volts, is"),
    ("temperature in °C, rounded", "temperature in degrees Celsius, rounded"),
    ("the mass in kg of it", "the mass in kilograms of it"),
    ("energy in K here", "energy in kelvins here"),
    ("joules per kg of water", "joules per kilogram of water"),
    ("a wavelength in nm", "a wavelength in nanometers"),
    ("a pressure of kPa units", "a pressure of kilopascals units"),
]


@pytest.mark.parametrize(("raw", "spoken"), BARE)
def test_bare_unit_symbols(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken


SYMBOLS = [
    ("a ± b", "a plus or minus b"),
    ("x ≤ 5", "x is less than or equal to 5"),
    ("x ≥ 5", "x is greater than or equal to 5"),
    (f"ΔU = Q {MINUS} W", "delta U equals Q minus W"),
    ("T = 2π", "T equals 2 pi"),
    ("√144", "square root of 144"),
    ("6 ÷ 3", "6 divided by 3"),
    ("2 × 3", "2 times 3"),
    ("an angle of 30° here", "an angle of 30 degrees here"),
    (f"x = {MINUS}2", "x equals minus 2"),
    (f"({MINUS}b ± d)", "(minus b plus or minus d)"),
    ("α-helix", "alpha-helix"),
    ("A → B", "A yields B"),
    ("N2 + 3H2 ⇌ 2NH3", "N2 plus 3H2 is in equilibrium with 2NH3"),
    ("x^2 + 5x + 6", "x^2 plus 5x plus 6"),
    ("2+3", "2 plus 3"),
    ("a +x", "a plus x"),
    ("→ Cu(OH)2(s) +Na2SO4(aq)", "yields Cu(OH)2(s) plus Na2SO4(aq)"),
    ("x -> y", "x yields y"),
    ("a < b", "a is less than b"),
    ("π.", "pi."),
]


@pytest.mark.parametrize(("raw", "spoken"), SYMBOLS)
def test_symbols(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken
    assert speak_symbols(raw) == spoken


# Charges stay attached for the formula pass; exponent signs stay too.
SYMBOL_BYSTANDERS = [
    "Na+ and Cl-",
    f"Cl{MINUS} ions",
    "Ca^2+ here",
    f"10^{MINUS}3 here",
    "pH 7",
    "see [1] now",
    "W) NAD+",
    "Na+",
    "H+",
    f"Cl{MINUS}",
]


@pytest.mark.parametrize("text", SYMBOL_BYSTANDERS)
def test_symbols_leave_charges_and_exponents(text: str) -> None:
    assert speak_units(text) == text


def test_sign_pair_between_ions_is_an_operator() -> None:
    assert speak_units("Na+ + Cl-") == "Na+ plus Cl-"


@pytest.mark.parametrize(
    "text",
    [
        "5 m/s",
        f"{MINUS}890 kJ/mol",
        "One electron volt, eV, is",
        "T = 2π",
        "1.6 × 10^-19 J",
        "N2 + 3H2 ⇌ 2NH3",
        "What is the value, in mol/L, to one",
    ],
)
def test_speak_units_is_idempotent(text: str) -> None:
    once = speak_units(text)
    assert speak_units(once) == once


def test_tables_are_injectable_and_data_driven() -> None:
    tables = Tables(
        units={
            "zz": UnitName("zed", "zeds"),
            "Zz/s": UnitName("zed per second", "zeds per second"),
        },
        symbols={"@": Symbol("at sign", "misc")},
    )
    assert speak_units("3 zz", tables=tables) == "3 zeds"
    assert speak_units("1 zz", tables=tables) == "1 zed"
    assert speak_units("a @ b", tables=tables) == "a at sign b"
    assert speak_units("5 m/s", tables=tables) == "5 m/s"


def test_real_tables_index_keys_and_aliases() -> None:
    tables = Tables.load()
    assert tables.units["m/s"].plural == "meters per second"
    assert tables.units["m/s^2"].plural == "meters per second squared"
    assert tables.units["mol/l"].plural == "moles per liter"
    # An alias ending in a period would swallow the sentence period.
    assert "ft." not in tables.units
    assert tables.symbols["⇌"].kind == "arrow"
    assert tables.templates["scientific_notation"] == "{mantissa} times ten to the {exponent}"


# Look-alike characters are written as escapes so no test depends on how an editor shows them.
MICRO = "µ"  # micro sign: symbols.json speaks it "micro"
MU = "μ"  # Greek small mu: speaks "mu"
OHM_SIGN = "Ω"
EN_DASH = "–"
ORDINAL_O = "º"  # PDFs use it for the degree sign
PRIVATE_USE = ""
REPLACEMENT = "�"
ITALIC_X = "\U0001d465"


def test_micro_sign_and_greek_mu_stay_distinct() -> None:
    assert speak_symbols(MICRO) == "micro"
    assert speak_symbols(MU) == "mu"
    assert speak_symbols(f"{MU}-opioid") == "mu-opioid"
    assert fold_compat(MICRO) == MICRO  # NFKC would turn it into Greek mu
    # In a unit both spell the same prefix.
    assert speak_units(f"10 {MICRO}m") == "10 micrometers"
    assert speak_units(f"10 {MU}m") == "10 micrometers"
    assert speak_units(f"5 {MICRO}g/mL") == "5 micrograms per milliliter"


FOLDS = [
    (ITALIC_X, "x"),
    ("\u00a0", " "),  # no-break space
    ("\u2009", " "),  # thin space
    ("\u202f", " "),  # narrow no-break space
    ("\u2103", "\u00b0C"),  # degree Celsius sign
    (OHM_SIGN, "\u03a9"),  # ohm sign -> Greek capital omega
    ("\u212a", "K"),  # kelvin sign
    ("\u212b", "\u00c5"),  # angstrom sign
    ("\u338f", "kg"),
    ("\ufb01", "fi"),
    ("\uff0b", "+"),
    ("\u00bd", "\u00bd"),  # one half stays: NFKC would split it with a fraction slash
    (MU, MU),
]


@pytest.mark.parametrize(("raw", "folded"), FOLDS)
def test_fold_compat(raw: str, folded: str) -> None:
    assert fold_compat(raw) == folded


def test_compat_characters_reach_the_unit_table() -> None:
    assert speak_units("25 ℃") == "25 degrees Celsius"
    assert speak_units("5 ㎏") == "5 kilograms"
    assert speak_units(f"10 {OHM_SIGN}") == "10 ohms"
    assert speak_units("5 m/s") == "5 meters per second"


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        (f"60{ORDINAL_O}", "60 degrees"),
        (f"0{ORDINAL_O}C", "0 degrees Celsius"),
        (f"90{ORDINAL_O}", "90 degrees"),
        ("66 ½° North", "66 one half degrees North"),
    ],
)
def test_ordinal_indicator_after_a_number_is_degrees(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken


# Real PDF artifacts from the sample rounds: subscripts arrive as separate tokens.
SPACED_FORMULAS = [
    ("C 6 H 12 O 2", "C6H12O2"),
    ("C 16 H 30 O 2", "C16H30O2"),
    ("H 2 O", "H2O"),
    ("CO 2", "CO2"),
    ("NH 3", "NH3"),
    ("SiO 2", "SiO2"),
    ("Fe 2 O 3", "Fe2O3"),
    ("N 2 O", "N2O"),
    ("AgNO 3", "AgNO3"),
    ("CH 3 OH", "CH3OH"),
    ("NO 2 molecules", "NO2 molecules"),
    ("H 3 O+ and OH-", "H3O+ and OH-"),
    ("Ca(OH) 2", "Ca(OH)2"),
    ("Mg(NO 3 ) 2", "Mg(NO3)2"),
    ("2C 4 H 10 + 13O 2", "2C4H10 + 13O2"),
    ("8CO 2 + 10H 2 O", "8CO2 + 10H2O"),
    ("N 2 + 3H 2", "N2 + 3H2"),
    ("(ACCEPT: O 2 )", "(ACCEPT: O2 )"),
    ("O 3", "O3"),
    ("SO 4 2-", "SO4 2-"),
    ("CO 2 3 times", "CO2 3 times"),
    ("P 1 V 1 = P 2 V 2", "P1V1 = P2V2"),
    ("Cl 2", "Cl2"),
]


@pytest.mark.parametrize(("raw", "closed"), SPACED_FORMULAS)
def test_spaced_subscripts_are_closed(raw: str, closed: str) -> None:
    assert collapse_spaced_formulas(raw) == closed
    assert prepare_text(raw) == closed
    assert collapse_spaced_formulas(closed) == closed


# Prose and algebra that merely look like "element number" stay as written.
NOT_SPACED_FORMULAS = [
    "OF 2",
    "ANSWER: IF N IS A MULTIPLE OF 2, THEN N + 1",
    "IS 0",
    "IN 3.2 SECONDS",
    "BY 3",
    "LOSS OF 17",
    "In 6 years from now",
    "In 12 seconds, a car goes",
    "Na 25 mg",
    "V 1 /n 1 = V 2 /n 2",
    "Page 2 - Score",
    "Middle School Round 7 Page 8",
    "I 2 hours",
    "Part (s) 2",
]


@pytest.mark.parametrize("text", NOT_SPACED_FORMULAS)
def test_prose_with_a_number_is_not_a_spaced_formula(text: str) -> None:
    assert collapse_spaced_formulas(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "How many lone pairs are in N H three?",
        "6 F two plus 2 H two O",
        "the K two C R two O seven",
        "in K O H",
    ],
)
def test_spelled_formula_output_is_not_read_as_units(text: str) -> None:
    # Re-running the unit stage on spoken formulas must change nothing.
    assert speak_units(text) == text


def test_units_do_not_read_spaced_subscripts_as_henries_or_siemens() -> None:
    # Regression: "6 H" was spoken "6 henries" and "2 S" "2 siemens" in PDF-flattened formulas.
    assert speak_units("C 6 H 12 O 2") == "C6H12O2"
    assert speak_units("C 2 H 4 and C 3 H 8") == "C2H4 and C3H8"
    assert speak_units("Fe 2 S 3") == "Fe2S3"
    assert "henr" not in speak_units("Y) C 6 H 14")


EN_DASH_MINUS = [
    (f"x = {EN_DASH}3", "x equals minus 3"),
    (f"({EN_DASH}3, 5)", "(minus 3, 5)"),
    (f"[{EN_DASH}10, 5]", "[minus 10, 5]"),
    (f"x {EN_DASH} 3 = 5", "x minus 3 equals 5"),
    (f"2 {EN_DASH} x", "2 minus x"),
    (f"x {EN_DASH} y", "x minus y"),
    (f"(a + b) {EN_DASH} 3", "(a plus b) minus 3"),
    (f"x = ({EN_DASH}b", "x equals (minus b"),
]


@pytest.mark.parametrize(("raw", "spoken"), EN_DASH_MINUS)
def test_en_dash_that_must_be_a_minus(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken


# Regression: a ")" before the dash gave the left operand an empty match and raised IndexError.
@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        (f"W) {EN_DASH}6x", "W) minus 6x"),
        (f"ANSWER: X) {EN_DASH}1", "ANSWER: X) minus 1"),
        (f"W) {EN_DASH}(k)3", f"W) {EN_DASH}(k)3"),
        (f"W) {EN_DASH}({EN_DASH}k)3", f"W) {EN_DASH}(minus k)3"),
        (f"1) {EN_DASH}7; 2) {EN_DASH}6", "1) minus 7; 2) minus 6"),
    ],
)
def test_en_dash_after_a_choice_marker_does_not_crash(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken


# A range, a dash between words, a charge and an exponent sign are not minus signs.
EN_DASH_KEPT = [
    f"5 {EN_DASH} 10 minutes",
    f"pH 2{EN_DASH}3",
    f"Page 2 {EN_DASH} Score",
    f"Cl {EN_DASH} chlorine",
    f"O2{EN_DASH} and more",
    f"the Earth {EN_DASH} a planet",
    f"A {EN_DASH} Science",
]


@pytest.mark.parametrize("text", EN_DASH_KEPT)
def test_en_dash_that_is_a_dash_is_kept(text: str) -> None:
    assert speak_units(text) == text


def test_flattened_exponent_signs_are_left_for_the_formula_pass() -> None:
    # Units run first; "10-3" after a times sign must still look like an exponent afterwards.
    assert speak_units("8 × 10−3") == "8 times 10−3"
    assert speak_units(f"3.28 × 10{EN_DASH}10") == f"3.28 times 10{EN_DASH}10"
    assert speak_units("x = 5 − 3") == "x equals 5 minus 3"


def test_private_use_and_replacement_glyphs_are_left_alone() -> None:
    assert speak_units(f"5 m/s{PRIVATE_USE}") == f"5 meters per second{PRIVATE_USE}"
    assert speak_units(f"{PRIVATE_USE} x {REPLACEMENT}") == f"{PRIVATE_USE} x {REPLACEMENT}"
    assert speak_symbols(f"a{PRIVATE_USE}b") == f"a{PRIVATE_USE}b"
