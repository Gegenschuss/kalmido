"""Access control: who sees / changes which list and task, module switches, list roles."""

import os
import time
from typing import NamedTuple, Optional

from flask import g, has_request_context

from ..core.config import app
from ..core.schema import MAX_DEPTH
from ..core.i18n import N_, tr
from ..core.db import db, ensure_inbox, err, usettings
from ..core.ctx import me  # 2.149.0 G (#2517): was accounts.session
from ..core.errors import Denied  # noqa: F401  2.149.0 G (#2517): moved to core/errors.py, re-exported here
from .pg import set_ctx_hook, st_ids, system_ctx as pg_system  # 2.149.0 G (#2517): pulled up from functions
from .dlock import dl_list_hidden, dl_lists_sql, dl_task_hidden, dl_task_sql  # 2.235.0 B (#2902): an agent's data lock


# ---------------------------------------------------------------- access control
# A list is visible to its owner and its members; role 'view' is read-only. Objects the user cannot
# see answer 404 (their existence is not revealed), writes with a view-only role 403.


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
            "office": N_("Office & finance is turned off in your settings"),  # 2.36.1 (#1021)
            "dispo": N_("The disposition is turned off in your settings"),  # 2.50.0 (#1194)
            "budget": N_("The household budget is turned off in your settings"),  # 2.72.0 (#1333)
            "feeds": N_("Feeds are turned off in your settings"),  # 2.85.0 B (#1162)
            "sheets": N_("Tables are turned off in your settings")}  # 2.89.0 (#1916)


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
    return "" if collab_all() else " AND FALSE"  # 2.37.0: a boolean for Postgres (was AND 0)


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
    """Organisation boundaries may exist: not in the mode shared (no organisations). 2.46.0 (#1592): always otherwise."""
    from ..accounts.orgs import INSTANCE_ENV
    return INSTANCE_ENV != "shared"


def _boundary_sql():
    """SQL condition that is true when the boundary applies. 2.46.0 (#1592): always (no longer only with several organisations)."""
    return "1=1"


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
            cache[uid] = _ctx_cached(c, uid)
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

# 2.149.0 C (#2508): requests reuse the memberships of an account across requests for a few seconds (KALMIDO_ACX_TTL,
# 0 = off). An entry is only taken while the instance-wide generation in kalmido_meta 'acx_gen' is unchanged; database
# triggers renew it on every write to org_members / agents (org, account) / orgs (personal office), in the writing
# transaction, so a change reaches every process with the next request. The session itself is never cached.
try:
    ACX_TTL = float(os.environ.get("KALMIDO_ACX_TTL", "10").strip() or 0)
except ValueError:
    ACX_TTL = 10.0
_REQ_CTX = {}

ACX_GEN_FN = """CREATE OR REPLACE FUNCTION kalmido_acx_bump() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
  INSERT INTO kalmido_meta(key, value) VALUES ('acx_gen', md5(random()::text || clock_timestamp()::text))
    ON CONFLICT (key) DO UPDATE SET value = excluded.value;
  RETURN NULL;
END $fn$"""
ACX_GEN_TRIGGERS = {
    "org_members": "INSERT OR UPDATE OR DELETE OR TRUNCATE",
    "agents": "INSERT OR DELETE OR TRUNCATE OR UPDATE OF org_id, user_id",
    "orgs": "INSERT OR DELETE OR TRUNCATE OR UPDATE OF personal_of",
}


def acx_gen_setup(c):
    """2.149.0 C (#2508), init_db (every start): the triggers that renew 'acx_gen' (idempotent; one per statement)."""
    c.execute(ACX_GEN_FN)
    for t, ev in ACX_GEN_TRIGGERS.items():
        c.execute(f"CREATE OR REPLACE TRIGGER kalmido_acx_{t} AFTER {ev} ON {t} FOR EACH STATEMENT EXECUTE FUNCTION kalmido_acx_bump()")
    # 2.149.0 review: a new generation on every start / after a restore (the dump brings an old value along)
    c.execute("INSERT INTO kalmido_meta(key, value) VALUES ('acx_gen', md5(random()::text || clock_timestamp()::text)) "
              "ON CONFLICT (key) DO UPDATE SET value = excluded.value")


def _acx_gen(c):
    """The membership generation as this transaction sees it: read fresh each time, so a transaction that changed
    memberships itself (renewed, not yet committed) never meets an older entry, and what it stores stays invisible to
    others until it commits (after a rollback the value never appears)."""
    r = c.execute("SELECT value FROM kalmido_meta WHERE key='acx_gen'").fetchone()
    return r[0] if r else ""


def _ctx_cached(c, uid):
    if ACX_TTL <= 0:
        return _ctx_build(c, uid)
    gen = _acx_gen(c)  # read before the memberships: a change committed in between only makes the entry miss later
    now = time.monotonic()
    hit = _REQ_CTX.get(uid)
    if hit and hit[0] > now and hit[1] == gen:
        return hit[2]
    ctx = _ctx_build(c, uid)
    if len(_REQ_CTX) > 5000:
        _REQ_CTX.clear()
    _REQ_CTX[uid] = (now + ACX_TTL, gen, ctx)
    return ctx


def _ctx_build(c, uid):
    with pg_system(c):  # 2.37.0 (#1150): the memberships themselves are read past row-level security
        orgs, aorg, agent = _orgs_of(c, uid)
        if not agent:  # 2.47.3 (#1360): the person's personal office (a hidden orgs row only its owner reaches)
            r = c.execute("SELECT id FROM orgs WHERE personal_of=?", (uid,)).fetchone()
            if r:
                orgs = (*orgs, r[0])
    return AccessCtx(uid, orgs, "agent" if agent else "user", aorg, None)


def acx(c=None):
    """The current request's access context (built once per request and account; rebuilt when g.user changes).
    Outside a request: system_ctx()."""
    if not has_request_context():
        return system_ctx()
    u = getattr(g, "user", None)
    uid = u["id"] if u is not None else None
    cur = g.get("acx")
    if cur is not None and cur.user_id == uid and (uid is not None or cur.org_ids == tuple(g.get("acx_anon_orgs") or ())):
        return cur
    if uid is None:
        ctx = AccessCtx(None, tuple(g.get("acx_anon_orgs") or ()), "anon", None, None)
    else:
        ctx = acx_of(c or db(), uid)._replace(list_allow=token_lists())
    g.acx = ctx
    acx_session_apply(ctx)
    return ctx


def acx_conn_hook(c):
    """2.37.0 (#1150, W-2): the context of the next statement on a pooled connection (core/pg.py Conn._resolve_ctx asks
    before every statement and applies a change at once): the signed-in account ("user" / "agent" with its
    organisations), without an account "anon" (organisations: only what a public path bound on purpose,
    g.acx_anon_orgs), outside a request None (keep the connection's own context: "system" for background threads). c is
    None for the cheap question; when the memberships are not cached yet the answer is pg.LOOKUP and the second call
    (c given) reads them as "system". Never writes g.acx (that stays acx()'s, with the token's list limit)."""
    if not has_request_context():
        return None
    u = getattr(g, "user", None)
    uid = (u["id"] if u is not None else None) or None  # 0 / None: a stand-in actor (public link, hook) = nobody
    if uid is None:
        uid = g.get("acx_token_uid")  # a personal secret link without a session (calendar feed, /drop): its owner
    if uid is None:
        return (None, tuple(g.get("acx_anon_orgs") or ()), "anon")
    cur = g.get("acx")
    if cur is not None and cur.user_id == uid:
        return (uid, cur.org_ids, cur.role)
    hit = g.get("acx_users", {}).get(uid)
    if hit is None:
        if c is None:
            from .pg import LOOKUP
            return LOOKUP
        hit = acx_of(c, uid)
    return (uid, hit.org_ids, hit.role)


def _acx_hook_register():
    set_ctx_hook(acx_conn_hook)


_acx_hook_register()


def acx_token_bind(uid):
    """2.37.0 (#1150): a request authenticated by a personal secret in the URL / header but without a session (the calendar
    feed, /drop) reads with its owner's context (from the next statement on) -- g.user stays unset."""
    g.acx_token_uid = int(uid)


def acx_anon_bind(c, org_id):
    """2.37.0 (#1150): a public path (list link, form, error-report / git hook) resolved its token as "system" and now
    reads as "anon" bound to exactly the organisation of what the token opens (None: a private object, no organisation).
    Applies to the running transaction at once and to every later one of this request.
    2.152.0 (#2167): a retired organisation (kept by law only) opens no public link any more: 404."""
    if org_id:
        from ..core.pg import system_ctx as _sys
        with _sys(c):  # instance structure: is the organisation retired?
            r = c.execute("SELECT retired_at FROM orgs WHERE id=?", (int(org_id),)).fetchone()
        if r and r[0]:
            raise Denied(404)
    g.acx_anon_orgs = (int(org_id),) if org_id else ()
    g.pop("acx", None)  # the next statement on c runs with it (core/pg.py asks acx_conn_hook)


def acx_drop():
    """Forget the cached contexts of this request (call after organisation memberships changed)."""
    _BG_CTX.clear()
    _REQ_CTX.clear()  # 2.149.0 C (#2508); other processes follow 'acx_gen' (renewed by the triggers)
    if has_request_context():
        g.pop("acx", None)
        g.pop("acx_users", None)
        g.pop("org_roles", None)  # 2.143.0 A (#2151): accounts/orgroles.py
        g.pop("_lr_cache", None)  # 2.280.0 B (#3116): list_role's request cache


def acx_session_apply(ctx=None):
    """2.37.0 (#1150): hand the request's context to its database connection. core/pg.py sets it with SET LOCAL semantics
    (set_config(..., true)) at the start of every transaction -- also after each commit -- so it never leaks into the next
    request on the same pooled connection. Background threads / init_db keep "system" (pg.SYSTEM)."""
    if has_request_context() and "db" in g:
        ctx = ctx or g.get("acx")
        if ctx is not None:
            g.db.set_ctx(**acx_conn_args(ctx))


def acx_conn_args(ctx):
    return {"user_id": ctx.user_id, "org_ids": ctx.org_ids, "role": ctx.role}


def acx_session_vars(ctx):
    """Postgres row-level security: the session variables of a context -- exactly these values are set per transaction
    as app.user_id / app.org_ids / app.role (core/pg.py Conn.set_ctx)."""
    return {"app.user_id": "" if ctx.user_id is None else str(ctx.user_id),
            "app.org_ids": ",".join(str(int(x)) for x in ctx.org_ids), "app.role": ctx.role}


def acx_org_ok(c, uid, org_id):
    """May account uid see an object of organisation org_id at all? Private objects (None): yes (the object's own rules
    decide). Organisation objects: only members (agents: only of their own workspace). The second floor under every
    membership row: former members lose access even where a membership row was left behind."""
    if not org_id or not uid or not _boundary_on():
        return True
    ctx = acx_of(c, uid)
    if ctx.role == "agent" and ctx.agent_org_id is None:
        return True  # a private agent: its list memberships decide (as before; the boundary check counts mismatches)
    return org_id in ctx.org_ids


# the organisation condition of the list scope, relative to the account column p.u (standard SQL, no parameters)
_ORG_SCOPE_SQL = ("(l.org_id IS NULL OR EXISTS (SELECT 1 FROM agents a WHERE a.user_id=p.u AND (a.org_id IS NULL OR a.org_id=l.org_id)) "
                  "OR (NOT EXISTS (SELECT 1 FROM agents a WHERE a.user_id=p.u) "
                  "AND EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=l.org_id AND om.user_id=p.u)))")


# 2.46.0 (#1603): "Everyone in the organisation" -- an organisation list with org_visibility 'org' is in the scope of every
# current member of its organisation (people only, never agents; never health / Home & life / family lists). Relative to p.u.
def _ov_sql(write=False):
    if not collab_all():
        return ""
    return (" OR (l.org_visibility='org' AND l.org_id IS NOT NULL AND COALESCE(l.life, '')='' AND COALESCE(l.family, '')=''"
            + (" AND l.org_edit=1" if write else "")
            + " AND NOT EXISTS (SELECT 1 FROM agents a WHERE a.user_id=p.u)"
            " AND EXISTS (SELECT 1 FROM users ou WHERE ou.id=p.u AND COALESCE(ou.kind, '')!='agent')"
            " AND EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=l.org_id AND om.user_id=p.u"
            + (" AND om.role IN ('admin', 'member')))" if write else " AND om.role IN ('admin', 'member', 'readonly')))"))  # 2.143.0 A (#2151)


def ov_open(row):
    """Does the list row (org_id, life, family, org_visibility) open itself to its organisation?"""
    return bool(row["org_id"]) and (row["org_visibility"] or "") == "org" and not (row["life"] or "") and not (row["family"] or "")


def ov_role(c, lid, uid, row=None):
    """2.46.0 (#1603): the role uid has in list lid only through "Everyone in the organisation" (not shared with them):
    'view', 'edit' with org_edit, else None. Agents never; the owner and members have their own role (list_role)."""
    if not uid or not collab_all():
        return None
    if row is None:
        row = c.execute("SELECT org_id, life, family, org_visibility, org_edit FROM lists WHERE id=?", (lid,)).fetchone()
    if not row or not ov_open(row):
        return None
    if c.execute("SELECT 1 FROM users WHERE id=? AND COALESCE(kind, '')='agent'", (uid,)).fetchone() or \
            c.execute("SELECT 1 FROM agents WHERE user_id=?", (uid,)).fetchone():
        return None
    if not c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (row["org_id"], uid)).fetchone():
        return None
    from ..accounts.orgroles import org_sees_all, org_writes
    if not org_sees_all(c, uid, row["org_id"]):
        return None  # 2.143.0 A (#2151): guests / accounting see only what is shared with them personally
    return "edit" if row["org_edit"] and org_writes(c, uid, row["org_id"]) else "view"


def otr_live(a="l"):
    """2.102.0 A (#1988): THE condition "the list is not in the trash" (lists.deleted_at, see lists/listtrash.py) for SQL on
    lists (a = the alias, "" without one). A deleted list is invisible everywhere except the trash's own routes."""
    return f"{a + '.' if a else ''}deleted_at IS NULL"


def acx_lists_sql(write=False, req=True, ov=True):
    """THE list scope (2.36.2, #1142): subquery of the list ids an account may see (write: change as a whole). Two ? = the
    account id. One place for owner / members / roles, the collaboration switch, the organisation boundary and (req=True:
    the request's own account) the health-list and token-allowlist filters. vis_sql, wr_sql, visible_lists and dav_lists use
    it. Participants are in the read scope; what they see is decided per task (tvis). ov=False: without the lists seen only
    through "Everyone in the organisation" (2.46.0, #1603: calendars, briefing, channels follow the joined lists)."""
    roles = " AND role IN ('edit', 'admin')" if write else ""
    org = f" AND (NOT ({_boundary_sql()}) OR {_ORG_SCOPE_SQL})" if _boundary_on() else ""
    if write and _boundary_on():  # 2.143.0 A (#2151): a read-only member changes no list of the organisation (also their own)
        org += (" AND (l.org_id IS NULL OR NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=l.org_id AND om.user_id=p.u"
                " AND om.role='readonly'))")
    return (f"(SELECT l.id FROM lists l, (SELECT CAST(? AS INTEGER) AS u, CAST(? AS INTEGER) AS v) p "
            f"WHERE {otr_live()} AND (l.owner_id=p.u OR l.id IN (SELECT list_id FROM list_members WHERE user_id=p.v{roles}{_members_on()}){_ov_sql(write) if ov else ''}){org}"
            f"{_req_filters_sql() if req else ''})")


def org_trips_hidden():
    """2.173.0 A (#2680): True for an agent or an API token -- an organisation's trips are for people in the app only for now."""
    return has_request_context() and getattr(g, "user", None) is not None and (
        g.get("auth_via") == "token" or ("kind" in g.user.keys() and g.user["kind"] == "agent"))


def org_trip_sql(a="l."):
    """2.173.1 A (#2714): SQL condition "an organisation's trip" on the list alias a (one place for agents, channels, assistant)."""
    return f"(COALESCE({a}life, '')='travel' AND {a}org_id IS NOT NULL)"


def reading_sql(a="l"):
    """2.172.1 A (#2689): THE condition "a read-later project" on lists alias a: a private one (life 'reading') or the
    project of an organisation (reading_orgs, same organisation as the list = readable wherever the list is). Read later
    is for people in the app only: never an agent's, an API token's or a webhook's."""
    return f"(COALESCE({a}.life, '')='reading' OR EXISTS (SELECT 1 FROM reading_orgs ro WHERE ro.list_id={a}.id))"


def reading_ids(c, ids):
    """2.172.1 A (#2689): the read-later projects among the list ids ids (see reading_sql)."""
    ids = [int(x) for x in ids or ()]
    if not ids:
        return set()
    return {r[0] for r in c.execute(f"SELECT l.id FROM lists l WHERE l.id IN ({','.join('?' * len(ids))}) AND {reading_sql()}", ids)}


def _req_filters_sql():
    """The request's own filters as plain WHERE conditions on l (health lists, token allowlist) -- no set operations, so
    the precedence is the same in every SQL dialect."""
    out = " AND COALESCE(l.life, '') NOT IN ('health', 'budget')" if health_hidden() else ""  # 2.72.0 (#1333): budgets too
    if org_trips_hidden():
        out += f" AND NOT {org_trip_sql()}"  # 2.173.0 A (#2680): an organisation's trip: in the app only for now
        out += f" AND NOT {reading_sql()}"  # 2.172.1 A (#2689): read later: in the app only
    if has_request_context() and getattr(g, "user", None) is not None and "kind" in g.user.keys() and g.user["kind"] == "agent":
        out += " AND l.e2e IS NULL"  # 2.64.1 B (#1817): an agent never sees a list with the lock (it is never a member either)
        out += dl_lists_sql(db(), g.user["id"])  # 2.235.0 B (#2902): the lists its data lock leaves out
    tl = token_lists()
    if tl is not None:
        out += f" AND l.id IN ({','.join(str(int(x)) for x in sorted(tl)) or '0'})"
    return out


def vis_sql(ov=True):
    """Subquery of the list ids the current user may see (two ? = user id; ov=False: only owned / joined, see acx_lists_sql)."""
    return acx_lists_sql(ov=ov)


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
    a participant must not see. "TRUE" when uid is a participant nowhere (the usual case)."""
    pl, dl = plists(c, uid), dl_task_sql(c, uid, a)  # 2.235.0 B (#2902): dl = the tasks the agent's data lock leaves out
    if not pl:
        return f"(TRUE{dl})" if dl else "TRUE"  # 2.37.0 (#1150): Postgres needs a boolean (was "1")
    q = ",".join(str(int(x)) for x in pl)
    return f"(({a}list_id NOT IN ({q}) OR {a}id IN ({_pset_sql(uid, pl, write)})){dl})"


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
    if role and dl_task_hidden(c, tid, uid):
        return False  # 2.235.0 B (#2902): a task the agent's data lock leaves out (404 like any task it cannot see)
    if write and role and has_request_context() and g.get("audit_aid") == uid:
        access_note(r[0], True)
    if role == "participant":
        vis, wr, _ = pvis(c, uid, r[0])
        if write and not _org_list_writes(c, r[0], uid):
            return False  # 2.143.0 A (#2151): read-only in the list's organisation
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


def _org_list_writes(c, lid, uid):
    """2.143.0 A (#2151): may uid change anything in list lid as far as its organisation is concerned (read-only: no)?"""
    r = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()
    from ..accounts.orgroles import org_writes
    return not r or org_writes(c, uid, r[0])


_LR_NO = object()


def _lr_cache(c):
    """2.280.0 B (#3116): the request cache of list_role ({_lr_key: role}) -- only while a GET / HEAD
    runs (reads change no membership; a write request always asks the database), forgotten by acx_drop()."""
    from flask import request
    if not has_request_context() or request.method not in ("GET", "HEAD"):
        return None
    return g.setdefault("_lr_cache", {})


def _lr_key(c, lid, uid):
    # who asks counts too: the db context, the request's account and how it signed in (health / token filters of list_role)
    u = getattr(g, "user", None)
    return lid, uid, getattr(c, "ctx", None), u["id"] if u is not None else None, g.get("auth_via")


def list_roles(c, uid, ids):
    """2.280.0 B (#3116): {list id: role or None} of account uid for many lists -- list_role for each, with the list rows and
    uid's memberships read in two queries for all (not two per list) and the answers kept in the request cache (_lr_cache),
    so later list_role / list_roles calls of the same GET ask nothing again. Same answers as list_role one by one; only the
    ids asked for (the caller's own visible lists / rooms), never every list of the instance."""
    uid = uid or me()
    ids = [int(x) for x in ids or ()]
    cache = _lr_cache(c)
    miss = sorted({x for x in ids if cache is None or _lr_key(c, x, uid) not in cache})
    pre_r, pre_m = {}, {}
    if len(miss) > 1:
        q = st_ids(miss)
        pre_r = {r[7]: r for r in c.execute("SELECT owner_id, life, org_id, family, org_visibility, org_edit, deleted_at, id FROM lists "
                                            "WHERE id = ANY(CAST(? AS BIGINT[]))", (q,)).fetchall()}
        pre_m = {r[1]: r for r in c.execute("SELECT role, list_id FROM list_members WHERE list_id = ANY(CAST(? AS BIGINT[])) AND user_id=?",
                                            (q, uid)).fetchall()}
    out = {}
    for x in ids:
        if x in out:
            continue
        if x in miss and len(miss) > 1:
            role = _list_role(c, x, uid, pre_r.get(x), pre_m.get(x))
            if cache is not None:
                cache[_lr_key(c, x, uid)] = role
            if role and has_request_context() and g.get("audit_aid") == uid:
                access_note(x)
            out[x] = role
        else:
            out[x] = list_role(c, x, uid)
    return out


def list_role(c, lid, uid=None):
    uid = uid or me()
    cache = _lr_cache(c)  # 2.280.0 B (#3116)
    key = _lr_key(c, lid, uid) if cache is not None else None
    if cache is not None and key in cache:
        role = cache[key]
    else:
        role = _list_role(c, lid, uid)
        if cache is not None:
            cache[key] = role
    if role and has_request_context() and g.get("audit_aid") == uid:
        access_note(lid)  # 2.30.0 (#919): the agents' list access log
    return role


def _list_role(c, lid, uid, r=_LR_NO, m=_LR_NO):
    # r / m (2.280.0 B, #3116): the list row / uid's membership row (None = none) already read by list_roles
    if r is _LR_NO:
        r = c.execute("SELECT owner_id, life, org_id, family, org_visibility, org_edit, deleted_at FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or r[6]:  # 2.102.0 A (#1988): a list in the trash has no roles (only the trash routes reach it)
        return None
    if r[1] in ("health", "budget") and health_hidden(c, uid):  # 2.22.0 (#663); 2.72.0 (#1333): budgets too
        return None
    if dl_list_hidden(c, uid, lid, r[1], r[2]):  # 2.235.0 B (#2902): a list the agent's data lock leaves out
        return None
    if not acx_org_ok(c, uid, r[2]):  # 2.36.2 (#1142): an organisation's list only for its members
        return None
    if has_request_context() and g.get("auth_via") == "token" and getattr(g, "user", None) is not None and uid == g.user["id"]:
        tl = token_lists()  # 2.30.0 (#919): a token limited to selected lists
        if tl is not None and lid not in tl:
            return None
    if ((org_trips_hidden() and uid == g.user["id"]) or health_hidden(c, uid)) and reading_ids(c, [lid]):
        return None  # 2.172.1 A (#2689): read later: in the app only (not for an agent / an API token, also when asked for an agent)
    if r[1] == "travel" and r[2] and org_trips_hidden() and uid == g.user["id"]:
        return None  # 2.306.0 D1 (#2875): an organisation's trip by its id too, like the lists (org_trip_sql, #2680)
    if r[0] == uid:
        role = "owner"
    else:
        if m is _LR_NO:
            m = c.execute("SELECT role FROM list_members WHERE list_id=? AND user_id=?", (lid, uid)).fetchone()
        role = m[0] if m and collab_all() else None
        if not m:
            role = ov_role(c, lid, uid, r)  # 2.46.0 (#1603): a reader of an organisation-wide list (not shared with them)
    if role and r[2]:
        from ..accounts.orgroles import cap_list_role
        role = cap_list_role(c, uid, r[2], role)  # 2.143.0 A (#2151): read-only in the organisation -> view
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
PROJECT_ONLY = {"time": N_("Switch on progress and status in this project to track time"),
                "deps": N_("Switch on progress and status in both projects to link their tasks"),
                "fields": N_("Switch on progress and status in this project to use custom fields"),
                "status": N_("Switch on progress and status in this project to set a status"),
                "overview": N_("Switch on progress and status in this project to use its project page")}
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
    if not r or dl_task_hidden(c, tid, me()):  # 2.235.0 B (#2902): a task the agent's data lock leaves out
        raise Denied(404)
    role = list_role(c, r[0])
    if write and role:
        access_note(r[0], True)
    if role == "participant":
        vis, wr, ctx = pvis(c, me(), r[0])
        if tid not in vis or (full and tid in ctx):
            raise Denied(404)
        if write and (tid not in wr or not _org_list_writes(c, r[0], me())):
            raise Denied(403)
        return role
    return need_list(c, r[0], write)


# 2.26.0: at most ONE agent per list (owner or member), enforced on every way into a list -- each list is its own sandbox,
# agents cannot hand each other text through a shared list. An agent's own sub-agents run under its account (not affected).
# Lists that had several agents before stay as they are (nothing removed automatically); their owner sees a hint.
ONE_AGENT_MSG = N_("Only one agent per project is allowed. Create a separate project for the second agent.")


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
