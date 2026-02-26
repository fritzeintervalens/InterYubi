from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Win32 cursor constants
_OCR_NORMAL = 32512  # Standard arrow
_OCR_IBEAM = 32513   # Text select (I-beam)
_SPI_SETCURSORS = 0x0057

# Properly typed Win32 function bindings
_user32 = ctypes.WinDLL("user32", use_last_error=True)

_user32.LoadCursorFromFileW.argtypes = [wintypes.LPCWSTR]
_user32.LoadCursorFromFileW.restype = wintypes.HCURSOR

_user32.SetSystemCursor.argtypes = [wintypes.HCURSOR, wintypes.DWORD]
_user32.SetSystemCursor.restype = wintypes.BOOL

_user32.SystemParametersInfoW.argtypes = [
    wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT,
]
_user32.SystemParametersInfoW.restype = wintypes.BOOL

# Path to the .ani file (next to this script)
_ANI_PATH = str(Path(__file__).parent / "assets" / "trigger.ani")

# No-op for when cursor swap is unavailable
_NOOP: Callable[[], None] = lambda: None


def trigger_cursor_feedback() -> Callable[[], None]:
    """Swap system cursor to animated key icon.

    Returns a *restore* callable.  The caller MUST invoke it (ideally in
    a ``finally`` block) to reset the cursor to the user's scheme.
    If the ``.ani`` file is missing or fails to load, returns a no-op.
    """
    if not Path(_ANI_PATH).is_file():
        logger.debug("Cursor animation skipped — %s not found", _ANI_PATH)
        return _NOOP

    swapped = False
    # Load a fresh handle per cursor ID — SetSystemCursor destroys the
    # handle it receives, and a fresh LoadCursorFromFileW preserves the
    # full .ani animation (CopyIcon strips it).
    for cursor_id in (_OCR_NORMAL, _OCR_IBEAM):
        h_cursor = _user32.LoadCursorFromFileW(_ANI_PATH)
        if h_cursor:
            _user32.SetSystemCursor(h_cursor, cursor_id)
            swapped = True

    if not swapped:
        logger.debug("Failed to load cursor from %s", _ANI_PATH)
        return _NOOP

    def _restore() -> None:
        _user32.SystemParametersInfoW(_SPI_SETCURSORS, 0, None, 0)

    return _restore
