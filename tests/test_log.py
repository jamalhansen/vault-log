import sqlite3

import pytest

from vault_log.db import (
    add_entry,
    archive_entry,
    expire_entries,
    init_db,
    list_archived,
    read_entries,
    search_entries,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("VAULT_LOG_DB", str(db_path))
    init_db(db_path)
    return db_path


# --- add / read ---

def test_add_and_read(db):
    add_entry(db, "BrainSync", "decision", "Rule 1", None)
    add_entry(db, "BrainSync", "context", "State A", None)
    entries = read_entries(db, "BrainSync")
    assert len(entries) == 2
    assert any(e["text"] == "Rule 1" for e in entries)
    assert any(e["text"] == "State A" for e in entries)


def test_read_filters_expired(db):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO entries (vault, type, date, expires, text) VALUES (?, ?, ?, ?, ?)",
            ("BrainSync", "session", "2020-01-01", "2020-01-02", "Old news"),
        )
    entries = read_entries(db, "BrainSync")
    assert len(entries) == 0


def test_read_excludes_archived(db):
    row_id = add_entry(db, "BrainSync", "decision", "Stale rule", None)
    archive_entry(db, row_id)
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


def test_add_returns_id(db):
    row_id = add_entry(db, "BrainSync", "decision", "Rule 1", None)
    assert isinstance(row_id, int)
    assert row_id > 0


def test_db_idempotent(db):
    init_db(db)
    init_db(db)
    with sqlite3.connect(db) as conn:
        conn.execute("SELECT * FROM entries")


# --- expire ---

def test_expire_purges_old(db):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO entries (vault, type, date, expires, text) VALUES (?, ?, ?, ?, ?)",
            ("BrainSync", "session", "2020-01-01", "2020-01-02", "Old news"),
        )
    expired = expire_entries(db)
    assert len(expired) == 1
    assert expired[0]["text"] == "Old news"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0


def test_expire_keeps_future(db):
    add_entry(db, "BrainSync", "session", "Future news", "2099-01-01")
    assert expire_entries(db) == []
    assert len(read_entries(db, "BrainSync")) == 1


def test_expire_nothing_to_do(db):
    add_entry(db, "BrainSync", "decision", "Rule 1", None)
    assert expire_entries(db) == []


def test_expire_returns_entry_details(db):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO entries (vault, type, date, expires, text) VALUES (?, ?, ?, ?, ?)",
            ("BrainSync", "session", "2020-01-01", "2020-01-02", "Old news"),
        )
    expired = expire_entries(db)
    assert expired[0]["vault"] == "BrainSync"
    assert expired[0]["type"] == "session"


# --- search ---

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
    assert search_entries(db, "Nonexistent") == []


def test_search_excludes_expired(db):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO entries (vault, type, date, expires, text) VALUES (?, ?, ?, ?, ?)",
            ("BrainSync", "session", "2020-01-01", "2020-01-02", "Old searchable thing"),
        )
    assert search_entries(db, "searchable") == []


def test_search_excludes_archived(db):
    row_id = add_entry(db, "BrainSync", "decision", "Archived searchable rule", None)
    archive_entry(db, row_id)
    assert search_entries(db, "Archived") == []


# --- archive ---

def test_archive_entry(db):
    row_id = add_entry(db, "BrainSync", "decision", "Old rule", None)
    result = archive_entry(db, row_id)
    assert result is not None
    assert result["text"] == "Old rule"


def test_archive_missing(db):
    assert archive_entry(db, 999) is None


def test_archive_hides_from_read(db):
    row_id = add_entry(db, "BrainSync", "decision", "Old rule", None)
    archive_entry(db, row_id)
    assert read_entries(db, "BrainSync") == []


def test_archive_hides_from_search(db):
    row_id = add_entry(db, "BrainSync", "decision", "Phase 4 MCP rule", None)
    archive_entry(db, row_id)
    assert search_entries(db, "MCP") == []


def test_archive_already_archived(db):
    row_id = add_entry(db, "BrainSync", "decision", "Rule", None)
    archive_entry(db, row_id)
    assert archive_entry(db, row_id) is None


# --- list_archived ---

def test_list_archived_basic(db):
    row_id = add_entry(db, "BrainSync", "decision", "Old rule", None)
    archive_entry(db, row_id)
    results = list_archived(db, "BrainSync")
    assert len(results) == 1
    assert results[0]["text"] == "Old rule"
    assert results[0]["archived_at"] is not None


def test_list_archived_type_filter(db):
    r1 = add_entry(db, "BrainSync", "decision", "Old rule", None)
    r2 = add_entry(db, "BrainSync", "context", "Old context", None)
    archive_entry(db, r1)
    archive_entry(db, r2)
    results = list_archived(db, "BrainSync", type_="decision")
    assert len(results) == 1
    assert results[0]["text"] == "Old rule"


def test_list_archived_empty(db):
    add_entry(db, "BrainSync", "decision", "Active rule", None)
    assert list_archived(db, "BrainSync") == []


def test_list_archived_excludes_active(db):
    add_entry(db, "BrainSync", "decision", "Active", None)
    row_id = add_entry(db, "BrainSync", "decision", "Archived", None)
    archive_entry(db, row_id)
    results = list_archived(db, "BrainSync")
    assert len(results) == 1
    assert results[0]["text"] == "Archived"
