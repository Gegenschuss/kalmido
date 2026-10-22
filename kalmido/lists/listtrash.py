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
Lists with end-to-end encryption keep the immediate hard delete (lists.list_purge)."""
import time
from datetime import timedelta
from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import bump, db, err, iso, now_utc
from ..core.retention import ret_days
from ..accounts.session import me
from ..core.access import collab_all, Denied, health_hidden, token_lists

OTR_TRASH_DAYS = ret_days("trash")  # 30 like the other trash periods; 2.152.0 (#2165): KALMIDO_TRASH_DAYS moves it
OTR_PRUNE = {"at": 0.0}


def otr_trash(c, lid, uid):
    """Moves list lid (archived, checked by the caller) into the trash: the list and its tasks that are not in the trash yet."""
    t = now_utc()
    ts = iso(t)
    for i in range(1, 60):  # the stamp marks what the restore brings back: never the one of a task trashed in the same second
        if not c.execute("SELECT 1 FROM tasks WHERE list_id=? AND deleted_at=? LIMIT 1", (lid, ts)).fetchone():
            break
        ts = iso(t + timedelta(seconds=i))
    c.execute("UPDATE lists SET deleted_at=?, deleted_by=? WHERE id=?", (ts, uid, lid))
    c.execute("UPDATE tasks SET deleted_at=? WHERE list_id=? AND deleted_at IS NULL", (ts, lid))
    from ..integrations.gitfolder import gf_before_list_delete
    gf_before_list_delete(c, lid)  # 2.33.0 (#934): a folder repository keeps syncing into a live list of its folder
    return ts


def otr_can(c, uid, r):
    """May uid see / restore / delete for good the deleted list row r (see the module docstring)?"""
    from ..agents.core import is_agent
    from ..accounts.orgs import org_role
    if not r or not r["deleted_at"] or r["is_inbox"]:
        return False
    if is_agent(g.user) or (r["life"] in ("health", "budget") and health_hidden(c, uid)):
        return False
    tl = token_lists()
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
    return collab_all() and bool(c.execute("SELECT 1 FROM list_members WHERE list_id=? AND user_id=? AND role='admin'",
                                           (r["id"], uid)).fetchone())


def otr_need(c, lid):
    r = c.execute("SELECT * FROM lists WHERE id=? AND deleted_at IS NOT NULL", (lid,)).fetchone()
    if not otr_can(c, me(), r):
        raise Denied(404)
    return r


def otr_hard(c, lid):
    """Deletes the (deleted) list lid for good with all its tasks. Returns (icon, file paths) to drop after the commit."""
    from ..tasks.tasks import hard_delete
    from .lists import list_purge
    # 2.102.0 review F1: lock the row and look again - a restore committed meanwhile wins (it waits on this lock, then finds nothing)
    r = c.execute("SELECT deleted_at FROM lists WHERE id=? FOR UPDATE", (lid,)).fetchone()
    if not r or not r[0]:
        return None
    files = hard_delete(c, [x[0] for x in c.execute("SELECT id FROM tasks WHERE list_id=?", (lid,))], lists={lid})
    icon, lfiles = list_purge(c, lid, None)  # no task is left to move: list_purge only drops the list row + its files
    return icon, lfiles + files


def otr_drop_files(lid, icon, files):
    from ..accounts.pictures import list_icon_drop_file
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
                         FROM lists l WHERE l.deleted_at IS NOT NULL AND (l.owner_id=? OR l.org_id IN ({oq})
                           OR l.id IN (SELECT list_id FROM list_members WHERE user_id=? AND role='admin'))
                         ORDER BY l.deleted_at DESC, l.id""", (uid, *orgs, uid)).fetchall()
    rows = [r for r in rows if otr_can(c, uid, r)]
    names = user_names(c, [r["deleted_by"] for r in rows])
    return jsonify(lists=[{"id": r["id"], "name": r["name"], "color": r["color"], "org_id": r["org_id"],
                           "deleted_at": r["deleted_at"], "deleted_by": r["deleted_by"], "by_name": names.get(r["deleted_by"], ""),
                           "tasks": r["n"]} for r in rows], days=OTR_TRASH_DAYS)


@app.post("/api/trash/lists/<int:lid>/restore")
def otr_restore(lid):
    """Brings the list back (archived, same organisation / private space) with its tasks, fields, tags, chat."""
    c = db()
    r = otr_need(c, lid)
    # 2.102.0 review F1/F7: only a list still in the trash comes back (not one purged or restored meanwhile)
    if c.execute("UPDATE lists SET deleted_at=NULL, deleted_by=NULL WHERE id=? AND deleted_at=?", (lid, r["deleted_at"])).rowcount != 1:
        raise Denied(404)
    c.execute("UPDATE tasks SET deleted_at=NULL WHERE list_id=? AND deleted_at=?", (lid, r["deleted_at"]))
    if r["org_id"]:
        from ..accounts.orglists import _ol_log
        _ol_log(c, r["org_id"], r, "undelete")
    bump(c)
    c.commit()
    return jsonify(ok=True, id=lid)


@app.delete("/api/trash/lists/<int:lid>")
def otr_delete(lid):
    """Deletes a list in the trash for good (the client asks first)."""
    c = db()
    r = otr_need(c, lid)
    got = otr_hard(c, lid)
    if got is None:  # 2.102.0 review F1: restored meanwhile
        raise Denied(404)
    icon, files = got
    if r["org_id"]:
        from ..accounts.orglists import _ol_log
        _ol_log(c, r["org_id"], r, "purge")
    bump(c)
    c.commit()
    otr_drop_files(lid, icon, files)
    print("list", lid, "deleted for good from the trash by", g.user["username"], flush=True)
    return jsonify(ok=True)


def otr_prune(c, force=False):
    """The watchdog (at most hourly, system context): lists in the trash longer than OTR_TRASH_DAYS go for good."""
    if not force and time.time() - OTR_PRUNE["at"] < 3600:
        return 0
    OTR_PRUNE["at"] = time.time()
    cut = iso(now_utc() - timedelta(days=OTR_TRASH_DAYS))
    n = 0
    for (lid,) in c.execute("SELECT id FROM lists WHERE deleted_at IS NOT NULL AND deleted_at<?", (cut,)).fetchall():
        got = otr_hard(c, lid)
        if got is None:  # 2.102.0 review F1: restored meanwhile
            c.commit()
            continue
        icon, files = got
        c.commit()
        otr_drop_files(lid, icon, files)
        n += 1
    return n


def otr_err_task(c, tid):
    """A task of a list in the trash comes back only with its list (409 for whoever may restore the list, else 404)."""
    r = c.execute("SELECT l.* FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=? AND l.deleted_at IS NOT NULL", (tid,)).fetchone()
    if r is None:
        return None
    if not otr_can(c, me(), r):
        raise Denied(404)
    return err(tr("This task’s project is in the trash: restore the project"), 409)
