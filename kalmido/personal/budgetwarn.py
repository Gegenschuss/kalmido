"""2.555.0 (#4570): the budget warning of projects and tasks (decision of 04.11.2026: only a display, no lock).

The tracked hours of a project (all its finished entries) or of a task (its branch: the task + its subtasks, like the task
detail, personal/timetrack.py task_budget) against "Budget h" (the number field, summed once per branch, budget_parents):
from 80 % the level is "warn", from 100 % "over" (bw_level, the same rounding as the task detail and the client's budget).
The project page (lists/projects.py overview_build: time.budget_level / budget_pct) and the task's time entries
(GET /api/time/entries?task_id=: budget.level) send it, so the web app and the agent API count the same.

Saving / stopping a time entry (personal/timetrack.py: start, stop, create, change, delete) calls bw_check: a threshold
crossed for the first time tells the project's people once (News kind "budgetwarn" + push, the row "timebudget" of the
notification settings, both switchable). Who: the project's owner and its admins (MANAGE_ROLES; the project has no field
of its own for who is responsible), never agents. The threshold told is kept in lists.budget_warn / tasks.budget_warn
(migrations.d/4570_a.py); when the share falls below it again (budget raised, an entry removed or moved), the mark goes
down with it, so the notice comes again on the next crossing. Tasks: the entry's task and the tasks above it that carry a
"Budget h" value of their own (a parent without one is no budget of its own; no notice per bare branch). Counted is
everyone's time (not what one viewer sees): the notice is about the project, not about a person's share."""
import json
import logging
import math

from flask import g, has_request_context

from ..core.config import PUBLIC_URL, app
from ..core.db import iso_ms, now_utc
from ..core.i18n import LANGS, lang, tr
from ..core.pg import system_ctx
from ..core.access import MANAGE_ROLES
from .timetrack import BUDGET_FIELD_NAMES
from .timetrack import budget_parents
from ..collab.comments import collab_user
from ..collab.news import notif_ok

BW_WARN, BW_OVER = 80, 100  # percent


def bw_level(seconds, budget_h):
    """-> (level, pct): none (no budget) | ok | warn (from 80 %) | over (from 100 %); pct rounded like task_budget."""
    if not budget_h or budget_h <= 0:
        return "none", None
    pct = round((seconds or 0) / 3600 / budget_h * 100)
    return ("over" if pct >= BW_OVER else "warn" if pct >= BW_WARN else "ok"), pct


def _bw_mark(level):
    return BW_OVER if level == "over" else BW_WARN if level == "warn" else 0


def _bw_fields(c, lid):
    names = set(BUDGET_FIELD_NAMES) | {tr("Budget h", lg=x).lower() for x in LANGS}
    return [r["id"] for r in c.execute("SELECT id, name FROM list_fields WHERE list_id=? AND type='number'", (lid,))
            if (r["name"] or "").strip().lower() in names]


def _bw_vals(c, fids, ids=None):
    """{task_id: hours} of the "Budget h" fields fids (of the tasks ids, else of all tasks not in the trash)."""
    if not fids:
        return {}
    q, args = f"field_id IN ({','.join('?' * len(fids))})", list(fids)
    if ids is not None:
        q += f" AND v.task_id IN ({','.join('?' * len(ids))})"
        args += list(ids)
    vals = {}
    for t, v in c.execute(f"""SELECT v.task_id, v.value FROM task_field_values v JOIN tasks t ON t.id=v.task_id
                              WHERE {q} AND t.deleted_at IS NULL""", args):
        try:
            x = float(str(v).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and x > 0:
            vals[t] = vals.get(t, 0) + x
    return vals


def _bw_secs(c, where, args):
    return c.execute(f"""SELECT COALESCE(SUM(seconds), 0) FROM time_entries WHERE "end" IS NOT NULL AND {where}""", args).fetchone()[0] or 0


def bw_states(c, lid, tids):
    """-> (project, {task_id: task}) with project / task = {h, s, level, pct, mark} (task: only the given tasks and the
    tasks above them that carry a budget value of their own); project None without a budget. Everyone's finished entries."""
    lr = c.execute("SELECT id, budget_warn FROM lists WHERE id=? AND time_tracking=1", (lid,)).fetchone()
    if not lr:
        return None, {}
    fids = _bw_fields(c, lid)
    if not fids:
        return None, {}
    vals = _bw_vals(c, fids)
    skip = budget_parents(c, lid, vals) if vals else set()
    proj = None
    b = round(sum(x for t, x in vals.items() if t not in skip), 2)
    if b > 0:
        s = _bw_secs(c, "list_id=?", (lid,))
        lv, pct = bw_level(s, b)
        proj = {"h": b, "s": s, "level": lv, "pct": pct, "mark": lr["budget_warn"] or 0}
    up, kids = {}, {}
    for k, p in c.execute("SELECT id, parent_id FROM tasks WHERE list_id=? AND deleted_at IS NULL AND parent_id IS NOT NULL", (lid,)):
        up[k] = p
        kids.setdefault(p, []).append(k)
    want = set()
    for t in tids:  # the task and the tasks above it (guarded against a broken cycle)
        seen = set()
        while t is not None and t not in seen:
            seen.add(t)
            if t in vals:
                want.add(t)
            t = up.get(t)
    tasks = {}
    for t in want:
        ids, todo = {t}, [t]
        while todo:
            for k in kids.get(todo.pop(), ()):
                if k not in ids:
                    ids.add(k)
                    todo.append(k)
        bv = {x: h for x, h in vals.items() if x in ids}
        bskip = budget_parents(c, lid, bv) if bv else set()
        tb = round(sum(h for x, h in bv.items() if x not in bskip), 2)
        if tb <= 0:
            continue
        s = _bw_secs(c, f"task_id IN ({','.join('?' * len(ids))})", tuple(ids))
        lv, pct = bw_level(s, tb)
        m = c.execute("SELECT budget_warn FROM tasks WHERE id=?", (t,)).fetchone()
        tasks[t] = {"h": tb, "s": s, "level": lv, "pct": pct, "mark": (m[0] if m else 0) or 0}
    return proj, tasks


def bw_people(c, lid):
    """The project's people who hear its budget warnings: the owner + the admins of the list, no agents."""
    lr = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    ids = [lr["owner_id"]] if lr and lr["owner_id"] else []
    ids += [r[0] for r in c.execute(f"SELECT user_id FROM list_members WHERE list_id=? AND role IN ({','.join('?' * len(MANAGE_ROLES))})",
                                    (lid, *MANAGE_ROLES))]
    ag = {r[0] for r in c.execute("SELECT id FROM users WHERE kind='agent'")}
    return [u for i, u in enumerate(ids) if u not in ag and u not in ids[:i]]


def _bw_tell(c, lid, tid, st, pushes):
    """One News item (+ push) per person for a threshold crossed (st = the state of bw_states). The pushes go into
    `pushes` and reach g.pushes only once the savepoint of bw_check held (review #4570 F1: no push for a rolled-back notice)."""
    from ..collab.liste2eguard import le2b_list_locked  # loaded after this module (kalmido/__init__.py ORDER)
    from ..notify.push import push_prio
    lst = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()
    locked = le2b_list_locked(c, lid)  # a list with the lock: no title in the push (the News item resolves it in the app)
    title = None
    if tid and not locked:
        tr_ = c.execute("SELECT title FROM tasks WHERE id=?", (tid,)).fetchone()
        title = tr_["title"] if tr_ else None
    data = {"scope": "task" if tid else "project", "level": _bw_mark(st["level"]), "pct": st["pct"],
            "h": st["h"], "tracked_h": round(st["s"] / 3600, 2)}
    for uid in bw_people(c, lid):
        s = collab_user(c, uid, lid)
        if not s:
            continue
        if notif_ok(c, uid, s, "timebudget", "news", lid):
            c.execute("INSERT INTO notifications(user_id,kind,task_id,list_id,actor_id,comment_id,data,created_at) VALUES(?,?,?,?,?,?,?,?)",
                      (uid, "budgetwarn", tid, lid, None, None, json.dumps(data), iso_ms(now_utc())))
        if has_request_context() and notif_ok(c, uid, s, "timebudget", "push", lid):
            lg = lang(c, uid)
            name = title or ("" if locked else (lst["name"] if lst else ""))
            head = tr("Budget exceeded", lg=lg) if data["level"] >= BW_OVER else tr("80 % of the budget used", lg=lg)
            msg = tr("{0}: {1} of {2} h tracked ({3} %)", name or tr("Project", lg=lg), f"{data['tracked_h']:g}", f"{st['h']:g}", st["pct"], lg=lg)
            pushes.append((uid, head, msg, f"{PUBLIC_URL}/#l/{lid}", push_prio(s)))


def bw_check(c, pairs):
    """After a time entry was saved / stopped / moved / deleted (caller commits): pairs = [(list_id, task_id | None)] the
    entry was in before and after. A threshold crossed for the first time tells the project's people (once, the mark
    goes up); a share below the mark lowers the mark silently. Never fails the save (a fault is only printed)."""
    todo = {}
    for lid, tid in pairs:
        if lid:
            todo.setdefault(int(lid), set())
            if tid:
                todo[int(lid)].add(int(tid))
    for lid, tids in todo.items():
        pushes = []
        try:
            with c.savepoint(), system_ctx(c):  # everyone's entries and the owner / admins, whatever the writer sees
                proj, tasks = bw_states(c, lid, tids)
                if proj:
                    _bw_step(c, "lists", lid, lid, None, proj, pushes)
                for tid, st in tasks.items():
                    _bw_step(c, "tasks", tid, lid, tid, st, pushes)
        except Exception:  # noqa: BLE001 - the time entry is what counts; the notice is extra
            # review #4570 F5: into the server's error log (admin alerts read it), not only stdout
            logging.getLogger(app.name).exception("budget warning failed for list %s", lid)
            continue
        if pushes and has_request_context():
            g.setdefault("pushes", []).extend(pushes)


def _bw_step(c, table, rid, lid, tid, st, pushes):
    new = _bw_mark(st["level"])
    if new < st["mark"]:
        c.execute(f"UPDATE {table} SET budget_warn=? WHERE id=?", (new, rid))
    elif new > st["mark"]:  # only the request that raises the mark tells (two saves at once: one notice)
        if c.execute(f"UPDATE {table} SET budget_warn=? WHERE id=? AND budget_warn<?", (new, rid, new)).rowcount:
            _bw_tell(c, lid, tid, st, pushes)
