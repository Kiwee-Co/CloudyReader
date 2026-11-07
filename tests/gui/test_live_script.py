"""LiveScript: the Spoken script follows the question after a pause, off the UI thread."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import pytest
import shiboken6
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from cloudyreader.gui.live_script import LiveScript
from cloudyreader.models import RenderOptions

DEBOUNCE_MS = 25
BURST_MS = 300  # typing and pasting finish well inside it, even on a busy machine
SETTLE_MS = 6 * DEBOUNCE_MS  # long enough that a second update, had one been coming, is in
WAIT_MS = 5000
PLAIN = RenderOptions()
ANSWER = RenderOptions(read_answer=True)


@dataclass
class Call:
    raw: str
    opts: RenderOptions
    thread: threading.Thread


class Computer:
    """A compute function that records each call, can hold the worker, and can fail."""

    def __init__(self, gate: threading.Event | None = None, error: Exception | None = None):
        self.calls: list[Call] = []
        self.started = threading.Event()
        self._gate = gate
        self.error = error

    def __call__(self, raw: str, opts: RenderOptions) -> str:
        self.calls.append(Call(raw, opts, threading.current_thread()))
        self.started.set()
        if self._gate is not None and not self._gate.wait(WAIT_MS / 1000):
            raise TimeoutError("the test never released the worker")
        if self.error is not None:
            raise self.error
        return f"script of {raw}"


class Hold(QRunnable):
    """Another job on the shared worker, such as a Speak that is still synthesizing."""

    def __init__(self, gate: threading.Event, started: threading.Event) -> None:
        super().__init__()
        self._gate = gate
        self._started = started

    def run(self) -> None:
        self._started.set()
        self._gate.wait(WAIT_MS / 1000)


@pytest.fixture
def pool(qapp):
    pool = QThreadPool()
    pool.setMaxThreadCount(1)  # the window's pool: one worker, one service call at a time
    yield pool
    assert pool.waitForDone(WAIT_MS)


@pytest.fixture
def gate(pool):
    gate = threading.Event()
    yield gate
    gate.set()  # a test that fails midway must not leave the worker blocked


@pytest.fixture
def make_live(pool):
    owners: list[QObject] = []

    def build(compute, debounce_ms=DEBOUNCE_MS):
        owner = QObject()  # stands in for the window
        owners.append(owner)
        live = LiveScript(compute, pool, debounce_ms=debounce_ms, parent=owner)
        emitted: list[tuple[str, threading.Thread]] = []
        live.script_ready.connect(lambda text: emitted.append((text, threading.current_thread())))
        return live, emitted

    return build


def texts(emitted) -> list[str]:
    return [text for text, _ in emitted]


# --- debounce ----------------------------------------------------------------------------------


def test_a_change_starts_one_single_shot_timer_of_the_given_interval(make_live):
    live, _ = make_live(Computer(), debounce_ms=DEBOUNCE_MS)
    timer = live.findChild(QTimer)

    assert not timer.isActive()
    live.schedule("a", PLAIN)

    assert (timer.isActive(), timer.isSingleShot(), timer.interval()) == (True, True, DEBOUNCE_MS)


def test_nothing_is_built_before_the_pause(qtbot, make_live):
    compute = Computer()
    live, emitted = make_live(compute, debounce_ms=BURST_MS)

    live.schedule("q", PLAIN)
    qtbot.wait(DEBOUNCE_MS)  # a fraction of the pause

    assert compute.calls == [] and emitted == []
    qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)
    assert texts(emitted) == ["script of q"]


def test_a_burst_of_changes_gives_one_job_and_one_update(qtbot, make_live):
    compute = Computer()
    live, emitted = make_live(compute)

    for text in ("W", "Wh", "Wha", "What"):
        live.schedule(text, PLAIN)
    qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)
    qtbot.wait(SETTLE_MS)

    assert texts(emitted) == ["script of What"]
    assert [call.raw for call in compute.calls] == ["What"]


def test_changes_a_pause_apart_are_each_updated(qtbot, make_live):
    live, emitted = make_live(Computer())

    live.schedule("one", PLAIN)
    qtbot.waitUntil(lambda: len(emitted) == 1, timeout=WAIT_MS)
    live.schedule("two", PLAIN)
    qtbot.waitUntil(lambda: len(emitted) == 2, timeout=WAIT_MS)

    assert texts(emitted) == ["script of one", "script of two"]


def test_the_options_of_the_last_change_travel_with_it(qtbot, make_live):
    compute = Computer()
    live, emitted = make_live(compute)

    live.schedule("q", PLAIN)
    live.schedule("q", ANSWER)  # only the answer line was switched on
    qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)

    assert [(call.raw, call.opts) for call in compute.calls] == [("q", ANSWER)]


# --- latest wins -------------------------------------------------------------------------------


def test_a_result_that_a_newer_change_outdated_is_never_shown(qtbot, make_live, gate):
    compute = Computer(gate=gate)
    live, emitted = make_live(compute)
    live.schedule("old", PLAIN)
    qtbot.waitUntil(compute.started.is_set, timeout=WAIT_MS)  # "old" is on the worker, held

    live.schedule("new", PLAIN)
    gate.set()
    qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)
    qtbot.wait(SETTLE_MS)

    assert texts(emitted) == ["script of new"]


def test_a_queued_job_that_a_newer_change_outdated_never_runs(qtbot, make_live, pool, gate):
    held = threading.Event()
    pool.start(Hold(gate, held))  # a Speak is synthesizing: the previews wait behind it
    qtbot.waitUntil(held.is_set, timeout=WAIT_MS)
    compute = Computer()
    live, emitted = make_live(compute)
    live.schedule("first", PLAIN)
    qtbot.wait(SETTLE_MS)  # its timer fires and its job queues
    live.schedule("second", PLAIN)
    qtbot.wait(SETTLE_MS)

    gate.set()
    qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)
    qtbot.wait(SETTLE_MS)

    assert [call.raw for call in compute.calls] == ["second"]
    assert texts(emitted) == ["script of second"]


def test_a_result_already_queued_for_the_ui_thread_loses_to_a_newer_change(
    qtbot, make_live, pool, gate
):
    compute = Computer(gate=gate)
    live, emitted = make_live(compute)
    live.schedule("old", PLAIN)
    qtbot.waitUntil(compute.started.is_set, timeout=WAIT_MS)
    gate.set()
    assert pool.waitForDone(WAIT_MS)  # "old" is done and its result waits in the event queue

    live.schedule("new", PLAIN)  # before the UI thread has looked at that result
    qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)
    qtbot.wait(SETTLE_MS)

    assert texts(emitted) == ["script of new"]


def test_a_change_after_a_slow_preview_still_gets_its_own_update(qtbot, make_live, gate):
    compute = Computer(gate=gate)
    live, emitted = make_live(compute)
    live.schedule("slow", PLAIN)
    qtbot.waitUntil(compute.started.is_set, timeout=WAIT_MS)
    live.schedule("later", PLAIN)
    gate.set()

    qtbot.waitUntil(lambda: texts(emitted) == ["script of later"], timeout=WAIT_MS)


# --- empty and bad input -----------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "   ", "\n\t \n", " 　"])
def test_blank_text_clears_the_panel_without_a_job(qtbot, make_live, raw):
    compute = Computer()
    live, emitted = make_live(compute)

    live.schedule(raw, PLAIN)
    qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)
    qtbot.wait(SETTLE_MS)

    assert texts(emitted) == [""]
    assert compute.calls == []


def test_blank_text_outdates_the_result_still_in_flight(qtbot, make_live, gate):
    compute = Computer(gate=gate)
    live, emitted = make_live(compute)
    live.schedule("text", PLAIN)
    qtbot.waitUntil(compute.started.is_set, timeout=WAIT_MS)

    live.schedule("", PLAIN)  # the box was cleared while "text" was previewing
    gate.set()
    qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)
    qtbot.wait(SETTLE_MS)

    assert texts(emitted) == [""]


def test_a_failing_preview_empties_the_panel_and_logs_a_warning(qtbot, make_live, caplog):
    failure = ValueError("bad paste")
    live, emitted = make_live(Computer(error=failure))

    with caplog.at_level(logging.WARNING, logger="cloudyreader.gui.live_script"):
        live.schedule("garbled paste", PLAIN)
        qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)

    assert texts(emitted) == [""]
    (record,) = (r for r in caplog.records if r.levelno == logging.WARNING)
    assert record.exc_info is not None and record.exc_info[1] is failure


def test_the_next_change_after_a_failure_previews_again(qtbot, make_live):
    compute = Computer(error=ValueError("bad paste"))
    live, emitted = make_live(compute)
    live.schedule("bad", PLAIN)
    qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)

    compute.error = None
    live.schedule("good", PLAIN)
    qtbot.waitUntil(lambda: len(emitted) == 2, timeout=WAIT_MS)

    assert texts(emitted) == ["", "script of good"]


# --- cancel ------------------------------------------------------------------------------------


def test_cancel_drops_the_change_that_is_waiting_for_its_pause(qtbot, make_live):
    compute = Computer()
    live, emitted = make_live(compute)

    live.schedule("text", PLAIN)
    live.cancel()
    qtbot.wait(SETTLE_MS)

    assert emitted == [] and compute.calls == []
    assert not live.findChild(QTimer).isActive()


def test_cancel_drops_a_result_that_is_in_flight(qtbot, make_live, gate):
    compute = Computer(gate=gate)
    live, emitted = make_live(compute)
    live.schedule("text", PLAIN)
    qtbot.waitUntil(compute.started.is_set, timeout=WAIT_MS)

    live.cancel()  # Speak starts: its final script will fill the panel
    gate.set()
    qtbot.wait(SETTLE_MS)

    assert emitted == []


def test_a_change_after_a_cancel_previews_normally(qtbot, make_live):
    live, emitted = make_live(Computer())
    live.schedule("before", PLAIN)
    live.cancel()

    live.schedule("after", PLAIN)
    qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)

    assert texts(emitted) == ["script of after"]


# --- threads -----------------------------------------------------------------------------------


def test_the_preview_runs_on_a_pool_thread_and_the_signal_comes_on_the_ui_thread(qtbot, make_live):
    compute = Computer()
    live, emitted = make_live(compute)

    live.schedule("q", PLAIN)
    qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)

    assert compute.calls[0].thread is not threading.main_thread()
    assert emitted[0][1] is threading.main_thread()


def test_a_preview_waits_for_the_worker_like_any_other_job(qtbot, make_live, pool, gate):
    held = threading.Event()
    pool.start(Hold(gate, held))
    qtbot.waitUntil(held.is_set, timeout=WAIT_MS)
    compute = Computer()
    live, emitted = make_live(compute)

    live.schedule("q", PLAIN)
    qtbot.wait(SETTLE_MS)
    assert compute.calls == [] and emitted == []  # the one worker is busy

    gate.set()
    qtbot.waitUntil(lambda: bool(emitted), timeout=WAIT_MS)
    assert texts(emitted) == ["script of q"]


def test_the_window_closing_during_a_preview_is_quiet(qtbot, make_live, pool, gate):
    compute = Computer(gate=gate)
    live, emitted = make_live(compute)
    live.schedule("q", PLAIN)
    qtbot.waitUntil(compute.started.is_set, timeout=WAIT_MS)

    shiboken6.delete(live.parent())  # the worker is mid-call when the window and its children go
    gate.set()

    assert pool.waitForDone(WAIT_MS)  # pytest-qt fails the test if the worker raised
    qtbot.wait(SETTLE_MS)
    assert emitted == []


# --- wired like the window ---------------------------------------------------------------------


@pytest.fixture
def boxes(qtbot):
    question, panel = QPlainTextEdit(), QPlainTextEdit()
    qtbot.addWidget(question)
    qtbot.addWidget(panel)
    return question, panel


def wire(live, question, panel, opts=PLAIN):
    live.script_ready.connect(panel.setPlainText)
    question.textChanged.connect(lambda: live.schedule(question.toPlainText(), opts))


def test_typing_updates_the_panel_once(qtbot, make_live, boxes):
    question, panel = boxes
    compute = Computer()
    live, _ = make_live(compute, debounce_ms=BURST_MS)
    wire(live, question, panel)

    qtbot.keyClicks(question, "What is H2O?")
    qtbot.waitUntil(lambda: bool(panel.toPlainText()), timeout=WAIT_MS)
    qtbot.wait(SETTLE_MS)

    assert panel.toPlainText() == "script of What is H2O?"
    assert [call.raw for call in compute.calls] == ["What is H2O?"]


def test_a_programmatic_set_and_a_paste_each_update_the_panel(qtbot, make_live, boxes):
    question, panel = boxes
    live, emitted = make_live(Computer())
    wire(live, question, panel)

    question.setPlainText("start question")  # the sample at launch
    qtbot.waitUntil(lambda: len(emitted) == 1, timeout=WAIT_MS)
    question.moveCursor(QTextCursor.MoveOperation.End)
    question.insertPlainText(" pasted")  # a paste inserts at the cursor
    qtbot.waitUntil(lambda: len(emitted) == 2, timeout=WAIT_MS)

    assert panel.toPlainText() == "script of start question pasted"


def test_clearing_the_box_shows_the_placeholder_again(qtbot, make_live, boxes):
    question, panel = boxes
    panel.setPlaceholderText("The words that are spoken appear here.")
    live, _ = make_live(Computer())
    wire(live, question, panel)
    question.setPlainText("text")
    qtbot.waitUntil(lambda: bool(panel.toPlainText()), timeout=WAIT_MS)

    question.clear()
    qtbot.waitUntil(lambda: not panel.toPlainText(), timeout=WAIT_MS)

    assert panel.document().isEmpty()  # empty is what shows the placeholder
