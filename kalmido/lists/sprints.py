"""2.60.0 (#343): sprints of a project list -- time boxes with a goal, a burndown and a close-out review.

Off until someone with edit rights switches them on for a project list (lists.sprint_cfg, json {on, weeks, dow, carry}).
Switching on starts sprint 1 (from the next start weekday, today when today is one). At most one sprint of a list is
active; more may be planned. A task belongs to at most one sprint of its OWN list (tasks.sprint_id, NULL = backlog;
sprint_at = when it went in). Moving it to another list clears the link (spr_cleanup, run with ms_cleanup).
Closing writes the review once (sprints.review, the form is in iface / spr_review) and starts the next sprint while sprints
are on; open tasks go along into it or back to the backlog. The watchdog closes an active sprint whose last day is over
(carry decides where open tasks go). Reading = seeing the list (participants count only the tasks they fully see),
changing = edit rights on the list. Agents: the v1 routes below (token list limits apply through list_role) and the events
sprint_started / sprint_closed to the agents of the list (agent_emit drops lists outside agents.list_ids and health lists).
"""
import json
from datetime import date, timedelta
from flask import jsonify, request

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, local_day, local_now, now_utc
from ..accounts.session import me
from ..core.access import Denied, is_project, list_role, need_list, pvis, WRITE_ROLES
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions

SPR_WEEKS = (0, 1, 2)       # 0 = free length (the dates of each sprint are set by hand; the next one keeps the last length)
SPR_FREE_DAYS = 14          # length of a new sprint of a list with a free length and no sprint before
SPR_DAYS_MAX = 92           # longest sprint (days)
SPR_NAME_MAX = 100
SPR_GOAL_MAX = 300
SPR_BULK_MAX = 500          # tasks per assign request
SPR_STATES = ("planned", "active", "closed")
SPR_CFG_DEFAULT = {"on": False, "weeks": 2, "dow": 0, "carry": True}
SPR_STATE_CLOSED_KEEP = 3   # closed sprints per list in /api/state (the task row shows their names)


def spr_cfg(raw):
    """The sprint settings of a list (always a full dict; on False when switched off / never set / unreadable)."""
    try:
        v = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        v = {}
    out = dict(SPR_CFG_DEFAULT)
    if isinstance(v, dict):
        if isinstance(v.get("on"), bool):
            out["on"] = v["on"]
        if v.get("weeks") in SPR_WEEKS and not isinstance(v.get("weeks"), bool):
            out["weeks"] = v["weeks"]
        if isinstance(v.get("dow"), int) and not isinstance(v.get("dow"), bool) and 0 <= v["dow"] <= 6:
            out["dow"] = v["dow"]
        if isinstance(v.get("carry"), bool):
            out["carry"] = v["carry"]
    return out


def spr_today():
    return local_now().date()


def spr_day(v, what):
    try:
        if isinstance(v, str) and len(v) == 10:
            return date.fromisoformat(v)
    except ValueError:
        pass
    raise BadInput(tr("Invalid value: {0}", what))


def spr_title(r, lg=None):
    return r["name"] or tr("Sprint {0}", r["num"], lg=lg)


def spr_review(r):
    try:
        v = json.loads(r["review"]) if r["review"] else None
    except (TypeError, ValueError):
        v = None
    return v if isinstance(v, dict) else None


def spr_row(c, sid):
    return c.execute("SELECT * FROM sprints WHERE id=?", (sid,)).fetchone()


def spr_active(c, lid):
    return c.execute("SELECT * FROM sprints WHERE list_id=? AND state='active' ORDER BY id LIMIT 1", (lid,)).fetchone()


def spr_tasks(c, s, uid=None):
    """The tasks counted in sprint s (no milestones, not deleted): its own tasks, a closed sprint the ones of its review
    (done + moved: the moved ones count as open at its end). With uid: a participant only the tasks they fully see."""
    rv = spr_review(s) if s["state"] == "closed" else None
    if rv is not None:
        ids = [int(x) for x in (rv.get("done") or []) + (rv.get("moved") or []) if isinstance(x, int)][:5000]
        rows = c.execute(f"SELECT * FROM tasks WHERE id IN ({','.join('?' * len(ids))}) AND list_id=? AND deleted_at IS NULL AND ms=0",
                         [*ids, s["list_id"]]).fetchall() if ids else []  # review: a task moved to another list since drops out
        moved = set(rv.get("moved") or [])
        rows = [dict(r, status=0, completed_at=None) if r["id"] in moved else dict(r) for r in rows]
    else:
        rows = [dict(r) for r in c.execute("SELECT * FROM tasks WHERE sprint_id=? AND deleted_at IS NULL AND ms=0 ORDER BY status!=0, sort, id",
                                           (s["id"],))]
    if uid and list_role(c, s["list_id"], uid) == "participant":
        _, wr, _ = pvis(c, uid, s["list_id"])
        rows = [r for r in rows if r["id"] in wr]
    return rows


def spr_pts(r):
    p = r.get("points")
    return p if isinstance(p, int) and not isinstance(p, bool) and p > 0 else 0


def spr_progress(rows):
    done = [r for r in rows if r["status"] != 0]
    return {"done": len(done), "total": len(rows), "percent": round(100 * len(done) / len(rows)) if rows else 0,
            "points_done": sum(spr_pts(r) for r in done), "points_total": sum(spr_pts(r) for r in rows)}


def spr_burn(s, rows, unit="count"):
    """Open work per day from the sprint's first day up to today (at most its last day); the ideal line runs from everything
    on the first day to 0 on the last. unit = count (tasks) or points (story points, tasks without points count 0).
    The same shape as the milestone burndown (projects.ms_report), so the client draws it with the same curve."""
    w = spr_pts if unit == "points" else (lambda r: 1)
    start, end = date.fromisoformat(s["start"]), date.fromisoformat(s["end_day"])
    stop = min(spr_today(), end)
    spans = [(w(r), local_day(r["completed_at"]) if r["status"] != 0 else None) for r in rows]
    total = sum(x for x, _ in spans)
    days, d = [], start
    while d <= stop:
        days.append({"day": d.isoformat(), "open": sum(x for x, z in spans if not (z and z <= d))})
        d += timedelta(days=1)
    ideal = [{"day": start.isoformat(), "open": total}, {"day": end.isoformat(), "open": 0}] if total else []
    return {"start": s["start"], "end": min(stop, end).isoformat() if days else s["start"], "due": s["end_day"],
            "unit": unit, "days": days, "ideal": ideal}


def spr_dict(c, s, uid=None, rows=None):
    rows = spr_tasks(c, s, uid) if rows is None else rows
    rv = spr_review(s)
    if rv and uid and list_role(c, s["list_id"], uid) == "participant":  # a participant: only the ids of tasks they fully see
        _, wr, _ = pvis(c, uid, s["list_id"])
        rv = {**rv, **{k: [i for i in (rv.get(k) or []) if i in wr] for k in ("done", "moved", "added")}}
        # review: the totals from the filtered ids too (the whole sprint's numbers would tell of hidden tasks)
        ids = [i for k in ("done", "moved", "added") for i in rv[k] if isinstance(i, int)]
        pts = {r["id"]: r["points"] or 0 for r in c.execute(
            f"SELECT id, points FROM tasks WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
        rv.update(count_done=len(rv["done"]), count_total=len(rv["done"]) + len(rv["moved"]),
                  points_done=sum(pts.get(i, 0) for i in rv["done"]),
                  points_total=sum(pts.get(i, 0) for i in rv["done"] + rv["moved"]),
                  points_added=sum(pts.get(i, 0) for i in rv["added"]))
    return {"id": s["id"], "list_id": s["list_id"], "num": s["num"], "name": s["name"], "title": spr_title(s),
            "start": s["start"], "end": s["end_day"], "goal": s["goal"], "state": s["state"],
            "closed_at": s["closed_at"], "created_at": s["created_at"], "review": rv, "progress": spr_progress(rows)}


def spr_brief(s):
    """The compact form in /api/state (no counts: the client counts the tasks it has)."""
    return {"id": s["id"], "num": s["num"], "title": spr_title(s), "start": s["start"], "end": s["end_day"],
            "goal": s["goal"], "state": s["state"]}


def spr_of_lists(c, rows):
    """{list id: {"cfg": settings, "sprints": [brief of the active + planned + the last closed sprints]}} for the lists of
    /api/state that have sprints on (lists without sprints get nothing new)."""
    on = {r["id"]: spr_cfg(r["sprint_cfg"]) for r in rows if "sprint_cfg" in r.keys() and r["sprint_cfg"]}
    on = {k: v for k, v in on.items() if v["on"]}
    if not on:
        return {}
    out = {k: {"cfg": v, "sprints": []} for k, v in on.items()}
    closed = {}
    for s in c.execute(f"SELECT * FROM sprints WHERE list_id IN ({','.join('?' * len(on))}) ORDER BY num DESC", list(on)):
        if s["state"] == "closed":
            closed[s["list_id"]] = closed.get(s["list_id"], 0) + 1
            if closed[s["list_id"]] > SPR_STATE_CLOSED_KEEP:
                continue
        out[s["list_id"]]["sprints"].append(spr_brief(s))
    return out


# ---------------------------------------------------------------- windows, start, close
def spr_first_start(dow, today):
    """The next start weekday from today on (today when today is one)."""
    return today + timedelta(days=(dow - today.weekday()) % 7)


def spr_len(c, cfg, lid):
    if cfg["weeks"]:
        return 7 * cfg["weeks"]
    last = c.execute("SELECT start, end_day FROM sprints WHERE list_id=? ORDER BY num DESC LIMIT 1", (lid,)).fetchone()
    if last:
        try:
            return max(1, (date.fromisoformat(last["end_day"]) - date.fromisoformat(last["start"])).days + 1)
        except ValueError:
            pass
    return SPR_FREE_DAYS


def spr_next_window(c, cfg, lid, prev_end=None):
    """(start, end) of the next sprint: right after prev_end (the rhythm stays); a window that would already be over (a list
    idle for weeks) moves to the one around today, starting on the last start weekday."""
    n, today = spr_len(c, cfg, lid), spr_today()
    start = prev_end + timedelta(days=1) if prev_end else spr_first_start(cfg["dow"], today)
    if start + timedelta(days=n - 1) < today:
        start = today - timedelta(days=(today.weekday() - cfg["dow"]) % 7)
    return start, start + timedelta(days=n - 1)


def spr_insert(c, lid, start, end, state, uid, name="", goal=""):
    num = c.execute("SELECT COALESCE(MAX(num),0)+1 FROM sprints WHERE list_id=?", (lid,)).fetchone()[0]
    return insert_id(c, "INSERT INTO sprints(list_id,num,name,start,end_day,goal,state,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
                     (lid, num, name, start.isoformat(), end.isoformat(), goal, state, iso(now_utc()), uid))


def spr_events(c, s, event, extra=None):
    """sprint_started / sprint_closed to the agents of the list (agent_emit drops agents limited to other lists, health
    lists, paused agents and the agent's own actions)."""
    from ..agents.core import agent_emit, list_agents, lst_brief
    aids = list_agents(c, s["list_id"])
    if not aids:
        return
    s = spr_row(c, s["id"])
    for aid in aids:
        if not list_role(c, s["list_id"], aid):
            continue
        d = {"list_id": s["list_id"], "list": lst_brief(c, s["list_id"]), "sprint": spr_dict(c, s, aid)}
        if extra:
            d.update(extra)
        agent_emit(c, aid, event, d)


def spr_start(c, s):
    c.execute("UPDATE sprints SET state='active' WHERE id=?", (s["id"],))
    spr_events(c, s, "sprint_started")


def spr_open_new(c, lid, cfg, uid, prev_end=None):
    """Starts the next sprint of list lid: the earliest planned one, else a new one after prev_end. Returns its id."""
    p = c.execute("SELECT * FROM sprints WHERE list_id=? AND state='planned' ORDER BY start, num LIMIT 1", (lid,)).fetchone()
    if p:
        spr_start(c, p)
        return p["id"]
    start, end = spr_next_window(c, cfg, lid, prev_end)
    nid = spr_insert(c, lid, start, end, "active", uid)
    spr_events(c, spr_row(c, nid), "sprint_started")
    return nid


def spr_close(c, s, target, uid):
    """Closes sprint s (active): the review (done / moved / added, counts and points), its open tasks go to the next sprint
    (target next; started now while sprints are on, else the earliest planned one) or back to the backlog. Returns
    (review, next sprint id or None)."""
    lid = s["list_id"]
    cfg = spr_cfg((c.execute("SELECT sprint_cfg FROM lists WHERE id=?", (lid,)).fetchone() or [""])[0])
    rows = [dict(r) for r in c.execute("SELECT id, status, points, sprint_at FROM tasks WHERE sprint_id=? AND deleted_at IS NULL AND ms=0",
                                       (s["id"],))]
    start = date.fromisoformat(s["start"])
    done = [r for r in rows if r["status"] == 2]
    moved = [r for r in rows if r["status"] == 0]
    added = [r for r in rows if (local_day(r["sprint_at"]) or start) > start]
    nxt = None
    if cfg["on"]:
        try:
            prev_end = date.fromisoformat(s["end_day"])
        except ValueError:
            prev_end = None
        nxt = spr_open_new(c, lid, cfg, uid, prev_end)
    elif target == "next":
        p = c.execute("SELECT id FROM sprints WHERE list_id=? AND state='planned' ORDER BY start, num LIMIT 1", (lid,)).fetchone()
        nxt = p[0] if p else None
    to = nxt if target == "next" else None
    ts = iso(now_utc())
    if moved:
        q = ",".join("?" * len(moved))
        c.execute(f"UPDATE tasks SET sprint_id=?, sprint_at=?, updated_at=? WHERE id IN ({q})",
                  (to, ts if to else None, ts, *[r["id"] for r in moved]))
    rv = {"done": [r["id"] for r in done], "moved": [r["id"] for r in moved], "added": [r["id"] for r in added],
          "count_done": len(done), "count_total": len(rows),
          "points_done": sum(spr_pts(r) for r in done), "points_total": sum(spr_pts(r) for r in rows),
          "points_added": sum(spr_pts(r) for r in added), "target": "next" if to else "backlog", "next_id": to}
    c.execute("UPDATE sprints SET state='closed', review=?, closed_at=? WHERE id=?", (json.dumps(rv), ts, s["id"]))
    spr_events(c, s, "sprint_closed", {"next_sprint_id": nxt})
    return rv, nxt


def spr_tick(c):
    """Watchdog: an active sprint whose last day is over is closed (open tasks along with carry on, else to the backlog) and
    the next one starts; a list with sprints on but none active starts its due planned sprint / a new one."""
    today = spr_today()
    for r in c.execute("SELECT id, sprint_cfg FROM lists WHERE sprint_cfg!='' AND archived=0").fetchall():
        cfg = spr_cfg(r["sprint_cfg"])
        if not cfg["on"]:
            continue
        write_lock(c, f"sprints:{r['id']}")
        a = spr_active(c, r["id"])
        if a and a["end_day"] < today.isoformat():
            spr_close(c, a, "next" if cfg["carry"] else "backlog", None)
        elif not a:
            spr_open_new(c, r["id"], cfg, None)
        else:
            c.rollback()
            continue
        bump(c)
        c.commit()


# ---------------------------------------------------------------- task links (sprint_id of a task)
def spr_target(c, sid, lid):
    """None when a task of list lid may go into sprint sid (same list, not closed), else an error text."""
    if sid is None:
        return None
    r = c.execute("SELECT list_id, state FROM sprints WHERE id=?", (sid,)).fetchone()
    if not r or r["list_id"] != lid or r["state"] == "closed":
        return tr("Not an open sprint of this project")
    return None


def spr_apply(c, f, cur, lid):
    """Task update (lifecycle): checks a new sprint_id (same list, edit rights) and sets sprint_at; a task moved to another
    list leaves its sprint. Returns an error text or None."""
    moved = lid != cur["list_id"]
    if "sprint_id" not in f or f["sprint_id"] == cur["sprint_id"]:  # unchanged (a moved task leaves it below)
        f.pop("sprint_id", None)
        if moved and cur["sprint_id"]:
            f["sprint_id"], f["sprint_at"] = None, None
        return None
    if f["sprint_id"] or not moved:
        if list_role(c, lid) not in WRITE_ROLES:
            raise Denied(403, tr("Only people who may edit the project plan its sprints"))
    e = spr_target(c, f["sprint_id"], lid)
    if e:
        return e
    f["sprint_at"] = iso(now_utc()) if f["sprint_id"] else None
    return None


def spr_cleanup(c):
    """Drops every sprint link that points to a sprint of another list (moved subtasks, bulk moves)."""
    c.execute("""UPDATE tasks SET sprint_id=NULL, sprint_at=NULL WHERE sprint_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sprints s
                 WHERE s.id=tasks.sprint_id AND s.list_id=tasks.list_id)""")


# ---------------------------------------------------------------- routes (web app; the v1 routes call these)
def need_sprint(c, sid, write=False):
    s = spr_row(c, sid)
    if not s:
        raise Denied(404)
    need_list(c, s["list_id"], write=write)
    return s


def spr_need_project(c, lid):
    if not is_project(c, lid):
        raise Denied(409, tr("Switch on progress and status in this project to use sprints"))


def spr_clean_fields(b, cur=None):
    """name / goal / start / end of a body -> column values (BadInput on bad ones)."""
    out = {}
    if "name" in b:
        out["name"] = str(b["name"] or "").strip()[:SPR_NAME_MAX]
    if "goal" in b:
        out["goal"] = str(b["goal"] or "").strip()[:SPR_GOAL_MAX]
    st = spr_day(b["start"], "start") if "start" in b else (date.fromisoformat(cur["start"]) if cur else None)
    en = spr_day(b["end"], "end") if "end" in b else (date.fromisoformat(cur["end_day"]) if cur else None)
    if "start" in b or "end" in b:
        if st is None or en is None or en < st or (en - st).days + 1 > SPR_DAYS_MAX:
            raise BadInput(tr("A sprint runs from its start to its end, at most {0} days", SPR_DAYS_MAX))
        out["start"], out["end_day"] = st.isoformat(), en.isoformat()
    return out


@app.get("/api/lists/<int:lid>/sprints")
def sprints_get(lid):
    """{settings, points_on, sprints: [newest first, with progress], active_id}."""
    c = db()
    need_list(c, lid, write=False)
    r = c.execute("SELECT sprint_cfg, points_on FROM lists WHERE id=?", (lid,)).fetchone()
    rows = c.execute("SELECT * FROM sprints WHERE list_id=? ORDER BY num DESC", (lid,)).fetchall()
    out = [spr_dict(c, s, me()) for s in rows]
    act = next((s["id"] for s in rows if s["state"] == "active"), None)
    return jsonify(settings=spr_cfg(r["sprint_cfg"]), points_on=bool(r["points_on"]), sprints=out, active_id=act)


@app.put("/api/lists/<int:lid>/sprint-settings")
def sprint_settings(lid):
    """{on?, weeks?, dow?, carry?} (edit rights, project lists). Switching on starts sprint 1 when the list has no active one."""
    b = body()
    c = db()
    need_list(c, lid)
    spr_need_project(c, lid)
    write_lock(c, f"sprints:{lid}")
    cur = spr_cfg(c.execute("SELECT sprint_cfg FROM lists WHERE id=?", (lid,)).fetchone()[0])
    new = dict(cur)
    for k in ("on", "carry"):
        if k in b:
            if not isinstance(b[k], bool):
                raise BadInput(tr("Invalid value: {0}", k))
            new[k] = b[k]
    if "weeks" in b:
        if isinstance(b["weeks"], bool) or b["weeks"] not in SPR_WEEKS:
            raise BadInput(tr("Invalid value: {0}", "weeks"))
        new["weeks"] = b["weeks"]
    if "dow" in b:
        if isinstance(b["dow"], bool) or not isinstance(b["dow"], int) or not 0 <= b["dow"] <= 6:
            raise BadInput(tr("Invalid value: {0}", "dow"))
        new["dow"] = b["dow"]
    c.execute("UPDATE lists SET sprint_cfg=? WHERE id=?", (json.dumps(new, separators=(",", ":")), lid))
    started = None
    if new["on"] and not cur["on"] and not spr_active(c, lid):
        started = spr_open_new(c, lid, new, me())
    bump(c)
    c.commit()
    return jsonify(settings=new, started_id=started)


@app.post("/api/lists/<int:lid>/sprints")
def sprint_create(lid):
    """{name?, goal?, start?, end?, tasks?}: a planned sprint (default window right after the last one). tasks: ids of the
    list's open backlog tasks to put in (the undo of a deleted sprint brings them back; others are skipped)."""
    b = body()
    c = db()
    need_list(c, lid)
    spr_need_project(c, lid)
    write_lock(c, f"sprints:{lid}")
    cfg = spr_cfg(c.execute("SELECT sprint_cfg FROM lists WHERE id=?", (lid,)).fetchone()[0])
    if not cfg["on"]:
        return err(tr("Sprints are switched off for this project"), 409)
    last = c.execute("SELECT end_day FROM sprints WHERE list_id=? AND state!='closed' ORDER BY end_day DESC LIMIT 1", (lid,)).fetchone()
    st, en = spr_next_window(c, cfg, lid, date.fromisoformat(last[0]) if last else None)
    f = spr_clean_fields({"start": st.isoformat(), "end": en.isoformat(), **b})
    tids = b.get("tasks") or []
    if not isinstance(tids, list) or len(tids) > SPR_BULK_MAX or any(isinstance(i, bool) or not isinstance(i, int) for i in tids):
        return err(tr("Invalid value: {0}", "tasks"))
    sid = spr_insert(c, lid, date.fromisoformat(f["start"]), date.fromisoformat(f["end_day"]), "planned", me(),
                     f.get("name", ""), f.get("goal", ""))
    moved, skipped = spr_assign_ids(c, lid, tids, sid, only_backlog=True)
    bump(c)
    c.commit()
    return jsonify({**spr_dict(c, spr_row(c, sid), me()), "moved": moved, "skipped": skipped})


@app.get("/api/sprints/<int:sid>")
def sprint_get(sid):
    """One sprint with its tasks (open first) and the burndown (?unit=count|points)."""
    from ..api.v1 import STATUS_NAMES
    c = db()
    s = need_sprint(c, sid)
    unit = request.args.get("unit") or "count"
    if unit not in ("count", "points"):
        return err(tr("Invalid value: {0}", "unit"))
    rows = spr_tasks(c, s, me())
    d = spr_dict(c, s, me(), rows)
    d["tasks"] = [{"id": r["id"], "title": r["title"], "status": STATUS_NAMES.get(r["status"], "open"), "points": r.get("points"),
                   "assignee_id": r["assignee_id"], "completed_at": r["completed_at"]} for r in rows]
    d["burndown"] = spr_burn(s, rows, unit)
    return jsonify(d)


@app.patch("/api/sprints/<int:sid>")
def sprint_update(sid):
    """{name?, goal?, start?, end?}; a closed sprint keeps its dates."""
    b = body()
    c = db()
    s = need_sprint(c, sid, write=True)
    if s["state"] == "closed" and ("start" in b or "end" in b):
        return err(tr("A closed sprint keeps its dates"), 409)
    f = spr_clean_fields(b, s)
    if f:
        c.execute(f"UPDATE sprints SET {','.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), sid))
        bump(c)
    c.commit()
    return jsonify(spr_dict(c, spr_row(c, sid), me()))


@app.delete("/api/sprints/<int:sid>")
def sprint_delete(sid):
    """Removes a planned sprint (its tasks go back to the backlog). Returns the sprint and its task ids: the undo creates it
    again with them (POST /api/lists/<id>/sprints with tasks)."""
    c = db()
    s = need_sprint(c, sid, write=True)
    if s["state"] != "planned":
        return err(tr("Only a planned sprint can be removed"), 409)
    d = spr_dict(c, s, me())
    tids = [r[0] for r in c.execute("SELECT id FROM tasks WHERE sprint_id=?", (sid,))]
    c.execute("UPDATE tasks SET sprint_id=NULL, sprint_at=NULL WHERE sprint_id=?", (sid,))
    c.execute("DELETE FROM sprints WHERE id=?", (sid,))
    bump(c)
    c.commit()
    return jsonify(ok=True, sprint=d, tasks=tids)


@app.post("/api/sprints/<int:sid>/start")
def sprint_start(sid):
    c = db()
    s = need_sprint(c, sid, write=True)
    write_lock(c, f"sprints:{s['list_id']}")
    s = spr_row(c, sid)
    if s["state"] != "planned":
        return err(tr("Only a planned sprint can be started"), 409)
    if spr_active(c, s["list_id"]):
        return err(tr("Another sprint of this project is running: close it first"), 409)
    spr_start(c, s)
    bump(c)
    c.commit()
    return jsonify(spr_dict(c, spr_row(c, sid), me()))


@app.post("/api/sprints/<int:sid>/close")
def sprint_close(sid):
    """{target: next | backlog}: closes the running sprint with its review; open tasks go to the next sprint or the backlog."""
    b = body()
    target = b.get("target") or "next"
    if target not in ("next", "backlog"):
        return err(tr("Invalid value: {0}", "target"))
    c = db()
    s = need_sprint(c, sid, write=True)
    write_lock(c, f"sprints:{s['list_id']}")
    s = spr_row(c, sid)
    if s["state"] != "active":
        return err(tr("Only a running sprint can be closed"), 409)
    _rv, nxt = spr_close(c, s, target, me())
    bump(c)
    c.commit()
    return jsonify(sprint=spr_dict(c, spr_row(c, sid), me()), next=spr_dict(c, spr_row(c, nxt), me()) if nxt else None)


def spr_assign_ids(c, lid, tids, sid, only_backlog=False):
    """Puts the tasks tids of list lid into sprint sid (None = backlog). Returns (changed ids, skipped ids); prev of changed
    ones is not needed here (the route reports it)."""
    moved, skipped = [], []
    ts = iso(now_utc())
    for tid in dict.fromkeys(tids):
        r = c.execute("SELECT list_id, sprint_id, deleted_at, ms FROM tasks WHERE id=?", (tid,)).fetchone()
        if not r or r["deleted_at"] or r["list_id"] != lid or r["ms"] or (only_backlog and r["sprint_id"] is not None):
            skipped.append(tid)
            continue
        if r["sprint_id"] == sid:
            continue
        c.execute("UPDATE tasks SET sprint_id=?, sprint_at=?, updated_at=? WHERE id=?", (sid, ts if sid else None, ts, tid))
        moved.append(tid)
    return moved, skipped


@app.post("/api/lists/<int:lid>/sprints/assign")
def sprints_assign(lid):
    """{ids: [task ids], sprint_id: id | null, _prev?: {task id: sprint id | null}}: several tasks of the list into a sprint
    (or the backlog) at once. Returns prev ({task id: its sprint before}); the undo sends the tasks back one sprint at a time
    (prev grouped). With _prev only the tasks still in the expected sprint change (others are reported as conflicts)."""
    from ..tasks.validation import as_int
    b = body()
    c = db()
    need_list(c, lid)
    ids = b.get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > SPR_BULK_MAX or any(isinstance(i, bool) or not isinstance(i, int) for i in ids):
        return err(tr("Invalid value: {0}", "ids"))
    sid = None if b.get("sprint_id") in (None, 0, "") else as_int(b["sprint_id"], "sprint_id", 1)
    e = spr_target(c, sid, lid)
    if e:
        return err(e)
    prev_in = b.get("_prev") if isinstance(b.get("_prev"), dict) else None
    conflicts, todo = [], []
    q = ",".join("?" * len(ids))
    cur = {r[0]: r[1] for r in c.execute(f"SELECT id, sprint_id FROM tasks WHERE id IN ({q}) AND list_id=?", (*ids, lid))}
    for tid in ids:
        if prev_in is not None and str(tid) in prev_in and cur.get(tid) != prev_in[str(tid)]:
            conflicts.append({"field": "sprint_id", "id": tid, "server": cur.get(tid), "mine": sid})
            continue
        todo.append(tid)
    moved, skipped = spr_assign_ids(c, lid, todo, sid)
    bump(c)
    c.commit()
    return jsonify(ok=True, moved=moved, skipped=skipped, prev={str(t): cur.get(t) for t in moved}, conflicts=conflicts)


# ---------------------------------------------------------------- the token API (scopes: reads read, changes write)
from ..api.common import v1_args, v1_call, v1_json, v1_view  # noqa: E402
from ..core.errors import UnknownFields  # noqa: E402


@app.get("/api/v1/lists/<int:lid>/sprints")
@v1_view
def v1_sprints(lid):
    v1_args(())
    d = v1_call(sprints_get, lid)
    return jsonify(data=d["sprints"], settings=d["settings"], points_on=d["points_on"], active_id=d["active_id"], next_cursor=None)


@app.get("/api/v1/sprints/<int:sid>")
@v1_view
def v1_sprint(sid):
    v1_args(("unit",))
    return jsonify(v1_call(sprint_get, sid))


@app.post("/api/v1/lists/<int:lid>/sprints/assign")
@v1_view
def v1_sprints_assign(lid):
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("ids", "sprint_id"))
    if unknown:
        raise UnknownFields(unknown)
    return jsonify(v1_call(sprints_assign, lid, body=b))


def spr_spec(paths, schemas, op, ok, errs, ref, pid):
    """2.60.0 (#343) additions to the OpenAPI document."""
    L, W = "Lists", "write"
    i, s_ = {"type": "integer"}, {"type": "string"}
    schemas["Sprint"] = {"type": "object", "description": "A sprint of a project list (time box). state: planned | active | closed; "
                         "review (closed sprints): done / moved / added task ids, count_done, count_total, points_done, points_total, "
                         "points_added, target, next_id.",
                         "properties": {"id": i, "list_id": i, "num": i, "name": s_, "title": s_, "start": {"type": "string", "format": "date"},
                                        "end": {"type": "string", "format": "date"}, "goal": s_, "state": {"type": "string", "enum": list(SPR_STATES)},
                                        "closed_at": {"type": ["string", "null"]}, "review": {"type": ["object", "null"]},
                                        "progress": {"type": "object"}, "tasks": {"type": "array", "items": {"type": "object"}},
                                        "burndown": {"type": "object"}}}
    schemas["SprintPage"] = {"type": "object", "properties": {"data": {"type": "array", "items": ref("Sprint")}, "settings": {"type": "object"},
                                                              "points_on": {"type": "boolean"}, "active_id": {"type": ["integer", "null"]},
                                                              "next_cursor": {"type": ["string", "null"]}}}
    schemas["SprintAssigned"] = {"type": "object", "properties": {"ok": {"type": "boolean"}, "moved": {"type": "array", "items": i},
                                                                  "skipped": {"type": "array", "items": i}, "prev": {"type": "object"},
                                                                  "conflicts": {"type": "array", "items": {"type": "object"}}}}
    paths["/lists/{id}/sprints"] = {"get": op("Sprints of a project list (newest first, with progress) and its sprint settings", L,
                                              ok(ref("SprintPage")) | errs("404"), [pid("id", "List id")])}
    paths["/sprints/{id}"] = {"get": op("One sprint with its tasks and burndown (unit=count or points)", L, ok(ref("Sprint")) | errs("400", "404"),
                                        [pid("id", "Sprint id"), {"name": "unit", "in": "query", "required": False, "description": "count | points",
                                                                  "schema": {"type": "string", "enum": ["count", "points"]}}])}
    paths["/lists/{id}/sprints/assign"] = {"post": op("Put tasks of the list into a sprint (sprint_id) or back to the backlog (sprint_id null)", L,
                                                      ok(ref("SprintAssigned")) | errs("400", "403", "404"), [pid("id", "List id")], scope=W,
                                                      body={"type": "object", "required": ["ids"], "properties": {
                                                          "ids": {"type": "array", "items": i}, "sprint_id": {"type": ["integer", "null"]}}})}


SPR_NAMES = (N_("Sprint {0}"),)  # the default name (translated in the client too)
