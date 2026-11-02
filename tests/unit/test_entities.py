"""Tests for cloudyreader.entities: NER mapping and hygiene, regex detectors, overlaps, preload."""

from __future__ import annotations

import importlib.util
import logging
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from cloudyreader import entities
from cloudyreader.entities import SciEntityDetector
from cloudyreader.models import EntitySpan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "questions"
LABELS = {"chemical", "formula", "protein", "gene", "other"}


@dataclass(frozen=True)
class FakeEnt:
    start_char: int
    end_char: int
    label_: str
    text: str = ""


class FakeNlp:
    """A spaCy stand-in: each needle found in the text becomes an entity; `offsets` are verbatim."""

    def __init__(self, *needles: tuple[str, str], offsets: tuple[tuple[int, int, str], ...] = ()):
        self.needles = needles
        self.offsets = offsets
        self.calls: list[str] = []

    def __call__(self, text: str) -> SimpleNamespace:
        self.calls.append(text)
        ents = [
            FakeEnt(m.start(), m.end(), label, needle)
            for needle, label in self.needles
            for m in re.finditer(re.escape(needle), text)
        ]
        ents += [FakeEnt(s, e, label, text[s:e]) for s, e, label in self.offsets]
        return SimpleNamespace(ents=sorted(ents, key=lambda ent: ent.start_char))


def regex_only(text: str) -> list[EntitySpan]:
    return SciEntityDetector(nlp=FakeNlp()).detect(text)


def with_ner(text: str, *needles: tuple[str, str]) -> list[EntitySpan]:
    return SciEntityDetector(nlp=FakeNlp(*needles)).detect(text)


def found(spans: list[EntitySpan]) -> list[tuple[str, str]]:
    return [(s.text, s.label) for s in spans]


def assert_well_formed(text: str, spans: list[EntitySpan]) -> None:
    previous_end = 0
    for span in spans:
        assert span.label in LABELS
        assert span.source in {"ner", "regex"}
        assert 0 <= span.start < span.end <= len(text)
        assert span.text == text[span.start : span.end]  # R5: the pasted text, never a name
        assert span.start >= previous_end  # sorted and non-overlapping
        previous_end = span.end


# --- NER mapping -----------------------------------------------------------------------------


def test_chebi_maps_to_chemical_with_exact_offsets():
    text = "Cells burn glucose in response to hunger."
    start = text.index("glucose")
    spans = with_ner(text, ("glucose", "CHEBI"))
    assert spans == [EntitySpan(start, start + len("glucose"), "glucose", "chemical", "ner")]


@pytest.mark.parametrize(
    ("needle", "label"),
    [("Wnt", "protein"), ("Hedgehog", "protein"), ("Notch", "protein"), ("FOXP", "gene")],
)
def test_ggp_is_a_gene_for_a_symbol_and_a_protein_for_a_word(needle, label):
    spans = with_ner(f"We studied {needle} today.", (needle, "GGP"))
    assert [(s.text, s.label, s.source) for s in spans] == [(needle, label, "ner")]


@pytest.mark.parametrize("ner_label", ["TAXON", "GO", "SO", "CL", "SOMETHING_NEW"])
def test_labels_the_resolvers_cannot_use_are_dropped(ner_label):
    assert with_ner("Escherichia coli undergoes apoptosis.", ("Escherichia coli", ner_label)) == []


@pytest.mark.parametrize("text", ["", "   ", "\n\t", None, 42])
def test_empty_or_non_text_input_gives_no_spans(text):
    nlp = FakeNlp(("glucose", "CHEBI"))
    assert SciEntityDetector(nlp=nlp).detect(text) == []
    assert nlp.calls == []


# --- NER span hygiene (real CRAFT quirks, see the model test) ---------------------------------


def test_generic_lead_words_are_stripped_from_a_ner_span():
    text = "A protein Wnt cascade amplifies the signal."
    assert found(with_ner(text, ("protein Wnt", "GGP"))) == [("Wnt", "protein")]


def test_trailing_choice_marker_is_not_part_of_the_span():
    text = "W) insulin X) glucagon Y) amylin"
    spans = with_ner(text, ("insulin X", "GGP"), ("glucagon Y", "GGP"), ("amylin", "GGP"))
    assert found(spans) == [("insulin", "protein"), ("glucagon", "protein"), ("amylin", "protein")]


def test_an_entity_never_crosses_a_line_break():
    text = "insulin\nglucagon"
    spans = with_ner(text, ("insulin\nglucagon", "GGP"))
    assert found(spans) == [("insulin", "protein"), ("glucagon", "protein")]


def test_spans_made_only_of_generic_words_are_dropped():
    text = "Each molecule of the mineral ion is an electron donor."
    ner = [(w, "CHEBI") for w in ("molecule", "mineral", "ion", "electron")]
    assert with_ner(text, *ner) == []


def test_edge_punctuation_is_trimmed():
    assert found(with_ner("glucose, fructose", ("glucose,", "CHEBI"))) == [("glucose", "chemical")]
    assert found(with_ner('the "insulin" level', ('"insulin"', "GGP"))) == [("insulin", "protein")]


def test_generic_trailing_word_is_stripped_but_protein_stays_in_a_name():
    text = "The insulin gene and green fluorescent protein."
    ner = [("insulin gene", "GGP"), ("green fluorescent protein", "GGP")]
    assert found(with_ner(text, *ner)) == [
        ("insulin", "protein"),
        ("green fluorescent protein", "protein"),
    ]


def test_function_words_are_stripped_at_the_edges():
    text = "Both glucose and fructose, in water."
    ner = [("glucose and", "CHEBI"), ("in water", "CHEBI")]
    assert found(with_ner(text, *ner)) == [("glucose", "chemical"), ("water", "chemical")]


@pytest.mark.parametrize("trailer", ["protein", "proteins"])
def test_symbol_loses_a_trailing_protein_word_but_a_name_keeps_it(trailer):
    text = f"The SMAD4 {trailer} and green fluorescent protein."
    ner = [(f"SMAD4 {trailer}", "GGP"), ("green fluorescent protein", "GGP")]
    assert found(with_ner(text, *ner)) == [
        ("SMAD4", "gene"),
        ("green fluorescent protein", "protein"),
    ]


def test_oncogene_prefix_is_a_category_word():
    assert found(with_ner("The oncogene MYB drives it.", ("oncogene MYB", "GGP"))) == [
        ("MYB", "gene")
    ]


def test_everyday_nouns_are_dropped_alone_but_kept_inside_a_name():
    text = "Use acid, metals and acetic acid."
    ner = [("acid", "CHEBI"), ("metals", "CHEBI"), ("acetic acid", "CHEBI")]
    assert found(with_ner(text, *ner)) == [("acetic acid", "chemical")]


def test_ner_span_that_is_only_punctuation_is_dropped():
    assert with_ner("A → B", ("→", "GGP")) == []


# --- Formulas and ions -----------------------------------------------------------------------

FORMULAS = [
    "H2SO4", "NaCl", "Ca(OH)2", "Fe3+", "H2O", "CO2", "C6H12O6", "NH3", "O2", "Cl2", "Na+",
    "Cl-", "H+", "OH-", "Ca2+", "Al2(SO4)3", "KMnO4", "NaOH", "HCl", "Fe2O3", "NaHCO3",
    "CuSO4", "SO4 2-", "CO", "NO", "KOH", "HCN", "(NH4)2SO4", "Fe(CN)6", "SO₄²⁻", "Ba²⁺", "Cl−",
    "Fe^3+", "BaSO₄", "O2–", "OH–", "MgSO4•7H2O", "CuSO4·5H2O", "Na2SO4•10H2O",
]  # fmt: skip


@pytest.mark.parametrize("formula", FORMULAS)
def test_formula_is_one_regex_span(formula):
    text = f"The substance {formula} is here."
    assert [(s.text, s.label, s.source) for s in regex_only(text)] == [
        (formula, "formula", "regex")
    ]


def test_formula_offsets_ignore_coefficients_and_brackets():
    text = "2H2 + O2 -> 2H2O, K = [NH3]^2 / ([N2][H2]^3), [H+] and [OH-]"
    spans = regex_only(text)
    assert [s.text for s in spans] == ["H2", "O2", "H2O", "NH3", "N2", "H2", "H+", "OH-"]
    assert text[spans[0].start - 1] == "2"
    assert text[spans[3].start - 1] == "["
    assert text[spans[6].start - 1] == "["


def test_element_table_has_all_118_symbols():
    assert len(entities._ELEMENTS) == 118


def test_nbsp_before_a_spaced_charge_is_still_one_ion():
    assert [s.text for s in regex_only("the SO4\u00a02- ion")] == ["SO4\u00a02-"]


def test_a_dash_between_two_formulas_is_not_a_charge():
    assert [s.text for s in regex_only("the H2O–CO2 system and O2– ion")] == ["H2O", "CO2", "O2–"]


def test_a_hydrate_dot_without_a_second_formula_ends_the_span():
    assert [s.text for s in regex_only("MgSO4• and CuSO4·, then H2O.")] == ["MgSO4", "CuSO4", "H2O"]


def test_electron_configurations_are_not_formulas():
    text = "ANSWER: [Ne]3s23p6 and [Xe] 6s15d104f14, [He]2s22p5"
    assert regex_only(text) == []


def test_charges_are_part_of_an_ion_but_a_hyphenated_word_is_not():
    spans = regex_only("Na+ and Cl- cross the Na+/K+ pump, not the Na-K or H-bond.")
    assert [s.text for s in spans] == ["Na+", "Cl-", "Na+", "K+"]


def test_a_parenthesised_symbol_without_a_subscript_is_not_a_formula():
    assert regex_only("Copyright (C) 2024, the (BS) degree and group (P) and (FF).") == []


def test_shouted_prose_does_not_turn_no_into_nitric_oxide():
    assert regex_only("IN NO EVENT SHALL THE AUTHORS BE LIABLE. NO WARRANTY. SEE CO NOW") == []
    spans = regex_only("Nitric oxide, NO, relaxes smooth muscle, unlike CO.")
    assert [s.text for s in spans] == ["NO", "CO"]


@pytest.mark.parametrize(
    "text",
    [
        "He said no, and in the end As and At are not Be.",
        "NASA, the DNA of RNA, ATP, UV light and the USA at the NSB.",
        "TOSS-UP BONUS NOT EXCEPT CPU ICU SOS",
        "pH 7 at 25 °C, 10 mmHg, 5 kPa, 3 MHz, 2 Hz",
        "Vitamin C and iron Fe, section B, type O, C-14 and U-235 and Fe-56",
        "Which of the following is NOT part of the human respiratory system?",
    ],
)
def test_ordinary_words_and_acronyms_are_not_formulas(text):
    assert regex_only(text) == []


# --- IUPAC-like names ------------------------------------------------------------------------

IUPAC_NAMES = [
    "2-methylpropan-1-ol", "1,2-dichloroethane", "butan-1-ol", "butan-2-ol",
    "2-methylpropan-2-ol", "propan-2-one", "3-methylbut-1-ene", "but-1-ene",
    "propane-1,2-diol", "2,2,4-trimethylpentane", "2-chloro-3-methylpentane", "ethanoic acid",
    "ethene", "Ethene", "methane", "methanol", "propanone", "cyclohexane", "isobutyl",
    "tert-butyl", "n-hexane", "1-propanol", "2-aminoethanol", "1-bromo-2-chloroethane",
    "benzene", "pent-2-yne", "2-hydroxypropanoic acid", "butadiene", "1,3-butadiene",
    "buta-1,3-diene",
]  # fmt: skip


@pytest.mark.parametrize("name", IUPAC_NAMES)
def test_iupac_like_name_is_one_chemical_span(name):
    text = f"Name the compound {name} here."
    assert [(s.text, s.label, s.source) for s in regex_only(text)] == [(name, "chemical", "regex")]


@pytest.mark.parametrize(
    "word",
    [
        "ethical", "decal", "octal", "metal", "petal", "butter", "button", "hexagon", "pentagon",
        "nonsense", "decade", "propel", "dial", "trial", "methylation", "2-fold", "3-dimensional",
        "second-order", "first-order", "x-axis", "1-2", "bromo", "chloro",
    ],
)  # fmt: skip
def test_ordinary_words_are_not_iupac_names(word):
    assert regex_only(f"The {word} is here.") == []


# --- Gene and protein symbols ----------------------------------------------------------------


@pytest.mark.parametrize("symbol", ["BRCA1", "TP53", "CDK2", "HER2", "IL6", "HOXA13", "SOX2"])
def test_symbol_with_digits_is_a_gene(symbol):
    assert found(regex_only(f"Mutations in {symbol} cause disease.")) == [(symbol, "gene")]


@pytest.mark.parametrize("symbol", ["p53", "p21", "p300"])
def test_p_number_is_a_protein(symbol):
    assert found(regex_only(f"The {symbol} level rises.")) == [(symbol, "protein")]


@pytest.mark.parametrize("symbol", ["CFTR", "HBB", "DMD", "APOE"])
def test_known_bare_letter_symbol_is_a_gene(symbol):
    assert found(regex_only(f"W) {symbol}")) == [(symbol, "gene")]


@pytest.mark.parametrize("text", ["the ATM gene", "gene XYZ", "XYZ genes"])
def test_symbol_next_to_the_word_gene_is_a_gene(text):
    symbol = re.search(r"[A-Z]{3}", text).group()
    assert found(regex_only(text)) == [(symbol, "gene")]


def test_acronyms_without_gene_context_are_not_genes():
    assert regex_only("DNA and RNA and ATP, NASA, UV, pH, T3 and A1C.") == []


def test_a_formula_is_never_also_a_gene():
    assert found(regex_only("CH3OH and CO2")) == [("CH3OH", "formula"), ("CO2", "formula")]


# --- Enzyme and protein words (heuristic back-stop for CRAFT) ---------------------------------

ENZYMES = [
    "amylase", "Amylase", "lipase", "catalase", "kinase", "ligase", "helicase", "hydrolase",
    "protease", "nuclease", "endonuclease", "urease", "polymerase", "transcriptase", "synthase",
    "synthetase", "oxidase", "peroxidase", "dehydrogenase", "phosphatase", "topoisomerase",
    "telomerase", "ATPase", "GTPase", "DNase", "RNase", "lactase", "sucrase", "luciferase",
    "oxidoreductase", "neuraminidase", "galactosidase", "POLYMERASE", "kinases", "polymerases",
    "proteases", "lyase", "isomerase", "primase", "cellulase",
]  # fmt: skip

NOT_ENZYMES = [
    "base", "bases", "case", "cases", "phase", "phases", "metaphase", "prophase", "anaphase",
    "telophase", "interphase", "prometaphase", "subphases", "increase", "increases", "decrease",
    "decreases", "disease", "diseases", "release", "releases", "purchase", "purchases",
    "repurchases", "grease", "greases", "chase", "erase", "lease", "please", "cease", "ceases",
    "ease", "tease", "crease", "phrase", "phrases", "paraphrase", "plagioclase", "orthoclase",
    "periclase", "database", "nucleobase", "lowercase", "uppercase", "suitcase", "crankcase",
    "showcase", "staircase", "gases", "vase", "oases", "dase", "tase", "nase", "aliases",
    "biases", "atlases", "canvases", "titlecase", "swapcase", "BaseTestCase", "pillowcase",
]  # fmt: skip


@pytest.mark.parametrize("word", ENZYMES)
def test_ase_word_is_a_protein(word):
    spans = regex_only(f"The {word} is here.")
    assert [(s.text, s.label, s.source) for s in spans] == [(word, "protein", "regex")]


@pytest.mark.parametrize("word", NOT_ENZYMES)
def test_everyday_ase_words_are_not_proteins(word):
    assert regex_only(f"The {word} is here.") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Which DNA polymerase is used?", "DNA polymerase"),
        ("RNA polymerase II reads it.", "RNA polymerase"),
        ("ATP synthase spins.", "ATP synthase"),
        ("A protein kinase adds phosphate.", "protein kinase"),
        ("HIV uses reverse transcriptase.", "reverse transcriptase"),
        ("A restriction endonuclease cuts DNA.", "restriction endonuclease"),
        ("The alpha-amylase works.", "amylase"),
        ("It is (amylase), not lipase.", "amylase"),
    ],
)
def test_enzyme_phrase_takes_an_acronym_or_known_modifier_but_not_other_words(text, expected):
    assert regex_only(text)[0].text == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Cells activate kinase signalling.", ["kinase"]),
        ("ANSWER: THE POLYMERASE", ["POLYMERASE"]),
        ("ANSWER: AMYLASE", ["AMYLASE"]),
        ("Short Answer Catalase breaks it down.", ["Catalase"]),
        ("Multiple Choice Amylase starts the process.", ["Amylase"]),
        ("W) amylase X) lipase Y) protease", ["amylase", "lipase", "protease"]),
    ],
)
def test_enzyme_span_does_not_swallow_verbs_headers_or_choice_letters(text, expected):
    assert [s.text for s in regex_only(text)] == expected


def test_a_substrate_the_model_knows_joins_the_enzyme_name():
    text = "Alcohol dehydrogenase converts ethanol to acetaldehyde."
    spans = with_ner(text, ("Alcohol", "CHEBI"), ("ethanol", "CHEBI"))
    assert [(s.text, s.label) for s in spans[:2]] == [
        ("Alcohol dehydrogenase", "protein"),
        ("ethanol", "chemical"),
    ]
    assert spans[0].source == "regex"
    assert regex_only(text)[0].text == "dehydrogenase"  # without NER nothing names the substrate


def test_a_phrase_the_model_tagged_whole_is_claimed_as_a_protein():
    spans = with_ner("Alcohol dehydrogenase works.", ("Alcohol dehydrogenase", "CHEBI"))
    assert [(s.text, s.label, s.source) for s in spans] == [
        ("Alcohol dehydrogenase", "protein", "regex")
    ]


def test_a_phrase_under_a_dropped_label_still_names_the_enzyme():
    text = "The enzyme alcohol dehydrogenase works."
    spans = with_ner(text, ("enzyme alcohol dehydrogenase", "SO"))
    assert [(s.text, s.label) for s in spans] == [("alcohol dehydrogenase", "protein")]


def test_a_long_model_phrase_does_not_become_an_enzyme_name():
    text = "A sequence encoding the polymerase is here."
    spans = with_ner(text, ("sequence encoding the polymerase", "SO"))
    assert [s.text for s in spans] == ["polymerase"]


def test_a_substrate_the_stoplist_hides_is_not_absorbed():
    spans = with_ner("The acid phosphatase works.", ("acid", "CHEBI"))
    assert [s.text for s in spans] == ["phosphatase"]


PROTEIN_WORDS = [
    "hemoglobin", "Hemoglobin", "haemoglobin", "myoglobin", "insulin", "keratin", "myosin",
    "actin", "collagen", "albumin", "pepsin", "trypsin", "chymotrypsin", "oxytocin",
    "vasopressin", "erythropoietin", "gonadotropin", "immunoglobulin", "ubiquitin", "cyclin",
    "troponin", "tropomyosin", "tubulin", "fibronectin", "thrombin", "casein", "elastin",
    "keratins", "integrins", "globin", "rhodopsin", "somatotropin", "calmodulin", "glucagon",
    "fibrinogen", "interferon", "histone", "HEMOGLOBIN", "calcitonin", "angiotensin",
]  # fmt: skip

NOT_PROTEINS = [
    "begin", "within", "basin", "again", "domain", "margin", "origin", "vitamin", "protein",
    "proteins", "glycoprotein", "robin", "Darwin", "Kelvin", "Franklin", "Einstein", "certain",
    "contain", "brain", "skin", "mountain", "penicillin", "lecithin", "chitin", "lignin",
    "melanin", "toxin", "chain", "main", "rain", "thin", "tin", "spin", "coin", "grain",
    "Calvin", "Martin", "Benjamin", "Latin", "dolphin", "penguin", "serotonin", "auxin",
    "chromatin", "myelin", "paraffin", "gelatin", "niacin", "tannin", "saccharin",
]  # fmt: skip


@pytest.mark.parametrize("word", PROTEIN_WORDS)
def test_known_protein_word_is_a_protein(word):
    spans = regex_only(f"The {word} is here.")
    assert [(s.text, s.label, s.source) for s in spans] == [(word, "protein", "regex")]


@pytest.mark.parametrize("word", NOT_PROTEINS)
def test_everyday_in_words_are_not_proteins(word):
    assert regex_only(f"The {word} is here.") == []


def test_regex_turns_a_model_chemical_hemoglobin_into_a_protein():
    spans = with_ner("Each hemoglobin binds oxygen.", ("hemoglobin", "CHEBI"), ("oxygen", "CHEBI"))
    assert [(s.text, s.label, s.source) for s in spans] == [
        ("hemoglobin", "protein", "regex"),
        ("oxygen", "chemical", "ner"),
    ]


# --- Overlaps: longer span wins, then regex over NER, then leftmost ---------------------------


def test_longer_regex_span_beats_a_shorter_ner_span():
    text = "Gypsum contains SO4 2- ions."
    spans = with_ner(text, ("SO4", "CHEBI"))
    assert [(s.text, s.label, s.source) for s in spans] == [("SO4 2-", "formula", "regex")]


def test_longer_ner_span_beats_a_shorter_regex_span():
    spans = with_ner("The Na+ ion pump works.", ("Na+ ion pump", "CHEBI"))
    assert [(s.text, s.label, s.source) for s in spans] == [("Na+ ion pump", "chemical", "ner")]


def test_on_equal_extent_regex_beats_ner_so_a_formula_stays_a_formula():
    spans = with_ner("Cellular respiration makes CO2.", ("CO2", "CHEBI"))
    assert [(s.text, s.label, s.source) for s in spans] == [("CO2", "formula", "regex")]


def test_on_equal_length_overlap_the_leftmost_span_wins():
    text = "glucose fructose"
    spans = SciEntityDetector(nlp=FakeNlp(offsets=((0, 7, "CHEBI"), (4, 11, "CHEBI")))).detect(text)
    assert [(s.start, s.end) for s in spans] == [(0, 7)]


def test_adjacent_spans_are_both_kept():
    text = "glucosefructose"
    spans = SciEntityDetector(nlp=FakeNlp(offsets=((0, 7, "CHEBI"), (7, 15, "CHEBI")))).detect(text)
    assert [(s.start, s.end) for s in spans] == [(0, 7), (7, 15)]


def test_repeated_entity_gets_one_span_per_occurrence():
    text = "CO2 in, CO2 out"
    assert [(s.start, s.text) for s in regex_only(text)] == [(0, "CO2"), (8, "CO2")]


def test_overlap_sweep_matches_a_brute_force_greedy_reference():
    rng = random.Random(11)
    for _ in range(200):
        cands = []
        for _ in range(rng.randint(1, 25)):
            start = rng.randint(0, 40)
            end, rank = start + rng.randint(1, 8), rng.randint(0, 3)
            cands.append(entities._Cand(start, end, "chemical", "ner", rank))
        expected: list[entities._Cand] = []
        for cand in sorted(cands, key=lambda c: (c.start - c.end, c.rank, c.start)):
            if all(cand.end <= k.start or cand.start >= k.end for k in expected):
                expected.append(cand)
        assert entities._resolve_overlaps(cands) == sorted(expected, key=lambda c: c.start)


# --- R5 and offsets --------------------------------------------------------------------------


def test_span_text_is_the_pasted_text_never_a_resolved_or_common_name():
    # R5 regression: a NER entity whose own .text is a common name must not leak into the span.
    text = "Which of these is NaHCO3?"
    start = text.index("NaHCO3")
    ents = [FakeEnt(start, start + len("NaHCO3"), "CHEBI", "baking soda")]
    spans = SciEntityDetector(nlp=lambda _text: SimpleNamespace(ents=ents)).detect(text)
    assert [s.text for s in spans] == ["NaHCO3"]
    assert "baking soda" not in repr(spans)
    assert_well_formed(text, spans)
    assert [s.text for s in regex_only(text)] == ["NaHCO3"]


def test_offsets_hold_after_unicode_and_leading_whitespace():
    text = "  \n Barium ions, Ba²⁺, react with SO₄²⁻ ions; ΔH is −890 kJ/mol."
    spans = regex_only(text)
    assert [s.text for s in spans] == ["Ba²⁺", "SO₄²⁻"]
    assert_well_formed(text, spans)


def test_crlf_text_keeps_offsets():
    text = "Water\r\nH2O\r\nCO2"
    spans = regex_only(text)
    assert [s.text for s in spans] == ["H2O", "CO2"]
    assert_well_formed(text, spans)


def _fixture_texts() -> list[str]:
    return [p.read_text(encoding="utf-8") for p in sorted(FIXTURES.glob("*.txt"))]


@pytest.mark.skipif(not FIXTURES.exists(), reason="fixtures not generated")
def test_every_fixture_gives_well_formed_spans():
    nlp = FakeNlp(("glucose", "CHEBI"), ("hemoglobin", "CHEBI"), ("insulin X", "GGP"))
    detector = SciEntityDetector(nlp=nlp)
    for text in _fixture_texts():
        assert_well_formed(text, detector.detect(text))


def test_random_noise_never_raises_and_stays_well_formed():
    rng = random.Random(7)
    alphabet = "HNaClO2()+-−^ ,[]abcpXY1,3ptBRCAmethylprop·₂²⁺⇌\n.W)"
    detector = SciEntityDetector(nlp=FakeNlp(("Na", "CHEBI"), ("pro", "GGP")))
    for _ in range(300):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 80)))
        assert_well_formed(text, detector.detect(text))


@pytest.mark.parametrize(
    "text",
    ["A" * 20_000, "ethan" * 5_000, "1,2-" * 5_000, "(" * 5_000, "Na+" * 5_000, "methyl-" * 3_000,
     "H2O " * 10_000, "CH3(CH2)" * 2_000, "gene " * 5_000, "AB1 " * 5_000, "H2O•2" * 5_000,
     "A•1" * 8_000, "Na2SO4•10H2O•" * 2_000, "O2–" * 5_000],
)  # fmt: skip
def test_hostile_input_does_not_backtrack_catastrophically(text):
    started = time.monotonic()
    regex_only(text)
    assert time.monotonic() - started < 3.0


# --- preload and fallback --------------------------------------------------------------------


def test_injected_nlp_needs_no_loading(monkeypatch):
    def boom(model):
        raise AssertionError("must not load a model")

    monkeypatch.setattr(entities, "_load_spacy", boom)
    detector = SciEntityDetector(nlp=FakeNlp(("glucose", "CHEBI")))
    detector.preload()
    assert found(detector.detect("glucose")) == [("glucose", "chemical")]


def test_preload_returns_at_once_and_detect_waits_for_the_model(monkeypatch):
    gate, started = threading.Event(), threading.Event()

    def slow_loader(model):
        started.set()
        gate.wait(10)
        return FakeNlp(("Insulin", "GGP"))

    monkeypatch.setattr(entities, "_load_spacy", slow_loader)
    detector = SciEntityDetector()
    t0 = time.monotonic()
    detector.preload()
    assert time.monotonic() - t0 < 1.0
    assert started.wait(5)

    result: dict[str, list[EntitySpan]] = {}
    worker = threading.Thread(target=lambda: result.update(spans=detector.detect("Insulin acts.")))
    worker.start()
    time.sleep(0.2)
    assert worker.is_alive()  # still waiting for the model
    gate.set()
    worker.join(10)
    assert not worker.is_alive()
    assert found(result["spans"]) == [("Insulin", "protein")]


def test_model_loads_once_across_preload_and_concurrent_detects(monkeypatch):
    loads: list[str] = []

    def loader(model):
        loads.append(model)
        time.sleep(0.1)
        return FakeNlp(("glucose", "CHEBI"))

    monkeypatch.setattr(entities, "_load_spacy", loader)
    detector = SciEntityDetector("some_model")
    detector.preload()
    detector.preload()
    results: list[list[EntitySpan]] = []
    threads = [
        threading.Thread(target=lambda: results.append(detector.detect("glucose")))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert loads == ["some_model"]
    assert [found(r) for r in results] == [[("glucose", "chemical")]] * 8


@pytest.mark.parametrize(
    "error", [OSError("E050 no such model"), ImportError("no spacy"), ValueError("bad")]
)
def test_load_failure_falls_back_to_regex_and_logs_once(monkeypatch, caplog, error):
    def failing_loader(model):
        raise error

    monkeypatch.setattr(entities, "_load_spacy", failing_loader)
    detector = SciEntityDetector("missing_model")
    detector.preload()
    with caplog.at_level(logging.WARNING, logger="cloudyreader.entities"):
        first = detector.detect("The CO2 level and glucose.")
        second = detector.detect("Water, H2O.")
    assert found(first) == [("CO2", "formula")]
    assert found(second) == [("H2O", "formula")]
    warnings = [r for r in caplog.records if r.name == "cloudyreader.entities"]
    assert len(warnings) == 1
    assert "missing_model" in warnings[0].getMessage()


def test_inference_failure_falls_back_to_regex_and_logs_once(caplog):
    class Exploding:
        def __call__(self, text):
            raise RuntimeError("E088 text too long")

    detector = SciEntityDetector(nlp=Exploding())
    with caplog.at_level(logging.WARNING, logger="cloudyreader.entities"):
        assert found(detector.detect("CO2")) == [("CO2", "formula")]
        assert found(detector.detect("H2O")) == [("H2O", "formula")]
    assert len([r for r in caplog.records if r.name == "cloudyreader.entities"]) == 1


@pytest.mark.slow
def test_absent_real_model_falls_back_to_regex_only(caplog):
    detector = SciEntityDetector("cloudyreader_no_such_model")
    with caplog.at_level(logging.WARNING, logger="cloudyreader.entities"):
        spans = detector.detect("Water, H2O, and 1,2-dichloroethane.")
    assert found(spans) == [("H2O", "formula"), ("1,2-dichloroethane", "chemical")]
    detector.detect("CO2 again")
    assert len([r for r in caplog.records if r.name == "cloudyreader.entities"]) == 1


# --- Real CRAFT model ------------------------------------------------------------------------
# en_ner_craft_md misses amylase, sucrase and DNA polymerase, yields only "Alcohol" for "alcohol
# dehydrogenase", and tags hemoglobin CHEBI; the -ase and protein-word heuristics repair those.

# It also returns cation-less partial names ("dioxide" for carbon dioxide, "oxide" for iron(III)
# oxide); the detector drops those. Enzyme names outside the heuristics stay NER-only.

PROBES = [
    (
        "Mutations in the tumor suppressor gene TP53, which encodes the protein p53, are found "
        "in about half of all human cancers.",
        {("TP53", "gene"), ("p53", "protein")},
    ),
    (
        "Mutations in which of the following genes are the primary cause of cystic fibrosis?\n"
        "BRCA1\nCFTR\nHBB\nDMD",
        {("BRCA1", "gene"), ("CFTR", "gene"), ("HBB", "gene"), ("DMD", "gene")},
    ),
    (
        "Cellular respiration oxidizes glucose, C6H12O6, to produce CO2, H2O, and ATP.",
        {("glucose", "chemical"), ("C6H12O6", "formula"), ("CO2", "formula"), ("H2O", "formula")},
    ),
    (
        "Ethene reacts with chlorine gas, Cl2, to produce 1,2-dichloroethane.",
        {
            ("Ethene", "chemical"),
            ("chlorine", "chemical"),
            ("Cl2", "formula"),
            ("1,2-dichloroethane", "chemical"),
        },
    ),  # fmt: skip
    (
        "Which is the IUPAC name of isobutyl alcohol? W) butan-1-ol X) 2-methylpropan-1-ol",
        {("butan-1-ol", "chemical"), ("2-methylpropan-1-ol", "chemical")},
    ),
    (
        "Barium ions, Ba²⁺, react with SO₄²⁻ ions in solution.",
        {("Ba²⁺", "formula"), ("SO₄²⁻", "formula")},
    ),
    (
        "Insulin is secreted by beta cells in response to glucose.",
        {("Insulin", "protein"), ("glucose", "chemical")},
    ),
    (
        "Each molecule of hemoglobin binds oxygen, and amylase in saliva breaks down starch.",
        {("hemoglobin", "protein"), ("amylase", "protein"), ("oxygen", "chemical")},
    ),
    (
        "Alcohol dehydrogenase converts ethanol to acetaldehyde, and DNA polymerase copies DNA.",
        {
            ("Alcohol dehydrogenase", "protein"),
            ("DNA polymerase", "protein"),
            ("ethanol", "chemical"),
        },
    ),
]


@pytest.fixture(scope="module")
def real_detector():
    if importlib.util.find_spec("en_ner_craft_md") is None:
        pytest.skip("en_ner_craft_md is not installed (run: make models)")
    detector = SciEntityDetector()
    detector.preload()
    return detector


@pytest.mark.model
@pytest.mark.parametrize(("text", "expected"), PROBES)
def test_real_model_probe_sentences(real_detector, text, expected):
    spans = real_detector.detect(text)
    assert_well_formed(text, spans)
    assert expected <= set(found(spans))


@pytest.mark.model
def test_real_model_trims_the_spans_it_gets_wrong(real_detector):
    text = "the tumor suppressor gene TP53, which encodes the protein p53, W) BRCA1 X) CFTR"
    texts = {s.text for s in real_detector.detect(text)}
    assert {"TP53", "p53", "BRCA1", "CFTR"} <= texts
    assert not texts & {"suppressor gene TP53", "protein p53", "BRCA1 X", "CFTR Y"}


@pytest.mark.model
def test_real_model_adds_ner_hits_the_regexes_cannot_find(real_detector):
    spans = real_detector.detect("Cells burn glucose in response to hunger.")
    assert [(s.text, s.label, s.source) for s in spans] == [("glucose", "chemical", "ner")]
