#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1004.0 (#5494, stage 4c rest of the core's trash): the approval records of deleted video reviews (office_signoffs,
kind video, video_id NULL; settings > Move and export everything) are deleted into the ONE trash of the core (office/okern.py
ofk_register kind osignoff, personal="created_by") instead of a copy in office_trash and the row deleted; the limits of the
fixed costs and of the corrections per month hold on a restore too. Invented names only.
 - an organisation's record: delete -> {trash: {kind osignoff, id}}, gone from the list, in the office trash (kind signoff,
   its title) -> a member 403, another organisation 404 -> restore -> listed again; no step in the undo list; delete for
   good from the office trash: the row and its core history are gone
 - a person without an organisation WITH a personal office: her record into her own office trash (nobody else's), someone
   else 404 on restore, she restores it; the core's retention run deletes one past the period with its history
 - a person without a personal office: the record goes for good, no core history left behind (as before: no office trash)
 - the account's end takes a private record of the trash with its history
 - review 2.905 (b): a fixed cost back from the trash past MAX_FIXED -> 409 (office trash and the toast's undo), it stays in
   the trash; a correction past CFS_MAX_MONTH -> 409, also through the person's undo list
tenant-matrix: office (another organisation: 404 on a record of the core's trash)
freelancer-matrix: office (a person without an organisation: her record deleted, listed in her trash, restored, purged)
usage: p21004_b_signoff_trash_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

fresh(prefix="P21004B")
OFC = B + "/api/office"
T = OFC + "/trash"
ORPH = B + "/api/videos/signoffs/orphaned"
NOW = "2026-11-01T10:00:00+00:00"

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
GID, Gs = freelancer(B, A, "gert")


def sig(org, by, title):
    tok = os.urandom(8).hex()
    return dbx("""INSERT INTO office_signoffs(org_id, kind, title, token_hash, token, state, created_by, created_at)
                  VALUES(?,'video',?,?,?,'open',?,?) RETURNING id""", (org, title, tok, tok, by, NOW))[0][0]


def listed(s):
    r = s.get(ORPH)
    return [x["id"] for x in r.json().get("signoffs") or []] if r.ok else None


def in_trash(s, core, rid):
    r = s.get(T)
    return [x for x in (r.json().get("items") or [] if r.ok else []) if x.get("core") == core and x.get("id") == rid]


def deleted(rid, table="office_signoffs"):
    r = dbx(f"SELECT deleted_at IS NOT NULL FROM {table} WHERE id=?", (rid,))
    return r[0][0] if r else None


def hist(kind, rid):
    return dbx("SELECT COUNT(*) FROM obj_history WHERE kind=? AND ref_id=?", (kind, rid))[0][0]


# ---------------------------------------------------------------- an organisation's record
S1 = sig(ORG, AID, "Example Rough Cut")
check(S1 in (listed(A) or []), "org: setup, an orphaned record is listed")
r = A.delete(ORPH + f"/{S1}")
check(r.ok and r.json().get("trash") == {"kind": "osignoff", "id": S1} and "trash_id" not in r.json(), f"org: into the core's trash {r.text[:200]}")
check(deleted(S1) is True and S1 not in (listed(A) or []), "org: the row carries deleted_at and is no longer listed")
check(not dbx("SELECT 1 FROM office_trash WHERE kind='signoff'"), "org: no copy in office_trash any more")
t = in_trash(A, "osignoff", S1)
check(len(t) == 1 and t[0]["kind"] == "signoff" and t[0]["label"] == "Example Rough Cut", f"org: the office trash lists it with its title {t}")
check(Bo.post(T + f"/core/osignoff/{S1}/restore").status_code == 403, "org: a member may not restore it (403)")
check(Ol.post(T + f"/core/osignoff/{S1}/restore").status_code == 404 and Ol.delete(T + f"/core/osignoff/{S1}").status_code == 404,
      "org: another organisation 404 (restore, delete for good)")
check(not dbx("SELECT 1 FROM obj_undo WHERE user_id=? AND kind='osignoff'", (AID,)), "org: no step in the undo list (the legal period check would be skipped)")
r = A.post(T + f"/core/osignoff/{S1}/restore")
check(r.ok and r.json().get("kind") == "signoff" and deleted(S1) is False and S1 in (listed(A) or []), f"org: restored, listed again {r.text[:200]}")
check(A.delete(ORPH + f"/{S1}").ok and hist("osignoff", S1) >= 1, "org: into the trash again (core history written)")
r = A.delete(T + f"/core/osignoff/{S1}")
check(r.ok and not dbx("SELECT 1 FROM office_signoffs WHERE id=?", (S1,)) and hist("osignoff", S1) == 0,
      f"org: deleted for good from the office trash, with its core history {r.text[:200]}")

# ---------------------------------------------------------------- a person without an organisation, with a personal office
check(Fr.get(OFC + "/services").ok, "freelancer: her office opens (her personal office exists)")
S2 = sig(None, FID, "Example Freelance Cut")
check(listed(Fr) == [S2] and S2 not in (listed(A) or []), "freelancer: her private record, only hers")
check(A.delete(ORPH + f"/{S2}").status_code == 404, "freelancer: someone else 404 on delete")
r = Fr.delete(ORPH + f"/{S2}")
check(r.ok and r.json().get("trash") == {"kind": "osignoff", "id": S2} and deleted(S2) is True, f"freelancer: into the core's trash {r.text[:200]}")
t = in_trash(Fr, "osignoff", S2)
check(len(t) == 1 and t[0]["label"] == "Example Freelance Cut" and not in_trash(A, "osignoff", S2), f"freelancer: in her office trash only {t}")
check(A.post(T + f"/core/osignoff/{S2}/restore").status_code == 404 and Gs.post(T + f"/core/osignoff/{S2}/restore").status_code in (403, 404),
      "freelancer: nobody else restores it")
check(Fr.post(T + f"/core/osignoff/{S2}/restore").ok and deleted(S2) is False and listed(Fr) == [S2], "freelancer: restored, listed again")
check(Fr.delete(ORPH + f"/{S2}").ok, "freelancer: into the trash again")
dbx("UPDATE office_signoffs SET deleted_at='2000-01-01T00:00:00+00:00' WHERE id=?", (S2,))
out = in_app("from kalmido.core.writes import obj_trash_prune\nprint('N', obj_trash_prune(c, 'osignoff', None, True))\nc.commit()")
check("N 1" in out and not dbx("SELECT 1 FROM office_signoffs WHERE id=?", (S2,)) and hist("osignoff", S2) == 0,
      f"freelancer: the core's retention run deletes it past the period, with its history {out[-300:]}")

# ---------------------------------------------------------------- a person without a personal office
check(not dbx("SELECT 1 FROM orgs WHERE personal_of=?", (GID,)), "no office: setup, gert has no personal office")
S3 = sig(None, GID, "Example Left Cut")
r = Gs.delete(ORPH + f"/{S3}")
check(r.ok and "trash" not in r.json() and not dbx("SELECT 1 FROM office_signoffs WHERE id=?", (S3,)) and hist("osignoff", S3) == 0,
      f"no office: deleted for good as before, nothing of the core left {r.text[:200]}")
check(not dbx("SELECT 1 FROM orgs WHERE personal_of=?", (GID,)), "no office: none was made")

# ---------------------------------------------------------------- the account's end
S4 = sig(None, FID, "Example Gone Cut")
check(Fr.delete(ORPH + f"/{S4}").ok and deleted(S4) is True and hist("osignoff", S4) >= 1, "account end: setup, a record in her trash")
r = A.delete(B + f"/api/users/{FID}")
check(r.ok and not dbx("SELECT 1 FROM office_signoffs WHERE id=?", (S4,)) and hist("osignoff", S4) == 0,
      f"account end: her record of the trash goes with its core history {r.status_code} {r.text[:160]}")

# ---------------------------------------------------------------- review 2.905 (b): a fixed cost past MAX_FIXED
FC = A.post(OFC + "/fixed-costs", json={"label": "Example Rent", "amount": "700", "start": "2026-01-01", "repeat": "monthly"}).json()["id"]
check(A.delete(OFC + f"/fixed-costs/{FC}").ok and deleted(FC, "office_fixed_costs") is True, "fixed cost: into the trash")
dbx("""INSERT INTO office_fixed_costs(org_id, label, amount, start, repeat, created_by, created_at, updated_at)
       SELECT ?, 'Example Filler', '1', '2026-01-01', 'monthly', ?, ?, ? FROM generate_series(1, 500)""", (ORG, AID, NOW, NOW))
r = A.post(T + f"/core/ofixed/{FC}/restore")
check(r.status_code == 409 and deleted(FC, "office_fixed_costs") is True, f"fixed cost: 500 live ones, the restore refused (409), still in the trash {r.status_code} {r.text[:160]}")
r = A.post(T + f"/core/ofixed/{FC}/restore?undo=1")
check(r.status_code == 409 and deleted(FC, "office_fixed_costs") is True, f"fixed cost: the toast's undo refused too {r.status_code}")
dbx("DELETE FROM office_fixed_costs WHERE org_id=? AND label='Example Filler'", (ORG,))
check(A.post(T + f"/core/ofixed/{FC}/restore").ok and deleted(FC, "office_fixed_costs") is False, "fixed cost: under the limit it comes back")

# ---------------------------------------------------------------- a correction past CFS_MAX_MONTH (office trash and undo list)
r = A.post(OFC + "/cashflow/adjust", json={"month": "2027-01", "dir": "out", "amount": "120", "note": "Example cash"})
check(r.status_code == 201, f"correction: setup {r.text[:200]}")
AJ = r.json()["id"]
check(A.delete(OFC + f"/cashflow/adjust/{AJ}").ok and deleted(AJ, "office_cf_adjust") is True, "correction: into the trash")
gid = next((x["id"] for x in A.get(B + "/api/undo").json().get("items") or [] if x.get("kind") == "oadjust" and x.get("ref_id") == AJ), None)
check(gid, "correction: its trash step is in the undo list")
dbx("""INSERT INTO office_cf_adjust(org_id, month, dir, amount, note, created_by, created_at, updated_at)
       SELECT ?, '2027-01', 'in', '1', '', ?, ?, ? FROM generate_series(1, 50)""", (ORG, AID, NOW, NOW))
r = A.post(T + f"/core/oadjust/{AJ}/restore")
check(r.status_code == 409 and deleted(AJ, "office_cf_adjust") is True, f"correction: 50 in its month, the restore refused (409) {r.status_code} {r.text[:160]}")
r = A.post(B + f"/api/undo/to/{gid}")
check(deleted(AJ, "office_cf_adjust") is True and not (r.ok and gid in (r.json().get("undone") or [])),
      f"correction: the undo list does not bring it back past the limit either {r.status_code} {r.text[:200]}")
dbx("DELETE FROM office_cf_adjust WHERE org_id=? AND month='2027-01' AND id<>?", (ORG, AJ))
check(A.post(T + f"/core/oadjust/{AJ}/restore").ok and deleted(AJ, "office_cf_adjust") is False, "correction: under the limit it comes back")

sys.exit(done("p21004_b_signoff_trash"))
