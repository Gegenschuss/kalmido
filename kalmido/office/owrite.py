"""2.567.0 (#4711): the shared core, stage 2 -- ONE write call for an office row (and a client) on the core's write layer.

The office's rows (office_* tables, the clients) have no owner_id / rev and their own rights (office_gate, office_org,
ofr_check and the office groups), so they are no registered kinds of core/objects.py yet (a real registration would open
them to shares and folders). The transition docs/dev/kern.md names: the kinds are tracked for the history and the undo only
(core/writes.py obj_track), and ow_write does for one row in ONE call what obj_write does for a core object:

  write_lock('obj-<kind>-<id>') -> the row again under the lock (FOR UPDATE) -> an AGENT must send expect_updated_at (400
  without, as obj_write) -> the version check (core/conflict.py ccf_check: 409 with the current state under "current",
  OwConflict; 2.576.0 #4794: the routes' old keys row / letter / client went, the dialogs read "current" through objsave.js) -> only the fields sent (the module's own cleaner, partial) -> nothing changed = nothing written ->
  the undo step (header X-Kalmido-Undo, people only: obj_undo_pre / obj_undo_post) -> updated_at (milliseconds, the base of
  the next save), updated_by -> the history (obj_history: before / after of the changed columns AS STORED -- an encrypted
  column stays sealed there, an agent marked) -> bump. The caller commits.

The rights stay the module's own (called before ow_write, unchanged: office_gate, office_org, ofr_check, need_client); no
other route changes here. A route that changes more than the row (a client's contact persons) does it in `extra`, inside
the same undo step.

Interface:
  ow_kind(kind, table, scope=None, keep=None, nofp=None)       track a kind (at import of its module)
  ow_write(c, uid, kind, rid, b, clean, *, where=..., args=..., dec=None, enc=None, public=None,
           version=True, extra=None, force=False) -> (row after (dec'd dict), {column: (before, after)})
  ow_check(b, have, cur)                                        the version check alone (OwConflict)
  ow_crypt(table, office) -> (dec, enc)                         for a table with encrypted columns (core/orgcrypt.py)
  ow_undo_ctx(kind, fn)                                         the session undo of the kind (office/undo.py route)
  ow_history(c, kind, rid, org, limit=50) -> the entries (the caller checked the rights to read the row)
  ow_is_agent(c, uid) -> bool, ow_uid() -> the signed-in account or None
  ow_history_answer(c, kind, rid, org) -> {items}              2.570.0 (#4783): the answer of a history route GET <save path>/history
                                                                (the route runs the rights checks of its save route first; office/rights.py
                                                                ofr_need asks a group for what saving needs)
  ow_need_row(c, table, where, args)                            404 when the row is not there (the where of the save route)"""
import json

from flask import g, has_request_context, jsonify

from ..collab.comments import user_names

from ..core.config import app
from ..core.conflict import Conflict, VersionRequired
from ..core.db import bump, iso_ms, now_utc
from ..core.errors import Denied
from ..core.i18n import tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.pg import table_columns, ts_canon, write_lock  # 2.1095.0 (#5306): ts_canon
from ..core.writes import (NEED_VERSION, OBJ_TRACK, _same, _val, obj_history_add, obj_is_agent, obj_track, obj_undo_post,
                           obj_undo_pre)

class OwConflict(Conflict):
    """409 {"error", "current": the current state} -- as obj_write. 2.576.0 (#4794): the alias key of before (row, letter,
    client) went once every dialog read "current" (objsave.js)."""

    def __init__(self, cur):
        super().__init__("current", cur)


@app.errorhandler(OwConflict)
def ow_conflict_answer(e):
    return jsonify({"error": e.text(), "current": e.cur}), 409


def ow_check(b, have, cur):
    """The version check (core/conflict.py ccf_check, answered with OwConflict): expect_updated_at set and not the row's -> 409."""
    exp = b.get("expect_updated_at") if isinstance(b, dict) else None
    if exp and ts_canon(str(exp)) != ts_canon(have):  # 2.1095.0 (#5306): one moment, whichever text form (TIMESTAMPTZ reads with microseconds)
        raise OwConflict(cur())


OW_UNDO_CTX = {}  # undo kind -> fn(ref) -> (c, uid, oid, after(c) -> the answer): how office/undo.py checks the rights (ow_undo_ctx)


def ow_undo_ctx(kind, fn):
    """A module on ow_write names how an undo of its kind is checked (the rights of its normal change) and answered."""
    OW_UNDO_CTX[kind] = fn
    return fn


_COLS = {}  # table -> its columns (they only grow at start-up: the migrations run before the first request)


def ow_kind(kind, table, scope=None, keep=None, nofp=None, label=None):
    """Track an office kind (core/writes.py obj_track): scope(rid, oid) -> the undo's tables (default: the row).
    2.747.0 (#5252): area "office" (its step groups are listed under the office, an undo from the list reloads it);
    label(main row as stored) -> (key, [values]) names the object in its step group (office/oubar.py)."""
    return obj_track(kind, table, area="office", undo_scope=scope or (lambda rid, oid: [(table, "id=?", (int(rid),), False)]),
                     undo_keep=keep, undo_nofp=nofp, undo_label=label)


def ow_cols(c, table):
    if table not in _COLS:
        _COLS[table] = table_columns(c, table)
    return _COLS[table]


def ow_crypt(table, oid):
    """(dec, enc) of ow_write for a table whose columns the organisation's key seals at rest."""
    return (lambda c, r: oc_dec_fields(c, oid, table, r)), (lambda c, d: oc_enc_fields(c, oid, table, d))


def ow_uid():
    """The signed-in account of the request (None outside one: background work)."""
    u = getattr(g, "user", None) if has_request_context() else None
    return u["id"] if u is not None else None


def ow_is_agent(c, uid):
    return obj_is_agent(c, uid)


def _stored(v):
    return _val(v)


def ow_write(c, uid, kind, rid, b, clean, *, where="id=? AND org_id=?", args=None, oid=None, dec=None, enc=None, public=None,
             version=True, extra=None, force=False, lock=None, write=None):
    """Change row rid of kind (module docstring). b = the request body (expect_updated_at in it); clean(c, b, cur) -> {column:
    clean value} of the fields sent; dec(c, raw) -> the row as dict (decrypted), enc(c, {column: value}) -> as stored;
    public(c, cur) -> the current state of a 409 (under "current");
    version=False for the module's own internal writes (no version check);
    extra(c, cur, changed) runs inside the step (more rows of the object); force = stamp the row even when no own column
    changed (extra changed something); lock = the name of the row's lock when the module's other writes use one already
    (default obj-<kind>-<id>); write(c, cur, {column: new}) = the module's own writer instead of the plain UPDATE (master
    data: office/model.py office_update seals and checks itself). Returns (row after, changed)."""
    reg = OBJ_TRACK.get(kind)
    if reg is None:
        raise ValueError(f"ow_write: kind {kind!r} not tracked (ow_kind)")
    t = reg["table"]
    rid = int(rid)
    args = (rid, oid) if args is None else tuple(args)
    write_lock(c, lock or f"obj-{kind}-{rid}")
    raw = c.execute(f"SELECT * FROM {t} WHERE {where} FOR UPDATE", args).fetchone()
    if raw is None:
        raise Denied(404)
    cur = dec(c, raw) if dec else dict(raw)
    b = b if isinstance(b, dict) else {}
    agent = obj_is_agent(c, uid) if uid else False
    if version:
        if agent and not b.get("expect_updated_at"):
            raise VersionRequired(("expect_updated_at",), tr(NEED_VERSION))  # 2.564.0 (#4702): the agents' one code version_required
        ow_check(b, raw["updated_at"], lambda: public(c, cur) if public else dict(cur))
    vals = clean(c, b, cur) or {}
    changed = {k: (cur.get(k), v) for k, v in vals.items() if not _same(cur.get(k), v)}
    if not changed and not force:
        return cur, {}
    roid = raw["org_id"] if "org_id" in raw.keys() else oid
    if uid:  # an internal write without a person (a mail sent in the background): no undo step
        obj_undo_pre(c, uid, kind, rid, roid or None)
    upd = enc(c, {k: z for k, (_, z) in changed.items()}) if (enc and changed) else {k: z for k, (_, z) in changed.items()}
    cols = ow_cols(c, t)
    stamp = {"updated_at": iso_ms(now_utc())}
    if "updated_by" in cols and uid:
        stamp["updated_by"] = uid
    if write is not None:
        if changed:
            write(c, cur, {k: z for k, (_, z) in changed.items()})
        upd = None  # the history takes the stored values from the row
        sets = stamp
    else:
        sets = {**upd, **stamp}
    c.execute(f"UPDATE {t} SET {','.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), rid])
    if extra:
        extra(c, cur, changed)
    if changed:
        rw = dict(raw)
        if upd is None:
            nw = dict(c.execute(f"SELECT * FROM {t} WHERE id=?", (rid,)).fetchone())
            upd = {k: nw.get(k) for k in changed}
        obj_history_add(c, uid, kind, rid, {k: _stored(rw.get(k)) for k in changed}, {k: _stored(upd.get(k)) for k in changed},
                        org_id=roid or None, agent=agent)
    obj_undo_post(c)
    bump(c)
    new = c.execute(f"SELECT * FROM {t} WHERE id=?", (rid,)).fetchone()
    return (dec(c, new) if dec else dict(new)), changed


def ow_created(c, uid, kind, rid, row, oid):
    """2.585.0 (#4795): the "create" entry of a row made outside ow_write (a deal / lead): row = the columns as stored (sealed
    ones stay sealed, as in ow_write's entries), without the bookkeeping columns and empty values."""
    skip = ("org_id", "created_by", "created_at", "updated_by", "updated_at", "sort")
    obj_history_add(c, uid, kind, rid, {}, {k: _stored(v) for k, v in row.items() if k not in skip and v not in (None, "", 0)},
                    action="create", org_id=oid or None)


def ow_history(c, kind, rid, oid, limit=50):
    """The history of row rid of kind, newest first. The caller checked the rights to read it (the office's own).
    2.570.0 (#4783 review F2): only the entries of office area oid (defence in depth on top of the route's row check);
    oid None = no filter (a client moves between organisations, its history goes along; need_client checked the row)."""
    if oid is None:
        rows = c.execute("SELECT * FROM obj_history WHERE kind=? AND ref_id=? ORDER BY id DESC LIMIT ?", (kind, int(rid), int(limit))).fetchall()
    else:
        rows = c.execute("SELECT * FROM obj_history WHERE kind=? AND ref_id=? AND (org_id=? OR org_id IS NULL) ORDER BY id DESC LIMIT ?",
                         (kind, int(rid), int(oid), int(limit))).fetchall()
    names = user_names(c, [r["user_id"] for r in rows if r["user_id"]])
    return [{"id": r["id"], "at": r["updated_at"], "user_id": r["user_id"], "name": names.get(r["user_id"], ""), "agent": bool(r["agent"]),
             "action": r["action"], "fields": sorted(set(json.loads(r["vals_before"] or "{}")) | set(json.loads(r["vals_after"] or "{}")))}
            for r in rows]


def ow_history_answer(c, kind, rid, oid):
    """2.570.0 (#4783): {items: the history of row rid of kind} -- the routes GET <the save route's path>/history call it after
    the rights checks of their save route (the gate, the row in the organisation, the level "own"; no state checks like
    "draft only": a finished row's history stays readable)."""
    return jsonify(items=ow_history(c, kind, rid, oid))


def ow_need_row(c, table, where, args):
    """404 unless the row is there (the where / args of the save route's ow_write)."""
    if c.execute(f"SELECT 1 FROM {table} WHERE {where}", tuple(args)).fetchone() is None:
        raise Denied(404)
