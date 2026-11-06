"""Verified clips of the lone choice letters, for the voices that read a bare letter as a word.

Said alone, "Z." comes out of Qwen3-TTS (Ryan, Aiden) and Chatterbox Turbo as "see" or "the one"
on some seeds, and no spelling fixes that. scripts/make_letter_clips.py renders takes through the
engines; the takes two recognizers heard as the letter's name sit in letter_clips/<engine>/<voice>/
with manifest.json. An engine plays the clip instead of rendering the letter, so the letter sounds
the same on every machine. A clip that is missing or fails its SHA-256 is skipped with a warning,
and the engine renders the letter as before (mlxkit.say_letter).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import threading
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from cloudyreader.frozen import bundle_resources_dir, is_frozen
from cloudyreader.models import Segment

log = logging.getLogger(__name__)

FOLDER = "letter_clips"
MANIFEST = "manifest.json"
LETTERS = "WXYZ"
_NAME = re.compile(r"[a-z0-9_]+")  # an engine or voice id: one path part inside the folder
_SHA256 = re.compile(r"[0-9a-f]{64}")


def clips_dir() -> Path | None:
    """The clip folder: a frozen app's copy under Contents/Resources, else the package's own."""
    if is_frozen():
        resources = bundle_resources_dir()
        return None if resources is None else resources / "cloudyreader" / "engines" / FOLDER
    return Path(__file__).with_name(FOLDER)


def lone_letter(segment: Segment) -> str | None:
    """The letter of a lone choice letter as the normalizer writes it ("W.", no overrides), else
    None. Any pause: a choice without text has a longer one than a letter before its text."""
    text = segment.text
    if len(text) == 2 and text[0] in LETTERS and text[1] == "." and not segment.overrides:
        return text[0]
    return None


def _pcm(data: bytes) -> tuple[np.ndarray, int]:
    """Float32 samples and rate of a 16-bit mono PCM WAV, scaled as mlxkit.write_pcm16 wrote it."""
    with wave.open(io.BytesIO(data), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError("not 16-bit mono PCM")
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32767.0, rate


def _resample(samples: np.ndarray, rate: int, target: int) -> np.ndarray:
    """Linear interpolation to `target` Hz: only for an engine that stops speaking at 24 kHz."""
    count = round(len(samples) * target / rate)
    where = np.arange(count, dtype=np.float64) * rate / target
    return np.interp(where, np.arange(len(samples)), samples).astype(np.float32)


def _entry(item: Any) -> tuple[tuple[str, str, str], dict[str, Any]] | None:
    """(engine, voice, letter) and the checked fields of one manifest entry, None if malformed."""
    if not isinstance(item, dict):
        return None
    engine, voice, letter = item.get("engine"), item.get("voice"), item.get("letter")
    rate, frames, sha256 = item.get("rate"), item.get("frames"), item.get("sha256")
    if not all(isinstance(v, str) and _NAME.fullmatch(v) for v in (engine, voice)):
        return None
    if not (isinstance(letter, str) and len(letter) == 1 and letter in LETTERS):
        return None
    if not all(type(v) is int and v > 0 for v in (rate, frames)):
        return None
    if not (isinstance(sha256, str) and _SHA256.fullmatch(sha256)):
        return None
    return (engine, voice, letter), {"rate": rate, "frames": frames, "sha256": sha256}


class LetterClips:
    """The clips of one folder: the manifest read on first use, each clip read, hashed and checked
    once per rate. Thread-safe. A failure is logged once and then means "no clip"."""

    def __init__(self, folder: Path | Callable[[], Path | None] | None = clips_dir) -> None:
        self._folder = folder
        self._lock = threading.Lock()
        self._root: Path | None = None
        self._entries: dict[tuple[str, str, str], dict[str, Any]] | None = None
        self._clips: dict[tuple[str, str, str, int], np.ndarray | None] = {}

    def get(self, engine: str, voice: str, segment: Segment, rate: int) -> np.ndarray | None:
        """The clip for a lone-letter segment in this voice at `rate` Hz (read-only), else None:
        any other segment, a voice or letter without a clip, or a clip that failed its checks."""
        letter = lone_letter(segment)
        if letter is None:
            return None
        key = (engine, voice, letter, rate)
        with self._lock:
            if key not in self._clips:
                self._clips[key] = self._load(engine, voice, letter, rate)
            return self._clips[key]

    def _manifest(self) -> dict[tuple[str, str, str], dict[str, Any]]:
        if self._entries is not None:
            return self._entries
        self._entries = {}
        folder = self._folder() if callable(self._folder) else self._folder
        if folder is None:
            return self._entries
        self._root = Path(folder)
        try:
            items = json.loads((self._root / MANIFEST).read_text(encoding="utf-8"))["clips"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("no letter clips: %s unreadable (%s)", MANIFEST, type(exc).__name__)
            return self._entries
        for item in items if isinstance(items, list) else ():
            if (entry := _entry(item)) is None:
                log.warning("letter clips: skipped a malformed %s entry", MANIFEST)
            else:
                self._entries[entry[0]] = entry[1]
        return self._entries

    def _load(self, engine: str, voice: str, letter: str, rate: int) -> np.ndarray | None:
        entry = self._manifest().get((engine, voice, letter))
        if entry is None or self._root is None:
            return None  # this voice has no clip for the letter: the engine renders it
        rel = f"{engine}/{voice}/{letter}.wav"
        try:
            data = (self._root / rel).read_bytes()
        except OSError as exc:
            log.warning("letter clip %s unreadable (%s): rendering it", rel, type(exc).__name__)
            return None
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            log.warning("letter clip %s fails its SHA-256: rendering it", rel)
            return None
        try:
            samples, clip_rate = _pcm(data)
        except (wave.Error, EOFError, ValueError) as exc:
            log.warning("letter clip %s is no 16-bit mono WAV (%s): rendering it", rel, exc)
            return None
        if clip_rate != entry["rate"] or len(samples) != entry["frames"]:
            log.warning("letter clip %s disagrees with %s: rendering it", rel, MANIFEST)
            return None
        if clip_rate != rate:
            samples = _resample(samples, clip_rate, rate)
        samples.flags.writeable = False  # shared by every reading of this letter
        return samples


CLIPS = LetterClips()  # the shipped clips; nothing is read until an engine asks for one
