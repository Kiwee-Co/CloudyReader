"""Packaging: the release DMG window (docs-ia's spec section 7), its art and its dmgbuild call."""

from __future__ import annotations

import importlib.util
import struct
import sys
import types
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAYOUT = ROOT / "packaging" / "dmg_layout.py"


def load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("cloudyreader_dmg_layout", LAYOUT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


layout = load()


def test_black_and_white_labels_both_reach_4_5_to_1_on_the_field():
    assert layout.contrast("#000000", layout.BACKGROUND) >= 4.5
    assert layout.contrast("#FFFFFF", layout.BACKGROUND) >= 4.5
    assert layout.contrast(layout.ARROW_COLOR, layout.BACKGROUND) >= 4.5


def test_the_window_matches_spec_section_7():
    assert layout.WINDOW_RECT == ((200, 120), (640, 400))
    assert (layout.ICON_SIZE, layout.TEXT_SIZE) == (128, 13)
    assert (layout.APP_CENTER, layout.APPLICATIONS_CENTER) == ((176, 190), (464, 190))
    assert layout.ARROW == ((272, 190), (368, 190))
    assert (layout.ARROW_STROKE, layout.ARROW_HEAD) == (3.0, 12.0)
    assert (layout.BACKGROUND, layout.VOLUME_NAME) == ("#7A63D6", "Cloudy Reader")


def test_the_dmg_constants_agree_with_the_ui_tokens_once_they_exist():
    tokens = pytest.importorskip("cloudyreader.gui.tokens")
    if not hasattr(tokens, "DMG_ICON_SIZE"):
        pytest.skip("cloudyreader.gui.tokens has no DMG_* tokens yet: the UI branch adds them")
    assert tokens.DMG_ICON_SIZE == layout.ICON_SIZE
    assert tokens.DMG_TEXT_PT == layout.TEXT_SIZE
    assert str(tokens.DMG_LABEL_BAND).upper() == layout.BACKGROUND.upper()


def decode(png: bytes) -> tuple[int, int, int, bytes]:
    """Width, height, dpi and the RGB bytes, row after row, of a PNG that render() wrote."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    chunks: dict[bytes, bytes] = {}
    i = 8
    while i < len(png):
        (size,) = struct.unpack(">I", png[i : i + 4])
        kind = png[i + 4 : i + 8]
        chunks[kind] = chunks.get(kind, b"") + png[i + 8 : i + 8 + size]
        i += 12 + size
    width, height, depth, color = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (depth, color) == (8, 2)  # 8-bit RGB
    per_meter, _, _ = struct.unpack(">IIB", chunks[b"pHYs"])
    raw, stride = zlib.decompress(chunks[b"IDAT"]), 1 + 3 * width
    assert all(raw[row * stride] == 0 for row in range(height))  # filter type 0 on each row
    rgb = b"".join(raw[row * stride + 1 : (row + 1) * stride] for row in range(height))
    return width, height, round(per_meter * 0.0254), rgb


@pytest.mark.parametrize("scale", [1, 2])
def test_the_art_is_the_flat_field_and_one_white_arrow(scale):
    width, height, dpi, rgb = decode(layout.render(scale))

    assert (width, height, dpi) == (640 * scale, 400 * scale, 72 * scale)

    def at(x: float, y: float) -> str:  # the pixel under a point
        i = 3 * (int(y * scale) * width + int(x * scale))
        return rgb[i : i + 3].hex()

    field = layout.BACKGROUND.removeprefix("#").lower()
    assert {at(0, 0), at(639, 399), at(320, 180), at(176, 190), at(464, 190)} == {field}
    assert at(320, 190) == at(365, 187) == at(365, 193) == "ffffff"  # the shaft, the head
    drawn = [
        (i // 3 % width, i // 3 // width)
        for i in range(0, len(rgb), 3)
        if rgb[i : i + 3].hex() != field
    ]
    xs, ys = [x / scale for x, _ in drawn], [y / scale for _, y in drawn]
    # The arrow is the only drawing: nothing outside its strokes and their 1.5 pt round caps.
    assert 270 <= min(xs) and max(xs) <= 370 and 182 <= min(ys) and max(ys) <= 198


def test_settings_are_a_dict_with_the_spec_layout(tmp_path):
    app = tmp_path / "Cloudy Reader.app"

    found = layout.settings(app, tmp_path / "AppIcon.icns", tmp_path / "background.png")

    assert found["icon_locations"] == {"Cloudy Reader.app": (176, 190), "Applications": (464, 190)}
    assert found["symlinks"] == {"Applications": "/Applications"}
    assert (found["format"], found["filesystem"]) == ("ULFO", "APFS")
    assert found["window_rect"] == ((200, 120), (640, 400))
    assert (found["icon_size"], found["text_size"], found["label_pos"]) == (128, 13, "bottom")
    assert found["files"] == [str(app)]
    assert found["icon"] == str(tmp_path / "AppIcon.icns")
    shown = ("show_status_bar", "show_tab_view", "show_toolbar", "show_pathbar", "show_sidebar")
    assert not any(found[key] for key in shown)


def test_main_hands_dmgbuild_the_art_and_a_settings_dict_never_a_file(monkeypatch, tmp_path):
    calls = []

    def build_dmg(filename, volume_name, settings_file=None, settings=None, **kwargs):
        art = Path(settings["background"])
        both = art.is_file() and art.with_name("background@2x.png").is_file()
        calls.append((filename, volume_name, settings_file, art.name, both, settings["icon"]))

    monkeypatch.setitem(sys.modules, "dmgbuild", types.SimpleNamespace(build_dmg=build_dmg))
    dmg = tmp_path / "out.dmg"

    assert layout.main([str(tmp_path / "Cloudy Reader.app"), str(dmg), ""]) == 0
    assert calls == [(str(dmg), "Cloudy Reader", None, "background.png", True, None)]
    assert layout.main([]) == 2
