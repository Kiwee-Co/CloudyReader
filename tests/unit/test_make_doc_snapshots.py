"""scripts/make_doc_snapshots.py: the voices figure lists voices in the app's own order."""

import importlib.util
import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QPlainTextEdit, QPushButton

from cloudyreader.gui import tokens
from cloudyreader.voice_meta import voice_sort_key

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_doc_snapshots.py"


@pytest.fixture
def snapshots(monkeypatch: pytest.MonkeyPatch):
    # Importing the script changes these two for its own run; the session keeps its own values.
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    monkeypatch.setenv("QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM", "1")
    spec = importlib.util.spec_from_file_location("make_doc_snapshots", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses looks its module up in sys.modules while it builds the script's classes.
    monkeypatch.setitem(sys.modules, "make_doc_snapshots", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def env(snapshots, qapp, monkeypatch):
    """The script's live app, offscreen; what it changes for its run is put back after."""
    from cloudyreader.gui import main_window

    monkeypatch.setattr(main_window, "reduce_motion", main_window.reduce_motion)
    name, org = qapp.applicationName(), qapp.organizationName()
    yield snapshots.Env("offscreen")
    qapp.setApplicationName(name)
    qapp.setOrganizationName(org)


def test_the_voices_figure_lists_the_voices_in_the_apps_order(snapshots, tmp_path):
    voices = snapshots.real_voices(tmp_path)

    assert [v.key for v in voices] == [v.key for v in sorted(voices, key=voice_sort_key)]
    assert list(dict.fromkeys(v.engine for v in voices)) == ["kokoro", "piper"]


def test_the_engine_catalog_lists_the_engine_groups_between_kokoro_and_piper(snapshots, tmp_path):
    voices = snapshots.with_engine_rows(snapshots.real_voices(tmp_path))

    assert [v.key for v in voices] == [v.key for v in sorted(voices, key=voice_sort_key)]
    engines = list(dict.fromkeys(v.engine for v in voices))
    assert engines == ["kokoro", "chatterbox_turbo", "qwen3_tts", "piper"]


# --- drawing the 0.0.2 look ------------------------------------------------------------------


def test_text_takes_opacity_which_every_renderer_honors(snapshots):
    svg = snapshots.Svg(10, 10, "t", "d")

    svg.text(0, 0, "dimmed", fill="#000000", fill_opacity=0.25)

    assert 'opacity="0.25"' in svg.xml()
    assert "fill-opacity" not in svg.xml()


def test_a_card_is_drawn_as_its_rounded_outline_around_its_fill(snapshots, qapp):
    from cloudyreader.gui.widgets import Card

    card = Card(QPlainTextEdit())
    card.set_colors(QColor("#ffffff"), QColor(tokens.CARD_BORDER_LIGHT))
    card.resize(200, 100)
    svg = snapshots.Svg(200, 100, "t", "d")

    snapshots.Canvas(svg, snapshots.look_for(False, None), card, 0, 0).card(card)

    half = tokens.BORDER_WIDTH / 2
    assert (
        f'<rect x="{half:g}" y="{half:g}" width="{200 - 2 * half:g}" height="{100 - 2 * half:g}" '
        f'rx="{tokens.CARD_RADIUS - half:g}" fill="#ffffff" stroke-width="{tokens.BORDER_WIDTH}" '
        f'stroke="{tokens.CARD_BORDER_LIGHT}"/>'
    ) in svg.xml()


def test_voice_menu_headers_keep_their_font_color_and_gap(snapshots, qapp):
    from cloudyreader.gui.fake_service import ENGINE_FAKE_VOICES
    from cloudyreader.gui.voice_picker import VoicePicker

    picker = VoicePicker()
    picker.set_voices(ENGINE_FAKE_VOICES)
    combo = picker.combo

    items = snapshots.combo_items(combo)
    heights = snapshots.row_heights(items, combo.font())

    headers = [i for i, item in enumerate(items) if item.header is not None]
    assert [items[i].text for i in headers] == ["Piper", "Kokoro", "Chatterbox Turbo", "Qwen3-TTS"]
    assert {items[i].ink.name() for i in headers} == {tokens.TEXT_SECONDARY_LIGHT}
    assert heights[0] < snapshots.MENU_ROW  # the top header: its smaller font, no gap
    assert heights[headers[1]] == pytest.approx(heights[0] + tokens.SECTION_HEADER_GAP)
    choices = [heights[i] for i in range(len(items)) if i not in headers]
    assert set(choices) == {snapshots.MENU_ROW}


def test_the_menu_opens_with_its_current_row_over_the_button(snapshots, qapp):
    from cloudyreader.gui.fake_service import ENGINE_FAKE_VOICES
    from cloudyreader.gui.voice_picker import VoicePicker

    picker = VoicePicker()
    picker.set_voices(ENGINE_FAKE_VOICES, preferred="qwen3_tts:ryan")
    combo = picker.combo
    items, current = snapshots.combo_items(combo), combo.currentIndex()
    button = snapshots.QRectF(100, 300, 200, 20)

    menu = snapshots.menu_rect(button, items, current, combo.font())

    heights = snapshots.row_heights(items, combo.font())
    row_top = menu.top() + snapshots.MENU_PAD + sum(heights[:current])
    assert row_top + snapshots.MENU_ROW / 2 == pytest.approx(button.center().y())
    assert menu.height() == pytest.approx(2 * snapshots.MENU_PAD + sum(heights))


def test_a_disabled_button_is_dimmed_with_opacity(snapshots, qapp):
    button = QPushButton("Speak")
    button.setEnabled(False)
    button.resize(80, 32)
    svg = snapshots.Svg(80, 32, "t", "d")

    snapshots.Canvas(svg, snapshots.look_for(False, None), button, 0, 0).button(button)

    assert 'opacity="0.25">Speak</text>' in svg.xml()


def test_the_busy_strip_marks_three_parts_with_no_busy_bar(env, snapshots):
    _svg, markers = snapshots.fig_status_busy(env, env.scheme(False))

    assert [m["part"] for m in markers] == ["message", "download label", "download progress bar"]


def test_the_about_figure_draws_its_description_on_one_line(env, snapshots):
    svg = snapshots.fig_about(env, env.scheme(False), snapshots.Logo())

    assert ">Reads National Science Bowl questions aloud.</text>" in svg.xml()


def test_the_window_figure_draws_the_card_and_the_panel(env, snapshots):
    svg = snapshots.fig_window(env, env.scheme(False)).xml()

    assert f'rx="{tokens.CARD_RADIUS}" fill="{tokens.PANEL_LIGHT}"/>' in svg  # the script panel
    assert f'stroke="{tokens.CARD_BORDER_LIGHT}"/>' in svg  # the question card's outline
    assert f'fill="{tokens.TEXT_SECONDARY_LIGHT}"' in svg  # the script's secondary text


def test_the_voice_menu_figure_draws_section_headers(env, snapshots):
    svg = snapshots.fig_menu(env, env.scheme(False), "voices", top=True).xml()

    header = f'font-weight="600" fill="{tokens.TEXT_SECONDARY_LIGHT}">Kokoro</text>'
    assert header in svg
