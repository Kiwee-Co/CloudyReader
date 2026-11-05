"""Main window: paste a question, pick a voice, speak it. Layout follows the macOS HIG (Layout)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from itertools import pairwise
from typing import Protocol

from PySide6.QtCore import (
    QByteArray,
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
    QColor,
    QGuiApplication,
    QKeySequence,
    QPalette,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cloudyreader.gui import tokens
from cloudyreader.gui.names import APP_NAME, app_version
from cloudyreader.gui.voice_picker import LOADING, VoicePicker
from cloudyreader.gui.widgets import DisclosureButton, StatusBar, Tone, text_style
from cloudyreader.models import AudioPlayer, ReaderService, Reading, RenderOptions, VoiceInfo

log = logging.getLogger(__name__)

_QUEUED = Qt.ConnectionType.QueuedConnection
_NATIVE = QKeySequence.SequenceFormat.NativeText


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
        self._about_box: QMessageBox | None = None

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
        self._status = StatusBar()
        self.setStatusBar(self._status)
        self._build_actions()
        self._build_ui()
        self._apply_text_colors()
        # The system switches light and dark at runtime; the placeholder tokens follow it.
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._apply_text_colors)
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
        def make(text: str, slot: Callable[[], object], *shortcuts: str) -> QAction:
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
        self.close_action = make("Close Window", self.close, "Ctrl+W")
        self.minimize_action = make("Minimize", self.showMinimized, "Ctrl+M")
        self.zoom_action = make("Zoom", self._toggle_zoom)

        # Edit commands act on the focused text field, which takes these keys itself anyway.
        def edit(text: str, key: QKeySequence.StandardKey, command: str) -> QAction:
            action = QAction(text, self)
            action.setShortcuts(key)
            action.triggered.connect(lambda: self._edit(command))
            return action

        self.undo_action = edit("Undo", QKeySequence.StandardKey.Undo, "undo")
        self.redo_action = edit("Redo", QKeySequence.StandardKey.Redo, "redo")
        self.cut_action = edit("Cut", QKeySequence.StandardKey.Cut, "cut")
        self.copy_action = edit("Copy", QKeySequence.StandardKey.Copy, "copy")
        self.paste_action = edit("Paste", QKeySequence.StandardKey.Paste, "paste")
        self.select_all_action = edit("Select All", QKeySequence.StandardKey.SelectAll, "selectAll")
        self._edit_actions = {
            "undo": self.undo_action,
            "redo": self.redo_action,
            "cut": self.cut_action,
            "copy": self.copy_action,
            "paste": self.paste_action,
            "selectAll": self.select_all_action,
        }

        # Standard app-menu roles: on macOS Qt moves these two into the application menu.
        self.about_action = QAction(f"About {APP_NAME}", self)
        self.about_action.setMenuRole(QAction.MenuRole.AboutRole)
        self.about_action.triggered.connect(self._show_about)
        self.quit_action = QAction(f"Quit {APP_NAME}", self)
        self.quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        self.quit_action.setShortcut(QKeySequence("Ctrl+Q"))  # Cmd+Q; StandardKey.Quit can be empty
        self.quit_action.triggered.connect(self.close)  # one window: closing it ends the app

        # HIG (Menus): the standard menus in the standard order, every shortcut discoverable.
        # Help only holds the About role action, so macOS empties and hides it.
        bar = self.menuBar()
        bar.addMenu("File").addActions([self.close_action, self.quit_action])
        self.edit_menu = bar.addMenu("Edit")
        self.edit_menu.addActions([self.undo_action, self.redo_action])
        self.edit_menu.addSeparator()
        self.edit_menu.addActions(
            [self.cut_action, self.copy_action, self.paste_action, self.select_all_action]
        )
        self.edit_menu.aboutToShow.connect(self._update_edit_actions)
        menu = bar.addMenu("Reading")
        menu.addActions([self.speak_action, self.speak_clipboard_action])
        menu.addSeparator()
        menu.addActions([self.repeat_action, self.stop_action])
        bar.addMenu("Window").addActions([self.minimize_action, self.zoom_action])
        bar.addMenu("Help").addAction(self.about_action)

    def _build_ui(self) -> None:
        speak_keys = self.speak_action.shortcuts()[0].toString(_NATIVE)
        self.question_edit = QPlainTextEdit()
        self.question_edit.setPlaceholderText(
            f"Paste a National Science Bowl question, then press {speak_keys} to hear it."
        )
        self.question_edit.setAccessibleName("Question")
        self.question_edit.setTabChangesFocus(True)  # Tab must leave the box, not type a tab
        self.question_edit.document().setDocumentMargin(tokens.TEXT_INSET)

        self.voice_picker = VoicePicker()
        self.read_answer_check = QCheckBox("Read answer line")
        self.read_answer_check.setToolTip("Also read the ANSWER line aloud.")
        self.online_lookups_check = QCheckBox("Online lookups")
        self.online_lookups_check.setToolTip(
            "Look up chemical and protein names on PubChem and UniProt to say them right."
        )

        self.paste_button = QPushButton("Paste")
        self.paste_button.setToolTip("Replace the question with the clipboard text.")
        self.paste_button.clicked.connect(self._on_paste)
        self.speak_clipboard_button = self._action_button(
            self.speak_clipboard_action, "Paste the clipboard and speak it"
        )
        self.repeat_button = self._action_button(self.repeat_action, "Play the last reading again")
        self.stop_button = self._action_button(self.stop_action, "Stop playback")
        self.speak_button = self._action_button(self.speak_action, "Speak the question")
        self.speak_button.setDefault(True)  # HIG (Buttons): the primary action is the default

        self.script_toggle = DisclosureButton("Spoken script")
        self.script_toggle.setAccessibleDescription("Show or hide the text that is spoken")
        self.script_toggle.toggled.connect(self._toggle_script)
        self.script_view = QPlainTextEdit()
        self.script_view.setReadOnly(True)
        self.script_view.setAccessibleName("Spoken script")
        self.script_view.setPlaceholderText("The words that are spoken appear here.")
        self.script_view.setFont(text_style(tokens.TEXT_CALLOUT_PT))  # secondary to the question
        self.script_view.document().setDocumentMargin(tokens.TEXT_INSET)
        self.script_view.setMinimumHeight(tokens.SCRIPT_MIN_HEIGHT)
        self.script_view.hide()

        # HIG (Layout): a form with right-aligned labels; popups keep their natural width.
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.setHorizontalSpacing(tokens.CONTROL_SPACING)
        form.setVerticalSpacing(tokens.CONTROL_SPACING)
        form.addRow(self.voice_picker.label, self.voice_picker)
        # A plain label, no buddy: each checkbox is named by its own text for VoiceOver.
        form.addRow(QLabel("Options:"), self.read_answer_check)
        form.addRow("", self.online_lookups_check)  # empty text: Qt adds no label at all
        buttons = QHBoxLayout()
        buttons.setSpacing(tokens.GROUP_SPACING)
        buttons.addWidget(self.paste_button)
        buttons.addWidget(self.speak_clipboard_button)
        buttons.addStretch(1)
        buttons.addWidget(self.repeat_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.speak_button)
        script = QVBoxLayout()  # a hidden view adds no spacing, so collapsed leaves no gap
        script.setSpacing(tokens.CONTROL_SPACING)
        script.addWidget(self.script_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        script.addWidget(self.script_view)

        layout = QVBoxLayout()
        layout.setContentsMargins(*(tokens.MARGIN,) * 4)
        layout.setSpacing(tokens.SECTION_SPACING)
        layout.addWidget(self.question_edit, 3)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addLayout(script, 2)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)  # indeterminate: the service reports no progress
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedWidth(tokens.BUSY_BAR_WIDTH)
        self.busy_bar.setAccessibleName("Preparing")
        self._status.addPermanentWidget(self.busy_bar)
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

    def _action_button(self, action: QAction, tip: str) -> QPushButton:
        button = QPushButton(action.text())
        button.setToolTip(f"{tip} ({action.shortcuts()[0].toString(_NATIVE)})")
        button.clicked.connect(action.trigger)
        return button

    def _apply_text_colors(self, scheme: Qt.ColorScheme | None = None) -> None:
        """Give placeholders the AA token of the current appearance; other colors stay native."""
        if scheme is None:
            scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Unknown:  # no word from the platform: judge the background
            base = self.question_edit.palette().color(QPalette.ColorRole.Base)
            scheme = Qt.ColorScheme.Dark if base.lightness() < 128 else Qt.ColorScheme.Light
        dark = scheme == Qt.ColorScheme.Dark
        palette = QPalette()  # sets no role yet, so every other role keeps following the system
        palette.setColor(
            QPalette.ColorRole.PlaceholderText,
            QColor(tokens.PLACEHOLDER_DARK if dark else tokens.PLACEHOLDER_LIGHT),
        )
        for view in (self.question_edit, self.script_view):
            view.setPalette(palette)

    def _restore_settings(self) -> None:
        saved = self._settings
        geometry = saved.value("geometry")
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            self.restoreGeometry(geometry)  # HIG: reopen where the user left it; False if broken
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
            self._notify("No voice is installed.", tone=Tone.WARNING)
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
        if self._status.currentMessage() == LOADING:  # unless something newer replaced it
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

    def _notify(self, text: str, *, tooltip: str | None = None, tone: Tone = Tone.INFO) -> None:
        self._status.show_message(text, tone)
        self._status.setToolTip(tooltip or text)

    def _clear_status(self) -> None:
        self._status.clearMessage()
        self._status.setToolTip("")

    def _show_error(self, exc: BaseException) -> None:
        detail = str(exc).strip() or type(exc).__name__
        text = f"Error: {detail.splitlines()[0]}"
        self._notify(text, tooltip=f"Error: {detail}", tone=Tone.ERROR)
        # No modal, so tell assistive tech the status changed.
        event = QAccessibleAnnouncementEvent(self._status, text)
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
        if self._status.currentMessage() == self._playback_text:
            self._clear_status()
        self._refresh_controls()

    # --- commands ----------------------------------------------------------------------------

    def _edit_target(self) -> QPlainTextEdit | QLineEdit | None:
        """The text field an Edit command acts on: the one with focus in this window."""
        widget = self.focusWidget()
        if isinstance(widget, QAbstractSpinBox):
            widget = widget.findChild(QLineEdit)
        return widget if isinstance(widget, QPlainTextEdit | QLineEdit) else None

    def _edit(self, command: str) -> None:
        target = self._edit_target()
        if target is not None:
            getattr(target, command)()

    def _update_edit_actions(self) -> None:
        """HIG (Menus): dim the Edit commands that cannot act on the focused field."""
        target = self._edit_target()
        states = dict.fromkeys(self._edit_actions, False)
        if isinstance(target, QPlainTextEdit):
            doc, editable = target.document(), not target.isReadOnly()
            selected = target.textCursor().hasSelection()
            states |= {
                "undo": editable and doc.isUndoAvailable(),
                "redo": editable and doc.isRedoAvailable(),
                "cut": editable and selected,
                "copy": selected,
                "paste": target.canPaste(),
                "selectAll": not doc.isEmpty(),
            }
        elif isinstance(target, QLineEdit):
            editable, selected = not target.isReadOnly(), target.hasSelectedText()
            states |= {
                "undo": target.isUndoAvailable(),
                "redo": target.isRedoAvailable(),
                "cut": editable and selected,
                "copy": selected,
                "paste": editable,
                "selectAll": bool(target.text()),
            }
        for command, enabled in states.items():
            self._edit_actions[command].setEnabled(enabled)

    def _toggle_zoom(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

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
            if self._loading_voices:
                self._notify(LOADING)
            else:
                self._notify("No voice is installed.", tone=Tone.WARNING)
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
            self._notify(_warning_text(warnings), tone=Tone.WARNING)
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
        if self._about_box is not None:  # one panel at a time, like the system About window
            self._about_box.raise_()
            self._about_box.activateWindow()
            return
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
        box.finished.connect(self._forget_about_box)  # on close, before the deferred delete
        self._about_box = box
        box.show()

    def _forget_about_box(self) -> None:
        self._about_box = None

    def _toggle_script(self, shown: bool) -> None:
        self.script_view.setVisible(shown)  # the disclosure button turns its own triangle

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
        self._settings.setValue("geometry", self.saveGeometry())
        self._silence()
        super().closeEvent(event)
