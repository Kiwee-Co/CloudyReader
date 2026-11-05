"""Voice rotation in the window: the Rotation row, its saved mode, and the voice that reads next."""

import random
import threading
from dataclasses import replace

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLabel

from cloudyreader.gui.fake_service import FAKE_VOICES, FakeReaderService
from cloudyreader.gui.main_window import _voice_label
from cloudyreader.gui.widgets import Tone
from cloudyreader.models import VoiceInfo
from cloudyreader.rotation import RotationMode, VoiceRotator

LESSAC = "piper:en_US-lessac-medium"
AMY = "piper:en_US-amy-medium"
ALAN = "piper:en_GB-alan-medium"
LIBRITTS = "piper:en_US-libritts-high"
HEART = "kokoro:af_heart"
MICHAEL = "kokoro:am_michael"
POOLS = {  # what R's pool() keeps from FAKE_VOICES
    RotationMode.SHUFFLE: {LESSAC, AMY, ALAN, HEART},
    RotationMode.US_SHUFFLE: {LESSAC, AMY, HEART},
    RotationMode.MEN_SHUFFLE: {ALAN},
    RotationMode.WOMEN_SHUFFLE: {LESSAC, AMY, HEART},
}


def choose(window, mode: RotationMode) -> None:
    window.rotation_combo.setCurrentIndex(window.rotation_combo.findData(str(mode)))


def speak(qtbot, window, text="What is H2O?"):
    window.question_edit.setPlainText(text)
    with qtbot.waitSignal(window.reading_played, timeout=5000):
        window.speak_button.click()


def status(window) -> str:
    return window.statusBar().currentMessage()


def spoken(service) -> list[str]:
    return [call.voice_key for call in service.calls]


# --- the Rotation row ------------------------------------------------------------------------


def test_the_rotation_row_lists_the_six_modes_in_order(window):
    combo = window.rotation_combo

    assert [combo.itemText(i) for i in range(combo.count())] == [
        "No rotation",
        "Round robin",
        "Random shuffle",
        "US only (random shuffle)",
        "Men only",
        "Women only",
    ]
    assert [combo.itemData(i) for i in range(combo.count())] == [str(m) for m in RotationMode]


def test_no_rotation_is_the_default(window):
    assert window.rotation_combo.currentText() == "No rotation"
    assert window.rotation_mode is RotationMode.NONE


def test_the_combo_is_named_and_labelled_for_assistive_tech(window):
    labels = window.centralWidget().findChildren(QLabel)

    assert window.rotation_combo.accessibleName() == "Voice rotation"
    assert [w.text() for w in labels if w.buddy() is window.rotation_combo] == ["Rotation:"]


def test_rotation_mode_follows_the_combo(window):
    choose(window, RotationMode.WOMEN_SHUFFLE)

    assert window.rotation_mode is RotationMode.WOMEN_SHUFFLE


def test_the_mode_persists_under_voice_rotation(make_window, tmp_path):
    path = str(tmp_path / "prefs.ini")
    first = make_window(settings=QSettings(path, QSettings.Format.IniFormat))
    choose(first, RotationMode.ROUND_ROBIN)
    first.close()

    second = make_window(settings=QSettings(path, QSettings.Format.IniFormat))

    assert QSettings(path, QSettings.Format.IniFormat).value("voice_rotation") == "round_robin"
    assert second.rotation_mode is RotationMode.ROUND_ROBIN
    assert second.rotation_combo.currentText() == "Round robin"


def test_stored_junk_reads_as_no_rotation_and_stays_on_disk(make_window, settings):
    settings.setValue("voice_rotation", "sideways")

    window = make_window()

    assert window.rotation_mode is RotationMode.NONE
    assert settings.value("voice_rotation") == "sideways"


# --- which voice reads -----------------------------------------------------------------------


def test_no_rotation_sends_the_picker_voice_and_speaker(qtbot, window, service):
    window.voice_picker.select_voice(LIBRITTS)
    window.voice_picker.speaker_spin.setValue(12)
    gate = service.gate = threading.Event()
    window.question_edit.setPlainText("q")
    window.speak_button.click()
    preparing = status(window)

    with qtbot.waitSignal(window.reading_played, timeout=5000):
        gate.set()

    assert preparing == "Preparing…"
    assert spoken(service) == [LIBRITTS]
    assert service.calls[-1].opts.speaker_id == 12
    assert status(window) == "Playing 2.0 s."


def test_round_robin_walks_the_pool_in_list_order(qtbot, window, service):
    choose(window, RotationMode.ROUND_ROBIN)

    for _ in range(5):
        speak(qtbot, window)

    assert spoken(service) == [LESSAC, AMY, ALAN, HEART, LESSAC]
    assert {call.opts.speaker_id for call in service.calls} == {None}


@pytest.mark.parametrize("mode", list(POOLS))
def test_each_shuffle_mode_reads_with_the_rotators_pick(qtbot, make_window, service, mode):
    window = make_window(rotator=VoiceRotator(rng=random.Random(7)))
    reference = VoiceRotator(mode, rng=random.Random(7))
    choose(window, mode)

    for _ in range(6):
        speak(qtbot, window)

    assert spoken(service) == [reference.next_voice(FAKE_VOICES).key for _ in range(6)]
    assert set(spoken(service)) <= POOLS[mode]
    assert {call.opts.speaker_id for call in service.calls} == {None}


def test_both_speak_paths_advance_and_repeat_reuses_the_voice(
    qtbot, window, service, clipboard, player
):
    choose(window, RotationMode.ROUND_ROBIN)
    speak(qtbot, window)
    clipboard.set_text("from the clipboard")
    with qtbot.waitSignal(window.reading_played, timeout=5000):
        window.speak_clipboard_button.click()

    window.repeat_button.click()
    speak(qtbot, window)

    assert player.replay_calls == 1
    assert spoken(service) == [LESSAC, AMY, ALAN]


def test_speaks_that_do_nothing_never_advance_the_rotation(qtbot, window, service):
    choose(window, RotationMode.ROUND_ROBIN)
    window.question_edit.setPlainText("  ")
    window.speak_button.click()  # blank question
    window.speak_clipboard_button.click()  # empty clipboard
    gate = service.gate = threading.Event()
    window.question_edit.setPlainText("q")
    window.speak_button.click()
    window._on_speak()  # busy: the slot's own guard
    window._on_speak_clipboard()
    with qtbot.waitSignal(window.reading_played, timeout=5000):
        gate.set()

    speak(qtbot, window)

    assert spoken(service) == [LESSAC, AMY]


def test_a_window_without_a_voice_never_advances(make_window):
    rotator = VoiceRotator()
    window = make_window(service=FakeReaderService(voices=[]), rotator=rotator)
    choose(window, RotationMode.ROUND_ROBIN)
    window.question_edit.setPlainText("q")

    window._on_speak()

    assert rotator.last_key is None
    assert status(window) == "No voice is installed."


def test_the_stored_voice_and_the_speaker_never_change(qtbot, window, settings):
    window.voice_picker.select_voice(LIBRITTS)
    window.voice_picker.speaker_spin.setValue(5)
    choose(window, RotationMode.ROUND_ROBIN)

    speak(qtbot, window)
    speak(qtbot, window)

    assert settings.value("voice") == LIBRITTS
    assert window.voice_picker.voice_key() == LIBRITTS
    assert window.voice_picker.speaker_id() == 5


def test_the_pool_follows_a_refreshed_list(qtbot, window, service):
    choose(window, RotationMode.MEN_SHUFFLE)
    speak(qtbot, window)
    service.voice_list = [replace(v, installed=True) for v in FAKE_VOICES]
    with qtbot.waitSignal(window.voices_refreshed, timeout=5000):
        window._refresh_voices()  # private on purpose: what a finished download triggers

    speak(qtbot, window)

    assert spoken(service) == [ALAN, MICHAEL]  # a new deck never opens with the last voice


def test_an_empty_pool_falls_back_to_the_picker_voice_with_a_warning(qtbot, make_window):
    service = FakeReaderService(voices=[v for v in FAKE_VOICES if v.key != ALAN])
    window = make_window(service=service)
    window.voice_picker.select_voice(LIBRITTS)
    window.voice_picker.speaker_spin.setValue(3)
    choose(window, RotationMode.MEN_SHUFFLE)
    warning = "No installed voice matches “Men only”; using the selected voice."
    gate = service.gate = threading.Event()
    window.question_edit.setPlainText("q")
    window.speak_button.click()
    preparing = (status(window), window.statusBar().tone)

    with qtbot.waitSignal(window.reading_played, timeout=5000):
        gate.set()

    assert preparing == (warning, Tone.WARNING)
    assert (status(window), window.statusBar().tone) == (warning, Tone.WARNING)
    assert spoken(service) == [LIBRITTS]
    assert service.calls[-1].opts.speaker_id == 3


def test_the_status_names_the_rotated_voice(qtbot, window, service):
    choose(window, RotationMode.ROUND_ROBIN)
    gate = service.gate = threading.Event()
    window.question_edit.setPlainText("q")
    window.speak_button.click()
    preparing = status(window)

    with qtbot.waitSignal(window.reading_played, timeout=5000):
        gate.set()

    assert preparing == "Preparing with Lessac (female)…"
    assert status(window) == "Playing 2.0 s with Lessac (female)."


# --- real voice names --------------------------------------------------------------------------
# scan_installed() names a Piper voice by its file stem ("lessac"); KokoroEngine writes the gender
# into the name ("Heart (female)"). The fakes above use neither shape.

REAL_LESSAC = VoiceInfo("piper:en_US-lessac-medium", "piper", "lessac", "en-US", "medium", 1, True)
REAL_HEART = VoiceInfo("kokoro:af_heart", "kokoro", "Heart (female)", "en-US", "A", 1, True)


@pytest.mark.parametrize(
    ("voice", "label"), [(REAL_HEART, "Heart (female)"), (REAL_LESSAC, "lessac (female)")]
)
def test_the_rotated_voice_label_names_the_gender_once(voice, label):
    assert _voice_label(voice) == label


def test_the_status_names_a_real_kokoro_voice_without_doubling_its_gender(qtbot, make_window):
    service = FakeReaderService(voices=[REAL_HEART])
    window = make_window(service=service)
    choose(window, RotationMode.ROUND_ROBIN)
    gate = service.gate = threading.Event()
    window.question_edit.setPlainText("q")
    window.speak_button.click()
    preparing = status(window)

    with qtbot.waitSignal(window.reading_played, timeout=5000):
        gate.set()

    assert preparing == "Preparing with Heart (female)…"
    assert status(window) == "Playing 2.0 s with Heart (female)."


def test_the_status_names_a_real_piper_voice_as_the_picker_does(qtbot, make_window):
    window = make_window(service=FakeReaderService(voices=[REAL_LESSAC]))
    choose(window, RotationMode.ROUND_ROBIN)

    speak(qtbot, window)

    assert status(window) == "Playing 2.0 s with lessac (female)."
