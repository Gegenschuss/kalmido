"""2.566.0 (#4712): calendars on the shared core, stage 3 (docs/dev/kern.md, audit #2822 "Stufe 3").

The calendar (ev_cals) is the object kind 'evcal' of core/objects.py:
- its role is obj_role (events/model.py ev_role): the organisation floor, an agent's workspace and data lock ("calendar",
  #4699) in one place; the base role is the calendar's own (_ev_role: its owner = 'manage', a member row of a calendar
  without a live node), the shares are the core's: rows of fs_shares on its reference node, mirrored from ev_cal_members by
  the trigger kalmido_kern_mirror (core/migrations.d/4712_a.py) -- one release long the old rows stay the fallback reader.
- losing access is the core's: obj_revoke_person takes the shares of the node and the rows of ev_cal_members (members= of
  obj_register) when a person leaves the organisation and when it retires (#4697), restorable 30 days (obj_revoked).
- its settings (name, colour, description) are written by obj_write (lock, version expect_updated_at, history, rev) and the
  calendar goes into the core's trash (obj_trash, #4707) with its events; restoring it brings them back.
- the file store: its node may lie in folders; as for the address books (files/fsref.py 2.199.0 F) filing it and sharing its
  folder stay with its owner (fs base role 'edit' only for 'manage', a member 'view'), so a member cannot pass it on.
The kind has no generic routes (routes=False): the calendar's own routes (events/web.py) call these functions; agents keep
their calendar API (events/v1.py, docs/AGENTS.md)."""
import re

from ..core.db import gset, gsetting, iso_ms, now_utc
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..core.objects import obj_node, obj_node_follow, obj_register, obj_role, obj_visible_sql
from ..core.pg import system_ctx, write_lock
from ..core.writes import obj_restore, obj_trash, obj_trash_prune, obj_write
from .invite import evi_cal_cancel
from ..contacts.model import BK_KERN
from .model import EV_KIND, EV_NODE_SQL, KERN, _ev_role, cal_touch, ev_tell

EV_MIGR_FLAG = "migr_kern4712"


def _cal(c, cid):
    with system_ctx(c):  # structure only (owner, workspace, trash): nothing is handed out here
        return c.execute("SELECT * FROM ev_cals WHERE id=?", (int(cid),)).fetchone()


def _base(c, uid, cid):
    """The core's base role: the calendar's own role (owner -> 'manage')."""
    return {"owner": "manage", "edit": "edit", "view": "view"}.get(_ev_role(c, uid, _cal(c, cid)))


def _visible(c, uid):
    """The ids _base opens to uid (its own calendars, the member rows of calendars without a live node)."""
    u = int(uid)
    return (f"(SELECT id FROM ev_cals WHERE owner_id = {u} UNION SELECT m.cal_id FROM ev_cal_members m WHERE m.user_id = {u} "
            f"AND NOT EXISTS ({EV_NODE_SQL.format('m.cal_id')}))")


def _fs_base(c, uid, cid):
    """The role the file store's folders ask for: 'edit' (file it, share its folder) only for its owner, a member 'view'."""
    cal = _cal(c, cid)
    if cal is None or cal["deleted_at"]:
        return None
    r = _ev_role(c, uid, cal)
    return "edit" if r == "owner" else ("view" if r else None)


def _fs_on_trash(c, uid, cid, restore):
    """Its node came back out of the file store's trash while the calendar is in the core's trash: its owner restores the
    calendar with its events (ev_cal_restore), anyone else leaves both in the trash."""
    cal = _cal(c, cid)
    if not restore or cal is None or not cal["deleted_at"]:
        return None
    if uid and _ev_role(c, uid, cal) == "owner":
        ev_cal_restore(c, uid, cid)
        return None
    c.execute("UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE kind='ref' AND ref_kind=? AND ref_id=?",
              (cal["deleted_at"], cal["deleted_by"], EV_KIND, int(cid)))
    return "stays"


def _f_name(c, v, row=None):
    if not isinstance(v, str) or not v.strip():
        raise BadInput(tr("Name missing"))
    return re.sub(r"[\x00-\x1f\x7f]", " ", v).strip()[:100]


def _f_color(c, v, row=None):
    if v is None:
        return ""
    if not isinstance(v, str) or not (v == "" or re.fullmatch(r"#[0-9a-fA-F]{6}", v)):
        raise BadInput(tr("Invalid value: {0}", tr("Colour")))
    return v.lower()


def _f_desc(c, v, row=None):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", "description"))
    return v[:2000]


KERN.update(role=obj_role, visible=obj_visible_sql, node=obj_node, write=obj_write, follow=obj_node_follow)
obj_register(EV_KIND, "ev_cals", label=N_("Calendar"), fields={"name": _f_name, "color": _f_color, "description": _f_desc},
             title=lambda c, rid: (_cal(c, rid) or {"name": ""})["name"], base_role=_base, visible=_visible, area="calendar",
             scopes=("calendar", "calendar"), dl_area="calendar", routes=False, members=("ev_cal_members", "cal_id"),
             open_url=lambda rid: "cal", fs_hooks={"base_role": _fs_base, "on_trash": _fs_on_trash})


# ---------------------------------------------------------------- the trash (#4707)
def ev_cal_trash(c, uid, cid):
    """The calendar into the core's trash (its owner, obj_trash): its live events go with it (the same deleted_at, so the
    restore knows them) and the people invited to them learn they are cancelled. Returns the external invitations' mails
    (events/invite.py evi_cal_cancel) for the caller to send after the commit."""
    mails = evi_cal_cancel(c, uid, cid)  # 2.111.0 B (#2056): its invited external attendees learn the events are gone
    rows = c.execute("SELECT * FROM events WHERE cal_id=? AND deleted_at IS NULL", (int(cid),)).fetchall()
    for r in rows:
        ev_tell(c, r, "cancelled")  # 2.367.2 (#2969): the people of the server too
    row = obj_trash(c, uid, EV_KIND, cid, step=False)  # 2.773.0 (#5292): no undo step until the events move onto the core trash (children)
    c.execute("UPDATE events SET deleted_at=?, updated_at=? WHERE cal_id=? AND deleted_at IS NULL", (row["deleted_at"], iso_ms(now_utc()), int(cid)))
    cal_touch(c, cid)
    return mails


def ev_cal_restore(c, uid, cid):
    """Out of the trash (its owner): the calendar and the events that went with it (not the ones deleted before)."""
    cal = _cal(c, cid)
    at = cal["deleted_at"] if cal is not None else None
    row = obj_restore(c, uid, EV_KIND, cid, step=False)  # 2.773.0 (#5292): see ev_cal_trash
    if at:
        c.execute("UPDATE events SET deleted_at=NULL, updated_at=? WHERE cal_id=? AND deleted_at=?", (iso_ms(now_utc()), int(cid), at))
    cal_touch(c, cid)
    return row


def ev_cal_trash_purge(c, cut, purge, old=None):
    """The calendars in the trash longer than the trash period (events/model.py ev_reminders' retention run): deleted for
    good with their events and node (purge False: only counted). Returns their number. old: their ids when the caller
    has read them already (2.582.0, #4810: _wd_events reads them with the events in one statement)."""
    # 2.773.0 (#5292): the core trash's own run (core/writes.py obj_trash_prune: node, history, undo steps with their groups)
    return obj_trash_prune(c, EV_KIND, cut, purge, ids=old)


KERN.update(trash=ev_cal_trash, restore=ev_cal_restore, purge=ev_cal_trash_purge)


# ---------------------------------------------------------------- the copy into the core (once)
def ev_kern_copy(c):
    """2.566.0 (#4712), once (flag migr_kern4712): every calendar and address book with members gets its reference node; the
    trigger kalmido_kern_mirror copies the member rows into the node's shares (UPDATE ... SET role=role fires it). The old
    rows stay (fallback reader, the way back). The calendars' and books' updated_at start at their changed_at. Idempotent: a
    second run finds the nodes and shares in place."""
    if gsetting(c, EV_MIGR_FLAG) == "1":
        return 0
    n = 0
    with system_ctx(c):  # structure of every workspace
        write_lock(c, "kalmido-" + EV_MIGR_FLAG)  # one process of the instance at a time
        if gsetting(c, EV_MIGR_FLAG) == "1":
            return 0
        c.execute("UPDATE ev_cals SET updated_at=changed_at WHERE updated_at=''")
        c.execute("UPDATE books SET updated_at=changed_at WHERE updated_at=''")
        for (cid, owner) in c.execute("SELECT DISTINCT m.cal_id, k.owner_id FROM ev_cal_members m JOIN ev_cals k ON k.id=m.cal_id "
                                      "ORDER BY m.cal_id").fetchall():
            obj_node(c, owner, EV_KIND, cid, make=True)
            c.execute("UPDATE ev_cal_members SET role=role WHERE cal_id=?", (cid,))
            n += 1
        for (bid, owner) in c.execute("SELECT DISTINCT m.book_id, b.owner_id FROM book_members m JOIN books b ON b.id=m.book_id "
                                      "ORDER BY m.book_id").fetchall():
            BK_KERN["node"](c, owner, bid)  # contacts/ctkern.py bk_node_ensure: the address books' node in their own area folder
            c.execute("UPDATE book_members SET role=role WHERE book_id=?", (bid,))
            n += 1
        gset(c, EV_MIGR_FLAG, "1")
    c.commit()
    if n:
        print("migrations: shared core stage 3 -", n, "calendar(s) / address book(s) with members got their shares in the core", flush=True)
    return n
