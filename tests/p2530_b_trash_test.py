#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.530.0 B (#4315): habits, "Delete all times of this project" and the sample project no longer go for good at once.
Own container (start.sh). Invented accounts only (example.com); every step as the person without an organisation (freelancer
fixture). freelancer-matrix: time, tasks
 - DELETE /api/habits/<id> = the trash: gone from the state, the export and API v1 (list, PATCH, check-in, stats 404), its logs
   stay; the state names it in habits_trash; POST /api/habits/<id>/restore brings it back with its ticks; a second restore 404;
   the trash run only counts while the switch is off, with KALMIDO_PURGE_TRASH=1 it deletes the habit with its logs once the
   trash period is over
 - an agent's DELETE /api/v1/habits/<id> waits for an approval (202, the habit stays)
 - "Delete all times": the delete keeps a copy on the server (wipe); the preview names it (undo); POST time/restore {wipe}
   brings the entries back without the answer's copy (the tab was closed), once (then 404); a restore from the answer's copy
   {entries} (an older window) uses the server's copy up; the trash run deletes an old copy
 - removing the sample project: its tasks go into the trash (none deleted for good), the project into the projects' trash
   (restorable with its tasks); the sample's time entry stays when its task was changed, else it goes
usage: p2530_b_trash_test.py <datadir>      (P2530B_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

from freelancer_fixture import freelancer
from kt import B, CT, check, dbx, done, fresh, setup

V = B + "/api/v1"
fresh(prefix="P2530B")
A = setup()
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
GID, G = freelancer(B, A, "gerda")


def box(code, env=()):
    """Python inside the app container (a fresh process)."""
    cmd = ["docker", "exec"]
    for e in env:
        cmd += ["-e", e]
    out = subprocess.run(cmd + [CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.commit()\nc.close()"],
                         capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def run_purge(switch):
    return box("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))", ("KALMIDO_PURGE_TRASH=1",) if switch else ())


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


def state(s):
    return s.get(B + "/api/state").json()


# ================================================================== habits: the trash
r = F.post(B + "/api/habits", json={"name": "Stretch", "goal": 1})
HB = r.json()["id"]
day = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
check(F.post(B + f"/api/habits/{HB}/log", json={"day": day, "count": 1}).ok, "habit: a tick")
r = F.delete(B + f"/api/habits/{HB}")
check(r.ok and r.json().get("trashed") is True, f"habit: DELETE answers trashed {r.status_code} {r.text[:120]}")
row = dbx("SELECT deleted_at FROM habits WHERE id=?", (HB,))
check(row and row[0][0], "habit: the row stays with deleted_at")
check(dbx("SELECT count FROM habit_logs WHERE habit_id=?", (HB,)) == [(1,)], "habit: its logs stay")
st = state(F)
check(all(h["id"] != HB for h in st["habits"]) and [h["id"] for h in st["habits_trash"]] == [HB],
      f"habit: gone from the state, named in habits_trash {st.get('habits_trash')}")
check(F.patch(B + f"/api/habits/{HB}", json={"name": "x"}).status_code == 404, "habit in the trash: PATCH 404")
check(F.post(B + f"/api/habits/{HB}/log", json={"day": day, "count": 2}).status_code == 404, "habit in the trash: tick 404")
check(F.delete(B + f"/api/habits/{HB}").status_code == 404, "habit in the trash: a second DELETE 404")
r = F.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "tasks:write", "delete"]})
TH = {"Authorization": "Bearer " + r.json()["token"]}
check(all(h["id"] != HB for h in requests.get(V + "/habits", headers=TH).json()["data"]), "habit in the trash: not in API v1 /habits")
check(requests.get(V + f"/habits/{HB}/stats", headers=TH).status_code == 404, "habit in the trash: v1 stats 404")
check(requests.post(V + f"/habits/{HB}/checkin", headers=TH, json={}).status_code == 404, "habit in the trash: v1 check-in 404")
check(G.post(B + f"/api/habits/{HB}/restore").status_code == 404, "another person cannot restore it (404)")
r = F.post(B + f"/api/habits/{HB}/restore")
check(r.ok, f"habit: restore {r.status_code} {r.text[:120]}")
st = state(F)
h = next((x for x in st["habits"] if x["id"] == HB), None)
check(h is not None and h["logs"].get(day) == 1 and not st["habits_trash"], f"habit: back with its tick {h}")
check(F.post(B + f"/api/habits/{HB}/restore").status_code == 404, "habit: a second restore 404 (not in the trash)")
# the trash run: counts while off, deletes for good when on and older than the period
F.delete(B + f"/api/habits/{HB}")
dbx("UPDATE habits SET deleted_at=? WHERE id=?", (ago(400), HB))
out = run_purge(False)
check(dbx("SELECT 1 FROM habits WHERE id=?", (HB,)) == [(1,)] and "'habits': 1" in out, f"trash run (switch off): counts, keeps {out[-300:]}")
out = run_purge(True)
check(not dbx("SELECT 1 FROM habits WHERE id=?", (HB,)) and not dbx("SELECT 1 FROM habit_logs WHERE habit_id=?", (HB,)),
      f"trash run (switch on): the habit and its logs are gone {out[-300:]}")

# an agent's delete waits for a person
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "scopes": ["read", "tasks:write", "delete"]})
check(r.status_code == 201, f"a personal agent {r.status_code} {r.text[:200]}")
AH = {"Authorization": "Bearer " + r.json()["token"]}
r = requests.post(V + "/habits", headers=AH, json={"name": "Agent habit"})
AHB = r.json().get("id")
check(r.status_code == 201, f"agent: own habit {r.status_code} {r.text[:120]}")
r = requests.delete(V + f"/habits/{AHB}", headers=AH)
check(r.status_code == 202 and r.json().get("approval_required"), f"agent: DELETE habit waits for an approval {r.status_code} {r.text[:200]}")
check(dbx("SELECT deleted_at FROM habits WHERE id=?", (AHB,)) == [(None,)], "agent: the habit stays until a person approves")
# a person's token deletes at once (into the trash)
r = F.post(B + "/api/habits", json={"name": "Read"})
H2 = r.json()["id"]
HB2 = F.post(B + "/api/habits", json={"name": "Walk"}).json()["id"]
check(requests.delete(V + f"/habits/{H2}", headers=TH).status_code == 204 and dbx("SELECT deleted_at IS NOT NULL FROM habits WHERE id=?", (H2,)) == [(True,)],
      "a person's token: DELETE 204, into the trash")
r = F.get(B + "/api/export.json")
check(r.ok and all(x.get("id") != H2 for x in r.json().get("habits", [])) and any(x.get("id") == HB2 for x in r.json().get("habits", [])),
      f"my data export leaves the trash out {r.status_code}")

# ================================================================== "Delete all times": the copy on the server
L = F.post(B + "/api/lists", json={"name": "Frida film", "kind": "project"}).json()["id"]
T = F.post(B + "/api/tasks", json={"title": "Edit", "list_id": L}).json()["id"]
for i in range(3):
    st0 = (datetime.now(timezone.utc) - timedelta(days=3, hours=i)).replace(microsecond=0)
    r = F.post(B + "/api/time/entries", json={"task_id": T, "start": st0.isoformat(), "end": (st0 + timedelta(minutes=30)).isoformat(), "note": f"n{i}"})
    check(r.ok, f"time: entry {i} {r.status_code} {r.text[:120]}")
n0 = dbx("SELECT COUNT(*) FROM time_entries WHERE list_id=?", (L,))[0][0]
check(n0 == 3, f"time: three entries {n0}")
r = F.post(B + f"/api/lists/{L}/time/delete-all", json={"confirm": "Frida film"})
j = r.json()
check(r.ok and j["deleted"] == 3 and isinstance(j.get("wipe"), int), f"time: deleted, the answer names the copy (wipe) {r.text[:200]}")
W = j.get("wipe")
check(dbx("SELECT COUNT(*) FROM time_entries WHERE list_id=?", (L,))[0][0] == 0, "time: the entries are gone from the list")
check(dbx("SELECT n, user_id FROM time_wipes WHERE id=?", (W,)) == [(3, FID)], "time: the copy on the server (3 entries)")
pv = F.get(B + f"/api/lists/{L}/time/delete-all").json()
check(pv["count"] == 0 and (pv.get("undo") or {}).get("wipe") == W and pv["undo"]["count"] == 3, f"time: the preview names the copy {pv}")
check(G.post(B + f"/api/lists/{L}/time/restore", json={"wipe": W}).status_code in (403, 404), "time: another person cannot use the copy")
# the tab was closed: no answer copy, only the wipe id
r = F.post(B + f"/api/lists/{L}/time/restore", json={"wipe": W})
check(r.ok and r.json()["restored"] == 3, f"time: restore from the server's copy {r.status_code} {r.text[:150]}")
check(sorted(x[0] for x in dbx("SELECT note FROM time_entries WHERE list_id=?", (L,))) == ["n0", "n1", "n2"], "time: the same three entries are back")
check(not dbx("SELECT 1 FROM time_wipes WHERE id=?", (W,)), "time: the used copy is gone")
check(F.post(B + f"/api/lists/{L}/time/restore", json={"wipe": W}).status_code == 404, "time: the copy works once (404)")
# an older window restores from the answer's copy: the server's copy of that delete is used up with it (no second way back)
r = F.post(B + f"/api/lists/{L}/time/delete-all", json={"confirm": "Frida film"})
W1, back1 = r.json()["wipe"], r.json()["entries"]
r = F.post(B + f"/api/lists/{L}/time/restore", json={"entries": back1})
check(r.ok and r.json()["restored"] == 3 and not dbx("SELECT 1 FROM time_wipes WHERE id=?", (W1,)),
      f"time: the answer's copy restores and uses the server's copy up {r.text[:120]}")
check(F.post(B + f"/api/lists/{L}/time/restore", json={"wipe": W1}).status_code == 404
      and dbx("SELECT COUNT(*) FROM time_entries WHERE list_id=?", (L,))[0][0] == 3, "time: no entry comes back twice")
check(F.post(B + f"/api/lists/{L}/time/restore", json={"wipe": "x"}).status_code == 400, "time: a wipe that is no number 400")
# the trash run deletes an old copy
r = F.post(B + f"/api/lists/{L}/time/delete-all", json={"confirm": "Frida film"})
W2 = r.json()["wipe"]
dbx("UPDATE time_wipes SET deleted_at=? WHERE id=?", (ago(400), W2))
run_purge(True)
check(not dbx("SELECT 1 FROM time_wipes WHERE id=?", (W2,)), "time: the trash run deletes the old copy")

# ================================================================== the sample project
def sample(s, uid, edit):
    r = s.post(B + "/api/sample", json={})
    check(r.ok and r.json().get("created"), f"sample: created {r.status_code} {r.text[:120]}")
    tids = [x[0] for x in dbx("SELECT item_id FROM sample_items WHERE user_id=? AND kind='task'", (uid,))]
    lids = [x[0] for x in dbx("SELECT item_id FROM sample_items WHERE user_id=? AND kind='list'", (uid,))]
    te = [x[0] for x in dbx("SELECT item_id FROM sample_items WHERE user_id=? AND kind='time'", (uid,))]
    if edit:  # the person changes the task the sample's time entry belongs to
        tt = dbx("SELECT task_id FROM time_entries WHERE id=?", (te[0],))[0][0]
        dbx("UPDATE tasks SET updated_at=? WHERE id=?", ((datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(timespec="seconds"), tt))
    r = s.delete(B + "/api/sample")
    check(r.ok and r.json()["tasks"] == len(tids), f"sample: removed {r.status_code} {r.text[:150]}")
    left = dbx("SELECT COUNT(*), COUNT(deleted_at) FROM tasks WHERE id = ANY(CAST(? AS BIGINT[]))", ("{" + ",".join(map(str, tids)) + "}",))[0]
    check(left[0] == len(tids) and left[1] == len(tids), f"sample: every task is in the trash, none gone for good {left} of {len(tids)}")
    check(all(dbx("SELECT deleted_at IS NOT NULL FROM lists WHERE id=?", (x,)) == [(True,)] for x in lids), "sample: its projects are in the projects' trash")
    return tids, lids, te


tids, lids, te = sample(F, FID, edit=True)
check(dbx("SELECT COUNT(*) FROM time_entries WHERE id=?", (te[0],)) == [(1,)], "sample: the time entry of a changed task stays")
r = F.post(B + f"/api/trash/lists/{lids[0]}/restore")
check(r.ok and dbx("SELECT COUNT(*) FROM tasks WHERE list_id=? AND deleted_at IS NULL", (lids[0],))[0][0] > 0,
      f"sample: the project comes back from the projects' trash with its tasks {r.status_code} {r.text[:120]}")
tids, lids, te = sample(G, GID, edit=False)
check(not dbx("SELECT 1 FROM time_entries WHERE id=?", (te[0],)), "sample: the untouched sample's time entry goes")

sys.exit(done("p2530_b_trash"))
