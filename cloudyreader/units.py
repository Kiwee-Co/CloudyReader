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


@cache
def element_names() -> frozenset[str]:
    """Lowercase element names. Used only to recognise a printed word, never to speak one."""
    return frozenset(entry["name"].lower() for entry in load_entries("elements").values())


@cache
def atomic_numbers() -> dict[str, int]:
    """Element symbol and lowercase name -> atomic number. Bounds a plausible mass number."""
    entries = load_entries("elements")
    by_symbol = {symbol: entry["atomic_number"] for symbol, entry in entries.items()}
    by_name = {entry["name"].lower(): entry["atomic_number"] for entry in entries.values()}
    return {**by_symbol, **by_name}


# Single letters that may touch the number ("5m", "3g"); other letters would hit "2N" ploidy,
# "5V", "3A", decades like "1960s", or algebra like "2h", so they need a space.
_ATTACH_OK = frozenset({"m", "g"})
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
    unit_words: re.Pattern[str]  # a spoken unit name right after a number: "centimeters"


def _compile(units: Mapping[str, UnitName]) -> _Matchers:
    everything = _alternation(units) or "(?!)"
    cue_words = _alternation([s for s in units if _is_cue_word(s)]) or "(?!)"
    strong = _alternation([s for s in units if _is_strong(s)]) or "(?!)"
    names = _alternation({n for u in units.values() for n in (u.singular, u.plural)}) or "(?!)"
    return _Matchers(
        quantity=re.compile(
            rf"(?<![\w.^:])(?P<num>{_SCI}|{_NUM})(?P<sep>[ ]?|-)(?P<unit>{everything}){_AFTER}"
        ),
        cued=re.compile(
            rf"(?<!\w)(?P<cue>(?i:in|per|units of|measured in))(?P<gap>\s+)"
            rf"(?P<unit>{cue_words}){_AFTER}"
        ),
        bare=re.compile(rf"(?<![\w./^\-−])(?P<unit>{strong}){_AFTER}"),
        unit_words=re.compile(rf"\s+(?:{names})\b", re.IGNORECASE),
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


# PDF glyphs that change meaning when read raw: the "less/greater or equal" variants and the
# fraction slash, which a voice drops ("1\u2044144" would be said as two numbers).
_GLYPH_ALIASES = str.maketrans({"\u2266": "\u2264", "\u2267": "\u2265", "\u2044": "/"})
# A Wingdings arrow arrives as "a grave", usually glued to the arrow itself. Then the grave is an
# echo and goes. Alone between spaces with a digit beside it ("2CaO a-grave 2Ca"), it is the arrow.
_WINGDINGS_ARROW = re.compile(r"(?<!\w)\u00e0(?=\s|\u2192|\uf0e0|$)")
_ARROW_FOLLOWS = re.compile(r"\s*(?:\u2192|\uf0e0|yields\b)")


def _wingdings_arrow(m: re.Match[str]) -> str:
    if _ARROW_FOLLOWS.match(m.string, m.end()):
        return ""
    if m.start() and not m.string[m.start() - 1].isspace():
        return m.group()
    before = re.search(r"(\S+)\s+$", m.string[: m.start()])
    after = re.match(r"\s+(\S+)", m.string[m.end() :])
    near = (before.group(1) if before else "") + (after.group(1) if after else "")
    return "\u2192" if re.search(r"\d", near) else m.group()


def fix_pdf_glyphs(text: str) -> str:
    return _WINGDINGS_ARROW.sub(_wingdings_arrow, text.translate(_GLYPH_ALIASES))


def prepare_text(text: str) -> str:
    """The first step of both stages: fold scripts, look-alikes and PDF glyphs, close subscripts."""
    return collapse_spaced_formulas(fix_pdf_glyphs(fold_compat(normalize_scripts(text))))


_DASHES = "-\u2212\u2013"


@cache
def _isotope_patterns() -> tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]:
    names = "|".join(sorted(element_names(), key=len, reverse=True))
    named = re.compile(
        rf"(?<![A-Za-z])(?P<name>(?i:{names}))[{_DASHES}](?P<mass>\d{{1,3}})m(?![A-Za-z0-9])"
    )
    symbol = re.compile(
        rf"(?<![A-Za-z0-9])(?P<symbol>[A-Z][a-z]?)[{_DASHES}](?P<mass>\d{{1,3}})m(?![A-Za-z0-9])"
    )
    # "99mTc": two digits or more and a two-letter symbol, so "5mH" and "3mV" stay units.
    prefixed = re.compile(
        r"(?<![A-Za-z0-9.])(?P<mass>\d{2,3})m(?P<symbol>[A-Z][a-z])(?![A-Za-z0-9])"
    )
    return named, symbol, prefixed


def speak_isotopes(text: str) -> str:
    """Metastable isotopes: "technetium-99m" -> "technetium ninety-nine m", never "99 meters".

    The m is a marker, not a unit. A printed name stays as printed; a symbol is spelled.
    """
    named, symbol, prefixed = _isotope_patterns()
    table, units = elements(), default_tables().units

    def mass(m: re.Match[str]) -> str:
        return cardinal(int(m["mass"]))

    def spelled(m: re.Match[str], pattern: str) -> str:
        sym = m["symbol"]
        if sym not in table or (pattern == "prefixed" and f"m{sym}" in units):
            return m.group()
        return f"{table[sym]} {mass(m)} m" if pattern == "symbol" else f"{mass(m)} m {table[sym]}"

    text = named.sub(lambda m: f"{m['name']} {mass(m)} m", text)
    text = symbol.sub(lambda m: spelled(m, "symbol"), text)
    return prefixed.sub(lambda m: spelled(m, "prefixed"), text)


_CURRENCY = re.compile(
    r"(?<![\w$])\$(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<scale> ?(?i:thousand|million|billion|trillion)|bn|BN|Bn|[KkMmBb])?(?!\w)"
)
_MONEY_SCALES = {"k": "thousand", "m": "million", "b": "billion", "bn": "billion"}


def _speak_currency(m: re.Match[str]) -> str:
    """ "$16.50" -> "16 dollars 50 cents", "$50K" -> "50 thousand dollars", "$1,200" too."""
    amount = m["amount"]
    scale = (m["scale"] or "").strip().lower()
    if scale:
        return f"{amount} {_MONEY_SCALES.get(scale, scale)} dollars"
    whole, _, fraction = amount.partition(".")
    if len(fraction) == 2:
        dollars, cents = int(whole.replace(",", "")), int(fraction)
        parts = []
        if dollars or not cents:
            parts.append(f"{whole} dollar{'' if dollars == 1 else 's'}")
        if cents:
            parts.append(f"{cents} cent{'' if cents == 1 else 's'}")
        return " ".join(parts)
    return f"{amount} dollar{'' if amount == '1' else 's'}"


_INITIAL = re.compile(r"\.\s+[A-Z]\.")
_HOUR_OF_DAY = re.compile(r"(?:[1-9]|1[0-2])")
# Spelled formula output ("in N H three", "6 F two"): a letter followed by a letter or number word.
_SPELLED_NEXT = re.compile(r" (?:[A-Z]\b|(?:" + "|".join([*_ONES, *filter(None, _TENS)]) + r")\b)")


# "5m \u2013 13", "3g = 12": an operator after an attached m or g, raw or spoken, makes it a
# variable.
_OPERATOR_AFTER = re.compile(
    r"\s*(?:[+=\u00d7\u00f7*^<>\u2013\u2212-]"
    r"|(?:plus|minus|times|divided|equals|is (?:less|greater))\b)"
)
# "If m is an integer and 20m is...": the same letter stands alone elsewhere in the text.
_ATTACHED_LETTER_ALONE = re.compile(r"(?<![\w.^/\u2212-])(?<![\d.]\s)([mg])(?![\w.^/\u2212-])")


def _speak_quantity(
    m: re.Match[str], units: Mapping[str, UnitName], alone: frozenset[str] = frozenset()
) -> str:
    num, sep, surface = m["num"], m["sep"], m["unit"]
    single = len(surface) == 1 and surface.isascii() and surface.isalpha()
    if single and sep != " " and surface not in _ATTACH_OK:
        return m.group()  # "2N", "5V", "1960s", "2-N"
    if single and not sep and (surface in alone or _OPERATOR_AFTER.match(m.string, m.end())):
        return m.group()  # algebra, not meters or grams: "5m \u2013 13", "3g = 12"
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
    alone = frozenset(_ATTACHED_LETTER_ALONE.findall(text))
    text = found.quantity.sub(lambda m: _speak_quantity(m, units, alone), text)

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
# A real minus right after a 10 and before a digit is that exponent's sign too (10 minus-7).
_TEN_BEFORE = re.compile(r"(?<![\w.])10\s*$")
_FLAT_EXPONENT_SIGN = re.compile(r"(?:\u00d7|\btimes|\b[xX])\s*10$")


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
        if (
            prev == "^"
            or _FLAT_EXPONENT_SIGN.search(text[:start])
            or _is_isotope_sign(text, start)
            or (nxt.isdigit() and _TEN_BEFORE.search(text[:start]))
        ):
            return False  # exponent sign: 10^−3, 4 × 10−3
        return not (_is_operand_end(prev) and not _is_operand_start(nxt))  # not a charge: Cl−
    if key == "~":
        return nxt.isdigit() or (nxt == " " and text[end + 1 : end + 2].isdigit())
    return spaced  # "<", ">" and ASCII arrows must stand alone


# The en dash is PDF text's minus and the ASCII hyphen is typed as one; the voice drops both.
# A dash is a minus as a sign ("-3", "y = \u2013 4") or between terms ("2x \u2013 6y", "x^2 - x"); a
# tight hyphen is never one. Two plain numbers are a range unless arithmetic sits beside them.
_NUMBER = r"\d+(?:\.\d+)?"
_NUMBER_TERM = rf"{_NUMBER}(?:[a-z]\d{{0,2}}){{0,4}}"  # 3x, 9am, 96a7b3
# "x^2 - 12" is the term x^2 minus 12, not the plain number 2 minus 12.
_TERM = rf"(?:(?:{_NUMBER_TERM}|[a-z]\d{{0,2}})(?:\^\d{{1,2}})?|\^\d{{1,2}})"
# The article "a" before a prose word ("Figure 3 \u2013 a graph") is no variable; other letters are.
_MATH_WORDS = r"(?:plus|minus|times|equals|over|divided|squared|cubed|to)\b"
_RIGHT = (
    rf"(?:{_NUMBER_TERM}(?!\w|\.\d)"
    rf"|a(?!\w|\.\d)(?![ ]+(?!{_MATH_WORDS})[a-z]{{2}})"
    r"|[b-z](?!\w|\.\d)|[a-z]\d{1,2}(?!\w|\.\d)|\()"
)
# After "equals" the hyphen has no space: "x=-3" is spoken "x equals-3".
_EN_DASH_SIGN = re.compile(
    r"(?:(?<![^\s(\[=,;])|(?<=equals))"
    r"(?:\u2013(?=\.?\d|log\b|[a-z]{1,2}\d{0,2}(?![A-Za-z]))"
    r"|-(?=\.?\d|log\b|[a-z]\d{0,2}(?![A-Za-z])))"
)
# A space after the sign: "y = \u2013 2x + 4" is said "y equals [pause] 2x", so the sign is lost.
_SPACED_SIGN = re.compile(
    r"(?P<opener>\bequals|[(\[,])(?P<gap>\s?)[\u2013-]\s+"
    r"(?=\.?\d|log\b|[a-z]\d{0,2}(?![A-Za-z])|\()"
)
_AFTER_TEN = re.compile(r"(?<![\w.])10\s+$")


_ELEMENT_NAME_BEFORE = re.compile(r"([A-Za-z]+)\s?$")
_MASS_NUMBER = re.compile(r"(\d{1,3})(?!\d|\.\d)")


def _is_isotope_mass(word: str, text: str, sign_at: int) -> bool:
    """An element, a sign and a whole mass number between Z and 3Z: "Uranium -235", "Cl -36".

    "At -40", "Helium \u2013269" and "In -3x" fall outside it, so they are negative numbers.
    """
    numbers = atomic_numbers()
    z = numbers.get(word) or numbers.get(word.lower())
    mass = _MASS_NUMBER.match(text, sign_at + 1)
    return bool(z and mass and z <= int(mass[1]) <= 3 * z)


def _en_dash_sign(m: re.Match[str]) -> str:
    text, start = m.string, m.start()
    if _AFTER_TEN.search(text[max(0, start - 16) : start]):
        return m.group()  # "is 10 \u20134 molar": an exponent, said by speak_formulas
    name = _ELEMENT_NAME_BEFORE.search(text[max(0, start - 20) : start])
    if name and _is_isotope_mass(name[1], text, start):
        return m.group()  # isotopes, not negative numbers
    glued = text[start - 1 : start] in {",", ";"} or text[start - 1 : start].isalpha()
    return " minus " if glued and start else "minus "  # "x=-3" arrives as "equals-3"


# The right operand is a lookahead: in a chain of dashes it stays free to start the next match.
_EN_DASH_BETWEEN = re.compile(
    rf"(?<![\w.])(?P<l>{_TERM})(?!\w|\.\d)(?P<gap>\s?)(?:\u2013|(?<=\s)-(?=\s))(?P<tail>\s?)"
    rf"(?=(?P<r>{_RIGHT}))"
)
_EN_DASH_AFTER_PAREN = re.compile(rf"\) [\u2013-] (?=(?P<r>{_RIGHT}))")
_WINDOW = 24  # how far from the dash a cue may sit
_OPERATOR_WORD = r"(?:plus|minus|times|divided by)"  # the spoken + - \u00d7 \u00f7
_CUE_BEFORE = re.compile(rf"(?:(?:\d|\)|\b[a-z])\s+{_OPERATOR_WORD}|\bequals|\blog)\s+$")
_CUE_AFTER = re.compile(
    rf"\s+{_OPERATOR_WORD}\s+[\d(]|[\s)(\d.\u2013-]{{0,24}}\bequals\b|\s+(?:pi|log)\b|\^"
    r"|\s+is (?:less|greater|not|approximately)\b"
)
_BRACKET_BEFORE = re.compile(r"\(\s*$")
_BRACKET_AFTER = re.compile(r"\s*\)")
# A range noun after the right number vetoes a minus: "1 \u2013 2 hours", "5 \u2013 10 grams".
_RANGE_NOUNS = re.compile(
    r"\s+(?:years?|days?|weeks?|months?|hours?|minutes?|seconds?|people|students|questions|points"
    r"|pages?|chapters?|rounds?|items?|grades?)\b",
    re.IGNORECASE,
)
# A bracket after a dash is math when a number or an operator opens it, or a variable sits
# inside: "8 \u2013 (2)", "5 \u2013 (\u20133)", "10 \u2013 (6 \u00f7 2)".
# A noun after the number is a label, so "Round 3 \u2013 (10 points)" keeps its dash.
_MATH_GROUP = re.compile(
    r"\(\s*(?:[\u2013\u2212-]?\d+(?:\.\d+)?"
    r"(?!\d|\.\d|\s+(?!(?:plus|minus|times|over|divided)\b)[a-z]{2})"
    r"|[+\u00d7\u00f7]"
    r"|[^()]{0,30}?(?:(?<![\w.])(?:\d+[a-z]{1,3}\d{0,2}|[a-z]\d{0,2})(?![\w.])"
    r"|\b(?:plus|minus|times|over|divided)\b))"
)
# "9am", "10th" and "1960s" are numbers with a suffix: "9am \u2013 5pm" is a range, not a minus.
_PLAIN_NUMBER = re.compile(rf"{_NUMBER}(?:st|nd|rd|th|am|pm)?|\d{{2,}}s")
_SCALE_WORD = re.compile(r"\s+(?:thousand|million|billion|trillion)\b", re.IGNORECASE)
_PERCENT_AFTER = re.compile(r"\s*percent\b")
# "10^3\u201310^4", "1 times 10^3\u20135 times 10^3": a range of magnitudes, never a subtraction.
# Two exponent digits at most, so the value stays a float.
_POWER_OF_TEN = r"(?:\d+(?:\.\d+)?\s*(?:[\u00d7xX*]|times)\s*)?10\^[-\u2212]?\d{1,2}"
_POWER_RANGE = re.compile(
    rf"(?<![\w.^])(?P<l>{_POWER_OF_TEN})(?P<gap>\s?)\u2013(?P<tail>\s?)"
    rf"(?=(?P<r>{_POWER_OF_TEN})(?![\w^.]))"
)
_POWER_PARTS = re.compile(
    r"(?:(?P<mantissa>\d+(?:\.\d+)?)\s*(?:[\u00d7xX*]|times)\s*)?10\^(?P<exp>[-\u2212]?\d+)"
)
# Fifteen digits at most, where float() still orders two numbers exactly.
_RANGE_NUMBER = r"(?:\d{1,3}(?:,\d{3}){1,4}|\d{1,15})(?:\.\d{1,15})?"
_RANGE = re.compile(
    rf"(?<![\w.,/^\u2013\u2212-])(?P<l>{_RANGE_NUMBER})(?P<gap> ?)(?P<dash>[\u2013-])(?P<tail> ?)"
    rf"(?P<r>{_RANGE_NUMBER})(?![\w/^\u2013\u2212-]|[.,]\d)"
)
# "Round 3 \u2013 10 points" is a title and its points, not a range of rounds.
_LABEL_BEFORE = re.compile(
    r"\b(?:Round|Page|Figure|Chapter|Section|Part|Problem|Question|Table|Step)\s+$"
)


def _power_value(term: str) -> float:
    parts = _POWER_PARTS.fullmatch(term)
    assert parts is not None
    return float(parts["mantissa"] or 1) * 10.0 ** int(parts["exp"].replace("\u2212", "-"))


def _range_follows(text: str, end: int, tables: Tables) -> bool:
    """A range noun, a unit or "percent" after the right number, past a scale word."""
    scale = _SCALE_WORD.match(text, end)
    at = scale.end() if scale else end
    return bool(
        _RANGE_NOUNS.match(text, at)
        or tables.matchers.unit_words.match(text, at)
        or _PERCENT_AFTER.match(text, at)
    )


def speak_ranges(text: str, *, tables: Tables | None = None) -> str:
    """ "5\u201310 grams" -> "5 to 10 grams". Call it after speak_formulas reads "Kw = 10\u201314".

    A tight en dash between ascending numbers is a range. A spaced one, or an ASCII hyphen, needs
    a range noun or a unit after it ("15-16 years"), so "pH 5-7" and "83 \u2013 19" keep the dash.
    """
    tables = tables or default_tables()

    def repl(m: re.Match[str]) -> str:
        if float(m["l"].replace(",", "")) >= float(m["r"].replace(",", "")):
            return m.group()
        if m["dash"] == "-" or m["gap"] or m["tail"]:
            label = _LABEL_BEFORE.search(m.string, max(0, m.start() - 20), m.start())
            if label or not _range_follows(m.string, m.end(), tables):
                return m.group()
        return f"{m['l']} to {m['r']}"

    return _RANGE.sub(repl, text)


def _is_minus(m: re.Match[str], *, chained: bool, tables: Tables) -> bool:
    text, left, right = m.string, m["l"], m["r"]
    if left == "10" and not m["gap"] and not m["tail"] and right.isdigit():
        return False  # "Kw = 10\u201314": the exponent's sign, said by speak_formulas
    plain = _PLAIN_NUMBER.fullmatch(left) and (_PLAIN_NUMBER.fullmatch(right) or right == "(")
    if not plain:
        return True  # a variable or an algebra term stands on a side
    if right == "(":
        return bool(_MATH_GROUP.match(text, m.end()))
    end = m.end() + len(right)
    if _RANGE_NOUNS.match(text, end) or tables.matchers.unit_words.match(text, end):
        return False
    before = text[max(0, m.start() - _WINDOW) : m.start()]
    return (
        chained  # the previous dash was a minus and this number is its right operand
        or bool(_CUE_BEFORE.search(before))
        or bool(_CUE_AFTER.match(text, end))
        or bool(_BRACKET_BEFORE.search(before) and _BRACKET_AFTER.match(text, end))
    )


def _speak_en_dash_minus(text: str, tables: Tables) -> str:
    """One left-to-right pass: a dash that is a minus vouches for the next one in a chain."""
    text = _EN_DASH_AFTER_PAREN.sub(") minus ", text)

    def power_range(m: re.Match[str]) -> str:
        tight = not m["gap"] and not m["tail"]
        end = m.end() + len(m["r"])
        ascending = _power_value(m["l"]) < _power_value(m["r"])
        if ascending and (tight or _range_follows(m.string, end, tables)):
            return f"{m['l']} to "
        return m.group()

    text = _POWER_RANGE.sub(power_range, text)
    pieces: list[str] = []
    position, chained_at = 0, -1
    for m in _EN_DASH_BETWEEN.finditer(text):
        minus = _is_minus(m, chained=m.start() == chained_at, tables=tables)
        pieces.append(text[position : m.start()])
        pieces.append(f"{m['l']} minus " if minus else m.group())
        position, chained_at = m.end(), (m.end() if minus else -1)
    pieces.append(text[position:])

    def spaced(m: re.Match[str]) -> str:
        gap = m["gap"] or (" " if m["opener"] in {",", "equals"} else "")
        return f"{m['opener']}{gap}minus "

    text = _SPACED_SIGN.sub(spaced, "".join(pieces))
    return _EN_DASH_SIGN.sub(_en_dash_sign, text)


# "x<3": "<" and ">" were said only standing alone, and the voices drop them raw (espeak says
# "x three"). Between operands they are spaced out; "<=" and ">=" become one sign.
_COMPARISON = re.compile(
    r"(?P<before>\s*)(?P<op><=|>=|<|>)(?P<after>\s*)(?=[\w(\[.]|[-\u2212\u2013]\.?\d)"
)
_COMPARISON_SIGNS = {"<=": "\u2264", ">=": "\u2265", "<": "<", ">": ">"}
_PREFIX_WORDS = {
    "<": "less than",
    ">": "greater than",
    "<=": "less than or equal to",
    ">=": "greater than or equal to",
}
_LEFT_WORD = re.compile(r"(\w+)$")
# HTML-like markup from a web paste is no comparison: "H<sub>2</sub>O" keeps its brackets.
_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9]*>")


def _space_comparisons(text: str) -> str:
    tags = [m.span() for m in _TAG.finditer(text)]

    def repl(m: re.Match[str]) -> str:
        op, at = m["op"], m.start("op")
        if any(start <= at < end for start, end in tags):
            return m.group()
        prev = text[m.start() - 1] if m.start() else ""
        word = _LEFT_WORD.search(text, max(0, m.start() - 30), m.start())
        # No operand on the left ("of <5%", "(<5)"): a prefix, said without "is".
        prose = word and word[1].isalpha() and len(word[1]) > 1 and not m["after"]
        operand = prev.isalnum() or (prev != "" and prev in ")]")
        if not operand or (prose and m["before"]):
            if not text[m.end() : m.end() + 1].isdigit():
                return m.group()
            return f"{m['before']}{_PREFIX_WORDS[op]} "
        return f" {_COMPARISON_SIGNS[op]} "

    return _COMPARISON.sub(repl, text)


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

    text = pattern.sub(repl, _space_comparisons(text) if only is None else text)
    if only is None:
        text = _speak_en_dash_minus(text, tables or default_tables())
    return re.sub(r" {2,}", " ", text)


def speak_units(text: str, *, tables: Tables | None = None) -> str:
    """Quantities ("5 m/s"), bare unit symbols ("in mol/L") and math symbols to words."""
    tables = tables or default_tables()
    text = _CURRENCY.sub(_speak_currency, speak_isotopes(prepare_text(text)))
    text = _speak_quantities(text, tables)
    return speak_symbols(text, tables=tables)
