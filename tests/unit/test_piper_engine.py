"""PiperEngine: voice scan, override rendering, WAV assembly (fake voice), one real-voice check."""

from __future__ import annotations

import importlib.metadata
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cloudyreader.engines import piper as piper_module
from cloudyreader.engines.piper import PiperEngine, to_piper_layout
from cloudyreader.models import Override, RenderOptions, Segment, SpokenScript, VoiceInfo

RATE = 22050
SAMPLES_PER_CHAR = 10
AMPLITUDE = 1000
# Deliberately lacks ASCII "g" (the map holds U+0261) and "ɝ" (U+025D), like real Piper voices.
SYMBOLS = " ,.!?:;ˈˌːabdefhiklmnoprstuvwzæɑɔəɛɪɹɡŋʃʊʌθðɚ"
PHARYNX = Override("Pharynx", "fˈɑːɹɪŋks", "respelling")
PHARYNX_IPA = ("fˈɑːɹɪŋks", "lexicon")


class FakeChunk:
    def __init__(self, sample_rate: int, samples: np.ndarray) -> None:
        self.sample_rate = sample_rate
        self.audio_int16_bytes = samples.tobytes()


class FakePiperVoice:
    """Stands in for piper.PiperVoice: one constant-amplitude chunk per sentence."""

    def __init__(self, rate: int = RATE, delay_s: float = 0.0) -> None:
        self.rate = rate
        self.delay_s = delay_s
        self.calls: list[tuple[str, Any]] = []
        self.active = 0
        self.max_active = 0
        self._guard = threading.Lock()

    def synthesize(self, text: str, syn_config: Any = None):
        with self._guard:
            self.calls.append((text, syn_config))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay_s)
            for sentence in (s.strip() for s in text.split(".")):
                if sentence:
                    samples = np.full(len(sentence) * SAMPLES_PER_CHAR, AMPLITUDE, dtype=np.int16)
                    yield FakeChunk(self.rate, samples)
        finally:
            with self._guard:
                self.active -= 1


def write_voice(
    voices_dir: Path,
    name: str = "en_US-fake-medium",
    *,
    num_speakers: int = 1,
    symbols: str = SYMBOLS,
    length_scale: float = 1.0,
) -> VoiceInfo:
    model = voices_dir / f"{name}.onnx"
    model.write_bytes(b"not a real model")
    config = {
        "audio": {"sample_rate": RATE, "quality": "medium"},
        "espeak": {"voice": "en-us"},
        "inference": {"noise_scale": 0.667, "length_scale": length_scale, "noise_w": 0.8},
        "phoneme_type": "espeak",
        "phoneme_id_map": {s: [i] for i, s in enumerate(symbols)},
        "num_symbols": len(symbols),
        "num_speakers": num_speakers,
        "speaker_id_map": {},
        "language": {"code": "en_US"},
    }
    (voices_dir / f"{name}.onnx.json").write_text(json.dumps(config), encoding="utf-8")
    return VoiceInfo(f"piper:{name}", "piper", "fake", "en-US", "medium", num_speakers, True, model)


def read_wav(path: Path) -> tuple[wave._wave_params, np.ndarray]:
    with wave.open(str(path), "rb") as wav:
        params = wav.getparams()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    return params, samples


def script_of(*segments: Segment) -> SpokenScript:
    return SpokenScript(tuple(segments))


@pytest.fixture
def voices_dir(tmp_path: Path) -> Path:
    path = tmp_path / "voices"
    path.mkdir()
    return path


@pytest.fixture
def voice(voices_dir: Path) -> VoiceInfo:
    return write_voice(voices_dir)


@pytest.fixture
def fake() -> FakePiperVoice:
    return FakePiperVoice()


@pytest.fixture
def engine(voices_dir: Path, fake: FakePiperVoice) -> PiperEngine:
    return PiperEngine(voices_dir, loader=lambda model, config: fake)


# --- identity and voices ---------------------------------------------------------------------


def test_engine_key_and_version(engine):
    assert engine.key == "piper"
    assert engine.version == f"piper-tts-{importlib.metadata.version('piper-tts')}+r5"


def test_available_when_piper_is_importable(engine, monkeypatch):
    assert engine.available() is True

    monkeypatch.setattr(piper_module, "_piper_installed", lambda: False)

    assert engine.available() is False


def test_voices_scans_the_voices_dir(voices_dir, engine):
    write_voice(voices_dir, "en_US-fake-medium", num_speakers=1)
    write_voice(voices_dir, "en_GB-multi-high", num_speakers=4)
    (voices_dir / "en_US-orphan-medium.onnx").write_bytes(b"x")  # no config

    found = engine.voices()

    assert [(v.key, v.engine, v.num_speakers, v.installed) for v in found] == [
        ("piper:en_GB-multi-high", "piper", 4, True),
        ("piper:en_US-fake-medium", "piper", 1, True),
    ]
    assert found[1].path == voices_dir / "en_US-fake-medium.onnx"


def test_voice_version_fingerprints_the_model_size_and_the_config(engine, voice):
    first = engine.voice_version(voice)
    assert first == engine.voice_version(voice)

    config = voice.path.with_name(voice.path.name + ".json")
    config.write_text(config.read_text(encoding="utf-8") + " ", encoding="utf-8")
    after_config_edit = engine.voice_version(voice)
    voice.path.write_bytes(b"a retrained, longer model body")

    assert len({first, after_config_edit, engine.voice_version(voice)}) == 3


def test_voice_version_differs_between_voices_with_different_files(voices_dir, engine, voice):
    other = write_voice(voices_dir, "en_US-other-medium", length_scale=1.3)

    assert engine.voice_version(other) != engine.voice_version(voice)


def test_voice_version_of_a_missing_voice_is_a_stable_marker_not_an_error(engine):
    ghost = VoiceInfo("piper:ghost", "piper", "ghost", "en-US", "medium", 1, False, None)

    assert engine.voice_version(ghost) == engine.voice_version(ghost) == "missing"


def test_last_warnings_hold_the_warnings_of_the_latest_synthesis(engine, voice, tmp_path):
    dirty = script_of(seg("Her answer.", Override("Her", "hɝ", "lexicon")))
    assert engine.last_warnings == []

    engine.synthesize(dirty, voice, RenderOptions(), tmp_path / "a.wav")
    after_dirty = engine.last_warnings
    engine.synthesize(script_of(seg("Clean.")), voice, RenderOptions(), tmp_path / "b.wav")

    assert after_dirty == list(engine.script_warnings(dirty, voice)) and len(after_dirty) == 1
    assert engine.last_warnings == []


def test_last_warnings_are_cleared_when_a_synthesis_is_rejected(engine, voice, tmp_path):
    dirty = script_of(seg("Her answer.", Override("Her", "hɝ", "lexicon")))
    engine.synthesize(dirty, voice, RenderOptions(), tmp_path / "a.wav")

    with pytest.raises(ValueError, match="speed"):
        engine.synthesize(dirty, voice, RenderOptions(speed=0), tmp_path / "b.wav")

    assert engine.last_warnings == []


def test_last_warnings_are_a_copy_and_belong_to_the_calling_thread(engine, voice, tmp_path):
    dirty = script_of(seg("Her answer.", Override("Her", "hɝ", "lexicon")))
    engine.synthesize(dirty, voice, RenderOptions(), tmp_path / "a.wav")
    engine.last_warnings.append("tampered")
    seen: list[list[str]] = []

    thread = threading.Thread(target=lambda: seen.append(engine.last_warnings))
    thread.start()
    thread.join()

    assert len(engine.last_warnings) == 1 and "tampered" not in engine.last_warnings
    assert seen == [[]]  # another thread's synthesis never shows up here


def test_importing_the_engine_modules_loads_neither_piper_nor_onnxruntime():
    # Kokoro's lean venv has no piper, and the GUI must start without loading onnxruntime.
    root = Path(__file__).resolve().parents[2]
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        "for name in ('cloudyreader.engines', 'cloudyreader.engines.piper',\n"
        "             'cloudyreader.voices', 'cloudyreader.tts', 'cloudyreader.audio'):\n"
        "    __import__(name)\n"
        "    loaded = [m for m in ('piper', 'onnxruntime') if m in sys.modules]\n"
        "    assert not loaded, (name, loaded)\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


# --- to_piper_layout -------------------------------------------------------------------------

# (word, neutral compact IPA as the lexicon writes it, the layout espeak itself gives the word)
ESPEAK_WORDS = [
    ("hot", "ˈhɑt", "hˈɑːt"),
    ("esophagus", "ɪˈsɑfəɡəs", "ɪsˈɑːfəɡəs"),
    ("word", "ˈwɜɹd", "wˈɜːd"),
    ("bird", "ˈbɜɹd", "bˈɜːd"),
    ("nurse", "ˈnɜɹs", "nˈɜːs"),
    ("circuit", "ˈsɜɹkɪt", "sˈɜːkɪt"),
    ("church", "ˈtʃɜɹtʃ", "tʃˈɜːtʃ"),
    ("hurry", "ˈhɜɹi", "hˈɜːɹi"),
    ("earth", "ˈɜɹθ", "ˈɜːθ"),
    ("urge", "ˈɜɹdʒ", "ˈɜːdʒ"),
    ("better", "ˈbɛɾɚ", "bˈɛɾɚ"),
    ("more", "ˈmɔɹ", "mˈɔːɹ"),
    ("north", "ˈnɔɹθ", "nˈɔːɹθ"),
    ("quartz", "ˈkwɔɹts", "kwˈɔːɹts"),
    ("all", "ˈɔl", "ˈɔːl"),
    ("awe", "ˈɔ", "ˈɔː"),
    ("poison", "ˈpɔɪzən", "pˈɔɪzən"),
    ("autograph", "ˈɔɾəˌɡɹæf", "ˈɔːɾəɡɹˌæf"),
    ("art", "ˈɑɹt", "ˈɑːɹt"),
    ("car", "ˈkɑɹ", "kˈɑːɹ"),
    ("shark", "ˈʃɑɹk", "ʃˈɑːɹk"),
    ("Martian", "ˈmɑɹʃən", "mˈɑːɹʃən"),
    ("see", "ˈsi", "sˈiː"),
    ("eat", "ˈit", "ˈiːt"),
    ("three", "ˈθɹi", "θɹˈiː"),
    ("sheep", "ˈʃip", "ʃˈiːp"),
    ("machine", "məˈʃin", "məʃˈiːn"),
    ("create", "kɹiˈeɪt", "kɹiːˈeɪt"),
    ("two", "ˈtu", "tˈuː"),
    ("pool", "ˈpul", "pˈuːl"),
    ("ooze", "ˈuz", "ˈuːz"),
    ("unique", "juˈnik", "juːnˈiːk"),
    ("continue", "kənˈtɪnju", "kəntˈɪnjuː"),
    ("butane", "ˈbjuteɪn", "bjˈuːteɪn"),
    ("happy", "ˈhæpi", "hˈæpi"),
    ("city", "ˈsɪɾi", "sˈɪɾi"),
    ("radium", "ˈɹeɪdiəm", "ɹˈeɪdiəm"),
    ("fermion", "ˈfɜɹmiən", "fˈɜːmiən"),
    ("idea", "aɪˈdiə", "aɪdˈiə"),
    ("area", "ˈɛɹiə", "ˈɛɹiə"),
    ("methane", "ˈmɛθeɪn", "mˈɛθeɪn"),
    ("propyl", "ˈpɹoʊpəl", "pɹˈoʊpəl"),
    ("strength", "ˈstɹɛŋθ", "stɹˈɛŋθ"),
    ("acetaldehyde", "ˌæsɪˈtældɪˌhaɪd", "ˌæsɪtˈældɪhˌaɪd"),
]
# Layout-only pairs: edge cases, and the cases the lexicon data actually produces.
EXTRA_PAIRS = [
    ("ˈfæɹɪŋks", "fˈæɹɪŋks"),
    ("ˈfɜɹmiɑn", "fˈɜːmiɑːn"),  # unstressed ɑ is long; the i before a vowel is not
    ("ˈtɹeɪkiə", "tɹˈeɪkiə"),
    ("ˈmiθeɪn", "mˈiːθeɪn"),
    ("ˌdʒioʊˈθɜɹməl", "dʒˌioʊθˈɜːməl"),
    ("ˈɔɪl", "ˈɔɪl"),
    ("ˈhɑt", "hˈɑːt"),
    ("hɑt", "hɑːt"),  # ɑ is long with or without a mark
    ("mɛθ", "mɛθ"),  # a monosyllable without a mark has nothing to move or lengthen
    ("ˌeɪ tˌi pˈi", "ˌeɪ tˌiː pˈiː"),  # a multi-word string is handled word by word
    ("ˈɜɹ", "ˈɜː"),
    ("", ""),
]
LAYOUT_PAIRS = [(compact, layout) for _, compact, layout in ESPEAK_WORDS] + EXTRA_PAIRS
VOWELS = "aeiouæɑɔɛɪʊʌəɚɜɐᵻ"


def test_the_layout_table_is_large_enough():
    assert len(LAYOUT_PAIRS) >= 30


@pytest.mark.parametrize(("compact", "layout"), LAYOUT_PAIRS)
def test_to_piper_layout_converts_neutral_ipa_to_the_espeak_layout(compact, layout):
    assert to_piper_layout(compact) == layout


@pytest.mark.parametrize("layout", sorted({layout for _, layout in LAYOUT_PAIRS}))
def test_to_piper_layout_leaves_espeak_layout_unchanged(layout):
    assert to_piper_layout(layout) == layout


@pytest.mark.parametrize("compact", sorted({compact for compact, _ in LAYOUT_PAIRS}))
def test_to_piper_layout_is_idempotent(compact):
    once = to_piper_layout(compact)

    assert to_piper_layout(once) == once
    assert "ːː" not in once


@pytest.mark.parametrize("compact", sorted({compact for compact, _ in LAYOUT_PAIRS}))
def test_to_piper_layout_leaves_no_stress_mark_before_a_consonant_that_leads_to_a_vowel(compact):
    assert not re.search(rf"[ˈˌ][^{VOWELS} ˈˌ]+[{VOWELS}]", to_piper_layout(compact))


def test_to_piper_layout_trusts_explicit_length_marks():
    # espeak keeps a short ɔ in "off" and a short i in "-iness"; a string with lengths is final.
    assert to_piper_layout("ˈɔf ˈhɑːt") == "ˈɔf hˈɑːt"
    assert to_piper_layout("tˈɛkinəs sˈiː") == "tˈɛkinəs sˈiː"


def test_to_piper_layout_moves_a_mark_over_the_whole_onset_cluster():
    assert to_piper_layout("ˈstɹɛŋθ") == "stɹˈɛŋθ"
    assert to_piper_layout("ˈtʃɛs") == "tʃˈɛs"
    assert to_piper_layout("ˈbjuti") == "bjˈuːti"


def test_to_piper_layout_keeps_a_mark_that_is_already_on_the_vowel():
    assert to_piper_layout("ˈæt") == "ˈæt"
    assert to_piper_layout("kɹˈeɪ") == "kɹˈeɪ"


@pytest.fixture(scope="module")
def espeak():
    """Piper's own espeak phonemizer (bundled data, no voice needed), ʲ and ᵻ folded away."""
    module = pytest.importorskip("piper.phonemize_espeak")
    phonemizer = module.EspeakPhonemizer()

    def run(word: str) -> str:
        sentences = phonemizer.phonemize("en-us", word)
        spoken = " ".join("".join(sentence) for sentence in sentences).strip()
        return spoken.replace("ʲ", "").replace("ᵻ", "ɪ")

    return run


@pytest.mark.parametrize(("word", "compact", "layout"), ESPEAK_WORDS, ids=lambda v: str(v)[:20])
def test_to_piper_layout_gives_what_espeak_gives_for_the_word(espeak, word, compact, layout):
    assert espeak(word) == layout == to_piper_layout(compact)


def to_compact(spoken: str) -> str:
    """Undo the layout: no lengths, NURSE as ɜɹ, each mark back before its syllable's onset."""
    compact = re.sub("ɜːɹ|ɜː", "ɜɹ", spoken).replace("ː", "")
    return re.sub(rf"([^{VOWELS} ˈˌ]*)([ˈˌ])", r"\2\1", compact)


def test_to_piper_layout_restores_espeak_layout_across_the_science_vocabulary(espeak):
    path = Path(__file__).resolve().parents[2] / "cloudyreader" / "data" / "pronunciations.json"
    if not path.exists():
        pytest.skip("lexicon data not present")
    words = [w for w in json.loads(path.read_text(encoding="utf-8"))["entries"] if w.isalpha()]
    spoken = [s for s in (espeak(w) for w in words) if s and " " not in s]

    restored = sum(to_piper_layout(to_compact(s)) == s for s in spoken)
    untouched = sum(to_piper_layout(s) == s for s in spoken)

    assert len(spoken) > 400
    assert restored / len(spoken) >= 0.95, (restored, len(spoken))
    assert untouched / len(spoken) >= 0.95, (untouched, len(spoken))


def test_to_piper_layout_is_idempotent_on_every_lexicon_pronunciation():
    data = Path(__file__).resolve().parents[2] / "cloudyreader" / "data"
    ipas = []
    for name in ("pronunciations.json", "iupac_morphemes.json"):
        if (data / name).exists():
            entries = json.loads((data / name).read_text(encoding="utf-8"))["entries"]
            ipas += [e["ipa"] for e in entries.values() if isinstance(e, dict) and "ipa" in e]
    if not ipas:
        pytest.skip("lexicon data not present")

    for ipa in ipas:
        once = to_piper_layout(ipa)
        assert to_piper_layout(once) == once, ipa
        assert "ːː" not in once, ipa


def test_render_converts_neutral_override_ipa_to_the_espeak_layout(engine, voice):
    text = engine.render(
        seg("The pharynx hurts.", Override("pharynx", "ˈfæɹɪŋks", "lexicon")), voice
    )

    assert text == "The [[fˈæɹɪŋks]] hurts."


def test_render_converts_before_it_filters_by_the_voice_phoneme_map(voices_dir, tmp_path):
    no_length = write_voice(voices_dir, "en_US-nolong-medium", symbols=SYMBOLS.replace("ː", ""))
    engine = PiperEngine(voices_dir)
    script = script_of(seg("A hot day", Override("hot", "ˈhɑt", "lexicon")))

    assert engine.render(script.segments[0], no_length) == "A [[hˈɑt]] day"
    (warning,) = engine.script_warnings(script, no_length)
    assert "'ː'" in warning and "U+02D0" in warning  # the length mark conversion added is reported


# --- render ----------------------------------------------------------------------------------


def seg(text: str, *overrides: Override, pause: int = 0) -> Segment:
    return Segment(text, pause, tuple(overrides))


def test_render_leaves_text_without_overrides_unchanged(engine, voice):
    assert engine.render(seg("Toss-up number two."), voice) == "Toss-up number two."


def test_render_replaces_the_surface_with_an_inline_ipa_block(engine, voice):
    text = engine.render(seg("Pharynx is part of the throat.", PHARYNX), voice)

    assert text == "[[fˈɑːɹɪŋks]] is part of the throat."


def test_render_replaces_every_occurrence_but_only_whole_words(engine, voice):
    text = engine.render(seg("Pharynx, pharynx, Pharynxes and (Pharynx).", PHARYNX), voice)

    assert text == "[[fˈɑːɹɪŋks,]] pharynx, Pharynxes and ( [[fˈɑːɹɪŋks.]]"


def test_render_prefers_the_longest_surface(engine, voice):
    short = Override("ATP", "ˌeɪ tˌiː pˈiː", "lexicon")
    long = Override("ATP synthase", "ˌeɪ tˌiː pˈiː sˈɪnθeɪs", "lexicon")

    text = engine.render(seg("ATP synthase makes ATP.", short, long), voice)

    assert text == "[[ˌeɪ tˌiː pˈiː sˈɪnθeɪs]] makes [[ˌeɪ tˌiː pˈiː.]]"


def test_render_never_rewrites_text_it_already_substituted(engine, voice):
    first = Override("ATP synthase", "eɪ ti pi", "lexicon")  # IPA contains the word "ti"
    second = Override("ti", "ʃ", "lexicon")

    text = engine.render(seg("ATP synthase and ti.", first, second), voice)

    assert text == "[[eɪ ti pi]] and [[ʃ.]]"


def test_render_handles_surfaces_with_regex_metacharacters(engine, voice):
    ion = Override("Na+", "sˈoʊdiəm", "lexicon")

    assert engine.render(seg("Na+ and Nax.", ion), voice) == "[[sˈoʊdiəm]] and Nax."


def test_render_keeps_the_first_override_when_a_surface_repeats(engine, voice):
    other = Override("Pharynx", "fˈæɹɪŋks", "lexicon")

    assert engine.render(seg("Pharynx.", PHARYNX, other), voice) == "[[fˈɑːɹɪŋks.]]"


def test_render_drops_symbols_the_voice_lacks(engine, voice):
    text = engine.render(seg("Her answer.", Override("Her", "hɝ", "lexicon")), voice)

    assert text == "[[h]] answer."


def test_render_maps_ascii_g_to_the_ipa_letter_the_voice_knows(engine, voice):
    text = engine.render(seg("Gut feeling.", Override("Gut", "gʌt", "lexicon")), voice)

    assert text == "[[ɡʌt]] feeling."
    assert (
        engine.script_warnings(script_of(seg("Gut feeling.", Override("Gut", "gʌt", "x"))), voice)
        == ()
    )


def test_render_trims_the_ipa_and_keeps_inner_spaces(engine, voice):
    text = engine.render(seg("ATP.", Override("ATP", "  eɪ ti pi  ", "lexicon")), voice)

    assert text == "[[eɪ ti pi.]]"


def test_render_speaks_the_surface_plain_when_no_ipa_symbol_survives(engine, voice):
    text = engine.render(seg("Qx rocks.", Override("Qx", "ɝɝ", "lexicon")), voice)

    assert text == "Qx rocks."  # an empty [[]] block would swallow the word


def test_render_ignores_an_override_with_an_empty_surface(engine, voice):
    assert engine.render(seg("Words here.", Override("", "ə", "lexicon")), voice) == "Words here."


LARYNX = Override("larynx", "lˈɛɹɪŋks", "lexicon")


def test_render_keeps_a_trailing_comma_inside_the_block(engine, voice):
    # Piper drops punctuation that follows a block and glues the next word onto it.
    text = engine.render(
        seg("the pharynx, larynx and trachea", Override("pharynx", *PHARYNX_IPA)), voice
    )

    assert text == "the [[fˈɑːɹɪŋks,]] larynx and trachea"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Is it the pharynx?", "Is it the [[fˈɑːɹɪŋks?]]"),
        ("It is the pharynx.", "It is the [[fˈɑːɹɪŋks.]]"),
        ("The pharynx: a tube", "The [[fˈɑːɹɪŋks:]] a tube"),
        ("Wow, the pharynx!", "Wow, the [[fˈɑːɹɪŋks!]]"),
        ("the pharynx;", "the [[fˈɑːɹɪŋks;]]"),
        ("the (pharynx), which", "the ( [[fˈɑːɹɪŋks,]] which"),
        ('he said "the pharynx."', 'he said "the [[fˈɑːɹɪŋks.]]'),
        ("(pharynx).", "( [[fˈɑːɹɪŋks.]]"),
    ],
)
def test_render_moves_punctuation_after_the_surface_into_the_block(engine, voice, raw, expected):
    text = engine.render(seg(raw, Override("pharynx", *PHARYNX_IPA)), voice)

    assert text == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pharynx/larynx", "[[fˈɑːɹɪŋks]] /larynx"),
        ("pharynx-like tube", "[[fˈɑːɹɪŋks]] -like tube"),
        ("pre-pharynx", "pre- [[fˈɑːɹɪŋks]]"),
        ("pharynx,larynx", "[[fˈɑːɹɪŋks,]] larynx"),
        ("(pharynx", "( [[fˈɑːɹɪŋks]]"),
        ("the (pharynx", "the ( [[fˈɑːɹɪŋks]]"),
    ],
)
def test_render_keeps_words_apart_around_a_block(engine, voice, raw, expected):
    text = engine.render(seg(raw, Override("pharynx", *PHARYNX_IPA)), voice)

    assert " ".join(text.split()) == expected


POTASSIUM = Override("Potassium", "pəˈtæsiəm", "lexicon")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Potassium-40 decays.", "[[pətˈæsiəm]] 40 decays."),
        ("W) Potassium-40, X) Potassium-39", "W) [[pətˈæsiəm]] 40, X) [[pətˈæsiəm]] 39"),
        ("Potassium-argon dating", "[[pətˈæsiəm]] -argon dating"),
    ],
)
def test_render_drops_the_hyphen_between_a_block_and_a_mass_number(engine, voice, raw, expected):
    # Regression: espeak reads a text part that opens with "-40" as "minus forty".
    assert engine.render(seg(raw, POTASSIUM), voice) == expected


def test_render_leaves_possessives_to_espeak_instead_of_spelling_out_the_s(engine, voice):
    script = script_of(
        seg("The pharynx’s wall and the pharynx's lining.", Override("pharynx", *PHARYNX_IPA))
    )

    assert engine.render(script.segments[0], voice) == script.segments[0].text
    assert "not found" in engine.script_warnings(script, voice)[0]


def test_render_ignores_syllable_dots_in_the_ipa(engine, voice):
    text = engine.render(seg("A pharynx here", Override("pharynx", "ˈfɑ.ɹɪŋks", "lexicon")), voice)

    assert text == "A [[fˈɑːɹɪŋks]] here"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("N A C L", "N [[ˈeɪ]] C L"),
        ("A T P", "[[ˈeɪ]] T P"),
        ("C A two plus", "C [[ˈeɪ]] two plus"),
        ("A B", "[[ˈeɪ]] B"),
        ("Y A B", "Y [[ˈeɪ]] B"),
        ("D N A", "D N [[ˈeɪ]]"),
        ("B R C A one", "B R C [[ˈeɪ]] one"),
        ("C A 2", "C [[ˈeɪ]] 2"),
        ("A two B three", "[[ˈeɪ]] two B three"),
        ("A l C l three", "[[ˈeɪ]] l C l three"),
        ("A g N O three", "[[ˈeɪ]] g N O three"),
        ("the A T P synthase", "the [[ˈeɪ]] T P synthase"),
        ("N A C L.", "N [[ˈeɪ]] C L."),
        ("W. A T P", "W. [[ˈeɪ]] T P"),
        ("Done. A B C is next.", "Done. [[ˈeɪ]] B C is next."),
        ("A T P and A D P", "[[ˈeɪ]] T P and [[ˈeɪ]] D P"),
    ],
)
def test_render_gives_a_bare_a_in_a_spelled_run_its_letter_name(engine, voice, text, expected):
    # espeak reads a lone "A" as the article /ɐ/, so "N A C L" would sound like "en uh see el".
    assert engine.render(seg(text), voice) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("N a C l", "N [[ˈeɪ]] C l"),
        ("N a H C O three", "N [[ˈeɪ]] H C O three"),
        ("C a two plus", "C [[ˈeɪ]] two plus"),
        ("B a S O four", "B [[ˈeɪ]] S O four"),
    ],
)
def test_render_gives_the_a_of_an_element_symbol_its_letter_name(engine, voice, text, expected):
    assert engine.render(seg(text), voice) == expected


@pytest.mark.parametrize(
    "text",
    [
        "A stone falls from a cliff.",
        "A stone",
        "A two kilogram block",
        "A one",
        "A 1",
        "A",
        "a",
        "points A and B",
        "vitamin A",
        "A, B",
        "A. B",
        "(A B)",
        "A  B",
        "A-B",
        "a b",
        "P a distance",
        "q a distance d",
        "a distance d",
        "N a",
        "N a stone",
    ],
)
def test_render_leaves_the_article_and_lone_letters_alone(engine, voice, text):
    assert engine.render(seg(text), voice) == text


def test_render_spells_a_run_beside_an_override_that_covers_a_run(engine, voice):
    override = Override("A T P synthase", "ˌeɪ tˌiː pˈiː sˈɪnθeɪs", "lexicon")

    text = engine.render(seg("A T P synthase and N A C L", override), voice)

    assert text == "[[ˌeɪ tˌiː pˈiː sˈɪnθeɪs]] and N [[ˈeɪ]] C L"


def test_render_spells_a_run_next_to_an_overridden_word(engine, voice):
    text = engine.render(seg("A B and Pharynx", PHARYNX), voice)

    assert text == "[[ˈeɪ]] B and [[fˈɑːɹɪŋks]]"


def test_spelling_a_run_raises_no_warning(engine, voice):
    assert engine.script_warnings(script_of(seg("N A C L and A T P")), voice) == ()


def test_render_flattens_literal_double_brackets_so_piper_cannot_misread_them(engine, voice):
    text = engine.render(seg("See [[1]] and [H+] and [[[x]]].", PHARYNX), voice)

    assert text == "See [1] and [H+] and [x]."
    assert "[[" not in text


def test_render_rejects_a_voice_key_that_escapes_the_voices_dir(engine):
    bad = VoiceInfo("piper:../evil", "piper", "evil", "en-US", "medium", 1, True, None)

    with pytest.raises(ValueError, match="voice key"):
        engine.render(seg("x"), bad)


def test_render_finds_the_config_from_the_voice_key_when_path_is_missing(engine, voice):
    nameless = VoiceInfo(voice.key, "piper", "fake", "en-US", "medium", 1, True, None)

    assert engine.render(seg("Pharynx.", PHARYNX), nameless) == "[[fˈɑːɹɪŋks.]]"


def test_render_reports_a_missing_voice_config(voices_dir, engine):
    ghost = VoiceInfo("piper:ghost", "piper", "ghost", "en-US", "medium", 1, False, None)

    with pytest.raises(FileNotFoundError, match="ghost"):
        engine.render(seg("x"), ghost)


def test_render_reports_a_broken_voice_config(voices_dir, engine):
    broken = write_voice(voices_dir, "en_US-broken-medium")
    (voices_dir / "en_US-broken-medium.onnx.json").write_text("{not json")

    with pytest.raises(ValueError, match="en_US-broken-medium"):
        engine.render(seg("x"), broken)


# --- warnings --------------------------------------------------------------------------------


def test_script_warnings_name_the_dropped_symbol_surface_and_voice(engine, voice):
    script = script_of(seg("Her answer.", Override("Her", "hɝ", "lexicon")))

    (warning,) = engine.script_warnings(script, voice)

    assert "'ɝ'" in warning and "U+025D" in warning
    assert "'Her'" in warning and voice.key in warning


def test_script_warnings_are_deduplicated_across_segments_and_keep_order(engine, voice):
    her = Override("Her", "hɝ", "lexicon")
    script = script_of(
        seg("Her one.", her), seg("Her two.", her), seg("Qx.", Override("Qx", "ʘ", "x"))
    )

    warnings = engine.script_warnings(script, voice)

    assert len(warnings) == 3  # 'ɝ' once, 'ʘ' once, "no usable symbol" once
    assert "'Her'" in warnings[0] and "'Qx'" in warnings[1] and "no usable" in warnings[2]


def test_script_warnings_flag_an_override_whose_surface_is_not_in_the_text(engine, voice):
    script = script_of(seg("Nothing matches here.", PHARYNX))

    (warning,) = engine.script_warnings(script, voice)

    assert "'Pharynx'" in warning and "not found" in warning


def test_script_warnings_flag_an_empty_surface(engine, voice):
    (warning,) = engine.script_warnings(script_of(seg("x.", Override("", "ə", "lexicon"))), voice)

    assert "empty surface" in warning


def test_script_warnings_are_empty_for_a_clean_script(engine, voice):
    assert engine.script_warnings(script_of(seg("Pharynx is a word.", PHARYNX)), voice) == ()


def test_synthesize_logs_every_warning(engine, voice, tmp_path, caplog):
    script = script_of(seg("Her answer.", Override("Her", "hɝ", "lexicon")))

    with caplog.at_level(logging.WARNING, logger="cloudyreader.engines.piper"):
        engine.synthesize(script, voice, RenderOptions(), tmp_path / "out.wav")

    assert "U+025D" in caplog.text


# --- synthesize ------------------------------------------------------------------------------


def test_synthesize_writes_a_mono_16_bit_wav_with_each_pause_appended(engine, voice, tmp_path):
    out = tmp_path / "out.wav"
    script = script_of(
        seg("hello there", pause=500), seg("world", pause=0), seg("again", pause=300)
    )

    audio = engine.synthesize(script, voice, RenderOptions(), out)

    params, samples = read_wav(out)
    pause_a, pause_c = round(RATE * 0.5), round(RATE * 0.3)
    speech = [len(t) * SAMPLES_PER_CHAR for t in ("hello there", "world", "again")]
    assert (params.nchannels, params.sampwidth, params.framerate) == (1, 2, RATE)
    assert len(samples) == sum(speech) + pause_a + pause_c
    first_end = speech[0]
    assert (samples[:first_end] == AMPLITUDE).all()
    assert (samples[first_end : first_end + pause_a] == 0).all()
    second = samples[first_end + pause_a : first_end + pause_a + speech[1]]
    assert (second == AMPLITUDE).all()
    assert (samples[-pause_c:] == 0).all()
    assert audio.wav_path == out
    assert audio.sample_rate == RATE
    assert audio.duration_s == pytest.approx(len(samples) / RATE)
    assert audio.cache_hit is False


def test_synthesize_feeds_the_rendered_text_to_piper(engine, voice, fake, tmp_path):
    script = script_of(seg("Pharynx is a word.", PHARYNX), seg("Plain."))

    engine.synthesize(script, voice, RenderOptions(), tmp_path / "out.wav")

    assert [text for text, _ in fake.calls] == ["[[fˈɑːɹɪŋks]] is a word.", "Plain."]


@pytest.mark.parametrize(
    ("text", "units"),
    [
        (
            "It is the pharynx. Next one.",
            ["It is the [[fˈɑːɹɪŋks.]]", "Next one."],
        ),
        (
            "Done. Pharynx is next.",
            ["Done.", "[[fˈɑːɹɪŋks]] is next."],
        ),
        (
            "Is it the pharynx? Yes, the pharynx! Truly the pharynx.",
            ["Is it the [[fˈɑːɹɪŋks?]]", "Yes, the [[fˈɑːɹɪŋks!]]", "Truly the [[fˈɑːɹɪŋks.]]"],
        ),
        ("W. Pharynx", ["W.", "[[fˈɑːɹɪŋks]]"]),
        ("The pharynx, then more.", ["The [[fˈɑːɹɪŋks,]] then more."]),
    ],
)
def test_sentences_next_to_a_block_are_synthesized_separately(
    engine, voice, fake, tmp_path, text, units
):
    # Piper appends the sentence after a block to the block's own phoneme sequence.
    engine.synthesize(
        script_of(seg(text, Override("pharynx", *PHARYNX_IPA), Override("Pharynx", *PHARYNX_IPA))),
        voice,
        RenderOptions(),
        tmp_path / "o.wav",
    )

    assert [call_text for call_text, _ in fake.calls] == units


def test_synthesize_joins_the_sentence_chunks_of_one_segment(engine, voice, tmp_path):
    out = tmp_path / "out.wav"

    engine.synthesize(script_of(seg("One. Two.")), voice, RenderOptions(), out)

    assert len(read_wav(out)[1]) == (len("One") + len("Two")) * SAMPLES_PER_CHAR


def test_synthesize_gives_blank_segments_only_their_pause(engine, voice, fake, tmp_path):
    out = tmp_path / "out.wav"

    engine.synthesize(
        script_of(seg("", pause=400), seg("   ", pause=100)), voice, RenderOptions(), out
    )

    assert fake.calls == []
    assert len(read_wav(out)[1]) == round(RATE * 0.4) + round(RATE * 0.1)


def test_synthesize_treats_a_negative_pause_as_none(engine, voice, tmp_path):
    out = tmp_path / "out.wav"

    audio = engine.synthesize(script_of(seg("abc", pause=-50)), voice, RenderOptions(), out)

    assert len(read_wav(out)[1]) == 3 * SAMPLES_PER_CHAR
    assert audio.duration_s == pytest.approx(3 * SAMPLES_PER_CHAR / RATE)


def test_synthesize_an_empty_script_writes_a_valid_empty_wav(engine, voice, tmp_path):
    out = tmp_path / "out.wav"

    audio = engine.synthesize(SpokenScript(()), voice, RenderOptions(), out)

    assert read_wav(out)[0].nframes == 0
    assert audio.duration_s == 0


@pytest.mark.parametrize(
    ("speed", "length_scale"), [(1.0, 1.0), (2.0, 0.5), (0.5, 2.0), (1.25, 0.8)]
)
def test_speed_becomes_the_inverse_length_scale(engine, voice, fake, tmp_path, speed, length_scale):
    engine.synthesize(script_of(seg("abc")), voice, RenderOptions(speed=speed), tmp_path / "o.wav")

    assert fake.calls[0][1].length_scale == pytest.approx(length_scale)


def test_speed_scales_the_voice_own_default_length_scale(voices_dir, fake, tmp_path):
    slow_voice = write_voice(voices_dir, "en_US-slow-medium", length_scale=1.2)
    engine = PiperEngine(voices_dir, loader=lambda model, config: fake)

    engine.synthesize(
        script_of(seg("abc")), slow_voice, RenderOptions(speed=2.0), tmp_path / "o.wav"
    )

    assert fake.calls[0][1].length_scale == pytest.approx(0.6)


@pytest.mark.parametrize("speed", [0, -1.0, float("nan"), float("inf")])
def test_unusable_speed_is_rejected(engine, voice, tmp_path, speed):
    with pytest.raises(ValueError, match="speed"):
        engine.synthesize(
            script_of(seg("abc")), voice, RenderOptions(speed=speed), tmp_path / "o.wav"
        )


def test_speaker_id_reaches_a_multi_speaker_voice(voices_dir, fake, tmp_path):
    multi = write_voice(voices_dir, "en_US-multi-medium", num_speakers=4)
    engine = PiperEngine(voices_dir, loader=lambda model, config: fake)

    engine.synthesize(script_of(seg("abc")), multi, RenderOptions(speaker_id=2), tmp_path / "o.wav")

    assert fake.calls[0][1].speaker_id == 2


@pytest.mark.parametrize("speaker", [4, 99, -1])
def test_speaker_id_outside_the_voice_is_rejected(voices_dir, fake, tmp_path, speaker):
    multi = write_voice(voices_dir, "en_US-multi-medium", num_speakers=4)
    engine = PiperEngine(voices_dir, loader=lambda model, config: fake)

    with pytest.raises(ValueError, match="speaker"):
        engine.synthesize(
            script_of(seg("x")), multi, RenderOptions(speaker_id=speaker), tmp_path / "o.wav"
        )

    assert fake.calls == []


def test_speaker_id_is_ignored_by_a_single_speaker_voice(engine, voice, fake, tmp_path):
    engine.synthesize(script_of(seg("abc")), voice, RenderOptions(speaker_id=3), tmp_path / "o.wav")

    assert fake.calls[0][1].speaker_id is None


def test_each_voice_is_loaded_once_and_reused(voices_dir, voice, tmp_path):
    loads: list[Path] = []

    def loader(model: Path, config: Path) -> FakePiperVoice:
        loads.append(model)
        return FakePiperVoice()

    engine = PiperEngine(voices_dir, loader=loader)
    other = write_voice(voices_dir, "en_US-other-medium")

    for target in (voice, voice, other, voice):
        engine.synthesize(script_of(seg("abc")), target, RenderOptions(), tmp_path / "o.wav")

    assert loads == [voice.path, other.path]


def test_the_loader_gets_the_model_and_its_config_path(voices_dir, voice, tmp_path):
    seen: list[tuple[Path, Path]] = []

    def loader(model: Path, config: Path) -> FakePiperVoice:
        seen.append((model, config))
        return FakePiperVoice()

    PiperEngine(voices_dir, loader=loader).synthesize(
        script_of(seg("abc")), voice, RenderOptions(), tmp_path / "o.wav"
    )

    assert seen == [(voice.path, voice.path.with_name(voice.path.name + ".json"))]


def test_a_voice_of_another_engine_is_rejected(engine, tmp_path):
    kokoro = VoiceInfo("kokoro:af_heart", "kokoro", "af_heart", "en-US", "high", 1, True, None)

    with pytest.raises(ValueError, match="kokoro"):
        engine.synthesize(script_of(seg("x")), kokoro, RenderOptions(), tmp_path / "o.wav")


def test_a_voice_whose_model_file_is_gone_is_reported(engine, voice, tmp_path):
    os.remove(voice.path)

    with pytest.raises(FileNotFoundError, match=voice.path.name):
        engine.synthesize(script_of(seg("x")), voice, RenderOptions(), tmp_path / "o.wav")


def test_synthesis_is_serialized_even_across_threads(voices_dir, voice, tmp_path):
    slow = FakePiperVoice(delay_s=0.05)
    engine = PiperEngine(voices_dir, loader=lambda model, config: slow)
    threads = [
        threading.Thread(
            target=engine.synthesize,
            args=(script_of(seg("abc")), voice, RenderOptions(), tmp_path / f"o{i}.wav"),
        )
        for i in range(4)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(slow.calls) == 4
    assert slow.max_active == 1  # the bundled espeak is not thread-safe


# --- real voice ------------------------------------------------------------------------------


def real_lessac() -> tuple[PiperEngine, VoiceInfo]:
    data_dir = os.environ.get("CLOUDYREADER_DATA_DIR")
    root = Path(data_dir) if data_dir else Path(__file__).resolve().parents[2] / ".data"
    voices_dir = root / "voices"
    if not (voices_dir / "en_US-lessac-medium.onnx").exists():
        pytest.skip(f"en_US-lessac-medium is not installed in {voices_dir}")
    engine = PiperEngine(voices_dir)
    return engine, next(v for v in engine.voices() if v.key == "piper:en_US-lessac-medium")


def real_parser(voice: VoiceInfo):
    """Piper's own phonemizer for the voice; it needs the config only, not the ONNX model."""
    from piper import PiperConfig, PiperVoice

    config = PiperConfig.from_dict(
        json.loads(voice.path.with_name(voice.path.name + ".json").read_text())
    )
    return PiperVoice(session=None, config=config)  # type: ignore[arg-type]


@pytest.mark.voice
def test_lessac_gets_the_letter_name_for_a_in_a_spelled_run():
    engine, voice = real_lessac()

    assert engine.render(seg("N A C L"), voice) == "N [[ˈeɪ]] C L"
    assert engine.render(seg("A stone falls."), voice) == "A stone falls."
    assert engine.render(seg("N a H C O three"), voice) == "N [[ˈeɪ]] H C O three"
    # The block must reach Piper's real parser as the letter name, between the neighbours.
    spoken = "".join(real_parser(voice).phonemize(engine.render(seg("N A C L"), voice))[0])
    assert spoken.startswith("ˈɛn ˈeɪ s")


@pytest.mark.voice
def test_lessac_phoneme_map_covers_every_converted_lexicon_pronunciation():
    engine, voice = real_lessac()
    data = Path(__file__).resolve().parents[2] / "cloudyreader" / "data"
    flagged = []
    checked = 0
    for name in ("pronunciations.json", "iupac_morphemes.json"):
        if not (data / name).exists():
            continue
        for word, entry in json.loads((data / name).read_text(encoding="utf-8"))["entries"].items():
            if isinstance(entry, dict) and "ipa" in entry:
                checked += 1
                script = script_of(seg(word, Override(word, entry["ipa"], "lexicon")))
                if engine.script_warnings(script, voice):
                    flagged.append(word)
    if not checked:
        pytest.skip("lexicon data not present")

    assert flagged == []  # no symbol dropped after conversion, and every surface found


@pytest.mark.voice
@pytest.mark.slow
def test_lessac_speaks_a_respelled_word_without_silence(tmp_path):
    engine, voice = real_lessac()
    segment = Segment("Pharynx is part of the throat.", 300, (PHARYNX,))

    text = engine.render(segment, voice)
    assert text == "[[fˈɑːɹɪŋks]] is part of the throat."
    assert engine.script_warnings(SpokenScript((segment,)), voice) == ()

    # Piper's own parser must keep the override symbols verbatim at the head of the sentence.
    parser = real_parser(voice)
    assert "".join(parser.phonemize(text)[0]).startswith("fˈɑːɹɪŋks")

    # Piper 1.8 drops punctuation after a block and glues the next word on: rendering must not.
    questions = Segment(
        "Is it the pharynx? Yes, the pharynx, then more.", 0, (Override("pharynx", *PHARYNX_IPA),)
    )
    spoken = [
        "".join(parser.phonemize(unit)[0])
        for unit in piper_module._units(engine.render(questions, voice))
    ]
    assert len(spoken) == 2
    assert spoken[0].endswith(" fˈɑːɹɪŋks?")
    assert " fˈɑːɹɪŋks, " in spoken[1] and spoken[1].endswith(".")

    out = tmp_path / "pharynx.wav"
    audio = engine.synthesize(SpokenScript((segment,)), voice, RenderOptions(), out)

    params, samples = read_wav(out)
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    assert (params.nchannels, params.sampwidth, params.framerate) == (1, 2, 22050)
    assert rms > 300, f"audio is near-silent (rms={rms:.1f})"
    assert 1.0 < audio.duration_s < 8.0
    assert audio.duration_s == pytest.approx(len(samples) / 22050)
    tail = samples[-round(22050 * 0.3) :]
    assert (tail == 0).all()  # the 300 ms pause is true digital silence
