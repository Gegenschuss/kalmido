"""Creating and changing tasks: milestones, moving subtrees, tags, assignees, waiting on external."""
from flask import g, has_request_context, jsonify

from ..core.config import app, PUBLIC_URL
from ..core.pg import insert_id, st_ids, write_lock
from ..core.schema import MAX_DEPTH, USER_DEFAULTS
from ..core.i18n import tr
from ..core.db import body, bump, db, err, inbox_default, iso, now_utc
from ..accounts.session import me
from ..core.access import (
    Denied, list_people, list_role, my_inbox, need_collab, need_list, need_task, ov_open, ov_role, task_visible,
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
    from ..lists.sprints import spr_cleanup
    spr_cleanup(c)  # 2.60.0 (#343): sprint links follow the same rule (a sprint of the task's own list)


def can_move(c, src, dst):
    """May the current user move a task from list src into dst? Always within a list and for the owner of
    src; an edit member only if nobody who sees the task now loses access (dst is seen by everyone who sees
    src) -- otherwise a member could pull a shared task (with subtasks and comments) away from the owner."""
    if src == dst or list_role(c, src) == "owner":
        return True
    if not list_people(c, src) <= list_people(c, dst):  # group / folder shares are member rows (materialized): counted here
        return False
    # 2.86.0 (N21): readers through "Everyone in the organisation" are no member rows: dst must be open to the same organisation
    q = "SELECT org_id, life, family, org_visibility FROM lists WHERE id=?"
    rs, rd = c.execute(q, (src,)).fetchone(), c.execute(q, (dst,)).fetchone()
    return not (rs and ov_open(rs)) or bool(rd and ov_open(rd) and rd["org_id"] == rs["org_id"])


def check_move(c, src, dst):
    if not can_move(c, src, dst):
        raise Denied(403, tr("Only the list owner can move tasks out of this shared list"))
    if src != dst:  # 2.64.0 (#1864): into another space -> the moved tasks' files get its key (after the commit)
        from ..core.orgcrypt import oc_enabled, oc_list_space
        if oc_enabled() and oc_list_space(c, src) != oc_list_space(c, dst):
            from ..admin.orgcrypt_cli import oc_settle_kick
            oc_settle_kick([dst])


def move_subtree(c, tid, lid):
    """Subtasks follow their parent into list lid (all levels). A subtask in another list that the current
    user may not move out of (subtask of a foreign parent) stays in its list and becomes top level there."""
    people, ok = list_people(c, lid), {}
    done, level, n = {tid}, [tid], 0
    moved = [tid]
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
            moved.append(k["id"])
        level, n = nxt, n + 1
    # 2.126.0 D (#1992 A5): who comes along stays only when they share the target list
    c.execute("DELETE FROM task_people WHERE task_id = ANY(CAST(? AS BIGINT[])) AND NOT (user_id = ANY(CAST(? AS BIGINT[])))",
              (st_ids(moved), st_ids(people)))


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
    return load_tasks(c, "id=?", (tid,), full_snips=True)[0]  # 2.35.0 (#1095): one task with its code snippets


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
    # 2.83.0 (#1725): + a member of the organisation who may edit the list without joining (org_edit; ov_role: people only,
    # current members of the list's organisation) -- a read-only reader could not tick the task off
    if aid not in list_people(c, lid) and ov_role(c, lid, aid) != "edit":
        return tr("Only the owner or a member of the list can be assigned")
    # 2.26.0 (#928): an agent only by someone it is open to in this list (owner / list admins, or everyone with "Members
    # may see and use the agent")
    from ..agents.core import agent_ids, agent_usable
    if aid in agent_ids(c) and aid != me() and not agent_usable(c, aid, me(), lid):
        return tr("The list owner has not opened this agent to members")
    return None


# 2.2.1 (#359): the fields the web API's task / list / comment endpoints know (others: warning, see web_fields)
WEB_TASK_NEW = frozenset(TASK_FIELDS) | {"tags", "ltags", "fields", "people"}
WEB_TASK_EDIT = WEB_TASK_NEW | {"add_tags", "_prev", "_act", "le2e_move"}  # 2.64.1 (#1817): le2e_move
WEB_TASK_EDIT |= {"shift_chain"}  # 2.67.0 B (#1865): shift_chain
WEB_TASK_NEW |= {"client_ref"}  # 2.126.0 D (#1990): the device's id of a new task (a repeated POST = the same task)
WEB_LIST_NEW = frozenset({"name", "color", "folder", "view", "kind", "checklist", "done_at_bottom", "dep_shift", "tickets", "ptype", "family", "sections", "org_id", "time_tracking"})  # 2.28.0 (#935): org_id; 2.41.0 (#1471): time_tracking
WEB_LIST_EDIT = frozenset(LIST_FIELDS) | {"col_sums", "kpis", "client_id", "rate", "agent_tidy", "tidy_agent_id", "listen_agent_ids", "agent_members", "agent_peers", "_prev", "ticket_tpl", "day_hours", "done_at_bottom", "columns", "ptype", "sort_mode", "org_id", "stale_days", "agent_followup", "done_in_section", "folder_adopt", "org_visibility", "org_edit"}  # 2.36.2 (#1136): done_in_section; 2.46.0 (#1603)
WEB_LIST_EDIT |= {"group_field"}  # 2.144.0 C (#2414)
WEB_LIST_EDIT |= {"tap_done"}  # 2.46.4 (#1751): "Tap does not open details" (owner / list admins)
WEB_COMMENT = frozenset({"body", "suggestion", "reply_to", "choices", "multi", "approval", "expires_in", "mentions"})  # 2.64.1 (#1817): mentions  # 2.33.0 (#1076): reply_to; 2.41.0 (#1383): choices
WEB_COMMENT |= {"portal"}  # 2.63.0 B (#1513): an answer the customer sees


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
    ref = str(b.get("client_ref") or "")[:64] or None  # 2.126.0 D (#1990): sent again (the answer got lost) = the same task
    if ref and me():
        write_lock(c, f"task-ref-{me()}")
        r = c.execute("SELECT id FROM tasks WHERE created_by=? AND client_ref=?", (me(), ref)).fetchone()
        if r:
            need_task(c, r[0])
            return jsonify(one_task(c, r[0]))
    role = need_task(c, f["parent_id"]) if f.get("parent_id") else None  # 2.86.0 (N14): 404 / 403 before the parent checks
    e = check_parent(c, None, f.get("parent_id"))
    if e:
        return err(e)
    if f.get("parent_id"):  # subtasks live in their parent's list
        f["list_id"] = c.execute("SELECT list_id FROM tasks WHERE id=?", (f["parent_id"],)).fetchone()[0]
    elif f.get("list_id"):
        role = list_role(c, f["list_id"])
        if role != "participant":
            need_list(c, f["list_id"])
        else:
            from ..core.access import _org_list_writes
            if not _org_list_writes(c, f["list_id"], me()):
                raise Denied(403)  # 2.143.0 A (#2151): read-only in the list's organisation
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
    from ..collab.liste2e import le2a_task_create, le2e_mode
    le2a_task_create(c, f["list_id"], f)  # 2.64.1 (#1817): texts of a list with the lock only as ciphertexts from the app
    le2_on = bool(le2e_mode(c, f["list_id"]))
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
    if f.get("sprint_id"):  # 2.60.0 (#343): created right into a sprint of its list (edit rights)
        from ..lists.sprints import spr_apply
        e = spr_apply(c, f, {"sprint_id": None, "list_id": f["list_id"]}, f["list_id"])
        if e:
            return err(e)
    e = check_assignee(c, f["list_id"], f.get("assignee_id")) or check_group_assignee(c, f["list_id"], f.get("assignee_group_id")) \
        or check_url(f) or repeat_problem(f.get("repeat"), f.get("due"))
    if e:
        return err(e)
    if "sort" not in f:
        f["sort"] = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NOT DISTINCT FROM ?",
                              (f["list_id"], f.get("parent_id"))).fetchone()[0]
        if f.get("parent_id"):  # subtasks append at the end
            f["sort"] = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM tasks WHERE parent_id=?",
                                  (f["parent_id"],)).fetchone()[0]
        elif c.execute("SELECT 1 FROM lists WHERE id=? AND checklist=1", (f["list_id"],)).fetchone():
            # 2.13.0 (#453 P19): a list with "done at the bottom" (shopping, packing) adds new items at the end, in the
            # order they are typed
            f["sort"] = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM tasks WHERE list_id=? AND parent_id IS NULL",
                                  (f["list_id"],)).fetchone()[0]
    if f.get("ttype") and not (f.get("content") or "").strip() and not le2_on:  # 2.4.0 (#340): a new bug / feature gets its note template
        tpl = ticket_template(c, f["list_id"], f["ttype"])
        if tpl:
            f["content"] = tpl
    from ..agents.core import is_agent
    if "locked" not in f and has_request_context() and is_agent(getattr(g, "user", None)):
        f["locked"] = 1  # 2.36.0 (#1118, decision 09.10.2026): a task an agent creates starts locked in the app
    ts = iso(now_utc())
    f["created_by"] = me()
    if ref and me():
        f["client_ref"] = ref
    if f.get("assignee_id") or f.get("assignee_group_id"):
        f["assigned_by"] = me()
    cols = list(f) + ["created_at", "updated_at"]
    cur_id = insert_id(c, f"INSERT INTO tasks({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                    [f[k] for k in f] + [ts, ts])
    if b.get("tags"):
        set_tags(c, cur_id, b["tags"])
    if b.get("ltags"):
        set_ltags(c, cur_id, b["ltags"], log=False)  # BadInput: 400, nothing stored
    if b.get("fields"):
        set_field_values(c, cur_id, f["list_id"], b["fields"], log=False)  # BadInput: 400, nothing stored
    if b.get("people"):  # 2.19.0 (#653): who comes along
        e = people_set(c, cur_id, f["list_id"], b["people"])
        if e:
            c.rollback()
            return err(e)
    log_act(c, cur_id, "created")
    agent_task_mentions(c, cur_id)
    agent_tidy_events(c, cur_id)
    agent_added_events(c, cur_id)  # 2.23.0 (#795)
    if f.get("assignee_id"):
        task_event(c, cur_id, "assign")
    if f.get("assignee_group_id"):
        grp_assign_events(c, cur_id, f["assignee_group_id"])
    newtask_events(c, cur_id)
    if f.get("parent_id"):
        log_act(c, f["parent_id"], "subtask", {"id": cur_id, "title": f["title"][:200]})
    from ..lists.rules import rul_fire, rul_snap_new
    rul_fire(c, cur_id, rul_snap_new(c))  # 2.71.0 A (#1457): created right in a column / with a list tag
    bump(c)
    c.commit()
    return jsonify(one_task(c, cur_id))


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
    from ..collab.liste2e import le2a_locked_text
    le2a_locked_text(c, c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()[0], note)  # 2.64.1 (#1817): not encrypted
    until = b.get("until") or None
    if until is not None and not valid_date(until):
        raise BadInput(tr("Invalid value: {0}", "until"))
    cur = c.execute("SELECT waiting_at, wait_until, wait_fired FROM tasks WHERE id=?", (tid,)).fetchone()
    fired = cur["wait_fired"] if cur["waiting_at"] and cur["wait_until"] == until else ""
    c.execute("UPDATE tasks SET waiting_at=?, wait_note=?, wait_until=?, wait_by=?, wait_fired=?, updated_at=? WHERE id=?",
              (cur["waiting_at"] or iso(now_utc()), note, until, me() or None, fired, iso(now_utc()), tid))
    log_act(c, tid, "waiting", {"note": note[:200], "until": until})
    if note and me():  # 2.41.0 (#1205): a text used again is a suggestion again
        c.execute("DELETE FROM wait_hidden WHERE user_id=? AND note_key=?", (me(), note.lower()))


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


# ---- 2.41.0 (#1205): "Waiting on" suggestions: the texts the signed-in person used before (newest first), from their own
# history only (activity "waiting" written by them, incl. completed tasks, and the tasks they marked as waiting now) --
# never another person's text from a shared list. "x" on a suggestion hides it for the person (table wait_hidden); the
# tasks keep their text. The web app shows at most 8 and filters while typing.
MT_WAIT_MAX = 50


def mt_wait_suggestions(c, uid):
    rows = c.execute("""SELECT note, MAX(at) AS at FROM (
                          SELECT data->>'note' AS note, created_at AS at FROM activity
                           WHERE user_id=? AND kind='waiting' AND COALESCE(data->>'note', '')<>''
                          UNION ALL SELECT wait_note, waiting_at FROM tasks WHERE wait_by=? AND wait_note<>'' AND waiting_at IS NOT NULL
                        ) x GROUP BY note ORDER BY MAX(at) DESC LIMIT 400""", (uid, uid)).fetchall()
    hidden = {r[0] for r in c.execute("SELECT note_key FROM wait_hidden WHERE user_id=?", (uid,))}
    out, seen = [], set()
    full = [r["note"].strip() for r in rows]
    for r in rows:
        n = r["note"].strip()
        k = n.lower()
        if not n or k in seen or k in hidden:
            continue
        if len(n) == 200 and any(len(f) > 200 and f.startswith(n) for f in full):
            continue  # the history keeps 200 characters: the full text of the same entry is in the list already
        seen.add(k)
        out.append({"note": n, "at": r["at"]})
        if len(out) >= MT_WAIT_MAX:
            break
    return out


@app.get("/api/me/wait-suggestions")
def mt_wait_suggestions_get():
    """{items: [{note, at}]}: the signed-in person's earlier "Waiting on" texts, newest first (at most 50)."""
    c = db()
    return jsonify(items=mt_wait_suggestions(c, me()))


@app.delete("/api/me/wait-suggestions")
def mt_wait_suggestions_hide():
    """{note}: takes the text out of the person's suggestions (the tasks keep it). Using it again brings it back."""
    note = (body() or {}).get("note")
    if not isinstance(note, str) or not note.strip():
        return err(tr("Invalid value: {0}", "note"))
    c = db()
    uid = me()
    c.execute("INSERT INTO wait_hidden(user_id, note_key, created_at) VALUES(?,?,?) ON CONFLICT DO NOTHING",
              (uid, note.strip()[:WAIT_NOTE_MAX].lower(), iso(now_utc())))
    c.commit()
    return jsonify(ok=True, items=mt_wait_suggestions(c, uid))


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
        if notif_ok(c, rcpt, s, "followup", "push", t["list_id"]):  # 2.33.0 (#927): + the list (owner's template)
            lname = tr("Basket", lg=lg) if t["list_inbox"] and inbox_default(t["list_name"]) else t["list_name"]
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
    from ..tasks.lifecycle import apply_update, need_live
    from ..personal.timetrack import field_alias, web_fields
    c = db()
    need_task(c, tid)
    need_live(c, tid)  # 2.126.0 D (#1992 A3)
    conflicts = []
    old = c.execute("SELECT due, status, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
    b = web_fields(field_alias(body(), "content", "notes"), WEB_TASK_EDIT, "PATCH /api/tasks/{tid}")
    chain_on = b.pop("shift_chain", True) is not False if isinstance(b, dict) else True  # 2.67.0 B (#1865): undo / agents opt out
    from ..collab.notelock import ln_guard
    if ln_guard(c, tid, b):  # 2.48.0 (#1642): app, API and agents: a locked note is not overwritten (409, a clear message)
        return err(ln_guard(c, tid, b), 409)
    e = apply_update(c, tid, b, conflicts, lock=True)
    if e:
        return err(e)
    new_due = c.execute("SELECT due FROM tasks WHERE id=?", (tid,)).fetchone()[0]
    skipped = []
    shifted = dep_shift(c, tid, old["due"], new_due, skipped=skipped) if chain_on and old["status"] == 0 and not old["deleted_at"] else []
    bump(c)
    c.commit()
    from ..tasks.depchain import dch_chain, dch_days
    return jsonify({**one_task(c, tid), "conflicts": conflicts, "shifted": shifted,
                    "chain": dch_chain(shifted, skipped, dch_days(old["due"], new_due))})


# "Move dependent tasks along" (list setting dep_shift, package D2). 2.67.0 B (#1865): the whole chain moves by the same
# number of days (gaps stay), not only the tasks that would start too early; see tasks/depchain.py
def dep_shift(c, root, old_due, new_due, seen=None, moved=None, skipped=None):
    """Returns [{id, title, start, due, prev_start, prev_due}] of the tasks moved along. seen / moved / skipped: shared by
    the calls of one request (D3: a whole list moved -- its own tasks are never moved twice, the cap counts once)."""
    from ..tasks.depchain import dch_shift
    return dch_shift(c, me(), root, old_due, new_due, seen, moved, skipped)
