#!/usr/bin/env python3
# kalmido-suite:
"""2.363.3 B API tests (#3134): duplicating and templates take everything except comments and times, the list CSV, the budget's
hint on shortened purposes, taking "Recognise again" back. Invented names only.
 - duplicate a task (POST /api/tasks/{id}/duplicate): subtasks, assignee, tags of others, fields, sprint, dependency, files as
   real copies (the original gone, the copy still opens); no comments, no times; a stranger 404, a participant keeps the copy
 - duplicate a list: WIP, sprints, list tags, key links, person + task fields; people only where they may see the copy
 - templates: the ids and the tags of others never reach the client; files stay after the original is gone; on use people only
   when they see the target; template_update is a partial update, a node that goes takes its files with it
 - CSV: the new columns, the formula guard, the import takes such a file back
 - budget: a purpose over 200 characters is marked, a shorter one not
 - docs: redo/undo brings the values back, a value set by hand stays, too late = 400, a stranger 404
 - a person without an organisation does the same
usage: p2363_3_b_api_test.py <datadir>"""
import csv
import io
import os
import sys

import dbx as dbxm
from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, sess, setup, until

DATA = sys.argv[1]
fresh()
A = setup()
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments", "fields"]})
FEAT = "comments,fields,collab,time,docs,files,budget,home"
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {"alice": 1}
for u, orgs in (("bob", [ORG]), ("pete", [ORG]), ("carol", [])):
    r = A.post(B + "/api/users", json={"orgs": orgs, "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Pe, Ca = sess("bob"), sess("pete"), sess("carol")
for s in (A, Bo, Pe, Ca):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT}).ok


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    c.execute(sql, args)
    c.commit()
    c.close()


def mk(s, **kw):
    r = s.post(B + "/api/tasks", json=kw)
    assert r.ok, (kw, r.text)
    return r.json()["id"]


def attach(s, tid, name, data):
    assert s.post(B + f"/api/tasks/{tid}/attachments", files={"file": (name, data, "text/plain")}).ok


def atts(tid):
    return dbx("SELECT id, name, path, comment_id FROM attachments WHERE task_id=? AND deleted_at IS NULL ORDER BY id", (tid,))


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


L = A.post(B + "/api/lists", json={"name": "Harbour", "kind": "project"}).json()["id"]
for u, ro in (("bob", "edit"), ("pete", "participant")):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": uid[u], "role": ro}).ok
SEC = A.post(B + "/api/sections", json={"list_id": L, "name": "Build"}).json()["id"]
assert A.patch(B + f"/api/sections/{SEC}", json={"wip_limit": 4}).ok
assert A.post(B + f"/api/lists/{L}/tags", json={"name": "bug", "color": "#ff0000"}).ok
FP = A.post(B + f"/api/lists/{L}/fields", json={"name": "Owner", "type": "person"}).json()["id"]
FT = A.post(B + f"/api/lists/{L}/fields", json={"name": "See", "type": "task"}).json()["id"]
assert A.post(B + f"/api/lists/{L}/links", json={"title": "Plan", "url": "https://example.com/plan"}).ok
S1 = A.put(B + f"/api/lists/{L}/sprint-settings", json={"on": True}).json().get("started_id")
check(bool(S1), "setup: a sprint")
T = mk(A, title="Lay deck", list_id=L, section_id=SEC, assignee_id=uid["bob"], tags=["mine"], ltags=["bug"], due="2031-05-04")
SUB = mk(A, title="Measure", parent_id=T, assignee_id=uid["bob"])
BL = mk(A, title="Order wood", list_id=L, section_id=SEC)
assert Bo.patch(B + f"/api/tasks/{T}", json={"tags": ["bobs-own-tag"]}).ok
assert A.patch(B + f"/api/tasks/{T}", json={"fields": {str(FP): str(uid["bob"]), str(FT): str(BL)}}).ok
assert A.post(B + f"/api/lists/{L}/sprints/assign", json={"ids": [T], "sprint_id": S1}).ok
dbw("INSERT INTO task_deps(task_id,blocker_id,created_at) VALUES(?,?,'2030-01-01T00:00:00Z') ON CONFLICT DO NOTHING", (T, BL))
attach(A, T, "plan.txt", b"the plan\n")
attach(A, SUB, "sub.txt", b"sub file\n")
C = A.post(B + f"/api/tasks/{T}/comments", json={"body": "a remark"}).json()["id"]
dbw("INSERT INTO attachments(task_id,name,path,created_at,comment_id) VALUES(?,'of-the-comment.txt','nowhere','2030-01-01T00:00:00Z',?)", (T, C))
dbw('INSERT INTO time_entries(user_id,task_id,list_id,start,"end",seconds,created_at,updated_at) VALUES(1,?,?,\'2030-01-01T08:00:00Z\',\'2030-01-01T09:00:00Z\',3600,\'2030-01-01T09:00:00Z\',\'2030-01-01T09:00:00Z\')', (T, L))

# ================================================================ a task
r = A.post(B + f"/api/tasks/{T}/duplicate")
check(r.ok and r.json()["task"]["id"] != T and r.json()["skipped_files"] == [], "duplicate a task " + r.text[:200])
D = r.json()["task"]
check(D["assignee_id"] == uid["bob"] and D["title"] == "Lay deck" and D["section_id"] == SEC and D["status"] == 0, "the copy: assignee, section, open")
check(D.get("sprint_id") == S1, "the copy: the sprint")
check([x[1] for x in atts(D["id"])] == ["plan.txt"] and atts(D["id"])[0][2] != atts(T)[0][2], "the copy: its own stored file")
check(one("SELECT COUNT(*) FROM task_tags WHERE task_id=? AND user_id=? AND tag='bobs-own-tag'", (D["id"], uid["bob"])) == 1, "the copy: the tag of another person, for that person")
check(one("SELECT COUNT(*) FROM task_list_tags WHERE task_id=?", (D["id"],)) == 1, "the copy: the list tag")
check(one("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (D["id"], FP)) == str(uid["bob"]), "the copy: the person field")
check(one("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (D["id"], FT)) == str(BL), "the copy: the task field")
check(one("SELECT COUNT(*) FROM task_deps WHERE task_id=? AND blocker_id=?", (D["id"], BL)) == 1, "the copy: waits on the same task")
check(one("SELECT COUNT(*) FROM comments WHERE task_id=?", (D["id"],)) == 0, "no comments")
check(one("SELECT COUNT(*) FROM time_entries WHERE task_id=?", (D["id"],)) == 0, "no times")
DS = dbx("SELECT id, title, assignee_id FROM tasks WHERE parent_id=?", (D["id"],))
check(len(DS) == 1 and DS[0][1] == "Measure" and DS[0][2] == uid["bob"] and [x[1] for x in atts(DS[0][0])] == ["sub.txt"], "the copy: the subtask with assignee + file")
check(Ca.post(B + f"/api/tasks/{T}/duplicate").status_code == 404, "tenant: a stranger gets 404")
PT = mk(A, title="For pete", list_id=L, assignee_id=uid["pete"])
r = Pe.post(B + f"/api/tasks/{PT}/duplicate")
check(r.ok and r.json()["task"]["assignee_id"] == uid["pete"], "a participant: the copy stays theirs " + r.text[:160])
check(Pe.post(B + f"/api/tasks/{T}/duplicate").status_code in (403, 404), "a participant: not somebody else's task")

# ================================================================ the original's file goes, the copy stays
DAT = atts(D["id"])[0][0]
assert A.delete(B + f"/api/attachments/{atts(T)[0][0]}").ok
check(A.get(B + f"/api/attachments/{DAT}").content == b"the plan\n", "the original's file deleted: the copy still opens")
attach(A, T, "plan.txt", b"the plan\n")

# ================================================================ a list
r = A.post(B + f"/api/lists/{L}/duplicate", json={"name": "Harbour two"})
check(r.ok, "duplicate the list " + r.text[:200])
N = r.json()["list_id"]
check(one("SELECT wip_limit FROM sections WHERE list_id=? AND name='Build'", (N,)) == 4, "the copy: WIP")
check(one("SELECT COUNT(*) FROM sprints WHERE list_id=?", (N,)) == 1, "the copy: the sprint")
check(one("SELECT COUNT(*) FROM list_links WHERE list_id=?", (N,)) == 1, "the copy: the key link")
check(one("SELECT COUNT(*) FROM list_tags WHERE list_id=?", (N,)) == 1, "the copy: the list tag")
check(one("SELECT COUNT(*) FROM list_members WHERE list_id=?", (N,)) == 0, "the copy: no members")
NT = dbx("SELECT id, assignee_id, sprint_id FROM tasks WHERE list_id=? AND title='Lay deck' AND parent_id IS NULL ORDER BY id", (N,))
check(len(NT) == 2 and all(x[1] is None for x in NT), "tenant: bob cannot see the copy: not assigned there " + str(NT))
check(all(x[2] for x in NT), "the copy: the tasks in the new sprint")
check(dbx("SELECT 1 FROM task_tags WHERE task_id=? AND user_id=?", (NT[0][0], uid["bob"])) == [], "tenant: no tag for somebody outside the copy")
check(one("SELECT COUNT(*) FROM task_field_values v JOIN list_fields f ON f.id=v.field_id WHERE v.task_id=? AND f.type='person'", (NT[0][0],)) == 0,
      "tenant: no person field for somebody outside the copy")
tv = dbx("SELECT v.value FROM task_field_values v JOIN list_fields f ON f.id=v.field_id WHERE v.task_id=? AND f.type='task'", (NT[0][0],))
nbl = one("SELECT id FROM tasks WHERE list_id=? AND title='Order wood'", (N,))
check(tv and tv[0][0] == str(nbl), "the copy: the task field points at the copy of the task")
check(len(atts(NT[0][0])) == 1, "the copy: the file")
check(Ca.post(B + f"/api/lists/{L}/duplicate", json={}).status_code == 404, "tenant: a stranger gets 404")

# ================================================================ templates
r = A.post(B + "/api/templates", json={"list_id": L, "name": "Harbour tpl"})
check(r.ok and r.json()["skipped_files"] == [], "a list template " + r.text[:200])
TP = r.json()["id"]
txt = A.get(B + "/api/templates").text
check("bobs-own-tag" not in txt and '"xt"' not in txt and '"extra"' not in txt, "the tags of others never reach the client")
paths = dbx("SELECT path FROM template_files WHERE template_id=? ORDER BY id", (TP,))
check(len(paths) >= 2 and all(p[0].startswith("tplfiles/") for p in paths), "the template has its own copies " + str(paths))
check(all(os.path.isfile(os.path.join(DATA, "attachments", p[0])) for p in paths) or not os.path.isdir(os.path.join(DATA, "attachments")), "the files are on the disk")
r = A.delete(B + f"/api/tasks/{T}")
check(r.ok, "the original task goes")
r = A.post(B + f"/api/templates/{TP}/apply", json={"name": "From tpl"})
check(r.ok, "use the template " + r.text[:200])
LT = r.json()["list_id"]
fid = dbx("SELECT a.id FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=? AND a.name='plan.txt'", (LT,))
check(fid and A.get(B + f"/api/attachments/{fid[0][0]}").content == b"the plan\n", "the original gone: the file comes from the template")
check(one("SELECT wip_limit FROM sections WHERE list_id=? AND name='Build'", (LT,)) == 4 and one("SELECT COUNT(*) FROM sprints WHERE list_id=?", (LT,)) == 1,
      "the template: WIP and sprint")
check(one("SELECT state FROM sprints WHERE list_id=?", (LT,)) == "planned", "the template: a sprint is planned again")

T2 = mk(A, title="Second", list_id=L, assignee_id=uid["bob"], tags=["mine"])
assert Bo.patch(B + f"/api/tasks/{T2}", json={"tags": ["bobs-tag-2"]}).ok
attach(A, T2, "two.txt", b"two\n")
r = A.post(B + "/api/templates", json={"task_id": T2, "name": "One task"})
check(r.ok and "bobs-tag-2" not in r.text, "a task template " + r.text[:200])
TT, tdata = r.json()["id"], r.json()["data"]
r = A.post(B + f"/api/templates/{TT}/apply", json={"list_id": L})
check(r.ok and r.json()["task"]["assignee_id"] == uid["bob"], "into a list bob sees: assigned " + r.text[:200])
NEW = r.json()["task"]["id"]
check(one("SELECT COUNT(*) FROM task_tags WHERE task_id=? AND user_id=?", (NEW, uid["bob"])) == 1 and [x[1] for x in atts(NEW)] == ["two.txt"], "into a list bob sees: his tag + the file")
own = A.post(B + "/api/lists", json={"name": "Mine only"}).json()["id"]
r = A.post(B + f"/api/templates/{TT}/apply", json={"list_id": own})
check(r.ok and r.json()["task"]["assignee_id"] is None, "tenant: into a list bob does not see: nobody assigned")
check(one("SELECT COUNT(*) FROM task_tags WHERE task_id=? AND user_id=?", (r.json()["task"]["id"], uid["bob"])) == 0, "tenant: and no tag of his")

# template_update: a partial update
r = A.patch(B + f"/api/templates/{TP}", json={"data": {"name": "Renamed project"}})
d = r.json()["data"]
check(r.ok and d["name"] == "Renamed project" and len(d["tasks"]) >= 2 and d["sections"] == ["Build"], "only the name in data: the rest stays " + r.text[:200])
n0 = d["tasks"][0]
r = A.patch(B + f"/api/templates/{TP}", json={"data": {"tasks": [{"k": n0["k"], "title": "New title"}]}})
d = r.json()["data"]
check(r.ok and d["tasks"][0]["title"] == "New title" and d["tasks"][0].get("due_offset") == n0.get("due_offset") and d["tasks"][0]["children"] == n0["children"],
      "a node with its key: the fields not named stay " + r.text[:200])
left = {x[0] for x in dbx("SELECT node_key FROM template_files WHERE template_id=?", (TP,))}
keys = {n0["k"]} | {k["k"] for k in n0["children"]}
check(left <= keys, f"a node that went took its files {left} {keys}")
r = A.patch(B + f"/api/templates/{TT}", json={"data": {"task": {"title": "Second renamed"}}})
check(r.ok and r.json()["data"]["task"]["title"] == "Second renamed" and r.json()["data"]["task"]["tags"] == ["mine"], "a task template: the root keeps its fields")
r = A.post(B + f"/api/templates/{TT}/apply", json={"list_id": L})
check(r.ok and r.json()["task"]["assignee_id"] == uid["bob"] and len(atts(r.json()["task"]["id"])) == 1, "after the edit: assignee and file are still there")
dpaths = [x[0] for x in dbx("SELECT path FROM template_files WHERE template_id=?", (TT,))]
assert A.delete(B + f"/api/templates/{TT}").ok
check(dbx("SELECT 1 FROM template_files WHERE template_id=?", (TT,)) == [], "template deleted: its rows go")
check(not any(os.path.exists(os.path.join(DATA, "attachments", p)) for p in dpaths), "template deleted: its files go")
check(Ca.get(B + "/api/templates").json()["templates"] == [], "tenant: a stranger sees no template")

# freelancer-matrix: lists, tasks, files, personal
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Solo"}).json()["id"]
FT1 = mk(Fr, title="Solo task", list_id=FL, assignee_id=FID)
attach(Fr, FT1, "solo.txt", b"solo\n")
r = Fr.post(B + f"/api/tasks/{FT1}/duplicate")
check(r.ok and len(atts(r.json()["task"]["id"])) == 1, "freelancer: duplicate a task with its file " + r.text[:200])
r = Fr.post(B + f"/api/lists/{FL}/duplicate", json={})
check(r.ok, "freelancer: duplicate the list " + r.text[:200])
ft = dbx("SELECT id, assignee_id FROM tasks WHERE list_id=? ORDER BY id", (r.json()["list_id"],))
check(len(ft) == 2 and all(len(atts(x[0])) == 1 for x in ft), "freelancer: the copy with the files " + str(ft))
r = Fr.post(B + "/api/templates", json={"list_id": FL, "name": "Solo tpl"})
check(r.ok and Fr.post(B + f"/api/templates/{r.json()['id']}/apply", json={}).ok, "freelancer: a template with files, used")

# ================================================================ the CSV
CL = A.post(B + "/api/lists", json={"name": "Csv"}).json()["id"]
C1 = mk(A, title="First", list_id=CL)
C2 = mk(A, title="=Second", list_id=CL, due="2031-02-03", repeat="FREQ=DAILY", reminders="15")
dbw("INSERT INTO task_deps(task_id,blocker_id,created_at) VALUES(?,?,'2030-01-01T00:00:00Z')", (C2, C1))
A.post(B + f"/api/tasks/{C2}/comments", json={"body": "one"})
A.post(B + f"/api/tasks/{C2}/comments", json={"body": "two"})
attach(A, C2, "f.txt", b"x\n")
txt = A.get(B + f"/api/lists/{CL}/export.csv").content.decode("utf-8-sig")
rows = list(csv.reader(io.StringIO(txt)))
h = rows[0]
check(h[-5:] == ["Repeat", "Reminders", "Dependencies", "Comments", "Attachments"], "the new columns at the end " + str(h[-6:]))
r2 = next(dict(zip(h, x)) for x in rows[1:] if x[0] == "'=Second")
r1 = next(dict(zip(h, x)) for x in rows[1:] if x[0] == "First")
check(r2["Repeat"] and r2["Reminders"] == "15" and r2["Dependencies"] == "First" and r2["Attachments"] == "1", "the values " + str(r2))
check(r2["Comments"] == "2", "the number of comments " + str(r2["Comments"]))
check(r1["Comments"] == "" and r1["Attachments"] == "" and r1["Repeat"] == "", "none: empty cells")
HID = mk(Ca, title="=Hidden blocker", list_id=Ca.get(B + "/api/state").json()["lists"][0]["id"])
dbw("INSERT INTO task_deps(task_id,blocker_id,created_at) VALUES(?,?,'2030-01-01T00:00:00Z')", (C1, HID))
txt = A.get(B + f"/api/lists/{CL}/export.csv").content.decode("utf-8-sig")
check("Hidden blocker" not in txt, "tenant: a blocker the person cannot see stays out")
r = A.post(B + "/api/import/csv", files={"file": ("back.csv", txt.encode("utf-8-sig"))}, data={"dry_run": "1"})
check(r.status_code == 200 and r.json()["created"]["tasks"] == 2, "the import takes such a file back " + r.text[:200])

# ================================================================ the budget
BL_ = Fr.post(B + "/api/budget/lists", json={}).json()["list_id"]
LONG = "x" * 201
TXT = f"Buchungstag;Betrag;Verwendungszweck\n01.03.2031;-5,00;{LONG}\n02.03.2031;-6,00;short text\n"
g = Fr.post(B + f"/api/budget/{BL_}/import/parse", json={"text": TXT}).json()["guess"]
rows = Fr.post(B + f"/api/budget/{BL_}/import/parse", json={"text": TXT, "mapping": g}).json()["rows"]
check(rows[0].get("cut") is True and len(rows[0]["title"]) == 200, "a long purpose is marked " + str(rows[0])[:120])
check(not rows[1].get("cut"), "a short one is not")


# ================================================================ Recognise again -> Undo
def doc(s, ws, name):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, b"Rechnung 12.03.2031\nGesamt 123,45 EUR\n", "text/plain"))])
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json()["state"] == "done", 90)
    return nid


def run_docs(s, ws, who):
    nid = doc(s, ws, f"r-{who}.txt")
    dbw("UPDATE doc_meta SET method='marker' WHERE node_id=?", (nid,))
    r = s.post(B + f"/api/docs/{nid}/redo")
    check(r.ok, who + ": redo " + r.text[:160])
    until(lambda: one("SELECT state FROM doc_meta WHERE node_id=?", (nid,)) == "done", 90)
    check(one("SELECT method FROM doc_meta WHERE node_id=?", (nid,)) != "marker", who + ": the run replaced the value")
    check(s.patch(B + f"/api/docs/{nid}", json={"amount": "77.70"}).ok, who + ": set by hand after the run")
    r = s.post(B + f"/api/docs/{nid}/redo/undo")
    check(r.ok and r.json()["state"] == "done", who + ": undo " + r.text[:160])
    check(one("SELECT method FROM doc_meta WHERE node_id=?", (nid,)) == "marker", who + ": the value from before is back")
    check(s.get(B + f"/api/docs/{nid}").json()["amount"] in ("77.70", 77.7), who + ": the value set by hand stays")
    check(one("SELECT redo_prev FROM doc_meta WHERE node_id=?", (nid,)) == "", who + ": the copy is gone")
    check(s.post(B + f"/api/docs/{nid}/redo/undo").status_code == 400, who + ": a second undo: 400")
    s.post(B + f"/api/docs/{nid}/redo")
    until(lambda: one("SELECT state FROM doc_meta WHERE node_id=?", (nid,)) == "done", 90)
    dbw("UPDATE doc_meta SET redo_at='2020-01-01T00:00:00Z' WHERE node_id=?", (nid,))
    check(s.post(B + f"/api/docs/{nid}/redo/undo").status_code == 400, who + ": after 24 h: 400")
    # 2.363.3 (#3134, review): a kept number given away meanwhile stays with the other document; a copy no key opens = 400, nothing written back
    other = doc(s, ws, f"r2-{who}.txt")
    dbw("UPDATE doc_meta SET asn=4711 WHERE node_id=?", (nid,))
    s.post(B + f"/api/docs/{nid}/redo")
    until(lambda: one("SELECT state FROM doc_meta WHERE node_id=?", (nid,)) == "done", 90)
    dbw("UPDATE doc_meta SET asn=NULL WHERE node_id=?", (nid,))
    dbw("UPDATE doc_meta SET asn=4711 WHERE node_id=?", (other,))
    r = s.post(B + f"/api/docs/{nid}/redo/undo")
    check(r.ok and one("SELECT asn FROM doc_meta WHERE node_id=?", (nid,)) is None, who + ": the number stays with the other document " + r.text[:160])
    dbw("UPDATE doc_meta SET asn=NULL WHERE node_id=?", (other,))
    s.post(B + f"/api/docs/{nid}/redo")
    until(lambda: one("SELECT state FROM doc_meta WHERE node_id=?", (nid,)) == "done", 90)
    dbw("""UPDATE doc_meta SET redo_prev=jsonb_set(redo_prev::jsonb, '{text}', '"kenc1:gone"')::text WHERE node_id=?""", (nid,))
    check(s.post(B + f"/api/docs/{nid}/redo/undo").status_code == 400, who + ": a key that is gone: 400")
    return nid


NID = run_docs(Fr, "private", "freelancer")
check(Ca.post(B + f"/api/docs/{NID}/redo/undo").status_code == 404, "tenant: a stranger gets 404")
run_docs(A, f"org:{ORG}", "org")

sys.exit(done("p2363_3_b"))
