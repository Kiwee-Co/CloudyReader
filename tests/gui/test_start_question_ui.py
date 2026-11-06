"""The start question in the window: only in an empty box, selected, read by Speak, never saved."""

from PySide6.QtCore import QSettings

SAMPLE = "TOSS-UP\n1) PHYSICS Short Answer What is the SI unit of force?\nANSWER: NEWTON"
# The keys the window saves today; the question text is none of them.
SAVED_KEYS = {"geometry", "read_answer", "online_lookups", "voice_rotation", "voice"}


def test_a_window_shows_no_start_question_by_default(window):
    # tests/fixtures is right here: only the app's entry point asks for a start question.
    assert window.question_edit.toPlainText() == ""


def test_the_start_question_fills_the_empty_box_selected(window):
    assert window.show_start_question(SAMPLE) is True

    edit = window.question_edit
    assert edit.toPlainText() == SAMPLE
    # Selected, so typing or pasting replaces it. Qt separates paragraphs with U+2029 here.
    assert edit.textCursor().selectedText().replace("\u2029", "\n") == SAMPLE
    assert not edit.document().isUndoAvailable()  # the box's first state: Undo never empties it


def test_typing_replaces_the_start_question(qtbot, window):
    window.show_start_question(SAMPLE)

    qtbot.keyClicks(window.question_edit, "Q")

    assert window.question_edit.toPlainText() == "Q"


def test_speak_reads_the_start_question(qtbot, window, service):
    window.show_start_question(SAMPLE)

    with qtbot.waitSignal(window.reading_played, timeout=5000):
        window.speak_button.click()

    assert service.calls[-1].raw == SAMPLE


def test_the_start_question_never_replaces_text_in_the_box(window):
    window.question_edit.setPlainText("typed")

    assert window.show_start_question(SAMPLE) is False
    assert window.question_edit.toPlainText() == "typed"


def test_a_blank_start_question_is_no_start_question(window):
    assert window.show_start_question(" \n") is False
    assert window.question_edit.toPlainText() == ""


def test_the_start_question_is_never_saved(make_window, tmp_path):
    path = tmp_path / "prefs.ini"
    window = make_window(settings=QSettings(str(path), QSettings.Format.IniFormat))
    window.show_start_question(SAMPLE)

    window.close()  # closing saves the geometry

    saved = QSettings(str(path), QSettings.Format.IniFormat)
    assert set(saved.allKeys()) <= SAVED_KEYS
    assert "SI unit of force" not in path.read_text(encoding="utf-8")
    assert make_window(settings=saved).question_edit.toPlainText() == ""
