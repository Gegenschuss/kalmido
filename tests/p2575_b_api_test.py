#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.575.0 B (#3966): the start state without the values every task has. Own container (start.sh). Invented texts only.
A person without an organisation (freelancer-matrix: tasks):
 - GET /api/state?td=1 (and with lz=1) leaves out the keys of a task at their default (None / '' / 0 / [] / {}) and carries
   the table (tdef); a set value (priority, due, tag, pinned) stays in it
 - without td (older clients, lz=1 alone) every key as before, no tdef
 - a long note: content stays out (content_n), it does not come back as '' when filled
 - GET /api/state/lists?td=1 the same; without td every key
 - the client's fill function (static/js/liveparts.js tdFill, run in node) makes the lean tasks equal to the whole ones;
   applyState, lzLoad and the delta use it before the tasks are read
 - 2.1117.0 (#6023): td=2 (what the client asks now) also sends created_at / updated_at / deleted_at without their zone +00:00
   and names them in tutc; tdFill puts it back (whole tasks equal to the whole state's), td=1 keeps the zone (older clients)
usage: p2575_b_api_test.py <datadir>"""
import json
import os
import re
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

ROOT = os.path.dirname(N)


def src(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


def node_fill(tasks, tdef, tutc=None):
    """the tasks filled by the client's own tdFill (cut out of liveparts.js), run in node"""
    m = re.search(r"^function tdFill\(.*?^}\n", src("static/js/liveparts.js"), re.M | re.S)
    assert m, "tdFill not found in liveparts.js"
    js = ("const S = {tdef: null, tutc: null};\n" + m.group(0) +
          "let d = '';process.stdin.on('data', x => d += x).on('end', () => { const j = JSON.parse(d); "
          "process.stdout.write(JSON.stringify(tdFill(j.tasks, j.tdef, j.tutc))); });")
    r = subprocess.run(["node", "-e", js], input=json.dumps({"tasks": tasks, "tdef": tdef, "tutc": tutc}), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


if not kt.nostart("P2575B"):
    kt.fresh()
A = kt.setup()
fid, F = freelancer(B, A, "frida")
L = F.post(B + "/api/lists", json={"name": "Werkstatt", "kind": "project"}).json()["id"]
plain = F.post(B + "/api/tasks", json={"title": "Schrauben sortieren", "list_id": L}).json()["id"]
setv = F.post(B + "/api/tasks", json={"title": "Regal streichen", "list_id": L, "priority": 3, "due": "2026-12-01",
                                     "tags": ["farbe"]}).json()["id"]
assert F.patch(B + f"/api/tasks/{setv}", json={"pinned": 1}).ok
longn = F.post(B + "/api/tasks", json={"title": "Plan lesen", "list_id": L, "content": "Lange Notiz " * 40}).json()["id"]

full = F.get(B + "/api/state").json()
lean = F.get(B + "/api/state?td=1").json()
old = F.get(B + "/api/state?lz=1&lzl=").json()
ft = {t["id"]: t for t in full["tasks"]}
lt = {t["id"]: t for t in lean["tasks"]}
td = lean.get("tdef")
check(isinstance(td, dict) and td.get("priority") == 0 and td.get("tags") == [] and td.get("due") is None, "td=1: the table comes along (tdef)")
check("tdef" not in full and "tdef" not in old, "without td (also lz=1 alone): no tdef")
for k in ("priority", "due", "pinned", "tags", "completed_at", "comment_count", "fields", "assignee_id", "content"):
    check(k in ft[plain] and k in {t["id"]: t for t in old["tasks"]}[plain], f"without td: '{k}' in the task as before")
p = lt[plain]
check(all(k not in p for k in ("priority", "due", "pinned", "tags", "completed_at", "comment_count", "fields", "assignee_id", "content")),
      f"td=1: the defaults are left out ({sorted(p)})")
check({"id", "title", "list_id", "sort", "created_at", "updated_at"} <= set(p), "td=1: id, title, list, order, times stay")
s = lt[setv]
check(s.get("priority") == 3 and s.get("due") == "2026-12-01" and s.get("pinned") == 1 and s.get("tags") == ["farbe"],
      f"td=1: values that are set stay ({ {k: s.get(k) for k in ('priority', 'due', 'pinned', 'tags')} })")
check(len(json.dumps(lean["tasks"])) < len(json.dumps(full["tasks"])) * 0.7, "td=1: the tasks are clearly smaller")
check("content" not in lt[longn] and lt[longn].get("content_n", 0) > 200, "a long note: no content, its length (content_n)")

filled = {t["id"]: t for t in node_fill(lean["tasks"], td)}
check(filled == ft, "the client's tdFill makes the lean tasks equal to the whole state's "
                    f"({[i for i in ft if filled.get(i) != ft[i]][:3]})")
check("content" not in filled[longn], "tdFill: a long note's content stays out (content_n)")
check(filled[plain]["tags"] == [] and filled[plain]["fields"] == {}, "tdFill: [] / {} back")

ls_full = F.get(B + f"/api/state/lists?ids={L}").json()
ls_lean = F.get(B + f"/api/state/lists?td=1&ids={L}").json()
check("tdef" not in ls_full and "priority" in {t["id"]: t for t in ls_full["tasks"]}[plain], "/api/state/lists without td: every key")
check(ls_lean.get("tdef") == td and "priority" not in {t["id"]: t for t in ls_lean["tasks"]}[plain], "/api/state/lists?td=1: lean + tdef")
check({t["id"]: t for t in node_fill(ls_lean["tasks"], ls_lean["tdef"])} == {t["id"]: t for t in ls_full["tasks"]},
      "/api/state/lists?td=1 filled = without td")

# 2.1117.0 (#6023): td=2 = td=1 + the points in time without their zone (tutc); td=1 keeps it (older clients)
z2 = F.get(B + "/api/state?td=2").json()
zt = {t["id"]: t for t in z2["tasks"]}
check(z2.get("tdef") == td and z2.get("tutc") == ["created_at", "updated_at", "deleted_at"] and "tutc" not in lean,
      "td=2: tdef + tutc; td=1 without tutc")
check(ft[plain]["updated_at"].endswith("+00:00") and lt[plain]["updated_at"] == ft[plain]["updated_at"], "td=1: the times keep +00:00")
check(zt[plain]["created_at"] == ft[plain]["created_at"][:-6] and not zt[setv]["updated_at"].endswith("+00:00"),
      f"td=2: the times without the zone ({zt[plain]['created_at']})")
check(len(json.dumps(z2["tasks"])) < len(json.dumps(lean["tasks"])), "td=2: smaller than td=1")
filled2 = {t["id"]: t for t in node_fill(z2["tasks"], z2["tdef"], z2["tutc"])}
check(filled2 == ft, f"td=2 filled by tdFill = the whole state ({[i for i in ft if filled2.get(i) != ft[i]][:3]})")
check({t["id"]: t for t in node_fill(full["tasks"], td, z2["tutc"])} == ft, "tdFill with tutc leaves whole tasks (the delta's) as they are")
zz = node_fill([{"id": 1, "created_at": "2026-11-13T10:00:00.000Z", "updated_at": "2026-11-13T10:00:00+02:00"}], {}, z2["tutc"])[0]
check(zz["created_at"].endswith("Z") and zz["updated_at"].endswith("+02:00"), f"tdFill: a time with its zone (an offline task's Z) stays {zz}")
ls2 = F.get(B + f"/api/state/lists?td=2&ids={L}").json()
check(ls2.get("tutc") == z2["tutc"] and {t["id"]: t for t in node_fill(ls2["tasks"], ls2["tdef"], ls2["tutc"])} == {t["id"]: t for t in ls_full["tasks"]},
      "/api/state/lists?td=2 filled = without td")

# the client asks with td (2 since 2.1117.0) and fills before any use (one function)
core, lp = src("static/js/core.js"), src("static/js/liveparts.js")
ap = core[core.index("function applyState("):]
check(ap.index("tdFill(j.tasks)") < ap.index("S.tasks = new Map(j.tasks"), "applyState fills before it takes the tasks")
check("'/api/state?') + 'td=2&'" in core and "S.tutc = j.tutc" in ap, "the start state is asked with td=2 (+ tutc kept)")  # 2.1117.0 (#6023): was td=1
lz = lp[lp.index("async function lzLoad("):]
check("/api/state/lists?td=2&" in lz and "j.tutc || S.tutc" in lz and lz.index("tdFill(j.tasks") < lz.index("S.tasks.set(t.id, t)"), "lzLoad asks td=2 and fills first")  # 2.1117.0 (#6023): was td=1
dl = lp[lp.index("async function lpDelta("):]
check(dl.index("tdFill(j.tasks)") < dl.index("S.tasks.set(t.id, t)"), "the delta fills before it takes the tasks")
check(lp.count("function tdFill(") == 1 and core.count("function tdFill(") == 0, "one fill function")
sys.exit(kt.done("p2575_b_api"))
