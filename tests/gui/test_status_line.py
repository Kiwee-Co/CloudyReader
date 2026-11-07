"""The status line: its height, its inks, one progress bar at a time, and the message's share of
the line."""

import threading

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QFont, QHelpEvent, QPalette
from PySide6.QtWidgets import QApplication, QToolTip

from cloudyreader.gui import theme, tokens
from cloudyreader.gui.fake_service import FakeReaderService
from cloudyreader.gui.status import ElidedLabel, StatusBar, Tone
from cloudyreader.prefetch import PrefetchProgress, PrefetchResult
from tests.gui.test_tokens import LOOKS

MB = 10**6
ENGINE_LABEL = "Downloading Chatterbox Turbo… 42% (176 of 420 MB)"
HINT = "loading Chatterbox Turbo (first use only)"  # makes "Preparing…" longer than half a line
TNUM = QFont.Tag("tnum")
ELIDE_RIGHT = Qt.TextElideMode.ElideRight


def engine_report() -> PrefetchProgress:
    return PrefetchProgress(
        "model.safetensors",
        1_489 * MB,
        3_050 * MB,
        1,
        64,
        group="chatterbox_turbo",
        group_done_bytes=420 * MB * 42 // 100,  # 42%: 176.4 MB, which the label rounds to 176
        group_total_bytes=420 * MB,
    )


def engine_download(qtbot, make_window, request, *, hint: str | None = None, **knobs):
    """A window downloading an engine; with hint, a reading is held in preparation too."""
    gate, prepare = threading.Event(), threading.Event()
    request.addfinalizer(gate.set)
    request.addfinalizer(prepare.set)
    service = FakeReaderService(
        prefetch_gate=gate,
        prefetch_events=[engine_report()],
        prefetch_result=PrefetchResult("nothing"),
        gate=prepare,
        load_hint=hint,
        **knobs,
    )
    window = make_window(service=service)
    qtbot.waitUntil(window.prefetch_label.isVisible, timeout=5000)
    return window


def hold_reading_during_download(qtbot, make_window, request, hint=HINT):
    """A reading held in preparation, its long first-use message beside an engine download."""
    window = engine_download(qtbot, make_window, request, hint=hint)
    window.question_edit.setPlainText("What is H2O?")
    window.speak_button.click()
    qtbot.waitUntil(lambda: window._busy, timeout=2000)  # private on purpose: no public flag
    return window


@pytest.fixture
def busy_during_download(qtbot, make_window, request):
    return hold_reading_during_download(qtbot, make_window, request)


def message_share(window) -> float:
    bar = window.statusBar()
    bar.layout().activate()
    _icon, text, _elided = bar.message_layout()
    area = bar.contentsRect()
    return (text.right() + 1 - area.left()) / area.width()


def message_needs(window) -> float:
    """The share of the line the message needs whole."""
    bar = window.statusBar()
    return bar.fontMetrics().horizontalAdvance(bar.currentMessage()) / bar.contentsRect().width()


def resize(qtbot, window, width: int) -> None:
    window.resize(width, window.height())
    qtbot.waitUntil(lambda: window.width() == width)
    QApplication.processEvents()


def test_the_status_line_is_at_least_the_token_height(window):
    bar = window.statusBar()

    assert bar.minimumHeight() == tokens.STATUS_LINE_HEIGHT
    assert bar.height() >= tokens.STATUS_LINE_HEIGHT


def test_at_560_a_long_message_keeps_half_the_line_and_the_label_elides(
    qtbot, busy_during_download
):
    window = busy_during_download
    resize(qtbot, window, tokens.WINDOW_MIN_SIZE[0])

    assert window.statusBar().currentMessage() == f"Preparing… {HINT}"
    assert message_needs(window) > tokens.MESSAGE_MIN_SHARE
    assert message_share(window) >= tokens.MESSAGE_MIN_SHARE
    assert window.prefetch_label.is_elided()


def test_a_short_message_shows_whole_and_leaves_the_label_its_room(qtbot, make_window, request):
    window = hold_reading_during_download(qtbot, make_window, request, hint=None)
    resize(qtbot, window, tokens.WINDOW_DEFAULT_SIZE[0])

    assert window.statusBar().currentMessage() == "Preparing…"
    assert message_share(window) >= message_needs(window)  # the message shows whole
    assert not window.prefetch_label.is_elided()


def test_an_idle_line_never_cuts_the_download_label(qtbot, make_window, request):
    window = engine_download(qtbot, make_window, request)
    resize(qtbot, window, tokens.WINDOW_DEFAULT_SIZE[0])

    assert window.statusBar().currentMessage() == ""
    assert window.prefetch_label.text() == ENGINE_LABEL
    assert not window.prefetch_label.is_elided()


@pytest.fixture
def mac_busy_during_download(mac_style, qtbot, make_window, request):
    return hold_reading_during_download(qtbot, make_window, request)


def test_in_the_macos_style_the_message_keeps_half_the_line_too(qtbot, mac_busy_during_download):
    window = mac_busy_during_download
    resize(qtbot, window, tokens.WINDOW_MIN_SIZE[0])

    assert message_share(window) >= tokens.MESSAGE_MIN_SHARE


def test_in_the_macos_style_the_label_sits_on_the_messages_line(mac_busy_during_download):
    window = mac_busy_during_download
    bar, label = window.statusBar(), window.prefetch_label
    bar.layout().activate()

    middle = label.mapTo(bar, QPoint(0, 0)).y() + label.height() / 2

    assert abs(middle - bar.height() / 2) <= 0.5  # QStatusBar pads 3 pt above, 2 pt below


def test_only_the_download_bar_shows_while_a_reading_is_prepared(busy_during_download):
    window = busy_during_download

    assert window.prefetch_bar.isVisible()
    assert window.busy_bar.isHidden()


def test_short_of_room_the_label_elides_at_its_end(qtbot, busy_during_download):
    window = busy_during_download
    resize(qtbot, window, tokens.WINDOW_MIN_SIZE[0])
    label = window.prefetch_label

    assert label.is_elided()
    shown = label.fontMetrics().elidedText(label.text(), ELIDE_RIGHT, label.contentsRect().width())
    assert shown.endswith("…")
    assert shown.startswith("Downloading")
    assert label.text() == ENGINE_LABEL  # the full text stays the label's, for VoiceOver too


def test_an_elided_label_shows_the_whole_text_over_its_tooltip(qtbot):
    label = ElidedLabel("Downloading Chatterbox Turbo… 42% (176 of 420 MB)")
    qtbot.addWidget(label)
    label.setToolTip("model.safetensors (all downloads: 48%)")
    label.resize(40, 20)
    label.show()
    point = QPoint(5, 5)

    try:
        QApplication.sendEvent(
            label, QHelpEvent(QEvent.Type.ToolTip, point, label.mapToGlobal(point))
        )
        assert QToolTip.text() == f"{label.text()}\n{label.toolTip()}"
    finally:
        QToolTip.hideText()
    assert label.toolTip() == "model.safetensors (all downloads: 48%)"  # the given tip stays


def test_a_label_with_room_keeps_its_plain_tooltip(qtbot):
    label = ElidedLabel("Downloading voices… 4%")
    qtbot.addWidget(label)
    label.resize(label.sizeHint())
    label.show()

    assert not label.is_elided()
    assert label.minimumSizeHint().width() == 0  # it never holds the window wider


@pytest.mark.parametrize("width", [tokens.WINDOW_DEFAULT_SIZE[0], tokens.WINDOW_MIN_SIZE[0]])
@pytest.mark.parametrize(
    ("voices", "message"), [(None, ""), ([], "No voice is installed.")], ids=["idle", "no voice"]
)
def test_the_download_label_text_sits_8_pt_left_of_its_bar(
    qtbot, make_window, request, width, voices, message
):
    check_label_beside_bar(qtbot, make_window, request, width, voices, message)


@pytest.mark.parametrize("width", [tokens.WINDOW_DEFAULT_SIZE[0], tokens.WINDOW_MIN_SIZE[0]])
def test_in_the_macos_style_the_label_stays_beside_its_bar_too(
    mac_style, qtbot, make_window, request, width
):
    check_label_beside_bar(qtbot, make_window, request, width, [], "No voice is installed.")


def check_label_beside_bar(qtbot, make_window, request, width, voices, message) -> None:
    knobs = {} if voices is None else {"voices": voices}
    window = engine_download(qtbot, make_window, request, **knobs)
    resize(qtbot, window, width)
    label, bar = window.prefetch_label, window.prefetch_bar
    shown = label.fontMetrics().elidedText(label.text(), ELIDE_RIGHT, label.contentsRect().width())
    drawn = label.style().itemTextRect(
        label.fontMetrics(), label.contentsRect(), label.alignment(), True, shown
    )

    assert window.statusBar().currentMessage() == message
    text_right = label.mapTo(bar.parentWidget(), drawn.topRight()).x() + 1  # right() is inclusive
    assert bar.geometry().left() - text_right == tokens.CONTROL_SPACING
    image = label.grab().toImage()  # the painted ink ends at the label's right edge too
    ink = [
        x
        for x in range(image.width())
        if any(image.pixelColor(x, y).lightness() < 128 for y in range(image.height()))
    ]
    assert image.width() - 1 - max(ink) <= 2  # a glyph's side bearing at most


def test_counting_digits_are_tabular(window):
    for widget in (window.statusBar(), window.prefetch_label):
        assert widget.font().featureValue(TNUM) == 1


# --- inks ----------------------------------------------------------------------------------------


@pytest.fixture
def bar(qtbot):
    widget = StatusBar()
    qtbot.addWidget(widget)
    widget.resize(tokens.WINDOW_DEFAULT_SIZE[0], tokens.STATUS_LINE_HEIGHT)
    widget.show()
    return widget


@pytest.mark.parametrize("name", list(LOOKS))
def test_information_reads_in_the_secondary_ink_of_the_appearance(bar, name):
    roles = theme.roles(LOOKS[name])
    bar.set_roles(roles)

    bar.show_message("Playing 2.4 s with Heart (female, Kokoro).")

    assert bar.ink() == QColor(roles.secondary_text)


@pytest.mark.parametrize("tone", [Tone.WARNING, Tone.ERROR])
@pytest.mark.parametrize("name", list(LOOKS))
def test_a_warning_or_an_error_reads_in_the_text_color(bar, name, tone):
    bar.set_roles(theme.roles(LOOKS[name]))

    bar.show_message("Some status text", tone)

    assert bar.ink() == bar.palette().color(QPalette.ColorRole.WindowText)


def test_a_new_status_bar_takes_the_appearance_it_starts_in(qtbot, monkeypatch):
    monkeypatch.setattr(theme, "current", lambda: LOOKS["hc-dark"])
    widget = StatusBar()
    qtbot.addWidget(widget)

    widget.show_message("Stopped.")

    assert widget.ink() == QColor(theme.roles(LOOKS["hc-dark"]).secondary_text)


def test_the_message_is_painted_in_its_ink(bar, monkeypatch):
    magenta = QColor("#ff00ff")
    monkeypatch.setattr(StatusBar, "ink", lambda _self: magenta)
    bar.show_message("Stopped.")
    _icon, text_rect, _text = bar.message_layout()

    image = bar.grab().toImage()

    def tinted(x: int, y: int) -> bool:  # magenta over gray: red and blue well above green
        color = image.pixelColor(x, y)
        return min(color.red(), color.blue()) - color.green() > 64

    xs = range(text_rect.left(), text_rect.right() + 1)
    ys = range(text_rect.top(), text_rect.bottom() + 1)
    assert any(tinted(x, y) for x in xs for y in ys)


def test_the_message_layout_keeps_its_shape_for_the_figure_generator(bar):
    bar.show_message("Error: boom", Tone.ERROR)

    icon, text, elided = bar.message_layout()

    assert (icon.left(), icon.width(), icon.height()) == (
        tokens.MARGIN,
        *(tokens.STATUS_ICON_SIZE,) * 2,
    )
    assert text.left() == icon.right() + 1 + tokens.INDICATOR_SPACING
    assert elided == "Error: boom"
