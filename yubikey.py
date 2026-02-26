from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
from typing import Optional

from config import CONFIG, YKMAN_TIMEOUT_S, TOUCH_TIMEOUT_S

logger = logging.getLogger(__name__)

# Prevent console window flash when spawning subprocesses on Windows
_CREATE_NO_WINDOW = 0x08000000


class YubiKeyError(Exception):
    """Custom exception for YubiKey-related errors."""


# Known install locations for ykman on Windows
_YKMAN_SEARCH_PATHS = [
    r"C:\Program Files\Yubico\YubiKey Manager CLI\ykman.exe",
    r"C:\Program Files (x86)\Yubico\YubiKey Manager CLI\ykman.exe",
    r"C:\Program Files\Yubico\YubiKey Manager\ykman.exe",
]

# Yubico Authenticator process names (covers Store, desktop, and legacy installs)
_AUTHENTICATOR_PROCESS_NAMES = frozenset({
    "authenticator.exe",
    "authenticator-helper.exe",
    "yubico-authenticator.exe",
})


def _find_ykman() -> str:
    """Find the ykman executable. Checks config, PATH, then known install locations."""
    # Check config first
    if CONFIG.ykman_path:
        logger.debug("Using configured ykman_path: %s", CONFIG.ykman_path)
        return CONFIG.ykman_path

    # Check PATH
    found = shutil.which("ykman")
    if found:
        logger.debug("Found ykman on PATH: %s", found)
        return found

    # Check known install locations
    for path in _YKMAN_SEARCH_PATHS:
        if os.path.isfile(path):
            logger.debug("Found ykman at known location: %s", path)
            return path

    raise YubiKeyError(
        "ykman CLI not found. Please install it:\n"
        "  - winget install Yubico.YubiKeyManagerCLI\n"
        "  - Or download from https://developers.yubico.com/yubikey-manager/"
    )


def _run_ykman(*args: str) -> str:
    """Run an ykman command and return stdout."""
    ykman = _find_ykman()
    cmd = [ykman] + list(args)
    logger.debug("Running: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=YKMAN_TIMEOUT_S,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        auth_running, auth_procs = check_authenticator_running()
        if auth_running:
            raise YubiKeyError(
                f"ykman timed out — Yubico Authenticator is running "
                f"({', '.join(auth_procs)}) and may be locking the YubiKey.\n"
                "  - Close Yubico Authenticator, then try again\n"
                "  - The helper process (authenticator-helper.exe) may persist\n"
                "    after closing the app — check Task Manager if the issue continues"
            )
        raise YubiKeyError(
            f"ykman timed out after {YKMAN_TIMEOUT_S}s. Try:\n"
            "  - Unplug and re-insert your YubiKey\n"
            "  - Close Yubico Authenticator if it's open"
        )
    except FileNotFoundError:
        raise YubiKeyError(f"ykman executable not found at: {ykman}")

    if result.returncode != 0:
        stderr = result.stderr.strip().lower()
        if "no yubikey" in stderr or "failed connecting" in stderr:
            auth_running, auth_procs = check_authenticator_running()
            if auth_running:
                raise YubiKeyError(
                    f"Cannot connect to YubiKey — Yubico Authenticator is running "
                    f"({', '.join(auth_procs)}) and may be locking the YubiKey.\n"
                    "  - Close Yubico Authenticator, then try again\n"
                    "  - The helper process may linger — check Task Manager"
                )
            raise YubiKeyError(
                "No YubiKey detected. Please check:\n"
                "  - Is your YubiKey plugged in?\n"
                "  - Try unplugging and re-inserting the key"
            )
        raise YubiKeyError(f"ykman error: {result.stderr.strip()}")

    return result.stdout


def fetch_totp_codes() -> list[tuple[str, Optional[str]]]:
    """Fetch all TOTP codes from the connected YubiKey.

    Returns:
        List of (account_name, code_or_none) tuples.
        code is None for accounts that require touch.

    Raises:
        YubiKeyError: If no YubiKey is detected, ykman fails, or no accounts found.
    """
    # Build command args, include OATH password if configured
    args = ["oath", "accounts", "code"]
    if CONFIG.oath_password:
        args.extend(["-p", CONFIG.oath_password])

    output = _run_ykman(*args)

    results: list[tuple[str, Optional[str]]] = []
    for line in output.strip().splitlines():
        # ykman output: "Issuer:Account  123456" or "Account  [Requires Touch]"
        code_match = re.match(r"^(.+?)\s{2,}(\d{6,8})\s*$", line)
        if code_match:
            results.append((code_match.group(1).strip(), code_match.group(2)))
            continue
        touch_match = re.match(r"^(.+?)\s{2,}\[Requires Touch\]\s*$", line)
        if touch_match:
            results.append((touch_match.group(1).strip(), None))

    if not results:
        raise YubiKeyError(
            "No TOTP accounts found on the YubiKey.\n"
            "Add accounts using Yubico Authenticator first."
        )

    touch_count = sum(1 for _, code in results if code is None)
    logger.debug("Fetched %d TOTP account(s) (%d require touch)", len(results), touch_count)
    return results


def list_totp_accounts() -> list[str]:
    """List all OATH account names on the YubiKey without computing codes.

    Unlike fetch_totp_codes(), this never blocks waiting for touch because
    it uses ``ykman oath accounts list`` instead of ``ykman oath accounts code``.

    Returns:
        List of account name strings.

    Raises:
        YubiKeyError: If no YubiKey is detected, ykman fails, or no accounts found.
    """
    output = _run_ykman("oath", "accounts", "list")

    results: list[str] = []
    for line in output.strip().splitlines():
        name = line.strip()
        if name:
            results.append(name)

    if not results:
        raise YubiKeyError(
            "No TOTP accounts found on the YubiKey.\n"
            "Add accounts using Yubico Authenticator first."
        )

    logger.debug("Listed %d OATH account(s)", len(results))
    return results


def fetch_code_for_account(
    account_name: str,
    ready_event: Optional[threading.Event] = None,
) -> str:
    """Fetch a TOTP code for a specific account (handles touch-required accounts).

    If *ready_event* is provided it is set as soon as ykman signals that it
    is ready for touch (by printing its "Touch your YubiKey..." prompt to
    stderr).  This lets the caller delay showing a touch-prompt UI until the
    hardware is actually waiting.

    Uses a longer timeout to allow time for the user to touch the YubiKey.

    Returns:
        The TOTP code string.

    Raises:
        YubiKeyError: If the fetch fails or times out.
    """
    ykman = _find_ykman()
    args = ["oath", "accounts", "code", account_name]
    if CONFIG.oath_password:
        args.extend(["-p", CONFIG.oath_password])

    cmd = [ykman] + args
    logger.debug("Fetching code for %s (touch timeout: %ds)", account_name, TOUCH_TIMEOUT_S)

    # PYTHONUNBUFFERED=1 forces ykman (a Python CLI) to flush stderr
    # immediately so we see the touch prompt without waiting for the
    # process to exit.
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=_CREATE_NO_WINDOW,
            env=env,
        )
    except FileNotFoundError:
        raise YubiKeyError(f"ykman executable not found at: {ykman}")

    # Drain stderr in a background thread.  When the "touch" prompt
    # appears we know ykman has sent the OATH challenge and the YubiKey
    # is physically waiting — only then should the UI prompt the user.
    stderr_lines: list[str] = []

    def _read_stderr() -> None:
        try:
            for line in proc.stderr:
                stderr_lines.append(line)
                if ready_event is not None and "touch" in line.lower():
                    ready_event.set()
        except (ValueError, OSError):
            pass  # pipe closed

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stderr_thread.start()

    # Drain stdout in a separate thread to avoid pipe deadlocks.
    stdout_chunks: list[str] = []

    def _read_stdout() -> None:
        try:
            data = proc.stdout.read()
            if data:
                stdout_chunks.append(data)
        except (ValueError, OSError):
            pass

    stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
    stdout_thread.start()

    # Wait for the process to finish — this is the timeout boundary.
    try:
        proc.wait(timeout=TOUCH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise YubiKeyError(
            f"Timed out waiting for touch ({TOUCH_TIMEOUT_S}s).\n"
            "  - Make sure to touch your YubiKey when prompted"
        )

    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)

    # Safety net: always signal ready once the process has exited so
    # the caller never blocks indefinitely waiting for the event.
    if ready_event is not None:
        ready_event.set()

    if proc.returncode != 0:
        stderr_text = "".join(stderr_lines).strip()
        raise YubiKeyError(f"ykman error: {stderr_text or '(no error output)'}")

    # Parse the code from output
    stdout = "".join(stdout_chunks)
    for line in stdout.strip().splitlines():
        match = re.match(r"^(.+?)\s{2,}(\d{6,8})\s*$", line)
        if match:
            return match.group(2)

    raise YubiKeyError(f"Could not parse TOTP code for {account_name}")


def check_ykman_available() -> tuple[bool, str]:
    """Check if ykman is installed and reachable. For startup diagnostics.

    Returns:
        (ok, message) — ok is True if ykman was found, message has the path or error.
    """
    try:
        path = _find_ykman()
        return True, path
    except YubiKeyError as e:
        return False, str(e)


def check_authenticator_running() -> tuple[bool, list[str]]:
    """Check if Yubico Authenticator is running (it may intermittently lock the YubiKey).

    Returns:
        (is_running, process_names) — is_running is True if any authenticator
        process was found; process_names lists which ones were detected.
    """
    try:
        result = subprocess.run(
            ["tasklist.exe", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.debug("Could not run tasklist.exe: %s", exc)
        return False, []

    found: list[str] = []
    for line in result.stdout.strip().splitlines():
        line_lower = line.lower()
        for proc_name in _AUTHENTICATOR_PROCESS_NAMES:
            if proc_name in line_lower:
                found.append(proc_name)
                break

    unique = sorted(set(found))
    return len(unique) > 0, unique


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # Check for authenticator conflict
    auth_running, auth_procs = check_authenticator_running()
    if auth_running:
        print(f"WARNING: Yubico Authenticator is running: {', '.join(auth_procs)}")
    else:
        print("OK: No Yubico Authenticator conflict")

    try:
        accounts = fetch_totp_codes()
        print(f"Found {len(accounts)} TOTP account(s):\n")
        for name, code in accounts:
            if code is None:
                print(f"  {name}: [Requires Touch]")
            else:
                print(f"  {name}: {code}")
    except YubiKeyError as e:
        print(f"Error: {e}")
