"""2.846.0 (#5520): the filter of the shared core on the server (docs/dev/kern.md "Filter"); the same rules as
static/js/fltkern.js in the browser (keep the two in step).

A filter is rules = {op: "and" | "or", conds: [{f, op, v, ...}]}. "is none of" (nin) and "is not" (isnot) always hold on top,
also with OR (#4478); the other conditions are combined by op. A condition that is off (no values, an empty text, an unknown
"what") counts as if it were not there. Rules come from a client: whatever does not fit is off and never reaches SQL as text.

An area passes its catalog as functions:
- kflt_where(rules, cond, old=None): cond(cnd) -> (sql, args) that is TRUE / FALSE, or None (off) -> one SQL condition or None
  (the tasks: kalmido/lists/filterrules.py filter_where)
- kflt_match(item, rules, cond, old=None): cond(cnd) -> test(item) -> bool, or None -> True / False for one item; kflt_cond
  builds such a test from a has table {f: (item, x) -> bool} (the newsletter segments: kalmido/newsletter/sync.py nwl_match)
- old(rules) -> conditions: the area's older stored form (optional); rules without a conds list and without old have none.
"""

COND_MAX, VAL_MAX = 100, 500  # more conditions / values than a dialog ever makes: the rest is left out
HARD = ("nin", "isnot")  # hold always, also with OR
SOFT_LIST = ("in", "is")  # a value list: any of the values


def kflt_conds(rules, old=None):
    """The conditions of rules (at most COND_MAX): rules.conds, else the area's conversion of its older form."""
    r = rules if isinstance(rules, dict) else {}
    conds = r["conds"] if isinstance(r.get("conds"), list) else (old(r) if old else [])
    return [x for x in conds[:COND_MAX] if isinstance(x, dict)]


def kflt_or(parts):
    """OR over the parts (sql, args); no part = matches nothing. Every part is TRUE or FALSE, never NULL (NOT stays exact)."""
    if not parts:
        return "FALSE", []
    return "COALESCE((" + " OR ".join(p[0] for p in parts) + "), FALSE)", [a for p in parts for a in p[1]]


def kflt_where(rules, cond, old=None, hard_ops=HARD):
    """The rules -> (one SQL condition or None, args): the hard conditions (hard_ops: an area may know fewer) always, the others
    combined by rules.op."""
    r = rules if isinstance(rules, dict) else {}
    hard, soft = [], []
    for cnd in kflt_conds(r, old):
        p = cond(cnd)
        if p:
            (hard if cnd.get("op") in hard_ops else soft).append(p)
    if soft:
        hard.append(("(" + (" OR " if r.get("op") == "or" else " AND ").join(p[0] for p in soft) + ")", [a for p in soft for a in p[1]]))
    if not hard:
        return None, []
    return "(" + " AND ".join(p[0] for p in hard) + ")", [a for p in hard for a in p[1]]


def kflt_cond(cnd, has, empty=None):
    """A value list condition -> test(item) or None (off): has = {f: (item, x) -> the item has the one value x}, empty = {f: the
    value "is empty" stands for}. op in / is = any of the values, nin / isnot = none of them, empty."""
    fn = has.get(cnd.get("f")) if isinstance(cnd.get("f"), str) else None
    if not fn:
        return None
    op, v = cnd.get("op"), cnd.get("v")
    if op == "empty":
        return (lambda x: fn(x, empty[cnd["f"]])) if empty and cnd["f"] in empty else None
    if not isinstance(v, list) or not v:
        return None
    vs = v[:VAL_MAX]
    if op in HARD:
        return lambda x: not any(fn(x, y) for y in vs)
    return (lambda x: any(fn(x, y) for y in vs)) if op in SOFT_LIST else None


def kflt_match(item, rules, cond, old=None, hard_ops=HARD):
    """One item against the rules: the hard conditions always, the others combined by rules.op; no condition = True."""
    r = rules if isinstance(rules, dict) else {}
    soft = []
    for cnd in kflt_conds(r, old):
        t = cond(cnd)
        if not t:
            continue
        if cnd.get("op") in hard_ops:
            if not t(item):
                return False
        else:
            soft.append(t)
    if not soft:
        return True
    return any(t(item) for t in soft) if r.get("op") == "or" else all(t(item) for t in soft)
