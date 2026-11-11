#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.925.0 (#5275, stage Q5a of the cross-cutting core): project tags and the labels of an organisation are tags of the core
(obj_tags / obj_tag_links, core/objtags.py). Own container. Invented names only.
 - the old tables (list_tags, task_list_tags, org_tags) are gone; made again by hand with rows (what a version before 2.925
   leaves after a rollback) the next start moves them: a project tag keeps its id, name, colour, order and time, a label's copy
   in a project becomes the label itself (one row, the task carries the label), a list rule naming the copy names the label
 - a project tag: set on a task (made on first use), shown in the project and on the task, taken off, deleted
 - a label of the organisation: put DIRECTLY on tasks of two projects -- one row, no copy per project; a rename reaches both;
   a new label takes over the project tag of its name (its tasks, the rule that added it); "remove from this project" takes it off one project only; the
   project cannot rename it (409); deleted, its tasks keep it as a project tag of their project
 - filters: API v1 ?tag= / ?list_tag= find a label's tasks in both projects; an agent's API v1 lists the label with org_tag_id
 - the tenant boundary: another organisation's admin gets no label of Alpha and cannot change one (404)
 - the organisation export holds the labels (org/labels.json) and the tasks' tags (tasks/tags.json with a label's id)
 - a task of an end-to-end locked project: its tag name stays plain text (decided 08.11.2026, question 10)
 - a person without an organisation: project tags work in her own project
 - review findings: F1 a project leaving its organisation on a side way / the organisation deleted keeps the labels as project
   tags, a label counts / converts only projects of its organisation; F2 / F3 the move keeps small ids, rewrites rules per
   list, keeps old SQLite times, drops links to copies of other projects; F4 a guest gets no unseen label (empty PATCH, rule
   names, rule ids, share dialog); F6 joining / the move / a full-view writer prefer the label; F7 sort of a label 409, a webhook finds a label by name; F5 the account import reads a tag of another scope
freelancer-matrix: tasks
usage: p2925_c_tags_core_test.py <datadir>"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, H, check, dbx  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402


def box(code):
    """Python inside the app container (as the system); "import app" starts the app (init_db: the move, the fragments)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\n"
                          "from kalmido.core.pg import system_ctx\nc = connect()\nwith system_ctx(c):\n"
                          + "".join("    " + ln + "\n" for ln in code.splitlines()) + "c.commit()\nc.close()"],
                         capture_output=True, text=True)
    check(out.returncode == 0, f"the run in the container works {out.stderr[-800:]}")
    return out.stdout.strip()


def table_there(t):
    return bool(dbx("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?", (t,)))


def st(s):
    return s.get(B + "/api/state").json()


def ltags_of(s, tid):
    return next((t.get("ltags") for t in st(s)["tasks"] if t["id"] == tid), None)


def list_tags(s, lid):
    return next((x.get("tags") for x in st(s)["lists"] if x["id"] == lid), None) or []


def mklist(s, name, org=None):
    r = s.post(B + "/api/lists", json={"name": name, "kind": "project", **({"org_id": org} if org else {})})
    assert r.ok, r.text
    return r.json()["id"]


def task(s, lid, title):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid})
    assert r.ok, r.text
    return r.json()["id"]


def tok(s, scopes=("read", "tasks:write", "structure")):
    return {"Authorization": "Bearer " + s.post(B + "/api/me/tokens", json={"name": "t", "scopes": list(scopes)}).json()["token"], **H}


def tagrows(name):
    return dbx("SELECT id, scope_kind, scope_id FROM obj_tags WHERE lower(name)=lower(?) ORDER BY id", (name,))


kt.fresh(prefix="P2824A")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": kt.PASSWORD})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = st(A)["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u == "bob" else [], "username": u, "display_name": u.title(),
                                       "password": kt.PASSWORD, "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
org_join(B, "bob", ORG)
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["carl"]})
assert r.status_code in (200, 201), r.text
Bo, Ca = kt.sess("bob"), kt.sess("carl")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
BOB = uid["bob"]

# ================================================================== the old tables are gone, the core's tables are there
check(table_there("obj_tags") and table_there("obj_tag_links"), "the core's tables obj_tags / obj_tag_links exist")
for t in ("list_tags", "task_list_tags", "org_tags"):
    check(not table_there(t), f"the old table {t} is gone")

L1, L2, L3 = mklist(A, "Support", ORG), mklist(A, "Sales", ORG), mklist(A, "Events", ORG)
for lid in (L1, L2, L3):
    A.put(B + f"/api/lists/{lid}/members", json={"user_id": BOB, "role": "edit"})
T1, T2, T3, T0 = task(A, L1, "Drucker klemmt"), task(A, L2, "Angebot Messe"), task(A, L3, "Standbau"), task(A, L1, "Ohne Tag")

# ================================================================== a project tag
r = Bo.patch(B + f"/api/tasks/{T1}", json={"ltags": ["Bug"]})
check(r.ok, f"bob puts a new project tag on a task {r.status_code} {r.text[:200]}")
rows = tagrows("Bug")
check(len(rows) == 1 and rows[0][1] == "list" and rows[0][2] == str(L1), f"one tag of the project in the core {rows}")
BUG = rows[0][0] if rows else 0
check(ltags_of(Bo, T1) == ["Bug"] and any(x["id"] == BUG and x["org_tag_id"] is None for x in list_tags(Bo, L1)),
      "the task and the project show it")
check(dbx("SELECT src, created_by FROM obj_tag_links WHERE tag_id=? AND kind='task' AND obj_id=?", (BUG, T1)) == [("person", BOB)],
      "the link says who set it")
check(Bo.patch(B + f"/api/tasks/{T1}", json={"ltags": []}).ok and ltags_of(Bo, T1) == [], "taken off the task")
check(tagrows("Bug") and any(x["id"] == BUG for x in list_tags(Bo, L1)), "the project keeps the tag")
check(Bo.patch(B + f"/api/tasks/{T1}", json={"ltags": ["bug"]}).ok and ltags_of(Bo, T1) == ["Bug"], "any case finds the same tag")
r = Bo.delete(B + f"/api/list-tags/{BUG}")
check(r.ok and r.json().get("ids") == [T1] and not tagrows("Bug") and ltags_of(Bo, T1) == [], f"deleted: from every task {r.text[:200]}")

# ================================================================== a label of the organisation, directly on the task
check(Bo.patch(B + f"/api/tasks/{T2}", json={"ltags": ["Kunde"]}).ok, "setup: a project tag Kunde in Sales")
OLD_KUNDE = tagrows("Kunde")[0][0]
r = A.post(B + f"/api/lists/{L2}/rules", json={"name": "Kunde markieren", "trigger": {"kind": "done"},
                                               "action": {"kind": "tag", "tag_id": OLD_KUNDE}})
check(r.ok, f"setup: a rule of Sales that adds the project tag {r.status_code} {r.text[:200]}")
KRULE = r.json().get("id")
r = A.post(B + "/api/org-labels", json={"org_id": ORG, "name": "Kunde", "color": "#f87171"})
check(r.status_code == 201, f"alice makes the label Kunde {r.status_code} {r.text[:200]}")
LB = r.json().get("id")
rows = tagrows("Kunde")
check(rows == [(LB, "org", str(ORG))], f"the label took over the project tag of its name: one row {rows} (old {OLD_KUNDE})")
check(ltags_of(Bo, T2) == ["Kunde"], "the task of Sales carries the label now")
check(json.loads(dbx("SELECT act_val FROM list_rules WHERE id=?", (KRULE,))[0][0]).get("tag_id") == LB
      and not dbx("SELECT paused_reason FROM list_rules WHERE id=? AND paused_reason<>''", (KRULE,)), "the rule of Sales adds the label now")
for t in (T1, T3):
    check(Bo.patch(B + f"/api/tasks/{t}", json={"ltags": ["kunde"]}).ok, f"bob puts the label on task {t}")
check(tagrows("Kunde") == [(LB, "org", str(ORG))], f"still ONE row: no copy per project {tagrows('Kunde')}")
links = sorted(x[0] for x in dbx("SELECT obj_id FROM obj_tag_links WHERE tag_id=? AND kind='task'", (LB,)))
check(links == sorted([T1, T2, T3]), f"the three tasks carry the label itself {links}")
for lid in (L1, L2, L3):
    check(any(x["id"] == LB and x["org_tag_id"] == LB and x["color"] == "#f87171" for x in list_tags(Bo, lid)),
          f"project {lid} shows the label in its colour")
check(Bo.patch(B + f"/api/list-tags/{LB}", json={"name": "Lead"}).status_code == 409, "a project cannot rename the label (409)")
r = A.patch(B + f"/api/org-labels/{LB}", json={"name": "Stammkunde", "color": "#c084fc"})
check(r.ok and r.json().get("lists") == 3, f"the admin renames it; it is used in three projects {r.text[:200]}")
check(all(ltags_of(Bo, t) == ["Stammkunde"] for t in (T1, T2, T3)), "the new name on every task at once")

# filters and an agent's view (API v1)
HB = tok(Bo)
got = sorted(x["id"] for x in Bo.get(B + "/api/v1/tasks", params={"tag": "stammkunde"}, headers=HB).json().get("data", []))
check(got == sorted([T1, T2, T3]), f"API v1 ?tag= finds the label's tasks in all projects {got}")
got = sorted(x["id"] for x in Bo.get(B + "/api/v1/tasks", params={"list_tag": "Stammkunde", "list_id": L1}, headers=HB).json().get("data", []))
check(got == [T1], f"?list_tag= in one project {got}")
v = Bo.get(B + f"/api/v1/lists/{L1}/tags", headers=HB).json().get("data", [])
check(any(x["id"] == LB and x["org_tag_id"] == LB and x["tasks"] == 1 for x in v), f"API v1 lists the label with org_tag_id {v}")
check(Bo.patch(B + f"/api/v1/lists/{L1}/tags/{LB}", json={"name": "x"}, headers=HB).status_code == 409, "API v1 cannot rename it either")
check(Bo.post(B + "/api/org-labels", json={"org_id": ORG, "name": "Spy"}, headers=HB).status_code == 403, "a token never manages labels")

# the tenant boundary
check(st(Ca).get("org_labels") == [], "another organisation's admin gets no label of Alpha")
check(Ca.get(B + "/api/org-labels").json().get("labels") == [], "... nor through the labels' route")
check(Ca.patch(B + f"/api/org-labels/{LB}", json={"name": "Mine"}).status_code == 404, "... and cannot change it (404)")
check(Ca.delete(B + f"/api/list-tags/{LB}?list_id={L1}").status_code == 404, "... nor take it off a project of Alpha (404)")

# the organisation export: the labels (#4031) and the tags of the tasks
out = box(f"""import io, json, zipfile
from kalmido.admin.orgexport import ox_build
b = io.BytesIO()
ox_build(c, {ORG}, b, by={{"id": {ALICE}, "name": "Admin"}})
z = zipfile.ZipFile(b)
print("OXJSON" + json.dumps({{n: json.loads(z.read(n)) for n in ("org/labels.json", "tasks/tags.json", "lists/tags.json") if n in z.namelist()}}, default=str))""")
line = next((x for x in out.splitlines() if x.startswith("OXJSON")), None)
ox = json.loads(line[6:]) if line else {}
lab = ox.get("org/labels.json") or []
check([(x.get("id"), x.get("name"), x.get("color"), x.get("org_id")) for x in lab] == [(LB, "Stammkunde", "#c084fc", ORG)]
      and not any("scope_kind" in x for x in lab), f"the organisation export holds the label {lab}")
tt = sorted((x.get("task_id"), x.get("tag_id")) for x in ox.get("tasks/tags.json") or [])
check(tt == sorted((t, LB) for t in (T1, T2, T3)), f"... and the tasks' tags with the label's id {tt}")

# remove from one project, then delete the label
r = Bo.delete(B + f"/api/list-tags/{LB}?list_id={L3}")
check(r.ok and r.json().get("ids") == [T3], f"taken off the tasks of Events only {r.text[:200]}")
check(ltags_of(Bo, T3) == [] and ltags_of(Bo, T1) == ["Stammkunde"] and tagrows("Stammkunde") == [(LB, "org", str(ORG))],
      "the other projects keep it, the label stays")
r = A.delete(B + f"/api/org-labels/{LB}")
check(r.ok and r.json().get("unlinked") == 2, f"the label deleted (two projects used it) {r.text[:200]}")
rows = tagrows("Stammkunde")
check(sorted((k, sid) for _i, k, sid in rows) == sorted([("list", str(L1)), ("list", str(L2))]),
      f"each project keeps it as its own project tag {rows}")
check(ltags_of(Bo, T1) == ["Stammkunde"] and ltags_of(Bo, T2) == ["Stammkunde"], "and the tasks keep it")

# ================================================================== end-to-end locked project: the name stays plain text
LE = mklist(A, "Vertraulich", ORG)
TE = task(A, LE, "Gehaltsrunde")
check(A.patch(B + f"/api/tasks/{TE}", json={"ltags": ["Geheimprojekt"]}).ok, "setup: a project tag before the lock")
dbx("UPDATE lists SET e2e='on' WHERE id=?", (LE,))
check(dbx("SELECT name FROM obj_tags WHERE scope_kind='list' AND scope_id=?", (str(LE),)) == [("Geheimprojekt",)],
      "a tag of a locked project is stored as plain text (no hash)")
out = box(f"from kalmido.core.objtags import obj_tags_of\nprint('E2E' + repr([x['name'] for x in obj_tags_of(c, [{TE}]).get({TE}, [])]))")
check("E2E['Geheimprojekt']" in out, f"the core reads it back as plain text {out[-200:]}")
dbx("UPDATE lists SET e2e=NULL WHERE id=?", (LE,))

# ================================================================== the move of the old tables (a version before 2.925 ran)
TM = task(A, L1, "Altbestand")
dbx("""CREATE TABLE org_tags (id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, org_id BIGINT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
       name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '', sort DOUBLE PRECISION NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""")
dbx("""CREATE TABLE list_tags (id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, list_id BIGINT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
       name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '', sort DOUBLE PRECISION NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
       org_tag_id BIGINT REFERENCES org_tags(id) ON DELETE SET NULL)""")
dbx("""CREATE TABLE task_list_tags (task_id BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
       tag_id BIGINT NOT NULL REFERENCES list_tags(id) ON DELETE CASCADE, PRIMARY KEY (task_id, tag_id))""")
dbx("INSERT INTO org_tags(id,org_id,name,color,sort,created_at) VALUES(700001,?,'Altkunde','#22c55e',3,'2026-10-01T08:00:00.000+00:00')", (ORG,))
dbx("INSERT INTO list_tags(id,list_id,name,color,sort,created_at) VALUES(900001,?,'Altlast','#3b82f6',7,'2026-10-02T09:00:00.000+00:00')", (L1,))
dbx("""INSERT INTO list_tags(id,list_id,name,color,sort,created_at,org_tag_id)
       VALUES(900002,?,'Altkunde','#22c55e',8,'2026-10-03T10:00:00.000+00:00',700001)""", (L1,))
dbx("INSERT INTO task_list_tags(task_id,tag_id) VALUES(?,900001),(?,900002)", (TM, TM))
SEED = next(i for i, _k, sid in tagrows("Stammkunde") if sid == str(L1))  # a project tag of L1 that exists now: the rule is made with it, then pointed at the copy
r = A.post(B + f"/api/lists/{L1}/rules", json={"name": "Markieren", "trigger": {"kind": "done"}, "action": {"kind": "tag", "tag_id": SEED}})
check(r.ok, f"setup: a rule that adds a tag {r.status_code} {r.text[:200]}")
RID = r.json().get("id")
dbx("UPDATE list_rules SET act_val=? WHERE id=?", (json.dumps({"tag_id": 900002}), RID))
box("pass")  # the next start of the app
for t in ("list_tags", "task_list_tags", "org_tags"):
    check(not table_there(t), f"the start dropped the old table {t} made again")
p = dbx("SELECT scope_kind, scope_id, name, color, sort, created_at FROM obj_tags WHERE id=900001")
check(p and p[0][:5] == ("list", str(L1), "Altlast", "#3b82f6", 7) and str(p[0][5]).startswith("2026-10-02"),
      f"a project tag kept its id, name, colour, order and time {p}")
lab = dbx("SELECT id, color, sort, created_at FROM obj_tags WHERE scope_kind='org' AND scope_id=? AND name='Altkunde'", (str(ORG),))
check(len(lab) == 1 and lab[0][1:3] == ("#22c55e", 3) and str(lab[0][3]).startswith("2026-10-01"), f"the label moved with its colour, order and time {lab}")
NL = lab[0][0] if lab else 0
check(not dbx("SELECT 1 FROM obj_tags WHERE id=900002") and len(tagrows("Altkunde")) == 1, "the label's copy is no tag of its own")
check(sorted(ltags_of(A, TM) or []) == ["Altkunde", "Altlast"], f"the task carries the project tag and the label {ltags_of(A, TM)}")
check(dbx("SELECT 1 FROM obj_tag_links WHERE tag_id=? AND kind='task' AND obj_id=?", (NL, TM)), "the label itself sits on the task")
check(json.loads(dbx("SELECT act_val FROM list_rules WHERE id=?", (RID,))[0][0]).get("tag_id") == NL, "the rule that named the copy names the label")

# ================================================================== review findings (Fable review of #5275, 2.925.0)
def label(name, org=ORG):
    r = A.post(B + "/api/org-labels", json={"org_id": org, "name": name, "color": "#a3e635"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def act_tag(rid):
    return json.loads(dbx("SELECT act_val FROM list_rules WHERE id=?", (rid,))[0][0]).get("tag_id")


def tag_rule(s, lid, tag):
    r = s.post(B + f"/api/lists/{lid}/rules", json={"name": "Markieren", "trigger": {"kind": "done"}, "action": {"kind": "tag", "tag_id": tag}})
    assert r.ok, r.text
    return r.json()["id"]


# F1: a project leaving its organisation on a side way ("Used for" makes it private: ws_private_for) keeps the labels
LP = mklist(A, "Familienkram", ORG)
TP = task(A, LP, "Geschenk kaufen")
F1L = label("Wichtig")
check(A.patch(B + f"/api/tasks/{TP}", json={"ltags": ["Wichtig"]}).ok and ltags_of(A, TP) == ["Wichtig"], "F1 setup: the label on a task")
F1R = tag_rule(A, LP, F1L)
r = A.patch(B + f"/api/lists/{LP}", json={"family": "household"})
check(r.ok and dbx("SELECT org_id FROM lists WHERE id=?", (LP,)) == [(None,)], f"F1: 'Used for' made the project private {r.status_code} {r.text[:200]}")
pt = dbx("SELECT id FROM obj_tags WHERE scope_kind='list' AND scope_id=? AND name='Wichtig'", (str(LP),))
check(ltags_of(A, TP) == ["Wichtig"] and len(pt) == 1, f"F1: the task keeps it as a project tag of the private project {ltags_of(A, TP)} {pt}")
check(pt and act_tag(F1R) == pt[0][0], "F1: the project's rule names its project tag now")
check(tagrows("Wichtig") and any(k == "org" for _i, k, _s in tagrows("Wichtig")), "F1: the label stays in the organisation")
# F1: olb_out / olb_delete count and convert only projects of the label's organisation (a link left on a task elsewhere)
dbx("INSERT INTO obj_tag_links(tag_id, kind, obj_id, src) VALUES(?, 'task', ?, 'person') ON CONFLICT DO NOTHING", (F1L, TP))
check(next((x["lists"] for x in A.get(B + "/api/org-labels").json()["labels"] if x["id"] == F1L), None) == 0,
      "F1: a link left on a task outside the organisation does not count as a project of the label")
r = A.delete(B + f"/api/org-labels/{F1L}")
check(r.ok and r.json().get("unlinked") == 0, f"F1: deleting the label gives that project nothing {r.text[:200]}")
check(len(dbx("SELECT id FROM obj_tags WHERE scope_kind='list' AND scope_id=? AND lower(name)='wichtig'", (str(LP),))) == 1, "F1: still one project tag there")

# F1: the organisation deleted for good -- its projects keep the labels on their tasks as project tags
r = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": ALICE})
check(r.status_code in (200, 201), f"F1 setup: the organisation Gamma {r.text[:200]}")
GAM = r.json().get("id")
LG = mklist(A, "Gamma-Projekt", GAM)
TG = task(A, LG, "Gamma-Aufgabe")
GL = label("Gamma-Label", GAM)
check(A.patch(B + f"/api/tasks/{TG}", json={"ltags": ["Gamma-Label"]}).ok and ltags_of(A, TG) == ["Gamma-Label"], "F1 setup: Gamma's label on the task")
# the route refuses an organisation that still has projects; the account deletion / retention run (odl_dismantle) delete the
# row while projects of it live on (lists.org_id SET NULL) -- the row deleted directly is that step
dbx("DELETE FROM orgs WHERE id=?", (GAM,))
check(not dbx("SELECT 1 FROM orgs WHERE id=?", (GAM,)) and dbx("SELECT org_id FROM lists WHERE id=?", (LG,)) == [(None,)],
      "F1: Gamma deleted, its project lives on without an organisation")
if dbx("SELECT 1 FROM lists WHERE id=?", (LG,)):
    check(dbx("SELECT name FROM obj_tags WHERE scope_kind='list' AND scope_id=?", (str(LG),)) == [("Gamma-Label",)]
          and dbx("SELECT 1 FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id WHERE k.obj_id=? AND ot.scope_kind='list'", (TG,)),
          "F1: the surviving project keeps the label as its project tag on the task")
else:
    print("note: deleting Gamma removed its project too (nothing to keep)", flush=True)

# F6: a project joining the organisation turns its project tag named like a label into that label
F6L = label("Kundin")
LJ = mklist(A, "Zuwachs")
dbx("UPDATE lists SET org_id=NULL WHERE id=?", (LJ,))  # private (the default workspace may have been Alpha)
TJ = task(A, LJ, "Rechnung")
check(A.patch(B + f"/api/tasks/{TJ}", json={"ltags": ["kundin"]}).ok, "F6 setup: a project tag of the private project")
OLDJ = dbx("SELECT id FROM obj_tags WHERE scope_kind='list' AND scope_id=?", (str(LJ),))[0][0]
F6R = tag_rule(A, LJ, OLDJ)
r = A.patch(B + f"/api/lists/{LJ}", json={"org_id": ORG})
check(r.ok, f"F6: the project joins Alpha {r.status_code} {r.text[:200]}")
check(not dbx("SELECT 1 FROM obj_tags WHERE id=?", (OLDJ,)) and dbx("SELECT 1 FROM obj_tag_links WHERE tag_id=? AND obj_id=?", (F6L, TJ)),
      "F6: its project tag became the label (the task carries the label, the project tag is gone)")
check(act_tag(F6R) == F6L, "F6: the rule names the label")

# F4 / F6: a guest of the organisation (row-level security lets her read the labels' rows) gets no label she does not see
r = A.post(B + "/api/users", json={"username": "gina", "display_name": "Gina", "password": kt.PASSWORD, "email": "gina@example.com",
                                   "orgs": [{"id": ORG, "role": "guest"}]})
check(r.ok, f"setup: gina, a guest of Alpha {r.text[:200]}")
GINA = r.json().get("id")
Gi = kt.sess("gina")
Gi.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
LQ = mklist(A, "Geteilt", ORG)
A.put(B + f"/api/lists/{LQ}/members", json={"user_id": GINA, "role": "admin"})
A.put(B + f"/api/lists/{LQ}/members", json={"user_id": BOB, "role": "edit"})
SEC = label("Vertraulich-Label")
r = Gi.patch(B + f"/api/list-tags/{SEC}", json={})
check(r.status_code == 404 and "Vertraulich" not in r.text, f"F4: an empty PATCH gives the guest no label {r.status_code} {r.text[:200]}")
check(A.patch(B + f"/api/list-tags/{SEC}", json={}).ok, "F4: the admin (full view) still gets the answer")
QR = tag_rule(A, LQ, SEC)
r = Gi.get(B + f"/api/lists/{LQ}/rules")
if r.ok:
    rr = next((x for x in r.json()["rules"] if x["id"] == QR), {})
    check(rr and rr["names"].get("tag_to") is None, f"F4: the rule shows the guest no name of a label she does not see {rr.get('names')}")
    r = Gi.post(B + f"/api/lists/{LQ}/rules", json={"name": "x", "trigger": {"kind": "done"}, "action": {"kind": "tag", "tag_id": SEC}})
    check(r.status_code == 400, f"F4: the guest cannot probe a label's id through a rule {r.status_code}")
else:
    check(False, f"F4 setup: the guest (project admin) reads the rules {r.status_code} {r.text[:200]}")
r = Gi.get(B + f"/api/lists/{LQ}/public-link")
if r.ok:
    check(not any(x["id"] == SEC for x in r.json()["options"]["tags"]), "F4: the share dialog offers the guest no unseen label")
TQ = task(A, LQ, "Gastaufgabe")
check(Gi.patch(B + f"/api/tasks/{TQ}", json={"ltags": ["Vertraulich-Label"]}).ok, "F6 setup: the guest's tag by the label's name")
check(not dbx("SELECT 1 FROM obj_tag_links WHERE tag_id=?", (SEC,)), "F6: the guest's tag is a plain project tag (no oracle)")
TQ2 = task(A, LQ, "Mitgliedsaufgabe")
check(Bo.patch(B + f"/api/tasks/{TQ2}", json={"ltags": ["Vertraulich-Label"]}).ok
      and dbx("SELECT 1 FROM obj_tag_links WHERE tag_id=? AND obj_id=?", (SEC, TQ2)),
      "F6: a member with the full view gets the label, not the guest's project tag of that name")

# F7: a label's order is the organisation's: no silent success for a sort through the project's route
check(A.patch(B + f"/api/list-tags/{SEC}?list_id={LQ}", json={"sort": 99}).status_code == 409, "F7: sort of a label through a project: 409")

# F7: the hook's tags find a label of the organisation by name
r = A.post(B + f"/api/lists/{L1}/hooks-in", json={"name": "n8n"})
check(r.status_code == 201 and r.json().get("token"), f"F7 setup: an inbound webhook of Support {r.status_code} {r.text[:200]}")
r = kt.sess(None).post(B + "/api/hooks/in/" + (r.json().get("token") or "x"), json={"title": "Vom Webhook", "tags": "Altkunde"})
check(r.status_code == 201 and ltags_of(A, r.json().get("id")) == ["Altkunde"], f"F7: a webhook puts the organisation's label on its task {r.status_code} {r.text[:200]}")

# F2 / F3 / the old times: a second move (a version before 2.925 ran again)
TZ = task(A, L3, "Zusammen-Aufgabe")
check(A.patch(B + f"/api/tasks/{TZ}", json={"ltags": ["Zusammen"]}).ok, "setup: a project tag Zusammen in Events (made before the label moves, and before K: it takes an id)")
seq = dbx("SELECT pg_get_serial_sequence('obj_tags', 'id')")[0][0]
K = max(dbx("SELECT COALESCE(MAX(id), 0) FROM obj_tags")[0][0], dbx(f"SELECT last_value FROM {seq}")[0][0])
OTHER = next(i for i, _k, sid in tagrows("Stammkunde") if sid == str(L2))  # a valid project tag of Sales
R2 = tag_rule(A, L2, OTHER)
TS1 = task(A, L1, "Altzeit")
dbx("""CREATE TABLE org_tags (id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, org_id BIGINT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
       name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '', sort DOUBLE PRECISION NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""")
dbx("""CREATE TABLE list_tags (id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, list_id BIGINT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
       name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '', sort DOUBLE PRECISION NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
       org_tag_id BIGINT REFERENCES org_tags(id) ON DELETE SET NULL)""")
dbx("""CREATE TABLE task_list_tags (task_id BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
       tag_id BIGINT NOT NULL REFERENCES list_tags(id) ON DELETE CASCADE, PRIMARY KEY (task_id, tag_id))""")
dbx("INSERT INTO org_tags(id,org_id,name,color,sort,created_at) VALUES(700011,?,'Neulabel','',1,'2026-10-05T08:00:00.000+00:00')", (ORG,))
dbx("INSERT INTO org_tags(id,org_id,name,color,sort,created_at) VALUES(700012,?,'Zusammen','',2,'2026-10-05T08:00:00.000+00:00')", (ORG,))
dbx("INSERT INTO list_tags(id,list_id,name,color,sort,created_at) VALUES(?,?,'Kleine Id','',1,'2026-09-01 07:30:00')", (K + 1, L1))
dbx("INSERT INTO list_tags(id,list_id,name,color,sort,created_at) VALUES(?,?,'Fremde Id','',2,'2026-10-06T08:00:00.000+00:00')", (OTHER, L1))
dbx("INSERT INTO list_tags(id,list_id,name,color,sort,created_at,org_tag_id) VALUES(900021,?,'Neulabel','',3,'2026-10-06T08:00:00.000+00:00',700011)", (L2,))
dbx("INSERT INTO task_list_tags(task_id,tag_id) VALUES(?,?),(?,900021)", (TS1, K + 1, TS1))  # 900021 is a copy in Sales: TS1 is in Support
box("pass")
p = dbx("SELECT name, created_at FROM obj_tags WHERE id=?", (K + 1,))
check(p and p[0][0] == "Kleine Id", f"F2: the project tag with the next free id keeps it (the labels were made after the identity moved on) {p}")
check(p and str(p[0][1]).startswith("2026-09-01"), f"the old SQLite time 'YYYY-MM-DD HH:MM:SS' is kept {p}")
check(act_tag(R2) == OTHER, f"F3: a rule of Sales naming its own tag {OTHER} is not rewritten by the move of Support's old row with that id")
NEU = dbx("SELECT id FROM obj_tags WHERE scope_kind='org' AND name='Neulabel'")
check(NEU and not dbx("SELECT 1 FROM obj_tag_links WHERE tag_id=? AND obj_id=?", (NEU[0][0], TS1)),
      "an old link to a copy of another project (the task moved on) does not turn into the label on the task")
ZL = dbx("SELECT id FROM obj_tags WHERE scope_kind='org' AND name='Zusammen'")
check(ZL and len(tagrows("Zusammen")) == 1 and ltags_of(A, TZ) == ["Zusammen"] and dbx("SELECT 1 FROM obj_tag_links WHERE tag_id=? AND obj_id=?", (ZL[0][0], TZ)),
      f"F6: the moved label took over the project tag of its name {tagrows('Zusammen')}")

# F5: the account import's check of earlier imports reads a remembered tag id that may be no project tag (a ws scope: 'o:3')
out = box("""from kalmido.admin.acctimport import UMZ_SRC
t, col, _p = UMZ_SRC["list_tags"]
i = c.execute("INSERT INTO obj_tags(scope_kind,scope_id,name,created_at) VALUES('ws','o:3','Ws-Tag',CURRENT_TIMESTAMP) RETURNING id").fetchone()[0]
print("UMZ" + repr([tuple(r) for r in c.execute(f"SELECT id, {col} AS up FROM {t} WHERE id IN (?)", (i,)).fetchall()]))
c.execute("DELETE FROM obj_tags WHERE id=?", (i,))
print("UMZKEYS" + ",".join(sorted(UMZ_SRC)))""")
check("UMZ[(" in out and ", None)]" in out, f"F5: a tag of another scope reads as no project (no cast error) {out[-300:]}")
keys = set(next((x[7:] for x in out.splitlines() if x.startswith("UMZKEYS")), "").split(","))
check({"lists", "sections", "list_fields", "list_tags", "list_status", "list_links", "list_milestones", "tasks", "list_rules",
       "portal_tickets", "template_files"} <= keys, f"review N2: every kind of the earlier-import check is there {sorted(keys)}")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Eigenes"}).json()["id"]
FT = task(Fr, FL, "Angebot schreiben")
r = Fr.patch(B + f"/api/tasks/{FT}", json={"ltags": ["Eilig"]})
check(r.ok and ltags_of(Fr, FT) == ["Eilig"], f"freelancer: a project tag on her task {r.status_code} {r.text[:200]}")
FTG = next((x["id"] for x in list_tags(Fr, FL) if x["name"] == "Eilig"), None)
check(FTG and dbx("SELECT org_id FROM obj_tags WHERE id=?", (FTG,)) == [(None,)], "freelancer: her project's tag, no organisation")
check(Fr.get(B + "/api/org-labels").json().get("labels") == [] and st(Fr).get("org_labels") == [], "freelancer: no labels")
check(Fr.delete(B + f"/api/list-tags/{FTG}").ok and ltags_of(Fr, FT) == [], "freelancer: she deletes it")

sys.exit(kt.done("p2925_c_tags_core"))
