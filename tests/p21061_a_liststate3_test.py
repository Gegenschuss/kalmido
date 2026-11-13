#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1061.0 (#5867, stage 3a of the projects' state marker): every read of "the project is archived" asks the marker lists.state
(core/access.py list_archived_sql / list_archived / list_out), not the old column archived - the column can go in a later,
one-way step. The suite holds the trigger kalmido_list_state off for a moment and writes the old column the other way round
than the marker: what the app shows and decides then must follow the marker. Invented names.
 - the app's project list (/api/state) and the API v1 (GET /api/v1/lists/<id>) show archived from the marker, same shape
 - archiving a project the marker already holds archived is no change (the marker decides, not the column)
 - deleting for good only from the archive: the marker decides (a live project with archived=1 in the column: 409)
 - the organisation admin's list of projects shows archived from the marker
 - a project in the trash keeps the archive it had (archived_at): list_archived_sql in the database
 - the trigger on again: the table agrees again
freelancer-matrix: tasks (a person without an organisation reads her archive through the marker)
usage: p21061_a_liststate3_test.py <datadir>"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402

fresh(prefix="P21061A")

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
FID, Fr = freelancer(B, A)


def plist(s, name, org=None):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": org})
    check(r.ok, f"setup: project {name} {r.text[:120]}")
    return r.json().get("id")


def row(lid):
    r = dbx("SELECT state, archived, archived_at, deleted_at FROM lists WHERE id=?", (lid,))
    return tuple(r[0]) if r else None


def trigger(on):
    """The suite's own session (the app's account does not own the table): the marker's trigger off / on."""
    dbxm.connect(os.path.join(kt.DATA, "tasks.db")).executescript(
        f"ALTER TABLE lists {'ENABLE' if on else 'DISABLE'} TRIGGER kalmido_list_state;\n")


def state_lists(s):
    return {x["id"]: x for x in s.get(B + "/api/state").json().get("lists", [])}


PA = plist(Fr, "Example Pottery Course")   # archived by the marker, the column says live
PL = plist(Fr, "Example Bike Repair")      # live by the marker, the column says archived
check(Fr.patch(B + f"/api/lists/{PA}", json={"archived": True}).ok and row(PA)[:2] == ("archived", 1), f"setup: archived {row(PA)}")
r = A.post(B + "/api/orgs", json={"name": "Example Board Studio"})
OID = r.json().get("id") if r.ok else None
check(OID is not None, f"setup: an organisation of alice {r.status_code} {r.text[:120]}")
PO = plist(A, "Example Studio Shelf", OID)
r = A.post(B + "/api/users", json={"orgs": [{"id": OID, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
check(r.ok and A.put(B + f"/api/lists/{PO}/members", json={"user_id": r.json().get("id"), "role": "edit"}).ok,
      f"setup: shared with bob (the admins see shared projects) {r.text[:120]}")
check(A.post(B + f"/api/orgs/{OID}/lists/{PO}/archive", json={"archived": True}).ok and row(PO)[0] == "archived",
      f"setup: the organisation's project archived {row(PO)}")
TOK = Fr.post(B + "/api/me/tokens", json={"name": "Example reader", "scopes": ["read", "write"]}).json().get("token")
check(bool(TOK), "setup: an API token of the person without an organisation")

trigger(False)
try:
    dbx("UPDATE lists SET archived=false WHERE id IN (?, ?)", (PA, PO))
    dbx("UPDATE lists SET archived=true WHERE id=?", (PL,))
    check(row(PA)[:2] == ("archived", 0) and row(PL)[:2] == ("live", 1), f"setup: the old column the other way round {row(PA)} {row(PL)}")

    # ------------------------------------------------------------ what the app and the API show
    ls = state_lists(Fr)
    check(PA in ls and ls[PA].get("archived") in (1, True) and ls[PA].get("name") == "Example Pottery Course",
          f"the app's project list: archived from the marker, with its name {ls.get(PA)}")
    check(PL in ls and ls[PL].get("archived") in (0, False) and ls[PL].get("name") == "Example Bike Repair",
          f"the app's project list: live from the marker {ls.get(PL)}")
    VH = {"Authorization": "Bearer " + str(TOK)}
    va = requests.get(B + f"/api/v1/lists/{PA}", headers=VH)
    vl = requests.get(B + f"/api/v1/lists/{PL}", headers=VH)
    va, vl = (va.json() if va.ok else {}), (vl.json() if vl.ok else {})
    va, vl = va.get("data", va), vl.get("data", vl)
    check(va.get("archived") is True and va.get("name") == "Example Pottery Course", f"API v1: archived true from the marker {va}")
    check(vl.get("archived") is False and vl.get("name") == "Example Bike Repair", f"API v1: archived false from the marker {vl}")
    seen = {x["id"]: x for x in A.get(B + f"/api/orgs/{OID}/lists").json().get("lists", [])}
    check(PO in seen and seen[PO].get("archived") is True and seen[PO].get("name") == "Example Studio Shelf",
          f"the organisation admin's list: archived from the marker {seen.get(PO)}")

    # ------------------------------------------------------------ what the app decides
    r = Fr.delete(B + f"/api/lists/{PL}")
    check(r.status_code == 409 and row(PL)[3] is None, f"deleting for good only from the archive: the marker says live {r.status_code} {row(PL)}")
    r = A.post(B + f"/api/orgs/{OID}/lists/{PO}/archive", json={"archived": True})
    check(r.ok and row(PO)[:2] == ("archived", 0), f"the admin archives an archived project: no change (the marker decides) {r.status_code} {row(PO)}")
    r = Fr.delete(B + f"/api/lists/{PA}")
    check(r.ok and row(PA)[0] == "archived" and row(PA)[3], f"an archived project (by the marker) goes into the trash {r.status_code} {row(PA)}")
finally:
    # the old column as the marker says again, then the trigger on (a write that leaves the marker reads archived)
    dbx("UPDATE lists SET archived=true WHERE id IN (?, ?)", (PA, PO))
    dbx("UPDATE lists SET archived=false WHERE id=?", (PL,))
    trigger(True)

# ------------------------------------------------------------ the database value of a project in the trash
dbx("UPDATE lists SET state=state WHERE id IN (?, ?, ?)", (PA, PL, PO))  # the trigger on again: the trash from deleted_at
check(row(PA)[0] == "trash" and row(PA)[2], f"setup: the archived project in the trash keeps its moment {row(PA)}")
out = in_app(f"""from kalmido.core.access import list_archived_sql, list_archived
r = c.execute("SELECT id, state, archived_at, " + list_archived_sql("l") + " AS a FROM lists l WHERE id IN ({int(PA)}, {int(PL)}) ORDER BY id").fetchall()
print("VALS", [(x["id"], x["a"], list_archived(x)) for x in r])""")
check(f"({int(PA)}, 1, 1)" in out and f"({int(PL)}, 0, 0)" in out, f"in the trash: archived as it went in (archived_at) {out[-300:]}")
from_app = in_app('from kalmido.core.access import list_archived_sql\nlist_archived_sql("l; DROP")')
check("invalid alias" in from_app, f"list_archived_sql refuses an alias that is no name {from_app[-200:]}")

bad = dbx("""SELECT id, state, archived FROM lists WHERE (state='archived' AND NOT archived) OR (state='live' AND archived)""")
check(not bad, f"the trigger on again: archived agrees with the marker {bad[:3]}")

sys.exit(done("p21061_a_liststate3"))
