import sys
from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated

import typer
from local_first_common.tracking import register_tool, timed_run

from vault_log.db import (
    add_entry,
    archive_entry,
    expire_entries,
    init_db,
    list_archived,
    read_entries,
    resolve_db_path,
    search_entries,
)

_TOOL = register_tool("vault-log")


def _parse_expires(value: str) -> str:
    """Parse an ISO date or +Nd shorthand. Raises ValueError on bad input."""
    if value.startswith("+") and value.endswith("d"):
        try:
            days = int(value[1:-1])
        except ValueError:
            raise ValueError(f"Invalid relative date '{value}'. Use +14d format.")
        return (datetime.now().astimezone() + timedelta(days=days)).date().isoformat()
    # Validate it looks like an ISO date
    try:
        datetime.strptime(value, "%Y-%m-%d")  # noqa: DTZ007 - format validation only; the value is kept as a date string
    except ValueError:
        raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD or +14d format.")
    return value


class EntryType(str, Enum):
    context = "context"
    session = "session"
    decision = "decision"


app = typer.Typer(help="SQLite-backed session log for Obsidian vaults", add_completion=False)
VaultRequired = Annotated[str, typer.Option("--vault", "-w")]


def _run(vault: str | None, command) -> None:
    db_path = resolve_db_path()
    init_db(db_path)
    # No LLM model involved (model=None); this just gives vlog a heartbeat on
    # the fleet dashboard's activity panel, which vault_log was invisible to.
    with timed_run("vault-log", None, source_location=vault) as run:
        run.item_count = command(db_path)


@app.callback()
def _root() -> None:
    """SQLite-backed session log for Obsidian vaults."""


@app.command()
def add(
    text: Annotated[str, typer.Argument()],
    vault: VaultRequired,
    entry_type: Annotated[EntryType, typer.Option("--type", "-t")],
    expires: Annotated[str | None, typer.Option("--expires", "-e", help="ISO date (YYYY-MM-DD) or relative (+14d)")] = None,
    verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False,
) -> None:
    """Add an entry."""
    def command(db_path) -> int:
        if entry_type == EntryType.session and not expires:
            print(
                "Warning: session entry without expiry. Consider adding -e YYYY-MM-DD or -e +14d.",
                file=sys.stderr,
            )
        expiry = None
        if expires:
            try:
                expiry = _parse_expires(expires)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                raise typer.Exit(1) from e
        row_id = add_entry(db_path, vault, entry_type.value, text, expiry)
        print(f"Added [{entry_type.value}] to {vault} (id={row_id})")
        return 1

    _run(vault, command)


@app.command()
def read(
    vault: VaultRequired,
    entry_type: Annotated[EntryType | None, typer.Option("--type", "-t")] = None,
) -> None:
    """Read active entries for a vault."""
    def command(db_path) -> int:
        entries = read_entries(db_path, vault, entry_type.value if entry_type else None)
        if not entries:
            print(f"No entries for vault '{vault}'.")
        for entry in entries:
            print(f"[{entry['type']}] {entry['text']}")
        return len(entries)

    _run(vault, command)


@app.command()
def search(
    query: Annotated[str, typer.Argument()],
    vault: Annotated[str | None, typer.Option("--vault", "-w")] = None,
) -> None:
    """Search entry text."""
    def command(db_path) -> int:
        results = search_entries(db_path, query, vault)
        if not results:
            print(f"No results for '{query}'.")
        for res in results:
            print(f"[{res['vault']} / {res['type']}] {res['text']}")
        return len(results)

    _run(vault, command)


@app.command()
def expire(verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False) -> None:
    """Hide entries whose expiry date has passed."""
    def command(db_path) -> int:
        expired = expire_entries(db_path)
        if not expired:
            print("Nothing to expire.")
            return 0
        if verbose:
            for entry in expired:
                print(f"Expired: [{entry['vault']} / {entry['type']}] {entry['text']}")
        print(f"Expired {len(expired)} {'entry' if len(expired) == 1 else 'entries'}.")
        return len(expired)

    _run(None, command)


@app.command()
def archive(entry_id: Annotated[int, typer.Option("--id", "-i")]) -> None:
    """Archive one active entry by id."""
    def command(db_path) -> int:
        entry = archive_entry(db_path, entry_id)
        if entry:
            print(f"Archived [{entry['type']}]: {entry['text']}")
        else:
            print(f"No active entry with id {entry_id}.")
        return 1 if entry else 0

    _run(None, command)


@app.command()
def archived(
    vault: VaultRequired,
    entry_type: Annotated[EntryType | None, typer.Option("--type", "-t")] = None,
) -> None:
    """List archived entries for a vault."""
    def command(db_path) -> int:
        entries = list_archived(db_path, vault, entry_type.value if entry_type else None)
        if not entries:
            print(f"No archived entries for vault '{vault}'.")
        for entry in entries:
            print(f"[{entry['type']}] (archived {entry['archived_at']}) {entry['text']}")
        return len(entries)

    _run(vault, command)


# Editable installs made before the Typer move (both Macs) have a `vlog` script that
# imports `main`; this keeps them working until they're reinstalled.
main = app


if __name__ == "__main__":
    app()
