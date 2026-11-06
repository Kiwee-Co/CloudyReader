"""Docs templates keep valid Liquid: Prettier once split an if tag and wrapped a string.

Prettier does not parse Liquid. In 13d572f it turned `{% if item.url == page.url %}` into
`{% if item.url="" ="page.url" %}` (nav.html) and put a line break inside the string literals of
`remove: "<p>"` (figure.html). Neither stops the build, so the site checker never noticed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
FILES = sorted(
    {
        *DOCS.glob("_includes/*.html"),
        *DOCS.glob("_layouts/*.html"),
        DOCS / "404.html",
        *DOCS.rglob("*.md"),
    }
)

TAG = re.compile(r"\{%-?(?P<tag>.*?)-?%\}|\{\{-?(?P<out>.*?)-?\}\}", re.S)
CONDITION_TAG = re.compile(r"\s*(?:if|elsif|unless)\s+(?P<body>.*?)\s*\Z", re.S)
LITERAL = re.compile(r"\"[^\"]*\"|'[^']*'")

_OPERAND = r"(?:S|[\w.\[\]-]+)"  # S stands for a string literal
_COMPARE = r"(?:\s*(?:==|!=|<>|<=|>=|<|>)\s*|\s+contains\s+)"
_TERM = rf"{_OPERAND}(?:{_COMPARE}{_OPERAND})?"
CONDITION = re.compile(rf"{_TERM}(?:\s+(?:and|or)\s+{_TERM})*")


def _tags(path: Path) -> list[tuple[int, str, str]]:
    """(line, kind, body) of every Liquid tag in the file; kind is "tag" or "out"."""
    text = path.read_text(encoding="utf-8")
    found = []
    for match in TAG.finditer(text):
        kind = "tag" if match.group("tag") is not None else "out"
        body = match.group("tag") if kind == "tag" else match.group("out")
        found.append((text.count("\n", 0, match.start()) + 1, kind, body))
    return found


def _ids(paths: list[Path]) -> list[str]:
    return [p.relative_to(ROOT).as_posix() for p in paths]


def test_the_docs_carry_liquid_to_check() -> None:
    assert sum(len(_tags(path)) for path in FILES) > 50


@pytest.mark.parametrize("path", FILES, ids=_ids(FILES))
def test_no_liquid_string_spans_a_line_break(path: Path) -> None:
    broken = [
        f"line {line}: {body.strip()!r}"
        for line, _kind, body in _tags(path)
        for literal in LITERAL.findall(body)
        if "\n" in literal
    ]

    assert not broken


@pytest.mark.parametrize("path", FILES, ids=_ids(FILES))
def test_every_if_condition_is_a_comparison_liquid_can_parse(path: Path) -> None:
    bad = []
    for line, kind, body in _tags(path):
        head = CONDITION_TAG.match(body) if kind == "tag" else None
        if head is None:
            continue
        skeleton = LITERAL.sub("S", head.group("body"))
        if CONDITION.fullmatch(skeleton) is None:
            bad.append(f"line {line}: {body.strip()!r}")

    assert not bad


def test_the_checks_catch_what_prettier_did(tmp_path: Path) -> None:
    mangled = tmp_path / "nav.html"
    mangled.write_text('<a {% if item.url="" ="page.url" %}x{% endif %}>', encoding="utf-8")
    split = tmp_path / "figure.html"
    split.write_text('{{ c | remove: "\n    <p>" | strip }}', encoding="utf-8")
    fine = tmp_path / "ok.html"
    fine.write_text("{% if item.url == page.url and a != 'b' %}x{% endif %}", encoding="utf-8")

    def condition_bad(path: Path) -> bool:
        for _line, kind, body in _tags(path):
            head = CONDITION_TAG.match(body) if kind == "tag" else None
            if head and CONDITION.fullmatch(LITERAL.sub("S", head.group("body"))) is None:
                return True
        return False

    def literal_broken(path: Path) -> bool:
        return any("\n" in lit for _l, _k, body in _tags(path) for lit in LITERAL.findall(body))

    assert condition_bad(mangled) and not condition_bad(fine)
    assert literal_broken(split) and not literal_broken(fine)
