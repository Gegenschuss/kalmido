#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.872.0 (#5532): the disposition on the shared core -- the shoot day (light kind "shoot_day") and its call sheet (kind
"callsheet", hub/dspkern.py). Invented names, firms and numbers only.
 - an organisation with Film & Video: a member saves the call sheet of a shoot day -> the row carries the core's columns
   (owner_id, rev, updated_by), the core's history lists "create" and the change by name with the changed details (keys
   only, never the values); a second change of the same person within ten minutes merges into it
 - the sketch: its history entry is a mark ("sketch"), never the picture (no history row holds the base64 text)
 - undo across devices: the member's change of the call sheet is a step of the core (GET /api/undo, kind callsheet) and goes
   back from the list -> the old details; the history names the undo
 - rights: the core's role of the shoot day -- a read-only member reads the call sheet and its history but saves nothing
   (403, the read-only text), restores no booking (403); a guest sees nothing (404); another organisation's admin nothing
 - the trash: the shoot day deleted (the whole job) -> the call sheet goes into the core's trash with it (deleted_at,
   history "trash"), the GET 404; the bookings restored -> the call sheet is back with its details (history "restore");
   deleted again and taken back from the list of steps (/api/undo, hub/dspundo.py) -> the call sheet is back as well;
   one booking of two deleted -> the call sheet stays
 - the core knows the shoot day: obj_role (test route /api/test/objrole) = manage for the member, view for the read-only
   member, nothing for the guest / another organisation (the call sheet's role is the same, checked above through its routes)
freelancer-matrix: hub (frida has no organisation: her call sheet's history in her personal area; greta: 404)
tenant-matrix: hub (greta, another person's area: frida's call sheet history 404; the other organisation's admin: 404)
usage: p5532_a_dispokern_test.py <datadir>"""
import base64
import struct
import zlib

import kt
from kt import B, check, done
from freelancer_fixture import freelancer

kt.fresh(prefix="P5532A")
A = kt.setup()
FEAT = "cal,collab,comments,kanban,fields,files,contacts,office,clients,dispo,workload"
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Film", "admin_id": ALICE}).json()["id"]
OTHER = A.post(B + "/api/admin/orgs", json={"name": "Beta Film", "admin_id": ALICE}).json()["id"]
U = {}
for name, org, role in (("bob", ORG, "member"), ("rita", ORG, "readonly"), ("gus", ORG, "guest"), ("olga", OTHER, "admin")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": org, "role": role}], "username": name, "display_name": name.title(),
                                       "password": "password123", "email": f"{name}@example.com"})
    check(r.ok, f"(setup) {name} {r.text[:120]}")
    U[name] = r.json()["id"]
S = {n: kt.sess(n) for n in U}
for n, s in S.items():
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.put(B + "/api/industry", json={"industry": "film"}).ok, "(setup) Alpha Film chooses Film & Video")
Bo, Ri, Gu, Ol = S["bob"], S["rita"], S["gus"], S["olga"]
PHONE = kt.sess("bob", headers={"X-Kalmido-Device": "Phone (Test)"})  # a second sign-in of bob = another device

r = A.post(B + "/api/team/dispo/bookings", json={"title": "Dreh Werbung", "start": "2031-05-06T07:00", "end": "2031-05-06T19:00",
                                                 "status": "firm", "org": ORG,
                                                 "resources": [{"kind": "user", "id": ALICE}, {"kind": "user", "id": U["bob"]}]})
check(r.status_code == 201, f"(setup) a shoot day of two people {r.status_code} {r.text[:160]}")
JOB = r.json()["bookings"][0]["job"]
BKS = sorted(x["id"] for x in r.json()["bookings"])
CS = f"/api/team/dispo/callsheet/{JOB}?org={ORG}"
HIST = f"/api/team/dispo/callsheet/{JOB}/history?org={ORG}"


def png():
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + bytes((30, 90, 160)) * 32 for _ in range(20))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 20, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def cs_row():
    x = kt.dbx("SELECT id, owner_id, rev, updated_by, deleted_at, deleted_by FROM hub_callsheets WHERE org_id=? AND job=?", (ORG, JOB))
    return dict(x[0]) if x else {}


def hist(s=Bo, url=HIST):
    r = s.get(B + url)
    return r.json().get("history", []) if r.ok else {"status": r.status_code}


def newest(s):
    r = s.get(B + "/api/undo")
    x = r.json().get("items", []) if r.ok else []
    return x[0] if x else {}


def role(s, kind, rid):
    r = s.get(B + f"/api/test/objrole/{kind}/{rid}")
    return r.json().get("role") if r.ok else None


# ---------------------------------------------------------------- the core's role of the shoot day
check(role(Bo, "shoot_day", BKS[0]) == "manage", f"the member: the shoot day's role manage ({role(Bo, 'shoot_day', BKS[0])})")
check(role(Ri, "shoot_day", BKS[0]) == "view", f"the read-only member: view ({role(Ri, 'shoot_day', BKS[0])})")
check(role(Gu, "shoot_day", BKS[0]) is None and role(Ol, "shoot_day", BKS[0]) is None, "a guest / another organisation's admin: no role")

# ---------------------------------------------------------------- saving through obj_write: the core's columns and history
r = Bo.put(B + CS, json={"data": {"loc_name": "Halle 1", "set_phone": "0170 1234567"}})
check(r.ok and r.json()["callsheet"]["data"].get("loc_name") == "Halle 1", f"the member saves the call sheet {r.status_code} {r.text[:160]}")
V1 = r.json()["callsheet"]["updated_at"]
row = cs_row()
check(row.get("owner_id") == U["bob"] and row.get("updated_by") == U["bob"] and (row.get("rev") or 0) >= 2 and not row.get("deleted_at"),
      f"the row carries the core's columns {row}")
CSID = row["id"]
h = hist()
check([x["action"] for x in h] == ["update", "create"] and h[0]["name"] == "Bob" and h[0]["fields"] == ["loc_name", "set_phone"],
      f"the history: created, then the details by name (keys only) {h}")
check("0170 1234567" not in str(h) and "Halle 1" not in str(h), "the history route shows which details changed, never their values")
r = Bo.put(B + CS, json={"data": {"loc_name": "Halle 2", "set_phone": "0170 1234567"}, "expect_updated_at": V1})
check(r.ok, f"a second change with the version read {r.status_code}")
h = hist()
check(len(h) == 2 and h[0]["fields"] == ["loc_name", "set_phone"], f"the same person within ten minutes: one entry {h}")
r = Bo.put(B + CS, json={"data": {"loc_name": "veraltet"}, "expect_updated_at": V1})
check(r.status_code == 409 and (r.json().get("callsheet") or {}).get("data", {}).get("loc_name") == "Halle 2",
      f"a stale save: 409 with the current state, as before ({r.status_code})")
r = A.put(B + CS, json={"data": {"loc_name": "Halle 2", "set_phone": "0170 1234567", "important": "Bitte leise"}})
h = hist(A)
check(r.ok and h[0]["name"] == "Alice Admin" and h[0]["fields"] == ["important"], f"another person: an entry of her own {h[:1]}")
n = cs_row()["rev"]
r = A.put(B + CS, json={"data": {"loc_name": "Halle 2", "set_phone": "0170 1234567", "important": "Bitte leise"}})
check(r.ok and cs_row()["rev"] == n and len(hist(A)) == len(h), "the same details again: no change, no new version, no entry")

# ---------------------------------------------------------------- the sketch: a mark in the history, never the picture
pic = base64.b64encode(png()).decode()
r = A.put(B + CS, json={"data": {"loc_name": "Halle 2", "set_phone": "0170 1234567", "important": "Bitte leise"},
                        "sketch": "data:image/png;base64," + pic})
h = hist(A)
check(r.ok and r.json()["callsheet"]["sketch"] is True and "sketch" in h[0]["fields"] and h[0]["name"] == "Alice Admin",
      f"the sketch is a change of the history (merged into her entry of ten minutes) {h[:1]}")
check(not kt.dbx("SELECT 1 FROM obj_history WHERE kind='callsheet' AND ref_id=? AND (vals_before LIKE ? OR vals_after LIKE ?)",
                 (CSID, "%" + pic[:40] + "%", "%" + pic[:40] + "%")), "no history row holds the picture")

# ---------------------------------------------------------------- undo across devices (the core's step of the call sheet)
r = Bo.put(B + CS, json={"data": {"loc_name": "Halle 3", "set_phone": "0170 1234567", "important": "Bitte leise"}})
check(r.ok, "bob changes the location on the laptop")
g = newest(PHONE)
check(g.get("kind") == "callsheet", f"the phone lists the step of the call sheet {g}")
r = PHONE.post(B + f"/api/undo/to/{g.get('id')}")
check(r.ok and Bo.get(B + CS).json()["callsheet"]["data"].get("loc_name") == "Halle 2", f"taken back from the phone: the old location {r.status_code} {r.text[:160]}")
check(hist()[0]["action"] == "undo", f"the history names the undo {hist()[:1]}")

# ---------------------------------------------------------------- rights
check(Ri.get(B + CS).ok and isinstance(hist(Ri), list), "the read-only member reads the call sheet and its history")
r = Ri.put(B + CS, json={"data": {"loc_name": "fremd"}})
check(r.status_code == 403 and "read-only" in r.text, f"the read-only member saves nothing (403, the read-only text) {r.status_code} {r.text[:120]}")
check(Gu.get(B + CS).status_code == 404 and Gu.put(B + CS, json={"data": {}}).status_code == 404, "a guest: 404")
check(Ol.get(B + f"/api/team/dispo/callsheet/{JOB}/history?org={ORG}").status_code == 404, "another organisation's admin: the history 404")
check(Ol.put(B + CS, json={"data": {}}).status_code == 404, "another organisation's admin: saving 404")
check(Bo.get(B + CS).json()["callsheet"]["data"].get("loc_name") == "Halle 2", "nothing was written by them")

# ---------------------------------------------------------------- the trash follows the shoot day
r = A.delete(B + f"/api/team/dispo/bookings/{BKS[1]}")
check(r.ok and not cs_row().get("deleted_at"), "one booking of two deleted: the call sheet stays")
check(A.post(B + "/api/team/dispo/bookings/restore", json={"ids": [BKS[1]]}).ok, "(setup) the booking back")
r = A.delete(B + f"/api/team/dispo/bookings/{BKS[0]}?all=1")
row = cs_row()
check(r.ok and row.get("deleted_at") and row.get("deleted_by") == ALICE, f"the shoot day deleted: the call sheet in the core's trash {row}")
check(A.get(B + CS).status_code == 404, "... the call sheet 404 with its shoot day")
check(kt.dbx("SELECT action FROM obj_history WHERE kind='callsheet' AND ref_id=? ORDER BY id DESC LIMIT 1", (CSID,))[0][0] == "trash",
      "the history notes the trash")
check(Ri.post(B + "/api/team/dispo/bookings/restore", json={"ids": BKS}).status_code == 403,
      "the read-only member restores no booking of the shoot day (403, as before)")
r = A.post(B + "/api/team/dispo/bookings/restore", json={"ids": BKS})
check(r.ok and not cs_row().get("deleted_at"), f"the bookings back: the call sheet out of the trash {r.status_code} {cs_row()}")
cs = A.get(B + CS).json().get("callsheet") or {}
check(cs.get("data", {}).get("loc_name") == "Halle 2" and cs.get("sketch") is True, "... with its details and sketch")
check(hist(A)[0]["action"] == "restore", f"the history notes the restore {hist(A)[:1]}")
r = A.delete(B + f"/api/team/dispo/bookings/{BKS[0]}?all=1")
check(r.ok and cs_row().get("deleted_at"), "deleted again: in the trash")
g = newest(A)
r = A.post(B + f"/api/undo/to/{g.get('id')}")
check(r.ok and g.get("kind") == "booking" and not cs_row().get("deleted_at"),
      f"the delete taken back from the list of steps: the call sheet is back too {r.status_code} {g} {cs_row()}")
r = A.post(B + f"/api/undo/{g.get('id')}/redo")
check(r.ok and cs_row().get("deleted_at"), f"redo: the call sheet goes with the shoot day again {r.status_code}")
check(A.post(B + "/api/team/dispo/bookings/restore", json={"ids": BKS}).ok and not cs_row().get("deleted_at"), "(setup) back again")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: hub)
FID, Fr = freelancer(B, A, "frida", features=FEAT)
GID, Gr = freelancer(B, A, "greta", features=FEAT)
check(Fr.put(B + "/api/industry", json={"industry": "film"}).ok, "(setup) frida chooses Film & Video")
r = Fr.post(B + "/api/team/dispo/bookings", json={"title": "Solo-Dreh", "start": "2031-06-01", "status": "firm",
                                                  "resources": [{"kind": "user", "id": FID}]})
check(r.status_code == 201, f"(setup) frida's shoot day {r.text[:160]}")
FJOB, FB = r.json()["bookings"][0]["job"], r.json()["bookings"][0]["id"]
PO = kt.dbx("SELECT org_id FROM hub_bookings WHERE id=?", (FB,))[0][0]
FCS, FH = f"/api/team/dispo/callsheet/{FJOB}?org={PO}", f"/api/team/dispo/callsheet/{FJOB}/history?org={PO}"
check(role(Fr, "shoot_day", FB) == "manage", "frida: her own shoot day manage")
r = Fr.put(B + FCS, json={"data": {"loc_name": "Wohnzimmer"}})
h = hist(Fr, FH)
check(r.ok and [x["action"] for x in h] == ["update", "create"] and h[0]["fields"] == ["loc_name"], f"frida saves, her history {h}")
check(Gr.get(B + f"/api/team/dispo/callsheet/{FJOB}/history?org={PO}").status_code == 404, "greta: frida's call sheet history 404")
check(role(Gr, "shoot_day", FB) is None, "greta: no role on frida's shoot day")
check(Fr.delete(B + f"/api/team/dispo/bookings/{FB}").ok and kt.dbx("SELECT deleted_at FROM hub_callsheets WHERE org_id=? AND job=?",
                                                                     (PO, FJOB))[0][0], "frida deletes her shoot day: the call sheet in the trash")
check(Fr.post(B + "/api/team/dispo/bookings/restore", json={"ids": [FB]}).ok
      and Fr.get(B + FCS).json()["callsheet"]["data"].get("loc_name") == "Wohnzimmer", "restored: back with its details")

raise SystemExit(done("p5532_a_dispokern"))
