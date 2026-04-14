# vault-log

SQLite-backed session log for Obsidian vaults. Replaces append-only markdown files (`_SESSION_LOG.md`, mutable sections of `_CONTEXT.md`) with a queryable, expiry-aware log.

Entries have a type (`decision`, `context`, `session`), an optional expiry date, and belong to a named vault. Session start becomes one command that returns only what's still active.

## Installation

```bash
uv sync
vlog --help
```

DB lives at `~/sync/vault-log/vault-log.db`. Override with `VAULT_LOG_DB` env var (also used in tests).

## Usage

### Session workflow

```bash
# Start of session — see what's still relevant
vlog read --vault BrainSync

# End of session — log what happened and auto-expire in 14 days
vlog add --vault BrainSync --type session --expires +14d \
  "Audited promo-generator. Next: build vault-log."

# Purge expired session entries
vlog expire
```

### Log a decision

```bash
vlog add --vault BrainSync --type decision \
  "Phase 4 writes via Obsidian MCP only -- never raw filesystem"
```

Decisions have no expiry by default. They stay until you archive them.

### Log context (current state)

```bash
vlog add --vault BrainSync --type context \
  "SQL series: 25 posts, publishing weekly through June 22"
```

When state changes, add the new entry and archive the old one.

### Archive a stale entry

```bash
# Find the id
vlog read --vault BrainSync

# Soft-delete it (preserves history)
vlog archive --id 42
```

### View archived entries

```bash
vlog archived --vault BrainSync
vlog archived --vault BrainSync --type context
```

### Search across vaults

```bash
vlog search "MCP"
vlog search "series" --vault BrainSync
```

## CLI reference

| Command | Description |
|---|---|
| `vlog add` | Append a new entry |
| `vlog read` | Show active (non-expired, non-archived) entries |
| `vlog search QUERY` | Full-text search across active entries |
| `vlog expire` | Hard-delete entries past their expiry date |
| `vlog archive --id N` | Soft-delete an entry (hidden from read/search, visible in archived) |
| `vlog archived` | Show archived entries for a vault |

### `vlog add`

```
vlog add --vault VAULT --type {session,decision,context} [--expires DATE] TEXT
```

- `--vault` / `-w` — vault name (required)
- `--type` / `-t` — entry type (required)
- `--expires` / `-e` — ISO date (`2026-06-22`) or relative (`+14d`); omit for no expiry
- Session entries without `--expires` print a warning to stderr

### `vlog read`

```
vlog read --vault VAULT [--type {session,decision,context}]
```

Returns active entries only: not expired, not archived.

### `vlog search`

```
vlog search QUERY [--vault VAULT]
```

FTS5 full-text search. Excludes expired and archived entries. Omit `--vault` to search all vaults.

### `vlog expire`

```
vlog expire [-v]
```

Hard-deletes rows where `expires < today`. Use `-v` to print each entry before removal.

### `vlog archive`

```
vlog archive --id N
```

Soft-deletes an entry by setting `archived_at`. Entry is hidden from `read` and `search` but retrievable via `vlog archived`. Use this when a decision or context entry is no longer true — it preserves the history of what was decided and when.

### `vlog archived`

```
vlog archived --vault VAULT [--type {session,decision,context}]
```

Shows all archived entries for a vault with their archive date.

## Entry types

| Type | Purpose | Expiry |
|---|---|---|
| `decision` | A convention, rule, or architectural choice | None (archive when superseded) |
| `context` | Current state of a project, series, or effort | None (archive when state changes) |
| `session` | What happened in a session and what's next | Set an expiry (e.g. +14d) |

## Project structure

```
vault-log/
├── Makefile
├── pyproject.toml
├── vault_log/
│   ├── __init__.py
│   ├── db.py        # schema, init_db, all data operations
│   └── cli.py       # argparse subcommands
└── tests/
    └── test_log.py
```

## Running tests

```bash
uv run pytest
```

All tests use `tmp_path` and `VAULT_LOG_DB` env override — no real DB is touched.
