"""Access control: who sees / changes which list and task, module switches, list roles."""

import time
from typing import NamedTuple, Optional

from flask import g, has_request_context

from ..core.config import app
from ..core.schema import MAX_DEPTH
from ..core.i18n import N_, tr
from ..core.db import db, ensure_inbox, err, usettings
from ..accounts.session import me


# ---------------------------------------------------------------- access control
# A list is visible to its owner and its members; role 'view' is read-only. Objects the user cannot
# see answer 404 (their existence is not revealed), writes with a view-only role 403.

class Denied(Exception):
    def __init__(self, code=404, msg=None):
        super().__init__(code)
        self.code, self.msg = code, msg

    def text(self):
        return self.msg or (tr("No permission (view only)") if self.code == 403 else tr("unknown"))


@app.errorhandler(Denied)
def denied(e):
    return err(e.text(), e.code)


# Collaboration for everyone (admin switch, settings.collab_all). Off: list memberships are ignored (shared
# lists are only visible to their owner), and sharing, assigning, @mentions, activity, News, status updates
# and collaboration pushes are off. Nothing is deleted; switching it on brings everything back. One process
# (waitress threads) and only the admin endpoint writes the value, so this cache is authoritative.
_COLLAB_ALL = {"on": True}


def collab_all():
    return _COLLAB_ALL["on"]


def need_collab():
    if not collab_all():
        raise Denied(403, tr("Collaboration is turned off on this server (an admin can turn it on)"))


# Time tracking for everyone (admin switch, settings.time_all), same pattern: off = the time endpoints refuse,
# no timers, no focus -> time entries, no timer pushes; entries stay. Timers running at that moment are stopped
# (end = the moment of switching off), so nothing keeps counting unseen.
_TIME_ALL = {"on": True}


def time_all():
    return _TIME_ALL["on"]


def need_time():
    if not time_all():
        raise Denied(403, tr("Time tracking is turned off on this server (an admin can turn it on)"))


# the user's own module switches (Settings > Layout): the action endpoints of a switched-off module refuse like the
# list-type gating (409 with the reason); reading, stopping and the data stay. deps / fields keep their API (D2 rule).
FEAT_OFF = {"pomo": N_("The focus timer is turned off in your settings"), "habits": N_("Habits are turned off in your settings"),
            "time": N_("Time tracking is turned off in your settings"), "comments": N_("Comments are turned off in your settings"),
            "events": N_("Events are turned off in your settings"), "contacts": N_("Contacts are turned off in your settings"),
            # 2.22.0 (#663): the modules of "Home & life"
            "contracts": N_("Contracts are turned off in your settings"), "home": N_("Home & devices are turned off in your settings"),
            "care": N_("Staying in touch is turned off in your settings"), "health": N_("Health is turned off in your settings"),
            "review": N_("The review is turned off in your settings"), "travel": N_("Travel is turned off in your settings"),
            "reading": N_("Read later is turned off in your settings"),
            # 2.23.0 (#463): package "Team, family, clients"
            "clients": N_("Clients are turned off in your settings"), "workload": N_("Workload is turned off in your settings"),
            "forms": N_("Forms are turned off in your settings"),
            "office": N_("Office & finance is turned off in your settings")}  # 2.36.1 (#1021)


# 2.22.0 (#663): health lists (lists.life 'health') are private. An agent never sees them (whatever list it is a member
# of), an API token only with the scope "private"; the web app, calendar apps (app passwords) and the owner's family
# members they share the list with see them as usual. Background work (reminders) is not affected.
def health_hidden(c=None, uid=None):
    """True when the current request (or user uid) must not see health lists."""
    if has_request_context() and getattr(g, "user", None) is not None and (uid is None or uid == g.user["id"]):
        u = g.user
        if (u["kind"] if "kind" in u.keys() else "user") == "agent":
            return True
        if g.get("auth_via") == "token" and "private" not in (g.get("scopes") or set()):
            return True
        return False
    if uid is not None and c is not None:
        r = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
        return bool(r and r[0] == "agent")
    return False


# 2.30.0 (#919): least privilege. An API token (an agent's tokens carry the agent's choice) may be limited to selected lists
# (api_tokens.list_ids, csv; '' = all): on every /api/v1 request the other lists do not exist for it -- list_role answers
# None (404), vis_sql / wr_sql leave them out. Only the token's own user is limited (other people's roles stay).
def token_lists():
    """frozenset of the list ids the current request's token is limited to, or None (no limit / not a token request)."""
    if not has_request_context() or g.get("auth_via") != "token":
        return None
    if "token_lists" in g:
        return g.token_lists
    t, out = g.get("token"), None
    raw = (t["list_ids"] if t is not None and "list_ids" in t.keys() else "") or ""
    if raw.strip():
        out = frozenset(int(x) for x in raw.split(",") if x.strip().isdigit())
    g.token_lists = out
    return out


def access_note(lid, write=False):
    """2.30.0 (#919): an agent's request touched list lid (the access log counts it once per request: read or write)."""
    if not lid or not has_request_context() or not g.get("audit_aid"):
        return
    d = g.get("agent_access")
    if d is None:
        d = g.agent_access = {}
    d[lid] = d.get(lid, False) or bool(write)


def need_feat(f):
    if f not in (usettings(db(), me()).get("features") or "").split(","):
        raise Denied(409, tr(FEAT_OFF[f]))


def _members_on():
    return "" if collab_all() else " AND 0"


# ---------------------------------------------------------------- 2.36.2 (#1142): request context + the one list scope
# Every request carries ONE access context, built once from the signed-in account (session, proxy login, API / agent token,
# CalDAV app password, calendar feed token) and its memberships -- never from the workspace switch: there is no "current
# organisation" per request, the shared view "All workspaces" keeps answering everything in one response.
#   user_id      the account (None: nobody / system)
#   org_ids      the organisations the account belongs to (user_orgs; an agent: only its own workspace agents.org_id)
#   role         "user" | "agent" | "system" | "anon"
#   agent_org_id the agent's workspace (None: private agent or not an agent)
#   list_allow   frozenset of the list ids an API token is limited to (None: no limit)
# Background threads, the watchdog and migrations use system_ctx() (greppable). In 2.37 (Postgres) exactly these values are
# set per transaction for the row-level policies -- see acx_session_vars(), the one place that will add
# SET LOCAL app.user_id / app.org_ids / app.role.
class AccessCtx(NamedTuple):
    user_id: Optional[int]
    org_ids: tuple
    role: str
    agent_org_id: Optional[int]
    list_allow: Optional[frozenset]


def system_ctx():
    """The context of background work (watchdog, reminders, migrations, boundary check): no per-user limits."""
    return AccessCtx(None, (), "system", None, None)


def _boundary_on():
    """Organisation boundaries may exist: not in the modes shared (no organisations) and organisation (one organisation,
    everybody in it). Without KALMIDO_INSTANCE_MODE the number of organisations decides (see _boundary_sql)."""
    from ..accounts.orgs import INSTANCE_ENV
    return INSTANCE_ENV not in ("shared", "organisation")


def _boundary_sql():
    """SQL condition that is true when the boundary applies (mode workspaces / multi; unset mode: more than one org)."""
    from ..accounts.orgs import INSTANCE_ENV
    return "1=1" if INSTANCE_ENV in ("workspaces", "multi") else "(SELECT COUNT(*) FROM orgs) > 1"


def _orgs_of(c, uid):
    """(org_ids, agent_org_id, is_agent) of account uid; agents: only their own workspace."""
    a = c.execute("SELECT org_id FROM agents WHERE user_id=?", (uid,)).fetchone()
    if a is not None:
        return ((a[0],) if a[0] else ()), a[0], True
    from ..accounts.orgs import user_orgs
    return tuple(user_orgs(c, uid)), None, False


def acx_of(c, uid):
    """The access context of account uid (cached per request; no token limit -- that belongs to the request only)."""
    if not uid:
        return system_ctx()
    if has_request_context():
        cache = g.setdefault("acx_users", {})
        if uid not in cache:
            cache[uid] = _ctx_build(c, uid)
        return cache[uid]
    hit = _BG_CTX.get(uid)  # background work: a short-lived cache (memberships change rarely; 2 s)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    ctx = _ctx_build(c, uid)
    if len(_BG_CTX) > 5000:
        _BG_CTX.clear()
    _BG_CTX[uid] = (time.monotonic() + 2.0, ctx)
    return ctx


_BG_CTX = {}


def _ctx_build(c, uid):
    orgs, aorg, agent = _orgs_of(c, uid)
    return AccessCtx(uid, orgs, "agent" if agent else "user", aorg, None)


def acx(c=None):
    """The current request's access context (built once per request and account; rebuilt when g.user changes).
    Outside a request: system_ctx()."""
    if not has_request_context():
        return system_ctx()
    u = getattr(g, "user", None)
    uid = u["id"] if u is not None else None
    cur = g.get("acx")
    if cur is not None and cur.user_id == uid:
        return cur
    if uid is None:
        ctx = AccessCtx(None, (), "anon", None, None)
    else:
        ctx = acx_of(c or db(), uid)._replace(list_allow=token_lists())
    g.acx = ctx
    return ctx


def acx_drop():
    """Forget the cached contexts of this request (call after organisation memberships changed)."""
    _BG_CTX.clear()
    if has_request_context():
        g.pop("acx", None)
        g.pop("acx_users", None)


def acx_session_vars(ctx):
    """2.37 (Postgres row-level security): the session variables of a context -- exactly these values become
    SET LOCAL app.user_id / app.org_ids / app.role. Not used by SQLite."""
    return {"app.user_id": "" if ctx.user_id is None else str(ctx.user_id),
            "app.org_ids": ",".join(str(int(x)) for x in ctx.org_ids), "app.role": ctx.role}


def acx_org_ok(c, uid, org_id):
    """May account uid see an object of organisation org_id at all? Private objects (None): yes (the object's own rules
    decide). Organisation objects: only members (agents: only of their own workspace). The second floor under every
    membership row: former members lose access even where a membership row was left behind."""
    if not org_id or not uid or not _boundary_on():
        return True
    from ..accounts.orgs import instance_mode
    if instance_mode(c) == "organisation":
        return True  # one organisation, everybody in it (user_orgs)
    ctx = acx_of(c, uid)
    if ctx.role == "agent" and ctx.agent_org_id is None:
        return True  # a private agent: its list memberships decide (as before; the boundary check counts mismatches)
    return org_id in ctx.org_ids


# the organisation condition of the list scope, relative to the account column p.u (standard SQL, no parameters)
_ORG_SCOPE_SQL = ("(l.org_id IS NULL OR EXISTS (SELECT 1 FROM agents a WHERE a.user_id=p.u AND (a.org_id IS NULL OR a.org_id=l.org_id)) "
                  "OR (NOT EXISTS (SELECT 1 FROM agents a WHERE a.user_id=p.u) "
                  "AND EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=l.org_id AND om.user_id=p.u)))")


def acx_lists_sql(write=False, req=True):
    """THE list scope (2.36.2, #1142): subquery of the list ids an account may see (write: change as a whole). Two ? = the
    account id. One place for owner / members / roles, the collaboration switch, the organisation boundary and (req=True:
    the request's own account) the health-list and token-allowlist filters. vis_sql, wr_sql, visible_lists and dav_lists use
    it. Participants are in the read scope; what they see is decided per task (tvis)."""
    roles = " AND role IN ('edit', 'admin')" if write else ""
    org = f" AND (NOT ({_boundary_sql()}) OR {_ORG_SCOPE_SQL})" if _boundary_on() else ""
    return (f"(SELECT l.id FROM lists l, (SELECT CAST(? AS INTEGER) AS u, CAST(? AS INTEGER) AS v) p "
            f"WHERE (l.owner_id=p.u OR l.id IN (SELECT list_id FROM list_members WHERE user_id=p.v{roles}{_members_on()})){org}"
            f"{_req_filters_sql() if req else ''})")


def _req_filters_sql():
    """The request's own filters as plain WHERE conditions on l (health lists, token allowlist) -- no set operations, so
    the precedence is the same in every SQL dialect."""
    out = " AND COALESCE(l.life, '')!='health'" if health_hidden() else ""
    tl = token_lists()
    if tl is not None:
        out += f" AND l.id IN ({','.join(str(int(x)) for x in sorted(tl)) or '0'})"
    return out


def vis_sql():
    """Subquery of the list ids the current user may see (two ? = user id)."""
    return acx_lists_sql()


def wr_sql():
    """Subquery of the list ids the current user may change as a whole (two ? = user id). Participants are not in it:
    what they may change is decided per task (tvis(..., write=True))."""
    return acx_lists_sql(write=True)


# ---------------------------------------------------------------- list roles (1.10.0)
# Roles of a list member (list_members.role; the owner is lists.owner_id, never a member row):
#   admin       sees and changes everything, manages members and their roles (not the owner)
#   edit        "Member": sees and changes everything (the role every share had before 1.10.0)
#   view        "Viewer": sees everything, changes nothing (may comment)
#   participant sees ONLY the tasks assigned to them (with all their subtasks, comments, files) and, read-only and
#               without notes / comments / files, the parent chain of an assigned subtask as context. Sections,
#               progress, search, calendar, statistics, time, API, webhooks, News: everything is filtered on the server.
#               They may add tasks to the list (always assigned to themselves) and subtasks under their tasks.
# The stored values edit / view stay (API compatibility); the app shows them as Member / Viewer.
ROLES = ("admin", "edit", "participant", "view")
FULL_ROLES = ("owner", "admin", "edit", "view")  # see the whole list
WRITE_ROLES = ("owner", "admin", "edit")         # change the whole list
MANAGE_ROLES = ("owner", "admin")                # members + roles, moderate comments


def plists(c, uid):
    """Ids of the lists in which uid is a participant (empty while collaboration is off: memberships are ignored)."""
    if not uid or not collab_all():
        return []
    return [r[0] for r in c.execute("SELECT list_id FROM list_members WHERE user_id=? AND role='participant' ORDER BY list_id",
                                    (int(uid),))]


def _pset_sql(uid, pl, write=False):
    """SELECT of the task ids uid sees (write: may change) in the participant lists pl (ints, inlined; no ? params):
    assigned to uid + all their subtasks; for reading also the parent chain of those (context)."""
    q, u, depth_cap = ",".join(str(int(x)) for x in pl), int(uid), MAX_DEPTH + 7
    base = f"""WITH RECURSIVE pa(id) AS (SELECT id FROM tasks WHERE (assignee_id={u} OR assignee_group_id IN
                                            (SELECT group_id FROM group_members WHERE user_id={u})
                                            OR id IN (SELECT task_id FROM task_people WHERE user_id={u})) AND list_id IN ({q})),
               dn(id, lvl) AS (SELECT id, 0 FROM pa UNION
                               SELECT t.id, dn.lvl + 1 FROM tasks t JOIN dn ON t.parent_id=dn.id
                               WHERE dn.lvl < {depth_cap} AND t.list_id IN ({q}))"""
    if write:
        return base + " SELECT id FROM dn"
    return base + f""", up(id, lvl) AS (SELECT t.parent_id, 1 FROM tasks t JOIN pa ON pa.id=t.id WHERE t.parent_id IS NOT NULL UNION
                               SELECT t.parent_id, up.lvl + 1 FROM tasks t JOIN up ON t.id=up.id
                               WHERE t.parent_id IS NOT NULL AND up.lvl < {depth_cap})
               SELECT id FROM dn UNION SELECT id FROM up"""


def tvis(c, uid, a="", write=False):
    """SQL condition (no ? params) that keeps only the task rows uid may see (write: change) among tasks of lists uid
    can access at all. Combine it with the list-level filter (vis_sql / wr_sql / a list id): it only removes the tasks
    a participant must not see. "1" when uid is a participant nowhere (the usual case)."""
    pl = plists(c, uid)
    if not pl:
        return "1"
    q = ",".join(str(int(x)) for x in pl)
    return f"({a}list_id NOT IN ({q}) OR {a}id IN ({_pset_sql(uid, pl, write)}))"


def pvis(c, uid, lid=None):
    """(visible, writable, context) task id sets of uid in their participant lists (or only in list lid)."""
    pl = plists(c, uid)
    if lid is not None:
        pl = [x for x in pl if x == lid]
    if not pl:
        return set(), set(), set()
    vis = {r[0] for r in c.execute(_pset_sql(uid, pl))}
    wr = {r[0] for r in c.execute(_pset_sql(uid, pl, write=True))}
    return vis, wr, vis - wr


def task_visible(c, tid, uid, write=False, full=False):
    """May uid see (write: change) task tid? Full roles: the list decides; participants: the task (full: not only as
    context, i.e. with notes, comments and files)."""
    r = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone() if tid else None
    if not r:
        return False
    role = list_role(c, r[0], uid)
    if write and role and has_request_context() and g.get("audit_aid") == uid:
        access_note(r[0], True)
    if role == "participant":
        vis, wr, _ = pvis(c, uid, r[0])
        return tid in (wr if write or full else vis)
    return bool(role) and (not write or role in WRITE_ROLES)


def acx_task_ok(c, tid, uid):
    """2.36.2 (#1142): second floor of News entries and agent events that carry a task: only for someone who may see the
    task (a task that no longer exists passes -- its event carries no content of a living task)."""
    if not tid or not uid:
        return True
    if not c.execute("SELECT 1 FROM tasks WHERE id=?", (tid,)).fetchone():
        return True
    return task_visible(c, tid, uid)


def list_role(c, lid, uid=None):
    uid = uid or me()
    r = c.execute("SELECT owner_id, life, org_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        return None
    if r[1] == "health" and health_hidden(c, uid):  # 2.22.0 (#663)
        return None
    if not acx_org_ok(c, uid, r[2]):  # 2.36.2 (#1142): an organisation's list only for its members
        return None
    if has_request_context() and g.get("auth_via") == "token" and getattr(g, "user", None) is not None and uid == g.user["id"]:
        tl = token_lists()  # 2.30.0 (#919): a token limited to selected lists
        if tl is not None and lid not in tl:
            return None
    if r[0] == uid:
        role = "owner"
    else:
        m = c.execute("SELECT role FROM list_members WHERE list_id=? AND user_id=?", (lid, uid)).fetchone()
        role = m[0] if m and collab_all() else None
    if role and has_request_context() and g.get("audit_aid") == uid:
        access_note(lid)  # 2.30.0 (#919): the agents' list access log
    return role


def need_list(c, lid, write=True, owner=False, manage=False):
    """Role of the current user in list lid; 404 when they cannot see it, 403 when the action needs more:
    write = change the list as a whole (participants and viewers cannot), manage = members / roles."""
    role = list_role(c, lid) if lid else None
    if not role:
        raise Denied(404)
    if write:
        access_note(lid, True)
    if (owner and role != "owner") or (manage and role not in MANAGE_ROLES) or (write and role not in WRITE_ROLES):
        raise Denied(403)
    return role


# list types (package D2): time tracking, dependencies, custom fields and project status only in project lists
PROJECT_ONLY = {"time": N_("Make this list a project to track time"),
                "deps": N_("Make both lists projects to link their tasks"),
                "fields": N_("Make this list a project to use custom fields"),
                "status": N_("Make this list a project to set a status"),
                "overview": N_("Make this list a project to use its project page")}
PROJ_SQL = "(SELECT id FROM lists WHERE kind='project')"


def is_project(c, lid):
    r = c.execute("SELECT kind FROM lists WHERE id=?", (lid,)).fetchone() if lid else None
    return bool(r) and r[0] == "project"


def need_project(c, lid, what):
    if not is_project(c, lid):
        raise Denied(409, tr(PROJECT_ONLY[what]))


def need_task(c, tid, write=True, full=False):
    """Role of the current user in the task's list; 404 when they cannot see the task, 403 when they cannot change it.
    Participants: only their tasks (and subtasks); the parent chain of an assigned subtask is context -- readable with
    full=False only (no notes, comments, files, history)."""
    r = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()
    if not r:
        raise Denied(404)
    role = list_role(c, r[0])
    if write and role:
        access_note(r[0], True)
    if role == "participant":
        vis, wr, ctx = pvis(c, me(), r[0])
        if tid not in vis or (full and tid in ctx):
            raise Denied(404)
        if write and tid not in wr:
            raise Denied(403)
        return role
    return need_list(c, r[0], write)


# 2.26.0: at most ONE agent per list (owner or member), enforced on every way into a list -- each list is its own sandbox,
# agents cannot hand each other text through a shared list. An agent's own sub-agents run under its account (not affected).
# Lists that had several agents before stay as they are (nothing removed automatically); their owner sees a hint.
ONE_AGENT_MSG = N_("Only one agent per list is allowed. Create a separate list for the second agent.")


def list_other_agent(c, lid, uid):
    """2.26.0: the id of another agent already in list lid (owner or member) when uid is an agent, else None."""
    if not c.execute("SELECT 1 FROM users WHERE id=? AND kind='agent'", (uid,)).fetchone():
        return None
    r = c.execute("""SELECT id FROM users WHERE kind='agent' AND id!=? AND (id=(SELECT owner_id FROM lists WHERE id=?)
                     OR id IN (SELECT user_id FROM list_members WHERE list_id=?)) ORDER BY id LIMIT 1""", (uid, lid, lid)).fetchone()
    return r[0] if r else None


def list_people(c, lid):
    """Owner + member ids of a list."""
    r = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    ids = {r[0]} if r else set()
    ids.update(x[0] for x in c.execute("SELECT user_id FROM list_members WHERE list_id=?", (lid,)))
    return ids


def my_inbox(c, uid=None):
    uid = uid or me()
    r = c.execute("SELECT id FROM lists WHERE is_inbox=1 AND owner_id=?", (uid,)).fetchone()
    if r:
        return r[0]
    ensure_inbox(c, uid)
    return c.execute("SELECT id FROM lists WHERE is_inbox=1 AND owner_id=?", (uid,)).fetchone()[0]


def my_max_sort(c, uid):
    a = c.execute("SELECT COALESCE(MAX(sort),0) FROM lists WHERE owner_id=?", (uid,)).fetchone()[0]
    b = c.execute("SELECT COALESCE(MAX(sort),0) FROM list_members WHERE user_id=?", (uid,)).fetchone()[0]
    return max(a, b)
