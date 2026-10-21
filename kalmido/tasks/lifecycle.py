"""Applying changes, completing (repeats), undo, skip, reopen, delete, trash and restore."""
import hashlib
import hmac
import json
import re
from datetime import date, datetime
from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.i18n import tr
from ..core.db import body, bump, db, err, gsetting, iso, local_now, now_utc, parse_iso
from ..accounts.session import me
from ..core.access import collab_all, Denied, list_people, list_role, need_list, need_task, wr_sql
from ..core.serializers import attachment_files, unlink_files
from ..lists.groups import check_group_assignee, grp_assign_events, grp_name, grp_shares_of_list
from ..tasks.validation import (
    check_parent, check_url, clean_task, DATE_MAX_Y, descendants, log_act, log_changes, rr_feasible, rr_norm, rr_rule, rmd_split,
    ticket_template, valid_hm, valid_plan_start,
)
from ..tasks.tasks import (
    check_assignee, check_move, hard_delete, move_subtree, ms_cleanup, ms_target, my_tags, one_task,
    participant_assignee, set_tags,
)
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions


def _norm(v):
    if isinstance(v, list):
        return sorted(str(x) for x in v)
    return None if v in ("", None) else str(v)


def apply_update(c, tid, b, conflicts=None, lock=False):
    """b may carry `_prev` = the values the client saw before its edit (offline replay, detail typing).
    A field whose server value differs from `_prev` was changed elsewhere meanwhile: it is NOT
    overwritten but reported back as a conflict (client lets the user pick).
    The caller checked write access to the task; moves are checked here (Denied).
    lock (2.36.0, #1118): a direct edit of a person (PATCH /api/tasks/<id>, multi-select, undo) honours the task lock; applied
    proposals / suggestions, dependent dates and roadmap shifts do not (they were approved or switched on on purpose)."""
    from ..collab.comments import assignment_events
    from ..lists.fields import field_value, set_field_values
    from ..agents.core import agent_task_mentions
    from ..collab.reactions import ltags_follow, set_ltags
    from ..family.family import _jparse, is_shop, people_set, rot_apply, shop_remember
    prev = b.get("_prev") if isinstance(b.get("_prev"), dict) else None
    if prev:
        row = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        b = dict(b)
        for k, old in prev.items():
            if k not in b or k.startswith("_"):
                continue
            if k == "fields":  # D4: custom field values, compared per field ({field id: value})
                if not isinstance(old, dict) or not isinstance(b["fields"], dict):
                    continue
                fv = dict(b["fields"])
                have = dict(c.execute("SELECT field_id, value FROM task_field_values WHERE task_id=?", (tid,)).fetchall())
                for fk, fold in old.items():
                    if fk not in fv or not str(fk).isdigit():
                        continue
                    cur = have.get(int(fk))
                    if _norm(cur) != _norm(fold) and _norm(cur) != _norm(fv[fk]):
                        if conflicts is not None:
                            conflicts.append({"field": f"field:{int(fk)}", "server": cur, "mine": fv[fk]})
                        del fv[fk]
                b["fields"] = fv
                continue
            if k == "tags":
                cur = my_tags(c, tid)
            elif k == "snippets" and k in row.keys():  # 2.35.0 (#1095): compared by their content (ids, language, path, line, code)
                from ..tasks.snippets import snip_sig
                cur, old, mine = snip_sig(row[k]), snip_sig(old), snip_sig(b[k])
                if cur != old and cur != mine:
                    if conflicts is not None:
                        conflicts.append({"field": k, "server": None, "mine": None})
                    del b[k]
                continue
            elif k in ("fam", "rotation") and k in row.keys():  # 2.19.0 (#653): JSON objects, compared as such
                js = lambda v: json.dumps(_jparse(v) or None, sort_keys=True)  # noqa: E731
                cur, old, mine = js(row[k]), js(old), js(b[k])
                if cur != old and cur != mine:
                    if conflicts is not None:
                        conflicts.append({"field": k, "server": _jparse(row[k]), "mine": b[k]})
                    del b[k]
                continue
            elif k in row.keys():
                cur = row[k] or None if k == "ms" else row[k]  # 2.18.0: the client omits ms = 0 (null there)
            else:
                continue
            if _norm(cur) != _norm(old) and _norm(cur) != _norm(b[k]):
                if conflicts is not None:
                    conflicts.append({"field": k, "server": cur, "mine": b[k]})
                del b[k]
    f = clean_task(b)
    if "title" in f and not f["title"]:
        return tr("Title missing")
    e = check_url(f)
    if e:
        return e
    cur = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()  # also the "before" of the activity log
    from ..lists.rules import rul_fire, rul_snap
    rb = rul_snap(c, tid)  # 2.71.0 A (#1457): list rules compare with this after the change
    from ..tasks.validation import lock_problem
    e = lock_problem(c, cur, f, b) if lock else None  # 2.36.0 (#1118): a locked task keeps its locked fields (app writes)
    if e:
        return e
    from ..collab.notelock import ln_guard
    e = ln_guard(c, tid, f)  # 2.48.0 (#1642): a note locked with a password is changed only through its own routes
    if e:
        return e
    from ..collab.liste2e import le2a_task_write, le2e_mode
    if f.get("ttype") and f["ttype"] != cur["ttype"] and "content" not in f and not (cur["content"] or "").strip() \
            and not le2e_mode(c, f.get("list_id") or cur["list_id"]):  # 2.64.1 (#1817): no plain template in a list with the lock
        tpl = ticket_template(c, f.get("list_id") or cur["list_id"], f["ttype"])  # 2.4.0 (#340): empty notes get the template
        if tpl:
            f["content"] = tpl
    if has_request_context() and getattr(g, "user", None) and list_role(c, cur["list_id"]) == "participant":
        e = participant_assignee(c, cur, f)
        if e:
            raise Denied(403, e)
        if "list_id" in f and f["list_id"] and f["list_id"] != cur["list_id"]:
            raise Denied(403, tr("Participants cannot move tasks to another list"))
        if "parent_id" in f and f["parent_id"] != cur["parent_id"] and not f["parent_id"] and cur["assignee_id"] != me():
            raise Denied(403, tr("Participants can only move subtasks within their own tasks"))
    if "repeat" in f and f["repeat"] != cur["repeat"]:
        e = repeat_problem(f["repeat"], f.get("due", cur["due"]))
        if e:
            return e
    if "start" in f or "due" in f:  # keep start <= due against the stored other half
        st, du = f.get("start", cur["start"]), f.get("due", cur["due"])
        if st and (not du or st > du):
            f["start"] = du
    if "parent_id" in f:
        if f["parent_id"]:
            need_task(c, f["parent_id"])  # 2.86.0 (N14): 404 / 403 before the parent checks (no existence / milestone oracle)
        e = check_parent(c, tid, f["parent_id"])
        if e:
            return e
        if f["parent_id"]:  # indent: follow the new parent's list / section
            p = c.execute("SELECT list_id, section_id FROM tasks WHERE id=?", (f["parent_id"],)).fetchone()
            f["list_id"] = p["list_id"]
            f["section_id"] = p["section_id"]
    if "list_id" in f:
        if not f["list_id"]:
            del f["list_id"]
        elif f["list_id"] != cur["list_id"]:
            need_list(c, f["list_id"])  # moving out needs write on the source (caller), in on the target
            check_move(c, cur["list_id"], f["list_id"])
    lid = f.get("list_id", cur["list_id"])
    le2_post = le2a_task_write(c, tid, cur, f, b, lid)  # 2.64.1 (#1817): the texts of a list with the lock (ciphertexts only, moves via the app)
    if f.get("section_id") and not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (f["section_id"], lid)).fetchone():
        f["section_id"] = None
    # 2.18.0 (#430): a milestone stays top level without subtasks; a task's milestone is one of its own list
    if f.get("ms") and not cur["ms"]:
        if f.get("parent_id", cur["parent_id"]):
            return tr("A milestone cannot be a subtask")
        if c.execute("SELECT 1 FROM tasks WHERE parent_id=? AND deleted_at IS NULL", (tid,)).fetchone():
            return tr("A milestone cannot have subtasks")
    if f.get("ms", cur["ms"]):
        if cur["milestone_id"] or f.get("milestone_id"):
            f["milestone_id"] = None
    elif "milestone_id" in f and (f["milestone_id"] != cur["milestone_id"] or lid != cur["list_id"]):
        e = ms_target(c, f["milestone_id"], lid, tid)
        if e:
            return e
    elif lid != cur["list_id"] and cur["milestone_id"]:
        f["milestone_id"] = None  # moved to another list: the milestone stays behind
    if lid != cur["list_id"] and cur["status"] == 0:  # 2.60.0 (#1512, review): a task waiting for its approval keeps its list
        from ..tasks.review import _gate_holds, rvw_gate, rvw_may
        if _gate_holds(c, cur) and not rvw_may(c, cur, me()):
            return rvw_gate(c, tid) or tr("Changed in the meantime, nothing to undo")
    if "sprint_id" in f or (lid != cur["list_id"] and cur["sprint_id"]):  # 2.60.0 (#343): a sprint of the same list
        from ..lists.sprints import spr_apply
        e = spr_apply(c, f, cur, lid)
        if e:
            return e
    if "rotation" in f or (cur["rotation"] and lid != cur["list_id"]):  # 2.19.0 (#653): household rotation
        if "rotation" in f and has_request_context() and getattr(g, "user", None) and list_role(c, cur["list_id"]) == "participant":
            raise Denied(403, tr("Participants cannot change who a task is assigned to"))
        e = rot_apply(c, f, cur, lid)
        if e:
            return e
    elif "assignee_id" in f and cur["rotation"]:  # assigned by hand: the turn continues from that person
        r = _jparse(cur["rotation"]) or {}
        if f["assignee_id"] in (r.get("who") or []):
            r["i"] = r["who"].index(f["assignee_id"])
            f["rotation"] = json.dumps(r, separators=(",", ":"))
    if "assignee_id" in f and (collab_all() or _norm(f["assignee_id"]) != _norm(cur["assignee_id"])):
        e = check_assignee(c, lid, f["assignee_id"])
        if e:
            return e
    elif lid != cur["list_id"] and cur["assignee_id"] and cur["assignee_id"] not in list_people(c, lid):
        f["assignee_id"] = None  # the assignee has no access to the new list
    # 2.10.0 (#441): a group instead of a person (and back); the group must reach the (new) list
    if f.get("assignee_group_id"):
        f["assignee_id"] = None
        if f["assignee_group_id"] != cur["assignee_group_id"] or lid != cur["list_id"]:
            e = check_group_assignee(c, lid, f["assignee_group_id"])
            if e:
                return e
    elif f.get("assignee_id") and cur["assignee_group_id"]:
        f["assignee_group_id"] = None
    elif "assignee_group_id" not in f and cur["assignee_group_id"] and lid != cur["list_id"] \
            and cur["assignee_group_id"] not in {x[0] for x in grp_shares_of_list(c, lid)}:
        f["assignee_group_id"] = None
    if "assignee_id" in f and _norm(f["assignee_id"]) != _norm(cur["assignee_id"]):
        f["assigned_by"] = me() if f["assignee_id"] else None
        if f["assignee_id"]:  # 2.40.0 (#1344): newly assigned = on top of the person's own order of "My tasks"
            c.execute("DELETE FROM user_task_order WHERE user_id=? AND task_id=?", (f["assignee_id"], tid))
    if f.get("assignee_group_id") and f["assignee_group_id"] != cur["assignee_group_id"]:
        f["assigned_by"] = me()
    if "fields" in b:  # custom field values: validated before anything is written (2.39.1 #1217: plain lists too)
        try:
            fl = {r["id"]: r for r in c.execute("SELECT * FROM list_fields WHERE list_id=?", (lid,))}
            if not isinstance(b["fields"], dict) or any(not str(k).isdigit() or int(k) not in fl for k in b["fields"]):
                raise BadInput(tr("Unknown field"))
            for k, v in b["fields"].items():
                field_value(c, fl[int(k)], v, lid)
        except BadInput as e:
            return str(e)
    if "snippets" in f:  # 2.35.0 (#1095): unchanged snippets keep their author and time
        from ..tasks.snippets import snip_keep
        f["snippets"] = snip_keep(f["snippets"], cur["snippets"])
    if f:
        # a changed date / reminder set re-arms the reminder
        if any(k in f for k in ("due", "due_time", "reminders", "assignee_id")):
            f["reminded"] = "[]"
        f["updated_at"] = iso(now_utc())
        c.execute(f"UPDATE tasks SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), tid])
        if "list_id" in f:  # subtasks follow their parent (all levels)
            move_subtree(c, tid, f["list_id"])
            if le2_post:
                le2_post()  # 2.64.1 (#1817): the re-encrypted texts of what moved along
            if "section_id" not in f:
                c.execute("UPDATE tasks SET section_id=NULL WHERE id=?", (tid,))
        if ("list_id" in f and f["list_id"] != cur["list_id"]) or ("ms" in f and f["ms"] != cur["ms"]):
            ms_cleanup(c)  # 2.18.0 (#430): moved / no milestone any more: its tasks (and moved subtasks) let go
    if f:
        log_changes(c, tid, cur, b.get("_act"))
        new_a, new_g = c.execute("SELECT assignee_id, assignee_group_id FROM tasks WHERE id=?", (tid,)).fetchone()
        assignment_events(c, tid, cur["assignee_id"], new_a)
        if new_g != cur["assignee_group_id"]:
            log_act(c, tid, "assign_group", {"group": grp_name(c, new_g), "from": grp_name(c, cur["assignee_group_id"])})
            if new_g:
                grp_assign_events(c, tid, new_g)
    if f and "list_id" in f and f["list_id"] != cur["list_id"]:
        ltags_follow(c, tid, f["list_id"])
        from ..agents.core import agent_added_events
        agent_added_events(c, tid, cur["list_id"])  # 2.23.0 (#795): moved into a list shared with an agent
    if "ltags" in b:
        try:
            set_ltags(c, tid, b["ltags"])
        except BadInput as e:
            return str(e)
    if f and ("title" in f or "content" in f):
        agent_task_mentions(c, tid, (cur["title"] or "") + "\n" + (cur["content"] or ""))
    if "tags" in b:
        set_tags(c, tid, b["tags"])
    elif "add_tags" in b:
        set_tags(c, tid, my_tags(c, tid) + list(b["add_tags"]))
    if "fields" in b and set_field_values(c, tid, lid, b["fields"]):
        c.execute("UPDATE tasks SET updated_at=? WHERE id=?", (iso(now_utc()), tid))
    if "people" in b:  # 2.19.0 (#653): who comes along
        e = people_set(c, tid, lid, b["people"])
        if e:
            return e
    if f and ("section_id" in f or "list_id" in f):  # 2.60.0 C (#1512): into the review section = review requested
        from ..tasks.review import rvw_on_move
        rvw_on_move(c, tid, cur)
    if f and "section_id" in f and not cur["parent_id"] and is_shop(c, lid):  # 2.19.0: the shop area of this item
        shop_remember(c, lid, f.get("title") or cur["title"], f["section_id"])
    if f and ("due" in f or "fam" in f) and cur["fam"]:  # 2.140.0 D (#2137): a birthday's date / year back into its address book
        from ..family.carddav import cdv_wb_note
        cdv_wb_note(c, tid, cur, b)
    rul_fire(c, tid, rb)  # 2.71.0 A (#1457)
    return None


def rmd_next(t):
    """2.116.0 D (#2066): next (date, HH:MM) of a rule with TIMES: the next time of the same day, after the last one
    the first time of the next matching day. repeat_from 'done' counts from now. None if there is none."""
    std, times = rmd_split(rr_norm(t["repeat"]))
    if not times or not t["due"]:
        return None
    now = local_now()
    day, cur = (t["due"], t["due_time"] or "00:00") if t["repeat_from"] != "done" else (now.date().isoformat(), now.strftime("%H:%M"))
    later = [x for x in times if x > cur]
    if later and (t["repeat_from"] != "done" or rr_day_ok(std, day)):
        return day, later[0]
    nd = next_due({**dict(t), "repeat": std, "due": day, "repeat_from": "due"})
    return (nd, times[0]) if nd else None


def rr_day_ok(std, day):
    rule = rr_rule(std, day)
    d = date.fromisoformat(day)
    return bool(rule) and rule.after(datetime(d.year, d.month, d.day), inc=True).date() == d


def next_due(t):
    """Next occurrence (date, keeps due_time) for a recurring task, or None."""
    if not t["repeat"] or not t["due"]:
        return None
    if "TIMES=" in t["repeat"]:  # 2.116.0 D (#2066)
        n = rmd_next(t)
        return n[0] if n else None
    try:
        base = t["due"] if t["repeat_from"] != "done" else local_now().date().isoformat()
        rule = rr_rule(t["repeat"], base)
        if rule is None:
            print("rrule not usable:", t["id"], repr(t["repeat"]), flush=True)
            return None
        d = date.fromisoformat(base)
        nxt = rule.after(datetime(d.year, d.month, d.day))
        return nxt.date().isoformat() if nxt and nxt.year <= DATE_MAX_Y else None
    except (ValueError, TypeError, OverflowError) as e:
        print("rrule error:", t["id"], t["repeat"], e, flush=True)
        return None


def repeat_problem(rep, due):
    """Error text if a new / changed rule never produces a date from due on, else None."""
    if rep and due and not rr_feasible(rr_norm(rep), due):
        return tr("Repeat: the rule has no date in the next 10 years")
    return None


def rr_count(repeat):
    m = re.search(r"(?:^|;)COUNT=(\d+)", repeat or "")
    return int(m.group(1)) if m else None


def rr_with_count(repeat, n):
    return re.sub(r"(^|;)COUNT=\d+", lambda m: f"{m.group(1)}COUNT={n}", repeat)


def need_live(c, tid):
    """2.126.0 D (#1992 A3): a task in the trash is not changed (it is restored first)."""
    if c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()[0]:
        raise Denied(409, tr("The task is in the trash"))


@app.post("/api/tasks/<int:tid>/complete")
def task_complete(tid):
    from ..collab.comments import task_event
    from ..tasks.dependencies import completed_ids, unblock_events
    from ..notify.push import push_handled
    c = db()
    need_task(c, tid)
    need_live(c, tid)  # 2.126.0 D (#1992 A3)
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    b = body()
    # the same recurring task ticked on two devices (one offline): only the first tick advances it
    # 2.126.0 D (#1987): also without expect_due (API, agents) and for two ticks at the same moment
    if t["repeat"] and t["status"] == 0 and (complete_stale(c, tid, b.get("expect_due") or t["due"]) or (
            "TIMES=" in t["repeat"] and b.get("expect_time") and b["expect_time"] != t["due_time"])):  # 2.116.0 D (#2066)
        return jsonify({**one_task(c, tid), "next_due": None, "skipped": True})
    st = int(b.get("status", 2))
    undo = {}
    nxt = do_complete(c, tid, st, undo)
    log_act(c, tid, "wont" if st == -1 else "reopen" if st == 0 else "complete", {"next": nxt} if nxt else None)
    if st == 2:
        task_event(c, tid, "complete")
    if st != 0:
        unblock_events(c, completed_ids(c, tid))
        push_handled(c, me(), [tid])  # 2.0.5: close its notification on my other devices
    bump(c)
    c.commit()
    return jsonify({**one_task(c, tid), "next_due": nxt, "undo": signed(tid, undo)})


def complete_stale(c, tid, due, status=0):
    """2.126.0 D (#1987): takes the task's completion lock; True when another tick changed its status / due since the
    caller read (status, due)."""
    write_lock(c, f"task-{tid}")
    t = c.execute("SELECT status, due FROM tasks WHERE id=?", (tid,)).fetchone()
    return t is None or t["status"] != status or _norm(t["due"]) != _norm(due)


def do_complete(c, tid, status=2, undo=None):
    """undo (dict, filled in): what POST /api/tasks/<id>/undo needs to take this completion back."""
    from ..collab.comments import assignment_events
    from ..family.family import _jparse, FAM_OCC, rot_next, stars_earn, stars_revoke
    write_lock(c, f"task-{tid}")  # 2.126.0 D (#1987): one completion of a task at a time (the row below is then current)
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if status == 2 and t["status"] != 2:  # 2.60.0 C (#1512): "done only after approval" -- every way of completing ends here
        from ..tasks.review import rvw_gate
        e = rvw_gate(c, tid)
        if e:
            raise Denied(409, e)
    from ..lists.rules import rul_fire_done, rul_snap
    rb = rul_snap(c, tid)  # 2.71.0 A (#1457)
    ts = iso(now_utc())
    who = (me() or None) if status != 0 else None  # 0 = public link: nobody's completion (statistics)
    cnt = rr_count(t["repeat"])
    nxt = next_due(t) if status == 2 and (cnt is None or cnt > 1) else None
    nxt_tm = (rmd_next(t) or (0, None))[1] if nxt and "TIMES=" in t["repeat"] else None  # 2.116.0 D (#2066)
    if undo is not None:
        undo.update(op="complete", at=ts, status=t["status"], repeat=t["repeat"], due=t["due"], start=t["start"], due_time=t["due_time"],
                    reminded=t["reminded"], copy_id=None, kids=[], plan_start=t["plan_start"])
        if t["remind_at"]:
            undo["remind_at"] = t["remind_at"]  # 2.111.0 C (#2057): the fixed reminder moves along, undo puts it back
    if status == 2 and t["status"] != 2:
        stars_earn(c, t, ts)  # 2.19.0 (#653): a kid's stars
    elif status == 0 and t["status"] == 2:
        stars_revoke(c, tid, kid=t["completed_by"])
    if status == 2 and t["repeat"] and not nxt:  # last repeat (COUNT used up / past UNTIL): done for good
        c.execute("UPDATE tasks SET repeat='' WHERE id=?", (tid,))
    if nxt:
        # keep a completed copy in the history, move the original forward
        cols = [k for k in t.keys() if k not in ("id", "tt_id", "client_ref")]  # 2.126.0 D (#1990): client_ref
        vals = {k: t[k] for k in cols}
        vals.update(status=2, repeat="", completed_at=ts, updated_at=ts, reminded="[]", completed_by=who, rotation="")
        cur_id = insert_id(c, f"INSERT INTO tasks({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                        [vals[k] for k in cols])
        for r in c.execute("SELECT user_id, tag FROM task_tags WHERE task_id=?", (tid,)).fetchall():
            c.execute("INSERT INTO task_tags(task_id,user_id,tag) VALUES(?,?,?)", (cur_id, r["user_id"], r["tag"]))
        c.execute("INSERT INTO task_field_values(task_id,field_id,value) SELECT ?, field_id, value FROM task_field_values WHERE task_id=?",
                  (cur_id, tid))
        c.execute("INSERT INTO sample_items(user_id,kind,item_id) SELECT user_id, 'task', ? FROM sample_items "
                  "WHERE kind='task' AND item_id=? ON CONFLICT DO NOTHING", (cur_id, tid))
        start = t["start"]
        if start:  # timeline range moves along with the due date
            start = (date.fromisoformat(start) + (date.fromisoformat(nxt) - date.fromisoformat(t["due"]))).isoformat()
        c.execute("UPDATE tasks SET due=?, start=?, plan_start=NULL, reminded='[]', updated_at=? WHERE id=?", (nxt, start, ts, tid))
        from ..tasks.remindat import rat_shift
        rat_shift(c, tid, t["due"], nxt)  # 2.111.0 C (#2057)
        if nxt_tm:
            c.execute("UPDATE tasks SET due_time=? WHERE id=?", (nxt_tm, tid))
        if cnt:
            c.execute("UPDATE tasks SET repeat=? WHERE id=?", (rr_with_count(t["repeat"], cnt - 1), tid))
        rot = rot_next(c, t) if t["rotation"] and (_jparse(t["rotation"]) or {}).get("mode") == "done" else None
        if rot:  # 2.19.0 (#653): the next person's turn
            c.execute("UPDATE tasks SET assignee_id=?, assignee_group_id=NULL, rotation=?, assigned_by=? WHERE id=?",
                      (rot[0], rot[1], who, tid))
            if undo is not None:
                undo["rot"] = [t["assignee_id"], t["rotation"]]
            if rot[0] != t["assignee_id"] and has_request_context():
                assignment_events(c, tid, t["assignee_id"], rot[0])
        occ = (_jparse(t["fam"]) or {}).get("kind") in FAM_OCC  # a birthday's gift ideas keep their ticks (what was given)
        for d in ([] if occ else descendants(c, tid)):
            k = c.execute("SELECT status, completed_at, completed_by FROM tasks WHERE id=?", (d,)).fetchone()
            if undo is not None and k["status"] != 0:
                undo["kids"].append([d, k["status"], k["completed_at"], k["completed_by"]])
            c.execute("UPDATE tasks SET status=0, completed_at=NULL, completed_by=NULL WHERE id=?", (d,))
        if undo is not None:
            undo.update(copy_id=cur_id, next=nxt)
        if t["review"]:  # 2.60.0 C (#1512): the next occurrence needs its own approval
            from ..tasks.review import rvw_after_repeat
            rvw_after_repeat(c, tid)
    else:
        c.execute("UPDATE tasks SET status=?, completed_at=?, completed_by=?, updated_at=? WHERE id=?",
                  (status, ts, who, ts, tid))
        if status != 0:  # completing a parent completes its open subtasks (all levels)
            for d in descendants(c, tid):
                c.execute("UPDATE tasks SET status=?, completed_at=?, completed_by=?, updated_at=? WHERE id=? AND status=0",
                          (status, ts, who, ts, d))
    rul_fire_done(c, tid, cur_id if nxt else None, rb)  # 2.71.0 A (#1457): a recurring task: its completed copy
    return nxt


def undo_sig(tid, u):
    """HMAC over an undo payload (task, user, content): the client hands it back unchanged or not at all."""
    key = UNDO_KEY.get("k") or UNDO_KEY.setdefault("k", gsetting(db(), "undo_key"))
    msg = json.dumps({"tid": tid, "uid": me(), **{k: v for k, v in u.items() if k != "sig"}}, sort_keys=True, default=str)
    return hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()


def signed(tid, u):
    return {**u, "sig": undo_sig(tid, u)} if u else u


UNDO_KEY = {}


def undo_status(c, tid, u):
    """Takes back a completion (op complete: the dict do_complete filled) or a reopen (op reopen: the
    status / completed_at / completed_by the task had). The caller checked write access. Returns an
    error text or None. Only acts while the task is still in the state the action left it in."""
    from ..family.family import stars_add, stars_revoke
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t or not isinstance(u, dict) or not hmac.compare_digest(str(u.get("sig") or ""), undo_sig(tid, u)):
        return tr("unknown")
    ts = iso(now_utc())
    people = list_people(c, t["list_id"])

    def who(v):  # a completer from the client: only someone of this list, else me
        try:
            return int(v) if int(v) in people else me()
        except (TypeError, ValueError):
            return me()

    def when(v):
        try:
            parse_iso(str(v))
            return str(v)
        except ValueError:
            return ts
    if u.get("op") == "reopen":
        st = int(u.get("status") or 0)
        if t["status"] != 0 or st not in (2, -1):
            return tr("Changed in the meantime, nothing to undo")
        if st == 2:  # 2.60.0 (#1512, review): undoing a reopen completes again -- only past an open review gate
            from ..tasks.review import rvw_gate
            e = rvw_gate(c, tid)
            if e:
                return e
        c.execute("UPDATE tasks SET status=?, completed_at=?, completed_by=?, updated_at=? WHERE id=?",
                  (st, when(u.get("completed_at")), who(u.get("completed_by")), ts, tid))
        if st == 2:  # 2.19.0 (#653): the kid's stars of that completion come back
            stars_add(c, who(u.get("completed_by")), t, when(u.get("completed_at")))
        log_act(c, tid, "wont" if st == -1 else "complete")
        return None
    if u.get("op") != "complete" or not u.get("at"):
        return tr("unknown")
    at = str(u["at"])
    cp = u.get("copy_id")
    if cp:  # recurring: drop the completed copy, move the task back to the occurrence it was on
        row = c.execute("SELECT * FROM tasks WHERE id=?", (int(cp),)).fetchone()
        if t["status"] != 0 or t["due"] != u.get("next") or not row or row["list_id"] != t["list_id"] or row["completed_at"] != at or row["status"] == 0 \
                or row["created_at"] != t["created_at"] or row["title"] != t["title"] or row["repeat"] \
                or row["id"] < tid or row["parent_id"] != t["parent_id"]:
            return tr("Changed in the meantime, nothing to undo")
        files = attachment_files(c, [row["id"]])
        c.execute("DELETE FROM tasks WHERE id=?", (row["id"],))
        unlink_files(files)
        try:
            due = date.fromisoformat(str(u.get("due"))).isoformat()
            start = date.fromisoformat(str(u["start"])).isoformat() if u.get("start") else None
            rem = json.dumps([str(x) for x in json.loads(u.get("reminded") or "[]")][-20:])
        except (ValueError, TypeError):
            return tr("unknown")
        ps = u.get("plan_start") if valid_plan_start(u.get("plan_start")) else None
        c.execute("UPDATE tasks SET due=?, start=?, plan_start=?, repeat=?, reminded=?, updated_at=? WHERE id=?",
                  (due, start, ps, str(u.get("repeat") or "")[:500], rem, ts, tid))
        if u.get("remind_at") and valid_plan_start(u.get("remind_at")):  # 2.111.0 C (#2057)
            c.execute("UPDATE tasks SET remind_at=? WHERE id=?", (u["remind_at"], tid))
        if "TIMES=" in str(u.get("repeat") or "") and valid_hm(u.get("due_time")):  # 2.116.0 D (#2066)
            c.execute("UPDATE tasks SET due_time=? WHERE id=?", (u["due_time"], tid))
        rot = u.get("rot")  # 2.19.0 (#653): whose turn it was (signed with the rest of the undo record)
        if isinstance(rot, list) and len(rot) == 2 and (rot[0] is None or isinstance(rot[0], int)) and isinstance(rot[1], str):
            c.execute("UPDATE tasks SET assignee_id=?, rotation=? WHERE id=?", (rot[0] if rot[0] in people else None, rot[1][:2000], tid))
        for k in u.get("kids") or []:
            try:
                d, st, cat, cby = int(k[0]), int(k[1]), when(k[2]), who(k[3])
            except (TypeError, ValueError, IndexError):
                continue
            if st not in (2, -1):
                continue
            c.execute("UPDATE tasks SET status=?, completed_at=?, completed_by=? WHERE id=? AND parent_id IS NOT NULL AND status=0 AND list_id=?",
                      (st, cat, cby, d, t["list_id"]))
    else:
        if t["status"] == 0 or t["completed_at"] != at:
            return tr("Changed in the meantime, nothing to undo")
        c.execute("UPDATE tasks SET status=0, completed_at=NULL, completed_by=NULL, updated_at=? WHERE id=?", (ts, tid))
        if u.get("repeat") and not t["repeat"]:  # the last occurrence had ended the repetition
            c.execute("UPDATE tasks SET repeat=? WHERE id=?", (str(u["repeat"])[:500], tid))
        for d in descendants(c, tid):  # subtasks completed together with it
            c.execute("UPDATE tasks SET status=0, completed_at=NULL, completed_by=NULL, updated_at=? WHERE id=? AND completed_at=?",
                      (ts, d, at))
    stars_revoke(c, tid, at=at)  # 2.19.0 (#653): a kid's stars for exactly this completion
    # the "completed" News items this completion created for others
    c.execute("DELETE FROM notifications WHERE task_id=? AND kind='complete' AND actor_id=? AND created_at>=?",
              (tid, me(), at))
    fam = [tid, *descendants(c, tid)]  # ... and the "unblock" items / lines it caused (the tasks wait again)
    q = ",".join("?" * len(fam))
    c.execute(f"DELETE FROM notifications WHERE kind='unblock' AND actor_id=? AND created_at>=? AND (data->>'blocker') IN ({q})",
              (me(), at, *fam))
    c.execute(f"DELETE FROM activity WHERE kind='unblocked' AND user_id=? AND created_at>=? AND (data->>'id') IN ({q})",
              (me(), at, *fam))
    log_act(c, tid, "reopen")
    return None


@app.post("/api/tasks/<int:tid>/undo")
def task_undo(tid):
    """Undo toast: takes back the completion / reopen described by the body (see undo_status)."""
    c = db()
    need_task(c, tid)
    e = undo_status(c, tid, body())
    if e:
        c.rollback()
        return err(e, 409)
    bump(c)
    c.commit()
    return jsonify(one_task(c, tid))


@app.post("/api/tasks/<int:tid>/skip")
def task_skip(tid):
    """'Skip this occurrence': move a recurring task to its next date without a done copy."""
    c = db()
    need_task(c, tid)
    need_live(c, tid)  # 2.126.0 D (#1992 A3)
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t["repeat"] or not t["due"]:
        return err(tr("Not a recurring task"))
    from ..tasks.validation import lock_problem
    e = lock_problem(c, t, {"due": ""})  # 2.36.0 (#1118): skipping moves the date, which a locked task keeps (app writes)
    if e:
        return err(e)
    cnt = rr_count(t["repeat"])
    base = dict(t)
    base["repeat_from"] = "due"  # skipping always means: the next regular date
    nxt = next_due(base) if cnt is None or cnt > 1 else None
    if not nxt:
        return err(tr("This is already the last occurrence"))
    start = t["start"]
    if start:
        start = (date.fromisoformat(start) + (date.fromisoformat(nxt) - date.fromisoformat(t["due"]))).isoformat()
    rep_new = rr_with_count(t["repeat"], cnt - 1) if cnt else t["repeat"]
    c.execute("UPDATE tasks SET due=?, start=?, plan_start=NULL, repeat=?, reminded='[]', updated_at=? WHERE id=?",
              (nxt, start, rep_new, iso(now_utc()), tid))
    from ..tasks.remindat import rat_shift
    rat_shift(c, tid, t["due"], nxt)  # 2.111.0 C (#2057)
    if "TIMES=" in t["repeat"] and rmd_next(base):  # 2.116.0 D (#2066): skipping = the next time
        c.execute("UPDATE tasks SET due_time=? WHERE id=?", (rmd_next(base)[1], tid))
    log_act(c, tid, "skip", {"next": nxt})
    bump(c)
    c.commit()
    return jsonify({**one_task(c, tid), "next_due": nxt})


@app.post("/api/tasks/<int:tid>/reopen")
def task_reopen(tid):
    from ..family.family import stars_revoke
    c = db()
    need_task(c, tid)
    need_live(c, tid)  # 2.126.0 D (#1992 A3)
    old = c.execute("SELECT status, completed_at, completed_by FROM tasks WHERE id=?", (tid,)).fetchone()
    from ..lists.rules import rul_fire, rul_snap
    rb = rul_snap(c, tid)  # 2.71.0 A (#1457)
    if old["status"] != 0:
        log_act(c, tid, "reopen")
        stars_revoke(c, tid, at=old["completed_at"], kid=old["completed_by"])  # 2.19.0 (#653)
    c.execute("UPDATE tasks SET status=0, completed_at=NULL, completed_by=NULL, updated_at=? WHERE id=?", (iso(now_utc()), tid))
    rul_fire(c, tid, rb)
    bump(c)
    c.commit()
    undo = {"op": "reopen", "status": old["status"], "completed_at": old["completed_at"], "completed_by": old["completed_by"]}
    return jsonify({**one_task(c, tid), "undo": signed(tid, undo) if old["status"] != 0 else None})


@app.delete("/api/tasks/<int:tid>")
def task_delete(tid):
    from ..integrations.webhooks import wh_note
    c = db()
    role = need_task(c, tid)
    if role == "participant":
        raise Denied(403, tr("Participants cannot delete tasks"))
    files = []
    if request.args.get("hard") == "1":
        if role != "owner":  # shared list: edit members only move tasks to the trash
            raise Denied(403, tr("Only the list owner can delete tasks permanently"))
        wh_note(c, tid, "purge")
        files = hard_delete(c, [tid])
    else:
        trash_task(c, tid)
    bump(c)
    c.commit()
    unlink_files(files)
    return jsonify(ok=True)


def trash_task(c, tid):
    """Moves a task (and its subtasks) to the trash with a history line (web client, REST API)."""
    do_delete(c, tid)
    log_act(c, tid, "delete")


def do_delete(c, tid):
    ts = iso(now_utc())
    for i in [tid, *descendants(c, tid)]:
        c.execute("UPDATE tasks SET deleted_at=COALESCE(deleted_at, ?) WHERE id=?", (ts, i))
    if (c.execute("SELECT ms FROM tasks WHERE id=?", (tid,)).fetchone() or [0])[0]:
        ms_cleanup(c)  # 2.18.0 (#430): a trashed milestone keeps its links (restored with it), see ms_cleanup


@app.post("/api/tasks/<int:tid>/restore")
def task_restore(tid):
    from ..lists.listtrash import otr_err_task
    c = db()
    e = otr_err_task(c, tid)  # 2.102.0 A (#1988): a task of a deleted list comes back only with its list (same place)
    if e is not None:
        return e
    need_task(c, tid)
    restore_task(c, tid)
    bump(c)
    c.commit()
    return jsonify(ok=True)


def restore_task(c, tid):
    r = c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
    if r:
        c.execute("UPDATE tasks SET deleted_at=NULL WHERE id=?", (tid,))
        for d in descendants(c, tid):  # children deleted together with it come back too
            c.execute("UPDATE tasks SET deleted_at=NULL WHERE id=? AND deleted_at=?", (d, r["deleted_at"]))
        # restoring a subtask whose parent is gone makes it top-level
        c.execute("""UPDATE tasks SET parent_id=NULL WHERE id=? AND parent_id IN
                     (SELECT id FROM tasks WHERE deleted_at IS NOT NULL)""", (tid,))
        if r["deleted_at"]:
            log_act(c, tid, "restore")


@app.post("/api/tasks/purge-done")
def purge_done():
    """Settings > 'Delete all completed': every done / won't-do task in MY lists -> trash
    (shared lists of other owners are left alone)."""
    c = db()
    n = c.execute("""UPDATE tasks SET deleted_at=? WHERE status!=0 AND deleted_at IS NULL
                     AND list_id IN (SELECT id FROM lists WHERE owner_id=?)""", (iso(now_utc()), me())).rowcount
    bump(c)
    c.commit()
    return jsonify(count=n)


def purge_lists(c, uid=None):
    """Ids of the lists whose trash the user may empty for good: the lists they OWN; instance admins (2.0.5) also the
    shared lists of other owners where they may edit (member or list admin). Everyone else's deleted tasks in shared
    lists stay in the trash: only the list owner deletes them permanently."""
    uid = uid or me()
    u = c.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()
    q, a = (wr_sql(), (uid, uid)) if u and u["is_admin"] else ("(SELECT id FROM lists WHERE owner_id=?)", (uid,))
    return {r[0] for r in c.execute(f"SELECT id FROM lists WHERE id IN {q}", a)}


@app.delete("/api/trash")
def trash_empty():
    """Hard-deletes the trash of the lists purge_lists() allows. {deleted, kept}: kept = deleted tasks the user sees in
    the trash but may not delete for good (shared lists of other owners)."""
    c = db()
    uid = me()
    ok = purge_lists(c, uid)
    rows = c.execute(f"SELECT id, list_id FROM tasks WHERE deleted_at IS NOT NULL AND list_id IN {wr_sql()}", (uid, uid)).fetchall()
    ids = [r["id"] for r in rows if r["list_id"] in ok]
    files = hard_delete(c, ids, lists=ok)
    bump(c)
    c.commit()
    unlink_files(files)
    return jsonify(ok=True, deleted=len(ids), kept=len(rows) - len(ids))
