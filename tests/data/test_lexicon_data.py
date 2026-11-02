"""Structure checks for the lexicon JSON files in cloudyreader/data."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "cloudyreader" / "data"
PIPER_VOICE_CONFIG = ROOT / ".data" / "voices" / "en_US-lessac-medium.onnx.json"

EXPECTED_FILES = (
    "elements.json",
    "ions_and_groups.json",
    "iupac_morphemes.json",
    "pronunciations.json",
    "respelling_rules.json",
    "symbols.json",
    "units.json",
)
SPEECH_FIELDS = ("ipa", "spoken", "respelling")
ELEMENT_COUNT = 118
MIN_PRONUNCIATIONS = 300
DATA_FILES = sorted(DATA_DIR.glob("*.json"))


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def entry_list(entries):
    return list(entries.values()) if isinstance(entries, dict) else list(entries)


def bad_speech_value(value, path):
    """Yield the JSON path of every empty or non-string leaf under a speech field."""
    if isinstance(value, str):
        if not value.strip():
            yield path
    elif isinstance(value, list):
        if not value:
            yield path
        for index, item in enumerate(value):
            yield from bad_speech_value(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        if not value:
            yield path
        for key, item in value.items():
            yield from bad_speech_value(item, f"{path}.{key}")
    else:
        yield path


def empty_speech_fields(node, path="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in SPEECH_FIELDS:
                yield from bad_speech_value(value, f"{path}.{key}")
            else:
                yield from empty_speech_fields(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from empty_speech_fields(value, f"{path}[{index}]")


@pytest.fixture(params=DATA_FILES, ids=lambda path: path.name)
def data_file(request):
    return request.param


def test_expected_files_exist():
    missing = [name for name in EXPECTED_FILES if not (DATA_DIR / name).is_file()]
    assert not missing, f"missing data files: {missing}"


def test_file_loads_as_json_object(data_file):
    assert isinstance(load(data_file), dict)


def test_schema_is_1(data_file):
    schema = load(data_file).get("schema")
    assert schema == 1 and not isinstance(schema, bool)


def test_entries_present_and_non_empty(data_file):
    entries = load(data_file).get("entries")
    assert isinstance(entries, dict | list)
    assert entries


def test_no_empty_speech_fields(data_file):
    bad = list(empty_speech_fields(load(data_file)))
    assert not bad, f"empty ipa/spoken/respelling at: {bad[:10]}"


def test_elements_has_118_complete_entries():
    entries = entry_list(load(DATA_DIR / "elements.json")["entries"])
    assert len(entries) == ELEMENT_COUNT
    for entry in entries:
        for field in ("name", "spoken_symbol"):
            assert isinstance(entry.get(field), str) and entry[field].strip(), entry
        assert isinstance(entry.get("atomic_number"), int), entry
    numbers = sorted(entry["atomic_number"] for entry in entries)
    assert numbers == list(range(1, ELEMENT_COUNT + 1))


def test_pronunciations_cover_at_least_300_words():
    entries = load(DATA_DIR / "pronunciations.json")["entries"]
    assert len(entries) >= MIN_PRONUNCIATIONS


def test_pronunciation_entries_are_well_formed():
    entries = load(DATA_DIR / "pronunciations.json")["entries"]
    bad = []
    for word, entry in entries.items():
        respelling, ipa = entry.get("respelling", ""), entry.get("ipa", "")
        # Override contract: no length marks, stressed NURSE is ɜɹ (Piper has no ɝ).
        ok = (
            word == word.lower()
            and " " not in word
            and any(char.isupper() for char in respelling)
            and ipa.count("ˈ") == 1
            and " " not in ipa
            and "ː" not in ipa
            and "ɝ" not in ipa
            and not re.search("ɜ(?!ɹ)", ipa)
        )
        if not ok:
            bad.append(word)
    assert not bad, f"malformed pronunciation entries: {bad[:10]}"


def test_pronunciation_ipa_uses_piper_phonemes():
    if not PIPER_VOICE_CONFIG.is_file():
        pytest.skip("Piper en_US-lessac-medium voice config is not downloaded")
    phonemes = set(load(PIPER_VOICE_CONFIG)["phoneme_id_map"])
    entries = load(DATA_DIR / "pronunciations.json")["entries"]
    bad = {
        word: sorted(set(entry["ipa"]) - phonemes)
        for word, entry in entries.items()
        if set(entry["ipa"]) - phonemes
    }
    assert not bad, f"IPA symbols not in the Piper phoneme map: {list(bad.items())[:10]}"
