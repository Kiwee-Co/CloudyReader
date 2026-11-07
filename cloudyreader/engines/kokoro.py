"""Kokoro-82M on MLX (Apple Silicon only) as an optional second TTS engine.

KokoroEngine owns rendering (Override -> misaki markup), voice listing, model verification and WAV
assembly. A KokoroBackend turns one line of marked-up text into audio, so the engine can run against
a fake in tests and against an in-process or out-of-process MLX backend in the app.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import os
import platform
import re
import sys
import threading
import wave
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from cloudyreader.engines.misaki_ipa import ipa_to_misaki
from cloudyreader.engines.padding import trim_letter_padding
from cloudyreader.models import Audio, RenderOptions, Segment, SpokenScript, VoiceInfo

log = logging.getLogger(__name__)

KOKORO_REPO = "mlx-community/Kokoro-82M-bf16"
KOKORO_REVISION = "a71e4d38b236d968966a2002c4c895dbd12b1c3c"
MODEL_SUBDIR = "kokoro"
SAMPLE_RATE = 24_000
SPEED_RANGE = (0.5, 2.0)
SPACY_MODEL = "en_core_web_sm"
# find_spec only: importing mlx and spaCy costs seconds, so available() must not do it.
BACKEND_MODULES = ("mlx", "mlx_audio", "misaki", SPACY_MODEL)

# Trust anchors live in code, not next to the downloaded files. Safetensors only: the repo also
# ships .pt/.pth pickles, which are never fetched or loaded.
MODEL_SHA256 = {
    "config.json": "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f",
    "kokoro-v1_0.safetensors": "4e9ecdf03b8b6cf906070390237feda473dc13327cb8d56a43deaa374c02acd8",
}
VOICE_SHA256 = {
    "af_alloy": "5bb848d02ade7e37981809acad52a1761ef7a586ff9f30d02d65fd71c4af95f9",
    "af_aoede": "23809148777f2a2378983dd856bc14b9c261018279f916f98c23d86e844409a5",
    "af_bella": "112d310468cbb3cf23404d3d0b50ad3adf017b87bf38bf9edd15f4ad572df6a3",
    "af_heart": "2c1c733b0e6576c810e268d3e440c21dea4e0f0131a3ba4cfc98d7fe6136d094",
    "af_jessica": "c358448e4277b79e8b13b92033711660a1a2205c3940c2dfb16698b99fed58a8",
    "af_kore": "c491174280cb1ad25210a842f2f34b46a9ef904ec6f6a8e784839531795fa278",
    "af_nicole": "574656386022c81a029e9a72558191925f44c3de2dad2fa2e45751938557d062",
    "af_nova": "242b9a0a01eac1ac2865c69fc617a756b20d86df82d5fae3970533e2312ca50e",
    "af_river": "82c866b0b976d50e82cbd781ac7bc771471ce5bd21decf05ab92812a08fb1c04",
    "af_sarah": "4940072182542f54c1035d1daf4c1cf3136ca9baa9ac57c8e006b4befcc50be6",
    "af_sky": "957af332330db8e9bd7f9dc449475a946cb0d7d689afef64b91007bbbf20eaa0",
    "am_adam": "a4f60a3b9c20353c2604a17485ba53260502a758681a84d41e8af53cc559d929",
    "am_echo": "031fc608a900332c4e1a29bd0884f5d0e84bd0348261fa79981e5cbd138c950d",
    "am_eric": "1fb4a61dcee1f114f90886ecf29bc2feed05e29eed9caa6ddb109f1934d73274",
    "am_fenrir": "9abed964b906c4cae6f404d9849e76260689aea862bc6ca85fc3f5207ba96538",
    "am_liam": "66b65a96e16c3d91035a6e9019d9986ed524d27ce35b487270cdf61c99e3ebad",
    "am_michael": "3940147ded35deba0bb52e8132f89b719298e0520258c34584358aa5a24da2ea",
    "am_onyx": "b5d6132a5747648d98c82c9c4aaa9cf52d7230e63e403c1cb9c12858446ca5f5",
    "am_puck": "9a8c2e56413bd2063f814cb4c3885fc425876157369117c3f8258d03c8a9ad89",
    "am_santa": "d1f433b57ffccf105ea9e434ea19af6c2a8a7916ba6d1a73c34f0046bd226084",
    "bf_alice": "9c77e390d93d9db7c4a7526c3b1f393290a2be46f233b89a00b8188e850c20a8",
    "bf_emma": "8878a75a6661305849eeb1d6293a7177250193616e161b4c3100636434dfe69f",
    "bf_isabella": "f7b6076f025649699fcfed1a6debf13049a87afdc7aafc8c72b7d81246db6ead",
    "bf_lily": "ee77a419046a765420ac82cb46e8b8cf5754a0b9d20c340fece1d4b18be7ecdb",
    "bm_daniel": "b195dec592ee024f57ddc5bf481464596082ba60998a2a295eba90bfc1064f4b",
    "bm_fable": "9fa80184e96d016a744bc13b0b2e7695e55d6b855556fa003325cb1e5ebf2c2b",
    "bm_george": "a3d9b8995cbbe5536f954b6be2a0f1f312f077118ba0d4d2178fc41dc8306672",
    "bm_lewis": "e1e68013c21a141efe527aaec561e1174c2f5a6951b3bcecc8396adab315b247",
}
# Overall grades from the model's VOICES.md. Non-English voices need other G2P stacks: not offered.
VOICE_GRADES = {
    "af_heart": "A",
    "af_bella": "A-",
    "af_nicole": "B-",
    "af_aoede": "C+",
    "af_kore": "C+",
    "af_sarah": "C+",
    "af_alloy": "C",
    "af_nova": "C",
    "af_sky": "C-",
    "af_jessica": "D",
    "af_river": "D",
    "am_fenrir": "C+",
    "am_michael": "C+",
    "am_puck": "C+",
    "am_echo": "D",
    "am_eric": "D",
    "am_liam": "D",
    "am_onyx": "D",
    "am_santa": "D-",
    "am_adam": "F+",
    "bf_emma": "B-",
    "bf_isabella": "C",
    "bf_alice": "D",
    "bf_lily": "D",
    "bm_fable": "C",
    "bm_george": "C",
    "bm_lewis": "D+",
    "bm_daniel": "D",
}
RECOMMENDED_VOICES = ("af_heart", "af_bella", "bf_emma", "am_michael", "am_fenrir", "am_puck")
_VOICE_ID = re.compile(r"^[ab][fm]_[a-z]+$")


class KokoroError(RuntimeError):
    """Kokoro could not produce audio."""


class KokoroUnavailable(KokoroError):
    """Kokoro cannot run here: wrong platform, missing packages, or an unverified model."""


class KokoroBackend(Protocol):
    def synthesize_line(self, text: str, voice: str, speed: float) -> tuple[np.ndarray, int]:
        """Return (mono float32 samples in [-1, 1], sample rate) for one line of misaki markup."""
        ...

    def close(self) -> None: ...


def _supported_platform() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


class InProcessBackend:
    """Kokoro through mlx-audio in this process. Imports happen on first use (they take seconds)."""

    def __init__(self, model_dir: Path, *, cache_limit_bytes: int = 1 << 30) -> None:
        self.model_dir = Path(model_dir)
        self.cache_limit_bytes = cache_limit_bytes
        self.last_phonemes: list[str] = []  # phoneme chunks of the latest line, for diagnostics
        self.last_skipped: list[str] = []  # words misaki could not phonemize (spoken as nothing)
        self._lock = threading.Lock()  # one MLX model, one caller at a time
        self._mx: Any = None
        self._model: Any = None
        self._pipeline_cls: Any = None
        self._pipelines: dict[str, Any] = {}

    def _load(self) -> None:
        if self._model is not None:
            return
        # Voices must come from model_dir; never let mlx-audio fall back to the Hugging Face Hub.
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            import mlx.core as mx
            import spacy
            from mlx_audio.tts.models.kokoro.pipeline import KokoroPipeline
            from mlx_audio.tts.utils import load_model
        except ImportError as exc:
            raise KokoroUnavailable(f"Kokoro backend not installed: {exc}") from exc
        if not spacy.util.is_package(SPACY_MODEL):
            # misaki would otherwise run `pip install` at runtime (and fail in a uv venv).
            raise KokoroUnavailable(f"spaCy model {SPACY_MODEL} is not installed")
        mx.set_cache_limit(self.cache_limit_bytes)
        self._model = load_model(self.model_dir, model_type="kokoro")
        self._mx, self._pipeline_cls = mx, KokoroPipeline

    def _pipeline(self, lang_code: str) -> Any:
        # Built directly: Model.generate() prints to stdout and resets the voice cache per call.
        if lang_code not in self._pipelines:
            self._pipelines[lang_code] = self._pipeline_cls(
                lang_code=lang_code,
                model=self._model,
                repo_id=KOKORO_REPO,
                model_path=self.model_dir,
            )
        return self._pipelines[lang_code]

    def synthesize_line(self, text: str, voice: str, speed: float) -> tuple[np.ndarray, int]:
        if not _VOICE_ID.match(voice):  # a value ending in .safetensors would be loaded as a path
            raise ValueError(f"invalid Kokoro voice id: {voice!r}")
        with self._lock:
            self._load()
            pipe = self._pipeline(voice[0])
            chunks: list[np.ndarray] = []
            phonemes: list[str] = []
            skipped: list[str] = []
            try:
                for result in pipe(text, voice=voice, speed=speed, split_pattern=None):
                    phonemes.append(result.phonemes)
                    skipped += [
                        t.text
                        for t in result.tokens or ()
                        if not t.phonemes and any(c.isalpha() for c in t.text)
                    ]
                    if result.audio is not None:
                        chunks.append(np.asarray(result.audio, dtype=np.float32).reshape(-1))
            finally:
                self._mx.clear_cache()  # the MLX buffer cache otherwise grows to several GB
            self.last_phonemes, self.last_skipped = phonemes, skipped
            audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
            return audio, int(self._model.sample_rate)

    def close(self) -> None:
        with self._lock:
            self._pipelines.clear()
            self._model = None
            if self._mx is not None:
                self._mx.clear_cache()


class KokoroEngine:
    """TtsEngine for Kokoro-82M. Overrides reach the model as misaki `[surface](/phonemes/)`."""

    key = "kokoro"
    # The +r suffix changes with the WAV assembly, so cached WAVs from older code are not reused.
    version = f"kokoro-82m@{KOKORO_REVISION[:8]}+misaki-ipa-2+r1"

    def __init__(
        self, models_dir: Path, backend: KokoroBackend | None = None, *, all_voices: bool = False
    ) -> None:
        self.model_dir = Path(models_dir) / MODEL_SUBDIR
        self._injected = backend is not None
        self.backend: KokoroBackend = (
            backend if backend is not None else InProcessBackend(self.model_dir)
        )
        self.all_voices = all_voices
        self.unavailable_reason: str | None = None
        self.last_warnings: list[str] = []  # since the last synthesize(); render() appends too
        self._verified: set[Path] = set()  # files whose SHA256 matched, checked once per process

    # --- availability -------------------------------------------------------------------------

    def available(self) -> bool:
        self.unavailable_reason = self._unavailable_reason()
        return self.unavailable_reason is None

    def _unavailable_reason(self) -> str | None:
        if not _supported_platform():
            return "Kokoro needs an Apple Silicon Mac (arm64)"
        if not self._injected:
            missing = [m for m in BACKEND_MODULES if importlib.util.find_spec(m) is None]
            if missing:
                return f"Kokoro backend packages missing: {', '.join(missing)}"
        for rel, digest in MODEL_SHA256.items():
            if error := self._verify(self.model_dir / rel, digest):
                return error
        return None

    def _verify(self, path: Path, digest: str) -> str | None:
        if path in self._verified:
            return None
        if not path.is_file():
            return f"Kokoro model file missing: {path}"
        with path.open("rb") as fh:
            actual = hashlib.file_digest(fh, "sha256").hexdigest()
        if actual != digest:
            return f"SHA256 mismatch for {path.name}: refusing to load it"
        self._verified.add(path)
        return None

    # --- voices -------------------------------------------------------------------------------

    def voices(self) -> list[VoiceInfo]:
        if not _supported_platform():
            return []
        ids = list(RECOMMENDED_VOICES)
        if self.all_voices:
            ids += [v for v in VOICE_GRADES if v not in RECOMMENDED_VOICES]
        return [self._voice_info(v) for v in ids]

    def _voice_info(self, vid: str) -> VoiceInfo:
        path = self.model_dir / "voices" / f"{vid}.safetensors"
        installed = path.is_file() and (self.model_dir / "kokoro-v1_0.safetensors").is_file()
        gender = "female" if vid[1] == "f" else "male"
        return VoiceInfo(
            key=f"kokoro:{vid}",
            engine="kokoro",
            name=f"{vid.split('_', 1)[1].title()} ({gender})",
            language="en-US" if vid[0] == "a" else "en-GB",
            quality=VOICE_GRADES[vid],
            num_speakers=1,
            installed=installed,
            path=path if installed else None,
        )

    # --- rendering ----------------------------------------------------------------------------

    def _warn(self, message: str) -> None:
        log.warning(message)
        self.last_warnings.append(message)

    def render(self, segment: Segment, voice: VoiceInfo | None = None) -> str:
        """Segment text with each Override as `[surface](/misaki/)`. US phonemes for every voice."""
        text = segment.text.replace("](", "] (")  # plain text must never parse as misaki markup
        marks: dict[str, str] = {}
        for ov in segment.overrides:
            if not ov.surface or "[" in ov.surface or "]" in ov.surface:
                self._warn(f"Kokoro: override surface {ov.surface!r} has a bracket; spoken plain")
                continue
            phonemes, rejected = ipa_to_misaki(ov.ipa)
            if rejected:
                dropped = ", ".join(repr(c) for c in rejected)
                self._warn(f"Kokoro: dropped {dropped} from IPA {ov.ipa!r} for {ov.surface!r}")
            if not phonemes:
                self._warn(f"Kokoro: no usable phonemes for {ov.surface!r}; spoken plain")
                continue
            marks.setdefault(ov.surface, phonemes)
        if not marks:
            return text
        # One pass, longest surface first, whole words only: no markup nests inside markup.
        alternatives = sorted(marks, key=len, reverse=True)
        words = "|".join(re.escape(s) for s in alternatives)
        # spaCy keeps "Strontium-90" one token and misaki then shifts later overrides onto the
        # wrong words, so a hyphen between the markup and a digit becomes a space.
        pattern = re.compile(rf"(?<!\w)(?P<surface>{words})(?!\w)(?P<hyphen>-(?=\d))?")
        found: set[str] = set()

        def mark(match: re.Match[str]) -> str:
            surface = match.group("surface")
            found.add(surface)
            gap = " " if match.group("hyphen") else ""
            return f"[{surface}](/{marks[surface]}/){gap}"

        text = pattern.sub(mark, text)
        for surface in alternatives:
            if surface not in found:
                self._warn(f"Kokoro: override surface {surface!r} not found in segment text")
        return text

    # --- synthesis ----------------------------------------------------------------------------

    def _voice_id(self, voice: VoiceInfo) -> str:
        engine, _, vid = voice.key.partition(":")
        if engine != self.key or vid not in VOICE_GRADES:
            raise ValueError(f"not a Kokoro voice: {voice.key!r}")
        return vid

    def synthesize(
        self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions, out_wav: Path
    ) -> Audio:
        self.last_warnings = []
        vid = self._voice_id(voice)
        if not self.available():
            raise KokoroUnavailable(self.unavailable_reason or "Kokoro is unavailable")
        if error := self._verify(
            self.model_dir / "voices" / f"{vid}.safetensors", VOICE_SHA256[vid]
        ):
            raise KokoroUnavailable(error)
        speed = min(max(opts.speed, SPEED_RANGE[0]), SPEED_RANGE[1])
        if speed != opts.speed:
            self._warn(f"Kokoro: speed {opts.speed} clamped to {speed}")
        speech: list[np.ndarray] = []
        for segment in script.segments:
            lines = self.render(segment, voice).splitlines()
            sound = [self._line(line.strip(), vid, speed) for line in lines if line.strip()]
            speech.append(np.concatenate(sound) if sound else np.zeros(0, dtype=np.float32))
        parts: list[np.ndarray] = []
        trimmed = trim_letter_padding(script.segments, speech, SAMPLE_RATE)
        for segment, sound in zip(script.segments, trimmed, strict=True):
            parts.append(sound)
            if segment.pause_after_ms > 0:
                parts.append(
                    np.zeros(round(SAMPLE_RATE * segment.pause_after_ms / 1000), np.float32)
                )
        samples = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        _write_wav(out_wav, samples)
        return Audio(out_wav, SAMPLE_RATE, len(samples) / SAMPLE_RATE, cache_hit=False)

    def _line(self, text: str, vid: str, speed: float) -> np.ndarray:
        audio, rate = self.backend.synthesize_line(text, vid, speed)
        if rate != SAMPLE_RATE:
            raise KokoroError(f"Kokoro backend returned {rate} Hz, expected {SAMPLE_RATE} Hz")
        for word in getattr(self.backend, "last_skipped", ()):
            self._warn(f"Kokoro: could not pronounce {word!r}; it was skipped")
        return np.asarray(audio, dtype=np.float32).reshape(-1)

    def close(self) -> None:
        self.backend.close()


def _write_wav(path: Path, samples: np.ndarray) -> None:
    pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm.tobytes())
