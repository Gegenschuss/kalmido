#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.531.0 part C (#4317, audit #2425 F9 F10 F12 F17): what the account export holds and says it does not hold. Invented names only
(example.com). Persons without an organisation (freelancer_fixture), an export of gina imported by hanna:
 - F9/F10: the export page's state (GET /api/account/export) names what is not in the file, readable, before and after the
   export: the trashes, the tasks of the trash, the areas not yet in the export by name (never a table name); the manifest names
   the trashes too
 - F12: gina's family link (kim, a child account) and her connections (otto, paula) are in the file, the other person only by
   name and address hash; the import asks otto again (an open request, never a connection without him), names paula (no account
   hanna may see) and the family link (only an admin sets one); the undo takes the request back
 - F17: preview and result count the comments and files of a task in the trash on their own
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2531C_NOSTART=1 = the server already runs like that).
freelancer-matrix: own
usage: p2531_c_umzug_test.py <datadir>"""
import base64
import io
import json
import os
import sys
import zipfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, FAILS, OKS, check, su_get, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
TS = "2026-10-20T06:00:00+00:00"


def one(sql, args=()):
    r = kt.dbx(sql, args)
    return r[0][0] if r else None


def state_of(s, iid):
    j = s.get(B + f"/api/account/import/{iid}").json()
    return j if j.get("state") not in ("checking", "running", "upload") else None


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "kalmido-account.zip"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid, until(lambda: state_of(s, iid), 180) or {}


kt.fresh(env={"KALMIDO_SECRET_KEY": KEY}, prefix="P2531C")
A = kt.setup()
GID, G = freelancer(B, A, "gina")
OID, _ = freelancer(B, A, "otto")
PID, _ = freelancer(B, A, "paula")
KID, _ = freelancer(B, A, "kim")
HID, H = freelancer(B, A, "hanna")
lo, hi = sorted((GID, OID))
kt.dbx("INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?,?,?)", (lo, hi, TS))
lo, hi = sorted((GID, PID))
kt.dbx("INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?,?,?)", (lo, hi, TS))
# 2.574.0 (#4556): the import asks only someone findable in the connection search (review B1), like a request by hand
kt.dbx("INSERT INTO disc_profiles(user_id, email, confirmed_at, created_at) SELECT id, lower(email), ?, ? FROM users WHERE id=?", (TS, TS, OID))
kt.dbx("UPDATE users SET kid=1 WHERE id=?", (KID,))
kt.dbx("INSERT INTO kid_parents(kid_id, parent_id) VALUES(?,?)", (KID, GID))

# ---- F9 / F10: before the export
j = G.get(B + "/api/account/export").json()
NI = j.get("not_included") or []
txt = " | ".join(NI)
check(j.get("state") == "none" and NI, f"F9 the export page names what is not in the file before an export: {j.get('state')} {txt[:200]}")
check(any(x.startswith("the trash of your files, knowledge pages, tables, address books") for x in NI), f"F10 the trashes are named: {txt[:400]}")
check(any(x.startswith("tasks in the trash with their comments and files") for x in NI), f"F10 the tasks of the trash are named: {txt[:400]}")
later = next((x for x in NI if x.startswith("not yet in the file: ")), "")
check("history of knowledge pages" in later and "rewards of the family" in later, f"F9 the areas not yet in the export by name: {later[:300]}")
check("wiki_versions" not in txt and "obj_versions" not in txt and "kid_rewards" not in txt and "conn_requests" not in txt, f"F9 no table name on the page: {txt[:300]}")
check(len(NI) == len(set(NI)), f"F9 no line twice: {len(NI)} {len(set(NI))}")

# ---- F17: a task in the trash with a comment and a file
L = G.post(B + "/api/lists", json={"name": "Umzug Papierkorb"}).json()["id"]
T = G.post(B + "/api/tasks", json={"title": "Weg damit", "list_id": L}).json()["id"]
check(G.post(B + f"/api/tasks/{T}/comments", json={"body": "Kommentar im Papierkorb"}).ok, "a comment")
check(G.post(B + f"/api/tasks/{T}/attachments", files={"file": ("note.txt", b"im Papierkorb\n", "text/plain")}).ok, "a file")
check(G.delete(B + f"/api/tasks/{T}").ok, "the task goes into the trash")

# ---- the export
check(G.post(B + "/api/account/export").status_code == 202, "the export starts")
j = until(lambda: (lambda x: x if x.get("state") != "running" else None)(G.get(B + "/api/account/export").json()), 180) or {}
check(j.get("state") == "done" and j.get("not_included") == NI, f"F9 ... and after it: {j.get('state')} {len(j.get('not_included') or [])}")
ZIP = su_get(G, B + "/api/account/export/file").content
zf = zipfile.ZipFile(io.BytesIO(ZIP))
man = json.loads(zf.read("manifest.json"))
check(any(x.startswith("the trash of your files") for x in man.get("not_included") or []), "F10 the manifest names the trashes")
check(any("conn_requests" in x for x in man.get("not_included") or []), "F12 the manifest names the open connection requests")
kp = json.loads(zf.read("data/kid_parents.json"))
cl = json.loads(zf.read("data/conn_links.json"))
check(len(kp) == 1 and kp[0].get("role") == "kid" and kp[0].get("name") == "Kim" and len(kp[0].get("email_hash") or "") == 64
      and "email" not in kp[0], f"F12 the family link is in the file, the child by name and hash: {kp}")
check(sorted(r.get("name") for r in cl) == ["Otto", "Paula"] and all(len(r.get("email_hash") or "") == 64 and "email" not in r for r in cl),
      f"F12 the connections are in the file, by name and hash: {cl}")
check("kim@example.com" not in json.dumps(kp) and "otto@example.com" not in json.dumps(cl), "F12 never another person's address")

# ---- the import by hanna (paula has no account hanna may see any more)
kt.dbx("UPDATE users SET disabled=1 WHERE id=?", (PID,))
iid, j = upload(H, ZIP)
check(j.get("state") == "preview", f"preview {j.get('state')} {j.get('error')}")
nt = {x.get("what"): x.get("count") for x in (j.get("preview") or {}).get("not_taken") or []}
check(nt.get("Tasks in the trash") == 1 and nt.get("Comments on tasks in the trash") == 1 and nt.get("Files of tasks in the trash") == 1,
      f"F17 the preview counts what hangs on the task in the trash: {nt}")
check("kid_parents" not in nt and "conn_links" not in nt, f"F12 both parts are read by the import: {nt}")
r = H.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}})
check(r.status_code == 202, f"the run starts {r.status_code} {r.text[:200]}")
j = until(lambda: state_of(H, iid), 180) or {}
check(j.get("state") == "done", f"the import is done {j.get('state')} {j.get('error')}")
RES = j.get("result") or {}
W = [x.get("text", "") for x in RES.get("warnings") or []]
left = next((w for w in W if w.startswith("These areas stay on the old server")), "")  # the result names them in this warning
check("Comments on tasks in the trash (1)" in left and "Files of tasks in the trash (1)" in left, f"F17 ... and the result: {left[:300]}")
check(any(w.startswith("Connections asked again") and "Otto" in w and "Paula" not in w for w in W), f"F12 otto is asked again: {W}")
check(any(w.startswith("Connections that do not move along") and "Paula" in w for w in W), f"F12 paula is named: {W}")
check(any(w.startswith("Family links do not move along") and "Kim" in w for w in W), f"F12 the family link is named: {W}")
check(one("SELECT status FROM conn_requests WHERE from_id=? AND to_id=?", (HID, OID)) == "open", "F12 an open request to otto, he confirms")
check(not one("SELECT 1 FROM conn_links WHERE ? IN (a_id, b_id)", (HID,)), "F12 never a connection without the other person")
check(not one("SELECT 1 FROM conn_requests WHERE from_id=? AND to_id=?", (HID, PID)), "F12 no request to paula")
check(not one("SELECT 1 FROM kid_parents WHERE ? IN (kid_id, parent_id)", (HID,)), "F12 no family link made by the import")

# ---- the undo takes the request back
IMP = RES.get("import_id")
check(IMP and H.post(B + f"/api/imports/{IMP}/undo", json={}).ok, "the undo")
# 2.574.0 (#4556): withdrawn (wd_open) as by hand instead of deleted (review B2)
check(until(lambda: one("SELECT status FROM conn_requests WHERE from_id=? AND to_id=?", (HID, OID)) == "wd_open", 30),
      "F12 the undo takes the request that still waits back")

print(f"p2531_c_umzug: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
