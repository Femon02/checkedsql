"""Offline tests: no API key, no network. The model is a fake that returns fixed replies."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from checkedsql import compare, contract, db, evaluate, gold, labels, report

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "Chinook_Sqlite.sqlite"
QUESTIONS = json.loads((ROOT / "data" / "questions.json").read_text())


@pytest.fixture
def conn():
    return db.connect(DB)


# --- the database guard -------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "DELETE FROM Artist",
    "UPDATE Artist SET Name = 'x'",
    "INSERT INTO Artist (Name) VALUES ('x')",
    "DROP TABLE Artist",
    "CREATE TABLE t (x)",
    "ATTACH DATABASE ':memory:' AS other",
    "PRAGMA writable_schema = 1",
])
def test_writes_are_refused(conn, sql):
    rows, err = db.run(conn, sql)
    assert rows is None and err
    assert db.run(conn, "SELECT COUNT(*) FROM Artist")[0] == [(275,)]


def test_two_statements_are_refused(conn):
    rows, err = db.run(conn, "SELECT 1; SELECT 2")
    assert rows is None and "one statement" in err


def test_runaway_query_is_stopped(conn, monkeypatch):
    monkeypatch.setattr(db, "TIME_LIMIT_S", 0.2)
    rows, err = db.run(conn, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT COUNT(*) FROM n")
    assert rows is None and "interrupted" in err


# --- the contract ---------------------------------------------------------------------

def test_clean_select_keeps_contract():
    assert contract.check("SELECT COUNT(*) FROM Artist;") == ("SELECT", "SELECT COUNT(*) FROM Artist", [])


def test_refusal_keeps_contract():
    assert contract.check("CANNOT_ANSWER")[0] == "REFUSAL"


@pytest.mark.parametrize("reply, problem", [
    ("```sql\nSELECT 1\n```", "code fence"),
    ("Here is the query: SELECT 1", "text before the SQL"),
    ("SELECT 1; SELECT 2", "more than one statement"),
    ("SELECT 1 -- count", "SQL comment"),
    ("I can't answer that.", "no SELECT statement"),
])
def test_violations_are_named(reply, problem):
    kind, _, problems = contract.check(reply)
    assert kind == "VIOLATION" and problem in problems


def test_violation_still_yields_sql_to_score():
    kind, sql, _ = contract.check("```sql\nSELECT COUNT(*) FROM Artist\n```")
    assert kind == "VIOLATION" and sql == "SELECT COUNT(*) FROM Artist"


# --- the comparator -------------------------------------------------------------------

def test_compare_ignores_row_order_and_rounds_floats():
    assert compare.compare([("b", 2.004), ("a", 1)], [("a", 1), ("b", 2.0)])[0]


def test_compare_reports_extra_column():
    ok, reason = compare.compare([("Helena", "Holý", 49.62)], [("Helena", "Holý")])
    assert not ok and "column count" in reason


# --- the checker checks itself --------------------------------------------------------

def test_every_gold_query_runs(conn):
    results = list(gold.check(conn, QUESTIONS))
    assert len(results) == 20 and not [r for r in results if r["error"]]


def test_tie_detector_finds_the_busiest_year_tie(conn):
    """The arbitrary gold answer found by hand on 2026-10-21: 2009-2012 all have 83 invoices."""
    busiest = "SELECT strftime('%Y', InvoiceDate) FROM Invoice GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1;"
    tie = gold.tie_at_top(conn, busiest)
    assert tie and tie[0][-1] == tie[1][-1] == 83


def test_no_tie_in_current_top_one_questions(conn):
    assert [r["id"] for r in gold.check(conn, QUESTIONS) if r["tie"]] == []


# --- the whole loop, with a fake model ------------------------------------------------

class FakeClient:
    """Stands in for anthropic.Anthropic(): replies[question] -> text."""

    def __init__(self, replies, stop_reason="end_turn"):
        self.replies, self.stop_reason, self.calls = replies, stop_reason, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        q = kw["messages"][0]["content"]
        usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0,
                                cache_creation_input_tokens=0, iterations=None)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.replies.get(q, "CANNOT_ANSWER"))],
                               stop_reason=self.stop_reason, model=kw["model"], usage=usage)


def _q(i):
    return next(q for q in QUESTIONS if q["id"] == i)


def test_run_end_to_end(tmp_path):
    qs = [_q(1), _q(4), _q(17), _q(3)]
    client = FakeClient({
        _q(1)["question"]: "SELECT COUNT(*) FROM Artist",                                  # MATCH
        _q(4)["question"]: "SELECT COUNT(*) FROM Customer WHERE Country = 'Brasil'",       # WRONG_RESULT
        _q(17)["question"]: "```sql\n" + _q(17)["gold_sql"] + "\n```",                     # CONTRACT_VIOLATION, would MATCH
        _q(3)["question"]: "SELECT Title FROM Albums",                                     # SQL_ERROR
    })
    path, s = evaluate.run(DB, qs, client, out_dir=tmp_path, echo=lambda *_: None)
    rows = {r["id"]: r for r in json.loads(path.read_text())["results"]}
    assert rows[1]["verdict"] == "MATCH"
    assert rows[4]["verdict"] == "WRONG_RESULT"
    assert rows[17]["verdict"] == "CONTRACT_VIOLATION" and rows[17]["would_be"] == "MATCH"
    assert rows[3]["verdict"] == "SQL_ERROR"
    assert s["verdicts"]["MATCH"] == 1 and s["cost_usd"] > 0
    # the request carries the contract, the schema, caching and the refusal fallback
    call = client.calls[0]
    assert "CANNOT_ANSWER" in call["system"][0]["text"] and "CREATE TABLE" in call["system"][0]["text"]
    assert call["fallbacks"] == "default" and call["model"] == "claude-opus-5-5"


def test_api_refusal_is_its_own_verdict(tmp_path):
    path, s = evaluate.run(DB, [_q(1)], FakeClient({}, stop_reason="refusal"), out_dir=tmp_path, echo=lambda *_: None)
    assert s["verdicts"]["MODEL_REFUSAL"] == 1


def test_labels_template_never_overwrites_and_report_counts_checker_mistakes(tmp_path):
    client = FakeClient({_q(1)["question"]: "SELECT 1", _q(4)["question"]: "SELECT 2"})
    path, _ = evaluate.run(DB, [_q(1), _q(4)], client, out_dir=tmp_path, echo=lambda *_: None)
    lp, made = labels.write_template(path)
    assert made and not labels.write_template(path)[1]
    data = json.loads(lp.read_text())
    data["labels"][0].update(category="checker-mistake", note="test", labelled_by="test")
    lp.write_text(json.dumps(data))
    text = report.build(path)
    assert "checker mistake" in text and "not labelled yet" in text


# --- replay mode (no API) -------------------------------------------------------------

def test_replay_scores_offline_and_never_claims_tokens_or_cost(tmp_path):
    from checkedsql import replay
    qs = [_q(1), _q(4)]
    client = replay.ReplayClient({"1": "SELECT COUNT(*) FROM Artist", "4": "```sql\nSELECT 1\n```"}, qs)
    src = {"kind": "replay", "file": "r.json", "how": "test"}
    path, s = evaluate.run(DB, qs, client, model_id="claude-opus-5-5", effort=None,
                           out_dir=tmp_path, echo=lambda *_: None, source=src)
    assert s["verdicts"]["MATCH"] == 1 and s["verdicts"]["CONTRACT_VIOLATION"] == 1
    assert s["cost_usd"] is None and s["tokens"]["input_tokens"] is None
    text = report.build(path)
    assert "Replay, not a live API run" in text and "estimated cost" not in text


def test_replay_refuses_a_file_with_missing_replies():
    from checkedsql import replay
    with pytest.raises(ValueError, match="no reply for question"):
        replay.ReplayClient({"1": "SELECT 1"}, [_q(1), _q(2)])


# --- does the checker catch wrong answers? --------------------------------------------

def test_wrong_answers_are_caught_except_the_known_quantity_blind_spot(conn):
    """Found 2026-11-06: every InvoiceLine.Quantity in Chinook is 1, so question 16 cannot
    tell UnitPrice * Quantity from UnitPrice. Fails if that changes, or if a new blind spot appears."""
    from checkedsql import sensitivity
    wrong = sensitivity.load(ROOT / "data" / "wrong_answers.json")
    missed = [r["id"] for r in sensitivity.check(conn, QUESTIONS, wrong) if not r["caught"]]
    assert missed == [16]
    assert db.run(conn, "SELECT DISTINCT Quantity FROM InvoiceLine")[0] == [(1,)]
