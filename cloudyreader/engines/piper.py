"""Piper engine: overrides become inline [[ipa]] blocks, segments join into one mono WAV."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import logging
import math
import re
import threading
import unicodedata
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from cloudyreader.engines.padding import trim_letter_padding
from cloudyreader.models import Audio, RenderOptions, Segment, SpokenScript, VoiceInfo
from cloudyreader.voices import KEY_PREFIX, is_safe_name, scan_installed

_LOG = logging.getLogger(__name__)

# Bump when rendering or silence logic changes, so cached WAVs from older code are not reused.
_RENDER_REVISION = 5
# espeak-ng keeps process-wide state, so one lock covers every engine instance.
_SYNTH_LOCK = threading.Lock()
# Voice maps carry the IPA letter U+0261, never ASCII "g", which hand-written IPA tends to use.
_ASCII_TO_IPA = {"g": "ɡ"}
# Neutral compact IPA puts the stress mark before the syllable onset and has no length marks.
# Piper voices learned espeak's layout: the mark before the vowel, ɑ u ɔ always long.
_VOWELS = "aeiouæɑɔɛɪʊʌəɚɜɐᵻ"
_MARK_BEFORE_ONSET = re.compile(rf"([ˈˌ])([^{_VOWELS} ˈˌ]*)")
_NURSE_BEFORE_VOWEL = re.compile(rf"ɜɹ(?=[{_VOWELS}])")
_ALWAYS_LONG = re.compile(r"ɔ(?![ɪː])|[ɑu](?!ː)")  # ɔɪ is a diphthong, not a long ɔ
_SHORT_I = re.compile(r"([ˈˌ]?)i(?!ː)")
# Piper reads any literal [[...]] in the text as raw phonemes; espeak ignores single brackets.
_OPEN_BRACKETS = re.compile(r"\[{2,}")
_CLOSE_BRACKETS = re.compile(r"\]{2,}")
# Piper drops punctuation right after a block and glues the next word onto it. Sentence marks
# therefore travel inside the block, the way Piper's own phonemizer emits them.
_MARKS = ",.;:!?"
_TRAILING = r"[,.;:!?)\]}\"”»'’]*"  # marks plus closers, which espeak does not speak
# Piper appends the sentence beside a block to the block's own phoneme sequence: split there.
_UNIT_BREAK = re.compile(r"(?<=[.!?]\]\])\s+|(?<=[.!?])\s+(?=\[\[)")
# espeak reads a lone "A" or "a" as the article /ɐ/ unless it ends the clause, so a spelled run
# ("N A C L", "N a H C O three") gets the letter name as a block. A run is 2+ letters and number
# words separated by single spaces; prose such as "A stone" has no second letter.
_NUMBER_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety"
).replace(" ", "|")
_RUN_TOKEN = rf"(?:[A-Za-z]|\d+|{_NUMBER_WORDS})"
_SPELLED_RUN = re.compile(rf"(?<!\S){_RUN_TOKEN}(?: {_RUN_TOKEN})+(?!\S)")
_LETTER_A = "[[ˈeɪ]]"


@dataclass(frozen=True)
class _VoiceConfig:
    sample_rate: int
    num_speakers: int
    length_scale: float
    symbols: frozenset[str]  # keys of phoneme_id_map


def _load_config(path: Path) -> _VoiceConfig:
    # Plain JSON read: importing piper pulls in onnxruntime, too slow for render and scan.
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _VoiceConfig(
            sample_rate=int(raw["audio"]["sample_rate"]),
            num_speakers=int(raw.get("num_speakers", 1)),
            length_scale=float(raw.get("inference", {}).get("length_scale", 1.0)),
            symbols=frozenset(raw["phoneme_id_map"]),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"invalid Piper voice config {path}: {exc!r}") from exc


def _load_piper_voice(model: Path, config: Path) -> Any:
    from piper import PiperVoice  # lazy: loads onnxruntime

    return PiperVoice.load(model, config_path=config)


def _piper_installed() -> bool:
    return importlib.util.find_spec("piper") is not None


def _engine_version() -> str:
    try:
        installed = importlib.metadata.version("piper-tts")
    except importlib.metadata.PackageNotFoundError:
        installed = "unknown"
    return f"piper-tts-{installed}+r{_RENDER_REVISION}"


def _lengthen_i(match: re.Match[str]) -> str:
    """espeak's i is long, except before another vowel ("kiə") and unstressed at the end."""
    stress, after = match.group(1), match.string[match.end() : match.end() + 1]
    if (after and after in _VOWELS) or (after in {"", " "} and not stress):
        return match.group(0)
    return f"{stress}iː"


def to_piper_layout(ipa: str) -> str:
    """Neutral compact IPA to the layout espeak gives Piper voices. espeak layout passes through."""
    explicit_lengths = "ː" in ipa  # compact data has none, so the author already chose these
    ipa = _MARK_BEFORE_ONSET.sub(r"\2\1", ipa)
    ipa = _NURSE_BEFORE_VOWEL.sub("ɜːɹ", ipa).replace("ɜɹ", "ɜː")
    if explicit_lengths:
        return ipa
    return _SHORT_I.sub(_lengthen_i, _ALWAYS_LONG.sub(lambda m: m.group() + "ː", ipa))


def _usable_ipa(ipa: str, symbols: frozenset[str]) -> tuple[str, list[str]]:
    """Keep the symbols the voice knows. Returns (usable ipa, distinct dropped symbols)."""
    kept: list[str] = []
    dropped: list[str] = []
    # Syllable dots are notation, and a "." phoneme would sound like a sentence end.
    for char in ipa.strip().replace(".", ""):
        spellings = (char, _ASCII_TO_IPA.get(char, char), unicodedata.normalize("NFD", char))
        usable = next((s for s in spellings if all(c in symbols for c in s)), None)
        if usable is not None:
            kept.append(usable)
        elif char not in dropped:
            dropped.append(char)
    return "".join(kept), dropped


def _render_segment(
    segment: Segment, symbols: frozenset[str], voice_key: str
) -> tuple[str, list[str]]:
    """Piper text for a segment plus the warnings for everything it could not honor."""
    text = _CLOSE_BRACKETS.sub("]", _OPEN_BRACKETS.sub("[", segment.text))
    warnings: list[str] = []
    blocks: dict[str, str] = {}
    for override in segment.overrides:
        surface = override.surface
        if not surface.strip():
            warnings.append(f"piper: override with an empty surface ignored (ipa {override.ipa!r})")
            continue
        if surface in blocks:  # the first usable override of a surface wins
            continue
        ipa, dropped = _usable_ipa(to_piper_layout(override.ipa), symbols)
        for char in dropped:
            warnings.append(
                f"piper: dropped IPA symbol {char!r} (U+{ord(char):04X}) from the override for "
                f"{surface!r}: not in the phoneme map of {voice_key}"
            )
        if ipa:
            blocks[surface] = ipa
        else:  # an empty [[]] block would swallow the word
            warnings.append(
                f"piper: override for {surface!r} has no usable IPA symbols; spoken plain"
            )
    if blocks:
        text, used = _substitute(text, blocks, symbols)
        for surface in blocks:
            if surface not in used:
                warnings.append(
                    f"piper: override surface {surface!r} not found in the segment text"
                )
    return _SPELLED_RUN.sub(_spell_run, text), warnings


def _substitute(text: str, blocks: dict[str, str], symbols: frozenset[str]) -> tuple[str, set[str]]:
    """Swap whole-word surfaces for `[[ipa]]` blocks in one pass, longest surface first."""
    surfaces = "|".join(re.escape(s) for s in sorted(blocks, key=len, reverse=True))
    # No match before apostrophe + letter: Piper cannot carry a spoken "'s" after a block.
    # The hyphen of "Potassium-40" goes: espeak reads a part opening with "-40" as "minus forty".
    pattern = re.compile(
        rf"(?<!\w)(?P<surface>{surfaces})(?!\w)(?!['’]\w)(?:-(?=\d)|(?P<tail>{_TRAILING}))"
    )
    used: set[str] = set()

    def swap(match: re.Match[str]) -> str:
        surface = match.group("surface")
        used.add(surface)
        start, end = match.span()
        marks = "".join(c for c in (match.group("tail") or "") if c in _MARKS and c in symbols)
        # Piper only separates a block from its neighbours when a space sits beside it.
        prev = text[start - 1] if start else " "
        following = text[end] if end < len(text) else " "
        before = "" if prev.isspace() else " "
        after = "" if following.isspace() else " "
        return f"{before}[[{blocks[surface]}{marks}]]{after}"

    return pattern.sub(swap, text), used


def _spell_run(match: re.Match[str]) -> str:
    tokens = match.group(0).split(" ")
    if sum(len(token) == 1 and token.isalpha() for token in tokens) < 2:
        return match.group(0)
    for i, token in enumerate(tokens):
        # A lowercase "a" counts only as the second letter of an element symbol ("N a"), and only
        # when more of the run follows, so prose such as "P a distance" keeps its article.
        symbol_a = token == "a" and i > 0 and tokens[i - 1].isupper() and i + 1 < len(tokens)
        if token == "A" or symbol_a:
            tokens[i] = _LETTER_A
    return " ".join(tokens)


def _units(text: str) -> list[str]:
    """Pieces to synthesize separately so no block sits on a sentence boundary."""
    return [unit.strip() for unit in _UNIT_BREAK.split(text) if unit.strip()]


def _checked_speed(speed: float) -> float:
    if not (math.isfinite(speed) and speed > 0):
        raise ValueError(f"speed must be a positive number, got {speed!r}")
    return speed


def _checked_speaker(speaker_id: int | None, num_speakers: int) -> int | None:
    if num_speakers <= 1 or speaker_id is None:
        return None  # single-speaker voices take no speaker input
    if not 0 <= speaker_id < num_speakers:
        raise ValueError(f"speaker_id {speaker_id} outside 0..{num_speakers - 1}")
    return speaker_id


class PiperEngine:
    """TtsEngine over piper-tts voices (`*.onnx` + `*.onnx.json`) found in `voices_dir`."""

    key = "piper"

    def __init__(
        self, voices_dir: Path, *, loader: Callable[[Path, Path], Any] | None = None
    ) -> None:
        self._voices_dir = Path(voices_dir)
        self._loader = loader or _load_piper_voice  # tests inject a fake PiperVoice
        # Voice files are not re-read while the engine lives; restart to pick up replaced ones.
        self._configs: dict[Path, _VoiceConfig] = {}
        self._models: dict[Path, Any] = {}
        self._local = threading.local()  # per thread: warnings of that thread's last synthesize
        self.version = _engine_version()

    def available(self) -> bool:
        return _piper_installed()

    @property
    def last_warnings(self) -> list[str]:
        """Warnings of the calling thread's latest `synthesize`; empty before the first."""
        return list(getattr(self._local, "warnings", ()))

    def voice_version(self, voice: VoiceInfo) -> str:
        """Model size plus config hash: replacing a voice file changes it, so its WAVs re-render."""
        model = self._model_path(voice)
        try:
            config = model.with_name(model.name + ".json").read_bytes()
            return f"{model.stat().st_size}-{hashlib.sha256(config).hexdigest()[:12]}"
        except OSError:
            return "missing"  # synthesize() then reports the missing file

    def voices(self) -> list[VoiceInfo]:
        return scan_installed(self._voices_dir)

    def render(self, segment: Segment, voice: VoiceInfo) -> str:
        """Piper input text: override surfaces become inline `[[ipa]]` blocks in espeak layout."""
        return _render_segment(segment, self._config(voice).symbols, voice.key)[0]

    def script_warnings(self, script: SpokenScript, voice: VoiceInfo) -> tuple[str, ...]:
        """What rendering could not honor (dropped symbols, unmatched surfaces), deduplicated."""
        return self._render_all(script, voice)[1]

    def synthesize(
        self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions, out_wav: Path
    ) -> Audio:
        """Write the script as a 16-bit mono WAV. `out_wav` is overwritten; missing or partial on
        error."""
        self._local.warnings = []
        if voice.engine != self.key:
            raise ValueError(f"voice {voice.key!r} belongs to engine {voice.engine!r}, not 'piper'")
        model = self._model_path(voice)
        if not model.exists():
            raise FileNotFoundError(f"Piper voice model not found: {model}")
        config = self._config(voice)
        length_scale = config.length_scale / _checked_speed(opts.speed)
        speaker = _checked_speaker(opts.speaker_id, config.num_speakers)
        texts, warnings = self._render_all(script, voice)
        self._local.warnings = list(warnings)
        for warning in warnings:
            _LOG.warning("%s", warning)

        from piper import SynthesisConfig  # lazy: loads onnxruntime

        syn_config = SynthesisConfig(speaker_id=speaker, length_scale=length_scale)
        rate = config.sample_rate
        frames = 0
        with _SYNTH_LOCK:
            piper_voice = self._piper_voice(model)
            speech = [
                np.frombuffer(
                    b"".join(
                        chunk.audio_int16_bytes
                        for unit in _units(text)
                        for chunk in piper_voice.synthesize(unit, syn_config)
                    ),
                    dtype=np.int16,
                )
                for text in texts
            ]
            trimmed = trim_letter_padding(script.segments, speech, rate)
            with wave.open(str(out_wav), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                for segment, sound in zip(script.segments, trimmed, strict=True):
                    wav.writeframes(sound.tobytes())
                    frames += len(sound)
                    silence = max(0, round(rate * segment.pause_after_ms / 1000))
                    wav.writeframes(b"\x00\x00" * silence)
                    frames += silence
        return Audio(out_wav, rate, frames / rate, cache_hit=False)

    def _render_all(
        self, script: SpokenScript, voice: VoiceInfo
    ) -> tuple[list[str], tuple[str, ...]]:
        symbols = self._config(voice).symbols
        texts: list[str] = []
        warnings: list[str] = []
        for segment in script.segments:
            text, found = _render_segment(segment, symbols, voice.key)
            texts.append(text)
            for warning in found:
                if warning not in warnings:
                    warnings.append(warning)
        return texts, tuple(warnings)

    def _model_path(self, voice: VoiceInfo) -> Path:
        if voice.path is not None:
            return voice.path
        name = voice.key.removeprefix(KEY_PREFIX)
        if not is_safe_name(name):
            raise ValueError(f"invalid voice key {voice.key!r}")
        return self._voices_dir / f"{name}.onnx"

    def _config(self, voice: VoiceInfo) -> _VoiceConfig:
        model = self._model_path(voice)
        if model not in self._configs:
            self._configs[model] = _load_config(model.with_name(model.name + ".json"))
        return self._configs[model]

    def _piper_voice(self, model: Path) -> Any:
        """Load on first use. Call with `_SYNTH_LOCK` held."""
        if model not in self._models:
            self._models[model] = self._loader(model, model.with_name(model.name + ".json"))
        return self._models[model]
