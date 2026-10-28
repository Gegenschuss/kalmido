#!/usr/bin/env python3
"""2.187.0 B (#2476): the guard of the office rights -- every office route has an area (like tenant_coverage).
No container needed: reads kalmido/office/rights.py, kalmido/office/model.py and static/js/ with the parser.
 1. every route under /api/office/ is the rights page (/api/office/rights*) or ofr_area_of(its path) names an area
    (/api/office/<kind>: every kind of the master data, model.MD)
 2. every rule in SPECIAL_ROUTES / OWN_ROUTES / MANAGE_ROUTES / ANY_READ is a route of the server, the specials are known
    ones, OWN_ROUTES lie in areas that offer the level "own" (and never write the settings)
 3. every office menu point (static/js/areas.js OFM_ITEMS with go 'office/...') and every OFC_TABS key (office*.js) is an area
 4. the templates only name known areas / levels / specials; the staff template is "own" in every own area
usage: python3 tests/p2187_b_guard_test.py"""
import ast
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routes_ast import app_routes, norm  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


class _Plain(ast.NodeTransformer):
    """N_("x") -> "x", frozenset({...}) -> {...}, so the tables of rights.py read as literals."""
    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id in ("N_", "frozenset", "set", "tuple") and len(node.args) == 1:
            return node.args[0]
        return node


def _module(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    return src, ast.parse(src)


RSRC, RTREE = _module(os.path.join(ROOT, "kalmido", "office", "rights.py"))
T = {}
for node in RTREE.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        name = node.targets[0].id
        if name in ("OFFICE_AREAS", "MANAGE_ROUTES", "SPECIAL_ROUTES", "OWN_ROUTES", "ANY_READ", "LEVELS", "SPECIALS"):
            T[name] = ast.literal_eval(_Plain().visit(node.value))
check(all(k in T for k in ("OFFICE_AREAS", "MANAGE_ROUTES", "SPECIAL_ROUTES", "OWN_ROUTES", "ANY_READ", "LEVELS", "SPECIALS")),
      f"rights.py: the tables read as literals {sorted(T)}")
AREAS = T.get("OFFICE_AREAS", ())
AREA_KEYS = [a[0] for a in AREAS]
AREA_OWN = {a[0] for a in AREAS if a[4]}
SPECIAL_KEYS = {k for k, _ in T.get("SPECIALS", ())}
check(len(AREA_KEYS) == len(set(AREA_KEYS)) and len(AREA_KEYS) >= 20, f"areas: unique keys {AREA_KEYS}")
SEGS = [s for a in AREAS for s in a[3]]
check(len(SEGS) == len(set(SEGS)), f"areas: every path segment in one area only {sorted(s for s in SEGS if SEGS.count(s) > 1)}")
check(all(a[5] in ("member", "admin") for a in AREAS), "areas: legacy is member or admin")

# ofr_area_of exactly as rights.py has it (its source, with the same _SEG)
fn = next((n for n in RTREE.body if isinstance(n, ast.FunctionDef) and n.name == "ofr_area_of"), None)
check(fn is not None, "rights.py: ofr_area_of")
NS = {"_SEG": sorted(((s, a[0]) for a in AREAS for s in a[3]), key=lambda x: -len(x[0]))}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "rights.py", "exec"), NS)  # noqa: S102 -- the repository's own function
area_of = NS["ofr_area_of"]

_, MTREE = _module(os.path.join(ROOT, "kalmido", "office", "model.py"))
KINDS = []
for node in MTREE.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", "") == "MD" and isinstance(node.value, ast.Dict):
        KINDS = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
check(len(KINDS) >= 5, f"model.MD: the master data kinds {KINDS}")

# ---- 1. every office route has an area
FOUND, PROBLEMS = app_routes(ROOT)
for p in PROBLEMS:
    check(False, f"route the guard cannot check: {p}")
OFFICE = sorted(r for r in FOUND if r.split(" ", 1)[1].startswith("/api/office/"))
check(len(OFFICE) > 200, f"office routes found ({len(OFFICE)})")
for r in OFFICE:
    meth, path = r.split(" ", 1)
    if path.startswith("/api/office/rights"):
        continue
    if path.startswith("/api/office/{}"):  # /api/office/<kind>[/<int:rid>]: one area per kind
        miss = [k for k in KINDS if area_of(path.replace("/api/office/{}", "/api/office/" + k, 1)) is None]
        check(not miss, f"{r}: kinds without an area {miss}")
        continue
    check(area_of(path) is not None, f"{r}: no office area (rights.py OFFICE_AREAS)")
check(area_of("/api/office/books/receipts") == "receipts" and area_of("/api/office/books") == "books", "longest segment wins")
check(area_of("/api/office/trips/vma.csv") == "travel" and area_of("/api/office/logbook.csv") == "logbook", "a file suffix keeps the area")
check(area_of("/api/office/docsx") is None and area_of("/api/officex/docs") is None, "no prefix match")

# ---- 2. the rule tables name real routes
NORMED = set(FOUND)
for x, sp in T.get("SPECIAL_ROUTES", {}).items():
    meth, rule = x.split(" ", 1)
    check(f"{meth} {norm(rule)}" in NORMED, f"SPECIAL_ROUTES: {x} is no route")
    check(sp in SPECIAL_KEYS and sp != "rights", f"SPECIAL_ROUTES: {x} -> unknown special {sp}")
    check(area_of(rule) is not None, f"SPECIAL_ROUTES: {x} has no area")
for x in T.get("OWN_ROUTES", ()):
    meth, rule = x.split(" ", 1)
    check(f"{meth} {norm(rule)}" in NORMED, f"OWN_ROUTES: {x} is no route")
    check(area_of(rule) in AREA_OWN, f"OWN_ROUTES: {x} lies in {area_of(rule)}, which has no level own")
    check(meth == "GET" or rule not in T.get("MANAGE_ROUTES", ()), f"OWN_ROUTES: {x} writes a manage route")
    check(x not in T.get("SPECIAL_ROUTES", {}), f"OWN_ROUTES: {x} needs a special (staff never has one)")
RULES = {r.split(" ", 1)[1] for r in FOUND}
for rule in list(T.get("MANAGE_ROUTES", ())) + list(T.get("ANY_READ", ())):
    check(norm(rule) in RULES, f"MANAGE_ROUTES / ANY_READ: {rule} is no route")
# exports, billing are never "own"
# 2.187.1 (#2735): the person's own reports (filtered like the lists) are "own" -- exactly these four
OWN_REPORTS = {"GET /api/office/trips/report", "GET /api/office/trips/vma", "GET /api/office/meals/report", "GET /api/office/logbook/report"}
for x in T.get("OWN_ROUTES", ()):
    check(not re.search(r"(report|\.csv|\.pdf$|\.zip|\.xlsx|/bill|/unbill|/close|/unlock|/trip$|/vma)", x) or x.endswith("/<int:mid>/pdf")
          or x in OWN_REPORTS, f"OWN_ROUTES: {x} looks like a report / export / billing step")

# ---- 3. the office menu points and tabs are areas
JS = os.path.join(ROOT, "static", "js")
with open(os.path.join(JS, "areas.js"), encoding="utf-8") as f:
    areas_js = f.read()
m = re.search(r"OFM_ITEMS\s*=\s*\[(.*?)\];", areas_js, re.S)
check(m is not None, "areas.js: OFM_ITEMS")
items = re.findall(r"\{key:\s*'([^']+)',\s*go:\s*'([^']+)'([^\n]*)", m.group(1) if m else "")
check(len(items) >= 15, f"areas.js: menu points found {[i[:2] for i in items]}")
for key, go, rest in items:
    if go.startswith("office/"):
        lvk = re.search(r"lvk:\s*'([^']+)'", rest)  # 2.380.0 B (#3409): invoices take the rights of the quotations' area
        check((lvk.group(1) if lvk else key) in AREA_KEYS, f"areas.js OFM_ITEMS: menu point {key} is no office area")
tabs = set()
TAB_AREA = {}  # office.js ofr_area: tabs that use another area's rights (receipts -> books, invoices -> offers)
for fn_ in sorted(glob.glob(os.path.join(JS, "office*.js"))):
    with open(fn_, encoding="utf-8") as f:
        src = f.read()
    oa = re.search(r"const ofr_area = [^\n]*", src)
    if oa:
        TAB_AREA.update(re.findall(r"t === '([a-z_-]+)' \? '([a-z_-]+)'", oa.group(0)))
    d = re.search(r"const OFC_TABS\s*=\s*\[(.*?)\];", src, re.S)
    if d:
        tabs |= set(re.findall(r"\[\s*'([a-z_-]+)',\s*'", d.group(1)))
    tabs |= set(re.findall(r"OFC_TABS\.splice\([^\n]*?0,\s*(?:/\*\*[^*]*\*/\s*)?\(?\[\s*'([a-z_-]+)'", src))
check({"offers", "settings", "travel", "books"} <= tabs, f"office*.js: OFC_TABS keys found {sorted(tabs)}")
for t in sorted(tabs):
    check(TAB_AREA.get(t, t) in AREA_KEYS, f"OFC_TABS: tab {t} is no office area")

# ---- 4. the templates
tpl = next((n for n in RTREE.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "TEMPLATES"), None)
check(tpl is not None, "rights.py: TEMPLATES")
check('"staff"' in RSRC and "own=tuple(AREA_OWN)" in RSRC, "the staff template: own in every own area")
check(AREA_OWN >= {"receipts", "travel", "logbook", "meals", "time"}, f"own areas: receipts, travel, logbook, meals, times {sorted(AREA_OWN)}")

print(f"\np2187_b_guard: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
