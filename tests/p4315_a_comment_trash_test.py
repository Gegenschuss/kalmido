#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.530.0 A (#4315, audit #2425 B36 B37 B11): deleting a comment or a team chat message puts it into the trash. Invented names only.
 - a comment with a file (also someone else's, deleted by the list owner): row, text and file stay in the database and on disk,
   nothing shows it (timeline, state, v1 for an agent, the file download, the task's file trash); a member who is neither the
   author nor an owner may not restore it, a person outside the list gets 404; the author restores it with its file; the trash
   run after the period removes row, text, file row and file
 - an agent deleting a comment through v1 waits for a person's approval (202)
 - a team chat message with a file in a list channel: the same (text + file kept, invisible, restore, run removes them)
 - a person without an organisation: own comment and own channel message deleted and restored (freelancer-matrix: tasks, team)
usage: p4315_a_comment_trash_test.py <datadir>"""
import os
import subprocess
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, DATA, check, dbx, docker_logs_on_first_fail, done, fresh, sess, setup  # noqa: E402

fresh(prefix="P4315A")
docker_logs_on_first_fail()
A = setup()
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
FEAT = "collab,comments"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
OLD = "2020-01-01T00:00:00.000+00:00"
SECRET, CHAT = "Zebrafinch plan", "Kingfisher note"
uid = {}
for u in ("bob", "dave", "carl"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com",
                                       "orgs": [{"id": ORG, "role": "member"}]})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Da, Ca = sess("bob"), sess("dave"), sess("carl")
for s in (Bo, Da, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})


def write(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    try:
        c.execute(q, args)
        c.commit()
    finally:
        c.close()


def box(code):
    """Python in the app container with the trash switch on (KALMIDO_PURGE_TRASH=1). -> last line."""
    out = subprocess.run(["docker", "exec", "-e", "KALMIDO_PURGE_TRASH=1", CT, "python", "-c", "import json, app\nc = app.connect()\ntry:\n"
                          + "".join("    " + ln + "\n" for ln in code.splitlines()) + "finally:\n    c.close()"],
                         capture_output=True, text=True)
    check(out.returncode == 0, f"the run works {out.stdout[-200:]} {out.stderr[-800:]}")
    lines = out.stdout.strip().splitlines()
    return lines[-1] if lines else ""


def disk(path):
    """True / False: the stored file on disk; None when the data dir is not readable here."""
    root = os.path.join(DATA, "attachments")
    return os.path.isfile(os.path.join(root, path)) if os.path.isdir(root) else None


def one(q, args=()):
    rows = dbx(q, args)
    return tuple(rows[0]) if rows else None


def comment_with_file(s, tid, text, name="plan.txt"):
    r = s.post(B + f"/api/tasks/{tid}/comments", data={"body": text}, files=[("file", (name, b"invented file content", "text/plain"))])
    check(r.ok, "setup: a comment with a file " + r.text[:160])
    cid = r.json()["id"]
    aid, path = one("SELECT id, path FROM attachments WHERE comment_id=?", (cid,))
    return cid, aid, path


# ================================================================== comments
L = A.post(B + "/api/lists", json={"name": "Shared project", "org_id": ORG}).json()["id"]
for u, role in (("bob", "edit"), ("dave", "edit")):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": uid[u], "role": role}).ok
T = A.post(B + "/api/tasks", json={"title": "Plan the trip", "list_id": L}).json()["id"]
CM, AT, AP = comment_with_file(Bo, T, SECRET)
check(disk(AP) in (True, None), "setup: the comment's file on disk")
r = A.delete(B + f"/api/comments/{CM}")
check(r.ok, f"the list owner deletes bob's comment {r.status_code}")
row = one("SELECT body, deleted_at FROM obj_comments WHERE id=?", (CM,))
check(row and row[0] == "" and row[1], f"the row looks deleted as before (body '', deleted_at) {row}")
check(one("SELECT body FROM obj_comment_trash WHERE comment_id=?", (CM,)) == (SECRET,), "#4315: the text is kept in the trash")
# 2.972.0 (#5272): the comment's time is a TIMESTAMPTZ now, the file's a text: compared as points in time
fa = one("SELECT a.deleted_at, a.deleted_at::timestamptz = k.deleted_at FROM attachments a, obj_comments k WHERE a.id=? AND k.id=?", (AT, CM))
check(fa is not None and fa[1] is True, f"#4315: the file row is kept, in the trash with the comment's time {fa}")
check(disk(AP) in (True, None), "#4315: the file stays on disk until the trash run")
# nothing shows it
for who, s in (("alice", A), ("bob", Bo), ("dave", Da)):
    tl = s.get(B + f"/api/tasks/{T}/timeline")
    check(tl.ok and SECRET not in tl.text and all(k["id"] != CM for k in tl.json()["comments"]), f"{who}: the timeline does not show it")
    st = s.get(B + "/api/state")
    check(SECRET not in st.text and "plan.txt" not in st.text, f"{who}: nor the state (no file in the task's file trash)")
    check(s.get(B + f"/api/attachments/{AT}").status_code == 404, f"{who}: the file download 404")
check(Bo.post(B + f"/api/attachments/{AT}/restore").status_code == 404, "the file alone cannot be restored from the file trash")
# rights of the restore
check(Da.post(B + f"/api/comments/{CM}/restore").status_code == 403, "dave (member, not the author, no owner) may not restore it")
check(Ca.post(B + f"/api/comments/{CM}/restore").status_code == 404, "carl (not in the project) gets 404")
r = Bo.post(B + f"/api/comments/{CM}/restore")
check(r.ok and r.json().get("task_id") == T, f"bob (the author) restores it {r.status_code} {r.text[:160]}")
tl = Bo.get(B + f"/api/tasks/{T}/timeline").json()["comments"]
k = next((x for x in tl if x["id"] == CM), None)
check(k and k["body"] == SECRET and [a["id"] for a in k["attachments"]] == [AT], f"text and file are back {k}")
check(Bo.get(B + f"/api/attachments/{AT}").content == b"invented file content", "the file opens again")
check(not dbx("SELECT 1 FROM obj_comment_trash WHERE comment_id=?", (CM,)), "the kept text is gone after the restore")
check(Bo.post(B + f"/api/comments/{CM}/restore").status_code == 404, "a live comment: nothing to restore (404)")
# a file deleted on its own before stays in the file trash when the comment comes back
CM2, AT2, AP2 = comment_with_file(Bo, T, "Second note", "keep.txt")
check(Bo.delete(B + f"/api/attachments/{AT2}").ok, "setup: bob removes the file of his second comment (file trash)")
FILE_TS = one("SELECT deleted_at FROM attachments WHERE id=?", (AT2,))[0]
check(Bo.delete(B + f"/api/comments/{CM2}").ok and Bo.post(B + f"/api/comments/{CM2}/restore").ok, "setup: second comment deleted and restored")
check(one("SELECT deleted_at FROM attachments WHERE id=?", (AT2,)) == (FILE_TS,), "a file removed before stays in the file trash")
# the trash run after the period: row, text, file row and file go
check(A.delete(B + f"/api/comments/{CM}").ok, "deleted again")
write("UPDATE attachments SET deleted_at=? WHERE comment_id=?", (OLD, CM))
write("UPDATE obj_comments SET deleted_at=? WHERE id=?", (OLD, CM))
box("from kalmido.files.trashpurge import tp_tick\nprint(json.dumps(tp_tick(c, True)))")
check(not dbx("SELECT 1 FROM obj_comments WHERE id=?", (CM,)) and not dbx("SELECT 1 FROM obj_comment_trash WHERE comment_id=?", (CM,)),
      "the trash run removes the comment and its kept text")
check(not dbx("SELECT 1 FROM attachments WHERE id=?", (AT,)), "the trash run removes the file row")
check(disk(AP) in (False, None), "the trash run removes the file from disk")
check(Bo.post(B + f"/api/comments/{CM}/restore").status_code == 404, "after the run: nothing to restore")
# a comment deleted before 2.530 (no kept text): 404
CM3 = Bo.post(B + f"/api/tasks/{T}/comments", json={"body": "old style"}).json()["id"]
write("UPDATE obj_comments SET body='', deleted_at=? WHERE id=?", ("2026-10-01T00:00:00.000+00:00", CM3))
check(Bo.post(B + f"/api/comments/{CM3}/restore").status_code == 404, "a comment deleted before 2.530 cannot be restored (404)")

# ================================================================== an agent deletes a comment: approval first
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "helper", "display_name": "Helper"})
assert r.status_code == 201, r.text
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
write("UPDATE agents SET control='' WHERE user_id=?", (AG,))  # no control level: the approval of need_approval is the gate here
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok
r = requests.post(B + f"/api/v1/tasks/{T}/comments", headers=AGH, json={"body": "Agent note"})
check(r.status_code == 201, f"setup: the agent comments {r.status_code} {r.text[:160]}")
AC = r.json()["id"]
r = requests.delete(B + f"/api/v1/comments/{AC}", headers=AGH)
check(r.status_code == 202 and r.json().get("approval_required") is True, f"#4315: the agent's delete waits for approval {r.status_code} {r.text[:160]}")
check(one("SELECT body, deleted_at FROM obj_comments WHERE id=?", (AC,)) == ("Agent note", None), "the comment is untouched meanwhile")
r = requests.delete(B + f"/api/v1/comments/{CM2}", headers=AGH)
check(r.status_code == 403, f"bob's comment: the agent may not delete it at all (403 before any approval) {r.status_code}")

# ================================================================== team chat (the list channel)
room = next((x for x in A.get(B + "/api/team").json()["rooms"] if x["kind"] == "list" and x["list_id"] == L), None)
check(room is not None, "setup: the project's channel")
RID = room["id"]
r = Bo.post(B + f"/api/team/rooms/{RID}/messages", data={"body": CHAT}, files=[("file", ("map.txt", b"invented map", "text/plain"))])
check(r.status_code == 201 and len(r.json().get("attachments") or []) == 1, "setup: bob's message with a file " + r.text[:160])
MID, FID_ = r.json()["id"], r.json()["attachments"][0]["id"]
FP = one("SELECT path FROM tchat_files WHERE id=?", (FID_,))[0]
check(A.delete(B + f"/api/team/messages/{MID}").ok, "the list owner deletes bob's message")
row = one("SELECT body, deleted_at FROM tchat_msgs WHERE id=?", (MID,))
check(row and row[0] == "" and row[1], f"the message looks deleted as before {row}")
check(one("SELECT body FROM tchat_trash_text WHERE message_id=?", (MID,)) == (CHAT,), "#4315: its text is kept in the trash")
check(dbx("SELECT 1 FROM tchat_files WHERE id=?", (FID_,)) and disk(FP) in (True, None), "#4315: its file row and file stay")
for who, s in (("bob", Bo), ("dave", Da)):
    ms = s.get(B + f"/api/team/rooms/{RID}/messages")
    m = next((x for x in ms.json()["messages"] if x["id"] == MID), None)
    check(ms.ok and CHAT not in ms.text and "map.txt" not in ms.text and (m is None or (m["deleted"] and m["attachments"] == [])),
          f"{who}: the conversation shows it deleted, without text or file")
    check(s.get(B + f"/api/team/files/{FID_}").status_code == 404, f"{who}: the file download 404")
    t = s.get(B + "/api/team")
    check(CHAT not in t.text and "map.txt" not in t.text, f"{who}: nor the conversation list (last message)")
check(Da.post(B + f"/api/team/messages/{MID}/restore").status_code == 403, "dave may not restore bob's message")
check(Ca.post(B + f"/api/team/messages/{MID}/restore").status_code in (403, 404), "carl (not in the channel) may not restore it")
r = Bo.post(B + f"/api/team/messages/{MID}/restore")
check(r.ok and r.json()["body"] == CHAT and not r.json()["deleted"] and [a["id"] for a in r.json()["attachments"]] == [FID_],
      f"bob restores it with its file {r.status_code} {r.text[:200]}")
check(Da.get(B + f"/api/team/files/{FID_}").content == b"invented map", "dave reads the file again")
check(Bo.post(B + f"/api/team/messages/{MID}/restore").status_code == 404, "a live message: nothing to restore (404)")
check(Bo.delete(B + f"/api/team/messages/{MID}").ok, "deleted again")
write("UPDATE tchat_msgs SET deleted_at=? WHERE id=?", (OLD, MID))
# 2.783.0 (#5368): the tombstones are the core's (core/writes.py obj_trash_tick), no longer tp_tick's
box("from kalmido.core.writes import obj_trash_tick\nprint(json.dumps(obj_trash_tick(c, force=True)))")
check(not dbx("SELECT 1 FROM tchat_msgs WHERE id=?", (MID,)) and not dbx("SELECT 1 FROM tchat_trash_text WHERE message_id=?", (MID,))
      and not dbx("SELECT 1 FROM tchat_files WHERE id=?", (FID_,)), "the trash run removes the message, its text and its file row")
check(disk(FP) in (False, None), "the trash run removes the message's file from disk")

# ================================================================== a person without an organisation
# freelancer-matrix: tasks, team
FRID, Fr = freelancer(B, A)
FIO, Fi = freelancer(B, A, "fiona")
FL = Fr.post(B + "/api/lists", json={"name": "My clients", "org_id": None}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Invoice draft", "list_id": FL}).json()["id"]
FC, FA, _p = comment_with_file(Fr, FT, "Own note")
check(Fr.delete(B + f"/api/comments/{FC}").ok and not Fr.get(B + f"/api/tasks/{FT}/timeline").json()["comments"], "freelancer: own comment deleted")
check(A.post(B + f"/api/comments/{FC}/restore").status_code == 404, "freelancer: the instance admin cannot restore her private comment")
r = Fr.post(B + f"/api/comments/{FC}/restore")
k = Fr.get(B + f"/api/tasks/{FT}/timeline").json()["comments"]
check(r.ok and k and k[0]["body"] == "Own note" and len(k[0]["attachments"]) == 1, f"freelancer: own comment restored with its file {r.status_code}")
# two freelancers work together through a group of the instance (as p2113b_b_api_test.py)
write("INSERT INTO groups(name,oidc_group,created_at,created_by) VALUES(?,?,?,?)", ("Pool 4315", "", "2026-11-04T08:00:00", ALICE))
GID = one("SELECT id FROM groups WHERE name=?", ("Pool 4315",))[0]
for x in (FRID, FIO):
    write("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (GID, x, "2026-11-04T08:00:00"))
r = Fr.post(B + "/api/team/channels", json={"name": "Club 4315", "members": [FIO]})
check(r.status_code == 201, "freelancer: own channel " + r.text[:160])
FCH = r.json()["id"]
r = Fr.post(B + f"/api/team/rooms/{FCH}/messages", json={"body": "Club news"})
FM = r.json()["id"]
check(Fr.delete(B + f"/api/team/messages/{FM}").ok, "freelancer: own message deleted")
check(Fi.post(B + f"/api/team/messages/{FM}/restore").status_code == 403, "freelancer: fiona may not restore it")
r = Fr.post(B + f"/api/team/messages/{FM}/restore")
check(r.ok and r.json()["body"] == "Club news", f"freelancer: own message restored {r.status_code}")
check(any(m["id"] == FM and m["body"] == "Club news" for m in Fi.get(B + f"/api/team/rooms/{FCH}/messages").json()["messages"]),
      "freelancer: fiona sees it again")

# ================================================================== 2.530.0 (#4315, review K2): the account goes, its kept words too
r = A.post(B + "/api/users", json={"username": "erin", "display_name": "Erin", "password": "password123", "email": "erin@example.com",
                                   "orgs": [{"id": ORG, "role": "member"}]})
assert r.ok, r.text
ERIN = r.json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ERIN, "role": "edit"}).ok
Er = sess("erin")
Er.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
EC = Er.post(B + f"/api/tasks/{T}/comments", json={"body": "Heron words"}).json()["id"]
check(Er.delete(B + f"/api/comments/{EC}").ok and dbx("SELECT 1 FROM obj_comment_trash WHERE comment_id=?", (EC,)),
      "account: erin's deleted comment keeps its text in the trash")
check(A.delete(B + f"/api/users/{ERIN}").ok, "account: erin deleted")
check(not dbx("SELECT 1 FROM obj_comment_trash WHERE comment_id=?", (EC,)), "account: the kept text went with the account")
check(A.post(B + f"/api/comments/{EC}/restore").status_code == 404, "account: the owner cannot bring erin's words back (404)")

sys.exit(done("p4315_a_comment_trash"))
