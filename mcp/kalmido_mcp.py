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
import uuid
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVER_NAME = "kalmido"
SERVER_VERSION = "2.13.1"
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
        return api.call("POST", f"/agent/chats/{int(a['user_id'])}", multipart=(_pick(a, ("body", "task_id")), files))
    if not a.get("body"):
        raise ApiError(400, "body (or files) is required")
    return api.call("POST", f"/agent/chats/{int(a['user_id'])}", body=_pick(a, ("body", "task_id")))


def t_get_attachment(api, a):
    """2.13.1 (#465): one file as base64 (source task = task / comment attachment, chat = a chat message's file), at most
    max_bytes (default 5 MB). Images also come as an MCP image item, so the model sees them."""
    cap = int(a.get("max_bytes") or ATT_CAP_DEFAULT)
    path = (f"/chat-attachments/{int(a['attachment_id'])}" if a.get("source") == "chat" else f"/attachments/{int(a['attachment_id'])}")
    r = api.call("GET", path, binary_cap=cap)
    return {"id": int(a["attachment_id"]), "source": a.get("source") or "task", "name": r["name"], "mime": r["mime"],
            "size": len(r["bytes"]), "base64": base64.b64encode(r["bytes"]).decode()}


def t_set_waiting(api, a):
    """2.1.0 (#335): waiting on external (note = who / what, until = follow-up day YYYY-MM-DD or null)."""
    return api.call("PUT", f"/tasks/{int(a['task_id'])}/waiting", body=_pick(a, ("note", "until")))


def t_list_waiting(api, a):
    q = {"waiting": "true", **_pick(a, ("list_id", "limit", "cursor"))}
    return api.call("GET", "/tasks", q)


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
                   "columns (2.14.0): the list's row columns in order (null = default layout), see set_list_columns.",
     _obj({}), lambda api, a: api.call("GET", "/lists")),
    ("set_list_columns", "2.14.0: set which columns the rows of a list show and in which order, the same for every member "
                         "(only as the list's owner or admin). Keys: id (task number in front of the title), due, prio, who "
                         "(assignee), tags, time (tracked), progress (subtasks), deps (dependencies), created, f:<field id> "
                         "(custom fields; ids in the fields of list_lists). A key that is not listed is not shown. columns: null = the "
                         "default layout. Phones show the first two as columns, the rest in the second line.",
     _obj({"list_id": S_ID, "columns": {"type": ["array", "null"], "items": {"type": "string"}, "maxItems": 40}}, ["list_id", "columns"]),
     lambda api, a: api.call("PATCH", f"/lists/{int(a['list_id'])}", body={"columns": a["columns"]})),
    ("list_repos", "Repositories connected to a list (provider, web_url, owner/repo, default branch, poll status). Never a token: "
                   "clone and push with your own git credentials.",
     _obj({"list_id": S_ID}, ["list_id"]), lambda api, a: api.call("GET", f"/lists/{int(a['list_id'])}/repos")),
    ("get_project_overview", "The overview of a project list (read-only): description (Markdown), key links (title + url, in "
                             "order), milestones (name, day, done), project files and Paperless documents of the list, the files "
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
           "waiting": {"type": "boolean", "description": "true = only tasks waiting on external, false = only the others"},
           "type": {"type": "string", "enum": ["bug", "feature", "task", "none"], "description": "only tickets of this type"},
           "assignee_group": {"type": "string", "description": "2.10.0: mine (assigned to one of your groups) or a group id"}}), t_list_tasks),
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
    ("set_waiting", "Mark a task as waiting on external (someone outside: a client, an office, a delivery), or change it. note: who / "
                    "what it waits for; until: the follow-up day (YYYY-MM-DD) -- on that day the person gets a reminder and agents that "
                    "follow the task the event followup_due.",
     _obj({"task_id": S_ID, "note": {"type": "string", "maxLength": 300}, "until": {"type": ["string", "null"]}}, ["task_id"]), t_set_waiting),
    ("clear_waiting", "The task no longer waits on external.",
     _obj({"task_id": S_ID}, ["task_id"]), lambda api, a: api.call("DELETE", f"/tasks/{int(a['task_id'])}/waiting")),
    ("list_waiting", "Open tasks waiting on external (task.waiting = {note, until, since, by}).",
     _obj({"list_id": S_ID, "limit": {"type": "integer", "minimum": 1, "maximum": 500}, "cursor": {"type": "string"}}), t_list_waiting),
    ("add_comment", "Comment on a task (Markdown; mention people as <@user_id>). Optional structured tidy suggestion.",
     _obj({"task_id": S_ID, "body": {"type": "string", "minLength": 1}, "suggestion": SUGGESTION}, ["task_id", "body"]), t_add_comment),
    ("request_merge_approval", "Ask for approval to merge your pull request: posts a 'ready to merge' comment on the task "
                               "(structured field kind merge_request). pr_url must be a pull request of a repository connected to "
                               "the task's list. Wait for the reaction event with approval 'approved' (👍 by the list owner / a list "
                               "admin / the assignee / an admin) before you merge; 'rejected' = do not merge.",
     _obj({"task_id": S_ID, "pr_url": {"type": "string", "minLength": 8, "maxLength": 500},
           "summary": {"type": "string", "maxLength": 2000}}, ["task_id", "pr_url"]), t_request_merge),
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
    ("set_status", "Report the agent's status, shown on its avatar: idle | working | waiting (for approval) | error, plus a short text. "
                   "task_id (optional): the task you are working on; while working, its comment area shows '<agent> is writing ...'.",
     _obj({"status": {"type": "string", "enum": ["idle", "working", "waiting", "error"]}, "text": {"type": "string", "maxLength": 200},
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
     "every comment of a person. Chat messages carry attachments [{id, name, mime, size}]: read them with get_attachment source chat.",
     _obj({"since": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
     lambda api, a: api.call("GET", "/agent/events", _pick(a, ("since", "limit")))),
    ("wait_for_events", "Long-poll: like list_events, but waits up to `wait` seconds (max 60) until an event arrives.",
     _obj({"since": {"type": "integer", "minimum": 0}, "wait": {"type": "integer", "minimum": 0, "maximum": WAIT_MAX},
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
                        "subtasks: {items: [{title, notes?, due?, estimate? (minutes)}], dependencies?: [[a, b]] (item a waits on b)}; "
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
                  "attach, [{name, base64, mime?}] (at most 10, each within the server's upload limit); with files the body may be empty.",
     _obj({"user_id": S_ID, "body": {"type": "string"}, "task_id": S_ID,
           "files": {"type": "array", "maxItems": 10, "items": {"type": "object", "properties": {
               "name": {"type": "string"}, "base64": {"type": "string"}, "mime": {"type": "string"}}, "required": ["name", "base64"]}}},
          ["user_id"]), t_send_chat),
    ("list_attachments", "Files of a task and of its comments (id, name, mime, size, comment_id): only tasks you see with their "
                         "comments. Read one with get_attachment.",
     _obj({"task_id": S_ID}, ["task_id"]), lambda api, a: api.call("GET", f"/tasks/{int(a['task_id'])}/attachments")),
    ("get_attachment", "Read one file: a task / comment attachment (source task, ids from list_attachments, get_task or comment "
                       "events) or a chat file (source chat, ids from a chat message's attachments). Returns name, mime, size and the "
                       "content as base64; images are also returned as an image you can look at. Use it when someone asks about a "
                       "screenshot. max_bytes caps the size (default 5 MB, at most 20 MB).",
     _obj({"attachment_id": S_ID, "source": {"type": "string", "enum": ["task", "chat"]},
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
     "Kalmido keeps the original text at the top of the notes.",
     _obj({"task_id": S_ID, "title": {"type": "string"}, "notes": {"type": "string"}, "section_id": {"type": ["integer", "null"]},
           "list_tags": STRS, "priority": PRIO}, ["task_id"]), t_tidy),
]
TOOL_MAP = {t[0]: t for t in TOOLS}


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
    if m == "tools/list":
        return _result(i, {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s, _ in TOOLS]})
    if m == "tools/call":
        name, args = p.get("name"), p.get("arguments") or {}
        t = TOOL_MAP.get(name)
        if not t:
            return _error(i, -32602, f"Unknown tool: {name}")
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
