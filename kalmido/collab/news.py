"""The News feed and the notification settings (matrix + list bells)."""
import json
import os
import re
import time
from datetime import datetime, timedelta
from flask import g, jsonify, request

from ..core.config import app, PUBLIC_URL
from ..core.schema import USER_DEFAULTS
from ..core.i18n import tr
from ..core.db import body, db, err, iso, iso_ms, now_utc, usettings
from ..accounts.session import me
from ..accounts.pictures import avatar_map
from ..core.access import list_role, plists, pvis
from ..collab.comments import collab_on, collab_user, lang_of, MENTION_RE, user_names


# ---------------------------------------------------------------- News feed ("Neuigkeiten")
# One row per event that concerns a user, written at the same points (and for the same recipients) as
# the collaboration pushes, plus list sharing (share / role / unshare; these have no push). Never my own
# actions; only users with module "collab" on get entries (collab off: nothing is written, the feed and
# its badge are hidden). The push burst rule does not apply: the feed keeps every item; consecutive
# plain comments on the same task are grouped into one row (with a count) when the feed is read.
# Visibility is re-checked at read time: items of tasks / lists I no longer see, tasks in the trash and
# deleted comments disappear. Retention: NEWS_KEEP_DAYS days and at most NEWS_KEEP_MAX items per user
# (watchdog, hourly).
NEWS_KEEP_DAYS = int(os.environ.get("TASKS_NEWS_DAYS", "90"))
NEWS_KEEP_MAX = int(os.environ.get("TASKS_NEWS_MAX", "500"))
NEWS_KINDS = ("mention", "comment", "assign", "unassign", "take", "complete", "share", "role", "unshare", "unblock", "status",
              "newtask", "approval", "followup",  # 2.1.0
              "usage",  # 2.1.1 (#326): an agent reached 80 % / 100 % of a usage limit (admins)
              "owner",  # 2.1.2 (#349): I am the new owner of a list
              "errreport",  # 2.18.0: a NEW error (new fingerprint) of the list's error-report webhook became a ticket
              "apdecide",  # 2.23.0 (#463): the approver decided on my approval request (row "assign")
              "signup")  # 2.23.0 (#711): a registration waits for approval (admins; row "usage", the admins' row)
NEWS_LIST_KINDS = ("share", "role", "unshare", "status", "owner", "evinvite", "evshare", "abshare")  # about a list (2.21: an event / calendar / address book), not a task
NEWS_EXCERPT = 300
# 1.9.0: per user (setting news_kinds) which groups of events create a News item; pushes are not affected
NEWS_GROUPS = {"mention": ("mention",), "assign": ("assign", "unassign", "take"), "comment": ("comment",), "complete": ("complete",),
               "unblock": ("unblock",), "share": ("share", "role", "unshare", "owner"), "status": ("status",)}
NEWS_TO_ME = ("mention", "assign", "unassign", "take")  # filter "Mentions & assigned to me"


def news_wanted(s, kind):
    on = set((s.get("news_kinds") if s else USER_DEFAULTS["news_kinds"]).split(","))
    return any(kind in NEWS_GROUPS[g] for g in on if g in NEWS_GROUPS)


# ---- 2.1.0 (#317): notification settings. One matrix per user (events x News / Push) + a bell per list, checked in ONE
# place (notif_ok) for both the News item and the push. Events:
#   comment   a comment on a task I created or am assigned to
#   reply     a reply to my comment: the comment right before the new one on that task is mine
#   follow    a comment on a task I follow (I commented on it before; created / assigned = "comment")
#   mention   @me in a comment          assign    assigned to me / taken away
#   newtask   someone else created a task in a shared list      complete  others completed my task
#   status    project status changed    share     a list shared with me (role changed, removed)
#   unblock   a task I wait on was completed    approval  an agent waits for my approval
#   followup  the follow-up day of a task "waiting on external" (#335)    reminder  due reminders (push only)
#   usage     2.1.1 (#326, admins only): an agent reached 80 % / 100 % of its soft limit or its hard limit
#   nag       2.7.0 (#413): a reminder repeating until the task is done (push only); unlike reminders it follows a list's bell
# A comment counts once, as the first matching event of: mention, comment, reply, follow.
# News of the events that existed before 2.1.0 stays in the setting news_kinds (their "News" column; reply and follow
# default to its "comment"), everything else in the setting "notify" (json {event: {news?: 0|1, push?: 0|1}}). Defaults
# = the behaviour up to 2.0.8: pushes for comments, mentions, assignments, completions, unblocked tasks, approvals and
# reminders; no pushes for status and sharing; newtask off; reply on (as comment); followup on.
# The bell of a list (table list_bell, per user): all = every event of that list (also every comment and new task) as
# News and push; default = the matrix; mute = nothing from that list except mentions of me and assignments to me (these
# follow the matrix). Reminders and follow-ups are my own and never muted by a bell.
NOTIF_ROWS = ("comment", "reply", "follow", "mention", "assign", "newtask", "complete", "status", "share", "unblock",
              "approval", "followup", "reminder", "usage",  # 2.1.1 (#326): usage = an agent's usage limit (admins only)
              "proposal",  # 2.3.0: an agent's proposal I asked for is ready
              "nag",  # 2.7.0 (#413): a reminder that repeats until the task is done (push only; a muted list bell stops it)
              "chat",  # 2.17.0 (#419): a direct message / a team chat message (push only; mentions follow "mention")
              "errreport")  # 2.18.0 (owner decision): exactly one News item + push when a NEW error first becomes a ticket
NOTIF_NEWS_GROUP = {"comment": "comment", "reply": "comment", "follow": "comment", "mention": "mention", "assign": "assign",
                    "complete": "complete", "status": "status", "share": "share", "unblock": "unblock"}
NOTIF_NEWS_PRIMARY = ("comment", "mention", "assign", "complete", "status", "share", "unblock")  # News = news_kinds
NOTIF_NEWS_NEW = {"newtask": 0, "approval": 0, "followup": 1, "usage": 1, "proposal": 1, "errreport": 1}
NOTIF_PUSH_DEFAULT = {"comment": 1, "reply": 1, "follow": 1, "mention": 1, "assign": 1, "newtask": 0, "complete": 1,
                      "status": 0, "share": 0, "unblock": 1, "approval": 1, "followup": 1, "reminder": 1, "usage": 1,
                      "proposal": 1, "nag": 1, "chat": 1, "errreport": 1}
NOTIF_NO_NEWS = ("reminder", "nag", "chat")
NOTIF_UNMUTED = ("mention", "assign")        # still come through a muted list
NOTIF_NO_BELL = ("reminder", "followup", "usage", "proposal")  # never changed by a list bell
BELL_MODES = ("all", "default", "mute", "custom")
# 2.6.1 (#404): the bell "custom" = my own choice per event for this list (News and push each): a ticked event comes from
# every task of the list (like "all" for that event), an unticked one never; reply / follow count as "comment". Events
# without a choice here (sharing, reminders, follow-ups, usage, proposals I asked for) follow the matrix as before.
BELL_CUSTOM_ROWS = ("newtask", "comment", "mention", "assign", "complete", "status", "unblock", "approval")
BELL_CUSTOM_KEY = {"reply": "comment", "follow": "comment"}
KIND_ROW = {"mention": "mention", "comment": "comment", "assign": "assign", "unassign": "assign", "complete": "complete",
            "share": "share", "role": "share", "unshare": "share", "unblock": "unblock", "status": "status",
            "newtask": "newtask", "approval": "approval", "followup": "followup", "usage": "usage", "owner": "share",
            "proposal": "proposal", "take": "assign", "errreport": "errreport", "apdecide": "assign", "signup": "usage"}


def notif_stored(s):
    try:
        o = json.loads((s or {}).get("notify") or "{}")
    except ValueError:
        return {}
    return o if isinstance(o, dict) else {}


def notif_matrix(s):
    """{event: {"news": bool|None, "push": bool}} of a user's settings (None = the event has no News)."""
    s = s or USER_DEFAULTS
    nk = set((s.get("news_kinds") if s.get("news_kinds") is not None else USER_DEFAULTS["news_kinds"]).split(","))
    o = notif_stored(s)
    out = {}
    for r in NOTIF_ROWS:
        x = o.get(r) if isinstance(o.get(r), dict) else {}
        if r in NOTIF_NO_NEWS:
            news = None
        elif r in NOTIF_NEWS_PRIMARY:
            news = NOTIF_NEWS_GROUP[r] in nk
        elif "news" in x:
            news = bool(x["news"])
        else:
            news = NOTIF_NEWS_GROUP[r] in nk if r in NOTIF_NEWS_GROUP else bool(NOTIF_NEWS_NEW[r])
        out[r] = {"news": news, "push": bool(x["push"]) if "push" in x else bool(NOTIF_PUSH_DEFAULT[r])}
    return out


def notif_update(s, v):
    """A change of the matrix (partial {event: {news?, push?}}) -> {setting: stored value} (notify + news_kinds)."""
    from ..personal.timetrack import BadInput
    bad = BadInput(tr("Invalid value: {0}", "notify"))
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            raise bad from None
    if not isinstance(v, dict) or len(v) > len(NOTIF_ROWS):
        raise bad
    o = {k: dict(x) for k, x in notif_stored(s).items() if k in NOTIF_ROWS and isinstance(x, dict)}
    nk = [x for x in (s.get("news_kinds") or "").split(",") if x]
    for r, x in v.items():
        if r not in NOTIF_ROWS or not isinstance(x, dict) or not x or any(k not in ("news", "push") for k in x) or \
                any(y not in (0, 1, True, False) for y in x.values()) or (r in NOTIF_NO_NEWS and "news" in x):
            raise bad
        cur = o.setdefault(r, {})
        if "push" in x:
            cur["push"] = int(bool(x["push"]))
        if "news" in x:
            if r in NOTIF_NEWS_PRIMARY:
                gname = NOTIF_NEWS_GROUP[r]
                nk = [k for k in nk if k != gname] + ([gname] if x["news"] else [])
            else:
                cur["news"] = int(bool(x["news"]))
        if not cur:
            o.pop(r)
    order = list(NEWS_GROUPS)
    return {"notify": json.dumps(o, separators=(",", ":"), sort_keys=True),
            "news_kinds": ",".join(k for k in order if k in nk)}


def list_bell(c, uid, lid):
    """(mode, custom choice dict) of my bell for list lid."""
    if not lid:
        return "default", {}
    r = c.execute("SELECT mode, custom FROM list_bell WHERE user_id=? AND list_id=?", (uid, lid)).fetchone()
    return (r["mode"], bell_custom_of(r["custom"])) if r else ("default", {})


def bell_custom_of(raw):
    try:
        o = json.loads(raw or "{}")
    except ValueError:
        return {}
    return {k: {ch: int(bool(v[ch])) for ch in ("news", "push") if ch in v} for k, v in o.items()
            if k in BELL_CUSTOM_ROWS and isinstance(v, dict)} if isinstance(o, dict) else {}


def bell_custom_clean(v):
    """A custom choice from a client -> the stored json; BadInput if invalid."""
    from ..personal.timetrack import BadInput
    bad = BadInput(tr("Invalid value: {0}", "custom"))
    if v is None:
        return "{}"
    if not isinstance(v, dict) or len(v) > len(BELL_CUSTOM_ROWS):
        raise bad
    out = {}
    for k, x in v.items():
        if k not in BELL_CUSTOM_ROWS or not isinstance(x, dict) or any(ch not in ("news", "push") for ch in x) or \
                any(y not in (0, 1, True, False) for y in x.values()):
            raise bad
        if x:
            out[k] = {ch: int(bool(y)) for ch, y in sorted(x.items())}
    return json.dumps(out, separators=(",", ":"), sort_keys=True)


def notif_ok(c, uid, s, row, ch, lid=None):
    """THE check for News (ch 'news') and pushes (ch 'push') of event row to uid about list lid."""
    m = notif_matrix(s)[row]
    if ch == "news" and m["news"] is None:
        return False
    bell, cust = list_bell(c, uid, lid) if lid and row not in NOTIF_NO_BELL else ("default", {})
    if bell == "mute" and row not in NOTIF_UNMUTED:
        return False
    if bell == "all":
        return True
    key = BELL_CUSTOM_KEY.get(row, row)
    if bell == "custom" and key in BELL_CUSTOM_ROWS:
        x = cust.get(key, {})
        return bool(x[ch]) if ch in x else bool(m[ch])  # not chosen yet: as in the matrix
    return bool(m[ch])


def bell_all_users(c, lid, row=None):
    """Who wants every event of this list: the bell "all", and (2.6.1, #404) "custom" with event row ticked (News or push)."""
    out = set()
    key = BELL_CUSTOM_KEY.get(row, row)
    for r in c.execute("SELECT user_id, mode, custom FROM list_bell WHERE list_id=? AND mode IN ('all','custom')", (lid,)):
        if r["mode"] == "all" or (key and any(bell_custom_of(r["custom"]).get(key, {}).values())):
            out.add(r["user_id"])
    return out


def list_push(c, uid, row, lid, title_fn, msg_fn, click=None):
    """2.1.0 (#317): a push about list lid for the events that had none before (status, share) or are new (newtask),
    when uid's settings want it. title_fn / msg_fn(lg) build the texts in uid's language."""
    from ..notify.push import push_prio, push_reachable
    from ..agents.core import agent_ids
    if not uid or uid == me() or uid in agent_ids(c):
        return
    s = collab_user(c, uid, lid)
    if not s or not notif_ok(c, uid, s, row, "push", lid) or not push_reachable(c, uid, s):
        return
    lg = lang_of(s)
    g.pushes.append((uid, title_fn(lg), msg_fn(lg), click or f"{PUBLIC_URL}/#l/{lid}", push_prio(s)))


def news_add(c, uid, kind, task_id=None, list_id=None, comment_id=None, data=None, actor=None, row=None, s=None):
    """Feed entry for uid (caller commits). Skipped for my own actions and for users without collab.
    actor 0 = someone via a public link (stored without an actor, data.via = public_link). 2.1.0: row = the event of the
    notification settings (default: by kind), checked with notif_ok; a follow-up (kind followup) is my own reminder."""
    own = kind == "followup"
    actor = (me() if actor is None else actor) if not own else None
    if not uid or (uid == actor and not own) or c.execute("SELECT 1 FROM users WHERE id=? AND kind='agent'", (uid,)).fetchone():
        return
    s = s or collab_user(c, uid, None)
    if not s:
        return
    lid = list_id
    if lid is None and task_id:
        lr = c.execute("SELECT list_id FROM tasks WHERE id=?", (task_id,)).fetchone()
        lid = lr[0] if lr else None
    if not notif_ok(c, uid, s, row or KIND_ROW.get(kind, kind), "news", lid):
        return
    if not actor and not own:
        data = {**(data or {}), "via": "public_link"}
    c.execute("INSERT INTO notifications(user_id,kind,task_id,list_id,actor_id,comment_id,data,created_at) "
              "VALUES(?,?,?,?,?,?,?,?)", (uid, kind, task_id, list_id, actor or None, comment_id,
                                          json.dumps(data or {}, ensure_ascii=False), iso_ms(now_utc())))


def news_sig(c, uid):
    """Cheap change marker of my unread items (in /api/version): clients reload the state when it moves."""
    r = c.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM notifications WHERE user_id=? AND read_at IS NULL",
                  (uid,)).fetchone()
    return f"{r[0]}.{r[1]}"


def news_items(c, uid, s=None, mentions_only=False, to_me=False):
    """My visible feed, newest first, consecutive comments on one task grouped. [] if collab is off."""
    from ..agents.usage import is_admin_id
    if not collab_on(s or usettings(c, uid)):
        return [], {}
    rows = c.execute("""SELECT n.*, t.title AS t_title, t.list_id AS t_list, t.deleted_at AS t_del,
                               k.body AS c_body, k.deleted_at AS c_del
                        FROM notifications n LEFT JOIN tasks t ON t.id=n.task_id LEFT JOIN comments k ON k.id=n.comment_id
                        WHERE n.user_id=? ORDER BY n.id DESC LIMIT ?""", (uid, NEWS_KEEP_MAX)).fetchall()
    roles, pl, pv = {}, set(plists(c, uid)), {}

    def sees(lid):
        if lid not in roles:
            roles[lid] = bool(lid) and bool(list_role(c, lid, uid))
        return roles[lid]

    def sees_task(tid, full):  # 1.10.0: a participant only sees the News of their own tasks (list-level check: sees())
        if not pl:
            return True
        if not pv:
            v, w, _ = pvis(c, uid)
            pv.update(vis=v, wr=w, lists={r[0]: r[1] for r in c.execute(
                f"SELECT id, list_id FROM tasks WHERE list_id IN ({','.join(str(x) for x in pl)})")})
        return pv["lists"].get(tid) not in pl or tid in pv["wr" if full else "vis"]
    out, uids = [], set()
    agents = {x[0] for x in c.execute("SELECT id FROM users WHERE kind='agent'")}
    for r in rows:
        kind = r["kind"]
        if (mentions_only and kind != "mention") or (to_me and kind not in NEWS_TO_ME):
            continue
        if kind in ("share", "role", "status", "owner"):
            if not sees(r["list_id"]):
                continue
        elif kind == "usage":  # 2.1.1 (#326): an agent's usage limit, for admins (no task, no list)
            if not is_admin_id(c, uid):
                continue
        elif kind == "signup":  # 2.23.0 (#711): for admins, while the registration still waits
            try:
                su = int(json.loads(r["data"] or "{}").get("user_id") or 0)
            except (ValueError, TypeError, AttributeError):
                su = 0
            if not is_admin_id(c, uid) or not c.execute("SELECT 1 FROM users WHERE id=? AND signup='pending'", (su,)).fetchone():
                continue
        elif kind == "proposal":  # 2.3.0: while the proposal job (mine) exists
            try:
                pj = int(json.loads(r["data"] or "{}").get("job") or 0)
            except (ValueError, TypeError, AttributeError):
                pj = 0
            if not c.execute("SELECT 1 FROM agent_jobs WHERE id=? AND user_id=? AND kind IS NOT NULL", (pj, uid)).fetchone():
                continue
        elif kind in ("evinvite", "evshare", "abshare"):  # 2.21.0 (#659 / #658): while I am still invited / a member
            try:
                dd = json.loads(r["data"] or "{}")
            except ValueError:
                dd = {}
            q = {"evinvite": "SELECT 1 FROM event_attendees a JOIN events e ON e.id=a.event_id WHERE a.event_id=? AND a.user_id=? AND e.deleted_at IS NULL",
                 "evshare": "SELECT 1 FROM ev_cal_members WHERE cal_id=? AND user_id=?",
                 "abshare": "SELECT 1 FROM book_members WHERE book_id=? AND user_id=?"}[kind]
            key = {"evinvite": "event_id", "evshare": "cal_id", "abshare": "book_id"}[kind]
            if not c.execute(q, (dd.get(key), uid)).fetchone():
                continue
        elif kind != "unshare":
            if r["t_title"] is None or r["t_del"] or not sees(r["t_list"]) or not sees_task(r["task_id"], True):
                continue
            if kind in ("mention", "comment") and (r["c_body"] is None or r["c_del"]):
                continue
        read = r["read_at"] is not None
        prev = out[-1] if out else None
        if kind == "comment" and prev and prev["kind"] == "comment" and prev["task_id"] == r["task_id"]:
            prev["ids"].append(r["id"])
            prev["count"] += 1
            prev["read"] = prev["read"] and read
            if r["actor_id"] not in prev["actors"]:
                prev["actors"].append(r["actor_id"])
            uids.add(r["actor_id"])
            continue
        # 2.13.0 (#453 A5): an agent's plain comments (no mention of me) one after the other, on any tasks, are ONE item
        # ("Claude left 12 comments on 5 tasks", one unread) instead of one per task: an agent working through a list
        # used to fill the bell with hundreds of unread items. Mentions, assignments and approvals stay single items.
        if kind == "comment" and r["actor_id"] in agents and prev and prev["kind"] == "comment" and prev["actors"] == [r["actor_id"]] \
                and prev.get("agent") and _news_age_h(prev["created_at"], r["created_at"]) <= 12:
            prev["ids"].append(r["id"])
            prev["count"] += 1
            prev["read"] = prev["read"] and read
            if not any(x["id"] == r["task_id"] for x in prev["tasks"]):
                prev["tasks"].append({"id": r["task_id"], "title": r["t_title"]})
            continue
        body = ""
        if kind in ("mention", "comment"):
            body = r["c_body"] or ""
            if len(body) > NEWS_EXCERPT:
                body = re.sub(r"<@?\d*$", "", body[:NEWS_EXCERPT]).rstrip() + "…"
            uids.update(int(x) for x in MENTION_RE.findall(body))
        data = json.loads(r["data"] or "{}")
        if kind == "status":
            body = data.get("note") or ""
        if kind == "unblock":  # the blocker's title only if I (still) see it
            bl = c.execute("SELECT title, list_id FROM tasks WHERE id=?", (data.get("blocker"),)).fetchone()
            data = {"title": bl["title"], "hidden": False} if bl and sees(bl["list_id"]) and sees_task(data.get("blocker"), False) \
                else {"title": None, "hidden": True}
        uids.add(r["actor_id"])
        lk = kind in NEWS_LIST_KINDS
        out.append({"id": r["id"], "ids": [r["id"]], "kind": kind, "count": 1, "actor_id": r["actor_id"],
                    "actors": [r["actor_id"]], "task_id": r["task_id"] if not lk else None,
                    "task_title": r["t_title"] if not lk else None,
                    "list_id": r["t_list"] if r["task_id"] and not lk else r["list_id"],
                    "comment_id": r["comment_id"], "excerpt": body, "data": data, "created_at": r["created_at"],
                    "read": read})
        if kind == "comment" and r["actor_id"] in agents:
            out[-1].update(agent=True, tasks=[{"id": r["task_id"], "title": r["t_title"]}])
    return out, user_names(c, uids)


def _news_age_h(newer, older):
    try:
        return (datetime.fromisoformat(newer.replace("Z", "+00:00")) - datetime.fromisoformat(older.replace("Z", "+00:00"))).total_seconds() / 3600
    except (ValueError, AttributeError):
        return 0


def news_unread(c, uid, s=None):
    return sum(1 for x in news_items(c, uid, s)[0] if not x["read"])


@app.get("/api/news")
def news_list():
    """My feed (only my own rows). ?filter=mentions: mentions only; ?filter=me (1.9.0): mentions + (un)assignments."""
    c = db()
    uid = me()
    s = usettings(c, uid)
    f = request.args.get("filter")
    items, names = news_items(c, uid, s, mentions_only=f == "mentions", to_me=f == "me")
    return jsonify(items=items, users={str(k): v for k, v in names.items()}, unread=news_unread(c, uid, s),
                   sig=news_sig(c, uid), enabled=collab_on(s), avatars=avatar_map(c, uid))


@app.post("/api/news/dismiss")
def news_dismiss():
    """{ids: [...]}: removes these items of mine from the feed (1.9.0, swipe / x). Other users' ids are ignored."""
    b = body()
    c = db()
    uid = me()
    try:
        ids = [int(x) for x in (b.get("ids") or [])][:1000]
    except (TypeError, ValueError):
        return err(tr("Invalid data"))
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        c.execute(f"DELETE FROM notifications WHERE user_id=? AND id IN ({','.join('?' * len(part))})", (uid, *part))
    c.commit()
    return jsonify(ok=True, unread=news_unread(c, uid), sig=news_sig(c, uid))


@app.post("/api/news/read")
def news_read():
    """{ids: [...]} or {all: true}: marks my items read (other users' ids are ignored). No version bump."""
    from ..notify.push import push_handled
    b = body()
    c = db()
    uid = me()
    ts = iso(now_utc())
    tids = set()  # 2.0.5: the tasks of the items read -> close their notifications on my other devices
    marked = []
    if b.get("unread"):  # 2.13.0 (#453 A5): the undo of "Mark all as read": {unread: true, ids: [...]} -> unread again
        try:
            ids = [int(x) for x in (b.get("ids") or [])][:5000]
        except (TypeError, ValueError):
            return err(tr("Invalid data"))
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            c.execute(f"UPDATE notifications SET read_at=NULL WHERE user_id=? AND id IN ({','.join('?' * len(part))})", (uid, *part))
        c.commit()
        return jsonify(ok=True, unread=news_unread(c, uid), sig=news_sig(c, uid))
    if b.get("all"):
        tids |= {r[0] for r in c.execute("SELECT DISTINCT task_id FROM notifications WHERE user_id=? AND read_at IS NULL "
                                         "AND task_id IS NOT NULL", (uid,))}
        marked = [r[0] for r in c.execute("SELECT id FROM notifications WHERE user_id=? AND read_at IS NULL ORDER BY id DESC LIMIT 5000", (uid,))]
        c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL", (ts, uid))
    else:
        try:
            ids = [int(x) for x in (b.get("ids") or [])][:1000]
        except (TypeError, ValueError):
            return err(tr("Invalid data"))
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            q = ",".join("?" * len(part))
            tids |= {r[0] for r in c.execute(f"SELECT DISTINCT task_id FROM notifications WHERE user_id=? AND read_at IS NULL "
                                             f"AND task_id IS NOT NULL AND id IN ({q})", (uid, *part))}
            c.execute(f"UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL AND id IN ({q})",
                      (ts, uid, *part))
    push_handled(c, uid, sorted(tids), ("*",) if b.get("all") else ())  # 2.19.0 (#668): "all read" closes them all
    c.commit()
    return jsonify(ok=True, unread=news_unread(c, uid), sig=news_sig(c, uid), **({"marked": marked} if b.get("all") else {}))


NEWS_CLEAN = {"at": 0.0}


def news_cleanup(c, force=False):
    """Watchdog, at most hourly: drops items older than NEWS_KEEP_DAYS and all but the newest NEWS_KEEP_MAX per user."""
    if not force and time.time() - NEWS_CLEAN["at"] < 3600:
        return 0
    NEWS_CLEAN["at"] = time.time()
    n = c.execute("DELETE FROM notifications WHERE created_at<?",
                  (iso(now_utc() - timedelta(days=NEWS_KEEP_DAYS)),)).rowcount
    n += c.execute("""DELETE FROM notifications WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER
                      (PARTITION BY user_id ORDER BY id DESC) AS rn FROM notifications) WHERE rn>?)""",
                   (NEWS_KEEP_MAX,)).rowcount
    c.commit()
    return n
