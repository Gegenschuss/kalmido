"""2.558.0 (#4709): the generic routes of the core objects (core/objects.py, core/writes.py) -- every kind registered with
routes=True gets them without a line of its own (docs/dev/kern.md). An unknown kind (or one without routes) is 404.

Web app (the person's session; static/js/objsave.js saves through PATCH with expect_updated_at and X-Kalmido-Undo):
  GET    /api/obj/<kind>                      the objects one sees (?trash=1: the trash one manages)
  POST   /api/obj/<kind>                      {org_id?, <fields>} a new object (201)
  GET    /api/obj/<kind>/<id>                 one object
  PATCH  /api/obj/<kind>/<id>                 {<fields sent only>, expect_updated_at?} -> 409 {current} when changed meanwhile
  POST   /api/obj/<kind>/<id>/trash | /restore   into / out of the trash
  DELETE /api/obj/<kind>/<id>                 delete for good (only from the trash)
  GET    /api/obj/<kind>/<id>/history         the history (newest first)
  POST   /api/obj/<kind>/<id>/undo            {sess, op: undo | redo | all | redoall}
  GET    /api/obj/<kind>/<id>/shares          own shares, the folders' shares, shares taken back
  POST   /api/obj/<kind>/<id>/shares          {user_id | group_id | agent_id, role: view | edit, expires_at?}
  DELETE /api/obj/<kind>/<id>/shares/<sid>    take a share back (restorable)
  POST   /api/obj/<kind>/<id>/shares/<rid>/restore   put a share taken back on again
Agents (API v1, the agent channel, scope agent + the kind's own scopes):
  GET    /api/v1/agent/objects/<kind>         what the agent sees (only what is shared with it)
  GET    /api/v1/agent/objects/<kind>/<id>
  PATCH  /api/v1/agent/objects/<kind>/<id>    expect_updated_at required (400 without, 409 when changed meanwhile)
  POST   /api/v1/agent/objects/<kind>/<id>/proposals   2.623.0 (#4718): the change as a proposal (agents/objprop.py)"""
from flask import g, jsonify, request

from ..accounts.session import me
from ..api.common import v1_args, v1_json, v1_view
from .access import Denied
from .config import app
from .conflict import Conflict
from .db import body, db
from .errors import BadInput
from .i18n import tr
from .objects import obj_need, obj_public, obj_reg, obj_rows, obj_share, obj_share_restore, obj_shares, obj_unshare
from .writes import obj_create, obj_history, obj_purge, obj_restore, obj_trash, obj_undo, obj_write
from ..files.web import _expiry
from ..api.scopes import need_scope


def _reg(kind):
    reg = obj_reg(kind)
    if not reg["routes"]:
        raise Denied(404)
    return reg


def _one(c, uid, kind, rid, trash=False):
    row, role = obj_need(c, uid, kind, rid, "view", trash=trash)
    return obj_public(c, uid, kind, row, role)


@app.get("/api/obj/<kind>")
def obj_list_route(kind):
    _reg(kind)
    c, uid = db(), me()
    trash = request.args.get("trash") == "1"
    return jsonify(items=[obj_public(c, uid, kind, r, role) for r, role in obj_rows(c, uid, kind, trash=trash)])


@app.post("/api/obj/<kind>")
def obj_create_route(kind):
    _reg(kind)
    c, uid = db(), me()
    b = body()
    b = dict(b) if isinstance(b, dict) else {}
    org = b.pop("org_id", None)
    row = obj_create(c, uid, kind, b, org_id=org)
    c.commit()
    return jsonify(obj_public(c, uid, kind, row, "manage")), 201


@app.get("/api/obj/<kind>/<int:rid>")
def obj_get_route(kind, rid):
    _reg(kind)
    c = db()
    return jsonify(_one(c, me(), kind, rid))


@app.patch("/api/obj/<kind>/<int:rid>")
def obj_patch_route(kind, rid):
    _reg(kind)
    c, uid = db(), me()
    row, changed = obj_write(c, uid, kind, rid, body())
    c.commit()
    return jsonify({**_one(c, uid, kind, rid), "changed": sorted(changed)})


@app.post("/api/obj/<kind>/<int:rid>/trash")
def obj_trash_route(kind, rid):
    _reg(kind)
    c, uid = db(), me()
    obj_trash(c, uid, kind, rid)
    c.commit()
    return jsonify(_one(c, uid, kind, rid, trash=True))


@app.post("/api/obj/<kind>/<int:rid>/restore")
def obj_restore_route(kind, rid):
    _reg(kind)
    c, uid = db(), me()
    obj_restore(c, uid, kind, rid)
    c.commit()
    return jsonify(_one(c, uid, kind, rid))


@app.delete("/api/obj/<kind>/<int:rid>")
def obj_purge_route(kind, rid):
    _reg(kind)
    c, uid = db(), me()
    obj_purge(c, uid, kind, rid)
    c.commit()
    return jsonify(ok=True)


@app.get("/api/obj/<kind>/<int:rid>/history")
def obj_history_route(kind, rid):
    _reg(kind)
    return jsonify(items=obj_history(db(), me(), kind, rid))


@app.post("/api/obj/<kind>/<int:rid>/undo")
def obj_undo_route(kind, rid):
    _reg(kind)
    c, uid = db(), me()
    b = body()
    b = b if isinstance(b, dict) else {}
    steps = obj_undo(c, uid, kind, rid, b.get("sess"), b.get("op") or "undo")
    c.commit()
    return jsonify({**_one(c, uid, kind, rid), "undo_steps": steps})


@app.get("/api/obj/<kind>/<int:rid>/shares")
def obj_shares_route(kind, rid):
    _reg(kind)
    return jsonify(obj_shares(db(), me(), kind, rid))


@app.post("/api/obj/<kind>/<int:rid>/shares")
def obj_share_route(kind, rid):
    _reg(kind)
    c, uid = db(), me()
    b = body()
    b = b if isinstance(b, dict) else {}
    key = next((k for k in ("user_id", "group_id", "agent_id") if b.get(k) is not None), None)
    if not key:
        raise BadInput(tr("Expected {0}", "user_id | group_id | agent_id"))
    sid = obj_share(c, uid, kind, rid, key, b.get(key), b.get("role") or "view", _expiry(b.get("expires_at"), b.get("tz")))
    c.commit()
    return jsonify(id=sid, **obj_shares(c, uid, kind, rid)), 201


@app.delete("/api/obj/<kind>/<int:rid>/shares/<int:sid>")
def obj_unshare_route(kind, rid, sid):
    _reg(kind)
    c, uid = db(), me()
    rev = obj_unshare(c, uid, kind, rid, sid)
    c.commit()
    return jsonify(revoked_id=rev, **obj_shares(c, uid, kind, rid))


@app.post("/api/obj/<kind>/<int:rid>/shares/<int:revoked_id>/restore")
def obj_share_restore_route(kind, rid, revoked_id):
    _reg(kind)
    c, uid = db(), me()
    sid = obj_share_restore(c, uid, kind, rid, revoked_id)
    c.commit()
    return jsonify(id=sid, **obj_shares(c, uid, kind, rid))


# ---------------------------------------------------------------- agents (API v1)
def _agent_kind(kind, write=False):
    """The kind for the agent channel: only an agent's token, with the kind's read (write) scope."""
    reg = _reg(kind)
    if (g.user["kind"] or "user") != "agent":  # agents/core.need_agent (the layer agents is above this module's)
        raise Denied(403, tr("Only agent accounts can use this endpoint"))
    aid = g.user["id"]
    need_scope(reg["scopes"][1 if write else 0])
    return aid


@app.get("/api/v1/agent/objects/<kind>")
@v1_view
def v1_obj_list(kind):
    v1_args(())
    aid = _agent_kind(kind)
    c = db()
    return jsonify(data=[obj_public(c, aid, kind, r, role) for r, role in obj_rows(c, aid, kind)], next_cursor=None)


@app.get("/api/v1/agent/objects/<kind>/<int:rid>")
@v1_view
def v1_obj_get(kind, rid):
    v1_args(())
    aid = _agent_kind(kind)
    return jsonify(_one(db(), aid, kind, rid))


@app.patch("/api/v1/agent/objects/<kind>/<int:rid>")
@v1_view
def v1_obj_patch(kind, rid):
    v1_args(())
    aid = _agent_kind(kind, write=True)
    c = db()
    try:
        row, changed = obj_write(c, aid, kind, rid, v1_json())
    except Conflict as e:
        e.v1_extra = {"current": e.cur}  # the API's error answer carries the current state too (v1_view)
        raise
    c.commit()
    return jsonify({**_one(c, aid, kind, rid), "changed": sorted(changed)})


def objects_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    """The OpenAPI part of the agent routes (api/openapi.py)."""
    T = "Core objects"
    schemas["CoreObject"] = {"type": "object", "description": "2.558.0: an object of an area built on the shared core; its fields depend on the kind",
                             "properties": {"id": {"type": "integer"}, "kind": {"type": "string"}, "org_id": nul("integer"),
                                            "owner_id": {"type": "integer"}, "rev": {"type": "integer"}, "title": {"type": "string"},
                                            "role": {"type": "string", "enum": ["view", "edit", "manage"]},
                                            "updated_at": {"type": "string", "description": "Send it back as expect_updated_at when changing"}},
                             "additionalProperties": True}
    schemas["CoreObjectPage"] = page("CoreObject")
    kp = {"name": "kind", "in": "path", "required": True, "schema": {"type": "string"}, "description": "The object kind (an area's name for it)"}
    paths["/agent/objects/{kind}"] = {"get": op("2.558.0: the objects of a kind shared with this agent", T, ok(ref("CoreObjectPage")) | errs("403", "404"),
                                                [kp], scope="agent")}
    paths["/agent/objects/{kind}/{id}"] = {
        "get": op("2.558.0: one object shared with this agent", T, ok(ref("CoreObject")) | errs("403", "404"), [kp, pid(desc="Object id")], scope="agent"),
        "patch": op("2.558.0: change the fields sent; expect_updated_at is required (400 without, 409 with the current state when "
                    "someone changed it since)", T, ok(ref("CoreObject")) | errs("400", "403", "404", "409"), [kp, pid(desc="Object id")],
                    body={"type": "object", "required": ["expect_updated_at"], "additionalProperties": True,
                          "properties": {"expect_updated_at": {"type": "string", "description": "updated_at of the object as read"}}},
                    scope="agent")}
    # 2.623.0 (#4718): the change as a proposal a person accepts (route in agents/objprop.py)
    paths["/agent/objects/{kind}/{id}/proposals"] = {"post": op(
        "2.623.0: propose a change of the fields in values (a person accepts or declines it)", T,
        ok({"type": "object"}, "Created", "201") | errs("400", "403", "404", "409", "413", "429"), [kp, pid(desc="Object id")],
        body={"type": "object", "required": ["values", "expect_updated_at"], "additionalProperties": False, "properties": {
            "values": {"type": "object", "description": "The fields to change and their new values (checked like a change)"},
            "expect_updated_at": {"type": "string", "description": "updated_at of the object as read (409 when it changed since)"},
            "summary": {"type": "string", "description": "Markdown: why"},
            "user_id": {"type": "integer", "description": "The person who decides (needs write rights on the object; default: its owner)"}}},
        scope="agent",
        desc="Agents only; the object must be visible to you (a view share is enough), the token needs the kind's read scope "
             "and one scope beyond reading (a read-only token sends no proposals). "
             "Nothing changes until the person accepts: then the values are written AS THEM with exactly your version (their "
             "rights; refused when anybody changed the object since). The answer comes as the event job (action approve / "
             "reject); at most 100 per day.")}
