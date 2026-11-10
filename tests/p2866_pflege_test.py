#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.866.0 (#5302): care after the review of 2.747 -- small findings of the office rights, the file store's shares, the
master data saves and the undo across devices. Own container (kt.fresh). Invented people, firms and figures only.
 - F5 a rights group restored from the office trash is in the rights log (group_restore, its definition as after)
 - F6 a projects folder's share with a list role: the file store's log line names the final role (edit for admin / edit)
 - F7 a share that ended with a move into another workspace and came back with the move back keeps by_role of who made it,
   and its obj_revoked row of the move goes (not offered a second time)
 - F8 a master data save that changes nothing ("800" for 800, blanks around a name, an unknown key) writes no history entry,
   no undo step, keeps updated_at
 - F9 a write while a "bis hierher" of the same person holds an undone group's parts does not wait for them (no deadlock
   window): it answers, the group stays; the next step tidies it
 - F10 a person who leaves an organisation loses her step groups there (with their parts), the others' stay
 - N2 a barrier holds "bis hierher" only for the steps of its own workspace (a private step behind an office barrier goes
   back, an office step behind it stays)
 - N5 office/oubar.py _plain: a browser ciphertext (e2e1:) or a sealed value never becomes a label; no label column of the
   office (documents, clients, master data) is in orgcrypt FIELDS
The same for a person without an organisation (freelancer_fixture: her personal office, her private project) at F5 / F8 / N2.
freelancer-matrix: office
usage: p2866_pflege_test.py <datadir>"""
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
import requests  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, sess  # noqa: E402

FEAT = "cal,events,contacts,comments,collab,files,sheets,office,clients,docs"
OFF = "/api/office"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


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


def in_app(code):
    cmd = ["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.close()"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    return out.stdout + out.stderr


def groups(u):
    return [dict(x) for x in sql("SELECT id, state, org_id, area, parts FROM undo_groups WHERE user_id=? ORDER BY id", (u,))]


def service(s, name, rate=800):
    r = s.post(B + OFF + "/services", json={"name_de": name, "daily_rate": rate})
    check(r.status_code in (200, 201), f"setup: a service {name} {r.text[:200]}")
    return r.json()


# ================================================================ F5 a rights group back from the trash: in the rights log
def f5(who, s):
    r = s.post(B + OFF + "/rights/groups", json={"name": f"Grading {who}"})
    check(r.status_code == 201, f"F5 {who}: setup: a rights group {r.text[:200]}")
    gid, levels = r.json()["id"], r.json()["levels"]
    r = s.delete(B + OFF + f"/rights/groups/{gid}")
    tid = r.json().get("trash_id") if r.ok else None
    check(r.ok and tid, f"F5 {who}: the group into the office trash {r.text[:200]}")
    check(s.post(B + OFF + f"/trash/{tid}/restore").ok, f"F5 {who}: restored")
    log = s.get(B + OFF + "/rights/log").json().get("items") or []
    mine = [x for x in log if x["group"] == f"g:{gid}"]
    check([x["action"] for x in mine][:2] == ["group_restore", "group_delete"],
          f"F5 {who}: the rights log names the restore after the delete (newest first) {[x['action'] for x in mine]}")
    rs = mine[0] if mine else {}
    check(rs.get("after", {}).get("name") == f"Grading {who}" and rs.get("after", {}).get("levels") == levels and rs.get("before") is None,
          f"F5 {who}: its definition as after {rs}")


# ================================================================ F6 a projects folder's share: the log names the final role
def f6():
    r = A.post(B + "/api/lists", json={"name": "Website", "folder": "Clients F6", "org_id": ORG})
    check(r.ok, f"F6: setup: a project in a folder {r.text[:200]}")
    tree = A.get(B + "/api/lists/tree").json().get("spaces") or []
    nid = next((f["id"] for sp in tree if sp.get("org_id") == ORG for f in sp.get("folders") or [] if f["path"] == "Clients F6" and f.get("mine")), None)
    check(nid, f"F6: setup: the projects folder's node {tree}")
    n0 = len(sql("SELECT 1 FROM fs_log WHERE node_id=? AND action='share'", (nid,)))
    r = A.post(B + f"/api/files/nodes/{nid}/shares", json={"user_id": ids["bob"], "role": "view", "list_role": "admin"})
    check(r.status_code == 201, f"F6: shared with the list role admin {r.text[:200]}")
    sid = r.json().get("id") if r.ok else None
    check(sql("SELECT role, list_role FROM fs_shares WHERE id=?", (sid,)) == [("edit", "admin")], "F6: the row: role edit, list role admin")
    lines = [x[0] for x in sql("SELECT detail FROM fs_log WHERE node_id=? AND action='share' ORDER BY id", (nid,))][n0:]
    check(lines == [f"user:{ids['bob']}:edit"], f"F6: ONE log line, with the final role (not the role of the body) {lines}")
    r = A.post(B + f"/api/files/nodes/{nid}/shares", json={"user_id": ids["bob"], "role": "edit", "list_role": "participant"})
    lines = [x[0] for x in sql("SELECT detail FROM fs_log WHERE node_id=? AND action='share' ORDER BY id", (nid,))]
    check(r.status_code == 201 and sql("SELECT role, list_role FROM fs_shares WHERE id=?", (sid,)) == [("view", "participant")]
          and lines[-1] == f"user:{ids['bob']}:view", f"F6: changed to participant: the row and the log line say view {lines}")
    r = A.post(B + f"/api/files/nodes/{nid}/shares", json={"user_id": ids["bob"], "role": "view", "list_role": "boss"})
    check(r.status_code == 400 and sql("SELECT role, list_role FROM fs_shares WHERE id=?", (sid,)) == [("view", "participant")],
          f"F6: an unknown list role: 400, nothing written {r.status_code}")


# ================================================================ F7 a share back with the move back: by_role kept, obj_revoked row gone
def moved_rows(shid):
    return [x[0] for x in sql("SELECT id, row_json FROM obj_revoked WHERE src='fs_shares' AND reason='move'") if json.loads(x[1]).get("id") == shid]


def f7():
    r = A.post(B + "/api/files/folders", json={"name": "Dailies F7", "space": f"org:{ORG}"})
    check(r.status_code == 201, f"F7: setup: a folder of the organisation {r.text[:200]}")
    nid = r.json()["id"]
    r = A.post(B + f"/api/files/nodes/{nid}/shares", json={"user_id": ids["bob"], "role": "view"})
    check(r.status_code == 201, f"F7: setup: shared with bob {r.text[:200]}")
    shid = r.json()["id"]
    sql("UPDATE fs_shares SET by_role='member' WHERE id=?", (shid,), write=True)  # made by a member (alice moves it: admin)
    r = A.post(B + "/api/files/move-space", json={"ids": [nid], "to": "private", "parent": None})
    check(r.ok and not sql("SELECT 1 FROM fs_shares WHERE node_id=?", (nid,)), f"F7: moved into the private space: the share ends {r.text[:200]}")
    check(len(moved_rows(shid)) == 1, "F7: it is in obj_revoked (reason move)")
    r = A.post(B + "/api/files/move-space", json={"ids": [nid], "to": f"org:{ORG}", "parent": None})
    check(r.ok and r.json().get("restored", 0) >= 1, f"F7: moved back: the memo brings the share back {r.text[:200]}")
    back = sql("SELECT user_id, role, by_role FROM fs_shares WHERE node_id=?", (nid,))
    check(back == [(ids["bob"], "view", "member")], f"F7: the share is back with by_role of who made it, not of who moved it {back}")
    check(moved_rows(shid) == [], f"F7: its obj_revoked row of the move is gone (no second way back) {moved_rows(shid)}")


# ================================================================ F8 a master data save of nothing: no history, no step
def f8(who, s, uid):
    sv = service(s, f"Beratung {who}")
    url = B + OFF + f"/services/{sv['id']}"
    hist = lambda: [json.loads(x[0]) for x in sql("SELECT vals_after FROM obj_history WHERE kind='office_md_services' AND ref_id=? ORDER BY id", (sv["id"],))]  # noqa: E731
    h0, g0 = hist(), len(groups(uid))
    r = s.patch(url, json={"daily_rate": "800", "name_de": f"  Beratung {who} ", "unit": sv["unit"], "no_such_column": 1,
                           "expect_updated_at": sv["updated_at"]})
    check(r.ok and r.json()["updated_at"] == sv["updated_at"], f"F8 {who}: the same values as text / with blanks: saved, the version stays {r.status_code} {r.text[:200]}")
    check(hist() == h0, f"F8 {who}: no history entry of nothing {hist()}")
    check(len(groups(uid)) == g0, f"F8 {who}: no undo step of nothing {groups(uid)[g0:]}")
    r = s.patch(url, json={"daily_rate": "850", "name_de": f"Beratung {who}", "no_such_column": 2, "expect_updated_at": sv["updated_at"]})
    h = hist()
    check(r.ok and r.json()["daily_rate"] == 850 and len(h) == len(h0) + 1 and list(h[-1]) == ["daily_rate"],
          f"F8 {who}: a real change: ONE entry with only the field that changed {h[len(h0):]}")
    check(len(groups(uid)) == g0 + 1, f"F8 {who}: and one undo step")


# ================================================================ F9 a write does not wait for the parts a "bis hierher" holds
HOLD = """import sys
import app
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
c = connect()
with system_ctx(c):
    n = len(c.execute("SELECT id FROM obj_undo WHERE group_id=? ORDER BY id FOR UPDATE", ({0},)).fetchall())
print("LOCKED", n, flush=True)
sys.stdin.readline()
c.rollback()
c.close()
print("FREE", flush=True)"""


def f9():
    s1, s2 = service(A, "Schnitt F9", 500), service(A, "Ton F9", 300)
    r = A.patch(B + OFF + f"/services/{s1['id']}", json={"daily_rate": 550, "expect_updated_at": s1["updated_at"]})
    check(r.ok, f"F9: setup: a step {r.text[:200]}")
    gid = groups(ALICE)[-1]["id"]
    r = A.post(B + f"/api/undo/to/{gid}")
    check(r.ok and gid in r.json().get("undone", []), f"F9: setup: taken back (its way forward is open) {r.text[:200]}")
    # a second device's "bis hierher" of the same person holds the parts of that group (as _run_group does while it waits
    # for the objects): a write must not wait for them (the circle of the deadlock)
    p = subprocess.Popen(["docker", "exec", "-i", CT, "python", "-u", "-c", HOLD.format(int(gid))], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        line = p.stdout.readline()
        check(line.startswith("LOCKED") and int(line.split()[1]) >= 1, f"F9: setup: the parts are held {line}")
        try:
            r = A.patch(B + OFF + f"/services/{s2['id']}", json={"daily_rate": 320, "expect_updated_at": s2["updated_at"]}, timeout=20)
            ok = r.ok
        except requests.exceptions.Timeout:
            ok, r = False, None
        check(ok, f"F9: a new step answers while the parts are held (no waiting for them) {r.status_code if r is not None else 'timeout'}")
        check(any(x["id"] == gid and x["state"] == "undone" for x in groups(ALICE)), "F9: the held group stays as it is")
    finally:
        p.stdin.write("go\n")
        p.stdin.flush()
        p.wait(timeout=60)
    s2 = A.get(B + OFF + f"/services/{s2['id']}").json()
    r = A.patch(B + OFF + f"/services/{s2['id']}", json={"daily_rate": 330, "expect_updated_at": s2["updated_at"]})
    check(r.ok and not any(x["id"] == gid for x in groups(ALICE)), f"F9: the next step tidies it: its way forward ends {r.status_code}")


# ================================================================ F10 leaving the organisation: the step groups there go
def task_step(s, name):
    """A step of s in a private project (org_id NULL): a task made and renamed -> (task id, group id of the rename)."""
    r = s.post(B + "/api/lists", json={"name": name, "org_id": None})
    check(r.ok, f"setup: a private project {name} {r.text[:200]}")
    lid = r.json()["id"]
    r = s.post(B + "/api/tasks", json={"list_id": lid, "title": f"{name} draft"})
    check(r.ok, f"setup: a task {r.text[:200]}")
    tid = r.json()["id"]
    r = s.patch(B + f"/api/tasks/{tid}", json={"title": f"{name} final"})
    check(r.ok, f"setup: renamed {r.text[:200]}")
    gid = sql("SELECT group_id FROM obj_undo WHERE kind='task' AND ref_id=? AND group_id IS NOT NULL ORDER BY id DESC LIMIT 1", (tid,))
    return tid, gid[0][0] if gid else None


def f10():
    sv = service(Do, "Dora F10", 400)
    r = Do.patch(B + OFF + f"/services/{sv['id']}", json={"daily_rate": 410, "expect_updated_at": sv["updated_at"]})
    check(r.ok, f"F10: setup: dora's office step {r.text[:200]}")
    _, gp = task_step(Do, "Dora private")
    gd = groups(ids["dora"])
    check(any(x["org_id"] == ORG for x in gd) and any(x["id"] == gp and x["org_id"] is None for x in gd),
          f"F10: setup: dora has groups in the organisation and a private one {gd}")
    ga = [x["id"] for x in groups(ALICE) if x["org_id"] == ORG]
    check(ga, "F10: setup: alice has groups in the organisation")
    r = A.delete(B + f"/api/orgs/{ORG}/members/{ids['dora']}")
    check(r.ok, f"F10: dora leaves (removed by alice) {r.status_code} {r.text[:200]}")
    gd2 = groups(ids["dora"])
    check(not any(x["org_id"] == ORG for x in gd2), f"F10: her groups in the organisation are gone {gd2}")
    check(not sql("SELECT 1 FROM obj_undo WHERE user_id=? AND org_id=?", (ids["dora"], ORG)), "F10: with their parts")
    check([x["id"] for x in gd2] == [gp], f"F10: her private group stays {gd2}")
    check([x["id"] for x in groups(ALICE) if x["org_id"] == ORG] == ga, "F10: alice's groups in the organisation stay")


# ================================================================ N2 a barrier holds only the steps of its own workspace
def barrier(uid, org):
    out = in_app(f"""from flask import g
from kalmido.core.config import app as fa
from kalmido.core.undogroups import undo_barrier
with fa.test_request_context('/api/office/docs/1/finalise', method='POST'):
    g.user = {{"id": {int(uid)}}}
    print('BARRIER', undo_barrier(c, {int(uid)}, 'office', 'Finalised: {{0}}', ('2026-001',), org_id={int(org)}))
    c.commit()""")
    gid = groups(uid)[-1]
    check("BARRIER" in out and gid["state"] == "barrier" and gid["org_id"] == org, f"N2: setup: a barrier in office {org} {out[-300:]}")
    return gid["id"]


def n2(who, s, uid, org):
    tid, gp = task_step(s, f"Moodboard {who}")
    check(gp and next((x for x in groups(uid) if x["id"] == gp), {}).get("org_id") is None, f"N2 {who}: setup: a private step {gp}")
    sv = service(s, f"Licht {who}", 200)
    r = s.patch(B + OFF + f"/services/{sv['id']}", json={"daily_rate": 210, "expect_updated_at": sv["updated_at"]})
    check(r.ok, f"N2 {who}: setup: an office step before the barrier")
    gb = groups(uid)[-1]["id"]
    bid = barrier(uid, org)
    sv = s.get(B + OFF + f"/services/{sv['id']}").json()
    r = s.patch(B + OFF + f"/services/{sv['id']}", json={"name_de": f"Licht {who} 2", "expect_updated_at": sv["updated_at"]})
    check(r.ok, f"N2 {who}: setup: an office step after the barrier")
    gc = groups(uid)[-1]["id"]
    r = s.post(B + f"/api/undo/to/{gp}")
    x = r.json() if r.ok else {}
    check(r.ok and {gc, gp} <= set(x.get("undone", [])) and gb not in x.get("undone", []) and (x.get("stopped") or {}).get("id") == bid,
          f"N2 {who}: 'bis hierher' over an office barrier: the newer office step and the private step go back, the barrier is named {r.status_code} {x}")
    st = {g["id"]: g["state"] for g in groups(uid)}
    check(st.get(gb) == "done" and s.get(B + OFF + f"/services/{sv['id']}").json().get("daily_rate") == 210,
          f"N2 {who}: the office step behind the barrier (same office) stays {st.get(gb)}")
    t = sql("SELECT title FROM tasks WHERE id=?", (tid,))
    check(t == [(f"Moodboard {who} draft",)], f"N2 {who}: the private task has its old title again {t}")


# ================================================================ N5 no sealed value becomes a label; label columns not in FIELDS
def n5():
    out = in_app("""from kalmido.office.oubar import _plain, oub_label_md, oub_label_client, oub_doc_name
from kalmido.core.orgcrypt import FIELDS, PREFIX
from kalmido.office.model import MD
print('PLAIN', repr([_plain('e2e1:QUJD'), _plain('  e2e1:x '), _plain(PREFIX + 'abc'), _plain('kenc2:abc'), _plain('Beratung'), _plain(None)]))
print('LABEL', repr([oub_label_md('name')({'id': 7, 'name': 'e2e1:QUJD'}), oub_label_client({'id': 8, 'name': PREFIX + 'x'})]))
bad = [(k, MD[k]['table'], MD[k]['label']) for k in MD if MD[k]['label'] in FIELDS.get(MD[k]['table'], ())]
bad += [(t, col) for t, col in (('office_docs', 'number'), ('clients', 'name')) if col in FIELDS.get(t, ())]
print('BAD', repr(bad), len(MD))""")
    check("PLAIN ['', '', '', '', 'Beratung', '']" in out, f"N5: _plain: a browser ciphertext (e2e1:), a sealed value: no text {out[-400:]}")
    check("LABEL [('Changed: {0}', ['#7']), ('Changed: {0}', ['#8'])]" in out, f"N5: the label falls back to the object number {out[-400:]}")
    check("BAD []" in out, f"N5: no label column (documents, clients, master data) is sealed at rest (orgcrypt FIELDS) {out[-400:]}")


# ================================================================ setup
kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2866")
kt.docker_logs_on_first_fail()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dora", "Dora Leaving")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Do = sess("bob"), sess("carol"), sess("dora")
for s in (A, Bo, Ca, Do):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "dora@example.com", "role": "admin"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2), (Do, ORG)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Fr = freelancer(B, A, "frida", features=FEAT)  # freelancer-matrix: office (the personal office, its own admin)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
for s in (A, Fr, Ca):
    s.put(B + OFF + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"})
FOFF = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))
FOFF = FOFF[0][0] if FOFF else None
check(FOFF, "setup: frida's personal office")

f5("alice", A)
f5("frida", Fr)
f6()
f7()
f8("alice", A, ALICE)
f8("frida", Fr, FID)
f9()
f10()
n2("alice", A, ALICE, ORG)
n2("frida", Fr, FID, FOFF)
n5()
# -- more parts below --

raise SystemExit(kt.done("p2866_pflege"))
