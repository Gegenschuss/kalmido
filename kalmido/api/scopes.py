"""Token scopes, approvals and the complete agent API (the routes the web client has)."""
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import threading
import time
from flask import g, jsonify, request, Response

from ..core.config import API_PREFIX, app
from ..core.i18n import N_, tr, trn
from ..core.db import bump, db, err, gsetting, iso, now_utc, usettings
from ..accounts.session import me
from ..core.access import Denied, need_list, need_task, need_time, ROLES, task_visible, token_lists, tvis, vis_sql, wr_sql
from ..core.serializers import load_tasks
from ..core.state import visible_lists
from ..lists.lists import list_delete, member_remove, member_set
from ..lists.sections import (
    _folder_paths, filter_create, filter_delete, filter_update, folder_delete, folder_rename, section_create,
    section_delete, section_update, sections_order,
)
from ..tasks.validation import as_int
from ..tasks.tasks import task_update
from ..tasks.lifecycle import task_restore, task_skip, trash_empty
from ..tasks.attachments import attachment_upload, text_attachment_create, TEXT_MAX
from ..tasks.batch import attachment_delete, task_batch
from ..collab.comments import collab_user, comment_delete, comment_update, lang_of, user_names
from ..collab.news import news_add, news_list, news_read
from ..personal.habits import habit_create, habit_delete, habit_update
from ..personal.timetrack import (
    BadInput, reject_unknown, time_delete, time_running, time_start, time_stop, time_update, UnknownFields,
)
from ..accounts.settings import export_json
from ..lists.templates import template_apply, template_create, template_delete, template_update, templates_list
from ..tasks.dependencies import dep_add, dep_remove, deps_get
from ..lists.projects import list_status_set, LIST_STATUSES
from ..lists.fields import field_create, field_delete, field_dict, field_update, need_field
from ..api.v1 import (
    _v1_live, API_SCOPES, api_scopes, cursor_dec, SCOPES, SCOPES_AGENT_DEFAULT, SCOPES_AGENT_NEVER, SCOPES_WRITE,
    STATUS_NAMES, v1_args, v1_call, v1_comment, v1_entry, v1_feature, v1_habit, v1_json, v1_limit, v1_one, v1_page,
    v1_task, V1_TASK_IN, v1_task_in, v1_view,
)
from ..api.openapi import openapi_spec
from ..agents.core import agent_emit, agent_row, is_agent, job_dict, JOB_LOG_MAX
from ..agents.admin import personal_agent_foreign
from ..agents.api import job_notify


# ---------------------------------------------------------------- 2.15.0 (#479): scopes + the complete agent API
# Every token (personal or an agent's) carries fine scopes; the OpenAPI document says per operation which one it needs
# (x-kalmido-scope) and api_authenticate enforces exactly that table (v1_scope_need), so documentation and enforcement
# cannot drift apart. Some routes need a second scope depending on their body (need_scope: a batch that deletes).
#   read               every GET (lists, tasks, comments, time, search, trash ...)
#   tasks:write        create / change / complete / move tasks and subtasks, dependencies, habits, waiting, day plan
#   comments           comments (write, edit, delete), reactions, News read state
#   structure          lists, sections, custom fields, list tags, templates, saved filters, folders, project overview, import
#   delete             tasks to the trash + restore + empty it, delete sections / lists / fields / templates / habits / filters
#   attachments:read   download files of tasks, comments and projects (their names come with read)
#   attachments:write  upload and remove them
#   time               time tracking (timer, entries)
#   export             the data export
#   calendar           2.21.0: events + event calendars (also reading them)
#   contacts           2.21.0: contacts + address books (also reading them; never in the legacy "write" or an agent's default)
#   account            the token user's own settings (notifications, app passwords) -- never for agents
#   admin-read         admin data (admins only) -- never for agents
#   agent              (implicit) an agent's own channel: status, events, jobs, chat, usage
# An admin caps what tokens may get at all (Settings > Agents > Set up: one limit for agents, one for personal tokens);
# a stored scope outside the cap simply does not count. Agents never get account / admin-read. New personal tokens
# start with read, new agents with read + tasks:write + comments. Tokens from before 2.15 keep "write" (= everything
# but admin-read) and their old read tokens got attachments:read once, so nothing changes for them.
# Dangerous changes by an AGENT wait for a person (need_approval): deleting a list / a field, emptying the trash, a
# batch of 10+ tasks, moving an own list into another folder, renaming / removing folders, sharing (people, groups).
# The agent gets 202 + a waiting job; Approve (the agent's owner, the list owner, an admin) replays the stored request
# as the agent with its rights at that moment (approval_run), Reject stops it; the agent gets a "job" event either way.
SCOPE_LABELS = {"read": N_("Read"), "tasks:write": N_("Tasks"), "comments": N_("Comments"), "structure": N_("Structure"),
                "delete": N_("Delete & trash"), "attachments:read": N_("Read files"), "attachments:write": N_("Upload files"),
                "time": N_("Time tracking"), "export": N_("Export"), "calendar": N_("Calendar"), "contacts": N_("Contacts"), "private": N_("Health & journal"),
                "account": N_("Account settings"), "admin-read": N_("Admin read"),
                "write": N_("Everything (old token)")}
SCOPE_HELP = {"read": N_("Lists, tasks, comments, time entries, habits, search"),
              "tasks:write": N_("Create, change, complete and move tasks; dependencies, habits"),
              "comments": N_("Write, edit and delete comments, reactions, mark News read"),
              "structure": N_("Lists, sections, custom fields, list tags, templates, filters, folders, project pages"),
              "delete": N_("Move to the trash, restore, empty the trash; delete sections, lists, fields, templates, habits, filters"),
              "attachments:read": N_("Download files"), "attachments:write": N_("Upload and remove files"),
              "time": N_("Timer and time entries"), "export": N_("Download all data"),
              "calendar": N_("Read and change events and calendars"),
              "contacts": N_("Read and change contacts and address books (personal data of other people)"),
              "private": N_("Health lists and the journal (sensitive personal data; never for agents)"),
              "account": N_("Notification settings and app passwords (an app password gives calendar apps full access to your tasks)"), "admin-read": N_("Users and server status (admins only)")}
ROLE_WORD = {"admin": N_("Admin"), "edit": N_("Member"), "participant": N_("Participant"), "view": N_("Viewer")}
BATCH_TITLE = {"update": N_("Change {0} tasks at once"), "complete": N_("Complete {0} tasks at once"), "reopen": N_("Reopen {0} tasks at once"),
               "wont_do": N_("Mark {0} tasks as won’t do"), "delete": N_("Move {0} tasks to the trash"),
               "restore": N_("Restore {0} tasks from the trash")}
APPROVAL_BATCH_MIN = 10   # an agent's batches with this many tasks or more ...
APPROVAL_BATCH_WINDOW = 600  # ... within this many seconds (counted together) wait for approval
_BATCH_SEEN, _BATCH_LOCK = {}, threading.Lock()
APPROVAL_PENDING_MAX = 20  # waiting approvals per agent
APPROVAL_BODY_MAX = 200_000
_SCOPE_MAP = {}
_REPLAY_KEY = secrets.token_bytes(32)   # per process: a replay header only works inside this server


class ApprovalPending(Exception):
    def __init__(self, job):
        super().__init__("approval")
        self.job = job


@app.errorhandler(ApprovalPending)
def approval_pending(e):
    r = jsonify(approval_required=True, job=e.job,
                message=tr("A person has to approve this first: it waits as job #{0}. You get a job event with the result.", e.job["id"]))
    r.status_code = 202
    return r


def scopes_clean(v, u, agent=False):
    """A scope list from a client -> the sorted stored list (BadInput / Denied). "write" is still accepted (scripts)."""
    if not isinstance(v, list) or any(not isinstance(s, str) or s not in API_SCOPES for s in v) or len(v) > 30:
        raise BadInput(tr("Invalid value: {0}", "scopes"))
    s = set(v) | {"read"}
    if agent and s & set(SCOPES_AGENT_NEVER):
        raise BadInput(tr("Agents cannot get the permission “{0}”", tr(SCOPE_LABELS[sorted(s & set(SCOPES_AGENT_NEVER))[0]])))
    if agent and "write" in s:  # an agent's "write" = every scope an agent can have
        s = (s - {"write"}) | (set(SCOPES_WRITE) - set(SCOPES_AGENT_NEVER))
    if "admin-read" in s and not u["is_admin"]:
        raise Denied(403, tr("Only admins can create tokens with admin access"))
    return sorted(s)


def ips_clean(v):
    """Allowed client addresses of a token: a list (or comma / space separated text) of IPs / networks; '' = any."""
    if v in (None, "", []):
        return ""
    items = v if isinstance(v, list) else re.split(r"[\s,]+", str(v))
    out = []
    for x in items:
        x = str(x).strip()
        if not x:
            continue
        try:
            out.append(str(ipaddress.ip_network(x, strict=False)))
        except ValueError:
            raise BadInput(tr("Invalid address or network: {0}", x[:60])) from None
    if len(out) > 20:
        raise BadInput(tr("At most {0} addresses", 20))
    return ",".join(dict.fromkeys(out))


def token_ip_ok(row, ip):
    nets = [x for x in (row["allowed_ips"] or "").split(",") if x] if "allowed_ips" in row.keys() else []
    if not nets:
        return True
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in ipaddress.ip_network(n, strict=False) for n in nets)


def scope_cap(c, kind):
    """The admin's limit for 'agents' or 'tokens' (personal tokens): the scopes they may have at all (default: all)."""
    v = gsetting(c, "scope_cap_" + kind)
    allowed = [s for s in SCOPES if kind != "agents" or s not in SCOPES_AGENT_NEVER]
    if not v:
        return allowed
    have = set(v.split(","))
    return [s for s in allowed if s in have or s == "read"]


def scopes_effective(c, row, u):
    """What a token may do now: its stored scopes (legacy "write" expanded) within the admin's limit; agents never
    account / admin-read; admin-read only while the user is an admin."""
    s = api_scopes(row["scopes"])
    if "write" in s:
        s = (s - {"write"}) | set(SCOPES_WRITE)
    agent = is_agent(u)
    s &= set(scope_cap(c, "agents" if agent else "tokens"))
    if agent:
        s -= set(SCOPES_AGENT_NEVER)
    if "admin-read" in s and not u["is_admin"]:
        s.discard("admin-read")
    return s | {"read"}


def scopes_offer(c, u, agent=False):
    """The scopes a person can pick for a token / an agent: [{scope, label, help, allowed}] (allowed = within the cap)."""
    cap = set(scope_cap(c, "agents" if agent else "tokens"))
    out = []
    for s in SCOPES:
        if (agent and s in SCOPES_AGENT_NEVER) or (s == "admin-read" and not u["is_admin"]):
            continue
        out.append({"scope": s, "label": tr(SCOPE_LABELS[s]), "help": tr(SCOPE_HELP[s]), "allowed": s in cap})
    return out


def v1_scope_need(method, rule):
    """The scope one API route needs, from the OpenAPI document (x-kalmido-scope); None = undocumented (refused)."""
    if not _SCOPE_MAP:
        for p, ms in openapi_spec()["paths"].items():
            for m, op in ms.items():
                _SCOPE_MAP[(m.upper(), re.sub(r"\{[^}]+\}", "{}", p))] = op.get("x-kalmido-scope", "read")
    if rule is None:  # no route matched (404 / 405 follow from the routing, no view runs)
        return "read"
    path = re.sub(r"<[^>]+>", "{}", rule.rule[len(API_PREFIX) - 1:])
    m = "GET" if method in ("HEAD", "OPTIONS") else method
    return _SCOPE_MAP.get((m, path), "read" if m == "GET" and path == "/openapi.json" else None)


def need_scope(s):
    """A second scope a route needs because of its body (e.g. a batch that deletes). Token requests only."""
    if g.get("auth_via") == "token" and s not in (g.get("scopes") or set()):
        raise Denied(403, tr("This token lacks the permission “{0}”", tr(SCOPE_LABELS.get(s, s))))


# operations declared with the old scope "write": the fine scope by path (first match wins); the new routes of 2.15
# declare theirs directly.
SCOPE_RULES = (
    (r"^/agent(/|$)", "agent"),
    (r"^/agents/\{[^}]+\}/chat/", "comments"),
    (r"^/me/", "account"),
    (r"^/chat-attachments/", "comments"),
    (r"^/tasks/\{[^}]+\}/comments", "comments"),
    (r"^/comments/", "comments"),
    (r"^/time/", "time"),
    (r"^/imports/", "delete"),  # an import's undo deletes what it created
    (r"^/import/", "structure"),
    (r"^/lists/\{[^}]+\}/files", "attachments:write"),
    (r"^/lists/\{[^}]+\}/shift$", "tasks:write"),
    (r"^/lists", "structure"),
    (r"^/(habits|tasks|dayplan)", "tasks:write"),
)


def scope_refine(paths):
    for p, ms in paths.items():
        for m, op in ms.items():
            sc = op.get("x-kalmido-scope", "read")
            if sc == "write":
                if m == "delete" and re.fullmatch(r"/tasks/\{[^}]+\}", p):
                    sc = "delete"
                else:
                    sc = next((s for rx, s in SCOPE_RULES if re.search(rx, p)), "structure")
            elif sc == "read" and m == "get" and (p in ("/attachments/{id}", "/lists/{id}/files/{file_id}")):
                sc = "attachments:read"
            op["x-kalmido-scope"] = sc
            if sc not in ("read", "agent"):
                op.setdefault("description", "")
                op["description"] = (op["description"] + " " if op["description"] else "") + f"Scope: {sc}."


# ---- approvals
def approval_approver(c, aid, list_id=None):
    """Who approves an agent's dangerous request: a personal agent's owner, else the owner of the list it concerns
    (admins always can)."""
    a = agent_row(c, aid)
    if a and a["owner_id"]:
        return a["owner_id"]
    if list_id:
        r = c.execute("SELECT l.owner_id FROM lists l JOIN users u ON u.id=l.owner_id WHERE l.id=? AND COALESCE(u.kind,'user')!='agent' "
                      "AND u.disabled=0", (list_id,)).fetchone()
        return r[0] if r else None
    return None


def need_approval(c, title, args=(), list_id=None, task_id=None):
    """Called by a route BEFORE it changes anything (and after its own permission checks): for an agent's token the
    request is stored as a waiting job and answered 202 (ApprovalPending); people and approved replays pass."""
    if g.get("auth_via") != "token" or not is_agent(g.user) or g.get("approved_job"):
        return
    aid = me()
    raw = request.get_data(as_text=True) if request.is_json else ""
    if len(raw) > APPROVAL_BODY_MAX:
        raise BadInput(tr("The request is too large to wait for an approval"))
    spec = {"m": request.method, "p": request.path, "q": request.query_string.decode("latin-1")[:2000], "b": raw}
    key = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    waiting = c.execute("SELECT * FROM agent_jobs WHERE agent_id=? AND state='waiting' AND approval IS NOT NULL ORDER BY id DESC",
                        (aid,)).fetchall()
    for j in waiting:  # the same request again (an agent retrying): the same job, no pile of approvals
        if json.loads(j["approval"]).get("key") == key:
            raise ApprovalPending(job_dict(c, j))
    if len(waiting) >= APPROVAL_PENDING_MAX:
        raise Denied(409, tr("Too many requests are waiting for an approval"))
    approver = approval_approver(c, aid, list_id)
    lg = lang_of(usettings(c, approver)) if approver else None
    args = [tr(a[1], lg=lg) if isinstance(a, tuple) else a for a in args]  # ("tr", key): a word in the approver's language
    ts = iso(now_utc())
    jid = c.execute("""INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,approval,list_id)
                       VALUES(?,?,?,?,'waiting','',?,?,?,?)""",
                    (aid, task_id, approver, tr(title, *args, lg=lg)[:300], ts, ts, json.dumps({**spec, "key": key}), list_id)).lastrowid
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    job_notify(c, j, None)
    if approver and not task_id:  # job_notify only adds News for task jobs: the approver hears of it anyway
        s = collab_user(c, approver, None)
        if s:
            news_add(c, approver, "approval", list_id=list_id, data={"title": j["title"][:200]}, actor=aid, s=s)
    bump(c)
    c.commit()
    print("agent", aid, "approval needed: job", jid, request.method, request.path, flush=True)
    raise ApprovalPending(job_dict(c, j))


def approval_replay_token(c, header):
    """The X-Kalmido-Replay header of approval_run -> the agent's newest token row (once per approved job)."""
    jid, _, sig = str(header).partition(":")
    if not jid.isdigit() or not hmac.compare_digest(sig, hmac.new(_REPLAY_KEY, jid.encode(), "sha256").hexdigest()):
        return None
    j = c.execute("SELECT * FROM agent_jobs WHERE id=? AND state='running' AND action='approve' AND approval IS NOT NULL",
                  (int(jid),)).fetchone()
    if not j:
        return None
    ap = json.loads(j["approval"])
    if ap.get("ran") or ap.get("m") != request.method or ap.get("p") != request.path:
        return None
    c.execute("UPDATE agent_jobs SET approval=? WHERE id=?", (json.dumps({**ap, "ran": 1}), j["id"]))
    c.commit()
    g.approved_job = j["id"]
    return c.execute("SELECT * FROM api_tokens WHERE user_id=? ORDER BY id DESC LIMIT 1", (j["agent_id"],)).fetchone()


def approval_replay(jid, spec):
    """Runs the stored request through the API as the agent (own thread = own request context and connection)."""
    out = {}

    def run():
        try:
            sig = hmac.new(_REPLAY_KEY, str(jid).encode(), "sha256").hexdigest()
            r = app.test_client().open(spec["p"], method=spec["m"], query_string=spec.get("q") or None,
                                       data=(spec.get("b") or None),
                                       headers={"X-Kalmido-Replay": f"{jid}:{sig}", "Content-Type": "application/json"})
            out["status"], out["body"] = r.status_code, r.get_data(as_text=True)
        except Exception as e:  # noqa: BLE001  reported in the job, never breaks the approver's request
            out["status"], out["body"] = 500, f"{type(e).__name__}: {e}"
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(120)
    return out or {"status": 504, "body": "timeout"}


def approval_run(c, j):
    """Approve on an approval job: replays the request, the job ends done / failed with the answer in its log."""
    ts = iso(now_utc())
    if json.loads(j["approval"]).get("ran") or not c.execute(
            "UPDATE agent_jobs SET state='running', action='approve', action_by=?, action_at=?, updated_at=? WHERE id=? AND state='waiting'",
            (me(), ts, ts, j["id"])).rowcount:
        c.rollback()
        return err(tr("This job has already ended"), 409)
    c.commit()
    res = approval_replay(j["id"], json.loads(j["approval"]))
    ok = 200 <= res["status"] < 300
    try:
        body_j = json.loads(res["body"]) if res["body"] else None
    except ValueError:
        body_j = None
    msg = (body_j or {}).get("error", {}).get("message") if isinstance(body_j, dict) and isinstance(body_j.get("error"), dict) else None
    line = tr("Approved by {0}", user_names(c, [me()]).get(me(), "")) + (" · " + tr("done") if ok else f" · HTTP {res['status']}: {msg or res['body'][:300]}")
    c.execute("UPDATE agent_jobs SET state=?, log=?, updated_at=? WHERE id=?", ("done" if ok else "failed", line[-JOB_LOG_MAX:], iso(now_utc()), j["id"]))
    j2 = c.execute("SELECT * FROM agent_jobs WHERE id=?", (j["id"],)).fetchone()
    agent_emit(c, j["agent_id"], "job", {"job": job_dict(c, j2), "action": "approve",
                                        "user": {"id": me(), "name": user_names(c, [me()]).get(me(), "")},
                                        "result": {"status": res["status"], "body": body_j if body_j is not None else res["body"][:2000]}})
    bump(c)
    c.commit()
    print("approval job", j["id"], "of agent", j["agent_id"], "approved by", g.user["username"], "->", res["status"], flush=True)
    return jsonify(job_dict(c, j2))


def agent_scopes_set(c, aid, b):
    """{scopes?, allowed_ips?} of an agent (admin: team agents, owner: personal ones) -> stored on the agent and on its
    tokens (a new token gets them too)."""
    if "scopes" in b:
        sc = ",".join(scopes_clean(b["scopes"], {"is_admin": 0}, agent=True))
        c.execute("UPDATE agents SET scopes=? WHERE user_id=?", (sc, aid))
        c.execute("UPDATE api_tokens SET scopes=? WHERE user_id=?", (sc, aid))
        print("agent", aid, "scopes", sc, "by", g.user["username"], flush=True)
    if "allowed_ips" in b:
        ips = ips_clean(b["allowed_ips"])
        c.execute("UPDATE agents SET allowed_ips=? WHERE user_id=?", (ips, aid))
        c.execute("UPDATE api_tokens SET allowed_ips=? WHERE user_id=?", (ips, aid))


def agent_scope_dict(c, a):
    u = c.execute("SELECT * FROM users WHERE id=?", (a["user_id"],)).fetchone()
    stored = a["scopes"] or ",".join(SCOPES_AGENT_DEFAULT)
    return {"scopes": sorted(api_scopes(stored)), "effective_scopes": [s for s in SCOPES if s in scopes_effective(c, {"scopes": stored}, u)] if u else [],
            "allowed_ips": [x for x in (a["allowed_ips"] or "").split(",") if x]}


# ---- the routes that were missing (#479 part 2). They reuse the web client's endpoints (v1_call), so the rules are the same.
def _v1_body(allowed):
    b = v1_json()
    reject_unknown(b, allowed)
    return b


def v1_section(r):
    return {"id": r["id"], "list_id": r["list_id"], "name": r["name"], "sort": r["sort"]}


@app.get("/api/v1/lists/<int:lid>/sections")
@v1_view
def v1_sections(lid):
    v1_args(())
    c = db()
    need_list(c, lid, write=False)
    return jsonify(data=[v1_section(r) for r in c.execute("SELECT * FROM sections WHERE list_id=? ORDER BY sort, id", (lid,))], next_cursor=None)


@app.post("/api/v1/lists/<int:lid>/sections")
@v1_view
def v1_section_create(lid):
    """{name, before_id?}: a new section at the end (or in front of section before_id)."""
    v1_args(())
    b = _v1_body(("name", "before_id"))
    c = db()
    need_list(c, lid)
    fwd = {"list_id": lid, "name": b.get("name")}
    if b.get("before_id") is not None:
        bid = as_int(b["before_id"], "before_id", 1)
        cur = c.execute("SELECT id, sort FROM sections WHERE list_id=? ORDER BY sort, id", (lid,)).fetchall()
        i = next((k for k, r in enumerate(cur) if r["id"] == bid), None)
        if i is None:
            raise BadInput(tr("Invalid value: {0}", "before_id"))
        fwd["sort"] = (cur[i - 1]["sort"] + cur[i]["sort"]) / 2 if i else cur[i]["sort"] - 1
    j = v1_call(section_create, body=fwd)
    return jsonify(v1_section(c.execute("SELECT * FROM sections WHERE id=?", (j["id"],)).fetchone())), 201


@app.patch("/api/v1/sections/<int:sid>")
@v1_view
def v1_section_update(sid):
    v1_args(())
    b = _v1_body(("name",))
    if "name" not in b:
        raise BadInput(tr("Nothing to change"))
    v1_call(section_update, sid, body={"name": b["name"]})
    return jsonify(v1_section(db().execute("SELECT * FROM sections WHERE id=?", (sid,)).fetchone()))


@app.put("/api/v1/lists/<int:lid>/sections/order")
@v1_view
def v1_sections_order(lid):
    v1_args(())
    b = _v1_body(("ids",))
    v1_call(sections_order, lid, body={"ids": b.get("ids")})
    c = db()
    return jsonify(data=[v1_section(r) for r in c.execute("SELECT * FROM sections WHERE list_id=? ORDER BY sort, id", (lid,))], next_cursor=None)


@app.delete("/api/v1/sections/<int:sid>")
@v1_view
def v1_section_delete(sid):
    """The section goes, its tasks stay in the list (without a section)."""
    v1_args(())
    j = v1_call(section_delete, sid, body={})
    return jsonify(ok=True, tasks=j.get("tasks") or [])


def _sort_at(c, tid, lid, sid, parent, before, after, position):
    """The sort value that puts task tid before / after a sibling or at the top / bottom of its place."""
    if parent:
        sib = c.execute("SELECT id, sort FROM tasks WHERE parent_id=? AND deleted_at IS NULL AND id!=? ORDER BY sort, id", (parent, tid)).fetchall()
    else:
        sib = c.execute("""SELECT id, sort FROM tasks WHERE list_id=? AND parent_id IS NULL AND deleted_at IS NULL AND status=0 AND id!=?
                           AND section_id IS ? ORDER BY sort, id""", (lid, tid, sid)).fetchall()
    ref = before or after
    if ref:
        i = next((k for k, r in enumerate(sib) if r["id"] == ref), None)
        if i is None:
            raise BadInput(tr("Invalid value: {0}", "before_id" if before else "after_id"))
        if before:
            return (sib[i - 1]["sort"] + sib[i]["sort"]) / 2 if i else sib[i]["sort"] - 1
        return (sib[i]["sort"] + sib[i + 1]["sort"]) / 2 if i + 1 < len(sib) else sib[i]["sort"] + 1
    if position == "top":
        return (sib[0]["sort"] - 1) if sib else 0
    return (sib[-1]["sort"] + 1) if sib else 0


@app.post("/api/v1/tasks/<int:tid>/move")
@v1_view
def v1_task_move(tid):
    """{list_id?, section_id? (null = none), parent_id? (null = top level), before_id? | after_id? | position? (top |
    bottom)}: move a task (with its subtasks) to another list / section / parent and to a place among its siblings."""
    v1_args(())
    b = _v1_body(("list_id", "section_id", "parent_id", "before_id", "after_id", "position"))
    if sum(1 for k in ("before_id", "after_id", "position") if b.get(k) is not None) > 1:
        raise BadInput(tr("Give only one of before_id, after_id, position"))
    if b.get("position") not in (None, "top", "bottom"):
        raise BadInput(tr("Invalid value: {0}", "position"))
    c = db()
    _v1_live(c, tid)
    ch = {k: b[k] for k in ("list_id", "section_id", "parent_id") if k in b}
    cur = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()
    if b.get("list_id") and b["list_id"] != cur["list_id"] and "section_id" not in b:
        ch["section_id"] = None  # another list: no section unless one of that list is given
    if b.get("list_id") and b["list_id"] != cur["list_id"]:
        from ..agents.safety import move_gate
        move_gate(c, [(tid, b["list_id"])])  # 2.30.0 (#919): an agent moving it to other people waits for approval
    if ch:
        v1_call(task_update, tid, body=ch)
    t = c.execute("SELECT list_id, section_id, parent_id FROM tasks WHERE id=?", (tid,)).fetchone()
    if "section_id" in b and b["section_id"] and t["section_id"] != b["section_id"]:
        raise BadInput(tr("Invalid value: {0}", "section_id"))
    ref = {k: as_int(b[k], k, 1) for k in ("before_id", "after_id") if b.get(k) is not None}
    if ref or b.get("position") or ch:
        srt = _sort_at(c, tid, t["list_id"], t["section_id"], t["parent_id"], ref.get("before_id"), ref.get("after_id"),
                       b.get("position") or "bottom")
        c.execute("UPDATE tasks SET sort=?, updated_at=? WHERE id=?", (srt, iso(now_utc()), tid))
        bump(c)
        c.commit()
    return jsonify(v1_one(c, tid))


BATCH_ACTIONS = ("update", "complete", "reopen", "wont_do", "delete", "restore")


@app.post("/api/v1/tasks/batch")
@v1_view
def v1_task_batch():
    """{ids (1-500), action: update | complete | reopen | wont_do | delete | restore, changes? (update: task fields)} --
    one transaction; tasks you may not change are skipped and reported in errors."""
    v1_args(())
    b = _v1_body(("ids", "action", "changes"))
    ids = b.get("ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or any(isinstance(i, bool) or not isinstance(i, int) for i in ids):
        raise BadInput(tr("Invalid value: {0}", "ids"))
    act = b.get("action")
    if act not in BATCH_ACTIONS:
        raise BadInput(tr("Invalid value: {0}", "action"))
    if act in ("delete", "restore"):
        need_scope("delete")
    data = {}
    if act == "update":
        ch = b.get("changes")
        if not isinstance(ch, dict) or not ch:
            raise BadInput(tr("Nothing to change"))
        data = v1_task_in(ch, tuple(k for k in V1_TASK_IN if k != "parent_id"))
    elif b.get("changes"):
        raise UnknownFields(["changes"])
    c = db()
    ids = list(dict.fromkeys(ids))
    vis = [i for i in ids if task_visible(c, i, me())]
    recent = 0
    if is_agent(g.user) and not g.get("approved_job"):  # an agent's batches count together for APPROVAL_BATCH_WINDOW s
        now = time.time()
        with _BATCH_LOCK:
            seen = [x for x in _BATCH_SEEN.get(me(), []) if now - x[0] < APPROVAL_BATCH_WINDOW]
            _BATCH_SEEN[me()] = seen
            recent = sum(x[1] for x in seen)
    if vis and act == "update" and data.get("list_id"):  # 2.30.0 (#919): moving tasks to other people waits for approval
        from ..agents.safety import move_gate
        move_gate(c, [(i, data["list_id"]) for i in vis])
    if vis and len(vis) + recent >= APPROVAL_BATCH_MIN:
        lids = [r[0] for r in c.execute(f"SELECT list_id FROM tasks WHERE id IN ({','.join('?' * len(vis))})", vis)]
        top = max(set(lids), key=lids.count) if lids else None
        need_approval(c, BATCH_TITLE[act], (len(vis),), list_id=top)
    if is_agent(g.user) and not g.get("approved_job") and vis:
        with _BATCH_LOCK:
            _BATCH_SEEN.setdefault(me(), []).append((time.time(), len(vis)))
    if act == "wont_do":
        act, data = "complete", {"status": -1}
    elif act == "complete":
        data = {"status": 2}
    j = v1_call(task_batch, body={"ids": vis, "action": "patch" if act == "update" else act, "data": data})
    hidden = len(ids) - len(vis)
    return jsonify(count=j.get("count", 0), errors=j.get("errors", []) + ([trn("{0} task not found", "{0} tasks not found", hidden)] if hidden else []),
                   conflicts=j.get("conflicts", []))


@app.post("/api/v1/tasks/<int:tid>/skip")
@v1_view
def v1_task_skip(tid):
    """Skip this occurrence of a repeating task: it moves to its next date without a completed copy."""
    v1_args(())
    c = db()
    _v1_live(c, tid)
    j = v1_call(task_skip, tid, body={})
    return jsonify({**v1_one(c, tid), "next_due": j.get("next_due")})


@app.get("/api/v1/trash")
@v1_view
def v1_trash():
    """Tasks in the trash of the lists you see (newest first)."""
    a = v1_args(("list_id", "limit", "cursor"))
    c, uid = db(), me()
    q, args = f"deleted_at IS NOT NULL AND list_id IN {vis_sql()} AND {tvis(c, uid)}", [uid, uid]
    if a.get("list_id"):
        q += " AND list_id=?"
        args.append(as_int(a["list_id"], "list_id", 1))
    rows = load_tasks(c, q + " ORDER BY deleted_at DESC, id DESC LIMIT 5000", tuple(args))
    return v1_page([{**v1_task(d), "deleted_at": d.get("deleted_at")} for d in rows], cursor_dec("o", a.get("cursor")), v1_limit(a))


@app.post("/api/v1/tasks/<int:tid>/restore")
@v1_view
def v1_task_restore(tid):
    v1_args(())
    c = db()
    need_task(c, tid)
    if not c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()[0]:
        raise Denied(409, tr("The task is not in the trash"))
    v1_call(task_restore, tid, body={})
    return jsonify(v1_one(c, tid))


@app.delete("/api/v1/trash")
@v1_view
def v1_trash_empty():
    """Deletes the trash for good: the lists you own (admins: also shared lists they may edit)."""
    v1_args(())
    c = db()
    n = c.execute(f"SELECT COUNT(*) FROM tasks WHERE deleted_at IS NOT NULL AND list_id IN {wr_sql()}", (me(), me())).fetchone()[0]
    need_approval(c, N_("Empty the trash for good ({0} tasks)"), (n,))
    j = v1_call(trash_empty, body={})
    return jsonify(deleted=j.get("deleted", 0), kept=j.get("kept", 0))


# dependencies
def v1_dep_rows(rows):
    return [{"id": r.get("id"), "title": r.get("title"), "status": STATUS_NAMES.get(r.get("status"), "open"), "list_id": r.get("list_id"),
             "hidden": bool(r.get("hidden"))} for r in rows]


@app.get("/api/v1/tasks/<int:tid>/dependencies")
@v1_view
def v1_deps(tid):
    """blocked_by = what the task waits on, blocking = what waits on it (hidden = a task you cannot see)."""
    v1_args(())
    _v1_live(db(), tid, write=False, full=True)
    j = v1_call(deps_get, tid)
    return jsonify(blocked_by=v1_dep_rows(j["blocked_by"]), blocking=v1_dep_rows(j["blocking"]))


@app.post("/api/v1/tasks/<int:tid>/dependencies")
@v1_view
def v1_dep_add(tid):
    """{blocked_by: task id}: this task waits on that one (project lists, no cycles)."""
    v1_args(())
    b = _v1_body(("blocked_by",))
    c = db()
    _v1_live(c, tid)
    v1_call(dep_add, body={"task_id": tid, "blocker_id": as_int(b.get("blocked_by"), "blocked_by", 1)})
    j = v1_call(deps_get, tid)
    return jsonify(blocked_by=v1_dep_rows(j["blocked_by"]), blocking=v1_dep_rows(j["blocking"])), 201


@app.delete("/api/v1/tasks/<int:tid>/dependencies/<blocker_id>")
@v1_view
def v1_dep_remove(tid, blocker_id):
    v1_args(())
    c = db()
    _v1_live(c, tid)
    v1_call(dep_remove, tid, as_int(blocker_id, "blocker_id", 1), body={})
    j = v1_call(deps_get, tid)
    return jsonify(blocked_by=v1_dep_rows(j["blocked_by"]), blocking=v1_dep_rows(j["blocking"]))


# custom fields (definitions; the values are the task's `fields`)
@app.get("/api/v1/lists/<int:lid>/fields")
@v1_view
def v1_fields(lid):
    v1_args(())
    c = db()
    need_list(c, lid, write=False)
    return jsonify(data=[field_dict(r) for r in c.execute("SELECT * FROM list_fields WHERE list_id=? ORDER BY sort, id", (lid,))],
                   next_cursor=None)


@app.post("/api/v1/lists/<int:lid>/fields")
@v1_view
def v1_field_create(lid):
    """{name, type: text | number | date | select | person | url | checkbox ..., options?, pinned?} (project lists, owner)."""
    v1_args(())
    b = _v1_body(("name", "type", "options", "pinned"))
    return jsonify(v1_call(field_create, lid, body=b)), 201


@app.patch("/api/v1/fields/<int:fid>")
@v1_view
def v1_field_update(fid):
    v1_args(())
    b = _v1_body(("name", "options", "pinned", "sort"))
    return jsonify(v1_call(field_update, fid, body=b))


@app.delete("/api/v1/fields/<int:fid>")
@v1_view
def v1_field_delete(fid):
    """The field goes with every value of it."""
    v1_args(())
    c = db()
    r = need_field(c, fid)
    need_approval(c, N_("Delete the custom field “{0}” and its values"), (r["name"],), list_id=r["list_id"])
    j = v1_call(field_delete, fid, body={})
    return jsonify(ok=True, values=j.get("values", 0))


# templates
@app.get("/api/v1/templates")
@v1_view
def v1_templates():
    v1_args(())
    return jsonify(data=v1_call(templates_list)["templates"], next_cursor=None)


@app.post("/api/v1/templates")
@v1_view
def v1_template_create():
    """{task_id} (the task with its subtasks) | {list_id, relative?} (the list's sections + open tasks) | {kind, data};
    name optional."""
    v1_args(())
    b = _v1_body(("task_id", "list_id", "relative", "kind", "data", "name"))
    return jsonify(v1_call(template_create, body=b)), 201


@app.patch("/api/v1/templates/<int:tid>")
@v1_view
def v1_template_update(tid):
    v1_args(())
    b = _v1_body(("name", "data"))
    return jsonify(v1_call(template_update, tid, body=b))


@app.delete("/api/v1/templates/<int:tid>")
@v1_view
def v1_template_delete(tid):
    v1_args(())
    v1_call(template_delete, tid, body={})
    return Response(status=204)


@app.post("/api/v1/templates/<int:tid>/apply")
@v1_view
def v1_template_apply(tid):
    """Task template: {list_id?, section_id?} (default the inbox). List template: {name?, folder?, start?, end?} -> a new list."""
    v1_args(())
    b = _v1_body(("list_id", "section_id", "name", "folder", "start", "end"))
    return jsonify(v1_call(template_apply, tid, body=b)), 201


# attachments + comments
@app.post("/api/v1/tasks/<int:tid>/attachments")
@v1_view
def v1_attachment_upload(tid):
    """multipart/form-data, field `file` (repeatable): files on the task (the server's upload limit per file)."""
    v1_args(())
    c = db()
    _v1_live(c, tid)
    if request.is_json or not request.files:
        raise BadInput(tr("File missing"))
    unknown = sorted(k for k in [*request.form, *request.files] if k != "file")
    if unknown:
        raise UnknownFields(unknown)
    before = {r[0] for r in c.execute("SELECT id FROM attachments WHERE task_id=?", (tid,))}
    v1_call(attachment_upload, tid)
    new = [dict(r) for r in c.execute("SELECT id, name, mime, size FROM attachments WHERE task_id=? AND comment_id IS NULL ORDER BY id", (tid,))
           if r["id"] not in before]
    return jsonify(data=new, next_cursor=None), 201


@app.post("/api/v1/tasks/<int:tid>/attachments/text")
@v1_view
def v1_attachment_text(tid):
    """2.30.0 (#380): {name, content}: a text file (Markdown, plain text, HTML / CSS / JS, data, code; UTF-8, at most 1 MB) on the
    task. Not a known text ending (e.g. .sh, .exe) -> ".txt" is appended; the name of an existing file of the task -> a new
    version "name (v2).ext" next to it (the old one stays). Same rights as an upload (may change the task)."""
    v1_args(())
    c = db()
    _v1_live(c, tid)
    b = _v1_body(("name", "content"))
    if not isinstance(b.get("name"), str) or not isinstance(b.get("content"), str):
        raise BadInput(tr("Expected {0}", '{"name": "...", "content": "..."}'))
    try:
        a = text_attachment_create(c, tid, b["name"], b["content"])
    except ValueError as e:
        raise BadInput(str(e)) from None
    return jsonify({**a, "url": f"/api/v1/attachments/{a['id']}"}), 201


@app.delete("/api/v1/attachments/<int:aid>")
@v1_view
def v1_attachment_delete(aid):
    v1_args(())
    v1_call(attachment_delete, aid, body={})
    return Response(status=204)


@app.patch("/api/v1/comments/<int:cid>")
@v1_view
def v1_comment_update(cid):
    """{body}: only the author edits a comment."""
    v1_args(())
    b = _v1_body(("body",))
    if not isinstance(b.get("body"), str):
        raise BadInput(tr("Expected {0}", '{"body": "..."}'))
    c = db()
    j = v1_call(comment_update, cid, body={"body": b["body"]})
    tid = c.execute("SELECT task_id FROM comments WHERE id=?", (cid,)).fetchone()[0]
    return jsonify(v1_comment(c, {**j, "task_id": tid}, user_names(c, [j.get("user_id") or me()])))


@app.delete("/api/v1/comments/<int:cid>")
@v1_view
def v1_comment_delete(cid):
    """The author, or the list's owner / admins (moderation)."""
    v1_args(())
    v1_call(comment_delete, cid, body={})
    return Response(status=204)


# folders (per person: each member files a shared list into their own folders)
@app.get("/api/v1/folders")
@v1_view
def v1_folders():
    v1_args(())
    c = db()
    paths = _folder_paths(c, me())
    cnt = {}
    for d in visible_lists(c, me()):
        if d["folder"]:
            cnt[d["folder"]] = cnt.get(d["folder"], 0) + 1
    return jsonify(data=[{"path": p, "lists": cnt.get(p, 0)} for p in paths], next_cursor=None)


@app.post("/api/v1/folders/rename")
@v1_view
def v1_folder_rename():
    """{old, new}: rename or move a folder ("A" -> "B", "A/x" -> "B/x"); its lists and subfolders go along."""
    v1_args(())
    b = _v1_body(("old", "new"))
    c = db()
    need_approval(c, N_("Rename the folder “{0}” to “{1}” (its lists move along)"), (str(b.get("old") or "")[:100], str(b.get("new") or "")[:100]))
    v1_call(folder_rename, body=b)
    return jsonify(data=[{"path": p} for p in _folder_paths(c, me())], next_cursor=None)


@app.post("/api/v1/folders/delete")
@v1_view
def v1_folder_delete():
    """{name}: removes the folder only; its lists and subfolders move up one level."""
    v1_args(())
    b = _v1_body(("name",))
    c = db()
    need_approval(c, N_("Remove the folder “{0}” (its lists move up a level)"), (str(b.get("name") or "")[:100],))
    v1_call(folder_delete, body=b)
    return jsonify(data=[{"path": p} for p in _folder_paths(c, me())], next_cursor=None)


# lists: delete + people
@app.delete("/api/v1/lists/<int:lid>")
@v1_view
def v1_list_delete(lid):
    """Deletes an ARCHIVED list for good (owner; archive it first with PATCH archived=true). Its tasks go to the trash."""
    v1_args(())
    c = db()
    need_list(c, lid, owner=True)
    r = c.execute("SELECT name, is_inbox, archived FROM lists WHERE id=?", (lid,)).fetchone()
    if not r["is_inbox"] and r["archived"]:
        need_approval(c, N_("Delete the list “{0}” for good"), (r["name"],), list_id=lid)
    v1_call(list_delete, lid, body={})
    return Response(status=204)


def v1_members(c, lid):
    lst = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    rows = c.execute("SELECT user_id, role, own_role, grole FROM list_members WHERE list_id=? ORDER BY user_id", (lid,)).fetchall()
    ids = [lst["owner_id"], *[r["user_id"] for r in rows]]
    names = user_names(c, ids)
    kinds = {r[0]: r[1] for r in c.execute(f"SELECT id, COALESCE(kind,'user') FROM users WHERE id IN ({','.join('?' * len(ids))})", ids)}
    out = [{"user_id": lst["owner_id"], "name": names.get(lst["owner_id"], ""), "role": "owner", "agent": kinds.get(lst["owner_id"]) == "agent",
            "via_group": False}]
    out += [{"user_id": r["user_id"], "name": names.get(r["user_id"], ""), "role": r["role"], "agent": kinds.get(r["user_id"]) == "agent",
             "via_group": bool(r["grole"]) and not r["own_role"]} for r in rows]
    return out


@app.get("/api/v1/lists/<int:lid>/members")
@v1_view
def v1_list_members(lid):
    v1_args(())
    c = db()
    need_list(c, lid, write=False)
    return jsonify(data=v1_members(c, lid), next_cursor=None)


@app.put("/api/v1/lists/<int:lid>/members/<user_id>")
@v1_view
def v1_member_set(lid, user_id):
    """{role: admin | edit | participant | view}: share the list with a person (owner / list admins)."""
    v1_args(())
    b = _v1_body(("role", "bridge_ok"))  # 2.30.0 (#919): bridge_ok counts only from a person's token
    uid = as_int(user_id, "user_id", 1)
    c = db()
    need_list(c, lid, write=False, manage=True)
    role = str(b.get("role") or "edit")
    if role not in ROLES:
        raise BadInput(tr("Role must be admin, edit, participant or view"))
    u = c.execute("SELECT display_name, username, kind FROM users WHERE id=? AND disabled=0", (uid,)).fetchone()
    if not u or uid == me() or personal_agent_foreign(c, uid, me()) or (role == "admin" and u["kind"] == "agent") \
            or c.execute("SELECT is_inbox FROM lists WHERE id=?", (lid,)).fetchone()[0]:
        raise Denied(404)  # checked before an approval, so a job never names or waits for someone it cannot share with
    need_approval(c, N_("Share the list “{0}” with {1} ({2})"), (c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0],
                                                                  u["display_name"] or u["username"], ("tr", ROLE_WORD[role])), list_id=lid)
    v1_call(member_set, lid, body={"user_id": uid, "role": b.get("role", "edit"), "bridge_ok": b.get("bridge_ok") is True})
    return jsonify(data=v1_members(c, lid), next_cursor=None)


@app.delete("/api/v1/lists/<int:lid>/members/<user_id>")
@v1_view
def v1_member_remove(lid, user_id):
    """Stop sharing with a person (owner / list admins), or leave the list (your own user id)."""
    v1_args(())
    uid = as_int(user_id, "user_id", 1)
    c = db()
    need_list(c, lid, write=False)
    if uid != me():
        need_list(c, lid, write=False, manage=True)
        need_approval(c, N_("Stop sharing the list “{0}” with {1}"), (c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0],
                                                                     user_names(c, [uid]).get(uid, "?")), list_id=lid)
    v1_call(member_remove, lid, uid, body={})
    return Response(status=204)


# saved filters
def v1_filter(r):
    try:
        rules = json.loads(r["rules"] or "{}")
    except ValueError:
        rules = {}
    return {"id": r["id"], "name": r["name"], "rules": rules, "sort": r["sort"]}


@app.get("/api/v1/filters")
@v1_view
def v1_filters():
    v1_args(())
    return jsonify(data=[v1_filter(r) for r in db().execute("SELECT * FROM filters WHERE user_id=? ORDER BY sort, id", (me(),))], next_cursor=None)


@app.post("/api/v1/filters")
@v1_view
def v1_filter_create():
    """{name, rules}: rules as the app stores them (lists, tags, priority, due, assignee ...; see docs/API.md)."""
    v1_args(())
    b = _v1_body(("name", "rules"))
    if "rules" in b and not isinstance(b["rules"], dict):
        raise BadInput(tr("Invalid value: {0}", "rules"))
    j = v1_call(filter_create, body=b)
    return jsonify(v1_filter(db().execute("SELECT * FROM filters WHERE id=?", (j["id"],)).fetchone())), 201


@app.patch("/api/v1/filters/<int:fid>")
@v1_view
def v1_filter_update(fid):
    v1_args(())
    b = _v1_body(("name", "rules", "sort"))
    if "rules" in b and not isinstance(b["rules"], dict):
        raise BadInput(tr("Invalid value: {0}", "rules"))
    if "sort" in b and (isinstance(b["sort"], bool) or not isinstance(b["sort"], (int, float))):
        raise BadInput(tr("Invalid value: {0}", "sort"))
    v1_call(filter_update, fid, body=b)
    return jsonify(v1_filter(db().execute("SELECT * FROM filters WHERE id=?", (fid,)).fetchone()))


@app.delete("/api/v1/filters/<int:fid>")
@v1_view
def v1_filter_delete(fid):
    v1_args(())
    v1_call(filter_delete, fid, body={})
    return Response(status=204)


# News
@app.get("/api/v1/news")
@v1_view
def v1_news():
    """Your News (mentions, assignments, comments, shares, status, approvals ...), newest first; ?filter=mentions | me."""
    a = v1_args(("filter",))
    if a.get("filter") not in (None, "mentions", "me"):
        raise BadInput(tr("Invalid value: {0}", "filter"))
    j = v1_call(news_list)
    tl = token_lists()  # 2.30.0 (#919): a token limited to selected lists sees only their News (and News without a list)
    items = [x for x in j["items"] if tl is None or not x.get("list_id") or x["list_id"] in tl]
    return jsonify(data=items, unread=j["unread"] if tl is None else sum(1 for x in items if not x.get("read")), next_cursor=None)


@app.post("/api/v1/news/read")
@v1_view
def v1_news_read():
    """{ids: [...]} or {all: true}: mark News read."""
    v1_args(())
    b = _v1_body(("ids", "all"))
    if not b.get("all") and not isinstance(b.get("ids"), list):
        raise BadInput(tr("Expected {0}", '{"ids": [...]} / {"all": true}'))
    j = v1_call(news_read, body=b)
    return jsonify(unread=j.get("unread", 0))


# habits
@app.post("/api/v1/habits")
@v1_view
def v1_habit_create():
    """{name, color?, goal?, days? ("1234567" = Mon-Sun), per_week?, remind_at? (HH:MM)}"""
    v1_args(())
    b = _v1_body(("name", "color", "goal", "days", "per_week", "remind_at"))
    j = v1_call(habit_create, body=b)
    c = db()
    return jsonify(v1_habit(c, c.execute("SELECT * FROM habits WHERE id=?", (j["id"],)).fetchone())), 201


@app.patch("/api/v1/habits/<int:hid>")
@v1_view
def v1_habit_update(hid):
    v1_args(())
    b = _v1_body(("name", "color", "goal", "days", "per_week", "remind_at", "archived"))
    if "archived" in b:
        if not isinstance(b["archived"], bool):
            raise BadInput(tr("Invalid value: {0}", "archived"))
        b = {**b, "archived": 1 if b["archived"] else 0}
    v1_call(habit_update, hid, body=b)
    c = db()
    return jsonify(v1_habit(c, c.execute("SELECT * FROM habits WHERE id=?", (hid,)).fetchone()))


@app.delete("/api/v1/habits/<int:hid>")
@v1_view
def v1_habit_delete(hid):
    v1_args(())
    v1_call(habit_delete, hid, body={})
    return Response(status=204)


# time: the timer, changing / deleting entries
@app.get("/api/v1/time/timer")
@v1_view
def v1_timer():
    """The running timer (null = none)."""
    v1_args(())
    need_time()
    t = time_running(db(), me())
    return jsonify(timer=v1_entry(t) if t else None)


@app.post("/api/v1/time/timer")
@v1_view
def v1_timer_start():
    """{task_id | list_id, note?}: start the timer (a running one stops at that moment)."""
    v1_args(())
    need_time()
    v1_feature("time")
    b = _v1_body(("task_id", "list_id", "note"))
    j = v1_call(time_start, body=b)
    return jsonify(timer=v1_entry(j["timer"]) if j.get("timer") else None,
                   stopped=j.get("stopped")), 201


@app.delete("/api/v1/time/timer")
@v1_view
def v1_timer_stop():
    """Stop the running timer; the entry is returned (null = nothing was running)."""
    v1_args(())
    need_time()
    j = v1_call(time_stop, body={})
    return jsonify(entry=v1_entry(j["entry"]) if j.get("entry") else None, discarded=bool(j.get("discarded")))


@app.patch("/api/v1/time/entries/<int:eid>")
@v1_view
def v1_time_update(eid):
    v1_args(())
    need_time()
    b = _v1_body(("start", "end", "minutes", "note", "task_id", "list_id"))
    return jsonify(v1_entry(v1_call(time_update, eid, body=b)))


@app.delete("/api/v1/time/entries/<int:eid>")
@v1_view
def v1_time_delete(eid):
    v1_args(())
    need_time()
    v1_call(time_delete, eid, body={})
    return Response(status=204)


# project status (also in GET /lists/{id}/overview with its history)
@app.put("/api/v1/lists/<int:lid>/status")
@v1_view
def v1_list_status(lid):
    """{status: on_track | at_risk | off_track | on_hold | complete | "" (none), note?}: a status update of a project."""
    v1_args(())
    b = _v1_body(("status", "note"))
    v1_call(list_status_set, lid, body=b)
    r = db().execute("SELECT status, status_note, status_by, status_at FROM lists WHERE id=?", (lid,)).fetchone()
    return jsonify(status=r["status"] or None, note=r["status_note"] or "", by=r["status_by"], at=r["status_at"])


# export
@app.get("/api/v1/export")
@v1_view
def v1_export():
    """Everything you own as JSON (the same as Settings > Data > Export)."""
    v1_args(())
    if token_lists() is not None:  # 2.30.0 (#919): the export holds every list and personal data: not for a limited token
        raise Denied(403, tr("A token limited to selected lists cannot export everything"))
    return export_json()


def api479_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    """2.15.0 (#479): the routes above in the OpenAPI document (with their scopes)."""
    T, L, S = "Tasks", "Lists", "Structure"
    lp = pid("id", "List id")

    def sub(name, desc):
        return {"name": name, "in": "path", "required": True, "description": desc, "schema": {"type": "integer"}}
    obj = {"type": "object"}
    ids = {"type": "array", "items": {"type": "integer"}}
    schemas["Section"] = {"type": "object", "properties": {"id": {"type": "integer"}, "list_id": {"type": "integer"},
                                                         "name": {"type": "string"}, "sort": {"type": "number"}}}
    schemas["SectionPage"] = page("Section")
    schemas["Field"] = {"type": "object", "properties": {"id": {"type": "integer"}, "list_id": {"type": "integer"}, "name": {"type": "string"},
                                                       "type": {"type": "string"}, "options": obj, "pinned": {"type": "integer"},
                                                       "sort": {"type": "number"}}}
    schemas["FieldPage"] = page("Field")
    schemas["Template"] = {"type": "object", "properties": {"id": {"type": "integer"}, "kind": {"type": "string", "enum": ["task", "list"]},
                                                          "name": {"type": "string"}, "data": obj, "count": {"type": "integer"},
                                                          "created_at": {"type": "string"}, "updated_at": {"type": "string"}}}
    schemas["TemplatePage"] = page("Template")
    schemas["Dependencies"] = {"type": "object", "properties": {"blocked_by": {"type": "array", "items": obj}, "blocking": {"type": "array", "items": obj}}}
    schemas["Member"] = {"type": "object", "properties": {"user_id": {"type": "integer"}, "name": {"type": "string"},
                                                        "role": {"type": "string", "enum": ["owner", *ROLES]}, "agent": {"type": "boolean"},
                                                        "via_group": {"type": "boolean"}}}
    schemas["MemberPage"] = page("Member")
    schemas["Filter"] = {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "rules": obj, "sort": {"type": "number"}}}
    schemas["FilterPage"] = page("Filter")
    schemas["Folder"] = {"type": "object", "properties": {"path": {"type": "string"}, "lists": {"type": "integer"}}}
    schemas["FolderPage"] = page("Folder")
    schemas["Approval"] = {"type": "object", "description": "202: an agent's request waits for a person's approval (#479)",
                           "properties": {"approval_required": {"type": "boolean"}, "job": obj, "message": {"type": "string"}}}
    acc = {"202": {"description": "Agents: waits for a person's approval (a job; the result comes as a job event)",
                   "content": {"application/json": {"schema": ref("Approval")}}}}
    nobody = {"204": {"description": "Done"}}
    new = {
        "/lists/{id}/sections": {
            "get": op("Sections of a list, in order", S, ok(ref("SectionPage")) | errs("404"), [lp]),
            "post": op("Create a section (at the end or before before_id)", S, ok(ref("Section"), "Created", "201") | errs("400", "403", "404"),
                       [lp], scope="structure", body={"type": "object", "required": ["name"], "properties": {
                           "name": {"type": "string", "maxLength": 200}, "before_id": {"type": "integer"}}})},
        "/lists/{id}/sections/order": {"put": op("Reorder all sections of a list", S, ok(ref("SectionPage")) | errs("400", "403", "404"), [lp],
                                                 scope="structure", body={"type": "object", "required": ["ids"], "properties": {"ids": ids}},
                                                 desc="ids: every section of the list exactly once, in the new order.")},
        "/sections/{id}": {
            "patch": op("Rename a section", S, ok(ref("Section")) | errs("400", "403", "404"), [pid("id", "Section id")], scope="structure",
                        body={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}),
            "delete": op("Delete a section (its tasks stay in the list)", S, ok(obj) | errs("403", "404"), [pid("id", "Section id")], scope="delete")},
        "/tasks/{id}/move": {"post": op("Move a task: list, section, parent and place", T, ok(ref("Task")) | errs("400", "403", "404"), [pid()],
                                        scope="tasks:write", body={"type": "object", "properties": {
                                            "list_id": {"type": "integer"}, "section_id": nul("integer"), "parent_id": nul("integer"),
                                            "before_id": {"type": "integer"}, "after_id": {"type": "integer"},
                                            "position": {"type": "string", "enum": ["top", "bottom"]}}},
                                        desc="Subtasks move along. Moving into another list needs edit rights there; out of a shared list "
                                             "only the owner (as in the app). before_id / after_id: a sibling in the target place.")},
        "/tasks/batch": {"post": op("Change many tasks at once", T, ok(obj) | acc | errs("400", "403"), scope="tasks:write",
                                    body={"type": "object", "required": ["ids", "action"], "properties": {
                                        "ids": {**ids, "minItems": 1, "maxItems": 500}, "action": {"type": "string", "enum": list(BATCH_ACTIONS)},
                                        "changes": {"type": "object", "description": "update: task fields (as PATCH /tasks/{id})"}}},
                                    desc="One transaction; tasks you may not change are skipped (errors). delete / restore also need the "
                                         f"scope delete. Agents: {APPROVAL_BATCH_MIN} or more tasks wait for a person's approval (202).")},
        "/tasks/{id}/skip": {"post": op("Skip this occurrence of a repeating task", T, ok(ref("Task")) | errs("400", "403", "404"), [pid()],
                                        scope="tasks:write")},
        "/tasks/{id}/restore": {"post": op("Restore a task from the trash", T, ok(ref("Task")) | errs("403", "404", "409"), [pid()], scope="delete")},
        "/trash": {"get": op("Tasks in the trash", T, ok(ref("TaskPage")) | errs("400"), [q("list_id", "Only this list", {"type": "integer"}),
                                                                                            q("limit", "Page size"), q("cursor", "next_cursor")]),
                   "delete": op("Empty the trash for good", T, ok(obj) | acc | errs("403"), scope="delete",
                                desc="Lists you own (admins: also shared lists they may edit). Agents: waits for approval (202).")},
        "/tasks/{id}/dependencies": {
            "get": op("What the task waits on and what waits on it", T, ok(ref("Dependencies")) | errs("404"), [pid()]),
            "post": op("The task waits on another task", T, ok(ref("Dependencies"), "Created", "201") | errs("400", "403", "404", "409"), [pid()],
                       scope="tasks:write", body={"type": "object", "required": ["blocked_by"], "properties": {"blocked_by": {"type": "integer"}}},
                       desc="Project lists only; no cycles.")},
        "/tasks/{id}/dependencies/{blocker_id}": {"delete": op("Remove a dependency", T, ok(ref("Dependencies")) | errs("403", "404"),
                                                               [pid(), sub("blocker_id", "The task it waits on")], scope="tasks:write")},
        "/lists/{id}/fields": {
            "get": op("Custom field definitions of a list", S, ok(ref("FieldPage")) | errs("404"), [lp]),
            "post": op("Create a custom field (project lists, owner)", S, ok(ref("Field"), "Created", "201") | errs("400", "403", "404", "409"), [lp],
                       scope="structure", body={"type": "object", "required": ["name", "type"], "properties": {
                           "name": {"type": "string"}, "type": {"type": "string"}, "options": obj, "pinned": {"type": "boolean"}}})},
        "/fields/{id}": {
            "patch": op("Change a custom field (the type stays)", S, ok(ref("Field")) | errs("400", "403", "404"), [pid("id", "Field id")],
                        scope="structure", body={"type": "object", "properties": {"name": {"type": "string"}, "options": obj,
                                                                                  "pinned": {"type": "boolean"}, "sort": {"type": "number"}}}),
            "delete": op("Delete a custom field with its values", S, ok(obj) | acc | errs("403", "404"), [pid("id", "Field id")], scope="delete",
                         desc="Agents: waits for approval (202).")},
        "/templates": {
            "get": op("Your templates", S, ok(ref("TemplatePage")) | errs()),
            "post": op("Create a template from a task, a list or data", S, ok(ref("Template"), "Created", "201") | errs("400", "403", "404"),
                       scope="structure", body={"type": "object", "properties": {
                           "task_id": {"type": "integer"}, "list_id": {"type": "integer"}, "relative": {"type": "boolean"},
                           "kind": {"type": "string", "enum": ["task", "list"]}, "data": obj, "name": {"type": "string"}}})},
        "/templates/{id}": {
            "patch": op("Rename a template or replace its data", S, ok(ref("Template")) | errs("400", "404"), [pid("id", "Template id")],
                        scope="structure", body={"type": "object", "properties": {"name": {"type": "string"}, "data": obj}}),
            "delete": op("Delete a template", S, nobody | errs("404"), [pid("id", "Template id")], scope="delete")},
        "/templates/{id}/apply": {"post": op("Use a template", S, ok(obj, "Created", "201") | errs("400", "403", "404"), [pid("id", "Template id")],
                                             scope="structure", body={"type": "object", "properties": {
                                                 "list_id": {"type": "integer"}, "section_id": {"type": "integer"}, "name": {"type": "string"},
                                                 "folder": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}}},
                                             desc="Task template: a task (+ subtasks) in list_id / section_id (default the inbox). "
                                                  "List template: a new list (name, folder, start / end move the dates).")},
        "/tasks/{id}/attachments": {"post": {**op("Upload files to a task", T, ok(page("Attachment") if "Attachment" in schemas else obj, "Created", "201")
                                                  | errs("400", "403", "404", "413"), [pid()], scope="attachments:write"),
                                             "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
                                                 "type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}}}}}},
        "/tasks/{id}/attachments/text": {"post": op(
            "Create a text file on a task (Markdown, plain text, HTML / CSS / JS, data, code)", T,
            ok({"type": "object", "properties": {"id": {"type": "integer"}, "task_id": {"type": "integer"}, "name": {"type": "string"},
                                                 "mime": {"type": "string"}, "size": {"type": "integer"}, "created_at": {"type": "string"},
                                                 "version": {"type": "integer"}, "replaces": {"type": ["integer", "null"]},
                                                 "url": {"type": "string"}}}, "Created", "201") | errs("400", "403", "404", "413"),
            [pid()], scope="attachments:write",
            body={"type": "object", "required": ["name", "content"], "properties": {
                "name": {"type": "string", "description": "File name with its ending, e.g. report.md"},
                "content": {"type": "string", "description": f"UTF-8 text, at most {TEXT_MAX // 1024} KB"}}},
            desc="2.30.0: the app shows Markdown formatted and everything else as source text, never runs it. An ending that is not "
                 "a known text type (.sh, .ps1, .bat, .exe ...) gets .txt appended. A name the task already has creates a new "
                 "version next to it (report (v2).md; version + replaces in the answer), the old file stays.")},
        "/attachments/{id}": {"delete": op("Remove a file of a task or comment", T, nobody | errs("403", "404"), [pid("id", "Attachment id")],
                                           scope="attachments:write")},
        "/comments/{id}": {
            "patch": op("Edit your comment", "Comments", ok(ref("Comment")) | errs("400", "403", "404"), [pid("id", "Comment id")], scope="comments",
                        body={"type": "object", "required": ["body"], "properties": {"body": {"type": "string"}}}),
            "delete": op("Delete a comment (author, list owner / admins)", "Comments", nobody | errs("403", "404"), [pid("id", "Comment id")],
                         scope="comments")},
        "/folders": {"get": op("Your folders (paths like Clients/Acme) with their number of lists", L, ok(ref("FolderPage")) | errs())},
        "/folders/rename": {"post": op("Rename or move a folder", L, ok(ref("FolderPage")) | acc | errs("400"), scope="structure",
                                       body={"type": "object", "required": ["old", "new"], "properties": {"old": {"type": "string"}, "new": {"type": "string"}}},
                                       desc="Its lists and subfolders go along. Agents: waits for approval (202).")},
        "/folders/delete": {"post": op("Remove a folder (its lists move up a level)", L, ok(ref("FolderPage")) | acc | errs("400"), scope="structure",
                                       body={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
                                       desc="Agents: waits for approval (202).")},
        "/lists/{id}/members": {"get": op("Owner and members of a list with their roles", L, ok(ref("MemberPage")) | errs("404"), [lp])},
        "/lists/{id}/members/{user_id}": {
            "put": op("Share a list with a person (or change the role)", L, ok(ref("MemberPage")) | acc | errs("400", "403", "404"),
                      [lp, sub("user_id", "User id")], scope="structure",
                      body={"type": "object", "properties": {"role": {"type": "string", "enum": list(ROLES)}}},
                      desc="Owner / list admins. Agents: waits for approval (202)."),
            "delete": op("Stop sharing with a person, or leave the list (your own id)", L, nobody | acc | errs("403", "404"),
                         [lp, sub("user_id", "User id")], scope="structure", desc="Agents removing someone else: waits for approval (202).")},
        "/filters": {
            "get": op("Your saved filters", S, ok(ref("FilterPage")) | errs()),
            "post": op("Save a filter", S, ok(ref("Filter"), "Created", "201") | errs("400"), scope="structure",
                       body={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}, "rules": obj}})},
        "/filters/{id}": {
            "patch": op("Change a saved filter", S, ok(ref("Filter")) | errs("400", "404"), [pid("id", "Filter id")], scope="structure",
                        body={"type": "object", "properties": {"name": {"type": "string"}, "rules": obj, "sort": {"type": "number"}}}),
            "delete": op("Delete a saved filter", S, nobody | errs("404"), [pid("id", "Filter id")], scope="delete")},
        "/news": {"get": op("Your News, newest first", "Account", ok(obj) | errs("400"), [q("filter", "mentions | me")])},
        "/news/read": {"post": op("Mark News read", "Account", ok(obj) | errs("400"), scope="comments",
                                  body={"type": "object", "properties": {"ids": ids, "all": {"type": "boolean"}}})},
        "/habits": {"post": op("Create a habit", "Habits", ok(ref("Habit"), "Created", "201") | errs("400", "403"), scope="tasks:write",
                               body={"type": "object", "required": ["name"], "properties": {
                                   "name": {"type": "string"}, "color": {"type": "string"}, "goal": {"type": "integer"},
                                   "days": {"type": "string"}, "per_week": {"type": "integer"}, "remind_at": {"type": "string"}}})},
        "/habits/{id}": {
            "patch": op("Change a habit", "Habits", ok(ref("Habit")) | errs("400", "404"), [pid("id", "Habit id")], scope="tasks:write",
                        body={"type": "object", "properties": {"name": {"type": "string"}, "color": {"type": "string"}, "goal": {"type": "integer"},
                                                               "days": {"type": "string"}, "per_week": {"type": "integer"},
                                                               "remind_at": {"type": "string"}, "archived": {"type": "boolean"}}}),
            "delete": op("Delete a habit", "Habits", nobody | errs("404"), [pid("id", "Habit id")], scope="delete")},
        "/time/timer": {
            "get": op("The running timer", "Time tracking", ok(obj) | errs("403")),
            "post": op("Start the timer", "Time tracking", ok(obj, "Created", "201") | errs("400", "403", "404", "409"), scope="time",
                       body={"type": "object", "properties": {"task_id": {"type": "integer"}, "list_id": {"type": "integer"}, "note": {"type": "string"}}}),
            "delete": op("Stop the timer", "Time tracking", ok(obj) | errs("403"), scope="time")},
        "/time/entries/{id}": {
            "patch": op("Change your time entry", "Time tracking", ok(ref("TimeEntry")) | errs("400", "403", "404"), [pid("id", "Entry id")], scope="time",
                        body={"type": "object", "properties": {k: {"type": "string"} for k in ("start", "end", "note")} | {
                            "minutes": {"type": "number"}, "task_id": {"type": "integer"}, "list_id": {"type": "integer"}}}),
            "delete": op("Delete your time entry", "Time tracking", nobody | errs("403", "404"), [pid("id", "Entry id")], scope="time")},
        "/export": {"get": op("Export everything you own as JSON", "Account", ok(obj) | errs(), scope="export")},
        "/lists/{id}/status": {"put": op("Post a status update of a project", L, ok(obj) | errs("400", "403", "404", "409"), [lp], scope="structure",
                                         body={"type": "object", "properties": {"status": {"type": "string", "enum": [*LIST_STATUSES, ""]},
                                                                                "note": {"type": "string"}}},
                                         desc="Members are told (News / push). The history: GET /lists/{id}/overview.")},
    }
    for p_, ms in new.items():  # merged: some paths already have a GET (habits, a task's attachments, an attachment)
        paths.setdefault(p_, {}).update(ms)
    paths["/lists/{id}"]["delete"] = op("Delete an archived list for good", L, nobody | acc | errs("403", "404", "409"), [lp], scope="delete",
                                        desc="Owner only; archive it first (PATCH archived=true). Its tasks go to the owner's trash. "
                                             "Agents: waits for approval (202).")
