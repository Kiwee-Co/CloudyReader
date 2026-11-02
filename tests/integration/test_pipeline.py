"""Pipeline wiring with a fake for every stage: order, R2, R5, offline, failures, preload, cache."""

from __future__ import annotations

import dataclasses
import inspect
import threading

import pytest

from cloudyreader.models import Choice, ReaderService, RenderOptions
from cloudyreader.pipeline import NER_PROBE, Pipeline

from .fakes import (
    BAKING,
    BAKING_RAW,
    EARTH,
    EARTH_RAW,
    LIFE,
    LIFE_RAW,
    SETTINGS,
    VOICE_A,
    VOICE_B,
    VOICE_C,
    CountingEngine,
    FakeDetector,
    PreloadingDetector,
    WarningTts,
    collapsed,
    make_rig,
    wait_until,
)

DEFAULT = RenderOptions()
READ_ANSWER = RenderOptions(read_answer=True)
OFFLINE = [
    pytest.param(RenderOptions(online_lookups=False), SETTINGS, id="online-lookups-off"),
    pytest.param(DEFAULT, dataclasses.replace(SETTINGS, offline=True), id="settings-offline"),
]


def test_pipeline_matches_the_reader_service_protocol():
    for name in ("voices", "prepare"):
        ours = list(inspect.signature(getattr(Pipeline, name)).parameters)
        assert ours == list(inspect.signature(getattr(ReaderService, name)).parameters)


def test_voices_come_from_the_tts_service():
    assert [v.key for v in make_rig().pipeline.voices()] == [VOICE_A, VOICE_B, VOICE_C]


# --- the happy path ---------------------------------------------------------------------------


def test_prepare_runs_the_stages_in_order_and_fills_the_reading():
    rig = make_rig()

    reading = rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)

    assert collapsed(rig.log) == ["voices", "parse", "detect", "resolve", "normalize", "synthesize"]
    assert rig.parser.raws == [EARTH_RAW]
    assert reading.questions == (EARTH,)
    assert [(e.text, e.label) for e in reading.entities] == [("mantle", "other")]
    assert set(reading.resolutions) == {"mantle"}
    assert reading.script is rig.normalizer.script
    assert reading.audio is rig.tts.audio
    assert reading.warnings == ()
    (call,) = rig.tts.calls
    assert (call.script, call.voice.key, call.opts) == (reading.script, VOICE_A, DEFAULT)


def test_several_questions_become_one_script_with_a_pause_between():
    rig = make_rig(questions=[EARTH, LIFE])

    reading = rig.pipeline.prepare(EARTH_RAW + LIFE_RAW, VOICE_A, DEFAULT)

    ((questions, _, _),) = rig.normalizer.calls  # one call for the whole paste
    assert questions == [EARTH, LIFE]
    assert len(rig.tts.calls) == 1  # and one audio
    pauses = [segment.pause_after_ms for segment in reading.script.segments]
    assert [i for i, ms in enumerate(pauses) if ms == 1500] == [len(EARTH.choices)]
    assert reading.questions == (EARTH, LIFE)


# --- paste and voice errors -------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "   ", "\n\t \r\n", "\u00a0\u3000"])
def test_blank_paste_raises_before_any_stage_runs(raw):
    rig = make_rig()

    with pytest.raises(ValueError, match="nothing to read"):
        rig.pipeline.prepare(raw, VOICE_A, DEFAULT)

    assert rig.log == []


def test_a_paste_the_parser_finds_nothing_in_raises_without_speech():
    rig = make_rig(questions=())

    with pytest.raises(ValueError, match="nothing to read"):
        rig.pipeline.prepare("???", VOICE_A, DEFAULT)

    assert rig.tts.calls == []
    assert "normalize" not in rig.log


def test_an_unknown_voice_raises_before_parsing_or_lookups():
    rig = make_rig()

    with pytest.raises(ValueError, match="unknown voice 'piper:nope'"):
        rig.pipeline.prepare(EARTH_RAW, "piper:nope", DEFAULT)

    assert rig.log == ["voices"]


def test_a_voice_that_is_not_installed_raises_a_clear_error():
    rig = make_rig()

    with pytest.raises(ValueError, match="not installed"):
        rig.pipeline.prepare(EARTH_RAW, VOICE_C, DEFAULT)

    assert rig.log == ["voices"]


# --- entities, R2 and R5 ----------------------------------------------------------------------


def test_entities_come_from_the_stem_and_every_choice():
    rig = make_rig(questions=[LIFE])

    rig.pipeline.prepare(LIFE_RAW, VOICE_A, DEFAULT)

    assert rig.detector.texts == [LIFE.stem, *(c.text for c in LIFE.choices)]


def test_the_answer_is_scanned_only_when_it_will_be_read():
    quiet, loud = make_rig(questions=[LIFE]), make_rig(questions=[LIFE])

    quiet.pipeline.prepare(LIFE_RAW, VOICE_A, DEFAULT)
    loud.pipeline.prepare(LIFE_RAW, VOICE_A, READ_ANSWER)

    assert LIFE.answer not in quiet.detector.texts
    assert loud.detector.texts[-1] == LIFE.answer


def test_a_missing_answer_is_never_scanned_even_when_answers_are_read():
    rig = make_rig()  # EARTH has no ANSWER line

    rig.pipeline.prepare(EARTH_RAW, VOICE_A, READ_ANSWER)

    assert rig.detector.texts == [EARTH.stem, *(c.text for c in EARTH.choices)]


def test_the_answer_is_spoken_only_when_asked():
    rig = make_rig(questions=[LIFE])

    quiet = rig.pipeline.prepare(LIFE_RAW, VOICE_A, DEFAULT)
    loud = rig.pipeline.prepare(LIFE_RAW, VOICE_A, READ_ANSWER)

    assert [call[2] for call in rig.normalizer.calls] == [DEFAULT, READ_ANSWER]
    assert "Answer." not in quiet.script.text()
    assert loud.script.segments[-1].text == "Answer. Y) ESOPHAGUS."


def test_resolved_names_never_change_what_is_spoken():
    # R5: a source may know NaHCO3 is baking soda. Speech still says the formula, never the name.
    rig = make_rig(questions=[BAKING], canonical={"NaHCO3": "sodium bicarbonate"})

    reading = rig.pipeline.prepare(BAKING_RAW, VOICE_A, DEFAULT)

    ((questions, resolutions, _),) = rig.normalizer.calls
    assert questions == [BAKING]  # the text reaches the normalizer exactly as parsed
    assert resolutions["NaHCO3"].canonical == "sodium bicarbonate"  # handed over, never applied
    assert rig.tts.calls[0].script is reading.script is rig.normalizer.script
    assert "NaHCO3" in reading.script.text()
    spoken = reading.script.text().lower()
    assert "sodium bicarbonate" not in spoken
    assert "baking soda" not in spoken


# --- lookups ----------------------------------------------------------------------------------


def test_a_name_that_repeats_is_resolved_once_but_every_span_is_reported():
    question = dataclasses.replace(
        BAKING,
        stem="Does NaHCO3 react?",
        choices=(Choice("W", "NaHCO3"), Choice("X", "mantle")),
    )
    rig = make_rig(questions=[question])

    reading = rig.pipeline.prepare(BAKING_RAW, VOICE_A, DEFAULT)

    ((spans, _),) = rig.resolver.calls
    assert [span.text for span in spans] == ["NaHCO3", "mantle"]
    assert [entity.text for entity in reading.entities] == ["NaHCO3", "NaHCO3", "mantle"]


def test_the_lookup_budget_comes_from_the_settings():
    rig = make_rig(settings=dataclasses.replace(SETTINGS, lookup_budget_s=1.25))

    rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)

    ((_, timeout_s),) = rig.resolver.calls
    assert timeout_s == 1.25


def test_online_lookups_use_the_online_resolver_only():
    rig = make_rig()

    rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)

    assert len(rig.resolver.calls) == 1
    assert rig.offline_resolver.calls == []


def test_no_entities_means_no_lookup_at_all():
    rig = make_rig()
    rig.detector.vocab = {}

    reading = rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)

    assert rig.resolver.calls == [] and rig.offline_resolver.calls == []
    assert reading.resolutions == {}
    assert rig.normalizer.calls[0][1] == {}


@pytest.mark.parametrize(("opts", "settings"), OFFLINE)
def test_offline_never_calls_the_online_resolver(opts, settings):
    rig = make_rig(settings=settings)

    reading = rig.pipeline.prepare(EARTH_RAW, VOICE_A, opts)

    assert rig.resolver.calls == []
    ((spans, timeout_s),) = rig.offline_resolver.calls
    assert [span.text for span in spans] == ["mantle"]
    assert timeout_s == settings.lookup_budget_s
    assert set(reading.resolutions) == {"mantle"}


@pytest.mark.parametrize(("opts", "settings"), OFFLINE)
def test_offline_without_an_offline_resolver_resolves_nothing(opts, settings):
    rig = make_rig(settings=settings, with_offline_resolver=False)

    reading = rig.pipeline.prepare(EARTH_RAW, VOICE_A, opts)

    assert rig.resolver.calls == []
    assert reading.resolutions == {}
    assert rig.normalizer.calls[0][1] == {}  # the normalizer still runs, on its built-in tables


# --- failures and warnings --------------------------------------------------------------------


def test_a_failing_detector_degrades_to_no_entities_and_warns(caplog):
    rig = make_rig()
    rig.detector.error = RuntimeError("model corrupt")

    with caplog.at_level("WARNING", logger="cloudyreader.pipeline"):
        reading = rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)

    assert reading.entities == () and reading.resolutions == {}
    assert reading.warnings == ("entity detection failed (RuntimeError); continuing without it",)
    assert "model corrupt" in caplog.text
    assert len(rig.tts.calls) == 1


def test_a_failing_resolver_degrades_to_no_resolutions_and_warns(caplog):
    rig = make_rig()
    rig.resolver.error = TimeoutError("budget gone")

    with caplog.at_level("WARNING", logger="cloudyreader.pipeline"):
        reading = rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)

    assert [entity.text for entity in reading.entities] == ["mantle"]
    assert reading.resolutions == {}
    assert reading.warnings == ("name lookup failed (TimeoutError); continuing without it",)
    assert "budget gone" in caplog.text
    assert len(rig.tts.calls) == 1


@pytest.mark.parametrize("stage", ["parser", "normalizer", "tts"])
def test_errors_from_the_core_stages_reach_the_caller(stage):
    rig = make_rig()
    getattr(rig, stage).error = RuntimeError(f"{stage} broke")

    with pytest.raises(RuntimeError, match=f"{stage} broke"):
        rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)


def test_warnings_merge_pipeline_script_and_engine_notes_without_duplicates():
    log: list[str] = []
    tts = WarningTts(
        log,
        warnings=("piper: dropped symbol", "script note"),
        last=("kokoro: no usable phonemes", "script note"),
    )
    rig = make_rig(log=log, tts=tts, script_warnings=("script note", "no IPA for 'xyz'"))
    rig.detector.error = RuntimeError("boom")

    reading = rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)

    assert reading.warnings == (
        "entity detection failed (RuntimeError); continuing without it",
        "script note",
        "no IPA for 'xyz'",
        "kokoro: no usable phonemes",
        "piper: dropped symbol",
    )


def test_last_warnings_are_read_right_after_the_synthesis_that_made_them():
    log: list[str] = []
    tts = WarningTts(log, last=("kokoro: speed clamped",))
    rig = make_rig(log=log, tts=tts)

    reading = rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)

    # The stale note a service holds from an earlier call must not leak into this reading.
    assert reading.warnings == ("kokoro: speed clamped",)


def test_a_failing_engine_warning_hook_never_fails_a_finished_synthesis():
    log: list[str] = []
    tts = WarningTts(log)
    tts.error_on_warnings = RuntimeError("probe broke")
    rig = make_rig(log=log, tts=tts)

    reading = rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)

    assert reading.audio is tts.audio
    assert reading.warnings == ("pronunciation check failed (RuntimeError); continuing without it",)


# --- entity mode (the --self-test report) -----------------------------------------------------


@pytest.mark.parametrize(("source", "expected"), [("ner", "ner"), ("regex", "regex-only")])
def test_entity_mode_tells_a_model_from_regex_only(source, expected):
    log: list[str] = []
    rig = make_rig(log=log, detector=FakeDetector(log, {NER_PROBE: "chemical"}, source))

    assert rig.pipeline.entity_mode() == expected


def test_entity_mode_is_regex_only_when_the_probe_finds_nothing():
    assert make_rig().pipeline.entity_mode() == "regex-only"


# --- preload ----------------------------------------------------------------------------------


def test_construction_starts_the_preload_without_waiting_for_it():
    log: list[str] = []
    gate = threading.Event()
    detector = PreloadingDetector(log, gate=gate)
    try:
        make_rig(log=log, detector=detector)  # returns although preload() is still blocked
        assert detector.started.wait(2)
        assert detector.preload_thread is not threading.current_thread()
        assert detector.preload_thread.daemon is True
        assert not detector.finished.is_set()
    finally:
        gate.set()
    assert detector.finished.wait(2)


def test_a_failing_preload_is_logged_and_prepare_still_works(caplog):
    log: list[str] = []
    detector = PreloadingDetector(log, error=OSError("no model"))

    with caplog.at_level("WARNING", logger="cloudyreader.pipeline"):
        rig = make_rig(log=log, detector=detector)
        assert wait_until(lambda: "no model" in caplog.text)

    assert rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT).audio is rig.tts.audio


def test_a_detector_without_preload_starts_no_thread():
    before = set(threading.enumerate())

    make_rig()

    assert [t for t in set(threading.enumerate()) - before if "preload" in t.name] == []


# --- with the real TtsService (fake engine) ---------------------------------------------------


@pytest.fixture
def real_tts(tmp_path):
    module = pytest.importorskip("cloudyreader.tts")
    engine = CountingEngine()
    return module.TtsService([engine], tmp_path / "wav"), engine


def test_the_same_input_twice_makes_one_engine_call(real_tts):
    tts, engine = real_tts
    rig = make_rig(tts=tts)

    first = rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)
    second = rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)

    assert (first.audio.cache_hit, second.audio.cache_hit) == (False, True)
    assert second.audio.wav_path == first.audio.wav_path
    assert len(engine.calls) == 1


def test_a_voice_switch_synthesizes_again(real_tts):
    tts, engine = real_tts
    rig = make_rig(tts=tts)

    first = rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)
    other = rig.pipeline.prepare(EARTH_RAW, VOICE_B, DEFAULT)
    back = rig.pipeline.prepare(EARTH_RAW, VOICE_A, DEFAULT)

    assert len(engine.calls) == 2
    assert other.audio.wav_path != first.audio.wav_path
    assert back.audio.cache_hit is True


def test_toggling_read_answer_changes_the_cache_key(real_tts):
    tts, engine = real_tts
    rig = make_rig(tts=tts, questions=[LIFE])

    quiet = rig.pipeline.prepare(LIFE_RAW, VOICE_A, DEFAULT)
    loud = rig.pipeline.prepare(LIFE_RAW, VOICE_A, READ_ANSWER)
    again = rig.pipeline.prepare(LIFE_RAW, VOICE_A, DEFAULT)

    assert len(engine.calls) == 2
    assert loud.audio.wav_path != quiet.audio.wav_path
    assert (again.audio.cache_hit, again.audio.wav_path) == (True, quiet.audio.wav_path)


def test_the_real_service_lists_its_voices_and_rejects_an_unknown_key(real_tts):
    tts, engine = real_tts
    rig = make_rig(tts=tts)

    assert [v.key for v in rig.pipeline.voices()] == [VOICE_A, VOICE_B]
    with pytest.raises(ValueError, match="unknown voice"):
        rig.pipeline.prepare(EARTH_RAW, VOICE_C, DEFAULT)

    assert engine.calls == []
