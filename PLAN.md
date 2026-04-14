# vault-log build plan

## Build log

All decisions, approach changes, and surprises during implementation go in `SESSION.log` at the root of this project. Use this format:

```
[YYYY-MM-DD] <what was done or decided and why>
```

One entry per meaningful decision or deviation from this plan. If something breaks and you fix it, write it down — that's the entry worth keeping.

---

SQLite-backed session log replacing `_SESSION_LOG.md` and the mutable sections of `_CONTEXT.md`. Entries have a type, vault, date, optional expiry, and text. Session start becomes one command returning only what's still valid.

CLI: `vlog`  
DB: `~/sync/vault-log/vault-log.db`  
Location: `~/projects/vault-log/`

---

## Project structure

```
vault-log/
├── Makefile
├── pyproject.toml
├── README.md
├── vault_log/
│   ├── __init__.py
│   ├── db.py          # schema, init_db, all CRUD + FTS
│   └── cli.py         # argparse subcommands: add, read, search, expire
├── tests/
│   ├── __init__.py
│   └── test_log.py
└── uv.lock
```

---

## Step 1 — Bootstrap

```bash
cd ~/projects/vault-log

uv init --name vault-log --no-workspace
uv add --dev pytest ruff

git init
git add .
git commit -m "Initial uv project scaffold"
```

Create `Makefile` (entire file — one line):

```makefile
include $(HOME)/projects/py-tooling/Makefile.common
```

Install hooks and verify:

```bash
python3 ~/projects/py-tooling/install_hooks.py --repo .
make check-hooks
```

---

## Step 2 — `pyproject.toml`

Replace the generated one:

```toml
[project]
name = "vault-log"
version = "0.1.0"
description = "SQLite-backed session log for Obsidian vaults"
requires-python = ">=3.11"
dependencies = []

[project.scripts]
vlog = "vault_log.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
]
```

No external dependencies — `sqlite3` and `argparse` are stdlib.

---

## Step 3 — `vault_log/db.py`

Owns schema, DB path resolution, and all data operations.

### DB path

Resolves to `~/sync/vault-log/vault-log.db`. Creates parent dirs on first use.
Override via `VAULT_LOG_DB` env var (useful for tests via `tmp_path`).

```python
def resolve_db_path() -> Path:
    if env := os.environ.get("VAULT_LOG_DB"):
        return Path(env).expanduser()
    return Path("~/sync/vault-log/vault-log.db").expanduser()
```

### Schema

```sql
CREATE TABLE IF NOT EXISTS entries (
    id      INTEGER PRIMARY KEY,
    vault   TEXT NOT NULL,
    type    TEXT NOT NULL CHECK(type IN ('context', 'session', 'decision')),
    date    TEXT NOT NULL,
    expires TEXT,           -- ISO date or NULL (never expires)
    text    TEXT NOT NULL
);

-- FTS5 content table backed by entries
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    text, vault, type,
    content=entries, content_rowid=id
);

-- Keep FTS in sync via triggers
CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, text, vault, type)
    VALUES (new.id, new.text, new.vault, new.type);
END;

CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, text, vault, type)
    VALUES ('delete', old.id, old.text, old.vault, old.type);
END;
```

### Functions

```python
def init_db(db_path: Path) -> None:
    """Create tables and triggers if they don't exist. Idempotent.
    Calls db_path.parent.mkdir(parents=True, exist_ok=True) before connecting --
    ~/sync/ may not exist on a fresh machine and must not be assumed present.
    """

def add_entry(db_path: Path, vault: str, type_: str, text: str, expires: str | None) -> int:
    """Insert entry. Returns new row id."""

def read_entries(db_path: Path, vault: str, type_: str | None = None) -> list[dict]:
    """Return non-expired entries for vault. Filters by type if given.
    WHERE expires IS NULL OR expires >= date('now')
    ORDER BY type, date DESC
    """

def search_entries(db_path: Path, query: str, vault: str | None = None) -> list[dict]:
    """FTS5 MATCH search. Optionally scoped to a vault."""

def expire_entries(db_path: Path) -> int:
    """DELETE where expires < date('now'). Returns count of deleted rows."""

def delete_entry(db_path: Path, id_: int) -> bool:
    """Delete a single entry by id. Returns True if a row was deleted, False if not found."""

def update_entry(
    db_path: Path,
    id_: int,
    text: str | None = None,
    expires: str | None = None,
    clear_expires: bool = False,
    type_: str | None = None,
) -> bool:
    """Update one or more fields on an entry. Returns True if found, False if not.
    clear_expires=True sets expires to NULL regardless of the expires argument.
    If text changes, triggers FTS rebuild for that row via DELETE + INSERT into entries_fts.
    """
```

> **Note (FTS5 + update):** FTS5 content tables do not support UPDATE — changes to `text` must be handled as a DELETE + INSERT in `entries_fts`. The `update_entry` function must do this manually when `text` is changed. See also: bulk inserts that bypass `add_entry` will not fire the INSERT trigger and require `INSERT INTO entries_fts(entries_fts) VALUES('rebuild')` to resync the index.

All functions accept `db_path` as a parameter — no global state. Makes testing clean via `tmp_path`.

---

## Step 4 — `vault_log/cli.py`

Four subcommands via `argparse` with a top-level parser and `add_subparsers`.

### `vlog add`

```
vlog add --vault VAULT --type {session,decision,context} [--expires YYYY-MM-DD] [-v] TEXT
```

- `TEXT` is a positional (last arg)
- `--vault` / `-w`, `--type` / `-t` required
- `--expires` / `-e` optional; ISO date
- If `--type session` and no `--expires`: print a warning to stderr suggesting a 14-day window, but don't block
- Prints: `Added [decision] to BrainSync (id=42)`

### `vlog read`

```
vlog read --vault VAULT [--type {session,decision,context}]
```

Output grouped by type, one entry per line:

```
[decision] Phase 4 writes via Obsidian MCP only
[decision] Promo flow replaced by threads + carousels
[context]  SQL series: 25 posts, publishing weekly through June 22
[session]  2026-04-14: Audited promo-generator. Next: build vault-log.
```

If no entries: `No entries for vault 'BrainSync'.`

### `vlog search`

```
vlog search QUERY [--vault VAULT]
```

Output includes vault and type for each hit (useful when searching across vaults):

```
[BrainSync / decision] Phase 4 writes via Obsidian MCP only
[Contexta  / session ] 2026-04-10: Resolved 4 tensions in determinism cluster.
```

If no hits: `No results for 'MCP'.`

### `vlog expire`

```
vlog expire [-v]
```

Purges rows where `expires < today`. Prints count:  
`Expired 3 entries.` (or `Nothing to expire.`)

`-v` prints each deleted entry before removing it.

### `vlog delete`

```
vlog delete --id ID [-v]
```

Deletes a single entry by id. Use when a `context` or `decision` entry is no longer true and you want it gone immediately rather than waiting for expiry.

- `--id` / `-i` required
- Prints: `Deleted entry 42.` or `No entry with id 42.`
- `-v` prints the entry text before deleting

Typical use: a context entry about the SQL series becomes stale after June 22. Add the new state, delete the old one.

### `vlog update`

```
vlog update --id ID [--text TEXT] [--expires YYYY-MM-DD] [--type {session,decision,context}] [-v]
```

Updates one or more fields on an existing entry. At least one of `--text`, `--expires`, or `--type` must be provided.

- `--id` / `-i` required
- `--text` / `-x` replaces entry text (also rebuilds FTS index for this row)
- `--expires` / `-e` sets or clears expiry (`--expires none` to remove it)
- `--type` / `-t` changes entry type
- `-v` prints the before/after
- Prints: `Updated entry 42.`

Typical use: a decision's wording needs tightening, or a context entry's expiry needs extending.

---

## Step 5 — `tests/test_log.py`

All tests use `tmp_path` and set `VAULT_LOG_DB` via `monkeypatch.setenv` so no real DB is touched.

```python
@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("VAULT_LOG_DB", str(db_path))
    init_db(db_path)
    return db_path
```

Tests to write:

| Test | What it checks |
|---|---|
| `test_add_and_read` | Add 2 entries, read returns both in correct format |
| `test_read_filters_expired` | Entry with yesterday's expiry not returned by read |
| `test_read_no_expiry_always_returned` | NULL expires entry always appears |
| `test_read_type_filter` | `type_="decision"` returns only decisions |
| `test_expire_purges_old` | expire() deletes past-due rows, returns correct count |
| `test_expire_keeps_future` | expire() does not delete entries expiring tomorrow |
| `test_expire_nothing_to_do` | Returns 0 when no expired entries |
| `test_search_basic` | FTS match returns correct row |
| `test_search_vault_filter` | Results scoped to vault, other vault's match excluded |
| `test_search_no_results` | Returns empty list cleanly |
| `test_add_returns_id` | add_entry returns integer id |
| `test_db_idempotent` | init_db called twice does not error or duplicate tables |
| `test_delete_existing` | delete_entry returns True and row is gone |
| `test_delete_missing` | delete_entry returns False for unknown id |
| `test_delete_removes_from_fts` | deleted entry no longer appears in search results |
| `test_update_text` | update_entry changes text, new text appears in read |
| `test_update_text_rebuilds_fts` | updated text is searchable, old text is not |
| `test_update_expires` | update_entry sets a new expiry date |
| `test_update_clear_expires` | clear_expires=True sets expires to NULL |
| `test_update_type` | update_entry changes type |
| `test_update_missing` | update_entry returns False for unknown id |
| `test_update_requires_field` | calling update with no changed fields is a no-op (or raises) |

Run with: `uv run pytest`

---

## Step 6 — Wire and install

```bash
uv sync                # installs the project in editable mode
vlog --help            # confirm entry point works
vlog add --vault BrainSync --type decision "test entry"
vlog read --vault BrainSync
```

---

## Step 7 — Commit

```bash
make check             # ruff
uv run pytest          # all tests pass
git add Makefile pyproject.toml vault_log/ tests/ README.md
git commit -m "Add vlog: SQLite-backed session log with FTS search

Four subcommands: add, read, search, expire.
DB at ~/sync/vault-log/vault-log.db.
Replaces _SESSION_LOG.md append workflow."
```

---

## Step 8 — Migrate existing content

Run once after the tool is working. These are the entries worth keeping from `_SESSION_LOG.md` and `_CONTEXT.md`:

```bash
# Decisions (no expiry)
vlog add --vault BrainSync --type decision \
  "Phase 4 (Tool #34) writes via Obsidian MCP only -- never raw filesystem (sync conflict risk)"
vlog add --vault BrainSync --type decision \
  "Promo file workflow replaced by threads (Bluesky/X) and carousels (LinkedIn)"
vlog add --vault BrainSync --type decision \
  "Blog posts live at blog/series/[series]/posts/[NN-slug]/ -- post file matches folder slug"
vlog add --vault BrainSync --type decision \
  "Series brainstorm canonical location is blog/series/[folder]/, not blog/ideas/"
vlog add --vault BrainSync --type decision \
  "Tool #34 scheduled 4AM Sundays; Tool #28 runs after it in the same window"
vlog add --vault BrainSync --type decision \
  "Newsletter is handwritten, not generated -- drafted in Obsidian, sent via beehiiv"

# Context (no expiry -- update when state changes)
vlog add --vault BrainSync --type context \
  "SQL series: 25 posts drafted, publishing weekly Mondays 8am CT through June 22 -- autopilot"
vlog add --vault BrainSync --type context \
  "DuckDB series: 12 posts, target Q3 2026 -- moving from passive to active prep in April"
vlog add --vault BrainSync --type context \
  "Forging the Truth (CLI series): 22 micro-posts drafted, targets June as SQL/DuckDB bridge"
vlog add --vault BrainSync --type context \
  "Course pre-sell planned for May -- outline needs to be finalized this month"
```

---

## Step 9 — Clean up markdown files

After confirming `vlog read --vault BrainSync` returns the right content:

**`_SESSION_LOG.md`**: Delete entirely. It is replaced by vlog.

**`_CONTEXT.md`**: Remove these sections:
- "Current Focus" (blog series status, paternity leave, newsletter/course/finds)
- "Paternity Leave" subsection
- Monthly goals pointer
- "Updating This File" section
- Task Routing row: "Create a promo file"
- Claude Task Instructions: "Make promo file"

What stays: CLI command table, Source Tags, Key Vault Locations, Task Routing (minus promo row), Claude Task Instructions (minus promo), Vault Organization rules.

---

## Session workflow after this is built

**Session start:**
```bash
vlog read --vault BrainSync
```

**Session end:**
```bash
vlog add --vault BrainSync --type session --expires YYYY-MM-DD \
  "What was done. Next: what's next."
vlog expire
```

**When a decision is made:**
```bash
vlog add --vault BrainSync --type decision "The convention or rule."
```

**When context changes** (series launches, series ends, focus shifts):
```bash
# No update-in-place -- just add a new context entry.
# Old one will stay until manually expired or explicitly deleted (add a vlog delete command later if needed).
vlog add --vault BrainSync --type context "Updated state..."
```
