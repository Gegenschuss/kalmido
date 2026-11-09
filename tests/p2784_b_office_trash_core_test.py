#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.784.0 (#5366, stage 4 of the core's trash): the office kinds that delete by deleted_at lie in the ONE trash of the core
(office/okern.py ofk_register -> core/writes.py obj_trash / obj_restore / obj_trash_prune). Kind osupplier (the suppliers
of the DATEV import, office/datevimp.py). Invented names only.
 - delete -> gone from the list, in the trash (deleted_at, deleted_by) -> restore -> back in the list
 - delete again -> one step of the person (mode trash) in GET /api/undo -> POST /api/undo/to/<id> brings it back
 - rights: a member 403, another organisation 404 (delete / restore / the step)
 - the retention run is the core's: obj_trash_prune counts (switch off) or deletes what is in the trash longer than the
   period; a younger one and a live one (old dates, never deleted) stay
tenant-matrix: office (another organisation: 404 on a foreign supplier, no undo of a foreign step)
freelancer-matrix: office (a person without an organisation: her supplier deleted, taken back, deleted for good after the period)
usage: p2784_b_office_trash_core_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

fresh(prefix="P2784B")
O = B + "/api/office/datev/suppliers"
K = "osupplier"

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments", "office", "clients"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
uid["bob"] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
check(A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]}).ok, "setup: another organisation")
Bo, Ol = sess("bob"), sess("olga")
for s in (Bo, Ol):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
AID = dbx("SELECT id FROM users WHERE username='alice'")[0][0]
FID, Fr = freelancer(B, A)
OLD = "2020-01-02T03:04:05.000Z"


def supplier(org, name, deleted=None):
    """A supplier as the DATEV import leaves it (plain values: the list decrypts only sealed ones)."""
    return dbx("INSERT INTO office_suppliers(org_id, account_no, name, created_at, updated_at, deleted_at) VALUES(?,?,?,?,?,?) RETURNING id",
               (org, "70001", name, OLD, OLD, deleted))[0][0]


def names(s):
    r = s.get(O)
    return [x["name"] for x in r.json().get("items", [])] if r.ok else None


def row(sid):
    r = dbx("SELECT deleted_at, deleted_by FROM office_suppliers WHERE id=?", (sid,))
    return r[0] if r else None


def groups(u):
    return dbx("SELECT id, state, label_key FROM undo_groups WHERE user_id=? ORDER BY id", (u,))


def modes(gid):
    return [r[0] for r in dbx("SELECT mode FROM obj_undo WHERE group_id=? ORDER BY id", (gid,))]


# ---------------------------------------------------------------- delete -> trash -> restore (an organisation's admin)
S1 = supplier(ORG, "Example Timber Ltd")
check(names(A) == ["Example Timber Ltd"], f"the supplier is in the list {names(A)}")
check(Bo.delete(O + f"/{S1}").status_code == 403 and row(S1)[0] is None, "a member: 403, nothing goes")
check(Ol.delete(O + f"/{S1}").status_code == 404 and row(S1)[0] is None, "another organisation: 404, nothing goes")
g0 = len(groups(AID))
r = A.delete(O + f"/{S1}")
check(r.ok and names(A) == [], f"deleted: gone from the list {r.status_code} {r.text[:200]}")
d = row(S1)
check(d is not None and d[0] and d[1] == AID, f"in the core's trash: deleted_at and deleted_by set, the row stays {d}")
check(Ol.post(O + f"/{S1}/restore").status_code == 404 and row(S1)[0], "another organisation: no restore (404)")
check(A.post(O + f"/{S1}/restore").ok and names(A) == ["Example Timber Ltd"] and row(S1) == (None, None),
      f"restored: back in the list, deleted_at / deleted_by empty {row(S1)}")
gs = groups(AID)
check(len(gs) == g0 + 2 and modes(gs[-2]["id"]) == ["trash"] and modes(gs[-1]["id"]) == ["restore"],
      f"delete and restore are two steps of the person (modes trash / restore) {gs[g0:]}")

# ---------------------------------------------------------------- delete again -> taken back from the list of steps
check(A.delete(O + f"/{S1}").ok and names(A) == [], "deleted again")
GT = groups(AID)[-1]["id"]
it = A.get(B + "/api/undo").json()["items"]
check(it and it[0]["id"] == GT and it[0]["undo"] is True and "Supplier" in it[0]["label"], f"the step is listed in GET /api/undo {it[:1]}")
check(Ol.post(B + f"/api/undo/to/{GT}").status_code == 404 and row(S1)[0], "a foreign step: 404, it stays in the trash")
r = A.post(B + f"/api/undo/to/{GT}")
check(r.ok and GT in r.json().get("undone", []) and names(A) == ["Example Timber Ltd"] and row(S1)[0] is None,
      f"undo: out of the trash, back in the list {r.status_code} {r.text[:200]}")
check(dbx("SELECT state FROM undo_groups WHERE id=?", (GT,))[0][0] == "undone", "the group is undone")

# ---------------------------------------------------------------- a person without an organisation (her personal office)
check(Fr.get(O).ok, "freelancer: the suppliers of her personal office open")
PB = dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
F1 = supplier(PB, "Example Prints")
check(names(Fr) == ["Example Prints"] and "Example Prints" not in (names(A) or []), "freelancer: her supplier, only hers")
check(A.delete(O + f"/{F1}").status_code == 404 and row(F1)[0] is None, "someone else: 404 on her supplier")
check(Fr.delete(O + f"/{F1}").ok and names(Fr) == [] and row(F1)[1] == FID, "freelancer: into the trash")
GF = groups(FID)[-1]["id"]
check(modes(GF) == ["trash"] and Fr.post(B + f"/api/undo/to/{GF}").ok and names(Fr) == ["Example Prints"], "freelancer: taken back with the undo")
check(Fr.delete(O + f"/{F1}").ok and Fr.post(O + f"/{F1}/restore").ok and names(Fr) == ["Example Prints"], "freelancer: restore")
check(Fr.delete(O + f"/{F1}").ok, "freelancer: into the trash again")

# ---------------------------------------------------------------- the retention run is the core's
S2 = supplier(ORG, "Example Old Ltd")
S3 = supplier(ORG, "Example Young Ltd")
S4 = supplier(ORG, "Example Live Ltd")  # old dates, never deleted: never a candidate
for s in (S2, S3):
    check(A.delete(O + f"/{s}").ok, f"into the trash {s}")
dbx("UPDATE office_suppliers SET deleted_at=? WHERE id IN (?, ?)", (OLD, S2, F1))
out = in_app(f"""from kalmido.core.writes import obj_trash_due, obj_trash_prune
print("DUE", sorted(obj_trash_due(c, "{K}")))
print("DRY", obj_trash_prune(c, "{K}", purge=False))""")
check(f"DUE {sorted([S2, F1])}" in out and "DRY 2" in out, f"due: only the old ones; switch off = counted {out[-400:]}")
check(row(S2) and row(F1) and row(S3) and row(S4), "switch off: nothing deleted")
out = in_app(f"""from kalmido.core.writes import obj_trash_prune
print("PURGED", obj_trash_prune(c, "{K}", purge=True))
c.commit()""")
check("PURGED 2" in out and row(S2) is None and row(F1) is None, f"switch on: the old ones (an organisation's, the freelancer's) gone {out[-300:]}")
check(row(S3) is not None and row(S3)[0] and row(S4) == (None, None), "the younger one stays in the trash, the live one stays live")
check(not dbx("SELECT 1 FROM obj_undo WHERE kind=? AND ref_id IN (?, ?)", (K, S2, F1)), "their undo steps went with them")
check(names(A) == ["Example Live Ltd", "Example Timber Ltd"] or sorted(names(A) or []) == ["Example Live Ltd", "Example Timber Ltd"],
      f"the list: the live ones only {names(A)}")

sys.exit(done("p2784_b_office_trash_core"))
