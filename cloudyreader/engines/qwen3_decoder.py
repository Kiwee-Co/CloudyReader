"""Qwen3-TTS decoder gate: mlx-audio 0.6.3 decodes past its trained 72-frame attention window.

`decoder_gate` reads mlx-audio's decoder source as bytes (it never imports mlx_audio) and picks
`upstream` (fix present), `patch` (the audited buggy file) or `blocked` (anything else).
"""

from __future__ import annotations

import base64
import functools
import hashlib
import importlib
import importlib.util
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

# speech_tokenizer.py of mlx-audio 0.6.3 and 0.6.4 (byte-identical, 54,223 B), in RECORD form.
KNOWN_BUGGY = frozenset({"UnoPuRKYj8X3BnYinsDEp32S3VwlBKStP1dRZu5aqgc"})
# Lines added by the upstream fix (mlx-audio PR #1117, merge f65753b5); 0.6.3 has neither.
FIX_MARKERS = (
    "RotatingKVCache(max_size=self.config.sliding_window)",
    "window_size=self.config.sliding_window",
)
WAITING = "waiting for a Qwen3 decoder fix"

Mode = Literal["upstream", "patch", "blocked"]

_SOURCE = ("tts", "models", "qwen3_tts", "speech_tokenizer.py")
_TARGET = "mlx_audio.tts.models.qwen3_tts.speech_tokenizer"
_CONFIG = "mlx_audio.tts.models.qwen3_tts.config"
_PATCHED = "_cloudyreader_window_patch"
# window_probe's decoder: real class, tiny random weights; layer scale 1 makes attention audible.
PROBE_WINDOW = 8
_PROBE_DIMS: Mapping[str, Any] = MappingProxyType(
    {
        "latent_dim": 16,
        "hidden_size": 32,
        "intermediate_size": 64,
        "head_dim": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
        "num_hidden_layers": 2,
        "layer_scale_initial_scale": 1.0,
    }
)


@dataclass(frozen=True)
class DecoderGate:
    mode: Mode
    reason: str


class DecoderPatchRefused(RuntimeError):
    """The gate is blocked: the decoder source is not one this patch was written for."""


_LOCK = threading.Lock()
_MEMO: dict[tuple[str, int, int], DecoderGate] = {}


def record_hash(data: bytes) -> str:
    """SHA-256 in the wheel RECORD form: urlsafe base64 without padding."""
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def decoder_source() -> Path | None:
    """mlx-audio's `speech_tokenizer.py`, found with a top-level spec (runs no package code)."""
    try:
        spec = importlib.util.find_spec("mlx_audio")
    except (ImportError, ValueError):  # ValueError: a stub module without __spec__
        return None
    for root in (spec.submodule_search_locations or ()) if spec else ():
        path = Path(root).joinpath(*_SOURCE)
        if path.is_file():
            return path
    return None


def _classify(data: bytes) -> DecoderGate:
    text = data.decode("utf-8", errors="replace")
    if all(marker in text for marker in FIX_MARKERS):
        return DecoderGate("upstream", "mlx-audio applies the decoder window")
    digest = record_hash(data)
    if digest in KNOWN_BUGGY:
        return DecoderGate("patch", "mlx-audio 0.6.3 decoder: window patched in")
    return DecoderGate("blocked", f"{WAITING} (unknown decoder {digest[:8]})")


def decoder_gate(source: Path | None = None) -> DecoderGate:
    """The gate for the Qwen engine and its download; memoized by (path, size, mtime_ns)."""
    path = source if source is not None else decoder_source()
    if path is None:
        return DecoderGate("blocked", f"{WAITING} (decoder source not found)")
    try:
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        with _LOCK:
            known = _MEMO.get(key)
        if known is not None:
            return known
        gate = _classify(path.read_bytes())
    except OSError as exc:
        return DecoderGate("blocked", f"{WAITING} (cannot read the decoder: {exc.strerror or exc})")
    with _LOCK:
        _MEMO[key] = gate
    return gate


def band_mask(rows: int, cols: int, window: int, xp: Any, *, offset: int | None = None) -> Any:
    """Boolean mask for numpy or mlx.core: query i, at position offset + i (default cols - rows),
    may attend key j iff 0 <= offset + i - j < window."""
    if rows < 1 or cols < 1 or window < 1:
        raise ValueError(f"band_mask needs positive sizes: rows={rows} cols={cols} window={window}")
    start = cols - rows if offset is None else offset
    distance = xp.arange(start, start + rows)[:, None] - xp.arange(cols)[None, :]
    return (distance >= 0) & (distance < window)


def apply_decoder_patch(gate: DecoderGate, *, target: type | None = None, xp: Any = None) -> None:
    """Band `DecoderTransformer`'s default mask to its sliding window. Call before `load_model`
    so `mx.compile` traces the patched call. Idempotent; a no-op upstream; refuses when blocked."""
    if gate.mode == "blocked":
        raise DecoderPatchRefused(gate.reason)
    if gate.mode == "upstream":
        return
    if target is None:
        target = importlib.import_module(_TARGET).DecoderTransformer
    if xp is None:
        xp = importlib.import_module("mlx.core")
    with _LOCK:
        if not getattr(target.__call__, _PATCHED, False):
            target.__call__ = _windowed(target.__call__, xp)


def _windowed(original: Callable[..., Any], xp: Any) -> Callable[..., Any]:
    @functools.wraps(original)
    def __call__(self: Any, inputs_embeds: Any, mask: Any = None, cache: Any = None) -> Any:
        # Only a cache-free call without a mask (the engine's whole-utterance decode) changes;
        # explicit masks and the streaming KV cache pass through untouched.
        window = getattr(getattr(self, "config", None), "sliding_window", None)
        rows = inputs_embeds.shape[1]
        if mask is None and cache is None and window and rows > 1:
            mask = band_mask(rows, rows, int(window), xp)
        return original(self, inputs_embeds, mask, cache)

    setattr(__call__, _PATCHED, True)
    return __call__


def window_probe() -> bool:
    """A tiny random DecoderTransformer of the real, possibly patched class: frames beyond its
    window must not change the last output. Run it after the patch and before `load_model`."""
    try:
        mx = importlib.import_module("mlx.core")
        config = importlib.import_module(_CONFIG).Qwen3TTSTokenizerDecoderConfig
        decoder = importlib.import_module(_TARGET).DecoderTransformer
        tiny = decoder(config(sliding_window=PROBE_WINDOW, **_PROBE_DIMS))
    except Exception:  # no mlx, or a refactored decoder: the engine stays blocked
        return False
    return _window_holds(tiny, mx)


def _window_holds(decoder_transformer: Any, mx: Any, *, seed: int = 0, margin: int = 4) -> bool:
    """True when frames past the last frame's reach (layers x (window - 1) + 1) leave its output
    unchanged and a frame inside the window changes it. Errors and non-finite output give False."""
    import numpy as np

    config = getattr(decoder_transformer, "config", None)
    window = int(getattr(config, "sliding_window", 0) or 0)
    latent = int(getattr(config, "latent_dim", 0) or 0)
    if window < 1 or latent < 1:
        return False
    layers = len(getattr(decoder_transformer, "layers", None) or ()) or 1
    frames = layers * (window - 1) + 1 + margin
    rng = np.random.default_rng(seed)
    base = rng.standard_normal((1, frames, latent)).astype(np.float32)
    far, near = base.copy(), base.copy()
    far[:, :margin] = 3 * rng.standard_normal((1, margin, latent))
    near[:, -2 if window > 1 else -1] = 3 * rng.standard_normal(latent)
    try:
        last = [_last_frame(decoder_transformer(mx.array(x)), mx, np) for x in (base, far, near)]
    except Exception:  # any failure keeps the engine blocked
        return False
    if not all(np.isfinite(row).all() for row in last):
        return False
    inside = float(np.max(np.abs(last[2] - last[0])))
    beyond = float(np.max(np.abs(last[1] - last[0])))
    return inside > 1e-6 and beyond <= 1e-3 * inside


def _last_frame(out: Any, mx: Any, np: Any) -> Any:
    if hasattr(out, "astype"):
        out = out.astype(mx.float32)  # numpy has no bfloat16
    return np.asarray(out, dtype=np.float64)[0, -1]
