#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.993.0 (#5413, stage 4b of the core's trash): entertainment receipts (office_meals, kind omeal), their restaurant bills
(office_meal_files, kind omealfile) and the PDF files of framework contracts (office_contract_files, kind ocfile) lie in the
ONE trash of the core (office/okern.py ofk_register); their own purge runs (bw_purge_tick, dma_purge_tick) are gone.
Invented names only.
 - a meal deleted -> gone from its list, in the office trash (kind meal, its label) -> restored there -> back, its bill
   still there (the same bytes); no step in GET /api/undo (step=False: a redo there would skip the approval lock)
 - the meal's own undo route (POST .../restore) and the office trash's delete for good (row, bill row and stored file go)
 - the retention run is the core's: a meal past the trash period goes with its bill, log and stored file; a removed bill of
   an approved meal stays (trash_keep, counted as kept; the keep hook refuses it), after its keep period it goes
 - contract files: removed -> in the office trash (kind contract_file) -> restored; restore while the contract is in the
   trash -> 409; past the period the core's run deletes row and stored file
 - rights: another organisation 404 on the office trash's restore
tenant-matrix: office (another organisation: 404)
freelancer-matrix: office (a person without an organisation: her meal deleted, restored, purged after the period)
usage: p2993_b_meals_contract_trash_test.py <datadir>"""
import json
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

fresh(prefix="P2993B")
O = B + "/api/office"
M = O + "/meals"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
OLD = "2020-01-02T03:04:05.000Z"

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments", "office", "clients"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
AID = dbx("SELECT id FROM users WHERE username='alice'")[0][0]
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
OLGA = r.json().get("id")
check(A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": OLGA}).ok, "setup: another organisation")
Ol = sess("olga")
Ol.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
FID, Fr = freelancer(B, A)


def meal(s, **kw):
    b = {"date": "2025-05-14", "place_name": "Trattoria Esempio", "occasion": "Kick-off of the website project"}
    b.update(kw)
    r = s.post(M, json=b)
    check(r.status_code == 201, f"setup: a meal {r.status_code} {r.text[:200]}")
    return r.json()["id"]


def bill(s, mid):
    r = s.post(M + f"/{mid}/file", files={"file": ("bill.pdf", PDF, "application/pdf")})
    check(r.status_code == 201, f"setup: a bill {r.status_code} {r.text[:200]}")
    return r.json()["file_id"]


def listed(s):
    r = s.get(M)
    return [x["id"] for x in r.json().get("meals", [])] if r.ok else None


def trash(s):
    r = s.get(O + "/trash")
    return [(x.get("core"), x["id"], x["kind"], x.get("label") or "") for x in r.json().get("items", [])] if r.ok else None


def mrow(mid):
    r = dbx("SELECT deleted_at, deleted_by FROM office_meals WHERE id=?", (mid,))
    return tuple(r[0]) if r else None


def frow(fid, table="office_meal_files"):
    r = dbx(f"SELECT deleted_at, org_id, file FROM {table} WHERE id=?", (fid,))
    return tuple(r[0]) if r else None


def stored(org, name):
    """The stored file below OFFICE_DIR exists (checked inside the container: its user owns the files)."""
    out = in_app(f"import os\nfrom kalmido.core.config import OFFICE_DIR\nprint('ISFILE', os.path.isfile(os.path.join(OFFICE_DIR, '{int(org)}', {name!r})))")
    return "ISFILE True" in out


def tick():
    """The core's retention run as the watchdog runs it, switch on (force: no hourly wait) -> its counts."""
    out = in_app("import json, os\nos.environ['KALMIDO_PURGE_TRASH'] = '1'\nfrom kalmido.core.writes import obj_trash_tick\n"
                 "print('TICK', json.dumps(obj_trash_tick(c, force=True)))")
    try:
        return json.loads(out.rsplit("TICK ", 1)[1].splitlines()[0])
    except (IndexError, ValueError):
        print(out[-800:])
        return {}


# ---------------------------------------------------------------- a meal: delete -> office trash -> restore, its bill stays
M1 = meal(A)
F1 = bill(A, M1)
_, _, FN1 = frow(F1)
check(M1 in listed(A) and stored(ORG, FN1), "a meal with its stored bill")
r = A.delete(M + f"/{M1}")
check(r.ok and (r.json().get("trash") or {}).get("kind") == "omeal" and M1 not in listed(A), f"deleted: gone from the list {r.text[:200]}")
d = mrow(M1)
check(d and d[0] and d[1] == AID, f"in the core's trash: deleted_at and deleted_by set {d}")
it = [x for x in trash(A) if x[0] == "omeal" and x[1] == M1]
check(it and it[0][2] == "meal" and "Trattoria Esempio" in it[0][3], f"the office trash shows it with its label {it}")
check(not [x for x in A.get(B + "/api/undo").json().get("items", []) if "Entertainment" in (x.get("label") or "")],
      "no step in the person's undo list (step=False)")
check(Ol.post(O + f"/trash/core/omeal/{M1}/restore").status_code == 404 and mrow(M1)[0], "another organisation: 404, it stays in the trash")
r = A.post(O + f"/trash/core/omeal/{M1}/restore")
check(r.ok and r.json().get("kind") == "meal" and M1 in listed(A) and mrow(M1) == (None, None), f"restored from the office trash {r.text[:200]}")
g = A.get(M + f"/{M1}/file/{F1}")
check(g.ok and g.content == PDF and stored(ORG, FN1), "its bill is still there (the same bytes)")
check(A.delete(M + f"/{M1}").ok and A.post(M + f"/{M1}/restore").ok and M1 in listed(A), "the toast's undo (POST .../restore) brings it back")

# ---------------------------------------------------------------- delete for good from the office trash
check(A.delete(M + f"/{M1}").ok, "into the trash again")
check(Ol.delete(O + f"/trash/core/omeal/{M1}").status_code == 404 and mrow(M1), "another organisation: no delete for good (404)")
r = A.delete(O + f"/trash/core/omeal/{M1}")
check(r.ok and mrow(M1) is None and frow(F1) is None and not stored(ORG, FN1), f"deleted for good: meal, bill row and stored file gone {r.text[:200]}")

# ---------------------------------------------------------------- the retention run: past the period, with bill and log
M2 = meal(A)
F2 = bill(A, M2)
_, _, FN2 = frow(F2)
M3 = meal(A, place_name="Young Example")
check(A.delete(M + f"/{M2}").ok and A.delete(M + f"/{M3}").ok, "two meals into the trash")
dbx("UPDATE office_meals SET deleted_at=? WHERE id=?", (OLD, M2))
n = tick()
check(n.get("omeal") == 1 and mrow(M2) is None and frow(F2) is None and not stored(ORG, FN2), f"past the period: the meal goes with its bill and stored file {n}")
check(mrow(M3) and mrow(M3)[0], "the younger one stays in the trash")
check(not dbx("SELECT 1 FROM office_meal_log WHERE meal_id=?", (M2,)), "its log went with it")

# ---------------------------------------------------------------- a removed bill of an approved meal is kept by law
FULL = {"place_address": "Beispielweg 1\n12345 Musterstadt", "occasion": "Negotiation of the follow-up order for the spring campaign",
        "host": {"id": AID}, "guests": [{"name": "Gina Gast", "extra": "Example GmbH, buyer"}],
        "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}]}
MK = meal(A, **FULL)
FK1 = bill(A, MK)
FK2 = bill(A, MK)  # replaces FK1: FK1 goes into the trash
_, _, FNK1 = frow(FK1)
check(frow(FK1)[0] and not frow(FK2)[0], "the replaced bill is in the trash, the new one live")
r = A.post(M + f"/{MK}/approve")
check(r.ok and r.json().get("locked"), f"approved {r.text[:200]}")
check(A.delete(M + f"/{MK}").status_code == 409 and mrow(MK) == (None, None), "an approved receipt cannot be deleted (409)")
dbx("UPDATE office_meal_files SET deleted_at=? WHERE id=?", (OLD, FK1))
n = tick()
check(frow(FK1) is not None and stored(ORG, FNK1) and n.get("omealfile_kept") == 1, f"the removed bill of the approved meal stays, counted as kept {n}")
out = in_app(f"from kalmido.office.meals import bw_file_purge\ntry:\n    bw_file_purge(c, {FK1})\n    print('PURGED')\nexcept Denied as e:\n    print('DENIED', e)\nc.rollback()")
check("DENIED" in out and frow(FK1) is not None, f"the keep hook refuses it (Denied) {out[-300:]}")
# past the keep period (the meal and its approval in 2010): the core's run deletes it
dbx("UPDATE office_meals SET date='2010-03-01' WHERE id=?", (MK,))
dbx("UPDATE office_meal_log SET at='2010-03-02T10:00:00+00:00' WHERE meal_id=?", (MK,))
n = tick()
check(frow(FK1) is None and not stored(ORG, FNK1) and frow(FK2) is not None and mrow(MK) == (None, None),
      f"after the keep period: the removed bill goes, the live one and the meal stay {n}")

# ---------------------------------------------------------------- contract files
C1 = A.post(O + "/contracts", json={"name": "Example Framework Contract"}).json()["id"]
CF = O + f"/contracts/{C1}/files"


def cup():
    r = A.post(CF, files={"file": ("contract.pdf", PDF, "application/pdf")})
    check(r.status_code == 201, f"setup: a contract file {r.text[:200]}")
    return r.json()["id"]


K1 = cup()
_, _, KN1 = frow(K1, "office_contract_files")
check(A.delete(CF + f"/{K1}").ok and frow(K1, "office_contract_files")[0], "a contract file removed (the trash)")
it = [x for x in trash(A) if x[0] == "ocfile" and x[1] == K1]
check(it and it[0][2] == "contract_file" and "Example Framework Contract" in it[0][3], f"in the office trash with its contract's name {it}")
check(Ol.post(O + f"/trash/core/ocfile/{K1}/restore").status_code == 404, "another organisation: 404")
r = A.post(O + f"/trash/core/ocfile/{K1}/restore")
check(r.ok and [x["id"] for x in A.get(CF).json()["items"]] == [K1], f"restored from the office trash: listed again {r.text[:200]}")
check(A.delete(CF + f"/{K1}").ok and A.post(CF + f"/{K1}/restore").ok and frow(K1, "office_contract_files")[0] is None, "the toast's undo restores it too")
# the contract in the trash: its file only comes back with it
check(A.delete(CF + f"/{K1}").ok, "removed again")
check(A.delete(O + f"/contracts/{C1}").ok, "the contract deleted")
r = A.post(O + f"/trash/core/ocfile/{K1}/restore")
check(r.status_code == 409 and frow(K1, "office_contract_files")[0], f"a file of a contract in the trash: 409, it stays in the trash {r.status_code} {r.text[:200]}")
dbx("UPDATE office_contract_files SET deleted_at=? WHERE id=?", (OLD, K1))
n = tick()
check(n.get("ocfile") == 1 and frow(K1, "office_contract_files") is None and not stored(ORG, KN1), f"past the period: row and stored file gone {n}")

# ---------------------------------------------------------------- a person without an organisation (her personal office)
PB = dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
MF = meal(Fr, place_name="Example Bistro")
FF = bill(Fr, MF)
_, _, FNF = frow(FF)
check(A.delete(M + f"/{MF}").status_code == 404, "someone else: 404 on her meal")
check(Fr.delete(M + f"/{MF}").ok and MF not in listed(Fr) and mrow(MF)[1] == FID, "freelancer: into the trash")
check(any(x[0] == "omeal" and x[1] == MF for x in trash(Fr)) and not any(x[1] == MF and x[0] == "omeal" for x in trash(A)),
      "freelancer: in her office trash, not in another one")
check(A.post(O + f"/trash/core/omeal/{MF}/restore").status_code == 404, "someone else: no restore (404)")
check(Fr.post(O + f"/trash/core/omeal/{MF}/restore").ok and MF in listed(Fr), "freelancer: restored")
check(Fr.delete(M + f"/{MF}").ok, "freelancer: into the trash again")
dbx("UPDATE office_meals SET deleted_at=? WHERE id=?", (OLD, MF))
n = tick()
check(mrow(MF) is None and frow(FF) is None and not stored(PB, FNF), f"freelancer: purged after the period with her bill {n}")

sys.exit(done("p2993_b_meals_contract_trash"))
