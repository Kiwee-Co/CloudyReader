import pytest
from PySide6.QtCore import Qt

from cloudyreader.gui.fake_service import FAKE_VOICES
from cloudyreader.gui.voice_picker import VoicePicker

LESSAC = "piper:en_US-lessac-medium"
AMY = "piper:en_US-amy-medium"
LIBRITTS = "piper:en_US-libritts-high"
HEART = "kokoro:af_heart"
MICHAEL = "kokoro:am_michael"  # listed, not installed


@pytest.fixture
def picker(qtbot):
    widget = VoicePicker()
    qtbot.addWidget(widget)
    widget.set_voices(FAKE_VOICES)
    widget.show()
    return widget


def items(picker):
    model = picker.combo.model()
    return [model.item(row) for row in range(model.rowCount())]


def is_selectable(item) -> bool:
    return bool(item.flags() & Qt.ItemFlag.ItemIsSelectable) and item.isEnabled()


def test_voices_are_grouped_by_engine_under_header_rows(picker):
    assert [item.text() for item in items(picker)] == [
        "Piper",
        "Lessac (en-US, medium)",
        "Amy (en-US, medium)",
        "Alan (en-GB, medium)",
        "LibriTTS (en-US, high)",
        "Kokoro",
        "Heart (en-US, high)",
        "Michael (en-US, high, not installed)",
    ]


def test_group_headers_are_not_selectable(picker):
    rows = items(picker)

    assert not is_selectable(rows[0])
    assert not is_selectable(rows[5])
    assert is_selectable(rows[1])


def test_header_row_has_no_voice_key(picker):
    picker.combo.setCurrentIndex(0)

    assert picker.voice_key() is None


def test_uninstalled_voice_is_disabled(picker):
    assert not is_selectable(items(picker)[7])


def test_default_selection_is_the_first_installed_voice(picker):
    assert picker.voice_key() == LESSAC
    assert picker.combo.currentIndex() == 1


def test_preferred_voice_is_selected_when_installed(picker):
    picker.set_voices(FAKE_VOICES, preferred=HEART)

    assert picker.voice_key() == HEART


@pytest.mark.parametrize("preferred", [MICHAEL, "piper:gone", "", None])
def test_unusable_preferred_voice_falls_back_to_the_first_installed(picker, preferred):
    picker.set_voices(FAKE_VOICES, preferred=preferred)

    assert picker.voice_key() == LESSAC


def test_set_voices_replaces_the_previous_list(picker):
    picker.set_voices(FAKE_VOICES[:1])

    assert [item.text() for item in items(picker)] == ["Piper", "Lessac (en-US, medium)"]


def test_rebuilding_the_list_never_emits_voice_changed(qtbot, picker):
    with qtbot.assertNotEmitted(picker.voice_changed):
        picker.set_voices(FAKE_VOICES, preferred=HEART)


def test_select_voice_by_key(picker):
    assert picker.select_voice(AMY) is True
    assert picker.voice_key() == AMY


@pytest.mark.parametrize("key", [MICHAEL, "piper:gone"])
def test_select_voice_refuses_uninstalled_and_unknown_keys(picker, key):
    assert picker.select_voice(key) is False
    assert picker.voice_key() == LESSAC


def test_voice_changed_carries_the_new_key(qtbot, picker):
    with qtbot.waitSignal(picker.voice_changed) as blocker:
        picker.select_voice(AMY)

    assert blocker.args == [AMY]


def test_voice_changed_is_silent_for_header_rows(qtbot, picker):
    with qtbot.assertNotEmitted(picker.voice_changed):
        picker.combo.setCurrentIndex(0)


def test_speaker_spin_is_hidden_for_a_single_speaker_voice(picker):
    assert picker.speaker_box.isHidden()
    assert picker.speaker_id() is None


def test_speaker_spin_appears_for_a_multi_speaker_voice(picker):
    picker.select_voice(LIBRITTS)

    assert picker.speaker_box.isVisible()
    assert (picker.speaker_spin.minimum(), picker.speaker_spin.maximum()) == (0, 903)
    assert picker.speaker_id() == 0


def test_speaker_id_follows_the_spin(picker):
    picker.select_voice(LIBRITTS)
    picker.speaker_spin.setValue(7)

    assert picker.speaker_id() == 7


def test_speaker_spin_hides_again_for_a_single_speaker_voice(picker):
    picker.select_voice(LIBRITTS)
    picker.speaker_spin.setValue(7)
    picker.select_voice(AMY)

    assert picker.speaker_box.isHidden()
    assert picker.speaker_id() is None


@pytest.mark.parametrize("voices", [[], [FAKE_VOICES[-1]]])
def test_no_installed_voice_means_no_selection(picker, voices):
    picker.set_voices(voices)

    assert picker.voice_key() is None
    assert picker.speaker_id() is None
    assert not picker.combo.isEnabled()


def test_loading_state_shows_a_placeholder_and_disables_the_combo(picker):
    picker.select_voice(LIBRITTS)

    picker.set_loading()

    assert picker.voice_key() is None
    assert picker.speaker_id() is None
    assert picker.speaker_box.isHidden()
    assert picker.combo.count() == 0
    assert picker.combo.placeholderText() == "Loading voices\u2026"
    assert not picker.combo.isEnabled()


def test_the_empty_list_after_loading_says_no_voice_instead(picker):
    picker.set_loading()

    picker.set_voices([])

    assert picker.combo.placeholderText() == "No voice installed"


def test_loading_then_voices_enables_the_combo_and_selects_the_first(picker):
    picker.set_loading()

    picker.set_voices(FAKE_VOICES)

    assert picker.combo.isEnabled()
    assert picker.voice_key() == LESSAC


def test_unavailable_state_says_so_and_stays_disabled(picker):
    picker.set_unavailable()

    assert picker.voice_key() is None
    assert picker.combo.count() == 0
    assert picker.combo.placeholderText() == "Voices unavailable"
    assert not picker.combo.isEnabled()
