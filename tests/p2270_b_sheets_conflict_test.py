#!/usr/bin/env python3
"""2.270.0 B (#3021, #3028): tables keep a newer input instead of overwriting it. Invented names only.
 - PUT cells with prev: a cell changed by someone else since stays, comes back in conflicts (with its current content in
   cells); the other cells of the same call are written; prev equal to the current input or the new input = no conflict;
   without prev the old behaviour (last write wins)
 - expect_rev: strict, 409 with the current cells when the table changed since; the right rev writes
 - undo of the app (the inverse write with prev): a cell changed elsewhere since is skipped
 - select options as single operations (options_ops): two dialogs from the same old state both keep their option (add),
   a rename over a newer rename is reported, remove; added ids come back
 - v1 with a token: cells by row_id / col_id + prev, conflicts; "B4" still works
 - step2 undo "table -> quotation": a draft edited in the office since stays (edited), an untouched one is deleted
 - a person without an organisation (P4): the same in the private space
freelancer-matrix: sheet
usage: p2270_b_sheets_conflict_test.py <datadir>"""
import sys

import requests

import kt
from kt import B, H, check, sess
from freelancer_fixture import FEATURES, freelancer

FEAT = "collab,comments,sheets,office,clients"
kt.fresh(prefix="P2270B")
A = kt.setup()
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A, "frida", FEATURES + ",sheets")


def sheet(s, sid):
    return s.get(B + f"/api/sheets/{sid}").json()


def raw(sh, rid, cid):
    return next((c["raw"] for c in sh["cells"] if c["row_id"] == rid and c["col_id"] == cid), "")


def cells_put(s, sid, cells, **kw):
    return s.put(B + f"/api/sheets/{sid}/cells", json={"cells": cells, **kw})


def run(P, Q, space, tag):
    """P writes, Q writes in between (Q = P for the person without an organisation: a second device)."""
    sh = P.post(B + "/api/sheets", json={"title": "Plan " + tag, "space": space}).json()
    sid, R, C = sh["id"], [x["id"] for x in sh["rows"]], [x["id"] for x in sh["columns"]]
    assert cells_put(P, sid, [{"row_id": R[0], "col_id": C[0], "raw": "Camera"}, {"row_id": R[1], "col_id": C[0], "raw": "Light"}]).ok
    # Q changes A1 after P read it; P writes A1 and A2 with prev from its old state
    assert cells_put(Q, sid, [{"row_id": R[0], "col_id": C[0], "raw": "Drone"}]).ok
    r = cells_put(P, sid, [{"row_id": R[0], "col_id": C[0], "raw": "Crane", "prev": "Camera"},
                           {"row_id": R[1], "col_id": C[0], "raw": "Sound", "prev": "Light"}])
    j = r.json()
    cf = j.get("conflicts") or []
    check(r.ok and len(cf) == 1 and cf[0]["row_id"] == R[0] and cf[0]["server"] == "Drone" and cf[0]["mine"] == "Crane",
          f"{tag}: a stale write of A1 is reported, not stored " + r.text[:300])
    check(any(c["row_id"] == R[0] and c["raw"] == "Drone" for c in j.get("cells", [])), f"{tag}: the conflict's current cell comes back")
    now = sheet(P, sid)
    check(raw(now, R[0], C[0]) == "Drone" and raw(now, R[1], C[0]) == "Sound", f"{tag}: A1 keeps the newer input, A2 is written")
    # prev equal to the new input (a repeated send) = no conflict; an empty cell has prev ""
    r = cells_put(P, sid, [{"row_id": R[1], "col_id": C[0], "raw": "Sound", "prev": "Light"}, {"row_id": R[2], "col_id": C[0], "raw": "Grip", "prev": ""}])
    check(r.ok and r.json()["conflicts"] == [] and raw(sheet(P, sid), R[2], C[0]) == "Grip", f"{tag}: a repeated send and an empty cell: no conflict")
    # without prev: the old behaviour (2.270.0: kept for old clients and agents)
    r = cells_put(P, sid, [{"row_id": R[0], "col_id": C[0], "raw": "Crane"}])
    check(r.ok and raw(sheet(P, sid), R[0], C[0]) == "Crane", f"{tag}: without prev the write goes through (compatible)")
    # undo of the app = the inverse write with prev: a cell changed since is skipped
    assert cells_put(P, sid, [{"row_id": R[3], "col_id": C[0], "raw": "Van", "prev": ""}]).ok
    assert cells_put(Q, sid, [{"row_id": R[3], "col_id": C[0], "raw": "Truck"}]).ok
    r = cells_put(P, sid, [{"row_id": R[3], "col_id": C[0], "raw": "", "prev": "Van"}])
    check(r.ok and len(r.json()["conflicts"]) == 1 and raw(sheet(P, sid), R[3], C[0]) == "Truck", f"{tag}: undo over a newer input skips the cell")
    # a formula's prev in the display form
    assert cells_put(P, sid, [{"row_id": R[4], "col_id": C[1], "raw": "=1+2"}]).ok
    disp = raw(sheet(P, sid), R[4], C[1])
    r = cells_put(P, sid, [{"row_id": R[4], "col_id": C[1], "raw": "=2+2", "prev": disp}])
    check(r.ok and r.json()["conflicts"] == [], f"{tag}: a formula's prev in the display form matches ({disp})")
    # expect_rev: strict
    rev = sheet(P, sid)["rev"]
    assert cells_put(Q, sid, [{"row_id": R[5], "col_id": C[0], "raw": "Other"}]).ok
    r = cells_put(P, sid, [{"row_id": R[6], "col_id": C[0], "raw": "Mine"}], expect_rev=rev)
    check(r.status_code == 409 and r.json().get("rev", 0) > rev and isinstance(r.json().get("cells"), list) and r.json().get("error"),
          f"{tag}: expect_rev of an older state: 409 with the current cells ({r.status_code})")
    check(raw(sheet(P, sid), R[6], C[0]) == "", f"{tag}: nothing written on 409")
    r = cells_put(P, sid, [{"row_id": R[6], "col_id": C[0], "raw": "Mine"}], expect_rev=sheet(P, sid)["rev"])
    check(r.ok and raw(sheet(P, sid), R[6], C[0]) == "Mine", f"{tag}: the current rev writes")
    check(cells_put(P, sid, [], expect_rev="x").status_code == 400, f"{tag}: a wrong expect_rev 400")

    # ---- select options as single operations
    cid = C[2]
    url = B + f"/api/sheets/{sid}/columns/{cid}"
    r = P.patch(url, json={"kind": "select", "options": [{"id": "o1", "label": "Open"}, {"id": "o2", "label": "Done"}]})
    assert r.ok, r.text
    r1 = P.patch(url, json={"options_ops": [{"op": "add", "label": "Waiting", "color": ""}]})
    r2 = Q.patch(url, json={"options_ops": [{"op": "add", "label": "Billed", "color": ""}]})
    labels = [o["label"] for o in r2.json()["column"]["options"]] if r2.ok else []
    check(r1.ok and r2.ok and labels == ["Open", "Done", "Waiting", "Billed"], f"{tag}: two dialogs each add their option, none is lost {labels}")
    check(len(r1.json().get("added") or []) == 1 and r1.json()["added"][0] not in ("o1", "o2"), f"{tag}: the added id comes back")
    r = Q.patch(url, json={"options_ops": [{"op": "add", "label": "waiting"}]})
    check(r.ok and r.json()["added"] == [] and len(r.json()["column"]["options"]) == 4, f"{tag}: the same label twice adds nothing")
    assert Q.patch(url, json={"options_ops": [{"op": "rename", "id": "o1", "label": "New", "prev": {"label": "Open"}}]}).ok
    r = P.patch(url, json={"options_ops": [{"op": "rename", "id": "o1", "label": "To do", "prev": {"label": "Open"}}]})
    opts = {o["id"]: o["label"] for o in r.json()["column"]["options"]} if r.ok else {}
    check(r.ok and opts.get("o1") == "New" and (r.json().get("conflicts") or [{}])[0].get("server") == "New",
          f"{tag}: a rename over a newer rename is reported, the newer stays {opts}")
    r = P.patch(url, json={"options_ops": [{"op": "remove", "id": "o2"}, {"op": "add", "id": "o2", "label": "Done again"}]})
    check(r.ok and any(o["id"] == "o2" and o["label"] == "Done again" for o in r.json()["column"]["options"]),
          f"{tag}: remove + add with the old id (the undo of a remove) keeps the id")
    check(P.patch(url, json={"options_ops": [{"op": "drop"}]}).status_code == 400, f"{tag}: an unknown op 400")
    # typing a new label into a select cell still adds the option (under the same lock)
    r = cells_put(P, sid, [{"row_id": R[0], "col_id": cid, "raw": "Archived", "prev": ""}])
    check(r.ok and any(o["label"] == "Archived" for o in sheet(P, sid)["columns"][2]["options"]), f"{tag}: a typed label becomes an option")
    # a select cell's prev may be the label
    r = cells_put(P, sid, [{"row_id": R[0], "col_id": cid, "raw": "New", "prev": "archived"}])
    check(r.ok and r.json()["conflicts"] == [], f"{tag}: a select cell's prev as its label matches")
    return sid, R, C


SID, R, C = run(A, Bo, f"org:{ORG}", "org")
FSID, FR, FC = run(Fr, Fr, "private", "freelancer")

# ---- v1 with a person's token: ids + prev, "B4" still works
for who, s, sid, rows, cols in (("org", A, SID, R, C), ("freelancer", Fr, FSID, FR, FC)):
    t = s.post(B + "/api/me/tokens", json={"name": "sheets", "scopes": ["read", "sheets:read", "sheets:write"]})
    if not t.ok:
        check(False, f"{who}: token " + t.text[:200])
        continue
    V = {"Authorization": "Bearer " + t.json()["token"], **H}
    cur = raw(sheet(s, sid), rows[7], cols[0])
    assert cells_put(s, sid, [{"row_id": rows[7], "col_id": cols[0], "raw": "Human"}]).ok  # a person writes after the agent read
    r = requests.put(B + f"/api/v1/sheets/{sid}/cells", headers=V, json={"cells": [{"row_id": rows[7], "col_id": cols[0], "raw": "Agent", "prev": cur}]})
    check(r.ok and len(r.json().get("conflicts") or []) == 1 and raw(sheet(s, sid), rows[7], cols[0]) == "Human",
          f"{who}: v1 by ids with prev keeps the person's newer input " + r.text[:200])
    r = requests.put(B + f"/api/v1/sheets/{sid}/cells", headers=V, json={"cells": [{"row_id": rows[8], "col_id": cols[0], "raw": "Agent", "prev": ""}]})
    check(r.ok and r.json()["conflicts"] == [] and raw(sheet(s, sid), rows[8], cols[0]) == "Agent", f"{who}: v1 by ids writes")
    r = requests.put(B + f"/api/v1/sheets/{sid}/cells", headers=V, json={"cells": [{"cell": "B10", "raw": "7"}]})
    check(r.ok and raw(sheet(s, sid), rows[9], cols[1]) == "7", f"{who}: v1 address B10 still works")
    rev = sheet(s, sid)["rev"]
    assert cells_put(s, sid, [{"row_id": rows[9], "col_id": cols[0], "raw": "x"}]).ok
    r = requests.put(B + f"/api/v1/sheets/{sid}/cells", headers=V, json={"cells": [{"cell": "A10", "raw": "y"}], "expect_rev": rev})
    check(r.status_code == 409 and isinstance(r.json().get("error", {}).get("cells"), list), f"{who}: v1 expect_rev of an older state 409 with the cells ({r.status_code})")

# ---- step2 undo "table -> quotation": an edited draft stays
for who, s, sid, rows, cols in (("org", A, SID, R, C), ("freelancer", Fr, FSID, FR, FC)):
    body = {"desc_col": cols[0], "rows": [rows[1]]}
    r = s.post(B + f"/api/sheets/{sid}/to-offer", json=body)
    if not r.ok:
        check(False, f"{who}: to-offer " + r.text[:200])
        continue
    o1 = r.json()
    s.get(B + f"/api/office/docs/{o1['doc_id']}")  # opening it changes nothing
    r = s.post(B + f"/api/sheets/{sid}/links/{o1['batch']}/undo")
    check(r.ok and r.json()["kept"] == [] and s.get(B + f"/api/office/docs/{o1['doc_id']}").status_code == 404,
          f"{who}: an untouched draft is deleted by the undo " + r.text[:200])
    o2 = s.post(B + f"/api/sheets/{sid}/to-offer", json=body).json()
    e = s.patch(B + f"/api/office/docs/{o2['doc_id']}", json={"project_title": "Edited in the office"})
    check(e.ok, f"{who}: the draft is edited in the office " + e.text[:200])
    r = s.post(B + f"/api/sheets/{sid}/links/{o2['batch']}/undo")
    check(r.ok and r.json()["kept"] == [o2["doc_id"]] and r.json().get("edited") == [o2["doc_id"]] and s.get(B + f"/api/office/docs/{o2['doc_id']}").ok,
          f"{who}: an edited draft stays (edited) " + r.text[:200])

sys.exit(kt.done("p2270_b_sheets_conflict"))
