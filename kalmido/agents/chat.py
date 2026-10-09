"""What people see of agents: state, chat (files, reactions), jobs, wake."""
import json
import mimetypes
import os
import re
import uuid
import threading
import time
from datetime import timedelta
from flask import g, jsonify, request

from ..core.config import app, ATT_DIR, MAX_FILE_MB
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied, need_task, task_visible
from ..core.serializers import unlink_files
from ..tasks.validation import as_int, log_act
from ..tasks.attachments import safe_name, send_stored, unexec_name
from ..collab.comments import user_names
from ..personal.timetrack import BadInput, UnknownFields
from ..notify.alerts import aa_count, aa_oserr
from ..api.v1 import hit_limit, task_for, v1_args, v1_json, v1_view
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
    from ..agents.steps import job_steps_count
    jc = job_steps_count(c, me(), [j["id"] for j in rows if j["user_id"] == me()])  # 2.32.0 (#1081): only my own jobs' history
    return jsonify(jobs=[{**job_dict(c, j, names), "can_act": job_may_act(c, j, me(), "approve"),
                          "can_stop": job_may_act(c, j, me(), "stop"), "steps": jc.get(j["id"], 0) if j["user_id"] == me() else 0} for j in rows])


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


def chat_dict(r, rx=None, files=None, api=False, newest=None):
    """rx: {message id: reactions} of chat_reactions_of (2.7.2, #421); delivered_at (#422): when the agent fetched a person's
    message (null = not yet; the agent's own messages: null). 2.13.1 (#465): files = chat_files_of (attachments: id, name,
    mime, size, url; api: the REST address /api/v1/chat-attachments/{id}, else the app's). 2.30.0 (#1037): newest = the id
    of the conversation's newest message that is not a permission question (chat_newest), for choice_state."""
    ch = _jload(r["choices"]) if "choices" in r.keys() else None
    ans = _jload(r["choice"]) if "choice" in r.keys() else None
    return {"id": r["id"], "agent_id": r["agent_id"], "user_id": r["user_id"], "from": r["sender"], "body": r["body"],
            "task_id": r["task_id"], "created_at": r["created_at"], "delivered_at": r["delivered_at"],
            "reactions": (rx or {}).get(r["id"], []), "asks": r["sender"] == "agent" and (chat_asks(r["body"]) or bool(ch and (ch.get("permission") or ch.get("approval")))),
            # 2.28.0 (#1005): answer buttons of an agent's message ({choices: [{id, label, style?}], multi}) and the person's
            # answer ({ids, at}); null without. 2.30.0 (#1037 / #1041): choices.permission (a permission question),
            # choices.expires_at; choice_state open | answered | expired (a newer message came, the time ran out) | withdrawn.
            # 2.35.0 (#1103): choices.approval = {title, what, std?} -- an approval request (buttons yes / no, a card)
            "choices": ch, "choice": ans, "choice_state": choice_state(r, ch, ans, newest),
            "job_id": r["job_id"] if "job_id" in r.keys() else None,  # 2.32.0 (#1081): the job whose result this is
            **chat_reply(r),  # 2.33.0 (#1076): reply_to + reply (the quote of the answered message)
            "attachments": [{**f, "url": (f"/api/v1/chat-attachments/{f['id']}" if api else f"/api/chat-files/{f['id']}")}
                            for f in (files or {}).get(r["id"], [])]}


def chat_reply(r):
    from ..collab.replies import reply_quotes
    rt = r["reply_to"] if "reply_to" in r.keys() else None
    return {"reply_to": rt, "reply": reply_quotes(db(), "a", [rt]).get(rt) if rt else None}


# ---- 2.30.0 (#1037): only the newest question's buttons are live. An agent message's buttons expire as soon as a newer
# message comes into the conversation (from the agent or from the person) -- except a permission question (#1041): it stays
# answerable while its host waits (until it is answered, its expires_at passed, or the agent withdraws it), and it does not
# make older buttons expire either. A press on expired buttons answers 409. The agent may withdraw a message's buttons.
def chat_newest(c, aid, uid):
    """Id of the newest message of the conversation that is not a permission question (0 = none). 2.35.0 (#1103): nor an
    approval request (it stays open like a permission question)."""
    r = c.execute("""SELECT MAX(id) FROM agent_chat WHERE agent_id=? AND user_id=?
                     AND (choices IS NULL OR (COALESCE(json_extract(choices, '$.permission'), 0) = 0
                                              AND json_extract(choices, '$.approval') IS NULL))""", (aid, uid)).fetchone()
    return (r[0] or 0) if r else 0


def choice_state(r, ch, ans, newest=None):
    """open | answered | expired | withdrawn of an agent message with buttons (None without)."""
    if not ch or r["sender"] != "agent":
        return None
    if ans:
        return "answered"
    if ch.get("withdrawn_at"):
        return "withdrawn" if not ch.get("outcome") else ("answered" if ch["outcome"] in ("allowed", "denied") else "expired")
    if ch.get("permission") or ch.get("approval"):  # 2.35.0 (#1103): approval requests too
        return "expired" if ch.get("expires_at") and ch["expires_at"] <= iso_ms(now_utc()) else "open"
    return "expired" if newest and newest > r["id"] else "open"


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
    return chat_dict(r, chat_reactions_of(c, [r["id"]]), chat_files_of(c, [r["id"]]), api=api,
                     newest=chat_newest(c, r["agent_id"], r["user_id"]))


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
        unexec = m["sender"] == "agent" and unexec_name(name) != name  # 2.30.0 (#380): no executable endings from agents
        if unexec:
            name = unexec_name(name)
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
        mime = "text/plain" if unexec else (f.mimetype if f.mimetype and f.mimetype != "application/octet-stream" else None) \
            or mimetypes.guess_type(name)[0] or "application/octet-stream"
        c.execute("INSERT INTO chat_files(message_id,name,mime,size,path,created_at) VALUES(?,?,?,?,?,?)",
                  (m["id"], name, mime, size, rel, ts))
    return None


def chat_file_paths(c, where, args):
    return [r[0] for r in c.execute(f"SELECT f.path FROM chat_files f JOIN agent_chat m ON m.id=f.message_id WHERE {where}", args)]


def _jload(v):
    try:
        return json.loads(v) if v else None
    except ValueError:
        return None


CHOICES_MAX, CHOICE_LABEL_MAX, CHOICE_ID_RE = 8, 80, re.compile(r"[A-Za-z0-9_.:-]{1,40}")
CHOICE_STYLES = ("default", "primary", "danger")
# 2.30.0 (#1041): a permission question = buttons allow / deny (given, or added by permission: true); expires_in: seconds
PERM_IDS, PERM_EXPIRES_MAX = ("allow", "deny"), 7 * 86400
PERM_CHOICES = [{"id": "allow", "label": "Allow", "style": "primary"}, {"id": "deny", "label": "Deny"}]


def chat_choices_clean(v, multi, permission=None, expires_in=None):
    """2.28.0 (#1005): choices from the agent -> the stored json, or None. [{id, label, style?}] (at most CHOICES_MAX, ids
    unique); multi: the person may pick several. Also accepted: a list of strings (id = label). 2.30.0 (#1041): permission
    true = a permission question (buttons allow / deny, added when missing); buttons with exactly the ids allow and deny
    count as one too (hosts from 2.28 / 2.29). expires_in: seconds the question stays open (permission questions)."""
    if permission not in (None, True, False, 0, 1, "1", "0", "true", "false"):
        raise BadInput(tr("Invalid value: {0}", "permission"))
    permission = permission in (True, 1, "1", "true")
    if expires_in not in (None, ""):
        try:
            expires_in = int(expires_in)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "expires_in")) from None
        if isinstance(expires_in, bool) or not 10 <= expires_in <= PERM_EXPIRES_MAX:
            raise BadInput(tr("Invalid value: {0}", "expires_in"))
    else:
        expires_in = None
    if permission and v in (None, "", []):
        v = PERM_CHOICES
    if expires_in and not permission and v in (None, "", []):
        raise BadInput(tr("Invalid value: {0}", "expires_in"))
    if v in (None, "", []):
        return None
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "choices")) from None
    if not isinstance(v, list) or len(v) > CHOICES_MAX:
        raise BadInput(tr("Invalid value: {0}", "choices"))
    out, ids = [], set()
    for x in v:
        if isinstance(x, str):
            x = {"id": x, "label": x}
        if not isinstance(x, dict) or not isinstance(x.get("id"), str) or not CHOICE_ID_RE.fullmatch(x["id"]) \
                or not isinstance(x.get("label", x["id"]), str) or not str(x.get("label", x["id"])).strip() or x["id"] in ids:
            raise BadInput(tr("Invalid value: {0}", "choices"))
        st = x.get("style", "default")
        if st not in CHOICE_STYLES:
            raise BadInput(tr("Invalid value: {0}", "choices"))
        ids.add(x["id"])
        out.append({"id": x["id"], "label": str(x.get("label", x["id"])).strip()[:CHOICE_LABEL_MAX], **({"style": st} if st != "default" else {})})
    if multi not in (None, True, False, 0, 1):
        raise BadInput(tr("Invalid value: {0}", "multi"))
    d = {"choices": out, "multi": bool(multi)}
    if permission or (sorted(ids) == sorted(PERM_IDS) and not multi):
        if sorted(ids) != sorted(PERM_IDS) or multi:
            raise BadInput(tr("Invalid value: {0}", "choices"))
        d["permission"] = True
    if expires_in:
        if not d.get("permission"):
            raise BadInput(tr("Invalid value: {0}", "expires_in"))
        d["expires_at"] = iso_ms(now_utc() + timedelta(seconds=expires_in))
    return json.dumps(d, ensure_ascii=False)


# ---- 2.35.0 (#1103): an approval request = an agent's message the person answers with yes / no on a card of its own
# ("Approval needed", pinned at the top of the chat until answered, counted at the agent). Buttons with the fixed ids yes
# (primary) and no; it stays open like a permission question (newer messages do not expire it) until answered, its
# expires_in passed or the agent withdraws it. The answer reaches the agent as chat_choice with approval approved |
# rejected (also by a 👍 / 👎 on the card). Silence is never a yes.
APPROVAL_IDS, APPROVAL_TITLE_MAX, APPROVAL_WHAT_MAX = ("yes", "no"), 200, 1000
# review M5: at most APPROVAL_OPEN_MAX open approval requests per agent and person (the next one: 409); the chat returns the
# newest APPROVAL_PIN_MAX open ones; at most APPROVAL_PUSH_HOUR "Approval needed" pushes per agent and person an hour
APPROVAL_OPEN_MAX, APPROVAL_PIN_MAX, APPROVAL_PUSH_HOUR = 10, 20, 5


def chat_approval_clean(v, expires_in=None):
    """{title, what?, yes_label?, no_label?} (or its json string) -> the stored choices json. BadInput."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "approval")) from None
    if not isinstance(v, dict) or any(k not in ("title", "what", "yes_label", "no_label") for k in v):
        raise BadInput(tr("Invalid value: {0}", "approval"))
    title, what = v.get("title"), v.get("what")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > APPROVAL_TITLE_MAX:
        raise BadInput(tr("Invalid value: {0}", "approval.title"))
    if what not in (None, "") and (not isinstance(what, str) or len(what.strip()) > APPROVAL_WHAT_MAX):
        raise BadInput(tr("Invalid value: {0}", "approval.what"))
    labels = []
    for k, std in (("yes_label", "Yes"), ("no_label", "No")):
        x = v.get(k)
        if x not in (None, "") and (not isinstance(x, str) or not x.strip()):
            raise BadInput(tr("Invalid value: {0}", f"approval.{k}"))
        labels.append(x.strip()[:CHOICE_LABEL_MAX] if x else None)
    d = json.loads(chat_choices_clean([{"id": "yes", "label": labels[0] or "Yes", "style": "primary"},
                                       {"id": "no", "label": labels[1] or "No"}], False))
    d["approval"] = {"title": title.strip(), "what": (what or "").strip(), **({"std": 1} if not any(labels) else {})}
    if expires_in not in (None, ""):
        try:
            expires_in = int(expires_in)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "expires_in")) from None
        if isinstance(expires_in, bool) or not 10 <= expires_in <= PERM_EXPIRES_MAX:
            raise BadInput(tr("Invalid value: {0}", "expires_in"))
        d["expires_at"] = iso_ms(now_utc() + timedelta(seconds=expires_in))
    return json.dumps(d, ensure_ascii=False)


def chat_approvals_open(c, aid, uid):
    """2.35.0 (#1103): the open approval requests + permission questions of agent aid to person uid (newest last)."""
    out = []
    for r in c.execute("""SELECT * FROM agent_chat WHERE agent_id=? AND user_id=? AND sender='agent' AND choice IS NULL
                          AND choices IS NOT NULL AND json_extract(choices, '$.withdrawn_at') IS NULL
                          AND (json_extract(choices, '$.approval') IS NOT NULL OR COALESCE(json_extract(choices, '$.permission'), 0) != 0)
                          ORDER BY id""", (aid, uid)):
        if choice_state(r, _jload(r["choices"]), None) == "open":
            out.append(r)
    return out


def _approval_of(ids):
    return "approved" if ids in (["allow"], ["yes"]) else "rejected" if ids in (["deny"], ["no"]) else None


def chat_choice_answer(c, m, ch, ids, uid, via):
    """Stores the person's answer on agent message m (open buttons) and sends the agent 'chat_choice'. 2.30.0 (#1041): on a
    permission question also the 'reaction' event a 👍 / 👎 sends (approval approved / rejected, via button), so hosts
    that listen for reactions keep working; a 👍 / 👎 answers it the other way round (via reaction). One answer per message:
    act once per message_id."""
    ans = {"ids": ids, "at": iso_ms(now_utc()), "user_id": uid, **({"via": via} if ch.get("permission") or ch.get("approval") else {})}
    c.execute("UPDATE agent_chat SET choice=? WHERE id=?", (json.dumps(ans), m["id"]))
    m2 = c.execute("SELECT * FROM agent_chat WHERE id=?", (m["id"],)).fetchone()
    labels = [x["label"] for x in ch["choices"] if x["id"] in ids]
    who = {"id": uid, "name": user_names(c, [uid]).get(uid, "")}
    data = {"message_id": m["id"], "choice_ids": ids, "labels": labels, "message": chat_one(c, m2, api=True), "user": who}
    if ch.get("permission"):
        data.update(permission=True, approval=_approval_of(ids), via=via)
    elif ch.get("approval"):  # 2.35.0 (#1103): an approval request
        a = ch["approval"]
        data.update(approval=_approval_of(ids), approval_request={"title": a.get("title", ""), "what": a.get("what", "")}, via=via)
    tdata = agent_task_data(c, m["task_id"], m["agent_id"]) if m["task_id"] and task_visible(c, m["task_id"], m["agent_id"], full=True) else {}
    agent_emit(c, m["agent_id"], "chat_choice", {**data, **tdata})
    if ch.get("permission") and via == "button":
        agent_emit(c, m["agent_id"], "reaction", {
            "chat_message": {"id": m["id"], "text": m["body"][:AGENT_EVENT_COMMENT_CHARS], "from": m["sender"], "created_at": m["created_at"],
                             "task_id": m["task_id"]},
            "reaction": {"emoji": "up" if ids == ["allow"] else "down", "user": who}, "approval": _approval_of(ids), "user": who,
            "via": "button", **tdata})
    return m2


def chat_choice_set(c, m, uid, ids):
    """2.28.0 (#1005): the person (the chat's partner) answers an agent message with buttons: stores the choice (once),
    sends the agent the event chat_choice. Returns the message row. BadInput / Denied."""
    ch = _jload(m["choices"])
    if m["sender"] != "agent" or not ch or m["user_id"] != uid:
        raise Denied(404)
    if m["choice"]:
        raise Denied(409, tr("This question was answered already"))
    if choice_state(m, ch, None, chat_newest(c, m["agent_id"], m["user_id"])) != "open":  # 2.30.0 (#1037): an old tab, an offline outbox
        raise Denied(409, tr("This suggestion is no longer current"))
    valid = [x["id"] for x in ch["choices"]]
    if not isinstance(ids, list) or not ids or not all(isinstance(x, str) and x in valid for x in ids) or len(set(ids)) != len(ids) \
            or (len(ids) > 1 and not ch.get("multi")):
        raise BadInput(tr("Invalid value: {0}", "choice_ids"))
    m2 = chat_choice_answer(c, m, ch, [x for x in valid if x in ids], uid, "button")
    bump(c)
    return m2


CHAT_OUTCOMES = ("allowed", "denied", "expired")


def chat_choices_withdraw(c, m, outcome=None):
    """2.30.0 (#1037): the agent takes back the open buttons of its message m (they disappear; a press answers 409).
    outcome (a permission question its host decided otherwise -- an answer in words, the host's time limit): allowed |
    denied | expired, shown instead of the buttons. Sends no event. Returns the row."""
    ch = _jload(m["choices"])
    if m["sender"] != "agent" or not ch:
        raise Denied(404)
    if outcome not in (None, "", *CHAT_OUTCOMES) or (outcome and not (ch.get("permission") or ch.get("approval"))) \
            or (outcome == "allowed" and ch.get("approval")):  # review N1: only the person approves, never the agent
        raise BadInput(tr("Invalid value: {0}", "outcome"))
    if m["choice"]:
        raise Denied(409, tr("This question was answered already"))
    ch = {**ch, "withdrawn_at": iso_ms(now_utc()), **({"outcome": outcome} if outcome else {})}
    c.execute("UPDATE agent_chat SET choices=? WHERE id=?", (json.dumps(ch, ensure_ascii=False), m["id"]))
    bump(c)
    return c.execute("SELECT * FROM agent_chat WHERE id=?", (m["id"],)).fetchone()


@app.post("/api/v1/agent/chats/<int:uid>/messages/<mid>/withdraw")
@v1_view
def v1_agent_chat_withdraw(uid, mid):
    """2.30.0 (#1037): {outcome?} -- the agent withdraws the open answer buttons of its message (MCP withdraw_chat_choices)."""
    from ..agents.core import agent_shares, need_agent
    v1_args(())
    aid = need_agent()
    c = db()
    mid = as_int(mid, "mid", 1)
    b = v1_json()
    unknown = sorted(k for k in b if k != "outcome")
    if unknown:
        raise UnknownFields(unknown)
    m = c.execute("SELECT * FROM agent_chat WHERE id=? AND agent_id=? AND user_id=?", (mid, aid, uid)).fetchone()
    if not m or not agent_shares(c, aid, uid):
        raise Denied(404)
    m2 = chat_choices_withdraw(c, m, b.get("outcome"))
    c.commit()
    return jsonify(chat_one(c, m2, api=True))


@app.post("/api/agents/<int:aid>/chat/<int:mid>/choice")
def agent_chat_choice(aid, mid):
    """2.28.0 (#1005): {choice_ids: [...]} -- I answer an agent's question with one of its buttons (several with multi)."""
    c = db()
    need_chat_agent(c, aid)
    m = c.execute("SELECT * FROM agent_chat WHERE id=? AND agent_id=? AND user_id=?", (mid, aid, me())).fetchone()
    if not m:
        raise Denied(404)
    try:
        m2 = chat_choice_set(c, m, me(), body().get("choice_ids"))
    except BadInput as e:
        return err(str(e))
    c.commit()
    return jsonify(chat_one(c, m2))


def chat_post(c, aid, uid, sender, b, files, allowed_keys=("body", "task_id")):
    """A chat message with optional files (both sides). b: the fields; returns the new row (caller commits).
    2.28.0 (#1005): an agent's message may carry choices (+ multi)."""
    text = b.get("body")
    if sender == "agent" and text in (None, "") and isinstance(b.get("approval"), (dict, str)) and b.get("approval"):
        try:  # 2.35.0 (#1103): an approval request without a text says its title
            av = json.loads(b["approval"]) if isinstance(b["approval"], str) else b["approval"]
            text = av.get("title") if isinstance(av, dict) and isinstance(av.get("title"), str) else text
        except ValueError:
            pass
    if files and (text is None or (isinstance(text, str) and not text.strip())):
        text = ""
    else:
        text = chat_body(text)
    tid = chat_task(c, b.get("task_id"), uid, aid)
    from ..collab.replies import reply_check
    orig = reply_check(c, "a", b.get("reply_to"), agent_id=aid, user_id=uid)  # 2.33.0 (#1076): the same conversation (else 400)
    if sender == "agent" and b.get("approval") not in (None, ""):  # 2.35.0 (#1103): an approval request
        if any(b.get(k) not in (None, "", [], False) for k in ("choices", "multi", "permission")):
            raise BadInput(tr("Invalid value: {0}", "approval"))
        choices = chat_approval_clean(b["approval"], b.get("expires_in"))
        if sum(1 for x in chat_approvals_open(c, aid, uid) if (_jload(x["choices"]) or {}).get("approval")) >= APPROVAL_OPEN_MAX:
            raise Denied(409, tr("Answer the open approval requests first (at most {0})", APPROVAL_OPEN_MAX))
    else:
        choices = chat_choices_clean(b.get("choices"), b.get("multi"), b.get("permission"), b.get("expires_in")) if sender == "agent" else None
    r = chat_add(c, aid, uid, sender, text, tid, choices)
    if orig:
        c.execute("UPDATE agent_chat SET reply_to=? WHERE id=?", (orig["id"], r["id"]))
        r = c.execute("SELECT * FROM agent_chat WHERE id=?", (r["id"],)).fetchone()
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


@app.put("/api/agents/<int:aid>/permission-mode")
def agent_permission_mode(aid):
    """2.29.0 (#1029): {mode: ask | auto | ''} from the chat header's badge -- the owner of a personal agent, an instance admin
    for a team agent. The agent's host reads it before its next run (runtime.permission_mode, event runtime_changed)."""
    from ..agents.admin import runtime_set
    from ..agents.core import may_set_runtime
    c = db()
    a = need_chat_agent(c, aid)
    if not may_set_runtime(c, a, me()):
        raise Denied(403, tr("Only the agent’s owner (a team agent: an admin) changes this"))
    b = body()
    new = runtime_set(c, a, {"permission_mode": b.get("mode")})
    bump(c)
    c.commit()
    return jsonify(ok=True, permission_mode=new["permission_mode"])


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
    nw = chat_newest(c, aid, me())
    # 2.32.0 (#1081): the agent's steps -- only here, only in the person's own conversation: stored ones with each answer
    # (steps), the live ones of a run in progress (steps_live, newest first), the history size of a job of mine (job_steps)
    from ..agents.steps import job_steps_count, steps_live, steps_of_messages
    sm = steps_of_messages(c, me(), [r["id"] for r in rows if r["sender"] == "agent"])
    jc = job_steps_count(c, me(), [r["job_id"] for r in rows if r["job_id"]])
    msgs = []
    for r in rows:
        d = chat_dict(r, rx, fs, newest=nw)
        if r["id"] in sm:
            d["steps"] = sm[r["id"]]
        if r["job_id"]:
            d["job_steps"] = jc.get(r["job_id"], 0)
        msgs.append(d)
    # 2.7.2 (#422): the server's clock, so the app can tell how long ago a message was delivered
    # 2.35.0 (#1103): the open approval requests (pinned at the top, also when older than this page)
    ap = chat_approvals_open(c, aid, me())[-APPROVAL_PIN_MAX:]
    return jsonify(agent=agent_public(c, a, me()), messages=msgs, now=iso_ms(now_utc()), has_more=more,
                   steps_live=steps_live(c, aid, me()),
                   approvals_open=[chat_dict(r, None, None, newest=nw) for r in ap])


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


def chat_add(c, aid, uid, sender, text, tid, choices=None):
    mid = c.execute("INSERT INTO agent_chat(agent_id,user_id,sender,body,task_id,created_at,choices) VALUES(?,?,?,?,?,?,?)",
                    (aid, uid, sender, text, tid, iso_ms(now_utc()), choices)).lastrowid
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
        fb, files = chat_input(("body", "task_id", "reply_to"))
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
    ch = _jload(m["choices"])
    perm = bool(ch and (ch.get("permission") or ch.get("approval")))  # 2.35.0 (#1103): approval requests answer the same way
    if emoji in ("up", "down") and (chat_asks(m["body"]) or perm):  # 2.13.0 (#453 A2): only on a question
        res["approval"] = "approved" if emoji == "up" else "rejected"
    stale = False
    if perm and res["approval"] and choice_state(m, ch, _jload(m["choice"])) != "open":
        res["approval"] = None  # 2.30.0 (#1041): an answered / expired permission question takes no go-ahead any more
        stale = True
    elif perm and res["approval"]:  # 👍 / 👎 = the buttons Allow / Deny (the answer shows the same way; chat_choice too)
        yes, no = ("yes", "no") if ch.get("approval") else ("allow", "deny")
        chat_choice_answer(c, m, ch, [yes if emoji == "up" else no], uid, "reaction")
    who = {"id": uid, "name": user_names(c, [uid]).get(uid, "")}
    data = {"chat_message": {"id": m["id"], "text": m["body"][:AGENT_EVENT_COMMENT_CHARS], "from": m["sender"], "created_at": m["created_at"],
                             "task_id": m["task_id"]},
            "reaction": {"emoji": emoji, "user": who}, "approval": res["approval"], "user": who}
    if stale:
        data["stale"] = True  # a 👍 on a closed permission question: hosts must read "approval", never the emoji
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


@app.post("/api/tasks/<int:tid>/editing")
def task_editing(tid):
    """2.27.0 (#999): "I am editing this task" (a field of its panel has the focus) for TASK_EDIT_S seconds: tidying waits."""
    from ..agents.core import task_editing_set
    c = db()
    return jsonify(task_editing_set(c, tid, me()))


@app.post("/api/v1/tasks/<int:tid>/typing")
@v1_view
def v1_task_typing(tid):
    v1_args(())
    c = db()
    return jsonify(task_typing_set(c, tid, me()))
