"""VoiceManager: installed scan, cached HF catalog, md5-checked download (no live network)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from cloudyreader import voices as voices_module
from cloudyreader.voices import (
    CATALOG_URL,
    FILE_URL_BASE,
    HttpDownloader,
    VoiceDownloadError,
    VoiceError,
    VoiceManager,
    scan_installed,
)

KEY = "en_US-fake-medium"
ONNX = b"fake-onnx-model" * 64
CONFIG = json.dumps(
    {
        "audio": {"sample_rate": 22050, "quality": "medium"},
        "espeak": {"voice": "en-us"},
        "phoneme_id_map": {" ": [3]},
        "num_speakers": 1,
        "language": {"code": "en_US"},
    }
).encode()


def md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def catalog_entry(
    key: str = KEY, *, onnx: bytes = ONNX, config: bytes = CONFIG, speakers: int = 1
) -> dict:
    lang, name, quality = key.split("-")
    folder = f"en/{lang}/{name}/{quality}"
    return {
        "key": key,
        "name": name,
        "language": {"code": lang, "family": "en", "region": lang.split("_")[1]},
        "quality": quality,
        "num_speakers": speakers,
        "speaker_id_map": {},
        "files": {
            f"{folder}/{key}.onnx": {"size_bytes": len(onnx), "md5_digest": md5(onnx)},
            f"{folder}/{key}.onnx.json": {"size_bytes": len(config), "md5_digest": md5(config)},
            f"{folder}/MODEL_CARD": {"size_bytes": 3, "md5_digest": md5(b"abc")},
        },
        "aliases": [],
    }


def payloads(entry: dict, *, onnx: bytes = ONNX, config: bytes = CONFIG) -> dict[str, bytes]:
    """URL -> bytes a faithful server would return for the entry's onnx and json files."""
    return {
        FILE_URL_BASE + quote(path): onnx if path.endswith(".onnx") else config
        for path in entry["files"]
        if path.endswith((".onnx", ".onnx.json"))
    }


class FakeDownloader:
    def __init__(self, served: dict[str, bytes]) -> None:
        self.served = served
        self.urls: list[str] = []

    def __call__(self, url: str, dest: Path) -> None:
        self.urls.append(url)
        if url not in self.served:
            raise VoiceDownloadError(f"HTTP 404 for {url}")
        dest.write_bytes(self.served[url])


@pytest.fixture
def voices_dir(tmp_path: Path) -> Path:
    path = tmp_path / "voices"
    path.mkdir()
    return path


def write_catalog(path: Path, *entries: dict) -> Path:
    path.write_text(json.dumps({e["key"]: e for e in entries}), encoding="utf-8")
    return path


def install(voices_dir: Path, key: str = KEY, config: bytes = CONFIG) -> None:
    (voices_dir / f"{key}.onnx").write_bytes(b"x")
    (voices_dir / f"{key}.onnx.json").write_bytes(config)


def leftovers(voices_dir: Path) -> list[str]:
    return sorted(p.name for p in voices_dir.iterdir())


# --- installed -------------------------------------------------------------------------------


def test_installed_lists_only_voices_with_both_files(voices_dir):
    install(voices_dir, "en_US-zed-medium")
    install(voices_dir, KEY)
    (voices_dir / "en_US-orphan-medium.onnx").write_bytes(b"x")  # no config: unusable
    (voices_dir / "notes.txt").write_text("ignore me")

    found = VoiceManager(voices_dir).installed()

    assert [v.key for v in found] == ["piper:en_US-fake-medium", "piper:en_US-zed-medium"]


def test_installed_fills_voice_info_from_the_config(voices_dir):
    multi = json.dumps(
        {"audio": {"quality": "high"}, "num_speakers": 4, "language": {"code": "en_GB"}}
    ).encode()
    install(voices_dir, "en_GB-multi-high", multi)

    (voice,) = scan_installed(voices_dir)

    assert (voice.engine, voice.name, voice.language, voice.quality) == (
        "piper",
        "multi",
        "en-GB",
        "high",
    )
    assert (voice.num_speakers, voice.installed) == (4, True)
    assert voice.path == voices_dir / "en_GB-multi-high.onnx"
    assert voice.precision == "high"  # Piper's slot is its tier, the same word as quality


def test_installed_falls_back_to_the_file_name_without_language_or_quality(voices_dir):
    install(voices_dir, "de_DE-thorsten-low", b"{}")

    (voice,) = scan_installed(voices_dir)

    assert (voice.language, voice.quality, voice.num_speakers) == ("de-DE", "low", 1)
    assert voice.precision == "low"


def test_installed_skips_a_corrupt_config_and_says_so(voices_dir, caplog):
    install(voices_dir, "en_US-broken-medium", b"{not json")
    install(voices_dir)

    with caplog.at_level("WARNING", logger="cloudyreader.voices"):
        found = scan_installed(voices_dir)

    assert [v.name for v in found] == ["fake"]
    assert "en_US-broken-medium" in caplog.text


def test_installed_is_empty_when_the_directory_is_missing(tmp_path):
    assert scan_installed(tmp_path / "nope") == []


# --- catalog ---------------------------------------------------------------------------------


def test_catalog_lists_voices_and_marks_the_installed_ones(voices_dir, tmp_path):
    catalog = write_catalog(
        tmp_path / "voices.json", catalog_entry(), catalog_entry("en_US-other-high", speakers=3)
    )
    install(voices_dir)

    listed = {v.key: v for v in VoiceManager(voices_dir, catalog).catalog()}

    fake, other = listed["piper:en_US-fake-medium"], listed["piper:en_US-other-high"]
    assert (fake.installed, fake.path) == (True, voices_dir / f"{KEY}.onnx")
    assert (other.installed, other.path) == (False, None)
    assert (other.engine, other.name, other.language) == ("piper", "other", "en-US")
    assert (other.quality, other.num_speakers) == ("high", 3)
    assert (fake.precision, other.precision) == ("medium", "high")


def test_the_live_catalog_has_a_non_ascii_voice_name_and_it_is_usable(voices_dir, tmp_path):
    key = "pt_PT-tugão-medium"  # real key in rhasspy/piper-voices
    entry = catalog_entry(key)
    catalog = write_catalog(tmp_path / "voices.json", entry)
    manager = VoiceManager(voices_dir, catalog, downloader=FakeDownloader(payloads(entry)))

    assert [v.name for v in manager.catalog()] == ["tugão"]
    assert manager.download(key).path == voices_dir / f"{key}.onnx"


def test_catalog_defaults_to_voices_json_inside_the_voices_dir(voices_dir):
    write_catalog(voices_dir / "voices.json", catalog_entry())

    assert [v.name for v in VoiceManager(voices_dir).catalog()] == ["fake"]


def test_catalog_is_empty_when_nothing_is_cached(voices_dir):
    assert VoiceManager(voices_dir).catalog() == []


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '"text"'])
def test_catalog_rejects_a_corrupt_cache(voices_dir, content):
    (voices_dir / "voices.json").write_text(content)

    with pytest.raises(VoiceError, match="voices.json"):
        VoiceManager(voices_dir).catalog()


def test_catalog_skips_malformed_and_unsafe_entries(voices_dir, tmp_path):
    good = catalog_entry()
    bad = {"key": "../evil", "name": "evil", "files": {}}
    catalog = tmp_path / "voices.json"
    catalog.write_text(json.dumps({good["key"]: good, "../evil": bad, "junk": 5}))

    assert [v.key for v in VoiceManager(voices_dir, catalog).catalog()] == [
        "piper:en_US-fake-medium"
    ]


def test_refresh_catalog_writes_the_cache(voices_dir):
    entry = catalog_entry()
    body = json.dumps({KEY: entry}).encode()
    manager = VoiceManager(voices_dir, downloader=FakeDownloader({CATALOG_URL: body}))

    refreshed = manager.refresh_catalog()

    assert [v.key for v in refreshed] == ["piper:en_US-fake-medium"]
    assert (voices_dir / "voices.json").read_bytes() == body
    assert leftovers(voices_dir) == ["voices.json"]


def test_refresh_catalog_keeps_the_old_cache_when_the_payload_is_garbage(voices_dir):
    old = write_catalog(voices_dir / "voices.json", catalog_entry())
    before = old.read_bytes()
    manager = VoiceManager(voices_dir, downloader=FakeDownloader({CATALOG_URL: b"<html>oops"}))

    with pytest.raises(VoiceError):
        manager.refresh_catalog()

    assert old.read_bytes() == before
    assert leftovers(voices_dir) == ["voices.json"]


# --- download --------------------------------------------------------------------------------


def make_manager(voices_dir: Path, tmp_path: Path, served: dict[str, bytes] | None = None):
    entry = catalog_entry()
    catalog = write_catalog(tmp_path / "voices.json", entry)
    downloader = FakeDownloader(payloads(entry) if served is None else served)
    return VoiceManager(voices_dir, catalog, downloader=downloader), downloader


def test_download_installs_both_files_after_the_md5_check(voices_dir, tmp_path):
    manager, downloader = make_manager(voices_dir, tmp_path)

    voice = manager.download(KEY)

    assert (voices_dir / f"{KEY}.onnx").read_bytes() == ONNX
    assert (voices_dir / f"{KEY}.onnx.json").read_bytes() == CONFIG
    assert (voice.key, voice.installed, voice.path) == (
        f"piper:{KEY}",
        True,
        voices_dir / f"{KEY}.onnx",
    )
    assert sorted(downloader.urls) == sorted(payloads(catalog_entry()))  # no MODEL_CARD
    assert leftovers(voices_dir) == [f"{KEY}.onnx", f"{KEY}.onnx.json"]


def test_download_accepts_the_prefixed_voice_key(voices_dir, tmp_path):
    manager, _ = make_manager(voices_dir, tmp_path)

    assert manager.download(f"piper:{KEY}").name == "fake"


def test_download_creates_the_voices_dir_on_demand(tmp_path):
    target = tmp_path / "fresh" / "voices"
    manager, _ = make_manager(target, tmp_path)

    manager.download(KEY)

    assert (target / f"{KEY}.onnx").exists()


def test_download_md5_mismatch_raises_and_leaves_the_install_untouched(voices_dir, tmp_path):
    install(voices_dir, KEY)  # a previous good install must survive a bad re-download
    (voices_dir / f"{KEY}.onnx").write_bytes(b"previous-good-model")
    unrelated = voices_dir / "keep-me.txt"
    unrelated.write_text("precious")
    served = payloads(catalog_entry(), onnx=b"corrupted-in-transit")
    manager, _ = make_manager(voices_dir, tmp_path, served)

    with pytest.raises(VoiceDownloadError, match="md5"):
        manager.download(KEY)

    assert (voices_dir / f"{KEY}.onnx").read_bytes() == b"previous-good-model"
    assert unrelated.read_text() == "precious"
    assert leftovers(voices_dir) == [f"{KEY}.onnx", f"{KEY}.onnx.json", "keep-me.txt"]


def test_download_config_mismatch_installs_nothing(voices_dir, tmp_path):
    served = payloads(catalog_entry(), config=b'{"tampered": true}')
    manager, _ = make_manager(voices_dir, tmp_path, served)

    with pytest.raises(VoiceDownloadError, match="md5"):
        manager.download(KEY)

    assert leftovers(voices_dir) == []


def test_download_failure_midway_installs_nothing(voices_dir, tmp_path):
    json_url = next(u for u in payloads(catalog_entry()) if u.endswith(".json"))
    manager, _ = make_manager(voices_dir, tmp_path, {json_url: CONFIG})  # onnx -> 404

    with pytest.raises(VoiceDownloadError, match="404"):
        manager.download(KEY)

    assert leftovers(voices_dir) == []


def test_download_publishes_the_model_last(voices_dir, tmp_path, monkeypatch):
    manager, _ = make_manager(voices_dir, tmp_path)
    moved: list[str] = []
    real_replace = os.replace

    def spy(src, dst):
        moved.append(Path(dst).name)
        real_replace(src, dst)

    monkeypatch.setattr(voices_module.os, "replace", spy)

    manager.download(KEY)

    # A scan keys on the .onnx file, so a half-installed voice is never listed.
    assert moved == [f"{KEY}.onnx.json", f"{KEY}.onnx"]


def test_download_unknown_key(voices_dir, tmp_path):
    manager, downloader = make_manager(voices_dir, tmp_path)

    with pytest.raises(VoiceError, match="unknown voice"):
        manager.download("en_US-nobody-medium")

    assert downloader.urls == []


def test_download_without_a_cached_catalog_says_to_refresh(voices_dir):
    manager = VoiceManager(voices_dir, downloader=FakeDownloader({}))

    with pytest.raises(VoiceError, match="refresh_catalog"):
        manager.download(KEY)


@pytest.mark.parametrize("key", ["piper:../evil", "a/b", "", "piper:"])
def test_download_rejects_unsafe_keys(voices_dir, tmp_path, key):
    manager, downloader = make_manager(voices_dir, tmp_path)

    with pytest.raises(VoiceError, match="invalid voice key"):
        manager.download(key)

    assert downloader.urls == []


@pytest.mark.parametrize(
    "path",
    [
        "../../escape/en_US-fake-medium.onnx",
        "/abs/en_US-fake-medium.onnx",
        "en/../../en_US-fake-medium.onnx",
        "en\\en_US-fake-medium.onnx",
    ],
)
def test_download_rejects_catalog_paths_that_escape(voices_dir, tmp_path, path):
    entry = catalog_entry()
    meta = entry["files"].pop(f"en/en_US/fake/medium/{KEY}.onnx")
    entry["files"][path] = meta
    manager = VoiceManager(
        voices_dir, write_catalog(tmp_path / "voices.json", entry), downloader=FakeDownloader({})
    )

    with pytest.raises(VoiceError, match="unsafe"):
        manager.download(KEY)

    assert leftovers(voices_dir) == []


def test_download_needs_both_files_in_the_catalog(voices_dir, tmp_path):
    entry = catalog_entry()
    del entry["files"][f"en/en_US/fake/medium/{KEY}.onnx.json"]
    manager = VoiceManager(
        voices_dir, write_catalog(tmp_path / "voices.json", entry), downloader=FakeDownloader({})
    )

    with pytest.raises(VoiceError, match=r"\.onnx\.json"):
        manager.download(KEY)


def test_download_rejects_a_malformed_md5_digest(voices_dir, tmp_path):
    entry = catalog_entry()
    entry["files"][f"en/en_US/fake/medium/{KEY}.onnx"]["md5_digest"] = "not-hex"
    manager = VoiceManager(
        voices_dir, write_catalog(tmp_path / "voices.json", entry), downloader=FakeDownloader({})
    )

    with pytest.raises(VoiceError, match="md5"):
        manager.download(KEY)


# --- HttpDownloader --------------------------------------------------------------------------


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_http_downloader_follows_redirects_and_streams_to_dest(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "huggingface.co":
            return httpx.Response(302, headers={"location": "https://cdn.example/blob"})
        return httpx.Response(200, content=b"voice-bytes" * 1000)

    dest = tmp_path / "file.onnx"

    HttpDownloader(client_for(handler))("https://huggingface.co/x/file.onnx", dest)

    assert dest.read_bytes() == b"voice-bytes" * 1000


def test_http_downloader_turns_http_errors_into_voice_download_errors(tmp_path):
    client = client_for(lambda request: httpx.Response(404))

    with pytest.raises(VoiceDownloadError, match="404"):
        HttpDownloader(client)("https://huggingface.co/missing", tmp_path / "f")


def test_http_downloader_turns_transport_errors_into_voice_download_errors(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(VoiceDownloadError, match="offline"):
        HttpDownloader(client_for(handler))("https://huggingface.co/x", tmp_path / "f")


# --- live network (never in the default run) -------------------------------------------------


@pytest.mark.network
def test_live_catalog_lists_lessac_and_downloads_the_smallest_english_voice(tmp_path):
    manager = VoiceManager(tmp_path / "voices")

    catalog = manager.refresh_catalog()

    assert "piper:en_US-lessac-medium" in {v.key for v in catalog}
    raw = json.loads((tmp_path / "voices" / "voices.json").read_text(encoding="utf-8"))
    english = [e for e in raw.values() if e["language"]["family"] == "en"]
    smallest = min(
        english,
        key=lambda e: sum(
            m["size_bytes"] for p, m in e["files"].items() if p.endswith((".onnx", ".onnx.json"))
        ),
    )

    voice = manager.download(smallest["key"])  # md5-verified against the live catalog

    assert voice.installed
    assert voice.path is not None and voice.path.stat().st_size > 1_000_000
    assert [v.key for v in manager.installed()] == [f"piper:{smallest['key']}"]
