#!/usr/bin/env python3
"""2.330 API tests, part A (small fixes found while filling staging), own container (start.sh). Invented companies, people
and figures only. tenant-matrix: life_org
 - #3295: Home & life in the private space shows only what lies in private projects. An office contract of the
   organisation (Office > Contracts & insurances, its deadline task in an organisation project), a device and a
   read-later entry in an organisation project never show in the private view (nor in its monthly / yearly sums); the
   private contract, device and read-later entry do; the organisation's view stays travel + staying in touch only
usage: p2330_a_kleine_fehler_test.py <datadir>"""
# kalmido-suite: fresh
import os
import subprocess
import sys
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from kt import check, dbx, done, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FEATS = "comments,collab,office,contracts,home,health,reading,travel,care"

if not os.environ.get("P2330A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Agentur Nordlicht", "admin_id": ALICE}).json()["id"]
SP = f"org:{ORG}"
assert A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATS, "workspace": SP}).ok
ENDS = (testclock.today() + timedelta(days=200)).isoformat()


def life(sp):
    r = A.get(B + "/api/life", params={"space": sp})
    assert r.ok, r.text
    return r.json()


# ---------------------------------------------------------------- the organisation's projects and entries
OL = A.post(B + "/api/lists", json={"name": "Agentur intern", "org_id": ORG}).json()["id"]
r = A.post(B + "/api/office/agreements", json={"kind": "rent", "name": "Gewerbemiete Studio", "provider": "Beispiel Immobilien GmbH",
                                                 "cost": "2000", "per": "month", "vat_pct": 0, "ends": ENDS, "notice": 3, "task": 1,
                                                 "list_id": OL})
check(r.status_code == 201 and r.json().get("task_id"), "an office contract with its deadline task " + r.text[:200])
OTASK = r.json().get("task_id")
check(dbx("SELECT list_id FROM tasks WHERE id=?", (OTASK,), DATA)[0][0] == OL, "its deadline task lies in the organisation's project")
r = A.post(B + "/api/life/devices", json={"name": "Studio-Drucker", "warranty": ENDS, "list_id": OL})
check(r.status_code == 201, "a device in the organisation's project " + r.text[:200])
ODEV = r.json().get("task_id") or r.json().get("id")
r = A.post(B + "/api/reading", json={"url": "https://example.com/report", "title": "Branchenbericht", "space": SP})
check(r.status_code == 201, "a read-later entry of the organisation " + r.text[:200])
ORT, ORL = r.json().get("task_id"), r.json().get("list_id")
check(dbx("SELECT org_id FROM lists WHERE id=?", (ORL,), DATA)[0][0] == ORG, "in the organisation's read-later project")

# ---------------------------------------------------------------- the private ones
r = A.post(B + "/api/life/contracts", json={"name": "Handyvertrag", "provider": "Beispiel Mobil", "cost": 20, "per": "month", "ends": ENDS})
check(r.status_code == 201, "a private contract " + r.text[:200])
PTASK = r.json().get("task_id") or r.json().get("id")
r = A.post(B + "/api/life/devices", json={"name": "Waschmaschine", "warranty": ENDS})
check(r.status_code == 201, "a private device " + r.text[:200])
PDEV = r.json().get("task_id") or r.json().get("id")
r = A.post(B + "/api/reading", json={"url": "https://example.com/recipe", "title": "Rezept", "space": "private"})
check(r.status_code == 201, "a private read-later entry " + r.text[:200])
PRT, PRL = r.json().get("task_id"), r.json().get("list_id")

# ---------------------------------------------------------------- #3295: the private view
j = life("private")
cs = [x["task_id"] for x in j.get("contracts", {}).get("items", [])]
check(cs == [PTASK], f"private contracts: only the private one, never the organisation's office contract {cs} (org {OTASK})")
check(j["contracts"]["monthly"] == 20 and j["contracts"]["yearly"] == 240, f"the sums only count the private contract {j['contracts']}")
ds = [x["task_id"] for x in j.get("home", {}).get("devices", [])]
check(ds == [PDEV], f"private devices: only the private one {ds} (org {ODEV})")
rd = j.get("reading") or {}
ri = [x["task_id"] for x in rd.get("items", [])]
check(ri == [PRT] and rd.get("count") == 1 and rd.get("lists") == [PRL], f"read later: only the private project and entry {rd.get('lists')} {ri} (org {ORT})")
check(life("") == j, "no space = private, the same answer")
# the organisation's view: as before, travel + staying in touch only
jo = life(SP)
check(set(jo["modules"]) <= {"travel", "care"} and not any(k in jo for k in ("contracts", "home", "health", "reading")),
      f"organisation view: still no contracts / devices / health / read later {jo.get('modules')}")
# the organisation's contract stays in the office, unchanged
check('"office_agreement"' in dbx("SELECT fam FROM tasks WHERE id=? AND status=0 AND deleted_at IS NULL", (OTASK,), DATA)[0][0],
      "the office contract's task stays as it was")

sys.exit(done("p2330_a_kleine_fehler"))
