#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1005.0 (#5637): the toast's "Undo" takes back exactly its own step group -- POST /api/undo/<id>/undo
(kalmido/core/undoweb.py undo_group_one) with the test kind 'objprobe' (KALMIDO_TEST_OBJ=1, tests/obj_probe.py). Invented names.
 - two groups of one person (two devices, two objects): the older one back, the newer one stays (the old way, POST
   /api/undo/to/<id>, took both: the regression); redo of it works as before
 - a part a newer step changed since stays and is named (code conflict), nothing written
 - a newer barrier of the same workspace holds it; a barrier of another workspace (private) does not
 - an undone group: 409; another person's group: 404; an agent: 403
 - "up to here" (POST /api/undo/to/<id>) stays as it was: everything newer goes with it
freelancer-matrix: undo (a person without an organisation: her older client step back, her newer service change stays)
usage: p21005_a_undo_one_test.py <datadir>"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, done, sess  # noqa: E402
from obj_probe import K, agent, in_app, new, start  # noqa: E402

start("P21005A")
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
Bo, Ca = sess("bob"), sess("carl")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
BOB = uid["bob"]
FID, Fr = freelancer(B, A)
PHONE, LAPTOP = {"X-Kalmido-Device": "Phone (Test)"}, {"X-Kalmido-Device": "Laptop (Test)"}


def groups(u):  # without the settings' steps of the setup (area self)
    return dbx("SELECT id, state, org_id FROM undo_groups WHERE user_id=? AND area<>'self' ORDER BY id", (u,))


def get(s, oid):
    return s.get(B + f"/api/obj/{K}/{oid}").json()


def patch(s, oid, headers=None, **kw):
    r = s.patch(B + f"/api/obj/{K}/{oid}", json=kw, headers=headers or {})
    assert r.ok, (oid, kw, r.status_code, r.text[:300])
    return r.json()


def state(u):
    return {g["id"]: g["state"] for g in groups(u)}


def one(s, gid):
    r = s.post(B + f"/api/undo/{gid}/undo")
    return r, (r.json() if r.ok else {})


# ---------------------------------------------------------------- two groups: the older one back, the newer stays
O1, O2 = new(Bo, "Single A", ORG, note="a1")["id"], new(Bo, "Single B", ORG, note="b1")["id"]
patch(Bo, O1, headers=PHONE, note="a2")
GX = groups(BOB)[-1]["id"]
patch(Bo, O2, headers=LAPTOP, note="b2")  # a newer step of the same person on another device
GY = groups(BOB)[-1]["id"]
check(GY > GX, f"two groups {GX} {GY}")
r, x = one(Bo, GX)
check(r.ok and x["undone"] == [GX] and x["stayed"] == [] and x["stopped"] is None and get(Bo, O1)["note"] == "a1",
      f"the toast's group goes back ({r.status_code} {r.text[:300]})")
check(get(Bo, O2)["note"] == "b2", f"#5637: the newer step on the other object stays (it went back with it before) {get(Bo, O2)['note']}")
st = state(BOB)
check(st[GX] == "undone" and st[GY] == "done", f"states after the single undo {st}")
check(x["text"] and "1" in x["text"], f"the answer says one step {x.get('text')}")
r, _ = one(Bo, GX)
check(r.status_code == 409, f"an undone group: 409, nothing left to take back ({r.status_code})")
r = Bo.post(B + f"/api/undo/{GX}/redo")
check(r.ok and get(Bo, O1)["note"] == "a2" and get(Bo, O2)["note"] == "b2", f"redo of the single undo ({r.status_code} {r.text[:200]})")

# ---------------------------------------------------------------- rights: another person 404, an agent 403
r, _ = one(Ca, GY)
check(r.status_code == 404 and get(Bo, O2)["note"] == "b2", f"another person's group: 404, nothing written ({r.status_code})")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
AG = agent(A, "undobot", ORG)
r = requests.post(B + f"/api/undo/{GY}/undo", headers=AG.h, timeout=30)
check(r.status_code in (401, 403) and get(Bo, O2)["note"] == "b2", f"an agent's token on the single undo: refused ({r.status_code})")
out = in_app(f"""
from kalmido.core.undoweb import undo_group_one
try:
    undo_group_one(c, {AG.id}, {GY})
    print('NO-REFUSAL')
except Denied as e:
    print('CODE', e.code)""")
check("CODE 403" in out, f"an agent: 403 (obj_is_agent) {out[-300:]}")

# ---------------------------------------------------------------- changed since by a newer step: stays and is named
patch(Bo, O2, note="b3")
r, x = one(Bo, GY)
check(r.ok and x["undone"] == [] and [(s["id"], s["code"]) for s in x["stayed"]] == [(O2, "conflict")] and get(Bo, O2)["note"] == "b3",
      f"the object changed since: it stays and is named ({r.status_code} {x})")

# ---------------------------------------------------------------- a newer barrier of the same workspace holds it, another workspace's not
patch(Bo, O1, note="a4")
GZ = groups(BOB)[-1]["id"]
dbx("INSERT INTO undo_groups(user_id, org_id, area, label_key, state, created_at, updated_at) VALUES(?, NULL, 'other', 'Change', 'barrier', "
    "date_trunc('second', now()), date_trunc('second', now()))", (BOB,))
r, x = one(Bo, GZ)
check(r.ok and x["undone"] == [GZ] and x["stopped"] is None and get(Bo, O1)["note"] == "a2",
      f"a barrier of another workspace (private) does not hold it ({r.status_code} {x})")
patch(Bo, O1, note="a5")
GW = groups(BOB)[-1]["id"]
dbx("INSERT INTO undo_groups(user_id, org_id, area, label_key, state, created_at, updated_at) VALUES(?, ?, 'office', 'Change', 'barrier', "
    "date_trunc('second', now()), date_trunc('second', now()))", (BOB, ORG))
GB = groups(BOB)[-1]["id"]
r, x = one(Bo, GW)
check(r.ok and x["stopped"] and x["stopped"]["id"] == GB and x["stopped"]["state"] == "barrier" and x["undone"] == []
      and get(Bo, O1)["note"] == "a5" and state(BOB)[GW] == "done", f"a newer barrier of the same workspace holds it ({r.status_code} {x})")
r, x = one(Bo, GB)
check(r.ok and x["stopped"] and x["stopped"]["id"] == GB and x["undone"] == [], f"the barrier itself: stopped, nothing goes {x}")

# ---------------------------------------------------------------- "up to here" stays as it was
O3 = new(Bo, "Single C", ORG, note="c1")["id"]
patch(Bo, O3, note="c2")
G1 = groups(BOB)[-1]["id"]
patch(Bo, O2, note="b4")
G2 = groups(BOB)[-1]["id"]
r = Bo.post(B + f"/api/undo/to/{G1}")
x = r.json() if r.ok else {}
check(r.ok and x["undone"] == [G2, G1] and get(Bo, O3)["note"] == "c1" and get(Bo, O2)["note"] == "b3",
      f"up to here: the newer step goes with it as before ({r.status_code} {x})")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: undo)
r = Fr.post(B + "/api/office/services", json={"name_de": "Beratung", "daily_rate": 800})
check(r.status_code in (200, 201), f"frida's service ({r.status_code} {r.text[:200]})")
SV = r.json()["id"]
r = Fr.post(B + "/api/clients", json={"name": "Single Client", "org_id": None})
FC = r.json()["id"]
check(Fr.patch(B + f"/api/clients/{FC}", json={"name": "Single Client 2"}).ok, "she renames her client")
FX = groups(FID)[-1]["id"]
check(Fr.patch(B + f"/api/office/services/{SV}", json={"name_de": "Beratung single"}).ok, "she changes her service after the client")
FY = groups(FID)[-1]["id"]
check(FY > FX, f"two groups of hers {FX} {FY}")
r, x = one(Fr, FX)
check(r.ok and x["undone"] == [FX] and Fr.get(B + f"/api/clients/{FC}").json()["name"] == "Single Client"
      and Fr.get(B + f"/api/office/services/{SV}").json()["name_de"] == "Beratung single",
      f"without an organisation: her client back, her newer service change stays ({r.status_code} {r.text[:300]})")
check(state(FID)[FY] == "done", f"her newer group is untouched {state(FID)}")
r, _ = one(Fr, GY)
check(r.status_code == 404, f"bob's group: 404 for her ({r.status_code})")

sys.exit(done("p21005_a_undo_one"))
