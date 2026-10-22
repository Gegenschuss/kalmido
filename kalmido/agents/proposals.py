"""Agent proposals, validation helpers, requests from people to agents."""
import json
import re
import time
from datetime import timedelta
from flask import g, jsonify, request

from ..core.config import app, PUBLIC_URL
from ..core.pg import insert_id
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, now_utc, iso_ms
from ..accounts.session import me
from ..accounts.pictures import avatar_url
from ..core.access import (
    collab_all, Denied, list_people, list_role, my_inbox, my_max_sort, need_collab, need_list, need_task, WRITE_ROLES,
)
from ..core.state import visible_lists, visible_sections
from ..lists.lists import list_created, clean_folder, FOLDER_MAX
from ..tasks.validation import as_int, check_parent, DURATION_MAX, log_act, PRIORITIES, TITLE_MAX, valid_date, valid_hm
from ..tasks.tasks import my_tags
from ..tasks.lifecycle import apply_update, do_delete, restore_task
from ..tasks.attachments import need_attachment, send_stored
from ..collab.comments import collab_user, lang_of, task_event, user_names
from ..collab.news import news_add, notif_ok
from ..core.errors import BadInput, UnknownFields
from ..tasks.dependencies import newtask_events
from ..lists.projects import list_purge_files, list_row_purge
from ..notify.push import push_prio, push_reachable
from ..api.v1 import _v1_live, PRIO_VALUES, v1_one
from ..api.common import v1_args, v1_err, v1_json, v1_view
from ..tasks.dayplan import dayplan_day, dayplan_input, dayplan_mode, dayplan_validate, dayplan_want
from ..agents.core import (
    agent_active, agent_emit, agent_ids, agent_online, agent_public, agent_row, agent_shares, AGENT_TYPING_S,
    agent_typing_to, agents_for, is_agent, job_dict, JOB_TITLE_MAX, list_sections, need_agent, need_chat_agent,
    tidy_agent_of,
)
from ..collab.reactions import clean_suggestion, tidy_apply
from ..agents.chat import (
    chat_delivered, chat_dict, chat_file_access, chat_newest, jn9_chat_jobs, chat_file_delete, chat_files_of, chat_input, chat_one, chat_post,
    chat_react_req, chat_reactions_of, chat_unlink_trimmed, cx_notice_post, APPROVAL_PUSH_HOUR,
)


# ---- 2.3.0 (#260 #261 #262 #263): agent PROPOSALS. Kalmido never runs a model itself and an agent must not silently create
# structure that belongs to it. So a person asks an agent for a proposal (a job of kind project | subtasks | triage |
# extract, event job_request with exactly the input the person chose to send), the agent answers with ONE structured,
# validated payload (POST /api/v1/agent/jobs/<id>/proposal, MCP submit_proposal) and the person reviews it: every item can
# be ticked off and edited, "Apply selected" creates / changes everything AS THAT PERSON (owner, creator, history line "from
# a proposal by <agent>"), one undo step; "Discard" tells the agent. Which agents a person may ask: agents.proposals =
# shared (default: people who share at least one list with the agent; instance admins count as sharing, as for the chat)
# | all (every person of the instance) | off. The agent never gets general access: the job input is the only data it sees
# (e.g. the selected inbox items, the lists the person ticked), stored with the job and deleted with it (PROP_KEEP_DAYS).
PROP_KINDS = ("project", "subtasks", "triage", "extract", "dayplan", "cleanup")  # 2.10.0 (#440): dayplan; 2.39.0 (#1151): cleanup
PROP_KINDS += ("time", "shoot")  # 2.51.0 C (#1353 #1355): time entries from events, shoot days (agents/agenttime.py, hub/agentdispo.py)
PROP_KINDS_AGENT = ("time", "shoot")  # 2.51.0 C: the agent proposes these itself (POST /api/v1/agent/proposals/time|shoot), never on request
PROP_STATES = ("requested", "ready", "applied", "discarded")
PROP_MODES = ("off", "shared", "all")
PROP_KINDS += ("inquiry", "setup")  # 2.51.0 B (#1351 #1358): an inquiry becomes a project, the setup assistant (agents/propkinds2.py)
PROP_KINDS += ("layout",)  # 2.55.0 (#1066): the agent proposes how a view is arranged (agents/lyprop.py), never on request
PROP_KINDS += ("import",)  # 2.68.0 (#1839): the agent proposes old data for the office (agents/importprop.py), never on request
PROP_KINDS += ("merge",)  # 2.70.0 B (#1357): duplicate contacts merged (agents/dupprop.py), on request
PROP_KINDS += ("notice",)  # 2.70.0 C (#1359): a contract's notice deadline as a note (agents/contractprop.py), never on request
PROP_KINDS += ("rule",)  # 2.71.0 A (#1457): the agent proposes a rule of a list (lists/rules.py), never on request
PROP_KINDS += ("office_text", "doc_summary", "report")  # 2.126.1 A (#2123 #2124): office texts, a receipt summary, the client report (agents/asstprop.py), on request
PROP_KINDS += ("sheet_tasks",)  # 2.126.1 B (#2125): table rows -> tasks, proposed by the agent itself (agents/sheetprop.py)
PROP_KINDS += ("ideas",)  # 2.156.0 A (#1201): sub-branches for a branch of the mind map, on request (agents/ideaprop.py)
PROP_MAX_ITEMS = 200                    # entries one proposal may create / change (tasks + subtasks)
PROP_MAX_BYTES = 256 * 1024             # JSON body of a proposal
PROP_TITLE_MAX, PROP_NOTES_MAX, PROP_NAME_MAX, PROP_SUMMARY_MAX = 300, 5000, 120, 2000
PROP_SECTIONS_MAX, PROP_SUBS_MAX, PROP_DEPS_MAX, PROP_TAGS_MAX, PROP_TAG_MAX = 30, 50, 20, 10, 60
PROP_TEXT_MAX, PROP_HINT_MAX = 50000, 2000   # pasted briefing / notes, the hint of "Break down"
PROP_TRIAGE_MAX, PROP_LISTS_MAX = 100, 200   # inbox items per request, lists offered
PROP_OPEN_MAX = 10                      # open (running / waiting) proposal requests per person
PROP_KEEP_DAYS = 30                     # proposal jobs (with their input) are removed after this many days
PROP_TITLES = {"project": N_("Project from a briefing"), "subtasks": N_("Break down: {0}"), "triage": N_("Sort the basket"),
               "dayplan": N_("Day plan: {0}"),
               "extract": N_("Tasks from notes: {0}")}
PROP_LIMITS = {"max_items": PROP_MAX_ITEMS, "max_bytes": PROP_MAX_BYTES, "title_max": PROP_TITLE_MAX, "notes_max": PROP_NOTES_MAX,
               "name_max": PROP_NAME_MAX, "summary_max": PROP_SUMMARY_MAX, "sections_max": PROP_SECTIONS_MAX,
               "subtasks_max": PROP_SUBS_MAX, "depends_max": PROP_DEPS_MAX, "tags_max": PROP_TAGS_MAX}
_PROP_CLEAN = {"at": 0.0}


def prop_mode(a):
    try:
        m = a["proposals"]
    except (KeyError, IndexError):
        m = "shared"
    return m if m in PROP_MODES else "shared"


def prop_agent_ok(c, a, uid):
    """May person uid ask agent a (agent_row) for proposals?"""
    if not agent_active(a) or not collab_all():
        return False
    u = c.execute("SELECT kind, disabled FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["kind"] == "agent" or u["disabled"]:
        return False
    m = prop_mode(a)
    return m == "all" or (m == "shared" and agent_shares(c, a["user_id"], uid))


def prop_agents(c, uid):
    """The agents uid may ask for a proposal: [{id, name, avatar, limit_reached}]."""
    from ..agents.usage import usage_block
    if not collab_all() or not uid:
        return []
    rows = c.execute("""SELECT a.*, u.username, u.display_name, u.avatar, u.disabled FROM agents a JOIN users u ON u.id=a.user_id
                        WHERE u.kind='agent' ORDER BY u.id""").fetchall()
    out = []
    for a in rows:
        if prop_agent_ok(c, a, uid):
            u = c.execute("SELECT * FROM users WHERE id=?", (a["user_id"],)).fetchone()
            out.append({"id": a["user_id"], "name": a["display_name"] or a["username"], "avatar": avatar_url(u),
                        "limit_reached": bool(usage_block(c, a["user_id"])),
                        "online": agent_online(a) is not False})  # 2.10.0 (#440): offers "Let an agent plan" only when online
    return out


# ---- validation helpers (BadInput -> 400; UnknownFields -> 400 unknown_field)
def _p_keys(v, what, allowed):
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid value: {0}", what))
    unknown = [f"{what}.{k}" if what else k for k in v if k not in allowed]
    if unknown:
        raise UnknownFields(unknown)
    return v


def _p_str(v, what, mx, required=False, line=True):
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", what))
    v = re.sub(r"[\x00-\x08\x0b-\x1f]", "", v.replace("\r\n", "\n"))
    if line:
        v = re.sub(r"\s*\n\s*", " ", v)
    v = v.strip()
    if len(v) > mx:
        raise BadInput(tr("Too long: {0} (at most {1} characters)", what, mx))
    if required and not v:
        raise BadInput(tr("Missing field: {0}", what))
    return v


def _p_date(v, what):
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not valid_date(v):
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def _p_int(v, what, lo=1, hi=None):
    if isinstance(v, bool) or not isinstance(v, int) or v < lo or (hi is not None and v > hi):
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def _p_list(v, what, mx):
    if v is None:
        return []
    if not isinstance(v, list):
        raise BadInput(tr("Invalid value: {0}", what))
    if len(v) > mx:
        raise BadInput(tr("Too many entries: {0} (at most {1})", what, mx))
    return v


def _p_prio(v, what):
    if v in (None, ""):
        return None
    if isinstance(v, str) and v in PRIO_VALUES:
        return PRIO_VALUES[v]
    if isinstance(v, int) and not isinstance(v, bool) and v in PRIORITIES:
        return v
    raise BadInput(tr("Invalid value: {0}", what))


def _p_tags(v, what):
    out = []
    for i, t in enumerate(_p_list(v, what, PROP_TAGS_MAX)):
        t = _p_str(t, f"{what}[{i}]", PROP_TAG_MAX, True).lstrip("#").strip()
        if t and t.casefold() not in (x.casefold() for x in out):
            out.append(t)
    return out


def _p_deps(pairs, n, what):
    """Dependency edges (a waits on b, indices < n) -> sorted unique list; BadInput on a bad index or a cycle."""
    edges = set()
    for a, b in pairs:
        if not isinstance(a, int) or isinstance(a, bool) or not isinstance(b, int) or isinstance(b, bool) \
                or not 0 <= a < n or not 0 <= b < n or a == b:
            raise BadInput(tr("Invalid value: {0}", what))
        edges.add((a, b))
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
    state = {}

    def visit(x):  # iterative DFS: a cycle = a back edge
        stack = [(x, iter(adj.get(x, ())))]
        state[x] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                raise BadInput(tr("The dependencies contain a cycle"))
            elif not state.get(nxt):
                state[nxt] = 1
                stack.append((nxt, iter(adj.get(nxt, ()))))
    for x in list(adj):
        if not state.get(x):
            visit(x)
    return sorted(edges)


def prop_validate(kind, b, inp):
    """An agent's proposal b (dict) for a job of this kind with input inp -> the normalized proposal (BadInput otherwise)."""
    if not isinstance(b, dict):
        raise BadInput(tr("The body must be a JSON object"))
    if b.get("kind") not in (None, kind):
        raise BadInput(tr("This job expects a proposal of kind {0}", kind))
    common = ("kind", "summary")
    out = {"kind": kind, "summary": _p_str(b.get("summary"), "summary", PROP_SUMMARY_MAX, line=False)}
    if kind == "sheet_tasks":  # 2.126.1 B (#2125)
        from ..agents.sheetprop import sht_validate
        return {**out, **sht_validate(b, inp)}
    if kind == "project":
        _p_keys(b, "", (*common, "name", "folder", "sections", "tasks"))
        out["name"] = _p_str(b.get("name"), "name", PROP_NAME_MAX, True)
        out["folder"] = _p_str(b.get("folder"), "folder", FOLDER_MAX)
        secs = []
        for i, s in enumerate(_p_list(b.get("sections"), "sections", PROP_SECTIONS_MAX)):
            s = _p_str(s, f"sections[{i}]", 100, True)
            if s.casefold() not in (x.casefold() for x in secs):
                secs.append(s)
        out["sections"] = secs
        tasks, total, deps = [], 0, []
        raw = _p_list(b.get("tasks"), "tasks", PROP_MAX_ITEMS)
        if not raw:
            raise BadInput(tr("Missing field: {0}", "tasks"))
        for i, t in enumerate(raw):
            w = f"tasks[{i}]"
            _p_keys(t, w, ("title", "notes", "section", "due", "start", "priority", "subtasks", "depends_on"))
            sec = _p_str(t.get("section"), w + ".section", 100)
            if sec:
                hit = next((x for x in secs if x.casefold() == sec.casefold()), None)
                if hit is None:
                    raise BadInput(tr("Unknown section: {0}", sec))
                sec = hit
            due, start = _p_date(t.get("due"), w + ".due"), _p_date(t.get("start"), w + ".start")
            if not due:
                start = None
            elif start and start > due:
                start = due
            subs = []
            for j, s in enumerate(_p_list(t.get("subtasks"), w + ".subtasks", PROP_SUBS_MAX)):
                sw = f"{w}.subtasks[{j}]"
                _p_keys(s, sw, ("title", "notes", "due"))
                subs.append({"title": _p_str(s.get("title"), sw + ".title", PROP_TITLE_MAX, True),
                             "notes": _p_str(s.get("notes"), sw + ".notes", PROP_NOTES_MAX, line=False),
                             "due": _p_date(s.get("due"), sw + ".due")})
            dep = _p_list(t.get("depends_on"), w + ".depends_on", PROP_DEPS_MAX)
            deps += [(i, d) for d in dep]
            total += 1 + len(subs)
            tasks.append({"title": _p_str(t.get("title"), w + ".title", PROP_TITLE_MAX, True),
                          "notes": _p_str(t.get("notes"), w + ".notes", PROP_NOTES_MAX, line=False), "section": sec or None,
                          "due": due, "start": start, "priority": _p_prio(t.get("priority"), w + ".priority") or 0,
                          "subtasks": subs, "depends_on": sorted({d for d in dep})})
        if total > PROP_MAX_ITEMS:
            raise BadInput(tr("Too many entries: {0} (at most {1})", "tasks + subtasks", PROP_MAX_ITEMS))
        _p_deps(deps, len(tasks), "depends_on")
        out["tasks"] = tasks
    elif kind == "subtasks":
        _p_keys(b, "", (*common, "items", "dependencies"))
        raw = _p_list(b.get("items"), "items", PROP_MAX_ITEMS)
        if not raw:
            raise BadInput(tr("Missing field: {0}", "items"))
        items = []
        for i, t in enumerate(raw):
            w = f"items[{i}]"
            _p_keys(t, w, ("title", "notes", "due", "estimate"))
            est = t.get("estimate")
            items.append({"title": _p_str(t.get("title"), w + ".title", PROP_TITLE_MAX, True),
                          "notes": _p_str(t.get("notes"), w + ".notes", PROP_NOTES_MAX, line=False),
                          "due": _p_date(t.get("due"), w + ".due"),
                          "estimate": None if est in (None, "") else _p_int(est, w + ".estimate", 1, DURATION_MAX)})
        pairs = []
        for i, d in enumerate(_p_list(b.get("dependencies"), "dependencies", PROP_MAX_ITEMS * 2)):
            if not isinstance(d, list) or len(d) != 2:
                raise BadInput(tr("Invalid value: {0}", f"dependencies[{i}]"))
            pairs.append(tuple(d))
        out["items"], out["dependencies"] = items, [list(x) for x in _p_deps(pairs, len(items), "dependencies")]
    elif kind == "triage":
        _p_keys(b, "", (*common, "items"))
        ids = {x["task_id"] for x in inp.get("items", [])}
        lists = {x["id"]: {s["id"] for s in x.get("sections", [])} for x in inp.get("lists", [])}
        items, seen = [], set()
        raw = _p_list(b.get("items"), "items", PROP_TRIAGE_MAX)
        if not raw:
            raise BadInput(tr("Missing field: {0}", "items"))
        for i, t in enumerate(raw):
            w = f"items[{i}]"
            _p_keys(t, w, ("task_id", "list_id", "section_id", "tags", "priority", "due", "rewrite_title"))
            tid = _p_int(t.get("task_id"), w + ".task_id")
            if tid not in ids or tid in seen:
                raise BadInput(tr("Invalid value: {0}", w + ".task_id"))
            seen.add(tid)
            lid = t.get("list_id")
            lid = None if lid in (None, "") else _p_int(lid, w + ".list_id")
            if lid is not None and lid not in lists:
                raise BadInput(tr("Invalid value: {0}", w + ".list_id"))
            sid = t.get("section_id")
            sid = None if sid in (None, "") else _p_int(sid, w + ".section_id")
            if sid is not None and (lid is None or sid not in lists[lid]):
                raise BadInput(tr("Invalid value: {0}", w + ".section_id"))
            items.append({"task_id": tid, "list_id": lid, "section_id": sid, "tags": _p_tags(t.get("tags"), w + ".tags"),
                          "priority": _p_prio(t.get("priority"), w + ".priority"), "due": _p_date(t.get("due"), w + ".due"),
                          "rewrite_title": _p_str(t.get("rewrite_title"), w + ".rewrite_title", PROP_TITLE_MAX) or None})
        out["items"] = items
    elif kind == "extract":
        _p_keys(b, "", (*common, "tasks"))
        members = {m["id"] for m in inp.get("members", [])}
        raw = _p_list(b.get("tasks"), "tasks", PROP_MAX_ITEMS)
        if not raw:
            raise BadInput(tr("Missing field: {0}", "tasks"))
        tasks = []
        for i, t in enumerate(raw):
            w = f"tasks[{i}]"
            _p_keys(t, w, ("title", "notes", "assignee_id", "due", "section"))
            aid = t.get("assignee_id")
            aid = None if aid in (None, "") else _p_int(aid, w + ".assignee_id")
            if aid is not None and aid not in members:
                raise BadInput(tr("Invalid value: {0}", w + ".assignee_id"))
            tasks.append({"title": _p_str(t.get("title"), w + ".title", PROP_TITLE_MAX, True),
                          "notes": _p_str(t.get("notes"), w + ".notes", PROP_NOTES_MAX, line=False),
                          "assignee_id": aid, "due": _p_date(t.get("due"), w + ".due"),
                          "section": _p_str(t.get("section"), w + ".section", 100) or None})
        out["tasks"] = tasks
    elif kind == "dayplan":  # 2.10.0 (#440)
        out.update(dayplan_validate(b, inp))
    elif kind in ("inquiry", "setup"):  # 2.51.0 B (#1351 #1358)
        from ..agents.propkinds2 import pk2_validate
        out.update(pk2_validate(kind, b, inp))
    elif kind == "cleanup":  # 2.39.0 (#1151): tidy up a list (agents/cleanup.py)
        from ..agents.cleanup import cln_validate
        _p_keys(b, "", (*common, "items"))
        out.update(cln_validate(b, inp))
    elif kind in PROP_KINDS_AGENT:  # 2.51.0 C (#1353 #1355)
        from ..agents.agenttime import atm_prop_validate
        out.update(atm_prop_validate(kind, b, inp))
    elif kind == "layout":  # 2.55.0 (#1066)
        from ..agents.lyprop import lyp_validate
        out.update(lyp_validate(b, inp))
    elif kind == "import":  # 2.68.0 (#1839)
        from ..agents.importprop import aim_validate
        out.update(aim_validate(b, inp))
    elif kind == "merge":  # 2.70.0 B (#1357)
        from ..agents.dupprop import dup_validate
        out.update(dup_validate(b, inp))
    elif kind == "notice":  # 2.70.0 C (#1359)
        from ..agents.contractprop import ctr_validate
        out.update(ctr_validate(b, inp))
    elif kind == "rule":  # 2.71.0 A (#1457)
        from ..lists.rules import rul_prop_validate
        out.update(rul_prop_validate(b, inp))
    elif kind in ("office_text", "doc_summary", "report"):  # 2.126.1 A (#2123 #2124): texts worded by the agent (agents/asstprop.py)
        from ..agents.asstprop import ast_validate
        out.update(ast_validate(kind, b, inp))
    elif kind == "ideas":  # 2.156.0 A (#1201)
        from ..agents.ideaprop import idp_validate
        out.update(idp_validate(b, inp))
    return out


# ---- the request (a person asks an agent)
def prop_input(c, uid, kind, b):
    """The job input for a request body b -> (input, title, task_id, list_id). Only what the person chose to send."""
    if kind in ("inquiry", "setup"):  # 2.51.0 B (#1351 #1358)
        from ..agents.propkinds2 import pk2_input
        return pk2_input(c, uid, kind, b)
    if kind == "merge":  # 2.70.0 B (#1357): one address book, only names / company / e-mails / phones
        from ..agents.dupprop import dup_input
        return dup_input(c, uid, b)
    if kind == "project":
        _p_keys(b, "", ("agent_id", "kind", "text", "file_name", "folder"))
        inp = {"text": _p_str(b.get("text"), "text", PROP_TEXT_MAX, True, line=False),
               "file_name": _p_str(b.get("file_name"), "file_name", 200) or None,
               "folder": clean_folder(b.get("folder")) or None}
        return inp, tr(PROP_TITLES["project"]), None, None
    if kind == "subtasks":
        _p_keys(b, "", ("agent_id", "kind", "task_id", "hint"))
        tid = _p_int(b.get("task_id"), "task_id")
        need_task(c, tid)
        t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if t["deleted_at"] or t["status"] != 0:
            raise BadInput(tr("Only open tasks can be broken down"))
        if list_role(c, t["list_id"]) not in WRITE_ROLES:
            raise Denied(403)
        e = check_parent(c, None, tid)
        if e:
            raise BadInput(e)
        subs = [r[0] for r in c.execute("SELECT title FROM tasks WHERE parent_id=? AND deleted_at IS NULL ORDER BY sort, id", (tid,))]
        inp = {"task": {"id": tid, "title": t["title"], "notes": (t["content"] or "")[:PROP_TEXT_MAX], "due": t["due"],
                        "subtasks": subs[:100]},
               "hint": _p_str(b.get("hint"), "hint", PROP_HINT_MAX, line=False) or None}
        return inp, tr(PROP_TITLES["subtasks"], t["title"][:80]), tid, t["list_id"]
    if kind == "triage":
        _p_keys(b, "", ("agent_id", "kind", "task_ids", "lists"))
        inbox = my_inbox(c, uid)
        q = "SELECT id, title, content FROM tasks WHERE list_id=? AND parent_id IS NULL AND status=0 AND deleted_at IS NULL"
        if b.get("task_ids") in (None, "all"):
            rows = c.execute(q + " ORDER BY created_at DESC, id DESC LIMIT ?", (inbox, PROP_TRIAGE_MAX)).fetchall()
        else:
            ids = [_p_int(x, "task_ids") for x in _p_list(b.get("task_ids"), "task_ids", PROP_TRIAGE_MAX)]
            if not ids:
                raise BadInput(tr("Missing field: {0}", "task_ids"))
            rows = c.execute(q + f" AND id IN ({','.join('?' * len(ids))}) ORDER BY sort, id", (inbox, *ids)).fetchall()
            if len(rows) != len(set(ids)):
                raise BadInput(tr("Only open tasks of your basket can be sorted"))
        if not rows:
            raise BadInput(tr("The basket is empty"))
        mine = [d for d in visible_lists(c, uid) if not d["is_inbox"] and not d["archived"] and d.get("role", "owner") in WRITE_ROLES]
        if b.get("lists") not in (None, "all"):
            want = {_p_int(x, "lists") for x in _p_list(b.get("lists"), "lists", PROP_LISTS_MAX)}
            if want - {d["id"] for d in mine}:
                raise BadInput(tr("Invalid value: {0}", "lists"))
            mine = [d for d in mine if d["id"] in want]
        secs = {}
        for s in visible_sections(c, uid):
            secs.setdefault(s["list_id"], []).append({"id": s["id"], "name": s["name"]})
        inp = {"items": [{"task_id": r["id"], "title": r["title"], "notes": (r["content"] or "")[:4000]} for r in rows],
               "lists": [{"id": d["id"], "name": d["name"], "folder": d["folder"] or None, "sections": secs.get(d["id"], [])}
                         for d in mine[:PROP_LISTS_MAX]]}
        return inp, tr(PROP_TITLES["triage"]), None, inbox
    if kind == "dayplan":  # 2.10.0 (#440): the same input the built-in planner uses
        _p_keys(b, "", ("agent_id", "kind", "date", "mode"))
        day = dayplan_day(b.get("date"))
        inp = dayplan_input(c, uid, day, dayplan_mode(b.get("mode")))
        if not inp["tasks"]:
            raise BadInput(tr("There are no open tasks to plan"))
        return inp, tr(PROP_TITLES["dayplan"], day.isoformat()), None, None
    from ..agents.meetprop import mtg_input  # 2.70.0 A (#1354): extract = notes and / or meeting photos (agents/meetprop.py)
    return mtg_input(c, uid, b)


@app.get("/api/proposals/agents")
def proposal_agents_get():
    c = db()
    if request.args.get("kind") in ("office_text", "doc_summary", "report") and not is_agent(g.user):  # 2.126.1 A (#2123 #2124): ?kind=&doc_id= | &list_id=
        from ..agents.asstprop import ast_agents_get
        return ast_agents_get(c, me(), request.args)
    if request.args.get("kind") == "ideas" and not is_agent(g.user):  # 2.156.0 A (#1201): ?kind=ideas&list_id=
        from ..agents.ideaprop import idp_agents_get
        return idp_agents_get(c, me(), request.args)
    return jsonify(agents=[] if is_agent(g.user) else prop_agents(c, me()))


@app.post("/api/proposals")
def proposal_request():
    """{agent_id, kind, ...input} -> a proposal job (state running) + the event job_request to that agent."""
    from ..agents.usage import usage_block
    need_collab()
    c = db()
    uid = me()
    if is_agent(g.user):
        raise Denied(403)
    b = body()
    kind = b.get("kind")
    if kind not in PROP_KINDS:
        return err(tr("Invalid value: {0}", "kind"))
    if kind == "sheet_tasks":  # 2.126.1 B (#2125): the agent proposes it itself, nothing to ask for
        return err(tr("Invalid value: {0}", "kind"))
    if kind == "cleanup":  # 2.39.0 (#1151): always the list's tidy agent, in packages (agents/cleanup.py)
        from ..agents.cleanup import cln_request
        return cln_request(c, uid, b)
    if kind in PROP_KINDS_AGENT or kind in ("layout", "import", "rule"):  # 2.51.0 C: proposed by the agent itself, nothing to ask for; 2.55.0 (#1066); 2.68.0 (#1839); 2.71.0 A
        return err(tr("Invalid value: {0}", "kind"))
    if kind == "notice":  # 2.70.0 C (#1359): the agent proposes it after contract_notice, never on request
        return err(tr("Invalid value: {0}", "kind"))
    if kind in ("office_text", "doc_summary", "report"):  # 2.126.1 A (#2123 #2124): own agents (office switches / the list's), own input (agents/asstprop.py)
        from ..agents.asstprop import ast_request
        return ast_request(c, uid, b)
    if kind == "ideas":  # 2.156.0 A (#1201): the agents of the list, only the branch's path (agents/ideaprop.py)
        from ..agents.ideaprop import idp_request
        return idp_request(c, uid, b)
    try:
        aid = int(b.get("agent_id") or 0)
    except (TypeError, ValueError):
        aid = 0
    a = agent_row(c, aid)
    if not a or not prop_agent_ok(c, a, uid):
        return err(tr("This agent cannot make proposals for you"), 404)
    if usage_block(c, aid):
        return err(tr("{0} reached its usage limit", a["display_name"] or a["username"]), 409)
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE user_id=? AND kind IS NOT NULL AND state IN ('running','waiting')",
                 (uid,)).fetchone()[0] >= PROP_OPEN_MAX:
        return err(tr("You have {0} open proposal requests: apply or discard some first", PROP_OPEN_MAX), 429)
    inp, title, tid, lid = prop_input(c, uid, kind, b)
    from ..collab.liste2eguard import le2b_list_locked, le2b_off, le2b_task_locked
    if le2b_list_locked(c, lid) or le2b_task_locked(c, tid):  # 2.64.1 B (#1817): agents never get texts of a list with the lock
        return err(le2b_off(), 409)
    from ..agents.core import agent_usable
    if lid and prop_mode(a) != "all" and list_role(c, lid, aid) and not agent_usable(c, aid, uid, lid):  # 2.26.0 (#928)
        return err(tr("The project owner has not opened this agent to members"), 403)
    ts = iso(now_utc())
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id)
                       VALUES(?,?,?,?,'running','',?,?,?,?,'requested',?)""",
                    (aid, tid, uid, title[:JOB_TITLE_MAX], ts, ts, kind, json.dumps(inp, ensure_ascii=False), lid))
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    agent_emit(c, aid, "job_request", {"job": job_dict(c, j), "kind": kind, "input": inp, "limits": PROP_LIMITS,
                                       "requested_by": {"id": uid, "name": user_names(c, [uid]).get(uid, "")}})
    bump(c)
    c.commit()
    print("proposal request", jid, kind, "agent", aid, "by user", uid, flush=True)
    return jsonify(job_dict(c, j)), 201


def need_prop(c, jid, lock=False):
    """A proposal job of the current person (only the person who asked: its input is theirs). lock: the row stays locked until
    the commit - two parallel apply / undo / redo of one proposal run one after the other (2.68.0, #1839 review)."""
    j = c.execute("SELECT * FROM agent_jobs WHERE id=? AND kind IS NOT NULL" + (" FOR UPDATE" if lock else ""), (jid,)).fetchone()
    if not j or j["user_id"] != me() or is_agent(g.user):
        raise Denied(404)
    return j


def prop_view(c, j):
    rec = json.loads(j["applied"] or "null")
    out = {"job": job_dict(c, j), "kind": j["kind"], "state": j["prop_state"] or "requested",
            "input": json.loads(j["input"] or "{}"), "proposal": json.loads(j["proposal"] or "null"),
            "agent": {"id": j["agent_id"], "name": user_names(c, [j["agent_id"]]).get(j["agent_id"], "")},
            "applied": {"undone": bool(rec.get("undone")), "list_id": rec.get("list"), "at": rec.get("at")} if rec else None,
            "limits": PROP_LIMITS}
    if j["kind"] == "sheet_tasks":  # 2.126.1 B (#2125): the rows as the person sees them now
        from ..agents.sheetprop import sht_view_extra
        out.update(sht_view_extra(c, j))
    if j["kind"] == "layout":  # 2.55.0 (#1066): before / after for the card
        from ..agents.lyprop import lyp_view_extra
        out.update(lyp_view_extra(c, j))
    if j["kind"] == "import":  # 2.68.0 (#1839): the target office and the judged rows (the person only)
        from ..agents.importprop import aim_view_extra
        out.update(aim_view_extra(c, j))
    if j["kind"] == "merge":  # 2.70.0 B (#1357): the groups with their contacts as they are now
        from ..agents.dupprop import dup_view_extra
        out.update(dup_view_extra(c, j))
    if j["kind"] == "notice":  # 2.70.0 C (#1359): the contract as it is now
        from ..agents.contractprop import ctr_view_extra
        out.update(ctr_view_extra(c, j))
    if j["kind"] == "rule":  # 2.71.0 A (#1457): the rule in names for the card
        from ..lists.rules import rul_prop_extra
        out.update(rul_prop_extra(c, j))
    if j["kind"] in ("office_text", "doc_summary", "report"):  # 2.126.1 A (#2123 #2124): the target as it is now
        from ..agents.asstprop import ast_view_extra
        out.update(ast_view_extra(c, j))
    if j["kind"] == "ideas":  # 2.156.0 A (#1201): the mind map of this list shows them
        out["list_id"] = j["list_id"]
    return out


@app.get("/api/proposals/<int:jid>")
def proposal_get(jid):
    c = db()
    return jsonify(prop_view(c, need_prop(c, jid)))


def prop_edit(kind, key, e, inp, prop):
    """One edited entry of the review dialog (title, due, section, assignee, list) -> clean values."""
    _p_keys(e, f"edits.{key}", ("title", "due", "section", "assignee_id", "list_id", "section_id", "time", "duration"))
    out = {}
    if kind == "dayplan":  # 2.10.0 (#440): another slot / length / day
        if "time" in e:
            if not isinstance(e["time"], str) or not valid_hm(e["time"]):
                raise BadInput(tr("Invalid value: {0}", "time"))
            out["time"] = e["time"]
        if "duration" in e:
            out["duration"] = _p_int(e["duration"], "duration", 5, 720)
        return out  # 2.11.0: no "due" edit, a day plan never moves dates
    if "title" in e:
        out["title"] = _p_str(e["title"], "title", PROP_TITLE_MAX, True)
    if "due" in e:
        out["due"] = _p_date(e["due"], "due")
    if kind in ("project", "extract") and "section" in e:
        out["section"] = _p_str(e["section"], "section", 100) or None
        if kind == "project" and out["section"] and out["section"].casefold() not in (s.casefold() for s in prop["sections"]):
            raise BadInput(tr("Unknown section: {0}", out["section"]))
    if kind == "extract" and "assignee_id" in e:
        v = e["assignee_id"]
        v = None if v in (None, "", 0) else _p_int(v, "assignee_id")
        if v is not None and v not in {m["id"] for m in inp.get("members", [])}:
            raise BadInput(tr("Invalid value: {0}", "assignee_id"))
        out["assignee_id"] = v
    if kind == "triage" and ("list_id" in e or "section_id" in e):
        lists = {x["id"]: {s["id"] for s in x.get("sections", [])} for x in inp.get("lists", [])}
        lid = e.get("list_id")
        lid = None if lid in (None, "", 0) else _p_int(lid, "list_id")
        sid = e.get("section_id")
        sid = None if sid in (None, "", 0) else _p_int(sid, "section_id")
        if (lid is not None and lid not in lists) or (sid is not None and (lid is None or sid not in lists[lid])):
            raise BadInput(tr("Invalid value: {0}", "list_id"))
        out["list_id"], out["section_id"] = lid, sid
    return out


def prop_sel(b, mx=PROP_MAX_ITEMS):
    """{select: [keys], edits: {key: {...}}, name?, folder?, share_agent?, use?} of the apply request."""
    _p_keys(b, "", ("select", "edits", "name", "folder", "share_agent", "use", "version"))  # 2.55.0 (#1066): use (a layout at once); 2.68.0 (#1839): version
    sel = b.get("select")
    if not isinstance(sel, list) or not sel or len(sel) > mx or \
            not all(isinstance(k, str) and re.fullmatch(r"\d{1,3}(\.\d{1,3})?", k) for k in sel):
        raise BadInput(tr("Select at least one entry"))
    ed = b.get("edits") or {}
    if not isinstance(ed, dict) or len(ed) > mx:
        raise BadInput(tr("Invalid value: {0}", "edits"))
    return list(dict.fromkeys(sel)), ed


def prop_insert(c, aid, lid, ts, title, notes="", section_id=None, parent_id=None, due=None, start=None, priority=0,
                assignee_id=None, duration=None, sort=0):
    """A task created from a proposal: owned / created by the person applying it; history "from a proposal by <agent>"."""
    from ..collab.liste2eguard import le2b_list_locked, le2b_off
    if le2b_list_locked(c, lid):  # 2.64.1 B (#1817): a proposal never writes plain texts into a list with the lock
        raise Denied(409, le2b_off())
    uid = me()
    tid = insert_id(c, """INSERT INTO tasks(list_id,section_id,parent_id,title,content,priority,due,start,duration,sort,created_at,updated_at,
                       created_by,assignee_id,assigned_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (lid, section_id, parent_id, title[:TITLE_MAX], notes or "", priority or 0, due, start if due else None, duration,
                     sort, ts, ts, uid, assignee_id, uid if assignee_id else None))
    log_act(c, tid, "created", {"agent": aid, "proposal": True})
    if parent_id:
        log_act(c, parent_id, "subtask", {"id": tid, "title": title[:200]})
    if assignee_id:
        task_event(c, tid, "assign")
    newtask_events(c, tid)
    from ..agents.core import agent_added_events
    agent_added_events(c, tid, source="proposal")  # 2.23.0 (#795): the other agents of the list (never the proposing one's own)
    return tid


def prop_section(c, lid, name, made):
    """Id of the section `name` in list lid (case-insensitive), created when missing (made: ids created by this apply)."""
    if not name:
        return None
    r = c.execute("SELECT id FROM sections WHERE list_id=? AND lower(name)=lower(?)", (lid, name)).fetchone()
    if r:
        return r[0]
    srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM sections WHERE list_id=?", (lid,)).fetchone()[0]
    sid = insert_id(c, "INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, name[:100], srt))
    made.append(sid)
    return sid


def prop_run(c, j, sel, ed, extra):
    """Applies the selected (and edited) entries of the stored proposal as the current person. Returns the undo record."""
    kind, aid, uid = j["kind"], j["agent_id"], me()
    if kind == "sheet_tasks":  # 2.126.1 B (#2125): the to-tasks core of the tables as the person (agents/sheetprop.py)
        from ..agents.sheetprop import sht_run
        return sht_run(c, j, sel, ed, extra, {"at": iso(now_utc()), "sel": sel, "edits": ed, "extra": extra, "tasks": [], "sections": [],
                                              "changes": {}, "list": None, "undone": False})
    if kind in PROP_KINDS_AGENT:  # 2.51.0 C (#1353 #1355): own edits (times, place), own records
        from ..agents.agenttime import atm_prop_run
        return atm_prop_run(c, j, sel, ed, {"at": iso(now_utc()), "sel": sel, "edits": ed, "extra": extra, "tasks": [], "sections": [],
                                            "changes": {}, "list": None, "undone": False})
    if kind == "import":  # 2.68.0 (#1839): the ticked rows into the person's office (agents/importprop.py)
        from ..agents.importprop import aim_run
        return aim_run(c, j, sel, ed, extra, {"at": iso(now_utc()), "sel": sel, "edits": ed, "extra": {}, "tasks": [], "sections": [],
                                              "changes": {}, "list": None, "undone": False})
    if kind == "layout":  # 2.55.0 (#1066): a saved arrangement, used at once (agents/lyprop.py)
        from ..agents.lyprop import lyp_run
        return lyp_run(c, j, sel, ed, extra, {"at": iso(now_utc()), "sel": sel, "edits": {}, "extra": extra, "tasks": [], "sections": [],
                                              "changes": {}, "list": None, "undone": False})
    if kind == "merge":  # 2.70.0 B (#1357): ctm_merge per ticked group as the person (agents/dupprop.py)
        from ..agents.dupprop import dup_run
        return dup_run(c, j, sel, ed, extra, {"at": iso(now_utc()), "sel": sel, "edits": ed, "extra": extra, "tasks": [], "sections": [],
                                              "changes": {}, "list": None, "undone": False})
    if kind == "notice":  # 2.70.0 C (#1359): a comment as the person (+ a reminder), agents/contractprop.py
        from ..agents.contractprop import ctr_run
        return ctr_run(c, j, sel, ed, extra, {"at": iso(now_utc()), "sel": sel, "edits": {}, "extra": extra, "tasks": [], "sections": [],
                                              "changes": {}, "list": None, "undone": False})
    if kind == "rule":  # 2.71.0 A (#1457): the rule is created as the person and belongs to them
        from ..lists.rules import rul_prop_run
        return rul_prop_run(c, j, {"at": iso(now_utc()), "sel": sel, "edits": {}, "extra": extra, "tasks": [], "sections": [],
                                   "changes": {}, "list": None, "undone": False})
    if kind in ("office_text", "doc_summary", "report"):  # 2.126.1 A (#2123 #2124): the (edited) text into its field as the person
        from ..agents.asstprop import ast_run
        return ast_run(c, j, sel, ed, extra, {"at": iso(now_utc()), "sel": sel, "edits": {}, "extra": {}, "tasks": [], "sections": [],
                                              "changes": {}, "list": None, "undone": False})
    if kind == "ideas":  # 2.156.0 A (#1201): the selected ideas as tasks under the branch (agents/ideaprop.py)
        from ..agents.ideaprop import idp_run
        return idp_run(c, j, sel, ed, extra, {"at": iso(now_utc()), "sel": sel, "edits": {}, "extra": {}, "tasks": [], "sections": [],
                                              "changes": {}, "list": None, "undone": False})
    prop, inp = json.loads(j["proposal"]), json.loads(j["input"] or "{}")
    edits = {k: prop_edit(kind, k, v, inp, prop) for k, v in ed.items()}
    ts = iso(now_utc())
    rec = {"at": ts, "sel": sel, "edits": ed, "extra": extra, "tasks": [], "sections": [], "changes": {}, "list": None, "undone": False}
    selected = set(sel)
    if kind == "cleanup":  # 2.39.0 (#1151)
        from ..agents.cleanup import cln_run
        return cln_run(c, j, sel, edits, rec)
    if kind in ("inquiry", "setup"):  # 2.51.0 B (#1351 #1358): own keys, edits and parts
        from ..agents.propkinds2 import pk2_run
        return pk2_run(c, j, sel, ed, extra, rec)
    if kind == "project":
        name = _p_str(extra.get("name") or prop["name"], "name", PROP_NAME_MAX, True)
        folder = clean_folder(extra.get("folder") if extra.get("folder") is not None else prop.get("folder") or "", False)
        lid = insert_id(c, "INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,checklist,kind) VALUES(?,?,?,?,?,?,?,?,?)",
                        (name, "", folder, my_max_sort(c, uid) + 1, "list", ts, uid, 0, "project"))
        from ..accounts.orgs import ws_apply_default
        ws_apply_default(c, uid, lid)  # 2.28.0 (#935): the default workspace
        rec["list"] = lid
        list_created(c, uid, lid)  # 2.4.2 (#391); 2.25.0 (#931): + groups and people of a shared folder
        secs = {}
        for i, s in enumerate(prop["sections"]):
            secs[s.casefold()] = insert_id(c, "INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, s, i + 1))
            rec["sections"].append(secs[s.casefold()])
        ids = {}
        for i, t in enumerate(prop["tasks"]):
            if str(i) not in selected:
                continue
            e = edits.get(str(i), {})
            sec = e.get("section", t["section"])
            ids[i] = prop_insert(c, aid, lid, ts, e.get("title", t["title"]), t["notes"], secs.get((sec or "").casefold()), None,
                                 e.get("due", t["due"]), t["start"], t["priority"], sort=i + 1)
            rec["tasks"].append(ids[i])
            for k, s in enumerate(t["subtasks"]):
                key = f"{i}.{k}"
                if key not in selected:
                    continue
                se = edits.get(key, {})
                rec["tasks"].append(prop_insert(c, aid, lid, ts, se.get("title", s["title"]), s["notes"], secs.get((sec or "").casefold()),
                                                ids[i], se.get("due", s["due"]), sort=k + 1))
        for i, t in enumerate(prop["tasks"]):
            for d in t["depends_on"]:
                if i in ids and d in ids:
                    c.execute("INSERT INTO task_deps(task_id,blocker_id,created_by,created_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING", (ids[i], ids[d], uid, ts))
        from ..core.access import list_other_agent
        from ..accounts.orgs import ws_member_problem
        from ..agents.safety import bridge_blocks
        if extra.get("share_agent") and agent_active(agent_row(c, aid)) and not list_other_agent(c, lid, aid) and not ws_member_problem(c, lid, aid) \
                and not bridge_blocks(c, lid, aid):  # 2.26.0; 2.28.0 (#935); 2.30.0 (#919): no bridge between lists with different people
            c.execute("INSERT INTO list_members(list_id,user_id,role,sort,added_at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
                      (lid, aid, "edit", my_max_sort(c, aid) + 1, ts))
            rec["shared"] = True
        return rec
    if kind == "subtasks":
        tid = j["task_id"]
        if not tid:
            raise Denied(404)
        need_task(c, tid)
        t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if t["deleted_at"]:
            raise Denied(409, tr("The task is in the trash"))
        e = check_parent(c, None, tid)
        if e:
            raise BadInput(e)
        base = c.execute("SELECT COALESCE(MAX(sort),0) FROM tasks WHERE parent_id=?", (tid,)).fetchone()[0]
        ids = {}
        for i, it in enumerate(prop["items"]):
            if str(i) not in selected:
                continue
            e = edits.get(str(i), {})
            ids[i] = prop_insert(c, aid, t["list_id"], ts, e.get("title", it["title"]), it["notes"], t["section_id"], tid,
                                 e.get("due", it["due"]), duration=it["estimate"], sort=base + i + 1)
            rec["tasks"].append(ids[i])
        for a_, b_ in prop["dependencies"]:
            if a_ in ids and b_ in ids:
                c.execute("INSERT INTO task_deps(task_id,blocker_id,created_by,created_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING", (ids[a_], ids[b_], uid, ts))
        rec["list"] = t["list_id"]
        return rec
    if kind == "extract":
        lid = j["list_id"]
        need_list(c, lid)
        n = len(prop["tasks"])
        base = c.execute("SELECT COALESCE(MIN(sort),0) FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0] - n - 1
        people = list_people(c, lid)
        for i, t in enumerate(prop["tasks"]):
            if str(i) not in selected:
                continue
            e = edits.get(str(i), {})
            asg = e.get("assignee_id", t["assignee_id"])
            if asg is not None and asg not in people:
                asg = None  # left the list meanwhile
            if asg is not None and not collab_all():
                asg = None
            sid = prop_section(c, lid, e.get("section", t["section"]), rec["sections"])
            rec["tasks"].append(prop_insert(c, aid, lid, ts, e.get("title", t["title"]), t["notes"], sid, None,
                                            e.get("due", t["due"]), assignee_id=asg, sort=base + i))
        rec["list"] = lid
        return rec
    if kind == "dayplan":  # 2.10.0 (#440): planned start (2.11.0, never due / deadline) + duration of the person's own tasks
        for key in sel:
            tid, want = dayplan_want(prop, inp, key, edits.get(key, {}))
            if not tid or str(tid) in rec["changes"]:
                continue
            try:
                need_task(c, tid)
            except Denied:
                continue
            cur = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
            if cur["deleted_at"] or cur["status"] != 0:
                continue
            before = {k: cur[k] for k in want}
            msg = apply_update(c, tid, dict(want))
            if msg:
                raise BadInput(msg)
            log_act(c, tid, "proposal", {"agent": aid})
            rec["changes"][str(tid)] = {"before": before, "after": want}
        return rec
    # triage: moves / edits of the person's inbox items (normal changes: apply_update checks every move)
    for i, it in enumerate(prop["items"]):
        if str(i) not in selected:
            continue
        tid = it["task_id"]
        try:
            need_task(c, tid)
        except Denied:
            continue
        e = edits.get(str(i), {})
        want = {}
        lid = e.get("list_id", it["list_id"]) if "list_id" in e else it["list_id"]
        sid = e.get("section_id") if "list_id" in e else it["section_id"]
        if lid:
            want["list_id"] = lid
            want["section_id"] = sid
        title = e.get("title", it["rewrite_title"])
        if title:
            want["title"] = title
        due = e.get("due", it["due"]) if "due" in e else it["due"]
        if due:
            want["due"] = due
        if it["priority"] is not None:
            want["priority"] = it["priority"]
        cur = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        before = {k: cur[k] for k in want}
        if it["tags"]:
            have = my_tags(c, tid)
            before["tags"] = have
            want["tags"] = have + [x for x in it["tags"] if x.casefold() not in (h.casefold() for h in have)]
        if not want:
            continue
        msg = apply_update(c, tid, dict(want))
        if msg:
            raise BadInput(msg)
        log_act(c, tid, "proposal", {"agent": aid})
        rec["changes"][str(tid)] = {"before": before, "after": want}
    return rec


def prop_notify_agent(c, j, action, state, extra=None):
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (j["id"],)).fetchone()
    if json.loads(j["input"] or "{}").get("assistant"):  # 2.75.0 A (#1411): the built-in assistant's proposal, no agent to tell
        return
    data = {"job": job_dict(c, j), "action": action, "proposal": {"state": state, **(extra or {})},
            "user": {"id": me(), "name": user_names(c, [me()]).get(me(), "")}}
    if j["kind"] == "cleanup":  # 2.39.0 (#1151): the list on top (agent_emit: health list, list limit, playbook)
        data["list_id"] = j["list_id"]
    agent_emit(c, j["agent_id"], "job", data)


@app.post("/api/proposals/<int:jid>/apply")
def proposal_apply(jid):
    """{select: ["0", "0.1", ...], edits: {key: {title?, due?, section?, assignee_id?, list_id?, section_id?}}, name?, folder?,
    share_agent?} -> creates / changes the selected entries as the current person; one undo step (POST .../undo)."""
    need_collab()
    c = db()
    j = need_prop(c, jid, lock=True)
    if j["prop_state"] != "ready" or not j["proposal"]:
        return err(tr("There is no proposal to apply (anymore)"), 409)
    b = body()
    rem = b.pop("remind", None) if j["kind"] == "notice" and isinstance(b, dict) else None  # 2.70.0 C (#1359): "Remind me"
    sel, ed = prop_sel(b, 500 if j["kind"] == "import" else PROP_MAX_ITEMS)  # 2.68.0 (#1839): up to 500 rows of an import
    extra = {k: b[k] for k in ("name", "folder", "share_agent", "use", "version") if k in b}  # 2.55.0 (#1066): use = a layout at once; 2.68.0 (#1839): version = the import card seen
    if rem is not None:  # 2.70.0 C (#1359)
        extra["remind"] = rem is True
    try:
        rec = prop_run(c, j, sel, ed, extra)
    except (BadInput, Denied):
        c.rollback()
        raise
    ts = iso(now_utc())
    c.execute("UPDATE agent_jobs SET prop_state='applied', state='done', action='approve', action_by=?, action_at=?, updated_at=?, applied=? "
              "WHERE id=?", (me(), ts, ts, json.dumps(rec, ensure_ascii=False), jid))
    counts = {"created": len(rec["tasks"]), "changed": len(rec["changes"])}
    if j["kind"] == "sheet_tasks":  # 2.126.1 B (#2125): rows skipped (carried over before, no title), the table
        from ..agents.sheetprop import sht_result
        counts.update(sht_result(rec))
    if j["kind"] in ("inquiry", "setup"):  # 2.51.0 B (#1351 #1358): event drafts, the quotation draft, lists, modules, project_list_id
        from ..agents.propkinds2 import pk2_result
        counts.update(pk2_result(rec))
    if j["kind"] == "cleanup":  # 2.39.0 (#1151): counts per kind of entry + the skipped tasks (why)
        from ..agents.cleanup import cln_result
        counts.update(cln_result(rec))
    if j["kind"] in PROP_KINDS_AGENT:  # 2.51.0 C: entries / drafts / options made (rec["made"])
        counts.update(created=len(rec.get("made") or []), warnings=rec.get("warnings", 0))
    if j["kind"] == "layout":  # 2.55.0 (#1066): the saved arrangement, its view, used at once
        from ..agents.lyprop import lyp_result
        counts.update(lyp_result(rec))
    if j["kind"] == "import":  # 2.68.0 (#1839): only counts go back to the agent, never the office's rows
        from ..agents.importprop import aim_result
        counts.update(aim_result(rec))
    if j["kind"] == "merge":  # 2.70.0 B (#1357): merged / skipped groups
        from ..agents.dupprop import dup_result
        counts.update(dup_result(rec))
    if j["kind"] == "notice":  # 2.70.0 C (#1359): the comment, the reminder
        from ..agents.contractprop import ctr_result
        counts.update(ctr_result(rec))
    if j["kind"] == "rule":  # 2.71.0 A (#1457)
        counts.update(rule_id=rec.get("rule_id"))
    if j["kind"] in ("office_text", "doc_summary", "report"):  # 2.126.1 A (#2123 #2124)
        from ..agents.asstprop import ast_result
        counts.update(ast_result(rec))
    prop_notify_agent(c, j, "approve", "applied", {**counts, "list_id": rec["list"] if j["kind"] in ("project", "cleanup") else None})
    c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND kind='proposal' AND read_at IS NULL AND data->>'job' = ?",
              (ts, me(), str(jid)))
    bump(c)
    c.commit()
    return jsonify({**counts, "list_id": rec["list"], "job": job_dict(c, c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone())})


@app.post("/api/proposals/<int:jid>/discard")
def proposal_discard(jid):
    c = db()
    j = need_prop(c, jid)
    if j["prop_state"] in ("applied", "discarded"):
        return err(tr("This proposal was already applied or discarded"), 409)
    ts = iso(now_utc())
    c.execute("UPDATE agent_jobs SET prop_state='discarded', state='stopped', action='reject', action_by=?, action_at=?, updated_at=? WHERE id=?",
              (me(), ts, ts, jid))
    prop_notify_agent(c, j, "reject", "discarded")
    c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND kind='proposal' AND read_at IS NULL AND data->>'job' = ?",
              (ts, me(), str(jid)))
    bump(c)
    c.commit()
    return jsonify(ok=True)


def prop_titles(c, ids):
    return [r[0][:40] for r in c.execute(f"SELECT title FROM tasks WHERE id IN ({','.join('?' * len(ids)) or 'NULL'})", ids)][:8]


@app.post("/api/proposals/<int:jid>/undo")
def proposal_undo(jid):
    """Takes an applied proposal back (one step): created tasks go to the trash (a new project list is removed when nobody
    added or changed anything in it), changes of the inbox items are reverted. What someone changed since stays (skipped)."""
    c = db()
    j = need_prop(c, jid, lock=True)
    rec = json.loads(j["applied"] or "null")
    if j["prop_state"] != "applied" or not rec or rec.get("undone"):
        return err(tr("Nothing to undo"), 409)
    ts, skipped, n = iso(now_utc()), [], 0
    if j["kind"] == "sheet_tasks":  # 2.126.1 B (#2125): the batch undo of the tables (tasks to the trash, row marks off)
        from ..agents.sheetprop import sht_undo
        n, skipped = sht_undo(c, j, rec)
    elif j["kind"] in ("inquiry", "setup"):  # 2.51.0 B (#1351 #1358)
        from ..agents.propkinds2 import pk2_undo
        n, skipped = pk2_undo(c, j, rec)
    elif j["kind"] == "cleanup":  # 2.39.0 (#1151): field changes back, closed tasks open again (one step)
        from ..agents.cleanup import cln_undo
        n, skipped = cln_undo(c, rec)
    elif j["kind"] in PROP_KINDS_AGENT:  # 2.51.0 C: removes what it made (unchanged since)
        from ..agents.agenttime import atm_prop_undo
        n, skipped = atm_prop_undo(c, j, rec)
    elif j["kind"] == "layout":  # 2.55.0 (#1066): back to the previous arrangement
        from ..agents.lyprop import lyp_undo
        n, skipped = lyp_undo(c, j, rec)
    elif j["kind"] == "import":  # 2.68.0 (#1839): the fixed costs it made go (unchanged since)
        from ..agents.importprop import aim_undo
        n, skipped = aim_undo(c, j, rec)
    elif j["kind"] == "merge":  # 2.70.0 B (#1357): every merge back (ctm_undo)
        from ..agents.dupprop import dup_undo
        n, skipped = dup_undo(c, j, rec)
    elif j["kind"] == "notice":  # 2.70.0 C (#1359): the comment goes, the reminder back
        from ..agents.contractprop import ctr_undo
        n, skipped = ctr_undo(c, j, rec)
    elif j["kind"] == "rule":  # 2.71.0 A (#1457): the accepted rule goes to the trash
        from ..lists.rules import rul_prop_undo
        n, skipped = rul_prop_undo(c, j, rec)
    elif j["kind"] in ("office_text", "doc_summary", "report"):  # 2.126.1 A (#2123 #2124): the text before comes back (unless changed since)
        from ..agents.asstprop import ast_undo
        n, skipped = ast_undo(c, j, rec)
    elif j["kind"] in ("triage", "dayplan"):
        for tid, ch in rec["changes"].items():
            try:
                need_task(c, int(tid))
            except Denied:
                continue
            conf = []
            try:
                msg = apply_update(c, int(tid), {**ch["before"], "_prev": ch["after"]}, conf)
            except Denied as e:
                msg = e.text()
            if msg or conf:
                skipped += prop_titles(c, [int(tid)])
            if not msg and len(conf) < len(ch["before"]):
                n += 1
    else:
        ids = rec["tasks"]
        q = ",".join("?" * len(ids)) or "NULL"
        mine = {r[0] for r in c.execute(f"SELECT id FROM tasks WHERE id IN ({q}) AND deleted_at IS NULL AND updated_at<=?", (*ids, rec["at"]))}
        skipped += prop_titles(c, [i for i in ids if i not in mine and c.execute(
            "SELECT 1 FROM tasks WHERE id=? AND deleted_at IS NULL", (i,)).fetchone()])
        lid = rec.get("list")
        others = c.execute(f"SELECT COUNT(*) FROM tasks WHERE list_id=? AND id NOT IN ({q})", (lid, *ids)).fetchone()[0] if lid else 1
        if j["kind"] == "project" and lid and not others and len(mine) == len(ids) and \
                c.execute("SELECT 1 FROM lists WHERE id=? AND owner_id=?", (lid, me())).fetchone():
            list_row_purge(c, lid, g.setdefault("purge_lists", []))  # the whole new project (sections, tasks, deps, members, files)
            rec["list_deleted"] = True
            n = len(ids)
        else:
            for tid in ids:
                if tid in mine and c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()["deleted_at"] is None:
                    do_delete(c, tid)
                    log_act(c, tid, "delete")
            rec["trashed"] = sorted(mine)
            n = len(mine)
    rec.update(undone=True, undone_at=ts)
    c.execute("UPDATE agent_jobs SET applied=?, updated_at=? WHERE id=?", (json.dumps(rec, ensure_ascii=False), ts, jid))
    bump(c)
    c.commit()
    list_purge_files(g.pop("purge_lists", []))
    return jsonify(undone=n, skipped=skipped, none=n == 0)


@app.post("/api/proposals/<int:jid>/redo")
def proposal_redo(jid):
    """The way forward again after an undo: trashed tasks come back; a removed project is created again; triage changes are
    applied again (what someone changed since stays)."""
    c = db()
    j = need_prop(c, jid, lock=True)
    rec = json.loads(j["applied"] or "null")
    if j["prop_state"] != "applied" or not rec or not rec.get("undone"):
        return err(tr("Nothing to redo"), 409)
    skipped, n = [], 0
    if j["kind"] == "sheet_tasks":  # 2.126.1 B (#2125): the batch again
        from ..agents.sheetprop import sht_undo
        n, skipped = sht_undo(c, j, rec, back=False)
        rec.update(undone=False)
    elif j["kind"] in ("inquiry", "setup"):  # 2.51.0 B (#1351 #1358)
        from ..agents.propkinds2 import pk2_redo
        try:
            rec, n, skipped = pk2_redo(c, j, rec)
        except (BadInput, Denied):
            c.rollback()
            raise
    elif j["kind"] == "project" and rec.get("list_deleted"):
        try:
            rec = prop_run(c, j, rec["sel"], rec["edits"], rec.get("extra") or {})
        except (BadInput, Denied):
            c.rollback()
            raise
        n = len(rec["tasks"])
    elif j["kind"] == "cleanup":  # 2.39.0 (#1151)
        from ..agents.cleanup import cln_undo
        n, skipped = cln_undo(c, rec, back=False)
        rec.update(undone=False)
    elif j["kind"] in PROP_KINDS_AGENT:  # 2.51.0 C: makes it again
        from ..agents.agenttime import atm_prop_undo
        n, skipped = atm_prop_undo(c, j, rec, back=False)
        rec.update(undone=False)
    elif j["kind"] == "layout":  # 2.55.0 (#1066)
        from ..agents.lyprop import lyp_undo
        try:
            n, skipped = lyp_undo(c, j, rec, back=False)
        except (BadInput, Denied):
            c.rollback()
            raise
        rec.update(undone=False)
    elif j["kind"] == "import":  # 2.68.0 (#1839): the removed rows come again (all or nothing)
        from ..agents.importprop import aim_undo
        try:
            n, skipped = aim_undo(c, j, rec, back=False)
        except (BadInput, Denied):
            c.rollback()
            raise
        rec.update(undone=False)
    elif j["kind"] == "merge":  # 2.70.0 B (#1357): merged again
        from ..agents.dupprop import dup_undo
        try:
            n, skipped = dup_undo(c, j, rec, back=False)
        except (BadInput, Denied):
            c.rollback()
            raise
        rec.update(undone=False)
    elif j["kind"] == "notice":  # 2.70.0 C (#1359)
        from ..agents.contractprop import ctr_undo
        n, skipped = ctr_undo(c, j, rec, back=False)
        rec.update(undone=False)
    elif j["kind"] == "rule":  # 2.71.0 A (#1457)
        from ..lists.rules import rul_prop_undo
        n, skipped = rul_prop_undo(c, j, rec, back=False)
        rec.update(undone=False)
    elif j["kind"] in ("office_text", "doc_summary", "report"):  # 2.126.1 A (#2123 #2124)
        from ..agents.asstprop import ast_undo
        n, skipped = ast_undo(c, j, rec, back=False)
    elif j["kind"] in ("triage", "dayplan"):
        for tid, ch in rec["changes"].items():
            try:
                need_task(c, int(tid))
            except Denied:
                continue
            conf = []
            try:
                msg = apply_update(c, int(tid), {**ch["after"], "_prev": ch["before"]}, conf)
            except Denied as e:
                msg = e.text()
            if msg or conf:
                skipped += prop_titles(c, [int(tid)])
            if not msg and len(conf) < len(ch["after"]):
                n += 1
        rec.update(undone=False)
    else:
        back = rec.get("trashed") or []
        for tid in back:  # a subtask comes back with its parent already (restore_task), then counts once
            r = c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
            if r and r["deleted_at"] and r["deleted_at"] >= rec.get("undone_at", ""):
                restore_task(c, tid)
        n = c.execute(f"SELECT COUNT(*) FROM tasks WHERE id IN ({','.join('?' * len(back)) or 'NULL'}) AND deleted_at IS NULL", back).fetchone()[0]
        rec.update(undone=False)
    ts = iso(now_utc())
    c.execute("UPDATE agent_jobs SET applied=?, updated_at=? WHERE id=?", (json.dumps(rec, ensure_ascii=False), ts, jid))
    bump(c)
    c.commit()
    return jsonify(redone=n, skipped=skipped, none=n == 0, list_id=rec.get("list"))


def prop_ready_notify(c, j):
    """The proposal is there: News (kind proposal) + push "Proposal ready" to the person who asked, per their settings."""
    uid = j["user_id"]
    s = collab_user(c, uid, None) if uid else None
    if not s:
        return
    news_add(c, uid, "proposal", data={"job": j["id"], "title": (j["title"] or "")[:200], "kind": j["kind"]}, actor=j["agent_id"], s=s)
    if not notif_ok(c, uid, s, "proposal", "push") or not push_reachable(c, uid, s):
        return
    lg = lang_of(s)
    name = user_names(c, [j["agent_id"]]).get(j["agent_id"], "?")
    g.pushes.append((uid, tr("Proposal ready", lg=lg), f"{name}: {j['title']}", f"{PUBLIC_URL}/#prop/{j['id']}", push_prio(s)))


@app.get("/api/v1/agent/jobs/<int:jid>")
@v1_view
def v1_agent_job_get(jid):
    """One job of the agent; proposal jobs with kind, input (exactly what the person sent), proposal and its state."""
    v1_args(())
    aid = need_agent()
    c = db()
    j = c.execute("SELECT * FROM agent_jobs WHERE id=? AND agent_id=?", (jid, aid)).fetchone()
    if not j:
        raise Denied(404)
    d = job_dict(c, j)
    if j["kind"]:
        d.update(input=json.loads(j["input"] or "{}"), proposal=json.loads(j["proposal"] or "null"), limits=PROP_LIMITS)
    return jsonify(d)


@app.post("/api/v1/agent/jobs/<int:jid>/proposal")
@v1_view
def v1_agent_job_proposal(jid):
    """The agent's structured proposal for a job_request (kind project | subtasks | triage | extract | dayplan | cleanup, see docs/AGENTS.md).
    Validated here; replaces an earlier one until the person applied or discarded it. The job waits for the person."""
    v1_args(())
    aid = need_agent()
    c = db()
    j = c.execute("SELECT * FROM agent_jobs WHERE id=? AND agent_id=?", (jid, aid)).fetchone()
    if not j:
        raise Denied(404)
    if not j["kind"]:
        raise BadInput(tr("This job did not ask for a proposal"))
    if j["kind"] == "sheet_tasks":  # 2.126.1 B (#2125): replacing checks the table and the list again
        from ..agents.sheetprop import sht_replace_check
        sht_replace_check(c, aid, j)
    if j["kind"] in PROP_KINDS_AGENT:  # 2.51.0 C (#1353 #1355): replacing needs the scope of creating it
        from ..api.scopes import need_scope
        need_scope({"time": "time", "shoot": "calendar"}[j["kind"]])
    if j["kind"] == "layout":  # 2.55.0 (#1066)
        from ..api.scopes import need_scope
        need_scope("layouts")
    if j["kind"] == "import":  # 2.68.0 (#1839)
        from ..api.scopes import need_scope
        need_scope("import")
    if j["kind"] == "notice":  # 2.70.0 C (#1359): replacing checks the contract again
        from ..agents.contractprop import _need_contract
        _need_contract(c, aid, j["task_id"])
    if j["kind"] == "rule":  # 2.71.0 A (#1457)
        from ..api.scopes import need_scope
        need_scope("structure")
    if j["kind"] in ("office_text", "doc_summary", "report"):  # 2.126.1 A (#2123 #2124): the office switches still on / the list still shared
        from ..agents.asstprop import ast_need_agent
        ast_need_agent(c, j, aid)
    if j["kind"] == "ideas":  # 2.156.0 A (#1201): the list still shared, nothing taken over yet
        from ..agents.ideaprop import idp_need_agent
        idp_need_agent(c, j, aid)
    if j["prop_state"] not in ("requested", "ready") or j["state"] not in ("running", "waiting"):
        raise Denied(409, tr("This proposal was already applied or discarded"))
    if len(request.data or b"") > PROP_MAX_BYTES:
        return v1_err(413, tr("The proposal is too large (at most {0} KB)", PROP_MAX_BYTES // 1024))
    p = prop_validate(j["kind"], v1_json(), json.loads(j["input"] or "{}"))
    first = j["prop_state"] != "ready"
    ts = iso(now_utc())
    c.execute("UPDATE agent_jobs SET proposal=?, prop_state='ready', state='waiting', updated_at=? WHERE id=?",
              (json.dumps(p, ensure_ascii=False), ts, jid))
    j2 = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    if first:
        prop_ready_notify(c, j2)
    bump(c)
    c.commit()
    return jsonify({**job_dict(c, j2), "proposal": p}), 201


def prop_cleanup(c, force=False):
    """Watchdog, at most hourly: proposal jobs (with their input) older than PROP_KEEP_DAYS, and those of deleted people, go."""
    if not force and time.time() - _PROP_CLEAN["at"] < 3600:
        return 0
    _PROP_CLEAN["at"] = time.time()
    from ..agents.lyprop import lyp_expire
    lyp_expire(c)  # 2.55.0 (#1066): open layout proposals expire after 14 days
    from ..agents.importprop import aim_expire
    aim_expire(c)  # 2.68.0 (#1839): open import proposals too
    from ..agents.contractprop import ctr_expire
    ctr_expire(c)  # 2.70.0 C (#1359): open notice proposals end with their deadline
    n = c.execute("DELETE FROM agent_jobs WHERE kind IS NOT NULL AND (updated_at<? OR user_id IS NULL)",
                  (iso(now_utc() - timedelta(days=PROP_KEEP_DAYS)),)).rowcount
    c.commit()
    return n


@app.get("/api/v1/agent/chats")
@v1_view
def v1_agent_chats():
    """Chat messages of every conversation after ?since=<message id> (both directions), oldest first; ?user_id= one person."""
    a = v1_args(("since", "user_id", "limit"))
    aid = need_agent()
    c = db()
    since = as_int(a.get("since", 0) or 0, "since", 0)
    limit = as_int(a.get("limit", 200), "limit", 1, 500)
    q, args = "SELECT * FROM agent_chat WHERE agent_id=? AND id>?", [aid, since]
    if a.get("user_id"):
        q += " AND user_id=?"
        args.append(as_int(a["user_id"], "user_id", 1))
    rows = c.execute(q + " ORDER BY id LIMIT ?", (*args, limit + 1)).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    if chat_delivered(c, aid, [r["id"] for r in rows if r["sender"] == "user" and not r["delivered_at"]]):  # 2.7.2 (#422)
        c.commit()
        rows = [c.execute("SELECT * FROM agent_chat WHERE id=?", (r["id"],)).fetchone() for r in rows]
    names = user_names(c, [r["user_id"] for r in rows])
    rx, fs = chat_reactions_of(c, [r["id"] for r in rows]), chat_files_of(c, [r["id"] for r in rows])
    nw = {u: chat_newest(c, aid, u) for u in {r["user_id"] for r in rows}}  # 2.30.0 (#1037): choice_state
    extra = {}
    if a.get("user_id"):  # 2.82.0 (#1862): one person's conversation also brings its pinned messages (like the app routes)
        from ..collab.chatpins import cpin_agent_list
        uid = as_int(a["user_id"], "user_id", 1)
        extra["pins"] = cpin_agent_list(c, aid, uid, api=True) if agent_shares(c, aid, uid) else []
    return jsonify(data=jn9_chat_jobs(c, [{**chat_dict(r, rx, fs, api=True, newest=nw[r["user_id"]]), "user": {"id": r["user_id"], "name": names.get(r["user_id"], "")}} for r in rows], aid),  # 2.59.0 (#1827)
                   cursor=rows[-1]["id"] if rows else since, has_more=more, **extra)


def _approval_pushes_hour(c, aid, uid):
    """How many approval requests agent aid sent person uid within the last hour (this one included)."""
    return c.execute("""SELECT COUNT(*) FROM agent_chat WHERE agent_id=? AND user_id=? AND sender='agent'
                        AND choices->>'approval' IS NOT NULL AND created_at>?""",
                     (aid, uid, iso_ms(now_utc() - timedelta(hours=1)))).fetchone()[0]


def _chat_task_lid(c, tid):
    r = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone() if tid else None
    return r["list_id"] if r else None


@app.post("/api/v1/agent/chats/<int:uid>")
@v1_view
def v1_agent_chat_post(uid):
    """{body, task_id?} -- the agent answers in its chat with person uid (push to that person). 2.13.1 (#465): or multipart
    (body?, task_id?, file... -- at most CHAT_FILES_MAX files of MAX_FILE_MB each) to send images / files."""
    v1_args(())
    aid = need_agent()
    c = db()
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or is_agent(u) or not agent_shares(c, aid, uid):
        raise Denied(404)
    fb, files = chat_input(("body", "task_id", "choices", "multi", "permission", "expires_in", "job_id", "job_parent", "reply_to", "approval", "offer_save", "kind", "job_msg"))
    b = fb if fb is not None else v1_json()
    # 2.28.0 (#1005): answer buttons; 2.30.0 (#1041): permission questions (permission, expires_in)
    unknown = sorted(k for k in b if k not in ("body", "task_id", "choices", "multi", "permission", "expires_in", "job_id", "job_parent", "reply_to",
                                               "approval", "offer_save", "kind", "job_msg"))  # 2.96.0 C (#2015): job_msg; 2.33.0: reply_to; 2.35.0 (#1103): approval; 2.37.0 (#1159): offer_save
    if unknown:
        raise UnknownFields(unknown)
    # 2.41.0 (#1206): kind = message (default) | notice (a small grey line, no push, never unread; older servers answer 400)
    if b.get("kind") not in (None, "", "message", "notice"):
        raise BadInput(tr("Invalid value: {0}", "kind"))
    if b.get("kind") == "notice":
        r = cx_notice_post(c, aid, uid, b, files)
        bump(c)
        c.commit()
        chat_unlink_trimmed()
        return jsonify(chat_one(c, r, api=True)), 201
    b.pop("kind", None)
    # 2.37.0 (#1159): offer_save: true = the button "Save as task" under the message; the person saves (POST /api/chat-save),
    # the agent never does
    offer = b.pop("offer_save", None)
    if fb is not None and isinstance(offer, str):  # a multipart form sends text
        offer = offer.lower() in ("1", "true", "yes")
    if offer not in (None, True, False):
        raise BadInput(tr("Invalid value: {0}", "offer_save"))
    jid = None
    if b.get("job_id") not in (None, ""):  # 2.32.0 (#1081): this message carries the result of a job for this person
        jid = as_int(b["job_id"], "job_id", 1)
        jr = c.execute("SELECT user_id FROM agent_jobs WHERE id=? AND agent_id=?", (jid, aid)).fetchone()
        if not jr or jr["user_id"] != uid:
            raise BadInput(tr("Invalid value: {0}", "job_id"))
    # 2.47.3 (#1764): job_parent = the leading job of a part job (a job of this agent); with job_id only. The app colours the
    # messages of a job by its number and gives a part job the colour of its leader
    jpar = None
    if b.get("job_parent") not in (None, ""):
        jpar = as_int(b["job_parent"], "job_parent", 1)
        if not jid or jpar == jid or not c.execute("SELECT 1 FROM agent_jobs WHERE id=? AND agent_id=? AND user_id=?", (jpar, aid, uid)).fetchone():  # review K3: + the person
            raise BadInput(tr("Invalid value: {0}", "job_parent"))
    # 2.96.0 C (#2015): job_msg = the kind of a job message (say | question | result | error); with job_id only
    from ..agents.jobchat import JCD_KINDS
    jmsg = b.get("job_msg")
    if jmsg in ("", None):
        jmsg = None
    elif jmsg not in JCD_KINDS or not jid:
        raise BadInput(tr("Invalid value: {0}", "job_msg"))
    b = {k: v for k, v in b.items() if k not in ("job_id", "job_parent", "job_msg")}
    if fb is not None and isinstance(b.get("multi"), str):
        b["multi"] = b["multi"].lower() in ("1", "true", "yes")
    r = chat_post(c, aid, uid, "agent", b, files)
    from ..agents.steps import steps_take
    if jid or offer:
        c.execute("UPDATE agent_chat SET job_id=?, job_parent=?, offer_save=?, job_msg=? WHERE id=?", (jid, jpar, 1 if offer else 0, jmsg, r["id"]))
        if jid and jpar:  # 2.59.0 (#1827): the job keeps its leader (once set it stays), so all its messages share the colour
            c.execute("UPDATE agent_jobs SET parent_id=? WHERE id=? AND parent_id IS NULL", (jpar, jid))
        r = c.execute("SELECT * FROM agent_chat WHERE id=?", (r["id"],)).fetchone()
    if not b.get("permission"):  # 2.32.0 (#1081): the answer takes the live steps of the run along (a permission question: the run goes on)
        steps_take(c, aid, uid, r["id"])
    text = r["body"] or " ".join(f"📎 {f['name']}" for f in chat_files_of(c, [r["id"]]).get(r["id"], []))
    c.execute("UPDATE agents SET typing_user=NULL, typing_until=0 WHERE user_id=? AND typing_user=?", (aid, uid))  # 2.4.1: answered
    s = collab_user(c, uid, None)
    from ..agents.chat import h6e_agent_push_ok
    if s and h6e_agent_push_ok(aid, uid):  # 2.86.0 (N31): daily push budget per agent and person
        name = user_names(c, [aid]).get(aid, "?")
        snippet = re.sub(r"\s+", " ", text)[:280]
        ch = json.loads(r["choices"]) if r["choices"] else {}
        # 2.35.0 (#1103): an approval request pushes as "Approval needed" (row approval of the notification settings, on by
        # default: a direct question to the person; the list ceiling of its task applies); off = the plain chat push
        if ch.get("approval") and notif_ok(c, uid, s, "approval", "push", _chat_task_lid(c, r["task_id"])) \
                and _approval_pushes_hour(c, aid, uid) <= APPROVAL_PUSH_HOUR:  # review M5: at most 5 an hour, then the plain push
            lg = lang_of(s)
            own = c.execute("SELECT 1 FROM user_settings WHERE user_id=? AND key='push_priority'", (uid,)).fetchone()
            g.pushes.append((uid, tr("Approval needed: {0}", name, lg=lg), ch["approval"].get("title") or snippet,
                             f"{PUBLIC_URL}/#agents/{aid}", push_prio(s) if own else push_prio(s, 4)))  # a chosen priority wins
        else:
            g.pushes.append((uid, name, snippet, f"{PUBLIC_URL}/#agents/{aid}", push_prio(s)))
    bump(c)
    c.commit()
    chat_unlink_trimmed()
    return jsonify(chat_one(c, r, api=True)), 201


@app.get("/api/v1/chat-attachments/<int:fid>")
@v1_view
def v1_chat_file_get(fid):
    """2.13.1 (#465): the binary of a chat file: the agent of its conversation, or the person (own token)."""
    v1_args(("dl", "v"))
    return send_stored(chat_file_access(db(), fid))


@app.delete("/api/v1/chat-attachments/<int:fid>")
@v1_view
def v1_chat_file_del(fid):
    """2.13.1 (#465): the sender removes one of its chat files."""
    v1_args(())
    c = db()
    r = chat_file_access(c, fid, write=True)
    m = chat_file_delete(c, r)
    return jsonify(ok=True, message_id=r["message_id"], message=chat_one(c, m, api=True) if m else None)


@app.get("/api/v1/tasks/<int:tid>/attachments")
@v1_view
def v1_task_attachments(tid):
    """2.13.1 (#465): the files of a task and of its comments (comment_id) -- only where the token's user sees the task
    with its comments; download with GET /api/v1/attachments/{id}."""
    v1_args(())
    c = db()
    _v1_live(c, tid, write=False, full=True)
    live = {r[0] for r in c.execute("SELECT id FROM comments WHERE task_id=? AND deleted_at IS NULL", (tid,))}
    rows = c.execute("SELECT id, name, mime, size, comment_id, created_at, enc FROM attachments WHERE task_id=? ORDER BY id", (tid,)).fetchall()
    # 2.42.0 (#828): an encrypted file is listed as such (only its uploader can open it, never an agent)
    from ..files.scan import sc_up
    return jsonify(data=sc_up(c, "att", [{"id": r["id"], "task_id": tid, "comment_id": r["comment_id"], "name": r["name"], "mime": r["mime"],
                                         "size": r["size"], "created_at": r["created_at"], "url": f"/api/v1/attachments/{r['id']}",
                                         **({"encrypted": True} if r["enc"] else {})}
                                        for r in rows if r["comment_id"] is None or r["comment_id"] in live]), next_cursor=None)  # 2.61.0 (#1818): + up


@app.get("/api/v1/attachments/<int:aid>")
@v1_view
def v1_attachment_get(aid):
    """2.13.1 (#465): the binary of a task / comment attachment (same rights as the app: sees the task with its comments)."""
    v1_args(("dl", "v"))
    c = db()
    a = need_attachment(c, aid, False)
    need_task(c, a["task_id"], write=False, full=True)
    if c.execute("SELECT deleted_at FROM tasks WHERE id=?", (a["task_id"],)).fetchone()[0]:
        raise Denied(404)
    return send_stored(a)


@app.post("/api/v1/agent/chats/<int:uid>/messages/<mid>/reactions")
@v1_view
def v1_agent_chat_react(uid, mid):
    """2.7.2 (#421): the agent reacts to a message of its chat with person uid ({emoji, on?}); never an approval, no event."""
    v1_args(())
    aid = need_agent()
    c = db()
    mid = as_int(mid, "mid", 1)  # a named path segment, so the OpenAPI path can call it {mid}
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("emoji", "on"))
    if unknown:
        raise UnknownFields(unknown)
    m = c.execute("SELECT * FROM agent_chat WHERE id=? AND agent_id=? AND user_id=?", (mid, aid, uid)).fetchone()
    if not m or not agent_shares(c, aid, uid):
        raise Denied(404)
    g.v1_body = b
    return jsonify(chat_react_req(c, m, aid))


@app.post("/api/v1/agents/<int:aid>/chat/<mid>/choice")
@v1_view
def v1_agent_chat_choice(aid, mid):
    """2.28.0 (#1005): {choice_ids: [...]} -- a person (own token) answers an agent's question with its buttons."""
    from ..agents.chat import chat_choice_set
    from ..agents.core import need_chat_agent
    v1_args(())
    c = db()
    need_chat_agent(c, aid)
    mid = as_int(mid, "mid", 1)
    m = c.execute("SELECT * FROM agent_chat WHERE id=? AND agent_id=? AND user_id=?", (mid, aid, me())).fetchone()
    if not m:
        raise Denied(404)
    m2 = chat_choice_set(c, m, me(), v1_json().get("choice_ids"))
    c.commit()
    return jsonify(chat_one(c, m2, api=True))


@app.post("/api/v1/agents/<int:aid>/chat/<mid>/reactions")
@v1_view
def v1_person_chat_react(aid, mid):
    """2.7.2 (#421): a person (token) reacts to a message of their chat with agent aid ({emoji, on?}); 👍 / 👎 on the agent's
    message = approval / rejection, the agent gets the event reaction."""
    v1_args(())
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot use this endpoint"))
    c = db()
    mid = as_int(mid, "mid", 1)
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("emoji", "on"))
    if unknown:
        raise UnknownFields(unknown)
    need_chat_agent(c, aid)
    m = c.execute("SELECT * FROM agent_chat WHERE id=? AND agent_id=? AND user_id=?", (mid, aid, me())).fetchone()
    if not m:
        raise Denied(404)
    g.v1_body = b
    return jsonify(chat_react_req(c, m, me()))


@app.post("/api/v1/agent/typing")
@v1_view
def v1_agent_typing():
    """2.4.1 (#375): {chat_user_id} -- "the agent is writing an answer to you": typing dots in that person's chat for
    AGENT_TYPING_S seconds (send it again to keep them; the answer ends them). Optional: the status "working" shows them too."""
    v1_args(())
    aid = need_agent()
    b = v1_json()
    unknown = sorted(k for k in b if k != "chat_user_id")
    if unknown:
        raise UnknownFields(unknown)
    uid = b.get("chat_user_id")
    if isinstance(uid, bool) or not isinstance(uid, int) or uid < 1:
        raise BadInput(tr("Invalid value: {0}", "chat_user_id"))
    c = db()
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or is_agent(u) or not agent_shares(c, aid, uid):
        raise Denied(404)
    old = agent_row(c, aid)
    c.execute("UPDATE agents SET typing_user=?, typing_until=? WHERE user_id=?", (uid, time.time() + AGENT_TYPING_S, aid))
    if agent_typing_to(old, uid) <= 2:  # a new signal (not a refresh): the person's client reloads
        bump(c)
    c.commit()
    return jsonify(ok=True, chat_user_id=uid, expires_in=AGENT_TYPING_S)


@app.post("/api/v1/tasks/<int:tid>/tidy")
@v1_view
def v1_task_tidy(tid):
    """{title?, notes?, section_id?, list_tags?, priority?} -- an agent tidies a task itself (the list's agent_tidy must be
    auto). The original text stays at the top of the notes."""
    v1_args(())
    need_agent()
    c = db()
    _v1_live(c, tid)
    t = c.execute("SELECT t.*, l.agent_tidy FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,)).fetchone()
    if (t["agent_tidy"] or "off") != "auto":
        raise Denied(409, tr("Tidying up is not set to automatic in this project"))
    if tidy_agent_of(c, t["list_id"]) != me():  # 2.4.1 (#379): exactly one agent tidies a list
        raise Denied(403, tr("Another agent tidies up this project"))
    b = dict(v1_json() or {})
    # 2.27.0 (#999): never over someone's work. Refused (409, try again later) while a person edits the task, when people
    # changed it after the tidy event went out, or when base_updated_at (the task's updated_at the agent read) is old
    base = b.pop("base_updated_at", None)
    from ..agents.core import task_being_edited
    p = c.execute("SELECT sent_at FROM tidy_pending WHERE task_id=?", (tid,)).fetchone()
    if task_being_edited(tid) or (base is not None and base != t["updated_at"]) or (p and p["sent_at"] and (t["updated_at"] or "") > p["sent_at"]):
        raise Denied(409, tr("Someone is working on this task right now: tidy it up later"))
    s = clean_suggestion(c, t, b)
    tidy_apply(c, c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone(), s)
    bump(c)
    c.commit()
    return jsonify(v1_one(c, tid))


@app.get("/api/v1/agents")
@v1_view
def v1_agents():
    v1_args(())
    c = db()
    return jsonify(data=agents_for(c, me()) if not is_agent(g.user) else [agent_public(c, agent_row(c, me()))], next_cursor=None)


# ---- 2.26.0 (#949): a proposal to ANOTHER topic. An agent may suggest tasks for a list it does not see (e.g. a change to a
# shared file that belongs to another team's topic). It lands as a ready proposal (kind extract) with the list's owner --
# never as an event for that list's agent; only when a person applies it do tasks exist. Allowed targets: lists owned by a
# person the agent already works with (agent_shares); everything else answers 404 (no probing of list ids).
XPROP_OPEN_MAX = 10   # open cross-topic proposals per agent


@app.post("/api/v1/agent/proposals")
@v1_view
def v1_agent_cross_proposal():
    """{list_id, title, reason, tasks: [{title, notes?, due?}]} -- the agent proposes tasks for a list it cannot see."""
    from ..agents.core import agent_shares
    v1_args(())
    aid = need_agent()
    b = v1_json()
    if isinstance(b, dict) and b.get("kind") in ("inquiry", "setup"):  # 2.51.0 B (#1351 #1358): a project from an inquiry, the setup
        from ..agents.propkinds2 import pk2_agent_proposal
        return pk2_agent_proposal(aid, b)
    if isinstance(b, dict) and b.get("kind") == "notice":  # 2.70.0 C (#1359): a reminder of a contract's notice deadline
        from ..agents.contractprop import ctr_agent_proposal
        return ctr_agent_proposal(aid, b)
    _p_keys(b, "", ("list_id", "title", "reason", "tasks", "summary"))
    lid = _p_int(b.get("list_id"), "list_id")
    title = _p_str(b.get("title"), "title", PROP_TITLE_MAX, True)
    reason = _p_str(b.get("reason"), "reason", PROP_NOTES_MAX, True, line=False)
    c = db()
    lst = c.execute("SELECT l.*, u.kind AS okind, u.disabled AS odis FROM lists l JOIN users u ON u.id=l.owner_id WHERE l.id=?", (lid,)).fetchone()
    if not lst or lst["okind"] == "agent" or lst["odis"] or lst["is_inbox"] or lst["archived"] or lst["life"] == "health" \
            or not agent_shares(c, aid, lst["owner_id"]):
        raise Denied(404)
    if list_role(c, lid, aid):
        raise BadInput(tr("You can see this project: create the tasks there directly"))
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND kind='extract' AND prop_state='ready' AND input ILIKE '%\"cross\": true%'",
                 (aid,)).fetchone()[0] >= XPROP_OPEN_MAX:
        return v1_err(429, tr("You have {0} open proposals for other topics: wait until people decided on them", XPROP_OPEN_MAX))
    tasks = [{**{k: v for k, v in t.items() if k in ("title", "notes", "due")}} if isinstance(t, dict) else t
             for t in (b.get("tasks") or [])] if isinstance(b.get("tasks"), list) else b.get("tasks")
    inp = {"list": {"id": lid, "name": lst["name"], "sections": []}, "members": [], "text": reason, "cross": True}
    p = prop_validate("extract", {"tasks": tasks, **({"summary": b["summary"]} if "summary" in b else {})}, inp)
    ts = iso(now_utc())
    aname = user_names(c, [aid]).get(aid, "?")
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id,proposal)
                       VALUES(?,NULL,?,?,'waiting','',?,?,'extract',?,'ready',?,?)""",
                    (aid, lst["owner_id"], tr("Proposal from {0}: {1}", aname, title)[:JOB_TITLE_MAX], ts, ts,
                     json.dumps(inp, ensure_ascii=False), lid, json.dumps(p, ensure_ascii=False)))
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    prop_ready_notify(c, j)
    bump(c)
    c.commit()
    print("cross-topic proposal", jid, "agent", aid, "list", lid, flush=True)
    return jsonify({**job_dict(c, j), "proposal": p}), 201
