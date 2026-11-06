"""2.558.0 (#4709): the shared core, stage 1 -- ONE write path for core objects (core/objects.py, docs/dev/kern.md).

obj_write does in one call what the areas used to do in pieces (each with its own gaps, audit #2822 part B):
  rights (obj_need 'write') -> write_lock('obj-<kind>-<id>') -> the row again under the lock -> the version check
  (expect_updated_at, core/conflict.py ccf_check: 409 with the current state under "current"; an AGENT must send it: 400
  without) -> only the fields sent (partial_clean, the kind's cleaners; an unknown field = 400) -> nothing changed = nothing
  written -> the undo step (header X-Kalmido-Undo, people only) -> rev+1, updated_at, updated_by -> the history (obj_history:
  before / after of the changed fields, an agent marked, the changes of one person within OBJ_MERGE_MIN merged) -> the
  title on the reference node -> bump(the kind's area). The caller commits.

Trash: obj_trash / obj_restore (deleted_at, deleted_by; 'manage' or the kind's trash_role), obj_purge (only from the trash,
'manage'; the reference node, the history, the undo steps and the revoked shares go with it).
Undo: obj_undo(c, uid, kind, id, sess, op) generalises office/undo.py -- a copy of the object's rows before each own step of an
editor session (header X-Kalmido-Undo: <token>), written back only while the object is exactly as that step left it
(fingerprint; someone else's change in between = 409). undo_scope of the kind = more tables than the main row (stage 2: the
office's documents with their parts).
Adapters for write paths that do not go through obj_write yet (stage 2 ff., like office/otrash.py otb_put):
  obj_undo_pre(c, uid, kind, id) / obj_undo_post(c)      record a step around an own write (in its transaction)
  obj_history_add(c, uid, kind, id, before, after, action) note a change in the history
  obj_touch(c, uid, kind, id)                             rev+1, updated_at, updated_by, bump (sh_touch for core objects)

Interface:
  obj_create(c, uid, kind, vals, org_id=None) -> row
  obj_write(c, uid, kind, id, body, expect=None) -> (row, changed fields)
  obj_trash(c, uid, kind, id) -> row, obj_restore(c, uid, kind, id) -> row, obj_purge(c, uid, kind, id)
  obj_space_set(c, uid, kind, id, org_id) -> (row, moved?)   2.579.0 (#4802): into an organisation / back to the owner's own space
  obj_history(c, uid, kind, id, limit=50) -> [{id, at, user_id, name, agent, action, before, after}]  ('view')
  obj_undo(c, uid, kind, id, sess, op) -> {state counts}            op undo | redo | all | redoall
  obj_is_agent(c, uid) -> bool

2.567.0 (#4711, stage 2): old areas whose rows have no owner_id / rev (the office, the clients) are no registered kinds yet:
obj_track(kind, table, area=..., undo_scope=..., undo_keep=..., undo_nofp=...) names them for the history and the undo
only (no rights, no routes, no folders -- the area keeps its own checks). obj_history_add, obj_undo_pre / obj_undo_post and
obj_undo_run (= obj_undo without its rights check, the area checked them) take such a kind like a registered one; the office's
one write call on top is office/owrite.py ow_write."""
import base64
import hashlib
import json
from datetime import timedelta

from flask import g, has_request_context, request

from .access import Denied, acx_of, acx_org_ok, need_feat
from .conflict import VersionRequired, ccf_check
from .db import bump, insert_id, iso, iso_ms, now_utc
from .errors import BadInput, UnknownFields
from .i18n import N_, tr
from .objects import OBJ_COLS, obj_need, obj_node_follow, obj_public, obj_reg, obj_row, obj_title, obj_forget
from .pg import system_ctx, table_columns, write_lock
from ..collab.comments import user_names
from ..accounts.orgroles import need_org_write, org_role_key
from ..accounts.orgout import org_out  # 2.579.0 (#4802): obj_space_set
from ..files.fsref import fs_ref_drop, fs_ref_rename
from ..files.store import _free_name

OBJ_MERGE_MIN = 10  # changes of one person to one object within this many minutes are one history entry (wiki/wkhist.py)
OBJ_HISTORY_MAX = 200  # entries kept per object (the oldest go)
META_KEYS = ("expect_updated_at",)
UNDO_HDR = "X-Kalmido-Undo"  # the same header as office/undo.py (static/js/office_undo.js, static/js/objsave.js)
UNDO_OPS = ("undo", "redo", "all", "redoall")
UNDO_KEEP_H = 24
UNDO_MAX_STEPS = 60
UNDO_FIXED = {"id", "org_id", "owner_id", "kind", "created_at", "created_by", "rev", "updated_at", "updated_by", "deleted_at", "deleted_by"}
UNDO_NO_FP = {"updated_at", "rev", "updated_by"}
NEED_VERSION = N_("Send expect_updated_at (the updated_at you read): agents change an object only with its version")
UNDO_CONFLICT = N_("Changed by someone else in the meantime, so it cannot be undone")
UNDO_MOVED = N_("Moved to another workspace in the meantime, so it cannot be undone")
UNDO_NOTHING = N_("Nothing to undo")
PURGE_FIRST = N_("Put it into the trash first")
JOIN_ADMIN = N_("Only admins of the organisation can share this with everyone of it")  # 2.579.0 (#4802)
MOVE_OWNER = N_("Its owner is not a member of that organisation")
MOVE_SHARED = N_("It is shared with people or agents: remove those shares first")
OBJ_TRACK = {}  # 2.567.0 (#4711): kind -> {table, area, undo_scope, undo_keep, undo_nofp, fields: None} (obj_track)


def obj_track(kind, table, *, area="other", undo_scope=None, undo_keep=None, undo_nofp=None):
    """2.567.0 (#4711): an old area's kind for the history and the undo only (module docstring). undo_keep / undo_nofp:
    {table: {column}} never written back on undo / never part of the fingerprint (a number drawn since, cached sums)."""
    OBJ_TRACK[kind] = {"kind": kind, "table": table, "area": area, "undo_scope": undo_scope, "fields": None,
                       "undo_keep": dict(undo_keep or {}), "undo_nofp": dict(undo_nofp or {})}
    return OBJ_TRACK[kind]


def _reg(kind):
    """A registered kind or one of obj_track."""
    return OBJ_TRACK.get(kind or "") or obj_reg(kind)


def obj_is_agent(c, uid):
    """Does uid write as an agent (its account, also through its token)?"""
    return acx_of(c, uid).role == "agent"


def _now():
    return iso_ms(now_utc())


def _clean(c, reg, b, row):
    """{field: clean value} of the fields sent (partial: only those); unknown keys -> 400."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    unknown = [k for k in b if k not in reg["fields"] and k not in META_KEYS]
    if unknown:
        raise UnknownFields(unknown)
    return {k: reg["fields"][k](c, b[k], row) for k in b if k in reg["fields"]}


def _same(a, b):
    return (a if a is not None else None) == (b if b is not None else None)


def _area(reg):
    return None if reg["area"] == "other" else reg["area"]


def obj_touch(c, uid, kind, rid):
    """The object changed (a write path of its own): rev+1, updated_at, updated_by and the area counter (bump)."""
    reg = obj_reg(kind)
    ts = _now()
    c.execute(f"UPDATE {reg['table']} SET rev=rev+1, updated_at=?, updated_by=? WHERE id=?", (ts, uid, int(rid)))
    bump(c, _area(reg))
    return ts


# ---------------------------------------------------------------- history
def obj_history_add(c, uid, kind, rid, before, after, action="update", org_id=None, agent=None):
    """Note a change of the object in obj_history (before / after: {field: value} of what changed). An 'update' of the same
    person (and the same agent flag) within OBJ_MERGE_MIN minutes merges into the last entry: its before stays, after grows."""
    reg = _reg(kind)
    if org_id is None:
        r = (c.execute(f"SELECT org_id FROM {reg['table']} WHERE id=?", (int(rid),)).fetchone() if kind in OBJ_TRACK
             else obj_row(c, kind, rid))
        org_id = (r["org_id"] or None) if r is not None else None
    ag = 1 if (obj_is_agent(c, uid) if agent is None else agent) else 0
    ts = _now()
    if action == "update":
        last = c.execute("SELECT * FROM obj_history WHERE kind=? AND ref_id=? ORDER BY id DESC LIMIT 1", (kind, int(rid))).fetchone()
        lim = iso_ms(now_utc() - timedelta(minutes=OBJ_MERGE_MIN))
        if last is not None and last["action"] == "update" and last["user_id"] == uid and last["agent"] == ag and str(last["updated_at"]) >= lim:
            b0, a0 = json.loads(last["vals_before"] or "{}"), json.loads(last["vals_after"] or "{}")
            for k, v in before.items():
                b0.setdefault(k, v)
            a0.update(after)
            for k in [k for k in a0 if k in b0 and _same(a0[k], b0[k])]:  # changed back within the window: no change any more
                a0.pop(k)
                b0.pop(k)
            c.execute("UPDATE obj_history SET vals_before=?, vals_after=?, updated_at=? WHERE id=?",
                      (json.dumps(b0, default=str), json.dumps(a0, default=str), ts, last["id"]))
            return last["id"]
    hid = insert_id(c, "INSERT INTO obj_history(kind,ref_id,org_id,user_id,agent,action,vals_before,vals_after,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (kind, int(rid), org_id, uid, ag, action, json.dumps(before, default=str), json.dumps(after, default=str), ts, ts))
    n = c.execute("SELECT COUNT(*) FROM obj_history WHERE kind=? AND ref_id=?", (kind, int(rid))).fetchone()[0]
    if n > OBJ_HISTORY_MAX:
        c.execute("DELETE FROM obj_history WHERE id IN (SELECT id FROM obj_history WHERE kind=? AND ref_id=? ORDER BY id LIMIT ?)",
                  (kind, int(rid), n - OBJ_HISTORY_MAX))
    return hid


def obj_history_add_many(c, uid, kind, items, agent=None):
    """2.609.0 (#4928): obj_history_add(action 'update') for many objects at once, in a few statements per 500 instead of a
    lookup, a write and a count per object (a renamed knowledge folder: one rename per page). items: [(id, before, after,
    org_id)] with each id once; org_id is taken as given (None = a private space, no lookup). The same merge within
    OBJ_MERGE_MIN and the same OBJ_HISTORY_MAX per object as obj_history_add."""
    if not items:
        return
    _reg(kind)
    ag = 1 if (obj_is_agent(c, uid) if agent is None else agent) else 0
    ts = _now()
    lim = iso_ms(now_utc() - timedelta(minutes=OBJ_MERGE_MIN))
    for i in range(0, len(items), 500):
        part = items[i:i + 500]
        ids = [int(x[0]) for x in part]
        q = ",".join("?" * len(ids))
        last = {r["ref_id"]: r for r in c.execute(f"SELECT DISTINCT ON (ref_id) * FROM obj_history WHERE kind=? AND ref_id IN ({q}) "
                                                  "ORDER BY ref_id, id DESC", [kind, *ids])}
        upd, ins = [], []
        for rid, before, after, oid in part:
            x = last.get(int(rid))
            if x is not None and x["action"] == "update" and x["user_id"] == uid and x["agent"] == ag and str(x["updated_at"]) >= lim:
                b0, a0 = json.loads(x["vals_before"] or "{}"), json.loads(x["vals_after"] or "{}")
                for k, v in before.items():
                    b0.setdefault(k, v)
                a0.update(after)
                for k in [k for k in a0 if k in b0 and _same(a0[k], b0[k])]:
                    a0.pop(k)
                    b0.pop(k)
                upd += [x["id"], json.dumps(b0, default=str), json.dumps(a0, default=str)]
            else:
                ins += [kind, int(rid), oid, uid, ag, "update", json.dumps(before, default=str), json.dumps(after, default=str), ts, ts]
        if upd:
            c.execute("UPDATE obj_history SET vals_before=v.b, vals_after=v.a, updated_at=? FROM (VALUES "
                      + ",".join(["(CAST(? AS bigint), CAST(? AS text), CAST(? AS text))"] * (len(upd) // 3))
                      + ") AS v(id, b, a) WHERE obj_history.id=v.id", [ts, *upd])
        if ins:
            c.execute("INSERT INTO obj_history(kind,ref_id,org_id,user_id,agent,action,vals_before,vals_after,created_at,updated_at) "
                      "VALUES " + ",".join(["(?,?,?,?,?,?,?,?,?,?)"] * (len(ins) // 10)), ins)
            c.execute(f"DELETE FROM obj_history WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY ref_id ORDER BY id DESC) "
                      f"AS rn FROM obj_history WHERE kind=? AND ref_id IN ({q})) t WHERE rn > ?)", [kind, *ids, OBJ_HISTORY_MAX])


def obj_history(c, uid, kind, rid, limit=50):
    """The history of the object, newest first ('view' on it)."""
    obj_need(c, uid, kind, rid, "view")
    rows = c.execute("SELECT * FROM obj_history WHERE kind=? AND ref_id=? ORDER BY id DESC LIMIT ?", (kind, int(rid), int(limit))).fetchall()
    names = user_names(c, [r["user_id"] for r in rows if r["user_id"]])
    return [{"id": r["id"], "at": r["updated_at"], "created_at": r["created_at"], "user_id": r["user_id"], "name": names.get(r["user_id"], ""),
             "agent": bool(r["agent"]), "action": r["action"], "before": json.loads(r["vals_before"] or "{}"),
             "after": json.loads(r["vals_after"] or "{}")} for r in rows]


# ---------------------------------------------------------------- create / write
def obj_create(c, uid, kind, vals, org_id=None):
    """A new object of kind in uid's private space (org_id None) or organisation org_id (a member / admin). Agents make
    nothing (403, docs/AGENTS.md: creating stays with people; review F4). vals: the kind's fields (the cleaners; unknown =
    400). Returns the row."""
    reg = obj_reg(kind)
    if reg["feat"]:
        need_feat(reg["feat"])
    if acx_of(c, uid).role == "agent":
        raise Denied(403)  # review F4: creating stays with people (an agent's object would have no owner who sees it)
    if org_id is not None:
        if isinstance(org_id, bool) or not isinstance(org_id, int):
            raise BadInput(tr("Invalid value: {0}", "org_id"))
        if not acx_org_ok(c, uid, org_id):
            raise Denied(404)
        need_org_write(c, uid, org_id)
        _join_ok(c, uid, reg, org_id)  # 2.579.0 (#4802)
    v = _clean(c, reg, vals, None)
    for k, f in reg["fields"].items():
        if k not in v:
            v[k] = f(c, None, None)  # the default of a field not sent (a required one refuses here)
    ts = _now()
    cols = ["org_id", "owner_id", "rev", "created_at", "created_by", "updated_at", "updated_by", *v]
    rid = insert_id(c, f"INSERT INTO {reg['table']}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                    (org_id, uid, 1, ts, uid, ts, uid, *v.values()))
    obj_history_add(c, uid, kind, rid, {}, {k: x for k, x in v.items() if x not in (None, "", 0)}, action="create", org_id=org_id)
    bump(c, _area(reg))
    return obj_row(c, kind, rid)


def obj_write(c, uid, kind, rid, b, expect=None):
    """Change the fields of the object sent in b (module docstring). Returns (row, {field: (before, after)})."""
    reg = obj_reg(kind)
    obj_need(c, uid, kind, rid, "write")
    write_lock(c, f"obj-{kind}-{int(rid)}")
    row = c.execute(f"SELECT * FROM {reg['table']} WHERE id=? FOR UPDATE", (int(rid),)).fetchone()
    if row is None or row["deleted_at"]:
        raise Denied(404)
    b = b if isinstance(b, dict) else {}
    exp = expect if expect is not None else b.get("expect_updated_at")
    agent = obj_is_agent(c, uid)
    if agent and not exp:
        raise VersionRequired(("expect_updated_at",), tr(NEED_VERSION))  # 2.564.0 (#4702): the agents' one code version_required
    ccf_check({"expect_updated_at": exp}, row["updated_at"], "current", lambda: obj_public(c, uid, kind, row, None))
    vals = _clean(c, reg, b, row)
    changed = {k: (row[k], v) for k, v in vals.items() if not _same(row[k], v)}
    if not changed:
        return row, {}
    oid = row["org_id"] or None
    obj_undo_pre(c, uid, kind, rid, oid)
    ts = _now()
    sets = ",".join(f"{k}=?" for k in changed)
    c.execute(f"UPDATE {reg['table']} SET {sets}, rev=rev+1, updated_at=?, updated_by=? WHERE id=?",
              (*(v for _, v in changed.values()), ts, uid, int(rid)))
    obj_history_add(c, uid, kind, rid, {k: a for k, (a, _) in changed.items()}, {k: z for k, (_, z) in changed.items()},
                    org_id=oid, agent=agent)
    if "title" in changed and not reg["title"]:
        fs_ref_rename(c, kind, rid, obj_title(c, kind, rid))
    obj_undo_post(c)
    bump(c, _area(reg))
    return obj_row(c, kind, rid), changed


def _join_ok(c, uid, reg, org_id):
    """2.579.0 (#4802): a kind registered with org_join="admin" comes into an organisation only through its admins."""
    if reg.get("org_join") == "admin" and org_role_key(c, uid, org_id) != "admin":
        raise Denied(403, tr(JOIN_ADMIN))


def obj_space_set(c, uid, kind, rid, org_id):
    """2.579.0 (#4802): the object moves into organisation org_id, or (None) back into its owner's own space -- e.g. a saved view
    an admin shares with everyone of the organisation (the members get the kind's org_access) and takes back again.
    Needs 'manage' and a person (no agent); into an organisation: a member who writes there (need_org_write; the kind's
    org_join "admin": only its admins), its owner a member there too; out of an organisation: only its admin
    (accounts/orgout.py org_out: logged, News to the other admins). An object whose reference node carries shares is refused
    (409): they were made for the old workspace (the owner takes them back first). rev+1, updated_at, the history ('move', the
    org_id before / after), the reference node follows (objects.obj_node_follow), bump. Returns (row, moved). The caller commits."""
    reg = obj_reg(kind)
    obj_need(c, uid, kind, rid, "manage")
    if obj_is_agent(c, uid):
        raise Denied(403)
    if org_id is not None and (isinstance(org_id, bool) or not isinstance(org_id, int)):
        raise BadInput(tr("Invalid value: {0}", "org_id"))
    write_lock(c, f"obj-{kind}-{int(rid)}")
    row = c.execute(f"SELECT * FROM {reg['table']} WHERE id=? FOR UPDATE", (int(rid),)).fetchone()
    if row is None or row["deleted_at"]:
        raise Denied(404)
    old = row["org_id"] or None
    if old == org_id:
        return row, False
    if org_id is not None:
        if not acx_org_ok(c, uid, org_id):
            raise Denied(404)
        need_org_write(c, uid, org_id)
        _join_ok(c, uid, reg, org_id)
        if row["owner_id"] != uid and org_role_key(c, row["owner_id"], org_id) is None:
            raise Denied(409, tr(MOVE_OWNER))
    if old is not None:
        org_out(c, old, org_id, kind, obj_title(c, kind, rid) or tr(reg["label"]))  # 403 for anybody but its admin
    with system_ctx(c):  # structure: whether its node (in the tree it leaves) carries a share
        shared = c.execute("SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind=? AND n.ref_id=? "
                           "LIMIT 1", (kind, int(rid))).fetchone()
    if shared:
        raise Denied(409, tr(MOVE_SHARED))
    ts = _now()
    c.execute(f"UPDATE {reg['table']} SET org_id=?, rev=rev+1, updated_at=?, updated_by=? WHERE id=?", (org_id, ts, uid, int(rid)))
    obj_history_add(c, uid, kind, rid, {"org_id": old}, {"org_id": org_id}, action="move", org_id=org_id)
    obj_node_follow(c, kind, rid)
    obj_forget()
    bump(c, _area(reg))
    return obj_row(c, kind, rid), True


# ---------------------------------------------------------------- trash
def _trash_need(reg):
    return "write" if reg["trash_role"] == "edit" else "manage"


def obj_trash(c, uid, kind, rid):
    """Into the trash (deleted_at): restorable by who manages it (obj_restore)."""
    reg = obj_reg(kind)
    obj_need(c, uid, kind, rid, _trash_need(reg))
    write_lock(c, f"obj-{kind}-{int(rid)}")
    ts = _now()
    c.execute(f"UPDATE {reg['table']} SET deleted_at=?, deleted_by=?, rev=rev+1, updated_at=?, updated_by=? WHERE id=? AND deleted_at IS NULL",
              (ts, uid, ts, uid, int(rid)))
    # review F7: its reference node goes into the file store's trash with it (the folders hide it as any node there)
    c.execute("UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE kind='ref' AND ref_kind=? AND ref_id=? AND deleted_at IS NULL",
              (ts, uid, kind, int(rid)))
    obj_history_add(c, uid, kind, rid, {}, {}, action="trash")
    obj_forget()
    bump(c, _area(reg))
    return obj_row(c, kind, rid)


def obj_restore(c, uid, kind, rid):
    """Out of the trash ('manage')."""
    reg = obj_reg(kind)
    row, _ = obj_need(c, uid, kind, rid, "manage", trash=True)
    write_lock(c, f"obj-{kind}-{int(rid)}")
    n = c.execute("SELECT * FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=? AND deleted_at=?", (kind, int(rid), row["deleted_at"])).fetchone()
    if n is not None:  # review F7: the node obj_trash put into the trash comes back (not one the file store's own trash holds)
        nm = _free_name(c, n["parent_id"], n["owner_id"], n["org_id"], n["name"], skip=n["id"])
        c.execute("UPDATE fs_nodes SET deleted_at=NULL, deleted_by=NULL, name=? WHERE id=?", (nm, n["id"]))
    ts = _now()
    c.execute(f"UPDATE {reg['table']} SET deleted_at=NULL, deleted_by=NULL, rev=rev+1, updated_at=?, updated_by=? WHERE id=?",
              (ts, uid, int(rid)))
    obj_history_add(c, uid, kind, rid, {}, {}, action="restore")
    obj_forget()
    bump(c, _area(reg))
    return obj_row(c, kind, rid)


def obj_purge(c, uid, kind, rid):
    """Delete for good: only an object in the trash ('manage'; 409 otherwise). Its node, history, undo steps and revoked
    shares go with it."""
    reg = obj_reg(kind)
    row = obj_row(c, kind, rid)
    if row is not None and not row["deleted_at"]:
        obj_need(c, uid, kind, rid, "manage")
        raise Denied(409, tr(PURGE_FIRST))
    obj_need(c, uid, kind, rid, "manage", trash=True)
    write_lock(c, f"obj-{kind}-{int(rid)}")
    fs_ref_drop(c, kind, rid)
    for t in ("obj_history", "obj_undo", "obj_revoked"):
        c.execute(f"DELETE FROM {t} WHERE kind=? AND ref_id=?", (kind, int(rid)))
    c.execute(f"DELETE FROM {reg['table']} WHERE id=?", (int(rid),))
    obj_forget()
    bump(c, _area(reg))


# ---------------------------------------------------------------- undo (office/undo.py, generalised)
def _val(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$b": base64.b64encode(bytes(v)).decode()}
    return v


def _unval(v):
    return base64.b64decode(v["$b"]) if isinstance(v, dict) and "$b" in v else v


def undo_scope(kind, rid, oid):
    """[(table, where, args, several rows?)] of the object; the first is its main row."""
    reg = _reg(kind)
    if reg["undo_scope"]:
        return reg["undo_scope"](int(rid), oid)
    return [(reg["table"], "id=?", (int(rid),), False)]


def _snap(c, sc):
    out = {}
    for t, where, args, _many in sc:
        rows = c.execute(f"SELECT * FROM {t} WHERE {where} ORDER BY id", args).fetchall()
        out[t] = [{k: _val(r[k]) for k in r.keys()} for r in rows]
    return out


def _fp(snap, nofp=None):
    nofp = nofp or {}
    s = {t: [{k: v for k, v in r.items() if k not in UNDO_NO_FP and k not in nofp.get(t, ())} for r in rows] for t, rows in snap.items()}
    return hashlib.sha256(json.dumps(s, sort_keys=True, default=str).encode()).hexdigest()


def _lock_rows(c, sc):
    t, where, args, _many = sc[0]
    c.execute(f"SELECT id FROM {t} WHERE {where} FOR UPDATE", args).fetchall()


def _write_back(c, sc, snap, uid, keep=None):
    """Copy snap back: the main row's own columns (not its identity, version, trash), the other tables' rows replaced.
    keep {table: {column}}: columns that stay as they are now (obj_track undo_keep)."""
    keep = keep or {}
    for t, where, args, many in reversed(sc):
        if many:
            c.execute(f"DELETE FROM {t} WHERE {where}", args)
    for i, (t, where, args, many) in enumerate(sc):
        cols = table_columns(c, t)
        rows = snap.get(t) or []
        if not many:
            if not rows:
                continue
            row = {k: _unval(v) for k, v in rows[0].items() if k in cols and k not in UNDO_FIXED and k not in keep.get(t, ())}
            if i == 0 and {"rev", "updated_at", "updated_by"} <= cols:
                c.execute(f"UPDATE {t} SET {','.join(k + '=?' for k in row)}{',' if row else ''} rev=rev+1, updated_at=?, updated_by=? WHERE {where}",
                          [*row.values(), _now(), uid, *args])
            elif i == 0 and "updated_at" in cols:  # 2.567.0 (#4711): an old area's row (obj_track): a new version for the next save
                row.update(updated_at=_now(), **({"updated_by": uid} if "updated_by" in cols else {}))
                c.execute(f"UPDATE {t} SET {','.join(k + '=?' for k in row)} WHERE {where}", [*row.values(), *args])
            elif row:
                c.execute(f"UPDATE {t} SET {','.join(k + '=?' for k in row)} WHERE {where}", [*row.values(), *args])
            continue
        for r in rows:
            row = {k: _unval(v) for k, v in r.items() if k in cols}
            c.execute(f"INSERT INTO {t}({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def _token():
    import re
    if not has_request_context():
        return ""
    tok = (request.headers.get(UNDO_HDR) or "").strip().lower()
    return tok if re.fullmatch(r"[a-f0-9]{16,64}", tok) else ""


def obj_undo_pre(c, uid, kind, rid, oid=None):
    """Before a write changes the object: with the header (a person's editor session), the state before = one step."""
    tok = _token()
    if not tok or obj_is_agent(c, uid):
        return
    sc = undo_scope(kind, rid, oid)
    _lock_rows(c, sc)
    snap = _snap(c, sc)
    main = (snap.get(sc[0][0]) or [None])[0]
    if not main:
        return
    key = (uid, tok, kind, int(rid))
    c.execute("DELETE FROM obj_undo WHERE user_id=? AND sess=? AND kind=? AND ref_id=? AND state<>'done'", key)  # a new step ends the way forward
    rows = c.execute("SELECT id, seq, fp_after FROM obj_undo WHERE user_id=? AND sess=? AND kind=? AND ref_id=? ORDER BY seq", key).fetchall()
    if not rows:
        c.execute("DELETE FROM obj_undo WHERE created_at<?", (iso(now_utc() - timedelta(hours=UNDO_KEEP_H)),))
    elif len(rows) >= UNDO_MAX_STEPS:
        c.execute("UPDATE obj_undo SET fp_after=? WHERE id=?", (rows[1]["fp_after"], rows[0]["id"]))
        c.execute("DELETE FROM obj_undo WHERE id=?", (rows[1]["id"],))
    sid = insert_id(c, "INSERT INTO obj_undo(org_id, user_id, sess, kind, ref_id, seq, state, snap, fp_before, fp_after, created_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (main.get("org_id"), uid, tok, kind, int(rid), (rows[-1]["seq"] + 1) if rows else 1, "done",
                     json.dumps(snap, ensure_ascii=False, default=str), _fp(snap, _nofp(kind)), "", iso(now_utc())))
    g.obj_undo_step = (sid, sc, _nofp(kind))


def obj_undo_post(c):
    """Right before the commit of the write: the state after the step (what an undo expects to find)."""
    st = g.pop("obj_undo_step", None) if has_request_context() else None
    if st:
        c.execute("UPDATE obj_undo SET fp_after=? WHERE id=?", (_fp(_snap(c, st[1]), st[2]), st[0]))


def _nofp(kind):
    return _reg(kind).get("undo_nofp") or {}


def _main_org(snap, sc):
    return ((snap.get(sc[0][0]) or [{}])[0]).get("org_id")


def _undo_one(c, sc, st, uid, reg, fix=None):
    nofp = reg.get("undo_nofp") or {}
    cur = _snap(c, sc)
    if not st["fp_after"] or _fp(cur, nofp) != st["fp_after"]:
        raise Denied(409, tr(UNDO_CONFLICT))
    old = json.loads(st["snap"])
    if _main_org(old, sc) != _main_org(cur, sc):
        raise Denied(409, tr(UNDO_MOVED))
    _write_back(c, sc, old, uid, reg.get("undo_keep"))
    if fix:
        fix(c)
    c.execute("UPDATE obj_undo SET state='undone', redo=?, fp_undone=? WHERE id=?",
              (json.dumps(cur, ensure_ascii=False, default=str), _fp(_snap(c, sc), nofp), st["id"]))
    return cur, old


def _redo_one(c, sc, st, uid, reg, fix=None):
    nofp = reg.get("undo_nofp") or {}
    cur = _snap(c, sc)
    if not st["fp_undone"] or _fp(cur, nofp) != st["fp_undone"] or not st["redo"]:
        raise Denied(409, tr(UNDO_CONFLICT))
    new = json.loads(st["redo"])
    if _main_org(new, sc) != _main_org(cur, sc):
        raise Denied(409, tr(UNDO_MOVED))
    _write_back(c, sc, new, uid, reg.get("undo_keep"))
    if fix:
        fix(c)
    c.execute("UPDATE obj_undo SET state='done', redo=NULL, fp_undone=NULL, fp_after=? WHERE id=?", (_fp(_snap(c, sc), nofp), st["id"]))
    return cur, new


def obj_undo(c, uid, kind, rid, sess, op="undo"):
    """undo = the newest own step of session sess back, all = every own step (back to the opening), redo / redoall = the way
    forward again; rights as for a change ('write'). 409 when someone else changed it meanwhile. Returns {state: count}."""
    _undo_args(sess, op)
    row, _ = obj_need(c, uid, kind, rid, "write")
    return obj_undo_run(c, uid, kind, rid, row["org_id"] or None, sess, op)


def _undo_args(sess, op):
    import re
    tok = str(sess or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{16,64}", tok) or op not in UNDO_OPS:
        raise BadInput(tr("Invalid data"))
    return tok


def obj_undo_run(c, uid, kind, rid, oid, sess, op="undo", fix=None, keep=None):
    """2.567.0 (#4711): obj_undo without its rights check -- the caller checked them (an obj_track kind: the area's own,
    office/undo.py). oid = the object's workspace now; fix(c) runs after each write back (the sums of a document).
    2.577.0 (#3964): keep {table: {column}} = columns that stay as they are now on top of undo_keep (fields uid may not change)."""
    tok = _undo_args(sess, op)
    reg = _reg(kind)
    if keep:
        reg = {**reg, "undo_keep": {t: set(reg["undo_keep"].get(t, ())) | set(v) for t, v in {**reg["undo_keep"], **keep}.items()}}
    if obj_is_agent(c, uid):
        raise Denied(403)
    write_lock(c, f"obj-{kind}-{int(rid)}")
    sc = undo_scope(kind, rid, oid)
    _lock_rows(c, sc)
    steps = c.execute("SELECT * FROM obj_undo WHERE user_id=? AND sess=? AND kind=? AND ref_id=? ORDER BY seq", (uid, tok, kind, int(rid))).fetchall()
    done = [s for s in steps if s["state"] == "done"]
    undone = [s for s in steps if s["state"] == "undone"]
    first = last = None
    if op in ("undo", "all"):
        if not done:
            raise Denied(409, tr(UNDO_NOTHING))
        if op == "all" and undone:
            c.execute(f"DELETE FROM obj_undo WHERE id IN ({','.join('?' * len(undone))})", [s["id"] for s in undone])
        for st in reversed(done if op == "all" else done[-1:]):
            a, z = _undo_one(c, sc, c.execute("SELECT * FROM obj_undo WHERE id=?", (st["id"],)).fetchone(), uid, reg, fix)
            first, last = first or a, z
    else:
        if not undone:
            raise Denied(409, tr(UNDO_NOTHING))
        for st in undone if op == "redoall" else undone[:1]:
            a, z = _redo_one(c, sc, c.execute("SELECT * FROM obj_undo WHERE id=?", (st["id"],)).fetchone(), uid, reg, fix)
            first, last = first or a, z
    t = sc[0][0]
    b0, a0 = (first.get(t) or [{}])[0], (last.get(t) or [{}])[0]
    keys = reg["fields"] if reg["fields"] is not None else [k for k in {**b0, **a0} if k not in UNDO_FIXED and k not in UNDO_NO_FP]
    diff = [k for k in keys if not _same(b0.get(k), a0.get(k))]
    obj_history_add(c, uid, kind, rid, {k: b0.get(k) for k in diff}, {k: a0.get(k) for k in diff}, action="undo" if op in ("undo", "all") else "redo",
                    org_id=oid, agent=False)
    bump(c, _area(reg))
    left = c.execute("SELECT state, COUNT(*) FROM obj_undo WHERE user_id=? AND sess=? AND kind=? AND ref_id=? GROUP BY state",
                     (uid, tok, kind, int(rid))).fetchall()
    return {r[0]: r[1] for r in left}


def obj_cols_ok(c, kind):
    """The kind's table has the core's columns (OBJ_COLS) and its fields -- for a start-up check or a test."""
    reg = obj_reg(kind)
    cols = table_columns(c, reg["table"])
    return [k for k in (*OBJ_COLS, *reg["fields"]) if k not in cols]
