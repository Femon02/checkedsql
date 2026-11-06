"""Does the checker catch a wrong answer? Score deliberately wrong SQL against the gold answers.

Every entry in data/wrong_answers.json is a plausible mistake written by hand. A wrong
answer that still MATCHES is a blind spot: the test data cannot tell that mistake from the
right answer, so a model making it would be scored correct.
"""
import json
from pathlib import Path

from . import compare, db


def check(conn, questions, wrong_answers):
    gold = {q["id"]: q["gold_sql"] for q in questions}
    for w in wrong_answers:
        gold_rows, _ = db.run(conn, gold[w["id"]])
        rows, err = db.run(conn, w["sql"])
        caught, reason = (True, err) if err else (lambda m: (not m[0], m[1]))(compare.compare(rows, gold_rows))
        yield {**w, "caught": caught, "reason": reason}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
