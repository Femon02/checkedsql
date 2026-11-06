"""Failure categories, assigned by a person.

The machine says MATCH or not; it cannot say why an answer is wrong, or whether
the gold answer was the wrong one. After each run, `checkedsql labels` writes a
template with one entry per non-MATCH question; a person fills in a category and
a note for each. The template never overwrites a file that already exists.
"""
import json
from pathlib import Path

CATEGORIES = {
    "wrong-join": "joined the wrong tables or on the wrong key",
    "wrong-filter": "wrong WHERE condition or literal",
    "wrong-aggregate": "wrong aggregate or arithmetic (COUNT vs SUM, rounding, units)",
    "wrong-grouping": "grouped or deduplicated differently",
    "shape-only": "right answer, different columns or format: a comparator false negative",
    "question-ambiguous": "the question allows more than one reasonable answer",
    "checker-mistake": "the gold answer was wrong or arbitrary (counted separately from model errors)",
    "contract-violation": "broke the output contract",
    "other": "anything else; explain in the note",
}


def labels_path(run_path):
    run_path = Path(run_path)
    return run_path.with_name(run_path.stem + ".labels.json")


def write_template(run_path):
    path = labels_path(run_path)
    if path.exists():
        return path, False
    data = json.loads(Path(run_path).read_text())
    entries = [{"id": r["id"], "verdict": r["verdict"], "question": r["question"],
                "model_sql": r["model_sql"], "gold_sql": r["gold_sql"], "detail": r["detail"],
                "category": "", "note": "", "labelled_by": ""}
               for r in data["results"] if r["verdict"] != "MATCH"]
    path.write_text(json.dumps({"categories": CATEGORIES, "labels": entries}, indent=2, ensure_ascii=False) + "\n")
    return path, True


def load(run_path):
    """{id: entry} for labelled entries only; an entry with an unknown category raises."""
    path = labels_path(run_path)
    if not path.exists():
        return {}
    out = {}
    for e in json.loads(path.read_text())["labels"]:
        if not e.get("category"):
            continue
        if e["category"] not in CATEGORIES:
            raise ValueError(f"question {e['id']}: unknown category {e['category']!r}")
        out[e["id"]] = e
    return out
