import importlib.metadata
import inspect
import threading
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from cloudyreader.gui import fake_service, main_window, names, tokens
from cloudyreader.gui.about import AboutPanel
from cloudyreader.gui.fake_service import FakePlayer, FakeReaderService
from cloudyreader.gui.main_window import MainWindow, _Job, _Signals
from cloudyreader.models import RenderOptions

AMY = "piper:en_US-amy-medium"
LESSAC = "piper:en_US-lessac-medium"
LIBRITTS = "piper:en_US-libritts-high"
HEART = "kokoro:af_heart"
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT_CMD_V = (Qt.Key.Key_V, CTRL | Qt.KeyboardModifier.ShiftModifier)


def speak(qtbot, window, text="What is H2O?"):
    window.question_edit.setPlainText(text)
    with qtbot.waitSignal(window.reading_played, timeout=5000) as blocker:
        window.speak_button.click()
    return blocker.args[0]


def status(window) -> str:
    return window.statusBar().currentMessage()


# --- initial state ---------------------------------------------------------------------------


def test_initial_state(window):
    assert window.windowTitle() == "Cloudy Reader"
    assert window.speak_button.isEnabled()
    assert not window.repeat_button.isEnabled()
    assert not window.stop_button.isEnabled()
    assert not window.read_answer_check.isChecked()
    assert window.online_lookups_check.isChecked()
    assert window.script_view.isVisible()
    assert status(window) == ""


def test_window_has_a_usable_minimum_size(window):
    assert window.minimumSize().width() == tokens.WINDOW_MIN_SIZE[0]
    assert window.minimumSize().height() == tokens.WINDOW_MIN_SIZE[1]


# --- speak -----------------------------------------------------------------------------------


def test_speak_sends_text_voice_and_options_to_the_service(qtbot, window, service):
    window.voice_picker.select_voice(AMY)
    window.read_answer_check.setChecked(True)
    window.online_lookups_check.setChecked(False)

    speak(qtbot, window, "TOSS-UP\n2) EARTH SCIENCE ...")

    call = service.calls[-1]
    assert call.raw == "TOSS-UP\n2) EARTH SCIENCE ..."
    assert call.voice_key == AMY
    assert call.opts == RenderOptions(read_answer=True, online_lookups=False, speaker_id=None)


def test_default_options_keep_the_answer_silent_and_lookups_on(qtbot, window, service):
    speak(qtbot, window)

    assert service.calls[-1].opts == RenderOptions(read_answer=False, online_lookups=True)


def test_speak_sends_the_speaker_id_of_a_multi_speaker_voice(qtbot, window, service):
    window.voice_picker.select_voice(LIBRITTS)
    window.voice_picker.speaker_spin.setValue(12)

    speak(qtbot, window)

    assert service.calls[-1].opts.speaker_id == 12


def test_prepare_runs_off_the_ui_thread_and_play_runs_on_it(qtbot, window, service, player):
    reading = speak(qtbot, window)

    assert service.calls[0].thread is not threading.main_thread()
    assert player.play_threads == [threading.main_thread()]
    assert player.played == [reading.audio]


def test_ui_stays_responsive_while_the_worker_is_blocked(qtbot, window, service, player):
    gate = service.gate = threading.Event()
    window.question_edit.setPlainText("q")
    window.speak_button.click()
    ticks = []
    QTimer.singleShot(10, lambda: ticks.append(1))

    qtbot.waitUntil(lambda: bool(ticks), timeout=2000)

    assert status(window).startswith("Preparing")
    assert window.busy_bar.isVisible()
    assert not window.speak_button.isEnabled()
    assert player.played == []
    with qtbot.waitSignal(window.reading_played, timeout=5000):
        gate.set()
    assert not window.busy_bar.isVisible()
    assert len(player.played) == 1


def test_busy_changed_brackets_the_preparation(qtbot, window):
    states = []
    window.busy_changed.connect(states.append)

    speak(qtbot, window)

    assert states == [True, False]


def test_second_speak_while_busy_is_ignored(qtbot, window, service):
    gate = service.gate = threading.Event()
    window.question_edit.setPlainText("q")
    window.speak_button.click()

    window.speak_button.click()
    window.speak_action.trigger()
    # The slot guards itself too, in case a click was queued before the state changed.
    window._on_speak()
    with qtbot.waitSignal(window.reading_played, timeout=5000):
        gate.set()

    assert len(service.calls) == 1
    assert window.question_edit.toPlainText() == "q"


def test_a_new_speak_replaces_audio_that_is_still_playing(qtbot, window, player):
    speak(qtbot, window)
    speak(qtbot, window)

    assert len(player.played) == 2
    assert player.stop_calls == 1


def test_blank_question_is_not_sent(window, service):
    window.question_edit.setPlainText("  \n ")

    window.speak_button.click()

    assert service.calls == []
    assert status(window) == "Paste a question first."


def test_playing_message_names_the_duration(qtbot, window):
    speak(qtbot, window)

    assert status(window) == "Playing 2.0 s."


# --- no clipboard commands: Edit > Paste (⌘V) brings the question in -------------------------


def test_no_paste_or_speak_clipboard_button_remains(window):
    buttons = [button.text() for button in window.centralWidget().findChildren(QPushButton)]

    assert sorted(buttons) == ["Repeat", "Speak", "Stop"]
    assert not hasattr(window, "paste_button")
    assert not hasattr(window, "speak_clipboard_button")


def test_the_reading_menu_has_no_speak_clipboard_command(window):
    menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "Reading")

    assert [action.text() for action in menu.actions()] == ["Speak", "", "Repeat", "Stop"]
    assert not hasattr(window, "speak_clipboard_action")


def test_shift_cmd_v_is_no_command_and_speaks_nothing(qtbot, window, service):
    taken = QKeySequence("Ctrl+Shift+V")
    window.question_edit.setPlainText("keep")

    qtbot.keyClick(window.question_edit, *SHIFT_CMD_V)

    assert [a.text() for a in window.findChildren(QAction) if taken in a.shortcuts()] == []
    assert service.calls == []
    assert window.question_edit.toPlainText() == "keep"


def test_no_clipboard_seam_is_left(window):
    assert "clipboard" not in inspect.signature(MainWindow).parameters
    assert not hasattr(main_window, "ClipboardSource")
    assert not hasattr(fake_service, "FakeClipboard")
    assert not hasattr(window, "_on_paste")
    assert not hasattr(window, "_on_speak_clipboard")


def test_the_window_never_reads_the_clipboard(qtbot, monkeypatch, service, player, settings):
    reads = []
    for app in (QGuiApplication, QApplication):
        monkeypatch.setattr(app, "clipboard", staticmethod(lambda: reads.append("read")))
    window = MainWindow(service, player, settings=settings)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: not window.loading_voices, timeout=5000)

    speak(qtbot, window)
    window.repeat_button.click()
    window.stop_button.click()
    qtbot.keyClick(window.question_edit, *SHIFT_CMD_V)

    assert reads == []


def test_edit_paste_still_reaches_the_question_box(window, monkeypatch):
    pasted = []
    monkeypatch.setattr(window.question_edit, "paste", lambda: pasted.append(True))  # no pasteboard
    window.question_edit.setFocus()

    window.paste_action.trigger()

    assert pasted == [True]
    paste = QKeySequence.keyBindings(QKeySequence.StandardKey.Paste)
    assert window.paste_action.shortcuts() == paste


# --- stop and repeat -------------------------------------------------------------------------


def test_stop_is_enabled_only_while_playing_and_calls_the_player(qtbot, window, player):
    assert not window.stop_button.isEnabled()
    speak(qtbot, window)
    assert window.stop_button.isEnabled()

    window.stop_button.click()

    assert player.stop_calls == 1
    assert not window.stop_button.isEnabled()
    assert status(window) == "Stopped."


def test_polling_leaves_a_playing_window_alone(qtbot, window):
    speak(qtbot, window)

    qtbot.wait(tokens.PLAYBACK_POLL_MS * 3)

    assert window.stop_button.isEnabled()
    assert status(window) == "Playing 2.0 s."


def test_stop_disables_itself_when_playback_ends_on_its_own(qtbot, window, player):
    speak(qtbot, window)

    player.finish()

    qtbot.waitUntil(lambda: not window.stop_button.isEnabled(), timeout=2000)
    assert player.stop_calls == 0
    assert status(window) == ""


class StubbornPlayer(FakePlayer):
    def stop(self):
        self.stop_calls += 1
        raise OSError("device busy")


def test_stop_error_reaches_the_status_bar_and_playback_goes_on(qtbot, make_window):
    window = make_window(player=StubbornPlayer())
    speak(qtbot, window)

    window.stop_button.click()

    assert status(window) == "Error: device busy"
    assert window.stop_button.isEnabled()


def test_repeat_is_disabled_until_the_first_successful_speak(qtbot, window, service):
    service.error = RuntimeError("boom")
    window.question_edit.setPlainText("q")
    with qtbot.waitSignal(window.error_occurred, timeout=5000):
        window.speak_button.click()
    assert not window.repeat_button.isEnabled()

    service.error = None
    speak(qtbot, window)

    assert window.repeat_button.isEnabled()


def test_repeat_replays_without_preparing_again(qtbot, window, service, player):
    speak(qtbot, window)
    player.finish()

    window.repeat_button.click()

    assert player.replay_calls == 1
    assert len(service.calls) == 1
    assert window.stop_button.isEnabled()


def test_repeat_keeps_stop_in_step_with_the_player(qtbot, window, player):
    speak(qtbot, window)
    player.finish()
    qtbot.waitUntil(lambda: not window.stop_button.isEnabled(), timeout=2000)

    window.repeat_button.click()
    assert window.stop_button.isEnabled()
    player.finish()

    qtbot.waitUntil(lambda: not window.stop_button.isEnabled(), timeout=2000)


def test_repeat_when_the_player_has_nothing_to_replay_says_so(window, player):
    window._on_repeat()  # the button is disabled here; this is the slot's own defense

    assert status(window) == "Nothing to repeat yet."
    assert player.replay_calls == 1


# --- script and warnings ---------------------------------------------------------------------


def test_script_area_is_open_and_shows_the_spoken_text(qtbot, window):
    assert window.script_view.isVisible()
    assert window.script_toggle.arrowType() == Qt.ArrowType.DownArrow
    assert window.script_view.isReadOnly()

    speak(qtbot, window, "alpha\nbeta")
    assert window.script_view.toPlainText() == "alpha beta"

    window.script_toggle.click()
    assert window.script_view.isHidden()
    assert window.script_toggle.arrowType() == Qt.ArrowType.RightArrow
    window.script_toggle.click()
    assert window.script_view.isVisible()
    assert window.script_toggle.arrowType() == Qt.ArrowType.DownArrow


def test_one_warning_reaches_the_status_bar(qtbot, window, service):
    service.warnings = ("no pronunciation for 'xyz'",)

    speak(qtbot, window)

    assert status(window) == "Warning: no pronunciation for 'xyz'"


def test_several_warnings_are_counted_and_listed(qtbot, window, service):
    service.warnings = ("first", "second")

    speak(qtbot, window)

    assert status(window) == "2 warnings: first; second"
    assert "first; second" in window.statusBar().toolTip()


def test_warnings_from_reading_and_script_are_merged_without_duplicates(qtbot, make_window):
    class ScriptWarnings(FakeReaderService):
        def prepare(self, raw, voice_key, opts):
            reading = super().prepare(raw, voice_key, opts)
            script = replace(reading.script, warnings=("a", "b"))
            return replace(reading, script=script, warnings=("b", "c"))

    window = make_window(service=ScriptWarnings())

    speak(qtbot, window)

    assert status(window) == "3 warnings: b; c; a"


def test_warnings_outlive_the_playback(qtbot, window, service, player):
    service.warnings = ("heads up",)
    speak(qtbot, window)

    player.finish()

    qtbot.waitUntil(lambda: not window.stop_button.isEnabled(), timeout=2000)
    assert status(window) == "Warning: heads up"


def test_menu_hover_does_not_wipe_the_status_message(window):
    window.speak_button.click()  # an empty box: its hint takes the slot
    menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "Reading")
    menu.popup(window.mapToGlobal(QPoint(10, 10)))

    menu.setActiveAction(window.speak_action)

    assert status(window) == "Paste a question first."
    menu.close()


# --- errors ----------------------------------------------------------------------------------


def test_service_error_reaches_the_status_bar_without_a_modal(qtbot, window, service):
    service.error = RuntimeError("voice file missing\nsecond line")
    window.question_edit.setPlainText("q")

    with qtbot.waitSignal(window.error_occurred, timeout=5000) as blocker:
        window.speak_button.click()

    assert status(window) == "Error: voice file missing"
    assert blocker.args == ["Error: voice file missing"]
    assert "second line" in window.statusBar().toolTip()
    assert QApplication.activeModalWidget() is None
    assert window.speak_button.isEnabled()
    assert not window.busy_bar.isVisible()


def test_error_without_a_message_names_the_exception_type(qtbot, window, service):
    service.error = KeyError()
    window.question_edit.setPlainText("q")

    with qtbot.waitSignal(window.error_occurred, timeout=5000):
        window.speak_button.click()

    assert status(window) == "Error: KeyError"


def test_player_error_reaches_the_status_bar(qtbot, window, player):
    player.error = OSError("no output device")
    window.question_edit.setPlainText("q")

    with qtbot.waitSignal(window.error_occurred, timeout=5000):
        window.speak_button.click()

    assert status(window) == "Error: no output device"
    assert not window.repeat_button.isEnabled()
    assert window.speak_button.isEnabled()


def test_repeat_error_reaches_the_status_bar(qtbot, window, player):
    speak(qtbot, window)
    player.error = OSError("device lost")

    with qtbot.waitSignal(window.error_occurred, timeout=2000):
        window.repeat_button.click()

    assert status(window) == "Error: device lost"


def test_a_failed_speak_does_not_disturb_earlier_audio(qtbot, window, service):
    speak(qtbot, window)
    service.error = RuntimeError("boom")

    window.speak_button.click()
    qtbot.waitUntil(lambda: status(window).startswith("Error"), timeout=5000)

    assert window.repeat_button.isEnabled()


def test_voice_listing_failure_is_reported_not_raised(make_window):
    class BrokenCatalog(FakeReaderService):
        def voices(self):
            raise RuntimeError("catalog unreadable")

    window = make_window(service=BrokenCatalog())

    assert status(window) == "Error: catalog unreadable"
    assert not window.speak_button.isEnabled()
    assert not window.loading_voices
    assert not window.busy_bar.isVisible()
    assert window.voice_picker.combo.placeholderText() == "Voices unavailable"
    assert not window.voice_picker.combo.isEnabled()


def test_no_installed_voice_disables_speaking(make_window):
    window = make_window(service=FakeReaderService(voices=[]))

    assert not window.speak_button.isEnabled()
    assert status(window) == "No voice is installed."


def test_speak_slot_refuses_without_a_voice_even_if_called_directly(make_window):
    service = FakeReaderService(voices=[])
    window = make_window(service=service)
    window.question_edit.setPlainText("q")

    window._on_speak()

    assert service.calls == []
    assert status(window) == "No voice is installed."


# --- voice loading ---------------------------------------------------------------------------


def test_voices_load_off_the_ui_thread_and_the_ui_stays_responsive(qtbot, make_window, service):
    gate = service.voices_gate = threading.Event()
    window = make_window(wait_for_voices=False)
    ticks = []
    QTimer.singleShot(10, lambda: ticks.append(1))

    qtbot.waitUntil(lambda: bool(ticks), timeout=2000)  # the event loop spins while voices() blocks

    assert window.loading_voices
    assert status(window) == "Loading voices\u2026"
    assert window.busy_bar.isVisible()
    assert window.voice_picker.combo.placeholderText() == "Loading voices\u2026"
    assert not window.voice_picker.combo.isEnabled()
    assert not window.speak_button.isEnabled()
    with qtbot.waitSignal(window.voices_settled, timeout=5000):
        gate.set()
    assert not window.loading_voices
    assert window.voice_picker.voice_key() == LESSAC
    assert window.speak_button.isEnabled()
    assert status(window) == ""
    assert not window.busy_bar.isVisible()
    assert service.voices_threads[0] is not threading.main_thread()


def test_a_saved_voice_is_selected_when_the_slow_list_arrives(
    qtbot, make_window, service, settings
):
    settings.setValue("voice", HEART)
    gate = service.voices_gate = threading.Event()
    window = make_window(wait_for_voices=False)

    with qtbot.waitSignal(window.voices_settled, timeout=5000):
        gate.set()

    assert window.voice_picker.voice_key() == HEART
    assert settings.value("voice") == HEART


def test_speak_slot_refuses_while_voices_load(qtbot, make_window, service):
    gate = service.voices_gate = threading.Event()
    window = make_window(wait_for_voices=False)
    window.question_edit.setPlainText("q")

    window._on_speak()

    assert service.calls == []
    assert status(window) == "Loading voices\u2026"
    with qtbot.waitSignal(window.voices_settled, timeout=5000):
        gate.set()


def test_a_message_that_replaced_the_loading_text_survives_the_arrival(qtbot, make_window, service):
    gate = service.voices_gate = threading.Event()
    window = make_window(wait_for_voices=False)
    window._on_repeat()  # Repeat is off while voices load; its slot still answers

    with qtbot.waitSignal(window.voices_settled, timeout=5000):
        gate.set()

    assert status(window) == "Nothing to repeat yet."


def test_a_slow_voice_list_that_fails_ends_the_loading_state(qtbot, make_window, service):
    gate = service.voices_gate = threading.Event()
    service.voices_error = RuntimeError("catalog unreadable")
    window = make_window(wait_for_voices=False)

    with qtbot.waitSignal(window.voices_settled, timeout=5000):
        gate.set()

    assert status(window) == "Error: catalog unreadable"
    assert not window.loading_voices
    assert not window.busy_bar.isVisible()
    assert not window.voice_picker.combo.isEnabled()
    assert window.voice_picker.combo.placeholderText() == "Voices unavailable"
    assert not window.speak_button.isEnabled()


def test_a_voice_list_arriving_after_close_is_dropped(qtbot, make_window, service):
    gate = service.voices_gate = threading.Event()
    window = make_window(wait_for_voices=False)
    gate.set()  # the list is ready; its signal reaches the window only after close()

    with qtbot.assertNotEmitted(window.voices_settled):
        window.close()  # waits for the worker
        qtbot.wait(100)

    assert window.loading_voices


def test_a_voice_list_failure_arriving_after_close_is_dropped(qtbot, make_window, service):
    gate = service.voices_gate = threading.Event()
    service.voices_error = RuntimeError("late")
    window = make_window(wait_for_voices=False)
    gate.set()

    with qtbot.assertNotEmitted(window.error_occurred):
        window.close()
        qtbot.wait(100)


# --- settings --------------------------------------------------------------------------------


def test_voice_and_checkboxes_persist_across_windows(make_window, tmp_path):
    path = str(tmp_path / "prefs.ini")
    first = make_window(settings=QSettings(path, QSettings.Format.IniFormat))
    first.voice_picker.select_voice(HEART)
    first.read_answer_check.setChecked(True)
    first.online_lookups_check.setChecked(False)
    first.close()

    second = make_window(settings=QSettings(path, QSettings.Format.IniFormat))

    assert second.voice_picker.voice_key() == HEART
    assert second.read_answer_check.isChecked()
    assert not second.online_lookups_check.isChecked()


def test_saved_voice_that_is_gone_falls_back_but_keeps_the_preference(make_window, settings):
    settings.setValue("voice", "piper:gone")

    window = make_window()

    assert window.voice_picker.voice_key() == LESSAC
    assert settings.value("voice") == "piper:gone"


# --- keyboard and accessibility --------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "keys"),
    [
        ("speak_action", ["Ctrl+Return", "Ctrl+Enter"]),
        ("repeat_action", ["Ctrl+R"]),
        ("stop_action", ["Ctrl+."]),
    ],
)
def test_shortcuts(window, action, keys):
    assert [s.toString() for s in getattr(window, action).shortcuts()] == keys


def test_cmd_return_in_the_text_box_speaks_without_adding_a_newline(qtbot, window, service):
    window.question_edit.setPlainText("q")
    window.question_edit.setFocus()

    with qtbot.waitSignal(window.reading_played, timeout=5000):
        qtbot.keyClick(window.question_edit, Qt.Key.Key_Return, CTRL)

    assert len(service.calls) == 1
    assert window.question_edit.toPlainText() == "q"


def test_cmd_r_repeats_and_cmd_period_stops(qtbot, window, player):
    speak(qtbot, window)

    qtbot.keyClick(window.question_edit, Qt.Key.Key_Period, CTRL)
    assert player.stop_calls == 1

    qtbot.keyClick(window.question_edit, Qt.Key.Key_R, CTRL)
    assert player.replay_calls == 1


def test_shortcuts_respect_the_disabled_state(qtbot, window, player):
    qtbot.keyClick(window.question_edit, Qt.Key.Key_R, CTRL)
    qtbot.keyClick(window.question_edit, Qt.Key.Key_Period, CTRL)

    assert (player.replay_calls, player.stop_calls) == (0, 0)


def test_tab_leaves_the_text_box_instead_of_typing_a_tab(window):
    assert window.question_edit.tabChangesFocus()


def test_focus_chain_follows_the_visual_order(window):
    expected = [  # design spec 5.8: the visual order, top to bottom
        window.question_edit,
        window.script_toggle,
        window.script_view,
        window.voice_picker.combo,
        window.voice_picker.speaker_spin,
        window.rotation_combo,
        window.read_answer_check,
        window.online_lookups_check,
        window.repeat_button,
        window.stop_button,
        window.speak_button,
    ]
    chain, widget = [], window.question_edit
    while True:
        if widget in expected:
            chain.append(widget)
        widget = widget.nextInFocusChain()
        if widget is window.question_edit:
            break

    assert chain == expected


def test_every_interactive_control_has_an_accessible_name(window):
    controls = [
        window.question_edit,
        window.voice_picker.combo,
        window.voice_picker.speaker_spin,
        window.rotation_combo,
        window.read_answer_check,
        window.online_lookups_check,
        window.repeat_button,
        window.stop_button,
        window.speak_button,
        window.script_toggle,
        window.script_view,
    ]
    for control in controls:
        label = control.accessibleName() or getattr(control, "text", lambda: "")()
        assert label, control


def test_no_style_sheet_overrides_the_native_look(window):
    widgets = [window, *window.findChildren(QWidget)]

    assert QApplication.instance().styleSheet() == ""
    assert [w for w in widgets if w.styleSheet()] == []


# --- app menu --------------------------------------------------------------------------------


def test_about_and_quit_use_the_standard_macos_app_menu_roles(window):
    assert window.about_action.text() == "About Cloudy Reader"
    assert window.about_action.menuRole() == QAction.MenuRole.AboutRole
    assert window.quit_action.text() == "Quit Cloudy Reader"
    assert window.quit_action.menuRole() == QAction.MenuRole.QuitRole
    assert window.quit_action.shortcut().toString() == "Ctrl+Q"  # Cmd+Q on macOS


def test_about_box_shows_the_name_and_version_without_blocking(window):
    window.about_action.trigger()

    box = window.findChild(AboutPanel)
    assert box.windowTitle() == "About Cloudy Reader"
    assert box.name_label.text() == "Cloudy Reader"
    assert box.version_label.text() == f"Version {importlib.metadata.version('cloudyreader')}"
    assert box.description_label.text() == "Reads National Science Bowl questions aloud."
    assert not box.isModal()
    box.close()


def test_about_box_says_dev_when_the_package_metadata_is_missing(window, monkeypatch):
    def missing(_name):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(names, "version", missing)

    window.about_action.trigger()

    box = window.findChild(AboutPanel)
    assert box.version_label.text() == "Version dev"
    box.close()


def test_about_box_carries_the_app_icon_when_there_is_one(qapp, window):
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.blue)
    qapp.setWindowIcon(QIcon(pixmap))
    try:
        window.about_action.trigger()

        box = window.findChild(AboutPanel)
        assert not box.icon_label.pixmap().isNull()
        box.close()
    finally:
        qapp.setWindowIcon(QIcon())


def test_cmd_q_closes_the_window_and_stops_playback(qtbot, window, player):
    speak(qtbot, window)

    qtbot.keyClick(window.question_edit, Qt.Key.Key_Q, CTRL)

    assert not window.isVisible()
    assert player.stop_calls == 1


# --- lifecycle -------------------------------------------------------------------------------


def test_closing_the_window_stops_playback(qtbot, window, player):
    speak(qtbot, window)

    window.close()

    assert player.stop_calls == 1


def test_a_result_arriving_after_close_is_not_played(qtbot, window, service, player):
    gate = service.gate = threading.Event()
    window.question_edit.setPlainText("q")
    window.speak_button.click()
    gate.set()  # the reading is ready; its signal reaches the window only after close()

    window.close()  # waits for the worker
    qtbot.wait(100)  # deliver the queued result

    assert player.played == []


def test_an_error_arriving_after_close_is_dropped(qtbot, window, service):
    gate = service.gate = threading.Event()
    service.error = RuntimeError("late")
    window.question_edit.setPlainText("q")
    window.speak_button.click()
    gate.set()

    with qtbot.assertNotEmitted(window.error_occurred):
        window.close()
        qtbot.wait(100)


def test_closing_survives_a_player_that_cannot_stop(qtbot, make_window):
    window = make_window(player=StubbornPlayer())
    speak(qtbot, window)

    window.close()  # pytest-qt fails the test if closeEvent lets the error escape


def test_closing_twice_stops_playback_only_once(qtbot, window, player):
    speak(qtbot, window)

    window.close()
    window.close()

    assert player.stop_calls == 1


def test_closing_with_nothing_playing_does_not_touch_the_player(window, player):
    window.close()

    assert player.stop_calls == 0


# --- quit: afplay is a child process, so it must be silenced before the app goes -------------


def test_quit_silences_playback_and_a_later_close_does_not_stop_again(qtbot, qapp, window, player):
    speak(qtbot, window)

    qapp.aboutToQuit.emit()
    assert player.stop_calls == 1
    assert not player.is_playing
    window.close()

    assert player.stop_calls == 1


def test_quit_after_close_does_not_stop_again(qtbot, qapp, window, player):
    speak(qtbot, window)
    window.close()

    qapp.aboutToQuit.emit()

    assert player.stop_calls == 1


def test_quit_is_safe_when_nothing_plays(qapp, window, player):
    qapp.aboutToQuit.emit()
    qapp.aboutToQuit.emit()

    assert player.stop_calls == 0


def test_quit_survives_a_player_that_cannot_stop(qtbot, qapp, make_window):
    player = StubbornPlayer()
    window = make_window(player=player)
    speak(qtbot, window)

    qapp.aboutToQuit.emit()  # pytest-qt fails the test if the slot lets the error escape

    assert player.stop_calls == 1  # it tried
    window.close()
    assert player.stop_calls == 2  # still playing, so the close path tries again


def test_window_grab_renders_a_screenshot(window, tmp_path):
    shot = tmp_path / "window.png"

    pixmap = window.grab()

    assert not pixmap.isNull()
    assert pixmap.width() >= tokens.WINDOW_MIN_SIZE[0]
    assert pixmap.save(str(shot))
    assert shot.stat().st_size > 0


# --- worker job (its run() executes on a Qt thread that coverage cannot trace) ----------------


def test_job_reports_the_result_by_signal():
    signals = _Signals()
    got = []
    signals.prepared.connect(got.append)
    service = FakeReaderService()

    def call():
        return service.prepare("raw", "piper:x", RenderOptions())

    _Job(call, signals.prepared, signals.failed).run()

    assert [r.script.text() for r in got] == ["raw"]
    assert service.calls[0].voice_key == "piper:x"


def test_job_reports_a_failure_by_signal_instead_of_raising():
    signals = _Signals()
    got = []
    signals.failed.connect(got.append)
    boom = RuntimeError("boom")

    def call():
        raise boom

    _Job(call, signals.prepared, signals.failed).run()

    assert got == [boom]
