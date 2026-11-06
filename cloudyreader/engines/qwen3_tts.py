"""Qwen3-TTS (0.6B CustomVoice, the 8-bit MLX build, Apple Silicon only) as an optional TTS engine.

Qwen3TtsEngine owns availability, the two preset voices, text prep, chunking, pauses and WAV
assembly; mlxkit.render_text runs each unit through a TextBackend. Presets only: no cloning.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.metadata
import logging
import math
import platform
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from cloudyreader import engine_catalog
from cloudyreader.config import Settings
from cloudyreader.engine_catalog import Assessment, Pinned, PinnedFile
from cloudyreader.engines import letter_clips, mlxkit
from cloudyreader.engines.letter_clips import LetterClips
from cloudyreader.engines.mlxkit import (
    INTER_CHUNK_MS,
    MAX_SCRIPT_CHARS,
    SAMPLE_RATE,
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
    say_letter,
    silence,
    speakable,
    write_pcm16,
)
from cloudyreader.engines.qwen3_decoder import (
    WAITING,
    DecoderGate,
    apply_decoder_patch,
    decoder_gate,
    window_probe,
)
from cloudyreader.models import Audio, RenderOptions, Segment, SpokenScript, VoiceInfo

log = logging.getLogger(__name__)

KEY = "qwen3_tts"
TITLE = "Qwen3-TTS"
# voice id -> (mlx-audio speaker, picker name, language); both presets are male.
VOICES: Mapping[str, tuple[str, str, str]] = MappingProxyType(
    {"ryan": ("Ryan", "Ryan (male)", "en"), "aiden": ("Aiden", "Aiden (male)", "en-US")}
)
MODEL_TYPE = "qwen3_tts"  # mlx-audio's model folder; a Path load never downloads
LANGUAGE = "english"
# find_spec and a path check only: importing mlx_audio.tts loads mlx.core, which takes seconds.
BACKEND_MODULES = ("mlx", "mlx_audio", "transformers")
BACKEND_SUBPACKAGE = "mlx_audio.tts.models.qwen3_tts"
LOAD_HINT = f"loading {TITLE} (first use only)"

# Explicit sampling outranks the checkpoint's generation_config.json and mlx-audio's defaults.
TEMPERATURE, TOP_K, TOP_P, REPETITION_PENALTY = 0.9, 50, 1.0, 1.05
SAMPLING_TAG = f"t{TEMPERATURE}k{TOP_K}p{TOP_P}r{REPETITION_PENALTY}"
RESPELLING_STYLE = "hyphen"
MAX_CHUNK_CHARS = 300  # about 21 s
MIN_CHUNK_CHARS = 24  # a shorter fragment joins its neighbor inside the segment
TOKENS_PER_S = 12.5  # codec frames per second of audio
TOKEN_CAP = (64, 2048)
# Bump when chunking, caps, seeds, speakable, the short-unit ladder, text prep or the letter clips
# change.
_RENDER_REVISION = 4
_ENDINGS = ".!?"
_CLOSERS = "\"')]”’"
WINDOW_FAILED = f"{WAITING} (the decoder window check failed)"


def supported() -> str | None:
    """Hard reason this engine cannot exist here (platform, packages, build), else None."""
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return f"{TITLE} needs an Apple Silicon Mac (arm64)"
    return mlx_support(BACKEND_MODULES, BACKEND_SUBPACKAGE)


def gate() -> str | None:
    """Soft reason that clears with a fixed mlx-audio: the decoder gate's, while it blocks."""
    current = decoder_gate()
    return current.reason if current.mode == "blocked" else None


def token_cap(budget_s: float) -> int:
    """Codec-token limit for one backend call of `budget_s` seconds, clamped to TOKEN_CAP."""
    low, high = TOKEN_CAP
    tokens = math.ceil(round(TOKENS_PER_S * budget_s, 6))  # 12.5 x 5.12 is 64.00000000000001
    return min(high, max(low, tokens))


def neutralize(text: str) -> str:
    """Break chat-template markers so pasted text cannot open or close a prompt turn."""
    return text.replace("<|", "< |").replace("|>", "| >")


def finish(chunk: str) -> str:
    """End on `.`, `!` or `?` (inside closing quotes); a final `,`, `;` or `:` becomes `.`."""
    body = chunk.rstrip()
    core = body.rstrip(_CLOSERS)
    if not core or core[-1] in _ENDINGS:
        return body
    stem = core[:-1] if core[-1] in ",;:" else core
    return stem + "." + body[len(core) :]


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


def _refusal(model: Any) -> str | None:
    """Why a load is unusable: the window probe failed (no model), or post_load_hook, which
    swallows tokenizer and speech-tokenizer failures, left the model half-built."""
    if model is None:
        return WINDOW_FAILED
    if getattr(model, "tokenizer", None) is None:
        return f"{TITLE} could not load its tokenizer"
    if getattr(model, "speech_tokenizer", None) is None:
        return f"{TITLE} could not load its speech tokenizer"
    return None


def _floats(audio: Any, mx: Any) -> np.ndarray:
    if hasattr(audio, "astype"):
        audio = audio.astype(mx.float32)  # numpy has no bfloat16
    return np.asarray(audio, dtype=np.float32).reshape(-1)


class MlxQwenBackend:
    """Qwen3-TTS CustomVoice via mlx-audio in this process; loads from a Path on first render."""

    def __init__(
        self,
        model_dir: Path,
        *,
        slot: ModelSlot | None = None,
        decoder: Callable[[], DecoderGate] = decoder_gate,
    ) -> None:
        self.model_dir = Path(model_dir)
        self._slot = slot if slot is not None else SLOT
        self._decoder = decoder
        self._lock = threading.RLock()  # the slot may call _unload from inside our own load
        self._model: Any = None
        self._mx: Any = None
        self.refused: str | None = None  # a load that failed its checks: sticky for the process

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        if self.refused:
            raise EngineUnavailable(self.refused)
        current = self._decoder()
        if current.mode == "blocked":
            raise EngineUnavailable(current.reason)
        try:
            import mlx.core as mx
            from mlx_audio.tts.utils import load_model
        except ImportError as exc:
            raise EngineUnavailable(f"{TITLE} backend not installed: {exc}") from exc
        with self._slot:  # one load at a time across engines
            self._slot.acquire(KEY, self._unload)
            try:
                with offline_guard(), quiet():
                    # Patch, probe the patched class, then load: post_load_hook's mx.compile
                    # traces the patched call and leaves no decoder module for a later probe.
                    apply_decoder_patch(current)
                    holds = window_probe()
                    model = load_model(self.model_dir, model_type=MODEL_TYPE) if holds else None
            except Exception as exc:
                self._slot.release(KEY)
                raise EngineUnavailable(f"{TITLE} could not load its model: {exc}") from exc
            self.refused = _refusal(model)
            if self.refused:
                self._slot.release(KEY)
                mx.clear_cache()
                raise EngineUnavailable(self.refused)
        self._model, self._mx = model, mx
        return model

    def render(
        self, text: str, voice: str, *, seed: int, budget_s: float
    ) -> tuple[np.ndarray, int]:
        if voice not in VOICES:
            raise ValueError(f"unknown {TITLE} voice: {voice!r}")
        with self._lock:
            model = self._load()
            mx = self._mx
            mx.random.seed(seed)
            try:
                with quiet():
                    results = model.generate_custom_voice(
                        text=text,
                        speaker=VOICES[voice][0],
                        language=LANGUAGE,
                        temperature=TEMPERATURE,
                        max_tokens=token_cap(budget_s),
                        top_k=TOP_K,
                        top_p=TOP_P,
                        repetition_penalty=REPETITION_PENALTY,
                        stream=False,
                    )
                    parts = [_floats(result.audio, mx) for result in results]
            finally:
                mx.clear_cache()  # the MLX buffer cache otherwise grows by GBs
            rate = int(model.sample_rate)
        audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        return audio, rate

    def _unload(self) -> None:
        with self._lock:
            self._model = None
            if self._mx is not None:
                self._mx.clear_cache()

    def close(self) -> None:
        self._unload()
        self._slot.release(KEY)


class Qwen3TtsEngine:
    """TtsEngine for Qwen3-TTS: presets Ryan and Aiden, plain text in, 24 kHz mono out."""

    key = KEY

    def __init__(
        self,
        settings: Settings,
        backend: TextBackend | None = None,
        *,
        pinned: Pinned | None = None,
        assess: Callable[[], Assessment] | None = None,
        slot: ModelSlot | None = None,
        decoder: Callable[[], DecoderGate] = decoder_gate,
        clips: LetterClips | None = None,
    ) -> None:
        self.model_dir = Path(settings.models_dir) / KEY
        self._pinned = pinned if pinned is not None else engine_catalog.pinned(settings, KEY)
        self._assess = (
            assess
            if assess is not None
            else functools.partial(engine_catalog.assess, settings, KEY)
        )
        self._decoder = decoder
        self._clips = clips if clips is not None else letter_clips.CLIPS
        self.backend: TextBackend = (
            backend
            if backend is not None
            else MlxQwenBackend(
                self.model_dir, slot=slot if slot is not None else SLOT, decoder=decoder
            )
        )
        self._files = ModelFiles(self.model_dir, self._pinned.files)
        rev8 = self._pinned.revision[:8] or "norev"
        self.decoder_mode = decoder().mode  # the cache key changes when the decoder does
        self.version = (
            f"qwen3-tts-0.6b-customvoice-8bit@{rev8}+mlx-audio-{_package_version()}"
            f"+{SAMPLING_TAG}+dec-{self.decoder_mode}+r{_RENDER_REVISION}"
        )
        self._fingerprint = fingerprint(self._pinned.files)
        self.unavailable_reason: str | None = None
        self._warnings = EngineWarnings()
        self._lock = threading.Lock()  # one synthesis at a time: the memo and the backend
        self._memo: dict[Any, Any] = {}  # render_text's short-unit memo, dropped with the model
        self._verified: tuple[tuple[str, int, int], ...] | None = None  # file state that hashed OK
        self._damage: tuple[tuple[tuple[str, int, int], ...], str] | None = None  # sticky

    # --- availability -------------------------------------------------------------------------

    def available(self) -> bool:
        """`ready` only, the decoder gate open, and no sticky refusal. Never hashes."""
        self.unavailable_reason = self._reason(self._assess())
        return self.unavailable_reason is None

    def _reason(self, assessment: Assessment) -> str | None:
        if assessment.state != "ready":
            return assessment.reason or f"{TITLE} is unavailable"
        current = self._decoder()
        if current.mode == "blocked":
            return current.reason
        if refused := getattr(self.backend, "refused", None):
            return refused
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
        """Hash every pinned file before the first load; a mismatch sticks until they change."""
        state = self._file_state()
        if state == self._verified:
            return
        if error := self._files.verify():
            reason = error if error.startswith("damaged") else f"damaged: {error}"
            self._damage = (state, reason)
            self.unavailable_reason = reason
            raise EngineUnavailable(reason)
        self._verified, self._damage = state, None

    def load_hint(self) -> str | None:
        """Status text for the first use; None while the model is resident."""
        return None if getattr(self.backend, "loaded", False) else LOAD_HINT

    # --- voices -------------------------------------------------------------------------------

    def _voice(self, voice_id: str, *, installed: bool, reason: str = "") -> VoiceInfo:
        _, name, language = VOICES[voice_id]
        return VoiceInfo(
            key=f"{KEY}:{voice_id}",
            engine=KEY,
            name=name,
            language=language,
            quality="8-bit",
            num_speakers=1,
            installed=installed,
            path=self.model_dir if installed else None,
            reason=reason,
        )

    def voices(self) -> list[VoiceInfo]:
        return [self._voice(v, installed=True) for v in VOICES] if self.available() else []

    def placeholder_voices(self) -> list[VoiceInfo]:
        """The dimmed rows of an engine that cannot speak yet; nothing for a hard blocker."""
        assessment = self._assess()
        reason = self._reason(assessment)
        if reason is None or not assessment.listable:
            return []
        return [self._voice(v, installed=False, reason=reason) for v in VOICES]

    def voice_version(self, voice: VoiceInfo) -> str:
        return f"{voice.key.partition(':')[2]}:{self._fingerprint}"

    # --- text prep ----------------------------------------------------------------------------

    def _prepare(self, script: SpokenScript) -> tuple[list[str], list[str]]:
        """Spoken text per segment, plus the warnings it implies, in first-seen order."""
        texts: list[str] = []
        hard: list[str] = []
        lost: list[str] = []
        for segment in script.segments:
            spoken = speakable(segment, style=RESPELLING_STYLE)
            hard += [w for w in spoken.unspoken if w not in hard]
            lost += [w for w in spoken.missing if w not in lost]
            texts.append(say_letter(" ".join(neutralize(spoken.text).split())))
        warnings = [_hard_word_warning(hard)] if hard else []
        warnings += [f"{TITLE}: override for {w!r} not found in the segment text" for w in lost]
        return texts, warnings

    def script_warnings(self, script: SpokenScript, voice: VoiceInfo) -> tuple[str, ...]:
        """What synthesis will paper over; the same strings as `last_warnings`."""
        return tuple(self._prepare(script)[1])

    @property
    def last_warnings(self) -> list[str]:
        """Warnings of the calling thread's latest `synthesize`."""
        return self._warnings.snapshot()

    # --- synthesis ----------------------------------------------------------------------------

    def _check_voice(self, voice: VoiceInfo) -> None:
        if voice.engine != KEY or voice.key.partition(":")[2] not in VOICES:
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
            self._warnings.add(f"{TITLE}: speed {opts.speed:g} is not supported; read at 1.0")
        if opts.speaker_id is not None:
            self._warnings.add(
                f"{TITLE}: speaker {opts.speaker_id} ignored; each voice has one speaker"
            )
        texts, warnings = self._prepare(script)
        for message in warnings:
            self._warnings.add(message)
        voice_id = voice.key.partition(":")[2]
        with self._lock:
            parts = [
                self._segment(segment, text, voice_id)
                for segment, text in zip(script.segments, texts, strict=True)
            ]
        samples = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        write_pcm16(out_wav, samples, SAMPLE_RATE)
        return Audio(out_wav, SAMPLE_RATE, len(samples) / SAMPLE_RATE, False)

    def _segment(self, segment: Segment, text: str, voice_id: str) -> np.ndarray:
        """One segment on its own: its chunks, then exactly its pause, whatever the chunking. A
        lone choice letter plays its verified clip for this voice when there is one."""
        parts: list[np.ndarray] = []
        if (clip := self._clips.get(KEY, voice_id, segment, SAMPLE_RATE)) is not None:
            parts.append(clip)
        elif text:
            chunks = chunk_text(text, max_chars=MAX_CHUNK_CHARS, min_chars=MIN_CHUNK_CHARS)
            for index, chunk in enumerate(chunks):
                if index:
                    parts.append(silence(INTER_CHUNK_MS))
                parts.append(self._render(finish(chunk), voice_id))
        if segment.pause_after_ms > 0:
            parts.append(silence(segment.pause_after_ms))
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

    def _render(self, text: str, voice_id: str) -> np.ndarray:
        audio, rate = mlxkit.render_text(
            self.backend, f"{KEY}:{voice_id}", voice_id, text, title=TITLE, memo=self._memo
        )
        if rate != SAMPLE_RATE:
            raise EngineError(f"{TITLE} backend returned {rate} Hz, expected {SAMPLE_RATE} Hz")
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        return np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)

    def close(self) -> None:
        self.backend.close()
        with self._lock:
            self._memo.clear()
