"""2.567.0 A (#4707): the trash of a list's sections and planned sprints, and the one trash view of everything else 2.567.0
moved from the hard delete into a trash (budget rows, templates, key links).

Deleting a section or a planned sprint keeps a copy in list_part_trash (kind, ref_id = its id, snap = the row, held = what
hung on it: the open tasks, for a section also the placements of other lists' tasks in it and the shopping memory) before the
row goes as before (its tasks stay without one). Some seventy readers of sections would need a filter for a deleted_at
column; a copy keeps all of them as they are (like time_wipes, personal/timewipe.py). Restoring puts the row back with the
same id -- so rules, forms and review settings that name it work again -- and hangs back what is still free (a task moved
into another section or sprint meanwhile stays there and is reported in skipped). Tasks of the section that were in the
task trash already keep its name (tasks.trash_section) and find it again on their own restore (tasks/lifecycle.py).

Who: whoever may change the list (as deleting); agents never (the way back stays with people, tests/parity_test.py).
After the trash period files/trashpurge.py (TP_PLAIN) deletes the copies. Not the trash of whole lists (lists/listtrash.py).
2.610.0 (#4762): the copy, the check who may take it back and putting the row back are the core's (core/objparts.py
part_copy / part_copy_take / part_copy_back); what hangs on a section / sprint stays here."""
import json

from flask import jsonify

from ..core.config import app
from ..core.db import bump, db, iso, now_utc
from ..core.i18n import tr
from ..core.objparts import part_copy, part_copy_back, part_copy_take, part_kind
from ..accounts.session import me
from ..accounts.orgroles import user_orgs_full  # 2.609.0 (#3373, review F5)
from ..core.access import Denied, acx_of, list_role, need_list, wr_sql, WRITE_ROLES
from ..core.access import live_sql, trash_sql  # 2.783.0 (#5368): the core's trash filter
from ..tasks.validation import log_changes
from ..collab.comments import user_names
from .listtrash import OTR_TRASH_DAYS
from .sprints import SPR_KIND, spr_dict, spr_row
from .templates import tpl_may_write  # 2.609.0 (#3373, review F5)

LPT_LIST_MAX = 300  # the trash view shows the newest ones
LPT_SECTION, LPT_SPRINT = "section", SPR_KIND  # the kinds of list_part_trash, side objects of the core (2.610.0 #4762)
part_kind(LPT_SECTION, "sections", lock="section-{id}", agent=False, trash_prune=True, copy=True)  # 2.783.0 (#5368): the core's run


def lpt_section_put(c, sid, uid):
    """The copy of section sid with its open tasks, the placements of other lists' tasks in it and its shopping memory."""
    lid = c.execute("SELECT list_id FROM sections WHERE id=?", (sid,)).fetchone()[0]
    held = {"tasks": [r[0] for r in c.execute(f"SELECT id FROM tasks WHERE section_id=? AND {live_sql()} ORDER BY id", (sid,))],
            "links": [[r[0], r[1]] for r in c.execute("SELECT task_id, list_id FROM task_links WHERE section_id=?", (sid,))],
            "shop": [[r[0], r[1]] for r in c.execute("SELECT item, at FROM shop_memory WHERE section_id=?", (sid,))]}
    part_copy(c, LPT_SECTION, sid, lid, held, uid)


def lpt_sprint_put(c, sid, uid):
    """The copy of planned sprint sid with its tasks (and when each was planned into it)."""
    lid = c.execute("SELECT list_id FROM sprints WHERE id=?", (sid,)).fetchone()[0]
    held = {"tasks": [[r[0], r[1]] for r in c.execute("SELECT id, sprint_at FROM tasks WHERE sprint_id=? ORDER BY id", (sid,))]}
    part_copy(c, LPT_SPRINT, sid, lid, held, uid)


def _need_edit(c, lid):
    need_list(c, lid)  # edit rights on its live list, as deleting


@app.post("/api/sections/<int:sid>/restore")
def section_restore(sid):
    """A deleted section comes back with the same id, its limits and its tasks that are still without a section in the list
    -> the section + {moved, skipped} (like POST /api/sections, the undo of the app). 404: not in the trash."""
    c = db()
    moved, skipped = lpt_section_back(c, sid, me())
    from .secundo import secu_add  # 2.809.0 (#5476): a step of the person's undo list
    sec = c.execute("SELECT name, list_id FROM sections WHERE id=?", (sid,)).fetchone()
    secu_add(c, sid, "restore", sec["name"], sec["list_id"])
    bump(c)
    c.commit()
    return jsonify({**dict(c.execute("SELECT * FROM sections WHERE id=?", (sid,)).fetchone()), "moved": moved, "skipped": skipped})


def lpt_section_back(c, sid, uid):
    """2.809.0 (#5476, from section_restore): section sid out of the trash with what still fits -> (moved, skipped) task ids.
    404: not in the trash; the rights: whoever may change its list (_need_edit). The caller bumps and commits."""
    r = part_copy_take(c, LPT_SECTION, sid, uid, _need_edit)
    lid = r["list_id"]
    _, held = part_copy_back(c, LPT_SECTION, r, f"sections:{lid}", fix=lambda c2, snap: _lpt_e2e(c2, lid, snap))
    moved, skipped = [], []
    for tid in held.get("tasks") or []:
        t = c.execute("SELECT list_id, section_id, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
        if not t or t["deleted_at"] or t["list_id"] != lid or t["section_id"] is not None:
            skipped.append(tid)
            continue
        before = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        c.execute("UPDATE tasks SET section_id=?, updated_at=? WHERE id=?", (sid, iso(now_utc()), tid))
        log_changes(c, tid, before)
        moved.append(tid)
    for tid, l2 in held.get("links") or []:
        c.execute("UPDATE task_links SET section_id=? WHERE task_id=? AND list_id=? AND section_id IS NULL", (sid, tid, l2))
    for item, at in held.get("shop") or []:
        c.execute("INSERT INTO shop_memory(list_id,item,section_id,at) VALUES(?,?,?,?) ON CONFLICT (list_id, item) DO NOTHING",
                  (lid, item, sid, at))
    return moved, skipped


def _lpt_e2e(c, lid, snap):
    """#5552: the lock of the project (collab/liste2e.py le2e_guard, as POST /api/sections) also guards the way back: a section
    with a plain name never comes back into a locked project, a ciphertext name never into an open one (409 / 400 {code});
    the copy stays in the trash. The section's own order lock is held (part_copy_back)."""
    from ..collab.liste2e import le2e_guard
    le2e_guard(c, lid, {"section": snap.get("name") or ""})


def lpt_section_purge_list(c, lid):
    """#5552: when the lock of project lid is switched on or off (collab/liste2e.py le2a_finish), the sections in its trash
    go, like its files and the kept texts of deleted comments: their names are of the other state (plain text in a locked
    project, a ciphertext nobody can read in an open one). The tasks in the trash forget their section's name too
    (tasks.trash_section, restoring them would make a section of that name). The caller commits. Returns the copies dropped."""
    n = c.execute("DELETE FROM list_part_trash WHERE list_id=? AND kind=?", (lid, LPT_SECTION)).rowcount
    c.execute("UPDATE tasks SET trash_section=NULL WHERE list_id=? AND trash_section IS NOT NULL", (lid,))
    return n


@app.post("/api/sprints/<int:sid>/restore")
def sprint_restore(sid):
    """A removed planned sprint comes back with the same id (a number taken meanwhile: the next free one) and its tasks that
    are in no sprint now -> {sprint, moved, skipped}. 404: not in the trash."""
    c = db()
    moved, skipped = lpt_sprint_back(c, sid, me())
    from .sprundo import spu_life  # 2.809.0 (#5476): a step of the person's undo list
    sp = spr_row(c, sid)
    spu_life(c, sid, "restore", sp["list_id"], sp["name"])
    bump(c)
    c.commit()
    return jsonify(sprint=spr_dict(c, spr_row(c, sid), me()), moved=moved, skipped=skipped)


def lpt_sprint_back(c, sid, uid):
    """2.809.0 (#5476, from sprint_restore): a removed planned sprint back with its id and the tasks that are in no sprint now
    -> (moved, skipped). 404: not in the trash; the rights: whoever may change its list. The caller bumps and commits."""
    r = part_copy_take(c, LPT_SPRINT, sid, uid, _need_edit)
    lid = r["list_id"]
    _, held = part_copy_back(c, LPT_SPRINT, r, f"sprints:{lid}", fix=_spr_fix)  # like starting / closing (sprints.py)
    moved, skipped = [], []
    for tid, at in held.get("tasks") or []:
        if c.execute(f"UPDATE tasks SET sprint_id=?, sprint_at=? WHERE id=? AND list_id=? AND sprint_id IS NULL AND {live_sql()}",
                     (sid, at or None, tid, lid)).rowcount:  # 2.1115.0 (#5951): sprint_at TIMESTAMPTZ, '' of an older copy = none
            moved.append(tid)
        else:
            skipped.append(tid)
    return moved, skipped


def _spr_fix(c, snap):
    """A sprint comes back planned; its number taken meanwhile -> the next free one."""
    snap["state"] = "planned"
    if c.execute("SELECT 1 FROM sprints WHERE list_id=? AND num=?", (snap["list_id"], snap.get("num"))).fetchone():
        snap["num"] = c.execute("SELECT COALESCE(MAX(num),0)+1 FROM sprints WHERE list_id=?", (snap["list_id"],)).fetchone()[0]


def _writable(c, uid, lid, cache):
    if lid not in cache:
        cache[lid] = list_role(c, lid, uid) in WRITE_ROLES
    return cache[lid]


@app.get("/api/trash/parts")
def lpt_index():
    """The trash view's group "Other deleted items": sections, planned sprints, key links of the lists the person may change,
    their own templates and the rows of the budgets they may change -> {items: [{kind, id, list_id, list, name, deleted_at,
    by_name}], days}. kind: section | sprint | link | template | budget_entry | budget_cat | budget_rec."""
    c, uid = db(), me()
    if acx_of(c, uid).role == "agent":
        raise Denied(404)
    can, items = {}, []
    names = {}

    def lname(lid):
        if lid not in names:
            x = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()
            names[lid] = x[0] if x else ""
        return names[lid]
    # 2.783.0 (#5368): only sections and sprints -- the core's copy trash holds deleted fields and time copies too (their own views)
    for r in c.execute(f"SELECT p.* FROM list_part_trash p JOIN lists l ON l.id=p.list_id WHERE {live_sql('l')} AND p.kind IN (?,?) "
                       f"AND p.list_id IN {wr_sql()} "  # review 2.567: the caller's lists before the LIMIT (not the instance's newest)
                       "ORDER BY p.deleted_at DESC, p.id DESC LIMIT 2000", (LPT_SECTION, LPT_SPRINT, uid, uid)).fetchall():
        if not _writable(c, uid, r["list_id"], can):
            continue
        snap = json.loads(r["snap"] or "{}")
        nm = snap.get("name") or (tr("Sprint {0}", snap.get("num")) if r["kind"] == "sprint" else "")
        items.append({"kind": r["kind"], "id": r["ref_id"], "list_id": r["list_id"], "name": nm, "deleted_at": r["deleted_at"],
                      "deleted_by": r["deleted_by"]})
    for r in c.execute(f"SELECT k.* FROM list_links k JOIN lists l ON l.id=k.list_id WHERE {trash_sql('k')} AND {live_sql('l')} "
                       f"AND k.list_id IN {wr_sql()} "
                       "ORDER BY k.deleted_at DESC LIMIT 2000", (uid, uid)).fetchall():
        if _writable(c, uid, r["list_id"], can):
            items.append({"kind": "link", "id": r["id"], "list_id": r["list_id"], "name": r["title"] or r["url"], "deleted_at": r["deleted_at"],
                          "deleted_by": r["deleted_by"]})
    orgs = user_orgs_full(c, uid)  # 2.609.0 (#3373, review F5): + the organisations' templates whose admin may bring them back
    for r in c.execute("SELECT * FROM templates WHERE deleted_at IS NOT NULL AND "  # 2.905.0 (#5288): owner_id (was user_id), the core's role
                       "((org_id IS NULL AND owner_id=?)" + (f" OR org_id IN ({','.join('?' * len(orgs))})" if orgs else "") + ")",
                       (uid, *orgs)).fetchall():
        if not tpl_may_write(c, r):  # as template_restore: a member's own one made for the organisation is no longer theirs
            continue
        items.append({"kind": "template", "id": r["id"], "list_id": None, "name": r["name"], "deleted_at": r["deleted_at"],
                      "deleted_by": r["deleted_by"]})
    items += _budget_items(c, uid)
    items.sort(key=lambda x: (x["deleted_at"] or "", x["id"]), reverse=True)
    items = items[:LPT_LIST_MAX]
    who = user_names(c, [x["deleted_by"] for x in items])
    for x in items:
        x["list"] = lname(x["list_id"]) if x["list_id"] else ""
        x["by_name"] = who.get(x.pop("deleted_by"), "")
    return jsonify(items=items, days=OTR_TRASH_DAYS)


def _budget_items(c, uid):
    """The rows in the trash of the budgets uid may change (none while the module is off or for an agent / a token)."""
    from ..life.budget import bud_dec, bud_lists, bud_need_on
    try:
        bud_need_on(c, uid)
    except Denied:
        return []
    out = []
    for bl in bud_lists(c, uid):
        if not bl["can_write"]:
            continue
        for kind, table, col in (("budget_entry", "budget_entries", "title"), ("budget_cat", "budget_cats", "name"),
                                 ("budget_rec", "budget_recurring", "title")):
            for r in c.execute(f"SELECT * FROM {table} WHERE list_id=? AND deleted_at IS NOT NULL ORDER BY deleted_at DESC LIMIT 500",
                               (bl["id"],)).fetchall():
                d = bud_dec(c, table, r) if table != "budget_cats" else dict(r)
                out.append({"kind": kind, "id": r["id"], "list_id": r["list_id"], "name": d[col], "deleted_at": r["deleted_at"],
                            "deleted_by": r["deleted_by"]})
    return out
