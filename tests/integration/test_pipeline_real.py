"""Pipeline with real components that need no voice and no model: the speech rules, the wiring."""

from __future__ import annotations

import platform
import sys
import threading

import pytest

from cloudyreader.config import load_settings
from cloudyreader.models import RenderOptions
from cloudyreader.pipeline import Pipeline, _engines, build_default_service

from .fakes import (
    BAKING,
    BAKING_RAW,
    EARTH,
    EARTH_RAW,
    LIFE,
    LIFE_RAW,
    VOICE_A,
    make_rig,
)

DEFAULT = RenderOptions()
READ_ANSWER = RenderOptions(read_answer=True)


@pytest.fixture(scope="module")
def normalizer():
    lexicon = pytest.importorskip("cloudyreader.lexicon")
    module = pytest.importorskip("cloudyreader.normalize")
    return module.ScriptNormalizer(lexicon.Lexicon.load())


def test_r5_a_resolved_name_never_reaches_the_speech(normalizer):
    rig = make_rig(
        questions=[BAKING], canonical={"NaHCO3": "sodium bicarbonate"}, normalizer=normalizer
    )

    reading = rig.pipeline.prepare(BAKING_RAW, VOICE_A, DEFAULT)

    assert reading.resolutions["NaHCO3"].canonical == "sodium bicarbonate"
    spoken = reading.script.text().lower()
    for leaked in ("sodium", "bicarbonate", "baking"):
        assert leaked not in spoken


def test_r2_the_answer_line_is_spoken_only_on_request(normalizer):
    rig = make_rig(questions=[LIFE], normalizer=normalizer)

    quiet = rig.pipeline.prepare(LIFE_RAW, VOICE_A, DEFAULT)
    loud = rig.pipeline.prepare(LIFE_RAW, VOICE_A, READ_ANSWER)

    assert "Answer." not in quiet.script.text()
    *before, last = loud.script.segments
    assert last.text == "Answer. Y. Esophagus."
    assert before[-1].pause_after_ms == 5000


def test_r1_a_respelling_is_an_override_and_never_read_as_letters(normalizer):
    rig = make_rig(questions=[LIFE], normalizer=normalizer)

    reading = rig.pipeline.prepare(LIFE_RAW, VOICE_A, DEFAULT)

    overrides = [o for segment in reading.script.segments for o in segment.overrides]
    assert {o.surface for o in overrides} >= {"Pharynx", "Larynx", "Esophagus", "Trachea"}
    assert {o.source for o in overrides} == {"respelling"}
    assert all(o.ipa for o in overrides)
    assert "FAR-ingks" not in reading.script.text()


def test_r4_questions_in_one_paste_are_read_in_order_with_a_1500_ms_gap(normalizer):
    rig = make_rig(questions=[EARTH, LIFE], normalizer=normalizer)

    reading = rig.pipeline.prepare(EARTH_RAW + LIFE_RAW, VOICE_A, DEFAULT)

    segments = reading.script.segments
    second = next(i for i, s in enumerate(segments) if s.text.startswith("Question number one."))
    assert segments[second - 1].pause_after_ms == 1500
    assert [s.pause_after_ms for s in segments].count(1500) == 1
    assert segments[0].text == "Toss-up number two."


def test_build_default_service_wires_the_real_components(tmp_path, monkeypatch):
    entities = pytest.importorskip("cloudyreader.entities")
    monkeypatch.setattr(entities.SciEntityDetector, "preload", lambda self: None)  # no model load
    settings = load_settings(
        {"CLOUDYREADER_DATA_DIR": str(tmp_path / "data"), "CLOUDYREADER_OFFLINE": "1"}
    )

    service = build_default_service(settings)

    assert isinstance(service, Pipeline)
    assert service.voices() == []  # an empty voices dir: Piper lists nothing, Kokoro is absent


def engine_keys(tmp_path):
    settings = load_settings({"CLOUDYREADER_DATA_DIR": str(tmp_path)})
    return [engine.key for engine in _engines(settings)]


def test_kokoro_joins_piper_only_on_apple_silicon(monkeypatch, tmp_path):
    pytest.importorskip("cloudyreader.engines.kokoro")

    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert engine_keys(tmp_path) == ["piper", "kokoro"]

    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert engine_keys(tmp_path) == ["piper"]


def test_a_kokoro_that_will_not_import_leaves_piper_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setitem(sys.modules, "cloudyreader.engines.kokoro", None)  # `import` now raises

    assert engine_keys(tmp_path) == ["piper"]


def test_kokoro_is_wired_to_list_all_28_voices(monkeypatch, tmp_path):
    pytest.importorskip("cloudyreader.engines.kokoro")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    settings = load_settings({"CLOUDYREADER_DATA_DIR": str(tmp_path)})

    kokoro = [engine for engine in _engines(settings) if engine.key == "kokoro"]

    assert len(kokoro) == 1
    assert kokoro[0].all_voices is True


def test_prefetch_voices_hands_settings_progress_and_cancel_to_voice_prefetch(
    monkeypatch, tmp_path
):
    from cloudyreader import prefetch

    calls = []
    done = prefetch.PrefetchResult("complete", files=2)

    class SpyPrefetch:
        def __init__(self, settings):
            calls.append(settings)

        def run(self, progress=None, cancel=None):
            calls.append((progress, cancel))
            return done

    monkeypatch.setattr(prefetch, "VoicePrefetch", SpyPrefetch)
    settings = load_settings({"CLOUDYREADER_DATA_DIR": str(tmp_path)})
    pipeline = make_rig(settings=settings).pipeline
    events, cancel = [], threading.Event()

    assert pipeline.prefetch_voices(events.append, cancel) is done
    assert pipeline.prefetch_voices(progress=events.append, cancel=cancel) is done
    assert calls == [settings, (events.append, cancel)] * 2
    # The window finds the hook by this exact name; a typo there would fail silently.
    assert callable(getattr(pipeline, "prefetch_voices", None))
