#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.595.0 part B (#4881): the "Move to..." list (GET /api/files/folders) shows no folder that sits in the trash, nor one
below a trashed folder (subfolders carry no deleted_at of their own); PATCH parent_id into such a folder is refused (400);
after the restore both are back and a move works again. Also for a person without an organisation.
freelancer-matrix: files
usage: p2595_b_folders_test.py <datadir>"""
import sys

import kt
from kt import B, FAILS, OKS, check, sess  # noqa: F401
from freelancer_fixture import freelancer

kt.fresh()
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "files,collab"})


def run(S, label):
    def mk(name, parent=None):
        r = S.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": "private"})})
        assert r.ok, r.text
        return r.json().get("id") or r.json()["node"]["id"]

    def ids():
        r = S.get(B + "/api/files/folders")
        assert r.ok, r.text
        return {f["id"] for f in r.json()["folders"]}

    a = mk("Alpha " + label)
    b = mk("Beta", a)
    t = mk("Target " + label)
    f = S.post(B + "/api/files/folders", json={"name": "Mover " + label, "space": "private"}).json()
    m = f.get("id") or f["node"]["id"]
    check({a, b, t} <= ids(), f"{label}: all folders listed before the trash")
    check(S.delete(B + f"/api/files/nodes/{a}").ok, f"{label}: A (with B) to the trash")
    now = ids()
    check(a not in now and b not in now and t in now, f"{label}: neither A nor the subfolder B in the list, others stay")
    r = S.patch(B + f"/api/files/nodes/{m}", json={"parent_id": b})
    check(r.status_code in (400, 404), f"{label}: a move into B (below the trashed A) is refused: {r.status_code}")
    r = S.patch(B + f"/api/files/nodes/{m}", json={"parent_id": a})
    check(r.status_code in (400, 404), f"{label}: a move into the trashed A is refused: {r.status_code}")
    check(S.post(B + f"/api/files/nodes/{a}/restore").ok, f"{label}: A restored")
    check({a, b} <= ids(), f"{label}: A and B back in the list")
    check(S.patch(B + f"/api/files/nodes/{m}", json={"parent_id": b}).ok, f"{label}: the move into B works again")


run(A, "member")
_, Fr = freelancer(B, A)
run(Fr, "freelancer")
print(f"p2595_b_folders: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
