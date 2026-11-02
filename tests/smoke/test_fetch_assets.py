"""Unit tests for scripts/fetch_assets.py: no network, no real .data/ writes."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fetch_assets.py"
PAYLOAD = b"voice model bytes"


@pytest.fixture
def fa(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("fetch_assets", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "LOCK", tmp_path / "assets.lock.json")
    monkeypatch.setattr(module, "DATA", tmp_path / ".data")
    monkeypatch.setattr(module, "MANIFEST", tmp_path / ".data" / "downloads.tsv")
    return module


def asset(payload=PAYLOAD, **overrides):
    entry = {
        "name": "v.onnx",
        "group": "voices",
        "url": "https://example.org/v.onnx",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
        "dest": ".data/voices",
    }
    return entry | overrides


def serve(fa, monkeypatch, body):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request.full_url)
            return io.BytesIO(body)

    monkeypatch.setattr(fa.urllib.request, "build_opener", lambda *handlers: Opener())
    return calls


def write_lock(fa, *entries):
    fa.LOCK.write_text(json.dumps({"version": 1, "assets": list(entries)}))


def leftovers(fa):
    return sorted(p.name for p in fa.DATA.glob(".fetch-*")) if fa.DATA.exists() else []


def test_fetch_downloads_verifies_moves_and_records(fa, monkeypatch):
    serve(fa, monkeypatch, PAYLOAD)
    write_lock(fa, asset())
    assert fa.fetch(fa.load([], []), offline=False) == 0
    assert (fa.DATA / "voices" / "v.onnx").read_bytes() == PAYLOAD
    assert "https://example.org/v.onnx" in fa.MANIFEST.read_text()
    assert leftovers(fa) == []


def test_fetch_refuses_sha256_mismatch_and_keeps_nothing(fa, monkeypatch):
    serve(fa, monkeypatch, b"tampered bytes!!!")
    write_lock(fa, asset())
    with pytest.raises(fa.FetchError, match="SHA256"):
        fa.fetch(fa.load([], []), offline=False)
    assert not (fa.DATA / "voices" / "v.onnx").exists()
    assert leftovers(fa) == []


def test_fetch_refuses_body_larger_than_pinned_size(fa, monkeypatch):
    serve(fa, monkeypatch, PAYLOAD + b"extra")
    write_lock(fa, asset())
    with pytest.raises(fa.FetchError, match="exceeds pinned size"):
        fa.fetch(fa.load([], []), offline=False)
    assert leftovers(fa) == []


def test_fetch_skips_valid_file_without_network(fa, monkeypatch):
    calls = serve(fa, monkeypatch, PAYLOAD)
    write_lock(fa, asset())
    (fa.DATA / "voices").mkdir(parents=True)
    (fa.DATA / "voices" / "v.onnx").write_bytes(PAYLOAD)
    assert fa.fetch(fa.load([], []), offline=False) == 0
    assert calls == []


def test_fetch_refuses_present_but_invalid_file(fa, monkeypatch):
    serve(fa, monkeypatch, PAYLOAD)
    write_lock(fa, asset())
    (fa.DATA / "voices").mkdir(parents=True)
    (fa.DATA / "voices" / "v.onnx").write_bytes(b"x" * len(PAYLOAD))
    with pytest.raises(fa.FetchError, match="fails its size or SHA256"):
        fa.fetch(fa.load([], []), offline=False)


def test_offline_refuses_missing_asset(fa, monkeypatch):
    calls = serve(fa, monkeypatch, PAYLOAD)
    write_lock(fa, asset())
    with pytest.raises(fa.FetchError, match="OFFLINE=1"):
        fa.fetch(fa.load([], []), offline=True)
    assert calls == []


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
    ],
)
def test_load_rejects_unsafe_lock_entries(fa, overrides):
    write_lock(fa, asset(**overrides))
    with pytest.raises(fa.FetchError, match="invalid entry"):
        fa.load([], [])


def test_load_rejects_voice_missing_from_lock(fa):
    write_lock(fa, asset())
    with pytest.raises(fa.FetchError, match="not in assets.lock.json: en_US-nobody-medium"):
        fa.load([], ["en_US-nobody-medium"])


def test_redirect_to_plain_http_is_refused(fa):
    with pytest.raises(fa.FetchError, match="non-HTTPS"):
        fa.HttpsOnlyRedirects().redirect_request(None, None, 302, "", {}, "http://x.org/v")


def test_paths_report_lists_only_verified_files(fa, capsys):
    write_lock(fa, asset(), asset(name="w.onnx"))
    (fa.DATA / "voices").mkdir(parents=True)
    (fa.DATA / "voices" / "v.onnx").write_bytes(PAYLOAD)
    assert fa.report(fa.load([], []), deep=True, paths=True) == 1
    out, err = capsys.readouterr()
    assert out.strip() == str(fa.DATA / "voices" / "v.onnx")
    assert "missing: .data/voices/w.onnx" in err
