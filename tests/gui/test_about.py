"""The About panel: a centered icon, name, version and description, no buttons, and its keys."""

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QSizeF, Qt
from PySide6.QtGui import QAccessible, QColor, QFont, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget

from cloudyreader.gui import tokens
from cloudyreader.gui.about import AboutPanel
from cloudyreader.gui.widgets import text_style

NAME = "Cloudy Reader"
DESCRIPTION = "Reads National Science Bowl questions aloud."
CTRL = Qt.KeyboardModifier.ControlModifier  # Command on a Mac
INK = QPalette.ColorRole.WindowText
TNUM = QFont.Tag("tnum")
CLOSERS = {
    "Escape": lambda qtbot, panel: qtbot.keyClick(panel, Qt.Key.Key_Escape),
    "Command-W": lambda qtbot, panel: qtbot.keyClick(panel, Qt.Key.Key_W, CTRL),
    "the close button": lambda qtbot, panel: panel.close(),
}


@pytest.fixture
def icon():
    """A source twice the panel's icon size: QIcon never scales a pixmap up."""
    pixmap = QPixmap(2 * tokens.ABOUT_ICON_SIZE, 2 * tokens.ABOUT_ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.blue)
    return QIcon(pixmap)


@pytest.fixture
def make_panel(qtbot):
    """Show an AboutPanel in front of a host window, as the main window does; the host cleans up."""
    host = QWidget()
    qtbot.addWidget(host)

    def build(*, name=NAME, version="0.0.3", description=DESCRIPTION, icon=None):
        panel = AboutPanel(name, version, description, QIcon() if icon is None else icon, host)
        with qtbot.waitActive(panel):  # a window shortcut works only in the active window
            panel.show()
        return panel

    return build


def column(panel) -> list[QLabel]:
    return [panel.icon_label, panel.name_label, panel.version_label, panel.description_label]


def ink_center(panel, label) -> float:
    """The middle of what the label draws, in the panel's coordinates."""
    image = panel.grab(label.geometry()).toImage()
    background = image.pixelColor(0, 0)
    ink = [
        x
        for x in range(image.width())
        if any(image.pixelColor(x, y) != background for y in range(image.height()))
    ]
    return label.x() + (min(ink) + max(ink) + 1) / 2


# --- what it says ----------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["0.0.3", "dev"])
def test_the_panel_names_the_app_its_version_and_what_it_does(make_panel, version):
    panel = make_panel(version=version)

    assert panel.windowTitle() == "About Cloudy Reader"
    texts = [panel.name_label.text(), panel.version_label.text(), panel.description_label.text()]
    assert texts == [NAME, f"Version {version}", DESCRIPTION]
    labels = [panel.name_label, panel.version_label, panel.description_label]
    assert {label.textFormat() for label in labels} == {Qt.TextFormat.PlainText}


def test_the_type_follows_the_ramp_and_only_the_version_is_tabular_and_selectable(make_panel):
    panel = make_panel()
    title, section = text_style(tokens.TEXT_TITLE_PT), text_style(tokens.TEXT_SECTION_PT)

    assert panel.name_label.font().pointSizeF() == pytest.approx(title.pointSizeF())
    assert panel.name_label.font().weight() == QFont.Weight.DemiBold
    for label in (panel.version_label, panel.description_label):
        assert label.font().pointSizeF() == pytest.approx(section.pointSizeF())
        assert label.font().weight() == QFont.Weight.Normal
    assert panel.version_label.font().featureValue(TNUM) == 1
    selectable = Qt.TextInteractionFlag.TextSelectableByMouse
    assert panel.version_label.textInteractionFlags() & selectable
    assert not panel.name_label.textInteractionFlags() & selectable
    assert not panel.description_label.textInteractionFlags() & selectable


def test_set_secondary_inks_the_version_and_description_and_leaves_the_name(make_panel):
    panel = make_panel()
    name_ink = panel.name_label.palette().color(INK)

    for ink in (QColor("#336699"), QColor("#cc9966")):  # a second call replaces the first
        panel.set_secondary(ink)

        for label in (panel.version_label, panel.description_label):
            assert label.palette().color(INK) == ink
        assert panel.name_label.palette().color(INK) == name_ink


# --- its shape -------------------------------------------------------------------------------


@pytest.mark.parametrize("native", [False, True], ids=["default", "macOS"])
def test_the_column_is_centered_with_the_gaps_of_the_spec(request, make_panel, icon, native):
    if native:
        request.getfixturevalue("mac_style")
    panel = make_panel(icon=icon)
    labels = column(panel)
    gaps = [tokens.ABOUT_ICON_GAP, tokens.ABOUT_LINE_GAP, tokens.GROUP_SPACING]

    assert labels[0].y() == tokens.MARGIN
    for above, below, gap in zip(labels[:-1], labels[1:], gaps, strict=True):
        assert below.y() == above.y() + above.height() + gap
    assert panel.height() == labels[-1].y() + labels[-1].height() + tokens.MARGIN
    for label in labels:
        assert label.geometry().center().x() == pytest.approx(panel.width() / 2, abs=1)
    for label in labels[1:]:  # the text too, not only its box
        assert ink_center(panel, label) == pytest.approx(panel.width() / 2, abs=2)


def test_the_panel_is_300_wide_and_the_description_fits_on_one_line(make_panel):
    panel = make_panel()
    label = panel.description_label
    advance = label.fontMetrics().horizontalAdvance(DESCRIPTION)

    assert advance + 2 * tokens.MARGIN <= tokens.ABOUT_WIDTH  # the premise: it fits in 300 pt
    assert panel.width() == tokens.ABOUT_WIDTH
    assert label.width() >= advance
    assert not label.wordWrap()


def test_a_long_description_widens_the_panel_instead_of_wrapping_or_clipping(make_panel):
    long = " ".join([DESCRIPTION] * 3)
    panel = make_panel(description=long)
    label = panel.description_label
    advance = label.fontMetrics().horizontalAdvance(long)

    assert advance + 2 * tokens.MARGIN > tokens.ABOUT_WIDTH
    assert label.width() >= advance
    assert panel.width() == pytest.approx(advance + 2 * tokens.MARGIN, abs=2)  # no slack either
    assert label.height() == label.fontMetrics().height()  # one line


def test_the_panel_has_one_fixed_size_like_the_system_panel(make_panel, icon):
    panel = make_panel(icon=icon)

    assert panel.minimumSize() == panel.maximumSize() == panel.size()


def test_the_panel_draws_and_clips_no_label(make_panel, icon):
    panel = make_panel(icon=icon)

    pixmap = panel.grab()
    assert pixmap.size() == panel.size() * pixmap.devicePixelRatio()
    for label in panel.findChildren(QLabel):
        hint = label.minimumSizeHint()
        assert label.width() >= hint.width()
        assert label.height() >= hint.height()


# --- the icon --------------------------------------------------------------------------------


def test_the_icon_is_64_points_and_named(make_panel, icon):
    label = make_panel(icon=icon).icon_label

    size = tokens.ABOUT_ICON_SIZE
    assert label.pixmap().deviceIndependentSize() == QSizeF(size, size)
    assert label.accessibleName() == "Cloudy Reader icon"


def test_without_an_icon_the_column_starts_at_the_name(make_panel):
    panel = make_panel()

    assert panel.icon_label is None
    assert panel.name_label.y() == tokens.MARGIN
    assert len(panel.findChildren(QLabel)) == 3


def test_voiceover_reads_the_icon_name_version_and_description_in_order(make_panel, icon):
    panel = make_panel(icon=icon)

    interface = QAccessible.queryAccessibleInterface(panel)
    names = [interface.child(i).text(QAccessible.Text.Name) for i in range(interface.childCount())]
    assert interface.text(QAccessible.Text.Name) == "About Cloudy Reader"
    assert names == ["Cloudy Reader icon", NAME, "Version 0.0.3", DESCRIPTION]


# --- how it closes ---------------------------------------------------------------------------


def test_the_panel_is_not_modal_and_has_no_buttons(make_panel, icon):
    panel = make_panel(icon=icon)

    assert not panel.isModal()
    assert panel.windowModality() == Qt.WindowModality.NonModal
    assert panel.findChildren(QAbstractButton) == []


@pytest.mark.parametrize("close", CLOSERS.values(), ids=CLOSERS)
def test_every_way_to_close_the_panel_ends_it_and_says_so(qtbot, make_panel, close):
    panel = make_panel()

    with qtbot.waitSignal(panel.finished, timeout=1000):
        close(qtbot, panel)

    assert not panel.isVisible()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(panel)  # deleted on close, after `finished` told its owner
