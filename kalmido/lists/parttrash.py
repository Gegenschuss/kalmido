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
After the trash period files/trashpurge.py (TP_PLAIN) deletes the copies. Not the trash of whole lists (lists/listtrash.py)."""
import json
import re

from flask import jsonify

from ..core.config import app
from ..core.db import bump, db, iso, now_utc
from ..core.i18n import tr
from ..core.pg import write_lock
from ..accounts.session import me
from ..core.access import Denied, acx_of, list_role, need_list, wr_sql, WRITE_ROLES
from ..tasks.validation import log_changes
from ..collab.comments import user_names
from .listtrash import OTR_TRASH_DAYS
from .sprints import spr_dict, spr_row

LPT_COL = re.compile(r"^[a-z_][a-z0-9_]*$")
LPT_LIST_MAX = 300  # the trash view shows the newest ones


def lpt_put(c, lid, kind, ref_id, snap, held, uid):
    """Keeps the copy of a section / sprint (the caller deletes the row afterwards, in the same transaction)."""
    c.execute("INSERT INTO list_part_trash(list_id,kind,ref_id,snap,held,deleted_by,deleted_at) VALUES(?,?,?,?,?,?,?)",
              (lid, kind, int(ref_id), json.dumps(dict(snap), ensure_ascii=False, default=str),
               json.dumps(held, ensure_ascii=False, default=str), uid, iso(now_utc())))


def lpt_section_put(c, sid, uid):
    """The copy of section sid with its open tasks, the placements of other lists' tasks in it and its shopping memory."""
    row = c.execute("SELECT * FROM sections WHERE id=?", (sid,)).fetchone()
    held = {"tasks": [r[0] for r in c.execute("SELECT id FROM tasks WHERE section_id=? AND deleted_at IS NULL ORDER BY id", (sid,))],
            "links": [[r[0], r[1]] for r in c.execute("SELECT task_id, list_id FROM task_links WHERE section_id=?", (sid,))],
            "shop": [[r[0], r[1]] for r in c.execute("SELECT item, at FROM shop_memory WHERE section_id=?", (sid,))]}
    lpt_put(c, row["list_id"], "section", sid, row, held, uid)


def lpt_sprint_put(c, sid, uid):
    """The copy of planned sprint sid with its tasks (and when each was planned into it)."""
    row = c.execute("SELECT * FROM sprints WHERE id=?", (sid,)).fetchone()
    held = {"tasks": [[r[0], r[1]] for r in c.execute("SELECT id, sprint_at FROM tasks WHERE sprint_id=? ORDER BY id", (sid,))]}
    lpt_put(c, row["list_id"], "sprint", sid, row, held, uid)


def lpt_need(c, kind, ref_id):
    """The newest copy of kind / ref_id the current person may restore (edit rights on its live list); 404 otherwise."""
    if acx_of(c, me()).role == "agent":  # agents never restore (core/access.py: the account kind, through its token too)
        raise Denied(404)
    r = c.execute("SELECT * FROM list_part_trash WHERE kind=? AND ref_id=? ORDER BY id DESC LIMIT 1", (kind, int(ref_id))).fetchone()
    if not r:
        raise Denied(404)
    need_list(c, r["list_id"])
    return r


def lpt_insert(c, table, snap):
    cols = [k for k in snap if LPT_COL.match(k)]
    c.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [snap[k] for k in cols])


@app.post("/api/sections/<int:sid>/restore")
def section_restore(sid):
    """A deleted section comes back with the same id, its limits and its tasks that are still without a section in the list
    -> the section + {moved, skipped} (like POST /api/sections, the undo of the app). 404: not in the trash."""
    c = db()
    r = lpt_need(c, "section", sid)
    lid = r["list_id"]
    write_lock(c, f"sections:{lid}")  # like the order of the sections (sections.py)
    if c.execute("SELECT 1 FROM sections WHERE id=?", (sid,)).fetchone() or \
            not c.execute("SELECT 1 FROM list_part_trash WHERE id=?", (r["id"],)).fetchone():
        raise Denied(404)  # restored meanwhile
    snap, held = json.loads(r["snap"] or "{}"), json.loads(r["held"] or "{}")
    snap.update(id=sid, list_id=lid)
    lpt_insert(c, "sections", snap)
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
    c.execute("DELETE FROM list_part_trash WHERE id=?", (r["id"],))
    bump(c)
    c.commit()
    return jsonify({**dict(c.execute("SELECT * FROM sections WHERE id=?", (sid,)).fetchone()), "moved": moved, "skipped": skipped})


@app.post("/api/sprints/<int:sid>/restore")
def sprint_restore(sid):
    """A removed planned sprint comes back with the same id (a number taken meanwhile: the next free one) and its tasks that
    are in no sprint now -> {sprint, moved, skipped}. 404: not in the trash."""
    c = db()
    r = lpt_need(c, "sprint", sid)
    lid = r["list_id"]
    write_lock(c, f"sprints:{lid}")  # like starting / closing (sprints.py)
    if spr_row(c, sid) or not c.execute("SELECT 1 FROM list_part_trash WHERE id=?", (r["id"],)).fetchone():
        raise Denied(404)
    snap, held = json.loads(r["snap"] or "{}"), json.loads(r["held"] or "{}")
    snap.update(id=sid, list_id=lid, state="planned")
    if c.execute("SELECT 1 FROM sprints WHERE list_id=? AND num=?", (lid, snap.get("num"))).fetchone():
        snap["num"] = c.execute("SELECT COALESCE(MAX(num),0)+1 FROM sprints WHERE list_id=?", (lid,)).fetchone()[0]
    lpt_insert(c, "sprints", snap)
    moved, skipped = [], []
    for tid, at in held.get("tasks") or []:
        if c.execute("UPDATE tasks SET sprint_id=?, sprint_at=? WHERE id=? AND list_id=? AND sprint_id IS NULL AND deleted_at IS NULL",
                     (sid, at, tid, lid)).rowcount:
            moved.append(tid)
        else:
            skipped.append(tid)
    c.execute("DELETE FROM list_part_trash WHERE id=?", (r["id"],))
    bump(c)
    c.commit()
    return jsonify(sprint=spr_dict(c, spr_row(c, sid), me()), moved=moved, skipped=skipped)


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
    for r in c.execute("SELECT p.* FROM list_part_trash p JOIN lists l ON l.id=p.list_id WHERE l.deleted_at IS NULL "
                       f"AND p.list_id IN {wr_sql()} "  # review 2.567: the caller's lists before the LIMIT (not the instance's newest)
                       "ORDER BY p.deleted_at DESC, p.id DESC LIMIT 2000", (uid, uid)).fetchall():
        if not _writable(c, uid, r["list_id"], can):
            continue
        snap = json.loads(r["snap"] or "{}")
        nm = snap.get("name") or (tr("Sprint {0}", snap.get("num")) if r["kind"] == "sprint" else "")
        items.append({"kind": r["kind"], "id": r["ref_id"], "list_id": r["list_id"], "name": nm, "deleted_at": r["deleted_at"],
                      "deleted_by": r["deleted_by"]})
    for r in c.execute("SELECT k.* FROM list_links k JOIN lists l ON l.id=k.list_id WHERE k.deleted_at IS NOT NULL AND l.deleted_at IS NULL "
                       f"AND k.list_id IN {wr_sql()} "
                       "ORDER BY k.deleted_at DESC LIMIT 2000", (uid, uid)).fetchall():
        if _writable(c, uid, r["list_id"], can):
            items.append({"kind": "link", "id": r["id"], "list_id": r["list_id"], "name": r["title"] or r["url"], "deleted_at": r["deleted_at"],
                          "deleted_by": r["deleted_by"]})
    for r in c.execute("SELECT id, name, deleted_at, deleted_by FROM templates WHERE user_id=? AND deleted_at IS NOT NULL", (uid,)).fetchall():
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
