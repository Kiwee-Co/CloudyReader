"""TTS service: engine registry plus a content-addressed WAV cache."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import threading
import uuid
import wave
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from cloudyreader.models import Audio, RenderOptions, SpokenScript, TtsEngine, VoiceInfo

_LOG = logging.getLogger(__name__)


class TtsError(RuntimeError):
    """Speech synthesis could not run."""


class EngineUnavailableError(TtsError):
    """The voice's engine is not registered or reports itself unavailable."""


def _engine_version(engine: TtsEngine, voice: VoiceInfo) -> str:
    """Engine version, plus the engine's own fingerprint of the voice files when it has one."""
    version = str(getattr(engine, "version", engine.key))
    voice_version = getattr(engine, "voice_version", None)
    return version if voice_version is None else f"{version}|{voice_version(voice)}"


def _digest(
    script: SpokenScript, voice: VoiceInfo, opts: RenderOptions, engine_version: str
) -> str:
    # Warnings and the other options only shape the script, never the audio: keep them out.
    payload = {
        "segments": [dataclasses.asdict(segment) for segment in script.segments],
        "voice": voice.key,
        "speed": float(opts.speed),
        "speaker": opts.speaker_id,
        "engine": engine_version,
    }
    # ASCII-escaped JSON hashes any str, even one holding a lone surrogate from a bad paste.
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


def _cached(path: Path) -> Audio | None:
    try:
        with wave.open(str(path), "rb") as wav:
            rate, frames = wav.getframerate(), wav.getnframes()
    except FileNotFoundError:
        return None
    except (wave.Error, EOFError, OSError):
        _LOG.warning("ignoring unreadable cache entry %s", path)
        return None
    return Audio(path, rate, frames / rate, cache_hit=True)


class TtsService:
    """Routes a voice to its engine and caches the WAV per (script, voice, speed, speaker)."""

    def __init__(self, engines: Sequence[TtsEngine], cache_dir: Path) -> None:
        self._engines: dict[str, TtsEngine] = {}
        for engine in engines:
            if engine.key in self._engines:
                raise ValueError(f"duplicate TTS engine key {engine.key!r}")
            self._engines[engine.key] = engine
        self._cache_dir = Path(cache_dir)
        self._lock = threading.Lock()
        self._local = threading.local()  # per thread: engine notes of that thread's last call

    def voices(self) -> list[VoiceInfo]:
        found: list[VoiceInfo] = []
        for engine in self._engines.values():
            if not engine.available():
                continue
            try:
                found.extend(engine.voices())
            except Exception as exc:  # one broken engine must not hide the other voices
                _LOG.warning(
                    "TTS engine %r failed to list voices: %s", engine.key, exc, exc_info=True
                )
        return found

    @property
    def last_warnings(self) -> list[str]:
        """Engine notes of the calling thread's latest `synthesize`; empty after a cache hit."""
        return list(getattr(self._local, "warnings", ()))

    def script_warnings(self, script: SpokenScript, voice: VoiceInfo) -> tuple[str, ...]:
        """Problems the engine will paper over for this script; empty when it reports none."""
        report = getattr(self._engine_for(voice), "script_warnings", None)
        return tuple(report(script, voice)) if report is not None else ()

    def cache_key(self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions) -> str:
        return _digest(script, voice, opts, _engine_version(self._engine_for(voice), voice))

    def synthesize(self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions) -> Audio:
        self._local.warnings = []
        engine = self._engine_for(voice)
        key = _digest(script, voice, opts, _engine_version(engine, voice))
        final = self._cache_dir / f"{key}.wav"
        if (hit := _cached(final)) is not None:
            return hit
        with self._lock:
            if (hit := _cached(final)) is not None:  # another request finished while we waited
                return hit
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            staged = self._cache_dir / f".{key}.{uuid.uuid4().hex}.tmp"
            try:
                audio = engine.synthesize(script, voice, opts, staged)
                os.replace(staged, final)  # atomic: a reader never sees a half-written WAV
                self._local.warnings = list(getattr(engine, "last_warnings", ()))
            finally:
                with suppress(OSError):
                    staged.unlink(missing_ok=True)
        return dataclasses.replace(audio, wav_path=final, cache_hit=False)

    def _engine_for(self, voice: VoiceInfo) -> TtsEngine:
        engine = self._engines.get(voice.engine)
        if engine is None:
            raise EngineUnavailableError(
                f"no TTS engine registered for {voice.engine!r} (voice {voice.key})"
            )
        if not engine.available():
            raise EngineUnavailableError(
                f"TTS engine {voice.engine!r} is unavailable (voice {voice.key})"
            )
        return engine
