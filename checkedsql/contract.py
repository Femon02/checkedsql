"""The prompt contract, and the check that the model kept it.

Contract: reply with exactly one SQLite SELECT statement and nothing else, or with
exactly CANNOT_ANSWER. A reply that breaks the contract is recorded as a violation,
even when the SQL inside it would have been right: the point is to see how often
the model keeps the contract, not to quietly repair it.
"""
import re

REFUSAL = "CANNOT_ANSWER"

SYSTEM_TEMPLATE = """You translate English questions into SQLite queries for the database below.

CONTRACT:
- Reply with exactly one SQLite SELECT statement (it may start with WITH) and nothing else:
  no markdown, no code fences, no comments, no explanation.
- Use only the tables and columns in the schema.
- If the question cannot be answered from this schema, reply with exactly: CANNOT_ANSWER

SCHEMA:
{schema}
"""

_FENCE = re.compile(r"^```[a-zA-Z]*\s*(.*?)\s*```$", re.DOTALL)


def system_prompt(schema):
    return SYSTEM_TEMPLATE.format(schema=schema)


def check(reply):
    """Classify a model reply.

    Returns (kind, sql, problems):
      kind      "SELECT" (contract kept), "REFUSAL", or "VIOLATION"
      sql       the statement to evaluate (for a violation, the best recoverable SQL, or None)
      problems  list of contract breaks found
    """
    text = (reply or "").strip()
    if text == REFUSAL:
        return "REFUSAL", None, []

    problems = []
    sql = text
    m = _FENCE.match(text)
    if m:
        problems.append("code fence")
        sql = m.group(1).strip()
    if sql == REFUSAL:
        return "VIOLATION", None, problems + ["refusal wrapped in extra text"]

    start = re.search(r"\b(SELECT|WITH)\b", sql, re.IGNORECASE)
    if not start:
        return "VIOLATION", None, problems + ["no SELECT statement"]
    if start.start() > 0:
        problems.append("text before the SQL")
        sql = sql[start.start():]

    body = sql.rstrip().rstrip(";").strip()
    if ";" in body:
        problems.append("more than one statement")
    if "--" in body or "/*" in body:
        problems.append("SQL comment")
    first = body.split(None, 1)[0].upper()
    if first not in ("SELECT", "WITH"):
        problems.append("does not start with SELECT or WITH")

    return ("VIOLATION" if problems else "SELECT"), body, problems
