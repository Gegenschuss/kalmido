"""2.1076.0 (#5271, stage Q3 of the cross-cutting core): the generic routes of the links' core (core/objlinks.py) -- one
address for the links of every kind of the core's register (also the light kinds task, event, hub_mail, client).

Web app (the person's session):
  GET    /api/obj/<kind>/<id>/links       {links: [{id, rel, note, dir: out | in, other: {kind, id, state: ok | gone, title?,
                                          open_url?}, created_at, created_by, agent}]} -- what the reader may see ('view' on
                                          the object; a target the reader may not see is left out, a deleted one is 'gone')
  POST   /api/obj/<kind>/<id>/links       {kind, id, rel?, note?} -> 201 {id, links}: 'write' on this object, 'view' on the
                                          target, the same workspace, no end-to-end locked project (409)
  DELETE /api/obj/links/<lid>             into the trash ('write' on its source) -> {ok, links}; taken back through the
                                          person's undo list (the answer's X-Kalmido-Undo-Gid, core/undoweb.py)
Agents (API v1, the agent channel; the kind's read scope to list, its write scope to link / unlink; review 2.1076: the other
side's read scope too -- a target of a kind the token may not read cannot be linked (403) and is left out of the list, and
removing needs the write scope of the link's source):
  GET    /api/v1/agent/objects/<kind>/<id>/links
  POST   /api/v1/agent/objects/<kind>/<id>/links
  DELETE /api/v1/agent/objects/<kind>/<id>/links/<lid>
An area's own relations (a filed e-mail's tasks, a letter's documents, a contact's tasks, a device's equipment) are listed here
too, but written and removed only through their area's routes (409 here)."""
from flask import Response, g, jsonify

from ..accounts.session import me
from ..api.common import v1_args, v1_json, v1_view
from ..api.scopes import need_scope
from .access import Denied
from .config import app
from .db import body, bump, db
from .i18n import tr
from .objects import OBJ, obj_need, obj_reg
from .objlinks import obj_link, obj_links_of, obj_unlink, olnk_row


def _b():
    b = body()
    return b if isinstance(b, dict) else {}


def _links(c, uid, kind, rid):
    return obj_links_of(c, uid, kind, rid)


@app.get("/api/obj/<kind>/<int:rid>/links")
def olw_list(kind, rid):
    c, uid = db(), me()
    obj_need(c, uid, kind, rid, "view")
    return jsonify(links=_links(c, uid, kind, rid))


@app.post("/api/obj/<kind>/<int:rid>/links")
def olw_add(kind, rid):
    c, uid = db(), me()
    b = _b()
    lid = obj_link(c, uid, kind, rid, b.get("kind"), b.get("id"), b.get("rel"), b.get("note"))
    bump(c)
    c.commit()
    return jsonify(id=lid, links=_links(c, uid, kind, rid)), 201


@app.delete("/api/obj/links/<int:lid>")
def olw_delete(lid):
    c, uid = db(), me()
    r = obj_unlink(c, uid, lid)
    bump(c)
    c.commit()
    return jsonify(ok=True, links=_links(c, uid, r["src_kind"], r["src_id"]))


# ---------------------------------------------------------------- agents (API v1)
def _agent(kind, write=False):
    """Only an agent's token, with the kind's read (write) scope (as core/objweb.py, also for the light kinds)."""
    reg = obj_reg(kind)
    if (g.user["kind"] or "user") != "agent":
        raise Denied(403, tr("Only agent accounts can use this endpoint"))
    need_scope(reg["scopes"][1 if write else 0])
    return g.user["id"]


# review 2.1076 (#5271): the read scope of a kind outside the core's register (core/objlinks.py olnk_kind)
OLNK_READ_SCOPE = {"contact": "contacts", "office_letter": "office"}


def _read_scope(kind):
    reg = OBJ.get(kind) if isinstance(kind, str) else None
    return reg["scopes"][0] if reg else OLNK_READ_SCOPE.get(kind, "read")


def _token_may(s):
    return g.get("auth_via") != "token" or s in (g.get("scopes") or set())


def _agent_links(c, aid, kind, rid):
    """The links as the agent's token may see them: a side of a kind whose read scope the token lacks is left out."""
    return [x for x in _links(c, aid, kind, rid) if "kind" not in x["other"] or _token_may(_read_scope(x["other"]["kind"]))]


@app.get("/api/v1/agent/objects/<kind>/<int:rid>/links")
@v1_view
def v1_olnk_list(kind, rid):
    v1_args(())
    aid = _agent(kind)
    c = db()
    obj_need(c, aid, kind, rid, "view")
    return jsonify(data=_agent_links(c, aid, kind, rid), next_cursor=None)


@app.post("/api/v1/agent/objects/<kind>/<int:rid>/links")
@v1_view
def v1_olnk_add(kind, rid):
    v1_args(())
    aid = _agent(kind, write=True)
    b = v1_json()
    if isinstance(b.get("kind"), str) and b["kind"] in OBJ:
        need_scope(_read_scope(b["kind"]))  # review 2.1076: the target's read scope too (an event: calendar)
    c = db()
    lid = obj_link(c, aid, kind, rid, b.get("kind"), b.get("id"), b.get("rel"), b.get("note"), agent_id=aid)
    bump(c)
    c.commit()
    return jsonify(id=lid, links=_agent_links(c, aid, kind, rid)), 201


@app.delete("/api/v1/agent/objects/<kind>/<int:rid>/links/<int:lid>")
@v1_view
def v1_olnk_delete(kind, rid, lid):
    v1_args(())
    aid = _agent(kind, write=True)
    c = db()
    r = olnk_row(c, lid)
    if r is None:
        raise Denied(404)
    if r["src_kind"] in OBJ and (r["src_kind"], r["src_id"]) != (kind, rid):  # review 2.1076: the write scope of its source
        need_scope(OBJ[r["src_kind"]]["scopes"][1])
    obj_unlink(c, aid, lid, kind=kind, rid=rid)
    bump(c)
    c.commit()
    return Response(status=204)


def links_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    """The OpenAPI part of the agent routes (api/openapi.py, next to core/objweb.py objects_spec)."""
    T = "Core objects"
    schemas["CoreLink"] = {"type": "object", "description": "2.1076.0: a link of the shared core between two objects",
                           "properties": {"id": {"type": "integer"}, "rel": {"type": "string"}, "note": {"type": "string"},
                                          "dir": {"type": "string", "enum": ["out", "in"]},
                                          "other": {"type": "object", "description": "The other side: kind, id, state ok | gone, title, open_url"},
                                          "created_at": {"type": "string"}, "agent": {"type": "boolean"}}}
    schemas["CoreLinkPage"] = page("CoreLink")
    kp = {"name": "kind", "in": "path", "required": True, "schema": {"type": "string"}, "description": "The object kind (task, event, hub_mail, client, an area's kind)"}
    lp = {"name": "lid", "in": "path", "required": True, "schema": {"type": "integer"}, "description": "Link id"}
    paths["/agent/objects/{kind}/{id}/links"] = {
        "get": op("2.1076.0: the links of an object you see (a target you may not see is left out, a deleted one is state gone)", T,
                  ok(ref("CoreLinkPage")) | errs("403", "404"), [kp, pid(desc="Object id")], scope="agent"),
        "post": op("2.1076.0: link this object (write on it) with another one you see in the same workspace", T,
                   ok({"type": "object"}, "Created", "201") | errs("400", "403", "404", "409"), [kp, pid(desc="Object id")],
                   body={"type": "object", "required": ["kind", "id"], "additionalProperties": False, "properties": {
                       "kind": {"type": "string", "description": "The target's kind"}, "id": {"type": "integer", "description": "The target's id"},
                       "rel": {"type": "string", "description": "What the link means (default related; an area's own relation is refused with 409)"},
                       "note": {"type": "string", "maxLength": 500}}}, scope="agent")}
    paths["/agent/objects/{kind}/{id}/links/{lid}"] = {"delete": op(
        "2.1076.0: remove a link of this object (write on its source; an area's own relation: 409)", T,
        ok({"type": "object"}, "No content", "204") | errs("403", "404", "409"), [kp, pid(desc="Object id"), lp], scope="agent")}
