"""2.872.0 (#5532): the disposition on the shared core (docs/dev/kern.md) -- the shoot day and its call sheet.

Decision of the task: the shoot day and the call sheet are kinds of the core (obj_register, obj_need, obj_write), the call
sheet a part of its shoot day (the same rights, a history of its own); no new rights table.

- shoot_day: a light kind (obj_register node=False, core/objlight.py) on hub_bookings -- a shoot day is no row of its own but the
  bookings made together (hub_bookings.job); its id is the id of any of its bookings. It has no shares, no folder, no routes and
  no write path of the core: the bookings keep their routes (hub/dispo.py) and their steps of the step groups (hub/dspundo.py).
  The disposition's routes ask obj_need(shoot_day, booking id) instead of their own role check (orgroles.need_org_write); the
  rule "a member changes only the bookings they saved, an admin of the area all of them" stays the area's own logic on top.
- callsheet: a kind with the core's columns (hub_callsheets, migrations.d/5532_a.py) without routes, folder node or listing
  (the pattern of sheets/shkern.py, office/okern.py): hub/callsheet.py checks what it checked before (the module, the
  industry Film & Video, a live booking of the job) and then saves the day details through obj_write (lock, version, history,
  undo step, bump); the sketch, too large for a copy in the history, goes through the adapters (obj_undo_pre / _post,
  obj_history_add with a mark instead of the picture). Its trash is the core's: the shoot day's last live booking deleted ->
  the call sheet into the trash (obj_trash), a booking back -> out of it (obj_restore); the core's hourly run deletes it for
  good after the trash period (trash_prune=True, with its history and undo rows).

The role (the same for both kinds, base_role; no shares count, cap gives nothing): a person (no agent, no kid account) with the
module "dispo" switched on who may enter the area (hub/absence.py abs_org: a full member of the organisation -- no guests /
accounting -- or the owner of the personal area): 'manage' when their organisation role changes content
(orgroles.org_writes: not read-only), 'view' when read-only; nobody else. Steps 1 + 2 of obj_role stay on top (the
organisation floor; agents never reach a role here). An object in the trash: only 'manage' (step 4).
The space: an organisation's area -> (org, None); a personal area -> (None, None) (its owner is checked by abs_org)."""
from ..core.access import Denied, live_sql
from ..core.db import usettings
from ..core.i18n import N_, tr
from ..core.objects import obj_need, obj_register
from ..core.pg import system_ctx
from ..core.writes import _purge_rows, obj_reg_node, obj_restore, obj_trash
from ..accounts.orgroles import RO_MSG, org_writes
from .absence import abs_org

DSK_DAY, DSK_CS = "shoot_day", "callsheet"
DSK_SKETCH = "picture"  # the history's mark of a sketch (never the picture itself)


def _person_area(c, uid, oid):
    """'manage' | 'view' | None of account uid in disposition area oid (module docstring)."""
    if not uid or not oid:
        return None
    u = c.execute("SELECT kind, kid FROM users WHERE id=?", (int(uid),)).fetchone()
    if u is None or (u["kind"] or "user") == "agent" or u["kid"]:
        return None
    if "dispo" not in (usettings(c, int(uid)).get("features") or "").split(","):
        return None
    try:
        abs_org(c, int(uid), int(oid), create=False)
    except Denied:
        return None
    return "manage" if org_writes(c, int(uid), int(oid)) else "view"


def _space_of(table):
    def space(c, rid):
        try:
            r = c.execute(f"SELECT org_id FROM {table} WHERE id=?", (int(rid),)).fetchone()
        except (TypeError, ValueError):
            return None
        if r is None:
            return None
        o = c.execute("SELECT personal_of FROM orgs WHERE id=?", (r["org_id"],)).fetchone()
        return (None, None) if o is not None and o["personal_of"] else (r["org_id"], None)
    return space


def _base_of(table):
    def base(c, uid, rid):
        try:
            r = c.execute(f"SELECT org_id FROM {table} WHERE id=?", (int(rid),)).fetchone()
        except (TypeError, ValueError):
            return None
        return _person_area(c, uid, r["org_id"]) if r is not None else None
    return base


def _day_title(c, bid):
    r = c.execute("SELECT title FROM hub_bookings WHERE id=?", (int(bid),)).fetchone()
    return (r["title"] or "") if r else ""


def _cs_visible(c, uid):  # the candidates only (cap hook: obj_role decides each row)
    u = int(uid)
    return (f"(SELECT id FROM hub_callsheets WHERE org_id IN (SELECT id FROM orgs WHERE personal_of = {u}) "
            f"OR org_id IN (SELECT org_id FROM org_members WHERE user_id = {u}))")


def _cs_data(c, value, row):
    """The field 'data' of obj_write: the day details (a dict, hub/callsheet.py cs_clean), stored as JSON, sealed with the
    organisation's key when its encryption is on (core/orgcrypt.py FIELDS: the history keeps the sealed text, as ow_write)."""
    import json
    from ..core.orgcrypt import oc_enc_fields
    from .callsheet import cs_clean
    d = cs_clean(value if value is not None else {})
    txt = json.dumps(d, ensure_ascii=False)
    return oc_enc_fields(c, row["org_id"], "hub_callsheets", {"data": txt})["data"] if row is not None else txt


obj_register(DSK_DAY, "hub_bookings", label=N_("Shoot day"), fields={}, node=False, area="team", space=_space_of("hub_bookings"),
             base_role=_base_of("hub_bookings"), title=_day_title, open_url=lambda bid: "workload")
obj_register(DSK_CS, "hub_callsheets", label=N_("Call sheet"), fields={"data": _cs_data}, area="team", routes=False, listed=False,
             fsref=False, space=_space_of("hub_callsheets"), base_role=_base_of("hub_callsheets"), visible=_cs_visible,
             cap=lambda c, uid, rid: None, list_col="org_id", trash_prune=True, open_url=lambda rid: "workload")


def dsk_need_day(c, uid, rows, write=True):
    """The core's check of the shoot day of the bookings rows (dicts / rows of one job): obj_need(shoot_day, ...) on each
    (a booking in the trash asks the trash). 404 without a role, 403 (read-only: its text) without the role asked."""
    for r in rows:
        try:
            obj_need(c, uid, DSK_DAY, r["id"], "write" if write else "view", trash=bool(r["deleted_at"]))
        except Denied as e:
            # a booking in the trash: only 'manage' sees it there (step 4 of obj_role), so a read-only member would get the
            # 404 of "not there" -- they see the shoot day, they may only not change it: the 403 with the read-only text
            if e.code == 404 and r["deleted_at"] and _person_area(c, uid, r["org_id"]) == "view":
                raise Denied(403, tr(RO_MSG)) from None
            raise


def dsk_sync(c, uid, oid, job):
    """After bookings of shoot day (oid, job) went into the trash or came back: its call sheet follows -- no live booking
    left = into the core's trash, a live one again = out of it. uid's rights (the caller checked them on the bookings)."""
    r = c.execute("SELECT id, deleted_at FROM hub_callsheets WHERE org_id=? AND job=?", (int(oid), job)).fetchone()
    if r is None:
        return
    live = c.execute(f"SELECT 1 FROM hub_bookings WHERE org_id=? AND job=? AND {live_sql()} LIMIT 1",
                     (int(oid), job)).fetchone() is not None
    if live and r["deleted_at"]:
        obj_restore(c, uid, DSK_CS, r["id"], step=False)
    elif not live and not r["deleted_at"]:
        obj_trash(c, uid, DSK_CS, r["id"], step=False)


def dsk_orphans(c, purge):
    """The call sheets whose shoot day has no booking at all any more (the bookings' trash run deleted them for good, or an
    older version left them): deleted for good the core's way (_purge_rows: its history and undo rows with it). -> count."""
    reg = obj_reg_node(DSK_CS)
    with system_ctx(c):  # the retention run reads every workspace (ids only)
        ids = [x[0] for x in c.execute("SELECT id FROM hub_callsheets cs WHERE NOT EXISTS "
                                       "(SELECT 1 FROM hub_bookings b WHERE b.org_id=cs.org_id AND b.job=cs.job)").fetchall()]
        if purge:
            for rid in ids:
                _purge_rows(c, DSK_CS, reg, rid)
    return len(ids)
