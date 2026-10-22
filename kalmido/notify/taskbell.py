"""2.53.0 C (#1424): the bell of ONE task, per person -- "As the list" (default), "Muted" or "Urgent".

Table task_bell (one row per task + person; level 'list' = as the list, kept so the last change can be undone):
  mute    no pushes about this task for that person (News stay); their own reminders are not touched
  urgent  every change (activity line) and every comment of the task by someone else is a push at the highest
          priority (ntfy 5 / Web Push urgency high), whatever the list bell, the matrix, the owner's template or the
          burst rule say. until = the last day (local date, inclusive); NULL = until the task is completed.
Evaluated when a push is decided (tbl_level), before the list bell: no cron, an expired / finished urgency simply
falls back to the list. Someone with the list's manage role (owner / admin) can set "Urgent" for members of the list
(only people of that list who see the task, never agents, never across the organisation). Everybody can switch their
own bell back; a person can refuse urgency set by others (user setting tbl_accept = 0: it then counts as "As the list",
the marking stays visible). Setting for others and switching off someone else's urgency are lines in the task history
(activity kind "bell", counts only: members do not learn who else is urgent). A row whose org_id differs from the
task's list (the task moved to another workspace) is ignored.
Undo: every change stamps the rows it touched with a token (act, act_by) and their previous state (prev); POST
/api/tasks/<id>/bell/undo puts back exactly those rows (only by the person who made the change)."""
import json
import secrets

from flask import g, has_request_context, jsonify

from ..core.config import app, PUBLIC_URL
from ..core.i18n import N_, tr
from ..core.db import body, db, err, iso, local_now, now_utc, usettings
from ..accounts.session import me
from ..core.access import Denied, MANAGE_ROLES, list_people, need_collab, need_task, task_visible
from ..core.errors import BadInput

TBL_LEVELS = ("list", "mute", "urgent")
TBL_PRIO = "5"  # ntfy 5 = urgent (Web Push: urgency high)
TBL_MAX_USERS = 500
TBL_SKIP = ("created", "bell")  # history lines that never push (a new task has no bells; bell changes push on their own)
TBL_DONE_KINDS = ("complete", "wont")  # the completion itself still reaches someone urgent "until completed"
# the push text of a change (activity kind -> what happened); anything else: "changed the task"
TBL_KIND_TXT = {
    "title": N_("{0} renamed the task"), "content": N_("{0} edited the description"),
    "due": N_("{0} changed the date"), "snooze": N_("{0} changed the date"), "dep_shift": N_("{0} changed the date"),
    "priority": N_("{0} changed the priority"), "assign": N_("{0} changed the assignee"),
    "list": N_("{0} moved the task to another project"), "section": N_("{0} moved the task to another section"),
    "complete": N_("{0} completed the task"), "reopen": N_("{0} reopened the task"), "wont": N_("{0} closed the task as won’t do"),
    "delete": N_("{0} deleted the task"), "restore": N_("{0} restored the task"),
    "attach": N_("{0} added a file"), "attach_rm": N_("{0} removed a file"), "subtask": N_("{0} added a subtask"),
}


def tbl_today():
    return local_now().date().isoformat()


def _org_of_task(c, tid):
    r = c.execute("SELECT t.list_id, l.org_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,)).fetchone()
    return (r[0], r[1]) if r else (None, None)


def tbl_rows(c, tid, uids=None):
    """{user id: row} of the bells of task tid that belong to its current workspace (level 'list' included)."""
    _, org = _org_of_task(c, tid)
    q = "SELECT * FROM task_bell WHERE task_id=? AND COALESCE(org_id,0)=?"
    args = [tid, org or 0]
    if uids is not None:
        uids = sorted({int(u) for u in uids})
        if not uids:
            return {}
        q += f" AND user_id IN ({','.join('?' * len(uids))})"
        args += uids
    return {r["user_id"]: r for r in c.execute(q, args)}


def tbl_effective(r, s, status, done_ok=False):
    """The level that counts for pushes of one row (None = as the list): an urgency ends with its day / the task's
    completion; urgency set by someone else counts only while the person accepts it (setting tbl_accept)."""
    if not r or r["level"] not in ("mute", "urgent"):
        return None
    if r["level"] == "mute":
        return "mute"
    if r["until"] and r["until"] < tbl_today():
        return None
    if not r["until"] and status and not done_ok:
        return None
    if r["set_by"] and r["set_by"] != r["user_id"] and (s or {}).get("tbl_accept", "1") == "0":
        return None
    return "urgent"


def tbl_level(c, uid, tid, s=None, done_ok=False):
    """'mute' | 'urgent' | None for pushes about task tid to uid (s = uid's settings)."""
    if not uid or not tid or not tbl_any(c):
        return None
    r = tbl_rows(c, tid, [uid]).get(uid)
    if not r or r["level"] == "list":
        return None
    t = c.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()
    return tbl_effective(r, s, t[0] if t else 0, done_ok)


def tbl_any(c):
    """False when no task bell is muted / urgent at all (one look per request; outside requests: True)."""
    if not has_request_context():
        return True
    if g.get("tbl_any") is None:
        g.tbl_any = bool(c.execute("SELECT 1 FROM task_bell WHERE level IN ('mute','urgent') LIMIT 1").fetchone())
    return g.tbl_any


def tbl_urgent_users(c, tid):
    """Who has "Urgent" on task tid (people only, raw rows; tbl_level decides per person)."""
    if not tbl_any(c):
        return set()
    ids = sorted(u for u, r in tbl_rows(c, tid).items() if r["level"] == "urgent")
    if not ids:
        return set()
    return {r[0] for r in c.execute(f"SELECT id FROM users WHERE kind!='agent' AND disabled=0 AND id IN ({','.join('?' * len(ids))})", ids)}


def tbl_sent(uid, tid):
    """True when uid already got an urgent push about tid in this request (one per task and request); marks it."""
    if not has_request_context():
        return False
    seen = g.setdefault("tbl_sent", set())
    if (uid, tid) in seen:
        return True
    seen.add((uid, tid))
    return False


def tbl_note(c, tid, kind, actor):
    """Called by every history line (tasks/validation.py log_act): an urgent push to everybody with "Urgent" on the
    task, except the person who made the change. Requests only (the watchdog's own changes push as before)."""
    if not has_request_context() or kind in TBL_SKIP or not tid:
        return
    uids = tbl_urgent_users(c, tid)
    uids.discard(actor)
    uids.discard(None)
    if not uids:
        return
    from ..collab.comments import collab_user, lang_of, user_names
    from ..notify.push import push_reachable
    t = c.execute("SELECT id, title, list_id FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t:
        return
    name = user_names(c, [actor]).get(actor, "?") if actor else None
    for uid in sorted(uids):
        s = collab_user(c, uid, t["list_id"])
        if not s or not task_visible(c, tid, uid, full=True) or \
                tbl_level(c, uid, tid, s, done_ok=kind in TBL_DONE_KINDS) != "urgent" or not push_reachable(c, uid, s):
            continue
        if tbl_sent(uid, tid):
            continue
        lg = lang_of(s)
        who = name or tr("Someone via the public link", lg=lg)
        msg = tr(TBL_KIND_TXT.get(kind, N_("{0} changed the task")), who, lg=lg)
        g.pushes.append((uid, tr("Urgent: {0}", t["title"], lg=lg), msg, f"{PUBLIC_URL}/#t/{tid}", TBL_PRIO, {"task": tid}))


# ---- routes (web app only; agents never set or read bells: an agent's v1 token cannot reach these routes)

def _no_agent():
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403)


def _names(c, ids):
    from ..collab.comments import user_names
    return user_names(c, list(ids))


def _row_out(r, names, status, s=None):
    if not r or r["level"] == "list":
        return {"level": "list", "until": None, "set_by": None, "by_name": None, "active": False}
    return {"level": r["level"], "until": r["until"], "set_by": r["set_by"], "by_name": names.get(r["set_by"]) if r["set_by"] else None,
            "active": tbl_effective(r, s, status) == r["level"]}


def _people(c, tid, lid):
    """The people of the task's list who may get a bell from an admin: owner + members (not readers through "everyone in
    the organisation"), humans only, who see this task with its comments."""
    ids = list_people(c, lid)
    if not ids:
        return []
    ag = {r[0] for r in c.execute(f"SELECT id FROM users WHERE kind='agent' AND id IN ({','.join('?' * len(ids))})", sorted(ids))}
    return sorted(u for u in ids if u not in ag and task_visible(c, tid, u, full=True))


def tbl_info(c, tid, role):
    lid, _ = _org_of_task(c, tid)
    st = c.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0]
    uid = me()
    rows = tbl_rows(c, tid)
    names = _names(c, {r["set_by"] for r in rows.values() if r["set_by"]} | {uid})
    out = {"task_id": tid, "mine": _row_out(rows.get(uid), names, st, usettings(c, uid)), "accept": usettings(c, uid).get("tbl_accept", "1") != "0",
           "can_others": role in MANAGE_ROLES}
    if role in MANAGE_ROLES:  # only the list's owner / admins see for whom it is set
        ppl = _people(c, tid, lid)
        pn = _names(c, ppl)
        # 2.53.0 (#1424, review): someone's own "Muted" is private -- admins see it as "As the list"
        out["people"] = [{"id": u, "name": pn.get(u, "?"), **_row_out(rows.get(u) if (rows.get(u) or {"level": ""})["level"] != "mute" else None, names, st)}
                         for u in ppl if u != uid]
    return out


@app.get("/api/tasks/<int:tid>/bell")
def tbl_get(tid):
    """My bell of the task; the list's owner / admins also see the people of the list and their bells."""
    _no_agent()
    c = db()
    role = need_task(c, tid, write=False, full=True)
    return jsonify(tbl_info(c, tid, role))


def _until_in(b, level):
    u = b.get("until")
    if level != "urgent" or u in (None, ""):
        return None
    from ..tasks.validation import valid_date
    if not isinstance(u, str) or not valid_date(u):
        raise BadInput(tr("Invalid value: {0}", "until"))
    if u < tbl_today():
        raise BadInput(tr("The date is in the past"))
    return u


def _put_row(c, tid, uid, org, level, until, by, act, prev):
    g.tbl_any = None  # looked up again by later history lines of this request
    ts = iso(now_utc())
    pj = json.dumps({"level": prev["level"], "until": prev["until"], "set_by": prev["set_by"]} if prev else None)
    c.execute("""INSERT INTO task_bell(task_id,user_id,org_id,level,until,set_by,created_at,updated_at,prev,act,act_by)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id,user_id) DO UPDATE SET org_id=excluded.org_id, level=excluded.level,
                 until=excluded.until, set_by=excluded.set_by, updated_at=excluded.updated_at, prev=excluded.prev, act=excluded.act,
                 act_by=excluded.act_by""", (tid, uid, org, level, until, by, ts, ts, pj, act, me()))


@app.put("/api/tasks/<int:tid>/bell")
def tbl_put(tid):
    """{level: list | mute | urgent, until?: YYYY-MM-DD (urgent; none = until completed), users?: [ids] | "all"}.
    Without users: my own bell (anyone who sees the task). With users: the list's owner / admins only, level urgent
    (set) or list (take back an urgency someone set; a person's own choice stays)."""
    from ..tasks.validation import log_act
    _no_agent()
    need_collab()
    c, b = db(), body()
    role = need_task(c, tid, write=False, full=True)
    level = b.get("level")
    if level not in TBL_LEVELS:
        return err(tr("Invalid value: {0}", "level"))
    try:
        until = _until_in(b, level)
    except BadInput as e:
        return err(str(e))
    lid, org = _org_of_task(c, tid)
    uid = me()
    users = b.get("users")
    act = secrets.token_urlsafe(9)
    rows = tbl_rows(c, tid)
    if users is None:
        prev = rows.get(uid)
        _put_row(c, tid, uid, org, level, until, uid if level != "list" else None, act, prev)
        # switching off an urgency someone else set is a history line (counts only)
        if prev and prev["level"] == "urgent" and prev["set_by"] and prev["set_by"] != uid and level != "urgent":
            log_act(c, tid, "bell", {"level": level, "self": 1})
        c.commit()
        return jsonify({**tbl_info(c, tid, role), "act": act})
    if role not in MANAGE_ROLES:
        raise Denied(403)
    if level not in ("urgent", "list"):
        return err(tr("Invalid value: {0}", "level"))
    ppl = _people(c, tid, lid)
    if users == "all":
        targets = ppl
    else:
        if not isinstance(users, list) or not users or len(users) > TBL_MAX_USERS:
            return err(tr("Invalid value: {0}", "users"))
        try:
            targets = sorted({int(u) for u in users})
        except (TypeError, ValueError):
            return err(tr("Invalid value: {0}", "users"))
        if any(u not in ppl for u in targets):  # not in this list / an agent / does not see the task: one answer for all
            return err(tr("unknown user"), 404)
    changed = []
    for u in targets:
        prev = rows.get(u)
        if level == "list" and not (prev and prev["level"] == "urgent" and prev["set_by"] and prev["set_by"] != u):
            continue  # only someone else's urgency is taken back
        if level == "urgent" and prev and prev["level"] == "urgent" and prev["until"] == until:
            continue
        _put_row(c, tid, u, org, level, until, uid if level == "urgent" else None, act, prev)
        changed.append(u)
    if changed:
        log_act(c, tid, "bell", {"level": level, "until": until, "n": len(changed)})
        if level == "urgent":
            tbl_news(c, tid, lid, [u for u in changed if u != uid], until)
    c.commit()
    return jsonify({**tbl_info(c, tid, role), "act": act if changed else None, "changed": len(changed)})


def tbl_news(c, tid, lid, uids, until):
    """A News item for everybody marked urgent by someone else (event row "Assignments": it is about them), and a push
    when their settings want one -- at the highest priority while they accept urgency from others."""
    from ..collab.comments import collab_user, lang_of
    from ..collab.news import news_add, notif_ok
    from ..notify.push import push_prio, push_reachable
    t = c.execute("SELECT title FROM tasks WHERE id=?", (tid,)).fetchone()
    who = _names(c, [me()]).get(me(), "?")
    for u in uids:
        s = collab_user(c, u, lid)
        if not s:
            continue
        news_add(c, u, "tbl_urgent", task_id=tid, row="assign", s=s, data={"until": until} if until else None)
        if not notif_ok(c, u, s, "assign", "push", lid) or not push_reachable(c, u, s):
            continue
        lg = lang_of(s)
        g.pushes.append((u, tr("Urgent: {0}", t["title"], lg=lg), tr("{0} marked this task urgent for you", who, lg=lg),
                         f"{PUBLIC_URL}/#t/{tid}", TBL_PRIO if s.get("tbl_accept", "1") != "0" else push_prio(s), {"task": tid}))


@app.post("/api/tasks/<int:tid>/bell/undo")
def tbl_undo(tid):
    """{act}: puts back the rows my change act touched (one undo step); rows changed since then stay as they are."""
    from ..tasks.validation import log_act
    _no_agent()
    need_collab()
    c, b = db(), body()
    role = need_task(c, tid, write=False, full=True)
    act = b.get("act")
    if not isinstance(act, str) or not act:
        return err(tr("Invalid value: {0}", "act"))
    uid = me()
    rows = [r for r in tbl_rows(c, tid).values() if r["act"] == act and r["act_by"] == uid]
    if any(r["user_id"] != uid for r in rows) and role not in MANAGE_ROLES:
        raise Denied(403)
    others = 0
    for r in rows:
        try:
            p = json.loads(r["prev"] or "null")
        except ValueError:
            p = None
        p = p if isinstance(p, dict) and p.get("level") in TBL_LEVELS else {"level": "list", "until": None, "set_by": None}
        c.execute("UPDATE task_bell SET level=?, until=?, set_by=?, act=NULL, act_by=NULL, prev=NULL, updated_at=? WHERE task_id=? AND user_id=?",
                  (p["level"], p.get("until"), p.get("set_by"), iso(now_utc()), tid, r["user_id"]))
        others += r["user_id"] != uid or bool(r["prev"] and p.get("set_by") and p["set_by"] != r["user_id"])  # what was in the history
    if others:
        log_act(c, tid, "bell", {"undo": 1, "n": others})
    c.commit()
    return jsonify({**tbl_info(c, tid, role), "undone": len(rows)})
