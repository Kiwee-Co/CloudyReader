"""Engine voices in the window: group download rows, row reasons, notes, and the first-use hint."""

import threading
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from cloudyreader.engine_catalog import LOW_DISK, NOT_IN_BUILD, NOT_WRITABLE
from cloudyreader.gui.fake_service import ENGINE_FAKE_VOICES, FAKE_VOICES, FakeReaderService
from cloudyreader.gui.status import Tone
from cloudyreader.gui.voice_picker import VoicePicker
from cloudyreader.models import RenderOptions
from cloudyreader.prefetch import PrefetchProgress, PrefetchResult

LESSAC = "piper:en_US-lessac-medium"
AMY = "piper:en_US-amy-medium"
MICHAEL = "kokoro:am_michael"  # listed, not installed, and no reason: a row from before engines
CHATTERBOX = "chatterbox_turbo:builtin"
RYAN = "qwen3_tts:ryan"
AIDEN = "qwen3_tts:aiden"
MB = 10**6
DISK = f"{LOW_DISK}: needs 3.2 GB, 1.1 GB free"
GATE = "waiting for a Qwen3 decoder fix"
HINT = "loading Chatterbox Turbo (first use only)"
NOTE = "Ryan (male, Qwen3-TTS) is not ready: not downloaded yet. Using Lessac (female, Piper)."
PARTIAL = "Some voices could not be downloaded. They are tried again at the next start."


def status(window) -> str:
    return window.statusBar().currentMessage()


def refresh(qtbot, window) -> None:
    with qtbot.waitSignal(window.voices_refreshed, timeout=5000):
        window._refresh_voices()  # private on purpose: the download path is tested elsewhere


def report(group: str, done_mb: int, total_mb: int, *, files_done: int = 0) -> PrefetchProgress:
    """A report inside one group; the whole run stands at 1,489 of 3,050 MB (48%)."""
    return PrefetchProgress(
        "model.safetensors",
        1_489 * MB,
        3_050 * MB,
        files_done,
        64,
        group=group,
        group_done_bytes=done_mb * MB,
        group_total_bytes=total_mb * MB,
    )


def with_ryan(**changes) -> list:
    return [replace(v, **changes) if v.key == RYAN else v for v in ENGINE_FAKE_VOICES]


def ryan_not_ready() -> list:
    return with_ryan(installed=False, reason="not downloaded yet")


def rows(picker) -> list:
    model = picker.combo.model()
    return [model.item(row) for row in range(model.rowCount())]


def row(picker, key: str):
    return next(item for item in rows(picker) if item.data(Qt.ItemDataRole.UserRole) == key)


def headers(picker) -> list[str]:
    return [item.text() for item in rows(picker) if item.data(Qt.ItemDataRole.UserRole) is None]


# --- the download row ------------------------------------------------------------------------


def test_a_group_report_names_the_engine_its_percent_and_its_megabytes(window):
    window._on_prefetch_progress(report("qwen3_tts", 829, 1_973))  # private on purpose: no thread

    assert window.prefetch_label.text() == "Downloading Qwen3-TTS… 42% (829 MB of 2.0 GB)"
    assert window.prefetch_label.toolTip() == "model.safetensors (all downloads: 48%)"
    assert window.prefetch_bar.value() == 42  # the group's percent, floored, as in the label
    assert window.prefetch_bar.accessibleName() == "Downloading Qwen3-TTS"
    assert window.prefetch_label.isVisible()
    assert window.prefetch_bar.isVisible()


@pytest.mark.parametrize(
    ("group", "title"),
    [
        ("voices", "Piper voices"),
        ("kokoro", "Kokoro"),
        ("chatterbox_turbo", "Chatterbox Turbo"),
        ("qwen3_tts", "Qwen3-TTS"),
    ],
)
def test_every_group_has_its_title(window, group, title):
    window._on_prefetch_progress(report(group, 5, 10))

    assert window.prefetch_label.text() == f"Downloading {title}… 50% (5 of 10 MB)"
    assert window.prefetch_bar.value() == 50
    assert window.prefetch_bar.accessibleName() == f"Downloading {title}"


def test_a_report_without_a_group_keeps_the_voices_label_tooltip_and_name(window):
    window._on_prefetch_progress(report("kokoro", 5, 10))

    window._on_prefetch_progress(
        PrefetchProgress("en_US-lessac-medium.onnx", 50 * MB, 200 * MB, 0, 4)
    )

    assert window.prefetch_label.text() == "Downloading voices… 25%"
    assert window.prefetch_label.toolTip() == "en_US-lessac-medium.onnx: 50.0 of 200.0 MB"
    assert window.prefetch_bar.value() == 25
    assert window.prefetch_bar.accessibleName() == "Downloading voices"


def test_a_new_group_re_lists_once_so_a_finished_engine_appears_mid_run(qtbot, make_window):
    service = FakeReaderService(voices=ENGINE_FAKE_VOICES)
    window = make_window(service=service)
    window._on_prefetch_progress(report("chatterbox_turbo", 100, 420, files_done=1))
    window._on_prefetch_progress(report("chatterbox_turbo", 420, 420, files_done=2))
    assert not window.voice_picker.select_voice(CHATTERBOX)
    service.voice_list = [
        replace(v, installed=True, reason="") if v.key == CHATTERBOX else v
        for v in ENGINE_FAKE_VOICES
    ]

    with qtbot.waitSignal(window.voices_refreshed, timeout=5000):
        window._on_prefetch_progress(report("qwen3_tts", 10, 1_973, files_done=3))
    window._on_prefetch_progress(report("qwen3_tts", 900, 1_973, files_done=4))
    qtbot.wait(100)

    assert len(service.voices_threads) == 2  # the first load, then exactly one re-list
    assert window.voice_picker.select_voice(CHATTERBOX)


# --- picker rows -----------------------------------------------------------------------------


@pytest.fixture
def picker(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    widget = VoicePicker(host)
    widget.set_voices(ENGINE_FAKE_VOICES)
    yield widget  # the host lives as long as the fixture: qtbot keeps only a weak reference


def test_engine_groups_follow_piper_and_kokoro_under_their_titles(picker):
    assert headers(picker) == ["Piper", "Kokoro", "Chatterbox Turbo", "Qwen3-TTS"]


def test_a_dimmed_row_ends_with_its_reason_and_holds_it_in_a_tooltip(picker):
    item = row(picker, CHATTERBOX)

    assert item.text() == "Built-in · Chatterbox Turbo · 4-bit — not downloaded yet"
    assert item.toolTip() == "not downloaded yet"
    assert not item.isEnabled()
    assert not picker.select_voice(CHATTERBOX)


@pytest.mark.parametrize(
    ("reason", "shown"),
    [
        (GATE, GATE),
        (DISK, "not enough disk space"),  # the row keeps the part before the colon
        ("offline: not downloaded", "offline: not downloaded"),
        (NOT_WRITABLE, NOT_WRITABLE),
        ("damaged: SHA-256 mismatch for model.safetensors", "damaged"),
    ],
)
def test_every_reason_reads_in_the_row_and_the_whole_of_it_in_the_tooltip(picker, reason, shown):
    picker.set_voices(with_ryan(installed=False, reason=reason))
    item = row(picker, RYAN)

    assert item.text() == f"Ryan (male) · Qwen3-TTS · 8-bit — {shown}"
    assert item.toolTip() == reason
    assert not item.isEnabled()


def test_a_row_without_a_reason_says_it_is_not_downloaded_yet_and_has_no_tooltip(picker):
    item = row(picker, MICHAEL)

    assert item.text() == "Michael (US, male) · Kokoro · Grade C+ — not downloaded yet"
    assert item.toolTip() == ""


def test_an_installed_engine_voice_is_a_plain_choice(picker):
    item = row(picker, AIDEN)

    assert item.text() == "Aiden (US, male) · Qwen3-TTS · 8-bit"
    assert item.toolTip() == ""
    assert picker.select_voice(AIDEN)


def test_an_engine_without_rows_gets_no_header(picker):
    # A hard blocker (no Apple Silicon, packages missing, not in this build) or nothing pinned:
    # the service lists no row for that engine, so the picker shows no empty group.
    picker.set_voices([v for v in ENGINE_FAKE_VOICES if v.engine != "qwen3_tts"])

    assert headers(picker) == ["Piper", "Kokoro", "Chatterbox Turbo"]


# --- the saved voice that is not ready -------------------------------------------------------


@pytest.fixture
def ryan_saved(settings):
    settings.setValue("voice", RYAN)
    return settings


def test_a_saved_voice_that_is_not_ready_falls_back_with_a_note(make_window, ryan_saved):
    window = make_window(service=FakeReaderService(voices=ryan_not_ready()))

    assert window.voice_picker.voice_key() == LESSAC
    assert status(window) == NOTE
    assert window.statusBar().tone is Tone.INFO
    assert ryan_saved.value("voice") == RYAN  # the fallback never replaces the choice


def test_the_note_comes_once_at_load_and_not_with_a_re_list(qtbot, make_window, ryan_saved):
    window = make_window(service=FakeReaderService(voices=ryan_not_ready()))
    window.statusBar().clearMessage()

    refresh(qtbot, window)

    assert window.voice_picker.voice_key() == LESSAC
    assert status(window) == ""


def test_the_note_goes_when_the_saved_voice_lands(qtbot, make_window, ryan_saved):
    service = FakeReaderService(voices=ryan_not_ready())
    window = make_window(service=service)
    assert status(window) == NOTE

    service.voice_list = list(ENGINE_FAKE_VOICES)
    refresh(qtbot, window)

    assert window.voice_picker.voice_key() == RYAN
    assert status(window) == ""


def test_a_landing_voice_leaves_a_newer_message_alone(qtbot, make_window, ryan_saved):
    service = FakeReaderService(voices=ryan_not_ready())
    window = make_window(service=service)
    window.speak_button.click()  # an empty box: its hint replaces the note

    service.voice_list = list(ENGINE_FAKE_VOICES)
    refresh(qtbot, window)

    assert window.voice_picker.voice_key() == RYAN
    assert status(window) == "Paste a question first."


def test_the_note_goes_when_the_user_picks_a_voice(make_window, ryan_saved):
    window = make_window(service=FakeReaderService(voices=ryan_not_ready()))

    window.voice_picker.select_voice(AMY)

    assert status(window) == ""
    assert ryan_saved.value("voice") == AMY


def test_a_saved_voice_without_a_reason_falls_back_quietly(make_window, settings):
    settings.setValue("voice", MICHAEL)

    window = make_window(service=FakeReaderService(voices=ENGINE_FAKE_VOICES))

    assert window.voice_picker.voice_key() == LESSAC
    assert status(window) == ""


def test_with_nothing_installed_the_no_voice_warning_stays(make_window, ryan_saved):
    voices = [replace(v, installed=False, reason="not downloaded yet") for v in ENGINE_FAKE_VOICES]

    window = make_window(service=FakeReaderService(voices=voices))

    assert status(window) == "No voice is installed."
    assert window.statusBar().tone is Tone.WARNING


# --- the end of the run ----------------------------------------------------------------------


def test_a_skip_the_user_can_act_on_warns_at_the_end_of_the_run(window):
    window._on_prefetch_done(PrefetchResult("nothing", skipped=(f"qwen3_tts: {DISK}",)))

    assert status(window) == f"Qwen3-TTS not downloaded: {DISK}"
    assert window.statusBar().tone is Tone.WARNING


def test_the_skip_tooltip_lists_every_skip(window):
    skipped = (f"chatterbox_turbo: {NOT_WRITABLE}", f"qwen3_tts: {GATE}", "conflict: /x/a.onnx")

    window._on_prefetch_done(PrefetchResult("nothing", skipped=skipped))

    assert status(window) == f"Chatterbox Turbo not downloaded: {NOT_WRITABLE}"
    assert window.statusBar().toolTip() == (
        f"Chatterbox Turbo not downloaded: {NOT_WRITABLE}\n"
        f"Qwen3-TTS not downloaded: {GATE}\n"
        "conflict: /x/a.onnx"
    )


@pytest.mark.parametrize(
    "skip", [f"qwen3_tts: {GATE}", f"chatterbox_turbo: {NOT_IN_BUILD}", "conflict: /x/a.onnx"]
)
def test_gate_build_and_other_skips_stay_in_the_picker(window, skip):
    window._on_prefetch_done(PrefetchResult("nothing", skipped=(skip,)))

    assert status(window) == ""


def test_a_skip_warning_never_covers_a_message_in_the_slot(window):
    window.speak_button.click()  # an empty box: its hint takes the slot

    window._on_prefetch_done(PrefetchResult("nothing", skipped=(f"qwen3_tts: {DISK}",)))

    assert status(window) == "Paste a question first."


def test_a_skip_worth_acting_on_outranks_voices_downloaded(qtbot, window):
    result = PrefetchResult("complete", files=3, skipped=(f"qwen3_tts: {DISK}",))

    with qtbot.waitSignal(window.voices_refreshed, timeout=5000):
        window._on_prefetch_done(result)

    assert status(window) == f"Qwen3-TTS not downloaded: {DISK}"


def test_failed_engine_files_still_warn_as_partial_and_are_named(window):
    result = PrefetchResult(
        "partial",
        failed=("qwen3_tts/model.safetensors",),
        skipped=(f"chatterbox_turbo: {DISK}",),
    )

    window._on_prefetch_done(result)

    assert status(window) == PARTIAL
    assert "qwen3_tts/model.safetensors" in window.statusBar().toolTip()


# --- first use -------------------------------------------------------------------------------


def speak_twice(qtbot, window) -> list[str]:
    """Speak two times; returns the status each click showed before its reading arrived."""
    window.question_edit.setPlainText("What is H2O?")
    shown = []
    for _ in range(2):
        with qtbot.waitSignal(window.reading_played, timeout=5000):
            window.speak_button.click()
            shown.append(status(window))  # the queued result has not been delivered yet
    return shown


def test_the_first_use_hint_shows_while_preparing_only_once(qtbot, make_window):
    service = FakeReaderService(load_hint=HINT)
    window = make_window(service=service)

    shown = speak_twice(qtbot, window)

    assert shown == [f"Preparing… {HINT}", "Preparing…"]
    assert status(window) == "Playing 2.0 s."
    assert service.load_hint_calls == [(LESSAC, threading.main_thread())] * 2


def test_a_failing_hint_never_stops_the_reading(qtbot, make_window, monkeypatch, caplog):
    def broken(_voice_key: str) -> str:
        raise RuntimeError("engine table busy")

    monkeypatch.setattr(FakeReaderService, "load_hint", property(lambda _self: broken))
    window = make_window()

    shown = speak_twice(qtbot, window)

    assert shown == ["Preparing…", "Preparing…"]
    assert any(r.exc_info and "engine table busy" in str(r.exc_info[1]) for r in caplog.records)


# --- the fakes -------------------------------------------------------------------------------


def test_engine_fake_voices_add_a_dimmed_chatterbox_and_two_qwen_voices():
    assert ENGINE_FAKE_VOICES[: len(FAKE_VOICES)] == FAKE_VOICES
    added = ENGINE_FAKE_VOICES[len(FAKE_VOICES) :]
    assert [(v.key, v.name, v.installed, v.reason) for v in added] == [
        (CHATTERBOX, "Chatterbox Turbo (built-in)", False, "not downloaded yet"),
        (RYAN, "Ryan (male)", True, ""),
        (AIDEN, "Aiden (male)", True, ""),
    ]
    assert [v.engine for v in added] == ["chatterbox_turbo", "qwen3_tts", "qwen3_tts"]


def test_the_load_hint_hook_is_absent_by_default_like_a_service_without_one():
    service = FakeReaderService()

    assert service.load_hint is None
    assert getattr(service, "load_hint", None) is None


def test_the_load_hint_lasts_until_that_voice_is_prepared():
    service = FakeReaderService(load_hint=HINT)

    assert service.load_hint(LESSAC) == HINT
    service.prepare("a", LESSAC, RenderOptions())

    assert service.load_hint(LESSAC) is None
    assert service.load_hint(AMY) == HINT
    assert [key for key, _thread in service.load_hint_calls] == [LESSAC, LESSAC, AMY]


def test_a_failed_prepare_keeps_the_hint():
    service = FakeReaderService(load_hint=HINT, error=RuntimeError("model load failed"))

    with pytest.raises(RuntimeError, match="model load failed"):
        service.prepare("a", LESSAC, RenderOptions())

    assert service.load_hint(LESSAC) == HINT
