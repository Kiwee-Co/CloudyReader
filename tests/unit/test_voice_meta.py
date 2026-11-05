"""voice_meta: gender and accent per voice (Kokoro id letters, the pinned Piper table)."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import typing
from pathlib import Path

import pytest

from cloudyreader.engines import kokoro
from cloudyreader.engines.kokoro import VOICE_GRADES, KokoroEngine
from cloudyreader.models import VoiceInfo
from cloudyreader.voice_meta import PIPER_GENDERS, Gender, VoiceProfile, profile_of
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
