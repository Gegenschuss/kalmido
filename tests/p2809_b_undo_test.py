#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.809.0 (#5476, part B): undo across devices, the rest of stage 7 -- more areas record their steps in the core's step
groups (core/undoareas.py) and go back from the list (POST /api/undo/to/<id>), also from another device of the same person.
Invented names only.
 - bookmarks (life/bmundo.py): details changed on the laptop -> the phone lists the step (label with the title, device) and
   takes it back -> the old title / note / tags; redo -> the new ones; a link changed -> undo -> the old link, its preview
   fetched again; into the trash -> undo -> back; out of the trash refused (named) when the same link is saved again meanwhile
 - scheduling polls (calendars/pollundo.py): title, place and times changed on the laptop -> the phone takes it back -> the old
   ones (the times too); redo; the link switched off -> undo -> on, the same link; into the trash -> undo -> back
 - only own steps: another person neither lists nor takes back a step (404)
freelancer-matrix: undo (a person without an organisation: her bookmark step goes back from the list)
usage: p2809_b_undo_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, done  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

kt.fresh(prefix="P2809B")
FEAT = FEATURES
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
BOB = r.json().get("id")
Bo = kt.sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
LAP = {"X-Kalmido-Device": "Laptop (Test)"}
PHONE = kt.sess("alice", headers={"X-Kalmido-Device": "Phone (Test)"})  # a second sign-in of alice = another device
FID, Fr = freelancer(B, A)


def lst(s):
    r = s.get(B + "/api/undo")
    return r.json().get("items", []) if r.ok else []


def newest(s):
    x = lst(s)
    return x[0] if x else {}


def back(s, gid):
    r = s.post(B + f"/api/undo/to/{gid}")
    return r.json() if r.ok else {"status": r.status_code, "text": r.text[:200]}


def redo(s, gid):
    r = s.post(B + f"/api/undo/{gid}/redo")
    return r.json() if r.ok else {"status": r.status_code, "text": r.text[:200]}


def row(table, rid, cols):
    x = kt.dbx(f"SELECT {cols} FROM {table} WHERE id=?", (rid,))
    return dict(x[0]) if x else {}


# ---------------------------------------------------------------- bookmarks
r = A.post(B + "/api/bookmarks", json={"url": "https://example.com/bm-eins", "title": "Lesestoff Beispiel", "note": "alt",
                                       "tags": ["eins"]})
check(r.status_code == 201, f"(setup) a bookmark {r.status_code} {r.text[:120]}")
BM = r.json()["bookmark"]["id"]
n0 = len(lst(A))
r = A.patch(B + f"/api/bookmarks/{BM}", json={"title": "Lesestoff Neu", "note": "neu", "tags": ["zwei"], "state": "read"}, headers=LAP)
check(r.ok, f"the bookmark changed on the laptop {r.status_code} {r.text[:120]}")
g = newest(PHONE)
check(len(lst(A)) == n0 + 1 and g.get("kind") == "bookmark" and g.get("ref_id") == BM and "Lesestoff Beispiel" in (g.get("label") or "")
      and g.get("device") == "Laptop (Test)" and g.get("undo"), f"the phone lists the laptop's bookmark step {g}")
res = back(PHONE, g["id"])
b = A.get(B + f"/api/bookmarks/{BM}").json()
check(res.get("undone") == [g["id"]] and not res.get("stayed") and b.get("title") == "Lesestoff Beispiel" and b.get("note") == "alt"
      and b.get("tags") == ["eins"] and b.get("state") == "unread", f"taken back from the phone: title, note, tags, state {res} {b}")
res = redo(PHONE, g["id"])
b = A.get(B + f"/api/bookmarks/{BM}").json()
check(res.get("redone") == 1 and b.get("title") == "Lesestoff Neu" and b.get("tags") == ["zwei"], f"redo: the new details again {res} {b}")
r = A.patch(B + f"/api/bookmarks/{BM}", json={"expect_updated_at": b.get("updated_at")})
check(r.ok and newest(A).get("id") == g["id"], f"a save without a change records no step {r.status_code}")

r = A.patch(B + f"/api/bookmarks/{BM}", json={"url": "https://example.com/bm-zwei"})
check(r.ok and r.json().get("url") == "https://example.com/bm-zwei", f"the link changed {r.status_code}")
g = newest(A)
res = back(A, g["id"])
x = row("bookmarks", BM, "url, url_key, preview")
check(res.get("undone") == [g["id"]] and x.get("url") == "https://example.com/bm-eins" and x.get("preview") in ("pending", "ok", "failed"),
      f"undo of the link: the old link, its preview fetched again {res} {x}")

r = A.delete(B + f"/api/bookmarks/{BM}")
check(r.ok and row("bookmarks", BM, "deleted_at").get("deleted_at"), f"the bookmark went into the trash {r.status_code}")
g = newest(A)
check("Lesestoff" in (g.get("label") or "") and g.get("kind") == "bookmark", f"the delete is a step with the title {g}")
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and not row("bookmarks", BM, "deleted_at").get("deleted_at")
      and A.get(B + f"/api/bookmarks/{BM}").ok, f"undo of the delete: the bookmark is back {res}")

r = A.delete(B + f"/api/bookmarks/{BM}")
g = newest(A)
r = A.post(B + "/api/bookmarks", json={"url": "https://example.com/bm-eins", "title": "Doppelt"})
check(r.status_code == 201, f"(setup) the same link saved again {r.status_code} {r.text[:120]}")
res = back(A, g["id"])
check(not res.get("undone") and res.get("stayed") and res["stayed"][0].get("code") == "conflict"
      and row("bookmarks", BM, "deleted_at").get("deleted_at"), f"out of the trash refused, the same link is saved again {res}")

# ---------------------------------------------------------------- scheduling polls
TIMES = [{"start": "2031-03-10T10:00"}, {"start": "2031-03-11T14:30"}]
r = A.post(B + "/api/polls", json={"title": "Teamessen Beispiel", "duration": 60, "tz": "Europe/Berlin", "options": TIMES})
check(r.status_code == 201, f"(setup) a poll {r.status_code} {r.text[:120]}")
PO = r.json()["poll"]
PID = PO["id"]


def poll(s=A):
    return s.get(B + f"/api/polls/{PID}").json().get("poll") or {}


opts = [{"id": PO["options"][0]["id"], "start": PO["options"][0]["start"]}, {"start": "2031-03-12T09:00"}]
r = A.patch(B + f"/api/polls/{PID}", json={"title": "Teamessen Neu", "location": "Kantine", "options": opts}, headers=LAP)
check(r.ok and len(poll()["options"]) == 2 and poll()["options"][1]["start"].startswith("2031-03-12"), f"the poll changed on the laptop {r.status_code} {r.text[:160]}")
g = newest(PHONE)
check(g.get("kind") == "poll" and g.get("ref_id") == PID and "Teamessen Beispiel" in (g.get("label") or "") and g.get("device") == "Laptop (Test)",
      f"the phone lists the poll's step {g}")
res = back(PHONE, g["id"])
p = poll()
check(res.get("undone") == [g["id"]] and p.get("title") == "Teamessen Beispiel" and p.get("location") == ""
      and [o["start"][:16] for o in p["options"]] == ["2031-03-10T10:00", "2031-03-11T14:30"],
      f"taken back from the phone: title, place and the old times {res} {p.get('title')} {[o['start'] for o in p.get('options', [])]}")
res = redo(PHONE, g["id"])
check(res.get("redone") == 1 and poll().get("title") == "Teamessen Neu", f"redo: the new title again {res}")
tok = row("sched_polls", PID, "token_hash")["token_hash"]
r = A.patch(B + f"/api/polls/{PID}", json={"link_on": False})
check(r.ok and not poll()["link_on"], f"the link switched off {r.status_code}")
g = newest(A)
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and poll()["link_on"] and row("sched_polls", PID, "token_hash")["token_hash"] == tok,
      f"undo of the link switch: on again, the same link {res}")
r = A.delete(B + f"/api/polls/{PID}")
check(r.ok and row("sched_polls", PID, "deleted_at").get("deleted_at"), f"the poll went into the trash {r.status_code}")
g = newest(A)
check("Teamessen" in (g.get("label") or "") and g.get("kind") == "poll", f"the delete is a step with the title {g}")
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and not row("sched_polls", PID, "deleted_at").get("deleted_at") and poll().get("id") == PID,
      f"undo of the delete: the poll is back {res}")

# ---------------------------------------------------------------- only own steps
check(not [x for x in lst(Bo) if x["id"] == g["id"]], "bob does not see alice's step")
r = Bo.post(B + f"/api/undo/to/{g['id']}")
check(r.status_code == 404, f"bob cannot take alice's step back {r.status_code}")

# ---------------------------------------------------------------- a person without an organisation
r = Fr.post(B + "/api/bookmarks", json={"url": "https://example.com/frei", "title": "Frei Beispiel"})
check(r.status_code == 201, f"(setup) the freelancer's bookmark {r.status_code} {r.text[:120]}")
FB = r.json()["bookmark"]["id"]
r = Fr.patch(B + f"/api/bookmarks/{FB}", json={"title": "Frei Neu"})
g = newest(Fr)
res = back(Fr, g["id"])
check(r.ok and g.get("kind") == "bookmark" and res.get("undone") == [g["id"]] and Fr.get(B + f"/api/bookmarks/{FB}").json().get("title") == "Frei Beispiel",
      f"freelancer: the bookmark step goes back from the list {res}")

sys.exit(done("p2809_b_undo"))
