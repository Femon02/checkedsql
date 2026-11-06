"""Run the test set through the model and give every question a verdict.

Verdicts:
  MATCH               contract kept, SQL ran, result equals the gold result
  WRONG_RESULT        contract kept, SQL ran, result differs from gold
  SQL_ERROR           contract kept, SQL failed (bad column, blocked write, timeout, ...)
  REFUSED             the model replied CANNOT_ANSWER
  CONTRACT_VIOLATION  the reply broke the contract (fences, prose, two statements, ...);
                      the SQL inside is still run and its would-be verdict recorded
  MODEL_REFUSAL       the API declined the request (stop_reason "refusal")
  GOLD_ERROR          the gold query itself failed: a checker bug, not a model error
Every non-MATCH row then gets a failure category by hand (see labels.py).
"""
import datetime
import json
from pathlib import Path

from . import compare, contract, db, model

VERDICTS = ("MATCH", "WRONG_RESULT", "SQL_ERROR", "REFUSED", "CONTRACT_VIOLATION",
            "MODEL_REFUSAL", "GOLD_ERROR")


def _judge_sql(conn, sql, gold_rows):
    rows, err = db.run(conn, sql)
    if err:
        return "SQL_ERROR", err, None
    ok, reason = compare.compare(rows, gold_rows)
    return ("MATCH" if ok else "WRONG_RESULT"), reason, rows


def evaluate_one(conn, client, system, q, model_id, effort):
    gold_rows, gold_err = db.run(conn, q["gold_sql"])
    reply = model.ask(client, system, q["question"], model=model_id, effort=effort)
    row = {"id": q["id"], "tag": q["tag"], "question": q["question"], "gold_sql": q["gold_sql"],
           "reply": reply.text, "stop_reason": reply.stop_reason, "served_by": reply.served_by,
           "fell_back": reply.fell_back, "request_id": reply.request_id, "usage": reply.usage,
           "cost_usd": reply.cost_usd, "model_sql": None, "contract_problems": [],
           "verdict": None, "detail": None, "would_be": None, "pred_rows_sample": None}

    if gold_err:
        row.update(verdict="GOLD_ERROR", detail=gold_err)
        return row
    if reply.stop_reason == "refusal":
        row.update(verdict="MODEL_REFUSAL", detail="API declined the request")
        return row

    kind, sql, problems = contract.check(reply.text)
    row.update(model_sql=sql, contract_problems=problems)
    if kind == "REFUSAL":
        row.update(verdict="REFUSED")
    elif kind == "SELECT":
        verdict, detail, rows = _judge_sql(conn, sql, gold_rows)
        row.update(verdict=verdict, detail=detail, pred_rows_sample=_sample(rows))
    else:
        row.update(verdict="CONTRACT_VIOLATION", detail="; ".join(problems))
        if sql:
            would_be, _, rows = _judge_sql(conn, sql, gold_rows)
            row.update(would_be=would_be, pred_rows_sample=_sample(rows))
    return row


def _sample(rows, n=5):
    return None if rows is None else [list(r) for r in rows[:n]]


def _total(values):
    """Sum, or None when any value is unknown (a replay has no token counts)."""
    values = list(values)
    return None if any(v is None for v in values) else sum(values)


def run(db_path, questions, client, model_id=model.DEFAULT_MODEL, effort=model.DEFAULT_EFFORT,
        out_dir="results", echo=print, source=None):
    """source: None for a live API run, or a dict describing a replay (see replay.py)."""
    conn = db.connect(db_path)
    system = contract.system_prompt(db.schema(conn))
    started = datetime.datetime.now().astimezone()
    rows = []
    for q in questions:
        r = evaluate_one(conn, client, system, q, model_id, effort)
        rows.append(r)
        flag = " (fallback: %s)" % r["served_by"] if r["fell_back"] else ""
        echo(f"[{q['id']:>2}] {r['verdict']:<18} {q['question']}{flag}")

    costs = [r["cost_usd"] for r in rows]
    summary = {
        "run_at": started.isoformat(timespec="seconds"),
        "source": source or {"kind": "api"},
        "model": model_id, "effort": effort, "db": Path(db_path).name,
        "questions": len(rows),
        "verdicts": {v: sum(r["verdict"] == v for r in rows) for v in VERDICTS},
        "fallbacks": sum(r["fell_back"] for r in rows),
        "tokens": {k: _total(r["usage"].get(k) for r in rows)
                   for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")},
        "cost_usd": round(sum(costs), 4) if all(c is not None for c in costs) else None,
        "system_prompt": system,
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"run_{started.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"summary": summary, "results": rows}, indent=2, ensure_ascii=False) + "\n")
    return path, summary
