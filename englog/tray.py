"""System tray icon for EngLog — shows status, allows quick actions."""

import sys
import threading
from typing import Optional

from englog import database as db
from englog.capture import CaptureEngine
from englog.session import get_active_session_info

# Only import pystray on Windows / where a display is available
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    HAS_TRAY = True
except Exception:
    HAS_TRAY = False


def _create_icon_image(active: bool = False) -> "Image.Image":
    """Create a simple tray icon — green circle when active, gray when idle."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (76, 175, 80, 255) if active else (158, 158, 158, 255)
    draw.ellipse([8, 8, size - 8, size - 8], fill=color)
    # "E" in the center
    try:
        draw.text((20, 14), "E", fill=(255, 255, 255, 255))
    except Exception:
        pass
    return img


class TrayApp:
    """System tray application that runs the capture engine in the background."""

    def __init__(self):
        self.capture_engine: Optional[CaptureEngine] = None
        self.icon: Optional["pystray.Icon"] = None
        self._session_info: Optional[dict] = None

    def _on_capture(self, screenshot_path, window_title, process_name):
        """Callback: save each capture to the database."""
        if self._session_info:
            db.add_capture(
                self._session_info["session_id"],
                screenshot_path=screenshot_path,
                active_window=window_title,
                active_process=process_name,
            )

    def _update_icon(self):
        if self.icon:
            active = self._session_info is not None
            self.icon.icon = _create_icon_image(active)
            status = f"EngLog — {self._session_info['project']}" if active else "EngLog — idle"
            self.icon.title = status

    def _get_menu(self):
        session = get_active_session_info()
        self._session_info = session

        if session:
            return pystray.Menu(
                pystray.MenuItem(f"● Recording: {session['project']}", None, enabled=False),
                pystray.MenuItem("Stop session", self._stop_session),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit EngLog", self._quit),
            )
        else:
            return pystray.Menu(
                pystray.MenuItem("○ Idle — start via CLI", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit EngLog", self._quit),
            )

    def _stop_session(self, icon, item):
        if self.capture_engine:
            self.capture_engine.stop()
            self.capture_engine = None
        from englog.session import stop_current_session
        stop_current_session()
        self._session_info = None
        self._update_icon()

    def _quit(self, icon, item):
        if self.capture_engine:
            self.capture_engine.stop()
        icon.stop()

    def start_capture_for_session(self, session_id: int, project_name: str):
        """Begin background capture for a session."""
        self._session_info = {"session_id": session_id, "project": project_name}
        self.capture_engine = CaptureEngine(session_id, on_capture=self._on_capture)
        self.capture_engine.start()
        self._update_icon()

    def run(self):
        """Run the tray icon (blocking — run in main thread or its own thread)."""
        if not HAS_TRAY:
            print("[englog] System tray not available on this platform.")
            return

        # Check if there's already an active session
        session = get_active_session_info()
        if session:
            self._session_info = session
            self.capture_engine = CaptureEngine(session["session_id"], on_capture=self._on_capture)
            self.capture_engine.start()

        self.icon = pystray.Icon(
            "englog",
            _create_icon_image(active=self._session_info is not None),
            title="EngLog",
            menu=self._get_menu(),
        )
        self.icon.run()
