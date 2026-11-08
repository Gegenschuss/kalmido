#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.747.0 (#5249): undo across devices, stage 1 -- the core's undo steps grouped per account (kalmido/core/undogroups.py,
kalmido/core/undoweb.py) with the test kind 'objprobe' (KALMIDO_TEST_OBJ=1, tests/obj_probe.py). Invented names only.
 - a write of a person (obj_write, office/owrite.py ow_write) opens a group: area, device (X-Kalmido-Device), label in the
   reader's language, parts, bytes; the person's own "self" counter moves; several writes of ONE request = one group, the
   header X-Kalmido-Undo-Group bundles two requests
 - GET /api/undo lists only the own groups (another person: nothing, 404 on undo / redo of a foreign group); an agent: 403
   (and its writes record no step)
 - POST /api/undo/to/<id>: newest first; a part someone else changed since stays (named in the answer), the rest of the group
   goes back anyway (partial); a barrier and a group too big for copies stop the run; redo of one group; a new step ends the
   way forward
 - limits: a part over 256 KB or a group at 1000 parts = toobig (listed, no copies); the 301st group removes the oldest
 - the watchdog: a group older than 30 days goes with its parts, a part without its group goes
 - copies are the stored row: a sealed value (kenc1:...) stays sealed in the copy and comes back sealed
 - GET /api/admin/retention counts the undo steps (groups, bytes, oldest)
tenant-matrix: undo (another person's group: not listed, 404 on undo / redo; an agent 403)
freelancer-matrix: undo (a person without an organisation: her office step listed, taken back, redone)
usage: p2747_b_undo_core_test.py <datadir>"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, done, sess, until  # noqa: E402
from obj_probe import K, agent, in_app, new, start  # noqa: E402

start("P2747B")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]})
Bo, Ca, Ol = sess("bob"), sess("carl"), sess("olga")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "de"})  # bob reads the labels in German
BOB, CARL = uid["bob"], uid["carl"]
FID, Fr = freelancer(B, A)
TOK = "ab12" * 8
DEV = {"X-Kalmido-Device": "Laptop (Test)"}


def groups(u):
    return dbx("SELECT id, state, parts, bytes, device, area, label_key, label_args, token FROM undo_groups WHERE user_id=? ORDER BY id", (u,))


def parts(gid):
    return dbx("SELECT id, kind, ref_id, state, bytes, sess FROM obj_undo WHERE group_id=? ORDER BY id", (gid,))


def get(s, oid):
    return s.get(B + f"/api/obj/{K}/{oid}").json()


def patch(s, oid, headers=None, **kw):
    r = s.patch(B + f"/api/obj/{K}/{oid}", json=kw, headers=headers or {})
    assert r.ok, (oid, kw, r.status_code, r.text[:300])
    return r.json()


def items(s):
    r = s.get(B + "/api/undo")
    return r.json()["items"] if r.ok else r.status_code


def self_ver(u):
    r = dbx("SELECT value FROM settings WHERE key=?", (f"version:self:{u}",))
    return int(r[0][0]) if r else 0


# ---------------------------------------------------------------- a write opens a group
O1 = new(Bo, "Plan", ORG, note="n1", size=1)["id"]
O2 = new(Bo, "Budget", ORG, note="m1")["id"]
check(groups(BOB) == [], "creating records no step")
v0 = self_ver(BOB)
patch(Bo, O1, headers=DEV, note="n2")
g1 = groups(BOB)
check(len(g1) == 1 and g1[0]["state"] == "done" and g1[0]["parts"] == 1 and g1[0]["bytes"] > 0 and g1[0]["device"] == "Laptop (Test)"
      and g1[0]["area"] == "other" and g1[0]["label_key"] == "Changed: {0}", f"obj_write: one group with area, device, label, parts, bytes {g1}")
G1 = g1[0]["id"]
p1 = parts(G1)
check(len(p1) == 1 and p1[0]["kind"] == K and p1[0]["ref_id"] == O1 and p1[0]["sess"] == "" and p1[0]["bytes"] == g1[0]["bytes"],
      f"its part: the object's copy, no editor session {p1}")
check(self_ver(BOB) > v0, f"a new group moves the person's own counter (other devices reload the list) {v0} -> {self_ver(BOB)}")
it = items(Bo)
check(isinstance(it, list) and len(it) == 1 and it[0]["id"] == G1 and it[0]["label"] == "Geändert: Test object" and it[0]["device"] == "Laptop (Test)"
      and it[0]["kind"] == K and it[0]["ref_id"] == O1 and it[0]["undo"] is True and it[0]["redo"] is False and "snap" not in it[0],
      f"GET /api/undo: the head in the reader's language, no copy {it}")

# ---- the header bundles two requests; one request with two writes = one group
patch(Bo, O1, headers={"X-Kalmido-Undo-Group": TOK}, size=2)
patch(Bo, O2, headers={"X-Kalmido-Undo-Group": TOK}, note="m2")
g2 = groups(BOB)
check(len(g2) == 2 and g2[1]["parts"] == 2 and g2[1]["token"] == TOK and [p["ref_id"] for p in parts(g2[1]["id"])] == [O1, O2],
      f"X-Kalmido-Undo-Group: two requests, one group with two parts {g2}")
G2 = g2[1]["id"]
O3 = new(Bo, "Notes", ORG, note="x1")["id"]
O4 = new(Bo, "Ideas", ORG, note="y1")["id"]
out = in_app(f"""
from flask import g
from kalmido.core.config import app as fa
from kalmido.core.writes import obj_write
with fa.test_request_context('/api/obj/{K}/{O3}', method='PATCH'):
    g.user = {{"id": {BOB}}}
    obj_write(c, {BOB}, '{K}', {O3}, {{'note': 'x2'}})
    obj_write(c, {BOB}, '{K}', {O4}, {{'note': 'y2'}})
    c.commit()
print('WROTE')""")
g3 = groups(BOB)
check("WROTE" in out and len(g3) == 3 and g3[2]["parts"] == 2 and sorted(p["ref_id"] for p in parts(g3[2]["id"])) == sorted([O3, O4]),
      f"two writes in one request: one group, two parts {g3} {out[-400:]}")
G3 = g3[2]["id"]

# ---------------------------------------------------------------- only the own steps (tenant-matrix: undo)
check(items(Ol) == [] and items(A) == [], "olga and alice list nothing of bob's")
check(Ol.post(B + f"/api/undo/to/{G1}").status_code == 404 and A.post(B + f"/api/undo/to/{G1}").status_code == 404
      and Ol.post(B + f"/api/undo/{G1}/redo").status_code == 404 and get(Bo, O1)["note"] == "n2", "another person's group: 404 on undo / redo, nothing written")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
AG = agent(A, "undobot", ORG)
r = requests.get(B + "/api/undo", headers=AG.h, timeout=30)
check(r.status_code in (401, 403), f"an agent's token on /api/undo: refused ({r.status_code})")
out = in_app(f"""
from kalmido.core.undoweb import undo_group_to
try:
    undo_group_to(c, {AG.id}, {G1})
    print('NO-REFUSAL')
except Denied as e:
    print('CODE', e.code)""")
check("CODE 403" in out, f"an agent: 403 (obj_is_agent) {out[-300:]}")
OA = new(Bo, "For the agent", ORG)["id"]
check(Bo.post(B + f"/api/obj/{K}/{OA}/shares", json={"agent_id": AG.id, "role": "edit"}).status_code == 201, "OA shared with the agent")
n = len(groups(BOB))
r = AG.patch(OA, {"note": "by the agent", "expect_updated_at": get(Bo, OA)["updated_at"]})
check(r.ok and groups(AG.id) == [] and len(groups(BOB)) == n, f"an agent's write records no step ({r.status_code} {r.text[:200]})")

# ---------------------------------------------------------------- back up to a step: a conflict stays, the rest goes
check(patch(Ca, O2, title="Budget (Carl)")["title"] == "Budget (Carl)", "carl changes O2 meanwhile")
r = Bo.post(B + f"/api/undo/to/{G2}")
x = r.json() if r.ok else {}
o1, o2 = get(Bo, O1), get(Bo, O2)
check(r.ok and x["undone"] == [G3] and x["partial"] == [G2] and [(s["kind"], s["id"], s["code"]) for s in x["stayed"]] == [(K, O2, "conflict")]
      and x["stayed"][0]["reason"] and x["stopped"] is None, f"to G2: G3 back, G2 partial, O2 named as changed since {x} {r.status_code}")
check(o1["size"] == 1 and o1["note"] == "n2" and o2["note"] == "m2" and o2["title"] == "Budget (Carl)" and get(Bo, O3)["note"] == "x1"
      and get(Bo, O4)["note"] == "y1", f"O1 back, carl's change of O2 stays, O3 / O4 back {o1} {o2}")
st = {g["id"]: g["state"] for g in groups(BOB)}
check(st[G2] == "partial" and st[G3] == "undone" and st[G1] == "done", f"states {st}")
check(any(h["action"] == "undo" for h in Bo.get(B + f"/api/obj/{K}/{O1}/history").json()["items"]), "the history names the undo")
r = Bo.post(B + f"/api/undo/{G3}/redo")
check(r.ok and r.json()["redone"] == 2 and get(Bo, O3)["note"] == "x2" and get(Bo, O4)["note"] == "y2"
      and {g["id"]: g["state"] for g in groups(BOB)}[G3] == "done", f"redo of G3: forward again ({r.status_code} {r.text[:200]})")
r = Bo.post(B + f"/api/undo/to/{G3}")
check(r.ok and get(Bo, O3)["note"] == "x1", "G3 back again")
patch(Bo, O1, note="n3")  # a new step
st = {g["id"]: g["state"] for g in groups(BOB)}
check(G3 not in st and Bo.post(B + f"/api/undo/{G3}/redo").status_code == 404 and st.get(G2) == "partial" and len(parts(G2)) == 1,
      f"a new step ends the way forward: the undone group goes, the partial one keeps what stayed {st}")
G4 = groups(BOB)[-1]["id"]

# ---------------------------------------------------------------- a barrier stops the run
out = in_app(f"""
from flask import g
from kalmido.core.config import app as fa
from kalmido.core.undogroups import undo_barrier
with fa.test_request_context('/api/office/docs/1/finalise', method='POST'):
    g.user = {{"id": {BOB}}}
    print('BARRIER', undo_barrier(c, {BOB}, 'office', 'Change', ()))
    c.commit()""")
check("BARRIER" in out and groups(BOB)[-1]["state"] == "barrier", f"undo_barrier: a row of its own {out[-300:]}")
GB = groups(BOB)[-1]["id"]
patch(Bo, O1, note="n4")
G5 = groups(BOB)[-1]["id"]
r = Bo.post(B + f"/api/undo/to/{G4}")
x = r.json() if r.ok else {}
check(r.ok and x["undone"] == [G5] and x["stopped"] and x["stopped"]["id"] == GB and x["stopped"]["state"] == "barrier"
      and get(Bo, O1)["note"] == "n3" and "Schritt" in x["text"], f"to G4 over a barrier: G5 back, it stops at the barrier, G4 stays {x}")
check({g["id"]: g["state"] for g in groups(BOB)}[G4] == "done" and get(Bo, O1)["note"] == "n3", "the step before the barrier stays")

# ---------------------------------------------------------------- too big: listed, no copies
O5 = new(Bo, "Archive", ORG, note="small")["id"]
dbx("UPDATE obj_probe SET note=repeat('x', 300000) WHERE id=?", (O5,))
patch(Bo, O5, title="Archive 2")
gb = groups(BOB)[-1]
check(gb["state"] == "toobig" and gb["parts"] == 1 and gb["bytes"] > 256 * 1024 and parts(gb["id"]) == [],
      f"a part over 256 KB: the group is toobig, no copy {dict(gb)}")
check(items(Bo)[0]["state"] == "toobig" and items(Bo)[0]["undo"] is False, "listed as toobig, not undoable")
TOK2 = "cd34" * 8
patch(Bo, O2, headers={"X-Kalmido-Undo-Group": TOK2}, note="m3")
gm = groups(BOB)[-1]
dbx("UPDATE undo_groups SET parts=1000 WHERE id=?", (gm["id"],))
patch(Bo, O3, headers={"X-Kalmido-Undo-Group": TOK2}, note="x5")
gm = groups(BOB)[-1]
check(gm["state"] == "toobig" and gm["parts"] == 1001 and parts(gm["id"]) == [], f"the 1001st part: toobig, its copies gone {dict(gm)}")
patch(Bo, O4, note="y9")
G6 = groups(BOB)[-1]["id"]
r = Bo.post(B + f"/api/undo/to/{gm['id']}")
x = r.json() if r.ok else {}
check(r.ok and x["undone"] == [G6] and x["stopped"]["state"] == "toobig" and get(Bo, O3)["note"] == "x5", f"a toobig group stops the run {x}")

# ---------------------------------------------------------------- sealed values stay sealed in the copy
O6 = new(Bo, "Sealed", ORG)["id"]
dbx("UPDATE obj_probe SET note='kenc1:SEALEDAAA' WHERE id=?", (O6,))
patch(Bo, O6, note="kenc1:SEALEDBBB", title="Sealed 2")
GS = groups(BOB)[-1]["id"]
snap = dbx("SELECT snap FROM obj_undo WHERE group_id=?", (GS,))[0][0]
check("kenc1:SEALEDAAA" in snap and "SEALEDBBB" not in snap, "the copy holds the value as stored (sealed), nothing decoded")
r = Bo.post(B + f"/api/undo/to/{GS}")
check(r.ok and dbx("SELECT note, title FROM obj_probe WHERE id=?", (O6,))[0][0] == "kenc1:SEALEDAAA", "the undo writes the sealed value back as it was")

# 2.747.0 (#5249, review F1): a step older than a key rotation of its organisation is never written back (its sealed copy
# would be unreadable once the old key is gone); a step after the rotation goes as usual; during a rotation nothing goes
O7 = new(Bo, "Rekeyed", ORG, note="r1")["id"]
patch(Bo, O7, note="r2")
GK = groups(BOB)[-1]["id"]
dbx("INSERT INTO org_keys(org_id, wrapped, kek_check, created_at, rotated_at) VALUES(?, 'x', 'x', '2026-01-01T00:00:00+00:00', "
    "to_char(now() + interval '1 hour', 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00')) ON CONFLICT (org_id) DO UPDATE SET rotated_at=EXCLUDED.rotated_at", (ORG,))
r = Bo.post(B + f"/api/undo/to/{GK}")
x = r.json() if r.ok else {}
check(r.ok and get(Bo, O7)["note"] == "r2" and [s["id"] for s in x.get("stayed", [])] == [O7] and "schlüssel" in (x["stayed"][0]["reason"] or "").lower(),  # bob reads German
      f"rotated after the step: the copy stays unused, the answer names the key change {x} {r.status_code}")
dbx("UPDATE org_keys SET rotated_at='2026-01-01T00:00:00+00:00', rot_started_at=to_char(now(), 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00') WHERE org_id=?", (ORG,))
patch(Bo, O7, note="r3")
GK2 = groups(BOB)[-1]["id"]
r = Bo.post(B + f"/api/undo/to/{GK2}")
check(r.ok and get(Bo, O7)["note"] == "r3", f"while a rotation runs nothing is written back {r.status_code} {r.text[:200]}")
dbx("UPDATE org_keys SET rot_started_at=NULL WHERE org_id=?", (ORG,))
patch(Bo, O7, note="r4")
r = Bo.post(B + f"/api/undo/to/{groups(BOB)[-1]['id']}")
check(r.ok and get(Bo, O7)["note"] == "r3", f"a step after the rotation goes back as usual {r.status_code} {r.text[:200]}")
dbx("DELETE FROM org_keys WHERE org_id=? AND wrapped='x'", (ORG,))

# ---------------------------------------------------------------- the 301st group removes the oldest
dbx("INSERT INTO undo_groups(user_id, area, label_key, state, created_at, updated_at) SELECT ?, 'other', 'Change', 'barrier', "
    "to_char(now() - interval '2 days' + s * interval '1 second', 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00'), "
    "to_char(now() - interval '2 days', 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00') FROM generate_series(1, 300) s", (CARL,))
first = dbx("SELECT MIN(id) FROM undo_groups WHERE user_id=?", (CARL,))[0][0]
patch(Ca, O1, note="carl")
gc = groups(CARL)
check(len(gc) == 300 and first not in [x["id"] for x in gc] and gc[-1]["state"] == "done" and gc[-1]["parts"] == 1,
      f"300 kept, the oldest ({first}, carl's change of O2) went ({len(gc)}, {gc[0]['id']}, {dict(gc[-1])})")

# ---------------------------------------------------------------- the watchdog: older than 30 days, parts without a group
old = "to_char(now() - interval '31 days', 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00')"
GO = dbx(f"INSERT INTO undo_groups(user_id, area, label_key, state, parts, created_at, updated_at) VALUES(?, 'other', 'Change', 'done', 1, {old}, {old}) "
         "RETURNING id", (BOB,))[0][0]
dbx(f"INSERT INTO obj_undo(user_id, sess, kind, ref_id, created_at, group_id) VALUES(?, '', ?, ?, {old}, ?)", (BOB, K, O1, GO))
dbx("INSERT INTO obj_undo(user_id, sess, kind, ref_id, created_at, group_id) VALUES(?, '', ?, ?, "
    "to_char(now(), 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00'), 999999999)", (BOB, K, O1))
gone = until(lambda: not dbx("SELECT 1 FROM undo_groups WHERE id=?", (GO,)) and not dbx("SELECT 1 FROM obj_undo WHERE group_id IN (?, 999999999)", (GO,)), timeout=120)
check(gone, "the watchdog removed the 31 days old group with its part and the part without a group")
check(dbx("SELECT 1 FROM undo_groups WHERE id=?", (G1,)), "a young group stays")

# ---------------------------------------------------------------- the retention page counts
r = A.get(B + "/api/admin/retention")
u = r.json().get("undo", {}) if r.ok else {}
check(r.ok and u.get("groups", 0) >= 300 and u.get("bytes", 0) > 0 and u.get("oldest") and u.get("keep_days") == 30, f"GET /api/admin/retention: undo {u}")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: undo)
r = Fr.post(B + "/api/office/services", json={"name_de": "Beratung", "daily_rate": 800})
check(r.status_code in (200, 201), f"frida's service ({r.status_code} {r.text[:200]})")
SV = r.json()["id"]
check(Fr.patch(B + f"/api/office/services/{SV}", json={"name_de": "Beratung plus", "daily_rate": 900}).ok, "she changes her service")
fg = groups(FID)
check(fg and fg[-1]["state"] == "done" and parts(fg[-1]["id"])[0]["kind"] == "office_md_services", f"the office adapter (oun_pre): her step in a group {fg}")
FG = fg[-1]["id"]
r = Fr.post(B + "/api/clients", json={"name": "Private Client", "org_id": None})
FC = r.json()["id"]
check(Fr.patch(B + f"/api/clients/{FC}", json={"name": "Private Client Ltd"}).ok, "she renames her private client")
fg = groups(FID)
check(fg[-1]["id"] > FG and parts(fg[-1]["id"])[0]["kind"] == "client", f"ow_write: the client's step in a group of its own {fg}")
FG2 = fg[-1]["id"]
check([i["id"] for i in items(Fr)][:2] == [FG2, FG], "her list shows both, newest first")
r = Fr.post(B + f"/api/undo/to/{FG}")
sv = Fr.get(B + f"/api/office/services/{SV}").json()
check(r.ok and r.json()["undone"] == [FG2, FG] and sv["name_de"] == "Beratung" and sv["daily_rate"] == 800
      and Fr.get(B + f"/api/clients/{FC}").json()["name"] == "Private Client", f"she takes both back ({r.status_code} {r.text[:300]})")
r = Fr.post(B + f"/api/undo/{FG}/redo")
check(r.ok and Fr.get(B + f"/api/office/services/{SV}").json()["name_de"] == "Beratung plus", f"and redoes the service ({r.status_code} {r.text[:200]})")
check(Fr.post(B + f"/api/undo/to/{G1}").status_code == 404, "bob's group: 404 for her")

# 2.747.0 (#5249, review F2): the copy of a client / document deleted for good does not wait 30 days (their own deletions do
# not call obj_rows_drop): the watchdog drops parts of obj_track kinds whose row is gone; a living row keeps its parts
now_ = "to_char(now(), 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00')"
dbx(f"INSERT INTO obj_undo(user_id, sess, kind, ref_id, snap, created_at) VALUES(?, ?, 'client', 999999998, '{{\"clients\": [{{\"name\": \"Gone Ltd\"}}]}}', {now_})", (FID, "ef" * 8))
dbx(f"INSERT INTO obj_undo(user_id, sess, kind, ref_id, created_at) VALUES(?, ?, 'client', ?, {now_})", (FID, "ef" * 8, FC))
check(until(lambda: not dbx("SELECT 1 FROM obj_undo WHERE kind='client' AND ref_id=999999998"), timeout=120),
      "the watchdog dropped the copy of a client that is gone for good")
check(dbx("SELECT 1 FROM obj_undo WHERE kind='client' AND ref_id=? AND sess=?", (FC, "ef" * 8)), "the parts of a living client stay")

sys.exit(done("p2747_b_undo_core"))
