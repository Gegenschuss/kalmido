#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1067.0 (#5789, stage 4e of the core's trash) API test: the start balance of the cash flow (office_cf_start, one row per
office) goes into the ONE trash of the core (kind ocfstart, office/cfstart.py) instead of a copy in office_trash; the copies'
routes are gone; an old copy (key org_id, made by hand as cfstart.py made it before 2.1067) is written back at the start.
Invented names and figures only.
freelancer-matrix: office (a person without an organisation: every step in her personal office)
tenant-matrix: office (another organisation: no undo, no restore, no delete for good of the start balance in the trash)
 - deleted: the row stays with deleted_at (id = the office's org_id), no copy in office_trash; the answer names
   trash {kind: ocfstart, id}; the start balance and the cash flow's account balance are gone
 - the office trash lists it with its label (the day) as cf_start; restored there: amount and day come back, the cash flow
   shows the account balance again
 - the delete is a step of the person's undo list (GET /api/undo, kind ocfstart)
 - the toast's undo (core restore ?undo=1) brings it back; another office 403 / 404; a member 403
 - set again while one lies in the trash: the one in the trash goes for good (no entry left, its undo 404), the new value
   stays; deleted for good from the office trash: the row is gone
 - an old copy in office_trash (key org_id, the row deleted) comes back as a row of the core's trash at the start
   (okern.ofk_copies_back): deleted_at / deleted_by of the copy, listed, restored with amount and day; a copy whose start
   balance was set again meanwhile stays a copy and is never listed
 - the copies' routes are gone: POST /api/office/trash/undo/cf_start/<id>, POST /api/office/trash/<id>/restore,
   DELETE /api/office/trash/<id> answer 404 / 405
usage: p21067_b_cfstart_trash_test.py <datadir>"""
import base64
import json
import os
import sys
from datetime import timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from office_trash_old import OLD_DDL, dropped, gone  # noqa: E402  2.1073.0 (#5865)
from obj_probe import in_app  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P21050B")
OFC = B + "/api/office"
ST = OFC + "/cashflow/start"
TODAY = testclock.today()
MONTH = TODAY.isoformat()[:7]
PM = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=3)
PM1, PM2 = PM.isoformat(), (PM + timedelta(days=4)).isoformat()


def start(s):
    return s.get(ST).json().get("start")


def account(s):
    """The cash flow's running account balance of this month (None without a start balance)."""
    r = s.get(OFC + f"/cashflow?from={MONTH}&months=1&basis=gross")
    j = r.json() if r.ok else {}
    return (j.get("start"), next((x.get("account") for x in j.get("rows") or [] if x["month"] == MONTH), None))


def listed(s, oid):
    return [x for x in s.get(OFC + "/trash").json().get("items") or [] if x.get("core") == "ocfstart" and x["id"] == oid]


def row(oid):
    r = dbx("SELECT id, deleted_at, deleted_by FROM office_cf_start WHERE org_id=?", (oid,))
    return r[0] if r else None


def old_copy(oid, uid, when="2099-01-09T10:00:00.000Z"):
    """2.1067.0 review (F1): dated after the row's last save, as a real copy is (the app's start revives a trashed row
    saved after its delete, office/cfstart.py cfs_start_fix; in_app runs that start). The start balance of oid as a copy in office_trash and the row deleted, as cfstart.py (otrash.otb_put, key org_id) did
    before 2.1067 -> the copy's id."""
    raw = json.loads(dbx("SELECT CAST(row_to_json(x) AS TEXT) FROM office_cf_start x WHERE org_id=?", (oid,))[0][0])
    snap = {"rows": [["office_cf_start", [{k: v for k, v in raw.items() if k not in ("id", "deleted_at", "deleted_by", "rev")}]]],
            "nulls": [], "key": "org_id"}
    dbx(OLD_DDL)  # 2.1073.0 (#5865): the table as the versions before made it (every start of the app drops it again)
    tid = dbx("INSERT INTO office_trash(org_id, kind, sub, ref_id, label, snap, deleted_by, deleted_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",
              (oid, "cf_start", "", oid, raw.get("day") or "", json.dumps(snap), uid, when))[0][0]
    dbx("DELETE FROM office_cf_start WHERE org_id=?", (oid,))
    return tid


def copies_back():
    out = in_app("from kalmido.office.okern import ofk_copies_back\nprint('BACK', ofk_copies_back(c))\nc.commit()")
    check("BACK" in out, f"the copies' run {out[-300:]}")
    return out


def scenario(S, who, oid, uid, other, member=None):
    # ------------------------------------------------------------ deleted into the core's trash
    r = S.put(ST, json={"amount": "2500.00", "day": PM1})
    check(r.ok and (start(S) or {}).get("amount") == "2500.00", f"{who}: setup start balance {r.text[:200]}")
    st0, acc0 = account(S)
    check(st0 and acc0 is not None, f"{who}: setup: the cash flow shows the account balance {st0} {acc0}")
    r = S.delete(ST)
    tr0 = (r.json().get("trash") or {}) if r.ok else {}
    check(r.ok and tr0 == {"kind": "ocfstart", "id": oid} and "trash_id" not in r.json() and (r.json().get("prev") or {}).get("amount") == "2500.00",
          f"{who}: DELETE answers where it lies in the core's trash {r.text[:200]}")
    rw = row(oid)
    check(rw and rw[0] == oid and rw[1] and rw[2] == uid and gone(dbx),
          f"{who}: the row stays with deleted_at / deleted_by, no copy (2.1073.0 #5865: no table office_trash at all) {rw}")
    check(start(S) is None and account(S) == (None, None), f"{who}: the start balance and the account balance are gone {account(S)}")
    it = listed(S, oid)
    check(it and it[0]["kind"] == "cf_start" and it[0]["label"] == PM1, f"{who}: the office trash lists it with its day {it}")
    gid = next((x["id"] for x in S.get(B + "/api/undo").json().get("items") or [] if x.get("kind") == "ocfstart" and x.get("ref_id") == oid), None)
    check(gid, f"{who}: the delete is a step of the person's undo list (the core's history)")
    # ------------------------------------------------------------ restored in the office trash
    check(other.post(OFC + f"/trash/core/ocfstart/{oid}/restore").status_code in (403, 404) and row(oid)[1],
          f"{who}: another office: no restore")  # tenant: POST /api/office/trash/core/{}/{}/restore
    r = S.post(OFC + f"/trash/core/ocfstart/{oid}/restore")
    st = start(S) or {}
    check(r.ok and r.json().get("kind") == "cf_start" and st.get("amount") == "2500.00" and st.get("day") == PM1 and account(S) == (st0, acc0),
          f"{who}: the office trash brings amount and day back, the cash flow as before {r.text[:200]} {st} {account(S)}")
    check(not listed(S, oid), f"{who}: no longer listed")
    # ------------------------------------------------------------ the toast's undo (the core's restore ?undo=1)
    r = S.delete(ST)
    check(r.ok and (r.json().get("trash") or {}).get("id") == oid, f"{who}: deleted again {r.text[:200]}")
    check(other.post(OFC + f"/trash/core/ocfstart/{oid}/restore?undo=1").status_code in (403, 404), f"{who}: another office: the undo 403 / 404")
    if member is not None:
        check(member.post(OFC + f"/trash/core/ocfstart/{oid}/restore?undo=1").status_code == 403, f"{who}: a member: the undo 403")
    r = S.post(OFC + f"/trash/core/ocfstart/{oid}/restore?undo=1")
    check(r.ok and (start(S) or {}).get("amount") == "2500.00", f"{who}: the undo brings it back {r.text[:200]}")
    check(S.post(OFC + f"/trash/core/ocfstart/{oid}/restore?undo=1").status_code == 404, f"{who}: a second undo 404")
    # ------------------------------------------------------------ set again while one lies in the trash
    S.delete(ST)
    r = S.put(ST, json={"amount": "-80.00", "day": PM2})
    st = start(S) or {}
    check(r.ok and r.json().get("prev") is None and st.get("amount") == "-80.00" and st.get("day") == PM2 and not listed(S, oid)
          and row(oid)[1] is None, f"{who}: a new start balance: the one in the trash went for good {r.text[:200]} {st}")
    r = S.post(OFC + f"/trash/core/ocfstart/{oid}/restore?undo=1")
    check(r.status_code == 404 and (start(S) or {}).get("amount") == "-80.00", f"{who}: its undo 404, the new value stays {r.status_code}")
    # ------------------------------------------------------------ deleted for good from the office trash
    S.delete(ST)
    check(other.delete(OFC + f"/trash/core/ocfstart/{oid}").status_code in (403, 404) and row(oid),
          f"{who}: another office: no delete for good")  # tenant: DELETE /api/office/trash/core/{}/{}
    r = S.delete(OFC + f"/trash/core/ocfstart/{oid}")
    check(r.ok and row(oid) is None and not listed(S, oid), f"{who}: deleted for good, the row is gone {r.text[:200]}")
    # ------------------------------------------------------------ the copies' routes are gone
    check(S.post(OFC + f"/trash/undo/cf_start/{oid}").status_code in (404, 405), f"{who}: the copies' undo route is gone")
    check(S.post(OFC + f"/trash/{oid}/restore").status_code in (404, 405) and S.delete(OFC + f"/trash/{oid}").status_code in (404, 405),
          f"{who}: the copies' restore / delete routes are gone")
    # ------------------------------------------------------------ an old copy written back at the start
    check(S.put(ST, json={"amount": "1234.56", "day": PM1}).ok, f"{who}: setup start balance for the old copy")
    sealed = dbx("SELECT amount FROM office_cf_start WHERE org_id=?", (oid,))[0][0]
    check(str(sealed).startswith("kenc1:"), f"{who}: setup: the amount is sealed at rest")
    old_copy(oid, uid)
    check(start(S) is None and not listed(S, oid), f"{who}: setup: an old copy (not listed any more)")
    out = copies_back()
    rw = row(oid)
    check(gone(dbx) and dropped(out) == 0 and rw and rw[0] == oid and rw[1] and rw[2] == uid
          and dbx("SELECT amount FROM office_cf_start WHERE org_id=?", (oid,))[0][0] == sealed,
          f"{who}: the copy is a row of the core's trash (deleted_by of the copy, sealed as stored) {rw} {out[-200:]}")
    it = listed(S, oid)
    check(it and it[0]["kind"] == "cf_start" and it[0]["label"] == PM1 and str(it[0]["deleted_at"]).startswith("2099-01-09"),
          f"{who}: listed with the copy's day and time {it}")
    r = S.post(OFC + f"/trash/core/ocfstart/{oid}/restore")
    st = start(S) or {}
    check(r.ok and st.get("amount") == "1234.56" and st.get("day") == PM1, f"{who}: restored: amount and day readable {r.text[:200]} {st}")
    # a copy whose start balance was set again meanwhile stays a copy, never listed
    old_copy(oid, uid)
    check(S.put(ST, json={"amount": "10.00", "day": PM2}).ok, f"{who}: setup: set again after the copy")
    out = copies_back()
    # 2.1073.0 (#5865): it stays a copy in the run, then goes with the table
    check(gone(dbx) and dropped(out) == 1 and (start(S) or {}).get("amount") == "10.00" and not listed(S, oid),
          f"{who}: set again meanwhile: the copy is not written back (it goes with the table), the new value stays, nothing listed {out[-200:]}")
    # review 2.1067.0 (F1): an older version (after a step back) set the start balance again on a row of the trash - its
    # upsert leaves deleted_at: at the next start the row is live again; a row deleted after its last save stays in the trash
    S.delete(ST)
    dbx("UPDATE office_cf_start SET deleted_at=deleted_at - interval '1 hour', updated_at=? WHERE org_id=?",
        ("2100-01-01T00:00:00.000Z", oid))
    # the start of in_app's process runs cfs_start_fix already (kalmido/startup.py); the explicit call finds nothing left then
    out = in_app("from kalmido.office.cfstart import cfs_start_fix\nprint('FIX', cfs_start_fix(c))\nc.commit()")
    check("FIX" in out and (start(S) or {}).get("amount") == "10.00" and row(oid)[1] is None and not listed(S, oid),
          f"{who}: a start balance an older version set on a trashed row is live again {out[-200:]}")
    dbx("UPDATE office_cf_start SET updated_at=? WHERE org_id=?", ("2000-01-01T00:00:00.000Z", oid))  # its save before the delete
    S.delete(ST)
    out = in_app("from kalmido.office.cfstart import cfs_start_fix\nprint('FIX', cfs_start_fix(c))\nc.commit()")
    check("FIX 0" in out and start(S) is None and listed(S, oid), f"{who}: a start balance deleted after its save stays in the trash {out[-200:]}")
    S.post(OFC + f"/trash/core/ocfstart/{oid}/restore")
    S.delete(ST)
    S.delete(OFC + f"/trash/core/ocfstart/{oid}")


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
ALICE = dbx("SELECT id FROM users WHERE username='alice'")[0][0]
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Example Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Example Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Fr = freelancer(B, A, "frida")  # freelancer-matrix: office (the personal office, its own admin)
Fr.get(OFC + "/settings")  # the personal office comes with the first office call
PERS = dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
for s in (A, Ca, Fr):
    s.put(OFC + "/settings", json={"lang": "en", "currency": "EUR"})

scenario(A, "alice", ORG, ALICE, Ca, member=Bo)
scenario(Fr, "frida", PERS, FID, A)
sys.exit(done("p21067_b_cfstart_trash"))
