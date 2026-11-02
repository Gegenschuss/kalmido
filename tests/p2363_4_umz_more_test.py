#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.363.4 (#3127): the account import takes over the rest of the person's own content. Invented names only (example.com).
A crafted account export (old account id 1000) into a person without an organisation (freelancer_fixture):
 - the preview no longer names mails, video sign-offs, bookmarks, focus sessions, notepads, playbooks, staying in touch,
   saved arrangements or task bells as staying behind; a notepad on a project of somebody else and a folder's playbook are
   named (they stay)
 - after the run: the filed mail with its .eml and attachment in the private space (sealed fields, its files point at it),
   the video sign-off with version and comment, the notepad and the playbook on the new project, the bookmark (the same link
   saved here already is not doubled), the finished focus session (a running one stays behind), staying in touch with the
   new contact, the saved arrangement of the project page under the new project id, the project page's arrangement, my bell
   and my follow on the task (a bell somebody else set stays behind)
 - the settings of the allow list move (week start, start page), sign-in / push settings never (push_priority stays)
 - the undo takes every one of them away again, the bookmark saved before stays
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P23634_NOSTART=1 = the server already runs like that).
freelancer-matrix: own
usage: p2363_4_umz_more_test.py <datadir>"""
import base64
import hashlib
import io
import json
import os
import sys
import zipfile

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
EML = b"From: a@example.com\r\nTo: b@example.com\r\nSubject: Umzug Mail\r\n\r\nHallo " + os.urandom(6).hex().encode() + b"\r\n"
TS = "2026-10-20T06:00:00Z"
ME = 1000


def sha(b):
    return hashlib.sha256(b).hexdigest()


def mkzip(tables, blobs):
    entries = {f"data/{t}.json": json.dumps(rows).encode() for t, rows in tables.items()}
    entries.update(blobs)
    flist = [{"path": p, "size": len(b), "sha256": sha(b)} for p, b in entries.items()]
    m = {"format": "kalmido-account", "v": 1, "kalmido_version": "test", "created_at": TS,
         "source": {"url": "https://example.com", "hosted": True}, "user": {"id": ME, "name": "Test Person", "email": "test@example.com"},
         "tables": {}, "files": flist, "client_encrypted": {}, "export_id": os.urandom(16).hex()}
    mb = json.dumps(m).encode()
    cs = f"{sha(mb)}  manifest.json\n" + "".join(f"{f['sha256']}  {f['path']}\n" for f in flist)
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", mb)
        z.writestr("checksum.sha256", cs.encode())
        for p, b in entries.items():
            z.writestr(p, b)
    return bio.getvalue()


def state_of(s, iid):
    j = s.get(B + f"/api/account/import/{iid}").json()
    return j if j.get("state") not in ("checking", "running", "upload") else None


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "kalmido-account.zip"})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid, until(lambda: state_of(s, iid), 180) or {}


def one(sql, args=()):
    r = kt.dbx(sql, args)
    return r[0][0] if r else None


EMLF, PDFF = "files/private_files/70-mail.eml", "files/private_files/71-plan.pdf"
FILE = mkzip({
    "lists": [{"id": 1, "name": "Umzug Projekt", "created_at": TS}],
    "tasks": [{"id": 11, "list_id": 1, "title": "Umzug Aufgabe", "created_at": TS, "updated_at": TS},
              {"id": 12, "list_id": 1, "title": "Fremde Glocke", "created_at": TS, "updated_at": TS}],
    "address_books": [{"id": 21, "name": "Umzug Adressen", "created_at": TS}],
    "contacts": [{"id": 22, "book_id": 21, "uid": "umzug-kontakt", "fn": "Erika Beispiel", "created_at": TS, "updated_at": TS}],
    "settings": [{"key": "week_start", "value": "sun"}, {"key": "start_page", "value": "today"}, {"key": "push_priority", "value": "5"}],
    "bookmarks": [{"url": "https://example.com/umzug-neu", "title": "Neu", "tags": "[\"umzug\"]", "state": "read", "created_at": TS},
                  {"url": "https://example.com/doppelt", "title": "Doppelt", "created_at": TS}],
    "pomos": [{"id": 81, "task_id": 11, "kind": "focus", "minutes": 25, "start": "2026-10-19T08:00:00Z", "end": "2026-10-19T08:25:00Z", "done": 1},
              {"id": 82, "task_id": 11, "kind": "focus", "minutes": 25, "start": "2026-10-19T09:00:00Z", "done": 0}],
    "contact_care": [{"contact_id": 22, "every_days": 30, "last": "2026-10-01", "note": "anrufen", "updated_at": TS}],
    "view_layouts": [{"id": 91, "view_key": "list:1", "name": "Fokus", "layout": "", "pos": 1, "created_at": TS, "updated_at": TS}],
    "list_layouts": [{"list_id": 1, "layout": "", "updated_at": TS}],
    "task_bell": [{"task_id": 11, "level": "urgent", "set_by": ME, "created_at": TS, "updated_at": TS},
                  {"task_id": 12, "level": "urgent", "set_by": 2000, "created_at": TS, "updated_at": TS}],
    "task_watchers": [{"task_id": 11, "created_at": TS}],
    "list_notepads": [{"id": 31, "list_id": 1, "title": "Umzug Notiz", "body": "Kartons", "created_by": ME, "created_at": TS, "updated_at": TS},
                      {"id": 32, "list_id": 99, "title": "Fremde Notiz", "body": "x", "created_by": ME, "created_at": TS, "updated_at": TS}],
    "playbooks": [{"id": 41, "list_id": 1, "version": 1, "body": "Umzug Playbook", "created_at": TS},
                  {"id": 42, "list_id": None, "owner_id": ME, "folder": "Kunden", "version": 1, "body": "Ordner", "created_at": TS}],
    "video_reviews": [{"id": 51, "title": "Umzug Video", "state": "open", "list_id": 1, "owner_id": ME, "created_at": TS, "updated_at": TS}],
    "video_versions": [{"id": 52, "review_id": 51, "n": 1, "url": "https://vimeo.com/76979871", "created_by": ME, "created_at": TS}],
    "video_comments": [{"id": 53, "review_id": 51, "version_id": 52, "at_sec": 3.5, "body": "Schnitt", "author_id": ME, "created_at": TS}],
    "hub_mails": [{"id": 61, "list_id": 1, "message_id": "<umzug@example.com>", "from_addr": "a@example.com", "subject": "Umzug Mail",
                   "body": "Hallo", "created_at": TS, "eml_file": EMLF, "attachment_files": [PDFF]}],
    "private_files": [{"id": 70, "kind": "file", "name": "mail.eml", "mime": "message/rfc822", "size": len(EML), "cur_version": 1,
                       "hub_mail_id": 61, "file": EMLF, "created_at": TS, "updated_at": TS},
                      {"id": 71, "kind": "file", "name": "plan.pdf", "mime": "application/pdf", "size": len(PDF), "cur_version": 1,
                       "hub_mail_id": 61, "file": PDFF, "created_at": TS, "updated_at": TS}],
}, {EMLF: EML, PDFF: PDF})

kt.fresh(env={"KALMIDO_SECRET_KEY": KEY}, prefix="P23634")
A = kt.setup()
GID, Gi = freelancer(B, A, "gina")  # the target account, without an organisation
r = Gi.post(B + "/api/bookmarks", json={"url": "https://example.com/doppelt"})
check(r.ok, f"a bookmark saved before {r.status_code} {r.text[:120]}")
BEFORE = one("SELECT id FROM bookmarks WHERE user_id=? AND deleted_at IS NULL", (GID,))
PUSH = (Gi.get(B + "/api/state").json().get("settings") or {}).get("push_priority")

iid, j = upload(Gi, FILE)
check(j.get("state") == "preview", f"preview {j.get('state')} {j.get('error')}")
nt = {x.get("what"): x.get("count") for x in (j.get("preview") or {}).get("not_taken") or []}
gone = {"E-mails", "Video sign-offs", "Bookmarks", "Focus sessions", "Staying in touch", "Saved arrangements", "Task bells"} & set(nt)
check(not gone, f"#3127 the preview no longer names them as staying behind {gone}")
check(nt.get("Notepads") == 1 and nt.get("Playbooks") == 1, f"#3127 ... but the notepad of another project and the folder's playbook {nt}")
r = Gi.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}})
check(r.status_code == 202, f"the run starts {r.status_code} {r.text[:200]}")
j = until(lambda: state_of(Gi, iid), 180) or {}
check(j.get("state") == "done", f"the import is done {j.get('state')} {j.get('error')}")
RES = j.get("result") or {}
IMP = RES.get("import_id")
WARN = json.dumps(RES.get("warnings"), ensure_ascii=False)[:600]
LID = one("SELECT id FROM lists WHERE owner_id=? AND name='Umzug Projekt' AND deleted_at IS NULL", (GID,))
TID = one("SELECT id FROM tasks WHERE list_id=? AND title='Umzug Aufgabe'", (LID or 0,))
check(LID and TID, f"the project and its task arrive {LID} {TID} {WARN}")

# mail with its files
m = kt.dbx("SELECT id, owner_id, org_id, list_id, eml_id, files, subject, ws FROM hub_mails WHERE owner_id=? AND deleted_at IS NULL", (GID,))
check(len(m) == 1, f"#3127 the filed mail arrives {m} {WARN}")
MID = m[0][0] if m else 0
if m:
    check(m[0][2] is None and m[0][3] == LID, f"#3127 ... in the private space, on the new project {m[0][2:4]}")
    check(m[0][6] != "Umzug Mail" and str(m[0][6]).startswith("kenc1:"), f"#3127 ... its subject sealed with the account key {str(m[0][6])[:12]}")
    att = json.loads(m[0][5] or "[]")
    check(m[0][4] and len(att) == 1, f"#3127 ... its .eml and its attachment point at the new nodes {m[0][4]} {att}")
    nodes = kt.dbx("SELECT id, name, hub_mail_id FROM fs_nodes WHERE owner_id=? AND org_id IS NULL AND deleted_at IS NULL AND kind='file'", (GID,))
    check(sorted(n[1] for n in nodes) == ["mail.eml", "plan.pdf"] and all(n[2] == MID for n in nodes),
          f"#3127 the mail's files arrive with the mail's mark {nodes}")
    r = Gi.get(B + f"/api/hubmail/mails/{MID}")
    check(r.ok and "Umzug Mail" in r.text, f"#3127 the mail opens with its subject {r.status_code} {r.text[:200]}")
# video sign-off
v = kt.dbx("SELECT id, owner_id, org_id, list_id FROM video_reviews WHERE owner_id=? AND deleted_at IS NULL", (GID,))
check(len(v) == 1 and v[0][2] is None and v[0][3] == LID, f"#3127 the video sign-off arrives on the new project {v}")
VID = v[0][0] if v else 0
check(one("SELECT COUNT(*) FROM video_versions WHERE review_id=? AND provider='vimeo'", (VID,)) == 1
      and one("SELECT author_id FROM video_comments WHERE review_id=? AND body='Schnitt'", (VID,)) == GID,
      "#3127 ... with its version and my comment")
# notepad, playbook
check(one("SELECT COUNT(*) FROM list_notepads WHERE list_id=? AND title='Umzug Notiz'", (LID or 0,)) == 1
      and one("SELECT COUNT(*) FROM list_notepads WHERE title='Fremde Notiz'") == 0, "#3127 the notepad of my project arrives, the other one not")
check(one("SELECT COUNT(*) FROM playbooks WHERE list_id=? AND body='Umzug Playbook'", (LID or 0,)) == 1
      and one("SELECT COUNT(*) FROM playbooks WHERE body='Ordner'") == 0, "#3127 the project's playbook arrives, the folder's not")
# bookmarks
bm = kt.dbx("SELECT url_key, state, preview FROM bookmarks WHERE user_id=? AND deleted_at IS NULL ORDER BY id", (GID,))
check(len(bm) == 2 and bm[1][0].endswith("example.com/umzug-neu") and bm[1][1] == "read" and bm[1][2] == "pending",
      f"#3127 the new bookmark arrives (its preview fetched again), the same link is not doubled {bm}")
# focus session, staying in touch, arrangements, bells
check(one("SELECT COUNT(*) FROM pomos WHERE user_id=?", (GID,)) == 1 and one("SELECT task_id FROM pomos WHERE user_id=?", (GID,)) == TID,
      "#3127 the finished focus session arrives on the new task, the running one not")
CID = one("SELECT c.id FROM contacts c JOIN books b ON b.id=c.book_id WHERE b.owner_id=? AND c.fn='Erika Beispiel'", (GID,))
check(CID and one("SELECT every_days FROM contact_care WHERE user_id=? AND contact_id=?", (GID, CID)) == 30, "#3127 staying in touch with the new contact")
check(one("SELECT COUNT(*) FROM view_layouts WHERE user_id=? AND view_key=? AND name='Fokus'", (GID, f"list:{LID}")) == 1,
      "#3127 the saved arrangement of the project page under the new project id")
check(one("SELECT COUNT(*) FROM list_layouts WHERE user_id=? AND list_id=?", (GID, LID or 0)) == 1, "#3127 the project page's arrangement")
check(one("SELECT level FROM task_bell WHERE user_id=? AND task_id=?", (GID, TID or 0)) == "urgent"
      and one("SELECT COUNT(*) FROM task_bell WHERE user_id=?", (GID,)) == 1, "#3127 my bell arrives, the one somebody else set not")
check(one("SELECT COUNT(*) FROM task_watchers WHERE user_id=? AND task_id=?", (GID, TID or 0)) == 1, "#3127 I follow the new task")
# settings
st = Gi.get(B + "/api/state").json().get("settings") or {}
check(st.get("week_start") == "sun" and st.get("start_page") == "today", f"#3127 the allowed settings move {st.get('week_start')} {st.get('start_page')}")
check(st.get("push_priority") == PUSH, f"#3127 a push setting never moves {st.get('push_priority')} {PUSH}")

# the undo
check(IMP and Gi.post(B + f"/api/imports/{IMP}/undo", json={}).ok, "the undo")
left = {t: one(f"SELECT COUNT(*) FROM {t} WHERE {col}=?", (GID,)) for t, col in (
    ("hub_mails", "owner_id"), ("video_reviews", "owner_id"), ("pomos", "user_id"), ("contact_care", "user_id"), ("view_layouts", "user_id"),
    ("list_layouts", "user_id"), ("task_bell", "user_id"), ("task_watchers", "user_id"))}
check(not any(left.values()), f"#3127 the undo takes them away again {left}")
check(one("SELECT COUNT(*) FROM list_notepads WHERE title='Umzug Notiz'") == 0 and one("SELECT COUNT(*) FROM playbooks WHERE body='Umzug Playbook'") == 0,
      "#3127 ... the notepad and the playbook too")
check([r[0] for r in kt.dbx("SELECT id FROM bookmarks WHERE user_id=? AND deleted_at IS NULL", (GID,))] == [BEFORE],
      "#3127 ... the imported bookmark too, the one saved before stays")
st = Gi.get(B + "/api/state").json().get("settings") or {}
check(st.get("week_start") != "sun" and st.get("start_page") != "today", f"#3127 ... and the settings come back {st.get('week_start')} {st.get('start_page')}")

sys.exit(kt.done("p2363_4_umz_more"))
