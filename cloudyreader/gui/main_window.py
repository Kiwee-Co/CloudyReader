"""Main window: paste a question, pick a voice, speak it. Layout follows the macOS HIG (Layout)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from itertools import pairwise
from typing import Protocol

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QRunnable,
    QSettings,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    SignalInstance,
)
from PySide6.QtGui import (
    QAccessible,
    QAccessibleAnnouncementEvent,
    QAction,
    QCloseEvent,
    QGuiApplication,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cloudyreader.gui import tokens
from cloudyreader.gui.names import APP_NAME, app_version
from cloudyreader.gui.voice_picker import LOADING, VoicePicker
from cloudyreader.models import AudioPlayer, ReaderService, Reading, RenderOptions, VoiceInfo

log = logging.getLogger(__name__)

_QUEUED = Qt.ConnectionType.QueuedConnection


class ClipboardSource(Protocol):
    """The slice of QClipboard the window reads; tests pass a fake."""

    def text(self) -> str: ...


class _Signals(QObject):
    prepared = Signal(object)  # Reading
    failed = Signal(object)  # Exception from prepare()
    voices_ready = Signal(object)  # list[VoiceInfo]
    voices_failed = Signal(object)  # Exception from voices()


class _Job(QRunnable):
    """Runs one blocking service call off the UI thread and reports back by signal."""

    def __init__(
        self, call: Callable[[], object], done: SignalInstance, failed: SignalInstance
    ) -> None:
        super().__init__()
        self._call = call
        self._done = done
        self._failed = failed

    def run(self) -> None:
        try:
            result = self._call()
        except Exception as exc:  # any backend failure must reach the status bar
            log.exception("service call failed")
            self._failed.emit(exc)
        else:
            self._done.emit(result)


def _warning_text(warnings: tuple[str, ...]) -> str:
    flat = [" ".join(w.split()) for w in warnings]
    if len(flat) == 1:
        return f"Warning: {flat[0]}"
    return f"{len(flat)} warnings: {'; '.join(flat)}"


class MainWindow(QMainWindow):
    busy_changed = Signal(bool)
    reading_played = Signal(object)  # Reading, once player.play() has accepted its audio
    error_occurred = Signal(str)  # the message now in the status bar
    voices_settled = Signal()  # the voice list load ended, whether it worked or not

    def __init__(
        self,
        service: ReaderService,
        player: AudioPlayer,
        *,
        settings: QSettings | None = None,
        clipboard: ClipboardSource | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._player = player
        self._settings = QSettings() if settings is None else settings
        self._clipboard = QGuiApplication.clipboard() if clipboard is None else clipboard
        self._busy = False
        self._loading_voices = True
        self._has_played = False
        self._closing = False
        self._playback_text = ""  # status text owned by playback: cleared when audio ends

        # One worker at a time: the service is not promised to be thread-safe. The pool is created
        # before the signals, so it is destroyed first and waits for a running job to finish.
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals(self)
        self._signals.prepared.connect(self._on_prepared, _QUEUED)
        self._signals.failed.connect(self._on_failed, _QUEUED)
        self._signals.voices_ready.connect(self._on_voices, _QUEUED)
        self._signals.voices_failed.connect(self._on_voices_failed, _QUEUED)
        self._poll = QTimer(self)
        self._poll.setInterval(tokens.PLAYBACK_POLL_MS)
        self._poll.timeout.connect(self._poll_playback)

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(*tokens.WINDOW_MIN_SIZE)
        self.resize(*tokens.WINDOW_DEFAULT_SIZE)
        self._build_actions()
        self._build_ui()
        self._restore_settings()
        self._load_voices()
        self._refresh_controls()
        self.question_edit.setFocus()
        app = QCoreApplication.instance()
        if app is not None:
            # afplay outlives the app: quit() or Cmd+Q must silence it even if no close event runs.
            app.aboutToQuit.connect(self._silence)

    @property
    def loading_voices(self) -> bool:
        return self._loading_voices

    # --- construction ------------------------------------------------------------------------

    def _build_actions(self) -> None:
        def make(text: str, slot: Callable[[], None], *shortcuts: str) -> QAction:
            action = QAction(text, self)
            action.setShortcuts([QKeySequence(s) for s in shortcuts])
            action.triggered.connect(slot)
            return action

        # Ctrl is Cmd on macOS in Qt key sequences.
        self.speak_action = make("Speak", self._on_speak, "Ctrl+Return", "Ctrl+Enter")
        self.speak_clipboard_action = make(
            "Speak Clipboard", self._on_speak_clipboard, "Ctrl+Shift+V"
        )
        self.repeat_action = make("Repeat", self._on_repeat, "Ctrl+R")
        self.stop_action = make("Stop", self._on_stop, "Ctrl+.")

        # Standard app-menu roles: on macOS Qt moves these two into the application menu.
        self.about_action = QAction(f"About {APP_NAME}", self)
        self.about_action.setMenuRole(QAction.MenuRole.AboutRole)
        self.about_action.triggered.connect(self._show_about)
        self.quit_action = QAction(f"Quit {APP_NAME}", self)
        self.quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        self.quit_action.setShortcut(QKeySequence("Ctrl+Q"))  # Cmd+Q; StandardKey.Quit can be empty
        self.quit_action.triggered.connect(self.close)  # one window: closing it ends the app

        # HIG (Menus): every command lives in the menu bar, where its shortcut is discoverable.
        # File and Help only hold the two role actions: macOS empties and hides them.
        bar = self.menuBar()
        bar.addMenu("File").addAction(self.quit_action)
        menu = bar.addMenu("Reading")
        menu.addActions([self.speak_action, self.speak_clipboard_action])
        menu.addSeparator()
        menu.addActions([self.repeat_action, self.stop_action])
        bar.addMenu("Help").addAction(self.about_action)

    def _build_ui(self) -> None:
        self.question_edit = QPlainTextEdit()
        self.question_edit.setPlaceholderText("Paste a question here")
        self.question_edit.setAccessibleName("Question")
        self.question_edit.setTabChangesFocus(True)  # Tab must leave the box, not type a tab

        self.voice_picker = VoicePicker()
        self.read_answer_check = QCheckBox("Read answer line")
        self.online_lookups_check = QCheckBox("Online lookups")

        self.paste_button = QPushButton("Paste")
        self.paste_button.clicked.connect(self._on_paste)
        self.speak_clipboard_button = self._action_button(self.speak_clipboard_action)
        self.repeat_button = self._action_button(self.repeat_action)
        self.stop_button = self._action_button(self.stop_action)
        self.speak_button = self._action_button(self.speak_action)
        self.speak_button.setDefault(True)  # HIG (Buttons): the primary action is the default

        self.script_toggle = QToolButton()
        self.script_toggle.setText("Spoken script")
        self.script_toggle.setCheckable(True)
        self.script_toggle.setAutoRaise(True)
        self.script_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.script_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.script_toggle.setAccessibleDescription("Show or hide the text that is spoken")
        self.script_toggle.toggled.connect(self._toggle_script)
        self.script_view = QPlainTextEdit()
        self.script_view.setReadOnly(True)
        self.script_view.setAccessibleName("Spoken script")
        self.script_view.setMinimumHeight(tokens.SCRIPT_MIN_HEIGHT)
        self.script_view.hide()

        layout = QVBoxLayout()
        layout.setContentsMargins(*(tokens.MARGIN,) * 4)
        layout.setSpacing(tokens.GROUP_SPACING)
        layout.addWidget(self.question_edit, 3)
        layout.addWidget(self.voice_picker)
        options = QHBoxLayout()
        options.setSpacing(tokens.GROUP_SPACING)
        options.addWidget(self.read_answer_check)
        options.addWidget(self.online_lookups_check)
        options.addStretch(1)
        layout.addLayout(options)
        buttons = QHBoxLayout()
        buttons.setSpacing(tokens.CONTROL_SPACING)
        buttons.addWidget(self.paste_button)
        buttons.addWidget(self.speak_clipboard_button)
        buttons.addStretch(1)
        buttons.addWidget(self.repeat_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.speak_button)
        layout.addLayout(buttons)
        layout.addWidget(self.script_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.script_view, 2)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)  # indeterminate: the service reports no progress
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedWidth(tokens.BUSY_BAR_WIDTH)
        self.busy_bar.setAccessibleName("Preparing")
        self.statusBar().addPermanentWidget(self.busy_bar)
        self.busy_bar.hide()

        order = [
            self.question_edit,
            self.voice_picker.combo,
            self.voice_picker.speaker_spin,
            self.read_answer_check,
            self.online_lookups_check,
            self.paste_button,
            self.speak_clipboard_button,
            self.repeat_button,
            self.stop_button,
            self.speak_button,
            self.script_toggle,
            self.script_view,
        ]
        for first, second in pairwise(order):
            QWidget.setTabOrder(first, second)

    def _action_button(self, action: QAction) -> QPushButton:
        button = QPushButton(action.text())
        button.clicked.connect(action.trigger)
        return button

    def _restore_settings(self) -> None:
        saved = self._settings
        self.read_answer_check.setChecked(saved.value("read_answer", False, type=bool))
        self.online_lookups_check.setChecked(saved.value("online_lookups", True, type=bool))
        # Connected after the restore so loading never rewrites the saved preference. The picker
        # never emits when its list is rebuilt, so the voice list arriving cannot overwrite it.
        self.read_answer_check.toggled.connect(lambda on: saved.setValue("read_answer", on))
        self.online_lookups_check.toggled.connect(lambda on: saved.setValue("online_lookups", on))
        self.voice_picker.voice_changed.connect(lambda key: saved.setValue("voice", key))

    def _load_voices(self) -> None:
        # Listing voices can take a second (a model file is hashed): never on the UI thread.
        self.voice_picker.set_loading()
        self._notify(LOADING)
        self._update_busy_bar()
        self._pool.start(
            _Job(self._service.voices, self._signals.voices_ready, self._signals.voices_failed)
        )

    def _on_voices(self, voices: list[VoiceInfo]) -> None:
        if self._closing:
            return
        saved = self._settings.value("voice", "", type=str)
        self.voice_picker.set_voices(voices, preferred=saved)
        self._end_loading()
        if self.voice_picker.voice_key() is None:
            self._notify("No voice is installed.")
        self.voices_settled.emit()

    def _on_voices_failed(self, exc: BaseException) -> None:
        if self._closing:
            return
        self.voice_picker.set_unavailable()
        self._end_loading()
        self._show_error(exc)
        self.voices_settled.emit()

    def _end_loading(self) -> None:
        self._loading_voices = False
        if self.statusBar().currentMessage() == LOADING:  # unless something newer replaced it
            self._clear_status()
        self._update_busy_bar()
        self._refresh_controls()

    # --- state -------------------------------------------------------------------------------

    def _refresh_controls(self) -> None:
        can_speak = self.voice_picker.voice_key() is not None and not self._busy
        states = (
            (self.speak_action, self.speak_button, can_speak),
            (self.speak_clipboard_action, self.speak_clipboard_button, can_speak),
            (self.repeat_action, self.repeat_button, self._has_played and not self._busy),
            (self.stop_action, self.stop_button, self._player.is_playing),
        )
        for action, button, enabled in states:
            action.setEnabled(enabled)
            button.setEnabled(enabled)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_busy_bar()
        self._refresh_controls()
        self.busy_changed.emit(busy)

    def _update_busy_bar(self) -> None:
        self.busy_bar.setVisible(self._busy or self._loading_voices)

    def _notify(self, text: str, *, tooltip: str | None = None) -> None:
        self.statusBar().showMessage(text)
        self.statusBar().setToolTip(tooltip or text)

    def _clear_status(self) -> None:
        self.statusBar().clearMessage()
        self.statusBar().setToolTip("")

    def _show_error(self, exc: BaseException) -> None:
        detail = str(exc).strip() or type(exc).__name__
        text = f"Error: {detail.splitlines()[0]}"
        self._notify(text, tooltip=f"Error: {detail}")
        # No modal, so tell assistive tech the status changed.
        event = QAccessibleAnnouncementEvent(self.statusBar(), text)
        event.setPoliteness(QAccessible.AnnouncementPoliteness.Assertive)
        QAccessible.updateAccessibility(event)
        self.error_occurred.emit(text)

    def _play_status(self, text: str) -> None:
        self._playback_text = text
        self._notify(text)

    def _poll_playback(self) -> None:
        if self._player.is_playing:
            return
        self._poll.stop()
        if self.statusBar().currentMessage() == self._playback_text:
            self._clear_status()
        self._refresh_controls()

    # --- commands ----------------------------------------------------------------------------

    def _on_paste(self) -> None:
        text = self._clipboard.text()
        if not text.strip():
            self._notify("Clipboard is empty.")
            return
        self.question_edit.setPlainText(text)
        self.question_edit.setFocus()

    def _on_speak(self) -> None:
        self._start(self.question_edit.toPlainText())

    def _on_speak_clipboard(self) -> None:
        if self._busy:
            return
        text = self._clipboard.text()
        if not text.strip():
            self._notify("Clipboard is empty.")
            return
        self.question_edit.setPlainText(text)
        self._start(text)

    def _start(self, raw: str) -> None:
        if self._busy:
            return
        voice_key = self.voice_picker.voice_key()
        if voice_key is None:
            self._notify(LOADING if self._loading_voices else "No voice is installed.")
            return
        if not raw.strip():
            self._notify("Paste a question first.")
            return
        opts = RenderOptions(
            read_answer=self.read_answer_check.isChecked(),
            online_lookups=self.online_lookups_check.isChecked(),
            speaker_id=self.voice_picker.speaker_id(),
        )
        self._set_busy(True)
        self._notify("Preparing…")
        self._pool.start(
            _Job(
                lambda: self._service.prepare(raw, voice_key, opts),
                self._signals.prepared,
                self._signals.failed,
            )
        )

    def _on_prepared(self, reading: Reading) -> None:
        if self._closing:
            return
        self._set_busy(False)
        self.script_view.setPlainText(reading.script.text())
        try:
            if self._player.is_playing:
                self._player.stop()
            self._player.play(reading.audio)
        except Exception as exc:  # no output device, unreadable WAV: report and stay usable
            log.exception("playback failed")
            self._show_error(exc)
            return
        self._has_played = True
        self._poll.start()
        warnings = tuple(dict.fromkeys((*reading.warnings, *reading.script.warnings)))
        if warnings:
            self._notify(_warning_text(warnings))
        else:
            self._play_status(f"Playing {reading.audio.duration_s:.1f} s.")
        self._refresh_controls()
        self.reading_played.emit(reading)

    def _on_failed(self, exc: BaseException) -> None:
        if self._closing:
            return
        self._set_busy(False)
        self._show_error(exc)

    def _on_repeat(self) -> None:
        try:
            replayed = self._player.replay()
        except Exception as exc:
            log.exception("replay failed")
            self._show_error(exc)
            return
        if not replayed:
            self._notify("Nothing to repeat yet.")
            return
        self._play_status("Repeating.")
        self._poll.start()
        self._refresh_controls()

    def _on_stop(self) -> None:
        try:
            self._player.stop()
        except Exception as exc:
            log.exception("stop failed")
            self._show_error(exc)
            return
        self._poll.stop()
        self._notify("Stopped.")
        self._refresh_controls()

    def _show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(APP_NAME)
        about = f"Version {app_version()}\nReads National Science Bowl questions aloud."
        box.setInformativeText(about)
        icon = self.windowIcon()
        if not icon.isNull():
            box.setIconPixmap(icon.pixmap(tokens.ABOUT_ICON_SIZE, tokens.ABOUT_ICON_SIZE))
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.setWindowModality(Qt.WindowModality.NonModal)  # like the system About panel
        box.show()

    def _toggle_script(self, shown: bool) -> None:
        self.script_view.setVisible(shown)
        arrow = Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow
        self.script_toggle.setArrowType(arrow)

    def event(self, event: QEvent) -> bool:
        # Menu hover sends an empty status tip that would wipe a message the user has not read.
        if event.type() == QEvent.Type.StatusTip:
            return True
        return super().event(event)

    def _silence(self) -> None:
        """Stop playback. Idempotent: it runs when the window closes and again at aboutToQuit."""
        try:
            if self._player.is_playing:
                self._player.stop()
        except Exception:
            log.exception("stopping playback on exit failed")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True  # a result still in flight must not start audio after close
        self._silence()
        super().closeEvent(event)
