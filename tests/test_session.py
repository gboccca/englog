"""Tests for session lifecycle management."""

import json
import pytest
from englog import database as db
from englog.session import (
    start_new_session,
    stop_current_session,
    add_session_note,
    get_active_session_info,
)


class TestSessionLifecycle:
    def test_start_creates_session(self):
        result = start_new_session("TestProj", "desc")
        assert "session_id" in result
        assert result["project"] == "TestProj"

        session = db.get_session(result["session_id"])
        assert session is not None
        assert session["is_active"] == 1

    def test_start_creates_pidfile(self, isolated_db):
        result = start_new_session("PidTest", "")
        pidfile = isolated_db / ".active_session"
        assert pidfile.exists()

        data = json.loads(pidfile.read_text())
        assert data["session_id"] == result["session_id"]
        assert data["project"] == "PidTest"

    def test_cannot_start_two_sessions(self):
        start_new_session("First", "")
        result = start_new_session("Second", "")
        assert "error" in result

    def test_stop_session(self):
        start_new_session("StopTest", "")
        result = stop_current_session()
        assert "error" not in result
        assert result["project"] == "StopTest"
        assert "notes_count" in result
        assert "captures_count" in result

    def test_stop_removes_pidfile(self, isolated_db):
        start_new_session("StopPid", "")
        stop_current_session()
        pidfile = isolated_db / ".active_session"
        assert not pidfile.exists()

    def test_stop_without_active_session(self):
        result = stop_current_session()
        assert "error" in result

    def test_get_active_session_info(self, isolated_db):
        assert get_active_session_info() is None
        start_new_session("InfoTest", "")
        info = get_active_session_info()
        assert info is not None
        assert info["project"] == "InfoTest"


class TestSessionNotes:
    def test_add_note_to_active_session(self):
        start_new_session("NoteTest", "")
        result = add_session_note("test note", "observation")
        assert "error" not in result

        info = get_active_session_info()
        notes = db.get_session_notes(info["session_id"])
        assert len(notes) == 1
        assert notes[0]["content"] == "test note"

    def test_add_note_without_session_fails(self):
        result = add_session_note("orphan note", "observation")
        assert "error" in result

    def test_add_multiple_notes(self):
        start_new_session("MultiNote", "")
        add_session_note("note 1", "observation")
        add_session_note("note 2", "decision")
        add_session_note("note 3", "blocker")

        info = get_active_session_info()
        notes = db.get_session_notes(info["session_id"])
        assert len(notes) == 3
        types = [n["note_type"] for n in notes]
        assert "observation" in types
        assert "decision" in types
        assert "blocker" in types
