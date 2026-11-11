#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.972.0 (#5272, stage Q4a of the cross-cutting core): comments are rows of the core (obj_comments, core/objcomments.py).
Own container. Invented names only.
 - the old tables comments / comment_trash_text are gone; an old table made again by hand (what a version before 2.972 leaves
   after a rollback) is moved at the next start of the app: id, task, author, answer, mentions (an array), the extras
   (suggestion, buttons, portal, rule name) in extra, the times as points in time (one not in ISO form), the kept text of a
   deleted one; the comment shows in the timeline as before (same JSON, ISO time with milliseconds); new ids go on after it
 - writing: the mention of someone who does not see the task becomes '@name' and counts not; who reads the task hears of it
   (a News entry), the creator who lost the project not
 - editing: only the author; with an old version 409 and the current comment, with the right one saved
 - deleting by someone else: the project's owner (manage) yes, another editor no (403); restoring the same rule
 - a guest of the organisation (reads, may not change the task) writes no comment (403)
 - a person without an organisation (freelancer fixture) writes, edits, deletes and restores in their own project
freelancer-matrix: tasks
usage: p2903_a_comments_test.py <datadir>"""
import json
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


def news(uid, cid):
    return [r[0] for r in dbx("SELECT kind FROM notifications WHERE user_id=? AND comment_id=?", (uid, cid))]


kt.fresh(prefix="P2903A")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
for u in ("bob", "dora", "gina", "otto"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    org_join(B, u, ORG)
Bo, Do, Gi, Ot = kt.sess("bob"), kt.sess("dora"), kt.sess("gina"), kt.sess("otto")
for s in (Bo, Do, Gi, Ot):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
BOB, DORA, GINA, OTTO = kt.me_id(Bo), kt.me_id(Do), kt.me_id(Gi), kt.me_id(Ot)

# ================================================================== the tables
check(table_there("obj_comments") and table_there("obj_comment_trash"), "the core's tables exist")
for t in ("comments", "comment_trash_text"):
    check(not table_there(t), f"the old table {t} is gone")

LID = A.post(B + "/api/lists", json={"name": "Studio", "kind": "project", "org_id": ORG}).json()["id"]
for u in (BOB, DORA):
    A.put(B + f"/api/lists/{LID}/members", json={"user_id": u, "role": "edit"})
TID = A.post(B + "/api/tasks", json={"title": "Schnittplan", "list_id": LID}).json()["id"]

# ================================================================== writing: mentions only of readers, News only for readers
DT = Do.post(B + "/api/tasks", json={"title": "Tonmischung", "list_id": LID}).json()["id"]  # dora created it ...
check(A.delete(B + f"/api/lists/{LID}/members/{DORA}").ok, "setup: ... and leaves the project")
r = A.post(B + f"/api/tasks/{DT}/comments", json={"body": f"<@{BOB}> und <@{OTTO}>: bitte ansehen"})
check(r.status_code in (200, 201), f"alice comments with two mentions {r.status_code} {r.text[:200]}")
C1 = r.json()["id"]
row = dbx("SELECT body, array_to_string(mentions, ','), kind, ref_id, org_id FROM obj_comments WHERE id=?", (C1,))[0]
check(row[1] == str(BOB), f"only bob (who sees the task) counts as mentioned {row[1]}")
check(f"<@{BOB}>" in row[0] and f"<@{OTTO}>" not in row[0] and "@Otto" in row[0], f"otto's token became '@Otto' {row[0]}")
check(row[2] == "task" and row[3] == DT and row[4] == ORG, f"kind task, the task, the project's organisation {row}")
check(news(BOB, C1) == ["mention"], f"bob reads the task: his News entry {news(BOB, C1)}")
check(news(OTTO, C1) == [] and news(DORA, C1) == [], f"no News for otto (no reader) nor for dora (creator, left) {news(OTTO, C1)} {news(DORA, C1)}")
tl = A.get(B + f"/api/tasks/{DT}/timeline").json()
k = next(x for x in tl["comments"] if x["id"] == C1)
check(k["mentions"] == [BOB] and k["created_at"].endswith("+00:00") and len(k["created_at"]) == 29,
      f"the timeline: mentions, the time as ISO text with milliseconds {k['mentions']} {k['created_at']}")

A.put(B + f"/api/lists/{LID}/members", json={"user_id": DORA, "role": "edit"})  # dora is back: an editor without manage

# ================================================================== editing: the author, the version (409)
r = Bo.post(B + f"/api/tasks/{TID}/comments", json={"body": "Erster Schnitt fertig"})
check(r.status_code in (200, 201), f"setup: bob comments {r.status_code} {r.text[:200]}")
C2 = r.json()["id"]
V0 = r.json()["created_at"]
r = A.patch(B + f"/api/comments/{C2}", json={"body": "geändert von alice"})
check(r.status_code == 403, f"only the author edits {r.status_code}")
r = Bo.patch(B + f"/api/comments/{C2}", json={"body": "Erster Schnitt fertig (v2)", "expect_updated_at": V0})
check(r.ok and r.json()["body"] == "Erster Schnitt fertig (v2)" and r.json()["edited_at"], f"the author edits with his version {r.status_code} {r.text[:200]}")
r = Bo.patch(B + f"/api/comments/{C2}", json={"body": "aus einem alten Tab", "expect_updated_at": V0})
check(r.status_code == 409 and r.json().get("comment", {}).get("body") == "Erster Schnitt fertig (v2)",
      f"an old version: 409 with the current comment {r.status_code} {r.text[:200]}")
check(dbx("SELECT body FROM obj_comments WHERE id=?", (C2,))[0][0] == "Erster Schnitt fertig (v2)", "nothing written by the old tab")

# ================================================================== deleting by someone else: author or manage
r = Do.delete(B + f"/api/comments/{C2}")
check(r.status_code == 403, f"another editor may not delete bob's comment {r.status_code}")
r = A.delete(B + f"/api/comments/{C2}")
check(r.ok, f"the project's owner (manage) deletes bob's comment {r.status_code} {r.text[:200]}")
tr_ = dbx("SELECT body FROM obj_comment_trash WHERE comment_id=?", (C2,))
check(tr_ and tr_[0][0] == "Erster Schnitt fertig (v2)", f"its text waits in obj_comment_trash {tr_}")
row = dbx("SELECT body, deleted_at, deleted_by FROM obj_comments WHERE id=?", (C2,))[0]
check(row[0] == "" and row[1] and row[2] == ALICE, f"the row looks deleted, deleted_by alice {row}")
check(not any(x["id"] == C2 for x in Bo.get(B + f"/api/tasks/{TID}/timeline").json()["comments"]), "the timeline does not show it")
r = Do.post(B + f"/api/comments/{C2}/restore")
check(r.status_code == 403, f"another editor may not restore it either {r.status_code}")
r = Bo.post(B + f"/api/comments/{C2}/restore")
check(r.ok, f"the author restores it {r.status_code} {r.text[:200]}")
check(any(x["id"] == C2 and x["body"] == "Erster Schnitt fertig (v2)" for x in Bo.get(B + f"/api/tasks/{TID}/timeline").json()["comments"]),
      "back with its text")
check(not dbx("SELECT 1 FROM obj_comment_trash WHERE comment_id=?", (C2,)), "the kept text is gone after the restore")

# ================================================================== a guest reads, says nothing
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": GINA, "role": "guest"}).ok, "setup: gina becomes a guest")
A.put(B + f"/api/lists/{LID}/members", json={"user_id": GINA, "role": "view"})
check(Gi.get(B + f"/api/tasks/{TID}/timeline").ok, "the guest reads the comments")
n0 = dbx("SELECT COUNT(*) FROM obj_comments WHERE ref_id=?", (TID,))[0][0]
r = Gi.post(B + f"/api/tasks/{TID}/comments", json={"body": "Darf ich?"})
check(r.status_code == 403 and dbx("SELECT COUNT(*) FROM obj_comments WHERE ref_id=?", (TID,))[0][0] == n0,
      f"a guest writes no comment (403) {r.status_code} {r.text[:200]}")

# ================================================================== the move of an old table (a version before 2.972 ran)
OLD_ID = 900001
dbx("""CREATE TABLE comments (id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, task_id BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
       user_id BIGINT REFERENCES users(id) ON DELETE SET NULL, body TEXT NOT NULL DEFAULT '', mentions TEXT NOT NULL DEFAULT '',
       created_at TEXT NOT NULL, edited_at TEXT, deleted_at TEXT, suggestion TEXT, reply_to BIGINT, choices JSONB, choice JSONB,
       ext_name TEXT, portal BIGINT NOT NULL DEFAULT 0, rule_name TEXT, client_ref TEXT, org_id BIGINT)""")
dbx("CREATE TABLE comment_trash_text (comment_id BIGINT PRIMARY KEY REFERENCES comments(id) ON DELETE CASCADE, body TEXT NOT NULL DEFAULT '', mentions TEXT NOT NULL DEFAULT '')")
SUG = json.dumps({"kind": "tidy", "state": "open", "title": "Neuer Titel"})
dbx("""INSERT INTO comments(id, task_id, user_id, body, mentions, created_at, edited_at, suggestion, reply_to, choices, portal, rule_name, client_ref)
       VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)""",
    (OLD_ID, TID, BOB, f"<@{ALICE}> alt", f"{ALICE}", "2026-11-01T08:30:00.123+00:00", "not a time", SUG, C2,
     json.dumps({"choices": [{"id": "a", "label": "A", "note": None}]}), "Regel 1", "ref-1"))
dbx("INSERT INTO comments(id, task_id, user_id, body, mentions, created_at, deleted_at) VALUES(?,?,?,'','',?,?)",
    (OLD_ID + 1, TID, BOB, "2026-11-01T09:00:00.000+00:00", "2026-11-02T10:00:00.000+00:00"))
dbx("INSERT INTO comment_trash_text(comment_id, body, mentions) VALUES(?,?,?)", (OLD_ID + 1, f"aufbewahrt <@{ALICE}>", f"{ALICE}"))
box("pass")  # the next start of the app
check(not table_there("comments") and not table_there("comment_trash_text"), "the start dropped the old tables made again")
m = dbx("""SELECT kind, ref_id, user_id, parent_id, array_to_string(mentions, ','), extra->>'suggestion', extra->'choices'->'choices'->0->>'id',
                  (extra->>'portal')::boolean, extra->>'rule_name', client_ref, created_at = '2026-11-01T08:30:00.123+00:00'::timestamptz,
                  edited_at IS NULL, org_id, jsonb_typeof(extra->'choices'->'choices'->0->'note') = 'null'
           FROM obj_comments WHERE id=?""", (OLD_ID,))
check(m, "the old row moved with its id")
if m:
    m = list(m[0])
    check(m[:4] == ["task", TID, BOB, C2], f"kind, task, author, answer {m[:4]}")
    check(m[4] == str(ALICE), f"the mentions as an array {m[4]}")
    check(m[5] == SUG and m[6] == "a" and m[7] is True and m[8] == "Regel 1" and m[9] == "ref-1",
          f"suggestion (its JSON text), buttons, portal, rule name, client_ref in place {m[5:10]}")
    check(m[10] is True and m[11] is True, f"created_at as a point in time, the edited_at that was no time is empty {m[10:12]}")
    check(m[12] == ORG and m[13] is True, f"the organisation filled, a null inside the buttons kept {m[12:]}")
t2 = dbx("SELECT k.deleted_at IS NOT NULL, x.body, array_to_string(x.mentions, ',') FROM obj_comments k JOIN obj_comment_trash x ON x.comment_id=k.id WHERE k.id=?", (OLD_ID + 1,))
check(t2 and t2[0][0] is True and t2[0][1] == f"aufbewahrt <@{ALICE}>" and t2[0][2] == str(ALICE),
      f"the deleted one with its kept text {t2}")
tl = A.get(B + f"/api/tasks/{TID}/timeline").json()
k = next((x for x in tl["comments"] if x["id"] == OLD_ID), None)
check(k is not None and k["created_at"] == "2026-11-01T08:30:00.123+00:00" and k["reply_to"] == C2 and k["portal"] is True
      and k["rule_name"] == "Regel 1" and (k["suggestion"] or {}).get("title") == "Neuer Titel" and k["mentions"] == [ALICE],
      f"the moved comment in the timeline as before {k}")
r = Bo.post(B + f"/api/comments/{OLD_ID + 1}/restore")
check(r.ok and any(x["id"] == OLD_ID + 1 and x["body"] == f"aufbewahrt <@{ALICE}>" for x in A.get(B + f"/api/tasks/{TID}/timeline").json()["comments"]),
      f"the moved trash text restores {r.status_code} {r.text[:200]}")
r = A.post(B + f"/api/tasks/{TID}/comments", json={"body": "nach dem Umzug"})
check(r.status_code in (200, 201) and r.json()["id"] > OLD_ID + 1, f"new ids go on after the moved ones {r.text[:120]}")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Eigenes"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Angebot schreiben", "list_id": FL}).json()["id"]
r = Fr.post(B + f"/api/tasks/{FT}/comments", json={"body": "Notiz"})
check(r.status_code in (200, 201), f"freelancer: a comment in her own project {r.status_code} {r.text[:200]}")
FC = r.json()["id"]
check(dbx("SELECT org_id FROM obj_comments WHERE id=?", (FC,))[0][0] is None, "freelancer: no organisation on the row")
r = Fr.patch(B + f"/api/comments/{FC}", json={"body": "Notiz (2)", "expect_updated_at": r.json()["created_at"]})
check(r.ok and r.json()["body"] == "Notiz (2)", f"freelancer: edits it {r.status_code} {r.text[:200]}")
check(Fr.delete(B + f"/api/comments/{FC}").ok and not Fr.get(B + f"/api/tasks/{FT}/timeline").json()["comments"], "freelancer: deletes it")
check(Fr.post(B + f"/api/comments/{FC}/restore").ok and Fr.get(B + f"/api/tasks/{FT}/timeline").json()["comments"][0]["body"] == "Notiz (2)",
      "freelancer: restores it")
check(A.get(B + f"/api/tasks/{FT}/timeline").status_code in (403, 404), "nobody else reads her comments")

sys.exit(kt.done("p2903_a_comments"))
