"""Compare a model's result rows with the gold rows.

The comparison ignores row order and column names, rounds floats to 2 places,
and nothing else. It can be wrong in both directions, which is why every
mismatch is read by a person before it is counted as a model error:
  - a false negative: the model's answer is right but shaped differently
    (an extra column, the same number as an int vs a float, rows in a
    different grouping);
  - a false positive: different SQL that happens to return the same rows.
"""


def _cell(v):
    return round(v, 2) if isinstance(v, float) else v


def normalize(rows):
    norm = [tuple(_cell(v) for v in r) for r in rows]
    return sorted(norm, key=lambda r: tuple((type(v).__name__, str(v)) for v in r))


def compare(pred_rows, gold_rows):
    """Returns (match, reason). reason explains a mismatch in a few words."""
    p, g = normalize(pred_rows), normalize(gold_rows)
    if p == g:
        return True, None
    if len(p) != len(g):
        return False, f"row count {len(p)} vs gold {len(g)}"
    pw = {len(r) for r in p}
    gw = {len(r) for r in g}
    if pw != gw:
        return False, f"column count {sorted(pw)} vs gold {sorted(gw)}"
    return False, "same shape, different values"
