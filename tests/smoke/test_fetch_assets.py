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
        {"group": "plugins"},
        {"name": "af_heart.pt"},
        {"name": "model.PTH"},
    ],
)
def test_load_rejects_unsafe_lock_entries(fa, overrides):
    write_lock(fa, asset(**overrides))
    with pytest.raises(fa.FetchError, match="invalid entry"):
        fa.load([], [])


def test_kokoro_group_lands_in_nested_dest(fa, monkeypatch):
    serve(fa, monkeypatch, PAYLOAD)
    voice = asset(name="af_heart.safetensors", group="kokoro", dest=".data/models/kokoro/voices")
    write_lock(fa, asset(), voice)
    assert fa.fetch(fa.load(["kokoro"], []), offline=False) == 0
    assert (fa.DATA / "models" / "kokoro" / "voices" / "af_heart.safetensors").is_file()
    assert not (fa.DATA / "voices" / "v.onnx").exists()


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


# --- engine groups (appended for the engines build) -----------------------------------------------


def engine_asset(rel="config.json", group="qwen3_tts", **overrides):
    sub, _, name = rel.rpartition("/")
    entry = asset(
        name=name,
        group=group,
        url=f"https://example.org/{group}/resolve/{'0' * 40}/{rel}",
        dest=f".data/models/{group}" + (f"/{sub}" if sub else ""),
    )
    return entry | overrides


# The cases of test_load_rejects_unsafe_lock_entries, repeated for the parity check.
UNSAFE = [
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
]
ENGINE_UNSAFE = [
    {"dest": ".data/models/kokoro"},
    {"dest": ".data/models/qwen3_tts/speech_tokenizer/extra"},
    {"dest": ".data/models"},
    {"dest": ".data/models/qwen3_tts/.."},
    {"dest": "/data/models/qwen3_tts"},
    {"url": "https://example.org/qwen3_tts/resolve/main/config.json"},
    {"url": "https://example.org/qwen3_tts/config.json"},
    {"url": f"https://example.org/x?ref=/resolve/{'0' * 40}/config.json"},
    {"name": "model.py"},
    {"name": "weights.npy"},
    {"name": "chat_template.jinja"},
    {"name": "conds.pt"},
    {"name": "model.onnx"},
]


def test_engine_entries_fetch_into_their_models_folder(fa, monkeypatch):
    serve(fa, monkeypatch, PAYLOAD)
    write_lock(fa, asset(), engine_asset("speech_tokenizer/model.safetensors"))

    assert fa.fetch(fa.load(["qwen3_tts"], []), offline=False) == 0

    target = fa.DATA / "models" / "qwen3_tts" / "speech_tokenizer" / "model.safetensors"
    assert target.read_bytes() == PAYLOAD
    assert not (fa.DATA / "voices" / "v.onnx").exists()


@pytest.mark.parametrize("overrides", ENGINE_UNSAFE)
def test_load_rejects_unsafe_engine_entries(fa, overrides):
    write_lock(fa, asset(), engine_asset() | overrides)

    with pytest.raises(fa.FetchError, match="invalid entry"):
        fa.load([], [])


def test_fetch_assets_validator_parity(fa):
    from cloudyreader import engine_catalog, prefetch

    shared = ("GROUPS", "ENGINE_GROUPS", "PICKLE_SUFFIXES", "DATA_SUFFIXES", "DEST_ROOTS")
    assert {n: getattr(fa, n) for n in shared} == {n: getattr(prefetch, n) for n in shared}
    assert fa.ENGINE_SUFFIXES == engine_catalog.ENGINE_SUFFIXES
    good = [
        asset(),
        asset(name="notes.txt"),
        asset(name="af_heart.safetensors", group="kokoro", dest=".data/models/kokoro/voices"),
        asset(name="ner-0.5.4.tar.gz", group="models", dest=".data/models/ner"),
        engine_asset(),
        engine_asset("merges.txt"),
        engine_asset("speech_tokenizer/config.json"),
        engine_asset("tokenizer/vocab.json"),
        engine_asset("conds.safetensors", "chatterbox_turbo"),
    ]
    bad = [
        *(asset(**overrides) for overrides in UNSAFE),
        *(engine_asset() | overrides for overrides in ENGINE_UNSAFE),
        "not a dict",
        {},
        asset(size=True),
        asset(size="12"),
        asset(name=7),
        asset(name=".bashrc"),
        asset(name="run.sh"),
        asset(dest=".data/cache"),
        asset(dest=".data"),
        asset(url="https://user:pw@example.org/v.onnx"),
        asset(url="https://"),
        asset(url="https://[broken/v.onnx"),
    ]
    for entry in good:
        assert (fa.safe_entry(entry), prefetch._safe_entry(entry)) == (True, True), entry
    for entry in bad:
        assert (fa.safe_entry(entry), prefetch._safe_entry(entry)) == (False, False), entry
    with pytest.raises(fa.FetchError, match="invalid entry"):
        fa.validate("not a dict")
