"""Parse pasted National Science Bowl questions into `Question` objects.

Pastes come from PDFs and web pages: hard wraps, odd whitespace and missing header parts are
the normal case. Parsing is line- and regex-based, never a hard failure on odd input.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from functools import cache

from cloudyreader.models import Choice, Fmt, Kind, Question, Respelling
from cloudyreader.units import load_entries

__all__ = ["QuestionParser", "extract_guides", "parse"]

# BOM, zero-width characters and soft hyphens are invisible but break header and word matching.
_INVISIBLE = {ord(c): None for c in "\ufeff\u200b\u200c\u200d\u2060\u00ad"}

# PDF symbol-font leftovers land in the private-use area: the few glyphs with a meaning become
# their Unicode symbol; stacked-bracket pieces and U+FFFD are blanks.
_PDF_GLYPHS = {cp: " " for cp in (*range(0xE000, 0xF900), 0xFFFD)} | {
    0xF0B0: "°",
    0xF071: "θ",
    0xF02D: "−",
    0xF0D6: "√",
    0xF0E0: "→",
}
# Math italics (U+1D465 ...) are plain letters to a reader; NFKC folds them and nothing else.
_MATH_ALNUM_RE = re.compile("[\U0001d400-\U0001d7ff]")

_LETTER = r"[^\W\d_]"
_DASHES = "–—-"

_HEADER_RE = re.compile(rf"\s*(?P<token>toss[\s-]?up|bonus)\b[\s:.{_DASHES}]*", re.IGNORECASE)
# `N)` always; `N.` only before whitespace, so a leading decimal such as 0.3 is not a number.
_NUMBER_RE = re.compile(r"\s*\*?\s*(?P<num>\d{1,4})(?:\s*\)|\.(?=\s|$))\s*")
# A bare number (the `)` lost in extraction) counts only before a category and a format label.
_BARE_NUMBER_RE = re.compile(r"\s*\*?\s*(?P<num>\d{1,4})\s+")
_GLUED_FORMAT_RE = re.compile(r"(?<=[A-Z])(?=(?:Multiple|Short)\b)")

# PDF text leaves rule lines, round titles ("ROUND ROBIN 2"), page footers ("Middle School Round 1
# Page 3", "PAGE 4") and an editorial omission note between the questions.
_RULE_RE = re.compile(r"~{3,}|\*{3,}|_{3,}|={3,}|-{5,}")
_TITLE_WORDS = (
    "double single elimination round robin middle high school junior senior regional national "
    "science bowl nsb mini set"
).replace(" ", "|")
_TITLE_RE = re.compile(
    rf"(?:\d{{4}}\s+)?(?:(?:{_TITLE_WORDS})\b[\s–—~,.-]*)*(?:round|robin|set)\s*\d{{1,2}}(?:\s*[A-Za-z])?",
    re.IGNORECASE,
)
_SCHOOL_RE = re.compile(r"(?:middle|high)\s+school", re.IGNORECASE)
_PAGE_RE = re.compile(r"\bpage\s*\d{1,3}$", re.IGNORECASE)
_FOOTER_WORD_RE = re.compile(
    r"\b(?:round|set|bowl|nsb|regional|events?|school|elimination|robin)\b|\d{4}", re.IGNORECASE
)
_OMITTED_RE = re.compile(r"the\s+(?:toss-?up|bonus)\b.*\b(?:omitted|removed|deleted)\.?", re.I)
# A stacked fraction or exponent is extracted as short, wordless lines beside its label.
_WORD_RE = re.compile(rf"{_LETTER}{{4,}}")

# `ANWER:` is a typo that occurs in a real round.
_ANSWER_LINE_RE = re.compile(r"\s*(?:(?i:ans?wer)\s*[:：]|ANSWER\b[:：]?)\s*")
# Clipboards lose newlines, so `ANSWER:` and `Answer:` are also recognised mid-line, but not the
# label `Short Answer:`.
_ANSWER_INLINE_RE = re.compile(r"(?<=\s)(?<![Ss][Hh][Oo][Rr][Tt]\s)(?:ANSWER|Answer)\s*[:：]\s*")

_CATEGORY_TOKEN_RE = re.compile(r"[A-Z][A-Z'’/-]*|&")
_TITLE_TOKEN_RE = re.compile(rf"{_LETTER}[^\W\d_'’/-]*(?:['’/-]{_LETTER}+)*|&")
_TITLE_SMALL_WORDS = frozenset({"and", "of", "the", "in", "for", "&"})
_MAX_TITLE_CATEGORY_TOKENS = 6
_SEPARATORS = frozenset({"-", "–", "—", ":", "|"})
_FORMATS = {
    "multiple-choice": Fmt.MULTIPLE_CHOICE,
    "multiplechoice": Fmt.MULTIPLE_CHOICE,
    "short-answer": Fmt.SHORT_ANSWER,
    "shortanswer": Fmt.SHORT_ANSWER,
}
# Without a printed format label an unknown capitalised word is more likely a stem start.
_CATEGORY_WORDS = frozenset(
    "BIOLOGY CHEMISTRY PHYSICS MATH MATHEMATICS ENERGY EARTH SPACE SCIENCE SCIENCES GENERAL LIFE "
    "PHYSICAL AND & COMPUTER ASTRONOMY".split()
)

_MARKER_RE = re.compile(r"(?<![^\s])(?P<letter>[WXYZwxyz])(?P<delim>[).:])")
_CHOICE_LETTERS = ("W", "X", "Y", "Z")

# A hyphen after these stays: "half-life" and "well-known" are not one word.
_KEEP_HYPHEN_AFTER = frozenset(
    "half self well high low long short cross first second third one two three four five six "
    "seven eight nine ten".split()
)
_TRAILING_ALPHA_RE = re.compile(rf"(?<![\w-])({_LETTER}{{2,}})-$")
_LEADING_ALPHA_RE = re.compile(rf"{_LETTER}+")
_OPEN_PAREN_GUIDE_RE = re.compile(
    r"\(\s*(?:read\s+as|pronounced|pronunciation\s*:)\s*:?[^()]*$", re.I
)

# A guide is `[...]`, `(read as: ...)` or `(pronounced: ...)`; a trailing `Read as: ...` joins them.
_BRACKET_RE = re.compile(
    r"\[([^\[\]]*)\]"
    r"|\(\s*(?:read\s+as\s*:?|pronounced\s*:?|pronunciation\s*:|read(?=\s*[\"“]))\s*((?:[^()]|\([^()]*\))*?)\s*\)",
    re.IGNORECASE,
)
_OPEN_READ_AS_RE = re.compile(r"\(\s*(?:read\s+as\s*:?|pronounced\s*:?)\s*[^()]+$", re.IGNORECASE)
_BARE_READ_AS_RE = re.compile(r"(?<![(\w])read\s+as\s*:\s*", re.IGNORECASE)
# A lowercase one-word bracket ("[jool]") is a guide unless it is a bracketed editorial note.
_NOTE_WORDS = frozenset({"sic", "note", "see", "ibid", "emphasis", "added", "edited"})
_NOTE_RE = re.compile(r"\*?\s*note\b|.*\b(?:must|accept|students)\b", re.IGNORECASE)
_GUIDE_WORD = rf"{_LETTER}+(?:['’-]{_LETTER}+)*"
_GUIDE_WORD_RE = re.compile(_GUIDE_WORD)
_VOWEL_DIGRAPH_RE = re.compile(r"[AEIOUY]{2}")
_VOWEL_GROUP_RE = re.compile(r"[AEIOUY]+")
_AFTER_WORD_RE = re.compile(r"[^\W_][\"'’”]*$")
_ALTERNATIVE_RE = re.compile(r"\s+or\s+")
# All-caps acronyms that look like a lone stressed syllable.
_ACRONYMS = frozenset({"AIDS", "NOAA", "UAE", "OPEC", "NAACP", "HIV"})
_SPELL_RE = re.compile(r"[A-Za-z0-9](?:(?:\.\s?|-)[A-Za-z0-9])+\.?(?:[’']s)?")
_HYPHEN_WORD_RE = re.compile(rf"{_LETTER}+(?:['’-]{_LETTER}+)+")
_WORD2_RE = re.compile(rf"{_LETTER}{{2,}}")
_NUMBER_WORDS = frozenset(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety "
    "hundred thousand million half halves third thirds quarter quarters fourth fourths fifth "
    "fifths sixth sixths seventh sevenths eighth eighths ninth ninths tenth tenths".split()
)
# `copper(I) [copper-one]`: an element and an oxidation state, said as the guide spells it.
_ION_RE = re.compile(rf"({_LETTER}+)-(?:one|two|three|four|five|six|seven)", re.IGNORECASE)
# One-word say-as brackets: "x2 [squared]" is how to say x2, not how to pronounce it.
_SAY_AS_WORDS = frozenset({"squared", "cubed", "prime", "degrees", "percent"})
_MATHY_RE = re.compile(r"[()\[\]=<>+]")
_CHOICE_MARKER_RE = re.compile(r"[WXYZ]\)")
_ARROWS = frozenset("→⟶⇒⟹↔⇌")
_MATH_CHARS = frozenset("+−–-×÷*/^=<>≤≥≠≈±≧≦|│⏐()[]{}√π∅∞→⟶⇒·•%!°∘\u2010\u2011\u2012")
_OPERATOR_CHARS = frozenset("+−×÷*/^=<>≤≥≠≈±≧≦√")
# Function names belong to a printed expression: "sinθ1 = sin θ2" is one surface for its guide.
# Copied from formulas._FUNCTIONS, not imported: the parser must not depend on the speech stages.
_FUNCTION_NAMES = frozenset(
    "sin cos tan sec csc cot sinh cosh tanh arcsin arccos arctan log ln exp det lim max min".split()
)
# Words that mark a bracket as spoken maths; two of them and no printed expression: say them.
_SPOKEN_MATH = frozenset(
    "over squared cubed plus minus times equals fraction numerator denominator absolute root power "
    "negative parenthesis quantity divided row sine cosine tangent theta log base factorial".split()
)


@dataclass(frozen=True)
class _Marker:
    start: int
    end: int
    letter: str
    delim: str
    lower: bool
    line_start: bool


def _squash(text: str) -> str:
    return " ".join(text.split())


def _clean(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw).translate(_INVISIBLE)
    text = _MATH_ALNUM_RE.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text)
    return text.translate(_PDF_GLYPHS)


def _is_noise(line: str) -> bool:
    """A rule line, round title, page footer or omission note: never part of a question."""
    text = line.strip()
    if any(r.fullmatch(text) for r in (_RULE_RE, _TITLE_RE, _SCHOOL_RE, _OMITTED_RE)):
        return True
    page = _PAGE_RE.search(text)
    return bool(page) and (page.start() == 0 or bool(_FOOTER_WORD_RE.search(text[: page.start()])))


def _is_fragment(line: str) -> bool:
    text = line.strip()
    return len(text) <= 40 and not _WORD_RE.search(text)


def _glue(prev: str, nxt: str) -> str:
    """Join two wrapped lines. A plain word split by a hyphen is rejoined, a compound is not."""
    if len(prev) < 2 or prev[-1] != "-" or not prev[-2].isalnum():
        return f"{prev} {nxt}"
    if _in_guide(prev):
        return prev + nxt  # a guide wrapped after a syllable hyphen keeps it ("[SINK-row-trawn]")
    left = _TRAILING_ALPHA_RE.search(prev)
    right = _LEADING_ALPHA_RE.match(nxt)
    if (
        left
        and right
        and right.group().islower()
        and left.group(1).lower() not in _KEEP_HYPHEN_AFTER
    ):
        return prev[:-1] + nxt
    return prev + nxt


def _in_guide(text: str) -> bool:
    """True while `text` ends inside an open `[` or `(read as:` / `(pronounced:` group."""
    return text.rfind("[") > text.rfind("]") or bool(_OPEN_PAREN_GUIDE_RE.search(text))


def _join_lines(lines: list[str]) -> str:
    out = ""
    for line in lines:
        piece = line.strip()
        if piece:
            out = _glue(out, piece) if out else piece
    return _squash(out)


def _match_header(line: str) -> tuple[Kind, str] | None:
    """Return (kind, rest of the line) for a TOSS-UP / BONUS header, else None."""
    m = _HEADER_RE.match(line)
    if not m:
        return None
    rest = line[m.end() :]
    token = m.group("token")
    # Lower-case "bonus points ..." inside a stem must not read as a header.
    if not (token.isupper() or not rest.strip() or _NUMBER_RE.match(rest)):
        return None
    return (Kind.BONUS if token.lower() == "bonus" else Kind.TOSS_UP), rest


def _match_format(tokens: list[str], i: int) -> tuple[Fmt | None, int]:
    word = tokens[i].lower().rstrip(":.,;")
    if word in _FORMATS:
        return _FORMATS[word], 1
    nxt = tokens[i + 1].lower().rstrip(":.,;") if i + 1 < len(tokens) else ""
    if (word, nxt) in {("multiple", "choice"), ("mutliple", "choice")}:  # sic: typo in a round
        return Fmt.MULTIPLE_CHOICE, 2
    if (word, nxt) == ("short", "answer"):
        return Fmt.SHORT_ANSWER, 2
    return None, 0


def _category_word(token: str) -> str | None:
    """`SCIENCE.` -> `SCIENCE`; None unless the token is an all-caps category word."""
    word = token.rstrip(".:")
    return word if _CATEGORY_TOKEN_RE.fullmatch(word) else None


def _join_category(words: list[str]) -> str | None:
    """`MATH Math Short Answer` prints the category twice."""
    kept = [w for i, w in enumerate(words) if i == 0 or w.lower() != words[i - 1].lower()]
    return " ".join(kept) or None


def _scan_title_case(tokens: list[str]) -> tuple[str | None, Fmt | None, str] | None:
    """`Life Science - Multiple Choice stem`: a Title Case category before a printed label."""
    for i in range(1, min(len(tokens), _MAX_TITLE_CATEGORY_TOKENS + 1)):
        fmt, used = _match_format(tokens, i)
        if fmt is None:
            continue
        words = [t for t in tokens[:i] if t not in _SEPARATORS]
        if not words or not all(
            _TITLE_TOKEN_RE.fullmatch(w) and (w[0].isupper() or w in _TITLE_SMALL_WORDS)
            for w in words
        ):
            return None
        rest = tokens[i + used :]
        while rest and rest[0] in _SEPARATORS:
            rest = rest[1:]
        return _join_category(words), fmt, " ".join(rest)
    return None


def _scan_dashed_category(tokens: list[str]) -> tuple[str | None, Fmt | None, str] | None:
    """`Energy – Artificial photosynthesis ...`: a known category and a dash, no printed format."""
    for i in range(1, min(len(tokens) - 1, _MAX_TITLE_CATEGORY_TOKENS + 1)):
        if tokens[i] not in _SEPARATORS:
            continue
        words = tokens[:i]
        if all(w.upper() in _CATEGORY_WORDS for w in words) and tokens[i + 1][:1].isupper():
            return " ".join(words), None, " ".join(tokens[i + 1 :])
        return None
    return None


def _scan_label(flat: str, *, structured: bool) -> tuple[str | None, Fmt | None, str]:
    """Split `CATEGORY Format stem` into (category, printed format, stem).

    `structured` = a header or number was seen, which makes a Title Case category believable.
    """
    # `ENERGYMultiple Choice`: PDF extraction glued the category to the format.
    glued = _GLUED_FORMAT_RE.search(flat)
    if glued and glued.start() < 60:
        flat = f"{flat[: glued.start()]} {flat[glued.start() :]}"
    tokens = flat.split()
    category: list[str] = []
    i = 0
    while i < len(tokens):
        fmt, used = _match_format(tokens, i)
        if fmt is not None:
            rest = tokens[i + used :]
            while rest and rest[0] in _SEPARATORS:
                rest = rest[1:]
            return _join_category(category), fmt, " ".join(rest)
        if tokens[i] in _SEPARATORS:
            i += 1
        elif (word := _category_word(tokens[i])) is not None:
            category.append(word)
            i += 1
        else:
            break
    titled = _scan_title_case(tokens) if structured else None
    titled = titled or (_scan_dashed_category(tokens) if structured else None)
    if titled:
        return titled
    if category and all(word in _CATEGORY_WORDS for word in category):
        return _join_category(category), None, " ".join(tokens[i:])
    return None, None, " ".join(tokens)


def _split_head(flat: str, *, header: bool) -> tuple[int | None, str | None, Fmt | None, str]:
    m = _NUMBER_RE.match(flat)
    if m is None:
        bare = _BARE_NUMBER_RE.match(flat)  # `46 MATH Multiple Choice ...`: the `)` was lost
        if bare and _scan_label(flat[bare.end() :], structured=True)[1] is not None:
            m = bare
    number = int(m.group("num")) if m else None
    category, fmt, stem = _scan_label(flat[m.end() :] if m else flat, structured=header or bool(m))
    return number, category, fmt, stem


def _label_head(line: str) -> bool:
    """A line that opens a question body: `N)`, or a bare number before a category and format."""
    if _NUMBER_RE.match(line):
        return True
    bare = _BARE_NUMBER_RE.match(line)
    return bool(bare) and _scan_label(line[bare.end() :], structured=True)[1] is not None


def _drop_stray_fragments(lines: list[str]) -> list[str]:
    """Drop stacked-fraction pieces that sit between a bare header and its label line."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        header = _match_header(lines[i])
        out.append(lines[i])
        i += 1
        if not header or header[1].strip():
            continue
        k, fragments = i, []
        while k < len(lines) and len(fragments) < 4:
            if not lines[k].strip():
                k += 1
            elif _is_fragment(lines[k]) and not _label_head(lines[k]):
                fragments.append(k)
                k += 1
            else:
                break
        if fragments and k < len(lines) and _label_head(lines[k]):
            out.extend(lines[j] for j in range(i, k) if j not in fragments)
            i = k
    return out


def _find_markers(text: str) -> list[_Marker]:
    found = []
    for m in _MARKER_RE.finditer(text):
        delim = m.group("delim")
        after = text[m.end() : m.end() + 1]
        # `W)Speed` is fine; `X.rays` or `Y:00` are not markers.
        if delim != ")" and after and not after.isspace():
            continue
        bol = text.rfind("\n", 0, m.start()) + 1
        letter = m.group("letter")
        found.append(
            _Marker(
                m.start(),
                m.end(),
                letter.upper(),
                delim,
                letter.islower(),
                not text[bol : m.start()].strip(),
            )
        )
    return found


def _last_chain(pool: list[_Marker]) -> list[_Marker] | None:
    """The last W marker that is followed by X, Y and Z in order."""
    for w in reversed([k for k in pool if k.letter == "W"]):
        chain = [w]
        for letter in _CHOICE_LETTERS[1:]:
            nxt = next((k for k in pool if k.letter == letter and k.start >= chain[-1].end), None)
            if nxt is None:
                break
            chain.append(nxt)
        else:
            return chain
    return None


def _loose_chain(markers: list[_Marker]) -> list[_Marker] | None:
    """Four line-start `)` markers in a row that are swapped (`W Y X Z`) or have a wrong first."""
    starts = [k for k in markers if k.line_start and k.delim == ")"]
    for i in range(len(starts) - 4, -1, -1):
        window = starts[i : i + 4]
        letters = [k.letter for k in window]
        if sorted(letters) == list(_CHOICE_LETTERS):
            return window
        if letters[1:] == list(_CHOICE_LETTERS[1:]):  # `Y X Y Z`: the first label is a typo
            return [replace(window[0], letter="W"), *window[1:]]
    return None


def _find_choices(text: str) -> list[_Marker] | None:
    """Pick the W-X-Y-Z marker run; stem initials such as `W. H. Bragg` have no X-Y-Z behind."""
    markers = _find_markers(text)
    for line_start_only in (True, False):
        for delim in (")", ".", ":"):
            for lower in (False, True, None):  # None: `w) a  X) b  Y) c  Z) d` mixes the cases
                pool = [
                    k
                    for k in markers
                    if k.delim == delim
                    and (lower is None or k.lower == lower)
                    and (k.line_start or not line_start_only)
                ]
                chain = _last_chain(pool)
                if chain:
                    return chain
    return _loose_chain(markers)


def _split_answer(lines: list[str]) -> tuple[list[str], str | None]:
    for i, line in enumerate(lines):
        m = _ANSWER_LINE_RE.match(line)
        before: list[str] = lines[:i]
        if not m:
            m = _ANSWER_INLINE_RE.search(line)
            if not m:
                continue
            before = [*before, line[: m.start()]]
        answer = _join_lines([line[m.end() :], *lines[i + 1 :]])
        return before, answer or None
    return lines, None


def _tighten(text: str) -> str:
    """PDF wraps leave stray spaces around the syllable hyphens ("FYE- lum")."""
    return re.sub(r"\s*-\s*", "-", text)


def _is_number_phrase(text: str) -> bool:
    """`one-seventh`, `two four`, `3-prime`: number words, which are said, never pronounced."""
    units = [u for u in re.split(r"[-\s]+", text.lower()) if u]
    return all(u in _NUMBER_WORDS or u == "prime" or u.isdigit() for u in units) and any(
        u in _NUMBER_WORDS or u == "prime" for u in units
    )


def _is_syllable(word: str) -> bool:
    """A lone all-caps syllable such as JOOL or NICH (one vowel run), not an acronym like DNA."""
    return (len(word) >= 3 and bool(_VOWEL_DIGRAPH_RE.search(word))) or (
        len(word) >= 4 and len(_VOWEL_GROUP_RE.findall(word)) == 1
    )


def _is_guide(content: str) -> bool:
    """A pronunciation guide: syllables joined by hyphens, or one lone syllable."""
    tokens = [t for t in content.split() if t != "or"]
    words = [t for t in tokens if not t.isdigit()]
    if not words or not all(_GUIDE_WORD_RE.fullmatch(w) for w in words):
        return False
    if len(words) > 1 and any(w.lower() in _SPOKEN_MATH for w in words):
        return False  # "99 hun-DREDTHS minus three fourths" is a reading, not a respelling
    hyphenated = [w for w in words if "-" in w]
    if hyphenated:
        if all(_is_number_phrase(w) for w in hyphenated):
            return False
        units = [u for w in hyphenated for u in w.split("-")]
        return not all(len(u) == 1 for u in units)  # `A-T-P` is spelled letters, not a guide
    if len(words) != len(tokens):
        return False  # a bare number is no syllable
    if len(words) == 1 and words[0].islower():
        return len(words[0]) >= 3 and words[0] not in _NOTE_WORDS
    stressed = [w for w in words if w.isupper() and _is_syllable(w) and w not in _ACRONYMS]
    return (
        all(w.isupper() or w.islower() for w in words)
        and not any(w in _ACRONYMS for w in words)
        and len(stressed) >= min(2, len(words))
    )


def _word_count(content: str) -> int:
    """Words a guide covers: `tek-NEE-shee-um 99 M` is one, `mi-KAY-lis MEN-tun` two."""
    first = _ALTERNATIVE_RE.split(content)[0].split()
    named = [
        t for t in first if len(re.sub(r"[^A-Za-z]", "", t)) >= 2 and t.lower() not in _NUMBER_WORDS
    ]
    return max(1, len(named))


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def _similarity(content: str, text: str) -> float:
    """How alike a respelling and a printed word are, letter by letter (0 to 1)."""
    guide, word = _letters(_ALTERNATIVE_RE.split(content)[0]), _letters(text)
    return SequenceMatcher(None, guide, word).ratio() if guide and word else 0.0


def _guide_units(content: str) -> set[str]:
    first = _ALTERNATIVE_RE.split(content)[0].split()
    return {unit.lower() for token in first for unit in token.split("-") if unit}


def _compound_surface(token: str, content: str) -> str:
    """`non-Newtonian [noo-TOH-nee-un]`: the parts of a compound the guide respells.

    A part the guide does not spell and that is a bare number or letter (`258`, `D`) stays out;
    of the spans that fit about equally well the narrowest wins, because speaking the part the
    guide leaves alone is harmless and dropping it is not.
    """
    parts = token.split("-")
    if len(parts) < 2 or not all(parts):
        return token
    units = _guide_units(content)
    said_number = any(u.isdigit() or u in _NUMBER_WORDS for u in units)

    def spelled(part: str) -> bool:  # `2-thiopyridone [two-thigh-oh-...]`: the guide says the 2
        digits = bool(re.fullmatch(r"[\d.,]+", part))
        return (
            part.lower() in units
            or (digits and said_number)
            or any(u.isdigit() and u in part for u in units)
        )

    def stub(part: str) -> bool:
        return bool(re.fullmatch(r"[\d.,]+|[^\W\d_]", part)) and not spelled(part)

    last = len(parts)
    spans = [
        "-".join(parts[i:j])
        for i in range(last)
        for j in range(i + 1, last + 1)
        if not stub(parts[i])
        and not stub(parts[j - 1])
        and not (spelled(parts[0]) and i > 0)
        and not (spelled(parts[-1]) and j < last)
    ]
    if not spans:
        return token
    scores = {span: _similarity(content, span) for span in spans}
    near = [span for span, score in scores.items() if score >= max(scores.values()) - 0.05]
    return min(near, key=lambda span: (span.count("-"), -token.rfind(span)))


def _headword(prefix: str, content: str) -> str:
    """The word the guide respells: as many words as the guide has, else the likeliest nearby one.

    A guide may follow the noun it qualifies (`Haber-Bosch process [HA-buhr BOSH]`), so words up
    to two back compete on letter likeness; the word just before the guide wins unless another
    one fits clearly better.
    """
    tokens = prefix.split()
    while tokens and not re.search(r"[^\W_]", tokens[-1]):
        tokens.pop()  # a dangling dash is no word
    if not tokens:
        return ""
    if _trim(tokens[-1]).isdigit() and len(tokens) > 1:  # `Maffei 1 [MAF-eye-one]`
        tokens[-2:] = [f"{tokens[-2]} {tokens[-1]}"]
    count = _word_count(content)
    for k in range(1, min(count, len(tokens)) + 1):
        phrase = " ".join(tokens[-k:])
        if count > 1 and len(re.split(r"[\s-]+", phrase)) == count:
            return _trim(phrase)
    near = _trim(tokens[-1])
    best_score, best = _similarity(content, near), near
    base_score = best_score
    first = _ALTERNATIVE_RE.split(content)[0].split()
    said_number = bool(first) and re.split(r"[-\s]+", first[-1])[-1].lower() in _NUMBER_WORDS
    for far in range(min(3, len(tokens))):
        for length in range(1, count + int(said_number) + 1):  # `meiosis I [my-OH-sis one]`
            if len(tokens) - far - length < 0:
                break
            window = _trim(" ".join(tokens[len(tokens) - far - length : len(tokens) - far]))
            score = _similarity(content, window) - 0.1 * far
            if score > best_score:
                best_score, best = score, window
    if best_score - base_score < 0.15:
        best = near
    return best if " " in best or "-" not in best else _compound_surface(best, content)


def _trim(phrase: str) -> str:
    return phrase.strip("\"'“”‘’()[]{}.,;:!?")


def _is_operator(token: str) -> bool:
    return bool(token) and all(c in _MATH_CHARS for c in token)


def _math_token(token: str, following: str | None) -> bool:
    """Part of a printed expression: digits, operators, a lone variable, `f(x)`; never a word."""
    core = token.strip(",;")
    if not core or token.endswith((":", ";")) or _HYPHEN_WORD_RE.fullmatch(core):
        return False
    if any(c.isdigit() for c in core):
        return True
    letters = [c for c in core if c.isalpha()]
    if not letters:
        return _is_operator(core)
    if core.lower() in _FUNCTION_NAMES:
        return True
    if any(c.isalpha() and not c.isascii() for c in core) and len(core) > 1:
        return True  # `cscθ`: Greek letters beside Latin ones only occur in formulas
    runs = re.findall(rf"{_LETTER}+", core)
    if any(c in _OPERATOR_CHARS for c in core) and any(len(r) == 1 for r in runs):
        return True  # `eV/d`, `a+b`; not `and/or`
    if core[0] in _MATH_CHARS and 2 <= len(core) <= 4 and core[1:].isalpha():
        return True  # `+ab`, `−x`, `√a`: a signed term
    if len(core) == 1:  # `a` and `I` are also words: only an operator after them makes a variable
        return core not in "aAI" or (following is not None and following[0] in _MATH_CHARS)
    return len(letters) <= 2 and any(c in "()[]|│⏐" for c in core)


def _math_run(before: str) -> str:
    """The printed expression that ends `before`: the words a say-as guide stands in for."""
    tokens = before.split()
    start = len(tokens)
    while start > 0 and _math_token(
        tokens[start - 1], tokens[start] if start < len(tokens) else None
    ):
        start -= 1
    if start == 0 and tokens and _CHOICE_MARKER_RE.fullmatch(tokens[0]):
        start = 1  # an answer such as `Y) 6 (read as: six)` opens with the choice letter
    return " ".join(tokens[start:])


@cache
def _unit_names() -> frozenset[str]:
    """Spelled-out unit names from units.json ("meters", "kilograms"), lowercase."""
    names: set[str] = set()
    for entry in load_entries("units").values():
        names.update(str(entry.get(key, "")).lower() for key in ("singular", "plural"))
        names.update(str(alias).lower() for alias in entry.get("aliases", ()))
    return frozenset(names - {""})


def _math_run_before_unit(before: str) -> str:
    """The expression before a trailing unit word: `6.4 x 106` in `6.4 x 106 meters`.

    The word must be a unit and the run more than a bare integer: `the 2 by 2 matrix` is not one.
    """
    tokens = before.split()
    if len(tokens) > 1 and tokens[-1].lower() in _unit_names():
        run = _math_run(" ".join(tokens[:-1]))
        if run and not run.isdigit():
            return run
    return ""


def _letter_surface(token: str, content: str) -> bool:
    """A genotype or letter name such as `Bb`, `(rr)` or `SSS` (`side, side, side`)."""
    core = token.strip("()[].,;:")
    if not core.isalpha():
        return False
    if (
        len(core) <= 2
        or sum(a.islower() != b.islower() for a, b in zip(core, core[1:], strict=False)) >= 3
    ):
        return True
    words = re.split(r"[,\s]+", content)
    return (
        core.isupper()
        and len(words) == len(core)
        and all(w[:1].upper() == c for w, c in zip(words, core, strict=True))
    )


def _ion_surface(before: str, tight: str) -> str:
    """The `copper(I)` or `lead (II)` a `copper-one` / `lead-two` guide stands in for, else ''."""
    ion = _ION_RE.fullmatch(tight)
    tokens = before.split()
    for k in (1, 2):
        if ion and len(tokens) >= k and tokens[-k].lower().startswith(ion.group(1).lower()):
            return " ".join(tokens[-k:])
    return ""


def _alnum_key(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text).upper()


def _letters_only(key: str) -> str:
    return re.sub(r"\d", "", key)


def _judge(before: str, content: str, *, paren: bool) -> Respelling | str | None:
    """Classify one bracket group that follows `before`.

    A `Respelling` records a guide (the bracket goes, the surface stays in the text), a string
    replaces the bracket ("" drops it: a moderator note), None leaves it as written.
    """
    if not content:
        return None
    tight = _tighten(content)
    if paren:
        tight = re.sub(r"[()]", "", tight)  # `(H)URR-bi-vohr`: an optional sound is still a sound
    last = before.split()[-1] if before.split() else ""
    if not paren and " " in content and _NOTE_RE.match(content):
        return ""
    if content.lower() == "yields":  # the arrow it names; without an arrow the word stays
        return Respelling(last, content, "spoken") if last in _ARROWS else content
    if _SPELL_RE.fullmatch(content):
        key, surface_key = _alnum_key(content), _alnum_key(last)
        spelled, written = _letters_only(key), _letters_only(surface_key)
        if key == surface_key or (len(written) >= 2 and spelled.endswith(written)):
            return Respelling(last.strip(".,;:!?\"'“”‘’"), content, "spell")
    if len(last) == 1 and not last.isascii() and re.fullmatch(rf"{_LETTER}+", content):
        return Respelling(last, content, "spoken")  # `π [pi]`: say the symbol
    if ion := _ion_surface(before, tight):
        return Respelling(ion, content, "spoken")
    syllables = not _is_number_phrase(tight) and content.lower() not in _SAY_AS_WORDS
    if syllables and content.split().count("-") < 2:  # " - " twice is a dash list, not syllables
        lone = paren and len(content.split()) == 1 and bool(_GUIDE_WORD_RE.fullmatch(content))
        if (
            (_is_guide(tight) or lone)
            and before.strip()
            and (paren or _AFTER_WORD_RE.search(before))
        ) and (head := _headword(before, tight)):
            return Respelling(head, tight)
    surface = _math_run(before)
    if not surface:
        surface = last if _letter_surface(last, content) else _math_run_before_unit(before)
    wordy = " " in content and bool(_WORD2_RE.search(content))
    if surface and (paren or wordy or _is_number_phrase(tight) or content.lower() in _SAY_AS_WORDS):
        return Respelling(surface, content, "spoken")
    if paren or len(_SPOKEN_MATH & set(content.lower().split())) >= 2:
        return content  # the printed expression is lost (a stacked fraction): say the words
    return None


def _wrap_trailing_read_as(text: str) -> str:
    """`... Read as: words` (parentheses lost, or just the `(`) becomes `... (read as: words)`."""
    found = list(_BARE_READ_AS_RE.finditer(text))  # only the final one can reach the end
    last = found[-1] if found else None
    tail = text[last.end() :] if last else ""
    if last is None or "(" in tail or tail.count(")") > 1:
        return text
    head = text[: last.start()]
    if head.count("(") > head.count(")"):
        return text  # already inside a parenthesis: "(also read as: 3)"
    words, _, rest = tail.partition(")")  # a lone `)` closes the guide: "... equals 1)?"
    if not words.strip():
        return text
    return f"{text[: last.start()]}(read as: {words.strip()}){rest}"


def _close_open_read_as(text: str) -> str:
    """`(read as: words?`: the closing parenthesis was lost; close it before the final mark."""
    if not _OPEN_READ_AS_RE.search(text):
        return text
    body = text.rstrip()
    tail = body[len(body.rstrip(".?!,;:")) :]
    return f"{body[: len(body) - len(tail)]}){tail}"


def _close_open_bracket(text: str) -> str:
    """`Thalamus [THAL-uh-mus`: a source typo that leaves the bracket open to the end."""
    if text.rfind("[") <= text.rfind("]"):
        return text
    body = text.rstrip()
    tail = body[len(body.rstrip(".?!,;:")) :]
    inside = body[body.rfind("[") + 1 : len(body) - len(tail)]
    if _MATHY_RE.search(inside):
        return text  # `[–10, 5)` is a half-open interval, not a guide
    return f"{body[: len(body) - len(tail)]}]{tail}"


def extract_guides(text: str) -> tuple[str, tuple[Respelling, ...]]:
    """Strip guides (phonetic, say-as, spelled) and notes from `text`; return text and guides."""
    text = _close_open_read_as(
        _close_open_bracket(re.sub(r"\[\s*\[", "[", _wrap_trailing_read_as(text)))
    )
    guides: list[Respelling] = []
    built = ""
    pos = 0
    for m in _BRACKET_RE.finditer(text):
        paren = m.group(1) is None
        content = _squash((m.group(2) if paren else m.group(1)) or "").strip('"“”')
        prefix = built + text[pos : m.start()]
        before = prefix.rstrip()
        verdict = _judge(before, content, paren=paren)
        gap = " " if text[m.end() : m.end() + 1].isalnum() else ""  # `[LIH-gund]binding`
        if verdict is None:
            built = prefix + m.group(0)
        elif isinstance(verdict, Respelling):
            guides.append(verdict)
            built = before + gap
        else:
            built = prefix + verdict + gap if verdict else before + gap
        pos = m.end()
    return _squash(built + text[pos:]), tuple(guides)


def _answered(lines: list[str]) -> bool:
    return any(_ANSWER_LINE_RE.match(line) or _ANSWER_INLINE_RE.search(line) for line in lines)


def _is_complete(lines: list[str]) -> bool:
    """True once a question has its answer line or its W-X-Y-Z choices."""
    return _answered(lines) or _find_choices("\n".join(lines)) is not None


def _reads_like_stem(text: str) -> bool:
    """A question, not an answer item: a `?`, or a longer mixed-case sentence (answers are caps)."""
    return "?" in text or (len(text.split()) > 4 and text != text.upper())


def _opens_question(line: str) -> bool:
    """`LIFE SCIENCE Short Answer What ...`: a category or stem after a format label, no number."""
    category, fmt, stem = _scan_label(line, structured=True)
    return fmt is not None and bool(category or stem)


def _has_body(lines: list[str]) -> bool:
    for line in lines:
        header = _match_header(line)
        if line.strip() and not (header and not header[1].strip()):
            return True
    return False


def _opened_by_header(lines: list[str]) -> bool:
    first = next((line for line in lines if line.strip()), "")
    return _match_header(first) is not None


def _open_number(lines: list[str]) -> int | None:
    """The number of the question the lines hold: on its header line or on its first body line."""
    texts = (h[1] if (h := _match_header(line)) else line for line in lines)
    m = _NUMBER_RE.match(next((t for t in texts if t.strip()), ""))
    return int(m.group("num")) if m else None


def _starts_question(line: str, current: list[str]) -> bool:
    if not line.strip() or not _has_body(current):
        return False
    if _match_header(line):
        return True
    complete = _is_complete(current)
    m = _NUMBER_RE.match(line)
    if not m:  # a label without `N)`: "LIFE SCIENCE Short Answer ...", "47 MATH Short Answer ..."
        return complete and (_label_head(line) or _opens_question(line))
    rest = line[m.end() :]
    if _scan_label(rest, structured=True)[1] is not None:
        return True  # a category and a format label are unmistakable
    blank_before = not current[-1].strip()
    if not rest.strip():
        return False  # `4)` alone ends an answer
    if rest[0].islower():  # `1) a square is ...` is a list in the stem, unless a new block starts
        return complete and blank_before
    number = _open_number(current)
    next_number = number is not None and int(m.group("num")) == number + 1
    if _answered(current):  # numbered lines inside a multi-line answer are answer text
        return blank_before or _reads_like_stem(rest)
    # A bare `N)` starts a question once the choices are complete, or after a blank line; but in
    # a header-opened stem only the next number counts: the stem may hold a blank-separated list.
    return complete or (blank_before and (next_number or not _opened_by_header(current)))


def _split_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if current and _starts_question(line, current):
            blocks.append(current)
            current = []
        elif current and _match_header(line) and not _has_body(current):
            current = []  # a bare header with nothing after it gives way to the next one
        current.append(line)
    blocks.append(current)
    return [b for b in blocks if any(line.strip() for line in b)]


def _build(lines: list[str]) -> Question | None:
    body = list(lines)
    first = next(i for i, line in enumerate(body) if line.strip())
    kind: Kind | None = None
    header = _match_header(body[first])
    if header:
        kind, body[first] = header

    pre, answer = _split_answer(body)
    text = "\n".join(pre)
    chain = _find_choices(text)
    head = text[: chain[0].start] if chain else text

    number, category, fmt, stem_raw = _split_head(
        _join_lines(head.splitlines()), header=kind is not None
    )
    stem, stem_guides = extract_guides(stem_raw)

    choices: list[Choice] = []
    if chain:
        for marker, nxt in zip(chain, [*chain[1:], None], strict=True):
            span = text[marker.end : nxt.start if nxt else len(text)]
            choice_text, guides = extract_guides(_join_lines(span.splitlines()))
            choices.append(Choice(marker.letter, choice_text, guides))  # type: ignore[arg-type]

    if not stem and not choices:
        return None
    return Question(
        kind=kind,
        number=number,
        category=category,
        fmt=fmt,
        stem=stem,
        choices=tuple(choices),
        answer=answer,
        raw="\n".join(lines).strip(),
        respellings=stem_guides,
    )


class QuestionParser:
    """Turns a paste holding one or more questions into `Question` objects, in reading order."""

    def parse(self, raw: str) -> list[Question]:
        lines = [ln for ln in _clean(raw).splitlines() if not _is_noise(ln)]
        questions = (_build(block) for block in _split_blocks(_drop_stray_fragments(lines)))
        return [q for q in questions if q is not None]


_PARSER = QuestionParser()


def parse(raw: str) -> list[Question]:
    return _PARSER.parse(raw)
