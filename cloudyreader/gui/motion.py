"""The macOS Reduce Motion setting, read through the Objective-C runtime with ctypes.

Public API only: NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion (AppKit) and
the runtime's objc_getClass, sel_registerName, and objc_msgSend. Any failure reads as off, so the
app animates as it always has: reduce_motion() never raises.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import sys
from collections.abc import Callable

log = logging.getLogger(__name__)


def _library(name: str) -> ctypes.CDLL:
    path = ctypes.util.find_library(name)
    if path is None:
        raise OSError(f"no {name} library")
    return ctypes.CDLL(path)


def appkit_reduce_motion() -> bool:
    """Ask AppKit directly. Raises OSError, or a ctypes error, when it cannot."""
    objc = _library("objc")
    _library("AppKit")  # loads NSWorkspace into the runtime
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    # objc_msgSend must be called through the exact prototype of each message, on arm64 too.
    send = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
    send_id = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(send)
    send_bool = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(send)
    workspace_class = objc.objc_getClass(b"NSWorkspace")
    if not workspace_class:
        raise OSError("no NSWorkspace class")
    workspace = send_id(workspace_class, objc.sel_registerName(b"sharedWorkspace"))
    if not workspace:
        raise OSError("no shared NSWorkspace")
    selector = objc.sel_registerName(b"accessibilityDisplayShouldReduceMotion")
    return bool(send_bool(workspace, selector))


def reduce_motion(read: Callable[[], bool] = appkit_reduce_motion) -> bool:
    """Whether the user asked macOS to reduce motion: False elsewhere, and on any failure."""
    if sys.platform != "darwin":
        return False
    try:
        return bool(read())
    except Exception:  # a missing library, class, or symbol must never stop the app
        log.debug("Reduce Motion is unreadable; treating it as off", exc_info=True)
        return False
