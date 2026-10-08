#!/usr/bin/env python3
"""Kalmido MCP server: lets an AI agent (Claude Code, Claude Desktop, any MCP client) use Kalmido as a tool.

Python 3 standard library only. It talks to the Kalmido REST API (/api/v1) with the agent's personal access token, so the
agent can never do more than its Kalmido user may: it sees only the lists shared with it, is never an admin and has no
Paperless access. Kalmido itself never starts AI processes; this server runs wherever YOU run your agent.

Configuration (environment):
  KALMIDO_URL     base address of the instance, e.g. https://tasks.example.com
  KALMIDO_TOKEN   the agent's API token (abk_...), Settings > Agents (team agents: admins; personal agents: Set up)
  MCP_HTTP_TOKEN optional: HTTP mode requires "Authorization: Bearer <this>" from the MCP client

Transports:
  python3 kalmido_mcp.py                      stdio (newline-delimited JSON-RPC 2.0), the default
  python3 kalmido_mcp.py --http [--host 127.0.0.1] [--port 8765]
                                             Streamable HTTP subset: POST /mcp, JSON responses (no SSE)
See mcp/README.md and docs/AGENTS.md.
"""
import argparse
import base64
import json
import os
import sys
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVER_NAME = "kalmido"
SERVER_VERSION = "2.21.0"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
WAIT_MAX = 60
ATT_CAP_DEFAULT = 5 * 1024 * 1024    # 2.13.1 (#465): get_attachment returns at most this many bytes (base64 in the answer)
ATT_CAP_MAX = 20 * 1024 * 1024

# ---------------------------------------------------------------- REST client


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class Kalmido:
    def __init__(self, url, token, timeout=30):
        self.base = (url or "").rstrip("/")
        self.token = token or ""
        self.timeout = timeout

    def call(self, method, path, query=None, body=None, timeout=None, multipart=None, binary_cap=None):
        """multipart: (fields dict, [(name, mime, bytes)]) -> a multipart/form-data body (field `file` per file).
        binary_cap: the answer is a file -> {"bytes", "mime", "name"} (ApiError 413 when larger than the cap)."""
        if not self.base or not self.token:
            raise ApiError(0, "KALMIDO_URL and KALMIDO_TOKEN must be set")
        q = {k: v for k, v in (query or {}).items() if v is not None and v != ""}
        url = self.base + "/api/v1" + path + ("?" + urllib.parse.urlencode(q) if q else "")
        ctype = {}
        if multipart is not None:
            data, ct = _multipart(*multipart)
            ctype = {"Content-Type": ct}
        else:
            data = json.dumps(body).encode() if body is not None else None
            if data is not None:
                ctype = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.token, "Accept": "*/*" if binary_cap else "application/json",
            "User-Agent": f"kalmido-mcp/{SERVER_VERSION}", **ctype})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                if binary_cap:
                    n = int(r.headers.get("Content-Length") or 0)
                    if n > binary_cap:
                        raise ApiError(413, f"the file has {n} bytes, more than max_bytes={binary_cap}")
                    raw = r.read(binary_cap + 1)
                    if len(raw) > binary_cap:
                        raise ApiError(413, f"the file is larger than max_bytes={binary_cap}")
                    return {"bytes": raw, "mime": (r.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip(),
                            "name": _cd_name(r.headers.get("Content-Disposition") or "")}
                raw = r.read()
                return json.loads(raw) if raw else {"ok": True}
        except urllib.error.HTTPError as e:
            raw = e.read()
            msg = f"HTTP {e.code}"
            try:
                j = json.loads(raw)
                er = j.get("error")
                msg = (er.get("message") if isinstance(er, dict) else er) or msg
                msg = f"HTTP {e.code}: {msg}"
            except (ValueError, AttributeError):
                pass
            raise ApiError(e.code, msg) from None
        except (urllib.error.URLError, OSError) as e:
            raise ApiError(0, f"cannot reach Kalmido: {getattr(e, 'reason', e)}") from None


def _multipart(fields, files):
    b = "kalmido" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        if v is None:
            continue
        out += [f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n".encode(), str(v).encode(), b"\r\n"]
    for name, mime, data in files:
        safe = name.replace("\\", "_").replace('"', "_").replace("\r", "").replace("\n", "")
        out += [f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{safe}\"\r\nContent-Type: {mime}\r\n\r\n".encode(),
                data, b"\r\n"]
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def _cd_name(cd):
    """The file name of a Content-Disposition header (filename*=UTF-8'' or filename=)."""
    for part in cd.split(";"):
        k, _, v = part.strip().partition("=")
        if k.lower() == "filename*" and "''" in v:
            return urllib.parse.unquote(v.split("''", 1)[1])
    for part in cd.split(";"):
        k, _, v = part.strip().partition("=")
        if k.lower() == "filename":
            return v.strip('"')
    return ""


# ---------------------------------------------------------------- tools

S_ID = {"type": "integer", "minimum": 1}
PRIO = {"type": "string", "enum": ["none", "low", "medium", "high"]}
STRS = {"type": "array", "items": {"type": "string"}}
TASK_FIELDS = {
    "title": {"type": "string"}, "list_id": S_ID, "notes": {"type": "string", "description": "Markdown"},
    "section_id": {"type": ["integer", "null"]}, "priority": PRIO,
    "due": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
    "due_time": {"type": ["string", "null"], "description": "HH:MM (local), null = all day"},
    "assignee_id": {"type": ["integer", "null"]}, "tags": {**STRS, "description": "the agent's personal tags"},
    "assignee_group_id": {"type": ["integer", "null"], "description": "2.10.0: assign to a group (whoever has time takes it); "
                          "the list must be shared with the group; clears assignee_id and the other way round"},
    "duration": {"type": ["integer", "null"], "minimum": 1, "description": "minutes (the calendar block of a timed task)"},
    "list_tags": {**STRS, "description": "shared list tags (seen by every list member)"},
    "parent_id": S_ID,
    "type": {"type": ["string", "null"], "enum": ["bug", "feature", "task", None],
             "description": "ticket type (lists with ticket types on); a new bug / feature with empty notes gets the list's template"},
    # 2.18.0 (#430): milestones are tasks; a task belongs to at most one milestone of its own list (e.g. a release / version)
    "milestone": {"type": "boolean", "description": "2.18.0: the task is a milestone (a diamond with a date, top level, no subtasks)"},
    "milestone_id": {"type": ["integer", "null"], "description": "2.18.0: the milestone task (same list) this task belongs to; null = none"},
    # 2.19.0 (#653): the module Family
    "rotation": {"type": ["object", "null"], "description": "2.19.0: household rotation {who: [user ids sharing the list, at least 2], "
                 "mode: done (next person after each completion) | week (every Monday)}; sets the assignee; null = none"},
    "people": {"type": "array", "items": {"type": "integer"}, "description": "2.19.0: who comes along (user ids sharing the list): they see the "
               "task and get its reminders"},
    "stars": {"type": ["integer", "null"], "minimum": 0, "maximum": 50, "description": "2.19.0: stars a kid account gets for completing it (null = 1)"},
    "family": {"type": ["object", "null"], "description": "2.19.0: birthday / anniversary {kind, name, year?, lead?} or household deadline "
               "{kind: deadline, type, who, expires, notice, lead} data; easier: add_occasion / add_deadline"},
}
SUGGESTION = {"type": "object", "description": "structured tidy suggestion (lists with agent tidy 'suggest'/'auto'); "
              "a 👍 by someone who may change the task applies it",
              "properties": {"title": {"type": "string"}, "notes": {"type": "string"}, "section_id": {"type": ["integer", "null"]},
                             "list_tags": STRS, "tags": STRS, "priority": PRIO}, "additionalProperties": False}


def _obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


def _pick(a, keys):
    return {k: a[k] for k in keys if k in a}


COMPACT_FIELDS = ("id", "title", "list_id", "section_id", "parent_id", "status", "due", "due_time", "priority", "tags", "list_tags",
                  "assignee_id")
COMPACT_AUTO = 25  # 2.0.8: without `compact`, a page with more tasks than this comes back compact


def t_list_tasks(api, a):
    """2.0.8: compact=true -> the API's fields=compact; false -> full tasks; not given -> full for small results,
    compact (client side, with "compact": true in the result) once a page has more than COMPACT_AUTO tasks."""
    q = _pick(a, ("list_id", "status", "tag", "list_tag", "assignee", "assignee_group", "limit", "cursor", "type"))
    if "waiting" in a:  # 2.1.0 (#335)
        q["waiting"] = "true" if a["waiting"] else "false"
    if "pinned" in a:  # 2.16.0 (#648)
        q["pinned"] = "true" if a["pinned"] else "false"
    if "milestone" in a:  # 2.18.0 (#430)
        q["milestone"] = "true" if a["milestone"] else "false"
    if a.get("milestone_id"):
        q["milestone_id"] = a["milestone_id"]
    if a.get("compact") is True:
        q["fields"] = "compact"
    r = api.call("GET", "/tasks", q)
    if a.get("compact") is True:
        r["compact"] = True
    elif "compact" not in a and len(r.get("data") or []) > COMPACT_AUTO:
        r["data"] = [{k: t.get(k) for k in COMPACT_FIELDS} for t in r["data"]]
        r["compact"] = True
        r["hint"] = "Compact because the page is large: get_task gives one task in full, compact=false the full page."
    return r


def t_get_task(api, a):
    tid = int(a["task_id"])
    task = api.call("GET", f"/tasks/{tid}")
    try:
        task["comments"] = api.call("GET", f"/tasks/{tid}/comments").get("data", [])
    except ApiError as e:  # collaboration off, or a context task: the task alone is still useful
        task["comments"], task["comments_error"] = [], e.message
    return task


def t_update_task(api, a):
    b = {k: v for k, v in a.items() if k != "task_id"}
    return api.call("PATCH", f"/tasks/{int(a['task_id'])}", body=b)


def t_add_comment(api, a):
    b = {"body": a["body"]}
    if a.get("suggestion"):
        b["suggestion"] = a["suggestion"]
    return api.call("POST", f"/tasks/{int(a['task_id'])}/comments", body=b)


def t_react(api, a):
    cid = int(a["comment_id"])
    if a.get("remove"):
        return api.call("DELETE", f"/comments/{cid}/reactions/{urllib.parse.quote(a['emoji'])}")
    return api.call("POST", f"/comments/{cid}/reactions", body={"emoji": a["emoji"]})


def t_react_chat(api, a):
    """2.7.2 (#421): a reaction on a message of the chat with person user_id (never an approval; no event)."""
    return api.call("POST", f"/agent/chats/{int(a['user_id'])}/messages/{int(a['message_id'])}/reactions",
                    body={"emoji": a["emoji"], "on": not a.get("remove")})


# 2.29.0 (#1031): an event cursor, or "latest" (start from now: no events, only the newest cursor)
S_SINCE = {"type": ["integer", "string"], "minimum": 0, "description": "event cursor (seq), or \"latest\""}


def t_wait(api, a):
    w = max(0, min(WAIT_MAX, int(a.get("wait", 30))))
    return api.call("GET", "/agent/events", {"since": a.get("since"), "wait": w, "limit": a.get("limit")}, timeout=w + 20)


def t_update_job(api, a):
    return api.call("PATCH", f"/agent/jobs/{int(a['job_id'])}", body={k: v for k, v in a.items() if k != "job_id"})


def t_send_chat(api, a):
    """2.13.1 (#465): files = [{name, base64, mime?}] -> a multipart message (the body may then be empty)."""
    if a.get("files"):
        files = []
        for f in a["files"]:
            if not isinstance(f, dict) or not isinstance(f.get("name"), str) or not isinstance(f.get("base64"), str):
                raise ApiError(400, "files: each entry needs name and base64")
            try:
                data = base64.b64decode(f["base64"], validate=True)
            except ValueError:
                raise ApiError(400, f"files: {f['name']} is not valid base64") from None
            files.append((f["name"], f.get("mime") or "application/octet-stream", data))
        return api.call("POST", f"/agent/chats/{int(a['user_id'])}", multipart=(_pick(a, ("body", "task_id", "choices", "multi")), files))
    if not a.get("body"):
        raise ApiError(400, "body (or files) is required")
    return api.call("POST", f"/agent/chats/{int(a['user_id'])}", body=_pick(a, ("body", "task_id", "choices", "multi")))


def t_get_attachment(api, a):
    """2.13.1 (#465): one file as base64 (source task = task / comment attachment, chat = a chat message's file), at most
    max_bytes (default 5 MB). Images also come as an MCP image item, so the model sees them."""
    cap = int(a.get("max_bytes") or ATT_CAP_DEFAULT)
    if a.get("source") == "project":  # 2.15.0 (#479): a project file (list_id needed)
        if not a.get("list_id"):
            raise ApiError(400, "list_id is required for source project")
        path = f"/lists/{int(a['list_id'])}/files/{int(a['attachment_id'])}"
    else:
        path = (f"/chat-attachments/{int(a['attachment_id'])}" if a.get("source") == "chat" else f"/attachments/{int(a['attachment_id'])}")
    r = api.call("GET", path, binary_cap=cap)
    return {"id": int(a["attachment_id"]), "source": a.get("source") or "task", "name": r["name"], "mime": r["mime"],
            "size": len(r["bytes"]), "base64": base64.b64encode(r["bytes"]).decode()}


def t_set_waiting(api, a):
    """2.1.0 (#335): waiting on someone outside (note = who / what, until = follow-up day YYYY-MM-DD or null)."""
    return api.call("PUT", f"/tasks/{int(a['task_id'])}/waiting", body=_pick(a, ("note", "until")))


def t_list_waiting(api, a):
    q = {"waiting": "true", **_pick(a, ("list_id", "limit", "cursor"))}
    return api.call("GET", "/tasks", q)


def t_request_gate(kind):
    """2.26.0 (#949): "ready to integrate" / "ready to deploy" without a pull request (comment with a structured field).
    The approver's decision arrives as a reaction event (approval approved / rejected, data.gate {kind, state, ...})."""
    def run(api, a):
        sug = {"kind": kind, **_pick(a, ("summary", "evidence") + (("source", "target") if kind == "integrate" else ("integrations",)))}
        head = (f"Ready to integrate: {a.get('source')} -> {a.get('target') or 'main'}" if kind == "integrate" else "Ready to deploy")
        summary = (a.get("summary") or "").strip()
        return api.call("POST", f"/tasks/{int(a['task_id'])}/comments", body={"body": head + (f"\n\n{summary}" if summary else ""), "suggestion": sug})
    return run


def t_request_merge(api, a):
    """2.2.0 (#339): a "ready to merge" comment with the structured field {kind: merge_request, pr_url, summary}. An approver's
    👍 / 👎 on it arrives as a reaction event (approval approved / rejected, merge_request {pr_url, state})."""
    summary = (a.get("summary") or "").strip()
    body = f"Ready to merge: {a['pr_url']}" + (f"\n\n{summary}" if summary else "")
    return api.call("POST", f"/tasks/{int(a['task_id'])}/comments",
                    body={"body": body, "suggestion": {"kind": "merge_request", "pr_url": a["pr_url"], "summary": summary}})


def t_submit_proposal(api, a):
    """2.3.0: the structured proposal for a job_request (the job's kind decides the shape, see docs/AGENTS.md "Proposals")."""
    return api.call("POST", f"/agent/jobs/{int(a['job_id'])}/proposal", body=a["proposal"])


def t_tidy(api, a):
    return api.call("POST", f"/tasks/{int(a['task_id'])}/tidy", body={k: v for k, v in a.items() if k != "task_id"})


TOOLS = [
    ("get_agent", "Who am I: the agent's user, enabled state, status, job counts, the latest event cursor and runtime (the "
                  "settings an admin chose for the agent's host: model, autocompact, autocompact_pct, nightly_reset HH:MM in "
                  "timezone, reset_seq raised by 'Reset now').",
     _obj({}), lambda api, a: api.call("GET", "/agent")),
    ("list_lists", "Lists the agent can see (shared with it), with role, sections [{id, name}], list tags, the agent tidy mode "
                   "(off/suggest/auto) and tidy_agent_id (the one agent that tidies the list up; only that agent gets tidy events). "
                   "listen_agent_ids (2.13.1): agents that get a comment event for EVERY comment a person writes in the list "
                   "(\"Agent reads every comment\", set by the list owner / admins), not only on tasks they follow. "
                   "columns (2.14.0): the list's row columns in order (null = default layout), see set_list_columns. "
                   "project_type (2.18.0): agency | software | private, null = none.",
     _obj({}), lambda api, a: api.call("GET", "/lists")),
    ("set_list_columns", "2.14.0: set which columns the rows of a list show and in which order, the same for every member "
                         "(only as the list's owner or admin). Keys: id (task number in front of the title), due, prio, who "
                         "(assignee), tags, time (tracked), progress (subtasks), deps (dependencies), created, f:<field id> "
                         "(custom fields; ids in the fields of list_lists). A key that is not listed is not shown. columns: null = the "
                         "default layout. Phones show the first two as columns, the rest in the second line.",
     _obj({"list_id": S_ID, "columns": {"type": ["array", "null"], "items": {"type": "string"}, "maxItems": 40}}, ["list_id", "columns"]),
     lambda api, a: api.call("PATCH", f"/lists/{int(a['list_id'])}", body={"columns": a["columns"]})),
    ("list_repos", "Repositories connected to a list (provider github | gitlab | gitea (also Forgejo) | bitbucket (Bitbucket Cloud), "
                   "web_url, owner/repo (GitLab owners can be nested groups: group/sub), default branch, poll status). Never a token: "
                   "clone and push with your own git credentials.",
     _obj({"list_id": S_ID}, ["list_id"]), lambda api, a: api.call("GET", f"/lists/{int(a['list_id'])}/repos")),
    ("get_project_overview", "The overview of a project list (read-only): description (Markdown), key links (title + url, in "
                             "order), milestones (name, day, done; since 2.18.0 their ids are task ids), project files and Paperless documents of the list, the files "
                             "of its tasks (with task_id), members with roles, the project status with its history and the tracked "
                             "time. 409 for lists that are not projects.",
     _obj({"list_id": S_ID}, ["list_id"]), lambda api, a: api.call("GET", f"/lists/{int(a['list_id'])}/overview")),
    ("list_list_tags", "Shared tags of one list (name, color).",
     _obj({"list_id": S_ID}, ["list_id"]), lambda api, a: api.call("GET", f"/lists/{int(a['list_id'])}/tags")),
    ("list_tasks", "Tasks the agent can see, filtered. status: open (default) | done | wont_do | all; assignee: me | none | user id. "
                   "compact: true = only id, title, list_id, section_id, parent_id, status, due, due_time, priority, tags, list_tags, "
                   "assignee_id; false = full tasks; not given = full, but compact once a page has more than 25 tasks.",
     _obj({"list_id": S_ID, "status": {"type": "string", "enum": ["open", "done", "wont_do", "all"]}, "tag": {"type": "string"},
           "list_tag": {"type": "string"}, "assignee": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 500},
           "cursor": {"type": "string"}, "compact": {"type": "boolean"},
           "waiting": {"type": "boolean", "description": "true = only tasks waiting on someone, false = only the others"},
           "pinned": {"type": "boolean", "description": "2.16.0: true = only pinned tasks (the 'Pinned' view), false = only the others"},
           "type": {"type": "string", "enum": ["bug", "feature", "task", "none"], "description": "only tickets of this type"},
           "assignee_group": {"type": "string", "description": "2.10.0: mine (assigned to one of your groups) or a group id"},
           "milestone": {"type": "boolean", "description": "2.18.0: true = only milestones, false = only the other tasks"},
           "milestone_id": {**S_ID, "description": "2.18.0: only the tasks of this milestone"}}), t_list_tasks),
    ("get_milestone", "2.18.0: a milestone task (read-only): progress (done / total of its tasks), its tasks (open first), a burndown "
                      "(open tasks per day + the ideal line to the due date) and release notes (Markdown of its completed tasks by "
                      "ticket type). Milestones are tasks with milestone: true (list_tasks milestone=true).",
     _obj({"task_id": S_ID}, ["task_id"]), lambda api, a: api.call("GET", f"/tasks/{int(a['task_id'])}/milestone")),
    # 2.10.0 (#441): groups (read) and the groups a list is shared with
    ("list_groups", "Groups of people (an admin creates them): id, name, members [{user_id, name}], synced (members follow a "
                    "sign-in group), mine. Lists and folders can be shared with a group; a task can be assigned to a group "
                    "(assignee_group_id) until one member takes it.",
     _obj({}), lambda api, a: api.call("GET", "/groups")),
    ("list_list_groups", "The groups one list is shared with: group_id, name, role, via (list = directly, else the folder).",
     _obj({"list_id": S_ID}, ["list_id"]), lambda api, a: api.call("GET", f"/lists/{int(a['list_id'])}/groups")),
    # 2.10.0 (#440): the built-in day plan + the daily review of the token's user (read-only previews)
    ("get_day_plan", "The built-in day plan of your user for a day (preview, nothing changes): working hours, calendar events, "
                     "fixed timed tasks, plan [{task_id, title, start, end, duration, estimated, reason}], nofit (tasks of the day "
                     "that do not fit; never moved) and free_min. Applying a plan sets plan_start + duration only, never due dates. mode: day = plan the day's tasks, fill = only fill free time with other tasks. For a person's "
                     "plan answer their job_request of kind dayplan with submit_proposal instead.",
     _obj({"date": {"type": "string", "description": "YYYY-MM-DD, default today"}, "mode": {"type": "string", "enum": ["day", "fill"]}}),
     lambda api, a: api.call("GET", "/dayplan", _pick(a, ("date", "mode")))),
    ("get_day_review", "The daily review of your user: done, still open and moved tasks of a day and a short plan for the next "
                       "working day.",
     _obj({"date": {"type": "string", "description": "YYYY-MM-DD, default today"}}),
     lambda api, a: api.call("GET", "/dayplan/review", _pick(a, ("date",)))),
    ("search_tasks", "Full-text search in titles, notes, links and custom fields of visible tasks.",
     _obj({"q": {"type": "string", "minLength": 1}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}, ["q"]),
     lambda api, a: api.call("GET", "/search", _pick(a, ("q", "limit")))),
    ("get_task", "One task with its comments (reactions, suggestions included). In a list connected to a repository also `code` "
                 "(linked pull requests with state + CI, commits) and `repo` (provider, web_url, owner, repo, default_branch, a "
                 "suggested branch name kalmido-<id>).",
     _obj({"task_id": S_ID}, ["task_id"]), t_get_task),
    ("create_task", "Create a task (or a subtask with parent_id) in a list the agent may change.",
     _obj(TASK_FIELDS, ["title"]), lambda api, a: api.call("POST", "/tasks", body=a)),
    ("update_task", "Change fields of a task. Only the given fields change.",
     _obj({"task_id": S_ID, **{k: v for k, v in TASK_FIELDS.items() if k != "parent_id"}}, ["task_id"]), t_update_task),
    ("complete_task", "Mark a task done (repeating tasks move to their next date).",
     _obj({"task_id": S_ID}, ["task_id"]), lambda api, a: api.call("POST", f"/tasks/{int(a['task_id'])}/complete")),
    ("set_waiting", "Mark a task as waiting on someone (outside: a client, an office, a delivery), or change it. note: who / "
                    "what it waits for; until: the follow-up day (YYYY-MM-DD) -- on that day the person gets a reminder and agents that "
                    "follow the task the event followup_due.",
     _obj({"task_id": S_ID, "note": {"type": "string", "maxLength": 300}, "until": {"type": ["string", "null"]}}, ["task_id"]), t_set_waiting),
    ("clear_waiting", "The task no longer waits on external.",
     _obj({"task_id": S_ID}, ["task_id"]), lambda api, a: api.call("DELETE", f"/tasks/{int(a['task_id'])}/waiting")),
    ("list_waiting", "Open tasks waiting on someone (task.waiting = {note, until, since, by}).",
     _obj({"list_id": S_ID, "limit": {"type": "integer", "minimum": 1, "maximum": 500}, "cursor": {"type": "string"}}), t_list_waiting),
    ("add_comment", "Comment on a task (Markdown; mention people as <@user_id>). Optional structured tidy suggestion.",
     _obj({"task_id": S_ID, "body": {"type": "string", "minLength": 1}, "suggestion": SUGGESTION}, ["task_id", "body"]), t_add_comment),
    ("request_merge_approval", "Ask for approval to merge your pull request: posts a 'ready to merge' comment on the task "
                               "(structured field kind merge_request). pr_url must be a pull request of a repository connected to "
                               "the task's list (GitLab: .../-/merge_requests/<n>, Bitbucket: .../pull-requests/<n>). Wait for the reaction event with approval 'approved' (👍 by the list owner / a list "
                               "admin / the assignee / an admin) before you merge; 'rejected' = do not merge.",
     _obj({"task_id": S_ID, "pr_url": {"type": "string", "minLength": 8, "maxLength": 500},
           "summary": {"type": "string", "maxLength": 2000}}, ["task_id", "pr_url"]), t_request_merge),
    ("request_integration_approval", "Ask a person to approve integrating your branch WITHOUT a pull request (e.g. feat/x into main): "
                                     "posts a 'ready to integrate' comment on the task with your evidence (build, start, logs, tests). Integrate "
                                     "only after the reaction event with approval 'approved'; 'rejected' = do not.",
     _obj({"task_id": S_ID, "source": {"type": "string", "minLength": 1, "maxLength": 200}, "target": {"type": "string", "maxLength": 200},
           "summary": {"type": "string", "maxLength": 4000}, "evidence": {"type": "string", "minLength": 1, "maxLength": 4000}},
          ["task_id", "source", "evidence"]), t_request_gate("integrate")),
    ("request_deploy_approval", "Ask a person to approve a deploy: bundles approved integrations (comment ids of your "
                                "request_integration_approval comments) and the checklist of open tasks tagged 'deploy' in the list. "
                                "A thumbs-up does not approve while that checklist has open tasks (the person may approve anyway). Deploy "
                                "only after the reaction event with approval 'approved'.",
     _obj({"task_id": S_ID, "integrations": {"type": "array", "items": {"type": "integer"}, "maxItems": 50},
           "summary": {"type": "string", "maxLength": 4000}, "evidence": {"type": "string", "minLength": 1, "maxLength": 4000}},
          ["task_id", "evidence"]), t_request_gate("deploy")),
    ("propose_to_other_topic", "Propose tasks for a list you cannot see (another topic, e.g. a change to a shared file). It lands "
                               "as a proposal with that list's owner -- never with the agent working there; only when a person applies "
                               "it do tasks exist. You learn the outcome as a job event.",
     _obj({"list_id": S_ID, "title": {"type": "string", "minLength": 1, "maxLength": 300}, "reason": {"type": "string", "minLength": 1, "maxLength": 5000},
           "tasks": {"type": "array", "minItems": 1, "maxItems": 50, "items": _obj({"title": {"type": "string", "minLength": 1, "maxLength": 300},
                                                                                     "notes": {"type": "string", "maxLength": 5000},
                                                                                     "due": {"type": "string", "format": "date"}}, ["title"])}},
          ["list_id", "title", "reason", "tasks"]), lambda api, a: api.call("POST", "/agent/proposals", body=_pick(a, ("list_id", "title", "reason", "tasks")))),
    ("react", "Add (or with remove=true take back) a reaction on a comment: up (👍), down (👎), heart (❤️) or any single emoji.",
     _obj({"comment_id": S_ID, "emoji": {"type": "string", "minLength": 1, "maxLength": 16,
                                         "description": "up, down, heart or one emoji character"}, "remove": {"type": "boolean"}},
          ["comment_id", "emoji"]), t_react),
    ("react_to_chat", "Add (or with remove=true take back) a reaction on a chat message of the conversation with person user_id "
                      "(message ids from list_chats / chat events): up (👍), down (👎), heart (❤️) or one emoji. A person's 👍 / 👎 on "
                      "YOUR chat message arrives as the event reaction with data.chat_message and approval approved / rejected: a 👍 "
                      "on your question is the go-ahead.",
     _obj({"user_id": S_ID, "message_id": S_ID, "emoji": {"type": "string", "minLength": 1, "maxLength": 16,
                                                         "description": "up, down, heart or one emoji character"}, "remove": {"type": "boolean"}},
          ["user_id", "message_id", "emoji"]), t_react_chat),
    ("set_status", "Report the agent's status, shown on its avatar: idle | working | waiting (for approval) | error | paused, plus a short text "
                   "(paused needs the reason, e.g. 'a person works interactively here': people see it in the chip and the chat; "
                   "events keep queueing until you report another status). "
                   "task_id (optional): the task you are working on; while working, its comment area shows '<agent> is writing ...'.",
     _obj({"status": {"type": "string", "enum": ["idle", "working", "waiting", "error", "paused"]}, "text": {"type": "string", "maxLength": 200},
           "task_id": S_ID},
          ["status"]), lambda api, a: api.call("PUT", "/agent/status", body=_pick(a, ("status", "text", "task_id")))),
    ("list_events", "Events for the agent (mention, comment, assigned, unassigned, chat, reaction, job, tidy, wake, ping, followup_due, "
     "job_request, runtime_changed, reset) after cursor `since`. runtime_changed / reset: your host should restart you (see get_agent "
     "runtime). job_request = a person asks for a proposal: read data.input, answer with submit_proposal. "
     "Store the returned cursor and pass it next time. Task events carry the task with its newest comments (task.comments, at most 20, "
     "task.comments_total) and the list with its sections and agent_tidy mode: no get_task / list_lists needed. A reaction on one of "
     "your chat messages: event reaction with data.chat_message {id, text, from, created_at}, data.reaction {emoji, user} and "
     "data.approval (approved = a person's 👍, rejected = 👎). Fetching a chat event marks the message delivered for the person. "
     "comment: tasks you follow (assignee, creator, earlier commenter) and, in lists where you read every comment (listen_agent_ids), "
     "every comment of a person. Chat messages carry attachments [{id, name, mime, size}]: read them with get_attachment source chat. "
     "No backlog floods: since='latest' on a first start returns no events, only the newest cursor; events older than two days come as "
     "ONE event missed {count, events: {type: n}, from, to} (read the current state instead); many tasks added to one list at once "
     "(bulk move, import, script) come as ONE event tasks_added {list, task_ids, count, how}.",
     _obj({"since": S_SINCE, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
     lambda api, a: api.call("GET", "/agent/events", _pick(a, ("since", "limit")))),
    ("wait_for_events", "Long-poll: like list_events, but waits up to `wait` seconds (max 60) until an event arrives.",
     _obj({"since": S_SINCE, "wait": {"type": "integer", "minimum": 0, "maximum": WAIT_MAX},
           "limit": {"type": "integer", "minimum": 1, "maximum": 500}}), t_wait),
    ("list_jobs", "The agent's jobs. state: running | waiting | done | failed | stopped.",
     _obj({"state": {"type": "string", "enum": ["running", "waiting", "done", "failed", "stopped"]}}),
     lambda api, a: api.call("GET", "/agent/jobs", _pick(a, ("state",)))),
    ("create_job", "Report a job (shown in the Agents tab with Approve / Reject / Stop). state defaults to running.",
     _obj({"title": {"type": "string", "minLength": 1}, "task_id": S_ID, "user_id": S_ID,
           "state": {"type": "string", "enum": ["running", "waiting", "done", "failed", "stopped"]}, "log": {"type": "string"}}, ["title"]),
     lambda api, a: api.call("POST", "/agent/jobs", body=a)),
    ("get_job", "One of the agent's jobs. A proposal job (event job_request) also carries kind (project | subtasks | triage | "
                "extract | dayplan), input (exactly what the person sent: never ask for more), proposal (what you submitted) and limits.",
     _obj({"job_id": S_ID}, ["job_id"]), lambda api, a: api.call("GET", f"/agent/jobs/{int(a['job_id'])}")),
    ("submit_proposal", "Answer a job_request with ONE structured proposal; the person reviews, edits and applies it. Never create "
                        "the lists / tasks yourself. proposal by kind -- project: {name, folder?, sections: [names], tasks: [{title, "
                        "notes?, section?, due?, start?, priority?, subtasks: [{title, notes?, due?}], depends_on: [task indices]}]}; "
                        "subtasks: {items: [{title, notes?, due?, estimate? (minutes)}], dependencies?: [[a, b]] (item a is blocked by b)}; "
                        "triage: {items: [{task_id, list_id?, section_id?, tags?, priority?, due?, rewrite_title?}]} (only ids from "
                        "the input); extract: {tasks: [{title, notes?, assignee_id? (a member id from the input), due?, section?}]}; "
                        "dayplan (2.10.0): {items: [{task_id, start (HH:MM), duration? (minutes, default the task's or input."
                        "default_duration), note?}], nofit: [{task_id, note?}]} -- applying sets only plan_start + duration, due dates "
                        "and deadlines never change; only task ids from "
                        "input.tasks; the input has date, now, work {start, end}, events, fixed (busy) and the built-in plan as a hint. "
                        "Every kind may add summary (a short explanation). Dates YYYY-MM-DD, priority none | low | medium | high. "
                        "At most 200 entries; resubmitting replaces the proposal until the person applied or discarded it.",
     _obj({"job_id": S_ID, "proposal": {"type": "object"}}, ["job_id", "proposal"]), t_submit_proposal),
    ("update_job", "Update a job: state, title, log (replace) or append_log (add lines).",
     _obj({"job_id": S_ID, "title": {"type": "string"}, "state": {"type": "string", "enum": ["running", "waiting", "done", "failed", "stopped"]},
           "log": {"type": "string"}, "append_log": {"type": "string"}}, ["job_id"]), t_update_job),
    ("list_chats", "Chat messages people sent to the agent (all conversations) after message id `since`, with reactions and "
                   "delivered_at (reading them marks them delivered).",
     _obj({"since": {"type": "integer", "minimum": 0}}), lambda api, a: api.call("GET", "/agent/chats", _pick(a, ("since",)))),
    ("chat_typing", "Show typing dots in one person's chat for 10 seconds while you write an answer (call again to keep them; "
                    "send_chat ends them).",
     _obj({"chat_user_id": S_ID}, ["chat_user_id"]), lambda api, a: api.call("POST", "/agent/typing", body=_pick(a, ("chat_user_id",)))),
    ("send_chat", "Answer in the chat with one person (user_id), optionally about a task. files (2.13.1): images / files to "
                  "attach, [{name, base64, mime?}] (at most 10, each within the server's upload limit); with files the body may be empty. "
                  "choices (2.28.0): answer buttons under the message, [{id, label, style?: primary | danger}] (at most 8; multi: several may "
                  "be picked) -- use them for questions and permission requests (put the command in a code block in the body, buttons "
                  "Allow / Deny). The person's answer arrives as the event chat_choice (message_id, choice_ids, labels); do not ask twice.",
     _obj({"user_id": S_ID, "body": {"type": "string"}, "task_id": S_ID,
           "choices": {"type": "array", "maxItems": 8, "items": {"type": "object", "properties": {
               "id": {"type": "string", "maxLength": 40}, "label": {"type": "string", "maxLength": 80},
               "style": {"type": "string", "enum": ["default", "primary", "danger"]}}, "required": ["id", "label"]}},
           "multi": {"type": "boolean"},
           "files": {"type": "array", "maxItems": 10, "items": {"type": "object", "properties": {
               "name": {"type": "string"}, "base64": {"type": "string"}, "mime": {"type": "string"}}, "required": ["name", "base64"]}}},
          ["user_id"]), t_send_chat),
    ("list_attachments", "Files of a task and of its comments (id, name, mime, size, comment_id): only tasks you see with their "
                         "comments. Read one with get_attachment.",
     _obj({"task_id": S_ID}, ["task_id"]), lambda api, a: api.call("GET", f"/tasks/{int(a['task_id'])}/attachments")),
    ("get_attachment", "Read one file: a task / comment attachment (source task, ids from list_attachments, get_task or comment "
                       "events), a chat file (source chat, ids from a chat message's attachments) or a project file (source project "
                       "+ list_id, ids from list_project_files). Returns name, mime, size and the "
                       "content as base64; images are also returned as an image you can look at. Use it when someone asks about a "
                       "screenshot. max_bytes caps the size (default 5 MB, at most 20 MB).",
     _obj({"attachment_id": S_ID, "source": {"type": "string", "enum": ["task", "chat", "project"]}, "list_id": S_ID,
           "max_bytes": {"type": "integer", "minimum": 1, "maximum": ATT_CAP_MAX}}, ["attachment_id"]), t_get_attachment),
    ("report_usage", "Report the agent's own model usage (numbers and ids only, never prompt content): model, input_tokens, "
                     "output_tokens, optional cache_read_tokens, cache_write_tokens, cost_usd, the task / list / job it was for and a "
                     "short note (max 200 characters). Shown in Kalmido's usage dashboard; admins may set limits on it. Works even when "
                     "the agent's hard limit is reached.",
     _obj({"model": {"type": "string", "minLength": 1, "maxLength": 100},
           **{k: {"type": "integer", "minimum": 0} for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")},
           "cost_usd": {"type": "number", "minimum": 0}, "task_id": S_ID, "list_id": S_ID, "job_id": S_ID,
           "note": {"type": "string", "maxLength": 200}}, ["model", "input_tokens", "output_tokens"]),
     lambda api, a: api.call("POST", "/agent/usage", body=a)),
    ("get_usage", "The agent's own reported usage between two local days (YYYY-MM-DD, default the last 30 days), grouped by "
                  "day | task | list | model, with totals and where it stands against its limit.",
     _obj({"from": {"type": "string"}, "to": {"type": "string"}, "group": {"type": "string", "enum": ["day", "task", "list", "model"]}}),
     lambda api, a: api.call("GET", "/agent/usage", _pick(a, ("from", "to", "group")))),
    ("tidy_task", "Tidy a task in a list with agent tidy mode 'auto': new title / notes / section / list tags / priority. "
     "Kalmido keeps the original text at the top of the notes. base_updated_at (2.27.0): the task's updated_at you read; "
     "409 = someone is working on the task right now, try again later.",
     _obj({"task_id": S_ID, "title": {"type": "string"}, "notes": {"type": "string"}, "section_id": {"type": ["integer", "null"]},
           "list_tags": STRS, "priority": PRIO, "base_updated_at": {"type": "string"}}, ["task_id"]), t_tidy),
]


# 2.21.0 (#659): events (scope calendar) and (#658) contacts (scope contacts: personal data, never in an agent's default)
EV_IN = {"cal_id": S_ID, "title": {"type": "string"}, "location": {"type": "string"}, "description": {"type": "string"},
         "all_day": {"type": "boolean"}, "start": {"type": "string", "description": "YYYY-MM-DDTHH:MM (local time of tz) or YYYY-MM-DD (all day)"},
         "end": {"type": "string", "description": "All day: the day AFTER the last day"}, "tz": {"type": "string", "description": "IANA zone, default the server's"},
         "rrule": {"type": "string", "description": "RRULE body, e.g. FREQ=WEEKLY;BYDAY=MO"}, "exdates": STRS,
         "reminders": {"type": "array", "items": {"type": "integer"}, "description": "minutes before the start"},
         "status": {"type": "string", "enum": ["confirmed", "tentative", "cancelled"]}, "busy": {"type": "boolean"},
         "url": {"type": ["string", "null"]}, "task_id": {"type": ["integer", "null"]},
         "attendees": {"type": "array", "items": {"type": "object", "properties": {"user_id": S_ID, "contact_id": S_ID, "email": {"type": "string"},
                                                                                 "name": {"type": "string"}}}}}
EV_KEYS = tuple(EV_IN)
OCC = {"occurrence": {"type": "string", "description": "only this date of a repeating event (its original start, Occurrence.occ)"}}
CT_IN = {"book_id": S_ID, "kind": {"type": "string", "enum": ["individual", "org", "group"]},
         **{k: {"type": "string"} for k in ("fn", "given", "family", "middle", "prefix", "suffix", "nickname", "org", "dept", "title", "note")},
         "emails": {"type": "array", "items": {"type": "object"}, "description": "[{value, type: [home|work|other]}]"},
         "phones": {"type": "array", "items": {"type": "object"}, "description": "[{value, type: [cell|home|work|other]}]"},
         "addresses": {"type": "array", "items": {"type": "object"}, "description": "[{street, city, code, region, country, type}]"},
         "urls": {"type": "array", "items": {"type": "object"}}, "bday": {"type": "string", "description": "YYYY-MM-DD or --MM-DD"},
         "anniversary": {"type": "string"}, "groups": STRS}
CT_KEYS = tuple(CT_IN)
TOOLS += [
    ("list_event_calendars", "2.21.0 (module Events): the event calendars you see (own + shared) with your role.", _obj({}),
     lambda api, a: api.call("GET", "/event-calendars")),
    ("create_event_calendar", "2.21.0: a new own calendar.", _obj({"name": {"type": "string"}, "color": {"type": "string"}, "description": {"type": "string"}}, ["name"]),
     lambda api, a: api.call("POST", "/event-calendars", body=_pick(a, ("name", "color", "description")))),
    ("update_event_calendar", "2.21.0: rename / recolour a calendar (owner) or hide it from your own views (hidden).",
     _obj({"calendar_id": S_ID, "name": {"type": "string"}, "color": {"type": "string"}, "description": {"type": "string"}, "hidden": {"type": "boolean"}}, ["calendar_id"]),
     lambda api, a: api.call("PATCH", f"/event-calendars/{int(a['calendar_id'])}", body=_pick(a, ("name", "color", "description", "hidden")))),
    ("delete_event_calendar", "2.21.0: delete a calendar with all its events (owner).", _obj({"calendar_id": S_ID}, ["calendar_id"]),
     lambda api, a: api.call("DELETE", f"/event-calendars/{int(a['calendar_id'])}")),
    ("share_event_calendar", "2.21.0: share a calendar with a person: view or edit (owner).",
     _obj({"calendar_id": S_ID, "user_id": S_ID, "role": {"type": "string", "enum": ["view", "edit"]}}, ["calendar_id", "user_id"]),
     lambda api, a: api.call("PUT", f"/event-calendars/{int(a['calendar_id'])}/members/{int(a['user_id'])}", body=_pick(a, ("role",)))),
    ("unshare_event_calendar", "2.21.0: stop sharing a calendar (owner) or leave one shared with you.", _obj({"calendar_id": S_ID, "user_id": S_ID}, ["calendar_id", "user_id"]),
     lambda api, a: api.call("DELETE", f"/event-calendars/{int(a['calendar_id'])}/members/{int(a['user_id'])}")),
    ("import_ics", "2.21.0: import the text of an .ics file into a calendar (the same UID is updated: no doubles); dry_run only counts.",
     _obj({"calendar_id": S_ID, "ics": {"type": "string"}, "dry_run": {"type": "boolean"}}, ["calendar_id", "ics"]),
     lambda api, a: api.call("POST", f"/event-calendars/{int(a['calendar_id'])}/import", body=_pick(a, ("ics", "dry_run")))),
    ("export_ics", "2.21.0: a calendar as ICS text.", _obj({"calendar_id": S_ID}, ["calendar_id"]),
     lambda api, a: api.call("GET", f"/event-calendars/{int(a['calendar_id'])}/export")),
    ("list_calendar_events", "2.21.0: the events in a date range (repeating ones expanded, at most 400 days): own + shared calendars and invitations.",
     _obj({"from": {"type": "string"}, "to": {"type": "string"}, "calendar_id": S_ID}, ["from", "to"]),
     lambda api, a: api.call("GET", "/events", {"from": a["from"], "to": a["to"], "calendar_id": a.get("calendar_id")})),
    ("get_event", "2.21.0: one event with its rule, changed / left-out dates and attendees.", _obj({"event_id": S_ID}, ["event_id"]),
     lambda api, a: api.call("GET", f"/events/{int(a['event_id'])}")),
    ("create_event", "2.21.0: create an event (all day or with times; repeat, reminders, attendees: people of this server, contacts, addresses).",
     _obj(EV_IN, ["title", "start"]), lambda api, a: api.call("POST", "/events", body=_pick(a, EV_KEYS))),
    ("update_event", "2.21.0: change an event; with occurrence only that date (title, location, description, all_day, start, end, status).",
     _obj({"event_id": S_ID, **OCC, **EV_IN}, ["event_id"]),
     lambda api, a: api.call("PATCH", f"/events/{int(a['event_id'])}", {"occurrence": a.get("occurrence")}, body=_pick(a, EV_KEYS))),
    ("delete_event", "2.21.0: delete an event (restorable for 30 days) or, with occurrence, leave out that date.",
     _obj({"event_id": S_ID, **OCC}, ["event_id"]),
     lambda api, a: api.call("DELETE", f"/events/{int(a['event_id'])}", {"occurrence": a.get("occurrence")})),
    ("restore_event", "2.21.0: restore a deleted event.", _obj({"event_id": S_ID}, ["event_id"]),
     lambda api, a: api.call("POST", f"/events/{int(a['event_id'])}/restore")),
    ("reply_to_event", "2.21.0: answer an invitation: accepted, tentative or declined.",
     _obj({"event_id": S_ID, "partstat": {"type": "string", "enum": ["accepted", "tentative", "declined", "needs-action"]}}, ["event_id", "partstat"]),
     lambda api, a: api.call("POST", f"/events/{int(a['event_id'])}/rsvp", body={"partstat": a["partstat"]})),
    ("add_preparation_task", "2.21.0: a task to prepare an event, due days_before its start, linked to it (needs tasks:write too).",
     _obj({"event_id": S_ID, "title": {"type": "string"}, "list_id": S_ID, "days_before": {"type": "integer", "minimum": 0, "maximum": 365}}, ["event_id"]),
     lambda api, a: api.call("POST", f"/events/{int(a['event_id'])}/prep-task", body=_pick(a, ("title", "list_id", "days_before")))),
    ("get_task_events", "2.21.0: the events a task prepares.", _obj({"task_id": S_ID}, ["task_id"]),
     lambda api, a: api.call("GET", f"/tasks/{int(a['task_id'])}/events")),
    ("list_address_books", "2.21.0 (module Contacts, scope contacts): the address books you see.", _obj({}),
     lambda api, a: api.call("GET", "/address-books")),
    ("create_address_book", "2.21.0: a new own address book.", _obj({"name": {"type": "string"}, "color": {"type": "string"}}, ["name"]),
     lambda api, a: api.call("POST", "/address-books", body=_pick(a, ("name", "color")))),
    ("update_address_book", "2.21.0: rename / recolour an address book, or choose the list for its birthdays (owner).",
     _obj({"book_id": S_ID, "name": {"type": "string"}, "color": {"type": "string"}, "birthdays_list_id": {"type": ["integer", "null"]}}, ["book_id"]),
     lambda api, a: api.call("PATCH", f"/address-books/{int(a['book_id'])}", body=_pick(a, ("name", "color", "birthdays_list_id")))),
    ("delete_address_book", "2.21.0: delete an address book with its contacts (owner).", _obj({"book_id": S_ID}, ["book_id"]),
     lambda api, a: api.call("DELETE", f"/address-books/{int(a['book_id'])}")),
    ("share_address_book", "2.21.0: share an address book: view or edit (owner). Contacts are personal data.",
     _obj({"book_id": S_ID, "user_id": S_ID, "role": {"type": "string", "enum": ["view", "edit"]}}, ["book_id", "user_id"]),
     lambda api, a: api.call("PUT", f"/address-books/{int(a['book_id'])}/members/{int(a['user_id'])}", body=_pick(a, ("role",)))),
    ("unshare_address_book", "2.21.0: stop sharing an address book (owner) or leave one.", _obj({"book_id": S_ID, "user_id": S_ID}, ["book_id", "user_id"]),
     lambda api, a: api.call("DELETE", f"/address-books/{int(a['book_id'])}/members/{int(a['user_id'])}")),
    ("import_vcards", "2.21.0: import the text of a .vcf file into an address book (the same UID is updated).",
     _obj({"book_id": S_ID, "vcf": {"type": "string"}}, ["book_id", "vcf"]),
     lambda api, a: api.call("POST", f"/address-books/{int(a['book_id'])}/import", body={"vcf": a["vcf"]})),
    ("export_vcards", "2.21.0: an address book as vCard text.", _obj({"book_id": S_ID}, ["book_id"]),
     lambda api, a: api.call("GET", f"/address-books/{int(a['book_id'])}/export")),
    ("search_contacts", "2.21.0: search contacts by name, company, e-mail, phone, address or group (q), optionally in one address book / group.",
     _obj({"q": {"type": "string"}, "book_id": S_ID, "group": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 500},
           "cursor": {"type": "string"}}),
     lambda api, a: api.call("GET", "/contacts", _pick(a, ("q", "book_id", "group", "limit", "cursor")))),
    ("get_contact", "2.21.0: one contact with its linked tasks and events.", _obj({"contact_id": S_ID}, ["contact_id"]),
     lambda api, a: api.call("GET", f"/contacts/{int(a['contact_id'])}")),
    ("create_contact", "2.21.0: create a contact (a name or a company).", _obj(CT_IN), lambda api, a: api.call("POST", "/contacts", body=_pick(a, CT_KEYS))),
    ("update_contact", "2.21.0: change a contact (only the fields given).", _obj({"contact_id": S_ID, **CT_IN}, ["contact_id"]),
     lambda api, a: api.call("PATCH", f"/contacts/{int(a['contact_id'])}", body=_pick(a, CT_KEYS))),
    ("delete_contact", "2.21.0: delete a contact.", _obj({"contact_id": S_ID}, ["contact_id"]),
     lambda api, a: api.call("DELETE", f"/contacts/{int(a['contact_id'])}")),
    ("link_contact", "2.21.0: link a contact to a task: waiting (the task waits on them), responsible (they do it outside Kalmido) or about "
                     "(needs tasks:write too).",
     _obj({"task_id": S_ID, "contact_id": S_ID, "kind": {"type": "string", "enum": ["waiting", "responsible", "about"]}}, ["task_id", "contact_id"]),
     lambda api, a: api.call("POST", f"/tasks/{int(a['task_id'])}/contacts", body=_pick(a, ("contact_id", "kind")))),
    ("unlink_contact", "2.21.0: remove a contact's link to a task (needs tasks:write too).", _obj({"task_id": S_ID, "contact_id": S_ID}, ["task_id", "contact_id"]),
     lambda api, a: api.call("DELETE", f"/tasks/{int(a['task_id'])}/contacts/{int(a['contact_id'])}")),
]
TOOL_MAP = {t[0]: t for t in TOOLS}


# ---------------------------------------------------------------- 2.15.0 (#479): the rest of the API as tools

def _without(a, *keys):
    return {k: v for k, v in a.items() if k not in keys}


def t_move_task(api, a):
    return api.call("POST", f"/tasks/{int(a['task_id'])}/move", body=_without(a, "task_id"))


def t_upload_attachment(api, a):
    """files = [{name, base64, mime?}] -> multipart POST /tasks/{id}/attachments."""
    files = []
    for f in a["files"]:
        if not isinstance(f, dict) or not isinstance(f.get("name"), str) or not isinstance(f.get("base64"), str):
            raise ApiError(400, "files: each entry needs name and base64")
        try:
            files.append((f["name"], f.get("mime") or "application/octet-stream", base64.b64decode(f["base64"], validate=True)))
        except ValueError:
            raise ApiError(400, f"files: {f['name']} is not valid base64") from None
    return api.call("POST", f"/tasks/{int(a['task_id'])}/attachments", multipart=({}, files))


def t_upload_project_file(api, a):
    try:
        data = base64.b64decode(a["base64"], validate=True)
    except ValueError:
        raise ApiError(400, "base64: not valid base64") from None
    return api.call("POST", f"/lists/{int(a['list_id'])}/files", multipart=({}, [(a["name"], a.get("mime") or "application/octet-stream", data)]))


def _id(a, k):
    return int(a[k])


def _q(v):
    return urllib.parse.quote(str(v), safe="")


TASK_PLACE = {"list_id": S_ID, "section_id": {"type": ["integer", "null"]}, "parent_id": {"type": ["integer", "null"]},
              "before_id": S_ID, "after_id": S_ID, "position": {"type": "string", "enum": ["top", "bottom"]}}
LIST_PROPS = {"name": {"type": "string"}, "color": {"type": "string"}, "folder": {"type": "string", "description": "path, e.g. Clients/Acme"},
              "view": {"type": "string", "enum": ["list", "kanban", "timeline"]}, "kind": {"type": "string", "enum": ["list", "project"]},
              "done_at_bottom": {"type": "boolean"}, "nag": {"type": "string"}, "day_hours": {"type": ["number", "null"]}}
HABIT_PROPS = {"name": {"type": "string"}, "color": {"type": "string"}, "goal": {"type": "integer", "minimum": 1},
               "days": {"type": "string", "description": "weekdays 1-7 (1 = Monday), e.g. 12345"}, "per_week": {"type": "integer", "minimum": 0},
               "remind_at": {"type": "string", "description": "HH:MM or empty"}}
FILES = {"type": "array", "minItems": 1, "maxItems": 10, "items": {"type": "object", "properties": {
    "name": {"type": "string"}, "base64": {"type": "string"}, "mime": {"type": "string"}}, "required": ["name", "base64"]}}
APPROVAL_NOTE = (" As an agent this waits for a person's approval: the answer is approval_required with a job; the result comes "
                 "as a job event.")

TOOLS += [
    ("get_me", "Your token: user, kind (agent / user), effective_scopes (what this token may do), switched-on modules, notifications.",
     _obj({}), lambda api, a: api.call("GET", "/me")),
    ("get_storage", "2.24.0: your storage quota: bytes used, the limit (null = unlimited), level ok | warn | high | full (uploads refused).",
     _obj({}), lambda api, a: api.call("GET", "/me/storage")),
    ("get_announcement", "2.24.0: the server's current notice (planned maintenance, announcements); {} when there is none.",
     _obj({}), lambda api, a: api.call("GET", "/announcement")),
    # ---- lists
    ("get_list", "One list with its sections and custom fields.", _obj({"list_id": S_ID}, ["list_id"]),
     lambda api, a: api.call("GET", f"/lists/{_id(a, 'list_id')}")),
    ("create_list", "Create a list (you become its owner). kind project = time tracking, dependencies, custom fields, overview. "
                    "project_type agency | software | private = a project of that built-in type (fields, ticket types); "
                    "sections true (2.27.0) = also the type's standard sections (default: none).",
     _obj({**LIST_PROPS, "project_type": {"type": "string", "enum": ["agency", "software", "private"]}, "sections": {"type": "boolean"}}, ["name"]),
     lambda api, a: api.call("POST", "/lists", body=a)),
    ("update_list", "Change a list: name, color, folder (moving your own list into another folder waits for approval), view, kind, "
                    "archived (true = archive), done_at_bottom, nag, day_hours, project_type (2.18.0, owner / list admins: "
                    "agency | software | private, null = none; switches on what the type needs, never deletes anything).",
     _obj({"list_id": S_ID, **LIST_PROPS, "archived": {"type": "boolean"},
           "project_type": {"type": ["string", "null"], "enum": ["agency", "software", "private", "", None]}}, ["list_id"]),
     lambda api, a: api.call("PATCH", f"/lists/{_id(a, 'list_id')}", body=_without(a, "list_id"))),
    ("delete_list", "Delete an ARCHIVED list for good (owner; archive it first with update_list archived=true); its tasks go to the "
                    "trash." + APPROVAL_NOTE, _obj({"list_id": S_ID}, ["list_id"]),
     lambda api, a: api.call("DELETE", f"/lists/{_id(a, 'list_id')}")),
    ("shift_list_dates", "Move every open date of a list by n days (negative = earlier).",
     _obj({"list_id": S_ID, "days": {"type": "integer"}}, ["list_id", "days"]),
     lambda api, a: api.call("POST", f"/lists/{_id(a, 'list_id')}/shift", body={"days": a["days"]})),
    ("list_members", "Owner and members of a list with their roles.", _obj({"list_id": S_ID}, ["list_id"]),
     lambda api, a: api.call("GET", f"/lists/{_id(a, 'list_id')}/members")),
    ("share_list", "Share a list with a person (role admin | edit | participant | view); owner / list admins." + APPROVAL_NOTE,
     _obj({"list_id": S_ID, "user_id": S_ID, "role": {"type": "string", "enum": ["admin", "edit", "participant", "view"]}}, ["list_id", "user_id"]),
     lambda api, a: api.call("PUT", f"/lists/{_id(a, 'list_id')}/members/{_id(a, 'user_id')}", body=_pick(a, ("role",)))),
    ("unshare_list", "Stop sharing a list with a person (or leave it: your own user id)." + APPROVAL_NOTE,
     _obj({"list_id": S_ID, "user_id": S_ID}, ["list_id", "user_id"]),
     lambda api, a: api.call("DELETE", f"/lists/{_id(a, 'list_id')}/members/{_id(a, 'user_id')}")),
    ("share_list_with_group", "Share a list with a group of people (role)." + APPROVAL_NOTE,
     _obj({"list_id": S_ID, "group_id": S_ID, "role": {"type": "string", "enum": ["admin", "edit", "participant", "view"]}}, ["list_id", "group_id"]),
     lambda api, a: api.call("PUT", f"/lists/{_id(a, 'list_id')}/groups/{_id(a, 'group_id')}", body=_pick(a, ("role",)))),
    ("unshare_list_from_group", "Stop sharing a list with a group." + APPROVAL_NOTE,
     _obj({"list_id": S_ID, "group_id": S_ID}, ["list_id", "group_id"]),
     lambda api, a: api.call("DELETE", f"/lists/{_id(a, 'list_id')}/groups/{_id(a, 'group_id')}")),
    ("get_group", "One group with its members.", _obj({"group_id": S_ID}, ["group_id"]),
     lambda api, a: api.call("GET", f"/groups/{_id(a, 'group_id')}")),
    # ---- sections
    ("list_sections", "Sections of a list in order.", _obj({"list_id": S_ID}, ["list_id"]),
     lambda api, a: api.call("GET", f"/lists/{_id(a, 'list_id')}/sections")),
    ("create_section", "Create a section in a list (at the end, or before section before_id).",
     _obj({"list_id": S_ID, "name": {"type": "string", "minLength": 1, "maxLength": 200}, "before_id": S_ID}, ["list_id", "name"]),
     lambda api, a: api.call("POST", f"/lists/{_id(a, 'list_id')}/sections", body=_without(a, "list_id"))),
    ("rename_section", "Rename a section.", _obj({"section_id": S_ID, "name": {"type": "string", "minLength": 1, "maxLength": 200}},
                                                 ["section_id", "name"]),
     lambda api, a: api.call("PATCH", f"/sections/{_id(a, 'section_id')}", body={"name": a["name"]})),
    ("reorder_sections", "Put the sections of a list in a new order (ids: every section of the list exactly once).",
     _obj({"list_id": S_ID, "ids": {"type": "array", "items": {"type": "integer"}}}, ["list_id", "ids"]),
     lambda api, a: api.call("PUT", f"/lists/{_id(a, 'list_id')}/sections/order", body={"ids": a["ids"]})),
    ("delete_section", "Delete a section; its tasks stay in the list without a section.", _obj({"section_id": S_ID}, ["section_id"]),
     lambda api, a: api.call("DELETE", f"/sections/{_id(a, 'section_id')}")),
    # ---- folders
    ("list_folders", "Your folders (paths like Clients/Acme) and how many lists they hold.", _obj({}),
     lambda api, a: api.call("GET", "/folders")),
    ("rename_folder", "Rename or move a folder (old -> new path); its lists go along." + APPROVAL_NOTE,
     _obj({"old": {"type": "string", "minLength": 1}, "new": {"type": "string", "minLength": 1}}, ["old", "new"]),
     lambda api, a: api.call("POST", "/folders/rename", body=a)),
    ("delete_folder", "Remove a folder; its lists move up a level." + APPROVAL_NOTE, _obj({"name": {"type": "string", "minLength": 1}}, ["name"]),
     lambda api, a: api.call("POST", "/folders/delete", body=a)),
    # ---- tasks
    ("move_task", "Move a task (with its subtasks): to another list / section / parent and to a place: before_id or after_id (a "
                  "sibling) or position top | bottom. Moving into another list needs edit rights there.",
     _obj({"task_id": S_ID, **TASK_PLACE}, ["task_id"]), t_move_task),
    ("batch_tasks", "Change many tasks at once (1-500 ids): action update (changes = task fields as in update_task) | complete | "
                    "reopen | wont_do | delete | restore. Tasks you may not change are skipped (errors). An agent's batch with 10 or "
                    "more tasks waits for a person's approval (approval_required + job).",
     _obj({"ids": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 500},
           "action": {"type": "string", "enum": ["update", "complete", "reopen", "wont_do", "delete", "restore"]},
           "changes": {"type": "object"}}, ["ids", "action"]),
     lambda api, a: api.call("POST", "/tasks/batch", body=a)),
    ("reopen_task", "Reopen a completed task.", _obj({"task_id": S_ID}, ["task_id"]),
     lambda api, a: api.call("POST", f"/tasks/{_id(a, 'task_id')}/reopen")),
    ("delete_task", "Move a task (with its subtasks) to the trash (restorable with restore_task).", _obj({"task_id": S_ID}, ["task_id"]),
     lambda api, a: api.call("DELETE", f"/tasks/{_id(a, 'task_id')}")),
    ("skip_occurrence", "Skip this occurrence of a repeating task: it moves to its next date without a completed copy.",
     _obj({"task_id": S_ID}, ["task_id"]), lambda api, a: api.call("POST", f"/tasks/{_id(a, 'task_id')}/skip")),
    ("take_task", "Take a task assigned to one of your groups: it becomes yours.", _obj({"task_id": S_ID}, ["task_id"]),
     lambda api, a: api.call("POST", f"/tasks/{_id(a, 'task_id')}/take")),
    ("list_subtasks", "The subtasks of a task.", _obj({"task_id": S_ID}, ["task_id"]),
     lambda api, a: api.call("GET", f"/tasks/{_id(a, 'task_id')}/subtasks")),
    ("add_subtask", "Add a subtask (same fields as create_task, without list_id / parent_id).",
     _obj({"task_id": S_ID, **{k: v for k, v in TASK_FIELDS.items() if k not in ("list_id", "parent_id")}}, ["task_id", "title"]),
     lambda api, a: api.call("POST", f"/tasks/{_id(a, 'task_id')}/subtasks", body=_without(a, "task_id"))),
    ("list_trash", "Tasks in the trash (newest first), optionally of one list.",
     _obj({"list_id": S_ID, "limit": {"type": "integer", "minimum": 1, "maximum": 500}, "cursor": {"type": "string"}}),
     lambda api, a: api.call("GET", "/trash", _pick(a, ("list_id", "limit", "cursor")))),
    ("restore_task", "Restore a task from the trash.", _obj({"task_id": S_ID}, ["task_id"]),
     lambda api, a: api.call("POST", f"/tasks/{_id(a, 'task_id')}/restore")),
    ("empty_trash", "Delete the trash for good (lists you own)." + APPROVAL_NOTE, _obj({}), lambda api, a: api.call("DELETE", "/trash")),
    ("list_tags", "Your personal tags and the list tags of the lists you see, with counts.", _obj({}), lambda api, a: api.call("GET", "/tags")),
    ("get_roadmap", "All projects / lists on one timeline (from, to as YYYY-MM-DD; projects_only, include_done).",
     _obj({"from": {"type": "string"}, "to": {"type": "string"}, "projects_only": {"type": "boolean"}, "include_done": {"type": "boolean"}}),
     lambda api, a: api.call("GET", "/roadmap", {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in a.items()})),
    # ---- dependencies
    ("get_dependencies", "What blocks a task (blocked_by: tasks to finish first) and what it blocks (blocking).", _obj({"task_id": S_ID}, ["task_id"]),
     lambda api, a: api.call("GET", f"/tasks/{_id(a, 'task_id')}/dependencies")),
    ("add_dependency", "task_id is blocked by blocked_by until that one is done (project lists; no cycles).", _obj({"task_id": S_ID, "blocked_by": S_ID}, ["task_id", "blocked_by"]),
     lambda api, a: api.call("POST", f"/tasks/{_id(a, 'task_id')}/dependencies", body={"blocked_by": a["blocked_by"]})),
    ("remove_dependency", "task_id is no longer blocked by blocked_by.", _obj({"task_id": S_ID, "blocked_by": S_ID}, ["task_id", "blocked_by"]),
     lambda api, a: api.call("DELETE", f"/tasks/{_id(a, 'task_id')}/dependencies/{_id(a, 'blocked_by')}")),
    # ---- custom fields
    ("list_fields", "Custom field definitions of a list (id, name, type, options). Values: the task's fields {field id: value}.",
     _obj({"list_id": S_ID}, ["list_id"]), lambda api, a: api.call("GET", f"/lists/{_id(a, 'list_id')}/fields")),
    ("create_field", "Create a custom field in a project list (owner): type text | number | date | select | person | url | checkbox "
                     "...; options for select: {options: [{id, label, color?}]}.",
     _obj({"list_id": S_ID, "name": {"type": "string", "minLength": 1}, "type": {"type": "string"}, "options": {"type": "object"},
           "pinned": {"type": "boolean"}}, ["list_id", "name", "type"]),
     lambda api, a: api.call("POST", f"/lists/{_id(a, 'list_id')}/fields", body=_without(a, "list_id"))),
    ("update_field", "Change a custom field (name, options, pinned, sort); the type stays.",
     _obj({"field_id": S_ID, "name": {"type": "string"}, "options": {"type": "object"}, "pinned": {"type": "boolean"}, "sort": {"type": "number"}},
          ["field_id"]),
     lambda api, a: api.call("PATCH", f"/fields/{_id(a, 'field_id')}", body=_without(a, "field_id"))),
    ("delete_field", "Delete a custom field with all its values." + APPROVAL_NOTE, _obj({"field_id": S_ID}, ["field_id"]),
     lambda api, a: api.call("DELETE", f"/fields/{_id(a, 'field_id')}")),
    # ---- list tags (shared by the members)
    ("create_list_tag", "Create a shared tag of a list.", _obj({"list_id": S_ID, "name": {"type": "string", "minLength": 1}, "color": {"type": "string"}},
                                                              ["list_id", "name"]),
     lambda api, a: api.call("POST", f"/lists/{_id(a, 'list_id')}/tags", body=_without(a, "list_id"))),
    ("update_list_tag", "Rename / recolor a list tag.", _obj({"list_id": S_ID, "tag_id": S_ID, "name": {"type": "string"}, "color": {"type": "string"}},
                                                           ["list_id", "tag_id"]),
     lambda api, a: api.call("PATCH", f"/lists/{_id(a, 'list_id')}/tags/{_id(a, 'tag_id')}", body=_without(a, "list_id", "tag_id"))),
    ("delete_list_tag", "Delete a list tag (it leaves every task).", _obj({"list_id": S_ID, "tag_id": S_ID}, ["list_id", "tag_id"]),
     lambda api, a: api.call("DELETE", f"/lists/{_id(a, 'list_id')}/tags/{_id(a, 'tag_id')}")),
    # ---- templates
    ("list_templates", "Your templates (task templates and list templates).", _obj({}), lambda api, a: api.call("GET", "/templates")),
    ("create_template", "Create a template from a task (task_id, with its subtasks), a list (list_id: sections + open tasks; relative "
                        "= dates from the project start) or data (kind + data); name optional.",
     _obj({"task_id": S_ID, "list_id": S_ID, "relative": {"type": "boolean"}, "kind": {"type": "string", "enum": ["task", "list"]},
           "data": {"type": "object"}, "name": {"type": "string"}}), lambda api, a: api.call("POST", "/templates", body=a)),
    ("update_template", "Rename a template or replace its data.", _obj({"template_id": S_ID, "name": {"type": "string"}, "data": {"type": "object"}},
                                                                       ["template_id"]),
     lambda api, a: api.call("PATCH", f"/templates/{_id(a, 'template_id')}", body=_without(a, "template_id"))),
    ("delete_template", "Delete a template.", _obj({"template_id": S_ID}, ["template_id"]),
     lambda api, a: api.call("DELETE", f"/templates/{_id(a, 'template_id')}")),
    ("apply_template", "Use a template: a task template creates the task in list_id / section_id (default the inbox); a list "
                       "template creates a new list (name, folder; start / end YYYY-MM-DD move its dates).",
     _obj({"template_id": S_ID, "list_id": S_ID, "section_id": S_ID, "name": {"type": "string"}, "folder": {"type": "string"},
           "start": {"type": "string"}, "end": {"type": "string"}}, ["template_id"]),
     lambda api, a: api.call("POST", f"/templates/{_id(a, 'template_id')}/apply", body=_without(a, "template_id"))),
    # ---- saved filters
    ("list_filters", "Your saved filters (name + rules).", _obj({}), lambda api, a: api.call("GET", "/filters")),
    ("create_filter", "Save a filter: rules as the app stores them (see docs/API.md).",
     _obj({"name": {"type": "string", "minLength": 1}, "rules": {"type": "object"}}, ["name"]), lambda api, a: api.call("POST", "/filters", body=a)),
    ("update_filter", "Change a saved filter.", _obj({"filter_id": S_ID, "name": {"type": "string"}, "rules": {"type": "object"}, "sort": {"type": "number"}},
                                                     ["filter_id"]),
     lambda api, a: api.call("PATCH", f"/filters/{_id(a, 'filter_id')}", body=_without(a, "filter_id"))),
    ("delete_filter", "Delete a saved filter.", _obj({"filter_id": S_ID}, ["filter_id"]),
     lambda api, a: api.call("DELETE", f"/filters/{_id(a, 'filter_id')}")),
    # ---- files + comments
    ("upload_attachment", "Attach files to a task: files = [{name, base64, mime?}] (at most 10, each within the server's upload limit).",
     _obj({"task_id": S_ID, "files": FILES}, ["task_id", "files"]), t_upload_attachment),
    ("delete_attachment", "Remove a file of a task (or of your comment).", _obj({"attachment_id": S_ID}, ["attachment_id"]),
     lambda api, a: api.call("DELETE", f"/attachments/{_id(a, 'attachment_id')}")),
    ("delete_chat_attachment", "Remove a file you sent in a chat.", _obj({"attachment_id": S_ID}, ["attachment_id"]),
     lambda api, a: api.call("DELETE", f"/chat-attachments/{_id(a, 'attachment_id')}")),
    ("update_comment", "Edit your comment (Markdown).", _obj({"comment_id": S_ID, "body": {"type": "string", "minLength": 1}}, ["comment_id", "body"]),
     lambda api, a: api.call("PATCH", f"/comments/{_id(a, 'comment_id')}", body={"body": a["body"]})),
    ("delete_comment", "Delete a comment (yours; list owners / admins any).", _obj({"comment_id": S_ID}, ["comment_id"]),
     lambda api, a: api.call("DELETE", f"/comments/{_id(a, 'comment_id')}")),
    # ---- project overview (write)
    ("set_project_overview", "Set the description (Markdown) of a project's overview.",
     _obj({"list_id": S_ID, "description": {"type": "string"}}, ["list_id", "description"]),
     lambda api, a: api.call("PATCH", f"/lists/{_id(a, 'list_id')}/overview", body={"description": a["description"]})),
    ("add_project_link", "Add a key link to a project's overview.", _obj({"list_id": S_ID, "title": {"type": "string"}, "url": {"type": "string"}},
                                                                       ["list_id", "url"]),
     lambda api, a: api.call("POST", f"/lists/{_id(a, 'list_id')}/links", body=_without(a, "list_id"))),
    ("update_project_link", "Change a key link.", _obj({"list_id": S_ID, "link_id": S_ID, "title": {"type": "string"}, "url": {"type": "string"}},
                                                       ["list_id", "link_id"]),
     lambda api, a: api.call("PATCH", f"/lists/{_id(a, 'list_id')}/links/{_id(a, 'link_id')}", body=_without(a, "list_id", "link_id"))),
    ("delete_project_link", "Remove a key link.", _obj({"list_id": S_ID, "link_id": S_ID}, ["list_id", "link_id"]),
     lambda api, a: api.call("DELETE", f"/lists/{_id(a, 'list_id')}/links/{_id(a, 'link_id')}")),
    ("reorder_project_links", "Put the key links in a new order (every link id once).",
     _obj({"list_id": S_ID, "ids": {"type": "array", "items": {"type": "integer"}}}, ["list_id", "ids"]),
     lambda api, a: api.call("PUT", f"/lists/{_id(a, 'list_id')}/links/order", body={"ids": a["ids"]})),
    ("add_milestone", "Add a milestone (name, day YYYY-MM-DD) to a project.",
     _obj({"list_id": S_ID, "name": {"type": "string", "minLength": 1}, "day": {"type": "string"}, "done": {"type": "boolean"}}, ["list_id", "name", "day"]),
     lambda api, a: api.call("POST", f"/lists/{_id(a, 'list_id')}/milestones", body=_without(a, "list_id"))),
    ("update_milestone", "Change a milestone (name, day, done).",
     _obj({"list_id": S_ID, "milestone_id": S_ID, "name": {"type": "string"}, "day": {"type": "string"}, "done": {"type": "boolean"}},
          ["list_id", "milestone_id"]),
     lambda api, a: api.call("PATCH", f"/lists/{_id(a, 'list_id')}/milestones/{_id(a, 'milestone_id')}", body=_without(a, "list_id", "milestone_id"))),
    ("delete_milestone", "Remove a milestone.", _obj({"list_id": S_ID, "milestone_id": S_ID}, ["list_id", "milestone_id"]),
     lambda api, a: api.call("DELETE", f"/lists/{_id(a, 'list_id')}/milestones/{_id(a, 'milestone_id')}")),
    ("set_project_status", "Post a status update of a project: status on_track | at_risk | off_track | on_hold | complete (empty = none) "
                           "and a short note; the members are told.",
     _obj({"list_id": S_ID, "status": {"type": "string", "enum": ["on_track", "at_risk", "off_track", "on_hold", "complete", ""]},
           "note": {"type": "string", "maxLength": 500}}, ["list_id", "status"]),
     lambda api, a: api.call("PUT", f"/lists/{_id(a, 'list_id')}/status", body=_without(a, "list_id"))),
    ("list_project_files", "Project files of a list (read them with get_attachment source project).", _obj({"list_id": S_ID}, ["list_id"]),
     lambda api, a: api.call("GET", f"/lists/{_id(a, 'list_id')}/files")),
    ("upload_project_file", "Add a file to a project's overview (name, base64, mime?).",
     _obj({"list_id": S_ID, "name": {"type": "string", "minLength": 1}, "base64": {"type": "string"}, "mime": {"type": "string"}},
          ["list_id", "name", "base64"]), t_upload_project_file),
    ("delete_project_file", "Remove a project file.", _obj({"list_id": S_ID, "file_id": S_ID}, ["list_id", "file_id"]),
     lambda api, a: api.call("DELETE", f"/lists/{_id(a, 'list_id')}/files/{_id(a, 'file_id')}")),
    # ---- time tracking
    ("get_timer", "The running timer (null = none).", _obj({}), lambda api, a: api.call("GET", "/time/timer")),
    ("start_timer", "Start the timer on a task (or a project list); a running one stops.", _obj({"task_id": S_ID, "list_id": S_ID, "note": {"type": "string"}}),
     lambda api, a: api.call("POST", "/time/timer", body=a)),
    ("stop_timer", "Stop the running timer.", _obj({}), lambda api, a: api.call("DELETE", "/time/timer")),
    ("list_time_entries", "Time entries (from / to YYYY-MM-DD, default the last 7 days; scope mine | all; list_id, task_id).",
     _obj({"from": {"type": "string"}, "to": {"type": "string"}, "scope": {"type": "string", "enum": ["mine", "all"]}, "list_id": S_ID,
           "task_id": S_ID, "limit": {"type": "integer", "minimum": 1, "maximum": 500}, "cursor": {"type": "string"}}),
     lambda api, a: api.call("GET", "/time/entries", a)),
    ("add_time_entry", "Add a time entry: task_id or list_id, start (YYYY-MM-DDTHH:MM), end or minutes, note.",
     _obj({"task_id": S_ID, "list_id": S_ID, "start": {"type": "string"}, "end": {"type": "string"}, "minutes": {"type": "number"},
           "note": {"type": "string"}}, ["start"]), lambda api, a: api.call("POST", "/time/entries", body=a)),
    ("update_time_entry", "Change your time entry.", _obj({"entry_id": S_ID, "start": {"type": "string"}, "end": {"type": "string"},
                                                           "minutes": {"type": "number"}, "note": {"type": "string"}, "task_id": S_ID, "list_id": S_ID},
                                                          ["entry_id"]),
     lambda api, a: api.call("PATCH", f"/time/entries/{_id(a, 'entry_id')}", body=_without(a, "entry_id"))),
    ("delete_time_entry", "Delete your time entry.", _obj({"entry_id": S_ID}, ["entry_id"]),
     lambda api, a: api.call("DELETE", f"/time/entries/{_id(a, 'entry_id')}")),
    # ---- habits
    ("list_habits", "Your habits with today's count and the last 30 days.", _obj({}), lambda api, a: api.call("GET", "/habits")),
    ("create_habit", "Create a habit.", _obj(HABIT_PROPS, ["name"]), lambda api, a: api.call("POST", "/habits", body=a)),
    ("update_habit", "Change a habit (archived = true to archive).", _obj({"habit_id": S_ID, **HABIT_PROPS, "archived": {"type": "boolean"}}, ["habit_id"]),
     lambda api, a: api.call("PATCH", f"/habits/{_id(a, 'habit_id')}", body=_without(a, "habit_id"))),
    ("delete_habit", "Delete a habit with its history.", _obj({"habit_id": S_ID}, ["habit_id"]),
     lambda api, a: api.call("DELETE", f"/habits/{_id(a, 'habit_id')}")),
    ("check_in_habit", "Check in a habit (date YYYY-MM-DD, default today; count = absolute count, default one more; note).",
     _obj({"habit_id": S_ID, "date": {"type": "string"}, "count": {"type": "integer", "minimum": 0}, "note": {"type": "string"}}, ["habit_id"]),
     lambda api, a: api.call("POST", f"/habits/{_id(a, 'habit_id')}/checkin", body=_without(a, "habit_id"))),
    # ---- News, agents, export
    ("list_news", "Your News (mentions, assignments, comments, shares, approvals ...), newest first; filter mentions | me.",
     _obj({"filter": {"type": "string", "enum": ["mentions", "me"]}}), lambda api, a: api.call("GET", "/news", a)),
    ("mark_news_read", "Mark News read: ids, or all=true.", _obj({"ids": {"type": "array", "items": {"type": "integer"}}, "all": {"type": "boolean"}}),
     lambda api, a: api.call("POST", "/news/read", body=a)),
    ("list_agents", "The agents in your lists with their state and running jobs.", _obj({}), lambda api, a: api.call("GET", "/agents")),
    ("export_data", "Everything the token's user owns as JSON (lists, tasks, comments, time, habits ...). Large.", _obj({}),
     lambda api, a: api.call("GET", "/export", timeout=120)),
]
TOOL_MAP = {t[0]: t for t in TOOLS}

# 2.15.0 (#479): the scope each tool needs (the same as its REST call, see GET /api/v1/openapi.json x-kalmido-scope);
# tools/list shows only the tools the token may use (GET /me effective_scopes; agent = agent tokens only).
# 2.17.0 (#442 #419): notes of lists and the team chat
NOTE_IN = {"title": {"type": "string", "maxLength": 300}, "body": {"type": "string", "description": "Markdown; #123 links task 123"},
           "tags": {"type": "array", "items": {"type": "string"}}, "pinned": {"type": "boolean"}}
TOOLS += [
    ("list_notes", "2.17.0: the notes of a list (Markdown documents next to its tasks: meeting notes, briefings, decisions), "
                   "with their text. Participants of a list see none.",
     _obj({"list_id": S_ID}, ["list_id"]), lambda api, a: api.call("GET", f"/lists/{int(a['list_id'])}/notes")),
    ("search_notes", "2.17.0: find notes (all words in title, text or tags), optionally in one list; results without the full text "
                     "(get_note for it).",
     _obj({"q": {"type": "string"}, "list_id": S_ID}), lambda api, a: api.call("GET", "/notes", _pick(a, ("q", "list_id")))),
    ("get_note", "2.17.0: one note with its text.", _obj({"note_id": S_ID}, ["note_id"]), lambda api, a: api.call("GET", f"/notes/{int(a['note_id'])}")),
    ("create_note", "2.17.0: write a note in a list (owner, list admins, members).", _obj({"list_id": S_ID, **NOTE_IN}, ["list_id", "title"]),
     lambda api, a: api.call("POST", f"/lists/{int(a['list_id'])}/notes", body=_pick(a, ("title", "body", "tags", "pinned")))),
    ("update_note", "2.17.0: change a note; list_id moves it; expect_updated_at (from get_note) refuses with 409 when someone changed it "
                    "in between (the answer carries the current note).",
     _obj({"note_id": S_ID, **NOTE_IN, "list_id": S_ID, "expect_updated_at": {"type": "string"}}, ["note_id"]),
     lambda api, a: api.call("PATCH", f"/notes/{int(a['note_id'])}", body=_pick(a, ("title", "body", "tags", "pinned", "list_id", "expect_updated_at")))),
    ("delete_note", "2.17.0: delete a note.", _obj({"note_id": S_ID}, ["note_id"]), lambda api, a: api.call("DELETE", f"/notes/{int(a['note_id'])}")),
    ("list_team_chats", "2.17.0: the team chat conversations you take part in: one channel per shared list you are a member of "
                        "(people + agents), with unread counts. Agents cannot open direct messages; people talk to you in your own "
                        "chat (send_chat). You get the event team_message when someone @mentions you in a channel.",
     _obj({}), lambda api, a: api.call("GET", "/team/rooms")),
    ("read_team_chat", "2.17.0: messages of a team chat conversation, oldest first; before = a message id for older ones. Mentions "
                       "are <@user id>.",
     _obj({"room_id": S_ID, "before": S_ID, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["room_id"]),
     lambda api, a: api.call("GET", f"/team/rooms/{int(a['room_id'])}/messages", _pick(a, ("before", "limit")))),
    ("post_team_message", "2.17.0: write in a team chat channel (Markdown; mention people as <@user id>; task_id links a task).",
     _obj({"room_id": S_ID, "body": {"type": "string", "maxLength": 8000}, "task_id": S_ID}, ["room_id", "body"]),
     lambda api, a: api.call("POST", f"/team/rooms/{int(a['room_id'])}/messages", body=_pick(a, ("body", "task_id")))),
    ("edit_team_message", "2.17.0: change your own team chat message.", _obj({"message_id": S_ID, "body": {"type": "string"}}, ["message_id", "body"]),
     lambda api, a: api.call("PATCH", f"/team/messages/{int(a['message_id'])}", body={"body": a["body"]})),
    ("delete_team_message", "2.17.0: delete your own team chat message.", _obj({"message_id": S_ID}, ["message_id"]),
     lambda api, a: api.call("DELETE", f"/team/messages/{int(a['message_id'])}")),
    ("react_team_message", "2.17.0: toggle a reaction (up, down, heart or one emoji) on a team chat message; on=true/false sets it.",
     _obj({"message_id": S_ID, "emoji": {"type": "string"}, "on": {"type": "boolean"}}, ["message_id", "emoji"]),
     lambda api, a: api.call("POST", f"/team/messages/{int(a['message_id'])}/reactions", body=_pick(a, ("emoji", "on")))),
    ("mark_team_chat_read", "2.17.0: mark a team chat conversation read (up to last_id, default the newest).",
     _obj({"room_id": S_ID, "last_id": S_ID}, ["room_id"]), lambda api, a: api.call("POST", f"/team/rooms/{int(a['room_id'])}/read", body=_pick(a, ("last_id",)))),
]


# 2.19.0 (#653): the module Family
KID = {"kid_id": S_ID}
REWARD_IN = {"title": {"type": "string", "maxLength": 200}, "cost": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "stars"},
             "emoji": {"type": "string", "maxLength": 16}, "once": {"type": "boolean", "description": "gone after one redemption"}}
TOOLS += [
    ("get_family", "2.19.0 (module Family): upcoming birthdays + anniversaries (with the age), household deadlines, whose turn it is in "
                   "the rotations, the meal plan of a week (week = any day of it, default this week), the shopping lists and the kids "
                   "you look after (stars, rewards, requests).",
     _obj({"week": {"type": "string", "description": "YYYY-MM-DD"}}), lambda api, a: api.call("GET", "/family", _pick(a, ("week",)))),
    ("add_occasion", "2.19.0: a birthday or anniversary as a yearly task (age from the year, reminders lead_days before and on the day, "
                     "gift ideas as subtasks); date YYYY-MM-DD or --MM-DD; list_id default: the first Birthdays list (created when missing).",
     _obj({"name": {"type": "string"}, "kind": {"type": "string", "enum": ["birthday", "anniversary"]}, "date": {"type": "string"},
           "year": {"type": ["integer", "null"]}, "lead_days": {"type": "integer", "minimum": 0, "maximum": 365}, "list_id": S_ID,
           "gifts": STRS}, ["name", "date"]),
     lambda api, a: api.call("POST", "/family/occasions", body=_pick(a, ("name", "kind", "date", "year", "lead_days", "list_id", "gifts")))),
    ("list_deadline_types", "2.19.0: the built-in household deadline types (passport, ID card, car inspection, insurance, contract, other) "
                            "with their default lead days, repeat and notice period.",
     _obj({}), lambda api, a: api.call("GET", "/family/deadline-types")),
    ("add_deadline", "2.19.0: a household deadline task: due = expires minus notice_months, a deadline with reminders lead_days before "
                     "and on the day; list_id default: the first Household list. Link a Paperless document in the app afterwards.",
     _obj({"type": {"type": "string", "enum": ["passport", "id_card", "car", "insurance", "contract", "other"]}, "expires": {"type": "string"},
           "who": {"type": "string"}, "notice_months": {"type": "integer", "minimum": 0, "maximum": 24},
           "lead_days": {"type": "integer", "minimum": 0, "maximum": 365}, "title": {"type": "string"}, "list_id": S_ID}, ["expires"]),
     lambda api, a: api.call("POST", "/family/deadlines", body=_pick(a, ("type", "expires", "who", "notice_months", "lead_days", "title", "list_id")))),
    ("ingredients_to_shopping", "2.19.0: put the ingredients of a meal (the list in its notes, or items) on a shopping list; open items "
                                "with the same name are not added twice.",
     _obj({"task_id": S_ID, "list_id": S_ID, "items": STRS}, ["task_id"]),
     lambda api, a: api.call("POST", f"/tasks/{int(a['task_id'])}/to-shopping", body=_pick(a, ("list_id", "items")))),
    ("add_shop_areas", "2.19.0: make a list a shopping list and add the default shop areas (sections); a new item goes to the area it "
                       "had last time.",
     _obj({"list_id": S_ID}, ["list_id"]), lambda api, a: api.call("POST", f"/lists/{int(a['list_id'])}/shop-areas")),
    ("list_packing_templates", "2.19.0: the built-in packing list templates.", _obj({}), lambda api, a: api.call("GET", "/family/packing")),
    ("create_packing_list", "2.19.0: a new packing list from a template (done items stay at the bottom, reusable).",
     _obj({"template": {"type": "string", "enum": ["holiday", "pool", "daycare", "camping", "business"]}, "name": {"type": "string"}}, ["template"]),
     lambda api, a: api.call("POST", "/family/packing", body=_pick(a, ("template", "name")))),
    ("list_kids", "2.19.0: the kid accounts you look after (or yourself, a kid) with stars, rewards and the history.",
     _obj({}), lambda api, a: api.call("GET", "/family/kids")),
    ("give_stars", "2.19.0: give (or correct) a kid's stars by hand (parents).", _obj({**KID, "delta": {"type": "integer"}, "note": {"type": "string"}}, ["kid_id", "delta"]),
     lambda api, a: api.call("POST", f"/family/kids/{int(a['kid_id'])}/stars", body=_pick(a, ("delta", "note")))),
    ("add_reward", "2.19.0: offer a kid a reward for stars (parents).", _obj({**KID, **REWARD_IN}, ["kid_id", "title", "cost"]),
     lambda api, a: api.call("POST", f"/family/kids/{int(a['kid_id'])}/rewards", body=_pick(a, ("title", "cost", "emoji", "once")))),
    ("update_reward", "2.19.0: change a reward (parents).", _obj({"reward_id": S_ID, **REWARD_IN}, ["reward_id"]),
     lambda api, a: api.call("PATCH", f"/family/rewards/{int(a['reward_id'])}", body=_pick(a, ("title", "cost", "emoji", "once")))),
    ("delete_reward", "2.19.0: delete a reward (parents).", _obj({"reward_id": S_ID}, ["reward_id"]),
     lambda api, a: api.call("DELETE", f"/family/rewards/{int(a['reward_id'])}")),
    ("request_reward", "2.19.0: a kid asks for a reward it has the stars for.", _obj({"reward_id": S_ID}, ["reward_id"]),
     lambda api, a: api.call("POST", f"/family/rewards/{int(a['reward_id'])}/request")),
    ("decide_reward", "2.19.0: approve (the stars are taken) or decline a reward (parents).", _obj({"reward_id": S_ID, "approve": {"type": "boolean"}}, ["reward_id", "approve"]),
     lambda api, a: api.call("POST", f"/family/rewards/{int(a['reward_id'])}/decide", body={"approve": a["approve"]})),
]
# 2.22.0 (#663): Home & life (each module switched on by the token's user; health + journal need the scope "private")
D = {"type": "string", "description": "YYYY-MM-DD"}
LEAD = {"type": "integer", "minimum": 0, "maximum": 365}
TOOLS += [
    ("get_life", "2.22.0 (Home & life): the switched-on modules with the contracts (cost per month / year, the last day to cancel), "
                 "devices + upkeep, contacts to get in touch with, health entries (scope private), trips and the reading list.",
     _obj({}), lambda api, a: api.call("GET", "/life")),
    ("list_upkeep_presets", "2.22.0: suggested upkeep tasks (heating, smoke detectors, tyres ...) with their interval.",
     _obj({}), lambda api, a: api.call("GET", "/life/upkeep-presets")),
    ("add_contract", "2.22.0: a contract / subscription: a task due on the last day to cancel (ends minus the notice period), repeating with "
                     "the renewal (renew_months, 0 = it ends), reminders lead_days before and on the day. Link the document from Paperless in the app.",
     _obj({"name": {"type": "string"}, "ends": {**D, "description": "End of the current term, YYYY-MM-DD"}, "provider": {"type": "string"},
           "cost": {"type": "number"}, "per": {"type": "string", "enum": ["month", "quarter", "year"]}, "notice": {"type": "integer", "minimum": 0, "maximum": 365},
           "notice_unit": {"type": "string", "enum": ["d", "w", "m"]}, "renew_months": {"type": "integer", "minimum": 0, "maximum": 120},
           "lead_days": LEAD, "start": D, "account": {"type": "string"}, "list_id": S_ID}, ["name", "ends"]),
     lambda api, a: api.call("POST", "/life/contracts", body=_pick(a, ("name", "ends", "provider", "cost", "per", "notice", "notice_unit", "renew_months",
                                                                       "lead_days", "start", "account", "list_id")))),
    ("add_device", "2.22.0: a device with its warranty (a task due when the warranty ends).",
     _obj({"name": {"type": "string"}, "model": {"type": "string"}, "bought": D, "warranty": D, "lead_days": LEAD, "list_id": S_ID}, ["name"]),
     lambda api, a: api.call("POST", "/life/devices", body=_pick(a, ("name", "model", "bought", "warranty", "lead_days", "list_id")))),
    ("add_upkeep", "2.22.0: a repeating upkeep task (every n months, next = the first time).",
     _obj({"title": {"type": "string"}, "every_months": {"type": "integer", "minimum": 1, "maximum": 120}, "next": D, "item": {"type": "string"},
           "lead_days": LEAD, "list_id": S_ID}, ["title", "every_months"]),
     lambda api, a: api.call("POST", "/life/upkeep", body=_pick(a, ("title", "every_months", "next", "item", "lead_days", "list_id")))),
    ("add_health_entry", "2.22.0 (scope private): an appointment, a check-up / vaccination (repeating every_months) or medication (times: "
                         "a daily task per HH:MM) in a private health list.",
     _obj({"type": {"type": "string", "enum": ["appointment", "checkup", "vaccination", "medication"]}, "title": {"type": "string"},
           "who": {"type": "string"}, "date": D, "time": {"type": "string", "description": "HH:MM"},
           "every_months": {"type": "integer", "minimum": 0, "maximum": 240}, "times": STRS, "lead_days": LEAD, "list_id": S_ID}, ["type", "title"]),
     lambda api, a: api.call("POST", "/life/health", body=_pick(a, ("type", "title", "who", "date", "time", "every_months", "times", "lead_days", "list_id")))),
    ("create_trip", "2.22.0: a trip: a list with bookings, things to do before leaving and a packing list (packing = a template key, '' = "
                    "none); event = also an all-day event (module Events).",
     _obj({"name": {"type": "string"}, "from": D, "to": D, "where": {"type": "string"}, "packing": {"type": "string"},
           "event": {"type": "boolean"}, "folder": {"type": "string"}}, ["name", "from", "to"]),
     lambda api, a: api.call("POST", "/life/trips", body=_pick(a, ("name", "from", "to", "where", "packing", "event", "folder")))),
    ("get_review", "2.22.0: the day or week in review: done, still open, moved, the next seven days (the journal only with the scope private).",
     _obj({"period": {"type": "string", "enum": ["day", "week"]}, "date": D}), lambda api, a: api.call("GET", "/life/review", _pick(a, ("period", "date")))),
    ("write_journal", "2.22.0 (scope private): write the journal entry of a day (text, mood 1-5; empty = deleted).",
     _obj({"day": D, "text": {"type": "string"}, "mood": {"type": ["integer", "null"], "minimum": 1, "maximum": 5}}, ["day"]),
     lambda api, a: api.call("PUT", f"/life/journal/{a['day']}", body=_pick(a, ("text", "mood")))),
    ("set_contact_care", "2.22.0 (scope contacts): stay in touch with a contact: every_days (0 = off), last (YYYY-MM-DD or \"today\"), a note.",
     _obj({"contact_id": S_ID, "every_days": {"type": "integer", "minimum": 0}, "last": {"type": "string"}, "note": {"type": "string"}}, ["contact_id"]),
     lambda api, a: api.call("PUT", f"/contacts/{int(a['contact_id'])}/care", body=_pick(a, ("every_days", "last", "note")))),
    ("comment_typing", "2.22.0 (#693): \"<name> is writing …\" in a task's comments for 8 s: send it before answering a comment (again while "
                       "writing), then post the comment.", _obj({"task_id": S_ID}, ["task_id"]),
     lambda api, a: api.call("POST", f"/tasks/{int(a['task_id'])}/typing")),
    ("sync_read_later", "2.22.0: fetch new bookmarks from the user's own Karakeep connection now (and archive the ticked ones).",
     _obj({}), lambda api, a: api.call("POST", "/life/karakeep/sync")),
]
# 2.23.0 (#463): package "Team, family, clients": clients, workload, approvals, forms
_CLIENT = {"name": {"type": "string"}, "icon": {"type": "string"}, "color": {"type": "string"}, "contact": {"type": "string"},
           "email": {"type": "string"}, "phone": {"type": "string"}, "address": {"type": "string"}, "note": {"type": "string"},
           "rate": {"type": "number"}, "budget_h": {"type": "number"}, "budget_amount": {"type": "number"}, "org_id": {"type": "integer"},
           "archived": {"type": "boolean"}}
_FORM = {"title": {"type": "string"}, "intro": {"type": "string"}, "access": {"type": "string", "enum": ["org", "public"]},
         "section_id": {"type": "integer"}, "ask_email": {"type": "boolean"}}
TOOLS += [
    ("list_clients", "2.23.0 (module clients): the clients of the user's organisation with their lists, hours (this month / in total), "
                     "amounts and budget level (ok / warn at 80 % / over).", _obj({"month": {"type": "string", "description": "YYYY-MM"},
                                                                                   "archived": {"type": "boolean"}}),
     lambda api, a: api.call("GET", "/clients", {**_pick(a, ("month",)), **({"archived": "1"} if a.get("archived") else {})})),
    ("get_client", "2.23.0: one client with estimate vs. actual per list (the tasks' durations next to the tracked time).",
     _obj({"client_id": S_ID, "month": {"type": "string"}}, ["client_id"]),
     lambda api, a: api.call("GET", f"/clients/{int(a['client_id'])}", _pick(a, ("month",)))),
    ("create_client", "2.23.0: add a client (contact, hourly rate for lists without one, budget in hours and / or money).",
     _obj(_CLIENT, ["name"]), lambda api, a: api.call("POST", "/clients", body=_pick(a, tuple(_CLIENT)))),
    ("update_client", "2.23.0: change a client.", _obj({"client_id": S_ID, **_CLIENT}, ["client_id"]),
     lambda api, a: api.call("PATCH", f"/clients/{int(a['client_id'])}", body=_pick(a, tuple(_CLIENT)))),
    ("delete_client", "2.23.0: delete a client (its creator or an admin); its lists stay.", _obj({"client_id": S_ID}, ["client_id"]),
     lambda api, a: api.call("DELETE", f"/clients/{int(a['client_id'])}")),
    ("get_workload", "2.23.0 (module workload): planned hours per person and week against their capacity (open assigned tasks, "
                     "their duration as the estimate).", _obj({"start": D, "weeks": {"type": "integer", "minimum": 1, "maximum": 12},
                                                               "org": {"type": "integer"}}),
     lambda api, a: api.call("GET", "/workload", _pick(a, ("start", "weeks", "org")))),
    ("request_approval", "2.23.0: ask a person of the task's list to approve it (action request + approver_id; the task is assigned to "
                         "them) or withdraw the request (action cancel). Only people decide; agents never approve.",
     _obj({"task_id": S_ID, "action": {"type": "string", "enum": ["request", "cancel"]}, "approver_id": {"type": "integer"},
           "note": {"type": "string"}}, ["task_id", "action"]),
     lambda api, a: api.call("POST", f"/tasks/{int(a['task_id'])}/approval", body=_pick(a, ("action", "approver_id", "note")))),
    ("list_forms", "2.23.0 (module forms): the forms of a list (owner / list admins) with their links.", _obj({"list_id": S_ID}, ["list_id"]),
     lambda api, a: api.call("GET", f"/lists/{int(a['list_id'])}/forms")),
    ("create_form", "2.23.0: a form for a list: a link whose page creates a task (subject, description, name, e-mail); access org = "
                    "signed-in people of the organisation, public = anyone with the link.", _obj({"list_id": S_ID, **_FORM}, ["list_id", "title"]),
     lambda api, a: api.call("POST", f"/lists/{int(a['list_id'])}/forms", body=_pick(a, tuple(_FORM)))),
    ("update_form", "2.23.0: change a form (enabled false = closed; regenerate true = a new link).",
     _obj({"form_id": S_ID, **_FORM, "enabled": {"type": "boolean"}, "regenerate": {"type": "boolean"}}, ["form_id"]),
     lambda api, a: api.call("PATCH", f"/forms/{int(a['form_id'])}", body=_pick(a, (*_FORM, "enabled", "regenerate")))),
    ("delete_form", "2.23.0: delete a form (tasks it created stay).", _obj({"form_id": S_ID}, ["form_id"]),
     lambda api, a: api.call("DELETE", f"/forms/{int(a['form_id'])}")),
]
TOOL_MAP = {t[0]: t for t in TOOLS}


TOOL_SCOPES = {
    "agent": ("get_agent", "react_to_chat", "set_status", "list_events", "wait_for_events", "list_jobs", "create_job", "get_job",
              "submit_proposal", "propose_to_other_topic", "update_job", "list_chats", "chat_typing", "send_chat", "report_usage", "get_usage"),
    "tasks:write": ("add_contract", "add_device", "add_upkeep", "sync_read_later", "add_occasion", "add_deadline", "ingredients_to_shopping", "give_stars", "add_reward", "update_reward", "request_reward",
                    "decide_reward", "create_note", "update_note", "create_task", "update_task", "complete_task", "set_waiting", "clear_waiting", "tidy_task", "move_task", "batch_tasks",
                    "reopen_task", "skip_occurrence", "take_task", "add_subtask", "add_dependency", "remove_dependency", "create_habit",
                    "update_habit", "check_in_habit", "shift_list_dates", "request_approval"),
    "comments": ("comment_typing", "post_team_message", "edit_team_message", "delete_team_message", "react_team_message", "mark_team_chat_read", "add_comment", "react", "request_merge_approval", "request_integration_approval", "request_deploy_approval", "update_comment", "delete_comment", "mark_news_read",
                 "delete_chat_attachment"),
    "structure": ("create_trip", "add_shop_areas", "create_packing_list", "set_list_columns", "create_list", "update_list", "share_list", "unshare_list", "share_list_with_group",
                  "unshare_list_from_group", "create_section", "rename_section", "reorder_sections", "rename_folder", "delete_folder",
                  "create_field", "update_field", "create_list_tag", "update_list_tag", "delete_list_tag", "create_template",
                  "update_template", "apply_template", "create_filter", "update_filter", "set_project_overview", "add_project_link",
                  "update_project_link", "delete_project_link", "reorder_project_links", "set_project_status", "add_milestone", "update_milestone",
                  "delete_milestone", "create_client", "update_client", "delete_client", "create_form", "update_form", "delete_form"),
    "delete": ("delete_reward", "delete_note", "delete_list", "delete_section", "delete_task", "restore_task", "empty_trash", "delete_field", "delete_template",
               "delete_filter", "delete_habit"),
    "attachments:read": ("get_attachment",),
    "attachments:write": ("upload_attachment", "delete_attachment", "upload_project_file", "delete_project_file"),
    "time": ("start_timer", "stop_timer", "add_time_entry", "update_time_entry", "delete_time_entry"),
    "export": ("export_data",),
    "calendar": ("list_event_calendars", "create_event_calendar", "update_event_calendar", "delete_event_calendar", "share_event_calendar",
                 "unshare_event_calendar", "import_ics", "export_ics", "list_calendar_events", "get_event", "create_event", "update_event", "delete_event",
                 "restore_event", "reply_to_event", "add_preparation_task", "get_task_events"),
    "contacts": ("list_address_books", "create_address_book", "update_address_book", "delete_address_book", "share_address_book",
                 "unshare_address_book", "import_vcards", "export_vcards", "search_contacts", "get_contact", "create_contact", "update_contact",
                 "delete_contact", "link_contact", "unlink_contact", "set_contact_care"),
    "private": ("add_health_entry", "write_journal"),
}
TOOL_SCOPE = {n: s for s, names in TOOL_SCOPES.items() for n in names}   # every other tool: read
ALL_SCOPES = ("read", "tasks:write", "comments", "structure", "delete", "attachments:read", "attachments:write", "time", "export", "calendar", "contacts",
              "private")
_ME = {"at": 0.0, "v": None}
ME_TTL = 300  # s: a changed scope shows in tools/list within 5 minutes (a call is refused by the server at once anyway)


def token_scopes(api):
    """(effective scopes, is agent) of the token, from GET /me, cached for ME_TTL; None when unknown (older server,
    unreachable): then every tool is listed and the server decides."""
    now = time.monotonic()
    if not _ME["at"] or now - _ME["at"] > ME_TTL:
        try:
            me = api.call("GET", "/me")
            t = me.get("token") if isinstance(me, dict) else None
            sc = (t.get("effective_scopes") or t.get("scopes")) if isinstance(t, dict) else None
            if not isinstance(sc, list) or not sc:
                _ME["v"] = None
            else:
                if "write" in sc:  # a server before 2.15: read + write = everything
                    sc = list(ALL_SCOPES)
                _ME["v"] = (set(sc), me.get("kind") == "agent")
        except ApiError:
            _ME["v"] = None
        _ME["at"] = now
    return _ME["v"]


def tool_allowed(api, name):
    ts = token_scopes(api)
    if ts is None:
        return True
    sc, agent = ts
    need = TOOL_SCOPE.get(name, "read")
    return agent if need == "agent" else need in sc


def _check_args(schema, a):
    if not isinstance(a, dict):
        return "arguments must be an object"
    props = schema.get("properties", {})
    for k in schema.get("required", []):
        if k not in a:
            return f"missing argument: {k}"
    for k, v in a.items():
        if k not in props:
            return f"unknown argument: {k}"
        typ = props[k].get("type")
        types = typ if isinstance(typ, list) else [typ]
        ok = any((t == "integer" and isinstance(v, int) and not isinstance(v, bool)) or (t == "string" and isinstance(v, str))
                 or (t == "number" and isinstance(v, (int, float)) and not isinstance(v, bool))  # 2.1.1: cost_usd
                 or (t == "boolean" and isinstance(v, bool)) or (t == "array" and isinstance(v, list))
                 or (t == "object" and isinstance(v, dict)) or (t == "null" and v is None) or t is None for t in types)
        if not ok:
            return f"invalid type for {k}"
        if "enum" in props[k] and v not in props[k]["enum"]:
            return f"invalid value for {k}"
        if isinstance(v, (int, float)) and not isinstance(v, bool) and (
                v < props[k].get("minimum", v) or v > props[k].get("maximum", v)):
            return f"{k} out of range"
        if isinstance(v, str) and (len(v) < props[k].get("minLength", 0) or len(v) > props[k].get("maxLength", len(v))):
            return f"invalid length for {k}"
    return None


# ---------------------------------------------------------------- JSON-RPC / MCP


def _result(i, r):
    return {"jsonrpc": "2.0", "id": i, "result": r}


def _error(i, code, msg):
    return {"jsonrpc": "2.0", "id": i, "error": {"code": code, "message": msg}}


def handle(api, msg):
    """One JSON-RPC message -> response dict, or None for notifications."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    i, m, p = msg.get("id"), msg["method"], msg.get("params") or {}
    notif = "id" not in msg
    if m == "initialize":
        want = p.get("protocolVersion") if isinstance(p, dict) else None
        r = {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
             "capabilities": {"tools": {"listChanged": False}},
             "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
             "instructions": "Kalmido tasks as the agent's user. Use wait_for_events to react to mentions, assignments, chat, "
                             "reactions (approvals), job actions, tidy requests and wake-ups; report progress with set_status and jobs, and "
                             "chat_typing while you write a chat answer."}
        return None if notif else _result(i, r)
    if m.startswith("notifications/"):
        return None
    if m == "ping":
        return None if notif else _result(i, {})
    if m == "tools/list":  # 2.15.0 (#479): only the tools this token may use
        return _result(i, {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s, _ in TOOLS if tool_allowed(api, n)]})
    if m == "tools/call":
        name, args = p.get("name"), p.get("arguments") or {}
        t = TOOL_MAP.get(name)
        if not t:
            return _error(i, -32602, f"Unknown tool: {name}")
        if not tool_allowed(api, name):
            need = TOOL_SCOPE.get(name, "read")
            return _result(i, {"content": [{"type": "text", "text": f"not allowed for this token: needs the scope {need}" if need != "agent"
                                            else "only for agent tokens"}], "isError": True})
        problem = _check_args(t[2], args)
        if problem:
            return _result(i, {"content": [{"type": "text", "text": problem}], "isError": True})
        try:
            out = t[3](api, args)
        except ApiError as e:
            return _result(i, {"content": [{"type": "text", "text": e.message}], "isError": True})
        content = [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=1)}]
        if name == "get_attachment" and isinstance(out, dict) and str(out.get("mime", "")).startswith("image/"):
            # 2.13.1 (#465): the model sees the image itself; the text item keeps name / mime / size only
            content = [{"type": "text", "text": json.dumps({k: v for k, v in out.items() if k != "base64"}, ensure_ascii=False)},
                       {"type": "image", "data": out["base64"], "mimeType": out["mime"]}]
        return _result(i, {"content": content, "structuredContent": out if isinstance(out, dict) else {"result": out}, "isError": False})
    return None if notif else _error(i, -32601, f"Method not found: {m}")


def handle_raw(api, raw):
    try:
        msg = json.loads(raw)
    except ValueError:
        return _error(None, -32700, "Parse error")
    if isinstance(msg, list):  # batch (2025-03-26)
        out = [r for r in (handle(api, x) for x in msg) if r is not None]
        return out or None
    return handle(api, msg)


def serve_stdio(api):
    lock = threading.Lock()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        r = handle_raw(api, line)
        if r is not None:
            with lock:
                sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
                sys.stdout.flush()


LOCAL_ORIGINS = ("localhost", "127.0.0.1", "[::1]", "::1")


def make_http_handler(api, token):
    class H(BaseHTTPRequestHandler):
        server_version = f"kalmido-mcp/{SERVER_VERSION}"

        def log_message(self, *a):  # quiet (never logs headers / tokens)
            pass

        def _send(self, code, obj=None, extra=None):
            data = json.dumps(obj).encode() if obj is not None else b""
            self.send_response(code)
            if obj is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _guard(self):
            if self.path.split("?")[0] != "/mcp":
                self._send(404, {"error": "not found"})
                return False
            origin = self.headers.get("Origin")
            if origin and (urllib.parse.urlsplit(origin).hostname or "") not in LOCAL_ORIGINS:
                self._send(403, {"error": "origin not allowed"})
                return False
            if token and self.headers.get("Authorization", "") != "Bearer " + token:
                self._send(401, {"error": "unauthorized"}, {"WWW-Authenticate": "Bearer"})
                return False
            return True

        def do_POST(self):
            if not self._guard():
                return
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                self._send(413, {"error": "too large"})
                return
            r = handle_raw(api, self.rfile.read(n).decode("utf-8", "replace"))
            if r is None:
                self._send(202)
            else:
                self._send(200, r)

        def do_GET(self):  # no server-initiated stream
            if self._guard():
                self._send(405, {"error": "use POST"}, {"Allow": "POST"})

        def do_DELETE(self):
            if self._guard():
                self._send(405, {"error": "no sessions"}, {"Allow": "POST"})
    return H


def main(argv=None):
    ap = argparse.ArgumentParser(description="Kalmido MCP server (stdio by default). Needs KALMIDO_URL and KALMIDO_TOKEN in the environment.")
    ap.add_argument("--http", action="store_true", help="serve Streamable HTTP (POST /mcp) instead of stdio")
    ap.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8765, help="HTTP port (default 8765)")
    a = ap.parse_args(argv)
    api = Kalmido(os.environ.get("KALMIDO_URL", ""), os.environ.get("KALMIDO_TOKEN", ""))
    if not api.base or not api.token:
        print("kalmido-mcp: KALMIDO_URL and KALMIDO_TOKEN must be set", file=sys.stderr)
    if a.http:
        srv = ThreadingHTTPServer((a.host, a.port), make_http_handler(api, os.environ.get("MCP_HTTP_TOKEN", "")))
        print(f"kalmido-mcp: listening on http://{a.host}:{srv.server_port}/mcp", file=sys.stderr, flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    else:
        serve_stdio(api)


if __name__ == "__main__":
    main()
