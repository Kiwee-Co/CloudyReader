"""Look and feel of the main window: menus, form layout, states, colors, and window behavior."""

import threading

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QPalette
from PySide6.QtWidgets import QApplication, QFormLayout, QLabel, QLineEdit, QMessageBox

from cloudyreader.gui import tokens
from cloudyreader.gui.fake_service import FakeReaderService
from cloudyreader.gui.widgets import Tone

LIBRITTS = "piper:en_US-libritts-high"
CTRL = Qt.KeyboardModifier.ControlModifier
NATIVE = QKeySequence.SequenceFormat.NativeText
EDIT_NAMES = ("undo", "redo", "cut", "copy", "paste", "select_all")


def speak(qtbot, window, text="What is H2O?"):
    window.question_edit.setPlainText(text)
    with qtbot.waitSignal(window.reading_played, timeout=5000):
        window.speak_button.click()


def edit_states(window) -> dict[str, bool]:
    window.edit_menu.aboutToShow.emit()  # macOS asks right before it opens the menu
    return {name: getattr(window, f"{name}_action").isEnabled() for name in EDIT_NAMES}


def placeholder(widget) -> str:
    return widget.palette().color(QPalette.ColorRole.PlaceholderText).name()


# --- menu bar --------------------------------------------------------------------------------


def test_menu_bar_has_the_standard_macos_menus_in_order(window):
    titles = [action.text() for action in window.menuBar().actions()]

    assert titles == ["File", "Edit", "Reading", "Window", "Help"]


@pytest.mark.parametrize(
    ("action", "key"),
    [
        ("undo_action", QKeySequence.StandardKey.Undo),
        ("redo_action", QKeySequence.StandardKey.Redo),
        ("cut_action", QKeySequence.StandardKey.Cut),
        ("copy_action", QKeySequence.StandardKey.Copy),
        ("paste_action", QKeySequence.StandardKey.Paste),
        ("select_all_action", QKeySequence.StandardKey.SelectAll),
    ],
)
def test_edit_menu_uses_the_platform_standard_shortcuts(window, action, key):
    assert getattr(window, action).shortcuts() == QKeySequence.keyBindings(key)


@pytest.mark.parametrize(
    ("action", "text", "key"),
    [
        ("close_action", "Close Window", "Ctrl+W"),
        ("minimize_action", "Minimize", "Ctrl+M"),
        ("zoom_action", "Zoom", ""),
    ],
)
def test_file_and_window_menu_commands(window, action, text, key):
    assert getattr(window, action).text() == text
    assert getattr(window, action).shortcut().toString() == key


def test_cmd_w_closes_the_window_and_stops_playback(qtbot, window, player):
    speak(qtbot, window)

    qtbot.keyClick(window.question_edit, Qt.Key.Key_W, CTRL)

    assert not window.isVisible()
    assert player.stop_calls == 1


def test_minimize_and_zoom_change_the_window_state(window):
    window.zoom_action.trigger()
    assert window.isMaximized()
    window.zoom_action.trigger()
    assert not window.isMaximized()

    window.minimize_action.trigger()
    assert window.isMinimized()


def test_select_all_and_copy_act_on_the_focused_text_box(window, monkeypatch):
    window.question_edit.setPlainText("hello world")
    window.question_edit.setFocus()
    monkeypatch.setattr(window.question_edit, "canPaste", lambda: True)  # no real pasteboard

    window.select_all_action.trigger()

    assert window.question_edit.textCursor().selectedText() == "hello world"
    assert edit_states(window) == {
        "undo": False,  # setPlainText() resets the undo history
        "redo": False,
        "cut": True,
        "copy": True,
        "paste": True,
        "select_all": True,
    }


def test_undo_and_redo_act_on_the_focused_text_box(qtbot, window):
    window.question_edit.setFocus()
    qtbot.keyClicks(window.question_edit, "abc")

    window.undo_action.trigger()
    assert window.question_edit.toPlainText() == ""
    assert edit_states(window)["redo"]

    window.redo_action.trigger()
    assert window.question_edit.toPlainText() == "abc"


def test_cut_and_copy_need_a_selection(window):
    window.question_edit.setPlainText("text")
    window.question_edit.setFocus()

    states = edit_states(window)

    assert not states["cut"]
    assert not states["copy"]
    assert states["select_all"]


def test_the_read_only_script_allows_copy_but_not_editing(qtbot, window):
    speak(qtbot, window, "alpha beta")
    window.script_toggle.click()
    window.script_view.setFocus()

    window.select_all_action.trigger()
    states = edit_states(window)

    assert window.script_view.textCursor().selectedText() == "alpha beta"
    assert states == {
        "undo": False,
        "redo": False,
        "cut": False,
        "copy": True,
        "paste": False,
        "select_all": True,
    }


def test_edit_commands_reach_the_speaker_field(window):
    window.voice_picker.select_voice(LIBRITTS)
    window.voice_picker.speaker_spin.setFocus()

    window.select_all_action.trigger()

    editor = window.voice_picker.speaker_spin.findChild(QLineEdit)
    assert editor.selectedText() == "0"
    assert edit_states(window)["copy"]


def test_edit_commands_are_disabled_without_a_text_field(window):
    window.speak_button.setFocus()

    assert edit_states(window) == dict.fromkeys(EDIT_NAMES, False)
    window.select_all_action.trigger()  # a stale shortcut must be harmless


# --- layout ----------------------------------------------------------------------------------


def form_of(window) -> QFormLayout:
    form = window.centralWidget().findChild(QFormLayout)
    assert form is not None
    return form


def test_voice_and_options_share_one_right_aligned_label_column(window):
    form = form_of(window)
    label_role = QFormLayout.ItemRole.LabelRole
    field_role = QFormLayout.ItemRole.FieldRole
    picker = window.voice_picker

    assert form.labelAlignment() & Qt.AlignmentFlag.AlignRight
    assert form.itemAt(0, label_role).widget() is picker.label
    assert form.itemAt(0, field_role).widget() is picker.combo  # the popup itself: no container
    assert form.itemAt(1, label_role).widget() is picker.speaker_label
    assert form.itemAt(1, field_role).widget() is picker.speaker_spin
    assert form.itemAt(2, label_role).widget().text() == "Rotation:"
    assert form.itemAt(2, label_role).widget().buddy() is window.rotation_combo
    assert form.itemAt(2, field_role).widget() is window.rotation_combo
    assert form.itemAt(3, label_role).widget().text() == "Options:"
    assert form.itemAt(3, field_role).widget() is window.read_answer_check
    assert form.itemAt(4, label_role) is None
    assert form.itemAt(4, field_role).widget() is window.online_lookups_check


def test_options_label_does_not_rename_a_checkbox_for_assistive_tech(window):
    label = form_of(window).itemAt(3, QFormLayout.ItemRole.LabelRole).widget()

    assert label.buddy() is None


def test_voice_label_names_the_combo_for_assistive_tech(window):
    assert window.voice_picker.label.text() == "Voice:"
    assert window.voice_picker.label.buddy() is window.voice_picker.combo


def test_popup_keeps_its_natural_width_like_a_native_form(window):
    form = form_of(window)

    assert form.fieldGrowthPolicy() == QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint


def test_the_script_text_sits_card_padding_from_the_panel_edge(window):
    inset = window.script_panel.layout().contentsMargins().left()

    assert inset + window.script_view.document().documentMargin() == tokens.CARD_PADDING


def test_spoken_script_is_secondary_text(window):
    body = QApplication.font().pointSizeF()
    ratio = tokens.TEXT_CALLOUT_PT / tokens.TEXT_BODY_PT

    assert window.script_view.font().pointSizeF() == pytest.approx(body * ratio)


# --- empty, busy and error states ------------------------------------------------------------


def test_empty_question_box_says_what_to_do_and_how(window):
    hint = window.question_edit.placeholderText()

    assert "question" in hint
    assert window.speak_action.shortcuts()[0].toString(NATIVE) in hint


def test_empty_script_view_explains_itself(window):
    assert window.script_view.placeholderText()


def test_error_status_has_the_error_tone(qtbot, window, service):
    service.error = RuntimeError("voice file missing")
    window.question_edit.setPlainText("q")

    with qtbot.waitSignal(window.error_occurred, timeout=5000):
        window.speak_button.click()

    assert window.statusBar().tone is Tone.ERROR


def test_warnings_have_the_warning_tone(qtbot, window, service):
    service.warnings = ("no pronunciation for 'xyz'",)

    speak(qtbot, window)

    assert window.statusBar().tone is Tone.WARNING


def test_plain_status_messages_are_informational(qtbot, window):
    speak(qtbot, window)

    assert window.statusBar().tone is Tone.INFO


def test_a_missing_voice_is_a_warning(make_window):
    window = make_window(service=FakeReaderService(voices=[]))

    assert window.statusBar().tone is Tone.WARNING


def test_a_failed_voice_list_is_an_error(make_window):
    window = make_window(service=FakeReaderService(voices_error=RuntimeError("unreadable")))

    assert window.statusBar().tone is Tone.ERROR


def test_busy_state_keeps_the_window_margin(qtbot, window, service):
    gate = service.gate = threading.Event()
    window.question_edit.setPlainText("q")
    window.speak_button.click()
    qtbot.waitUntil(window.busy_bar.isVisible, timeout=2000)
    bar = window.statusBar()

    assert bar.width() - window.busy_bar.geometry().right() - 1 == tokens.MARGIN
    with qtbot.waitSignal(window.reading_played, timeout=5000):
        gate.set()


# --- colors ----------------------------------------------------------------------------------


def test_placeholders_use_the_aa_token_for_the_light_appearance(window):
    assert placeholder(window.question_edit) == QColor(tokens.PLACEHOLDER_LIGHT).name()
    # On the script panel's fill the placeholder tokens miss 4.5:1; the secondary token meets it.
    assert placeholder(window.script_view) == QColor(tokens.TEXT_SECONDARY_LIGHT).name()


def test_placeholders_follow_a_switch_to_dark_and_back(window):
    hints = QGuiApplication.styleHints()

    hints.colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert placeholder(window.question_edit) == QColor(tokens.PLACEHOLDER_DARK).name()
    assert placeholder(window.script_view) == QColor(tokens.TEXT_SECONDARY_DARK).name()

    hints.colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert placeholder(window.question_edit) == QColor(tokens.PLACEHOLDER_LIGHT).name()


def test_an_unknown_scheme_picks_the_token_from_the_text_background(qapp, window):
    original = qapp.palette()
    dark = QPalette(original)
    dark.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
    try:
        qapp.setPalette(dark)
        qapp.processEvents()  # Qt 6 posts the palette change to the widgets
        QGuiApplication.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Unknown)

        assert placeholder(window.question_edit) == QColor(tokens.PLACEHOLDER_DARK).name()
    finally:
        qapp.setPalette(original)
        qapp.processEvents()


def test_the_placeholder_override_leaves_every_other_color_to_the_system(qapp, window):
    original = qapp.palette()
    tinted = QPalette(original)
    tinted.setColor(QPalette.ColorRole.Base, QColor("#fffbe6"))
    try:
        qapp.setPalette(tinted)
        qapp.processEvents()

        assert window.question_edit.palette().color(QPalette.ColorRole.Base).name() == "#fffbe6"
        assert placeholder(window.question_edit) == QColor(tokens.PLACEHOLDER_LIGHT).name()
    finally:
        qapp.setPalette(original)
        qapp.processEvents()


# --- discoverability and accessibility -------------------------------------------------------


@pytest.mark.parametrize(
    ("button", "action"),
    [
        ("speak_button", "speak_action"),
        ("speak_clipboard_button", "speak_clipboard_action"),
        ("repeat_button", "repeat_action"),
        ("stop_button", "stop_action"),
    ],
)
def test_button_tooltips_teach_the_shortcut(window, button, action):
    shortcut = getattr(window, action).shortcuts()[0].toString(NATIVE)

    assert shortcut in getattr(window, button).toolTip()


@pytest.mark.parametrize(
    "control", ["paste_button", "read_answer_check", "online_lookups_check", "script_toggle"]
)
def test_controls_without_a_shortcut_still_explain_themselves(window, control):
    widget = getattr(window, control)

    assert widget.toolTip() or widget.accessibleDescription()


def test_online_lookups_says_where_names_go(window):
    assert "PubChem" in window.online_lookups_check.toolTip()


def test_online_lookups_promises_nothing_about_the_sound(window):
    # Only the local OPSIN check changes how a name is said; PubChem and UniProt answers are
    # fetched and cached, and the script builder ignores them.
    tip = window.online_lookups_check.toolTip()

    assert tip == "Look up chemical and protein names on PubChem and UniProt."
    assert "say them right" not in tip


# --- window behavior -------------------------------------------------------------------------


def test_window_size_is_restored_on_the_next_launch(make_window, tmp_path):
    path = str(tmp_path / "prefs.ini")
    first = make_window(settings=QSettings(path, QSettings.Format.IniFormat))
    first.resize(600, 500)
    first.close()

    second = make_window(settings=QSettings(path, QSettings.Format.IniFormat))

    assert (second.width(), second.height()) == (600, 500)


def test_a_broken_saved_geometry_keeps_the_default_size(make_window, settings):
    settings.setValue("geometry", b"not a geometry")

    window = make_window()

    assert (window.width(), window.height()) == tokens.WINDOW_DEFAULT_SIZE


@pytest.mark.parametrize("native", [False, True], ids=["default", "macOS"])
def test_the_about_description_stays_on_one_line(request, qtbot, make_window, native):
    if native:
        request.getfixturevalue("mac_style")
    window = make_window()
    window.about_action.trigger()
    box = window.findChild(QMessageBox)
    qtbot.waitUntil(box.isVisible)
    description = "Reads National Science Bowl questions aloud."
    label = next(w for w in box.findChildren(QLabel) if description in w.text())

    assert label.minimumWidth() == tokens.ABOUT_TEXT_MIN_WIDTH
    assert label.width() >= label.fontMetrics().horizontalAdvance(description)
    box.close()


def test_about_box_is_a_single_panel_like_the_system_one(window):
    window.about_action.trigger()
    window.about_action.trigger()

    boxes = window.findChildren(QMessageBox)
    assert len(boxes) == 1
    boxes[0].close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    window.about_action.trigger()

    assert len(window.findChildren(QMessageBox)) == 1
    window.findChild(QMessageBox).close()
