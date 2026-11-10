#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.846.0 A (#5520): the filter of the shared core on the server (kalmido/core/filters.py). Invented titles only.
freelancer-matrix: lists (a person without an organisation, the own project and filter)
 - the core alone (the module has no imports): conditions of rules.conds or of an area's older form (old), at most COND_MAX,
   no dicts left out; kflt_cond for value lists (in / is any, nin / isnot none, empty, no values = off); kflt_match: AND / OR,
   "is not" / "is none of" hold on top also with OR, an area may name fewer hard comparisons (the tasks: only nin);
   kflt_where: the same as SQL text with its parameters in order
 - the tasks through the core (GET /api/v1/tasks?filter_id=, kalmido/lists/filterrules.py filter_where): OR of priority and a
   text, "is none of" on top; an older rule (prios) hits the same tasks
   (the newsletter segments' rule through the core: tests/p2625_a_nwlseg_ui.js counts them against the fake service)
usage: p2846_a_filterkern_test.py <datadir>      (KMT_NOSTART=1 / P2846A_NOSTART=1: a running server)"""
import importlib.util
import os
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup

N = os.path.dirname(os.path.abspath(__file__))
sp = importlib.util.spec_from_file_location("kflt", os.path.join(N, "..", "kalmido", "core", "filters.py"))
K = importlib.util.module_from_spec(sp)
sp.loader.exec_module(K)

# ================================================================== the core alone
ITEMS = [{"id": 1, "tags": {"vip"}, "n": 5}, {"id": 2, "tags": {"vip", "press"}, "n": 1}, {"id": 3, "tags": {"press"}, "n": 3},
         {"id": 4, "tags": set(), "n": 0}]
HAS = {"tag": lambda x, y: y in x["tags"], "n": lambda x, y: x["n"] == y}
EMPTY = {"tag": None}
HAS_E = {**HAS, "tag": lambda x, y: (not x["tags"]) if y is None else y in x["tags"]}


def hit(rules, hard_ops=K.HARD, has=HAS, empty=None, old=None):
    return [x["id"] for x in ITEMS if K.kflt_match(x, rules, lambda c: K.kflt_cond(c, has, empty), old, hard_ops)]


check(hit({}) == [1, 2, 3, 4] and hit(None) == [1, 2, 3, 4] and hit({"conds": []}) == [1, 2, 3, 4], "no condition: every item")
check(hit({"conds": [{"f": "tag", "op": "in", "v": ["vip"]}]}) == [1, 2], "in: any of the values")
check(hit({"conds": [{"f": "tag", "op": "is", "v": ["press", "vip"]}]}) == [1, 2, 3], "is = in (a newsletter segment's row)")
check(hit({"conds": [{"f": "tag", "op": "nin", "v": ["press"]}]}) == [1, 4], "nin: none of the values")
check(hit({"conds": [{"f": "tag", "op": "in", "v": []}, {"f": "nope", "op": "in", "v": [1]}, {"f": "n", "op": "gt", "v": [1]}]}) == [1, 2, 3, 4],
      "no values, an unknown what, an unknown comparison: off")
r_or = {"op": "or", "conds": [{"f": "n", "op": "in", "v": [5]}, {"f": "tag", "op": "in", "v": ["press"]}, {"f": "tag", "op": "isnot", "v": ["vip"]}]}
check(hit(r_or) == [3], f"OR, but 'is not' holds on top: {hit(r_or)}")
check(hit({**r_or, "op": "and"}) == [], "AND: n 5 and press is nobody")
r_or2 = {"op": "or", "conds": [{"f": "tag", "op": "in", "v": ["press"]}, {"f": "tag", "op": "isnot", "v": ["vip"]}]}
check(hit(r_or2) == [3] and hit(r_or2, hard_ops=("nin",)) == [2, 3, 4],
      f"an area with only nin as hard: isnot is one of the OR parts ({hit(r_or2)} / {hit(r_or2, hard_ops=('nin',))})")
check(hit({"conds": [{"f": "tag", "op": "empty"}]}, has=HAS_E, empty=EMPTY) == [4], "empty: the catalog's empty value")
check(hit({"conds": [{"f": "n", "op": "empty"}]}, has=HAS_E, empty=EMPTY) == [1, 2, 3, 4], "empty without an empty value in the catalog: off")
old = lambda r: [{"f": "tag", "op": "in", "v": r["tags"]}] if r.get("tags") else []  # noqa: E731
check(hit({"tags": ["press"]}, old=old) == [2, 3], "an older stored form converts through old")
check(hit({"tags": ["press"]}) == [1, 2, 3, 4], "without old an older form has no conditions")
check(hit({"tags": ["press"], "conds": [{"f": "tag", "op": "in", "v": ["vip"]}]}, old=old) == [1, 2], "conds wins over the older form")
many = [{"f": "n", "op": "in", "v": [0]}] + [{"f": "nope", "op": "in", "v": [1]}] * K.COND_MAX + [{"f": "n", "op": "in", "v": [5]}]
check(len(K.kflt_conds({"conds": many})) == K.COND_MAX and hit({"conds": many}) == [4], "at most COND_MAX conditions, the rest left out")
check(K.kflt_conds({"conds": [1, "x", None, {"f": "n"}]}) == [{"f": "n"}], "conditions that are no objects are left out")
sql = {"n": lambda c: ("n=ANY(?)", [c["v"]]) if c.get("v") else None}
w, a = K.kflt_where({"op": "or", "conds": [{"f": "n", "op": "in", "v": [1]}, {"f": "n", "op": "nin", "v": [2]}, {"f": "n", "op": "in", "v": [3]}]},
                    lambda c: sql[c["f"]](c))
check(w == "(n=ANY(?) AND (n=ANY(?) OR n=ANY(?)))" and a == [[2], [1], [3]], f"kflt_where: the hard part first, the rest by op: {w} {a}")
check(K.kflt_where({"conds": [{"f": "n", "op": "in", "v": []}]}, lambda c: sql[c["f"]](c)) == (None, []), "kflt_where: nothing on = None")
check(K.kflt_or([]) == ("FALSE", []) and K.kflt_or([("a", [1]), ("b", [2])]) == ("COALESCE((a OR b), FALSE)", [1, 2]), "kflt_or")

# ================================================================== the tasks through the core, without an organisation
fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="P2846A")
A = setup()
FID, F = freelancer(B, A)
L = F.post(B + "/api/lists", json={"name": "Own project"}).json()["id"]


def task(title, **b):
    r = F.post(B + "/api/tasks", json={"title": title, "list_id": L, **b})
    assert r.ok, r.text
    return r.json()["id"]


T1 = task("Crash on login", priority=5)
T2 = task("Tidy the crash docs", priority=1)
T3 = task("Plan the launch", priority=3)
tok = F.post(B + "/api/me/tokens", json={"name": "flt", "scopes": ["read"]})
assert tok.ok, tok.text
TH = {"Authorization": "Bearer " + tok.json()["token"]}


def ids(rules):
    r = F.post(B + "/api/filters", json={"name": "F", "rules": rules})
    assert r.ok, r.text
    q = requests.get(B + "/api/v1/tasks", headers=TH, params={"filter_id": r.json()["id"]})
    assert q.ok, q.text
    return sorted(t["id"] for t in q.json()["data"])


r_or = {"op": "or", "conds": [{"f": "prio", "op": "in", "v": [5]}, {"f": "text", "op": "has", "v": "crash"}]}
check(ids(r_or) == sorted([T1, T2]), "freelancer, the API: priority high OR the text crash")
check(ids({**r_or, "conds": r_or["conds"] + [{"f": "prio", "op": "nin", "v": [1]}]}) == [T1], "'is none of' holds on top, also with OR")
check(ids({"prios": [3, 5]}) == sorted([T1, T3]), "an older rule (prios) hits the same tasks")
check(ids({"op": "or", "conds": [{"f": "text", "op": "isnot", "v": "crash"}, {"f": "prio", "op": "in", "v": [3]}]}) == sorted([T1, T2, T3]),
      "tasks: a text row with another comparison stays a 'contains' part of the OR, as before")


sys.exit(done("p2846_a_filterkern"))
