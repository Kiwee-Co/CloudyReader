"""cloudyreader.engines.letter_clips and the clip hook in Qwen3-TTS and Chatterbox Turbo.

The clips stand in for a lone choice letter ("W.") in the voices that read one as a word. Each
engine runs against its fake backend here; tests/engines_real plays the shipped clips for real.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from cloudyreader.config import Settings
from cloudyreader.engines import chatterbox_turbo as ct
from cloudyreader.engines import letter_clips
from cloudyreader.engines import qwen3_tts as qt
from cloudyreader.engines.letter_clips import (
    FOLDER,
    MANIFEST,
    LetterClips,
    clips_dir,
    lone_letter,
)
from cloudyreader.engines.mlxkit import SAMPLE_RATE, ModelSlot, write_pcm16
from cloudyreader.models import Override, RenderOptions, Segment, SpokenScript
from cloudyreader.normalize import CHOICE_PAUSE_MS, LETTER_PAUSE_MS, ScriptNormalizer
from cloudyreader.parser import parse
from tests.unit import test_chatterbox_engine as cbt
from tests.unit import test_qwen3_engine as qwt

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "questions"
SHIPPED = ROOT / "cloudyreader" / "engines" / FOLDER
SHIPPED_VOICES = {("qwen3_tts", "ryan"), ("qwen3_tts", "aiden"), ("chatterbox_turbo", "builtin")}
TONE = np.linspace(-0.5, 0.5, 4800, dtype=np.float32)  # 0.2 s, no sample the fake backend gives


def wav_bytes(path: Path, samples: np.ndarray, rate: int = SAMPLE_RATE) -> bytes:
    write_pcm16(path, samples, rate)
    return path.read_bytes()


def make_folder(
    root: Path, clips: dict[tuple[str, str, str], np.ndarray], rate: int = SAMPLE_RATE
) -> Path:
    """A clip folder laid out as make_letter_clips.py writes it: WAVs plus manifest.json."""
    entries = []
    for (engine, voice, letter), samples in sorted(clips.items()):
        data = wav_bytes(root / engine / voice / f"{letter}.wav", samples, rate)
        entries.append(
            {
                "engine": engine,
                "voice": voice,
                "letter": letter,
                "rate": rate,
                "frames": len(samples),
                "sha256": hashlib.sha256(data).hexdigest(),
                "take": 0,
                "seed": 1,
                "text": f"{letter}.",
            }
        )
    (root / MANIFEST).write_text(json.dumps({"clips": entries}, indent=1) + "\n")
    return root


def pcm16(samples: np.ndarray) -> np.ndarray:
    return np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")


def read_pcm(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (SAMPLE_RATE, 1, 2)
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")


# --- lone_letter -------------------------------------------------------------------------------


@pytest.mark.parametrize("letter", "WXYZ")
@pytest.mark.parametrize("pause", [LETTER_PAUSE_MS, CHOICE_PAUSE_MS, 0])
def test_a_lone_choice_letter_is_found_whatever_its_pause(letter: str, pause: int) -> None:
    assert lone_letter(Segment(f"{letter}.", pause)) == letter


@pytest.mark.parametrize(
    "text",
    ["A.", "V.", "w.", "W", "W!", "WY.", "W. Pharynx.", "Answer. W. Pharynx.", "double you.", ""],
)
def test_any_other_text_is_no_lone_letter(text: str) -> None:
    assert lone_letter(Segment(text, LETTER_PAUSE_MS)) is None


def test_a_letter_with_an_override_is_no_lone_letter() -> None:
    # speakable() would say the override, so the model's text is no longer the bare letter.
    override = Override("W", "ˈdʌbəlju", "respelling", respelling="dub-ul-yoo")
    assert lone_letter(Segment("W.", LETTER_PAUSE_MS, (override,))) is None


def test_every_fixture_letter_and_nothing_else_is_a_lone_letter() -> None:
    normalizer = ScriptNormalizer()
    pastes = sorted(FIXTURES.glob("*.txt"))
    assert len(pastes) == 63
    for paste in pastes:
        questions = parse(paste.read_bytes().decode("utf-8"))
        script = normalizer.to_script(questions, {}, RenderOptions(read_answer=True))
        found = [seg.text for seg in script.segments if lone_letter(seg)]
        letters = [f"{choice.letter}." for q in questions for choice in q.choices]
        assert found == letters, paste.name


# --- LetterClips -------------------------------------------------------------------------------


def test_a_clip_comes_back_as_written_read_only_and_read_once(tmp_path: Path) -> None:
    folder = make_folder(tmp_path, {("qwen3_tts", "ryan", "W"): TONE})
    clips = LetterClips(folder)

    clip = clips.get("qwen3_tts", "ryan", Segment("W.", LETTER_PAUSE_MS), SAMPLE_RATE)

    assert clip is not None and clip.dtype == np.float32
    assert np.array_equal(pcm16(clip), pcm16(TONE))  # the WAV's very samples
    assert not clip.flags.writeable
    (folder / "qwen3_tts" / "ryan" / "W.wav").unlink()
    again = clips.get("qwen3_tts", "ryan", Segment("W.", CHOICE_PAUSE_MS), SAMPLE_RATE)
    assert again is clip  # cached: the file is read and hashed once


def test_no_clip_for_other_text_voices_engines_or_letters(tmp_path: Path) -> None:
    clips = LetterClips(make_folder(tmp_path, {("qwen3_tts", "ryan", "W"): TONE}))
    letter = Segment("W.", LETTER_PAUSE_MS)

    assert clips.get("qwen3_tts", "ryan", Segment("Nitrogen.", 400), SAMPLE_RATE) is None
    assert clips.get("qwen3_tts", "aiden", letter, SAMPLE_RATE) is None
    assert clips.get("kokoro", "ryan", letter, SAMPLE_RATE) is None
    assert clips.get("qwen3_tts", "ryan", Segment("X.", LETTER_PAUSE_MS), SAMPLE_RATE) is None


def test_nothing_is_read_before_a_lone_letter_asks(tmp_path: Path) -> None:
    calls: list[int] = []

    def folder() -> Path:
        calls.append(1)
        return tmp_path

    clips = LetterClips(folder)
    assert clips.get("qwen3_tts", "ryan", Segment("Nitrogen.", 400), SAMPLE_RATE) is None
    assert calls == []
    assert clips.get("qwen3_tts", "ryan", Segment("W.", 300), SAMPLE_RATE) is None
    assert calls == [1]


def test_no_folder_means_no_clips_and_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert LetterClips(None).get("qwen3_tts", "ryan", Segment("W."), SAMPLE_RATE) is None
    assert caplog.records == []


def damage_hash(folder: Path) -> None:
    path = folder / "qwen3_tts" / "ryan" / "W.wav"
    data = bytearray(path.read_bytes())
    data[-1] ^= 0x01  # one flipped sample bit: still a valid WAV
    path.write_bytes(bytes(data))


def drop_wav(folder: Path) -> None:
    (folder / "qwen3_tts" / "ryan" / "W.wav").unlink()


def drop_manifest(folder: Path) -> None:
    (folder / MANIFEST).unlink()


def garble_manifest(folder: Path) -> None:
    (folder / MANIFEST).write_text("{not json")


def wrong_frames(folder: Path) -> None:
    manifest = json.loads((folder / MANIFEST).read_text())
    manifest["clips"][0]["frames"] += 1
    (folder / MANIFEST).write_text(json.dumps(manifest))


def stereo_clip(folder: Path) -> None:
    path = folder / "qwen3_tts" / "ryan" / "W.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(np.zeros(200, dtype="<i2").tobytes())
    manifest = json.loads((folder / MANIFEST).read_text())
    manifest["clips"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (folder / MANIFEST).write_text(json.dumps(manifest))


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (damage_hash, "fails its SHA-256"),
        (drop_wav, "unreadable"),
        (drop_manifest, "no letter clips"),
        (garble_manifest, "no letter clips"),
        (wrong_frames, "disagrees with manifest.json"),
        (stereo_clip, "no 16-bit mono WAV"),
    ],
)
def test_a_damaged_clip_is_skipped_with_a_warning(
    damage, message: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    folder = make_folder(tmp_path, {("qwen3_tts", "ryan", "W"): TONE})
    damage(folder)

    with caplog.at_level(logging.WARNING, logger=letter_clips.__name__):
        clip = LetterClips(folder).get("qwen3_tts", "ryan", Segment("W."), SAMPLE_RATE)

    assert clip is None
    assert [message in record.getMessage() for record in caplog.records] == [True]


@pytest.mark.parametrize(
    "entry",
    [
        {"engine": "../x", "voice": "ryan", "letter": "W"},
        {"engine": "qwen3_tts", "voice": "Ryan", "letter": "W"},
        {"engine": "qwen3_tts", "voice": "ryan", "letter": "A"},
        {"engine": "qwen3_tts", "voice": "ryan", "letter": "W", "rate": "24000"},
        {"engine": "qwen3_tts", "voice": "ryan", "letter": "W", "frames": True},
        {"engine": "qwen3_tts", "voice": "ryan", "letter": "W", "sha256": "ABC"},
        "W.wav",
    ],
)
def test_a_malformed_manifest_entry_is_skipped_with_a_warning(
    entry, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    folder = make_folder(tmp_path, {("qwen3_tts", "ryan", "W"): TONE})
    manifest = json.loads((folder / MANIFEST).read_text())
    if isinstance(entry, dict):
        entry = manifest["clips"][0] | entry
    manifest["clips"] = [entry]
    (folder / MANIFEST).write_text(json.dumps(manifest))

    with caplog.at_level(logging.WARNING, logger=letter_clips.__name__):
        clip = LetterClips(folder).get("qwen3_tts", "ryan", Segment("W."), SAMPLE_RATE)

    assert clip is None
    assert ["malformed" in record.getMessage() for record in caplog.records] == [True]


def test_a_clip_at_another_rate_is_resampled_to_the_engine_rate(tmp_path: Path) -> None:
    folder = make_folder(tmp_path, {("qwen3_tts", "ryan", "W"): TONE}, rate=48_000)

    clip = LetterClips(folder).get("qwen3_tts", "ryan", Segment("W."), SAMPLE_RATE)

    assert clip is not None and len(clip) == len(TONE) // 2
    assert clip[0] == pytest.approx(TONE[0], abs=1e-4)
    assert clip[-1] == pytest.approx(TONE[-2], abs=1e-4)  # every second sample


# --- where the clips are -----------------------------------------------------------------------


def test_a_checkout_reads_the_package_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert clips_dir() == SHIPPED


def test_a_frozen_app_reads_its_bundled_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    contents = tmp_path / "Cloudy Reader.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    bundled = contents / "Resources" / "cloudyreader" / "engines" / FOLDER
    make_folder(bundled, {("chatterbox_turbo", "builtin", "Z"): TONE})
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(contents / "MacOS" / "Cloudy Reader"))

    assert clips_dir() == bundled.resolve()
    clip = LetterClips().get("chatterbox_turbo", "builtin", Segment("Z."), SAMPLE_RATE)
    assert clip is not None and np.array_equal(pcm16(clip), pcm16(TONE))


def test_a_frozen_process_outside_an_app_has_no_clips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))

    assert clips_dir() is None
    assert LetterClips().get("qwen3_tts", "ryan", Segment("W."), SAMPLE_RATE) is None


# --- the shipped clips -------------------------------------------------------------------------


def test_the_shipped_clips_cover_each_letter_of_each_word_reading_voice() -> None:
    entries = json.loads((SHIPPED / MANIFEST).read_text())["clips"]

    assert {(e["engine"], e["voice"], e["letter"]) for e in entries} == {
        (engine, voice, letter) for engine, voice in SHIPPED_VOICES for letter in "WXYZ"
    }
    assert sorted(p.relative_to(SHIPPED).as_posix() for p in SHIPPED.rglob("*") if p.is_file()) == (
        sorted([MANIFEST] + [f"{e['engine']}/{e['voice']}/{e['letter']}.wav" for e in entries])
    )


@pytest.mark.parametrize(("engine", "voice"), sorted(SHIPPED_VOICES))
@pytest.mark.parametrize("letter", "WXYZ")
def test_each_shipped_clip_loads_and_is_short_clean_and_unclipped(
    engine: str, voice: str, letter: str
) -> None:
    clip = LetterClips(SHIPPED).get(engine, voice, Segment(f"{letter}."), SAMPLE_RATE)

    assert clip is not None
    assert 0.3 <= len(clip) / SAMPLE_RATE <= 1.2
    peak = float(np.abs(clip).max())
    assert 0.05 < peak < 0.99  # audible, never at full scale
    edge = SAMPLE_RATE // 100
    assert np.abs(clip[:edge]).max() <= 0.1 * peak and np.abs(clip[-edge:]).max() <= 0.1 * peak
    assert pcm16(clip)[0] == 0 and pcm16(clip)[-1] == 0  # exact zeros, as the engines cut a take


# --- the engines -------------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(tmp_path, tmp_path / "cache", tmp_path / "voices", tmp_path / "models")


def qwen(settings: Settings, clips: LetterClips) -> tuple[qt.Qwen3TtsEngine, qwt.FakeBackend]:
    backend = qwt.FakeBackend()
    engine = qt.Qwen3TtsEngine(
        settings,
        backend,
        pinned=qwt.install(settings),
        assess=lambda: qwt.READY,
        slot=ModelSlot(),
        decoder=lambda: qwt.PATCH,
        clips=clips,
    )
    return engine, backend


def chatterbox(
    settings: Settings, clips: LetterClips
) -> tuple[ct.ChatterboxTurboEngine, cbt.FakeBackend]:
    backend = cbt.FakeBackend()
    engine = ct.ChatterboxTurboEngine(
        settings,
        backend,
        pinned=cbt.install(settings),
        assess=lambda: cbt.READY,
        slot=ModelSlot(capacity=1),
        clips=clips,
    )
    return engine, backend


ENGINES = {
    "ryan": (qwen, "qwen3_tts", "ryan", 0),
    "aiden": (qwen, "qwen3_tts", "aiden", 1),
    "builtin": (chatterbox, "chatterbox_turbo", "builtin", 0),
}


def say(engine, out: Path, *segments: Segment, voice: int = 0) -> np.ndarray:
    chosen = engine.voices()[voice]
    engine.synthesize(SpokenScript(tuple(segments)), chosen, RenderOptions(), out)
    return read_pcm(out)


@pytest.mark.parametrize("name", list(ENGINES))
def test_a_lone_letter_plays_its_clip_then_exactly_its_pause(
    name: str, settings: Settings, tmp_path: Path
) -> None:
    make, engine_key, voice_id, index = ENGINES[name]
    clips = LetterClips(make_folder(tmp_path / "clips", {(engine_key, voice_id, "W"): TONE}))
    engine, backend = make(settings, clips)
    segments = (Segment("W.", LETTER_PAUSE_MS), Segment("Nitrogen.", CHOICE_PAUSE_MS))

    pcm = say(engine, tmp_path / "out.wav", *segments, voice=index)

    assert backend.texts == ["Nitrogen."]  # the letter never reached the model
    pause = SAMPLE_RATE * LETTER_PAUSE_MS // 1000
    assert np.array_equal(pcm[: len(TONE)], pcm16(TONE))
    assert not pcm[len(TONE) : len(TONE) + pause].any()
    assert pcm[len(TONE) + pause] != 0  # then the choice text


@pytest.mark.parametrize("name", list(ENGINES))
def test_other_letters_and_other_voices_still_reach_the_model(
    name: str, settings: Settings, tmp_path: Path
) -> None:
    make, engine_key, voice_id, index = ENGINES[name]
    other = "aiden" if voice_id == "ryan" else "ryan"
    clips = {(engine_key, voice_id, "W"): TONE, (engine_key, other, "X"): TONE}
    engine, backend = make(settings, LetterClips(make_folder(tmp_path / "clips", clips)))
    letters = [Segment(f"{c}.", LETTER_PAUSE_MS) for c in "WXYZ"]

    say(engine, tmp_path / "out.wav", *letters, voice=index)

    assert backend.texts == ["ecks.", "Why.", "Z."]  # say_letter, as before


@pytest.mark.parametrize("name", list(ENGINES))
def test_a_voice_without_clips_says_the_letter_as_before(
    name: str, settings: Settings, tmp_path: Path
) -> None:
    make, _, _, index = ENGINES[name]
    engine, backend = make(settings, LetterClips(None))

    say(
        engine,
        tmp_path / "out.wav",
        *[Segment(f"{c}.", LETTER_PAUSE_MS) for c in "WXYZ"],
        voice=index,
    )

    assert backend.texts == ["double you.", "ecks.", "Why.", "Z."]


@pytest.mark.parametrize("name", list(ENGINES))
def test_a_clip_that_fails_its_hash_falls_back_to_the_model(
    name: str, settings: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    make, engine_key, voice_id, index = ENGINES[name]
    folder = make_folder(tmp_path / "clips", {(engine_key, voice_id, "W"): TONE})
    path = folder / engine_key / voice_id / "W.wav"
    path.write_bytes(path.read_bytes()[:-2] + b"\x01\x00")
    engine, backend = make(settings, LetterClips(folder))

    with caplog.at_level(logging.WARNING, logger=letter_clips.__name__):
        say(engine, tmp_path / "out.wav", Segment("W.", LETTER_PAUSE_MS), voice=index)

    assert backend.texts == ["double you."]
    assert any("fails its SHA-256" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("name", list(ENGINES))
def test_the_shipped_clips_leave_every_other_fixture_segment_to_the_model(
    name: str, settings: Settings, tmp_path: Path
) -> None:
    make, _, _, index = ENGINES[name]
    shipped, shipped_backend = make(settings, LetterClips(SHIPPED))
    plain, plain_backend = make(settings, LetterClips(None))
    normalizer = ScriptNormalizer()
    for paste in sorted(FIXTURES.glob("*.txt")):
        questions = parse(paste.read_bytes().decode("utf-8"))
        script = normalizer.to_script(questions, {}, RenderOptions(read_answer=True))
        for engine in (shipped, plain):
            engine._memo.clear()
            engine.synthesize(script, engine.voices()[index], RenderOptions(), tmp_path / "o.wav")
    letters = {"double you.", "ecks.", "Why.", "Z."}
    assert letters <= set(plain_backend.texts)
    assert shipped_backend.texts == [t for t in plain_backend.texts if t not in letters]


@pytest.mark.parametrize("name", list(ENGINES))
def test_the_read_answer_line_reaches_the_model_unchanged(
    name: str, settings: Settings, tmp_path: Path
) -> None:
    # One segment that only starts with a letter: no clip, no say_letter, as on main.
    make, _, _, index = ENGINES[name]
    engine, backend = make(settings, LetterClips(SHIPPED))

    say(engine, tmp_path / "out.wav", Segment("Answer. W. Pharynx.", 0), voice=index)

    assert backend.texts == ["Answer. W. Pharynx."]


def test_both_engines_moved_to_render_revision_4(settings: Settings) -> None:
    assert qwen(settings, LetterClips(None))[0].version.endswith("+r4")
    assert chatterbox(settings, LetterClips(None))[0].version.endswith("+r4")


def test_the_engines_play_the_shipped_clips_by_default(settings: Settings) -> None:
    assert qwen(settings, None)[0]._clips is letter_clips.CLIPS  # type: ignore[arg-type]
    assert chatterbox(settings, None)[0]._clips is letter_clips.CLIPS  # type: ignore[arg-type]
