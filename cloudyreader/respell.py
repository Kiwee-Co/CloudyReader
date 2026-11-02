"""NSB bracket respelling ("FAR-ingks") to General American IPA, espeak-ng en-us symbols.

Rules live in data/respelling_rules.json (algorithm: its `notes`). A respelling the rules cannot
place whole gives None: the caller speaks the printed word and warns, it never gets a guess.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache, cached_property
from pathlib import Path
from typing import Any

RULES_FILE = Path(__file__).parent / "data" / "respelling_rules.json"

PRIMARY = "ˈ"
SECONDARY = "ˌ"

_VOWEL_LETTERS = frozenset("aeiou")
# A syllable that ends in a silent e (dare, tube, site, nayse) takes the long vowel's own
# respelling from the table: a=ay, e=ee, i=eye, o=oh, u=oo. Before r, the r-vowel graphemes.
_LONG_VOWEL = {"a": "ay", "e": "ee", "i": "eye", "o": "oh", "u": "oo"}
_LONG_VOWEL_R = {"a": "air", "e": "eer", "i": "eyer", "o": "or", "u": "yoor"}
_SOFT_BEFORE_SILENT_E = {"c": "s", "g": "j"}  # ace, age
_SILENT_E = re.compile(r"([^aeiouy]*)([aeiou])([^aeiouy])e(s?)")
_PAIR_SILENT_E = re.compile(r"(.*[aeiouy]{2}[^aeiouy]+)e(s?)")
_DOUBLED_CONSONANT = re.compile(r"([^aeiouy])\1+")  # ill, ell, miss: one sound
# Piper's en_US phoneme_id_map has no ASCII g and no ɝ; these are the symbols it does have.
_PIPER_SAFE = str.maketrans({"g": "ɡ", "r": "ɹ", "ɝ": "ɜɹ"})
# Hyphen look-alikes that PDF and word-processor pastes put inside a respelling.
_DASHES = str.maketrans(dict.fromkeys("\u2010\u2011\u2012\u2013\u2212", "-"))
# Real guides spell the OH sound ōe (fōe-tōe-SIN-teh-sis); the case of ō carries the stress.
_MACRON_OE = re.compile(r"[\u014d\u014c][eE]?")
_ALTERNATE = re.compile(r" or ")
_SPACED_HYPHEN = re.compile(r" ?- ?")
_SHAPE = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*(?: [A-Za-z]+(?:-[A-Za-z]+)*)*")


@dataclass(frozen=True)
class RuleTable:
    """Grapheme tables. `rules` is matched longest first; the others override it per syllable."""

    rules: Mapping[str, str]
    vowel_symbols: frozenset[str]
    stressed: Mapping[str, str] = field(default_factory=dict)  # inside a CAPS syllable
    r_link: Mapping[str, str] = field(default_factory=dict)  # CAPS syllable end, vowel next
    primary: str = PRIMARY
    secondary: str = SECONDARY
    before_nucleus: bool = False  # espeak layout; False puts the mark before the onset

    def __post_init__(self) -> None:
        if not self.rules:
            raise ValueError("respelling rule table is empty")

    @cached_property
    def _longest(self) -> int:
        return max(map(len, self.rules))

    def match(self, letters: str, pos: int) -> str | None:
        """Longest grapheme of `rules` starting at `pos`, or None."""
        for size in range(min(self._longest, len(letters) - pos), 0, -1):
            if letters[pos : pos + size] in self.rules:
                return letters[pos : pos + size]
        return None

    def is_vocalic(self, ipa: str) -> bool:
        return any(symbol in self.vowel_symbols for symbol in ipa)

    def mark(self, ipa: str, stress: str) -> str:
        """Put a stress mark on one syllable's IPA."""
        if self.before_nucleus:
            for i, symbol in enumerate(ipa):
                if symbol in self.vowel_symbols:
                    return ipa[:i] + stress + ipa[i:]
        return stress + ipa


def parse_rules(doc: Mapping[str, Any]) -> RuleTable:
    """Build a RuleTable from the decoded respelling_rules.json document."""
    entries = doc["entries"]
    stress = entries.get("stress", {})
    placement = stress.get("placement", "before-syllable")
    if placement not in ("before-syllable", "before-nucleus"):
        raise ValueError(f"unknown stress placement {placement!r}")
    return RuleTable(
        rules=_pairs(entries["rules"]),
        vowel_symbols=frozenset(entries["vowel_symbols"]),
        stressed=_pairs(entries.get("stressed_rules", ())),
        r_link=_pairs(entries.get("r_link_rules", ())),
        primary=stress.get("primary", PRIMARY),
        secondary=stress.get("secondary", SECONDARY),
        before_nucleus=placement == "before-nucleus",
    )


def _pairs(pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    table: dict[str, str] = {}
    for grapheme, ipa in pairs:
        if grapheme.lower() in table:
            raise ValueError(f"respelling grapheme {grapheme!r} is listed twice")
        table[grapheme.lower()] = ipa
    return table


def load_rules(path: Path = RULES_FILE) -> RuleTable:
    return parse_rules(json.loads(path.read_text(encoding="utf-8")))


@cache
def default_rules() -> RuleTable:
    return load_rules()


def to_ipa(respelling: str, *, rules: RuleTable | None = None) -> str | None:
    """Convert bracket text such as "i-SOF-uh-guhs" to IPA, or None when any part is unknown.

    CAPS syllables are stressed: the first in a word gets the primary mark, later ones the
    secondary. Words join with one space. No CAPS means no stress mark (never guessed).
    """
    text = _clean(respelling)
    if text is None:
        return None
    table = rules if rules is not None else default_rules()
    words: list[str] = []
    lone_word = " " not in text
    for word in text.split(" "):
        ipa = _word_ipa(word, table, lone_word)
        if ipa is None:
            return None
        words.append(ipa)
    return piper_safe(" ".join(words))


def piper_safe(ipa: str) -> str:
    """Swap symbols Piper's phoneme_id_map lacks (ASCII g, r, ɝ) for the ones it has."""
    return ipa.translate(_PIPER_SAFE)


def _clean(raw: str) -> str | None:
    text = unicodedata.normalize("NFKC", raw).translate(_DASHES)
    text = _MACRON_OE.sub(lambda m: "OH" if m.group()[0] == "\u014c" else "oh", text)
    text = " ".join(text.split())
    # "pi-KAHN or PEE-kan": the first variant is the one spoken.
    text = _SPACED_HYPHEN.sub("-", _ALTERNATE.split(text, maxsplit=1)[0])
    return text if _SHAPE.fullmatch(text) else None


def _word_ipa(word: str, table: RuleTable, lone_word: bool) -> str | None:
    syllables = word.split("-")
    stress = [_stress_of(syllable) for syllable in syllables]
    if None in stress:
        return None
    # A guide that is one syllable ([jool], [saks]) is the whole word, so that syllable is stressed.
    if lone_word and len(syllables) == 1:
        stress = [True]
    # Every syllable in CAPS carries no stress information: the paste was upper-cased.
    if len(syllables) > 1 and all(stress):
        return None
    parts: list[str] = []
    marked = False
    for i, syllable in enumerate(syllables):
        vowel_next = i + 1 < len(syllables) and syllables[i + 1][0].lower() in _VOWEL_LETTERS
        low = syllable.lower()
        ipa = _syllable_ipa(low, bool(stress[i]), vowel_next, table)
        if ipa is None and i > 0 and not stress[i]:
            ipa = _syllabic(low, table, after_vowel=parts[-1][-1] in table.vowel_symbols)
        if ipa is None:
            return None
        if stress[i]:
            ipa = table.mark(ipa, table.secondary if marked else table.primary)
            marked = True
        parts.append(ipa)
    return "".join(parts)


def _stress_of(syllable: str) -> bool | None:
    if syllable.isupper():
        return True
    if syllable.islower() or syllable.istitle():  # Tee-o-door: a capital letter, not stress
        return False
    return None  # mixed case, e.g. the Na of NaCl: not a respelling


def _pieces(letters: str, stressed: bool, vowel_next: bool, table: RuleTable) -> list[str] | None:
    """Sounds of one syllable by longest-match graphemes, or None at the first unknown letter."""
    letters = _DOUBLED_CONSONANT.sub(r"\1", letters)
    pieces: list[str] = []
    pos = 0
    while pos < len(letters):
        grapheme = table.match(letters, pos)
        if grapheme is None:
            return None
        pos += len(grapheme)
        ipa = table.rules[grapheme]
        if stressed:
            ipa = table.stressed.get(grapheme, ipa)
            if vowel_next and pos == len(letters):
                ipa = table.r_link.get(grapheme, ipa)
        pieces.append(ipa)
    return pieces


def _syllable_ipa(letters: str, stressed: bool, vowel_next: bool, table: RuleTable) -> str | None:
    # One vowel per syllable: "NASA" or "hetero" are ordinary spellings, not respellings.
    pieces = _pieces(letters, stressed, vowel_next, table)
    if pieces is not None and _one_vowel(pieces, table):
        return "".join(pieces)
    long_form = _silent_e_form(letters)
    if long_form is None:
        return None
    pieces = _pieces(long_form, stressed, vowel_next, table)
    return "".join(pieces) if pieces is not None and _one_vowel(pieces, table) else None


def _one_vowel(pieces: list[str], table: RuleTable) -> bool:
    return sum(table.is_vocalic(piece) for piece in pieces) == 1


def _silent_e_form(letters: str) -> str | None:
    """Respell dare, tube, site, nayse with the long vowel and no final e, or None."""
    if letters == "one":
        return None  # the number word, not "ohn"
    match = _SILENT_E.fullmatch(letters)
    if match:
        onset, vowel, coda, tail = match.groups()
        if coda == "r":
            return onset + _LONG_VOWEL_R[vowel] + tail
        return onset + _LONG_VOWEL[vowel] + _SOFT_BEFORE_SILENT_E.get(coda, coda) + tail
    match = _PAIR_SILENT_E.fullmatch(letters)
    return match.group(1) + match.group(2) if match else None


def _syllabic(letters: str, table: RuleTable, *, after_vowel: bool) -> str | None:
    """Vowelless syllable ending in l, m or n: schwa + it (AD-n-een), or a coda after a vowel."""
    schwa = table.rules.get("uh")
    pieces = _pieces(letters, False, False, table)
    if schwa is None or not pieces or letters[-1] not in "lmn":
        return None
    if any(table.is_vocalic(piece) for piece in pieces):
        return None
    if len(letters) == 1 and after_vowel:
        return pieces[0]  # ETH-eye-n: the n closes the syllable before it
    return "".join(pieces[:-1]) + schwa + pieces[-1]
