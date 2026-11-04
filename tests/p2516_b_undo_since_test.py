#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.516.0 (#4366): the undo of an account import, findings 7-9 of audit #2478. Invented names only (example.com). A person
without an organisation exports, a second one imports into the private workspace (freelancer-matrix: own):
 - a habit with a reminder time (remind_at "08:00", a time of day) nobody touched since goes like the one without
 - an own, older event moved into an imported calendar since: the calendar stays and the event with it
 - an imported calendar renamed since (its events untouched: only ev_cals.changed_at says so) stays with its event
 - an imported calendar nothing happened in goes
 - a sprint the import brought into the list of an earlier import, that list belongs to somebody else since (no right to
   write there): it stays
 - every time column the undo reads as "worked on since" (umz_undoplan._work_cols) holds an ISO time stamp in this database
usage: p2516_b_undo_since_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, until  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()


def one(sql, args=()):
    r = kt.dbx(sql, args)
    return r[0][0] if r else None


def run_sql(q, args=()):
    """A write in the suite's database (kt.dbx only reads)."""
    import dbx as dbxm
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"), timeout=10)
    try:
        c.execute(q, args)
        c.commit()
    finally:
        c.close()


def in_app(code):
    """Lines of Python inside the container; prints the JSON of `out`."""
    head = "import json\nimport app\nfrom kalmido.core.db import connect\nc = connect()\n"
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", kt.CT, "python", "-c", head + code + "\nprint('OUT' + json.dumps(out))"],
                       capture_output=True, text=True, timeout=200)
    for line in r.stdout.splitlines():
        if line.startswith("OUT"):
            return json.loads(line[3:])
    raise AssertionError(r.stdout[-800:] + r.stderr[-1500:])


def export_of(s):
    r = s.post(B + "/api/account/export")
    assert r.status_code == 202, r.text
    j = until(lambda: (lambda x: x if x.get("state") != "running" else None)(s.get(B + "/api/account/export").json()), 120)
    assert j and j.get("state") == "done", j
    r = kt.su_get(s, B + "/api/account/export/file")
    assert r.ok, r.text[:200]
    return r.content


def state_of(s, iid):
    j = s.get(B + f"/api/account/import/{iid}").json()
    return j if j.get("state") not in ("checking", "running", "upload") else None


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "kalmido-account.zip"})
    assert r.ok, r.text
    iid = r.json()["id"]
    r = s.put(B + f"/api/account/import/{iid}?offset=0", data=data, headers={"Content-Type": "application/octet-stream"})
    assert r.ok, r.text
    return iid, until(lambda: state_of(s, iid), 180) or {}


kt.fresh(env={"KALMIDO_SECRET_KEY": KEY}, prefix="P2516B")
A = kt.setup()
AID = one("SELECT id FROM users WHERE username='alice'")
FID, Fr = freelancer(B, A, features=FEATURES)
GID, Gi = freelancer(B, A, "gina", features=FEATURES)


def do_import(s, data):
    iid, j = upload(s, data)
    check(j.get("state") == "preview", f"preview {j.get('state')} {j.get('error')}")
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}, "again": True})
    check(r.status_code == 202, f"the run {r.text[:160]}")
    j = until(lambda: state_of(s, iid), 180) or {}
    check(j.get("state") == "done", f"done {j.get('state')} {j.get('error')}")
    return (j.get("result") or {}).get("import_id")


# ---------------------------------------------------------------- a first import: a project list (a sprint comes with the second)
L = Fr.post(B + "/api/lists", json={"name": "Projekt Sprint"}).json()["id"]
check(Fr.patch(B + f"/api/lists/{L}", json={"kind": "project"}).ok, "a project list")
check(Fr.post(B + "/api/tasks", json={"title": "Aufgabe im Projekt", "list_id": L}).status_code in (200, 201), "a task in it")
check(do_import(Gi, export_of(Fr)), "the first import")
r = Fr.put(B + f"/api/lists/{L}/sprint-settings", json={"on": True})
check(r.ok and r.json().get("started_id"), f"sprints on, the first sprint runs {r.text[:160]}")

# ---------------------------------------------------------------- what the person moving has for the second
check(Fr.post(B + "/api/habits", json={"name": "Mit Erinnerung", "remind_at": "08:00"}).status_code in (200, 201), "a habit with a reminder")
check(Fr.post(B + "/api/habits", json={"name": "Ohne Erinnerung"}).status_code in (200, 201), "a habit without")
D = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
for n in ("Kalender Ziel", "Kalender Still", "Kalender Umbenannt"):
    r = Fr.post(B + "/api/evcals", json={"name": n})
    check(r.status_code in (200, 201), f"calendar {n} {r.text[:160]}")
    r = Fr.post(B + "/api/events", json={"cal_id": r.json().get("id"), "title": f"Termin in {n}", "start": f"{D}T10:00", "end": f"{D}T11:00",
                                         "tz": "Europe/Berlin"})
    check(r.status_code in (200, 201), f"an event in {n} {r.text[:160]}")

# the importing person's own, older calendar and event
r = Gi.post(B + "/api/evcals", json={"name": "Eigener Kalender"})
check(r.status_code in (200, 201), "gina's own calendar")
r = Gi.post(B + "/api/events", json={"cal_id": r.json().get("id"), "title": "Mein Termin", "start": f"{D}T14:00", "end": f"{D}T15:00",
                                     "tz": "Europe/Berlin"})
check(r.status_code in (200, 201), f"gina's own event {r.text[:160]}")
MINE = r.json().get("id")

# ---------------------------------------------------------------- the import
IMP = do_import(Gi, export_of(Fr))
check(IMP, "an import to undo")
at = one("SELECT created_at FROM imports WHERE id=?", (IMP,))
since = datetime.fromisoformat(at.replace("Z", "+00:00"))
check(until(lambda: datetime.now(timezone.utc) >= since + timedelta(seconds=1.1) or None, 10), "the clock is past the import")

HR = one("SELECT id FROM habits WHERE name='Mit Erinnerung' AND user_id=?", (GID,))
HO = one("SELECT id FROM habits WHERE name='Ohne Erinnerung' AND user_id=?", (GID,))
check(HR and one("SELECT remind_at FROM habits WHERE id=?", (HR,)) == "08:00", "the imported habit keeps its reminder time")
KZ = one("SELECT id FROM ev_cals WHERE name='Kalender Ziel' AND owner_id=?", (GID,))
KS = one("SELECT id FROM ev_cals WHERE name='Kalender Still' AND owner_id=?", (GID,))
KU = one("SELECT id FROM ev_cals WHERE name='Kalender Umbenannt' AND owner_id=?", (GID,))
GL = one("SELECT id FROM lists WHERE name='Projekt Sprint' AND owner_id=?", (GID,))
SP = one("SELECT id FROM sprints WHERE list_id=?", (GL,))
check(KZ and KS and KU and GL and SP, f"the imports brought the calendars, the list and its sprint {KZ} {KS} {KU} {GL} {SP}")
cr = json.loads(one("SELECT created FROM imports WHERE id=?", (IMP,)) or "{}")
check(["sprints", SP] in (cr.get("parts") or []), f"the second import recorded the sprint on the list of the first {cr.get('parts')}")

# ---------------------------------------------------------------- since the import
r = Gi.patch(B + f"/api/events/{MINE}", json={"cal_id": KZ})
check(r.ok, f"gina moves her own event into an imported calendar {r.status_code} {r.text[:160]}")
check(one("SELECT cal_id FROM events WHERE id=?", (MINE,)) == KZ, "the event lies in the imported calendar")
r = Gi.patch(B + f"/api/evcals/{KU}", json={"name": "Mein Kalender jetzt"})
check(r.ok, f"gina renames an imported calendar (its events untouched) {r.status_code} {r.text[:160]}")
# the imported list belongs to somebody else since (handed over, gina no member): its sprint is not gina's to take back
run_sql("UPDATE lists SET owner_id=? WHERE id=?", (AID, GL))
run_sql("DELETE FROM list_members WHERE list_id=? AND user_id=?", (GL, GID))

# ---------------------------------------------------------------- the undo
r = Gi.post(B + f"/api/imports/{IMP}/undo", json={})
check(r.ok, f"the undo {r.status_code} {r.text[:200]}")


def there(table, rid):
    return bool(kt.dbx(f"SELECT 1 FROM {table} WHERE id=?", (rid,)))


check(not there("habits", HR), "the untouched habit with a reminder time goes (remind_at is no time stamp)")
check(not there("habits", HO), "the untouched habit without goes")
check(there("events", MINE) and not one("SELECT deleted_at FROM events WHERE id=?", (MINE,)), "gina's own moved event is still there")
check(there("ev_cals", KZ), "the calendar it was moved into stays")
check(not there("ev_cals", KS), "the calendar nothing happened in goes")
check(there("ev_cals", KU) and there("events", one("SELECT MIN(id) FROM events WHERE cal_id=?", (KU,)) or 0),
      "the calendar renamed since (only its changed_at says so) stays with its event")
check(there("sprints", SP), "the sprint of a list gina may not write any more stays")

# ---------------------------------------------------------------- every work time column holds ISO here
j = in_app("""
from kalmido.admin.acctimport import umz_cols
from kalmido.admin.orgimport import oi_tables
from kalmido.admin.umz_undoplan import _BASE, _PARTS, _work_cols
from kalmido.core.db import parse_iso
out = {"bad": [], "cols": 0}
for t in sorted(set(oi_tables()) | set(_BASE) | set(_PARTS) | {"ev_cals", "books", "events", "contacts"}):
    if not umz_cols(c, t)[0]:
        continue
    for col in _work_cols(c, t):
        out["cols"] += 1
        for (v,) in c.execute(f"SELECT {col} FROM {t} WHERE {col} IS NOT NULL AND CAST({col} AS TEXT) <> '' LIMIT 50").fetchall():
            try:
                parse_iso(v)
            except (TypeError, ValueError):
                out["bad"].append(f"{t}.{col}={v!r}")
                break
""")
check(j["cols"] > 20, f"the scan reads the work time columns of the undo's tables: {j['cols']}")
check(not j["bad"], f"every work time column of the undo holds an ISO time stamp (else into _NOT_WORK): {j['bad']}")

sys.exit(kt.done("p2516_b_undo_since"))
