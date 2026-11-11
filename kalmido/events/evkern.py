"""2.566.0 (#4712): calendars on the shared core, stage 3 (docs/dev/kern.md, audit #2822 "Stufe 3").

The calendar (ev_cals) is the object kind 'evcal' of core/objects.py:
- its role is obj_role (events/model.py ev_role): the organisation floor, an agent's workspace and data lock ("calendar",
  #4699) in one place; the base role is the calendar's own (_ev_role: its owner = 'manage'), the shares are the core's: rows
  of fs_shares on its reference node. 2.924.0 (#5069, stage 7b): the only ones -- the calendar's own sharing dialog writes
  them (cal_member_set -> obj_node_person_put); the old table ev_cal_members and the mirror triggers of 4712_a.py go at the
  start (ev_kern_drop, core/migrations.d/5069_b.py).
- losing access is the core's: obj_revoke_person takes the shares of the node when a person leaves the organisation and when
  it retires (#4697), restorable 30 days (obj_revoked; GET /api/obj/evcal/<id>/shares, POST .../shares/<rid>/restore).
- its settings (name, colour, description) are written by obj_write (lock, version expect_updated_at, history, rev) and the
  calendar goes into the core's trash (obj_trash, #4707) with its events; restoring it brings them back.
- the file store: its node may lie in folders; as for the address books (files/fsref.py 2.199.0 F) filing it and sharing its
  folder stay with its owner (fs base role 'edit' only for 'manage', a member 'view'), so a member cannot pass it on.
The kind has no generic routes (routes=False): the calendar's own routes (events/web.py) call these functions; agents keep
their calendar API (events/v1.py, docs/AGENTS.md)."""
import re

from ..core.db import iso_ms, now_utc
from ..core.errors import BadInput, Denied  # 2.924.0 (#5069): Denied for ev_kern_drop
from ..core.i18n import N_, tr
from ..collab.news import news_add  # 2.924.0 (#5069): _share_back
from ..notify.alerts import aa_now  # 2.924.0 (#5069): the admins' alert of ev_kern_drop (sent by the watchdog)
from ..core.kernretire import KERN_RETIRE_LOCK, kern_retire  # 2.924.0 (#5069): stage 7's start check and DROP (part A)
from ..collab.tcxcore import TCX_RETIRE_WAITS  # 2.924.0 (#5069): the one text of the admins' alert of stage 7
from ..core.objects import obj_node, obj_node_follow, obj_node_person_drop, obj_node_person_put, obj_register, obj_role, obj_visible_sql
from ..core import objhooks
from ..core.pg import qi, system_ctx, write_lock
from ..core.writes import obj_restore, obj_trash, obj_trash_prune, obj_write
from .invite import evi_cal_cancel
from ..contacts.model import BK_KERN
from .model import EV_KIND, KERN, _ev_role, cal_touch, ev_tell


def _cal(c, cid):
    with system_ctx(c):  # structure only (owner, workspace, trash): nothing is handed out here
        return c.execute("SELECT * FROM ev_cals WHERE id=?", (int(cid),)).fetchone()


def _base(c, uid, cid):
    """The core's base role: the calendar's own role (owner -> 'manage')."""
    return {"owner": "manage", "edit": "edit", "view": "view"}.get(_ev_role(c, uid, _cal(c, cid)))


def _visible(c, uid):
    """The ids _base opens to uid: its own calendars (2.924.0, #5069: the members are the core's shares only)."""
    return f"(SELECT id FROM ev_cals WHERE owner_id = {int(uid)})"


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


def _share_back(c, uid, cid, share):
    """2.924.0 (#5069, fable F3): a share of the calendar came back through the core's restore (GET /api/obj/evcal/<id>/shares,
    POST .../restore): what the calendar's own dialog does on a new member -- the person's News and the calendar's signature
    (CalDAV, the clients' calendar list)."""
    who = share.get("user_id") or share.get("agent_id")
    cal = _cal(c, cid)
    if who and cal is not None:
        news_add(c, int(who), "evshare", data={"cal_id": int(cid), "name": cal["name"], "role": share.get("role") or "view"}, row="share")
    cal_touch(c, cid)


KERN.update(role=obj_role, visible=obj_visible_sql, node=obj_node, write=obj_write, follow=obj_node_follow, put=obj_node_person_put,
            drop=obj_node_person_drop)  # 2.924.0 (#5069): put / drop = the calendar's own sharing dialog
obj_register(EV_KIND, "ev_cals", label=N_("Calendar"), fields={"name": _f_name, "color": _f_color, "description": _f_desc},
             title=lambda c, rid: (_cal(c, rid) or {"name": ""})["name"], base_role=_base, visible=_visible, area="calendar",
             scopes=("calendar", "calendar"), dl_area="calendar", routes=False, node_shares=True, on_share_back=_share_back,
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


# ---------------------------------------------------------------- 2.924.0 (#5069): stage 7b, the old member tables go
OLD_TABLES = (("ev_cal_members", "cal_id", EV_KIND, "ev_cals"), ("book_members", "book_id", "address_book", "books"))
_OLD_NAMES = {x for t, col, _k, tb in OLD_TABLES for x in (t, col, tb)}  # the allowlist of qi() for the SQL below
# the sync triggers of stage 3 (core/migrations.d/4712_a.py, 5046_a.py, 5089_a.py): (trigger, its table), then their functions
OLD_TRIGGERS = (("kalmido_kern_back", "fs_shares"), ("kalmido_kern_node_made", "fs_nodes"), ("kalmido_kern_node_gone", "fs_nodes"),
                ("kalmido_kern_mirror_cal", "ev_cal_members"), ("kalmido_kern_mirror_book", "book_members"))
OLD_FUNCS = ("kalmido_kern_back", "kalmido_kern_node_made", "kalmido_kern_node_gone", "kalmido_kern_mirror")
_OLD_TRIG = {x for p in OLD_TRIGGERS for x in p} | set(OLD_FUNCS)  # the allowlist of qi() for the DROP statements


def ev_kern_left(c):
    """{table: number} of the rows of the old member tables the shared core does not hold: the object has no reference node,
    or its node has no share row (live or run out) of that person / agent (ev_kern_drop deletes those first: the core said
    no, so only rows without a node are left after it). The drop waits while one is left. Tables already gone are not named."""
    out = {}
    for t, col, kind, _tb in OLD_TABLES:
        if c.execute("SELECT to_regclass(?) IS NOT NULL", (t,)).fetchone()[0]:
            col = qi(col, _OLD_NAMES)
            out[t] = c.execute(f"SELECT COUNT(*) FROM {qi(t, _OLD_NAMES)} m WHERE NOT EXISTS (SELECT 1 FROM fs_nodes n JOIN fs_shares s ON s.node_id=n.id "
                               f"WHERE n.kind='ref' AND n.ref_kind='{kind}' AND n.ref_id=m.{col} AND (s.user_id=m.user_id OR s.agent_id=m.user_id))"
                               ).fetchone()[0]
    return out


def _old_triggers_drop(c, out):
    """The sync triggers of stage 3 and their functions (no data in them). Only together with the tables (fable F1: no half
    state -- while the tables stay, the triggers keep them and the core in step as before)."""
    trig = {(r[0], r[1]) for r in c.execute("SELECT t.tgname, k.relname FROM pg_trigger t JOIN pg_class k ON k.oid=t.tgrelid "  # pg-ok: pg_catalog oid
                                            "WHERE NOT t.tgisinternal AND k.relnamespace=current_schema()::regnamespace").fetchall()}
    for tg, tb in OLD_TRIGGERS:
        if (tg, tb) in trig:
            c.execute(f"DROP TRIGGER IF EXISTS {qi(tg, _OLD_TRIG)} ON {qi(tb, _OLD_TRIG)}")
            out["triggers"] = out.get("triggers", 0) + 1
    funcs = {r[0] for r in c.execute("SELECT proname FROM pg_proc WHERE pronamespace=current_schema()::regnamespace "  # pg-ok: pg_catalog
                                      f"AND proname IN ({','.join('?' * len(OLD_FUNCS))})", OLD_FUNCS).fetchall()}
    for fn in OLD_FUNCS:  # fable 2.924 F6: only the ones still there (not four DROP statements at every start)
        if fn in funcs:
            c.execute(f"DROP FUNCTION IF EXISTS {qi(fn, _OLD_TRIG)}()")


def ev_kern_drop(c):
    """2.924.0 (#5069) at every start until it is done (core/objhooks.START, core/db.init_db; the step of
    core/migrations.d/5069_b.py). Stage 7b of the shared core: calendars and address books are shared only by the shares of
    their reference node.
    1. the one-shot of before (ev_kern_copy, without its flag): every calendar / address book with an old row and no node
       gets its node, every row of these its share on it (the same person / agent, the row's role and date) -- so a row an
       older version wrote after a rollback comes along too; a row of an object that HAS a node is never copied (the node
       is the truth: a share taken back there stays taken back);
    2. fable F1 (#5117): a row of an object WITH a node and no share of that person is stale -- the core said no -- and is
       deleted (one way; the log names the number);
    3. the check: is a row left the core does not hold (ev_kern_left: still no node -- the copy could not make one), the
       tables AND the triggers stay (no half state), the log names the numbers and the admins get an alert (aa_now,
       "storage"); the next start checks again;
    4. else the sync triggers of stage 3 and their functions go, then DROP TABLE ev_cal_members, book_members and their rows
       in obj_revoked (src = the old table: nothing can put them back; the twin share row of the node stays restorable).
    One way: after the DROP the database refuses an older version (core/kernretire.py kern_retire_floor, fable 2.924 F1).
    Returns {what: number}."""
    out = {}
    with system_ctx(c):  # structure of every workspace
        have = [x for x in OLD_TABLES if c.execute("SELECT to_regclass(?) IS NOT NULL", (x[0],)).fetchone()[0]]
        if not have:
            _old_triggers_drop(c, out)  # a trigger on fs_nodes / fs_shares left without its tables (cheap: one catalog read)
            return out
        write_lock(c, KERN_RETIRE_LOCK)  # one process of the instance at a time (reentrant: kern_retire below takes it again)
        have = [x for x in OLD_TABLES if c.execute("SELECT to_regclass(?) IS NOT NULL", (x[0],)).fetchone()[0]]
        c.execute("UPDATE ev_cals SET updated_at=changed_at WHERE updated_at=''")  # what ev_kern_copy did (#4712)
        c.execute("UPDATE books SET updated_at=changed_at WHERE updated_at=''")
        for t, col, kind, tb in have:
            made = []
            col = qi(col, _OLD_NAMES)
            for (rid, owner) in c.execute(f"SELECT DISTINCT m.{col}, k.owner_id FROM {qi(t, _OLD_NAMES)} m JOIN {qi(tb, _OLD_NAMES)} k ON k.id=m.{col} WHERE NOT EXISTS "
                                          f"(SELECT 1 FROM fs_nodes n WHERE n.kind='ref' AND n.ref_kind='{kind}' AND n.ref_id=m.{col}) "
                                          f"ORDER BY m.{col}").fetchall():
                try:  # an object the core cannot place (no workspace) keeps its rows without a node: the check below holds the drop
                    with c.savepoint():
                        n = obj_node(c, owner, EV_KIND, rid, make=True) if kind == EV_KIND else \
                            BK_KERN["node"](c, owner, rid)  # contacts/ctkern.py bk_node_ensure: in its workspace's "Address book" folder
                except Denied:
                    n = None
                if n is not None:
                    made.append(int(rid))
                    out["nodes"] = out.get("nodes", 0) + 1
            if made:  # (the trigger kalmido_kern_node_made mirrors them as well while it is there: then this finds them in place)
                out[t] = c.execute(
                    f"INSERT INTO fs_shares(node_id, user_id, agent_id, role, created_at, by_role) SELECT n.id, CASE WHEN u.kind='agent' THEN NULL "
                    f"ELSE m.user_id END, CASE WHEN u.kind='agent' THEN m.user_id END, "
                    f"CASE WHEN m.role IN ('view', 'edit') THEN m.role ELSE 'view' END, "
                    f"m.added_at, 'mirror' FROM {qi(t, _OLD_NAMES)} m JOIN users u ON u.id=m.user_id JOIN fs_nodes n ON n.kind='ref' AND n.ref_kind='{kind}' "
                    f"AND n.ref_id=m.{col} WHERE m.{col} IN ({','.join(str(x) for x in made)}) AND NOT EXISTS (SELECT 1 FROM fs_shares s "
                    f"WHERE s.node_id=n.id AND (s.user_id=m.user_id OR s.agent_id=m.user_id))").rowcount
            # fable F1 / #5117 (decided 08.11.2026, one way): a row of an object WITH a node and no share of its person is stale -- the
            # core said no (a share taken back in the file dialog before 2.647): it goes instead of holding the drop for ever
            gone = c.execute(f"DELETE FROM {qi(t, _OLD_NAMES)} m WHERE EXISTS (SELECT 1 FROM fs_nodes n WHERE n.kind='ref' AND n.ref_kind='{kind}' "
                             f"AND n.ref_id=m.{col}) AND NOT EXISTS (SELECT 1 FROM fs_nodes n JOIN fs_shares s ON s.node_id=n.id "
                             f"WHERE n.kind='ref' AND n.ref_kind='{kind}' AND n.ref_id=m.{col} AND (s.user_id=m.user_id OR "
                             f"s.agent_id=m.user_id))").rowcount
            if gone:
                out["stale"] = out.get("stale", 0) + gone
                print(f"migrations: shared core stage 7b (#5069) - {gone} stale row(s) of {t} deleted (their node has no share of "
                      "that person: the core said no)", flush=True)
        # the start check and DROP: the shared helper of stage 7 (core/kernretire.py, the same one as the team chat's 7a);
        # the triggers and functions go only together with the tables (fable F1: no half state)
        out.update(kern_retire(c, [t for t, *_ in OLD_TABLES], lambda c: sum(ev_kern_left(c).values()),
                               "calendars / address books, stage 7b (#5069)", drop=lambda c: _old_triggers_drop(c, out), alert=_retire_alert))
    return out


def _retire_alert(n, tables):
    """fable F1: the admins learn that the start check keeps the old tables (not only the container's log); the text of 7a."""
    aa_now("storage", "kern5069:" + ",".join(tables), TCX_RETIRE_WAITS, (int(n), ", ".join(tables)))


objhooks.START.append(("kern5069_b", False, ev_kern_drop))  # every start until done (cheap afterwards: three catalog reads)
