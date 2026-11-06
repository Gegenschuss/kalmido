"""2.609.0 (#3372): own ticket types per workspace, next to the built-in bug / feature / task.

An organisation (org_id) or a person without one (org_id NULL, owner_id = that person) defines up to TT_MAX own types: name,
symbol, colour, note template; switched off = kept (tasks keep showing it) but no longer offered. Epic and story come as
suggestions to switch on (TT_SUGGEST), never on by themselves. Who manages them: the organisation's admins, a person their
own; agents only read (web routes, API v1, MCP list_ticket_types). A project offers all enabled types of its workspace or
the ones it picked (lists.ttypes, json list of keys). The server takes a built-in type in any project (forms, imports and
older clients send them); an own type only where the project offers it, checked when a task gets it (tt_check).
Deleting a type that tasks carry asks first (409 with the count), then those tasks lose their type."""
import json
import re

from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.i18n import N_, tr, trn
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, need_list, vis_sql
from ..core.errors import BadInput, reject_unknown
from ..accounts.orgroles import org_roles_of, user_orgs_full
from ..accounts.orgs import is_org_admin
from ..api.common import v1_args, v1_json, v1_view
from .validation import TICKET_TPL_MAX, TICKET_TYPES, TT_KEY_RE

TT_MAX = 20          # own types per workspace
TT_NAME_MAX = 40
TT_ICONS = ("bug", "bulb", "tsq", "flag", "book", "star", "heart", "target", "rocket", "zap", "shield", "bookmark", "list", "mindmap")
TT_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# the shipped suggestions: key -> (name, icon, colour, note template); switched on through POST {key} (nothing else needed)
TT_SUGGEST = {
    "epic": (N_("Epic"), "flag", "#7c3aed", N_("**Goal**\n\n**Scope**\n- \n\n**Done when**\n- [ ] \n")),
    "story": (N_("Story"), "book", "#0e7490", N_("**As a** \n**I want** \n**so that** \n\n**Acceptance criteria**\n- [ ] \n")),
}


def tt_person_only():
    u = getattr(g, "user", None) if has_request_context() else None
    if u is not None and (u["kind"] or "user") == "agent":  # agents.core is_agent (a higher layer)
        raise Denied(403, tr("Agents can read ticket types, not change them"))


def tt_list_scope(c, lid):
    """(org id, owner id) of the workspace list lid belongs to (owner None for an organisation's list)."""
    r = c.execute("SELECT org_id, owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        return None, None
    return (r["org_id"], None) if r["org_id"] else (None, r["owner_id"])


def tt_rows(c, oid, owner, enabled=False):
    q = "org_id=?" if oid else "org_id IS NULL AND owner_id=?"
    return c.execute(f"SELECT * FROM ticket_types WHERE {q}{' AND enabled=1' if enabled else ''} ORDER BY sort, id",
                     (oid or owner,)).fetchall()


def tt_offered(c, lid):
    """The type keys list lid offers, in order: the built-in ones, then the enabled own ones of its workspace; a project that
    picked some (lists.ttypes) offers only those."""
    oid, owner = tt_list_scope(c, lid)
    keys = [*TICKET_TYPES, *(r["key"] for r in tt_rows(c, oid, owner, True))]
    r = c.execute("SELECT ttypes FROM lists WHERE id=?", (lid,)).fetchone()
    try:
        pick = json.loads(r["ttypes"]) if r and r["ttypes"] else None
    except ValueError:
        pick = None
    return [k for k in keys if k in pick] if isinstance(pick, list) and pick else keys


def tt_known(c, lid, key):
    """Is key a built-in type or an own type of list lid's workspace (enabled or not)? (A project's default type.)"""
    if key in TICKET_TYPES:
        return True
    oid, owner = tt_list_scope(c, lid)
    return any(r["key"] == key for r in tt_rows(c, oid, owner))


def tt_check(c, lid, key):
    """None when a task of list lid may get type key, else the message. Built-in types always (see the module text)."""
    if not key or key in TICKET_TYPES:
        return None
    if key not in tt_offered(c, lid):
        return tr("This project does not offer the ticket type {0}", key)
    return None


def tt_space(c, uid, v):
    """org id (None = private) of a space value "private" | "org:<id>" | <id>; 404 outside the person's organisations."""
    if v in (None, "", "private", 0, "0"):
        return None
    s = str(v)
    s = s[4:] if s.startswith("org:") else s
    try:
        oid = int(s)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "space")) from None
    if oid not in user_orgs_full(c, uid):  # 2.609.0 (#3372, review F6): a guest / accounting person has no workspace view
        raise Denied(404)
    return oid


def tt_may_edit(c, uid, oid, owner):
    if oid:
        return is_org_admin(c, uid, oid)
    return owner == uid


def tt_out(c, uid, r, n=None):
    o = {"id": r["id"], "key": r["key"], "name": r["name"], "icon": r["icon"], "color": r["color"], "template": r["tpl"],
         "sort": r["sort"], "enabled": bool(r["enabled"]), "org_id": r["org_id"],
         "space": f"org:{r['org_id']}" if r["org_id"] else "private",
         "can_edit": tt_may_edit(c, uid, r["org_id"], r["owner_id"])}
    if not r["org_id"]:
        o["owner_id"] = r["owner_id"]
    if n is not None:
        o["tasks"] = n
    return o


def tt_get(c, uid, tid, write=False):
    r = c.execute("SELECT * FROM ticket_types WHERE id=?", (tid,)).fetchone()
    if not r:
        raise Denied(404)
    if r["org_id"]:
        if r["org_id"] not in user_orgs_full(c, uid):  # review F6: as tt_space
            raise Denied(404)
    elif r["owner_id"] != uid and (write or r["owner_id"] not in tt_owners_seen(c, uid)):
        raise Denied(404)  # another person's own types: never changed by someone else
    if write:
        tt_person_only()
        if not tt_may_edit(c, uid, r["org_id"], r["owner_id"]):
            raise Denied(403, tr("Only an admin of this organisation can change its ticket types"))
    return r


def tt_owners_seen(c, uid):
    """The owners of the private lists uid sees (their own types show in those lists)."""
    return {r[0] for r in c.execute(f"SELECT DISTINCT owner_id FROM lists WHERE org_id IS NULL AND id IN ({vis_sql()})", (uid, uid))}


def tt_task_count(c, oid, owner, key):
    q = "l.org_id=?" if oid else "l.org_id IS NULL AND l.owner_id=?"
    return c.execute(f"SELECT COUNT(*) FROM tasks t JOIN lists l ON l.id=t.list_id WHERE {q} AND t.ttype=? AND t.deleted_at IS NULL",
                     (oid or owner, key)).fetchone()[0]


def tt_suggestions(have):
    return [{"key": k, "name": tr(n), "icon": i, "color": col} for k, (n, i, col, _t) in TT_SUGGEST.items() if k not in have]


def tt_index_data(c, uid, space=None):
    """All types uid can meet (own, their organisations', the owners' of private lists they see) or, with space, the ones of
    that workspace (disabled too, with their task counts, the suggestions not taken yet and whether uid may change them)."""
    if space is not None:
        oid = tt_space(c, uid, space)
        owner = None if oid else uid
        rows = tt_rows(c, oid, owner)
        edit = tt_may_edit(c, uid, oid, owner)  # review F6: the task counts (over every project of the workspace) for its managers only
        return {"space": f"org:{oid}" if oid else "private", "can_edit": edit, "max": TT_MAX,
                "types": [tt_out(c, uid, r, tt_task_count(c, oid, owner, r["key"]) if edit else None) for r in rows],
                "suggestions": tt_suggestions({r["key"] for r in rows}), "builtin": list(TICKET_TYPES)}
    orgs = sorted(user_orgs_full(c, uid))
    owners = sorted(tt_owners_seen(c, uid) | {uid})
    q = f"(org_id IS NULL AND owner_id IN ({','.join('?' * len(owners))}))"
    if orgs:
        q += f" OR org_id IN ({','.join('?' * len(orgs))})"
    rows = c.execute(f"SELECT * FROM ticket_types WHERE {q} ORDER BY sort, id", [*owners, *orgs]).fetchall()
    return {"types": [tt_out(c, uid, r) for r in rows] + tt_limited(c, uid, set(orgs)), "builtin": list(TICKET_TYPES)}


def tt_limited(c, uid, full):
    """2.609.0 (#3372, review F6): a guest / accounting person of an organisation meets only the types its projects shared with
    them offer -- key, name, symbol and colour (no note template, no switched off ones, no counts)."""
    lim = [o for o in org_roles_of(c, uid) if o not in full]
    if not lim:
        return []
    out, seen = [], set()
    for lr in c.execute(f"SELECT id, org_id FROM lists WHERE org_id IN ({','.join('?' * len(lim))}) AND id IN ({vis_sql()}) ORDER BY id",
                        [*lim, uid, uid]).fetchall():
        keys = set(tt_offered(c, lr["id"]))
        for r in tt_rows(c, lr["org_id"], None, True):
            if r["key"] in keys and r["id"] not in seen:
                seen.add(r["id"])
                out.append({"key": r["key"], "name": r["name"], "icon": r["icon"], "color": r["color"], "enabled": True,
                            "org_id": r["org_id"], "space": f"org:{r['org_id']}"})
    return out


def tt_clean(b, create):
    """Checked fields of a type from a request (name, icon, color, template, sort, enabled)."""
    out = {}
    if "name" in b or create:
        n = str(b.get("name") or "").strip()[:TT_NAME_MAX]
        if not n:
            raise BadInput(tr("Name missing"))
        out["name"] = n
    if "icon" in b:
        if b["icon"] not in ("", None, *TT_ICONS):
            raise BadInput(tr("Invalid value: {0}", "icon"))
        out["icon"] = b["icon"] or ""
    if "color" in b:
        if b["color"] not in ("", None) and not (isinstance(b["color"], str) and TT_COLOR_RE.match(b["color"])):
            raise BadInput(tr("Invalid value: {0}", "color"))
        out["color"] = (b["color"] or "").lower()
    if "template" in b:
        if b["template"] is not None and not isinstance(b["template"], str):
            raise BadInput(tr("Invalid value: {0}", "template"))
        out["tpl"] = (b["template"] or "").replace("\r\n", "\n")[:TICKET_TPL_MAX]
    if "sort" in b:
        if isinstance(b["sort"], bool) or not isinstance(b["sort"], int):
            raise BadInput(tr("Invalid value: {0}", "sort"))
        out["sort"] = b["sort"]
    if "enabled" in b:
        if not isinstance(b["enabled"], bool):
            raise BadInput(tr("Invalid value: {0}", "enabled"))
        out["enabled"] = 1 if b["enabled"] else 0
    return out


def tt_key_from(name):
    k = re.sub(r"[^a-z0-9]+", "_", name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")).strip("_")
    k = k[:24].strip("_")
    return k if k and k[0].isalpha() else ("t_" + k)[:24].strip("_")


def tt_create(c, uid, b):
    """{space?, key?, name, icon?, color?, template?, enabled?}; a suggestion's key alone switches it on with its values."""
    tt_person_only()
    oid = tt_space(c, uid, b.get("space"))
    owner = None if oid else uid
    if not tt_may_edit(c, uid, oid, owner):
        raise Denied(403, tr("Only an admin of this organisation can change its ticket types"))
    write_lock(c, f"ticket-types-{oid or 'u' + str(owner)}")  # 2.609.0 (#3372): the key / count check and the insert together
    key = b.get("key")
    sug = TT_SUGGEST.get(key) if isinstance(key, str) else None
    if sug and not b.get("name"):
        b = {"name": tr(sug[0]), "icon": sug[1], "color": sug[2], "template": tr(sug[3]), **b}
    f = tt_clean(b, True)
    if key in (None, ""):
        key = tt_key_from(f["name"])
    if not isinstance(key, str) or not TT_KEY_RE.match(key) or key in TICKET_TYPES or key == "none":
        raise BadInput(tr("Invalid value: {0}", "key"))
    rows = tt_rows(c, oid, owner)
    if any(r["key"] == key for r in rows):
        raise BadInput(tr("A ticket type with this key exists already: {0}", key))
    if len(rows) >= TT_MAX:
        raise BadInput(tr("At most {0} own ticket types", TT_MAX))
    f.setdefault("sort", max([r["sort"] for r in rows], default=0) + 1)
    cols = {"org_id": oid, "owner_id": owner, "key": key, "created_at": iso(now_utc()), **f}
    tid = insert_id(c, f"INSERT INTO ticket_types({','.join(cols)}) VALUES({','.join('?' * len(cols))})", list(cols.values()))
    bump(c)
    c.commit()
    return tt_out(c, uid, c.execute("SELECT * FROM ticket_types WHERE id=?", (tid,)).fetchone())


def tt_update(c, uid, tid, b):
    tt_get(c, uid, tid, write=True)
    if "key" in b:
        raise BadInput(tr("The key of a ticket type cannot be changed"))
    f = tt_clean(b, False)
    if f:
        c.execute(f"UPDATE ticket_types SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), tid])
        bump(c)
        c.commit()
    return tt_out(c, uid, c.execute("SELECT * FROM ticket_types WHERE id=?", (tid,)).fetchone())


def tt_delete(c, uid, tid, confirm):
    """Without confirm and with tasks of this type: Denied 409 with the count (the app asks); with: those tasks lose their type,
    the projects of the workspace forget it as their default / offered type."""
    r = tt_get(c, uid, tid, write=True)
    oid, owner, key = r["org_id"], r["owner_id"], r["key"]
    write_lock(c, f"ticket-types-{oid or 'u' + str(owner)}")  # 2.609.0 (#3372)
    n = tt_task_count(c, oid, owner, key)
    if n and not confirm:
        e = Denied(409, trn("{0} task has this type and will have no type", "{0} tasks have this type and will have no type", n, n),
                   data={"code": "has_tasks", "tasks": n})
        e.v1_name, e.v1_extra = "has_tasks", {"tasks": n}
        raise e
    q = "org_id=?" if oid else "org_id IS NULL AND owner_id=?"
    # review F8: the tasks changed (API clients with updated_since, the sync see it)
    c.execute(f"UPDATE tasks SET ttype='', updated_at=? WHERE ttype=? AND list_id IN (SELECT id FROM lists WHERE {q})", (iso(now_utc()), key, oid or owner))
    c.execute(f"UPDATE lists SET def_ttype='' WHERE def_ttype=? AND {q}", (key, oid or owner))
    for lr in c.execute(f"SELECT id, ttypes FROM lists WHERE {q} AND ttypes ILIKE ?", (oid or owner, f'%"{key}"%')).fetchall():
        try:
            keep = [k for k in json.loads(lr["ttypes"]) if k != key]
        except ValueError:
            keep = []
        c.execute("UPDATE lists SET ttypes=? WHERE id=?", (json.dumps(keep) if keep else "", lr["id"]))
    c.execute("DELETE FROM ticket_types WHERE id=?", (tid,))
    bump(c)
    c.commit()
    return {"ok": True, "tasks": n}


def _web(fn, *a):
    try:
        return jsonify(fn(*a))
    except BadInput as e:
        return err(str(e))


@app.get("/api/ticket-types")
def tt_index():
    """?space=private|org:<id> = one workspace for its settings; without = every type the person can meet (to show them)."""
    c, uid = db(), me()
    return _web(tt_index_data, c, uid, request.args.get("space"))


@app.post("/api/ticket-types")
def tt_create_route():
    c, uid = db(), me()
    return _web(tt_create, c, uid, body())


@app.patch("/api/ticket-types/<int:tid>")
def tt_update_route(tid):
    c, uid = db(), me()
    return _web(tt_update, c, uid, tid, body())


@app.delete("/api/ticket-types/<int:tid>")
def tt_delete_route(tid):
    c, uid = db(), me()
    return _web(tt_delete, c, uid, tid, request.args.get("confirm") in ("1", "true"))


@app.get("/api/lists/<int:lid>/ticket-types")
def tt_list_route(lid):
    """The types project lid offers (keys in order; what the app's type pickers show)."""
    c = db()
    need_list(c, lid, write=False)
    return jsonify(keys=tt_offered(c, lid))


# ---- API v1 (+ MCP list_ticket_types): agents read, people with a token manage like in the app
TT_V1_FIELDS = ("space", "key", "name", "icon", "color", "template", "sort", "enabled")


@app.get("/api/v1/ticket-types")
@v1_view
def v1_tt_index():
    v1_args(("space",))
    return jsonify(tt_index_data(db(), me(), request.args.get("space")))


@app.post("/api/v1/ticket-types")
@v1_view
def v1_tt_create():
    v1_args(())
    b = v1_json()
    reject_unknown(b, TT_V1_FIELDS)
    return jsonify(tt_create(db(), me(), b))


@app.patch("/api/v1/ticket-types/<int:tid>")
@v1_view
def v1_tt_update(tid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, TT_V1_FIELDS)
    return jsonify(tt_update(db(), me(), tid, b))


@app.delete("/api/v1/ticket-types/<int:tid>")
@v1_view
def v1_tt_delete(tid):
    v1_args(("confirm",))
    return jsonify(tt_delete(db(), me(), tid, request.args.get("confirm") in ("1", "true")))


@app.get("/api/v1/lists/<int:lid>/ticket-types")
@v1_view
def v1_tt_list(lid):
    v1_args(())
    c = db()
    need_list(c, lid, write=False)
    return jsonify(keys=tt_offered(c, lid))


def tt_spec(paths, schemas, op, ok, errs, ref, pid, q):
    schemas["TicketType"] = {"type": "object", "description": "2.609.0 (#3372): an own ticket type of a workspace", "properties": {
        "id": {"type": "integer"}, "key": {"type": "string", "description": "What a task's type holds (lower case, unique per workspace)"},
        "name": {"type": "string"}, "icon": {"type": "string", "enum": ["", *TT_ICONS]},
        "color": {"type": "string", "description": "#rrggbb or empty"}, "template": {"type": "string", "description": "Note template of a new ticket"},
        "sort": {"type": "integer"}, "enabled": {"type": "boolean", "description": "false = kept, not offered"},
        "org_id": {"type": ["integer", "null"]}, "space": {"type": "string", "description": "private or org:<id>"},
        "owner_id": {"type": "integer", "description": "Only for a private type: the person"},
        "can_edit": {"type": "boolean"}, "tasks": {"type": "integer", "description": "Only with ?space: tasks of this type"}}}
    tt_body = {"type": "object", "additionalProperties": False, "properties": {
        "space": {"type": "string", "description": "private (default) or org:<id>; only when creating"},
        "key": {"type": "string", "pattern": TT_KEY_RE.pattern, "description": "Only when creating; default from the name. "
                "epic / story alone switch the shipped suggestion on"},
        "name": {"type": "string", "maxLength": TT_NAME_MAX}, "icon": {"type": "string", "enum": ["", *TT_ICONS]},
        "color": {"type": "string"}, "template": {"type": "string", "maxLength": TICKET_TPL_MAX}, "sort": {"type": "integer"},
        "enabled": {"type": "boolean"}}}
    T = "Ticket types"
    lst = {"type": "object", "properties": {"types": {"type": "array", "items": ref("TicketType")},
                                            "builtin": {"type": "array", "items": {"type": "string"}},
                                            "suggestions": {"type": "array", "items": {"type": "object"}}}}
    paths["/ticket-types"] = {
        "get": op("2.609.0 (#3372): ticket types. Without space: every own type you can meet (yours, your organisations', the owners' "
                  "of private projects you see); with space: the ones of that workspace with their task counts and the suggestions",
                  T, ok(lst) | errs("400", "404"), [q("space", "private or org:<id>")]),
        "post": op("Create an own ticket type (an organisation's admins, a person their own; not agents). At most 20 per workspace",
                   T, ok(ref("TicketType")) | errs("400", "403", "404"),
                   body=tt_body, scope="write")}
    paths["/ticket-types/{id}"] = {
        "patch": op("Change an own ticket type (not its key; not agents)", T, ok(ref("TicketType")) | errs("400", "403", "404"),
                    [pid("id", "Ticket type id")], body=tt_body, scope="write"),
        "delete": op("Delete an own ticket type. Tasks of this type: 409 has_tasks with their count, then again with confirm=1: they "
                     "get no type", T, ok({"type": "object"}) | errs("403", "404", "409"),
                     [pid("id", "Ticket type id"), q("confirm", "1 = also when tasks have this type", {"type": "string"})], scope="delete")}  # review F8: as deleting a field
    paths["/lists/{id}/ticket-types"] = {"get": op(
        "The ticket type keys a project offers (built-in and own, in order)", T,
        ok({"type": "object", "properties": {"keys": {"type": "array", "items": {"type": "string"}}}}) | errs("404"), [pid("id", "List id")])}
