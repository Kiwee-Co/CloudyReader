"""Entry point: `python -m cloudyreader` and the `cloudyreader` console script."""

from __future__ import annotations

import argparse
import dataclasses
import importlib.metadata
import logging
import os
import platform
import sys
import tempfile
import time
import traceback
import wave
from array import array
from collections.abc import Sequence
from pathlib import Path

from cloudyreader.config import OFFLINE_ENV, Settings, load_settings
from cloudyreader.gui.names import APP_NAME, app_version
from cloudyreader.models import RenderOptions
from cloudyreader.pipeline import build_default_service

log = logging.getLogger(__name__)

# Embedded, not read from tests/: a frozen app has no source tree.
SELF_TEST_PASTE = (
    "TOSS-UP\n"
    "2) EARTH SCIENCE Multiple Choice The source of energy for the movements of\n"
    "crustal plates is currently thought to be the result of:\n"
    "W) tidal motion that produces a net westward movement of landmasses\n"
    "X) the pulling apart of the poles resulting from the Earth’s rotation\n"
    "Y) convection currents produced within the mantle\n"
    "Z) remnant magnetism\n"
)
SELF_TEST_MIN_SECONDS = 3.0
SELF_TEST_MIN_PEAK = 0.01  # of full scale
EXIT_OK, EXIT_FAILED, EXIT_NO_VOICE = 0, 1, 2
REPORTED_PACKAGES = ("piper-tts", "spacy", "scispacy", "pyside6-essentials", "py2opsin", "httpx")


def _arg_parser() -> argparse.ArgumentParser:
    # No abbreviations: whatever is not exactly ours goes to Qt untouched.
    parser = argparse.ArgumentParser(
        prog="cloudyreader",
        description="Read US DOE National Science Bowl questions aloud, with science-aware speech.",
        epilog="Any other argument goes to Qt, for example: -style fusion.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help=f"no network lookups (PubChem, UniProt); same as {OFFLINE_ENV}=1",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="read a sample question with the first Piper voice, no window and no sound; "
        "exit 0 when it works, 1 when it fails, 2 when no voice is installed",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {app_version()}")
    return parser


def _link_bundled_assets(settings: Settings) -> None:
    """A frozen app carries its voices and models in the bundle: link them into the data dir."""
    if not getattr(sys, "frozen", False):
        return
    try:
        from cloudyreader.frozen import link_bundled_assets

        link_bundled_assets(settings)
    except Exception:
        # No voice is a state the GUI and --self-test both report; a crash here would be silent.
        log.warning("could not link the bundled assets", exc_info=True)


def _dist_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "n/a"  # a frozen bundle may carry the code without its dist-info


def _measure(path: Path) -> tuple[float, float]:
    """Seconds and peak amplitude (0 to 1 of full scale) of a 16-bit WAV, stdlib only."""
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit samples, got {wav.getsampwidth() * 8}-bit")
        rate, frames = wav.getframerate(), wav.getnframes()
        samples = array("h", wav.readframes(frames))
    if sys.byteorder == "big":
        samples.byteswap()
    return frames / rate, max(map(abs, samples), default=0) / 32768


def _check_wav(path: Path, lines: list[str]) -> list[str]:
    """Report line plus the problems with the self-test WAV (empty list: all good)."""
    if not path.is_file():
        return [f"WAV missing: {path}"]
    try:
        seconds, peak = _measure(path)
    except (wave.Error, EOFError, ValueError, ZeroDivisionError) as exc:
        return [f"WAV unreadable: {exc}"]
    lines.append(f"audio     {seconds:.1f} s, peak {peak:.2f}")
    problems = []
    if seconds < SELF_TEST_MIN_SECONDS:
        problems.append(f"audio too short: {seconds:.1f} s, need {SELF_TEST_MIN_SECONDS:g} s")
    if peak <= SELF_TEST_MIN_PEAK:
        problems.append(f"audio too quiet: peak {peak:.3f}, need more than {SELF_TEST_MIN_PEAK:g}")
    return problems


def _self_test(settings: Settings) -> int:
    """Read the sample with the first Piper voice and check the WAV. No window, no sound."""
    started = time.perf_counter()
    lines = [
        f"{APP_NAME} {app_version()} self-test",
        f"python    {platform.python_version()}",
        "packages  " + ", ".join(f"{name} {_dist_version(name)}" for name in REPORTED_PACKAGES),
    ]
    code, problems = EXIT_OK, []
    try:
        with tempfile.TemporaryDirectory(
            prefix="cloudyreader-selftest-", ignore_cleanup_errors=True
        ) as scratch:
            # A fresh cache makes the read really synthesize; offline keeps it off the network.
            service = build_default_service(
                dataclasses.replace(settings, cache_dir=Path(scratch), offline=True)
            )
            voices = service.voices()
            voice = next((v for v in voices if v.engine == "piper" and v.installed), None)
            if voice is None:
                lines.append(f"voices    {len(voices)} found, no Piper voice")
                code, problems = EXIT_NO_VOICE, ["no Piper voice installed"]
            else:
                lines.append(f"voices    {len(voices)} found, using {voice.key}")
                reading = service.prepare(SELF_TEST_PASTE, voice.key, RenderOptions())
                mode = getattr(service, "entity_mode", None)
                lines.append(f"entities  {mode() if callable(mode) else 'unknown'}")
                problems = _check_wav(reading.audio.wav_path, lines)
                code = EXIT_FAILED if problems else EXIT_OK
    except Exception as exc:
        traceback.print_exc()
        code, problems = EXIT_FAILED, [f"{type(exc).__name__}: {exc}"]
    lines.append(f"wall      {time.perf_counter() - started:.1f} s")
    print("\n".join(lines))
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    if not problems:
        print("PASS")
    return code


def main(argv: Sequence[str] | None = None) -> int:
    args, qt_args = _arg_parser().parse_known_args(sys.argv[1:] if argv is None else argv)
    if args.offline:
        os.environ[OFFLINE_ENV] = "1"
    settings = load_settings()
    _link_bundled_assets(settings)
    if args.self_test:
        return _self_test(settings)
    # The service starts the NER preload, so build it before the slow Qt import: they overlap.
    service = build_default_service(settings)
    from cloudyreader.audio import AfplayPlayer
    from cloudyreader.gui.app import run

    return run(service, AfplayPlayer(), argv=qt_args)


if __name__ == "__main__":
    sys.exit(main())
