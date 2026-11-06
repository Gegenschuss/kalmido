#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.609.0 (#3372 / #3373): the findings of the review of ticket types and the organisation's schema, each with its
regression check. Own container (hosted, a server key: sealed files and a support session). Invented names only.
 - F1 an organisation's task template goes into a private project / the inbox only through its admin (logged), a member gets
   403; its project template makes the project in the organisation only: a read-only member 403 (was: privately), a support
   session without the organisation's own support access 403 support_session
 - F2 an admin who makes another admin's organisation template private owns it now (with its file copies)
 - F4 an organisation's templates stay when their maker's account goes (the heir owns them, their files still open);
   they no longer count for their maker's limit
usage: p2609_c_review_api_test.py <datadir>"""
import os
import sys

import requests

import dbx as dbxm
import kt
from kt import B, H, check, dbx, sess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer, login, org_join  # noqa: E402

KEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (32 bytes, base64)
PW = kt.PASSWORD
V = B + "/api/v1"
FEAT = "collab,comments,fields"

kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_HOSTED": "1"})
assert kt.sess(None).post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": PW}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
ORG = A.get(B + "/api/orgs").json()["orgs"][0]["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u, role in (("bob", "member"), ("dora", "admin"), ("eve", "admin"), ("rita", "readonly"), ("gina", "guest"), ("cara", "member")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": PW, "email": f"{u}@example.com",
                                       "orgs": [{"id": ORG, "role": role}]})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/users", json={"username": "carl", "display_name": "Carl", "password": PW, "email": "carl@example.com"})
assert r.ok, r.text
Bo, Do, Ev, Ri, Gi, Cc, Ca = (login(B, u) for u in ("bob", "dora", "eve", "rita", "gina", "cara", "carl"))
for s in (A, Bo, Do, Ev, Ri, Gi, Cc, Ca):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT}).ok
FID, Fr = freelancer(B, A)


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"), timeout=10)
    c.execute(sql, args)
    c.commit()
    c.close()


def st(s):
    return s.get(B + "/api/state").json()


def mklist(s, name, org=None, **kw):
    r = s.post(B + "/api/lists", json={"name": name, "kind": "project", "org_id": org, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def attach(s, tid, name, data):
    assert s.post(B + f"/api/tasks/{tid}/attachments", files={"file": (name, data, "text/plain")}).ok


def files_of(tid):
    return dbx("SELECT id, name FROM attachments WHERE task_id=? AND deleted_at IS NULL ORDER BY id", (tid,))


def tok(s, scopes):
    r = s.post(B + "/api/me/tokens", json={"name": "t", "scopes": list(scopes)})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["token"], **H}


def tpl(s, **kw):
    r = s.post(B + "/api/templates", json=kw)
    assert r.ok, r.text
    return r.json()["id"]


def trash_tpls(s):
    return [x["id"] for x in s.get(B + "/api/trash/parts").json()["items"] if x["kind"] == "template"]


L1 = mklist(A, "Support desk", ORG, tickets=True)
for u, role in (("bob", "edit"), ("dora", "edit"), ("eve", "edit"), ("gina", "edit")):
    assert A.put(B + f"/api/lists/{L1}/members", json={"user_id": uid[u], "role": role}).ok
LB = mklist(Bo, "Bob's own", None)
LA = mklist(A, "Alice's own", None)
check(next(x for x in st(Bo)["lists"] if x["id"] == LB)["org_id"] is None, "setup: bob has a private project")
T1 = task(A, L1, "Printer jams")

# ================================================================== F1 applying an organisation's template
TT = tpl(A, task_id=T1, name="Jam fix", space=f"org:{ORG}")
r = Bo.post(B + f"/api/templates/{TT}/apply", json={"list_id": LB})
check(r.status_code == 403, f"F1: a member does not put the organisation's template into a private project {r.status_code} {r.text[:120]}")
r = Bo.post(B + f"/api/templates/{TT}/apply", json={})
check(r.status_code == 403, f"F1: nor into the own inbox {r.status_code}")
check(not any(t["title"] == "Printer jams" and t["list_id"] != L1 for t in st(Bo)["tasks"]), "F1: nothing landed outside")
r = Bo.post(B + f"/api/templates/{TT}/apply", json={"list_id": L1})
check(r.ok, f"F1: into a project of the organisation it works {r.text[:120]}")
n0 = dbx("SELECT COUNT(*) FROM org_list_log WHERE org_id=? AND action='moveout' AND detail LIKE ?", (ORG, '%"template"%'))[0][0]
r = A.post(B + f"/api/templates/{TT}/apply", json={"list_id": LA})
check(r.ok, f"F1: the admin takes it into her own project {r.text[:120]}")
n1 = dbx("SELECT COUNT(*) FROM org_list_log WHERE org_id=? AND action='moveout' AND detail LIKE ?", (ORG, '%"template"%'))[0][0]
check(n1 == n0 + 1, f"F1: logged as a move out of the organisation {n0} -> {n1}")
TP = tpl(A, list_id=L1, name="Desk project", space=f"org:{ORG}")
before = len(dbx("SELECT id FROM lists WHERE deleted_at IS NULL"))
r = Ri.post(B + f"/api/templates/{TP}/apply", json={"name": "Rita's desk"})
check(r.status_code == 403, f"F1: a read-only member cannot make the organisation's project (was: privately) {r.status_code} {r.text[:120]}")
check(len(dbx("SELECT id FROM lists WHERE deleted_at IS NULL")) == before, "F1: no project was made")
r = Bo.post(B + f"/api/templates/{TP}/apply", json={"name": "Bob's desk"})
check(r.ok and dbx("SELECT org_id FROM lists WHERE id=?", (r.json().get("list_id"),)) == [(ORG,)], f"F1: a member makes it in the organisation {r.text[:120]}")

# F1 (not checked by the review): a support session and the organisation's fixed org_id
r = Ca.post(B + "/api/orgs", json={"name": "Client Studio"})
assert r.status_code == 201, r.text
CO = r.json()["id"]
assert Ca.put(B + f"/api/orgs/{CO}/members", json={"email": "cara@example.com"}).ok
assert org_join(B, "cara", CO)
CL = mklist(Ca, "Studio board", CO)
CT = tpl(Ca, list_id=CL, name="Studio project", space=f"org:{CO}")
r = Cc.post(B + f"/api/templates/{CT}/apply", json={"name": "Cara's studio"})
check(r.ok and dbx("SELECT org_id FROM lists WHERE id=?", (r.json().get("list_id"),)) == [(CO,)], f"F1: cara's own session makes it {r.text[:120]}")
assert Cc.post(B + "/api/support-access", json={"hours": 1}).ok
r = A.post(B + f"/api/users/{uid['cara']}/signin-link")
assert r.ok, r.text
Y = kt.sess(None)
assert Y.post(B + "/api/auth/link", json={"token": r.json()["link"].split("#signin/")[1]}).ok
n0 = dbx("SELECT COUNT(*) FROM lists WHERE org_id=?", (CO,))[0][0]
r = Y.post(B + f"/api/templates/{CT}/apply", json={"name": "Support's studio"})
check(r.status_code == 403 and r.json().get("code") == "support_session",
      f"F1: a support session makes no project in an organisation without its own support access {r.status_code} {r.text[:120]}")
check(dbx("SELECT COUNT(*) FROM lists WHERE org_id=?", (CO,))[0][0] == n0, "F1: nothing was made there")

# ================================================================== F4 the maker's account goes
TF0 = task(Do, L1, "Escalation")
attach(Do, TF0, "spec.txt", b"the spec\n")
TF = tpl(Do, task_id=TF0, name="Escalation", space=f"org:{ORG}")
r = A.delete(B + f"/api/users/{uid['dora']}")
check(r.ok, f"F4: dora's account deleted {r.status_code} {r.text[:160]}")
check(dbx("SELECT user_id, org_id FROM templates WHERE id=?", (TF,)) == [(ALICE, ORG)], "F4: the organisation's template stays, with the heir")
check(any(x["id"] == TF for x in Bo.get(B + "/api/templates").json()["templates"]), "F4: the members still see it")
r = Bo.post(B + f"/api/templates/{TF}/apply", json={"list_id": L1})
nt = r.json().get("task", {}).get("id") if r.ok else None
f = files_of(nt) if nt else []
check(f and Bo.get(B + f"/api/attachments/{f[0][0]}").content == b"the spec\n", f"F4: its file opens after the key went {r.text[:120]} {f}")
# the limit: the organisation's templates no longer count for the person who made them
dbw("INSERT INTO templates(user_id,kind,name,data,created_at,updated_at,org_id) SELECT ?, 'task', 'bulk ' || g, '{\"task\":{\"title\":\"x\"}}', "
    "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', ? FROM generate_series(1, 200) g", (ALICE, ORG))
r = A.post(B + "/api/templates", json={"kind": "task", "data": {"task": {"title": "Mine"}}, "name": "Still mine"})
check(r.ok, f"F4: 200 organisation templates do not block her own {r.status_code} {r.text[:120]}")
r = A.post(B + "/api/templates", json={"kind": "task", "data": {"task": {"title": "One more"}}, "name": "Org 201", "space": f"org:{ORG}"})
check(r.status_code == 400, f"F4: the organisation has its own limit {r.status_code}")
dbw("DELETE FROM templates WHERE org_id=? AND name LIKE 'bulk %'", (ORG,))

# ================================================================== F2 an admin makes another admin's template private
TD0 = task(Ev, L1, "Eve's checklist")
attach(Ev, TD0, "steps.txt", b"step one\n")
TD = tpl(Ev, task_id=TD0, name="Eve's checklist", space=f"org:{ORG}")
check(dbx("SELECT user_id FROM template_files WHERE template_id=?", (TD,)) == [(uid["eve"],)], "setup: the template has eve's file copy")
r = A.patch(B + f"/api/templates/{TD}", json={"space": "private"})
check(r.ok and r.json()["org_id"] is None and r.json()["mine"] is True, f"F2: the admin who makes it private owns it {r.text[:160]}")
check(dbx("SELECT user_id FROM templates WHERE id=?", (TD,)) == [(ALICE,)], "F2: user_id = the admin")
check(dbx("SELECT user_id FROM template_files WHERE template_id=?", (TD,)) == [(ALICE,)], "F2: its file copies follow")
check(not any(x["id"] == TD for x in Ev.get(B + "/api/templates").json()["templates"]), "F2: not eve's private template")
r = A.post(B + f"/api/templates/{TD}/apply", json={"list_id": LA})
nt = r.json().get("task", {}).get("id") if r.ok else None
f = files_of(nt) if nt else []
check(f and A.get(B + f"/api/attachments/{f[0][0]}").content == b"step one\n", f"F2: its file still opens {r.text[:120]} {f}")

sys.exit(kt.done("p2609_c_review_api"))
