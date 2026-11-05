"""The version lives in three files that must agree: pyproject.toml, the package, uv.lock."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_version_is_0_0_1_in_pyproject_init_and_the_lock():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    init = (ROOT / "cloudyreader" / "__init__.py").read_text()
    (declared,) = re.findall(r'^__version__ = "([^"]+)"$', init, re.M)
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    (entry,) = [p for p in lock["package"] if p["name"] == "cloudyreader"]

    assert pyproject == declared == entry["version"] == "0.0.1"
