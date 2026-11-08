#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.663.0 part C API test (#4200): the open table's poll asks with its etag first (GET /api/sheets/<id>?etag=...).
Invented names only.
 - GET /api/sheets/<id> carries an etag; the same etag back -> only {unchanged: true, etag}, no cells
 - a cell written -> the old etag gets the whole sheet with a new etag
 - a Kalmido value (=task.<id>.title) that changes with the task, not with the table's rev: the old etag gets the whole sheet
 - presence of another person in an organisation table changes the answer too (new etag for the reader)
 - rights as the route itself: another person gets 404 with or without the etag, never {unchanged}
All first as a person without an organisation (frida), then an organisation table of alice read by bob.
freelancer-matrix: sheets
usage: p2663_c_sheet_etag_test.py <datadir>      (a fresh container; P2663CS_NOSTART=1 = the server already runs)"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402

kt.fresh(prefix="P2663CS")
H = {"X-Requested-With": "kalmido"}
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "sheets,collab,comments", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": "sheets,collab,comments", "tour": "done"})
FID, Fr = freelancer(B, A)


def get(s, sid, etag=None):
    return s.get(B + f"/api/sheets/{sid}", params={"etag": etag} if etag else None)


def first_cell(s, sid):
    d = get(s, sid).json()
    rows = sorted(d["rows"], key=lambda x: x["pos"])
    cols = sorted(d["columns"], key=lambda x: x["pos"])
    return rows[0]["id"], cols[0]["id"], rows[1]["id"]


# ---- a person without an organisation, her private table
r = Fr.post(B + "/api/sheets", json={"title": "Fence budget", "space": "private"})
check(r.status_code == 201, "frida: a private table " + r.text[:200])
SID = r.json()["id"]
R0, C0, R1 = first_cell(Fr, SID)
check(Fr.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"row_id": R0, "col_id": C0, "raw": "Paint"}]}).ok, "frida: a cell")
d1 = get(Fr, SID).json()
E1 = d1.get("etag")
check(isinstance(E1, str) and len(E1) >= 16, "the sheet carries an etag " + repr(E1))
check(get(Fr, SID).json().get("etag") == E1, "nothing changed: the same etag again (the answer is stable)")
r = get(Fr, SID, E1)
j = r.json()
check(r.status_code == 200 and j == {"unchanged": True, "etag": E1}, "the same etag back: only {unchanged, etag} " + r.text[:200])
check("cells" not in j and len(r.content) < 200, f"unchanged: no cells over the wire ({len(r.content)} bytes)")
r = get(Fr, SID, "0" * 24)
check(r.ok and r.json().get("cells") is not None and r.json().get("etag") == E1, "another etag: the whole sheet")

# a cell written: the old etag gets the whole sheet with a new etag
check(Fr.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"row_id": R0, "col_id": C0, "raw": "Paint twice"}]}).ok, "frida: the cell changed")
j = get(Fr, SID, E1).json()
E2 = j.get("etag")
check(not j.get("unchanged") and E2 and E2 != E1 and any(c.get("raw") == "Paint twice" for c in j.get("cells", [])),
      "a cell written: the old etag loads the whole sheet with the new value")

# a Kalmido value: the task changes, the table's rev does not
r = Fr.post(B + "/api/tasks", json={"title": "Buy brushes"})
check(r.ok, "frida: a task " + r.text[:200])
TID = r.json()["id"]
check(Fr.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"row_id": R1, "col_id": C0, "raw": f"=task.{TID}.title"}]}).ok, "frida: a Kalmido value")
d3 = get(Fr, SID).json()
E3, REV3 = d3.get("etag"), d3.get("rev")
check(any(c.get("origin") == "kalmido" and c.get("display") == "Buy brushes" for c in d3.get("cells", [])), "setup: the Kalmido value shows the title")
check(get(Fr, SID, E3).json().get("unchanged") is True, "the Kalmido value unchanged: unchanged")
check(Fr.patch(B + f"/api/tasks/{TID}", json={"title": "Buy wide brushes"}).ok, "frida: the task renamed")
j = get(Fr, SID, E3).json()
check(not j.get("unchanged") and j.get("rev") == REV3 and any(c.get("display") == "Buy wide brushes" for c in j.get("cells", [])),
      "the task renamed (the table's rev the same): the old etag loads the whole sheet with the new title "
      + str([(c.get("display"), c.get("origin")) for c in j.get("cells", [])])[:300])

# rights: another person never learns anything through the etag
for who, s in (("bob", Bo), ("alice", A)):
    r1, r2 = get(s, SID), get(s, SID, E2)
    check(r1.status_code == 404 and r2.status_code == 404 and "unchanged" not in r2.text,
          f"{who}: frida's private table 404 with and without the etag ({r1.status_code}, {r2.status_code})")
s_out = requests.Session()
s_out.headers.update(H)
check(get(s_out, SID, E2).status_code in (401, 403), "not signed in: refused, never {unchanged}")

# ---- an organisation table: bob reads, alice is in a cell (presence) -> bob's etag no longer fits
r = A.post(B + "/api/sheets", json={"title": "Crew plan", "space": f"org:{ORG}"})
check(r.status_code == 201, "alice: an organisation table " + r.text[:200])
OS = r.json()["id"]
OR0, OC0, _ = first_cell(A, OS)
jb = get(Bo, OS).json()
EB = jb.get("etag")
check(EB and get(Bo, OS, EB).json().get("unchanged") is True, "bob: the organisation table unchanged with his etag")
check(A.post(B + f"/api/sheets/{OS}/presence", json={"cell_id": None}).ok, "alice: is in the table (presence)")
j = get(Bo, OS, EB).json()
check(not j.get("unchanged") and any(p.get("name") == "Alice" for p in j.get("presence", [])), "alice's presence: bob's old etag loads the whole sheet " + str(j.get("presence")))
check(A.put(B + f"/api/sheets/{OS}/cells", json={"cells": [{"row_id": OR0, "col_id": OC0, "raw": "Grip"}]}).ok, "alice: a cell")
j2 = get(Bo, OS, j.get("etag")).json()
check(not j2.get("unchanged") and any(c.get("raw") == "Grip" for c in j2.get("cells", [])), "alice's cell: bob gets the whole sheet")

print(f"p2663_c_sheet_etag: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
