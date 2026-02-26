from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
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


def fetch_code_for_account(account_name: str) -> str:
    """Fetch a TOTP code for a specific account (handles touch-required accounts).

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

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TOUCH_TIMEOUT_S,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        raise YubiKeyError(
            f"Timed out waiting for touch ({TOUCH_TIMEOUT_S}s).\n"
            "  - Make sure to touch your YubiKey when prompted"
        )
    except FileNotFoundError:
        raise YubiKeyError(f"ykman executable not found at: {ykman}")

    if result.returncode != 0:
        raise YubiKeyError(f"ykman error: {result.stderr.strip()}")

    # Parse the code from output
    for line in result.stdout.strip().splitlines():
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
