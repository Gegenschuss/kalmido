#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.578.0 part A (#4796): an account's deletion takes the shared core's history of its PRIVATE objects along. Own container.
Invented names only (example.com).  freelancer-matrix: pim
 - a person without an organisation: her private calendar (settings changed -> obj_history, an undo row of somebody else on
   it) goes with the account and so do its obj_history / obj_undo / obj_revoked rows
 - her private calendar shared with bob (edit) is handed on to him (#4301): it stays, its history stays, her name in it is gone
   (user_id NULL)
 - her own project deleted along (?lists=delete): its core history rows go with it (lists/lists.py list_purge)
usage: p2578_a_konto_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, check  # noqa: E402

FEAT = "cal,events,contacts,comments,collab,files"
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2578A")


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def rows(kind, rid):
    """{table: number of rows} of the core's history tables for the object."""
    return {t: sql(f"SELECT COUNT(*) FROM {t} WHERE kind=? AND ref_id=?", (kind, rid))[0][0] for t in ("obj_history", "obj_undo", "obj_revoked")}


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
FRIDA, Fr = freelancer(B, A, "frida")
BOB, Bo = freelancer(B, A, "bob")
TS = "2026-11-06T08:00:00+00:00"

# ---------------------------------------------------------------- her private calendar and the one she shares with bob
P = Fr.post(B + "/api/evcals", json={"name": "Private plan"}).json()["id"]
S = Fr.post(B + "/api/evcals", json={"name": "Shared plan"}).json()["id"]
check(sql("SELECT org_id, owner_id FROM ev_cals WHERE id IN (?,?) ORDER BY id", (P, S)) == [(None, FRIDA), (None, FRIDA)],
      "two private calendars of frida")
check(Fr.put(B + f"/api/evcals/{S}/members", json={"user_id": BOB, "role": "edit"}).ok, "the second one shared with bob (edit)")
for k, name in ((P, "Private plan 2026"), (S, "Shared plan 2026")):
    kc = {x["id"]: x for x in Fr.get(B + "/api/evcals").json()["items"]}[k]
    r = Fr.patch(B + f"/api/evcals/{k}", json={"name": name, "expect_updated_at": kc["updated_at"]}, headers={"X-Kalmido-Undo": "t1"})
    check(r.ok, f"frida renames calendar {k} {r.text[:160]}")
check(rows("evcal", P)["obj_history"] >= 1 and rows("evcal", S)["obj_history"] >= 1, f"both have core history {rows('evcal', P)} {rows('evcal', S)}")
# an undo row and a revoked share of somebody else on the private calendar (as when it was shared once)
sql("INSERT INTO obj_undo(org_id, user_id, sess, kind, ref_id, created_at) VALUES(NULL,?,?,?,?,?)", (BOB, "b1", "evcal", P, TS), write=True)
sql("INSERT INTO obj_revoked(src, org_id, user_id, kind, ref_id, row_json, reason, created_at) VALUES('fs_shares',NULL,?,?,?,'{}','unshare',?)",
    (BOB, "evcal", P, TS), write=True)
check(rows("evcal", P)["obj_undo"] >= 1 and rows("evcal", P)["obj_revoked"] == 1, f"the private calendar has undo / revoked rows {rows('evcal', P)}")

# ---------------------------------------------------------------- her own project with a history row of the core
r = Fr.post(B + "/api/lists", json={"name": "Garden"})
check(r.status_code in (200, 201), "frida's project " + r.text[:160])
L = r.json()["id"]
sql("INSERT INTO obj_history(kind, ref_id, org_id, user_id, action, vals_before, vals_after, created_at, updated_at) "
    "VALUES('list',?,NULL,?,'update','{}','{\"props\": 1}',?,?)", (L, FRIDA, TS, TS), write=True)

# ---------------------------------------------------------------- the account goes (the instance admin's delete, projects along)
r = A.delete(B + f"/api/users/{FRIDA}", params={"lists": "delete", "confirm": "frida"})
check(r.ok and not sql("SELECT 1 FROM users WHERE id=?", (FRIDA,)), "frida's account deleted " + r.text[:200])
check(not sql("SELECT 1 FROM ev_cals WHERE id=?", (P,)), "her private calendar went with the account")
check(rows("evcal", P) == {"obj_history": 0, "obj_undo": 0, "obj_revoked": 0},
      f"#4796: its history, undo and revoked rows went with it {rows('evcal', P)}")
check(sql("SELECT owner_id FROM ev_cals WHERE id=?", (S,)) == [(BOB,)], "the shared calendar was handed on to bob (#4301)")
check(rows("evcal", S)["obj_history"] >= 1, f"#4796: the shared object keeps its history {rows('evcal', S)}")
check(not sql("SELECT 1 FROM obj_history WHERE kind='evcal' AND ref_id=? AND user_id=?", (S, FRIDA))
      and sql("SELECT COUNT(*) FROM obj_history WHERE kind='evcal' AND ref_id=? AND user_id IS NULL", (S,))[0][0] >= 1,
      "#4796: her rows in it keep no name (user_id NULL)")
check(S in {x["id"] for x in Bo.get(B + "/api/evcals").json()["items"]}, "bob still sees the shared calendar")
check(not sql("SELECT 1 FROM lists WHERE id=?", (L,)) and rows("list", L)["obj_history"] == 0,
      f"#4796: her project deleted along takes its core history {rows('list', L)}")
check(not sql("SELECT 1 FROM obj_history WHERE user_id=?", (FRIDA,)), "no history row names her any more")

sys.exit(kt.done("p2578_a_konto"))
