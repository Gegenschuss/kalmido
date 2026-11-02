"""2.483.0 (#1902): the filed e-mails (hub_mails, hub/hubmail.py #1198) in the REST API v1 + MCP -- read only (scope read).

A token reads the mails filed with a client or a project only, never the mails "Not assigned" (not even its own person's:
those stay in the app's hub inbox), never a deleted one. The app routes /api/hubmail/* keep their 403 for agents (_gate);
this module has its own checks:
- a project's mail: the token's user sees the project (list_role: the token's list restriction, an agent's data lock and
  its shares) and the project lies in the mail's workspace (hbm_can);
- a client's mail: a PERSON's token -- the person sees the client (team/clients.py client_rows) in the mail's workspace;
  an AGENT (client_rows gives agents no clients) and a person's token limited to some projects -- the client is in the
  mail's workspace, not in the trash, and the token's user sees at least one project of that client in the same
  workspace (a private client: a project of the client's own person), like the agent API reads clients only through the
  projects it shares.
An agent with the data lock "Private e-mails" (the default) reads no mail of a private space (review 2.483 F1).
Anything else answers 404 (also another organisation's mail). Kid accounts get 403 (as in the app).
The answer has no addresses for the client / project, no write flags and no file ids to download (the attachments' names,
sizes and types only). No event "new mail filed" in this step (decision 30.10.2026)."""
from flask import g, jsonify

from ..core.config import app
from ..core.access import Denied, list_role, token_lists
from ..core.dlock import dl_of
from ..core.db import db
from ..core.i18n import tr
from ..core.errors import BadInput
from ..tasks.validation import as_int
from ..api.common import cursor_dec, cursor_enc, v1_args, v1_view
from .hubmail import HBM_PAGE, _search, _visible_client, hbm_can, hbm_public

HMV_ORDER = "ORDER BY COALESCE(sent_at, created_at) DESC, id DESC LIMIT 2000"
HMV_LIMIT, HMV_LIMIT_MAX = 100, 500  # like api/v1.py API_PAGE_DEFAULT / API_PAGE_MAX
HMV_DROP = ("mine", "can_write", "folder_id", "eml_id", "note")


def _hmv_agent():
    """The token's user is an agent (like agents.core.is_agent; no import upwards from this layer)."""
    return (g.user["kind"] or "user") == "agent"


def _hmv_gate():
    u = g.user
    if u["kid"]:
        raise Denied(403, tr("Only people can file e-mails"))
    return u["id"]


def hmv_client(c, uid, cid):
    """The client row when the token's user may read the mails filed with client cid, else None (see the module text)."""
    if not _hmv_agent() and token_lists() is None:
        return _visible_client(c, uid, cid)
    k = c.execute("SELECT id, org_id, created_by FROM clients WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
    if not k or (not _hmv_agent() and not _visible_client(c, uid, cid)):
        return None
    if k["org_id"]:
        lids = c.execute("SELECT id FROM lists WHERE client_id=? AND org_id=? AND deleted_at IS NULL ORDER BY id", (cid, k["org_id"])).fetchall()
    else:
        lids = c.execute("SELECT id FROM lists WHERE client_id=? AND org_id IS NULL AND owner_id=? AND deleted_at IS NULL ORDER BY id",
                         (cid, k["created_by"])).fetchall()
    return k if any(list_role(c, r[0]) for r in lids) else None


def hmv_locked(c, uid, org_id):
    """Review 2.483 F1: an agent with the data lock "Private e-mails" (core/dlock.py, on by default) reads no mail filed in a
    private space (no organisation), like the mail tasks there (tvis)."""
    d = dl_of(c, uid)
    return bool(d and d["_mail"] and not org_id)


def hmv_can(c, uid, m):
    """May the token's user read hub mail row m through the API? Only a filed one (client or project), never deleted."""
    if m["deleted_at"] or not (m["client_id"] or m["list_id"]) or hmv_locked(c, uid, m["org_id"]):
        return False
    if m["list_id"]:
        return hbm_can(c, uid, m)
    k = hmv_client(c, uid, m["client_id"])
    return bool(k) and (k["org_id"] or None) == (m["org_id"] or None)


def hmv_public(c, m, full=False):
    d = hbm_public(c, m, full=full)
    for k in HMV_DROP:
        d.pop(k, None)
    for a in d.get("attachments") or []:
        a.pop("id", None)
    return d


def _id_arg(a, k):
    v = a.get(k)
    if v in (None, ""):
        return None
    if not str(v).isdigit() or int(v) <= 0:
        raise BadInput(tr("Invalid value: {0}", k))
    return int(v)


@app.get("/api/v1/mails")
@v1_view
def v1_hub_mails():
    """?client_id= | ?list_id= (exactly one), q=, limit=, cursor= -- the mails filed there, newest first."""
    a = v1_args(("client_id", "list_id", "q", "limit", "cursor"))
    c = db()
    uid = _hmv_gate()
    cid, lid = _id_arg(a, "client_id"), _id_arg(a, "list_id")
    if bool(cid) == bool(lid):
        raise BadInput(tr("Invalid value: {0}", "client_id | list_id"))
    if cid:
        k = hmv_client(c, uid, cid)
        if not k or hmv_locked(c, uid, k["org_id"]):
            raise Denied(404)
        rows = c.execute("SELECT * FROM hub_mails WHERE client_id=? AND deleted_at IS NULL AND org_id IS NOT DISTINCT FROM ? " + HMV_ORDER,
                         (cid, k["org_id"])).fetchall()
    else:
        if not list_role(c, lid):
            raise Denied(404)
        lo = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()
        if hmv_locked(c, uid, lo["org_id"] if lo else None):
            raise Denied(404)
        rows = c.execute("SELECT * FROM hub_mails WHERE list_id=? AND deleted_at IS NULL AND org_id IS NOT DISTINCT FROM ? " + HMV_ORDER,
                         (lid, lo["org_id"] if lo else None)).fetchall()
    rows = [m for m in rows if hmv_can(c, uid, m)]
    q = (a.get("q") or "").strip()[:200]
    if q:
        rows = _search(c, rows, q)
    off, n = cursor_dec("o", a.get("cursor")), min(as_int(a.get("limit", HMV_LIMIT), "limit", 1, HMV_LIMIT_MAX), HBM_PAGE)
    out = [hmv_public(c, m) for m in rows[off:off + n]]
    return jsonify(data=out, next_cursor=cursor_enc("o", off + n) if len(rows) > off + n else None)


@app.get("/api/v1/mails/<int:mid>")
@v1_view
def v1_hub_mail(mid):
    """One filed mail with its plain text (body, body_short) and the names of its attachments."""
    v1_args(())
    c = db()
    uid = _hmv_gate()
    m = c.execute("SELECT * FROM hub_mails WHERE id=?", (mid,)).fetchone()
    if not m or not hmv_can(c, uid, m):
        raise Denied(404)
    return jsonify(hmv_public(c, m, full=True))


def hmv_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """The OpenAPI part (api/openapi.py)."""
    T = "Mail"
    schemas["FiledMail"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "org_id": {"type": ["integer", "null"]}, "client_id": {"type": ["integer", "null"]},
        "client_name": {"type": "string"}, "list_id": {"type": ["integer", "null"]}, "list_name": {"type": "string"},
        "from_addr": {"type": "string"}, "from_name": {"type": "string"}, "subject": {"type": "string"},
        "sent_at": {"type": ["string", "null"]}, "created_at": {"type": "string"}, "files": {"type": "integer", "description": "Number of attachments"},
        "dir": {"type": "string", "enum": ["in", "out"], "description": "out = sent from the filing"}, "state": {"type": "string"},
        "deleted": {"type": "boolean"},
        "body": {"type": "string", "description": "The plain text (one mail only)"},
        "body_short": {"type": "string", "description": "The text without quoted earlier mails and signature (one mail only)"},
        "to": {"type": "string", "description": "The recipients (one mail only)"},
        "to_list": {"type": "array", "items": {"type": "string"}, "description": "A sent mail (dir out): the recipient addresses"},
        "attachments": {"type": "array", "description": "One mail only: name, size, mime, scan (no download through the API)",
                        "items": {"type": "object"}}}}
    rule = ("Only mails filed with a client or a project you see, in that client's / project's workspace; never the mails "
            "\"Not assigned\" of anybody, never deleted ones; an agent with the data lock \"Private e-mails\" (the default) none of a private space. An agent sees a client's mails when it sees a project of that "
            "client. Read only: filing, assigning, deleting and sending stay in the app.")
    paths["/mails"] = {"get": op("E-mails filed with a client or a project (2.483.0)", T,
                                 ok({"type": "object", "properties": {"data": {"type": "array", "items": ref("FiledMail")},
                                                                      "next_cursor": {"type": ["string", "null"]}}}) | errs("400", "403", "404"),
                                 [q("client_id", "The client (exactly one of client_id / list_id)", {"type": "integer"}),
                                  q("list_id", "The project", {"type": "integer"}), q("q", "Words in subject, sender or text"),
                                  q("limit", "Mails per page, at most 200", {"type": "integer"}), q("cursor", "next_cursor of the page before")],
                                 desc=rule)}
    paths["/mails/{id}"] = {"get": op("One filed e-mail with its text (2.483.0)", T, ok(ref("FiledMail")) | errs("403", "404"),
                                      [pid("id", "Mail id")], desc=rule)}
