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


# 2.30.0 (#380): files an agent stores never carry an executable / script ending (a downloaded "fix.sh" an injected agent
# wrote must not be one double click away from running): the name gets ".txt" appended and the file is plain text.
EXEC_EXT = {"sh", "bash", "zsh", "fish", "ksh", "csh", "command", "tool", "ps1", "psm1", "psd1", "bat", "cmd", "exe", "com", "msi",
            "msp", "msix", "appx", "vbs", "vbe", "jse", "wsf", "wsh", "scr", "pif", "cpl", "hta", "lnk", "reg", "jar", "app",
            "dmg", "pkg", "deb", "rpm", "apk", "run", "bin", "elf", "out", "desktop", "scpt", "applescript", "workflow", "inf",
            "gadget", "dll", "so", "dylib", "action", "url", "website", "library-ms", "settingcontent-ms", "appimage", "xll", "xlam"}


def file_ext(name):
    name = name.rstrip(". ")  # "evil.bat." / "evil.bat " end up as evil.bat once saved on Windows
    return name.rsplit(".", 1)[1].lower() if "." in name.strip(".") else ""


def unexec_name(name):
    """The stored name of an agent's file: an executable ending gets ".txt" appended (deploy.sh -> deploy.sh.txt)."""
    return name[:146] + ".txt" if file_ext(name) in EXEC_EXT else name


def uploader_is_agent(c, uid):
    r = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return bool(r) and (r["kind"] or "user") == "agent"


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
    ag = uploader_is_agent(c, me())  # 2.30.0 (#380): the names as stored (an agent's deploy.sh became deploy.sh.txt)
    log_act(c, tid, "attach", {"names": [unexec_name(safe_name(f.filename)) if ag else safe_name(f.filename) for f in files][:20], "n": len(files)})
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
    agent = uploader_is_agent(c, uid)  # 2.30.0 (#380)
    for f in files:
        name = safe_name(f.filename)
        unexec = agent and unexec_name(name) != name
        if unexec:
            name = unexec_name(name)
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
        mime = "text/plain" if unexec else (f.mimetype if f.mimetype and f.mimetype != "application/octet-stream" else None) \
            or mimetypes.guess_type(name)[0] or "application/octet-stream"
        c.execute("INSERT INTO attachments(task_id,name,mime,size,path,created_at,comment_id,user_id) VALUES(?,?,?,?,?,?,?,?)",
                  (tid, name, mime, size, rel, ts, comment_id, uid))
    if comment_id is None:
        c.execute("UPDATE tasks SET updated_at=? WHERE id=?", (ts, tid))
    return None


# 2.30.0 (#380): text files written by agents / scripts through the API (name + UTF-8 content, no upload form): Markdown,
# plain text, HTML / CSS / JS sources, data and code. The app shows them as a preview (Markdown formatted, the rest as
# source); they are never served for the browser to run (send_stored: a download, octet-stream, sandbox CSP).
TEXT_MAX = 1024 * 1024  # bytes (UTF-8): larger texts belong into an upload
TEXT_EXT = {"md", "markdown", "txt", "text", "log", "html", "htm", "css", "scss", "sass", "less", "js", "mjs", "cjs", "jsx", "ts", "tsx",
            "json", "jsonl", "ndjson", "csv", "tsv", "xml", "yml", "yaml", "toml", "ini", "cfg", "conf", "env", "properties", "py", "pyi",
            "rb", "go", "rs", "java", "kt", "kts", "scala", "swift", "c", "h", "cc", "cpp", "cxx", "hpp", "cs", "php", "pl", "lua", "r",
            "dart", "ex", "exs", "erl", "hs", "ml", "clj", "sql", "graphql", "proto", "tf", "diff", "patch", "vue", "svelte", "rst",
            "adoc", "tex", "bib", "srt", "vtt", "ics", "vcf", "mk", "cmake", "gradle", "lock"}
TEXT_MIME = {"md": "text/markdown", "markdown": "text/markdown", "csv": "text/csv", "tsv": "text/tab-separated-values", "json": "application/json",
             "html": "text/html", "htm": "text/html", "css": "text/css", "js": "text/javascript", "mjs": "text/javascript", "xml": "application/xml",
             "yml": "application/yaml", "yaml": "application/yaml"}
_VER_RE = re.compile(r"^(.*?)(?: \(v(\d{1,6})\))?$")


def text_file_name(name):
    """The stored name of a text file: safe, a known text ending (anything else, executables included, gets ".txt")."""
    name = safe_name(name)
    return name if file_ext(name) in TEXT_EXT else name[:146] + ".txt"


def text_version_name(c, tid, name):
    """Same name as a file of the task = a new version next to it, the old one stays: "report.md" -> "report (v2).md"
    (v3, ... after the highest one). Returns (name, version, the id of the newest earlier version or None)."""
    stem, dot, ext = name.rpartition(".") if "." in name.strip(".") else (name, "", "")
    base = _VER_RE.match(stem).group(1)
    best, prev = 0, None
    for r in c.execute("SELECT id, name FROM attachments WHERE task_id=? AND comment_id IS NULL ORDER BY id", (tid,)):
        st, d2, ex = r["name"].rpartition(".") if "." in r["name"].strip(".") else (r["name"], "", "")
        if ex.lower() != ext.lower() or d2 != dot:
            continue
        m = _VER_RE.match(st)
        if m.group(1) == base:
            v = int(m.group(2) or 1)
            if v >= best:
                best, prev = v, r["id"]
    if not best:
        return name, 1, None
    return f"{base[:140]} (v{best + 1}){dot}{ext}", best + 1, prev


def text_attachment_create(c, tid, name, content):
    """Stores `content` (str) as a text file of task tid (caller checked the rights; commits). Returns the new row as a dict
    (+ version, replaces) or raises ValueError with the message."""
    import io
    from werkzeug.datastructures import FileStorage
    if not isinstance(name, str) or not name.strip():
        raise ValueError(tr("Name missing"))
    if not isinstance(content, str):
        raise ValueError(tr("Expected {0}", '{"name": "...", "content": "..."}'))
    data = content.encode("utf-8")
    if not data:
        raise ValueError(tr("{0}: the file is empty and was not uploaded", safe_name(name)))
    if len(data) > TEXT_MAX:
        raise ValueError(tr("{0}: larger than {1} MB", safe_name(name), TEXT_MAX // (1024 * 1024)))
    fname, ver, prev = text_version_name(c, tid, text_file_name(name))
    mime = TEXT_MIME.get(file_ext(fname), "text/plain")
    saved = []
    e = save_attachments(c, tid, [FileStorage(stream=io.BytesIO(data), filename=fname, content_type=mime)], saved=saved)
    if e:
        c.rollback()
        unlink_files(saved)
        raise ValueError(e)
    row = c.execute("SELECT id, task_id, name, mime, size, created_at FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (tid,)).fetchone()
    log_act(c, tid, "attach", {"names": [row["name"]], "n": 1, **({"version": ver} if ver > 1 else {})})
    bump(c)
    c.commit()
    return {**dict(row), "comment_id": None, "version": ver, "replaces": prev}


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
