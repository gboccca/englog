"""Tests for summary context building (no Ollama needed)."""

import pytest
from englog import database as db
from englog.summary import build_session_context


class TestBuildSessionContext:
    def _create_session_with_data(self):
        pid = db.create_project("SumTest", "A test project")
        db.update_project_context("SumTest", "Project about testing.")
        db.update_project_rules("SumTest", "Always be precise.")
        sid = db.start_session(pid)
        db.stop_session(sid)
        db.add_note(sid, "decided to use approach A because faster", "decision")
        db.add_note(sid, "waiting on review from Pierre", "blocker")
        db.add_note(sid, "updated the spreadsheet", "observation")
        db.add_capture(sid, None, "Excel - budget.xlsx", "EXCEL.EXE")
        db.add_capture(sid, None, "VSCode - main.py", "Code.exe")
        return sid

    def test_context_contains_project_info(self):
        sid = self._create_session_with_data()
        ctx = build_session_context(sid)
        assert "SumTest" in ctx
        assert "A test project" in ctx

    def test_context_contains_project_context(self):
        sid = self._create_session_with_data()
        ctx = build_session_context(sid)
        assert "Project about testing." in ctx

    def test_context_contains_project_rules(self):
        sid = self._create_session_with_data()
        ctx = build_session_context(sid)
        assert "Always be precise." in ctx

    def test_context_contains_notes(self):
        sid = self._create_session_with_data()
        ctx = build_session_context(sid)
        assert "decided to use approach A" in ctx
        assert "waiting on review from Pierre" in ctx
        assert "updated the spreadsheet" in ctx

    def test_context_contains_captures(self):
        sid = self._create_session_with_data()
        ctx = build_session_context(sid)
        assert "EXCEL.EXE" in ctx
        assert "Code.exe" in ctx

    def test_context_deduplicates_captures(self):
        pid = db.create_project("Dedup")
        sid = db.start_session(pid)
        db.stop_session(sid)
        # Add three identical captures — only one transition should appear
        for _ in range(3):
            db.add_capture(sid, None, "Same Window", "Same.exe")
        ctx = build_session_context(sid)
        assert ctx.count("Same.exe") == 1

    def test_nonexistent_session(self):
        ctx = build_session_context(99999)
        assert ctx == ""

    def test_context_labels_note_types(self):
        sid = self._create_session_with_data()
        ctx = build_session_context(sid)
        assert "NOTE (decision)" in ctx
        assert "NOTE (blocker)" in ctx
        assert "NOTE (observation)" in ctx
