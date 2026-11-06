"""VoiceOver gets a name and a description for every control (WCAG 2.2, 4.1.2 Name, Role, Value).

A description is what assistive tech reads after the name: Qt falls back to the tooltip, so a
control with a tooltip already has one; the rest get the placeholder or a sentence of their own.
"""

import pytest
from PySide6.QtGui import QAccessible

CONTROLS = (
    "question_edit",
    "voice_picker.combo",
    "voice_picker.speaker_spin",
    "rotation_combo",
    "read_answer_check",
    "online_lookups_check",
    "paste_button",
    "speak_clipboard_button",
    "repeat_button",
    "stop_button",
    "speak_button",
    "script_toggle",
    "script_view",
    "busy_bar",
    "prefetch_bar",
)


def control(window, path: str):
    target = window
    for name in path.split("."):
        target = getattr(target, name)
    return target


def accessible_text(widget, kind: QAccessible.Text) -> str:
    interface = QAccessible.queryAccessibleInterface(widget)
    assert interface is not None, widget
    return interface.text(kind)


@pytest.mark.parametrize("path", CONTROLS)
def test_every_control_has_an_accessible_name(window, path):
    assert accessible_text(control(window, path), QAccessible.Text.Name)


@pytest.mark.parametrize("path", CONTROLS)
def test_every_control_has_an_accessible_description(window, path):
    assert accessible_text(control(window, path), QAccessible.Text.Description)
