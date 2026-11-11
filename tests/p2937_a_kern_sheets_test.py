#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.937.0 part A (#5244, stage 7c of the shared core): tables are shared only by the core shares of their node; sheet_shares
keeps the addresses typed in, its old rows of people and its column core_id go at the start (one way). Own container (mode
workspaces). Invented names only.
tenant-matrix: sheet_share
freelancer-matrix: sheets
 - the two dialogs show one row: a share made in the table's dialog is the row of the file store's dialog (its id), ended in
   the table's dialog it is gone in the other; a group the person is in opens the table and marks it shared with them
 - an address typed in: the account of that address signs in with it proved -> its core share on the table's node (the
   dialog still reads "invited", a negative id); ending the address ends the core share
 - the undo of a move between workspaces: the guest reads the table again (a real read, not a column)
 - a person without an organisation shares her private table by name with another one: core share, read, both dialogs
 - the start check: an older database (core_id, TEXT times) with a row of a person whose table's node is full keeps
   everything (log line), a row the last forward copy can serve gets its core share at once
 - the drop at the next start: rows of people gone, core_id gone, an address bound to a share that is gone deleted, an
   address ended by a move kept, created_at / revoked_at TIMESTAMPTZ, back_floor = this minor (the minor before refuses to
   start), the table read through the forward copy; a later start does nothing
usage: p2937_a_kern_sheets_test.py <datadir>"""
import json
import subprocess
import sys

import requests

import kt
from freelancer_fixture import freelancer
from kt import B, check, dbx, sess, until

FEAT = "sheets,files,collab,comments"
CT = kt.CT
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_API_RATE": "100000"}, prefix="P2937A")
kt.docker_logs_on_first_fail()


def core(sid, who):
    """Roles of who's core shares on table sid's node."""
    return [x[0] for x in dbx("SELECT s.role FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind='sheet' "
                              "AND n.ref_id=? AND (s.user_id=? OR s.agent_id=?)", (sid, who, who))]


def node(sid):
    x = dbx("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='sheet' AND ref_id=?", (sid,))
    return x[0][0] if x else None


def table(s, title, space):
    r = s.post(B + "/api/sheets", json={"title": title, "space": space})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def dlg(s, sid):
    return s.get(B + f"/api/sheets/{sid}/shares").json().get("shares", [])


def fsdlg(s, nid):
    return s.get(B + f"/api/files/nodes/{nid}").json().get("shares", [])


def reads(s, sid):
    return s.get(B + f"/api/sheets/{sid}").status_code == 200


def cols():
    return {r[0]: r[1] for r in dbx("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema() "
                                    "AND table_name='sheet_shares'")}


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def _health():
    try:
        return requests.get(B + "/api/health", timeout=3).ok
    except requests.RequestException:
        return False


def restart():
    """The next start (core/db.py init_db runs sheets/shshare.py shs_retire)."""
    subprocess.run(["docker", "restart", CT], capture_output=True)
    check(until(_health, timeout=90), "the server is up again after the restart")


def in_app(code, *args):
    r = subprocess.run(["docker", "exec", "-i", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", code, *map(str, args)],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (r.stdout + r.stderr)[-600:]}


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/me").json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Kappa", "admin_id": ALICE})
assert r.status_code in (200, 201), r.text
K = r.json()["id"]
uid, S = {}, {}
for u, role in (("bob", "member"), ("gina", "guest")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
    check(A.put(B + f"/api/orgs/{K}/members", json={"email": f"{u}@example.com", "role": role}).ok, f"setup: {u} in Kappa ({role})")
    S[u] = sess(u)
    S[u].patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
BOB, GINA, Gi = uid["bob"], uid["gina"], S["gina"]
A.patch(B + "/api/settings", json={"workspace": f"org:{K}"})
SP = f"org:{K}"

# ================================================================ one row in both dialogs
T1 = table(A, "Rates", SP)
r = A.post(B + f"/api/sheets/{T1}/shares", json={"user_id": GINA, "role": "read"})
check(r.status_code == 201 and reads(Gi, T1), f"alice shares the table with the guest, she reads it {r.status_code}")
SH = r.json().get("id")
N1 = node(T1)
check([x["id"] for x in fsdlg(A, N1)] == [SH] and [x["id"] for x in dlg(A, T1)] == [SH],
      f"the table's dialog and the file store's dialog show the same row {fsdlg(A, N1)} {dlg(A, T1)}")
check(not dbx("SELECT 1 FROM sheet_shares WHERE sheet_id=?", (T1,)), "no old row of the person")
check(A.patch(B + f"/api/files/shares/{SH}", json={"role": "edit"}).ok and dlg(A, T1)[0]["role"] == "write", "a role set in the file store shows in the table's dialog")
check(A.delete(B + f"/api/sheets/{T1}/shares/{SH}").ok and fsdlg(A, N1) == [] and not reads(Gi, T1),
      "ended in the table's dialog: gone in the file store's dialog, the guest reads nothing")
check(dbx("SELECT reason FROM obj_revoked WHERE src='fs_shares' AND kind='sheet' AND ref_id=?", (T1,)) == [("unshare",)], "... restorable in obj_revoked")
# a group the guest is in (file store's dialog on the table's node): opens it, marked as shared with her
r = A.post(B + "/api/admin/groups", json={"name": "Readers", "members": [GINA]})
G = r.json().get("id") if r.ok else None
if G:
    check(A.post(B + f"/api/files/nodes/{N1}/shares", json={"group_id": G, "role": "view"}).ok and reads(Gi, T1), "a group share on the table's node opens it")
    row = next((x for x in Gi.get(B + "/api/sheets?space=shared").json().get("sheets", []) if x["id"] == T1), {})
    check(row.get("shared_in") is True and row.get("share_role") == "read", f"#5244: the group share counts as a share (shared with me) {row}")
    check(dlg(A, T1) == [], "a group's share is no row of the table's dialog (the file store's dialog holds it)")
else:
    check(False, f"setup: a group of Kappa {r.status_code} {r.text[:160]}")

# ================================================================ an address typed in: redeemed against the core
T2 = table(A, "Later", SP)
check(A.post(B + f"/api/sheets/{T2}/shares", json={"email": "late@example.com", "role": "write"}).status_code == 201, "shared by address")
r = A.post(B + "/api/users", json={"orgs": [], "username": "late", "display_name": "Late Person", "password": "password123", "email": "late@example.com"})
assert r.ok, r.text
LATE = r.json()["id"]
check(A.put(B + f"/api/orgs/{K}/members", json={"email": "late@example.com", "role": "guest"}).ok, "setup: the account joins Kappa as a guest")
dbx("UPDATE users SET email_proved='late@example.com' WHERE id=?", (LATE,))
La = sess("late")
La.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
check(core(T2, LATE) == ["edit"] and reads(La, T2), f"the sign-in takes the address: a core share on the node with the invitation's role {core(T2, LATE)}")
check(dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=?", (T2,)) == [(LATE,)], "the address row is bound to the account (no core_id)")
d = dlg(A, T2)
check(len(d) == 1 and d[0]["state"] == "invited" and d[0]["id"] < 0 and d[0]["user_id"] is None and d[0]["role"] == "write",
      f"the dialog still reads the address, never the name {d}")
check(len(fsdlg(A, node(T2))) == 1, "the file store's dialog holds the core share")
check(A.delete(B + f"/api/sheets/{T2}/shares/{d[0]['id']}").ok and not core(T2, LATE) and not reads(La, T2)
      and not dbx("SELECT 1 FROM sheet_shares WHERE sheet_id=?", (T2,)), "ending the address ends its core share, the address goes")

# ================================================================ the undo of a move: a real read again
T3 = table(A, "Moved", SP)
check(A.post(B + f"/api/sheets/{T3}/shares", json={"user_id": GINA, "role": "read"}).status_code == 201 and reads(Gi, T3), "setup: shared with the guest")
r = A.post(B + f"/api/sheets/{T3}/move-space", json={"to": "private"})
MID = r.json().get("move_id") if r.ok else None
check(MID and not reads(Gi, T3) and not core(T3, GINA), f"moved to Private: the guest reads nothing {r.text[:160]}")
r = A.post(B + f"/api/sheets/{T3}/move-space", json={"to": SP, "undo": MID})
check(r.ok and r.json().get("shares_back") == 1, f"the undo names the share back {r.text[:160]}")
check(reads(Gi, T3) and core(T3, GINA) == ["view"], "#5244: the guest reads the table again (the core share is back, from obj_revoked)")
check(not dbx("SELECT 1 FROM obj_revoked WHERE src='fs_shares' AND kind='sheet' AND ref_id=?", (T3,)), "... taken out of obj_revoked")

# ================================================================ a person without an organisation (freelancer-matrix: sheets)
FID, Fr = freelancer(B, A, "frida", features=FEAT)
FIO, Fi = freelancer(B, A, "fiona", features=FEAT)
P1 = table(Fr, "Own rates", "private")
# two people without organisation see each other only by address (no shared list): bound to her account at once
r = Fr.post(B + f"/api/sheets/{P1}/shares", json={"email": "fiona@example.com", "role": "read"})
check(r.status_code == 201 and reads(Fi, P1) and core(P1, FIO) == ["view"], f"freelancer: the address is a core share, she reads {r.text[:160]}")
fs = fsdlg(Fr, node(P1))
check(len(fs) == 1 and fs[0]["user_id"] == FIO and dlg(Fr, P1)[0]["state"] == "invited", "freelancer: the file store's dialog holds the core share")
check(Fr.delete(B + f"/api/files/shares/{fs[0]['id'] if fs else 0}").ok and dlg(Fr, P1) == [] and not reads(Fi, P1),
      "freelancer: ended in the file store's dialog, gone in the table's dialog (the address too)")
check(Fi.get(B + f"/api/sheets/{T3}").status_code == 404, "tenant: a person of no organisation does not read the organisation's table")

# ================================================================ Fable F4: the same share twice at once is one row
# 2.937.0 (#5244, Fable F4): core/objects.py obj_node_share checks and writes under a lock of node + person
import threading  # noqa: E402
T11 = table(A, "Double click", SP)
check(A.post(B + f"/api/sheets/{T11}/shares", json={"user_id": BOB, "role": "read"}).status_code == 201 and node(T11),
      "F4 setup: T11 shared with bob, it has its node")
gate = threading.Barrier(8)


def _twice():
    s2 = requests.Session()
    s2.cookies.update(A.cookies)
    s2.headers.update(A.headers)
    gate.wait()
    s2.post(B + f"/api/sheets/{T11}/shares", json={"user_id": GINA, "role": "read"})


th = [threading.Thread(target=_twice) for _ in range(8)]
for t in th:
    t.start()
for t in th:
    t.join()
check(core(T11, GINA) == ["view"] and len(dlg(A, T11)) == 2, f"F4: eight shares with the guest at once -> one core share {core(T11, GINA)}")

# ================================================================ an older database: the start check
T4 = table(A, "Old copy", SP)
T5 = table(A, "Full node", SP)
T6 = table(A, "Dead address", SP)
check(A.post(B + f"/api/sheets/{T5}/shares", json={"user_id": BOB, "role": "read"}).status_code == 201, "setup: T5 has its node")
check(A.post(B + f"/api/sheets/{T6}/shares", json={"email": "gina@example.com", "role": "read"}).status_code == 201 and reads(Gi, T6),
      "setup: T6 shared with the guest's address (bound)")
T7 = table(A, "Moved address", SP)
check(A.post(B + f"/api/sheets/{T7}/shares", json={"email": "nobody@example.com", "role": "read"}).status_code == 201, "setup: T7 by address")
dbx("UPDATE sheet_shares SET revoked_at='2026-11-01T10:00:00.000+00:00' WHERE sheet_id=?", (T7,))  # ended by a move (its undo)
T10 = table(A, "Broken end", SP)
check(A.post(B + f"/api/sheets/{T10}/shares", json={"email": "nobody2@example.com", "role": "read"}).status_code == 201, "F8 setup: T10 by address")
# Fable F6: T9 shared with the guest's address (bound), then in the trash without its node (its shares went with the node)
T9 = table(A, "Trashed address", SP)
check(A.post(B + f"/api/sheets/{T9}/shares", json={"email": "gina@example.com", "role": "read"}).status_code == 201 and reads(Gi, T9),
      "F6 setup: T9 shared with the guest's address (bound)")
check(A.delete(B + f"/api/sheets/{T9}").ok, "F6 setup: T9 in the trash")
dbx("DELETE FROM fs_nodes WHERE kind='ref' AND ref_kind='sheet' AND ref_id=?", (T9,))
# the table as a version before 2.937 had it: core_id, TEXT times
dbx("ALTER TABLE sheet_shares ADD COLUMN IF NOT EXISTS core_id BIGINT")
dbx("ALTER TABLE sheet_shares ALTER COLUMN created_at TYPE TEXT USING to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"+00:00\"')")
dbx("ALTER TABLE sheet_shares ALTER COLUMN revoked_at TYPE TEXT USING to_char(revoked_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"+00:00\"')")
TS = "2026-11-05T10:00:00.000+00:00"
# Fable F8: times the cast cannot read -- a week date as T7's start, an ended address (T10) with a broken end time
dbx("UPDATE sheet_shares SET created_at='2026-W45-3' WHERE sheet_id=?", (T7,))
dbx("UPDATE sheet_shares SET revoked_at='yesterday-ish' WHERE sheet_id=?", (T10,))
# T6: the address names a core share that is gone (an older version's rest: it gave nothing, listed by nobody)
dbx("DELETE FROM fs_shares WHERE node_id=? AND user_id=?", (node(T6), GINA))
dbx("UPDATE sheet_shares SET core_id=987654321 WHERE sheet_id=?", (T6,))
for sid in (T4, T5):
    dbx("INSERT INTO sheet_shares(sheet_id,org_id,user_id,role,created_by,created_at,email_key) VALUES(?,?,?,'read',?,?,'')", (sid, K, GINA, ALICE, TS))
dbx("INSERT INTO sheet_shares(sheet_id,org_id,user_id,role,created_by,created_at,revoked_at,email_key) VALUES(?,?,?,'read',?,?,?,'')",
    (T1, K, BOB, ALICE, TS, TS))  # an ended row of a person
N5 = node(T5)
dbx("INSERT INTO fs_shares(node_id,user_id,role,created_by,created_at) SELECT ?, ?, 'view', ?, ? FROM generate_series(1, 200)", (N5, ALICE, ALICE, TS))
check(not reads(Gi, T4) and not reads(Gi, T5), "setup: an old row not moved yet gives nothing")
restart()
Gi, A = sess("gina"), sess("alice")
check("core_id" in cols(), "start check: a row left without a share -> core_id stays (nothing dropped)")
check("tables, stage 7c (#5244): 1 old row(s) of sheet_shares have no share in the shared core" in logs(), "start check: the log names the row left")
check(dbx("SELECT COUNT(*) FROM sheet_shares WHERE email_key=''")[0][0] == 3, "start check: the old rows stay")
check(core(T4, GINA) == ["view"] and reads(Gi, T4), "the last forward copy gave T4's row its core share at once")
check(not reads(Gi, T5), "T5's row found no room: it gives nothing")

# ================================================================ the drop at the next start (one way)
dbx("DELETE FROM fs_shares WHERE node_id=? AND user_id=?", (N5, ALICE))
restart()
Gi, A = sess("gina"), sess("alice")
c = cols()
check("core_id" not in c, f"drop: core_id is gone {sorted(c)}")
check(c.get("created_at") == "timestamp with time zone" and c.get("revoked_at") == "timestamp with time zone", f"drop: the times are TIMESTAMPTZ {c}")
check("tables, stage 7c (#5244): every old row of sheet_shares has its share in the shared core" in logs(), "drop: the log says so")
check(dbx("SELECT COUNT(*) FROM sheet_shares WHERE email_key=''")[0][0] == 0, "drop: no row of a person left")
check(core(T5, GINA) == ["view"] and reads(Gi, T5), "drop: T5's row got its core share first, the guest reads it")
check(not dbx("SELECT 1 FROM sheet_shares WHERE sheet_id=?", (T6,)) and not reads(Gi, T6), "drop: a bound address without its core share is gone (reopens nothing)")
check(dbx("SELECT revoked_at IS NOT NULL FROM sheet_shares WHERE sheet_id=?", (T7,)) == [(True,)], "drop: an address ended by a move stays (its undo)")
check(dbx("SELECT user_id IS NULL, revoked_at IS NULL FROM sheet_shares WHERE sheet_id=?", (T9,)) == [(True, True)],
      "F6: the bound address of a table in the trash without its node opens again (kept, no account bound, not ended)")
check(dbx("SELECT revoked_at IS NOT NULL FROM sheet_shares WHERE sheet_id=?", (T10,)) == [(True,)],
      "F8: an address ended with a time the cast cannot read stays ended (never opens again)")
check(dbx("SELECT created_at IS NOT NULL FROM sheet_shares WHERE sheet_id=?", (T7,)) == [(True,)], "F8: a week date as start time: the start's time")
check(A.post(B + f"/api/sheets/{T9}/restore").ok, "F6: T9 back from the trash")
dbx("UPDATE users SET email_proved='gina@example.com' WHERE id=?", (GINA,))
Gi = sess("gina")
check(reads(Gi, T9) and core(T9, GINA) == ["view"], "F6: the guest's next sign-in takes the address again: a core share, she reads T9")
fl = dict(dbx("SELECT key, value FROM kalmido_meta WHERE key IN ('back_floor','back_floor_how')"))
mine = in_app("import json; from kalmido.core.config import APP_VERSION; print(json.dumps(APP_VERSION))")
check(isinstance(mine, str) and fl.get("back_floor") == ".".join(mine.split(".")[:2] + ["0"]) and "#5244" in (fl.get("back_floor_how") or ""),
      f"drop: back_floor is the minor of this image {fl} {mine}")
v = in_app("import json, sys; from kalmido.core.db import appver_check; from kalmido.core.config import APP_VERSION as m; "
           "x = m.split('.'); prev = f'{x[0]}.{int(x[1]) - 1}.0'; "
           "print(json.dumps(appver_check(m, prev, mine=prev, floor=sys.argv[1])))", fl.get("back_floor"))
check(v == "format", f"drop: the previous minor now refuses to start on this database: {v}")
# the dialog after the drop: shares by name and by address work on the new types
check(A.post(B + f"/api/sheets/{T4}/shares", json={"email": "someone@example.com", "role": "read"}).status_code == 201, "after the drop: an address")
d = dlg(A, T4)
check(len(d) == 2 and {x["state"] for x in d} == {"active", "invited"} and all(x["created_at"] for x in d), f"after the drop: both rows listed {d}")
seen = logs().count("tables, stage 7c (#5244)")
restart()
check("core_id" not in cols() and logs().count("tables, stage 7c (#5244)") == seen, "a later start: nothing to do (no new log line)")

# ================================================================ Fable F1: a database from before core_id came (before 2.565)
# 2.937.0 (#5244, Fable F1): "done" is the target types, not the missing core_id -- the hook adds the column back and runs
T8 = table(A, "Before the core", SP)
dbx("ALTER TABLE sheet_shares ALTER COLUMN created_at TYPE TEXT USING to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"+00:00\"'), "
    "ALTER COLUMN revoked_at TYPE TEXT USING to_char(revoked_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"+00:00\"')")
dbx("INSERT INTO sheet_shares(sheet_id,org_id,user_id,role,created_by,created_at,email_key) VALUES(?,?,?,'read',?,?,'')", (T8, K, GINA, ALICE, TS))
check("core_id" not in cols() and cols().get("created_at") == "text" and not reads(Gi, T8),
      "F1 setup: sheet_shares as before 2.565 (no core_id, TEXT times), a person row that gives nothing yet")
restart()
Gi = sess("gina")
c = cols()
check("core_id" not in c and c.get("created_at") == "timestamp with time zone" and c.get("revoked_at") == "timestamp with time zone",
      f"F1: the start ran the whole stage on the old database (core_id added back and dropped again, real types) {c}")
check(core(T8, GINA) == ["view"] and reads(Gi, T8), "F1: the old row was copied forward first, the guest reads the table")
check(dbx("SELECT COUNT(*) FROM sheet_shares WHERE email_key=''")[0][0] == 0, "F1: no row of a person left")
check("sheet_shares: a database from before the shared core's columns core_id -- added back" in logs(), "F1: the log names the old database")

sys.exit(kt.done("p2937_a_kern_sheets"))
