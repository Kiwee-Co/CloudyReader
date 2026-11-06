"""Chatterbox Turbo (the 4-bit MLX build, Apple Silicon only) as an optional plain-text TTS engine.

ChatterboxTurboEngine owns availability, the voice row, text prep, chunking and WAV assembly; each
chunk goes through mlxkit.render_text (the short-unit ladder). A TextBackend turns one chunk into
audio, so the engine runs against a fake in tests and against MlxChatterboxBackend in the app. The
model reads plain text, so overrides reach it through `speakable` (respelling or printed word). It
has one built-in voice and no cloning: the backend never passes reference audio.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.metadata
import logging
import math
import re
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from cloudyreader import engine_catalog
from cloudyreader.config import Settings
from cloudyreader.engine_catalog import Assessment, Pinned, PinnedFile
from cloudyreader.engines.mlxkit import (
    INTER_CHUNK_MS,
    MAX_SCRIPT_CHARS,
    SAMPLE_RATE,
    SHORT_CHARS,
    SLOT,
    EngineError,
    EngineUnavailable,
    EngineWarnings,
    ModelFiles,
    ModelSlot,
    TextBackend,
    chunk_text,
    mlx_support,
    offline_guard,
    quiet,
    render_text,
    say_letter,
    silence,
    speakable,
    write_pcm16,
)
from cloudyreader.models import Audio, RenderOptions, Segment, SpokenScript, VoiceInfo

log = logging.getLogger(__name__)

KEY = "chatterbox_turbo"
TITLE = "Chatterbox Turbo"
VOICE_ID = "builtin"
VOICE_KEY = f"{KEY}:{VOICE_ID}"
MODEL_TYPE = "chatterbox_turbo"  # mlx-audio's model folder; a Path load never downloads
# find_spec and a path check only: importing mlx_audio.tts loads mlx.core, which takes seconds.
BACKEND_MODULES = ("mlx", "mlx_audio", "transformers")
BACKEND_SUBPACKAGE = "mlx_audio.tts.models.chatterbox_turbo"
LOAD_HINT = f"loading {TITLE} (first use only)"

# Sampling: explicit, so an mlx-audio default change cannot alter the audio behind the cache key.
TEMPERATURE, TOP_K, TOP_P, REPETITION_PENALTY = 0.8, 1000, 0.95, 1.2
SAMPLING_TAG = f"t{TEMPERATURE}k{TOP_K}p{TOP_P}r{REPETITION_PENALTY}"
RESPELLING_STYLE = "hyphen"
MAX_CHUNK_CHARS = 280  # about 20 s: Turbo drifts past 25 to 30 s of audio
TOKENS_PER_S = 25  # speech tokens per second of audio; render_text's budget is already 2 x est
TOKEN_CAP = (100, 800)
# In the cache key: bump it when chunking, caps, seeds, speakable, the ladder or text prep change.
_RENDER_REVISION = 3
_BRACKETS = re.compile(r"[\[\]]")
BRACKET_WARNING = f"{TITLE}: square brackets were dropped (the model reads them as sound cues)"


def supported() -> str | None:
    """Hard reason this engine cannot exist here (platform, packages, build), else None."""
    return mlx_support(BACKEND_MODULES, BACKEND_SUBPACKAGE)


def gate() -> str | None:
    """Soft reason that can clear by itself. Chatterbox has none."""
    return None


def token_cap(budget_s: float) -> int:
    """Speech-token limit for one render: the budget at 25 tokens/s, clamped to TOKEN_CAP."""
    low, high = TOKEN_CAP
    tokens = math.ceil(round(TOKENS_PER_S * budget_s, 6))  # 25 x 9.88 is 247.00000000000003
    return min(high, max(low, tokens))


def fingerprint(files: Sequence[PinnedFile]) -> str:
    """First 12 hex of SHA-256 over the sorted `rel:sha256` lines of the pinned files."""
    lines = "\n".join(sorted(f"{f.rel}:{f.sha256}" for f in files))
    return hashlib.sha256(lines.encode()).hexdigest()[:12]


def _package_version() -> str:
    try:
        return importlib.metadata.version("mlx-audio")
    except importlib.metadata.PackageNotFoundError:
        return "n/a"


def _hard_word_warning(words: Sequence[str]) -> str:
    named = ", ".join(words[:3]) + (f" and {len(words) - 3} more" if len(words) > 3 else "")
    count = f"{len(words)} hard words use" if len(words) > 1 else "1 hard word uses"
    return f"{TITLE} cannot take IPA: {count} the printed spelling ({named})"


class MlxChatterboxBackend:
    """Chatterbox Turbo through mlx-audio in this process. Loads on first render, from a Path."""

    def __init__(self, model_dir: Path, *, slot: ModelSlot | None = None) -> None:
        self.model_dir = Path(model_dir)
        self._slot = slot if slot is not None else SLOT
        # Lock order: the slot, then this lock. Another engine's load may call _unload while it
        # holds the slot, so render never waits for the slot while holding this lock.
        self._lock = threading.Lock()
        self._model: Any = None
        self._mx: Any = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _ensure_loaded(self) -> tuple[Any, Any]:
        with self._lock:
            if self._model is not None:
                return self._model, self._mx
        try:
            import mlx.core as mx
            from mlx_audio.tts.utils import load_model
        except ImportError as exc:
            raise EngineUnavailable(f"{TITLE} backend not installed: {exc}") from exc
        with self._slot:  # one load at a time across engines
            with self._lock:
                if self._model is not None:
                    return self._model, self._mx
            self._slot.acquire(KEY, self._unload)  # evicts another engine's model first
            try:
                # A Path never downloads; the guard also blocks the S3 tokenizer fetch in
                # post_load_hook, which only voice cloning needs (it logs and goes on).
                with offline_guard(), quiet():
                    model = load_model(self.model_dir, model_type=MODEL_TYPE)
                # post_load_hook swallows these failures and leaves the model half-built.
                if getattr(model, "tokenizer", None) is None:
                    raise EngineUnavailable(f"{TITLE} could not load its tokenizer")
                if getattr(model, "_conds", None) is None:
                    raise EngineUnavailable(f"{TITLE} could not load its built-in voice")
            except EngineUnavailable:
                self._slot.release(KEY)
                raise
            except Exception as exc:
                self._slot.release(KEY)
                raise EngineUnavailable(f"{TITLE} could not load its model: {exc}") from exc
            with self._lock:
                self._model, self._mx = model, mx
        return model, mx

    def render(
        self, text: str, voice: str, *, seed: int, budget_s: float
    ) -> tuple[np.ndarray, int]:
        if voice != VOICE_ID:
            raise ValueError(f"unknown {TITLE} voice: {voice!r}")
        model, mx = self._ensure_loaded()
        with self._lock:  # one generation at a time; an eviction waits for it
            mx.random.seed(seed)
            try:
                with quiet():  # t3 draws a tqdm bar per chunk
                    results = model.generate(
                        text,
                        temperature=TEMPERATURE,
                        top_k=TOP_K,
                        top_p=TOP_P,
                        repetition_penalty=REPETITION_PENALTY,
                        max_tokens=token_cap(budget_s),
                        split_pattern=None,  # the engine chunks; mlx-audio must not re-split
                        stream=False,
                    )
                    parts = [np.asarray(r.audio, dtype=np.float32).reshape(-1) for r in results]
            finally:
                mx.clear_cache()  # the MLX buffer cache otherwise grows by GBs
        audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        return audio, int(model.sample_rate)

    def _unload(self) -> None:
        with self._lock:
            self._model = None
            if self._mx is not None:
                self._mx.clear_cache()

    def close(self) -> None:
        self._unload()
        self._slot.release(KEY)


class ChatterboxTurboEngine:
    """TtsEngine for Chatterbox Turbo: one built-in voice, plain text in, 24 kHz mono out."""

    key = KEY

    def __init__(
        self,
        settings: Settings,
        backend: TextBackend | None = None,
        *,
        pinned: Pinned | None = None,
        assess: Callable[[], Assessment] | None = None,
        slot: ModelSlot | None = None,
    ) -> None:
        self.model_dir = Path(settings.models_dir) / KEY
        self._pinned = pinned if pinned is not None else engine_catalog.pinned(settings, KEY)
        self._assess = (
            assess
            if assess is not None
            else functools.partial(engine_catalog.assess, settings, KEY)
        )
        self.backend: TextBackend = (
            backend
            if backend is not None
            else MlxChatterboxBackend(self.model_dir, slot=slot if slot is not None else SLOT)
        )
        self._files = ModelFiles(self.model_dir, self._pinned.files)
        rev8 = self._pinned.revision[:8] or "norev"
        self.version = (
            f"chatterbox-turbo-4bit@{rev8}+mlx-audio-{_package_version()}"
            f"+{SAMPLING_TAG}+r{_RENDER_REVISION}"
        )
        self._fingerprint = fingerprint(self._pinned.files)
        self.unavailable_reason: str | None = None
        self._warnings = EngineWarnings()
        self._lock = threading.Lock()  # one synthesis at a time: the memo and the backend
        self._memo: dict = {}  # render_text's: short units by (voice key, text), LRU-bounded
        self._verified: tuple[tuple[str, int, int], ...] | None = None  # file state that hashed OK
        self._damage: tuple[tuple[tuple[str, int, int], ...], str] | None = None  # sticky

    # --- availability -------------------------------------------------------------------------

    def available(self) -> bool:
        """`ready` only. Never hashes: the SHA-256 check runs before the first load."""
        self.unavailable_reason = self._reason(self._assess())
        return self.unavailable_reason is None

    def _reason(self, assessment: Assessment) -> str | None:
        if assessment.state != "ready":
            return assessment.reason or f"{TITLE} is unavailable"
        if self._damage is not None and self._damage[0] == self._file_state():
            return self._damage[1]
        return None

    def _file_state(self) -> tuple[tuple[str, int, int], ...]:
        state = []
        for pin in self._pinned.files:
            try:
                st = (self.model_dir / pin.rel).stat()
            except OSError:
                state.append((pin.rel, -1, -1))
            else:
                state.append((pin.rel, st.st_size, st.st_mtime_ns))
        return tuple(state)

    def _verify(self) -> None:
        """Hash each pinned file before the first load; a mismatch sticks until the files change."""
        state = self._file_state()
        if state == self._verified:
            return
        if error := self._files.verify():  # available() already refused a known mismatch
            reason = error if error.startswith("damaged") else f"damaged: {error}"
            self._damage = (state, reason)
            self.unavailable_reason = reason
            raise EngineUnavailable(reason)
        self._verified, self._damage = state, None

    def load_hint(self) -> str | None:
        """Status text for the first use; None while the model is resident."""
        return None if getattr(self.backend, "loaded", False) else LOAD_HINT

    # --- voices -------------------------------------------------------------------------------

    def _voice(self, *, installed: bool, reason: str = "") -> VoiceInfo:
        return VoiceInfo(
            key=VOICE_KEY,
            engine=KEY,
            name=f"{TITLE} (built-in)",
            language="en",
            quality="4-bit",
            num_speakers=1,
            installed=installed,
            path=self.model_dir if installed else None,
            reason=reason,
        )

    def voices(self) -> list[VoiceInfo]:
        return [self._voice(installed=True)] if self.available() else []

    def placeholder_voices(self) -> list[VoiceInfo]:
        """The dimmed row of an engine that cannot speak yet; nothing for a hard blocker."""
        assessment = self._assess()
        reason = self._reason(assessment)
        if reason is None or not assessment.listable:
            return []
        return [self._voice(installed=False, reason=reason)]

    def voice_version(self, voice: VoiceInfo) -> str:
        return f"{VOICE_ID}:{self._fingerprint}"

    # --- text prep ----------------------------------------------------------------------------

    def _prepare(self, script: SpokenScript) -> tuple[list[str], list[str]]:
        """Spoken text per segment, plus the warnings it implies, in first-seen order."""
        texts: list[str] = []
        hard: list[str] = []
        missing: list[str] = []
        brackets = False
        for segment in script.segments:
            spoken = speakable(segment, style=RESPELLING_STYLE)
            hard += [word for word in spoken.unspoken if word not in hard]
            missing += [surface for surface in spoken.missing if surface not in missing]
            brackets = brackets or bool(_BRACKETS.search(spoken.text))
            # Turbo's tokenizer turns [laugh], [sigh] and 17 more into sound cues.
            texts.append(say_letter(" ".join(_BRACKETS.sub(" ", spoken.text).split())))
        warnings = [_hard_word_warning(hard)] if hard else []
        warnings += [f"{TITLE}: override for {s!r} not found in the segment text" for s in missing]
        if brackets:
            warnings.append(BRACKET_WARNING)
        return texts, warnings

    def script_warnings(self, script: SpokenScript, voice: VoiceInfo) -> tuple[str, ...]:
        """What synthesis will paper over; the same strings as `last_warnings`."""
        return tuple(self._prepare(script)[1])

    @property
    def last_warnings(self) -> list[str]:
        """Warnings of the calling thread's latest `synthesize`."""
        return self._warnings.snapshot()

    def _warn(self, message: str) -> None:
        if message not in self._warnings.snapshot():
            log.warning("%s", message)
        self._warnings.add(message)

    # --- synthesis ----------------------------------------------------------------------------

    def _check_voice(self, voice: VoiceInfo) -> None:
        if voice.engine != KEY or voice.key != VOICE_KEY:
            raise ValueError(f"not a {TITLE} voice: {voice.key!r}")

    def synthesize(
        self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions, out_wav: Path
    ) -> Audio:
        """Write the script as a 24 kHz 16-bit mono WAV; each pause is exact silence."""
        self._warnings.reset()
        self._check_voice(voice)
        if not self.available():
            raise EngineUnavailable(self.unavailable_reason or f"{TITLE} is unavailable")
        self._verify()
        chars = sum(len(segment.text) for segment in script.segments)
        if chars > MAX_SCRIPT_CHARS:
            raise EngineError(
                f"{TITLE} reads at most {MAX_SCRIPT_CHARS:,} characters at once; this has {chars:,}"
            )
        if opts.speed != 1.0:
            self._warn(f"{TITLE}: speed {opts.speed:g} is not supported; read at 1.0")
        if opts.speaker_id is not None:
            self._warn(f"{TITLE}: speaker {opts.speaker_id} ignored; it has one voice")
        texts, warnings = self._prepare(script)
        for message in warnings:
            self._warn(message)
        with self._lock:
            parts = [
                self._segment(segment, text, voice)
                for segment, text in zip(script.segments, texts, strict=True)
            ]
        samples = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        write_pcm16(out_wav, samples, SAMPLE_RATE)
        return Audio(out_wav, SAMPLE_RATE, len(samples) / SAMPLE_RATE, False)

    def _segment(self, segment: Segment, text: str, voice: VoiceInfo) -> np.ndarray:
        """One segment on its own (never merged across a pause): its chunks, INTER_CHUNK_MS
        between them, then exactly its pause, whatever the chunking did."""
        parts: list[np.ndarray] = []
        if text:
            # chunk_text may grow a chunk by min_chars when a short fragment joins it.
            limit = MAX_CHUNK_CHARS - SHORT_CHARS
            for index, chunk in enumerate(chunk_text(text, max_chars=limit, min_chars=SHORT_CHARS)):
                if index:
                    parts.append(silence(INTER_CHUNK_MS))
                parts.append(self._unit(chunk, voice.key))
        if segment.pause_after_ms > 0:
            parts.append(silence(segment.pause_after_ms))
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

    def _unit(self, text: str, voice_key: str) -> np.ndarray:
        audio, rate = render_text(
            self.backend, voice_key, VOICE_ID, text, title=TITLE, memo=self._memo
        )
        if rate != SAMPLE_RATE:
            raise EngineError(f"{TITLE} backend returned {rate} Hz, expected {SAMPLE_RATE} Hz")
        return np.asarray(audio, dtype=np.float32).reshape(-1)

    def close(self) -> None:
        self.backend.close()
        with self._lock:
            self._memo.clear()
