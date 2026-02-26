from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Optional

import keyboard
import pystray
from PIL import Image, ImageDraw

from config import (
    CONFIG,
    HOTKEY_DEBOUNCE_S,
    QUEUE_POLL_TIMEOUT_S,
    AppConfig,
    save_config,
    update_config,
)
from yubikey import (
    YubiKeyError,
    check_authenticator_running,
    check_ykman_available,
    fetch_code_for_account,
    fetch_totp_codes,
    list_totp_accounts,
)
from selector import get_monitor_work_area, show_account_selector
from theme import ACCENT_COLOR, SUBTEXT_COLOR, TEXT_COLOR, TITLE_BG
from cursor_feedback import trigger_cursor_feedback
from typing_engine import type_code

logger = logging.getLogger(__name__)

# Thread communication queue (keyboard callbacks fire on background thread,
# but tkinter must run on the main thread)
_trigger_queue: queue.Queue[str] = queue.Queue()

# Shutdown event for clean thread coordination
_shutdown_event = threading.Event()

# Global tray icon reference
_tray_icon: Optional[pystray.Icon] = None

# Hidden tkinter root (created in main, used for all UI windows)
_tk_root: Optional[tk.Tk] = None

# Debounce tracking
_last_trigger_time: float = 0.0

# If ykman's stderr prompt hasn't arrived after this many seconds, show the
# touch overlay anyway (safety net for buffered or missing stderr output).
_TOUCH_READY_FALLBACK_S: float = 3.0

# Hotkey hook IDs for re-registration
_hotkey_id: Optional[int] = None
_selector_hotkey_id: Optional[int] = None

# Settings window reference (prevent duplicates)
_settings_window = None

# --- Startup shortcut management ---

_STARTUP_FOLDER = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
_SHORTCUT_NAME = "InterYubi.lnk"
_SHORTCUT_PATH = _STARTUP_FOLDER / _SHORTCUT_NAME
_LEGACY_SHORTCUT_NAME = "YubiKey TOTP AutoFill.lnk"
_LEGACY_SHORTCUT_PATH = _STARTUP_FOLDER / _LEGACY_SHORTCUT_NAME


def _check_startup_shortcut_exists() -> bool:
    """Check if the startup shortcut exists."""
    return _SHORTCUT_PATH.is_file()


def _create_startup_shortcut() -> None:
    """Create a Windows Startup folder shortcut via PowerShell."""
    script_dir = Path(__file__).parent
    vbs_path = script_dir / "interyubi_silent.vbs"

    ps_command = (
        '$ws = New-Object -ComObject WScript.Shell; '
        f'$s = $ws.CreateShortcut("{_SHORTCUT_PATH}"); '
        f'$s.TargetPath = "wscript.exe"; '
        f'$s.Arguments = \'"{vbs_path}"\'; '
        f'$s.WorkingDirectory = "{script_dir}"; '
        '$s.Description = "InterYubi - auto-type TOTP codes from YubiKey"; '
        '$s.Save()'
    )
    try:
        subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
            capture_output=True, timeout=10,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        logger.info("Startup shortcut created at %s", _SHORTCUT_PATH)
    except Exception as e:
        logger.error("Failed to create startup shortcut: %s", e)


def _remove_startup_shortcut() -> None:
    """Remove the startup shortcut if it exists."""
    try:
        if _SHORTCUT_PATH.is_file():
            _SHORTCUT_PATH.unlink()
            logger.info("Startup shortcut removed")
    except Exception as e:
        logger.error("Failed to remove startup shortcut: %s", e)


def _cleanup_legacy_shortcut() -> None:
    """Remove old 'YubiKey TOTP AutoFill' shortcut if it exists."""
    try:
        if _LEGACY_SHORTCUT_PATH.is_file():
            _LEGACY_SHORTCUT_PATH.unlink()
            logger.info("Removed legacy startup shortcut: %s", _LEGACY_SHORTCUT_NAME)
    except Exception:
        pass


# --- Hotkey callbacks ---

def _on_hotkey_pressed() -> None:
    """Called by keyboard library on a background thread. Signals the main thread."""
    global _last_trigger_time
    now = time.monotonic()
    if now - _last_trigger_time < HOTKEY_DEBOUNCE_S:
        logger.debug("Hotkey debounced (%.1fs since last)", now - _last_trigger_time)
        return
    _last_trigger_time = now
    _trigger_queue.put("trigger")


def _on_selector_hotkey_pressed() -> None:
    """Called when the 'always show selector' hotkey is pressed."""
    global _last_trigger_time
    now = time.monotonic()
    if now - _last_trigger_time < HOTKEY_DEBOUNCE_S:
        return
    _last_trigger_time = now
    _trigger_queue.put("trigger_selector")


# --- Notifications ---

def _show_notification(message: str, title: str = "InterYubi") -> None:
    """Show a non-blocking tray balloon notification."""
    if _tray_icon and _tray_icon.visible:
        try:
            _tray_icon.notify(message, title)
        except Exception:
            logger.warning("Notification (tray failed): %s", message)
    else:
        logger.warning("Notification (no tray): %s", message)


def _show_touch_overlay() -> Optional[tk.Toplevel]:
    """Show a small always-on-top overlay prompting the user to touch their YubiKey.

    Returns the Toplevel window so the caller can destroy it when done.
    Returns None if the tkinter root is not available.
    """
    if _tk_root is None:
        return None

    try:
        overlay = tk.Toplevel(_tk_root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.configure(bg=TITLE_BG)

        # Main content frame with padding
        frame = tk.Frame(overlay, bg=TITLE_BG, padx=16, pady=12)
        frame.pack(fill="both", expand=True)

        # Accent bar on the left side (visual indicator)
        accent_bar = tk.Frame(frame, bg=ACCENT_COLOR, width=4)
        accent_bar.pack(side="left", fill="y", padx=(0, 12))

        # Text content
        text_frame = tk.Frame(frame, bg=TITLE_BG)
        text_frame.pack(side="left", fill="both", expand=True)

        tk.Label(
            text_frame,
            text="Touch your YubiKey...",
            font=("Segoe UI", 11, "bold"),
            fg=TEXT_COLOR,
            bg=TITLE_BG,
            anchor="w",
        ).pack(anchor="w")

        tk.Label(
            text_frame,
            text="Waiting for touch to generate TOTP code",
            font=("Segoe UI", 8),
            fg=SUBTEXT_COLOR,
            bg=TITLE_BG,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # Position near cursor, respecting multi-monitor work areas
        overlay.update_idletasks()
        win_width = overlay.winfo_reqwidth()
        win_height = overlay.winfo_reqheight()

        mouse_x = overlay.winfo_pointerx()
        mouse_y = overlay.winfo_pointery()

        x = mouse_x - 20
        y = mouse_y - 20

        work_area = get_monitor_work_area(mouse_x, mouse_y)
        if work_area is not None:
            mon_left, mon_top, mon_right, mon_bottom = work_area
        else:
            mon_left, mon_top = 0, 0
            mon_right = overlay.winfo_screenwidth()
            mon_bottom = overlay.winfo_screenheight()

        if x + win_width > mon_right:
            x = mon_right - win_width - 10
        if y + win_height > mon_bottom:
            y = mon_bottom - win_height - 10
        if x < mon_left:
            x = mon_left + 10
        if y < mon_top:
            y = mon_top + 10

        overlay.geometry(f"+{x}+{y}")
        overlay.update()
        return overlay

    except Exception:
        logger.warning("Failed to create touch overlay")
        return None


def _run_with_touch_overlay(
    target_fn,
    ready_event: Optional[threading.Event] = None,
):
    """Run *target_fn* in a background thread, optionally showing a touch overlay.

    If *ready_event* is provided the overlay is deferred until the event is
    set (meaning ykman is actually waiting for a physical touch), a fallback
    timeout elapses, or the task finishes — whichever comes first.  If the
    task finishes before the event fires the overlay is never shown at all.

    If *ready_event* is ``None`` the function runs *target_fn* in the
    background while pumping the tkinter event loop.  A time-based fallback
    shows the overlay if the task is still running after
    ``_TOUCH_READY_FALLBACK_S`` seconds (safety net for unexpected blocking).

    Any exception raised by *target_fn* is re-raised on the main thread.
    """
    result_holder: dict = {"value": None, "error": None, "done": False}

    def _bg() -> None:
        try:
            result_holder["value"] = target_fn()
        except Exception as exc:
            result_holder["error"] = exc
        finally:
            result_holder["done"] = True

    thread = threading.Thread(target=_bg, daemon=True)
    thread.start()

    overlay = None

    if ready_event is not None:
        # Wait for the touch-ready signal, task completion, or fallback
        # timeout — whichever comes first.  Pump tkinter in the meantime.
        deadline = time.monotonic() + _TOUCH_READY_FALLBACK_S
        while not result_holder["done"] and not ready_event.is_set():
            if time.monotonic() >= deadline:
                logger.debug("Touch-ready fallback timeout reached, showing overlay")
                break
            if _tk_root is not None:
                _tk_root.update()
            time.sleep(0.05)

        # Only show the overlay if the task is still running (i.e. ykman
        # is actually waiting for touch).
        if not result_holder["done"]:
            overlay = _show_touch_overlay()

    # Pump tkinter event loop while waiting for completion.
    # When no ready_event was provided, use a time-based fallback: if the
    # task is still running after _TOUCH_READY_FALLBACK_S, show the overlay
    # as a safety net (e.g. if ykman unexpectedly blocks for touch).
    fallback_deadline = (
        time.monotonic() + _TOUCH_READY_FALLBACK_S
        if ready_event is None else None
    )
    while not result_holder["done"]:
        if (
            overlay is None
            and fallback_deadline is not None
            and time.monotonic() >= fallback_deadline
        ):
            logger.debug("No ready_event; task still running after fallback — showing overlay")
            overlay = _show_touch_overlay()
        if _tk_root is not None:
            _tk_root.update()
        time.sleep(0.05)

    # Clean up overlay
    if overlay is not None:
        try:
            overlay.destroy()
        except tk.TclError:
            pass

    if result_holder["error"] is not None:
        raise result_holder["error"]

    return result_holder["value"]


# --- Account resolution ---

def _resolve_account(accounts: list[tuple[str, str]]) -> Optional[int]:
    """Determine which account to use. Returns index or None if cancelled.

    Matching priority for default_account: exact > prefix > substring.
    Falls through to selector popup if no match or multiple matches.
    """
    if CONFIG.default_account:
        target = CONFIG.default_account.lower()

        # Exact match
        for i, (name, _) in enumerate(accounts):
            if name.lower() == target:
                logger.info("Exact match for default account: %s", name)
                return i

        # Prefix match
        for i, (name, _) in enumerate(accounts):
            if name.lower().startswith(target):
                logger.info("Prefix match for default account: %s", name)
                return i

        # Substring match (only if unambiguous)
        matches = [(i, name) for i, (name, _) in enumerate(accounts) if target in name.lower()]
        if len(matches) == 1:
            logger.info("Substring match for default account: %s", matches[0][1])
            return matches[0][0]
        elif len(matches) > 1:
            logger.warning(
                "Multiple accounts match '%s': %s — showing selector",
                CONFIG.default_account,
                [m[1] for m in matches],
            )

    # Single account — use it directly
    if len(accounts) == 1:
        return 0

    # Multiple accounts — show selector popup
    return show_account_selector(accounts, parent=_tk_root)


# --- Main trigger handler ---

def _handle_hotkey_trigger(force_selector: bool = False) -> None:
    """Called on the main thread when a hotkey event is received.
    Orchestrates: fetch codes -> select account -> type code.
    """
    # Instant visual feedback — animated cursor runs in parallel
    trigger_cursor_feedback()

    # Capture the active window title BEFORE any UI appears
    window_title = None
    if CONFIG.domain_auto_detect and not force_selector:
        try:
            from domain_detect import get_active_window_title
            window_title = get_active_window_title()
        except Exception:
            pass

    # 1. Fetch all TOTP codes from YubiKey (background thread keeps tkinter
    #    responsive).  A ready_event lets fetch_totp_codes() signal
    #    immediately when ykman is waiting for a physical touch — this is
    #    critical for single-credential keys where CALCULATE ALL blocks
    #    inline instead of returning [Requires Touch].
    touch_ready = threading.Event()
    try:
        accounts = _run_with_touch_overlay(
            lambda: fetch_totp_codes(ready_event=touch_ready),
            ready_event=touch_ready,
        )
    except YubiKeyError as e:
        _show_notification(str(e))
        return

    # 2. Prepare display list for selector (replace None with display text)
    display_accounts: list[tuple[str, str]] = [
        (name, code if code is not None else "Touch required")
        for name, code in accounts
    ]

    # 3. Domain auto-detect (if enabled and not forcing selector)
    selected_idx = None
    if window_title and not force_selector and len(accounts) > 1:
        try:
            from domain_detect import match_account_to_window
            selected_idx = match_account_to_window(accounts, window_title)
        except Exception:
            pass

    # 4. Fall through to normal resolution if no auto-detect match
    if selected_idx is None:
        if force_selector and len(accounts) > 1:
            # Force selector — bypass default_account matching
            selected_idx = show_account_selector(display_accounts, parent=_tk_root)
        else:
            selected_idx = _resolve_account(display_accounts)

    if selected_idx is None:
        logger.debug("Account selection cancelled")
        return

    # 5. Get the code — either already fetched or needs touch
    account_name, code_str = accounts[selected_idx]
    if code_str is None:
        # Touch-required: fetch code with overlay deferred until ykman is
        # actually ready for touch (so touching too early doesn't get lost).
        logger.info("Waiting for touch on %s...", account_name)
        try:
            touch_ready = threading.Event()
            code_str = _run_with_touch_overlay(
                lambda: fetch_code_for_account(account_name, ready_event=touch_ready),
                ready_event=touch_ready,
            )
        except YubiKeyError as e:
            _show_notification(str(e))
            return

    # 6. Type the code into the focused input field
    type_code(code_str, delay_ms=CONFIG.type_delay_ms, auto_submit=CONFIG.auto_submit)


# --- Settings ---

def _open_settings_window() -> None:
    """Open the settings window (or bring existing one to front)."""
    global _settings_window

    # Guard against duplicate windows
    if _settings_window is not None:
        try:
            if _settings_window.is_open():
                _settings_window.win.lift()
                _settings_window.win.focus_force()
                return
        except Exception:
            pass

    from settings import SettingsWindow
    startup_enabled = _check_startup_shortcut_exists()
    _settings_window = SettingsWindow(
        parent=_tk_root,
        current_config=CONFIG,
        on_save=_apply_new_config,
        startup_enabled=startup_enabled,
    )


def _apply_new_config(new_config: AppConfig, enable_startup: bool) -> None:
    """Apply new configuration from the settings window."""
    global _hotkey_id, _selector_hotkey_id, _settings_window, CONFIG
    _settings_window = None

    # Re-register primary hotkey if changed
    if new_config.hotkey != CONFIG.hotkey:
        try:
            if _hotkey_id is not None:
                keyboard.remove_hotkey(_hotkey_id)
        except Exception:
            pass
        _hotkey_id = keyboard.add_hotkey(new_config.hotkey, _on_hotkey_pressed)
        logger.info("Primary hotkey changed to: %s", new_config.hotkey)

    # Re-register selector hotkey if changed
    if new_config.selector_hotkey != CONFIG.selector_hotkey:
        try:
            if _selector_hotkey_id is not None:
                keyboard.remove_hotkey(_selector_hotkey_id)
                _selector_hotkey_id = None
        except Exception:
            pass
        if new_config.selector_hotkey:
            _selector_hotkey_id = keyboard.add_hotkey(
                new_config.selector_hotkey, _on_selector_hotkey_pressed
            )
            logger.info("Selector hotkey set to: %s", new_config.selector_hotkey)
        else:
            logger.info("Selector hotkey cleared")

    # Handle startup shortcut
    if enable_startup and not _check_startup_shortcut_exists():
        _create_startup_shortcut()
    elif not enable_startup and _check_startup_shortcut_exists():
        _remove_startup_shortcut()

    # Save and apply
    update_config(new_config)
    CONFIG = new_config  # Keep local module reference in sync
    if save_config(new_config):
        _show_notification("Settings saved", title="InterYubi")
    else:
        _show_notification(
            "Settings applied but could not save to disk.\n"
            "Changes will be lost on restart.",
            title="InterYubi - Warning",
        )


# --- System tray ---

def _create_tray_icon() -> Image.Image:
    """Create a small green circle icon with a white "Y" for the system tray."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill="#22c55e")
    draw.text((22, 14), "Y", fill="white")
    return img


def _on_tray_settings(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    """Called when the user clicks Settings in the tray menu."""
    _trigger_queue.put("open_settings")


def _on_tray_exit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    """Called when the user clicks Exit in the tray menu."""
    icon.stop()
    _shutdown_event.set()
    # Unblock the tkinter mainloop from the tray thread
    if _tk_root:
        try:
            _tk_root.after(0, _tk_root.quit)
        except Exception:
            pass


def _start_tray() -> None:
    """Start the system tray icon (runs in a background thread)."""
    global _tray_icon
    menu = pystray.Menu(
        pystray.MenuItem(
            lambda item: f"Hotkey: {CONFIG.hotkey}",
            None,
            enabled=False,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Settings", _on_tray_settings),
        pystray.MenuItem("Exit", _on_tray_exit),
    )
    _tray_icon = pystray.Icon(
        "interyubi",
        _create_tray_icon(),
        "InterYubi",
        menu,
    )
    _tray_icon.run()


# --- Startup diagnostics ---

def _startup_checks() -> None:
    """Run startup diagnostics and log status."""
    logger.info("=" * 50)
    logger.info("InterYubi")
    logger.info("=" * 50)

    # Check ykman
    ok, msg = check_ykman_available()
    if ok:
        logger.info("[OK] ykman found: %s", msg)
    else:
        logger.error("[!!] ykman: %s", msg)

    # Check for Yubico Authenticator conflict
    auth_running, auth_procs = check_authenticator_running()
    if auth_running:
        logger.warning(
            "[!!] Yubico Authenticator is running (%s) — "
            "it may intermittently lock the YubiKey and block TOTP reads. "
            "Close it if you experience timeouts.",
            ", ".join(auth_procs),
        )
    else:
        logger.info("[OK] No Yubico Authenticator conflict detected")

    # Check YubiKey presence (non-fatal — user might plug it in later)
    # Uses list_totp_accounts() instead of fetch_totp_codes() to avoid
    # blocking on touch-required accounts at startup.
    try:
        account_names = list_totp_accounts()
        logger.info("[OK] YubiKey detected — %d TOTP account(s)", len(account_names))
        for name in account_names:
            logger.info("     - %s", name)
    except YubiKeyError as e:
        logger.warning("[--] YubiKey: %s (will retry on hotkey press)", e)

    # Config summary
    logger.info("[OK] Hotkey: %s", CONFIG.hotkey)
    if CONFIG.selector_hotkey:
        logger.info("[OK] Selector hotkey: %s", CONFIG.selector_hotkey)
    if CONFIG.default_account:
        logger.info("[OK] Default account: %s", CONFIG.default_account)
    if CONFIG.auto_submit:
        logger.info("[OK] Auto-submit: enabled")
    if CONFIG.domain_auto_detect:
        logger.info("[OK] Domain auto-detect: enabled")

    logger.info("=" * 50)
    logger.info("Ready. Press %s to fetch a TOTP code.", CONFIG.hotkey)
    logger.info("Right-click the tray icon to open Settings or exit.")
    logger.info("")


# --- Main event loop (tkinter-based) ---

def _poll_queue() -> None:
    """Poll the trigger queue and process messages. Scheduled via root.after()."""
    if _shutdown_event.is_set():
        if _tk_root:
            _tk_root.quit()
        return

    try:
        while True:
            msg = _trigger_queue.get_nowait()
            if msg == "trigger":
                _handle_hotkey_trigger()
            elif msg == "trigger_selector":
                _handle_hotkey_trigger(force_selector=True)
            elif msg == "open_settings":
                _open_settings_window()
    except queue.Empty:
        pass

    if _tk_root:
        _tk_root.after(100, _poll_queue)


def main() -> None:
    global _tk_root, _hotkey_id, _selector_hotkey_id

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    _startup_checks()

    # Clean up legacy startup shortcut from old name
    _cleanup_legacy_shortcut()

    # Create hidden tkinter root for all UI windows (stays invisible)
    _tk_root = tk.Tk()
    _tk_root.withdraw()

    # Register global hotkeys
    _hotkey_id = keyboard.add_hotkey(CONFIG.hotkey, _on_hotkey_pressed)
    if CONFIG.selector_hotkey:
        _selector_hotkey_id = keyboard.add_hotkey(
            CONFIG.selector_hotkey, _on_selector_hotkey_pressed
        )

    # Run tray icon in a background thread
    tray_thread = threading.Thread(target=_start_tray, daemon=True)
    tray_thread.start()

    # Start polling the queue via tkinter's event loop
    _tk_root.after(100, _poll_queue)

    try:
        _tk_root.mainloop()
    except KeyboardInterrupt:
        pass

    logger.info("Shutting down...")
    keyboard.unhook_all()
    if _tray_icon and _tray_icon.visible:
        try:
            _tray_icon.stop()
        except Exception:
            pass
    sys.exit(0)


def _relaunch_hidden() -> None:
    """If running under python.exe (console attached), re-launch under pythonw.exe
    so the process is fully detached from the terminal. The original process then exits."""
    import shutil
    import subprocess as sp

    exe = sys.executable
    # Already running under pythonw — nothing to do
    if "pythonw" in os.path.basename(exe).lower():
        return

    pythonw = shutil.which("pythonw")
    if pythonw is None:
        # Try next to the current python.exe
        candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(candidate):
            pythonw = candidate

    if pythonw is None:
        # Can't find pythonw — just keep running with the console
        return

    # Re-launch detached: CREATE_NO_WINDOW + DETACHED_PROCESS on Windows
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    script = os.path.abspath(__file__)
    sp.Popen(
        [pythonw, script] + sys.argv[1:],
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
        close_fds=True,
    )
    sys.exit(0)


if __name__ == "__main__":
    _relaunch_hidden()
    main()
