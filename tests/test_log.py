import pytest
import sqlite3
from vault_log.db import (
    init_db,
    add_entry,
    read_entries,
    search_entries,
    expire_entries,
    delete_entry,
    update_entry,
)

@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("VAULT_LOG_DB", str(db_path))
    init_db(db_path)
    return db_path

def test_add_and_read(db):
    add_entry(db, "BrainSync", "decision", "Rule 1", None)
    add_entry(db, "BrainSync", "context", "State A", None)
    entries = read_entries(db, "BrainSync")
    assert len(entries) == 2
    assert any(e["text"] == "Rule 1" for e in entries)
    assert any(e["text"] == "State A" for e in entries)

def test_read_filters_expired(db):
    # Manually insert an expired entry since add_entry sets date('now')
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO entries (vault, type, date, expires, text) VALUES (?, ?, ?, ?, ?)",
            ("BrainSync", "session", "2020-01-01", "2020-01-02", "Old news")
        )
    entries = read_entries(db, "BrainSync")
    assert len(entries) == 0

def test_read_no_expiry_always_returned(db):
    add_entry(db, "BrainSync", "decision", "Eternal truth", None)
    entries = read_entries(db, "BrainSync")
    assert len(entries) == 1
    assert entries[0]["text"] == "Eternal truth"

def test_read_type_filter(db):
    add_entry(db, "BrainSync", "decision", "Rule 1", None)
    add_entry(db, "BrainSync", "context", "State A", None)
    entries = read_entries(db, "BrainSync", type_="decision")
    assert len(entries) == 1
    assert entries[0]["text"] == "Rule 1"

def test_expire_purges_old(db):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO entries (vault, type, date, expires, text) VALUES (?, ?, ?, ?, ?)",
            ("BrainSync", "session", "2020-01-01", "2020-01-02", "Old news")
        )
    count = expire_entries(db)
    assert count == 1
    with sqlite3.connect(db) as conn:
        res = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
        assert res[0] == 0

def test_expire_keeps_future(db):
    # Future expiry
    add_entry(db, "BrainSync", "session", "Future news", "2099-01-01")
    count = expire_entries(db)
    assert count == 0
    entries = read_entries(db, "BrainSync")
    assert len(entries) == 1

def test_expire_nothing_to_do(db):
    add_entry(db, "BrainSync", "decision", "Rule 1", None)
    count = expire_entries(db)
    assert count == 0

def test_search_basic(db):
    add_entry(db, "BrainSync", "decision", "Phase 4 writes via MCP", None)
    results = search_entries(db, "MCP")
    assert len(results) == 1
    assert results[0]["text"] == "Phase 4 writes via MCP"

def test_search_vault_filter(db):
    add_entry(db, "VaultA", "decision", "Common keyword", None)
    add_entry(db, "VaultB", "decision", "Common keyword", None)
    results = search_entries(db, "keyword", vault="VaultA")
    assert len(results) == 1
    assert results[0]["vault"] == "VaultA"

def test_search_no_results(db):
    add_entry(db, "BrainSync", "decision", "Rule 1", None)
    results = search_entries(db, "Nonexistent")
    assert len(results) == 0

def test_add_returns_id(db):
    row_id = add_entry(db, "BrainSync", "decision", "Rule 1", None)
    assert isinstance(row_id, int)
    assert row_id > 0

def test_db_idempotent(db):
    init_db(db)
    init_db(db)
    # No error, and tables still exist
    with sqlite3.connect(db) as conn:
        conn.execute("SELECT * FROM entries")

def test_delete_existing(db):
    row_id = add_entry(db, "BrainSync", "decision", "Rule 1", None)
    success = delete_entry(db, row_id)
    assert success is True
    entries = read_entries(db, "BrainSync")
    assert len(entries) == 0

def test_delete_missing(db):
    success = delete_entry(db, 999)
    assert success is False

def test_delete_removes_from_fts(db):
    row_id = add_entry(db, "BrainSync", "decision", "Rule 1", None)
    delete_entry(db, row_id)
    results = search_entries(db, "Rule")
    assert len(results) == 0

def test_update_text(db):
    row_id = add_entry(db, "BrainSync", "decision", "Old text", None)
    success = update_entry(db, row_id, text="New text")
    assert success is True
    entries = read_entries(db, "BrainSync")
    assert entries[0]["text"] == "New text"

def test_update_text_rebuilds_fts(db):
    row_id = add_entry(db, "BrainSync", "decision", "Initial state", None)
    update_entry(db, row_id, text="Updated state")
    
    # New text should be searchable
    results = search_entries(db, "Updated")
    assert len(results) == 1
    
    # Old text should NOT be searchable
    results = search_entries(db, "Initial")
    assert len(results) == 0

def test_update_expires(db):
    row_id = add_entry(db, "BrainSync", "session", "Note", None)
    update_entry(db, row_id, expires="2026-01-01")
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT expires FROM entries WHERE id = ?", (row_id,)).fetchone()
        assert row[0] == "2026-01-01"

def test_update_clear_expires(db):
    row_id = add_entry(db, "BrainSync", "session", "Note", "2026-01-01")
    update_entry(db, row_id, clear_expires=True)
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT expires FROM entries WHERE id = ?", (row_id,)).fetchone()
        assert row[0] is None

def test_update_type(db):
    row_id = add_entry(db, "BrainSync", "session", "Note", None)
    update_entry(db, row_id, type_="decision")
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT type FROM entries WHERE id = ?", (row_id,)).fetchone()
        assert row[0] == "decision"

def test_update_missing(db):
    success = update_entry(db, 999, text="Fail")
    assert success is False

def test_update_requires_field(db):
    row_id = add_entry(db, "BrainSync", "session", "Note", None)
    success = update_entry(db, row_id)
    assert success is False
