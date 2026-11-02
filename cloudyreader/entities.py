"""Science entity detection: scispaCy CRAFT NER plus regexes for what the model misses.

Labels: CHEBI is a chemical; GGP is a gene (capitalised symbol such as TP53) or a protein (a word,
or a p-number such as p53). Regex adds formulas, IUPAC-like chemical names and gene symbols.
Span text is always the pasted text (rule R5): nothing here swaps in a resolved or common name.
"""

from __future__ import annotations

import logging
import re
import threading
from bisect import bisect_left
from collections.abc import Iterator
from typing import Any, Literal, NamedTuple

from cloudyreader.models import EntitySpan

log = logging.getLogger(__name__)

Label = Literal["chemical", "formula", "protein", "gene", "other"]

# Tie-break order for equal-length overlaps: shape-specific regexes before the coarse NER labels.
_FORMULA, _IUPAC, _GENE, _PROTEIN, _NER = range(5)


class _Cand(NamedTuple):
    start: int
    end: int
    label: Label
    source: str
    rank: int


# --- Formulas and ions ---------------------------------------------------------------------------

# The 118 element symbols are a fixed fact; keeping them here means detection needs no data file.
_ELEMENTS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br"
    " Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho"
    " Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es"
    " Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split()
)
# Capitals-only strings with no digit are mostly acronyms (NSB, USA); only these are safe formulas.
_ALLCAPS_FORMULAS = frozenset({"CO", "NO", "HF", "KOH", "HCN"})

_DIGITS = "0-9₀-₉"  # ASCII digits and Unicode subscripts
_SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_ATOM = rf"[A-Z][a-z]?[{_DIGITS}]*"
# A group needs a subscript: (NH4)2SO4 and Ca(OH)2 are formulas, the copyright mark (C) is not.
_GROUP = rf"\((?:{_ATOM})+\)[{_DIGITS}]+"
_UNIT = rf"(?:{_ATOM}|{_GROUP})+"
# A hydrate dot joins a second formula and its coefficient: MgSO4•7H2O.
# A charge is "+", "3+", "^3+", "²⁺", "O2–" (en dash) or NSB's spaced "SO4 2-". The sign must end
# the token, so "Na-K" and "H2O–CO2" are not ions.
_SIGN = "+\\-−–"
_FORMULA_RE = re.compile(
    rf"(?<![A-Za-z])(?P<body>{_UNIT}(?:[•·⋅∙][ ]?\d*{_UNIT})*)"
    rf"(?P<charge>[{_SUPERSCRIPTS}]*[⁺⁻]|\^?[{_DIGITS}]*[{_SIGN}]"
    rf"|[ \u00a0][{_DIGITS}]+[{_SIGN}])?(?![A-Za-z0-9])"
)
_SYMBOL_RE = re.compile(r"[A-Z][a-z]?")
_STRUCTURE_RE = re.compile(rf"[({_DIGITS}]")
_CAPS_BEFORE = re.compile(r"(?<![A-Za-z])[A-Z]{2,}[ \t]+\Z")
_CAPS_AFTER = re.compile(r"[ \t]+[A-Z]{2,}(?![a-z])")


def _is_formula(body: str, charge: str | None) -> bool:
    symbols = _SYMBOL_RE.findall(body)
    if any(symbol not in _ELEMENTS for symbol in symbols):
        return False
    if charge or _STRUCTURE_RE.search(body):
        return True
    # NaCl, HCl: two symbols and some lower case. A lone symbol (He, In, As) is an English word.
    return (len(symbols) > 1 and not body.isupper()) or body in _ALLCAPS_FORMULAS


def _in_caps_run(text: str, start: int, end: int) -> bool:
    """True inside shouted prose ("IN NO EVENT SHALL"), where CO and NO are plain words."""
    return bool(
        _CAPS_BEFORE.search(text, max(0, start - 40), start) or _CAPS_AFTER.match(text, end)
    )


def _formula_spans(text: str) -> Iterator[_Cand]:
    for m in _FORMULA_RE.finditer(text):
        if not _is_formula(m["body"], m["charge"]):
            continue
        if m["body"] in _ALLCAPS_FORMULAS and not m["charge"] and _in_caps_run(text, *m.span()):
            continue
        yield _Cand(m.start(), m.end(), "formula", "regex", _FORMULA)


# --- IUPAC-like names ----------------------------------------------------------------------------

# Systematic names only: locants plus alkane-family morphemes. Every quantifier is bounded so
# hostile input cannot backtrack badly; the NER model covers trivial names (ethanol, acetone).
_STEM = "meth|eth|prop|but|pent|hex|hept|oct|non|dec"
_LOCANT = r"(?:\d+[a-z]?(?:,\d+[a-z]?){0,5}|[NOSP](?:,[NOSP]){0,3})"
_BRANCH = r"(?:iso|neo|(?:n|sec|tert)-)"
_ALKYL = rf"{_BRANCH}?(?:{_STEM}|benz)yl"
_SUBSTITUENT = (
    rf"(?:{_ALKYL}|chloro|bromo|fluoro|iodo|hydroxy|amino|nitro|oxo|cyano|phenyl|methoxy|ethoxy)"
)
_MULTIPLIER = "di|tri|tetra|penta|hexa|hepta|octa|nona|deca|bis|tris"
_GROUP = rf"(?:{_LOCANT}-)?(?:{_MULTIPLIER})?{_SUBSTITUENT}-?"
_SUFFIX = "ol|diol|triol|al|dial|one|dione|oic acid|dioic acid|amine|diamine|amide|nitrile|thiol"
# propane, propan-1-ol, propane-1,2-diol, ethanoic acid | but-1-ene, buta-1,3-diene | butadiene
_TAIL = (
    rf"(?:an|en|yn)(?:e(?:-{_LOCANT}-(?:{_SUFFIX}))?|(?:-{_LOCANT}-)?(?:{_SUFFIX}))"
    rf"|a?-{_LOCANT}-(?:diene|triene|ene|yne|diyne)(?:-{_LOCANT}-(?:{_SUFFIX}))?"
    r"|a(?:diene|triene|diyne)"
)
_IUPAC_RE = re.compile(
    r"(?<![A-Za-z0-9,])(?:"
    rf"(?:{_LOCANT}-)?(?:{_GROUP}){{0,8}}{_BRANCH}?(?:cyclo)?(?:{_STEM}|benz)(?:{_TAIL})"
    rf"|{_ALKYL})(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _iupac_spans(text: str) -> Iterator[_Cand]:
    for m in _IUPAC_RE.finditer(text):
        yield _Cand(m.start(), m.end(), "chemical", "regex", _IUPAC)


# --- Gene and protein symbols --------------------------------------------------------------------

# Bare-letter symbols have no shape cue, so the common NSB ones are listed. Extend as needed.
_KNOWN_GENES = "CFTR|HBB|DMD|APOE|HTT|MYC|KRAS|HRAS|NRAS|EGFR|PTEN|SRY|ACTB|GAPDH|LDLR|HEXA|VHL|ABO"
_GENE_RE = re.compile(  # BRCA1, TP53, CDK2: capitals then a digit. CO2 loses the tie to formula.
    r"(?<![A-Za-z0-9])(?:[A-Z]{2,6}\d[A-Z0-9]{0,6}|" + _KNOWN_GENES + r")(?![A-Za-z0-9])"
)
_P_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])p\d{2,3}(?![A-Za-z0-9])")  # p53, p21: protein names
# "the CFTR gene", "gene TP53": same line only, so a stem ending in "gene" cannot adopt ANSWER.
_GENE_WORD_RE = re.compile(
    r"\b(?i:genes?)[ \t]+([A-Z][A-Z0-9]{2,7})\b|\b([A-Z][A-Z0-9]{2,7})[ \t]+(?i:genes?)\b"
)


def _gene_spans(text: str) -> Iterator[_Cand]:
    for m in _GENE_RE.finditer(text):
        yield _Cand(m.start(), m.end(), "gene", "regex", _GENE)
    for m in _P_NUMBER_RE.finditer(text):
        yield _Cand(m.start(), m.end(), "protein", "regex", _GENE)
    for m in _GENE_WORD_RE.finditer(text):
        group = 1 if m[1] else 2
        yield _Cand(m.start(group), m.end(group), "gene", "regex", _GENE)


# --- Enzymes and protein words -------------------------------------------------------------------

# CRAFT misses enzymes (amylase) and tags hemoglobin a chemical, so an -ase word is a protein
# unless it is everyday English. An -in word is not: 93% of them in real questions are Darwin,
# Kelvin, robin, within and the like, so only a closed list and sure endings count.
_ENZYME_RE = re.compile(r"(?<![A-Za-z0-9])(?i:[a-z]{2,}ases?)(?![A-Za-z0-9])")
_NOT_ENZYMES = frozenset(  # a plural is also checked with its "s" dropped
    "increase decrease disease release purchase repurchase grease cease chase erase please lease"
    " phrase paraphrase ease unease appease tease crease aliases biases atlases canvases"
    " pancreases".split()
)
# No enzyme ends this way (helicase is the one -case exception): cell-cycle phases, feldspars,
# databases, nucleobases, lowercase, suitcase.
_NOT_ENZYME_ENDINGS = ("phase", "clase", "base", "case")
_ENZYME_MODIFIERS = frozenset({"protein", "reverse", "restriction"})
_WORD_BEFORE_RE = re.compile(r"([A-Za-z][A-Za-z0-9-]*) \Z")
_PROTEIN_ENDINGS = "globin|globulin|psin|tropin|poietin|pressin|nectin|myosin|tubulin"
_PROTEIN_WORDS = "|".join(
    "actin albumin amylin angiotensin avidin calcitonin calmodulin casein catenin cadherin cyclin"
    " clathrin collagen dynein dystrophin elastin ferritin fibrin fibrinogen fibronectin gastrin"
    " ghrelin glucagon gliadin hemocyanin histone insulin integrin interferon keratin kinesin"
    " laminin lectin leptin motilin opsin oxytocin papain pepsinogen plasmin plasminogen"
    " prolactin prothrombin relaxin renin rennin secretin somatostatin spectrin thrombin"
    " thymosin titin transferrin troponin trypsinogen ubiquitin zein".split()
)
_PROTEIN_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?:[a-z]{{0,14}}(?:{_PROTEIN_ENDINGS})|{_PROTEIN_WORDS})s?(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _substrate_start(text: str, start: int, end: int, hints: dict[int, int]) -> int:
    """Where an enzyme name begins: the model's phrase, or a substrate word right before it."""
    covering = hints.get(end)  # CRAFT tagged the whole phrase: "Alcohol dehydrogenase"
    # Three or more words ahead of the enzyme read as prose ("sequence encoding the polymerase").
    if covering is not None and covering < start and text.count(" ", covering, start) < 3:
        return covering
    before = _WORD_BEFORE_RE.search(text, max(0, start - 40), start)
    if before is None:
        return start
    word = before[1]
    acronym = word.isupper() and 2 <= len(word) <= 5 and word.lower() not in _EDGE_WORDS
    if acronym or word.lower() in _ENZYME_MODIFIERS:
        return before.start(1)
    return hints.get(before.end(1), start)  # CRAFT tagged the substrate: "alcohol" + enzyme


def _is_enzyme_word(word: str) -> bool:
    singular = word.removesuffix("s")
    if word in _NOT_ENZYMES or singular in _NOT_ENZYMES:
        return False
    return singular.endswith("helicase") or not singular.endswith(_NOT_ENZYME_ENDINGS)


def _enzyme_spans(text: str, hints: dict[int, int]) -> Iterator[_Cand]:
    """`hints` maps the end of each cleaned CRAFT entity, of any label, to its start."""
    for m in _ENZYME_RE.finditer(text):
        if not _is_enzyme_word(m[0].lower()):
            continue
        begin = _substrate_start(text, m.start(), m.end(), hints)
        yield _Cand(begin, m.end(), "protein", "regex", _PROTEIN)


def _protein_word_spans(text: str) -> Iterator[_Cand]:
    for m in _PROTEIN_RE.finditer(text):
        yield _Cand(m.start(), m.end(), "protein", "regex", _PROTEIN)


def _regex_candidates(text: str) -> list[_Cand]:
    return [
        *_formula_spans(text),
        *_iupac_spans(text),
        *_gene_spans(text),
        *_protein_word_spans(text),
    ]


# --- NER output ----------------------------------------------------------------------------------

# TAXON, GO, SO and CL are dropped: OPSIN, PubChem and UniProt cannot resolve them and they fire
# on everyday words (human, mutation, cell).
_KEPT_NER_LABELS = frozenset({"CHEBI", "GGP"})
# Words an entity never starts or ends with: function words, and category nouns the model glues on.
_EDGE_WORDS = frozenset(
    "the a an and or of in with to by for is are as at on gene genes oncogene oncogenes ion ions"
    " molecule molecules molecular compound compounds mineral minerals electron electrons"
    " product products".split()
)
# Leading only: "green fluorescent protein" keeps its tail, "protein p53" loses its head.
_LEAD_WORDS = _EDGE_WORDS | frozenset(
    "protein proteins enzyme enzymes suppressor polyatomic".split()
)
_KIND_WORDS = frozenset({"protein", "proteins", "enzyme", "enzymes"})
# CRAFT tags these everyday nouns alone; no resolver or pronunciation rule can use them.
_ALONE_WORDS = frozenset(
    "acid acids base bases salt salts metal metals gas gases oxide oxides dioxide monoxide food"
    " chemical chemicals nucleotide nucleotides".split()
)
_EDGE_PUNCTUATION = ".,;:!?\"'“”‘’"
_LINE_RE = re.compile(r"[^\r\n]+")
_WORD_RE = re.compile(r"\S+")
_CHOICE_MARKER_RE = re.compile(r"[WXYZwxyz][).:]?")


def _is_generic(word: str, generic: frozenset[str]) -> bool:
    bare = word.strip(_EDGE_PUNCTUATION + "()[]").lower()
    return not any(ch.isalnum() for ch in bare) or bare in generic


def _is_symbol(word: str) -> bool:
    """TP53, IL6, p21: a digit or two capitals, unlike a plain word such as Wnt."""
    return any(ch.isdigit() for ch in word) or sum(ch.isupper() for ch in word) >= 2


def _clean_ner_span(text: str, start: int, end: int) -> Iterator[tuple[int, int]]:
    """Trim a CRAFT entity to the name itself; the model adds neighbours (see the model tests)."""
    for line in _LINE_RE.finditer(text, start, end):  # a name never spans a line break
        words = list(_WORD_RE.finditer(text, line.start(), line.end()))
        # CRAFT swallows the next "X)" choice marker into the entity before it.
        if words and _CHOICE_MARKER_RE.fullmatch(words[-1][0]):
            tail = words[-1]
            if len(tail[0]) == 2 or text[tail.end() : tail.end() + 1] in {")", ".", ":"}:
                words.pop()
        while words and _is_generic(words[0][0], _LEAD_WORDS):
            words.pop(0)
        while words and _is_generic(words[-1][0], _EDGE_WORDS):
            words.pop()
        # "p21 protein" is the symbol p21; "green fluorescent protein" is a name and stays whole.
        if len(words) > 1 and words[-1][0].lower() in _KIND_WORDS and _is_symbol(words[-2][0]):
            words.pop()
        if not words:
            continue
        first, last = words[0].start(), words[-1].end()
        while first < last and text[first] in _EDGE_PUNCTUATION:
            first += 1
        while last > first and text[last - 1] in _EDGE_PUNCTUATION:
            last -= 1
        if text[first:last].lower() not in _ALONE_WORDS:
            yield first, last


def _ggp_label(name: str) -> Label:
    """HGNC symbols are capitals (TP53, CFTR); any lower case makes it a protein name (p53)."""
    has_lower = any(ch.islower() for ch in name)
    return "protein" if has_lower or not any(ch.isupper() for ch in name) else "gene"


def _clean_entities(text: str, ents: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    return [
        (start, end, ner_label)
        for ent_start, ent_end, ner_label in ents
        for start, end in _clean_ner_span(text, ent_start, ent_end)
    ]


def _ner_to_candidates(text: str, cleaned: list[tuple[int, int, str]]) -> list[_Cand]:
    cands = []
    for start, end, ner_label in cleaned:
        if ner_label in _KEPT_NER_LABELS:
            label = _ggp_label(text[start:end]) if ner_label == "GGP" else "chemical"
            cands.append(_Cand(start, end, label, "ner", _NER))
    return cands


def _resolve_overlaps(cands: list[_Cand]) -> list[_Cand]:
    """Greedy sweep: the longer span wins; on equal length regex beats NER (formula, then chemical
    name, then gene symbol), then the leftmost wins. Spans that only touch are both kept."""
    kept: list[_Cand] = []  # sorted by start and disjoint, so only the two neighbours can clash
    starts: list[int] = []
    for cand in sorted(cands, key=lambda c: (c.start - c.end, c.rank, c.start)):
        i = bisect_left(starts, cand.start)
        if (i > 0 and kept[i - 1].end > cand.start) or (i < len(kept) and kept[i].start < cand.end):
            continue
        kept.insert(i, cand)
        starts.insert(i, cand.start)
    return kept


def _load_spacy(model: str) -> Any:
    import spacy  # lazy: importing spaCy takes seconds and tests with a fake pipeline skip it

    # Only NER is read. Dropping the tagger, parser and lemmatizer gives identical entities in
    # about two thirds of the time.
    return spacy.load(model, exclude=["tagger", "attribute_ruler", "lemmatizer", "parser"])


class SciEntityDetector:
    """Finds chemicals, formulas, genes and proteins in pasted question text.

    `detect` returns sorted, disjoint spans with `text == text[start:end]` (overlap rule: see
    `_resolve_overlaps`). `model` is a spaCy package name or directory. A missing or broken model
    degrades to regex-only with one log line, never an error.
    """

    def __init__(self, model: str = "en_ner_craft_md", *, nlp: Any | None = None) -> None:
        self._model = model
        self._nlp = nlp
        self._ready = threading.Event()
        self._started = nlp is not None
        if self._started:
            self._ready.set()
        self._start_lock = threading.Lock()
        self._infer_lock = threading.Lock()  # spaCy pipelines are not thread-safe
        self._inference_failed = False

    def preload(self) -> None:
        """Load the model in a background thread; `detect` waits for it. Safe to call repeatedly."""
        with self._start_lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._load, name="entities-preload", daemon=True).start()

    def detect(self, text: str) -> list[EntitySpan]:
        if not isinstance(text, str) or not text.strip():
            return []
        cleaned = _clean_entities(text, self._ner_entities(text))
        hints: dict[int, int] = {}
        for start, end, _ in cleaned:
            hints[end] = min(start, hints.get(end, start))
        cands = [
            *_regex_candidates(text),
            *_enzyme_spans(text, hints),
            *_ner_to_candidates(text, cleaned),
        ]
        return [
            EntitySpan(c.start, c.end, text[c.start : c.end], c.label, c.source)
            for c in _resolve_overlaps(cands)
        ]

    def _load(self) -> None:
        try:
            self._nlp = _load_spacy(self._model)
        except Exception as exc:  # any failure must leave the regex detectors working
            log.warning(
                "NER model %r unavailable (%s: %s); using regex-only entity detection",
                self._model,
                type(exc).__name__,
                exc,
            )
        finally:
            self._ready.set()

    def _ner_entities(self, text: str) -> list[tuple[int, int, str]]:
        self.preload()
        self._ready.wait()
        if self._nlp is None:
            return []
        with self._infer_lock:
            try:
                ents = [(e.start_char, e.end_char, e.label_) for e in self._nlp(text).ents]
            except Exception as exc:  # e.g. spaCy E088, text longer than nlp.max_length
                if not self._inference_failed:
                    self._inference_failed = True
                    log.warning(
                        "NER failed (%s: %s); using regex-only for this text",
                        type(exc).__name__,
                        exc,
                    )
                return []
        return ents
