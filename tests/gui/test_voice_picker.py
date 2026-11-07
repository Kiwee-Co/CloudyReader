import ast
import inspect

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QFormLayout, QWidget

from cloudyreader.gui import theme, tokens, voice_picker
from cloudyreader.gui.fake_service import ENGINE_FAKE_VOICES, FAKE_VOICES, MACOS_FAKE_VOICES
from cloudyreader.gui.voice_picker import VoicePicker
from cloudyreader.voice_meta import spoken_label, unique_labels

LESSAC = "piper:en_US-lessac-medium"
AMY = "piper:en_US-amy-medium"
LIBRITTS = "piper:en_US-libritts-high"
HEART = "kokoro:af_heart"
MICHAEL = "kokoro:am_michael"  # listed, not installed


@pytest.fixture
def picker(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    widget = VoicePicker(host)
    widget.add_rows(QFormLayout(host))
    widget.set_voices(FAKE_VOICES)
    host.show()
    yield widget  # the host lives as long as the fixture: qtbot keeps only a weak reference


def items(picker):
    model = picker.combo.model()
    return [model.item(row) for row in range(model.rowCount())]


def is_selectable(item) -> bool:
    return bool(item.flags() & Qt.ItemFlag.ItemIsSelectable) and item.isEnabled()


def test_voices_are_grouped_by_engine_under_header_rows(picker):
    assert [item.text() for item in items(picker)] == [
        "Piper",
        "Lessac (US, female) · Piper · medium",
        "Amy (US, female) · Piper · medium",
        "Alan (UK, male) · Piper · medium",
        "LibriTTS (US) · Piper · high",
        "Kokoro",
        "Heart (US, female) · Kokoro · bf16",
        "Michael (US, male) · Kokoro · bf16 — not downloaded yet",
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

    assert [item.text() for item in items(picker)] == [
        "Piper",
        "Lessac (US, female) · Piper · medium",
    ]


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
    assert picker.speaker_spin.isHidden()
    assert picker.speaker_id() is None


def test_speaker_spin_appears_for_a_multi_speaker_voice(picker):
    picker.select_voice(LIBRITTS)

    assert picker.speaker_spin.isVisible()
    assert picker.speaker_label.isVisible()  # its own form row, under the popup
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

    assert picker.speaker_spin.isHidden()
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
    assert picker.speaker_spin.isHidden()
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


# --- the label, its spoken form, the tooltips and the ink -------------------------------------

APPEARANCES = [
    theme.Appearance(dark=dark, high_contrast=high)
    for dark in (False, True)
    for high in (False, True)
]


def row(picker, key: str):
    return next(item for item in items(picker) if item.data(Qt.ItemDataRole.UserRole) == key)


def headers(picker) -> list:
    return [item for item in items(picker) if item.data(Qt.ItemDataRole.UserRole) is None]


def dimmed_rows(picker) -> list:
    voices = [item for item in items(picker) if item.data(Qt.ItemDataRole.UserRole) is not None]
    return [item for item in voices if not item.isEnabled()]


def test_a_row_shows_the_label_and_voiceover_hears_the_spoken_form(picker):
    labels = unique_labels(FAKE_VOICES)

    for voice in FAKE_VOICES:
        item = row(picker, voice.key)
        assert item.text() == labels[voice.key]
        assert item.data(Qt.ItemDataRole.AccessibleTextRole) == spoken_label(voice)
    assert row(picker, LESSAC).data(Qt.ItemDataRole.AccessibleTextRole) == (
        "Lessac, American English, female. Piper, medium."
    )


def test_a_header_reads_the_engine_title_and_no_grade_letter_shows_anywhere(picker):
    assert [h.text() for h in headers(picker)] == ["Piper", "Kokoro"]
    for item in items(picker):
        assert " A " not in f" {item.text()} " and "C+" not in item.text()  # Heart is A, Michael C+


def test_only_a_kokoro_grade_or_a_dimmed_reason_gets_a_tooltip(picker):
    assert row(picker, HEART).toolTip() == "Published grade A"
    assert row(picker, LESSAC).toolTip() == ""
    assert row(picker, MICHAEL).toolTip() == ""  # dimmed with no reason: the row says it all
    picker.set_voices(ENGINE_FAKE_VOICES)
    assert row(picker, "chatterbox_turbo:builtin").toolTip() == "not downloaded yet"
    assert row(picker, "qwen3_tts:ryan").toolTip() == ""


def test_the_closed_pop_up_tooltip_speaks_the_selected_voice(picker):
    assert picker.combo.toolTip() == "Lessac, American English, female. Piper, medium."

    picker.select_voice(HEART)
    assert picker.combo.toolTip() == "Heart, American English, female. Kokoro, bf16."

    picker.set_voices(FAKE_VOICES, preferred=AMY)  # a rebuild emits nothing, the tip still follows
    assert picker.combo.toolTip().startswith("Amy, American English")

    picker.set_voices([])
    assert picker.combo.toolTip() == ""


@pytest.mark.parametrize(
    "look", APPEARANCES, ids=lambda look: f"dark={look.dark},hc={look.high_contrast}"
)
def test_roles_ink_the_headers_the_dimmed_rows_and_the_disabled_placeholder(picker, look):
    roles = theme.roles(look)
    picker.set_roles(roles)

    for rebuild in (False, True):  # a rebuild keeps the ink
        if rebuild:
            picker.set_voices(FAKE_VOICES)
        for item in (*headers(picker), *dimmed_rows(picker)):
            assert item.foreground().color() == QColor(roles.secondary_text)
        for item in items(picker):
            if item.isEnabled() and item.data(Qt.ItemDataRole.UserRole) is not None:
                assert item.data(Qt.ItemDataRole.ForegroundRole) is None  # the menu's own ink
    disabled = QPalette.ColorGroup.Disabled
    for role in (QPalette.ColorRole.ButtonText, QPalette.ColorRole.Text):
        assert picker.combo.palette().color(disabled, role) == QColor(roles.field_placeholder)


def test_set_dark_stays_a_shorthand_for_the_standard_contrast_roles(picker):
    picker.set_dark(True)

    roles = theme.roles(theme.Appearance(dark=True))
    assert headers(picker)[0].foreground().color() == QColor(roles.secondary_text)


def test_the_speaker_row_names_its_range(picker):
    picker.select_voice(LIBRITTS)

    assert picker.speaker_spin.toolTip() == "Speakers are numbered 0 to 903."
    assert (
        picker.speaker_spin.accessibleDescription() == "Choose a speaker of this voice. 0 to 903."
    )


def test_the_closed_pop_up_is_as_wide_as_the_longest_label_needs(picker):
    assert tokens.VOICE_COMBO_MIN_CHARS == 32
    assert picker.combo.minimumContentsLength() == tokens.VOICE_COMBO_MIN_CHARS
    assert picker.combo.sizeAdjustPolicy() == (
        picker.combo.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )


@pytest.mark.parametrize(
    ("setup", "words"),
    [
        (lambda p: p.set_loading(), "Loading voices…"),
        (lambda p: p.set_unavailable(), "Voices unavailable"),
        (lambda p: p.set_voices([]), "No voice installed"),
    ],
    ids=["loading", "unavailable", "none"],
)
def test_the_three_empty_states_keep_their_exact_words(picker, setup, words):
    setup(picker)

    assert picker.combo.placeholderText() == words
    assert not picker.combo.isEnabled()


def test_typing_a_name_jumps_to_that_voice_and_never_to_a_header_or_a_dimmed_row(qtbot, picker):
    picker.set_voices([*ENGINE_FAKE_VOICES, *MACOS_FAKE_VOICES])
    picker.select_voice(LESSAC)

    qtbot.keyClicks(picker.combo, "Sam")
    assert picker.voice_key() == "macos:samantha"

    picker.select_voice(LESSAC)
    for typed in ("Mich", "Chatter", "Kok"):  # a dimmed row, a dimmed row, a header
        qtbot.keyClicks(picker.combo, typed)
        assert picker.voice_key() == LESSAC, typed


def test_macos_voices_list_under_their_own_header_after_the_others(picker):
    picker.set_voices([*ENGINE_FAKE_VOICES, *MACOS_FAKE_VOICES])

    assert [h.text() for h in headers(picker)][-2:] == ["Qwen3-TTS", "macOS"]
    assert row(picker, "macos:samantha").text() == "Samantha (US) · macOS · Enhanced"
    assert headers(picker)[-1].data(Qt.ItemDataRole.AccessibleTextRole) == "macOS voices"


def test_the_header_delegate_knows_its_combo_before_qt_can_ask_it_anything():
    # Qt may call sizeHint() while the delegate is still being built; a stale wrapper that never
    # ran __init__ then fails with "no attribute _combo" (seen after a failing test).
    source = inspect.getsource(voice_picker._SectionHeader.__init__)
    body = ast.parse(source.strip()).body[0].body

    first = body[0]
    assert isinstance(first, ast.Assign) and ast.unparse(first.targets[0]) == "self._combo"
