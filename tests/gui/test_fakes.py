import threading
import time
from pathlib import Path

import pytest

from cloudyreader.gui import fake_service
from cloudyreader.gui.fake_service import (
    FakeClipboard,
    FakePlayer,
    FakeReaderService,
)
from cloudyreader.models import Audio, RenderOptions


def make_audio(duration_s: float = 1.0) -> Audio:
    return Audio(Path("x.wav"), 22_050, duration_s, cache_hit=False)


def test_service_lists_both_engines_a_multi_speaker_and_an_uninstalled_voice():
    voices = FakeReaderService().voices()

    assert {v.engine for v in voices} == {"piper", "kokoro"}
    assert any(v.num_speakers > 1 for v in voices)
    assert any(not v.installed for v in voices)


def test_prepare_records_the_call_and_builds_a_script_per_line():
    service = FakeReaderService(duration_s=3.5)

    reading = service.prepare("one\n\n two \n", "piper:x", RenderOptions(read_answer=True))

    call = service.calls[0]
    assert (call.raw, call.voice_key) == ("one\n\n two \n", "piper:x")
    assert call.opts == RenderOptions(read_answer=True)
    assert reading.script.text() == "one two"
    assert reading.audio.duration_s == 3.5


def test_prepare_returns_configured_warnings():
    reading = FakeReaderService(warnings=["w1"]).prepare("a", "k", RenderOptions())

    assert reading.warnings == ("w1",)


def test_prepare_raises_the_configured_error():
    service = FakeReaderService(error=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        service.prepare("a", "k", RenderOptions())


def test_prepare_blocks_until_the_gate_opens():
    gate = threading.Event()
    service = FakeReaderService(gate=gate)
    worker = threading.Thread(target=service.prepare, args=("a", "k", RenderOptions()))

    worker.start()
    worker.join(0.1)
    assert worker.is_alive()
    gate.set()
    worker.join(2)
    assert not worker.is_alive()
    assert service.calls[0].thread is worker


def test_an_unreleased_gate_fails_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(fake_service, "_GATE_TIMEOUT_S", 0.05)
    service = FakeReaderService(gate=threading.Event())

    with pytest.raises(TimeoutError, match="gate"):
        service.prepare("a", "k", RenderOptions())


def test_voices_block_until_the_voices_gate_opens_and_record_their_thread():
    gate = threading.Event()
    service = FakeReaderService(voices_gate=gate)
    listed = []
    worker = threading.Thread(target=lambda: listed.append(service.voices()))

    worker.start()
    worker.join(0.1)
    assert worker.is_alive()
    gate.set()
    worker.join(2)

    assert listed == [list(fake_service.FAKE_VOICES)]
    assert service.voices_threads == [worker]


def test_voices_raise_the_configured_error():
    service = FakeReaderService(voices_error=RuntimeError("catalog unreadable"))

    with pytest.raises(RuntimeError, match="catalog unreadable"):
        service.voices()


def test_voices_wait_out_the_configured_delay():
    service = FakeReaderService(voices_delay_s=0.05)
    started = time.monotonic()

    service.voices()

    assert time.monotonic() - started >= 0.04


def test_an_unreleased_voices_gate_fails_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(fake_service, "_GATE_TIMEOUT_S", 0.05)
    service = FakeReaderService(voices_gate=threading.Event())

    with pytest.raises(TimeoutError, match="gate"):
        service.voices()


def test_player_replay_is_false_before_any_play():
    player = FakePlayer()

    assert player.replay() is False
    assert player.replay_calls == 1


def test_player_tracks_play_stop_and_finish():
    player = FakePlayer()
    audio = make_audio()

    player.play(audio)
    assert player.is_playing
    assert player.played == [audio]
    player.stop()
    assert not player.is_playing
    assert player.stop_calls == 1
    assert player.replay() is True
    assert player.is_playing
    player.finish()
    assert not player.is_playing


def test_player_records_the_thread_that_played():
    player = FakePlayer()

    player.play(make_audio())

    assert player.play_threads == [threading.current_thread()]


def test_real_time_player_stops_after_the_audio_duration():
    player = FakePlayer(real_time=True)

    player.play(make_audio(duration_s=0.02))
    assert player.is_playing
    time.sleep(0.06)
    assert not player.is_playing


def test_player_raises_the_configured_error():
    player = FakePlayer(error=OSError("no output device"))

    with pytest.raises(OSError, match="no output device"):
        player.play(make_audio())
    with pytest.raises(OSError, match="no output device"):
        player.replay()


def test_clipboard_returns_what_was_set():
    clipboard = FakeClipboard("abc")
    assert clipboard.text() == "abc"

    clipboard.set_text("def")
    assert clipboard.text() == "def"
