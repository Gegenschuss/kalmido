"""Kalmido: files of lists with the lock, encrypted in the browser with the list key (2.64.2, #1817, stage 2).

Format (static/js/liste2efile.js): b"KENC\\x02" | gen (4 bytes, big endian) | iv (12) | AES-256-GCM(list key of gen,
AAD "kalmido-lfile:v1:<list_id>:<gen>", u32 header length | header JSON {name, type, size} | file bytes). attachments.enc = 2,
attachments.e2e_gen = gen, attachments.name = the file name as list cipher (field "file_name"), mime application/octet-stream.
Readable for every member with the list key; no text extract, no preview, no agent access. Upload, conversion when the lock
goes on / off / after a key change, and the guards of the plain upload ways live here (part B)."""
import os
import re
import struct
import uuid

from flask import g, jsonify, request

from ..core.config import app, ATT_DIR, MAX_FILE_MB
from ..core.i18n import N_, tr
from ..core.db import bump, db, err, insert_id, iso, now_utc
from ..core.access import Denied, MANAGE_ROLES, need_task, need_list
from ..core.orgcrypt import oc_seal_path, oc_task_org, oc_task_space  # 2.149.0 G (#2517): pulled up from functions
from ..core.serializers import unlink_files  # 2.149.0 G (#2517): pulled up from functions

LE2F_MAGIC = b"KENC\x02"
LE2F_HEAD = len(LE2F_MAGIC) + 4      # magic + generation; then iv (12) and the AES-GCM ciphertext (tag 16)
LE2F_SLACK = 64 * 1024               # the encrypted header + iv + tag on top of the plain size limit
LE2F_NAME_MAX = 4000                 # characters of the encrypted file name (150 characters of name, base64 + tag + padding)
LE2F_STORED = "encrypted.kenc"       # what a download of a list file is called (the real name is inside the file)
LE2F_MIME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,60}/[A-Za-z0-9][A-Za-z0-9.+_-]{0,80}$")
LE2F_MSG = {
    "plain": N_("This project is encrypted in the browser. Files can only be added in the app."),
    "project": N_("This project is encrypted in the browser. Add files to a task: project files would not be encrypted."),
    "move": N_("Tasks with encrypted files cannot move to another project. Download the files and remove them from the task first."),
}


def le2f_task_mode(c, tid):
    from .liste2e import le2e_task_mode
    return le2e_task_mode(c, tid)


def le2f_plain_guard(c, tid):
    """Every plain upload way (web upload, comment file, text file, API, MCP, the per-person files of 2.42, shares) into a
    task of a list with the lock: 409 list_e2e. Called by save_attachments before anything is written."""
    if tid and le2f_task_mode(c, tid):
        from .liste2e import LE2EDenied
        raise LE2EDenied("list_e2e", msg=tr(LE2F_MSG["plain"]))


def le2f_plain_skip(c, tid):
    """The background ways (mail import, shares): a file for a task of a list with the lock is skipped."""
    return bool(tid) and bool(le2f_task_mode(c, tid))


def le2f_blob_gen(head):
    """The generation in the head of a list file (None: not a list file)."""
    if len(head) < LE2F_HEAD or head[:len(LE2F_MAGIC)] != LE2F_MAGIC:
        return None
    return struct.unpack(">I", head[len(LE2F_MAGIC):LE2F_HEAD])[0]


def le2f_name_ok(v, gen):
    """The file name as a list ciphertext of generation gen."""
    from .liste2e import le2e_parse
    d = le2e_parse(v, LE2F_NAME_MAX) if isinstance(v, str) and len(v) <= LE2F_NAME_MAX + 200 else None
    return bool(d) and d["g"] == gen


def _le2f_person():
    from .liste2e import le2e_writer_ok
    if not le2e_writer_ok():
        raise Denied(403)
    return g.user["id"]


def _le2f_store(c, tid, f, gen, uid, saved):
    """Writes one uploaded list file (werkzeug FileStorage) next to the task's files, sealed like its neighbours.
    -> (rel path, size) or raises ValueError with the message."""
    from ..notify.alerts import aa_count, aa_oserr
    head = f.stream.read(LE2F_HEAD)
    f.stream.seek(0)
    if le2f_blob_gen(head) != gen:
        raise ValueError(tr("Invalid value: {0}", "file"))
    try:
        os.makedirs(os.path.join(ATT_DIR, str(tid)), exist_ok=True)
        rel = os.path.join(str(tid), f"{uuid.uuid4().hex[:12]}-{LE2F_STORED}")
        full = os.path.join(ATT_DIR, rel)
        f.save(full)
    except OSError as e:
        aa_count("storage", "attachments", aa_oserr(e))
        raise
    size = os.path.getsize(full)
    if size > MAX_FILE_MB * 1024 * 1024 + LE2F_SLACK or size <= LE2F_HEAD + 12 + 16:
        os.remove(full)
        raise ValueError(tr("{0}: larger than {1} MB", tr("Encrypted file"), MAX_FILE_MB) if size > LE2F_HEAD + 28
                         else tr("Invalid value: {0}", "file"))
    saved.append(rel)
    # #828, 2.64.0 (#1864): sealed at rest with the key of its space (organisation, else the list owner's account), like every task file
    oc_seal_path(c, oc_task_space(c, tid) or 0, full, fresh=True)
    return rel, size


def le2f_save(c, tid, files, names, comment_id=None, saved=None, uid=None):
    """Stores list files (already encrypted in the browser) for task tid or one of its comments; names = the file names as
    list ciphertexts, in the same order. The list must be 'on'. Returns an error message or None (caller commits; on an
    error the caller rolls back and unlinks `saved`) -- like save_attachments."""
    from .liste2e import le2a_gen
    from ..admin.hosting import quota_guard
    uid = uid or _le2f_person()
    lid = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()[0]
    mode, gen = le2a_gen(c, lid)
    if mode != "on":
        from .liste2e import LE2EDenied
        raise LE2EDenied("list_e2e_busy" if mode else "list_e2e_open")
    if len(names) != len(files) or not all(le2f_name_ok(n, gen) for n in names):
        return tr("Invalid value: {0}", "name")
    quota_guard(c, uid)
    saved = [] if saved is None else saved
    ts = iso(now_utc())
    for f, name in zip(files, names):
        try:
            rel, size = _le2f_store(c, tid, f, gen, uid, saved)
        except ValueError as e:
            return str(e)
        insert_id(c, "INSERT INTO attachments(task_id,name,mime,size,path,created_at,comment_id,user_id,enc,e2e_gen) "
                     "VALUES(?,?,?,?,?,?,?,?,2,?)", (tid, name, "application/octet-stream", size, rel, ts, comment_id, uid, gen))
    if comment_id is None:
        c.execute("UPDATE tasks SET updated_at=? WHERE id=?", (ts, tid))
    return None


# ---------------------------------------------------------------- routes
@app.post("/api/tasks/<int:tid>/list-attachments")
def le2f_upload(tid):
    """multipart "file" (one or more list files, KENC\\x02 of the list's current generation), "name" (per file: the file name
    as list ciphertext), optional "comment_id" (a comment of mine on this task). Only a person in the web app; the task's
    files need the right to change the task, a comment's files are its author's."""
    from ..tasks.tasks import one_task
    from ..tasks.validation import log_act
    c = db()
    uid = _le2f_person()
    files, names = request.files.getlist("file"), request.form.getlist("name")
    if not files:
        return err(tr("File missing"))
    cid = request.form.get("comment_id") or None
    if cid is not None:
        try:
            cid = int(cid)
        except ValueError:
            return err(tr("Invalid value: {0}", "comment_id"))
        role = need_task(c, tid, write=False, full=True)
        cm = c.execute("SELECT user_id, deleted_at FROM comments WHERE id=? AND task_id=?", (cid, tid)).fetchone()
        if not cm or cm["deleted_at"]:
            raise Denied(404)
        if cm["user_id"] != uid and role not in MANAGE_ROLES:
            raise Denied(403)
    else:
        need_task(c, tid)
    if c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()[0]:
        return err(tr("The task is in the trash"), 409)
    saved = []
    e = le2f_save(c, tid, files, names, comment_id=cid, saved=saved, uid=uid)
    if e:
        c.rollback()
        unlink_files(saved)
        return err(e)
    if cid is None:
        log_act(c, tid, "attach", {"names": [tr("Encrypted file")] * min(len(files), 20), "n": len(files)})
    bump(c)
    c.commit()
    return jsonify(one_task(c, tid))


def le2f_left(c, lid, mode, gen, uid, limit=0):
    """The files of list lid that the running switch still has to convert -> ([{id, task_id, comment_id, enc, gen, size}],
    count). encrypting / on: plain files, list files of an older generation than gen, the per-person files of uid (the
    others' stay as they are: only their uploader can read them); decrypting: every list file. limit 0 = count only."""
    if mode == "decrypting":
        cond, args = "a.enc=2", ()
    elif mode in ("encrypting", "on"):
        cond, args = "(a.enc=0 OR (a.enc=2 AND a.e2e_gen<?) OR (a.enc=1 AND a.enc_by=?))", (int(gen or 0), uid or 0)
    else:
        return [], 0
    sql = f"FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=? AND {cond}"
    n = c.execute(f"SELECT COUNT(*) {sql}", (lid, *args)).fetchone()[0]
    if not limit or not n:
        return [], n
    rows = c.execute(f"SELECT a.id, a.task_id, a.comment_id, a.enc, a.e2e_gen, a.size, a.name, a.mime {sql} ORDER BY a.id LIMIT ?",
                     (lid, *args, int(limit))).fetchall()
    return [{"id": r["id"], "task_id": r["task_id"], "comment_id": r["comment_id"], "enc": r["enc"], "gen": r["e2e_gen"],
             "size": r["size"], "name": r["name"], "mime": r["mime"]} for r in rows], n  # + name / mime: what a plain file is called


@app.post("/api/lists/<int:lid>/e2e/files/<int:aid>")
def le2f_convert(lid, aid):
    """multipart "file" + "name" (+ "type" when the lock goes off): one file of list lid in the target format of the running
    switch, replacing the content of the same attachment row (same id, the comment stays). encrypting / on: a list file of
    the current generation (name = list ciphertext); decrypting: the plain file (name and type in plain). Owner / list admins
    (and the uploader of a per-person file of 2.42); no history entry."""
    from .liste2e import LE2EDenied, le2a_gen
    from ..tasks.attachments import safe_name
    c = db()
    uid = _le2f_person()
    role = need_list(c, lid, write=False)
    a = c.execute("SELECT a.* FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE a.id=? AND t.list_id=?", (aid, lid)).fetchone()
    if not a:
        raise Denied(404)
    if role not in MANAGE_ROLES and not (a["enc"] == 1 and a["enc_by"] == uid and role in ("edit", "admin", "owner")):
        raise Denied(403, tr("Only the owner and project admins can change this setting"))
    mode, gen = le2a_gen(c, lid)
    if not mode:
        raise LE2EDenied("list_e2e_open")
    if not _le2f_todo(a, mode, gen, uid):
        return err(tr("Nothing to do"), 409)
    files = request.files.getlist("file")
    if len(files) != 1:
        return err(tr("File missing"))
    f, name = files[0], request.form.get("name") or ""
    saved = []
    if mode == "decrypting":
        if le2f_blob_gen(f.stream.read(LE2F_HEAD)) is not None or name.startswith("e2e1:"):
            return err(tr("Invalid value: {0}", "file"))
        f.stream.seek(0)
        name = safe_name(name)
        typ = request.form.get("type") or ""
        import mimetypes
        mime = typ if LE2F_MIME.match(typ) else (mimetypes.guess_type(name)[0] or "application/octet-stream")
        try:
            rel, size, mime, info = _le2f_plain_store(c, a["task_id"], f, name, saved, mime, uid)
        except ValueError as e:
            return err(str(e))
        n = c.execute("UPDATE attachments SET name=?, mime=?, size=?, path=?, enc=0, enc_by=NULL, e2e_gen=0 WHERE id=? AND path IS NOT DISTINCT FROM ? "
                      "AND enc=? AND e2e_gen=?", (name, mime, size, rel, aid, a["path"], a["enc"], a["e2e_gen"])).rowcount
    else:
        if not le2f_name_ok(name, gen):
            return err(tr("Invalid value: {0}", "name"))
        try:
            rel, size = _le2f_store(c, a["task_id"], f, gen, uid, saved)
        except ValueError as e:
            unlink_files(saved)
            return err(str(e))
        n = c.execute("UPDATE attachments SET name=?, mime='application/octet-stream', size=?, path=?, enc=2, enc_by=NULL, e2e_gen=? "
                      "WHERE id=? AND path IS NOT DISTINCT FROM ? AND enc=? AND e2e_gen=?",
                      (name, size, rel, gen, aid, a["path"], a["enc"], a["e2e_gen"])).rowcount
    if not n:  # 2.64.2 review (L1): another browser converted it meanwhile -- keep theirs, drop this copy
        c.rollback()
        unlink_files([rel])
        return err(tr("Nothing to do"), 409)
    if mode != "decrypting":  # 2.61.0 (#1820): the recognised text of the plain file goes (the server keeps only ciphertext)
        from ..files.textscan import ts_forget
        ts_forget(c, "att", aid)
    else:  # 2.61.0 (#1818 #1820): an unchecked file is remembered for the later scan, text recognition queued
        from ..core.orgcrypt import oc_task_org
        from ..files.upsafe import up_after_store
        up_after_store(c, "att", aid, oc_task_org(c, a["task_id"]) or None, info)
    bump(c)
    c.commit()
    if a["path"] and a["path"] != rel:
        unlink_files([a["path"]])
    return jsonify(ok=True, id=aid, size=size, enc=0 if mode == "decrypting" else 2, gen=0 if mode == "decrypting" else gen)


def _le2f_todo(a, mode, gen, uid):
    """Does the switch still have to convert attachment row a?"""
    if mode == "decrypting":
        return a["enc"] == 2
    return a["enc"] == 0 or (a["enc"] == 2 and (a["e2e_gen"] or 0) < gen) or (a["enc"] == 1 and a["enc_by"] == uid)


def _le2f_plain_store(c, tid, f, name, saved, mime, uid):
    """The way back: the decrypted file, stored like a plain upload (size limit, upload checks of 2.61.0, sealed at rest).
    -> (rel, size, mime, info of the upload checks for up_after_store)."""
    from ..notify.alerts import aa_count, aa_oserr
    from ..files.upsafe import up_check_path, UploadRefused
    try:
        os.makedirs(os.path.join(ATT_DIR, str(tid)), exist_ok=True)
        rel = os.path.join(str(tid), f"{uuid.uuid4().hex[:12]}-{name}")
        full = os.path.join(ATT_DIR, rel)
        f.save(full)
    except OSError as e:
        aa_count("storage", "attachments", aa_oserr(e))
        raise
    size = os.path.getsize(full)
    saved.append(rel)
    if size > MAX_FILE_MB * 1024 * 1024 or not size:
        os.remove(full)
        saved.remove(rel)
        raise ValueError(tr("{0}: larger than {1} MB", name, MAX_FILE_MB) if size else tr("{0}: the file is empty and was not uploaded", name))
    try:  # 2.61.0 (#1818 #1819): the plain file is new content for the server: scan + metadata like an upload
        size, mime, info = up_check_path(c, full, name, mime, uid, oc_task_org(c, tid) or None, "att")
    except UploadRefused as e:  # up_check_path removed the file already
        saved.remove(rel)
        raise ValueError(str(e))
    oc_seal_path(c, oc_task_space(c, tid) or 0, full, fresh=True)  # 2.64.0 (#1864): the key of its space, also private
    return rel, size, mime, info


# ---------------------------------------------------------------- guards used elsewhere
def le2f_att_guard(a):
    """need_attachment(read) of a list file: only a person in the web app (agents, API tokens, calendar apps: 404); the
    caller checks the read right on the task (and the comment) as for every file."""
    from .liste2e import le2e_writer_ok
    if not le2e_writer_ok():
        raise Denied(404)


def le2f_move_guard(c, tid, src, dst):
    """A task (with its subtasks) that carries list files never leaves its list (finding M8): the files are encrypted with
    the key of the source list. Plain files moving into a list with the lock are converted by the next background run."""
    if not dst or src == dst:
        return
    from .liste2e import LE2EDenied, le2a_subtree
    ids = le2a_subtree(c, tid)
    q = ",".join("?" * len(ids))
    if c.execute(f"SELECT 1 FROM attachments WHERE enc=2 AND task_id IN ({q}) LIMIT 1", ids).fetchone():
        raise LE2EDenied("list_e2e_files", msg=tr(LE2F_MSG["move"]))
