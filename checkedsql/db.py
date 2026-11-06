"""Read-only access to the sample database.

Model-written SQL runs here, so three guards stand between it and the data:
the file is opened read-only, an authorizer refuses anything but reading,
and a progress handler stops a query that runs too long.
"""
import sqlite3
import time
from pathlib import Path

# Authorizer actions that only read. Everything else (INSERT, UPDATE, DELETE, CREATE,
# DROP, ATTACH, PRAGMA, ...) is denied before it runs.
_READ_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
_RECURSIVE = getattr(sqlite3, "SQLITE_RECURSIVE", None)   # WITH RECURSIVE, also read-only
if _RECURSIVE is not None:
    _READ_ACTIONS.add(_RECURSIVE)

TIME_LIMIT_S = 5.0
ROW_LIMIT = 10_000


def connect(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in _READ_ACTIONS else sqlite3.SQLITE_DENY)
    return conn


def schema(conn):
    """CREATE TABLE statements, in name order, for the prompt. Read before the authorizer matters."""
    rows = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name").fetchall()
    return "\n\n".join(r[0].strip() for r in rows)


def run(conn, sql):
    """Run one statement. Returns (rows, None) or (None, "ErrorType: message")."""
    deadline = time.monotonic() + TIME_LIMIT_S
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cur = conn.execute(sql)   # sqlite3 refuses more than one statement per call
        rows = cur.fetchmany(ROW_LIMIT + 1)
        if len(rows) > ROW_LIMIT:
            return None, f"RowLimit: more than {ROW_LIMIT} rows"
        return rows, None
    except sqlite3.Error as e:
        msg = "interrupted after %.0fs" % TIME_LIMIT_S if "interrupted" in str(e) else str(e)
        return None, f"{type(e).__name__}: {msg}"
    except sqlite3.Warning as e:  # e.g. "You can only execute one statement at a time."
        return None, f"{type(e).__name__}: {e}"
    finally:
        conn.set_progress_handler(None, 0)
