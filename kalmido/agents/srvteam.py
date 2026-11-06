"""2.569.0 B (#4675): the Kalmido AI (the server agent, agents/srvagent.py) in team projects - stage 2c.

Two kinds (decision of 05.11.2026):
 (a) a PERSONAL server agent in a project shared with other people: only its owner gives it orders, as for every personal agent.
     agent_emit already drops the asking events of other people (agents/core.py agent_usable: a personal agent only for its
     owner); what still reached its queue from them (a new task while it listens in, a review step, a planned job of someone
     else) is data for its next run, never the start of one (srv_may_order; the SQL of srvagent_run._pending: SRV_FOREIGN_SQL).
 (b) a TEAM server agent of an organisation: an admin of the organisation creates it (POST /api/orgs/<id>/server-agents, no
     instance admin needed) and stores the key; its costs go on that key. Members give it orders where the project opens it to
     them (the project switch "Members may see and use the agent", agents/core.py agent_usable / agent_shares - checked again
     here before a run, because rights change between the event and the run).
     Limits per member: agent_server.member_limits {period day | month, metric tokens, hard} (GET / PUT
     /api/agents/<id>/server/team, an admin of its organisation or an instance admin: srv_need). Every run works for ONE
     requester (srv_batch: the events of the next person wait for the next run), its usage rows carry asked_by; a member at
     the limit gets a clear answer and their requests are not worked on, the other members' runs go on. The limits of the agent
     itself (agents/usage.py usage_block: admins' limits, the owner's budget) hold unchanged on top.
The circle limit (agents/safety.py) and the approvals hold unchanged: they are checks of /api/v1 that the run's token meets.
Proposals of a server agent in a team project (SRV_TEAM_PROP_KINDS with the project's list_id) are seen by every person with
write rights in that project (srv_prop_team_ok: list_role of core/access.py, no own share table); readers and other people never.
"""
from datetime import timezone

from flask import g, jsonify

from ..core.config import app, USERNAME_RE
from ..core.pg import system_ctx, write_lock
from ..core.i18n import N_, tr
from ..core.db import body, bump, create_user, db, ensure_inbox, err, iso, now_utc, uset, usettings
from ..core.access import Denied, list_role, list_roles, WRITE_ROLES
from ..core.errors import BadInput
from ..accounts.session import me
from ..accounts.orgs import is_org_admin
from ..accounts.supportgrant import sga_is_support
from ..accounts.colors import ac_assign
from ..api.v1 import SCOPES_AGENT_DEFAULT
from ..collab.comments import user_names
from ..api.scopes import agent_scopes_set
from .core import AGENT_GATED, agent_row, agent_shares, agent_usable, is_agent, need_person
from .admin import _agent_name, agent_org_set, make_agent
from .usage import USAGE_SUM, usage_limits, usage_limits_clean, usage_period, usage_totals
from .srvagent import srv_need, srv_off, SRV_PROVIDER

SRV_PROV = SRV_PROVIDER
SRV_TEAM_MAX = 5             # team server agents of one organisation that its admins create themselves
# the events in which a person gives the agent an order: their right is checked again before a run (team agents)
SRV_ORDER_EVENTS = AGENT_GATED + ("chat", "chat_choice")
# the proposal kinds that belong to one project (their input comes from it): seen by its members with write rights.
# 2.611.0 D (#4784): applying needs write rights in the CURRENT list of the target (proposals.py prop_run: need_task / need_list write=True);
# and of an extract the others see only the proposed tasks, never the free text / images of the one who asked (prop_view_input)
SRV_TEAM_PROP_KINDS = ("subtasks", "extract", "cleanup")
# SQL for srvagent_run._pending (on agent_events): an event a person other than the owner of a personal agent made
SRV_FOREIGN_SQL = """EXISTS(SELECT 1 FROM agents x WHERE x.user_id=agent_events.agent_id AND x.owner_id IS NOT NULL
                     AND COALESCE(agent_events.payload::jsonb->'actor'->>'kind', '')='person'
                     AND (agent_events.payload::jsonb->'actor'->>'id')::bigint<>x.owner_id)"""
_UNSET = object()


# ---------------------------------------------------------------- who asks

def srv_requester(e):
    """The person an event e (an envelope of /api/v1/agent/events) asks for: the person who made it, else the person a proposal
    request or a planned job names; None for the server's own events (a check, a reminder) and for agents."""
    if not isinstance(e, dict):
        return None
    act = e.get("actor") if isinstance(e.get("actor"), dict) else {}
    if act.get("kind") == "person" and isinstance(act.get("id"), int):
        return act["id"]
    d = e.get("data") if isinstance(e.get("data"), dict) else {}
    if e.get("event") == "job_request":
        rb = d.get("requested_by")
        rb = rb.get("id") if isinstance(rb, dict) else rb
        return rb if isinstance(rb, int) and not isinstance(rb, bool) else None
    if e.get("event") == "scheduled_job":
        by = d.get("by") if isinstance(d.get("by"), dict) else {}
        return by.get("id") if isinstance(by.get("id"), int) else None
    return None


def _ev_lid(d):
    """The project of an event's data (as agents/core.py agent_emit reads it)."""
    if not isinstance(d, dict):
        return None
    t = d.get("task") if isinstance(d.get("task"), dict) else {}
    lst = d.get("list") if isinstance(d.get("list"), dict) else {}
    room = d.get("room") if isinstance(d.get("room"), dict) else {}
    lid = d.get("list_id") or t.get("list_id") or lst.get("id") or room.get("list_id")
    return lid if isinstance(lid, int) and not isinstance(lid, bool) else None


def srv_may_order(c, a, uid, e):
    """May event e of requester uid start work of server agent a? A personal agent: only its owner (or the server itself,
    uid None). A team agent: the server itself, or a person the event's project opens the agent to (agent_usable; a chat
    without a project: agent_shares) - only for the events that are orders (SRV_ORDER_EVENTS); the project's own automations
    (listening in, tidying, the review step) were switched on by its owner and stay as they are."""
    if a is None:
        return False
    if a["owner_id"]:
        return uid is None or uid == a["owner_id"]
    if uid is None or e.get("event") not in SRV_ORDER_EVENTS:
        return True
    lid = _ev_lid(e.get("data"))
    if lid:
        return agent_usable(c, a["user_id"], uid, lid)
    return agent_shares(c, a["user_id"], uid)


def srv_kick_ok(a, actor):
    """srvagent.srv_event: no run for an event another person made for a personal agent (it stays data for the next run)."""
    if not a or not a["owner_id"] or not isinstance(actor, dict) or actor.get("kind") != "person":
        return True
    return actor.get("id") == a["owner_id"]


def srv_batch(c, aid, data, triggers):
    """The events of one run -> (work, cut, who). work = the events that ask the agent for work and may (srv_may_order), all
    from ONE requester who (a team agent: the next person's events wait for the next run; a personal agent: its owner);
    cut = the cursor to keep when events of another requester follow (the seq of the last event of this run), else None.
    The caller runs it in system_ctx (the worker; it acts only through the agent's token afterwards)."""
    a = agent_row(c, aid)
    work, who, cut = [], _UNSET, None
    for i, e in enumerate(data):
        if not isinstance(e, dict) or e.get("event") not in triggers or (e.get("actor") or {}).get("kind") == "agent":
            continue
        uid = srv_requester(e)
        if not srv_may_order(c, a, uid, e):
            continue
        if a and not a["owner_id"]:
            if who is _UNSET:
                who = uid
            elif uid != who:
                prev = data[i - 1].get("seq") if i and isinstance(data[i - 1], dict) else None
                if isinstance(prev, int) and not isinstance(prev, bool):
                    cut = prev
                    break
        work.append(e)
    if a and a["owner_id"]:
        who = a["owner_id"] if work else None
    return work, cut, (None if who is _UNSET else who)


# ---------------------------------------------------------------- limits per member

def srv_member_limits(row):
    """The limit per member {period, metric, soft, hard} of a team agent's agent_server row, or None."""
    if not row or "member_limits" not in row.keys() or not row["member_limits"]:
        return None
    return usage_limits({"usage_limits": row["member_limits"]})


def srv_member_state(c, aid, uid, lim):
    """{used, hard, reached, resets_at} of member uid against limit lim (tokens of agent_usage rows with asked_by=uid)."""
    _, first, end = usage_period(lim["period"])
    r = c.execute(f"SELECT {USAGE_SUM} FROM agent_usage WHERE agent_id=? AND asked_by=? AND day>=?", (aid, uid, first)).fetchone()
    used = usage_totals(r)["tokens"]
    return {"used": used, "hard": lim["hard"], "reached": lim["hard"] is not None and used >= lim["hard"],
            "resets_at": iso(end.astimezone(timezone.utc))}


def srv_member_block(c, aid, uid, rid=None):
    """The reason (an i18n key) when member uid (rid: the requester of run rid) used up their limit of team agent aid, else ''.
    Never for a personal agent's owner (its own limits are the agent's) nor for the server's own events (uid None)."""
    with system_ctx(c):  # the worker's own read of the agent's settings, its run and usage numbers
        if rid is not None:
            r = c.execute("SELECT asked_by FROM agent_runs WHERE id=? AND agent_id=?", (rid, aid)).fetchone()
            uid = r[0] if r else None
        if not uid:
            return ""
        a = agent_row(c, aid)
        if not a or a["owner_id"]:
            return ""
        row = c.execute("SELECT * FROM agent_server WHERE agent_id=?", (aid,)).fetchone()
        lim = srv_member_limits(row)
        if not lim:
            return ""
        return N_("Your usage limit for this agent is reached; the requests of the others still run") \
            if srv_member_state(c, aid, uid, lim)["reached"] else ""


def srv_run_asker(c, rid, uid):
    """The run rid works for person uid (agent_runs.asked_by): its usage rows get the same (srv_usage_mark)."""
    with system_ctx(c):  # the worker's own run row
        c.execute("UPDATE agent_runs SET asked_by=? WHERE id=?", (uid, rid))


def srv_usage_mark(c, aid, rid, usage_id):
    """The usage row usage_id that run rid of agent aid reported counts for the run's requester."""
    if not isinstance(usage_id, int) or isinstance(usage_id, bool):
        return
    with system_ctx(c):  # the usage row the run's own token just reported
        c.execute("""UPDATE agent_usage SET asked_by=(SELECT asked_by FROM agent_runs WHERE id=? AND agent_id=?)
                     WHERE id=? AND agent_id=?""", (rid, aid, usage_id, aid))


def _need_team(c, aid):
    a = srv_need(c, aid)
    if a["owner_id"]:
        raise Denied(400, tr("Only a team agent has limits per member"))
    return a


def _team_dict(c, a):
    with system_ctx(c):  # the agent's own settings and usage numbers (srv_need decided who asks)
        row = c.execute("SELECT * FROM agent_server WHERE agent_id=?", (a["user_id"],)).fetchone()
        lim = srv_member_limits(row)
        rows = c.execute("""SELECT asked_by, COALESCE(SUM(input_tokens + output_tokens + cache_write_tokens), 0) AS t FROM agent_usage
                            WHERE agent_id=? AND asked_by IS NOT NULL AND day>=? GROUP BY asked_by ORDER BY 2 DESC LIMIT 200""",
                         (a["user_id"], _period_first(lim))).fetchall()
    names = user_names(c, [r["asked_by"] for r in rows])
    return {"team": True, "org_id": a["org_id"], "member_limit": lim, "period": lim["period"] if lim else "month",
            "members": [{"id": r["asked_by"], "name": names.get(r["asked_by"], ""), "used": int(r["t"]),
                         "reached": bool(lim and lim["hard"] is not None and r["t"] >= lim["hard"])} for r in rows]}


def _period_first(lim):
    return usage_period(lim["period"] if lim else "month")[1]


@app.get("/api/agents/<int:aid>/server/team")
def srv_team_get(aid):
    """{team, org_id, member_limit: {period, metric, soft, hard} | null, period, members: [{id, name, used, reached}]}."""
    c = db()
    return jsonify(_team_dict(c, _need_team(c, aid)))


@app.put("/api/agents/<int:aid>/server/team")
def srv_team_put(aid):
    """{member_limit: {period: day | month, hard: tokens} | null} -> as GET. Tokens only (a server agent reports no costs)."""
    c = db()
    a = _need_team(c, aid)
    b = body()
    if not isinstance(b, dict) or any(k != "member_limit" for k in b) or "member_limit" not in b:
        return err(tr("Invalid value: {0}", ", ".join(sorted(k for k in (b if isinstance(b, dict) else {}) if k != "member_limit")) or "member_limit"))
    v = b["member_limit"]
    if v not in (None, "", {}):
        if not isinstance(v, dict) or v.get("metric", "tokens") != "tokens" or "soft" in v:
            return err(tr("Invalid value: {0}", "member_limit"))
        if v.get("hard") in (None, ""):
            return err(tr("Invalid value: {0}", "hard"))
        v = {"period": v.get("period", "month"), "metric": "tokens", "hard": v["hard"]}
    try:
        val = usage_limits_clean(v)
    except BadInput as e:
        return err(str(e))
    with system_ctx(c):  # the agent's own row (srv_need decided)
        if not c.execute("SELECT 1 FROM agent_server WHERE agent_id=?", (aid,)).fetchone():
            return err(tr("Set up the agent on the Kalmido server first"), 409)
        c.execute("UPDATE agent_server SET member_limits=?, updated_at=?, updated_by=? WHERE agent_id=?", (val, iso(now_utc()), me(), aid))
    c.commit()
    print("server agent", aid, "member limit", "set" if val else "removed", "by user", me(), flush=True)
    return jsonify(_team_dict(c, a))


# ---------------------------------------------------------------- an organisation's admin creates a team agent

@app.post("/api/orgs/<int:oid>/server-agents")
def srv_team_create(oid):
    """{username, display_name?} -> 201 {id, username, name, org_id, provider} - a team agent of organisation oid that runs on the
    Kalmido server (provider kalmido-server). Only an admin of oid (no instance admin needed, never through a support access);
    then PUT /api/agents/<id>/server stores the organisation's key. 403 server_agents_off while the instance switch is on."""
    need_person(404)
    c = db()
    if is_agent(g.user) or not is_org_admin(c, me(), oid) or sga_is_support(c):
        raise Denied(404)
    if srv_off(c):
        return jsonify(error="server_agents_off", message=tr("Server agents are switched off on this server")), 403
    b = body()
    if not isinstance(b, dict) or any(k not in ("username", "display_name") for k in b):
        return err(tr("The body must be a JSON object"))
    username = str(b.get("username") or "").strip().lower()
    if not USERNAME_RE.fullmatch(username):
        return err(tr("Username: 1-32 characters a-z, 0-9, dot, dash, underscore"))
    write_lock(c, f"srv_team_create:{oid}")
    with system_ctx(c):  # the organisation's admin creates an account (structure): checked above who may
        n = c.execute("SELECT COUNT(*) FROM agents WHERE org_id=? AND owner_id IS NULL AND provider=?", (oid, SRV_PROV)).fetchone()[0]
        if n >= SRV_TEAM_MAX:
            c.rollback()
            return err(tr("An organisation can have at most {0} team agents on the Kalmido server", SRV_TEAM_MAX), 409)
        if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            c.rollback()
            return err(tr("Username already exists"), 409)
        uid = create_user(c, username, _agent_name(b.get("display_name")) or username, None, None, False, paperless_access=False)
        make_agent(c, uid)
        c.execute("UPDATE agents SET provider=?, ai=1 WHERE user_id=?", (SRV_PROV, uid))
        c.execute("UPDATE users SET avatar=? WHERE id=?", ("p:a-robot", uid))
        try:
            agent_org_set(c, uid, oid)
            agent_scopes_set(c, uid, {"scopes": list(SCOPES_AGENT_DEFAULT)})
        except (BadInput, Denied):
            c.rollback()
            raise
        uset(c, uid, "lang", usettings(c, me())["lang"])
        ensure_inbox(c, uid)
        ac_assign(c, [uid])
        bump(c)
    c.commit()
    print("team server agent", uid, "of organisation", oid, "created by user", me(), flush=True)
    with system_ctx(c):  # the new agent's own row (made above by the organisation's admin)
        a = agent_row(c, uid)
    return jsonify(id=uid, username=a["username"], name=a["display_name"] or a["username"], org_id=a["org_id"], provider=SRV_PROV), 201


# ---------------------------------------------------------------- proposals in team projects

def srv_prop_team_ok(c, j, uid):
    """May person uid (not the one who asked) see proposal job j? Only a proposal of a TEAM server agent that belongs to one project
    (SRV_TEAM_PROP_KINDS with its list_id, not a basket) and only with write rights in that project (list_role)."""
    return bool(j) and j["id"] in srv_prop_team_ids(c, [j], uid)


def srv_prop_team_ids(c, jobs, uid):
    """2.611.0 D (#4784): srv_prop_team_ok for many jobs at once -> the set of the ids uid may see as a team proposal. Only the
    team kinds are looked at; their agent rows, lists and uid's roles are read once for all (not per job: Waiting for me scans
    up to 500 jobs). The same rule as before, one place."""
    cand = [j for j in jobs if j and j["kind"] in SRV_TEAM_PROP_KINDS and j["list_id"]]
    if not cand or not uid:
        return set()
    aids = sorted({int(j["agent_id"]) for j in cand})
    with system_ctx(c):  # whose agent it is: the proposals' own agent rows
        team = {r[0] for r in c.execute(f"""SELECT a.user_id FROM agents a JOIN users u ON u.id=a.user_id
                                            WHERE a.user_id IN ({','.join('?' * len(aids))}) AND u.kind='agent'
                                            AND COALESCE(a.provider, '')=? AND a.owner_id IS NULL""", (*aids, SRV_PROV))}
        u = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
    # review: a personal server agent (owner_id) works for its owner alone - its proposals stay with the one who asked
    cand = [j for j in cand if j["agent_id"] in team]
    if not cand or not u or u["kind"] == "agent":
        return set()
    lids = sorted({int(j["list_id"]) for j in cand})
    proj = {r[0] for r in c.execute(f"SELECT id FROM lists WHERE id IN ({','.join('?' * len(lids))}) AND is_inbox=0", lids)}
    roles = list_roles(c, uid, sorted(proj))
    return {j["id"] for j in cand if j["list_id"] in proj and roles.get(j["list_id"]) in WRITE_ROLES}


@app.get("/api/lists/<int:lid>/agent-proposals")
def srv_team_props(lid):
    """{proposals: [{id, kind, title, state, agent: {id, name}, by: {id, name}, updated_at}]} - the ready proposals of server agents
    in project lid, for a person with write rights there (404 otherwise)."""
    need_person(404)
    c = db()
    if list_role(c, lid, me()) not in WRITE_ROLES:
        raise Denied(404)
    rows = c.execute(f"""SELECT * FROM agent_jobs WHERE list_id=? AND kind IN ({','.join('?' * len(SRV_TEAM_PROP_KINDS))})
                         AND prop_state='ready' AND state='waiting' ORDER BY updated_at DESC, id DESC LIMIT 100""",
                     (lid, *SRV_TEAM_PROP_KINDS)).fetchall()
    team = srv_prop_team_ids(c, [j for j in rows if j["user_id"] != me()], me())  # 2.611.0 D (#4784): one look for all rows
    rows = [j for j in rows if j["user_id"] == me() or j["id"] in team]
    names = user_names(c, [j["agent_id"] for j in rows] + [j["user_id"] for j in rows if j["user_id"]])
    return jsonify(proposals=[{"id": j["id"], "kind": j["kind"], "title": j["title"], "state": j["prop_state"],
                               "agent": {"id": j["agent_id"], "name": names.get(j["agent_id"], "")},
                               "by": {"id": j["user_id"], "name": names.get(j["user_id"], "")} if j["user_id"] else None,
                               "updated_at": j["updated_at"]} for j in rows])
