"""2.567.0 (#4711): the shared core, stage 2 -- ONE write call for an office row (and a client) on the core's write layer.

The office's rows (office_* tables, the clients) have no owner_id / rev and their own rights (office_gate, office_org,
ofr_check and the office groups), so they are no registered kinds of core/objects.py yet (a real registration would open
them to shares and folders). The transition docs/dev/kern.md names: the kinds are tracked for the history and the undo only
(core/writes.py obj_track), and ow_write does for one row in ONE call what obj_write does for a core object:

  write_lock('obj-<kind>-<id>') -> the row again under the lock (FOR UPDATE) -> an AGENT must send expect_updated_at (400
  without, as obj_write) -> the version check (core/conflict.py ccf_check: 409 with the current state under "current", or
  under the route's old key too, OwConflict) -> only the fields sent (the module's own cleaner, partial) -> nothing changed = nothing written ->
  the undo step (header X-Kalmido-Undo, people only: obj_undo_pre / obj_undo_post) -> updated_at (milliseconds, the base of
  the next save), updated_by -> the history (obj_history: before / after of the changed columns AS STORED -- an encrypted
  column stays sealed there, an agent marked) -> bump. The caller commits.

The rights stay the module's own (called before ow_write, unchanged: office_gate, office_org, ofr_check, need_client); no
other route changes here. A route that changes more than the row (a client's contact persons) does it in `extra`, inside
the same undo step.

Interface:
  ow_kind(kind, table, scope=None, keep=None, nofp=None)       track a kind (at import of its module)
  ow_write(c, uid, kind, rid, b, clean, *, where=..., args=..., dec=None, enc=None, public=None, alias=None,
           version=True, extra=None, force=False) -> (row after (dec'd dict), {column: (before, after)})
  ow_check(b, have, cur, alias=None)                            the version check alone (OwConflict)
  ow_crypt(table, office) -> (dec, enc)                         for a table with encrypted columns (core/orgcrypt.py)
  ow_undo_ctx(kind, fn)                                         the session undo of the kind (office/undo.py route)
  ow_history(c, kind, rid, limit=50) -> the entries (the caller checked the rights to read the row)
  ow_is_agent(c, uid) -> bool, ow_uid() -> the signed-in account or None"""
import json

from flask import g, has_request_context, jsonify

from ..collab.comments import user_names

from ..core.config import app
from ..core.conflict import Conflict
from ..core.db import bump, iso_ms, now_utc
from ..core.errors import BadInput, Denied
from ..core.i18n import tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.pg import table_columns, write_lock
from ..core.writes import (NEED_VERSION, OBJ_TRACK, _same, _val, obj_history_add, obj_is_agent, obj_track, obj_undo_post,
                           obj_undo_pre)

class OwConflict(Conflict):
    """409 {"error", "current": the current state, <alias>: the same} -- "current" as obj_write; alias = the key the route
    answered with before (row, letter, client), so the clients and agents reading it go on working."""

    def __init__(self, cur, alias=None):
        super().__init__("current", cur)
        self.alias = alias


@app.errorhandler(OwConflict)
def ow_conflict_answer(e):
    out = {"error": e.text(), "current": e.cur}
    if e.alias and e.alias != "current":
        out[e.alias] = e.cur
    return jsonify(out), 409


def ow_check(b, have, cur, alias=None):
    """The version check (core/conflict.py ccf_check, answered with OwConflict): expect_updated_at set and not the row's -> 409."""
    exp = b.get("expect_updated_at") if isinstance(b, dict) else None
    if exp and str(exp) != str(have or ""):
        raise OwConflict(cur(), alias)


OW_UNDO_CTX = {}  # undo kind -> fn(ref) -> (c, uid, oid, after(c) -> the answer): how office/undo.py checks the rights (ow_undo_ctx)


def ow_undo_ctx(kind, fn):
    """A module on ow_write names how an undo of its kind is checked (the rights of its normal change) and answered."""
    OW_UNDO_CTX[kind] = fn
    return fn


_COLS = {}  # table -> its columns (they only grow at start-up: the migrations run before the first request)


def ow_kind(kind, table, scope=None, keep=None, nofp=None):
    """Track an office kind (core/writes.py obj_track): scope(rid, oid) -> the undo's tables (default: the row)."""
    return obj_track(kind, table, area="other", undo_scope=scope or (lambda rid, oid: [(table, "id=?", (int(rid),), False)]),
                     undo_keep=keep, undo_nofp=nofp)


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
             alias=None, version=True, extra=None, force=False, lock=None, write=None):
    """Change row rid of kind (module docstring). b = the request body (expect_updated_at in it); clean(c, b, cur) -> {column:
    clean value} of the fields sent; dec(c, raw) -> the row as dict (decrypted), enc(c, {column: value}) -> as stored;
    public(c, cur) -> the current state of a 409 (under "current", and under alias too: the key the route used before);
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
            raise BadInput(tr(NEED_VERSION))
        ow_check(b, raw["updated_at"], lambda: public(c, cur) if public else dict(cur), alias)
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


def ow_history(c, kind, rid, limit=50):
    """The history of row rid of kind, newest first. The caller checked the rights to read it (the office's own)."""
    rows = c.execute("SELECT * FROM obj_history WHERE kind=? AND ref_id=? ORDER BY id DESC LIMIT ?", (kind, int(rid), int(limit))).fetchall()
    names = user_names(c, [r["user_id"] for r in rows if r["user_id"]])
    return [{"id": r["id"], "at": r["updated_at"], "user_id": r["user_id"], "name": names.get(r["user_id"], ""), "agent": bool(r["agent"]),
             "action": r["action"], "fields": sorted(set(json.loads(r["vals_before"] or "{}")) | set(json.loads(r["vals_after"] or "{}")))}
            for r in rows]
