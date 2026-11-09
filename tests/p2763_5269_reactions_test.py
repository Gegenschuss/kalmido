#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.763.0 (#5269, stage Q1 of the cross-cutting core): reactions are rows of the core (obj_reactions, core/objreact.py).
Own container. Invented names only.
 - the start moved the rows of the old tables (comment_reactions, tchat_rx, chat_reactions) into obj_reactions and dropped
   them: an old table made again by hand with a row (what a version before 2.763 leaves after a rollback) is moved and dropped
   at the next start of the app; a row whose target is gone stays behind
 - the one rule for comments and team chat messages: not on one's own message (400, taking an old one back works), a guest of
   the organisation does not react (403); toggling sets / takes back; the answer lists {emoji, count, users}
 - a team chat message in the trash keeps its reactions (the answer shows none), a restore brings them back (decided
   08.11.2026, question 5); deleted for good (the trash run deletes the row) they go with it (trigger kalmido_orx_gone); the
   same for a comment's row
 - the account export lists my reactions with the kinds comment / message; the organisation export keeps the files
   comments/reactions.json (comment_id) and chat/reactions.json (message_id)
 - a person without an organisation (freelancer fixture) reacts on a comment in their own list, not on their own
freelancer-matrix: tasks
usage: p2763_5269_reactions_test.py <datadir>"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, dbx  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

NOW = "2026-11-09T10:00:00.000+00:00"


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


def rx(kind, tid):
    return sorted((r[0], r[1]) for r in dbx("SELECT user_id, emoji FROM obj_reactions WHERE target_kind=? AND target_id=?", (kind, tid)))


kt.fresh(prefix="P2763R")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
for u in ("bob", "gina"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    org_join(B, u, ORG)
Bo, Gi = kt.sess("bob"), kt.sess("gina")
for s in (Bo, Gi):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
BOB, GINA = kt.me_id(Bo), kt.me_id(Gi)

# ================================================================== the old tables are gone, the core's table is there
check(table_there("obj_reactions"), "the core's table obj_reactions exists")
for t in ("comment_reactions", "tchat_rx", "chat_reactions"):
    check(not table_there(t), f"the old table {t} is gone")

# ================================================================== comments: the one rule
LID = A.post(B + "/api/lists", json={"name": "Studio", "kind": "project", "org_id": ORG}).json()["id"]
for u in (BOB, GINA):
    A.put(B + f"/api/lists/{LID}/members", json={"user_id": u, "role": "edit"})
TID = A.post(B + "/api/tasks", json={"title": "Schnittplan", "list_id": LID}).json()["id"]
r = A.post(B + f"/api/tasks/{TID}/comments", json={"body": "Erster Entwurf steht"})
check(r.ok, f"setup: alice comments {r.status_code} {r.text[:200]}")
CID = r.json()["id"]
r = A.post(B + f"/api/comments/{CID}/reactions", json={"emoji": "up"})
check(r.status_code == 400 and "own" in r.text, f"alice cannot react to her own comment {r.status_code} {r.text[:200]}")
check(rx("comment", CID) == [], "nothing stored for her own comment")
r = Bo.post(B + f"/api/comments/{CID}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["reactions"] == [{"emoji": "up", "count": 1, "users": [{"id": BOB, "name": "Bob"}]}],
      f"bob's thumb on alice's comment {r.status_code} {r.text[:300]}")
check(rx("comment", CID) == [(BOB, "up")], "the reaction is a row of obj_reactions (kind comment)")
r = Bo.post(B + f"/api/comments/{CID}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["reactions"] == [] and rx("comment", CID) == [], f"a second press takes it back {r.text[:200]}")
Bo.post(B + f"/api/comments/{CID}/reactions", json={"emoji": "heart", "on": True})
tl = A.get(B + f"/api/tasks/{TID}/timeline").json()
k = next(x for x in tl["comments"] if x["id"] == CID)
check([e["emoji"] for e in k["reactions"]] == ["heart"], f"the timeline shows the reaction {k.get('reactions')}")
# an old reaction on one's own comment can still be taken back (the rule only stops setting one)
dbx("INSERT INTO obj_reactions(target_kind,target_id,user_id,emoji,created_at) VALUES('comment',?,?,?,?)", (CID, ALICE, "down", NOW))
r = A.post(B + f"/api/comments/{CID}/reactions", json={"emoji": "down", "on": False})
check(r.ok and (ALICE, "down") not in rx("comment", CID), f"an old reaction on her own comment is taken back {r.status_code} {r.text[:200]}")

# a guest of the organisation only reads: no reaction (403), taking one back stays
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": GINA, "role": "guest"}).ok, "setup: gina becomes a guest")
A.put(B + f"/api/lists/{LID}/members", json={"user_id": GINA, "role": "view"})
r = Gi.post(B + f"/api/comments/{CID}/reactions", json={"emoji": "up"})
check(r.status_code in (403, 404) and rx("comment", CID) == [(BOB, "heart")], f"a guest does not react on a comment {r.status_code} {r.text[:200]}")

# ================================================================== team chat: the rule, the trash and the restore
DM = A.post(B + "/api/team/dm", json={"user_id": BOB}).json()["id"]
r = A.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "Treffen um zehn?"})
check(r.status_code == 201, f"setup: alice writes to bob {r.status_code} {r.text[:200]}")
MID = r.json()["id"]
r = A.post(B + f"/api/team/messages/{MID}/reactions", json={"emoji": "up"})
check(r.status_code == 400 and "own" in r.text, f"alice cannot react to her own message {r.status_code} {r.text[:200]}")
r = Bo.post(B + f"/api/team/messages/{MID}/reactions", json={"emoji": "up"})
check(r.ok and r.json()["reactions"] == [{"emoji": "up", "count": 1, "users": [{"id": BOB, "name": "Bob"}]}],
      f"bob's thumb on alice's message {r.status_code} {r.text[:300]}")
check(rx("tchat", MID) == [(BOB, "up")], "the reaction is a row of obj_reactions (kind tchat)")
r = A.delete(B + f"/api/team/messages/{MID}")
check(r.ok, f"alice deletes her message {r.status_code}")
check(rx("tchat", MID) == [(BOB, "up")], "a message in the trash keeps its reactions")
msgs = A.get(B + f"/api/team/rooms/{DM}/messages").json()
m = next((x for x in (msgs.get("messages") if isinstance(msgs, dict) else msgs) if x["id"] == MID), None)
check(m is not None and m["deleted"] and m["reactions"] == [], f"the deleted message shows no reactions {m}")
r = Bo.post(B + f"/api/team/messages/{MID}/reactions", json={"emoji": "heart"})
check(r.status_code == 409, f"no reaction on a deleted message {r.status_code}")
r = A.post(B + f"/api/team/messages/{MID}/restore")
check(r.ok and r.json()["reactions"] == [{"emoji": "up", "count": 1, "users": [{"id": BOB, "name": "Bob"}]}],
      f"the restore brings the reactions back {r.status_code} {r.text[:300]}")

# ================================================================== exports
out = box(f"""import json
from kalmido.admin.acctexport import umz_mine_queries
q, a = umz_mine_queries({BOB})["reactions"]
print("RX" + json.dumps([dict(r) for r in c.execute(q, a).fetchall()], default=str))""")
line = next((x for x in out.splitlines() if x.startswith("RX")), None)
mine = json.loads(line[2:]) if line else []
check(sorted((x["kind"], x["target_id"], x["emoji"]) for x in mine) == [("comment", CID, "heart"), ("message", MID, "up")],
      f"the account export lists bob's reactions with the kinds comment / message {mine}")
check(all(isinstance(x["created_at"], str) and x["created_at"].endswith("+00:00") for x in mine), f"the time as ISO text {mine}")
out = box(f"""import io, json, zipfile
from kalmido.admin.orgexport import ox_build
b = io.BytesIO()
ox_build(c, {ORG}, b, by={{"id": {ALICE}, "name": "Admin"}})
z = zipfile.ZipFile(b)
print("OXJSON" + json.dumps({{n: json.loads(z.read(n)) for n in ("comments/reactions.json", "chat/reactions.json") if n in z.namelist()}}, default=str))""")
line = next((x for x in out.splitlines() if x.startswith("OXJSON")), None)
ox = json.loads(line[6:]) if line else {}
cr = ox.get("comments/reactions.json") or []
check([(x.get("comment_id"), x.get("user_id"), x.get("emoji")) for x in cr] == [(CID, BOB, "heart")] and "target_id" not in (cr[0] if cr else {}),
      f"the organisation export keeps comments/reactions.json with comment_id {cr}")

# ================================================================== deleted for good: the reactions go with the row
dbx("DELETE FROM tchat_msgs WHERE id=?", (MID,))
check(rx("tchat", MID) == [], "a team chat message deleted for good takes its reactions along")
dbx("DELETE FROM comments WHERE id=?", (CID,))
check(rx("comment", CID) == [], "a comment deleted for good takes its reactions along")

# ================================================================== the move of an old table (a version before 2.763 ran)
T2 = A.post(B + "/api/tasks", json={"title": "Abnahme", "list_id": LID}).json()["id"]
C2 = A.post(B + f"/api/tasks/{T2}/comments", json={"body": "Bitte abnehmen"}).json()["id"]
dbx("""CREATE TABLE comment_reactions (comment_id BIGINT NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
       user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, emoji TEXT NOT NULL, created_at TEXT NOT NULL,
       PRIMARY KEY (comment_id, user_id, emoji))""")
dbx("INSERT INTO comment_reactions(comment_id,user_id,emoji,created_at) VALUES(?,?,?,?)", (C2, BOB, "up", "2026-11-01T08:30:00.000+00:00"))
dbx("INSERT INTO comment_reactions(comment_id,user_id,emoji,created_at) VALUES(?,?,?,?)", (C2, GINA, "heart", "not a time"))
box("pass")  # the next start of the app
check(not table_there("comment_reactions"), "the start dropped the old table made again")
check(rx("comment", C2) == [(BOB, "up"), (GINA, "heart")], f"its rows moved into obj_reactions {rx('comment', C2)}")
when = dbx("SELECT created_at FROM obj_reactions WHERE target_kind='comment' AND target_id=? AND user_id=?", (C2, BOB))
check(when and str(when[0][0]).startswith("2026-11-01"), f"the time came along as a point in time {when}")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Eigenes"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Angebot schreiben", "list_id": FL}).json()["id"]
r = Fr.post(B + f"/api/tasks/{FT}/comments", json={"body": "Notiz"})
check(r.ok, f"setup: frida's note {r.status_code} {r.text[:200]}")
FC = r.json()["id"]
r = Fr.post(B + f"/api/comments/{FC}/reactions", json={"emoji": "up"})
check(r.status_code == 400 and rx("comment", FC) == [], f"freelancer: not on her own comment {r.status_code}")
dbx("UPDATE comments SET user_id=? WHERE id=?", (ALICE, FC))  # a comment of somebody else in her list (an import, a former member)
r = Fr.post(B + f"/api/comments/{FC}/reactions", json={"emoji": "heart"})
check(r.ok and rx("comment", FC) == [(FID, "heart")], f"freelancer: a reaction on another person's comment in her list {r.status_code} {r.text[:200]}")

sys.exit(kt.done("p2763_5269_reactions"))
