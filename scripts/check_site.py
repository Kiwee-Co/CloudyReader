"""Check the GitHub Pages source in docs/ before Jekyll builds it. Standard library only.

It reads the source tree, not a build, so it runs where Jekyll is missing: in CI before
actions/jekyll-build-pages, and on a laptop. It checks that:
- front matter parses (a strict YAML subset: block mappings and lists, scalars, flow lists);
- every page has a title and exactly one h1, counting the h1 its layouts print;
- nav_order is an integer, unique within its nav_group, and the group is in nav_groups;
- every internal link and asset resolves to a file of the site: relative_url and absolute_url
  literals, Markdown links and images, HTML src and href, include and link tags;
- no link hard-codes the base path or the site's host, and templates link through relative_url;
- every img element and every figure include has alt text;
- no page loads a resource from another origin (link, script, img, source, and the like).

Usage: python3 scripts/check_site.py [DOCS_DIR]  (default: the docs/ folder beside scripts/)
Exit 0 when clean, 1 with one "path:line: problem" line each, 2 when DOCS_DIR is missing.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import string
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit

# --- front matter: a strict subset of YAML --------------------------------------------------


class YamlError(ValueError):
    """YAML outside the supported subset, or YAML that Jekyll's loader rejects."""

    def __init__(self, line: int, message: str) -> None:
        super().__init__(message)
        self.line = line


class _Unterminated(Exception):
    """A quoted scalar that does not close within the text given."""


_BOOLEANS = {"true": True, "yes": True, "on": True, "false": False, "no": False, "off": False}
_INT = re.compile(r"[-+]?(?:0|[1-9][0-9_]*)")
_FLOAT = re.compile(r"[-+]?(?:[0-9][0-9_]*)?\.[0-9]+(?:[eE][-+]?[0-9]+)?")
_ESCAPES = {
    "0": "\0",
    "a": "\a",
    "b": "\b",
    "t": "\t",
    "\t": "\t",
    "n": "\n",
    "v": "\v",
    "f": "\f",
    "r": "\r",
    "e": "\x1b",
    " ": " ",
    '"': '"',
    "/": "/",
    "\\": "\\",
    "N": "\x85",
    "_": "\xa0",
    "L": "\u2028",
    "P": "\u2029",
}
_HEX_ESCAPES = {"x": 2, "u": 4, "U": 8}
_KEY_END = re.compile(r":(?:[ \t]|$)")
_COMMENT = re.compile(r"[ \t]#")
_BLOCK_HEADER = re.compile(r"([|>])([1-9]?)([-+]?)([1-9]?)[ \t]*(?:#.*)?")


def _scalar(text: str) -> object:
    """A plain scalar resolved as Ruby's YAML 1.1 loader does for the common types."""
    lowered = text.lower()
    if lowered in ("", "~", "null"):
        return None
    if lowered in _BOOLEANS:
        return _BOOLEANS[lowered]
    if _INT.fullmatch(text):
        return int(text.replace("_", ""))
    if _FLOAT.fullmatch(text):
        return float(text.replace("_", ""))
    return text


def _plain(text: str, line: int) -> object:
    match = _COMMENT.search(text)
    text = (text[: match.start()] if match else text).rstrip()
    if text[:1] in tuple("]}#%@`,") or text.startswith("- "):
        raise YamlError(line, f"a value cannot start with {text[0]!r}; quote it")
    if _KEY_END.search(text):
        raise YamlError(line, "a ': ' inside a value needs quotes")
    return _scalar(text)


def _quoted(text: str, start: int, line: int) -> tuple[str, int]:
    """The quoted scalar at text[start] and the index after its closing quote."""
    quote, out, i = text[start], [], start + 1
    while i < len(text):
        char = text[i]
        if quote == "'":
            if char == "'":
                if text[i + 1 : i + 2] != "'":
                    return "".join(out), i + 1
                i += 1
            out.append(char)
            i += 1
            continue
        if char == '"':
            return "".join(out), i + 1
        if char != "\\":
            out.append(char)
            i += 1
            continue
        code = text[i + 1 : i + 2]
        if code in _ESCAPES:
            out.append(_ESCAPES[code])
            i += 2
            continue
        width = _HEX_ESCAPES.get(code, 0)
        digits = text[i + 2 : i + 2 + width]
        if not width or len(digits) != width or any(c not in string.hexdigits for c in digits):
            raise YamlError(line, f"unknown escape \\{code} in a double-quoted value")
        out.append(chr(int(digits, 16)))
        i += 2 + width
    raise _Unterminated


def _is_item(text: str) -> bool:
    return text == "-" or text.startswith(("- ", "-\t"))


def _starts_mapping(text: str) -> bool:
    """True when a list item's text is 'key: value', so the item is a mapping."""
    if text[0] in "[{|>&*!":
        return False
    if text[0] in "\"'":
        try:
            _, end = _quoted(text, 0, 0)
        except (_Unterminated, YamlError):
            return False
        rest = text[end:].lstrip(" \t")
        return rest.startswith(":") and rest[1:2] in ("", " ", "\t")
    match = _KEY_END.search(text)
    return match is not None and not _COMMENT.search(text[: match.start()])


def _fold(lines: list[str]) -> str:
    """Folded block scalar body: a line break becomes a space, an empty line a newline."""
    out: list[str] = []
    for line in lines:
        if not line:
            out.append("\n")
        elif out and out[-1] != "\n":
            out.append(" " + line)
        else:
            out.append(line)
    return "".join(out)


class _FlowReader:
    """A single-line flow list or mapping: [a, "b"] or {key: value}."""

    def __init__(self, text: str, line: int) -> None:
        self._text = text
        self._line = line
        self.pos = 0

    def node(self) -> object:
        self._skip()
        char = self._peek()
        if char == "[":
            return self._sequence()
        if char == "{":
            return self._mapping()
        if char in ("'", '"'):
            try:
                value, self.pos = _quoted(self._text, self.pos, self._line)
            except _Unterminated:
                raise YamlError(self._line, "a quoted value never closes") from None
            return value
        start = self.pos
        while self._peek() not in ("", ",", "]", "}") and not self._at_colon():
            self.pos += 1
        return _scalar(self._text[start : self.pos].strip())

    def _sequence(self) -> list[object]:
        self.pos += 1
        items: list[object] = []
        while True:
            self._skip()
            if self._peek() == "]":
                self.pos += 1
                return items
            items.append(self.node())
            self._separator("]")

    def _mapping(self) -> dict[str, object]:
        self.pos += 1
        result: dict[str, object] = {}
        while True:
            self._skip()
            if self._peek() == "}":
                self.pos += 1
                return result
            key = self.node()
            self._skip()
            if not self._at_colon():
                raise YamlError(self._line, "expected key: value in a flow mapping")
            self.pos += 1
            result[str(key)] = self.node()
            self._separator("}")

    def _separator(self, close: str) -> None:
        self._skip()
        char = self._peek()
        if char == ",":
            self.pos += 1
        elif char != close:
            raise YamlError(self._line, f"expected ',' or '{close}': flow lists close on one line")

    def _at_colon(self) -> bool:
        return self._peek() == ":" and self._text[self.pos + 1 : self.pos + 2] in ("", " ", "\t")

    def _peek(self) -> str:
        return self._text[self.pos : self.pos + 1]

    def _skip(self) -> None:
        while self._peek() in (" ", "\t"):
            self.pos += 1


class _YamlParser:
    """Block mappings and lists; plain, quoted, folded, and literal scalars; flow lists."""

    def __init__(self, text: str, first_line: int) -> None:
        self._lines = text.split("\n")
        self._first = first_line
        self._pos = 0

    def parse(self) -> dict[str, object]:
        start = self._next_content()
        if start is None:
            return {}
        if _is_item(start[1]):
            raise YamlError(self._number(), "expected key: value pairs, not a list")
        value = self._mapping(start[0])
        if self._next_content() is not None:
            raise YamlError(self._number(), "this line is indented less than the first key")
        return value

    def _number(self) -> int:
        return self._first + self._pos

    def _next_content(self) -> tuple[int, str] | None:
        """(indent, text) of the next line that is not blank or a comment; not consumed."""
        while self._pos < len(self._lines):
            raw = self._lines[self._pos]
            stripped = raw.strip()
            if stripped and not stripped.startswith("#"):
                body = raw.lstrip(" ")
                if body.startswith("\t"):
                    raise YamlError(self._number(), "a tab in the indentation; use spaces")
                return len(raw) - len(body), body.rstrip()
            self._pos += 1
        return None

    def _mapping(self, indent: int) -> dict[str, object]:
        result: dict[str, object] = {}
        while (line := self._next_content()) is not None:
            column, text = line
            if column < indent:
                break
            if column > indent:
                raise YamlError(self._number(), "unexpected indentation")
            if _is_item(text):
                raise YamlError(self._number(), "a list item where a key was expected")
            key, rest = self._key(text)
            if key in result:
                raise YamlError(self._number(), f"duplicate key {key!r}")
            number = self._number()
            self._pos += 1
            result[key] = self._value(rest, indent, number)
        return result

    def _list(self, indent: int) -> list[object]:
        items: list[object] = []
        while (line := self._next_content()) is not None:
            column, text = line
            if column < indent or (column == indent and not _is_item(text)):
                break
            if column > indent:
                raise YamlError(self._number(), "unexpected indentation")
            content = text[1:].lstrip(" \t")
            if content and not content.startswith("#") and _starts_mapping(content):
                # "- key: value" opens a mapping whose keys line up with "key".
                inner = column + len(text) - len(content)
                self._lines[self._pos] = " " * inner + content
                items.append(self._mapping(inner))
                continue
            number = self._number()
            self._pos += 1
            items.append(self._value(content, column, number))
        return items

    def _key(self, text: str) -> tuple[str, str]:
        number = self._number()
        if text[0] in ("'", '"'):
            try:
                key, end = _quoted(text, 0, number)
            except _Unterminated:
                raise YamlError(number, "a quoted key never closes") from None
            rest = text[end:].lstrip(" \t")
            if not rest.startswith(":") or rest[1:2] not in ("", " ", "\t"):
                raise YamlError(number, "expected key: value")
            return key, rest[1:].strip()
        match = _KEY_END.search(text)
        if match is None or match.start() == 0:
            raise YamlError(number, "expected key: value")
        key = text[: match.start()].rstrip()
        if _COMMENT.search(key) or key[0] in "[]{}#&*!|>%@`,?":
            raise YamlError(number, f"unsupported key {key!r}")
        return key, text[match.end() :].strip()

    def _value(self, rest: str, indent: int, number: int) -> object:
        if not rest or rest.startswith("#"):
            line = self._next_content()
            if line is not None:
                column, text = line
                if column > indent:
                    return self._list(column) if _is_item(text) else self._mapping(column)
                if column == indent and _is_item(text):
                    return self._list(column)
            return None
        head = rest[0]
        if head in "|>":
            return self._block_scalar(rest, indent, number)
        if head in ("'", '"'):
            return self._quoted_value(rest, number)
        if head in "[{":
            reader = _FlowReader(rest, number)
            value = reader.node()
            tail = rest[reader.pos :].strip()
            if tail and not tail.startswith("#"):
                raise YamlError(number, "text after a flow list")
            return value
        if head in "&*!":
            raise YamlError(number, "anchors, aliases, and tags are not supported")
        return _plain(rest, number)

    def _quoted_value(self, rest: str, number: int) -> str:
        text = rest
        while True:
            try:
                value, end = _quoted(text, 0, number)
            except _Unterminated:
                if self._pos >= len(self._lines):
                    raise YamlError(number, "a quoted value never closes") from None
                more = self._lines[self._pos].strip()
                self._pos += 1
                text += "\n" if not more else more if text.endswith("\n") else " " + more
                continue
            tail = text[end:].strip()
            if tail and not tail.startswith("#"):
                raise YamlError(number, "text after a quoted value")
            return value

    def _block_scalar(self, header: str, indent: int, number: int) -> str:
        match = _BLOCK_HEADER.fullmatch(header)
        if match is None:
            raise YamlError(number, f"bad block scalar header {header!r}")
        style, digit_before, chomp, digit_after = match.groups()
        digit = digit_before or digit_after
        block_indent = indent + int(digit) if digit else None
        lines: list[str] = []
        while self._pos < len(self._lines):
            raw = self._lines[self._pos]
            if not raw.strip():
                lines.append("")
                self._pos += 1
                continue
            column = len(raw) - len(raw.lstrip(" "))
            if block_indent is None:
                block_indent = column
            if column < block_indent or column <= indent:
                break
            lines.append(raw[block_indent:])
            self._pos += 1
        trailing = 0
        while lines and not lines[-1]:
            lines.pop()
            trailing += 1
        if not lines:
            return ""
        body = "\n".join(lines) if style == "|" else _fold(lines)
        if chomp == "-":
            return body
        return body + "\n" * (trailing + 1 if chomp == "+" else 1)


def parse_yaml(text: str, first_line: int = 1) -> dict[str, object]:
    """Parse a YAML mapping; raise YamlError with a line number outside the subset."""
    return _YamlParser(text.replace("\r\n", "\n"), first_line).parse()


# --- the site --------------------------------------------------------------------------------

_MARKDOWN = frozenset({".md", ".markdown", ".mkd", ".mkdn"})
_HTML = frozenset({".html", ".htm"})
_CONVERTED = {".scss": ".css", ".sass": ".css", ".coffee": ".js"}  # what Jekyll outputs instead
_ALWAYS_EXCLUDED = (
    "_site",
    ".jekyll-cache",
    ".sass-cache",
    "node_modules",
    "vendor",
    "Gemfile",
    "Gemfile.lock",
)
_ALLOWED_PLUGINS = frozenset({"jekyll-seo-tag", "jekyll-sitemap"})
_GENERATED = {"jekyll-sitemap": "/sitemap.xml"}
# What a GitHub Pages theme adds to the site: layouts (with the h1 elements they print) and files.
# jekyll-theme-architect 0.2.0: its default layout's header h1 is the site title, not counted.
_THEME_LAYOUTS = {"jekyll-theme-architect": {"default": 0}}
_THEME_FILES = {
    "jekyll-theme-architect": (
        "/assets/css/style.css",
        "/assets/css/print.css",
        "/assets/images/body-bg.jpg",
        "/assets/images/download-button.png",
        "/assets/images/github-button.png",
        "/assets/images/header-bg.jpg",
        "/assets/images/highlight-bg.jpg",
        "/assets/images/sidebar-bg.jpg",
    )
}
# The project site and the planned custom domain: links to them must go through relative_url.
_PAGES_HOST, _PAGES_PATH = "kiwee-co.github.io", "/cloudyreader"
_CUSTOM_HOSTS = frozenset({"cloudyreader.com", "www.cloudyreader.com"})
_FRONT_MATTER = re.compile(r"\A---[ \t]*\n(.*?\n)?(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.S)
_MASK = "\x1a"
_EXTERNAL = re.compile(r"(?:[a-z][a-z0-9+.-]*:)?//", re.I)
_RESOURCE_ATTRS = {
    "script": ("src",),
    "img": ("src", "srcset"),
    "source": ("src", "srcset"),
    "iframe": ("src",),
    "embed": ("src",),
    "object": ("data",),
    "video": ("src", "poster"),
    "audio": ("src",),
    "track": ("src",),
    "input": ("src",),
    "image": ("href", "xlink:href"),
    "use": ("href", "xlink:href"),
}
_LOADING_RELS = frozenset(
    {"stylesheet", "icon", "apple-touch-icon", "mask-icon", "manifest", "preload"}
    | {"modulepreload", "prefetch", "preconnect", "dns-prefetch", "prerender"}
)
_LIQUID_URL = re.compile(
    r"\{\{-?\s*(['\"])(?P<path>[^'\"]*)\1\s*\|\s*(?:relative_url|absolute_url)\b[^}]*\}\}"
)
_BASEURL = re.compile(r"\{\{-?\s*site\.baseurl\s*-?\}\}(?P<path>/[^\s\"'<>)]*)")
_INCLUDE = re.compile(r"\{%-?\s*include\s+(?P<name>[\w./-]+)(?P<params>.*?)-?%\}", re.S)
_PARAM = re.compile(r"(?P<key>\w+)\s*=\s*(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'|(?P<var>\S+))")
_LINK_TAG = re.compile(r"(?P<base>\{\{-?\s*site\.baseurl\s*-?\}\})?\{%-?\s*link\s+(?P<path>\S+)")
_LIQUID = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
_LIQUID_BLOCKS = re.compile(
    r"\{%-?\s*(?P<tag>comment|raw)\s*-?%\}.*?\{%-?\s*end(?P=tag)\s*-?%\}", re.S
)
_MD_LINK = re.compile(
    r"(?P<bang>!?)\[(?P<text>(?:[^\[\]\n]|\[[^\]\n]*\])*)\]"
    r"\(\s*(?P<url><[^>\n]*>|[^\s)]+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
_MD_REFERENCE = re.compile(r"^ {0,3}\[[^\]]+\]:[ \t]*(?P<url><[^>\n]*>|\S+)", re.M)
_AUTOLINK = re.compile(r"<(?P<url>https?://[^>\s]+)>")
_FENCE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(?<!`)(?P<ticks>`+)(?!`).+?(?<!`)(?P=ticks)(?!`)")
_ATX_H1 = re.compile(r"^ {0,3}#(?:[ \t]+|$)", re.M)
_SETEXT_H1 = re.compile(r"^ {0,3}=+[ \t]*$")
_CSS_URL = re.compile(
    r"url\(\s*(['\"]?)(?P<url>[^'\")]*)\1\s*\)|@import\s+(['\"])(?P<imp>[^'\"]+)\3"
)
_DECORATIVE = ("presentation", "none")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SVG_ROOT = re.compile(r"<svg\b[^>]*>", re.I)
_SVG_ATTR = re.compile(r"(?P<name>[\w:-]+)\s*=\s*[\"'](?P<value>[^\"']*)[\"']")


@dataclass
class Problem:
    path: Path
    line: int
    message: str


@dataclass
class Source:
    """One file of the docs tree that Jekyll renders, or a layout or include."""

    path: Path
    rel: str  # POSIX path under the docs root
    front: dict[str, object] | None
    body: str
    body_line: int  # line number of the first body line
    url: str = ""  # the URL it is served at; empty for layouts and includes
    front_ok: bool = True  # False when the front matter did not parse

    @property
    def markdown(self) -> bool:
        return PurePosixPath(self.rel).suffix in _MARKDOWN

    @property
    def html_output(self) -> bool:
        return self.markdown or PurePosixPath(self.rel).suffix in _HTML


@dataclass
class Site:
    root: Path
    config: dict[str, object]
    pages: list[Source] = field(default_factory=list)
    layouts: dict[str, Source] = field(default_factory=dict)
    includes: dict[str, Source] = field(default_factory=dict)
    styles: list[Path] = field(default_factory=list)
    served: set[str] = field(default_factory=set)
    theme_layouts: dict[str, int] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)

    def report(self, path: Path, line: int, message: str) -> None:
        self.problems.append(Problem(path, line, message))

    def resolves(self, url_path: str) -> bool:
        """True when a site path such as /manual/voices/ names a page or a file."""
        path = unquote(url_path.split("#", 1)[0].split("?", 1)[0])
        if not path:
            return True
        if not path.startswith("/"):
            path = "/" + path
        candidates = {path}
        if path.endswith("/"):
            candidates.add(path + "index.html")
        else:
            candidates |= {path + "/", path + ".html", path + "/index.html"}
        return not candidates.isdisjoint(self.served)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _ignored(rel: str, config: dict[str, object]) -> bool:
    """True for paths Jekyll never reads: excluded, hidden, or underscored (bar templates)."""
    parts = rel.split("/")
    if parts[0] in ("_layouts", "_includes") and len(parts) > 1:
        return False
    included = _strings(config.get("include"))
    if any(rel == item or rel.startswith(item.rstrip("/") + "/") for item in included):
        return False
    if any(part[:1] in "._#" or part.endswith("~") for part in parts):
        return True
    for pattern in (*_ALWAYS_EXCLUDED, *_strings(config.get("exclude"))):
        stem = pattern.strip("/")
        if rel == stem or rel.startswith(stem + "/") or fnmatch.fnmatch(rel, pattern):
            return True
    return False


def _files(root: Path) -> Iterator[Path]:
    for folder, dirs, names in os.walk(root):
        dirs.sort()
        for name in sorted(names):
            yield Path(folder) / name


def _page_url(rel: str, front: dict[str, object] | None, style: str) -> str:
    path = PurePosixPath(rel)
    suffix = path.suffix
    output = ".html" if suffix in _MARKDOWN else _CONVERTED.get(suffix, suffix)
    folder = "" if str(path.parent) == "." else f"/{path.parent}"
    permalink = front.get("permalink") if front else None
    if isinstance(permalink, str) and permalink:
        url = permalink.replace(":path", folder.lstrip("/")).replace(":basename", path.stem)
        url = url.replace(":output_ext", output)
        return url if url.startswith("/") else "/" + url
    if path.stem == "index" and output == ".html":
        return f"{folder}/"
    if style == "pretty" and output == ".html":
        return f"{folder}/{path.stem}/"
    return f"{folder}/{path.stem}{output}"


def _split_front_matter(text: str) -> tuple[str | None, str, int]:
    """(front matter text or None, body, line number of the body's first line)."""
    match = _FRONT_MATTER.match(text)
    if match is None:
        return None, text, 1
    return match.group(1) or "", text[match.end() :], match.group(0).count("\n") + 1


def load_site(root: Path) -> Site:
    config_path = root / "_config.yml"
    site = Site(root, {})
    if config_path.is_file():
        try:
            site.config = parse_yaml(config_path.read_text(encoding="utf-8"))
        except YamlError as exc:
            site.report(config_path, exc.line, f"_config.yml does not parse: {exc}")
    style = site.config.get("permalink")
    style = style if isinstance(style, str) else "date"
    plugins = _strings(site.config.get("plugins"))
    site.served |= {url for plugin, url in _GENERATED.items() if plugin in plugins}
    theme = site.config.get("theme")
    if isinstance(theme, str):
        site.served |= set(_THEME_FILES.get(theme, ()))
        site.theme_layouts = dict(_THEME_LAYOUTS.get(theme, {}))
    for path in _files(root):
        rel = path.relative_to(root).as_posix()
        if rel == "_config.yml" or _ignored(rel, site.config):
            continue
        with path.open("rb") as handle:
            head = handle.read(3)
        template = rel.startswith(("_layouts/", "_includes/"))
        if head != b"---" and not template and path.suffix not in _MARKDOWN:
            site.served.add("/" + rel)
            if path.suffix in (".css", ".scss"):
                site.styles.append(path)
            continue
        try:
            text = path.read_text(encoding="utf-8").lstrip("\ufeff").replace("\r\n", "\n")
        except UnicodeDecodeError:
            site.report(path, 1, "not UTF-8 text")
            continue
        front_text, body, body_line = _split_front_matter(text)
        front: dict[str, object] | None = None
        front_ok = True
        if front_text is not None:
            try:
                front = parse_yaml(front_text, first_line=2)
            except YamlError as exc:
                site.report(path, exc.line, f"front matter does not parse: {exc}")
                front, front_ok = {}, False
        source = Source(path, rel, front, body, body_line, front_ok=front_ok)
        if rel.startswith("_layouts/"):
            site.layouts[PurePosixPath(rel).stem] = source
        elif rel.startswith("_includes/"):
            site.includes[rel.removeprefix("_includes/")] = source
        else:
            source.url = _page_url(rel, front, style)
            site.pages.append(source)
            site.served.add(source.url)
            if source.url.endswith("/"):
                site.served.add(source.url + "index.html")
            if source.url.endswith(".html"):
                site.served.add(source.url.removesuffix(".html"))
            if path.suffix in (".css", ".scss"):
                site.styles.append(path)
    return site


# --- reading templates and pages ------------------------------------------------------------


def _blank(text: str, start: int, end: int) -> str:
    """text with [start, end) replaced by spaces, newlines kept, so positions stay put."""
    return text[:start] + re.sub(r"[^\n]", " ", text[start:end]) + text[end:]


def _code_spans(text: str) -> list[tuple[int, int]]:
    """Fenced code blocks and inline code spans of Markdown text, as [start, end) offsets."""
    spans: list[tuple[int, int]] = []
    offset, fence, fence_start = 0, "", 0
    for line in text.splitlines(keepends=True):
        match = _FENCE.match(line)
        if fence:
            closing = match is not None and match["fence"][0] == fence[0]
            if closing and len(match["fence"]) >= len(fence) and not line.strip(" \n`~"):
                spans.append((fence_start, offset + len(line)))
                fence = ""
        elif match is not None:
            fence, fence_start = match["fence"], offset
        else:
            spans += [(offset + m.start(), offset + m.end()) for m in _CODE_SPAN.finditer(line)]
        offset += len(line)
    if fence:
        spans.append((fence_start, len(text)))
    return spans


def _line_of(source: Source, text: str, index: int) -> int:
    return source.body_line + text.count("\n", 0, index)


class _Tags(HTMLParser):
    """Start tags with their attributes and line numbers."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, dict[str, str], int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value if value is not None else "" for name, value in attrs}
        self.found.append((tag, values, self.getpos()[0]))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def _tags(masked: str) -> list[tuple[str, dict[str, str], int]]:
    parser = _Tags()
    parser.feed(masked)
    parser.close()
    return parser.found


@dataclass
class _Scan:
    """A file's text prepared for checks: Liquid comments, raw blocks, and code blanked."""

    plain: str  # Liquid still present, for Liquid reference checks
    masked: str  # Liquid replaced by _MASK, for HTML and Markdown checks


def _prepare(site: Site, source: Source) -> _Scan:
    text = source.body
    raw_blocks = [(m.start(), m.end()) for m in _LIQUID_BLOCKS.finditer(text)]
    if source.markdown:
        for start, end in _code_spans(text):
            inside_raw = any(a <= start and end <= b for a, b in raw_blocks)
            code = text[start:end]
            if not inside_raw and ("{{" in code or "{%" in code):
                line = _line_of(source, text, start)
                site.report(source.path, line, "Liquid inside code runs; wrap it in raw tags")
            text = _blank(text, start, end)
    for start, end in raw_blocks:
        text = _blank(text, start, end)
    masked = _LIQUID.sub(lambda m: re.sub(r"[^\n]", _MASK, m.group()), text)
    return _Scan(text, masked)


# --- checks -----------------------------------------------------------------------------------


def _site_url(url: str) -> bool:
    parts = urlsplit(url if "://" in url else "https:" + url)
    host = (parts.hostname or "").lower()
    path = parts.path.lower()
    return host in _CUSTOM_HOSTS or (
        host == _PAGES_HOST and (path == _PAGES_PATH or path.startswith(_PAGES_PATH + "/"))
    )


def _check_url(site: Site, source: Source, url: str, line: int, *, resource: bool) -> None:
    """One literal URL from a src, href, or Markdown link of a page or template."""
    url = url.strip().removeprefix("<").removesuffix(">")
    if not url or url.startswith("#") or _MASK in url:
        return
    template = not source.url
    if _EXTERNAL.match(url):
        if resource:
            site.report(source.path, line, f"loads {url} from another origin")
        elif url.lower().startswith(("http:", "https:", "//")) and _site_url(url):
            site.report(source.path, line, f"{url} hard-codes the site address; use relative_url")
        return
    scheme = urlsplit(url).scheme.lower()
    if scheme in ("mailto", "tel") and not resource:
        return
    if scheme == "data" and resource:
        return
    if scheme:
        site.report(source.path, line, f"unsupported URL scheme in {url}")
    elif url.startswith("/"):
        site.report(source.path, line, f"{url} skips the base path; use relative_url")
    elif template:
        site.report(source.path, line, f"{url} is relative in a template; use relative_url")
    elif PurePosixPath(unquote(urlsplit(url).path)).suffix in _MARKDOWN:
        target = (source.path.parent / unquote(urlsplit(url).path)).resolve()
        if not any(page.path == target for page in site.pages):
            site.report(source.path, line, f"{url} names no Markdown page of the site")
    elif not site.resolves(urlsplit(urljoin("https://site.invalid" + source.url, url)).path):
        site.report(source.path, line, f"{url} does not resolve to a file of the site")


def _check_liquid(site: Site, source: Source, scan: _Scan) -> None:
    text = scan.plain
    for match in _LIQUID_URL.finditer(text):
        if not site.resolves(match["path"]):
            line = _line_of(source, text, match.start())
            site.report(source.path, line, f"{match['path']!r} does not resolve to a file")
    for match in _BASEURL.finditer(text):
        if not site.resolves(match["path"]):
            line = _line_of(source, text, match.start())
            site.report(source.path, line, f"{match['path']!r} does not resolve to a file")
    for match in _LINK_TAG.finditer(text):
        line = _line_of(source, text, match.start())
        if not (site.root / match["path"]).is_file():
            site.report(source.path, line, f"link tag names a missing file {match['path']!r}")
        if not match["base"]:
            site.report(source.path, line, "Jekyll 3's link tag omits baseurl; use relative_url")
    for match in _INCLUDE.finditer(text):
        line = _line_of(source, text, match.start())
        name = match["name"]
        if name not in site.includes:
            site.report(source.path, line, f"include names a missing file {name!r}")
        if name == "figure.html":
            _check_figure(site, source, match["params"], line)


def _check_figure(site: Site, source: Source, params: str, line: int) -> None:
    values = {
        m["key"]: m["dq"] if m["dq"] is not None else m["sq"] if m["sq"] is not None else None
        for m in _PARAM.finditer(params)
    }
    keys = {m["key"] for m in _PARAM.finditer(params)}
    if "alt" not in keys or (values.get("alt") is not None and not values["alt"].strip()):
        site.report(source.path, line, "figure include needs alt text")
    src = values.get("src")
    if "src" not in keys:
        site.report(source.path, line, "figure include needs src")
    if not src:
        return
    path = src if "/" in src else "/assets/img/" + src
    size = None
    if not site.resolves(path):
        site.report(source.path, line, f"figure image {path} does not exist")
    else:
        size = _svg_size(site.root / path.lstrip("/"))
    given = (values.get("width"), values.get("height"))
    if size and all(value and _NUMBER.fullmatch(value) for value in given):
        width, height = (float(value) for value in given)
        if abs(width / height - size[0] / size[1]) > 0.01 * size[0] / size[1]:
            shown = f"{size[0]:g}x{size[1]:g}"
            site.report(source.path, line, f"width and height do not match {path} ({shown})")


def _svg_size(path: Path) -> tuple[float, float] | None:
    """(width, height) of an SVG from its root width and height, else its viewBox."""
    if path.suffix != ".svg" or not path.is_file():
        return None
    root = _SVG_ROOT.search(path.read_text(encoding="utf-8", errors="replace"))
    if root is None:
        return None
    attrs = {m["name"]: m["value"] for m in _SVG_ATTR.finditer(root.group())}
    width, height = attrs.get("width", ""), attrs.get("height", "")
    if _NUMBER.fullmatch(width.removesuffix("px")) and _NUMBER.fullmatch(height.removesuffix("px")):
        return float(width.removesuffix("px")), float(height.removesuffix("px"))
    box = attrs.get("viewBox", "").replace(",", " ").split()
    if len(box) == 4 and all(_NUMBER.fullmatch(part) for part in box[2:]):
        return float(box[2]), float(box[3])
    return None


def _check_tags(site: Site, source: Source, scan: _Scan) -> int:
    """Check src, href, and alt of every start tag; return the number of h1 elements."""
    h1 = 0
    for tag, attrs, line_in_body in _tags(scan.masked):
        line = source.body_line + line_in_body - 1
        if tag == "h1":
            h1 += 1
        if tag == "img":
            alt = attrs.get("alt")
            hidden = attrs.get("aria-hidden") == "true" or attrs.get("role") in _DECORATIVE
            if alt is None or (not alt.strip() and _MASK not in alt and not hidden):
                site.report(source.path, line, "img needs alt text (empty only if aria-hidden)")
        for name in _RESOURCE_ATTRS.get(tag, ()):
            value = attrs.get(name, "")
            urls = [part.split()[0] for part in value.split(",") if part.split()]
            for url in urls if name == "srcset" else [value]:
                _check_url(site, source, url, line, resource=True)
        if tag == "link" and "href" in attrs:
            rels = set(attrs.get("rel", "").lower().split())
            _check_url(site, source, attrs["href"], line, resource=bool(rels & _LOADING_RELS))
        if tag in ("a", "area") and "href" in attrs:
            _check_url(site, source, attrs["href"], line, resource=False)
    return h1


def _check_markdown(site: Site, source: Source, scan: _Scan) -> int:
    """Check Markdown links and images; return the number of Markdown h1 headings."""
    text = scan.masked
    for match in _MD_LINK.finditer(text):
        line = _line_of(source, text, match.start())
        image = bool(match["bang"])
        if image and not match["text"].strip():
            site.report(source.path, line, "Markdown image needs alt text")
        _check_url(site, source, match["url"], line, resource=image)
    for match in (*_MD_REFERENCE.finditer(text), *_AUTOLINK.finditer(text)):
        line = _line_of(source, text, match.start())
        _check_url(site, source, match["url"], line, resource=False)
    h1 = len(_ATX_H1.findall(text))
    lines = text.split("\n")
    for previous, line in zip(lines, lines[1:], strict=False):
        if _SETEXT_H1.match(line) and previous.strip() and not _ATX_H1.match(previous):
            h1 += 1
    return h1


def _template_h1(site: Site, source: Source, seen: frozenset[str]) -> int:
    """h1 elements a layout or include prints, with the includes and layouts it uses."""
    masked = _prepare(site, source).masked if source.rel not in seen else ""
    count = sum(1 for tag, _, _ in _tags(masked) if tag == "h1")
    seen = seen | {source.rel}
    for match in _INCLUDE.finditer(source.body):
        child = site.includes.get(match["name"])
        if child is not None and child.rel not in seen:
            count += _template_h1(site, child, seen)
    parent = (source.front or {}).get("layout")
    if isinstance(parent, str) and source.rel.startswith("_layouts/"):
        layout = site.layouts.get(parent)
        if layout is not None and layout.rel not in seen:
            count += _template_h1(site, layout, seen)
        elif layout is None:
            count += site.theme_layouts.get(parent, 0)
    return count


def _check_page(site: Site, page: Source) -> None:
    scan = _prepare(site, page)
    _check_liquid(site, page, scan)
    h1 = _check_tags(site, page, scan)
    if page.markdown:
        h1 += _check_markdown(site, page, scan)
    for match in _INCLUDE.finditer(scan.plain):
        child = site.includes.get(match["name"])
        if child is not None:
            h1 += _template_h1(site, child, frozenset())
    front = page.front
    if front is None:
        site.report(page.path, 1, "a Markdown page needs front matter (layout, title)")
        return
    if not page.front_ok or not page.html_output:
        return  # a front matter error is reported already; the rest would only echo it
    title = front.get("title")
    if not isinstance(title, str) or not title.strip():
        site.report(page.path, 1, "page needs a title in its front matter")
    layout = front.get("layout")
    if layout is None and page.markdown and "layout" not in front:
        site.report(page.path, 1, "page needs a layout in its front matter")
    if isinstance(layout, str) and layout not in ("none", ""):
        if layout in site.layouts:
            h1 += _template_h1(site, site.layouts[layout], frozenset())
        elif layout in site.theme_layouts:
            h1 += site.theme_layouts[layout]
        else:
            site.report(page.path, 1, f"layout {layout!r} is in neither _layouts/ nor the theme")
    if h1 != 1:
        site.report(page.path, 1, f"needs exactly one h1, has {h1} (layout and body together)")


def _check_nav(site: Site) -> None:
    groups = _strings(site.config.get("nav_groups"))
    seen: dict[tuple[str, int], Source] = {}
    for page in site.pages:
        front = page.front or {}
        group, order = front.get("nav_group"), front.get("nav_order")
        if group is None:
            if order is not None:
                site.report(page.path, 1, "nav_order without nav_group")
            continue
        if not isinstance(group, str) or (groups and group not in groups):
            site.report(page.path, 1, f"nav_group {group!r} is not one of {groups}")
            continue
        if not isinstance(order, int) or isinstance(order, bool):
            site.report(page.path, 1, f"nav_order must be an integer, got {order!r}")
            continue
        other = seen.setdefault((group, order), page)
        if other is not page:
            site.report(page.path, 1, f"nav_order {order} repeats {other.rel} in {group}")


def _check_config(site: Site) -> None:
    path = site.root / "_config.yml"
    for key in ("url", "baseurl"):
        if site.config.get(key):
            site.report(path, 1, f"{key} is set; the Pages build sets it, so leave it out")
    if site.config.get("remote_theme"):
        site.report(path, 1, "remote_theme is set; the site uses its own layouts")
    for plugin in _strings(site.config.get("plugins")):
        if plugin not in _ALLOWED_PLUGINS:
            site.report(path, 1, f"plugin {plugin} is not allowed here")
    if not any(page.url == "/" for page in site.pages):
        site.report(path, 1, "no home page: add index.md")
    urls: dict[str, Source] = {}
    for page in site.pages:
        other = urls.setdefault(page.url, page)
        if other is not page:
            site.report(page.path, 1, f"URL {page.url} is also the URL of {other.rel}")


def _check_styles(site: Site) -> None:
    """Stylesheets, and the Sass partials that compile into assets/css/style.css."""
    partials = (
        sorted((site.root / "_sass").rglob("*.scss")) if (site.root / "_sass").is_dir() else []
    )
    sheets = [(path, "/" + path.relative_to(site.root).as_posix()) for path in site.styles]
    sheets += [(path, "/assets/css/style.css") for path in partials]
    for path, base in sheets:
        text = path.read_text(encoding="utf-8")
        for match in _CSS_URL.finditer(text):
            sass_import = match["url"] is None
            url = (match["imp"] if sass_import else match["url"]).strip()
            line = text.count("\n", 0, match.start()) + 1
            if not url or url.startswith(("data:", "#")) or "{{" in url or "{%" in url:
                continue  # empty, inline, or built by Liquid (checked as a relative_url literal)
            if _EXTERNAL.match(url):
                site.report(path, line, f"loads {url} from another origin")
            elif sass_import and path.suffix == ".scss" and not url.endswith(".css"):
                continue  # a Sass partial, inlined at build time
            elif not site.resolves(urlsplit(urljoin("https://site.invalid" + base, url)).path):
                site.report(path, line, f"{url} does not resolve to a file of the site")


def check(root: Path) -> tuple[Site, list[Problem]]:
    site = load_site(root)
    _check_config(site)
    for source in (*site.layouts.values(), *site.includes.values()):
        scan = _prepare(site, source)
        _check_liquid(site, source, scan)
        _check_tags(site, source, scan)
    for page in site.pages:
        _check_page(site, page)
    _check_nav(site)
    _check_styles(site)
    return site, sorted(site.problems, key=lambda p: (str(p.path), p.line, p.message))


def _shown(path: Path) -> str:
    relative = os.path.relpath(path)
    return path.as_posix() if relative.startswith("..") else relative


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default = Path(__file__).resolve().parent.parent / "docs"
    parser.add_argument("docs", nargs="?", type=Path, default=default, help="the Jekyll source")
    args = parser.parse_args(argv)
    root = args.docs.resolve()
    if not root.is_dir():
        print(f"check_site: no such folder: {args.docs}", file=sys.stderr)
        return 2
    site, problems = check(root)
    for problem in problems:
        print(f"{_shown(problem.path)}:{problem.line}: {problem.message}")
    if problems:
        print(f"check_site: {len(problems)} problem(s) in {_shown(root)}", file=sys.stderr)
        return 1
    print(f"check_site: {len(site.pages)} pages and {len(site.served)} URLs in {_shown(root)}: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
