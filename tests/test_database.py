"""Tests for database CRUD operations."""

import pytest
from englog import database as db


class TestProjects:
    def test_create_and_get(self):
        pid = db.create_project("TestProject", "A test project")
        assert pid > 0
        project = db.get_project("TestProject")
        assert project is not None
        assert project["name"] == "TestProject"
        assert project["description"] == "A test project"

    def test_create_duplicate_returns_existing_id(self):
        pid1 = db.create_project("Dup", "first")
        pid2 = db.create_project("Dup", "second")
        assert pid1 == pid2

    def test_list_projects(self):
        db.create_project("A")
        db.create_project("B")
        projects = db.list_projects()
        names = [p["name"] for p in projects]
        assert "A" in names
        assert "B" in names

    def test_get_nonexistent(self):
        assert db.get_project("NoSuchProject") is None

    def test_update_context(self):
        db.create_project("Ctx")
        db.update_project_context("Ctx", "some context")
        p = db.get_project("Ctx")
        assert p["context"] == "some context"

    def test_update_rules(self):
        db.create_project("Rules")
        db.update_project_rules("Rules", "rule 1")
        p = db.get_project("Rules")
        assert p["rules"] == "rule 1"

    def test_update_examples(self):
        db.create_project("Ex")
        db.update_project_examples("Ex", "example text")
        p = db.get_project("Ex")
        assert p["examples"] == "example text"

    def test_save_project_status(self):
        db.create_project("St")
        db.save_project_status("St", "all good")
        p = db.get_project("St")
        assert p["status"] == "all good"


class TestRenameProject:
    def test_rename_success(self):
        pid = db.create_project("OldName")
        result = db.rename_project(pid, "NewName")
        assert "error" not in result
        assert db.get_project("OldName") is None
        assert db.get_project("NewName") is not None

    def test_rename_duplicate_fails(self):
        db.create_project("NameA")
        pid_b = db.create_project("NameB")
        result = db.rename_project(pid_b, "NameA")
        assert "error" in result


class TestDeleteProject:
    def test_delete_with_sessions(self):
        pid = db.create_project("ToDelete")
        sid = db.start_session(pid)
        db.stop_session(sid)
        db.add_note(sid, "a note")
        db.add_capture(sid, None, "window", "process")

        result = db.delete_project(pid)
        assert "error" not in result
        assert result["deleted_sessions"] == 1
        assert result["deleted_notes"] == 1
        assert result["deleted_captures"] == 1
        assert db.get_project("ToDelete") is None
        assert db.get_session(sid) is None

    def test_delete_refuses_active_session(self):
        pid = db.create_project("Active")
        db.start_session(pid)  # active, not stopped
        result = db.delete_project(pid)
        assert "error" in result
        assert db.get_project("Active") is not None

    def test_delete_empty_project(self):
        pid = db.create_project("Empty")
        result = db.delete_project(pid)
        assert result["deleted_sessions"] == 0
        assert db.get_project("Empty") is None


class TestSessions:
    def test_start_and_stop(self):
        pid = db.create_project("Sess")
        sid = db.start_session(pid)
        session = db.get_session(sid)
        assert session["is_active"] == 1
        assert session["ended_at"] is None

        db.stop_session(sid)
        session = db.get_session(sid)
        assert session["is_active"] == 0
        assert session["ended_at"] is not None

    def test_get_active_session(self):
        pid = db.create_project("ActSess")
        sid = db.start_session(pid)
        active = db.get_active_session()
        assert active is not None
        assert active["id"] == sid

        db.stop_session(sid)
        assert db.get_active_session() is None

    def test_list_sessions(self):
        pid = db.create_project("ListSess")
        s1 = db.start_session(pid)
        db.stop_session(s1)
        s2 = db.start_session(pid)
        db.stop_session(s2)

        sessions = db.list_sessions(project_name="ListSess")
        assert len(sessions) == 2

    def test_save_and_get_summary(self):
        pid = db.create_project("Sum")
        sid = db.start_session(pid)
        db.save_session_summary(sid, "A summary.")
        session = db.get_session(sid)
        assert session["summary"] == "A summary."


class TestDeleteSession:
    def test_delete_stopped_session(self):
        pid = db.create_project("Del")
        sid = db.start_session(pid)
        db.stop_session(sid)
        db.add_note(sid, "note1")
        db.add_note(sid, "note2")
        db.add_capture(sid, None, "w", "p")

        result = db.delete_session(sid)
        assert result["deleted_notes"] == 2
        assert result["deleted_captures"] == 1
        assert db.get_session(sid) is None

    def test_delete_active_session_fails(self):
        pid = db.create_project("DelAct")
        sid = db.start_session(pid)
        result = db.delete_session(sid)
        assert "error" in result
        assert db.get_session(sid) is not None

    def test_delete_nonexistent(self):
        result = db.delete_session(99999)
        assert "error" in result


class TestNotes:
    def test_add_and_get(self):
        pid = db.create_project("Notes")
        sid = db.start_session(pid)
        nid = db.add_note(sid, "test note", "decision")
        assert nid > 0

        notes = db.get_session_notes(sid)
        assert len(notes) == 1
        assert notes[0]["content"] == "test note"
        assert notes[0]["note_type"] == "decision"

    def test_delete_note(self):
        pid = db.create_project("DelNote")
        sid = db.start_session(pid)
        nid = db.add_note(sid, "to delete")
        db.delete_note(nid)
        assert len(db.get_session_notes(sid)) == 0

    def test_update_note(self):
        pid = db.create_project("UpdNote")
        sid = db.start_session(pid)
        nid = db.add_note(sid, "original", "observation")
        db.update_note(nid, "modified", "decision")
        notes = db.get_session_notes(sid)
        assert notes[0]["content"] == "modified"
        assert notes[0]["note_type"] == "decision"

    def test_search_notes(self):
        pid = db.create_project("Search")
        sid = db.start_session(pid)
        db.add_note(sid, "thermal analysis complete")
        db.add_note(sid, "mass budget updated")

        results = db.search_notes("thermal")
        assert len(results) == 1
        assert "thermal" in results[0]["content"]

    def test_search_by_project(self):
        p1 = db.create_project("SearchA")
        p2 = db.create_project("SearchB")
        s1 = db.start_session(p1)
        s2 = db.start_session(p2)
        db.add_note(s1, "shared keyword here")
        db.add_note(s2, "shared keyword here")

        results = db.search_notes("shared", project_name="SearchA")
        assert len(results) == 1


class TestCaptures:
    def test_add_and_get(self):
        pid = db.create_project("Cap")
        sid = db.start_session(pid)
        cid = db.add_capture(sid, "/path/to/img.jpg", "Excel - file.xlsx", "EXCEL.EXE")
        assert cid > 0

        captures = db.get_session_captures(sid)
        assert len(captures) == 1
        assert captures[0]["active_window"] == "Excel - file.xlsx"
        assert captures[0]["active_process"] == "EXCEL.EXE"
