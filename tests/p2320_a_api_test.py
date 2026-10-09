#!/usr/bin/env python3
"""2.32.0 API tests, part A: views built from blocks (#1063) and the project page (#983).
 - the view settings view_today / view_time / view_agents / view_projects: {order, hidden, half, full, opts, mobile}
   cleaned and stored per person ('' = default), bad shapes 400; the start page key "dashboard" takes the same shape and
   still only knows its cards
 - agents never arrange views: an agent's token is refused for the settings keys and the layout route, nothing stored
 - the project page: GET /api/lists/<id>/layout and the overview's "layout" {std, mine, can_std}; PUT scope standard only
   for the owner / list admins (403 for members), scope mine for everyone who sees the project, '' = back to the standard /
   the built-in default; a stranger gets 404; the standard reaches every member, an own arrangement only its person
 - rollback safety: lists.page_layout + table list_layouts are additive (the 2.31 columns untouched)
usage: p2320_a_api_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def settings(s):
    return s.get(B + "/api/state").json()["settings"]


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")

# ================================================================== #1063 the view settings
lay = {"order": ["tasks", "events", "wait"], "hidden": ["review"], "half": [], "full": ["events"], "opts": {"bar": {"period": "month"}},
       "mobile": {"order": ["wait", "tasks"], "hidden": ["events"]}}
r = A.patch(B + "/api/settings", json={"view_today": json.dumps(lay)})
check(r.ok, "#1063: view_today saved " + r.text[:80])
got = json.loads(settings(A)["view_today"])
check(got["order"] == ["tasks", "events", "wait"] and got["hidden"] == ["review"] and got["full"] == ["events"]
      and got["opts"] == {"bar": {"period": "month"}} and got["mobile"] == {"order": ["wait", "tasks"], "hidden": ["events"]},
      "#1063: ... and comes back cleaned " + json.dumps(got))
check(settings(Bo)["view_today"] == "", "#1063: per person: bob still has the default")
for k in ("view_time", "view_agents", "view_projects"):
    check(A.patch(B + "/api/settings", json={k: json.dumps({"order": ["a", "b"], "hidden": ["b"]})}).ok, f"#1063: {k} is a view key")
check(json.loads(settings(A)["view_time"]) == {"order": ["a", "b"], "hidden": ["b"]}, "#1063: view_time stored")
for bad, what in ((json.dumps({"order": ["x"], "nope": []}), "an unknown field"), (json.dumps({"order": "tasks"}), "order not a list"),
                  (json.dumps({"order": ["Bad Key"]}), "a bad block key"), (json.dumps({"order": ["a"] * 41}), "too many blocks"),
                  (json.dumps({"opts": {"bar": {"period": "x" * 41}}}), "a long option"), (json.dumps({"mobile": {"opts": {}}}), "opts inside mobile"),
                  ("{not json", "no json"), (json.dumps([1, 2]), "a list")):
    check(A.patch(B + "/api/settings", json={"view_today": bad}).status_code == 400, f"#1063: 400 for {what}")
check(json.loads(settings(A)["view_today"])["order"] == ["tasks", "events", "wait"], "#1063: a refused value changes nothing")
check(A.patch(B + "/api/settings", json={"view_today": ""}).ok and settings(A)["view_today"] == "", "#1063: '' = the default again")
# the start page: the same shape, still only its cards
r = A.patch(B + "/api/settings", json={"dashboard": json.dumps({"order": ["today", "wait"], "hidden": ["stats"], "full": ["today"], "mobile": {"order": ["wait"]}})})
check(r.ok and json.loads(settings(A)["dashboard"])["full"] == ["today"], "#1063: the start page takes widths and a phone arrangement " + r.text[:80])
check(A.patch(B + "/api/settings", json={"dashboard": json.dumps({"order": ["nope"]})}).status_code == 400, "#475: an unknown card is still 400")
check(A.patch(B + "/api/settings", json={"dashboard": json.dumps({"mobile": {"hidden": ["nope"]}})}).status_code == 400, "#1063: ... also in the phone arrangement")

# ================================================================== #1063 / #983 agents never arrange views
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}

# ================================================================== #983 the project page
P = A.post(B + "/api/lists", json={"name": "Website relaunch", "kind": "project"}).json()["id"]
A.put(B + f"/api/lists/{P}/members", json={"user_id": BOB, "role": "admin"})
A.put(B + f"/api/lists/{P}/members", json={"user_id": CAROL, "role": "edit"})
A.put(B + f"/api/lists/{P}/members", json={"user_id": CL, "role": "edit"})
ov = A.get(B + f"/api/lists/{P}/overview").json()
check(ov.get("layout") == {"std": "", "mine": "", "can_std": True}, "#983: the overview carries the layout (owner may set the standard) " + str(ov.get("layout")))
check(Ca.get(B + f"/api/lists/{P}/layout").json() == {"std": "", "mine": "", "can_std": False}, "#983: a member may not set the standard")
check(Bo.get(B + f"/api/lists/{P}/layout").json()["can_std"] is True, "#983: a list admin may")
STD = {"order": ["files", "desc", "ms"], "hidden": ["links"], "half": ["files"]}
r = A.put(B + f"/api/lists/{P}/layout", json={"layout": json.dumps(STD), "scope": "standard"})
check(r.ok and json.loads(r.json()["std"]) == STD, "#983: the owner sets the standard for everyone " + r.text[:100])
check(json.loads(Ca.get(B + f"/api/lists/{P}/overview").json()["layout"]["std"]) == STD, "#983: ... every member gets it")
check(Ca.put(B + f"/api/lists/{P}/layout", json={"layout": json.dumps({"order": ["ms"]}), "scope": "standard"}).status_code == 403, "#983: a member's standard is refused (403)")
check(json.loads(A.get(B + f"/api/lists/{P}/layout").json()["std"]) == STD, "#983: ... and changes nothing")
r = Bo.put(B + f"/api/lists/{P}/layout", json={"layout": {"order": ["desc", "files"], "hidden": ["links", "time"]}, "scope": "standard"})
check(r.ok and json.loads(r.json()["std"])["order"] == ["desc", "files"], "#983: a list admin sets it too (an object works as well as a json string) " + r.text[:80])
MINE = {"order": ["ms", "desc"], "hidden": ["files"], "mobile": {"order": ["desc"], "hidden": []}}
r = Ca.put(B + f"/api/lists/{P}/layout", json={"layout": json.dumps(MINE)})
check(r.ok and json.loads(r.json()["mine"]) == MINE, "#1063: a member overrides for themselves (scope mine by default) " + r.text[:100])
check(A.get(B + f"/api/lists/{P}/layout").json()["mine"] == "", "#1063: ... only for carol")
check(json.loads(A.get(B + f"/api/lists/{P}/layout").json()["std"])["order"] == ["desc", "files"], "#1063: ... the standard stays")
r = Ca.put(B + f"/api/lists/{P}/layout", json={"layout": "", "scope": "mine"})
check(r.ok and r.json()["mine"] == "" and dbx("SELECT COUNT(*) FROM list_layouts WHERE list_id=? AND user_id=?", (P, CAROL))[0][0] == 0,
      "#1063: Reset to the standard removes the own arrangement")
r = A.put(B + f"/api/lists/{P}/layout", json={"layout": None, "scope": "standard"})
check(r.ok and r.json()["std"] == "", "#983: '' / null = the built-in default again")
check(A.put(B + f"/api/lists/{P}/layout", json={"layout": json.dumps({"order": ["Bad"]})}).status_code == 400, "#983: a bad layout 400")
check(A.put(B + f"/api/lists/{P}/layout", json={"layout": "", "scope": "everyone"}).status_code == 400, "#983: an unknown scope 400")
check(A.put(B + f"/api/lists/{P}/layout", json={"layout": "", "extra": 1}).status_code == 400, "#983: an unknown field 400")
check(Da.get(B + f"/api/lists/{P}/layout").status_code == 404 and Da.put(B + f"/api/lists/{P}/layout", json={"layout": json.dumps({"order": ["ms"]})}).status_code == 404,
      "#983: someone outside the project gets 404")
plain = A.post(B + "/api/lists", json={"name": "Groceries"}).json()["id"]
check(A.put(B + f"/api/lists/{plain}/layout", json={"layout": json.dumps({"order": ["ms"]})}).status_code in (404, 409), "#983: a plain list has no project page")

# ---- agents: the token API has no route for it, the app routes refuse an agent; nothing stored
before = settings(A)
for method, url, body in (("PUT", B + f"/api/lists/{P}/layout", {"layout": json.dumps({"order": ["ms"]})}),
                          ("PUT", V + f"/lists/{P}/layout", {"layout": json.dumps({"order": ["ms"]})}),
                          ("PUT", B + f"/api/lists/{P}/layout", {"layout": json.dumps({"order": ["ms"]}), "scope": "standard"}),
                          ("PATCH", B + "/api/settings", {"view_today": json.dumps({"order": ["tasks"]})}),
                          ("PATCH", B + "/api/settings", {"dashboard": json.dumps({"order": ["today"]})}),
                          ("PATCH", V + "/me/settings", {"view_today": json.dumps({"order": ["tasks"]})})):
    r = requests.request(method, url, json=body, headers={**CLH, **H})
    check(r.status_code in (401, 403, 404, 405), f"#1063: an agent is refused: {method} {url.replace(B, '')} -> {r.status_code}")
check(dbx("SELECT COUNT(*) FROM list_layouts WHERE user_id=?", (CL,))[0][0] == 0 and dbx("SELECT page_layout FROM lists WHERE id=?", (P,))[0][0] == "",
      "#1063: ... nothing stored for the agent or the project")
check(dbx("SELECT COUNT(*) FROM user_settings WHERE user_id=? AND key IN ('view_today', 'dashboard') AND value != ''", (CL,))[0][0] == 0, "#1063: ... no view settings of the agent")
# the person themselves: their own session works (the same request as above)
check(A.put(B + f"/api/lists/{P}/layout", json={"layout": json.dumps({"order": ["ms"]})}).ok, "#1063: the person themselves may (session)")
ex = A.get(B + "/api/export.json").json()
check([x["list_id"] for x in ex.get("list_layouts", [])] == [P] and "view_today" in json.dumps(ex.get("settings", ex)), "#1063: the data export carries my own arrangements")

# ---- rollback safety: only additive changes
cols = [r[1] for r in dbx("PRAGMA table_info(lists)")]
check("page_layout" in cols and dbx("SELECT dflt_value FROM pragma_table_info('lists') WHERE name='page_layout'")[0][0] == "''", "rollback: lists.page_layout is a new column with a default")
check([r[1] for r in dbx("PRAGMA table_info(list_layouts)")] == ["list_id", "user_id", "layout", "updated_at"], "rollback: list_layouts is a new table")
# deleting the project removes the arrangements (cascade)
A.put(B + f"/api/lists/{P}/layout", json={"layout": json.dumps({"order": ["ms"]})})
A.delete(B + f"/api/lists/{P}")
A.post(B + "/api/trash/empty")
check(dbx("SELECT COUNT(*) FROM list_layouts WHERE list_id=?", (P,))[0][0] == 0 or dbx("SELECT COUNT(*) FROM lists WHERE id=?", (P,))[0][0] == 1,
      "#983: the arrangements go with the project")

print(f"p2320_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
