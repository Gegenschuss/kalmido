#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.585.0 Teil D. Invented names only (example.com); the person is one without an organisation (freelancer-matrix: tasks).
#4350: an account import (source "Kalmido", the move) can be undone for 30 days, the task imports keep 24 hours
 - an account import of 29 days ago: the list of imports offers the undo until day 30, GET /api/imports/<id>/undo-plan names
   the last moment and what goes for good (an unchanged filter) and into the trash (an unchanged task) and changes nothing;
   the undo itself works (the filter is gone, the task in the trash)
 - an account import of 31 days ago: plan and undo 409 ("30 days"), the list offers no undo
 - a task import of 23 hours ago can be undone, one of 25 hours ago not (409, "24 hours")
 - the plan of somebody else's import: 404
#4795: the core's history (obj_history) also for a folder move in the knowledge base and for a new lead (freelancer-matrix: wiki, office)
 - POST /api/wiki/move: every page of the folder gets its rename entry, the versions answer carries it (from / to)
 - a lead made in the pipeline, by the CSV import and by the deal route: a "create" entry, GET .../history shows it
usage: p2585_d_api_test.py <datadir>"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else kt.DATA


def one(sql, args=()):
    r = kt.dbx(sql, args)
    return r[0][0] if r else None


def ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat(timespec="seconds")


def imp_row(uid, source, created, at):
    return one("INSERT INTO imports(user_id, source, file_name, created, report, created_at) VALUES(?,?,?,?,?,?) RETURNING id",
               (uid, source, "datei.zip", json.dumps(created), "{}", at))


def listed(s, iid):
    return next((x for x in s.get(B + "/api/imports").json()["imports"] if x["id"] == iid), None)


kt.fresh(prefix="P2585D")
A = kt.setup()
FID, Fr = freelancer(B, A)
GID, Gi = freelancer(B, A, "gina")

# ---------------------------------------------------------------- #4350: an account import, 29 days ago
LID = Fr.post(B + "/api/lists", json={"name": "Umzugsliste"}).json()["id"]
TID = Fr.post(B + "/api/tasks", json={"title": "Umzugsaufgabe", "list_id": LID}).json()["id"]
check(Fr.post(B + "/api/filters", json={"name": "Umzugsfilter", "rules": {"op": "and"}}).status_code in (200, 201), "a filter")
FLT = one("SELECT id FROM filters WHERE name=? AND user_id=?", ("Umzugsfilter", FID))
OLD = ago(days=29, hours=1)
kt.dbx("UPDATE tasks SET tt_id='kalmido:t1', created_at=?, updated_at=? WHERE id=?", (OLD, OLD, TID))
kt.dbx("UPDATE filters SET created_at=? WHERE id=?", (OLD, FLT))
IMP = imp_row(FID, "Kalmido", {"tasks": [TID], "filters": [FLT]}, ago(days=29))
x = listed(Fr, IMP)
until = datetime.fromisoformat((x or {}).get("undo_until", "2000-01-01T00:00:00+00:00").replace("Z", "+00:00"))
check(x and x["can_undo"] and timedelta(hours=20) < until - datetime.now(timezone.utc) < timedelta(days=1, hours=1),
      f"#4350: the account import of 29 days ago can still be undone, until day 30 {x}")
r = Fr.get(B + f"/api/imports/{IMP}/undo-plan")
p = r.json() if r.ok else {}
check(r.ok and p.get("undo_until") == x["undo_until"], f"#4350: the plan names the last moment {r.status_code} {r.text[:200]}")
check({"what": "Filters", "count": 1} in (p.get("for_good") or []) and p.get("trash_tasks") == 1 and p.get("kept_tasks") == 0,
      f"#4350: the plan: the filter goes for good, the task into the trash {p}")
check(one("SELECT 1 FROM filters WHERE id=?", (FLT,)) and not one("SELECT deleted_at FROM tasks WHERE id=?", (TID,)),
      "#4350: the plan changes nothing")
r = Gi.get(B + f"/api/imports/{IMP}/undo-plan")
check(r.status_code == 404, f"#4350: the plan of somebody else's import: 404 ({r.status_code})")
r = Fr.post(B + f"/api/imports/{IMP}/undo")
check(r.ok and r.json().get("tasks") == 1, f"#4350: the undo on day 29 works {r.status_code} {r.text[:200]}")
check(not one("SELECT 1 FROM filters WHERE id=?", (FLT,)) and one("SELECT deleted_at FROM tasks WHERE id=?", (TID,)),
      "#4350: the filter is gone, the task in the trash")

# ---------------------------------------------------------------- #4350: an account import, 31 days ago
IMP2 = imp_row(FID, "Kalmido", {"tasks": []}, ago(days=31))
x = listed(Fr, IMP2)
check(x and not x["can_undo"], f"#4350: the account import of 31 days ago offers no undo {x}")
r = Fr.get(B + f"/api/imports/{IMP2}/undo-plan")
check(r.status_code == 409 and "30 days" in r.text, f"#4350: its plan 409 {r.status_code} {r.text[:200]}")
r = Fr.post(B + f"/api/imports/{IMP2}/undo")
check(r.status_code == 409 and "30 days" in r.text and not one("SELECT undone_at FROM imports WHERE id=?", (IMP2,)),
      f"#4350: its undo 409, nothing undone {r.status_code} {r.text[:200]}")

# ---------------------------------------------------------------- #4350: task imports stay at 24 hours
IMP3 = imp_row(FID, "todoist", {"tasks": [], "lists": [], "sections": []}, ago(hours=23))
IMP4 = imp_row(FID, "todoist", {"tasks": [], "lists": [], "sections": []}, ago(hours=25))
check((listed(Fr, IMP3) or {}).get("can_undo") and not (listed(Fr, IMP4) or {"can_undo": True})["can_undo"],
      "#4350: the task import offers its undo for 24 hours only")
r = Fr.post(B + f"/api/imports/{IMP4}/undo")
check(r.status_code == 409 and "24 hours" in r.text, f"#4350: a task import of 25 hours ago: 409 {r.status_code} {r.text[:200]}")
r = Fr.post(B + f"/api/imports/{IMP3}/undo")
check(r.ok, f"#4350: a task import of 23 hours ago can be undone {r.status_code} {r.text[:200]}")
r = Fr.get(B + f"/api/imports/{IMP3}/undo-plan")
check(r.status_code == 404, f"#4350: a task import has no undo plan (404) {r.status_code}")

# ---------------------------------------------------------------- #4795: a folder move in the knowledge base
PIDS = {}
for n in ("Ordner/Seite A", "Ordner/Unter/Seite B"):
    r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": n, "body": "Text"})
    check(r.status_code == 201, f"#4795 setup: page {n} {r.text[:200]}")
    PIDS[n] = r.json()["id"]
r = Fr.post(B + "/api/wiki/move", json={"space": "private", "from": "Ordner", "to": "Neu"})
check(r.ok and len(r.json().get("moved") or []) == 2, f"#4795: the folder moved {r.status_code} {r.text[:200]}")
for n, pid in PIDS.items():
    to = "Neu" + n[len("Ordner"):]
    rn = Fr.get(B + f"/api/wiki/pages/{pid}/versions").json().get("renames") or []
    check(len(rn) == 1 and rn[0]["from"] == n and rn[0]["to"] == to, f"#4795: the rename of {n} in its history {rn}")
    h = kt.dbx("SELECT user_id, action FROM obj_history WHERE kind='wiki' AND ref_id=?", (pid,))
    check([tuple(x) for x in h] == [(FID, "update")], f"#4795: one obj_history entry of the person for {n} {h}")

# ---------------------------------------------------------------- #4795: new leads start their history
Fr.get(B + "/api/office/docs?kind=invoice")  # the personal office exists from its first use


def created(did, what):
    r = Fr.get(B + f"/api/office/deals/{did}/history")
    items = r.json().get("items") if r.ok else None
    check(r.ok and [x["action"] for x in items] == ["create"] and items[0]["user_id"] == FID and "title" in items[0]["fields"],
          f"#4795: {what}: a create entry in its history {r.status_code} {r.text[:300]}")


r = Fr.post(B + "/api/office/deals", json={"title": "Lead Beispiel", "stage": "lead", "contact": "Erika Beispiel"})
check(r.status_code == 201, f"#4795 setup: a lead {r.status_code} {r.text[:200]}")
LD = r.json().get("id")
created(LD, "a lead of the pipeline")
r = Fr.patch(B + f"/api/office/deals/{LD}", json={"note": "Anrufen", "expect_updated_at": r.json()["updated_at"]})
check(r.ok, f"#4795 setup: the lead changed {r.status_code} {r.text[:200]}")
h = Fr.get(B + f"/api/office/deals/{LD}/history").json()["items"]
check([x["action"] for x in h] == ["update", "create"], f"#4795: the change joins the create entry, it does not merge into it {h}")
r = Fr.post(B + "/api/office/leads/import", json={"text": "Name;E-mail\nMax Muster;max@example.com\n", "commit": True})
check(r.status_code == 201 and len(r.json().get("ids") or []) == 1, f"#4795 setup: a lead imported {r.status_code} {r.text[:200]}")
created((r.json().get("ids") or [0])[0], "an imported lead")

sys.exit(kt.done("p2585_d"))
