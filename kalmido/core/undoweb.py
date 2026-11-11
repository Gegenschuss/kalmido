"""2.747.0 (#5249): undo across devices, stage 1 -- a person's step groups (core/undogroups.py) listed and taken back.

GET  /api/undo?limit=100       the own groups, newest first (heads only, no copies; the label in the reader's language)
POST /api/undo/to/<gid>        every own group from the newest down to gid back ("bis hierher")
POST /api/undo/<gid>/redo      the way forward of one undone group again (until a new step of the person ends it)
2.905.0 (#5255): a write that recorded its step in a group answers with the header X-Kalmido-Undo-Gid: <group id> (undo_gid_header),
so the app's arrow, Ctrl/Cmd+Z and the toast's "Undo" take back exactly that group (static/js/undo.js); no copy in the browser.
People only: an agent gets 403 (it records no steps either); not in API v1 / MCP. Another person's group = 404.

Taking back: newest group first, each group in ONE transaction (committed after it), each part under write_lock of its object
and in a savepoint, with the fingerprint check of the editor undo (core/writes.py _undo_one: the object must be exactly as the
step left it). The rights are checked at the moment of taking back, never the ones of then: a registered kind needs 'write'
(obj_need), a tracked kind of an old area the check its area registered (undo_need_reg: the office in office/undo.py); a kind
without one is never written back (noaccess). A part that cannot go back (changed since, moved, no right) stays and is named
in the answer, the other parts of the group go back anyway (decision of #5249): the group becomes partial (or noaccess when
nothing of it may be changed). A barrier or a group too big for copies stops the run there -- 2.866.0 (#5302 N2): a barrier
only for the groups of its own workspace (org_id; a finalised invoice does not hold a task step or another office's step). Barriers are per person like the list (decision 2 of
#5249: only own steps): a barrier of someone else does not stop a person's run; a finalised document is frozen anyway."""
import json

from flask import g, jsonify, request

from .config import app
from .ctx import me
from .db import bump, db
from .db import IntegrityError  # 2.809.0 (#5476, review)
from .errors import BadInput, Denied
from .i18n import N_, tr, tr_stored
from .objects import obj_need, obj_row
from .objhooks import OBJ
from .pg import write_lock
from .undodiff import UNDO_DIFF
from .undogroups import UNDO_GROUPS_MAX, UNDO_KEEP_D
from .writes import UNDO_NOTHING, _area, _lock_rows, _redo_one, _reg, _undo_one, obj_is_agent, obj_undo_hist, undo_scope
from .writes import UNDO_CONFLICT, obj_restore, obj_trash  # 2.773.0 (#5292): trash steps go back the core's way

UNDO_NEED = {}  # kind -> fn(c, uid, rid, oid) -> {"fix": fn(c), "keep": {table: {column}}, "lock": name}; Denied = may not
TRASH_MODES = ("trash", "restore")  # 2.773.0 (#5292): obj_undo.mode of a step without a copy (core/writes.py _trash_step)
UNDO_TRASH = {}  # 2.985.0 (#5394): kind -> {"restore": fn(c, uid, rid), "trash": fn(c, uid, rid)} (undo_trash_reg)
UG_NOACCESS = N_("You may not change it any more, so it cannot be undone")
UG_GONE = N_("It is no longer there, so it cannot be undone")
UG_STOP = N_("Stopped before a step that cannot be undone: {0}")
UG_UNDONE = N_("{0} of {1} steps undone")
UG_REDONE = N_("{0} of {1} steps redone")
UG_KEPT = N_("Changed elsewhere, not undone: {0}")  # 2.774.0 (#5251): the fields of a diff part that stayed
UG_KEPT_REDO = N_("Changed elsewhere, not redone: {0}")
UNDO_GID_HDR = "X-Kalmido-Undo-Gid"  # 2.905.0 (#5255)


def undo_need_reg(kind, fn):
    """A tracked kind (core/writes.py obj_track) says who may take its steps back now: fn(c, uid, rid, oid) raises Denied
    (403 / 404 = no access, 409 = its own reason) or returns {"fix", "keep"} as obj_undo_run takes them, and "lock" when
    the kind's saves take another write_lock than obj-<kind>-<id> (ow_write lock=)."""
    UNDO_NEED[kind] = fn


def undo_trash_reg(kind, restore, trash):
    """2.985.0 (#5394): a core kind whose area puts it into / takes it out of the trash its own way (a calendar with its
    events, an address book with its contacts' links and birthday tasks): a trash step of it goes back through restore(c,
    uid, rid) / trash(c, uid, rid) -- each checks the person's rights of now and raises Denied -- instead of obj_restore /
    obj_trash. Neither commits nor sends mails (the group commits; an undo sends no mails)."""
    UNDO_TRASH[kind] = {"restore": restore, "trash": trash}


def _need(c, uid, kind, rid, oid):
    if kind in UNDO_NEED:
        return UNDO_NEED[kind](c, uid, int(rid), oid) or {}
    if kind in OBJ:
        obj_need(c, uid, kind, rid, "write")
        return {}
    raise Denied(403, tr(UG_NOACCESS))  # a kind without a check of its own is never written back


def _label(r):
    try:
        args = json.loads(r["label_args"] or "[]")
    except ValueError:
        args = []
    args = args if isinstance(args, list) else []
    return tr_stored([r["label_key"], *args]) if r["label_key"] else "", args


def _diff_part(c, uid, p, redo):
    """2.774.0 (#5251): a diff part (core/undodiff.py) back / forward through its area's own write path. None when it went
    whole; {..., code, reason, went: True} when it went but some of it stayed (fields changed elsewhere)."""
    kind, rid = p["kind"], int(p["ref_id"])
    spec = UNDO_DIFF.get(kind)
    try:
        with c.savepoint():
            if spec is None:
                raise Denied(404, tr(UG_GONE))
            st = c.execute("SELECT id, state, snap FROM obj_undo WHERE id=?", (p["id"],)).fetchone()
            if st is None or st["state"] != ("undone" if redo else "done"):
                raise Denied(409, tr(UNDO_NOTHING))
            try:
                data = json.loads(st["snap"] or "{}")
            except ValueError:
                raise Denied(404, tr(UG_GONE)) from None
            g.undo_running = True  # the area's write path records no new step (core/undodiff.py undo_quiet)
            try:
                data, left = spec["run"](c, uid, rid, data, redo)
            finally:
                g.undo_running = False
            c.execute("UPDATE obj_undo SET state=?, snap=? WHERE id=?",
                      ("done" if redo else "undone", json.dumps(data, ensure_ascii=False, default=str), p["id"]))
            p["area"] = spec["area"]
        if left:
            return {"group": p["group_id"], "kind": kind, "id": rid, "code": "conflict", "went": True,
                    "reason": tr(UG_KEPT_REDO if redo else UG_KEPT, ", ".join(str(x) for x in left))}
        return None
    except Denied as e:
        code = "noaccess" if e.code in (403, 404) else "conflict"
        return {"group": p["group_id"], "kind": kind, "id": rid, "code": code, "reason": e.text()}
    except IntegrityError:  # 2.809.0 (#5476, review): a unique row came back meanwhile (a feed followed again): the part stays
        return {"group": p["group_id"], "kind": kind, "id": rid, "code": "conflict", "reason": tr(UNDO_CONFLICT)}
    except BadInput as e:  # a value the area's checks refuse now (a rule changed since): stays, named
        return {"group": p["group_id"], "kind": kind, "id": rid, "code": "conflict", "reason": str(e)}


def _trash_part(c, uid, kind, rid, p, redo):
    """2.773.0 (#5292): a trash / restore step (mode, core/writes.py _trash_step) goes back the core's opposite way --
    obj_restore / obj_trash with their rights of now, the node and the children; the object elsewhere already = 409."""
    st = c.execute("SELECT * FROM obj_undo WHERE id=?", (p["id"],)).fetchone()
    if st is None or st["state"] != ("undone" if redo else "done"):
        raise Denied(409, tr(UNDO_NOTHING))
    write_lock(c, f"obj-{kind}-{int(rid)}")  # 2.985.0 (#5394, review F10): the trash state read under the lock of obj_trash / obj_restore
    row = obj_row(c, kind, rid)
    if row is None:
        raise Denied(404, tr(UG_GONE))
    back = (st["mode"] == "trash") != bool(redo)  # undo of a trash / redo of a restore = out of the trash
    if bool(row["deleted_at"]) != back:
        raise Denied(409, tr(UNDO_CONFLICT))
    hook = UNDO_TRASH.get(kind)  # 2.985.0 (#5394): the area's own way (calendars, address books)
    if hook:
        hook["restore" if back else "trash"](c, uid, rid)
    elif back:  # 2.778.0 (#5371): the own step back with the role of putting it in (trash_role 'edit' = write), not 'manage'
        obj_restore(c, uid, kind, rid, step=False, undo=True)
    else:
        obj_trash(c, uid, kind, rid, step=False)
    c.execute("UPDATE obj_undo SET state=? WHERE id=?", ("done" if redo else "undone", st["id"]))


def _part(c, uid, p, redo):
    """One part back (redo: forward again). None when it went, else {group, kind, id, code, reason}."""
    kind, rid = p["kind"], int(p["ref_id"])
    if p.get("mode") in ("diff", "ref"):  # 2.778.0 (#5253): a pointer part (tables, knowledge) runs like a diff part
        return _diff_part(c, uid, p, redo)
    try:
        with c.savepoint():
            if p.get("mode") in TRASH_MODES and kind in OBJ:  # 2.773.0 (#5292)
                _trash_part(c, uid, kind, rid, p, redo)
                p["area"] = _area(_reg(kind))
                return None
            try:
                reg = _reg(kind)
            except Denied:
                raise Denied(404, tr(UG_GONE)) from None  # the kind's module is not there (any more)
            ext = _need(c, uid, kind, rid, p["org_id"])
            if ext.get("keep"):
                keep = ext["keep"]
                base = reg.get("undo_keep") or {}
                reg = {**reg, "undo_keep": {t: set(base.get(t, ())) | set(keep.get(t, ())) for t in {**base, **keep}}}
            write_lock(c, ext.get("lock") or f"obj-{kind}-{rid}")  # the lock the kind's own saves take (ow_write lock=)
            sc = undo_scope(kind, rid, p["org_id"])
            _lock_rows(c, sc)
            st = c.execute("SELECT * FROM obj_undo WHERE id=?", (p["id"],)).fetchone()
            if st is None or st["state"] != ("undone" if redo else "done"):
                raise Denied(409, tr(UNDO_NOTHING))  # an editor session took it meanwhile
            a, z = (_redo_one if redo else _undo_one)(c, sc, st, uid, reg, ext.get("fix"))
            obj_undo_hist(c, uid, kind, rid, p["org_id"], reg, sc, a, z, "redo" if redo else "undo")
            p["area"] = _area(reg)
        return None
    except Denied as e:
        code = "noaccess" if e.code in (403, 404) else "conflict"
        return {"group": p["group_id"], "kind": kind, "id": rid, "code": code, "reason": e.text()}


def _state(c, gid):
    n = dict(c.execute("SELECT state, COUNT(*) FROM obj_undo WHERE group_id=? GROUP BY state", (gid,)).fetchall())
    done, undone = n.get("done", 0), n.get("undone", 0)
    return "undone" if not done else "done" if not undone else "partial"  # no parts left: nothing more to take back


def _run_group(c, uid, grp, redo):
    """Every part of grp back (redo: forward), newest first (redo: oldest first). -> (moved, [stayed])."""
    parts = c.execute("SELECT id, group_id, kind, ref_id, org_id, mode FROM obj_undo WHERE group_id=? AND state=? ORDER BY id " + ("ASC" if redo else "DESC"),
                      (grp["id"], "undone" if redo else "done")).fetchall()
    moved, stayed, areas = 0, [], set()
    for r in parts:
        p = dict(r)
        bad = _part(c, uid, p, redo)
        if bad:
            stayed.append(bad)
        if not bad or bad.pop("went", False):  # 2.774.0 (#5251): a diff part that went with some fields kept counts as moved
            moved += 1
            areas.add(p.get("area"))
    state = _state(c, grp["id"])
    if not redo and not moved and stayed and all(x["code"] == "noaccess" for x in stayed):
        state = "noaccess"
    c.execute("UPDATE undo_groups SET state=? WHERE id=?", (state, grp["id"]))
    for a in areas:
        bump(c, a)
    return moved, stayed


def _own(c, uid, gid):
    if obj_is_agent(c, uid):
        raise Denied(403)
    r = c.execute("SELECT * FROM undo_groups WHERE id=? AND user_id=?", (int(gid), int(uid))).fetchone()
    if r is None:
        raise Denied(404)
    return r


def undo_group_to(c, uid, gid):
    """Every own group from the newest down to gid back (module docstring); commits after each group.
    -> {undone: [ids], partial: [ids], stayed: [{group, kind, id, code, reason}], stopped: {id, state, label} | None, text}"""
    _own(c, uid, gid)
    groups = c.execute("SELECT * FROM undo_groups WHERE user_id=? AND id>=? AND state<>'undone' ORDER BY id DESC", (int(uid), int(gid))).fetchall()
    out = {"undone": [], "partial": [], "stayed": [], "stopped": None}
    total = 0
    held = set()  # 2.866.0 (#5302 N2): the workspaces (org_id, None = private) a barrier holds from here down
    for grp in groups:
        if grp["state"] == "barrier":  # it holds only the steps of its own workspace; the others go on (another org, private)
            out["stopped"] = out["stopped"] or {"id": grp["id"], "state": grp["state"], "label": _label(grp)[0]}
            held.add(grp["org_id"])
            continue
        if grp["state"] == "toobig":  # no copies: nothing older may go back past it
            out["stopped"] = out["stopped"] or {"id": grp["id"], "state": grp["state"], "label": _label(grp)[0]}
            break
        if grp["org_id"] in held:
            continue
        total += 1
        moved, stayed = _run_group(c, uid, grp, False)
        out["stayed"] += stayed
        if moved and stayed:
            out["partial"].append(grp["id"])
        elif moved or not stayed:
            out["undone"].append(grp["id"])
        c.commit()
    bump(c, "self")
    bump(c, "undo")  # #5407: the list of steps of the other devices (undolist.js)
    c.commit()
    text = tr(UG_UNDONE, len(out["undone"]) + len(out["partial"]), total)
    if out["stopped"]:
        text += " " + tr(UG_STOP, out["stopped"]["label"])
    out["text"] = text
    return out


def undo_group_redo(c, uid, gid):
    """The undone parts of one own group forward again; 409 when nothing of it is undone (a new step ended its way forward)."""
    grp = _own(c, uid, gid)
    if grp["state"] not in ("undone", "partial"):
        raise Denied(409, tr(UNDO_NOTHING))
    moved, stayed = _run_group(c, uid, grp, True)
    bump(c, "self")
    bump(c, "undo")  # #5407: the list of steps of the other devices (undolist.js)
    c.commit()
    return {"redone": moved, "stayed": stayed, "text": tr(UG_REDONE, 1 if moved else 0, 1)}


def undo_list(c, uid, limit=100):
    """The own groups, newest first: heads only (no copies); kind / ref_id = the object of the first part (the app sets a
    title it can read itself, e.g. of an encrypted list)."""
    rows = c.execute("SELECT g.*, (SELECT u.kind FROM obj_undo u WHERE u.group_id=g.id ORDER BY u.id LIMIT 1) AS p_kind, "
                     "(SELECT u.ref_id FROM obj_undo u WHERE u.group_id=g.id ORDER BY u.id LIMIT 1) AS p_ref "
                     "FROM undo_groups g WHERE g.user_id=? ORDER BY g.id DESC LIMIT ?", (int(uid), int(limit))).fetchall()
    out = []
    for r in rows:
        label, args = _label(r)
        out.append({"id": r["id"], "at": r["created_at"], "area": r["area"], "label": label, "label_key": r["label_key"],
                    "label_args": args, "device": r["device"], "state": r["state"], "parts": r["parts"], "bytes": r["bytes"],
                    "kind": r["p_kind"], "ref_id": r["p_ref"], "org_id": r["org_id"],
                    "undo": r["state"] in ("done", "partial", "noaccess"), "redo": r["state"] in ("undone", "partial")})
    return out


def _limit():
    try:
        n = int(request.args.get("limit") or 100)
    except ValueError:
        n = 100
    return max(1, min(n, UNDO_GROUPS_MAX))


@app.get("/api/undo")
def undo_list_route():
    c, uid = db(), me()
    if obj_is_agent(c, uid):
        raise Denied(403)
    return jsonify(items=undo_list(c, uid, _limit()), keep_days=UNDO_KEEP_D, max=UNDO_GROUPS_MAX)


@app.post("/api/undo/to/<int:gid>")
def undo_to_route(gid):
    c, uid = db(), me()
    return jsonify(undo_group_to(c, uid, gid))


@app.post("/api/undo/<int:gid>/redo")
def undo_redo_route(gid):
    c, uid = db(), me()
    return jsonify(undo_group_redo(c, uid, gid))


@app.after_request
def undo_gid_header(resp):
    """2.905.0 (#5255): the step group a successful write of a person recorded (core/undogroups.py ug_current, kept in g)."""
    cur = g.get("undo_group")
    if cur and resp.status_code < 400 and request.method != "GET":
        resp.headers[UNDO_GID_HDR] = str(int(cur["id"]))
    return resp
