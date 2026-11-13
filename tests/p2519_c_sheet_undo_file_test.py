#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.519.0 (#4386): an agent's Undo of a file cell brings the cell's file back out of the trash. Own container. Invented names only.
freelancer-matrix: sheets
 - an agent points a file cell at another file of the table (the cell's file goes to the trash), a person undoes the call:
   the former file comes back out of the trash, the displaced one goes in
 - the trash run after the period (deleted_at moved back, the run forced with purging on) keeps the cell's file (download
   still works) and removes the displaced one
 - the same in an organisation's table (its agent through an attached list) and in the private table of a person without
   an organisation (her own agent through a share)
usage: p2519_c_sheet_undo_file_test.py <datadir>"""
import base64
import os
import subprocess
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402

V = B + "/api/v1"
KEY = base64.b64encode(os.urandom(32)).decode()
FEAT = "collab,comments,sheets"
SW = ["read", "sheets:read", "sheets:write"]
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
OLD = "2020-01-01T00:00:00.000+00:00"

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY})
assert kt.sess(None).post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def agent(name, org=None, owner=None):
    body = {"scopes": SW, "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], bearer(r.json()["token"])


def deleted(fid):
    row = kt.dbx("SELECT deleted_at FROM sheet_files WHERE id=?", (fid,))
    return row[0][0] if row else "gone"


def purge_run():
    """The files' trash run after the period: every trashed file of the tables moved back, the run forced, purging on."""
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute("UPDATE sheet_files SET deleted_at=? WHERE deleted_at IS NOT NULL", (OLD,))
        c.commit()
    finally:
        c.close()
    out = subprocess.run(["docker", "exec", "-e", "KALMIDO_PURGE_TRASH=1", kt.CT, "python", "-c",
                          # 2.1093.0 (#5472): the files no cell holds go through the core's run (part kind sheet_file; shk_tick went)
                          "import app\nc = app.connect()\ntry:\n    from kalmido.core.writes import obj_trash_tick\n"
                          "    obj_trash_tick(c, True)\nfinally:\n    c.close()\nprint('ok')"], capture_output=True, text=True)
    check(out.returncode == 0 and out.stdout.strip().endswith("ok"), f"the trash run works {out.stdout[-200:]} {out.stderr[-800:]}")


def case(who, s, ag, sid):
    """Two files in the table, the agent points the first file's cell at the second one, the person undoes the call."""
    sh = s.get(B + f"/api/sheets/{sid}").json()
    rows = [x["id"] for x in sh["rows"]]
    r = s.post(B + f"/api/sheets/{sid}/columns", json={"title": "Doc", "kind": "file"})
    check(r.status_code == 201, f"{who}: a file column " + r.text[:200])
    col = r.json()["column"]["id"]

    def up(rid, name):
        r = s.post(B + f"/api/sheets/{sid}/files", data={"row_id": str(rid), "col_id": str(col)},
                   files={"file": (name, PDF, "application/pdf")})
        check(r.status_code == 201, f"{who}: upload {name} " + r.text[:200])
        return r.json().get("file", {}).get("id")

    f1, f2 = up(rows[0], "kept.pdf"), up(rows[1], "spare.pdf")
    check(s.put(B + f"/api/sheets/{sid}/cells", json={"cells": [{"row_id": rows[1], "col_id": col, "raw": ""}]}).ok,
          f"{who}: the second cell emptied (its file into the trash)")
    check(deleted(f1) is None and deleted(f2) is not None, f"{who}: setup: only the spare file in the trash {deleted(f1)} {deleted(f2)}")
    r = ag.put(V + f"/sheets/{sid}/cells", json={"cells": [{"row_id": rows[0], "col_id": col, "raw": f"file:{f2}"}], "expect_rev": ag.get(V + f"/sheets/{sid}").json()["rev"]})  # 2.564.0 (#4702): an agent sends the version it read
    check(r.ok and r.json().get("batch"), f"{who}: the agent points the cell at the spare file " + r.text[:200])
    batch = r.json().get("batch")
    check(deleted(f1) is not None and deleted(f2) is None, f"{who}: the agent's change swapped the files in the trash")
    r = s.post(B + f"/api/sheets/{sid}/batches/{batch}/undo")
    check(r.ok and r.json().get("undone") == 1, f"{who}: the person undoes the agent's call " + r.text[:200])
    x = next((c for c in s.get(B + f"/api/sheets/{sid}").json()["cells"] if c["row_id"] == rows[0] and c["col_id"] == col), {})
    check(x.get("raw") == f"file:{f1}", f"{who}: the cell shows the former file again {x.get('raw')}")
    check(deleted(f1) is None, f"#4386 {who}: Undo takes the cell's file out of the trash {deleted(f1)}")
    check(deleted(f2) is not None, f"#4386 {who}: the displaced file goes into the trash {deleted(f2)}")
    return f1, f2


# ================================================================== an organisation's table, its agent via an attached list
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123",
                                   "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
AG, ag = agent("tallybot", org=ORG)
L = Bo.post(B + "/api/lists", json={"name": "Shoot", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the agent may change the list")
r = Bo.post(B + "/api/sheets", json={"title": "Kit list", "space": f"org:{ORG}", "list_id": L})
check(r.ok, "bob creates a table of the organisation " + r.text[:200])
OS = r.json()["id"]
o1, o2 = case("org", Bo, ag, OS)

# ================================================================== a person without an organisation, her own agent
# freelancer-matrix: sheets
FID, Fr = freelancer(B, A, "fiona", FEAT)
DA, da = agent("fionabot", owner=FID)
r = Fr.post(B + "/api/sheets", json={"title": "Gear", "space": "private"})
check(r.ok, "freelancer: a private table " + r.text[:200])
FS = r.json()["id"]
check(Fr.post(B + f"/api/sheets/{FS}/shares", json={"user_id": DA, "role": "write"}).status_code == 201,
      "freelancer: shares the table with her own agent")
p1, p2 = case("freelancer", Fr, da, FS)

# ================================================================== the trash run after the period
purge_run()
for who, s, sid, keep, gone in (("org", Bo, OS, o1, o2), ("freelancer", Fr, FS, p1, p2)):
    check(deleted(keep) is None, f"#4386 {who}: the cell's file survives the trash run {deleted(keep)}")
    r = s.get(B + f"/api/sheets/{sid}/files/{keep}")
    check(r.ok and r.content == PDF, f"#4386 {who}: and still downloads ({r.status_code})")
    check(deleted(gone) == "gone", f"{who}: the displaced file is removed for good {deleted(gone)}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
