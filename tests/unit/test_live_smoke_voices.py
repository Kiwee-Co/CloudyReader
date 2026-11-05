"""scripts/live_smoke_voices.py: probe lines, the small download, and the verdict, on canned hosts.

No live calls: respx answers every host, and the lock is a small fake with known payloads.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
import respx

from cloudyreader.config import load_settings

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "live_smoke_voices.py"
HOST, CDN = "files.example", "cdn.example"


def payload(name: str) -> bytes:
    return (name.encode() + b"\n") * 4


def entry(name: str, group: str, dest: str) -> dict:
    body = payload(name)
    return {
        "name": name,
        "group": group,
        "url": f"https://{HOST}/{group}/{name}?download=true",
        "sha256": hashlib.sha256(body).hexdigest(),
        "size": len(body),
        "dest": dest,
    }


LOCK = [
    entry("ner-0.1.tar.gz", "models", ".data/models/ner"),
    entry("en_US-a-medium.onnx", "voices", ".data/voices"),
    entry("en_US-a-medium.onnx.json", "voices", ".data/voices"),
    entry("en_GB-b-medium.onnx", "voices", ".data/voices"),
    entry("en_GB-b-medium.onnx.json", "voices", ".data/voices"),
    entry("config.json", "kokoro", ".data/models/kokoro"),
    entry("kokoro-v1_0.safetensors", "kokoro", ".data/models/kokoro"),
    entry("af_bella.safetensors", "kokoro", ".data/models/kokoro/voices"),
    entry("af_heart.safetensors", "kokoro", ".data/models/kokoro/voices"),
]
PROBED = sorted(e["name"] for e in LOCK if e["group"] != "models")  # the NER model: never
SMALL = sorted(
    ["en_US-a-medium.onnx.json", "en_GB-b-medium.onnx.json", "config.json", "af_heart.safetensors"]
)


def name_of(request: httpx.Request) -> str:
    return request.url.path.rsplit("/", 1)[-1]


def answer(request: httpx.Request) -> httpx.Response:
    """A range probe gets byte 0 and the full size; a plain GET gets the whole file."""
    body = payload(name_of(request))
    if request.headers.get("range") == "bytes=0-0":
        headers = {"Content-Range": f"bytes 0-0/{len(body)}"}
        return httpx.Response(206, headers=headers, content=body[:1])
    return httpx.Response(200, content=body)


def redirect(location: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(302, headers={"Location": location})


def refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("blocked", request=request)


class Server:
    """Every host behind one object: a test bends one file by setting `files[name]`."""

    def __init__(self, router: respx.MockRouter) -> None:
        self.requests: list[httpx.Request] = []
        self.files: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.fallback = answer
        router.route().mock(side_effect=self._serve)

    def _serve(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.files.get(name_of(request), self.fallback)(request)

    def probes(self) -> list[str]:
        return [name_of(r) for r in self.requests if r.headers.get("range") == "bytes=0-0"]

    def downloads(self) -> list[str]:
        return [name_of(r) for r in self.requests if "range" not in r.headers]


@pytest.fixture
def smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location("live_smoke_voices", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses looks its module up in sys.modules while it builds the script's classes.
    monkeypatch.setitem(sys.modules, "live_smoke_voices", module)
    spec.loader.exec_module(module)
    lock = tmp_path / "assets.lock.json"
    lock.write_text(json.dumps({"version": 1, "assets": LOCK}))
    monkeypatch.setattr(module, "find_lock", lambda **kwargs: lock)
    monkeypatch.setattr(module, "RETRY_DELAY_S", 0.0)
    return module


@pytest.fixture
def server():
    with respx.mock(assert_all_called=False) as router:
        yield Server(router)


@pytest.fixture
def run(smoke, server, capsys):
    def go(**kwargs) -> tuple[int, str]:
        code = smoke.main(**kwargs)
        return code, capsys.readouterr().out

    return go


def line_for(out: str, name: str) -> str:
    """The probe line of `name`, whitespace squeezed."""
    pattern = re.compile(rf"(HELD|BROKEN|NO DATA)\s+{re.escape(name)}\s")
    for line in out.splitlines():
        if pattern.match(line):
            return " ".join(line.split())
    raise AssertionError(f"no probe line for {name!r} in:\n{out}")


def verdict(out: str, scope: str) -> str:
    """The verdict line of `scope`, whitespace squeezed."""
    pattern = re.compile(rf"(HELD|PARTIAL|BROKEN|NO DATA)\s+{scope}\s")
    for line in out.split("== verdict ==", 1)[-1].splitlines():
        if pattern.match(line):
            return " ".join(line.split())
    raise AssertionError(f"no verdict line for {scope!r} in:\n{out}")


def test_a_healthy_run_holds_every_check(run):
    code, out = run()

    assert code == 0
    for name in PROBED:
        size = len(payload(name))
        assert line_for(out, name) == f"HELD {name} HTTP 206, 0 hop(s), {size} of {size} bytes"
    assert verdict(out, "probes") == "HELD probes each pinned file reports its pinned size 8/8"
    assert verdict(out, "download") == (
        "HELD download the small files arrive with their pinned SHA-256 4/4"
    )
    assert "RESULT: every check held." in out


def test_one_range_probe_per_pinned_file_then_only_the_small_files(run, server):
    run()

    assert sorted(server.probes()) == PROBED
    assert sorted(server.downloads()) == SMALL
    for request in server.requests:
        assert (request.method, request.url.scheme) == ("GET", "https")
        assert not request.content
        assert not {"authorization", "cookie"} & set(request.headers)


def test_lines_hold_names_statuses_and_byte_counts_never_a_url_host_or_query(run, server):
    server.files["en_US-a-medium.onnx"] = redirect(f"https://{CDN}/blob?sig=s3cret")

    _, out = run()

    for leak in ("://", HOST, CDN, "sig=", "s3cret", "download=true", ".data"):
        assert leak not in out


def test_redirects_are_followed_and_counted(run, server):
    name = "en_US-a-medium.onnx"
    server.files["hop1"] = redirect("/hop2")
    server.files["hop2"] = redirect(f"/{name}")
    server.files[name] = lambda r: (
        answer(r) if r.url.host == CDN else redirect(f"https://{CDN}/hop1")(r)
    )

    _, out = run()

    size = len(payload(name))
    assert line_for(out, name) == f"HELD {name} HTTP 206, 3 hop(s), {size} of {size} bytes"


def test_a_size_other_than_the_pin_is_broken(run, server):
    size = len(payload("af_bella.safetensors"))
    server.files["af_bella.safetensors"] = lambda r: httpx.Response(
        206, headers={"Content-Range": f"bytes 0-0/{size + 1}"}, content=b"x"
    )

    code, out = run()

    assert code == 0
    assert line_for(out, "af_bella.safetensors") == (
        f"BROKEN af_bella.safetensors HTTP 206, 0 hop(s), {size + 1} of {size} bytes"
    )
    assert verdict(out, "probes") == (
        "PARTIAL probes each pinned file reports its pinned size 7/8 fails: af_bella.safetensors"
    )
    assert "RESULT: 1 of 2 checks did not hold." in out


def test_a_redirect_to_plain_http_is_broken(run, server):
    server.files["config.json"] = redirect(f"http://{CDN}/config.json")

    _, out = run()

    assert line_for(out, "config.json") == "BROKEN config.json refused a non-HTTPS redirect"
    assert not any(r.url.scheme == "http" for r in server.requests)
    assert verdict(out, "download") == (
        "PARTIAL download the small files arrive with their pinned SHA-256 3/4 fails: config.json"
    )


@pytest.mark.parametrize(
    ("status", "headers"),
    [(404, {}), (206, {"Content-Range": "bytes */9"}), (500, {})],
    ids=["not-found", "no-total", "server-error"],
)
def test_an_answer_without_the_pinned_size_is_broken(run, server, status, headers):
    server.files["en_GB-b-medium.onnx"] = lambda r: httpx.Response(status, headers=headers)

    _, out = run()

    size = len(payload("en_GB-b-medium.onnx"))
    assert line_for(out, "en_GB-b-medium.onnx") == (
        f"BROKEN en_GB-b-medium.onnx HTTP {status}, 0 hop(s), ? of {size} bytes"
    )


def test_a_server_that_ignores_the_range_is_judged_by_its_content_length(run, server):
    name = "kokoro-v1_0.safetensors"
    server.files[name] = lambda r: httpx.Response(200, content=payload(name))

    _, out = run()

    size = len(payload(name))
    assert line_for(out, name) == f"HELD {name} HTTP 200, 0 hop(s), {size} of {size} bytes"


def test_a_tampered_small_file_breaks_the_download_check(run, server):
    name = "af_heart.safetensors"
    tampered = httpx.Response(200, content=b"y" * len(payload(name)))
    server.files[name] = lambda r: answer(r) if r.headers.get("range") else tampered

    _, out = run()

    assert verdict(out, "download") == (
        f"PARTIAL download the small files arrive with their pinned SHA-256 3/4 fails: {name}"
    )


def test_connect_errors_are_no_data_and_skip_the_download(run, server):
    server.fallback = refuse

    code, out = run()

    assert code == 0
    for name in PROBED:
        assert line_for(out, name) == f"NO DATA {name} no response (ConnectError)"
    assert verdict(out, "probes").startswith("NO DATA probes")
    assert verdict(out, "download") == "NO DATA download skipped: no probe got an answer"
    assert "RESULT: no HTTP response at all" in out
    assert server.downloads() == []


def test_writes_only_into_a_temp_dir_whatever_the_environment_says(
    run, smoke, tmp_path, monkeypatch
):
    sentinel, scratch, cwd = tmp_path / "sentinel", tmp_path / "tmp", tmp_path / "cwd"
    for folder in (sentinel, scratch, cwd):
        folder.mkdir()
    monkeypatch.setenv("CLOUDYREADER_DATA_DIR", str(sentinel))
    monkeypatch.setenv("CLOUDYREADER_OFFLINE", "1")  # must not turn the live test into a no-op
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    monkeypatch.chdir(cwd)
    used = []
    real = smoke.VoicePrefetch

    def spy(settings, **kwargs):
        used.append(settings)
        return real(settings, **kwargs)

    monkeypatch.setattr(smoke, "VoicePrefetch", spy)

    code, out = run()

    assert code == 0
    assert "RESULT: every check held." in out
    assert list(sentinel.iterdir()) == list(cwd.iterdir()) == []
    assert list(scratch.iterdir()) == []  # the temp dir is removed afterwards
    (settings,) = used
    assert settings.data_dir.is_relative_to(scratch)
    assert settings.offline is False


def test_given_settings_receive_the_small_files(run, tmp_path):
    settings = load_settings({"CLOUDYREADER_DATA_DIR": str(tmp_path / "given")})

    code, _ = run(settings=settings)

    assert code == 0
    heart = settings.models_dir / "kokoro" / "voices" / "af_heart.safetensors"
    assert heart.read_bytes() == payload("af_heart.safetensors")
    assert (settings.voices_dir / "en_US-a-medium.onnx.json").is_file()
    assert not (settings.voices_dir / "en_US-a-medium.onnx").exists()


def test_no_lock_reports_no_data_and_sends_nothing(run, smoke, server, monkeypatch):
    monkeypatch.setattr(smoke, "find_lock", lambda **kwargs: None)

    code, out = run()

    assert code == 0
    assert re.search(r"NO DATA\s+lock\s+no assets\.lock\.json found", out)
    assert server.requests == []


def test_a_rejected_lock_is_broken_and_sends_nothing(run, smoke, server, tmp_path, monkeypatch):
    bad = tmp_path / "bad.lock.json"
    bad.write_text(json.dumps({"version": 1, "assets": [LOCK[1] | {"url": "http://x/y"}]}))
    monkeypatch.setattr(smoke, "find_lock", lambda **kwargs: bad)

    code, out = run()

    assert code == 0
    assert re.search(r"BROKEN\s+lock\s+bad\.lock\.json rejected: entry 0 is unsafe", out)
    assert "http" not in out
    assert server.requests == []
