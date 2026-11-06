"""Every GUI color, size, spacing, and timing comes from tokens.py: no raw literal elsewhere."""

import ast
import re
from pathlib import Path

import pytest

from cloudyreader.gui import tokens

GUI = Path(tokens.__file__).parent
HEX_COLOR = re.compile(r"#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
# Calls whose numbers are sizes, spacing, geometry, font sizes, colors, or milliseconds.
SIZED = frozenset(
    {
        "QColor",
        "QMargins",
        "QMarginsF",
        "QPen",
        "QPoint",
        "QPointF",
        "QRect",
        "QRectF",
        "QSize",
        "QSizeF",
        "addRoundedRect",
        "addSpacing",
        "adjusted",
        "darker",
        "drawRoundedRect",
        "fromHsl",
        "fromHsv",
        "fromRgb",
        "fromRgbF",
        "lighter",
        "move",
        "resize",
        "setAlpha",
        "setAlphaF",
        "setContentsMargins",
        "setDocumentMargin",
        "setFixedHeight",
        "setFixedSize",
        "setFixedWidth",
        "setGeometry",
        "setHeight",
        "setHorizontalSpacing",
        "setIconSize",
        "setInterval",
        "setMaximumHeight",
        "setMaximumSize",
        "setMaximumWidth",
        "setMinimumHeight",
        "setMinimumSize",
        "setMinimumWidth",
        "setPixelSize",
        "setPointSize",
        "setPointSizeF",
        "setRgb",
        "setRgbF",
        "setSpacing",
        "setVerticalSpacing",
        "setWidth",
        "setWidthF",
        "singleShot",
        "start",
        "translated",
    }
)


def call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def numbers(arg: ast.expr) -> list[float]:
    """The literal numbers an argument spells directly: 96, -1.5, or (4, 8) unpacked."""
    if isinstance(arg, ast.Starred):
        return numbers(arg.value)
    if isinstance(arg, ast.Tuple | ast.List):
        return [n for item in arg.elts for n in numbers(item)]
    if isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
        return [-n for n in numbers(arg.operand)]
    is_number = isinstance(arg, ast.Constant) and isinstance(arg.value, int | float)
    return [arg.value] if is_number and not isinstance(arg.value, bool) else []


def raw_literals(path: Path) -> list[str]:
    """Hex colors in strings, and nonzero numbers passed straight to a sized call."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found += [f"{path.name}:{node.lineno}: {m}" for m in HEX_COLOR.findall(node.value)]
        elif isinstance(node, ast.Call) and (name := call_name(node.func)) in SIZED:
            args = [*node.args, *(keyword.value for keyword in node.keywords)]
            values = [n for arg in args for n in numbers(arg) if n != 0]
            found += [f"{path.name}:{node.lineno}: {n:g} in {name}()" for n in values]
    return found


def test_a_planted_hex_color_is_caught(tmp_path):
    planted = tmp_path / "planted.py"
    planted.write_text('from PySide6.QtGui import QColor\n\nINK = QColor("#1d1d1f")\n')

    assert raw_literals(planted) == ["planted.py:3: #1d1d1f"]


def test_a_planted_size_and_timing_are_caught_and_zero_is_not(tmp_path):
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def build(bar, layout, timer):\n"
        "    bar.setFixedWidth(96)\n"
        "    layout.setContentsMargins(0, 0, 0, 0)\n"
        "    layout.setSpacing(*(12,))\n"
        "    timer.setInterval(interval_ms=150)\n"
        "    bar.resize(-1.5, 0)\n"
    )

    assert raw_literals(planted) == [
        "planted.py:2: 96 in setFixedWidth()",
        "planted.py:4: 12 in setSpacing()",
        "planted.py:5: 150 in setInterval()",
        "planted.py:6: -1.5 in resize()",
    ]


@pytest.mark.parametrize(
    "path",
    sorted(p for p in GUI.glob("*.py") if p.name != "tokens.py"),
    ids=lambda p: p.name,
)
def test_no_gui_module_holds_a_raw_color_or_size(path):
    assert raw_literals(path) == []


def test_tokens_import_nothing_so_packaging_can_read_them_without_qt():
    tree = ast.parse((GUI / "tokens.py").read_text(encoding="utf-8"))

    assert [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)] == []
