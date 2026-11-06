"""Turn a run file and its hand labels into a short Markdown report."""
import json
from collections import Counter
from pathlib import Path

from . import labels


def build(run_path):
    data = json.loads(Path(run_path).read_text())
    s, rows = data["summary"], data["results"]
    lab = labels.load(run_path)
    misses = [r for r in rows if r["verdict"] != "MATCH"]
    unlabelled = [r["id"] for r in misses if r["id"] not in lab]
    checker = [r["id"] for r in misses if lab.get(r["id"], {}).get("category") == "checker-mistake"]
    matched = s["verdicts"]["MATCH"]
    model_errors = len(misses) - len(checker)

    src = s.get("source") or {"kind": "api"}
    replayed = src.get("kind") == "replay"
    cost = "unknown (a model without a price entry ran)" if s["cost_usd"] is None else f"${s['cost_usd']:.4f}"
    t = s["tokens"]
    out = [f"# CheckedSQL run {s['run_at']}", ""]
    if replayed:
        out += [f"**Replay, not a live API run.** Replies from `{src['file']}`: model `{s['model']}`. {src['how']}",
                "Token counts, cost, stop reason and fallback model are not measured in a replay.", ""]
    else:
        out += [f"Model `{s['model']}`, effort `{s['effort']}`, live API run."]
    out += [
        f"Database `{s['db']}`, {s['questions']} questions.",
        "",
        f"- **Matched the hand-checked answer:** {matched}/{s['questions']}",
        f"- **Model errors:** {model_errors}" + (f" (plus {len(checker)} checker mistake(s), counted separately)" if checker else ""),
        *([] if replayed else [
            f"- **Served by a fallback model:** {s['fallbacks']}",
            f"- **Tokens:** {t['input_tokens']} in, {t['output_tokens']} out, "
            f"{t['cache_read_input_tokens']} cache read · **estimated cost** {cost}"]),
        "",
        "| Verdict | Count |", "|---|---|",
        *[f"| {v} | {n} |" for v, n in s["verdicts"].items() if n],
        "",
    ]
    if misses:
        cats = Counter(lab[r["id"]]["category"] for r in misses if r["id"] in lab)
        out += ["## Failure categories (assigned by hand)", ""]
        out += [f"- **{c}** ({labels.CATEGORIES[c]}): {n}" for c, n in cats.most_common()]
        if unlabelled:
            out.append(f"- **not labelled yet:** questions {', '.join(map(str, unlabelled))}")
        out += ["", "## Every miss", "",
                "| # | Question | Verdict | Category | Note |", "|---|---|---|---|---|"]
        for r in misses:
            e = lab.get(r["id"], {})
            out.append(f"| {r['id']} | {r['question']} | {r['verdict']} | {e.get('category', '—')} | "
                       f"{(e.get('note') or r.get('detail') or '').replace('|', '/')} |")
    return "\n".join(out) + "\n"
