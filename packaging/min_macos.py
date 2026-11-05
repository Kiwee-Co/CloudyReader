"""Oldest macOS that loads every Mach-O file of a bundle: what LSMinimumSystemVersion must say.

Stdlib only; it reads load commands, never runs a tool. Wheel tags can understate the answer:
PySide6 6.12 is tagged macOS 14.0, yet its bindings are built for 26.0.
"""

from __future__ import annotations

import os
import struct
from collections.abc import Iterable
from typing import BinaryIO

Version = tuple[int, int, int]

_THIN = b"\xcf\xfa\xed\xfe"  # 64-bit Mach-O, little-endian: arm64 and x86_64
_FAT = b"\xca\xfe\xba\xbe"  # universal binary; a Java class file starts the same way
_MAX_SLICES = 20  # like file(1): a class file's "slice count" is its major version, 45 or more
_CPU_ARM64 = 0x0100000C
_LC_VERSION_MIN_MACOSX, _LC_BUILD_VERSION, _PLATFORM_MACOS = 0x24, 0x32, 1


def _version(packed: int) -> Version:
    return packed >> 16, packed >> 8 & 0xFF, packed & 0xFF


def _slice_versions(f: BinaryIO, base: int) -> list[tuple[Version, Version]]:
    """(minos, sdk) from the load commands of the thin Mach-O that starts at byte `base`."""
    f.seek(base)
    head = f.read(32)
    if len(head) < 32 or head[:4] != _THIN:
        return []
    ncmds, size = struct.unpack_from("<II", head, 16)
    cmds = f.read(size)
    found, at = [], 0
    for _ in range(ncmds):
        if at + 8 > len(cmds):
            break
        cmd, cmdsize = struct.unpack_from("<II", cmds, at)
        if cmd == _LC_BUILD_VERSION and at + 20 <= len(cmds):
            platform, minos, sdk = struct.unpack_from("<III", cmds, at + 8)
            if platform == _PLATFORM_MACOS:
                found.append((_version(minos), _version(sdk)))
        elif cmd == _LC_VERSION_MIN_MACOSX and at + 16 <= len(cmds):
            minos, sdk = struct.unpack_from("<II", cmds, at + 8)
            found.append((_version(minos), _version(sdk)))
        if cmdsize < 8:
            break
        at += cmdsize
    return found


def read_versions(path: str | os.PathLike[str]) -> list[tuple[Version, Version]]:
    """(minos, sdk) of each macOS slice of the Mach-O file at path; [] for any other file.

    A universal binary counts only its arm64 slices when it has some: the bundle is arm64.
    """
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic == _THIN:
                return _slice_versions(f, 0)
            if magic != _FAT:
                return []
            (count,) = struct.unpack(">I", f.read(4))
            if not 0 < count <= _MAX_SLICES:
                return []
            table = f.read(20 * count)
            slices = [struct.unpack_from(">III", table, 20 * i) for i in range(count)]
            arm64 = [s for s in slices if s[0] == _CPU_ARM64] or slices
            return [v for _cpu, _sub, offset in arm64 for v in _slice_versions(f, offset)]
    except (OSError, struct.error):
        return []


def min_macos(paths: Iterable[str | os.PathLike[str]], floor: str = "11.0") -> str:
    """The highest minos among the Mach-O files in paths, never below floor: "26.0", "26.2.1"."""
    newest = tuple(int(part) for part in f"{floor}.0.0".split(".")[:3])
    for path in paths:
        for minos, _sdk in read_versions(path):
            newest = max(newest, minos)
    return ".".join(map(str, newest if newest[2] else newest[:2]))
