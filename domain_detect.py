"""Active window domain detection for auto-matching TOTP accounts."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def get_active_window_title() -> Optional[str]:
    """Get the title of the currently focused window using Win32 API."""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return None

    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return None

    buffer = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


# Common issuer-to-domain aliases for better matching
_DOMAIN_ALIASES: dict[str, list[str]] = {
    "google": ["google.com", "accounts.google", "gmail"],
    "microsoft": ["microsoft.com", "live.com", "outlook.com", "login.microsoftonline"],
    "github": ["github.com"],
    "amazon": ["amazon.com", "aws.amazon"],
    "facebook": ["facebook.com", "meta.com"],
    "twitter": ["twitter.com", "x.com"],
    "discord": ["discord.com"],
    "slack": ["slack.com"],
    "dropbox": ["dropbox.com"],
    "steam": ["steampowered.com", "steamcommunity.com"],
    "apple": ["apple.com", "icloud.com"],
    "linkedin": ["linkedin.com"],
    "reddit": ["reddit.com"],
    "twitch": ["twitch.tv"],
    "paypal": ["paypal.com"],
    "cloudflare": ["cloudflare.com", "dash.cloudflare"],
    "digitalocean": ["digitalocean.com", "cloud.digitalocean"],
    "gitlab": ["gitlab.com"],
    "bitbucket": ["bitbucket.org"],
    "npm": ["npmjs.com"],
    "pypi": ["pypi.org"],
}


_BROWSER_SUFFIXES = [
    " - Google Chrome",
    " - Mozilla Firefox",
    " - Microsoft Edge",
    " - Brave",
    " - Opera",
    " - Vivaldi",
    " - Arc",
    " - Chromium",
    " - Waterfox",
]


def _extract_domain_hints(window_title: str) -> list[str]:
    """Extract potential domain/service names from a browser window title.

    Browser titles are typically: "Page Title - Site Name - Browser Name"
    """
    clean = window_title
    for suffix in _BROWSER_SUFFIXES:
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)]
            break

    # Split on common delimiters and collect hints
    parts = re.split(r"\s[-|]\s", clean)
    hints = []
    for part in parts:
        part = part.strip().lower()
        if part:
            hints.append(part)

    return hints


def match_account_to_window(
    accounts: list[tuple[str, Optional[str]]],
    window_title: str,
) -> Optional[int]:
    """Try to match a TOTP account to the active window.

    Returns the index of the matching account, or None if no unique match.
    Only returns a match when exactly one account matches (conservative).
    """
    if not window_title:
        return None

    hints = _extract_domain_hints(window_title)
    title_lower = window_title.lower()

    matches: list[int] = []

    for i, (account_name, _) in enumerate(accounts):
        # Extract issuer from "Issuer:Account" format
        if ":" in account_name:
            issuer = account_name.split(":")[0].strip().lower()
        else:
            issuer = account_name.strip().lower()

        # Direct issuer match in title
        if issuer in title_lower:
            matches.append(i)
            continue

        # Check alias mapping
        matched_alias = False
        for alias_key, alias_domains in _DOMAIN_ALIASES.items():
            if issuer == alias_key or issuer.startswith(alias_key):
                if any(domain in title_lower for domain in alias_domains):
                    matches.append(i)
                    matched_alias = True
                    break
        if matched_alias:
            continue

        # Check if any hint contains the issuer or vice versa
        for hint in hints:
            if issuer in hint or hint in issuer:
                matches.append(i)
                break

    # Only return if exactly one match (unambiguous)
    if len(matches) == 1:
        logger.info(
            "Domain auto-detect matched account '%s' from window title '%s'",
            accounts[matches[0]][0],
            window_title,
        )
        return matches[0]

    if len(matches) > 1:
        logger.info(
            "Domain auto-detect found %d matches, falling through to selector",
            len(matches),
        )

    return None
