import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from cloudyreader.gui import fake_service
from cloudyreader.gui.fake_service import (
    FakeClipboard,
    FakePlayer,
    FakeReaderService,
)
from cloudyreader.models import Audio, RenderOptions
from cloudyreader.prefetch import PrefetchProgress, PrefetchResult


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


# --- prefetch hook ---------------------------------------------------------------------------

HEART = "kokoro:af_heart"


def progress_event(files_done: int, file: str = "a.onnx") -> PrefetchProgress:
    return PrefetchProgress(file, files_done * 10, 40, files_done, 4)


def run_prefetch(service, **kwargs) -> tuple[list[PrefetchProgress], PrefetchResult]:
    seen: list[PrefetchProgress] = []
    result = service.prefetch_voices(progress=seen.append, **kwargs)
    return seen, result


def test_prefetch_hook_is_absent_by_default_like_a_service_without_one():
    service = FakeReaderService()

    assert service.prefetch_voices is None
    assert getattr(service, "prefetch_voices", None) is None


def test_prefetch_reports_its_events_then_returns_the_result_and_records_its_thread():
    events = [progress_event(1), progress_event(2)]
    result = PrefetchResult("complete", files=2)
    service = FakeReaderService(prefetch_result=result, prefetch_events=events)

    seen, got = run_prefetch(service)

    assert (seen, got) == (events, result)
    assert service.prefetch_threads == [threading.current_thread()]


def test_prefetch_works_without_progress_or_cancel():
    service = FakeReaderService(prefetch_result=PrefetchResult("nothing"))

    assert service.prefetch_voices() == PrefetchResult("nothing")


def test_prefetch_installs_voices_before_its_first_event():
    voices = [
        replace(v, installed=False) if v.key == HEART else v for v in fake_service.FAKE_VOICES
    ]
    service = FakeReaderService(
        voices=voices,
        prefetch_result=PrefetchResult("complete", files=1),
        prefetch_events=[progress_event(1)],
        prefetch_installs=[HEART],
    )
    installed_at_event = []

    service.prefetch_voices(
        progress=lambda _e: installed_at_event.append(
            {v.key: v.installed for v in service.voices()}[HEART]
        )
    )

    assert installed_at_event == [True]
    assert fake_service.FAKE_VOICES[4].installed  # the shared tuple is never edited


def test_prefetch_gate_holds_the_run_after_its_first_event():
    gate = threading.Event()
    events = [progress_event(1), progress_event(2)]
    service = FakeReaderService(
        prefetch_result=PrefetchResult("complete", files=2),
        prefetch_events=events,
        prefetch_gate=gate,
    )
    seen = []
    worker = threading.Thread(target=lambda: service.prefetch_voices(progress=seen.append))

    worker.start()
    worker.join(0.1)
    assert worker.is_alive()
    assert seen == events[:1]
    gate.set()
    worker.join(2)

    assert seen == events
    assert service.prefetch_threads == [worker]


def test_prefetch_gate_holds_at_the_start_without_events():
    gate = threading.Event()
    service = FakeReaderService(prefetch_result=PrefetchResult("nothing"), prefetch_gate=gate)
    worker = threading.Thread(target=service.prefetch_voices)

    worker.start()
    worker.join(0.1)
    assert worker.is_alive()
    gate.set()
    worker.join(2)
    assert not worker.is_alive()


def test_cancel_ends_a_held_prefetch():
    gate, cancel = threading.Event(), threading.Event()
    service = FakeReaderService(
        prefetch_result=PrefetchResult("complete", files=2),
        prefetch_events=[progress_event(1), progress_event(2)],
        prefetch_gate=gate,
    )
    got = []
    worker = threading.Thread(target=lambda: got.append(run_prefetch(service, cancel=cancel)))

    worker.start()
    worker.join(0.1)
    cancel.set()
    worker.join(2)

    assert not worker.is_alive()
    assert got == [([progress_event(1)], PrefetchResult("cancelled"))]


def test_cancel_before_the_start_reports_nothing():
    cancel = threading.Event()
    cancel.set()
    service = FakeReaderService(
        prefetch_result=PrefetchResult("complete", files=1),
        prefetch_events=[progress_event(1)],
        prefetch_installs=[HEART],
    )

    assert run_prefetch(service, cancel=cancel) == ([], PrefetchResult("cancelled"))


def test_prefetch_raises_the_configured_error():
    service = FakeReaderService(prefetch_error=RuntimeError("disk full"))

    assert callable(service.prefetch_voices)
    with pytest.raises(RuntimeError, match="disk full"):
        service.prefetch_voices()


def test_prefetch_waits_out_the_configured_delay():
    service = FakeReaderService(prefetch_result=PrefetchResult("nothing"), prefetch_delay_s=0.05)
    started = time.monotonic()

    service.prefetch_voices()

    assert time.monotonic() - started >= 0.04


def test_an_unreleased_prefetch_gate_fails_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(fake_service, "_GATE_TIMEOUT_S", 0.05)
    service = FakeReaderService(
        prefetch_result=PrefetchResult("nothing"), prefetch_gate=threading.Event()
    )

    with pytest.raises(TimeoutError, match="gate"):
        service.prefetch_voices()


def test_cancel_between_events_stops_the_run():
    cancel = threading.Event()
    service = FakeReaderService(
        prefetch_result=PrefetchResult("complete", files=2),
        prefetch_events=[progress_event(1), progress_event(2)],
    )
    seen = []

    def report(event):
        seen.append(event)
        cancel.set()

    result = service.prefetch_voices(progress=report, cancel=cancel)

    assert (seen, result) == ([progress_event(1)], PrefetchResult("cancelled"))
