#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1076.0 (#5271, stage Q3 of the cross-cutting core): the links' core obj_links (kalmido/core/objlinks.py, routes
core/objlinkweb.py) and the four areas moved onto it.
 - the generic API: 'write' on the source + 'view' on the target; a read-only member 403, another organisation / an agent
   without a share 404, two workspaces 409, an area's own relation through the generic route 409, an end-to-end locked
   project 409; the list shows the other side with title and address, a target the reader may not see is left out (a
   participant), a deleted target answers 'gone' (no title) and comes back with its restore; removing = the person's undo
   list (X-Kalmido-Undo-Gid, POST /api/undo/<gid>/undo brings the same row back)
 - agents (API v1): list / link / unlink through a project shared with them, another agent without a share 404
 - the areas: a contact's task link (rel contact, extra.kind) removed and taken back through the undo list, a device link of a
   person without an organisation the same (her own row: owner_id)
 - the move at the start (core/objlinks.py olnk_move): rows of hub_mail_links, life_device_links, contact_tasks and
   office_letter_links arrive in obj_links with their relation, workspace, owner, extra and trash state
freelancer-matrix: obj (her private tasks linked, listed, unlinked; her device link)
tenant-matrix: obj (another organisation's person: 404 on the list and the link; an agent without a share 404)
usage: p21076_a_objlinks_test.py <datadir>"""
import json
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, DATA, H, check, docker_logs_on_first_fail, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

V = B + "/api/v1"


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


def hdr(token):
    return {**H, "Authorization": "Bearer " + token}


fresh(prefix="P21076A")
docker_logs_on_first_fail()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True,
                                     "modules": ["cal", "comments", "collab", "agents"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u, rk in (("bob", "member"), ("rita", "readonly"), ("pia", "member")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rk}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as {rk} " + r.text[:200])
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
r = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]})
check(r.ok, "setup: another organisation with olga as its admin " + r.text[:200])
BOB, RITA, PIA, OLGA = (uid[u] for u in ("bob", "rita", "pia", "olga"))
S = {u: sess(u) for u in ("bob", "rita", "pia", "olga")}
S["alice"] = A
for s in S.values():
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
Bo, Ri, Pi, Ol = (S[u] for u in ("bob", "rita", "pia", "olga"))
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "planbot", "display_name": "Planbot", "org_id": ORG})
assert r.status_code in (200, 201), r.text
AG, AGH = r.json()["id"], hdr(r.json()["token"])
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "lonebot", "display_name": "Lonebot", "org_id": ORG})
assert r.status_code in (200, 201), r.text
AG2H = hdr(r.json()["token"])
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"workspace": "private"})


def links(s, kind, rid):
    r = s.get(B + f"/api/obj/{kind}/{rid}/links")
    return r.json().get("links") if r.ok else r.status_code


def link(s, kind, rid, okind, oid, **kw):
    return s.post(B + f"/api/obj/{kind}/{rid}/links", json={"kind": okind, "id": oid, **kw})


def live(lid):
    r = sql("SELECT deleted_at FROM obj_links WHERE id=?", (lid,))
    return bool(r) and r[0][0] is None


# ================================================================ the generic API
r = Bo.post(B + "/api/lists", json={"name": "Shoot plan", "org_id": ORG})
check(r.ok, "setup: bob's project " + r.text[:160])
P = r.json()["id"]
for who, rl in ((RITA, "edit"), (PIA, "participant"), (AG, "edit")):
    r = Bo.put(B + f"/api/lists/{P}/members", json={"user_id": who, "role": rl})
    check(r.ok, f"setup: member {who} as {rl} " + r.text[:160])
T1 = Bo.post(B + "/api/tasks", json={"title": "Location scout", "list_id": P, "assignee_id": PIA}).json()["id"]
T2 = Bo.post(B + "/api/tasks", json={"title": "Call the venue", "list_id": P}).json()["id"]
T3 = Bo.post(B + "/api/tasks", json={"title": "Budget", "list_id": P}).json()["id"]

r = link(Bo, "task", T1, "task", T2, note="first the venue")
check(r.status_code == 201 and r.json().get("id"), "bob links two tasks of his project " + r.text[:200])
L12 = r.json().get("id")
lk = links(Bo, "task", T1)
check(isinstance(lk, list) and len(lk) == 1 and lk[0]["dir"] == "out" and lk[0]["rel"] == "related" and lk[0]["note"] == "first the venue"
      and lk[0]["other"] == {"kind": "task", "id": T2, "state": "ok", "title": "Call the venue", "open_url": f"t/{T2}"},
      f"the source lists the target with title and address {lk}")
lk = links(Bo, "task", T2)
check(isinstance(lk, list) and [(x["dir"], x["other"]["id"]) for x in lk] == [("in", T1)], f"the target lists the link the other way {lk}")
check(link(Bo, "task", T1, "task", T2).json().get("id") == L12, "linking again: the same link (one per pair and relation)")
check(sql("SELECT 1 FROM obj_history WHERE kind='task' AND ref_id=? AND action='link'", (T1,)), "the link is noted in the history of the source")
check(link(Bo, "task", T1, "task", T1).status_code == 400, "a link to itself: 400")
check(link(Bo, "task", T1, "task", T3, rel="made").status_code == 409, "an area's own relation through the generic route: 409")
check(link(Bo, "task", T1, "task", T3, rel="Bad Rel").status_code == 400, "a relation that is no name: 400")
check(link(Bo, "task", T1, "task", T3, note="x" * 501).status_code == 400, "a note over 500 characters: 400")

# rights: a read-only member reads, never links; another organisation nothing
lk = links(Ri, "task", T1)
check(isinstance(lk, list) and len(lk) == 1, f"rita (read-only) reads the links {lk}")
check(link(Ri, "task", T1, "task", T3).status_code == 403, "rita (read-only) cannot link: 403")
# tenant: GET /api/obj/{}/{}/links
check(links(Ol, "task", T1) == 404, "olga (another organisation): the list 404")
OT = Ol.post(B + "/api/tasks", json={"title": "Olga's own"}).json().get("id")
# tenant: POST /api/obj/{}/{}/links
check(OT and link(Ol, "task", OT, "task", T1).status_code == 404, "olga links her task to bob's: 404 (the target is not hers to see)")
check(link(Ol, "task", T1, "task", T2).status_code == 404 and not sql("SELECT 1 FROM obj_links WHERE created_by=?", (OLGA,)),
      "olga links from bob's task: 404, nothing written")
check(Ol.delete(B + f"/api/obj/links/{L12}").status_code == 404, "olga removes bob's link: 404")
# two workspaces: bob's private task with his organisation's task
BP = Bo.post(B + "/api/lists", json={"name": "Bob private", "org_id": None}).json()["id"]
BT = Bo.post(B + "/api/tasks", json={"title": "Private note", "list_id": BP}).json()["id"]
check(link(Bo, "task", BT, "task", T1).status_code == 409, "a private task with an organisation's task: 409 (one workspace)")
# end-to-end lock: never a link into a locked project (the lock set straight in the database)
PE = Bo.post(B + "/api/lists", json={"name": "Locked", "org_id": ORG}).json()["id"]
TE = Bo.post(B + "/api/tasks", json={"title": "Sealed", "list_id": PE}).json()["id"]
sql("UPDATE lists SET e2e=? WHERE id=?", (json.dumps({"v": 1}), PE), write=True)
r = link(Bo, "task", T1, "task", TE)
check(r.status_code == 409 and not sql("SELECT 1 FROM obj_links WHERE dst_kind='task' AND dst_id=?", (TE,)), "a target in a locked project: 409 " + r.text[:160])
sql("UPDATE lists SET e2e=NULL WHERE id=?", (PE,), write=True)

# a target the reader may not see is left out: pia (participant) sees T1 (assigned), not T3
check(link(Bo, "task", T1, "task", T3).status_code == 201, "setup: T1 -> T3")
lk = links(Pi, "task", T1)
check(isinstance(lk, list) and T3 not in [x["other"].get("id") for x in lk] and all(x["other"].get("state") for x in lk),
      f"pia (participant): the task she may not see is left out {lk}")

# "target deleted" once in the core: the task in the trash answers 'gone' without a title, back with its restore
check(Bo.delete(B + f"/api/tasks/{T2}").ok, "setup: T2 into the trash")
lk = links(Bo, "task", T1)
o = next((x["other"] for x in lk if x["id"] == L12), None) if isinstance(lk, list) else None
check(o == {"kind": "task", "id": T2, "state": "gone"}, f"the target in the trash: state gone, no title {o}")
check(Bo.post(B + f"/api/tasks/{T2}/restore").ok, "setup: T2 restored")
o = next((x["other"] for x in links(Bo, "task", T1) if x["id"] == L12), None)
check(o and o["state"] == "ok" and o["title"] == "Call the venue", f"restored: the link shows the target again {o}")

# removing: into the trash of the links, one step of bob's undo list, taken back = the same row
r = Bo.delete(B + f"/api/obj/links/{L12}")
gid = r.headers.get("X-Kalmido-Undo-Gid") if r.ok else None
check(r.ok and gid and not live(L12) and L12 not in [x["id"] for x in r.json().get("links") or []], f"removed: into the trash, an undo step {r.text[:160]} {gid}")
check(Ri.delete(B + f"/api/obj/links/{L12}").status_code == 404, "a link in the trash cannot be removed again: 404")
r = Bo.post(B + f"/api/undo/{gid}/undo")
check(r.ok and live(L12) and L12 in [x["id"] for x in links(Bo, "task", T1)], f"undo: the same link is back {r.status_code} {r.text[:160]}")
# a fallback-free removal: rita (read-only) cannot remove
check(Ri.delete(B + f"/api/obj/links/{L12}").status_code == 403, "rita (read-only) cannot remove a link: 403")

# ================================================================ agents (API v1)
r = requests.get(V + f"/agent/objects/task/{T1}/links", headers=AGH)
check(r.ok and any(x["id"] == L12 for x in r.json().get("data") or []), "planbot (project shared) lists the links " + r.text[:160])
r = requests.post(V + f"/agent/objects/task/{T3}/links", headers=AGH, json={"kind": "task", "id": T2, "rel": "blocks"})
check(r.status_code == 201, "planbot links two tasks of the shared project " + r.text[:200])
AL = r.json().get("id")
check(sql("SELECT agent_id, created_by, rel FROM obj_links WHERE id=?", (AL,)) == [(AG, AG, "blocks")], "the agent's link carries the agent")
# tenant: GET /api/v1/agent/objects/{}/{}/links
check(requests.get(V + f"/agent/objects/task/{T1}/links", headers=AG2H).status_code == 404, "lonebot (no share): 404")
# tenant: POST /api/v1/agent/objects/{}/{}/links
check(requests.post(V + f"/agent/objects/task/{T1}/links", headers=AG2H, json={"kind": "task", "id": T2}).status_code == 404, "lonebot links: 404")
# tenant: DELETE /api/v1/agent/objects/{}/{}/links/{}
check(requests.delete(V + f"/agent/objects/task/{T1}/links/{L12}", headers=AG2H).status_code == 404 and live(L12), "lonebot unlinks: 404, the link stays")
check(requests.get(V + f"/agent/objects/task/{T1}/links", headers=hdr("x" * 40)).status_code in (401, 403), "no valid token: refused")
check(requests.delete(V + f"/agent/objects/task/{T1}/links/{AL}", headers=AGH).status_code == 404, "unlink through an object it does not hang on: 404")
r = requests.delete(V + f"/agent/objects/task/{T3}/links/{AL}", headers=AGH)
check(r.status_code == 204 and not live(AL), "planbot removes its link " + r.text[:160])

# ================================================================ the areas on the core
# a contact's task link (contacts/model.py): rel contact, extra.kind, removed and taken back through the undo list
BK = A.post(B + "/api/books", json={"name": "Private book"}).json()["id"]
CT = A.post(B + "/api/contacts", json={"book_id": BK, "fn": "Kim Example"}).json()["id"]
AP = A.post(B + "/api/lists", json={"name": "Alice private", "org_id": None}).json()["id"]
AT = A.post(B + "/api/tasks", json={"title": "Call Kim", "list_id": AP}).json()["id"]
r = A.post(B + f"/api/tasks/{AT}/contacts", json={"contact_id": CT, "kind": "waiting"})
check(r.ok and [(x["contact_id"], x["kind"]) for x in r.json().get("items") or []] == [(CT, "waiting")], "contact link " + r.text[:200])
row = sql("SELECT id, rel, extra->>'kind' FROM obj_links WHERE src_kind='contact' AND src_id=? AND dst_kind='task' AND dst_id=?", (CT, AT))
check(len(row) == 1 and row[0][1:] == ("contact", "waiting"), f"a row of obj_links (rel contact, extra.kind) {row}")
CL = row[0][0] if row else 0
r = A.post(B + f"/api/tasks/{AT}/contacts", json={"contact_id": CT, "kind": "about"})
check(sql("SELECT id, extra->>'kind' FROM obj_links WHERE src_kind='contact' AND src_id=?", (CT,)) == [(CL, "about")], "linking again sets the kind")
lk = links(A, "task", AT)
o = lk[0]["other"] if isinstance(lk, list) and lk else {}
check(o.get("kind") == "contact" and o.get("id") == CT and o.get("title") == "Kim Example" and o.get("open_url") == f"contacts/{CT}",
      f"the generic list names the contact (the file store's reference kind) {lk}")
check(A.delete(B + f"/api/obj/links/{CL}").status_code == 409, "the contact link through the generic route: 409 (its area removes it)")
r = A.delete(B + f"/api/tasks/{AT}/contacts/{CT}")
gid = r.headers.get("X-Kalmido-Undo-Gid") if r.ok else None
check(r.ok and gid and not live(CL), f"the contact link removed: trash + undo step {gid}")
check(A.post(B + f"/api/undo/{gid}/undo").ok and live(CL)
      and [x["task_id"] for x in A.get(B + f"/api/contacts/{CT}").json().get("tasks") or []] == [AT], "undo: the contact shows the task again")

# ================================================================ a person without an organisation
# freelancer-matrix: obj -- her private tasks
FP = Fr.post(B + "/api/lists", json={"name": "Frida work"}).json()["id"]
F1 = Fr.post(B + "/api/tasks", json={"title": "Cut", "list_id": FP}).json()["id"]
F2 = Fr.post(B + "/api/tasks", json={"title": "Grade", "list_id": FP}).json()["id"]
r = link(Fr, "task", F1, "task", F2)
check(r.status_code == 201 and sql("SELECT org_id FROM obj_links WHERE id=?", (r.json().get("id"),)) == [(None,)], "freelancer: her link, private " + r.text[:160])
FL = r.json().get("id")
check([x["other"]["id"] for x in links(Fr, "task", F1)] == [F2], "freelancer: her list")
check(links(Bo, "task", F1) == 404 and Bo.delete(B + f"/api/obj/links/{FL}").status_code == 404, "bob: her task / link 404")
check(Fr.delete(B + f"/api/obj/links/{FL}").ok and links(Fr, "task", F1) == [], "freelancer: her link removed")
# her device <-> her own office's equipment (life/devlink.py): her own row, removed and taken back
Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Beispiel Einzel", "street": "Weg 1", "zip": "12345", "city": "Musterstadt",
                                                            "country": "DE"}})
FT = Fr.post(B + "/api/life/devices", json={"name": "Kamera", "serial": "SN-1"}).json()["id"]
offs = Fr.get(B + f"/api/life/devices/{FT}/link").json().get("offices") or []
r = Fr.post(B + f"/api/life/devices/{FT}/to-office", json={"office_id": offs[0]["id"] if offs else 0, "name": "Kamera"})
check(r.status_code == 201, "freelancer: the device into her own office " + r.text[:200])
DL = (r.json().get("link") or {}).get("id")
row = sql("SELECT owner_id, src_kind, src_id, dst_kind, rel, extra->>'origin' FROM obj_links WHERE id=?", (DL,))
check(row == [(FID, "task", FT, "omd_equipment", "device", "device")], f"the device link: her own row of obj_links {row}")
check(links(Bo, "task", FT) == 404, "bob: her device 404")
r = Fr.delete(B + f"/api/life/device-links/{DL}")
gid = r.headers.get("X-Kalmido-Undo-Gid") if r.ok else None
check(r.ok and gid and Fr.get(B + f"/api/life/devices/{FT}/link").json().get("link") is None, "the device link removed (undo step)")
check(Fr.post(B + f"/api/undo/{gid}/undo").ok and (Fr.get(B + f"/api/life/devices/{FT}/link").json().get("link") or {}).get("id") == DL,
      "undo: the device link is back")

# ================================================================ the move of the old tables (core/objlinks.py olnk_move)
# a version before 2.1076 ran after a rollback: its old tables are there again with rows (made here as the test's database
# user), then the app starts ("import app": init_db runs the move and the fragment 5271_a drops the tables)
for stmt in (
    "CREATE TABLE hub_mail_links (id BIGINT PRIMARY KEY, mail_id BIGINT, org_id BIGINT, kind TEXT, ref_id BIGINT, created_by BIGINT, created_at TEXT)",
    f"INSERT INTO hub_mail_links VALUES (1, 900001, {ORG}, 'task', {T1}, {ALICE}, '2026-10-01T08:00:00Z'), "
    f"(2, 900001, {ORG}, 'task', {T1}, {ALICE}, '2026-10-01T08:00:00Z'), (3, 900002, {ORG}, 'event', 900003, NULL, 'not a time')",
    "CREATE TABLE life_device_links (id BIGINT PRIMARY KEY, user_id BIGINT, task_id BIGINT, office_id BIGINT, equipment_id BIGINT, origin TEXT, "
    "created_at TEXT, updated_at TEXT)",
    f"INSERT INTO life_device_links VALUES (1, {BOB}, 900010, {ORG}, 900011, 'equipment', '2026-10-02T08:00:00Z', '2026-10-03T08:00:00Z'), "
    f"(2, {BOB}, NULL, {ORG}, 900012, 'device', '2026-10-02T08:00:00Z', '2026-10-02T08:00:00Z')",
    "CREATE TABLE contact_tasks (contact_id BIGINT, task_id BIGINT, kind TEXT, added_by BIGINT, added_at TEXT)",
    f"INSERT INTO contact_tasks VALUES (900020, {T3}, 'responsible', {ALICE}, '2026-10-04T08:00:00Z'), "
    f"(900021, {T3}, 'about', {ALICE}, ''), (900022, {T3}, 'about', NULL, NULL)",  # #5916: an empty / missing added_at
    "CREATE TABLE office_letter_links (id BIGINT PRIMARY KEY, org_id BIGINT, letter_id BIGINT, node_id BIGINT, kind TEXT, created_by BIGINT, "
    "agent_id BIGINT, created_at TEXT, deleted_at TIMESTAMPTZ, deleted_by BIGINT, rev BIGINT, updated_at TIMESTAMPTZ, updated_by BIGINT)",
    f"INSERT INTO office_letter_links VALUES (1, {ORG}, 900030, 900031, 'answers', {ALICE}, NULL, '2026-10-05T08:00:00Z', NULL, NULL, 1, NULL, NULL), "
    f"(2, {ORG}, 900030, 900032, 'reply', {ALICE}, 7, '2026-10-05T08:00:00Z', '2026-10-06T08:00:00Z', {ALICE}, 2, NULL, NULL)",
):
    sql(stmt, write=True)
out = in_app("pass")
check("obj_links: moved hub_mail_links 2, life_device_links 1, contact_tasks 3, office_letter_links 2" in out,
      f"the start moves each table's rows (a doubled mail link once, a device link without its device stays out) {out[-600:]}")
m = sql("SELECT org_id, dst_kind, dst_id, rel, created_by, created_at IS NOT NULL FROM obj_links WHERE src_kind='hub_mail' AND src_id IN (900001, 900002) ORDER BY src_id")
check([tuple(x) for x in m] == [(ORG, "task", T1, "made", ALICE, True), (ORG, "event", 900003, "made", None, True)],
      f"mail links: hub_mail -> task | event, rel made, the mail's workspace (a broken time = now) {m}")
d = sql("SELECT owner_id, org_id, src_kind, src_id, dst_kind, dst_id, extra->>'origin', extra->>'office_id' FROM obj_links WHERE rel='device' AND owner_id=?", (BOB,))
check([tuple(x) for x in d] == [(BOB, None, "task", 900010, "omd_equipment", 900011, "equipment", str(ORG))],
      f"device link: the person's own row, origin and office in extra {d}")
k = sql("SELECT src_id, dst_id, extra->>'kind', created_by FROM obj_links WHERE src_kind='contact' AND src_id=900020")
check([tuple(x) for x in k] == [(900020, T3, "responsible", ALICE)], f"contact link: rel contact, its kind in extra {k}")
k = sql("SELECT src_id, created_at IS NOT NULL FROM obj_links WHERE src_kind='contact' AND src_id IN (900021, 900022) ORDER BY src_id")
check([tuple(x) for x in k] == [(900021, True), (900022, True)],
      f"#5916: a contact link with an empty / missing added_at moves with created_at = now (the start of 2.1067 data broke off) {k}")
lt = sql("SELECT dst_id, rel, agent_id, deleted_at IS NOT NULL, org_id FROM obj_links WHERE src_kind='office_letter' AND src_id=900030 ORDER BY dst_id")
check([tuple(x) for x in lt] == [(900031, "answers", None, False, ORG), (900032, "reply", 7, True, ORG)],
      f"letter links: office_letter -> fs_entry, the kind as relation, the agent and the trash kept {lt}")
check(not sql("SELECT 1 FROM pg_tables WHERE tablename IN ('hub_mail_links', 'life_device_links', 'contact_tasks', 'office_letter_links')"),
      "the old tables are gone (a fresh database: the fragment 5271_a dropped them)")
out = in_app("from kalmido.core.objlinks import olnk_move\nprint('AGAIN', olnk_move(c))")
check("AGAIN {}" in out, f"without the old tables the move does nothing {out[-300:]}")
# the link dies with its object: a task deleted for good takes its links along (trigger kalmido_olnk_gone)
sql("DELETE FROM tasks WHERE id=?", (T3,), write=True)
check(not sql("SELECT 1 FROM obj_links WHERE (src_kind='task' AND src_id=?) OR (dst_kind='task' AND dst_id=?)", (T3, T3)),
      "a task deleted for good: its links are gone")

# ================================================================ review of 2.1076 (fixes of the review's findings)
# F1: the workspace of a side is the one of its real row -- a file of one organisation never links to a page of another
O2 = A.post(B + "/api/admin/orgs", json={"name": "Second Example", "admin_id": ALICE}).json().get("id")
O3 = A.post(B + "/api/admin/orgs", json={"name": "Third Example", "admin_id": ALICE}).json().get("id")
FA = A.post(B + "/api/files/folders", json={"name": "Shoot files", "space": f"org:{O2}"}).json().get("id")
r = A.post(B + "/api/wiki/pages", json={"space": f"org:{O3}", "path": "Shoot notes"})
WB = r.json().get("id") if r.status_code in (200, 201) else None
r = A.post(B + "/api/wiki/pages", json={"space": f"org:{O2}", "path": "Same office notes"})
WA = r.json().get("id") if r.status_code in (200, 201) else None
check(O2 and O3 and FA and WA and WB, f"setup: two more organisations of alice, a folder in one, pages in both {O2} {O3} {FA} {WA} {WB}")
r = link(A, "fs_entry", FA, "wiki_page", WB)
check(r.status_code == 409 and not sql("SELECT 1 FROM obj_links WHERE src_kind='fs_entry' AND src_id=?", (FA,)),
      "F1: a folder of one organisation with a page of another: 409, nothing written " + r.text[:160])
r = link(A, "fs_entry", FA, "wiki_page", WA)
check(r.status_code == 201 and sql("SELECT org_id FROM obj_links WHERE id=?", (r.json().get("id"),)) == [(O2,)],
      "F1: the same organisation: linked, the link in that workspace " + r.text[:160])

# F2: an agent's token needs the read scope of the other side too (an event: calendar), removing the write scope of the source
r = requests.post(V + f"/agent/objects/task/{T1}/links", headers=AGH, json={"kind": "event", "id": 999001})
check(r.status_code == 403, f"F2: planbot (no calendar scope) links a task with an event: 403 {r.status_code} {r.text[:160]}")
sql(f"INSERT INTO obj_links(org_id, src_kind, src_id, dst_kind, dst_id, rel, created_by) VALUES({ORG}, 'event', 999002, 'task', {T1}, 'related', {BOB})",
    write=True)
EL = sql("SELECT id FROM obj_links WHERE src_kind='event' AND src_id=999002")[0][0]
r = requests.delete(V + f"/agent/objects/task/{T1}/links/{EL}", headers=AGH)
check(r.status_code == 403 and live(EL), f"F2: planbot removes a link whose source is an event: 403, it stays {r.status_code} {r.text[:160]}")
sql("DELETE FROM obj_links WHERE id=?", (EL,), write=True)

# F3: a side deleted for good names its kind and id only to the link's creator; one in the trash only to who has a role on it
sql(f"INSERT INTO obj_links(org_id, src_kind, src_id, dst_kind, dst_id, rel, created_by) VALUES({ORG}, 'task', {T1}, 'task', 999003, 'related', {BOB})",
    write=True)
GL = sql("SELECT id FROM obj_links WHERE dst_kind='task' AND dst_id=999003")[0][0]
o = next((x["other"] for x in links(Ri, "task", T1) if x["id"] == GL), None)
check(o == {"state": "gone"}, f"F3: rita sees a target deleted for good as gone, without kind and id {o}")
o = next((x["other"] for x in links(Bo, "task", T1) if x["id"] == GL), None)
check(o == {"kind": "task", "id": 999003, "state": "gone"}, f"F3: bob (who linked it) keeps kind and id {o}")
sql("DELETE FROM obj_links WHERE id=?", (GL,), write=True)
T5 = Bo.post(B + "/api/tasks", json={"title": "Rehearsal", "list_id": P}).json()["id"]
r = link(Bo, "task", T1, "task", T5)
L15 = r.json().get("id")
check(r.status_code == 201 and Bo.delete(B + f"/api/tasks/{T5}").ok, "setup: T1 -> T5, T5 into the trash")
check(L15 not in [x["id"] for x in links(Ri, "task", T1)], "F3: rita (no role on a task in the trash) does not see that link")
o = next((x["other"] for x in links(Bo, "task", T1) if x["id"] == L15), None)
check(o == {"kind": "task", "id": T5, "state": "gone"}, f"F3: bob (manages it) sees it gone {o}")
check(Bo.post(B + f"/api/tasks/{T5}/restore").ok, "setup: T5 restored")

# F4: the history of the source names the relation and the kind of the other side, not its id
h = sql("SELECT vals_after FROM obj_history WHERE kind='task' AND ref_id=? AND action='link' ORDER BY id DESC LIMIT 1", (T1,))
v = json.loads(h[0][0]) if h and isinstance(h[0][0], str) else (h[0][0] if h else None)
check(v == {"link": "related:task"}, f"F4: the history entry of the link without the target's id {v}")

# F6: the boundary check sees a crossing link of every kind with a workspace (here a folder and a page of two organisations)
sql(f"INSERT INTO obj_links(org_id, src_kind, src_id, dst_kind, dst_id, rel, created_by) VALUES({O2}, 'fs_entry', {FA}, 'wiki_page', {WB}, 'probe', {ALICE})",
    write=True)
XL = sql("SELECT id FROM obj_links WHERE src_kind='fs_entry' AND src_id=? AND dst_kind='wiki_page' AND dst_id=? AND rel='probe'", (FA, WB))[0][0]
out = in_app("from kalmido.accounts.tenancy import CHECKS\nprint('CROSS', sorted(r[0] for r in c.execute(CHECKS['obj_link']).fetchall()))")
check(f"CROSS [{XL}]" in out, f"F6: the boundary check counts the crossing link, and only it {out[-400:]}")
sql("DELETE FROM obj_links WHERE id=?", (XL,), write=True)

# F5: a task deleted for good by a person takes along also a link in another organisation's workspace (row-level security)
O1 = sql("SELECT id FROM orgs WHERE name='Other Example'")[0][0]
TX = Bo.post(B + "/api/tasks", json={"title": "Wrap party", "list_id": P}).json()["id"]
sql(f"INSERT INTO obj_links(org_id, src_kind, src_id, dst_kind, dst_id, rel, created_by) VALUES({O1}, 'task', {OT}, 'task', {TX}, 'related', {OLGA})",
    write=True)
out = in_app(f"c.commit()\nc._sys = 0\nc._ctx = ({BOB}, ({ORG},), 'user')\n"
             f"print('MINE', c.execute('SELECT COUNT(*) FROM obj_links WHERE org_id={O1}').fetchone()[0])\n"
             f"c.execute('DELETE FROM tasks WHERE id={TX}')\nc.commit()\nprint('DELETED')")
check("MINE 0" in out and "DELETED" in out, f"F5: bob's context does not see the other organisation's link, and deleted his task {out[-400:]}")
check(not sql("SELECT 1 FROM obj_links WHERE dst_kind='task' AND dst_id=?", (TX,)), "F5: the link of the other workspace went with the task")

sys.exit(done("p21076_a_objlinks"))
