"""Lexicon: token lookup, user-file precedence, and IUPAC segmentation (inline tables first)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cloudyreader.lexicon import Lexicon
from cloudyreader.models import Override
from cloudyreader.respell import piper_safe

ROOT = Path(__file__).resolve().parents[2]
VOICE_JSON = ROOT / ".data" / "voices" / "en_US-lessac-medium.onnx.json"

# fmt: off
# Keys, kinds and compact layout follow data/iupac_morphemes.json: digit locants, exact-case lone
# letters, lowercase words; a monosyllable carries no stress mark, a polysyllable one.
_MORPHEME_ROWS = [
    ("1", "wʌn", "locant"), ("2", "tu", "locant"), ("10", "tɛn", "locant"),
    ("N", "ɛn", "locant"), ("n", "nɔɹməl", "substituent"), ("R", "ɑɹ", "stereo"),
    ("meth", "mɛθ", "stem"), ("eth", "ɛθ", "stem"), ("prop", "pɹoʊp", "stem"),
    ("propa", "ˈpɹoʊpə", "stem"),
    ("methyl", "ˈmɛθɪl", "substituent"), ("ethyl", "ˈɛθɪl", "substituent"),
    ("chloro", "ˈklɔɹoʊ", "substituent"), ("azo", "eɪzoʊ", "substituent"),
    ("an", "eɪn", "suffix"), ("ane", "eɪn", "suffix"), ("ol", "ɑl", "suffix"),
    ("di", "daɪ", "multiplier"),
]
# fmt: on
MORPHEMES = {key: ipa for key, ipa, _ in _MORPHEME_ROWS}
KINDS = {key: kind for key, _, kind in _MORPHEME_ROWS}
PRONUNCIATIONS = {
    "Pharynx": "ˈfɑɹɪŋks",
    "Krebs cycle": "ˈkɹɛbz ˈsaɪkəl",
    "isobutyl alcohol": "ˈaɪsoʊbjutɪl ˈælkəhɔl",
}
ISOBUTANOL = "tu ˈmɛθɪlpɹoʊpeɪn wʌn ɑl"


@pytest.fixture
def lex() -> Lexicon:
    return Lexicon(PRONUNCIATIONS, MORPHEMES, kinds=KINDS)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    morphemes = {key: {"ipa": ipa, "kind": KINDS[key]} for key, ipa in MORPHEMES.items()}
    for name, entries in (("pronunciations", PRONUNCIATIONS), ("iupac_morphemes", morphemes)):
        doc = {"schema": 1, "description": "test", "entries": entries}
        (folder / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")
    return folder


def ipa_of(table: Lexicon, token: str) -> str | None:
    found = table.lookup(token)
    return None if found is None else found.ipa


def said(table: Lexicon, name: str) -> str | None:
    found = table.iupac(name)
    return None if found is None else found.ipa


class TestLookup:
    def test_hit_keeps_the_callers_surface(self, lex: Lexicon) -> None:
        assert lex.lookup("PHARYNX") == Override("PHARYNX", "ˈfɑɹɪŋks", "lexicon")

    def test_case_and_whitespace_insensitive(self, lex: Lexicon) -> None:
        assert ipa_of(lex, "krebs\n  CYCLE") == "ˈkɹɛbz ˈsaɪkəl"

    @pytest.mark.parametrize("token", ["", "  ", "larynx", "Pharynxes"])
    def test_miss_is_none(self, lex: Lexicon, token: str) -> None:
        assert lex.lookup(token) is None

    def test_ascii_g_and_r_in_entries_become_piper_symbols(self) -> None:
        table = Lexicon({"gauss": "ˈgaʊs", "rho": "ˈroʊ"}, MORPHEMES)
        assert ipa_of(table, "gauss") == "ˈɡaʊs"
        assert ipa_of(table, "rho") == "ˈɹoʊ"

    def test_object_valued_entries(self, data_dir: Path) -> None:
        doc = {"schema": 1, "entries": {"gauss": {"ipa": "ˈɡaʊs", "respelling": "GOWS"}}}
        (data_dir / "pronunciations.json").write_text(json.dumps(doc), encoding="utf-8")
        assert ipa_of(Lexicon.load(data_dir=data_dir), "Gauss") == "ˈɡaʊs"

    def test_bundled_entry_without_ipa_fails_loudly(self, data_dir: Path) -> None:
        doc = {"schema": 1, "entries": {"gauss": {"respelling": "GOWS"}}}
        (data_dir / "pronunciations.json").write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(ValueError, match="gauss"):
            Lexicon.load(data_dir=data_dir)


class TestUserOverrides:
    def test_overrides_argument_wins(self) -> None:
        table = Lexicon({"gauss": "stock"}, MORPHEMES, overrides={"Gauss": "custom"})
        assert ipa_of(table, "gauss") == "custom"

    def test_user_file_wins_and_adds(self, tmp_path: Path, data_dir: Path) -> None:
        user = tmp_path / "user.json"
        user.write_text(json.dumps({"schema": 1, "entries": {"pharynx": "ˈmine", "zzz": "ˈzɪz"}}))
        table = Lexicon.load(user, data_dir=data_dir)
        assert ipa_of(table, "Pharynx") == "ˈmine"
        assert ipa_of(table, "zzz") == "ˈzɪz"
        assert ipa_of(table, "krebs cycle") == "ˈkɹɛbz ˈsaɪkəl"  # untouched entries stay
        assert table.warnings == ()

    def test_user_file_may_be_a_bare_object_with_object_values(
        self, tmp_path: Path, data_dir: Path
    ) -> None:
        user = tmp_path / "user.json"
        user.write_text(json.dumps({"zzz": "ˈzɪz", "yyy": {"ipa": "ˈjɪj", "note": "mine"}}))
        table = Lexicon.load(user, data_dir=data_dir)
        assert ipa_of(table, "zzz") == "ˈzɪz"
        assert ipa_of(table, "yyy") == "ˈjɪj"
        assert table.warnings == ()

    def test_user_ipa_is_made_piper_safe(self, tmp_path: Path, data_dir: Path) -> None:
        user = tmp_path / "user.json"
        user.write_text(json.dumps({"entries": {"gauss": "ˈgaʊs"}}))
        assert ipa_of(Lexicon.load(user, data_dir=data_dir), "gauss") == "ˈɡaʊs"

    def test_missing_user_file_is_silent(self, tmp_path: Path, data_dir: Path) -> None:
        assert Lexicon.load(tmp_path / "nope.json", data_dir=data_dir).warnings == ()

    def test_no_user_file(self, data_dir: Path) -> None:
        assert Lexicon.load(data_dir=data_dir).warnings == ()

    @pytest.mark.parametrize("body", ["{not json", "[1, 2]", '"text"', ""])
    def test_malformed_user_file_is_reported_and_ignored(
        self, tmp_path: Path, data_dir: Path, body: str
    ) -> None:
        user = tmp_path / "user.json"
        user.write_text(body)
        table = Lexicon.load(user, data_dir=data_dir)
        assert len(table.warnings) == 1
        assert "user.json ignored" in table.warnings[0]
        assert ipa_of(table, "pharynx") == "ˈfɑɹɪŋks"  # bundled still works

    def test_bad_entries_are_skipped_one_by_one(self, tmp_path: Path, data_dir: Path) -> None:
        user = tmp_path / "user.json"
        user.write_text(
            json.dumps({"entries": {"good": "ˈɡʊd", "empty": " ", "num": 5, " ": "ˈx"}})
        )
        table = Lexicon.load(user, data_dir=data_dir)
        assert ipa_of(table, "good") == "ˈɡʊd"
        assert ipa_of(table, "empty") is None
        assert table.warnings == (
            "user lexicon user.json: skipped 'empty' (invalid entry)",
            "user lexicon user.json: skipped 'num' (invalid entry)",
            "user lexicon user.json: skipped ' ' (invalid entry)",
        )


class TestIupac:
    def test_isobutanol_systematic_name(self, lex: Lexicon) -> None:
        assert lex.iupac("2-methylpropan-1-ol") == Override(
            "2-methylpropan-1-ol", ISOBUTANOL, "iupac"
        )

    def test_comma_locants_are_separate_words(self, lex: Lexicon) -> None:
        got = lex.iupac("1,2-dichloroethane")
        assert got is not None
        assert got.ipa == "wʌn tu daɪˈklɔɹoʊɛθeɪn"

    def test_first_primary_stays_and_later_ones_drop_to_secondary(self, lex: Lexicon) -> None:
        assert said(lex, "2-methylethyl") == "tu ˈmɛθɪlˌɛθɪl"
        assert said(lex, "methyl ethyl") == "ˈmɛθɪl ˌɛθɪl"

    def test_case_insensitive_and_surface_untouched(self, lex: Lexicon) -> None:
        got = lex.iupac("2-Methylpropan-1-OL")
        assert got == Override("2-Methylpropan-1-OL", ISOBUTANOL, "iupac")

    @pytest.mark.parametrize(
        "variant",
        [
            "2 methylpropan 1 ol",
            "2\u2010methylpropan\u20131\u2011ol",
            "(2-methylpropan)-[1]-ol",
            " 2,methylpropan,1,ol ",
        ],
    )
    def test_any_separator_only_splits_words(self, lex: Lexicon, variant: str) -> None:
        got = lex.iupac(variant)
        assert got is not None
        assert got.ipa == ISOBUTANOL

    def test_longest_match_backs_off_when_it_dead_ends(self, lex: Lexicon) -> None:
        # "propa" would leave a stray "ne"; "prop" + "ane" completes the run.
        got = lex.iupac("propane")
        assert got is not None
        assert got.ipa == "ˈpɹoʊpeɪn"

    def test_dead_ends_are_remembered_so_a_bad_run_fails_fast(self) -> None:
        # Splits of 2 and 3 letters reach the same position many ways; without the memo of
        # failed positions this 61-letter run takes exponential time.
        table = Lexicon({}, {"aa": "x", "aaa": "y"})
        assert table.iupac("aaaaaz") is None
        assert table.iupac("a" * 60 + "z") is None
        assert said(table, "a" * 60) == "ˈ" + "y" * 20

    def test_lone_letters_match_exact_case_and_only_as_whole_tokens(self, lex: Lexicon) -> None:
        assert said(lex, "N,N-dimethyl") == "ɛn ɛn daɪˈmɛθɪl"
        assert said(lex, "N-methyl") == "ɛn ˈmɛθɪl"
        assert said(lex, "n-methyl") == "nɔɹməl ˈmɛθɪl"
        assert said(lex, "(2R)-methyl") == "tu ɑɹ ˈmɛθɪl"
        assert said(lex, "(2r)-methyl") is None  # there is no lowercase r key
        assert said(lex, "methylN") is None  # a letter never matches inside a word
        assert said(lex, "methyln") is None

    @pytest.mark.parametrize("name", ["N", "2R", "2", "n"])
    def test_a_name_needs_a_word_morpheme(self, lex: Lexicon, name: str) -> None:
        assert lex.iupac(name) is None

    def test_known_locant_is_a_whole_digit_token(self, lex: Lexicon) -> None:
        assert said(lex, "10-methyl") == "tɛn ˈmɛθɪl"

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "   ",
            "-",
            "12",  # a number is not a name
            "2-methylfoo-1-ol",  # unknown morpheme
            "2'-methyl",  # prime is not understood
            "100-methyl",  # locant not in the table
            "05-methyl",  # leading zero is not a locant
            "4-methyl",  # 4 is not in this table
            "methyl+",
        ],
    )
    def test_unknown_or_unsupported_is_none(self, lex: Lexicon, name: str) -> None:
        assert lex.iupac(name) is None

    def test_empty_morpheme_table_never_matches(self) -> None:
        assert Lexicon({}, {}).iupac("methyl") is None

    def test_morpheme_ipa_is_made_piper_safe(self) -> None:
        got = Lexicon({}, {"prop": "pɹoʊp", "gol": "gɑl"}).iupac("gol")
        assert got is not None
        assert got.ipa == "ˈɡɑl"  # no kinds known: the first morpheme takes the stress

    def test_speaks_only_the_names_own_morphemes_never_a_trivial_name(self, lex: Lexicon) -> None:
        # R5: "isobutyl alcohol" is in the lexicon, yet the systematic name must not turn into it.
        got = lex.iupac("2-methylpropan-1-ol")
        trivial = lex.lookup("isobutyl alcohol")
        assert got is not None
        assert trivial is not None
        assert got.ipa != trivial.ipa
        assert (got.surface, got.source) == ("2-methylpropan-1-ol", "iupac")


class TestIupacStress:
    """One primary stress per name: a marked morpheme's, else the first stem or substituent's."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("ethanol", "ˈɛθeɪnɑl"),
            ("methane", "ˈmɛθeɪn"),
            ("propan-2-ol", "ˈpɹoʊpeɪn tu ɑl"),
            ("1,2-dichloroethane", "wʌn tu daɪˈklɔɹoʊɛθeɪn"),
            ("chloromethane", "ˈklɔɹoʊmɛθeɪn"),
        ],
    )
    def test_the_named_examples(self, lex: Lexicon, name: str, expected: str) -> None:
        assert said(lex, name) == expected
        assert expected.count("ˈ") == 1

    def test_a_substituent_before_the_stem_takes_the_mark(self, lex: Lexicon) -> None:
        assert said(lex, "azoethane") == "ˈeɪzoʊɛθeɪn"

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("dimeth", "daɪˈmɛθ"),  # a multiplier is skipped
            ("2-ethane", "tu ˈɛθeɪn"),  # so is a locant
            ("R-ethane", "ɑɹ ˈɛθeɪn"),  # and a stereo descriptor
        ],
    )
    def test_only_a_stem_or_substituent_takes_the_first_mark(
        self, lex: Lexicon, name: str, expected: str
    ) -> None:
        assert said(lex, name) == expected

    def test_with_no_stem_or_substituent_the_first_morpheme_takes_it(self, lex: Lexicon) -> None:
        assert said(lex, "diol") == "ˈdaɪɑl"
        assert said(lex, "2-ol") == "ˈtu ɑl"

    def test_a_marked_name_keeps_exactly_one_primary(self, lex: Lexicon) -> None:
        for name in ("chloromethane", "2-methylethyl", "methyl ethyl", "1,2-dichloroethane"):
            assert (said(lex, name) or "").count("ˈ") == 1, name

    def test_without_kinds_the_first_morpheme_takes_it(self) -> None:
        bare = Lexicon({}, {"2": "tu", "eth": "ɛθ", "ane": "eɪn"})
        assert said(bare, "ethane") == "ˈɛθeɪn"
        assert said(bare, "2-ethane") == "ˈtu ɛθeɪn"

    def test_kinds_come_from_the_data_file(self, data_dir: Path) -> None:
        assert said(Lexicon.load(data_dir=data_dir), "2-ethane") == "tu ˈɛθeɪn"


@pytest.fixture(scope="module")
def piper_symbols() -> frozenset[str]:
    if not VOICE_JSON.exists():
        pytest.skip(f"no Piper voice metadata at {VOICE_JSON}")
    return frozenset(json.loads(VOICE_JSON.read_text(encoding="utf-8"))["phoneme_id_map"])


def _entries(name: str) -> dict[str, dict[str, str]]:
    path = ROOT / "cloudyreader" / "data" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


@pytest.fixture(scope="module")
def bundled() -> Lexicon:
    return Lexicon.load()


class TestShippedData:
    @pytest.mark.parametrize("name", ["2-methylpropan-1-ol", "1,2-dichloroethane"])
    def test_brief_iupac_names_are_speakable(self, bundled: Lexicon, name: str) -> None:
        got = bundled.iupac(name)
        assert got is not None
        assert (got.surface, got.source) == (name, "iupac")
        assert got.ipa.count("ˈ") == 1
        assert " " in got.ipa  # locants are separate words

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("ethanol", "ˈɛθeɪnɑl"),
            ("methane", "ˈmɛθeɪn"),
            ("propan-2-ol", "ˈpɹoʊpeɪn tu ɑl"),
            ("1,2-dichloroethane", "wʌn tu daɪˈklɔɹoʊɛθeɪn"),
            ("chloromethane", "ˈklɔɹoʊmɛθeɪn"),
        ],
    )
    def test_stress_policy_on_the_shipped_morphemes(
        self, bundled: Lexicon, name: str, expected: str
    ) -> None:
        got = bundled.iupac(name)
        assert got is not None
        assert got.ipa == expected
        assert got.ipa.count("ˈ") == 1

    def test_every_pronunciation_is_found_by_its_key(self, bundled: Lexicon) -> None:
        for token, entry in _entries("pronunciations").items():
            found = bundled.lookup(token.upper())
            assert found is not None, token
            assert found.ipa == piper_safe(entry["ipa"]), token

    def test_every_symbol_exists_in_the_piper_voice(
        self, bundled: Lexicon, piper_symbols: frozenset[str]
    ) -> None:
        for name in ("pronunciations", "iupac_morphemes"):
            for token, entry in _entries(name).items():
                missing = set(piper_safe(entry["ipa"])) - piper_symbols
                assert not missing, (name, token, sorted(missing))

    def test_iupac_output_symbols_exist_in_the_piper_voice(
        self, bundled: Lexicon, piper_symbols: frozenset[str]
    ) -> None:
        for name in ("2-methylpropan-1-ol", "1,2-dichloroethane", "(2R)-butan-2-ol"):
            got = bundled.iupac(name)
            assert got is not None, name
            assert not set(got.ipa) - piper_symbols, name
