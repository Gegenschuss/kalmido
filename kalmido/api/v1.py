"""REST API /api/v1 with personal access tokens: token management, authentication, the routes, errors, groups."""
import base64
import functools
import html
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta
from flask import g, has_request_context, jsonify, request, Response

from ..core.config import API_PREFIX, app, APP_NAME, APP_VERSION, PUB_PREFIX, TZ
from ..core.pg import insert_id, system_ctx
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, gsetting, inbox_default, iso, local_now, now_utc, parse_iso, test_seconds, uset, usettings
from ..accounts.session import _accept_lang, _rate_blocked, _rate_fail, _token_hash, FAIL_WINDOW, client_ip, me, rate_ip
from ..accounts.login import twofa_methods
from ..core.access import collab_all, Denied, list_role, need_list, need_task, need_time, time_all, token_lists, tvis, vis_sql
from ..core.serializers import load_tasks
from ..core.instance import semver, update_state
from ..core.state import search_tasks, visible_lists, visible_sections
from ..lists.lists import clean_folder, clean_list_value, list_create, LIST_KIND_ALIASES, LIST_KINDS, list_update
from ..lists.groups import (
    groups_for, grp_dict, grp_of_user, list_group_del, list_group_set, list_groups_get, need_group, task_take_web,
)
from ..lists.ownership import list_owner_set
from ..tasks.validation import as_int, NAG_VALUES, PRIORITIES, TICKET_TYPES, valid_date
from ..tasks.tasks import clear_waiting, set_waiting, task_create, task_update
from ..tasks.roadmap import list_shift, roadmap_build
from ..tasks.lifecycle import task_complete, task_reopen, trash_task
from ..collab.comments import att_dicts, comment_create, comment_dict, comment_plain, user_names
from ..collab.news import bell_custom_clean, bell_custom_of, BELL_MODES, notif_matrix, notif_update
from ..personal.habits import habit_log, habit_times, need_habit
from ..personal.timetrack import clean_day_hours, entry_out, time_create, time_rounding, time_rows, vis_ids
from ..core.errors import BadInput, field_alias, reject_unknown, UnknownFields
from ..lists.templates import PTYPES
from ..lists.projects import bell_store, ms_report
from ..calendars.caldav import apppw_create, apppw_delete, apppw_list, dav_info
from ..integrations.importers import imp_request, imp_undo
from ..notify.alerts import _env_int, aa_count, aa_now, fx2_mask_ip
from ..admin.backup import BK_ON_ENV
from ..core.env import env_bool
from ..api.common import (  # noqa: F401  2.149.0 G (#2517): the route helpers moved to api/common.py, re-exported here
    _HITS, _HITS_LOCK, act_via, cursor_dec, cursor_enc, hit_budget, hit_limit, RATE_WINDOW_S, v1_args, v1_call, v1_err,
    v1_error, v1_feature, v1_json, v1_out, v1_page, v1_view, V1_CODES, V1Error,
)


# ---------------------------------------------------------------- package B: REST API with personal access tokens
# /api/v1/* is a small, versioned, documented subset for scripts and integrations (Home Assistant, n8n, shell). It
# authenticates ONLY with a personal access token ("Authorization: Bearer abk_..."): never with a session cookie or
# the proxy header, so it needs no CSRF header, and a browser page on another site cannot use someone's login for it
# (no CORS either). A token belongs to one user and never grants more than that user has: every request runs as the
# user, through the same permission helpers (need_list / need_task / vis_sql) and mostly the very same internal views
# as the web client (g.body hands them the translated request) -- one code path for the business rules, so history
# lines ("via API"), notifications and webhooks behave exactly as in the app. Scopes: read (GET), write (changes,
# implies read), admin-read (GET /api/v1/admin/*, only while the user is an admin). The token is shown once at creation
# (abk_ + 256 random bits); only its SHA-256 is stored. Disabled or deleted users' tokens stop working at once.
# Limits: KALMIDO_API_RATE requests per token and minute; invalid tokens count per client address (FAIL_WINDOW) and
# are reported to the admins. KALMIDO_API=0 turns the whole API off (404). Spec: GET /api/v1/openapi.json (no data,
# served without a token), docs/API.md in the repository.
def _env_on(name, dflt="1"):
    return env_bool(name, dflt.strip().lower() not in ("0", "false", "no", "off"))  # 2.149.0 D (#2511)


API_ON = _env_on("KALMIDO_API")
WH_ON = _env_on("KALMIDO_WEBHOOKS")
PUB_ENV = _env_on("KALMIDO_PUBLIC_LINKS")
API_RATE = _env_int("KALMIDO_API_RATE", 120)   # requests per token and minute
API_BAD_LIMIT = 30                            # invalid tokens per client address within FAIL_WINDOW, then 429
API_TOKEN_MAX = 20                            # per user
API_TOKEN_RE = re.compile(r"abk_[A-Za-z0-9_-]{20,100}")
# 2.15.0 (#479): fine scopes. "write" (the only write scope before 2.15) stays valid: stored on a token it means every
# scope but admin-read (old tokens and scripts keep working unchanged); new tokens / agents get the fine ones.
# 2.21.0 (#659 / #658): "calendar" (events and event calendars, reading included) and "contacts" (address books and
# contacts, reading included: sensitive, so never part of the legacy "write"); a new agent gets neither by default
SCOPES = ("read", "tasks:write", "comments", "structure", "delete", "attachments:read", "attachments:write", "time", "export",
          "calendar", "contacts", "private", "account", "admin-read",
          "files:read", "files:write",  # 2.48.0 (#1207): the file store (folders / files shared with the token's account)
          "office",  # 2.51.0 A (#1348): office drafts of agents (office/agentdocs.py; never in the legacy "write" or a default)
          "pinboard",  # 2.51.0 (#1352): notepads on project pages (an agent changes only its own; off for new agents)
          "layouts",  # 2.55.0 (#1066): agents read how views are arranged and propose arrangements (off for new agents)
          "import",  # 2.68.0 (#1839): agents propose old data for the office as an import card (off for new agents)
          "sheets:read", "sheets:write")  # 2.89.0 C (#1916): tables (an agent: only shared ones; off for new agents)
# 2.22.0 (#663): "private" = health lists and the journal (reading included); like "contacts" never part of the legacy
# "write" and never in an agent's default (agents never see health lists at all, see core/access.py)
# 2.51.0 (#1352): nor "pinboard" (an old "write" token must not open the pin board for agents)
SCOPES_WRITE = tuple(s for s in SCOPES if s not in ("read", "admin-read", "contacts", "private", "office", "pinboard", "layouts", "import", "sheets:read", "sheets:write"))   # what the legacy "write" stands for; 2.55.0 (#1066): nor layouts; 2.68.0 (#1839): nor import; 2.89.0 C (#1916): nor sheets
SCOPES_AGENT_NEVER = ("account", "admin-read", "private")   # never for an agent: credentials / settings of the account, admin data, health + journal (2.22.0)
# 2.48.0 (#1207): a new agent may use the file store: it sees only what is shared with it (and its own folder) anyway
SCOPES_AGENT_DEFAULT = ("read", "tasks:write", "comments", "files:read", "files:write")
API_SCOPES = SCOPES + ("write",)
API_PAGE_MAX, API_PAGE_DEFAULT = 500, 100
API_USED_EVERY = 60                           # s between two last_used_at updates of one token
API_VERSION = "1.0"
PRIO_NAMES = {0: "none", 1: "low", 3: "medium", 5: "high"}
PRIO_VALUES = {v: k for k, v in PRIO_NAMES.items()}
STATUS_NAMES = {0: "open", 2: "done", -1: "wont_do"}


def api_scopes(csv_):
    """The scopes stored on a token (as given; "write" = the legacy umbrella). See scopes_effective for what counts."""
    s = {x for x in str(csv_ or "").split(",") if x in API_SCOPES}
    if "write" in s:
        s.add("read")
    return s


def api_authenticate():
    """before_request for /api/v1/*: the bearer token -> g.user (auth_via 'token'), scope and rate checks."""
    from ..agents.core import agent_active, agent_row, is_agent
    from ..agents.usage import usage_refused
    from ..api.scopes import approval_replay_token, SCOPE_LABELS, scopes_effective, token_ip_ok, v1_scope_need
    if not API_ON:
        return v1_err(404, tr("The API is turned off on this server"))
    if request.path == API_PREFIX + "openapi.json":
        return None  # the spec contains no data
    g.audit_t0 = time.monotonic()
    ip = rate_ip()
    bad = [("apibad:" + ip, API_BAD_LIMIT)]  # 2.126.0 C (#1979 I2): checked below, only when the token is not valid
    auth = request.headers.get("Authorization", "")
    tok = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    c = db()
    row = c.execute("SELECT * FROM api_tokens WHERE token_hash=?", (_token_hash(tok),)).fetchone() \
        if API_TOKEN_RE.fullmatch(tok) else None
    if request.headers.get("X-Kalmido-Replay"):  # 2.15.0 (#479): a person approved an agent's request (approval_run)
        row = approval_replay_token(c, request.headers["X-Kalmido-Replay"])
        if not row:
            return v1_err(401, tr("Missing or invalid API token"))
        tok = ""
    u = c.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone() if row else None
    if u and is_agent(u):  # 2.2.1 (#358): every request with an agent's token lands in its audit log (see audit_after)
        g.audit_aid = u["id"]
    if u and (u["disabled"] or u["kid"]):  # 2.79.0 (#476 M5): a child account has no API (its limits live in the web session)
        u = None
    expired = bool(row and row["expires_at"] and parse_iso(row["expires_at"]) <= now_utc())
    if not u or expired:
        if _rate_blocked(bad):
            return v1_err(429, tr("Too many invalid tokens, please wait a few minutes"), {"Retry-After": str(FAIL_WINDOW)})
        if tok and not expired:  # a missing header is a client mistake; a wrong token is counted and reported
            for k in _rate_fail(bad):
                aa_now("security", "ratelimit:" + k, N_("API rate limit reached for IP {0}: too many invalid tokens (refused for {1} min)."),
                       [fx2_mask_ip(ip), FAIL_WINDOW // 60])
            aa_count("security", "api", ip)
        return v1_err(401, tr("The API token has expired") if expired else tr("Missing or invalid API token"),
                      {"WWW-Authenticate": 'Bearer realm="kalmido"'})
    if is_agent(u):
        g.user = u  # 2.37.0 (#1150): from here on the agent's own context (its workspace): its row is read under it
    if is_agent(u) and not agent_active(agent_row(c, u["id"])):
        return v1_err(403, tr("This agent is paused"))
    if is_agent(u):  # 2.1.1 (#326): over its hard usage limit -> 429 (reporting usage + the status still work)
        refused = usage_refused(c, u["id"])
        if refused is not None:
            return refused
    if not g.get("approved_job") and not token_ip_ok(row, client_ip()):  # 2.15.0 (#479): optional address restriction (checked when an approved request was stored)
        return v1_err(403, tr("This token may not be used from this address"))
    scopes = scopes_effective(c, row, u)
    need = v1_scope_need(request.method, request.url_rule)
    g.scope_need = need
    if request.path.startswith(API_PREFIX + "admin/"):
        if "admin-read" not in scopes or not u["is_admin"]:
            return v1_err(403, tr("This token may not read admin data"), required_scope="admin-read")
        if need is None or need not in scopes:  # 2.79.0 (#476 M2): an admin route that writes needs its own scope too
            return v1_err(403, tr("This token lacks the permission “{0}”", tr(SCOPE_LABELS.get(need, need or "?"))), required_scope=need)
    elif need == "agent":
        pass  # the agent's own channel (status, events, jobs, chat, usage): the routes check need_agent()
    elif need is None:
        return v1_err(403, tr("Not allowed (scope, role or a switched-off module)"))
    elif need not in scopes:
        if need == "read":
            return v1_err(403, tr("This token has no read access"), required_scope=need)
        if not scopes - {"read", "attachments:read"}:
            return v1_err(403, tr("This token is read-only"), required_scope=need)
        return v1_err(403, tr("This token lacks the permission “{0}”", tr(SCOPE_LABELS.get(need, need))), required_scope=need)
    if hit_limit(f"api:{row['id']}", API_RATE):
        return v1_err(429, tr("Too many requests, please slow down"), {"Retry-After": "60"})
    g.user, g.auth_via, g.token, g.scopes = u, "token", row, scopes
    last = row["last_used_at"]
    if not last or (now_utc() - parse_iso(last)).total_seconds() >= API_USED_EVERY:
        c.execute("UPDATE api_tokens SET last_used_at=? WHERE id=?", (iso(now_utc()), row["id"]))
        c.commit()
    return None


def v1_limit(a):
    return as_int(a.get("limit", API_PAGE_DEFAULT), "limit", 1, API_PAGE_MAX)


def _reminders_list(v):
    return [int(x) for x in str(v or "").split(",") if re.fullmatch(r"-?\d{1,7}", x.strip())]


def task_core(r, tags, fields):
    """The task fields shared by the REST API and webhook payloads (r: a tasks row or load_tasks dict)."""
    from ..family.family import _jparse
    return {"id": r["id"], "list_id": r["list_id"], "section_id": r["section_id"], "parent_id": r["parent_id"],
            "title": r["title"], "notes": r["content"], "priority": PRIO_NAMES.get(r["priority"], "none"),
            "status": STATUS_NAMES.get(r["status"], "open"), "due": r["due"], "due_time": r["due_time"], "start": r["start"],
            "duration": r["duration"], "reminders": _reminders_list(r["reminders"]), "repeat": r["repeat"] or "",
            "repeat_from": r["repeat_from"], "url": r["url"], "tags": tags, "list_tags": list(r["ltags"]) if "ltags" in r.keys() else [],
            "pinned": bool(r["pinned"]),
            "assignee_id": r["assignee_id"], "created_by": r["created_by"], "completed_by": r["completed_by"],
            "assignee_group_id": r["assignee_group_id"] if "assignee_group_id" in r.keys() else None,  # 2.10.0 (#441)
            "created_at": r["created_at"], "updated_at": r["updated_at"], "completed_at": r["completed_at"],
            "deleted": bool(r["deleted_at"]), "fields": fields, "waiting": waiting_of(r),
            "type": (r["ttype"] if "ttype" in r.keys() else "") or None,
            # 2.7.0 (#412, #413): the due date is a deadline (+ on Today from the first reminder on), the nag interval
            "deadline": bool(r["deadline"]) if "deadline" in r.keys() else False,
            "deadline_in_today": (r["deadline"] == 2) if "deadline" in r.keys() else False,
            "nag": (r["nag"] if "nag" in r.keys() else "") or "",
            "plan_start": r["plan_start"] if "plan_start" in r.keys() else None,  # 2.11.0: day plan slot
            # 2.18.0 (#430): a milestone / the milestone (a task of the same list) the task belongs to
            "milestone": bool(r["ms"]) if "ms" in r.keys() and r["ms"] else False,
            "milestone_id": r["milestone_id"] if "milestone_id" in r.keys() else None,
            # 2.19.0 (#653): birthday / anniversary / household deadline data, the household rotation, a kid's stars
            "family": (_jparse(r["fam"]) or None) if "fam" in r.keys() else None,
            "rotation": (_jparse(r["rotation"]) or None) if "rotation" in r.keys() else None,
            "stars": r["stars"] if "stars" in r.keys() else None,
            "people": list(r["people"]) if "people" in r.keys() else [],
            # 2.23.0 (#463): an approval: pending | approved | changes | rejected (null = none) and who decides
            "approval": (r["approval"] or None) if "approval" in r.keys() else None,
            "approver_id": r["approver_id"] if "approval" in r.keys() and r["approval"] else None,
            # 2.36.0 (#1118): locked in the app (tasks created with an agent token start locked; the API is not bound by it)
            "locked": bool(r["locked"]) if "locked" in r.keys() else False,
            "points": r["points"] if "points" in r.keys() else None,  # 2.60.0 (#1511): story points (null = none)
            "remind_at": r["remind_at"] if "remind_at" in r.keys() else None,  # 2.111.0 C (#2057): fixed-time reminder
            # 2.35.0 (#1095): the code snippets: one task (GET / change / webhook row) all of them, lists only snippets_n
            **_snips(r)}


def _snips(r):
    from ..tasks.snippets import snip_out
    keys = r.keys()
    if "snippets" in keys:
        v = r["snippets"]
        sn = [dict(s) for s in v] if isinstance(v, list) else snip_out(v)
        return {"snippets": sn, "snippets_n": len(sn)}
    return {"snippets_n": r["snippets_n"] if "snippets_n" in keys else 0}


def waiting_of(r):
    """2.1.0 (#335): {note, until, since, by} while the task waits on someone outside, else None."""
    if "waiting_at" not in r.keys() or not r["waiting_at"]:
        return None
    return {"note": r["wait_note"] or "", "until": r["wait_until"], "since": r["waiting_at"], "by": r["wait_by"]}


def v1_task(d):
    out = task_core(d, d["tags"], d.get("fields") or {})
    out["list_tags"] = d.get("ltags") or []
    out.update(blocked=bool(d.get("blocked")), comment_count=d.get("comment_count", 0), context=bool(d.get("context")),
               attachments=[{**{k: a[k] for k in ("id", "name", "mime", "size")}, **({"encrypted": True} if a.get("enc") else {})}
                            for a in d.get("attachments") or []])
    if d.get("encrypted_note"):  # 2.42.0 (#828): only that there is one (the content is end-to-end encrypted)
        out["encrypted_note"] = True
    if d.get("note_locked"):  # 2.48.0 (#1642): the note is locked with its owner's password: notes stays empty
        out["note_locked"] = True
    if d.get("also"):  # 2.71.0 B (#1459): the further lists the token's user sees (absent: none)
        out["also"] = d["also"]
    if d.get("file_hit"):  # 2.81.0 (#1856): search -- only the recognised text of this file matched (absent otherwise; G4: needs attachments:read)
        out["file_hit"] = d["file_hit"]
    return out


def task_for(c, row, uid):
    """task_core of a tasks row as user uid sees it (their tags, the field values of the task's list)."""
    from ..collab.reactions import ltag_names
    tags = [r[0] for r in c.execute("SELECT tag FROM task_tags WHERE task_id=? AND user_id=? ORDER BY tag", (row["id"], uid))]
    fields = {str(r[0]): r[1] for r in c.execute("""SELECT v.field_id, v.value FROM task_field_values v JOIN list_fields f
                                                    ON f.id=v.field_id WHERE v.task_id=? AND f.list_id=?""", (row["id"], row["list_id"]))}
    if row["list_id"]:  # 2.43.0 (#1328): formula fields are computed (read-only for agents too)
        from ..lists.formula import fx_fill
        fields = fx_fill(c, {row["id"]: fields}, {row["id"]: row["list_id"]}).get(row["id"], fields)
    out = {**task_core(row, tags, fields), "list_tags": ltag_names(c, row["id"])}
    if c.execute("SELECT 1 FROM task_enc_notes WHERE task_id=? LIMIT 1", (row["id"],)).fetchone():
        out["encrypted_note"] = True  # 2.42.0 (#828): agents learn only that there is an encrypted note
    if c.execute("SELECT 1 FROM task_note_locks WHERE task_id=?", (row["id"],)).fetchone():
        out["note_locked"] = True  # 2.48.0 (#1642): the note is locked with its owner's password (never readable here)
    if str(row["tt_id"] or "").startswith("mail:"):  # 2.126.0 B (#1978): title and notes came from an e-mail
        out.update(origin="mail", untrusted=True)
    return out


V1_TASK_IN = ("title", "notes", "list_id", "section_id", "parent_id", "priority", "due", "due_time", "start", "duration",
              "reminders", "repeat", "repeat_from", "url", "tags", "assignee_id", "pinned", "fields", "list_tags", "type",
              "deadline", "deadline_in_today", "nag", "assignee_group_id", "plan_start", "milestone", "milestone_id",
              "family", "rotation", "stars", "people", "snippets", "locked")
V1_TASK_IN += ("points",)  # 2.60.0 (#1511): story points 1, 2, 3, 5, 8, 13 (null = none)
V1_TASK_IN += ("remind_at",)  # 2.111.0 C (#2057): a reminder at a fixed local time "YYYY-MM-DDTHH:MM" (null = none)


def v1_task_in(b, allowed=V1_TASK_IN):
    """API task body -> the body of the internal task endpoints (their clean_task validates the values).
    2.2.1 (#359): `content` (the web API's name of the notes) is accepted as an alias of `notes`."""
    from ..collab.reactions import clean_ltag_names
    b = field_alias(b, "notes", "content")
    reject_unknown(b, allowed)
    out = {}
    for k, v in b.items():
        if k == "notes":
            out["content"] = v
        elif k == "priority":
            if isinstance(v, str) and v in PRIO_VALUES:
                out["priority"] = PRIO_VALUES[v]
            elif isinstance(v, int) and not isinstance(v, bool) and v in PRIORITIES:
                out["priority"] = v
            else:
                raise BadInput(tr("Invalid value: {0}", "priority"))
        elif k == "tags":
            if not isinstance(v, list) or len(v) > 50 or not all(isinstance(x, str) and 0 < len(x.strip()) <= 100 for x in v):
                raise BadInput(tr("Invalid value: {0}", "tags"))
            out["tags"] = v
        elif k == "list_tags":
            out["ltags"] = clean_ltag_names(v)
        elif k == "pinned":
            if not isinstance(v, bool):
                raise BadInput(tr("Invalid value: {0}", "pinned"))
            out["pinned"] = 1 if v else 0
        elif k == "fields" and not isinstance(v, dict):
            raise BadInput(tr("Invalid value: {0}", "fields"))
        elif k == "repeat_from" and v not in ("due", "done"):
            raise BadInput(tr("Invalid value: {0}", "repeat_from"))
        elif k == "type":  # 2.4.0 (#340): bug | feature | task | null
            if v is not None and v not in TICKET_TYPES:
                raise BadInput(tr("Invalid value: {0}", "type"))
            out["ttype"] = v or ""
        elif k in ("deadline", "deadline_in_today"):  # 2.7.0 (#412): booleans -> the internal 0 / 1 / 2
            if not isinstance(v, bool):
                raise BadInput(tr("Invalid value: {0}", k))
        elif k == "nag":  # 2.7.0 (#413): '' = the list's default, 'off', or an interval
            if v not in NAG_VALUES:
                raise BadInput(tr("Invalid value: {0}", "nag"))
            out["nag"] = v
        elif k == "milestone":  # 2.18.0 (#430): boolean -> the internal ms 0 / 1
            if not isinstance(v, bool):
                raise BadInput(tr("Invalid value: {0}", "milestone"))
            out["ms"] = 1 if v else 0
        elif k == "locked":  # 2.36.0 (#1118): boolean -> 0 / 1
            if not isinstance(v, bool):
                raise BadInput(tr("Invalid value: {0}", "locked"))
            out["locked"] = 1 if v else 0
        elif k == "family":  # 2.19.0 (#653): the column fam
            out["fam"] = v
        else:
            out[k] = v
    if "deadline" in b or "deadline_in_today" in b:
        # deadline false = none; true (or only deadline_in_today) = a deadline, on Today from the first reminder when
        # deadline_in_today is true
        out["deadline"] = 0 if b.get("deadline") is False else 2 if b.get("deadline_in_today") is True else 1
    return out


def v1_one(c, tid):
    from ..integrations.git import git_repo_for_task
    rows = load_tasks(c, "id=? AND deleted_at IS NULL", (tid,), full_snips=True)  # 2.35.0 (#1095): one task: all snippets
    if not rows:
        raise Denied(404)
    out = v1_task(rows[0])
    if not rows[0].get("context"):  # 2.2.0 (#271 / #339): linked pull requests / commits + the list's repository
        out["code"] = rows[0].get("code") or {"prs": [], "commits": []}
        if out["code"].get("build"):  # 2.151.0 A2 (#2558 review): branch names marked untrusted also without repo below
            from ..integrations.gitbuild import gb_untrusted
            out["code"] = {**out["code"], "build": gb_untrusted(out["code"]["build"])}
        rp = git_repo_for_task(c, rows[0])
        if rp:
            out["repo"] = rp
            if rp.get("build"):  # 2.151.0 A (#2558): the build state, branch names marked untrusted as in repo
                out["code"] = {**out["code"], "build": rp["build"]}
    return out


def v1_list(d):
    name = tr("Basket") if d["is_inbox"] and inbox_default(d["name"]) else d["name"]
    return {"id": d["id"], "name": name, "color": d["color"], "folder": d["folder"], "is_inbox": bool(d["is_inbox"]),
            "archived": bool(d["archived"]), "done_at_bottom": bool(d.get("checklist")), "checklist": bool(d.get("checklist")),
            "kind": d.get("kind") or "list", "view": d["view"], "role": d["role"],
            "org_id": d.get("org_id"),  # 2.28.0 (#935): the workspace (null = private)
            # 2.46.0 (#1603): "" = only the people it is shared with, "org" = everyone in the organisation (org_edit: they may
            # edit without joining); org_reader: you see it only that way (POST /lists/{id}/join makes you a member)
            "org_visibility": d.get("org_visibility") or "", "org_edit": bool(d.get("org_edit")), "org_reader": bool(d.get("org_reader")),
            "owner_id": d["owner_id"], "owner_name": d["owner_name"], "shared": d["shared"],
            "status": d.get("status") or None, "progress": d["progress"], "created_at": d["created_at"],
            "tags": d.get("tags") or [], "agent_tidy": d.get("agent_tidy") or "off", "tidy_agent_id": d.get("tidy_agent_id"),
            "listen_agent_ids": d.get("listen_agent_ids") or [],  # 2.13.1 (#471)
            "listen_default": bool(d.get("listen_default")),  # 2.30.0 (#1034): the project type lets agents listen in by default
            # 2.26.0 (#928): members may see and use the list's agents / agents may address each other
            "agent_members": bool(d.get("agent_members")), "agent_peers": False,  # 2.40.0 (#1373): deprecated, always false
            # 2.34.0 (#266): stale after N idle days (null = the default) / "Agent follows up" (event stale_tasks)
            "stale_days": d.get("stale_days"), "agent_followup": bool(d.get("agent_followup")),
            "icon": d.get("icon") or "",
            "repos": d.get("repos") or [], "tickets": bool(d.get("tickets")),
            "time_tracking": bool(d.get("time_tracking")),  # 2.41.0 (#1471): time tracking on for this list
            "points_on": bool(d.get("points_on")),  # 2.60.0 (#1511): story points shown in the app
            "header_style": d.get("header_style") or "",  # 2.83.0 (#1427): the list's header strip in the app (read only)
            "nag": d.get("nag") or "", "day_hours": d.get("day_hours"),  # 2.7.0 (#413, #407)
            "columns": d.get("columns"),  # 2.14.0 (#425): the list's columns (null = default)
            "project_type": d.get("ptype") or None,  # 2.18.0 (#408): agency | software | private, null = none
            "family": d.get("family") or None,  # 2.19.0 (#653): shopping | meals | birthdays | household | packing, null = none
            "life": d.get("life") or None, "trip": d.get("trip") or None,
            # 2.144.0 C (#2414): the list's sort and its grouping by a custom field, the same for every member
            "sort_mode": d.get("sort_mode") or "", "group_field": d.get("group_field") or "",
            "client_id": d.get("client_id")}  # 2.22.0 (#663): contracts | home | health | travel | reading


# ---- token management (Settings > Account > API tokens; session / proxy login only, a token cannot reach these)
def need_api():
    if not API_ON:
        raise Denied(409, tr("The API is turned off on this server"))


def token_public(r):
    """2.15.0 (#479): scopes = as stored ("write" = the legacy umbrella), effective_scopes = what the token may do now
    (the legacy umbrella expanded, the admin's limit and the agent rules applied), allowed_ips = the address restriction."""
    from ..api.scopes import scopes_effective
    c = db()
    u = c.execute("SELECT * FROM users WHERE id=?", (r["user_id"],)).fetchone()
    return {"id": r["id"], "name": r["name"], "prefix": r["prefix"], "scopes": sorted(api_scopes(r["scopes"])),
            "effective_scopes": [x for x in SCOPES if x in scopes_effective(c, r, u)] if u else [],
            "allowed_ips": [x for x in (r["allowed_ips"] or "").split(",") if x],
            "list_ids": sorted(int(x) for x in (r["list_ids"] if "list_ids" in r.keys() else "").split(",") if x.strip().isdigit()),  # 2.30.0 (#919)
            "expires_at": r["expires_at"], "created_at": r["created_at"], "last_used_at": r["last_used_at"],
            "expired": bool(r["expires_at"] and parse_iso(r["expires_at"]) <= now_utc())}


def token_lists_clean(c, v):
    """2.30.0 (#919): the lists a personal token is limited to: lists I see ([] / None = all)."""
    from ..agents.safety import list_ids_clean
    return list_ids_clean(c, v, lambda n: bool(list_role(c, n, me())))


@app.get("/api/me/tokens")
def tokens_list():
    from ..api.scopes import scope_cap, scopes_offer
    c = db()
    return jsonify(enabled=API_ON, rate=API_RATE, tokens=[token_public(r) for r in c.execute(
        "SELECT * FROM api_tokens WHERE user_id=? ORDER BY id DESC", (me(),))],
                   scopes=scopes_offer(c, g.user), limit=scope_cap(c, "tokens"))  # 2.15.0 (#479)


@app.post("/api/me/tokens")
def token_create():
    """{name, scopes: [read, write, admin-read], expires_days: null | 1..3650} -> the token, shown this once."""
    from ..api.scopes import ips_clean, scopes_clean
    need_api()
    b, c = body(), db()
    name = str(b.get("name") or "").strip()[:60]
    if not name:
        return err(tr("Name missing"))
    scopes = scopes_clean(b.get("scopes") or ["read"], g.user)
    ips = ips_clean(b.get("allowed_ips"))
    lids = token_lists_clean(c, b.get("list_ids"))  # 2.30.0 (#919)
    days = b.get("expires_days")
    exp = None
    if days not in (None, "", 0):
        exp = iso(now_utc() + timedelta(days=as_int(days, tr("Expiry"), 1, 3650)))
    if c.execute("SELECT COUNT(*) FROM api_tokens WHERE user_id=?", (me(),)).fetchone()[0] >= API_TOKEN_MAX:
        return err(tr("At most {0} tokens", API_TOKEN_MAX), 409)
    tok = "abk_" + secrets.token_urlsafe(32)
    tid = insert_id(c, "INSERT INTO api_tokens(user_id,name,token_hash,prefix,scopes,expires_at,created_at,allowed_ips,list_ids) VALUES(?,?,?,?,?,?,?,?,?)",
                    (me(), name, _token_hash(tok), tok[:12], ",".join(scopes), exp, iso(now_utc()), ips, lids))
    c.commit()
    print("api token", tid, "created for user", me(), "scopes", ",".join(scopes), flush=True)
    return jsonify({**token_public(c.execute("SELECT * FROM api_tokens WHERE id=?", (tid,)).fetchone()), "token": tok}), 201


@app.patch("/api/me/tokens/<int:tid>")
def token_update(tid):
    """2.15.0 (#479): {scopes?, allowed_ips?, name?} -- change what one of my tokens may do (the token itself stays)."""
    from ..api.scopes import ips_clean, scopes_clean
    need_api()
    b, c = body(), db()
    r = c.execute("SELECT * FROM api_tokens WHERE id=? AND user_id=?", (tid, me())).fetchone()
    if not r:
        raise Denied(404)
    unknown = sorted(k for k in b if k not in ("scopes", "allowed_ips", "name", "list_ids"))
    if unknown:
        return err(tr("Invalid value: {0}", ", ".join(unknown)))
    if "scopes" in b:
        c.execute("UPDATE api_tokens SET scopes=? WHERE id=?", (",".join(scopes_clean(b["scopes"], g.user)), tid))
    if "allowed_ips" in b:
        c.execute("UPDATE api_tokens SET allowed_ips=? WHERE id=?", (ips_clean(b["allowed_ips"]), tid))
    if "list_ids" in b:  # 2.30.0 (#919): limited to selected lists ([] = all)
        c.execute("UPDATE api_tokens SET list_ids=? WHERE id=?", (token_lists_clean(c, b["list_ids"]), tid))
    if "name" in b:
        name = str(b["name"] or "").strip()[:60]
        if not name:
            return err(tr("Name missing"))
        c.execute("UPDATE api_tokens SET name=? WHERE id=?", (name, tid))
    c.commit()
    print("api token", tid, "of user", me(), "changed:", ",".join(sorted(b)), flush=True)
    return jsonify(token_public(c.execute("SELECT * FROM api_tokens WHERE id=?", (tid,)).fetchone()))


@app.delete("/api/me/tokens/<int:tid>")
def token_delete(tid):
    c = db()
    if not c.execute("DELETE FROM api_tokens WHERE id=? AND user_id=?", (tid, me())).rowcount:
        raise Denied(404)
    c.commit()
    return jsonify(ok=True)


# ---- the API (every route: @v1_view; reads need scope read, changes write -- checked in api_authenticate)
@app.get("/api/v1/openapi.json")
def v1_openapi():
    from ..api.openapi import openapi_spec
    r = Response(json.dumps(openapi_spec(), ensure_ascii=False, indent=1), mimetype="application/json")
    r.headers["Cache-Control"] = "no-cache"
    return r


@app.get("/api/v1/me")
@v1_view
def v1_me():
    from ..agents.core import is_agent
    c, u, t = db(), g.user, g.token
    fs = (usettings(c, u["id"]).get("features") or "").split(",")
    return jsonify(id=u["id"], username=u["username"], display_name=u["display_name"] or u["username"], is_admin=bool(u["is_admin"]),
                   kind="agent" if is_agent(u) else "user",
                   token={"id": t["id"], "name": t["name"], "scopes": sorted(api_scopes(t["scopes"])), "expires_at": t["expires_at"],
                          "effective_scopes": [s for s in SCOPES if s in g.get("scopes", set())],  # 2.15.0 (#479)
                          "list_ids": sorted(token_lists() or [])},  # 2.30.0 (#919): [] = all lists
                   features={"collaboration": collab_all() and "collab" in fs, "time_tracking": time_all() and "time" in fs,
                             "dependencies": "deps" in fs, "custom_fields": "fields" in fs, "comments": "comments" in fs},
                   api_version=API_VERSION, rate_limit_per_minute=API_RATE, notifications=v1_notif(c, u["id"]))


def v1_notif(c, uid):
    """2.1.0 (#317): my notification settings: the matrix + the bells of my lists (only lists not on "default")."""
    rows = c.execute(f"SELECT list_id, mode, custom FROM list_bell WHERE user_id=? AND mode!='default' AND list_id IN {vis_sql()}",
                     (uid, uid, uid)).fetchall()
    return {"events": notif_matrix(usettings(c, uid)),
            "lists": {str(r[0]): r[1] for r in rows},
            # 2.6.1 (#404): the event choice of lists on "custom" (events missing there = as in the matrix)
            "custom": {str(r[0]): bell_custom_of(r[2]) for r in rows if r[1] == "custom"}}


# 2.9.0 (#435): app passwords for calendar apps (CalDAV), persons only (an agent never gets CalDAV)
def v1_person():
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot use calendar apps"))


@app.get("/api/v1/me/app-passwords")
@v1_view
def v1_apppw_list():
    v1_args(())
    v1_person()
    return jsonify(data=apppw_list(db(), me()), caldav=dav_info(g.user))


@app.post("/api/v1/me/app-passwords")
@v1_view
def v1_apppw_create():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("name",))
    v1_person()
    if token_lists() is not None or not {"calendar", "contacts"} <= set(g.scopes):  # 2.79.0 (#476 M1): an app password
        # opens CalDAV / CardDAV without any limit, so only a token that may already do all of that creates one
        return v1_err(403, tr("Only a token for all lists with the permissions “Calendar” and “Contacts” may create an app password"),
                      required_scope="contacts")
    row, pw = apppw_create(db(), g.user, b.get("name"))
    return jsonify({**row, "password": pw}), 201


@app.delete("/api/v1/me/app-passwords/<int:pid>")
@v1_view
def v1_apppw_delete(pid):
    v1_args(())
    v1_person()
    apppw_delete(db(), me(), pid)
    return jsonify(ok=True)


@app.patch("/api/v1/me/notifications")
@v1_view
def v1_notif_update():
    """{events?: {event: {news?, push?}}, lists?: {list id: all | default | mute}} -- partial changes."""
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("events", "lists"))
    if unknown:
        raise UnknownFields(unknown)
    c, uid = db(), me()
    if "events" in b:
        for k, v in notif_update(usettings(c, uid), b["events"]).items():
            uset(c, uid, k, v)
    if "lists" in b:
        if not isinstance(b["lists"], dict) or len(b["lists"]) > 1000:
            raise BadInput(tr("Invalid value: {0}", "lists"))
        for k, mode in b["lists"].items():
            lid = as_int(k, "lists", 1)
            cust = None
            if isinstance(mode, dict):  # 2.6.1 (#404): {mode: "custom", events: {event: {news?, push?}}}
                if set(mode) - {"mode", "events"} or mode.get("mode") != "custom":
                    raise BadInput(tr("Invalid value: {0}", "lists"))
                cust = bell_custom_clean(mode.get("events") or {})
                mode = "custom"
            if mode not in BELL_MODES:
                raise BadInput(tr("Invalid value: {0}", "lists"))
            if not list_role(c, lid, uid):
                raise Denied(404)
            bell_store(c, uid, lid, mode, cust)
    bump(c)
    c.commit()
    return jsonify(v1_notif(c, uid))


@app.get("/api/v1/lists")
@v1_view
def v1_lists():
    v1_args(())
    c = db()
    secs = {}
    for r in visible_sections(c, me()):  # 2.0.8 (#333): every list with its sections [{id, name}]
        secs.setdefault(r["list_id"], []).append({"id": r["id"], "name": r["name"]})
    fl = v1_list_fields(c)
    from ..lists.favorites import lc_fav_of
    fav = lc_fav_of(c, me())  # 2.46.1 (#1361): favourite of the person (an agent: of its owner)
    return jsonify(data=[{**v1_list(d), "sections": secs.get(d["id"], []), "fields": fl.get(d["id"], []), "favorite": d["id"] in fav}
                         for d in visible_lists(c, me())], next_cursor=None)


def v1_list_fields(c, lid=None):
    """2.14.0 (#425): the custom fields of the visible lists {list_id: [{id, name, type}]} (for columns "f:<id>")."""
    out = {}
    q = f"SELECT id, list_id, name, type FROM list_fields WHERE list_id IN {vis_sql()}" + (" AND list_id=?" if lid else "") + " ORDER BY sort, id"
    for r in c.execute(q, (me(), me(), *((lid,) if lid else ()))):
        out.setdefault(r["list_id"], []).append({"id": r["id"], "name": r["name"], "type": r["type"]})
    return out


@app.post("/api/v1/lists")
@v1_view
def v1_list_create():
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("name", "color", "folder", "checklist", "done_at_bottom", "kind", "tickets", "project_type", "nag", "day_hours",
                                               "family", "sections", "org_id", "time_tracking"))  # 2.28.0 (#935): org_id; 2.41.0 (#1471)
    unknown = [k for k in unknown if k != "points_on"]  # 2.60.0 (#1511): story points on (set right after, like time_tracking)
    if unknown:
        raise UnknownFields(unknown)
    later = {k: b.pop(k) for k in ("nag", "day_hours", "time_tracking") if k in b}  # 2.7.0: set right after the list exists
    if "points_on" in b:  # 2.60.0 (#1511)
        later["points_on"] = b.pop("points_on")
        if not isinstance(later["points_on"], bool):
            raise BadInput(tr("Invalid value: {0}", "points_on"))
    if "time_tracking" in later and not isinstance(later["time_tracking"], bool):  # 2.41.0 (#1471)
        raise BadInput(tr("Invalid value: {0}", "time_tracking"))
    if "nag" in later:
        clean_list_value("nag", later["nag"])
    if "day_hours" in later and clean_day_hours(later["day_hours"]) is False:
        raise BadInput(tr("Hours per day: a number from 1 to 24"))
    for k in ("checklist", "done_at_bottom"):
        if k in b and not isinstance(b[k], bool):
            raise BadInput(tr("Invalid value: {0}", k))
    if "tickets" in b and not isinstance(b["tickets"], bool):
        raise BadInput(tr("Invalid value: {0}", "tickets"))
    if b.get("project_type") is not None and b["project_type"] not in PTYPES:
        raise BadInput(tr("Invalid value: {0}", "project_type"))
    if "sections" in b and (not isinstance(b["sections"], bool) or not b.get("project_type")):  # 2.27.0 (#972)
        raise BadInput(tr("Invalid value: {0}", "sections"))
    if b.get("project_type"):
        b = {**{k: v for k, v in b.items() if k not in ("project_type", "kind", "checklist", "done_at_bottom", "tickets")}, "ptype": b["project_type"]}
    if "kind" in b and b["kind"] not in LIST_KINDS and b["kind"] not in LIST_KIND_ALIASES:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    j = v1_call(list_create, body=b)
    from ..agents.safety import token_list_add
    token_list_add(db(), j["id"])  # 2.30.0 (#919): a token limited to selected lists keeps the list it created
    db().commit()
    if later:
        v1_call(list_update, j["id"], body=later)
    d = next(x for x in visible_lists(db(), me()) if x["id"] == j["id"])
    return jsonify(v1_list(d)), 201


@app.patch("/api/v1/lists/<int:lid>")
@v1_view
def v1_list_patch(lid):
    """2.7.0: change a list: name, color, folder (yours), view, kind, nag (default of the list's tasks), day_hours;
    2.7.2 (#414): done_at_bottom ("Show completed at the bottom"; checklist = deprecated alias); 2.13.1 (#471):
    listen_agent_ids (the agents that read every comment; owner / list admins, never an agent token); 2.14.0 (#425):
    columns (the list's columns for every member; owner / list admins); 2.18.0 (#408): project_type (owner / list admins:
    switches on what the type needs -- type Project, ticket types, its modules -- and never deletes anything)."""
    from ..api.scopes import need_approval
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("name", "color", "folder", "view", "kind", "nag", "day_hours", "done_at_bottom", "checklist",
                                               "listen_agent_ids", "columns", "archived", "project_type", "family", "life", "trip",
                                               "client_id", "agent_members", "agent_peers", "org_id",
                                               "stale_days", "agent_followup", "folder_adopt", "time_tracking",
                                               "org_visibility", "org_edit", "sort_mode", "group_field"))  # 2.28.0 (#935); 2.34.0 (#266); 2.39.1 (#1188); 2.41.0 (#1471); 2.46.0 (#1603)
    unknown = [k for k in unknown if k != "points_on"]  # 2.60.0 (#1511): story points on (the owner)
    if "points_on" in b and not isinstance(b["points_on"], bool):
        raise BadInput(tr("Invalid value: {0}", "points_on"))
    if unknown:
        raise UnknownFields(unknown)
    if "family" in b and b["family"] is None:  # 2.19.0 (#653): null = an ordinary list
        b = {**b, "family": ""}
    if "life" in b and b["life"] is None:  # 2.22.0 (#663)
        b = {**b, "life": ""}
    if "project_type" in b:  # 2.18.0 (#408): change the project type (owner / list admins; null / "" = none)
        if b["project_type"] not in (None, "") and b["project_type"] not in PTYPES:
            raise BadInput(tr("Invalid value: {0}", "project_type"))
        b = {**{k: v for k, v in b.items() if k != "project_type"}, "ptype": b["project_type"] or ""}
    for k in ("checklist", "done_at_bottom", "archived", "agent_members", "agent_peers", "time_tracking", "org_edit"):  # 2.41.0 (#1471): time_tracking
        if k in b and not isinstance(b[k], bool):
            raise BadInput(tr("Invalid value: {0}", k))
    if "folder_adopt" in b and not isinstance(b["folder_adopt"], bool):  # 2.39.1 (#1188): take the new folder's settings
        raise BadInput(tr("Invalid value: {0}", "folder_adopt"))
    if "archived" in b:  # 2.15.0 (#479): archive / restore (the owner); deleting for good: DELETE /lists/{id}
        b = {**b, "archived": 1 if b["archived"] else 0}
    c = db()
    role = need_list(c, lid, write=False)
    if "folder" in b and role == "owner":  # 2.15.0 (#479): an agent moving its own list into another folder (group shares!)
        cur = c.execute("SELECT name, folder FROM lists WHERE id=?", (lid,)).fetchone()
        if clean_folder(b["folder"] or "") != (cur["folder"] or ""):
            need_approval(c, N_("Move the list “{0}” into the folder “{1}”"), (cur["name"], str(b["folder"] or "")[:100]), list_id=lid)
    if b.get("org_visibility") == "org" or b.get("org_edit") is True:  # 2.46.0 (#1603): an agent opens a list to its organisation
        cur = c.execute("SELECT name, org_visibility, org_edit FROM lists WHERE id=?", (lid,)).fetchone()
        if (b.get("org_visibility") == "org" and cur["org_visibility"] != "org") or (b.get("org_edit") is True and not cur["org_edit"]):
            need_approval(c, N_("Make the list “{0}” visible to everyone in the organisation"), (cur["name"],), list_id=lid)
    j = v1_call(list_update, lid, body=b)
    d = next((x for x in visible_lists(c, me()) if x["id"] == lid), None)
    if not d:
        raise Denied(404)
    # 2.39.1 (#1293): the modules this change switched on (custom field columns: "fields" for the owner; project_type)
    return jsonify({**v1_list(d), **({"modules_on": j["modules_on"]} if isinstance(j, dict) and "modules_on" in j else {})})


@app.get("/api/v1/lists/<int:lid>")
@v1_view
def v1_list_get(lid):
    v1_args(())
    c = db()
    need_list(c, lid, write=False)
    d = next((x for x in visible_lists(c, me()) if x["id"] == lid), None)
    if not d:
        raise Denied(404)
    from ..lists.favorites import lc_fav_of
    from ..lists.playbook import pb_effective
    pb = pb_effective(c, lid)  # 2.39.0 (#1168): the effective Playbook (null = none; never of a health list)
    return jsonify({**v1_list(d), "sections": [{"id": r["id"], "name": r["name"], "sort": r["sort"]}
                                               for r in visible_sections(c, me()) if r["list_id"] == lid],
                    "fields": v1_list_fields(c, lid).get(lid, []),
                    "favorite": lid in lc_fav_of(c, me()),  # 2.46.1 (#1361)
                    "playbook": pb["text"] if pb and pb["text"] and pb["life"] != "health" else None})


@app.post("/api/v1/lists/<int:lid>/owner")
@v1_view
def v1_list_owner(lid):
    """2.1.2 (#349): transfer the ownership (owner) or take a list of an agent / a disabled user over (admins). Never agents."""
    from ..agents.core import is_agent
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k != "user_id")
    if unknown:
        raise UnknownFields(unknown)
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot transfer lists"))
    return jsonify(v1_call(list_owner_set, lid, body={"user_id": b.get("user_id")}))


@app.get("/api/v1/roadmap")
@v1_view
def v1_roadmap():
    return jsonify(roadmap_build(db(), me(), v1_args(("from", "to", "projects_only", "include_done"))))


@app.post("/api/v1/lists/<int:lid>/shift")
@v1_view
def v1_list_shift(lid):
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k != "days")
    if unknown:
        raise UnknownFields(unknown)
    return jsonify(v1_call(list_shift, lid, body={"days": b.get("days")}))


def _v1_since(v):
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "updated_since")) from None
    return iso(dt if dt.tzinfo else dt.replace(tzinfo=TZ))


@app.get("/api/v1/tasks")
@v1_view
def v1_tasks():
    """Visible tasks (not in the trash), oldest id first, cursor pages. Filters: list_id, status, due_from, due_to,
    tag, assignee (me | none | id), updated_since, parent_id, top_level."""
    a = v1_args(("list_id", "status", "due_from", "due_to", "tag", "list_tag", "assignee", "updated_since", "parent_id", "top_level",
                 "limit", "cursor", "fields", "waiting", "type", "assignee_group", "pinned", "milestone", "milestone_id"))
    if a.get("fields") not in (None, "", "full", "compact"):
        raise BadInput(tr("Invalid value: {0}", "fields"))
    c, uid = db(), me()
    where, args = [f"list_id IN {vis_sql()}", "deleted_at IS NULL", tvis(c, uid)], [uid, uid]
    if a.get("list_id"):
        lid = as_int(a["list_id"], "list_id", 1)
        need_list(c, lid, write=False)
        where.append("list_id=?")
        args.append(lid)
    st = a.get("status", "open")
    if st not in ("open", "done", "wont_do", "all"):
        raise BadInput(tr("Invalid value: {0}", "status"))
    if st != "all":
        where.append("status=?")
        args.append({"open": 0, "done": 2, "wont_do": -1}[st])
    for k, op in (("due_from", ">="), ("due_to", "<=")):
        if a.get(k):
            if not valid_date(a[k]):
                raise BadInput(tr("Invalid value: {0}", k))
            where.append(f"due IS NOT NULL AND due{op}?")
            args.append(a[k])
    if a.get("tag"):  # 2.0.0: a personal tag or a list tag of that name
        where.append("(id IN (SELECT task_id FROM task_tags WHERE user_id=? AND tag=?) OR id IN (SELECT x.task_id FROM task_list_tags x "
                     "JOIN list_tags lt ON lt.id=x.tag_id WHERE lower(lt.name)=lower(?) AND lt.list_id=tasks.list_id))")
        args += [uid, a["tag"].lstrip("#"), a["tag"].lstrip("#")]
    if a.get("list_tag"):
        where.append("id IN (SELECT x.task_id FROM task_list_tags x JOIN list_tags lt ON lt.id=x.tag_id "
                     "WHERE lower(lt.name)=lower(?) AND lt.list_id=tasks.list_id)")
        args.append(a["list_tag"].lstrip("#"))
    if a.get("assignee"):
        if a["assignee"] == "none":
            where.append("assignee_id IS NULL")
        else:
            where.append("assignee_id=?")
            args.append(uid if a["assignee"] == "me" else as_int(a["assignee"], "assignee", 1))
    if a.get("assignee_group"):  # 2.10.0 (#441): mine = assigned to one of my groups, or a group id
        if a["assignee_group"] == "mine":
            where.append("assignee_group_id IN (SELECT group_id FROM group_members WHERE user_id=?)")
            args.append(uid)
        else:
            where.append("assignee_group_id=?")
            args.append(as_int(a["assignee_group"], "assignee_group", 1))
    if a.get("updated_since"):
        where.append("updated_at>=?")
        args.append(_v1_since(a["updated_since"]))
    if a.get("parent_id"):
        where.append("parent_id=?")
        args.append(as_int(a["parent_id"], "parent_id", 1))
    if a.get("top_level") in ("1", "true"):
        where.append("parent_id IS NULL")
    if a.get("waiting") not in (None, ""):  # 2.1.0 (#335): only tasks waiting on external (true) / only the others (false)
        if a["waiting"] not in ("1", "true", "0", "false"):
            raise BadInput(tr("Invalid value: {0}", "waiting"))
        where.append("waiting_at IS NOT NULL" if a["waiting"] in ("1", "true") else "waiting_at IS NULL")
    if a.get("pinned") not in (None, ""):  # 2.16.0 (#648): only pinned tasks (true) / only the others (false)
        if a["pinned"] not in ("1", "true", "0", "false"):
            raise BadInput(tr("Invalid value: {0}", "pinned"))
        where.append("pinned=1" if a["pinned"] in ("1", "true") else "pinned=0")
    if a.get("milestone") not in (None, ""):  # 2.18.0 (#430): only milestones (true) / only the other tasks (false)
        if a["milestone"] not in ("1", "true", "0", "false"):
            raise BadInput(tr("Invalid value: {0}", "milestone"))
        where.append("ms=1" if a["milestone"] in ("1", "true") else "ms=0")
    if a.get("milestone_id") not in (None, ""):  # 2.18.0 (#430): the tasks of one milestone
        where.append("milestone_id=?")
        args.append(as_int(a["milestone_id"], "milestone_id", 1))
    if a.get("type") not in (None, ""):  # 2.4.0 (#340): bug | feature | task | none
        if a["type"] not in (*TICKET_TYPES, "none"):
            raise BadInput(tr("Invalid value: {0}", "type"))
        where.append("ttype=?")
        args.append("" if a["type"] == "none" else a["type"])
    after, limit = cursor_dec("i", a.get("cursor")), v1_limit(a)
    where.append("id>?")
    args += [after, limit + 1]
    rows = load_tasks(c, " AND ".join(where) + " ORDER BY id LIMIT ?", args)
    more = len(rows) > limit
    rows = rows[:limit]
    out = [v1_task(d) for d in rows]
    if a.get("fields") == "compact":  # 2.0.8 (#333): the few fields an agent scans a list with
        out = [{k: x.get(k) for k in V1_COMPACT} for x in out]
    return jsonify(data=out, next_cursor=cursor_enc("i", rows[-1]["id"]) if more else None)


V1_COMPACT = ("id", "title", "list_id", "section_id", "parent_id", "status", "due", "due_time", "priority", "tags", "list_tags",
              "assignee_id")


@app.post("/api/v1/tasks")
@v1_view
def v1_task_create():
    v1_args(())
    j = v1_call(task_create, body=v1_task_in(v1_json()))
    r = jsonify(v1_one(db(), j["id"]))
    r.status_code, r.headers["Location"] = 201, f"{API_PREFIX}tasks/{j['id']}"
    return r


@app.get("/api/v1/tasks/<int:tid>")
@v1_view
def v1_task_get(tid):
    v1_args(())
    c = db()
    need_task(c, tid, write=False)
    return jsonify(v1_one(c, tid))


def _v1_live(c, tid, write=True, full=False):
    need_task(c, tid, write=write, full=full)
    r = c.execute("SELECT deleted_at, status FROM tasks WHERE id=?", (tid,)).fetchone()
    if r["deleted_at"]:
        raise Denied(404)
    return r


@app.patch("/api/v1/tasks/<int:tid>")
@v1_view
def v1_task_update(tid):
    v1_args(())
    c = db()
    _v1_live(c, tid)
    raw = dict(v1_json())
    sc = raw.pop("shift_chain", True)  # 2.67.0 B (#1865): false = the tasks waiting on it stay where they are
    if not isinstance(sc, bool):
        raise BadInput(tr("Invalid value: {0}", "shift_chain"))
    b = v1_task_in(raw)
    if not b:
        raise BadInput(tr("Nothing to change"))
    if b.get("list_id"):
        from ..agents.safety import move_gate
        move_gate(c, [(tid, b["list_id"])])  # 2.30.0 (#919): an agent moving it to other people waits for approval
    r = v1_call(task_update, tid, body={**b, "shift_chain": sc})
    out = v1_one(c, tid)
    ch = (r or {}).get("chain") or {}
    if ch.get("moved") or ch.get("skipped"):
        out["chain"] = ch  # 2.67.0 B (#1865): the dependent tasks moved along / left in place
    return jsonify(out)


@app.delete("/api/v1/tasks/<int:tid>")
@v1_view
def v1_task_delete(tid):
    """To the trash (restorable in the app); permanent deletion is not part of the API."""
    v1_args(())
    c = db()
    if _v1_live(c, tid) and list_role(c, c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()[0]) == "participant":
        raise Denied(403, tr("Participants cannot delete tasks"))
    trash_task(c, tid)
    bump(c)
    c.commit()
    return Response(status=204)


@app.put("/api/v1/tasks/<int:tid>/waiting")
@v1_view
def v1_task_waiting_set(tid):
    """2.1.0 (#335): {note?, until? (YYYY-MM-DD)} -- mark the task as waiting on external (or change note / date)."""
    v1_args(())
    c = db()
    _v1_live(c, tid)
    set_waiting(c, tid, v1_json())
    bump(c)
    c.commit()
    return jsonify(v1_one(c, tid))


@app.delete("/api/v1/tasks/<int:tid>/waiting")
@v1_view
def v1_task_waiting_clear(tid):
    v1_args(())
    c = db()
    _v1_live(c, tid)
    if clear_waiting(c, tid):
        bump(c)
        c.commit()
    return jsonify(v1_one(c, tid))


@app.post("/api/v1/tasks/<int:tid>/complete")
@v1_view
def v1_task_complete(tid):
    v1_args(())
    c = db()
    r = _v1_live(c, tid)
    if v1_json():
        raise UnknownFields(v1_json())
    if r["status"] != 0:  # already done: nothing happens (a retry of the same call is harmless)
        return jsonify({**v1_one(c, tid), "next_due": None})
    j = v1_call(task_complete, tid, body={})
    return jsonify({**v1_one(c, tid), "next_due": j.get("next_due")})


@app.post("/api/v1/tasks/<int:tid>/reopen")
@v1_view
def v1_task_reopen(tid):
    v1_args(())
    c = db()
    _v1_live(c, tid)
    v1_call(task_reopen, tid, body={})
    return jsonify(v1_one(c, tid))


@app.get("/api/v1/tasks/<int:tid>/milestone")
@v1_view
def v1_task_milestone(tid):
    """2.18.0 (#430): progress, tasks, burndown and release notes of a milestone task."""
    v1_args(())
    c = db()
    _v1_live(c, tid, write=False, full=True)
    return jsonify(ms_report(c, tid, me()))


@app.get("/api/v1/tasks/<int:tid>/subtasks")
@v1_view
def v1_subtasks(tid):
    v1_args(())
    c, uid = db(), me()
    _v1_live(c, tid, write=False)
    rows = load_tasks(c, f"parent_id=? AND deleted_at IS NULL AND list_id IN {vis_sql()} AND {tvis(c, uid)} ORDER BY sort, id",
                      (tid, uid, uid))
    return jsonify(data=[v1_task(d) for d in rows], next_cursor=None)


@app.post("/api/v1/tasks/<int:tid>/subtasks")
@v1_view
def v1_subtask_create(tid):
    v1_args(())
    c = db()
    _v1_live(c, tid)
    b = v1_task_in(v1_json(), tuple(k for k in V1_TASK_IN if k not in ("parent_id", "list_id")))
    j = v1_call(task_create, body={**b, "parent_id": tid})
    r = jsonify(v1_one(c, j["id"]))
    r.status_code, r.headers["Location"] = 201, f"{API_PREFIX}tasks/{j['id']}"
    return r


# 1.9.0: delete a tag completely (sidebar tag menu). Tags are per user: only my own tag rows are touched, the tasks
# stay. The answer lists the task ids, so the client's undo step can put the tag back (POST /api/tags/restore).
def _tag_arg(v):
    t = str(v or "").strip().lstrip("#")
    if not t or len(t) > 200:
        raise BadInput(tr("Invalid data"))
    return t


@app.get("/api/tags/count")
def tag_count():
    """{tasks, open}: how many of my tasks (not in the trash, in lists I see) carry the tag ?tag=."""
    c, uid = db(), me()
    try:
        tag = _tag_arg(request.args.get("tag"))
    except BadInput as e:
        return err(str(e))
    r = c.execute(f"""SELECT COUNT(*), COALESCE(SUM(CASE WHEN t.status=0 THEN 1 ELSE 0 END),0) FROM task_tags g JOIN tasks t ON t.id=g.task_id
                      WHERE g.user_id=? AND g.tag=? AND t.deleted_at IS NULL AND t.list_id IN {vis_sql()} AND {tvis(c, uid, "t.")}""",
                  (uid, tag, uid, uid)).fetchone()
    return jsonify(tasks=r[0], open=r[1])


@app.post("/api/tags/delete")
def tag_delete():
    """{tag}: removes my tag from every task (trash included); returns {ids, count} (count = tasks outside the trash)."""
    c, uid = db(), me()
    try:
        tag = _tag_arg(body().get("tag"))
    except BadInput as e:
        return err(str(e))
    rows = c.execute("""SELECT g.task_id, t.deleted_at FROM task_tags g JOIN tasks t ON t.id=g.task_id
                        WHERE g.user_id=? AND g.tag=?""", (uid, tag)).fetchall()
    ids = [r[0] for r in rows]
    c.execute("DELETE FROM task_tags WHERE user_id=? AND tag=?", (uid, tag))
    if ids:
        bump(c)
    c.commit()
    return jsonify(ok=True, ids=ids, count=sum(1 for r in rows if not r[1]))


@app.post("/api/tags/restore")
def tag_restore():
    """{tag, ids}: puts my tag back on these tasks (undo of a delete); tasks I no longer see are skipped."""
    b = body()
    c, uid = db(), me()
    try:
        tag = _tag_arg(b.get("tag"))
        ids = [int(x) for x in (b.get("ids") or [])][:20000]
    except (BadInput, TypeError, ValueError):
        return err(tr("Invalid data"))
    n = 0
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        n += c.execute(f"""INSERT INTO task_tags(task_id,user_id,tag) SELECT id, ?, ? FROM tasks
                           WHERE id IN ({','.join('?' * len(part))}) AND list_id IN {vis_sql()} AND {tvis(c, uid)} ON CONFLICT DO NOTHING""",
                       (uid, tag, *part, uid, uid)).rowcount
    if n:
        bump(c)
    c.commit()
    return jsonify(ok=True, count=n)


@app.get("/api/v1/tags")
@v1_view
def v1_tags():
    from ..agents.usage import v1_ltag
    v1_args(())
    c, uid = db(), me()
    rows = c.execute(f"""SELECT g.tag, COUNT(*) AS n, SUM(CASE WHEN t.status=0 THEN 1 ELSE 0 END) AS open FROM task_tags g
                         JOIN tasks t ON t.id=g.task_id WHERE g.user_id=? AND t.deleted_at IS NULL AND t.list_id IN {vis_sql()}
                         AND {tvis(c, uid, "t.")} GROUP BY g.tag ORDER BY lower(g.tag)""", (uid, uid, uid)).fetchall()
    out = [{"name": r["tag"], "tasks": r["n"], "open": r["open"], "kind": "personal"} for r in rows]
    for lid in [d["id"] for d in visible_lists(c, uid)]:  # 2.0.0: the list tags of the lists I see
        out += [{**v1_ltag(c, r), "kind": "list"} for r in c.execute("SELECT * FROM list_tags WHERE list_id=? ORDER BY sort, lower(name)", (lid,))]
    return jsonify(data=out, next_cursor=None)


def v1_comment(c, d, names):
    au = c.execute("SELECT kind FROM users WHERE id=?", (d["user_id"],)).fetchone() if d["user_id"] else None
    return {"id": d["id"], "task_id": d.get("task_id"),
            "author": {"id": d["user_id"], "name": names.get(d["user_id"], "") or d.get("ext_name") or "", "agent": bool(au and au["kind"] == "agent"),
                       **({"customer": True} if d.get("ext_name") else {})},  # 2.50.0 (#329): a customer's comment through the public link
            "reactions": d.get("reactions") or [], "suggestion": d.get("suggestion"),
            "body": d["body"], "text": comment_plain(c, d["body"]), "mentions": d["mentions"], "created_at": d["created_at"],
            "edited_at": d["edited_at"], "attachments": [{k: a[k] for k in ("id", "name", "mime", "size")} for a in d["attachments"]],
            "reply_to": d.get("reply_to"), "reply": d.get("reply"),  # 2.33.0 (#1076)
            # 2.41.0 (#1383): answer buttons / approval card of an agent's comment, the answer and its state
            "choices": d.get("choices"), "choice": d.get("choice"), "choice_state": d.get("choice_state"),
            "portal": bool(d.get("portal"))}  # 2.63.0 B (#1513): the customer sees it (public answer / their own comment)


@app.get("/api/v1/tasks/<int:tid>/comments")
@v1_view
def v1_comments(tid):
    from ..collab.reactions import with_reactions
    v1_args(())
    c = db()
    _v1_live(c, tid, write=False, full=True)
    rows = c.execute("SELECT * FROM comments WHERE task_id=? AND deleted_at IS NULL ORDER BY id", (tid,)).fetchall()
    atts = att_dicts(c, "task_id=? AND comment_id IS NOT NULL", (tid,))
    names = user_names(c, [r["user_id"] for r in rows])
    from ..collab.replies import with_replies
    from ..collab.cchoice import lv_with_choices
    ds = lv_with_choices(c, tid, rows, with_replies(c, "c", with_reactions(c, [{**comment_dict(r, atts), "task_id": tid} for r in rows])))
    return jsonify(data=[v1_comment(c, d, names) for d in ds], next_cursor=None)


@app.post("/api/v1/tasks/<int:tid>/comments")
@v1_view
def v1_comment_create(tid):
    v1_args(())
    b = v1_json()
    # 2.2.1 (#359): 400 unknown_field; 2.33.0 (#1076): reply_to; 2.41.0 (#1383): choices / multi / approval / expires_in
    reject_unknown(b, ("body", "suggestion", "reply_to", "choices", "multi", "approval", "expires_in", "portal"))  # 2.63.0 B (#1513): + portal
    if not isinstance(b.get("body"), str):
        raise BadInput(tr("Expected {0}", '{"body": "..."}'))
    c = db()
    _v1_live(c, tid, write=False, full=True)  # view-only members may comment (as in the app)
    if b.get("portal") not in (None, False, 0, "0", "false", "") and not any(b.get(k) for k in ("suggestion", "choices", "approval")):
        # 2.126.0 B (#1979 G5): an agent's answer to a customer waits for a person (need_approval: agents only)
        from ..api.scopes import need_approval
        from ..team.portal import pt_comment_flag
        if pt_comment_flag(c, tid, me(), b["portal"]):
            t = c.execute("SELECT title, list_id FROM tasks WHERE id=?", (tid,)).fetchone()
            need_approval(c, N_("Answer the customer of the task “{0}”"), (t["title"][:80],), list_id=t["list_id"], task_id=tid)
    j = v1_call(comment_create, tid, body={"body": b["body"], **{k: b[k] for k in ("suggestion", "reply_to", "choices", "multi", "approval",
                                                                                    "expires_in", "portal") if k in b}})
    return jsonify(v1_comment(c, {**j, "task_id": tid}, user_names(c, [me()]))), 201


def v1_entry(e):
    return {k: e[k] for k in ("id", "user_id", "user_name", "task_id", "list_id", "title", "start", "end", "seconds", "rounded",
                              "note", "source", "running", "billable")} | {"billed": bool(e.get("billed"))}  # 2.144.6 A (#2053)


@app.get("/api/v1/time/entries")
@v1_view
def v1_time_entries():
    """Time entries I can see (mine, or everyone's in shared lists with scope=all) whose start lies in [from, to]
    (local dates, default: the last 7 days), newest first."""
    need_time()
    v1_feature("time")
    a = v1_args(("from", "to", "scope", "list_id", "task_id", "limit", "cursor"))
    for k in ("from", "to"):
        if a.get(k) and not valid_date(a[k]):
            raise BadInput(tr("Invalid value: {0}", k))
    if a.get("scope", "mine") not in ("mine", "all"):
        raise BadInput(tr("Invalid value: {0}", "scope"))
    c, uid = db(), me()
    q = {"from": a.get("from") or (local_now().date() - timedelta(days=6)).isoformat(), "to": a.get("to") or local_now().date().isoformat(),
         "scope": a.get("scope", "mine")}
    if a.get("task_id"):
        q["task_id"] = str(as_int(a["task_id"], "task_id", 1))
    from ..personal.timetrack import n43_admin_lists
    # 2.63.0 (#1523): as /api/time/entries (agents and the entries of one task: unchanged)
    rows, _, _, _ = time_rows(c, uid, q, own=None if q.get("task_id") else n43_admin_lists(c, uid))
    vis, ref, rm = vis_ids(c, uid), now_utc(), time_rounding(usettings(c, uid))
    out = [entry_out(r, uid, vis, ref, rm) for r in rows]
    if a.get("list_id"):
        lid = as_int(a["list_id"], "list_id", 1)
        out = [e for e in out if e["list_id"] == lid]
    out.reverse()
    return v1_page([v1_entry(e) for e in out], cursor_dec("o", a.get("cursor")), v1_limit(a))


@app.post("/api/v1/time/entries")
@v1_view
def v1_time_create():
    v1_args(())
    need_time()
    v1_feature("time")
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("task_id", "list_id", "start", "end", "minutes", "note", "billable"))  # 2.144.6 A (#2053): + billable
    if unknown:
        raise UnknownFields(unknown)
    j = v1_call(time_create, body=b)
    return jsonify(v1_entry(j)), 201


def v1_habit(c, h):
    since = (local_now().date() - timedelta(days=29)).isoformat()
    logs = {r["day"]: r["count"] for r in c.execute("SELECT day, count FROM habit_logs WHERE habit_id=? AND day>=? AND count>0",
                                                    (h["id"], since))}
    return {"id": h["id"], "name": h["name"], "color": h["color"], "goal": h["goal"], "days": h["days"], "per_week": h["per_week"],
            "remind_at": h["remind_at"], "remind_times": habit_times(h),  # 2.140.0 C (#2135)
            "archived": bool(h["archived"]), "today": logs.get(local_now().date().isoformat(), 0), "last_30_days": logs}


@app.get("/api/v1/habits")
@v1_view
def v1_habits():
    v1_args(())
    c = db()
    return jsonify(data=[v1_habit(c, h) for h in c.execute("SELECT * FROM habits WHERE user_id=? ORDER BY archived, sort, id", (me(),))],
                   next_cursor=None)


@app.post("/api/v1/habits/<int:hid>/checkin")
@v1_view
def v1_habit_checkin(hid):
    """{date?: YYYY-MM-DD (default today), count?: absolute count (default: one more), note?}."""
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("date", "count", "note"))
    if unknown:
        raise UnknownFields(unknown)
    c = db()
    need_habit(c, hid)
    day = b.get("date") or local_now().date().isoformat()
    if not valid_date(day) or day > (local_now().date() + timedelta(days=1)).isoformat():
        raise BadInput(tr("Invalid value: {0}", "date"))
    old = c.execute("SELECT count FROM habit_logs WHERE habit_id=? AND day=?", (hid, day)).fetchone()
    cnt = as_int(b["count"], "count", 0, 1000) if "count" in b else (old[0] if old else 0) + 1
    fwd = {"day": day, "count": cnt}
    if "note" in b:
        if not isinstance(b["note"], str):
            raise BadInput(tr("Invalid value: {0}", "note"))
        fwd["note"] = b["note"]
    v1_call(habit_log, hid, body=fwd)
    return jsonify({**v1_habit(c, c.execute("SELECT * FROM habits WHERE id=?", (hid,)).fetchone()), "date": day, "count": cnt})


@app.get("/api/v1/search")
@v1_view
def v1_search():
    if request.args.get("scope") == "messages":  # 2.33.0 (#1080): comments, team chat, agent chats
        from ..collab.msgsearch import v1_search_messages
        return v1_search_messages()
    a = v1_args(("q", "limit", "cursor", "scope", "semantic", "fulltext"))  # 2.59.0 B (#1375): + semantic; 2.116.0 B: + fulltext
    if a.get("fulltext") not in (None, "", "0", "1"):
        raise BadInput(tr("Invalid value: {0}", "fulltext"))
    if a.get("fulltext") == "1" and a.get("scope") in (None, "", "tasks"):  # 2.116.0 B (#2065): ranked, with comments
        from ..tasks.ftsearch import fts_v1
        return fts_v1(a, v1_task)
    if a.get("scope") not in (None, "", "tasks"):
        raise BadInput(tr("Invalid value: {0}", "scope"))
    if a.get("semantic") not in (None, "", "0", "1"):
        raise BadInput(tr("Invalid value: {0}", "semantic"))
    q = (a.get("q") or "").strip()
    if not q or len(q) > 200:
        raise BadInput(tr("Invalid value: {0}", "q"))
    # audit G4: the recognised text of files (and file_hit) only for a token that may read the files
    rows = search_tasks(db(), me(), q, 2000, files=g.get("auth_via") != "token" or "attachments:read" in (g.get("scopes") or set()))
    if a.get("semantic") == "1":  # 2.59.0 B (#1375): + tasks of similar meaning (only visible ones, flag similar)
        from ..tasks.related import rt9_search_extend
        rows = rt9_search_extend(db(), me(), q, rows, len(rows) + 20)
    return v1_page([{**v1_task(d), **({"similar": True} if d.get("similar") else {})} for d in rows], cursor_dec("o", a.get("cursor")), v1_limit(a))


@app.post("/api/v1/import/<source>")
@v1_view
def v1_import(source):
    """package C: the importers of Settings > Data (multipart: file + options; dry_run=1 = preview only)."""
    v1_args(())
    return jsonify(imp_request(source))


@app.post("/api/v1/imports/<int:iid>/undo")
@v1_view
def v1_import_undo(iid):
    v1_args(())
    return jsonify(imp_undo(db(), me(), iid))


@app.get("/api/v1/admin/users")
@v1_view
def v1_admin_users():
    v1_args(())
    c = db()
    return jsonify(data=[{"id": u["id"], "username": u["username"], "display_name": u["display_name"] or u["username"],
                          "is_admin": bool(u["is_admin"]), "disabled": bool(u["disabled"]), "created_at": u["created_at"],
                          "has_password": bool(u["password_hash"]), "sso": bool(u["proxy_login"]), "two_factor": bool(twofa_methods(c, u)),
                          "api_tokens": c.execute("SELECT COUNT(*) FROM api_tokens WHERE user_id=?", (u["id"],)).fetchone()[0]}
                         for u in c.execute("SELECT * FROM users ORDER BY id")], next_cursor=None)


@app.get("/api/v1/admin/status")
@v1_view
def v1_admin_status():
    v1_args(())
    c = db()
    info, n = update_state(c), lambda q: c.execute(q).fetchone()[0]
    latest, cur = semver(info.get("latest")), semver(APP_VERSION)
    with system_ctx(c):  # 2.37.0 (#1150): instance counts over every organisation (numbers only)
        n_lists = n("SELECT COUNT(*) FROM lists")
    return jsonify(version=APP_VERSION, users=n("SELECT COUNT(*) FROM users WHERE disabled=0"), lists=n_lists,
                   open_tasks=n("SELECT COUNT(*) FROM tasks WHERE status=0 AND deleted_at IS NULL"),
                   update_available=bool(latest and cur and latest > cur), latest_version=info.get("latest") or None,
                   update_checked_at=info.get("checked_at") or None, update_error=info.get("error") or None,
                   backups={"enabled": BK_ON_ENV and gsetting(c, "bk_on") == "1", "last_ok": gsetting(c, "bk_last_ok") or None},
                   webhooks_pending=n("SELECT COUNT(*) FROM webhook_queue"))


@app.get("/api/v1/admin/orgs/activity")
@v1_view
def v1_admin_orgs_activity():
    """2.143.0 D (#2156): numbers per organisation (+ the people without one); admins only, no names or contents."""
    v1_args(())
    if not g.user["is_admin"]:
        raise Denied(403)
    from ..admin.hosting import org_activity
    return jsonify(org_activity(db()))


@app.errorhandler(404)
def not_found(e):
    from ..lists.public import BOT_ERROR, pub_gone, pub_html
    if request.path.startswith(API_PREFIX):
        return v1_err(404, tr("Not found"))
    if request.path.startswith(PUB_PREFIX):
        return pub_gone()
    if request.method == "GET" and "text/html" in (request.headers.get("Accept") or "") and not request.path.startswith("/static/"):
        lg = _accept_lang()  # 2.14.0: a page that does not exist: the figure (2.136.0: the bot) + a way back (no user data, like /s/)
        r = pub_html(tr("Page not found", lg=lg), f'<div class="msg">{BOT_ERROR}<h1>{html.escape(tr("Page not found", lg=lg))}</h1>'
                     f'<p>{html.escape(tr("This address does not exist.", lg=lg))}</p><p><a class="btn" href="/">'
                     f'{html.escape(tr("Open {0}", APP_NAME, lg=lg))}</a></p></div>', lg, 404, foot=False)
        return r
    return e


@app.errorhandler(405)
def not_allowed(e):
    if request.path.startswith(API_PREFIX):
        return v1_err(405, tr("Method not allowed"))
    return e


# ---- OpenAPI 3.1 description of /api/v1 (served at /api/v1/openapi.json; built once)
_SPEC = {}


# ---- 2.10.0 (#441): groups in the REST API (and the MCP server): read every group with its members, the groups a list is
# shared with (directly or through a folder), share a list with a group (owner / list admin), take a group task.
def v1_group(d):
    return {"id": d["id"], "name": d["name"], "synced": d["synced"], "members": d["members"]}


@app.get("/api/v1/groups")
@v1_view
def v1_groups():
    v1_args(())
    c = db()
    mine = set(grp_of_user(c, me()))
    return jsonify(data=[{**v1_group(d), "mine": d["id"] in mine} for d in groups_for(c)], next_cursor=None)


@app.get("/api/v1/groups/<int:gid>")
@v1_view
def v1_group_get(gid):
    v1_args(())
    c = db()
    d = grp_dict(c, need_group(c, gid), full=False)
    from ..accounts.orgs import instance_mode, visible_people
    vis = visible_people(c, me()) if instance_mode(c) == "workspaces" else None
    if vis is not None:  # 2.30.0 (#1036): only the members one may see (as GET /groups)
        d["members"] = [m for m in d["members"] if m["user_id"] in vis]
    return jsonify({**v1_group(d), "mine": gid in grp_of_user(c, me())})


@app.get("/api/v1/lists/<int:lid>/groups")
@v1_view
def v1_list_groups(lid):
    v1_args(())
    return jsonify(data=v1_call(list_groups_get, lid)["groups"], next_cursor=None)


def _v1_gid(group_id):
    try:
        return int(group_id)
    except (TypeError, ValueError):
        raise Denied(404) from None


@app.put("/api/v1/lists/<int:lid>/groups/<group_id>")
@v1_view
def v1_list_group_set(lid, group_id):
    from ..api.scopes import need_approval, ROLE_WORD
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("role",))
    c = db()
    need_list(c, lid, write=False, manage=True)
    from ..lists.groups import need_group
    gr = need_group(c, _v1_gid(group_id))  # 2.86.0 (N29): 404 before the job title names a group the agent cannot see
    if gr:  # 2.15.0 (#479): sharing by an agent waits for a person's approval
        need_approval(c, N_("Share the list “{0}” with the group “{1}” ({2})"),
                      (c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0], gr["name"],
                       ("tr", ROLE_WORD.get(str(b.get("role") or "edit"), "Member"))), list_id=lid)
    v1_call(list_group_set, lid, _v1_gid(group_id), body=b)
    return jsonify(data=v1_call(list_groups_get, lid)["groups"], next_cursor=None)


@app.delete("/api/v1/lists/<int:lid>/groups/<group_id>")
@v1_view
def v1_list_group_del(lid, group_id):
    from ..api.scopes import need_approval
    v1_args(())
    c = db()
    need_list(c, lid, write=False, manage=True)
    gr = c.execute("SELECT g.name FROM groups g JOIN group_shares s ON s.group_id=g.id WHERE g.id=? AND s.list_id=?",
                   (_v1_gid(group_id), lid)).fetchone()  # 2.86.0 (N29): only a group the list is shared with
    if gr:
        need_approval(c, N_("Stop sharing the list “{0}” with the group “{1}”"), (c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0], gr[0]),
                      list_id=lid)
    v1_call(list_group_del, lid, _v1_gid(group_id), body={})
    return jsonify(ok=True)


@app.post("/api/v1/tasks/<int:tid>/take")
@v1_view
def v1_task_take(tid):
    v1_args(())
    if v1_json():
        raise UnknownFields(v1_json())
    c = db()
    _v1_live(c, tid, write=False)
    v1_call(task_take_web, tid, body={})
    return jsonify(v1_one(c, tid))
