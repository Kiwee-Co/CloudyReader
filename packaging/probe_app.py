"""Bundling probe for Cloudy Reader.app: exercises every heavy dependency the real app freezes.

scripts/build_app.sh builds it (ENTRY=probe) while the real entry point is not ready, then runs
the bundle with `--self-test`. Prints one JSON line; exit 0 when every check passes, else 1.
No window on screen, no audio, no network.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import tempfile
import time
import wave
from collections.abc import Callable
from pathlib import Path

PROBE_WORD = "Hello."
OPSIN_NAME = "2-methylpropan-1-ol"
NER_SENTENCE = "Hemoglobin binds oxygen in Escherichia coli."
_CF = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_UTF8 = 0x08000100  # kCFStringEncodingUTF8


def _resources_dir() -> Path | None:
    resources = Path(sys.executable).resolve().parent.parent / "Resources"
    return resources if getattr(sys, "frozen", False) and resources.is_dir() else None


def _voices_dir() -> Path:
    if env := os.environ.get("CLOUDYREADER_PROBE_VOICES"):
        return Path(env)
    resources = _resources_dir()
    return resources / "assets" / "voices" if resources else Path(".data/voices")


def check_qt() -> dict:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([sys.argv[0]])
    label = QLabel("Cloudy Reader probe")
    label.show()
    app.processEvents()
    shown = label.isVisible()
    label.close()
    app.processEvents()
    return {"ok": shown, "platform": app.platformName()}


def check_piper() -> dict:
    from piper import PiperVoice

    model = sorted(_voices_dir().glob("*.onnx"))[0]
    voice = PiperVoice.load(model, config_path=Path(f"{model}.json"))
    with tempfile.TemporaryDirectory(prefix="cloudyreader-probe-") as tmp:
        out = Path(tmp) / "probe.wav"
        with wave.open(str(out), "wb") as wav:
            voice.synthesize_wav(PROBE_WORD, wav)
        with wave.open(str(out), "rb") as wav:
            frames, rate = wav.readframes(wav.getnframes()), wav.getframerate()
    peak = max(
        abs(int.from_bytes(frames[i : i + 2], "little", signed=True))
        for i in range(0, len(frames), 2)
    )
    seconds = len(frames) / 2 / rate
    return {"ok": seconds > 0.2 and peak > 500, "voice": model.stem, "seconds": round(seconds, 2)}


def check_spacy() -> dict:
    import spacy

    # Same pipes as cloudyreader.entities: NER only.
    nlp = spacy.load(
        "en_ner_craft_md", exclude=["tagger", "attribute_ruler", "lemmatizer", "parser"]
    )
    ents = [(e.text, e.label_) for e in nlp(NER_SENTENCE).ents]
    return {"ok": bool(ents), "ents": ents}


def check_opsin() -> dict:
    import jdk4py

    # py2opsin runs a bare `java -version` at import time: the bundled JRE must come first.
    os.environ["PATH"] = f"{jdk4py.JAVA_HOME / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"
    from py2opsin import py2opsin

    with tempfile.TemporaryDirectory(prefix="cloudyreader-probe-") as tmp:
        smiles = py2opsin(OPSIN_NAME, tmp_fpath=str(Path(tmp) / "names.txt"))
    # Isobutanol is C4H10O; OPSIN may order the SMILES either way ("CC(CO)C", "CC(C)CO").
    atoms = sorted(c for c in smiles or "" if c.isalpha())
    return {"ok": atoms == ["C", "C", "C", "C", "O"], "smiles": smiles}


def check_sqlite_httpx() -> dict:
    import sqlite3

    import httpx

    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE t (k TEXT PRIMARY KEY, v TEXT)")
        db.execute("INSERT INTO t VALUES ('a', 'b')")
        row = db.execute("SELECT v FROM t WHERE k = 'a'").fetchone()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport) as client:
        body = client.get("https://example.invalid/probe").json()
    return {"ok": row == ("b",) and body == {"ok": True}, "sqlite": sqlite3.sqlite_version}


def check_kokoro() -> dict:
    resources = _resources_dir()
    models = resources / "assets" / "models" if resources else Path(".data/models")
    if not (models / "kokoro").is_dir():
        return {"ok": True, "skipped": "no Kokoro model bundled"}
    from cloudyreader.engines.kokoro import KokoroEngine
    from cloudyreader.models import RenderOptions, Segment, SpokenScript

    engine = KokoroEngine(models)
    if not engine.available():
        return {"ok": False, "error": engine.unavailable_reason}
    voice = engine.voices()[0]
    with tempfile.TemporaryDirectory(prefix="cloudyreader-probe-") as tmp:
        script = SpokenScript((Segment(PROBE_WORD),))
        audio = engine.synthesize(script, voice, RenderOptions(), Path(tmp) / "kokoro.wav")
    return {"ok": audio.duration_s > 0.2, "voice": voice.key, "seconds": round(audio.duration_s, 2)}


def _cf_string(cf: ctypes.CDLL, ref: int | None) -> str | None:
    buf = ctypes.create_string_buffer(256)
    return buf.value.decode() if ref and cf.CFStringGetCString(ref, buf, 256, _UTF8) else None


def _process_path() -> str:
    """Executable of this process as ps and Activity Monitor see it (libproc, no exec)."""
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
    buf = ctypes.create_string_buffer(4096)  # PROC_PIDPATHINFO_MAXSIZE
    size = libproc.proc_pidpath(os.getpid(), buf, ctypes.c_uint32(len(buf)))
    return buf.value.decode() if size > 0 else ""


def check_identity() -> dict:
    """What the Dock sees: the process executable and the main bundle it resolves."""
    cf = ctypes.CDLL(_CF)
    vp = ctypes.c_void_p
    cf.CFBundleGetMainBundle.restype = vp
    cf.CFBundleGetIdentifier.argtypes, cf.CFBundleGetIdentifier.restype = [vp], vp
    cf.CFStringCreateWithCString.argtypes = [vp, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = vp
    cf.CFBundleGetValueForInfoDictionaryKey.argtypes = [vp, vp]
    cf.CFBundleGetValueForInfoDictionaryKey.restype = vp
    cf.CFStringGetCString.argtypes = [vp, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    cf.CFStringGetCString.restype = ctypes.c_bool
    bundle = cf.CFBundleGetMainBundle()
    key = cf.CFStringCreateWithCString(None, b"CFBundleName", _UTF8)
    process = _process_path()
    frozen = bool(getattr(sys, "frozen", False))
    return {
        "ok": "/Contents/MacOS/" in process or not frozen,
        "frozen": frozen,
        "process": process,
        "bundle_id": _cf_string(cf, cf.CFBundleGetIdentifier(bundle)),
        "bundle_name": _cf_string(cf, cf.CFBundleGetValueForInfoDictionaryKey(bundle, key)),
    }


CHECKS: dict[str, Callable[[], dict]] = {
    "identity": check_identity,
    "sqlite_httpx": check_sqlite_httpx,
    "qt": check_qt,
    "piper": check_piper,
    "spacy": check_spacy,
    "opsin": check_opsin,
    "kokoro": check_kokoro,
}


def main() -> int:
    started = time.perf_counter()
    results: dict[str, dict] = {}
    for name, check in CHECKS.items():
        t0 = time.perf_counter()
        try:
            results[name] = check()
        except Exception as exc:  # report every failing check, not just the first
            results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        results[name]["s"] = round(time.perf_counter() - t0, 2)
    ok = all(r["ok"] for r in results.values())
    total = round(time.perf_counter() - started, 2)
    print(json.dumps({"ok": ok, "total_s": total, "checks": results}))
    return 0 if ok else 1


if __name__ == "__main__":
    # `--self-test` is accepted so build_app.sh runs the probe and the real app the same way.
    sys.exit(main())
