#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.905.0 (#5288, stage Q10 of the cross-cutting core): task, project and section templates are one kind of the shared core,
"template" (kalmido/lists/tplkind.py: org_access view, org_join admin, agent_own), on the table templates. Invented names only.
 - the start-time move (core/tplmove.py): a database of before (templates.user_id, times as TEXT -- one unreadable --, data /
   extra as TEXT, section_templates with rows) is moved by the next start: owner_id, TIMESTAMPTZ, JSONB, the section templates
   rows of kind sections (one without sections stays out), section_templates gone; the app lists and uses everything as before;
   a further start changes nothing
 - rights through the core: a member reads and uses the organisation's templates (read only), brings none into the
   organisation (403, and nothing is left behind of the refused request), keeps private ones; changing / deleting an
   organisation's template is its admins'; a section template goes into the templates' trash and comes back from there;
   the version check (409 with the current state)
 - tenant-matrix: sectpl / orgschema -- another organisation's person: 404 on every route
 - agents: their own templates through the API (agent_own), never their owner's private ones, no section templates (403)
 - a person without an organisation (freelancer-matrix: sectpl): own task and section templates, no organisation space (404)
 - the account export carries the section templates (kind sections)
2.905.0 (#5288, rebuilt on main): a section template's rename and trash are steps of the person's undo list (lists/tplundo.py, as
   task / project templates since #5476); a template is deleted for good by the core's trash run (obj_trash_tick, trash_prune +
   obj_on_purge: its file copies, its undo rows), no longer by files/trashpurge.py
usage: p2905_c_tplkind_api_test.py <datadir>      (P2905C_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, H, check, docker_logs_on_first_fail, done, fresh, nostart, sess, until  # noqa: E402

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


def restart():
    """The same database, a new start of the app (init_db runs again)."""
    if nostart("P2905C"):
        return
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1"), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    until(lambda: requests.get(B + "/api/health", timeout=3).ok, 60)


def types():
    return {r[0]: r[1] for r in sql("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='templates'")}


def mklist(s, name, secs=(), org=None):
    r = s.post(B + "/api/lists", json={"name": name, **({"org_id": org} if org else {})})
    assert r.ok, r.text
    lid = r.json()["id"]
    for n in secs:
        assert s.post(B + "/api/sections", json={"list_id": lid, "name": n}).ok
    return lid


def secnames(s, lid):
    st = s.get(B + "/api/state").json()
    return [x["name"] for x in sorted((x for x in st["sections"] if x["list_id"] == lid), key=lambda x: (x["sort"], x["id"]))]


def sct(s):
    """{name: template} of the section templates s sees."""
    return {x["name"]: x for x in s.get(B + "/api/section-templates").json()["templates"]}


def tpls(s):
    return {x["name"]: x for x in s.get(B + "/api/templates").json()["templates"]}


fresh(prefix="P2905C")
docker_logs_on_first_fail()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha Example", "lang": "en", "collab_all": True, "modules": ["comments", "agents"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u, rk in (("bob", "member"), ("rita", "readonly")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rk}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/users", json={"orgs": [], "username": "carl", "display_name": "Carl", "password": "password123", "email": "carl@example.com"})
uid["carl"] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta Example", "admin_id": uid["carl"]})
assert r.ok, r.text

# ================================================================== the start-time move from a database of before
r = A.post(B + "/api/templates", json={"kind": "task", "data": {"task": {"title": "Check the light"}}, "name": "Old private"})
check(r.ok, f"setup: a private task template {r.text[:200]}")
TA = r.json()["id"]
r = A.post(B + "/api/templates", json={"kind": "task", "data": {"task": {"title": "Call the client"}}, "name": "Old team", "space": f"org:{ORG}"})
check(r.ok and r.json()["org_id"] == ORG, f"setup: an organisation's task template (its admin) {r.text[:200]}")
TO = r.json()["id"]
canon = "to_char({0} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"+00:00\"')"
for stmt in ("ALTER TABLE templates RENAME COLUMN owner_id TO user_id",
             *(f"ALTER TABLE templates ALTER COLUMN {x} TYPE TEXT USING {canon.format(x)}" for x in ("created_at", "updated_at", "deleted_at")),
             *(f"ALTER TABLE templates ALTER COLUMN {x} DROP DEFAULT, ALTER COLUMN {x} TYPE TEXT USING {x}::text, ALTER COLUMN {x} SET DEFAULT '{{}}'"
               for x in ("data", "extra")),
             """CREATE TABLE section_templates (id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, user_id BIGINT NOT NULL
                REFERENCES users(id) ON DELETE CASCADE, org_id BIGINT REFERENCES orgs(id) ON DELETE CASCADE, name TEXT NOT NULL,
                sections TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""):
    sql(stmt, write=True)
sql("UPDATE templates SET updated_at='last tuesday' WHERE id=?", (TA,), write=True)  # no ISO time: becomes the start's time
for name, org, secs in (("Film private", None, ["Idea", "Shoot", "Edit"]), ("Film team", ORG, ["Prep", "Shoot"]), ("Empty", None, [])):
    sql("INSERT INTO section_templates(user_id, org_id, name, sections, created_at, updated_at) VALUES(?,?,?,?,?,?)",
        (ALICE, org, name, json.dumps(secs), "2026-10-01T08:00:00+00:00", "2026-10-02T09:30:00+00:00"), write=True)
check(types().get("user_id") == "bigint" and types().get("data") == "text", "setup: the table as before 2.905")
restart()
A, Bo, Ri, Ca = sess("alice"), sess("bob"), sess("rita"), sess("carl")
t = types()
check("owner_id" in t and "user_id" not in t, f"move: user_id is owner_id now {sorted(t)}")
check(all(t.get(x) == "timestamp with time zone" for x in ("created_at", "updated_at", "deleted_at")), f"move: the times are TIMESTAMPTZ {t}")
check(t.get("data") == "jsonb" and t.get("extra") == "jsonb", f"move: data / extra are JSONB {t}")
check(sql("SELECT to_regclass('section_templates')")[0][0] is None, "move: section_templates is gone")
moved = {r[0]: r for r in sql("SELECT name, owner_id, org_id, data, created_at FROM templates WHERE kind='sections'")}
check(set(moved) == {"Film private", "Film team"}, f"move: the section templates with sections came over, the empty one not {sorted(moved)}")
check(moved.get("Film team") and moved["Film team"][1] == ALICE and moved["Film team"][2] == ORG
      and json.loads(moved["Film team"][3]) == {"sections": ["Prep", "Shoot"]}, f"move: owner, workspace and sections kept {moved.get('Film team')}")
check(moved.get("Film private") and str(moved["Film private"][4]).replace(" ", "T").startswith("2026-10-01T08:00:00"), f"move: the time kept {moved.get('Film private')}")
ta = tpls(A)
check({"Old private", "Old team"} <= set(ta) and not ({"Film private", "Film team"} & set(ta)),
      f"move: the task templates as before, the section templates not among them {sorted(ta)}")
check(ta.get("Old private", {}).get("updated_at", "")[:2] == "20", f"move: an unreadable time became a time {ta.get('Old private')}")
sa = sct(A)
check(sa.get("Film private", {}).get("sections") == ["Idea", "Shoot", "Edit"] and sa.get("Film team", {}).get("org_id") == ORG,
      f"move: the section templates in their dialog with names and sections {sa}")
sb = sct(Bo)
check(set(sb) == {"Film team"} and sb["Film team"]["can_edit"] is False, f"move: a member sees the organisation's one, read only {sb}")
check(not sct(Ca), "move: another organisation sees none")
LB = mklist(Bo, "Bob's shoot", ("shoot",))
r = Bo.post(B + f"/api/lists/{LB}/sections/from-template", json={"template_id": sb["Film team"]["id"]})
check(r.ok and [x["name"] for x in r.json()["added"]] == ["Prep"] and r.json()["skipped"] == ["Shoot"], f"move: a member uses it {r.text[:200]}")
check(secnames(Bo, LB) == ["shoot", "Prep"], f"move: the sections are there {secnames(Bo, LB)}")
n0 = sql("SELECT COUNT(*) FROM templates")[0][0]
restart()
A, Bo, Ri, Ca = sess("alice"), sess("bob"), sess("rita"), sess("carl")
check(sql("SELECT COUNT(*) FROM templates")[0][0] == n0 and types() == t, "move: a further start changes nothing")

# ================================================================== rights through the core
FT = sct(A)["Film team"]["id"]
r = Bo.post(B + "/api/section-templates", json={"name": "Bob team", "sections": ["X"], "space": f"org:{ORG}"})
check(r.status_code == 403, f"rights: a member brings no section template into the organisation (2.905.0) {r.status_code}")
r = Bo.post(B + "/api/templates", json={"kind": "task", "data": {"task": {"title": "x"}}, "name": "Bob team task", "space": f"org:{ORG}"})
check(r.status_code == 403, f"rights: nor a task template {r.status_code}")
check("Bob team" not in sct(Bo) and "Bob team task" not in tpls(Bo)
      and not sql("SELECT 1 FROM templates WHERE name IN ('Bob team', 'Bob team task')"), "rights: nothing of the refused requests stays")
r = Bo.post(B + "/api/section-templates", json={"name": "Bob own", "sections": ["Mine"]})
check(r.ok and r.json()["space"] == "private" and r.json()["mine"] and r.json()["can_edit"], f"rights: a member keeps private ones {r.text[:200]}")
check("Bob own" not in sct(A), "rights: the admin does not see a member's private template")
check(Bo.patch(B + f"/api/section-templates/{FT}", json={"name": "x"}).status_code == 403, "rights: a member does not change the organisation's")
check(Bo.delete(B + f"/api/section-templates/{FT}").status_code == 403, "rights: nor delete it")
# 2.905.0 review F2: a member who OWNS an organisation's template (made before 2.905.0, or a demoted admin) changes it no more
r = A.post(B + "/api/section-templates", json={"name": "Member made", "sections": ["Old"], "space": f"org:{ORG}"})
MM = r.json()["id"]
sql("UPDATE templates SET owner_id=? WHERE id=?", (uid["bob"], MM), write=True)
check(sct(Bo).get("Member made", {}).get("can_edit") is False, f"rights: the member owner sees it read only {sct(Bo).get('Member made')}")
check(Bo.patch(B + f"/api/section-templates/{MM}", json={"name": "x"}).status_code == 403, "rights: the member owner does not change it")
check(Bo.delete(B + f"/api/section-templates/{MM}").status_code == 403, "rights: nor deletes it")
check(A.delete(B + f"/api/section-templates/{MM}").ok, "rights: its admin deletes it")
# 2.905.0 (#5288, Fable review F1): an owner in a role without the full view (a demoted admin as guest) no longer reads the
# organisation's templates -- the core gives an owner 'view' in any role; before 2.905.0 the rule asked for the full view
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "guest"}], "username": "gus", "display_name": "Gus",
                                   "password": "password123", "email": "gus@example.com"})
check(r.ok, f"F1: a guest of the organisation {r.text[:200]}")
uid["gus"] = r.json()["id"]
GU = sess("gus")
r = A.post(B + "/api/section-templates", json={"name": "Guest owned", "sections": ["G"], "space": f"org:{ORG}"})
GO = r.json()["id"]
r = A.post(B + "/api/templates", json={"kind": "task", "data": {"task": {"title": "g"}}, "name": "Guest owned task", "space": f"org:{ORG}"})
GT = r.json()["id"]
sql("UPDATE templates SET owner_id=? WHERE id IN (?, ?)", (uid["gus"], GO, GT), write=True)
check("Guest owned" not in sct(GU) and "Guest owned task" not in tpls(GU), "F1: the guest owner does not list the organisation's templates")
check(GU.patch(B + f"/api/templates/{GT}", json={"name": "x"}).status_code == 404, "F1: nor reaches a task template (404)")
check(GU.patch(B + f"/api/section-templates/{GO}", json={"name": "x"}).status_code == 404, "F1: nor reaches its routes (404)")
check("Guest owned" in sct(Ri) and "Guest owned task" in tpls(Ri), "F1: a read-only member still reads them")
check(Ri.get(B + "/api/section-templates").ok and "Film team" in sct(Ri), "rights: a read-only member reads it")
check(A.patch(B + f"/api/templates/{FT}", json={"name": "x"}).status_code == 404 and Bo.patch(B + f"/api/templates/{FT}", json={"name": "x"}).status_code == 404,
      "rights: a section template is no task / project template (404, also for a member: not 403)")
r = A.patch(B + f"/api/section-templates/{FT}", json={"sections": ["Prep", "Shoot", "Grade"], "expect_updated_at": "2020-01-01T00:00:00+00:00"})
check(r.status_code == 409 and r.json().get("template", {}).get("sections") == ["Prep", "Shoot"], f"rights: an old version 409 with the current state {r.status_code} {r.text[:200]}")
cur = sct(A)["Film team"]["updated_at"]
r = A.patch(B + f"/api/section-templates/{FT}", json={"sections": ["Prep", "Shoot", "Grade"], "expect_updated_at": cur})
check(r.ok and r.json()["sections"] == ["Prep", "Shoot", "Grade"], f"rights: the admin changes it with the version she read {r.text[:200]}")
# 2.905.0 (#5288): a section template's rename is a step of the person's undo list (lists/tplundo.py), taken back by name
r = A.patch(B + f"/api/section-templates/{FT}", json={"name": "Film crew"})
check(r.ok and r.json().get("undo_group") and "Film crew" in sct(Bo), f"undo: the rename of a section template is a step {r.text[:160]}")
r = A.post(B + f"/api/undo/to/{r.json().get('undo_group')}")
check(r.ok and "Film team" in sct(Bo) and sct(Bo)["Film team"]["sections"] == ["Prep", "Shoot", "Grade"],
      f"undo: taken back -- its old name, its sections kept {r.text[:160]} {sorted(sct(Bo))}")
r = A.delete(B + f"/api/section-templates/{FT}")
check(r.ok and r.json().get("trash") and "Film team" not in sct(Bo), f"rights: the admin deletes it into the trash, gone for the members {r.text[:120]}")
UG = r.json().get("undo_group")
check(UG and A.post(B + f"/api/undo/to/{UG}").ok and "Film team" in sct(Bo), f"undo: the delete taken back, the members see it again {UG}")
check(A.post(B + f"/api/undo/{UG}/redo").ok and "Film team" not in sct(Bo), "undo: redo puts it into the trash again")
trash = [x["id"] for x in A.get(B + "/api/trash/parts").json()["items"] if x["kind"] == "template"]
check(FT in trash, f"rights: in the admin's trash {trash}")
check(Bo.post(B + f"/api/templates/{FT}/restore").status_code == 404, "rights: a member does not restore it")
r = A.post(B + f"/api/templates/{FT}/restore")
check(r.ok and sct(Bo).get("Film team", {}).get("sections") == ["Prep", "Shoot", "Grade"], f"rights: restored, the members see it again {r.text[:120]}")
r = A.patch(B + f"/api/templates/{TO}", json={"space": "private"})
check(r.ok and r.json()["org_id"] is None and "Old team" not in tpls(Bo), f"rights: the admin takes a template out of the organisation {r.text[:160]}")
check(A.patch(B + f"/api/templates/{TO}", json={"space": f"org:{ORG}"}).ok and "Old team" in tpls(Bo), "rights: and brings it back")
# the trash period: a template deleted for good takes its rows of the core with it (the history of its moves)
check(sql("SELECT COUNT(*) FROM obj_history WHERE kind='template' AND ref_id=?", (TO,))[0][0] >= 2, "trash: the moves are in the core's history")
check(A.delete(B + f"/api/templates/{TO}").ok, "trash: the admin deletes the organisation's task template")
sql("UPDATE templates SET deleted_at='2020-01-01T00:00:00+00:00' WHERE id=?", (TO,), write=True)
out = subprocess.run(["docker", "exec", "-e", "KALMIDO_RETENTION_PURGE=1", CT, "python", "-c",
                      "import app\nfrom kalmido.core.db import connect\nfrom kalmido.files.trashpurge import tp_tick\n"
                      "from kalmido.core.writes import obj_trash_tick\n"
                      "c = connect()\nprint('counts', tp_tick(c, True), obj_trash_tick(c, force=True))\nc.close()"], capture_output=True, text=True)
check("counts" in out.stdout and "Traceback" not in out.stderr, "trash: the trash run ran " + (out.stdout + out.stderr)[-400:])
# 2.905.0 (#5288): the core's run deletes it (obj_trash_tick reports kind template), the old area run no more
check("'template': 1" in out.stdout and "'templates'" not in out.stdout, "trash: the core's run deleted it " + out.stdout[-300:])
check(not sql("SELECT 1 FROM templates WHERE id=?", (TO,)) and not sql("SELECT 1 FROM obj_history WHERE kind='template' AND ref_id=?", (TO,))
      and not sql("SELECT 1 FROM obj_undo WHERE kind='list_template' AND ref_id=?", (TO,)),
      "trash: deleted for good with its history and undo rows")
# tenant-matrix: sectpl / orgschema
LC = mklist(Ca, "Carl's list", ("A",))
check(Ca.patch(B + f"/api/section-templates/{FT}", json={"name": "x"}).status_code == 404, "tenant: another organisation cannot change it (404)")
check(Ca.delete(B + f"/api/section-templates/{FT}").status_code == 404, "tenant: nor delete it (404)")
check(Ca.post(B + f"/api/lists/{LC}/sections/from-template", json={"template_id": FT}).status_code == 404, "tenant: nor use it (404)")
check(Ca.post(B + f"/api/templates/{FT}/restore").status_code == 404, "tenant: nor restore it (404)")
check(Ca.post(B + f"/api/templates/{TA}/apply", json={"list_id": LC}).status_code == 404, "tenant: nor a task template of Alpha's (404)")
check(Ca.post(B + "/api/section-templates", json={"name": "x", "sections": ["X"], "space": f"org:{ORG}"}).status_code == 404,
      "tenant: nothing into another organisation (404)")

# ================================================================== agents: their own templates, the app's section templates not
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "structure"], "username": "planbot", "display_name": "Planbot", "org_id": ORG})
assert r.status_code in (200, 201), r.text
r0 = r
AGH = {**H, "Authorization": "Bearer " + r.json()["token"]}
r = requests.post(V + "/templates", headers=AGH, json={"kind": "task", "data": {"task": {"title": "Bot step"}}, "name": "Bot template"})
check(r.status_code == 201, f"agent: makes a template of its own {r.status_code} {r.text[:200]}")
names = [x["name"] for x in requests.get(V + "/templates", headers=AGH).json().get("data", [])]
check(names == ["Bot template"], f"agent: lists its own only (not its owner's, not the organisation's, no section templates) {names}")
check(requests.get(B + "/api/section-templates", headers=AGH).status_code in (401, 403), "agent: no section templates")
check("Bot template" not in tpls(A), "agent: its template is not alice's")
# 2.905.0 (#5288, review): a key limited to projects sees no template - so it makes none either (403, nothing left behind)
AGID = r0.json()["id"]
LAG = mklist(A, "Bot's project")
check(A.put(B + f"/api/lists/{LAG}/members", json={"user_id": AGID, "role": "edit"}).ok, "setup: the project is shared with the agent")
check(A.patch(B + f"/api/admin/agents/{AGID}", json={"list_ids": [LAG], "bridge_ok": True}).ok, "setup: the agent is limited to that project")
r = requests.post(V + "/templates", headers=AGH, json={"kind": "task", "data": {"task": {"title": "Fenced"}}, "name": "Fenced template"})
check(r.status_code == 403, f"agent limited to projects: makes no template (403) {r.status_code} {r.text[:200]}")
check(not sql("SELECT 1 FROM templates WHERE name='Fenced template'"), "agent limited to projects: nothing was stored")
check(A.patch(B + f"/api/admin/agents/{AGID}", json={"list_ids": [], "bridge_ok": True}).ok, "setup: the limit lifted again")

# ================================================================== a person without an organisation (freelancer-matrix: sectpl)
FID, Fr = freelancer(B, A)
LF = mklist(Fr, "Free list", ("Ask", "Offer"))
r = Fr.post(B + "/api/section-templates", json={"name": "Sales", "list_id": LF})
check(r.ok and r.json()["space"] == "private" and r.json()["can_edit"], f"freelancer: an own section template {r.text[:200]}")
r = Fr.post(B + "/api/templates", json={"kind": "task", "data": {"task": {"title": "Follow up"}}, "name": "Free task"})
check(r.ok and r.json()["can_edit"], f"freelancer: an own task template {r.text[:200]}")
check(set(sct(Fr)) == {"Sales"} and set(tpls(Fr)) == {"Free task"}, f"freelancer: sees only her own {sorted(sct(Fr))} {sorted(tpls(Fr))}")
check(Fr.post(B + "/api/section-templates", json={"name": "x", "sections": ["X"], "space": f"org:{ORG}"}).status_code == 404,
      "freelancer: no organisation space (404)")
check(Fr.post(B + f"/api/lists/{LF}/sections/from-template", json={"template_id": FT}).status_code == 404, "freelancer: not Alpha's template (404)")

# ================================================================== the account export
ex = A.get(B + "/api/export.json").json().get("templates", [])
check(any(x.get("kind") == "sections" and x.get("name") == "Film private" for x in ex), f"export: the own section templates come along {[x.get('name') for x in ex]}")

sys.exit(done("p2817_c_tplkind_api"))
