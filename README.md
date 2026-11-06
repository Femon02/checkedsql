# CheckedSQL

**An evaluation harness for text-to-SQL that checks its own checker.**

CheckedSQL asks a language model to turn 20 English questions into SQLite queries on the public
[Chinook](https://github.com/lerocha/chinook-database) music-store database. It runs each query
read-only and compares the result with a hand-checked gold answer. Then it asks whether that
comparison can be trusted at all: are the gold answers right, and would a wrong answer actually be caught?

Yuhao Fu · INFO 7375 Computational Skepticism for AI, Northeastern University · Fall 2026

## Results (2026-11-06)

| Check | Result |
|---|---|
| Gold SQL runs and has no tied "top one" answer | **20/20, 0 ties** |
| Model answers that match the gold answer | **20/20** (replay, see below) |
| Contract kept (one bare SELECT, no fences or prose) | **20/20** |
| Deliberately wrong answers the checker catches | **7/8: one blind spot** |

**What the 20/20 means, and what it doesn't.** A perfect score on 20 questions says more about the
test than about the model. These are short, single-intent questions on a small and well-known schema.
The score shows the model handles questions at this level. It is not evidence that the model is
reliable on text-to-SQL in general. A harder question set is the obvious next step.

**The blind spot.** Question 16 asks for revenue as *unit price times quantity*. Every one of the
2,240 rows in `InvoiceLine` has `Quantity = 1`. A query that forgets the quantity returns exactly the same
numbers, so the checker would score that mistake as correct. A test locks this finding in
(`test_wrong_answers_are_caught_except_the_known_quantity_blind_spot`).

**Found earlier, by hand (2026-10-21).** The first version of the question set asked for the year with
the most invoices. 2009, 2010, 2011 and 2012 all have 83, so the gold `ORDER BY … LIMIT 1` was an
arbitrary pick. That question is not in the current set, and `check-gold` now flags any tied top-one answer
automatically.

### How the model answers were produced: a replay, not an API run

I did not have an Anthropic API key when I ran this. Each of the 20 questions was therefore answered by a separate, fresh
**Claude Opus 5.5 subagent inside Claude Code**. Each one saw only the same system prompt and its one
question (`replays/prompts/`). None of them saw the gold answers or any other question. Their replies are
recorded word for word in `replays/claude-code-subagents.json` and scored by exactly the same code as a live
run.

A replay cannot measure tokens, cost, the stop reason or a fallback model, so those are recorded as
unknown, never as zero. The harness's live API mode (`python -m checkedsql run`) is fully implemented and
tested offline against a fake client. It has **not** been run against the real API yet.

## Run it

Needs Python 3.10 or later.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q                                          # 28 offline tests, no key needed
python -m checkedsql check-gold                              # are the gold answers sound?
python -m checkedsql check-wrong                             # would a wrong answer be caught? (exits 1: one blind spot)
python -m checkedsql run --replies replays/claude-code-subagents.json   # rescore the recorded replies
python -m checkedsql report results/run_<time>.json
```

With an API key (`export ANTHROPIC_API_KEY=...`), run a live evaluation, starting with one question:

```bash
python -m checkedsql run --limit 1      # then: python -m checkedsql run
```

Each live call records the tokens used, an estimated cost (from the price table in `checkedsql/model.py`;
check current pricing), and which model actually served it. If a request is declined, the API's
server-side fallback can re-run it on another model. That would change what is being evaluated, so every row
records `served_by`, and the report counts fallbacks separately.

## How it works

| Module | Job |
|---|---|
| `db.py` | Opens the database read-only, refuses every action that is not a read (DELETE, DROP, ATTACH, PRAGMA, …), stops a query after 5 s, caps results at 10,000 rows, runs one statement only |
| `contract.py` | The prompt contract (one SELECT, or exactly `CANNOT_ANSWER`) and the check that it was kept. A violation is recorded, never quietly repaired; the SQL inside still runs and its would-be verdict is kept |
| `compare.py` | Compares result rows ignoring row order and column names, rounding floats to 2 places, and names the kind of mismatch |
| `gold.py` | Runs every gold query; flags any `ORDER BY … LIMIT 1` whose first place is tied |
| `sensitivity.py` | Scores hand-written wrong answers (`data/wrong_answers.json`); any that still match are blind spots |
| `evaluate.py` | One verdict per question: MATCH, WRONG_RESULT, SQL_ERROR, REFUSED, CONTRACT_VIOLATION, MODEL_REFUSAL, GOLD_ERROR |
| `labels.py`, `report.py` | Hand-labelled failure categories for every miss (checker mistakes counted apart from model errors), and the Markdown report |
| `replay.py` | Scores replies collected earlier, without an API call |

## Limitations

- **Small, easy test set.** 20 questions, all written by me, each meant to have one clear reading. Nothing here
  measures ambiguous questions, multi-step reasoning or a large schema.
- **One run.** Model output varies between runs, and one pass of 20 says nothing about that variance.
- **Replay, not API.** The subagents ran inside Claude Code, which has its own system prompt around the
  task, so this is close to, but not the same as, a bare API call with the same prompt.
- **Order-insensitive comparison.** It cannot check a requested sort order. Because column names are
  ignored, it also cannot check that the requested columns were labelled right. An extra column counts as a
  mismatch, even when the answer is otherwise right (a false negative; label it `shape-only`).
- **The data hides some mistakes.** The Quantity blind spot is the one I found. There may be others that
  my wrong-answer list does not cover.

## Credits

- Chinook database © Luis Rocha, MIT License: see `data/NOTICE.md`.
- Questions, gold SQL and the tie finding: Yuhao Fu.
- Code: written with Claude (Anthropic), reviewed and run by me: see `SOURCES.md`.
