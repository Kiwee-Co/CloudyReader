"""scripts/pin_engine_assets.py against canned Hugging Face API replies and a fake transport."""

from __future__ import annotations

import email.message
import hashlib
import importlib.util
import io
import json
import re
import sys
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pin_engine_assets.py"
API = "https://huggingface.co/api/models"
HUB = "https://huggingface.co"
REPO = "mlx-community/test-engine-4bit"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
GROUP = "chatterbox_turbo"
FILES = {
    "model.safetensors": b"M" * 5000,
    "speech_tokenizer/model.safetensors": b"S" * 3000,
    "vocab.json": b"V" * 40,
    "merges.txt": b"G" * 40,
    "config.json": b"C" * 20,
}
LFS = ("model.safetensors", "speech_tokenizer/model.safetensors")
ORDER = [
    "config.json",
    "merges.txt",
    "vocab.json",
    "speech_tokenizer/model.safetensors",
    "model.safetensors",
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class FakeReply:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    stream: io.BytesIO = field(default_factory=io.BytesIO)


def redirect(location: str, status: int = 302) -> Callable[[], FakeReply]:
    return lambda: FakeReply(status, {"location": location})


def body(data: bytes, length: int | None = None) -> Callable[[], FakeReply]:
    size = len(data) if length is None else length
    return lambda: FakeReply(200, {"content-length": str(size)}, io.BytesIO(data))


def tree_file(path: str, size: int, *, lfs: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"type": "file", "oid": "0" * 40, "size": size, "path": path}
    if lfs is not None:
        item["lfs"] = {"oid": lfs, "size": size, "pointerSize": 134}
    return item


class Hub:
    """Canned model API and file server (each file behind a signed CDN redirect); logs requests."""

    def __init__(
        self,
        files: dict[str, bytes] = FILES,
        *,
        extra: tuple[dict[str, Any], ...] = (),
        oids: dict[str, str] | None = None,
    ) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.routes: dict[str, Callable[[], FakeReply]] = {}
        self.signed: dict[str, str] = {}
        self.json(f"{API}/{REPO}/revision/main", {"id": REPO, "sha": COMMIT})
        tree: list[dict[str, Any]] = [
            {"type": "directory", "oid": "d" * 40, "size": 0, "path": "speech_tokenizer"}
        ]
        for path, data in files.items():
            oid = (oids or {}).get(path, sha256(data)) if path in LFS else None
            tree.append(tree_file(path, len(data), lfs=oid))
            self.signed[path] = f"https://cdn.example.net/xet/{path}?X-Amz-Signature=s3cr3t"
            self.routes[f"{HUB}/{REPO}/resolve/{COMMIT}/{path}"] = redirect(self.signed[path])
            self.routes[self.signed[path]] = body(data)
        self.tree_url = f"{API}/{REPO}/tree/{COMMIT}?recursive=true"
        self.tree = tree + list(extra)
        self.json(self.tree_url, self.tree)

    def json(self, url: str, data: Any, headers: dict[str, str] | None = None) -> None:
        blob = json.dumps(data).encode()
        self.routes[url] = lambda: FakeReply(200, dict(headers or {}), io.BytesIO(blob))

    def __call__(self, url: str, headers: dict[str, str]) -> FakeReply:
        self.requests.append((url, dict(headers)))
        route = self.routes.get(url)
        return route() if route else FakeReply(404, {}, io.BytesIO(b"{}"))

    def urls(self) -> list[str]:
        return [url for url, _ in self.requests]

    def downloads(self) -> list[str]:
        prefix = f"{HUB}/{REPO}/resolve/"
        return [
            url[len(prefix) :].split("/", 1)[1] for url in self.urls() if url.startswith(prefix)
        ]


def spec(engine: str = GROUP, expect: dict[str, tuple[int, str | None]] | None = None, **kw):
    fields = {"title": engine, "repo": REPO, "voices": (), "license": "MIT", "credit": ""}
    return SimpleNamespace(engine=engine, expect=expect or {}, **{**fields, **kw})


def entry(name: str, group: str, dest: str) -> dict[str, Any]:
    url = f"https://example.org/org/{group}/resolve/{'1' * 40}/{name}"  # valid in every group
    return {"name": name, "group": group, "url": url, "sha256": "ab" * 32, "size": 10, "dest": dest}


BASE_LOCK = {
    "description": "Pinned non-PyPI assets.",
    "version": 1,
    "assets": [
        entry("en_ner_craft_md-0.5.4.tar.gz", "models", ".data/models/en_ner_craft_md"),
        entry("en_US-lessac-medium.onnx", "voices", ".data/voices"),
        entry("config.json", "kokoro", ".data/models/kokoro"),
        entry("af_heart.safetensors", "kokoro", ".data/models/kokoro/voices"),
        entry("model.safetensors", "qwen3_tts", ".data/models/qwen3_tts"),
    ],
}


def canonical(data: Any) -> str:
    return json.dumps(data, indent=2) + "\n"


def rel_of(item: dict[str, Any]) -> str:
    folder = item["dest"].removeprefix(f".data/models/{GROUP}").lstrip("/")
    return f"{folder}/{item['name']}" if folder else item["name"]


def spans(text: str) -> tuple[str, list[tuple[str, str]], str]:
    """Header, each asset entry's exact text with its group, and the tail of a lock file."""
    decoder, start = json.JSONDecoder(), text.index('"assets": [') + len('"assets": [')
    found, i = [], start
    while True:
        while text[i] in " \n,":
            i += 1
        if text[i] == "]":
            return text[:start], found, text[i:]
        item, end = decoder.raw_decode(text, i)
        found.append((item["group"], text[i:end]))
        i = end


@pytest.fixture
def pin(monkeypatch: pytest.MonkeyPatch):
    loader = importlib.util.spec_from_file_location("pin_engine_assets", SCRIPT)
    module = importlib.util.module_from_spec(loader)
    # dataclasses looks its module up in sys.modules while it builds the script's classes.
    monkeypatch.setitem(sys.modules, "pin_engine_assets", module)
    loader.loader.exec_module(module)
    monkeypatch.setattr(module, "SPECS", {GROUP: spec(), "qwen3_tts": spec("qwen3_tts")})
    return module


@dataclass
class Run:
    module: Any
    lock: Path
    data: Path
    capsys: Any
    free: int = 10**12

    def __call__(self, hub: Hub, *args: str) -> tuple[int, str]:
        code = self.module.main(
            [GROUP, *args],
            transport=hub,
            lock_path=self.lock,
            data_dir=self.data,
            free_bytes=lambda path: self.free,
        )
        captured = self.capsys.readouterr()
        return code, captured.out + captured.err

    def written(self) -> list[dict[str, Any]]:
        return [a for a in json.loads(self.lock.read_text())["assets"] if a["group"] == GROUP]


@pytest.fixture
def run(pin, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Run:
    lock = tmp_path / "assets.lock.json"
    lock.write_text(canonical(BASE_LOCK))
    return Run(pin, lock, tmp_path / "data", capsys)


# --- the first tests of the package --------------------------------------------------------------


def test_pickle_suffix_files_are_listed_but_never_pinned(run: Run):
    risky = ("conds.pt", "voice.pkl", "weights.bin", "embed.npy", "modeling.py")
    hub = Hub(extra=tuple(tree_file(name, 90, lfs="f" * 64) for name in risky))
    code, out = run(hub, "--write")
    assert code == 0
    for name in risky:
        assert f"SKIPPED  {name}: can run code when loaded, never pinned" in out
        assert name not in hub.downloads()
        assert name not in run.lock.read_text()
    assert sorted(rel_of(a) for a in run.written()) == sorted(FILES)


def test_lfs_oid_mismatch_aborts(run: Run):
    hub = Hub(oids={"speech_tokenizer/model.safetensors": "e" * 64})
    code, out = run(hub, "--write", "--install")
    assert code == 1
    assert "speech_tokenizer/model.safetensors: SHA-256 does not match the LFS oid" in out
    assert "model.safetensors" not in hub.downloads()  # the larger file comes later: never fetched
    assert run.lock.read_text() == canonical(BASE_LOCK)
    assert list(run.data.iterdir()) == []  # no temp dir left, nothing installed


def test_drift_from_the_research_table_is_reported(run: Run, pin):
    pin.SPECS[GROUP] = spec(
        expect={
            "config.json": (20, None),
            "model.safetensors": (4_999, None),
            "generation_config.json": (245, None),
        }
    )
    hub = Hub()
    code, out = run(hub, "--write")
    assert code == 1
    assert "DRIFT    model.safetensors: 5,000 B, the research table says 4,999 B" in out
    assert (
        "DRIFT    generation_config.json: in the research table, not pinnable at this commit" in out
    )
    assert "new      vocab.json: not in the research table" in out
    assert "DRIFT    config.json" not in out  # a match is silent
    assert hub.downloads() == []  # sizes drift before any download
    assert run.lock.read_text() == canonical(BASE_LOCK)


def test_a_hash_that_differs_from_the_research_table_is_drift_after_download(run: Run, pin):
    expect: dict[str, tuple[int, str | None]] = {p: (len(d), None) for p, d in FILES.items()}
    expect["config.json"] = (20, "0" * 64)
    expect["model.safetensors"] = (5000, sha256(FILES["model.safetensors"]))
    pin.SPECS[GROUP] = spec(expect=expect)
    code, out = run(Hub(), "--write", "--install")
    assert code == 1
    want = f"DRIFT    config.json: sha256 {sha256(FILES['config.json'])[:12]}, the research"
    assert want in out and "table says 000000000000" in out
    assert "model.safetensors: sha256" not in out
    assert run.lock.read_text() == canonical(BASE_LOCK)
    assert list(run.data.iterdir()) == []


def test_urls_are_commit_pinned(run: Run):
    hub = Hub()
    code, out = run(hub, "--write")
    assert code == 0
    assert f"{REPO} at main = commit {COMMIT}" in out
    for item in run.written():
        assert item["url"] == f"{HUB}/{REPO}/resolve/{COMMIT}/{rel_of(item)}"
    first_hops = [u for u in hub.urls() if u.startswith(f"{HUB}/{REPO}/resolve/")]
    assert len(first_hops) == len(FILES)
    assert all(u.startswith(f"{HUB}/{REPO}/resolve/{COMMIT}/") for u in first_hops)


def test_entries_are_sorted_small_files_first(run: Run):
    hub = Hub()
    code, _ = run(hub, "--write")
    assert code == 0
    written = run.written()
    assert [rel_of(a) for a in written] == ORDER  # size, then path for a tie
    assert hub.downloads() == ORDER
    assert written[3]["dest"] == f".data/models/{GROUP}/speech_tokenizer"
    assert written[3]["name"] == "model.safetensors"
    assert written[0] == {
        "name": "config.json",
        "group": GROUP,
        "url": f"{HUB}/{REPO}/resolve/{COMMIT}/config.json",
        "sha256": sha256(FILES["config.json"]),
        "size": 20,
        "dest": f".data/models/{GROUP}",
    }


def test_write_replaces_only_this_group_and_keeps_the_rest_byte_identical(run: Run):
    stale = entry("old.safetensors", GROUP, f".data/models/{GROUP}")
    assets = BASE_LOCK["assets"]
    run.lock.write_text(canonical({**BASE_LOCK, "assets": [*assets[:3], stale, *assets[3:]]}))
    before = run.lock.read_text()
    code, out = run(Hub(), "--write")
    assert code == 0
    assert f"wrote    assets.lock.json: 5 {GROUP} entries" in out
    after = run.lock.read_text()
    head_b, spans_b, tail_b = spans(before)
    head_a, spans_a, tail_a = spans(after)
    assert (head_a, tail_a) == (head_b, tail_b)
    assert [s for g, s in spans_a if g != GROUP] == [s for g, s in spans_b if g != GROUP]
    assert [g for g, _ in spans_a] == [
        *["models", "voices", "kokoro"],
        *[GROUP] * 5,  # in place of the old entry
        *["kokoro", "qwen3_tts"],
    ]
    assert "old.safetensors" not in after
    assert after == canonical(json.loads(after))


def test_a_first_pin_lands_after_kokoro_and_before_later_engines(run: Run):
    code, _ = run(Hub(), "--write")
    assert code == 0
    groups = [a["group"] for a in json.loads(run.lock.read_text())["assets"]]
    assert groups == ["models", "voices", "kokoro", "kokoro", *[GROUP] * 5, "qwen3_tts"]


def test_install_moves_verified_files_into_the_data_dir(run: Run):
    code, out = run(Hub(), "--install")
    assert code == 0
    folder = run.data / "models" / GROUP
    for path, data in FILES.items():
        assert (folder / path).read_bytes() == data
        assert f"installed {path}: {len(data):,} B" in out
    assert [p.name for p in run.data.iterdir()] == ["models"]  # the temp dir is gone
    assert run.lock.read_text() == canonical(BASE_LOCK)  # --install alone writes no lock


def test_redirect_to_http_is_refused(run: Run):
    hub = Hub()
    hub.routes[f"{HUB}/{REPO}/resolve/{COMMIT}/config.json"] = redirect("http://cdn.example.net/c")
    code, out = run(hub, "--write")
    assert code == 1
    assert "refused a redirect that leaves HTTPS" in out
    assert not any(u.startswith("http://") for u in hub.urls())
    assert run.lock.read_text() == canonical(BASE_LOCK)


def test_size_cap_per_file(run: Run, pin, monkeypatch: pytest.MonkeyPatch):
    # A server that sends more than the tree lists is cut off at the listed size.
    hub = Hub()
    hub.routes[hub.signed["vocab.json"]] = body(FILES["vocab.json"] + b"extra", length=40)
    code, out = run(hub, "--write")
    assert code == 1
    assert "vocab.json: more bytes than the 40 B listed" in out
    assert run.lock.read_text() == canonical(BASE_LOCK)
    # A listed size over the cap stops the run before any download.
    monkeypatch.setattr(pin, "MAX_FILE_BYTES", 4_000)
    hub = Hub()
    code, out = run(hub, "--write")
    assert code == 1
    assert "model.safetensors: 5,000 B is over the 4,000 B cap per file" in out
    assert hub.downloads() == []


def test_output_shows_no_url_or_token(run: Run, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HF_TOKEN", "hf_SeCrEt")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "hf_SeCrEt")
    hub = Hub(extra=(tree_file("conds.pt", 9, lfs="f" * 64),))
    code, out = run(hub, "--write", "--install")
    assert code == 0
    for secret in ("://", "huggingface.co", "example.net", "Signature", "SeCrEt"):
        assert secret not in out
    assert all("authorization" not in {k.lower() for k in h} for _, h in hub.requests)
    hub = Hub()
    hub.routes[f"{API}/{REPO}/revision/main"] = lambda: FakeReply(500, {}, io.BytesIO(b"https://x"))
    code, out = run(hub)
    assert code == 1
    assert "model API: HTTP 500" in out and "://" not in out


# --- more behavior -------------------------------------------------------------------------------


def test_a_revision_resolves_to_a_commit_and_a_bad_answer_stops(run: Run):
    hub = Hub()
    hub.json(f"{API}/{REPO}/revision/v1.0", {"sha": COMMIT})
    code, out = run(hub, "--rev", "v1.0")
    assert code == 0
    assert f"at v1.0 = commit {COMMIT}" in out
    for answer in ({"sha": "main"}, {"id": REPO}, ["not", "a", "dict"]):
        hub = Hub()
        hub.json(f"{API}/{REPO}/revision/main", answer)
        code, out = run(hub)
        assert code == 1
        assert "the model API returned no commit for that revision" in out


def test_a_bad_repo_id_or_revision_sends_no_request(run: Run, pin):
    hub = Hub()
    code, out = run(hub, "--rev", "../main")
    assert code == 1 and "bad repo id or revision" in out
    pin.SPECS[GROUP] = spec(repo="../../etc")
    code, out = run(hub)
    assert code == 1 and "bad repo id or revision" in out
    assert hub.requests == []


def test_an_unknown_engine_is_a_usage_error(run: Run):
    with pytest.raises(SystemExit) as exc:
        run.module.main(["f5"], transport=Hub(), lock_path=run.lock, data_dir=run.data)
    assert exc.value.code == 2


def test_the_tree_listing_follows_next_links_of_the_same_listing_only(run: Run, pin, monkeypatch):
    hub = Hub()
    page2 = f"{hub.tree_url}&cursor=abc"
    hub.json(hub.tree_url, hub.tree[:3], {"link": f'<{page2}>; rel="next"'})
    hub.json(page2, hub.tree[3:])
    code, _ = run(hub)
    assert code == 0
    assert page2 in hub.urls()
    hub.json(hub.tree_url, hub.tree[:3], {"link": f'<{API}/{REPO}/tree/main?c=1>; rel="next"'})
    code, out = run(hub)
    assert code == 1 and "unexpected pagination link" in out
    monkeypatch.setattr(pin, "MAX_PAGES", 1)
    hub.json(hub.tree_url, hub.tree[:3], {"link": f'<{page2}>; rel="next"'})
    code, out = run(hub)
    assert code == 1 and "the tree listing has more than 1 pages" in out


def test_unsafe_nested_hidden_and_empty_names_are_skipped(run: Run):
    odd = ("bad name.json", "nested/deeper/x.json", ".gitattributes", "README.md")
    extra = [tree_file(p, 5) for p in (*odd, "chat_template.jinja")]
    code, out = run(Hub(extra=(*extra, tree_file("empty.json", 0))), "--write")
    assert code == 0
    assert "bad name" not in out
    assert re.search(r"skipped  tree entry #\d+: unsafe name, not shown", out)
    assert "skipped  nested/deeper/x.json: more than one folder deep" in out
    assert "skipped  .gitattributes: hidden file" in out
    assert "skipped  README.md: not a data file" in out
    assert "skipped  chat_template.jinja: not a data file" in out
    assert "skipped  empty.json: empty" in out
    assert sorted(rel_of(a) for a in run.written()) == sorted(FILES)


@pytest.mark.parametrize(
    ("tree", "message"),
    [
        ({"not": "a list"}, "unexpected tree listing"),
        ([["not", "a", "dict"]], "tree entry #0 is malformed"),
        ([{"type": "file", "path": "a.json", "size": "9"}], "tree entry #0 is malformed"),
        ([tree_file("a.safetensors", 9, lfs="nothex")], "a.safetensors: malformed LFS record"),
        ([{**tree_file("a.safetensors", 9), "lfs": {"oid": "f" * 64, "size": 8}}], "malformed LFS"),
        ([tree_file("README.md", 9)], "nothing to pin: no .safetensors, .json or .txt file"),
    ],
)
def test_a_malformed_or_empty_tree_stops_the_run(run: Run, tree, message):
    hub = Hub()
    hub.json(hub.tree_url, tree)
    code, out = run(hub)
    assert code == 1
    assert message in out
    assert hub.downloads() == []


def test_low_disk_space_stops_before_any_download(run: Run):
    run.free = 1
    hub = Hub()
    code, out = run(hub, "--install")
    assert code == 1
    assert "not enough disk space: needs 1,073,750,734 B, 1 B free" in out  # 8,100 x 1.1 + 1 GiB
    assert hub.downloads() == []


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (
            body(FILES["config.json"], length=99),
            "config.json: Content-Length differs from the 20 B",
        ),
        (lambda: FakeReply(200, {}, io.BytesIO(b"C" * 10)), "config.json: got 10 of 20 B"),
        (lambda: FakeReply(403, {}, io.BytesIO()), "config.json: HTTP 403"),
        (redirect(""), "HTTP 302 redirect without a Location"),
    ],
)
def test_a_bad_download_reply_stops_the_run(run: Run, reply, message):
    hub = Hub()
    hub.routes[hub.signed["config.json"]] = reply
    code, out = run(hub, "--write")
    assert code == 1
    assert message in out
    assert run.lock.read_text() == canonical(BASE_LOCK)


def test_redirects_are_capped_and_relative_ones_resolved(run: Run):
    hub = Hub()
    hops = [f"https://cdn.example.net/hop{i}" for i in range(6)]
    hub.routes[f"{HUB}/{REPO}/resolve/{COMMIT}/config.json"] = redirect(hops[0])
    for here, there in zip(hops, hops[1:], strict=False):
        hub.routes[here] = redirect(there)
    code, out = run(hub)
    assert code == 1 and "more than 5 redirects" in out
    assert hops[-1] not in hub.urls()
    hub = Hub()
    hub.routes[f"{HUB}/{REPO}/resolve/{COMMIT}/config.json"] = redirect("/cache/c", status=307)
    hub.routes[f"{HUB}/cache/c"] = body(FILES["config.json"])
    code, _ = run(hub)
    assert code == 0


def test_api_replies_must_be_small_json(run: Run, pin, monkeypatch: pytest.MonkeyPatch):
    hub = Hub()
    hub.routes[hub.tree_url] = lambda: FakeReply(200, {}, io.BytesIO(b"<html>"))
    code, out = run(hub)
    assert code == 1 and "model API reply is not JSON" in out
    monkeypatch.setattr(pin, "MAX_JSON_BYTES", 10)
    code, out = run(Hub())
    assert code == 1 and "model API reply is too large" in out


def test_install_keeps_identical_files_replaces_others_and_reports_stale_ones(run: Run):
    folder = run.data / "models" / GROUP
    folder.mkdir(parents=True)
    (folder / "config.json").write_bytes(FILES["config.json"])
    (folder / "vocab.json").write_bytes(b"x" * 40)
    (folder / "old.safetensors").write_bytes(b"x")
    code, out = run(Hub(), "--install")
    assert code == 0
    assert "kept     config.json" in out
    assert "installed vocab.json: 40 B" in out
    assert (folder / "vocab.json").read_bytes() == FILES["vocab.json"]
    assert "stale    old.safetensors: not in this pin; move it out of the folder" in out
    assert (folder / "old.safetensors").read_bytes() == b"x"  # reported, never deleted


def test_install_refuses_a_symlink_before_moving_anything(run: Run, tmp_path: Path):
    folder = run.data / "models" / GROUP
    folder.mkdir(parents=True)
    (folder / "model.safetensors").symlink_to(tmp_path / "elsewhere")
    code, out = run(Hub(), "--install")
    assert code == 1
    assert "model.safetensors: the installed copy is a symlink; nothing installed" in out
    assert not (folder / "config.json").exists()
    assert not (tmp_path / "elsewhere").exists()


def test_install_refuses_a_models_folder_that_leads_into_an_app_bundle(run: Run, tmp_path):
    bundle = tmp_path / "X.app" / "Contents" / "Resources"
    bundle.mkdir(parents=True)
    (run.data / "models").mkdir(parents=True)
    (run.data / "models" / GROUP).symlink_to(bundle, target_is_directory=True)
    code, out = run(Hub(), "--install")
    assert code == 1
    assert "config.json: its folder is inside an app bundle; nothing installed" in out
    assert list(bundle.iterdir()) == []


def test_a_data_dir_inside_an_app_bundle_is_refused_before_any_download(run: Run, tmp_path):
    run.data = tmp_path / "Cloudy Reader.app" / "Contents" / "Resources" / "data"
    hub = Hub()
    code, out = run(hub, "--install")
    assert code == 1
    assert "the data folder is inside an app bundle; nothing downloaded" in out
    assert hub.downloads() == []
    assert not run.data.exists()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (json.dumps(BASE_LOCK), "assets.lock.json is not in the json.dumps(indent=2) layout"),
        (canonical({**BASE_LOCK, "version": 2}), "assets.lock.json is not a version 1 asset lock"),
        (canonical({"version": 1}), "assets.lock.json is not a version 1 asset lock"),
        ("{not json", "assets.lock.json is not JSON; nothing written"),
    ],
)
def test_a_lock_that_cannot_be_spliced_safely_is_left_alone(run: Run, text: str, message: str):
    run.lock.write_text(text)
    code, out = run(Hub(), "--write")
    assert code == 1
    assert message in out
    assert run.lock.read_text() == text


def test_a_failed_lock_write_keeps_the_old_lock_and_leaves_no_temp_file(run: Run, pin, monkeypatch):
    def refuse(src, dst):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(pin.os, "replace", refuse)
    code, out = run(Hub(), "--write")
    assert code == 1
    assert "pin_engine_assets: PermissionError: Permission denied" in out
    assert run.lock.read_text() == canonical(BASE_LOCK)
    assert sorted(p.name for p in run.lock.parent.iterdir()) == ["assets.lock.json", "data"]


def test_write_keeps_the_lock_file_mode(run: Run):
    run.lock.chmod(0o644)
    code, _ = run(Hub(), "--write")
    assert code == 0
    assert run.lock.stat().st_mode & 0o777 == 0o644
    assert sorted(p.name for p in run.lock.parent.iterdir()) == ["assets.lock.json", "data"]


def test_urllib_transport_hands_back_redirects_unfollowed(pin, monkeypatch: pytest.MonkeyPatch):
    class Opener:
        def __init__(self, outcome: Any) -> None:
            self.outcome, self.seen = outcome, []

        def open(self, request, timeout):
            self.seen.append((request.full_url, request.get_header("User-agent"), timeout))
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome

    class Resp(io.BytesIO):
        status = 200
        headers = {"Content-Length": "3"}

    hdrs = email.message.Message()
    hdrs["Location"] = "https://cdn.example.net/x"
    moved = urllib.error.HTTPError("https://h.example/x", 302, "Found", hdrs, io.BytesIO(b""))
    for outcome, status, headers in (
        (moved, 302, {"location": "https://cdn.example.net/x"}),
        (Resp(b"abc"), 200, {"content-length": "3"}),
    ):
        opener = Opener(outcome)
        monkeypatch.setattr(pin.urllib.request, "build_opener", lambda *handlers, o=opener: o)
        reply = pin.urllib_transport("https://h.example/x", {"User-Agent": "t"})
        assert (reply.status, dict(reply.headers)) == (status, headers)
        assert opener.seen == [("https://h.example/x", "t", pin.TIMEOUT_S)]
    assert reply.stream.read() == b"abc"
    opener = Opener(urllib.error.URLError("no route to h.example"))
    monkeypatch.setattr(pin.urllib.request, "build_opener", lambda *handlers, o=opener: o)
    with pytest.raises(pin.PinError, match=r"^network error: URLError$"):
        pin.urllib_transport("https://h.example/x", {})
    assert pin._NoRedirects().redirect_request(None, None, 302, "Found", {}, "https://x") is None


def test_the_real_research_tables_are_pinnable(pin):
    from cloudyreader.engine_catalog import SPECS

    assert set(SPECS) >= {"chatterbox_turbo", "qwen3_tts"}
    for engine, real in SPECS.items():
        assert real.engine == engine
        assert pin._REPO.fullmatch(real.repo)
        for rel, (size, digest) in real.expect.items():
            assert pin.skip_reason(rel) is None, (engine, rel)
            assert size > 0
            assert digest is None or re.fullmatch(r"[0-9a-f]{64}", digest)


def test_written_entries_pass_both_lock_validators(run: Run, tmp_path: Path, monkeypatch):
    # One entry either validator refuses would reject the whole lock, voices included.
    from cloudyreader import prefetch
    from cloudyreader.config import DATA_DIR_ENV, load_settings

    loader = importlib.util.spec_from_file_location(
        "fetch_assets", ROOT / "scripts/fetch_assets.py"
    )
    fetch_assets = importlib.util.module_from_spec(loader)
    monkeypatch.setitem(sys.modules, "fetch_assets", fetch_assets)
    loader.loader.exec_module(fetch_assets)
    code, _ = run(Hub(), "--write")
    assert code == 0
    assert all(fetch_assets.safe_entry(a) for a in json.loads(run.lock.read_text())["assets"])
    settings = load_settings({DATA_DIR_ENV: str(tmp_path / "app-data")})
    mine = [a for a in prefetch.load_assets(run.lock, settings) if a.group == GROUP]
    folder = settings.models_dir / GROUP
    assert sorted(a.path.relative_to(folder).as_posix() for a in mine) == sorted(FILES)
