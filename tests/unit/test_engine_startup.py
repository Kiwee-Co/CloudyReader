"""The startup run with the engine groups: order, per-group checks, Range resume, group progress."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath

import httpx
import pytest

from cloudyreader import engine_catalog, prefetch
from cloudyreader.config import Settings
from cloudyreader.prefetch import PrefetchProgress, PrefetchResult, VoicePrefetch

REAL_CLIENT = httpx.Client
REV = "89abcdef0123456789abcdef0123456789abcdef"
GATE = "waiting for a Qwen3 decoder fix"
PLENTY = 1 << 50
BIG = "model.safetensors"  # the qwen file the resume tests bend


def payload(group: str, rel: str) -> bytes:
    return (f"{group}/{rel}".encode() + b"\n") * 6


def entry(group: str, rel: str, **overrides) -> dict:
    sub, _, name = rel.rpartition("/")
    data = payload(group, rel)
    if group in ("chatterbox_turbo", "qwen3_tts"):
        url = f"https://files.example/{group}/resolve/{REV}/{rel}"
        dest = f".data/models/{group}" + (f"/{sub}" if sub else "")
    elif group == "voices":
        url, dest = f"https://files.example/voices/{rel}", ".data/voices"
    else:
        url = f"https://files.example/{group}/{rel}"
        dest = f".data/models/{group}" + (f"/{sub}" if sub else "")
    item = {
        "name": name,
        "group": group,
        "url": url,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "dest": dest,
    }
    return item | overrides


# Engines first in the lock: the plan must sort the groups. Inside a group, small files first,
# as the pin script writes them.
ENGINES = [
    ("qwen3_tts", "config.json"),
    ("qwen3_tts", "merges.txt"),
    ("qwen3_tts", "model.safetensors"),
    ("qwen3_tts", "speech_tokenizer/model.safetensors"),
    ("chatterbox_turbo", "config.json"),
    ("chatterbox_turbo", "model.safetensors"),
]
VOICES = [
    ("kokoro", "config.json"),
    ("voices", "en_US-a-medium.onnx"),
    ("voices", "en_US-a-medium.onnx.json"),
]
ORDER = [
    ("voices", "en_US-a-medium.onnx.json"),
    ("voices", "en_US-a-medium.onnx"),
    ("kokoro", "config.json"),
    ("chatterbox_turbo", "config.json"),
    ("chatterbox_turbo", "model.safetensors"),
    ("qwen3_tts", "config.json"),
    ("qwen3_tts", "merges.txt"),
    ("qwen3_tts", "model.safetensors"),
    ("qwen3_tts", "speech_tokenizer/model.safetensors"),
]


def group_bytes(group: str) -> int:
    return sum(len(payload(g, rel)) for g, rel in ORDER if g == group)


def go() -> str | None:
    return None


ALL_READY: dict[str, Callable[[], str | None]] = {"kokoro": go, "chatterbox_turbo": go}
ALL_READY["qwen3_tts"] = go


def url_path(group: str, rel: str) -> str:
    return httpx.URL(entry(group, rel)["url"]).path


def wire(body: bytes, status: int = 200, **headers: str) -> httpx.Response:
    """An answer as a transport delivers it: headers and an unread stream."""
    return httpx.Response(
        status,
        headers={"Content-Length": str(len(body)), **headers},
        stream=httpx.ByteStream(body),
    )


def short(body: bytes, keep: int) -> httpx.Response:
    """A 200 that announces the whole file and stops after `keep` bytes."""
    headers = {"Content-Length": str(len(body))}
    return httpx.Response(200, headers=headers, stream=httpx.ByteStream(body[:keep]))


def ranged(body: bytes, start: int, *, end: int | None = None, total: int | None = None):
    end = len(body) - 1 if end is None else end
    total = len(body) if total is None else total
    return wire(body[start : end + 1], 206, **{"Content-Range": f"bytes {start}-{end}/{total}"})


def asked_start(request: httpx.Request) -> int:
    return int(request.headers["range"].removeprefix("bytes=").removesuffix("-"))


class Server:
    """Serves every lock entry; a test bends one path by setting `routes[path]`."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.bodies = {url_path(g, rel): payload(g, rel) for g, rel in ENGINES + VOICES}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get(request.url.path)
        if handler is not None:
            return handler(request)
        body = self.bodies.get(request.url.path)
        return httpx.Response(404) if body is None else wire(body)

    def asked(self, group: str) -> list[str]:
        prefix = f"/{group}/"
        return [r.url.path for r in self.requests if r.url.path.startswith(prefix)]

    def ranges(self, group: str, rel: str) -> list[str | None]:
        return [r.headers.get("range") for r in self.requests if r.url.path == url_path(group, rel)]


class Rig:
    def __init__(self, root: Path) -> None:
        data = root / "data"
        self.settings = Settings(data, data / "cache", data / "voices", data / "models")
        self.lock = root / "assets.lock.json"
        self.write_lock(ENGINES + VOICES)
        self.server = Server()
        self.client = REAL_CLIENT(transport=httpx.MockTransport(self.server))

    def write_lock(self, files: list[tuple[str, str]]) -> None:
        entries = [entry(group, rel) for group, rel in files]
        self.lock.write_text(json.dumps({"version": 1, "assets": entries}))

    def prefetch(self, **changes) -> VoicePrefetch:
        """Every group may download and the disk is huge, unless a test says otherwise. A partial
        `ready` map is laid over that, so no test ever reaches this machine's real checks."""
        if changes.get("ready") is not None:
            changes["ready"] = ALL_READY | changes["ready"]
        options = {
            "lock_path": self.lock,
            "client": self.client,
            "retry_delay_s": 0.0,
            "ready": ALL_READY,
            "free_bytes": lambda path: PLENTY,
        }
        return VoicePrefetch(self.settings, **(options | changes))

    def target(self, group: str, rel: str) -> Path:
        root, *rest = PurePosixPath(entry(group, rel)["dest"]).parts[1:]
        base = self.settings.voices_dir if root == "voices" else self.settings.models_dir
        return base.joinpath(*rest, rel.rpartition("/")[2])

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


def everything() -> PrefetchResult:
    return PrefetchResult("complete", files=len(ORDER))


def need(missing: int) -> int:
    return math.ceil(missing * prefetch.DISK_FACTOR) + prefetch.DISK_MARGIN


# --- groups and order -----------------------------------------------------------------------------


def test_engine_groups_join_fetched_in_the_order_voices_kokoro_chatterbox_qwen(rig: Rig) -> None:
    assert list(prefetch.FETCHED) == ["voices", "kokoro", "chatterbox_turbo", "qwen3_tts"]
    assert prefetch.VOICE_GROUPS == ("voices", "kokoro")
    assert (
        prefetch.ENGINE_GROUPS == ("chatterbox_turbo", "qwen3_tts") == tuple(engine_catalog.SPECS)
    )
    assert prefetch.GROUPS == ("models", "voices", "kokoro", "chatterbox_turbo", "qwen3_tts")
    assert prefetch.DATA_SUFFIXES == (".onnx", ".json", ".safetensors", ".txt")
    assert (prefetch.DISK_FACTOR, prefetch.DISK_MARGIN) == (1.1, 1 << 30)

    plan = rig.prefetch().plan()

    assert [(a.group, a.path) for a in plan.assets] == [(g, rig.target(g, r)) for g, r in ORDER]
    assert rig.prefetch().run() == everything()
    assert [r.url.path for r in rig.server.requests] == [url_path(g, r) for g, r in ORDER]


def test_a_lock_without_engine_entries_is_valid_and_plans_nothing_for_engines(rig: Rig) -> None:
    asked: list[str] = []
    checks = {g: (lambda g=g: asked.append(g)) for g in prefetch.ENGINE_GROUPS}
    rig.write_lock(VOICES)

    plan = rig.prefetch(ready=checks).plan()
    result = rig.prefetch(ready=checks).run()

    assert {a.group for a in plan.assets} == {"voices", "kokoro"}
    assert result == PrefetchResult("complete", files=3)
    assert asked == []  # a group with nothing missing is never asked


def test_groups_seam_limits_the_plan(rig: Rig) -> None:
    voices = rig.prefetch(groups=prefetch.VOICE_GROUPS)

    assert {a.group for a in voices.plan().assets} == {"voices", "kokoro"}
    assert {a.group for a in voices.plan(groups=("qwen3_tts",)).assets} == {"qwen3_tts"}
    assert voices.run() == PrefetchResult("complete", files=3)
    assert rig.server.asked("qwen3_tts") == rig.server.asked("chatterbox_turbo") == []


@pytest.mark.parametrize(
    ("group", "rel", "overrides"),
    [
        ("qwen3_tts", "speech_tokenizer/config.json", {}),
        ("qwen3_tts", "tokenizer/vocab.json", {}),  # ONE safe sub-folder, any name
        ("qwen3_tts", "merges.txt", {}),
        ("chatterbox_turbo", "conds.safetensors", {}),
        ("voices", "en_US-a-medium.txt", {}),
    ],
)
def test_engine_entry_rules_accept(rig: Rig, group: str, rel: str, overrides: dict) -> None:
    rig.lock.write_text(json.dumps({"version": 1, "assets": [entry(group, rel, **overrides)]}))

    plan = rig.prefetch().plan()

    assert [a.name for a in plan.assets] == [rel.rpartition("/")[2]]


ENGINE_URL = f"https://files.example/qwen3_tts/resolve/{REV}/config.json"


@pytest.mark.parametrize(
    ("rel", "overrides"),
    [
        ("config.json", {"dest": ".data/models/kokoro"}),  # another group's folder
        ("config.json", {"dest": ".data/models/qwen3_tts/speech_tokenizer/extra"}),
        ("config.json", {"dest": ".data/models"}),
        ("config.json", {"dest": ".data/voices"}),
        ("config.json", {"dest": ".data/models/qwen3_tts/.hidden"}),
        ("config.json", {"dest": ".data/models/qwen3_tts/.."}),
        ("config.json", {"dest": "/data/models/qwen3_tts"}),
        ("config.json", {"url": "https://files.example/qwen3_tts/resolve/main/config.json"}),
        ("config.json", {"url": f"https://files.example/qwen3_tts/resolve/{REV[:-1]}/config.json"}),
        ("config.json", {"url": f"https://files.example/qwen3_tts/resolve/{REV.upper()}/c.json"}),
        ("config.json", {"url": "https://files.example/qwen3_tts/config.json"}),
        ("config.json", {"url": f"https://files.example/x?ref=/resolve/{REV}/config.json"}),
        ("model.onnx", {}),  # engine files: .safetensors .json .txt only
        ("model.py", {}),
        ("weights.npy", {}),
        ("chat_template.jinja", {}),
        ("conds.pt", {}),
        ("pytorch_model.bin", {}),
    ],
)
def test_engine_entry_rules_reject_the_whole_lock(rig: Rig, rel: str, overrides: dict) -> None:
    rig.lock.write_text(
        json.dumps(
            {
                "version": 1,
                "assets": [entry("voices", "a.onnx.json"), entry("qwen3_tts", rel, **overrides)],
            }
        )
    )

    result = rig.prefetch().run()

    assert result.outcome == "nothing"
    assert result.skipped[0].startswith("invalid assets.lock.json")
    assert rig.server.requests == []


# --- per-group checks -----------------------------------------------------------------------------


def test_a_group_whose_ready_gives_a_reason_is_skipped_with_it_and_sends_no_request(
    rig: Rig,
) -> None:
    ready = {"qwen3_tts": lambda: GATE, "chatterbox_turbo": lambda: None}

    plan = rig.prefetch(ready=ready).plan()
    result = rig.prefetch(ready=ready).run()

    assert "qwen3_tts" not in {a.group for a in plan.assets}
    assert plan.skipped == (f"qwen3_tts: {GATE}",)
    assert result == PrefetchResult("complete", files=len(ORDER) - 4, skipped=plan.skipped)
    assert rig.server.asked("qwen3_tts") == []
    assert not (rig.settings.models_dir / "qwen3_tts").exists()


def test_a_blocked_group_does_not_stop_the_next_one(rig: Rig) -> None:
    ready = {"chatterbox_turbo": lambda: "needs an Apple Silicon Mac (arm64)"}

    result = rig.prefetch(ready=ready).run()

    assert result.skipped == ("chatterbox_turbo: needs an Apple Silicon Mac (arm64)",)
    assert result.files == len(ORDER) - 2
    assert rig.server.asked("chatterbox_turbo") == []
    assert len(rig.server.asked("qwen3_tts")) == 4


def test_the_default_ready_map_asks_the_catalog_for_engines_and_kokoro_ready_for_kokoro(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def ready_reason(group: str) -> str | None:
        asked.append(group)
        return "not in this build" if group == "qwen3_tts" else None

    monkeypatch.setattr(engine_catalog, "ready_reason", ready_reason)

    plan = rig.prefetch(ready=None, kokoro_ready=lambda: False).plan()

    assert asked == ["chatterbox_turbo", "qwen3_tts"]
    assert plan.skipped == (
        "kokoro: needs an Apple Silicon Mac with the Kokoro packages",
        "qwen3_tts: not in this build",
    )
    assert {a.group for a in plan.assets} == {"voices", "chatterbox_turbo"}


def test_a_partial_ready_map_keeps_the_defaults_for_the_other_groups(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_catalog, "ready_reason", lambda group: f"default for {group}")
    fetch = VoicePrefetch(
        rig.settings,
        lock_path=rig.lock,
        client=rig.client,
        kokoro_ready=lambda: True,
        ready={"qwen3_tts": go},
        free_bytes=lambda path: PLENTY,
    )

    assert fetch.plan().skipped == ("chatterbox_turbo: default for chatterbox_turbo",)


def test_a_raising_ready_check_skips_only_its_group(rig: Rig) -> None:
    def broken() -> str | None:
        raise RuntimeError("bad check")

    result = rig.prefetch(ready={"qwen3_tts": broken}).run()

    assert result.skipped == ("qwen3_tts: check failed (RuntimeError)",)
    assert result.files == len(ORDER) - 4


def test_disk_is_checked_before_each_engine_with_size_x_1_1_plus_1_gib(rig: Rig) -> None:
    rig.settings.data_dir.mkdir(parents=True)
    chatterbox, qwen = group_bytes("chatterbox_turbo"), group_bytes("qwen3_tts")
    # plan: chatterbox, qwen; then right before each group's first request: chatterbox, qwen.
    answers = iter([need(chatterbox), need(qwen), need(chatterbox), need(qwen) - 1])
    asked: list[Path] = []

    def free_bytes(path: Path) -> int:
        asked.append(path)
        return next(answers)

    result = rig.prefetch(free_bytes=free_bytes).run()

    reason = engine_catalog.space_reason(rig.settings.models_dir, qwen, lambda p: need(qwen) - 1)
    assert result.skipped == (f"qwen3_tts: {reason}",)
    assert reason.startswith("not enough disk space: needs 1.1 GB, ")
    assert result.files == len(ORDER) - 4
    assert rig.server.asked("qwen3_tts") == []
    assert len(asked) == 4
    assert asked[:2] == [rig.settings.data_dir] * 2  # nothing exists below data_dir at plan time
    assert asked[2:] == [rig.settings.models_dir] * 2  # kokoro made models_dir by then


def test_low_disk_at_plan_time_skips_the_group_before_any_request(rig: Rig) -> None:
    result = rig.prefetch(free_bytes=lambda path: 0).run()

    assert [s.partition(":")[0] for s in result.skipped] == ["chatterbox_turbo", "qwen3_tts"]
    assert all(": not enough disk space: " in s for s in result.skipped)
    assert result == PrefetchResult("complete", files=3, skipped=result.skipped)


def test_an_unwritable_models_dir_skips_engines_with_a_reason(rig: Rig) -> None:
    if os.geteuid() == 0:
        pytest.skip("root can write anywhere")
    rig.write_lock([f for f in ENGINES + VOICES if f[0] != "kokoro"])
    rig.settings.models_dir.mkdir(parents=True)
    rig.settings.models_dir.chmod(0o500)
    try:
        result = rig.prefetch().run()
    finally:
        rig.settings.models_dir.chmod(0o700)

    assert result.skipped == (
        f"chatterbox_turbo: {engine_catalog.NOT_WRITABLE}",
        f"qwen3_tts: {engine_catalog.NOT_WRITABLE}",
    )
    assert result.files == 2
    assert rig.server.asked("chatterbox_turbo") == rig.server.asked("qwen3_tts") == []


def test_the_room_check_runs_again_right_before_the_first_request(rig: Rig) -> None:
    calls = {"n": 0}

    def free_bytes(path: Path) -> int:
        calls["n"] += 1
        return PLENTY if calls["n"] <= 2 else 0  # fine at plan time, full by the run

    events: list[PrefetchProgress] = []
    result = rig.prefetch(free_bytes=free_bytes).run(events.append)

    assert [s.partition(":")[0] for s in result.skipped] == ["chatterbox_turbo", "qwen3_tts"]
    assert result.files == 3
    assert rig.server.asked("chatterbox_turbo") == rig.server.asked("qwen3_tts") == []
    assert not (rig.settings.models_dir / "chatterbox_turbo").exists()
    done = [e.done_bytes for e in events]
    assert done == sorted(done)


def test_voices_and_kokoro_never_get_a_room_check(rig: Rig) -> None:
    rig.write_lock(VOICES)

    assert rig.prefetch(free_bytes=lambda path: 0).run() == PrefetchResult("complete", files=3)


def test_a_failed_engine_file_reads_group_and_path(rig: Rig) -> None:
    rel = "speech_tokenizer/model.safetensors"
    rig.server.routes[url_path("qwen3_tts", rel)] = lambda r: httpx.Response(404)
    rig.server.routes[url_path("voices", "en_US-a-medium.onnx")] = lambda r: httpx.Response(404)

    result = rig.prefetch().run()

    assert result.failed == ("en_US-a-medium.onnx", f"qwen3_tts/{rel}")


# --- Range resume ---------------------------------------------------------------------------------


def bend(rig: Rig, *answers: Callable[[httpx.Request, bytes], httpx.Response]) -> bytes:
    """Answer the big Qwen file with `answers` in turn, then normally."""
    body = payload("qwen3_tts", BIG)
    queue = list(answers)

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0)(request, body) if queue else wire(body)

    rig.server.routes[url_path("qwen3_tts", BIG)] = handler
    return body


def test_range_resume_continues_after_a_short_read(rig: Rig) -> None:
    body = bend(
        rig,
        lambda r, b: short(b, 20),
        lambda r, b: ranged(b, asked_start(r)),
    )

    assert rig.prefetch().run() == everything()
    assert rig.server.ranges("qwen3_tts", BIG) == [None, "bytes=20-"]
    assert rig.target("qwen3_tts", BIG).read_bytes() == body
    assert rig.leftovers() == []


def test_resume_re_hashes_the_bytes_already_on_disk(rig: Rig) -> None:
    def tamper_then_resume(request: httpx.Request, body: bytes) -> httpx.Response:
        (part,) = rig.stage.glob("*.part")
        data = bytearray(part.read_bytes())
        data[0] ^= 0xFF  # the disk now disagrees with what the first attempt hashed
        part.write_bytes(bytes(data))
        return ranged(body, asked_start(request))

    bend(rig, lambda r, b: short(b, 20), tamper_then_resume)

    result = rig.prefetch().run()

    assert result.failed == (f"qwen3_tts/{BIG}",)
    assert not rig.target("qwen3_tts", BIG).exists()
    assert rig.leftovers() == []


def test_a_server_that_ignores_range_restarts_the_file(rig: Rig) -> None:
    body = bend(rig, lambda r, b: short(b, 20))  # then the default 200 answers the Range

    assert rig.prefetch().run() == everything()
    assert rig.server.ranges("qwen3_tts", BIG) == [None, "bytes=20-"]
    assert rig.target("qwen3_tts", BIG).read_bytes() == body


def test_a_416_restarts_the_file(rig: Rig) -> None:
    body = bend(rig, lambda r, b: short(b, 20), lambda r, b: httpx.Response(416))

    assert rig.prefetch().run() == everything()
    assert rig.server.ranges("qwen3_tts", BIG) == [None, "bytes=20-", None]
    assert rig.target("qwen3_tts", BIG).read_bytes() == body


@pytest.mark.parametrize(
    "answer",
    [
        lambda r, b: ranged(b, asked_start(r) - 1),
        lambda r, b: ranged(b, asked_start(r), end=len(b) - 2),
        lambda r, b: ranged(b, asked_start(r), total=len(b) + 1),
        lambda r, b: wire(b[asked_start(r) :], 206),  # no Content-Range
        lambda r, b: wire(b[asked_start(r) :], 206, **{"Content-Range": "bytes */60"}),
        lambda r, b: httpx.Response(
            206,
            headers={
                "Content-Range": f"bytes {asked_start(r)}-{len(b) - 1}/{len(b)}",
                "Content-Length": "1",
            },
            stream=httpx.ByteStream(b[asked_start(r) :]),
        ),
    ],
    ids=["start", "end", "total", "no-range-header", "unsatisfied", "length"],
)
def test_a_malformed_206_restarts_the_file(rig: Rig, answer) -> None:
    body = bend(rig, lambda r, b: short(b, 20), answer)

    assert rig.prefetch().run() == everything()
    assert rig.server.ranges("qwen3_tts", BIG) == [None, "bytes=20-", None]
    assert rig.target("qwen3_tts", BIG).read_bytes() == body


def test_a_resumed_transfer_that_breaks_resumes_again_from_the_new_end(rig: Rig) -> None:
    def broken_range(request: httpx.Request, body: bytes) -> httpx.Response:
        start = asked_start(request)
        headers = {
            "Content-Range": f"bytes {start}-{len(body) - 1}/{len(body)}",
            "Content-Length": str(len(body) - start),
        }
        return httpx.Response(206, headers=headers, stream=httpx.ByteStream(body[start:30]))

    body = bend(
        rig, lambda r, b: short(b, 20), broken_range, lambda r, b: ranged(b, asked_start(r))
    )

    assert rig.prefetch().run() == everything()
    assert rig.server.ranges("qwen3_tts", BIG) == [None, "bytes=20-", "bytes=30-"]
    assert rig.target("qwen3_tts", BIG).read_bytes() == body


def test_a_full_part_is_fetched_again_without_a_range(rig: Rig) -> None:
    def everything_then_drop(request: httpx.Request, body: bytes) -> httpx.Response:
        def chunks() -> Iterator[bytes]:
            yield body
            raise httpx.ReadError("connection reset", request=request)

        return httpx.Response(200, headers={"Content-Length": str(len(body))}, content=chunks())

    body = bend(rig, everything_then_drop)

    assert rig.prefetch().run() == everything()
    assert rig.server.ranges("qwen3_tts", BIG) == [None, None]
    assert rig.target("qwen3_tts", BIG).read_bytes() == body


def test_the_part_is_gone_after_the_last_failure(rig: Rig) -> None:
    bend(
        rig,
        lambda r, b: short(b, 10),
        lambda r, b: short(b, 15),  # ignores the Range: restarts, stops short again
        lambda r, b: short(b, 12),
    )

    result = rig.prefetch().run()

    assert result.failed == (f"qwen3_tts/{BIG}",)
    assert rig.server.ranges("qwen3_tts", BIG) == [None, "bytes=10-", "bytes=15-"]
    assert rig.leftovers() == []


def test_the_part_is_gone_after_a_cancel_in_a_resumed_stream(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prefetch, "CHUNK", 8)
    cancel = threading.Event()

    def cancelling(request: httpx.Request, body: bytes) -> httpx.Response:
        start = asked_start(request)

        def chunks() -> Iterator[bytes]:
            yield body[start : start + 8]
            cancel.set()
            yield body[start + 8 :]

        headers = {
            "Content-Range": f"bytes {start}-{len(body) - 1}/{len(body)}",
            "Content-Length": str(len(body) - start),
        }
        return httpx.Response(206, headers=headers, content=chunks())

    bend(rig, lambda r, b: short(b, 20), cancelling)

    result = rig.prefetch().run(cancel=cancel)

    assert result.outcome == "cancelled"
    assert rig.leftovers() == []
    assert not rig.target("qwen3_tts", BIG).exists()


# --- progress -------------------------------------------------------------------------------------


def test_progress_carries_group_and_group_bytes(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prefetch, "PROGRESS_INTERVAL_S", 3600.0)
    events: list[PrefetchProgress] = []

    rig.prefetch().run(events.append)

    assert [e.group for e in events[::2]] == [g for g, _ in ORDER]
    for group in prefetch.FETCHED:
        mine = [e for e in events if e.group == group]
        assert {e.group_total_bytes for e in mine} == {group_bytes(group)}
        done = [e.group_done_bytes for e in mine]
        assert done == sorted(done) and done[0] == 0 and done[-1] == group_bytes(group)
    total = sum(group_bytes(g) for g in prefetch.FETCHED)
    assert (events[-1].done_bytes, events[-1].total_bytes) == (total, total)
    assert events[-1] == PrefetchProgress(BIG, total, total, len(ORDER), len(ORDER))


def test_a_resumed_file_reports_monotonic_group_bytes(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prefetch, "PROGRESS_INTERVAL_S", 0.0)
    monkeypatch.setattr(prefetch, "CHUNK", 8)
    bend(rig, lambda r, b: short(b, 20), lambda r, b: ranged(b, asked_start(r)))
    events: list[PrefetchProgress] = []

    rig.prefetch().run(events.append)

    qwen = [e.group_done_bytes for e in events if e.group == "qwen3_tts"]
    assert qwen == sorted(qwen) and qwen[-1] == group_bytes("qwen3_tts")
