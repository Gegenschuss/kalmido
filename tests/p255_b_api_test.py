#!/usr/bin/env python3
"""2.55.0 API tests, part B (#1066 agents propose arrangements of views, the person accepts). Invented names only.
 - the right: scope layouts (off for new agents, not part of the legacy "write"); without it 403 on every route
 - whose views: a team agent only for a person who may chat with it and is in its organisation, a personal agent only for
   its owner; anyone else 404; the project page only when the list is shared with the agent, is a project and the person
   sees it (else 404)
 - reading: block keys, order, widths, heights, hidden -- never content, never the person's block switches
 - proposing: unknown block / hiding a fixed block / a wrong width: 400; a ready proposal job (kind layout) + News; a new
   one for the same view replaces the old one; a person cannot request the kind
 - deciding: only the person (not the agent's token, not another person); 👍 = a saved arrangement (source agent,
   prop:<id>) used at once, the person's switches stay; undo / redo; use=false keeps the view; 👎 discards; the agent gets
   the event job either way; an expired proposal: 409
 - rollback: no new table or column
tenant-matrix: agent, list
usage: p255_b_api_test.py <datadir>      (a fresh container; the suite restarts it in mode workspaces)"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

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


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def agent(name, scopes, org=None, owner=None):
    r = A.post(B + "/api/admin/agents", json={"username": name, "display_name": name.title(), "scopes": scopes})
    assert r.status_code == 201, r.text
    aid, t = r.json()["id"], r.json().get("token") or ""
    dbx("DELETE FROM org_members WHERE user_id=? AND org_id IS DISTINCT FROM ?", (aid, org), write=True)
    if org:
        dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (org, aid), write=True)
    dbx("UPDATE agents SET org_id=?, owner_id=? WHERE user_id=?", (org, owner, aid), write=True)
    return aid, tok(t)


def events(aid, kind="job"):
    return [json.loads(r[0]).get("data") or {} for r in dbx("SELECT payload FROM agent_events WHERE agent_id=? AND event=? ORDER BY id", (aid, kind))]


def setting(uid, key):
    r = dbx("SELECT value FROM user_settings WHERE user_id=? AND key=?", (uid, key))
    return r[0][0] if r else None


if not os.environ.get("P255B_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = ids["bob"], ids["carol"], ids["dave"], ids["erin"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
ORG2 = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok, "setup: carol joins Alpha")
AG, AGS = agent("lybot", ["read", "tasks:write", "comments", "layouts"], org=ORG)
AG0, AG0S = agent("plainbot", ["read", "tasks:write", "comments"], org=ORG)
PAG, PAGS = agent("erinbot", ["read", "comments", "layouts"], owner=ERIN)
A.post(B + "/api/auth/logout")
A, Bo, Ca, Da, Er = sess("alice"), sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ---- rollback: nothing new in the schema for part B (the proposal is an agent job of kind layout)
check(not dbx("SELECT 1 FROM information_schema.tables WHERE table_name='layout_proposals'"), "no new table layout_proposals")

# ---- the right: off by default, not in the legacy write
r = A.post(B + "/api/admin/agents", json={"username": "newbot", "display_name": "Newbot"})
NEW = r.json()["id"]
sc = dbx("SELECT scopes FROM api_tokens WHERE user_id=?", (NEW,))
check(r.status_code == 201 and sc and "layouts" not in sc[0][0], f"a new agent has no layouts right ({sc})")
spec = AGS.get(V + "/openapi.json").json()["paths"]
check(spec.get("/layouts/proposals", {}).get("post", {}).get("x-kalmido-scope") == "layouts"
      and spec.get("/layouts/{view}", {}).get("get", {}).get("x-kalmido-scope") == "layouts"
      and spec.get("/layouts/blocks", {}).get("get", {}).get("x-kalmido-scope") == "layouts", "OpenAPI: the three routes need layouts")
for path in ("/layouts/blocks?view=view_today", "/layouts/view_today"):
    r = AG0S.get(V + path)
    check(r.status_code == 403, f"without the right: GET {path} 403 ({r.status_code})")
r = AG0S.post(V + "/layouts/proposals", json={"view": "view_today", "name": "X", "layout": {"order": ["tasks"]}})
check(r.status_code == 403 and "Propose arrangements" in r.text, f"without the right: propose 403 with the name of the right ({r.status_code} {r.text[:120]})")

# ---- the project of Alpha shared with the agent; a list that is not a project; one not shared
r = Bo.post(B + "/api/lists", json={"name": "Film Alpha", "kind": "project"})
P = r.json()["id"]
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, P), write=True)
check(Bo.put(B + f"/api/lists/{P}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: share P with the agent")
r = Bo.post(B + "/api/lists", json={"name": "Plain", "kind": "list"})
L = r.json()["id"]
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, L), write=True)
Bo.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"})
r = Bo.post(B + "/api/lists", json={"name": "Hidden project", "kind": "project"})
PX = r.json()["id"]
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, PX), write=True)
Bo.post(B + "/api/tasks", json={"list_id": P, "title": "Top secret plan"})

# ---- reading
r = AGS.get(V + "/layouts/blocks", params={"view": "view_today", "user_id": BOB})
bl = r.json().get("blocks", []) if r.ok else []
check(r.ok and [b["key"] for b in bl][:2] == ["brief", "wait"] and any(b["key"] == "tasks" and b["fixed"] for b in bl),
      f"blocks of Today ({r.status_code} {r.text[:200]})")
r = AGS.get(V + "/layouts/dashboard", params={"user_id": BOB})
check(r.ok and r.json()["source"] == "default" and r.json()["layout"]["order"][0] == "today" and "search" in r.json()["layout"]["hidden"],
      f"the start page without an own arrangement: the default ({r.text[:200]})")
own = {"order": ["inbox", "brief"], "hidden": ["review"], "opts": {"tasks": {"compact": True}, "brief": {"lw": 3}}}
check(Bo.patch(B + "/api/settings", json={"view_today": json.dumps(own)}).ok, "setup: bob arranges Today")
r = AGS.get(V + "/layouts/view_today", params={"user_id": BOB})
lay = r.json().get("layout", {}) if r.ok else {}
ix = lambda o, k: o.index(k) if k in o else -1  # noqa: E731
check(r.ok and r.json()["source"] == "own" and len(lay["order"]) == 7 and ix(lay["order"], "inbox") < ix(lay["order"], "brief") and lay["hidden"] == ["review"]
      and lay["widths"]["brief"] == 3 and lay["widths"]["tasks"] == 6 and "compact" not in r.text,
      f"bob's Today: order, hidden, widths, no switches ({r.text[:300]})")
r = AGS.get(V + f"/layouts/list:{P}", params={"user_id": BOB})
check(r.ok and "kpis" in r.json()["layout"]["order"] and "Top secret" not in r.text and "Film Alpha" not in r.text,
      f"the project page: blocks only, no content ({r.status_code} {r.text[:200]})")

# ---- who and which views
for who, sess_, uid, what in ((AGS, "team", ERIN, "a person who does not share anything with it"),
                              (AGS, "team", DAVE, "a person of another organisation"),
                              (PAGS, "personal", BOB, "someone else than its owner")):
    r = who.get(V + "/layouts/view_today", params={"user_id": uid})
    check(r.status_code == 404, f"{sess_} agent, {what}: 404 ({r.status_code})")
r = PAGS.get(V + "/layouts/view_time")
check(r.ok and r.json()["user_id"] == ERIN, f"a personal agent works for its owner by default ({r.status_code} {r.text[:120]})")
for key, what in ((f"list:{PX}", "a project not shared with the agent"), (f"list:{L}", "a list that is no project"),
                  ("list:999999", "a list that does not exist")):
    r = AGS.get(V + f"/layouts/{key}", params={"user_id": BOB})
    check(r.status_code == 404, f"{what}: 404 ({r.status_code})")
r = AGS.get(V + f"/layouts/list:{P}", params={"user_id": CAROL})
check(r.status_code == 404, f"the project page of a person who does not see it: 404 ({r.status_code})")
r = AGS.get(V + "/layouts/settings", params={"user_id": BOB})
check(r.status_code == 400, f"an unknown view: 400 ({r.status_code})")
dbx("UPDATE agents SET list_ids=? WHERE user_id=?", (str(L), AG), write=True)
r = AGS.get(V + f"/layouts/list:{P}", params={"user_id": BOB})
check(r.status_code == 404, f"the agent limited to other lists: 404 ({r.status_code})")
dbx("UPDATE agents SET list_ids='' WHERE user_id=?", (AG,), write=True)

# ---- proposing: the checks
def prop(layout, view="view_today", who=AGS, **kw):
    return who.post(V + "/layouts/proposals", json={"view": view, "name": "Focus", "layout": layout, "user_id": BOB, **kw})


for bad, what in (({"order": ["tasks", "nosuch"]}, "an unknown block"), ({"hidden": ["tasks"]}, "hiding a fixed block"),
                  ({"widths": {"brief": 5}}, "a wrong width"), ({"heights": {"brief": 9}}, "a wrong height"),
                  ({"order": ["tasks"], "colour": "red"}, "an unknown field"), ({}, "nothing to change")):
    r = prop(bad)
    check(r.status_code == 400, f"proposal with {what}: 400 ({r.status_code} {r.text[:120]})")
r = prop({"order": ["nosuch"]})
check("nosuch" in r.text and "blocks" in r.text, f"the unknown block is named with the way to the blocks ({r.text[:160]})")
check(Bo.post(B + "/api/proposals", json={"agent_id": AG, "kind": "layout"}).status_code == 400, "a person cannot request kind layout")

r = prop({"order": ["tasks", "brief"], "hidden": ["inbox"], "widths": {"brief": 3}}, summary="Tasks first")
J1 = r.json().get("id") if r.status_code == 201 else None
check(r.status_code == 201 and r.json()["kind"] == "layout" and r.json()["proposal_state"] == "ready", f"proposal: 201 ({r.text[:200]})")
check(bool(dbx("SELECT 1 FROM notifications WHERE user_id=? AND kind='proposal' AND data->>'job' = ?", (BOB, str(J1)))), "News for bob")
r = prop({"order": ["tasks", "events"]})
J2 = r.json().get("id")
st = dict(dbx("SELECT id, prop_state FROM agent_jobs WHERE id IN (?, ?)", (J1, J2)))
check(st.get(J1) == "discarded" and st.get(J2) == "ready", f"a new proposal for the same view replaces the old one ({st})")
check(not dbx("SELECT 1 FROM notifications WHERE user_id=? AND kind='proposal' AND data->>'job' = ? AND read_at IS NULL", (BOB, str(J1))),
      "the replaced proposal's News is read")

r = prop({"order": ["done"]}, view="view_review")
check(r.status_code == 400, f"a proposal that changes nothing: 400 ({r.status_code})")
r = prop({"hidden": ["moved"]}, view="view_review")
check(r.status_code == 201 and r.json()["proposal"]["proposed"]["order"][0] == "done" and r.json()["proposal"]["proposed"]["hidden"] == ["moved"],
      f"left out = as it is: the order stays, one block hidden ({r.text[:200]})")
# ---- deciding: only the person
before = setting(BOB, "view_today")
for who, what in ((AGS, "the agent's token"), (Ca, "another person")):
    r = who.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0"]})
    check(r.status_code in (401, 403, 404), f"{what} cannot accept ({r.status_code})")
check(Ca.get(B + f"/api/proposals/{J2}").status_code == 404, "another person does not see the proposal")
check(setting(BOB, "view_today") == before, "nothing changed yet")
r = Bo.get(B + f"/api/proposals/{J2}")
v = r.json() if r.ok else {}
check(r.ok and ix(v.get("layout_now", {}).get("order", []), "inbox") < ix(v["layout_now"]["order"], "brief") and v["proposal"]["proposed"]["order"][0] == "tasks" and ix(v["proposal"]["proposed"]["order"], "tasks") < ix(v["proposal"]["proposed"]["order"], "events")
      and any(b["key"] == "tasks" for b in v.get("blocks", [])), f"the card has before / after and the block names ({r.text[:300]})")

# 👍 used at once
r = Bo.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0"], "use": True})
check(r.ok and r.json().get("used") is True and r.json().get("layout_id"), f"👍: applied ({r.status_code} {r.text[:200]})")
row = dbx("SELECT id, name, source, source_ref, layout FROM view_layouts WHERE user_id=? AND view_key='view_today'", (BOB,))
check(len(row) == 1 and row[0][2] == "agent" and row[0][3] == f"prop:{J2}" and "Focus" in row[0][1] and "Lybot" in row[0][1],
      f"a saved arrangement from the agent ({row})")
now = json.loads(setting(BOB, "view_today") or "{}")
check(now.get("order", [])[:2] == ["tasks", "events"] and now.get("opts", {}).get("tasks", {}).get("compact") is True,
      f"used at once, bob's block switches stay ({now})")
ev = [e for e in events(AG) if (e.get("job") or {}).get("id") == J2]
check(ev and ev[-1]["action"] == "approve" and ev[-1]["proposal"]["state"] == "applied" and ev[-1]["proposal"].get("view") == "view_today",
      f"the agent hears approve ({ev[-1:] if ev else ev})")
# undo / redo
r = Bo.post(B + f"/api/proposals/{J2}/undo")
check(r.ok and setting(BOB, "view_today") == before and not dbx("SELECT 1 FROM view_layouts WHERE user_id=? AND view_key='view_today'", (BOB,)),
      f"undo: the previous arrangement, the saved one goes ({r.text[:120]})")
r = Bo.post(B + f"/api/proposals/{J2}/redo")
check(r.ok and json.loads(setting(BOB, "view_today") or "{}").get("order", [])[:1] == ["tasks"]
      and len(dbx("SELECT 1 FROM view_layouts WHERE user_id=? AND view_key='view_today'", (BOB,))) == 1, f"redo ({r.text[:120]})")
check(Bo.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0"]}).status_code == 409, "a decided proposal: 409")

# use = false: stored, the view stays
cur = setting(BOB, "view_time")
r = prop({"order": ["entries", "tiles"]}, view="view_time")
J3 = r.json()["id"]
r = Bo.post(B + f"/api/proposals/{J3}/apply", json={"select": ["0"], "use": False})
check(r.ok and r.json().get("used") is False and setting(BOB, "view_time") == cur
      and dbx("SELECT 1 FROM view_layouts WHERE user_id=? AND view_key='view_time' AND source='agent'", (BOB,)),
      f"use=false: saved, the view unchanged ({r.text[:120]})")

# 👎 on the project page
r = prop({"order": ["ms", "kpis"], "widths": {"ms": 6}}, view=f"list:{P}")
J4 = r.json().get("id")
check(r.status_code == 201, f"a proposal for the shared project page ({r.status_code} {r.text[:150]})")
r = Bo.post(B + f"/api/proposals/{J4}/discard")
ev = [e for e in events(AG) if (e.get("job") or {}).get("id") == J4]
check(r.ok and ev and ev[-1]["action"] == "reject" and not dbx("SELECT 1 FROM view_layouts WHERE view_key=?", (f"list:{P}",))
      and not dbx("SELECT 1 FROM list_layouts WHERE list_id=?", (P,)), f"👎: discarded, nothing stored, the agent hears reject ({ev[-1:]})")
r = prop({"order": ["ms"]}, view=f"list:{PX}")
check(r.status_code == 404, f"a proposal for a project page not shared: 404 ({r.status_code})")

# the personal agent proposes to its owner
r = PAGS.post(V + "/layouts/proposals", json={"view": "dashboard", "name": "Morning", "layout": {"order": ["today", "news"], "widths": {"news": 6}}})
J5 = r.json().get("id")
check(r.status_code == 201 and dbx("SELECT user_id FROM agent_jobs WHERE id=?", (J5,))[0][0] == ERIN, f"personal agent -> its owner ({r.text[:150]})")
check(Er.post(B + f"/api/proposals/{J5}/apply", json={"select": ["0"]}).ok
      and json.loads(setting(ERIN, "dashboard") or "{}").get("opts", {}).get("news", {}).get("lw") == 6, "erin accepts: the news block full width")

# expired
r = prop({"order": ["jobs"]}, view="view_agents")
J6 = r.json()["id"]
dbx("UPDATE agent_jobs SET created_at='2026-01-01T08:00:00+00:00' WHERE id=?", (J6,), write=True)
check(Bo.post(B + f"/api/proposals/{J6}/apply", json={"select": ["0"]}).status_code == 409, "an expired proposal: 409")

# the agent still cannot arrange views directly
check(AGS.put(B + f"/api/lists/{P}/layout", json={"layout": ""}).status_code in (401, 403), "the agent's token: the layout route of people refused")
r = AGS.get(V + f"/agent/jobs/{J2}")
check(r.ok and r.json()["kind"] == "layout" and "Top secret" not in r.text, "the agent reads its job (no content)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
