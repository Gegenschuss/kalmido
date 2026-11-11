"""2.784.0 (#5366, stage 4 of the core's trash): office kinds on the ONE trash of the core (core/writes.py obj_trash /
obj_restore / obj_trash_prune, docs/dev/kern.md). An office kind that deletes by deleted_at is registered here as a core
object without routes, folder node or listing (ofk_register): its own office routes check the office rights as before and
then put the row into the core's trash (ofk_trash: deleted_at / deleted_by, the person's undo step, mode trash) and take it
back (ofk_restore: mode restore); the core's hourly retention run (obj_trash_tick, trash_prune=True) deletes it for good
after the trash period, with its children (obj_register children) -- the area's own purge runs are gone.
The core's role of such a row (the second floor under the route's own check): 'manage' for who may manage the office area
in the kind's rights area (a personal office: its owner; an organisation: the level `need` of deleting it there, the
admin role or the groups, office/rights.py office_can), nothing for anyone else -- no shares, no agents' own way (agents keep the office routes).
GoBD: rows that are locked (booked / finalised) never get here -- the routes refuse to delete them (409) before
ofk_trash, and the retention run only ever reads rows in the trash.
The office trash of copies (office/otrash.py, office_trash) stays for the kinds that delete the row itself (drafts, parts,
trips, card lines, ...) until their stage moves them here.
2.905.0 (#5414, stage 4c): the master data (office/model.py MD), the rights groups, the fixed costs (and
an import of them taken back), the cash flow's corrections and a letter's links moved here. view= shows such a kind in the
office trash (GET /api/office/trash, restore / delete for good through POST/DELETE /api/office/trash/core/<kind>/<id>, the
toast's undo through ?undo=1); old copies of these kinds already in office_trash stay restorable there until their period ends."""
from ..core.access import Denied, trash_sql
from ..core.objects import OBJ, obj_register, obj_row
from ..core.pg import qi, system_ctx
from ..core.retention import ret_on, ret_trash_cut
from ..core.writes import _purge_rows, obj_purge_after, obj_restore, obj_trash, obj_trash_prune  # 2.993.0 (#5413): + obj_purge_after
from ..core.serializers import unlink_files  # 2.993.0 (#5413): an overdue row's stored files after the commit (ofk_restore)
from ..core.objects import obj_forget  # 2.809.0 (#5418)
from ..core.pg import write_lock  # 2.809.0 (#5418)
from .model import office_on, office_role, pb_owner
from ..accounts.orgroles import is_write_request, office_allowed  # 2.809.0 (#5418)
from ..accounts.supportgrant import sga_org_foreign  # 2.809.0 (#5418)
from .rights import office_can  # 2.905.0 (#5414): rights.py never imports this module at its top (its trash kind is registered in office/web.py)

OFK = {}  # kind -> {table, area, need, base, view}


def _tables():
    """The allowlist of the table names for SQL text (core/pg.py qi): the ones registered here."""
    return {k["table"] for k in OFK.values()}


def _base_of(kind):
    def base(c, uid, rid):
        row = obj_row(c, kind, rid)
        if row is None or not row["org_id"]:
            return None
        oid = row["org_id"]
        # 2.809.0 (#5418): the same gates as the office routes (office_gate / office_org) also on the core's way (/api/undo,
        # the trash): the office switched on for the person, the organisation role may write there (office_allowed: no
        # read-only, accounting or guest), and a support session writes into no foreign organisation (sga_org_foreign)
        if not office_on(c, uid) or office_allowed(c, uid, oid, write=True) is not None:
            return None
        if is_write_request() and sga_org_foreign(c, oid):
            return None
        if OFK[kind].get("base"):  # 2.905.0 (#5414): a kind whose rights are not one area's level (the rights groups), after the gates
            return OFK[kind]["base"](c, uid, row)
        owner = pb_owner(c, oid)
        if owner is not None:  # a personal office: only its owner
            return "manage" if owner == uid else None
        if office_role(c, uid, oid) is None:
            return None  # not of this organisation at all
        k = OFK[kind]
        return "manage" if office_can(c, uid, oid, k["area"], k["need"]) else None
    return base


def _visible_of(table):
    def visible(c, uid):  # the candidates only (cap hook: obj_role decides each row)
        u = int(uid)
        return (f"(SELECT id FROM {qi(table, _tables())} WHERE org_id IN (SELECT id FROM orgs WHERE personal_of = {u}) "
                f"OR org_id IN (SELECT org_id FROM org_members WHERE user_id = {u}))")
    return visible


def _space_of(table):
    def space(c, rid):
        r = c.execute(f"SELECT org_id FROM {qi(table, _tables())} WHERE id=?", (int(rid),)).fetchone()
        if r is None:
            return None
        # a personal office has no organisation floor (its owner is checked by the base role), an organisation's has
        return (None, None) if pb_owner(c, r["org_id"]) is not None else (r["org_id"], None)
    return space


def ofk_register(kind, table, label, area, need="manage", children=(), base=None, view=None, step=True, trash_keep=None):
    """Registers an office kind on the core's trash (module docstring); area = its rights area (office/rights.py), need =
    the level its route needs to delete a row (an "own" level: the route checks the row is the person's own).
    2.905.0 (#5414): base(c, uid, row) -> 'manage' | None replaces the area's level (the rights groups: who manages the
    rights); view = {"kind": the app's name of it (or fn(row)), "label": fn(c, oid, row) -> text, "ctx": the module's context
    () -> (c, uid, oid) for the toast's undo, "back": fn(c, oid, row) after a restore} shows it in the office trash.
    2.905.0 (#5414, review): step=False = no step in the person's undo list (GET /api/undo): a kind whose route does more
    than the core on trash / restore (in-use checks, members out, the view's back hook) is only taken back through its
    own routes (the toast's undo, the office trash), never by the core's undo / redo that would skip them.
    2.993.0 (#5413): trash_keep = obj_register trash_keep (rows of the trash kept by law, the retention run leaves them; the
    exact check stays the kind's obj_on_purge hook, Denied = kept)."""
    OFK[kind] = {"table": table, "area": area, "need": need, "base": base, "view": view, "step": step}
    return obj_register(kind, table, label=label, fields={}, area="office", routes=False, listed=False, fsref=False,
                        space=_space_of(table), base_role=_base_of(kind), visible=_visible_of(table), cap=lambda c, uid, rid: None,
                        scopes=("office", "office"), children=children, trash_prune=True, trash_keep=trash_keep)


def ofk_trash(c, uid, kind, rid):
    """Into the core's trash (the route checked the office rights and that the row may go); one undo step of the person
    (not for a kind registered with step=False, see ofk_register)."""
    return obj_trash(c, uid, kind, rid, step=OFK.get(kind, {}).get("step", True))


def ofk_restore(c, uid, kind, rid, undo=False):
    """Out of the core's trash. One past the trash period (switch on) is deleted for good first and answers 404 (committed
    before the refusal rolls back), as the office's own runs did on the next write. undo: the person's own step taken back
    (core/writes.py obj_restore undo=True: only who put it there, while it is still that trash)."""
    row = obj_row(c, kind, rid)
    if row is not None and row["deleted_at"] and ret_on("trash"):
        with system_ctx(c):
            due = c.execute(f"SELECT 1 FROM {qi(OBJ[kind]['table'], _tables())} WHERE id=? AND deleted_at<?", (int(rid), ret_trash_cut())).fetchone()
        if due:
            with obj_purge_after(keep_locked=True) as box:  # 2.993.0 (#5413): its stored files (obj_on_purge) after the commit
                obj_trash_prune(c, kind, purge=True, ids=[int(rid)])
            c.commit()
            unlink_files(box["after"])
            with system_ctx(c):
                kept = c.execute(f"SELECT 1 FROM {qi(OBJ[kind]['table'], _tables())} WHERE id=?", (int(rid),)).fetchone()
            if kept and box["err"]:  # 2.993.0 (#5413, fable F2): the purge failed (not a lock) - no restore of a half-checked row,
                raise Denied(409)  # the next retention run tries again
            if kept:  # kept by law (a receipt: trash_keep / the hook's Denied): it stays in the trash and comes back as any other
                return obj_restore(c, uid, kind, rid, undo=undo, step=OFK.get(kind, {}).get("step", True))
            raise Denied(404)
    return obj_restore(c, uid, kind, rid, undo=undo, step=OFK.get(kind, {}).get("step", True))  # 2.905.0 (#5414, review): ofk_register step


def ofk_purge(c, kind, rid):
    """2.809.0 (#5418): delete one row of an office kind for good on the core's way (core/writes.py _purge_rows: its history,
    undo steps with their emptied groups, revoked shares and children go along, no obj_undo / obj_history left behind) --
    for the office's own deletes that checked the rights themselves (the DATEV import's undo, office/datevimp.py di_undo)."""
    write_lock(c, f"obj-{kind}-{int(rid)}")
    _purge_rows(c, kind, OBJ[kind], rid)
    obj_forget()


def ofk_trash_items(c, oid):
    """2.905.0 (#5414): the rows of office area oid in the core's trash of the kinds shown in the office trash (view=), in the
    shape of the office trash's list (GET /api/office/trash) plus core = the core's kind; id = the row's id."""
    out = []
    for kind, k in sorted(OFK.items()):
        v = k.get("view")
        if not v:
            continue
        for r in c.execute(f"SELECT * FROM {qi(k['table'], _tables())} WHERE org_id=? AND {trash_sql()} "
                           "ORDER BY deleted_at DESC, id DESC LIMIT 500", (oid,)).fetchall():  # review 2.905.0: bounded per kind
            row = dict(r)
            out.append({"id": row["id"], "core": kind, "kind": v["kind"](row) if callable(v["kind"]) else v["kind"], "sub": "",
                        "ref_id": row["id"], "label": (v["label"](c, oid, row) or "")[:300], "deleted_by": row.get("deleted_by"),
                        "deleted_at": str(row["deleted_at"])})
    return out
