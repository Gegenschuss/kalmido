#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.981.0 (#5273, stage Q4b of the cross-cutting core): the comments of video / picture reviews and the notes on documents are
rows of the comments' core (obj_comments kind video / doc_note). Own container. Invented names only.
 - the old tables video_comments / doc_notes are gone; old tables made again by hand (what a version before leaves after a
   rollback) are moved at the next start: new ids, the answer keeps its comment, version / timecode / point -> anchor, done ->
   state, a comment in the trash keeps its text (obj_comment_trash), one deleted before the clean-up of #5263 is left out, a
   note keeps its sealed text, its name and its source
 - a review comment: edit with the version (an old one: 409 with the current comment; B3, was written over), done under the
   lock, delete = the core's trash with its answers (its text kept, the row empty), restore brings both back; deleting by
   someone else: who may change the review (manage) yes, who only reads no (403)
 - a document's note: delete = the core's trash (B6, was a hard DELETE), restore by its author; who only reads deletes no other
   note (403); the text stays sealed (server key)
 - the generic routes /api/obj/<kind>/<id>/comments, /api/obj/comments/<cid> (+ restore) for both kinds; the task kind keeps
   its own (404 here); a person who does not see the object gets 404
 - a person without an organisation (freelancer fixture): comments on her own review, a note on her own document
freelancer-matrix: files, videos
usage: p2981_a_comments_test.py <datadir>"""
import io
import os
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, dbx, until  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def docx(word):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:document {W_NS}><w:body>'
                   f'<w:p><w:r><w:t>Akte {word}</w:t></w:r></w:p></w:body></w:document>')
    return b.getvalue()


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


def vcom(s, vid):
    r = s.get(B + f"/api/videos/{vid}")
    return {x["id"]: x for x in (r.json().get("comments") or [])} if r.ok else {}


def upload(s, name, ws):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, docx(name.split(".")[0]), DOCX_MIME))])
    check(r.ok and r.json().get("ids"), f"setup: {name} uploaded {r.status_code} {r.text[:160]}")
    nid = r.json()["ids"][0] if r.ok and r.json().get("ids") else 0
    until(lambda: (lambda x: x.ok and x.json()["state"] in ("done", "failed"))(s.get(B + f"/api/docs/{nid}")), 90)
    return nid


kt.fresh(env={"KALMIDO_SECRET_KEY": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="}, prefix="P2981A")  # a server key: notes sealed
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
for u in ("bob", "dora", "otto"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    org_join(B, u, ORG)
Bo, Do, Ot = kt.sess("bob"), kt.sess("dora"), kt.sess("otto")
for s in (Bo, Do, Ot):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
BOB, DORA, OTTO = kt.me_id(Bo), kt.me_id(Do), kt.me_id(Ot)

# ================================================================== the tables
for t in ("video_comments", "doc_notes"):
    check(not table_there(t), f"the old table {t} is gone")

LID = A.post(B + "/api/lists", json={"name": "Schnitt", "kind": "project", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{LID}/members", json={"user_id": BOB, "role": "edit"})
A.put(B + f"/api/lists/{LID}/members", json={"user_id": OTTO, "role": "view"})
r = A.post(B + "/api/videos", json={"title": "Trailer", "url": "https://vimeo.com/123456789", "list_id": LID})
check(r.ok, f"setup: a review {r.status_code} {r.text[:160]}")
VID = r.json()["id"]
VER = r.json()["versions"][-1]["id"]

# ================================================================== a review comment: the row, edit with version (B3)
r = Bo.post(B + f"/api/videos/{VID}/comments", json={"body": "Farbe bei 12 s", "at_sec": 12})
check(r.ok, f"bob comments at 12 s {r.status_code} {r.text[:200]}")
C1 = r.json().get("comment_id")
row = dbx("SELECT kind, ref_id, org_id, user_id, anchor->>'version_id', anchor->>'t', state FROM obj_comments WHERE id=?", (C1,))
check(bool(row) and list(row[0][:5]) == ["video", VID, ORG, BOB, str(VER)] and row[0][5] in ("12", "12.0") and row[0][6] is None,
      f"kind video, the review, its organisation, the author, version and timecode in anchor, open {row}")
c1 = vcom(Bo, VID).get(C1) or {}
check(c1.get("at_sec") == 12 and c1.get("done") is False and c1.get("author") == "Bob", f"the review shows it as before {c1}")
V0 = c1.get("edited_at") or c1.get("created_at")
r = Bo.patch(B + f"/api/videos/{VID}/comments/{C1}", json={"body": "Farbe bei 12 s (v2)", "expect_updated_at": V0})
check(r.ok and (vcom(Bo, VID).get(C1) or {}).get("body") == "Farbe bei 12 s (v2)", f"the author edits with his version {r.status_code} {r.text[:200]}")
r = Bo.patch(B + f"/api/videos/{VID}/comments/{C1}", json={"body": "aus einem alten Tab", "expect_updated_at": V0})
check(r.status_code == 409 and (r.json().get("comment") or {}).get("body") == "Farbe bei 12 s (v2)",
      f"B3: an old version is refused with 409 and the current comment (was written over) {r.status_code} {r.text[:200]}")
check(dbx("SELECT body FROM obj_comments WHERE id=?", (C1,))[0][0] == "Farbe bei 12 s (v2)", "B3: nothing written by the old tab")
r = A.patch(B + f"/api/videos/{VID}/comments/{C1}", json={"body": "von alice"})
check(r.status_code == 403, f"only the author edits the text {r.status_code}")
r = A.patch(B + f"/api/videos/{VID}/comments/{C1}", json={"done": True})
check(r.ok and dbx("SELECT state FROM obj_comments WHERE id=?", (C1,))[0][0] == "done" and (vcom(A, VID).get(C1) or {}).get("done") is True,
      f"who may change the review marks it done (state done) {r.status_code}")

# ================================================================== delete = the core's trash, with its answer; who may
r = A.post(B + f"/api/videos/{VID}/comments", json={"body": "Antwort von Alice", "parent_id": C1})
check(r.ok, f"setup: an answer {r.status_code} {r.text[:160]}")
C2 = r.json().get("comment_id")
r = Ot.delete(B + f"/api/videos/{VID}/comments/{C1}")
check(r.status_code == 403 and dbx("SELECT deleted_at FROM obj_comments WHERE id=?", (C1,))[0][0] is None,
      f"who only reads the review deletes bob's comment not (403) {r.status_code}")
r = A.delete(B + f"/api/videos/{VID}/comments/{C1}")
check(r.ok, f"who may change the review (manage) deletes bob's comment {r.status_code} {r.text[:200]}")
t1 = dbx("SELECT k.body, k.deleted_by, x.body FROM obj_comments k JOIN obj_comment_trash x ON x.comment_id=k.id WHERE k.id=?", (C1,))
check(t1 and t1[0][0] == "" and t1[0][1] == ALICE and t1[0][2] == "Farbe bei 12 s (v2)",
      f"B2: the row is empty, its text waits in obj_comment_trash (gone after the trash period) {t1}")
check(dbx("SELECT deleted_at IS NOT NULL FROM obj_comments WHERE id=?", (C2,))[0][0] is True, "its answer went into the trash with it")
check(C1 not in vcom(A, VID) and C2 not in vcom(A, VID), "the review shows neither")
r = Ot.post(B + f"/api/videos/{VID}/comments/{C1}/restore")
check(r.status_code == 403, f"who only reads restores it not either {r.status_code}")
r = Bo.post(B + f"/api/videos/{VID}/comments/{C1}/restore")
cm = vcom(Bo, VID)
check(r.ok and (cm.get(C1) or {}).get("body") == "Farbe bei 12 s (v2)" and (cm.get(C2) or {}).get("body") == "Antwort von Alice",
      f"the author restores it, the answer comes back with it {r.status_code} {r.text[:200]}")
check(not dbx("SELECT 1 FROM obj_comment_trash WHERE comment_id IN (?, ?)", (C1, C2)), "the kept texts are gone after the restore")

# ================================================================== the generic routes
r = Bo.get(B + f"/api/obj/video/{VID}/comments")
check(r.ok and any(x["id"] == C1 for x in r.json().get("comments") or []), f"GET /api/obj/video/<id>/comments {r.status_code}")
r = Bo.post(B + f"/api/obj/video/{VID}/comments", json={"body": "über den Kern", "at_sec": 30})
check(r.status_code == 201 and r.json().get("comment_id"), f"POST /api/obj/video/<id>/comments {r.status_code} {r.text[:200]}")
C3 = r.json().get("comment_id")
r = Bo.patch(B + f"/api/obj/comments/{C3}", json={"done": True})
check(r.ok and dbx("SELECT state FROM obj_comments WHERE id=?", (C3,))[0][0] == "done", f"PATCH /api/obj/comments/<cid> done {r.status_code}")
r = Bo.delete(B + f"/api/obj/comments/{C3}")
check(r.ok and dbx("SELECT deleted_at IS NOT NULL FROM obj_comments WHERE id=?", (C3,))[0][0] is True, f"DELETE /api/obj/comments/<cid> {r.status_code}")
r = Bo.post(B + f"/api/obj/comments/{C3}/restore")
check(r.ok and C3 in vcom(Bo, VID), f"POST /api/obj/comments/<cid>/restore {r.status_code}")
check(Do.get(B + f"/api/obj/video/{VID}/comments").status_code == 404, "dora (no member of the project) gets 404")
check(Do.delete(B + f"/api/obj/comments/{C3}").status_code == 404, "... and cannot reach the comment either")
TID = A.post(B + "/api/tasks", json={"title": "Aufgabe", "list_id": LID}).json()["id"]
check(A.get(B + f"/api/obj/task/{TID}/comments").status_code == 404, "the task keeps its own routes (404 here)")

# ================================================================== a document's note: trash instead of DELETE (B6)
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": BOB})
check(r.ok, f"setup: an organisation of bob {r.status_code} {r.text[:120]}")
OB = r.json().get("id")
for u in ("dora", "otto"):
    Bo.put(B + f"/api/orgs/{OB}/members", json={"email": f"{u}@example.com"})
    org_join(B, u, OB)
DN = upload(Bo, "akte.docx", f"org:{OB}")
check(Bo.post(B + f"/api/files/nodes/{DN}/shares", json={"user_id": DORA, "role": "edit"}).ok, "setup: shared with dora (edit)")
check(Bo.post(B + f"/api/files/nodes/{DN}/shares", json={"user_id": OTTO, "role": "view"}).ok, "setup: shared with otto (view)")
NB = f"/api/docs/{DN}/notes"
r = Do.post(B + NB, json={"text": "Rueckruf Hummelwiese"})
check(r.status_code == 201, f"dora (edit) writes a note {r.status_code} {r.text[:160]}")
N1 = (r.json().get("note") or {}).get("id")
row = dbx("SELECT kind, ref_id, org_id, user_id, body FROM obj_comments WHERE id=?", (N1,))
check(row and list(row[0][:4]) == ["doc_note", DN, OB, DORA] and row[0][4].startswith("kenc1:"),
      f"kind doc_note, the document, its organisation, the author, the text sealed {row and list(row[0][:4])}")
check(Ot.post(B + NB, json={"text": "darf ich?"}).status_code == 403, "otto (view) writes no note")
check(Ot.delete(B + f"{NB}/{N1}").status_code == 403, "otto (view) deletes dora's note not (403)")
r = Bo.delete(B + f"{NB}/{N1}")
check(r.ok and r.json()["notes"] == [], f"bob (owner, manage) deletes dora's note {r.status_code} {r.text[:160]}")
t = dbx("SELECT k.deleted_at IS NOT NULL, k.body, x.body FROM obj_comments k JOIN obj_comment_trash x ON x.comment_id=k.id WHERE k.id=?", (N1,))
check(t and t[0][0] is True and t[0][1] == "" and t[0][2].startswith("kenc1:"),
      f"B6: the note waits in the trash (the row stays, its sealed text kept; was a hard DELETE) {t}")
r = Do.post(B + f"{NB}/{N1}/restore")
check(r.ok and [n["text"] for n in r.json()["notes"]] == ["Rueckruf Hummelwiese"], f"the author restores it with its text {r.status_code} {r.text[:160]}")
r = Do.get(B + f"/api/obj/doc_note/{DN}/comments")
check(r.ok and [n["id"] for n in r.json().get("notes") or []] == [N1], f"GET /api/obj/doc_note/<doc>/comments {r.status_code} {r.text[:120]}")
r = Do.patch(B + f"/api/obj/comments/{N1}", json={"body": "Rueckruf Hummelwiese (neu)"})
check(r.ok and [n["text"] for n in r.json().get("notes") or []] == ["Rueckruf Hummelwiese (neu)"]
      and dbx("SELECT body FROM obj_comments WHERE id=?", (N1,))[0][0].startswith("kenc1:"),
      f"the author edits a note through the core: sealed again {r.status_code} {r.text[:160]}")
check(Bo.patch(B + f"/api/obj/comments/{N1}", json={"body": "von bob"}).status_code == 403, "only its author edits a note")
check(A.get(B + f"/api/obj/doc_note/{DN}/comments").status_code == 404, "alice (no right on the document) gets 404")

# ================================================================== the move of old tables (a version before ran)
dbx("""CREATE TABLE video_comments (id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, review_id BIGINT NOT NULL, version_id BIGINT,
       org_id BIGINT, parent_id BIGINT, at_sec REAL, body TEXT NOT NULL DEFAULT '', author_id BIGINT, ext_name TEXT,
       done BIGINT NOT NULL DEFAULT 0, created_at TEXT NOT NULL, deleted_at TEXT, page BIGINT, pos_x REAL, pos_y REAL)""")
dbx("""CREATE TABLE doc_notes (id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, org_id BIGINT, ws TEXT NOT NULL, node_id BIGINT NOT NULL,
       user_id BIGINT, author TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, source TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)""")
dbx("INSERT INTO video_comments(id, review_id, version_id, org_id, at_sec, body, author_id, done, created_at) VALUES(1, ?, ?, ?, 7.5, 'Alt oben', ?, 1, '2026-11-01T08:00:00+00:00')",
    (VID, VER, ORG, BOB))
dbx("INSERT INTO video_comments(id, review_id, version_id, org_id, parent_id, body, ext_name, created_at) VALUES(2, ?, ?, ?, 1, 'Alt Antwort', 'Kundin Erika', '2026-11-01T09:00:00+00:00')",
    (VID, VER, ORG))
dbx("INSERT INTO video_comments(id, review_id, version_id, org_id, body, author_id, created_at, deleted_at) VALUES(3, ?, ?, ?, 'Alt geloescht', ?, '2026-11-01T09:00:00+00:00', '2026-11-09T10:00:00+00:00')",
    (VID, VER, ORG, BOB))
dbx("INSERT INTO video_comments(id, review_id, version_id, org_id, body, author_id, created_at, deleted_at) VALUES(4, ?, ?, ?, 'Vor dem Stichtag', ?, '2026-11-01T09:00:00+00:00', '2026-11-02T10:00:00+00:00')",
    (VID, VER, ORG, BOB))
dbx("INSERT INTO doc_notes(org_id, ws, node_id, user_id, author, text, source, created_at) VALUES(?, ?, ?, NULL, 'Paul Paperless', 'Altnotiz', 'paperless', '2026-11-01T08:00:00+00:00')",
    (OB, f"o{OB}", DN))
box("pass")  # the next start of the app
check(not table_there("video_comments") and not table_there("doc_notes"), "the start moved and dropped the old tables made again")
mv = {r[0]: r[1:] for r in dbx("""SELECT body, id, parent_id, user_id, ext_name, anchor->>'t', state, deleted_at IS NOT NULL, created_at = '2026-11-01T08:00:00+00:00'::timestamptz
                                  FROM obj_comments WHERE kind='video' AND ref_id=? AND (body LIKE 'Alt%' OR deleted_at IS NOT NULL OR body='')""", (VID,))}
top = mv.get("Alt oben")
check(top and top[2] == BOB and top[4] in ("7.5",) and top[5] == "done" and top[7] is True and top[0] not in (1, 2, 3, 4),
      f"the comment moved with a new id, author, timecode, done, its time {top}")
ans = mv.get("Alt Antwort")
check(ans and top and ans[1] == top[0] and ans[2] is None and ans[3] == "Kundin Erika", f"the answer keeps its comment and the customer's name {ans}")
gone = dbx("SELECT x.body FROM obj_comment_trash x JOIN obj_comments k ON k.id=x.comment_id WHERE k.kind='video' AND k.ref_id=? AND k.deleted_at IS NOT NULL", (VID,))
bodies = [g[0] for g in gone]
check("Alt geloescht" in bodies and "Vor dem Stichtag" not in bodies,
      f"a deleted comment keeps its text in the trash, one deleted before the clean-up of #5263 is left out {bodies}")
nt = dbx("SELECT ext_name, extra->>'source', body, user_id FROM obj_comments WHERE kind='doc_note' AND ref_id=? AND ext_name='Paul Paperless'", (DN,))
check(nt and nt[0][1] == "paperless" and nt[0][2] == "Altnotiz" and nt[0][3] is None, f"the note moved with its name and source {nt}")
r = Bo.get(B + NB)
check(r.ok and any(n["text"] == "Altnotiz" and n["author"]["name"] == "Paul Paperless" for n in r.json()["notes"]),
      f"the document shows the moved note {r.text[:200]}")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Eigenes"}).json()["id"]
r = Fr.post(B + "/api/videos", json={"title": "Eigen", "url": "https://vimeo.com/123456789", "list_id": FL})
check(r.ok, f"freelancer: a review in her own project {r.status_code} {r.text[:160]}")
FV = r.json()["id"]
r = Fr.post(B + f"/api/videos/{FV}/comments", json={"body": "Notiz", "at_sec": 2})
FC = r.json().get("comment_id") if r.ok else 0
check(r.ok and dbx("SELECT org_id FROM obj_comments WHERE id=?", (FC,))[0][0] is None, "freelancer: a comment, no organisation on the row")
fc = vcom(Fr, FV).get(FC) or {}
r = Fr.patch(B + f"/api/videos/{FV}/comments/{FC}", json={"body": "Notiz (2)", "expect_updated_at": fc.get("created_at")})
check(r.ok and (vcom(Fr, FV).get(FC) or {}).get("body") == "Notiz (2)", f"freelancer: edits it with its version {r.status_code} {r.text[:160]}")
check(Fr.delete(B + f"/api/videos/{FV}/comments/{FC}").ok and FC not in vcom(Fr, FV), "freelancer: deletes it (trash)")
check(Fr.post(B + f"/api/videos/{FV}/comments/{FC}/restore").ok and FC in vcom(Fr, FV), "freelancer: restores it")
FD = upload(Fr, "eigen.docx", "private")
r = Fr.post(B + f"/api/docs/{FD}/notes", json={"text": "Eigene Notiz"})
FN = (r.json().get("note") or {}).get("id") if r.status_code == 201 else 0
fr = dbx("SELECT kind, org_id FROM obj_comments WHERE id=?", (FN or 0,))
check(r.status_code == 201 and bool(fr) and list(fr[0]) == ["doc_note", None], f"freelancer: a note on her own document {r.status_code} {r.text[:160]} {fr}")
check(Fr.delete(B + f"/api/docs/{FD}/notes/{FN}").ok and Fr.get(B + f"/api/docs/{FD}/notes").json()["notes"] == [], "freelancer: deletes it")
r = Fr.post(B + f"/api/docs/{FD}/notes/{FN}/restore")
check(r.ok and [n["text"] for n in r.json()["notes"]] == ["Eigene Notiz"], f"freelancer: restores it {r.status_code} {r.text[:160]}")
check(A.get(B + f"/api/obj/video/{FV}/comments").status_code == 404, "freelancer: nobody else reaches her review's comments")
r = Fr.post(B + f"/api/obj/video/{FV}/comments", json={"body": "ueber den Kern", "at_sec": 4})
FK = r.json().get("comment_id") if r.status_code == 201 else 0
check(r.status_code == 201 and FK, f"freelancer: the generic route writes a comment {r.status_code} {r.text[:160]}")
check(Fr.patch(B + f"/api/obj/comments/{FK}", json={"done": True}).ok, "freelancer: the generic route marks it done")
check(Fr.delete(B + f"/api/obj/comments/{FK}").ok and Fr.post(B + f"/api/obj/comments/{FK}/restore").ok and FK in vcom(Fr, FV),
      "freelancer: the generic routes delete and restore it")
# another organisation's person reaches none of it (404: the object's read first)
check(A.post(B + f"/api/obj/video/{FV}/comments", json={"body": "fremd"}).status_code == 404, "alice writes no comment on her review")
check(A.patch(B + f"/api/obj/comments/{FK}", json={"done": False}).status_code == 404, "alice changes none")
check(A.delete(B + f"/api/obj/comments/{FK}").status_code == 404, "alice deletes none")
check(Fr.delete(B + f"/api/obj/comments/{FK}").ok and A.post(B + f"/api/obj/comments/{FK}/restore").status_code == 404, "alice restores none")
check(A.post(B + f"/api/docs/{FD}/notes/{FN}/restore").status_code == 404, "alice restores no note of hers")

sys.exit(kt.done("p2981_a_comments"))
