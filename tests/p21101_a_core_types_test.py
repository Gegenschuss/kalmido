#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1101.0 (#5954): the core's own tables obj_history, obj_undo and obj_revoked on real types (core/objretype.py obj_retype,
core/migrations.d/4709_a.py). Invented names only.
 - a new database makes them so at once: created_at / updated_at TIMESTAMPTZ, vals_before / vals_after / snap / row_json JSONB,
   and the back limit (kalmido_meta back_floor) names the step
 - the start-time move from a database of before (the columns as TEXT, an unreadable time, a text that is no JSON, a JSON
   array): the next start moves them, keeps every readable value (the instant, the JSON), an unreadable time becomes the start's
   time and a broken JSON '{}'; the back limit rises again; a further start changes nothing
 - after the move the core works on them as before: an object's history (one entry per person within ten minutes, the merge
   of core/writes.py obj_history_add read as a point in time), the undo of the editor session, a share taken back and put back
   (obj_revoked), and the rename of a knowledge folder twice within ten minutes (core/writes.py obj_history_add_many: the
   merge writes JSONB from a VALUES list -- typed text it failed with "column vals_before is of type jsonb")
 - a person without an organisation: her history and undo on the new types (no new route: freelancer-matrix n/a)
usage: p21101_a_core_types_test.py <datadir>"""
import json
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, docker_logs_on_first_fail, done, fresh, sess  # noqa: E402
from obj_probe import ENV, K, TABLE_SQL, new, start  # noqa: E402

COLS = {("obj_history", "created_at"): "timestamp with time zone", ("obj_history", "updated_at"): "timestamp with time zone",
        ("obj_history", "vals_before"): "jsonb", ("obj_history", "vals_after"): "jsonb",
        ("obj_undo", "created_at"): "timestamp with time zone", ("obj_undo", "snap"): "jsonb",
        ("obj_revoked", "created_at"): "timestamp with time zone", ("obj_revoked", "row_json"): "jsonb"}
SESS = "5954abcdef012345"
U = {"X-Kalmido-Undo": SESS}


def types():
    return {(r[0], r[1]): r[2] for r in dbx("SELECT table_name, column_name, data_type FROM information_schema.columns "
                                            "WHERE table_schema=current_schema() AND table_name IN ('obj_history', 'obj_undo', 'obj_revoked')")
            if (r[0], r[1]) in COLS}


def floor():
    return {r[0]: r[1] for r in dbx("SELECT key, value FROM kalmido_meta WHERE key IN ('back_floor', 'back_floor_how')")}


def restart():
    """The same database, a new start of the app (init_db runs again, obj_retype with it)."""
    fresh(env=ENV, prefix="P21101A", keep=True)
    dbx(TABLE_SQL)


def hist(s, oid):
    r = s.get(B + f"/api/obj/{K}/{oid}/history")
    return r.json()["items"] if r.ok else r.status_code


start("P21101A")
docker_logs_on_first_fail()
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
BOB = r.json()["id"]
Bo = sess("bob")
FID, Fr = freelancer(B, A)

# ================================================================== a new database
t = types()
check(t == COLS, f"new database: the times are TIMESTAMPTZ, the copies JSONB {t}")
fl = floor()
check("#5954" in fl.get("back_floor_how", ""), f"new database: the back limit names the step {fl}")

# ================================================================== a database of before
o = new(Bo, "Call sheet draft", ORG, note="first")
O = o["id"]
r = Bo.patch(B + f"/api/obj/{K}/{O}", json={"note": "second"}, headers=U)
check(r.ok, f"setup: a change with an undo step {r.status_code} {r.text[:200]}")
check(len([x for x in hist(Bo, O) if x["action"] == "update"]) == 1, "setup: one history entry of the change")
canon = "to_char({0} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"+00:00\"')"
for (tb, col), ty in COLS.items():
    if ty == "jsonb":
        dbx(f"ALTER TABLE {tb} ALTER COLUMN {col} DROP DEFAULT, ALTER COLUMN {col} TYPE TEXT USING {col}::text, ALTER COLUMN {col} SET DEFAULT '{{}}'")
    else:
        dbx(f"ALTER TABLE {tb} ALTER COLUMN {col} TYPE TEXT USING {canon.format(col)}")
dbx("DELETE FROM kalmido_meta WHERE key IN ('back_floor', 'back_floor_how')")
check(set(types().values()) == {"text"}, f"setup: the columns as before 2.1101 {types()}")
OLD = "2026-10-01T08:00:00+00:00"
HB = dbx("INSERT INTO obj_history(kind, ref_id, org_id, user_id, action, vals_before, vals_after, created_at, updated_at) "
         "VALUES(?, ?, ?, ?, 'update', ?, 'not json', ?, 'last tuesday') RETURNING id",
         (K, O, ORG, BOB, json.dumps({"note": "Müller's note"}), OLD))[0][0]
UB = dbx("INSERT INTO obj_undo(org_id, user_id, sess, kind, ref_id, seq, state, snap, created_at) "
         "VALUES(?, ?, 'feedfeedfeedfeed', ?, ?, 1, 'done', '{broken', '2026-02-30T10:00:00+00:00') RETURNING id", (ORG, BOB, K, O))[0][0]
RA = dbx("INSERT INTO obj_revoked(src, org_id, user_id, kind, ref_id, row_json, reason, created_at) "
         "VALUES('fs_shares', ?, ?, ?, ?, '[1, 2]', 'unshare', '') RETURNING id", (ORG, BOB, K, O))[0][0]
restart()
A, Bo = sess("alice"), sess("bob")
t = types()
check(t == COLS, f"move: the times are TIMESTAMPTZ, the copies JSONB {t}")
h = dbx("SELECT vals_before, vals_after, created_at, updated_at FROM obj_history WHERE id=?", (HB,))[0]
check(json.loads(h[0]) == {"note": "Müller's note"} and json.loads(h[1]) == {}, f"move: the JSON kept, a text that is no JSON is {{}} {h[:2]}")
check(str(h[2]).replace(" ", "T").startswith("2026-10-01T08:00:00") and str(h[3])[:2] == "20" and str(h[3]) > "2026-11",
      f"move: a readable time kept, an unreadable one is the start's time {h[2:]}")
u = dbx("SELECT snap, created_at FROM obj_undo WHERE id=?", (UB,))[0]
check(json.loads(u[0]) == {} and str(u[1]) > "2026-11", f"move: a broken copy is {{}}, 30 February the start's time {u}")
rv = dbx("SELECT row_json, created_at FROM obj_revoked WHERE id=?", (RA,))[0]
check(json.loads(rv[0]) == [1, 2] and str(rv[1]) > "2026-11", f"move: a JSON array kept as it is, an empty time the start's {rv}")
fl = floor()
check("#5954" in fl.get("back_floor_how", "") and fl.get("back_floor", "").count(".") == 2,
      f"move: the back limit rises (an older version would write text into them) {fl}")
n0 = dbx("SELECT COUNT(*) FROM obj_history")[0][0]
restart()
A, Bo = sess("alice"), sess("bob")
check(types() == COLS and dbx("SELECT COUNT(*) FROM obj_history")[0][0] == n0, "move: a further start changes nothing")

# ================================================================== the core on the new types
dbx("DELETE FROM obj_history WHERE id=?", (HB,))
o2 = new(Bo, "Location list", ORG)
O2 = o2["id"]
check(Bo.patch(B + f"/api/obj/{K}/{O2}", json={"title": "Location list A"}, headers=U).ok
      and Bo.patch(B + f"/api/obj/{K}/{O2}", json={"title": "Location list B", "size": 3}, headers=U).ok, "core: two changes")
hs = [x for x in hist(Bo, O2) if x["action"] == "update"]
check(len(hs) == 1 and hs[0]["before"].get("title") == "Location list" and hs[0]["after"] == {"title": "Location list B", "size": 3}
      and hs[0]["name"] == "Bob", f"core: one person's changes within ten minutes are one entry (the time read as a time) {hs}")
r = Bo.post(B + f"/api/obj/{K}/{O2}/undo", json={"sess": SESS, "op": "undo"})
check(r.ok and r.json()["title"] == "Location list A" and r.json()["size"] is None, f"core: the undo of the editor session {r.status_code} {r.text[:200]}")
r = Bo.post(B + f"/api/obj/{K}/{O2}/undo", json={"sess": SESS, "op": "redo"})
check(r.ok and r.json()["title"] == "Location list B", f"core: and the redo {r.status_code} {r.text[:200]}")
check(dbx("SELECT COUNT(*) FROM obj_undo WHERE kind=? AND ref_id=? AND jsonb_typeof(snap->'obj_probe')='array'", (K, O2))[0][0] >= 1,
      "core: the undo copy is a JSONB object (a JSONB operator reads it)")

# a share taken back and put back (obj_revoked)
o3 = new(A, "Shoot plan")
O3 = o3["id"]
r = A.post(B + f"/api/obj/{K}/{O3}/shares", json={"user_id": BOB, "role": "edit"})
check(r.status_code == 201, f"revoked: a share for Bob {r.status_code} {r.text[:200]}")
SB = r.json().get("id") if r.ok else 0
r = A.delete(B + f"/api/obj/{K}/{O3}/shares/{SB}")
RV = r.json().get("revoked_id") if r.ok else 0
check(r.ok and Bo.get(B + f"/api/obj/{K}/{O3}").status_code == 404, f"revoked: the share taken back {r.status_code} {r.text[:200]}")
rv = dbx("SELECT row_json, created_at FROM obj_revoked WHERE id=?", (RV,))
check(rv and json.loads(rv[0][0]).get("user_id") == BOB and str(rv[0][1]) > "2026-11", f"revoked: the row in obj_revoked, its copy JSON {rv}")
r = A.post(B + f"/api/obj/{K}/{O3}/shares/{RV}/restore")
check(r.ok and Bo.get(B + f"/api/obj/{K}/{O3}").json().get("role") == "edit", f"revoked: put back from there {r.status_code} {r.text[:200]}")

# a knowledge folder renamed twice within ten minutes (obj_history_add_many: the second rename merges through a VALUES list)
for p in ("Crew/Lights", "Crew/Sound"):
    r = A.post(B + "/api/wiki/pages", json={"space": "private", "path": p, "body": "Invented text"})
    check(r.ok, f"wiki: page {p} {r.status_code} {r.text[:200]}")
PIDS = [x[0] for x in dbx("SELECT id FROM wiki_pages WHERE path IN ('Crew/Lights', 'Crew/Sound') AND deleted_at IS NULL ORDER BY id")]
r = A.post(B + "/api/wiki/move", json={"space": "private", "from": "Crew", "to": "Team"})
check(r.ok, f"wiki: the folder renamed {r.status_code} {r.text[:200]}")
r = A.post(B + "/api/wiki/move", json={"space": "private", "from": "Team", "to": "People"})
check(r.ok, f"wiki: and renamed again within ten minutes (the merge, JSONB from a VALUES list) {r.status_code} {r.text[:200]}")
wh = {x[0]: (json.loads(x[1]), json.loads(x[2])) for x in dbx("SELECT ref_id, vals_before, vals_after FROM obj_history WHERE kind='wiki' "
                                                              "AND ref_id IN (?, ?)", tuple(PIDS))}
check(len(PIDS) == 2 and wh.get(PIDS[0]) == ({"path": "Crew/Lights"}, {"path": "People/Lights"})
      and wh.get(PIDS[1]) == ({"path": "Crew/Sound"}, {"path": "People/Sound"}), f"wiki: one entry per page, from the first name to the last {wh}")

# ================================================================== a person without an organisation (freelancer-matrix: n/a, no route)
of = new(Fr, "My own plan")
OF = of["id"]
check(Fr.patch(B + f"/api/obj/{K}/{OF}", json={"note": "one"}, headers=U).ok and Fr.patch(B + f"/api/obj/{K}/{OF}", json={"note": "two"}, headers=U).ok,
      "freelancer: two changes")
hf = [x for x in hist(Fr, OF) if x["action"] == "update"]
check(len(hf) == 1 and hf[0]["after"] == {"note": "two"}, f"freelancer: her history on the new types {hf}")
r = Fr.post(B + f"/api/obj/{K}/{OF}/undo", json={"sess": SESS, "op": "undo"})
check(r.ok and r.json()["note"] == "one", f"freelancer: her undo {r.status_code} {r.text[:200]}")
sys.exit(done())
