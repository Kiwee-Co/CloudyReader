"""Chemical formulas, ions, scientific notation, exponents and ratios to spoken words.

A formula token is spelled letter by letter with number words: "H2O" -> "H two O",
"Ca2+" -> "C A two plus". Entity resolution never reaches this module, and a formula is never
swapped for a substance name (rule R5): the output holds letters and number words only.

Detection is conservative. Every symbol must be a real element (data/elements.json), and the
token needs a digit count, a charge, or two or more symbols with mixed case ("NaCl"). Words that
happen to be element symbols ("As", "He said", "In", "No", "I", "US", "Be", "At") are left alone,
unless the token sits next to a reaction operator ("2 Na + Cl2 → 2 NaCl").

Call speak_units first; this module accepts both raw ("×", "+") and already spoken ("times",
"plus") input. PDF text arrives with flattened exponents ("4.56 × 1011" is 4.56 × 10^11) and
spaced subscripts ("H 2 O"); `prepare_text` and the flattened-exponent rule undo both when the
shape is unambiguous, and anything unclear is left as it is.
"""

from __future__ import annotations

import re
from functools import cache

from cloudyreader.units import (
    PLAIN_WORDS,
    cardinal,
    decimal_words,
    default_tables,
    elements,
    load_entries,
    next_to_operator,
    ordinal,
    prepare_text,
    speak_symbols,
)

_ELEMENT = r"[A-Z][a-z]?"
# Two digits at most: "P450" is a name, not a formula.
_COUNT = r"(?:\d{1,2})?"
_UNIT = rf"(?:{_ELEMENT}|\((?:{_ELEMENT}{_COUNT})+\)){_COUNT}"
_SIGN = r"[+\-−–]"
# "^2+", "^{2+}", "SO4 2-", or a bare trailing sign.
_CHARGE = r"\^\{?(?:\d?" + _SIGN + r"|" + _SIGN + r"\d)\}?| \d" + _SIGN + r"|" + _SIGN
_FORMULA = re.compile(
    r"(?<![\w.^])(?P<coef>\d+)?(?P<body>(?:" + _UNIT + r")+)(?P<charge>" + _CHARGE + r")?(?!\w)"
)
_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)|(\()|(\))(\d*)")
_SIGN_WORD = {"+": "plus", "-": "minus", "−": "minus", "–": "minus"}
_NUMBER_WORDS = frozenset(cardinal(n) for n in range(21))
# "P- and S-waves", "N- and C-terminal": a suspended hyphen, not an ion. "Cl-36" and "I-131" are
# isotopes: the sign is followed by a digit, so it never reads as a charge.
_SUSPENDED_HYPHEN = re.compile(r"\s+(?:and|or|to)\s+\S+[-–]\w")
_AFTER_NUMBER = re.compile(r"\d ?$")
_HYPHEN_BEFORE = re.compile(r"[A-Za-z]-$")
_HYPHEN_AFTER = re.compile(r"-[A-Za-z]")
# All-caps tokens safe to spell without an operator next to them (HF, CO), beyond the ions table.
_ALLCAPS_EXTRA = frozenset({"CO", "HF", "KOH", "HCN"})


@cache
def _allcaps_formulas() -> frozenset[str]:
    """All-caps formulas worth spelling anywhere: the ions table's bases plus a few more."""
    bases = {key.split("^")[0].lstrip("-") for key in load_entries("ions_and_groups")}
    return _ALLCAPS_EXTRA | {b for b in bases if re.fullmatch(r"[A-Z]{2,}", b)}


def _spell(body: str) -> tuple[list[str], int, bool, bool] | None:
    """(words, element count, has a digit count, has a two-letter symbol), or None if invalid."""
    table = elements()
    words: list[str] = []
    count_elements, counted, mixed = 0, False, False
    for symbol, count, opener, _closer, group_count in _TOKEN.findall(body):
        if symbol:
            if symbol not in table:
                return None
            words.append(table[symbol])
            count_elements += 1
            mixed = mixed or len(symbol) == 2
            if count:
                words.append(cardinal(int(count)))
                counted = True
        elif opener:
            words.append("open parenthesis")
        else:
            words.append("close parenthesis")
            if group_count:
                words.append(cardinal(int(group_count)))
                counted = True
    return words, count_elements, counted, mixed


def _accepted(m: re.Match[str], body: str, spelled: tuple[list[str], int, bool, bool]) -> bool:
    _, count_elements, counted, mixed = spelled
    start, end, text = m.start(), m.end(), m.string
    if m["charge"] or counted or (count_elements >= 2 and mixed):
        return True
    if next_to_operator(text, start, end):
        return True
    # All caps, no digit: only a known formula, and never a syllable of a hyphenated word
    # ("my-OH-sis").
    return (
        count_elements >= 2
        and body in _allcaps_formulas()
        and not _HYPHEN_BEFORE.search(text[:start])
        and not _HYPHEN_AFTER.match(text, end)
    )


def _render(m: re.Match[str], *, force: bool = False) -> str:
    """Spell one formula match. `force` skips the acceptance rules (a state symbol vouches)."""
    text, whole = m.string, m.group()
    coef, body, charge = m["coef"], m["body"], m["charge"]
    if not coef and _AFTER_NUMBER.search(text[: m.start()]) and whole in default_tables().units:
        return whole  # "7 TeV" is a unit, not Te + V
    sign, digits = "", ""
    if charge:
        sign = next(c for c in reversed(charge) if c in _SIGN_WORD)
        digits = "".join(c for c in charge if c.isdigit())
        if not digits and re.search(r"\d\d$", body):
            body, digits = body[:-1], body[-1]  # "SO42-" is SO4 with charge 2-
        if sign in "-–" and _SUSPENDED_HYPHEN.match(text, m.end()):
            return whole
    spelled = _spell(body)
    if spelled is None or not (force or _accepted(m, body, spelled)):
        return whole
    parts = [cardinal(int(coef))] if coef else []
    parts += spelled[0]
    if digits:
        parts.append(cardinal(int(digits)))
    if sign:
        parts.append(_SIGN_WORD[sign])
    return " ".join(parts)


def _template(name: str, default: str) -> str:
    return default_tables().templates.get(name, default)


def _power(sign: str, digits: str) -> str:
    """The exponent phrase: the symbols table first, then the templates."""
    n = int(digits)
    entry = default_tables().symbols.get(f"^{'-' if sign else ''}{n}")
    if entry:
        return entry.spoken
    if sign:
        return _template("exponent_negative", "to the minus {n}").format(n=cardinal(n))
    return _template("exponent_positive", "to the {n}").format(n=ordinal(n))


def _scientific_words(mantissa: str, sign: str, digits: str) -> str:
    n = int(digits)
    return _template("scientific_notation", "{mantissa} times ten to the {exponent}").format(
        mantissa=decimal_words(mantissa), exponent=f"minus {cardinal(n)}" if sign else ordinal(n)
    )


_SCIENTIFIC = re.compile(
    r"(?<![\w.^])(?P<mantissa>\d+(?:\.\d+)?)\s*(?:[×xX*]|times)\s*10\^(?P<sign>[-−–]?)(?P<exp>\d+)"
)
# PDF text flattens the exponent into the base: "4.56 × 1011" is 4.56 × 10^11, "10–6" is 10^-6.
# It is an exponent only after a mantissa and a times sign, and never when the digits start with
# zero ("2 × 1000", "30 × 100" stay numbers).
_FLAT_SCIENTIFIC = re.compile(
    r"(?<![\w.^])(?P<mantissa>\d+(?:\.\d+)?)\s*(?:×|times)\s*10(?P<sign>[-−–]?)(?P<exp>\d+)"
    r"(?!\w|\.\d)"
)
_EXPONENT = re.compile(
    r"(?P<base>[A-Za-z0-9)]+)\^(?P<sign>[-−]?)(?P<exp>\d+|[A-Za-z](?![A-Za-z0-9]))"
)
_CARET = re.compile(r"\s*\^\s*")


def _speak_scientific(m: re.Match[str]) -> str:
    return _scientific_words(m["mantissa"], m["sign"], m["exp"])


def _speak_flat_scientific(m: re.Match[str]) -> str:
    if m["exp"].startswith("0"):
        return m.group()
    return _scientific_words(m["mantissa"], m["sign"], m["exp"])


def _speak_exponent(m: re.Match[str]) -> str:
    base, sign, exp = m["base"], m["sign"], m["exp"]
    if base.isdigit():
        base = cardinal(int(base))
    elif re.fullmatch(r"[a-z]{2,3}", base) and base not in _NUMBER_WORDS:
        base = " ".join(base)  # "ax" would be read as a word
    power = _power(sign, exp) if exp.isdigit() else f"to the {'minus ' if sign else ''}{exp}"
    return f"{base} {power}"


_PAREN_SLASH = re.compile(r"(?<=\))\s*/\s*(?=[\w(\[])")
_SPACED_SLASH = re.compile(r"(?:(?<=\d)|(?<=\s[A-Za-z]))\s+/\s+(?=[\w(\[])")
# Not after a number: "3 m/s" is a quantity, not a ratio of variables.
_LETTER_RATIO = re.compile(r"(?<![\w/.])(?<!\d )(?P<a>[A-Za-z])/(?P<b>[A-Za-z])(?![\w/])")


def _speak_ratio(m: re.Match[str]) -> str:
    a, b = m["a"], m["b"]
    return m.group() if a.isupper() and b.isupper() else f"{a} over {b}"  # keep "N/A"


_SPECIES_BRACKET = re.compile(r"\[(?P<inner>[A-Z][A-Za-z0-9()]*(?:\^?\d?" + _SIGN + r")?)\]")
_ELECTRON = re.compile(r"(?<![A-Za-z_])(?P<n>\d*)e\^?(?P<sign>[+\-−])(?!\w)")
_DOTS = frozenset("·⋅∙")
# "MgSO4•7H2O": a bullet between formula parts is the hydrate dot (a list bullet never is).
_HYDRATE_DOT = re.compile(r"(?<=[A-Za-z0-9)])•(?=\d*[A-Z])")


def _unwrap_species(m: re.Match[str]) -> str:
    """Concentration brackets: [H+] -> H+, [NH3] -> NH3, [A] -> A (the formula pass speaks it)."""
    inner = m["inner"]
    core = re.sub(r"\^?\d?" + _SIGN + r"$", "", inner)
    if len(core) != 1 and _spell(core) is None:
        return m.group()
    text, start, end = m.string, m.start(), m.end()
    left = " " if start and text[start - 1].isalnum() else ""
    right = " " if end < len(text) and text[end].isalnum() else ""
    # "[He]" would otherwise be read as the pronoun: a bare element is spelled here.
    return f"{left}{elements().get(inner, inner)}{right}"


# "2KOH(aq)", "H2O (l)", "Cu(s)": state symbols are words, never letters. Only a formula-shaped
# token qualifies, so "word(s)" and "the (S)-isomer" are untouched.
_STATES = {"aq": "aqueous", "s": "solid", "l": "liquid", "g": "gas"}
_STATE_SYMBOL = re.compile(
    r"(?<![\w])(?P<token>\d*(?:" + _UNIT + r")+(?:\^?\d?[+\-\u2212])?)(?P<gap> ?)"
    r"\((?P<state>aq|s|l|g|AQ|S|L|G)\)"
)


def _speak_state(m: re.Match[str]) -> str:
    token = m["token"]
    formula = _FORMULA.fullmatch(token)
    spelled = _spell(formula["body"]) if formula else None
    if formula is None or spelled is None:
        return m.group()
    _, count_elements, counted, _ = spelled
    bare = token.lstrip("0123456789")
    # A single symbol needs the state symbol right against it ("K(s)"), and never a plain word.
    if not (
        counted
        or count_elements >= 2
        or formula["charge"]
        or (not m["gap"] and bare not in PLAIN_WORDS)
    ):
        return m.group()
    return f"{_render(formula, force=True)} {_STATES[m['state'].lower()]}"


def _speak_electron(m: re.Match[str]) -> str:
    n = f"{m['n']} " if m["n"] else ""
    return f"{n}e {_SIGN_WORD[m['sign']]}"


def _speak_hydrate_dots(text: str) -> str:
    symbols = default_tables().symbols
    dot = symbols.get("•") or symbols.get("·")
    return _HYDRATE_DOT.sub(f" {dot.spoken} ", text) if dot else text


def _speak_reaction_symbols(text: str) -> str:
    """Arrows, hydrate dots and spaced plus signs. Other symbols are speak_units' job."""
    symbols = default_tables().symbols
    arrows = {key for key, s in symbols.items() if s.kind == "arrow"}
    text = speak_symbols(text, only=arrows | _DOTS)
    return re.sub(r"(?<=\s)\+(?=\s)", symbols["+"].spoken, text)


def speak_formulas(text: str) -> str:
    """Formulas, ions, scientific notation, exponents and ratios to words."""
    text = _speak_hydrate_dots(prepare_text(text))
    text = re.sub(r"(?<=\])\s*(?=\[[A-Z])", " times ", text)  # [N2][H2] -> [N2] times [H2]
    text = _SPECIES_BRACKET.sub(_unwrap_species, text)
    text = _SCIENTIFIC.sub(_speak_scientific, text)
    text = _FLAT_SCIENTIFIC.sub(_speak_flat_scientific, text)
    text = _STATE_SYMBOL.sub(_speak_state, text)
    text = _FORMULA.sub(_render, text)
    text = _ELECTRON.sub(_speak_electron, text)
    text = _speak_reaction_symbols(text)
    text = _PAREN_SLASH.sub(" over ", text)
    text = _SPACED_SLASH.sub(" over ", text)
    text = _LETTER_RATIO.sub(_speak_ratio, text)
    text = _EXPONENT.sub(_speak_exponent, text)
    return _CARET.sub(" to the power of ", text)
