"""Comments, mentions, the activity timeline and collaboration pushes."""
import json
import os
import re
import threading
import time
from datetime import date
from flask import g, has_request_context, jsonify, request

from ..core.config import app, PUBLIC_URL
from ..core.i18n import LANGS, short_day, tr, trn
from ..core.db import body, bump, db, err, inbox_default, iso, iso_ms, local_now, now_utc, usettings
from ..accounts.session import me
from ..core.access import collab_all, Denied, list_people, list_role, MANAGE_ROLES, need_feat, need_task, task_visible
from ..core.serializers import unlink_files
from ..tasks.tasks import WEB_COMMENT
from ..tasks.attachments import save_attachments
from ..integrations.paperless import pl_usable_ids


# ---------------------------------------------------------------- comments + activity timeline
# Everyone who sees a task may comment on it (view-only members too; they still cannot change the
# task). A private task's comments are a personal log. Authors edit / delete their own comments; the
# list owner and the list's admins (1.10.0) may delete any comment in the list (moderation). Instance admins have no extra
# rights here. Participants comment only on their own tasks (never on a context parent).
# Deleted comments disappear (soft delete: body, mentions and files are wiped).
# Mentions are stored as <@user_id> tokens (+ comments.mentions); only people who see the task count.
MAX_COMMENT = 10000
MENTION_RE = re.compile(r"<@(\d+)>")


def user_names(c, ids):
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {r["id"]: r["display_name"] or r["username"]
            for r in c.execute(f"SELECT id, username, display_name FROM users WHERE id IN ({q})", ids)}


def task_people(c, lid):
    """Enabled users who can see the tasks of a list (owner + members): the mention picker."""
    ids = list_people(c, lid)
    q = ",".join("?" * len(ids)) or "NULL"
    return [{"id": r["id"], "name": r["display_name"] or r["username"]}
            for r in c.execute(f"SELECT id, username, display_name FROM users WHERE id IN ({q}) AND disabled=0 ORDER BY id",
                               list(ids))]


def clean_mentions(c, lid, text):
    """Keeps <@id> tokens of people who see the list; any other token becomes plain '@name'."""
    allowed = {p["id"] for p in task_people(c, lid)}
    names = user_names(c, [int(x) for x in MENTION_RE.findall(text)])
    found = []

    def sub(m):
        uid = int(m.group(1))
        if uid in allowed:
            found.append(uid)
            return m.group(0)
        return "@" + names.get(uid, "?")
    text = MENTION_RE.sub(sub, text)
    return text, list(dict.fromkeys(found))


def comment_plain(c, text, names=None):
    """Comment text for a push: tokens -> @name, whitespace collapsed."""
    names = names or user_names(c, [int(x) for x in MENTION_RE.findall(text)])
    return re.sub(r"\s+", " ", MENTION_RE.sub(lambda m: "@" + names.get(int(m.group(1)), "?"), text)).strip()


def att_dicts(c, where, args):
    out = {}
    for a in c.execute(f"SELECT id, comment_id, name, mime, size, created_at FROM attachments WHERE {where} ORDER BY id", args):
        out.setdefault(a["comment_id"], []).append({k: a[k] for k in ("id", "name", "mime", "size", "created_at")})
    return out


def comment_dict(r, atts):
    return {"id": r["id"], "user_id": r["user_id"], "body": r["body"], "created_at": r["created_at"],
            "edited_at": r["edited_at"], "mentions": [int(x) for x in (r["mentions"] or "").split(",") if x],
            "attachments": atts.get(r["id"], []), "suggestion": json.loads(r["suggestion"]) if r["suggestion"] else None}


def need_live_comment(c, cid):
    """(comment row, my role in its list): 404 if the comment is gone or its task is not visible."""
    r = c.execute("SELECT * FROM comments WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
    if not r:
        raise Denied(404)
    return r, need_task(c, r["task_id"], write=False, full=True)


@app.get("/api/tasks/<int:tid>/timeline")
def timeline(tid):
    """Comments + activity of a task (loaded when the detail panel opens) and the mention picker.
    2.0.6 (#315): comments no longer need collaboration (personal notes); without it (instance switch off)
    there is no activity and nobody to mention."""
    from ..personal.timetrack import vis_ids
    from ..tasks.dependencies import DEP_ACTS
    from ..agents.core import agent_ids, is_approver
    from ..collab.reactions import with_reactions
    c = db()
    role = need_task(c, tid, write=False, full=True)
    t = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()
    rows = c.execute("SELECT * FROM comments WHERE task_id=? AND deleted_at IS NULL ORDER BY id", (tid,)).fetchall()
    atts = att_dicts(c, "task_id=? AND comment_id IS NOT NULL", (tid,))
    acts = [{"id": a["id"], "user_id": a["user_id"], "kind": a["kind"], "data": json.loads(a["data"] or "{}"),
             "created_at": a["created_at"]}
            for a in c.execute("SELECT * FROM activity WHERE task_id=? ORDER BY id", (tid,))] if collab_all() else []
    vis, pl_ok = None, pl_usable_ids(c, me())
    for a in acts:
        if a["kind"] in ("paperless", "paperless_rm") and (a["data"].get("conn") or 0) not in pl_ok:
            a["data"] = {"title": tr("Paperless document")}
        if a["kind"] in DEP_ACTS and a["data"].get("id"):
            vis = vis if vis is not None else vis_ids(c, me())
            o = c.execute("SELECT list_id FROM tasks WHERE id=?", (a["data"]["id"],)).fetchone()
            if not o or o["list_id"] not in vis or not task_visible(c, a["data"]["id"], me()):
                a["data"] = {"hidden": True}
    comments = with_reactions(c, [comment_dict(r, atts) for r in rows])
    ids = {x["user_id"] for x in comments + acts} | {m for x in comments for m in x["mentions"]} \
        | {a["data"].get("to") for a in acts if a["kind"] == "assign"} | {a["data"].get("agent") for a in acts} | {a["data"].get("approver") for a in acts} \
        | {a["data"].get("by") for a in acts} | {u["id"] for x in comments for e in x["reactions"] for u in e["users"]}
    seen = c.execute("SELECT seen_id FROM task_seen WHERE user_id=? AND task_id=?", (me(), tid)).fetchone()
    ag = agent_ids(c)
    ppl = task_people(c, t["list_id"]) if collab_all() else []
    for p in ppl:
        if p["id"] in ag:
            p["agent"] = True
    return jsonify(comments=comments, activity=acts, users={str(k): v for k, v in user_names(c, ids).items()},
                   people=ppl, seen=seen[0] if seen else 0, moderator=role in MANAGE_ROLES,
                   agents=sorted(i for i in ids | {p["id"] for p in ppl} if i in ag),
                   can_write=task_visible(c, tid, me(), write=True),
                   approver=is_approver(c, c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone(), me()))  # 2.2.0 (#339)


@app.post("/api/tasks/<int:tid>/seen")
def timeline_seen(tid):
    """Marks every comment of the task as seen by me (no version bump: only my unread dot changes)."""
    from ..notify.push import push_handled
    c = db()
    need_task(c, tid, write=False, full=True)
    top = c.execute("SELECT COALESCE(MAX(id),0) FROM comments WHERE task_id=?", (tid,)).fetchone()[0]
    c.execute("INSERT INTO task_seen(user_id,task_id,seen_id) VALUES(?,?,?) "
              "ON CONFLICT(user_id,task_id) DO UPDATE SET seen_id=MAX(seen_id, excluded.seen_id)", (me(), tid, top))
    c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND task_id=? AND read_at IS NULL", (iso(now_utc()), me(), tid))
    push_handled(c, me(), [tid])
    c.commit()
    return jsonify(ok=True, seen=top)


def comment_input():
    """(text, files) from a JSON body or a multipart form (comment with files)."""
    from ..personal.timetrack import web_fields
    if request.files or request.form:
        web_fields({k: 1 for k in [*request.form, *request.files]}, {"body", "file"}, "POST /api/tasks/{tid}/comments (form)")
        return (request.form.get("body") or "").strip(), [f for f in request.files.getlist("file") if f and f.filename]
    web_fields(body(), WEB_COMMENT, "POST /api/tasks/{tid}/comments")
    return (body().get("body") or "").strip(), []


@app.post("/api/tasks/<int:tid>/comments")
def comment_create(tid):
    """2.0.6 (#315): also without collaboration (a personal note). Only with collaboration on (instance switch):
    @mentions, pushes, News and agent events; comments off in my settings: refused (409), agents excepted."""
    from ..personal.timetrack import BadInput
    from ..integrations.webhooks import wh_note
    from ..agents.core import agent_comment_events, is_agent, tidy_agent_of
    from ..collab.reactions import clean_suggestion, with_reactions
    from ..integrations.git import git_merge_link, git_merge_request
    c = db()
    if not is_agent(g.user):
        need_feat("comments")
    need_task(c, tid, write=False, full=True)  # view-only members may comment (participants: on their own tasks)
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if t["deleted_at"]:
        return err(tr("The task is in the trash"), 409)
    text, files = comment_input()
    if len(text) > MAX_COMMENT:
        return err(tr("The comment is too long (max. {0} characters)", MAX_COMMENT))
    if not text and not files:
        return err(tr("The comment is empty"))
    text, mentions = clean_mentions(c, t["list_id"], text) if collab_all() else (text, [])
    sug = body().get("suggestion") if not (request.files or request.form) else None
    if isinstance(sug, dict) and sug.get("kind") == "merge_request":  # 2.2.0 (#339): "ready to merge" of a coding agent
        if not is_agent(g.user):
            return err(tr("Only agents can post suggestions"), 403)
        if not task_visible(c, tid, me(), write=True):
            raise Denied(403)
        try:
            sug = git_merge_request(c, t, sug)
        except BadInput as e:
            return err(str(e))
    elif isinstance(sug, dict) and sug.get("kind") in ("integrate", "deploy"):  # 2.26.0 (#949): ready to integrate / deploy
        from ..agents.gates import gate_clean
        if not is_agent(g.user):
            return err(tr("Only agents can post suggestions"), 403)
        if not task_visible(c, tid, me(), write=True):
            raise Denied(403)
        try:
            sug = gate_clean(c, t, sug)
        except BadInput as e:
            return err(str(e))
    elif sug is not None:  # 2.0.0: a tidy suggestion (agents, in lists with tidying on)
        if not is_agent(g.user):
            return err(tr("Only agents can post suggestions"), 403)
        if (c.execute("SELECT agent_tidy FROM lists WHERE id=?", (t["list_id"],)).fetchone()[0] or "off") == "off":
            return err(tr("Tidying up is turned off in this list"), 409)
        if not task_visible(c, tid, me(), write=True):
            raise Denied(403)
        if tidy_agent_of(c, t["list_id"]) != me():  # 2.4.1 (#379)
            return err(tr("Another agent tidies up this list"), 403)
        try:
            sug = {**clean_suggestion(c, t, sug), "state": "open"}
        except BadInput as e:
            return err(str(e))
    cid = c.execute("INSERT INTO comments(task_id,user_id,body,mentions,created_at,suggestion) VALUES(?,?,?,?,?,?)",
                    (tid, me(), text, ",".join(map(str, mentions)), iso_ms(now_utc()),
                     json.dumps(sug, ensure_ascii=False) if sug else None)).lastrowid
    if sug and sug.get("kind") == "merge_request":
        git_merge_link(c, t, sug)
    saved = []
    e = save_attachments(c, tid, files, comment_id=cid, saved=saved) if files else None
    if e:
        c.rollback()
        unlink_files(saved)
        return err(e)
    c.execute("INSERT INTO task_seen(user_id,task_id,seen_id) VALUES(?,?,?) "
              "ON CONFLICT(user_id,task_id) DO UPDATE SET seen_id=MAX(seen_id, excluded.seen_id)", (me(), tid, cid))
    pushes = comment_pushes(c, t, cid, text, mentions, mentions, len(files)) if collab_all() else []
    if collab_all():
        agent_comment_events(c, t, cid, mentions, mentions)
    wh_note(c, tid, "comment", cid=cid)
    bump(c)
    c.commit()
    send_pushes(pushes)
    r = c.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
    return jsonify(with_reactions(c, [comment_dict(r, att_dicts(c, "comment_id=?", (cid,)))])[0])


@app.patch("/api/comments/<int:cid>")
def comment_update(cid):
    """Only the author edits a comment; people mentioned for the first time are notified (with collaboration on)."""
    from ..personal.timetrack import web_fields
    from ..agents.core import agent_comment_events, is_agent
    from ..collab.reactions import with_reactions
    c = db()
    if not is_agent(g.user):
        need_feat("comments")
    r, _ = need_live_comment(c, cid)
    if r["user_id"] != me():
        return err(tr("Only the author can edit this comment"), 403)
    t = c.execute("SELECT * FROM tasks WHERE id=?", (r["task_id"],)).fetchone()
    text = (web_fields(body(), {"body"}, "PATCH /api/comments/{cid}").get("body") or "").strip()
    if len(text) > MAX_COMMENT:
        return err(tr("The comment is too long (max. {0} characters)", MAX_COMMENT))
    nfiles = c.execute("SELECT COUNT(*) FROM attachments WHERE comment_id=?", (cid,)).fetchone()[0]
    if not text and not nfiles:
        return err(tr("The comment is empty"))
    text, mentions = clean_mentions(c, t["list_id"], text) if collab_all() else (text, [])
    old = {int(x) for x in (r["mentions"] or "").split(",") if x}
    c.execute("UPDATE comments SET body=?, mentions=?, edited_at=? WHERE id=?",
              (text, ",".join(map(str, mentions)), iso(now_utc()), cid))
    new_m = [m for m in mentions if m not in old] if collab_all() else []
    pushes = comment_pushes(c, t, cid, text, mentions, new_m, 0, only=new_m) if new_m and not t["deleted_at"] else []
    if new_m and not t["deleted_at"]:
        agent_comment_events(c, t, cid, mentions, new_m, created=False)
    bump(c)
    c.commit()
    send_pushes(pushes)
    return jsonify(with_reactions(c, [comment_dict(c.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone(),
                                                   att_dicts(c, "comment_id=?", (cid,)))])[0])


@app.delete("/api/comments/<int:cid>")
def comment_delete(cid):
    """Author, or the owner of the list (moderation). The comment disappears with its files."""
    c = db()
    r, role = need_live_comment(c, cid)
    if r["user_id"] != me() and role not in MANAGE_ROLES:
        return err(tr("Only the author or the list owner can delete this comment"), 403)
    files = [a[0] for a in c.execute("SELECT path FROM attachments WHERE comment_id=?", (cid,))]
    c.execute("DELETE FROM attachments WHERE comment_id=?", (cid,))
    c.execute("UPDATE comments SET body='', mentions='', deleted_at=? WHERE id=?", (iso(now_utc()), cid))
    bump(c)
    c.commit()
    unlink_files(files)
    return jsonify(ok=True)


# ---- collaboration pushes (module "collab" of the recipient must be on; never to the person who acted;
# only users who still see the task; each via their own ntfy topic, in their own language; click opens it)
#  - comment: assignee, creator, everyone who commented before + mentioned people (even non-participants)
#  - assign / unassign: the new assignee / the previous one when someone else (re)assigns the task
#  - complete: creator + whoever assigned it, when someone else completes a task in a shared list
# Burst rule, shared by all of them (per recipient and task): the first push goes out right away; anything
# else on that task in the next TASK_PUSH_GAP seconds is only counted, and once that minute is over the
# watchdog sends ONE summary ("2 more comments · 1 more change", "you were mentioned").
TASK_PUSH_GAP = int(os.environ.get("TASKS_PUSH_GAP", "60"))  # seconds


def collab_on(s):
    return collab_all() and "collab" in (s.get("features") or "").split(",")


def collab_user(c, uid, lid=None):
    """Settings of a user who takes part in collaboration notifications (News feed and pushes) about
    list lid -- enabled, module "collab" on, still sees the list (lid None: no list check) -- else None.
    The feed entry is written for every such user; the push additionally needs an ntfy topic + burst gate."""
    u = c.execute("SELECT disabled FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["disabled"] or (lid is not None and not list_role(c, lid, uid)):
        return None
    s = usettings(c, uid)
    return s if collab_on(s) else None


def burst_gate(c, uid, tid, mentioned=False, event=False):
    """True = push now (time remembered); False = counted for the watchdog's summary."""
    now = time.time()
    st = c.execute("SELECT sent_at FROM task_push WHERE user_id=? AND task_id=?", (uid, tid)).fetchone()
    if st and now - st["sent_at"] < TASK_PUSH_GAP:
        c.execute("""UPDATE task_push SET pending=pending+?, events=events+?, mentioned=MAX(mentioned,?)
                     WHERE user_id=? AND task_id=?""", (0 if event else 1, 1 if event else 0, 1 if mentioned else 0, uid, tid))
        return False
    c.execute("INSERT INTO task_push(user_id,task_id,sent_at) VALUES(?,?,?) ON CONFLICT(user_id,task_id) "
              "DO UPDATE SET sent_at=excluded.sent_at, pending=0, events=0, mentioned=0", (uid, tid, now))
    return True


def lang_of(s):
    return s.get("lang") if s.get("lang") in LANGS else "en"


def comment_pushes(c, t, cid, text, mentions, notify_mentions, nfiles, only=None):
    """Decides who gets a push for this comment (burst state updated in c, caller commits).
    Returns [(user id, title, message, click, priority)] to send after the commit."""
    from ..collab.news import agent_push_ok, bell_all_users, news_add, notif_ok
    from ..notify.push import push_prio, push_reachable
    from ..agents.core import agent_ids
    author = me()
    ids = {t["assignee_id"], t["created_by"]} | set(notify_mentions)
    before = {r[0] for r in c.execute("SELECT DISTINCT user_id FROM comments WHERE task_id=? AND deleted_at IS NULL AND id<?",
                                      (t["id"], cid))}
    ids |= before
    ids |= bell_all_users(c, t["list_id"], "comment")  # 2.1.0 (#317): the bell "All" of a list: every comment (2.6.1: or "custom")
    if only is not None:
        ids = set(only)
    prev = c.execute("SELECT user_id FROM comments WHERE task_id=? AND deleted_at IS NULL AND id<? ORDER BY id DESC LIMIT 1",
                     (t["id"], cid)).fetchone()
    prev = prev[0] if prev else None
    ids.discard(None)
    ids.discard(author)
    if not ids:
        return []
    names = user_names(c, [author] + [int(x) for x in MENTION_RE.findall(text)])
    snippet = comment_plain(c, text, names)
    snippet = snippet[:280] + ("…" if len(snippet) > 280 else "")
    out = []
    ag = agent_ids(c)
    for uid in sorted(ids):
        s = collab_user(c, uid, t["list_id"]) if uid not in ag else None  # 2.0.0: agents get events (agent_comment_events)
        if not s or not task_visible(c, t["id"], uid, full=True):  # 1.10.0: participants only about their tasks
            continue
        if "comments" not in (s.get("features") or "").split(","):  # 2.0.6: comments off -> no comment News / pushes
            continue
        mentioned = uid in notify_mentions
        # 2.1.0 (#317): which event of the notification settings this comment is for uid (first match)
        row = "mention" if mentioned else "comment" if uid in (t["assignee_id"], t["created_by"]) else \
            "reply" if uid == prev else "follow"
        # 2.28.0 (#987): a reply to my comment (the one right before) is marked: it counts as "For you" in the News
        news_add(c, uid, "mention" if mentioned else "comment", task_id=t["id"], comment_id=cid, actor=author, row=row, s=s,
                 data={"reply": 1} if uid == prev and not mentioned else None)
        if not notif_ok(c, uid, s, row, "push", t["list_id"]) or not push_reachable(c, uid, s) or \
                not burst_gate(c, uid, t["id"], mentioned=mentioned):
            continue
        if not mentioned and not agent_push_ok(c, uid, s, author):  # 2.28.0 (#987): an agent's comments push only when wanted
            continue
        lg = lang_of(s)
        what = snippet or trn("{0} file", "{0} files", nfiles, lg=lg)
        who = names.get(author, "?")
        msg = tr("{0} mentioned you: {1}", who, what, lg=lg) if mentioned else tr("{0} commented: {1}", who, what, lg=lg)
        out.append((uid, t["title"], msg, f"{PUBLIC_URL}/#t/{t['id']}", push_prio(s), comment_push_extra(t, lg)))
    return out


def comment_push_extra(t, lg):
    """2.0.8 (#331): comment / mention pushes get the buttons Reply (opens the task with the comment box focused) and
    Done (completes it in the background, like the reminder's). An open task only; a completed one gets Reply alone."""
    acts = [(tr("Reply", lg=lg), f"{PUBLIC_URL}/#reply/{t['id']}")]
    if not t["status"] and not t["deleted_at"]:
        acts.append((tr("Done|action", lg=lg), f"{PUBLIC_URL}/#done/{t['id']}"))
    return {"actions": acts, "task": t["id"]}


def push_day(due, due_time, lg):
    day = tr("today", lg=lg) if due == local_now().date().isoformat() else \
        short_day(date.fromisoformat(due), lg)
    return day + (" " + due_time if due_time else "")


def task_event(c, tid, kind, prev_assignee=None):
    """assign / unassign / complete pushes; queued in g.pushes and sent once the request succeeded."""
    from ..collab.news import agent_push_ok, bell_all_users, KIND_ROW, news_add, notif_ok
    from ..notify.push import push_prio, push_reachable
    from ..agents.core import agent_assign_event, agent_ids
    actor = me()
    t = c.execute("""SELECT t.*, l.name AS list_name, l.is_inbox AS list_inbox FROM tasks t JOIN lists l ON l.id=t.list_id
                     WHERE t.id=?""", (tid,)).fetchone()
    if not t or t["deleted_at"]:
        return
    if kind == "assign":
        rcpt = {t["assignee_id"]}
        agent_assign_event(c, tid, "assigned", t["assignee_id"])
    elif kind == "unassign":
        rcpt = {prev_assignee}
        agent_assign_event(c, tid, "unassigned", prev_assignee)
    else:  # complete: only in shared lists (in a private list the creator is the one completing), or via a public link
        if actor and not c.execute("SELECT 1 FROM list_members WHERE list_id=?", (t["list_id"],)).fetchone():
            return
        rcpt = {t["created_by"], t["assigned_by"]} | bell_all_users(c, t["list_id"], "complete")  # 2.1.0: bell "All" (2.6.1: "custom")
    rcpt.discard(None)
    rcpt.discard(actor)
    rcpt -= agent_ids(c)  # 2.0.0: agents get events (agent_assign_event), no pushes / News
    name = user_names(c, [actor]).get(actor, "?")
    for uid in sorted(rcpt):
        s = collab_user(c, uid, t["list_id"])
        if not s or (kind != "unassign" and not task_visible(c, tid, uid, full=True)):
            continue
        news_add(c, uid, kind, task_id=tid, actor=actor, s=s)
        if not notif_ok(c, uid, s, KIND_ROW[kind], "push", t["list_id"]) or not push_reachable(c, uid, s) or \
                not burst_gate(c, uid, tid, event=True):
            continue
        if kind == "complete" and not agent_push_ok(c, uid, s, actor):  # 2.28.0 (#987)
            continue
        lg = lang_of(s)
        who = name if actor else tr("Someone via the public link", lg=lg)
        lname = tr("Inbox", lg=lg) if t["list_inbox"] and inbox_default(t["list_name"]) else t["list_name"]
        if kind == "assign":
            title = tr("{0} assigned you: {1}", who, t["title"], lg=lg)
            msg = lname + (" · " + tr("due {0}", push_day(t["due"], t["due_time"], lg), lg=lg) if t["due"] else "")
        elif kind == "unassign":
            title, msg = tr("{0} unassigned you from: {1}", who, t["title"], lg=lg), lname
        else:
            title, msg = tr("{0} completed: {1}", who, t["title"], lg=lg), lname
        g.pushes.append((uid, title, msg, f"{PUBLIC_URL}/#t/{tid}", push_prio(s)))


def assignment_events(c, tid, old_assignee, new_assignee):
    if old_assignee == new_assignee:
        return
    if new_assignee:
        task_event(c, tid, "assign")
    if old_assignee:
        task_event(c, tid, "unassign", prev_assignee=old_assignee)


def send_pushes(pushes):
    from ..notify.push import notify
    if pushes:
        # (uid, title, msg, click, prio[, extra]): extra = notify() keywords (2.0.8: actions + task of comment pushes)
        threading.Thread(target=lambda: [notify(x[0], x[1], x[2], x[4], x[3], **(x[5] if len(x) > 5 else {}))
                                         for x in pushes], daemon=True).start()


@app.after_request
def send_queued_pushes(resp):
    p = g.pop("pushes", None) if has_request_context() else None
    if p and resp.status_code < 400:
        send_pushes(p)
    return resp


def task_push_tick(c, users, S, LG):
    """Watchdog: one summary push for everything collected during the burst window."""
    from ..notify.push import _wd_fail
    now = time.time()
    rows = c.execute("""SELECT p.*, t.title, t.list_id, t.deleted_at FROM task_push p JOIN tasks t ON t.id=p.task_id
                        WHERE (p.pending>0 OR p.events>0) AND p.sent_at<=?""", (now - TASK_PUSH_GAP,)).fetchall()
    for p in rows:
        try:
            _push_tick_one(c, p, users, S, LG, now)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "collab push", (p["user_id"], p["task_id"]), e)
    c.execute("DELETE FROM task_push WHERE pending=0 AND events=0 AND sent_at<?", (now - 86400,))
    c.commit()


def _push_tick_one(c, p, users, S, LG, now):
    from ..notify.push import notify, push_prio
    c.execute("UPDATE task_push SET sent_at=?, pending=0, events=0, mentioned=0 WHERE user_id=? AND task_id=?",
              (now, p["user_id"], p["task_id"]))
    c.commit()
    uid = p["user_id"]
    if uid not in users or p["deleted_at"] or not collab_on(S[uid]) or not task_visible(c, p["task_id"], uid, full=True):
        return
    lg = LG[uid]
    parts = ([trn("{0} more comment", "{0} more comments", p["pending"], lg=lg)] if p["pending"] else []) + \
        ([trn("{0} more change", "{0} more changes", p["events"], lg=lg)] if p["events"] else []) + \
        ([tr("you were mentioned", lg=lg)] if p["mentioned"] else [])
    ex = {}
    if p["pending"] or p["mentioned"]:  # 2.0.8: the summary of a comment burst gets Reply / Done too
        t = c.execute("SELECT id, status, deleted_at FROM tasks WHERE id=?", (p["task_id"],)).fetchone()
        ex = comment_push_extra(t, lg) if t else {}
    notify(uid, p["title"], " · ".join(parts), push_prio(S[uid]), f"{PUBLIC_URL}/#t/{p['task_id']}", s=S[uid], **ex)
