"""2.981.0 (#5287, stage Q9b of the cross-cutting core, analysis #3563, decided 08.11.2026): the owner's ceiling of the
notifications of an object, once, in the shared core -- one table obj_notif_cap (migrations.d/5287_a.py); it replaced
list_notif and folder_notif.

    kind 'list'    a project (ref_id = lists.id, path '')
    kind 'folder'  a folder of the project owner (ref_id = the owner's account, path = the folder's path: a folder is keyed by its
                   owner and path like every folder setting, lists/lffolder.py -- the same path in two workspaces is one folder
                   of the person)
    user_id 0      the template for everyone of the object, else for that one person
    tpl            read | work | all | custom (custom: JSONB {event: 0|1}); notify/caps.py says what each one lets through

What a template means, who may set it and how a person's template resolves (person, project, folders upwards, the default)
stays with notify/caps.py; this module only keeps the rows. A ceiling limits pushes of people who already are in the project
(notify/caps.py cap_ok, asked by collab/news.py notif_ok): it never gives anyone a right, so reading a row needs no check of its
own beyond the caller's (the owner's routes ask list_role / the own folder).

The rows go with their object: the trigger kalmido_ncap_gone deletes a project's rows when it is deleted for good, an
account's folder rows and every row naming it as the person when the account goes. Not in the organisation export (a person's
setting, as before); the account export keeps its parts list_notif / folder_notif with their old columns.

Interface (c = the connection):
  ncap_rows(c, kind, rid, path='', uids=None) -> {user_id: row (tpl, custom JSON text | None)}
  ncap_rows_of(c, kind, rids, uids) -> [row (ref_id, path, user_id, tpl, custom)]   many objects at once
  ncap_put(c, kind, rid, path, uid, tpl, custom=None, once=False) -> bool   custom replaces the stored one only when given;
                                                                            once: only when there is no row yet
  ncap_drop(c, kind, rid, path, uid) -> int
  ncap_move(c) -> int    the start (core/objhooks.MOVE): the old tables in, before the fragment 5287_a drops them
"""
from .db import iso, now_utc
from .kernretire import kern_retire_floor
from .objhooks import MOVE
from .pg import st_ids

NCAP_KINDS = ("list", "folder")
NCAP_TPLS = ("read", "work", "all", "custom")
NCAP_COLS = "ref_id, path, user_id, tpl, custom::text AS custom, updated_at"


def _kind(kind):
    if kind not in NCAP_KINDS:
        raise ValueError(f"obj_notif_cap: unknown kind {kind!r}")
    return kind


def ncap_rows(c, kind, rid, path="", uids=None):
    """{user_id: row} of the ceilings of (kind, rid, path); uids: only these people (0 = the template for everyone)."""
    q = f"SELECT {NCAP_COLS} FROM obj_notif_cap WHERE kind=? AND ref_id=? AND path=?"
    a = [_kind(kind), int(rid), path or ""]
    if uids is not None:
        q += " AND user_id = ANY(CAST(? AS BIGINT[]))"
        a.append(st_ids(sorted({int(u) for u in uids})))
    return {r["user_id"]: r for r in c.execute(q, a).fetchall()}


def ncap_rows_of(c, kind, rids, uids):
    """The rows of many objects of kind (rids) for the people uids, in one query."""
    rids = sorted({int(x) for x in rids or ()})
    if not rids:
        return []
    return c.execute(f"SELECT {NCAP_COLS} FROM obj_notif_cap WHERE kind=? AND ref_id = ANY(CAST(? AS BIGINT[])) "
                     "AND user_id = ANY(CAST(? AS BIGINT[]))", (_kind(kind), st_ids(rids), st_ids(sorted({int(u) for u in uids})))).fetchall()


def ncap_put(c, kind, rid, path, uid, tpl, custom=None, once=False):
    """Sets the ceiling of (kind, rid, path) for person uid (0 = everyone): tpl of NCAP_TPLS, custom = JSON text of the chosen
    events (replaces the stored one only when given). once: only when there is no row yet. True = a row was written."""
    if tpl not in NCAP_TPLS:
        raise ValueError(f"obj_notif_cap: unknown template {tpl!r}")
    conflict = "DO NOTHING" if once else ("DO UPDATE SET tpl=excluded.tpl, custom=COALESCE(excluded.custom, obj_notif_cap.custom), "
                                          "updated_at=excluded.updated_at")
    return c.execute("INSERT INTO obj_notif_cap(kind, ref_id, path, user_id, tpl, custom, updated_at) VALUES(?,?,?,?,?,CAST(? AS JSONB),?) "
                     f"ON CONFLICT (kind, ref_id, path, user_id) {conflict}",
                     (_kind(kind), int(rid), path or "", int(uid or 0), tpl, custom, iso(now_utc()))).rowcount > 0


def ncap_drop(c, kind, rid, path, uid):
    """The ceiling of (kind, rid, path) for person uid (0 = the one for everyone) goes; returns the rows deleted."""
    return c.execute("DELETE FROM obj_notif_cap WHERE kind=? AND ref_id=? AND path=? AND user_id=?",
                     (_kind(kind), int(rid), path or "", int(uid or 0))).rowcount


# ---- the start

NCAP_ISO = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d{1,6})?(Z|[+-]\d\d:\d\d)$"
_NCAP_VAL = """CASE WHEN n.tpl IN ('read','work','all','custom') THEN n.tpl ELSE 'read' END,
           CASE WHEN pg_input_is_valid(n.custom, 'jsonb') AND left(ltrim(n.custom), 1) = '{' THEN n.custom::jsonb END,
           CASE WHEN n.updated_at ~ ? THEN n.updated_at::timestamptz ELSE CURRENT_TIMESTAMP END"""
NCAP_OLD_LIST = f"""INSERT INTO obj_notif_cap(kind, ref_id, path, user_id, tpl, custom, updated_at)
    SELECT 'list', n.list_id, '', n.user_id, {_NCAP_VAL}
    FROM list_notif n JOIN lists l ON l.id=n.list_id
    ON CONFLICT DO NOTHING"""
NCAP_OLD_FOLDER = f"""INSERT INTO obj_notif_cap(kind, ref_id, path, user_id, tpl, custom, updated_at)
    SELECT 'folder', n.owner_id, n.folder, n.user_id, {_NCAP_VAL}
    FROM folder_notif n JOIN users u ON u.id=n.owner_id
    ON CONFLICT DO NOTHING"""
NCAP_FLOOR_HOW = ("the notification templates of projects and folders moved into the shared core (obj_notif_cap, #5287) and the old "
                  "tables were dropped - an older version would make them again empty and lose what it writes there; go back only "
                  "with a backup from before")


def ncap_move(c):
    """2.981.0 (#5287): the rows of list_notif and folder_notif into obj_notif_cap, while those tables are there (the first start
    of 2.981, or again after an older version ran and made them anew). Only rows whose project / owner still exists; a row there
    already stays; an unknown template becomes 'read' (the default of a share), a custom that is no JSON object NULL, an old
    time that is not in the app's ISO form the time of the move. The fragment 5287_a drops the old tables right after
    (one-way). Returns the rows moved."""
    n, old = 0, False
    for t, q in (("list_notif", NCAP_OLD_LIST), ("folder_notif", NCAP_OLD_FOLDER)):
        if c.execute("SELECT to_regclass(?)", (t,)).fetchone()[0]:
            n += c.execute(q, (NCAP_ISO,)).rowcount
            old = True
    if old:  # the back limit = the minor of the image that moves (core/kernretire.py, review 2.972), not the package label
        kern_retire_floor(c, how=NCAP_FLOOR_HOW)
    if n:
        print(f"notification templates moved into obj_notif_cap: {n}", flush=True)
    return n


MOVE.append(ncap_move)  # core/db.py init_db, before the fragments' AFTER (core/objhooks.py)
