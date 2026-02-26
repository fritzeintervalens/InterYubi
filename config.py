from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# --- Named constants (replace magic numbers project-wide) ---

YKMAN_TIMEOUT_S: int = 10
TOUCH_TIMEOUT_S: int = 15
HOTKEY_DEBOUNCE_S: float = 2.0
FOCUS_SETTLE_DELAY_S: float = 0.2
SUBMIT_DELAY_S: float = 0.05
QUEUE_POLL_TIMEOUT_S: float = 0.5
TOTP_PERIOD_S: int = 30

# --- Config file location (next to this script) ---

_CONFIG_DIR = Path(__file__).parent
CONFIG_FILE = _CONFIG_DIR / "config.json"


@dataclass
class AppConfig:
    """Application configuration with sensible defaults."""

    hotkey: str = "ctrl+alt+x"
    selector_hotkey: Optional[str] = None
    default_account: Optional[str] = None
    type_delay_ms: int = 50
    auto_submit: bool = False
    ykman_path: Optional[str] = None
    oath_password: Optional[str] = None
    domain_auto_detect: bool = True

    def validate(self) -> list[str]:
        """Validate config values. Returns list of warnings (empty = all good).
        Corrects invalid values in-place where possible."""
        warnings: list[str] = []

        if self.type_delay_ms < 0:
            warnings.append(f"type_delay_ms={self.type_delay_ms} is negative, clamping to 0")
            self.type_delay_ms = 0
        if self.type_delay_ms > 500:
            warnings.append(f"type_delay_ms={self.type_delay_ms}ms is very high — typing will be slow")

        if self.ykman_path and not Path(self.ykman_path).is_file():
            warnings.append(f"ykman_path '{self.ykman_path}' does not exist, will auto-detect")
            self.ykman_path = None

        return warnings


def _try_load_json(path: Path) -> Optional[dict]:
    """Attempt to load and parse a JSON file. Returns None on any failure."""
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        logger.warning("Config file %s does not contain a JSON object", path)
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read %s: %s", path, e)
        return None


def load_config() -> AppConfig:
    """Load config from config.json if it exists, otherwise use defaults.

    If config.json is missing or corrupted, attempts recovery from config.json.bak.
    """
    config_data = _try_load_json(CONFIG_FILE)
    if config_data is None:
        backup_path = CONFIG_FILE.with_suffix(".json.bak")
        config_data = _try_load_json(backup_path)
        if config_data is not None:
            logger.warning("Recovered config from backup: %s", backup_path)
        else:
            return AppConfig()

    # Only accept known fields, warn about unknown ones
    known_fields = {f.name for f in fields(AppConfig)}
    unknown = set(config_data.keys()) - known_fields
    if unknown:
        logger.warning("Unknown config keys ignored: %s", ", ".join(sorted(unknown)))

    filtered = {k: v for k, v in config_data.items() if k in known_fields}
    config = AppConfig(**filtered)

    for warning in config.validate():
        logger.warning("Config: %s", warning)

    return config


def save_config(config: AppConfig) -> bool:
    """Save config to config.json using atomic write.

    Writes to a temporary file first, then atomically replaces the target.
    This prevents corruption if the process crashes mid-write.

    Returns True if save succeeded, False if it failed.
    """
    data = {f.name: getattr(config, f.name) for f in fields(AppConfig)}

    try:
        # Write to a temp file in the same directory (same filesystem = atomic rename)
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp", prefix="config_", dir=str(_CONFIG_DIR),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        # Back up existing config before replacing
        if CONFIG_FILE.is_file():
            backup_path = CONFIG_FILE.with_suffix(".json.bak")
            try:
                shutil.copy2(CONFIG_FILE, backup_path)
            except OSError as e:
                logger.debug("Could not create config backup: %s", e)

        # Atomic replace (os.replace is atomic on NTFS for same-volume renames)
        os.replace(tmp_path, str(CONFIG_FILE))
        logger.info("Config saved to %s", CONFIG_FILE)
        return True

    except Exception as e:
        logger.error("Failed to save config: %s", e)
        return False


def update_config(new_config: AppConfig) -> None:
    """Update the global CONFIG singleton."""
    global CONFIG
    CONFIG = new_config


# Module-level config instance — import this from other modules
CONFIG: AppConfig = load_config()
