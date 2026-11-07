#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.623.0 (#4718): an agent's change of a core object as a PROPOSAL a person accepts (kind obj_patch, agents/objprop.py),
with the test kind 'objprobe' (KALMIDO_TEST_OBJ=1, tests/obj_probe.py). Invented names only.
 - proposing: only with the version read (400 without, 409 old), unknown field / nothing changes 400, nothing is written,
   a view share is enough, a token that may only read is refused (403); an unshared object or another organisation's 404; user_id must be a
   person with write rights on the object (400)
 - accepting (the owner's card): written as the person (history: the person, not an agent), undo / redo; another person
   cannot open or accept the card (404); the agent gets the event job (approve / reject)
 - accepting after someone else changed the object: 409 with a plain message, nothing written, the card says stale
 - a person who lost the write right since (now read-only in the organisation) cannot accept (403), nothing written; discarding
 - review C: undo / redo after someone else's change 409 (the card keeps its state); discarding while accepting holds the
   proposal's row waits for it and answers 409
tenant-matrix: obj (another organisation's agent: 404 on a proposal)
freelancer-matrix: obj (a person without an organisation: her agent proposes, she accepts)
usage: p2623_c_objprop_test.py <datadir>"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
import dbx as _dbx  # noqa: E402
from kt import B, DATA, check, dbx, done, sess  # noqa: E402
from obj_probe import K, agent, new, start  # noqa: E402

start("P2623C")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u, rk in (("bob", "member"), ("carl", "member"), ("rita", "readonly")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rk}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]}).json().get("id")
Bo, Ca, Ri, Ol = sess("bob"), sess("carl"), sess("rita"), sess("olga")
for s in (Bo, Ca, Ri, Ol):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
FID, Fr = freelancer(B, A)
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})


def get(s, oid):
    return s.get(B + f"/api/obj/{K}/{oid}").json()


def propose(ag, oid, body):
    return requests.post(B + f"/api/v1/agent/objects/{K}/{oid}/proposals", headers=ag.h, json=body, timeout=30)


def events(ag):
    r = requests.get(B + "/api/v1/agent/events", params={"since": 0, "limit": 200}, headers=ag.h, timeout=30)
    return [e for e in r.json().get("data", []) if e["event"] == "job"] if r.ok else []


# ---------------------------------------------------------------- proposing
o = new(Bo, "Kick-off", ORG, note="first", size=2)
O = o["id"]
AG = agent(A, "propbot", ORG, scopes=("read", "comments"))  # no write scope of the kind: a proposal writes nothing
RO = agent(A, "readbot", ORG, scopes=("read",))
check(A.post(B + f"/api/obj/{K}/{O}/shares", json={"agent_id": AG.id, "role": "view"}).status_code == 201, "shared with the agent (view)")
cur = AG.get(O).json()
check(AG.patch(O, {"note": "direct", "expect_updated_at": cur["updated_at"]}).status_code == 403, "the agent cannot write directly (view share, no write scope)")
A.post(B + f"/api/obj/{K}/{O}/shares", json={"agent_id": RO.id, "role": "view"})
r = propose(RO, O, {"values": {"note": "x"}, "expect_updated_at": cur["updated_at"]})
check(r.status_code == 403, f"a token that may only read sends no proposals: 403 ({r.status_code} {r.text[:120]})")
r = propose(AG, O, {"values": {"note": "by proposal"}})
check(r.status_code == 400 and r.json()["error"].get("code") == "version_required", f"without the version: 400 version_required ({r.status_code} {r.text[:160]})")
r = propose(AG, O, {"values": {"nope": 1}, "expect_updated_at": cur["updated_at"]})
check(r.status_code == 400, f"an unknown field: 400 ({r.status_code})")
r = propose(AG, O, {"values": {"size": -1}, "expect_updated_at": cur["updated_at"]})
check(r.status_code == 400, f"a bad value: 400 ({r.status_code})")
r = propose(AG, O, {"values": {"note": "first"}, "expect_updated_at": cur["updated_at"]})
check(r.status_code == 400, f"nothing would change: 400 ({r.status_code})")
r = propose(AG, O, {"values": {"note": "x"}, "expect_updated_at": cur["updated_at"], "colour": "red"})
check(r.status_code == 400, f"an unknown key of the body: 400 ({r.status_code})")
r = propose(AG, O, {"values": {"note": "by proposal", "done": True}, "expect_updated_at": cur["updated_at"], "summary": "Clearer note"})
p = r.json() if r.status_code == 201 else {}
J1 = p.get("id")
check(r.status_code == 201 and p.get("kind") == "obj_patch" and p["proposal"]["after"] == {"note": "by proposal", "done": 1}
      and p["proposal"]["before"] == {"note": "first", "done": 0}, f"a proposal: 201 with before / after ({r.status_code} {r.text[:240]})")
now = get(Bo, O)
check(now["note"] == "first" and now["rev"] == 1, f"proposing writes nothing {now.get('note')} rev {now.get('rev')}")

# ---------------------------------------------------------------- who sees / accepts the card
v = Bo.get(B + f"/api/proposals/{J1}")
x = v.json() if v.ok else {}
check(v.ok and x.get("kind") == "obj_patch" and x.get("object", {}).get("id") == O and x["object"]["stale"] is False
      and x["object"]["can_write"] is True and {c["field"]: (c["now"], c["after"]) for c in x.get("changes", [])} == {"note": ("first", "by proposal"), "done": (0, 1)},
      f"the owner's card: the object, now -> after ({v.status_code} {v.text[:300]})")
check(Ca.get(B + f"/api/proposals/{J1}").status_code == 404 and Ca.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}).status_code == 404,
      "another person (with write rights) cannot open or accept the card: 404")
check(Ol.get(B + f"/api/proposals/{J1}").status_code == 404, "another organisation's person: 404")
r = Bo.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]})
check(r.ok and r.json().get("changed") == 2 and sorted(r.json().get("fields") or []) == ["done", "note"], f"accepted ({r.status_code} {r.text[:200]})")
now = get(Bo, O)
check(now["note"] == "by proposal" and now["done"] == 1 and now["rev"] == 2 and now["updated_by"] == uid["bob"], f"written as the person {now}")
h = Bo.get(B + f"/api/obj/{K}/{O}/history").json()["items"]
check(h[0]["user_id"] == uid["bob"] and h[0]["agent"] is False and h[0]["after"] == {"note": "by proposal", "done": 1}, f"the history names the person {h[0]}")
ev = [e for e in events(AG) if ((e.get("data") or {}).get("job") or {}).get("id") == J1]
check(any((e["data"].get("action") == "approve" and e["data"]["proposal"].get("fields") == ["done", "note"]) for e in ev), f"the agent hears approve {ev[-1:]}")
check(Bo.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}).status_code == 409, "accepting twice: 409")
r = Bo.post(B + f"/api/proposals/{J1}/undo")
check(r.ok and r.json().get("undone") == 1 and get(Bo, O)["note"] == "first" and get(Bo, O)["done"] == 0, f"undo: the values before ({r.status_code} {r.text[:160]})")
r = Bo.post(B + f"/api/proposals/{J1}/redo")
check(r.ok and r.json().get("redone") == 1 and get(Bo, O)["note"] == "by proposal", f"redo: the proposal's values again ({r.status_code} {r.text[:160]})")
Ca.patch(B + f"/api/obj/{K}/{O}", json={"note": "carl's"})
r = Bo.post(B + f"/api/proposals/{J1}/undo")
# 2.623.0 (#4718, review C): a step that cannot be done is a 409 and the card keeps its state (was: 200 "undone", nothing written)
check(r.status_code == 409 and get(Bo, O)["note"] == "carl's" and Bo.get(B + f"/api/proposals/{J1}").json()["applied"]["undone"] is False,
      f"undo after someone else's change: 409, nothing written, the card stays applied ({r.status_code} {r.text[:160]})")

# ---------------------------------------------------------------- review C: redo after someone else's change (409, stays undone)
cur = AG.get(O).json()
r = propose(AG, O, {"values": {"note": "redo me"}, "expect_updated_at": cur["updated_at"]})
J4 = r.json().get("id") if r.status_code == 201 else None
check(Bo.post(B + f"/api/proposals/{J4}/apply", json={"select": ["0"]}).ok and Bo.post(B + f"/api/proposals/{J4}/undo").ok
      and get(Bo, O)["note"] == "carl's", "applied and undone")
Ca.patch(B + f"/api/obj/{K}/{O}", json={"note": "carl again"})
r = Bo.post(B + f"/api/proposals/{J4}/redo")
x = Bo.get(B + f"/api/proposals/{J4}").json()
check(r.status_code == 409 and get(Bo, O)["note"] == "carl again" and x["applied"]["undone"] is True,
      f"redo after someone else's change: 409, nothing written, the card stays undone ({r.status_code} {r.text[:160]} {x.get('applied')})")

# ---------------------------------------------------------------- review C: discarding while accepting holds the row (409)
cur = AG.get(O).json()
r = propose(AG, O, {"values": {"note": "race"}, "expect_updated_at": cur["updated_at"]})
J5 = r.json().get("id") if r.status_code == 201 else None
dbc, dbn = _dbx._target(DATA)
hold = subprocess.Popen(["docker", "exec", "-i", dbc, "psql", "-U", "kalmido", "-d", dbn, "-X", "-q", "-v", "ON_ERROR_STOP=1"], stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
hold.stdin.write(f"BEGIN; SELECT id FROM agent_jobs WHERE id={int(J5)} FOR UPDATE; UPDATE agent_jobs SET prop_state='applied', state='done' "
                 f"WHERE id={int(J5)}; SELECT pg_sleep(2.5); COMMIT;\n")
hold.stdin.close()
held = False
for _ in range(100):  # until the other transaction holds the row (it sleeps inside it)
    held = dbx("SELECT count(*) FROM pg_stat_activity WHERE query LIKE ? AND state='active' AND pid<>pg_backend_pid()", ("%pg_sleep(2.5)%",))[0][0] > 0
    if held:
        break
    time.sleep(0.05)
r = Bo.post(B + f"/api/proposals/{J5}/discard")
hold.wait(timeout=30)
check(held and r.status_code == 409 and dbx("SELECT prop_state FROM agent_jobs WHERE id=?", (J5,))[0][0] == "applied",
      f"discarding while the proposal is being accepted: 409, it stays applied (held {held}, {r.status_code} {r.text[:120]})")

# ---------------------------------------------------------------- accepting after someone else changed it: 409
cur = AG.get(O).json()
r = propose(AG, O, {"values": {"size": 7}, "expect_updated_at": cur["updated_at"]})
J2 = r.json().get("id") if r.status_code == 201 else None
check(r.status_code == 201, f"a second proposal ({r.status_code} {r.text[:160]})")
r = propose(AG, O, {"values": {"size": 8}, "expect_updated_at": o["updated_at"]})
check(r.status_code == 409 and r.json()["error"].get("current", {}).get("note") == "carl again", f"proposing on an old version: 409 with the current state ({r.status_code})")
Ca.patch(B + f"/api/obj/{K}/{O}", json={"title": "Kick-off (carl)"})
x = Bo.get(B + f"/api/proposals/{J2}").json()
check(x.get("object", {}).get("stale") is True, "the card says: changed since")
r = Bo.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0"]})
msg = (r.json().get("error") if r.headers.get("content-type", "").startswith("application/json") else "") or ""
msg = msg.get("message", "") if isinstance(msg, dict) else msg
check(r.status_code == 409 and "since the proposal" in msg, f"accepting after someone else's change: 409 with a plain message ({r.status_code} {r.text[:200]})")
check(get(Bo, O)["size"] == 2 and Bo.get(B + f"/api/proposals/{J2}").json()["state"] == "ready", "nothing written, the card stays")
check(Bo.post(B + f"/api/proposals/{J2}/discard").ok and Bo.get(B + f"/api/proposals/{J2}").json()["state"] == "discarded", "discarded")
check(any(((e.get("data") or {}).get("job") or {}).get("id") == J2 and e["data"].get("action") == "reject" for e in events(AG)), "the agent hears reject")
check(Bo.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0"]}).status_code == 409, "a discarded proposal cannot be accepted")
cur = AG.get(O).json()
check(requests.post(B + f"/api/v1/agent/jobs/{J2}/proposal", headers=AG.h, json={"values": {"size": 3}}, timeout=30).status_code == 409,
      "no replacing through the jobs route: 409")

# ---------------------------------------------------------------- the person who decides (user_id)
r = propose(AG, O, {"values": {"size": 3}, "expect_updated_at": cur["updated_at"], "user_id": uid["rita"]})
check(r.status_code == 400, f"user_id of a read-only member (view only): 400 ({r.status_code})")
r = propose(AG, O, {"values": {"size": 3}, "expect_updated_at": cur["updated_at"], "user_id": uid["olga"]})
check(r.status_code == 400, f"user_id of another organisation's person: 400 ({r.status_code})")
r = propose(AG, O, {"values": {"size": 3}, "expect_updated_at": cur["updated_at"], "user_id": AG.id})
check(r.status_code == 400, f"user_id of an agent: 400 ({r.status_code})")
r = propose(AG, O, {"values": {"size": 3}, "expect_updated_at": cur["updated_at"], "user_id": uid["carl"]})
J3 = r.json().get("id") if r.status_code == 201 else None
check(r.status_code == 201, f"a card for carl, a member who may change it ({r.status_code} {r.text[:160]})")
check(Bo.get(B + f"/api/proposals/{J3}").status_code == 404, "the owner does not see a card addressed to carl")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["carl"], "role": "readonly"}).ok, "carl becomes read-only")
r = Ca.post(B + f"/api/proposals/{J3}/apply", json={"select": ["0"]})
check(r.status_code == 403 and get(Bo, O)["size"] == 2, f"carl lost the write right: he cannot accept, nothing written ({r.status_code} {r.text[:160]})")
x = Ca.get(B + f"/api/proposals/{J3}")
check(x.ok and x.json().get("state") == "ready" and x.json().get("object", {}).get("can_write") is False,
      f"the card stays ready and says: view only ({x.status_code} {x.text[:200]})")

# ---------------------------------------------------------------- only what the agent sees (tenant-matrix: obj)
o3 = new(Bo, "Not shared", ORG)
r = propose(AG, o3["id"], {"values": {"note": "x"}, "expect_updated_at": o3["updated_at"]})
check(r.status_code == 404, f"an object not shared with the agent: 404 ({r.status_code})")
oh = new(Bo, "hide this plan", ORG)
A.post(B + f"/api/obj/{K}/{oh['id']}/shares", json={"agent_id": AG.id, "role": "edit"})
check(propose(AG, oh["id"], {"values": {"note": "x"}, "expect_updated_at": oh["updated_at"]}).status_code == 404, "what the area hides from agents: 404")
OAG = agent(Ol, "otherbot", ORG2)
check(propose(OAG, O, {"values": {"note": "x"}, "expect_updated_at": get(Bo, O)["updated_at"]}).status_code == 404, "another organisation's agent: 404")
cur = get(Bo, O)
check(requests.post(B + f"/api/v1/agent/objects/{K}/{O}/proposals", headers={**AG.h, "Authorization": "Bearer nope"},
                    json={"values": {"note": "x"}, "expect_updated_at": cur["updated_at"]}, timeout=30).status_code == 401, "no token: 401")
check(Bo.post(B + f"/api/v1/agent/objects/{K}/{O}/proposals", json={"values": {"note": "x"}, "expect_updated_at": cur["updated_at"]}).status_code in (401, 403),
      "a person's session: not on the agent route")
check(Bo.post(B + "/api/proposals", json={"agent_id": AG.id, "kind": "obj_patch"}).status_code == 400, "a person cannot ask for kind obj_patch")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: obj)
f = new(Fr, "Frida's plan", note="a")
FA = agent(Fr, "fridabot", scopes=("read", "comments"))
check(Fr.post(B + f"/api/obj/{K}/{f['id']}/shares", json={"agent_id": FA.id, "role": "view"}).status_code == 201, "shared with her own agent")
r = propose(FA, f["id"], {"values": {"note": "b"}, "expect_updated_at": FA.get(f["id"]).json()["updated_at"]})
FJ = r.json().get("id") if r.status_code == 201 else None
check(r.status_code == 201, f"her agent proposes ({r.status_code} {r.text[:160]})")
r = Fr.post(B + f"/api/proposals/{FJ}/apply", json={"select": ["0"]})
check(r.ok and get(Fr, f["id"])["note"] == "b", f"she accepts, the value is written ({r.status_code} {r.text[:160]})")
check(propose(AG, f["id"], {"values": {"note": "c"}, "expect_updated_at": get(Fr, f["id"])["updated_at"]}).status_code == 404,
      "an organisation's agent never reaches her object: 404")

sys.exit(done("p2623_c_objprop"))
