"""2.122.0 B (#2294): the chosen documents at once -- tags added / removed, the type or the sender set (POST /api/docs/bulk,
its undo sends the old values back) and the download as one ZIP (POST /api/docs/zip checks and hands out a ticket, GET
/api/docs/zip/<ticket> sends it: a plain link, so the browser saves the file itself instead of holding it in memory).

Rights: a change needs write access to each document (others are skipped and counted), the ZIP takes only documents the
person sees (files/store.py fs_visible_sql). Every change and every file in a ZIP is in the file's history (fs_log). A file
that cannot be read (damaged, missing, locked by the virus scanner) is left out of the ZIP, the rest still comes. Limits:
DSR_IDS documents per request, the ZIP at most DSR_ZIP_FILES files and DSR_ZIP_MB MB (checked before anything is written,
refused with a hint), at most two ZIPs built at once. The web app only (agents: API v1)."""
import os
import secrets
import tempfile
import threading
import time
import zipfile
from datetime import datetime

from flask import g, jsonify, send_file

from ..core.config import app
from ..core.db import body, bump, db, err
from ..core.i18n import tr
from ..core.access import Denied
from ..accounts.session import me
from ..files.store import fs_log_add, fs_read, fs_role, fs_visible_sql
from . import store as S

DSR_IDS = 2000          # documents per request (the selection's limit in docs.js, DC_SMV_MAX)
DSR_EDIT = 500          # documents per change request (each one learns: the client sends larger choices in parts)
DSR_ZIP_FILES = int(os.environ.get("KALMIDO_DOCS_ZIP_MAX_FILES", "2000"))
DSR_ZIP_MB = int(os.environ.get("KALMIDO_DOCS_ZIP_MAX_MB", "1024"))
DSR_TICKET_S = 300      # a ZIP ticket is good for five minutes, once
DSR_BUSY = threading.BoundedSemaphore(2)
DSR_TICKETS = {}        # ticket -> (account id, [node ids], until); one server process (waitress threads)
DSR_LOCK = threading.Lock()
DSR_PACKED = ("pdf", "jpg", "jpeg", "png", "gif", "webp", "avif", "heic", "heif", "zip", "docx", "xlsx", "pptx", "odt", "ods")


def _no_agent():
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403)


def dsr_idlist(v, most=DSR_IDS):
    """A list of document ids from the client (ints, no duplicates) or Denied(400)."""
    if not isinstance(v, list) or not v:
        raise Denied(400, tr("Invalid value: {0}", "ids"))
    out = list(dict.fromkeys(x for x in v if isinstance(x, int) and not isinstance(x, bool) and x > 0))
    if not out:
        raise Denied(400, tr("Invalid value: {0}", "ids"))
    if len(out) > most:
        raise Denied(413, tr("Too many at once: at most {0}", most))
    return out


def dsr_visible(c, uid, ids):
    """The rows (doc_meta d + fs_nodes n columns) of those ids that are documents uid sees, in the order of ids."""
    rows = {}
    for i in range(0, len(ids), 1000):
        part = ids[i:i + 1000]
        for r in c.execute(f"""SELECT n.id, n.name, n.size, n.mime, n.org_id, n.owner_id, d.ws FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id
                               WHERE n.kind='file' AND n.id IN ({','.join('?' * len(part))}) AND n.id IN {fs_visible_sql(uid, c)}""", part):
            rows[r["id"]] = r
    return [rows[i] for i in ids if i in rows]


def dsr_state(c, m):
    """The values a change may touch, as the undo sends them back: {id, sender, type, tags} (names)."""
    ws = m["ws"]
    return {"id": m["node_id"], "sender": S.label_name(c, ws, "sender", m["sender_id"]) or "",
            "type": S.label_name(c, ws, "type", m["type_id"]) or "", "tags": [t["name"] for t in S.node_tags(c, m["node_id"])]}


def _names(v):
    return [str(x).strip()[:S.NAME_MAX] for x in (v or [])[:30] if isinstance(x, (str, int)) and str(x).strip()] if isinstance(v, list) else []


@app.post("/api/docs/bulk")
def docs_bulk():
    """{ids, add_tags?: [names], remove_tags?: [names], type?: name | "" (none), sender?: name | ""} -- one change on every
    chosen document I may change (names make labels in each document's workspace) -> {changed, denied, before: [{id,
    sender, type, tags}]} (denied: chosen documents I may only view). {restore: [{id, sender, type, tags}]} (the undo): those values back."""
    from .web import doc_update
    c = db()
    _no_agent()
    uid = me()
    b = body()
    restore = b.get("restore")
    if restore is not None:
        if not isinstance(restore, list):
            return err(tr("Invalid value: {0}", "restore"))
        items = {x["id"]: x for x in restore if isinstance(x, dict) and isinstance(x.get("id"), int)}
        ids = dsr_idlist(list(items), DSR_EDIT)
    else:
        ids = dsr_idlist(b.get("ids"), DSR_EDIT)
        add, rem = _names(b.get("add_tags")), {x.lower() for x in _names(b.get("remove_tags"))}
        if not (add or rem or "type" in b or "sender" in b):
            return err(tr("Nothing to change"))
    changed, denied, before = [], 0, []
    for n in dsr_visible(c, uid, ids):
        if fs_role(c, n["id"], uid) not in ("owner", "edit"):
            denied += 1
            continue
        m = S.meta_row(c, n["id"])
        cur = dsr_state(c, m)
        if restore is not None:
            x = items[n["id"]]
            d = {k: (_names(x[k]) if k == "tags" else str(x[k] or "")[:S.NAME_MAX]) for k in ("sender", "type", "tags") if k in x}
        else:
            d = {}
            if add or rem:
                tags = [t for t in cur["tags"] if t.lower() not in rem]
                tags += [t for t in add if t.lower() not in {x.lower() for x in tags}]
                if tags != cur["tags"]:
                    d["tags"] = tags[:30]
            for k in ("type", "sender"):
                if k in b and str(b[k] or "").strip()[:S.NAME_MAX].lower() != cur[k].lower():
                    d[k] = str(b[k] or "").strip()[:S.NAME_MAX]
        if not d:
            continue
        e = doc_update(c, n["id"], d, uid)
        if e:
            c.rollback()
            return e
        fs_log_add(c, n["id"], "edit", "bulk:" + ",".join(sorted(d)))
        changed.append(n["id"])
        before.append(cur)
    if changed:
        bump(c)
    c.commit()
    return jsonify(changed=changed, denied=denied, before=before)


# ---- the ZIP
def dsr_zipname(name, taken):
    """A file name for the ZIP (no path parts), "name (2).ext" when the ZIP has it already (case-insensitive)."""
    name = (name or "document").replace("/", "_").replace("\\", "_").strip(". ") or "document"
    base, dot, ext = name.rpartition(".")
    if not dot or not base:
        base, ext = name, ""
    out, i = name, 1
    while out.lower() in taken:
        i += 1
        out = f"{base} ({i}).{ext}" if ext else f"{base} ({i})"
    taken.add(out.lower())
    return out


def dsr_zip_check(rows):
    """The refusal text when the ZIP would hold too much, else None."""
    size = sum(int(r["size"] or 0) for r in rows)
    if len(rows) > DSR_ZIP_FILES or size > DSR_ZIP_MB * 1024 * 1024:
        return tr("Too much for one ZIP: at most {0} files and {1} MB. Please choose fewer.", DSR_ZIP_FILES, DSR_ZIP_MB)
    return None


def _tickets_gc(now):
    for k in [k for k, v in DSR_TICKETS.items() if v[2] < now]:
        DSR_TICKETS.pop(k, None)


@app.post("/api/docs/zip")
def docs_zip_ticket():
    """{ids} -> {files, size, url}: the check before the download (only documents I see; too many / too large = 413 with
    the limits). url = the download, good once within five minutes for me."""
    c = db()
    _no_agent()
    uid = me()
    rows = dsr_visible(c, uid, dsr_idlist(body().get("ids")))
    if not rows:
        raise Denied(404)
    msg = dsr_zip_check(rows)
    if msg:
        return err(msg, 413)
    tok = secrets.token_urlsafe(18)
    now = time.time()
    with DSR_LOCK:
        _tickets_gc(now)
        DSR_TICKETS[tok] = (uid, [r["id"] for r in rows], now + DSR_TICKET_S)
    return jsonify(files=len(rows), size=sum(int(r["size"] or 0) for r in rows), url=f"/api/docs/zip/{tok}")


@app.get("/api/docs/zip/<tok>")
def docs_zip_get(tok):
    """The ZIP of a ticket (the visibility is checked again: a document no longer visible is left out)."""
    c = db()
    _no_agent()
    uid = me()
    with DSR_LOCK:
        _tickets_gc(time.time())
        t = DSR_TICKETS.get(str(tok))
        if not t or t[0] != uid:  # another account's request leaves the ticket alone
            raise Denied(404)
        DSR_TICKETS.pop(str(tok), None)
    rows = dsr_visible(c, uid, t[1])
    if not rows:
        raise Denied(404)
    msg = dsr_zip_check(rows)
    if msg:
        return err(msg, 413)
    if not DSR_BUSY.acquire(blocking=False):
        raise Denied(429, tr("Too many requests"))
    fd, path = tempfile.mkstemp(prefix="kalmido-docs-zip-", suffix=".zip")
    try:
        taken = set()
        with os.fdopen(fd, "wb") as f, zipfile.ZipFile(f, "w", allowZip64=True) as z:
            for r in rows:
                try:
                    data = fs_read(c, r["id"])
                except Exception:  # noqa: BLE001 -- damaged / missing / locked: left out, the rest still comes
                    continue
                p = dsr_zipname(r["name"], taken)
                ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
                packed = ext in DSR_PACKED or (r["mime"] or "").startswith(("image/", "video/", "audio/"))
                z.writestr(p, data, compress_type=zipfile.ZIP_STORED if packed else zipfile.ZIP_DEFLATED)
                fs_log_add(c, r["id"], "download", "zip")
        c.commit()
        fh = open(path, "rb")  # noqa: SIM115 -- closed by the response; the name is gone at once
        os.unlink(path)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    finally:
        DSR_BUSY.release()
    resp = send_file(fh, mimetype="application/zip", as_attachment=True, max_age=0,
                     download_name=f"{tr('Documents')}-{datetime.now().strftime('%Y-%m-%d')}.zip")
    resp.headers["Cache-Control"] = "private, no-cache"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp
