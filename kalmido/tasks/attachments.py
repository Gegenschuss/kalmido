"""Files of tasks (upload, download, delete)."""
import mimetypes
import os
import re
import uuid
from flask import g, has_request_context, jsonify, request, send_file

from ..core.config import app, ATT_DIR, INLINE_TYPES, MAX_FILE_MB
from ..core.i18n import tr
from ..core.db import bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, MANAGE_ROLES, need_task
from ..core.serializers import unlink_files
from ..tasks.validation import log_act
from ..tasks.tasks import one_task


# ---------------------------------------------------------------- attachments

def safe_name(n):
    n = os.path.basename((n or "").replace("\\", "/")).strip()
    n = re.sub(r"[\x00-\x1f/\\:*?\"<>|]", "_", n)[:150]
    return n or "datei"


@app.post("/api/tasks/<int:tid>/attachments")
def attachment_upload(tid):
    c = db()
    need_task(c, tid)
    files = request.files.getlist("file")
    if not files:
        return err(tr("File missing"))
    saved = []
    e = save_attachments(c, tid, files, saved=saved)
    if e:
        c.rollback()
        unlink_files(saved)
        return err(e)
    log_act(c, tid, "attach", {"names": [safe_name(f.filename) for f in files][:20], "n": len(files)})
    bump(c)
    c.commit()
    return jsonify(one_task(c, tid))


def save_attachments(c, tid, files, comment_id=None, saved=None, uid=None):
    """Store uploaded werkzeug files for a task (or one of its comments). Returns an error message or
    None (caller commits; on an error the caller rolls back and unlinks `saved`)."""
    from ..notify.alerts import aa_count, aa_oserr
    from ..admin.hosting import quota_guard
    if uid is None:  # the uploader: the signed-in person (/drop passes the token's owner)
        uid = g.user["id"] if has_request_context() and g.get("user") else None
    quota_guard(c, uid)  # 2.24.0 (#910): refused before anything is written (413 quota_exceeded)
    try:
        os.makedirs(os.path.join(ATT_DIR, str(tid)), exist_ok=True)
    except OSError as e:
        aa_count("storage", "attachments", aa_oserr(e))
        raise
    ts = iso(now_utc())
    for f in files:
        name = safe_name(f.filename)
        rel = os.path.join(str(tid), f"{uuid.uuid4().hex[:12]}-{name}")
        full = os.path.join(ATT_DIR, rel)
        try:
            f.save(full)
        except OSError as e:
            aa_count("storage", "attachments", aa_oserr(e))
            raise
        size = os.path.getsize(full)
        if size > MAX_FILE_MB * 1024 * 1024:
            os.remove(full)
            return tr("{0}: larger than {1} MB", name, MAX_FILE_MB)
        if not size:  # 2.13.2 (#478 N6): a 0-byte file is refused (it would only show up as a broken file)
            os.remove(full)
            return tr("{0}: the file is empty and was not uploaded", name)
        if saved is not None:
            saved.append(rel)
        mime = (f.mimetype if f.mimetype and f.mimetype != "application/octet-stream" else None) \
            or mimetypes.guess_type(name)[0] or "application/octet-stream"
        c.execute("INSERT INTO attachments(task_id,name,mime,size,path,created_at,comment_id,user_id) VALUES(?,?,?,?,?,?,?,?)",
                  (tid, name, mime, size, rel, ts, comment_id, uid))
    if comment_id is None:
        c.execute("UPDATE tasks SET updated_at=? WHERE id=?", (ts, tid))
    return None


def need_attachment(c, aid, write):
    """Task files: read = sees the task, write = may change it. Comment files: read = sees the task
    (and the comment is not deleted), write = the comment's author (or the list owner, moderation)."""
    a = c.execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
    if not a:
        raise Denied(404)
    if a["comment_id"] is None:
        need_task(c, a["task_id"], write, full=True)
        return a
    role = need_task(c, a["task_id"], write=False, full=True)
    cm = c.execute("SELECT user_id, deleted_at FROM comments WHERE id=?", (a["comment_id"],)).fetchone()
    if not cm or cm["deleted_at"]:
        raise Denied(404)
    if write and cm["user_id"] != me() and role not in MANAGE_ROLES:
        raise Denied(403)
    return a


@app.get("/api/attachments/<int:aid>")
def attachment_get(aid):
    return send_stored(need_attachment(db(), aid, False))


def send_stored(a):
    """A stored file (row with id, path, name, mime, size: task / comment attachments, 2.13.1 chat files) for the browser or an
    API client: images / pdf / text inline (?dl=1: download) in a sandbox CSP, a damaged file as 410, versioned caching."""
    full = os.path.join(ATT_DIR, a["path"])
    if not os.path.isfile(full) or (a["size"] and os.path.getsize(full) != a["size"]):  # 2.13.0: also empty / cut off
        if os.path.isfile(full):
            print(f"WARNING file {a['id']}: {os.path.getsize(full)} bytes on disk, {a['size']} recorded", flush=True)
        e = err(tr("File damaged or missing"), 410 if os.path.isfile(full) else 404)
        e[0].headers["Cache-Control"] = "no-store"  # never cache a broken answer
        return e
    inline = a["mime"] in INLINE_TYPES and request.args.get("dl") != "1"
    resp = send_file(full, mimetype=a["mime"] if inline else "application/octet-stream",
                     as_attachment=not inline, download_name=a["name"], conditional=True, max_age=0)
    if a["mime"] != "application/pdf":  # the browser pdf viewer does not run inside a sandboxed CSP
        resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
    # 2.13.0: the app asks with ?v=<size>: only that versioned address is cached for a day; anything else revalidates
    # (ETag), so a repaired file is never hidden behind a cached broken answer
    resp.headers["Cache-Control"] = "private, max-age=86400" if request.args.get("v") == str(a["size"]) else "private, no-cache"
    return resp
