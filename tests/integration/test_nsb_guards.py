"""Corpus-scale guards: the hard rule R5 and IUPAC pronunciations on ordinary words.

R5 (user rule): entity resolution only decides HOW a token is said. A resolved or common name must
never reach the spoken text ("NaHCO3" never becomes "baking soda"). These tests hand
ScriptNormalizer fake Resolutions whose canonical name is a sentinel, over a deterministic sample of
the real NSB rounds (.data/samples), and look for the sentinel anywhere in the script.

Ordinary words: OPSIN parses "pyramid", "allen", "water", "lead"; the lexicon must refuse them, so
the pipeline (OPSIN ok AND lexicon parses) never gives them a morpheme pronunciation. Measured on
the corpus vocabulary (14570 words): OPSIN ok 257, lexicon builds 96, both 36, all real chemicals.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import pytest

from cloudyreader.models import Fmt, Kind, Question, RenderOptions, Resolution

from .test_nsb_corpus import SAMPLES, corpus_report, needs_corpus

SENTINEL = "ZZLEAK"
OTHER_KINDS = ("chemical", "protein", "gene")
# Names the lexicon can build from morphemes: they exercise the branch that makes an Override.
IUPAC_NAMES = re.compile(
    r"\b(?:methane|ethanol|propane|ethylene|ethane|benzene|methanol|octane|butanol|butane|hexane"
    r"|acetylene|cyclohexane|heptane|chloroform|trimethylamine|formaldehyde)\b",
    re.IGNORECASE,
)
# OPSIN parses every one of these; none is an IUPAC name of the thing the question means.
ORDINARY_WORDS = (
    "pyramid",
    "allen",
    "germinate",
    "coronal",
    "german",
    "bipyramid",
    "lead",
    "tin",
    "water",
)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'’+\-–]*")
_SPACED_FORMULA = re.compile(r"\b[A-Z][a-z]?(?: \d{1,3})?(?: [A-Z][a-z]?(?: \d{1,3})?)+")


def _resolution(name: str, kind: str, n: int) -> Resolution:
    return Resolution(name, kind, f"{SENTINEL}-{kind}-{n}", {"pubchem": str(n)}, "pubchem", "ok")


def _question(stem: str) -> Question:
    return Question(Kind.TOSS_UP, 1, "MATH", Fmt.SHORT_ANSWER, stem, (), None, stem)


def _texts(q: Question, read_answer: bool) -> list[str]:
    texts = [q.stem, *(c.text for c in q.choices)]
    return texts + [q.answer] if read_answer and q.answer else texts


def _keys(texts: Iterable[str]) -> list[str]:
    """Every word, word pair and spaced formula: what an over-eager detector could emit."""
    keys: set[str] = set()
    for text in texts:
        words = [w for w in _WORD.findall(text) if len(w) >= 2]
        keys.update(words)
        keys.update(f"{a} {b}" for a, b in zip(words, words[1:], strict=False))
        keys.update(_SPACED_FORMULA.findall(text))
    return sorted(keys)


def _iupac_overrides(script) -> list:
    return [o for seg in script.segments for o in seg.overrides if o.source == "iupac"]


def _assert_no_leak(script, where: str) -> None:
    assert SENTINEL.lower() not in script.text().lower(), f"{where}: canonical name in the text"
    for seg in script.segments:
        for o in seg.overrides:
            assert SENTINEL.lower() not in f"{o.surface} {o.ipa} {o.source}".lower(), where
    assert not [w for w in script.warnings if SENTINEL.lower() in w.lower()], where


@pytest.fixture(scope="module")
def sample() -> list[tuple[str, Question]]:
    """Every 10th question of the corpus plus every one that names a buildable IUPAC compound."""
    from cloudyreader.parser import QuestionParser

    parser = QuestionParser()
    every = []
    for set_name, file_name, text in corpus_report.load_rounds(SAMPLES):
        if corpus_report.expected_questions(text):
            every += [(f"{set_name}/{file_name}", q) for q in parser.parse(text)]
    chosen = {i for i in range(0, len(every), 10)}
    for i, (_, q) in enumerate(every):
        if IUPAC_NAMES.search(" ".join(_texts(q, read_answer=True))):
            chosen.add(i)
    return [every[i] for i in sorted(chosen)]


@pytest.fixture(scope="module")
def normalizer():
    module = pytest.importorskip("cloudyreader.normalize", reason="normalize not written yet")
    return module.ScriptNormalizer()


@pytest.mark.slow
@needs_corpus
@pytest.mark.parametrize("read_answer", [False, True], ids=["quiet", "read-answer"])
def test_r5_a_resolved_name_never_reaches_the_speech(sample, normalizer, read_answer):
    opts = RenderOptions(read_answer=read_answer)
    built = 0
    assert len(sample) > 1000
    for name, q in sample:
        keys = _keys(_texts(q, read_answer))
        plain = normalizer.to_script([q], {}, opts)
        where = f"{name} #{q.number}"
        others = {k: _resolution(k, OTHER_KINDS[i % 3], i) for i, k in enumerate(keys)}
        # Only `iupac` resolutions may count, so the other kinds must change nothing at all.
        other = normalizer.to_script([q], others, opts)
        assert other.segments == plain.segments, f"{where}: a non-iupac resolution changed speech"
        _assert_no_leak(other, where)
        unbuildable = [k for k in keys if normalizer.lexicon.iupac(k) is None]
        quiet = {k: _resolution(k, "iupac", i) for i, k in enumerate(unbuildable)}
        silent = normalizer.to_script([q], quiet, opts)
        assert silent.segments == plain.segments, f"{where}: iupac ok moved text or overrides"
        everything = {k: _resolution(k, "iupac", i) for i, k in enumerate(keys)}
        loud = normalizer.to_script([q], everything, opts)
        _assert_no_leak(loud, where)
        assert [s.pause_after_ms for s in loud.segments] == [
            s.pause_after_ms for s in plain.segments
        ]
        overrides = _iupac_overrides(loud)
        built += any(IUPAC_NAMES.fullmatch(o.surface) for o in overrides)
        joined = loud.text()
        for o in overrides:
            assert o.surface in joined, f"{where}: surface {o.surface!r} left the text"
    assert built >= 100, f"only {built} questions built an Override for a real compound"


@pytest.mark.parametrize("word", ORDINARY_WORDS)
def test_an_ordinary_word_never_gets_an_iupac_override(word, normalizer):
    resolutions = {
        form: Resolution(form, "iupac", SENTINEL, {}, "opsin", "ok")
        for form in (word, word.capitalize(), word.upper())
    }
    q = _question(f"What is a {word}? Name the {word.capitalize()} or the {word.upper()} one.")

    script = normalizer.to_script([q], resolutions, RenderOptions())

    assert _iupac_overrides(script) == []
    assert word in script.text() and SENTINEL.lower() not in script.text().lower()


@pytest.mark.slow
@needs_corpus
def test_ordinary_words_in_real_questions_never_get_an_iupac_override(sample, normalizer):
    alternation = "|".join(ORDINARY_WORDS)
    pattern = re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)
    seen = 0
    for name, q in sample:
        found = {m.group() for text in _texts(q, True) for m in pattern.finditer(text)}
        if not found:
            continue
        seen += 1
        resolutions = {w: Resolution(w, "iupac", SENTINEL, {}, "opsin", "ok") for w in found}
        script = normalizer.to_script([q], resolutions, RenderOptions(read_answer=True))
        assert _iupac_overrides(script) == [], f"{name} #{q.number}: {sorted(found)}"
    assert seen > 100, f"only {seen} sampled questions hold an ordinary word"
