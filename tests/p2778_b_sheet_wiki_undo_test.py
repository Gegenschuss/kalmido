#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.778.0 (#5253): undo across devices, stage 5 -- tables and knowledge pages as pointer steps (kalmido/sheets/shundo.py,
kalmido/wiki/wkundo.py). Invented names only.
 - a person's cell write is ONE step of "Recent steps" (area sheets, kind sheet, mode ref: a pointer to the table's batch, no
   copy); taken back = the former inputs, redo = the new ones again; a cell someone else changed since stays and is named
   (A1), the rest goes back (the group partial); a row added is a step too (back = in the trash, redo = out again)
 - the person's batch is no agent call: the table's panel of agent calls does not list it, its batch-undo route answers 404
 - a save of a knowledge page points to its versions: taken back = the version before as a NEW version, redo = the saved
   text again; saves within the merge time share the step; someone else's save since = 409 naming them, their text stays
 - another account neither sees nor takes the step (404); a table moved to the trash since: the step stays (no access)
tenant-matrix: undo (another account's table / page step: not listed, 404)
freelancer-matrix: undo (a person without an organisation: her table and page steps taken back)
usage: p2778_b_sheet_wiki_undo_test.py <datadir>"""
import json
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402

fresh(prefix="P2778B")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}
for u in ("bob",):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
Bo, Ol = sess("bob"), sess("olga")
for s in (A, Bo, Ol):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
BOB = uid["bob"]
FID, Fr = freelancer(B, A)


def groups(u):
    return [dict(zip(("id", "state", "parts", "area", "label_key", "label_args"), r)) for r in
            dbx("SELECT id, state, parts, area, label_key, label_args FROM undo_groups WHERE user_id=? ORDER BY id", (u,))]


def parts(gid):
    return [(k, rid, mode, json.loads(snap or "{}")) for k, rid, mode, snap in
            dbx("SELECT kind, ref_id, mode, snap FROM obj_undo WHERE group_id=? ORDER BY id", (gid,))]


def state(gid):
    r = dbx("SELECT state FROM undo_groups WHERE id=?", (gid,))
    return r[0][0] if r else None


# ---------------------------------------------------------------- tables
def new_sheet(s, title, space):
    r = s.post(B + "/api/sheets", json={"title": title, "space": space})
    assert r.status_code in (200, 201), r.text[:300]
    sid = r.json()["id"]
    j = s.get(B + f"/api/sheets/{sid}").json()
    return sid, [c["id"] for c in j["columns"]], [x["id"] for x in j["rows"]]


def cell(rid, cid):
    r = dbx("SELECT raw FROM sheet_cells WHERE row_id=? AND col_id=?", (rid, cid))
    return r[0][0] if r else ""


def put(s, sid, *cells):
    r = s.put(B + f"/api/sheets/{sid}/cells", json={"cells": [{"row_id": a, "col_id": b, "raw": v} for a, b, v in cells]})
    assert r.ok, r.text[:300]
    return r.json()


SID, COLS, ROWS = new_sheet(Bo, "Plan sheet", SP)
R1, C1, C2 = ROWS[0], COLS[0], COLS[1]
n0 = len(groups(BOB))
put(Bo, SID, (R1, C1, "first"))
put(Bo, SID, (R1, C1, "second"), (R1, C2, "x"))
gs = groups(BOB)
check(len(gs) == n0 + 2, f"two cell writes = two steps {gs[n0:]}")
G1 = gs[-1]["id"]
pp = parts(G1)
check(len(pp) == 1 and pp[0][0] == "sheet" and pp[0][1] == SID and pp[0][2] == "ref" and set(pp[0][3]) == {"b", "rev"}
      and pp[0][3]["b"].startswith("p"), f"one pointer part: the table's batch and rev, no copy {pp}")
BATCH = pp[0][3]["b"]
it = Bo.get(B + "/api/undo").json()["items"]
check(it and it[0]["id"] == G1 and it[0]["area"] == "sheets" and it[0]["label"] == "Changed: Plan sheet" and it[0]["undo"] is True
      and it[0]["kind"] == "sheet" and it[0]["ref_id"] == SID, f"listed in Recent steps: area, label, the table {it[:1]}")

# ---- the person's batch is not an agent call
j = Bo.get(B + f"/api/sheets/{SID}").json()
check(not any(x["batch"] == BATCH for x in j.get("batches") or []), f"the agents' panel does not list the person's batch {j.get('batches')}")
check(dbx("SELECT COUNT(*) FROM sheet_cells WHERE sheet_id=? AND agent_batch IS NOT NULL", (SID,))[0][0] == 0,
      "the person's cells carry no agent mark")
check(Bo.post(B + f"/api/sheets/{SID}/batches/{BATCH}/undo").status_code == 404, "the agents' batch-undo route: 404 for a person's batch")
check(cell(R1, C1) == "second", "nothing went back through it")

# ---- another account
check(not any(x["id"] == G1 for x in Ol.get(B + "/api/undo").json()["items"]), "another account does not see the step")
check(Ol.post(B + f"/api/undo/to/{G1}").status_code == 404 and cell(R1, C1) == "second", "another account: 404, nothing went back")
check(not any(x["id"] == G1 for x in A.get(B + "/api/undo").json()["items"]), "the organisation's admin does not see it either")

# ---- back and forward
r = Bo.post(B + f"/api/undo/to/{G1}")
check(r.ok and G1 in r.json().get("undone", []) and not r.json().get("stayed"), f"undo of the cell step {r.status_code} {r.text[:300]}")
check(cell(R1, C1) == "first" and cell(R1, C2) == "", f"the former inputs are back {cell(R1, C1)!r} {cell(R1, C2)!r}")
check(state(G1) == "undone", "the group is undone")
check(len(groups(BOB)) == n0 + 2, "the undo itself records no step")
r = Bo.post(B + f"/api/undo/{G1}/redo")
check(r.ok and cell(R1, C1) == "second" and cell(R1, C2) == "x" and state(G1) == "done", f"redo: the new inputs again {r.text[:300]}")

# ---- a conflict: one cell changed by someone else since stays (named), the rest goes back
put(Bo, SID, (R1, C1, "third"), (R1, C2, "y"))
G2 = groups(BOB)[-1]["id"]
put(A, SID, (R1, C1, "alice's"))
r = Bo.post(B + f"/api/undo/to/{G2}")
st = r.json().get("stayed", []) if r.ok else []
check(r.ok and G2 in r.json().get("partial", []) and len(st) == 1 and st[0]["code"] == "conflict" and "A1" in st[0]["reason"]
      and "B1" not in st[0]["reason"], f"the cell changed elsewhere is named (A1), the group partial {r.status_code} {r.text[:300]}")
check(cell(R1, C1) == "alice's" and cell(R1, C2) == "x", f"A1 keeps the other person's input, B1 went back {cell(R1, C1)!r} {cell(R1, C2)!r}")

# ---- a row added: back = in the trash, redo = out again
r = Bo.post(B + f"/api/sheets/{SID}/rows", json={"count": 1})
check(r.ok and r.json().get("ids"), f"a row added {r.text[:200]}")
NR = r.json()["ids"][0]
G3 = groups(BOB)[-1]["id"]
check(parts(G3)[0][0] == "sheet", "the row added is a step of the table")
check(Bo.post(B + f"/api/undo/to/{G3}").ok and dbx("SELECT deleted_at FROM sheet_rows WHERE id=?", (NR,))[0][0], "undo: the new row in the trash")
check(Bo.post(B + f"/api/undo/{G3}/redo").ok and not dbx("SELECT deleted_at FROM sheet_rows WHERE id=?", (NR,))[0][0], "redo: the row back")
# ---------------------------------------------------------------- knowledge pages
def page(s, space, path, text):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, r.text[:300]
    return r.json()["id"]


def body(s, pid):
    return s.get(B + f"/api/wiki/pages/{pid}").json().get("body")


def nvers(pid):
    return dbx("SELECT COUNT(*) FROM obj_versions WHERE kind='wiki' AND ref_id=?", (pid,))[0][0]  # 2.958.0 (#5281): obj_versions


def save(s, pid, text):
    r = s.patch(B + f"/api/wiki/pages/{pid}", json={"body": text})
    assert r.ok, r.text[:300]


PID = page(A, SP, "Notes", "Text of Alice")
nb = len(groups(BOB))
save(Bo, PID, "Text of Bob")
gs = groups(BOB)
check(len(gs) == nb + 1, f"Bob's save is one step {gs[nb:]}")
GW = gs[-1]["id"]
pp = parts(GW)
check(len(pp) == 1 and pp[0][:3] == ("wiki", PID, "ref") and set(pp[0][3]) == {"b", "a"}, f"a pointer to the page's versions {pp}")
it = Bo.get(B + "/api/undo").json()["items"]
check(it[0]["id"] == GW and it[0]["area"] == "wiki" and it[0]["label"] == "Changed: Notes", f"listed: area wiki, the page's name {it[:1]}")
save(Bo, PID, "Text of Bob, more")
check(len(groups(BOB)) == nb + 1, "a second save within the merge time shares the step (one version)")
check(not any(x["id"] == GW for x in Ol.get(B + "/api/undo").json()["items"]) and Ol.post(B + f"/api/undo/to/{GW}").status_code == 404,
      "another account: not listed, 404")
nv = nvers(PID)
r = Bo.post(B + f"/api/undo/to/{GW}")
check(r.ok and GW in r.json().get("undone", []) and body(Bo, PID) == "Text of Alice", f"undo: the version before is the text {r.text[:300]}")
check(nvers(PID) == nv + 1, "taken back as a NEW version (the history keeps Bob's text)")
r = Bo.post(B + f"/api/undo/{GW}/redo")
check(r.ok and body(Bo, PID) == "Text of Bob, more" and state(GW) == "done", f"redo: Bob's text again {r.text[:300]}")
save(A, PID, "Alice wrote on")
r = Bo.post(B + f"/api/undo/to/{GW}")
st = r.json().get("stayed", []) if r.ok else []
check(r.ok and st and st[0]["code"] == "conflict" and "Alice" in st[0]["reason"] and body(Bo, PID) == "Alice wrote on",
      f"someone else saved since: named, their text stays {r.status_code} {r.text[:300]}")

# ---------------------------------------------------------------- a person without an organisation
FS, FC, FR = new_sheet(Fr, "Frida's sheet", "private")
put(Fr, FS, (FR[0], FC[0], "one"))
put(Fr, FS, (FR[0], FC[0], "two"))
GF = groups(FID)[-1]["id"]
check(Fr.post(B + f"/api/undo/to/{GF}").ok and cell(FR[0], FC[0]) == "one", "freelancer: her table step taken back")
check(Ol.post(B + f"/api/undo/to/{GF}").status_code == 404, "someone else: 404 on her step")
FP = page(Fr, "private", "Diary", "Day one")
dbx("UPDATE obj_versions SET created_at='2026-01-02T03:04:05.000Z', updated_at='2026-01-02T03:04:05.000Z' WHERE kind='wiki' AND ref_id=?", (FP,))  # 2.958.0 (#5281)
dbx("UPDATE wiki_pages SET updated_at='2026-01-02T03:04:05.000Z' WHERE id=?", (FP,))
save(Fr, FP, "Day two")
GP = groups(FID)[-1]["id"]
check(parts(GP)[0][:2] == ("wiki", FP), f"freelancer: her page save is a step {parts(GP)}")
check(Fr.post(B + f"/api/undo/to/{GP}").ok and body(Fr, FP) == "Day one", f"freelancer: her page back {body(Fr, FP)!r}")

# ---------------------------------------------------------------- the rights of now: a table in the trash
put(Bo, SID, (R1, C2, "z"))
G4 = groups(BOB)[-1]["id"]
check(A.delete(B + f"/api/sheets/{SID}").ok, "the admin moves the table to the trash")
r = Bo.post(B + f"/api/undo/to/{G4}")
st = r.json().get("stayed", []) if r.ok else []
check(r.ok and st and st[0]["code"] == "noaccess" and cell(R1, C2) == "z", f"a table in the trash: the step stays (no access) {r.text[:300]}")

# ---------------------------------------------------------------- review r2778 F1 + F2 (own table, at the end: no step order above changes)
S2, _, _ = new_sheet(Bo, "Review sheet", SP)
r = Bo.post(B + f"/api/sheets/{S2}/rows", json={"count": 1})
NR2 = r.json()["ids"][0]
G5 = groups(BOB)[-1]["id"]
check(Bo.post(B + f"/api/undo/to/{G5}").ok and dbx("SELECT deleted_at FROM sheet_rows WHERE id=?", (NR2,))[0][0], "F1: undo puts the row in the trash")
dbx("UPDATE sheet_rows SET deleted_at='2026-12-01T00:00:00.000Z' WHERE id=?", (NR2,))  # someone else deleted it later
r = Bo.post(B + f"/api/undo/{G5}/redo")
st = r.json().get("stayed", []) if r.ok else []
check(not r.json().get("redone") and st and st[0]["code"] == "conflict"
      and dbx("SELECT deleted_at FROM sheet_rows WHERE id=?", (NR2,))[0][0] == "2026-12-01T00:00:00.000Z",
      f"F1: redo leaves a row deleted since in the trash {r.status_code} {r.text[:200]}")
# F2: an agent's batch whose agent was removed since (agent_id NULL, accounts/orgretain.py) stays in the agents' panel and
# their batch-undo route; a person's batch ('p...') is neither listed nor taken there
dbx("INSERT INTO sheet_changes (sheet_id, batch, agent_id, cell_id, row_id, col_id, kind, old_raw, new_raw, created_at) "
    "VALUES (?, 'a00ff00ff00ff00ff', NULL, NULL, NULL, NULL, 'fmt', NULL, NULL, '2026-11-09T10:00:00.000Z')", (S2,))
bl = [x["batch"] for x in Bo.get(B + f"/api/sheets/{S2}").json().get("batches", [])]
check("a00ff00ff00ff00ff" in bl and not any(b.startswith("p") for b in bl), f"F2: agents' panel lists the removed agent's batch, no person's {bl}")
pb = dbx("SELECT batch FROM sheet_changes WHERE sheet_id=? AND substr(batch, 1, 1) = 'p' LIMIT 1", (S2,))[0][0]
check(Bo.post(B + f"/api/sheets/{S2}/batches/{pb}/undo").status_code == 404, "F2: a person's batch is 404 on the agents' undo route")

sys.exit(done("p2778_b_sheet_wiki_undo"))
