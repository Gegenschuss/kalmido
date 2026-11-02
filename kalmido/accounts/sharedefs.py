"""2.470.0 (#3596): the sharing defaults of a workspace: what a new external link and a new file request start with.

A setting of the workspace, not of the office (files work without it): an organisation keeps it in orgs.share_defaults (its
admins change it, PATCH /api/orgs/<id>), the private workspace in the person's setting "share_defaults" (PATCH /api/settings).
Stored json with only the fields someone chose; a missing field = the built-in value. A private folder counts for whoever
works in it: their own defaults. These are starting values only: the limits of the requests (files/filereq.py) and the switches
"external links" of the organisation and the server keep their say, and every stored value is held to today's limits again
when it is read (the limits come from the environment and can shrink)."""
import json

from flask import g, jsonify, request

from ..core.config import MAX_FILE_MB, app
from ..core.db import db, usettings
from ..core.errors import BadInput, Denied
from ..core.i18n import tr
from .session import me
from .wsareas import WSA_KEY_RE
from .orgs import instance_mode, org_need_person  # 2.369.5 (#2517): pulled up from functions

# the limits of a file request and the kinds it may allow (endings; the default is documents + pictures), here because the
# defaults are held to them below the file store (files/filereq.py uses them, FRQ_NEVER there stays out of every kind)
FRQ_DAYS_DEFAULT, FRQ_DAYS_MAX = 14, 90
FRQ_FILES_DEFAULT, FRQ_FILES_MAX = 20, 200
FRQ_MB_DEFAULT = min(25, MAX_FILE_MB)
FRQ_TYPES = {
    "docs": ("pdf", "txt", "csv", "md", "rtf", "odt", "ods", "odp", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "xml", "eml"),
    "images": ("jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "avif", "tif", "tiff", "bmp"),
    "design": ("ai", "eps", "psd", "indd", "idml"),
    "archives": ("zip", "7z", "rar", "tar", "gz"),
    "media": ("mp3", "m4a", "wav", "aac", "ogg", "mp4", "mov", "m4v", "webm"),
}
FRQ_TYPES_DEFAULT = ("docs", "images")
SD_LINK_EXPIRES = ("1d", "7d", "30d", "none")
SD_LINK_DEFAULT = "7d"
SD_NUMS = {"req_days": (FRQ_DAYS_DEFAULT, FRQ_DAYS_MAX), "req_mb": (FRQ_MB_DEFAULT, MAX_FILE_MB), "req_files": (FRQ_FILES_DEFAULT, FRQ_FILES_MAX)}


def sd_clean(v):
    """A request's value -> stored json. Strict: an unknown field, a value outside the limits or no allowed kind is a 400."""
    bad = BadInput(tr("Invalid value: {0}", "share_defaults"))
    try:
        o = json.loads(v or "{}") if isinstance(v, str) else v
    except ValueError:
        raise bad from None
    if not isinstance(o, dict) or set(o) - {"link_expires", "req_types", *SD_NUMS}:
        raise bad
    if "link_expires" in o and o["link_expires"] not in SD_LINK_EXPIRES:
        raise bad
    for k, (_std, hi) in SD_NUMS.items():
        if k in o and (not isinstance(o[k], int) or isinstance(o[k], bool) or not 1 <= o[k] <= hi):
            raise bad
    if "req_types" in o:
        t = o["req_types"]
        if not isinstance(t, list) or not t or any(not isinstance(x, str) or x not in FRQ_TYPES for x in t):
            raise bad
        o["req_types"] = [k for k in FRQ_TYPES if k in t]
    return json.dumps(o, separators=(",", ":"))


def _stored(c, org_id, uid):
    if org_id:
        r = c.execute("SELECT share_defaults FROM orgs WHERE id=?", (int(org_id),)).fetchone()
        raw = r[0] if r else ""
    else:
        raw = usettings(c, uid).get("share_defaults")
    try:
        o = json.loads(raw or "{}")
    except ValueError:
        return {}
    return o if isinstance(o, dict) else {}


def sd_for(c, org_id, uid):
    """The defaults that count for a new link / request in organisation org_id (None = the private workspace of uid)."""
    s = _stored(c, org_id, uid)
    out = {"link_expires": s["link_expires"] if s.get("link_expires") in SD_LINK_EXPIRES else SD_LINK_DEFAULT}
    for k, (std, hi) in SD_NUMS.items():
        v = s.get(k)
        out[k] = min(v, hi) if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else std
    t = s.get("req_types")
    out["req_types"] = [k for k in FRQ_TYPES if isinstance(t, list) and k in t] or list(FRQ_TYPES_DEFAULT)
    return out


@app.get("/api/share-defaults")
def sd_get():
    """?space=private | org:<id> -> the workspace's defaults, what is stored and the limits (every member sees them, as the
    dialogs use them; a stranger gets the 404 of an organisation they are not in)."""
    c = db()
    if "kind" in g.user.keys() and g.user["kind"] == "agent":
        raise Denied(403, tr("Agents cannot use this endpoint"))
    sp = request.args.get("space") or "private"
    if not WSA_KEY_RE.fullmatch(sp):
        raise BadInput(tr("Invalid value: {0}", "space"))
    oid = None if sp == "private" else int(sp[4:])
    edit = True
    if oid:
        edit = org_need_person(c, oid) == "admin" and instance_mode(c) == "workspaces"
    return jsonify(space=sp, can_edit=edit, stored=_stored(c, oid, me()), defaults=sd_for(c, oid, me()),
                   limits={"days": FRQ_DAYS_MAX, "max_mb": MAX_FILE_MB, "max_files": FRQ_FILES_MAX, "types": list(FRQ_TYPES)})
