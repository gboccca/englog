"""Session manager — ties together capture, notes, and database."""

import json
from pathlib import Path
from typing import Optional

from englog.config import DATA_DIR
from englog import database as db
from englog.capture import CaptureEngine

# Pidfile to track active session across CLI invocations
SESSION_FILE = DATA_DIR / ".active_session"


def _save_active_session(session_id: int, project_name: str):
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps({"session_id": session_id, "project": project_name}))


def _clear_active_session():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def get_active_session_info() -> Optional[dict]:
    """Read active session info from pidfile (works across CLI calls)."""
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text())
            # Verify it's still active in DB
            session = db.get_active_session()
            if session and session["id"] == data["session_id"]:
                return data
            else:
                _clear_active_session()
        except Exception:
            _clear_active_session()
    return None


def start_new_session(project_name: str, description: str = "") -> dict:
    """Start a new tracking session for a project."""
    # Check no session already active
    active = get_active_session_info()
    if active:
        return {"error": f"Session already active on project '{active['project']}'. Stop it first."}

    # Create/get project
    project_id = db.create_project(project_name, description)
    session_id = db.start_session(project_id)
    _save_active_session(session_id, project_name)

    return {"session_id": session_id, "project": project_name}


def stop_current_session() -> dict:
    """Stop the active session."""
    active = get_active_session_info()
    if not active:
        return {"error": "No active session."}

    db.stop_session(active["session_id"])
    _clear_active_session()

    session = db.get_session(active["session_id"])
    notes = db.get_session_notes(active["session_id"])
    captures = db.get_session_captures(active["session_id"])

    return {
        "session_id": active["session_id"],
        "project": active["project"],
        "started_at": session["started_at"],
        "ended_at": session["ended_at"],
        "notes_count": len(notes),
        "captures_count": len(captures),
    }


def add_session_note(content: str, note_type: str = "observation") -> dict:
    """Add a note to the active session."""
    active = get_active_session_info()
    if not active:
        return {"error": "No active session. Start one with: englog start <project>"}

    note_id = db.add_note(active["session_id"], content, note_type)
    return {
        "note_id": note_id,
        "session_id": active["session_id"],
        "project": active["project"],
        "type": note_type,
    }
