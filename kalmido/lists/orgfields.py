"""2.609.0 (#3373): the field schema of an organisation -- fields defined once (org_fields) that a project of the organisation
takes over with a switch as linked custom fields (list_fields.org_field_id). A linked field stays a field of the list (values,
columns, filters, pinned / required per project), but its name and options are the organisation's: a change there reaches every
linked project, removed options leave their values everywhere. The key (a-z, 0-9, _) is the same in every project, so the API
can evaluate a field over projects (GET /api/v1/tasks?fkey_<key>=value). Without an organisation the same works with the
person's own fields (org_id NULL, owner_id): their lists without an organisation take them over.

Only its admins change the fields of an organisation; every member with the full view reads them, the owner of a list (or its
project admins) switches them on. Fields of another organisation are never offered (404). Only for people in the app: agents
read the linked fields (and their key) in the list object."""
import json
import re

from flask import g, has_request_context, jsonify

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import MANAGE_ROLES, Denied, need_list
from ..core.errors import BadInput
from ..accounts.orgs import is_org_admin
from ..accounts.orgroles import org_writes, user_orgs_full
from .fields import FIELD_MAX, field_clean_def, field_prune_opts, tb_fields_module_on

OF_MAX = 50  # fields per organisation / person
OF_TYPES_OFF = ("formula",)  # a formula names the fields of one project: not shared
OF_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")


def of_need_person():
    u = getattr(g, "user", None) if has_request_context() else None
    try:
        agent = bool(u) and (u["kind"] or "user") == "agent"
    except (KeyError, IndexError):
        agent = False
    if agent or (has_request_context() and g.get("auth_via") == "token"):
        raise Denied(403, tr("The fields of an organisation are only managed in the app"))


def of_space(c, uid, v):
    """org id (None = the person's own fields) of a space value "private" | "org:<id>" | <id>; 404 for an organisation uid
    does not fully see, 403 for a member who is no admin of it."""
    if v in (None, "", "private", 0, "0"):
        return None
    s = str(v)
    s = s[4:] if s.startswith("org:") else s
    try:
        oid = int(s)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "space")) from None
    if oid not in user_orgs_full(c, uid):
        raise Denied(404)
    return oid


def of_may_write(c, uid, r):
    if r["org_id"] is None:
        return r["owner_id"] == uid
    return org_writes(c, uid, r["org_id"]) and is_org_admin(c, uid, r["org_id"])


def of_get(c, uid, ofid, write=False):
    r = c.execute("SELECT * FROM org_fields WHERE id=?", (ofid,)).fetchone()
    if not r or (r["org_id"] is None and r["owner_id"] != uid) or (r["org_id"] is not None and r["org_id"] not in user_orgs_full(c, uid)):
        raise Denied(404)
    if write and not of_may_write(c, uid, r):
        raise Denied(403, tr("Only an administrator of the organisation can change its fields"))
    return r


def of_out(c, uid, r):
    return {"id": r["id"], "space": f"org:{r['org_id']}" if r["org_id"] else "private", "org_id": r["org_id"], "key": r["key"],
            "name": r["name"], "type": r["type"], "options": json.loads(r["options"] or "{}"), "sort": r["sort"],
            "can_edit": of_may_write(c, uid, r),
            "lists": c.execute("SELECT COUNT(*) FROM list_fields WHERE org_field_id=?", (r["id"],)).fetchone()[0]}


def of_key(c, oid, uid, v, name):
    """The key of a new field: the one given (checked) or made from the name; unique in its space (BadInput)."""
    if v not in (None, ""):
        k = str(v).strip().lower()
        if not OF_KEY_RE.fullmatch(k):
            raise BadInput(tr("The key may hold a-z, 0-9 and _ and starts with a letter"))
    else:
        k = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", name.lower().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})))).strip("_")
        k = k if k[:1].isalpha() else "f_" + k
        k = k[:40].rstrip("_") or "field"
    q, a = ("org_id=?", (oid,)) if oid else ("org_id IS NULL AND owner_id=?", (uid,))
    if c.execute(f"SELECT 1 FROM org_fields WHERE {q} AND key=?", (*a, k)).fetchone():
        raise BadInput(tr("A field with the key “{0}” exists already", k))
    return k


@app.get("/api/org-fields")
def of_index():
    """The fields of the person's organisations (full view) and their own: {fields: [...]}."""
    of_need_person()
    c, uid = db(), me()
    orgs = user_orgs_full(c, uid)
    q, a = "(org_id IS NULL AND owner_id=?)", [uid]
    if orgs:
        q += f" OR org_id IN ({','.join('?' * len(orgs))})"
        a += orgs
    rows = c.execute(f"SELECT * FROM org_fields WHERE {q} ORDER BY org_id NULLS FIRST, sort, id", a).fetchall()
    return jsonify(fields=[of_out(c, uid, r) for r in rows])


@app.post("/api/org-fields")
def of_create():
    """{space?, name, type, options?, key?}: an admin of the organisation (space "org:<id>") or the person (own fields)."""
    of_need_person()
    b = body()
    c, uid = db(), me()
    try:
        oid = of_space(c, uid, b.get("space"))
        if oid and not (org_writes(c, uid, oid) and is_org_admin(c, uid, oid)):
            raise Denied(403, tr("Only an administrator of the organisation can change its fields"))
        name, ftype, opts = field_clean_def(b)
        if ftype in OF_TYPES_OFF:
            raise BadInput(tr("A formula field belongs to one project"))
        key = of_key(c, oid, uid, b.get("key"), name)
    except BadInput as e:
        return err(str(e))
    q, a = ("org_id=?", (oid,)) if oid else ("org_id IS NULL AND owner_id=?", (uid,))
    if c.execute(f"SELECT COUNT(*) FROM org_fields WHERE {q}", a).fetchone()[0] >= OF_MAX:
        return err(tr("At most {0} fields", OF_MAX))
    srt = c.execute(f"SELECT COALESCE(MAX(sort),0)+1 FROM org_fields WHERE {q}", a).fetchone()[0]
    ofid = insert_id(c, "INSERT INTO org_fields(org_id,owner_id,key,name,type,options,sort,created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (oid, None if oid else uid, key, name, ftype, json.dumps(opts, ensure_ascii=False), srt, iso(now_utc())))
    bump(c)
    c.commit()
    return jsonify(of_out(c, uid, c.execute("SELECT * FROM org_fields WHERE id=?", (ofid,)).fetchone()))


@app.patch("/api/org-fields/<int:ofid>")
def of_update(ofid):
    """{name?, options?, sort?}: the type and the key stay. Name and options reach every linked project (removed options
    leave their values there)."""
    of_need_person()
    b = body()
    c, uid = db(), me()
    of_get(c, uid, ofid, write=True)
    write_lock(c, f"org-field-{ofid}")  # 2.609.0 (#3373): one change of a schema field at a time (it reaches every linked project)
    r = c.execute("SELECT * FROM org_fields WHERE id=?", (ofid,)).fetchone()
    try:
        name, _, opts = field_clean_def(b, r)
    except BadInput as e:
        return err(str(e))
    if "sort" in b:
        try:
            c.execute("UPDATE org_fields SET sort=? WHERE id=?", (float(b["sort"]), ofid))
        except (TypeError, ValueError):
            return err(tr("Invalid data"))
    o = json.dumps(opts, ensure_ascii=False)
    c.execute("UPDATE org_fields SET name=?, options=? WHERE id=?", (name, o, ofid))
    for (fid,) in c.execute("SELECT id FROM list_fields WHERE org_field_id=?", (ofid,)).fetchall():
        field_prune_opts(c, fid, r["type"], opts)
        c.execute("UPDATE list_fields SET name=?, options=? WHERE id=?", (name, o, fid))
    bump(c)
    c.commit()
    return jsonify(of_out(c, uid, c.execute("SELECT * FROM org_fields WHERE id=?", (ofid,)).fetchone()))


@app.delete("/api/org-fields/<int:ofid>")
def of_delete(ofid):
    """The field leaves the schema; the linked fields stay in their projects as plain fields (with their values)."""
    of_need_person()
    c, uid = db(), me()
    of_get(c, uid, ofid, write=True)
    n = c.execute("UPDATE list_fields SET org_field_id=NULL WHERE org_field_id=?", (ofid,)).rowcount
    c.execute("DELETE FROM org_fields WHERE id=?", (ofid,))
    bump(c)
    c.commit()
    return jsonify(ok=True, unlinked=n)


def of_for_list(c, lid):
    """The org_fields rows list lid may take over: its organisation's, or (a list without one) its owner's own."""
    lst = c.execute("SELECT org_id, owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not lst:
        return []
    if lst["org_id"]:
        return c.execute("SELECT * FROM org_fields WHERE org_id=? ORDER BY sort, id", (lst["org_id"],)).fetchall()
    return c.execute("SELECT * FROM org_fields WHERE org_id IS NULL AND owner_id=? ORDER BY sort, id", (lst["owner_id"],)).fetchall()


def of_schema_seen(c, uid, lid, role):
    """2.609.0 (#3373): may uid (role in list lid) see the whole schema of the list's workspace? (of_list_index, review F7: and
    switch on a field of it that is not linked yet)"""
    oid = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
    return oid in user_orgs_full(c, uid) if oid else role in MANAGE_ROLES


@app.get("/api/lists/<int:lid>/org-fields")
def of_list_index(lid):
    """The fields of the list's organisation (its owner's own without one) with "field_id" = the linked field of the list (null = off).
    2.609.0 (#3373): the whole schema only for those who may see it (a member of the organisation with full access; without
    one the owner and the project's admins); any other viewer (a guest, a person outside the organisation) gets only the
    fields linked in this list."""
    of_need_person()
    c, uid = db(), me()
    role = need_list(c, lid, write=False)
    linked = {r[0]: r[1] for r in c.execute("SELECT org_field_id, id FROM list_fields WHERE list_id=? AND org_field_id IS NOT NULL", (lid,))}
    full = of_schema_seen(c, uid, lid, role)
    return jsonify(fields=[{**of_out(c, uid, r), "field_id": linked.get(r["id"])} for r in of_for_list(c, lid) if full or r["id"] in linked])


@app.put("/api/lists/<int:lid>/org-fields/<int:ofid>")
def of_list_switch(lid, ofid):
    """{on: bool}: on = the list gets the linked field (counts towards the fields of the project), off = the link goes, the
    field stays in the list as a plain one. Owner and project admins."""
    of_need_person()
    b = body()
    c = db()
    role = need_list(c, lid, manage=True)
    r = next((x for x in of_for_list(c, lid) if x["id"] == ofid), None)
    if not r:
        raise Denied(404)  # never a field of another organisation / person
    write_lock(c, f"list-fields-{lid}")  # 2.609.0 (#3373): two switches at once never link the field twice
    have = c.execute("SELECT id FROM list_fields WHERE list_id=? AND org_field_id=?", (lid, ofid)).fetchone()
    fid = have[0] if have else None
    if b.get("on") and not have and not of_schema_seen(c, me(), lid, role):
        raise Denied(404)  # 2.609.0 (#3373, review F7): a field of the schema this person does not see (switching off stays)
    if b.get("on") and not have:
        if c.execute("SELECT COUNT(*) FROM list_fields WHERE list_id=?", (lid,)).fetchone()[0] >= FIELD_MAX:
            return err(tr("At most {0} fields per project", FIELD_MAX))
        srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM list_fields WHERE list_id=?", (lid,)).fetchone()[0]
        fid = insert_id(c, "INSERT INTO list_fields(list_id,name,type,options,pinned,sort,created_at,org_field_id) VALUES(?,?,?,?,?,?,?,?)",
                        (lid, r["name"], r["type"], r["options"], 0, srt, iso(now_utc()), ofid))
        tb_fields_module_on(c, lid)
    elif not b.get("on") and have:
        c.execute("UPDATE list_fields SET org_field_id=NULL WHERE id=?", (fid,))
        fid = None
    bump(c)
    c.commit()
    return jsonify(ok=True, field_id=fid)
