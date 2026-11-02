"""cloudyreader.frozen: locating the .app bundle and linking its read-only assets."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from cloudyreader import frozen
from cloudyreader.config import Settings
from cloudyreader.frozen import LinkAction, bundle_resources_dir, is_frozen, link_bundled_assets


def make_bundle(root: Path, name: str = "Cloudy Reader.app") -> Path:
    """A fake .app with two voices and one nested model file; returns Contents/Resources."""
    contents = root / name / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "MacOS" / "Cloudy Reader").write_bytes(b"exe")
    assets = contents / "Resources" / "assets"
    for rel in (
        "voices/en_US-lessac-medium.onnx",
        "voices/en_US-lessac-medium.onnx.json",
        "models/kokoro/voices/af_heart.safetensors",
    ):
        (assets / rel).parent.mkdir(parents=True, exist_ok=True)
        (assets / rel).write_text(rel)
    return contents / "Resources"


def make_settings(root: Path) -> Settings:
    data = root / "data"
    return Settings(data, data / "cache", data / "voices", data / "models")


@pytest.fixture
def resources(tmp_path: Path) -> Path:
    return make_bundle(tmp_path / "Applications")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


def test_is_frozen_false_in_plain_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert is_frozen() is False


def test_is_frozen_true_when_bundler_sets_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert is_frozen() is True


def test_resources_dir_none_when_not_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert bundle_resources_dir() is None


def test_resources_dir_from_explicit_executable(resources: Path) -> None:
    exe = resources.parent / "MacOS" / "Cloudy Reader"
    assert bundle_resources_dir(exe) == resources.resolve()


def test_resources_dir_from_sys_executable_when_frozen(
    monkeypatch: pytest.MonkeyPatch, resources: Path
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(resources.parent / "MacOS" / "Cloudy Reader"))
    assert bundle_resources_dir() == resources.resolve()


def test_resources_dir_none_outside_an_app_layout(tmp_path: Path) -> None:
    exe = tmp_path / "bin" / "python"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    assert bundle_resources_dir(exe) is None


def test_resources_dir_none_when_resources_missing(tmp_path: Path) -> None:
    exe = tmp_path / "X.app" / "Contents" / "MacOS" / "X"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert bundle_resources_dir(exe) is None


def test_links_every_asset_and_creates_parents(resources: Path, settings: Settings) -> None:
    actions = link_bundled_assets(settings, resources_dir=resources)

    voice = settings.voices_dir / "en_US-lessac-medium.onnx"
    model = settings.models_dir / "kokoro" / "voices" / "af_heart.safetensors"
    assert voice.is_symlink() and voice.read_text() == "voices/en_US-lessac-medium.onnx"
    assert (
        model.is_symlink()
        and model.resolve()
        == (resources / "assets/models/kokoro/voices/af_heart.safetensors").resolve()
    )
    assert (settings.voices_dir / "en_US-lessac-medium.onnx.json").is_symlink()
    assert sorted(a.path for a in actions) == sorted(
        [voice, settings.voices_dir / "en_US-lessac-medium.onnx.json", model]
    )
    assert {a.action for a in actions} == {"link"}


def test_second_run_is_a_no_op(resources: Path, settings: Settings) -> None:
    link_bundled_assets(settings, resources_dir=resources)
    assert link_bundled_assets(settings, resources_dir=resources) == []


def test_never_overwrites_a_real_file(resources: Path, settings: Settings) -> None:
    settings.voices_dir.mkdir(parents=True)
    mine = settings.voices_dir / "en_US-lessac-medium.onnx"
    mine.write_text("user copy")

    actions = link_bundled_assets(settings, resources_dir=resources)

    assert not mine.is_symlink() and mine.read_text() == "user copy"
    assert mine not in [a.path for a in actions]


def test_relinks_dangling_link_into_a_moved_bundle(tmp_path: Path, settings: Settings) -> None:
    old = make_bundle(tmp_path / "old")
    link_bundled_assets(settings, resources_dir=old)
    (tmp_path / "old" / "Cloudy Reader.app").rename(tmp_path / "old" / "Gone.app")
    new = make_bundle(tmp_path / "new")

    actions = link_bundled_assets(settings, resources_dir=new)

    voice = settings.voices_dir / "en_US-lessac-medium.onnx"
    assert voice.resolve() == (new / "assets/voices/en_US-lessac-medium.onnx").resolve()
    assert len(actions) == 3 and {a.action for a in actions} == {"relink"}
    assert all(a.target.is_relative_to(new) for a in actions)


def test_keeps_dangling_link_that_is_not_a_bundle_asset(
    tmp_path: Path, resources: Path, settings: Settings
) -> None:
    settings.voices_dir.mkdir(parents=True)
    foreign = settings.voices_dir / "en_US-lessac-medium.onnx"
    foreign.symlink_to(tmp_path / "unmounted-drive" / "voice.onnx")

    link_bundled_assets(settings, resources_dir=resources)

    assert foreign.is_symlink() and not foreign.exists()
    assert foreign.readlink() == tmp_path / "unmounted-drive" / "voice.onnx"


def test_keeps_valid_link_to_another_copy(
    tmp_path: Path, resources: Path, settings: Settings
) -> None:
    other = make_bundle(tmp_path / "elsewhere")
    link_bundled_assets(settings, resources_dir=other)

    assert link_bundled_assets(settings, resources_dir=resources) == []
    voice = settings.voices_dir / "en_US-lessac-medium.onnx"
    assert voice.resolve().is_relative_to(other.resolve())


def test_no_bundle_means_no_actions(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert link_bundled_assets(settings) == []
    assert not settings.data_dir.exists()


def test_bundle_without_assets_is_fine(tmp_path: Path, settings: Settings) -> None:
    resources = tmp_path / "Bare.app" / "Contents" / "Resources"
    resources.mkdir(parents=True)
    assert link_bundled_assets(settings, resources_dir=resources) == []


def test_one_failing_link_does_not_stop_the_rest(
    resources: Path, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    settings.models_dir.mkdir(parents=True)
    (settings.models_dir / "kokoro").write_text("a file where a folder must go")

    with caplog.at_level(logging.WARNING, logger=frozen.__name__):
        actions = link_bundled_assets(settings, resources_dir=resources)

    assert [a.path.name for a in actions] == [
        "en_US-lessac-medium.onnx",
        "en_US-lessac-medium.onnx.json",
    ]
    assert "af_heart.safetensors" in caplog.text


def test_link_action_is_a_value_object(tmp_path: Path) -> None:
    a = LinkAction("link", tmp_path / "a", tmp_path / "b")
    assert a == LinkAction("link", tmp_path / "a", tmp_path / "b")
    with pytest.raises(AttributeError):
        a.action = "relink"  # type: ignore[misc]
