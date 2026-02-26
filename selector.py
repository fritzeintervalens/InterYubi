from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time
import tkinter as tk
from typing import Optional

from config import TOTP_PERIOD_S
from theme import (
    BG_COLOR,
    CODE_COLOR,
    COUNTDOWN_GREEN,
    COUNTDOWN_RED,
    COUNTDOWN_YELLOW,
    HIGHLIGHT_BG,
    ITEM_BG,
    SUBTEXT_COLOR,
    TEXT_COLOR,
    TITLE_BG,
)

logger = logging.getLogger(__name__)


def get_monitor_work_area(x: int, y: int) -> Optional[tuple[int, int, int, int]]:
    """Get the work area (excluding taskbar) of the monitor containing point (x, y).

    Returns (left, top, right, bottom) of the monitor work area,
    or None if the Win32 API call fails.
    """
    try:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.wintypes.LONG), ("y", ctypes.wintypes.LONG)]

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.wintypes.LONG),
                ("top", ctypes.wintypes.LONG),
                ("right", ctypes.wintypes.LONG),
                ("bottom", ctypes.wintypes.LONG),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", ctypes.wintypes.DWORD),
            ]

        MONITOR_DEFAULTTONEAREST = 2
        point = POINT(x, y)
        h_monitor = ctypes.windll.user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
        if not h_monitor:
            return None

        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        success = ctypes.windll.user32.GetMonitorInfoW(h_monitor, ctypes.byref(info))
        if not success:
            return None

        rc = info.rcWork
        return (rc.left, rc.top, rc.right, rc.bottom)

    except Exception:
        return None


class AccountSelector:
    """Dark-themed TOTP account selector with keyboard navigation and countdown."""

    def __init__(self, accounts: list[tuple[str, str]], parent: Optional[tk.Tk] = None) -> None:
        self.accounts = accounts
        self.selected: Optional[int] = None
        self.highlighted: int = 0
        self._use_toplevel = parent is not None

        if parent is not None:
            self.root = tk.Toplevel(parent)
        else:
            self.root = tk.Tk()

        self.item_frames: list[tk.Frame] = []
        self._build_ui()
        self._bind_keys()
        self._update_countdown()

    def _build_ui(self) -> None:
        self.root.title("InterYubi")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG_COLOR)

        # --- Title bar ---
        title_frame = tk.Frame(self.root, bg=TITLE_BG, padx=12, pady=8)
        title_frame.pack(fill="x")

        tk.Label(
            title_frame,
            text="Select TOTP Account",
            font=("Segoe UI", 10, "bold"),
            fg=TEXT_COLOR,
            bg=TITLE_BG,
        ).pack(side="left")

        tk.Label(
            title_frame,
            text="ESC to cancel",
            font=("Segoe UI", 8),
            fg=SUBTEXT_COLOR,
            bg=TITLE_BG,
        ).pack(side="right")

        # --- Account items ---
        items_frame = tk.Frame(self.root, bg=BG_COLOR, padx=6, pady=4)
        items_frame.pack(fill="both", expand=True)

        for i, (name, code) in enumerate(self.accounts):
            frame = self._create_item(items_frame, i, name, code)
            self.item_frames.append(frame)

        # --- Countdown bar ---
        self.countdown_canvas = tk.Canvas(
            self.root, height=4, bg=BG_COLOR, highlightthickness=0,
        )
        self.countdown_canvas.pack(fill="x", padx=10, pady=(4, 10))

        # --- Position near cursor (multi-monitor aware) ---
        self.root.update_idletasks()
        win_width = self.root.winfo_reqwidth()
        win_height = self.root.winfo_reqheight()

        mouse_x = self.root.winfo_pointerx()
        mouse_y = self.root.winfo_pointery()

        x = mouse_x - 20
        y = mouse_y - 20

        # Get the work area of the monitor where the mouse is
        work_area = get_monitor_work_area(mouse_x, mouse_y)
        if work_area is not None:
            mon_left, mon_top, mon_right, mon_bottom = work_area
        else:
            mon_left, mon_top = 0, 0
            mon_right = self.root.winfo_screenwidth()
            mon_bottom = self.root.winfo_screenheight()

        # Keep on screen (within the correct monitor)
        if x + win_width > mon_right:
            x = mon_right - win_width - 10
        if y + win_height > mon_bottom:
            y = mon_bottom - win_height - 10
        if x < mon_left:
            x = mon_left + 10
        if y < mon_top:
            y = mon_top + 10

        self.root.geometry(f"+{x}+{y}")
        self._update_highlight()

    def _create_item(self, parent: tk.Frame, index: int, name: str, code: str) -> tk.Frame:
        """Create a single account row."""
        frame = tk.Frame(parent, bg=ITEM_BG, cursor="hand2", padx=10, pady=8)
        frame.pack(fill="x", pady=2)

        # Number hint
        num_label = tk.Label(
            frame,
            text=f"{index + 1}.",
            font=("Consolas", 10),
            fg=SUBTEXT_COLOR,
            bg=ITEM_BG,
            width=2,
            anchor="e",
        )
        num_label.pack(side="left", padx=(0, 6))

        # Account name
        name_label = tk.Label(
            frame,
            text=name,
            font=("Segoe UI", 10),
            fg=TEXT_COLOR,
            bg=ITEM_BG,
            anchor="w",
        )
        name_label.pack(side="left", fill="x", expand=True)

        # TOTP code
        code_label = tk.Label(
            frame,
            text=code,
            font=("Consolas", 12, "bold"),
            fg=CODE_COLOR,
            bg=ITEM_BG,
        )
        code_label.pack(side="right", padx=(10, 0))

        # Click binding on all child widgets
        for widget in (frame, num_label, name_label, code_label):
            widget.bind("<Button-1>", lambda e, idx=index: self._confirm(idx))
            widget.bind("<Enter>", lambda e, idx=index: self._set_highlight(idx))

        return frame

    def _bind_keys(self) -> None:
        """Bind keyboard shortcuts."""
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<Return>", lambda e: self._confirm(self.highlighted))
        self.root.bind("<Up>", lambda e: self._move_highlight(-1))
        self.root.bind("<Down>", lambda e: self._move_highlight(1))

        # Number keys 1-9 for quick select
        for i in range(min(9, len(self.accounts))):
            self.root.bind(str(i + 1), lambda e, idx=i: self._confirm(idx))

    def _move_highlight(self, delta: int) -> None:
        self.highlighted = (self.highlighted + delta) % len(self.accounts)
        self._update_highlight()

    def _set_highlight(self, index: int) -> None:
        self.highlighted = index
        self._update_highlight()

    def _update_highlight(self) -> None:
        """Update visual highlight on all items."""
        for i, frame in enumerate(self.item_frames):
            bg = HIGHLIGHT_BG if i == self.highlighted else ITEM_BG
            frame.configure(bg=bg)
            for child in frame.winfo_children():
                child.configure(bg=bg)

    def _confirm(self, index: int) -> None:
        self.selected = index
        logger.info("Selected account %d: %s", index, self.accounts[index][0])
        self.root.destroy()

    def _update_countdown(self) -> None:
        """Update the TOTP countdown bar. Schedules itself every second."""
        remaining = TOTP_PERIOD_S - (int(time.time()) % TOTP_PERIOD_S)
        fraction = remaining / TOTP_PERIOD_S

        # Pick color based on time remaining
        if remaining > 10:
            color = COUNTDOWN_GREEN
        elif remaining > 5:
            color = COUNTDOWN_YELLOW
        else:
            color = COUNTDOWN_RED

        # Draw the bar
        self.countdown_canvas.update_idletasks()
        width = self.countdown_canvas.winfo_width()
        self.countdown_canvas.delete("all")
        bar_width = max(1, int(width * fraction))
        self.countdown_canvas.create_rectangle(0, 0, bar_width, 4, fill=color, outline="")

        # Auto-close if code expired during selection
        if remaining <= 1:
            logger.warning("TOTP code expired during selection")
            self.root.destroy()
            return

        self.root.after(1000, self._update_countdown)

    def run(self) -> Optional[int]:
        """Show the selector and block until user selects or cancels."""
        self.root.after(10, self.root.focus_force)
        if self._use_toplevel:
            self.root.grab_set()
            self.root.wait_window()
        else:
            self.root.mainloop()
        return self.selected


def show_account_selector(accounts: list[tuple[str, str]], parent: Optional[tk.Tk] = None) -> Optional[int]:
    """Display a popup listing TOTP accounts with codes and countdown timer.

    Args:
        accounts: List of (account_name, code) tuples.
        parent: Optional tkinter root to use as parent (uses Toplevel instead of Tk).

    Returns:
        Index of selected account, or None if cancelled.
    """
    selector = AccountSelector(accounts, parent=parent)
    return selector.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_accounts = [
        ("Google: user@gmail.com", "482937"),
        ("GitHub: myuser", "159263"),
        ("Microsoft: work@company.com", "731048"),
    ]
    result = show_account_selector(test_accounts)
    print(f"Selected index: {result}")
