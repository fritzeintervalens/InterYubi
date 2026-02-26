from __future__ import annotations

import logging
import time

from pynput.keyboard import Controller, Key

from config import FOCUS_SETTLE_DELAY_S, SUBMIT_DELAY_S

logger = logging.getLogger(__name__)


def type_code(code: str, delay_ms: int = 50, auto_submit: bool = False) -> None:
    """Type a TOTP code character by character into the currently focused input field.

    Args:
        code: The string to type (e.g., "482937").
        delay_ms: Milliseconds to wait between each keystroke.
        auto_submit: If True, press Enter after typing the code.
    """
    controller = Controller()

    # Wait for focus to settle back to the browser after popup closes
    time.sleep(FOCUS_SETTLE_DELAY_S)

    logger.info("Typing %d-character code", len(code))
    for char in code:
        controller.press(char)
        controller.release(char)
        time.sleep(delay_ms / 1000)

    if auto_submit:
        time.sleep(SUBMIT_DELAY_S)
        controller.press(Key.enter)
        controller.release(Key.enter)
        logger.debug("Pressed Enter (auto_submit)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("You have 3 seconds to click on an input field...")
    time.sleep(3)
    type_code("123456", delay_ms=50, auto_submit=False)
    print("Done!")
