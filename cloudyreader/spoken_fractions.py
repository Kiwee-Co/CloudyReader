"""Written fractions to spoken words: "3/9" -> "three ninths", "2 1/2" -> "two and one half".

Every voice reads a raw slash as "slash" (or drops it), so a fraction is said the way a moderator
says it. Only a plain fraction of whole numbers qualifies: a letter, a decimal point, a thousands
comma or another slash beside it ("m/s", "t1/2", "1.5/2", "1,000/3", "3/9/2024") keeps it as is.

Pipeline order: `fold_glyphs` before speak_units, so "½ m" is still a quantity; `speak_fractions`
after it, so "-3/7" has become "minus 3/7" the way a plain negative number does.
"""

from __future__ import annotations

import re
import unicodedata

from cloudyreader.units import cardinal, ordinal

__all__ = ["fold_glyphs", "speak_fractions"]

# ¼ ½ ¾, U+2150-U+215E and ↉ (0/3). U+215F is a bare "1/" with no denominator, so it stays.
_GLYPH = re.compile("[¼-¾⅐-⅞↉]")
# Nine digits at most: cardinal() stays short and int() never meets its digit limit. A leading
# zero ("01/02") is a date or a code, not a fraction.
_NUMBER = r"(?:0|[1-9][0-9]{0,8})"
_FRACTION = re.compile(
    rf"(?<![\w/.,])(?:(?P<whole>{_NUMBER})(?P<sep>[ -]))?"
    rf"(?P<num>{_NUMBER})[/\u2044\u2215](?P<den>{_NUMBER})(?i:(?:st|nd|rd|th)s?)?"
    r"(?![\w/]|[.,][0-9])"
)
_NAMES = {2: ("half", "halves"), 4: ("quarter", "quarters")}


def _words(num: int, den: int) -> str:
    """ "three ninths"; a denominator with no everyday ordinal is read "over" ("one over zero")."""
    if den in _NAMES:
        one, many = _NAMES[den]
    elif 3 <= den <= 99 or den in (100, 1000):
        one = ordinal(den).removeprefix("one ")  # 1/100 is "one hundredth"
        many = one + "s"
    else:
        return f"{cardinal(num)} over {cardinal(den)}"
    return f"{cardinal(num)} {one if num == 1 else many}"


def _speak(m: re.Match[str]) -> str:
    num, den, whole = int(m["num"]), int(m["den"]), m["whole"]
    words = _words(num, den)
    if whole is None:
        return words
    if num < den:
        return f"{cardinal(int(whole))} and {words}"
    return f"{whole}{m['sep']}{words}"  # "2 3/2" is two numbers, not a mixed number


def _fold_glyph(m: re.Match[str]) -> str:
    text, start, end = m.string, m.start(), m.end()
    num, _, den = unicodedata.normalize("NFKC", m.group()).partition("\u2044")
    # A space after a digit makes "2½" the mixed number 2 1/2; beside a letter it keeps the words.
    before = " " if start and text[start - 1].isalnum() else ""
    after = " " if end < len(text) and text[end].isalnum() else ""
    return f"{before}{num}/{den}{after}"


def fold_glyphs(text: str) -> str:
    """ "½" -> "1/2", "2½" -> "2 1/2". Digits, so the unit stage still reads "½ m" as meters."""
    return _GLYPH.sub(_fold_glyph, text)


def speak_fractions(text: str) -> str:
    """Fractions, mixed numbers and fraction glyphs to words; anything else stays as written."""
    return _FRACTION.sub(_speak, fold_glyphs(text))
