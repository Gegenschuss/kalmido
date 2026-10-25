#!/usr/bin/env python3
"""2.272.0 API tests, part D (#3029, #3027 client part): deleting a client or an organisation names what goes along, a
client goes to the trash. Own container (start.sh, mode workspaces). Invented accounts only (example.com); the person
without an organisation (freelancer fixture, private clients in the personal office) does every client step.
 - GET /api/clients/usage counts every row pointing at the client (foreign-key catalogue): contact person, project, data
   protection sheet, mail-in address
 - DELETE /api/clients/<id> = the trash: gone from the lists, the state, the client page, the portal link, the mail-in
   address; the project lets go of it; restore brings it back with its project; bulk delete / untrash the same
 - the trash run only counts while the switch is off, with KALMIDO_PURGE_TRASH=1 it deletes the client for good (the
   data protection sheet, the mail-in address and the contact person go along)
 - the delete dialog of an organisation counts the rest of its content (a deal)
 - the undo of an office import takes its clients only within 24 hours, then into the clients' trash
freelancer-matrix: office
usage: p2272_d_client_delete_test.py <datadir>      (P2272D_NOSTART=1: a running server on KALMIDO_TEST_PORT)
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


if os.environ.get("P2272D_NOSTART") != "1":
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

Fr.get(B + "/api/office/docs?kind=invoice")  # the personal office exists from its first use
PO = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
NOW = ago()

# ================================================================== what points at a client
r = Fr.post(B + "/api/clients", json={"name": "Acme Test", "email": "acme@example.com", "contacts": [{"name": "Ann Example"}]})
assert r.status_code == 201, r.text
CID = r.json()["id"]
check(r.json()["org_id"] is None, "setup: the freelancer's client is private")
LID = Fr.post(B + "/api/lists", json={"name": "Acme project"}).json()["id"]
sql("UPDATE lists SET client_id=? WHERE id=?", (CID, LID))
sql("INSERT INTO office_privacy_sheets(org_id, client_id, created_by, created_at, updated_at) VALUES(?,?,?,?,?)", (PO, CID, FID, NOW, NOW))
sql("INSERT INTO hub_tokens(token, kind, user_id, org_id, client_id, created_at) VALUES(?,?,?,?,?,?)", ("p2272dtoken01", "client", FID, None, CID, NOW))
u = Fr.get(B + f"/api/clients/usage?ids={CID}").json()
refs = u.get("refs") or {}
check(refs.get("office_privacy_sheets") == 1 and refs.get("hub_tokens") == 1 and refs.get("office_client_contacts") == 1 and refs.get("lists") == 1,
      f"usage: the data protection sheet, mail-in address, contact person and project are counted {refs}")
check("1 data protection sheet" in u.get("text", "") and "1 project" in u.get("text", ""), f"usage: the text names them {u.get('text')}")
check(u.get("in_use") == 0 and u.get("trash_days", 0) >= 1, f"usage: not kept by records, a trash period {u}")
check(Fr.get(B + "/api/clients/usage?ids=999999").status_code == 404, "usage: a client one does not see -> 404")

HOLDER = (f"from kalmido.hub import hubmail as H\nfrom kalmido.core.pg import system_ctx\n"
          f"with system_ctx(c):\n    print('holder', H._holder_ok(c, 'client', {FID}, None, {CID}, None) is not None)")
portal0 = Fr.post(B + f"/api/office/clients/{CID}/portal-link", json={}).status_code
hold0 = box(HOLDER)
check("holder True" in hold0, f"setup: the mail-in address of the client receives {hold0[-300:]}")

# ================================================================== delete = trash, restore
r = Fr.delete(B + f"/api/clients/{CID}")
check(r.ok and r.json().get("trashed") is True, f"delete: the client goes to the trash {r.text[:200]}")
check(CID not in [x["id"] for x in Fr.get(B + "/api/clients?archived=1").json()["clients"]], "trash: not in the client list (also with archived)")
check(Fr.get(B + f"/api/clients/{CID}").status_code == 404, "trash: the client page answers 404")
check(CID not in [x["id"] for x in Fr.get(B + "/api/state").json().get("clients") or []], "trash: not in the pickers (state)")
portal1 = Fr.post(B + f"/api/office/clients/{CID}/portal-link", json={}).status_code
check(portal0 != 404 and portal1 == 404, f"trash: no portal link for a client in the trash ({portal0} -> {portal1})")
hold1 = box(HOLDER)
check("holder False" in hold1, f"trash: its mail-in address receives no more {hold1[-300:]}")
# 2.272.0 F (#3029, review M1): a mail to it is kept with the client (hidden until the restore), not lost
th = box(f"from kalmido.hub import hubmail as H\nfrom kalmido.core.pg import system_ctx\n"
         f"with system_ctx(c):\n    print('keep', H.hbm_trash_holder(c, {FID}, {CID}))")
check(f"keep (None, {CID})" in th, f"trash: a mail to its address is kept with the client {th[-300:]}")
# 2.272.0 F (#3029, review M2): an approval link of the client's video review is dead while the client lies in the trash
VR = sql("INSERT INTO video_reviews(client_id, owner_id, title, created_at, updated_at) VALUES(?,?,?,?,?) RETURNING id", (CID, FID, "Cut 1", NOW, NOW))[0][0]
SIGROW = (f"from kalmido.videos.review import vdr_sig_row\nfrom kalmido.core.pg import system_ctx\n"
          f"with system_ctx(c):\n    print('sigrow', vdr_sig_row(c, {{'video_id': {VR}}}) is not None)")
sr = box(SIGROW)
check("sigrow False" in sr, f"trash: the video approval link of the client is dead {sr[-300:]}")
check(sql("SELECT client_id FROM lists WHERE id=?", (LID,))[0][0] is None, "trash: the project lets go of the client")
check(sql("SELECT COUNT(*) FROM office_privacy_sheets WHERE client_id=?", (CID,))[0][0] == 1
      and sql("SELECT COUNT(*) FROM hub_tokens WHERE client_id=?", (CID,))[0][0] == 1, "trash: data protection sheet and mail-in address stay")
t = Fr.get(B + "/api/clients/trash").json()
check([x["id"] for x in t.get("clients", [])] == [CID] and t["clients"][0]["deleted_at"] and t.get("trash_days", 0) >= 1,
      f"trash: the trash lists it with the period {t}")
check(Fr.get(B + f"/api/clients/usage?ids={CID}").ok, "trash: the dialog of the final delete reads its numbers")

r = Fr.post(B + f"/api/clients/{CID}/restore")
check(r.ok and r.json().get("id") == CID and LID in r.json().get("lists", []), f"restore: back with its project {r.text[:200]}")
check(Fr.get(B + f"/api/clients/{CID}").ok and len(Fr.get(B + f"/api/clients/{CID}").json().get("contacts") or []) == 1, "restore: the page and the contact person are back")
check("holder True" in box(HOLDER), "restore: the mail-in address receives again")
check("sigrow True" in box(SIGROW), "restore: the video approval link works again")
check(Fr.post(B + f"/api/clients/{CID}/restore").status_code == 404, "restore: a client not in the trash -> 404")

j = Fr.post(B + "/api/clients/bulk", json={"action": "delete", "ids": [CID]}).json()
check(j.get("deleted") == 1 and j.get("trashed") == [CID], f"bulk: delete moves into the trash {j}")
j = Fr.post(B + "/api/clients/bulk", json={"action": "untrash", "ids": [CID]}).json()
check(j.get("changed") == 1 and Fr.get(B + f"/api/clients/{CID}").ok, f"bulk: untrash brings it back {j}")
check(sql("SELECT client_id FROM lists WHERE id=?", (LID,))[0][0] == CID, "bulk: the project has the client again")

# ================================================================== the trash run: counts with the switch off, deletes with it on
assert Fr.delete(B + f"/api/clients/{CID}").ok
sql("UPDATE clients SET deleted_at=? WHERE id=?", (ago(days=40), CID))
out = box("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))")
check(sql("SELECT COUNT(*) FROM clients WHERE id=?", (CID,))[0][0] == 1 and "'clients': 1" in out, f"run: switch off = counted, the client stays {out[-300:]}")
out = box("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))", ("KALMIDO_PURGE_TRASH=1",))
check(sql("SELECT COUNT(*) FROM clients WHERE id=?", (CID,))[0][0] == 0, f"run: switch on = the client is deleted for good {out[-300:]}")
check(sql("SELECT COUNT(*) FROM office_privacy_sheets WHERE client_id=?", (CID,))[0][0] == 0
      and sql("SELECT COUNT(*) FROM hub_tokens WHERE client_id=?", (CID,))[0][0] == 0
      and sql("SELECT COUNT(*) FROM office_client_contacts WHERE client_id=?", (CID,))[0][0] == 0,
      "run: data protection sheet, mail-in address and contact person go with it")
check(sql("SELECT COUNT(*) FROM lists WHERE id=?", (LID,))[0][0] == 1, "run: the project stays")

# a person deletes a client in the trash for good
C2 = Fr.post(B + "/api/clients", json={"name": "Beta Test"}).json()["id"]
check(Fr.delete(B + f"/api/clients/{C2}/purge").status_code == 404, "purge: only a client in the trash")
assert Fr.delete(B + f"/api/clients/{C2}").ok
check(Fr.delete(B + f"/api/clients/{C2}/purge").ok and not sql("SELECT 1 FROM clients WHERE id=?", (C2,)), "purge: deleted for good from the trash")

# ================================================================== the delete dialog of an organisation
OID = A.post(B + "/api/admin/orgs", json={"name": "Gamma Example"}).json()["id"]
sql("INSERT INTO office_deals(org_id, title, created_at, updated_at) VALUES(?,?,?,?)", (OID, "Example deal", NOW, NOW))
info = A.get(B + f"/api/admin/orgs/{OID}/delete-info").json()
check((info.get("more") or {}).get("deals") == 1 and "1 deal" in (info.get("more_text") or ""), f"org: the dialog counts the deal {info.get('more')} {info.get('more_text')}")
check("org_members" not in (info.get("more") or {}) and not (info.get("more") or {}).get("other"), f"org: members / settings are no content {info.get('more')}")

# ================================================================== the undo of an office import: clients 24 hours, then the trash
RID = sql("INSERT INTO office_import_runs(org_id, kind, created_by, created_at) VALUES(?,?,?,?) RETURNING id", (PO, "data", FID, ago(hours=25)))[0][0]
C3 = sql("INSERT INTO clients(name, created_by, created_at, updated_at, import_run_id) VALUES(?,?,?,?,?) RETURNING id", ("Imported Example", FID, NOW, NOW, RID))[0][0]
r = Fr.post(B + f"/api/office/legacy/runs/{RID}/undo", json={"kinds": ["clients"]})
check(r.status_code == 409 and sql("SELECT deleted_at FROM clients WHERE id=?", (C3,))[0][0] is None, f"import undo: after 25 hours the clients stay {r.status_code} {r.text[:200]}")
sql("UPDATE office_import_runs SET created_at=? WHERE id=?", (ago(hours=1), RID))
r = Fr.post(B + f"/api/office/legacy/runs/{RID}/undo", json={"kinds": ["clients"]})
row = sql("SELECT deleted_at FROM clients WHERE id=?", (C3,))
check(r.ok and (r.json().get("removed") or {}).get("clients") == 1 and row and row[0][0], f"import undo: within 24 hours the client goes to the trash {r.text[:200]} {row}")
check(C3 in [x["id"] for x in Fr.get(B + "/api/clients/trash").json().get("clients", [])], "import undo: the client lies in the trash (restorable)")

# 2.272.0 F (#3027, review H1): the undo leaves the contact persons of a client it puts into the trash -> restore brings them back
RID2 = sql("INSERT INTO office_import_runs(org_id, kind, created_by, created_at) VALUES(?,?,?,?) RETURNING id", (PO, "data", FID, ago(hours=1)))[0][0]
C4 = Fr.post(B + "/api/clients", json={"name": "Imported Delta", "contacts": [{"name": "Dora Example"}]}).json()["id"]
sql("UPDATE clients SET import_run_id=? WHERE id=?", (RID2, C4))
sql("UPDATE office_client_contacts SET import_run_id=? WHERE client_id=?", (RID2, C4))
r = Fr.post(B + f"/api/office/legacy/runs/{RID2}/undo", json={"kinds": ["clients"]})
check(r.ok and sql("SELECT COUNT(*) FROM office_client_contacts WHERE client_id=?", (C4,))[0][0] == 1,
      f"import undo: the contact person stays with the client in the trash {r.text[:200]}")
r = Fr.post(B + f"/api/clients/{C4}/restore")
check(r.ok and len(Fr.get(B + f"/api/clients/{C4}").json().get("contacts") or []) == 1, f"import undo: restore brings the contact person back {r.text[:200]}")

print(f"p2272_d_client_delete: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
