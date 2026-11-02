"""Runtime settings: data locations and network budgets, read from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_ENV = "CLOUDYREADER_DATA_DIR"
OFFLINE_ENV = "CLOUDYREADER_OFFLINE"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    cache_dir: Path
    voices_dir: Path
    models_dir: Path
    lookup_budget_s: float = 2.5
    http_timeout_s: float = 4.0
    max_rps: float = 5.0
    offline: bool = False  # True means zero HTTP


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from `env` (default: os.environ). Pure: creates no directories."""
    env = os.environ if env is None else env
    override = env.get(DATA_DIR_ENV, "").strip()
    if override:
        # Absolute so a later chdir (GUI launched from Finder) cannot move the data.
        data_dir = Path(override).expanduser().absolute()
    else:
        data_dir = Path.home() / "Library" / "Application Support" / "cloudyreader"
    return Settings(
        data_dir=data_dir,
        cache_dir=data_dir / "cache",
        voices_dir=data_dir / "voices",
        models_dir=data_dir / "models",
        offline=env.get(OFFLINE_ENV, "").strip().lower() in _TRUE_VALUES,
    )
