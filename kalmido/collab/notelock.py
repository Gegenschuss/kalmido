"""2.48.0 (#1642): lock the note of a task with one's own password (end-to-end, built on collab/e2e.py).

The browser encrypts the task's note (tasks.content) with the person's content key of the end-to-end key bundle
(passphrase + recovery code, see e2e.py), AES-256-GCM, AAD "kalmido-locknote:v1:<task_id>:<user_id>", and stores only the
ciphertext here (task_note_locks); tasks.content is emptied in the same step. Password and recovery code lost = the note is
lost: nobody can restore it, not even the operator.

- Locking only in an own list that is not shared: its owner, no people / groups as members, no shared list folder, not
  opened to the whole organisation (agents may be on the list: they never read a locked note).
- Title, dates and list stay readable; only the note is locked. Everything that reads tasks.content (search, agents, API,
  exports, CalDAV / iCal, public links, templates, webhooks, mail) sees an empty note and the flag note_locked.
- Nothing may change a locked note except its owner through these routes: a write of the note (app, API, agents,
  CalDAV, proposals) is refused (409) or, for CalDAV, ignored.
- Locking removes what the history kept of the old text (the "Restore the description" entry of #1409).
- Unlocking for good writes the plain text back (sent by the browser) and drops the lock.

Endpoints only for the signed-in person (agent accounts: 403)."""
import json

from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso_ms, now_utc
from ..core.access import Denied, need_task, ov_open
from ..tasks.validation import CONTENT_MAX, log_act
from .e2e import E2E_NOTE_MAX, e2e_blob, e2e_has_keys, e2e_person


def ln_msg():
    return tr("This note is locked with a password. It cannot be read or changed here.")


def ln_locked_ids(c, ids):
    """{task_id: locker user id} of the tasks in ids that carry a locked note."""
    out = {}
    ids = list(ids or [])
    for i in range(0, len(ids), 5000):
        part = ids[i:i + 5000]
        for r in c.execute(f"SELECT task_id, user_id FROM task_note_locks WHERE task_id IN ({','.join('?' * len(part))})", part):
            out[r[0]] = r[1]
    return out


def ln_is_locked(c, tid):
    return c.execute("SELECT 1 FROM task_note_locks WHERE task_id=?", (tid,)).fetchone() is not None


def ln_list_problem(c, lid, uid):
    """Why the note of a task in list lid cannot be locked by uid (a text), or None: only an own list that is not shared."""
    r = c.execute("SELECT owner_id, folder, org_id, life, family, org_visibility FROM lists WHERE id=?", (lid,)).fetchone() if lid else None
    if not r or r["owner_id"] != uid:
        return tr("Notes can only be locked in your own lists.")
    people = c.execute("""SELECT 1 FROM list_members m JOIN users u ON u.id=m.user_id
                          WHERE m.list_id=? AND m.user_id<>? AND COALESCE(u.kind, '')<>'agent' LIMIT 1""", (lid, uid)).fetchone()
    groups = c.execute("SELECT 1 FROM group_shares WHERE list_id=? LIMIT 1", (lid,)).fetchone()
    folder = (r["folder"] or "") and c.execute("SELECT 1 FROM folder_people WHERE owner_id=? AND folder=? LIMIT 1",
                                                (uid, r["folder"])).fetchone()
    if people or groups or folder or ov_open(r):
        return tr("Notes can only be locked in lists that are not shared.")
    return None


def ln_guard(c, tid, f):
    """apply_update / PATCH: the error text when the change f writes the note of a task whose note is locked, else None
    (an empty note is what a locked task has: sending it back unchanged is no change)."""
    if (f.get("content") or "") != "" and ln_is_locked(c, tid):
        return ln_msg()
    return None


def _ln_task(c, tid):
    uid = e2e_person()
    need_task(c, tid, write=True, full=True)
    if c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()[0]:
        raise Denied(404)
    return uid


def _ln_mine(c, tid, uid):
    r = c.execute("SELECT user_id, body, updated_at FROM task_note_locks WHERE task_id=?", (tid,)).fetchone()
    if r and r["user_id"] != uid:
        raise Denied(403, ln_msg())
    return r


def ln_forget_text(c, tid):
    """What the history kept of the note's text goes (the md_subtasks entry holds the text before, #1409)."""
    c.execute("DELETE FROM activity WHERE task_id=? AND kind='md_subtasks'", (tid,))


@app.get("/api/tasks/<int:tid>/note-lock")
def ln_get(tid):
    """{body: {v, iv, ct}, updated_at} -- the locked note of the task, only for the person who locked it (404: not locked)."""
    c = db()
    uid = e2e_person()
    need_task(c, tid, write=False, full=True)
    r = _ln_mine(c, tid, uid)
    if not r:
        raise Denied(404)
    return jsonify(task_id=tid, body=json.loads(r["body"]), updated_at=r["updated_at"])


@app.put("/api/tasks/<int:tid>/note-lock")
def ln_put(tid):
    """{body: {v, iv, ct}} -- lock the note (the browser sends it encrypted; the plain note is emptied here) or save the changed
    locked note. Locking needs my keys and an own list that is not shared."""
    c = db()
    uid = _ln_task(c, tid)
    if not e2e_has_keys(c, uid):
        return err(tr("Set up end-to-end encryption first (Settings > Account)."), 409)
    enc = e2e_blob(body().get("body"), E2E_NOTE_MAX)
    if not enc:
        return err(tr("Invalid value: {0}", "body"))
    old = _ln_mine(c, tid, uid)
    if not old:
        e = ln_list_problem(c, c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()[0], uid)
        if e:
            return err(e, 409)
    ts = iso_ms(now_utc())
    c.execute("INSERT INTO task_note_locks(task_id,user_id,body,updated_at) VALUES(?,?,?,?) ON CONFLICT(task_id) "
              "DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at", (tid, uid, enc, ts))
    if not old:
        # the plain note goes in the same transaction; the history says only "locked" (never the text)
        c.execute("UPDATE tasks SET content='', updated_at=? WHERE id=?", (ts, tid))
        ln_forget_text(c, tid)
        log_act(c, tid, "note_lock")
    bump(c)
    c.commit()
    return jsonify(ok=True, task_id=tid, locked=True, updated_at=ts)


@app.delete("/api/tasks/<int:tid>/note-lock")
def ln_delete(tid):
    """{content} -- unlock the note for good: the browser sends the decrypted text, it becomes the task's note again.
    Without content (the note could not be decrypted any more) the locked note is deleted."""
    c = db()
    uid = _ln_task(c, tid)
    if not _ln_mine(c, tid, uid):
        raise Denied(404)
    text = body().get("content")
    text = text if isinstance(text, str) else ""
    if len(text) > CONTENT_MAX:
        return err(tr("Invalid value: {0}", "content"))
    ts = iso_ms(now_utc())
    c.execute("DELETE FROM task_note_locks WHERE task_id=?", (tid,))
    c.execute("UPDATE tasks SET content=?, updated_at=? WHERE id=?", (text, ts, tid))
    log_act(c, tid, "note_unlock")
    bump(c)
    c.commit()
    return jsonify(ok=True, task_id=tid, locked=False)
