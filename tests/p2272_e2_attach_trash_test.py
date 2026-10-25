#!/usr/bin/env python3
"""2.272.0 E2 (#3038) API tests (fresh DB): what was deleted for good at once now lies in a trash with a period.
 - task files: deleting one keeps row and file (deleted_at), the task lists it under attachments_trash, the download is 404,
   restore brings it back; the trash run counts only while the switch is off and removes row and file with
   KALMIDO_RETENTION_PURGE=1 (a fresh one stays)
 - project files: the same through the overview (files_trash, restore)
 - office: a deleted quotation draft and a deleted service lie in the office trash (GET /api/office/trash), restore brings
   them back with their positions; the run deletes old copies with the switch on
 - sections: a task in the trash remembers its deleted section; restoring it makes the section anew with that name
 - list_purge: fields with values, tags in use and section names go into the inbox
 - removing a member: ?dry=1 names the assignments and person values that go, nothing changes
 - checklist "clear done": only my own done items unless others=true (owner / admin)
The case without an organisation (freelancer fixture) runs the same steps (files, office, sections).
freelancer-matrix: lists, tasks, office"""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from freelancer_fixture import FEATURES, freelancer
from kt import B, CT, DATA, check, dbx, done, sess

OLD = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
ATT = os.path.join(DATA, "attachments")


def sql(q, a=()):
    import dbx as dbxm
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute(q, a)
        c.commit()
    finally:
        c.close()


def one(q, a=()):
    r = dbx(q, a)
    return r[0][0] if r else None


def in_app(code, env=()):
    cmd = ["docker", "exec"] + [x for k in env for x in ("-e", k)] + [CT, "python", "-c",
                                                                        "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.close()"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    return out.stdout + out.stderr


def tick(on):
    out = in_app("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))", env=("KALMIDO_RETENTION_PURGE=1",) if on else ())
    check("counts" in out and "Traceback" not in out, "trash run ran " + out[-800:])
    return out


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
A_ID = A.get(B + "/api/state").json()["me"]["id"]
BOB, Bo = freelancer(B, A, "bob")
FRIDA, Fr = freelancer(B, A, "frida")


def files_case(s, who):
    """Task file + project file in the trash, restore, the run (alice and frida)."""
    lid = s.post(B + "/api/lists", json={"name": f"Film {who}", "kind": "project"}).json()["id"]
    tid = s.post(B + "/api/tasks", json={"title": "Cut", "list_id": lid}).json()["id"]
    r = s.post(B + f"/api/tasks/{tid}/attachments", files={"file": ("notes.txt", b"take 3 is the one\n" * 20, "text/plain")})
    check(r.ok, f"{who}: setup file on the task {r.text[:120]}")
    aid, path = dbx("SELECT id, path FROM attachments WHERE task_id=?", (tid,))[0]
    r = s.delete(B + f"/api/attachments/{aid}")
    j = r.json() if r.ok else {}
    check(r.ok and not j.get("attachments") and [x["id"] for x in j.get("attachments_trash") or []] == [aid],
          f"{who}: delete -> the task lists it in its trash {r.text[:200]}")
    check(one("SELECT deleted_at FROM attachments WHERE id=?", (aid,)) and os.path.isfile(os.path.join(ATT, path)), f"{who}: row and file stay")
    check(s.get(B + f"/api/attachments/{aid}").status_code == 404, f"{who}: a file in the trash is not handed out")
    r = s.post(B + f"/api/attachments/{aid}/restore")
    check(r.ok and [x["id"] for x in r.json().get("attachments") or []] == [aid] and not r.json().get("attachments_trash"),
          f"{who}: restore brings it back {r.text[:200]}")
    check(s.get(B + f"/api/attachments/{aid}").ok, f"{who}: downloadable again")
    check(s.post(B + f"/api/attachments/{aid}/restore").status_code == 404, f"{who}: restoring a live file: 404")
    # the project file
    r = s.post(B + f"/api/lists/{lid}/files", files={"file": ("brief.txt", b"the brief\n" * 20, "text/plain")})
    check(r.ok, f"{who}: setup project file {r.text[:120]}")
    fid, fpath = dbx("SELECT id, path FROM list_files WHERE list_id=?", (lid,))[0]
    check(s.delete(B + f"/api/list-files/{fid}").ok, f"{who}: project file deleted")
    ov = s.get(B + f"/api/lists/{lid}/overview").json()
    check(not ov["files"] and [x["id"] for x in ov.get("files_trash") or []] == [fid] and ov.get("files_trash_days") == 30,
          f"{who}: overview: in its trash with the period {ov.get('files_trash')}")
    check(s.get(B + f"/api/list-files/{fid}").status_code == 404 and os.path.isfile(os.path.join(ATT, fpath)), f"{who}: 404, the file stays")
    r = s.post(B + f"/api/list-files/{fid}/restore")
    check(r.ok and [x["id"] for x in r.json()["files"]] == [fid] and not r.json()["files_trash"], f"{who}: project file restored {r.text[:160]}")
    # 2.272.0 F (#3038, review E2-H2 / E2-H1): a file in the trash leaves the quota, is skipped by the encryption switch and can
    # be deleted for good by the person; the same for a project file
    uid = s.get(B + "/api/state").json()["me"]["id"]
    probe = (f"from kalmido.core.pg import system_ctx\nfrom kalmido.admin.hosting import _user_bytes\nfrom kalmido.collab.liste2efile import le2f_left\n"
             f"with system_ctx(c):\n    print('probe', _user_bytes(c, [{uid}]), le2f_left(c, {lid}, 'encrypting', 0, {uid})[1])")
    r = s.post(B + f"/api/tasks/{tid}/attachments", files={"file": ("oops.txt", b"wrong file\n" * 50, "text/plain")})
    oops, opath = max(dbx("SELECT id, path FROM attachments WHERE task_id=?", (tid,)))
    b0 = in_app(probe).split("probe", 1)[-1].split()
    check(s.delete(B + f"/api/attachments/{oops}").ok, f"{who}: the wrong file into the trash")
    b1 = in_app(probe).split("probe", 1)[-1].split()
    b0, b1 = b0[:2], b1[:2]  # the server prints its start warnings after the line
    check(len(b0) == 2 and len(b1) == 2 and int(b1[0]) < int(b0[0]) and int(b1[1]) == int(b0[1]) - 1,
          f"{who}: a file in the trash leaves the quota and the encryption switch {b0} {b1}")
    check(s.delete(B + f"/api/attachments/{aid}/purge").status_code == 404, f"{who}: purge only from the trash")
    r = s.delete(B + f"/api/attachments/{oops}/purge")
    check(r.ok and not dbx("SELECT 1 FROM attachments WHERE id=?", (oops,)) and not os.path.exists(os.path.join(ATT, opath))
          and oops not in [x["id"] for x in r.json().get("attachments_trash") or []], f"{who}: deleted for good, row and file {r.text[:160]}")
    r = s.post(B + f"/api/lists/{lid}/files", files={"file": ("wrong.txt", b"wrong brief\n" * 20, "text/plain")})
    wf, wpath = max(dbx("SELECT id, path FROM list_files WHERE list_id=?", (lid,)))
    check(s.delete(B + f"/api/list-files/{wf}").ok, f"{who}: the wrong project file into the trash")
    r = s.delete(B + f"/api/list-files/{wf}/purge")
    check(r.ok and not dbx("SELECT 1 FROM list_files WHERE id=?", (wf,)) and not os.path.exists(os.path.join(ATT, wpath)),
          f"{who}: project file deleted for good {r.text[:160]}")
    # into the trash again, made old; a fresh one next to it
    check(s.delete(B + f"/api/attachments/{aid}").ok and s.delete(B + f"/api/list-files/{fid}").ok, f"{who}: both deleted again")
    sql("UPDATE attachments SET deleted_at=? WHERE id=?", (OLD, aid))
    sql("UPDATE list_files SET deleted_at=? WHERE id=?", (OLD, fid))
    r = s.post(B + f"/api/tasks/{tid}/attachments", files={"file": ("fresh.txt", b"fresh\n" * 20, "text/plain")})
    fresh = max(x[0] for x in dbx("SELECT id FROM attachments WHERE task_id=?", (tid,)))
    check(s.delete(B + f"/api/attachments/{fresh}").ok, f"{who}: a fresh one in the trash")
    return aid, path, fid, fpath, fresh


def office_case(s, who):
    """A quotation draft with a position and a service: office trash, restore, made old for the run."""
    r = s.post(B + "/api/office/docs", json={"project_title": f"Spring {who}"})
    check(r.status_code == 201, f"{who}: setup quotation {r.text[:160]}")
    did = r.json()["id"]
    check(s.put(B + f"/api/office/docs/{did}/items", json={"items": [{"kind": "service", "title": "Shoot day", "qty": 2, "unit": "day", "rate": 500}]}).ok,
          f"{who}: setup position")
    r = s.delete(B + f"/api/office/docs/{did}")
    tid = r.json().get("trash_id") if r.ok else None
    check(r.ok and tid and one("SELECT COUNT(*) FROM office_docs WHERE id=?", (did,)) == 0, f"{who}: the draft goes, a trash copy {r.text[:160]}")
    lst = s.get(B + "/api/office/trash").json()
    check([x["id"] for x in lst["items"]] == [tid] and lst["items"][0]["kind"] == "doc" and "Spring" in lst["items"][0]["label"] and lst["days"] == 30,
          f"{who}: office trash lists it {lst}")
    r = s.post(B + f"/api/office/trash/{tid}/restore")
    d = s.get(B + f"/api/office/docs/{did}").json()
    check(r.ok and d.get("project_title") == f"Spring {who}" and [x["title"] for x in d.get("items") or []] == ["Shoot day"],
          f"{who}: restored with its position {r.text[:160]}")
    check(s.post(B + f"/api/office/trash/{tid}/restore").status_code == 404, f"{who}: a second restore: 404")
    sv = s.post(B + "/api/office/services", json={"name_de": f"Schnitt {who}", "daily_rate": 400}).json()["id"]
    r = s.delete(B + f"/api/office/services/{sv}")
    st = r.json().get("trash_id")
    check(r.ok and r.json().get("result") == "deleted" and st, f"{who}: a service into the office trash {r.text[:160]}")
    check(s.post(B + f"/api/office/trash/{st}/restore").ok and s.get(B + f"/api/office/services/{sv}").json().get("daily_rate") == 400,
          f"{who}: the service is back")
    # into the trash again, made old
    did_tid = s.delete(B + f"/api/office/docs/{did}").json().get("trash_id")
    sql("UPDATE office_trash SET deleted_at=? WHERE id=?", (OLD, did_tid))
    return did_tid


def section_case(s, who):
    lid = s.post(B + "/api/lists", json={"name": f"Sections {who}"}).json()["id"]
    sid = s.post(B + "/api/sections", json={"list_id": lid, "name": "Shoot"}).json()["id"]
    t1 = s.post(B + "/api/tasks", json={"title": "Light", "list_id": lid, "section_id": sid}).json()["id"]
    check(one("SELECT section_id FROM tasks WHERE id=?", (t1,)) == sid, f"{who}: setup task in the section")
    check(s.delete(B + f"/api/tasks/{t1}").ok, f"{who}: task into the trash")
    check(s.delete(B + f"/api/sections/{sid}").ok, f"{who}: the section deleted")
    check(one("SELECT trash_section FROM tasks WHERE id=?", (t1,)) == "Shoot", f"{who}: the task in the trash remembers its section")
    check(s.post(B + f"/api/tasks/{t1}/restore").ok, f"{who}: restore")
    ns = one("SELECT section_id FROM tasks WHERE id=?", (t1,))
    check(ns and one("SELECT name FROM sections WHERE id=?", (ns,)) == "Shoot" and one("SELECT list_id FROM sections WHERE id=?", (ns,)) == lid
          and one("SELECT trash_section FROM tasks WHERE id=?", (t1,)) is None, f"{who}: back in a section 'Shoot' made anew")


# ---- files, office, sections: alice (instance admin, private space) and frida (no organisation, P4)
fa = files_case(A, "alice")
ff = files_case(Fr, "frida")
oa = office_case(A, "alice")
of = office_case(Fr, "frida")
section_case(A, "alice")
section_case(Fr, "frida")

# ---- the trash run: switch off = only counted; on = the old ones go, the fresh ones stay
out = tick(False)
for aid, path, fid, fpath, fresh in (fa, ff):
    check(one("SELECT COUNT(*) FROM attachments WHERE id=?", (aid,)) == 1 and os.path.isfile(os.path.join(ATT, path))
          and one("SELECT COUNT(*) FROM list_files WHERE id=?", (fid,)) == 1, "switch off: files stay")
check(one("SELECT COUNT(*) FROM office_trash WHERE id IN (?, ?)", (oa, of)) == 2, "switch off: office copies stay")
check("'attachments': 2" in out and "'list_files': 2" in out and "'office': 2" in out, "switch off: counted " + out[-400:])
tick(True)
for aid, path, fid, fpath, fresh in (fa, ff):
    check(one("SELECT COUNT(*) FROM attachments WHERE id=?", (aid,)) == 0 and not os.path.exists(os.path.join(ATT, path)), "switch on: old task file gone (row + disk)")
    check(one("SELECT COUNT(*) FROM list_files WHERE id=?", (fid,)) == 0 and not os.path.exists(os.path.join(ATT, fpath)), "switch on: old project file gone")
    check(one("SELECT COUNT(*) FROM attachments WHERE id=?", (fresh,)) == 1, "switch on: the fresh one stays")
check(one("SELECT COUNT(*) FROM office_trash WHERE id IN (?, ?)", (oa, of)) == 0, "switch on: old office copies gone")

# ---- list_purge: fields, tags and section names into the inbox
LP = A.post(B + "/api/lists", json={"name": "Old project"}).json()["id"]
SP = A.post(B + "/api/sections", json={"list_id": LP, "name": "Edit"}).json()["id"]
F = A.post(B + f"/api/lists/{LP}/fields", json={"name": "Budget", "type": "number"}).json()["id"]
TP = A.post(B + "/api/tasks", json={"title": "Grade", "list_id": LP, "section_id": SP}).json()["id"]
check(A.patch(B + f"/api/tasks/{TP}", json={"fields": {str(F): 1200}}).ok, "setup: a field value")
sql("INSERT INTO list_tags(list_id, name, color, sort, created_at) VALUES(?,?,?,?,?)", (LP, "urgent", "", 0, OLD))
TG = one("SELECT id FROM list_tags WHERE list_id=?", (LP,))
sql("INSERT INTO task_list_tags(task_id, tag_id) VALUES(?,?)", (TP, TG))
INBOX = one("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (A_ID,))
out = in_app(f"from kalmido.core.pg import system_ctx\nfrom kalmido.lists.lists import list_purge\nwith system_ctx(c):\n    list_purge(c, {LP}, {INBOX})\nc.commit()\nprint('ok')")
check("ok" in out and "Traceback" not in out, "list_purge ran " + out[-600:])
nf = one("SELECT id FROM list_fields WHERE list_id=? AND name='Budget' AND type='number'", (INBOX,))
check(one("SELECT list_id FROM tasks WHERE id=?", (TP,)) == INBOX and one("SELECT deleted_at FROM tasks WHERE id=?", (TP,)), "list_purge: the task in the inbox trash")
check(nf and one("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (TP, nf)) is not None, "list_purge: the field and its value went along")
check(one("SELECT COUNT(*) FROM task_list_tags x JOIN list_tags t ON t.id=x.tag_id WHERE x.task_id=? AND t.list_id=? AND t.name='urgent'", (TP, INBOX)) == 1,
      "list_purge: the tag went along")
check(one("SELECT trash_section FROM tasks WHERE id=?", (TP,)) == "Edit", "list_purge: the section's name is kept")

# ---- removing a member: the question names what goes (dry: nothing changes)
LS = A.post(B + "/api/lists", json={"name": "Shared"}).json()["id"]
check(A.put(B + f"/api/lists/{LS}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: bob in the list")
TB = A.post(B + "/api/tasks", json={"title": "Bob's job", "list_id": LS, "assignee_id": BOB}).json()["id"]
r = A.delete(B + f"/api/lists/{LS}/members/{BOB}?dry=1")
check(r.ok and r.json().get("assigned") == 1 and r.json().get("values") == 0, f"member dry run: 1 assignment {r.text[:160]}")
check(one("SELECT assignee_id FROM tasks WHERE id=?", (TB,)) == BOB and one("SELECT COUNT(*) FROM list_members WHERE list_id=? AND user_id=?", (LS, BOB)) == 1,
      "member dry run: nothing changed")

# ---- checklist "clear done": only my own; the other members' ones on the owner's choice
mine = A.post(B + "/api/tasks", json={"title": "Milk", "list_id": LS}).json()["id"]
bobs = Bo.post(B + "/api/tasks", json={"title": "Bread", "list_id": LS}).json()["id"]
for t, s in ((mine, A), (bobs, Bo)):
    check(s.post(B + f"/api/tasks/{t}/complete", json={}).ok, "setup: done")
r = Bo.post(B + f"/api/lists/{LS}/checklist", json={"action": "clear_done", "dry": True})
check(r.ok and r.json() == {"own": 1, "others": 1, "may_others": False}, f"bob's dry run {r.text[:160]}")
r = Bo.post(B + f"/api/lists/{LS}/checklist", json={"action": "clear_done", "others": True})
check(r.ok and r.json().get("ids") == [bobs] and r.json().get("kept") == 1 and one("SELECT deleted_at FROM tasks WHERE id=?", (mine,)) is None,
      f"bob (edit): only his own, others=true does not count for him {r.text[:160]}")
check(Bo.post(B + f"/api/tasks/{bobs}/restore").ok, "setup: bob's back")
check(one("SELECT status FROM tasks WHERE id=?", (bobs,)) != 0, "setup: bob's still done after the restore")
r = A.post(B + f"/api/lists/{LS}/checklist", json={"action": "clear_done"})
check(r.ok and r.json().get("ids") == [mine] and r.json().get("kept") == 1, f"alice: by default only her own {r.text[:160]}")
r = A.post(B + f"/api/lists/{LS}/checklist", json={"action": "clear_done", "others": True})
check(r.ok and r.json().get("ids") == [bobs], f"alice (owner) with others=true: bob's too {r.text[:160]}")

sys.exit(done("p2272_e2_attach_trash"))
