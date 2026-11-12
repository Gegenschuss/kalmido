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
2.747.0 (#5249): every write of a person records its step (not only with the header) as a part of the request's step group
per account (core/undogroups.py, kept UNDO_KEEP_D days); core/undoweb.py lists the groups and takes them back (GET /api/undo).
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
from contextlib import contextmanager  # 2.809.0 (#5365): obj_purge_after
from contextvars import ContextVar
from datetime import timedelta

from flask import g, has_request_context, request

from .access import Denied, acx_of, acx_org_ok, live_sql, need_feat, trash_sql  # 2.773.0 (#5292): live_sql, trash_sql
from .conflict import VersionRequired, ccf_check
from .db import bump, insert_id, iso, iso_ms, now_utc
from .undogroups import UG_LABEL, UG_LABEL_PLAIN, UNDO_KEEP_D, UG_TRACKED, ug_added, ug_current, ug_fits, ug_gc, ug_gids  # 2.747.0 (#5249)
from .errors import BadInput, UnknownFields
from .i18n import N_, tr
from .objhooks import OBJ  # 2.773.0 (#5292): obj_trash_tick
from .objparts import PART_KINDS, part_trash_due, part_trash_purge  # 2.783.0 (#5368): the side objects' trash run
from .objects import OBJ_COLS, obj_need, obj_node_follow, obj_public, obj_reg, obj_row, obj_title, obj_forget
from .objects import obj_reg_node  # 2.754.0 (#5268): the write paths refuse a light kind
from .pg import qi, system_ctx, table_columns, ts_canon, write_lock  # 2.755.0 (#5296): qi; 2.760.0 (#5311): ts_canon
from .retention import ret_due, ret_on, ret_report, ret_trash_cut  # 2.773.0 (#5292): the trash's retention run
from ..collab.comments import user_names
from .serializers import unlink_files  # 2.809.0 (#5365): obj_trash_tick, after the commit
from ..accounts.orgroles import need_org_write, org_role_key
from ..accounts.orgout import org_out  # 2.579.0 (#4802): obj_space_set
from ..files.fsref import fs_ref_drop, fs_ref_rename
from ..files.store import _free_name, fs_purge_files  # 2.783.0 (#5368): fs_purge_files

OBJ_MERGE_MIN = 10  # changes of one person to one object within this many minutes are one history entry (wiki/wkhist.py)
OBJ_HISTORY_MAX = 200  # entries kept per object (the oldest go)
META_KEYS = ("expect_updated_at",)
UNDO_HDR = "X-Kalmido-Undo"  # the same header as office/undo.py (static/js/office_undo.js, static/js/objsave.js)
UNDO_OPS = ("undo", "redo", "all", "redoall")
UNDO_KEEP_H = 24 * UNDO_KEEP_D  # 2.747.0 (#5249): 30 days (was 24 hours), the steps are listed per account now (core/undogroups.py)
UNDO_MAX_STEPS = 60
UNDO_FIXED = {"id", "org_id", "owner_id", "kind", "created_at", "created_by", "rev", "updated_at", "updated_by", "deleted_at", "deleted_by"}
UNDO_NO_FP = {"updated_at", "rev", "updated_by"}
NEED_VERSION = N_("Send expect_updated_at (the updated_at you read): agents change an object only with its version")
UNDO_CONFLICT = N_("Changed by someone else in the meantime, so it cannot be undone")
UNDO_MOVED = N_("Moved to another workspace in the meantime, so it cannot be undone")
UNDO_REKEYED = N_("The organisation's key was changed since then, so it cannot be undone")  # 2.747.0 (#5249, review F1)
UNDO_SPACE_REKEYED = N_("The key of its space was changed since then, so it cannot be undone")  # 2.985.0 (#5394): obj_track undo_spaces
UNDO_NOTHING = N_("Nothing to undo")
PURGE_FIRST = N_("Put it into the trash first")
UG_TRASHED = N_("Moved to the trash: {0}")  # 2.773.0 (#5292): the label of a trash step (core/undogroups.py)
UG_RESTORED = N_("Restored from the trash: {0}")
JOIN_ADMIN = N_("Only admins of the organisation can share this with everyone of it")  # 2.579.0 (#4802)
# 2.657.0 (#4828): a kind with org_join "admin" (a saved view) is always made private; sharing is a step of its own
CREATE_PRIVATE = N_("This is created in your own space first; an admin of the organisation shares it with everyone afterwards")
MOVE_OWNER = N_("Its owner is not a member of that organisation")
MOVE_SHARED = N_("It is shared with people or agents: remove those shares first")
OBJ_TRACK = {}  # 2.567.0 (#4711): kind -> {table, area, undo_scope, undo_keep, undo_nofp, fields: None} (obj_track)


def obj_track(kind, table, *, area="other", undo_scope=None, undo_keep=None, undo_nofp=None, undo_label=None, undo_free=None,
              undo_spaces=None, hist_skip=None):
    """2.567.0 (#4711): an old area's kind for the history and the undo only (module docstring). undo_keep / undo_nofp:
    {table: {column}} never written back on undo / never part of the fingerprint (a number drawn since, cached sums).
    2.747.0 (#5252): undo_label(main row as stored) -> (i18n key, [values]) = the label of its step group (obj_undo_pre).
    2.777.0 (#5254): undo_free = columns of UNDO_FIXED the undo writes back on the MAIN row all the same (deleted_at,
    deleted_by: a step "into the trash" goes back; the area's fix then does what its own restore / trash does besides).
    2.985.0 (#5394): undo_spaces(c, snap) -> [space ids] whose keys sealed the copy about to be written back (core/orgcrypt.py:
    an organisation > 0, an account < 0); a rotation of one since the step (or one running) refuses it like the
    organisation's own (_undo_rekeyed). The function itself raises Denied(409) when the copy's space is not the one its rows
    belong to now (a list moved into another space, its encryption switched) -- life/budundo.py.
    2.985.0 (#5394, review F2): hist_skip = main-row columns never written into obj_history by an undo / redo (obj_undo_hist:
    the sealed columns of a budget entry -- a plain copy there would outlive the encryption)."""
    UG_TRACKED[kind] = table  # 2.747.0 (#5249, review F2): undogroups.py ug_drop_orphans
    OBJ_TRACK[kind] = {"kind": kind, "table": table, "area": area, "undo_scope": undo_scope, "fields": None,
                       "undo_keep": dict(undo_keep or {}), "undo_nofp": dict(undo_nofp or {}), "undo_label": undo_label,
                       "undo_free": frozenset(undo_free or ()), "undo_spaces": undo_spaces,
                       "hist_skip": frozenset(hist_skip or ())}
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
    reg = obj_reg_node(kind)  # 2.754.0 (#5268): not a light kind
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
        if kind in OBJ_TRACK:  # 2.777.0 (#5254): a tracked table without a workspace column (habits: always a person's own)
            r = (c.execute(f"SELECT org_id FROM {qi(reg['table'], {reg['table']})} WHERE id=?", (int(rid),)).fetchone()
                 if "org_id" in (table_columns(c, reg["table"]) or ()) else None)
        else:
            r = obj_row(c, kind, rid)
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
    reg = obj_reg_node(kind)  # 2.754.0 (#5268)
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
        if reg.get("org_join") == "admin":  # 2.657.0 (#4828): made private, shared only through obj_space_set (/share)
            raise Denied(403, tr(CREATE_PRIVATE))
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
    reg = obj_reg_node(kind)  # 2.754.0 (#5268)
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
    reg = obj_reg_node(kind)  # 2.754.0 (#5268)
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
    # 2.657.0 (#4828): the shares of its node (2.924.0, #5069: the old member tables are gone) are checked BEFORE org_out writes its log / News
    with system_ctx(c):  # structure: whether its node (in the tree it leaves) carries a share
        shared = c.execute("SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind=? AND n.ref_id=? "
                           "LIMIT 1", (kind, int(rid))).fetchone()
    if shared:
        raise Denied(409, tr(MOVE_SHARED))
    if old is not None:
        org_out(c, old, org_id, kind, obj_title(c, kind, rid) or tr(reg["label"]), uid=uid)  # 403 for anybody but its admin
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


def _kids(reg):
    """2.773.0 (#5292): the object's child tables ((table, key column), ...; obj_register children)."""
    return reg.get("children") or ()


def _kids_trash(c, reg, rid, ts):
    """Its live children into the trash with the object's time (one already in the trash keeps its own: it stays there)."""
    for t, col in _kids(reg):
        c.execute(f"UPDATE {qi(t, (t,))} SET deleted_at=? WHERE {qi(col, (col,))}=? AND {live_sql()}", (ts, int(rid)))


def _kids_restore(c, reg, rid, gone):
    """The children that went with it (the same time, compared canonically: TEXT or TIMESTAMPTZ) come back; not the others."""
    for t, col in _kids(reg):
        back = [r[0] for r in c.execute(f"SELECT id, deleted_at FROM {qi(t, (t,))} WHERE {qi(col, (col,))}=? AND {trash_sql()}",
                                        (int(rid),)).fetchall() if ts_canon(r[1]) == gone]
        if back:
            c.execute(f"UPDATE {qi(t, (t,))} SET deleted_at=NULL WHERE id = ANY(CAST(? AS BIGINT[]))", (back,))


OBJ_PURGE = {}  # 2.809.0 (#5365): kind -> f(c, rid) of obj_on_purge
_PURGE_BOX = ContextVar("obj_purge_box", default=None)


def obj_on_purge(kind, f):
    """2.809.0 (#5365): the area's part of the delete for good of an object of kind (_purge_rows runs it first): f(c, rid) cleans
    what the core does not know (stored files, scan / text rows, folder nodes) and returns what must happen after the commit
    (paths relative to ATT_DIR or callables, core/serializers.py unlink_files) or None; Denied = the object is kept (a receipt
    under the legal retention, files/store.py fs_on_delete): obj_purge refuses, the retention run counts it as locked."""
    OBJ_PURGE[kind] = f


@contextmanager
def obj_purge_after(keep_locked=False):
    """2.809.0 (#5365): collects the after-commit work of the purges within ({"after": [...], "locked": n}); the caller commits
    and then calls unlink_files(box["after"]). keep_locked: a Denied of an area's hook keeps that object (counted) instead of
    refusing (the retention run)."""
    box = {"after": [], "locked": 0, "err": [], "keep": bool(keep_locked)}  # 2.936.0 (#5364, review): err
    tok = _PURGE_BOX.set(box)
    try:
        yield box
    finally:
        _PURGE_BOX.reset(tok)


def _purge_area(c, kind, rid):
    """2.809.0 (#5365): the area's hook of obj_on_purge (in a savepoint: a refusal leaves nothing half done). False = kept."""
    f = OBJ_PURGE.get(kind)
    if f is None:
        return True
    box = _PURGE_BOX.get()
    n0 = len(box["after"]) if box is not None else 0
    try:
        with c.savepoint():
            out = f(c, int(rid))
    except Denied:
        if box is not None:  # 2.993.0 (#5413, fable F2): the savepoint is undone, so is the after-commit work a nested purge of
            del box["after"][n0:]  # the hook queued (a bill file's unlink): its row stays, its file must stay too
        if box is None or not box["keep"]:
            raise
        box["locked"] += 1
        return False
    except Exception as e:  # noqa: BLE001 - 2.936.0 (#5364): in the retention run one object that fails (its savepoint undone)
        # waits for the next run instead of holding every other one back hour after hour; it is no lock -- counted as
        # <kind>_err with its message, and obj_trash_tick raises after its commit so the watchdog reports it (_wd_section)
        if box is not None:
            del box["after"][n0:]  # 2.993.0 (#5413, fable F2): as above
        if box is None or not box["keep"]:
            raise
        print("obj purge:", kind, int(rid), "kept for the next run:", type(e).__name__, str(e)[:200], flush=True)
        box["err"].append(f"{kind} {int(rid)}: {type(e).__name__}")
        return False
    if out and box is not None:
        box["after"] += list(out)
    elif out:  # without a box nobody unlinks after the commit: the orphan sweep (files/fsmove.py, admin/dataretention.py) does
        print("obj purge: after-commit work without obj_purge_after", kind, flush=True)
    return True


def _purge_kinds(kind, reg):
    """2.1002.0 (#5695): the kinds whose history / undo rows belong to an object of kind: itself and every kind of obj_track on
    the same table (an office row is tracked for its saves as e.g. office_meal, but trashed and purged as omeal -- its
    obj_history / obj_undo rows outlived the delete for good)."""
    return [kind] + sorted(k for k, t in OBJ_TRACK.items() if k != kind and t["table"] == reg["table"])


def _purge_rows(c, kind, reg, rid):
    """THE delete for good of one object of the trash (obj_purge after its rights check, obj_trash_prune for the retention run):
    its reference node, history, undo steps, revoked shares and children go with it. 2.809.0 (#5365): the area's hook first
    (obj_on_purge); one that keeps the object (legal retention) leaves it in the trash."""
    # 2.1015.0 (#5675, review): the row first, its history after - the order of every writer and of okern.ofk_purge_many
    # (row locks, then the history); history first here waited the other way round and made a deadlock with a mass purge
    c.execute(f"SELECT 1 FROM {qi(reg['table'], (reg['table'],))} WHERE id=? FOR UPDATE", (int(rid),)).fetchall()
    if not _purge_area(c, kind, rid):
        return
    fs_ref_drop(c, kind, rid)
    kinds = _purge_kinds(kind, reg)  # 2.1002.0 (#5695): + the tracked kinds of its table (an office row's history / undo)
    gids = ug_gids(c, "kind = ANY(CAST(? AS TEXT[])) AND ref_id=?", (kinds, int(rid)))  # 2.747.0 (#5249): its undo rows' groups
    for t in ("obj_history", "obj_undo", "obj_revoked"):
        c.execute(f"DELETE FROM {qi(t, (t,))} WHERE kind = ANY(CAST(? AS TEXT[])) AND ref_id=?", (kinds, int(rid)))
    ug_gc(c, gids)
    for t, col in _kids(reg):  # 2.773.0 (#5292)
        c.execute(f"DELETE FROM {qi(t, (t,))} WHERE {qi(col, (col,))}=?", (int(rid),))
    c.execute(f"DELETE FROM {qi(reg['table'], (reg['table'],))} WHERE id=?", (int(rid),))


def _trash_step(c, uid, kind, rid, oid, op):
    """2.773.0 (#5292): a trash / restore of a person is a part of the request's step group (core/undogroups.py) without a copy
    (mode = op): taking it back is the opposite way of the core (core/undoweb.py _trash_part: obj_restore / obj_trash), so the
    node, the children and the rights go as they do there. Agents and writes outside a request record nothing."""
    if not has_request_context() or obj_is_agent(c, uid):
        return
    reg = _reg(kind)
    grp = ug_current(c, uid, _area(reg), oid, (UG_TRASHED if op == "trash" else UG_RESTORED, [[reg["label"]]]))
    if grp is None or not ug_fits(c, grp, 0):
        return
    insert_id(c, "INSERT INTO obj_undo(org_id, user_id, sess, kind, ref_id, seq, state, snap, fp_before, fp_after, created_at, "
                 "group_id, mode, bytes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (oid, uid, "", kind, int(rid), 1, "done", "{}", "", "", iso(now_utc()), grp["id"], op, 0))
    ug_added(c, grp, 0)


def obj_trash_step(c, uid, kind, rid, oid, op):
    """2.985.0 (#5394): the trash / restore step of an area that puts a core kind into its trash its own way (an address book:
    contacts/web.py bk_trash); taken back through the area's own way (core/undoweb.py undo_trash_reg). op trash | restore."""
    _trash_step(c, uid, kind, rid, oid, op)


def obj_trash(c, uid, kind, rid, step=True):
    """Into the trash (deleted_at): restorable by who manages it (obj_restore). 2.773.0 (#5292): THE trash of the core -- its
    children go with it (obj_register children) and the step can be taken back (step=False: the undo itself)."""
    reg = obj_reg_node(kind)  # 2.754.0 (#5268): a light kind has no write path of the core
    row, _ = obj_need(c, uid, kind, rid, _trash_need(reg))
    write_lock(c, f"obj-{kind}-{int(rid)}")
    ts = _now()
    n = c.execute(f"UPDATE {qi(reg['table'], (reg['table'],))} SET deleted_at=?, deleted_by=?, rev=rev+1, updated_at=?, updated_by=? WHERE id=? AND {live_sql()}",
                  (ts, uid, ts, uid, int(rid))).rowcount
    if not n:
        return obj_row(c, kind, rid)  # someone else was quicker (the lock waited): it is in the trash already
    _kids_trash(c, reg, rid, ts)
    # review F7: its reference node goes into the file store's trash with it (the folders hide it as any node there)
    c.execute(f"UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE kind='ref' AND ref_kind=? AND ref_id=? AND {live_sql()}",
              (ts, uid, kind, int(rid)))
    obj_history_add(c, uid, kind, rid, {}, {}, action="trash")
    if step:
        _trash_step(c, uid, kind, rid, row["org_id"] or None, "trash")
    obj_forget()
    bump(c, _area(reg))
    return obj_row(c, kind, rid)


OBJ_BACK = {}  # 2.1002.0 (#5491): kind -> f(c, uid, rid, row) of obj_on_restore


def obj_on_restore(kind, f):
    """2.1002.0 (#5491): the area's part of a restore from the core's trash (obj_restore runs it after the core put the row
    back): f(c, uid, rid, row) with the row as it was in the trash (its deleted_at as stored) -- what the core does not know
    (tasks: the subtasks that went with it, a parent still in the trash, the section, the area's log and undo step)."""
    OBJ_BACK[kind] = f


def obj_restore(c, uid, kind, rid, step=True, undo=False, checked=False):
    """Out of the trash ('manage'), with the children that went with it. step=False: no step of its own. 2.778.0 (#5371):
    undo=True is the person's own trash step taken back (core/undoweb.py _trash_part): the role of putting it in
    (_trash_need), so who may trash it may take that back -- only while it is still the trash uid put it in (deleted_by);
    the trash's own restore stays at 'manage'.
    2.1002.0 (#5491): checked=True = the area checked the rights itself (its route's own rule, or its inner restore without a
    person, uid may be None): no check of the core; an object not in the trash is left as it is (returns its row; unchecked:
    one gone or restored meanwhile under the lock is Denied 404, as obj_need answers). A light kind
    (node=False: tasks) is restored only so (Denied 404 otherwise), without node, children, history or undo step of the core
    (its area keeps its own log). The area's hook obj_on_restore runs after the row is back; with checked the caller bumps."""
    reg = obj_reg(kind) if checked else obj_reg_node(kind)  # 2.754.0 (#5268); 2.1002.0 (#5491): a light kind only checked
    light = not reg.get("node", True)
    if not checked:  # (an area's inner restore holds its own lock / runs in its own transaction, as before)
        obj_need(c, uid, kind, rid, _trash_need(reg) if undo else "manage", trash=True, own_trash=undo)
        write_lock(c, f"obj-{kind}-{int(rid)}")
    row = obj_row(c, kind, rid)  # 2.1002.0 (#5491, review F3 of 2.851): read again under the lock (deleted_at of now)
    if row is None or not row["deleted_at"]:  # gone or restored meanwhile: as obj_need would answer now
        if checked:
            return row
        raise Denied(404)
    # 2.760.0 (#5311): the node's deleted_at is TEXT, the object's may be TIMESTAMPTZ (read canonically, pg.py ts_canon):
    # compare both canonically, not as text (a TIMESTAMPTZ table's restore left its node in the trash)
    gone = ts_canon(row["deleted_at"])
    ts = _now()  # 2.1002.0 (#5491, review): the row first - its node and children come back only when the row did
    # 2.1002.0 (#5491): only a row still in the trash -- a second restore at the same time (or the retention run that deleted
    # it meanwhile) changes nothing and runs no hook, no history
    if not c.execute(f"UPDATE {qi(reg['table'], (reg['table'],))} SET deleted_at=NULL, deleted_by=NULL, rev=rev+1, updated_at=?, "
                     "updated_by=? WHERE id=? AND deleted_at IS NOT NULL", (ts, uid, int(rid))).rowcount:
        obj_forget()
        if not checked:
            raise Denied(404)
        return obj_row(c, kind, rid)
    if not light:
        n = next((x for x in c.execute(f"SELECT * FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=? AND {trash_sql()}",
                                       (kind, int(rid))).fetchall() if ts_canon(x["deleted_at"]) == gone), None)
        if n is not None:  # review F7: the node obj_trash put into the trash comes back (not one the file store's own trash holds)
            nm = _free_name(c, n["parent_id"], n["owner_id"], n["org_id"], n["name"], skip=n["id"])
            c.execute("UPDATE fs_nodes SET deleted_at=NULL, deleted_by=NULL, name=? WHERE id=?", (nm, n["id"]))
        _kids_restore(c, reg, rid, gone)  # 2.773.0 (#5292)
    if not light:
        obj_history_add(c, uid, kind, rid, {}, {}, action="restore")
        if step:
            _trash_step(c, uid, kind, rid, row["org_id"] or None, "restore")
    if kind in OBJ_BACK:  # 2.1002.0 (#5491)
        OBJ_BACK[kind](c, uid, int(rid), row)
    obj_forget()
    if not checked:  # 2.1002.0 (#5491): an area's inner restore (checked) leaves the bump to its caller, as before
        bump(c, _area(reg))
    return obj_row(c, kind, rid)


def obj_purge(c, uid, kind, rid):
    """Delete for good: only an object in the trash ('manage'; 409 otherwise). Its node, history, undo steps, revoked
    shares and children go with it (_purge_rows)."""
    reg = obj_reg_node(kind)  # 2.754.0 (#5268)
    row = obj_row(c, kind, rid)
    if row is not None and not row["deleted_at"]:
        obj_need(c, uid, kind, rid, "manage")
        raise Denied(409, tr(PURGE_FIRST))
    obj_need(c, uid, kind, rid, "manage", trash=True)
    write_lock(c, f"obj-{kind}-{int(rid)}")
    _purge_rows(c, kind, reg, rid)
    obj_forget()
    bump(c, _area(reg))


OBJ_PRUNE_BATCH = 500  # 2.809.0 (#5365, review): at most so many objects per kind and run (one lock each); the rest next hour


def _reg_trash(kind):
    """2.936.0 (#5364): the registration of a core kind for the retention run -- a kind with a node, or a light kind with
    trash_prune (its area's obj_on_purge hook deletes it: tasks); Denied(404) for any other light kind."""
    reg = obj_reg(kind)
    if not reg.get("node", True) and not reg.get("trash_prune"):
        raise Denied(404)  # 2.754.0 (#5268): a light kind has no trash of the core
    return reg


def _keep(reg, a):
    """2.936.0 (#5364): (' AND NOT (...)', args) of the kind's objects the retention run leaves (trash_keep), else ('', ())."""
    if reg.get("trash_keep") is None:
        return "", ()
    sql, args = reg["trash_keep"](a)
    return f" AND NOT ({sql})", tuple(args)


def obj_trash_due(c, kind, cut=None, limit=None):
    """2.773.0 (#5292): the ids of the kind's objects in the trash longer than the trash period (core/retention.py ret_trash_cut).
    2.783.0 (#5368): a side object of core/objparts.py (part_kind trash_prune=True) the same way.
    2.809.0 (#5365, review): limit = at most so many (the oldest ids first; core kinds only).
    2.936.0 (#5364): without the ones its trash_keep leaves (kept by law)."""
    if kind in PART_KINDS and kind not in OBJ:
        with system_ctx(c):
            return part_trash_due(c, kind, cut or ret_trash_cut())
    reg = _reg_trash(kind)
    t = reg["table"]
    kq, ka = _keep(reg, qi(t, (t,)))
    with system_ctx(c):  # the retention run reads every workspace's trash (ids only, no content)
        lim = f" LIMIT {int(limit)}" if limit else ""
        return [r[0] for r in c.execute(f"SELECT id FROM {qi(t, (t,))} WHERE {trash_sql()} AND deleted_at<?{kq} ORDER BY id{lim}",
                                        (cut or ret_trash_cut(), *ka)).fetchall()]


def obj_trash_kept(c, kind, cut=None):
    """2.936.0 (#5364): how many of the kind's objects past the trash period its trash_keep leaves (kept by law); 0 without."""
    reg = _reg_trash(kind)
    if reg.get("trash_keep") is None:
        return 0
    t = reg["table"]
    sql, args = reg["trash_keep"](qi(t, (t,)))
    with system_ctx(c):  # the retention run counts every workspace's kept trash (a number only, no content)
        return c.execute(f"SELECT COUNT(*) FROM {qi(t, (t,))} WHERE {trash_sql()} AND deleted_at<? AND ({sql})",
                         (cut or ret_trash_cut(), *args)).fetchone()[0]


def obj_trash_prune(c, kind, cut=None, purge=None, ids=None, paths=None):
    """2.773.0 (#5292): THE retention run of a core kind -- its objects in the trash longer than the trash period are deleted
    for good the same way as obj_purge (_purge_rows), with the switch of every run (ret_on("trash"); off = count only) and its
    report (ret_report run obj_<kind>). ids: read already by the caller. Returns their number; the caller commits.
    2.783.0 (#5368): a side object kind (core/objparts.py part_kind trash_prune=True: webhooks, chat messages, member memos,
    the copies of list_part_trash) goes through part_trash_purge; the files it names land in paths (the caller unlinks them
    after its commit: files/store.py fs_purge_files).
    2.936.0 (#5364): the kind's trash_keep (kept by law) stays, also when checked again under the lock; trash_batch per kind;
    when deleting, the number is the objects deleted (also one that went with another of the run, e.g. a subtask with its
    parent), not the ones restored or kept meanwhile."""
    purge = ret_on("trash") if purge is None else bool(purge)
    if kind in PART_KINDS and kind not in OBJ:
        old = obj_trash_due(c, kind, cut) if ids is None else [int(x) for x in ids]
        if old and purge:
            with system_ctx(c):  # no person: the period ran out (the area checked the rights when it went into the trash)
                got = part_trash_purge(c, kind, old)
            if paths is not None:
                paths += got
        return len(old)
    reg = _reg_trash(kind)  # 2.936.0 (#5364): a light kind with trash_prune too (tasks)
    # 2.809.0 (#5365, review): a batch per run - every file-store node runs here now, and thousands of advisory locks in one
    # transaction would break the whole tick (max_locks_per_transaction) hour after hour
    old = obj_trash_due(c, kind, cut, limit=reg.get("trash_batch") or OBJ_PRUNE_BATCH) if ids is None else [int(x) for x in ids]
    if old and purge:
        t, cut = reg["table"], cut or ret_trash_cut()
        kq, ka = _keep(reg, qi(t, (t,)))
        n = 0
        with system_ctx(c):  # no person: the period ran out (the rights were checked when it went into the trash)
            for rid in old:
                write_lock(c, f"obj-{kind}-{int(rid)}")
                # 2.784.0 (#5366 review): checked again under the lock - a restore (e.g. via /api/undo) between reading the
                # ids and the lock keeps its row alive instead of losing it for good
                if not c.execute(f"SELECT 1 FROM {qi(t, (t,))} WHERE id=? AND {trash_sql()} AND deleted_at<?{kq}",
                                 (int(rid), cut, *ka)).fetchone():
                    # 2.936.0 (#5364): gone = it went with another one of this run (a subtask with its parent): counted
                    if not c.execute(f"SELECT 1 FROM {qi(t, (t,))} WHERE id=?", (int(rid),)).fetchone():
                        n += 1
                    continue
                _purge_rows(c, kind, reg, rid)
                n += 1
        obj_forget()
        bump(c, _area(reg))
        return n
    return len(old)


def obj_trash_tick(c, force=False):
    """2.773.0 (#5292): the watchdog's hourly run over the kinds registered with trash_prune=True (the others keep their
    area's run until their stage moves them onto the core). 2.936.0 (#5364): + <kind>_kept (trash_keep, kept by law); tasks
    and projects run here too (the runs ttp_tick / otr_prune went)."""
    if not ret_due("obj_trash", force=force):
        return {}
    purge, cut, out = ret_on("trash"), ret_trash_cut(), {}
    paths = []
    with obj_purge_after(keep_locked=True) as box:  # 2.809.0 (#5365): the areas' stored files after the commit, receipts locked
        for kind, reg in sorted(OBJ.items()):
            if reg.get("trash_prune"):
                n0, a0, e0 = box["locked"], len(box["after"]), len(box["err"])
                try:  # 2.936.0 (#5364, review): one savepoint per kind -- a kind that fails holds back no other one
                    with c.savepoint():
                        n = obj_trash_prune(c, kind, cut, purge)
                except Exception as e:  # noqa: BLE001 - this kind waits for the next run, the watchdog hears of it below
                    del box["after"][a0:]  # its rows stay, so do their files
                    box["locked"] = n0
                    del box["err"][e0:]
                    box["err"].append(f"{kind}: {type(e).__name__}")
                    print("core trash:", kind, type(e).__name__, str(e)[:200], flush=True)
                    out[kind + "_err"] = 1
                    continue
                er = len(box["err"]) - e0
                if er:
                    out[kind + "_err"] = er
                lk = box["locked"] - n0
                out[kind] = n - lk - er  # 2.809.0 (#5365, review): a locked receipt counts as locked, not as deleted (2.936.0: nor an error)
                if lk:
                    out[kind + "_locked"] = lk
                if reg.get("trash_keep") is not None:  # 2.936.0 (#5364)
                    out[kind + "_kept"] = obj_trash_kept(c, kind, cut)
        for kind, k in sorted(PART_KINDS.items()):  # 2.783.0 (#5368): the side objects (core/objparts.py), one savepoint each
            if k["trash_prune"] and kind not in OBJ:
                got = []
                try:
                    with c.savepoint():
                        n = obj_trash_prune(c, kind, cut, purge, paths=got)
                    if n:  # only the side object kinds with something due (the report keeps the numbers only anyway)
                        out[kind] = n
                except Exception as e:  # noqa: BLE001 - like files/trashpurge.py: this kind waits for the next run
                    print("core trash:", kind, type(e).__name__, flush=True)
                    out[kind + "_err"] = 1
                    continue
                paths += got
    if out:
        ret_report(c, "trash", out, purge, run="obj_trash")
    c.commit()
    unlink_files(box["after"])  # 2.809.0 (#5365): after the commit (a failed commit keeps the rows and their files)
    if paths:  # after the commit: a failed commit keeps the rows and their files
        fs_purge_files([], paths)
    if box["err"]:  # 2.936.0 (#5364, review): after the commit -- the watchdog (notify/push.py _wd_section) reports it
        raise RuntimeError("core trash run: " + "; ".join(box["err"][:10]))
    return out


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


UNDO_SKIP = {}  # 2.872.0 (#5532): table -> {column}: never copied into an undo step (undo_skip)


def undo_skip(table, *cols):
    """2.872.0 (#5532): columns of table that no undo copy holds (a picture of megabytes would make every step of the object
    too big for its step group, core/undogroups.py ug_fits): they are not in the copy, not in its fingerprint, and taking a
    step back leaves them as they are now (the area records no step for a change of such a column alone)."""
    UNDO_SKIP.setdefault(table, set()).update(cols)


def _snap(c, sc):
    out = {}
    for t, where, args, _many in sc:
        rows = c.execute(f"SELECT * FROM {t} WHERE {where} ORDER BY id", args).fetchall()
        skip = UNDO_SKIP.get(t, ())
        out[t] = [{k: _val(r[k]) for k in r.keys() if k not in skip} for r in rows]
    return out


def _fp(snap, nofp=None, rows=True):
    nofp = nofp or {}

    def skip(t, r):  # 2.884.0 (#5479): an entry with of_row(row) names the columns left out per row (sheets/shhist.py _NotOwn)
        x = nofp.get(t, ())
        return x.of_row(r) if rows and hasattr(x, "of_row") else x
    s = {}
    for t, rows in snap.items():
        s[t] = []
        for r in rows:
            sk = skip(t, r)
            s[t].append({k: v for k, v in r.items() if k not in UNDO_NO_FP and k not in sk})
    return hashlib.sha256(json.dumps(s, sort_keys=True, default=str).encode()).hexdigest()


def _fp_is(snap, nofp, want):
    """2.884.0 (#5479, review F8): snap still has the fingerprint want -- also the one without the per-row columns (of_row) a
    step written before 2.884.0 noted."""
    if not want:
        return False
    if _fp(snap, nofp) == want:
        return True
    return any(hasattr(x, "of_row") for x in (nofp or {}).values()) and _fp(snap, nofp, rows=False) == want


def _lock_rows(c, sc):
    t, where, args, _many = sc[0]
    c.execute(f"SELECT id FROM {t} WHERE {where} FOR UPDATE", args).fetchall()


def _write_back(c, sc, snap, uid, keep=None, free=()):
    """Copy snap back: the main row's own columns (not its identity, version, trash), the other tables' rows replaced.
    keep {table: {column}}: columns that stay as they are now (obj_track undo_keep). 2.777.0 (#5254): free = columns of
    UNDO_FIXED written back on the main row all the same (obj_track undo_free: its trash state)."""
    keep = keep or {}
    # 2.755.0 (#5296): the table and column names only from the schema (qi): the snapshot's keys are data read back
    cols_of = {t: table_columns(c, t) for t, _w, _a, _m in sc}
    tabs = {t for t, cols in cols_of.items() if cols}
    for t, where, args, many in reversed(sc):
        if many:
            c.execute(f"DELETE FROM {qi(t, tabs)} WHERE {where}", args)
    for i, (t, where, args, many) in enumerate(sc):
        cols = cols_of[t]
        rows = snap.get(t) or []
        if not many:
            if not rows:
                continue
            row = {k: _unval(v) for k, v in rows[0].items() if k in cols and (k not in UNDO_FIXED or (i == 0 and k in free))
                   and k not in keep.get(t, ())}
            if i == 0 and {"rev", "updated_at", "updated_by"} <= cols:
                c.execute(f"UPDATE {qi(t, tabs)} SET {','.join(qi(k, cols) + '=?' for k in row)}{',' if row else ''} "
                          f"rev=rev+1, updated_at=?, updated_by=? WHERE {where}", [*row.values(), _now(), uid, *args])
            elif i == 0 and "updated_at" in cols:  # 2.567.0 (#4711): an old area's row (obj_track): a new version for the next save
                row.update(updated_at=_now(), **({"updated_by": uid} if "updated_by" in cols else {}))
                c.execute(f"UPDATE {qi(t, tabs)} SET {','.join(qi(k, cols) + '=?' for k in row)} WHERE {where}",
                          [*row.values(), *args])
            elif row:
                c.execute(f"UPDATE {qi(t, tabs)} SET {','.join(qi(k, cols) + '=?' for k in row)} WHERE {where}",
                          [*row.values(), *args])
            continue
        for r in rows:
            row = {k: _unval(v) for k, v in r.items() if k in cols}
            c.execute(f"INSERT INTO {qi(t, tabs)}({','.join(qi(k, cols) for k in row)}) VALUES({','.join('?' * len(row))})",
                      list(row.values()))


def _token():
    import re
    if not has_request_context():
        return ""
    tok = (request.headers.get(UNDO_HDR) or "").strip().lower()
    return tok if re.fullmatch(r"[a-f0-9]{16,64}", tok) else ""


def obj_undo_pre(c, uid, kind, rid, oid=None):
    """Before a write changes the object: the state before = one step. 2.747.0 (#5249): of every write of a person in a
    request, as a part of the request's step group (core/undogroups.py); with the header X-Kalmido-Undo also a step of that
    editor session (the same row). Agents and writes outside a request record nothing."""
    if not has_request_context() or obj_is_agent(c, uid):
        return
    tok = _token()
    sc = undo_scope(kind, rid, oid)
    _lock_rows(c, sc)
    snap = _snap(c, sc)
    main = (snap.get(sc[0][0]) or [None])[0]
    if not main:
        return
    js = json.dumps(snap, ensure_ascii=False, default=str)
    n = len(js.encode())
    reg = _reg(kind)
    label = (UG_LABEL, [[reg["label"]]]) if reg.get("label") else (UG_LABEL_PLAIN, [])
    if callable(reg.get("undo_label")):  # 2.747.0 (#5252): a tracked kind names its object (office/oubar.py)
        label = reg["undo_label"](main) or label
    grp = ug_current(c, uid, _area(reg), main.get("org_id"), label, obj=(kind, int(rid)))  # 2.985.0 (#5394, review F6)
    gid = grp["id"] if grp is not None and ug_fits(c, grp, n) else None
    if not tok and gid is None:
        return  # a group too big for copies: listed, nothing to keep
    seq = 1
    if tok:
        key = (uid, tok, kind, int(rid))
        gone = ug_gids(c, "user_id=? AND sess=? AND kind=? AND ref_id=? AND state<>'done'", key)
        c.execute("DELETE FROM obj_undo WHERE user_id=? AND sess=? AND kind=? AND ref_id=? AND state<>'done'", key)  # a new step ends the way forward
        rows = c.execute("SELECT id, seq, fp_after, group_id FROM obj_undo WHERE user_id=? AND sess=? AND kind=? AND ref_id=? ORDER BY seq", key).fetchall()
        if not rows:
            c.execute("DELETE FROM obj_undo WHERE created_at<?", (iso(now_utc() - timedelta(hours=UNDO_KEEP_H)),))
        elif len(rows) >= UNDO_MAX_STEPS:
            c.execute("UPDATE obj_undo SET fp_after=? WHERE id=?", (rows[1]["fp_after"], rows[0]["id"]))
            c.execute("DELETE FROM obj_undo WHERE id=?", (rows[1]["id"],))
            gone.append(rows[1]["group_id"])  # 2.747.0 (#5249): its group keeps the other parts (or goes, ug_gc)
        ug_gc(c, gone)
        seq = (rows[-1]["seq"] + 1) if rows else 1
    sid = insert_id(c, "INSERT INTO obj_undo(org_id, user_id, sess, kind, ref_id, seq, state, snap, fp_before, fp_after, created_at, "
                       "group_id, mode, bytes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (main.get("org_id"), uid, tok, kind, int(rid), seq, "done", js, _fp(snap, _nofp(kind)), "", iso(now_utc()),
                     gid, "snap", n))
    if gid is not None:
        ug_added(c, grp, n)
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


def _undo_rekeyed(c, st, reg=None, snap=None):
    """2.747.0 (#5249, review F1): a copy holds the sealed values (kenc1:) as they were; after a key rotation of the
    organisation (or while one runs) the old key is gone or going, so writing the copy back would leave unreadable text.
    A step older than the rotation (or any step during one) is refused with 409, never written back.
    2.985.0 (#5394): + the spaces the kind names for the copy snap (obj_track undo_spaces: a budget row's list space); checked
    before the fingerprint, so the answer names the key change and not "changed by someone else" (a rotation reseals rows)."""
    oid = st["org_id"] if "org_id" in st.keys() else None
    spaces = {int(oid)} if oid else set()
    fn = (reg or {}).get("undo_spaces")
    extra = {int(x) for x in (fn(c, snap or {}) or ()) if x} if callable(fn) else set()
    for sp in sorted(spaces | extra):
        if sp <= 0:
            continue  # an account's key is never rotated (core/orgcrypt.py: only re-wrapped under a new server key)
        with system_ctx(c):  # org_keys is infrastructure (core/orgcrypt.py reads it as "system"); only the two times are read
            k = c.execute("SELECT rot_started_at, rotated_at FROM org_keys WHERE org_id=?", (sp,)).fetchone()
        if k and (k["rot_started_at"] or (k["rotated_at"] and str(st["created_at"] or "") < str(k["rotated_at"]))):
            raise Denied(409, tr(UNDO_REKEYED if sp in spaces else UNDO_SPACE_REKEYED))


def _undo_one(c, sc, st, uid, reg, fix=None):
    nofp = reg.get("undo_nofp") or {}
    cur = _snap(c, sc)
    old = json.loads(st["snap"])
    _undo_rekeyed(c, st, reg, old)  # 2.985.0 (#5394): before the fingerprint (a rotation reseals the rows it compares)
    if not _fp_is(cur, nofp, st["fp_after"]):
        raise Denied(409, tr(UNDO_CONFLICT))
    if _main_org(old, sc) != _main_org(cur, sc):
        raise Denied(409, tr(UNDO_MOVED))
    _write_back(c, sc, old, uid, reg.get("undo_keep"), reg.get("undo_free") or ())
    if fix:
        fix(c)
    c.execute("UPDATE obj_undo SET state='undone', redo=?, fp_undone=? WHERE id=?",
              (json.dumps(cur, ensure_ascii=False, default=str), _fp(_snap(c, sc), nofp), st["id"]))
    return cur, old


def _redo_one(c, sc, st, uid, reg, fix=None):
    nofp = reg.get("undo_nofp") or {}
    cur = _snap(c, sc)
    new = json.loads(st["redo"]) if st["redo"] else None
    _undo_rekeyed(c, st, reg, new)  # 2.985.0 (#5394): the spaces of the copy written forward, before the fingerprint
    if not _fp_is(cur, nofp, st["fp_undone"]) or not new:
        raise Denied(409, tr(UNDO_CONFLICT))
    if _main_org(new, sc) != _main_org(cur, sc):
        raise Denied(409, tr(UNDO_MOVED))
    _write_back(c, sc, new, uid, reg.get("undo_keep"), reg.get("undo_free") or ())
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


def obj_undo_run(c, uid, kind, rid, oid, sess, op="undo", fix=None, keep=None, lock=None):
    """2.567.0 (#4711): obj_undo without its rights check -- the caller checked them (an obj_track kind: the area's own,
    office/undo.py). oid = the object's workspace now; fix(c) runs after each write back (the sums of a document).
    2.577.0 (#3964): keep {table: {column}} = columns that stay as they are now on top of undo_keep (fields uid may not change).
    2.747.0 (#5252, review F3): lock = the write_lock name the kind's own saves take (an office document: office_doc_<id>, the
    one of finalising / numbering / status), so an undo and those serialise (default obj-<kind>-<id>)."""
    tok = _undo_args(sess, op)
    reg = _reg(kind)
    if keep:
        reg = {**reg, "undo_keep": {t: set(reg["undo_keep"].get(t, ())) | set(v) for t, v in {**reg["undo_keep"], **keep}.items()}}
    if obj_is_agent(c, uid):
        raise Denied(403)
    write_lock(c, lock or f"obj-{kind}-{int(rid)}")
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
    obj_undo_hist(c, uid, kind, rid, oid, reg, sc, first, last, "undo" if op in ("undo", "all") else "redo")
    bump(c, _area(reg))
    left = c.execute("SELECT state, COUNT(*) FROM obj_undo WHERE user_id=? AND sess=? AND kind=? AND ref_id=? GROUP BY state",
                     (uid, tok, kind, int(rid))).fetchall()
    return {r[0]: r[1] for r in left}


def obj_undo_hist(c, uid, kind, rid, oid, reg, sc, first, last, action):
    """The history entry of an undo / redo: the main row's fields from first (before it) to last (after it)."""
    t = sc[0][0]
    b0, a0 = (first.get(t) or [{}])[0], (last.get(t) or [{}])[0]
    keys = reg["fields"] if reg["fields"] is not None else [k for k in {**b0, **a0} if k not in UNDO_FIXED and k not in UNDO_NO_FP]
    skip = reg.get("hist_skip") or ()  # 2.985.0 (#5394, review F2): sealed columns stay out of the history
    diff = [k for k in keys if k not in skip and not _same(b0.get(k), a0.get(k))]
    obj_history_add(c, uid, kind, rid, {k: b0.get(k) for k in diff}, {k: a0.get(k) for k in diff}, action=action, org_id=oid, agent=False)


def obj_undo_forget(c, kind, ids):
    """2.985.0 (#5394, review F2): the undo copies (every step of the kind's rows ids, also of an editor session) and the history
    rows of those rows go -- their values are about to be sealed, a plain copy must not outlive that. A group left without
    parts goes (core/undogroups.py ug_gc); one that keeps other parts gets the plain label "Change" (its label could name a
    value of these rows); review F7: so do the toobig groups of the kind's area. Inside the caller's transaction, as the system (a background pass)."""
    ids = sorted({int(x) for x in ids or () if x})
    if not ids:
        return
    with system_ctx(c):  # the undo / history rows of the resealed rows only: nothing is read out
        for at in range(0, len(ids), 500):
            part = ids[at:at + 500]
            q = ",".join("?" * len(part))
            gone = ug_gids(c, f"kind=? AND ref_id IN ({q})", (kind, *part))
            c.execute(f"DELETE FROM obj_undo WHERE kind=? AND ref_id IN ({q})", (kind, *part))
            ug_gc(c, gone)
            if gone:
                c.execute(f"UPDATE undo_groups SET label_key=?, label_args='[]' WHERE id IN ({','.join('?' * len(gone))})",
                          (UG_LABEL_PLAIN, *gone))
            c.execute(f"DELETE FROM obj_history WHERE kind=? AND ref_id IN ({q})", (kind, *part))
        # 2.985.0 (#5394, review F7): a toobig group lost its parts (ug_fits), so ug_gids cannot find it - its label could still
        # name a plain value of these rows: every toobig group of the kind's area gets the plain label (rare, only the label goes)
        area = (OBJ_TRACK.get(kind) or {}).get("area") or ""
        if area and area != "other":
            c.execute("UPDATE undo_groups SET label_key=?, label_args='[]' WHERE area=? AND state='toobig' AND label_args<>'[]'",
                      (UG_LABEL_PLAIN, area))


def obj_cols_ok(c, kind):
    """The kind's table has the core's columns (OBJ_COLS) and its fields -- for a start-up check or a test."""
    reg = obj_reg(kind)
    cols = table_columns(c, reg["table"])
    return [k for k in (*OBJ_COLS, *reg["fields"]) if k not in cols]
