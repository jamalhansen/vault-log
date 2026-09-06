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
                id          INTEGER PRIMARY KEY,
                vault       TEXT NOT NULL,
                type        TEXT NOT NULL CHECK(type IN ('context', 'session', 'decision')),
                date        TEXT NOT NULL,
                expires     TEXT,
                archived_at TEXT DEFAULT NULL,
                text        TEXT NOT NULL
            );
        """)
        # Migrate: add archived_at if this is an existing DB that predates it
        try:
            conn.execute("ALTER TABLE entries ADD COLUMN archived_at TEXT DEFAULT NULL")
        except sqlite3.OperationalError:
            pass  # column already exists

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
            (vault, type_, expires, text),
        )
        return cursor.lastrowid


def read_entries(db_path: Path, vault: str, type_: str | None = None) -> list[dict]:
    """Return active (non-expired, non-archived) entries for vault."""
    query = """
        SELECT id, vault, type, date, expires, text
        FROM entries
        WHERE vault = ?
          AND archived_at IS NULL
          AND (expires IS NULL OR expires >= date('now'))
    """
    params = [vault]
    if type_:
        query += " AND type = ?"
        params.append(type_)
    query += " ORDER BY type, date DESC"

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params)]


def _sanitize_fts_query(query_str: str) -> str:
    """Quote each whitespace-separated token so FTS5's query syntax (column
    filters, NOT via leading '-', etc.) can't misparse raw user input like
    "session-orient". Tokens match literally; multiple tokens AND together."""
    tokens = query_str.split()
    return " ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def search_entries(db_path: Path, query_str: str, vault: str | None = None) -> list[dict]:
    """FTS5 MATCH search. Excludes expired and archived entries. Optionally scoped to a vault."""
    sql = """
        SELECT e.id, e.vault, e.type, e.date, e.expires, e.text
        FROM entries e
        JOIN entries_fts f ON e.id = f.rowid
        WHERE entries_fts MATCH ?
          AND e.archived_at IS NULL
          AND (e.expires IS NULL OR e.expires >= date('now'))
    """
    params = [_sanitize_fts_query(query_str)]
    if vault:
        sql += " AND e.vault = ?"
        params.append(vault)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def expire_entries(db_path: Path) -> list[dict]:
    """Hard-delete entries where expires < today. Returns the deleted entries."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        expired = [
            dict(row)
            for row in conn.execute(
                "SELECT id, vault, type, date, expires, text FROM entries WHERE expires < date('now')"
            )
        ]
        if expired:
            conn.execute("DELETE FROM entries WHERE expires < date('now')")
        return expired


def archive_entry(db_path: Path, id_: int) -> dict | None:
    """Soft-delete an entry by setting archived_at. Returns the entry, or None if not found."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, vault, type, date, expires, text FROM entries WHERE id = ? AND archived_at IS NULL",
            (id_,),
        ).fetchone()
        if not row:
            return None
        conn.execute("UPDATE entries SET archived_at = date('now') WHERE id = ?", (id_,))
        return dict(row)


def list_archived(db_path: Path, vault: str, type_: str | None = None) -> list[dict]:
    """Return archived entries for vault."""
    query = """
        SELECT id, vault, type, date, archived_at, text
        FROM entries
        WHERE vault = ? AND archived_at IS NOT NULL
    """
    params = [vault]
    if type_:
        query += " AND type = ?"
        params.append(type_)
    query += " ORDER BY type, archived_at DESC"

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params)]
