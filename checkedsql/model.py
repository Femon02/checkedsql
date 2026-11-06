"""One call to Claude per question, with the facts a reviewer needs about that call.

Each call records: the raw reply, the stop reason, which model actually answered
(a refusal can be re-run on a fallback model server-side), token usage, and an
estimated cost. Nothing about the reply is fixed up here; contract.py judges it.
"""
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# US$ per million tokens: (input, output, cache read). Cache writes cost 1.25x input.
# First-party API list prices as of 2026-10-06; check current pricing before quoting a cost.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
}


@dataclass
class Reply:
    text: str
    stop_reason: str
    requested_model: str
    served_by: str
    fell_back: bool
    request_id: str | None
    usage: dict = field(default_factory=dict)
    cost_usd: float | None = None


def _cost(model, inp, out, cache_read, cache_write):
    if model not in PRICES:
        return None
    pi, po, pr = PRICES[model]
    return (inp * pi + out * po + cache_read * pr + cache_write * pi * 1.25) / 1_000_000


def ask(client, system, question, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT):
    msg = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": question}],
        output_config={"effort": effort},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    text = "".join(b.text for b in msg.content if b.type == "text")

    u = msg.usage
    iterations = list(getattr(u, "iterations", None) or [])
    fell_back = any(getattr(it, "type", "") == "fallback_message" for it in iterations)

    # Cost per model that ran: with a fallback, the declined attempt and the rescue are billed separately.
    parts = iterations or [u]
    cost, known = 0.0, True
    for it in parts:
        c = _cost(getattr(it, "model", None) or msg.model,
                  it.input_tokens or 0, it.output_tokens or 0,
                  it.cache_read_input_tokens or 0, it.cache_creation_input_tokens or 0)
        if c is None:
            known = False
        else:
            cost += c

    return Reply(
        text=text,
        stop_reason=msg.stop_reason,
        requested_model=model,
        served_by=msg.model,
        fell_back=fell_back,
        request_id=getattr(msg, "_request_id", None),
        usage={"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
               "cache_read_input_tokens": u.cache_read_input_tokens or 0,
               "cache_creation_input_tokens": u.cache_creation_input_tokens or 0},
        cost_usd=round(cost, 6) if known else None,
    )
