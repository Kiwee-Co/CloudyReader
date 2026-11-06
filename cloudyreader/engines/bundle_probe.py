"""Engine import probe for a built app: the launcher runs it when `CLOUDYREADER_PROBE=engines`.

Asks each engine's supported() first, then imports what the two engines need and finds the Qwen
gate's decoder file. Loads no weights, makes no network call, opens no data folder.
One `ok` or `FAIL <name>: <error>` line each; 0 if all pass. plan_main is the `plan` probe.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from collections.abc import Sequence
from pathlib import Path

ENGINES = ("chatterbox_turbo", "qwen3_tts")
IMPORTS = (
    "transformers",
    "tokenizers",
    "transformers.models.auto",
    "transformers.models.qwen2",
    "transformers.models.gpt2",
    "mlx_audio.tts.models.chatterbox_turbo",
    "mlx_audio.tts.models.qwen3_tts",
)
GATE_CHECK = "qwen3_tts speech_tokenizer.py"
_GATE_FILE = ("tts", "models", "qwen3_tts", "speech_tokenizer.py")


def _decoder_source() -> Path | None:
    """The gate's lookup, for a tree without its module: a top-level spec runs no package code."""
    spec = importlib.util.find_spec("mlx_audio")
    for root in (spec.submodule_search_locations or ()) if spec else ():
        if Path(root).joinpath(*_GATE_FILE).is_file():
            return Path(root).joinpath(*_GATE_FILE)
    return None


def gate_file() -> Path | None:
    """speech_tokenizer.py where the Qwen decoder gate looks for it."""
    try:
        from cloudyreader.engines.qwen3_decoder import decoder_source
    except ImportError:
        decoder_source = _decoder_source
    return decoder_source()


def unsupported(engine: str) -> str | None:
    """The engine's supported() reason, None when the app would offer it."""
    return importlib.import_module(f"cloudyreader.engines.{engine}").supported()


def main(argv: Sequence[str] | None = None) -> int:
    os.environ["HF_HUB_OFFLINE"] = "1"  # before transformers reads it at import
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    failed = 0
    # Before the imports below, as at app start: supported() must find each engine through the
    # import system's finders (PyInstaller 6.10+ in an .app), not in modules loaded here.
    for engine in ENGINES:
        try:
            reason = unsupported(engine)
        except Exception as exc:  # a crash in the check is a finding too
            reason = f"{type(exc).__name__}: {exc}"
        if reason is None:
            print(f"ok {engine} supported()", flush=True)
        else:
            print(f"FAIL {engine} supported(): {reason}", flush=True)
            failed += 1
    for name in IMPORTS:
        try:
            importlib.import_module(name)
        except Exception as exc:  # any import error is a finding: report it, check the rest
            print(f"FAIL {name}: {type(exc).__name__}: {exc}", flush=True)
            failed += 1
        else:
            print(f"ok {name}", flush=True)
    try:
        found = gate_file()
    except Exception as exc:
        print(f"FAIL {GATE_CHECK}: {type(exc).__name__}: {exc}", flush=True)
        failed += 1
    else:
        if found is None:
            print(f"FAIL {GATE_CHECK}: not found where the Qwen gate looks for it", flush=True)
            failed += 1
        else:
            print(f"ok {GATE_CHECK}", flush=True)
    return 1 if failed else 0


def plan_main() -> int:
    """`CLOUDYREADER_PROBE=plan`: the bytes this app downloads at first launch, for build_app.sh.

    VoicePrefetch.plan() on the bundled lock and CLOUDYREADER_DATA_DIR, as this build decides it:
    reads the lock and stats files, writes nothing, opens no connection. A group the build lacks
    ("not in this build") is left out, since the app never offers it. Any other skip undercounts
    a first launch elsewhere: exit 3. Any error fails closed: exit 2 and no number.
    """
    try:
        from cloudyreader.config import load_settings
        from cloudyreader.engine_catalog import NOT_IN_BUILD
        from cloudyreader.prefetch import VoicePrefetch

        plan = VoicePrefetch(load_settings()).plan()
    except Exception as exc:  # whatever breaks the plan, the figure must not be guessed
        print(f"plan: failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2
    undercount = False
    for reason in plan.skipped:
        lacks = reason.endswith(f": {NOT_IN_BUILD}")
        print(f"plan: {'leaves out' if lacks else 'skips'} {reason}", file=sys.stderr, flush=True)
        undercount = undercount or not lacks
    if undercount:
        return 3
    print(plan.total_bytes, flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover - the frozen app reaches it through the launcher
    raise SystemExit(main())
