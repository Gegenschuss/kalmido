#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.981.0 (#5274, stage Q4c of the cross-cutting core): the team chat's trash is the comments' core. Own container. Invented
names only.
 - the table: tchat_trash_text is gone; obj_comment_trash has a kind and the key (kind, comment_id), no foreign key
 - a message of a project's channel: who only takes part (edit / view) deletes no message of someone else (403), the project's
   owner (manage on the room) does; its text waits in obj_comment_trash kind 'tchat'; its reactions stay and come back with the
   restore (question 5); the author restores it
 - a channel of the organisation: its creator (manage) deletes and restores a member's message; another member does not (403)
 - the same id: a task comment and a team chat message with one id are kept side by side in the trash, each restore brings
   back its own text, never the other's
 - the move: an old tchat_trash_text made again by hand (what a version before leaves) goes into obj_comment_trash at the next
   start and is dropped; the restore of the moved message brings its old text; a text of a live message stays behind
 - an account's deletion takes only the kept texts of its own messages / comments (not the other kind with the same id)
 - a person without an organisation: own channel message deleted, not by the other member, restored with its reaction
freelancer-matrix: team
usage: p2981_a2_teamchat_trash_test.py <datadir>"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, dbx  # noqa: E402
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


def kept(kind, i):
    r = dbx("SELECT body FROM obj_comment_trash WHERE kind=? AND comment_id=?", (kind, i))
    return r[0][0] if r else None


def msgs(s, rid):
    r = s.get(B + f"/api/team/rooms/{rid}/messages")
    return {m["id"]: m for m in r.json()["messages"]} if r.ok else {}


def comments(s, tid):
    r = s.get(B + f"/api/tasks/{tid}/timeline")
    return {k["id"]: k for k in r.json()["comments"]} if r.ok else {}


def msg_at(mid, rid, uid, text):
    """A team chat message with a chosen id (the same as a comment's) -- straight into the table, like a written one."""
    dbx("INSERT INTO tchat_msgs(id, room_id, user_id, body, created_at) VALUES(?,?,?,?,?)", (mid, rid, uid, text, "2026-11-10T09:00:00.000+00:00"))


def comment_at(cid, tid, uid, text):
    """A task comment with a chosen id (the same as a message's)."""
    dbx("INSERT INTO obj_comments(id, kind, ref_id, user_id, body) VALUES(?, 'task', ?, ?, ?)", (cid, tid, uid, text))


kt.fresh(prefix="P2981A2")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
for u in ("bob", "dora", "otto", "erik"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    org_join(B, u, ORG)
Bo, Do, Ot, Er = kt.sess("bob"), kt.sess("dora"), kt.sess("otto"), kt.sess("erik")
for s in (Bo, Do, Ot, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
BOB, DORA, OTTO, ERIK = kt.me_id(Bo), kt.me_id(Do), kt.me_id(Ot), kt.me_id(Er)

# ================================================================== the table
check(not table_there("tchat_trash_text"), "the old table tchat_trash_text is gone")
key = dbx("""SELECT array_agg(a.attname::text ORDER BY a.attname) FROM pg_constraint con JOIN pg_attribute a ON a.attrelid=con.conrelid
             AND a.attnum = ANY(con.conkey) WHERE con.contype='p' AND con.conrelid='obj_comment_trash'::regclass""")
check(key and key[0][0] == ["comment_id", "kind"], f"obj_comment_trash: key (kind, comment_id) {key}")
check(not dbx("SELECT 1 FROM pg_constraint WHERE contype='f' AND conrelid='obj_comment_trash'::regclass"),
      "obj_comment_trash: no foreign key (a kind names its table, triggers delete with the row)")

LID = A.post(B + "/api/lists", json={"name": "Schnitt", "kind": "project", "org_id": ORG}).json()["id"]
for u, role in ((BOB, "edit"), (DORA, "edit"), (OTTO, "view"), (ERIK, "edit")):
    check(A.put(B + f"/api/lists/{LID}/members", json={"user_id": u, "role": role}).ok, f"setup: member {u} ({role})")
TID = A.post(B + "/api/tasks", json={"title": "Rohschnitt", "list_id": LID}).json()["id"]
room = next((x for x in A.get(B + "/api/team").json()["rooms"] if x["kind"] == "list" and x["list_id"] == LID), None)
check(room is not None, "setup: the project's channel")
RID = room["id"]
for s in (Bo, Do, Ot, Er):
    s.get(B + "/api/team")

# ================================================================== delete / restore in a project's channel, with reactions
r = Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Farbkorrektur fertig"})
check(r.status_code == 201, f"bob writes {r.status_code} {r.text[:160]}")
M1 = r.json()["id"]
check(Do.post(B + f"/api/team/messages/{M1}/reactions", json={"emoji": "up", "on": True}).ok, "setup: dora reacts")
check(A.post(B + f"/api/team/messages/{M1}/reactions", json={"emoji": "heart", "on": True}).ok, "setup: alice reacts")
RX = sorted((x["emoji"], x["count"]) for x in msgs(Bo, RID)[M1]["reactions"])
check(len(RX) == 2, f"setup: two reactions on the message {RX}")
check(Do.delete(B + f"/api/team/messages/{M1}").status_code == 403, "dora (edit, not the author) deletes bob's message not (403)")
check(Ot.delete(B + f"/api/team/messages/{M1}").status_code == 403, "otto (only reads) deletes it not (403)")
check(dbx("SELECT deleted_at FROM tchat_msgs WHERE id=?", (M1,))[0][0] is None, "the message is still there")
check(A.delete(B + f"/api/team/messages/{M1}").ok, "alice (the project's owner: manage on the room) deletes bob's message")
check(kept("tchat", M1) == "Farbkorrektur fertig" and kept("comment", M1) is None,
      "its text waits in obj_comment_trash, kind tchat (not as a comment)")
m = msgs(Do, RID).get(M1)
check(m is None or (m["deleted"] and m["body"] == "" and m["reactions"] == []), f"the conversation shows it deleted, no reactions {m}")
check(dbx("SELECT COUNT(*) FROM obj_reactions WHERE target_kind='tchat' AND target_id=?", (M1,))[0][0] == 2,
      "the reactions stay in the core while the message is in the trash")
check(Do.post(B + f"/api/team/messages/{M1}/restore").status_code == 403, "dora may not restore it")
r = Bo.post(B + f"/api/team/messages/{M1}/restore")
check(r.ok and r.json()["body"] == "Farbkorrektur fertig" and not r.json()["deleted"], f"bob restores it {r.status_code} {r.text[:160]}")
m = msgs(Do, RID).get(M1) or {}
check(sorted((x["emoji"], x["count"]) for x in m.get("reactions") or []) == RX, f"question 5: the reactions are back {m.get('reactions')}")
check(kept("tchat", M1) is None, "the kept text is gone after the restore")
check(A.delete(B + f"/api/team/messages/{M1}").ok and A.post(B + f"/api/team/messages/{M1}/restore").ok,
      "the owner (manage) restores what she deleted too")

# ================================================================== a channel of the organisation: its creator manages
r = Do.post(B + "/api/team/channels", json={"name": "Grading", "org_id": ORG, "members": [BOB, OTTO]})
check(r.status_code == 201, f"setup: dora's channel {r.status_code} {r.text[:160]}")
CH = r.json()["id"]
M2 = Bo.post(B + f"/api/team/rooms/{CH}/messages", json={"body": "LUT gewaehlt"}).json()["id"]
check(Ot.delete(B + f"/api/team/messages/{M2}").status_code == 403, "otto (a member) deletes bob's message not (403)")
check(Er.delete(B + f"/api/team/messages/{M2}").status_code == 404, "erik (not in the channel) gets 404")
check(Do.delete(B + f"/api/team/messages/{M2}").ok and kept("tchat", M2) == "LUT gewaehlt", "dora (its creator) deletes it, text kept")
check(Ot.post(B + f"/api/team/messages/{M2}/restore").status_code == 403, "otto restores it not")
r = Do.post(B + f"/api/team/messages/{M2}/restore")
check(r.ok and r.json()["body"] == "LUT gewaehlt", f"dora restores it {r.status_code}")

# ================================================================== the same id: a comment and a message
SAME = 900001
comment_at(SAME, TID, BOB, "Kommentar-Text 900001")
msg_at(SAME, RID, BOB, "Chat-Text 900001")
check(SAME in comments(Bo, TID) and SAME in msgs(Bo, RID), "setup: a comment and a message with the same id")
check(Bo.delete(B + f"/api/comments/{SAME}").ok, "bob deletes the comment")
check(Bo.delete(B + f"/api/team/messages/{SAME}").ok, "bob deletes the message of the same id")
check(kept("comment", SAME) == "Kommentar-Text 900001" and kept("tchat", SAME) == "Chat-Text 900001",
      "both texts wait side by side, each under its kind")
r = Bo.post(B + f"/api/team/messages/{SAME}/restore")
check(r.ok and r.json()["body"] == "Chat-Text 900001", f"the message's restore brings the message's text, never the comment's {r.text[:160]}")
check(kept("comment", SAME) == "Kommentar-Text 900001", "the comment's text is still kept")
check(SAME not in comments(Bo, TID) or comments(Bo, TID)[SAME].get("body") in ("", None), "the comment stays deleted")
r = Bo.post(B + f"/api/comments/{SAME}/restore")
check(r.ok and (comments(Bo, TID).get(SAME) or {}).get("body") == "Kommentar-Text 900001",
      f"the comment's restore brings the comment's text {r.status_code} {r.text[:160]}")
check(msgs(Bo, RID)[SAME]["body"] == "Chat-Text 900001", "the message keeps its own text")
# the other order: the message first, a comment deleted later writes no text over it
check(Bo.delete(B + f"/api/team/messages/{SAME}").ok and Bo.delete(B + f"/api/comments/{SAME}").ok, "both deleted again (message first)")
check(kept("tchat", SAME) == "Chat-Text 900001" and kept("comment", SAME) == "Kommentar-Text 900001", "neither text overwrote the other")
check(Bo.post(B + f"/api/comments/{SAME}/restore").ok and Bo.post(B + f"/api/team/messages/{SAME}/restore").ok
      and msgs(Bo, RID)[SAME]["body"] == "Chat-Text 900001" and comments(Bo, TID)[SAME]["body"] == "Kommentar-Text 900001",
      "both restores bring their own text")

# ================================================================== the move of an old tchat_trash_text (a version before ran)
M3 = Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "wird gleich alt"}).json()["id"]
M4 = Bo.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "lebt noch"}).json()["id"]
dbx("UPDATE tchat_msgs SET body='', deleted_at='2026-11-10T10:00:00.000+00:00', edited_at='2026-11-10T10:00:00.000+00:00' WHERE id=?", (M3,))
dbx("CREATE TABLE tchat_trash_text (message_id BIGINT PRIMARY KEY REFERENCES tchat_msgs(id) ON DELETE CASCADE, body TEXT NOT NULL DEFAULT '', enc TEXT)")
dbx("INSERT INTO tchat_trash_text(message_id, body) VALUES(?, 'Alter Papierkorb-Text')", (M3,))
dbx("INSERT INTO tchat_trash_text(message_id, body) VALUES(?, 'gehoert zu keiner geloeschten')", (M4,))
box("pass")  # the next start of the app
check(not table_there("tchat_trash_text"), "the start moved and dropped the old table made again")
check(kept("tchat", M3) == "Alter Papierkorb-Text" and kept("comment", M3) is None, "the kept text moved, kind tchat")
check(kept("tchat", M4) is None, "a text of a live message stays behind")
r = Bo.post(B + f"/api/team/messages/{M3}/restore")
check(r.ok and r.json()["body"] == "Alter Papierkorb-Text", f"the moved message is restored with its old text {r.status_code} {r.text[:160]}")
check(msgs(Bo, RID)[M4]["body"] == "lebt noch", "the live message is unchanged")

# ================================================================== an account goes: only its own kept texts
E1, E2 = 900010, 900020
msg_at(E1, RID, ERIK, "Eriks Nachricht")
comment_at(E1, TID, ALICE, "Alices Kommentar")
comment_at(E2, TID, ERIK, "Eriks Kommentar")
msg_at(E2, RID, BOB, "Bobs Nachricht")
check(Er.delete(B + f"/api/team/messages/{E1}").ok and A.delete(B + f"/api/comments/{E1}").ok
      and Er.delete(B + f"/api/comments/{E2}").ok and Bo.delete(B + f"/api/team/messages/{E2}").ok, "setup: four deleted, two ids")
check(all(kept(k, i) for k, i in (("tchat", E1), ("comment", E1), ("comment", E2), ("tchat", E2))), "setup: four kept texts")
check(A.delete(B + f"/api/users/{ERIK}").ok, "erik's account is deleted")
check(kept("tchat", E1) is None and kept("comment", E2) is None, "erik's kept message and comment went with the account")
check(kept("comment", E1) == "Alices Kommentar" and kept("tchat", E2) == "Bobs Nachricht",
      "the other people's texts with the same ids stay")
check(A.post(B + f"/api/team/messages/{E1}/restore").status_code == 404, "nobody brings erik's message back (404)")
check(A.post(B + f"/api/comments/{E1}/restore").ok and Bo.post(B + f"/api/team/messages/{E2}/restore").ok,
      "alice's comment and bob's message come back")

# ================================================================== the trash run takes the kept text with the row
check(Bo.delete(B + f"/api/team/messages/{M4}").ok and kept("tchat", M4) == "lebt noch", "setup: one more kept text")
dbx("DELETE FROM tchat_msgs WHERE id=?", (M4,))
check(kept("tchat", M4) is None, "a message deleted for good takes its kept text (trigger kalmido_oct_gone_tchat)")
check(Bo.delete(B + f"/api/comments/{SAME}").ok and Bo.delete(B + f"/api/team/messages/{SAME}").ok, "setup: both of the same id deleted")
dbx("DELETE FROM obj_comments WHERE id=?", (SAME,))
check(kept("comment", SAME) is None and kept("tchat", SAME) == "Chat-Text 900001",
      "a comment deleted for good takes only its own kept text, not the message's of the same id")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
FIO, Fi = freelancer(B, A, "fiona")
dbx("INSERT INTO groups(name, oidc_group, created_at, created_by) VALUES(?,?,?,?)", ("Pool 5274", "", "2026-11-11T08:00:00", ALICE))
GID = dbx("SELECT id FROM groups WHERE name=?", ("Pool 5274",))[0][0]
for x in (FID, FIO):
    dbx("INSERT INTO group_members(group_id, user_id, added_at) VALUES(?,?,?)", (GID, x, "2026-11-11T08:00:00"))
r = Fr.post(B + "/api/team/channels", json={"name": "Club 5274", "members": [FIO]})
check(r.status_code == 201, "freelancer: own channel " + r.text[:160])
FCH = r.json()["id"]
FM = Fr.post(B + f"/api/team/rooms/{FCH}/messages", json={"body": "Clubabend"}).json()["id"]
check(Fi.post(B + f"/api/team/messages/{FM}/reactions", json={"emoji": "up", "on": True}).ok, "freelancer: fiona reacts")
check(Fi.delete(B + f"/api/team/messages/{FM}").status_code == 403, "freelancer: fiona deletes her message not (403)")
check(Fr.delete(B + f"/api/team/messages/{FM}").ok and kept("tchat", FM) == "Clubabend", "freelancer: own message into the trash")
r = Fr.post(B + f"/api/team/messages/{FM}/restore")
check(r.ok and r.json()["body"] == "Clubabend", f"freelancer: restored {r.status_code}")
fm = msgs(Fi, FCH).get(FM) or {}
check(fm.get("body") == "Clubabend" and len(fm.get("reactions") or []) == 1, f"freelancer: fiona sees it again with her reaction {fm}")

sys.exit(kt.done("p2981_a2_teamchat_trash"))
