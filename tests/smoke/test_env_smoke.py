"""Environment smoke tests. Each test skips with a reason when its dependency is absent."""

import importlib.metadata
import importlib.util
import os
import shutil
import sys
import wave
from pathlib import Path

import pytest

import cloudyreader

DATA_DIR = Path(
    os.environ.get("CLOUDYREADER_DATA_DIR", Path(__file__).resolve().parents[2] / ".data")
)
DEFAULT_VOICE = DATA_DIR / "voices" / "en_US-lessac-medium.onnx"
PHARYNX_IPA = "fˈæɹɪŋks"  # [FAR-ingks] written as eSpeak-style IPA


def require(module: str, fix: str = "make deps") -> None:
    if importlib.util.find_spec(module) is None:
        pytest.skip(f"{module} is not installed (run: {fix})")


@pytest.fixture(scope="module")
def piper_voice():
    require("piper")
    if not DEFAULT_VOICE.exists():
        pytest.skip(f"{DEFAULT_VOICE.name} missing (run: make voices)")
    from piper import PiperVoice

    return PiperVoice.load(DEFAULT_VOICE)


def test_package_version_matches_metadata():
    assert cloudyreader.__version__ == importlib.metadata.version("cloudyreader")


@pytest.mark.voice
def test_piper_synthesizes_hello_wav(piper_voice, tmp_path):
    out = tmp_path / "hello.wav"
    with wave.open(str(out), "wb") as wav_file:
        piper_voice.synthesize_wav("Hello", wav_file)
    with wave.open(str(out), "rb") as wav_file:
        assert wav_file.getnframes() > 0
        assert wav_file.getframerate() == piper_voice.config.sample_rate


@pytest.mark.model
@pytest.mark.slow
def test_scispacy_tags_chemical_and_protein():
    require("spacy")
    require("en_ner_craft_md", "make models")
    import spacy

    doc = spacy.load("en_ner_craft_md")("Insulin is secreted by beta cells in response to glucose.")
    labels = {ent.text.lower(): ent.label_ for ent in doc.ents}
    assert labels.get("glucose") == "CHEBI"
    assert labels.get("insulin") == "GGP"


@pytest.mark.java
def test_opsin_parses_iupac_name_with_bundled_jre(monkeypatch, tmp_path):
    require("py2opsin")
    require("jdk4py")
    import jdk4py

    # py2opsin runs the bare `java`; the pip-installed JRE goes first on PATH.
    monkeypatch.setenv("PATH", f"{jdk4py.JAVA_HOME / 'bin'}{os.pathsep}{os.environ['PATH']}")
    assert Path(shutil.which("java")) == jdk4py.JAVA
    from py2opsin import py2opsin

    smiles = py2opsin("2-methylpropan-1-ol", tmp_fpath=str(tmp_path / "opsin_in.txt"))
    assert smiles == "CC(CO)C"


def test_espeak_phonemizes_esophagus_to_ipa():
    require("piper")
    from piper.phonemize_espeak import EspeakPhonemizer

    sentences = EspeakPhonemizer().phonemize("en-us", "esophagus")
    assert "".join(sentences[0]) == "ɪsˈɑːfəɡəs"


def test_qapplication_builds_offscreen(monkeypatch):
    require("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    assert app.platformName() == "offscreen"


def test_afplay_is_available():
    if sys.platform != "darwin":
        pytest.skip("afplay is macOS-only")
    # Only locate the binary: tests must never play audio.
    assert shutil.which("afplay")


@pytest.mark.voice
def test_piper_speaks_raw_phonemes(piper_voice):
    # Text inside [[ ]] bypasses eSpeak: each codepoint is one phoneme.
    sentences = piper_voice.phonemize(f"The [[ {PHARYNX_IPA} ]] is a tube.")
    assert PHARYNX_IPA in "".join(sentences[0])
    assert set(PHARYNX_IPA) <= set(piper_voice.config.phoneme_id_map)
    audio = piper_voice.phoneme_ids_to_audio(piper_voice.phonemes_to_ids(list(PHARYNX_IPA)))
    assert audio.size > 0
