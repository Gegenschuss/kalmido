"""Group pictures (2.46.0, #1605): a preset or an own photo per group, like the profile pictures of people."""
import contextlib
import os
import re
import secrets

from flask import jsonify, request, send_file

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err
from ..core.access import Denied, list_role
from ..accounts.pictures import AVATAR_DIR, AVATAR_MAX_MB, AVATAR_PRESETS, avatar_process
from ..lists.groups import need_group
from ..lists.lists import folder_under


# ---- 2.46.0 (#1605): groups.avatar = '' (the group symbol, as before) | 'p:<preset>' (the presets of the profile pictures) |
# 'u:<token>' (an own photo, re-encoded by avatar_process: square JPEG, no metadata) stored as ATT_DIR/avatars/g<id>-<token>.jpg
# (so backups include it). Whoever may manage the group changes it; served with login to everybody who may see the group
# (as GET /api/groups) or a list shared with it; new picture = new token = new URL (cached for good).
FG_TOK = r"[A-Za-z0-9_-]{8,40}"


def fg_avatar_url(r):
    """The picture URL of group row / dict r ('' = none)."""
    try:
        a = r["avatar"] or ""
    except (IndexError, KeyError):
        return ""
    if a.startswith("p:") and a[2:] in AVATAR_PRESETS:
        return f"/static/avatars/{a[2:]}.svg"
    if a.startswith("u:") and re.fullmatch(FG_TOK, a[2:]):
        return f"/api/group-avatar/{r['id']}/{a[2:]}.jpg"
    return ""


def fg_avatar_path(gid, tok):
    return os.path.join(AVATAR_DIR, f"g{int(gid)}-{tok}.jpg")


def fg_drop_file(gid, a):
    if a and a.startswith("u:") and re.fullmatch(FG_TOK, a[2:]):
        with contextlib.suppress(OSError):
            os.remove(fg_avatar_path(gid, a[2:]))


def fg_need_manage(c, gid):
    """Who may change a group (as PATCH /api/admin/groups/<gid>) may change its picture."""
    from ..accounts.users import need_admin
    need_admin()
    return need_group(c, gid)


def fg_may_see(c, gid):
    """The group is visible to me (as in GET /api/groups), or a list I see is shared with it (directly or through a folder)."""
    from ..lists.groups import grp_visible
    r = c.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()
    if not r:
        return False
    if grp_visible(c, r):
        return True
    for s in c.execute("SELECT list_id, owner_id, folder FROM group_shares WHERE group_id=?", (gid,)).fetchall():
        if s["list_id"]:
            if list_role(c, s["list_id"]):
                return True
        elif s["owner_id"] and s["folder"]:
            for x in c.execute("SELECT id, folder FROM lists WHERE owner_id=? AND folder!='' AND is_inbox=0", (s["owner_id"],)).fetchall():
                if folder_under(x["folder"], s["folder"]) and list_role(c, x["id"]):
                    return True
    return False


def _fg_set(c, gid, value):
    old = c.execute("SELECT avatar FROM groups WHERE id=?", (gid,)).fetchone()
    c.execute("UPDATE groups SET avatar=? WHERE id=?", (value, gid))
    bump(c)
    c.commit()
    if old and old[0] != value:
        fg_drop_file(gid, old[0])
    return jsonify(avatar=fg_avatar_url({"id": gid, "avatar": value}))


@app.put("/api/admin/groups/<int:gid>/avatar")
def fg_avatar_preset(gid):
    """{preset: "coffee" | ... | null}: a preset picture for the group, or none (the group symbol)."""
    c = db()
    fg_need_manage(c, gid)
    p = body().get("preset")
    if p is not None and p not in AVATAR_PRESETS:
        return err(tr("Invalid value: {0}", "preset"))
    return _fg_set(c, gid, f"p:{p}" if p else "")


@app.post("/api/admin/groups/<int:gid>/avatar")
def fg_avatar_upload(gid):
    """multipart "file": an own photo for the group (JPEG / PNG / WebP, up to AVATAR_MAX_MB MB), stored as a square JPEG."""
    from ..personal.timetrack import BadInput
    c = db()
    fg_need_manage(c, gid)
    f = request.files.get("file")
    if not f:
        return err(tr("No file"))
    raw = f.read(AVATAR_MAX_MB * 1024 * 1024 + 1)
    if len(raw) > AVATAR_MAX_MB * 1024 * 1024:
        return err(tr("The picture is too large (at most {0} MB)", AVATAR_MAX_MB), 413)
    try:
        jpg = avatar_process(raw)
    except BadInput as e:
        return err(str(e))
    tok = secrets.token_urlsafe(12)
    os.makedirs(AVATAR_DIR, exist_ok=True)
    tmp = fg_avatar_path(gid, tok) + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(jpg)
    os.replace(tmp, fg_avatar_path(gid, tok))
    return _fg_set(c, gid, "u:" + tok)


@app.delete("/api/admin/groups/<int:gid>/avatar")
def fg_avatar_delete(gid):
    c = db()
    fg_need_manage(c, gid)
    return _fg_set(c, gid, "")


@app.get("/api/group-avatar/<int:gid>/<tok>.jpg")
def fg_avatar_get(gid, tok):
    """A group's own photo: for everybody who may see the group."""
    c = db()
    r = c.execute("SELECT id, avatar FROM groups WHERE id=?", (gid,)).fetchone()
    if not r or r["avatar"] != "u:" + tok or not re.fullmatch(FG_TOK, tok) or not fg_may_see(c, gid):
        raise Denied(404)
    p = fg_avatar_path(gid, tok)
    if not os.path.isfile(p):
        raise Denied(404)
    rs = send_file(p, mimetype="image/jpeg", max_age=31536000)
    rs.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return rs
