"""Command line: python -m checkedsql <command>.

  check-gold              run every gold query, flag errors and tied "top one" answers (no API call)
  check-wrong             score deliberately wrong answers; any that still match are blind spots
  run [--limit N]         ask the model every question, write results/run_<time>.json
  run --replies FILE      score replies collected earlier instead of calling the API (no key needed)
  labels RUN              write the hand-labelling template for a run's misses
  report RUN              write the run's Markdown report (uses the labels filled in so far)
"""
import argparse
import json
import sys
from pathlib import Path

from . import db, evaluate, gold, labels, model, replay, report, sensitivity

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "Chinook_Sqlite.sqlite"
DEFAULT_QUESTIONS = ROOT / "data" / "questions.json"
DEFAULT_WRONG = ROOT / "data" / "wrong_answers.json"


def _questions(path, limit=None, ids=None):
    qs = json.loads(Path(path).read_text(encoding="utf-8"))
    if ids:
        qs = [q for q in qs if q["id"] in ids]
    return qs[:limit] if limit else qs


def cmd_check_gold(a):
    conn = db.connect(a.db)
    qs = _questions(a.questions)
    errors = ties = 0
    for r in gold.check(conn, qs):
        status = f"ERROR {r['error']}" if r["error"] else f"{len(r['rows'])} row(s): {r['rows'][:5]}"
        print(f"[{r['id']:>2}] {r['question']}\n     -> {status}")
        if r["tie"]:
            ties += 1
            print(f"     !! TIE at first place: {r['tie']} — the gold answer is an arbitrary pick")
        errors += bool(r["error"])
    print(f"\nGold SQL errors: {errors}/{len(qs)} · tied top-one answers: {ties}. "
          "A human still has to read each result and confirm it answers the question.")
    return 1 if errors or ties else 0


def cmd_check_wrong(a):
    conn = db.connect(a.db)
    results = list(sensitivity.check(conn, _questions(a.questions), sensitivity.load(a.wrong)))
    for r in results:
        mark = "caught " if r["caught"] else "MISSED "
        print(f"[{r['id']:>2}] {mark} {r['mistake']}" + ("" if r["caught"] else
              "  <- a wrong answer scores as correct: blind spot in the test data"))
    missed = [r for r in results if not r["caught"]]
    print(f"\nWrong answers caught: {len(results) - len(missed)}/{len(results)} · blind spots: {len(missed)}")
    return 1 if missed else 0


def cmd_run(a):
    qs = _questions(a.questions, a.limit, a.ids)
    if a.replies:
        r = replay.load(a.replies)
        source = {"kind": "replay", "file": Path(a.replies).name, "how": r["how"]}
        path, s = evaluate.run(a.db, qs, replay.ReplayClient(r["replies"], qs), model_id=r["model"],
                               effort=None, out_dir=a.out, source=source)
        print(f"\n{s['verdicts']['MATCH']}/{s['questions']} matched (replay: no tokens or cost measured)")
    else:
        import anthropic
        path, s = evaluate.run(a.db, qs, anthropic.Anthropic(), model_id=a.model, effort=a.effort, out_dir=a.out)
        cost = "unknown" if s["cost_usd"] is None else f"${s['cost_usd']:.4f}"
        print(f"\n{s['verdicts']['MATCH']}/{s['questions']} matched · fallbacks {s['fallbacks']} · "
              f"tokens in {s['tokens']['input_tokens']} out {s['tokens']['output_tokens']} · est. cost {cost}")
    print(f"Saved {path}\nNext: python -m checkedsql labels {path}")
    return 0


def cmd_labels(a):
    path, made = labels.write_template(a.run)
    print(("Wrote " if made else "Already exists (not overwritten): ") + str(path))
    print("Fill in category, note and labelled_by for every entry; categories are listed at the top of the file.")
    return 0


def cmd_report(a):
    text = report.build(a.run)
    out = Path(a.run).with_suffix(".md")
    out.write_text(text)
    print(text)
    print(f"Saved {out}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="checkedsql", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-gold").set_defaults(fn=cmd_check_gold)
    w = sub.add_parser("check-wrong")
    w.add_argument("--wrong", default=str(DEFAULT_WRONG))
    w.set_defaults(fn=cmd_check_wrong)
    r = sub.add_parser("run")
    r.add_argument("--limit", type=int)
    r.add_argument("--ids", type=int, nargs="+", help="only these question ids")
    r.add_argument("--model", default=model.DEFAULT_MODEL)
    r.add_argument("--effort", default=model.DEFAULT_EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    r.add_argument("--replies", help="replies file to score offline instead of calling the API")
    r.add_argument("--out", default=str(ROOT / "results"))
    r.set_defaults(fn=cmd_run)
    for name, fn in (("labels", cmd_labels), ("report", cmd_report)):
        s = sub.add_parser(name)
        s.add_argument("run", help="path to results/run_<time>.json")
        s.set_defaults(fn=fn)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
