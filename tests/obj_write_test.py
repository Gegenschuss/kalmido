#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.558.0 (#4709): the shared core, stage 1 -- THE write path (kalmido/core/writes.py) through the generic routes with the
test kind 'objprobe' (KALMIDO_TEST_OBJ=1, tests/obj_probe.py). Invented names only.
 - only the fields sent change (partial), an unknown field / a bad value 400, nothing changed = no new version
 - expect_updated_at: the current one passes, an old one 409 with the current state under "current" (nothing written);
   a person without it writes as before; an AGENT without it 400, with it 200, an old one 409
 - every change: rev+1, updated_at, updated_by, the area counter of /api/version; the history (create / update / trash /
   restore / undo, an agent marked, one person's changes within ten minutes merged, changed back = no entry left)
 - undo of the editor session (X-Kalmido-Undo): undo, redo, all; someone else's change in between = 409, nothing written
 - the trash: delete for good only from the trash (409 before), then the object and its history are gone
tenant-matrix: obj (another organisation's person / agent: 404 on change, undo, history)
freelancer-matrix: obj (a person without an organisation: change with the version, undo, history, her agent writes with the version)
usage: obj_write_test.py <datadir>"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, done, sess  # noqa: E402
from obj_probe import K, agent, new, start  # noqa: E402

start("OBJWRITE")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]}).json().get("id")
Bo, Ca, Ol = sess("bob"), sess("carl"), sess("olga")
FID, Fr = freelancer(B, A)


def get(s, oid):
    return s.get(B + f"/api/obj/{K}/{oid}").json()


def hist(s, oid):
    r = s.get(B + f"/api/obj/{K}/{oid}/history")
    return r.json()["items"] if r.ok else r.status_code


def ver(s):
    return s.get(B + "/api/version").json()


# ---------------------------------------------------------------- partial writes, validation, versions
o = new(Bo, "Kick-off", ORG, note="first", size=2)
O = o["id"]
check(o["rev"] == 1 and o["title"] == "Kick-off" and o["note"] == "first" and o["size"] == 2 and o["done"] == 0, f"created {o}")
check(Bo.post(B + f"/api/obj/{K}", json={"note": "no title"}).status_code == 400, "a required field missing: 400")
v0 = ver(Ca)
r = Ca.patch(B + f"/api/obj/{K}/{O}", json={"note": "second", "expect_updated_at": o["updated_at"]})
x = r.json() if r.ok else {}
check(r.ok and x["note"] == "second" and x["title"] == "Kick-off" and x["size"] == 2 and x["rev"] == 2 and x["updated_by"] == uid["carl"]
      and x["changed"] == ["note"], f"only the field sent changes, rev+1, updated_by ({r.status_code} {r.text[:200]})")
v1 = ver(Ca)
check(int(v1["v"]) > int(v0["v"]), f"the change counter moved (bump) {v0.get('v')} -> {v1.get('v')}")
check(Ca.patch(B + f"/api/obj/{K}/{O}", json={"colour": "red"}).status_code == 400, "an unknown field: 400")
check(Ca.patch(B + f"/api/obj/{K}/{O}", json={"size": -1}).status_code == 400 and get(Ca, O)["size"] == 2, "a bad value: 400, nothing written")
r = Ca.patch(B + f"/api/obj/{K}/{O}", json={"note": "second"})
check(r.ok and r.json()["rev"] == 2 and r.json()["changed"] == [], "nothing changed: no new version")
r = Bo.patch(B + f"/api/obj/{K}/{O}", json={"title": "Stale", "expect_updated_at": o["updated_at"]})
check(r.status_code == 409 and r.json().get("current", {}).get("note") == "second" and get(Bo, O)["title"] == "Kick-off",
      f"an old version: 409 with the current state, nothing written ({r.status_code} {r.text[:200]})")
r = Bo.patch(B + f"/api/obj/{K}/{O}", json={"title": "Kick-off 2"})
check(r.ok and r.json()["title"] == "Kick-off 2", "a person without a version writes as before")

# ---------------------------------------------------------------- the history
h = hist(Ca, O)
acts = [(e["action"], e["user_id"]) for e in h]
check(acts == [("update", uid["bob"]), ("update", uid["carl"]), ("create", uid["bob"])], f"history newest first {acts}")
check(h[1]["before"] == {"note": "first"} and h[1]["after"] == {"note": "second"}, f"before / after of the changed field {h[1]}")
Ca.patch(B + f"/api/obj/{K}/{O}", json={"size": 5})
Ca.patch(B + f"/api/obj/{K}/{O}", json={"size": 6, "done": True})
h = hist(Ca, O)
check(len(h) == 4 and h[0]["before"] == {"size": 2, "done": 0} and h[0]["after"] == {"size": 6, "done": 1},
      f"one person's changes within ten minutes: one entry, the first before, the last after {h[0]}")
Ca.patch(B + f"/api/obj/{K}/{O}", json={"size": 2, "done": False})
h = hist(Ca, O)
check(len(h) == 4 and h[0]["after"] == {} and h[0]["before"] == {}, f"changed back within the window: nothing left in the entry {h[0]}")

# ---------------------------------------------------------------- agents must send the version
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
AG = agent(A, "writebot", ORG)
A.post(B + f"/api/obj/{K}/{O}/shares", json={"agent_id": AG.id, "role": "edit"})
cur = AG.get(O).json()
r = AG.patch(O, {"note": "by the agent"})
check(r.status_code == 400 and get(A, O)["note"] == "second", f"an agent without expect_updated_at: 400 ({r.status_code} {r.text[:160]})")
r = AG.patch(O, {"note": "by the agent", "expect_updated_at": cur["updated_at"]})
check(r.ok and r.json()["note"] == "by the agent", f"with the version: 200 ({r.status_code} {r.text[:160]})")
r = AG.patch(O, {"note": "again", "expect_updated_at": cur["updated_at"]})
check(r.status_code == 409 and r.json()["error"].get("current", {}).get("note") == "by the agent" and get(A, O)["note"] == "by the agent",
      f"an agent with an old version: 409 with the current state ({r.status_code} {r.text[:160]})")
check(AG.patch(O, {"nope": 1, "expect_updated_at": get(A, O)["updated_at"]}).status_code == 400, "an agent: unknown field 400")
h = hist(A, O)
check(h[0]["agent"] is True and h[0]["user_id"] == AG.id and h[0]["after"] == {"note": "by the agent"}, f"the agent's change is marked {h[0]}")
RO = agent(A, "readbot", ORG, scopes=("read",))
A.post(B + f"/api/obj/{K}/{O}/shares", json={"agent_id": RO.id, "role": "edit"})
check(RO.get(O).ok and RO.patch(O, {"note": "x", "expect_updated_at": get(A, O)["updated_at"]}).status_code == 403, "a read-only token: reads, no change (403)")

# ---------------------------------------------------------------- undo of the editor session
SESS = "0123456789abcdef"
U = {"X-Kalmido-Undo": SESS}
o2 = new(Ca, "Draft", ORG)
O2 = o2["id"]
Ca.patch(B + f"/api/obj/{K}/{O2}", json={"title": "Draft A"}, headers=U)
Ca.patch(B + f"/api/obj/{K}/{O2}", json={"title": "Draft B", "size": 9}, headers=U)
r = Ca.post(B + f"/api/obj/{K}/{O2}/undo", json={"sess": SESS, "op": "undo"})
check(r.ok and r.json()["title"] == "Draft A" and r.json()["size"] is None and r.json()["rev"] == 4, f"undo: the step before (a new version) ({r.status_code} {r.text[:200]})")
r = Ca.post(B + f"/api/obj/{K}/{O2}/undo", json={"sess": SESS, "op": "redo"})
check(r.ok and r.json()["title"] == "Draft B" and r.json()["size"] == 9, "redo")
check(Bo.post(B + f"/api/obj/{K}/{O2}/undo", json={"sess": SESS, "op": "undo"}).status_code == 409, "another person's undo: nothing of theirs (409)")
r = Ca.post(B + f"/api/obj/{K}/{O2}/undo", json={"sess": SESS, "op": "all"})
check(r.ok and r.json()["title"] == "Draft" and r.json()["undo_steps"] == {"undone": 2}, f"undo all: back to the opening {r.text[:200]}")
Ca.post(B + f"/api/obj/{K}/{O2}/undo", json={"sess": SESS, "op": "redoall"})
Ca.patch(B + f"/api/obj/{K}/{O2}", json={"note": "mine"}, headers=U)
Bo.patch(B + f"/api/obj/{K}/{O2}", json={"note": "bob's"})
r = Ca.post(B + f"/api/obj/{K}/{O2}/undo", json={"sess": SESS, "op": "undo"})
check(r.status_code == 409 and get(Ca, O2)["note"] == "bob's", f"someone else changed it since: 409, nothing written ({r.status_code})")
check(Ca.post(B + f"/api/obj/{K}/{O2}/undo", json={"sess": "nothex", "op": "undo"}).status_code == 400, "a bad session: 400")
check([e["action"] for e in hist(Ca, O2)][:3] == ["update", "update", "redo"], f"undo / redo are in the history {[e['action'] for e in hist(Ca, O2)]}")

# ---------------------------------------------------------------- trash, delete for good
check(Ca.delete(B + f"/api/obj/{K}/{O2}").status_code == 409, "delete for good outside the trash: 409")
check(Ca.post(B + f"/api/obj/{K}/{O2}/trash").ok and Ca.patch(B + f"/api/obj/{K}/{O2}", json={"note": "x"}).status_code == 404, "in the trash: no change (404)")
check(Ca.post(B + f"/api/obj/{K}/{O2}/restore").ok and [e["action"] for e in hist(Ca, O2)][:2] == ["restore", "trash"], "trash and restore in the history")
Ca.post(B + f"/api/obj/{K}/{O2}/trash")
check(Ca.delete(B + f"/api/obj/{K}/{O2}").ok and Ca.get(B + f"/api/obj/{K}/{O2}").status_code == 404, "deleted for good")
check(dbx("SELECT COUNT(*) FROM obj_history WHERE kind=? AND ref_id=?", (K, O2))[0][0] == 0
      and dbx("SELECT COUNT(*) FROM obj_undo WHERE kind=? AND ref_id=?", (K, O2))[0][0] == 0, "its history and undo steps went along")

# ---------------------------------------------------------------- another organisation (tenant-matrix: obj)
OAG = agent(Ol, "otherbot", ORG2)
check(Ol.patch(B + f"/api/obj/{K}/{O}", json={"note": "x"}).status_code == 404 and Ol.get(B + f"/api/obj/{K}/{O}/history").status_code == 404
      and Ol.post(B + f"/api/obj/{K}/{O}/undo", json={"sess": SESS, "op": "undo"}).status_code == 404, "olga: 404 on change, history, undo")
check(OAG.patch(O, {"note": "x", "expect_updated_at": get(A, O)["updated_at"]}).status_code == 404, "olga's agent: 404")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: obj)
f = new(Fr, "Frida's list", note="a")
F = f["id"]
r = Fr.patch(B + f"/api/obj/{K}/{F}", json={"note": "b", "expect_updated_at": f["updated_at"]}, headers=U)
check(r.ok and r.json()["note"] == "b", "she changes it with the version")
check(Fr.post(B + f"/api/obj/{K}/{F}/undo", json={"sess": SESS, "op": "undo"}).ok and get(Fr, F)["note"] == "a", "her undo")
FA = agent(Fr, "fridabot")
check(Fr.post(B + f"/api/obj/{K}/{F}/shares", json={"agent_id": FA.id, "role": "edit"}).status_code == 201, "shared with her own agent")
r = requests.patch(B + f"/api/v1/agent/objects/{K}/{F}", headers=FA.h, json={"note": "c", "expect_updated_at": get(Fr, F)["updated_at"]})
check(r.ok and get(Fr, F)["note"] == "c" and hist(Fr, F)[0]["agent"] is True, f"her agent writes with the version ({r.status_code})")
check(FA.patch(F, {"note": "d"}).status_code == 400, "her agent without the version: 400")

sys.exit(done("obj_write"))
