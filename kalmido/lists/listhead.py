"""2.83.0 C (#1427): the header strip of a list (and of an owner's folder): a slim band on top of the list view, a gradient
from the list colour, one of a few CSS patterns or an own picture. It belongs to the list (the same for every member); the
owner and the list admins set it, like the list's colour and icon. The own picture is re-encoded (Pillow: JPEG, no metadata,
at most HEAD_W x HEAD_H), sealed like the list icons (an organisation list's picture with its key) and served to everybody
who may see the list. A locked list (end-to-end, #1817) gets no own picture: the server would see it in plain."""
import contextlib
import io
import os
import re
import secrets

from flask import g, jsonify, request

from ..core.config import app, ATT_DIR
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..core.access import Denied, list_role, need_list
from ..accounts.session import me
from ..core.errors import BadInput
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions
from ..core.orgcrypt import oc_list_space, oc_send_file, oc_write_file  # 2.149.0 G (#2517): pulled up from functions

HEAD_STYLES = ("", "gradient", "dots", "lines", "grid", "image")
FOLDER_HEAD_STYLES = ("", "gradient", "dots", "lines", "grid")  # a folder has no own picture
HEAD_MAX_MB = 2
HEAD_W, HEAD_H = 1600, 800
HEAD_DIR = os.path.join(ATT_DIR, "listheads")
_TOK = re.compile(r"[A-Za-z0-9_-]{8,40}")


def o3c_head_rel(lid, tok):
    """The picture's path below ATT_DIR."""
    return os.path.join("listheads", f"l{int(lid)}-{tok}.jpg")


def o3c_head_files(c, oid=None):
    """{full path: org id} of the lists' header pictures (all lists, or those of organisation oid) for the encryption
    tools (admin/orgcrypt_cli.py, like the list icons)."""
    with system_ctx(c):  # orgcrypt: server-side bulk work on stored files, never content handed to a person
        rows = c.execute("SELECT id, header_file, org_id FROM lists WHERE header_file!=''" + ("" if oid is None else " AND org_id=?"),
                         () if oid is None else (oid,)).fetchall()
    return {os.path.join(ATT_DIR, o3c_head_rel(r[0], r[1])): r[2] for r in rows if _TOK.fullmatch(r[1] or "")}


def o3c_head_drop(lid, tok):
    if tok and _TOK.fullmatch(tok):
        with contextlib.suppress(OSError):
            os.remove(os.path.join(ATT_DIR, o3c_head_rel(lid, tok)))


def o3c_head_process(raw):
    """Upload bytes -> JPEG bytes (at most HEAD_W x HEAD_H, no metadata). BadInput for anything that is not a JPEG / PNG /
    WebP picture (the content decides, not the name or the type the browser sends)."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise BadInput(tr("Photos are not available on this server"))
    Image.MAX_IMAGE_PIXELS = 30_000_000
    try:
        im = Image.open(io.BytesIO(raw))  # reads the header only
        if im.format not in ("JPEG", "PNG", "WEBP"):
            raise BadInput(tr("Please choose a JPEG, PNG or WebP picture"))
        if im.width * im.height > 20_000_000:  # 2.83.0 review: a 1600 x 800 strip needs no more (PNG / WebP decode in full)
            raise BadInput(tr("This picture cannot be read"))
        if im.format == "JPEG":
            im.draft("RGB", (HEAD_W, HEAD_H))
        im.load()
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        else:
            im = im.convert("RGB")
        im.thumbnail((HEAD_W, HEAD_H), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=82, optimize=True)  # a new file: no EXIF, GPS or ICC data carried over
        return out.getvalue()
    except BadInput:
        raise
    except Exception:  # noqa: BLE001  (decompression bomb, truncated, unknown format ...)
        raise BadInput(tr("This picture cannot be read"))


def _no_agent():
    if g.user["kind"] == "agent":  # the strip is a setting of the people's app; agents keep to the v1 API
        raise Denied(403)


def _out(c, lid):
    r = c.execute("SELECT header_style, header_file FROM lists WHERE id=?", (lid,)).fetchone()
    return jsonify(header_style=r["header_style"], header_file=r["header_file"])


@app.put("/api/lists/<int:lid>/header")
def o3c_head_put(lid):
    """{style: '' | gradient | dots | lines | grid | image} -- the owner or a list admin sets the list's header strip ('image'
    only when the list has a picture)."""
    c = db()
    _no_agent()
    need_list(c, lid, manage=True)
    st = body().get("style")
    if st is None:
        st = ""
    if st not in HEAD_STYLES:
        return err(tr("Invalid value: {0}", "style"))
    if st == "image" and not c.execute("SELECT header_file FROM lists WHERE id=?", (lid,)).fetchone()[0]:
        return err(tr("Invalid value: {0}", "style"))
    if st == "image":  # 2.83.0 review: a list locked after the upload shows no own picture
        from ..collab.liste2e import le2e_mode
        if le2e_mode(c, lid):
            return err(tr("A locked list has no own header picture"), 409)
    c.execute("UPDATE lists SET header_style=? WHERE id=?", (st, lid))
    bump(c)
    c.commit()
    return _out(c, lid)


@app.post("/api/lists/<int:lid>/header")
def o3c_head_upload(lid):
    """multipart "file": an own picture for the header strip (JPEG / PNG / WebP, up to HEAD_MAX_MB MB). Not for a locked list."""
    from ..collab.liste2e import le2e_mode
    c = db()
    _no_agent()
    need_list(c, lid, manage=True)
    if le2e_mode(c, lid):
        return err(tr("A locked list has no own header picture"), 409)
    f = request.files.get("file")
    if not f:
        return err(tr("No file"))
    raw = f.read(HEAD_MAX_MB * 1024 * 1024 + 1)
    if len(raw) > HEAD_MAX_MB * 1024 * 1024:
        return err(tr("The picture is too large (at most {0} MB)", HEAD_MAX_MB), 413)
    try:
        jpg = o3c_head_process(raw)
    except BadInput as e:
        return err(str(e))
    tok = secrets.token_urlsafe(12)
    os.makedirs(HEAD_DIR, exist_ok=True)
    # sealed at rest with the list's space key (organisation, else the owner's account), as attachments are
    oc_write_file(c, oc_list_space(c, lid), os.path.join(ATT_DIR, o3c_head_rel(lid, tok)), jpg, fresh=True)
    old = c.execute("SELECT header_file FROM lists WHERE id=?", (lid,)).fetchone()[0]
    c.execute("UPDATE lists SET header_style='image', header_file=? WHERE id=?", (tok, lid))
    bump(c)
    c.commit()
    if old and old != tok:
        o3c_head_drop(lid, old)
    return _out(c, lid)


@app.get("/api/list-header/<int:lid>/<tok>.jpg")
def o3c_head_get(lid, tok):
    """A list's header picture: for everybody who sees the list (and the admins of its organisation, as the list icon)."""
    c = db()
    r = c.execute("SELECT header_file FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or not _TOK.fullmatch(tok) or r["header_file"] != tok or not list_role(c, lid):
        from ..accounts.orglists import ole_org_admin
        if not r or r["header_file"] != tok or not _TOK.fullmatch(tok) or not ole_org_admin(c, lid):
            raise Denied(404)
    from ..collab.liste2e import le2e_mode
    if le2e_mode(c, lid):  # 2.83.0 review: locked after the upload = no own picture any more
        raise Denied(404)
    p = os.path.join(ATT_DIR, o3c_head_rel(lid, tok))
    if not os.path.isfile(p):
        raise Denied(404)
    rs = oc_send_file(c, p, mimetype="image/jpeg", max_age=31536000)
    rs.headers["Cache-Control"] = "private, max-age=31536000, immutable"  # a new picture = a new token = a new URL
    return rs


# ---- an owner's folders: the style only (no picture), per owner like the folder defaults (folder_props)
@app.get("/api/folder-heads")
def o3c_folder_heads():
    c = db()
    rows = c.execute("SELECT folder, style FROM folder_heads WHERE owner_id=?", (me(),)).fetchall()
    return jsonify(heads={r["folder"]: r["style"] for r in rows if r["style"]})


@app.put("/api/folder-heads")
def o3c_folder_head_put():
    """{folder, style: '' | gradient | dots | lines | grid} -- the strip of one of my folders ('' removes it)."""
    from ..lists.lists import clean_folder
    c, b = db(), body()
    _no_agent()
    try:
        f = clean_folder(b.get("folder") or "")
    except BadInput as e:
        return err(str(e))
    st = b.get("style") or ""
    if not f or st not in FOLDER_HEAD_STYLES:
        return err(tr("Invalid value: {0}", "style" if f else "folder"))
    if st:
        c.execute("INSERT INTO folder_heads(owner_id,folder,style,updated_at) VALUES(?,?,?,?) ON CONFLICT(owner_id,folder) "
                  "DO UPDATE SET style=excluded.style, updated_at=excluded.updated_at", (me(), f, st, iso(now_utc())))
    else:
        c.execute("DELETE FROM folder_heads WHERE owner_id=? AND folder=?", (me(), f))
    c.commit()
    return o3c_folder_heads()
