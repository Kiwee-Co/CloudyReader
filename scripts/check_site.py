"""Check the built documentation site in site/dist. Standard library only.

It reads the HTML that `npm run build` writes in site/, so it checks what visitors get. It checks:
- every page has exactly one h1 (a redirect page has none and is skipped);
- every internal link resolves to a built file, and a #fragment to an id on the target page;
- no page links to an old address that only redirects (link to the new page instead);
- every image resolves and has an alt attribute; an image in a figure has a non-empty alt;
- ids are unique on a page, and every figure that the Figure component draws has an id;
- no link hard-codes the site's own host, and no page loads a resource from another origin.

Usage: python3 scripts/check_site.py [DIST_DIR]  (default: site/dist beside scripts/)
Exit 0 when clean, 1 with one "path: problem" line each, 2 when DIST_DIR is missing.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

HOST = "cloudyreader.com"
FIGURE_CLASS = "cr-figure"  # the Figure component's class (site/src/components/Figure.astro)
# Attributes that load something into the page, by tag. A link only loads with these rel values.
RESOURCES = {
    "img": ("src", "srcset"),
    "source": ("src", "srcset"),
    "script": ("src",),
    "link": ("href",),
    "video": ("src", "poster"),
    "audio": ("src",),
    "track": ("src",),
    "iframe": ("src",),
    "embed": ("src",),
    "object": ("data",),
}
LOADING_RELS = {
    "stylesheet",
    "icon",
    "shortcut",
    "preload",
    "modulepreload",
    "manifest",
    "prefetch",
}
SKIPPED_SCHEMES = {"mailto", "tel", "data", "javascript"}


@dataclass
class Ref:
    tag: str
    url: str
    line: int
    resource: bool  # loads into the page, rather than a link the reader follows


@dataclass
class Page:
    ids: list[str] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    h1: int = 0
    redirect: bool = False
    problems: list[str] = field(default_factory=list)


class _Parser(HTMLParser):
    def __init__(self, page: Page) -> None:
        super().__init__(convert_charrefs=True)
        self.page = page
        self.figures: list[bool] = []  # one entry per open <figure>: True for a Figure component

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        line = self.getpos()[0]
        if "id" in values:
            self.page.ids.append(values["id"])
        if tag == "h1":
            self.page.h1 += 1
        if tag == "meta" and values.get("http-equiv", "").lower() == "refresh":
            self.page.redirect = True
        if tag == "figure":
            ours = FIGURE_CLASS in values.get("class", "").split()
            self.figures.append(ours)
            if ours and not values.get("id"):
                self.page.problems.append(f"line {line}: a figure has no id")
        if tag == "img":
            if "alt" not in values:
                self.page.problems.append(f"line {line}: <img> without alt: {values.get('src')}")
            elif any(self.figures) and not values["alt"].strip():
                self.page.problems.append(f"line {line}: figure image with empty alt")
        rels = set(values.get("rel", "").lower().split())
        for name in RESOURCES.get(tag, ()):
            if name not in values or (tag == "link" and not rels & LOADING_RELS):
                continue
            urls = _srcset(values[name]) if name == "srcset" else [values[name]]
            self.page.refs += [Ref(tag, url, line, resource=True) for url in urls]
        if tag in ("a", "area") and "href" in values:
            self.page.refs.append(Ref(tag, values["href"], line, resource=False))
        if tag == "link" and "href" in values and not rels & LOADING_RELS:
            self.page.refs.append(Ref(tag, values["href"], line, resource=False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag == "figure":
            self.figures.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag == "figure" and self.figures:
            self.figures.pop()


def _srcset(value: str) -> list[str]:
    """The URLs of a srcset: "a.svg 1x, b.svg 2x" gives a.svg and b.svg."""
    return [candidate.split()[0] for candidate in value.split(",") if candidate.strip()]


def parse(path: Path) -> Page:
    page = Page()
    _Parser(page).feed(path.read_text(encoding="utf-8"))
    return page


def _target(dist: Path, page: Path, url_path: str) -> Path:
    base = dist if url_path.startswith("/") else page.parent
    found = (base / unquote(url_path.lstrip("/"))).resolve()
    return found / "index.html" if found.is_dir() else found


def _check_ref(dist: Path, path: Path, pages: dict[Path, Page], ref: Ref) -> str | None:
    parts = urlsplit(ref.url)
    if parts.scheme in SKIPPED_SCHEMES:
        return None
    if parts.scheme or parts.netloc:  # absolute, or protocol-relative //host/path
        if parts.hostname == HOST and ref.tag == "a":
            return f"line {ref.line}: link hard-codes the site's host: {ref.url}"
        if parts.hostname != HOST and ref.resource:
            return f"line {ref.line}: <{ref.tag}> loads from another origin: {ref.url}"
        return None
    target = _target(dist, path, parts.path) if parts.path else path
    if not target.is_relative_to(dist) or not target.is_file():
        return f"line {ref.line}: missing {ref.url}"
    if ref.tag == "a" and target in pages and pages[target].redirect and not pages[path].redirect:
        return f"line {ref.line}: link goes through a redirect: {ref.url}"
    if parts.fragment and target.suffix == ".html":
        ids = pages[target].ids if target in pages else parse(target).ids
        if unquote(parts.fragment) not in ids:
            return f"line {ref.line}: no #{parts.fragment} in {target.relative_to(dist).as_posix()}"
    return None


def check(dist: Path) -> list[str]:
    """Every problem of the built site, as "page: problem" lines."""
    dist = dist.resolve()
    pages = {path: parse(path) for path in sorted(dist.rglob("*.html"))}
    problems = []
    for path, page in pages.items():
        rel = path.relative_to(dist).as_posix()
        found = list(page.problems)
        if not page.redirect and page.h1 != 1:
            found.append(f"{page.h1} h1 elements, not 1")
        found += [f"duplicate id {i!r}" for i, n in sorted(Counter(page.ids).items()) if n > 1]
        found += [p for ref in page.refs if (p := _check_ref(dist, path, pages, ref))]
        problems += [f"{rel}: {problem}" for problem in found]
    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    dist = Path(args[0]) if args else Path(__file__).resolve().parents[1] / "site" / "dist"
    if not dist.is_dir():
        print(f"no built site at {dist}: run npm run build in site/ first", file=sys.stderr)
        return 2
    problems = check(dist)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
