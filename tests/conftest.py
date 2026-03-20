"""Shared test fixtures — isolated temp database for each test."""

import os
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point EngLog at a temporary directory so tests never touch the real database.

    Must patch both config and the modules that import from config at module level,
    since `from englog.config import X` creates a separate reference.
    """
    db_path = tmp_path / "englog.db"
    ss_dir = tmp_path / "screenshots"
    pidfile = tmp_path / ".active_session"
    ss_dir.mkdir()

    # Patch config (source of truth)
    monkeypatch.setattr("englog.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("englog.config.DB_PATH", db_path)
    monkeypatch.setattr("englog.config.SCREENSHOTS_DIR", ss_dir)
    # Patch database.py's own imported references
    monkeypatch.setattr("englog.database.DB_PATH", db_path)
    monkeypatch.setattr("englog.database.SCREENSHOTS_DIR", ss_dir)
    # Patch session.py's pidfile path
    monkeypatch.setattr("englog.session.SESSION_FILE", pidfile)

    from englog import database as db
    db.init_db()
    yield tmp_path
