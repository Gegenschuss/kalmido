"""What people see of agents: state, chat (files, reactions), jobs, wake."""
import json
import mimetypes
import os
import re
import uuid
import threading
import time
from flask import g, jsonify, request

from ..core.config import app, ATT_DIR, MAX_FILE_MB
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied, need_task, task_visible
from ..core.serializers import unlink_files
from ..tasks.validation import as_int, log_act
from ..tasks.attachments import safe_name, send_stored
from ..collab.comments import user_names
from ..personal.timetrack import BadInput, UnknownFields
from ..notify.alerts import aa_count, aa_oserr
from ..api.v1 import hit_limit, task_for, v1_args, v1_view
from ..agents.core import (
    agent_active, agent_emit, AGENT_EVENT_COMMENT_CHARS, agent_public, agent_row, agent_task_data, agents_for,
    CHAT_KEEP, CHAT_MAX, is_agent, JOB_ACTIONS, job_dict, job_may_act, job_visible, list_agents, lst_brief,
    need_chat_agent, WAKE_LIMIT,
)
from ..collab.reactions import clean_emoji


# ---- agents: what people see (state, chat, jobs, wake)
@app.get("/api/agents")
def agents_get():
    c = db()
    return jsonify(agents=agents_for(c, me()) if not is_agent(g.user) else [])


@app.get("/api/agents/jobs")
def agent_jobs_get():
    """Jobs I can see (the linked task, or jobs for me; admins all), newest first. ?agent_id= ?state=open|all"""
    c = db()
    q, args = "SELECT * FROM agent_jobs", []
    where = []
    if request.args.get("agent_id"):
        where.append("agent_id=?")
        args.append(as_int(request.args["agent_id"], "agent_id", 1))
    if request.args.get("state", "all") == "open":
        where.append("state IN ('running','waiting')")
    rows = c.execute(q + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY updated_at DESC, id DESC LIMIT 500", args).fetchall()
    rows = [j for j in rows if job_visible(c, j, me())][:200]
    names = user_names(c, [x for j in rows for x in (j["agent_id"], j["user_id"], j["action_by"])])
    return jsonify(jobs=[{**job_dict(c, j, names), "can_act": job_may_act(c, j, me(), "approve"),
                          "can_stop": job_may_act(c, j, me(), "stop")} for j in rows])


@app.post("/api/agents/jobs/<int:jid>/action")
def agent_job_action(jid):
    """{action: approve|reject|stop} -- sent to the agent as a 'job' event, shown in the task's history."""
    from ..api.scopes import approval_run
    c = db()
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    if not j or not job_visible(c, j, me()):
        raise Denied(404)
    action = body().get("action")
    if action not in JOB_ACTIONS:
        return err(tr("Invalid value: {0}", "action"))
    if not job_may_act(c, j, me(), action):
        raise Denied(403, tr("Only the list owner, a list admin, the assignee or the person the job is for can do this"))
    if j["state"] in ("done", "failed", "stopped"):
        return err(tr("This job has already ended"), 409)
    if j["approval"] and action == "approve":  # 2.15.0 (#479): run the agent's stored request now
        if j["state"] != "waiting":
            return err(tr("This job has already ended"), 409)
        return approval_run(c, j)
    if j["kind"] and action == "approve":  # 2.3.0: a proposal is applied from its dialog (selection + edits)
        return err(tr("Open the proposal to review and apply it"), 409)
    if j["kind"]:
        c.execute("UPDATE agent_jobs SET prop_state='discarded' WHERE id=?", (jid,))
    if j["approval"]:  # 2.15.0 (#479): rejected / stopped: the stored request can never run any more
        c.execute("UPDATE agent_jobs SET approval=? WHERE id=?", (json.dumps({**json.loads(j["approval"]), "ran": 1, "rejected": 1}), jid))
    state = {"approve": "running", "reject": "stopped", "stop": "stopped"}[action]
    if action == "approve" and j["state"] != "waiting":
        state = j["state"]
    ts = iso(now_utc())
    c.execute("UPDATE agent_jobs SET action=?, action_by=?, action_at=?, state=?, updated_at=? WHERE id=?",
              (action, me(), ts, state, ts, jid))
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    data = {"job": job_dict(c, j), "action": action, "user": {"id": me(), "name": user_names(c, [me()]).get(me(), "")}}
    if j["task_id"]:
        t = c.execute("SELECT * FROM tasks WHERE id=?", (j["task_id"],)).fetchone()
        if t:
            log_act(c, t["id"], "agent_job", {"agent": j["agent_id"], "action": action, "title": j["title"][:200]})
            if task_visible(c, t["id"], j["agent_id"], full=True):
                data.update(task=task_for(c, t, j["agent_id"]), list=lst_brief(c, t["list_id"]))
    agent_emit(c, j["agent_id"], "job", data)
    bump(c)
    c.commit()
    return jsonify(job_dict(c, j))


def chat_dict(r, rx=None, files=None, api=False):
    """rx: {message id: reactions} of chat_reactions_of (2.7.2, #421); delivered_at (#422): when the agent fetched a person's
    message (null = not yet; the agent's own messages: null). 2.13.1 (#465): files = chat_files_of (attachments: id, name,
    mime, size, url; api: the REST address /api/v1/chat-attachments/{id}, else the app's)."""
    return {"id": r["id"], "agent_id": r["agent_id"], "user_id": r["user_id"], "from": r["sender"], "body": r["body"],
            "task_id": r["task_id"], "created_at": r["created_at"], "delivered_at": r["delivered_at"],
            "reactions": (rx or {}).get(r["id"], []), "asks": r["sender"] == "agent" and chat_asks(r["body"]),
            "attachments": [{**f, "url": (f"/api/v1/chat-attachments/{f['id']}" if api else f"/api/chat-files/{f['id']}")}
                            for f in (files or {}).get(r["id"], [])]}


# ---- 2.13.1 (#465): images / files in the chat between a person and an agent. Same limits and checks as task attachments
# (MAX_FILE_MB per file, safe names, the sandbox CSP when shown); stored under ATT_DIR/chat/<agent>-<person>/. Only the
# two sides of the conversation can fetch them (the person in the app or with a token, the agent with its token); only
# the sender removes them. Trimmed messages (CHAT_KEEP) and deleted conversations take their files along.
CHAT_FILES_MAX = 10   # files per message


def chat_files_of(c, mids):
    out, mids = {}, [x for x in mids if x]
    if not mids:
        return out
    for r in c.execute(f"SELECT id, message_id, name, mime, size FROM chat_files WHERE message_id IN ({','.join('?' * len(mids))}) ORDER BY id", mids):
        out.setdefault(r["message_id"], []).append({"id": r["id"], "name": r["name"], "mime": r["mime"], "size": r["size"]})
    return out


def chat_one(c, r, api=False):
    """chat_dict of one row with its reactions and files."""
    return chat_dict(r, chat_reactions_of(c, [r["id"]]), chat_files_of(c, [r["id"]]), api=api)


def chat_upload_files():
    """The files of a multipart chat message (field `file`, repeatable), else []."""
    files = [f for f in request.files.getlist("file") if f and f.filename]
    if len(files) > CHAT_FILES_MAX:
        raise BadInput(tr("At most {0} files per message", CHAT_FILES_MAX))
    return files


def chat_input(allowed):
    """(body dict, files) of a chat message: JSON, or a multipart form (body, task_id, file...)."""
    if request.files or request.form:
        b = {k: request.form.get(k) for k in request.form}
        unknown = sorted(k for k in [*request.form, *request.files] if k not in (*allowed, "file"))
        if unknown:
            raise UnknownFields(unknown)
        return b, chat_upload_files()
    return None, []


def chat_save_files(c, m, files, saved):
    """Stores the uploaded files of chat row m. Returns an error message or None (caller commits / rolls back + unlinks)."""
    if m["sender"] == "user":  # 2.24.0 (#910): a person's files count towards their storage
        from ..admin.hosting import quota_guard
        quota_guard(c, m["user_id"])
    sub = os.path.join("chat", f"{m['agent_id']}-{m['user_id']}")
    try:
        os.makedirs(os.path.join(ATT_DIR, sub), exist_ok=True)
    except OSError as e:
        aa_count("storage", "attachments", aa_oserr(e))
        raise
    ts = iso(now_utc())
    for f in files:
        name = safe_name(f.filename)
        rel = os.path.join(sub, f"{uuid.uuid4().hex[:12]}-{name}")
        full = os.path.join(ATT_DIR, rel)
        try:
            f.save(full)
        except OSError as e:
            aa_count("storage", "attachments", aa_oserr(e))
            raise
        saved.append(rel)
        size = os.path.getsize(full)
        if size > MAX_FILE_MB * 1024 * 1024:
            return tr("{0}: larger than {1} MB", name, MAX_FILE_MB)
        if not size:
            return tr("{0}: the file is empty and was not uploaded", name)
        mime = (f.mimetype if f.mimetype and f.mimetype != "application/octet-stream" else None) \
            or mimetypes.guess_type(name)[0] or "application/octet-stream"
        c.execute("INSERT INTO chat_files(message_id,name,mime,size,path,created_at) VALUES(?,?,?,?,?,?)",
                  (m["id"], name, mime, size, rel, ts))
    return None


def chat_file_paths(c, where, args):
    return [r[0] for r in c.execute(f"SELECT f.path FROM chat_files f JOIN agent_chat m ON m.id=f.message_id WHERE {where}", args)]


def chat_post(c, aid, uid, sender, b, files, allowed_keys=("body", "task_id")):
    """A chat message with optional files (both sides). b: the fields; returns the new row (caller commits)."""
    text = b.get("body")
    if files and (text is None or (isinstance(text, str) and not text.strip())):
        text = ""
    else:
        text = chat_body(text)
    tid = chat_task(c, b.get("task_id"), uid, aid)
    r = chat_add(c, aid, uid, sender, text, tid)
    if files:
        saved = []
        try:
            e = chat_save_files(c, r, files, saved)
        except OSError:
            c.rollback()
            g.chat_unlink = []
            unlink_files(saved)
            raise
        if e:
            c.rollback()
            g.chat_unlink = []
            unlink_files(saved)
            raise BadInput(e)
    return r


def chat_file_row(c, fid):
    r = c.execute("""SELECT f.*, m.agent_id, m.user_id, m.sender FROM chat_files f JOIN agent_chat m ON m.id=f.message_id
                     WHERE f.id=?""", (fid,)).fetchone()
    if not r:
        raise Denied(404)
    return r


def chat_file_access(c, fid, write=False):
    """A chat file the current user may read (a side of its conversation) or, write=True, remove (its sender)."""
    r = chat_file_row(c, fid)
    uid = me()
    if is_agent(g.user):
        if r["agent_id"] != uid:
            raise Denied(404)
        side = "agent"
    else:
        if r["user_id"] != uid:
            raise Denied(404)
        side = "user"
    if write and r["sender"] != side:
        raise Denied(403, tr("Only the sender can remove this file"))
    return r


def chat_file_delete(c, r):
    """Removes one chat file; a message left without text and files goes as well. Returns the message (or None)."""
    c.execute("DELETE FROM chat_files WHERE id=?", (r["id"],))
    m = c.execute("SELECT * FROM agent_chat WHERE id=?", (r["message_id"],)).fetchone()
    if m and not (m["body"] or "").strip() and not c.execute("SELECT 1 FROM chat_files WHERE message_id=?", (m["id"],)).fetchone():
        c.execute("DELETE FROM agent_chat WHERE id=?", (m["id"],))
        m = None
    c.commit()
    unlink_files([r["path"]])
    return m


def chat_files_gc(c):
    """Watchdog: files of chat messages that no longer exist (a deleted person / agent) leave the disk. At most hourly."""
    if time.time() - _CHAT_GC["at"] < 3600:
        return 0
    _CHAT_GC["at"] = time.time()
    root = os.path.join(ATT_DIR, "chat")
    if not os.path.isdir(root):
        return 0
    known, n = {r[0] for r in c.execute("SELECT path FROM chat_files")}, 0
    for d in os.listdir(root):
        for fn in os.listdir(os.path.join(root, d)) if os.path.isdir(os.path.join(root, d)) else []:
            rel = os.path.join("chat", d, fn)
            full = os.path.join(ATT_DIR, rel)
            # a file just being uploaded has no row yet: only older ones count
            if rel not in known and time.time() - os.path.getmtime(full) > 3600:
                unlink_files([rel])
                n += 1
    return n


_CHAT_GC = {"at": 0.0}


# 2.13.0 (#453 A2): a 👍 / 👎 of the person counts as an approval / rejection only on an agent message that asks something:
# a question mark outside code blocks, inline code and links. A casual 👍 on a status report stays a plain reaction.
_CHAT_ASK_STRIP = re.compile(r"```.*?```|`[^`\n]*`|https?://\S+", re.S)


def chat_asks(body):
    return "?" in _CHAT_ASK_STRIP.sub(" ", body or "")


def chat_reactions_of(c, mids):
    """2.7.2 (#421): {message id: [{emoji, count, users: [{id, name}]}]} like reactions_of for comments."""
    out, mids = {}, [x for x in mids if x]
    if not mids:
        return out
    for r in c.execute(f"""SELECT r.message_id, r.emoji, r.user_id, u.display_name, u.username FROM chat_reactions r
                           JOIN users u ON u.id=r.user_id WHERE r.message_id IN ({','.join('?' * len(mids))})
                           ORDER BY r.created_at, r.user_id""", mids):
        lst = out.setdefault(r["message_id"], [])
        e = next((x for x in lst if x["emoji"] == r["emoji"]), None)
        if not e:
            e = {"emoji": r["emoji"], "count": 0, "users": []}
            lst.append(e)
        e["count"] += 1
        e["users"].append({"id": r["user_id"], "name": r["display_name"] or r["username"]})
    return out


def chat_delivered(c, aid, mids=None, user_id=None):
    """2.7.2 (#422): the agent has the person's messages now (mids: these; else every message of the conversation with
    user_id, or of all its conversations). The caller commits. Returns how many changed."""
    q, args = "UPDATE agent_chat SET delivered_at=? WHERE agent_id=? AND sender='user' AND delivered_at IS NULL", [iso_ms(now_utc()), aid]
    if mids is not None:
        mids = [int(x) for x in mids if isinstance(x, int)]
        if not mids:
            return 0
        q += f" AND id IN ({','.join('?' * len(mids))})"
        args += mids
    elif user_id:
        q += " AND user_id=?"
        args.append(user_id)
    return c.execute(q, args).rowcount


def chat_event_mids(envs):
    """The chat message ids inside event envelopes (event chat, data.message.id)."""
    out = []
    for e in envs:
        if isinstance(e, dict) and e.get("event") == "chat":
            m = (e.get("data") or {}).get("message") or {}
            if isinstance(m.get("id"), int):
                out.append(m["id"])
    return out


@app.get("/api/agents/<int:aid>/chat")
def agent_chat_get(aid):
    """My conversation with an agent, oldest first: the newest ?limit= messages (default 300, max 300); ?after=<id>: only
    newer ones; 2.12.2 (#451) ?before=<id>: the page of older ones (has_more: there are even older ones). Marks its answers read."""
    c = db()
    a = need_chat_agent(c, aid)
    after = as_int(request.args.get("after", 0), "after", 0)
    before = as_int(request.args.get("before", 0), "before", 0)
    limit = as_int(request.args.get("limit", 300), "limit", 1, 300)
    q, args = "SELECT * FROM agent_chat WHERE agent_id=? AND user_id=? AND id>?", [aid, me(), after]
    if before:
        q += " AND id<?"
        args.append(before)
    rows = c.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()[::-1]
    more = bool(rows) and bool(c.execute("SELECT 1 FROM agent_chat WHERE agent_id=? AND user_id=? AND id<? LIMIT 1",
                                         (aid, me(), rows[0]["id"])).fetchone())
    if c.execute("UPDATE agent_chat SET read_at=? WHERE agent_id=? AND user_id=? AND sender='agent' AND read_at IS NULL",
                 (iso(now_utc()), aid, me())).rowcount:
        c.commit()
    rx, fs = chat_reactions_of(c, [r["id"] for r in rows]), chat_files_of(c, [r["id"] for r in rows])
    # 2.7.2 (#422): the server's clock, so the app can tell how long ago a message was delivered
    return jsonify(agent=agent_public(c, a, me()), messages=[chat_dict(r, rx, fs) for r in rows], now=iso_ms(now_utc()), has_more=more)


def chat_task(c, v, uid_a, uid_b):
    """A task id both may see (with comments), else BadInput."""
    if v in (None, ""):
        return None
    tid = as_int(v, "task_id", 1)
    if not (task_visible(c, tid, uid_a, full=True) and task_visible(c, tid, uid_b, full=True)):
        raise BadInput(tr("Invalid value: {0}", "task_id"))
    return tid


def chat_body(v):
    if not isinstance(v, str) or not v.strip():
        raise BadInput(tr("The message is empty"))
    if len(v) > CHAT_MAX:
        raise BadInput(tr("The message is too long (max. {0} characters)", CHAT_MAX))
    return v.strip()


def chat_add(c, aid, uid, sender, text, tid):
    mid = c.execute("INSERT INTO agent_chat(agent_id,user_id,sender,body,task_id,created_at) VALUES(?,?,?,?,?,?)",
                    (aid, uid, sender, text, tid, iso_ms(now_utc()))).lastrowid
    cut = c.execute("SELECT id FROM agent_chat WHERE agent_id=? AND user_id=? ORDER BY id DESC LIMIT 1 OFFSET ?", (aid, uid, CHAT_KEEP)).fetchone()
    if cut:  # 2.13.1 (#465): the files of trimmed messages leave the disk
        g.chat_unlink = getattr(g, "chat_unlink", []) + chat_file_paths(c, "m.agent_id=? AND m.user_id=? AND m.id<=?", (aid, uid, cut[0]))
        c.execute("DELETE FROM agent_chat WHERE agent_id=? AND user_id=? AND id<=?", (aid, uid, cut[0]))
    return c.execute("SELECT * FROM agent_chat WHERE id=?", (mid,)).fetchone()


@app.post("/api/agents/<int:aid>/chat")
def agent_chat_post(aid):
    """{body, task_id?} -- a message to the agent (a 'chat' event). 2.13.1 (#465): or a multipart form (body?, task_id?,
    file...) with images / files (the body may then be empty)."""
    c = db()
    a = need_chat_agent(c, aid)
    if not agent_active(a):
        return err(tr("This agent is paused"), 409)
    try:
        fb, files = chat_input(("body", "task_id"))
        r = chat_post(c, aid, me(), "user", fb if fb is not None else body(), files)
    except UnknownFields as e:
        return err(str(e))
    except BadInput as e:
        return err(str(e))
    chat_emit(c, aid, r)
    c.commit()
    chat_unlink_trimmed()
    return jsonify(chat_one(c, r)), 201


def chat_emit(c, aid, r):
    """The 'chat' event for the agent about a person's message r (with its files: REST addresses)."""
    tid = r["task_id"]
    data = {"message": chat_one(c, r, api=True), "user": {"id": r["user_id"], "name": user_names(c, [r["user_id"]]).get(r["user_id"], "")}}
    if tid:
        data.update(agent_task_data(c, tid, aid))
    agent_emit(c, aid, "chat", data)


def chat_unlink_trimmed():
    paths = getattr(g, "chat_unlink", None)
    if paths:
        g.chat_unlink = []
        unlink_files(paths)


@app.get("/api/chat-files/<int:fid>")
def chat_file_get(fid):
    """2.13.1 (#465): a file of my chat with an agent (inline image / pdf / text, ?dl=1 download)."""
    return send_stored(chat_file_access(db(), fid))


@app.delete("/api/chat-files/<int:fid>")
def chat_file_del(fid):
    """2.13.1 (#465): removes a file I sent (a message left without text and files goes too)."""
    c = db()
    r = chat_file_access(c, fid, write=True)
    m = chat_file_delete(c, r)
    return jsonify(ok=True, message=chat_one(c, m) if m else None, message_id=r["message_id"])


# ---- 2.7.2 (#421): reactions on chat messages. Both sides may react (the person on the agent's answers and on their own
# messages, the agent on the person's); a person's 👍 / 👎 on one of the AGENT's messages that asks something (2.13.0:
# chat_asks) is an approval / rejection and the
# agent gets the event "reaction" (the envelope of comment reactions: reaction + approval, with chat_message instead of a
# comment). Reactions of agents never approve anything and send no event.
def chat_react(c, m, uid, emoji, on):
    """Adds (on) / removes uid's reaction on chat row m. Returns {approval} (caller commits)."""
    res = {"approval": None}
    if not on:
        c.execute("DELETE FROM chat_reactions WHERE message_id=? AND user_id=? AND emoji=?", (m["id"], uid, emoji))
        return res
    if not c.execute("INSERT OR IGNORE INTO chat_reactions(message_id,user_id,emoji,created_at) VALUES(?,?,?,?)",
                     (m["id"], uid, emoji, iso_ms(now_utc()))).rowcount:
        return res
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if is_agent(u) or m["sender"] != "agent" or uid != m["user_id"]:
        return res  # only the person of the conversation reacting to the agent's message counts
    if emoji in ("up", "down") and chat_asks(m["body"]):  # 2.13.0 (#453 A2): only on a question
        res["approval"] = "approved" if emoji == "up" else "rejected"
    who = {"id": uid, "name": user_names(c, [uid]).get(uid, "")}
    data = {"chat_message": {"id": m["id"], "text": m["body"][:AGENT_EVENT_COMMENT_CHARS], "from": m["sender"], "created_at": m["created_at"],
                             "task_id": m["task_id"]},
            "reaction": {"emoji": emoji, "user": who}, "approval": res["approval"], "user": who}
    if m["task_id"] and task_visible(c, m["task_id"], m["agent_id"], full=True):
        data.update(agent_task_data(c, m["task_id"], m["agent_id"]))
    agent_emit(c, m["agent_id"], "reaction", data)
    return res


def chat_react_req(c, m, uid):
    b = body() if not getattr(g, "v1_body", None) else g.v1_body
    emoji = clean_emoji(b.get("emoji"))
    if "on" in b and not isinstance(b["on"], bool):
        raise BadInput(tr("Invalid value: {0}", "on"))
    have = bool(c.execute("SELECT 1 FROM chat_reactions WHERE message_id=? AND user_id=? AND emoji=?", (m["id"], uid, emoji)).fetchone())
    on = b["on"] if isinstance(b.get("on"), bool) else not have
    own = (m["sender"] == "agent" and uid == m["agent_id"]) or (m["sender"] != "agent" and uid == m["user_id"])
    if on and own:  # 2.23.0 (#823): not on one's own message
        raise BadInput(tr("You cannot react to your own message"))
    res = chat_react(c, m, uid, emoji, on)
    c.commit()
    return {"ok": True, "message_id": m["id"], "reactions": chat_reactions_of(c, [m["id"]]).get(m["id"], []), **res}


@app.post("/api/agents/<int:aid>/chat/<int:mid>/reactions")
def agent_chat_react(aid, mid):
    """{emoji: up|down|heart or one emoji, on?: bool} -- toggles my reaction on a message of my chat with agent aid."""
    c = db()
    need_chat_agent(c, aid)
    m = c.execute("SELECT * FROM agent_chat WHERE id=? AND agent_id=? AND user_id=?", (mid, aid, me())).fetchone()
    if not m:
        raise Denied(404)
    try:
        return jsonify(chat_react_req(c, m, me()))
    except BadInput as e:
        return err(str(e))


def wake_limit():
    if hit_limit(f"wake:{me()}", WAKE_LIMIT, 600):
        raise Denied(429, tr("Too many requests, please slow down"))


@app.post("/api/tasks/<int:tid>/wake")
def task_wake(tid):
    """{agent_id?} -- an immediate 'wake' event about this task (the assignee if it is an agent, else the only agent of the
    list; with several, agent_id picks one). 2.4.1 (#376): no button any more; kept for agents without an event loop
    (a script or a person nudges them)."""
    c = db()
    need_task(c, tid, write=False, full=True)
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    cands = [a for a in list_agents(c, t["list_id"]) if agent_active(agent_row(c, a)) and task_visible(c, tid, a, full=True)]
    b = body()
    if b.get("agent_id") not in (None, ""):
        aid = as_int(b["agent_id"], "agent_id", 1)
        if aid not in cands:
            raise Denied(404)
    elif t["assignee_id"] in cands:
        aid = t["assignee_id"]
    elif len(cands) == 1:
        aid = cands[0]
    else:
        return err(tr("No agent can see this task") if not cands else tr("Choose an agent"), 409)
    wake_limit()
    seq = agent_emit(c, aid, "wake", agent_task_data(c, tid, aid, user={"id": me(), "name": user_names(c, [me()]).get(me(), "")}, source="task"))
    c.commit()
    return jsonify(ok=bool(seq), agent_id=aid)


@app.post("/api/agents/<int:aid>/wake")
def agent_wake(aid):
    """{task_id?} -- a 'wake' event for the agent (optionally about a task); API only since 2.4.1 (#376)."""
    c = db()
    a = need_chat_agent(c, aid)
    if not agent_active(a):
        return err(tr("This agent is paused"), 409)
    b = body()
    try:
        tid = chat_task(c, b.get("task_id"), me(), aid)
    except BadInput as e:
        return err(str(e))
    wake_limit()
    data = {"user": {"id": me(), "name": user_names(c, [me()]).get(me(), "")}, "source": "chat"}
    if tid:
        data.update(agent_task_data(c, tid, aid))
    seq = agent_emit(c, aid, "wake", data)
    c.commit()
    return jsonify(ok=bool(seq), agent_id=aid)


# ---- 2.22.0 (#693): "<name> is writing …" in a task's comments, for people and agents alike (like the chat's typing). A
# signal lasts TASK_TYPING_S seconds (send it again while writing); kept in memory only (one process, nothing to store).
# Everyone who sees the task's comments learns it with their next GET /api/version (field ty), never their own signal.
TASK_TYPING_S = 8
_TTYPE, _TTYPE_LOCK = {}, threading.Lock()


def task_typing_set(c, tid, uid):
    need_task(c, tid, write=False, full=True)
    now = time.time()
    with _TTYPE_LOCK:
        for k in [k for k, v in _TTYPE.items() if v <= now]:
            _TTYPE.pop(k, None)
        if len(_TTYPE) < 5000:
            _TTYPE[(tid, uid)] = now + TASK_TYPING_S
    return {"ok": True, "seconds": TASK_TYPING_S}


def task_typing_for(c, uid):
    """[{task_id, user_id, name}] of the signals in tasks uid may see fully (comments), without uid's own."""
    now = time.time()
    with _TTYPE_LOCK:
        live = [(t, u) for (t, u), v in _TTYPE.items() if v > now and u != uid]
    if not live:
        return []
    names = user_names(c, {u for _, u in live})
    return [{"task_id": t, "user_id": u, "name": names.get(u, "?")} for t, u in live if task_visible(c, t, uid, full=True)][:50]


@app.post("/api/tasks/<int:tid>/typing")
def task_typing(tid):
    """Says "I am writing a comment on this task" for TASK_TYPING_S seconds (also POST /api/v1/tasks/{id}/typing)."""
    c = db()
    return jsonify(task_typing_set(c, tid, me()))


@app.post("/api/v1/tasks/<int:tid>/typing")
@v1_view
def v1_task_typing(tid):
    v1_args(())
    c = db()
    return jsonify(task_typing_set(c, tid, me()))
