"""2.273.0 B (#3042): what a move of a task ends, remembered so that moving it back brings it back.

A task moved to another list (or indented / outdented) can lose what the target cannot carry: who comes along (task_people),
the assignee, the group, the milestone, the sprint, list tags that the target lacks, its "also in" links (the kalmido_ml_prune
trigger) and subtasks in lists the mover may not move out of (detached, parent_id NULL). tmm_snap reads that before the write,
tmm_after compares afterwards and keeps what ended as one space_moves row (kind 'task', detail = JSON) and returns the counts
for the answer ("move_ended"); tmm_restore runs when the task goes back to where it came from (the undo step or a move back
by hand) within TMM_KEEP_H hours and puts back what is still valid there (people with access, an open sprint / milestone of
that list, links into lists of the same workspace, detached subtasks that are still top level in their list).
"""
import json
from datetime import timedelta

from flask import g, has_request_context

from ..core.access import list_people, list_role, ov_role, WRITE_ROLES
from ..core.db import iso, now_utc, parse_iso
from ..core.pg import insert_id, st_ids
from ..lists.groups import grp_shares_of_list
from ..tasks.validation import descendants

TMM_KEEP_H = 24  # how long a move back restores (the undo window of the other moves)


def _wr_role(c, lid):
    """2.273.0 F1 (#3042): the role of the person making the request in list lid (None without one: restore nothing there)."""
    if not has_request_context() or not getattr(g, "user", None):
        return None
    return list_role(c, lid)


def _ids(c, tid):
    return [tid] + descendants(c, tid)


def tmm_snap(c, tid):
    """Before a move / indent of tid: the rows of tid and its subtasks, who comes along, the list tags and the links."""
    ids = _ids(c, tid)
    rows = {r["id"]: dict(r) for r in c.execute(
        """SELECT id, parent_id, list_id, assignee_id, assignee_group_id, milestone_id, sprint_id FROM tasks
           WHERE id = ANY(CAST(? AS BIGINT[]))""", (st_ids(ids),))}
    people = {}
    for r in c.execute("SELECT task_id, user_id FROM task_people WHERE task_id = ANY(CAST(? AS BIGINT[]))", (st_ids(ids),)):
        people.setdefault(r[0], set()).add(r[1])
    ltags = {}
    for r in c.execute("""SELECT k.task_id, lt.name FROM task_list_tags k JOIN list_tags lt ON lt.id=k.tag_id
                          WHERE k.task_id = ANY(CAST(? AS BIGINT[]))""", (st_ids(ids),)):
        ltags.setdefault(r[0], set()).add(r[1])
    links = [dict(r) for r in c.execute("SELECT list_id, section_id, sort FROM task_links WHERE task_id=?", (tid,))]
    return {"rows": rows, "people": people, "ltags": ltags, "links": links}


def tmm_after(c, tid, snap, uid=None, skip=()):
    """After the move: what ended (kept for a move back) -> counts {people, links, subtasks, assignee, group, milestone,
    sprint, ltags} (only the ones above 0), {} when nothing ended. skip = fields of tid the request set itself (not lost)."""
    old = snap["rows"]
    ids = list(old)
    now = {r["id"]: dict(r) for r in c.execute(
        """SELECT id, parent_id, list_id, assignee_id, assignee_group_id, milestone_id, sprint_id FROM tasks
           WHERE id = ANY(CAST(? AS BIGINT[]))""", (st_ids(ids),))}
    root_o, root_n = old.get(tid), now.get(tid)
    if not root_o or not root_n:
        return {}
    d = {"from": [root_o["list_id"], root_o["parent_id"]], "to": [root_n["list_id"], root_n["parent_id"]],
         "people": [], "links": [], "detached": [], "fields": {}, "ltags": {}}
    have = {}
    for r in c.execute("SELECT task_id, user_id FROM task_people WHERE task_id = ANY(CAST(? AS BIGINT[]))", (st_ids(ids),)):
        have.setdefault(r[0], set()).add(r[1])
    for t, us in snap["people"].items():
        for u in sorted(us - have.get(t, set())):
            d["people"].append([t, u])
    keep = {r[0] for r in c.execute("SELECT list_id FROM task_links WHERE task_id=?", (tid,))}
    d["links"] = [x for x in snap["links"] if x["list_id"] not in keep]
    for t, o in old.items():
        n = now.get(t)
        if not n:
            continue
        if t != tid and o["parent_id"] and not n["parent_id"]:
            d["detached"].append([t, o["parent_id"], n["list_id"]])
        ch = {k: o[k] for k in ("assignee_id", "assignee_group_id", "milestone_id", "sprint_id")
              if o[k] and not n[k] and not (t == tid and k in skip)}
        if ch:
            d["fields"][str(t)] = ch
    tags = {}
    for r in c.execute("""SELECT k.task_id, lt.name FROM task_list_tags k JOIN list_tags lt ON lt.id=k.tag_id
                          WHERE k.task_id = ANY(CAST(? AS BIGINT[]))""", (st_ids(ids),)):
        tags.setdefault(r[0], set()).add(r[1].casefold())
    for t, ns in ({} if "ltags" in skip else snap["ltags"]).items():
        gone = sorted(x for x in ns if x.casefold() not in tags.get(t, set()))
        if gone:
            d["ltags"][str(t)] = gone
    fl = [v for x in d["fields"].values() for v in x]
    out = {"people": len(d["people"]), "links": len(d["links"]), "subtasks": len(d["detached"]),
           "assignee": fl.count("assignee_id"), "group": fl.count("assignee_group_id"), "milestone": fl.count("milestone_id"),
           "sprint": fl.count("sprint_id"), "ltags": sum(len(x) for x in d["ltags"].values())}
    out = {k: v for k, v in out.items() if v}
    if not out:
        return {}
    orgs = [r[0] if r else None for r in (c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()
                                            for lid in (root_o["list_id"], root_n["list_id"]))]
    insert_id(c, "INSERT INTO space_moves(kind,obj_id,from_org,to_org,by_id,at,detail) VALUES('task',?,?,?,?,?,?)",
              (tid, orgs[0], orgs[1], uid, iso(now_utc()), json.dumps(d, separators=(",", ":"))))
    return out


def tmm_restore(c, tid, prev, skip=()):
    """After a move / outdent of tid that left (list, parent) prev: when the newest memo of tid is the move from where the task
    is now to prev, younger than TMM_KEEP_H, put back what ended and is still valid. skip = task fields the same request set
    (they win). Returns counts like tmm_after ({} = nothing)."""
    m = c.execute("SELECT id, at, detail FROM space_moves WHERE kind='task' AND obj_id=? ORDER BY id DESC LIMIT 1", (tid,)).fetchone()
    t = c.execute("SELECT list_id, parent_id FROM tasks WHERE id=?", (tid,)).fetchone()
    if not m or not t:
        return {}
    try:
        d = json.loads(m["detail"])
        young = parse_iso(m["at"]) > now_utc() - timedelta(hours=TMM_KEEP_H)
    except (TypeError, ValueError):
        return {}
    if not young or d.get("restored") or d.get("from") != [t["list_id"], t["parent_id"]] or d.get("to") != list(prev):
        return {}
    lid = t["list_id"]
    people, out = list_people(c, lid), {}
    sub = set(_ids(c, tid))

    def n(k):
        out[k] = out.get(k, 0) + 1
    for x, u in d.get("people") or []:
        if x in sub and u in people and c.execute("SELECT 1 FROM tasks WHERE id=? AND list_id=?", (x, lid)).fetchone():
            c.execute("INSERT INTO task_people(task_id,user_id) VALUES(?,?) ON CONFLICT DO NOTHING", (x, u))
            n("people")
    if not t["parent_id"]:
        org = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
        for k in d.get("links") or []:
            x = c.execute("SELECT org_id, archived, deleted_at FROM lists WHERE id=?", (k["list_id"],)).fetchone()
            if not x or k["list_id"] == lid or x["org_id"] != org or x["archived"] or x["deleted_at"]:
                continue
            if _wr_role(c, k["list_id"]) not in WRITE_ROLES:  # 2.273.0 F1 (#3042): only where the mover may link (ml_check)
                continue
            sid = k.get("section_id")
            if sid and not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (sid, k["list_id"])).fetchone():
                sid = None
            c.execute("""INSERT INTO task_links(task_id, list_id, section_id, sort, org_id, added_by, created_at) VALUES(?,?,?,?,?,?,?)
                         ON CONFLICT (task_id, list_id) DO NOTHING""",
                      (tid, k["list_id"], sid, float(k.get("sort") or 0), org, None, iso(now_utc())))
            n("links")
    for x, p, xl in d.get("detached") or []:  # still top level in the list it stayed in, and no links of its own by now
        r = c.execute("SELECT parent_id, list_id, deleted_at FROM tasks WHERE id=?", (x,)).fetchone()
        if r and not r["parent_id"] and r["list_id"] == xl and not r["deleted_at"] and p in sub \
                and _wr_role(c, xl) in WRITE_ROLES \
                and not c.execute("SELECT 1 FROM task_links WHERE task_id=?", (x,)).fetchone():  # 2.273.0 (#3042, Fable): only where the mover may write
            c.execute("UPDATE tasks SET parent_id=? WHERE id=?", (p, x))
            n("subtasks")
    for x, ch in (d.get("fields") or {}).items():
        x = int(x)
        r = c.execute("SELECT list_id, assignee_id, assignee_group_id, milestone_id, sprint_id FROM tasks WHERE id=?", (x,)).fetchone()
        if not r or r["list_id"] != lid or x not in sub:
            continue
        put = {}
        if ch.get("assignee_id") and not r["assignee_id"] and not r["assignee_group_id"] and ch["assignee_id"] in people:
            put["assignee_id"] = ch["assignee_id"]
        if ch.get("assignee_group_id") and not r["assignee_group_id"] and not r["assignee_id"] and not put:
            if ch["assignee_group_id"] in {g[0] for g in grp_shares_of_list(c, lid)}:
                put["assignee_group_id"] = ch["assignee_group_id"]
        if ch.get("milestone_id") and not r["milestone_id"] and c.execute(
                "SELECT 1 FROM tasks WHERE id=? AND ms=1 AND list_id=? AND deleted_at IS NULL", (ch["milestone_id"], lid)).fetchone():
            put["milestone_id"] = ch["milestone_id"]
        if ch.get("sprint_id") and not r["sprint_id"] and c.execute(
                "SELECT 1 FROM sprints WHERE id=? AND list_id=? AND state!='closed'", (ch["sprint_id"], lid)).fetchone():
            put["sprint_id"], put["sprint_at"] = ch["sprint_id"], iso(now_utc())
        if x == tid:
            put = {k: v for k, v in put.items() if k not in skip and not (k == "sprint_at" and "sprint_id" in skip)}
        if put:
            c.execute(f"UPDATE tasks SET {','.join(k + '=?' for k in put)} WHERE id=?", [*put.values(), x])
            for k in put:
                if k != "sprint_at":
                    n({"assignee_id": "assignee", "assignee_group_id": "group", "milestone_id": "milestone", "sprint_id": "sprint"}[k])
    if "ltags" not in skip:
        for x, names in (d.get("ltags") or {}).items():
            x = int(x)
            if x not in sub or not c.execute("SELECT 1 FROM tasks WHERE id=? AND list_id=?", (x, lid)).fetchone():
                continue
            for nm in names:
                r = c.execute("SELECT id FROM list_tags WHERE list_id=? AND lower(name)=lower(?)", (lid, nm)).fetchone()
                if r:
                    c.execute("INSERT INTO task_list_tags(task_id,tag_id) VALUES(?,?) ON CONFLICT DO NOTHING", (x, r[0]))
                    n("ltags")
    d["restored"] = iso(now_utc())
    c.execute("UPDATE space_moves SET detail=? WHERE id=?", (json.dumps(d, separators=(",", ":")), m["id"]))
    return out


# ---- 2.273.0 B (#3042): a list into another workspace (list_org_set + ov_private_reset) ends its client, its opening to the
# organisation (with the tasks assigned to readers) and the "also in" links across the boundary; moving it back within
# TMM_KEEP_H hours (the list dialog's undo) brings that back where it fits.
def lmm_snap(c, lid):
    l = c.execute("SELECT org_id, client_id, org_visibility, org_edit FROM lists WHERE id=?", (lid,)).fetchone()
    if not l:
        return None
    links = [dict(r) for r in c.execute("""SELECT task_id, list_id, section_id, sort FROM task_links WHERE list_id=?
                                           OR task_id IN (SELECT id FROM tasks WHERE list_id=?)""", (lid, lid))]
    assign = [list(r) for r in c.execute("""SELECT id, assignee_id FROM tasks WHERE list_id=? AND assignee_id IS NOT NULL
                                            AND assignee_id NOT IN (SELECT owner_id FROM lists WHERE id=?)
                                            AND assignee_id NOT IN (SELECT user_id FROM list_members WHERE list_id=?)""", (lid, lid, lid))]
    # 2.401.0 (#2924): the clients of its tasks' customer reports (lists/lmove.py lmv_follow unbinds one of another workspace)
    tcl = [list(r) for r in c.execute("""SELECT id, client_id FROM portal_tickets WHERE client_id IS NOT NULL
                                         AND task_id IN (SELECT id FROM tasks WHERE list_id=?)""", (lid,))]
    return {"org": l["org_id"], "client": l["client_id"], "vis": [l["org_visibility"] or "", l["org_edit"] or 0], "links": links, "assign": assign,
            "tclients": tcl}


def lmm_after(c, lid, snap, uid=None):
    """After the workspace change: what ended (kept) -> counts {client, visibility, links, assignees}, {} = nothing."""
    l = c.execute("SELECT org_id, client_id, org_visibility, org_edit FROM lists WHERE id=?", (lid,)).fetchone()
    if not snap or not l or (l["org_id"] or None) == (snap["org"] or None):
        return {}
    have = {(r[0], r[1]) for r in c.execute("""SELECT task_id, list_id FROM task_links WHERE list_id=?
                                               OR task_id IN (SELECT id FROM tasks WHERE list_id=?)""", (lid, lid))}
    d = {"from": snap["org"], "to": l["org_id"], "client": snap["client"] if snap["client"] and not l["client_id"] else None,
         "vis": snap["vis"] if snap["vis"][0] and not l["org_visibility"] else None,
         "links": [k for k in snap["links"] if (k["task_id"], k["list_id"]) not in have], "assign": []}
    for tid, a in snap["assign"]:
        if not c.execute("SELECT assignee_id FROM tasks WHERE id=?", (tid,)).fetchone()[0]:
            d["assign"].append([tid, a])
    d["tclients"] = [[p, k] for p, k in snap.get("tclients") or []
                     if c.execute("SELECT 1 FROM portal_tickets WHERE id=? AND client_id IS NULL", (p,)).fetchone()]  # 2.401.0 (#2924)
    out = {k: v for k, v in (("client", 1 if d["client"] else 0), ("visibility", 1 if d["vis"] else 0), ("links", len(d["links"])),
                             ("assignees", len(d["assign"])), ("tclients", len(d["tclients"]))) if v}
    if out:
        insert_id(c, "INSERT INTO space_moves(kind,obj_id,from_org,to_org,by_id,at,detail) VALUES('list',?,?,?,?,?,?)",
                  (lid, snap["org"], l["org_id"], uid, iso(now_utc()), json.dumps(d, separators=(",", ":"))))
    return out


def lmm_restore(c, lid, prev):
    """The list went from workspace prev back to the one of its newest memo (younger than TMM_KEEP_H): client, opening,
    readers' assignments and links back where they fit. -> counts like lmm_after."""
    m = c.execute("SELECT id, at, detail FROM space_moves WHERE kind='list' AND obj_id=? ORDER BY id DESC LIMIT 1", (lid,)).fetchone()
    l = c.execute("SELECT org_id, client_id, org_visibility FROM lists WHERE id=?", (lid,)).fetchone()
    if not m or not l:
        return {}
    try:
        d = json.loads(m["detail"])
        young = parse_iso(m["at"]) > now_utc() - timedelta(hours=TMM_KEEP_H)
    except (TypeError, ValueError):
        return {}
    org = l["org_id"] or None
    if not young or d.get("restored") or (d.get("from") or None) != org or (d.get("to") or None) != (prev or None):
        return {}
    out = {}
    if d.get("client") and not l["client_id"] and c.execute("SELECT 1 FROM clients WHERE id=? AND org_id IS NOT DISTINCT FROM ?",
                                                             (d["client"], org)).fetchone():
        c.execute("UPDATE lists SET client_id=? WHERE id=?", (d["client"], lid))
        out["client"] = 1
    if d.get("vis") and org and not l["org_visibility"]:
        c.execute("UPDATE lists SET org_visibility=?, org_edit=? WHERE id=?", (d["vis"][0], d["vis"][1], lid))
        out["visibility"] = 1
        for tid, a in d.get("assign") or []:
            # 2.273.0 F1 (#3042): only who may be assigned there now (check_assignee: list people or org_edit reader)
            if a not in list_people(c, lid) and ov_role(c, lid, a) != "edit":
                continue
            if c.execute("UPDATE tasks SET assignee_id=? WHERE id=? AND list_id=? AND assignee_id IS NULL AND assignee_group_id IS NULL",
                         (a, tid, lid)).rowcount:
                out["assignees"] = out.get("assignees", 0) + 1
    for k in d.get("links") or []:
        t = c.execute("SELECT t.parent_id, t.deleted_at, o.org_id FROM tasks t JOIN lists o ON o.id=t.list_id WHERE t.id=?", (k["task_id"],)).fetchone()
        x = c.execute("SELECT org_id, archived, deleted_at FROM lists WHERE id=?", (k["list_id"],)).fetchone()
        if not t or not x or t["parent_id"] or t["deleted_at"] or x["archived"] or x["deleted_at"] or (t["org_id"] or None) != (x["org_id"] or None):
            continue
        if _wr_role(c, k["list_id"]) not in WRITE_ROLES:  # 2.273.0 F1 (#3042): as in tmm_restore
            continue
        sid = k.get("section_id")
        if sid and not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (sid, k["list_id"])).fetchone():
            sid = None
        if c.execute("""INSERT INTO task_links(task_id, list_id, section_id, sort, org_id, added_by, created_at) VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT (task_id, list_id) DO NOTHING""",
                     (k["task_id"], k["list_id"], sid, float(k.get("sort") or 0), x["org_id"], None, iso(now_utc()))).rowcount:
            out["links"] = out.get("links", 0) + 1
    for p, k in d.get("tclients") or []:  # 2.401.0 (#2924): a customer report's client, where it fits the report's space again
        if c.execute("""UPDATE portal_tickets SET client_id=? WHERE id=? AND client_id IS NULL AND task_id IN (SELECT id FROM tasks WHERE list_id=?)
                        AND org_id IS NOT DISTINCT FROM (SELECT org_id FROM clients WHERE id=?)""", (k, p, lid, k)).rowcount:
            out["tclients"] = out.get("tclients", 0) + 1
    d["restored"] = iso(now_utc())
    c.execute("UPDATE space_moves SET detail=? WHERE id=?", (json.dumps(d, separators=(",", ":")), m["id"]))
    return out
