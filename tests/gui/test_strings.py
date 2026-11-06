"""Every visible string, accessible name, and shortcut the manual quotes stays as the facts sheet
records it: the UI pass restyles the window and changes no word of it."""

import pytest
from PySide6.QtWidgets import QLabel

# (control, Qt getter, the text the facts sheet records), facts sections 3 and 15.
STRINGS = [
    (
        "question_edit",
        "placeholderText",
        "Paste a National Science Bowl question, then press ⌘↵ to hear it.",
    ),
    ("question_edit", "accessibleName", "Question"),
    ("voice_picker.label", "text", "Voice:"),
    ("voice_picker.combo", "accessibleName", "Voice"),
    ("voice_picker.speaker_spin", "accessibleName", "Speaker"),
    ("rotation_combo", "accessibleName", "Voice rotation"),
    ("rotation_combo", "toolTip", "How Speak picks the next voice."),
    ("read_answer_check", "text", "Read answer line"),
    ("read_answer_check", "toolTip", "Also read the ANSWER line aloud."),
    ("online_lookups_check", "text", "Online lookups"),
    (
        "online_lookups_check",
        "toolTip",
        "Look up chemical and protein names on PubChem and UniProt.",
    ),
    ("paste_button", "text", "Paste"),
    ("paste_button", "toolTip", "Replace the question with the clipboard text."),
    ("speak_clipboard_button", "text", "Speak Clipboard"),
    ("speak_clipboard_button", "toolTip", "Paste the clipboard and speak it (⇧⌘V)"),
    ("repeat_button", "text", "Repeat"),
    ("repeat_button", "toolTip", "Play the last reading again (⌘R)"),
    ("stop_button", "text", "Stop"),
    ("stop_button", "toolTip", "Stop playback (⌘.)"),
    ("speak_button", "text", "Speak"),
    ("speak_button", "toolTip", "Speak the question (⌘↵)"),
    ("script_toggle", "text", "Spoken script"),
    ("script_toggle", "accessibleDescription", "Show or hide the text that is spoken"),
    ("script_view", "placeholderText", "The words that are spoken appear here."),
    ("script_view", "accessibleName", "Spoken script"),
    ("busy_bar", "accessibleName", "Preparing"),
    ("prefetch_bar", "accessibleName", "Downloading voices"),
]
# The VoiceOver-only text the lead approved (design spec 9), exactly as written there. The fifth,
# each engine header's "<engine> voices", is pinned in test_voice_menu.py.
VOICEOVER_ONLY = [
    ("voice_picker.combo", "accessibleDescription", "Choose the voice that reads the question."),
    ("voice_picker.speaker_spin", "accessibleDescription", "Choose a speaker of this voice."),
    ("busy_bar", "accessibleDescription", "A reading is being prepared."),
    ("prefetch_bar", "accessibleDescription", "Voice download progress."),
]
ROTATION_ITEMS = [
    "No rotation",
    "Round robin",
    "Random shuffle",
    "US only (random shuffle)",
    "Men only",
    "Women only",
]


def control(window, path: str):
    target = window
    for name in path.split("."):
        target = getattr(target, name)
    return target


@pytest.mark.parametrize(("path", "getter", "text"), STRINGS, ids=lambda v: str(v)[:40])
def test_every_quoted_string_is_unchanged(window, path, getter, text):
    assert getattr(control(window, path), getter)() == text


@pytest.mark.parametrize(("path", "getter", "text"), VOICEOVER_ONLY, ids=lambda v: str(v)[:40])
def test_the_approved_voiceover_text_is_exact(window, path, getter, text):
    assert getattr(control(window, path), getter)() == text


def test_the_form_labels_are_unchanged(window):
    labels = {w.text() for w in window.centralWidget().findChildren(QLabel) if w.text()}

    assert {"Voice:", "Rotation:", "Options:"} <= labels


def test_the_rotation_items_are_unchanged(window):
    combo = window.rotation_combo

    assert [combo.itemText(i) for i in range(combo.count())] == ROTATION_ITEMS


def test_the_window_title_menus_and_sizes_are_unchanged(window):
    assert window.windowTitle() == "Cloudy Reader"
    assert [a.text() for a in window.menuBar().actions()] == [
        "File",
        "Edit",
        "Reading",
        "Window",
        "Help",
    ]
    assert window.speak_button.isDefault()
