"""EngLog GUI — small floating panel built with CustomTkinter.

Coexists with the CLI: both share the same SQLite database.
Launch with: englog-gui  (or: python -m englog.gui)
"""

import os
import sys
import threading
import time
from datetime import datetime
from typing import Optional, Callable

import customtkinter as ctk

from englog import database as db
from englog.session import (
    start_new_session,
    stop_current_session,
    add_session_note,
    get_active_session_info,
    _save_active_session,
)
from englog.capture import CaptureEngine
from englog.note_utils import detect_note_type
from englog.config import (
    SCREENSHOT_INTERVAL_SECONDS,
    SCREENSHOT_QUALITY,
    DATA_DIR,
)

# ── Theme ────────────────────────────────────────────────

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

COLOR_BG = "#F5F4F1"
COLOR_CARD = "#FFFFFF"
COLOR_ACCENT = "#2B4C8C"
COLOR_GREEN = "#22A55B"
COLOR_RED = "#DC3545"
COLOR_ORANGE = "#E6930A"
COLOR_DIM = "#8C8C8C"
COLOR_BORDER = "#E8E6E1"
COLOR_TEXT = "#1A1A1A"
COLOR_TEXT_SEC = "#6B6B6B"

COLOR_STATUS_IDLE = "#EEEDEA"
COLOR_STATUS_RECORDING = "#E8F5E9"
COLOR_STATUS_PAUSED = "#FFF8E1"

COLOR_BTN_SECONDARY_BG = "#EEECEA"
COLOR_BTN_SECONDARY_HOVER = "#E0DEDA"
COLOR_BTN_DANGER_HOVER = "#FDE8EA"

TYPE_COLORS = {
    "decision": "#8B5CF6",
    "blocker": "#DC3545",
    "observation": "#3B82F6",
}
TYPE_BG_TINTS = {
    "decision": "#F3EEFE",
    "blocker": "#FDE8EA",
    "observation": "#E8F0FE",
}

FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"

# ── Model profiles ──────────────────────────────────────
# Known models with recommended settings and descriptions.
# Models not in this dict still work — they just use defaults.
MODEL_PROFILES = {
    "mistral":       {"ctx": 32768,  "desc": "General-purpose, good default. Balanced speed/quality."},
    "llama3.1":      {"ctx": 32768,  "desc": "Reliable structured output (JSON). Good for timesheets."},
    "llama3.2":      {"ctx": 32768,  "desc": "Latest Llama, strong reasoning. Good all-rounder."},
    "gemma2":        {"ctx": 8192,   "desc": "Good at following detailed instructions. Smaller context."},
    "qwen2.5":       {"ctx": 32768,  "desc": "Strong on technical/engineering content."},
    "mistral-small": {"ctx": 32768,  "desc": "22B — best quality, much slower. Needs 16GB+ RAM."},
    "phi3":          {"ctx": 4096,   "desc": "Very fast, small. Good for quick notes, weak on long sessions."},
    "deepseek-r1":   {"ctx": 65536,  "desc": "Strong reasoning. Good for complex technical analysis."},
    "command-r":     {"ctx": 131072, "desc": "128K context. Best for very long sessions (8h+)."},
}

DEFAULT_EXAMPLE = """\
# Session Logbook — SolarSailDesign
## 2026-04-15 | 09:12 - 17:45

### Overview
Today's session focused on finalising the CMG sizing trade study. \
Started by reviewing the updated mass budget, then ran the redundancy \
analysis for 3-CMG vs 4-CMG configurations.

### Timeline
- **09:12** — Opened CMG_trade_v2.xlsx, reviewed mass breakdown.
  - [DECISION] Reduced from 4 to 3 CMGs — redundancy analysis shows \
acceptable risk at target orbit inclination, saving 1.2 kg.
- **10:30** — Switched to CATIA for bracket redesign.
  - [BLOCKER] Waiting on thermal data from Pierre before finalising \
bracket mounting points.
- **14:00** — Team meeting on Teams. Presented trade study results.

### Decisions Summary
- 3-CMG configuration selected (mass savings outweigh redundancy loss)
- Bracket design frozen pending thermal analysis

### Status
CMG trade study complete. Blocked on thermal data for bracket design.\
"""


# ── Markdown rendering helpers ───────────────────────────

import re

_MD_INLINE_RE = re.compile(r'(\*\*.*?\*\*|\[DECISION\]|\[BLOCKER\])')


def _configure_md_tags(textbox: ctk.CTkTextbox):
    """Configure Markdown text tags on a CTkTextbox's underlying tk Text widget."""
    tw = textbox._textbox
    tw.tag_configure("h1", font=(FONT_FAMILY, 16, "bold"), spacing1=6, spacing3=4)
    tw.tag_configure("h2", font=(FONT_FAMILY, 13, "bold"), spacing1=6, spacing3=2)
    tw.tag_configure("h3", font=(FONT_FAMILY, 12, "bold"), spacing1=4, spacing3=2)
    tw.tag_configure("bold", font=(FONT_MONO, 11, "bold"))
    tw.tag_configure("bullet", lmargin1=16, lmargin2=28)
    tw.tag_configure("indent", lmargin1=32, lmargin2=40)
    tw.tag_configure("decision", font=(FONT_MONO, 11, "bold"), foreground="#8B5CF6")
    tw.tag_configure("blocker", font=(FONT_MONO, 11, "bold"), foreground="#DC3545")
    tw.tag_configure("status_line", font=(FONT_MONO, 11, "italic"), foreground=COLOR_ACCENT)


def _render_markdown(textbox: ctk.CTkTextbox, text: str):
    """Parse Markdown text and insert it into a CTkTextbox with formatting tags.

    Assumes _configure_md_tags() has already been called on this textbox.
    """
    tw = textbox._textbox

    for line in text.split("\n"):
        stripped = line.strip()

        # Headers
        if stripped.startswith("### "):
            tw.insert("end", stripped[4:] + "\n", "h3")
            continue
        if stripped.startswith("## "):
            tw.insert("end", stripped[3:] + "\n", "h2")
            continue
        if stripped.startswith("# "):
            tw.insert("end", stripped[2:] + "\n", "h1")
            continue

        # Determine line-level tag (bullet vs indented sub-bullet)
        line_tag = ""
        content = stripped
        if stripped.startswith("- "):
            line_tag = "bullet"
            content = stripped
        elif stripped.startswith("  - ") or stripped.startswith("    - "):
            line_tag = "indent"
            content = stripped.lstrip()

        # Process inline formatting: **bold**, [DECISION], [BLOCKER]
        parts = _MD_INLINE_RE.split(content)

        for part in parts:
            if part == "[DECISION]":
                tags = ("decision", line_tag) if line_tag else ("decision",)
                tw.insert("end", part, tags)
            elif part == "[BLOCKER]":
                tags = ("blocker", line_tag) if line_tag else ("blocker",)
                tw.insert("end", part, tags)
            elif part.startswith("**") and part.endswith("**"):
                inner = part[2:-2]
                tags = ("bold", line_tag) if line_tag else ("bold",)
                tw.insert("end", inner, tags)
            else:
                tags = (line_tag,) if line_tag else ()
                tw.insert("end", part, tags)

        tw.insert("end", "\n")


# ── Main Application ─────────────────────────────────────

class EngLogApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        from englog.config import load_settings
        load_settings()
        db.init_db()

        self.title("EngLog")
        screen_h = int(self.winfo_screenheight() * 0.88)
        self.geometry(f"450x{screen_h}")
        self.minsize(400, 525)
        self.resizable(True, True)
        self.configure(fg_color=COLOR_BG)

        # State
        self._capture_engine: Optional[CaptureEngine] = None
        self._session_started_at: Optional[datetime] = None

        # ── Navigation bar ──
        self._nav_frame = ctk.CTkFrame(self, fg_color=COLOR_ACCENT, corner_radius=0, height=42)
        self._nav_frame.pack(fill="x")
        self._nav_frame.pack_propagate(False)

        self._nav_buttons: list[ctk.CTkButton] = []
        nav_labels = ["Session", "Project", "History", "Summary", "Settings"]
        for i, label in enumerate(nav_labels):
            btn = ctk.CTkButton(
                self._nav_frame,
                text=label,
                width=80,
                height=38,
                corner_radius=0,
                fg_color="transparent",
                hover_color="#3D5FA0",
                text_color="#B8C8E0",
                font=ctk.CTkFont(family=FONT_FAMILY, size=13),
                command=lambda idx=i: self._show_frame(idx),
            )
            btn.pack(side="left", padx=1)
            self._nav_buttons.append(btn)

        # Underline indicator for active tab (use tk.Frame to allow place with width/height)
        import tkinter as tk
        self._nav_underline = tk.Frame(self._nav_frame, bg="#FFFFFF", height=3)

        # ── Frames ──
        self._container = ctk.CTkFrame(self, fg_color=COLOR_BG, corner_radius=0)
        self._container.pack(fill="both", expand=True)

        self._frames: list[ctk.CTkFrame] = [
            SessionFrame(self._container, self),
            ProjectFrame(self._container, self),
            HistoryFrame(self._container, self),
            SummaryFrame(self._container, self),
            SettingsFrame(self._container, self),
        ]
        for f in self._frames:
            f.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._current_frame = -1
        self._show_frame(0)

        # ── Global hotkey (Ctrl+Shift+N) ──
        self._quick_note_popup = None
        self._setup_global_hotkey()

    # ── Helpers ───────────────────────────────────────────

    def _show_frame(self, index: int):
        if index == self._current_frame:
            return
        self._current_frame = index
        for i, btn in enumerate(self._nav_buttons):
            if i == index:
                btn.configure(
                    fg_color="transparent",
                    text_color="#FFFFFF",
                    font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color="#B8C8E0",
                    font=ctk.CTkFont(family=FONT_FAMILY, size=13),
                )
        # Position underline under active tab button
        btn = self._nav_buttons[index]
        self._nav_underline.place(
            x=btn.winfo_x(), y=38,
            width=btn.winfo_width(), height=3,
        )
        # Schedule a re-position after layout settles (first show)
        self.after(10, lambda: self._nav_underline.place(
            x=self._nav_buttons[index].winfo_x(), y=38,
            width=self._nav_buttons[index].winfo_width(), height=3,
        ))
        self._frames[index].tkraise()
        if hasattr(self._frames[index], "on_show"):
            self._frames[index].on_show()

    def _run_in_background(self, fn: Callable, callback: Callable):
        """Run fn() in a daemon thread, deliver result via after()."""
        def worker():
            try:
                result = fn()
                self.after(0, lambda: callback(result, None))
            except Exception as e:
                self.after(0, lambda: callback(None, e))
        threading.Thread(target=worker, daemon=True).start()

    def navigate_to_summary(self, session_id: int):
        """Navigate to SummaryFrame and select a session."""
        self._show_frame(3)
        summary_frame: SummaryFrame = self._frames[3]
        summary_frame.select_session(session_id)

    # ── Global hotkey ────────────────────────────────────

    def _setup_global_hotkey(self):
        """Register Ctrl+Shift+N as a system-wide hotkey for quick notes."""
        try:
            import keyboard
            keyboard.add_hotkey("ctrl+shift+n", self._on_global_hotkey, suppress=True)
        except Exception:
            pass  # keyboard module unavailable or no permissions — degrade silently

    def _on_global_hotkey(self):
        """Called from keyboard listener thread — schedule popup on main thread."""
        self.after(0, self._show_quick_note)

    def _show_quick_note(self):
        """Show the quick-note popup. If already open, focus it."""
        if self._quick_note_popup and self._quick_note_popup.winfo_exists():
            self._quick_note_popup.focus_force()
            self._quick_note_popup._entry.focus_force()
            return

        active = get_active_session_info()
        self._quick_note_popup = QuickNotePopup(self, active)

    def _teardown_global_hotkey(self):
        """Unregister the global hotkey on app exit."""
        try:
            import keyboard
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

    def destroy(self):
        self._teardown_global_hotkey()
        super().destroy()


class QuickNotePopup(ctk.CTkToplevel):
    """Minimal floating popup for adding a note via global hotkey."""

    def __init__(self, app: EngLogApp, active_session: Optional[dict]):
        super().__init__(app)
        self._app = app
        self._active = active_session

        # Window setup — small, centered, always-on-top, no resize
        self.title("Quick Note")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.overrideredirect(False)

        # Center on screen
        w, h = 460, 140
        sx = self.winfo_screenwidth() // 2 - w // 2
        sy = self.winfo_screenheight() // 3 - h // 2
        self.geometry(f"{w}x{h}+{sx}+{sy}")
        self.configure(fg_color=COLOR_BG)

        # Status line
        if active_session:
            project = active_session.get("project", "?")
            status_text = f"Session active: {project}  |  Ctrl+Shift+N"
            status_color = COLOR_GREEN
        else:
            status_text = "No active session  |  Start one first"
            status_color = COLOR_RED

        ctk.CTkLabel(
            self, text=status_text, font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=status_color,
        ).pack(anchor="w", padx=12, pady=(8, 2))

        # Note entry row
        entry_row = ctk.CTkFrame(self, fg_color="transparent")
        entry_row.pack(fill="x", padx=12, pady=(2, 2))

        self._entry = ctk.CTkEntry(
            entry_row, placeholder_text="Type your note and press Enter...",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13), height=36,
            corner_radius=10,
        )
        self._entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._entry.bind("<Return>", lambda e: self._submit())
        self._entry.bind("<Escape>", lambda e: self.destroy())
        self._entry.bind("<KeyRelease>", self._on_keyrelease)

        self._submit_btn = ctk.CTkButton(
            entry_row, text="Add", width=60, height=36,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            corner_radius=16, fg_color=COLOR_BTN_SECONDARY_BG,
            hover_color=COLOR_BTN_SECONDARY_HOVER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER,
            command=self._submit,
            state="normal" if active_session else "disabled",
        )
        self._submit_btn.pack(side="right")

        # Type preview + feedback
        self._feedback = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM,
        )
        self._feedback.pack(anchor="w", padx=14, pady=(0, 6))

        # Bindings
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        # Focus
        self.after(50, lambda: self._entry.focus_force())
        self._type_debounce_job = None

    def _on_keyrelease(self, event):
        if self._type_debounce_job:
            self.after_cancel(self._type_debounce_job)
        self._type_debounce_job = self.after(200, self._update_type_preview)

    def _update_type_preview(self):
        text = self._entry.get().strip()
        if text:
            ntype = detect_note_type(text)
            color = TYPE_COLORS.get(ntype, COLOR_DIM)
            self._feedback.configure(text=f"type: {ntype}", text_color=color)
        else:
            self._feedback.configure(text="")

    def _submit(self):
        if not self._active:
            self._feedback.configure(text="No active session!", text_color=COLOR_RED)
            return

        content = self._entry.get().strip()
        if not content:
            return

        note_type = detect_note_type(content)
        result = add_session_note(content, note_type)

        if "error" in result:
            self._feedback.configure(text=result["error"], text_color=COLOR_RED)
            return

        type_color = TYPE_COLORS.get(note_type, COLOR_DIM)
        self._feedback.configure(
            text=f"Saved: [{note_type}] {content[:50]}{'...' if len(content) > 50 else ''}",
            text_color=type_color,
        )
        self._entry.delete(0, "end")

        # Auto-close after brief feedback
        self.after(800, self.destroy)


# ── View 1: Session ──────────────────────────────────────

class SessionFrame(ctk.CTkFrame):
    def __init__(self, parent, app: EngLogApp):
        super().__init__(parent, fg_color=COLOR_BG, corner_radius=0)
        self.app = app
        self._timer_job = None
        self._notes_job = None
        self._type_debounce_job = None

        # ── Status bar ──
        self._status_frame = ctk.CTkFrame(self, fg_color=COLOR_STATUS_IDLE, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        self._status_frame.pack(fill="x", padx=12, pady=(10, 5))

        self._status_dot_frame = ctk.CTkFrame(self._status_frame, width=10, height=10, corner_radius=5, fg_color=COLOR_DIM)
        self._status_dot_frame.pack(side="left", padx=(12, 6), pady=10)
        self._status_dot_frame.pack_propagate(False)
        self._status_label = ctk.CTkLabel(self._status_frame, text="No active session", font=ctk.CTkFont(family=FONT_FAMILY, size=13), text_color=COLOR_TEXT)
        self._status_label.pack(side="left", padx=4, fill="x", expand=True)
        self._timer_label = ctk.CTkLabel(self._status_frame, text="", font=ctk.CTkFont(family=FONT_MONO, size=14, weight="bold"), width=80, text_color=COLOR_TEXT)
        self._timer_label.pack(side="right", padx=12)

        # ── Project / description ──
        self._setup_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        self._setup_frame.pack(fill="x", padx=12, pady=5)

        ctk.CTkLabel(self._setup_frame, text="Project:", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT).pack(anchor="w", padx=12, pady=(8, 0))
        self._project_combo = ctk.CTkComboBox(
            self._setup_frame, width=380, values=self._get_project_names(),
            font=ctk.CTkFont(family=FONT_FAMILY, size=12), corner_radius=10,
        )
        self._project_combo.pack(padx=12, pady=(2, 4), fill="x")
        self._project_combo.set("")

        ctk.CTkLabel(self._setup_frame, text="Description:", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT).pack(anchor="w", padx=12)
        self._desc_entry = ctk.CTkTextbox(self._setup_frame, height=32, font=ctk.CTkFont(family=FONT_FAMILY, size=12), corner_radius=10, border_width=1, border_color=COLOR_BORDER, wrap="word")
        self._desc_entry.pack(padx=12, pady=(2, 8), fill="x")
        self._desc_entry._textbox.bind("<<Modified>>", lambda e: self._on_textbox_modified(self._desc_entry, 4))
        self._desc_entry._current_lines = 1

        # ── Start/Stop + Pause buttons ──
        self._btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._btn_frame.pack(fill="x", padx=12, pady=5)

        self._action_btn = ctk.CTkButton(
            self._btn_frame, text="Start Session", font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            height=40, corner_radius=20, fg_color=COLOR_GREEN, hover_color="#1B8A4A",
            command=self._toggle_session,
        )
        self._action_btn.pack(side="left", fill="x", expand=True)

        self._pause_btn = ctk.CTkButton(
            self._btn_frame, text="Pause", font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            height=40, width=90, corner_radius=20, fg_color=COLOR_ORANGE, hover_color="#C97E08",
            command=self._toggle_pause,
        )
        # Not packed yet — shown only during active session

        self._is_paused = False

        # ── Note input ──
        self._note_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        self._note_frame.pack(fill="x", padx=12, pady=5)

        note_row = ctk.CTkFrame(self._note_frame, fg_color="transparent")
        note_row.pack(fill="x", padx=12, pady=(8, 2))
        self._note_entry = ctk.CTkTextbox(note_row, height=32, font=ctk.CTkFont(family=FONT_FAMILY, size=12), corner_radius=10, border_width=1, border_color=COLOR_BORDER, wrap="word")
        self._note_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._note_entry.bind("<Return>", self._on_note_return)
        self._note_entry.bind("<KeyRelease>", self._on_note_keyrelease)
        self._note_entry._textbox.bind("<<Modified>>", lambda e: self._on_textbox_modified(self._note_entry, 4))
        self._note_entry._current_lines = 1
        self._add_note_btn = ctk.CTkButton(
            note_row, text="Add", width=60, height=30,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            corner_radius=16, fg_color=COLOR_BTN_SECONDARY_BG,
            hover_color=COLOR_BTN_SECONDARY_HOVER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER,
            command=self._add_note,
        )
        self._add_note_btn.pack(side="right")

        self._type_preview = ctk.CTkLabel(self._note_frame, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM)
        self._type_preview.pack(anchor="w", padx=14, pady=(0, 6))

        # ── Bottom panel (switches between live feed and idle dashboard) ──
        self._bottom_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLOR_DIM)
        self._bottom_label.pack(anchor="w", padx=16, pady=(8, 3))
        self._bottom_scroll = ctk.CTkScrollableFrame(self, fg_color=COLOR_BG, corner_radius=0)
        self._bottom_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 5))

        # ── Capture status ──
        self._capture_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM)
        self._capture_label.pack(anchor="w", padx=16, pady=(0, 8))

        # Show idle dashboard initially
        self._show_idle_dashboard()

        # Check for existing active session on startup
        self.after(100, self._check_existing_session)

    def _get_project_names(self) -> list[str]:
        try:
            return [p["name"] for p in db.list_projects()]
        except Exception:
            return []

    def _check_existing_session(self):
        active = get_active_session_info()
        if active:
            session = db.get_session(active["session_id"])
            if session:
                self.app._session_started_at = datetime.strptime(session["started_at"], "%Y-%m-%d %H:%M:%S")
                self._enter_active_state(active["project"], active["session_id"], resume_capture=True)

    def _toggle_session(self):
        active = get_active_session_info()
        if active:
            self._stop_session()
        else:
            self._start_session()

    def _start_session(self):
        project = self._project_combo.get().strip()
        if not project:
            self._status_label.configure(text="Enter a project name", text_color=COLOR_RED)
            return

        desc = self._desc_entry.get("1.0", "end-1c").strip()
        result = start_new_session(project, desc)
        if "error" in result:
            self._status_label.configure(text=result["error"], text_color=COLOR_RED)
            return

        session_id = result["session_id"]
        self.app._session_started_at = datetime.now()
        self._enter_active_state(project, session_id, resume_capture=True)

    def _enter_active_state(self, project: str, session_id: int, resume_capture: bool = False):
        """Switch UI to active-session mode."""
        self._status_dot_frame.configure(fg_color=COLOR_GREEN)
        self._status_frame.configure(fg_color=COLOR_STATUS_RECORDING)
        self._status_label.configure(text=f"Recording: {project}", text_color=COLOR_TEXT)
        self._action_btn.configure(text="Stop Session", fg_color=COLOR_RED, hover_color="#B82D3A")

        # Hide setup fields
        self._setup_frame.pack_forget()

        # Re-pack button frame and show pause button
        self._btn_frame.pack(fill="x", padx=12, pady=5, before=self._note_frame)
        self._pause_btn.pack(side="left", padx=(6, 0))
        self._is_paused = False
        self._pause_btn.configure(text="Pause", fg_color=COLOR_ORANGE, hover_color="#C97E08")

        # Start capture
        if resume_capture and not self.app._capture_engine:
            def on_capture(path, window, process):
                db.add_capture(session_id, path, window, process)
            self.app._capture_engine = CaptureEngine(session_id, on_capture=on_capture)
            self.app._capture_engine.start()
            self._capture_label.configure(text=f"Capturing every {SCREENSHOT_INTERVAL_SECONDS}s")

        # Start timer
        self._update_timer()
        # Switch bottom panel to live feed
        self._bottom_label.configure(text="LIVE ACTIVITY")
        self._refresh_live_feed(session_id)
        # Refresh project combo values
        self._project_combo.configure(values=self._get_project_names())

    def _stop_session(self):
        # Stop capture engine
        if self.app._capture_engine:
            self.app._capture_engine.stop()
            self.app._capture_engine = None

        result = stop_current_session()
        if "error" in result:
            self._status_label.configure(text=result["error"], text_color=COLOR_RED)
            return

        self._exit_active_state()
        self._status_label.configure(
            text=f"Stopped: {result['project']} ({result['notes_count']} notes, {result['captures_count']} captures)",
            text_color=COLOR_ORANGE,
        )

    def _toggle_pause(self):
        """Pause or resume screen capture. Session stays active, notes still work."""
        active = get_active_session_info()
        if not active:
            return

        if not self._is_paused:
            # Pause: stop capture engine
            if self.app._capture_engine:
                self.app._capture_engine.stop()
                self.app._capture_engine = None
            self._is_paused = True
            self._pause_btn.configure(text="Resume", fg_color=COLOR_GREEN, hover_color="#1B8A4A")
            self._status_dot_frame.configure(fg_color=COLOR_ORANGE)
            self._status_frame.configure(fg_color=COLOR_STATUS_PAUSED)
            self._status_label.configure(text=f"Paused: {active['project']}", text_color=COLOR_ORANGE)
            self._capture_label.configure(text="Capture paused — notes still active")
        else:
            # Resume: restart capture engine
            session_id = active["session_id"]
            def on_capture(path, window, process):
                db.add_capture(session_id, path, window, process)
            self.app._capture_engine = CaptureEngine(session_id, on_capture=on_capture)
            self.app._capture_engine.start()
            self._is_paused = False
            self._pause_btn.configure(text="Pause", fg_color=COLOR_ORANGE, hover_color="#C97E08")
            self._status_dot_frame.configure(fg_color=COLOR_GREEN)
            self._status_frame.configure(fg_color=COLOR_STATUS_RECORDING)
            self._status_label.configure(text=f"Recording: {active['project']}", text_color=COLOR_TEXT)
            self._capture_label.configure(text=f"Capturing every {SCREENSHOT_INTERVAL_SECONDS}s")

    def _exit_active_state(self):
        """Switch UI back to idle mode."""
        self._status_dot_frame.configure(fg_color=COLOR_DIM)
        self._status_frame.configure(fg_color=COLOR_STATUS_IDLE)
        self._timer_label.configure(text="")
        self._action_btn.configure(text="Start Session", fg_color=COLOR_GREEN, hover_color="#1B8A4A")
        self._capture_label.configure(text="")
        self.app._session_started_at = None
        self._is_paused = False

        # Cancel timers
        if self._timer_job:
            self.after_cancel(self._timer_job)
            self._timer_job = None
        if self._notes_job:
            self.after_cancel(self._notes_job)
            self._notes_job = None

        # Hide pause button, show setup fields again
        self._pause_btn.pack_forget()
        self._setup_frame.pack(fill="x", padx=12, pady=5, after=self._status_frame)
        self._btn_frame.pack_forget()
        self._btn_frame.pack(fill="x", padx=12, pady=5, after=self._setup_frame)

        # Switch bottom panel back to idle dashboard
        self._show_idle_dashboard()

    def _update_timer(self):
        if not self.app._session_started_at:
            return
        elapsed = datetime.now() - self.app._session_started_at
        total_seconds = int(elapsed.total_seconds())
        h, remainder = divmod(total_seconds, 3600)
        m, s = divmod(remainder, 60)
        self._timer_label.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
        self._timer_job = self.after(1000, self._update_timer)

    def _on_note_return(self, event):
        """Submit note on Enter, allow Shift+Enter for newline."""
        if not (event.state & 0x1):  # Shift not held
            self._add_note()
            return "break"  # Prevent newline insertion

    def _on_note_keyrelease(self, event):
        if self._type_debounce_job:
            self.after_cancel(self._type_debounce_job)
        self._type_debounce_job = self.after(300, self._update_type_preview)

    def _update_type_preview(self):
        text = self._note_entry.get("1.0", "end-1c").strip()
        if text:
            ntype = detect_note_type(text)
            color = TYPE_COLORS.get(ntype, COLOR_DIM)
            self._type_preview.configure(text=f"auto-detected: {ntype}", text_color=color)
        else:
            self._type_preview.configure(text="")

    def _on_textbox_modified(self, textbox: ctk.CTkTextbox, max_lines: int = 4):
        """Resize textbox height to fit content. Only reconfigures when line count changes."""
        # Reset the modified flag so the event fires again next time
        textbox._textbox.edit_modified(False)
        # Update after idle so the widget has finished laying out the text
        self.after_idle(lambda: self._resize_textbox(textbox, max_lines))

    def _resize_textbox(self, textbox: ctk.CTkTextbox, max_lines: int):
        """Compute display line count and resize if changed."""
        inner = textbox._textbox
        try:
            # Count actual display lines (accounts for word wrap)
            num_display_lines = int(inner.count("1.0", "end", "displaylines") or 1)
        except Exception:
            num_display_lines = int(inner.index("end-1c").split(".")[0])
        num_display_lines = max(1, min(num_display_lines, max_lines))
        # Only reconfigure if line count changed
        prev = getattr(textbox, "_current_lines", 1)
        if num_display_lines != prev:
            textbox._current_lines = num_display_lines
            new_height = 32 + (num_display_lines - 1) * 20
            textbox.configure(height=new_height)

    def _add_note(self):
        content = self._note_entry.get("1.0", "end-1c").strip()
        if not content:
            return
        note_type = detect_note_type(content)
        result = add_session_note(content, note_type)
        if "error" in result:
            self._type_preview.configure(text=result["error"], text_color=COLOR_RED)
            return
        self._note_entry.delete("1.0", "end")
        self._note_entry._current_lines = 1
        self._note_entry.configure(height=32)
        self._type_preview.configure(text="")
        # Refresh live feed
        active = get_active_session_info()
        if active:
            self._refresh_live_feed(active["session_id"])

    def _refresh_live_feed(self, session_id: int):
        """Show merged timeline of notes + capture transitions, newest first."""
        notes = db.get_session_notes(session_id)
        captures = db.get_session_captures(session_id)

        # Build unified timeline items
        items = []
        for n in notes:
            items.append({
                "kind": "note",
                "timestamp": n["timestamp"],
                "note_type": n["note_type"],
                "content": n["content"],
            })

        # Only show capture *transitions* (when app/window changes)
        prev_process = None
        prev_window = None
        for c in captures:
            proc = c.get("active_process") or "unknown"
            win = c.get("active_window") or "unknown"
            if proc != prev_process or win != prev_window:
                win_short = win[:60] + "..." if len(win) > 63 else win
                items.append({
                    "kind": "capture",
                    "timestamp": c["timestamp"],
                    "process": proc,
                    "window": win_short,
                })
                prev_process = proc
                prev_window = win

        # Sort by timestamp, take last 25, show newest first
        items.sort(key=lambda x: x["timestamp"])
        items = list(reversed(items[-25:]))

        # Skip rebuild if data hasn't changed (prevents flickering)
        fingerprint = str([(i.get("timestamp"), i.get("kind"), i.get("content", i.get("process", ""))) for i in items])
        if hasattr(self, "_feed_fingerprint") and self._feed_fingerprint == fingerprint:
            # No changes — just reschedule
            active = get_active_session_info()
            if active:
                self._notes_job = self.after(5000, lambda: self._refresh_live_feed(session_id))
            return
        self._feed_fingerprint = fingerprint

        # Clear existing
        for w in self._bottom_scroll.winfo_children():
            w.destroy()

        for item in items:
            ts = item["timestamp"].split(" ")[1][:5] if " " in item["timestamp"] else item["timestamp"]

            if item["kind"] == "note":
                ntype = item["note_type"]
                accent_color = TYPE_COLORS.get(ntype, COLOR_DIM)
                tint_color = TYPE_BG_TINTS.get(ntype, None)
                badge_bg = tint_color if tint_color else COLOR_BTN_SECONDARY_BG
                content = item["content"]

                card = ctk.CTkFrame(self._bottom_scroll, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER, height=0)
                card.pack(fill="x", pady=2, padx=2)

                accent_bar = ctk.CTkFrame(card, fg_color=accent_color, width=4, height=0, corner_radius=2)
                accent_bar.pack(side="left", fill="y")

                content_frame = ctk.CTkFrame(card, fg_color="transparent", height=0)
                content_frame.pack(side="left", fill="x", expand=True, padx=(8, 8), pady=(4, 4))

                top_row = ctk.CTkFrame(content_frame, fg_color="transparent", height=0)
                top_row.pack(fill="x")

                ctk.CTkLabel(
                    top_row, text=ntype[:5].upper(),
                    font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold"),
                    text_color=accent_color, fg_color=badge_bg,
                    corner_radius=6, height=18, width=46,
                ).pack(side="left")
                ctk.CTkLabel(top_row, text=ts, font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLOR_DIM).pack(side="right")

                ctk.CTkLabel(content_frame, text=content, font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT, anchor="w", wraplength=380).pack(fill="x", pady=(2, 0))

            else:  # capture transition
                row = ctk.CTkFrame(self._bottom_scroll, fg_color="transparent", height=20)
                row.pack(fill="x", pady=0, padx=6)
                row.pack_propagate(False)
                ctk.CTkLabel(
                    row, text=f"{ts}  \u2192  {item['process']}",
                    font=ctk.CTkFont(family=FONT_MONO, size=10),
                    text_color=COLOR_DIM, anchor="w",
                ).pack(side="left")
                ctk.CTkLabel(
                    row, text=item["window"],
                    font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                    text_color="#AAAAAA", anchor="e",
                ).pack(side="right", padx=(4, 0))

        # Schedule next refresh if session active
        active = get_active_session_info()
        if active:
            self._notes_job = self.after(5000, lambda: self._refresh_live_feed(session_id))

    def _show_idle_dashboard(self):
        """Show stats dashboard when no session is active."""
        self._feed_fingerprint = None
        self._bottom_label.configure(text="DASHBOARD")
        for w in self._bottom_scroll.winfo_children():
            w.destroy()

        try:
            stats = db.get_dashboard_stats()
        except Exception:
            ctk.CTkLabel(
                self._bottom_scroll, text="No data yet — start your first session!",
                font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_DIM,
            ).pack(pady=20)
            return

        # ── Stat cards row ──
        cards_frame = ctk.CTkFrame(self._bottom_scroll, fg_color="transparent")
        cards_frame.pack(fill="x", padx=2, pady=(4, 8))
        cards_frame.columnconfigure((0, 1, 2), weight=1)

        def _format_duration(seconds: int) -> str:
            h, m = divmod(seconds // 60, 60)
            if h > 0:
                return f"{h}h {m:02d}m"
            return f"{m}m"

        stat_items = [
            ("Today", _format_duration(stats["today_seconds"])),
            ("This week", _format_duration(stats["week_seconds"])),
            (("Streak" if stats["streak"] > 0 else "Streak"), f"{stats['streak']}d" if stats["streak"] > 0 else "—"),
        ]
        for col, (label, value) in enumerate(stat_items):
            card = ctk.CTkFrame(cards_frame, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
            card.grid(row=0, column=col, padx=3, sticky="nsew")
            ctk.CTkLabel(card, text=value, font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"), text_color=COLOR_ACCENT).pack(padx=8, pady=(8, 0))
            ctk.CTkLabel(card, text=label, font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLOR_DIM).pack(padx=8, pady=(0, 8))

        # ── Week summary line ──
        parts = []
        if stats["week_sessions"] > 0:
            parts.append(f"{stats['week_sessions']} session{'s' if stats['week_sessions'] != 1 else ''}")
        if stats["week_notes"] > 0:
            parts.append(f"{stats['week_notes']} notes")
        if stats["week_decisions"] > 0:
            parts.append(f"{stats['week_decisions']} decisions")
        if parts:
            summary_text = "This week: " + " \u00b7 ".join(parts)
            ctk.CTkLabel(
                self._bottom_scroll, text=summary_text,
                font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_SEC,
            ).pack(anchor="w", padx=8, pady=(0, 4))

        # ── Top apps this week ──
        if stats["top_apps"]:
            apps_text = "Top apps: " + ", ".join(
                app for app, _cnt in stats["top_apps"]
            )
            ctk.CTkLabel(
                self._bottom_scroll, text=apps_text,
                font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLOR_DIM,
            ).pack(anchor="w", padx=8, pady=(0, 8))

        # ── Recent sessions ──
        recent = stats["recent_sessions"]
        if recent:
            ctk.CTkLabel(
                self._bottom_scroll, text="RECENT SESSIONS",
                font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLOR_DIM,
            ).pack(anchor="w", padx=6, pady=(4, 3))

            for s in recent[:5]:
                card = ctk.CTkFrame(self._bottom_scroll, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
                card.pack(fill="x", pady=2, padx=2)

                info_frame = ctk.CTkFrame(card, fg_color="transparent")
                info_frame.pack(side="left", fill="both", expand=True, padx=(10, 4), pady=6)

                # Project name + date
                top_row = ctk.CTkFrame(info_frame, fg_color="transparent")
                top_row.pack(fill="x")
                ctk.CTkLabel(
                    top_row, text=s["project_name"],
                    font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                    text_color=COLOR_TEXT, anchor="w",
                ).pack(side="left")

                # Relative date
                try:
                    started = datetime.strptime(s["started_at"], "%Y-%m-%d %H:%M:%S")
                    delta = datetime.now() - started
                    if delta.days == 0:
                        rel = "today"
                    elif delta.days == 1:
                        rel = "yesterday"
                    else:
                        rel = f"{delta.days}d ago"
                except (ValueError, TypeError):
                    rel = s["started_at"][:10]
                ctk.CTkLabel(
                    top_row, text=rel,
                    font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLOR_DIM,
                ).pack(side="right")

                # Duration + note count
                duration_text = ""
                if s["ended_at"]:
                    try:
                        start_dt = datetime.strptime(s["started_at"], "%Y-%m-%d %H:%M:%S")
                        end_dt = datetime.strptime(s["ended_at"], "%Y-%m-%d %H:%M:%S")
                        dur_min = int((end_dt - start_dt).total_seconds()) // 60
                        h, m = divmod(dur_min, 60)
                        duration_text = f"{h}h {m:02d}m" if h > 0 else f"{m}m"
                    except (ValueError, TypeError):
                        pass
                meta_parts = []
                if duration_text:
                    meta_parts.append(duration_text)
                meta_parts.append(f"{s['note_count']} notes")
                ctk.CTkLabel(
                    info_frame, text=" \u00b7 ".join(meta_parts),
                    font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLOR_TEXT_SEC, anchor="w",
                ).pack(fill="x")

                # View button
                sid = s["id"]
                ctk.CTkButton(
                    card, text="View", width=50, height=26,
                    font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                    corner_radius=12, fg_color=COLOR_BTN_SECONDARY_BG,
                    hover_color=COLOR_BTN_SECONDARY_HOVER, text_color=COLOR_TEXT,
                    border_width=1, border_color=COLOR_BORDER,
                    command=lambda s_id=sid: self.app.navigate_to_summary(s_id),
                ).pack(side="right", padx=8, pady=6)

        # ── Total all-time ──
        if stats["total_seconds"] > 0:
            total_text = f"All time: {_format_duration(stats['total_seconds'])} logged"
            ctk.CTkLabel(
                self._bottom_scroll, text=total_text,
                font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLOR_DIM,
            ).pack(anchor="w", padx=8, pady=(8, 4))

    def on_show(self):
        """Called when this frame becomes visible."""
        active = get_active_session_info()
        if active:
            self._refresh_live_feed(active["session_id"])
        else:
            self._show_idle_dashboard()
        self._project_combo.configure(values=self._get_project_names())


# ── View 2: Project ─────────────────────────────────────

class ProjectFrame(ctk.CTkFrame):
    def __init__(self, parent, app: EngLogApp):
        super().__init__(parent, fg_color=COLOR_BG, corner_radius=0)
        self.app = app
        self._save_debounce_job = None

        # ── Project selector ──
        sel_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        sel_frame.pack(fill="x", padx=12, pady=(10, 5))

        ctk.CTkLabel(sel_frame, text="Project:", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT).pack(side="left", padx=(12, 4), pady=8)
        self._project_combo = ctk.CTkComboBox(
            sel_frame, values=[], font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            corner_radius=10, command=self._on_project_selected,
        )
        self._project_combo.pack(side="left", fill="x", expand=True, padx=4, pady=8)
        self._project_combo.set("")

        self._delete_proj_btn = ctk.CTkButton(
            sel_frame, text="Delete", width=54, height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color="transparent", hover_color=COLOR_BTN_DANGER_HOVER,
            text_color=COLOR_RED, border_width=1, border_color=COLOR_RED,
            corner_radius=16, command=self._delete_project,
        )
        self._delete_proj_btn.pack(side="right", padx=(2, 12), pady=8)

        self._rename_proj_btn = ctk.CTkButton(
            sel_frame, text="Rename", width=58, height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color=COLOR_BTN_SECONDARY_BG, hover_color=COLOR_BTN_SECONDARY_HOVER,
            text_color=COLOR_TEXT, border_width=1, border_color=COLOR_BORDER,
            corner_radius=16, command=self._rename_project,
        )
        self._rename_proj_btn.pack(side="right", padx=2, pady=8)

        self._saved_label = ctk.CTkLabel(sel_frame, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM)
        self._saved_label.pack(side="right", padx=(0, 4))

        # ── Tabview: Context / Rules / Examples ──
        self._tabview = ctk.CTkTabview(self, height=180, corner_radius=12, border_width=1, border_color=COLOR_BORDER, segmented_button_selected_color=COLOR_ACCENT)
        self._tabview.pack(fill="x", padx=12, pady=5)

        tab_ctx = self._tabview.add("Context")
        tab_rules = self._tabview.add("Rules (optional)")
        tab_examples = self._tabview.add("Examples (optional)")

        # — Context tab —
        ctk.CTkLabel(
            tab_ctx,
            text="Describe what this project is about. The AI uses this to interpret sessions more precisely.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM, wraplength=370, anchor="w",
        ).pack(anchor="w", padx=4, pady=(0, 4))

        self._context_text = ctk.CTkTextbox(
            tab_ctx, font=ctk.CTkFont(family=FONT_FAMILY, size=11), height=100,
            corner_radius=10, border_width=1, border_color=COLOR_BORDER,
        )
        self._context_text.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self._context_text.bind("<KeyRelease>", self._on_field_keyrelease)

        # — Rules tab —
        ctk.CTkLabel(
            tab_rules,
            text="Add project-specific rules for the AI (e.g. \"always mention file names\", "
                 "\"distinguish meetings from solo work\", \"use French for the summary\").",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM, wraplength=370, anchor="w",
        ).pack(anchor="w", padx=4, pady=(0, 4))

        self._rules_text = ctk.CTkTextbox(
            tab_rules, font=ctk.CTkFont(family=FONT_FAMILY, size=11), height=100,
            corner_radius=10, border_width=1, border_color=COLOR_BORDER,
        )
        self._rules_text.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self._rules_text.bind("<KeyRelease>", self._on_field_keyrelease)

        # — Examples tab —
        ctk.CTkLabel(
            tab_examples,
            text="Edit this example or replace with your own. The AI will match this style and detail level.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM, wraplength=370, anchor="w",
        ).pack(anchor="w", padx=4, pady=(0, 4))

        self._examples_text = ctk.CTkTextbox(
            tab_examples, font=ctk.CTkFont(family=FONT_FAMILY, size=11), height=100,
            corner_radius=10, border_width=1, border_color=COLOR_BORDER,
        )
        self._examples_text.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self._examples_text.bind("<KeyRelease>", self._on_field_keyrelease)

        # ── Project status (AI-generated) ──
        status_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        status_frame.pack(fill="both", expand=True, padx=12, pady=5)

        status_header = ctk.CTkFrame(status_frame, fg_color="transparent")
        status_header.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(status_header, text="Project Status", font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"), text_color=COLOR_TEXT).pack(side="left")

        self._gen_status_btn = ctk.CTkButton(
            status_header, text="Generate", width=70, height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            corner_radius=20, fg_color=COLOR_ACCENT, hover_color="#1E3A6E",
            command=self._generate_status,
        )
        self._gen_status_btn.pack(side="right", padx=(4, 0))

        self._regen_status_btn = ctk.CTkButton(
            status_header, text="Refresh", width=60, height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            corner_radius=16, fg_color=COLOR_BTN_SECONDARY_BG,
            hover_color=COLOR_BTN_SECONDARY_HOVER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER,
            command=self._generate_status,
        )
        self._regen_status_btn.pack(side="right")

        ctk.CTkLabel(
            status_frame,
            text="AI-generated summary of where this project currently stands.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM, wraplength=370, anchor="w",
        ).pack(anchor="w", padx=12, pady=(0, 4))

        self._status_text = ctk.CTkTextbox(
            status_frame, font=ctk.CTkFont(family=FONT_MONO, size=11),
            corner_radius=10, border_width=1, border_color=COLOR_BORDER,
            state="disabled",
        )
        self._status_text.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        _configure_md_tags(self._status_text)

        # ── Progress bar ──
        self._progress = ctk.CTkProgressBar(status_frame, mode="indeterminate", height=4, progress_color=COLOR_ACCENT)
        # Not packed by default — shown during generation

        self._status_info = ctk.CTkLabel(status_frame, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM)
        self._status_info.pack(anchor="w", padx=12, pady=(0, 8))

    def on_show(self):
        self._refresh_project_list()

    def _refresh_project_list(self):
        projects = db.list_projects()
        names = [p["name"] for p in projects]
        self._project_combo.configure(values=names)
        current = self._project_combo.get()
        if not current and names:
            self._project_combo.set(names[0])
            self._on_project_selected(names[0])
        elif current and current in names:
            self._on_project_selected(current)

    def _on_project_selected(self, value: str):
        project = db.get_project(value)
        if not project:
            return

        # Load all three fields
        for widget, key, default in [
            (self._context_text, "context", ""),
            (self._rules_text, "rules", ""),
            (self._examples_text, "examples", DEFAULT_EXAMPLE),
        ]:
            widget.delete("1.0", "end")
            text = project.get(key) or default
            if text:
                widget.insert("1.0", text)

        self._saved_label.configure(text="")

        # Load cached status
        status = project.get("status") or ""
        self._set_status_text(status if status else "No status yet. Click 'Generate' to create one.")

    def _set_status_text(self, text: str):
        self._status_text.configure(state="normal")
        self._status_text.delete("1.0", "end")
        _render_markdown(self._status_text, text)
        self._status_text.configure(state="disabled")

    def _on_field_keyrelease(self, event):
        """Auto-save all fields after a brief pause in typing."""
        if self._save_debounce_job:
            self.after_cancel(self._save_debounce_job)
        self._save_debounce_job = self.after(1000, self._save_all_fields)

    def _save_all_fields(self):
        project_name = self._project_combo.get()
        if not project_name:
            return
        db.update_project_context(project_name, self._context_text.get("1.0", "end").strip())
        db.update_project_rules(project_name, self._rules_text.get("1.0", "end").strip())
        db.update_project_examples(project_name, self._examples_text.get("1.0", "end").strip())
        self._saved_label.configure(text="Saved", text_color=COLOR_GREEN)
        self.after(2000, lambda: self._saved_label.configure(text=""))

    def _generate_status(self):
        project_name = self._project_combo.get()
        if not project_name:
            return

        from englog.summary import generate_project_status, check_ollama

        if not check_ollama():
            self._status_info.configure(text="Ollama not available. Start Ollama and try again.", text_color=COLOR_RED)
            return

        # Save any pending edits first
        self._save_all_fields()

        self._status_info.configure(text="Generating status...", text_color=COLOR_DIM)
        self._progress.pack(fill="x", padx=10, pady=2, before=self._status_info)
        self._progress.start()
        self._gen_status_btn.configure(state="disabled")
        self._regen_status_btn.configure(state="disabled")

        def work():
            return generate_project_status(project_name)

        def done(result, err):
            self._progress.stop()
            self._progress.pack_forget()
            self._gen_status_btn.configure(state="normal")
            self._regen_status_btn.configure(state="normal")
            if err:
                self._status_info.configure(text=f"Error: {err}", text_color=COLOR_RED)
            elif result and result.startswith("Error"):
                self._set_status_text(result)
                self._status_info.configure(text="Generation failed", text_color=COLOR_RED)
            else:
                self._set_status_text(result or "")
                self._status_info.configure(text="Status updated.", text_color=COLOR_GREEN)

        self.app._run_in_background(work, done)

    def _rename_project(self):
        project_name = self._project_combo.get()
        if not project_name:
            return
        project = db.get_project(project_name)
        if not project:
            return

        dialog = ctk.CTkInputDialog(text=f"New name for '{project_name}':", title="Rename Project")
        new_name = dialog.get_input()
        if not new_name or new_name.strip() == "" or new_name.strip() == project_name:
            return

        new_name = new_name.strip()
        result = db.rename_project(project["id"], new_name)
        if "error" in result:
            self._saved_label.configure(text=result["error"], text_color=COLOR_RED)
            return

        # Update the pidfile if this project has an active session
        active = get_active_session_info()
        if active and active.get("project") == project_name:
            _save_active_session(active["session_id"], new_name)

        self._saved_label.configure(text="Renamed", text_color=COLOR_GREEN)
        self.after(2000, lambda: self._saved_label.configure(text=""))
        self._refresh_project_list()
        self._project_combo.set(new_name)
        self._on_project_selected(new_name)

    def _delete_project(self):
        from tkinter import messagebox
        project_name = self._project_combo.get()
        if not project_name:
            return
        project = db.get_project(project_name)
        if not project:
            return

        sessions = db.list_sessions(project_name=project_name, limit=1000)
        n_sessions = len(sessions)
        confirm = messagebox.askyesno(
            "Delete Project",
            f"Permanently delete '{project_name}'?\n\n"
            f"This will remove {n_sessions} session(s) and all associated\n"
            f"notes, captures, and screenshots.\n\n"
            f"This cannot be undone.",
        )
        if not confirm:
            return

        result = db.delete_project(project["id"])
        if "error" in result:
            self._saved_label.configure(text=result["error"], text_color=COLOR_RED)
            return

        self._saved_label.configure(text="Deleted", text_color=COLOR_ORANGE)
        self.after(2000, lambda: self._saved_label.configure(text=""))
        self._refresh_project_list()
        # Clear fields if no projects left
        names = [p["name"] for p in db.list_projects()]
        if not names:
            self._project_combo.set("")
            for widget in (self._context_text, self._rules_text, self._examples_text):
                widget.delete("1.0", "end")
            self._set_status_text("No projects yet.")


# ── View 3: History ──────────────────────────────────────

class HistoryFrame(ctk.CTkFrame):
    def __init__(self, parent, app: EngLogApp):
        super().__init__(parent, fg_color=COLOR_BG, corner_radius=0)
        self.app = app

        # ── Filter bar ──
        filter_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        filter_frame.pack(fill="x", padx=12, pady=(10, 5))

        ctk.CTkLabel(filter_frame, text="Project:", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT).pack(side="left", padx=(12, 4))
        self._project_filter = ctk.CTkComboBox(
            filter_frame, width=120, values=["All"], font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            corner_radius=10, command=lambda _: self._load_sessions(),
        )
        self._project_filter.pack(side="left", padx=4, pady=8)
        self._project_filter.set("All")

        ctk.CTkLabel(filter_frame, text="Search:", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT).pack(side="left", padx=(10, 4))
        self._search_entry = ctk.CTkEntry(filter_frame, placeholder_text="Search notes...", width=140, font=ctk.CTkFont(family=FONT_FAMILY, size=12), corner_radius=10)
        self._search_entry.pack(side="left", padx=4, pady=8, fill="x", expand=True)
        self._search_entry.bind("<Return>", lambda e: self._load_sessions())

        search_btn = ctk.CTkButton(
            filter_frame, text="Go", width=40, height=28,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            corner_radius=16, fg_color=COLOR_BTN_SECONDARY_BG,
            hover_color=COLOR_BTN_SECONDARY_HOVER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER,
            command=self._load_sessions,
        )
        search_btn.pack(side="right", padx=(4, 12), pady=8)

        # ── Sessions list ──
        self._sessions_scroll = ctk.CTkScrollableFrame(self, fg_color=COLOR_BG, corner_radius=0)
        self._sessions_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    def on_show(self):
        # Refresh project list
        projects = ["All"] + [p["name"] for p in db.list_projects()]
        self._project_filter.configure(values=projects)
        self._load_sessions()

    def _load_sessions(self):
        for w in self._sessions_scroll.winfo_children():
            w.destroy()

        project = self._project_filter.get()
        project_name = None if project == "All" else project
        query = self._search_entry.get().strip()

        if query:
            # Search mode: find sessions with matching notes
            results = db.search_notes(query, project_name=project_name)
            session_ids = list(dict.fromkeys(r.get("session_id") for r in results))
            sessions = []
            for sid in session_ids[:30]:
                s = db.get_session(sid)
                if s:
                    sessions.append(s)
        else:
            sessions = db.list_sessions(project_name=project_name, limit=30)

        if not sessions:
            ctk.CTkLabel(
                self._sessions_scroll, text="No sessions found.",
                font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_DIM,
            ).pack(pady=20)
            return

        for s in sessions:
            self._create_session_card(s)

    def _create_session_card(self, session: dict):
        card = ctk.CTkFrame(self._sessions_scroll, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        card.pack(fill="x", pady=3)

        # Row 1: ID, project, date
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            row1, text=f"#{session['id']}", font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"), text_color=COLOR_ACCENT,
        ).pack(side="left")
        ctk.CTkLabel(
            row1, text=session.get("project_name", "?"), font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT,
        ).pack(side="left", padx=8)

        date_str = session["started_at"][:10]
        ctk.CTkLabel(row1, text=date_str, font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM).pack(side="right")

        # Row 2: duration, notes count
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=(0, 2))

        duration = ""
        if session.get("ended_at"):
            try:
                fmt = "%Y-%m-%d %H:%M:%S"
                start_dt = datetime.strptime(session["started_at"], fmt)
                end_dt = datetime.strptime(session["ended_at"], fmt)
                total_min = int((end_dt - start_dt).total_seconds() / 60)
                h, m = divmod(total_min, 60)
                duration = f"{h}h {m:02d}m"
            except Exception:
                duration = ""
        else:
            duration = "active"

        notes_count = len(db.get_session_notes(session["id"]))
        info_text = f"{duration} | {notes_count} notes" if duration else f"{notes_count} notes"
        ctk.CTkLabel(row2, text=info_text, font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM).pack(side="left")

        # Row 3: summary preview
        summary = session.get("summary") or ""
        if summary:
            preview = summary.replace("\n", " ")[:100]
            if len(summary) > 100:
                preview += "..."
            ctk.CTkLabel(
                card, text=preview, font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_SEC,
                anchor="w", wraplength=370,
            ).pack(padx=12, pady=(0, 4), fill="x")

        # Buttons row
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(anchor="e", padx=12, pady=(0, 8))

        ctk.CTkButton(
            btn_row, text="View", width=50, height=24,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            corner_radius=16, fg_color=COLOR_ACCENT,
            hover_color="#3D5FA0", text_color="#FFFFFF",
            command=lambda sid=session["id"]: self.app.navigate_to_summary(sid),
        ).pack(side="left")

        # Delete button (only for non-active sessions) — ghost/danger style
        if not session.get("is_active"):
            ctk.CTkButton(
                btn_row, text="Delete", width=55, height=24,
                font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                fg_color="transparent", hover_color=COLOR_BTN_DANGER_HOVER,
                text_color=COLOR_RED, border_width=1, border_color=COLOR_BORDER,
                corner_radius=16,
                command=lambda sid=session["id"], pname=session.get("project_name", "?"): self._delete_session(sid, pname),
            ).pack(side="left", padx=(4, 0))

    def _delete_session(self, session_id: int, project_name: str):
        from tkinter import messagebox
        confirm = messagebox.askyesno(
            "Delete Session",
            f"Permanently delete session #{session_id} ({project_name})?\n\n"
            f"All notes, captures, and screenshots will be removed.\n"
            f"This cannot be undone.",
        )
        if not confirm:
            return
        result = db.delete_session(session_id)
        if "error" in result:
            from tkinter import messagebox as mb
            mb.showerror("Error", result["error"])
            return
        self._load_sessions()


# ── View 4: Summary & Export ─────────────────────────────

class SummaryFrame(ctk.CTkFrame):
    def __init__(self, parent, app: EngLogApp):
        super().__init__(parent, fg_color=COLOR_BG, corner_radius=0)
        self.app = app
        self._current_session_id: Optional[int] = None

        # ── Session selector ──
        sel_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        sel_frame.pack(fill="x", padx=12, pady=(10, 5))

        ctk.CTkLabel(sel_frame, text="Session:", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT).pack(side="left", padx=(12, 4), pady=8)
        self._session_combo = ctk.CTkComboBox(
            sel_frame, values=[], font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            corner_radius=10, command=self._on_session_selected,
        )
        self._session_combo.pack(side="left", fill="x", expand=True, padx=4, pady=8)
        self._session_combo.set("")

        # ── Model override for regeneration ──
        model_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        model_frame.pack(fill="x", padx=12, pady=(0, 5))

        ctk.CTkLabel(model_frame, text="Model:", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT).pack(side="left", padx=(12, 4), pady=6)
        self._model_combo = ctk.CTkComboBox(
            model_frame, values=[], width=140, font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            corner_radius=10, command=self._on_model_override,
        )
        self._model_combo.pack(side="left", padx=4, pady=6)
        self._model_combo.set("")

        self._model_hint = ctk.CTkLabel(
            model_frame, text="(current)", font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLOR_DIM,
        )
        self._model_hint.pack(side="left", padx=4)

        # ── Summary display ──
        self._summary_text = ctk.CTkTextbox(
            self, font=ctk.CTkFont(family=FONT_MONO, size=11),
            corner_radius=10, border_width=1, border_color=COLOR_BORDER,
            state="disabled",
        )
        self._summary_text.pack(fill="both", expand=True, padx=12, pady=5)
        _configure_md_tags(self._summary_text)

        # ── Progress bar ──
        self._progress = ctk.CTkProgressBar(self, mode="indeterminate", height=4, progress_color=COLOR_ACCENT)
        # Not packed by default — shown during generation

        # ── Buttons ──
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(5, 4))

        self._gen_btn = ctk.CTkButton(
            btn_frame, text="Generate Summary",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            height=34, corner_radius=20, fg_color=COLOR_ACCENT, hover_color="#1E3A6E",
            command=self._generate_summary,
        )
        self._gen_btn.pack(side="left", padx=(0, 4))

        self._regen_btn = ctk.CTkButton(
            btn_frame, text="Regenerate",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            height=34, corner_radius=16, fg_color=COLOR_BTN_SECONDARY_BG,
            hover_color=COLOR_BTN_SECONDARY_HOVER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER,
            command=self._regenerate_summary,
        )
        self._regen_btn.pack(side="left", padx=4)

        self._export_btn = ctk.CTkButton(
            btn_frame, text="Export XLSX",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            height=34, corner_radius=20, fg_color=COLOR_GREEN, hover_color="#1B8A4A",
            command=self._export_xlsx,
        )
        self._export_btn.pack(side="left", padx=4)

        self._open_btn = ctk.CTkButton(
            btn_frame, text="Open File",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            height=34, corner_radius=16, fg_color=COLOR_BTN_SECONDARY_BG,
            hover_color=COLOR_BTN_SECONDARY_HOVER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER,
            command=self._open_exported_file, state="disabled",
        )
        self._open_btn.pack(side="left", padx=4)

        self._last_export_path: Optional[str] = None
        self._status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM)
        self._status_label.pack(anchor="w", padx=14, pady=(0, 4))

    def on_show(self):
        self._refresh_session_list()
        self._refresh_model_list()

    def _refresh_session_list(self):
        sessions = db.list_sessions(limit=30)
        values = []
        for s in sessions:
            label = f"#{s['id']} - {s.get('project_name', '?')} - {s['started_at'][:10]}"
            values.append(label)
        self._session_combo.configure(values=values)
        if values and not self._current_session_id:
            self._session_combo.set(values[0])
            self._on_session_selected(values[0])

    def _refresh_model_list(self):
        """Populate model dropdown from Ollama (installed models only)."""
        import englog.config as config

        def work():
            import requests
            try:
                resp = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5)
                if resp.status_code == 200:
                    return sorted({m["name"].split(":")[0] for m in resp.json().get("models", [])})
            except Exception:
                pass
            return []

        def done(models, err):
            if models:
                self._model_combo.configure(values=models)
                self._model_combo.set(config.OLLAMA_MODEL)
                self._model_hint.configure(text="(current)")

        self.app._run_in_background(work, done)

    def _on_model_override(self, value: str):
        """Update hint when a different model is selected."""
        import englog.config as config
        if value == config.OLLAMA_MODEL:
            self._model_hint.configure(text="(current)")
        else:
            profile = MODEL_PROFILES.get(value)
            hint = profile["desc"][:40] + "..." if profile else "will switch for this generation"
            self._model_hint.configure(text=hint)

    def select_session(self, session_id: int):
        """Called from HistoryFrame to pre-select a session."""
        self._refresh_session_list()
        for val in self._session_combo.cget("values"):
            if val.startswith(f"#{session_id} "):
                self._session_combo.set(val)
                self._on_session_selected(val)
                return

    def _on_session_selected(self, value: str):
        try:
            sid = int(value.split("#")[1].split(" ")[0])
        except (IndexError, ValueError):
            return
        self._current_session_id = sid
        session = db.get_session(sid)
        self._set_summary_text(session.get("summary") or "No summary yet. Click 'Generate Summary'.")

    def _set_summary_text(self, text: str):
        """Render text into the summary textbox with Markdown formatting."""
        self._summary_text.configure(state="normal")
        self._summary_text.delete("1.0", "end")
        _render_markdown(self._summary_text, text)
        self._summary_text.configure(state="disabled")

    def _show_progress(self, msg: str):
        self._status_label.configure(text=msg)
        self._progress.pack(fill="x", padx=10, pady=2, before=self._status_label)
        self._progress.start()
        self._gen_btn.configure(state="disabled")
        self._regen_btn.configure(state="disabled")
        self._export_btn.configure(state="disabled")

    def _hide_progress(self):
        self._progress.stop()
        self._progress.pack_forget()
        self._gen_btn.configure(state="normal")
        self._regen_btn.configure(state="normal")
        self._export_btn.configure(state="normal")

    def _apply_model_override(self) -> Optional[str]:
        """Temporarily switch to the selected model. Returns the previous model name."""
        import englog.config as config
        selected = self._model_combo.get().split("  (")[0].strip()
        if not selected or selected == config.OLLAMA_MODEL:
            return None  # no override
        previous = config.OLLAMA_MODEL
        config.OLLAMA_MODEL = selected
        # Auto-adjust context window
        profile = MODEL_PROFILES.get(selected)
        if profile:
            config.OLLAMA_NUM_CTX = profile["ctx"]
        return previous

    def _restore_model(self, previous: Optional[str]):
        """Restore the model after a one-shot override."""
        if previous is None:
            return
        import englog.config as config
        config.OLLAMA_MODEL = previous
        profile = MODEL_PROFILES.get(previous)
        if profile:
            config.OLLAMA_NUM_CTX = profile["ctx"]

    def _generate_summary(self):
        if not self._current_session_id:
            return
        session = db.get_session(self._current_session_id)
        if session and session.get("summary"):
            self._set_summary_text(session["summary"])
            self._status_label.configure(text="Summary already exists. Use 'Regenerate' to replace.")
            return
        self._do_generate()

    def _regenerate_summary(self):
        if not self._current_session_id:
            return
        self._do_generate()

    def _do_generate(self):
        from englog.summary import generate_summary_stream, check_ollama
        sid = self._current_session_id
        previous_model = self._apply_model_override()
        import englog.config as config
        model_used = config.OLLAMA_MODEL

        if not check_ollama():
            self._restore_model(previous_model)
            self._status_label.configure(text="Ollama not available. Start Ollama and try again.", text_color=COLOR_RED)
            return

        self._show_progress(f"Generating summary with {model_used}...")
        # Clear the textbox and enable for streaming writes
        self._summary_text.configure(state="normal")
        self._summary_text.delete("1.0", "end")
        self._summary_text.configure(state="disabled")

        import queue
        token_queue = queue.Queue()

        def stream_worker():
            try:
                for token in generate_summary_stream(sid):
                    token_queue.put(("token", token))
                token_queue.put(("done", None))
            except Exception as e:
                token_queue.put(("error", e))

        def poll_tokens():
            try:
                while True:
                    msg_type, value = token_queue.get_nowait()
                    if msg_type == "token":
                        # Check if it's an error message (first token)
                        current_text = self._summary_text.get("1.0", "end").strip()
                        if not current_text and value.startswith("Error"):
                            self._summary_text.configure(state="normal")
                            self._summary_text.insert("end", value)
                            self._summary_text.configure(state="disabled")
                            # Don't stop yet — more tokens may follow
                        else:
                            self._summary_text.configure(state="normal")
                            self._summary_text.insert("end", value)
                            self._summary_text.see("end")
                            self._summary_text.configure(state="disabled")
                    elif msg_type == "done":
                        self._restore_model(previous_model)
                        self._hide_progress()
                        final_text = self._summary_text.get("1.0", "end").strip()
                        if final_text.startswith("Error"):
                            self._status_label.configure(text="Generation failed", text_color=COLOR_RED)
                        else:
                            # Re-render with Markdown formatting
                            self._set_summary_text(final_text)
                            self._status_label.configure(text=f"Summary generated with {model_used}.", text_color=COLOR_GREEN)
                        return
                    elif msg_type == "error":
                        self._restore_model(previous_model)
                        self._hide_progress()
                        self._status_label.configure(text=f"Error: {value}", text_color=COLOR_RED)
                        return
            except queue.Empty:
                pass
            self.after(50, poll_tokens)

        threading.Thread(target=stream_worker, daemon=True).start()
        self.after(50, poll_tokens)

    def _export_xlsx(self):
        if not self._current_session_id:
            return
        from englog.export import export_xlsx
        from englog.summary import check_ollama
        sid = self._current_session_id
        previous_model = self._apply_model_override()
        import englog.config as config
        model_used = config.OLLAMA_MODEL
        ollama_ok = check_ollama()

        if not ollama_ok:
            self._restore_model(previous_model)

        self._show_progress(f"Exporting timesheet with {model_used}...")

        # Build a model-tagged output path so different models don't overwrite each other
        session = db.get_session(sid)
        if session:
            from englog.config import DATA_DIR
            exports_dir = DATA_DIR / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            date_str = session["started_at"][:10].replace("-", "")
            output_path = str(exports_dir / f"englog_{session['project_name']}_{date_str}_s{sid}_{model_used}.xlsx")
        else:
            output_path = None

        def work():
            return export_xlsx(sid, output_path=output_path, ollama_available=ollama_ok)

        def done(result, err):
            self._restore_model(previous_model)
            self._hide_progress()
            if err:
                self._status_label.configure(text=f"Export failed: {err}", text_color=COLOR_RED)
            else:
                self._last_export_path = result
                self._open_btn.configure(state="normal")
                self._status_label.configure(text=f"Exported ({model_used}): {result}", text_color=COLOR_GREEN)

        self.app._run_in_background(work, done)

    def _open_exported_file(self):
        if self._last_export_path and os.path.exists(self._last_export_path):
            os.startfile(self._last_export_path)


# ── View 5: Settings ─────────────────────────────────────

class SettingsFrame(ctk.CTkFrame):
    def __init__(self, parent, app: EngLogApp):
        super().__init__(parent, fg_color=COLOR_BG, corner_radius=0)
        self.app = app

        # ── Ollama status ──
        ollama_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        ollama_frame.pack(fill="x", padx=12, pady=(10, 5))

        row = ctk.CTkFrame(ollama_frame, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=8)

        self._ollama_dot_frame = ctk.CTkFrame(row, width=10, height=10, corner_radius=5, fg_color=COLOR_DIM)
        self._ollama_dot_frame.pack(side="left", padx=(0, 6))
        self._ollama_dot_frame.pack_propagate(False)
        self._ollama_status = ctk.CTkLabel(row, text="Ollama: checking...", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT)
        self._ollama_status.pack(side="left", padx=4)

        refresh_btn = ctk.CTkButton(
            row, text="Refresh", width=60, height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            corner_radius=16, fg_color=COLOR_BTN_SECONDARY_BG,
            hover_color=COLOR_BTN_SECONDARY_HOVER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER,
            command=self._check_ollama,
        )
        refresh_btn.pack(side="right")

        # ── Model selector ──
        model_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        model_frame.pack(fill="x", padx=12, pady=5)

        ctk.CTkLabel(model_frame, text="Model:", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT).pack(anchor="w", padx=12, pady=(8, 2))
        self._model_combo = ctk.CTkComboBox(
            model_frame, values=[],
            font=ctk.CTkFont(family=FONT_FAMILY, size=12), corner_radius=10,
            command=self._on_model_changed,
        )
        self._model_combo.pack(padx=12, pady=(2, 2), fill="x")

        self._model_desc = ctk.CTkLabel(
            model_frame, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM,
            wraplength=370, anchor="w",
        )
        self._model_desc.pack(anchor="w", padx=12, pady=(0, 4))

        self._model_ctx_label = ctk.CTkLabel(
            model_frame, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLOR_DIM,
        )
        self._model_ctx_label.pack(anchor="w", padx=12, pady=(0, 8))

        # ── Screenshot settings ──
        capture_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        capture_frame.pack(fill="x", padx=12, pady=5)

        # Interval slider
        ctk.CTkLabel(capture_frame, text="Screenshot Interval:", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT).pack(anchor="w", padx=12, pady=(8, 0))
        interval_row = ctk.CTkFrame(capture_frame, fg_color="transparent")
        interval_row.pack(fill="x", padx=12, pady=2)
        import englog.config as _cfg
        self._interval_slider = ctk.CTkSlider(
            interval_row, from_=10, to=120, number_of_steps=22,
            button_color=COLOR_ACCENT, progress_color=COLOR_ACCENT,
            command=self._on_interval_changed,
        )
        self._interval_slider.set(_cfg.SCREENSHOT_INTERVAL_SECONDS)
        self._interval_slider.pack(side="left", fill="x", expand=True)
        self._interval_label = ctk.CTkLabel(interval_row, text=f"{_cfg.SCREENSHOT_INTERVAL_SECONDS}s", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT, width=40)
        self._interval_label.pack(side="right", padx=4)

        # Quality slider
        ctk.CTkLabel(capture_frame, text="Screenshot Quality:", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT).pack(anchor="w", padx=12, pady=(4, 0))
        quality_row = ctk.CTkFrame(capture_frame, fg_color="transparent")
        quality_row.pack(fill="x", padx=12, pady=(2, 0))
        self._quality_slider = ctk.CTkSlider(
            quality_row, from_=10, to=95, number_of_steps=17,
            button_color=COLOR_ACCENT, progress_color=COLOR_ACCENT,
            command=self._on_quality_changed,
        )
        self._quality_slider.set(_cfg.SCREENSHOT_QUALITY)
        self._quality_slider.pack(side="left", fill="x", expand=True)
        self._quality_label = ctk.CTkLabel(quality_row, text=str(_cfg.SCREENSHOT_QUALITY), font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT, width=40)
        self._quality_label.pack(side="right", padx=4)

        # Storage estimate hint (updated dynamically)
        self._capture_hint = ctk.CTkLabel(
            capture_frame, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLOR_DIM,
            anchor="w",
        )
        self._capture_hint.pack(anchor="w", padx=14, pady=(0, 8))

        # Cache for measured screenshot sizes (quality -> KB), populated lazily
        self._screenshot_size_kb: dict[int, float] = {}
        self._sizes_measured = False

        # ── Data directory ──
        data_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        data_frame.pack(fill="x", padx=12, pady=5)

        ctk.CTkLabel(data_frame, text="Data Directory:", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT).pack(anchor="w", padx=12, pady=(8, 2))
        dir_row = ctk.CTkFrame(data_frame, fg_color="transparent")
        dir_row.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(dir_row, text=str(DATA_DIR), font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            dir_row, text="Open", width=50, height=24,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            corner_radius=16, fg_color=COLOR_BTN_SECONDARY_BG,
            hover_color=COLOR_BTN_SECONDARY_HOVER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER,
            command=lambda: os.startfile(str(DATA_DIR)) if os.path.isdir(str(DATA_DIR)) else None,
        ).pack(side="right")

        # ── Reset to defaults ──
        ctk.CTkButton(
            self, text="Reset to Defaults", width=130, height=30,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            corner_radius=16, fg_color=COLOR_BTN_SECONDARY_BG,
            hover_color=COLOR_BTN_SECONDARY_HOVER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER,
            command=self._reset_to_defaults,
        ).pack(anchor="w", padx=12, pady=(8, 0))

        # ── Footer ──
        ctk.CTkLabel(self, text="Settings apply to new sessions.", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_DIM).pack(anchor="w", padx=16, pady=(8, 2))
        ctk.CTkLabel(self, text="EngLog v1.0.0", font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color="#C0C0C0").pack(anchor="w", padx=16, pady=(0, 10))

    def on_show(self):
        self._check_ollama()
        if not self._sizes_measured:
            self._measure_screenshot_sizes()
        else:
            self._update_capture_hint()

    def _measure_screenshot_sizes(self):
        """Take one screenshot and measure JPEG size at every quality step."""
        def work():
            import mss
            from PIL import Image
            from englog.config import SCREENSHOT_SCALE
            import io
            with mss.mss() as sct:
                raw = sct.grab(sct.monitors[1])
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            new_w = int(img.width * SCREENSHOT_SCALE)
            new_h = int(img.height * SCREENSHOT_SCALE)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            sizes = {}
            for q in range(10, 100, 5):
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=q)
                sizes[q] = round(buf.tell() / 1024, 1)
            return sizes

        def done(sizes, err):
            if sizes and not err:
                self._screenshot_size_kb = sizes
                self._sizes_measured = True
                self._update_capture_hint()

        self.app._run_in_background(work, done)

    def _update_capture_hint(self):
        """Update the storage estimate label based on current quality and interval."""
        quality = int(self._quality_slider.get())
        interval = int(self._interval_slider.get())

        if not self._screenshot_size_kb:
            self._capture_hint.configure(text="Measuring screenshot sizes...")
            return

        # Snap quality to nearest measured step
        measured_q = min(self._screenshot_size_kb, key=lambda q: abs(q - quality))
        size_kb = self._screenshot_size_kb[measured_q]

        shots_per_hour = 3600 / interval
        mb_per_hour = (size_kb * shots_per_hour) / 1024
        mb_per_8h = mb_per_hour * 8

        self._capture_hint.configure(
            text=f"~{size_kb:.0f} KB/shot  |  ~{mb_per_hour:.1f} MB/hour  |  ~{mb_per_8h:.0f} MB/8h workday"
        )

    def _check_ollama(self):
        self._ollama_dot_frame.configure(fg_color=COLOR_DIM)
        self._ollama_status.configure(text="Ollama: checking...")

        def work():
            import requests
            from englog.config import OLLAMA_BASE_URL, OLLAMA_MODEL
            try:
                resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
                if resp.status_code != 200:
                    return False, set(), OLLAMA_MODEL
                installed = {m["name"].split(":")[0] for m in resp.json().get("models", [])}
                return True, installed, OLLAMA_MODEL
            except Exception:
                return False, set(), OLLAMA_MODEL

        def done(result, err):
            if err:
                self._ollama_dot_frame.configure(fg_color=COLOR_RED)
                self._ollama_status.configure(text=f"Ollama: error ({err})")
                return
            connected, installed, current_model = result
            self._installed_models = installed
            if connected:
                current_ok = current_model in installed
                self._ollama_dot_frame.configure(fg_color=COLOR_GREEN if current_ok else COLOR_ORANGE)
                status = f"Ollama: Connected | Model: {current_model}"
                if not current_ok:
                    status += " (not installed)"
                self._ollama_status.configure(text=status)

                # Build dropdown: installed models first, then known-but-not-installed
                display_values = []
                for m in sorted(installed):
                    display_values.append(m)
                for m in sorted(MODEL_PROFILES.keys()):
                    if m not in installed:
                        display_values.append(f"{m}  (not pulled)")
                self._model_combo.configure(values=display_values)
                self._model_combo.set(current_model)
                self._update_model_description(current_model)
            else:
                self._ollama_dot_frame.configure(fg_color=COLOR_RED)
                self._ollama_status.configure(text="Ollama: Not connected")
                # Still show known models so user can see what's available
                self._model_combo.configure(values=list(MODEL_PROFILES.keys()))

        self.app._run_in_background(work, done)

    def _update_model_description(self, model_name: str):
        """Show model description and install status."""
        profile = MODEL_PROFILES.get(model_name)
        installed = hasattr(self, '_installed_models') and model_name in self._installed_models
        if profile:
            self._model_desc.configure(text=profile["desc"])
            ctx_text = f"Context window: {profile['ctx']:,} tokens (auto-configured)"
            if not installed:
                ctx_text += f"  |  Run: ollama pull {model_name}"
            self._model_ctx_label.configure(text=ctx_text)
        else:
            self._model_desc.configure(text="Custom model — using default settings.")
            self._model_ctx_label.configure(text="Context window: 32,768 tokens (default)")

    def _on_model_changed(self, value: str):
        import englog.config as config
        # Strip the "(not pulled)" suffix if present
        model_name = value.split("  (")[0].strip()
        config.OLLAMA_MODEL = model_name
        # Auto-adjust context window for known models
        profile = MODEL_PROFILES.get(model_name)
        if profile:
            config.OLLAMA_NUM_CTX = profile["ctx"]
        self._update_model_description(model_name)
        config.save_settings()

    def _on_interval_changed(self, value: float):
        import englog.config as config
        val = int(value)
        config.SCREENSHOT_INTERVAL_SECONDS = val
        self._interval_label.configure(text=f"{val}s")
        self._update_capture_hint()
        config.save_settings()

    def _on_quality_changed(self, value: float):
        import englog.config as config
        val = int(value)
        config.SCREENSHOT_QUALITY = val
        self._quality_label.configure(text=str(val))
        self._update_capture_hint()
        config.save_settings()

    def _reset_to_defaults(self):
        """Reset model, interval, and quality to factory defaults."""
        import englog.config as config

        # Model → mistral
        config.OLLAMA_MODEL = "mistral"
        config.OLLAMA_NUM_CTX = 32768
        self._model_combo.set("mistral")
        self._update_model_description("mistral")

        # Interval → 30s
        config.SCREENSHOT_INTERVAL_SECONDS = 30
        self._interval_slider.set(30)
        self._interval_label.configure(text="30s")

        # Quality → 40
        config.SCREENSHOT_QUALITY = 40
        self._quality_slider.set(40)
        self._quality_label.configure(text="40")

        self._update_capture_hint()
        config.save_settings()


# ── Entry point ──────────────────────────────────────────

def main():
    app = EngLogApp()
    app.mainloop()


if __name__ == "__main__":
    main()
