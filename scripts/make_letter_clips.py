"""Render takes of the lone choice letters; write the chosen takes as the engines' letter clips.

Qwen3-TTS (Ryan, Aiden) and Chatterbox Turbo read a bare letter as a word on some seeds, so they
play a clip from cloudyreader/engines/letter_clips/ instead (see letter_clips.py). Run it yourself
on an Apple Silicon Mac with the kokoro extra, CLOUDYREADER_DATA_DIR naming a data folder whose
models are installed:

    python scripts/make_letter_clips.py render OUT [--voice qwen3_tts:ryan ...] [--takes 8]
    python scripts/make_letter_clips.py write OUT qwen3_tts:ryan:W=3 [...]

`render` writes OUT/<engine>-<voice>-<letter>-t<take>.wav and OUT/takes.json. Each take is the
engine's own synthesize() of the one-segment script "W." with no clip and no pause. Take 0 uses the
app's seed; take k adds 1000 x k to every attempt, so the model draws another reading. Judge the
takes outside the repo, by ear or with recognizers: no recognizer ships here. `write` copies each
chosen take byte for byte to letter_clips/<engine>/<voice>/<letter>.wav and merges it into
manifest.json; every other clip stays as it was.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import wave
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cloudyreader.config import Settings, load_settings
from cloudyreader.engines import mlxkit
from cloudyreader.engines.letter_clips import FOLDER, LETTERS, MANIFEST, LetterClips
from cloudyreader.models import RenderOptions, Segment, SpokenScript

ROOT = Path(__file__).resolve().parents[1]
CLIPS = ROOT / "cloudyreader" / "engines" / FOLDER
VOICES = ("qwen3_tts:ryan", "qwen3_tts:aiden", "chatterbox_turbo:builtin")
TAKES = "takes.json"
SALT = 1000  # take k moves every attempt number by SALT x k


def make_engine(name: str, settings: Settings) -> Any:
    """The real engine, with no clips: a take is always the model's own reading."""
    if name == "qwen3_tts":
        from cloudyreader.engines.qwen3_tts import Qwen3TtsEngine

        return Qwen3TtsEngine(settings, clips=LetterClips(None))
    if name == "chatterbox_turbo":
        from cloudyreader.engines.chatterbox_turbo import ChatterboxTurboEngine

        return ChatterboxTurboEngine(settings, clips=LetterClips(None))
    raise SystemExit(f"no letter clips for engine {name!r}")


@contextmanager
def salted(take: int) -> Iterator[None]:
    """mlxkit.seed_for with each attempt moved by SALT x take; take 0 is the app's own seed."""
    original = mlxkit.seed_for

    def seed_for(voice_key: str, text: str, attempt: int = 0) -> int:
        return original(voice_key, text, attempt + SALT * take)

    mlxkit.seed_for = seed_for
    try:
        yield
    finally:
        mlxkit.seed_for = original


def _seed_log(engine: Any) -> list[int]:
    """The seed of each backend call the engine makes from now on, in order."""
    seeds: list[int] = []
    backend_render = engine.backend.render

    def logged(text: str, voice: str, *, seed: int, budget_s: float) -> Any:
        seeds.append(seed)
        return backend_render(text, voice, seed=seed, budget_s=budget_s)

    engine.backend.render = logged
    return seeds


def render(
    out: Path,
    voices: Sequence[str] = VOICES,
    letters: str = LETTERS,
    takes: Sequence[int] = range(8),
    *,
    settings: Settings | None = None,
    engine_for: Callable[[str, Settings], Any] = make_engine,
) -> list[dict[str, Any]]:
    """Render every take of every letter in every voice; the rows of OUT/takes.json."""
    settings = settings if settings is not None else load_settings()
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for key in voices:
        engine_name, _, voice_id = key.partition(":")
        engine = engine_for(engine_name, settings)
        voice = next((v for v in engine.voices() if v.key == key), None)
        if voice is None:
            raise SystemExit(f"{key} cannot speak here: {engine.unavailable_reason}")
        seeds = _seed_log(engine)
        for letter in letters:
            for take in takes:
                wav = out / f"{engine_name}-{voice_id}-{letter}-t{take}.wav"
                script = SpokenScript((Segment(f"{letter}."),))
                seeds.clear()
                engine._memo.clear()  # render_text memoizes by text alone, never by seed
                row = {"engine": engine_name, "voice": voice_id, "letter": letter, "take": take}
                row["text"] = mlxkit.say_letter(f"{letter}.")
                try:
                    with salted(take):
                        audio = engine.synthesize(script, voice, RenderOptions(), wav)
                except mlxkit.EngineError as exc:  # the model said nothing usable this take
                    row |= {"wav": None, "seed": None, "seconds": 0.0, "error": str(exc)}
                else:
                    row |= {"wav": str(wav), "seed": seeds[-1], "error": None}
                    row["seconds"] = round(audio.duration_s, 3)
                rows.append(row)
                print(f"{key} {letter} t{take}: {row['seconds']} s", row["error"] or "", flush=True)
        engine.close()
    (out / TAKES).write_text(json.dumps(rows, indent=1) + "\n")
    return rows


def write(out: Path, picks: Sequence[str], clips: Path = CLIPS) -> list[dict[str, Any]]:
    """Copy each pick (`engine:voice:letter=take`) into `clips`; the merged manifest entries."""
    takes = {
        (row["engine"], row["voice"], row["letter"], row["take"]): row
        for row in json.loads((out / TAKES).read_text())
    }
    manifest = clips / MANIFEST
    entries = {}
    if manifest.exists():
        for entry in json.loads(manifest.read_text())["clips"]:
            entries[entry["engine"], entry["voice"], entry["letter"]] = entry
    for pick in picks:
        name, _, take = pick.partition("=")
        engine, voice, letter = name.split(":")
        row = takes.get((engine, voice, letter, int(take)))
        if row is None or row["wav"] is None:
            raise SystemExit(f"no rendered take for {pick}")
        data = Path(row["wav"]).read_bytes()
        with wave.open(io.BytesIO(data), "rb") as clip:
            rate, frames = clip.getframerate(), clip.getnframes()
        dest = clips / engine / voice / f"{letter}.wav"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        entries[engine, voice, letter] = {
            "engine": engine,
            "voice": voice,
            "letter": letter,
            "rate": rate,
            "frames": frames,
            "sha256": hashlib.sha256(data).hexdigest(),
            "take": row["take"],
            "seed": row["seed"],
            "text": row["text"],
        }
    listed = [entries[key] for key in sorted(entries)]
    manifest.write_text(json.dumps({"clips": listed}, indent=4) + "\n")  # prettier: 4 for JSON
    return listed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    takes = commands.add_parser("render", help="render the takes of each letter")
    takes.add_argument("out", type=Path)
    takes.add_argument("--voice", action="append", choices=VOICES, help="default: all three")
    takes.add_argument("--letters", default=LETTERS)
    takes.add_argument("--takes", type=int, default=8)
    takes.add_argument("--first", type=int, default=0, help="the first take number")
    pick = commands.add_parser("write", help="copy the chosen takes into the clip folder")
    pick.add_argument("out", type=Path)
    pick.add_argument("picks", nargs="+", metavar="ENGINE:VOICE:LETTER=TAKE")
    args = parser.parse_args(argv)
    if args.command == "render":
        if not args.letters or set(args.letters) - set(LETTERS):
            parser.error(f"--letters takes letters of {LETTERS}, got {args.letters!r}")
        numbers = range(args.first, args.first + args.takes)
        render(args.out, args.voice or VOICES, args.letters, numbers)
    else:
        write(args.out, args.picks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
