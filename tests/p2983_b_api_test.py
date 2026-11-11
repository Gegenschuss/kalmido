#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.983.0 B (#5589): the history rows of a deleted time entry and the watchdog's undo run (core/undogroups.py undo_prune ->
ug_drop_orphans), as a person without an organisation. Invented names and notes only.
 - while the entry's "time_life" undo part can bring it back, the run keeps its history (review finding of the earlier build:
   ug_drop_orphans took it at once, against the rule of collab/liste2eguard.py le2b_hist_gone; UG_LIFE now)
 - once that part ran out (UNDO_KEEP_D), the same run takes the history row -- every hour, no project lock needed
 - a living entry keeps its history
usage: p2983_b_api_test.py <datadir>      (KMT_NOSTART=1 / P2983B_NOSTART=1: a running server)"""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import dbx as dbxm
from freelancer_fixture import freelancer
from kt import B, CT, DATA, check, dbx, done, fresh, setup

fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="P2983B")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, F = freelancer(B, A)


def write(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def prune():
    """One watchdog undo run in the app container (system context, forced past its hourly pace)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import os; os.environ['TASKS_WATCHDOG']='0'\nimport app\n"
                          "from kalmido.core.undogroups import undo_prune\nc = app.connect()\nundo_prune(c, force=True)\nprint('OK')"],
                         capture_output=True, text=True)
    return out.returncode == 0 and "OK" in out.stdout, out.stderr.strip()[-400:]


def hist(eid):
    return bool(dbx("SELECT 1 FROM obj_history WHERE kind='time_entry' AND ref_id=?", (eid,)))


def life(eid):
    return bool(dbx("SELECT 1 FROM obj_undo WHERE kind='time_life' AND ref_id=?", (eid,)))


L = F.post(B + "/api/lists", json={"name": "Garden studio", "kind": "project"}).json()["id"]
r = F.post(B + "/api/time/entries", json={"list_id": L, "start": (datetime.now() - timedelta(hours=5)).isoformat(timespec="seconds"),
                                          "minutes": 25, "note": "Kickoff notes"})
check(r.ok, f"(setup) a time entry with a note {r.status_code} {r.text[:200]}")
EG = r.json()["id"]
r = F.patch(B + f"/api/time/entries/{EG}", json={"note": "Kickoff notes, revised"})
GG = r.json().get("undo_group") if r.ok else None
check(bool(GG) and F.post(B + f"/api/undo/to/{GG}").ok and F.delete(B + f"/api/time/entries/{EG}").ok and hist(EG) and life(EG),
      f"(setup) changed, undone, deleted: its history row and its time_life part are there {GG}")
r = F.post(B + "/api/time/entries", json={"list_id": L, "start": (datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds"),
                                          "minutes": 10, "note": "Standup"})
EL = r.json()["id"]
GL = F.patch(B + f"/api/time/entries/{EL}", json={"note": "Standup, short"}).json().get("undo_group")
check(bool(GL) and F.post(B + f"/api/undo/to/{GL}").ok and hist(EL), f"(setup) a living entry with a history row {GL}")

ok, err = prune()
check(ok and life(EG), f"(setup) the undo run leaves the young time_life part {err}")
check(hist(EG), "#5589: while its time_life part can bring the entry back, the undo run keeps its history")
check(hist(EL), "#5589: the living entry keeps its history")

old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(timespec="seconds")
write("UPDATE undo_groups SET created_at=? WHERE id IN (SELECT group_id FROM obj_undo WHERE kind='time_life' AND ref_id=?)", (old, EG))
write("UPDATE obj_undo SET created_at=? WHERE kind='time_life' AND ref_id=?", (old, EG))
ok, err = prune()
check(ok and not life(EG), f"(setup) the undo run took the time_life part past its age {err}")
check(not hist(EG), "#5589: with it the history row of the deleted entry goes (the watchdog's run, no lock needed)")
check(hist(EL), "#5589: the living entry still keeps its history")

sys.exit(done("p2983_b_api"))
