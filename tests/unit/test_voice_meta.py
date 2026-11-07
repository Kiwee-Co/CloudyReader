"""voice_meta: gender and accent per voice (Kokoro id letters, the pinned Piper table)."""

from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import sys
import typing
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from cloudyreader import engine_catalog, voice_meta
from cloudyreader.engines import chatterbox_turbo, kokoro, qwen3_tts
from cloudyreader.engines.chatterbox_turbo import ChatterboxTurboEngine
from cloudyreader.engines.kokoro import VOICE_GRADES, KokoroEngine
from cloudyreader.engines.qwen3_tts import Qwen3TtsEngine
from cloudyreader.models import VoiceInfo
from cloudyreader.voice_meta import (
    ENGINE_ORDER,
    ENGINE_TITLES,
    NOT_DOWNLOADED,
    PIPER_GENDERS,
    ROW_REASON_MAX,
    Gender,
    VoiceProfile,
    accent_of,
    display_name,
    engine_title,
    precision_of,
    profile_of,
    row_reason,
    spoken_label,
    unique_labels,
    voice_label,
    voice_phrase,
)
from cloudyreader.voices import scan_installed

ROOT = Path(__file__).resolve().parents[2]

PINNED_PIPER = {
    "en_US-lessac-medium": VoiceProfile("female", "en-US"),
    "en_US-amy-medium": VoiceProfile("female", "en-US"),
    "en_US-ryan-medium": VoiceProfile("male", "en-US"),
    "en_GB-alan-medium": VoiceProfile("male", "en-GB"),
    "en_GB-jenny_dioco-medium": VoiceProfile("female", "en-GB"),
}


def voice(key: str, language: str = "en-US") -> VoiceInfo:
    return VoiceInfo(key, key.partition(":")[0], key, language, "medium", 1, True)


def piper_language(vid: str) -> str:
    return vid.split("-")[0].replace("_", "-")  # en_US-lessac-medium -> en-US, as voices.py does


def kokoro_language(vid: str) -> str:
    return "en-US" if vid[0] == "a" else "en-GB"  # KokoroEngine: a = American, b = British


# --- VoiceProfile and the Piper table ---------------------------------------------------------


def test_gender_is_female_or_male():
    assert typing.get_args(Gender) == ("female", "male")


def test_voice_profile_is_frozen_with_gender_then_accent():
    profile = VoiceProfile("female", "en-US")
    assert [f.name for f in dataclasses.fields(VoiceProfile)] == ["gender", "accent"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.gender = "male"


def test_piper_genders_cover_the_five_pinned_voices():
    assert dict(PIPER_GENDERS) == {vid: p.gender for vid, p in PINNED_PIPER.items()}


def test_piper_genders_are_read_only():
    with pytest.raises(TypeError):
        PIPER_GENDERS["en_US-joe-medium"] = "male"


def test_every_pinned_piper_voice_in_the_lock_has_a_gender():
    # Drift guard: a voice added to assets.lock.json without a gender would never rotate.
    lock = json.loads((ROOT / "assets.lock.json").read_text(encoding="utf-8"))
    ids = {
        asset["name"].removesuffix(".json").removesuffix(".onnx")
        for asset in lock["assets"]
        if asset["group"] == "voices"
    }
    assert ids, "no voices group in assets.lock.json"
    assert sorted(ids - PIPER_GENDERS.keys()) == []


# --- profile_of ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("vid", "expected"), PINNED_PIPER.items())
def test_pinned_piper_voice_profiles(vid, expected):
    assert profile_of(voice(f"piper:{vid}", piper_language(vid))) == expected


def test_piper_profiles_fit_the_keys_the_installed_scan_gives(tmp_path):
    for vid in PINNED_PIPER:
        (tmp_path / f"{vid}.onnx").write_bytes(b"model")
        config = {"language": {"code": vid.split("-")[0]}, "num_speakers": 1}
        (tmp_path / f"{vid}.onnx.json").write_text(json.dumps(config), encoding="utf-8")

    scanned = {v.key: profile_of(v) for v in scan_installed(tmp_path)}

    assert scanned == {f"piper:{vid}": profile for vid, profile in PINNED_PIPER.items()}


@pytest.mark.parametrize("vid", sorted(VOICE_GRADES))
def test_every_graded_kokoro_voice_has_a_profile(vid):
    expected = VoiceProfile({"f": "female", "m": "male"}[vid[1]], kokoro_language(vid))
    assert profile_of(voice(f"kokoro:{vid}", kokoro_language(vid))) == expected


def test_kokoro_profiles_agree_with_the_engine_voice_list(tmp_path, monkeypatch):
    # The engine names each voice "Heart (female)" and derives its language from the id.
    monkeypatch.setattr(kokoro, "_supported_platform", lambda: True)
    listed = KokoroEngine(tmp_path, all_voices=True).voices()

    profiles = [(v, profile_of(v)) for v in listed]

    assert len(profiles) == len(VOICE_GRADES)
    assert all(p is not None and v.name.endswith(f"({p.gender})") for v, p in profiles)
    assert all(p is not None and p.accent == v.language for v, p in profiles)


@pytest.mark.parametrize(
    "info",
    [
        voice("piper:en_US-libritts-high"),  # a catalog voice outside the table
        voice("piper:de_DE-thorsten-medium", "de-DE"),
        voice("piper:en_US-lessac-medium", "de-DE"),  # known key, non-English language
        voice("piper:"),
        voice("kokoro:af_heart", "ja-JP"),  # valid id, non-English language
        voice("kokoro:af_heart", "english"),
        voice("kokoro:jf_alpha", "ja-JP"),  # Japanese Kokoro voice
        voice("kokoro:zf_xiaobei"),  # Mandarin id with an English language
        voice("kokoro:ax_heart"),
        voice("kokoro:af_"),
        voice("kokoro:AF_HEART"),
        voice("kokoro:af_heart.safetensors"),
        voice("kokoro:"),
        voice("en_US-lessac-medium"),  # no engine prefix
        voice("espeak:en-us"),
        voice(""),
    ],
    ids=lambda info: f"{info.key}|{info.language}",
)
def test_unknown_or_non_english_voices_have_no_profile(info):
    assert profile_of(info) is None


@pytest.mark.parametrize(
    "odd",
    [
        None,
        "kokoro:af_heart",
        object(),
        VoiceInfo(None, "kokoro", "Heart", "en-US", "A", 1, True),
        VoiceInfo("kokoro:af_heart", "kokoro", "Heart", None, "A", 1, True),
    ],
)
def test_odd_input_gives_none_instead_of_raising(odd):
    assert profile_of(odd) is None


# --- Voice menu text: one label per voice --------------------------------------------------------

LABEL = re.compile(
    r"(?P<name>[^()·—]+?)(?: \((?P<detail>[^()]+)\))?"
    r" · (?P<engine>Kokoro|Chatterbox Turbo|Qwen3-TTS|Piper|macOS)"
    r" · (?P<precision>[^·—]+?)(?: — (?P<reason>.+))?"
)
GRADE = re.compile(r"(?<!\w)[A-DF][+-]?(?!\w)")  # a standalone grade letter: A, C+, F-


def make(
    key: str,
    name: str,
    language: str,
    quality: str,
    precision: str = "",
    *,
    installed: bool = True,
    reason: str = "",
) -> VoiceInfo:
    engine = key.partition(":")[0]
    return VoiceInfo(key, engine, name, language, quality, 1, installed, None, reason, precision)


HEART = make("kokoro:af_heart", "Heart (female)", "en-US", "A", "bf16")
EMMA = make("kokoro:bf_emma", "Emma (female)", "en-GB", "B-", "bf16")
MICHAEL = make("kokoro:am_michael", "Michael (male)", "en-US", "C+", "bf16", installed=False)
BUILTIN = make(
    "chatterbox_turbo:builtin",
    "Chatterbox Turbo (built-in)",
    "en",
    "4-bit",
    "4-bit",
    installed=False,
    reason="not downloaded yet",
)
QWEN_RYAN = make("qwen3_tts:ryan", "Ryan (male)", "en", "8-bit", "8-bit")
AIDEN = make("qwen3_tts:aiden", "Aiden (male)", "en-US", "8-bit", "8-bit")
LESSAC = make("piper:en_US-lessac-medium", "lessac", "en-US", "medium", "medium")
PIPER_RYAN = make("piper:en_US-ryan-medium", "ryan", "en-US", "medium", "medium")
JENNY = make("piper:en_GB-jenny_dioco-medium", "jenny_dioco", "en-GB", "medium", "medium")
LIBRITTS = make("piper:en_US-libritts-high", "libritts", "en-US", "high", "high")

LABELS = [
    (HEART, "Heart (US, female) · Kokoro · bf16"),
    (EMMA, "Emma (UK, female) · Kokoro · bf16"),
    (MICHAEL, "Michael (US, male) · Kokoro · bf16 — not downloaded yet"),
    (BUILTIN, "Built-in · Chatterbox Turbo · 4-bit — not downloaded yet"),
    (QWEN_RYAN, "Ryan (male) · Qwen3-TTS · 8-bit"),  # language "en": no region, so no accent
    (AIDEN, "Aiden (US, male) · Qwen3-TTS · 8-bit"),
    (LESSAC, "Lessac (US, female) · Piper · medium"),
    (PIPER_RYAN, "Ryan (US, male) · Piper · medium"),
    (JENNY, "Jenny Dioco (UK, female) · Piper · medium"),
    (LIBRITTS, "Libritts (US) · Piper · high"),  # no gender table row: none shown
]


@pytest.fixture
def macos_genders(monkeypatch):
    """The macOS gender rows belong to the mac-tts lane; the labels need only the lookup."""
    rows = MappingProxyType({"samantha": "female", "daniel": "male"})
    table = MappingProxyType({**voice_meta.ENGINE_GENDERS, "macos": rows})
    monkeypatch.setattr(voice_meta, "ENGINE_GENDERS", table)


@pytest.fixture
def real_voices(tmp_path, monkeypatch) -> list[VoiceInfo]:
    """Every engine's own rows, built by its own code and without loading a model."""
    monkeypatch.setattr(kokoro, "_supported_platform", lambda: True)
    rows = KokoroEngine(tmp_path / "kokoro", all_voices=True).voices()  # files missing: dimmed
    folder = tmp_path / "piper"
    folder.mkdir()
    for vid in PINNED_PIPER:
        (folder / f"{vid}.onnx").write_bytes(b"model")
        config = {"language": {"code": vid.split("-")[0]}, "audio": {"quality": "medium"}}
        (folder / f"{vid}.onnx.json").write_text(json.dumps(config), encoding="utf-8")
    rows += scan_installed(folder)
    engine = SimpleNamespace(model_dir=tmp_path / "models")
    rows += [Qwen3TtsEngine._voice(engine, vid, installed=True) for vid in qwen3_tts.VOICES]
    rows.append(ChatterboxTurboEngine._voice(engine, installed=True))
    return rows


def test_every_real_voice_has_a_precision_and_the_label_format(real_voices):
    assert len(real_voices) == 28 + 5 + 2 + 1
    for info in real_voices:
        for shown in (info, dataclasses.replace(info, installed=False, reason="")):
            parts = LABEL.fullmatch(voice_label(shown))
            assert parts, voice_label(shown)
            assert parts["engine"] == engine_title(info.engine)
            assert parts["precision"] == info.precision != ""


def test_labels_are_unique_over_every_engines_real_voices(real_voices):
    labels = [voice_label(info) for info in real_voices]

    assert len(set(labels)) == len(labels)
    assert list(unique_labels(real_voices).values()) == labels  # no clash: no id appended


def test_no_visible_label_holds_a_grade_letter(real_voices):
    for info in real_voices:
        for shown in (info, dataclasses.replace(info, precision="")):  # even without a precision
            assert not GRADE.search(voice_label(shown)), voice_label(shown)
            assert not GRADE.search(spoken_label(shown)), spoken_label(shown)


def test_only_kokoro_rows_carry_the_grade_and_only_as_the_order_s_input(real_voices):
    graded = {info.key: info.quality for info in real_voices if info.engine == "kokoro"}

    assert graded["kokoro:af_heart"] == "A"
    assert all(
        precision_of(info) != info.quality for info in real_voices if info.engine == "kokoro"
    )


@pytest.mark.parametrize(("info", "label"), LABELS, ids=[i.key for i, _ in LABELS])
def test_label_examples(info, label):
    assert voice_label(info) == label


def test_macos_labels_carry_the_tier_alone(macos_genders):
    samantha = make("macos:samantha", "Samantha", "en-US", "Enhanced", "Enhanced")
    daniel = make("macos:daniel", "Daniel", "en-GB", "Premium", "Premium")
    fiona = make("macos:fiona", "Fiona", "en-scotland", "Standard", "Standard")
    zed = make("macos:zed", "Zed", "en", "Standard", "Standard")

    assert voice_label(samantha) == "Samantha (US, female) · macOS · Enhanced"
    assert voice_label(daniel) == "Daniel (UK, male) · macOS · Premium"
    assert voice_label(fiona) == "Fiona (Scotland) · macOS · Standard"
    assert voice_label(zed) == "Zed · macOS · Standard"
    assert LABEL.fullmatch(voice_label(samantha))


def test_a_voice_without_precision_drops_the_field_and_never_shows_the_grade():
    no_precision = dataclasses.replace(HEART, precision="")

    assert voice_label(no_precision) == "Heart (US, female) · Kokoro"
    assert precision_of(no_precision) == ""
    assert precision_of(dataclasses.replace(LESSAC, precision="")) == "medium"  # a tier is no grade
    assert precision_of(make("macos:x", "X", "en-US", "Enhanced")) == "Enhanced"


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en-US", ("US", "American")),
        ("en_US", ("US", "American")),
        ("en-GB", ("UK", "British")),
        ("en_GB", ("UK", "British")),
        ("en-AU", ("AU", "Australian")),
        ("en-CA", ("CA", "Canadian")),
        ("en-IE", ("IE", "Irish")),
        ("en-IN", ("IN", "Indian")),
        ("en-NZ", ("NZ", "New Zealand")),
        ("en-ZA", ("ZA", "South African")),
        ("en-scotland", ("Scotland", "Scottish")),
        ("en-SG", ("SG", "SG")),  # a region nobody listed shows its own code
        ("de-DE", ("DE", "DE")),
        ("en", None),  # a bare language is no accent: never a guess
        ("", None),
        ("english", None),
    ],
)
def test_accent_of(language, expected):
    assert accent_of(language) == expected


@pytest.mark.parametrize(
    ("info", "name"),
    [
        (HEART, "Heart"),
        (QWEN_RYAN, "Ryan"),
        (dataclasses.replace(AIDEN, name="Aiden (Male)"), "Aiden"),
        (LESSAC, "Lessac"),
        (JENNY, "Jenny Dioco"),
        (dataclasses.replace(LIBRITTS, name="LibriTTS"), "LibriTTS"),  # mixed case stays
        (BUILTIN, "Built-in"),  # the engine's only voice, named after the engine
        (dataclasses.replace(BUILTIN, name="Chatterbox Turbo"), "Chatterbox Turbo"),
        (dataclasses.replace(LESSAC, name="Piperade"), "Piperade"),  # not the engine's echo
        (dataclasses.replace(LESSAC, name="piperade"), "Piperade"),
    ],
)
def test_display_name(info, name):
    assert display_name(info) == name


@pytest.mark.parametrize(
    ("reason", "shown"),
    [
        ("", NOT_DOWNLOADED),
        ("not downloaded yet", "not downloaded yet"),
        ("x" * ROW_REASON_MAX, "x" * ROW_REASON_MAX),
        ("offline: not downloaded", "offline: not downloaded"),
        ("not enough disk space: needs 2.1 GB, 1.5 GB free", "not enough disk space"),
        ("damaged: SHA-256 mismatch for model.safetensors", "damaged"),
        ("a" * 40, "a" * (ROW_REASON_MAX - 1) + "…"),
        ("b" * 40 + ": detail", "b" * (ROW_REASON_MAX - 1) + "…"),
    ],
)
def test_row_reason(reason, shown):
    assert row_reason(dataclasses.replace(MICHAEL, reason=reason)) == shown
    assert len(shown) <= ROW_REASON_MAX


def test_a_dimmed_label_ends_with_its_short_reason():
    info = dataclasses.replace(BUILTIN, reason="not enough disk space: needs 2.1 GB, 1.5 GB free")

    assert voice_label(info).endswith(" — not enough disk space")


def test_unique_labels_add_the_id_after_a_clash_only():
    one = make("piper:xx_US-a-medium", "a", "en-US", "medium", "medium")
    two = make(
        "piper:yy_US-a-medium", "a", "en-US", "medium", "medium"
    )  # same label, no gender row

    labels = unique_labels([one, two, HEART])

    assert labels["kokoro:af_heart"] == "Heart (US, female) · Kokoro · bf16"
    assert labels[one.key] == "A (US) · Piper · medium [xx_US-a-medium]"
    assert labels[two.key] == "A (US) · Piper · medium [yy_US-a-medium]"
    assert len(set(labels.values())) == 3


@pytest.mark.parametrize(
    ("info", "spoken"),
    [
        (HEART, "Heart, American English, female. Kokoro, bf16."),
        (EMMA, "Emma, British English, female. Kokoro, bf16."),
        (QWEN_RYAN, "Ryan, male. Qwen3-TTS, 8-bit."),
        (LIBRITTS, "Libritts, American English. Piper, high."),
        (BUILTIN, "Built-in. Chatterbox Turbo, 4-bit. Not available: not downloaded yet."),
        (
            MICHAEL,
            "Michael, American English, male. Kokoro, bf16. Not available: not downloaded yet.",
        ),
    ],
)
def test_spoken_label(info, spoken):
    assert spoken_label(info) == spoken


@pytest.mark.parametrize(
    ("info", "phrase"),
    [
        (HEART, "Heart (female, Kokoro)"),
        (QWEN_RYAN, "Ryan (male, Qwen3-TTS)"),
        (PIPER_RYAN, "Ryan (male, Piper)"),  # two Ryans: the engine tells them apart
        (LIBRITTS, "Libritts (Piper)"),
        (BUILTIN, "Chatterbox Turbo"),
    ],
)
def test_voice_phrase_is_name_gender_and_engine(info, phrase):
    assert voice_phrase(info) == phrase


def test_engine_titles_agree_with_the_engine_catalog_and_name_every_engine():
    for engine, title in engine_catalog.TITLES.items():
        assert ENGINE_TITLES.get(engine, title) == title  # "voices" is Piper's lock group
    assert ENGINE_TITLES["piper"] == "Piper"
    assert ENGINE_TITLES["macos"] == "macOS"
    assert set(ENGINE_ORDER) <= set(ENGINE_TITLES)
    assert engine_title("espeak") == "Espeak"


def test_the_engine_modules_agree_with_the_table_they_are_labelled_from():
    assert chatterbox_turbo.TITLE == ENGINE_TITLES["chatterbox_turbo"]
    assert qwen3_tts.TITLE == ENGINE_TITLES["qwen3_tts"]


def test_importing_voice_meta_loads_only_the_stdlib():
    # The GUI imports it at start-up: no Qt, httpx, engines, or pipeline.
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "before = set(sys.modules)\n"
        "import cloudyreader.voice_meta\n"
        "new = {name.partition('.')[0] for name in set(sys.modules) - before}\n"
        "foreign = sorted(new - set(sys.stdlib_module_names) - {'cloudyreader'})\n"
        "assert not foreign, foreign\n"
        "ours = {name for name in sys.modules if name.startswith('cloudyreader.')}\n"
        "assert ours <= {'cloudyreader.voice_meta', 'cloudyreader.models'}, sorted(ours)\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
