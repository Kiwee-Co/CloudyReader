"""Quantities, units and math symbols to spoken words. Pure text in, text out.

Data: data/units.json (written forms and aliases -> singular/plural names) and
data/symbols.json (symbol -> spoken words, plus phrase templates). Digits stay digits; only the
unit or symbol becomes words ("5 m/s" -> "5 meters per second").

Pipeline order: call speak_units before speak_formulas. "1.6 × 10^-19 J" is then still a
quantity here, and ion signs ("Na+", "Cl−") are still attached when the formula pass reads them.

This module also owns the helpers both stages share: number words and `prepare_text`, which
folds Unicode scripts and look-alikes and closes PDF-spaced subscripts ("H 2 O" -> "H2O") before
the unit pass can read "6 H" as henries.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"

_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_SCALES = ((10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (10**3, "thousand"))
_IRREGULAR_ORDINALS = {
    "one": "first",
    "two": "second",
    "three": "third",
    "five": "fifth",
    "eight": "eighth",
    "nine": "ninth",
    "twelve": "twelfth",
}


def cardinal(n: int) -> str:
    """Moderator style: no "and", no commas, hyphenated tens (23 -> "twenty-three")."""
    if n < 0:
        return f"minus {cardinal(-n)}"
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_ONES[hundreds]} hundred" + (f" {cardinal(rest)}" if rest else "")
    for scale, name in _SCALES:
        if n >= scale:
            head, rest = divmod(n, scale)
            return f"{cardinal(head)} {name}" + (f" {cardinal(rest)}" if rest else "")
    raise AssertionError("unreachable: n >= 1000 always reaches a scale")


def ordinal(n: int) -> str:
    """23 -> "twenty-third"."""
    match = re.fullmatch(r"(.*?)([a-z]+)", cardinal(n))
    assert match is not None
    prefix, last = match.groups()
    if last in _IRREGULAR_ORDINALS:
        last = _IRREGULAR_ORDINALS[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return prefix + last


def decimal_words(number: str) -> str:
    """ "6.02" -> "six point oh two"; a zero after the point is "oh", as people say it."""
    whole, _, fraction = number.replace(",", "").partition(".")
    words = cardinal(int(whole))
    if fraction:
        digits = ("oh" if d == "0" else _ONES[int(d)] for d in fraction)
        words += " point " + " ".join(digits)
    return words


_SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻"
_SUBSCRIPTS = "₀₁₂₃₄₅₆₇₈₉₊₋"
_SUPER_TABLE = str.maketrans(_SUPERSCRIPTS, "0123456789+-")
_SUB_TABLE = str.maketrans(_SUBSCRIPTS, "0123456789+-")
_SUPER_RUN = re.compile(f"[{_SUPERSCRIPTS}]+")
_SUB_RUN = re.compile(f"[{_SUBSCRIPTS}]+")


def normalize_scripts(text: str) -> str:
    """Fold Unicode super/subscripts to ASCII: m/s² -> m/s^2, SO₄²⁻ -> SO4^2-. Idempotent."""
    text = _SUPER_RUN.sub(lambda m: "^" + m.group().translate(_SUPER_TABLE), text)
    return _SUB_RUN.sub(lambda m: m.group().translate(_SUB_TABLE), text)


# Look-alikes that PDFs and word processors put in place of plain characters. Only these ranges
# are folded: NFKC on everything would erase U+00B5 (micro sign, spoken "micro", not Greek mu's
# "mu") and turn "½" into "1⁄2".
_COMPAT = re.compile(
    "[\U0001d400-\U0001d7ff"  # math italics and bold
    "\u00a0\u2000-\u200a\u202f\u205f\u3000"  # no-break and thin spaces -> " "
    "\u2103\u2109\u2113\u2126\u212a\u212b"  # degree C and F, script l, ohm, kelvin, angstrom
    "\u3300-\u33ff"  # square unit symbols (kg, mm, m2)
    "\ufb00-\ufb06"  # ligatures (fi, fl)
    "\uff01-\uff5e]+"  # full-width ASCII
)


def fold_compat(text: str) -> str:
    return _COMPAT.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text)


@dataclass(frozen=True)
class UnitName:
    singular: str
    plural: str


@dataclass(frozen=True)
class Symbol:
    spoken: str
    kind: str


def load_document(name: str, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """data/<name>.json as a dict (schema 1)."""
    path = data_dir / f"{name}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != 1:
        raise ValueError(f"{path}: unsupported schema {doc.get('schema')!r}")
    return doc


def load_entries(name: str, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    return load_document(name, data_dir)["entries"]


@cache
def elements() -> dict[str, str]:
    """Element symbol -> its spoken letters ("Na" -> "N A")."""
    return {symbol: entry["spoken_symbol"] for symbol, entry in load_entries("elements").items()}


# Single letters that may touch the number ("5m", "3g"); other letters would hit "2N" ploidy,
# "5V", "3A", or decades like "1960s", so they need a space.
_ATTACH_OK = frozenset({"m", "g", "h"})
# Bare symbols with no tell-tale shape, still safe to speak without a number before them.
_STRONG_WORDS = frozenset(
    "atm ppm ppb mol mmol rpm psi mph kph bpm torr kcal amu Hz kyr Myr Gyr kbp MPa GPa".split()
)
# Words that may follow "in" or "per" and are then read as the unit.
_CUE_WORDS = frozenset(
    "kg mg ng cm mm km nm ms ns ft lb oz mi yr min cal m g s K N J W V L".split()
)
_DEGREE_SIGNS = "°º˚"


def _is_strong(surface: str) -> bool:
    """True when a written form is distinctive enough to be a unit with no number before it."""
    if surface in _STRONG_WORDS:
        return True
    if all(c in _DEGREE_SIGNS for c in surface):
        return False
    if any(ord(c) > 127 for c in surface) or "/" in surface:
        return True  # μm, Å, Ω, °C, N·m, m/s, kJ/mol
    if "^" in surface:
        return sum(c.isalpha() for c in surface) >= 2  # cm^2, mol^-1, but not m^2 or s^-1
    return re.search(r"[a-z][A-Z]", surface) is not None  # eV, kJ, kPa, mL, kHz, mmHg


def _is_cue_word(surface: str) -> bool:
    return _is_strong(surface) or surface in _CUE_WORDS


_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_SCI = rf"(?:{_NUM}[ ]*[×xX*][ ]*)?10\^[-−]?\d+"
# After a unit: no more letters/digits, no exponent, no charge sign ("2 H+"), no "/x" tail.
_AFTER = r"(?![\w^+\-−]|/[\w(])"


def _alternation(surfaces: Collection[str]) -> str:
    return "|".join(re.escape(s) for s in sorted(surfaces, key=lambda s: (-len(s), s)))


@dataclass(frozen=True)
class _Matchers:
    quantity: re.Pattern[str]
    cued: re.Pattern[str]
    bare: re.Pattern[str]


def _compile(units: Mapping[str, UnitName]) -> _Matchers:
    everything = _alternation(units) or "(?!)"
    cue_words = _alternation([s for s in units if _is_cue_word(s)]) or "(?!)"
    strong = _alternation([s for s in units if _is_strong(s)]) or "(?!)"
    return _Matchers(
        quantity=re.compile(
            rf"(?<![\w.^:])(?P<num>{_SCI}|{_NUM})(?P<sep>[ ]?|-)(?P<unit>{everything}){_AFTER}"
        ),
        cued=re.compile(
            rf"(?<!\w)(?P<cue>(?i:in|per|units of|measured in))(?P<gap>\s+)"
            rf"(?P<unit>{cue_words}){_AFTER}"
        ),
        bare=re.compile(rf"(?<![\w./^\-−])(?P<unit>{strong}){_AFTER}"),
    )


@dataclass(eq=False)
class Tables:
    """Spoken forms. `units` maps every written form (key and aliases) to its names."""

    units: Mapping[str, UnitName]
    symbols: Mapping[str, Symbol]
    templates: Mapping[str, str] = field(default_factory=dict)
    matchers: _Matchers = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.matchers = _compile(self.units)

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> Tables:
        units: dict[str, UnitName] = {}
        for key, entry in load_entries("units", data_dir).items():
            names = UnitName(entry["singular"], entry["plural"])
            for surface in (key, *entry.get("aliases", ())):
                surface = normalize_scripts(surface)
                # An alias ending in "." ("ft.") would swallow the sentence period.
                if not surface.endswith("."):
                    units.setdefault(surface, names)
        doc = load_document("symbols", data_dir)
        symbols = {
            key: Symbol(entry["spoken"], entry["kind"]) for key, entry in doc["entries"].items()
        }
        return cls(units, symbols, doc.get("templates", {}))


@cache
def default_tables() -> Tables:
    return Tables.load()


@cache
def operator_neighbors() -> tuple[re.Pattern[str], re.Pattern[str]]:
    """Patterns for a reaction operator right before / right after a token, raw or spoken."""
    arrows = [(key, s.spoken) for key, s in default_tables().symbols.items() if s.kind == "arrow"]
    words = {"+", "plus", *(w for pair in arrows for w in pair)}
    alt = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?:^|\s)(?:{alt})\s$"), re.compile(rf"^\s(?:{alt})(?:\s|$)")


def next_to_operator(text: str, start: int, end: int) -> bool:
    before, after = operator_neighbors()
    return bool(before.search(text[:start]) or after.match(text[end:]))


# PDF text flattens subscripts into separate tokens: "C 6 H 12 O 2", "CO 2", "Ca(OH) 2".
_CHUNK = r"(?:[A-Z][a-z]?\d{0,2})+"
# A chunk that takes a spaced number must end in a letter: "CO2 3" is not "CO23".
_LETTER_END = r"(?:[A-Z][a-z]?\d{0,2})*[A-Z][a-z]?"
# One number after each chunk: "SO 4 2-" closes to "SO4 2-" and the charge stays apart.
_SPACED = re.compile(
    rf"(?<![\w.])(?P<coef>\d+)?"
    rf"(?P<body>{_LETTER_END}(?:(?: \d{{1,2}} {_LETTER_END})+(?: \d{{1,2}})?| \d{{1,2}}))(?!\w)"
)
_SPACED_GROUP = re.compile(
    r"(?<=[A-Za-z0-9])\((?P<inner>[A-Za-z0-9 ]{1,20})\)(?: (?P<count>\d{1,2})(?!\w))?"
)
# Element-symbol spellings that are also plain words, so "OF 2", "IS 0", "In 6 years" stay prose.
PLAIN_WORDS = frozenset("OF IS IN BY ON UP US IF HI OH OK I As At Be He In No Am".split())
_ALONE_BEFORE = re.compile(r"(?:^|[(\[,;:]) ?$")
_ALONE_AFTER = re.compile(r"^ ?(?:$|[)\],;.?!])")


def _element_symbols(word: str) -> list[str] | None:
    """The element symbols in `word` (digits ignored), or None if any is not an element."""
    found = re.findall(r"[A-Z][a-z]?", re.sub(r"\d", "", word))
    return found if all(s in elements() for s in found) else None


def _collapse_spaced(m: re.Match[str]) -> str:
    tokens = m["body"].split(" ")
    symbols: list[str] = []
    for i, token in enumerate(tokens):
        if token.isdigit():
            continue
        found = _element_symbols(token)
        subscripted = i + 1 < len(tokens) and tokens[i + 1].isdigit()
        # Only a word followed by its number is prose ("OF 2"); a trailing "OH" is a group.
        if found is None or (subscripted and re.sub(r"\d", "", token) in PLAIN_WORDS):
            return m.group()
        symbols += found
    if len(symbols) == 1:  # "Na 25 mg" is prose; "O 2" counts only as a standalone item
        text, start, end = m.string, m.start(), m.end()
        alone = _ALONE_BEFORE.search(text[:start]) and _ALONE_AFTER.match(text[end:])
        if not (m["coef"] or alone or next_to_operator(text, start, end)):
            return m.group()
    return (m["coef"] or "") + m["body"].replace(" ", "")


def _collapse_group(m: re.Match[str]) -> str:
    compact = m["inner"].replace(" ", "")
    if compact == "I" or not re.fullmatch(_CHUNK, compact) or _element_symbols(compact) is None:
        return m.group()
    return f"({compact}){m['count'] or ''}"


def collapse_spaced_formulas(text: str) -> str:
    """ "H 2 O" -> "H2O", "Mg(NO 3 ) 2" -> "Mg(NO3)2" when every token is an element or a digit."""
    return _SPACED.sub(_collapse_spaced, _SPACED_GROUP.sub(_collapse_group, text))


def prepare_text(text: str) -> str:
    """The first step of both stages: fold scripts and look-alikes, close spaced subscripts."""
    return collapse_spaced_formulas(fold_compat(normalize_scripts(text)))


_INITIAL = re.compile(r"\.\s+[A-Z]\.")
_HOUR_OF_DAY = re.compile(r"(?:[1-9]|1[0-2])")
# Spelled formula output ("in N H three", "6 F two"): a letter followed by a letter or number word.
_SPELLED_NEXT = re.compile(r" (?:[A-Z]\b|(?:" + "|".join([*_ONES, *filter(None, _TENS)]) + r")\b)")


def _speak_quantity(m: re.Match[str], units: Mapping[str, UnitName]) -> str:
    num, sep, surface = m["num"], m["sep"], m["unit"]
    single = len(surface) == 1 and surface.isascii() and surface.isalpha()
    if single and sep != " " and surface not in _ATTACH_OK:
        return m.group()  # "2N", "5V", "1960s", "2-N"
    if single and surface.isupper() and _INITIAL.match(m.string, m.end()):
        return m.group()  # "1915 W. H. Bragg": W is an initial, not watts
    if single and _SPELLED_NEXT.match(m.string, m.end()):
        return m.group()
    if surface == "pm" and _HOUR_OF_DAY.fullmatch(num):
        return m.group()  # "5 pm" is a time of day
    names = units[surface]
    singular = (num.replace(",", "") == "1" or sep == "-") and "10^" not in num
    return f"{num}{'-' if sep == '-' else ' '}{names.singular if singular else names.plural}"


def _speak_quantities(text: str, tables: Tables) -> str:
    units, found = tables.units, tables.matchers
    text = found.quantity.sub(lambda m: _speak_quantity(m, units), text)

    def cued(m: re.Match[str]) -> str:
        if len(m["unit"]) == 1 and _SPELLED_NEXT.match(m.string, m.end()):
            return m.group()
        names = units[m["unit"]]
        word = names.singular if m["cue"].lower() == "per" else names.plural
        return f"{m['cue']}{m['gap']}{word}"

    text = found.cued.sub(cued, text)
    return found.bare.sub(lambda m: units[m["unit"]].plural, text)


# ASCII signs whose meaning depends on the neighbours. Everything else is spoken wherever found.
_CONTEXTUAL = frozenset("+<>~−")
_SKIPPED = frozenset("•′″")  # bullet and primes: no safe reading
_SCRIPT_CHARS = frozenset(_SUPERSCRIPTS + _SUBSCRIPTS)
_NO_SPACE_AFTER = frozenset(".,;:!?)]}-/")
_NO_SPACE_BEFORE = frozenset("([{")


def _is_operand_end(ch: str) -> bool:
    return bool(ch) and (ch.isalnum() or ch in ")]")


def _is_operand_start(ch: str) -> bool:
    return bool(ch) and (ch.isalnum() or ch in "([")


# "10−3" after a times sign is a flattened exponent: the sign stays for the formula pass.
_FLAT_EXPONENT_SIGN = re.compile(r"(?:\u00d7|\btimes|\bx)\s*10$")


_ELEMENT_BEFORE = re.compile(r"(?<![A-Za-z])[A-Z][a-z]?$")


def _is_isotope_sign(text: str, start: int) -> bool:
    """An element symbol, a minus and a mass number is an isotope, not a subtraction."""
    symbol = _ELEMENT_BEFORE.search(text[:start])
    return bool(symbol) and symbol.group() in elements() and text[start + 1 : start + 2].isdigit()


def _applies(key: str, text: str, start: int, end: int) -> bool:
    """Whether a context-dependent sign is an operator here rather than a charge or exponent."""
    prev = text[start - 1] if start else ""
    nxt = text[end] if end < len(text) else ""
    spaced = (not prev or prev.isspace()) and (not nxt or nxt.isspace())
    if key == "+":
        sign = (not prev or prev.isspace() or prev in "([") and nxt.isalnum()  # " +Na2SO4", "+5"
        return spaced or sign or (_is_operand_end(prev) and _is_operand_start(nxt))
    if key == "−":
        if prev == "^" or _FLAT_EXPONENT_SIGN.search(text[:start]) or _is_isotope_sign(text, start):
            return False  # exponent sign: 10^−3, 4 × 10−3
        return not (_is_operand_end(prev) and not _is_operand_start(nxt))  # not a charge: Cl−
    if key == "~":
        return nxt.isdigit()
    return spaced  # "<", ">" and ASCII arrows must stand alone


# The en dash is also PDF text's minus. It is one only where a minus sign must stand: before a
# number or variable after "=", "(", "[", "," or a space, or between algebra operands ("x – 3").
# "5 – 10" and "Page 2 – Score" stay a range and a dash.
_EN_DASH_SIGN = re.compile(r"(?<![^\s(\[=,;])–(?=\.?\d|[a-z](?!\w))")
_EN_DASH_BETWEEN = re.compile(
    r"(?<![\w.])(?P<l>[a-z]|\d+(?:\.\d+)?)\s?–\s?(?P<r>[a-z](?!\w)|\d+(?:\.\d+)?|\()"
)
_EN_DASH_AFTER_PAREN = re.compile(r"\) – (?P<r>[a-z](?!\w)|\d+(?:\.\d+)?|\()")


def _en_dash_between(m: re.Match[str]) -> str:
    if m["l"][0].isdigit() and m["r"][0].isdigit():
        return m.group()
    return f"{m['l']} minus {m['r']}"


def _speak_en_dash_minus(text: str) -> str:
    text = _EN_DASH_AFTER_PAREN.sub(lambda m: f") minus {m['r']}", text)
    text = _EN_DASH_BETWEEN.sub(_en_dash_between, text)
    return _EN_DASH_SIGN.sub("minus ", text)


def speak_symbols(
    text: str, *, tables: Tables | None = None, only: Collection[str] | None = None
) -> str:
    """Math symbols, Greek letters and arrows to words. `only` restricts the symbols spoken."""
    table = (tables or default_tables()).symbols
    keys = [
        key
        for key, symbol in table.items()
        if symbol.kind != "exponent"
        and not key.startswith("^")
        and key not in _SKIPPED
        and key not in _SCRIPT_CHARS
        and (only is None or key in only)
    ]
    if not keys:
        return text
    pattern = re.compile(_alternation(keys))

    def repl(m: re.Match[str]) -> str:
        key, start, end = m.group(), m.start(), m.end()
        prev = m.string[start - 1] if start else ""
        nxt = m.string[end] if end < len(m.string) else ""
        contextual = key in _CONTEXTUAL or (len(key) > 1 and key.isascii())
        if contextual and not _applies(key, m.string, start, end):
            return key
        left = " " if prev and not prev.isspace() and prev not in _NO_SPACE_BEFORE else ""
        right = " " if nxt and not nxt.isspace() and nxt not in _NO_SPACE_AFTER else ""
        return f"{left}{table[key].spoken}{right}"

    text = pattern.sub(repl, text)
    if only is None:
        text = _speak_en_dash_minus(text)
    return re.sub(r" {2,}", " ", text)


def speak_units(text: str, *, tables: Tables | None = None) -> str:
    """Quantities ("5 m/s"), bare unit symbols ("in mol/L") and math symbols to words."""
    tables = tables or default_tables()
    text = _speak_quantities(prepare_text(text), tables)
    return speak_symbols(text, tables=tables)
