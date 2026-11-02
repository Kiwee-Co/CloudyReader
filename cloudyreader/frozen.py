"""Frozen-app support: find "Cloudy Reader.app" resources and expose its bundled assets.

The bundle ships Piper voices (and Kokoro when built with it) read-only under
Contents/Resources/assets/{voices,models}. Symlinking each file into the user's data folders lets
the engines read `settings.voices_dir` / `settings.models_dir` unchanged.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cloudyreader.config import Settings

log = logging.getLogger(__name__)

# Link text of a symlink this module made: an absolute path into some bundle's assets.
_BUNDLE_ASSET = re.compile(r"\.app/Contents/Resources/assets/")


@dataclass(frozen=True)
class LinkAction:
    action: Literal["link", "relink"]
    path: Path  # the symlink in the user's data folder
    target: Path  # the bundled file it points at


def is_frozen() -> bool:
    """True inside a PyInstaller (or py2app) build."""
    return bool(getattr(sys, "frozen", False))


def bundle_resources_dir(executable: str | os.PathLike[str] | None = None) -> Path | None:
    """Contents/Resources of the .app around `executable` (default: this frozen process).

    None when not frozen, or when the executable does not sit in an .app's Contents/MacOS.
    """
    if executable is None:
        if not is_frozen():
            return None
        executable = sys.executable
    macos = Path(executable).resolve().parent
    resources = macos.parent / "Resources"
    if macos.name != "MacOS" or macos.parent.name != "Contents" or not resources.is_dir():
        return None
    return resources


def link_bundled_assets(
    settings: Settings, *, resources_dir: Path | None = None
) -> list[LinkAction]:
    """Symlink each bundled voice/model file into the user's data folders when absent.

    Never replaces a real file or a working symlink; replaces a dangling symlink only when it
    pointed into a bundle that has since moved. Idempotent. Returns the links made.
    """
    resources = resources_dir if resources_dir is not None else bundle_resources_dir()
    if resources is None:
        return []
    actions: list[LinkAction] = []
    for sub, dest_root in (("voices", settings.voices_dir), ("models", settings.models_dir)):
        src_root = resources / "assets" / sub
        if not src_root.is_dir():
            continue
        for src in sorted(p for p in src_root.rglob("*") if p.is_file()):
            dest = dest_root / src.relative_to(src_root)
            try:
                action = _link_one(src.absolute(), dest)
            except OSError as exc:  # one blocked path must not keep the app from starting
                log.warning("cannot link bundled asset %s -> %s: %s", dest, src, exc)
                continue
            if action is not None:
                actions.append(action)
    return actions


def _link_one(src: Path, dest: Path) -> LinkAction | None:
    if dest.is_symlink():
        if dest.exists() or not _BUNDLE_ASSET.search(os.readlink(dest)):
            return None  # working link, or a dangling one that someone else made
        dest.unlink()
        kind: Literal["link", "relink"] = "relink"
    elif dest.exists():
        return None
    else:
        kind = "link"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.symlink_to(src)
    return LinkAction(kind, dest, src)
