"""2.102.0 A (#1988, #2166): the trash of deleted lists. Deleting an archived list (owner, list admin, organisation admin)
no longer moves its tasks into the owner's private inbox and drops fields, tags, chat, sections at once: the list gets
lists.deleted_at / deleted_by and stays with everything; its open tasks go to the trash with the same time stamp (so
every task reader skips them, and the restore brings back exactly these). A deleted list has no roles (access.list_role,
acx_lists_sql via otr_live): only the routes here reach it.

Who sees / restores / deletes for good: a private list -- its owner and its list admins; an organisation's list -- the
organisation's admins, its owner and its list admins, all only while they are members of that organisation (so the former
owner who left never sees it, and nothing of it ever lands in a private space). Agents never. Restoring brings the list
back into the same place (archived, the same organisation or private space). After OTR_TRASH_DAYS the watchdog deletes it
for good (tasks, comments, attachments with their files, fields, chat); time entries stay with list_id NULL (bookkeeping).
2.936.0 (#5364, stage 2a of the core's trash): that run is the core's (core/writes.py obj_trash_tick over the kind list of
lists/lmcore.py: trash_prune, trash_keep=otr_keep, its obj_on_purge hook otr_core_purge); otr_prune went.
2.1002.0 (#5491, stage 2b): restore and delete for good run through the core too (core/writes.py obj_restore / obj_purge; the
kind's trash rule trash_can = otr_can, its children = the tasks); the routes keep their form and the area's rules (a kept
project, the early delete with the name).
Lists with end-to-end encryption keep the immediate hard delete (lists.list_purge)."""
from datetime import timedelta
from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import bump, db, err, iso, now_utc
from ..core.retention import ret_days, ret_on
from ..accounts.session import me
from ..accounts.login import login_log_who  # 2.239.0 B (#2888)
from ..core.access import acx_of, collab_all, Denied, health_hidden, live_sql, token_lists, trash_sql  # 2.936.0 (#5364): live_sql, trash_sql
from contextvars import ContextVar  # 2.1002.0 (#5491): _OTR_EARLY
from ..core.serializers import unlink_files  # 2.1002.0 (#5491): the files of otr_core_purge after the commit
from .lists import list_purge  # 2.369.5 (#2517): pulled up from functions
from ..accounts.pictures import list_icon_drop_file  # 2.369.5 (#2517): pulled up from functions

OTR_TRASH_DAYS = max(1, ret_days("trash"))  # 2.272.0 A (#3026): floor 1 like ret_trash_days; 30 like the other trash periods; 2.152.0 (#2165): KALMIDO_TRASH_DAYS moves it


def otr_trash(c, lid, uid):
    """Moves list lid (archived, checked by the caller) into the trash: the list and its tasks that are not in the trash yet."""
    t = now_utc()
    ts = iso(t)
    for i in range(1, 60):  # the stamp marks what the restore brings back: never the one of a task trashed in the same second
        if not c.execute("SELECT 1 FROM tasks WHERE list_id=? AND deleted_at=? LIMIT 1", (lid, ts)).fetchone():
            break
        ts = iso(t + timedelta(seconds=i))
    c.execute("UPDATE lists SET deleted_at=?, deleted_by=? WHERE id=?", (ts, uid, lid))
    c.execute(f"UPDATE tasks SET deleted_at=? WHERE list_id=? AND {live_sql()}", (ts, lid))
    from ..integrations.gitfolder import gf_before_list_delete
    gf_before_list_delete(c, lid)  # 2.33.0 (#934): a folder repository keeps syncing into a live list of its folder
    return ts


def otr_can(c, uid, r):
    """May uid see / restore / delete for good the deleted list row r (see the module docstring)?
    2.1031.0 (#5538): everything about uid itself, not about the request's person (the core's obj_role asks it for any uid):
    an agent through its access context (core/access.py acx_of); the token limit only when uid is the request's own person
    (it belongs to the request); outside a request the same rule (no request = no token limit)."""
    from ..accounts.orgs import org_role
    if not uid or not r or not r["deleted_at"] or r["is_inbox"]:
        return False
    if acx_of(c, uid).role == "agent" or (r["life"] in ("health", "budget") and health_hidden(c, uid)):
        return False
    u = getattr(g, "user", None) if has_request_context() else None
    tl = token_lists() if u is not None and u["id"] == uid else None
    if tl is not None and r["id"] not in tl:
        return False
    if r["org_id"]:
        role = org_role(c, uid, r["org_id"])
        if not role or role in ("guest", "readonly", "accounting"):
            return False  # 2.143.0 A (#2151): the limited roles restore / delete nothing of the organisation
        if role == "admin" and r["owner_id"] != uid:  # 2.148.1 A (#2480): only a shared list (as the overview of the admins)
            from ..accounts.orglists import ol_shared
            if ol_shared(c, r):
                return True
    if r["owner_id"] == uid:
        return True
    if not r["org_id"] and (r["retain_until"] or "") >= now_utc().date().isoformat():  # 2.186.1 review M1: kept = its custodian only
        return False
    return collab_all() and bool(c.execute("SELECT 1 FROM list_members WHERE list_id=? AND user_id=? AND role='admin'",
                                           (r["id"], uid)).fetchone())


def otr_need(c, lid):
    """The deleted list lid for the current person, or Denied(404). 2.1002.0 (#5491): the core's check (core/objects.py obj_need
    trash=True; otr_can is the kind list's trash_can rule, lists/lmcore.py)."""
    from ..core.objects import obj_need  # a later module (kalmido/__init__.py ORDER)
    return obj_need(c, me(), "list", lid, "manage", trash=True)[0]


def otr_hard(c, lid, early=False):
    """Deletes the (deleted) list lid for good with all its tasks. Returns (icon, file paths) to drop after the commit.
    early = the custodian deletes a project kept by law before the end of its period (otr_held, checked by the caller);
    without it a project kept by law stays (None)."""
    from ..tasks.tasks import hard_delete
    # 2.102.0 review F1: lock the row and look again - a restore committed meanwhile wins (it waits on this lock, then finds nothing)
    r = c.execute("SELECT deleted_at, retain_until FROM lists WHERE id=? FOR UPDATE", (lid,)).fetchone()
    if not r or not r[0]:
        return None
    # 2.992.0 (#5635): retain_until looked at under the row lock too (set meanwhile = kept by law), like ttp_purge for tasks
    if not early and (r[1] or "") >= now_utc().date().isoformat():
        return None
    files = hard_delete(c, [x[0] for x in c.execute("SELECT id FROM tasks WHERE list_id=?", (lid,))], lists={lid})
    icon, lfiles = list_purge(c, lid, None)  # no task is left to move: list_purge only drops the list row + its files
    return icon, lfiles + files


def otr_drop_files(lid, icon, files):
    from .projects import list_files_drop
    list_icon_drop_file(lid, icon)
    list_files_drop(files)


@app.get("/api/trash/lists")
def otr_index():
    """The deleted lists the current person may restore: [{id, name, color, org_id, deleted_at, deleted_by, by_name, tasks}]."""
    from ..accounts.orgs import user_orgs
    from ..collab.comments import user_names
    c, uid = db(), me()
    orgs = user_orgs(c, uid)
    oq = ",".join("?" * len(orgs)) or "NULL"
    rows = c.execute(f"""SELECT l.*, (SELECT COUNT(*) FROM tasks t WHERE t.list_id=l.id AND t.deleted_at=l.deleted_at) AS n
                         FROM lists l WHERE {trash_sql('l')} AND (l.owner_id=? OR l.org_id IN ({oq})
                           OR l.id IN (SELECT list_id FROM list_members WHERE user_id=? AND role='admin'))
                         ORDER BY l.deleted_at DESC, l.id""", (uid, *orgs, uid)).fetchall()
    rows = [r for r in rows if otr_can(c, uid, r)]
    names = user_names(c, [r["deleted_by"] for r in rows])
    today = now_utc().date().isoformat()
    return jsonify(lists=[{"id": r["id"], "name": r["name"], "color": r["color"], "org_id": r["org_id"],
                           "deleted_at": r["deleted_at"], "deleted_by": r["deleted_by"], "by_name": names.get(r["deleted_by"], ""),
                           "tasks": r["n"], "retain_until": r["retain_until"] if (r["retain_until"] or "") >= today else None,
                           "held": otr_held(r, uid)} for r in rows], days=OTR_TRASH_DAYS,
                   purge_on=ret_on("trash"))  # 2.223.3 A (#2877)


def otr_held(r, uid):
    """2.186.1 (#2732): the deleted list row r is a private project kept by law that uid holds as its custodian (a hosted
    account deleted with the retention export waived, useradmin.ua8_lists_settle): uid may download it and delete it for
    good before the end of the period (the duty to keep it lay with the person who waived it). Organisations' lists never."""
    return bool(r["deleted_at"] and not r["org_id"] and r["owner_id"] == uid
                and (r["retain_until"] or "") >= now_utc().date().isoformat())


OTR_HELD = N_("A kept project cannot be restored: download it or delete it before the end of its period.")


def otr_back(c, r, uid, checked=False):
    """2.997.0 (#5609): the deleted list row r back (archived, same organisation / private space) with the tasks of its trash
    stamp (the restore below and the undo of a delete, lists/otrundo.py).
    2.1002.0 (#5491): through the core's restore (core/writes.py obj_restore: the rule otr_can, the lock, the tasks that went
    with it = the kind's children with the same time, rev / updated_by, a history line; no step of the undo list, as before).
    checked=True: the caller checked rights and trash stamp under its own row lock (the undo, lists/otrundo.py)."""
    from ..core.writes import obj_restore  # a later module (kalmido/__init__.py ORDER)
    # 2.102.0 review F1/F7: only a list still in the trash comes back (not one purged or restored meanwhile): Denied(404)
    obj_restore(c, uid, "list", r["id"], step=False, checked=checked)
    if r["org_id"]:
        from ..accounts.orglists import _ol_log
        _ol_log(c, r["org_id"], r, "undelete")


@app.post("/api/trash/lists/<int:lid>/restore")
def otr_restore(lid):
    """Brings the list back (archived, same organisation / private space) with its tasks, fields, tags, chat."""
    c = db()
    r = otr_need(c, lid)
    if otr_held(r, me()):  # 2.186.1 review M2: kept for the law, not taken over (download it or delete it before the end)
        return err(tr(OTR_HELD), 409)
    otr_back(c, r, me())
    bump(c)
    c.commit()
    return jsonify(ok=True, id=lid)


@app.delete("/api/trash/lists/<int:lid>")
def otr_delete(lid):
    """Deletes a list in the trash for good (the client asks first)."""
    c = db()
    r = otr_need(c, lid)
    early = otr_held(r, me())
    if early and getattr(g, "auth_via", None) not in ("session", "proxy"):  # review N1: people only, like the export
        raise Denied(404)
    if early and (request.args.get("confirm") or "") != r["name"]:  # 2.186.1 (#2732): before the end of the period
        return err(tr("Type the project name to confirm"), 409)
    if not early and (r["retain_until"] or "") >= now_utc().date().isoformat():  # 2.186.0 A (#2566): kept by law until then
        return err(tr("This project keeps receipts by law until {0}: it can be deleted permanently after that.", r["retain_until"]), 409)
    # 2.1002.0 (#5491): the core's delete for good (core/writes.py obj_purge: the rule otr_can, the lock, the project's hook
    # otr_core_purge = otr_hard, with early for the custodian's early delete; its history and undo steps go with it); the
    # files after the commit. Restored or kept by law meanwhile: the hook refuses (409 of the core -> 404 as before)
    from ..core.writes import obj_purge, obj_purge_after  # a later module (kalmido/__init__.py ORDER)
    tok = _OTR_EARLY.set(bool(early))
    try:
        with obj_purge_after() as box:
            obj_purge(c, me(), "list", lid, early=bool(early))  # 2.1031.0 (#5538): the core checks trash_keep (otr_keep) too
    except Denied as e:
        if e.code == 409:
            raise Denied(404) from None
        raise
    finally:
        _OTR_EARLY.reset(tok)
    if r["org_id"]:
        from ..accounts.orglists import _ol_log
        _ol_log(c, r["org_id"], r, "purge")
    if early:  # 2.186.1 (#2732): the retention log row of a kept project deleted before the end of its period (same transaction)
        from ..admin.retexport import rx_alert, rx_log
        rx_log(c, {"key": f"list:{int(r['id'])}"}, "purge_early", {"name": r["name"], "until": r["retain_until"]})
    bump(c)
    c.commit()
    unlink_files(box["after"])  # otr_drop_files of otr_core_purge
    if early:  # 2.186.1 (#2732): the security log (like the account deletion, useradmin.ua8_audit)
        rx_alert(N_("{0} deleted the kept project {1} permanently before the end of its retention period ({2})."),
                 [g.user["username"], r["name"], r["retain_until"]])
    print("list", lid, "deleted for good from the trash by", login_log_who(g.user), flush=True)
    return jsonify(ok=True)


def otr_keep(a):
    """2.936.0 (#5364): obj_register trash_keep of the kind list -- a project with receipts kept by law (lists.retain_until today
    or later, useradmin.ua8_receipts_keep; 2.186.0 A, #2566) waits for its end (counted as list_kept)."""
    # 2.1115.0 (#5951): retain_until is DATE (no '' any more); never NULL as a whole - the core uses it under NOT (...)
    return f"({a}.retain_until IS NOT NULL AND {a}.retain_until>=?)", (now_utc().date().isoformat(),)


_OTR_EARLY = ContextVar("otr_early", default=False)  # 2.1002.0 (#5491): otr_delete's early delete for its obj_purge


def otr_core_purge(c, lid):
    """2.936.0 (#5364): the obj_on_purge hook of the kind list (lists/lmcore.py) -- the core's retention run (core/writes.py
    obj_trash_tick: system context, the id checked again under its lock, the switch ret_on("trash"), its report run
    "obj_trash" with list / list_kept / list_err) deletes the project here with its tasks (otr_hard); the icon and the
    files after its commit. Denied(409) = it stays (restored meanwhile). An error undoes this project only (the core's
    savepoint), it waits for the next run and the run reports it as list_err (core/writes.py _purge_area). otr_prune went.
    2.1002.0 (#5491): also the route DELETE /api/trash/lists/<id> (core/writes.py obj_purge); its early delete of a kept
    project (checked there) comes in _OTR_EARLY -- the retention run never sets it."""
    got = otr_hard(c, lid, early=_OTR_EARLY.get())
    if got is None:  # 2.102.0 review F1: restored meanwhile; 2.992.0 (#5635): or kept by law meanwhile
        raise Denied(409)
    icon, files = got
    return [lambda: otr_drop_files(lid, icon, files)]


def otr_err_task(c, tid):
    """A task of a list in the trash comes back only with its list (409 for whoever may restore the list, else 404)."""
    r = c.execute(f"SELECT l.* FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=? AND {trash_sql('l')}", (tid,)).fetchone()
    if r is None:
        return None
    if not otr_can(c, me(), r):
        raise Denied(404)
    return err(tr("This task’s project is in the trash: restore the project"), 409)
