"""speak_units: quantities and math symbols to words, driven by data/units.json and symbols.json."""

from __future__ import annotations

import time

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


# The m of "technetium-99m" marks a metastable state. It is not a unit and never "meters".
METASTABLE = [
    ("technetium-99m", "technetium ninety-nine m"),
    ("Technetium-99m scans", "Technetium ninety-nine m scans"),
    ("TECHNETIUM-99m", "TECHNETIUM ninety-nine m"),
    ("Tc-99m", "T C ninety-nine m"),
    ("Kr-81m", "K R eighty-one m"),
    ("In-113m", "I N one hundred thirteen m"),
    ("99mTc", "ninety-nine m T C"),
    ("81mKr", "eighty-one m K R"),
    (f"technetium{EN_DASH}99m", "technetium ninety-nine m"),
    (f"Tc{MINUS}99m", "T C ninety-nine m"),
    ("uses technetium-99m, a tracer", "uses technetium ninety-nine m, a tracer"),
]


@pytest.mark.parametrize(("raw", "spoken"), METASTABLE)
def test_metastable_isotopes_are_not_meters(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken
    assert speak_units(spoken) == spoken  # idempotent
    assert "meter" not in speak_units(raw)


@pytest.mark.parametrize(
    "text",
    [
        "carbon-14 dating",
        "uranium-235",
        "uranium-238 and uranium-235",
        "Pb-206",
        "iodine-131",
        "cobalt-60",
        "C-14",
        "U-238",
        "nickel-78",
        "helium-3",
    ],
)
def test_other_isotope_notation_is_left_alone(text: str) -> None:
    assert speak_units(text) == text


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("5 m", "5 meters"),
        ("5m", "5 meters"),
        ("99 m/s", "99 meters per second"),
        ("a 5-m rope", "a 5-meter rope"),
        ("5mH", "5 millihenries"),
        ("3mV", "3 millivolts"),
        # A space breaks the notation: that is a quantity.
        ("technetium 99 m", "technetium 99 meters"),
    ],
)
def test_metastable_rule_leaves_real_meters_alone(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken


def test_a_metastable_symbol_is_spelled_never_named() -> None:
    assert "technetium" not in speak_units("Tc-99m").lower()
    assert "krypton" not in speak_units("81mKr").lower()


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


GRAVE_A = "\u00e0"  # a Wingdings arrow decoded as a letter
FRACTION_SLASH = "\u2044"
LESS_EQUAL_VARIANT = "\u2266"
GREATER_EQUAL_VARIANT = "\u2267"

# Real excerpts (m_round04, m_round06, m_round15): a dash between terms is a minus sign.
EN_DASH_TERMS = [
    (f"3(2x {EN_DASH} 6y + 3)", "3(2x minus 6y plus 3)"),
    (
        f"(6x2 {EN_DASH} 7x + 13) {EN_DASH} ({EN_DASH}x2 + 4x {EN_DASH} 3)",
        "(6x2 minus 7x plus 13) minus (minus x2 plus 4x minus 3)",
    ),
    (f"6x + 18y {EN_DASH} 9", "6x plus 18y minus 9"),
    (f"300 {EN_DASH} 200 = $100", "300 minus 200 equals 100 dollars"),
    (f"(0 {EN_DASH} 0) =", "(0 minus 0) equals"),
    (f"x {EN_DASH} a + b", "x minus a plus b"),
    (f"x = 6 {EN_DASH} 2", "x equals 6 minus 2"),
    (f"y {EN_DASH} 3.", "y minus 3."),
    # Real lines the first version missed: a number and a variable, two variables, a bracket,
    # and two numbers beside an operator word, "pi" or "log".
    (f"4 {EN_DASH} x < 6 + 3x.", "4 minus x is less than 6 plus 3x."),
    (f"15 {EN_DASH} x \u2265 3x + 6", "15 minus x is greater than or equal to 3x plus 6"),
    (
        f"the values of x {EN_DASH} y and 2x {MINUS} y are",
        "the values of x minus y and 2x minus y are",
    ),
    (f"What is a {EN_DASH} c in terms of b?", "What is a minus c in terms of b?"),
    (
        f"1 over ( m {EN_DASH} n close parenthesis".replace("( m", "open parenthesis m"),
        "1 over open parenthesis m minus n close parenthesis",
    ),
    (f"3x2 + 4 {EN_DASH} (3x + 2 {EN_DASH} x2)", "3x2 plus 4 minus (3x plus 2 minus x2)"),
    (f"10 {EN_DASH} 2 times 3", "10 minus 2 times 3"),
    (f"the value of 30 + 2 {EN_DASH} 1 {EN_DASH} 3?", "the value of 30 plus 2 minus 1 minus 3?"),
    (f"What is 83 {EN_DASH} 19 + 17?", "What is 83 minus 19 plus 17?"),
    (f"100 {EN_DASH} 25\u03c0", "100 minus 25 pi"),
    (f"2 log 32 + log 40 {EN_DASH} 3 log 8", "2 log 32 plus log 40 minus 3 log 8"),
    # A chain: each dash needs the term the previous one used as its right operand.
    (f"y = 2x2 {EN_DASH} 5x {EN_DASH} 1", "y equals 2x2 minus 5x minus 1"),
    (f"(x + 1) {EN_DASH} (x + 2) {EN_DASH} 3", "(x plus 1) minus (x plus 2) minus 3"),
    (f"6 {EN_DASH} 2 {EN_DASH} 1 = 3", "6 minus 2 minus 1 equals 3"),
    # A long chain: every dash goes, however many there are.
    (
        f"What is 30 + 2 {EN_DASH} 1 {EN_DASH} 3 {EN_DASH} 4 {EN_DASH} 5 {EN_DASH} 6?",
        "What is 30 plus 2 minus 1 minus 3 minus 4 minus 5 minus 6?",
    ),
    # A bracket of plain numbers is math too, so the minus before it is spoken.
    (f"What is 5 {EN_DASH} ({EN_DASH}3)?", "What is 5 minus (minus 3)?"),
    (f"What is 8 {EN_DASH} (2)?", "What is 8 minus (2)?"),
    (f"What is 10 {EN_DASH} (6 \u00f7 2)?", "What is 10 minus (6 divided by 2)?"),
    (f"Evaluate: |4 {EN_DASH} (-8)|", "Evaluate: |4 minus (-8)|"),
    (f"{EN_DASH}log 5", "minus log 5"),
]


@pytest.mark.parametrize(("raw", "spoken"), EN_DASH_TERMS)
def test_en_dash_between_algebra_terms_is_a_minus(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken
    assert speak_units(spoken) == spoken


# Genuine ranges and page dashes keep their dash.
@pytest.mark.parametrize(
    "text",
    [
        f"5 {EN_DASH} 10 minutes",
        f"Round 3 {EN_DASH} 10 points",
        f"Page 2 {EN_DASH} Score",
        f"Figure 3 {EN_DASH} a graph",
        f"Repeat 5 {EN_DASH} 10 times a day",
        f"Page 2 {EN_DASH} (continued)",
        # A noun after the number makes the bracket a label, not arithmetic.
        f"Round 3 {EN_DASH} (10 points)",
        f"Figure 2 {EN_DASH} (2019 data)",
        f"Chapter 5 {EN_DASH} (3 of 5)",
        # A suffixed number is still a number: these are ranges, not subtractions.
        # "over" is a preposition here, not a division.
        # Weak cues are gone: prose "plus", "over" and "squared" never turn a range into a minus.
        f"The trip takes 4 hours plus 1 {EN_DASH} 2 hours of rest.",
        f"3 over 4 {EN_DASH} 1",
        f"5 {EN_DASH} 3 squared",
        f"Repeat 5 {EN_DASH} 10 times a day",
        f"The drug acts over 5 {EN_DASH} 10 minutes.",
        f"Prices rose over 2 {EN_DASH} 3 years.",
        f"open 9am {EN_DASH} 5pm daily",
        f"open 9 am {EN_DASH} 5 pm daily",
        f"the 1960s {EN_DASH} 1970s",
        f"grades 10th {EN_DASH} 12th",
        f"the 3rd {EN_DASH} 5th centuries",
        f"open 9:00 {EN_DASH} 17:00",
        f"the Earth {EN_DASH} a planet",
        f"pH 2{EN_DASH}3",
    ],
)
def test_ranges_and_page_dashes_stay_dashes(text: str) -> None:
    assert speak_units(text) == text


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        (f"2CaO {GRAVE_A} 2Ca + O2", "2CaO yields 2Ca plus O2"),
        # The parser leaves the grave glued to the arrow, or the paste prints "yields" after it.
        (f"2CaO {GRAVE_A}\u2192 2Ca + O2", "2CaO yields 2Ca plus O2"),
        # A raw private-use arrow stays (the parser maps it first); only the echo goes.
        (f"4Fe + 3O2 {GRAVE_A}\uf0e0 2Fe2O3", "4Fe plus 3O2 \uf0e0 2Fe2O3"),
        (f"2CaO {GRAVE_A} yields 2Ca", "2CaO yields 2Ca"),
        (f"4Fe + 3O2 {GRAVE_A} 2Fe2O3", "4Fe plus 3O2 yields 2Fe2O3"),
        (f"Mg + ZnBr2 {GRAVE_A} Zn + MgBr2", "Mg plus ZnBr2 yields Zn plus MgBr2"),
        (f"atomic # of 16 {GRAVE_A} loss of 1", "atomic # of 16 yields loss of 1"),
        (f"2 chromatids {GRAVE_A} 46 x 2 = 92", "2 chromatids yields 46 x 2 equals 92"),
        # French and other words with no digit beside them are not arrows.
        (f"{GRAVE_A} la carte", f"{GRAVE_A} la carte"),
        (f"cafe {GRAVE_A} Paris", f"cafe {GRAVE_A} Paris"),
    ],
)
def test_wingdings_arrow_read_as_a_letter_is_an_arrow(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken


def test_glyphs_that_change_meaning_when_read_raw() -> None:
    both = f"x {GREATER_EQUAL_VARIANT} {MINUS}2 and x {LESS_EQUAL_VARIANT} 12"
    assert speak_units(both) == (
        "x is greater than or equal to minus 2 and x is less than or equal to 12"
    )
    assert prepare_text(f"1{FRACTION_SLASH} 144") == "1/ 144"
    assert prepare_text(f"3) {FRACTION_SLASH} 4") == "3) / 4"


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("apple ~ 125", "apple approximately 125"),
        ("Earth ~ 78%", "Earth approximately 78 percent"),
        ("~5 m", "approximately 5 meters"),
        ("liver ~ 7; lard", "liver approximately 7; lard"),
        ("a ~ b", "a ~ b"),
    ],
)
def test_tilde_before_a_number_is_approximately(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken


CURRENCY = [
    ("$16.50", "16 dollars 50 cents"),
    ("$16.00", "16 dollars"),
    ("$5", "5 dollars"),
    ("$1", "1 dollar"),
    ("$1,200", "1,200 dollars"),
    ("$1,200.50", "1,200 dollars 50 cents"),
    ("$0.50", "50 cents"),
    ("$1.01", "1 dollar 1 cent"),
    ("$1.5 million", "1.5 million dollars"),
    ("$16.5", "16.5 dollars"),
    ("costs $16.50.", "costs 16 dollars 50 cents."),
    ("$50K salary", "50 thousand dollars salary"),
    ("$5 MILLION", "5 million dollars"),
    ("a $2B deal", "a 2 billion dollars deal"),
    ("$2bn", "2 billion dollars"),
    ("$1.2M", "1.2 million dollars"),
    ("worth $750k.", "worth 750 thousand dollars."),
    ("(Solution: 50 bags × $6 = $300)", "(Solution: 50 bags times 6 dollars equals 300 dollars)"),
]


@pytest.mark.parametrize(("raw", "spoken"), CURRENCY)
def test_dollar_amounts(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken
    assert speak_units(spoken) == spoken


@pytest.mark.parametrize(
    "text",
    ["the $ sign", "in $ and cents", "A$5 and US$ 5", "cost $x", "$5MB of data", "$50Kx"],
)
def test_dollar_sign_without_an_amount_is_left_alone(text: str) -> None:
    assert speak_units(text) == text


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        # A unit or range noun after the right number keeps the dash, even beside a cue word.
        (f"5 {EN_DASH} 10 grams", f"5 {EN_DASH} 10 grams"),
        (f"1 {EN_DASH} 2 cm of rain", f"1 {EN_DASH} 2 centimeters of rain"),
        (f"Take 4 + 1 {EN_DASH} 2 hours", f"Take 4 plus 1 {EN_DASH} 2 hours"),
        # The corpus-backed cues still read as a minus.
        (f"10 {EN_DASH} 2 times 3", "10 minus 2 times 3"),
        (f"What is 83 {EN_DASH} 19 + 17?", "What is 83 minus 19 plus 17?"),
        (f"100 {EN_DASH} 25\u03c0", "100 minus 25 pi"),
        (f"2 log 32 + log 40 {EN_DASH} 3 log 8", "2 log 32 plus log 40 minus 3 log 8"),
        (f"(6 {EN_DASH} 2)(180) =", "(6 minus 2)(180) equals"),
        (f"5 {EN_DASH} 3^2", "5 minus 3^2"),
    ],
)
def test_two_plain_numbers_need_a_cue_or_a_unit_veto(raw: str, spoken: str) -> None:
    assert speak_units(raw) == spoken


def test_a_long_dash_chain_is_linear_in_time() -> None:
    # Regression: the fixed-point loop was cubic. N=800 took 30 s; one pass takes ~10 ms.
    started = time.perf_counter()
    spoken = speak_units("What is 30 + " + f"1 {EN_DASH} " * 800 + "1?")
    assert time.perf_counter() - started < 2.0
    assert spoken.count("minus") == 800
    assert EN_DASH not in spoken
    started = time.perf_counter()
    assert speak_units("What is 30 + " + f"1 {EN_DASH} " * 5000 + "1?").count("minus") == 5000
    assert time.perf_counter() - started < 5.0


def test_a_dash_straight_after_a_ten_is_an_exponent_sign_not_a_minus() -> None:
    # speak_units leaves these for speak_formulas: "Kw = 10-14" is 10^-14, "is 10 -4 molar" 10^-4.
    for text, spoken in [
        (f"Kw = 10{EN_DASH}14", f"Kw equals 10{EN_DASH}14"),
        (f"10{EN_DASH}3 = 0.001", f"10{EN_DASH}3 equals 0.001"),
        (f"is 10 {EN_DASH}4 molar?", f"is 10 {EN_DASH}4 molar?"),
        (f"W) 10 {EN_DASH}16", f"W) 10 {EN_DASH}16"),
        (f"is 10 {MINUS}4", f"is 10 {MINUS}4"),
        (f"Kw = 10{MINUS}14", f"Kw equals 10{MINUS}14"),
        # Spaces on both sides keep it a subtraction.
        (f"10 {EN_DASH} 4 = 6", "10 minus 4 equals 6"),
        (f"10 {MINUS} 4", "10 minus 4"),
    ]:
        assert speak_units(text) == spoken


def test_flattened_exponent_signs_are_left_for_the_formula_pass() -> None:
    # Units run first; "10-3" after a times sign must still look like an exponent afterwards.
    assert speak_units("8 × 10−3") == "8 times 10−3"
    assert speak_units(f"3.28 × 10{EN_DASH}10") == f"3.28 times 10{EN_DASH}10"
    assert speak_units("x = 5 − 3") == "x equals 5 minus 3"


def test_private_use_and_replacement_glyphs_are_left_alone() -> None:
    assert speak_units(f"5 m/s{PRIVATE_USE}") == f"5 meters per second{PRIVATE_USE}"
    assert speak_units(f"{PRIVATE_USE} x {REPLACEMENT}") == f"{PRIVATE_USE} x {REPLACEMENT}"
    assert speak_symbols(f"a{PRIVATE_USE}b") == f"a{PRIVATE_USE}b"
