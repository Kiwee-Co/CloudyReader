"""Voice padding at the choice-letter pause: cut to PAD_S there, every other edge kept."""

from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import numpy as np
import pytest

from cloudyreader.engines import kokoro
from cloudyreader.engines.kokoro import SAMPLE_RATE as KOKORO_RATE
from cloudyreader.engines.kokoro import KokoroEngine
from cloudyreader.engines.padding import (
    FLOOR_DB,
    PAD_S,
    WINDOW_S,
    audible_span,
    is_choice_letter,
    trim_letter_padding,
)
from cloudyreader.engines.piper import PiperEngine
from cloudyreader.models import RenderOptions, Segment, SpokenScript, VoiceInfo
from cloudyreader.normalize import (
    CHOICE_PAUSE_MS,
    LETTER_PAUSE_MS,
    STEM_PAUSE_MS,
    ScriptNormalizer,
)
from cloudyreader.parser import parse

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "questions" / "36-general-science-barometer-mc.txt"
RATE = 24_000
WINDOW = round(RATE * WINDOW_S)
PAD = round(RATE * PAD_S)
PIPER_RATE = 22050
SYMBOLS = " ,.!?:;ˈˌːabdefhiklmnoprstuvwzæɑɔəɛɪɹɡŋʃʊʌθðɚ"  # as test_piper_engine.py
LEAD_WINDOWS, TRAIL_WINDOWS = 38, 46  # about what Kokoro pads each line with, in 10 ms windows


def sine(count: int, level: float = 0.5) -> np.ndarray:
    return level * np.sin(2 * np.pi * 440 * np.arange(count) / RATE)


def padded(lead: int, body: np.ndarray, trail: int) -> np.ndarray:
    return np.concatenate([np.zeros(lead), body, np.zeros(trail)]).astype(np.float32)


# --- audible_span ----------------------------------------------------------------------------


def test_silence_tone_silence_keeps_the_tone_and_one_pad_each_side():
    x = padded(40 * WINDOW, sine(20 * WINDOW), 50 * WINDOW)

    assert audible_span(x, RATE) == (40 * WINDOW - PAD, 60 * WINDOW + PAD)


def test_off_the_window_grid_at_most_one_window_more_than_the_pad_is_kept():
    lead, body = 40 * WINDOW + 37, 20 * WINDOW + 1
    x = padded(lead, sine(body), 9000)

    start, end = audible_span(x, RATE)

    assert PAD <= lead - start < PAD + WINDOW
    assert PAD <= end - (lead + body) < PAD + WINDOW


def test_all_silence_is_left_whole():
    x = np.zeros(30 * WINDOW, dtype=np.float32)

    assert audible_span(x, RATE) == (0, len(x))


def test_no_samples_give_an_empty_span():
    assert audible_span(np.zeros(0, dtype=np.float32), RATE) == (0, 0)


def test_a_segment_shorter_than_the_pad_is_left_whole():
    x = padded(WINDOW // 2, sine(WINDOW), WINDOW // 2)
    assert len(x) < PAD

    assert audible_span(x, RATE) == (0, len(x))


def test_a_tone_from_sample_zero_keeps_its_first_sample():
    x = padded(0, sine(20 * WINDOW), 40 * WINDOW)

    assert audible_span(x, RATE) == (0, 20 * WINDOW + PAD)


def test_a_soft_onset_under_the_floor_survives_inside_the_pad():
    soft = sine(PAD - WINDOW, level=0.5 * 10 ** ((FLOOR_DB - 6) / 20))
    x = padded(40 * WINDOW, np.concatenate([soft, sine(20 * WINDOW)]), 40 * WINDOW)

    start, _ = audible_span(x, RATE)

    assert start <= 40 * WINDOW  # every sample of the soft onset is kept


def test_a_noise_floor_far_under_the_speech_counts_as_padding():
    noise = np.random.default_rng(7).normal(0.0, 0.5 * 10 ** (-70 / 20), 40 * WINDOW)
    x = np.concatenate([noise, sine(20 * WINDOW), noise]).astype(np.float32)

    assert audible_span(x, RATE) == (40 * WINDOW - PAD, 60 * WINDOW + PAD)


def test_the_floor_is_relative_so_a_quiet_voice_is_trimmed_like_a_loud_one():
    loud = padded(40 * WINDOW, sine(20 * WINDOW), 40 * WINDOW)

    assert audible_span(loud * np.float32(1e-3), RATE) == audible_span(loud, RATE)


def test_int16_samples_give_the_float_span_even_at_full_scale():
    x = padded(40 * WINDOW, sine(20 * WINDOW, level=1.0), 40 * WINDOW)
    pcm = np.clip(np.rint(x * 32768.0), -32768, 32767).astype(np.int16)
    pcm[40 * WINDOW + 5] = -32768  # abs() and squares overflow in int16 arithmetic

    assert audible_span(pcm, RATE) == audible_span(x, RATE)


# --- is_choice_letter and trim_letter_padding ---------------------------------------------------


@pytest.mark.parametrize(
    ("text", "pause", "expected"),
    [
        ("W.", LETTER_PAUSE_MS, True),
        ("Z.", LETTER_PAUSE_MS, True),
        ("W.", CHOICE_PAUSE_MS, False),  # a letter without choice text, or a choice reading "W."
        ("A.", LETTER_PAUSE_MS, False),
        ("W. Anemometer", LETTER_PAUSE_MS, False),
        ("Anemometer", LETTER_PAUSE_MS, False),
    ],
)
def test_is_choice_letter(text, pause, expected):
    assert is_choice_letter(Segment(text, pause)) is expected


def test_only_the_letter_tail_and_the_head_of_its_text_are_trimmed():
    segments = [
        Segment("Which one?", STEM_PAUSE_MS),
        Segment("W.", LETTER_PAUSE_MS),
        Segment("Anemometer", CHOICE_PAUSE_MS),
        Segment("X.", CHOICE_PAUSE_MS),  # no choice text: the next letter follows
        Segment("Y.", LETTER_PAUSE_MS),
        Segment("Hygrometer", CHOICE_PAUSE_MS),
        Segment("Z.", LETTER_PAUSE_MS),  # last segment: no text to pull closer
    ]
    body = sine(20 * WINDOW).astype(np.float32)
    lead, trail = LEAD_WINDOWS * WINDOW, TRAIL_WINDOWS * WINDOW
    speech = [padded(lead, body, trail) for _ in segments]

    out = trim_letter_padding(segments, speech, RATE)

    kept = [
        (lead, trail),
        (lead, PAD),
        (PAD, trail),
        (lead, trail),
        (lead, PAD),
        (PAD, trail),
        (lead, trail),
    ]
    for got, (keep_lead, keep_trail) in zip(out, kept, strict=True):
        assert got.dtype == np.float32
        assert len(got) == keep_lead + len(body) + keep_trail
        np.testing.assert_array_equal(got[keep_lead : keep_lead + len(body)], body)
    assert all(len(s) == lead + len(body) + trail for s in speech)  # the input is not changed


# --- the join in each engine, with fake voices that pad like Kokoro ---------------------------


def _script() -> SpokenScript:
    questions = parse(FIXTURE.read_bytes().decode("utf-8"))
    return ScriptNormalizer().to_script(questions, {}, RenderOptions())


class PaddingKokoroBackend:
    """One window of constant sound per character, wrapped in Kokoro-sized zero padding."""

    last_skipped: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.spoken = 0  # samples of sound produced, padding excluded

    def synthesize_line(self, text: str, voice: str, speed: float) -> tuple[np.ndarray, int]:
        window = round(KOKORO_RATE * WINDOW_S)
        body = np.full(len(text) * window, 0.25)
        self.spoken += len(body)
        return padded(LEAD_WINDOWS * window, body, TRAIL_WINDOWS * window), KOKORO_RATE

    def close(self) -> None:
        pass


class PaddingChunk:
    def __init__(self, samples: np.ndarray) -> None:
        self.sample_rate = PIPER_RATE
        self.audio_int16_bytes = samples.tobytes()


class PaddingPiperVoice:
    """piper.PiperVoice stand-in: one chunk per call, constant sound inside zero padding."""

    def __init__(self) -> None:
        self.spoken = 0

    def synthesize(self, text: str, syn_config: object = None):
        window = round(PIPER_RATE * WINDOW_S)
        body = np.full(len(text) * window, 1000, dtype=np.int16)
        self.spoken += len(body)
        lead, trail = (np.zeros(n * window, dtype=np.int16) for n in (LEAD_WINDOWS, TRAIL_WINDOWS))
        yield PaddingChunk(np.concatenate([lead, body, trail]))


Built = tuple[KokoroEngine | PiperEngine, VoiceInfo, PaddingKokoroBackend | PaddingPiperVoice]


def _kokoro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Built:
    snap = tmp_path / "models" / "kokoro"
    (snap / "voices").mkdir(parents=True)
    files = {"config.json": b'{"vocab": {}}', "kokoro-v1_0.safetensors": b"weights"}
    for rel, data in files.items():
        (snap / rel).write_bytes(data)
    (snap / "voices" / "af_heart.safetensors").write_bytes(b"voice af_heart")
    sha = {rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()}
    heart = hashlib.sha256(b"voice af_heart").hexdigest()
    monkeypatch.setattr(kokoro, "MODEL_SHA256", sha)
    monkeypatch.setattr(kokoro, "VOICE_SHA256", {**kokoro.VOICE_SHA256, "af_heart": heart})
    monkeypatch.setattr(kokoro, "_supported_platform", lambda: True)
    backend = PaddingKokoroBackend()
    engine = KokoroEngine(tmp_path / "models", backend)
    return engine, next(v for v in engine.voices() if v.key == "kokoro:af_heart"), backend


def _piper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Built:
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "en_US-fake-medium.onnx").write_bytes(b"not a real model")
    config = {
        "audio": {"sample_rate": PIPER_RATE, "quality": "medium"},
        "espeak": {"voice": "en-us"},
        "inference": {"noise_scale": 0.667, "length_scale": 1.0, "noise_w": 0.8},
        "phoneme_type": "espeak",
        "phoneme_id_map": {s: [i] for i, s in enumerate(SYMBOLS)},
        "num_symbols": len(SYMBOLS),
        "num_speakers": 1,
        "speaker_id_map": {},
        "language": {"code": "en_US"},
    }
    (voices / "en_US-fake-medium.onnx.json").write_text(json.dumps(config), encoding="utf-8")
    fake = PaddingPiperVoice()
    engine = PiperEngine(voices, loader=lambda model, config: fake)
    (voice,) = engine.voices()
    return engine, voice, fake


def _zero_runs(samples: np.ndarray) -> list[int]:
    edges = np.flatnonzero(np.diff(np.concatenate(([0], samples == 0, [0])).astype(np.int8)))
    return (edges[1::2] - edges[::2]).tolist()


@pytest.mark.parametrize("build", [_kokoro, _piper], ids=["kokoro", "piper"])
def test_letter_gap_is_the_pause_plus_two_pads_and_every_other_gap_is_unchanged(
    build, tmp_path, monkeypatch
):
    engine, voice, fake = build(tmp_path, monkeypatch)
    script = _script()
    segments = script.segments
    assert [s.text for s in segments if is_choice_letter(s)] == ["W.", "X.", "Y.", "Z."]

    audio = engine.synthesize(script, voice, RenderOptions(), tmp_path / "q.wav")

    with wave.open(str(tmp_path / "q.wav"), "rb") as wav:
        rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    window, pad = round(rate * WINDOW_S), round(rate * PAD_S)
    lead, trail = LEAD_WINDOWS * window, TRAIL_WINDOWS * window

    def pause(segment: Segment) -> int:
        return round(rate * segment.pause_after_ms / 1000)

    gaps = [lead]  # before the first segment: no letter boundary, untouched
    for this in segments[:-1]:
        letter = is_choice_letter(this)
        gaps.append((pad if letter else trail) + pause(this) + (pad if letter else lead))
    gaps.append(trail + pause(segments[-1]))
    assert _zero_runs(samples) == gaps
    assert gaps[segments.index(Segment("W.", LETTER_PAUSE_MS)) + 1] == (
        2 * pad + round(rate * LETTER_PAUSE_MS / 1000)
    )
    assert np.count_nonzero(samples) == fake.spoken  # no sound sample was cut
    assert audio.duration_s == pytest.approx(len(samples) / rate)
