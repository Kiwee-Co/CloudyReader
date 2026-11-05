"""scripts/make_doc_snapshots.py: the voices figure lists voices in the app's own order."""

import importlib.util
import sys
from pathlib import Path

import pytest

from cloudyreader.voice_meta import voice_sort_key

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_doc_snapshots.py"


@pytest.fixture
def snapshots(monkeypatch: pytest.MonkeyPatch):
    # Importing the script changes these two for its own run; the session keeps its own values.
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    monkeypatch.setenv("QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM", "1")
    spec = importlib.util.spec_from_file_location("make_doc_snapshots", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses looks its module up in sys.modules while it builds the script's classes.
    monkeypatch.setitem(sys.modules, "make_doc_snapshots", module)
    spec.loader.exec_module(module)
    return module


def test_the_voices_figure_lists_the_voices_in_the_apps_order(snapshots, tmp_path):
    voices = snapshots.real_voices(tmp_path)

    assert [v.key for v in voices] == [v.key for v in sorted(voices, key=voice_sort_key)]
    assert list(dict.fromkeys(v.engine for v in voices)) == ["kokoro", "piper"]
