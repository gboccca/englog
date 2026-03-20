"""Screenshot capture and active window tracking.

Platform: Windows (uses pywin32 + mss).
On other platforms, window tracking gracefully degrades.
"""

import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

import mss
from PIL import Image

from englog.config import SCREENSHOTS_DIR, SCREENSHOT_INTERVAL_SECONDS, SCREENSHOT_QUALITY, SCREENSHOT_SCALE

# ── Active window detection (Windows) ─────────────────────

def get_active_window_info() -> tuple[str, str]:
    """Return (window_title, process_name) for the currently focused window."""
    if sys.platform != "win32":
        return ("unknown", "unknown")
    try:
        import win32gui
        import win32process
        import psutil

        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        return (title, process.name())
    except Exception:
        return ("unknown", "unknown")


# ── Screenshot ────────────────────────────────────────────

def take_screenshot(session_id: int) -> Optional[str]:
    """Capture a screenshot, save as compressed JPEG, return the file path."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = SCREENSHOTS_DIR / str(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        filepath = session_dir / f"{timestamp}.jpg"

        with mss.mss() as sct:
            # Capture primary monitor
            monitor = sct.monitors[1]
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        # Resize to save space
        new_size = (int(img.width * SCREENSHOT_SCALE), int(img.height * SCREENSHOT_SCALE))
        img = img.resize(new_size, Image.LANCZOS)
        img.save(str(filepath), "JPEG", quality=SCREENSHOT_QUALITY)

        return str(filepath)
    except Exception as e:
        import sys
        print(f"[englog] Screenshot failed: {e}", file=sys.stderr)
        return None


# ── Background capture loop ───────────────────────────────

class CaptureEngine:
    """Runs in a background thread: takes periodic screenshots + tracks active window."""

    def __init__(self, session_id: int, on_capture: Optional[Callable] = None):
        self.session_id = session_id
        self.on_capture = on_capture  # callback(screenshot_path, window_title, process_name)
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        while self._running:
            window_title, process_name = get_active_window_info()
            screenshot_path = take_screenshot(self.session_id)

            if self.on_capture:
                self.on_capture(screenshot_path, window_title, process_name)

            # Sleep in small increments so we can stop quickly
            for _ in range(SCREENSHOT_INTERVAL_SECONDS * 2):
                if not self._running:
                    break
                time.sleep(0.5)
