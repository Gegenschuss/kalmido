#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.631.0 (#4584): the account's delete dialog says per shared folder that is handed on what of it does not go along (a
locked folder with what lies in it, a shortcut, the trash, the copy of a mail that goes with the account) and how many
public links and file requests of others on it end; an agent of another person with a share in it keeps it (only said).
The numbers are exactly what the deletion then does: the entries counted are the ones missing afterwards, the links and
requests counted are the ones ended. The mail copy is never handed on (it went right after anyway). People without an
organisation throughout (freelancer-matrix: files). Invented names only.
usage: p2631_c_purge_branches_test.py <datadir>"""
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from kt import B, check, dbx, sess, until  # noqa: E402

kt.fresh({"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": base64.b64encode(os.urandom(32)).decode()})
A = kt.setup()
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
FEAT = "files,docs,collab"
T0 = "2026-02-01T00:00:00Z"


def write(q, args=()):
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"))
    c.execute(q, args)
    c.commit()
    c.close()


def person(name):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com", "orgs": []})
    assert r.ok, r.text
    s = sess(name)
    assert s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"}).ok
    return r.json()["id"], s


def folder(s, name, parent=None):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": "private"})})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(s, name, data, parent):
    r = s.post(B + "/api/files/upload", data={"parent_id": str(parent)}, files={"file": (name, data)})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def owner(nid):
    r = dbx("SELECT owner_id FROM fs_nodes WHERE id=?", (nid,))
    return r[0][0] if r else None


def settled(nid):
    return until(lambda: not dbx("SELECT 1 FROM file_text WHERE kind='fs' AND node_id=? AND state IN ('wait', 'run')", (nid,))
                 and not dbx("SELECT 1 FROM doc_meta WHERE node_id=? AND state IN ('wait', 'run')", (nid,)), 120)


def subtree(nid):
    return {r[0]: r[1] for r in dbx("""WITH RECURSIVE t(id) AS (SELECT id FROM fs_nodes WHERE id=? UNION ALL
                                        SELECT n.id FROM fs_nodes n JOIN t ON n.parent_id=t.id)
                                        SELECT f.id, f.owner_id FROM fs_nodes f JOIN t ON t.id=f.id WHERE f.kind<>'ref'""", (nid,))}


VERA, Ve = person("vera")
WIM, Wi = person("wim")
XENA, Xe = person("xena")
check(not Ve.get(B + "/api/state").json()["me"].get("workspaces"), "setup: vera has no organisation")
GB = folder(Ve, "Studio")
check(Ve.post(B + f"/api/files/nodes/{GB}/shares", json={"user_id": WIM, "role": "edit"}).status_code == 201, "shared with wim to edit")
F1 = upload(Ve, "a.txt", b"the first file", GB)
QF = upload(Wi, "wim.txt", b"wim's contribution", GB)  # the folder owner's node: goes along
LK = folder(Ve, "Locked", GB)
LKF = upload(Ve, "inside.txt", b"locked away", LK)
TR = upload(Ve, "old.txt", b"thrown away", GB)
MC = upload(Ve, "mail.eml", b"From: a@example.com\r\n\r\nhello", GB)
for n in (F1, QF, LKF, TR, MC):
    check(settled(n), f"nothing is being recognised in {n}")
# a locked folder (its key cannot be wrapped for the heir), a shortcut, the trash, the copy of a mail that goes
write("INSERT INTO fs_locks(node_id, e2e, e2e_gen) VALUES(?, 'on', 1)", (LK,))
write("INSERT INTO fs_nodes(parent_id, kind, name, owner_id, ref_kind, ref_id, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
      (GB, "link", "a task file", VERA, "att", 1, T0, T0))
write("UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE id=?", (T0, VERA, TR))
write("INSERT INTO hub_mails(owner_id, ws, message_id, subject, created_at) VALUES(?,?,?,?,?)", (VERA, f"u{VERA}", "<p2631c@example.com>", "Hello", T0))
HM = dbx("SELECT id FROM hub_mails WHERE message_id='<p2631c@example.com>'")[0][0]
write("UPDATE fs_nodes SET hub_mail_id=? WHERE id=?", (HM, MC))
# xena's public links on the file (one live, one run out) and her file request on the folder
write("INSERT INTO fs_ext_links(node_id, created_by, token_hash, token, created_at) VALUES(?,?,?,?,?)", (F1, XENA, "p2631c-h1", "p2631c-t1", T0))
write("INSERT INTO fs_ext_links(node_id, created_by, token_hash, token, expires_at, created_at) VALUES(?,?,?,?,?,?)",
      (F1, XENA, "p2631c-h2", "p2631c-t2", "2020-01-01T00:00:00Z", T0))
write("""INSERT INTO fs_upload_requests(node_id, created_by, token, token_hash, title, expires_at, created_at)
         VALUES(?,?,?,?,?,?,?)""", (GB, XENA, "p2631c-req", "p2631c-req-hash", "For the studio", "2099-01-01T00:00:00Z", T0))
# an agent of xena with a share of the file: it keeps it (as built), the dialog says so
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok
AG = Xe.post(B + "/api/my/agents", json={"username": "xhelper", "display_name": "X helper", "scopes": ["read"]})
check(AG.ok, "xena's agent " + AG.text[:120])
AGID = AG.json()["id"]
# 2.631.0 (#4584, Fable): an agent share lives in fs_shares.agent_id (files/web.py), never in user_id
write("INSERT INTO fs_shares(node_id, agent_id, role, created_by, created_at) VALUES(?,?,'view',?,?)", (F1, AGID, VERA, T0))

BEFORE = subtree(GB)
OWN = {n for n, o in BEFORE.items() if o == VERA}
check({GB, F1, QF, LK, LKF, TR, MC} <= OWN and len(OWN) == 8, f"setup: eight entries of vera in the folder ({len(OWN)})")
sh = A.get(B + f"/api/users/{VERA}/delete-info").json()["purge"]["shared"]
check(sh["to"] == {"folders": 1} and not sh["gone"], f"the folder is handed on: {sh}")
# without #4584 there is no "branches": the dialog said nothing about what stays behind
check(sh.get("branches") == [{"stay": 5, "ends": 2, "agents": 1}],
      f"per folder: 5 entries stay behind (locked folder + its file, shortcut, trash, mail copy), 2 links / requests end, 1 agent keeps it: {sh.get('branches')}")
# the person themselves sees the same numbers in their own delete dialog
me = Ve.get(B + "/api/account/delete")
check(me.ok and me.json().get("purge", {}).get("shared", {}).get("branches") == sh["branches"], "the own delete dialog counts the same " + me.text[:200])

r = A.delete(B + f"/api/users/{VERA}")
check(r.ok, "vera's account goes " + r.text[:200])
AFTER = {n: owner(n) for n in BEFORE}
missing = {n for n in OWN if AFTER[n] is None}
check(len(missing) == 5 and {LK, LKF, TR, MC} <= missing, f"exactly the five counted entries are gone ({sorted(missing)})")
check(AFTER[GB] == WIM and AFTER[F1] == WIM and AFTER[QF] == WIM, "the folder, its file and wim's contribution are wim's")
check(not dbx("SELECT 1 FROM fs_ext_links WHERE token_hash IN ('p2631c-h1', 'p2631c-h2')"), "the public links ended")
check(dbx("SELECT revoked_at FROM fs_upload_requests WHERE token_hash='p2631c-req-hash'")[0][0], "the file request ended")
check(dbx("SELECT role FROM fs_shares WHERE node_id=? AND agent_id=?", (F1, AGID)) == [("view",)], "xena's agent keeps its share")
check(not dbx("SELECT 1 FROM fs_versions WHERE node_id=?", (MC,)), "the mail copy went with the account")
r = Wi.get(B + f"/api/files/nodes/{F1}/content")
check(r.ok and r.content == b"the first file", f"wim reads the file sealed for him ({r.status_code})")

sys.exit(kt.done("p2631_c_purge_branches"))
