"""Tests for scripts/make_icons.py: the four Cloudy Reader icon candidates and their .icns files."""

import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_icons.py"
NAMES = ("cloud-voice", "cloud-book", "cloud-atom", "cloud-wave")
# What `iconutil` requires, written out here on purpose: the contract, not the script's own table.
ICONSET = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}

pytestmark = pytest.mark.usefixtures("qapp")
needs_iconutil = pytest.mark.skipif(
    shutil.which("iconutil") is None, reason="iconutil is macOS-only"
)


def _load():
    # scripts/ is not a package, so import the file by path.
    spec = importlib.util.spec_from_file_location("make_icons", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_icons"] = module
    spec.loader.exec_module(module)
    return module


make_icons = _load()


@pytest.fixture(scope="module")
def built(tmp_path_factory, qapp):
    out = tmp_path_factory.mktemp("icons")
    assert make_icons.main(["--out", str(out)]) == 0
    return out


def test_design_names_are_the_four_agreed_and_unique():
    names = [d.name for d in make_icons.DESIGNS]
    assert names == list(NAMES)
    assert len(set(names)) == len(names)


def test_default_txt_names_an_existing_design_folder():
    icons = make_icons.DEFAULT_OUT
    text = (icons / "default.txt").read_text(encoding="utf-8")
    assert len(text.splitlines()) == 1
    assert text.strip() in NAMES
    assert (icons / text.strip() / "AppIcon.icns").is_file()


@needs_iconutil
@pytest.mark.parametrize("name", NAMES)
def test_design_folder_has_the_expected_files(built, name):
    folder = built / name
    assert {p.name for p in folder.iterdir()} == {
        "icon_1024.png",
        "icon_512.png",
        "AppIcon.iconset",
        "AppIcon.icns",
    }


@needs_iconutil
@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("filename, size", [("icon_1024.png", 1024), ("icon_512.png", 512)])
def test_icon_png_is_square_with_alpha_and_a_transparent_corner(built, name, filename, size):
    image = QImage(str(built / name / filename))
    assert (image.width(), image.height()) == (size, size)
    assert image.hasAlphaChannel()
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(size - 1, size - 1).alpha() == 0


@needs_iconutil
@pytest.mark.parametrize("name", NAMES)
def test_iconset_has_the_ten_required_sizes(built, name):
    iconset = built / name / "AppIcon.iconset"
    assert {p.name for p in iconset.iterdir()} == set(ICONSET)
    for filename, size in ICONSET.items():
        image = QImage(str(iconset / filename))
        assert (image.width(), image.height()) == (size, size), filename
        assert image.hasAlphaChannel(), filename


@needs_iconutil
@pytest.mark.parametrize("name", NAMES)
def test_icns_has_magic_and_declared_length(built, name):
    data = (built / name / "AppIcon.icns").read_bytes()
    assert data[:4] == b"icns"
    assert int.from_bytes(data[4:8], "big") == len(data)


@needs_iconutil
@pytest.mark.parametrize("name", NAMES)
def test_body_is_opaque_inside_and_shadow_stays_clear_of_the_canvas_edge(built, name):
    image = QImage(str(built / name / "icon_1024.png"))
    assert image.pixelColor(512, 200).alpha() == 255  # above the symbol, inside the body
    assert image.pixelColor(110, 110).alpha() < 128  # the rounded corner is cut away
    edge = 40  # the shadow reaches about 45 px below the body, 100 px from the canvas edge
    for x in range(0, 1024, 8):
        for y in [*range(0, edge, 8), *range(1024 - edge, 1024, 8)]:
            assert image.pixelColor(x, y).alpha() == 0, (x, y)
            assert image.pixelColor(y, x).alpha() == 0, (y, x)


@needs_iconutil
def test_designs_are_visibly_different(built):
    digests = {
        hashlib.sha256((built / n / "icon_1024.png").read_bytes()).hexdigest() for n in NAMES
    }
    assert len(digests) == len(NAMES)

    def hues(name):  # gradient corners, clear of every symbol, in 30-degree bands
        image = QImage(str(built / name / "icon_1024.png"))
        return tuple(image.pixelColor(x, x).hue() // 30 for x in (200, 800))

    assert len({hues(n) for n in NAMES}) == len(NAMES)


@needs_iconutil
def test_preview_sheet_is_written(built):
    sheet = QImage(str(built / "preview.png"))
    assert sheet.width() >= 4 * 256
    assert sheet.height() > 2 * 256


@needs_iconutil
def test_only_writes_one_design_and_the_preview(tmp_path):
    assert make_icons.main(["--only", "cloud-atom", "--out", str(tmp_path)]) == 0
    assert {p.name for p in tmp_path.iterdir()} == {"cloud-atom", "preview.png"}


def test_only_rejects_an_unknown_design(tmp_path):
    with pytest.raises(SystemExit) as exc:
        make_icons.main(["--only", "cloud-nine", "--out", str(tmp_path)])
    assert exc.value.code == 2


def test_missing_iconutil_is_reported_not_raised(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(make_icons.shutil, "which", lambda _name: None)
    assert make_icons.main(["--only", "cloud-voice", "--out", str(tmp_path)]) == 2
    assert "iconutil" in capsys.readouterr().err


def test_render_is_deterministic():
    design = make_icons.DESIGNS[0]
    first = bytes(make_icons.render(design, 1.0).constBits())
    assert first == bytes(make_icons.render(design, 1.0).constBits())


def test_small_sizes_use_the_heftier_drawing():
    red, blue = QColor("red"), QColor("blue")
    master, small = make_icons.blank(1024), make_icons.blank(1024)
    master.fill(red)
    small.fill(blue)
    rendered = make_icons.Rendered(master, small)
    assert rendered.at(16).pixelColor(8, 8) == blue
    assert rendered.at(32).pixelColor(16, 16) == blue
    assert rendered.at(64).pixelColor(32, 32) == red
    assert rendered.at(1024).pixelColor(512, 512) == red


def test_squircle_fills_its_rect_and_cuts_the_corners():
    rect = QRectF(100, 100, 824, 824)
    path = make_icons.squircle(rect, 185)
    box = path.boundingRect()
    assert (box.left(), box.top(), box.width(), box.height()) == pytest.approx((100, 100, 824, 824))
    assert path.contains(QPointF(512, 512))
    assert path.contains(QPointF(512, 101))  # mid-edge is on the edge
    assert not path.contains(QPointF(105, 105))  # corner is rounded off


def test_blur_samples_are_a_unit_weight_kernel():
    samples = make_icons.blur_samples(10.0)
    assert sum(w for _dx, _dy, w in samples) == pytest.approx(1.0)
    assert max((dx * dx + dy * dy) ** 0.5 for dx, dy, _w in samples) <= 26.0
