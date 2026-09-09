"""Minimal Windows auto-clicker GUI.

The GUI exposes a Start/Stop toggle. While running, a background worker sends
left-click events at the current cursor position with a random interval between
the configured minimum and maximum. Stop keys are handled through a global
keyboard listener, even when another window has focus.
"""

from __future__ import annotations

import queue
import random
import threading
import time
import tkinter as tk
from tkinter import messagebox
from typing import Any

try:
    from pynput import keyboard, mouse
except ImportError:
    keyboard = None
    mouse = None


DEFAULT_MIN_INTERVAL_MS = 67
DEFAULT_MAX_INTERVAL_MS = 67
START_DELAY_SECONDS = 0.5
COUNTDOWN_THRESHOLD_SECONDS = 5
COUNTDOWN_REFRESH_MS = 100
STOP_HOTKEY_LABEL = "|, \\, F6"
STOP_HOTKEY_CHARS = {"|", "\\"}


class AutoClickerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.stop_requested = threading.Event()
        self.worker: threading.Thread | None = None
        self.hotkey_listener: Any | None = None
        self.hotkey_events: queue.Queue[str] = queue.Queue()
        self.mouse_controller: Any | None = mouse.Controller() if mouse is not None else None
        self.countdown_lock = threading.Lock()
        self.countdown_deadline: float | None = None
        self.closed = False
        self.min_interval_var = tk.StringVar(value=str(DEFAULT_MIN_INTERVAL_MS))
        self.max_interval_var = tk.StringVar(value=str(DEFAULT_MAX_INTERVAL_MS))

        root.title("NMZHelper Auto Clicker")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.frame = tk.Frame(root, padx=24, pady=20)
        self.frame.grid(row=0, column=0, sticky="nsew")

        self.title_label = tk.Label(
            self.frame,
            text="Auto Clicker",
            font=("Segoe UI", 14, "bold"),
        )
        self.title_label.grid(row=0, column=0, sticky="ew")

        self.status_label = tk.Label(
            self.frame,
            text=self.stopped_status,
            font=("Segoe UI", 10),
        )
        self.status_label.grid(row=1, column=0, pady=(8, 16), sticky="ew")

        self.interval_frame = tk.Frame(self.frame)
        self.interval_frame.grid(row=2, column=0, sticky="ew")
        self.interval_frame.columnconfigure(1, weight=1)

        self.min_interval_label = tk.Label(
            self.interval_frame,
            text="Min interval (ms)",
            font=("Segoe UI", 10),
        )
        self.min_interval_label.grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 8))

        self.min_interval_entry = tk.Entry(
            self.interval_frame,
            textvariable=self.min_interval_var,
            width=10,
            font=("Segoe UI", 10),
        )
        self.min_interval_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        self.max_interval_label = tk.Label(
            self.interval_frame,
            text="Max interval (ms)",
            font=("Segoe UI", 10),
        )
        self.max_interval_label.grid(row=1, column=0, sticky="w", padx=(0, 8))

        self.max_interval_entry = tk.Entry(
            self.interval_frame,
            textvariable=self.max_interval_var,
            width=10,
            font=("Segoe UI", 10),
        )
        self.max_interval_entry.grid(row=1, column=1, sticky="ew")

        self.countdown_label = tk.Label(
            self.frame,
            text="",
            font=("Segoe UI", 10),
        )
        self.countdown_label.grid(row=3, column=0, pady=(12, 0), sticky="ew")

        self.toggle_button = tk.Button(
            self.frame,
            text="Start",
            width=16,
            height=2,
            command=self.toggle_clicking,
            font=("Segoe UI", 11),
        )
        self.toggle_button.grid(row=4, column=0, pady=(16, 0), sticky="ew")

        if keyboard is None or mouse is None:
            self.toggle_button.configure(state=tk.DISABLED)
            self.status_label.configure(text="Install requirements to enable clicking.")
            return

        self.register_hotkey_listener()
        self.root.after(50, self.process_hotkey_events)
        self.root.after(COUNTDOWN_REFRESH_MS, self.update_countdown_display)

    @property
    def stopped_status(self) -> str:
        return f"Stopped. Stop keys: {STOP_HOTKEY_LABEL}."

    def register_hotkey_listener(self) -> None:
        if keyboard is None:
            return

        try:
            self.hotkey_listener = keyboard.Listener(on_press=self.handle_key_press)
            self.hotkey_listener.start()
        except Exception as exc:  # noqa: BLE001 - keep the GUI usable if hook setup fails.
            self.status_label.configure(text=f"{self.stopped_status} Hotkey unavailable: {exc}")

    def handle_key_press(self, key: Any) -> None:
        if self.is_stop_hotkey(key):
            self.hotkey_events.put("stop")

    def is_stop_hotkey(self, key: Any) -> bool:
        if keyboard is not None and key == keyboard.Key.f6:
            return True

        return getattr(key, "char", None) in STOP_HOTKEY_CHARS

    def process_hotkey_events(self) -> None:
        while not self.hotkey_events.empty():
            event = self.hotkey_events.get_nowait()
            if event == "stop" and self.is_running:
                self.stop_clicking()

        if not self.closed:
            self.root.after(50, self.process_hotkey_events)

    def toggle_clicking(self) -> None:
        if self.is_running:
            self.stop_clicking()
        else:
            self.start_clicking()

    @property
    def is_running(self) -> bool:
        return self.worker is not None and self.worker.is_alive() and not self.stop_requested.is_set()

    def start_clicking(self) -> None:
        intervals = self.parse_intervals()
        if intervals is None:
            return

        min_interval_ms, max_interval_ms = intervals
        self.stop_requested.clear()
        self.clear_countdown_display()
        self.worker = threading.Thread(
            target=self.click_loop,
            args=(min_interval_ms, max_interval_ms),
            daemon=True,
        )
        self.worker.start()
        self.toggle_button.configure(text="Stop")
        self.set_interval_inputs_enabled(False)
        self.status_label.configure(
            text=(
                f"Running. Interval: {min_interval_ms}-{max_interval_ms} ms. "
                f"Stop keys: {STOP_HOTKEY_LABEL}."
            )
        )

    def stop_clicking(self) -> None:
        self.stop_requested.set()
        self.clear_countdown_display()
        self.toggle_button.configure(text="Start")
        self.set_interval_inputs_enabled(True)
        self.status_label.configure(text=self.stopped_status)

    def parse_intervals(self) -> tuple[int, int] | None:
        min_raw = self.min_interval_var.get().strip()
        max_raw = self.max_interval_var.get().strip()

        try:
            min_interval_ms = int(min_raw)
            max_interval_ms = int(max_raw)
        except ValueError:
            messagebox.showerror(
                "Invalid Intervals",
                "Minimum and maximum intervals must be whole numbers of milliseconds.",
            )
            return None

        if min_interval_ms < 1 or max_interval_ms < 1:
            messagebox.showerror(
                "Invalid Intervals",
                "Minimum and maximum intervals must be at least 1 millisecond.",
            )
            return None

        if min_interval_ms > max_interval_ms:
            messagebox.showerror(
                "Invalid Intervals",
                "Minimum interval must be less than or equal to maximum interval.",
            )
            return None

        return min_interval_ms, max_interval_ms

    def set_interval_inputs_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        self.min_interval_entry.configure(state=state)
        self.max_interval_entry.configure(state=state)

    def set_countdown_deadline(self, deadline: float) -> None:
        with self.countdown_lock:
            self.countdown_deadline = deadline

    def clear_countdown(self) -> None:
        with self.countdown_lock:
            self.countdown_deadline = None

    def clear_countdown_display(self) -> None:
        self.clear_countdown()
        self.countdown_label.configure(text="")


    def update_countdown_display(self) -> None:
        countdown_text = ""

        with self.countdown_lock:
            countdown_deadline = self.countdown_deadline

        if self.is_running and countdown_deadline is not None:
            seconds_remaining = max(0, countdown_deadline - time.perf_counter())
            countdown_text = f"Next click in {seconds_remaining:.1f}s"

        self.countdown_label.configure(text=countdown_text)

        if not self.closed:
            self.root.after(COUNTDOWN_REFRESH_MS, self.update_countdown_display)

    def click_loop(self, min_interval_ms: int, max_interval_ms: int) -> None:
        self.clear_countdown()
        next_click_at = time.perf_counter() + START_DELAY_SECONDS

        while not self.stop_requested.is_set():
            wait_time = max(0, next_click_at - time.perf_counter())
            if self.stop_requested.wait(wait_time):
                break

            try:
                self.send_left_click()
            except Exception as exc:  # noqa: BLE001 - surface OS click failures to the GUI.
                self.root.after(0, self.handle_worker_error, exc)
                break

            next_interval_seconds = random.randint(min_interval_ms, max_interval_ms) / 1000
            next_click_at += next_interval_seconds
            if next_click_at < time.perf_counter():
                next_click_at = time.perf_counter() + next_interval_seconds

            if next_interval_seconds > COUNTDOWN_THRESHOLD_SECONDS:
                self.set_countdown_deadline(next_click_at)
            else:
                self.clear_countdown()

    def send_left_click(self) -> None:
        if mouse is None or self.mouse_controller is None:
            raise RuntimeError("The pynput mouse controller is unavailable.")

        self.mouse_controller.click(mouse.Button.left)

    def handle_worker_error(self, exc: Exception) -> None:
        self.stop_clicking()
        messagebox.showerror("Auto Clicker Error", str(exc))

    def close(self) -> None:
        self.closed = True
        self.stop_requested.set()
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    AutoClickerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
