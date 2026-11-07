#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.649.0 A (#5049): a public link of the file store ("Ablage") gives only what its creator may read in the app -- the
receipts lock (office groups, area receipts) on the link's listing, download, preview and ZIP. Invented names only.
 - bob (member, office group "Staff": receipts "own") owns a folder holding a colleague's receipt (a picture), his own
   receipt and a plain file; in the app he does not see the colleague's receipt
 - bob's link: the folder page lists his receipt and the plain file, not the colleague's; its download and preview 404;
   the ZIP leaves it out; his own receipt downloads (200)
 - alice's (the organisation admin) link on the same folder: everything, the colleague's receipt downloads (the lock follows
   the creator, not the folder)
 - a person without an organisation (freelancer-matrix: files): her receipt in her own folder, her link lists and serves it
usage: p2649_a_rights_test.py <datadir>   (P2649A_NOSTART=1: against a running instance on KALMIDO_TEST_PORT)"""
import io
import os
import re
import subprocess
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import check, done, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
FEAT = "cal,comments,collab,office,clients,docs,files"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
IP = ["198.51.100.20"]

if not (os.environ.get("P2649A_NOSTART") or os.environ.get("KMT_NOSTART")):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Example", "admin_id": ALICE}).json()["id"]
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
check(A.put(B + f"/api/office/rights/people/{BOB}", json={"groups": ["tpl:staff"]}).ok, "setup: bob in the office group Staff (receipts own)")


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        cur = c.execute(q, args)
        if write:
            c.commit()
            return None
        return cur.fetchall()
    finally:
        c.close()


def folder(s, name, space):
    r = s.post(B + "/api/files/folders", json={"name": name, "space": space})
    assert r.status_code == 201, (name, r.status_code, r.text)
    return r.json()["id"]


def up(s, name, data, parent, mime):
    r = s.post(B + "/api/files/upload", data={"parent_id": str(parent)}, files={"file": (name, data, mime)})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def receipt(nid, org, ws, by):
    sql("INSERT INTO rc_receipts(node_id, org_id, ws, category, set_by, set_at) VALUES(?,?,?,?,?,?)",
        (nid, org, ws, "Software", by, "2026-11-01T00:00:00Z"), write=True)


def link(s, nid):
    r = s.post(B + f"/api/files/nodes/{nid}/ext-links", json={})
    check(r.ok and r.json().get("links"), f"setup: a public link on the folder ({r.status_code} {r.text[:160]})")
    return re.sub(r"^https?://[^/]+", "", r.json()["links"][-1]["url"])


def pub(path):
    """A visitor without an account (own cookie jar, own address)."""
    IP[0] = f"198.51.100.{int(IP[0].rsplit('.', 1)[1]) + 1}"
    return requests.get(B + path, headers={"X-Forwarded-For": IP[0]}, allow_redirects=False, timeout=30)


def zip_names(path):
    r = pub(path + "/zip")
    if r.status_code != 200:
        return r.status_code
    return sorted(n.rsplit("/", 1)[-1] for n in zipfile.ZipFile(io.BytesIO(r.content)).namelist() if not n.endswith("/"))  # names without the folder


# ---------------------------------------------------------------- bob's folder: a colleague's receipt, his own, a plain file
BOX = folder(Bo, "Bob box", f"org:{ORG}")
RA = up(A, "colleague-receipt.png", PNG, BOX, "image/png")
RB = up(Bo, "bob-receipt.txt", b"Receipt Bob 12,00 EUR\n", BOX, "text/plain")
PL = up(A, "plain-notes.txt", b"Meeting notes\n", BOX, "text/plain")
receipt(RA, ORG, f"o{ORG}", ALICE)
receipt(RB, ORG, f"o{ORG}", BOB)
kids = Bo.get(B + "/api/files", params={"parent": BOX})
seen = [x["id"] for x in kids.json().get("items", [])] if kids.ok else None
check(seen is not None and RA not in seen and RB in seen and PL in seen,
      f"setup: in the app bob does not see the colleague's receipt ({seen}; {RA} {RB} {PL})")

BP = link(Bo, BOX)
r = pub(BP)
check(r.status_code == 200 and "bob-receipt.txt" in r.text and "plain-notes.txt" in r.text,
      f"bob's link: the page lists his receipt and the plain file ({r.status_code})")
check("colleague-receipt.png" not in r.text, "#5049 bob's link: the colleague's receipt is not listed")
check(pub(f"{BP}/d/{RA}").status_code == 404, "#5049 bob's link: the colleague's receipt does not download (404)")
check(pub(f"{BP}/v/{RA}").status_code == 404, "#5049 bob's link: no preview of it either (404)")
z = zip_names(BP)
check(isinstance(z, list) and "bob-receipt.txt" in z and "plain-notes.txt" in z and "colleague-receipt.png" not in z,
      f"#5049 bob's link: the ZIP leaves it out ({z})")
r = pub(f"{BP}/d/{RB}")
check(r.status_code == 200 and r.content == b"Receipt Bob 12,00 EUR\n", f"bob's link: his own receipt downloads ({r.status_code})")
check(pub(f"{BP}/d/{PL}").status_code == 200, "bob's link: the plain file downloads")

# ---------------------------------------------------------------- the admin's link on the same folder: everything
AP = link(A, BOX)
r = pub(AP)
check(r.status_code == 200 and "colleague-receipt.png" in r.text and "bob-receipt.txt" in r.text,
      f"alice's link (admin): the page lists both receipts ({r.status_code})")
r = pub(f"{AP}/d/{RA}")
check(r.status_code == 200 and r.content == PNG, f"alice's link: the colleague's receipt downloads ({r.status_code})")
check(pub(f"{AP}/v/{RA}").status_code == 200, "alice's link: its preview")
z = zip_names(AP)
check(isinstance(z, list) and "colleague-receipt.png" in z and "bob-receipt.txt" in z, f"alice's link: the ZIP has both ({z})")

# ---------------------------------------------------------------- a person without an organisation: as before
# freelancer-matrix: files
FID, Fr = freelancer(B, A, features=FEAT)
FB = folder(Fr, "Frida box", "private")
FR = up(Fr, "frida-receipt.png", PNG, FB, "image/png")
receipt(FR, None, "private", FID)
FP = link(Fr, FB)
r = pub(FP)
check(r.status_code == 200 and "frida-receipt.png" in r.text, f"freelancer's link: her receipt is listed ({r.status_code})")
check(pub(f"{FP}/d/{FR}").status_code == 200 and pub(f"{FP}/v/{FR}").status_code == 200, "freelancer's link: download and preview")
z = zip_names(FP)
check(isinstance(z, list) and "frida-receipt.png" in z, f"freelancer's link: the ZIP has it ({z})")

sys.exit(done("p2649_a_rights"))
