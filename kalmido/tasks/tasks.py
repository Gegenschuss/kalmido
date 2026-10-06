"""Creating and changing tasks: milestones, moving subtrees, tags, assignees, waiting on external."""
from datetime import date, timedelta
from flask import jsonify

from ..core.config import app, PUBLIC_URL
from ..core.schema import MAX_DEPTH, USER_DEFAULTS
from ..core.i18n import tr
from ..core.db import body, bump, db, err, inbox_default, iso, now_utc
from ..accounts.session import me
from ..core.access import (
    Denied, list_people, list_role, my_inbox, need_collab, need_list, need_project, need_task, task_visible, WRITE_ROLES,
)
from ..core.serializers import attachment_files, load_tasks
from ..lists.lists import LIST_FIELDS
from ..lists.groups import check_group_assignee, grp_assign_events
from ..tasks.validation import (
    check_parent, check_url, clean_task, log_act, TASK_FIELDS, ticket_template, valid_date, valid_hm,
)


# ---- 2.18.0 (#430): milestones. A milestone is a task with ms = 1 (top level, no subtasks, a date is optional); a task
# belongs to at most one milestone of its OWN list (milestone_id). Moving a task to another list, trashing / deleting the
# milestone or turning it into a normal task clears the link (ms_cleanup), so milestone_id never points anywhere else.
def ms_target(c, mid, lid, tid=None):
    """None when a task (tid, in list lid) may belong to milestone mid, else an error text."""
    if mid is None:
        return None
    r = c.execute("SELECT list_id, ms, deleted_at FROM tasks WHERE id=?", (mid,)).fetchone()
    if not r or r["deleted_at"] or not r["ms"] or mid == tid or r["list_id"] != lid:
        return tr("Not a milestone of this list")
    return None


def ms_cleanup(c):
    """Drops every milestone link whose milestone is gone (deleted for good, no milestone any more, another list).
    2.18.0 (owner decision): a milestone in the TRASH keeps its links, so restoring it brings its tasks back with it; while it
    is in the trash the link is inert (clients only show milestones they can see, new links need an open milestone)."""
    c.execute("""UPDATE tasks SET milestone_id=NULL WHERE milestone_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM tasks m
                 WHERE m.id=tasks.milestone_id AND m.ms=1 AND m.list_id=tasks.list_id)""")


def can_move(c, src, dst):
    """May the current user move a task from list src into dst? Always within a list and for the owner of
    src; an edit member only if nobody who sees the task now loses access (dst is seen by everyone who sees
    src) -- otherwise a member could pull a shared task (with subtasks and comments) away from the owner."""
    return src == dst or list_role(c, src) == "owner" or list_people(c, src) <= list_people(c, dst)


def check_move(c, src, dst):
    if not can_move(c, src, dst):
        raise Denied(403, tr("Only the list owner can move tasks out of this shared list"))


def move_subtree(c, tid, lid):
    """Subtasks follow their parent into list lid (all levels). A subtask in another list that the current
    user may not move out of (subtask of a foreign parent) stays in its list and becomes top level there."""
    people, ok = list_people(c, lid), {}
    done, level, n = {tid}, [tid], 0
    while level and n < MAX_DEPTH + 7:
        q = ",".join("?" * len(level))
        nxt = []
        for k in c.execute(f"SELECT id, list_id, assignee_id FROM tasks WHERE parent_id IN ({q})", level).fetchall():
            if k["id"] in done:
                continue
            done.add(k["id"])
            if k["list_id"] not in ok:
                ok[k["list_id"]] = can_move(c, k["list_id"], lid)
            if not ok[k["list_id"]]:
                c.execute("UPDATE tasks SET parent_id=NULL WHERE id=?", (k["id"],))
                continue
            c.execute("UPDATE tasks SET list_id=? WHERE id=?", (lid, k["id"]))
            if k["assignee_id"] and k["assignee_id"] not in people:
                c.execute("UPDATE tasks SET assignee_id=NULL WHERE id=?", (k["id"],))
            nxt.append(k["id"])
        level, n = nxt, n + 1


def hard_delete(c, ids, lists=None):
    """Permanently deletes tasks (subtasks go with them: ON DELETE CASCADE). Subtasks in lists the current
    user does not own (lists: set of list ids where they may, see purge_lists) are detached first and stay with
    their list. Returns the attachment paths to unlink."""
    for tid in ids:
        done, level, n = {tid}, [tid], 0
        while level and n < MAX_DEPTH + 7:
            q = ",".join("?" * len(level))
            nxt = []
            for k in c.execute(f"SELECT id, list_id FROM tasks WHERE parent_id IN ({q})", level).fetchall():
                if k["id"] in done:
                    continue
                done.add(k["id"])
                if (k["list_id"] not in lists) if lists is not None else list_role(c, k["list_id"]) != "owner":
                    c.execute("UPDATE tasks SET parent_id=NULL WHERE id=?", (k["id"],))
                else:
                    nxt.append(k["id"])
            level, n = nxt, n + 1
    files = attachment_files(c, ids)
    for tid in ids:
        c.execute("DELETE FROM tasks WHERE id=?", (tid,))
    ms_cleanup(c)  # 2.18.0 (#430)
    return files


def set_tags(c, tid, tags, uid=None):
    uid = uid or me()
    c.execute("DELETE FROM task_tags WHERE task_id=? AND user_id=?", (tid, uid))
    for t in dict.fromkeys(x.strip().lstrip("#") for x in tags if x and x.strip().lstrip("#")):
        c.execute("INSERT INTO task_tags(task_id,user_id,tag) VALUES(?,?,?)", (tid, uid, t))


def my_tags(c, tid):
    return [r[0] for r in c.execute("SELECT tag FROM task_tags WHERE task_id=? AND user_id=?", (tid, me()))]


def one_task(c, tid):
    return load_tasks(c, "id=?", (tid,))[0]


def participant_assignee(c, cur, f):
    """Error text when a participant's change of the assignee (f) is not allowed, else None. Participants cannot
    hand tasks to others or take them away (an unassigned task would vanish from their view); on a new subtask under
    one of their tasks (cur None) they may leave it unassigned or take it themselves."""
    from ..tasks.lifecycle import _norm
    if "assignee_group_id" in f and f["assignee_group_id"] != (cur["assignee_group_id"] if cur is not None else None):
        return tr("Participants cannot change who a task is assigned to")  # 2.10.0 (#441): "Take it" is POST .../take
    if "assignee_id" not in f:
        return None
    new = f["assignee_id"]
    if cur is None:
        return None if new in (None, me()) else tr("Participants can only assign tasks to themselves")
    if _norm(new) == _norm(cur["assignee_id"]):
        return None
    return tr("Participants cannot change who a task is assigned to")


def check_assignee(c, lid, aid):
    """None if aid may be assigned in list lid, else an error message."""
    if aid is None:
        return None
    need_collab()
    try:
        aid = int(aid)
    except (TypeError, ValueError):
        return tr("unknown user")
    if aid not in list_people(c, lid):
        return tr("Only the owner or a member of the list can be assigned")
    # 2.26.0 (#928): an agent only by someone it is open to in this list (owner / list admins, or everyone with "Members
    # may see and use the agent")
    from ..agents.core import agent_ids, agent_usable
    if aid in agent_ids(c) and aid != me() and not agent_usable(c, aid, me(), lid):
        return tr("The list owner has not opened this agent to members")
    return None


# 2.2.1 (#359): the fields the web API's task / list / comment endpoints know (others: warning, see web_fields)
WEB_TASK_NEW = frozenset(TASK_FIELDS) | {"tags", "ltags", "fields", "people"}
WEB_TASK_EDIT = WEB_TASK_NEW | {"add_tags", "_prev", "_act"}
WEB_LIST_NEW = frozenset({"name", "color", "folder", "view", "kind", "checklist", "done_at_bottom", "dep_shift", "tickets", "ptype", "family"})
WEB_LIST_EDIT = frozenset(LIST_FIELDS) | {"client_id", "rate", "agent_tidy", "tidy_agent_id", "listen_agent_ids", "agent_members", "agent_peers", "_prev", "ticket_tpl", "day_hours", "done_at_bottom", "columns", "ptype"}
WEB_COMMENT = frozenset({"body", "suggestion"})


@app.post("/api/tasks")
def task_create():
    from ..tasks.lifecycle import repeat_problem
    from ..collab.comments import task_event
    from ..personal.timetrack import field_alias, web_fields
    from ..tasks.dependencies import newtask_events
    from ..lists.fields import set_field_values
    from ..agents.core import agent_added_events, agent_task_mentions, agent_tidy_events
    from ..collab.reactions import set_ltags
    from ..family.family import is_shop, people_set, rot_apply, shop_area_of, shop_remember
    b = web_fields(field_alias(body(), "content", "notes"), WEB_TASK_NEW, "POST /api/tasks")
    f = clean_task(b)
    if not f.get("title"):
        return err(tr("Title missing"))
    c = db()
    e = check_parent(c, None, f.get("parent_id"))
    if e:
        return err(e)
    if f.get("parent_id"):  # subtasks live in their parent's list
        role = need_task(c, f["parent_id"])
        f["list_id"] = c.execute("SELECT list_id FROM tasks WHERE id=?", (f["parent_id"],)).fetchone()[0]
    elif f.get("list_id"):
        role = list_role(c, f["list_id"])
        if role != "participant":
            need_list(c, f["list_id"])
    else:
        role, f["list_id"] = "owner", my_inbox(c)
    if role == "participant":  # 1.10.0: a participant's new task is theirs (else it would vanish from their view)
        e = participant_assignee(c, None, f)
        if e:
            return err(e, 403)
        if not f.get("parent_id"):
            f["assignee_id"] = me()
    if f.get("section_id") and not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?",
                                              (f["section_id"], f["list_id"])).fetchone():
        f["section_id"] = None
    shop = not f.get("parent_id") and is_shop(c, f["list_id"])  # 2.19.0 (#653): a new item goes to the area it had last time
    if shop and not f.get("section_id"):
        f["section_id"] = shop_area_of(c, f["list_id"], f["title"])
    elif shop:
        shop_remember(c, f["list_id"], f["title"], f["section_id"])
    if f.get("rotation"):
        if role == "participant":
            return err(tr("Participants cannot change who a task is assigned to"), 403)
        e = rot_apply(c, f, None, f["list_id"])
        if e:
            return err(e)
    if f.get("assignee_group_id"):  # 2.10.0 (#441): a person or a group, never both
        f["assignee_id"] = None
    if f.get("ms"):  # 2.18.0 (#430): a milestone is a top-level task and belongs to no milestone itself
        if f.get("parent_id"):
            return err(tr("A milestone cannot be a subtask"))
        f["milestone_id"] = None
    e = ms_target(c, f.get("milestone_id"), f["list_id"])
    if e:
        return err(e)
    e = check_assignee(c, f["list_id"], f.get("assignee_id")) or check_group_assignee(c, f["list_id"], f.get("assignee_group_id")) \
        or check_url(f) or repeat_problem(f.get("repeat"), f.get("due"))
    if e:
        return err(e)
    if "sort" not in f:
        f["sort"] = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS ?",
                              (f["list_id"], f.get("parent_id"))).fetchone()[0]
        if f.get("parent_id"):  # subtasks append at the end
            f["sort"] = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM tasks WHERE parent_id=?",
                                  (f["parent_id"],)).fetchone()[0]
        elif c.execute("SELECT 1 FROM lists WHERE id=? AND checklist=1", (f["list_id"],)).fetchone():
            # 2.13.0 (#453 P19): a list with "done at the bottom" (shopping, packing) adds new items at the end, in the
            # order they are typed
            f["sort"] = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM tasks WHERE list_id=? AND parent_id IS NULL",
                                  (f["list_id"],)).fetchone()[0]
    if b.get("fields"):
        need_project(c, f["list_id"], "fields")
    if f.get("ttype") and not (f.get("content") or "").strip():  # 2.4.0 (#340): a new bug / feature gets its note template
        tpl = ticket_template(c, f["list_id"], f["ttype"])
        if tpl:
            f["content"] = tpl
    ts = iso(now_utc())
    f["created_by"] = me()
    if f.get("assignee_id") or f.get("assignee_group_id"):
        f["assigned_by"] = me()
    cols = list(f) + ["created_at", "updated_at"]
    cur = c.execute(f"INSERT INTO tasks({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                    [f[k] for k in f] + [ts, ts])
    if b.get("tags"):
        set_tags(c, cur.lastrowid, b["tags"])
    if b.get("ltags"):
        set_ltags(c, cur.lastrowid, b["ltags"], log=False)  # BadInput: 400, nothing stored
    if b.get("fields"):
        set_field_values(c, cur.lastrowid, f["list_id"], b["fields"], log=False)  # BadInput: 400, nothing stored
    if b.get("people"):  # 2.19.0 (#653): who comes along
        e = people_set(c, cur.lastrowid, f["list_id"], b["people"])
        if e:
            c.rollback()
            return err(e)
    log_act(c, cur.lastrowid, "created")
    agent_task_mentions(c, cur.lastrowid)
    agent_tidy_events(c, cur.lastrowid)
    agent_added_events(c, cur.lastrowid)  # 2.23.0 (#795)
    if f.get("assignee_id"):
        task_event(c, cur.lastrowid, "assign")
    if f.get("assignee_group_id"):
        grp_assign_events(c, cur.lastrowid, f["assignee_group_id"])
    newtask_events(c, cur.lastrowid)
    if f.get("parent_id"):
        log_act(c, f["parent_id"], "subtask", {"id": cur.lastrowid, "title": f["title"][:200]})
    bump(c)
    c.commit()
    return jsonify(one_task(c, cur.lastrowid))


# ---- 2.1.0 (#335): "Waiting on external" (German "Warten auf Extern"): who / what the task waits for + a follow-up day.
# The task keeps its status (open). On the follow-up day (at the all-day reminder time of the person it is for) that
# person gets a push "Follow up" + a News item, and every agent that follows the task (assignee, creator, commented) the
# event followup_due. Once per date; a new date fires again. Clearing it is one call (DELETE).
WAIT_NOTE_MAX = 300


def set_waiting(c, tid, b):
    """{note?, until?} -> sets / changes the waiting state (caller commits). BadInput on invalid values."""
    from ..personal.timetrack import BadInput, UnknownFields
    unknown = sorted(k for k in b if k not in ("note", "until"))
    if unknown:
        raise UnknownFields(unknown)
    note = b.get("note")
    if note is not None and not isinstance(note, str):
        raise BadInput(tr("Invalid value: {0}", "note"))
    note = (note or "").strip()[:WAIT_NOTE_MAX]
    until = b.get("until") or None
    if until is not None and not valid_date(until):
        raise BadInput(tr("Invalid value: {0}", "until"))
    cur = c.execute("SELECT waiting_at, wait_until, wait_fired FROM tasks WHERE id=?", (tid,)).fetchone()
    fired = cur["wait_fired"] if cur["waiting_at"] and cur["wait_until"] == until else ""
    c.execute("UPDATE tasks SET waiting_at=?, wait_note=?, wait_until=?, wait_by=?, wait_fired=?, updated_at=? WHERE id=?",
              (cur["waiting_at"] or iso(now_utc()), note, until, me() or None, fired, iso(now_utc()), tid))
    log_act(c, tid, "waiting", {"note": note[:200], "until": until})


def clear_waiting(c, tid):
    """True when the task was waiting (caller commits)."""
    if not c.execute("SELECT waiting_at FROM tasks WHERE id=?", (tid,)).fetchone()["waiting_at"]:
        return False
    c.execute("UPDATE tasks SET waiting_at=NULL, wait_note='', wait_until=NULL, wait_by=NULL, wait_fired='', updated_at=? WHERE id=?",
              (iso(now_utc()), tid))
    log_act(c, tid, "waiting_rm")
    return True


@app.put("/api/tasks/<int:tid>/waiting")
def task_waiting_set(tid):
    c = db()
    need_task(c, tid)
    set_waiting(c, tid, body())
    bump(c)
    c.commit()
    return jsonify(one_task(c, tid))


@app.delete("/api/tasks/<int:tid>/waiting")
def task_waiting_clear(tid):
    c = db()
    need_task(c, tid)
    if clear_waiting(c, tid):
        bump(c)
        c.commit()
    return jsonify(one_task(c, tid))


def _wd_followups(c, users, S, LG, now):
    """The follow-up day of waiting tasks: push + News to the person it is for, followup_due to the following agents."""
    from ..notify.push import _wd_fail
    today = now.date().isoformat()
    rows = c.execute("""SELECT t.*, l.name AS list_name, l.is_inbox AS list_inbox, l.owner_id AS list_owner FROM tasks t
                        JOIN lists l ON l.id=t.list_id WHERE t.waiting_at IS NOT NULL AND t.wait_until IS NOT NULL
                        AND t.wait_until<=? AND t.wait_fired!=t.wait_until AND t.status=0 AND t.deleted_at IS NULL
                        AND l.archived=0""", (today,)).fetchall()
    for t in rows:
        try:
            _wd_followup(c, t, users, S, LG, now)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "follow-up of task", t["id"], e)


def _wd_followup(c, t, users, S, LG, now):
    from ..collab.comments import collab_user
    from ..collab.news import news_add, notif_ok
    from ..notify.push import notify, push_prio
    from ..api.v1 import waiting_of
    from ..agents.core import agent_emit, agent_ids, agent_task_data
    ag = agent_ids(c)
    rcpt = next((u for u in (t["assignee_id"], t["created_by"], t["wait_by"], t["list_owner"])
                 if u and u in users and u not in ag and (u == t["list_owner"] or task_visible(c, t["id"], u, full=True))), None)
    s, lg = S.get(rcpt, USER_DEFAULTS), LG.get(rcpt, "en")
    allday = s.get("allday_time") if valid_hm(s.get("allday_time")) else "09:00"
    if t["wait_until"] == now.date().isoformat() and now.strftime("%H:%M") < allday:
        return  # today, but not yet the time of day
    c.execute("UPDATE tasks SET wait_fired=? WHERE id=?", (t["wait_until"], t["id"]))
    push = None
    if rcpt and task_visible(c, t["id"], rcpt, full=True):
        cs = collab_user(c, rcpt, None)
        if cs:
            news_add(c, rcpt, "followup", task_id=t["id"], data={"note": t["wait_note"][:200], "until": t["wait_until"]}, s=cs)
        if notif_ok(c, rcpt, s, "followup", "push"):
            lname = tr("Inbox", lg=lg) if t["list_inbox"] and inbox_default(t["list_name"]) else t["list_name"]
            push = (tr("Follow up: {0}", t["title"], lg=lg),
                    (tr("Waiting on: {0}", t["wait_note"], lg=lg) + " · " if t["wait_note"] else "") + lname)
    follow = {t["assignee_id"], t["created_by"]} | {r[0] for r in c.execute(
        "SELECT DISTINCT user_id FROM comments WHERE task_id=? AND deleted_at IS NULL", (t["id"],))}
    for aid in sorted(agent_ids(c) & follow):
        if task_visible(c, t["id"], aid, full=True):
            agent_emit(c, aid, "followup_due", agent_task_data(c, t["id"], aid, waiting=waiting_of(t)), actor=None)
    c.commit()  # before the push: sending it writes to the database itself (push tags)
    if push:
        notify(rcpt, push[0], push[1], push_prio(s), f"{PUBLIC_URL}/#t/{t['id']}", s=s, task=t["id"])


@app.patch("/api/tasks/<int:tid>")
def task_update(tid):
    from ..tasks.lifecycle import apply_update
    from ..personal.timetrack import field_alias, web_fields
    c = db()
    need_task(c, tid)
    conflicts = []
    old = c.execute("SELECT due, status, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
    b = web_fields(field_alias(body(), "content", "notes"), WEB_TASK_EDIT, "PATCH /api/tasks/{tid}")
    e = apply_update(c, tid, b, conflicts)
    if e:
        return err(e)
    new_due = c.execute("SELECT due FROM tasks WHERE id=?", (tid,)).fetchone()[0]
    shifted = dep_shift(c, tid, old["due"], new_due) if old["status"] == 0 and not old["deleted_at"] else []
    bump(c)
    c.commit()
    return jsonify({**one_task(c, tid), "conflicts": conflicts, "shifted": shifted})


# "Move dependent tasks along" (list setting dep_shift, package D2): when a task's due date moves LATER, the open
# tasks waiting on it that would now start before it is due move by the same number of days (start and due, so
# the duration stays), and so on down the chain. Only tasks in lists with the setting on that the user may change,
# breadth-first, at most DEP_SHIFT_MAX tasks and DEP_SHIFT_DEPTH levels, each task once. Every move is a normal
# change (activity line, reminders re-armed, webhooks). Moving a task earlier never moves anything.
DEP_SHIFT_MAX, DEP_SHIFT_DEPTH = 50, 10


def dep_shift(c, root, old_due, new_due, seen=None, moved=None):
    """Returns [{id, title, start, due, prev_start, prev_due}] of the tasks moved along. seen / moved: shared by the
    calls of one request (D3: a whole list moved -- its own tasks are never moved twice, the cap counts once)."""
    from ..tasks.lifecycle import apply_update
    try:
        delta = (date.fromisoformat(new_due) - date.fromisoformat(old_due)).days if old_due and new_due else 0
    except ValueError:
        return []
    moved = [] if moved is None else moved
    if delta <= 0:
        return moved
    uid = me()
    seen = {root} if seen is None else seen
    seen.add(root)
    level = [(root, new_due)]
    for _ in range(DEP_SHIFT_DEPTH):
        nxt = []
        for bid, bdue in level:
            for w in c.execute("""SELECT t.id, t.title, t.start, t.due, t.list_id FROM task_deps d JOIN tasks t ON t.id=d.task_id
                                  JOIN lists l ON l.id=t.list_id
                                  WHERE d.blocker_id=? AND t.status=0 AND t.deleted_at IS NULL AND t.due IS NOT NULL
                                  AND l.dep_shift=1 AND l.kind='project' ORDER BY t.id""", (bid,)).fetchall():
                if w["id"] in seen or (w["start"] or w["due"]) >= bdue or list_role(c, w["list_id"], uid) not in WRITE_ROLES:
                    continue
                if len(moved) >= DEP_SHIFT_MAX:
                    return moved
                seen.add(w["id"])
                try:
                    nd = (date.fromisoformat(w["due"]) + timedelta(days=delta)).isoformat()
                    ns = (date.fromisoformat(w["start"]) + timedelta(days=delta)).isoformat() if w["start"] else None
                except (ValueError, OverflowError):
                    continue
                if apply_update(c, w["id"], {"due": nd, "start": ns, "_act": "dep_shift"}):
                    continue
                moved.append({"id": w["id"], "title": w["title"], "start": ns, "due": nd, "prev_start": w["start"], "prev_due": w["due"]})
                nxt.append((w["id"], nd))
        if not nxt:
            break
        level = nxt
    return moved
