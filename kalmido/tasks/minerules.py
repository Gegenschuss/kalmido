"""2.823.0 (#4773): the person's own rules of "My tasks" (tables user_mine_rules / user_mine_rule_runs, migrations.d/4773_a.py).

Every person can set up to MR_MAX rules in "My tasks" (view menu > Rules). A personal rule NEVER changes
the task, only the person's own view: its only action is "move into my section X, at the top / the end". Triggers: N days
before the due date, due today, due today or overdue, overdue, newly assigned to me (no place yet = "Recently assigned"),
the priority becomes high, from project Y, gets the project tag Z; optional conditions "only if" (priority, project, project
tag) like the project rules (#4768). The fixed rule of #4395 "due today or overdue -> Now" is the first rule made with the
sections (dflt = 1; switched off or deleted like any other, a deleted one never comes back by itself).

Once per rule, task and occasion (user_mine_rule_runs: due:<due day>, new, prio, list:<id>, ltag:<id>): a task the person
moves by hand afterwards stays where it was put. A moved due date is a new occasion; for new / prio / list / ltag the marker
goes when the trigger no longer holds (priority lowered, task out of the project, tag removed), so the next time counts again.

Where it runs: the web app knows which tasks "My tasks" shows (assigned to me or my group, hidden projects left out) and sends
their ids (POST /api/mine-rules/apply) when the view opens or its tasks change; the server checks every id against what the
person sees (no new visibility), evaluates triggers and conditions itself and writes only user_task_order (section_id, pos).
The topmost rule that holds moves the task (the others note the occasion). Personal rules start no project rules and project
rules none of these (they only touch the own order). Agents neither read nor propose them (403, like the own sections)."""
import json
from datetime import date, timedelta

from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, write_lock, iso, iso_ms, local_now, now_utc
from ..core.access import Denied, live_sql, trash_sql, tvis, vis_sql, list_role
from ..core.conflict import ccf_check
from ..core.pg import qi
from ..core.objtags import OTG_TASK_FROM, otg_scope_sql
from .mineorder import VW_MINE_MAX, _ms_person as _person, ms_rule_seed as mr_seed, vw_mine_order, vw_mine_sections

MR_MAX = 20             # rules per person (deleted ones do not count)
MR_NAME_MAX = 80
MR_DAYS_MAX = 30        # "N days before the due date": 1..30
MR_TRIGS = ("due", "new", "prio", "list", "ltag")
MR_DUE = {"today": "t", "now": "n", "overdue": "o", "before": "b"}  # trigger.when -> trig_val ('b<days>')
MR_PRIO = {"none": 0, "low": 1, "medium": 3, "high": 5, "urgent": 7}  # the condition priority (names as the project rules)
MR_HIGH = 5             # trigger prio: the priority becomes high (or urgent)
MR_PLACES = ("top", "bottom")
MR_EDGE = ("new", "prio", "list", "ltag")  # their marker goes when the trigger no longer holds
MR_COLS = ("name", "trig", "trig_val", "conds", "section_id", "place", "active", "updated_at")  # what PATCH writes (mr_clean)


class _Bad(Exception):
    pass


def _int(v, what):
    if isinstance(v, bool) or not isinstance(v, int):
        raise _Bad(tr("Invalid value: {0}", what))
    return v


def _own_secs(c, uid):
    """{section id: kind} of the person's own sections without "Recently assigned", top first (dict order)."""
    return {r[0]: r[1] for r in c.execute("SELECT id, kind FROM user_mine_sections WHERE user_id=? AND kind<>'recent' ORDER BY pos, id", (uid,))}


def _due_val(tv):
    """(when, days) of a due trig_val; None = a value this version does not know (the rule does not run)."""
    if tv in ("t", "n", "o"):
        return {"t": "today", "n": "now", "o": "overdue"}[tv], 0
    if tv[:1] == "b" and tv[1:].isdigit() and 1 <= int(tv[1:]) <= MR_DAYS_MAX:
        return "before", int(tv[1:])
    return None


def _jload(v):
    try:
        x = json.loads(v) if v else {}
    except (TypeError, ValueError):
        return {}
    return x if isinstance(x, dict) else {}


def _tag_list(c, tag):
    # 2.947.0 (#5275): a project tag is a row of the core (obj_tags scope list, scope_id = the list's id)
    r = c.execute("SELECT CAST(scope_id AS BIGINT) FROM obj_tags WHERE id=? AND scope_kind='list'", (tag,)).fetchone()
    return r[0] if r else None


def mr_row(c, r, secs=None):
    """A rule for the app: {id, name, trigger {kind, when?, days?, list_id?, tag_id?}, section_id, place, conditions, active,
    default, updated_at, waiting (its section is gone: it moves nothing until the Undo brings the section back)}."""
    secs = _own_secs(c, r["user_id"]) if secs is None else secs
    t = {"kind": r["trig"]}
    if r["trig"] == "due":
        w = _due_val(r["trig_val"]) or ("today", 0)
        t["when"] = w[0]
        if w[0] == "before":
            t["days"] = w[1]
    elif r["trig"] == "list" and r["trig_val"].isdigit():
        t["list_id"] = int(r["trig_val"])
    elif r["trig"] == "ltag" and r["trig_val"].isdigit():
        t["tag_id"] = int(r["trig_val"])
        t["list_id"] = _tag_list(c, t["tag_id"])
    cond = _jload(r["conds"])
    if cond.get("tag_id"):
        cond["tag_list_id"] = _tag_list(c, cond["tag_id"])
    return {"id": r["id"], "name": r["name"] or "", "trigger": t, "section_id": r["section_id"], "place": r["place"],
            "conditions": cond, "active": bool(r["active"]), "default": bool(r["dflt"]), "updated_at": r["updated_at"],
            "waiting": r["section_id"] not in secs}


def mr_list(c, uid):
    secs = _own_secs(c, uid)
    return [mr_row(c, r, secs) for r in c.execute(f"SELECT * FROM user_mine_rules WHERE user_id=? AND {live_sql()} ORDER BY pos, id", (uid,))]


def _see_list(c, uid, lid):
    if not list_role(c, lid, uid):
        raise _Bad(tr("Invalid value: {0}", "list_id"))
    return lid


def _see_tag(c, uid, tag):
    lid = _tag_list(c, tag)
    if not lid or not list_role(c, lid, uid):
        raise _Bad(tr("Invalid value: {0}", "tag_id"))
    return tag


def mr_clean(c, uid, b, partial=None):
    """{name?, trigger {kind, when?, days?, list_id?, tag_id?}, section_id, place?, conditions?, active?} -> the columns (_Bad).
    Projects and tags only those the person sees; the section one of the person's own (not "Recently assigned")."""
    out = {}
    if "name" in b or partial is None:
        n = b.get("name", "")
        if not isinstance(n, str):
            raise _Bad(tr("Invalid value: {0}", "name"))
        out["name"] = " ".join(n.split())[:MR_NAME_MAX]
    if "trigger" in b or partial is None:
        t = b.get("trigger")
        if not isinstance(t, dict) or t.get("kind") not in MR_TRIGS:
            raise _Bad(tr("Invalid value: {0}", "trigger"))
        k, v = t["kind"], ""
        if k == "due":
            when = t.get("when") or "today"
            if when not in MR_DUE:
                raise _Bad(tr("Invalid value: {0}", "trigger.when"))
            v = MR_DUE[when]
            if when == "before":
                d = _int(t.get("days"), "trigger.days")
                if not 1 <= d <= MR_DAYS_MAX:
                    raise _Bad(tr("Invalid value: {0}", "trigger.days"))
                v += str(d)
        elif k == "list":
            v = str(_see_list(c, uid, _int(t.get("list_id"), "trigger.list_id")))
        elif k == "ltag":
            v = str(_see_tag(c, uid, _int(t.get("tag_id"), "trigger.tag_id")))
        out["trig"], out["trig_val"] = k, v
    if "section_id" in b or partial is None:
        sid = _int(b.get("section_id"), "section_id")
        if sid not in _own_secs(c, uid):
            raise _Bad(tr("Invalid value: {0}", "section_id"))
        out["section_id"] = sid
    if "place" in b or partial is None:
        p = b.get("place", "top")
        if p not in MR_PLACES:
            raise _Bad(tr("Invalid value: {0}", "place"))
        out["place"] = p
    if "conditions" in b:
        d = b["conditions"]
        if d in (None, "", {}):
            out["conds"] = ""
        elif not isinstance(d, dict) or set(d) - {"priority", "list_id", "tag_id"}:
            raise _Bad(tr("Invalid value: {0}", "conditions"))
        else:
            cd = {}
            if d.get("priority") not in (None, ""):
                if d["priority"] not in MR_PRIO:
                    raise _Bad(tr("Invalid value: {0}", "conditions.priority"))
                cd["priority"] = d["priority"]
            if d.get("list_id") not in (None, "", 0):
                cd["list_id"] = _see_list(c, uid, _int(d["list_id"], "conditions.list_id"))
            if d.get("tag_id") not in (None, "", 0):
                cd["tag_id"] = _see_tag(c, uid, _int(d["tag_id"], "conditions.tag_id"))
            out["conds"] = json.dumps(cd, separators=(",", ":")) if cd else ""
    if "active" in b:
        if not isinstance(b["active"], bool):
            raise _Bad(tr("Invalid value: {0}", "active"))
        out["active"] = b["active"]
    return out


def _answer(c, uid, **kw):
    bump(c)
    c.commit()
    return jsonify(ok=True, rules=mr_list(c, uid), limit=MR_MAX, mine_sections=vw_mine_sections(c, uid), **kw)


def _get(c, uid, rid):
    r = c.execute(f"SELECT * FROM user_mine_rules WHERE id=? AND user_id=? AND {live_sql()}", (rid, uid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def _bad(c, e):
    c.rollback()
    return jsonify(error=str(e)), 400


def _active_n(c, uid):
    return c.execute(f"SELECT COUNT(*) FROM user_mine_rules WHERE user_id=? AND {live_sql()}", (uid,)).fetchone()[0]


@app.get("/api/mine-rules")
def mr_get():
    """The person's rules, top first (the topmost that holds wins), and the limit."""
    c, uid = _person()
    return jsonify(rules=mr_list(c, uid), limit=MR_MAX)


@app.post("/api/mine-rules")
def mr_create():
    """{name?, trigger, section_id, place?, conditions?, active?} -> a new rule at the end. At most MR_MAX (400)."""
    c, uid = _person()
    b = body() or {}
    write_lock(c, f"mine-order-{uid}")
    if _active_n(c, uid) >= MR_MAX:
        c.rollback()
        return jsonify(error=tr("At most {0} rules", MR_MAX)), 400
    try:
        v = mr_clean(c, uid, b)
    except _Bad as e:
        return _bad(c, e)
    t = iso_ms(now_utc())
    pos = c.execute("SELECT COALESCE(MAX(pos), 0) + 1 FROM user_mine_rules WHERE user_id=?", (uid,)).fetchone()[0]
    rid = c.execute("INSERT INTO user_mine_rules(user_id, name, trig, trig_val, conds, section_id, place, pos, active, created_at, updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                    (uid, v["name"], v["trig"], v["trig_val"], v.get("conds", ""), v["section_id"], v["place"], pos, v.get("active", True), t, t)).fetchone()[0]
    return _answer(c, uid, id=rid)


@app.patch("/api/mine-rules/<int:rid>")
def mr_patch(rid):
    """{name?, trigger?, section_id?, place?, conditions?, active?, expect_updated_at?}: a changed trigger, section or condition
    makes the rule new (its markers go: it looks at every task again). Another version now -> 409 {error, rule}."""
    c, uid = _person()
    b = body() or {}
    write_lock(c, f"mine-order-{uid}")
    r = _get(c, uid, rid)
    ccf_check(b, r["updated_at"], "rule", lambda: mr_row(c, r))
    try:
        v = mr_clean(c, uid, b, partial=r)
    except _Bad as e:
        return _bad(c, e)
    if not v:
        c.rollback()
        return jsonify(ok=True, rule=mr_row(c, r), rules=mr_list(c, uid), limit=MR_MAX)
    if any(k in v and v[k] != r[k] for k in ("trig", "trig_val", "conds", "section_id", "place")):
        c.execute("DELETE FROM user_mine_rule_runs WHERE rule_id=?", (rid,))
    v["updated_at"] = iso_ms(now_utc())
    c.execute(f"UPDATE user_mine_rules SET {', '.join(qi(k, MR_COLS) + '=?' for k in v)} WHERE id=?", (*v.values(), rid))
    return _answer(c, uid, rule=mr_row(c, _get(c, uid, rid)))


@app.delete("/api/mine-rules/<int:rid>")
def mr_delete(rid):
    """{expect_updated_at?}: deletes the rule (POST /api/mine-rules/<id>/restore is its Undo). The first rule is kept as
    deleted, so it never comes back by itself."""
    c, uid = _person()
    b = body() or {}
    write_lock(c, f"mine-order-{uid}")
    r = _get(c, uid, rid)
    ccf_check(b, r["updated_at"], "rule", lambda: mr_row(c, r))
    c.execute("UPDATE user_mine_rules SET deleted_at=?, updated_at=? WHERE id=?", (iso(now_utc()), iso_ms(now_utc()), rid))
    return _answer(c, uid, id=rid)


@app.post("/api/mine-rules/<int:rid>/restore")
def mr_restore(rid):
    """The Undo of a deletion: the rule comes back at its place (not over the limit)."""
    c, uid = _person()
    write_lock(c, f"mine-order-{uid}")
    if not c.execute(f"SELECT 1 FROM user_mine_rules WHERE id=? AND user_id=? AND {trash_sql()}", (rid, uid)).fetchone():
        c.rollback()
        raise Denied(404)
    if _active_n(c, uid) >= MR_MAX:
        c.rollback()
        return jsonify(error=tr("At most {0} rules", MR_MAX)), 400
    c.execute("UPDATE user_mine_rules SET deleted_at=NULL, updated_at=? WHERE id=?", (iso_ms(now_utc()), rid))
    return _answer(c, uid, id=rid)


@app.put("/api/mine-rules/order")
def mr_order():
    """{ids: [rule ids, top first]}: the order of the rules (the topmost that holds moves a task). Rules not named stay behind."""
    c, uid = _person()
    ids = (body() or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        return jsonify(error=tr("Invalid value: {0}", "ids")), 400
    write_lock(c, f"mine-order-{uid}")
    rows = [r[0] for r in c.execute(f"SELECT id FROM user_mine_rules WHERE user_id=? AND {live_sql()} ORDER BY pos, id", (uid,))]
    new = [x for x in dict.fromkeys(ids) if x in rows]
    new += [x for x in rows if x not in new]
    c.executemany("UPDATE user_mine_rules SET pos=? WHERE id=?", [(n + 1, x) for n, x in enumerate(new)])
    return _answer(c, uid)


# ---------------------------------------------------------------- the run
def _today(v):
    """The person's day as the app sends it (its time zone), at most one day from the server's; else the server's."""
    srv = local_now().date()
    try:
        d = date.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        d = None
    return d if d and abs((d - srv).days) <= 1 else srv


def mr_key(r, t, day, placed, tags):
    """The occasion (run marker) of rule r on task t today, None when its trigger does not hold."""
    k, v = r["trig"], r["trig_val"]
    if k == "due":
        w, due = _due_val(v), t["due"]
        if not w or not due:
            return None
        try:
            n = (date.fromisoformat(due[:10]) - day).days
        except ValueError:
            return None
        ok = {"today": n == 0, "now": n <= 0, "overdue": n < 0, "before": 0 < n <= w[1]}[w[0]]
        return "due:" + due[:10] if ok else None
    if k == "new":
        return "new" if t["id"] not in placed else None
    if k == "prio":
        return "prio" if (t["priority"] or 0) >= MR_HIGH else None
    if k == "list":
        return "list:" + v if str(t["list_id"]) == v else None
    if k == "ltag":
        return "ltag:" + v if v.isdigit() and int(v) in tags else None
    return None


def mr_cond_ok(r, t, tags):
    d = _jload(r["conds"])
    if "priority" in d and (t["priority"] or 0) != MR_PRIO.get(d["priority"], -1):
        return False
    if "list_id" in d and t["list_id"] != d["list_id"]:
        return False
    return not ("tag_id" in d and d["tag_id"] not in tags)


def mr_move(order, secs, moves):
    """order = [(task id, section id | None)] of user_task_order top first; moves = [(task id, section id, place)] in the
    order of "My tasks". -> the new order: a task to the top goes above the first task of its section, to the end below its
    last; a section without tasks takes it at the end (the app groups by section, the order inside counts)."""
    top = next(iter(secs), None)
    eff = lambda s: s if s in secs else top  # noqa: E731  a row without a section of its own stands in the topmost one
    gone = {m[0] for m in moves}
    out = [x for x in order if x[0] not in gone]
    groups = {}
    for tid, sid, place in moves:
        groups.setdefault((sid, place), []).append((tid, sid))
    for (sid, place), rows in groups.items():
        at = [i for i, x in enumerate(out) if eff(x[1]) == sid]
        i = (at[0] if place == "top" else at[-1] + 1) if at else len(out)
        out[i:i] = rows
    return out


@app.post("/api/mine-rules/apply")
def mr_apply():
    """{ids: [the task ids "My tasks" shows, in its order], today?: 'YYYY-MM-DD' of the device} -> {moved, mine_order?,
    mine_sections?}. Runs the person's rules on those tasks (only ids the person sees, open ones); writes only the own order.
    Makes the first rule once (mr_seed)."""
    c, uid = _person()
    b = body() or {}
    ids = b.get("ids")
    if not isinstance(ids, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        return jsonify(error=tr("Invalid value: {0}", "ids")), 400
    ids = [x for x in dict.fromkeys(ids) if 0 < x < 10 ** 12][:VW_MINE_MAX]
    day = _today(b.get("today"))
    write_lock(c, f"mine-order-{uid}")
    seeded = mr_seed(c, uid, day)
    secs = _own_secs(c, uid)
    rules = [r for r in c.execute(f"SELECT * FROM user_mine_rules WHERE user_id=? AND active AND {live_sql()} ORDER BY pos, id", (uid,))
             if r["section_id"] in secs]
    if not rules or not ids:
        if not seeded:
            c.rollback()
            return jsonify(ok=True, moved=0)
        return _apply_answer(c, uid, 0)
    tasks, tags = {}, {}
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        q = ",".join("?" * len(part))
        for r in c.execute(f"SELECT id, list_id, due, priority FROM tasks WHERE id IN ({q}) AND status=0 AND {live_sql()} "
                           f"AND list_id IN {vis_sql()} AND {tvis(c, uid)}", (*part, uid, uid)):
            tasks[r["id"]] = r
        for r in c.execute(f"SELECT k.obj_id, ot.id {OTG_TASK_FROM} WHERE k.obj_id IN ({q}) AND {otg_scope_sql()}", part):
            tags.setdefault(r[0], set()).add(r[1])
    tids = list(tasks)
    runs = {}  # (rule id, task id) -> the keys of its markers
    for i in range(0, len(tids), 500):
        part = tids[i:i + 500]
        for r in c.execute(f"SELECT rule_id, task_id, key FROM user_mine_rule_runs WHERE user_id=? AND task_id IN ({','.join('?' * len(part))})", (uid, *part)):
            runs.setdefault((r[0], r[1]), set()).add(r[2])
    order = [(r[0], r[1]) for r in c.execute("SELECT task_id, section_id FROM user_task_order WHERE user_id=? ORDER BY pos, task_id", (uid,))]
    placed = {x[0] for x in order}
    now, new_runs, gone_runs, moves = iso(now_utc()), [], [], []
    for tid in ids:
        t = tasks.get(tid)
        if not t:
            continue
        tg, moved = tags.get(tid, set()), False
        for r in rules:
            key = mr_key(r, t, day, placed, tg)
            if key is None:
                if r["trig"] in MR_EDGE:  # the trigger no longer holds: the next time is a new occasion
                    gone_runs += [(r["id"], tid, k) for k in runs.get((r["id"], tid), ())]
                continue
            if key in runs.get((r["id"], tid), ()) or not mr_cond_ok(r, t, tg):
                continue
            new_runs.append((uid, r["id"], tid, key, now))
            if not moved:
                moves.append((tid, r["section_id"], r["place"]))
                moved = True
    if not new_runs and not gone_runs and not seeded:
        c.rollback()
        return jsonify(ok=True, moved=0)
    if gone_runs:
        c.executemany("DELETE FROM user_mine_rule_runs WHERE rule_id=? AND task_id=? AND key=?", gone_runs)
    if new_runs:
        c.executemany("INSERT INTO user_mine_rule_runs(user_id, rule_id, task_id, key, at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING", new_runs)
    if not moves and not seeded:  # only markers changed: nothing the other devices need to load
        c.commit()
        return jsonify(ok=True, moved=0)
    if moves:
        out = mr_move(order, secs, moves)[:VW_MINE_MAX]
        c.execute("DELETE FROM user_task_order WHERE user_id=?", (uid,))
        c.executemany("INSERT INTO user_task_order(user_id, task_id, pos, section_id) VALUES(?,?,?,?)",
                      [(uid, tid, n, sid) for n, (tid, sid) in enumerate(out)])
    # markers of tasks completed a month ago are done with (a task deleted takes its own along)
    c.execute("DELETE FROM user_mine_rule_runs WHERE user_id=? AND at<? AND task_id IN (SELECT id FROM tasks WHERE status<>0)",
              (uid, iso(now_utc() - timedelta(days=30))))
    return _apply_answer(c, uid, len(moves))


def _apply_answer(c, uid, moved):
    bump(c)
    c.commit()
    return jsonify(ok=True, moved=moved, mine_order=vw_mine_order(c, uid), mine_sections=vw_mine_sections(c, uid))
