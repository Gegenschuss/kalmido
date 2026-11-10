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
 - team absences (hub/absundo.py): days moved on the laptop -> the phone lists it (area team, the old days) and takes it
   back; redo; deleted -> undo -> back; a member takes back the change of their own absence
 - a project's environments (lists/envundo.py): renamed -> undo -> the old name and switch; the webhook alone is no step;
   removed -> undo -> back with the webhook off; removed again, the name taken meanwhile -> undo refused (named)
 - appointment types (calendars/apptundo.py): name and length -> undo from the phone; deleted -> undo -> back
 - dispatch bookings (hub/dspundo.py): a job of two people changed -> one step, two parts -> undo -> both as before; the job
   deleted -> undo -> back; redo -> deleted again
 - notepads of the pin board (lists/padundo.py): renamed -> undo from the phone -> the old title; a text save -> undo
 - followed feeds (life/rssundo.py): unfollowed -> undo from the phone -> followed again; the same address followed again
   meanwhile -> undo refused (named), no error
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

# ---------------------------------------------------------------- team absences
r = A.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2031-05-04", "end_date": "2031-05-08", "note": "Urlaub", "org": ORG})
check(r.status_code == 201, f"(setup) an absence {r.status_code} {r.text[:120]}")
AB = r.json()["id"]


def absence():
    return row("hub_absences", AB, "start_date, end_date, half_day, deleted_at")


r = A.patch(B + f"/api/team/absences/{AB}", json={"start_date": "2031-05-11", "end_date": "2031-05-15"}, headers=LAP)
check(r.ok and absence().get("start_date") == "2031-05-11", f"the absence moved on the laptop {r.status_code} {r.text[:120]}")
g = newest(PHONE)
check(g.get("kind") == "absence" and g.get("area") == "team" and "2031-05-04 - 2031-05-08" in (g.get("label") or "")
      and g.get("device") == "Laptop (Test)", f"the phone lists the absence's step (area team, the old days) {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and absence().get("start_date") == "2031-05-04" and absence().get("end_date") == "2031-05-08",
      f"taken back from the phone: the old days {res} {absence()}")
items = A.get(B + f"/api/team/absences?org={ORG}&start=2031-05-01&end=2031-05-31").json().get("items", [])
check([x["start_date"] for x in items if x["id"] == AB] == ["2031-05-04"], f"the team view shows the old days {items}")
res = redo(PHONE, g["id"])
check(res.get("redone") == 1 and absence().get("start_date") == "2031-05-11", f"redo: the new days again {res}")
r = A.delete(B + f"/api/team/absences/{AB}")
check(r.ok and absence().get("deleted_at"), f"the absence deleted {r.status_code}")
g = newest(A)
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and not absence().get("deleted_at"), f"undo of the delete: the absence is back {res}")
# a person who may not change it any more takes nothing back: bob's own absence, bob leaves the area's people? -> the admin
# rule: bob's step on his own absence goes back for bob; alice's step on bob's absence needs alice to be admin NOW
r = Bo.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2031-06-01", "end_date": "2031-06-02", "org": ORG})
check(r.status_code == 201, f"(setup) bob's absence {r.status_code} {r.text[:120]}")
BAB = r.json()["id"]
r = Bo.patch(B + f"/api/team/absences/{BAB}", json={"half_day": "am", "end_date": "2031-06-01"})
g = newest(Bo)
res = back(Bo, g["id"])
check(r.ok and g.get("kind") == "absence" and res.get("undone") == [g["id"]]
      and row("hub_absences", BAB, "end_date")["end_date"] == "2031-06-02", f"bob takes back his own change {res}")

# ---------------------------------------------------------------- a project's environments
r = A.post(B + "/api/lists", json={"name": "Umgebungen Beispiel"})
check(r.ok, f"(setup) a project {r.status_code} {r.text[:120]}")
LID = r.json()["id"]
r = A.post(B + f"/api/lists/{LID}/envs", json={"name": "Test"})
check(r.status_code == 201, f"(setup) an environment {r.status_code} {r.text[:120]}")
EN = r.json()["id"]
r = A.patch(B + f"/api/envs/{EN}", json={"name": "Abnahme", "auto_close": True}, headers=LAP)
check(r.ok, f"the environment renamed on the laptop {r.status_code} {r.text[:120]}")
g = newest(PHONE)
check(g.get("kind") == "env" and "Test" in (g.get("label") or ""), f"the phone lists the environment's step {g}")
res = back(PHONE, g["id"])
x = row("list_envs", EN, "name, auto_close")
check(res.get("undone") == [g["id"]] and x == {"name": "Test", "auto_close": 0}, f"taken back: the old name and switch {res} {x}")
r = A.patch(B + f"/api/envs/{EN}", json={"hook": "on"})
check(r.ok and newest(A).get("id") == g["id"], f"the webhook alone records no step {r.status_code}")
r = A.delete(B + f"/api/envs/{EN}")
g = newest(A)
check(r.ok and g.get("kind") == "env", f"the removal is a step {r.status_code} {g}")
res = back(A, g["id"])
x = row("list_envs", EN, "deleted_at, token_hash")
check(res.get("undone") == [g["id"]] and not x.get("deleted_at") and x.get("token_hash") == "", f"undo: it is back, the webhook stays off {res} {x}")
r = A.delete(B + f"/api/envs/{EN}")
g = newest(A)
r = A.post(B + f"/api/lists/{LID}/envs", json={"name": "Test"})
check(r.status_code == 201, f"(setup) the name taken by a new environment {r.status_code}")
res = back(A, g["id"])
check(not res.get("undone") and res.get("stayed") and res["stayed"][0].get("reason") and row("list_envs", EN, "deleted_at").get("deleted_at"),
      f"back out of the trash refused: the name is taken meanwhile {res}")

# ---------------------------------------------------------------- appointment types of the booking page
r = A.put(B + "/api/appt/page", json={"title": "Termine Beispiel"})
check(r.ok, f"(setup) the booking page {r.status_code} {r.text[:120]}")
r = A.post(B + "/api/appt/types", json={"name": "Erstgespraech", "duration_min": 30})
check(r.status_code == 201, f"(setup) an appointment type {r.status_code} {r.text[:120]}")
AT = r.json()["id"]
r = A.patch(B + f"/api/appt/types/{AT}", json={"name": "Beratung", "duration_min": 60}, headers=LAP)
g = newest(PHONE)
check(r.ok and g.get("kind") == "appt_type" and g.get("area") == "calendar" and "Erstgespraech" in (g.get("label") or ""),
      f"the phone lists the appointment type's step {r.status_code} {g}")
res = back(PHONE, g["id"])
t = [x for x in A.get(B + "/api/appt/types").json().get("types", []) if x["id"] == AT]
check(res.get("undone") == [g["id"]] and t and t[0]["name"] == "Erstgespraech" and t[0]["duration_min"] == 30, f"taken back: name and length {res} {t}")
r = A.delete(B + f"/api/appt/types/{AT}")
g = newest(A)
res = back(A, g["id"])
check(r.ok and res.get("undone") == [g["id"]] and [x for x in A.get(B + "/api/appt/types").json().get("types", []) if x["id"] == AT],
      f"undo of the delete: the type is back {res}")

# ---------------------------------------------------------------- bookings of the dispatch board
r = A.post(B + "/api/team/dispo/bookings", json={"title": "Dreh Beispiel", "start": "2031-07-01", "end": "2031-07-02", "org": ORG,
                                                 "resources": [{"kind": "user", "id": ALICE}, {"kind": "user", "id": BOB}]})
check(r.status_code == 201 and len(r.json().get("bookings", [])) == 2, f"(setup) a job with two people {r.status_code} {r.text[:160]}")
BK = sorted(x["id"] for x in r.json()["bookings"])


def bookings():
    return [dict(x) for x in kt.dbx("SELECT id, title, start, status, deleted_at FROM hub_bookings WHERE id IN (?, ?) ORDER BY id", tuple(BK))]


r = A.patch(B + f"/api/team/dispo/bookings/{BK[0]}", json={"title": "Dreh Neu", "start": "2031-07-03", "end": "2031-07-04", "all": True},
            headers=LAP)
check(r.ok and all(x["title"] == "Dreh Neu" for x in bookings()), f"the whole job changed on the laptop {r.status_code} {r.text[:120]}")
g = newest(PHONE)
check(g.get("kind") == "booking" and g.get("area") == "team" and g.get("parts") == 2 and "Dreh Beispiel" in (g.get("label") or ""),
      f"one step with a part per booking {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and all(x["title"] == "Dreh Beispiel" and x["start"] == "2031-07-01" for x in bookings()),
      f"taken back from the phone: both bookings as before {res} {bookings()}")
r = A.delete(B + f"/api/team/dispo/bookings/{BK[0]}?all=1")
check(r.ok and all(x["deleted_at"] for x in bookings()), f"the job deleted {r.status_code}")
g = newest(A)
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and not any(x["deleted_at"] for x in bookings()), f"undo of the delete: the job is back {res}")
res = redo(A, g["id"])
check(res.get("redone") == 2 and all(x["deleted_at"] for x in bookings()), f"redo: both deleted again {res}")

# ---------------------------------------------------------------- notepads of a project's pin board
r = A.post(B + f"/api/lists/{LID}/notepads", json={"title": "Notizen Beispiel", "body": "erste Zeile"})
check(r.ok and r.json().get("id"), f"(setup) a notepad {r.status_code} {r.text[:120]}")
NP = r.json()["id"]
r = A.patch(B + f"/api/notepads/{NP}", json={"title": "Notizen Neu"}, headers=LAP)
g = newest(PHONE)
check(r.ok and g.get("kind") == "notepad" and "Notizen Beispiel" in (g.get("label") or ""), f"the phone lists the rename {r.status_code} {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and row("list_notepads", NP, "title")["title"] == "Notizen Beispiel", f"taken back: the old title {res}")
r = A.patch(B + f"/api/notepads/{NP}", json={"body": "neuer Text"})
g = newest(A)
res = back(A, g["id"])
check(r.ok and res.get("undone") == [g["id"]] and row("list_notepads", NP, "body")["body"] == "erste Zeile", f"a text save taken back {res}")
r = A.get(B + f"/api/lists/{LID}/overview")
pads = [x for x in ((r.json().get("layout") or {}).get("pads") or []) if x.get("id") == NP] if r.ok else []
check(pads and pads[0].get("body") == "erste Zeile" and pads[0].get("title") == "Notizen Beispiel", f"the pin board shows the old title and text {r.status_code} {pads}")

# ---------------------------------------------------------------- followed feeds
kt.dbx("INSERT INTO rss_feeds(user_id,url,title,created_at) VALUES(?,?,?,?)", (ALICE, "https://feeds.example.com/undo.xml", "Nachrichten Beispiel",
                                                                             "2031-01-01T00:00:00+00:00"))  # following needs a fetch: a row
FD = kt.dbx("SELECT id FROM rss_feeds WHERE url=?", ("https://feeds.example.com/undo.xml",))[0]["id"]
r = A.delete(B + f"/api/feeds/{FD}")
g = newest(A)
check(r.ok and g.get("kind") == "feed" and "Nachrichten Beispiel" in (g.get("label") or ""), f"unfollowing is a step with the title {r.status_code} {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and not row("rss_feeds", FD, "deleted_at").get("deleted_at")
      and [f for f in A.get(B + "/api/feeds").json().get("feeds", []) if f["id"] == FD], f"taken back from the phone: followed again {res}")
r = A.delete(B + f"/api/feeds/{FD}")
g = newest(A)
kt.dbx("INSERT INTO rss_feeds(user_id,url,created_at) VALUES(?,?,?)", (ALICE, "https://feeds.example.com/undo.xml", "2031-01-02T00:00:00+00:00"))
res = back(A, g["id"])
check(not res.get("undone") and res.get("stayed") and res["stayed"][0].get("code") == "conflict" and row("rss_feeds", FD, "deleted_at").get("deleted_at"),
      f"back refused (named): the same address is followed again meanwhile {res}")

# ---------------------------------------------------------------- only own steps
g = newest(A)
check(g.get("id") and not [x for x in lst(Bo) if x["id"] == g["id"]], "bob does not see alice's step")
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
