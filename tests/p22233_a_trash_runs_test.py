#!/usr/bin/env python3
"""2.223.3 A API tests (#2879, #2877): the trash run covers absences, disposition bookings, scheduling polls (with their
votes), appointment types and file requests, and the trash answers say whether the run deletes. Own container (start.sh,
mode workspaces). Invented accounts only (example.com); the person without an organisation (freelancer fixture, personal
area) owns every row.
 - #2879: a row deleted before the period + KALMIDO_PURGE_TRASH=1 -> gone (a poll's votes and options with it); a row deleted
   inside the period stays; with the switch off the due rows stay and are counted
 - #2877: GET /api/tasks?scope=trash and the other trash lists carry purge_on false while the switch is off
freelancer-matrix: retention
usage: p22233_a_trash_runs_test.py <datadir>      (P22233A_NOSTART=1: a running server on KALMIDO_TEST_PORT)
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # an UPDATE without rows to read
            return []
    finally:
        c.close()


def box(code, env=()):
    """Runs python code inside the app container (a fresh process: the run state of the watchdog starts empty)."""
    cmd = ["docker", "exec"]
    for e in env:
        cmd += ["-e", e]
    out = subprocess.run(cmd + [CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.commit()\nc.close()"],
                         capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def ago(hours=0, days=0):
    return (datetime.now(timezone.utc) - timedelta(hours=hours, days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


if os.environ.get("P22233A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
FID, Fr = freelancer(B, A)
Fr.get(B + "/api/office/docs?kind=invoice")  # the personal area exists from its first use
PO = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
NOW, OLD, NEW = ago(), ago(days=40), ago(days=2)

# ================================================================== #2877: the trash answers say whether the run deletes
r = Fr.get(B + "/api/tasks?scope=trash")
check(r.ok and r.json().get("purge_on") is False and r.json().get("days") == 30,
      f"#2877 task trash: purge_on false while the switch is off {r.text[:200]}")
r = Fr.get(B + "/api/files?space=trash")
check(r.ok and r.json().get("purge_on") is False, f"#2877 file trash: purge_on false {r.text[:200]}")
r = A.get(B + "/api/admin/retention")
check(r.ok and r.json()["kinds"]["trash"]["on"] is False and r.json().get("general_switch") == "KALMIDO_RETENTION_PURGE",
      f"#2877 admin: the trash kind counts only, the switch is named {r.text[:200]}")

# ================================================================== #2879: rows of the five areas, one due and one young each
r = Fr.post(B + "/api/team/absences", json={"kind": "sick", "start_date": "2026-11-02", "note": "test note"})
check(r.status_code == 201, f"setup: a sick note in the personal area {r.text[:200]}")
AB_OLD = r.json().get("id") or r.json().get("absence", {}).get("id")
check(Fr.delete(B + f"/api/team/absences/{AB_OLD}").ok, "setup: the sick note goes to the trash")
sql("UPDATE hub_absences SET deleted_at=? WHERE id=?", (OLD, AB_OLD))
AB_NEW = sql("INSERT INTO hub_absences(org_id, user_id, kind, start_date, end_date, created_at, deleted_at) VALUES(?,?,?,?,?,?,?) RETURNING id",
             (PO, FID, "vacation", "2026-11-09", "2026-11-10", NOW, NEW))[0][0]
BK = {}
for k, d in (("old", OLD), ("new", NEW)):
    BK[k] = sql("INSERT INTO hub_bookings(org_id, title, start, \"end\", resource_kind, resource_id, created_at, updated_at, deleted_at) "
                "VALUES(?,?,?,?,?,?,?,?,?) RETURNING id", (PO, "Shoot " + k, "2026-11-17", "2026-11-17", "user", FID, NOW, NOW, d))[0][0]
PL = {}
for k, d in (("old", OLD), ("new", NEW)):
    PL[k] = sql("INSERT INTO sched_polls(user_id, org_id, title, token, token_hash, created_at, updated_at, deleted_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",
                (FID, PO, "Poll " + k, "tok-" + k, "hash-p22233a-" + k, NOW, NOW, d))[0][0]
    sql("INSERT INTO sched_poll_options(poll_id, start, \"end\", pos) VALUES(?,?,?,0)", (PL[k], "2026-11-20T10:00", "2026-11-20T11:00"))
    sql("INSERT INTO sched_poll_votes(poll_id, name, email, edit_hash, ip_hash, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        (PL[k], "Guest " + k, k + "@example.com", "eh-" + k, "ip-" + k, NOW, NOW))
AT = {}
for k, d in (("old", OLD), ("new", NEW)):
    AT[k] = sql("INSERT INTO appt_types(user_id, name, created_at, updated_at, deleted_at) VALUES(?,?,?,?,?) RETURNING id",
                (FID, "Call " + k, NOW, NOW, d))[0][0]
BOOK = sql("INSERT INTO appt_bookings(user_id, type_id, start, \"end\", name, email, created_at) VALUES(?,?,?,?,?,?,?) RETURNING id",
           (FID, AT["old"], "2026-11-21T10:00Z", "2026-11-21T10:30Z", "Guest", "guest@example.com", NOW))[0][0]
FOLDER = sql("INSERT INTO fs_nodes(parent_id, kind, name, owner_id, org_id, created_by, created_at, updated_at) VALUES(NULL,'folder',?,?,?,?,?,?) RETURNING id",
             ("Requests p22233a", FID, PO, FID, NOW, NOW))[0][0]
FR = {}
for k, d in (("old", OLD), ("new", NEW)):
    FR[k] = sql("INSERT INTO fs_upload_requests(node_id, org_id, created_by, token, token_hash, title, expires_at, created_at, deleted_at) "
                "VALUES(?,?,?,?,?,?,?,?,?) RETURNING id", (FOLDER, PO, FID, "tok-" + k, "hash-p22233a-fr-" + k, "Docs " + k, NOW, NOW, d))[0][0]

AREAS = (("absences", "hub_absences", AB_OLD, AB_NEW), ("bookings", "hub_bookings", BK["old"], BK["new"]),
         ("polls", "sched_polls", PL["old"], PL["new"]), ("appt_types", "appt_types", AT["old"], AT["new"]),
         ("file_requests", "fs_upload_requests", FR["old"], FR["new"]))


def alive(table, rid):
    return bool(sql(f"SELECT 1 FROM {table} WHERE id=?", (rid,)))


# switch off: everything stays, the due rows are counted
out = box("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))")
for key, table, old, new in AREAS:
    check(f"'{key}': 1" in out and alive(table, old) and alive(table, new), f"#2879 switch off: {key} counted (1), nothing deleted {out[-300:]}")

# switch on: the due rows go (votes and options with the poll), the young ones stay
out = box("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))", ("KALMIDO_PURGE_TRASH=1",))
for key, table, old, new in AREAS:
    check(f"'{key}': 1" in out and not alive(table, old) and alive(table, new), f"#2879 switch on: {key} past the period deleted, the young one stays {out[-300:]}")
check(not sql("SELECT 1 FROM sched_poll_votes WHERE poll_id=?", (PL["old"],)) and not sql("SELECT 1 FROM sched_poll_options WHERE poll_id=?", (PL["old"],)),
      "#2879 the votes and options of the deleted poll went with it")
check(len(sql("SELECT 1 FROM sched_poll_votes WHERE poll_id=?", (PL["new"],))) == 1, "#2879 the votes of the young poll stay")
check(sql("SELECT type_id FROM appt_bookings WHERE id=?", (BOOK,))[0][0] is None,
      "#2879 a booking of a deleted appointment type keeps its time (type_id set null)")
check(alive("fs_nodes", FOLDER), "#2879 the folder of a deleted file request stays")
check("_err" not in out, f"#2879 no area failed {out[-300:]}")
r = A.get(B + "/api/admin/retention")
last = (r.json()["kinds"]["trash"].get("runs") or {}).get("trash") or {}
check(r.ok and last.get("purged") is True and last.get("counts", {}).get("absences") == 1, f"#2879 admin: the run's numbers name the absences {r.text[:300]}")

# 2.223.3 (#2878): a trashed client held only by a draft goes after the period (the draft stays without it); one held by a
# finalised invoice stays -- the trash run uses the same hold rule as deleting a client (team/clients.py cl_hold_sql)
CL = {}
for k in ("draft", "locked"):
    CL[k] = sql("INSERT INTO clients(org_id, name, created_by, created_at, updated_at, deleted_at) VALUES(?,?,?,?,?,?) RETURNING id",
                (PO, "Client p22233a " + k, FID, NOW, NOW, OLD))[0][0]
DR = sql("INSERT INTO office_docs(org_id, kind, client_id, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?) RETURNING id",
         (PO, "offer", CL["draft"], FID, NOW, NOW))[0][0]
sql("INSERT INTO office_docs(org_id, kind, number, status, client_id, created_by, created_at, updated_at, locked_at) VALUES(?,?,?,?,?,?,?,?,?)",
    (PO, "invoice", "P22233A-1", "sent", CL["locked"], FID, NOW, NOW, NOW))
out = box("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))", ("KALMIDO_PURGE_TRASH=1",))
check(not alive("clients", CL["draft"]) and alive("office_docs", DR) and sql("SELECT client_id FROM office_docs WHERE id=?", (DR,))[0][0] is None,
      f"#2878 trash run: a client held only by a draft goes, the draft stays {out[-300:]}")
check(alive("clients", CL["locked"]), "#2878 trash run: a client of a finalised invoice stays")

print(f"p22233_a_trash_runs: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
