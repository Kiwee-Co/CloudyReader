"""scripts/check_site.py: the checks of the built site, on small hand-written dist trees."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_site.py"


@pytest.fixture
def check_site(monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("check_site", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses looks its module up in sys.modules while it builds the script's classes.
    monkeypatch.setitem(sys.modules, "check_site", module)
    spec.loader.exec_module(module)
    return module


def html(body: str, *, head: str = "", h1: str = "<h1>Title</h1>") -> str:
    return f"<!doctype html><html><head>{head}</head><body>{h1}{body}</body></html>"


def build(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def problems(check_site, root: Path, files: dict[str, str]) -> list[str]:
    return check_site.check(build(root, files))


CLEAN = {
    "index.html": html(
        '<a href="/manual/voices/">Voices</a> <a href="manual/voices/#rotation">Rotation</a>'
        ' <a href="https://github.com/Kiwee-Co/CloudyReader">Source</a> <a href="#top">Top</a>'
        ' <a href="mailto:someone@example.org">Mail</a> <img src="/img/logo.svg" alt="">',
        head='<link rel="stylesheet" href="/_astro/site.css"><link rel="icon" href="/favicon.svg">'
        '<link rel="canonical" href="https://cloudyreader.com/">'
        '<link rel="sitemap" href="/sitemap.xml">',
        h1='<h1 id="top">Cloudy Reader</h1>',
    ),
    "manual/voices/index.html": html(
        '<h2 id="rotation">Rotation</h2>'
        '<figure id="figure-voices" class="cr-figure">'
        '<img src="/img/voices-light.svg" alt="The menu">'
        '<img src="/img/voices-dark.svg" alt="The menu"><figcaption>Voices</figcaption></figure>'
        '<figure class="frame is-terminal"><pre>make app</pre></figure>'
    ),
    "custom-domain/index.html": (
        '<html><head><meta http-equiv="refresh" content="0;url=/x/"></head></html>'
    ),
    "_astro/site.css": "body{}",
    "favicon.svg": "<svg/>",
    "sitemap.xml": "<urlset/>",
    "img/logo.svg": "<svg/>",
    "img/voices-light.svg": "<svg/>",
    "img/voices-dark.svg": "<svg/>",
}


def test_a_clean_site_passes_and_main_exits_0(check_site, tmp_path, capsys):
    build(tmp_path, CLEAN)

    assert check_site.check(tmp_path) == []
    assert check_site.main([str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""


def test_a_missing_build_exits_2(check_site, tmp_path, capsys):
    assert check_site.main([str(tmp_path / "dist")]) == 2
    assert "npm run build" in capsys.readouterr().err


def test_problems_print_one_line_each_and_main_exits_1(check_site, tmp_path, capsys):
    build(
        tmp_path,
        {**CLEAN, "index.html": html('<a href="/gone/">Gone</a> <a href="/also/">Also</a>')},
    )

    assert check_site.main([str(tmp_path)]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "index.html: line 1: missing /gone/",
        "index.html: line 1: missing /also/",
    ]


@pytest.mark.parametrize(
    ("href", "problem"),
    [
        ("/manual/gone/", "missing /manual/gone/"),
        ("../outside/", "missing ../outside/"),
        ("/manual/voices/#nowhere", "no #nowhere in manual/voices/index.html"),
        ("#nowhere", "no #nowhere in index.html"),
        ("https://cloudyreader.com/manual/voices/", "link hard-codes the site's host"),
    ],
)
def test_a_bad_link_is_named(check_site, tmp_path, href, problem):
    found = problems(check_site, tmp_path, {**CLEAN, "index.html": html(f'<a href="{href}">x</a>')})

    assert len(found) == 1
    assert problem in found[0]


def test_links_resolve_to_directories_files_and_encoded_names(check_site, tmp_path):
    body = (
        '<a href="/manual/voices">no slash</a> <a href="/img/logo.svg?v=2">query</a>'
        ' <a href="/manual/voices/index.html#rotation">file</a> <a href="/a%20b/">space</a>'
    )
    files = {**CLEAN, "index.html": html(body), "a b/index.html": html("")}

    assert problems(check_site, tmp_path, files) == []


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ('<img src="/img/gone.svg" alt="x">', "missing /img/gone.svg"),
        ('<img src="/img/logo.svg">', "<img> without alt"),
        ('<img srcset="/img/logo.svg 1x, /img/gone.svg 2x" alt="">', "missing /img/gone.svg"),
        (
            '<figure id="f" class="cr-figure"><img src="/img/logo.svg" alt=" "></figure>',
            "figure image with empty alt",
        ),
        (
            '<figure class="cr-figure"><img src="/img/logo.svg" alt="x"></figure>',
            "a figure has no id",
        ),
        ('<p id="a"></p><p id="a"></p>', "duplicate id 'a'"),
    ],
)
def test_images_figures_and_ids(check_site, tmp_path, body, problem):
    found = problems(check_site, tmp_path, {**CLEAN, "index.html": html(body)})

    assert len(found) == 1
    assert problem in found[0]


def test_a_bare_alt_is_decorative_and_code_figures_need_no_id(check_site, tmp_path):
    body = (
        '<img src="/img/logo.svg" alt><img src="/img/logo.svg" alt=""/><figure class="frame"/>'
        '<figure class="frame"><img src="/img/logo.svg" alt=""></figure>'
    )

    assert problems(check_site, tmp_path, {**CLEAN, "index.html": html(body)}) == []


@pytest.mark.parametrize(
    "head",
    [
        '<script src="https://cdn.example.org/a.js"></script>',
        '<link rel="stylesheet" href="https://fonts.example.org/a.css">',
        '<script src="//cdn.example.org/a.js"></script>',
    ],
)
def test_a_resource_from_another_origin_fails(check_site, tmp_path, head):
    found = problems(check_site, tmp_path, {**CLEAN, "index.html": html("", head=head)})

    assert len(found) == 1
    assert "loads from another origin" in found[0]


def test_an_image_from_another_origin_fails_but_a_link_to_one_passes(check_site, tmp_path):
    body = '<img src="https://img.example.org/a.png" alt="x"> <a href="https://example.org/">ok</a>'

    found = problems(check_site, tmp_path, {**CLEAN, "index.html": html(body)})

    assert found == [
        "index.html: line 1: <img> loads from another origin: https://img.example.org/a.png"
    ]


@pytest.mark.parametrize(("h1", "count"), [("", 0), ("<h1>A</h1><h1>B</h1>", 2)])
def test_a_page_needs_exactly_one_h1(check_site, tmp_path, h1, count):
    found = problems(check_site, tmp_path, {**CLEAN, "index.html": html("", h1=h1)})

    assert found == [f"index.html: {count} h1 elements, not 1"]


def test_the_default_build_folder_is_site_dist_beside_scripts(check_site, monkeypatch, capsys):
    monkeypatch.setattr(check_site, "__file__", "/nowhere/scripts/check_site.py")

    assert check_site.main([]) == 2
    assert "/nowhere/site/dist" in capsys.readouterr().err
