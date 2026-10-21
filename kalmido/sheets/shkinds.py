"""2.124.0 B (#2110, #2111): more column kinds of a table and the rows / columns that stay in view.

Kinds (sheets/core.py SH_KINDS): checkbox (raw "1" / "0"; 1 / 0 in formulas, so SUMME counts the ticks), person (raw = the
account id; shown with the name only for the people who may see the table, anyone else / a deleted account reads "Unknown"),
link (http / https / mailto only, anything else is refused) and file (raw "file:<id>" of a row in sheet_files: the bytes
sealed like task files, ATT_DIR/sheets/<sheet id>/, read only with the right to read the table). A cell that no longer holds
its file puts the file into the trash (deleted_at; Undo of the cell brings it back), the watchdog removes it for good after
SHK_TRASH_DAYS. Changing a column's kind keeps every input as it was (an input that does not fit reads as text).

freeze_rows / freeze_cols (sheets columns): the first N rows / columns stay in view while scrolling (the client makes them
sticky); changed with the right to write the table. Not to be mixed up with sh_freeze (a cell's value kept as a copy).
"""
import mimetypes
import os
import re
import uuid
from datetime import timedelta

from flask import jsonify, request

from ..core.access import Denied, list_people, need_feat
from ..core.config import ATT_DIR, MAX_FILE_MB, app
from ..core.db import db, err, insert_id, iso_ms, now_utc, body
from ..core.i18n import tr
from ..core.orgcrypt import OrgCryptError, oc_read_file, oc_user_space, oc_write_file
from ..core.serializers import unlink_files
from ..accounts.session import me
from ..collab.comments import user_names
from ..core.errors import BadInput
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions

SHK_KINDS = ("checkbox", "person", "link", "file")
SHK_TRUE = {"1", "x", "✓", "true", "wahr", "yes", "ja", "si", "sí", "oui", "vrai", "waar"}
SHK_FALSE = {"0", "false", "falsch", "no", "nein", "non", "nee", "faux", "onwaar", "falso"}
SHK_LINK_RE = re.compile(r"(?i)(?:https?://[^\s<>\"']+|mailto:[^\s<>\"']+)")
SHK_BARE_RE = re.compile(r"(?i)(?:www\.)?[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,24}(?:[/?#][^\s<>\"']*)?")
SHK_FILE_RE = re.compile(r"file:(\d{1,15})")
SHK_LINK_MAX = 2000
SHK_TRASH_DAYS = 30
SHK_FREEZE_ROWS, SHK_FREEZE_COLS = 50, 20


# ---------------------------------------------------------------- people of a sheet
def shk_people(c, sheet_row):
    """{account id: name} of the people a person column of this sheet offers: those who may see the table -- the attached
    list's owner and members, else the organisation's members, else (private) the owner. People only (no agents, no
    disabled accounts), plus the people a single table is shared with (2.124.0 C, #2113)."""
    from .core import sh_list_bound
    l = sh_list_bound(c, sheet_row)
    if l is not None:
        ids = set(list_people(c, l["id"]))
    elif sheet_row["org_id"]:
        # 2.143.0 A (#2151, review): who sees the organisation's tables (admin, member, read-only); guests only by a share below
        ids = {r[0] for r in c.execute("SELECT user_id FROM org_members WHERE org_id=? AND role IN ('admin','member','readonly')", (sheet_row["org_id"],))}
    else:
        ids = {sheet_row["owner_id"]} if sheet_row["owner_id"] else set()
    # 2.124.0 (#2113): + the people this one table is shared with (agents drop out below)
    ids |= {r[0] for r in c.execute("SELECT user_id FROM sheet_shares WHERE sheet_id=? AND revoked_at IS NULL", (sheet_row["id"],))}
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    ok = {r[0] for r in c.execute(f"SELECT id FROM users WHERE id IN ({q}) AND disabled=0 AND COALESCE(kind, 'user')<>'agent'", ids)}
    names = user_names(c, ok)
    return {i: names.get(i, "") for i in sorted(ok, key=lambda i: (names.get(i, "").lower(), i))}


def _people_of(ev):
    p = getattr(ev, "_shk_people", None)
    if p is None:
        p = ev._shk_people = shk_people(ev.c, ev.book.sheet)
    return p


def _files_of(ev):
    f = getattr(ev, "_shk_files", None)
    if f is None:
        f = ev._shk_files = {r["id"]: r["name"] for r in ev.c.execute(
            "SELECT id, name FROM sheet_files WHERE sheet_id=?", (ev.book.sheet["id"],))}
    return f


def shk_bool(raw):
    """True / False of a checkbox input, None when empty, "" when it is no yes / no."""
    t = (raw or "").strip().lower()
    if not t:
        return None
    return True if t in SHK_TRUE else False if t in SHK_FALSE else ""


# ---------------------------------------------------------------- the value of a typed input (ShEvaluator.plain)
def shk_plain(ev, x, kind):
    """The result of a typed (non-formula) input in a column of one of the SHK_KINDS."""
    raw = x["raw"] or ""
    t = raw.strip()
    if not t:
        return ev.out(None, kind, "own")
    if kind == "checkbox":
        b = shk_bool(t)
        if b in (True, False):
            r = ev.out(1.0 if b else 0.0, kind, "own")
            r["display"] = tr("Yes") if b else tr("No")
            return r
    elif kind == "person" and t.isdigit():
        name = _people_of(ev).get(int(t))
        r = ev.out(name or tr("Unknown"), kind, "own")
        return r
    elif kind == "file":
        m = SHK_FILE_RE.fullmatch(t)
        if m:
            name = _files_of(ev).get(int(m.group(1)))
            return ev.out(name or tr("File missing"), kind, "own")
    r = ev.out(raw, kind, "own")  # a link, or an input from before the kind changed: text as typed
    r["display"] = raw
    return r


# ---------------------------------------------------------------- an input -> the stored raw (core._write_cells)
def shk_link(raw):
    """A link as stored (http / https / mailto; a bare www.example.com gets https://) or BadInput."""
    t = (raw or "").strip()
    if not t:
        return ""
    if len(t) > SHK_LINK_MAX or re.search(r"[\x00-\x20\x7f]", t):
        raise BadInput(tr("Web address expected"))
    if SHK_LINK_RE.fullmatch(t):
        return t
    if SHK_BARE_RE.fullmatch(t) and "@" not in t:
        return "https://" + t
    if re.fullmatch(r"[^@\s:/]+@[^@\s:/]+\.[A-Za-z]{2,24}", t):
        return "mailto:" + t
    raise BadInput(tr("Web address expected"))


def shk_raw(c, book, col, row_id, raw):
    """The stored form of a plain input in a column of the SHK_KINDS (BadInput when it does not fit): checkbox "1" / "0",
    person = the id of someone who may see the table (a name is looked up), link checked, file only "file:<id>" of this
    sheet (Undo / paste) -- the file of the input before goes to the trash when no other cell holds it."""
    kind = col["kind"]
    t = (raw or "").strip()
    if kind == "checkbox":
        b = shk_bool(t)
        if b == "":
            raise BadInput(tr("Yes or no expected"))
        out = "" if b is None else "1" if b else "0"
    elif kind == "person":
        out = ""
        if t:
            people = getattr(book, "_shk_people", None)
            if people is None:
                people = book._shk_people = shk_people(c, book.sheet)
            x = book.at.get((row_id, col["id"]))
            if t.isdigit() and (int(t) in people or (x and (x["raw"] or "").strip() == t)):
                out = str(int(t))
            else:
                low = t.casefold()
                hit = [i for i, n in people.items() if n and n.casefold() == low]
                if len(hit) != 1:
                    raise BadInput(tr("This person cannot see the table"))
                out = str(hit[0])
    elif kind == "link":
        out = shk_link(t)
    else:  # file
        out = ""
        if t:
            m = SHK_FILE_RE.fullmatch(t)
            if not m or not c.execute("SELECT 1 FROM sheet_files WHERE id=? AND sheet_id=?", (int(m.group(1)), book.sheet["id"])).fetchone():
                raise BadInput(tr("Upload the file into the cell"))
            out = t
    if kind == "file":
        _shk_file_swap(c, book, col["id"], row_id, out)
    return out


def _shk_file_swap(c, book, col_id, row_id, new):
    """A file cell gets another input: the file it held goes to the trash (unless another cell holds it too, also one of a
    row / column in the trash), the file it gets now comes out of the trash."""
    x = book.at.get((row_id, col_id))
    old = (x["raw"] or "").strip() if x else ""
    if old == new:
        return
    ts = iso_ms(now_utc())
    m = SHK_FILE_RE.fullmatch(old)
    if m and not any((y["raw"] or "").strip() == old for y in book.cells.values() if y is not x):  # also rows / columns in the trash (their Undo)
        c.execute("UPDATE sheet_files SET deleted_at=? WHERE id=? AND sheet_id=? AND deleted_at IS NULL", (ts, int(m.group(1)), book.sheet["id"]))
    m = SHK_FILE_RE.fullmatch(new)
    if m:
        c.execute("UPDATE sheet_files SET deleted_at=NULL WHERE id=? AND sheet_id=?", (int(m.group(1)), book.sheet["id"]))


# ---------------------------------------------------------------- import / export (sheets/io.py)
def shk_export(col, r, v, lg, csv=False):
    """The exported value of a cell of the SHK_KINDS: a checkbox as a truth value (CSV: WAHR / FALSCH in German, else
    TRUE / FALSE), a person as the name, a link as its text, a file as its name; other kinds unchanged."""
    if not col or col["kind"] not in SHK_KINDS or v is None:
        return v
    if col["kind"] == "checkbox" and isinstance(v, float) and v in (0.0, 1.0) and r and r.get("origin") == "own":
        if csv:
            de = (lg or "").split("-")[0].lower() == "de"
            return ("WAHR" if v else "FALSCH") if de else ("TRUE" if v else "FALSE")
        return bool(v)
    return v


def shk_guess(vals):
    """2.124.0 B (#2110): an import column of truth values only (WAHR / FALSCH, TRUE / FALSE) becomes a checkbox column."""
    vals = [v.strip().upper() for v in vals if v and v.strip()]
    return bool(vals) and all(v in ("WAHR", "FALSCH", "TRUE", "FALSE") for v in vals)


# ---------------------------------------------------------------- files of file cells
def shk_space(r):
    """The key space of a sheet's files (orgcrypt): its organisation, else its owner's account."""
    return int(r["org_id"]) if r["org_id"] else oc_user_space(r["owner_id"])


def shk_file_dict(f, sid):
    return {"id": f["id"], "name": f["name"], "mime": f["mime"], "size": f["size"], "created_at": f["created_at"],
            "url": f"/api/sheets/{int(sid)}/files/{int(f['id'])}"}


@app.get("/api/sheets/<int:sid>/people")
def shk_people_get(sid):
    """The people a person cell of this table may name (those who may see it) -> {people: [{id, name}]}."""
    from .core import sh_need
    c = db()
    r = sh_need(c, sid)
    return jsonify(people=[{"id": i, "name": n} for i, n in shk_people(c, r).items()])


@app.post("/api/sheets/<int:sid>/files")
def shk_upload(sid):
    """multipart file + row_id + col_id (a file column): the file into that cell (sealed at rest) -> 201 {file, cells, rev,
    old_raw} (old_raw = the cell's input before: the app's Undo writes it back through PUT .../cells)."""
    from ..admin.hosting import quota_guard
    from ..files.upsafe import UploadRefused, h6d_read, up_after_store, up_check
    from ..tasks.attachments import safe_name
    from .core import ShBook, sh_need, sh_reload, sh_set_cells
    need_feat("sheets")
    c = db()
    uid = me()
    r = sh_need(c, sid, write=True)
    try:
        rid, cid = int(request.form.get("row_id") or 0), int(request.form.get("col_id") or 0)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "cell")) from None
    book = ShBook(c, r)
    col = book.col_by.get(cid)
    if rid not in book.row_idx or col is None:
        raise BadInput(tr("Invalid value: {0}", "cell"))
    if col["kind"] != "file":
        raise BadInput(tr("Files go into a column of the kind File"))
    f = request.files.get("file")
    if not f:
        return err(tr("File missing"))
    name = safe_name(f.filename)
    data = h6d_read(f, MAX_FILE_MB * 1024 * 1024)
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        return err(tr("{0}: larger than {1} MB", name, MAX_FILE_MB))
    if not data:
        return err(tr("{0}: the file is empty and was not uploaded", name))
    x = book.at.get((rid, cid))
    old = x["raw"] if x else ""
    quota_guard(c, uid, len(data))
    mime = (f.mimetype if f.mimetype and f.mimetype != "application/octet-stream" else None) or mimetypes.guess_type(name)[0] \
        or "application/octet-stream"
    try:
        data, mime, info = up_check(c, name, data, mime, uid, r["org_id"], "sheet")
    except UploadRefused as e:
        return err(f"{name}: {e}")
    rel = os.path.join("sheets", str(int(sid)), f"{uuid.uuid4().hex[:12]}-{name}")
    full = os.path.join(ATT_DIR, rel)
    try:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        oc_write_file(c, shk_space(r), full, data, fresh=True)  # sealed at rest like task files (#828 / #1864), also private
        fid = insert_id(c, "INSERT INTO sheet_files(sheet_id,org_id,owner_id,name,mime,size,path,created_by,created_at) "
                           "VALUES(?,?,?,?,?,?,?,?,?)", (sid, r["org_id"], r["owner_id"], name, mime, len(data), rel, uid, iso_ms(now_utc())))
        up_after_store(c, "sheet", fid, r["org_id"], info)
        cells = sh_set_cells(c, r, [{"row_id": rid, "col_id": cid, "raw": f"file:{fid}"}], uid)
        c.commit()
    except BaseException:  # no stored file without its row
        c.rollback()
        unlink_files([rel])
        raise
    fr = c.execute("SELECT * FROM sheet_files WHERE id=?", (fid,)).fetchone()
    return jsonify(file=shk_file_dict(fr, sid), cells=cells, rev=sh_reload(c, sid)["rev"], old_raw=old), 201


@app.get("/api/sheets/<int:sid>/files/<int:fid>")
@app.get("/api/sheets/<int:sid>/files/<int:fid>/<path:name>")
def shk_file_get(sid, fid, name=None):
    """A file of a file cell (?dl=1 downloads) -- only with the right to read the table."""
    from ..files.scan import sc_guard
    from ..tasks.attachments import send_stored
    from .core import sh_need
    c = db()
    sh_need(c, sid)
    f = c.execute("SELECT * FROM sheet_files WHERE id=? AND sheet_id=? AND deleted_at IS NULL", (fid, sid)).fetchone()
    if not f:
        raise Denied(404)
    sc_guard(c, "sheet", fid)  # a file found infected later stays locked
    return send_stored(f)


@app.post("/api/sheets/<int:sid>/fixed")
def shk_fixed(sid):
    """{rows, cols}: the first N rows / columns stay in view while scrolling (0 = none) -> {ok, rev, freeze_rows, freeze_cols}."""
    from .core import sh_need, sh_reload, sh_touch
    need_feat("sheets")
    c = db()
    r = sh_need(c, sid, write=True)
    b = body()
    out = {}
    for k, col, top in (("rows", "freeze_rows", SHK_FREEZE_ROWS), ("cols", "freeze_cols", SHK_FREEZE_COLS)):
        if k in b:
            v = b[k]
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= top:
                raise BadInput(tr("Invalid value: {0}", k))
            out[col] = v
    if out:
        c.execute(f"UPDATE sheets SET {','.join(k + '=?' for k in out)} WHERE id=?", [*out.values(), sid])
        sh_touch(c, sid, me())
    c.commit()
    r = sh_reload(c, sid)
    return jsonify(ok=True, rev=r["rev"], freeze_rows=r["freeze_rows"], freeze_cols=r["freeze_cols"])


# ---------------------------------------------------------------- the files' life (watchdog, move, purge)
def shk_tick(c):
    """Watchdog (rule "deleting = really gone"): a file no cell holds any more is removed for good after SHK_TRASH_DAYS --
    row, scan / text marks, the stored file after the commit. Files of a table in the trash stay with it (its Undo)."""
    cut = iso_ms(now_utc() - timedelta(days=SHK_TRASH_DAYS))
    with system_ctx(c):  # housekeeping over every space: rows are only deleted, nothing is handed to a person
        rows = c.execute("SELECT f.id, f.path FROM sheet_files f JOIN sheets s ON s.id=f.sheet_id WHERE f.deleted_at IS NOT NULL "
                         "AND f.deleted_at<? AND s.deleted_at IS NULL ORDER BY f.id LIMIT 500", (cut,)).fetchall()
        if not rows:
            return
        ids = [r["id"] for r in rows]
        q = ",".join("?" * len(ids))
        c.execute(f"DELETE FROM upload_scan WHERE kind='sheet' AND ref_id IN ({q})", ids)
        c.execute(f"DELETE FROM file_text WHERE kind='sheet' AND ref_id IN ({q})", ids)
        c.execute(f"DELETE FROM sheet_files WHERE id IN ({q})", ids)
    c.commit()
    unlink_files([r["path"] for r in rows])


def shk_move_files(c, sid, to, uid):
    """A table moved between the private space and an organisation (sheets/shmove.py) takes its files along (also the ones
    in the trash): row org / owner as the sheet, the stored file sealed again with the target's key. The caller commits."""
    rows = c.execute("SELECT id, path FROM sheet_files WHERE sheet_id=?", (sid,)).fetchall()
    space = int(to) if to else oc_user_space(uid)
    for r in rows:
        full = os.path.join(ATT_DIR, r["path"])
        try:
            data = oc_read_file(c, full)
        except (OSError, OrgCryptError):
            continue  # a missing / unreadable file stays as it is (the storage check reports it)
        oc_write_file(c, space, full, data, fresh=True)
    if rows:
        fids = [r["id"] for r in rows]
        q = ",".join("?" * len(fids))
        c.execute(f"UPDATE sheet_files SET org_id=?, owner_id=? WHERE id IN ({q})", (to, None if to else uid, *fids))
        c.execute(f"UPDATE upload_scan SET org_id=? WHERE kind='sheet' AND ref_id IN ({q})", (to, *fids))
    return len(rows)


def shk_user_files(c, uid):
    """The stored files of a person's private tables (user_purge unlinks them after the rows went with the account)."""
    return [r[0] for r in c.execute("SELECT f.path FROM sheet_files f JOIN sheets s ON s.id=f.sheet_id WHERE s.org_id IS NULL AND s.owner_id=?", (uid,))]


def shk_org_files(c, oid):
    """The stored files of an organisation's tables (orgs.org_delete unlinks them; the rows go with the organisation)."""
    return [r[0] for r in c.execute("SELECT f.path FROM sheet_files f JOIN sheets s ON s.id=f.sheet_id WHERE s.org_id=?", (oid,))]
