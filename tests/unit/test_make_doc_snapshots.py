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
    pytest.importorskip("cloudyreader.engine_catalog")  # 0.0.2 on
    voices = snapshots.with_engine_rows(snapshots.real_voices(tmp_path))

    assert [v.key for v in voices] == [v.key for v in sorted(voices, key=voice_sort_key)]
    engines = list(dict.fromkeys(v.engine for v in voices))
    assert engines == ["kokoro", "chatterbox_turbo", "qwen3_tts", "piper"]


def _needs_groups():
    from dataclasses import fields

    from cloudyreader.prefetch import PrefetchProgress

    if "group" not in {f.name for f in fields(PrefetchProgress)}:
        pytest.skip("this code labels the download as one whole, not per group (0.0.1)")


@pytest.mark.parametrize(
    ("words", "said"),
    [(["Piper"], "Piper"), (["A", "B"], "A and B"), (["A", "B", "C"], "A, B, and C")],
)
def test_series_lists_words_as_a_sentence_does(snapshots, words, said):
    assert snapshots.series(words) == said


def test_a_download_report_gives_the_files_group_and_its_share(snapshots):
    _needs_groups()
    import json

    lock = json.loads((snapshots.ROOT / "assets.lock.json").read_text(encoding="utf-8"))
    piper = sum(a["size"] for a in lock["assets"] if a["group"] == "voices")

    first = snapshots.download_event(4, "en_US-lessac-medium.onnx", files_done=5)
    later = snapshots.download_event(42, "af_bella.safetensors")

    assert (first.group, first.group_total_bytes) == ("voices", piper)
    assert first.group_done_bytes * 100 // first.group_total_bytes == 4
    assert first.done_bytes == first.group_done_bytes  # Piper voices come first
    assert later.group == "kokoro"
    assert later.group_done_bytes * 100 // later.group_total_bytes == 42
    assert later.done_bytes == piper + later.group_done_bytes


def test_an_engine_report_is_a_share_of_the_engine_group(snapshots):
    _needs_groups()
    from cloudyreader.engine_catalog import SPECS

    event = snapshots.engine_event()

    assert event.group == "qwen3_tts"
    assert event.group_total_bytes == sum(size for size, _ in SPECS["qwen3_tts"].expect.values())
    assert event.group_done_bytes * 100 // event.group_total_bytes == 20
    assert event.done_bytes < event.total_bytes


def test_dimmed_engine_rows_give_their_reason(snapshots):
    pytest.importorskip("cloudyreader.engine_catalog")

    rows = snapshots.engine_rows({"qwen3_tts": "not downloaded yet"})

    by_engine = {v.engine: (v.installed, v.reason) for v in rows}
    assert by_engine == {
        "chatterbox_turbo": (True, ""),
        "qwen3_tts": (False, "not downloaded yet"),
    }
    assert all(v.installed and not v.reason for v in snapshots.engine_rows())


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


def test_the_download_strip_describes_the_label_it_draws(env, snapshots):
    _needs_groups()
    import re

    xml = snapshots.fig_download_progress(env, env.scheme(False)).xml()

    drawn = re.findall(r">(Downloading [^<]+)</text>", xml)
    desc = re.search(r"<desc[^>]*>([^<]*)</desc>", xml).group(1)
    assert len(drawn) == 1
    assert drawn[0] in desc  # the description names the label the strip shows


# --- the status bar as the app draws it ------------------------------------------------------


def status_strip(snapshots, text: str, tone_name: str = "info"):
    """A light status bar with one message, drawn into a figure; returns the figure's XML."""
    from cloudyreader.gui import theme
    from cloudyreader.gui.status import StatusBar, Tone

    bar = StatusBar()
    bar.set_roles(theme.roles(theme.Appearance()))
    bar.resize(400, tokens.STATUS_LINE_HEIGHT)
    bar.show_message(text, Tone(tone_name))
    svg = snapshots.Svg(400, tokens.STATUS_LINE_HEIGHT, "t", "d")
    snapshots.Canvas(svg, snapshots.look_for(False, None), bar, 0, 0).status_bar(bar)
    return svg.xml()


def test_the_status_strip_draws_information_in_the_secondary_ink(snapshots, qapp):
    xml = status_strip(snapshots, "Stopped.")

    assert f'fill="{tokens.TEXT_SECONDARY_LIGHT}">Stopped.</text>' in xml
    assert "<circle" not in xml  # information has no glyph


@pytest.mark.parametrize(
    ("tone_name", "role"), [("warning", "TONE_WARNING_LIGHT"), ("error", "TONE_ERROR_LIGHT")]
)
def test_the_tone_glyph_is_the_apps_line_drawing_in_its_role(snapshots, qapp, tone_name, role):
    xml = status_strip(snapshots, "Some status text", tone_name)

    color = getattr(tokens, role)
    assert f'fill="none" stroke-width="{tokens.STATUS_GLYPH_STROKE:g}" stroke="{color}"' in xml
    assert f'r="{tokens.GLYPH_DOT_RADIUS:g}" fill="{color}"/>' in xml  # the exclamation mark's dot
    assert f'fill="{tokens.TEXT_SECONDARY_LIGHT}">Some status text' not in xml  # primary ink


def test_the_download_label_is_drawn_as_it_shows_in_its_ink(snapshots, qapp):
    import re

    from PySide6.QtGui import QPalette

    from cloudyreader.gui.status import ElidedLabel, download_variants

    longest, middle, shortest = download_variants("Kokoro", 42, 139 * 10**6, 330 * 10**6)
    label = ElidedLabel()
    label.set_variants(longest, middle, shortest)
    quiet = QPalette()
    quiet.setColor(QPalette.ColorRole.WindowText, QColor(tokens.TEXT_SECONDARY_LIGHT))
    label.setPalette(quiet)
    label.resize(label.fontMetrics().horizontalAdvance(longest) - 1, 20)  # the sizes no longer fit
    svg = snapshots.Svg(label.width(), 20, "t", "d")

    snapshots.Canvas(svg, snapshots.look_for(False, None), label, 0, 0).label(label)

    drawn = re.findall(r'fill="([^"]+)"[^>]*>([^<]+)</text>', svg.xml())
    assert drawn == [(tokens.TEXT_SECONDARY_LIGHT, middle)]
