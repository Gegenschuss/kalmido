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
The office trash of copies (office/otrash.py, office_trash) stays for the kinds that delete the row itself (drafts, master
data, trips, ...) until their stage moves them here."""
from ..core.access import Denied
from ..core.objects import OBJ, obj_register, obj_row
from ..core.pg import system_ctx
from ..core.retention import ret_on, ret_trash_cut
from ..core.writes import obj_restore, obj_trash, obj_trash_prune
from .model import office_role, pb_owner

OFK = {}  # kind -> {table, area}


def _base_of(kind):
    def base(c, uid, rid):
        row = obj_row(c, kind, rid)
        if row is None or not row["org_id"]:
            return None
        oid = row["org_id"]
        owner = pb_owner(c, oid)
        if owner is not None:  # a personal office: only its owner
            return "manage" if owner == uid else None
        if office_role(c, uid, oid) is None:
            return None  # not of this organisation at all
        from .rights import office_can  # rights.py imports the office trash's module chain at its top
        k = OFK[kind]
        return "manage" if office_can(c, uid, oid, k["area"], k["need"]) else None
    return base


def _visible_of(table):
    def visible(c, uid):  # the candidates only (cap hook: obj_role decides each row)
        u = int(uid)
        return (f"(SELECT id FROM {table} WHERE org_id IN (SELECT id FROM orgs WHERE personal_of = {u}) "
                f"OR org_id IN (SELECT org_id FROM org_members WHERE user_id = {u}))")
    return visible


def _space_of(table):
    def space(c, rid):
        r = c.execute(f"SELECT org_id FROM {table} WHERE id=?", (int(rid),)).fetchone()
        if r is None:
            return None
        # a personal office has no organisation floor (its owner is checked by the base role), an organisation's has
        return (None, None) if pb_owner(c, r["org_id"]) is not None else (r["org_id"], None)
    return space


def ofk_register(kind, table, label, area, need="manage", children=()):
    """Registers an office kind on the core's trash (module docstring); area = its rights area (office/rights.py), need =
    the level its route needs to delete a row (an "own" level: the route checks the row is the person's own)."""
    OFK[kind] = {"table": table, "area": area, "need": need}
    return obj_register(kind, table, label=label, fields={}, area="office", routes=False, listed=False, fsref=False,
                        space=_space_of(table), base_role=_base_of(kind), visible=_visible_of(table), cap=lambda c, uid, rid: None,
                        scopes=("office", "office"), children=children, trash_prune=True)


def ofk_trash(c, uid, kind, rid):
    """Into the core's trash (the route checked the office rights and that the row may go); one undo step of the person."""
    return obj_trash(c, uid, kind, rid)


def ofk_restore(c, uid, kind, rid):
    """Out of the core's trash. One past the trash period (switch on) is deleted for good first and answers 404 (committed
    before the refusal rolls back), as the office's own runs did on the next write."""
    row = obj_row(c, kind, rid)
    if row is not None and row["deleted_at"] and ret_on("trash"):
        with system_ctx(c):
            due = c.execute(f"SELECT 1 FROM {OBJ[kind]['table']} WHERE id=? AND deleted_at<?", (int(rid), ret_trash_cut())).fetchone()
        if due:
            obj_trash_prune(c, kind, purge=True, ids=[int(rid)])
            c.commit()
            raise Denied(404)
    return obj_restore(c, uid, kind, rid)
