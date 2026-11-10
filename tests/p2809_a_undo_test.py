#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.809.0 (#5476, part A): undo across devices for the areas of group 1 -- their steps in the core's step groups
(core/undoareas.py), listed by GET /api/undo and taken back by POST /api/undo/to/<id> from another device of the person.
Invented names only.
 - sections (lists/secundo.py): a new section is a step (listed on the phone with its name) -> undo = gone, redo = back with its
   id; a deleted section -> undo = back with its card; restoring it from the trash is a step too; one deleted again since stays
 - time entries (personal/timeundo.py): a change on the laptop is listed on the phone (area time, duration before) and goes
   back / forward; a deleted entry comes back with its id and goes again on redo; not back into a project without time
   tracking; another person cannot take it back
 - custom fields (lists/fieldundo.py): a new field is a step (undo = field trash, redo = back with its id); a rename goes back;
   an option added and used since is not removed by an undo (409); a change that clears values records no server step; a
   deleted field comes back and goes again on redo
 - rules (lists/ruleundo.py): a change goes back (old name, switched on again); into the trash -> undo -> back, redo -> trash
 - a project's settings (lists/lpundo.py): a rename + colour on the laptop is listed on the phone (area tasks, kind listset,
   label with the old name, device, the answer names its group) and goes back from there; redo; archiving -> undo -> out of
   the archive; a save of the same values and a save with a folder (side effects) record no step; a new sidebar order since
   does not block the undo; a rename by someone else since stays (named); a project admin takes back her own rename, but not
   after she became an editor (noaccess); another person neither lists nor takes back the step (404)
freelancer-matrix: undo (a person without an organisation: her project's colour, her new section and field and her deleted time entry go back from the list)
usage: p2809_a_undo_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, done  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(prefix="P2809A")
FEAT = "collab,comments,time"
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"orgs": [], "username": "bob", "display_name": "Bob", "password": "password123",
                                   "email": "bob@example.com"})
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


def lrow(s, lid):
    return next((x for x in s.get(B + "/api/state").json().get("lists", []) if x["id"] == lid), {})


# ---------------------------------------------------------------- a project's settings
r = A.post(B + "/api/lists", json={"name": "Projekt Beispiel", "color": "#3366cc"})
check(r.ok, f"(setup) a project {r.status_code} {r.text[:120]}")
L = r.json()["id"]
r = A.patch(B + f"/api/lists/{L}", json={"name": "Projekt Neu", "color": "#cc3333"}, headers=LAP)
check(r.ok and r.json().get("undo_group"), f"renamed on the laptop, the answer names its step group {r.status_code} {r.text[:160]}")
UG = r.json().get("undo_group")
g = newest(PHONE)
check(g.get("id") == UG and g.get("area") == "tasks" and g.get("kind") == "listset" and g.get("ref_id") == L
      and "Projekt Beispiel" in (g.get("label") or "") and g.get("device") == "Laptop (Test)" and g.get("undo"),
      f"the phone lists the laptop's step: area, kind, label with the old name, device {g}")
res = back(PHONE, g["id"])
x = lrow(A, L)
check(res.get("undone") == [g["id"]] and not res.get("stayed") and x.get("name") == "Projekt Beispiel" and x.get("color") == "#3366cc",
      f"taken back from the phone: the old name and colour {res} {x.get('name')} {x.get('color')}")
r = PHONE.post(B + f"/api/undo/{g['id']}/redo")
x = lrow(A, L)
check(r.ok and x.get("name") == "Projekt Neu" and x.get("color") == "#cc3333", f"redo: the new name again {r.status_code} {x.get('name')}")
check(Bo.post(B + f"/api/undo/to/{g['id']}").status_code == 404 and not [y for y in lst(Bo) if y["id"] == g["id"]],
      "another person neither lists nor takes back alice's step (404)")

# archive: its own label, back out of the archive
r = A.patch(B + f"/api/lists/{L}", json={"archived": 1})
g = newest(A)
check(r.ok and g.get("kind") == "listset" and (g.get("label") or "").startswith("Archived"), f"archiving is a step with its label {g.get('label')}")
res = back(A, g["id"])
x = lrow(A, L)
check(res.get("undone") == [g["id"]] and not x.get("archived"), f"undo: out of the archive again {res} {x.get('archived')}")

# nothing changed / side effects: no step
before = newest(A).get("id")
r = A.patch(B + f"/api/lists/{L}", json={"name": "Projekt Neu"})
check(r.ok and not r.json().get("undo_group") and newest(A).get("id") == before, f"a save of the same name records no step {newest(A)}")
r = A.patch(B + f"/api/lists/{L}", json={"name": "Projekt Mappe", "folder": "Ablage Beispiel"})
check(r.ok and not r.json().get("undo_group") and newest(A).get("id") == before,
      f"a save that moves it into a folder (side effects) records no server step (the browser keeps its own) {newest(A)}")
A.patch(B + f"/api/lists/{L}", json={"folder": ""})

# a new sidebar order since does not block; a rename by someone else since does
r = A.patch(B + f"/api/lists/{L}", json={"name": "Projekt Zwei"})
g = newest(A)
ids = [y["id"] for y in A.get(B + "/api/state").json().get("lists", []) if not y.get("is_inbox")]
A.post(B + "/api/lists/reorder", json={"ids": list(reversed(ids))})
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and lrow(A, L).get("name") == "Projekt Mappe",
      f"a new sidebar order since does not block the undo of a rename {res} {lrow(A, L).get('name')}")
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "admin"})
check(r.ok, f"(setup) bob becomes a project admin {r.status_code} {r.text[:120]}")
A.patch(B + f"/api/lists/{L}", json={"name": "Projekt Drei"})
ga = newest(A)
r = Bo.patch(B + f"/api/lists/{L}", json={"name": "Projekt Bob"})
check(r.ok and r.json().get("undo_group"), f"the project admin renames it: a step of his {r.status_code} {r.text[:120]}")
gb = newest(Bo)
res = back(A, ga["id"])
check(not res.get("undone") and res.get("stayed") and lrow(A, L).get("name") == "Projekt Bob",
      f"alice's rename does not go back over bob's: it stays, named {res}")
res = back(Bo, gb["id"])
check(res.get("undone") == [gb["id"]] and lrow(A, L).get("name") == "Projekt Drei", f"the admin takes back his own rename {res}")
r = Bo.patch(B + f"/api/lists/{L}", json={"name": "Projekt Bob Zwei"})
gb = newest(Bo)
A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"})
res = back(Bo, gb["id"])
check(not res.get("undone") and res.get("stayed") and res["stayed"][0].get("code") == "noaccess" and lrow(A, L).get("name") == "Projekt Bob Zwei",
      f"an editor now: his step does not go back (the rights of today) {res}")

# ---------------------------------------------------------------- sections: create / delete / restore
def secs(s, lid):
    return {x["id"]: x for x in s.get(B + "/api/state").json().get("sections", []) if x["list_id"] == lid}


r = A.post(B + "/api/lists", json={"name": "Brett Beispiel"})
SL = r.json()["id"]
r = A.post(B + "/api/sections", json={"list_id": SL, "name": "Offen"}, headers=LAP)
check(r.ok and r.json().get("undo_group"), f"a new section on the laptop: a step {r.status_code} {r.text[:120]}")
S1 = r.json()["id"]
g = newest(PHONE)
check(g.get("kind") == "section_life" and g.get("ref_id") == S1 and "Offen" in (g.get("label") or "") and g.get("area") == "tasks",
      f"the phone lists it with the section's name {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and S1 not in secs(A, SL), f"taken back: the section is gone (in the trash) {res}")
r = PHONE.post(B + f"/api/undo/{g['id']}/redo")
check(r.ok and S1 in secs(A, SL), f"redo: the section is back with its id {r.status_code} {r.text[:120]}")
r = A.post(B + "/api/tasks", json={"title": "Karte Beispiel", "list_id": SL, "section_id": S1})
T1 = r.json()["id"]
r = A.delete(B + f"/api/sections/{S1}")
check(r.ok and r.json().get("undo_group") and S1 not in secs(A, SL), f"the section deleted: a step {r.status_code}")
g = newest(A)
check(g.get("kind") == "section_life" and (g.get("label") or "").startswith("Section") and "deleted" in (g.get("label") or ""),
      f"labelled as deleted {g.get('label')}")
res = back(A, g["id"])
t = A.get(B + f"/api/tasks/{T1}").json()
check(res.get("undone") == [g["id"]] and S1 in secs(A, SL) and t.get("section_id") == S1,
      f"undo of the delete: the section is back with its card {res} {t.get('section_id')}")
r = A.post(B + f"/api/undo/{g['id']}/redo")
check(r.ok and S1 not in secs(A, SL), f"redo: deleted again {r.status_code}")
r = A.post(B + f"/api/sections/{S1}/restore")
g = newest(A)
check(r.ok and g.get("kind") == "section_life" and S1 in secs(A, SL), f"restoring it from the trash is a step too {g}")
A.put(B + f"/api/lists/{SL}/members", json={"user_id": BOB, "role": "edit"})
r = Bo.delete(B + f"/api/sections/{S1}")  # someone else deleted it since: the restore's undo stays, named
check(r.ok, f"(setup) bob deletes the section {r.status_code} {r.text[:120]}")
res = back(A, g["id"])
check(not res.get("undone") and res.get("stayed") and res["stayed"][0].get("code") == "conflict",
      f"a section no longer where the step left it stays (named) {res}")

# ---------------------------------------------------------------- time entries: change / delete
from datetime import date, timedelta  # noqa: E402
DAY = (date.today() - timedelta(days=1)).isoformat()
r = A.post(B + "/api/lists", json={"name": "Zeit Beispiel", "time_tracking": True})
TL = r.json()["id"]
r = A.post(B + "/api/time/entries", json={"list_id": TL, "start": DAY + "T09:00", "minutes": 30, "note": "Schnitt"})
check(r.ok, f"(setup) a time entry {r.status_code} {r.text[:120]}")
TE = r.json()["id"]
r = A.patch(B + f"/api/time/entries/{TE}", json={"minutes": 90, "note": "Schnitt und Ton"}, headers=LAP)
check(r.ok and r.json().get("undo_group"), f"the entry changed on the laptop: a step {r.status_code} {r.text[:120]}")
g = newest(PHONE)
check(g.get("kind") == "time_entry" and g.get("area") == "time" and "0:30" in (g.get("label") or ""), f"listed with its duration before {g}")
res = back(PHONE, g["id"])
e = A.get(B + f"/api/time/entries/{TE}").json()
check(res.get("undone") == [g["id"]] and e.get("seconds") == 1800 and e.get("note") == "Schnitt", f"taken back: 30 minutes and the old note {res} {e.get('seconds')}")
r = PHONE.post(B + f"/api/undo/{g['id']}/redo")
e = A.get(B + f"/api/time/entries/{TE}").json()
check(r.ok and e.get("seconds") == 5400, f"redo: 90 minutes again {r.status_code} {e.get('seconds')}")
check(Bo.post(B + f"/api/undo/to/{g['id']}").status_code == 404, "another person cannot take it back (404)")
r = A.delete(B + f"/api/time/entries/{TE}")
check(r.ok and r.json().get("undo_group") and A.get(B + f"/api/time/entries/{TE}").status_code == 404, f"the entry deleted: a step {r.status_code}")
g = newest(A)
check(g.get("kind") == "time_life" and "1:30" in (g.get("label") or ""), f"listed as deleted with its duration {g.get('label')}")
res = back(A, g["id"])
e = A.get(B + f"/api/time/entries/{TE}")
check(res.get("undone") == [g["id"]] and e.ok and e.json().get("seconds") == 5400 and e.json().get("note") == "Schnitt und Ton",
      f"undo of the delete: the entry is back with its id {res} {e.status_code}")
r = A.post(B + f"/api/undo/{g['id']}/redo")
check(r.ok and A.get(B + f"/api/time/entries/{TE}").status_code == 404, f"redo: deleted again {r.status_code} {r.text[:120]}")
r = A.post(B + "/api/time/entries", json={"list_id": TL, "start": DAY + "T13:00", "minutes": 20})
TE2 = r.json()["id"]
A.patch(B + f"/api/time/entries/{TE2}", json={"minutes": 25})
g = newest(A)
A.patch(B + f"/api/lists/{TL}", json={"time_tracking": False})  # the project takes no time any more
A.patch(B + f"/api/time/entries/{TE2}", json={"note": "x"})
A.delete(B + f"/api/time/entries/{TE2}")
gd = newest(A)
res = back(A, gd["id"])
check(not res.get("undone") and res.get("stayed") and A.get(B + f"/api/time/entries/{TE2}").status_code == 404,
      f"a deleted entry does not come back into a project without time tracking (409, named) {res}")

# ---------------------------------------------------------------- custom fields: create / change / delete
def fld(s, fid):
    return next((x for x in s.get(B + "/api/state").json().get("fields", []) if x["id"] == fid), None)


r = A.post(B + "/api/lists", json={"name": "Felder Beispiel"})
FLX = r.json()["id"]
r = A.post(B + f"/api/lists/{FLX}/fields", json={"name": "Phase", "type": "select",
                                                  "options": {"options": [{"id": "a1", "name": "Dreh", "color": "blue"}]}}, headers=LAP)
check(r.ok and r.json().get("undo_group"), f"a new field: a step {r.status_code} {r.text[:120]}")
FX = r.json()["id"]
g = newest(PHONE)
check(g.get("kind") == "field_life" and "Phase" in (g.get("label") or ""), f"listed with its name {g}")
res = back(PHONE, g["id"])
check(res.get("undone") == [g["id"]] and fld(A, FX) is None, f"taken back: the field is gone (field trash) {res}")
r = PHONE.post(B + f"/api/undo/{g['id']}/redo")
check(r.ok and fld(A, FX) is not None, f"redo: the field is back with its id {r.status_code} {r.text[:120]}")
r = A.patch(B + f"/api/fields/{FX}", json={"name": "Phase Neu", "pinned": 1})
check(r.ok and r.json().get("undo_group"), f"the field renamed: a step {r.status_code} {r.text[:120]}")
g = newest(A)
check(g.get("kind") == "list_field" and "Phase" in (g.get("label") or ""), f"listed {g}")
res = back(A, g["id"])
f = fld(A, FX) or {}
check(res.get("undone") == [g["id"]] and f.get("name") == "Phase" and not f.get("pinned"), f"undo: the old name, not on the rows {res} {f.get('name')}")
r = A.post(B + "/api/tasks", json={"title": "Drehtag", "list_id": FLX})
TF = r.json()["id"]
r = A.patch(B + f"/api/fields/{FX}", json={"options": {"options": [{"id": "a1", "name": "Dreh", "color": "blue"},
                                                                    {"id": "a2", "name": "Schnitt", "color": "red"}]}})
g = newest(A)
A.put(B + f"/api/lists/{FLX}/members", json={"user_id": BOB, "role": "edit"})
r = Bo.patch(B + f"/api/tasks/{TF}", json={"fields": {str(FX): "a2"}})  # someone else uses the new option
check(r.ok, f"(setup) bob sets the new option {r.status_code} {r.text[:120]}")
res = back(A, g["id"])
f = fld(A, FX) or {}
check(not res.get("undone") and res.get("stayed") and len((f.get("options") or {}).get("options") or []) == 2,
      f"an option added and used since: its removal does not go back (409, named) {res}")
before = newest(A).get("id")
r = A.patch(B + f"/api/fields/{FX}", json={"options": {"options": [{"id": "a1", "name": "Dreh", "color": "blue"}]}})
check(r.ok and not r.json().get("undo_group") and newest(A).get("id") == before,
      f"a change that removes a used option (its values go) records no step of the server {newest(A)}")
r = A.delete(B + f"/api/fields/{FX}")
check(r.ok and r.json().get("undo_group"), f"the field deleted: a step {r.status_code}")
g = newest(A)
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and fld(A, FX) is not None, f"undo of the delete: the field is back {res}")
r = A.post(B + f"/api/undo/{g['id']}/redo")
check(r.ok and fld(A, FX) is None, f"redo: deleted again {r.status_code} {r.text[:120]}")

# ---------------------------------------------------------------- rules: change / trash
def rul(s, lid, rid):
    return next((x for x in s.get(B + f"/api/lists/{lid}/rules").json().get("rules", []) if x["id"] == rid), None)


r = A.post(B + "/api/lists", json={"name": "Regeln Beispiel"})
RLX = r.json()["id"]
r = A.post(B + f"/api/lists/{RLX}/rules", json={"name": "Fertig an Alice", "trigger": {"kind": "done"},
                                                 "action": {"kind": "assign", "user_id": ALICE}})
check(r.status_code in (200, 201), f"(setup) a rule {r.status_code} {r.text[:160]}")
RU = r.json().get("id")
r = A.patch(B + f"/api/rules/{RU}", json={"name": "Fertig an Alice neu", "active": False}, headers=LAP)
check(r.ok and r.json().get("undo_group"), f"the rule changed: a step {r.status_code} {r.text[:120]}")
g = newest(PHONE)
check(g.get("kind") == "list_rule" and "Fertig an Alice" in (g.get("label") or ""), f"listed with its name {g}")
res = back(PHONE, g["id"])
x = rul(A, RLX, RU) or {}
check(res.get("undone") == [g["id"]] and x.get("name") == "Fertig an Alice" and x.get("active"), f"taken back: old name, on again {res} {x.get('name')}")
r = A.delete(B + f"/api/rules/{RU}")
check(r.ok and r.json().get("undo_group") and rul(A, RLX, RU) is None, f"the rule into the trash: a step {r.status_code}")
g = newest(A)
res = back(A, g["id"])
check(res.get("undone") == [g["id"]] and rul(A, RLX, RU) is not None, f"undo: the rule is back from the trash {res}")
r = A.post(B + f"/api/undo/{g['id']}/redo")
check(r.ok and rul(A, RLX, RU) is None, f"redo: in the trash again {r.status_code} {r.text[:120]}")

# freelancer-matrix
r = Fr.post(B + "/api/lists", json={"name": "Frida Projekt", "color": "#3366cc"})
FL = r.json()["id"]
r = Fr.patch(B + f"/api/lists/{FL}", json={"color": "#22aa22"})
g = newest(Fr)
check(r.ok and g.get("kind") == "listset", f"a person without an organisation: her colour change is a step {g}")
res = back(Fr, g["id"])
check(res.get("undone") == [g["id"]] and lrow(Fr, FL).get("color") == "#3366cc", f"... and goes back from the list {res}")
r = Fr.post(B + "/api/sections", json={"list_id": FL, "name": "Frida Abschnitt"})
FS = r.json()["id"]
g = newest(Fr)
res = back(Fr, g["id"])
check(g.get("kind") == "section_life" and res.get("undone") == [g["id"]] and FS not in secs(Fr, FL), f"... and her new section goes back {res}")
r = Fr.post(B + f"/api/lists/{FL}/fields", json={"name": "Frida Feld", "type": "text"})
FFX = r.json().get("id")
g = newest(Fr)
res = back(Fr, g["id"])
check(g.get("kind") == "field_life" and res.get("undone") == [g["id"]] and fld(Fr, FFX) is None, f"... and her new field goes back {res}")
Fr.patch(B + f"/api/lists/{FL}", json={"time_tracking": True})
r = Fr.post(B + "/api/time/entries", json={"list_id": FL, "start": DAY + "T10:00", "minutes": 15})
FT = r.json()["id"]
Fr.delete(B + f"/api/time/entries/{FT}")
g = newest(Fr)
res = back(Fr, g["id"])
check(g.get("kind") == "time_life" and res.get("undone") == [g["id"]] and Fr.get(B + f"/api/time/entries/{FT}").ok, f"... and her deleted time entry comes back {res}")

sys.exit(done("p2809_a_undo"))
