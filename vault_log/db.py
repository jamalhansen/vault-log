import os
import sqlite3
from pathlib import Path

def resolve_db_path() -> Path:
    if env := os.environ.get("VAULT_LOG_DB"):
        return Path(env).expanduser()
    return Path("~/sync/vault-log/vault-log.db").expanduser()

def init_db(db_path: Path) -> None:
    """Create tables and triggers if they don't exist. Idempotent."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id      INTEGER PRIMARY KEY,
                vault   TEXT NOT NULL,
                type    TEXT NOT NULL CHECK(type IN ('context', 'session', 'decision')),
                date    TEXT NOT NULL,
                expires TEXT,           -- ISO date or NULL (never expires)
                text    TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
                text, vault, type,
                content=entries, content_rowid=id
            );
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
                INSERT INTO entries_fts(rowid, text, vault, type)
                VALUES (new.id, new.text, new.vault, new.type);
            END;
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, text, vault, type)
                VALUES ('delete', old.id, old.text, old.vault, old.type);
            END;
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, text, vault, type)
                VALUES ('delete', old.id, old.text, old.vault, old.type);
                INSERT INTO entries_fts(rowid, text, vault, type)
                VALUES (new.id, new.text, new.vault, new.type);
            END;
        """)

def add_entry(db_path: Path, vault: str, type_: str, text: str, expires: str | None) -> int:
    """Insert entry. Returns new row id."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO entries (vault, type, date, expires, text) VALUES (?, ?, date('now'), ?, ?)",
            (vault, type_, expires, text)
        )
        return cursor.lastrowid

def read_entries(db_path: Path, vault: str, type_: str | None = None) -> list[dict]:
    """Return non-expired entries for vault. Filters by type if given."""
    query = """
        SELECT id, vault, type, date, expires, text
        FROM entries
        WHERE vault = ? AND (expires IS NULL OR expires >= date('now'))
    """
    params = [vault]
    if type_:
        query += " AND type = ?"
        params.append(type_)
    query += " ORDER BY type, date DESC"

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params)]

def search_entries(db_path: Path, query_str: str, vault: str | None = None) -> list[dict]:
    """FTS5 MATCH search. Optionally scoped to a vault."""
    sql = """
        SELECT e.id, e.vault, e.type, e.date, e.expires, e.text
        FROM entries e
        JOIN entries_fts f ON e.id = f.rowid
        WHERE entries_fts MATCH ?
    """
    params = [query_str]
    if vault:
        sql += " AND e.vault = ?"
        params.append(vault)
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]

def expire_entries(db_path: Path) -> int:
    """DELETE where expires < date('now'). Returns count of deleted rows."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("DELETE FROM entries WHERE expires < date('now')")
        return cursor.rowcount

def delete_entry(db_path: Path, id_: int) -> bool:
    """Delete a single entry by id. Returns True if a row was deleted."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("DELETE FROM entries WHERE id = ?", (id_,))
        return cursor.rowcount > 0

def update_entry(
    db_path: Path,
    id_: int,
    text: str | None = None,
    expires: str | None = None,
    clear_expires: bool = False,
    type_: str | None = None,
) -> bool:
    """Update one or more fields on an entry. Returns True if found."""
    updates = []
    params = []
    if text is not None:
        updates.append("text = ?")
        params.append(text)
    if clear_expires:
        updates.append("expires = NULL")
    elif expires is not None:
        updates.append("expires = ?")
        params.append(expires)
    if type_ is not None:
        updates.append("type = ?")
        params.append(type_)
    
    if not updates:
        return False
    
    params.append(id_)
    with sqlite3.connect(db_path) as conn:
        sql = f"UPDATE entries SET {', '.join(updates)} WHERE id = ?"
        cursor = conn.execute(sql, params)
        return cursor.rowcount > 0
