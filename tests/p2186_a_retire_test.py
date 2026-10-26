#!/usr/bin/env python3
"""2.186.0 API tests, part A (#2599): a retired organisation, own container (start.sh, mode workspaces, server key).
Invented companies and figures only. freelancer-matrix: office  tenant-matrix: org
 - an organisation with a finalised invoice is retired: its admins of that moment are noted (orgs.retired_admins), no
   waiver is noted; its former admin (no instance admin, no member any more) finds it under GET /api/orgs "retired", starts
   its export and downloads the retention export; an instance admin who was not its admin, a former member and the
   instance admin's delete-info get no export (the organisation boundary)
 - after the period it goes without an export step, noted honestly as "expired" (no waiver)
 - a person without organisation with a finalised invoice (self-hosting): the deletion retires the personal office without
   an export step and without a waiver row (delete-info retention.state = retire)
 - an organisation whose folder lies in the trash with a file inside: the file counts as trash, the deletion goes
usage: p2186_a_retire_test.py <datadir>"""
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess, su_get  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,files,docs,office,clients"
O = "/api/office"
KEYENV = " -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY=" + "A" * 43 + "="


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


def lock_doc(did, day="2026-03-02", number="RE-2026-001"):
    """A finalised document (the state the finalising leaves; finalising itself is tested in the office suites)."""
    sql("UPDATE office_docs SET locked_at=?, status='issued', number=?, date=? WHERE id=?",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), number, day, did), write=True)


if os.environ.get("P2186A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces" + KEYENV)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n, adm in (("dora", "Dora Director", False), ("bob", "Bob Member", False), ("erik", "Erik Server", True)):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com", "is_admin": adm})
    assert r.ok, r.text
ALICE = A.get(B + "/api/me").json()["id"]
Do, Bo, Er = sess("dora"), sess("bob"), sess("erik")
DORA = Do.get(B + "/api/me").json()["id"]
check(Er.get(B + "/api/me").json().get("is_admin") is True and not Do.get(B + "/api/me").json().get("is_admin"), "setup: erik is an instance admin, dora not")
for s in (A, Do, Bo, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})

# ================================================================== a retired organisation: only its former admins export it
DEL = A.post(B + "/api/admin/orgs", json={"name": "Delta Film", "admin_id": DORA}).json()["id"]
assert Do.put(B + f"/api/orgs/{DEL}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (Do, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{DEL}"})
r = Do.post(B + O + "/docs", json={"project_title": "Event film"})
DDOC = r.json().get("id") if r.status_code == 201 else None
check(DDOC, "Delta: a document " + r.text[:160])
lock_doc(DDOC, "2025-11-20", "RE-2025-042")
r = A.delete(B + f"/api/admin/orgs/{DEL}", params={"confirm": "1"})
check(r.ok and r.json().get("retired") is True and r.json().get("retain_until") == "2035-12-31", "Delta: retired " + r.text[:200])
if not r.ok:
    app_log()
check(sql("SELECT retired_admins FROM orgs WHERE id=?", (DEL,)) == [(str(DORA),)], "Delta: its admin of that moment is noted")
check(not sql("SELECT 1 FROM retention_log WHERE subject=?", (f"org:{DEL}",)), "Delta: retired, no waiver noted")
check(not sql("SELECT 1 FROM org_members WHERE org_id=?", (DEL,)), "Delta: nobody is a member any more")

ret = Do.get(B + "/api/orgs").json().get("retired") or []
check([(o["id"], o["name"], o["retain_until"]) for o in ret] == [(DEL, "Delta Film", "2035-12-31")], f"dora: Delta under retired {ret}")
for who, s in (("bob", Bo), ("alice", A), ("erik", Er)):
    check(not any(o["id"] == DEL for o in (s.get(B + "/api/orgs").json().get("retired") or [])), f"{who}: Delta not under retired")

# the former admin: the organisation export and the retention export
r = Do.get(B + f"/api/orgs/{DEL}/export")
check(r.ok and r.json().get("enabled") is True, f"dora: the export state of retired Delta {r.status_code} {r.text[:160]}")
r = Do.post(B + f"/api/orgs/{DEL}/export")
check(r.status_code == 202, f"dora: starts the export {r.status_code} {r.text[:160]}")
for _ in range(480):
    if Do.get(B + f"/api/orgs/{DEL}/export").json().get("state") != "running":
        break
    time.sleep(0.25)
r = Do.get(B + f"/api/orgs/{DEL}/export/file")
check(r.ok and r.content[:8] == b"KALMIDO-", f"dora: downloads the archive {r.status_code} {r.content[:60]}")
r = Do.get(B + f"/api/retention/org/{DEL}")
check(r.ok and r.json().get("can_export") is True and r.json().get("counts", {}).get("documents") == 1, "dora: the retention info " + r.text[:300])
r = su_get(Do, B + f"/api/retention/org/{DEL}/export.zip")  # 2.223.2 C (#2871): the download needs the step-up (kt.su_get)
check(r.ok and r.content[:2] == b"PK", f"dora: the retention export {r.status_code}")

# nobody else: not the instance admins (they were not its admins), not the former member
for who, s in (("alice", A), ("erik", Er)):
    check(s.get(B + f"/api/orgs/{DEL}/export").status_code in (403, 404) and s.post(B + f"/api/orgs/{DEL}/export").status_code in (403, 404),
          f"{who} (instance admin, never its admin): no organisation export")
    r = s.get(B + f"/api/retention/org/{DEL}")
    check(r.ok and r.json().get("can_export") is False and "url" not in r.json() and "counts" not in r.json(), f"{who}: retention info without export " + r.text[:200])
    check(s.get(B + f"/api/retention/org/{DEL}/export.zip").status_code == 404, f"{who}: no retention ZIP")
    di = s.get(B + f"/api/admin/orgs/{DEL}/delete-info").json()
    check(di.get("retired") is True and di.get("can_export") is False, f"{who}: delete-info offers no export {di}")
check(Bo.get(B + f"/api/orgs/{DEL}/export").status_code in (403, 404) and Bo.get(B + f"/api/retention/org/{DEL}/export.zip").status_code == 404,
      "bob (former member): no export")
# an organisation retired before 2.186 (no noted admins): the instance admins as before
# 2.239.0 (#2943): ... but only its retention export (the records kept by law), never the whole organisation's export
sql("UPDATE orgs SET retired_admins=NULL WHERE id=?", (DEL,), write=True)
check(A.get(B + f"/api/orgs/{DEL}/export").status_code in (403, 404) and su_get(A, B + f"/api/retention/org/{DEL}/export.zip").ok
      and Do.get(B + f"/api/orgs/{DEL}/export").status_code in (403, 404),
      "retired before 2.186: the instance admin gets the retention export only")
di = A.get(B + f"/api/admin/orgs/{DEL}/delete-info").json()
check(di.get("can_export") is False and di.get("can_retention") is True, f"retired before 2.186: delete-info offers the retention export only {di}")
sql("UPDATE orgs SET retired_admins=? WHERE id=?", (str(DORA), DEL), write=True)
# review M3: none of the noted admins left = the instance admins export it (else nobody could for years)
# 2.239.0 (#2943): the retention export only
for v in ("", "999999"):
    sql("UPDATE orgs SET retired_admins=? WHERE id=?", (v, DEL), write=True)
    check(su_get(A, B + f"/api/retention/org/{DEL}/export.zip").ok and A.post(B + f"/api/orgs/{DEL}/export").status_code in (403, 404),
          f"retired_admins {v!r}: the instance admin gets the retention export, not the organisation export")
sql("UPDATE orgs SET retired_admins=? WHERE id=?", (str(DORA), DEL), write=True)

# still within the period: not deleted
r = A.delete(B + f"/api/admin/orgs/{DEL}")
check(r.status_code == 409 and "2035-12-31" in r.text, "Delta: not deleted before the period ends " + r.text[:160])
# after the period: no export step, noted as expired (never as a waiver)
sql("UPDATE orgs SET retain_until='2020-12-31' WHERE id=?", (DEL,), write=True)
# 2.239.0 (#2874): the manual delete computes the period anew (like the watchdog): the invoice must be old enough, too
sql("UPDATE office_docs SET date='2013-03-02' WHERE id=?", (DDOC,), write=True)
r = A.get(B + f"/api/retention/org/{DEL}")
check(r.ok and r.json().get("state") == "expired", "after the period: retention state expired " + r.text[:200])
r = A.delete(B + f"/api/admin/orgs/{DEL}")
check(r.ok and not sql("SELECT 1 FROM orgs WHERE id=?", (DEL,)) and not sql("SELECT 1 FROM office_docs WHERE id=?", (DDOC,)),
      "after the period: deleted without an export step " + r.text[:200])
if not r.ok:
    app_log()
kinds = [k for (k,) in sql("SELECT kind FROM retention_log WHERE subject=? ORDER BY id", (f"org:{DEL}",))]
check(kinds[-1:] == ["expired"] and "waiver" not in kinds, f"after the period: noted as expired, no waiver {kinds}")

# ================================================================== self-hosting: a person's office is retired without a waiver
FID, Fr = freelancer(B, A, "frida", features=FEAT)  # freelancer-matrix: office
r = Fr.post(B + O + "/docs", json={"project_title": "Corporate film"})
FDOC = r.json().get("id") if r.status_code == 201 else None
check(FDOC, "frida: a document " + r.text[:160])
lock_doc(FDOC)
info = A.get(B + f"/api/users/{FID}/delete-info").json()
ri = info.get("retention") or {}
check(ri.get("needed") is True and ri.get("state") == "retire" and (info.get("purge") or {}).get("office") == "keep",
      f"frida: delete-info says retired, no export step {ri}")
r = A.delete(B + f"/api/users/{FID}")
check(r.ok and not sql("SELECT 1 FROM users WHERE id=?", (FID,)), "frida: deleted without a step (the office is retired) " + r.text[:200])
if not r.ok:
    app_log()
check(sql("SELECT 1 FROM office_docs WHERE id=?", (FDOC,)) and not sql("SELECT 1 FROM retention_log WHERE subject=?", (f"user:{FID}",)),
      "frida: the invoice is kept, no waiver noted")

# 2.186.0 review M1: a private receipt kept only by a lock of #2600 (doc_meta.kept_until) moves into the retired office
# instead of blocking the deletion with a 409
HID, Ha = freelancer(B, A, "hanna", features=FEAT)  # freelancer-matrix: office
r = Ha.post(B + "/api/files/upload", files={"file": ("receipt.txt", b"a receipt\n")})
HN = (r.json().get("items") or [{}])[0].get("id") if r.ok else None
check(HN, "hanna: a private file " + r.text[:160])
now = datetime.now(timezone.utc).isoformat()
sql("INSERT INTO doc_meta(node_id, ws, created_at, updated_at, kept_until) VALUES(?,?,?,?,?) "
    "ON CONFLICT(node_id) DO UPDATE SET kept_until=excluded.kept_until", (HN, f"u{HID}", now, now, "2034-12-31"), write=True)
r = A.delete(B + f"/api/users/{HID}")
check(r.ok and not sql("SELECT 1 FROM users WHERE id=?", (HID,)), "hanna: deleted although a receipt is kept " + r.text[:200])
if not r.ok:
    app_log()
kept = sql("SELECT n.org_id, o.retired_at FROM fs_nodes n JOIN orgs o ON o.id=n.org_id WHERE n.id=?", (HN,))
check(kept and kept[0][1], f"hanna: the kept receipt went into the retired office {kept}")

# ================================================================== a folder in the trash: its files are trash too
ECH = A.post(B + "/api/admin/orgs", json={"name": "Echo", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ECH}"})
r = A.post(B + "/api/files/folders", json={"name": "Receipts", "space": f"org:{ECH}"})
FOLD = r.json().get("id") if r.status_code == 201 else None
check(FOLD, "Echo: a folder " + r.text[:160])
r = A.post(B + "/api/files/upload", data={"parent_id": str(FOLD)}, files={"file": ("note.txt", b"just a note\n")})
check(r.ok and sql("SELECT COUNT(*) FROM fs_nodes WHERE org_id=? AND deleted_at IS NULL", (ECH,))[0][0] == 2, "Echo: a file in it " + r.text[:160])
r = A.delete(B + f"/api/admin/orgs/{ECH}")
check(r.status_code == 409 and "2 folders and files" in r.text, "Echo: live folder + file block the deletion " + r.text[:160])
check(A.delete(B + f"/api/files/nodes/{FOLD}").ok, "Echo: the folder into the trash")
check(sql("SELECT COUNT(*) FROM fs_nodes WHERE org_id=? AND deleted_at IS NULL", (ECH,))[0][0] == 1, "setup: only the folder carries deleted_at")
A.patch(B + "/api/settings", json={"workspace": "private"})
r = A.delete(B + f"/api/admin/orgs/{ECH}")
check(r.ok and not sql("SELECT 1 FROM orgs WHERE id=?", (ECH,)), "Echo: the file in the trashed folder no longer blocks the deletion " + r.text[:200])
if not r.ok:
    app_log()

print(f"p2186_a_retire: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
