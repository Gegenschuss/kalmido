"""2.99.0 A (#2182): files of knowledge pages (PDFs and pictures) -- uploaded to a page, taken over by the ZIP import (a
SilverBullet export: pages + their files, often in _attachments/) and given back by the export (round trip).

A file belongs to one page (page_id) and lies in the page's space (org_id / owner_id as the page). Read = the page can be
read (wiki_need: a page in the trash hides its files, Undo brings them back), write = the write right in the space. Stored
like task files: ATT_DIR/wiki/<page id>/, sealed with the space's key (orgcrypt, private spaces with the account key),
checked by files/upsafe (virus scan, picture metadata). Only PDF / PNG / JPEG / GIF / WebP and cleaned SVG; the type comes
from the content, the ending only has to agree. A space with the lock (wikie2e: texts encrypted in the browser) takes no
files yet (they would lie readable for the server). Pages link their files as Markdown: ![label](/api/wiki/files/<id>/<name>)
shows a picture, [label](/api/wiki/files/<id>/<name>) opens it; the export writes them as [[_attachments/<page>/<name>]].
"""
import hashlib
import json
import os
import posixpath
import re
import tempfile
import threading
import unicodedata
import uuid
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import quote, unquote

from flask import jsonify, request, send_file

from ..core.config import app, ATT_DIR
from ..core.i18n import tr as _tr_base
from ..core.db import bump, db, err, insert_id, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied
from ..core.orgcrypt import OrgCryptError, oc_read_file, oc_send_file, oc_user_space, oc_write_file
from ..core.serializers import unlink_files
from ..core.errors import BadInput
from ..tasks.attachments import file_ext, safe_name, send_stored
from .pages import (WIKI_ZIP_FILES, WIKI_ZIP_FILE_MAX, wiki_clean_path, wiki_frontmatter, wiki_insert, wiki_need,
                    wiki_set_links, wiki_space_sql)
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions

WKA_LANG = threading.local()  # 2.177.0 (#2685): the language of the person a background import (wkimport.py) works for


def tr(key, *a, lg=None):
    """core.i18n.tr; in the background import in the language of its person (in a request: as usual)."""
    return _tr_base(key, *a, lg=lg or getattr(WKA_LANG, "lg", None))


def _wka_env_mb(name, dflt, hi=512):
    """Review L8: at most hi MB (a file is held in memory a few times while it is checked and sealed)."""
    try:
        return min(hi, max(1, int(os.environ.get(name, "").strip() or dflt)))
    except ValueError:
        return dflt


# 2.177.0 (#2685): 100 MB per file (was 25 MB; handbooks as PDF are larger), KALMIDO_WIKI_FILE_MAX_MB
WKA_FILE_MAX = _wka_env_mb("KALMIDO_WIKI_FILE_MAX_MB", 100) * 1024 * 1024  # bytes per file (upload and import)
WKA_ZIP_TOTAL = 500 * 1024 * 1024  # bytes of a ZIP to import, and of everything unpacked from it (zip bombs)
WKA_MD_TOTAL = 30_000_000  # bytes of all pages of one import together (the limit before 2.99)
WKA_UPLOAD_FILES = 20
WKA_RATIO = 200  # 2.177.0 (#2685): unpacked / packed of one entry above 1 MB (zip bombs; like the account import)
WKA_TYPES = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
             "webp": "image/webp", "svg": "image/svg+xml"}
SVG = "image/svg+xml"
WKA_URL_RE = re.compile(r"(!?)\[([^\[\]\n]*)\]\(/api/wiki/files/(\d{1,15})(?:/[^\s()]*)?\)")
# [[file.pdf]], ![[pic.png]], [[file.pdf|label]] -- and Markdown links / pictures with a relative address
WKA_WIKILINK_RE = re.compile(r"(!?)\[\[([^\[\]|\n]{1,250}?)(?:\|([^\[\]\n]*))?\]\]")
WKA_MDLINK_RE = re.compile(r"(!?)\[([^\[\]\n]*)\]\(\s*(<[^<>\n]{1,500}>|[^\s()<>]{1,500}(?:\([^\s()]*\)[^\s()<>]*)*)"
                           r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)")
WKA_TMP = os.path.join(ATT_DIR, ".wikitmp")  # the export ZIP while it is written (the backup skips this folder)
WKA_TRASH_DAYS = 30  # review M1: a file in the trash (undo possible) is deleted for good after this


def wka_space(r):
    """The key space of a page's files (orgcrypt): its organisation, else its owner's account."""
    return int(r["org_id"]) if r["org_id"] else oc_user_space(r["owner_id"])


def wka_locked(c, r):
    from .wikie2e import wke_page_mode
    return bool(wke_page_mode(c, r))


def wka_name(name):
    """A stored file name: safe, without the characters of a [[link]] (the export writes [[_attachments/…/name]])."""
    return safe_name(re.sub(r"[\[\]|#^]", "_", unicodedata.normalize("NFC", name or "")))


def wka_url(fid, name):
    return f"/api/wiki/files/{int(fid)}/{quote(name, safe='')}"


def wka_dict(r, marks=None):
    d = {"id": r["id"], "page_id": r["page_id"], "name": r["name"], "mime": r["mime"], "size": r["size"],
         "created_by": r["created_by"], "created_at": r["created_at"], "url": wka_url(r["id"], r["name"]),
         "image": r["mime"].startswith("image/")}
    if marks and r["id"] in marks:
        d["up"] = marks[r["id"]]  # 2.61.0 marks (unchecked / infected), like the other file lists
    return d


def wka_list(c, page):
    """The files of a page (none in a space with the lock)."""
    if wka_locked(c, page):
        return []
    from ..files.upsafe import up_marks
    rows = c.execute("SELECT * FROM wiki_files WHERE page_id=? AND deleted_at IS NULL ORDER BY id LIMIT 1000", (page["id"],)).fetchall()
    marks = up_marks(c, "wiki", [r["id"] for r in rows])
    return [wka_dict(r, marks) for r in rows]


# ---- the type from the content ----------------------------------------------------------------------------------------
def wka_sniff(head):
    if b"%PDF-" in head[:1024]:
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


SVG_DROP = {"script", "foreignobject", "iframe", "object", "embed", "audio", "video", "handler", "listener", "set", "animate",
            "animatetransform", "animatemotion", "discard"}
SVG_STYLE_BAD = re.compile(r"@import|expression\s*\(|url\s*\(\s*['\"]?\s*(?!#)", re.I)
SVG_DATA_IMG = re.compile(r"^\s*data:image/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\s]*$", re.I)
ET.register_namespace("", "http://www.w3.org/2000/svg")
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")


def _local(n):
    return n.rsplit("}", 1)[-1].lower() if isinstance(n, str) else ""


def wka_svg_clean(data):
    """An SVG without scripts, event attributes, foreign content and references outside itself (only #ids and embedded
    pictures stay); no DOCTYPE / ENTITY at all. BadInput when it cannot be cleaned."""
    bad = BadInput(tr("The SVG picture could not be cleaned"))
    if b"\x00" in data[:64] or re.search(rb"<!\s*(?:doctype|entity)", data, re.I):  # review L3: also UTF-16 / 32 (no DTD at all)
        raise bad
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError):
        raise bad
    if _local(root.tag) != "svg":
        raise bad
    for el in list(root.iter()):
        for ch in list(el):
            if not isinstance(ch.tag, str) or _local(ch.tag) in SVG_DROP or (_local(ch.tag) == "style" and SVG_STYLE_BAD.search(ch.text or "")):
                el.remove(ch)
        for k in list(el.attrib):
            v, n = el.attrib[k], _local(k)
            if n.startswith("on") or "javascript:" in v.lower().replace(" ", "") or (n == "style" and SVG_STYLE_BAD.search(v)) \
                    or (n in ("href", "src") and not v.strip().startswith("#") and not SVG_DATA_IMG.match(v)):
                del el.attrib[k]
            elif SVG_STYLE_BAD.search(v) and "url" in v.lower():  # fill="url(https://…)" and the like
                del el.attrib[k]
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode").encode("utf-8")


def wka_check(name, data):
    """(mime, bytes to store) of a file for a page, or BadInput with the reason: a supported ending whose content agrees."""
    want = WKA_TYPES.get(file_ext(name))
    if not want:
        raise BadInput(tr("Only PDF files and pictures (PNG, JPEG, GIF, WebP, SVG)"))
    if not data:
        raise BadInput(tr("The file is empty"))
    if len(data) > WKA_FILE_MAX:
        raise BadInput(tr("Larger than {0} MB", WKA_FILE_MAX // (1024 * 1024)))
    if want == SVG:
        return SVG, wka_svg_clean(data)
    if wka_sniff(data[:1024]) != want:
        raise BadInput(tr("The content does not match the file type"))
    return want, data


def wka_store(c, page, name, mime, data, uid, saved):
    """Store one checked file for a page (the caller checked the rights and commits; `saved` gets the relative path).
    Returns the new id; UploadRefused (virus) or QuotaExceeded raise on."""
    from ..files.upsafe import up_after_store, up_check
    from ..admin.hosting import quota_guard
    quota_guard(c, uid, len(data))
    data, got, info = up_check(c, name, data, mime, uid, page["org_id"], "wiki")
    if mime != SVG and got != mime:  # the scan's sniffing found another type: never stored as a picture
        raise BadInput(tr("The content does not match the file type"))
    rel = os.path.join("wiki", str(int(page["id"])), f"{uuid.uuid4().hex[:12]}-{name}")
    full = os.path.join(ATT_DIR, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    oc_write_file(c, wka_space(page), full, data, fresh=True)  # sealed at rest like task files (#828 / #1864), also private
    saved.append(rel)
    fid = insert_id(c, "INSERT INTO wiki_files(page_id,org_id,owner_id,name,mime,size,path,sha256,created_by,created_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (page["id"], page["org_id"], page["owner_id"], name, mime, len(data), rel, hashlib.sha256(data).hexdigest(),
                     uid, iso_ms(now_utc())))
    up_after_store(c, "wiki", fid, page["org_id"], info)
    return fid


# ---- routes ---------------------------------------------------------------------------------------------------------------
def wka_need(c, fid, write=False):
    """(file row, page row): the file is not in the trash and its page can be read (write: changed) by the person."""
    f = c.execute("SELECT * FROM wiki_files WHERE id=?", (fid,)).fetchone()
    if not f or f["deleted_at"]:
        raise Denied(404)
    pg = wiki_need(c, f["page_id"], write=write)  # 2.200.0 A (#2747): write = edit on the page
    if wka_locked(c, pg):
        raise Denied(404)
    return f, pg


@app.get("/api/wiki/files/<int:fid>")
@app.get("/api/wiki/files/<int:fid>/<path:name>")
def wka_get(fid, name=None):
    """A file of a page (the name in the address is only for reading; ?dl=1 downloads). SVG: as a picture in a sandbox."""
    c = db()
    f, _ = wka_need(c, fid)
    from ..files.scan import sc_guard
    sc_guard(c, "wiki", fid)  # 2.61.0 (#1818): a file found infected later stays locked
    if f["mime"] != SVG:
        return send_stored(f)
    full = os.path.join(ATT_DIR, f["path"])
    if not os.path.isfile(full):
        return err(tr("File damaged or missing"), 404)
    dl = request.args.get("dl") == "1"
    resp = oc_send_file(c, full, mimetype=SVG if not dl else "application/octet-stream", as_attachment=dl,
                        download_name=f["name"], conditional=True, max_age=0)
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp


@app.post("/api/wiki/pages/<int:pid>/files")
def wka_upload(pid):
    """multipart file (one or more, at most WKA_UPLOAD_FILES): PDFs / pictures for the page -> 201 {files}."""
    from ..files.upsafe import UploadRefused, h6d_read
    from ..admin.hosting import QuotaExceeded
    c = db()
    uid = me()
    pg = wiki_need(c, pid, write=True)  # 2.200.0 A (#2747): edit on the page
    if wka_locked(c, pg):
        raise Denied(403, tr("Files cannot be added to an encrypted space yet."))
    files = request.files.getlist("file")
    if not files:
        return err(tr("File missing"))
    if len(files) > WKA_UPLOAD_FILES:
        return err(tr("Too many files (at most {0})", WKA_UPLOAD_FILES))
    saved, ids = [], []
    try:
        for f in files:
            name = wka_name(f.filename)
            try:
                mime, data = wka_check(name, h6d_read(f, WKA_FILE_MAX))
                ids.append(wka_store(c, pg, name, mime, data, uid, saved))
            except (BadInput, UploadRefused) as e:
                c.rollback()
                unlink_files(saved)
                return err(f"{name}: {e}")
    except BaseException:  # review L1: QuotaExceeded and any other error -- no stored file without its row
        c.rollback()
        unlink_files(saved)
        raise
    c.execute("UPDATE wiki_pages SET updated_at=updated_at WHERE id=?", (pid,))
    bump(c)
    c.commit()
    rows = c.execute(f"SELECT * FROM wiki_files WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id", ids).fetchall()
    return jsonify(files=[wka_dict(r) for r in rows]), 201


@app.delete("/api/wiki/files/<int:fid>")
def wka_delete(fid):
    """To the trash (Undo: POST /api/wiki/restore {files: [id]})."""
    c = db()
    f, _ = wka_need(c, fid, write=True)
    c.execute("UPDATE wiki_files SET deleted_at=? WHERE id=?", (iso_ms(now_utc()), fid))
    bump(c)
    c.commit()
    return jsonify(ok=True, file=wka_dict(f))


def wka_bulk(c, uid, ids, trash):
    """Files to the trash / back (wiki_bulk: {files}); -> (done, skipped). Only files of pages one may change."""
    done, skipped, ts = [], [], iso_ms(now_utc())
    for fid in ids:
        f = c.execute("SELECT * FROM wiki_files WHERE id=?", (fid,)).fetchone()
        try:
            if not f or bool(f["deleted_at"]) == trash:
                raise Denied(404)
            pg = wiki_need(c, f["page_id"], write=True)  # 2.200.0 A (#2747): edit on the page
            if wka_locked(c, pg):
                raise Denied(404)
        except Denied:
            skipped.append(fid)
            continue
        c.execute("UPDATE wiki_files SET deleted_at=? WHERE id=?", (ts if trash else None, fid))
        done.append(fid)
    return done, skipped


def wka_space_has_files(c, oid, uid):
    """A file (not in the trash) in the space: the lock cannot be switched on (wikie2e.wke_start; the trashed ones go then)."""
    w, a = wiki_space_sql(oid, uid)
    return bool(c.execute(f"SELECT 1 FROM wiki_files WHERE deleted_at IS NULL AND {w} LIMIT 1", a).fetchone())


def wka_drop_trashed(c, oid, uid):
    """Review M2: switching the lock on deletes the space's files in the trash for good (no plain file stays behind in an
    encrypted space); -> their paths, unlinked by the caller after the commit."""
    w, a = wiki_space_sql(oid, uid)
    rows = c.execute(f"SELECT id, path FROM wiki_files WHERE deleted_at IS NOT NULL AND {w}", a).fetchall()
    if rows:
        ids = [r["id"] for r in rows]
        q = ",".join("?" * len(ids))
        c.execute(f"DELETE FROM upload_scan WHERE kind='wiki' AND ref_id IN ({q})", ids)
        c.execute(f"DELETE FROM file_text WHERE kind='wiki' AND ref_id IN ({q})", ids)
        c.execute(f"DELETE FROM wiki_files WHERE id IN ({q})", ids)
    return [r["path"] for r in rows]


def wka_user_files(c, uid):
    """The stored files of a person's private pages (user_purge unlinks them after the rows went with the account)."""
    return [r[0] for r in c.execute("SELECT path FROM wiki_files WHERE org_id IS NULL AND owner_id=?", (uid,))]


def wka_org_files(c, oid):
    """The stored files of an organisation's pages (orgs.org_delete unlinks them; the rows go with the organisation)."""
    return [r[0] for r in c.execute("SELECT path FROM wiki_files WHERE org_id=?", (oid,))]


def wka_move_files(c, page_ids, to, uid):
    """2.99.0 (#2182 x 2.96.0 #1941): pages moved between the private space and an organisation take their files along (also
    the ones in the trash): row org / owner as the page, the stored file sealed again with the target's key. The caller
    commits; a file read with its own header key, so a failed commit leaves every file readable."""
    ids = [int(x) for x in page_ids]
    if not ids:
        return 0
    rows = c.execute(f"SELECT id, path FROM wiki_files WHERE page_id IN ({','.join('?' * len(ids))})", ids).fetchall()
    space = int(to) if to else oc_user_space(uid)
    for r in rows:
        full = os.path.join(ATT_DIR, r["path"])
        try:
            data = oc_read_file(c, full)
        except (OSError, OrgCryptError):
            continue  # a missing / unreadable file stays as it is (the storage check reports it)
        oc_write_file(c, space, full, data, fresh=True)  # review 2 L1: plain bytes that look sealed get an outer layer
    if rows:
        q = ",".join("?" * len(rows))
        fids = [r["id"] for r in rows]
        c.execute(f"UPDATE wiki_files SET org_id=?, owner_id=? WHERE id IN ({q})", (to, None if to else uid, *fids))
        c.execute(f"UPDATE upload_scan SET org_id=? WHERE kind='wiki' AND ref_id IN ({q})", (to, *fids))
    return len(rows)


def wka_pages_have_files(c, page_ids):
    ids = [int(x) for x in page_ids]
    return bool(ids) and bool(c.execute(f"SELECT 1 FROM wiki_files WHERE page_id IN ({','.join('?' * len(ids))}) LIMIT 1", ids).fetchone())


def wka_tick(c):
    """Watchdog (review M1, rule "deleting = really gone"): a file deleted on its own (its page is not in the trash) is removed
    for good after WKA_TRASH_DAYS -- row, scan / text marks, the stored file after the commit. Files of a page in the trash
    stay with it (undo of the page); they go with the final deletion of pages (wka_page_files)."""
    from datetime import timedelta
    cut = iso_ms(now_utc() - timedelta(days=WKA_TRASH_DAYS))
    with system_ctx(c):  # housekeeping over every space: rows are only deleted, nothing is handed to a person
        rows = c.execute("SELECT f.id, f.path FROM wiki_files f JOIN wiki_pages p ON p.id=f.page_id WHERE f.deleted_at IS NOT NULL "
                         "AND f.deleted_at<? AND p.deleted_at IS NULL ORDER BY f.id LIMIT 500", (cut,)).fetchall()
        if not rows:
            return
        ids = [r["id"] for r in rows]
        q = ",".join("?" * len(ids))
        c.execute(f"DELETE FROM upload_scan WHERE kind='wiki' AND ref_id IN ({q})", ids)
        c.execute(f"DELETE FROM file_text WHERE kind='wiki' AND ref_id IN ({q})", ids)
        c.execute(f"DELETE FROM wiki_files WHERE id IN ({q})", ids)
    c.commit()
    unlink_files([r["path"] for r in rows])


def wka_page_files(c, page_ids):
    """For the final deletion of pages (after the trash): their stored files -- the caller deletes the rows (cascade) and
    unlinks these paths after the commit."""
    ids = [int(x) for x in page_ids]
    if not ids:
        return []
    return [r[0] for r in c.execute(f"SELECT path FROM wiki_files WHERE page_id IN ({','.join('?' * len(ids))})", ids)]


# ---- import ---------------------------------------------------------------------------------------------------------------
def _wka_read(z, info, cap, budget):
    """The bytes of a ZIP entry, None when it is larger than cap; budget[0] = what may still be unpacked (zip bombs: the
    sizes in the archive may lie, so the bytes are counted while reading)."""
    with z.open(info) as fh:
        data = fh.read(min(cap, budget[0]) + 1)
    budget[0] -= len(data)
    if budget[0] < 0:
        raise BadInput(tr("The archive is too large"))
    return None if len(data) > cap else data


def _wka_nfc(n):
    return unicodedata.normalize("NFC", n.replace("\\", "/"))


def _wka_target(raw):
    """A link's address as a path in the archive (None for web addresses / anchors)."""
    t = raw.strip()
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1].strip()
    if not t or t.startswith(("#", "//", "/api/wiki/files/")) or re.match(r"^[a-z][a-z0-9+.-]*:", t, re.I):
        return None
    t = re.split(r"[?#]", t, 1)[0]
    return _wka_nfc(unquote(t)).strip() or None


def wka_import_zip(c, uid, oid, replace):
    """POST /api/wiki/import (pages.wiki_import checked the space and its lock): the upload as werkzeug spooled it (memory or
    its temporary file), read as a ZIP."""
    f = request.files.get("file")
    if not f:
        raise BadInput(tr("No file"))
    saved, st = [], f.stream  # review L2: werkzeug spooled the upload already (no second copy on disk)
    try:
        st.seek(0, os.SEEK_END)
        if st.tell() > WKA_ZIP_TOTAL:
            raise BadInput(tr("The archive is too large"))
        st.seek(0)
        try:
            z = zipfile.ZipFile(st)
            infos = [i for i in z.infolist() if not i.is_dir()]
        except (zipfile.BadZipFile, ValueError, OSError):
            raise BadInput(tr("This is not a ZIP file"))
        with z:
            return _wka_import(c, uid, oid, replace, z, infos, saved)
    except BaseException:
        c.rollback()
        unlink_files(saved)
        raise


def _wka_import(c, uid, oid, replace, z, infos, saved, total=WKA_ZIP_TOTAL, max_files=WIKI_ZIP_FILES, tick=None):
    """2.177.0 (#2685): total / max_files = the limits of the route (wkimport.py: larger), tick() after every entry (the
    progress of the background import; it may raise to stop -- the caller rolls back)."""
    from ..files.upsafe import UploadRefused
    from ..admin.hosting import QuotaExceeded
    tick = tick or (lambda n=1: None)
    if len(infos) > max_files:
        raise BadInput(tr("Too many files (at most {0})", max_files))
    if sum(i.file_size for i in infos) > total:
        raise BadInput(tr("The archive is too large"))
    w, a = wiki_space_sql(oid, uid)
    created, updated, skipped, ts = [], [], [], iso_ms(now_utc())
    budget, md_left = [total], [WKA_MD_TOTAL]
    pages, files = [], {}  # pages: (id, folder, path, text) of the new / replaced ones; files: lower path -> (info, name, path)

    def skip(name, why):
        skipped.append({"name": name[:200], "reason": why})
    for i in infos:
        name = i.filename
        nm = _wka_nfc(name)
        parts = [p for p in nm.split("/") if p]
        ext = file_ext(nm)
        if "__MACOSX" in parts or (parts and parts[-1] in (".DS_Store", "Thumbs.db", "desktop.ini")):
            skip(name, tr("System file"))
            continue
        if ext == "md":
            if i.file_size > WIKI_ZIP_FILE_MAX or i.file_size > md_left[0]:
                skip(name, tr("Larger than {0} MB", WIKI_ZIP_FILE_MAX // 1_000_000) if i.file_size > WIKI_ZIP_FILE_MAX else tr("The archive is too large"))
                continue
            folder = "/".join(parts[:-1])  # the page's folder in the archive (its relative links start there)
            try:
                path = wiki_clean_path(name)
                raw = _wka_read(z, i, WIKI_ZIP_FILE_MAX, budget)
                if raw is None:
                    raise BadInput(tr("Larger than {0} MB", WIKI_ZIP_FILE_MAX // 1_000_000))
                md_left[0] -= len(raw)
                text = raw.decode("utf-8-sig", "replace")
                if text.startswith("e2e1:"):  # 2.64.3 (#1817, review M1): no ciphertext-like text in an open space
                    raise BadInput(tr("Invalid value: {0}", "body"))
            except BadInput as e:
                if str(e) == tr("The archive is too large"):
                    raise
                skip(name, str(e))
                continue
            except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError):
                skip(name, tr("The file is damaged"))
                continue
            pid = wiki_insert(c, oid, uid, path, text, ts)
            if pid:
                created.append(pid)
                pages.append((pid, folder, path, text))
                continue
            old = c.execute(f"SELECT id FROM wiki_pages WHERE deleted_at IS NULL AND {w} AND lower(path)=?", [*a, path.lower()]).fetchone()
            if replace and old and _wka_lost(c, old["id"]):  # 2.139.0 C (#2386): an unreadable page is never overwritten
                skip(name, tr("The page cannot be read (the key of its encryption is missing)"))
            elif replace and old:
                _wka_save(c, old["id"], text, uid, ts)  # 2.123.0 A (#2105, #2102): sealed, the text before in the history
                updated.append(old["id"])
                pages.append((old["id"], folder, path, text))
            else:
                skip(name, tr("A page with this name already exists"))
            continue
        if ext not in WKA_TYPES:
            skip(name, tr("Only PDF files and pictures (PNG, JPEG, GIF, WebP, SVG)"))
            continue
        if not parts or any(p in (".", "..") or p.startswith(".") for p in parts):
            skip(name, tr("Invalid value: {0}", "path"))
            continue
        if i.file_size > WKA_FILE_MAX:
            skip(name, tr("Larger than {0} MB", WKA_FILE_MAX // (1024 * 1024)))
            continue
        if i.file_size > 1 << 20 and i.file_size > WKA_RATIO * max(1, i.compress_size):  # 2.177.0 (#2685)
            skip(name, tr("The file is damaged"))
            continue
        files["/".join(parts).lower()] = (i, name, "/".join(parts))
    tick(len(infos) - len(files))  # 2.177.0 (#2685): the pages and skipped entries; the files count one by one below

    # which page links which file: resolved against the page's folder, the top of the archive and _attachments/
    by_base = {}
    for k in files:
        by_base.setdefault(posixpath.basename(k), []).append(k)

    def resolve(folder, raw):
        t = _wka_target(raw)
        if not t or file_ext(t) not in WKA_TYPES:
            return None
        cands = [t.lstrip("/")] if t.startswith("/") else [posixpath.join(folder, t), t, posixpath.join("_attachments", t),
                                                           posixpath.join("_attachments", folder, t)]
        for cd in cands:
            n = posixpath.normpath(cd).lower()
            if not n.startswith("..") and n in files:
                return n
        hit = by_base.get(posixpath.basename(t).lower()) or []
        return hit[0] if len(hit) == 1 else None

    def refs(folder, text):
        for m in WKA_WIKILINK_RE.finditer(text):
            k = resolve(folder, m.group(2).split("#", 1)[0])
            if k:
                yield k
        for m in WKA_MDLINK_RE.finditer(text):
            k = resolve(folder, m.group(3))
            if k:
                yield k
    linked = {}
    for pid, folder, path, text in pages:
        for k in refs(folder, text):
            linked.setdefault(k, [])
            if pid not in linked[k]:
                linked[k].append(pid)
    by_path = {path.lower(): pid for pid, folder, path, text in pages}

    def home(p):
        """The folder of a file without a leading _attachments/ (the export puts a page's files at _attachments/<page>/)."""
        d = posixpath.dirname(p)
        return d[len("_attachments"):].lstrip("/") if d.lower() == "_attachments" or d.lower().startswith("_attachments/") else d

    stored, new_ids, pagerows, extra = {}, [], {}, {}  # extra: page id -> lines for files nobody links
    full = [False]

    def page_row(pid):
        if pid not in pagerows:
            pagerows[pid] = c.execute("SELECT * FROM wiki_pages WHERE id=?", (pid,)).fetchone()
        return pagerows[pid]

    def imported_page(folder):
        label = tr("Imported files")
        try:
            path = wiki_clean_path(f"{folder}/{label}" if folder else label)
        except BadInput:
            path = label
        if path.lower() in by_path:
            return by_path[path.lower()]
        old = c.execute(f"SELECT id FROM wiki_pages WHERE deleted_at IS NULL AND {w} AND lower(path)=?", [*a, path.lower()]).fetchone()
        if old:
            pid = old["id"]
            if _wka_lost(c, pid):  # 2.139.0 C (#2386): its list cannot be added to -- the file is skipped, the page named once
                if not any(x["name"] == path for x in skipped):
                    skip(path, tr("The page cannot be read (the key of its encryption is missing)"))
                raise BadInput(tr("The page cannot be read (the key of its encryption is missing)") + ": " + path)
            if pid not in updated and pid not in created:
                updated.append(pid)
        else:
            pid = wiki_insert(c, oid, uid, path, "", ts)
            if pid is None:
                raise BadInput(tr("A page with this name already exists"))
            created.append(pid)
        by_path[path.lower()] = pid
        return pid
    for k in sorted(files):
        tick()
        info, name, orig = files[k]
        owners = linked.get(k) or []
        ho = home(orig)
        own = by_path.get(ho.lower())  # the page of the file's folder (export: _attachments/<page>/<name>)
        listed = False
        if owners:  # the first page that links it, the page of its folder first
            pid = own if own in owners else owners[0]
        elif own and orig.lower().startswith("_attachments/"):  # nobody links it, but the export put it at its page
            pid = own
        else:  # nobody links it: the page "Imported files" of its folder lists it (made once a file of it passed)
            pid, listed = None, True
        if full[0]:
            skip(name, tr("Your storage is full"))
            continue
        try:
            data = _wka_read(z, info, WKA_FILE_MAX, budget)
            if data is None:
                raise BadInput(tr("Larger than {0} MB", WKA_FILE_MAX // (1024 * 1024)))
            fname = wka_name(posixpath.basename(_wka_nfc(name)))
            mime, data = wka_check(fname, data)
            if pid is None:
                pid = imported_page(ho)
            pg = page_row(pid)
            same = c.execute("SELECT id FROM wiki_files WHERE page_id=? AND lower(name)=? AND sha256=? AND deleted_at IS NULL",
                             (pid, fname.lower(), hashlib.sha256(data).hexdigest())).fetchone()
            fid = same["id"] if same else wka_store(c, pg, fname, mime, data, uid, saved)
        except BadInput as e:
            if str(e) == tr("The archive is too large"):
                raise
            skip(name, str(e))
            continue
        except UploadRefused as e:
            skip(name, str(e))
            continue
        except QuotaExceeded:
            full[0] = True
            skip(name, tr("Your storage is full"))
            continue
        except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError):
            skip(name, tr("The file is damaged"))
            continue
        if not same:
            new_ids.append(fid)
        stored[k] = (fid, fname, mime)
        if listed:
            extra.setdefault(pid, []).append(k)

    # the links in the pages point at the stored files
    def md(k, bang, label):
        fid, fname, mime = stored[k]
        lb = (label or fname).replace("[", "(").replace("]", ")")
        return f"{'!' if bang and mime.startswith('image/') else ''}[{lb}]({wka_url(fid, fname)})"
    for pid, folder, path, text in pages:
        def wl(m, folder=folder):
            k = resolve(folder, m.group(2).split("#", 1)[0])
            return md(k, m.group(1), m.group(3) or posixpath.basename(m.group(2).split("#", 1)[0].strip())) if k in stored else m.group(0)

        def ml(m, folder=folder):
            k = resolve(folder, m.group(3))
            return md(k, m.group(1), m.group(2)) if k in stored else m.group(0)
        nb = WKA_MDLINK_RE.sub(ml, WKA_WIKILINK_RE.sub(wl, text))
        nb = _wka_append(nb, [md(k, True, None) for k in extra.pop(pid, [])])
        if nb != text:
            _wka_save(c, pid, nb, uid, ts)
    for pid, ks in extra.items():  # "Imported files" pages and pages outside this import
        r = page_row(pid)
        from .wkhist import wkh_body  # 2.123.0 A (#2105)
        nb = _wka_append(wkh_body(c, r), [md(k, True, None) for k in ks])
        _wka_save(c, pid, nb, uid, ts)
    if created or updated or new_ids:
        bump(c)
        c.commit()
    # 2.99.0 A (#2182): skipped stays the list of names (older callers); skipped_detail = {name, reason} for the report
    return {"ok": True, "created": created, "updated": updated, "files": new_ids, "files_n": len(stored),
            "skipped": [s["name"] for s in skipped][:200], "skipped_detail": skipped[:200], "skipped_n": len(skipped)}


def _wka_lost(c, pid):
    """2.139.0 C (#2386): page pid has a text sealed at rest that cannot be opened."""
    from .wkhist import WikiUnreadable, wkh_body
    try:
        wkh_body(c, c.execute("SELECT id, org_id, owner_id, body FROM wiki_pages WHERE id=?", (pid,)).fetchone())
    except WikiUnreadable:
        return True
    return False


def _wka_append(body, lines):
    if not lines:
        return body
    return (body.rstrip() + "\n\n" if body.strip() else "") + "\n".join(f"- {x}" for x in lines) + "\n"


def _wka_save(c, pid, text, uid, ts):
    from .wkhist import wkh_note, wkh_prev, wkh_seal  # 2.123.0 A (#2105, #2102): sealed; the text before stays in the history
    r = c.execute("SELECT * FROM wiki_pages WHERE id=?", (pid,)).fetchone()
    prev = wkh_prev(c, r)
    c.execute("UPDATE wiki_pages SET body=?, attrs=?, updated_by=?, updated_at=? WHERE id=?",
              (wkh_seal(c, r["org_id"], r["owner_id"], text), json.dumps(wiki_frontmatter(text), ensure_ascii=False), uid, ts, pid))
    wiki_set_links(c, pid, text)
    wkh_note(c, pid, uid, ts, prev=prev)


# ---- export ---------------------------------------------------------------------------------------------------------------
def wka_export_zip(c, oid, uid):
    """GET /api/wiki/export (pages.wiki_export checked the space and its lock): every page as .md, its files under
    _attachments/<page path>/<name>, the links in the pages as [[_attachments/…]] (a re-import gives the same structure).
    Written into a temporary file (the files may be large), sent and gone."""
    w, a = wiki_space_sql(oid, uid)
    pw = w.replace(" AND ", " AND p.")
    pages = c.execute(f"SELECT id, org_id, owner_id, path, body FROM wiki_pages WHERE deleted_at IS NULL AND {w} ORDER BY path", a).fetchall()
    zpath, used = {}, {}
    rows = c.execute(f"SELECT f.id, f.page_id, f.name, f.path, p.path AS ppath FROM wiki_files f JOIN wiki_pages p ON p.id=f.page_id "
                     f"WHERE f.deleted_at IS NULL AND p.deleted_at IS NULL AND p.{pw} ORDER BY f.page_id, f.id", a).fetchall()
    for r in rows:
        stem, dot, ext = r["name"].rpartition(".") if "." in r["name"].strip(".") else (r["name"], "", "")
        n, name = 1, r["name"]
        while f"{r['page_id']}/{name.lower()}" in used:
            n += 1
            name = f"{stem} ({n}){dot}{ext}"
        used[f"{r['page_id']}/{name.lower()}"] = 1
        zpath[r["id"]] = (f"_attachments/{r['ppath']}/{name}", r)

    def back(m):
        hit = zpath.get(int(m.group(3)))
        if not hit:
            return m.group(0)
        p, r = hit
        if m.group(1) and r["name"].lower().rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
            return f"![[{p}]]"
        lb = m.group(2)
        return f"[[{p}]]" if not lb or lb == r["name"] else f"[[{p}|{lb.replace('|', '/')}]]"
    from .wkhist import wsb_body_or
    os.makedirs(WKA_TMP, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="export-", suffix=".zip", dir=WKA_TMP)
    try:
        with os.fdopen(fd, "wb") as out, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for r in pages:
                text = wsb_body_or(c, r, None)  # 2.126.2 B (#2358): an unreadable page is left out, never its ciphertext
                if text is not None:
                    z.writestr(r["path"] + ".md", WKA_URL_RE.sub(back, text or ""))  # 2.123.0 A (#2105): opened
            for p, r in zpath.values():
                try:
                    data = oc_read_file(c, os.path.join(ATT_DIR, r["path"]))
                except OSError:
                    continue  # a missing file (storage check reports it) does not stop the export
                z.writestr(p, data, compress_type=zipfile.ZIP_DEFLATED if p.lower().endswith(".svg") else zipfile.ZIP_STORED)
        fh = open(tmp, "rb")
    finally:
        os.remove(tmp)  # the open handle keeps the bytes until the answer is sent
    return send_file(fh, mimetype="application/zip", as_attachment=True, download_name="wiki.zip")
