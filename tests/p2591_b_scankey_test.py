#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.591.0 B (#4886): edit a scan inbox afterwards - name, folder, a year more. Invented names only, generated file contents.
freelancer-matrix: files
 - a person without an organisation renames her inbox and moves it to another folder: the key stays the same (same hash),
   an upload with the old key lands in the new folder; back to the documents directly with parent_id null
 - refused: somebody else's inbox (404, also for a member of the same organisation), a folder of somebody else, readable
   through a share only (400, the share between bob and carol), a folder in the trash (400), the place (ws / org) as a field (400), an empty name (400, also in
   German), an empty body (400), extend not a boolean (400)
 - an expired inbox (upload 401) with extend: true runs a year from now and takes uploads again
 - an inbox of an organisation: a folder of it the person may add to is fine (an edit share), one she only reads or not at all is
   not (400), nor a folder of her own documents (400); after the
   person left the organisation 403
usage: p2591_b_scankey_test.py <datadir>      (P2591B_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, check, sess  # noqa: E402
from freelancer_fixture import freelancer, org_join  # noqa: E402

V = B + "/api/v1"
kt.fresh(prefix="P2591B")
A = kt.setup()


def bearer(tok):
    return {"Authorization": "Bearer " + tok}


def up(tok, name="scan.txt", body=b"Rechnung Beispiel 4886"):
    return requests.post(V + "/documents", headers=bearer(tok), files={"file": (name, body, "text/plain")})


def key_of(r):
    raw = r.json().get("code", "kalmido-scan:1:")[len("kalmido-scan:1:"):]
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))).get("key", "")


def parent(nid):
    r = kt.dbx("SELECT parent_id, org_id FROM fs_nodes WHERE id=?", (nid,))
    return r[0] if r else (None, None)


def first_doc(s, ws):
    r = s.post(B + "/api/docs", files={"files": ("start.txt", b"Start Beispiel", "text/plain")}, data={"ws": ws})
    assert r.ok, r.text
    return s.get(B + f"/api/docs/settings?ws={ws}").json()["root_id"]


def folder(s, name, pid):
    r = s.post(B + "/api/files/folders", json={"name": name, "parent_id": pid})
    assert r.ok, r.text
    return r.json()["id"]


def listed(s, ws, kid):
    return next((k for k in s.get(B + f"/api/docs/scan-keys?ws={ws}").json()["keys"] if k["id"] == kid), {})


# ---- setup: alice (instance admin), Alpha = bob (admin) + carol (member), frida without an organisation
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ids["bob"]})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG), "setup: carol joins Alpha")
FRIDA, Fr = freelancer(B, A)
for s in (Bo, Ca, Fr):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "files,docs,comments,collab"})

# ==== a person without an organisation (freelancer-matrix: files)
ROOT = first_doc(Fr, "private")
F1, F2 = folder(Fr, "Belege", ROOT), folder(Fr, "Vertraege", ROOT)
r = Fr.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": "Scanner", "parent_id": F1})
check(r.status_code == 201, f"setup: frida's inbox into Belege {r.text[:200]}")
KID, KEY = r.json().get("id"), key_of(r)
HASH = kt.dbx("SELECT token_hash FROM api_tokens WHERE id=?", (KID,))[0][0]
check(parent(up(KEY).json().get("id"))[0] == F1, "before: the upload lands in Belege")

r = Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"name": "Scanner Flur", "parent_id": F2})
check(r.ok and r.json().get("name") == "Scanner Flur" and r.json().get("parent_id") == F2 and "Vertraege" in r.json().get("target", ""),
      f"#4886: name and folder changed, the answer is the listed row {r.status_code} {r.text[:200]}")
check(kt.dbx("SELECT token_hash FROM api_tokens WHERE id=?", (KID,))[0][0] == HASH, "#4886: the key stays the same")
r = up(KEY, "nachher.txt")
check(r.status_code == 201 and parent(r.json().get("id"))[0] == F2, f"#4886: the old key uploads into the new folder {r.status_code} {r.text[:160]}")
r = requests.get(V + "/documents/upload-target", headers=bearer(KEY))
check(r.ok and r.json().get("name") == "Scanner Flur" and r.json().get("target", "").endswith("/ Vertraege"), f"upload-target follows {r.text[:160]}")
r = Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"parent_id": None})
check(r.ok and r.json().get("parent_id") is None and parent(up(KEY).json().get("id"))[0] == ROOT, f"#4886: back to the documents directly {r.text[:160]}")

# ---- refused
check(Ca.patch(B + f"/api/docs/scan-keys/{KID}", json={"name": "fremd"}).status_code == 404, "#4886: somebody else's inbox: 404")
check(listed(Fr, "private", KID).get("name") == "Scanner Flur", "nothing changed by the refused call")
ROOTC = first_doc(Ca, "private")
CF = folder(Ca, "Carol privat", ROOTC)
r = Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"parent_id": CF})
check(r.status_code == 400, f"#4886: a folder of somebody else: 400 {r.status_code} {r.text[:160]}")
check(Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"ws": f"org:{ORG}"}).status_code == 400, "#4886: the place is no field: 400")
check(Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"org": ORG}).status_code == 400, "#4886: org is no field either")
check(Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"parent_id": "x"}).status_code == 400, "parent_id not a number: 400")
check(Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"extend": "yes"}).status_code == 400, "extend not a boolean: 400")
check(Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={}).status_code == 400, "an empty body: 400")
r = Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"name": "  "})
check(r.status_code == 400 and "Name missing" in r.text, f"an empty name: 400 {r.text[:160]}")
Fr.patch(B + "/api/settings", json={"lang": "de"})
r = Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"name": ""})
check(r.status_code == 400 and "Name fehlt" in r.text, f"in German too {r.text[:160]}")
Fr.patch(B + "/api/settings", json={"lang": "en"})
check(Fr.delete(B + f"/api/files/nodes/{F1}").ok, "setup: Belege into the trash")
r = Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"parent_id": F1})
check(r.status_code == 400, f"#4886: a folder in the trash: 400 {r.status_code}")
check(parent(up(KEY).json().get("id"))[0] == ROOT, "the inbox still uploads into the documents directly")

# ---- expired + a year more
past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
kt.dbx("UPDATE api_tokens SET expires_at=? WHERE id=?", (past, KID))
check(up(KEY).status_code == 401 and listed(Fr, "private", KID).get("expired") is True, "setup: the inbox ran out (401, listed as expired)")
r = Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"name": "Scanner Flur", "extend": False})
check(r.ok and r.json().get("expired") is True, f"#4886: extend false changes nothing about the date {r.status_code} {r.text[:160]}")
check(Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"extend": False}).status_code == 400, "extend false alone: nothing to change (400)")
r = Fr.patch(B + f"/api/docs/scan-keys/{KID}", json={"extend": True})
try:
    days = (datetime.fromisoformat(r.json().get("expires_at", "").replace("Z", "+00:00")) - datetime.now(timezone.utc)).days
except ValueError:
    days = -1
check(r.ok and r.json().get("expired") is False and 363 <= days <= 366, f"#4886: extended it runs a year from now {days} {r.text[:200]}")
r = up(KEY, "wieder.txt")
check(r.status_code == 201, f"#4886: the extended key uploads again {r.status_code} {r.text[:160]}")

# ==== an organisation: carol's inbox of Alpha
ORT = first_doc(Bo, f"org:{ORG}")
OF = folder(Bo, "Eingang Alpha", ORT)
r = Ca.post(B + "/api/docs/scan-keys", json={"ws": f"org:{ORG}", "name": "Alpha Scanner"})
check(r.status_code == 201, f"setup: carol's inbox of Alpha {r.text[:160]}")
K2ID, K2 = r.json().get("id"), key_of(r)
check(Bo.patch(B + f"/api/docs/scan-keys/{K2ID}", json={"name": "chef"}).status_code == 404, "#4886: not even the organisation's admin edits carol's inbox")
r = Ca.patch(B + f"/api/docs/scan-keys/{K2ID}", json={"parent_id": CF})
check(r.status_code == 400, f"#4886: a folder of her own documents for the inbox of Alpha: 400 {r.status_code}")
r = Ca.patch(B + f"/api/docs/scan-keys/{K2ID}", json={"parent_id": OF})
check(r.status_code == 400, f"#4886: a folder of Alpha carol may not add to: 400 {r.status_code}")
check(Bo.post(B + f"/api/files/nodes/{OF}/shares", json={"user_id": ids["carol"], "role": "view"}).status_code == 201, "setup: bob shares it with carol to read")
check(Ca.patch(B + f"/api/docs/scan-keys/{K2ID}", json={"parent_id": OF}).status_code == 400, "#4886: readable only: still 400")
check(Bo.post(B + f"/api/files/nodes/{OF}/shares", json={"user_id": ids["carol"], "role": "edit"}).status_code == 201, "setup: bob lets carol add to it")
r = Ca.patch(B + f"/api/docs/scan-keys/{K2ID}", json={"parent_id": OF})
check(r.ok and r.json().get("parent_id") == OF, f"#4886: another folder of Alpha is fine {r.status_code} {r.text[:160]}")
r = up(K2, "alpha.txt")
check(r.status_code == 201 and parent(r.json().get("id")) == (OF, ORG), f"the upload lands in Alpha's folder {r.text[:160]}")
ROOTB = first_doc(Bo, "private")
BF = folder(Bo, "Bob privat", ROOTB)
r = Bo.post(B + f"/api/files/nodes/{BF}/shares", json={"user_id": ids["carol"], "role": "view"})
check(r.status_code == 201, f"setup: bob shares a folder of his own documents with carol to read {r.status_code} {r.text[:160]}")
r = Ca.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": "Carol Scanner"})
K3ID = r.json().get("id")
r = Ca.patch(B + f"/api/docs/scan-keys/{K3ID}", json={"parent_id": BF})
check(r.status_code == 400, f"#4886: a folder of somebody else, readable through a share only: 400 {r.status_code} {r.text[:160]}")
check(listed(Ca, f"org:{ORG}", K2ID).get("parent_id") == OF and listed(Ca, "private", K2ID) == {}, "still listed only in Alpha's settings")
check(Bo.delete(B + f"/api/orgs/{ORG}/members/{ids['carol']}").ok, "setup: bob takes carol out of Alpha")
r = Ca.patch(B + f"/api/docs/scan-keys/{K2ID}", json={"name": "danach"})
check(r.status_code == 403, f"#4886: after leaving Alpha its inbox cannot be edited: 403 {r.status_code}")

sys.exit(kt.done("p2591_b_scankey"))
