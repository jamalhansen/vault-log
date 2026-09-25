"""The command-line contract: what `vlog` prints and exits with, recorded as golden output.

The Contexta session hook runs `vlog read --vault Contexta`, and CLAUDE.md documents the
other commands, so a change of CLI framework must not change them. Runs the installed
script against a temporary database. Re-record deliberately with RECORD_CLI_CONTRACT=1.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden" / "cli_contract.json"
VLOG = Path(sys.executable).parent / "vlog"

SEQUENCE = [
    ["add", "--vault", "Contexta", "--type", "context", "hello world"],
    ["add", "-w", "Contexta", "-t", "session", "a session note"],
    ["add", "-w", "Contexta", "-t", "session", "-e", "+14d", "expires later"],
    ["add", "-w", "Contexta", "-t", "decision", "-e", "2020-01-01", "already expired"],
    ["add", "-w", "KeySix", "-t", "decision", "-v", "other vault"],
    ["add", "-w", "Contexta", "-t", "decision", "-e", "not-a-date", "bad expiry"],
    ["add", "-w", "Contexta", "-t", "bogus", "bad type"],
    ["add", "-w", "Contexta", "-t", "context"],
    ["read", "--vault", "Contexta"],
    ["read", "-w", "Contexta", "-t", "session"],
    ["read", "-w", "Nowhere"],
    ["search", "hello"],
    ["search", "note", "-w", "Contexta"],
    ["search", "zzzqqq"],
    ["archive", "--id", "1"],
    ["archive", "-i", "99"],
    ["archive", "-i", "not-a-number"],
    ["archived", "-w", "Contexta"],
    ["archived", "-w", "Contexta", "-t", "decision"],
    ["expire", "-v"],
    ["expire"],
    ["read", "-w", "Contexta"],
    [],
    ["nonsense"],
]


def _normalize(text: str) -> str:
    return re.sub(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?", "<DATE>", text)


def _results(tmp_path: Path) -> list[dict]:
    env = {**os.environ, "VAULT_LOG_DB": str(tmp_path / "vlog.db"),
           "LOCAL_FIRST_TRACKING_DB": str(tmp_path / "tracking.duckdb")}
    out = []
    for argv in SEQUENCE:
        proc = subprocess.run([str(VLOG), *argv], capture_output=True, text=True, env=env, check=False)
        result = {"argv": argv, "exit": proc.returncode, "stdout": _normalize(proc.stdout)}
        if proc.returncode != 2:  # usage errors: only the exit code is part of the contract
            result["stderr"] = _normalize(proc.stderr)
        out.append(result)
    return out


def test_cli_contract(tmp_path):
    results = _results(tmp_path)
    if os.environ.get("RECORD_CLI_CONTRACT"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(results, indent=2) + "\n")
        pytest.skip("recorded")
    assert results == json.loads(GOLDEN.read_text())
