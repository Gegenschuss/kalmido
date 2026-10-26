#!/usr/bin/env python3
"""2.239.0 API tests, part C (#2866 #2943 #2874): account deletion and retention, own container (start.sh, mode workspaces,
server key). Invented names only, addresses @example.com. freelancer-matrix: office  tenant-matrix: org
 - #2866: a guest / accounting person never takes over the organisation's calendar of a deleted account: without another
   admin or member the deletion is refused (409, nothing changed); with a member it goes and the member gets it
 - #2866: the private-space check of an organisation admin's deletion names agents' projects, the personal office's
   vehicles, focus sessions and notes in the basket
 - #2866: stored admin alerts naming the deleted account name its number instead
 - #2874: the personal retention export has no receipts of an organisation's project (only the own projects)
 - #2874: an organisation with only a procedure documentation / an e-invoice is retired, not deleted; deleting a retired
   organisation by hand computes the period anew
 - a person without an organisation: the own retention export and the account deletion work as before
usage: p2239_c_loeschung_test.py <datadir>"""
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess, su_get  # noqa: E402  shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,events,files,docs,office,clients"
KEYENV = " -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY=" + "A" * 43 + "="
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def app_log():
    out = subprocess.run(["docker", "logs", "--tail", "400", CT], capture_output=True, text=True)
    text = out.stdout + out.stderr
    i = text.rfind("Traceback")
    print(text[i:i + 4000] if i >= 0 else text[-2000:], flush=True)


def new_user(name, orgs=None, admin=False):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title() + " Example", "password": "password123",
                                       "email": f"{name}@example.com", "orgs": orgs or [], "is_admin": admin})
    assert r.ok, r.text
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
    return r.json()["id"], s


if os.environ.get("P2239C_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces" + KEYENV)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/me").json()["id"]
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok

# ================================================================== #2866: the heir is an admin or a member, never a guest
# carl shares organisation Hub with alice (an instance admin manages the people she shares an organisation with, #1592)
HUB = A.post(B + "/api/admin/orgs", json={"name": "Hub Studio", "admin_id": ALICE}).json()["id"]
CARL, Ca = new_user("carl", [{"id": HUB, "role": "member"}])
GAM = A.post(B + "/api/admin/orgs", json={"name": "Gamma Studio", "admin_id": CARL}).json()["id"]
GINA, _ = new_user("gina", [{"id": GAM, "role": "guest"}])
ANNA, _ = new_user("anna", [{"id": GAM, "role": "accounting"}])
roles = dict(sql("SELECT user_id, role FROM org_members WHERE org_id=?", (GAM,)))
if roles.get(CARL) != "admin":  # added by an instance admin as its admin (as p2186_a)
    sql("INSERT INTO org_members(org_id, user_id, role) VALUES(?,?,'admin') ON CONFLICT DO NOTHING", (GAM, CARL), write=True)
    roles = dict(sql("SELECT user_id, role FROM org_members WHERE org_id=?", (GAM,)))
check(roles.get(CARL) == "admin" and roles.get(GINA) == "guest" and roles.get(ANNA) == "accounting", f"setup: Gamma's roles {roles}")
Ca.patch(B + "/api/settings", json={"workspace": f"org:{GAM}"})
r = Ca.post(B + "/api/evcals", json={"name": "Gamma bookings", "org_id": GAM})
GCAL = r.json().get("id") if r.ok else None
check(GCAL and sql("SELECT owner_id, org_id FROM ev_cals WHERE id=?", (GCAL,)) == [(CARL, GAM)], "setup: carl's calendar of Gamma " + r.text[:160])
# a stored admin alert naming carl (user name, e-mail address, display name)
sql("INSERT INTO admin_alerts(kind, key, message, tmpl, created_at, state) VALUES(?,?,?,?,?,?)",
    ("security", "admin:carl", "carl is now an admin (set by alice). Contact: carl@example.com, Carl Example",
     json.dumps(["{0} is now an admin (set by {1}).", None, ["carl", "alice"], None]), NOW, "sent"), write=True)
r = A.delete(B + f"/api/users/{CARL}")
check(r.status_code == 409 and "another admin or member" in r.json().get("error", ""),
      "carl: refused while only a guest and an accounting person are left (409) " + r.text[:200])
check(sql("SELECT 1 FROM users WHERE id=?", (CARL,)) and sql("SELECT owner_id FROM ev_cals WHERE id=?", (GCAL,)) == [(CARL,)],
      "carl: nothing changed (account and calendar owner)")
MIA, _ = new_user("mia", [{"id": GAM, "role": "member"}])
r = A.delete(B + f"/api/users/{CARL}")
check(r.ok and not sql("SELECT 1 FROM users WHERE id=?", (CARL,)), "carl: deleted once a member is there " + r.text[:200])
if not r.ok:
    app_log()
check(sql("SELECT owner_id FROM ev_cals WHERE id=?", (GCAL,)) == [(MIA,)], "the member takes over the calendar, not the guest")
rows = sql("SELECT key, message, tmpl FROM admin_alerts WHERE key LIKE 'admin:%'")
text = json.dumps([list(x) for x in rows])
check(rows and "carl" not in text.lower() and f"#{CARL}" in text, f"the stored alert names the account by its number {text[:300]}")
check("alice" in text, "the other names of the alert stay")
# 2.239.0 (#2866, review): a lone first name as display name is a common word - other alerts keep it
HUGO, _ = new_user("hugo")
sql("UPDATE users SET display_name='Backup' WHERE id=?", (HUGO,), write=True)
sql("INSERT INTO admin_alerts(kind, key, message, tmpl, created_at, state) VALUES(?,?,?,?,?,?)",
    ("backup", "backup:p2239c", "Backup failed on the server", json.dumps(["Backup failed on the server", None, [], None]), NOW, "sent"), write=True)
r = A.delete(B + f"/api/users/{HUGO}")
check(r.ok and sql("SELECT message FROM admin_alerts WHERE key='backup:p2239c'") == [("Backup failed on the server",)],
      "a one-word display name of a deleted account leaves other alerts alone " + r.text[:160])

# ================================================================== #2866: the private-space check of an organisation admin
ALP = A.post(B + "/api/admin/orgs", json={"name": "Alpha Film", "admin_id": ALICE}).json()["id"]
DORA, Do = new_user("dora", [{"id": ALP, "role": "admin"}])
BOB, Bo = new_user("bob", [{"id": ALP, "role": "member"}])
check(Do.get(B + f"/api/users/{BOB}/delete-info").json().get("can_delete") is True, "setup: dora (organisation admin) may delete bob, nothing private")


def reason():
    j = Do.get(B + f"/api/users/{BOB}/delete-info").json()
    return j.get("can_delete"), j.get("reason") or ""


# focus sessions
sql("INSERT INTO pomos(kind, minutes, start, user_id) VALUES('focus', 25, ?, ?)", (NOW, BOB), write=True)
ok, why = reason()
check(ok is False and "focus sessions" in why, f"focus sessions named: {why}")
sql("DELETE FROM pomos WHERE user_id=?", (BOB,), write=True)
# notes in the basket
INBOX = sql("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (BOB,))[0][0]
sql("INSERT INTO notes(list_id, title, body, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?)", (INBOX, "Idea", "text", BOB, NOW, NOW), write=True)
ok, why = reason()
check(ok is False and "notes" in why, f"notes in the basket named: {why}")
sql("DELETE FROM notes WHERE list_id=?", (INBOX,), write=True)
# a vehicle of the personal office
sql("INSERT INTO orgs(name, icon, created_at, personal_of) VALUES(?,?,?,?)", ("private", "", NOW, BOB), write=True)
POID = sql("SELECT id FROM orgs WHERE personal_of=?", (BOB,))[0][0]
sql("INSERT INTO office_vehicles(org_id, name, created_at, updated_at) VALUES(?,?,?,?)", (POID, "Kombi", NOW, NOW), write=True)
ok, why = reason()
check(ok is False and "personal office" in why, f"a vehicle of the personal office named: {why}")
sql("DELETE FROM office_vehicles WHERE org_id=?", (POID,), write=True)
# a private project of bob's own agent
Bo.patch(B + "/api/settings", json={"workspace": "private"})
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot", "display_name": "Bobbot", "scopes": ["read"], "org_id": None})
AG = (sql("SELECT user_id FROM agents WHERE owner_id=?", (BOB,)) or [[None]])[0][0]
check(AG, "setup: bob's agent " + r.text[:160])
r = Bo.post(B + "/api/lists", json={"name": "Agent work"})
AL = r.json().get("id") if r.ok else None
check(AL, "setup: a list " + r.text[:160])
sql("UPDATE lists SET owner_id=?, org_id=NULL WHERE id=?", (AG, AL), write=True)
ok, why = reason()
check(ok is False and "agents' projects" in why, f"the agent's private project named: {why}")
check("projects" not in why.replace("agents' projects", ""), "bob himself owns no private project")
r = Do.delete(B + f"/api/users/{BOB}")
check(r.status_code == 409 and sql("SELECT 1 FROM users WHERE id=?", (BOB,)), "dora does not delete bob with his agent's private project " + r.text[:200])
if not sql("SELECT 1 FROM users WHERE id=?", (BOB,)):
    print(f"p2239_c_loeschung: {OKS[0]} ok, {len(FAILS)} failed (stopped: bob is gone)", flush=True)
    sys.exit(1)

# ================================================================== #2874: the personal retention export: own projects only
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ALP}"})
r = Bo.post(B + "/api/lists", json={"name": "Alpha budget"})
OL = r.json().get("id") if r.ok else None
Bo.patch(B + "/api/settings", json={"workspace": "private"})
r = Bo.post(B + "/api/lists", json={"name": "Home budget"})
PL = r.json().get("id") if r.ok else None
check(OL and PL and sql("SELECT org_id FROM lists WHERE id=?", (OL,)) == [(ALP,)] and sql("SELECT org_id FROM lists WHERE id=?", (PL,)) == [(None,)],
      "setup: bob owns an Alpha project and a private one")
for lid in (OL, PL):
    sql("INSERT INTO budget_entries(list_id, day, amount, title, created_at, updated_at) VALUES(?,?,?,?,?,?)", (lid, "2026-03-02", "-10", "Paper", NOW, NOW), write=True)
    eid = sql("SELECT id FROM budget_entries WHERE list_id=?", (lid,))[0][0]
    sql("INSERT INTO budget_files(entry_id, list_id, name, path, created_at) VALUES(?,?,?,?,?)", (eid, lid, f"receipt-{lid}.pdf", f"budget/{lid}/x.pdf", NOW), write=True)
r = Bo.get(B + "/api/retention/me")
check(r.ok and (r.json().get("counts") or {}).get("project_receipts") == 1, "bob: only the private project's receipt counts " + r.text[:300])
r = su_get(Bo, B + "/api/retention/me/export.zip")  # 2.223.2 C (#2871): the download needs the step-up (bundle 2.305)
csv = ""
if r.ok and r.content[:2] == b"PK":
    z = zipfile.ZipFile(io.BytesIO(r.content))
    csv = next((z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith("project-receipts.csv")), "")
check("Home budget" in csv and "Alpha budget" not in csv, f"bob: the export lists the private project's receipt only {csv[:300]}")

# ================================================================== #2874: what retires an organisation
OM = A.post(B + "/api/admin/orgs", json={"name": "Omega Docs", "admin_id": ALICE}).json()["id"]
sql("INSERT INTO office_procdocs(org_id, version, data, created_by, created_at) VALUES(?,?,?,?,?)", (OM, 1, "{}", ALICE, NOW), write=True)
r = A.delete(B + f"/api/admin/orgs/{OM}")
check(r.status_code == 409 and (r.json().get("retain_until") or "") >= "2036-12-31" and (r.json().get("kept") or {}).get("procdocs") == 1,
      "Omega (procedure documentation only): retired instead of deleted " + r.text[:300])
r = A.delete(B + f"/api/admin/orgs/{OM}", params={"confirm": "1"})
check(r.ok and r.json().get("retired") is True, "Omega: retired on confirmation " + r.text[:200])
# deleting by hand: the period anew (the stored one ran out, the procedure documentation still runs)
sql("UPDATE orgs SET retain_until='2020-12-31' WHERE id=?", (OM,), write=True)
r = A.delete(B + f"/api/admin/orgs/{OM}")
check(r.status_code == 409 and sql("SELECT 1 FROM orgs WHERE id=?", (OM,)), "Omega: not deleted by hand while the new period runs " + r.text[:200])
check((sql("SELECT retain_until FROM orgs WHERE id=?", (OM,)) or [[""]])[0][0] >= "2036-12-31", "Omega: the new period is noted")
di = A.get(B + f"/api/admin/orgs/{OM}/delete-info").json()
check((di.get("kept_until") or "") >= "2036-12-31", f"Omega: delete-info shows the new period {di.get('kept_until')}")

# an e-invoice in the documents, no receipt (yet)
PSI = A.post(B + "/api/admin/orgs", json={"name": "Psi Invoices", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{PSI}"})
r = A.post(B + "/api/files/folders", json={"name": "Invoices", "space": f"org:{PSI}"})
PF = r.json().get("id") if r.status_code == 201 else None
r = A.post(B + "/api/files/upload", data={"parent_id": str(PF)}, files={"file": ("invoice.xml", b"<Invoice/>\n")})
NID = (r.json().get("items") or [{}])[0].get("id") if r.ok else None
check(NID and sql("SELECT org_id FROM fs_nodes WHERE id=?", (NID,)) == [(PSI,)], "setup: a file of Psi " + r.text[:200])
sql("INSERT INTO doc_meta(node_id, org_id, ws, extracted, doc_date, created_at, updated_at) VALUES(?,?,?,?,?,?,?) "
    "ON CONFLICT(node_id) DO UPDATE SET org_id=excluded.org_id, extracted=excluded.extracted, doc_date=excluded.doc_date",
    (NID, PSI, f"o{PSI}", json.dumps({"_einv": {"number": "INV-1", "total": "119.00"}}), "2026-02-01", NOW, NOW), write=True)
A.patch(B + "/api/settings", json={"workspace": "private"})
r = A.delete(B + f"/api/admin/orgs/{PSI}")
check(r.status_code == 409 and (r.json().get("kept") or {}).get("einvoices") == 1 and r.json().get("retain_until"),
      "Psi (an e-invoice only): retired instead of deleted " + r.text[:300])
check(sql("SELECT 1 FROM orgs WHERE id=?", (PSI,)), "Psi: still there")

# ================================================================== a person without an organisation: as before
FID, Fr = freelancer(B, A, "frida", features=FEAT)  # freelancer-matrix: office
Fr.patch(B + "/api/settings", json={"workspace": "private"})
r = Fr.post(B + "/api/lists", json={"name": "Frida budget"})
FL = r.json().get("id") if r.ok else None
sql("INSERT INTO budget_entries(list_id, day, amount, title, created_at, updated_at) VALUES(?,?,?,?,?,?)", (FL, "2026-03-02", "-10", "Paper", NOW, NOW), write=True)
FE = sql("SELECT id FROM budget_entries WHERE list_id=?", (FL,))[0][0]
sql("INSERT INTO budget_files(entry_id, list_id, name, path, created_at) VALUES(?,?,?,?,?)", (FE, FL, "receipt.pdf", f"budget/{FL}/x.pdf", NOW), write=True)
r = Fr.get(B + "/api/retention/me")
check(r.ok and (r.json().get("counts") or {}).get("project_receipts") == 1, "frida: her project's receipt counts " + r.text[:300])
r = su_get(Fr, B + "/api/retention/me/export.zip")  # 2.223.2 C (#2871): the step-up (bundle 2.305)
check(r.ok and r.content[:2] == b"PK", f"frida: her retention export {r.status_code}")
GID, Gr = freelancer(B, A, "greta", features=FEAT)
r = A.delete(B + f"/api/users/{GID}")
check(r.ok and not sql("SELECT 1 FROM users WHERE id=?", (GID,)), "greta (no organisation, nothing kept): deleted as before " + r.text[:200])

print(f"p2239_c_loeschung: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
