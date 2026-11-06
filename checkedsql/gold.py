"""Check the checker: run every gold query and look for answers that are arbitrary.

Running is not the same as being right. Besides SQL errors, this looks for the
failure found by hand on 2026-10-21: a "top one" query (ORDER BY ... LIMIT 1)
where the first place is tied, so the gold answer is one arbitrary pick.
A person still has to read every result and confirm it answers the question.
"""
import re

from . import db

_ORDER_BY = re.compile(r"\bORDER\s+BY\s+(.+?)(?:\s+(ASC|DESC))?\s+LIMIT\s+1\s*;?\s*$", re.IGNORECASE | re.DOTALL)


def tie_at_top(conn, gold_sql):
    """For an ORDER BY <expr> LIMIT 1 query, return the tied first-place rows if there is a tie, else []."""
    m = _ORDER_BY.search(gold_sql)
    if not m:
        return []
    expr, direction = m.group(1).strip(), (m.group(2) or "ASC").upper()
    body = gold_sql[:m.start()].rstrip()
    # Re-run the top two with the sort key exposed (the query may not select it) and compare their keys.
    sel = re.match(r"\s*SELECT\s+(.*?)\s+FROM\s+(.*)$", body, re.IGNORECASE | re.DOTALL)
    if not sel:
        return []
    probe = f"SELECT {sel.group(1)}, {expr} AS _key FROM {sel.group(2)} ORDER BY {expr} {direction} LIMIT 2"
    rows, err = db.run(conn, probe)
    if err or not rows or len(rows) < 2:
        return []
    return rows if rows[0][-1] == rows[1][-1] else []


def check(conn, questions):
    """Yields one dict per question: id, question, rows (or None), error, tie."""
    for q in questions:
        rows, err = db.run(conn, q["gold_sql"])
        tie = [] if err else tie_at_top(conn, q["gold_sql"])
        yield {"id": q["id"], "question": q["question"], "rows": rows, "error": err, "tie": tie}
