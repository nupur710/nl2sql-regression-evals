"""Grader 1: does the SQL run without error (within the time limit)?

Also the shared way to run any SQL against the eval database. Queries run on a
read-only connection so a generated query can never modify the test data.
"""

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TIMEOUT_S = 5.0
# How often (in SQLite VM instructions) to check the clock.
_PROGRESS_INTERVAL = 10_000


@dataclass
class ExecResult:
    ok: bool
    rows: list = field(default_factory=list)
    error: str | None = None


def connect_readonly(db_path):
    """Open the database read-only. Fails if the file does not exist."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def run_sql(sql, db_path, timeout_s=DEFAULT_TIMEOUT_S):
    """Run one SQL statement and return its rows, or the error."""
    if not sql or not sql.strip():
        return ExecResult(ok=False, error="empty SQL")

    conn = connect_readonly(db_path)
    deadline = time.monotonic() + timeout_s
    # SQLite calls this handler while a query runs; returning non-zero aborts it.
    conn.set_progress_handler(lambda: time.monotonic() > deadline, _PROGRESS_INTERVAL)
    try:
        rows = conn.execute(sql).fetchall()
        return ExecResult(ok=True, rows=rows)
    except sqlite3.Error as exc:
        if time.monotonic() > deadline:
            return ExecResult(ok=False, error=f"timeout after {timeout_s}s")
        return ExecResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        conn.close()


def executes(sql, db_path, timeout_s=DEFAULT_TIMEOUT_S):
    """Pass/fail: True if the SQL runs without error or timeout."""
    return run_sql(sql, db_path, timeout_s).ok
