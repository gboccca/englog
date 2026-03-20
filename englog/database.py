"""SQLite database for sessions, notes, and captures."""

import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from englog.config import DB_PATH, SCREENSHOTS_DIR, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    context TEXT DEFAULT '',
    rules TEXT DEFAULT '',
    examples TEXT DEFAULT '',
    status TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    summary TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    timestamp TEXT DEFAULT (datetime('now', 'localtime')),
    content TEXT NOT NULL,
    note_type TEXT DEFAULT 'observation'
);

CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    timestamp TEXT DEFAULT (datetime('now', 'localtime')),
    screenshot_path TEXT,
    active_window TEXT,
    active_process TEXT
);
"""


def get_connection() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    # Migrate: add columns that may not exist in older databases
    for col, default in [("context", "''"), ("rules", "''"), ("examples", "''"), ("status", "''")]:
        try:
            conn.execute(f"ALTER TABLE projects ADD COLUMN {col} TEXT DEFAULT {default}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()


# ── Projects ──────────────────────────────────────────────

def create_project(name: str, description: str = "") -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            (name, description),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        row = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
        return row["id"]
    finally:
        conn.close()


def get_project(name: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_projects() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_project_context(name: str, context: str):
    conn = get_connection()
    conn.execute("UPDATE projects SET context = ? WHERE name = ?", (context, name))
    conn.commit()
    conn.close()


def update_project_rules(name: str, rules: str):
    conn = get_connection()
    conn.execute("UPDATE projects SET rules = ? WHERE name = ?", (rules, name))
    conn.commit()
    conn.close()


def update_project_examples(name: str, examples: str):
    conn = get_connection()
    conn.execute("UPDATE projects SET examples = ? WHERE name = ?", (examples, name))
    conn.commit()
    conn.close()


def save_project_status(name: str, status: str):
    conn = get_connection()
    conn.execute("UPDATE projects SET status = ? WHERE name = ?", (status, name))
    conn.commit()
    conn.close()


def rename_project(project_id: int, new_name: str) -> dict:
    """Rename a project. Returns {"error": ...} on failure, {} on success."""
    conn = get_connection()
    try:
        conn.execute("UPDATE projects SET name = ? WHERE id = ?", (new_name, project_id))
        conn.commit()
        return {}
    except sqlite3.IntegrityError:
        return {"error": f"A project named '{new_name}' already exists."}
    finally:
        conn.close()


def delete_project(project_id: int) -> dict:
    """Delete a project and all its sessions, notes, captures, and screenshots.

    Refuses if the project has an active session.
    Returns {"error": ...} on failure or stats dict on success.
    """
    conn = get_connection()
    # Check for active sessions
    active = conn.execute(
        "SELECT id FROM sessions WHERE project_id = ? AND is_active = 1", (project_id,)
    ).fetchone()
    if active:
        conn.close()
        return {"error": "Cannot delete a project with an active session. Stop the session first."}

    session_rows = conn.execute(
        "SELECT id FROM sessions WHERE project_id = ?", (project_id,)
    ).fetchall()
    session_ids = [r["id"] for r in session_rows]

    deleted_notes = 0
    deleted_captures = 0
    for sid in session_ids:
        deleted_notes += conn.execute("DELETE FROM notes WHERE session_id = ?", (sid,)).rowcount
        deleted_captures += conn.execute("DELETE FROM captures WHERE session_id = ?", (sid,)).rowcount

    conn.execute("DELETE FROM sessions WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()

    # Clean up screenshot directories
    for sid in session_ids:
        sdir = SCREENSHOTS_DIR / str(sid)
        if sdir.is_dir():
            shutil.rmtree(sdir, ignore_errors=True)

    return {
        "deleted_sessions": len(session_ids),
        "deleted_notes": deleted_notes,
        "deleted_captures": deleted_captures,
    }


# ── Sessions ──────────────────────────────────────────────

def start_session(project_id: int) -> int:
    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT INTO sessions (project_id, started_at) VALUES (?, ?)",
        (project_id, now),
    )
    conn.commit()
    session_id = cur.lastrowid
    conn.close()
    return session_id


def stop_session(session_id: int):
    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE sessions SET ended_at = ?, is_active = 0 WHERE id = ?",
        (now, session_id),
    )
    conn.commit()
    conn.close()


def get_active_session() -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        """SELECT s.*, p.name as project_name, p.description as project_description
           FROM sessions s JOIN projects p ON s.project_id = p.id
           WHERE s.is_active = 1 ORDER BY s.started_at DESC LIMIT 1"""
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_session(session_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        """SELECT s.*, p.name as project_name, p.description as project_description
           FROM sessions s JOIN projects p ON s.project_id = p.id
           WHERE s.id = ?""",
        (session_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_sessions(project_name: Optional[str] = None, limit: int = 20) -> list[dict]:
    conn = get_connection()
    if project_name:
        rows = conn.execute(
            """SELECT s.*, p.name as project_name
               FROM sessions s JOIN projects p ON s.project_id = p.id
               WHERE p.name = ? ORDER BY s.started_at DESC LIMIT ?""",
            (project_name, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT s.*, p.name as project_name
               FROM sessions s JOIN projects p ON s.project_id = p.id
               ORDER BY s.started_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_session_summary(session_id: int, summary: str):
    conn = get_connection()
    conn.execute("UPDATE sessions SET summary = ? WHERE id = ?", (summary, session_id))
    conn.commit()
    conn.close()


def delete_session(session_id: int) -> dict:
    """Delete a session and all its notes, captures, and screenshots.

    Refuses to delete an active session.
    Returns {"error": ...} on failure or stats dict on success.
    """
    conn = get_connection()
    row = conn.execute("SELECT is_active FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        conn.close()
        return {"error": f"Session {session_id} not found."}
    if row["is_active"]:
        conn.close()
        return {"error": "Cannot delete an active session. Stop it first."}

    deleted_notes = conn.execute("DELETE FROM notes WHERE session_id = ?", (session_id,)).rowcount
    deleted_captures = conn.execute("DELETE FROM captures WHERE session_id = ?", (session_id,)).rowcount
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()

    # Clean up screenshots
    sdir = SCREENSHOTS_DIR / str(session_id)
    if sdir.is_dir():
        shutil.rmtree(sdir, ignore_errors=True)

    return {"deleted_notes": deleted_notes, "deleted_captures": deleted_captures}


def delete_note(note_id: int):
    """Delete a single note."""
    conn = get_connection()
    conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()


def update_note(note_id: int, content: str, note_type: str):
    """Update a note's content and type."""
    conn = get_connection()
    conn.execute(
        "UPDATE notes SET content = ?, note_type = ? WHERE id = ?",
        (content, note_type, note_id),
    )
    conn.commit()
    conn.close()


# ── Notes ─────────────────────────────────────────────────

def add_note(session_id: int, content: str, note_type: str = "observation") -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO notes (session_id, content, note_type) VALUES (?, ?, ?)",
        (session_id, content, note_type),
    )
    conn.commit()
    note_id = cur.lastrowid
    conn.close()
    return note_id


def get_session_notes(session_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM notes WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_notes(query: str, project_name: Optional[str] = None) -> list[dict]:
    conn = get_connection()
    if project_name:
        rows = conn.execute(
            """SELECT n.*, s.started_at as session_date, p.name as project_name
               FROM notes n
               JOIN sessions s ON n.session_id = s.id
               JOIN projects p ON s.project_id = p.id
               WHERE n.content LIKE ? AND p.name = ?
               ORDER BY n.timestamp DESC""",
            (f"%{query}%", project_name),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT n.*, s.started_at as session_date, p.name as project_name
               FROM notes n
               JOIN sessions s ON n.session_id = s.id
               JOIN projects p ON s.project_id = p.id
               WHERE n.content LIKE ?
               ORDER BY n.timestamp DESC""",
            (f"%{query}%",),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Captures ──────────────────────────────────────────────

def add_capture(
    session_id: int,
    screenshot_path: Optional[str] = None,
    active_window: Optional[str] = None,
    active_process: Optional[str] = None,
) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO captures (session_id, screenshot_path, active_window, active_process)
           VALUES (?, ?, ?, ?)""",
        (session_id, screenshot_path, active_window, active_process),
    )
    conn.commit()
    capture_id = cur.lastrowid
    conn.close()
    return capture_id


def get_session_captures(session_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM captures WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Dashboard stats ──────────────────────────────────────

def get_dashboard_stats() -> dict:
    """Return stats for the idle dashboard on the Session tab."""
    conn = get_connection()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    # Monday of current week
    monday = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")

    # Hours today
    rows = conn.execute(
        """SELECT started_at, ended_at FROM sessions
           WHERE started_at >= ? AND ended_at IS NOT NULL""",
        (today,),
    ).fetchall()
    today_seconds = sum(_session_duration_seconds(r) for r in rows)

    # Hours this week
    rows = conn.execute(
        """SELECT started_at, ended_at FROM sessions
           WHERE started_at >= ? AND ended_at IS NOT NULL""",
        (monday,),
    ).fetchall()
    week_seconds = sum(_session_duration_seconds(r) for r in rows)

    # Sessions this week
    week_session_count = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE started_at >= ?", (monday,),
    ).fetchone()[0]

    # Notes this week
    week_note_count = conn.execute(
        """SELECT COUNT(*) FROM notes n JOIN sessions s ON n.session_id = s.id
           WHERE s.started_at >= ?""",
        (monday,),
    ).fetchone()[0]

    # Decisions this week
    week_decisions = conn.execute(
        """SELECT COUNT(*) FROM notes n JOIN sessions s ON n.session_id = s.id
           WHERE s.started_at >= ? AND n.note_type = 'decision'""",
        (monday,),
    ).fetchone()[0]

    # Current streak (consecutive days with at least 1 session)
    day_rows = conn.execute(
        """SELECT DISTINCT DATE(started_at) as d FROM sessions
           WHERE ended_at IS NOT NULL ORDER BY d DESC""",
    ).fetchall()
    streak = 0
    check_date = now.date()
    for row in day_rows:
        d = datetime.strptime(row["d"], "%Y-%m-%d").date()
        if d == check_date:
            streak += 1
            check_date -= timedelta(days=1)
        elif d < check_date:
            break
    # If no session today yet, check if streak is from yesterday
    if streak == 0 and day_rows:
        d = datetime.strptime(day_rows[0]["d"], "%Y-%m-%d").date()
        yesterday = now.date() - timedelta(days=1)
        if d == yesterday:
            check_date = yesterday
            for row in day_rows:
                d = datetime.strptime(row["d"], "%Y-%m-%d").date()
                if d == check_date:
                    streak += 1
                    check_date -= timedelta(days=1)
                elif d < check_date:
                    break

    # Top 3 apps this week
    app_rows = conn.execute(
        """SELECT c.active_process, COUNT(*) as cnt
           FROM captures c JOIN sessions s ON c.session_id = s.id
           WHERE s.started_at >= ? AND c.active_process IS NOT NULL
             AND c.active_process != 'unknown'
           GROUP BY c.active_process ORDER BY cnt DESC LIMIT 3""",
        (monday,),
    ).fetchall()
    top_apps = [(r["active_process"], r["cnt"]) for r in app_rows]

    # Total hours all time
    rows = conn.execute(
        "SELECT started_at, ended_at FROM sessions WHERE ended_at IS NOT NULL",
    ).fetchall()
    total_seconds = sum(_session_duration_seconds(r) for r in rows)

    # Recent sessions (last 5 completed)
    recent = conn.execute(
        """SELECT s.id, p.name as project_name, s.started_at, s.ended_at,
                  s.summary,
                  (SELECT COUNT(*) FROM notes n WHERE n.session_id = s.id) as note_count
           FROM sessions s JOIN projects p ON s.project_id = p.id
           WHERE s.ended_at IS NOT NULL
           ORDER BY s.started_at DESC LIMIT 5""",
    ).fetchall()

    conn.close()
    return {
        "today_seconds": today_seconds,
        "week_seconds": week_seconds,
        "week_sessions": week_session_count,
        "week_notes": week_note_count,
        "week_decisions": week_decisions,
        "streak": streak,
        "top_apps": top_apps,
        "total_seconds": total_seconds,
        "recent_sessions": [dict(r) for r in recent],
    }


def _session_duration_seconds(row) -> int:
    """Calculate duration in seconds from a session row with started_at/ended_at."""
    try:
        start = datetime.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(row["ended_at"], "%Y-%m-%d %H:%M:%S")
        return max(0, int((end - start).total_seconds()))
    except (ValueError, TypeError):
        return 0
