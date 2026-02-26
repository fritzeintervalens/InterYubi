from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from pathlib import Path

logger = logging.getLogger(__name__)

# Win32 cursor constants
_OCR_NORMAL = 32512  # Standard arrow
_OCR_IBEAM = 32513   # Text select (I-beam)
_SPI_SETCURSORS = 0x0057

# Properly typed Win32 function bindings
_user32 = ctypes.WinDLL("user32", use_last_error=True)

_user32.LoadCursorFromFileW.argtypes = [wintypes.LPCWSTR]
_user32.LoadCursorFromFileW.restype = wintypes.HCURSOR

# CopyCursor is a C macro that maps to CopyIcon
_user32.CopyIcon.argtypes = [wintypes.HICON]
_user32.CopyIcon.restype = wintypes.HICON

_user32.SetSystemCursor.argtypes = [wintypes.HCURSOR, wintypes.DWORD]
_user32.SetSystemCursor.restype = wintypes.BOOL

_user32.SystemParametersInfoW.argtypes = [
    wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT,
]
_user32.SystemParametersInfoW.restype = wintypes.BOOL

_user32.DestroyCursor.argtypes = [wintypes.HCURSOR]
_user32.DestroyCursor.restype = wintypes.BOOL

# Path to the .ani file (next to this script)
_ANI_PATH = str(Path(__file__).parent / "assets" / "trigger.ani")


def _flash_cursor(duration_s: float = 1.0) -> None:
    """Replace system cursor with animated cursor, restore after duration."""
    if not Path(_ANI_PATH).is_file():
        logger.debug("Cursor animation skipped — %s not found", _ANI_PATH)
        return

    h_cursor = _user32.LoadCursorFromFileW(_ANI_PATH)
    if not h_cursor:
        logger.debug("Failed to load cursor from %s", _ANI_PATH)
        return

    try:
        # Replace arrow and I-beam (user is likely in a text field)
        for cursor_id in (_OCR_NORMAL, _OCR_IBEAM):
            h_copy = _user32.CopyIcon(h_cursor)
            if h_copy:
                _user32.SetSystemCursor(h_copy, cursor_id)

        time.sleep(duration_s)
    finally:
        # Restore all cursors to user's configured scheme
        _user32.SystemParametersInfoW(_SPI_SETCURSORS, 0, None, 0)
        _user32.DestroyCursor(h_cursor)


def trigger_cursor_feedback(duration_s: float = 1.0) -> None:
    """Fire-and-forget: flash the cursor animation in a background thread."""
    t = threading.Thread(target=_flash_cursor, args=(duration_s,), daemon=True)
    t.start()
