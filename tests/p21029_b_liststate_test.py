#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1029.0 (#5537, stage 1): a project carries ONE state marker lists.state ('live' | 'archived' | 'trash'), kept equal to
archived / deleted_at by the trigger kalmido_list_state (migrations.d/5537_a.py); reads ask through core/access.py
list_state_sql() / otr_live(). Invented names only.
 - a new project is 'live'; archived -> 'archived'; back -> 'live'; archived and into the trash -> 'trash'; restored from
   the trash -> 'archived' again (it was archived); every way through the app's routes, nothing writes the marker itself
 - a write that names state with a wrong value (a copy of all columns, a hand-made statement) is corrected by the trigger;
   a write of other columns leaves it as it is
 - the whole table: no row whose marker differs from its columns (the start's one-off fill and the trigger)
 - taking the archive step back (Recent steps, POST /api/undo/to/<id>) brings the project back to 'live'
 - the helper: list_state_sql("l") = l.state='live', several states as IN (...), otr_live = live or archived, an unknown
   state / alias is refused
 - a read moved onto the marker (lists/folders.py folder_lists, the picker of a folder's projects): live projects only, not an
   archived one, not one in the trash (before: one in the trash was offered when it was not archived)
 - the project list of the app still shows an archived project with archived true and leaves out the one in the trash
freelancer-matrix: tasks (a person without an organisation: her projects carry the marker through archive, trash and restore)
usage: p21029_b_liststate_test.py <datadir>"""
import ast
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

fresh(prefix="P21029B")

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
FID, Fr = freelancer(B, A)

LAP = {"X-Kalmido-Device": "Laptop (Test)"}


def plist(s, name):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": None})
    check(r.ok, f"setup: project {name} {r.text[:120]}")
    return r.json().get("id")


def state(lid):
    r = dbx("SELECT state, archived, deleted_at FROM lists WHERE id=?", (lid,))
    return r[0][0] if r else None


# ---------------------------------------------------------------- the marker follows the routes (a person without an organisation)
P1 = plist(Fr, "Example Garden Plan")
check(state(P1) == "live", f"a new project is live: {state(P1)}")
r = Fr.patch(B + f"/api/lists/{P1}", json={"archived": True}, headers=LAP)
check(r.ok and state(P1) == "archived", f"archived through the route -> archived: {r.status_code} {state(P1)}")
r = Fr.patch(B + f"/api/lists/{P1}", json={"archived": False}, headers=LAP)
check(r.ok and state(P1) == "live", f"taken out of the archive -> live: {r.status_code} {state(P1)}")

P2 = plist(Fr, "Example Old Workshop")
Fr.patch(B + f"/api/lists/{P2}", json={"archived": True})
r = Fr.delete(B + f"/api/lists/{P2}")
check(r.ok and state(P2) == "trash", f"an archived project into the trash -> trash (the trash comes first): {r.status_code} {state(P2)}")
seen = [x["id"] for x in Fr.get(B + "/api/trash/lists").json().get("lists", [])]
check(P2 in seen, f"the trash view lists it {seen}")

# the app's project list: the archived one with archived true, the one in the trash not at all
P3 = plist(Fr, "Example Archive Shelf")
Fr.patch(B + f"/api/lists/{P3}", json={"archived": True})
st = Fr.get(B + "/api/state").json()
ls = {x["id"]: x for x in st.get("lists", [])}
check(P3 in ls and ls[P3].get("archived") in (1, True) and ls[P3].get("state") == "archived",
      f"the project list shows the archived project as archived {ls.get(P3, {}).get('archived')} {ls.get(P3, {}).get('state')}")
check(P2 not in ls, "the project in the trash is not in the project list")
check(P1 in ls and ls[P1].get("name") == "Example Garden Plan" and ls[P1].get("state") == "live", "the live project is there with its name")

r = Fr.post(B + f"/api/trash/lists/{P2}/restore")
check(r.ok and state(P2) == "archived", f"restored from the trash -> archived again (it was archived): {r.status_code} {state(P2)}")

# ---------------------------------------------------------------- the trigger corrects a wrong value, other writes leave it
dbx("UPDATE lists SET state='trash' WHERE id=?", (P1,))
check(state(P1) == "live", f"a write naming state with a wrong value is corrected: {state(P1)}")
dbx("UPDATE lists SET name='Example Garden Plan 2' WHERE id=?", (P3,))
check(state(P3) == "archived", f"a write of another column leaves the marker: {state(P3)}")
dbx("UPDATE lists SET deleted_at=archived_at WHERE id=?", (P3,))
check(state(P3) == "trash", f"deleted_at set by hand -> trash: {state(P3)}")
dbx("UPDATE lists SET deleted_at=NULL WHERE id=?", (P3,))
check(state(P3) == "archived", f"deleted_at emptied by hand -> archived: {state(P3)}")

# ---------------------------------------------------------------- the whole table agrees with its columns
bad = dbx("""SELECT id, state, archived, deleted_at FROM lists WHERE state IS DISTINCT FROM
             (CASE WHEN deleted_at IS NOT NULL THEN 'trash' WHEN archived <> 0 THEN 'archived' ELSE 'live' END)""")
n = dbx("SELECT COUNT(*) FROM lists")[0][0]
check(n >= 4 and not bad, f"every project's marker agrees with archived / deleted_at ({n} rows) {bad[:3]}")
check(bool(dbx("SELECT 1 FROM settings WHERE key='migr_liststate5537' AND value='1'")), "the start's one-off fill is recorded")

# ---------------------------------------------------------------- the archive step taken back (Recent steps)
P4 = plist(Fr, "Example Kitchen Shelves")
r = Fr.patch(B + f"/api/lists/{P4}", json={"archived": True}, headers=LAP)
check(r.ok and state(P4) == "archived", f"setup: archived {state(P4)}")
items = Fr.get(B + "/api/undo").json().get("items", [])
gid = items[0]["id"] if items else None
check(gid is not None, f"the archive step is in Recent steps {items[:1]}")
if gid is not None:
    r = Fr.post(B + f"/api/undo/to/{gid}")
    check(r.ok and state(P4) == "live", f"the step taken back: live again {r.status_code} {r.text[:160]} {state(P4)}")

# ---------------------------------------------------------------- the helper and a read moved onto it
out = in_app(f"""from kalmido.core.access import list_state_sql, otr_live
print("H1", list_state_sql("l"))
print("H2", list_state_sql("", "trash", "archived"))
print("H3", otr_live("l"))
for bad in (("l", "gone"), ("l;x", "live")):
    try:
        list_state_sql(*bad)
        print("HBAD accepted", bad)
    except ValueError:
        print("HBAD refused")""")
check("H1 l.state='live'" in out, f"list_state_sql('l') = l.state='live' {out[-400:]}")
check("H2 state IN ('archived', 'trash')" in out, f"several states: IN, in a fixed order {out[-400:]}")
check("H3 l.state IN ('live', 'archived')" in out, f"otr_live = live or archived {out[-400:]}")
check(out.count("HBAD refused") == 2 and "HBAD accepted" not in out, f"an unknown state / alias is refused {out[-400:]}")
# P2 again in the trash, now not archived: the case the old filter archived=0 let through (an older version's row, a hand-made
# statement; the app archives a project before it goes into the trash)
dbx("UPDATE lists SET archived=0, deleted_at=created_at WHERE id=?", (P2,))
check(state(P2) == "trash", f"setup: P2 in the trash, not archived {state(P2)}")
dbx(f"UPDATE lists SET folder='Example Folder' WHERE id IN ({int(P1)}, {int(P2)}, {int(P3)}, {int(P4)})")
out = in_app(f"""from kalmido.lists.folders import folder_lists
print("FL", sorted(r["id"] for r in folder_lists(c, {FID}, "Example Folder")))""")
fl = next((x[3:] for x in out.splitlines() if x.startswith("FL ")), "None")
try:
    fl = ast.literal_eval(fl)
except (ValueError, SyntaxError):
    fl = None
check(fl == sorted([P1, P4]), f"the folder's projects: only the live ones {fl} (live {P1}, {P4}; archived {P3}; in the trash {P2}) {out[-300:]}")

sys.exit(done("p21029_b_liststate"))
