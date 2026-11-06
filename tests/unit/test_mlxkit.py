"""cloudyreader.engines.mlxkit: chunking, audio, seeds, file checks, guards, slot, plain text.

No mlx, mlx-audio, transformers or huggingface_hub: every model module is a fake.
"""

from __future__ import annotations

import hashlib
import inspect
import math
import os
import random
import subprocess
import sys
import threading
import types
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from cloudyreader.engines import mlxkit
from cloudyreader.engines.mlxkit import (
    MIN_EST_S,
    RUNAWAY,
    SAMPLE_RATE,
    SHORT_CHARS,
    EngineError,
    EngineUnavailable,
    EngineWarnings,
    ModelFiles,
    ModelSlot,
    chunk_text,
    crop_first_repeat,
    est_seconds,
    mlx_support,
    offline_guard,
    quiet,
    render_text,
    say_letter,
    seed_for,
    silence,
    speakable,
    write_pcm16,
)
from cloudyreader.models import Override, RenderOptions, Segment
from cloudyreader.normalize import CHOICE_PAUSE_MS, LETTER_PAUSE_MS, ScriptNormalizer
from cloudyreader.parser import parse
from tests.unit.pause_probe import FIXTURES, mc_script, read_samples, silent_runs

ROOT = Path(__file__).resolve().parents[2]
HEAVY = ("mlx", "mlx_audio", "transformers", "huggingface_hub", "torch", "tokenizers")


@dataclass(frozen=True)
class Pin:
    """Stands in for engine_catalog.PinnedFile: ModelFiles reads only these three fields."""

    rel: str
    size: int
    sha256: str


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- chunk_text --------------------------------------------------------------------------------

LONG = (
    "The ribosome reads messenger RNA three bases at a time, and each codon, read in order, "
    "selects one amino acid; the growing chain leaves through an exit tunnel. Why? Because the "
    "large subunit catalyzes peptide bond formation without any protein in its active site, which "
    "makes the ribosome a ribozyme. Okazaki fragments, by contrast, form on the lagging strand."
)


def test_chunk_text_keeps_every_word_in_order() -> None:
    for max_chars in (20, 45, 80, 200, 1000):
        chunks = chunk_text(LONG, max_chars=max_chars)
        assert " ".join(chunks).split() == LONG.split()
        assert all(c == " ".join(c.split()) and 0 < len(c) <= max_chars for c in chunks)
    assert chunk_text("  one \n two\tthree  ", max_chars=50) == ["one two three"]
    assert chunk_text(" \n\t ", max_chars=50) == []
    assert chunk_text("", max_chars=50, min_chars=5) == []


def test_chunk_text_splits_long_sentences_at_clauses_then_spaces() -> None:
    text = "One two three, four five six; seven eight nine ten eleven twelve thirteen."
    # Both clauses fit one chunk; the long third clause breaks at a space.
    assert chunk_text(text, max_chars=30) == [
        "One two three, four five six;",
        "seven eight nine ten eleven",
        "twelve thirteen.",
    ]
    # Whole sentences are kept together before any clause break is used.
    two = "Alpha beta gamma, delta. Epsilon zeta eta, theta."
    assert chunk_text(two, max_chars=30) == ["Alpha beta gamma, delta.", "Epsilon zeta eta, theta."]
    # A closing quote or bracket after the stop still ends the sentence.
    quoted = 'He said "stop." Then (we left.) Done now, at last.'
    assert chunk_text(quoted, max_chars=20) == [
        'He said "stop."',
        "Then (we left.)",
        "Done now, at last.",
    ]


def test_chunk_text_cuts_a_word_longer_than_max_chars() -> None:
    word = "a" * 25
    assert chunk_text(f"{word} end", max_chars=10) == ["a" * 10, "a" * 10, "aaaaa end"]


def test_chunk_text_merges_a_short_fragment_inside_one_text() -> None:
    tail = "Alpha beta gamma delta epsi. Yes."  # the sentence is 28 chars
    assert chunk_text(tail, max_chars=30) == ["Alpha beta gamma delta epsi.", "Yes."]
    assert chunk_text(tail, max_chars=30, min_chars=8) == [tail]
    head = "Why? Alpha beta gamma delta epsi."
    assert chunk_text(head, max_chars=30) == ["Why?", "Alpha beta gamma delta epsi."]
    assert chunk_text(head, max_chars=30, min_chars=8) == [head]
    # A fragment of min_chars or more stays apart.
    kept = "Alpha beta gamma delta epsi. Yes sure."
    assert chunk_text(kept, max_chars=30, min_chars=8) == [
        "Alpha beta gamma delta epsi.",
        "Yes sure.",
    ]
    # One text only: a short text is never padded from elsewhere (the letter segment "W.").
    assert chunk_text("W.", max_chars=280, min_chars=20) == ["W."]


def test_chunk_text_takes_text_only_so_a_segment_pause_is_never_its_business() -> None:
    assert list(inspect.signature(chunk_text).parameters) == ["text", "max_chars", "min_chars"]
    letter = Segment("W.", LETTER_PAUSE_MS)
    with pytest.raises(TypeError, match="text"):
        chunk_text(letter, max_chars=280, min_chars=SHORT_CHARS)  # type: ignore[arg-type]
    # Shorter than min_chars, it still comes back alone: no other segment can join it.
    assert chunk_text(letter.text, max_chars=280, min_chars=SHORT_CHARS) == ["W."]


def test_chunk_text_property_words_kept_and_size_bounded() -> None:
    rng = random.Random(7)
    marks = ["", "", "", ",", ";", ":", ".", "!", "?", '."', ".)"]
    for _ in range(300):
        words = ["x" * rng.randint(1, 12) + rng.choice(marks) for _ in range(rng.randint(1, 80))]
        text = " ".join(words)
        max_chars = rng.randint(15, 120)
        min_chars = rng.randint(0, max_chars // 2)
        chunks = chunk_text(text, max_chars=max_chars, min_chars=min_chars)
        assert " ".join(chunks).split() == words
        assert all(len(c) <= max_chars + 2 * (min_chars + 1) for c in chunks)
        if len(chunks) > 1:
            assert all(len(c) >= min_chars for c in chunks)


@pytest.mark.parametrize(("max_chars", "min_chars"), [(0, 0), (10, -1), (10, 6)])
def test_chunk_text_rejects_bad_limits(max_chars: int, min_chars: int) -> None:
    with pytest.raises(ValueError):
        chunk_text("text", max_chars=max_chars, min_chars=min_chars)


# --- est_seconds, seed_for, silence, write_pcm16 ------------------------------------------------


def test_est_seconds_floor_is_one_second() -> None:
    assert est_seconds("W.") == MIN_EST_S == 1.0
    assert est_seconds("") == MIN_EST_S
    assert est_seconds("x" * 14) == MIN_EST_S
    assert est_seconds("x" * 140) == pytest.approx(10.0)
    assert est_seconds("  " + "x" * 28 + "\n") == pytest.approx(2.0)  # outer whitespace is free
    assert est_seconds("x" * 70, chars_per_s=7.0) == pytest.approx(10.0)
    with pytest.raises(ValueError):
        est_seconds("text", chars_per_s=0)


def test_seed_for_varies_with_voice_text_attempt() -> None:
    base = seed_for("chatterbox_turbo:builtin", "W.")
    assert base == seed_for("chatterbox_turbo:builtin", "W.", 0)  # deterministic
    others = {
        seed_for("qwen3_tts:ryan", "W."),
        seed_for("chatterbox_turbo:builtin", "X."),
        seed_for("chatterbox_turbo:builtin", "W.", 1),
        seed_for("chatterbox_turbo:builtin", "W.", 2),
    }
    assert base not in others and len(others) == 4
    seeds = [seed_for("v", f"text {i}", i % 3) for i in range(200)]
    assert all(isinstance(s, int) and 0 <= s < 2**32 for s in seeds)
    assert seed_for("v", "lone surrogate \ud800") == seed_for("v", "lone surrogate \ud800")


def test_silence_is_exact() -> None:
    assert silence(300).shape == (7200,) and silence(300).dtype == np.float32
    assert not silence(300).any()
    assert silence(0).shape == (0,)
    assert silence(7, rate=22_050).shape == (154,)
    with pytest.raises(ValueError):
        silence(-1)


def _read_wav(path: Path) -> tuple[list[int], np.ndarray]:
    with wave.open(str(path)) as w:
        fmt = [w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()]
        return fmt, np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def test_write_pcm16_is_mono_16_bit_and_clips(tmp_path: Path) -> None:
    out = tmp_path / "deep" / "dir" / "out.wav"
    samples = np.array([0.0, 0.5, -0.5, 1.5, -2.0, np.nan, np.inf, -np.inf], dtype=np.float32)
    write_pcm16(out, samples)
    fmt, pcm = _read_wav(out)
    assert fmt == [SAMPLE_RATE, 1, 2, 8]
    assert pcm.tolist() == [0, 16384, -16384, 32767, -32767, 0, 32767, -32767]
    write_pcm16(out, np.full((5, 1), 0.25), rate=16_000)  # a column of one channel is mono
    fmt, pcm = _read_wav(out)
    assert fmt == [16_000, 1, 2, 5] and set(pcm.tolist()) == {8192}
    write_pcm16(out, np.zeros(0, dtype=np.float32))
    assert _read_wav(out)[0] == [SAMPLE_RATE, 1, 2, 0]


def test_write_pcm16_refuses_stereo_and_bad_rates(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mono"):
        write_pcm16(tmp_path / "x.wav", np.zeros((10, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="rate"):
        write_pcm16(tmp_path / "x.wav", np.zeros(10, dtype=np.float32), rate=0)
    assert not (tmp_path / "x.wav").exists()


# --- crop_first_repeat and render_text ---------------------------------------------------------

TONE = 0.25
KEY, VOICE, TITLE = "chatterbox_turbo:builtin", "builtin", "Chatterbox Turbo"


def tone(seconds: float) -> np.ndarray:
    return np.full(round(seconds * SAMPLE_RATE), TONE, dtype=np.float32)


def repeats(copies: int = 3, word_s: float = 0.4, gap_s: float = 0.2) -> np.ndarray:
    """`copies` words of constant tone with digital silence between them."""
    gap = np.zeros(round(gap_s * SAMPLE_RATE), dtype=np.float32)
    parts = [part for _ in range(copies) for part in (tone(word_s), gap)]
    return np.concatenate(parts[:-1])


class ScriptedBackend:
    """TextBackend that answers each render with the next outcome: seconds of tone, an array, or
    an exception to raise."""

    def __init__(self, *outcomes: float | np.ndarray | Exception) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str, int, float]] = []

    def render(
        self, text: str, voice: str, *, seed: int, budget_s: float
    ) -> tuple[np.ndarray, int]:
        self.calls.append((text, voice, seed, budget_s))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return (outcome if isinstance(outcome, np.ndarray) else tone(outcome)), SAMPLE_RATE

    def close(self) -> None:
        pass


def test_crop_first_repeat_cuts_at_the_quiet_gap_and_refuses_without_one() -> None:
    word = tone(0.4)
    noise = np.random.default_rng(3).standard_normal(round(0.2 * SAMPLE_RATE)) * 1e-3
    hush = noise.astype(np.float32)  # a gap with a little noise, not digital silence
    lead = np.zeros(round(0.3 * SAMPLE_RATE), dtype=np.float32)
    audio = np.concatenate([lead, word, hush, word, hush, word])
    first = crop_first_repeat(audio, SAMPLE_RATE)
    assert first is not None and first.dtype == np.float32
    assert len(first) == round(0.8 * SAMPLE_RATE)  # lead, first word, half of the first gap
    assert np.array_equal(first[: len(lead) + len(word)], audio[: len(lead) + len(word)])
    fade = SAMPLE_RATE * 5 // 1000
    assert first[-1] == 0.0
    assert np.all(np.abs(first[-fade:]) <= np.abs(audio[len(first) - fade : len(first)]))
    assert len(crop_first_repeat(repeats(copies=2), SAMPLE_RATE, copies=2)) == round(
        0.5 * SAMPLE_RATE
    )
    # No clear gap: one long sound, digital silence, too little audio, gaps too short.
    assert crop_first_repeat(tone(1.5), SAMPLE_RATE) is None
    assert crop_first_repeat(np.zeros(SAMPLE_RATE, dtype=np.float32), SAMPLE_RATE) is None
    assert crop_first_repeat(tone(0.05), SAMPLE_RATE) is None
    assert crop_first_repeat(repeats(gap_s=0.05), SAMPLE_RATE) is None
    with pytest.raises(ValueError, match="copies"):
        crop_first_repeat(audio, SAMPLE_RATE, copies=1)


def test_render_text_tries_alone_twice_then_repeat_and_crop_then_raises() -> None:
    # A short unit: alone with attempts 0 and 1, then three copies with attempt 2, then crop.
    backend = ScriptedBackend(RuntimeError("generate failed"), 0.05, repeats())
    samples, rate = render_text(backend, KEY, VOICE, "W.", title=TITLE)
    assert [(text, seed) for text, _, seed, _ in backend.calls] == [
        ("W.", seed_for(KEY, "W.", 0)),
        ("W.", seed_for(KEY, "W.", 1)),
        ("W. W. W.", seed_for(KEY, "W.", 2)),
    ]
    assert [call[1] for call in backend.calls] == [VOICE] * 3
    assert [call[3] for call in backend.calls] == [2.0, 2.0, 6.0]  # max(2, 2 x est), 3 copies
    assert rate == SAMPLE_RATE and len(samples) == round(0.5 * SAMPLE_RATE)
    assert samples[0] == TONE and samples[-1] == 0.0
    # A unit without a stop gets one per copy, so the copies come out apart.
    backend = ScriptedBackend(0.0, 0.0, repeats())
    render_text(backend, KEY, VOICE, "Pharynx", title=TITLE)
    assert backend.calls[-1][0] == "Pharynx. Pharynx. Pharynx."
    # The copies run together: no clear gap, so the unit fails; no carrier word is tried.
    backend = ScriptedBackend(0.0, 0.0, 1.5)
    with pytest.raises(EngineError, match=r"^Chatterbox Turbo could not say 'W\.'; try another"):
        render_text(backend, KEY, VOICE, "W.", title=TITLE)
    assert len(backend.calls) == 3
    # SHORT_CHARS or more: three alone attempts, never the repeat.
    text = "Which of the following is a gas giant?"
    assert len(text) >= SHORT_CHARS
    backend = ScriptedBackend(0.0, ValueError("bad"), 0.0)
    with pytest.raises(EngineError, match="could not say 'Which of the following is a gas…'"):
        render_text(backend, KEY, VOICE, text, title=TITLE)
    assert [(call[0], call[2]) for call in backend.calls] == [
        (text, seed_for(KEY, text, attempt)) for attempt in range(3)
    ]
    # The first good attempt wins; an engine that cannot run stops at once.
    backend = ScriptedBackend(0.4)
    assert len(render_text(backend, KEY, VOICE, "W.", title=TITLE)[0]) == round(0.4 * SAMPLE_RATE)
    assert len(backend.calls) == 1
    backend = ScriptedBackend(EngineUnavailable("model gone"), 0.4)
    with pytest.raises(EngineUnavailable, match="model gone"):
        render_text(backend, KEY, VOICE, "W.", title=TITLE)
    assert len(backend.calls) == 1
    with pytest.raises(ValueError, match="text"):
        render_text(backend, KEY, VOICE, " \n ", title=TITLE)


def test_render_text_flags_runaway_at_1_9_times_the_estimate() -> None:
    text = "x" * 42
    assert est_seconds(text) == pytest.approx(3.0) and RUNAWAY == 1.9
    edge = math.ceil(RUNAWAY * 3.0 * SAMPLE_RATE)  # the first length at 1.9 x the estimate
    backend = ScriptedBackend(np.full(edge, TONE, np.float32), np.full(edge - 1, TONE, np.float32))
    samples, _ = render_text(backend, KEY, VOICE, text, title=TITLE)
    assert len(samples) == edge - 1 and len(backend.calls) == 2
    assert backend.calls[0][3] == pytest.approx(6.0)  # max(2.0, 2 x est)
    # A short unit that runs away twice goes on to the repeat.
    backend = ScriptedBackend(1.9, 2.5, repeats())
    assert len(render_text(backend, KEY, VOICE, "W.", title=TITLE)[0]) == round(0.5 * SAMPLE_RATE)
    assert len(backend.calls) == 3


def padded(lead_s: float, speech_s: float, tail_s: float) -> np.ndarray:
    """Tone between digital silences, as a model pads its own audio."""
    hush = [np.zeros(round(s * SAMPLE_RATE), dtype=np.float32) for s in (lead_s, tail_s)]
    return np.concatenate([hush[0], tone(speech_s), hush[1]])


def test_render_text_cuts_each_take_to_its_speech_and_judges_the_cut() -> None:
    # Regression: Qwen3-TTS Ryan pads about 0.45 s before and 0.5 s after the speech. A clean
    # 'Life Science.' (1.12 s said, 2.09 s in all) went over the 1.9 s cut and the unit failed.
    backend = ScriptedBackend(padded(0.45, 1.12, 0.52))
    samples, _ = render_text(backend, KEY, VOICE, "Life Science.", title=TITLE)
    lead, speech, tail = (round(s * SAMPLE_RATE) for s in (0.05, 1.12, 0.08))
    assert len(backend.calls) == 1
    assert len(samples) == lead + speech + tail  # cut to the speech: scripted pauses stay exact
    assert np.all(samples[lead : lead + speech] == TONE) and samples[0] == samples[-1] == 0.0
    # Speech past the cut still runs away, padded or not, and a render with no speech fails.
    silent = np.zeros(SAMPLE_RATE, dtype=np.float32)
    backend = ScriptedBackend(padded(0.45, 1.9, 0.5), silent, repeats())
    samples, _ = render_text(backend, KEY, VOICE, "Life Science.", title=TITLE)
    assert len(samples) == round(0.5 * SAMPLE_RATE) and len(backend.calls) == 3


def test_render_text_memoizes_units_of_three_seconds_or_less(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memo: dict = {}
    backend = ScriptedBackend(0.4, 3.0, 3.01, 3.01, 0.4)
    first, _ = render_text(backend, KEY, VOICE, "W.", title=TITLE, memo=memo)
    again, _ = render_text(backend, KEY, VOICE, " W. ", title=TITLE, memo=memo)
    assert again is first and len(backend.calls) == 1
    assert not first.flags.writeable  # shared by every reading: nobody may change it
    for _ in range(2):
        render_text(backend, KEY, VOICE, "x" * 42, title=TITLE, memo=memo)  # 3.0 s: kept
    assert len(backend.calls) == 2
    for _ in range(2):
        render_text(backend, KEY, VOICE, "y" * 42, title=TITLE, memo=memo)  # 3.01 s: not kept
    assert len(backend.calls) == 4
    render_text(backend, "qwen3_tts:ryan", "ryan", "W.", title="Qwen3-TTS", memo=memo)
    assert len(backend.calls) == 5  # another voice, another entry
    backend = ScriptedBackend(0.4, 0.4)
    for _ in range(2):
        render_text(backend, KEY, VOICE, "W.", title=TITLE)  # no memo: every call renders
    assert len(backend.calls) == 2
    # The memo keeps the MEMO_LIMIT most recently used units.
    monkeypatch.setattr(mlxkit, "MEMO_LIMIT", 2)
    memo = {}
    backend = ScriptedBackend(0.4, 0.4, 0.4)
    for unit in ("W.", "X.", "W.", "Y."):
        render_text(backend, KEY, VOICE, unit, title=TITLE, memo=memo)
    assert list(memo) == [(KEY, "W."), (KEY, "Y.")] and len(backend.calls) == 3


# --- pause_probe -------------------------------------------------------------------------------


def test_silent_runs_keeps_only_runs_of_250_ms_or_more(tmp_path: Path) -> None:
    rate = SAMPLE_RATE
    sound = np.full(100, 7, dtype=np.int16)

    def gap(ms: int) -> np.ndarray:
        return np.zeros(rate * ms // 1000, dtype=np.int16)

    samples = np.concatenate(
        [gap(300), sound, gap(120), sound, gap(250), sound, gap(249), sound, gap(700)]
    )
    assert silent_runs(samples, rate) == [7200, 6000, 16800]  # the 120 ms chunk gap is out
    assert silent_runs(samples, rate, min_ms=100) == [7200, 2880, 6000, 5976, 16800]
    assert silent_runs(np.zeros(0, dtype=np.int16), rate) == []
    assert silent_runs(sound, rate) == []
    # 250 ms at 22,050 Hz is 5,512.5 samples: 5,512 falls short, 5,513 counts.
    odd = np.concatenate([np.zeros(5512, np.int16), sound, np.zeros(5513, np.int16)])
    assert silent_runs(odd, 22_050) == [5513]
    # Through a WAV written by write_pcm16: digital silence stays exactly zero.
    write_pcm16(tmp_path / "x.wav", np.concatenate([tone(0.3), silence(400), tone(0.3)]))
    assert silent_runs(*reversed(read_samples(tmp_path / "x.wav"))) == [9600]


def test_mc_script_reads_both_fixtures_with_letter_pauses() -> None:
    script, questions = mc_script()
    assert sum(1 for q in questions if q.choices) >= 2
    letters = [i for i, seg in enumerate(script.segments) if seg.text in ("W.", "X.", "Y.", "Z.")]
    assert len(letters) == 4 * sum(1 for q in questions if q.choices)
    for i in letters:
        assert script.segments[i].pause_after_ms == LETTER_PAUSE_MS
        assert script.segments[i + 1].pause_after_ms >= CHOICE_PAUSE_MS


# --- speakable ---------------------------------------------------------------------------------


def _respelled(surface: str, respelling: str) -> Override:
    return Override(surface, "ˈx", "respelling", respelling=respelling)


def test_speakable_applies_respelling_and_reports_ipa_only_words() -> None:
    seg = Segment(
        "Pharynx and esophagus; the pharynx, troponin, Okazaki and esophagus again.",
        400,
        (
            _respelled("Pharynx", "FAR-ingks"),
            Override("esophagus", "ɪˈsɑfəɡəs", "lexicon"),
            Override("troponin", "ˈtɹoʊpənɪn", "lexicon"),
            Override("Okazaki", "ˌoʊkəˈzɑki", "iupac"),
            Override("esophagus", "ɪˈsɑfəɡəs", "lexicon"),  # duplicates are reported once
            _respelled("Larynx", "LAR-ingks"),  # not in this segment
            Override("ribozyme", "ˈɹaɪbəzaɪm", "lexicon"),  # not in this segment
        ),
    )
    out = speakable(seg)
    # Whole words, case as given: "pharynx" in lower case is not this override's surface.
    assert (
        out.text == "far-ingks and esophagus; the pharynx, troponin, Okazaki and esophagus again."
    )
    assert out.unspoken == ("esophagus", "troponin", "Okazaki")
    assert out.missing == ("Larynx", "ribozyme")
    assert speakable(seg, style="join").text.startswith("faringks and")
    assert speakable(seg, style="space").text.startswith("far ingks and")


def test_speakable_longest_surface_first_whole_words_and_respelling_cleanup() -> None:
    seg = Segment(
        "sodium chloride and chloride ions; Larynxes and Tee-o-door's Larynx.",
        overrides=(
            _respelled("chloride", "KLOR-ide"),
            _respelled("sodium chloride", "SO-dee-um KLOR-ide"),
            _respelled("Larynx", "LAR-ingks!?"),  # other punctuation is dropped
            _respelled("Tee-o-door's", "TEE-o-DOOR's"),  # apostrophes stay
        ),
    )
    out = speakable(seg)
    assert out.text == "so-dee-um klor-ide and klor-ide ions; Larynxes and tee-o-door's lar-ingks."
    assert out.unspoken == () and out.missing == ()


def test_speakable_without_overrides_or_with_an_empty_respelling() -> None:
    plain = Segment("Earth Science.", 300)
    assert speakable(plain) == mlxkit.Speakable("Earth Science.", (), ())
    # A respelling that is only punctuation says nothing: the printed word stays and is reported.
    seg = Segment("Pharynx.", overrides=(_respelled("Pharynx", "?!"), Override("", "x", "lexicon")))
    assert speakable(seg) == mlxkit.Speakable("Pharynx.", ("Pharynx",), ())
    with pytest.raises(ValueError, match="style"):
        speakable(seg, style="dash")  # type: ignore[arg-type]


# --- say_letter --------------------------------------------------------------------------------


def test_say_letter_spells_w_x_and_y_and_leaves_everything_else() -> None:
    assert [say_letter(f"{c}.") for c in "WXYZ"] == ["double you.", "ecks.", "Why.", "Z."]
    others = ("A.", "V.", "w.", "x.", "y.", "W", "Y!", "WY.", "double you.", "", "X. Pharynx.")
    others += ("Answer. W. Pharynx.", "Q minus W.", "W. H. Bragg shared the prize.")
    assert [say_letter(text) for text in others] == list(others)


def test_every_fixture_choice_letter_is_a_unit_say_letter_knows() -> None:
    # say_letter matches whole segments: the normalizer must keep writing letters as "W.".
    normalizer = ScriptNormalizer()
    for paste in sorted(FIXTURES.glob("*.txt")):
        questions = parse(paste.read_bytes().decode("utf-8"))
        script = normalizer.to_script(questions, {}, RenderOptions(read_answer=True))
        letters = [seg for seg in script.segments if seg.text in ("W.", "X.", "Y.", "Z.")]
        assert len(letters) == sum(len(q.choices) for q in questions), paste.name
        assert {seg.pause_after_ms for seg in letters} <= {LETTER_PAUSE_MS, CHOICE_PAUSE_MS}


# --- ModelFiles --------------------------------------------------------------------------------

FILES = {
    "config.json": b'{"model_type": "fake"}',
    "model.safetensors": b"weights" * 10,
    "speech_tokenizer/model.safetensors": b"speech" * 5,
}


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    root = tmp_path / "models" / "fake_engine"
    for rel, data in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return root


def _pins() -> list[Pin]:
    return [Pin(rel, len(data), _sha(data)) for rel, data in FILES.items()]


def _wreck(root: Path, defect: str) -> None:
    if defect == "missing":
        (root / "model.safetensors").unlink()
    elif defect == "wrong size":
        (root / "config.json").write_bytes(b"{}")
    elif defect == "file symlink":
        (root / "model.safetensors").unlink()
        (root.parent / "elsewhere.safetensors").write_bytes(FILES["model.safetensors"])
        (root / "model.safetensors").symlink_to(root.parent / "elsewhere.safetensors")
    elif defect == "dir symlink":
        real = root.parent / "real_tokenizer"
        (root / "speech_tokenizer").rename(real)
        (root / "speech_tokenizer").symlink_to(real, target_is_directory=True)
    elif defect == "folder symlink":
        real = root.parent / "real_engine"
        root.rename(real)
        root.symlink_to(real, target_is_directory=True)
    elif defect == "unpinned":
        (root / "speech_tokenizer" / "extra.safetensors").write_bytes(b"x")
    elif defect == "not a file":
        (root / "config.json").unlink()
        (root / "config.json").mkdir()
    elif defect == "parent is a file":
        for path in sorted((root / "speech_tokenizer").iterdir()):
            path.unlink()
        (root / "speech_tokenizer").rmdir()
        (root / "speech_tokenizer").write_bytes(b"x")
    else:  # a forbidden suffix such as conds.pt
        (root / defect).write_bytes(b"pickle")


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("missing", "model.safetensors is missing"),
        ("wrong size", "wrong size for config.json (2 B, expected 22 B)"),
        ("file symlink", "model.safetensors is a symlink"),
        ("dir symlink", "speech_tokenizer is a symlink"),
        ("folder symlink", "the model folder is a symlink"),
        ("unpinned", "unpinned weights speech_tokenizer/extra.safetensors"),
        ("not a file", "config.json is not a file"),
        ("parent is a file", "speech_tokenizer/model.safetensors is not a file"),
        ("conds.pt", "unexpected pickle-capable file conds.pt"),
        ("model.pth", "unexpected pickle-capable file model.pth"),
        ("x.pkl", "unexpected pickle-capable file x.pkl"),
        ("x.pickle", "unexpected pickle-capable file x.pickle"),
        ("x.ckpt", "unexpected pickle-capable file x.ckpt"),
        ("pytorch_model.bin", "unexpected pickle-capable file pytorch_model.bin"),
        ("CONDS.PT", "unexpected pickle-capable file CONDS.PT"),
    ],
)
def test_model_files_problem_names_each_defect(model_dir: Path, defect: str, message: str) -> None:
    files = ModelFiles(model_dir, _pins())
    assert files.problem() is None and files.damage() is None and files.missing() == ()
    _wreck(model_dir, defect)
    assert files.problem() == message
    if defect == "missing":
        assert files.damage() is None
        assert files.missing() == (_pins()[1],)
    else:
        assert files.damage() == message and files.missing() == ()


def test_model_files_damage_comes_before_missing_and_absent_folder_is_missing(
    model_dir: Path, tmp_path: Path
) -> None:
    (model_dir / "model.safetensors").unlink()
    (model_dir / "conds.pt").write_bytes(b"pickle")
    assert ModelFiles(model_dir, _pins()).problem() == "unexpected pickle-capable file conds.pt"
    absent = ModelFiles(tmp_path / "nowhere", _pins())
    assert absent.damage() is None and absent.missing() == tuple(_pins())
    assert absent.problem() == "config.json is missing"


@pytest.mark.parametrize("rel", ["../escape.json", "/etc/passwd", "a//b.json", "./x.json", ""])
def test_model_files_refuse_an_unsafe_pinned_name(model_dir: Path, rel: str) -> None:
    files = ModelFiles(model_dir, [*_pins(), Pin(rel, 1, "0" * 64)])
    assert files.problem() == f"unsafe file name {rel!r}"
    assert files.missing() == ()
    assert files.verify() == f"unsafe file name {rel!r}"


def test_model_files_verify_hashes_once_per_file_state(
    model_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mlxkit, "_DIGESTS", {})
    hashed: list[str] = []
    real = mlxkit._sha256_file

    def spy(path: Path) -> str:
        hashed.append(path.relative_to(model_dir).as_posix())
        return real(path)

    monkeypatch.setattr(mlxkit, "_sha256_file", spy)
    assert ModelFiles(model_dir, _pins()).verify() is None
    assert sorted(hashed) == sorted(FILES)
    assert ModelFiles(model_dir, _pins()).verify() is None  # a new instance shares the memo
    assert len(hashed) == 3
    # Same size, new bytes and a new mtime: hashed again, and the mismatch is sticky.
    target = model_dir / "model.safetensors"
    target.write_bytes(b"WEIGHTS" * 10)
    st = target.stat()
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    files = ModelFiles(model_dir, _pins())
    assert files.verify() == "SHA-256 mismatch for model.safetensors"
    assert files.verify() == "SHA-256 mismatch for model.safetensors"
    assert hashed.count("model.safetensors") == 2
    target.write_bytes(FILES["model.safetensors"])
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000))
    assert files.verify() is None
    assert hashed.count("model.safetensors") == 3


def test_model_files_verify_reports_a_stat_problem_without_hashing(
    model_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mlxkit, "_sha256_file", lambda path: pytest.fail("hashed"))
    (model_dir / "config.json").write_bytes(b"{}")
    assert (
        ModelFiles(model_dir, _pins()).verify() == "wrong size for config.json (2 B, expected 22 B)"
    )


def test_model_files_compare_digests_case_insensitively(model_dir: Path) -> None:
    pins = [Pin(p.rel, p.size, p.sha256.upper()) for p in _pins()]
    assert ModelFiles(model_dir, pins).verify() is None


# --- mlx_support -------------------------------------------------------------------------------


def _package(root: Path, dotted: str) -> None:
    """A package tree whose every __init__ raises: finding it must never run it."""
    path = root
    for part in dotted.split("."):
        path = path / part
        path.mkdir(exist_ok=True)
        (path / "__init__.py").write_text(f"raise RuntimeError('executed {part}')\n")


def test_mlx_support_never_imports_mlx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _package(tmp_path, "fake_mlx")
    _package(tmp_path, "fake_audio.tts.models.chatterbox_turbo")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(mlxkit, "_apple_silicon", lambda: True)
    modules = ("fake_mlx", "fake_audio")
    assert mlx_support(modules, "fake_audio.tts.models.chatterbox_turbo") is None
    assert mlx_support(modules, "fake_audio/tts/models/chatterbox_turbo") is None
    assert mlx_support(modules, "fake_audio.tts.models.qwen3_tts") == "not in this build"
    assert mlx_support(modules, "fake_mlx.tts") == "not in this build"
    assert (
        mlx_support(("fake_mlx", "fake_absent_a", "fake_absent_b"), "fake_audio.tts")
        == "backend packages missing: fake_absent_a, fake_absent_b"
    )
    assert not [m for m in sys.modules if m.startswith(("fake_mlx", "fake_audio"))]
    # The real packages, in a fresh interpreter: located, never imported.
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from cloudyreader.engines import mlxkit\n"
        "mlxkit._apple_silicon = lambda: True\n"
        "print(mlxkit.mlx_support(('mlx', 'mlx_audio', 'transformers'),\n"
        "                         'mlx_audio.tts.models.chatterbox_turbo'))\n"
        f"loaded = [m for m in {HEAVY!r} if m in sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_mlx_support_counts_loaded_modules_and_blocked_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mlxkit, "_apple_silicon", lambda: True)
    fake = types.ModuleType("fake_loaded")  # no __spec__, no __path__, like a test double
    monkeypatch.setitem(sys.modules, "fake_loaded", fake)
    monkeypatch.setitem(sys.modules, "fake_loaded.sub.pkg", types.ModuleType("fake_loaded.sub.pkg"))
    monkeypatch.setitem(sys.modules, "fake_blocked", None)
    assert mlx_support(("fake_loaded",), "fake_loaded.sub.pkg") is None
    assert mlx_support(("fake_loaded",), "fake_loaded.other") == "not in this build"
    assert mlx_support(("fake_blocked",), "fake_loaded.sub.pkg") == (
        "backend packages missing: fake_blocked"
    )
    assert mlx_support(("fake_loaded",), "fake_blocked.sub") == "not in this build"


def test_mlx_support_skips_finders_that_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Raising:
        def find_spec(self, name: str, path: object = None, target: object = None) -> None:
            raise ImportError(f"broken finder: {name}")

    _package(tmp_path, "fake_found.sub")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(mlxkit, "_apple_silicon", lambda: True)
    monkeypatch.setattr(sys, "meta_path", [object(), Raising(), *sys.meta_path])
    assert mlx_support(("fake_found",), "fake_found.sub") is None
    assert not [m for m in sys.modules if m.startswith("fake_found")]


def test_mlx_support_in_an_app_bundle_says_not_in_this_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An .app built without engines lacks transformers: nothing the user could install.
    monkeypatch.setattr(mlxkit, "_apple_silicon", lambda: True)
    monkeypatch.setitem(sys.modules, "fake_absent_pkg", None)
    assert mlx_support(("fake_absent_pkg",), "json.decoder").startswith("backend packages missing")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert mlx_support(("fake_absent_pkg",), "json.decoder") == "not in this build"
    assert mlx_support(("os",), "json.decoder") is None


def test_mlx_support_needs_apple_silicon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert mlx_support(("os",), "json.decoder") == "needs an Apple Silicon Mac (arm64)"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(mlxkit.platform, "machine", lambda: "x86_64")
    assert mlx_support(("os",), "json.decoder") == "needs an Apple Silicon Mac (arm64)"
    monkeypatch.setattr(mlxkit.platform, "machine", lambda: "arm64")
    assert mlx_support(("os",), "json.decoder") is None


# --- EngineWarnings ----------------------------------------------------------------------------


def test_engine_warnings_are_per_thread_and_deduplicated() -> None:
    notes = EngineWarnings()
    assert notes.snapshot() == []
    notes.add("a")
    notes.add("b")
    notes.add("a")
    assert notes.snapshot() == ["a", "b"]
    seen: list[list[str]] = []

    def other() -> None:
        notes.add("c")
        seen.append(notes.snapshot())

    thread = threading.Thread(target=other)
    thread.start()
    thread.join()
    assert seen == [["c"]] and notes.snapshot() == ["a", "b"]
    notes.snapshot().append("x")  # a copy
    assert notes.snapshot() == ["a", "b"]
    notes.reset()
    assert notes.snapshot() == []


# --- offline_guard and quiet -------------------------------------------------------------------

HUB_NAMES = (
    "huggingface_hub",
    "huggingface_hub.constants",
    "huggingface_hub.file_download",
    "huggingface_hub._snapshot_download",
    "mlx_audio",
    "mlx_audio.utils",
)


@pytest.fixture
def no_hub(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Hide any real copy of the watched modules; put everything back afterwards."""
    saved = {name: sys.modules.pop(name) for name in HUB_NAMES if name in sys.modules}
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "0")
    yield
    for name in HUB_NAMES:
        sys.modules.pop(name, None)
    sys.modules.update(saved)


def _fake_hub() -> types.SimpleNamespace:
    """Watched modules already loaded, as after the backend's own imports (no_hub cleans up)."""
    calls: list[str] = []

    def snapshot_download(*args: object, **kwargs: object) -> str:
        calls.append("snapshot_download")
        return "/downloaded"

    def hf_hub_download(*args: object, **kwargs: object) -> str:
        calls.append("hf_hub_download")
        return "/downloaded"

    hub = types.ModuleType("huggingface_hub")
    hub.snapshot_download = snapshot_download  # hf_hub_download stays lazy, as in the real one
    constants = types.ModuleType("huggingface_hub.constants")
    constants.HF_HUB_OFFLINE = False
    file_download = types.ModuleType("huggingface_hub.file_download")
    file_download.hf_hub_download = hf_hub_download
    utils = types.ModuleType("mlx_audio.utils")
    utils.snapshot_download = snapshot_download
    for module in (hub, constants, file_download, utils):
        sys.modules[module.__name__] = module
    return types.SimpleNamespace(
        calls=calls,
        hub=hub,
        constants=constants,
        file_download=file_download,
        utils=utils,
        snapshot_download=snapshot_download,
        hf_hub_download=hf_hub_download,
    )


def test_offline_guard_blocks_hf_downloads_and_restores_state(no_hub: None) -> None:
    fake = _fake_hub()
    meta_path = list(sys.meta_path)
    with offline_guard():
        assert os.environ["HF_HUB_OFFLINE"] == "1" and os.environ["TRANSFORMERS_OFFLINE"] == "1"
        assert fake.constants.HF_HUB_OFFLINE is True
        from huggingface_hub import hf_hub_download  # resolved at call time, as mlx-audio does

        stubs = [
            fake.hub.snapshot_download,
            hf_hub_download,
            fake.file_download.hf_hub_download,
            fake.utils.snapshot_download,
        ]
        for stub in stubs:
            with pytest.raises(EngineUnavailable, match="blocked"):
                stub("mlx-community/S3TokenizerV2", filename="model.safetensors")
    assert fake.calls == []
    assert "HF_HUB_OFFLINE" not in os.environ and os.environ["TRANSFORMERS_OFFLINE"] == "0"
    assert fake.constants.HF_HUB_OFFLINE is False
    assert fake.hub.snapshot_download is fake.snapshot_download
    assert "hf_hub_download" not in vars(fake.hub)  # lazy again
    assert fake.file_download.hf_hub_download is fake.hf_hub_download
    assert fake.utils.snapshot_download is fake.snapshot_download
    assert sys.meta_path == meta_path


def test_offline_guard_restores_on_error_and_nests(no_hub: None) -> None:
    fake = _fake_hub()
    meta_path = list(sys.meta_path)
    with pytest.raises(KeyError), offline_guard():
        with offline_guard():
            assert fake.constants.HF_HUB_OFFLINE is True
        assert fake.constants.HF_HUB_OFFLINE is True  # the outer guard still holds
        with pytest.raises(EngineUnavailable):
            fake.utils.snapshot_download("repo")
        raise KeyError("boom")
    assert fake.constants.HF_HUB_OFFLINE is False
    assert fake.utils.snapshot_download is fake.snapshot_download
    assert "HF_HUB_OFFLINE" not in os.environ and sys.meta_path == meta_path


def test_offline_guard_patches_modules_imported_inside_it(
    no_hub: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = tmp_path / "huggingface_hub"
    hub.mkdir()
    (hub / "__init__.py").write_text(
        "CALLS = []\n"
        "def snapshot_download(*a, **k):\n    CALLS.append('snapshot_download')\n    return 'd'\n"
        "def hf_hub_download(*a, **k):\n    CALLS.append('hf_hub_download')\n    return 'd'\n"
    )
    (hub / "constants.py").write_text(
        "import os\nHF_HUB_OFFLINE = os.environ.get('HF_HUB_OFFLINE') == '1'\n"
    )
    (tmp_path / "mlx_audio").mkdir()
    (tmp_path / "mlx_audio" / "__init__.py").write_text("")
    (tmp_path / "mlx_audio" / "utils.py").write_text(
        "from huggingface_hub import snapshot_download\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    with offline_guard():
        import huggingface_hub
        import huggingface_hub.constants
        import mlx_audio.utils

        assert huggingface_hub.constants.HF_HUB_OFFLINE is True
        blocked = (
            huggingface_hub.snapshot_download,
            huggingface_hub.hf_hub_download,
            mlx_audio.utils.snapshot_download,
        )
        for stub in blocked:
            with pytest.raises(EngineUnavailable, match="blocked"):
                stub("mlx-community/S3TokenizerV2")
        for module in (huggingface_hub, mlx_audio.utils):  # each keeps its real loader
            assert module.__loader__ is module.__spec__.loader
            assert type(module.__loader__).__name__ == "SourceFileLoader"
    assert huggingface_hub.snapshot_download("repo") == "d"  # its own functions come back
    assert huggingface_hub.CALLS == ["snapshot_download"]
    # Bound to the stub while it loaded inside the guard: it stays blocked.
    with pytest.raises(EngineUnavailable):
        mlx_audio.utils.snapshot_download("repo")


def test_quiet_discards_model_output(capsys: pytest.CaptureFixture[str]) -> None:
    with quiet():
        print("Generating: the pasted question")
        sys.stderr.write("100%|##########| 12/12\n")
    print("after")
    assert capsys.readouterr() == ("after\n", "")
    with pytest.raises(ValueError), quiet():
        raise ValueError("model failed")
    sys.stderr.write("restored\n")
    assert capsys.readouterr().err == "restored\n"


# --- ModelSlot ---------------------------------------------------------------------------------


def test_model_slot_closes_the_previous_owner() -> None:
    slot = ModelSlot(capacity=1)
    closed: list[str] = []
    slot.acquire("chatterbox_turbo", lambda: closed.append("chatterbox_turbo"))
    slot.acquire("qwen3_tts", lambda: closed.append("qwen3_tts"))
    assert closed == ["chatterbox_turbo"]
    slot.acquire("qwen3_tts", lambda: closed.append("qwen3_tts"))  # the owner never closes itself
    assert closed == ["chatterbox_turbo"]
    slot.acquire("chatterbox_turbo", lambda: closed.append("chatterbox_turbo"))
    assert closed == ["chatterbox_turbo", "qwen3_tts"]
    slot.release("chatterbox_turbo")  # unloaded itself: nothing left to close
    slot.release("never_acquired")
    slot.acquire("qwen3_tts", lambda: closed.append("qwen3_tts"))
    assert closed == ["chatterbox_turbo", "qwen3_tts"]


def test_model_slot_capacity_follows_ram_and_evicts_the_oldest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gib = 1 << 30
    assert ModelSlot(ram_bytes=24 * gib).capacity == 2
    assert ModelSlot(ram_bytes=24 * gib - 1).capacity == 1
    assert ModelSlot(capacity=1, ram_bytes=64 * gib).capacity == 1  # an explicit capacity wins
    monkeypatch.setattr(mlxkit, "_ram_bytes", lambda: 32 * gib)
    assert ModelSlot().capacity == 2
    monkeypatch.setattr(mlxkit, "_ram_bytes", lambda: 8 * gib)
    assert ModelSlot().capacity == 1
    slot = ModelSlot(ram_bytes=24 * gib)
    closed: list[str] = []
    for owner in ("a", "b", "c", "b", "d"):
        slot.acquire(owner, lambda owner=owner: closed.append(owner))
    assert closed == ["a", "c"]  # re-acquiring b made c the oldest
    with pytest.raises(ValueError):
        ModelSlot(capacity=0)


def test_ram_bytes_reads_the_machine_and_falls_back_to_one_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ram = mlxkit._ram_bytes()
    assert ram > 0
    assert mlxkit.SLOT.capacity == (2 if ram >= 24 << 30 else 1)

    def broken(name: str) -> int:
        raise ValueError(f"unknown sysconf name {name}")

    monkeypatch.setattr(mlxkit.os, "sysconf", broken)
    assert mlxkit._ram_bytes() == 0 and ModelSlot().capacity == 1


def test_model_slot_close_may_call_back_into_the_slot_and_may_fail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail() -> None:
        raise RuntimeError("close failed")

    slot = ModelSlot(capacity=1)
    slot.acquire("a", lambda: slot.release("a"))  # as an engine's close() does: no deadlock
    slot.acquire("b", fail)
    slot.acquire("c", lambda: None)  # b's failure is logged; c still gets the slot
    assert "could not close" in caplog.text and "'b'" in caplog.text


def test_model_slot_serializes_loads() -> None:
    slot = ModelSlot()
    entered = threading.Event()

    def load() -> None:
        with slot:
            entered.set()

    with slot as held:
        assert held is slot
        with slot:  # re-entrant on the loading thread
            pass
        thread = threading.Thread(target=load)
        thread.start()
        assert not entered.wait(0.1)
    assert entered.wait(5)
    thread.join()


# --- import weight -----------------------------------------------------------------------------


def test_import_loads_no_mlx_transformers_huggingface_hub_torch() -> None:
    # numpy is allowed, with whatever it loads itself (its Cython runtime modules, for one).
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import numpy\n"
        "before = set(sys.modules)\n"
        "import cloudyreader.engines.mlxkit\n"
        "new = {name.partition('.')[0] for name in set(sys.modules) - before}\n"
        "foreign = sorted(new - set(sys.stdlib_module_names) - {'cloudyreader'})\n"
        "assert not foreign, foreign\n"
        f"loaded = [m for m in {HEAVY!r} if m in sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
