# Sources and contributions

## What I did (Yuhao Fu)
- Chose the project and the Chinook database.
- Wrote the 20 questions and their gold SQL (`data/questions.json`).
- Found the tied "busiest year" gold answer by hand on 2026-10-21.
- Chose the replay approach when I had no API key, reviewed the results and decided what goes in this repo.

## What Claude did (Anthropic; Claude Opus 5.5 in Claude Code)
- Wrote the first draft script, `docs/run_eval_draft_2026-10-21.py`.
- Wrote the `checkedsql` package and its tests: the read-only guard, contract check, comparator,
  tie detector, wrong-answer check, replay mode, labels and report.
- Wrote the wrong answers in `data/wrong_answers.json`, and found the Quantity = 1 blind spot when one of them still matched.
- Drafted this README.
- Answered the 20 questions in the replay: 20 separate fresh subagents, one question each, prompts in
  `replays/prompts/`, replies verbatim in `replays/claude-code-subagents.json`.

The model that answered the questions and the model that wrote the checker are the same model family.
That is a real limitation: a checker can share the blind spots of the thing it checks.

## Data
- Chinook database, Luis Rocha, MIT License: see `data/NOTICE.md`.
