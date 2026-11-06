"""scripts/make_letter_clips.py: takes rendered on a fake engine, then written as clips."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from cloudyreader.config import Settings
from cloudyreader.engines import mlxkit
from cloudyreader.engines.letter_clips import MANIFEST, LetterClips
from cloudyreader.engines.mlxkit import EngineError, write_pcm16
from cloudyreader.models import Audio, Segment, VoiceInfo

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "make_letter_clips.py"
RATE = 24_000


def load_script():
    spec = importlib.util.spec_from_file_location("make_letter_clips", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mlc = load_script()


class FakeEngine:
    """Synthesizes like the MLX engines: say_letter, one backend call seeded by mlxkit.seed_for."""

    def __init__(self, key: str, *, voice: str = "ryan", fail: str = "") -> None:
        self.key, self.voice_id, self.fail = key, voice, fail
        self.backend = SimpleNamespace(render=self.render)
        self._memo: dict = {"a unit": "memoized"}
        self.unavailable_reason = "no weights"
        self.closed = False
        self.memo_at_synthesis: list[int] = []

    def voices(self) -> list[VoiceInfo]:
        return [VoiceInfo(f"{self.key}:{self.voice_id}", self.key, "x", "en", "x", 1, True)]

    def render(self, text: str, voice: str, *, seed: int, budget_s: float):
        return np.full(RATE // 2, (seed % 100) / 200, dtype=np.float32), RATE

    def synthesize(self, script, voice, opts, out: Path) -> Audio:
        (segment,) = script.segments
        assert segment.pause_after_ms == 0
        self.memo_at_synthesis.append(len(self._memo))
        text = mlxkit.say_letter(segment.text)
        if segment.text == self.fail:
            raise EngineError(f"could not say {text!r}")
        seed = mlxkit.seed_for(voice.key, text, 0)
        audio, rate = self.backend.render(text, self.voice_id, seed=seed, budget_s=2.0)
        write_pcm16(out, audio, rate)
        return Audio(out, rate, len(audio) / rate, False)

    def close(self) -> None:
        self.closed = True


def settings(tmp_path: Path) -> Settings:
    return Settings(tmp_path, tmp_path / "cache", tmp_path / "voices", tmp_path / "models")


def test_render_writes_each_take_with_the_app_seed_first_then_salted_ones(tmp_path: Path) -> None:
    engines: list[FakeEngine] = []

    def make(name: str, _settings: Settings) -> FakeEngine:
        engines.append(FakeEngine(name, fail="Y."))
        return engines[-1]

    seed_for = mlxkit.seed_for
    rows = mlc.render(
        tmp_path / "out",
        ["qwen3_tts:ryan"],
        "WY",
        range(2),
        settings=settings(tmp_path),
        engine_for=make,
    )

    assert mlxkit.seed_for is seed_for  # restored
    assert json.loads((tmp_path / "out" / mlc.TAKES).read_text()) == rows
    w0, w1, y0, _ = rows
    assert w0["seed"] == seed_for("qwen3_tts:ryan", "double you.", 0)  # the app's own reading
    assert w1["seed"] == seed_for("qwen3_tts:ryan", "double you.", mlc.SALT)
    assert (w0["text"], w0["seconds"], w0["error"]) == ("double you.", 0.5, None)
    assert Path(w0["wav"]).name == "qwen3_tts-ryan-W-t0.wav" and Path(w0["wav"]).is_file()
    assert y0["wav"] is None and y0["seed"] is None and "could not say" in y0["error"]
    assert engines[0].memo_at_synthesis == [0, 0, 0, 0]  # never a memoized take
    assert engines[0].closed


def test_render_stops_on_a_voice_that_cannot_speak(tmp_path: Path) -> None:
    def make(name: str, _settings: Settings) -> FakeEngine:
        return FakeEngine(name, voice="aiden")

    with pytest.raises(SystemExit, match="qwen3_tts:ryan cannot speak here: no weights"):
        mlc.render(tmp_path, ["qwen3_tts:ryan"], settings=settings(tmp_path), engine_for=make)


def test_write_copies_the_picks_and_merges_the_manifest(tmp_path: Path) -> None:
    def make(name: str, _settings: Settings) -> FakeEngine:
        return FakeEngine(name)

    out, clips = tmp_path / "out", tmp_path / "clips"
    mlc.render(
        out, ["qwen3_tts:ryan"], "WZ", range(3), settings=settings(tmp_path), engine_for=make
    )

    mlc.write(out, ["qwen3_tts:ryan:Z=2"], clips)
    listed = mlc.write(out, ["qwen3_tts:ryan:W=1"], clips)

    assert [(e["letter"], e["take"]) for e in listed] == [("W", 1), ("Z", 2)]
    data = (clips / "qwen3_tts" / "ryan" / "W.wav").read_bytes()
    assert data == (out / "qwen3_tts-ryan-W-t1.wav").read_bytes()  # byte for byte
    assert listed[0] | {"seed": 0} == {
        "engine": "qwen3_tts",
        "voice": "ryan",
        "letter": "W",
        "rate": RATE,
        "frames": RATE // 2,
        "sha256": hashlib.sha256(data).hexdigest(),
        "take": 1,
        "seed": 0,
        "text": "double you.",
    }
    assert json.loads((clips / MANIFEST).read_text()) == {"clips": listed}
    clip = LetterClips(clips).get("qwen3_tts", "ryan", Segment("W.", 300), RATE)
    assert clip is not None and len(clip) == RATE // 2


def test_write_refuses_a_take_that_was_never_rendered(tmp_path: Path) -> None:
    (tmp_path / mlc.TAKES).write_text("[]")

    with pytest.raises(SystemExit, match="no rendered take for qwen3_tts:ryan:W=9"):
        mlc.write(tmp_path, ["qwen3_tts:ryan:W=9"], tmp_path / "clips")


@pytest.mark.parametrize("letters", ["", "WA", "w"])
def test_main_takes_only_choice_letters(letters: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        mlc.main(["render", "out", "--letters", letters])

    assert stop.value.code == 2
    assert "--letters takes letters of WXYZ" in capsys.readouterr().err


def test_main_runs_render_and_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(mlc, "render", lambda *args: calls.append(("render", *args)))
    monkeypatch.setattr(mlc, "write", lambda *args: calls.append(("write", *args)))

    assert mlc.main(["render", str(tmp_path), "--takes", "3", "--first", "5"]) == 0
    assert mlc.main(["write", str(tmp_path), "qwen3_tts:ryan:W=5"]) == 0

    assert calls == [
        ("render", tmp_path, mlc.VOICES, "WXYZ", range(5, 8)),
        ("write", tmp_path, ["qwen3_tts:ryan:W=5"]),
    ]
