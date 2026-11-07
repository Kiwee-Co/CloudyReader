"""Child process of test_window_teardown.py: close and delete windows as a reading ends.

usage: python -I -B window_teardown_probe.py <checkout> <settings-dir> <rounds>
A timer thread opens the reading's gate just after close() starts, so the job ends while the
window goes away. It prints "ok" unless the deletion deadlocks.
"""

import os
import sys
import threading

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # never a real window
sys.path.insert(0, sys.argv[1])

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cloudyreader.gui import main_window  # noqa: E402
from cloudyreader.gui.fake_service import FakePlayer, FakeReaderService  # noqa: E402

RELEASE_S = 0.2  # after close() starts: an unguarded window is deleted well before this

main_window.reduce_motion = lambda: False  # no read of this Mac's accessibility setting
app = QApplication([])
ini = os.path.join(sys.argv[2], "gui.ini")


def pump(until) -> None:
    while not until():
        app.processEvents()


def close_as_a_reading_ends() -> None:
    service = FakeReaderService(gate=threading.Event())
    settings = QSettings(ini, QSettings.Format.IniFormat)
    window = main_window.MainWindow(service, FakePlayer(), settings=settings)
    pump(lambda: not window.loading_voices)
    window.question_edit.setPlainText("What is H2O?")
    window.speak_button.click()
    pump(lambda: bool(service.calls))  # the reading is on the worker, waiting at its gate
    threading.Timer(RELEASE_S, service.gate.set).start()
    window.close()
    window.deleteLater()  # pytest-qt's teardown; the app drops its last reference instead
    loop = QEventLoop()
    QTimer.singleShot(0, loop.quit)
    loop.exec()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


for _ in range(int(sys.argv[3])):
    close_as_a_reading_ends()
print("ok")
