"""Overrides pyinstaller-hooks-contrib's hook-pycparser: hooks in the spec's hookspath outrank it.

That hook names pycparser.lextab and pycparser.yacctab, PLY tables that pycparser 3 no longer has
(its lexer and parser are hand-written). Each is kept only where the installed pycparser ships it.
"""

from pathlib import Path

from PyInstaller.utils.hooks import get_package_paths

_pycparser = Path(get_package_paths("pycparser")[1])
hiddenimports = [
    f"pycparser.{table}"
    for table in ("lextab", "yacctab")
    if (_pycparser / f"{table}.py").is_file()
]
