"""Written fractions to spoken words: "3/9" -> "three ninths", "2 1/2" -> "two and one half".

Every voice reads a raw slash as "slash" (or drops it), so a fraction is said the way a moderator
says it. Only a plain fraction of whole numbers qualifies: a letter, a root sign, a decimal point,
a thousands comma or another slash beside it ("m/s", "√10/5", "1.5/2", "1,000/3", "3/9/2024")
keeps it as is.

Two passes. `mark_fractions` reads the raw text, before speak_units rewrites the neighbours ("√"
-> "square root of ", "²" -> "^2"), and swaps each fraction's slash for a mark. `say_marked` runs
after speak_units, so "-3/7" is already "minus 3/7", and reads each marked fraction.
"""

from __future__ import annotations

import re
import unicodedata

from cloudyreader.units import cardinal, ordinal

__all__ = ["mark_fractions", "say_marked", "speak_fractions"]

# Noncharacters are reserved for internal use, so no pasted text holds one. The first marks the
# slash of a fraction, the second the slash of a mixed number's fraction ("2 1/2").
_SLASH, _MIXED = "\ufdd0", "\ufdd1"
# Nine digits at most: cardinal() stays short and int() never meets its digit limit. A leading
# zero ("01/02") is a date or a code, not a fraction.
_NUMBER = r"(?:0|[1-9][0-9]{0,8})"
_SUFFIX = r"(?i:(?:st|nd|rd|th)s?)"
_FRACTION = re.compile(
    rf"(?<![\w/.,√∛∜])(?:(?P<whole>{_NUMBER})(?P<sep>[ -]))?"
    rf"(?P<num>{_NUMBER})[/\u2044\u2215](?P<den>{_NUMBER})(?P<suffix>{_SUFFIX})?"
    r"(?![\w/]|[.,][0-9])"
)
# ¼ ½ ¾, U+2150-U+215E and ↉ (0/3): always a fraction. U+215F is a bare "1/", so it stays.
_GLYPH = re.compile(rf"(?:(?<![\w/.,√∛∜])(?P<whole>{_NUMBER})(?P<sep>[ -]?))?(?P<glyph>[¼-¾⅐-⅞↉])")
# A sign the unit stage left: after "^" ("x^-1/2"), or in a guide's words, which skip that stage.
_MARKED = re.compile(
    rf"(?P<sign>(?:(?<=[\^ (])|^)[-−–])?"
    rf"(?:(?P<whole>{_NUMBER})[ -](?={_NUMBER}{_MIXED}))?"
    rf"(?P<num>{_NUMBER})[{_SLASH}{_MIXED}](?P<den>{_NUMBER})(?P<suffix>{_SUFFIX})?"
)
_UNMARK = str.maketrans({_SLASH: "/", _MIXED: "/"})
_NAMES = {2: ("half", "halves")}


def _words(num: int, den: int, suffix: str | None) -> str:
    """ "three ninths"; a denominator with no everyday ordinal is read "over" ("one over zero")."""
    if den in _NAMES:
        one, many = _NAMES[den]
    elif den == 4 and num in (1, 3):
        one, many = "quarter", "quarters"  # every other count of fourths is "fourths"
    elif 3 <= den <= 99 or den in (100, 1000):
        one = ordinal(den).removeprefix("one ")  # 1/100 is "one hundredth"
        many = one + "s"
    elif suffix:  # "1/360th" asks for the ordinal: "one three-hundred-sixtieth"
        one = ordinal(den).replace(" ", "-")
        many = one + "s"
    else:
        return f"{cardinal(num)} over {cardinal(den)}"
    return f"{cardinal(num)} {one if num == 1 else many}"


def _mark(m: re.Match[str]) -> str:
    whole, num, den = m["whole"], m["num"], m["den"]
    suffix = m["suffix"] or ""
    if whole is not None and int(num) < int(den):
        return f"{whole}{m['sep']}{num}{_MIXED}{den}{suffix}"
    lead = "" if whole is None else whole + m["sep"]  # "2 3/2" is two numbers
    return f"{lead}{num}{_SLASH}{den}{suffix}"


def _mark_glyph(m: re.Match[str]) -> str:
    text, start, end = m.string, m.start("glyph"), m.end()
    num, _, den = unicodedata.normalize("NFKC", m["glyph"]).partition("\u2044")
    after = " " if end < len(text) and text[end].isalnum() else ""
    if m["whole"] is not None:  # "2½" and "2 ½" are mixed numbers
        return f"{m['whole']}{m['sep'] or ' '}{num}{_MIXED}{den}{after}"
    before = " " if start and text[start - 1].isalnum() else ""  # "x½" keeps two words
    return f"{before}{num}{_SLASH}{den}{after}"


def _say(m: re.Match[str]) -> str:
    num, den, suffix = int(m["num"]), int(m["den"]), m["suffix"]
    sign = "minus " if m["sign"] else ""
    if m["whole"] is not None:
        return f"{sign}{cardinal(int(m['whole']))} and {_words(num, den, suffix)}"
    if not suffix and num % 5 == 0 and 0 < num < 100 and num + den == 100:
        return f"{sign}{cardinal(num)}-{cardinal(den)}"  # a split: "50/50" is "fifty-fifty"
    return sign + _words(num, den, suffix)


def mark_fractions(text: str) -> str:
    """First pass, on the raw text: each fraction's slash becomes a mark; glyphs become digits."""
    return _GLYPH.sub(_mark_glyph, _FRACTION.sub(_mark, text))


def say_marked(text: str) -> str:
    """Second pass: each marked fraction to words. A raw slash is never touched."""
    return _MARKED.sub(_say, text).translate(_UNMARK)


def speak_fractions(text: str) -> str:
    """Both passes at once, for words no other stage reads (a say-as guide)."""
    return say_marked(mark_fractions(text))
