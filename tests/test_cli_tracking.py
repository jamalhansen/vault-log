import os

import duckdb
from typer.testing import CliRunner

from vault_log.cli import app

runner = CliRunner()


def _run(monkeypatch, tmp_path, argv):
    monkeypatch.setenv("VAULT_LOG_DB", str(tmp_path / "test.db"))
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.output


def _tracking_db():
    return duckdb.connect(os.environ["LOCAL_FIRST_TRACKING_DB"])


def test_add_logs_a_processing_run(monkeypatch, tmp_path):
    """vault-log was invisible to the fleet dashboard's activity panel because
    nothing in it ever called into local_first_common.tracking. `vlog add`
    should now show up in processing_log."""
    _run(monkeypatch, tmp_path, ["add", "--vault", "BrainSync", "--type", "decision", "Rule 1"])

    rows = _tracking_db().execute(
        "SELECT tool_name, item_count, success FROM processing_log WHERE tool_name = 'vault-log'"
    ).fetchall()
    assert rows == [("vault-log", 1, True)]


def test_read_logs_item_count(monkeypatch, tmp_path):
    _run(monkeypatch, tmp_path, ["add", "--vault", "BrainSync", "--type", "context", "State A"])
    _run(monkeypatch, tmp_path, ["read", "--vault", "BrainSync"])

    row = _tracking_db().execute(
        "SELECT item_count FROM processing_log WHERE tool_name = 'vault-log' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert row == (1,)
