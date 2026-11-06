"""Text-to-SQL eval harness for the Chinook SQLite database.

Usage:
  python run_eval.py --db Chinook_Sqlite.sqlite --check-gold        # no API call: run every gold SQL, print results
  python run_eval.py --db Chinook_Sqlite.sqlite --limit 1           # first question only (the "first piece that runs")
  python run_eval.py --db Chinook_Sqlite.sqlite                     # full run, writes results/run_<timestamp>.json

Needs ANTHROPIC_API_KEY in the environment for anything except --check-gold.
"""
import argparse, json, os, re, sqlite3, sys, datetime

SYSTEM_TEMPLATE = """You translate English questions into SQLite queries.

CONTRACT:
- Output exactly one SQLite SELECT statement and nothing else: no markdown, no code fences, no explanation.
- Use only the tables and columns in the schema below.
- If the question cannot be answered from this schema, output exactly: CANNOT_ANSWER

SCHEMA:
{schema}
"""

def connect_ro(path):
    if not os.path.exists(path):
        sys.exit(f"Database not found: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)  # read-only: model SQL can never modify data

def get_schema(conn):
    rows = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name").fetchall()
    return "\n\n".join(r[0] for r in rows)

def run_sql(conn, sql):
    try:
        return conn.execute(sql).fetchall(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def normalize(rows):
    """Order-insensitive, column-name-insensitive comparison; floats rounded to 2 places."""
    def cell(v):
        return round(v, 2) if isinstance(v, float) else v
    norm = [tuple(cell(v) for v in r) for r in rows]
    return sorted(norm, key=lambda r: tuple(str(v) for v in r))

def clean_model_sql(text):
    text = text.strip()
    text = re.sub(r"^```(?:sql)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    return text

def ask_claude(client, model, system, question):
    msg = client.messages.create(
        model=model, max_tokens=500, system=system,
        messages=[{"role": "user", "content": question}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--questions", default="questions.json")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--model", default=os.environ.get("EVAL_MODEL", "claude-sonnet-5-5"))
    ap.add_argument("--check-gold", action="store_true", help="only execute gold SQL; no API calls")
    args = ap.parse_args()

    conn = connect_ro(args.db)
    questions = json.load(open(args.questions, encoding="utf-8"))
    if args.limit:
        questions = questions[: args.limit]

    if args.check_gold:
        bad = 0
        for q in questions:
            rows, err = run_sql(conn, q["gold_sql"])
            status = "ERROR " + err if err else f"{len(rows)} row(s): {rows[:5]}"
            bad += bool(err)
            print(f"[{q['id']:>2}] {q['question']}\n     -> {status}")
        print(f"\nGold SQL errors: {bad}/{len(questions)}. A human still has to read each result and confirm it answers the question.")
        return

    import anthropic
    client = anthropic.Anthropic()
    system = SYSTEM_TEMPLATE.format(schema=get_schema(conn))
    results, correct = [], 0
    for q in questions:
        raw = ask_claude(client, args.model, system, q["question"])
        sql = clean_model_sql(raw)
        gold_rows, gold_err = run_sql(conn, q["gold_sql"])
        if gold_err:
            verdict, pred_err = "GOLD_ERROR", None
        elif sql == "CANNOT_ANSWER":
            verdict, pred_err = "REFUSED", None
        elif not sql.lower().lstrip().startswith(("select", "with")):
            verdict, pred_err = "NOT_SELECT", None
        else:
            pred_rows, pred_err = run_sql(conn, sql)
            if pred_err:
                verdict = "SQL_ERROR"
            else:
                verdict = "MATCH" if normalize(pred_rows) == normalize(gold_rows) else "WRONG_RESULT"
        correct += verdict == "MATCH"
        results.append({"id": q["id"], "tag": q["tag"], "question": q["question"],
                        "model_sql": sql, "gold_sql": q["gold_sql"], "verdict": verdict,
                        "error": pred_err, "failure_category": None})
        print(f"[{q['id']:>2}] {verdict:<12} {q['question']}")

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    os.makedirs("results", exist_ok=True)
    out = {"run_at": stamp, "model": args.model, "db": os.path.basename(args.db),
           "correct": correct, "total": len(results), "results": results}
    path = f"results/run_{stamp}.json"
    json.dump(out, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\n{correct}/{len(results)} matched. Saved {path}")
    print("Fill in failure_category by hand for every non-MATCH row (e.g. wrong join, wrong aggregate, ambiguity, comparator false negative).")

if __name__ == "__main__":
    main()
