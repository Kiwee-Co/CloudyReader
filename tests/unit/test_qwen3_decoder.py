"""Qwen3 decoder gate: source gate, band mask, class patch, load-time window probe."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import types
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from cloudyreader.engines import qwen3_decoder as qd
from cloudyreader.engines.qwen3_decoder import (
    FIX_MARKERS,
    KNOWN_BUGGY,
    WAITING,
    DecoderGate,
    DecoderPatchRefused,
    apply_decoder_patch,
    band_mask,
    decoder_gate,
    decoder_source,
    record_hash,
    window_probe,
)

ROOT = Path(__file__).resolve().parents[2]
REL = "mlx_audio/tts/models/qwen3_tts/speech_tokenizer.py"
NP = SimpleNamespace(array=np.asarray, float32=np.float32)  # numpy stands in for mlx.core
PATCH = DecoderGate("patch", "test")


def _run(code: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    return subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def _source(tmp_path: Path, text: str, name: str = "speech_tokenizer.py") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --- decoder_gate ----------------------------------------------------------------------------


def test_record_hash_is_the_wheel_record_form():
    assert record_hash(b"") == "47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU"
    assert "UnoPuRKYj8X3BnYinsDEp32S3VwlBKStP1dRZu5aqgc" in KNOWN_BUGGY


def test_gate_is_upstream_when_both_markers_are_present(tmp_path):
    fixed = _source(tmp_path, "class X:\n" + "".join(f"    {m},\n" for m in FIX_MARKERS))
    half = _source(tmp_path, f"class X:\n    {FIX_MARKERS[0]}\n", name="half.py")

    assert decoder_gate(fixed).mode == "upstream"
    assert decoder_gate(half).mode == "blocked"


def test_gate_is_patch_for_the_known_hash(tmp_path, monkeypatch):
    src = _source(tmp_path, "mask = create_additive_causal_mask(total_len)\n")
    monkeypatch.setattr(qd, "KNOWN_BUGGY", frozenset({record_hash(src.read_bytes())}))

    gate = decoder_gate(src)

    assert gate == DecoderGate("patch", gate.reason)
    assert gate.reason


def test_gate_is_blocked_for_an_unknown_source_and_names_a_hash_prefix(tmp_path):
    src = _source(tmp_path, "# a refactored decoder\n")

    gate = decoder_gate(src)
    missing = decoder_gate(tmp_path / "gone.py")

    assert gate.mode == "blocked"
    assert gate.reason.startswith(WAITING)
    assert record_hash(src.read_bytes())[:8] in gate.reason
    assert missing.mode == "blocked" and missing.reason.startswith(WAITING)


def test_gate_is_memoized_by_path_size_and_mtime(tmp_path, monkeypatch):
    src = _source(tmp_path, "# one\n")
    first = decoder_gate(src)
    reads = []
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: reads.append(self) or real(self))

    again = decoder_gate(src)
    src.write_text("class X:\n" + "".join(f"    {m},\n" for m in FIX_MARKERS), encoding="utf-8")
    changed = decoder_gate(src)

    assert again is first and first.mode == "blocked"
    assert changed.mode == "upstream"
    assert reads == [src]


def test_gate_without_an_installed_mlx_audio_is_blocked(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlx_audio", types.ModuleType("mlx_audio"))  # no __spec__

    assert decoder_source() is None
    assert decoder_gate() == DecoderGate("blocked", f"{WAITING} (decoder source not found)")


def test_gate_names_an_unreadable_source(tmp_path, monkeypatch):
    src = _source(tmp_path, "# unreadable\n")

    def deny(self):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_bytes", deny)

    gate = decoder_gate(src)

    assert gate.mode == "blocked"
    assert gate.reason == f"{WAITING} (cannot read the decoder: Permission denied)"


def test_decoder_source_finds_the_file_under_the_package_spec(tmp_path, monkeypatch):
    pkg = tmp_path / "site" / "mlx_audio"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("raise RuntimeError('mlx_audio was imported')\n")
    monkeypatch.delitem(sys.modules, "mlx_audio", raising=False)
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    assert decoder_source() is None  # a build without the Qwen3-TTS model package
    src = pkg / "tts" / "models" / "qwen3_tts" / "speech_tokenizer.py"
    src.parent.mkdir(parents=True)
    src.write_text("# decoder\n")

    assert decoder_source() == src
    assert "mlx_audio" not in sys.modules


def test_gate_reads_the_file_without_importing_mlx_audio(tmp_path):
    pkg = tmp_path / "site" / "mlx_audio"
    (pkg / "tts" / "models" / "qwen3_tts").mkdir(parents=True)
    (pkg / "__init__.py").write_text("raise RuntimeError('mlx_audio was imported')\n")
    marked = "".join(f"    {m},\n" for m in FIX_MARKERS)
    (pkg / "tts" / "models" / "qwen3_tts" / "speech_tokenizer.py").write_text("x = (\n" + marked)
    code = textwrap.dedent(
        f"""
        import sys
        sys.path[:0] = [{str(tmp_path / "site")!r}, {str(ROOT)!r}]
        from cloudyreader.engines.qwen3_decoder import decoder_gate
        print(decoder_gate().mode)
        heavy = [m for m in ("mlx_audio", "mlx", "numpy") if m in sys.modules]
        assert not heavy, heavy
        """
    )

    result = _run(code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["upstream"]


def test_known_hash_matches_the_installed_wheel_record():
    try:
        dist = metadata.distribution("mlx-audio")
    except metadata.PackageNotFoundError:
        pytest.skip("mlx-audio is not installed")
    entry = next((f for f in dist.files or () if str(f) == REL), None)
    if entry is None:
        pytest.skip("this mlx-audio has no Qwen3-TTS decoder")
    path = Path(entry.locate())
    data = path.read_bytes()

    gate = decoder_gate(path)

    assert entry.hash is not None and entry.hash.mode == "sha256"
    assert record_hash(data) == entry.hash.value and len(data) == entry.size
    if dist.version in ("0.6.3", "0.6.4"):  # speech_tokenizer.py is byte-identical in both
        assert entry.hash.value in KNOWN_BUGGY and entry.size == 54_223
        assert gate.mode == "patch"
    else:
        assert gate.mode != "patch"  # a bump never patches a file nobody audited


# --- band_mask -------------------------------------------------------------------------------


def _reference(rows: int, cols: int, window: int, offset: int) -> np.ndarray:
    return np.array(
        [[0 <= (offset + i) - j < window for j in range(cols)] for i in range(rows)], dtype=bool
    )


@pytest.mark.parametrize("size", [1, 72, 73, 300])
def test_band_mask_matches_the_reference_definition(size):
    np.testing.assert_array_equal(band_mask(size, size, 72, np), _reference(size, size, 72, 0))


def test_band_mask_with_an_offset_and_a_wide_window():
    np.testing.assert_array_equal(band_mask(4, 80, 72, np), _reference(4, 80, 72, 76))
    np.testing.assert_array_equal(band_mask(3, 10, 4, np, offset=2), _reference(3, 10, 4, 2))
    np.testing.assert_array_equal(band_mask(5, 5, 99, np), np.tril(np.ones((5, 5), dtype=bool)))
    with pytest.raises(ValueError, match="window=0"):
        band_mask(2, 2, 0, np)


# --- apply_decoder_patch ---------------------------------------------------------------------


def _fake_class() -> type:
    class FakeDecoderTransformer:
        def __init__(self, window: int | None) -> None:
            self.config = SimpleNamespace(sliding_window=window)
            self.seen: list[tuple[object, object]] = []

        def __call__(self, inputs_embeds, mask=None, cache=None):
            self.seen.append((mask, cache))
            return inputs_embeds

    return FakeDecoderTransformer


def test_patch_adds_a_band_mask_and_leaves_explicit_masks_and_caches_alone():
    cls = _fake_class()
    assert apply_decoder_patch(PATCH, target=cls, xp=np) is None
    model, frames = cls(3), np.zeros((1, 5, 2))
    explicit, cache = np.ones((5, 5), dtype=bool), [object()]

    model(frames)
    model(frames, explicit)
    model(frames, cache=cache)
    model(np.zeros((1, 1, 2)))
    cls(None)(frames)

    np.testing.assert_array_equal(model.seen[0][0], band_mask(5, 5, 3, np))
    assert model.seen[0][1] is None
    assert model.seen[1][0] is explicit
    assert model.seen[2] == (None, cache)
    assert model.seen[3] == (None, None)


def test_patch_is_idempotent_and_refuses_when_blocked():
    cls, other = _fake_class(), _fake_class()
    original, untouched = cls.__call__, other.__call__

    apply_decoder_patch(PATCH, target=cls, xp=np)
    wrapped = cls.__call__
    apply_decoder_patch(PATCH, target=cls, xp=np)
    model = cls(3)
    model(np.zeros((1, 4, 1)))
    blocked = DecoderGate("blocked", f"{WAITING} (unknown decoder abcdefgh)")
    with pytest.raises(DecoderPatchRefused, match="unknown decoder abcdefgh"):
        apply_decoder_patch(blocked, target=other, xp=np)

    assert cls.__call__ is wrapped and wrapped.__wrapped__ is original
    assert len(model.seen) == 1
    apply_decoder_patch(DecoderGate("upstream", ""), target=other, xp=np)
    assert other.__call__ is untouched


def _mask_decoder_class() -> type:
    class DecoderTransformer:
        """numpy stand-in: each layer averages the frames its mask allows (default: every past
        frame, like mlx-audio 0.6.3's plain causal mask)."""

        def __init__(self, config):
            self.config = config
            self.layers = [None] * config.num_hidden_layers

        def __call__(self, inputs_embeds, mask=None, cache=None):
            x = np.asarray(inputs_embeds, dtype=np.float64)
            frames = x.shape[1]
            allowed = np.tril(np.ones((frames, frames), dtype=bool)) if mask is None else mask
            weights = np.asarray(allowed, dtype=np.float64)
            for _ in self.layers:
                x = np.tanh(x + (weights @ x[0])[None] / weights.sum(axis=1)[None, :, None])
            return x

    return DecoderTransformer


def _fake_mlx_audio(monkeypatch, decoder: type) -> list[dict]:
    """Fake mlx.core (numpy) and mlx-audio's Qwen3 config and decoder modules."""
    configs: list[dict] = []
    core = types.ModuleType("mlx.core")
    core.array, core.arange, core.float32 = np.asarray, np.arange, np.float32
    config = types.ModuleType(qd._CONFIG)
    config.Qwen3TTSTokenizerDecoderConfig = lambda **kw: configs.append(kw) or SimpleNamespace(**kw)
    target = types.ModuleType(qd._TARGET)
    target.DecoderTransformer = decoder
    parents = (
        "mlx",
        "mlx_audio",
        "mlx_audio.tts",
        "mlx_audio.tts.models",
        "mlx_audio.tts.models.qwen3_tts",
    )
    for name in parents:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    for name, module in (("mlx.core", core), (qd._CONFIG, config), (qd._TARGET, target)):
        monkeypatch.setitem(sys.modules, name, module)
    return configs


def test_patch_resolves_the_mlx_audio_class_and_mlx_core_by_default(monkeypatch):
    cls = _fake_class()
    _fake_mlx_audio(monkeypatch, cls)

    apply_decoder_patch(PATCH)
    model = cls(2)
    model(np.zeros((1, 3, 1)))

    np.testing.assert_array_equal(model.seen[0][0], band_mask(3, 3, 2, np))


# --- window_probe ----------------------------------------------------------------------------


class NumpyDecoder:
    """Toy decoder: each layer mixes every frame with its window (or its whole past)."""

    def __init__(self, window: int, layers: int = 2, latent: int = 3, *, full: bool = False):
        self.config = SimpleNamespace(sliding_window=window, latent_dim=latent)
        self.layers = [object()] * layers
        self.full = full

    def __call__(self, inputs_embeds, mask=None, cache=None):
        x = np.asarray(inputs_embeds, dtype=np.float64)
        for _ in self.layers:
            out = np.empty_like(x)
            for t in range(x.shape[1]):
                lo = 0 if self.full else max(0, t - self.config.sliding_window + 1)
                out[:, t] = np.tanh(x[:, lo : t + 1].mean(axis=1) + x[:, t])
            x = out
        return x


def test_probe_detects_influence_beyond_the_window():
    assert qd._window_holds(NumpyDecoder(window=4), NP) is True
    assert qd._window_holds(NumpyDecoder(window=1, layers=1), NP) is True
    assert qd._window_holds(NumpyDecoder(window=4, full=True), NP) is False


def test_window_probe_runs_a_tiny_decoder_of_the_installed_class(monkeypatch):
    decoder = _mask_decoder_class()
    configs = _fake_mlx_audio(monkeypatch, decoder)

    before = window_probe()  # the class as shipped: a plain causal mask
    apply_decoder_patch(PATCH)
    after = window_probe()

    assert (before, after) == (False, True)
    assert configs[0] == {"sliding_window": qd.PROBE_WINDOW, **qd._PROBE_DIMS}


def test_window_probe_is_false_when_it_cannot_build_the_decoder(monkeypatch):
    _fake_mlx_audio(monkeypatch, _mask_decoder_class())
    monkeypatch.setitem(sys.modules, "mlx.core", None)  # no mlx: the import fails

    assert window_probe() is False


class _Broken(NumpyDecoder):
    def __init__(self, kind: str) -> None:
        super().__init__(window=3)
        self.kind = kind

    def __call__(self, inputs_embeds, mask=None, cache=None):
        if self.kind == "raises":
            raise RuntimeError("Metal device lost")
        x = np.asarray(inputs_embeds, dtype=np.float64)
        return np.full_like(x, np.nan) if self.kind == "nan" else np.zeros_like(x)


@pytest.mark.parametrize("kind", ["raises", "nan", "dead"])
def test_probe_fails_safe(kind):
    assert qd._window_holds(_Broken(kind), NP) is False


def test_probe_needs_a_window_and_a_latent_size():
    no_window, no_latent = NumpyDecoder(window=3), NumpyDecoder(window=3)
    no_window.config = SimpleNamespace(latent_dim=3)
    no_latent.config = SimpleNamespace(sliding_window=3)

    assert qd._window_holds(no_window, NP) is False
    assert qd._window_holds(no_latent, NP) is False


_REAL_DECODER = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, sys.argv[1])
    try:
        import mlx.core as mx
        import numpy as np
        from mlx_audio.lm.models.base import create_causal_mask
        from mlx_audio.tts.models.qwen3_tts.config import Qwen3TTSTokenizerDecoderConfig
        from mlx_audio.tts.models.qwen3_tts.speech_tokenizer import DecoderTransformer
    except Exception as exc:
        print("SKIP", type(exc).__name__, exc)
        raise SystemExit(0)
    from cloudyreader.engines.qwen3_decoder import DecoderGate, apply_decoder_patch, window_probe

    before = window_probe()
    apply_decoder_patch(DecoderGate("patch", "test"))
    after = window_probe()
    mx.random.seed(0)
    cfg = Qwen3TTSTokenizerDecoderConfig(
        latent_dim=16, hidden_size=32, intermediate_size=64, head_dim=8, num_attention_heads=4,
        num_key_value_heads=4, num_hidden_layers=2, sliding_window=8,
        max_position_embeddings=256, layer_scale_initial_scale=1.0,
    )
    model = DecoderTransformer(cfg)
    x = mx.random.normal((1, 40, 16))
    patched = np.array(model(x))
    upstream = np.array(
        DecoderTransformer.__call__.__wrapped__(model, x, create_causal_mask(40, window_size=8))
    )
    print("RESULT", before, after, float(np.max(np.abs(patched - upstream))))
    """
)


@pytest.mark.slow
@pytest.mark.skipif(find_spec("mlx") is None, reason="needs mlx")
@pytest.mark.skipif(find_spec("mlx_audio") is None, reason="needs mlx-audio")
def test_real_decoder_ignores_frames_beyond_the_window():
    result = subprocess.run(
        [sys.executable, "-I", "-c", _REAL_DECODER, str(ROOT)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    lines = result.stdout.splitlines()
    skip = next((x for x in lines if x.startswith("SKIP ")), None)
    if skip:
        pytest.skip(skip)
    line = next((x for x in lines if x.startswith("RESULT ")), None)
    assert line, result.stdout[-2000:] + result.stderr[-2000:]
    _, before, after, diff = line.split()

    assert before == "False"  # mlx-audio 0.6.3 as shipped: far frames leak into the output
    assert after == "True"
    assert float(diff) <= 1e-5  # the patch equals upstream's own windowed mask


def test_importing_the_decoder_gate_loads_no_heavy_module():
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        from cloudyreader.engines import qwen3_decoder
        qwen3_decoder.decoder_gate()
        heavy = [m for m in ("mlx", "mlx_audio", "transformers", "huggingface_hub", "torch",
                             "numpy") if m in sys.modules]
        assert not heavy, heavy
        """
    )

    result = _run(code)

    assert result.returncode == 0, result.stderr
