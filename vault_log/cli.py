import argparse
import sys
from datetime import datetime, timedelta

from local_first_common.tracking import timed_run

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


def main():
    parser = argparse.ArgumentParser(description="SQLite-backed session log for Obsidian vaults")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # vlog add
    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("--vault", "-w", required=True)
    add_parser.add_argument("--type", "-t", required=True, choices=["context", "session", "decision"])
    add_parser.add_argument("--expires", "-e", help="ISO date (YYYY-MM-DD) or relative (+14d)")
    add_parser.add_argument("-v", "--verbose", action="store_true")
    add_parser.add_argument("text")

    # vlog read
    read_parser = subparsers.add_parser("read")
    read_parser.add_argument("--vault", "-w", required=True)
    read_parser.add_argument("--type", "-t", choices=["context", "session", "decision"])

    # vlog search
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--vault", "-w")

    # vlog expire
    expire_parser = subparsers.add_parser("expire")
    expire_parser.add_argument("-v", "--verbose", action="store_true")

    # vlog archive
    archive_parser = subparsers.add_parser("archive")
    archive_parser.add_argument("--id", "-i", type=int, required=True)

    # vlog archived
    archived_parser = subparsers.add_parser("archived")
    archived_parser.add_argument("--vault", "-w", required=True)
    archived_parser.add_argument("--type", "-t", choices=["context", "session", "decision"])

    args = parser.parse_args()
    db_path = resolve_db_path()
    init_db(db_path)

    # No LLM model involved (model=None); this just gives vlog a heartbeat on
    # the fleet dashboard's activity panel, which vault_log was invisible to.
    with timed_run("vault-log", None, source_location=getattr(args, "vault", None)) as run:
        run.item_count = _dispatch(args, db_path)


def _dispatch(args, db_path) -> int:
    """Run the parsed command; returns an item count for tracking."""
    if args.command == "add":
        if args.type == "session" and not args.expires:
            print(
                "Warning: session entry without expiry. Consider adding -e YYYY-MM-DD or -e +14d.",
                file=sys.stderr,
            )

        expires = None
        if args.expires:
            try:
                expires = _parse_expires(args.expires)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)

        row_id = add_entry(db_path, args.vault, args.type, args.text, expires)
        print(f"Added [{args.type}] to {args.vault} (id={row_id})")
        return 1

    elif args.command == "read":
        entries = read_entries(db_path, args.vault, args.type)
        if not entries:
            print(f"No entries for vault '{args.vault}'.")
        else:
            for entry in entries:
                print(f"[{entry['type']}] {entry['text']}")
        return len(entries)

    elif args.command == "search":
        results = search_entries(db_path, args.query, args.vault)
        if not results:
            print(f"No results for '{args.query}'.")
        else:
            for res in results:
                print(f"[{res['vault']} / {res['type']}] {res['text']}")
        return len(results)

    elif args.command == "expire":
        expired = expire_entries(db_path)
        if not expired:
            print("Nothing to expire.")
        else:
            if args.verbose:
                for entry in expired:
                    print(f"Expired: [{entry['vault']} / {entry['type']}] {entry['text']}")
            print(f"Expired {len(expired)} {'entry' if len(expired) == 1 else 'entries'}.")
        return len(expired)

    elif args.command == "archive":
        entry = archive_entry(db_path, args.id)
        if entry:
            print(f"Archived [{entry['type']}]: {entry['text']}")
        else:
            print(f"No active entry with id {args.id}.")
        return 1 if entry else 0

    elif args.command == "archived":
        entries = list_archived(db_path, args.vault, args.type)
        if not entries:
            print(f"No archived entries for vault '{args.vault}'.")
        else:
            for entry in entries:
                print(f"[{entry['type']}] (archived {entry['archived_at']}) {entry['text']}")
        return len(entries)

    return 0


if __name__ == "__main__":
    main()
