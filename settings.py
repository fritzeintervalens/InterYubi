"""Settings window for InterYubi (Catppuccin Mocha dark theme)."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
import webbrowser
from typing import Callable, Optional

import keyboard

from config import AppConfig
from selector import get_monitor_work_area
from theme import (
    ACCENT_COLOR,
    BG_COLOR,
    BUTTON_BG,
    BUTTON_HOVER,
    ENTRY_BG,
    ITEM_BG,
    SUBTEXT_COLOR,
    TEXT_COLOR,
    TITLE_BG,
)

logger = logging.getLogger(__name__)


class SettingsWindow:
    """Dark-themed settings window for InterYubi."""

    def __init__(
        self,
        parent: tk.Tk,
        current_config: AppConfig,
        on_save: Callable[[AppConfig, bool], None],
        startup_enabled: bool,
    ) -> None:
        self.parent = parent
        self.current_config = current_config
        self.on_save = on_save
        self._recording = False

        self.win = tk.Toplevel(parent)
        self.win.title("InterYubi Settings")
        self.win.configure(bg=BG_COLOR)
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # --- Variables ---
        self.hotkey_var = tk.StringVar(value=current_config.hotkey)
        self.selector_hotkey_var = tk.StringVar(
            value=current_config.selector_hotkey or ""
        )
        self.auto_detect_var = tk.BooleanVar(value=current_config.domain_auto_detect)
        self.startup_var = tk.BooleanVar(value=startup_enabled)
        self.delay_var = tk.IntVar(value=current_config.type_delay_ms)
        self.auto_submit_var = tk.BooleanVar(value=current_config.auto_submit)
        self.default_account_var = tk.StringVar(
            value=current_config.default_account or ""
        )

        self._build_ui()
        self._center_window()

    def _center_window(self) -> None:
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        h = self.win.winfo_reqheight()

        # Center on the monitor where the mouse currently is
        mouse_x = self.win.winfo_pointerx()
        mouse_y = self.win.winfo_pointery()
        work_area = get_monitor_work_area(mouse_x, mouse_y)

        if work_area is not None:
            mon_left, mon_top, mon_right, mon_bottom = work_area
        else:
            mon_left, mon_top = 0, 0
            mon_right = self.win.winfo_screenwidth()
            mon_bottom = self.win.winfo_screenheight()

        x = mon_left + (mon_right - mon_left - w) // 2
        y = mon_top + (mon_bottom - mon_top - h) // 2
        self.win.geometry(f"+{x}+{y}")

    def _build_ui(self) -> None:
        main_frame = tk.Frame(self.win, bg=BG_COLOR, padx=20, pady=16)
        main_frame.pack(fill="both", expand=True)

        # --- Title ---
        title_frame = tk.Frame(main_frame, bg=TITLE_BG, padx=12, pady=8)
        title_frame.pack(fill="x", pady=(0, 16))
        tk.Label(
            title_frame,
            text="InterYubi Settings",
            font=("Segoe UI", 12, "bold"),
            fg=TEXT_COLOR,
            bg=TITLE_BG,
        ).pack(side="left")

        # --- Hotkeys section ---
        self._build_section_header(main_frame, "HOTKEYS")
        hotkey_frame = tk.Frame(main_frame, bg=ITEM_BG, padx=12, pady=10)
        hotkey_frame.pack(fill="x", pady=(0, 12))

        # Primary hotkey row
        row1 = tk.Frame(hotkey_frame, bg=ITEM_BG)
        row1.pack(fill="x", pady=(0, 6))
        tk.Label(
            row1,
            text="Primary hotkey:",
            font=("Segoe UI", 9),
            fg=TEXT_COLOR,
            bg=ITEM_BG,
            width=16,
            anchor="w",
        ).pack(side="left")
        self.hotkey_entry = tk.Entry(
            row1,
            textvariable=self.hotkey_var,
            font=("Consolas", 9),
            fg=ACCENT_COLOR,
            bg=ENTRY_BG,
            insertbackground=TEXT_COLOR,
            relief="flat",
            width=20,
        )
        self.hotkey_entry.pack(side="left", padx=(0, 6))
        self.hotkey_record_btn = tk.Button(
            row1,
            text="Record",
            font=("Segoe UI", 8),
            fg=TEXT_COLOR,
            bg=BUTTON_BG,
            activebackground=BUTTON_HOVER,
            activeforeground=TEXT_COLOR,
            relief="flat",
            cursor="hand2",
            command=lambda: self._record_hotkey(
                self.hotkey_var, self.hotkey_record_btn
            ),
        )
        self.hotkey_record_btn.pack(side="left")

        # Selector hotkey row
        row2 = tk.Frame(hotkey_frame, bg=ITEM_BG)
        row2.pack(fill="x")
        tk.Label(
            row2,
            text="Selector hotkey:",
            font=("Segoe UI", 9),
            fg=TEXT_COLOR,
            bg=ITEM_BG,
            width=16,
            anchor="w",
        ).pack(side="left")
        self.selector_entry = tk.Entry(
            row2,
            textvariable=self.selector_hotkey_var,
            font=("Consolas", 9),
            fg=ACCENT_COLOR,
            bg=ENTRY_BG,
            insertbackground=TEXT_COLOR,
            relief="flat",
            width=20,
        )
        self.selector_entry.pack(side="left", padx=(0, 6))
        self.selector_record_btn = tk.Button(
            row2,
            text="Record",
            font=("Segoe UI", 8),
            fg=TEXT_COLOR,
            bg=BUTTON_BG,
            activebackground=BUTTON_HOVER,
            activeforeground=TEXT_COLOR,
            relief="flat",
            cursor="hand2",
            command=lambda: self._record_hotkey(
                self.selector_hotkey_var, self.selector_record_btn
            ),
        )
        self.selector_record_btn.pack(side="left")

        tk.Label(
            hotkey_frame,
            text="Selector hotkey always opens the account picker, bypassing auto-detect.",
            font=("Segoe UI", 8),
            fg=SUBTEXT_COLOR,
            bg=ITEM_BG,
            wraplength=380,
            justify="left",
        ).pack(fill="x", pady=(6, 0))

        # --- Auto-detection section ---
        self._build_section_header(main_frame, "AUTO-DETECTION")
        detect_frame = tk.Frame(main_frame, bg=ITEM_BG, padx=12, pady=10)
        detect_frame.pack(fill="x", pady=(0, 12))
        tk.Checkbutton(
            detect_frame,
            text="Enable domain auto-detection",
            variable=self.auto_detect_var,
            font=("Segoe UI", 9),
            fg=TEXT_COLOR,
            bg=ITEM_BG,
            selectcolor=ENTRY_BG,
            activebackground=ITEM_BG,
            activeforeground=TEXT_COLOR,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            detect_frame,
            text="Automatically selects the matching TOTP account based on\nthe active browser tab. Falls back to selector if no match.",
            font=("Segoe UI", 8),
            fg=SUBTEXT_COLOR,
            bg=ITEM_BG,
            justify="left",
        ).pack(fill="x", pady=(4, 0))

        # --- Startup section ---
        self._build_section_header(main_frame, "STARTUP")
        startup_frame = tk.Frame(main_frame, bg=ITEM_BG, padx=12, pady=10)
        startup_frame.pack(fill="x", pady=(0, 12))
        tk.Checkbutton(
            startup_frame,
            text="Launch InterYubi on PC startup",
            variable=self.startup_var,
            font=("Segoe UI", 9),
            fg=TEXT_COLOR,
            bg=ITEM_BG,
            selectcolor=ENTRY_BG,
            activebackground=ITEM_BG,
            activeforeground=TEXT_COLOR,
            anchor="w",
        ).pack(fill="x")

        # --- Typing section ---
        self._build_section_header(main_frame, "TYPING")
        typing_frame = tk.Frame(main_frame, bg=ITEM_BG, padx=12, pady=10)
        typing_frame.pack(fill="x", pady=(0, 12))

        delay_row = tk.Frame(typing_frame, bg=ITEM_BG)
        delay_row.pack(fill="x", pady=(0, 6))
        tk.Label(
            delay_row,
            text="Type delay:",
            font=("Segoe UI", 9),
            fg=TEXT_COLOR,
            bg=ITEM_BG,
            anchor="w",
        ).pack(side="left")
        self.delay_label = tk.Label(
            delay_row,
            text=f"{self.delay_var.get()} ms",
            font=("Consolas", 9),
            fg=ACCENT_COLOR,
            bg=ITEM_BG,
            width=8,
        )
        self.delay_label.pack(side="right")
        self.delay_scale = tk.Scale(
            delay_row,
            from_=0,
            to=200,
            orient="horizontal",
            variable=self.delay_var,
            showvalue=False,
            bg=ITEM_BG,
            fg=TEXT_COLOR,
            troughcolor=ENTRY_BG,
            highlightthickness=0,
            sliderrelief="flat",
            command=self._on_delay_change,
        )
        self.delay_scale.pack(side="right", fill="x", expand=True, padx=(10, 10))

        tk.Checkbutton(
            typing_frame,
            text="Auto-submit (press Enter after typing code)",
            variable=self.auto_submit_var,
            font=("Segoe UI", 9),
            fg=TEXT_COLOR,
            bg=ITEM_BG,
            selectcolor=ENTRY_BG,
            activebackground=ITEM_BG,
            activeforeground=TEXT_COLOR,
            anchor="w",
        ).pack(fill="x")

        # --- Account section ---
        self._build_section_header(main_frame, "ACCOUNT")
        account_frame = tk.Frame(main_frame, bg=ITEM_BG, padx=12, pady=10)
        account_frame.pack(fill="x", pady=(0, 16))

        acct_row = tk.Frame(account_frame, bg=ITEM_BG)
        acct_row.pack(fill="x")
        tk.Label(
            acct_row,
            text="Default account:",
            font=("Segoe UI", 9),
            fg=TEXT_COLOR,
            bg=ITEM_BG,
            anchor="w",
        ).pack(side="left")
        tk.Entry(
            acct_row,
            textvariable=self.default_account_var,
            font=("Consolas", 9),
            fg=ACCENT_COLOR,
            bg=ENTRY_BG,
            insertbackground=TEXT_COLOR,
            relief="flat",
            width=28,
        ).pack(side="right")

        # --- Buttons ---
        btn_frame = tk.Frame(main_frame, bg=BG_COLOR)
        btn_frame.pack(fill="x", pady=(4, 0))

        link_label = tk.Label(
            btn_frame,
            text="intervalens.com",
            font=("Segoe UI", 8),
            fg=SUBTEXT_COLOR,
            bg=BG_COLOR,
            cursor="hand2",
        )
        link_label.pack(side="left")
        link_label.bind(
            "<Button-1>",
            lambda e: webbrowser.open("https://www.intervalens.com"),
        )

        save_btn = tk.Button(
            btn_frame,
            text="Save",
            font=("Segoe UI", 9, "bold"),
            fg=ACCENT_COLOR,
            bg=BUTTON_BG,
            activebackground=BUTTON_HOVER,
            activeforeground=ACCENT_COLOR,
            relief="flat",
            cursor="hand2",
            width=10,
            command=self._on_save,
        )
        save_btn.pack(side="right", padx=(6, 0))

        cancel_btn = tk.Button(
            btn_frame,
            text="Cancel",
            font=("Segoe UI", 9),
            fg=TEXT_COLOR,
            bg=BUTTON_BG,
            activebackground=BUTTON_HOVER,
            activeforeground=TEXT_COLOR,
            relief="flat",
            cursor="hand2",
            width=10,
            command=self._on_cancel,
        )
        cancel_btn.pack(side="right")

    def _build_section_header(self, parent: tk.Frame, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            font=("Segoe UI", 8, "bold"),
            fg=SUBTEXT_COLOR,
            bg=BG_COLOR,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))

    def _on_delay_change(self, value: str) -> None:
        self.delay_label.configure(text=f"{int(float(value))} ms")

    def _record_hotkey(self, target_var: tk.StringVar, button: tk.Button) -> None:
        if self._recording:
            return
        self._recording = True
        button.configure(text="Press keys...")
        target_var.set("")

        def _capture() -> None:
            try:
                combo = keyboard.read_hotkey(suppress=False)
                self.win.after(0, lambda: self._finish_recording(target_var, button, combo))
            except Exception:
                self.win.after(0, lambda: self._finish_recording(target_var, button, None))

        threading.Thread(target=_capture, daemon=True).start()

    def _finish_recording(
        self, target_var: tk.StringVar, button: tk.Button, combo: Optional[str]
    ) -> None:
        self._recording = False
        button.configure(text="Record")
        if combo:
            target_var.set(combo)

    def _on_save(self) -> None:
        hotkey = self.hotkey_var.get().strip()
        if not hotkey:
            hotkey = self.current_config.hotkey  # fallback to current

        selector_hk = self.selector_hotkey_var.get().strip() or None
        default_acct = self.default_account_var.get().strip() or None

        new_config = AppConfig(
            hotkey=hotkey,
            selector_hotkey=selector_hk,
            default_account=default_acct,
            type_delay_ms=self.delay_var.get(),
            auto_submit=self.auto_submit_var.get(),
            ykman_path=self.current_config.ykman_path,
            oath_password=self.current_config.oath_password,
            domain_auto_detect=self.auto_detect_var.get(),
        )

        enable_startup = self.startup_var.get()
        self.win.destroy()
        self.on_save(new_config, enable_startup)

    def _on_cancel(self) -> None:
        self.win.destroy()

    def is_open(self) -> bool:
        try:
            return self.win.winfo_exists()
        except tk.TclError:
            return False
