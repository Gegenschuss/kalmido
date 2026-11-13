"""2.235.0 A (#2891 #2900 #2901): the control level of an agent (Kontrolle), its one-way steps and the deadline of its approvals.

Applies to agents only (people keep their roles and the approvals of gates.py). Stored as JSON in agents.control; '' = no
level chosen (an agent from before 2.235.0): it works as before, no gate at all, until its owner picks a level. A new agent
starts with approve_all (agents/admin.py make_agent, ctl_new; KALMIDO_AGENT_CONTROL_NEW).

Levels, per agent and per project (a project's exception wins over the agent's level):
  approve_all  every change waits for an approval card
  routine      small reversible steps (create tasks, plan them, comment, tick off) without asking; the rest by card
  free         the agent decides itself towards its goal (free text); every decision is one line in the history
A personal agent never gets more in a project than its owner's own rights there (owner / admin -> free, edit -> routine,
reading / commenting -> approve_all; ctl_cap). One-way steps (#2900) always need a card, on every level: the server
enforces deleting (every DELETE route and the delete actions); costs, login / registration, migrations without a way back and
the owner's own items happen outside Kalmido -- they reach the agent as its rules (GET /api/v1/agent "control").

Enforced on the server (ctl_gate, before every write of an agent token under /api/v1/): each route has a class
(ctl_class: meta = the agent's own channel, always allowed; routine; change = everything not listed; one_way). Refused =
409 {"error": {"code": "approval_required", "step", "level", ...}}. The way to the approval: an approval card in its chat
(POST /api/v1/agent/chats/<uid> {"approval": {"title", "what", "step": {"method", "path", "body"?}, "recommend"?, "one_way"?}});
after the person's Yes the agent sends exactly that request again with the header X-Kalmido-Approval: <id of the card> -- once,
bound to method + path + body (2.235.0 A2: a one-way step only with the Yes of a person who may change the project). Each decision the agent took without a card (and each approved step) is one line in the history
(agent_decisions, newest CTL_KEEP per agent) with Undo where the server can (created -> trash, ticked off -> open again,
plan -> the old dates, comment -> deleted).

#2901: an approval card left unanswered for the deadline (off | 1h | 4h | 1d | 3d) ends by itself (ctl_deadline_tick,
watchdog): reject (default), ask_again (one more push, then reject) or recommend (the card's recommended answer; never on a
one-way step -- there reject). The result is a line in the history and the event approval_expired."""
import json
import os
import re
import unicodedata
from datetime import timedelta
from urllib.parse import unquote
from flask import g, jsonify, request

from ..core.config import API_PREFIX, app, PUBLIC_URL
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, iso_ms, now_utc, parse_iso
from ..core.pg import insert_id
from ..core.access import Denied, joined_lists_sql, list_role, task_visible, WRITE_ROLES, otr_live
from ..core.errors import BadInput, UnknownFields
from ..api.common import hit_limit, v1_args, v1_call, v1_err, v1_json, v1_view, V1Error
from ..accounts.session import me
from ..tasks.lifecycle import apply_update, task_reopen, trash_task
from ..collab.news import news_forget_comment
from ..notify.push import notify, push_prio, WD_TICKS
from ..agents.core import agent_emit, agent_row, agent_shares, is_agent, need_agent
from ..agents.chat import _jload, chat_choices_withdraw, choice_state
from ..agents.workstyle import ws_need_editor
from ..agents.steps import redact  # 2.653.0 (#5079): a decision line masks secrets like a step
from ..core.objcomments import ocm_trash  # 2.530.0 A (#4315, B11): text and files into the trash like comment_delete; 2.972.0 (#5272): the core's

CTL_LEVELS = ("approve_all", "routine", "free")
CTL_ONE_WAY_FIXED = ("delete", "costs", "login", "migration")  # #2900: fixed, cannot be switched off
CTL_ONE_WAY_TEXT = {"delete": N_("Deleting"), "costs": N_("Anything that costs money"), "login": N_("Sign-in and registration"),
                    "migration": N_("Migrations without a way back")}
CTL_ONE_WAY_MAX, CTL_ONE_WAY_LEN = 20, 120
CTL_DEADLINES = {"off": None, "1h": 3600, "4h": 4 * 3600, "1d": 86400, "3d": 3 * 86400}
CTL_THEN = ("reject", "ask_again", "recommend")
CTL_GOAL_MAX = 500
CTL_DEFAULTS = {"level": "approve_all", "goal": "", "projects": {}, "one_way": [], "deadline": "off", "then": "reject"}
CTL_KEEP = 500  # history lines per agent (2.653.0, #5079: was 50; the dialog shows the newest groups, "Whole history" pages)
CTL_SHOW = 50  # 2.653.0 (#5079): the lines GET /api/agents/<id>/control carries; older ones through .../control/history?before=
CTL_PAGE_MAX = 200
CTL_DECISION_MAX = 200  # 2.653.0 (#5079): title and ref of a decision the agent writes itself (POST /api/v1/agent/decisions)
CTL_DECISION_RATE = 30  # per minute and agent
CTL_FIELDS_MAX = 12
CTL_WRITE = ("POST", "PUT", "PATCH", "DELETE")
CTL_PLAN_KEYS = {"due", "due_time", "start"}  # "plan" = only these dates (+ the conflict helpers of PATCH)
CTL_PLAN_EXTRA = {"expect_updated_at", "_prev", "shift_chain"}
CTL_HEADER = "X-Kalmido-Approval"
CTL_BODY_MAX = 32000  # 2.235.0 A2 (#2891): the bound body of an approval card (canonical JSON)

# (methods, path with {} for the route variables, class). First match wins; DELETE not listed = one_way, the rest = change.
CTL_ROUTES = (
    (("PATCH",), r"^/agent/objects/\{\}/\{\}$", "change"),  # 2.558.0 (#4709): an object of the shared core (an area's data, not the agent's channel)
    (CTL_WRITE, r"^/agent(/|$)", "meta"),  # the agent's own channel: status, typing, chat + approval cards, jobs, proposals, queue
    (("POST",), r"^/tasks/\{\}/typing$", "meta"),
    (CTL_WRITE, r"^/tasks/\{\}/working$", "meta"),  # 2.407.0 (#3513): "agent is working" mark, its own status like typing
    (("POST",), r"^/(news/read|team/rooms/\{\}/read)$", "meta"),
    (("POST",), r"^/comments/\{\}/withdraw$", "meta"),
    (("POST",), r"^/(layouts/proposals|lists/\{\}/(playbook|rules)/proposals)$", "meta"),  # proposals a person takes or not
    (("POST",), r"^/(documents/\{\}/receipt-suggestion|office/payment-suggestions)$", "meta"),
    (("POST",), r"^/tasks/brief$", "meta"),  # 2.392.3 (#3368): the work package export reads only (a POST for its list of ids)
    (CTL_WRITE, r"^/agents/\{\}/chat/", "meta"),
    (("POST",), r"^/tasks$", "routine"),
    (("POST",), r"^/tasks/\{\}/(subtasks|comments|complete|reopen|skip)$", "routine"),
    (("POST", "DELETE"), r"^/tasks/\{\}/watchers(/\{\})?$", "routine"),  # 2.473.0 (#3357): small and reversible, the task itself stays as it is
    (("POST", "DELETE"), r"^/tasks/\{\}/relations(/\{\})?$", "routine"),  # 2.576.0 (#3371): a saved relation (relates / duplicate; close as duplicate = won't do, undoable), reversible like watchers
    (("PATCH",), r"^/tasks/\{\}$", "plan"),
    (("POST",), r"^/tasks/batch$", "batch"),
    (("POST",), r"^/videos/\{\}/comments$", "routine"),
    (("POST",), r"^/team/rooms/\{\}/messages$", "routine"),
    (("POST",), r"^/(comments|team/messages)/\{\}/reactions$", "routine"),
    (("DELETE",), r"^/comments/\{\}/reactions/\{\}$", "routine"),
    (("POST",), r"^/comments/\{\}/choice$", "routine"),
    (("DELETE",), r"^/(time/timer|tasks/\{\}/waiting)$", "change"),  # stops a timer / ends waiting: nothing is deleted
    (("POST",), r"^/(folders/delete|imports/\{\}/undo)$", "one_way"),  # delete actions behind a POST
)
CTL_STEP_RANK = {"meta": 0, "routine": 1, "change": 2, "one_way": 3}


def ctl_rule_path(rule):
    """The route of a request as the table writes it: /tasks/{} (no API prefix)."""
    return re.sub(r"<[^>]+>", "{}", rule.rule[len(API_PREFIX) - 1:]) if rule is not None else ""


def ctl_class(method, path, b=None):
    """meta | routine | change | one_way of a write request (path = ctl_rule_path, b = its JSON body)."""
    b = b if isinstance(b, dict) else {}
    for ms, rx, cls in CTL_ROUTES:
        if method in ms and re.search(rx, path):
            if cls == "plan":  # 2.542.0 (#4609): taking the lock off (locked false) is routine too - completing a locked task
                # needs it first, and the tasks an agent creates start locked (#1118); setting a lock stays a change
                unlock = {"locked"} if b.get("locked") is False or b.get("locked") == 0 else set()
                return "routine" if b and set(b) <= CTL_PLAN_KEYS | CTL_PLAN_EXTRA | unlock else "change"
            if cls == "batch":
                act, ch = b.get("action"), b.get("changes")
                if act == "delete":
                    return "one_way"
                if act in ("complete", "reopen") or (act == "update" and isinstance(ch, dict) and ch and set(ch) <= CTL_PLAN_KEYS):
                    return "routine"
                return "change"
            return cls
    return "one_way" if method == "DELETE" else "change"


# ---------------------------------------------------------------- the stored settings
def ctl_new():
    """What a new agent stores at creation (agents/admin.py make_agent): {"level": ...}, None = nothing (works as before;
    the test containers start so, tests/start.sh)."""
    v = (os.environ.get("KALMIDO_AGENT_CONTROL_NEW") or "approve_all").strip()
    return None if v == "legacy" else {"level": v if v in CTL_LEVELS else "approve_all"}


def ctl_load(a):
    """The stored dict of agent row a (None = no level chosen yet: an agent from before 2.235.0)."""
    raw = a["control"] if a is not None and "control" in a.keys() else ""
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return d if isinstance(d, dict) and d.get("level") in CTL_LEVELS else None


def ctl_get(a):
    """The effective settings of agent row a (None = no level chosen)."""
    d = ctl_load(a)
    if d is None:
        return None
    try:
        return ctl_clean(CTL_DEFAULTS, d, strict=False)
    except BadInput:
        return {**CTL_DEFAULTS, "level": d["level"]}


def ctl_clean(cur, b, strict=True):
    """Validates a partial dict b over cur -> the new full dict. projects is merged: {list id: level | null (= remove)}."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid value: {0}", "control"))
    unknown = sorted(k for k in b if k not in CTL_DEFAULTS)
    if unknown and strict:
        raise UnknownFields(unknown)
    out = {k: cur.get(k, v) for k, v in CTL_DEFAULTS.items()}
    out["projects"] = dict(out["projects"] or {})
    for k, v in b.items():
        if k not in CTL_DEFAULTS:
            continue
        try:
            if k == "projects":
                if not isinstance(v, dict):
                    raise BadInput(tr("Invalid value: {0}", k))
                for lid, lv in v.items():
                    if not str(lid).isdigit() or (lv is not None and lv not in CTL_LEVELS):
                        raise BadInput(tr("Invalid value: {0}", k))
                    if lv is None:
                        out["projects"].pop(str(int(lid)), None)
                    else:
                        out["projects"][str(int(lid))] = lv
            else:
                out[k] = ctl_value(k, v)
        except BadInput:
            if strict:
                raise
    return out


def ctl_value(k, v):
    bad = BadInput(tr("Invalid value: {0}", k))
    if k == "level":
        if v not in CTL_LEVELS:
            raise bad
        return v
    if k == "goal":
        if v is None:
            return ""
        if not isinstance(v, str) or len(v.strip()) > CTL_GOAL_MAX:
            raise bad
        return v.strip()
    if k == "one_way":
        if not isinstance(v, list) or len(v) > CTL_ONE_WAY_MAX or \
                any(not isinstance(x, str) or not x.strip() or len(x.strip()) > CTL_ONE_WAY_LEN for x in v):
            raise bad
        return list(dict.fromkeys(" ".join(x.split()) for x in v))
    if k == "deadline":
        if v not in CTL_DEADLINES:
            raise bad
        return v
    if k == "then":
        if v not in CTL_THEN:
            raise bad
        return v
    raise bad


def ctl_cap(c, a, lid):
    """The highest level the agent may have in project lid: its owner's own rights there (a team agent: no cap)."""
    if not a["owner_id"] or not lid:
        return "free"
    role = list_role(c, lid, a["owner_id"])
    return "free" if role in ("owner", "admin") else "routine" if role == "edit" else "approve_all"


def ctl_min(*levels):
    return min(levels, key=CTL_LEVELS.index)


def ctl_level(c, a, d, lid):
    """The effective level of agent row a (settings d) in project lid (None = without a project)."""
    lv = (d["projects"].get(str(lid)) if lid else None) or d["level"]
    return ctl_min(lv, ctl_cap(c, a, lid)) if lid else lv


def ctl_public(c, a):
    """What agent row a reads in GET /api/v1/agent "control" (and the event control_changed)."""
    d = ctl_get(a)
    fixed = [{"id": k, "text": tr(CTL_ONE_WAY_TEXT[k])} for k in CTL_ONE_WAY_FIXED]
    if d is None:
        return {"level": None, "chosen": False, "enforced": False, "goal": "", "projects": [],
                "one_way": {"fixed": fixed, "custom": []}, "deadline": None, "then": "reject"}
    projects = [{"list_id": int(k), "level": v, "effective": ctl_level(c, a, d, int(k))} for k, v in sorted(d["projects"].items(), key=lambda x: int(x[0]))]
    return {"level": d["level"], "chosen": True, "enforced": True, "goal": d["goal"] if d["level"] == "free" else "",
            "projects": projects, "one_way": {"fixed": fixed, "custom": d["one_way"]},
            "deadline": CTL_DEADLINES[d["deadline"]], "then": d["then"],
            "approval_header": CTL_HEADER}


def ctl_set(c, a, b):
    """Validates and stores b for agent row a (a project level above the owner's rights there: 400); event control_changed."""
    cur = ctl_get(a)
    new = ctl_clean(cur or CTL_DEFAULTS, b)
    for lid, lv in (b.get("projects") or {}).items() if isinstance(b.get("projects"), dict) else ():
        if lv is not None and CTL_LEVELS.index(lv) > CTL_LEVELS.index(ctl_cap(c, a, int(lid))):
            raise BadInput(tr("Your own rights in this project allow at most “{0}”", tr(CTL_LEVEL_TEXT[ctl_cap(c, a, int(lid))])))
    if new != cur:
        # 2.235.0 A2 (#2901): a deadline counts from when it was set, never from before (older open cards keep their time)
        at = iso_ms(now_utc()) if new["deadline"] != (cur or CTL_DEFAULTS)["deadline"] else (ctl_load(a) or {}).get("deadline_set_at")
        keep = {"deadline_set_at": at} if at else {}
        c.execute("UPDATE agents SET control=? WHERE user_id=?", (json.dumps({**new, **keep}, ensure_ascii=False), a["user_id"]))
        a2 = agent_row(c, a["user_id"])
        agent_emit(c, a["user_id"], "control_changed", {"control": ctl_public(c, a2)})
        print("agent", a["user_id"], "control", ",".join(sorted(k for k in new if new[k] != (cur or {}).get(k))) or "-",
              "by", g.user["username"], flush=True)
    return new


CTL_LEVEL_TEXT = {"approve_all": N_("Approve everything"), "routine": N_("Routine free"), "free": N_("Free run with a goal")}


# ---------------------------------------------------------------- the gate
# 2.235.0 A2 (#2891): the object routes whose project the gate knows: (path prefix, route variable, query -> list_id)
CTL_OBJ = (
    ("/tasks/{}", "tid", "SELECT list_id FROM tasks WHERE id=?"),
    ("/lists/{}", "lid", None),
    ("/comments/{}", "cid", "SELECT t.list_id FROM obj_comments k JOIN tasks t ON t.id=k.ref_id AND k.kind='task' WHERE k.id=?"),
    ("/sections/{}", "sid", "SELECT list_id FROM sections WHERE id=?"),
    ("/notes/{}", "nid", "SELECT list_id FROM notes WHERE id=?"),
    ("/notepads/{}", "pid", "SELECT list_id FROM list_notepads WHERE id=?"),
    ("/sheets/{}", "sid", "SELECT list_id FROM sheets WHERE id=?"),
    ("/team/rooms/{}", "rid", "SELECT list_id FROM tchat_rooms WHERE id=?"),
    ("/team/messages/{}", "mid", "SELECT r.list_id FROM tchat_msgs m JOIN tchat_rooms r ON r.id=m.room_id WHERE m.id=?"),
    ("/time/entries/{}", "eid", "SELECT list_id FROM time_entries WHERE id=?"),
    ("/videos/{}", "vid", "SELECT list_id FROM video_reviews WHERE id=?"),
    ("/attachments/{}", "aid", "SELECT t.list_id FROM attachments x JOIN tasks t ON t.id=x.task_id WHERE x.id=?"),
)


def _ctl_int(v):
    """An id from a body (int or a string of digits) or None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if 0 < v < 2 ** 62 else None
    return int(v) if isinstance(v, str) and v.isdigit() and len(v) < 18 else None


def ctl_lists(c, aid, path, b):
    """The projects a write request concerns (route variables and body), only those the agent sees -> (lids, unknown).
    lids None = an object of a project the agent cannot see (the route itself refuses). 2.235.0 A2 (#2891): unknown = the
    request touches an object or names a project the gate cannot place (a route not in CTL_OBJ with a variable, an object
    without a project, a list_id that is no id): the caller caps a personal agent there (ctl_gate)."""
    va = request.view_args or {}
    lids, unknown = [], False
    if path == "/tasks/batch":
        ids = [x for x in b.get("ids") or [] if isinstance(x, int) and not isinstance(x, bool)][:500] if isinstance(b.get("ids"), list) else []
        if ids:
            lids = sorted({r[0] for r in c.execute(f"SELECT list_id FROM tasks WHERE id IN ({','.join('?' * len(ids))})", ids)})
        lids = [x for x in lids if list_role(c, x, aid)]
        ch = b.get("changes") if isinstance(b.get("changes"), dict) else {}
        if "list_id" in ch:  # a move: the target counts too
            t = _ctl_int(ch["list_id"])
            if t and list_role(c, t, aid):
                lids = sorted(set(lids) | {t})
            elif ch["list_id"] is not None:
                unknown = True
        return lids, unknown
    hit = next((x for x in CTL_OBJ if (path == x[0] or path.startswith(x[0] + "/")) and x[1] in va), None)
    if hit:
        if hit[2] is None:
            lids = [va[hit[1]]]
        else:
            r = c.execute(hit[2], (va[hit[1]],)).fetchone()
            lids = [r[0]] if r and r[0] else []
            unknown = bool(r) and not r[0]  # an object without a project (a sheet of nobody's project, a direct room ...)
        if lids and not all(list_role(c, x, aid) for x in lids):
            if hit in CTL_OBJ[:4]:
                return None, False  # tasks, lists, comments, sections: seen = may open; the route answers 404
            lids, unknown = [], True  # an object the agent reaches another way (a room member, its own entry): careful
    elif any(k for k in va):
        unknown = True  # an object route the gate cannot place (wiki, events, files, office ...)
    if path == "/tasks":  # a new task: its list, or the list of its parent / section (none: the agent's own default list)
        for k, q in (("parent_id", "SELECT list_id FROM tasks WHERE id=?"), ("section_id", "SELECT list_id FROM sections WHERE id=?")):
            if b.get(k) is not None and "list_id" not in b:
                r = c.execute(q, (_ctl_int(b[k]),)).fetchone() if _ctl_int(b[k]) else None
                if r and list_role(c, r[0], aid):
                    lids.append(r[0])
                else:
                    unknown = True
    if "list_id" in b and b["list_id"] is not None:  # a body naming a project (create there, move there)
        t = _ctl_int(b["list_id"])
        if t and list_role(c, t, aid):
            lids = sorted(set(lids) | {t})
        else:
            unknown = True
    return lids, unknown


def ctl_refuse(step, level, lid, d):
    # 2.1045.0 (#5827): the step is taken over as it stands (approval.step, never typed again) and run from the card after the Yes
    if step == "one_way":
        msg = tr("One-way step: ask with an approval card in your chat (approval.step = method, path, body and if_match exactly as in this answer), then after the Yes run it with POST /api/v1/agent/approvals/ID/run (MCP: run_approved_step) - the server sends exactly this step.")
    else:
        msg = tr("Your control level needs an approval for this step: ask with an approval card in your chat (approval.step = method, path, body and if_match exactly as in this answer), then after the Yes run it with POST /api/v1/agent/approvals/ID/run (MCP: run_approved_step) - the server sends exactly this step.")
    files = request.mimetype == "multipart/form-data" and bool(request.files)
    if files:  # 2.1078.0 (#5866, N4): the run from the card sends JSON only, an upload cannot run there: the header way
        msg = (tr("One-way step.") + " " if step == "one_way" else "") + tr("Your control level needs an approval for this upload: ask with an approval card in your chat (approval.step = method, path and body exactly as in this answer), then after the Yes send this request again with the files and the header X-Kalmido-Approval: ID of the card (MCP: use_approval) - the run from the card cannot send files.")
    rb = ctl_req_body()  # 2.235.0 A2 (#2891): the card binds the body too -- copy it into approval.step.body
    im = (request.headers.get("If-Match") or "").strip()[:200]  # 2.1045.0 (#5827): the version read, sent along when the card runs
    st = {"method": request.method, "path": request.path, **({"body": rb} if rb not in ({}, []) else {}), **({"if_match": im} if im else {})}
    return v1_err(409, msg, name="approval_required", step=step, level=level, project_id=lid,
                  approval={**st, "header": CTL_HEADER}, **({"run": "header"} if files else {}))


def ctl_req_body():
    """2.235.0 A2 (#2891): what an approval card binds of this request: its JSON body, else its form fields ({} = none).
    2.1085.0 (#5936): an upload binds its files too: field _files = [{field, name, sha256}] (ctl_files), so a Yes to
    "upload to X" holds for exactly these files under exactly these form fields."""
    if request.is_json:
        j = request.get_json(silent=True)
        return j if j is not None else {}
    b = request.form.to_dict(flat=True) if request.form else {}
    if CTL_FILES_KEY in b:  # 2.1085.0 (#5936, review): a form field of this name would hide behind the bound files
        raise BadInput(tr("Invalid value: {0}", CTL_FILES_KEY))
    fs = ctl_files()
    return {**b, CTL_FILES_KEY: fs} if fs else b


CTL_FILES_KEY = "_files"  # 2.1085.0 (#5936): the field of a bound body holding the files of an upload


def ctl_files():
    """2.1085.0 (#5936): the files of a multipart request as [{field, name, sha256}] (grouped by form field, each field in the
    order sent; review: the field is bound, a route taking "the first file of any field" gets the approved one); the stream
    of each file is wound back after hashing, the route reads it whole. [] = no upload."""
    import hashlib
    if request.mimetype != "multipart/form-data" or not request.files:
        return []
    out = []
    for k, f in request.files.items(multi=True):
        h = hashlib.sha256()
        f.stream.seek(0)
        for chunk in iter(lambda: f.stream.read(1 << 16), b""):
            h.update(chunk)
        f.stream.seek(0)
        out.append({"field": k, "name": f.filename or "", "sha256": h.hexdigest()})
    return out


def ctl_canon(x):
    """The canonical text of a body (keys sorted; no body = {})."""
    return json.dumps({} if x in (None, [], {}) else x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def ctl_norm_path(p):
    """A path as the server reads it (percent signs decoded, Unicode NFC): /comments/5/reactions/%F0%9F%91%8D = its emoji."""
    return unicodedata.normalize("NFC", unquote(p))


@app.before_request
def ctl_gate():
    """Every write of an agent token under /api/v1/: allowed by the level, by an approved card (once), or 409."""
    if request.method not in CTL_WRITE or not request.path.startswith(API_PREFIX) or request.url_rule is None:
        return None
    if g.get("auth_via") != "token" or not is_agent(g.get("user")) or g.get("approved_job"):
        return None  # people, and the replay of a request a person approved (api/scopes.py approval_run)
    c = db()
    a = agent_row(c, g.user["id"])
    d = ctl_get(a)
    web = None
    if a is not None and (a["provider"] or "") == "kalmido-server":  # 2.571.0 D (#4676): a server agent's run with web access is on
        from .srvweb import srvweb_state
        web = srvweb_state(c, a["user_id"])
    if d is None and web is None:
        return None  # no level chosen: works as before
    if web is not None:  # decision 05.11.2026: with the web, every change by card - whatever the level (also none chosen)
        d = {**(d or CTL_DEFAULTS), "level": "approve_all", "projects": {}}
    path = ctl_rule_path(request.url_rule)
    b = request.get_json(silent=True) if request.is_json else None
    b = b if isinstance(b, dict) else {}
    step = ctl_class(request.method, path, b)
    if step == "meta" and web is not None:  # its own channel too: messages only to the people of the run, rules by card
        from .srvweb import srvweb_gate_step
        step = srvweb_gate_step(web, request.method, path, b, request.view_args or {}) or step
    if step == "meta":
        return None
    lids, unknown = ctl_lists(c, a["user_id"], path, b)
    if lids is None:
        return None  # a project it cannot see: the route answers 404
    level = ctl_min(*[ctl_level(c, a, d, x) for x in lids]) if lids else d["level"]
    if unknown and a["owner_id"]:  # 2.235.0 A2 (#2891): a place the gate cannot check the owner's rights for: at most routine
        level = ctl_min(level, "routine")
    lid = lids[0] if len(lids) == 1 else None
    ok = (step == "routine" and level in ("routine", "free")) or (step == "change" and level == "free")
    mid = None
    if not ok:
        hdr = request.headers.get(CTL_HEADER, "").strip()
        if not hdr:
            return ctl_refuse(step, level, lid, d)
        mid, why = ctl_claim(c, a, hdr, step, lids)
        if not mid:  # 2.1045.0 (#5827): the 409 names what does not fit (reason + its words), never a content of the card
            return v1_err(409, tr("This approval does not fit: it needs a person's Yes, exactly this method, path and body, and works once.")
                          + " " + ctl_reason_text(why), name="approval_invalid", step=step, level=level, project_id=lid, **why)
    g.ctl_note = {"step": step, "level": level, "lid": lid, "path": path, "mid": mid, "aid": a["user_id"],
                  "before": ctl_before(c, path, b), "info": ctl_info(path, b)}
    return None


def ctl_card_row(c, aid, mid):
    """2.1045.0 (#5827): the approval card mid of agent aid -> (row, choices, answer) or (None, None, None)."""
    m = c.execute("""SELECT user_id, choices, choice FROM agent_chat WHERE id=? AND agent_id=? AND sender='agent'
                     AND choices->'approval' IS NOT NULL""", (mid, aid)).fetchone()
    return (m, _jload(m["choices"]) or {}, _jload(m["choice"])) if m else (None, None, None)


def ctl_card_state(m, ch, ans):
    """2.1045.0 (#5827): why card m cannot be used (a reason dict) or None = answered Yes and not used yet."""
    if not m:
        return {"reason": "not_found"}
    ap = ch.get("approval") or {}
    if ap.get("used_at"):
        return {"reason": "used", "used_at": ap["used_at"]}
    if not isinstance(ans, dict):
        return {"reason": "withdrawn"} if ch.get("withdrawn_at") else {"reason": "unanswered"}
    if ans.get("ids") != ["yes"]:
        return {"reason": "rejected"}
    if not isinstance(ap.get("step"), dict) or not ap["step"].get("method"):
        return {"reason": "no_step"}
    return None


def ctl_body_diff(a, b):
    """2.1045.0 (#5827): the names of the top-level fields in which two bodies differ (never their values); a list body: ["[]"]."""
    a = {} if a in (None, [], {}) else a
    b = {} if b in (None, [], {}) else b
    if not isinstance(a, dict) or not isinstance(b, dict):
        return ["[]"]
    return sorted(str(k) for k in set(a) | set(b) if ctl_canon(a.get(k, None)) != ctl_canon(b.get(k, None)) or (k in a) != (k in b))[:CTL_FIELDS_MAX]


CTL_REASON_TEXT = {"not_found": N_("No approval card with this id of yours."),
                   "unanswered": N_("The card has not been answered yet."),
                   "withdrawn": N_("The card was withdrawn or expired."),
                   "rejected": N_("The card was answered No."),
                   "no_step": N_("The card names no step (method and path)."),
                   "one_way": N_("A one-way step needs a card marked one_way and the Yes of a person."),
                   "approver_rights": N_("The person who said Yes may not change this project themselves."),
                   "approver_shares": N_("The person who said Yes shares no project with you."),
                   "format": N_("The header must be the id of the card (a number)."),
                   "nested": N_("The step of a card cannot run a card."),
                   "upload": N_("The card approves an upload: send the upload again with the same files and the header X-Kalmido-Approval: ID of the card (MCP: use_approval) - the run from the card cannot send files.")}
CTL_STATE_FIELDS = {"expect_updated_at", "prev", "_prev", "If-Match"}  # 2.1045.0 (#5827): fields that carry the state the step read


def ctl_reason_text(why):
    """2.1045.0 (#5827): the reason of a 409 approval_invalid in words (names, methods and times only, no content)."""
    r = why.get("reason")
    if r == "method":
        return tr("The card approves the method {0}, your call is {1}.", why.get("card_method", ""), why.get("call_method", ""))
    if r == "path":
        return tr("The card approves the path {0}, your call is {1}.", why.get("card_path", ""), why.get("call_path", ""))
    if r == "stale":
        return tr("The state field differs from the card ({0}): the target changed since the card, or you read it again. Read it again and ask with a new card.",
                  ", ".join(why.get("fields") or []))
    if r == "body" and CTL_FILES_KEY in (why.get("fields") or []):  # 2.1085.0 (#5936): another file than the card's
        return tr("The files differ from the card (names or content): the card approves exactly the files of the refused upload. Send exactly these files, or ask with a new card.")
    if r == "body":
        return tr("The body differs from the card in: {0}. Run the card with run_approved_step (POST /api/v1/agent/approvals/ID/run) instead of sending it again.",
                  ", ".join(why.get("fields") or []))
    if r == "used":
        if why.get("used_at"):  # 2.1045.0 (#5827, N3): a parallel try that failed later frees the card again -- never "it ran" for sure
            return tr("The card is in use right now or has run (at {0}): check the result instead of sending it again.", why["used_at"])
        return tr("The card is in use right now or has run: check the result instead of sending it again.")
    return tr(CTL_REASON_TEXT.get(r, N_("The approval does not fit.")))


def ctl_claim(c, a, hdr, step, lids):
    """Uses the approval card hdr (a message id) for this request: answered Yes, its step = this method + path + body, not
    used yet. Atomic (two requests with the same card: one wins). 2.235.0 A2 (#2891): the body is bound (step.body, none =
    an empty body); a one-way step needs a card marked one_way and the Yes of a person (never the deadline's "recommend");
    the person who said Yes (the deadline: the person of the card) must be allowed to change every project the request
    touches themselves, without a project share a list with the agent (a team agent's chat partner who only reads there
    approves nothing). -> (the message id, {}) or (None, {"reason", ...}). 2.1045.0 (#5827): the reason of a refusal
    (ctl_reason_text): method / path (both sides), body / stale (the names of the differing fields), used (+ used_at), ..."""
    aid = a["user_id"]
    if not re.fullmatch(r"[0-9]{1,18}", hdr):
        return None, {"reason": "format"}
    m, ch, ans = ctl_card_row(c, aid, int(hdr))
    bad = ctl_card_state(m, ch, ans)
    if bad:
        return None, bad
    ap = ch.get("approval") or {}
    st = ap["step"]
    if st.get("method") != request.method:
        return None, {"reason": "method", "card_method": st.get("method"), "call_method": request.method}
    if ctl_norm_path(str(st.get("path") or "")) != unicodedata.normalize("NFC", request.path):
        return None, {"reason": "path", "card_path": str(st.get("path") or "")[:300], "call_path": request.path[:300]}
    rb = ctl_req_body()
    if request.is_json and isinstance(rb, dict) and CTL_FILES_KEY in rb:  # 2.1085.0 (#5936): the files of an upload card come
        return None, {"reason": "body", "fields": [CTL_FILES_KEY]}  # only with the files themselves, never typed into a JSON body
    if ctl_canon(st.get("body")) != ctl_canon(rb):
        fields = ctl_body_diff(st.get("body"), rb)
        return None, {"reason": "stale" if fields and set(fields) <= CTL_STATE_FIELDS else "body", "fields": fields}
    who = ans.get("user_id") or (m["user_id"] if ans.get("via") == "deadline" else None)
    if not who:
        return None, {"reason": "unanswered"}
    if step == "one_way" and (not ap.get("one_way") or ans.get("via") == "deadline"):
        return None, {"reason": "one_way"}
    if lids and any(list_role(c, x, who) not in WRITE_ROLES for x in lids):
        return None, {"reason": "approver_rights"}
    if not lids and not agent_shares(c, aid, who):
        return None, {"reason": "approver_shares"}
    n = c.execute("""UPDATE agent_chat SET choices=jsonb_set(choices, '{approval,used_at}', to_jsonb(CAST(? AS TEXT)))
                     WHERE id=? AND agent_id=? AND choices->'approval'->>'used_at' IS NULL""",
                  (iso_ms(now_utc()), int(hdr), aid)).rowcount
    c.commit()
    if not n:  # the other of two requests with the same card won
        m, ch, ans = ctl_card_row(c, aid, int(hdr))
        return None, ctl_card_state(m, ch, ans) or {"reason": "used"}
    return int(hdr), {}


CTL_RUN_TIMEOUT = 120  # 2.1045.0 (#5827): seconds the run of an approved step may take (as api/scopes.py approval_replay)
CTL_RUN_ENV = "kalmido.ctl_run"  # 2.1045.0 (#5827, M1): set by ctl_run_replay; v1_agent_approval_run refuses a request carrying it
CTL_RUN_HOLD = CTL_RUN_TIMEOUT + 30  # 2.1045.0 (#5827, M3): seconds a run holds its card (a run that never came back frees it)


def ctl_run_replay(st, mid):
    """2.1045.0 (#5827): sends the stored step st {method, path, body?} through the API as this agent (its own token from this
    request, its address, the header CTL_HEADER = mid) in an own thread (own request context and connection, as
    api/scopes.py approval_replay). The gate (ctl_gate -> ctl_claim) checks the card exactly as for a request from outside, so
    nothing is looser: the body is the card's own. -> (status, body bytes, content type)."""
    import threading
    out = {}
    env = {"REMOTE_ADDR": request.remote_addr or "", CTL_RUN_ENV: str(mid)}  # 2.1045.0 (#5827, M1): a run inside a run -> 409
    if request.environ.get("kalmido.inproc"):  # a server agent's run in this process (v1.py srv_inproc reads it with the token name)
        env["kalmido.inproc"] = request.environ["kalmido.inproc"]
    hdrs = {"Authorization": request.headers.get("Authorization", ""), CTL_HEADER: str(mid),
            **({"If-Match": st["if_match"]} if st.get("if_match") else {})}
    body = st.get("body")
    data = None
    if body not in (None, {}, []):
        data = json.dumps(body, ensure_ascii=False).encode()
        hdrs["Content-Type"] = "application/json"

    def run():
        try:
            r = app.test_client().open(st["path"], method=st["method"], data=data, headers=hdrs, environ_base=env)
            out["status"], out["body"], out["ctype"] = r.status_code, r.get_data(), r.headers.get("Content-Type") or "application/json"
        except Exception as e:  # noqa: BLE001  answered as an error, the card stays unused (ctl_after did not run)
            print("agent approval run:", type(e).__name__, e, flush=True)
            out["status"], out["body"], out["ctype"] = 500, b"", ""
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(CTL_RUN_TIMEOUT)
    return (out["status"], out["body"], out["ctype"]) if out else (504, b"", "")


@app.post("/api/v1/agent/approvals/<int:mid>/run")
@v1_view
def v1_agent_approval_run(mid):
    """2.1045.0 (#5827): runs the step of approval card mid (method, path and body as stored on the card) once, after a person's
    Yes -- the agent never types the request a second time. The answer is the route's own answer (status and body). Refused
    with 409 approval_invalid + reason (ctl_reason_text): not_found, unanswered, rejected, withdrawn, no_step, used (+ used_at:
    the step ran then), one_way, approver_rights, approver_shares, upload (2.1085.0 #5936: an upload's card binds its files); a route's 409 conflict (the target changed since the card:
    expect_updated_at / prev) gets reason stale. Only the token's own agent and its own cards."""
    v1_args(())
    aid = need_agent()
    if request.environ.get(CTL_RUN_ENV):  # 2.1045.0 (#5827, M1): a card's step that runs a card (itself or another) never runs
        return v1_err(409, tr(CTL_REASON_TEXT["nested"]), name="approval_invalid", message_id=mid, reason="nested")
    if request.get_data():
        raise BadInput(tr("The step comes from the card: send no body"))
    c = db()
    m, ch, ans = ctl_card_row(c, aid, mid)
    bad = ctl_card_state(m, ch, ans)
    if bad and bad["reason"] == "not_found":
        raise Denied(404)
    if bad:
        return v1_err(409, tr("This approval does not fit: it needs a person's Yes, exactly this method, path and body, and works once.")
                      + " " + ctl_reason_text(bad), name="approval_invalid", message_id=mid, **bad)
    st = ch["approval"]["step"]
    if isinstance(st.get("body"), dict) and isinstance(st["body"].get(CTL_FILES_KEY), list):  # 2.1085.0 (#5936): an upload's card binds its files,
        return v1_err(409, tr(CTL_REASON_TEXT["upload"]), name="approval_invalid", message_id=mid, reason="upload")  # the run has none
    if not ctl_run_hold(c, aid, mid):  # 2.1045.0 (#5827, M3): two runs at once -- one holds the card, the other is refused
        bad = ctl_card_state(*ctl_card_row(c, aid, mid)) or {"reason": "used"}
        return v1_err(409, tr("This approval does not fit: it needs a person's Yes, exactly this method, path and body, and works once.")
                      + " " + ctl_reason_text(bad), name="approval_invalid", message_id=mid, **bad)
    status, raw, ctype = ctl_run_replay(st, mid)
    if 200 <= status < 300 and status != 202:  # a step the gate let pass without the card (the level allows it now, no level,
        # the agent's own channel) uses the card too: a card runs once, whatever the gate needed. 2.1045.0 (#5827, N2): 202 =
        # the step waits for a person (need_approval), it did not run: the card stays usable (ctl_after frees a claimed one)
        c.execute("""UPDATE agent_chat SET choices=jsonb_set(choices, '{approval,used_at}', to_jsonb(CAST(? AS TEXT)))
                     WHERE id=? AND agent_id=? AND choices->'approval'->>'used_at' IS NULL""", (iso_ms(now_utc()), mid, aid))
    if status != 504:  # a run that did not come back within CTL_RUN_TIMEOUT may still go on: its hold ends after CTL_RUN_HOLD
        c.execute("UPDATE agent_chat SET choices=choices #- '{approval,run_at}' WHERE id=? AND agent_id=?", (mid, aid))
    c.commit()
    if status == 409 and raw:
        try:
            j = json.loads(raw)
        except ValueError:
            j = None
        er = j.get("error") if isinstance(j, dict) else None
        code = er.get("code") if isinstance(er, dict) else None
        if code == "conflict":  # the route's version check: the target changed since the card (the card stays unused, ctl_after)
            fields = sorted(k for k in st["body"] if k in CTL_STATE_FIELDS) if isinstance(st.get("body"), dict) else []
            er = {**er, "reason": "stale", "message_id": mid, "fields": fields,
                  "message": ((er.get("message") or "") + " " + tr("The state field differs from the card ({0}): the target changed since the card, or you read it again. Read it again and ask with a new card.",
                                                                   ", ".join(fields))).strip()}
            resp = jsonify(**{**j, "error": er})  # a Response with its status (v1_view turns a (body, 409) tuple into a plain message)
            resp.status_code = 409
            return resp
    from flask import Response
    return Response(raw, status=status, content_type=ctype or "application/json")


def ctl_run_hold(c, aid, mid):
    """2.1045.0 (#5827, M3): marks card mid as running (approval.run_at = now, epoch seconds) -- atomic, only while it is unused
    and no other run holds it (a hold older than CTL_RUN_HOLD seconds counts as gone). Commits. -> True = this run holds it."""
    import time
    now = time.time()
    n = c.execute("""UPDATE agent_chat SET choices=jsonb_set(choices, '{approval,run_at}', to_jsonb(CAST(? AS DOUBLE PRECISION)))
                     WHERE id=? AND agent_id=? AND choices->'approval'->>'used_at' IS NULL
                     AND COALESCE(CAST(choices->'approval'->>'run_at' AS DOUBLE PRECISION), 0) < ?""",
                  (now, mid, aid, now - CTL_RUN_HOLD)).rowcount
    c.commit()
    return bool(n)


def ctl_unclaim(c, mid):
    c.execute("UPDATE agent_chat SET choices=choices #- '{approval,used_at}' WHERE id=?", (mid,))


def ctl_before(c, path, b):
    """What the history needs to undo the step later (read before the route changes it)."""
    va = request.view_args or {}
    if request.method == "PATCH" and path == "/tasks/{}":
        r = c.execute("SELECT due, due_time, start, title FROM tasks WHERE id=?", (va.get("tid"),)).fetchone()
        return {"tasks": {str(va.get("tid")): {"due": r["due"], "due_time": r["due_time"], "start": r["start"]}}, "title": r["title"]} if r else None
    if path == "/tasks/{}/complete":
        r = c.execute("SELECT title, status FROM tasks WHERE id=?", (va.get("tid"),)).fetchone()
        return {"ids": [va.get("tid")], "title": r["title"]} if r and r["status"] == 0 else None
    if path == "/tasks/batch" and b.get("action") in ("complete", "update") and isinstance(b.get("ids"), list):
        ids = [x for x in b["ids"] if isinstance(x, int) and not isinstance(x, bool)][:500]
        if not ids:
            return None
        rows = c.execute(f"SELECT id, due, due_time, start, status FROM tasks WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        if b["action"] == "complete":
            return {"ids": [r["id"] for r in rows if r["status"] == 0]}
        return {"tasks": {str(r["id"]): {"due": r["due"], "due_time": r["due_time"], "start": r["start"]} for r in rows}}
    return None


def ctl_info(path, b):
    """2.653.0 (#5079): what a task change touched, for a history line in words: {fields: [the body's keys], count?: tasks of a
    batch} -- only the names of the fields, never their values. {} for any other route."""
    skip = CTL_PLAN_EXTRA | {"If-Match"}
    if request.method == "POST" and path in ("/tasks/{}/notes/append", "/tasks/{}/notes/replace-section"):
        return {"fields": ["notes"]}  # 2.1111.0 (#5830, review F6): a targeted change of the notes
    if request.method == "PATCH" and path == "/tasks/{}":
        return {"fields": sorted(k for k in b if isinstance(k, str) and k not in skip)[:CTL_FIELDS_MAX]}
    if path == "/tasks/batch":
        ch, ids = b.get("changes"), b.get("ids")
        fields = sorted(k for k in ch if isinstance(k, str))[:CTL_FIELDS_MAX] if isinstance(ch, dict) else []
        return {"fields": fields, "action": str(b.get("action") or "")[:40], "count": len(ids) if isinstance(ids, list) else 0}
    return {}


def ctl_kind(note, method, resp_j):
    """The kind of a history line and what it needs for Undo -> (kind, target id, title, undo data).
    2.653.0 (#5079): a change of a task that is no plan of its dates is task_changed (its title + the changed fields in info),
    no longer "other" -- the history reads in words, never as method + path."""
    p, bf = note["path"], note["before"] or {}
    j = resp_j if isinstance(resp_j, dict) else {}
    info = note.get("info") or {}
    if method == "POST" and p in ("/tasks", "/tasks/{}/subtasks") and isinstance(j.get("id"), int):
        return "task_created", j["id"], j.get("title") or "", None
    if method == "POST" and p == "/tasks/{}/comments" and isinstance(j.get("id"), int):
        return "comment", j["id"], re.sub(r"\s+", " ", str(j.get("body") or ""))[:120], {"task_id": (request.view_args or {}).get("tid")}
    if p in ("/tasks/{}/complete", "/tasks/batch") and bf.get("ids"):
        return "task_completed", bf["ids"][0], bf.get("title") or "", {"ids": bf["ids"]}
    plan = p == "/tasks/batch" or set(info.get("fields") or ()) & CTL_PLAN_KEYS  # 2.653.0 (#5079): unlocking only = a change
    if p in ("/tasks/{}", "/tasks/batch") and bf.get("tasks") and note["step"] == "routine" and plan:
        return "task_planned", int(next(iter(bf["tasks"]))), bf.get("title") or "", {"tasks": bf["tasks"]}
    if (method == "PATCH" and p == "/tasks/{}") or (method == "POST" and p in ("/tasks/{}/notes/append", "/tasks/{}/notes/replace-section")):
        tid = (request.view_args or {}).get("tid")  # 2.1111.0 (#5830, review F6): + the targeted changes of the notes
        return "task_changed", tid if isinstance(tid, int) else None, str(j.get("title") or bf.get("title") or ""), None
    if p == "/tasks/batch":
        ids = [x for x in ((bf.get("ids") or list((bf.get("tasks") or {}).keys())) or []) if str(x).isdigit()]
        return "task_changed", int(ids[0]) if ids else None, "", None
    return "other", None, "", None


@app.after_request
def ctl_after(resp):
    """Writes the history line of a step the gate let through; an approval of a failed request can be used again."""
    note = g.pop("ctl_note", None)
    if not note:
        return resp
    c = db()
    try:
        if resp.status_code >= 400 or resp.status_code == 202:  # 202 = it waits for a person (api/scopes.py need_approval)
            if note["mid"]:  # 2.1045.0 (#5827, N2): also a 202 -- the step waits for a person, it did not run
                ctl_unclaim(c, note["mid"])
                c.commit()
            return resp
        try:
            rj = resp.get_json(silent=True)
        except Exception:  # noqa: BLE001  a file / stream answer
            rj = None
        kind, target, title, undo = ctl_kind(note, request.method, rj)
        if kind == "task_planned":  # 2.235.0 A2 (#2891): the state after the step -- Undo only while it still holds
            ids = [int(x) for x in undo["tasks"]]
            undo["after"] = {str(r["id"]): {"due": r["due"], "due_time": r["due_time"], "start": r["start"]} for r in c.execute(
                f"SELECT id, due, due_time, start FROM tasks WHERE id IN ({','.join('?' * len(ids))})", ids)}
        ts = iso(now_utc())
        info = (note.get("info") or {}) if kind == "task_changed" else {}
        insert_id(c, """INSERT INTO agent_decisions(agent_id,list_id,step,level,kind,method,path,target_id,title,undo,via,message_id,created_at,info)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (note["aid"], note["lid"], note["step"], note["level"], kind, request.method, request.path[:300], target, title[:200],
                   json.dumps(undo) if undo else None, "approval" if note["mid"] else "self", note["mid"], ts,
                   json.dumps(info) if info else ""))
        ctl_prune(c, note["aid"])
        c.commit()
    except Exception as e:  # noqa: BLE001  the history never breaks the agent's answer
        c.rollback()
        print("agent control history:", type(e).__name__, e, flush=True)
    return resp


def ctl_prune(c, aid):
    c.execute("""DELETE FROM agent_decisions WHERE agent_id=? AND id<=(SELECT id FROM agent_decisions WHERE agent_id=?
                 ORDER BY id DESC LIMIT 1 OFFSET ?)""", (aid, aid, CTL_KEEP))


def ctl_log(c, aid, kind, title, lid=None, message_id=None, via="deadline", step="", level="", info=None):
    """A history line without a request (the deadline of an approval; 2.653.0 #5079: a decision the agent wrote itself)."""
    did = insert_id(c, """INSERT INTO agent_decisions(agent_id,list_id,step,level,kind,method,path,target_id,title,undo,via,message_id,created_at,info)
                    VALUES(?,?,?,?,?,'','',NULL,?,NULL,?,?,?,?)""",
                    (aid, lid, step, level, kind, title[:200], via, message_id, iso(now_utc()), json.dumps(info) if info else ""))
    ctl_prune(c, aid)
    return did


# ---------------------------------------------------------------- 2.653.0 (#5079): a decision the agent writes itself
def ctl_decision_text(v, name, need):
    """One line of text for a decision: whitespace folded, secrets out (agents/steps.py redact), cut to CTL_DECISION_MAX."""
    if v is None and not need:
        return ""
    if not isinstance(v, str) or len(v) > 4000:
        raise BadInput(tr("Invalid value: {0}", name))
    t = re.sub(r"\s+", " ", redact(v)[0]).strip()
    if need and not t:
        raise BadInput(tr("Invalid value: {0}", name))
    return t[:CTL_DECISION_MAX - 1].rstrip() + "…" if len(t) > CTL_DECISION_MAX else t


@app.post("/api/v1/agent/decisions")
@v1_view
def v1_agent_decision():
    """{title, ref?} -- a line in the agent's OWN history (Settings > Agents > Work style > History) for a decision that ran
    outside the Kalmido API: a job card it answered itself, a change of a tool on its server, something it deliberately did not
    start. kind decision, shown as "Decided: <title>"; no Undo (nothing in Kalmido to take back). Only ever the token's own agent
    (no agent id in the path). title max 200 characters (longer is cut), empty = 400; ref (a task, a commit subject) max 200.
    CTL_DECISION_RATE per minute (429). 201 {id, kind, title, ref, created_at}."""
    v1_args(())
    aid = need_agent()
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("title", "ref"))
    if unknown:
        raise UnknownFields(unknown)
    title = ctl_decision_text(b.get("title"), "title", True)
    ref = ctl_decision_text(b.get("ref"), "ref", False)
    if hit_limit(f"ctl-decisions:{aid}", CTL_DECISION_RATE):
        return v1_err(429, tr("Too many requests, please slow down"), {"Retry-After": "5"})
    c = db()
    did = ctl_log(c, aid, "decision", title, via="self", info={"ref": ref} if ref else None)
    c.commit()
    r = c.execute("SELECT created_at FROM agent_decisions WHERE id=?", (did,)).fetchone()
    return jsonify(id=did, kind="decision", title=title, ref=ref, created_at=r["created_at"] if r else None), 201


# ---------------------------------------------------------------- the approval card (agents/chat.py chat_approval_clean)
def ctl_card_extra(v):
    """step {method, path, body?} / recommend yes | no / one_way of an approval card -> the keys stored with it (BadInput).
    2.235.0 A2 (#2891): step.body = the exact body of the request (as in the 409's approval.body); the server marks a card
    whose step is a one-way step one_way itself (the person sees it on the card)."""
    out = {}
    st = v.get("step")
    if st not in (None, ""):
        bad = BadInput(tr("Invalid value: {0}", "approval.step"))
        if not isinstance(st, dict) or set(st) - {"method", "path", "body", "if_match"} or st.get("method") not in CTL_WRITE or \
                not isinstance(st.get("path"), str) or not re.fullmatch(r"/[^\s?#]{1,300}", st["path"]):
            raise bad
        if st.get("if_match") not in (None, "") and (not isinstance(st["if_match"], str) or not re.fullmatch(r"[^\x00-\x1f\x7f]{1,200}", st["if_match"])):
            raise bad  # 2.1045.0 (#5827): the If-Match of the refused request (a version), sent along by .../run
        p = ctl_norm_path(st["path"])
        if not p.startswith("/") or re.search(r"[\s?#%]", p):  # 2.1078.0 (#5866, N7): + "%": the run decodes the path once more
            raise bad  # (%2541 -> %41 stored -> A on the run): a card that looked other than its target
        out["step"] = {"method": st["method"], "path": p if p.startswith(API_PREFIX) else API_PREFIX.rstrip("/") + p}
        if st.get("body") not in (None, {}, []):
            if not isinstance(st["body"], (dict, list)) or len(ctl_canon(st["body"])) > CTL_BODY_MAX:
                raise bad
            out["step"]["body"] = st["body"]
        if st.get("if_match"):
            out["step"]["if_match"] = st["if_match"]
        ctl_card_route(out["step"])  # 2.1045.0 (#5827): a step no route answers is refused here, never stored as a one-way card
        if ctl_card_one_way(out):
            out["one_way"] = True
    if v.get("recommend") not in (None, ""):
        if v["recommend"] not in ("yes", "no"):
            raise BadInput(tr("Invalid value: {0}", "approval.recommend"))
        out["recommend"] = v["recommend"]
    if v.get("one_way") not in (None, False):
        if v["one_way"] is not True:
            raise BadInput(tr("Invalid value: {0}", "approval.one_way"))
        out["one_way"] = True
    return out


def ctl_card_route(st):
    """2.1045.0 (#5827): the step {method, path} of a new approval card must be a route of the API (else 400 naming the methods
    the path has, e.g. "allowed: PATCH"): a card with a guessed method (PUT on a wiki page that is PATCH) could never be used
    and fell into the one-way branch of ctl_card_one_way."""
    adapter = app.url_map.bind("localhost")
    try:
        ep, _ = adapter.match(st["path"], method=st["method"])
    except Exception:  # noqa: BLE001  checked below: another method, or no such path
        ep = None
    if ep is not None:
        if app.view_functions.get(ep) is v1_agent_approval_run:  # 2.1045.0 (#5827, M1): a card that runs a card (a loop)
            raise BadInput(tr(CTL_REASON_TEXT["nested"]))
        return
    try:
        allowed = sorted(m for m in adapter.allowed_methods(st["path"]) if m in CTL_WRITE)
    except Exception:  # noqa: BLE001
        allowed = []
    if allowed:
        raise BadInput(tr("This route does not exist: {0} {1} - allowed there: {2}. Take the step from the 409 approval_required answer.",
                          st["method"], st["path"], ", ".join(allowed)))
    raise BadInput(tr("This route does not exist: {0} {1}. Take the step from the 409 approval_required answer.", st["method"], st["path"]))


def ctl_card_one_way(ap):
    """Is the step of approval card ap a one-way step (marked by the agent, or a route of class one_way with its body)?"""
    if ap.get("one_way"):
        return True
    st = ap.get("step") or {}
    if not st:
        return False
    try:
        adapter = app.url_map.bind("localhost")
        rule, _ = adapter.match(st["path"], method=st["method"], return_rule=True)
    except Exception:  # noqa: BLE001  no such route: careful
        return True
    return ctl_class(st["method"], ctl_rule_path(rule), st.get("body") if isinstance(st.get("body"), dict) else {}) == "one_way"


# ---------------------------------------------------------------- #2901: the deadline of the approvals (watchdog)
def ctl_deadline_tick(c, users, S, LG):
    """Ends the approval cards of agents with a deadline that were not answered in time (see the module text)."""
    now = now_utc()
    for ag in c.execute("SELECT user_id FROM agents WHERE control<>''").fetchall():
        a = agent_row(c, ag["user_id"])
        d = ctl_get(a)
        secs = CTL_DEADLINES.get(d["deadline"]) if d else None
        if not secs:
            continue
        set_at = (ctl_load(a) or {}).get("deadline_set_at")
        set_at = parse_iso(set_at) if isinstance(set_at, str) and set_at else None
        for r in c.execute("""SELECT * FROM agent_chat WHERE agent_id=? AND sender='agent' AND choice IS NULL
                              AND choices->'approval' IS NOT NULL AND choices->>'withdrawn_at' IS NULL ORDER BY id""",
                           (a["user_id"],)).fetchall():
            ch = _jload(r["choices"])
            if not ch or choice_state(r, ch, None) != "open":
                continue
            since = parse_iso(ch.get("deadline_asked_at") or r["created_at"])
            if since is not None and set_at is not None and set_at > since:
                since = set_at  # 2.235.0 A2 (#2901): from max(card, setting)
            if since is None or since + timedelta(seconds=secs) > now:
                continue
            ap = ch["approval"]
            then = d["then"]
            if then == "ask_again" and ch.get("deadline_asked_at"):
                then = "reject"  # asked once more already
            outcome = "rejected"
            if then == "ask_again":
                ch = {**ch, "deadline_asked_at": iso_ms(now)}
                c.execute("UPDATE agent_chat SET choices=? WHERE id=?", (json.dumps(ch, ensure_ascii=False), r["id"]))
                outcome = "asked_again"
                uid = r["user_id"]
                if uid in users:
                    lg = LG.get(uid, "en")
                    notify(uid, a["display_name"] or a["username"], tr("Still waiting for your approval: {0}", ap.get("title", ""), lg=lg),
                           push_prio(S[uid]), f"{PUBLIC_URL}/#agents/{a['user_id']}", s=S[uid], kind="other")
            elif then == "recommend" and ap.get("recommend") in ("yes", "no") and not ctl_card_one_way(ap):
                ans = {"ids": [ap["recommend"]], "at": iso_ms(now), "user_id": None, "via": "deadline"}  # A2: ctl_claim checks the card's person
                c.execute("UPDATE agent_chat SET choice=? WHERE id=?", (json.dumps(ans), r["id"]))
                outcome = "approved" if ap["recommend"] == "yes" else "rejected"
            else:
                chat_choices_withdraw(c, r, "expired")
            ctl_log(c, a["user_id"], "deadline_" + outcome, ap.get("title", ""), message_id=r["id"])
            agent_emit(c, a["user_id"], "approval_expired", {
                "message_id": r["id"], "user_id": r["user_id"], "outcome": outcome, "then": d["then"],
                "approval_request": {"title": ap.get("title", ""), "what": ap.get("what", ""), "step": ap.get("step")}})
            c.commit()
            print("agent", a["user_id"], "approval", r["id"], "deadline:", outcome, flush=True)


WD_TICKS.append(("agent approval deadlines", ctl_deadline_tick))


# ---------------------------------------------------------------- the routes of the settings (Settings > Agents > the gear)
def ctl_area(path):
    """2.653.0 (#5079): the area of a line's route ("tasks", "lists", "events" ...: its first part after the API prefix), for a
    line in words ("Entry changed · Calendar") instead of method + path."""
    p = path[len(API_PREFIX) - 1:] if path.startswith(API_PREFIX) else path
    m = re.match(r"/([a-z][a-z0-9_-]{0,40})", p or "")
    return m.group(1) if m else ""


def ctl_decision_dict(c, r, names):
    try:
        info = json.loads(r["info"]) if r.get("info") else {}
    except (ValueError, TypeError):
        info = {}
    info = info if isinstance(info, dict) else {}
    kind, area = r["kind"], ctl_area(r["path"] or "")
    if kind == "other" and r["method"] == "PATCH" and re.fullmatch(r"/tasks/\d+", (r["path"] or "")[len(API_PREFIX) - 1:]):
        kind = "task_changed"  # 2.653.0 (#5079): a line from before 2.653 reads in words too (its title was never stored)
    return {"id": r["id"], "kind": kind, "step": r["step"], "level": r["level"], "title": r["title"], "via": r["via"],
            "method": r["method"], "path": r["path"], "list_id": r["list_id"], "list_name": names.get(r["list_id"]),
            "area": area, "fields": [x for x in info.get("fields") or [] if isinstance(x, str)][:CTL_FIELDS_MAX],
            "count": info.get("count") if isinstance(info.get("count"), int) else None, "ref": str(info.get("ref") or ""),
            "created_at": r["created_at"], "undone_at": r["undone_at"],
            "can_undo": bool(r["undo"] or r["kind"] == "task_created") and not r["undone_at"] and r["kind"] not in ("other", "decision")}


def ctl_names(c, a):
    """The projects of agent a the person sees -> [{id, name, max_level}] (the offer of the settings, the names of the history)."""
    aid = a["user_id"]
    rows = c.execute(f"""SELECT l.id, l.name FROM lists l WHERE {otr_live('l')} AND l.id IN {joined_lists_sql()}
                        ORDER BY l.name, l.id""", (aid, aid)).fetchall()
    return [{"id": r["id"], "name": r["name"], "max_level": ctl_cap(c, a, r["id"])} for r in rows if list_role(c, r["id"], me())]


def ctl_state(c, a):
    d = ctl_get(a)
    aid = a["user_id"]
    offer = ctl_names(c, a)  # only projects the person sees
    names = {x["id"]: x["name"] for x in offer}
    hist = c.execute("SELECT * FROM agent_decisions WHERE agent_id=? ORDER BY id DESC LIMIT ?", (aid, CTL_SHOW)).fetchall()
    return {"control": d, "chosen": d is not None, "defaults": CTL_DEFAULTS,
            "one_way_fixed": [{"id": k, "text": tr(CTL_ONE_WAY_TEXT[k])} for k in CTL_ONE_WAY_FIXED],
            "projects": offer, "history": [ctl_decision_dict(c, r, names) for r in hist]}


@app.get("/api/agents/<int:aid>/control")
def ctl_route_get(aid):
    c = db()
    a = ws_need_editor(c, aid)
    return jsonify(ctl_state(c, a))


@app.get("/api/agents/<int:aid>/control/history")
def ctl_route_history(aid):
    """2.653.0 (#5079): the whole history, page by page (the view "Whole history"): ?before=<line id> (older than it), ?limit=
    (1..200, default 100) -> {history: [newest first], more: bool}. Owner / instance admin like the settings, else 404."""
    c = db()
    a = ws_need_editor(c, aid)
    try:
        before = int(request.args.get("before") or 0)
        limit = int(request.args.get("limit") or 100)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "before / limit")) from None
    if before < 0 or not 1 <= limit <= CTL_PAGE_MAX:
        raise BadInput(tr("Invalid value: {0}", "before / limit"))
    names = {x["id"]: x["name"] for x in ctl_names(c, a)}
    rows = c.execute(f"SELECT * FROM agent_decisions WHERE agent_id=? {'AND id<?' if before else ''} ORDER BY id DESC LIMIT ?",
                     (aid, before, limit + 1) if before else (aid, limit + 1)).fetchall()
    return jsonify(history=[ctl_decision_dict(c, r, names) for r in rows[:limit]], more=len(rows) > limit)


@app.patch("/api/agents/<int:aid>/control")
def ctl_route_patch(aid):
    """{level?, goal?, projects? {list id: level | null}, one_way? [texts], deadline?, then?} -- autosave per field."""
    c = db()
    a = ws_need_editor(c, aid)
    b = body()
    if isinstance(b.get("projects"), dict):
        for lid, lv in b["projects"].items():  # 2.235.0 A2 (#2891): removing (null) also for a project the person no longer sees
            if not str(lid).isdigit() or (lv is not None and not list_role(c, int(lid), me())):
                raise BadInput(tr("Invalid value: {0}", "projects"))
    ctl_set(c, a, b)
    bump(c)
    c.commit()
    return jsonify(ctl_state(c, agent_row(c, aid)))


@app.post("/api/agents/<int:aid>/control/history/<int:did>/undo")
def ctl_route_undo(aid, did):
    """Takes one decision of the agent back (where the server can); the agent gets the event decision_undone."""
    c = db()
    a = ws_need_editor(c, aid)
    r = c.execute("SELECT * FROM agent_decisions WHERE id=? AND agent_id=?", (did, aid)).fetchone()
    if not r:
        raise Denied(404)
    if r["undone_at"]:
        return err(tr("This was undone already"), 409)
    undo = json.loads(r["undo"]) if r["undo"] else {}
    msg = ctl_undo(c, r, undo)
    if msg:
        c.rollback()
        return err(msg, 409)
    c.execute("UPDATE agent_decisions SET undone_at=?, undone_by=? WHERE id=?", (iso(now_utc()), me(), did))
    agent_emit(c, aid, "decision_undone", {"decision": {"id": did, "kind": r["kind"], "title": r["title"], "method": r["method"],
                                                        "path": r["path"], "target_id": r["target_id"]},
                                          "user": {"id": me(), "name": g.user["display_name"] or g.user["username"]}})
    bump(c)
    c.commit()
    print("agent", aid, "decision", did, r["kind"], "undone by", g.user["username"], flush=True)
    return jsonify(ctl_state(c, agent_row(c, aid)))


def ctl_undo(c, r, undo):
    """Does the undo of history line r; -> an error text or None."""
    no = tr("You cannot change this task")
    if r["kind"] == "task_created":
        t = c.execute("SELECT list_id, deleted_at FROM tasks WHERE id=?", (r["target_id"],)).fetchone()
        if not t or t["deleted_at"]:
            return tr("The task is gone already")
        if list_role(c, t["list_id"], me()) not in WRITE_ROLES:
            return no
        trash_task(c, r["target_id"])
        return None
    if r["kind"] == "comment":
        k = c.execute("SELECT id, user_id, ref_id FROM obj_comments WHERE id=? AND kind='task' AND deleted_at IS NULL", (r["target_id"],)).fetchone()
        if not k:
            return tr("The comment is gone already")
        if k["user_id"] != r["agent_id"] or not task_visible(c, k["ref_id"], me()):
            return no
        ocm_trash(c, k["id"], me(), check=False)  # checked above: the agent's own comment on a task the person sees
        news_forget_comment(c, k["id"])
        c.commit()
        return None
    changed = tr("Changed meanwhile by someone else – undo it by hand")
    try:
        if r["kind"] == "task_completed":  # 2.235.0 A2 (#2891): all visible first; only what the agent itself ticked off
            ids = [int(x) for x in undo.get("ids") or []]
            if not all(task_visible(c, tid, me(), write=True) for tid in ids):
                return no
            rows = {x["id"]: x for x in c.execute(f"SELECT id, status, completed_by FROM tasks WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
            todo = [tid for tid in ids if tid in rows and rows[tid]["status"] != 0]
            if any(rows[tid]["completed_by"] != r["agent_id"] for tid in todo):
                return changed
            for tid in todo:
                v1_call(task_reopen, tid, body={})
            return None
        if r["kind"] == "task_planned":  # 2.235.0 A2 (#2891): only while the dates are still the agent's
            tasks, after = undo.get("tasks") or {}, undo.get("after")
            if not isinstance(after, dict):
                return tr("This cannot be undone automatically")
            if not all(task_visible(c, int(tid), me(), write=True) for tid in tasks):
                return no
            plan = {}
            for tid, old in tasks.items():
                now_r = c.execute("SELECT due, due_time, start FROM tasks WHERE id=?", (int(tid),)).fetchone()
                aft = after.get(tid) or {}
                if not now_r or any(now_r[k] != aft.get(k) for k in ("due", "due_time", "start")):
                    return changed
                plan[int(tid)] = {k: old.get(k) for k in ("due", "due_time", "start") if now_r[k] != old.get(k)}
            for tid, diff in plan.items():
                if diff:  # unchanged since the agent's own step: taking it back passes the app's task lock (#1118)
                    e = apply_update(c, tid, diff)
                    if e:
                        return tr("This cannot be undone any more") + f" ({e})"
            return None
    except V1Error as e:
        try:
            j = e.resp.get_json(silent=True) or {}
            why = j.get("error") if isinstance(j.get("error"), str) else (j.get("error") or {}).get("message")
        except Exception:  # noqa: BLE001
            why = None
        return tr("This cannot be undone any more") + (f" ({why})" if why else "")
    return tr("This cannot be undone automatically")
