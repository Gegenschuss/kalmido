"""Access control: who sees / changes which list and task, module switches, list roles."""

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
            "forms": N_("Forms are turned off in your settings")}


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


def _health_sql():
    return " EXCEPT SELECT id FROM lists WHERE life='health'" if health_hidden() else ""


def need_feat(f):
    if f not in (usettings(db(), me()).get("features") or "").split(","):
        raise Denied(409, tr(FEAT_OFF[f]))


def _members_on():
    return "" if collab_all() else " AND 0"


def vis_sql():
    """Subquery of the list ids the current user may see (two ? = user id)."""
    return f"(SELECT id FROM lists WHERE owner_id=? UNION SELECT list_id FROM list_members WHERE user_id=?{_members_on()}{_health_sql()})"


def wr_sql():
    """Subquery of the list ids the current user may change as a whole (two ? = user id). Participants are not in it:
    what they may change is decided per task (tvis(..., write=True))."""
    return f"(SELECT id FROM lists WHERE owner_id=? UNION SELECT list_id FROM list_members WHERE user_id=? AND role IN ('edit', 'admin'){_members_on()}{_health_sql()})"


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
    if role == "participant":
        vis, wr, _ = pvis(c, uid, r[0])
        return tid in (wr if write or full else vis)
    return bool(role) and (not write or role in WRITE_ROLES)


def list_role(c, lid, uid=None):
    uid = uid or me()
    r = c.execute("SELECT owner_id, life FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        return None
    if r[1] == "health" and health_hidden(c, uid):  # 2.22.0 (#663)
        return None
    if r[0] == uid:
        return "owner"
    m = c.execute("SELECT role FROM list_members WHERE list_id=? AND user_id=?", (lid, uid)).fetchone()
    return m[0] if m and collab_all() else None


def need_list(c, lid, write=True, owner=False, manage=False):
    """Role of the current user in list lid; 404 when they cannot see it, 403 when the action needs more:
    write = change the list as a whole (participants and viewers cannot), manage = members / roles."""
    role = list_role(c, lid) if lid else None
    if not role:
        raise Denied(404)
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
