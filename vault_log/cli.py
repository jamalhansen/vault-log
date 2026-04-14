import argparse
import sys
from datetime import datetime, timedelta
from vault_log.db import (
    resolve_db_path,
    init_db,
    add_entry,
    read_entries,
    search_entries,
    expire_entries,
    delete_entry,
    update_entry,
)

def main():
    parser = argparse.ArgumentParser(description="SQLite-backed session log for Obsidian vaults")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # vlog add
    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("--vault", "-w", required=True)
    add_parser.add_argument("--type", "-t", required=True, choices=["context", "session", "decision"])
    add_parser.add_argument("--expires", "-e", help="ISO date (YYYY-MM-DD)")
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

    # vlog delete
    delete_parser = subparsers.add_parser("delete")
    delete_parser.add_argument("--id", "-i", type=int, required=True)
    delete_parser.add_argument("-v", "--verbose", action="store_true")

    # vlog update
    update_parser = subparsers.add_parser("update")
    update_parser.add_argument("--id", "-i", type=int, required=True)
    update_parser.add_argument("--text", "-x")
    update_parser.add_argument("--expires", "-e")
    update_parser.add_argument("--type", "-t", choices=["context", "session", "decision"])
    update_parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()
    db_path = resolve_db_path()
    init_db(db_path)

    if args.command == "add":
        if args.type == "session" and not args.expires:
            print("Warning: session entry without expiry. Consider adding -e YYYY-MM-DD (e.g. +14d).", file=sys.stderr)
        
        expires = args.expires
        if expires and expires.startswith("+") and expires.endswith("d"):
            days = int(expires[1:-1])
            expires = (datetime.now() + timedelta(days=days)).date().isoformat()

        row_id = add_entry(db_path, args.vault, args.type, args.text, expires)
        print(f"Added [{args.type}] to {args.vault} (id={row_id})")

    elif args.command == "read":
        entries = read_entries(db_path, args.vault, args.type)
        if not entries:
            print(f"No entries for vault '{args.vault}'.")
        else:
            for entry in entries:
                print(f"[{entry['type']}] {entry['text']}")

    elif args.command == "search":
        results = search_entries(db_path, args.query, args.vault)
        if not results:
            print(f"No results for '{args.query}'.")
        else:
            for res in results:
                print(f"[{res['vault']} / {res['type']}] {res['text']}")

    elif args.command == "expire":
        # Verbose mode needs to fetch before deleting
        if args.verbose:
            import sqlite3
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                expired = conn.execute("SELECT * FROM entries WHERE expires < date('now')").fetchall()
                for entry in expired:
                    print(f"Expiring: [{entry['vault']} / {entry['type']}] {entry['text']}")
        
        count = expire_entries(db_path)
        if count > 0:
            print(f"Expired {count} entries.")
        else:
            print("Nothing to expire.")

    elif args.command == "delete":
        if args.verbose:
            import sqlite3
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                entry = conn.execute("SELECT * FROM entries WHERE id = ?", (args.id,)).fetchone()
                if entry:
                    print(f"Deleting: [{entry['vault']} / {entry['type']}] {entry['text']}")

        if delete_entry(db_path, args.id):
            print(f"Deleted entry {args.id}.")
        else:
            print(f"No entry with id {args.id}.")

    elif args.command == "update":
        clear_expires = args.expires == "none"
        expires = None if clear_expires else args.expires
        
        if update_entry(db_path, args.id, args.text, expires, clear_expires, args.type):
            print(f"Updated entry {args.id}.")
        else:
            print(f"No entry with id {args.id} or no fields provided to update.")

if __name__ == "__main__":
    main()
