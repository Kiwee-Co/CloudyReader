"""Every engine's real voice rows, built by the engine's own code and without loading a model."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cloudyreader.engines import kokoro, qwen3_tts
from cloudyreader.engines.chatterbox_turbo import ChatterboxTurboEngine
from cloudyreader.engines.kokoro import KokoroEngine
from cloudyreader.engines.qwen3_tts import Qwen3TtsEngine
from cloudyreader.models import VoiceInfo
from cloudyreader.voice_meta import PIPER_GENDERS
from cloudyreader.voices import scan_installed


def real_voices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[VoiceInfo]:
    """All 28 Kokoro voices (files missing, so dimmed), the 5 pinned Piper voices, Qwen3-TTS and
    Chatterbox Turbo (installed)."""
    monkeypatch.setattr(kokoro, "_supported_platform", lambda: True)
    rows = KokoroEngine(tmp_path / "kokoro", all_voices=True).voices()
    folder = tmp_path / "piper"
    folder.mkdir()
    for vid in PIPER_GENDERS:
        (folder / f"{vid}.onnx").write_bytes(b"model")
        config = {"language": {"code": vid.split("-")[0]}, "audio": {"quality": "medium"}}
        (folder / f"{vid}.onnx.json").write_text(json.dumps(config), encoding="utf-8")
    rows += scan_installed(folder)
    engine = SimpleNamespace(model_dir=tmp_path / "models")  # all `_voice` reads of self
    rows += [Qwen3TtsEngine._voice(engine, vid, installed=True) for vid in qwen3_tts.VOICES]
    rows.append(ChatterboxTurboEngine._voice(engine, installed=True))
    return rows
