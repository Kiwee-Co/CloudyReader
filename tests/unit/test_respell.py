"""Respelling to IPA: engine on an inline rule document, then the shipped data vs the golden."""

from __future__ import annotations

import copy
import csv
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from cloudyreader import respell
from cloudyreader.respell import RuleTable, default_rules, parse_rules, piper_safe, to_ipa

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden" / "respelling_cases.yaml"
VOICE_JSON = ROOT / ".data" / "voices" / "en_US-lessac-medium.onnx.json"
CORPUS = ROOT / "tests" / "golden" / "corpus" / "respellings.tsv"

# fmt: off
# A small document in the shape of data/respelling_rules.json.
INLINE: dict[str, Any] = {
    "schema": 1,
    "entries": {
        "stress": {"primary": "ˈ", "secondary": "ˌ", "placement": "before-syllable"},
        "vowel_symbols": "aeiouæɑɔɛɪʊʌəɚɜ",
        "rules": [
            ["yoor", "jʊɹ"], ["eye", "aɪ"], ["yay", "jeɪ"], ["yoo", "ju"],
            ["air", "ɛɹ"], ["eer", "ɪɹ"], ["oor", "ʊɹ"],
            ["ar", "ɑɹ"], ["or", "ɔɹ"], ["er", "ɚ"], ["ur", "ɚ"],
            ["ay", "eɪ"], ["ee", "i"], ["oo", "u"], ["oh", "oʊ"], ["uh", "ə"], ["ah", "ɑ"],
            ["ow", "aʊ"], ["ye", "aɪ"],
            ["ch", "tʃ"], ["sh", "ʃ"], ["zh", "ʒ"], ["th", "θ"], ["dh", "ð"], ["ng", "ŋ"],
            ["kw", "kw"], ["ks", "ks"],
            ["a", "æ"], ["e", "ɛ"], ["i", "ɪ"], ["o", "ɑ"], ["u", "ə"], ["y", "aɪ"],
            ["b", "b"], ["d", "d"], ["f", "f"], ["g", "ɡ"], ["h", "h"], ["j", "dʒ"],
            ["k", "k"], ["l", "l"], ["m", "m"], ["n", "n"], ["p", "p"], ["r", "ɹ"],
            ["s", "s"], ["t", "t"], ["v", "v"], ["w", "w"], ["z", "z"],
        ],
        "stressed_rules": [["uh", "ʌ"], ["u", "ʌ"], ["ur", "ɜɹ"], ["er", "ɜɹ"]],
        "r_link_rules": [["ar", "æɹ"], ["er", "ɛɹ"]],
    },
}
# fmt: on


def table(*, placement: str = "before-syllable") -> RuleTable:
    doc = copy.deepcopy(INLINE)
    doc["entries"]["stress"]["placement"] = placement
    return parse_rules(doc)


RULES = table()


def ipa(text: str) -> str | None:
    return to_ipa(text, rules=RULES)


@pytest.mark.parametrize(
    ("respelling", "expected"),
    [
        ("FAR-ingks", "ˈfæɹɪŋks"),
        ("i-SOF-uh-guhs", "ɪˈsɑfəɡəs"),
        ("TRAY-kee-uh", "ˈtɹeɪkiə"),
        ("KREBZ SY-kul", "ˈkɹɛbz ˈsaɪkəl"),
        ("nye-DAIR-ee-uh", "naɪˈdɛɹiə"),
    ],
)
def test_brief_examples(respelling: str, expected: str) -> None:
    assert ipa(respelling) == expected


class TestStress:
    def test_mark_sits_before_the_syllable_onset(self) -> None:
        assert ipa("sub-DUK-shun") == "səbˈdʌkʃən"

    def test_mark_can_sit_before_the_nucleus_instead(self) -> None:
        nuclear = table(placement="before-nucleus")
        assert to_ipa("sub-DUK-shun", rules=nuclear) == "səbdˈʌkʃən"
        assert to_ipa("TRAY-kee-uh", rules=nuclear) == "tɹˈeɪkiə"
        assert to_ipa("OH-bee", rules=nuclear) == "ˈoʊbi"

    def test_each_word_restarts_primary(self) -> None:
        assert ipa("HAR-dee WYN-berg") == "ˈhɑɹdi ˈwaɪnbɚɡ"

    def test_later_caps_syllables_get_secondary(self) -> None:
        assert ipa("FOS-foh-FRUK-toh-KY-nays") == "ˈfɑsfoʊˌfɹʌktoʊˌkaɪneɪs"

    def test_adjacent_and_separated_caps_syllables_each_marked(self) -> None:
        assert ipa("KAR-BOH-hy-drayt") == "ˈkɑɹˌboʊhaɪdɹeɪt"
        assert ipa("SOO-per-NOH-vuh") == "ˈsupɚˌnoʊvə"

    def test_no_caps_means_no_stress_mark(self) -> None:
        assert ipa("buh-nan-uh") == "bənænə"

    def test_lone_caps_syllable_is_stressed(self) -> None:
        assert ipa("JOOL") == "ˈdʒul"

    def test_lone_lowercase_syllable_inside_a_longer_guide_is_unstressed(self) -> None:
        assert ipa("luh shat-el-YAY") == "lə ʃætɛlˈjeɪ"
        assert ipa("kin ten") == "kɪn tɛn"

    def test_a_guide_that_is_one_lowercase_syllable_is_stressed(self) -> None:
        # [jool] [saks] [tork]: the whole guide is the word, so its only syllable carries stress.
        assert ipa("jool") == "ˈdʒul"
        assert ipa("saks") == "ˈsæks"
        assert ipa("Jool") == "ˈdʒul"
        assert ipa("buh-nan-uh") == "bənænə"  # several syllables, none marked: stays unmarked

    def test_title_case_syllable_is_unstressed(self) -> None:
        assert ipa("Tray-kee-uh") == "tɹeɪkiə"
        assert ipa("Pas-TUR") == "pæsˈtɜɹ"

    def test_stressed_rules_apply_only_inside_caps_syllables(self) -> None:
        assert ipa("PUL-sar") == "ˈpʌlsɑɹ"
        assert ipa("pul-SAR") == "pəlˈsɑɹ"
        assert ipa("FUR-mee-on") == "ˈfɜɹmiɑn"
        assert ipa("fur-MEE-on") == "fɚˈmiɑn"

    def test_r_link_needs_a_stressed_syllable_end_and_a_vowel_next(self) -> None:
        assert ipa("KAR-uh-teen") == "ˈkæɹətin"  # stressed, vowel follows
        assert ipa("PAR-sek") == "ˈpɑɹsɛk"  # consonant follows
        assert ipa("SAR") == "ˈsɑɹ"  # nothing follows
        assert ipa("sar-uh-KOH") == "sɑɹəˈkoʊ"  # unstressed: no link
        assert ipa("PAR kuh") == "ˈpɑɹ kə"  # the next word does not count

    def test_r_link_beats_the_stressed_rule(self) -> None:
        assert ipa("BER-ee") == "ˈbɛɹi"
        assert ipa("BER-lin") == "ˈbɜɹlɪn"

    def test_all_caps_multisyllable_word_is_unplaceable(self) -> None:
        assert ipa("FAR-INGKS") is None


class TestLetterRules:
    @pytest.mark.parametrize(
        ("respelling", "expected"),
        [
            ("YAY", "ˈjeɪ"),
            ("yoo-KAIR-ee-oht", "juˈkɛɹioʊt"),
            ("MYOO-on", "ˈmjuɑn"),
            ("FYOOR-ik", "ˈfjʊɹɪk"),
            ("SY-kul", "ˈsaɪkəl"),
            ("rye", "ˈɹaɪ"),  # a lone lowercase syllable is stressed
            ("ye", "ˈaɪ"),  # the table decides: plain ye is the vowel
        ],
    )
    def test_y_graphemes(self, respelling: str, expected: str) -> None:
        assert ipa(respelling) == expected

    def test_longest_grapheme_wins(self) -> None:
        # "eer" is one r-vowel, not "ee" then "r"; "ng" is one sound, not n then g.
        assert ipa("as-THEN-uh-sfeer") == "æsˈθɛnəsfɪɹ"
        assert ipa("BRONG-ky") == "ˈbɹɑŋkaɪ"

    def test_order_of_the_rule_list_does_not_matter(self) -> None:
        shuffled = copy.deepcopy(INLINE)
        shuffled["entries"]["rules"].reverse()
        assert to_ipa("as-THEN-uh-sfeer", rules=parse_rules(shuffled)) == ipa("as-THEN-uh-sfeer")

    def test_a_doubled_consonant_letter_is_one_sound(self) -> None:
        assert ipa("bull") == ipa("bul") == "ˈbʌl"
        assert ipa("AM-ill-ayse") == ipa("AM-il-ayse") == "ˈæmɪleɪs"
        assert ipa("ell") == ipa("el") == "ˈɛl"

    def test_doubled_vowel_letters_are_not_collapsed(self) -> None:
        assert ipa("kee") == "ˈki"  # ee is a grapheme, not a doubled consonant

    def test_lowercase_has_no_stress_and_no_stress_only_rules(self) -> None:
        assert ipa("far-ingks") == "fɑɹɪŋks"


class TestCleaning:
    def test_wrapped_line_leaves_a_spaced_hyphen(self) -> None:
        assert ipa("i-SOF-uh- guhs") == ipa("i-SOF-uh-guhs")
        assert ipa("i-SOF-uh -guhs") == ipa("i-SOF-uh-guhs")

    def test_unicode_hyphens_and_spaces(self) -> None:
        assert ipa("i\u2010SOF\u2011uh\u2013guhs") == ipa("i-SOF-uh-guhs")
        assert ipa("KREBZ\u00a0\u00a0SY\u2212kul") == ipa("KREBZ SY-kul")

    def test_macron_o_with_silent_e_is_long_o(self) -> None:
        # Real guides write the OH sound as ōe: [fōe-tōe-SIN-teh-sis], [TŌE].
        assert ipa("TŌE") == ipa("TOH") == "ˈtoʊ"
        assert ipa("fōe-tōe") == ipa("foh-toh") == "foʊtoʊ"
        assert ipa("to\u0304e") == ipa("toh")  # decomposed o + combining macron
        assert ipa("prōe-KAHR-ee- ōets") == ipa("proh-KAHR-ee-ohts")  # ōe + ts = "oats"

    def test_surrounding_whitespace(self) -> None:
        assert ipa("  TRAY-kee-uh \n") == ipa("TRAY-kee-uh")

    def test_alternate_pronunciation_speaks_the_first(self) -> None:
        assert ipa("pi-KAHN or PEE-kan") == ipa("pi-KAHN") == "pɪˈkɑn"


class TestSilentE:
    """A syllable ending in a silent e is read with its long vowel, taken from the table."""

    @pytest.mark.parametrize(
        ("guide", "expected"),
        [
            ("dare", "ˈdɛɹ"),
            ("more", "ˈmɔɹ"),
            ("fire", "ˈfaɪɹ"),
            ("here", "ˈhɪɹ"),
            ("pure", "ˈpjʊɹ"),
            ("tube", "ˈtub"),
            ("robe", "ˈɹoʊb"),
            ("ide", "ˈaɪd"),
            ("site", "ˈsaɪt"),
            ("klaze", "ˈkleɪz"),
        ],
    )
    def test_vowel_consonant_e(self, guide: str, expected: str) -> None:
        assert ipa(guide) == expected

    def test_soft_c_and_g_before_the_silent_e(self) -> None:
        assert ipa("ace") == "ˈeɪs"
        assert ipa("age") == "ˈeɪdʒ"

    def test_plural_and_past_endings_after_the_silent_e(self) -> None:
        assert ipa("sites") == "ˈsaɪts"
        assert ipa("rides") == "ˈɹaɪds"

    def test_a_past_tense_ending_is_not_a_silent_e_tail(self) -> None:
        assert ipa("lated") is None  # the d needs a vowel of its own: no guess

    def test_vowel_pair_then_consonant_then_silent_e(self) -> None:
        assert ipa("nayse") == "ˈneɪs"
        assert ipa("AM-il-ayse") == "ˈæmɪleɪs"

    def test_a_reading_that_already_has_one_vowel_is_left_alone(self) -> None:
        assert ipa("tle") == "ˈtlɛ"
        assert ipa("kee") == "ˈki"

    def test_the_number_word_one_is_not_read_as_ohn(self) -> None:
        assert ipa("one") is None

    def test_two_consonants_before_the_e_do_not_lengthen_the_vowel(self) -> None:
        assert ipa("dense") is None  # no long-vowel guess for "-nse"

    def test_whole_guide_with_silent_e_syllables(self) -> None:
        assert ipa("PRO-dare-ee-ide") == "ˈpɹɑdɛɹiaɪd"


class TestSyllabicConsonant:
    def test_lone_l_m_n_after_a_syllable_gets_a_schwa(self) -> None:
        assert ipa("AD-n-een") == "ˈædənin"
        assert ipa("BEE-tl") == "ˈbitəl"
        assert ipa("BOT-m") == "ˈbɑtəm"

    def test_a_lone_sonorant_after_a_vowel_is_just_the_coda(self) -> None:
        assert ipa("ETH-eye-n") == "ˈɛθaɪn"
        assert ipa("FOH-l") == "ˈfoʊl"

    def test_not_at_the_start_of_a_word_and_not_for_other_consonants(self) -> None:
        assert ipa("N-ah-see") is None  # a spelled letter, not a syllabic n
        assert ipa("BEE-t") is None
        assert ipa("bee-N") is None  # CAPS carries stress; a stressed lone n is not a syllable


class TestUnknownIsNone:
    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "-",
            "FAR-",
            "-ingks",
            "FAR--ingks",
            "QUAK",  # q is not in this table
            "ZAX-un",  # nor is x
            "FAR-xyz",  # one unknown fragment spoils the whole respelling
            "H2O",
            "Ca2+",
            "H+",
            "1",
            "0, 1",
            "NaCl",  # mixed case inside one syllable
            "STEEl",  # typo: caps then lowercase
            "tRAY-kee-uh",
            "A-T-P",  # all caps, several syllables
            "a-t-p",  # t has no vowel
            "NASA",  # two vowels in one syllable
            "foto",  # two vowels in one syllable, no silent e
            "naïve",
            "TRAY-kee-uh.",
        ],
    )
    def test_returns_none(self, bad: str) -> None:
        assert ipa(bad) is None

    def test_never_returns_a_partial_string(self) -> None:
        assert ipa("FAR-ingks QUAK") is None


class TestPiperSafeSymbols:
    def test_piper_safe_swaps_missing_symbols(self) -> None:
        assert piper_safe("g r ɝ ɡ ɹ") == "ɡ ɹ ɜɹ ɡ ɹ"

    def test_engine_output_is_piper_safe(self) -> None:
        doc = {
            "entries": {
                "vowel_symbols": "əɚɜɝ",
                "rules": [["b", "b"], ["g", "g"], ["r", "r"], ["ur", "ɚ"], ["uh", "ə"]],
                "stressed_rules": [["ur", "ɝ"]],
            }
        }
        ascii_table = parse_rules(doc)
        assert to_ipa("BURG", rules=ascii_table) == "ˈbɜɹɡ"
        assert to_ipa("ruh", rules=ascii_table) == "ˈɹə"


class TestRuleTable:
    def test_empty_table_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            RuleTable(rules={}, vowel_symbols=frozenset("a"))

    def test_match_prefers_the_longest_grapheme(self) -> None:
        rules = RuleTable(rules={"e": "ɛ", "eer": "ɪɹ", "ee": "i"}, vowel_symbols=frozenset("ɛiɪ"))
        assert rules.match("eer", 0) == "eer"
        assert rules.match("eel", 0) == "ee"
        assert rules.match("xe", 1) == "e"
        assert rules.match("xe", 0) is None

    def test_duplicate_grapheme_is_rejected_even_across_case(self) -> None:
        doc = {"entries": {"vowel_symbols": "a", "rules": [["a", "æ"], ["A", "ɑ"]]}}
        with pytest.raises(ValueError, match="twice"):
            parse_rules(doc)

    def test_unknown_placement_is_rejected(self) -> None:
        doc = copy.deepcopy(INLINE)
        doc["entries"]["stress"]["placement"] = "middle"
        with pytest.raises(ValueError, match="placement"):
            parse_rules(doc)

    def test_stress_block_is_optional_and_defaults_to_the_contract(self) -> None:
        doc = {"entries": {"vowel_symbols": "æ", "rules": [["t", "t"], ["a", "æ"]]}}
        assert to_ipa("TAT", rules=parse_rules(doc)) == "ˈtæt"


def _golden_cases() -> list[dict[str, Any]]:
    return yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["cases"]


def _fold(text: str) -> str:
    # The golden header allows ASCII g and r in reference strings.
    return text.replace("g", "ɡ").replace("r", "ɹ")


@pytest.fixture(scope="module")
def piper_symbols() -> frozenset[str]:
    if not VOICE_JSON.exists():
        pytest.skip(f"no Piper voice metadata at {VOICE_JSON}")
    return frozenset(json.loads(VOICE_JSON.read_text(encoding="utf-8"))["phoneme_id_map"])


class TestShippedData:
    def test_golden_corpus_size(self) -> None:
        assert len(_golden_cases()) >= 40

    @pytest.mark.parametrize("case", _golden_cases(), ids=lambda c: f"{c['id']}-{c['respelling']}")
    def test_golden_case(self, case: dict[str, Any]) -> None:
        accepted = {_fold(x) for x in [case["ipa"], *case["alt_ipa"]]}
        assert to_ipa(case["respelling"]) in accepted

    def test_the_data_own_examples_match_the_engine(self) -> None:
        document = json.loads(respell.RULES_FILE.read_text(encoding="utf-8"))
        for example in document["entries"]["examples"]:
            assert to_ipa(example["respelling"]) == example["ipa"], example

    def test_every_rule_symbol_exists_in_the_piper_voice(
        self, piper_symbols: frozenset[str]
    ) -> None:
        rules = default_rules()
        sounds = [*rules.rules.values(), *rules.stressed.values(), *rules.r_link.values()]
        sounds += [rules.primary, rules.secondary]
        missing = {s for sound in sounds for s in piper_safe(sound)} - piper_symbols
        assert not missing, sorted(missing)

    def test_every_golden_output_symbol_exists_in_the_piper_voice(
        self, piper_symbols: frozenset[str]
    ) -> None:
        for case in _golden_cases():
            out = to_ipa(case["respelling"])
            assert out is not None, case["id"]
            assert not set(out) - piper_symbols, (case["id"], sorted(set(out) - piper_symbols))

    def test_vowel_symbols_cover_every_vowel_grapheme(self) -> None:
        # A rule that emits a vowel missing from vowel_symbols would make every syllable
        # using it fail the one-vowel check, silently turning a respelling into None.
        rules = default_rules()
        for grapheme, sound in rules.rules.items():
            if grapheme not in ("qu", "y") and set(grapheme) & set("aeiou"):
                assert rules.is_vocalic(sound), (grapheme, sound)
        for sound in [*rules.stressed.values(), *rules.r_link.values()]:
            assert rules.is_vocalic(sound), sound

    def test_default_rules_are_cached(self) -> None:
        assert default_rules() is default_rules()


def _phonetic_corpus_guides() -> list[str]:
    """Real guides from the sample rounds, minus the ones the parser sends elsewhere.

    Digits, dotted letters and spelled letters (C-A-T) are Respelling kinds "spoken" and "spell".
    """
    if not CORPUS.exists():
        return []
    with CORPUS.open(encoding="utf-8", newline="") as handle:
        guides = [row["respelling"] for row in csv.DictReader(handle, delimiter="\t")]
    return [
        g for g in guides if not re.search(r"\d|\.", g) and not re.fullmatch(r"[A-Z]+(-[A-Z]+)+", g)
    ]


@pytest.fixture(scope="module")
def guides() -> list[str]:
    found = _phonetic_corpus_guides()
    if not found:
        pytest.skip(f"no corpus oracle at {CORPUS}")
    return found


class TestRealCorpus:
    """Guides harvested from real NSB rounds (tests/golden/corpus, written by the corpus agent)."""

    def test_most_real_guides_are_placed(self, guides: list[str]) -> None:
        # What stays None is ordinary spelling in one chunk (hetero-ZYE-gus, organ-ELL): the
        # key cannot read it, and the printed word is better left to the TTS than guessed.
        placed = sum(to_ipa(g) is not None for g in guides)
        assert placed / len(guides) >= 0.88, f"{placed}/{len(guides)} placed"

    def test_no_guide_raises(self, guides: list[str]) -> None:
        for guide in guides:
            to_ipa(guide)

    def test_every_output_symbol_exists_in_the_piper_voice(
        self, guides: list[str], piper_symbols: frozenset[str]
    ) -> None:
        for guide in guides:
            out = to_ipa(guide)
            if out is not None:
                assert not set(out) - piper_symbols, (guide, out, sorted(set(out) - piper_symbols))

    def test_at_most_one_primary_mark_per_word(self, guides: list[str]) -> None:
        for guide in guides:
            out = to_ipa(guide)
            if out is not None:
                assert all(word.count("ˈ") <= 1 for word in out.split(" ")), (guide, out)
