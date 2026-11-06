"""Turn parsed questions into the spoken script handed to the TTS stage.

Rule R5: entity resolution only picks HOW a token is said (an IUPAC Override). No resolved or
common name is ever put into the text: "NaHCO3" must never become "baking soda".

Pasted guides come in three kinds: phonetic ones become an Override (IPA), spoken ones replace
the expression with the words the paste gives, spell ones replace it with its letters.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace

from cloudyreader import formulas, respell, spoken_fractions, units
from cloudyreader.lexicon import Lexicon
from cloudyreader.models import (
    Fmt,
    Kind,
    Override,
    Question,
    RenderOptions,
    Resolution,
    Respelling,
    Segment,
    SpokenScript,
)
from cloudyreader.parser import extract_guides

__all__ = ["ScriptNormalizer"]

HEADER_PAUSE_MS = 400
CATEGORY_PAUSE_MS = 300
FORMAT_PAUSE_MS = 500
STEM_PAUSE_MS = 700
LETTER_PAUSE_MS = 300
CHOICE_PAUSE_MS = 400
ANSWER_LEAD_MS = 5000
QUESTION_GAP_MS = 1500

_SMALL_WORDS = frozenset("a an and as at but by for in of on or the to".split())

# Bare `[1]` citation marks from web pastes; `k[1]^2` style math keeps its brackets for later.
_FOOTNOTE_RE = re.compile(r"\s*\[\d{1,3}\](?![\^=/*×+−-])")
_BRACKET_RE = re.compile(r"[\[\]]")
# Whole words only: the engines match an Override surface as a whole word.
_WORD_RE = re.compile(r"(?<!\w)[^\W\d_]{2,}(?!\w)")
# Pause punctuation inside one word's IPA makes the engines pause or reject it (see misaki_ipa).
_IPA_PUNCT_RE = re.compile(r"[.;:,!?—…\"()“”\[\]{}]")
# Whole all-caps words only: "CO2" must not become "Co2".
_SHOUTED_RE = re.compile(r"(?<!\w)[^\W\d_]{2,}(?!\w)")
_ANSWER_MARKER_RE = re.compile(r"\s*([WXYZwxyz])[).:]\s*")
# A moderator reads the primary answer; ACCEPT / PROMPT / NOTE / SOLUTION / MUST notes are for
# judges. Everything from the first note on goes. "(Accept 2)" needs its parenthesis; a bare
# SOLUTION or PROMPT is a real answer, and a colon makes a note explicit.
_NOTE_WORDS = (
    r"(?:also accept|do not accept|accept|do not prompt|prompt|solution|note|must|students?)"
)
_ANSWER_NOTE_RE = re.compile(
    rf"\s*(?:\(\s*{_NOTE_WORDS}\b|\b{_NOTE_WORDS}\s*:).*", re.IGNORECASE | re.DOTALL
)
# Bracketed moderator notes: "[NOTE: STUDENTS MUST GIVE BOTH ANSWERS]", "[must give both]".
_ANSWER_BRACKET_NOTE_RE = re.compile(
    r"\s*\[\s*(?:note|must|do not|accept|prompt|students?)\b[^\]]*\]", re.IGNORECASE
)
_PRIVATE_USE = 0xE000


def _squash(text: str) -> str:
    return " ".join(text.split())


def _header(q: Question) -> str | None:
    kind = {Kind.TOSS_UP: "Toss-up", Kind.BONUS: "Bonus"}.get(q.kind) if q.kind else None
    if q.number is None:
        return f"{kind}." if kind else None
    return f"{kind or 'Question'} number {units.cardinal(q.number)}."


def _title_category(category: str) -> str:
    if not category.isupper():
        return category
    words = category.replace("&", "and").lower().split()
    return " ".join(w if i and w in _SMALL_WORDS else w.capitalize() for i, w in enumerate(words))


def _unshout(text: str) -> str:
    """Title-case each whole all-caps word."""
    return _SHOUTED_RE.sub(
        lambda m: m.group().capitalize() if m.group().isupper() else m.group(), text
    )


def _surface_pattern(surface: str) -> re.Pattern[str]:
    """The surface as a whole word; an end that is not a word character needs no boundary."""
    head = r"(?<!\w)" if re.match(r"\w", surface) else ""
    tail = r"(?!\w)" if re.search(r"\w$", surface) else ""
    return re.compile(head + re.escape(surface) + tail)


def _hide(
    text: str, pattern: re.Pattern[str], words: str, marks: dict[str, str], count: int = 0
) -> str:
    """Swap the first `count` matches (0 = all) for a private-use mark that restores to `words`."""
    mark = chr(_PRIVATE_USE + len(marks))
    marks[mark] = words
    return pattern.sub(lambda _: mark, text, count=count)


def _spell_out(content: str) -> str:
    """The letters a spell guide gives: "F.A.D." -> "F A D", "H-E-2-S-1" -> "H E two S one"."""
    parts = [p for p in re.split(r"[-.\s]+", content) if p]
    return " ".join(units.cardinal(int(p)) if p.isdecimal() else p for p in parts)


def _trim_overlaps(guides: Sequence[Respelling]) -> Sequence[Respelling]:
    """A phonetic guide printed right after another guided word can swallow that word.

    "fluorescein [A] isothiocyanate [B C]" gives B C the surface "fluorescein isothiocyanate".
    """
    trimmed: list[Respelling] = []
    for guide in guides:
        surface = guide.surface
        if guide.kind == "phonetic":
            for earlier in trimmed:
                if earlier.kind == "phonetic" and surface.startswith(earlier.surface + " "):
                    surface = surface[len(earlier.surface) + 1 :]
        trimmed.append(replace(guide, surface=surface))
    return trimmed


def _usable(override: Override | None, warnings: list[str]) -> Override | None:
    if override is not None and _IPA_PUNCT_RE.search(override.ipa):
        warnings.append(
            f"Pronunciation for {override.surface!r} dropped: its IPA holds punctuation."
        )
        return None
    return override


class ScriptNormalizer:
    """Builds a `SpokenScript`, one Segment each: header, stem, choice letter, choice text, answer.

    `speak_formulas`, `speak_units` and `to_ipa` default to the real stages; tests inject fakes.
    """

    def __init__(
        self,
        lexicon: Lexicon | None = None,
        *,
        speak_formulas: Callable[[str], str] | None = None,
        speak_units: Callable[[str], str] | None = None,
        to_ipa: Callable[[str], str | None] | None = None,
    ) -> None:
        self.lexicon = lexicon if lexicon is not None else Lexicon.load()
        self._formulas = speak_formulas or formulas.speak_formulas
        self._units = speak_units or units.speak_units
        self._to_ipa = to_ipa or respell.to_ipa

    def to_script(
        self,
        questions: Sequence[Question],
        resolutions: Mapping[str, Resolution],
        opts: RenderOptions,
    ) -> SpokenScript:
        warnings: list[str] = [*self.lexicon.warnings]
        names = self._iupac_overrides(resolutions, warnings)
        segments: list[Segment] = []
        for i, q in enumerate(questions):
            made = self._question(q, names, opts, warnings)
            if made and i < len(questions) - 1:
                made[-1] = replace(made[-1], pause_after_ms=QUESTION_GAP_MS)
            segments.extend(made)
        return SpokenScript(tuple(segments), tuple(dict.fromkeys(warnings)))

    def _iupac_overrides(
        self, resolutions: Mapping[str, Resolution], warnings: list[str]
    ) -> dict[str, Override]:
        """Only an `iupac`/`ok` resolution the lexicon can also build from morphemes counts.

        OPSIN says `ok` for "lead" and "water" too; `Lexicon.iupac` returns None for those.
        """
        found: dict[str, Override] = {}
        for name, res in resolutions.items():
            if res.kind != "iupac" or res.status != "ok" or _BRACKET_RE.search(name):
                continue
            override = self.lexicon.iupac(name)
            if override is not None:
                override = _usable(replace(override, surface=name), warnings)
            if override is not None:
                found[name] = override
        return found

    def _question(
        self,
        q: Question,
        names: Mapping[str, Override],
        opts: RenderOptions,
        warnings: list[str],
    ) -> list[Segment]:
        segments: list[Segment] = []

        def add(text: str, pause: int = 0, overrides: Sequence[Override] = ()) -> None:
            if text:
                segments.append(Segment(text, pause, tuple(overrides)))

        add(_header(q) or "", HEADER_PAUSE_MS)
        if q.category:
            add(f"{_title_category(q.category)}.", CATEGORY_PAUSE_MS)
        if q.fmt is not None:
            add(
                "Multiple choice." if q.fmt is Fmt.MULTIPLE_CHOICE else "Short answer.",
                FORMAT_PAUSE_MS,
            )
        stem, overrides = self._speak(q.stem, q.respellings, names, warnings)
        add(stem, STEM_PAUSE_MS if q.choices else 0, overrides)
        for choice in q.choices:
            text, overrides = self._speak(choice.text, choice.respellings, names, warnings)
            # The letter is its own segment: its pause is exact silence in every engine, not
            # each voice's own reading of the period.
            add(f"{choice.letter}.", LETTER_PAUSE_MS if text else CHOICE_PAUSE_MS)
            add(text, CHOICE_PAUSE_MS, overrides)
        if opts.read_answer and q.answer:
            text, overrides = self._speak_answer(q.answer, names, warnings)
            if text and segments:
                segments[-1] = replace(segments[-1], pause_after_ms=ANSWER_LEAD_MS)
            add(f"Answer. {text}" if text else "", 0, overrides)
        return segments

    def _speak_answer(
        self, answer: str, names: Mapping[str, Override], warnings: list[str]
    ) -> tuple[str, tuple[Override, ...]]:
        answer = _ANSWER_BRACKET_NOTE_RE.sub("", _ANSWER_NOTE_RE.sub("", answer))
        answer, guides = extract_guides(answer)
        marker = _ANSWER_MARKER_RE.match(answer)
        if marker:
            answer = f"{marker.group(1).upper()}. {answer[marker.end() :]}"
        shouted = not any(c.islower() for c in answer)
        text, overrides = self._speak(answer, guides, names, warnings, shouted=shouted)
        if text and text[-1] not in ".!?":
            text += "."
        return text, overrides

    def _speak(
        self,
        text: str,
        respellings: Sequence[Respelling],
        names: Mapping[str, Override],
        warnings: list[str],
        *,
        shouted: bool = False,
    ) -> tuple[str, tuple[Override, ...]]:
        text = _squash(_FOOTNOTE_RE.sub("", text))
        respellings = _trim_overlaps(respellings)
        # A pasted guide, or an IUPAC name, says how its words sound, so the formula, unit and
        # acronym stages must not touch them: each becomes a private-use mark until the end.
        marks: dict[str, str] = {}
        found: dict[int, Override] = {}
        done: set[str] = set()
        for i in sorted(range(len(respellings)), key=lambda k: -len(respellings[k].surface)):
            guide = respellings[i]
            # A phonetic guide covers every occurrence at once; a say-as guide only the one it
            # followed ("y = [y equals ...]. When y = 3" must keep its second "y =").
            if guide.kind == "phonetic":
                if guide.surface in done:
                    continue
                done.add(guide.surface)
            pattern = _surface_pattern(guide.surface) if guide.surface else None
            if pattern is None or not pattern.search(text):
                warnings.append(
                    f"Guide [{guide.respelling}] dropped: {guide.surface!r} is not in the text."
                )
            elif guide.kind == "phonetic":
                text, override = self._hide_phonetic(text, pattern, guide, shouted, marks, warnings)
                if override is not None:
                    found[i] = override
            else:
                text = self._hide_say_as(text, pattern, guide, marks, warnings)
        named: dict[str, Override] = {}
        for name in sorted(names, key=len, reverse=True):
            pattern = _surface_pattern(name)
            if pattern.search(text):
                text = _hide(text, pattern, name, marks)
                named[name] = names[name]

        # Fractions are found on the raw text, before the unit stage turns "√10/5" into "square
        # root of 10/5"; their words come after it has said the signs ("-3/7" is "minus 3/7") and
        # before the formula stage, which would take the 2 of "1/2 × 10^3" for a mantissa.
        text = self._units(spoken_fractions.mark_fractions(text))
        text = self._formulas(spoken_fractions.say_marked(text))
        # Ranges come last: by then the formula stage has read "Kw = 10–14" as a power.
        spoken = _squash(units.speak_ranges(text))
        if shouted:
            spoken = _unshout(spoken)
        spoken = _squash(_BRACKET_RE.sub(" ", spoken))
        lexicon_hits = self._lexicon_overrides(spoken, warnings)
        for mark, words in marks.items():
            spoken = spoken.replace(mark, words)

        overrides = [found[i] for i in sorted(found)]
        overrides += [o for name, o in named.items() if _surface_pattern(name).search(spoken)]
        return spoken, tuple(overrides + lexicon_hits)

    def _hide_say_as(
        self,
        text: str,
        pattern: re.Pattern[str],
        guide: Respelling,
        marks: dict[str, str],
        warnings: list[str],
    ) -> str:
        words = _spell_out(guide.respelling) if guide.kind == "spell" else guide.respelling
        # The guide's words skip every stage, so a fraction in them would still be read "slash".
        words = spoken_fractions.speak_fractions(_squash(_BRACKET_RE.sub(" ", words)))
        if not re.search(r"\w", words):
            warnings.append(f"Guide for {guide.surface!r} dropped: it holds no words.")
            return text
        return _hide(text, pattern, words, marks, count=1)

    def _hide_phonetic(
        self,
        text: str,
        pattern: re.Pattern[str],
        guide: Respelling,
        shouted: bool,
        marks: dict[str, str],
        warnings: list[str],
    ) -> tuple[str, Override | None]:
        """Shield the surface so its Override still matches; without IPA the word stays plain."""
        ipa = self._to_ipa(guide.respelling)
        if ipa is None:
            warnings.append(
                f"No pronunciation for respelling [{guide.respelling}]: "
                f"{guide.surface!r} is spoken plain."
            )
            return text, None
        surface = _unshout(guide.surface) if shouted else guide.surface
        override = _usable(
            Override(surface, ipa, "respelling", respelling=guide.respelling), warnings
        )
        if override is None:
            return text, None
        return _hide(text, pattern, surface, marks), override

    def _lexicon_overrides(self, spoken: str, warnings: list[str]) -> list[Override]:
        """Known hard words; guide surfaces and IUPAC names are marks here, so never looked up."""
        found: list[Override] = []
        seen: set[str] = set()
        for word in _WORD_RE.findall(spoken):
            if word in seen:
                continue
            seen.add(word)
            hit = self.lexicon.lookup(word)
            override = None if hit is None else _usable(replace(hit, surface=word), warnings)
            if override is not None:
                found.append(override)
        return found
