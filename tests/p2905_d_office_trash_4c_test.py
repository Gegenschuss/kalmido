#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.905.0 (#5414, stage 4c of the core's trash): the office's master data and small office kinds are deleted into the ONE
trash of the core (office/okern.py ofk_register -> core/writes.py obj_trash) instead of a copy in office_trash and the row
deleted. Invented names only.
 - master data (services, equipment, sets, texts, framework contracts, freelancer roles, crew): delete -> gone from the list
   and from GET /api/office/<kind>/<id> (404) -> in the office trash (core = its kind) -> restore -> back in the list
 - a picking list does not offer a row in the trash (a set's device, a text of the settings)
 - the toast's undo (?undo=1): the person who deleted it; no step in GET /api/undo (its routes' checks would be skipped)
 - delete for good from the office trash (DELETE .../core/<kind>/<id>): the row is gone
 - rights: a member 403, another organisation 404 (restore, delete for good)
 - an old copy in office_trash (made before 2.905) is still listed and restored as before. 2.1005.0 (#5415): the start writes it
   back into its table as a row of the core's trash (okern.ofk_copies_back): listed as the core's kind, restored through it
 - the retention run is the core's: a service in the trash longer than the period is deleted for good, a younger one stays
 - a rights group (kind orgroup): delete -> gone from the rights page, nobody can be put into it, in the office trash ->
   restore -> back without its members; the toast's undo of the manager
 - a fixed cost (kind ofixed): delete -> gone from the fixed costs, in the office trash -> restore -> back
 - a correction of the cash flow (kind oadjust): delete -> not counted in the cash flow, in the office trash -> restore
 - a letter's link (kind oletlink): p2567_c_office_trash_test.py (removed, listed, undo, linked again)
 - 2.990.0 (#5539): the undo of a data import removes the run's services (live and in the trash) with their history
tenant-matrix: office (another organisation: 404 on a foreign row of the core's trash, restore and delete for good)
freelancer-matrix: office (a person without an organisation: her service deleted, listed in her trash, restored, deleted for good)
usage: p2905_d_office_trash_4c_test.py <datadir>"""
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
import kt  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

fresh(prefix="P2905D")
OFC = B + "/api/office"
T = OFC + "/trash"

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments", "office", "clients"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
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
ORG2 = dbx("SELECT id FROM orgs WHERE name='Other Example'")[0][0]
Ol.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
AID = dbx("SELECT id FROM users WHERE username='alice'")[0][0]
FID, Fr = freelancer(B, A)

MASTER = [  # (the app's kind, the core's kind, body, the label's field)
    ("services", "omd_services", {"name_de": "Example Edit Day", "daily_rate": 400}, "name_de"),
    ("equipment", "omd_equipment", {"name": "Example Camera"}, "name"),
    ("sets", "omd_sets", {"name": "Example Light Set"}, "name"),
    ("texts", "omd_texts", {"kind": "note", "key": "example-note", "text_de": "Example note text"}, "key"),
    ("contracts", "omd_contracts", {"name": "Example Frame Contract"}, "name"),
    ("roles", "omd_roles", {"name_de": "Example Editor"}, "name_de"),
    ("crew", "omd_roles", {"name_de": "Example Gaffer"}, "name_de"),
]


def ids(s, kind):
    r = s.get(OFC + f"/{kind}")
    return [x["id"] for x in r.json().get("items", [])] if r.ok else None


def trash(s):
    r = s.get(T)
    return r.json().get("items", []) if r.ok else None


def in_trash(s, core, rid):
    return [x for x in trash(s) or [] if x.get("core") == core and x.get("id") == rid]


def drow(table, rid):
    r = dbx(f"SELECT deleted_at, deleted_by FROM {table} WHERE id=?", (rid,))
    return r[0] if r else None


TABLE = {"services": "office_services", "equipment": "office_equipment", "sets": "office_sets", "texts": "office_texts",
         "contracts": "office_contracts", "roles": "office_roles", "crew": "office_roles"}

# ---------------------------------------------------------------- every master kind: delete -> trash -> restore
for kind, core, b, lab in MASTER:
    r = A.post(OFC + f"/{kind}", json=b)
    check(r.status_code in (200, 201), f"{kind}: setup {r.status_code} {r.text[:200]}")
    rid = r.json()["id"]
    check(rid in (ids(A, kind) or []), f"{kind}: in the list")
    check(Bo.delete(OFC + f"/{kind}/{rid}").status_code == 403 and drow(TABLE[kind], rid)[0] is None, f"{kind}: a member 403, nothing goes")
    check(Ol.delete(OFC + f"/{kind}/{rid}").status_code in (403, 404) and drow(TABLE[kind], rid)[0] is None, f"{kind}: another organisation, nothing goes")
    r = A.delete(OFC + f"/{kind}/{rid}")
    j = r.json() if r.ok else {}
    check(r.ok and j.get("result") == "deleted" and j.get("trash") == {"kind": core, "id": rid}, f"{kind}: deleted into the core's trash {r.text[:200]}")
    lst, g = ids(A, kind), A.get(OFC + f"/{kind}/{rid}")
    check(lst is not None and rid not in lst and g.status_code == 404, f"{kind}: gone from the list, 404 on its address {lst} {g.status_code}")
    d = drow(TABLE[kind], rid)
    check(d and d[0] and d[1] == AID, f"{kind}: the row stays with deleted_at / deleted_by {d}")
    t = in_trash(A, core, rid)
    check(len(t) == 1 and t[0]["kind"] == kind and t[0]["label"] == b[lab], f"{kind}: in the office trash with its label {t}")
    check(Ol.post(T + f"/core/{core}/{rid}/restore").status_code in (403, 404) and drow(TABLE[kind], rid)[0], f"{kind}: another organisation: no restore")  # tenant: POST /api/office/trash/core/{}/{}/restore
    check(Bo.post(T + f"/core/{core}/{rid}/restore").status_code == 403 and drow(TABLE[kind], rid)[0], f"{kind}: a member: no restore")
    r = A.post(T + f"/core/{core}/{rid}/restore")
    check(r.ok and r.json().get("kind") == kind and rid in (ids(A, kind) or []) and drow(TABLE[kind], rid) == (None, None),
          f"{kind}: restored, back in the list {r.status_code} {r.text[:200]}")
    check(not in_trash(A, core, rid) and A.post(T + f"/core/{core}/{rid}/restore").status_code == 404, f"{kind}: out of the trash, a second restore 404")

# ---------------------------------------------------------------- the toast's undo, the step of the person, delete for good
SV = A.post(OFC + "/services", json={"name_de": "Example Grading"}).json()["id"]
check(A.delete(OFC + f"/services/{SV}").ok, "service: deleted")
check(A.post(T + f"/core/omd_services/{SV}/restore?undo=1").ok and SV in ids(A, "services"), "the toast's undo brings it back")
check(A.delete(OFC + f"/services/{SV}").ok, "service: deleted again")
# 2.905.0 (#5414, review): master data, rights groups and fixed costs leave NO step in the person's undo list - the core's
# undo / redo would skip what their routes do besides (in-use check, contract files, members out, the import run); they
# come back only through the toast's undo and the office trash (okern.py ofk_register step=False)
check(not dbx("SELECT 1 FROM obj_undo WHERE user_id=? AND kind='omd_services' AND ref_id=? AND mode IN ('trash', 'restore')", (AID, SV)),
      "a master data delete is no step of the person's undo list")
check(Ol.delete(T + f"/core/omd_services/{SV}").status_code in (403, 404) and drow("office_services", SV), "another organisation: no delete for good")  # tenant: DELETE /api/office/trash/core/{}/{}
check(Bo.delete(T + f"/core/omd_services/{SV}").status_code == 403 and drow("office_services", SV), "a member: no delete for good")
check(A.delete(T + f"/core/omd_services/{SV}").ok and drow("office_services", SV) is None and not in_trash(A, "omd_services", SV),
      "deleted for good: the row is gone")
check(A.delete(T + f"/core/omd_services/{SV}").status_code == 404, "a second delete for good: 404")
LIVE = A.post(OFC + "/services", json={"name_de": "Example Live"}).json()["id"]
check(A.post(T + f"/core/omd_services/{LIVE}/restore").status_code == 404 and A.delete(T + f"/core/omd_services/{LIVE}").status_code == 404
      and LIVE in ids(A, "services"), "a live row is not in the trash: 404, it stays")
check(A.post(T + f"/core/nokind/{LIVE}/restore").status_code == 404, "an unknown kind: 404")

# ---------------------------------------------------------------- the retention run is the core's (TIMESTAMPTZ columns)
OLDS = A.post(OFC + "/services", json={"name_de": "Example Old"}).json()["id"]
YNG = A.post(OFC + "/services", json={"name_de": "Example Young"}).json()["id"]
check(A.delete(OFC + f"/services/{OLDS}").ok and A.delete(OFC + f"/services/{YNG}").ok, "two services into the trash")
dbx("UPDATE office_services SET deleted_at=? WHERE id=?", ("2020-01-02T03:04:05+00:00", OLDS))
out = in_app("""from kalmido.core.writes import obj_trash_prune
print("PURGED", obj_trash_prune(c, "omd_services", purge=True))
c.commit()""")
check("PURGED 1" in out and drow("office_services", OLDS) is None and drow("office_services", YNG)[0], f"the old one gone for good, the young one stays {out[-300:]}")

# ---------------------------------------------------------------- a picking list never offers a row of the trash
EQ = A.post(OFC + "/equipment", json={"name": "Example Tripod"}).json()["id"]
check(A.delete(OFC + f"/equipment/{EQ}").ok, "a device into the trash")
r = A.post(OFC + "/sets", json={"name": "Example Bag", "items": [{"equipment_id": EQ, "qty": 1}]})
check(r.status_code == 400, f"a set with a device of the trash: 400 {r.status_code} {r.text[:120]}")
TX = A.post(OFC + "/texts", json={"kind": "intro", "key": "example-intro", "text_de": "Hello"}).json()["id"]
check(A.delete(OFC + f"/texts/{TX}").ok, "a text into the trash")
r = A.put(OFC + "/settings", json={"intro_text_id": {"de": TX}})
check(r.status_code == 400, f"the settings refuse a text of the trash {r.status_code} {r.text[:120]}")
check(not [x for x in A.get(OFC + "/texts?q=example-intro").json().get("items", []) if x["id"] == TX], "the search does not find it")
ST = A.post(OFC + "/sets", json={"name": "Example Moving Set"}).json()["id"]
check(A.delete(OFC + f"/sets/{ST}").ok, "a set into the trash")
r = A.post(OFC + "/move-space", json={"what": "sets", "ids": [ST], "dry": 1})  # 2.905.0 (#5414, review): not moved from the trash
check(r.status_code == 404 and drow("office_sets", ST)[0], f"a set of the trash is not moved to another workspace {r.status_code} {r.text[:120]}")
ex = A.get(OFC + "/export")
check(ex.ok and "example-intro" not in ex.text and "Example Tripod" not in ex.text, "the master data export leaves the trash out")

# ---------------------------------------------------------------- an old copy in office_trash (before 2.905) still comes back
OC = A.post(OFC + "/services", json={"name_de": "Example Old Copy"}).json()["id"]
row = json.loads(dbx("SELECT CAST(row_to_json(s) AS TEXT) FROM office_services s WHERE id=?", (OC,))[0][0])
snap = {"rows": [["office_services", [{k: v for k, v in row.items() if k not in ("deleted_at", "deleted_by", "rev", "created_by", "updated_by")}]]], "nulls": []}
TID = dbx("INSERT INTO office_trash(org_id, kind, sub, ref_id, label, snap, deleted_by, deleted_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",
          (ORG, "services", "", OC, "Example Old Copy", json.dumps(snap), AID, "2026-11-09T10:00:00.000Z"))[0][0]
dbx("DELETE FROM office_services WHERE id=?", (OC,))
# 2.1005.0 (#5415): the copy goes back into its table as a row of the core's trash (the start runs it; here by hand)
in_app("from kalmido.office.okern import ofk_copies_back\nprint(ofk_copies_back(c))\nc.commit()")
check(not dbx("SELECT 1 FROM office_trash WHERE id=?", (TID,)) and drow("office_services", OC)[0] is not None, "the old copy is a row of the core's trash")
check(in_trash(A, "omd_services", OC), "the old copy is listed (the core's kind)")
check(A.post(T + f"/core/omd_services/{OC}/restore").ok and OC in ids(A, "services") and drow("office_services", OC) == (None, None), "the old copy comes back live")

# ---------------------------------------------------------------- a rights group
R = OFC + "/rights"


def groups(s):
    r = s.get(R)
    return [x["id"] for x in r.json().get("groups", [])] if r.ok else None


r = A.post(R + "/groups", json={"name": "Example Editors"})
check(r.status_code == 201, f"rgroup: setup {r.text[:200]}")
GID = r.json()["id"]
check(A.put(R + f"/people/{uid['bob']}", json={"groups": [f"g:{GID}"]}).ok, "rgroup: bob in the group")
check(Bo.delete(R + f"/groups/{GID}").status_code == 403 and drow("office_rgroups", GID)[0] is None, "rgroup: a member 403")
r = A.delete(R + f"/groups/{GID}")
check(r.ok and r.json().get("trash") == {"kind": "orgroup", "id": GID}, f"rgroup: deleted into the core's trash {r.text[:200]}")
check(groups(A) is not None and GID not in groups(A) and drow("office_rgroups", GID)[1] == AID, "rgroup: gone from the rights page, the row stays")
check(not dbx("SELECT 1 FROM office_rgroup_members WHERE group_id=?", (GID,)), "rgroup: its members are taken out")
check(A.put(R + f"/people/{uid['bob']}", json={"groups": [f"g:{GID}"]}).status_code == 400, "rgroup: nobody can be put into a group of the trash")
t = in_trash(A, "orgroup", GID)
check(len(t) == 1 and t[0]["kind"] == "rgroup" and t[0]["label"] == "Example Editors", f"rgroup: in the office trash {t}")
check(Ol.post(T + f"/core/orgroup/{GID}/restore").status_code in (403, 404), "rgroup: another organisation: no restore")
# 2.905.0 (#5414, review): a parallel ofr_person_put put bob into the group while it was being deleted (simulated: his only row
# is one in the trashed group) - the restore takes him out with "No office access", never the implicit "Previous access"
BOB_ROWS = dbx("SELECT group_id, tpl FROM office_rgroup_members WHERE user_id=? AND org_id=(SELECT org_id FROM office_rgroups WHERE id=?)", (uid["bob"], GID))
dbx("DELETE FROM office_rgroup_members WHERE user_id=? AND org_id=(SELECT org_id FROM office_rgroups WHERE id=?)", (uid["bob"], GID))
dbx("INSERT INTO office_rgroup_members(org_id, user_id, group_id, created_at) SELECT org_id, ?, id, created_at FROM office_rgroups WHERE id=?", (uid["bob"], GID))
check(A.post(T + f"/core/orgroup/{GID}/restore?undo=1").ok and GID in (groups(A) or []), "rgroup: the toast's undo brings it back")
check(not dbx("SELECT 1 FROM office_rgroup_members WHERE group_id=?", (GID,)), "rgroup: back without its members (no rights handed out)")
check([tuple(x) for x in dbx("SELECT group_id, tpl FROM office_rgroup_members WHERE user_id=? AND org_id=(SELECT org_id FROM office_rgroups WHERE id=?)", (uid["bob"], GID))] == [(None, "none")],
      "rgroup: a member added during the delete is left with 'No office access', not 'Previous access' (review)")
dbx("DELETE FROM office_rgroup_members WHERE user_id=? AND org_id=(SELECT org_id FROM office_rgroups WHERE id=?)", (uid["bob"], GID))
for g_, t_ in BOB_ROWS:  # bob's rows as before the simulation
    dbx("INSERT INTO office_rgroup_members(org_id, user_id, group_id, tpl, created_at) SELECT org_id, ?, ?, ?, created_at FROM office_rgroups WHERE id=?", (uid["bob"], g_, t_, GID))
check(not dbx("SELECT 1 FROM obj_undo WHERE user_id=? AND kind='orgroup' AND ref_id=? AND mode IN ('trash', 'restore')", (AID, GID)),
      "rgroup: no step in the undo list (a redo would skip the member and manager checks, review)")  # 2.905.0 (#5414)
check(A.delete(R + f"/groups/{GID}").ok and A.post(T + f"/core/orgroup/{GID}/restore").ok and GID in (groups(A) or []), "rgroup: restored from the trash")

# ---------------------------------------------------------------- a fixed cost
FC = A.post(OFC + "/fixed-costs", json={"label": "Example Rent", "amount": "700", "start": "2026-01-01", "repeat": "monthly"}).json()["id"]
fixed = lambda s: [x["id"] for x in s.get(OFC + "/fixed-costs").json().get("items") or []]  # noqa: E731
r = A.delete(OFC + f"/fixed-costs/{FC}")
check(r.ok and r.json().get("trash") == {"kind": "ofixed", "id": FC} and FC not in fixed(A), f"fixed cost: into the trash, gone from the list {r.text[:200]}")
check(A.patch(OFC + f"/fixed-costs/{FC}", json={"label": "Changed"}).status_code == 404, "fixed cost: one in the trash is not saved (404)")
t = in_trash(A, "ofixed", FC)
check(len(t) == 1 and t[0]["kind"] == "fixed_cost" and t[0]["label"] == "Example Rent", f"fixed cost: in the office trash {t}")
check(A.post(T + f"/core/ofixed/{FC}/restore").ok and FC in fixed(A), "fixed cost: restored, back in the list")

# ---------------------------------------------------------------- a correction of the cash flow
r = A.post(OFC + "/cashflow/adjust", json={"month": "2026-12", "dir": "out", "amount": "120", "note": "Example cash"})
check(r.status_code == 201, f"correction: setup {r.text[:200]}")
AJ = r.json()["id"]


def adj(s):
    j = s.get(OFC + "/cashflow?from=2026-12&months=1").json()
    return [e["id"] for e in j.get("adjust") or []]


n0 = adj(A)
r = A.delete(OFC + f"/cashflow/adjust/{AJ}")
check(n0 == [AJ] and r.ok and r.json().get("trash") == {"kind": "oadjust", "id": AJ} and adj(A) == [], f"correction: into the trash, not counted {n0} {r.text[:200]}")
t = in_trash(A, "oadjust", AJ)
check(len(t) == 1 and t[0]["kind"] == "cf_adjust" and t[0]["label"] == "2026-12", f"correction: in the office trash {t}")
check(A.post(T + f"/core/oadjust/{AJ}/restore").ok and adj(A) == [AJ], "correction: restored, counted again")

# ---------------------------------------------------------------- review 2.905.0 (#5414): a contract in the trash holds no client, takes no files
r = A.post(B + "/api/clients", json={"name": "Example Client Hold", "email": "hold@example.com", "org_id": ORG})
check(r.ok, f"setup: a client {r.text[:200]}")
CLI = r.json().get("id")
CT = A.post(OFC + "/contracts", json={"name": "Example Held Contract", "client_id": CLI}).json()["id"]
dbx("UPDATE office_contracts SET client_id=? WHERE id=?", (CLI, CT))
held = "from kalmido.team.clients import cl_hold_sql\nprint('HOLD', c.execute('SELECT COUNT(*) FROM clients WHERE id=%d' + cl_hold_sql()).fetchone()[0])"
check("HOLD 0" in in_app(held % CLI), "a live contract holds its client")
check(A.get(OFC + f"/contracts/{CT}/files").ok, "a live contract lists its files")
check(A.delete(OFC + f"/contracts/{CT}").ok, "contract: into the trash")
out = in_app(held % CLI)
check("HOLD 1" in out, f"a contract in the trash holds its client no more {out[-300:]}")
check(A.get(OFC + f"/contracts/{CT}/files").status_code == 404, "a contract in the trash: its files 404")

# ---------------------------------------------------------------- a person without an organisation (her personal office)
check(Fr.get(OFC + "/services").ok, "freelancer: her office opens")
FS = Fr.post(OFC + "/services", json={"name_de": "Example Freelance Day"}).json()["id"]
check(A.delete(OFC + f"/services/{FS}").status_code == 404 and drow("office_services", FS)[0] is None, "someone else: 404 on her service")
check(Fr.delete(OFC + f"/services/{FS}").ok and FS not in ids(Fr, "services") and drow("office_services", FS)[1] == FID, "freelancer: into the trash")
check(in_trash(Fr, "omd_services", FS) and not in_trash(A, "omd_services", FS), "freelancer: in her trash only")
check(A.post(T + f"/core/omd_services/{FS}/restore").status_code == 404, "someone else: no restore (404)")
check(Fr.post(T + f"/core/omd_services/{FS}/restore").ok and FS in ids(Fr, "services"), "freelancer: restored")
check(Fr.delete(OFC + f"/services/{FS}").ok and Fr.delete(T + f"/core/omd_services/{FS}").ok and drow("office_services", FS) is None,
      "freelancer: deleted for good")

# ---------------------------------------------------------------- 2.990.0 (#5539): the undo of a data import (office/legacyimport.py
# fi_undo) deletes the run's master data on the core's way: a live row and one the person put into the trash since go for
# good with their history (was: a plain DELETE of every row of the run, obj_history / obj_undo left behind); as a person
# without an organisation (her personal office; the organisation's undo is the same code)
PBF = dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
RUN = dbx("INSERT INTO office_import_runs(org_id, kind, counts, detail, created_by, created_at) VALUES(?, 'data', '{}', '{}', ?, ?) RETURNING id",
          (PBF, FID, "2026-01-02T03:04:05+00:00"))[0][0]
IS = [Fr.post(OFC + "/services", json={"name_de": f"Example Imported {i}"}).json()["id"] for i in (1, 2)]
dbx(f"UPDATE office_services SET import_run_id=? WHERE id IN ({IS[0]}, {IS[1]})", (RUN,))
check(Fr.delete(OFC + f"/services/{IS[1]}").ok and drow("office_services", IS[1])[0], "import undo: one imported service into the trash since")
for i in IS:  # what the core keeps per row (a change of it): must go with the row
    dbx("INSERT INTO obj_history(kind, ref_id, org_id, user_id, action, created_at, updated_at) VALUES('omd_services', ?, ?, ?, 'update', ?, ?)",
        (i, PBF, FID, "2026-01-02T03:04:05+00:00", "2026-01-02T03:04:05+00:00"))
r = Fr.post(OFC + f"/legacy/runs/{RUN}/undo", json={"kinds": ["services"]})
check(r.ok and (r.json().get("removed") or {}).get("services") == 1, f"import undo: the live service counted removed {r.status_code} {r.text[:200]}")
check(drow("office_services", IS[0]) is None and drow("office_services", IS[1]) is None, "import undo: the live service and the one in the trash are gone")
left = dbx(f"SELECT ref_id FROM obj_history WHERE kind='omd_services' AND ref_id IN ({IS[0]}, {IS[1]})")
check(not left, f"import undo: no history of the removed services left behind (was: orphaned) {left}")
check(not in_trash(Fr, "omd_services", IS[1]), "import undo: nothing of the run left in her trash")

# ---------------------------------------------------------------- 2.1015.0 (#5675): the undo of a big import (3000 master data rows,
# FI_ROWS_MAX is 2000 per sheet and four kinds) goes through: okern.ofk_purge_many holds a few locks for all of them, not one
# advisory lock per row until the commit (out of shared memory at max_locks_per_transaction); as a person without an organisation
RUN2 = dbx("INSERT INTO office_import_runs(org_id, kind, counts, detail, created_by, created_at) VALUES(?, 'data', '{}', '{}', ?, ?) RETURNING id",
           (PBF, FID, "2026-01-02T03:04:05+00:00"))[0][0]
dbx("INSERT INTO office_services(org_id, name_de, import_run_id, created_at, updated_at) SELECT ?, 'Example Bulk ' || g, ?, ?, ? "
    "FROM generate_series(1, 3000) g", (PBF, RUN2, "2026-01-02T03:04:05+00:00", "2026-01-02T03:04:05+00:00"))
BULK = [x[0] for x in dbx("SELECT id FROM office_services WHERE import_run_id=? ORDER BY id", (RUN2,))]
dbx("INSERT INTO obj_history(kind, ref_id, org_id, user_id, action, created_at, updated_at) SELECT 'omd_services', id, ?, ?, 'update', ?, ? "
    "FROM office_services WHERE import_run_id=?", (PBF, FID, "2026-01-02T03:04:05+00:00", "2026-01-02T03:04:05+00:00", RUN2))
r = Fr.post(OFC + f"/legacy/runs/{RUN2}/undo", json={"kinds": ["services"]})
check(len(BULK) == 3000 and r.ok and (r.json().get("removed") or {}).get("services") == 3000,
      f"big import undo: 3000 services removed in one go {len(BULK)} {r.status_code} {r.text[:200]}")
check(not dbx("SELECT 1 FROM office_services WHERE import_run_id=? LIMIT 1", (RUN2,))
      and not dbx(f"SELECT 1 FROM obj_history WHERE kind='omd_services' AND ref_id IN ({','.join(map(str, BULK))}) LIMIT 1"),
      "big import undo: every row and its history gone")
# the mechanism: before the commit the purging transaction holds ONE advisory lock, whatever the number of rows (was one per row)
dbx("INSERT INTO office_services(org_id, name_de, import_run_id, created_at, updated_at) SELECT ?, 'Example Lock ' || g, ?, ?, ? "
    "FROM generate_series(1, 300) g", (PBF, RUN2, "2026-01-02T03:04:05+00:00", "2026-01-02T03:04:05+00:00"))
r = subprocess.run(["docker", "exec", kt.CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n"
                    "from kalmido.office.okern import ofk_purge_many\nfrom kalmido.core.pg import system_ctx\n"
                    "with system_ctx(c):\n"
                    f"    ids = [x[0] for x in c.execute('SELECT id FROM office_services WHERE import_run_id=?', ({int(RUN2)},)).fetchall()]\n"
                    "    n = ofk_purge_many(c, 'omd_services', ids)\n"
                    "    k = c.execute(\"SELECT COUNT(*) FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()\").fetchone()[0]\n"
                    "c.commit()\nprint('purged', n, 'advisory', k)"], capture_output=True, text=True, timeout=300)
out = (r.stdout + r.stderr).strip()
check("purged 300 advisory 1\n" in out + "\n" and not dbx("SELECT 1 FROM office_services WHERE import_run_id=? LIMIT 1", (RUN2,)),
      f"ofk_purge_many: 300 rows, one advisory lock held until the commit (was 300) {out[-300:]}")

sys.exit(done("p2905_d_office_trash_4c"))
