#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.936.0 part C (#5582): the rest of the review of 2.900 (project lock, #5550/#5551) -- undo copies of time entries.
Invented names only. For alice (organisation admin) and for a person without an organisation:
 a) a time entry moved by a save (PATCH /api/time/entries/<id>) into a locked project: its older undo steps go (their copies
    held the note of before); the save itself works and leaves the entry in the locked project
 b) a deleted entry taken back, then its project locked (by an older version: the note emptied, the step missed): redo
    deletes it again (no 409 because of the emptied note) and its copy keeps no note
The lock is set in the database (e2e='on'), as p264a_b_api does for the steps a scrub missed.
freelancer-matrix: time (a person without an organisation: her entry moved into her locked project, her redo of a deleted entry there)
usage: p2936_c_lock_rest_test.py <datadir>"""
import os
import sys
from datetime import date, timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from kt import B, check, done  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(prefix="P2936C")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": "collab,comments,time", "tour": "done"})
FID, Fr = freelancer(B, A)
DAY = (date.today() - timedelta(days=1)).isoformat()


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"), timeout=10)
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def copies(word):
    """Undo parts whose copy (before / after) still holds word."""
    return kt.dbx("SELECT id, kind FROM obj_undo WHERE snap LIKE ? OR COALESCE(redo, '') LIKE ?", (f"%{word}%", f"%{word}%"))


def plist(s, name):
    r = s.post(B + "/api/lists", json={"name": name, "time_tracking": True})
    check(r.ok, f"(setup) project {name} {r.status_code} {r.text[:160]}")
    return r.json()["id"]


def run(s, who):
    mk = "Zqk" + who
    # ---- a) moved into a locked project by a save
    lo, lk = plist(s, f"{who} Open"), plist(s, f"{who} Locked")
    r = s.post(B + "/api/time/entries", json={"list_id": lo, "start": DAY + "T09:00", "minutes": 30, "note": mk + "First"})
    check(r.ok, f"(setup) {who}: a time entry with a note {r.status_code} {r.text[:160]}")
    te = r.json()["id"]
    r = s.patch(B + f"/api/time/entries/{te}", json={"minutes": 45, "note": mk + "Second"})
    check(r.ok and r.json().get("undo_group"), f"(setup) {who}: a change is an undo step {r.status_code} {r.text[:160]}")
    check(bool(copies(mk + "First")), f"(setup) {who}: the step's copy holds the first note")
    dbw("UPDATE lists SET e2e='on' WHERE id=?", (lk,))
    r = s.patch(B + f"/api/time/entries/{te}", json={"list_id": lk, "note": ""})
    e = s.get(B + f"/api/time/entries/{te}").json()
    check(r.ok and e.get("list_id") == lk and (e.get("note") or "") == "",
          f"a) {who}: the entry moves into the locked project without its note {r.status_code} {r.text[:200]}")
    left = copies(mk + "First")
    check(not left, f"#5582 a) {who}: its older undo step (the note of before in the copy) is gone {left}")
    dbw("UPDATE lists SET e2e=NULL WHERE id=?", (lk,))

    # ---- b) redo of a deleted entry whose project was locked since
    lb = plist(s, f"{who} Later")
    r = s.post(B + "/api/time/entries", json={"list_id": lb, "start": DAY + "T13:00", "minutes": 20, "note": mk + "Gone"})
    te2 = r.json()["id"]
    r = s.delete(B + f"/api/time/entries/{te2}")
    g = r.json().get("undo_group") if r.ok else None
    check(bool(g), f"(setup) {who}: the delete is a step {r.status_code} {r.text[:160]}")
    r = s.post(B + f"/api/undo/to/{g}")
    check(r.ok and g in (r.json().get("undone") or []) and s.get(B + f"/api/time/entries/{te2}").ok,
          f"(setup) {who}: undo brings the entry back {r.status_code} {r.text[:200]}")
    dbw("UPDATE lists SET e2e='on' WHERE id=?", (lb,))
    dbw("UPDATE time_entries SET note='' WHERE id=?", (te2,))  # as le2b_scrub_free did at the lock (the step missed)
    r = s.post(B + f"/api/undo/{g}/redo")
    check(r.ok and r.json().get("redone") == 1 and s.get(B + f"/api/time/entries/{te2}").status_code == 404,
          f"#5582 b) {who}: redo deletes the entry in the locked project again {r.status_code} {r.text[:200]}")
    left = copies(mk + "Gone")
    check(not left, f"#5582 b) {who}: the step's copy keeps no note {left}")
    dbw("UPDATE lists SET e2e=NULL WHERE id=?", (lb,))


run(A, "Alice")
run(Fr, "Frida")
# 2.936.0: the index came with #5564 (migrations.d/5564_a.py, obj_undo_ref), #5582 needs no own one
check(bool(kt.dbx("SELECT 1 FROM pg_indexes WHERE indexname='obj_undo_ref'")), "#5582 c) the index obj_undo(kind, ref_id) exists (#5564)")

sys.exit(done("p2936_c_lock_rest"))
