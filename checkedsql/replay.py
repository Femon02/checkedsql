"""Offline mode: score replies that were collected earlier, without calling the API.

A replies file is JSON:

    {"model": "claude-opus-5-5",
     "how": "one sentence on how the replies were produced",
     "replies": {"1": "SELECT ...", "2": "CANNOT_ANSWER", ...}}

Every reply goes through exactly the same contract check, read-only database and
comparator as a live run. What a replay cannot give you: token counts, cost, the
stop reason, or which model actually served the request. Those fields are recorded
as unknown, never as zero, and the report says the run was a replay.
"""
import json
from pathlib import Path
from types import SimpleNamespace

REPLAY_MODEL = "replay"   # not in model.PRICES, so cost is recorded as unknown


def load(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("model", "how", "replies"):
        if key not in data:
            raise ValueError(f"{path}: missing {key!r}")
    return data


class ReplayClient:
    """Stands in for anthropic.Anthropic(): answers each question from a replies file."""

    def __init__(self, replies_by_id, questions):
        by_text = {q["question"]: str(q["id"]) for q in questions}
        missing = [i for i in by_text.values() if i not in replies_by_id]
        if missing:
            raise ValueError(f"replies file has no reply for question(s) {', '.join(missing)}")
        self._replies = {text: replies_by_id[i] for text, i in by_text.items()}
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        text = self._replies[kw["messages"][0]["content"]]
        usage = SimpleNamespace(input_tokens=None, output_tokens=None, cache_read_input_tokens=None,
                                cache_creation_input_tokens=None, iterations=None)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                               stop_reason=None, model=REPLAY_MODEL, usage=usage)
