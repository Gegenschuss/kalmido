#!/usr/bin/env python3
"""2.369.5 (#2517): the rest of the layer clean-up, checked without a container.
 - need_person() in kalmido/agents/core.py is THE "people only" gate: an agent gets Denied(code, msg); no inline
   `if is_agent(g.user): raise Denied(...)` is left (the code / text of each place moved into the call unchanged)
 - joined_lists_sql() in kalmido/core/access.py is THE raw "lists an account owns or is a member of" subquery; the
   hand-written copies of it are gone (vis_sql stays the request's own scope)
 - tools/check_layers.py is green and the budget of the needless function-local imports is below 1.000 (it was 2.022)
 - the module-level import graph has no import cycle beyond the three known pairs (a pulled-up import must never close one:
   the module would load half-done)
freelancer-matrix: n/a (no route of its own; the gates and queries keep their behaviour)
usage: p2369_5_layers_test.py"""
import ast
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KAL = os.path.join(ROOT, "kalmido")
sys.path.insert(0, os.path.join(ROOT, "tools"))
from kt import FAILS, OKS, check  # noqa: E402  2.192.0 (#2514): shared helpers (tests/kt.py)
import check_layers as CL  # noqa: E402


def ck(what, cond, detail=None):
    check(cond, what if cond or detail is None else f"{what}: {str(detail)[:600]}")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def pyfiles():
    for dp, _, fs in os.walk(KAL):
        for fn in sorted(fs):
            if fn.endswith(".py"):
                yield os.path.join(dp, fn)


# ---- need_person
core = read(os.path.join(KAL, "agents", "core.py"))
fn = next((n for n in ast.parse(core).body if isinstance(n, ast.FunctionDef) and n.name == "need_person"), None)
ck("need_person() is defined in agents/core.py", fn is not None)
if fn is not None:
    src = ast.get_source_segment(core, fn)
    ck("need_person(code=403, msg=None) raises Denied(code, msg) for an agent",
          [a.arg for a in fn.args.args] == ["code", "msg"] and "if is_agent(g.user):" in src and "raise Denied(code, msg)" in src,
          src)
inline = []
for p in pyfiles():
    if p.endswith(os.path.join("agents", "core.py")):
        continue  # need_person() itself
    lines = read(p).split("\n")
    for i, ln in enumerate(lines[:-1]):
        m = re.match(r"^(\s*)if is_agent\(g\.user\):\s*(#.*)?$", ln)
        if m and re.match(m.group(1) + r"    raise Denied\(", lines[i + 1]):
            after = lines[i + 2] if i + 2 < len(lines) else ""
            if not after.strip() or len(after) - len(after.lstrip()) <= len(m.group(1)):
                inline.append(f"{os.path.relpath(p, ROOT)}:{i + 1}")
ck("no inline 'if is_agent(g.user): raise Denied(...)' gate is left (need_person)", not inline, inline[:10])
uses = sum(read(p).count("need_person(") for p in pyfiles())
ck("need_person() is used in many places (46 gates moved)", uses >= 46, uses)

# ---- joined_lists_sql
acc = read(os.path.join(KAL, "core", "access.py"))
ck("joined_lists_sql() in core/access.py: owner first, then member (two ?)",
      'return "(SELECT id FROM lists WHERE owner_id=? UNION SELECT list_id FROM list_members WHERE user_id=?)"' in acc)
pats = [re.compile(r"owner_id ?= ?\? OR (l\.)?id IN\s*\(SELECT list_id FROM list_members WHERE user_id ?= ?\?\)"),
        re.compile(r"SELECT id( AS l)? FROM lists WHERE owner_id ?= ?\?\s+UNION\s+SELECT list_id FROM list_members WHERE user_id ?= ?\?")]
left = []
for p in pyfiles():
    if p.endswith(os.path.join("core", "access.py")):
        continue
    s = read(p)
    for pt in pats:
        left += [f"{os.path.relpath(p, ROOT)}: {m.group(0)[:60]}" for m in pt.finditer(s)]
ck("no hand-written copy of the owner-or-member subquery is left (joined_lists_sql)", not left, left[:10])

# ---- check_layers + budget
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_layers.py"), "-v"], capture_output=True, text=True)
ck("tools/check_layers.py is green", r.returncode == 0, (r.stdout + r.stderr)[-800:])
budget = json.loads(read(os.path.join(ROOT, "tools", "layers_budget.json")))
ck("budget local_needless below 1.000 (was 2.022 before 2.369.5)", budget.get("local_needless", 10 ** 6) < 1000, budget)

# ---- no new import cycle at module level
CL.ROOT = ROOT
_, _, _, order = CL.layers()
pos = set(order)
graph = {}
for m in order:
    tree = ast.parse(read(os.path.join(KAL, *m.split(".")) + ".py"))
    graph[m] = set()

    def tops(body, m=m):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(n, ast.ImportFrom):
                t = CL.target(m, n)
                if t in pos:
                    graph[m].add(t)
                elif t:
                    graph[m].update(f"{t}.{a.name}" for a in n.names if f"{t}.{a.name}" in pos)
                continue
            tops(list(ast.iter_child_nodes(n)))
    tops(tree.body)
    graph[m].discard(m)
sys.setrecursionlimit(10000)
idx, low, stack, on, comps, cnt = {}, {}, [], set(), [], [0]


def scc(v):
    idx[v] = low[v] = cnt[0]
    cnt[0] += 1
    stack.append(v)
    on.add(v)
    for w in graph[v]:
        if w not in idx:
            scc(w)
            low[v] = min(low[v], low[w])
        elif w in on:
            low[v] = min(low[v], idx[w])
    if low[v] == idx[v]:
        comp = set()
        while True:
            w = stack.pop()
            on.discard(w)
            comp.add(w)
            if w == v:
                break
        if len(comp) > 1:
            comps.append(sorted(comp))


for v in order:
    if v not in idx:
        scc(v)
KNOWN_CYCLES = [["office.abschlag", "office.invoices"], ["office.bank", "office.bankrules"], ["office.cardlines", "office.cards"]]
new = [c for c in comps if c not in KNOWN_CYCLES]
ck("no import cycle at module level beyond the three known pairs", not new, new)

print(f"p2369_5_layers: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
