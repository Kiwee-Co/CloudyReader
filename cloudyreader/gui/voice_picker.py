"""Voice chooser: a combo box grouped by engine, plus a speaker spin for multi-speaker voices."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPalette,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QComboBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from cloudyreader.gui import theme, tokens
from cloudyreader.gui.widgets import text_style
from cloudyreader.models import VoiceInfo
from cloudyreader.voice_meta import engine_title, spoken_label, unique_labels

_KEY_ROLE = Qt.ItemDataRole.UserRole
_NO_VOICE = "No voice installed"
LOADING = "Loading voices…"
_UNAVAILABLE = "Voices unavailable"
_Index = QModelIndex | QPersistentModelIndex


def _tooltip(voice: VoiceInfo) -> str:
    """What the row's text does not say: a dimmed row's whole reason, a Kokoro grade's source."""
    if not voice.installed:
        return voice.reason
    return f"Published grade {voice.quality}" if voice.engine == "kokoro" and voice.quality else ""


def _gap(index: _Index) -> int:
    """The space above a header row: a section gap, except above the first row of the menu."""
    return tokens.SECTION_HEADER_GAP if index.row() > 0 else 0


class _SectionHeader(QStyledItemDelegate):
    """The delegate of each engine header row; voice rows keep the menu's own delegate.

    The menu's delegate draws the header too, below the section gap: the row carries its own
    font and color, which that delegate honors, so the header text starts where voice names do.
    """

    def __init__(self, combo: QComboBox) -> None:
        self._combo = combo  # first: Qt may ask sizeHint() while the base is still being built
        super().__init__(combo)

    def _menu(self) -> QAbstractItemDelegate:
        # Asked for at every call and never kept: a kept wrapper of an object Qt made can go
        # stale when Qt reuses its address.
        return self._combo.view().itemDelegate()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: _Index) -> None:
        below = QStyleOptionViewItem(option)
        below.rect = option.rect.adjusted(0, _gap(index), 0, 0)
        self._menu().paint(painter, below, index)

    def sizeHint(self, option: QStyleOptionViewItem, index: _Index) -> QSize:
        size = self._menu().sizeHint(option, index)
        return QSize(size.width(), size.height() + _gap(index))


class VoicePicker(QObject):
    """Emits voice_changed(key) when the user lands on a voice. A rebuild never emits.

    add_rows() puts the Voice row and the Speaker row into a form. The popup is a field of the
    form itself: in a container or a box layout, macOS would move its visible edge off the
    form's field edge. The Speaker row shows only for a voice with more than one speaker.
    """

    voice_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._voices: dict[str, VoiceInfo] = {}
        self._rows: dict[str, int] = {}  # installed voices only
        self._header_rows: list[int] = []
        self._dim_rows: list[int] = []  # listed, but not installed: they cannot be chosen
        self._header_font = text_style(tokens.TEXT_SECTION_PT)
        self._header_font.setWeight(QFont.Weight.DemiBold)
        self._ink = QBrush()  # headers and dimmed rows, set by set_roles()

        self.combo = QComboBox()
        self._model = QStandardItemModel(self.combo)
        self.combo.setModel(self._model)
        self.combo.setAccessibleName("Voice")
        self.combo.setAccessibleDescription("Choose the voice that reads the question.")
        self.combo.setPlaceholderText(_NO_VOICE)
        self.combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.combo.setMinimumContentsLength(tokens.VOICE_COMBO_MIN_CHARS)
        self._section_header = _SectionHeader(self.combo)
        self.speaker_spin = QSpinBox()
        self.speaker_spin.setAccessibleName("Speaker")
        self.speaker_spin.setAccessibleDescription("Choose a speaker of this voice.")

        self.label = QLabel("Voice:")
        self.label.setBuddy(self.combo)
        self.speaker_label = QLabel("Speaker:")
        self.speaker_label.setBuddy(self.speaker_spin)
        for widget in (self.speaker_label, self.speaker_spin):
            widget.hide()

        self.combo.currentIndexChanged.connect(self._on_index_changed)
        self.set_roles(theme.roles(theme.Appearance()))

    def add_rows(self, form: QFormLayout) -> None:
        form.addRow(self.label, self.combo)
        form.addRow(self.speaker_label, self.speaker_spin)  # hidden, it takes no room

    def set_roles(self, roles: theme.Roles) -> None:
        """Ink the engine headers and the dimmed rows, and the placeholder of a disabled pop-up."""
        self._ink = QBrush(QColor(roles.secondary_text))
        for row in (*self._header_rows, *self._dim_rows):
            self._model.item(row).setForeground(self._ink)
        # An empty list's placeholder ("Loading voices…") is a state, not a dimmed control: the
        # bezel stays dimmed, the words read at 4.5:1. A fresh palette sets nothing else.
        palette = QPalette()
        for role in (QPalette.ColorRole.ButtonText, QPalette.ColorRole.Text):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(roles.field_placeholder))
        self.combo.setPalette(palette)

    def set_dark(self, dark: bool) -> None:
        """The standard-contrast roles of one appearance; the window passes full roles instead."""
        self.set_roles(theme.roles(theme.Appearance(dark=dark)))

    def _header(self, engine: str) -> QStandardItem:
        """A section header: no choice, so the keyboard skips it; the menu draws it in its own
        font and color, and VoiceOver hears "<engine> voices"."""
        title = engine_title(engine)
        header = QStandardItem(title)
        header.setFlags(Qt.ItemFlag.NoItemFlags)
        header.setFont(self._header_font)
        header.setForeground(self._ink)
        header.setData(f"{title} voices", Qt.ItemDataRole.AccessibleTextRole)
        return header

    def set_voices(self, voices: Sequence[VoiceInfo], preferred: str | None = None) -> None:
        """Rebuild grouped by engine; select `preferred`, else the first installed voice."""
        self._voices = {voice.key: voice for voice in voices}
        self.combo.setPlaceholderText(_NO_VOICE)
        groups: dict[str, list[VoiceInfo]] = {}
        for voice in voices:
            groups.setdefault(voice.engine, []).append(voice)
        labels = unique_labels(voices)

        view = self.combo.view()
        for row in self._header_rows:  # the last list's headers sat in other rows
            view.setItemDelegateForRow(row, None)
        self.combo.blockSignals(True)
        self._model.clear()
        self._rows.clear()
        self._header_rows = []
        self._dim_rows = []
        for engine, members in groups.items():
            self._header_rows.append(self._model.rowCount())
            self._model.appendRow(self._header(engine))
            for voice in members:
                item = QStandardItem(labels[voice.key])
                item.setData(voice.key, _KEY_ROLE)
                item.setData(spoken_label(voice), Qt.ItemDataRole.AccessibleTextRole)
                item.setToolTip(_tooltip(voice))
                item.setEnabled(voice.installed)
                if voice.installed:
                    self._rows[voice.key] = self._model.rowCount()
                else:  # the reason is text a person reads: the secondary ink, not the faint gray
                    item.setForeground(self._ink)
                    self._dim_rows.append(self._model.rowCount())
                self._model.appendRow(item)
        for row in self._header_rows:
            view.setItemDelegateForRow(row, self._section_header)
        first_installed = next(iter(self._rows.values()), -1)
        self.combo.setCurrentIndex(self._rows.get(preferred or "", first_installed))
        self.combo.setEnabled(bool(self._rows))
        self.combo.blockSignals(False)
        self._sync_selection()

    def set_loading(self) -> None:
        """An empty, disabled list that says so, until set_voices() delivers the real one."""
        self.set_voices([])
        self.combo.setPlaceholderText(LOADING)

    def set_unavailable(self) -> None:
        """An empty, disabled list for a failed load; the window says why in its status bar."""
        self.set_voices([])
        self.combo.setPlaceholderText(_UNAVAILABLE)

    def voice_key(self) -> str | None:
        key = self.combo.currentData(_KEY_ROLE)
        return key if isinstance(key, str) else None

    def select_voice(self, key: str) -> bool:
        row = self._rows.get(key)
        if row is None:
            return False
        self.combo.setCurrentIndex(row)
        return True

    def speaker_id(self) -> int | None:
        return None if self.speaker_spin.isHidden() else self.speaker_spin.value()

    def _on_index_changed(self, _index: int) -> None:
        self._sync_selection()
        key = self.voice_key()
        if key is not None:
            self.voice_changed.emit(key)

    def _sync_selection(self) -> None:
        voice = self._voices.get(self.voice_key() or "")
        self.combo.setToolTip("" if voice is None else spoken_label(voice))
        self._sync_speaker(voice)

    def _sync_speaker(self, voice: VoiceInfo | None) -> None:
        speakers = 1 if voice is None else voice.num_speakers
        if speakers > 1:
            last = speakers - 1
            self.speaker_spin.setRange(0, last)
            self.speaker_spin.setValue(0)
            self.speaker_spin.setToolTip(f"Speakers are numbered 0 to {last}.")
            self.speaker_spin.setAccessibleDescription(
                f"Choose a speaker of this voice. 0 to {last}."
            )
        for widget in (self.speaker_label, self.speaker_spin):
            widget.setVisible(speakers > 1)
