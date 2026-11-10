"""2.754.0 (#5268, stage Q0b of the cross-section audit #3563): the light kinds of the shared core -- task, event, hub_mail,
client. Every (kind, id) table of the core that comes next (links, tags, comments, seen, follow: obj_links, obj_tags ...)
names its objects by kind and id and asks obj_role / obj_need (core/objects.py) for the role; these four old areas had no
kind yet (the reference kinds of the file store cover the office, sheets, wiki, calendars, contacts, projects ...).

A light kind (obj_register node=False) has no reference node, no shares, no folder, no routes and no write path of the
core: nothing of the areas moves, no old way is taken down, nothing is stored twice. The kind only knows
- base_role: EXACTLY the area's own check, called with the account asked about (never more than the area's routes give):
    task      the task's project role (core/access.py need_task): owner / project admin 'manage', editor 'edit', viewer
              'view'; a participant 'edit' on the tasks they may change (pvis writable and the organisation lets them
              write), 'view' on the other tasks they see -- a parent task that is only context of an assigned subtask
              (need_task full=True refuses it) gives nothing; a task an agent's data lock covers gives nothing
    event     the event's role (events/model.py ev_role_of): the calendar's owner 'manage', a calendar role edit / view,
              an invited person 'view'; the agent's data lock (the calendar area, the event's task) gives nothing
    hub_mail  the filed e-mail (hub/hubmail.py): in the app (a person) hbm_can -- read 'view', write (assign, delete,
              restore) 'edit'; an agent or a request with the account's own API token reads like API v1 (hub/hmv1.py
              hmv_can: only mails filed with a client or a project, never "Not assigned", the agent's lock "Private
              e-mails") and gets 'view' at most; kid accounts nothing
    client    team/clients.py need_client: who sees the client 'view', 'edit' when the organisation lets them write (not
              read-only), 'manage' for who may delete it as well (cl_may_delete: its creator, an admin of its
              organisation, the server admin without workspaces); agents and kid accounts nothing (they reach clients
              only through the projects they share, client_public)
- steps 1 + 2 of obj_role stay on top (the organisation floor, an agent of another workspace never, the list limit of an API
  token: a kind without a list_id column gives such a token nothing) -- they only ever take a role away
- space: the workspace of the object (a task / event: its project's / calendar's; a client: its organisation and creator)
- title: what a link may show (live from the object, never stored): a task of a locked project (end-to-end) has none
- open_url: the app route (t/<id>, ev/<id>, mailhub/<id>, client/<id>)
An object in its area's trash: only 'manage' (step 4 of obj_role) -- the base roles above do not look at deleted_at.

Interface: nothing of its own -- obj_role / obj_need / obj_title / obj_space / OBJ[kind]["open_url"] of core/objects.py with
the kinds LT_TASK, LT_EVENT, LT_MAIL, LT_CLIENT.
Test containers only (KALMIDO_TEST=1): GET /api/test/objrole/<kind>/<id>[?as=<account>] -> {role, title, open, space} of the
signed-in account (a person's session or a token) or of another one, so the suites compare the core's answer with the areas' own routes."""
import os

from flask import g, jsonify, request

from .access import _org_list_writes, acx_of, acx_org_ok, list_role, pvis
from .config import app
from .db import db
from .dlock import dl_of, dl_task_hidden
from .i18n import N_
from .objects import OBJ, obj_register, obj_role, obj_space, obj_title
from .objhooks import NOTIFY_TICK
from .pg import system_ctx
from ..files.fsref import _api_way as fsr_api_way
from ..accounts.orgroles import org_writes
from ..events.model import ev_role_of
from ..hub.hmv1 import hmv_can
from ..hub.hubmail import _open as hbm_open, hbm_can
from ..team.clients import cl_may_delete, client_rows

LT_TASK, LT_EVENT, LT_MAIL, LT_CLIENT = "task", "event", "hub_mail", "client"
_LIST_ROLE = {"owner": "manage", "admin": "manage", "edit": "edit", "view": "view"}  # = lists/lmcore.py _ROLE
_EV_ROLE = {"owner": "manage", "edit": "edit", "view": "view", "attendee": "view"}


def _one(c, sql, rid):
    try:
        return c.execute(sql, (int(rid),)).fetchone()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- task
def _task_base(c, uid, tid):
    """need_task for uid (module docstring)."""
    r = _one(c, "SELECT id, list_id FROM tasks WHERE id=?", tid)
    if r is None or dl_task_hidden(c, r["id"], uid):
        return None
    lid = r["list_id"]
    role = list_role(c, lid, uid)
    if role == "participant":
        vis, wr, ctx = pvis(c, uid, lid)
        if r["id"] not in vis or r["id"] in ctx:
            return None
        return "edit" if r["id"] in wr and _org_list_writes(c, lid, uid) else "view"
    return _LIST_ROLE.get(role)


def _task_space(c, tid):
    r = _one(c, "SELECT l.org_id, l.owner_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", tid)
    return (r[0] or None, r[1]) if r else None


def _task_title(c, tid):
    r = _one(c, "SELECT t.title, COALESCE(l.e2e, '') AS e2e FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", tid)
    return "" if r is None or r["e2e"] else (r["title"] or "")


def _task_tick(c, uid, tid, memo):
    """2.891.0 (#5270): obj_role(c, uid, 'task', tid) >= 'view' for a PERSON in a run without a request (the watchdog's task
    reminders and nags, core/objnotify.py obj_readers): the steps of obj_role for this kind -- the organisation floor of the
    project's workspace (_gate: no token, no API way, no agent branch outside a request for a person), the project role and a
    participant's own tasks (_task_base), an agent's data lock, the trash only for 'manage' -- with what depends on the project
    and the person kept in the tick's memo under the keys notify/push.py _wd_sees / _wd_prefetch fill already
    (("role", list, uid), ("dl", uid), ("pvis", list, uid)), so a wave of reminders reads each project and person once."""
    tk = ("task_row", int(tid))
    if tk not in memo:
        memo[tk] = _one(c, "SELECT t.id, t.list_id, t.deleted_at, l.org_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", tid)
    r = memo[tk]
    if r is None:
        return False
    ak = ("acx_agent", uid)  # 2.891.0 (#5270, review): an agent never, whatever obj_readers filtered before (the rule stands alone)
    if ak not in memo:
        memo[ak] = acx_of(c, uid).role == "agent"
    if memo[ak]:
        return False
    lid = r["list_id"]
    ok = ("org_ok", r["org_id"], uid)
    if ok not in memo:
        memo[ok] = acx_org_ok(c, uid, r["org_id"])
    if not memo[ok]:
        return False
    k = ("role", lid, uid)
    if k not in memo:
        memo[k] = list_role(c, lid, uid)
    role = memo[k]
    if not role:
        return False
    dk = ("dl", uid)
    if dk not in memo:
        memo[dk] = bool(dl_of(c, uid))
    if memo[dk] and dl_task_hidden(c, r["id"], uid):
        return False
    if role == "participant":
        pk = ("pvis", lid, uid)
        if pk not in memo:
            memo[pk] = pvis(c, uid, lid)
        vis, _wr, ctx = memo[pk]
        if r["id"] not in vis or r["id"] in ctx:
            return False
        base = "view"  # 'edit' or 'view': both read; only 'manage' passes the trash
    else:
        base = _LIST_ROLE.get(role)
    if not base:
        return False
    return not r["deleted_at"] or base == "manage"


# ---------------------------------------------------------------- event
def _ev_base(c, uid, eid):
    r = _one(c, "SELECT * FROM events WHERE id=?", eid)
    return _EV_ROLE.get(ev_role_of(c, uid, r)) if r is not None else None


def _ev_space(c, eid):
    r = _one(c, "SELECT k.org_id, k.owner_id FROM events e JOIN ev_cals k ON k.id=e.cal_id WHERE e.id=?", eid)
    return (r[0] or None, r[1]) if r else None


def _ev_title(c, eid):
    r = _one(c, "SELECT title FROM events WHERE id=?", eid)
    return (r[0] or "") if r else ""


# ---------------------------------------------------------------- hub_mail
def _kid(c, uid):
    u = _one(c, "SELECT kid FROM users WHERE id=?", uid)
    return u is None or bool(u["kid"])


def _mail_base(c, uid, mid):
    m = _one(c, "SELECT * FROM hub_mails WHERE id=?", mid)
    if m is None or _kid(c, uid):
        return None
    if fsr_api_way(c, uid):  # an agent / the account's own token: the API's rule (hub/hmv1.py), read only
        return "view" if hmv_can(c, uid, m) else None
    if not hbm_can(c, uid, m):
        return None
    return "edit" if hbm_can(c, uid, m, write=True) else "view"


def _mail_space(c, mid):
    m = _one(c, "SELECT org_id, owner_id FROM hub_mails WHERE id=?", mid)
    return (m[0] or None, m[1]) if m else None


def _mail_title(c, mid):
    m = _one(c, "SELECT * FROM hub_mails WHERE id=?", mid)
    return (hbm_open(c, m).get("subject") or "") if m is not None else ""


# ---------------------------------------------------------------- client
def _client_base(c, uid, cid):
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return None
    r = next(iter(client_rows(c, uid, only=cid)), None)  # need_client's own read (kids, agents: none)
    if r is None:
        return None
    if r["org_id"] and not org_writes(c, uid, r["org_id"]):
        return "view"  # need_client: read-only / guest / accounting change nothing
    return "manage" if cl_may_delete(c, uid, r) else "edit"


def _client_space(c, cid):
    r = _one(c, "SELECT org_id, created_by FROM clients WHERE id=?", cid)
    return (r[0] or None, r[1]) if r else None


def _client_title(c, cid):
    r = _one(c, "SELECT name FROM clients WHERE id=?", cid)
    return (r[0] or "") if r else ""


obj_register(LT_TASK, "tasks", label=N_("Task"), fields={}, node=False, area="tasks", base_role=_task_base, space=_task_space,
             title=_task_title, open_url=lambda tid: f"t/{int(tid)}")
NOTIFY_TICK[LT_TASK] = _task_tick  # 2.891.0 (#5270): the watchdog's reminders ask the task's readers with the tick's memo
obj_register(LT_EVENT, "events", label=N_("Event"), fields={}, node=False, area="calendar", base_role=_ev_base, space=_ev_space,
             title=_ev_title, open_url=lambda eid: f"ev/{int(eid)}")
obj_register(LT_MAIL, "hub_mails", label=N_("E-mail"), fields={}, node=False, area="other", base_role=_mail_base, space=_mail_space,
             title=_mail_title, open_url=lambda mid: f"mailhub/{int(mid)}")
obj_register(LT_CLIENT, "clients", label=N_("Client"), fields={}, node=False, area="other", base_role=_client_base,
             space=_client_space, title=_client_title, open_url=lambda cid: f"client/{int(cid)}")


if os.environ.get("KALMIDO_TEST") == "1":  # test containers only (tests/p2754_d_kinds_api_test.py)
    @app.get("/api/test/objrole/<kind>/<int:rid>")
    def _lt_test_role(kind, rid):
        """{role, title, open, space} of the signed-in account (?as=<account id>: of that account, asked outside its own
        request, as the core's notification will ask for every recipient) on object (kind, rid) of a light kind -- obj_role
        as the next core tables will ask it (title / open only with a role)."""
        reg = OBJ.get(kind)
        if reg is None or reg.get("node", True):
            return jsonify(error="no light kind"), 404
        c = db()
        other = request.args.get("as")
        if other:  # like a background run (the system context: every row readable, the role functions decide)
            with system_ctx(c):
                return _lt_answer(c, int(other), reg, kind, rid)
        return _lt_answer(c, g.user["id"], reg, kind, rid)

    def _lt_answer(c, uid, reg, kind, rid):
        role = obj_role(c, uid, kind, rid)
        sp = obj_space(c, kind, rid) if role else None
        return jsonify(role=role, title=obj_title(c, kind, rid) if role else None, open=reg["open_url"](rid) if role else None,
                       space=list(sp) if sp else None)
