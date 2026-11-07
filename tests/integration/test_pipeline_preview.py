"""Pipeline.preview_script: the live Spoken script, parse and normalize with every lookup off."""

from __future__ import annotations

import dataclasses
import socket
from pathlib import Path

import pytest

from cloudyreader.lexicon import Lexicon
from cloudyreader.models import RenderOptions, SpokenScript
from cloudyreader.normalize import ScriptNormalizer
from cloudyreader.parser import QuestionParser
from cloudyreader.pipeline import Pipeline

from .fakes import (
    EARTH,
    EARTH_RAW,
    SETTINGS,
    VOICE_A,
    FakeDetector,
    FakeResolver,
    FakeTts,
    make_rig,
)

DEFAULT = RenderOptions()
READ_ANSWER = RenderOptions(read_answer=True)
FIXTURES = sorted((Path(__file__).resolve().parents[1] / "fixtures" / "questions").glob("*.txt"))
BARE = ("detect", "resolve", "offline-resolve", "synthesize", "voices")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any connection attempt fails the test, even when the code under test swallows the error."""
    attempts: list[object] = []

    def refuse(self, address, *args, **kwargs):
        attempts.append(address)
        raise AssertionError("a script preview opened a connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    yield
    assert attempts == []


def test_the_preview_parses_and_normalizes_and_nothing_else():
    rig = make_rig()

    script = rig.pipeline.preview_script(EARTH_RAW, DEFAULT)

    assert rig.log == ["parse", "normalize"]
    assert rig.parser.raws == [EARTH_RAW]
    assert script is rig.normalizer.script


def test_the_normalizer_gets_the_parsed_questions_no_resolutions_and_the_options():
    rig = make_rig()

    rig.pipeline.preview_script(EARTH_RAW, READ_ANSWER)

    ((questions, resolutions, opts),) = rig.normalizer.calls
    assert (questions, resolutions, opts) == ([EARTH], {}, READ_ANSWER)


@pytest.mark.parametrize("offline", [False, True], ids=["online-settings", "offline-settings"])
@pytest.mark.parametrize("lookups", [True, False], ids=["lookups-on", "lookups-off"])
def test_the_preview_asks_no_resolver_no_detector_no_voice_and_makes_no_audio(offline, lookups):
    rig = make_rig(settings=dataclasses.replace(SETTINGS, offline=offline))

    rig.pipeline.preview_script(EARTH_RAW, RenderOptions(online_lookups=lookups))

    assert not set(rig.log) & set(BARE)
    assert rig.resolver.calls == [] and rig.offline_resolver.calls == []
    assert rig.detector.texts == [] and rig.tts.calls == []


@pytest.mark.parametrize("raw", ["", "   ", "\n\t \r\n", "\u00a0\u3000"])
def test_blank_text_previews_as_an_empty_script_without_parsing(raw):
    rig = make_rig()

    assert rig.pipeline.preview_script(raw, DEFAULT) == SpokenScript(())

    assert rig.log == []


def test_text_the_parser_finds_nothing_in_previews_as_an_empty_script():
    rig = make_rig(questions=())

    assert rig.pipeline.preview_script("???", DEFAULT) == SpokenScript(())

    assert rig.log == ["parse"]


def test_a_parser_failure_is_raised_for_the_panel_to_log():
    rig = make_rig()
    rig.parser.error = RuntimeError("parser exploded")

    with pytest.raises(RuntimeError, match="parser exploded"):
        rig.pipeline.preview_script(EARTH_RAW, DEFAULT)


def test_a_normalizer_failure_is_raised_for_the_panel_to_log():
    rig = make_rig()
    rig.normalizer.error = RuntimeError("normalizer exploded")

    with pytest.raises(RuntimeError, match="normalizer exploded"):
        rig.pipeline.preview_script(EARTH_RAW, DEFAULT)


# --- parity with Speak ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lexicon():
    return Lexicon.load()


def real_pipeline(lexicon: Lexicon) -> Pipeline:
    """The real parser and normalizer; a detector that tags nothing, so Speak resolves nothing."""
    log: list[str] = []
    return Pipeline(
        parser=QuestionParser(),
        detector=FakeDetector(log, vocab={}),
        resolver=FakeResolver(log, "resolve"),
        offline_resolver=FakeResolver(log, "offline-resolve"),
        normalizer=ScriptNormalizer(lexicon),
        tts=FakeTts(log),
        settings=SETTINGS,
    )


@pytest.mark.parametrize("read_answer", [False, True], ids=["answer-silent", "answer-read"])
@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem[:24])
def test_the_preview_is_the_script_speak_builds_with_lookups_off(lexicon, path, read_answer):
    pipeline = real_pipeline(lexicon)
    raw = path.read_text(encoding="utf-8")
    opts = RenderOptions(read_answer=read_answer)

    try:
        speak = RenderOptions(read_answer=read_answer, online_lookups=False)
        expected = pipeline.prepare(raw, VOICE_A, speak).script
    except ValueError:  # a fixture that holds no question: Speak refuses, the panel stays empty
        expected = SpokenScript(())

    assert pipeline.preview_script(raw, opts) == expected


def test_the_fixture_corpus_is_there_to_compare_against():
    assert len(FIXTURES) >= 60
