#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.747.0 A (#5246): the shared core, stage 7e -- the office and the file store. Own container (kt.fresh). Invented people,
firms and figures only.
freelancer-matrix: office
tenant-matrix: office
 - 1 office_undo is gone: the table is dropped, the account export's not_included names it nowhere, the organisation export's
   and the account export's lists in the code neither, tools/check_export_tables.py is green
 - 2 a share made and taken back in the file store's dialog (POST /api/files/nodes/<id>/shares, DELETE /api/files/shares/<id>)
   goes the core's way: the row carries by_role, taking it back puts it into obj_revoked (src fs_shares, reason unshare) with
   the log line; the same target again changes the one row
 - b the master data save (PATCH /api/office/<kind>/<id>) runs on ow_write: an old expect_updated_at -> 409 with the row under
   "current" (no "row"), nothing written; a save = ONE obj_history entry (kind office_md_<kind>); with the header
   X-Kalmido-Undo the dialog's undo POST /api/office/<kind>/<id>/undo brings the old value back; the same for a client
   (POST /api/clients/<id>/undo); another office / person: 404
 - 3 the last hard deletes of #4707 go into the office trash and come back: a quotation part with its positions (DELETE
   .../parts/<id> answers trash_id; restore brings part and positions back and names the quotation), an office rights group
   (its definition comes back, its members do not), an orphaned video sign-off record (the trash of its office)
 - 4 the calendars' trash run (2.925.0 #5367: obj_trash_prune, kind evcal; was events/evkern.py ev_cal_trash_purge): a calendar in the trash with members, events, a feed, history, an undo step and a
   revoked share is deleted for good with all of them and its node; purge False only counts; a calendar not in the trash stays
The same for a person without an organisation (freelancer_fixture: the personal office, her private files and calendar).
usage: p2747_a_buero_test.py <datadir>"""
import io
import json
import os
import subprocess
import sys
import zipfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
import requests  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, sess, su_get  # noqa: E402

FEAT = "cal,events,contacts,comments,collab,files,sheets,office,clients,docs"
OFF = "/api/office"
V = B + "/api/v1"
TOK = "a1b2c3d4e5f60718293a4b5c6d7e8f90"  # an undo session of the dialog (static/js/objsave.js objSess)
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


# ================================================================ 1 office_undo is gone
def export_gone():
    check(sql("SELECT to_regclass('office_undo') IS NULL") == [(True,)], "1: the table office_undo is dropped (migrations.d/5246.py)")
    root = os.path.join(N, "..")
    for f in ("kalmido/admin/orgexport.py", "kalmido/admin/exportleft.py", "kalmido/accounts/orgretain.py", "kalmido/accounts/useradmin.py",
              "kalmido/core/rls.py", "kalmido/core/schema.py"):
        src = open(os.path.join(root, f), encoding="utf-8").read()
        check('"office_undo"' not in src and "office_undo(" not in src and "TABLE IF NOT EXISTS office_undo" not in src,
              f"1: {f} names office_undo no more")
    r = subprocess.run([sys.executable, os.path.join(root, "tools", "check_export_tables.py")], capture_output=True, text=True)
    check(r.returncode == 0, "1: check_export_tables is green " + (r.stdout + r.stderr)[-400:])


def acct_export(s, who):
    check(s.post(B + "/api/account/export").status_code in (200, 202), f"1 {who}: the account export starts")
    j = kt.until(lambda: (lambda x: x if x.get("state") != "running" else None)(s.get(B + "/api/account/export").json()), 120)
    check((j or {}).get("state") == "done", f"1 {who}: the account export is done {j}")
    raw = su_get(s, B + "/api/account/export/file").content
    man = json.loads(zipfile.ZipFile(io.BytesIO(raw)).read("manifest.json"))
    left = man.get("not_included") or []
    check(left and not any("office_undo" in x for x in left), f"1 {who}: the manifest's not_included names office_undo nowhere {left[:3]}")
    check(any("obj_undo" in x for x in left), f"1 {who}: the core's undo steps stay named (the list is the real one)")


# ================================================================ 2 the share dialog through the core
def shares(who, s, space, agid, org):
    r = s.post(B + "/api/sheets/folders", json={"name": f"Shared {who}", "space": space})
    check(r.status_code == 201, f"2 {who}: setup: a folder {r.text[:200]}")
    nid = r.json()["folder"]["id"]
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json={"agent_id": agid, "role": "view"})
    check(r.status_code == 201, f"2 {who}: the folder shared with the agent {r.text[:200]}")
    shid = r.json()["id"]
    row = sql("SELECT role, by_role, created_by FROM fs_shares WHERE id=?", (shid,))
    check(row and row[0][0] == "view" and row[0][1], 
          f"2 {who}: the row is the core's (obj_node_share: by_role) {row}")
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json={"agent_id": agid, "role": "edit"})
    check(r.status_code == 201 and r.json()["id"] == shid and sql("SELECT COUNT(*) FROM fs_shares WHERE node_id=?", (nid,)) == [(1,)]
          and sql("SELECT role FROM fs_shares WHERE id=?", (shid,)) == [("edit",)], f"2 {who}: the same target again changes the one row {r.text[:160]}")
    check(s.delete(B + f"/api/files/shares/{shid}").ok, f"2 {who}: the share taken back in the dialog")
    check(not sql("SELECT 1 FROM fs_shares WHERE id=?", (shid,)), f"2 {who}: the share is gone")
    rv = [x for x in sql("SELECT reason, org_id, row_json FROM obj_revoked WHERE src='fs_shares'") if json.loads(x[2]).get("id") == shid]
    check(len(rv) == 1 and rv[0][0] == "unshare" and (rv[0][1] or None) == (org or None) and json.loads(rv[0][2]).get("agent_id") == agid,
          f"2 {who}: it is in obj_revoked (the core's way), not only deleted {rv}")
    check(sql("SELECT 1 FROM fs_log WHERE node_id=? AND action='unshare' AND detail=?", (nid, str(shid))), f"2 {who}: the log line")


# ================================================================ b the master data / a client on ow_write, the dialog's undo
def master(who, s, other):
    r = s.post(B + OFF + "/services", json={"name_de": f"Beratung {who}", "daily_rate": 800})
    check(r.status_code in (200, 201), f"b {who}: a service {r.text[:200]}")
    sv = r.json()
    url = B + OFF + f"/services/{sv['id']}"
    r = s.patch(url, json={"daily_rate": 900, "expect_updated_at": sv["updated_at"]}, headers={"X-Kalmido-Undo": TOK})
    check(r.ok and r.json()["daily_rate"] == 900, f"b {who}: saved with its base and the undo header {r.status_code} {r.text[:200]}")
    h = sql("SELECT action, vals_before, vals_after FROM obj_history WHERE kind='office_md_services' AND ref_id=?", (sv["id"],))
    check(len(h) == 1 and "daily_rate" in json.loads(h[0][2]), f"b {who}: ONE history entry of the core (office_md_services) {h}")
    r = s.patch(url, json={"daily_rate": 700, "expect_updated_at": sv["updated_at"]})
    check(r.status_code == 409 and r.json().get("current", {}).get("daily_rate") == 900 and "row" not in r.json(),
          f"b {who}: an old base -> 409 with the row under current {r.status_code} {r.text[:200]}")
    check(s.get(url).json()["daily_rate"] == 900, f"b {who}: the 409 wrote nothing")
    check(other.post(B + f"/api/office/services/{sv['id']}/undo", json={"sess": TOK, "op": "all"}).status_code == 404, f"b {who}: another office's undo: 404")
    r = s.post(B + f"/api/office/services/{sv['id']}/undo", json={"sess": TOK, "op": "all"})
    check(r.ok and s.get(url).json()["daily_rate"] == 800, f"b {who}: the dialog's undo (POST <save url>/undo) brings the old rate back {r.status_code} {r.text[:200]}")
    check(s.post(B + OFF + "/docs/999999/undo", json={"sess": TOK, "op": "all"}).status_code == 404, f"b {who}: no master data kind: 404")
    # a client
    r = s.post(B + "/api/clients", json={"name": f"Beispiel Studio {who}"})
    check(r.status_code == 201, f"b {who}: a client {r.text[:200]}")
    cl = r.json()
    r = s.patch(B + f"/api/clients/{cl['id']}", json={"name": f"Beispiel Media {who}", "expect_updated_at": cl["updated_at"]},
                headers={"X-Kalmido-Undo": TOK})
    check(r.ok and r.json()["name"] == f"Beispiel Media {who}", f"b {who}: the client saved with the undo header {r.text[:200]}")
    check(other.post(B + f"/api/clients/{cl['id']}/undo", json={"sess": TOK, "op": "all"}).status_code in (403, 404),
          f"b {who}: another person's undo of the client: refused")
    r = s.post(B + f"/api/clients/{cl['id']}/undo", json={"sess": TOK, "op": "all"})
    check(r.ok and r.json().get("name") == f"Beispiel Studio {who}", f"b {who}: the client's undo brings the old name back {r.status_code} {r.text[:200]}")


# ================================================================ 3 the last hard deletes into the office trash
def in_trash(s, tid, kind):
    return any(x["id"] == tid and x["kind"] == kind for x in s.get(B + OFF + "/trash").json().get("items") or [])


def part(who, s, other):
    did = s.post(B + OFF + "/docs", json={"project_title": f"Spring {who}"}).json()["id"]
    r = s.post(B + OFF + f"/docs/{did}/parts", json={"kind": "items", "title": f"Drehtage {who}"})
    check(r.status_code == 201 and r.json().get("part"), f"3 {who}: setup: a part {r.text[:200]}")
    pid = r.json()["part"]["id"]
    r = s.put(B + OFF + f"/docs/{did}/parts/{pid}/items", json={"items": [{"kind": "service", "title": "Kamera", "qty": 2, "unit": "day", "rate": 500}]})
    check(r.ok, f"3 {who}: setup: its position {r.text[:200]}")
    n_items = sql("SELECT COUNT(*) FROM office_doc_items WHERE doc_id=? AND (part_id=? OR ref_part_id=?)", (did, pid, pid))[0][0]
    check(n_items >= 2, f"3 {who}: setup: the position and the title page line {n_items}")
    r = s.delete(B + OFF + f"/docs/{did}/parts/{pid}")
    tid = r.json().get("trash_id") if r.ok else None
    check(r.ok and tid and not sql("SELECT 1 FROM office_doc_parts WHERE id=?", (pid,)), f"3 {who}: the part goes, a trash copy {r.text[:200]}")
    check(in_trash(s, tid, "part"), f"3 {who}: the office trash lists the part")
    check(other.post(B + OFF + f"/trash/{tid}/restore").status_code == 404, f"3 {who}: another office cannot restore it")
    r = s.post(B + OFF + f"/trash/{tid}/restore")
    check(r.ok and r.json().get("kind") == "part" and r.json().get("doc_id") == did, f"3 {who}: restored, the answer names the quotation {r.text[:200]}")
    d = s.get(B + OFF + f"/docs/{did}").json()
    check(any(p["id"] == pid for p in d.get("parts") or []), f"3 {who}: the part is back in the quotation")
    check(sql("SELECT COUNT(*) FROM office_doc_items WHERE doc_id=? AND (part_id=? OR ref_part_id=?)", (did, pid, pid))[0][0] == n_items,
          f"3 {who}: with its positions and title page line")
    check(s.post(B + OFF + f"/trash/{tid}/restore").status_code == 404, f"3 {who}: a second restore: 404")


def rgroup(who, s, member_id=None):
    r = s.post(B + OFF + "/rights/groups", json={"name": f"Schnitt {who}"})
    check(r.status_code == 201, f"3 {who}: setup: a rights group {r.text[:200]}")
    gid, levels = r.json()["id"], r.json()["levels"]
    if member_id:
        check(s.put(B + OFF + f"/rights/people/{member_id}", json={"groups": [f"g:{gid}"]}).ok, f"3 {who}: setup: a member in the group")
    r = s.delete(B + OFF + f"/rights/groups/{gid}")
    # 2.905.0 (#5414): the core's trash (kind orgroup, the row stays with deleted_at), restore through core/
    tid = (r.json().get("trash") or {}).get("id") if r.ok else None
    check(r.ok and tid == gid and sql("SELECT 1 FROM office_rgroups WHERE id=? AND deleted_at IS NOT NULL", (gid,))
          and not any(x["id"] == gid for x in s.get(B + OFF + "/rights").json().get("groups") or []), f"3 {who}: the group goes into the trash {r.text[:200]}")
    check(in_trash(s, tid, "rgroup"), f"3 {who}: the office trash lists the rights group")
    r = s.post(B + OFF + f"/trash/core/orgroup/{tid}/restore")
    check(r.ok, f"3 {who}: restored {r.text[:200]}")
    g = next((x for x in s.get(B + OFF + "/rights").json().get("groups") or [] if x["id"] == gid), None)
    check(g and g["name"] == f"Schnitt {who}" and g["levels"] == levels, f"3 {who}: the group's definition is back {g}")
    check(not sql("SELECT 1 FROM office_rgroup_members WHERE group_id=?", (gid,)), f"3 {who}: its members do not come back (no rights handed out)")


def signoff(who, s, uid, org):
    sql("INSERT INTO office_signoffs(org_id, kind, title, token_hash, token, state, created_by, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (org, "video", f"Rohschnitt {who}", f"p2747a-{who}", "", "open", uid, "2026-01-05T10:00:00Z"), write=True)
    sid = sql("SELECT id FROM office_signoffs WHERE token_hash=?", (f"p2747a-{who}",))[0][0]
    check(any(x["id"] == sid for x in s.get(B + "/api/videos/signoffs/orphaned").json().get("signoffs") or []), f"3 {who}: setup: an orphaned record")
    r = s.delete(B + f"/api/videos/signoffs/orphaned/{sid}")
    tid = r.json().get("trash_id") if r.ok else None
    check(r.ok and tid and not sql("SELECT 1 FROM office_signoffs WHERE id=?", (sid,)), f"3 {who}: the record goes, a trash copy {r.text[:200]}")
    check(in_trash(s, tid, "signoff"), f"3 {who}: the trash of its office lists it")
    r = s.post(B + OFF + f"/trash/{tid}/restore")
    check(r.ok and sql("SELECT title, org_id FROM office_signoffs WHERE id=?", (sid,)) == [(f"Rohschnitt {who}", org)], f"3 {who}: restored as it was {r.text[:200]}")


# ================================================================ 4 ev_cal_trash_purge
def cal_purge(who, s, agid):
    k = s.post(B + "/api/evcals", json={"name": f"Team {who}"}).json()["id"]
    keep = s.post(B + "/api/evcals", json={"name": f"Bleibt {who}"}).json()["id"]
    check(s.put(B + f"/api/evcals/{k}/members", json={"user_id": agid, "role": "edit"}).ok, f"4 {who}: setup: shared with the agent")
    j = s.get(B + "/api/evcals").json()
    cur = next(x for x in (j if isinstance(j, list) else j.get("items") or []) if x["id"] == k)
    check(s.patch(B + f"/api/evcals/{k}", json={"name": f"Team neu {who}", "expect_updated_at": cur.get("updated_at")}, headers={"X-Kalmido-Undo": TOK}).ok,
          f"4 {who}: setup: renamed (history + undo step)")
    e = s.post(B + "/api/events", json={"cal_id": k, "title": "Planung", "start": "2026-12-03T09:00", "end": "2026-12-03T10:00"})
    check(e.ok, f"4 {who}: setup: an event {e.text[:160]}")
    check(s.post(B + f"/api/evcals/{k}/feed", json={"action": "create"}).ok, f"4 {who}: setup: a feed")
    # a revoked share of the calendar (the members dialog's removal is not on the core yet, 7b: the row as the core writes it)
    sql("INSERT INTO obj_revoked(src, org_id, user_id, kind, ref_id, row_json, reason, by_id, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        ("fs_shares", None, agid, "evcal", k, "{}", "unshare", None, "2026-11-08T10:00:00Z"), write=True)
    node = sql("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='evcal' AND ref_id=?", (k,))
    have = {t: sql(f"SELECT COUNT(*) FROM {t} WHERE kind='evcal' AND ref_id=?", (k,))[0][0] for t in ("obj_history", "obj_undo", "obj_revoked")}
    check(node and all(have.values()), f"4 {who}: setup: a node, history, an undo step and a revoked share {node} {have}")
    check(s.delete(B + f"/api/evcals/{k}").ok, f"4 {who}: the calendar into the trash")
    # 2.925.0 (#5367): ev_cal_trash_purge is gone - the calendars' trash is the core's run (obj_trash_prune, kind evcal)
    code = "from kalmido.core.pg import system_ctx\nfrom kalmido.core.writes import obj_trash_prune\nwith system_ctx(c):\n" \
           "    print('n', obj_trash_prune(c, 'evcal', '9999', {0}))\nc.commit()"
    out = in_app(code.format("False"))
    check("n " in out and "Traceback" not in out and sql("SELECT 1 FROM ev_cals WHERE id=?", (k,)), f"4 {who}: purge off: only counted, still there {out[-300:]}")
    out = in_app(code.format("True"))
    check("n " in out and "Traceback" not in out, f"4 {who}: the purge ran {out[-300:]}")
    check(not sql("SELECT 1 FROM ev_cals WHERE id=?", (k,)), f"4 {who}: the calendar is gone for good")
    check(not sql("SELECT 1 FROM fs_nodes WHERE id=?", (node[0][0],)), f"4 {who}: its node too")
    for t in ("obj_history", "obj_undo", "obj_revoked"):
        check(sql(f"SELECT COUNT(*) FROM {t} WHERE kind='evcal' AND ref_id=?", (k,)) == [(0,)], f"4 {who}: its {t} rows too")
    for t, col in (("events", "cal_id"), ("ev_cal_feeds", "cal_id")):  # 2.924.0 (#5069): ev_cal_members is gone
        check(sql(f"SELECT COUNT(*) FROM {t} WHERE {col}=?", (k,)) == [(0,)], f"4 {who}: its {t} rows too (cascade)")
    check(sql("SELECT deleted_at FROM ev_cals WHERE id=?", (keep,)) == [(None,)], f"4 {who}: a calendar not in the trash stays")


# ================================================================ setup
kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2747A")
kt.docker_logs_on_first_fail()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/admin/agents", json={"username": "claude", "display_name": "Claude", "scopes": ["read", "calendar", "contacts"], "org_id": ORG})
assert r.ok, r.text
AAG = requests.get(V + "/me", headers={"X-Requested-With": "kalmido", "Authorization": "Bearer " + r.json()["token"]}).json().get("id")
FID, Fr = freelancer(B, A, "frida", features=FEAT)  # freelancer-matrix: office (the personal office, its own admin)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "calendar", "contacts"]})
assert r.status_code == 201, r.text
FAG = r.json()["id"]
for s in (A, Fr, Ca):
    s.put(B + OFF + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"})

export_gone()
acct_export(Fr, "frida")

shares("alice", A, f"org:{ORG}", AAG, ORG)
shares("frida", Fr, "private", FAG, None)

master("alice", A, Ca)
master("frida", Fr, Ca)

part("alice", A, Ca)
part("frida", Fr, Ca)
rgroup("alice", A, ids["bob"])
rgroup("frida", Fr)
signoff("alice", A, ALICE, ORG)
signoff("frida", Fr, FID, None)  # her personal office exists (the office settings above made it)

cal_purge("alice", A, AAG)
cal_purge("frida", Fr, FAG)

raise SystemExit(kt.done("p2747_a_buero"))
