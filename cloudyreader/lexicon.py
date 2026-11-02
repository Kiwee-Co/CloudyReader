"""Pronunciation lexicon: exact IPA for known tokens, and IUPAC names built from morphemes.

Rule R5: this only decides HOW a token is said. It never maps a token to another name, so
the surface of every Override is the caller's own text.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from cloudyreader.models import Override
from cloudyreader.respell import PRIMARY, SECONDARY, piper_safe

DATA_DIR = Path(__file__).parent / "data"
PRONUNCIATIONS_FILE = DATA_DIR / "pronunciations.json"
MORPHEMES_FILE = DATA_DIR / "iupac_morphemes.json"

# Separators only split words: whitespace, comma, brackets, hyphen and its look-alikes.
_SEP = r"\s,()\[\]{}\-\u2010-\u2013\u2212"
_PARTS = re.compile(rf"\d+|[^\d{_SEP}]+|[{_SEP}]+")
_SEPARATORS = re.compile(rf"[{_SEP}]+")
_DOC_KEYS = ("schema", "description")
# Morpheme kinds that take the primary stress of a name no morpheme has marked (ethanol, methane).
_STRESS_FIRST = ("stem", "substituent")


@dataclass(frozen=True)
class _Morpheme:
    ipa: str
    kind: str = ""


class Lexicon:
    """Token -> IPA and morpheme -> IPA tables, fixed after construction.

    `overrides` (the user file) replace `pronunciations`. `warnings` lists user-file problems.
    Morpheme keys: a locant is a digit string ("2"), a lone letter is an exact-case token ("N",
    "R"), anything longer matches case-insensitively inside a run of letters. `kinds` maps a
    morpheme key to its kind (stem, substituent, suffix, ...); without it every kind is unknown.
    """

    def __init__(
        self,
        pronunciations: Mapping[str, str],
        morphemes: Mapping[str, str],
        warnings: Sequence[str] = (),
        *,
        overrides: Mapping[str, str] | None = None,
        kinds: Mapping[str, str] | None = None,
    ) -> None:
        self._pronunciations = {_key(k): piper_safe(v) for k, v in pronunciations.items()}
        self._pronunciations |= {_key(k): piper_safe(v) for k, v in (overrides or {}).items()}
        self._tokens = {
            k: _Morpheme(piper_safe(v), (kinds or {}).get(k, "")) for k, v in morphemes.items()
        }
        self._inside_words = {
            k.casefold(): m for k, m in self._tokens.items() if len(k) > 1 and not k.isdigit()
        }
        self._longest = max(map(len, self._inside_words), default=0)
        self.warnings = tuple(warnings)

    @classmethod
    def load(cls, user_file: Path | None = None, *, data_dir: Path = DATA_DIR) -> Self:
        """Read the bundled tables; entries in `user_file` (optional) win over bundled ones."""
        overrides, warnings = _read_user_file(user_file) if user_file else ({}, [])
        pronunciations = _read_entries(data_dir / PRONUNCIATIONS_FILE.name)
        morphemes = _read_entries(data_dir / MORPHEMES_FILE.name)
        return cls(
            {token: ipa for token, (ipa, _) in pronunciations.items()},
            {token: ipa for token, (ipa, _) in morphemes.items()},
            warnings,
            overrides=overrides,
            kinds={token: kind for token, (_, kind) in morphemes.items()},
        )

    def lookup(self, token: str) -> Override | None:
        ipa = self._pronunciations.get(_key(token))
        return None if ipa is None else Override(surface=token, ipa=ipa, source="lexicon")

    def iupac(self, name: str) -> Override | None:
        """Speak an IUPAC name as locants and morphemes, or None if any part is unknown.

        Separators (hyphen, comma, brackets, space) start a new word; a run of letters is one
        word of morphemes, longest match first. The result has exactly one primary stress: the
        first marked morpheme's, else one placed before the first stem or substituent. A name
        needs at least one morpheme longer than one letter.
        """
        words: list[list[_Morpheme]] = []
        has_name_part = False
        for part in _PARTS.findall(unicodedata.normalize("NFKC", name)):
            if _SEPARATORS.fullmatch(part):
                continue
            word = self._word(part)
            if word is None:
                return None
            words.append(word)
            has_name_part |= part.isalpha() and len(part) > 1
        if not has_name_part:
            return None
        return Override(surface=name, ipa=_speak(words), source="iupac")

    def _word(self, part: str) -> list[_Morpheme] | None:
        if part.isdigit() or len(part) == 1:
            found = self._tokens.get(part)  # locant or lone letter: whole token, exact case
            return None if found is None else [found]
        return self._segment(part.casefold())

    def _segment(self, run: str) -> list[_Morpheme] | None:
        """Greedy longest-match split of one letter run; backs off when a long match dead-ends."""
        dead: set[int] = set()

        def walk(pos: int) -> list[_Morpheme] | None:
            if pos == len(run):
                return []
            if pos in dead:
                return None
            for size in range(min(self._longest, len(run) - pos), 1, -1):
                morpheme = self._inside_words.get(run[pos : pos + size])
                if morpheme is None:
                    continue
                rest = walk(pos + size)
                if rest is not None:
                    return [morpheme, *rest]
            dead.add(pos)
            return None

        return walk(0)


def _key(token: str) -> str:
    return " ".join(token.split()).casefold()


def _speak(words: list[list[_Morpheme]]) -> str:
    """Join the words of a name into IPA with exactly one primary stress mark."""
    morphemes = [m for word in words for m in word]
    sounds = [m.ipa for m in morphemes]
    if not any(PRIMARY in sound for sound in sounds):
        first = next((i for i, m in enumerate(morphemes) if m.kind in _STRESS_FIRST), 0)
        sounds[first] = PRIMARY + sounds[first]
    spoken: list[str] = []
    start = 0
    for word in words:
        spoken.append("".join(sounds[start : start + len(word)]))
        start += len(word)
    return _demote_stress(" ".join(spoken))


def _demote_stress(ipa: str) -> str:
    head, mark, tail = ipa.partition(PRIMARY)
    return head + mark + tail.replace(PRIMARY, SECONDARY)


def _ipa_of(value: Any) -> str | None:
    ipa = value.get("ipa") if isinstance(value, Mapping) else value
    return ipa.strip() if isinstance(ipa, str) and ipa.strip() else None


def _read_entries(path: Path) -> dict[str, tuple[str, str]]:
    """Bundled table as token -> (ipa, kind). A bad file is a packaging bug: fail loudly."""
    table: dict[str, tuple[str, str]] = {}
    for token, value in json.loads(path.read_text(encoding="utf-8"))["entries"].items():
        ipa = _ipa_of(value)
        if ipa is None:
            raise ValueError(f"{path.name}: entry {token!r} has no ipa")
        table[token] = (ipa, str(value.get("kind", "")) if isinstance(value, Mapping) else "")
    return table


def _read_user_file(path: Path) -> tuple[dict[str, str], list[str]]:
    """User table: never crash the reader over a hand-edited file, report and skip instead.

    Accepts the bundled layout ({"schema": 1, "entries": {...}}) or a bare {token: ipa} object.
    """
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, []
    except (OSError, ValueError) as exc:
        return {}, [f"user lexicon {path.name} ignored: {exc}"]
    entries = doc.get("entries", doc) if isinstance(doc, dict) else None
    if not isinstance(entries, dict):
        return {}, [f"user lexicon {path.name} ignored: expected a JSON object of token to IPA"]
    table: dict[str, str] = {}
    problems: list[str] = []
    for token, value in entries.items():
        ipa = _ipa_of(value)
        if ipa is not None and token.strip():
            table[token] = ipa
        elif token not in _DOC_KEYS:
            problems.append(f"user lexicon {path.name}: skipped {token!r} (invalid entry)")
    return table, problems
