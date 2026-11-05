"""cloudyreader.prefetch: lock checks, the plan, and the download loop, on canned servers.

No live calls: every client runs on httpx.MockTransport, and building any other httpx.Client fails.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import stat
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath

import httpx
import pytest

from cloudyreader import prefetch
from cloudyreader.config import Settings
from cloudyreader.prefetch import (
    PrefetchError,
    PrefetchProgress,
    PrefetchResult,
    VoicePrefetch,
    find_lock,
    open_https,
)

ROOT = Path(__file__).resolve().parents[2]
REAL_CLIENT = httpx.Client
HOST = "https://files.example"
LOGGER = "cloudyreader.prefetch"


def payload(name: str) -> bytes:
    return (name.encode() + b"\n") * 3


def entry(name: str, group: str = "voices", dest: str = ".data/voices", **overrides) -> dict:
    body = payload(name)
    item = {
        "name": name,
        "group": group,
        "url": f"{HOST}/{group}/{name}",
        "sha256": hashlib.sha256(body).hexdigest(),
        "size": len(body),
        "dest": dest,
    }
    return item | overrides


# Lock order is scrambled on purpose: the plan must sort it.
MODELS = [entry("ner-0.1.tar.gz", "models", ".data/models/ner")]
KOKORO = [
    entry("af_heart.safetensors", "kokoro", ".data/models/kokoro/voices"),
    entry("kokoro-v1_0.safetensors", "kokoro", ".data/models/kokoro"),
    entry("config.json", "kokoro", ".data/models/kokoro"),
]
PIPER = [
    entry("en_US-a-medium.onnx"),
    entry("en_US-a-medium.onnx.json"),
    entry("en_GB-b-medium.onnx"),
    entry("en_GB-b-medium.onnx.json"),
]
ENTRIES = {e["name"]: e for e in MODELS + KOKORO + PIPER}
ORDER = [
    "en_US-a-medium.onnx.json",
    "en_GB-b-medium.onnx.json",
    "en_US-a-medium.onnx",
    "en_GB-b-medium.onnx",
    "config.json",
    "kokoro-v1_0.safetensors",
    "af_heart.safetensors",
]
FIRST = ORDER[0]
TOTAL = sum(len(payload(name)) for name in ORDER)


def url_path(name: str) -> str:
    return httpx.URL(ENTRIES[name]["url"]).path


def make_settings(root: Path, **changes) -> Settings:
    data = root / "data"
    return dataclasses.replace(
        Settings(data, data / "cache", data / "voices", data / "models"), **changes
    )


def wire(body: bytes) -> httpx.Response:
    """A 200 as a transport delivers it: headers and an unread stream (`content=` reads it)."""
    headers = {"Content-Length": str(len(body))}
    return httpx.Response(200, headers=headers, stream=httpx.ByteStream(body))


class Server:
    """Serves every lock entry's payload; a test bends one path by setting `routes[path]`."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.bodies = {url_path(name): payload(name) for name in ENTRIES}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get(request.url.path)
        if handler is not None:
            return handler(request)
        body = self.bodies.get(request.url.path)
        return httpx.Response(404) if body is None else wire(body)

    def hits(self, name: str) -> int:
        return sum(1 for r in self.requests if r.url.path == url_path(name))


class Rig:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.settings = make_settings(root)
        self.lock = root / "assets.lock.json"
        self.write_lock(*MODELS, *KOKORO, *PIPER)
        self.server = Server()
        self.client = REAL_CLIENT(transport=httpx.MockTransport(self.server))

    def write_lock(self, *entries: dict, version: object = 1) -> None:
        self.lock.write_text(json.dumps({"version": version, "assets": list(entries)}))

    def prefetch(self, **changes) -> VoicePrefetch:
        options = {
            "lock_path": self.lock,
            "client": self.client,
            "kokoro_ready": lambda: True,
            "retry_delay_s": 0.0,
        }
        return VoicePrefetch(self.settings, **(options | changes))

    def target(self, name: str) -> Path:
        root, *rest = PurePosixPath(ENTRIES[name]["dest"]).parts[1:]
        base = self.settings.voices_dir if root == "voices" else self.settings.models_dir
        return base.joinpath(*rest, name)

    def install(self, name: str, body: bytes | None = None) -> Path:
        path = self.target(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload(name) if body is None else body)
        return path

    @property
    def stage(self) -> Path:
        return self.settings.data_dir / ".prefetch"

    def leftovers(self) -> list[str]:
        return sorted(p.name for p in self.stage.iterdir()) if self.stage.exists() else []


@pytest.fixture(autouse=True)
def no_live_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Any httpx.Client the code builds itself fails the test, even when the error is swallowed."""
    built: list[str] = []

    def refuse(*args, **kwargs):
        built.append("httpx.Client")
        raise AssertionError("prefetch built its own httpx.Client in a test")

    monkeypatch.setattr(httpx, "Client", refuse)
    yield built
    assert built == []


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    made = Rig(tmp_path)
    yield made
    made.client.close()


@pytest.fixture
def logs(caplog: pytest.LogCaptureFixture) -> Callable[[], str]:
    """This module's log text only: httpx logs its own request lines elsewhere."""
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    return lambda: "\n".join(r.getMessage() for r in caplog.records if r.name == LOGGER)


def redirect(location: str, status: int = 302) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, headers={"Location": location})


def serve(body: bytes) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: wire(body)


# --- lock -----------------------------------------------------------------------------------------


def test_find_lock_prefers_the_bundled_lock_then_the_source_checkout(tmp_path: Path) -> None:
    resources, source = tmp_path / "Resources", tmp_path / "repo"
    (resources / "assets").mkdir(parents=True)
    source.mkdir()
    bundled, checkout = resources / "assets" / "assets.lock.json", source / "assets.lock.json"
    bundled.write_text("{}")
    checkout.write_text("{}")

    assert find_lock(resources_dir=resources, root=source) == bundled
    bundled.unlink()
    assert find_lock(resources_dir=resources, root=source) == checkout
    checkout.unlink()
    assert find_lock(resources_dir=resources, root=source) is None


def test_find_lock_outside_a_bundle_is_the_repo_lock() -> None:
    assert find_lock() == ROOT / "assets.lock.json"


def test_no_lock_is_nothing_and_sends_no_request(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prefetch, "find_lock", lambda **kwargs: None)

    assert rig.prefetch(lock_path=None).run() == PrefetchResult(
        "nothing", skipped=("no assets.lock.json",)
    )
    assert rig.prefetch(lock_path=rig.root / "absent.json").run().outcome == "nothing"
    assert rig.server.requests == []
    assert not rig.settings.data_dir.exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"dest": "../outside"},
        {"dest": "/tmp/abs"},
        {"dest": "models"},
        {"url": "http://example.org/v.onnx"},
        {"sha256": "abc"},
        {"name": "../v.onnx"},
        {"size": 0},
        {"group": "plugins"},
        {"name": "af_heart.pt"},
        {"name": "model.PTH"},
        {"dest": ".data/cache"},  # a dest root that is neither voices nor models
        {"dest": ".data"},
        {"dest": ".data/voices/.hidden"},
        {"name": ".bashrc"},
        {"name": "run.sh"},  # fetched files are data only: never code
        {"name": "libevil.dylib"},
        {"url": "https://user:secret@files.example/v.onnx"},
        {"url": "https://"},
        {"url": "https://[broken/v.onnx"},
        {"size": True},
        {"size": "12"},
        {"name": 7},
    ],
)
def test_one_unsafe_entry_rejects_the_whole_lock(rig: Rig, logs, overrides: dict) -> None:
    rig.write_lock(*PIPER, entry("v.onnx") | overrides)

    result = rig.prefetch().run()

    assert result.outcome == "nothing"
    assert result.skipped[0].startswith("invalid assets.lock.json")
    assert rig.server.requests == []
    assert not rig.settings.data_dir.exists()
    assert "rejected" in logs()
    assert "http" not in logs() and "secret" not in logs()


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"assets": []}',
        '{"version": 2, "assets": []}',
        '{"version": true, "assets": []}',
        '{"version": 1}',
        '{"version": 1, "assets": [5]}',
        '{"version": 1, "assets": [{"name": "x.onnx"}]}',
    ],
)
def test_a_malformed_lock_is_rejected(rig: Rig, text: str) -> None:
    rig.lock.write_text(text)

    result = rig.prefetch().run()

    assert result.outcome == "nothing"
    assert result.skipped[0].startswith("invalid assets.lock.json")
    assert rig.server.requests == []


def test_an_unreadable_lock_is_rejected(rig: Rig) -> None:
    rig.lock.write_bytes(b"\xff\xfe not utf-8")

    assert rig.prefetch().plan().skipped[0].startswith("invalid assets.lock.json")


def test_the_real_lock_loads_and_matches_the_kokoro_trust_anchors(tmp_path: Path) -> None:
    from cloudyreader.engines.kokoro import MODEL_SHA256, VOICE_SHA256

    settings = make_settings(tmp_path)
    lock = ROOT / "assets.lock.json"

    plan = VoicePrefetch(settings, lock_path=lock, kokoro_ready=lambda: True).plan()

    assert Counter(a.group for a in plan.assets) == {"voices": 10, "kokoro": 30}
    kokoro = {a.name: a.sha256 for a in plan.assets if a.group == "kokoro"}
    anchors = MODEL_SHA256 | {f"{vid}.safetensors": sha for vid, sha in VOICE_SHA256.items()}
    assert kokoro == anchors
    piper = {a.name for a in plan.assets if a.group == "voices"}
    assert piper == {n + ".json" for n in piper if n.endswith(".onnx")} | {
        n.removesuffix(".json") for n in piper if n.endswith(".json")
    }
    assert plan.total_bytes == 657_773_366  # about 658 MB on a fresh dev checkout
    heart = next(a for a in plan.assets if a.name == "af_heart.safetensors")
    assert heart.path == settings.models_dir / "kokoro" / "voices" / "af_heart.safetensors"
    assert not settings.data_dir.exists()


# --- plan -----------------------------------------------------------------------------------------


def test_plan_puts_piper_configs_first_then_models_then_kokoro_and_never_the_ner_model(
    rig: Rig,
) -> None:
    plan = rig.prefetch().plan()

    assert [a.name for a in plan.assets] == ORDER
    assert plan.assets[0].path == rig.settings.voices_dir / FIRST
    assert plan.assets[4].path == rig.settings.models_dir / "kokoro" / "config.json"
    assert plan.total_bytes == TOTAL
    assert (plan.conflicts, plan.skipped) == ((), ())
    assert not rig.settings.data_dir.exists()  # stat only


def test_an_asset_never_shows_its_url_in_repr(rig: Rig) -> None:
    plan = rig.prefetch().plan()

    assert HOST not in repr(plan)
    assert plan.assets[0].url == f"{HOST}/voices/{FIRST}"


def test_a_file_of_the_pinned_size_is_skipped_and_one_of_another_size_never_touched(
    rig: Rig, logs
) -> None:
    rig.install("en_US-a-medium.onnx")
    other = rig.install("en_GB-b-medium.onnx", b"someone else's bytes")

    plan = rig.prefetch().plan()
    result = rig.prefetch().run()

    names = [a.name for a in plan.assets]
    assert "en_US-a-medium.onnx" not in names and "en_GB-b-medium.onnx" not in names
    assert plan.conflicts == (other,)
    assert f"conflict: {other}" in plan.skipped
    assert result == PrefetchResult("complete", files=5, skipped=(f"conflict: {other}",))
    assert other.read_bytes() == b"someone else's bytes"
    assert rig.server.hits("en_GB-b-medium.onnx") == rig.server.hits("en_US-a-medium.onnx") == 0
    assert "en_GB-b-medium.onnx" in logs()


def test_a_directory_in_place_of_a_file_is_a_conflict(rig: Rig) -> None:
    (rig.settings.voices_dir / FIRST).mkdir(parents=True)

    assert rig.prefetch().plan().conflicts == (rig.settings.voices_dir / FIRST,)


def test_a_file_in_place_of_the_voices_dir_turns_its_files_into_conflicts(rig: Rig) -> None:
    rig.settings.data_dir.mkdir(parents=True)
    rig.settings.voices_dir.write_bytes(b"not a directory")

    plan = rig.prefetch().plan()

    assert plan.conflicts == tuple(rig.target(n) for n in ORDER[:4])
    assert [a.name for a in plan.assets] == ORDER[4:]


def test_a_dangling_symlink_is_missing_and_a_live_link_into_an_app_is_present(
    rig: Rig, tmp_path: Path
) -> None:
    bundled = tmp_path / "Cloudy Reader.app" / "Contents" / "Resources" / "assets" / "voices"
    bundled.mkdir(parents=True)
    (bundled / "en_US-a-medium.onnx").write_bytes(payload("en_US-a-medium.onnx"))
    rig.settings.voices_dir.mkdir(parents=True)
    (rig.settings.voices_dir / "en_US-a-medium.onnx").symlink_to(bundled / "en_US-a-medium.onnx")
    (rig.settings.voices_dir / "en_GB-b-medium.onnx").symlink_to(tmp_path / "Moved.app" / "x")

    names = [a.name for a in rig.prefetch().plan().assets]

    assert "en_US-a-medium.onnx" not in names
    assert "en_GB-b-medium.onnx" in names


def test_kokoro_files_are_skipped_with_a_reason_when_kokoro_cannot_run_here(rig: Rig) -> None:
    plan = rig.prefetch(kokoro_ready=lambda: False).plan()
    result = rig.prefetch(kokoro_ready=lambda: False).run()

    assert {a.group for a in plan.assets} == {"voices"}
    assert [s for s in plan.skipped if s.startswith("kokoro:")] == list(plan.skipped)
    assert len(plan.skipped) == 1
    assert (result.outcome, result.files, result.skipped) == ("complete", 4, plan.skipped)
    assert not any("/kokoro/" in r.url.path for r in rig.server.requests)


def test_kokoro_check_runs_only_when_a_kokoro_file_is_missing(rig: Rig) -> None:
    for item in KOKORO:
        rig.install(item["name"])
    asked: list[int] = []

    plan = rig.prefetch(kokoro_ready=lambda: asked.append(1) or False).plan()

    assert asked == []
    assert [a.name for a in plan.assets] == ORDER[:4]


def test_default_kokoro_check_needs_apple_silicon_and_every_backend_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kokoro = pytest.importorskip("cloudyreader.engines.kokoro")
    found = set(kokoro.BACKEND_MODULES)
    monkeypatch.setattr(prefetch.sys, "platform", "darwin")
    monkeypatch.setattr(prefetch.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        prefetch.importlib.util, "find_spec", lambda name: object() if name in found else None
    )

    assert prefetch.kokoro_supported() is True
    found.discard("mlx_audio")
    assert prefetch.kokoro_supported() is False
    found.add("mlx_audio")
    monkeypatch.setattr(prefetch.platform, "machine", lambda: "x86_64")
    assert prefetch.kokoro_supported() is False


def test_default_kokoro_check_is_false_when_the_engine_will_not_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prefetch.sys, "platform", "darwin")
    monkeypatch.setattr(prefetch.platform, "machine", lambda: "arm64")
    monkeypatch.setitem(sys.modules, "cloudyreader.engines.kokoro", None)  # `import` now raises

    assert prefetch.kokoro_supported() is False


# --- run ------------------------------------------------------------------------------------------


def test_run_installs_every_missing_file_with_its_pinned_bytes(rig: Rig) -> None:
    result = rig.prefetch().run()

    assert result == PrefetchResult("complete", files=7)
    for name in ORDER:
        assert rig.target(name).read_bytes() == payload(name)
    assert not rig.target("ner-0.1.tar.gz").exists()
    assert rig.leftovers() == []
    assert stat.S_IMODE(rig.stage.stat().st_mode) == 0o700
    assert [r.url.path for r in rig.server.requests] == [url_path(n) for n in ORDER]
    for request in rig.server.requests:
        assert (request.method, request.url.scheme) == ("GET", "https")
        assert request.headers["accept-encoding"] == "identity"
        assert request.headers["user-agent"] == "cloudyreader-prefetch/0.1"
        assert not {"authorization", "cookie", "range"} & set(request.headers)
        assert request.extensions["timeout"] == {
            "connect": 10,
            "read": 30,
            "write": 30,
            "pool": 30,
        }
    assert rig.prefetch().run() == PrefetchResult("nothing")
    assert len(rig.server.requests) == 7


def test_without_an_injected_client_run_builds_its_own_and_closes_it(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[tuple[dict, httpx.Client]] = []

    def factory(**kwargs) -> httpx.Client:
        client = REAL_CLIENT(transport=httpx.MockTransport(rig.server), **kwargs)
        built.append((kwargs, client))
        return client

    monkeypatch.setattr(httpx, "Client", factory)

    assert rig.prefetch(client=None).run() == PrefetchResult("complete", files=7)
    ((kwargs, client),) = built
    assert kwargs == {"timeout": prefetch.TIMEOUT, "follow_redirects": False}
    assert client.is_closed


def test_each_piper_config_is_moved_in_before_its_model(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    moved: list[str] = []
    real = os.replace

    def spy(src, dst):
        moved.append(Path(dst).name)
        real(src, dst)

    monkeypatch.setattr(prefetch.os, "replace", spy)

    rig.prefetch().run()

    assert moved == ORDER


def test_progress_is_monotonic_and_ends_at_the_total(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prefetch, "PROGRESS_INTERVAL_S", 3600.0)  # a slow machine adds no event
    events: list[PrefetchProgress] = []

    rig.prefetch().run(events.append)

    assert len(events) == 2 * len(ORDER)  # one at the start and one at the end of each file
    assert {(e.total_bytes, e.files_total) for e in events} == {(TOTAL, 7)}
    done = [e.done_bytes for e in events]
    assert done == sorted(done)
    assert [e.files_done for e in events] == sorted(e.files_done for e in events)
    assert [e.file for e in events[::2]] == ORDER
    assert events[-1] == PrefetchProgress("af_heart.safetensors", TOTAL, TOTAL, 7, 7)


def test_progress_reports_partial_bytes_while_a_file_streams(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prefetch, "CHUNK", 8)
    monkeypatch.setattr(prefetch, "PROGRESS_INTERVAL_S", 0.0)
    events: list[PrefetchProgress] = []

    rig.prefetch().run(events.append)

    first = [e.done_bytes for e in events if e.file == FIRST]
    assert first[:3] == [0, 8, 16]
    assert first[-1] == len(payload(FIRST))
    assert [e.done_bytes for e in events] == sorted(e.done_bytes for e in events)


def test_progress_while_streaming_waits_for_the_interval(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prefetch, "CHUNK", 8)
    monkeypatch.setattr(prefetch.time, "monotonic", lambda: 1000.0)  # the clock never moves
    events: list[PrefetchProgress] = []

    rig.prefetch().run(events.append)

    assert len(events) == 2 * len(ORDER)


def test_a_raising_progress_callback_is_logged_once_and_ignored(rig: Rig, logs) -> None:
    def broken(event: PrefetchProgress) -> None:
        raise RuntimeError("window gone")

    assert rig.prefetch().run(broken) == PrefetchResult("complete", files=7)
    assert logs().count("progress callback failed") == 1


def test_run_never_raises_on_an_unexpected_error(
    rig: Rig, logs, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.server.routes[url_path("en_US-a-medium.onnx")] = lambda request: 1 / 0

    result = rig.prefetch().run()

    assert result == PrefetchResult("partial", files=2, failed=("en_US-a-medium.onnx",))
    assert "ZeroDivisionError" in logs()
    monkeypatch.setattr(VoicePrefetch, "plan", lambda self: None)
    assert rig.prefetch().run() == PrefetchResult("partial")


def test_importing_prefetch_loads_no_heavy_module() -> None:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import cloudyreader.prefetch\n"
        "heavy = ('PySide6', 'spacy', 'piper', 'onnxruntime', 'numpy', 'mlx',\n"
        "         'cloudyreader.engines.kokoro')\n"
        "loaded = [m for m in heavy if m in sys.modules]\n"
        "assert not loaded, loaded\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


# --- failures -------------------------------------------------------------------------------------


def test_a_sha256_mismatch_is_not_installed_and_the_next_file_still_comes(rig: Rig, logs) -> None:
    rig.server.routes[url_path(FIRST)] = serve(b"x" * len(payload(FIRST)))

    result = rig.prefetch().run()

    assert result == PrefetchResult("partial", files=6, failed=(FIRST,))
    assert not rig.target(FIRST).exists()
    assert rig.server.hits(FIRST) == 1
    assert rig.target(ORDER[1]).read_bytes() == payload(ORDER[1])
    assert "SHA-256" in logs()
    assert rig.leftovers() == []


def test_a_short_read_is_retried_and_the_second_attempt_succeeds(rig: Rig) -> None:
    body = payload(FIRST)
    answers = iter([body[:-1], body])
    # A streamed body has no Content-Length, so only the byte count can tell it is short.
    rig.server.routes[url_path(FIRST)] = lambda r: httpx.Response(
        200, content=iter([next(answers)])
    )

    result = rig.prefetch().run()

    assert result == PrefetchResult("complete", files=7)
    assert rig.server.hits(FIRST) == 2
    assert rig.target(FIRST).read_bytes() == body


def test_a_short_read_three_times_fails_that_file(rig: Rig) -> None:
    short = payload(FIRST)[:-1]
    rig.server.routes[url_path(FIRST)] = lambda r: httpx.Response(200, content=iter([short]))

    result = rig.prefetch().run()

    assert result == PrefetchResult("partial", files=6, failed=(FIRST,))
    assert rig.server.hits(FIRST) == 3
    assert rig.leftovers() == []


def test_a_body_above_the_pinned_size_stops_at_the_cap(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prefetch, "CHUNK", 8)
    body, pulled = payload(FIRST), []

    def endless(request: httpx.Request) -> httpx.Response:
        def chunks() -> Iterator[bytes]:
            for index in range(1000):
                pulled.append(index)
                yield body

        return httpx.Response(200, content=chunks())

    rig.server.routes[url_path(FIRST)] = endless

    result = rig.prefetch().run()

    assert result == PrefetchResult("partial", files=6, failed=(FIRST,))
    assert len(pulled) == 2  # the pinned size, then one more chunk: never the rest
    assert rig.server.hits(FIRST) == 1
    assert not rig.target(FIRST).exists()
    assert rig.leftovers() == []


def test_a_client_error_is_final_after_one_request(rig: Rig) -> None:
    rig.server.routes[url_path(FIRST)] = lambda r: httpx.Response(404)

    assert rig.prefetch().run() == PrefetchResult("partial", files=6, failed=(FIRST,))
    assert rig.server.hits(FIRST) == 1


def raise_(error: type[httpx.TransportError]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error("no route to https://cdn.example/blob?sig=token", request=request)

    return handler


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500),
        lambda r: httpx.Response(503),
        lambda r: httpx.Response(429),
        raise_(httpx.ConnectError),
        raise_(httpx.ReadTimeout),
    ],
    ids=["500", "503", "429", "connect-error", "read-timeout"],
)
def test_transient_failures_are_tried_three_times(rig: Rig, logs, handler) -> None:
    rig.server.routes[url_path(FIRST)] = handler

    result = rig.prefetch().run()

    assert result == PrefetchResult("partial", files=6, failed=(FIRST,))
    assert rig.server.hits(FIRST) == 3
    assert "https://" not in logs() and "sig=" not in logs()


def test_the_backoff_grows_with_each_attempt(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    rig.server.routes[url_path(FIRST)] = lambda r: httpx.Response(500)
    cancel = threading.Event()
    monkeypatch.setattr(cancel, "wait", lambda timeout: waits.append(timeout) or False)

    rig.prefetch(retry_delay_s=2.0).run(cancel=cancel)

    assert waits == [2.0, 4.0]


def test_an_https_redirect_is_followed_and_a_relative_location_resolved(rig: Rig) -> None:
    rig.server.routes[url_path(FIRST)] = redirect("https://cdn.example/blob/1")
    rig.server.routes["/blob/1"] = redirect("/blob/2?sig=token", 307)
    rig.server.routes["/blob/2"] = serve(payload(FIRST))

    assert rig.prefetch().run() == PrefetchResult("complete", files=7)
    hops = [(r.url.host, r.url.path) for r in rig.server.requests[:3]]
    assert hops == [
        ("files.example", url_path(FIRST)),
        ("cdn.example", "/blob/1"),
        ("cdn.example", "/blob/2"),
    ]
    assert {r.headers["user-agent"] for r in rig.server.requests[:3]} == {
        "cloudyreader-prefetch/0.1"
    }


def test_a_redirect_to_plain_http_is_refused_and_never_logged(rig: Rig, logs) -> None:
    rig.server.routes[url_path(FIRST)] = redirect("http://cdn.example/blob?sig=token")

    result = rig.prefetch().run()

    assert result == PrefetchResult("partial", files=6, failed=(FIRST,))
    assert rig.server.hits(FIRST) == 1
    assert not any(r.url.scheme == "http" for r in rig.server.requests)
    assert "non-HTTPS redirect" in logs()
    assert "cdn.example" not in logs() and "sig=" not in logs()


def chain(rig: Rig, hops: int) -> None:
    """FIRST answers with `hops` redirects in a row before the payload."""
    rig.server.routes[url_path(FIRST)] = redirect("https://cdn.example/hop/1")
    for n in range(1, hops):
        rig.server.routes[f"/hop/{n}"] = redirect(f"/hop/{n + 1}")
    rig.server.routes[f"/hop/{hops}"] = serve(payload(FIRST))


def test_five_redirects_are_followed(rig: Rig) -> None:
    chain(rig, 5)

    assert rig.prefetch().run() == PrefetchResult("complete", files=7)


def test_a_sixth_redirect_is_refused(rig: Rig) -> None:
    chain(rig, 6)

    result = rig.prefetch().run()

    assert result == PrefetchResult("partial", files=6, failed=(FIRST,))
    assert [r.url.path for r in rig.server.requests[:6]] == [url_path(FIRST)] + [
        f"/hop/{n}" for n in range(1, 6)
    ]
    assert not any(r.url.path == "/hop/6" for r in rig.server.requests)


def test_a_content_length_other_than_the_pin_fails_before_the_body_is_read(rig: Rig) -> None:
    pulled: list[int] = []

    def wrong(request: httpx.Request) -> httpx.Response:
        def chunks() -> Iterator[bytes]:
            pulled.append(1)
            yield payload(FIRST)

        size = str(len(payload(FIRST)) + 1)
        return httpx.Response(200, content=chunks(), headers={"Content-Length": size})

    rig.server.routes[url_path(FIRST)] = wrong

    assert rig.prefetch().run() == PrefetchResult("partial", files=6, failed=(FIRST,))
    assert pulled == []
    assert rig.server.hits(FIRST) == 1


def test_open_https_refuses_a_plain_http_url_without_a_request(rig: Rig) -> None:
    with pytest.raises(PrefetchError, match="non-HTTPS URL"):
        open_https(rig.client, "http://files.example/x")
    with pytest.raises(PrefetchError, match="malformed URL"):
        open_https(rig.client, "https://files.example:port/x")
    assert rig.server.requests == []


def test_open_https_keeps_the_redirect_history_and_extra_headers(rig: Rig) -> None:
    chain(rig, 2)

    response = open_https(rig.client, ENTRIES[FIRST]["url"], headers={"Range": "bytes=0-0"})
    response.close()

    assert response.status_code == 200
    assert [r.status_code for r in response.history] == [302, 302]
    assert {r.headers["range"] for r in rig.server.requests} == {"bytes=0-0"}


# --- offline and cancel ---------------------------------------------------------------------------


def test_offline_sends_nothing_and_makes_no_directory(rig: Rig) -> None:
    offline = dataclasses.replace(rig.settings, offline=True)

    assert VoicePrefetch(offline, lock_path=rig.lock).run() == PrefetchResult("offline")
    assert VoicePrefetch(offline, lock_path=rig.lock, client=rig.client).run().outcome == "offline"
    assert rig.server.requests == []
    assert not rig.settings.data_dir.exists()


def test_cancel_before_the_start_sends_nothing(rig: Rig) -> None:
    cancel = threading.Event()
    cancel.set()

    assert rig.prefetch().run(cancel=cancel) == PrefetchResult("cancelled")
    assert rig.server.requests == []
    assert not rig.settings.data_dir.exists()


def test_cancel_mid_stream_keeps_finished_files_and_removes_the_part(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prefetch, "CHUNK", 8)
    cancel, third = threading.Event(), ORDER[2]

    def cancelling(request: httpx.Request) -> httpx.Response:
        body = payload(third)

        def chunks() -> Iterator[bytes]:
            yield body[:8]
            cancel.set()  # the window closes while the third file streams
            yield body[8:]

        return httpx.Response(200, content=chunks())

    rig.server.routes[url_path(third)] = cancelling

    result = rig.prefetch().run(cancel=cancel)

    assert result == PrefetchResult("cancelled", files=2)
    assert [rig.target(n).exists() for n in ORDER] == [True, True] + [False] * 5
    assert len(rig.server.requests) == 3
    assert rig.leftovers() == []


def test_cancel_during_the_backoff_returns_at_once(rig: Rig) -> None:
    cancel = threading.Event()

    def busy(request: httpx.Request) -> httpx.Response:
        cancel.set()
        return httpx.Response(503)

    rig.server.routes[url_path(FIRST)] = busy
    started = time.monotonic()

    result = rig.prefetch(retry_delay_s=60.0).run(cancel=cancel)

    assert time.monotonic() - started < 10
    assert result == PrefetchResult("cancelled")
    assert len(rig.server.requests) == 1


def test_cancel_between_files_stops_before_the_next_request(rig: Rig) -> None:
    cancel = threading.Event()

    def stop_after_first(event: PrefetchProgress) -> None:
        if event.files_done == 1:
            cancel.set()

    result = rig.prefetch().run(stop_after_first, cancel)

    assert result == PrefetchResult("cancelled", files=1)
    assert len(rig.server.requests) == 1


# --- destination ----------------------------------------------------------------------------------


def test_a_dangling_symlink_is_replaced_and_its_target_never_written(
    rig: Rig, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere" / FIRST
    rig.settings.voices_dir.mkdir(parents=True)
    link = rig.settings.voices_dir / FIRST
    link.symlink_to(elsewhere)

    assert rig.prefetch().run() == PrefetchResult("complete", files=7)
    assert not link.is_symlink()
    assert link.read_bytes() == payload(FIRST)
    assert not elsewhere.parent.exists()


def test_a_destination_inside_an_app_bundle_is_refused_before_any_request(
    rig: Rig, tmp_path: Path, logs
) -> None:
    inside = tmp_path / "X.app" / "Contents" / "Resources" / "assets" / "voices"
    inside.mkdir(parents=True)
    rig.settings.data_dir.mkdir(parents=True)
    rig.settings.voices_dir.symlink_to(inside, target_is_directory=True)

    result = rig.prefetch().run()

    assert result == PrefetchResult("partial", files=3, failed=tuple(ORDER[:4]))
    assert list(inside.iterdir()) == []
    assert [r.url.path for r in rig.server.requests] == [url_path(n) for n in ORDER[4:]]
    assert "app bundle" in logs()


def test_a_stage_dir_inside_an_app_bundle_is_refused(rig: Rig, tmp_path: Path) -> None:
    inside = tmp_path / "Y.APP" / "Contents" / "stage"
    inside.mkdir(parents=True)
    rig.settings.data_dir.mkdir(parents=True)
    rig.stage.symlink_to(inside, target_is_directory=True)

    result = rig.prefetch().run()

    assert (result.outcome, result.files) == ("partial", 0)
    assert list(inside.iterdir()) == []
    assert rig.server.requests == []


def test_a_stage_dir_that_will_not_resolve_fails_every_file_without_a_request(
    rig: Rig, logs
) -> None:
    rig.settings.data_dir.mkdir(parents=True)
    rig.stage.symlink_to(rig.stage)  # a symlink loop

    result = rig.prefetch().run()

    assert result == PrefetchResult("partial", failed=tuple(ORDER))
    assert rig.server.requests == []
    assert "cannot resolve" in logs()


def test_a_failing_sweep_is_logged_and_the_run_goes_on(
    rig: Rig, logs, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.stage.mkdir(parents=True)

    def denied(self: Path, pattern: str) -> Iterator[Path]:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(prefetch.Path, "glob", denied)

    assert rig.prefetch().run() == PrefetchResult("complete", files=7)
    assert "sweep stopped: PermissionError" in logs()


def test_a_destination_that_appears_before_the_move_is_left_alone(rig: Rig) -> None:
    def racing(request: httpx.Request) -> httpx.Response:
        rig.install(FIRST, b"installed meanwhile")  # another process wins the race
        return wire(payload(FIRST))

    rig.server.routes[url_path(FIRST)] = racing

    result = rig.prefetch().run()

    assert result == PrefetchResult("complete", files=6, skipped=(f"exists: {rig.target(FIRST)}",))
    assert rig.target(FIRST).read_bytes() == b"installed meanwhile"
    assert rig.leftovers() == []


def test_a_failing_move_fails_that_file_only(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    real = os.replace

    def replace(src, dst):
        if Path(dst).name == FIRST:
            raise OSError(18, "Cross-device link")
        real(src, dst)

    monkeypatch.setattr(prefetch.os, "replace", replace)

    result = rig.prefetch().run()

    assert result == PrefetchResult("partial", files=6, failed=(FIRST,))
    assert rig.server.hits(FIRST) == 1  # a local disk error is not retried
    assert rig.leftovers() == []


def test_stale_parts_are_swept_and_fresh_ones_kept(rig: Rig) -> None:
    rig.stage.mkdir(parents=True)
    stale, fresh, other = rig.stage / "a.part", rig.stage / "b.part", rig.stage / "keep.txt"
    for path in (stale, fresh, other):
        path.write_bytes(b"x")
    old = time.time() - 25 * 3600
    os.utime(stale, (old, old))
    os.utime(other, (old, old))

    rig.prefetch().run()

    assert (stale.exists(), fresh.exists(), other.exists()) == (False, True, True)


def test_a_symlinked_stage_dir_is_never_swept(rig: Rig, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    stale = elsewhere / "c.part"
    stale.write_bytes(b"x")
    old = time.time() - 25 * 3600
    os.utime(stale, (old, old))
    rig.settings.data_dir.mkdir(parents=True)
    rig.stage.symlink_to(elsewhere, target_is_directory=True)

    rig.prefetch().run()

    assert stale.exists()
