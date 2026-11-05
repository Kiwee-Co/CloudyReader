"""Overrides PyInstaller's own hook-scipy.special._ufuncs: hooks in the spec's hookspath outrank it.

The same hidden imports, except scipy.special._cdflib where the installed SciPy has no such
extension: SciPy 1.13 added it, and the locked 1.17.1 no longer has it.
"""

from pathlib import Path

from PyInstaller.utils.hooks import get_package_paths, is_module_satisfies

# The _ufuncs extension imports these from C, where the import scan cannot see them.
hiddenimports = ["scipy.special._ufuncs_cxx"]

_special = Path(get_package_paths("scipy")[1]) / "special"
if is_module_satisfies("scipy >= 1.13.0") and any(_special.glob("_cdflib.*")):
    hiddenimports += ["scipy.special._cdflib"]

if is_module_satisfies("scipy >= 1.14.0"):
    hiddenimports += ["scipy.special._special_ufuncs"]
