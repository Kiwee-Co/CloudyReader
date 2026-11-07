"""Voice downloads in the window: the progress widgets, the download thread, and the re-list."""

import logging
import threading
from dataclasses import replace

import pytest
import shiboken6
from PySide6.QtCore import QPoint

from cloudyreader.gui import tokens
from cloudyreader.gui.fake_service import FAKE_VOICES, FakeReaderService
from cloudyreader.gui.main_window import MainWindow, _emit, _Signals
from cloudyreader.gui.status import Tone, download_variants, size_text
from cloudyreader.prefetch import PrefetchProgress, PrefetchResult

LIBRITTS = "piper:en_US-libritts-high"
HEART = "kokoro:af_heart"
LESSAC = "piper:en_US-lessac-medium"
MB = 10**6


def prefetch_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "cloudyreader-prefetch"]


def status(window) -> str:
    return window.statusBar().currentMessage()


def refresh(qtbot, window) -> None:
    with qtbot.waitSignal(window.voices_refreshed, timeout=5000):
        window._refresh_voices()  # private on purpose: the download path is tested elsewhere


# --- the default fake has no download hook ----------------------------------------------------


def test_a_service_without_the_hook_gets_no_thread_no_widgets_and_no_status(window):
    assert not callable(getattr(window._service, "prefetch_voices", None))
    assert prefetch_threads() == []
    assert window.prefetch_label.isHidden()
    assert window.prefetch_bar.isHidden()
    assert status(window) == ""


def test_download_widgets_sit_left_of_the_busy_bar(window):
    bar = window.statusBar()
    for widget in (window.prefetch_label, window.prefetch_bar, window.busy_bar):
        widget.show()
    bar.layout().activate()

    lefts = [w.geometry().left() for w in (window.prefetch_label, window.prefetch_bar)]
    assert max(lefts) < window.busy_bar.geometry().left()
    assert window.prefetch_bar.accessibleName() == "Downloading voices"
    assert (window.prefetch_bar.minimum(), window.prefetch_bar.maximum()) == (0, 100)


# --- re-list ---------------------------------------------------------------------------------


def test_a_re_list_brings_new_voices_and_follows_the_stored_voice(qtbot, make_window, settings):
    settings.setValue("voice", HEART)
    voices = [replace(v, installed=False) if v.key == HEART else v for v in FAKE_VOICES]
    service = FakeReaderService(voices=voices)
    window = make_window(service=service)
    assert window.voice_picker.voice_key() == LESSAC  # the stored voice is not installed yet

    service.voice_list = list(FAKE_VOICES)
    refresh(qtbot, window)

    assert window.voice_picker.voice_key() == HEART
    assert settings.value("voice") == HEART


def test_a_re_list_keeps_the_speaker_of_an_unchanged_voice(qtbot, window):
    window.voice_picker.select_voice(LIBRITTS)
    window.voice_picker.speaker_spin.setValue(42)

    refresh(qtbot, window)

    assert window.voice_picker.voice_key() == LIBRITTS
    assert window.voice_picker.speaker_id() == 42


def test_a_re_list_that_finds_a_voice_clears_the_no_voice_warning(qtbot, make_window):
    service = FakeReaderService(voices=[])
    window = make_window(service=service)
    assert status(window) == "No voice is installed."
    assert not window.speak_button.isEnabled()

    service.voice_list = list(FAKE_VOICES)
    refresh(qtbot, window)

    assert status(window) == ""
    assert window.speak_button.isEnabled()


def test_a_re_list_leaves_a_newer_message_alone(qtbot, make_window):
    service = FakeReaderService(voices=[])
    window = make_window(service=service)
    window._on_repeat()  # Speak is off with no voice; Repeat's slot still answers

    service.voice_list = list(FAKE_VOICES)
    refresh(qtbot, window)

    assert status(window) == "Nothing to repeat yet."


def test_re_list_requests_coalesce_while_one_is_in_flight(qtbot, window, service):
    seen = []
    window.voices_refreshed.connect(lambda: seen.append(1))
    gate = service.voices_gate = threading.Event()
    window._refresh_voices()
    window._refresh_voices()
    window._refresh_voices()

    gate.set()
    qtbot.waitUntil(lambda: len(seen) == 2, timeout=5000)
    qtbot.wait(100)

    assert len(seen) == 2
    assert len(service.voices_threads) == 3  # the first load, then exactly two re-lists


def test_a_failed_re_list_only_logs(qtbot, window, service, caplog):
    service.voices_error = RuntimeError("catalog busy")
    before = window.voice_picker.voice_key()

    with qtbot.assertNotEmitted(window.voices_refreshed, wait=200):
        window._refresh_voices()
        qtbot.waitUntil(lambda: not window._refreshing, timeout=5000)

    assert window.voice_picker.voice_key() == before
    assert window.voice_picker.combo.isEnabled()
    assert status(window) == ""
    assert any(r.exc_info and "catalog busy" in str(r.exc_info[1]) for r in caplog.records)


def test_a_re_list_arriving_after_close_is_dropped(qtbot, window, service):
    gate = service.voices_gate = threading.Event()
    window._refresh_voices()
    gate.set()  # the list is ready; its signal reaches the window only after close()

    with qtbot.assertNotEmitted(window.voices_refreshed):
        window.close()  # waits for the worker
        qtbot.wait(100)


# --- the download thread ---------------------------------------------------------------------

PARTIAL = "Some voices could not be downloaded. They are tried again at the next start."


def progress(files_done: int, done_mb: int, total_mb: int = 200) -> PrefetchProgress:
    return PrefetchProgress(
        "en_US-lessac-medium.onnx", done_mb * 10**6, total_mb * 10**6, files_done, 4
    )


def speak(qtbot, window, text="What is H2O?"):
    window.question_edit.setPlainText(text)
    with qtbot.waitSignal(window.reading_played, timeout=5000):
        window.speak_button.click()


def held(make_window, **knobs):
    """A window whose download holds at the fake's gate; returns (window, service, gate)."""
    gate = threading.Event()
    service = FakeReaderService(prefetch_gate=gate, **knobs)
    return make_window(service=service), service, gate


def test_progress_reaches_the_label_and_bar_on_the_main_thread(qtbot, make_window, monkeypatch):
    slot_threads = []
    original = MainWindow._on_prefetch_progress

    def spy(self, event):
        slot_threads.append(threading.current_thread())
        original(self, event)

    monkeypatch.setattr(MainWindow, "_on_prefetch_progress", spy)
    result = PrefetchResult("complete", files=1)
    window, service, gate = held(
        make_window, prefetch_result=result, prefetch_events=[progress(0, 50)]
    )

    qtbot.waitUntil(window.prefetch_label.isVisible, timeout=5000)

    assert window.prefetch_label.text() == "Downloading voices… 25%"
    assert window.prefetch_label.toolTip() == "en_US-lessac-medium.onnx: 50.0 of 200.0 MB"
    assert window.prefetch_bar.isVisible()
    assert window.prefetch_bar.value() == 25
    assert slot_threads == [threading.main_thread()]
    [worker] = service.prefetch_threads
    assert (worker.name, worker.daemon) == ("cloudyreader-prefetch", True)
    with qtbot.waitSignals([window.prefetch_finished, window.voices_refreshed], timeout=5000):
        gate.set()
    assert window.prefetch_label.isHidden()
    assert window.prefetch_bar.isHidden()


def test_a_report_without_a_total_shows_zero_percent(qtbot, make_window):
    zero = PrefetchProgress("config.json", 0, 0, 0, 1)
    window, _service, gate = held(
        make_window, prefetch_result=PrefetchResult("nothing"), prefetch_events=[zero]
    )

    qtbot.waitUntil(window.prefetch_label.isVisible, timeout=5000)

    assert window.prefetch_label.text() == "Downloading voices… 0%"
    with qtbot.waitSignal(window.prefetch_finished, timeout=5000):
        gate.set()


def test_speak_works_during_a_download_and_playing_survives_its_progress(qtbot, make_window):
    events = [progress(1, 50), progress(2, 120)]
    result = PrefetchResult("complete", files=2)
    window, _service, gate = held(make_window, prefetch_result=result, prefetch_events=events)
    qtbot.waitUntil(window.prefetch_label.isVisible, timeout=5000)

    speak(qtbot, window)
    assert status(window) == "Playing 2.0 s."
    with qtbot.waitSignals([window.prefetch_finished, window.voices_refreshed], timeout=5000):
        gate.set()

    assert status(window) == "Playing 2.0 s."  # not "Voices downloaded.": the slot was taken


def test_a_complete_download_re_lists_and_follows_the_stored_voice(qtbot, make_window, settings):
    settings.setValue("voice", HEART)
    voices = [replace(v, installed=False) if v.key == HEART else v for v in FAKE_VOICES]
    result = PrefetchResult("complete", files=1)
    window, _service, gate = held(
        make_window, voices=voices, prefetch_result=result, prefetch_installs=[HEART]
    )
    assert window.voice_picker.voice_key() == LESSAC

    with qtbot.waitSignals([window.prefetch_finished, window.voices_refreshed], timeout=5000):
        gate.set()

    assert window.voice_picker.voice_key() == HEART
    assert status(window) == "Voices downloaded."
    assert window.statusBar().tone is Tone.INFO


def test_an_empty_picker_re_lists_after_the_first_file_and_speak_enables_mid_run(
    qtbot, make_window
):
    voices = [replace(v, installed=False) for v in FAKE_VOICES]
    window, service, gate = held(
        make_window,
        voices=voices,
        prefetch_result=PrefetchResult("complete", files=2),
        prefetch_events=[progress(1, 30), progress(2, 200)],
        prefetch_installs=[LESSAC],
    )

    qtbot.waitUntil(window.speak_button.isEnabled, timeout=5000)

    assert service.prefetch_threads[0].is_alive()  # still held after its first file
    assert window.voice_picker.voice_key() == LESSAC
    assert status(window) == ""  # the stale "No voice is installed." is gone
    with qtbot.waitSignal(window.prefetch_finished, timeout=5000):
        gate.set()


def test_a_partial_download_warns_and_names_the_failed_files(qtbot, make_window):
    result = PrefetchResult("partial", files=1, failed=("en_GB-alan-medium.onnx",))
    window, _service, gate = held(make_window, prefetch_result=result)

    with qtbot.waitSignals([window.prefetch_finished, window.voices_refreshed], timeout=5000):
        gate.set()

    assert status(window) == PARTIAL
    assert window.statusBar().tone is Tone.WARNING
    assert "en_GB-alan-medium.onnx" in window.statusBar().toolTip()


@pytest.mark.parametrize("outcome", ["offline", "nothing", "cancelled"])
def test_offline_nothing_and_cancelled_stay_silent(qtbot, make_window, outcome):
    result = PrefetchResult(outcome)
    window, _service, gate = held(make_window, prefetch_result=result)

    with qtbot.waitSignal(window.prefetch_finished, timeout=5000) as blocker:
        gate.set()

    assert blocker.args == [result]
    assert status(window) == ""
    assert window.prefetch_label.isHidden()


def test_a_raising_hook_warns_and_leaves_a_usable_window(qtbot, make_window, caplog):
    service = FakeReaderService(prefetch_error=RuntimeError("disk full"))
    window = make_window(service=service)

    qtbot.waitUntil(lambda: status(window) == PARTIAL, timeout=5000)

    assert window.statusBar().tone is Tone.WARNING
    assert any(r.levelname == "WARNING" and r.exc_info for r in caplog.records)
    speak(qtbot, window)


def test_a_failed_voice_list_still_starts_the_download(qtbot, make_window):
    window, service, gate = held(
        make_window,
        voices_error=RuntimeError("catalog unreadable"),
        prefetch_result=PrefetchResult("nothing"),
    )

    with qtbot.waitSignal(window.prefetch_finished, timeout=5000):
        gate.set()

    assert len(service.prefetch_threads) == 1


def test_one_download_per_window(qtbot, make_window):
    window, service, gate = held(make_window, prefetch_result=PrefetchResult("nothing"))
    with qtbot.waitSignal(window.prefetch_finished, timeout=5000):
        gate.set()

    window._start_prefetch()  # private on purpose: a second voice list never comes in the app

    assert len(service.prefetch_threads) == 1


def test_closing_cancels_the_download_and_nothing_arrives_after(qtbot, make_window):
    window, service, _gate = held(make_window, prefetch_result=PrefetchResult("complete", files=1))
    qtbot.waitUntil(lambda: bool(service.prefetch_threads), timeout=5000)

    with qtbot.assertNotEmitted(window.prefetch_finished, wait=200):
        window.close()
        service.prefetch_threads[0].join(2)

    assert not service.prefetch_threads[0].is_alive()


def test_quitting_cancels_the_download(qtbot, qapp, make_window):
    window, service, _gate = held(make_window, prefetch_result=PrefetchResult("complete", files=1))
    qtbot.waitUntil(lambda: bool(service.prefetch_threads), timeout=5000)

    with qtbot.assertNotEmitted(window.prefetch_finished, wait=200):
        qapp.aboutToQuit.emit()
        service.prefetch_threads[0].join(2)

    assert not service.prefetch_threads[0].is_alive()


def test_a_report_for_a_deleted_window_is_dropped(caplog):
    signals = _Signals()
    shiboken6.delete(signals)

    with caplog.at_level(logging.DEBUG, logger="cloudyreader.gui.main_window"):
        _emit(signals, "prefetch_done", PrefetchResult("nothing"))  # must not raise

    assert any("window is gone" in r.getMessage() for r in caplog.records)


def test_reports_queued_before_close_are_ignored_after_it(qtbot, window):
    finished = []
    window.prefetch_finished.connect(finished.append)
    window.close()

    window._on_prefetch_progress(progress(1, 10))  # private on purpose: a queued late delivery
    window._on_prefetch_done(PrefetchResult("complete", files=1))

    assert window.prefetch_label.isHidden()
    assert finished == []
    assert not window._refreshing


# --- one bar at a time ----------------------------------------------------------------------
# Busy goes through _set_busy(): what Speak does, with no reading held on a thread.


def right_margin(window, widget) -> int:
    bar = window.statusBar()
    bar.layout().activate()
    widget.parentWidget().layout().activate()  # the download bar sits in its cluster
    return bar.width() - widget.mapTo(bar, QPoint(widget.width(), 0)).x()


def test_a_download_bar_alone_keeps_the_window_margin(window):
    window._on_prefetch_progress(progress(1, 50))  # private on purpose: a report, no thread

    assert window.busy_bar.isHidden()
    assert right_margin(window, window.prefetch_bar) == tokens.MARGIN


@pytest.mark.parametrize("download_first", [True, False])
def test_a_reading_prepared_during_a_download_shows_only_the_download_bar(window, download_first):
    if download_first:
        window._on_prefetch_progress(progress(1, 50))
    window._set_busy(True)
    if not download_first:
        window._on_prefetch_progress(progress(1, 50))

    assert window.busy_bar.isHidden()
    assert window.prefetch_bar.isVisible()
    assert right_margin(window, window.prefetch_bar) == tokens.MARGIN


def test_the_busy_bar_stays_hidden_when_the_reading_ends_during_a_download(window):
    window._on_prefetch_progress(progress(1, 50))
    window._set_busy(True)

    window._set_busy(False)

    assert window.busy_bar.isHidden()
    assert right_margin(window, window.prefetch_bar) == tokens.MARGIN


def test_the_busy_bar_returns_when_the_download_ends_during_a_reading(window):
    window._on_prefetch_progress(progress(1, 50))
    window._set_busy(True)

    window._on_prefetch_done(PrefetchResult("nothing"))

    assert window.busy_bar.isVisible()
    assert right_margin(window, window.busy_bar) == tokens.MARGIN


# --- the download label's wording -------------------------------------------------------------


@pytest.mark.parametrize(
    ("size", "said"),
    [
        (0, "0 MB"),
        (22 * MB, "22 MB"),
        (330 * MB, "330 MB"),
        (999_400_000, "999 MB"),
        (999_600_000, "1.0 GB"),  # never "1,000 MB": a thousand megabytes read as gigabytes
        (1_240 * MB, "1.2 GB"),
        (1_973 * MB, "2.0 GB"),
    ],
)
def test_sizes_read_in_decimal_units_as_finder_counts_them(size, said):
    assert size_text(size) == said


@pytest.mark.parametrize(
    ("done", "total", "sizes"),
    [
        (139 * MB, 330 * MB, "139 of 330 MB"),  # under a gigabyte: one unit, said once
        (829 * MB, 1_973 * MB, "829 MB of 2.0 GB"),
        (1_240 * MB, 1_970 * MB, "1.2 GB of 2.0 GB"),
    ],
)
def test_the_download_label_drops_its_sizes_then_its_verb(done, total, sizes):
    wordings = download_variants("Qwen3-TTS", 42, done, total)

    assert wordings == (
        f"Downloading Qwen3-TTS… 42% ({sizes})",
        "Downloading Qwen3-TTS… 42%",
        "Qwen3-TTS 42%",
    )
