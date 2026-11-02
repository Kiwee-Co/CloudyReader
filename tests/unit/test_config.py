"""Settings: env-driven data dir, derived dirs, offline flag. No test touches the real home."""

import dataclasses
from pathlib import Path

import pytest

from cloudyreader.config import Settings, load_settings

APP_SUPPORT = Path("Library") / "Application Support" / "cloudyreader"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Fake HOME, empty at the start, so the default data dir never resolves to the real one."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    return fake


def test_default_data_dir_is_under_application_support(home):
    assert load_settings({}).data_dir == home / APP_SUPPORT


def test_env_data_dir_overrides_default(tmp_path):
    settings = load_settings({"CLOUDYREADER_DATA_DIR": str(tmp_path / "data")})
    assert settings.data_dir == tmp_path / "data"


@pytest.mark.parametrize("override", [None, "custom"])
def test_derived_dirs_hang_off_data_dir(home, tmp_path, override):
    env = {} if override is None else {"CLOUDYREADER_DATA_DIR": str(tmp_path / override)}
    settings = load_settings(env)
    base = home / APP_SUPPORT if override is None else tmp_path / override
    assert settings.cache_dir == base / "cache"
    assert settings.voices_dir == base / "voices"
    assert settings.models_dir == base / "models"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_data_dir_env_falls_back_to_default(home, blank):
    # Path("") is "." : a blank variable would otherwise scatter data into the cwd.
    assert load_settings({"CLOUDYREADER_DATA_DIR": blank}).data_dir == home / APP_SUPPORT


def test_tilde_in_data_dir_is_expanded(home):
    assert load_settings({"CLOUDYREADER_DATA_DIR": "~/cr"}).data_dir == home / "cr"


def test_relative_data_dir_is_pinned_to_cwd(tmp_path, monkeypatch):
    # A GUI launched from Finder has a different cwd later; a relative path would drift with it.
    monkeypatch.chdir(tmp_path)
    settings = load_settings({"CLOUDYREADER_DATA_DIR": ".data"})
    assert settings.data_dir == tmp_path / ".data"
    assert settings.voices_dir.is_absolute()


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, False),
        ({"CLOUDYREADER_OFFLINE": "1"}, True),
        ({"CLOUDYREADER_OFFLINE": "true"}, True),
        ({"CLOUDYREADER_OFFLINE": " On "}, True),
        ({"CLOUDYREADER_OFFLINE": "0"}, False),
        ({"CLOUDYREADER_OFFLINE": "false"}, False),
        ({"CLOUDYREADER_OFFLINE": ""}, False),
    ],
)
def test_offline_flag(env, expected):
    assert load_settings(env).offline is expected


def test_budget_defaults():
    settings = load_settings({})
    assert settings.lookup_budget_s == 2.5
    assert settings.http_timeout_s == 4.0
    assert settings.max_rps == 5.0


def test_load_settings_creates_no_directories(home, tmp_path):
    data = tmp_path / "data"
    load_settings({"CLOUDYREADER_DATA_DIR": str(data)})
    load_settings({})
    assert not data.exists()
    assert list(home.iterdir()) == []


def test_none_env_reads_process_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDYREADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CLOUDYREADER_OFFLINE", "1")
    settings = load_settings()
    assert settings.data_dir == tmp_path / "data"
    assert settings.offline is True


def test_explicit_env_ignores_process_environment(monkeypatch, tmp_path, home):
    monkeypatch.setenv("CLOUDYREADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CLOUDYREADER_OFFLINE", "1")
    settings = load_settings({})
    assert settings.data_dir == home / APP_SUPPORT
    assert settings.offline is False


def test_settings_is_frozen(tmp_path):
    settings = load_settings({"CLOUDYREADER_DATA_DIR": str(tmp_path)})
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.offline = True


def test_settings_field_order_and_defaults(tmp_path):
    a, b, c, d = (tmp_path / name for name in "abcd")
    settings = Settings(a, b, c, d)
    assert (settings.data_dir, settings.cache_dir, settings.voices_dir, settings.models_dir) == (
        a,
        b,
        c,
        d,
    )
    assert (settings.lookup_budget_s, settings.http_timeout_s, settings.max_rps) == (2.5, 4.0, 5.0)
    assert settings.offline is False
