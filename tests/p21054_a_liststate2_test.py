#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1054.0 (#5794, stage 2 of the projects' state marker): the write paths of the archive set lists.state through
core/access.py list_set_archived(); the trigger kalmido_list_state (migrations.d/5537_a.py) writes the old column archived
from the marker (the way back for a version before) and keeps 'trash' from deleted_at (the trash of the core). Invented names.
 - archive / restore through the route (a person without an organisation): marker, archived and archived_at follow; archiving
   an archived project again keeps its moment
 - the marker written by hand to 'archived' / 'live' sets archived (what a version before reads); a write of archived alone (a
   version before, the undo of the settings) still sets the marker; a write of state='trash' decides nothing
 - an INSERT that names state 'archived' gets archived=1; one that names archived=1 (a copy of an older row) gets 'archived'
 - the way back: with the trigger of stage 1 (a version before) the rows written by this one read right, its writes set the
   marker; the trigger of this version again: the marker decides
 - a project in the trash taken out of the archive (list_set_archived) stays in the trash and comes back live
 - the organisation admin's archive (POST /api/orgs/<oid>/lists/<lid>/archive) and the quick-notes project brought back from
   the archive (POST /api/notes/quick-list) go through the marker
 - the app's project list still shows archived true / false (no change of shape)
 - the whole table: archived agrees with the marker
freelancer-matrix: tasks (a person without an organisation archives and restores her projects through the marker)
usage: p21054_a_liststate2_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402

fresh(prefix="P21054A")

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


# ---------------------------------------------------------------- the route writes the marker, archived follows
P1 = plist(Fr, "Example Garden Plan")
r = Fr.patch(B + f"/api/lists/{P1}", json={"archived": True})
st, ar, at, _ = row(P1)
check(r.ok and st == "archived" and ar == 1 and at, f"archived through the route: marker, archived and its moment {r.status_code} {row(P1)}")
dbx("UPDATE lists SET archived_at='2026-01-02T03:04:05+00:00' WHERE id=?", (P1,))
r = Fr.patch(B + f"/api/lists/{P1}", json={"archived": True})
check(r.ok and row(P1)[:3] == ("archived", 1, "2026-01-02T03:04:05+00:00"), f"archived again: its moment stays {row(P1)}")
r = Fr.patch(B + f"/api/lists/{P1}", json={"archived": False})
check(r.ok and row(P1)[:3] == ("live", 0, None), f"out of the archive: live, archived 0, no moment {r.status_code} {row(P1)}")
ls = {x["id"]: x for x in Fr.get(B + "/api/state").json().get("lists", [])}
check(P1 in ls and ls[P1].get("archived") in (0, False) and ls[P1].get("name") == "Example Garden Plan",
      f"the project list shows it live with its name {ls.get(P1)}")
Fr.patch(B + f"/api/lists/{P1}", json={"archived": True})
ls = {x["id"]: x for x in Fr.get(B + "/api/state").json().get("lists", [])}
check(P1 in ls and ls[P1].get("archived") in (1, True) and ls[P1].get("state") == "archived",
      f"the project list shows archived true as before (no change of shape) {ls.get(P1)}")

# ---------------------------------------------------------------- both ways in the database
P2 = plist(Fr, "Example Kitchen Shelves")
dbx("UPDATE lists SET state='archived' WHERE id=?", (P2,))
check(row(P2)[:2] == ("archived", 1), f"the marker written to 'archived': archived=1 for a version before {row(P2)}")
dbx("UPDATE lists SET state='live' WHERE id=?", (P2,))
check(row(P2)[:2] == ("live", 0), f"the marker written to 'live': archived=0 {row(P2)}")
dbx("UPDATE lists SET archived=true WHERE id=?", (P2,))
check(row(P2)[:2] == ("archived", 1), f"archived written alone (a version before, the undo): the marker follows {row(P2)}")
dbx("UPDATE lists SET state='trash' WHERE id=?", (P2,))
check(row(P2)[:2] == ("archived", 1), f"state='trash' written by hand decides nothing (the trash is deleted_at) {row(P2)}")
dbx("UPDATE lists SET archived=false, state='archived' WHERE id=?", (P2,))
check(row(P2)[:2] == ("live", 0), f"both in one write, the marker as it was (a copy of a row): archived decides, never apart {row(P2)}")
dbx("UPDATE lists SET archived=false, state='archived' WHERE id=?", (P2,))
check(row(P2)[:2] == ("archived", 1), f"both in one write, the marker changed: the marker decides {row(P2)}")

ins = dbx("INSERT INTO lists (name, created_at, owner_id, state) VALUES ('Example Copy A', '2026-01-02T03:04:05+00:00', ?, 'archived') RETURNING id",
          (FID,))
I1 = ins[0][0] if ins else None
check(I1 and row(I1)[:2] == ("archived", 1), f"an INSERT naming state 'archived' gets archived=1 {I1 and row(I1)}")
ins = dbx("INSERT INTO lists (name, created_at, owner_id, archived) VALUES ('Example Copy B', '2026-01-02T03:04:05+00:00', ?, true) RETURNING id",
          (FID,))
I2 = ins[0][0] if ins else None
check(I2 and row(I2)[:2] == ("archived", 1), f"an INSERT naming archived=1 (an older row) gets 'archived' {I2 and row(I2)}")

# ---------------------------------------------------------------- the way back: the trigger of a version before, then this one again
OLD = """CREATE OR REPLACE FUNCTION kalmido_list_state() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  j JSONB := to_jsonb(NEW);
BEGIN
  IF NOT j ? 'state' THEN RETURN NEW; END IF;
  NEW.state := CASE WHEN COALESCE(j->>'deleted_at', '') <> '' THEN 'trash' WHEN COALESCE(j->>'archived', '0') NOT IN ('0', '') THEN 'archived' ELSE 'live' END;
  RETURN NEW;
END $$;"""
P3 = plist(Fr, "Example Old Workshop")
Fr.patch(B + f"/api/lists/{P3}", json={"archived": True})
# the suite's own session (the app's account may not create functions): the trigger function as a version before has it
dbxm.connect(os.path.join(kt.DATA, "tasks.db")).executescript(OLD + "\n")
check("NOT IN ('0', '') THEN 'archived' ELSE 'live' END;\n  RETURN NEW" in (dbx("SELECT prosrc FROM pg_proc WHERE proname='kalmido_list_state'") or [[""]])[0][0],
      "setup: the trigger of stage 1 back (a version before)")
check(row(P3)[:2] == ("archived", 1), f"a row this version archived reads archived for the version before {row(P3)}")
dbx("UPDATE lists SET archived=false, archived_at=NULL WHERE id=?", (P3,))
check(row(P3)[:3] == ("live", 0, None), f"the version before restores it its way: the marker follows {row(P3)}")
ns = {}
FRAG = os.path.join(N, "..", "kalmido", "core", "migrations.d", "5537_a.py")
with open(FRAG, encoding="utf-8") as f:
    exec(compile(f.read(), FRAG, "exec"), ns)  # nosec: a file of this repository, data only
dbxm.connect(os.path.join(kt.DATA, "tasks.db")).executescript(ns["SCHEMA"] + "\n")
check("NEW.state IS DISTINCT FROM OLD.state" in (dbx("SELECT prosrc FROM pg_proc WHERE proname='kalmido_list_state'") or [[""]])[0][0],
      "setup: the trigger of this version again (as its start writes it)")
r = Fr.patch(B + f"/api/lists/{P3}", json={"archived": True})
check(r.ok and row(P3)[:2] == ("archived", 1), f"forward again: the route archives through the marker {r.status_code} {row(P3)}")

# ---------------------------------------------------------------- the trash stays the core's
P4 = plist(Fr, "Example Archive Shelf")
Fr.patch(B + f"/api/lists/{P4}", json={"archived": True})
r = Fr.delete(B + f"/api/lists/{P4}")
check(r.ok and row(P4)[:2] == ("trash", 1), f"an archived project into the trash: trash {r.status_code} {row(P4)}")
out = in_app(f"""from kalmido.core.access import list_set_archived
print("SET", list_set_archived(c, {int(P4)}, False))
c.commit()""")
check("SET True" in out and row(P4)[:3] == ("trash", 0, None), f"out of the archive while in the trash: stays in the trash {row(P4)} {out[-200:]}")
r = Fr.post(B + f"/api/trash/lists/{P4}/restore")
check(r.ok and row(P4)[:2] == ("live", 0), f"restored from the trash: live (it was taken out of the archive) {r.status_code} {row(P4)}")
check("SET False" in in_app("from kalmido.core.access import list_set_archived\nprint('SET', list_set_archived(c, 987654321, True))"),
      "list_set_archived of a project that does not exist: False")

# ---------------------------------------------------------------- the organisation admin's archive and the quick notes
r = A.post(B + "/api/orgs", json={"name": "Example Board Studio"})
OID = r.json().get("id") if r.ok else None
check(OID is not None, f"setup: an organisation of alice {r.status_code} {r.text[:120]}")
P5 = plist(A, "Example Studio Board", OID)
r = A.post(B + "/api/users", json={"orgs": [{"id": OID, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
check(r.ok, f"setup: bob in the organisation {r.text[:120]}")
check(A.put(B + f"/api/lists/{P5}/members", json={"user_id": r.json().get("id"), "role": "edit"}).ok,
      "setup: shared with bob (the admins act on shared projects)")
r = A.post(B + f"/api/orgs/{OID}/lists/{P5}/archive", json={"archived": True})
st, ar, at, _ = row(P5)
check(r.ok and st == "archived" and ar == 1 and at, f"the organisation admin archives: through the marker {r.status_code} {r.text[:120]} {row(P5)}")
seen = {x["id"]: x for x in A.get(B + f"/api/orgs/{OID}/lists").json().get("lists", [])}
check(P5 in seen and seen[P5].get("archived") is True and seen[P5].get("name") == "Example Studio Board",
      f"the admin's list of the organisation's projects shows it archived {seen.get(P5)}")
r = A.post(B + f"/api/orgs/{OID}/lists/{P5}/archive", json={"archived": False})
check(r.ok and row(P5)[:3] == ("live", 0, None), f"the organisation admin brings it back {r.status_code} {row(P5)}")

r = Fr.post(B + "/api/notes/quick-list")
QN = r.json().get("list_id") if r.ok else None
check(QN is not None, f"setup: the quick-notes project {r.status_code} {r.text[:120]}")
if QN:
    Fr.patch(B + f"/api/lists/{QN}", json={"archived": True})
    check(row(QN)[0] == "archived", f"setup: quick notes archived {row(QN)}")
    r = Fr.post(B + "/api/notes/quick-list")
    check(r.ok and r.json().get("list_id") == QN and row(QN)[:3] == ("live", 0, None),
          f"the quick notes come back from the archive through the marker {r.text[:120]} {row(QN)}")

# ---------------------------------------------------------------- the whole table
bad = dbx("""SELECT id, state, archived FROM lists WHERE (state='archived' AND NOT archived) OR (state='live' AND archived)
             OR state IS DISTINCT FROM (CASE WHEN deleted_at IS NOT NULL THEN 'trash' WHEN archived THEN 'archived' ELSE 'live' END)""")
n = dbx("SELECT COUNT(*) FROM lists")[0][0]
check(n >= 7 and not bad, f"every project: archived agrees with the marker ({n} rows) {bad[:3]}")

sys.exit(done("p21054_a_liststate2"))
