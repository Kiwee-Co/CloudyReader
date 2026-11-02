"""ipa_to_misaki: General American IPA (espeak-ng en-us style) -> Kokoro/misaki phonemes."""

import json
import os
from pathlib import Path

import pytest

from cloudyreader.engines.misaki_ipa import MODEL_VOCAB, ipa_to_misaki

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = Path(
    os.environ.get(
        "CLOUDYREADER_KOKORO_SNAPSHOT",
        ROOT
        / ".cache/spike-kokoro/hf/hub/models--mlx-community--Kokoro-82M-bf16/snapshots"
        / "a71e4d38b236d968966a2002c4c895dbd12b1c3c",
    )
)


@pytest.mark.parametrize(
    ("ipa", "expected"),
    [
        ("ˈfæɹɪŋks", "fˈæɹɪŋks"),  # FAR-ingks: stress moves to just before the vowel
        ("ɪˈsɑfəgəs", "ɪsˈɑfəɡəs"),  # ASCII g becomes U+0261; the model drops ASCII g
        ("ˈtreɪkiə", "tɹˈAkiə"),
        ("ˌmoʊhoʊˈroʊvətʃɪtʃ", "mˌOhOɹˈOvəʧɪʧ"),
        ("ˈnaɪtrədʒən", "nˈItɹəʤən"),
        ("ˈaʊ", "ˈW"),
        ("ˈbɔɪl", "bˈYl"),
        ("mɝ", "mɜɹ"),
        ("ˈwɔɾɚ", "wˈɔTəɹ"),
        ("ˈfɑː.ðɚ", "fˈɑðəɹ"),  # length mark and syllable dot are dropped
        ("ˈtreɪ.ki.ə", "tɹˈAkiə"),
    ],
)
def test_maps_general_american_ipa(ipa: str, expected: str) -> None:
    assert ipa_to_misaki(ipa) == (expected, [])


@pytest.mark.parametrize(
    ("ipa", "expected"),
    [
        ("bˈɜːd", "bˈɜɹd"),
        ("ɐbˈaʊt", "əbˈWt"),
        ("mˈɔːɹ", "mˈɔɹ"),
        ("fˈaɪɚ", "fˈIəɹ"),
        ("bˈʌʔn̩", "bˈʌʔᵊn"),  # syllabic n
        ("bˈɑːx", "bˈɑk"),
        ("fˈɑːɹɹɪŋks", "fˈɑɹɪŋks"),  # espeak doubles the r
        ("fˌoʊɾoʊsˈɪnθəsˌɪs", "fˌOTOsˈɪnθəsˌɪs"),
        ("t͡ʃˈɜːt͡ʃ", "ʧˈɜɹʧ"),  # tie bars
        ("dʒˈʌdʒ", "ʤˈʌʤ"),
        ("aɪdˈɪə", "Idˈiə"),
    ],
)
def test_maps_espeak_en_us_output(ipa: str, expected: str) -> None:
    assert ipa_to_misaki(ipa) == (expected, [])


@pytest.mark.parametrize(
    ("ipa", "expected"),
    [
        ("ˈfoɹ", "fˈɔɹ"),
        ("ˈkloɹin", "klˈɔɹin"),
        ("ˈnitɹo", "nˈitɹO"),
        ("ðeɹ", "ðɛɹ"),
        ("ˈke", "kˈA"),
        ("ˈfor", "fˈɔɹ"),  # ASCII r
    ],
)
def test_maps_bare_o_and_e(ipa: str, expected: str) -> None:
    assert ipa_to_misaki(ipa) == (expected, [])


def test_multi_word_keeps_single_spaces() -> None:
    assert ipa_to_misaki("  ˈhɑɹdi   ˈwaɪnbɝɡ ") == ("hˈɑɹdi wˈInbɜɹɡ", [])


def test_rejects_symbols_outside_model_vocab() -> None:
    assert ipa_to_misaki("ˈfæɹ-ɪŋks☃") == ("fˈæɹɪŋks", ["-", "☃"])


def test_rejects_pause_punctuation_inside_ipa() -> None:
    # Punctuation is in the model vocab but would make Kokoro pause mid-word.
    assert ipa_to_misaki("ˈfæɹ,ɪŋks!?") == ("fˈæɹɪŋks", [",", "!", "?"])


def test_reports_each_rejected_symbol_once() -> None:
    assert ipa_to_misaki("ɵɵˈkɵt")[1] == ["ɵ"]


def test_empty_input() -> None:
    assert ipa_to_misaki("") == ("", [])
    assert ipa_to_misaki("-") == ("", ["-"])


@pytest.mark.parametrize("ipa", ["mˌOhOɹˈOvəʧɪʧ", "tɹˈAkiə", "wˈɔTəɹ", "bˈʌʔᵊn"])
def test_idempotent_on_misaki_phonemes(ipa: str) -> None:
    assert ipa_to_misaki(ipa) == (ipa, [])


@pytest.mark.parametrize(
    "ipa", ["ˈfɑː.ðɚ", "t͡ʃˈɜːt͡ʃ", "bˈʌʔn̩", "ˌmoʊhoʊˈroʊvətʃɪtʃ", "ˈɡ r x ç ɬ ɫ ɐ ɾ õ"]
)
def test_output_only_uses_model_vocab(ipa: str) -> None:
    ps, _ = ipa_to_misaki(ipa)
    assert set(ps) <= MODEL_VOCAB


def test_model_vocab_has_114_symbols() -> None:
    assert len(MODEL_VOCAB) == 114
    assert "g" not in MODEL_VOCAB and "ɡ" in MODEL_VOCAB


@pytest.mark.skipif(not (SNAPSHOT / "config.json").is_file(), reason="Kokoro snapshot not present")
def test_model_vocab_matches_pinned_config() -> None:
    config = json.loads((SNAPSHOT / "config.json").read_text(encoding="utf-8"))
    assert set(config["vocab"]) == MODEL_VOCAB
