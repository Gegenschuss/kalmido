"""2.30.0 (#919): the server keeps an agent inside one circle of people -- prompt injection cannot be solved reliably at the
AI level, so the boundary is enforced here, not in the model's rules.

PEOPLE CIRCLE of a list = its owner + its members that are persons (agents do not count), every role.
BRIDGE = one agent in two lists whose circles are neither equal nor one inside the other (nested is fine: a private list
and a list shared with one more person). Text of person A in list X could otherwise make the agent copy content of list
Y (that A does not see) into X. Only the lists the agent can really use count (its list restriction, agents.list_ids).
  * Sharing a list with an agent, or adding a person to a list with an agent, that creates a bridge is refused (409,
    code agent_bridge, the lists) unless the request says bridge_ok: true and comes from a person who manages every list
    involved (owner / list admin) or owns the personal agent. The approval is stored per pair (agent_bridges) and shown in
    the agent's settings. An agent never approves a bridge. Automatic ways (Share all, Share new lists automatically,
    shared folders, a proposal's share_agent) skip such lists. Bridges from before 2.30 or from groups / sharing by
    e-mail address stay (nothing is removed) and are flagged in the agent's settings.
  * MOVING a task across circles: an agent that moves a task (with its subtasks, notes, comments, files) into a list
    whose circle is not part of the source list's circle waits for a person's approval (the 2.15 approval jobs). Sharing
    by an agent already waits for approval. Free text cannot be traced to its source -- that is what the bridge rule is for.
LEAST PRIVILEGE: agents.list_ids / api_tokens.list_ids (csv, '' = all) limit an agent / a token to selected lists on top of
the membership (core/access.py token_lists); an agent gets no events about other lists.
ACCESS LOG: per agent, list, day and kind (read | write) one counter (agent_list_access, AGENT_ACCESS_DAYS days); the
members of a list see it (list menu > Agent access, GET /api/lists/<id>/agent-access).
"""
import threading
import time
from datetime import timedelta
from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.i18n import N_, tr, trn
from ..core.db import connect, db, iso, local_now, now_utc
from ..accounts.session import GATE, me
from ..core.access import Denied, list_role, MANAGE_ROLES, need_list
from ..personal.timetrack import BadInput

AGENT_ACCESS_DAYS = 30
LIST_IDS_MAX = 500
BRIDGE_MSG = N_("This would let {0} carry content between lists with different people: {1}. Approve it only if everyone may see what the agent brings from one list into the other.")


class AgentBridge(Exception):
    def __init__(self, items, hidden, agents):
        super().__init__("agent_bridge")
        self.items, self.hidden, self.agents = items, hidden, agents


@app.errorhandler(AgentBridge)
def agent_bridge_resp(e):
    parts = [f"“{x['name']}”" for x in e.items] + ([trn("{0} list you cannot see", "{0} lists you cannot see", e.hidden)] if e.hidden else [])
    msg = tr(BRIDGE_MSG, ", ".join(e.agents) or tr("the agent"), ", ".join(parts))
    if request.path.startswith("/api/v1/"):
        from ..api.v1 import v1_err
        return v1_err(409, msg, name="agent_bridge", bridges=e.items, hidden=e.hidden)
    r = jsonify(error=msg, code="agent_bridge", bridges=e.items, hidden=e.hidden)
    r.status_code = 409
    return r


# ---- circles and bridges
def list_circle(c, lid):
    """The people circle of list lid: owner + members that are persons (frozenset of user ids)."""
    return frozenset(r[0] for r in c.execute("""SELECT id FROM users WHERE COALESCE(kind,'user')!='agent' AND (id=(SELECT owner_id FROM lists
                                                WHERE id=?) OR id IN (SELECT user_id FROM list_members WHERE list_id=?))""", (lid, lid)))


def ids_parse(raw):
    return frozenset(int(x) for x in str(raw or "").split(",") if x.strip().isdigit())


def agent_cap(c, aid):
    """The lists agent aid is limited to (agents.list_ids) or None (all its lists)."""
    r = c.execute("SELECT list_ids FROM agents WHERE user_id=?", (aid,)).fetchone() if aid else None
    raw = (r["list_ids"] if r else "") or ""
    return ids_parse(raw) if raw.strip() else None


def agent_reach(c, aid):
    """The lists agent aid can really use: owned or shared with it (no health list), within its list restriction."""
    rows = [r[0] for r in c.execute("""SELECT id FROM lists WHERE COALESCE(life,'')!='health' AND (owner_id=? OR id IN
                                       (SELECT list_id FROM list_members WHERE user_id=?))""", (aid, aid))]
    cap = agent_cap(c, aid)
    return [x for x in rows if cap is None or x in cap]


def nested(a, b):
    return a <= b or b <= a


def _pair(a, b):
    return (a, b) if a < b else (b, a)


def bridge_ok_pair(c, aid, a, b):
    x, y = _pair(a, b)
    return bool(c.execute("SELECT 1 FROM agent_bridges WHERE agent_id=? AND list_a=? AND list_b=?", (aid, x, y)).fetchone())


def bridge_conflicts(c, aid, lid, circle=None, joining=False):
    """Ids of the other lists of agent aid whose circle is not nested with list lid's (circle: lid's circle to test, e.g.
    with a person added) and that no approval covers. joining: aid is about to join lid (its own cap does not matter then
    for lid; earlier approvals with lid are void)."""
    cap = agent_cap(c, aid)
    if cap is not None and lid not in cap:
        return []  # the agent cannot use lid at all: no bridge through it
    circle = list_circle(c, lid) if circle is None else circle
    reach = [l2 for l2 in agent_reach(c, aid) if l2 != lid]
    circ = {l2: list_circle(c, l2) for l2 in reach}
    if any(x == circle for x in circ.values()):
        return []  # it already works for exactly these people elsewhere: no new bridge (an existing one stays as it is)
    return [l2 for l2 in reach if not nested(circle, circ[l2]) and (joining or not bridge_ok_pair(c, aid, lid, l2))]


def _names(c, ids, viewer):
    items, hidden = [], 0
    for l2 in ids:
        r = c.execute("SELECT name, is_inbox FROM lists WHERE id=?", (l2,)).fetchone()
        if r and viewer and list_role(c, l2, viewer):
            items.append({"list_id": l2, "name": tr("Inbox") if r["is_inbox"] else r["name"]})
        else:
            hidden += 1
    return items, hidden


def may_approve_bridge(c, uid, aid, lids):
    """A person who owns the personal agent aid, or who manages (owner / list admin) every list in lids."""
    from ..agents.admin import agent_owner
    u = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not u or (u["kind"] or "user") == "agent":
        return False
    if agent_owner(c, aid) == uid:
        return True
    return all(list_role(c, x, uid) in MANAGE_ROLES for x in lids)


def bridge_check(c, lid, uid, ok=False):
    """Before uid (an agent or a person) joins list lid: raises AgentBridge (409) when this creates an unapproved bridge;
    with ok (bridge_ok from a person allowed to approve) it stores the approvals instead. Returns the agents' names."""
    from ..agents.core import agent_ids, is_agent
    ag = agent_ids(c)
    if not ag:
        return
    found = []  # (agent id, [other list ids])
    if uid in ag:
        if c.execute("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (lid, uid)).fetchone():
            return  # a role change: nothing new
        c.execute("DELETE FROM agent_bridges WHERE agent_id=? AND (list_a=? OR list_b=?)", (uid, lid, lid))  # joins anew
        bad = bridge_conflicts(c, uid, lid, joining=True)
        if bad:
            found.append((uid, bad))
    else:
        circle = list_circle(c, lid)
        if uid in circle:
            return
        new = circle | {uid}
        o = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()
        members = ({o[0]} if o else set()) | {r[0] for r in c.execute("SELECT user_id FROM list_members WHERE list_id=?", (lid,))}
        for aid in sorted(members & ag):
            bad = bridge_conflicts(c, aid, lid, circle=new)
            if bad:
                found.append((aid, bad))
    if not found:
        return
    actor = me() if has_request_context() and getattr(g, "user", None) is not None else None
    person = actor and not is_agent(g.user)
    if has_request_context() and g.get("approved_job") and not person:
        # an agent's request a person approved (sharing waits for approval): that person approves the bridge too, if allowed
        j = c.execute("SELECT action_by FROM agent_jobs WHERE id=?", (g.approved_job,)).fetchone()
        by = j["action_by"] if j else None
        if by and all(may_approve_bridge(c, by, aid, [lid] + bad) for aid, bad in found):
            ts = iso(now_utc())
            for aid, bad in found:
                for l2 in bad:
                    x, y = _pair(lid, l2)
                    c.execute("INSERT OR REPLACE INTO agent_bridges(agent_id,list_a,list_b,by_id,at) VALUES(?,?,?,?,?)", (aid, x, y, by, ts))
            print("agent bridge approved with job", g.approved_job, "list", lid, "by", by, flush=True)
            return
        raise Denied(409, tr("This would connect lists with different people through an agent; only someone who manages all of them can approve it"))
    if ok and person and all(may_approve_bridge(c, actor, aid, [lid] + bad) for aid, bad in found):
        ts = iso(now_utc())
        for aid, bad in found:
            for l2 in bad:
                x, y = _pair(lid, l2)
                c.execute("INSERT OR REPLACE INTO agent_bridges(agent_id,list_a,list_b,by_id,at) VALUES(?,?,?,?,?)", (aid, x, y, actor, ts))
        print("agent bridge approved: agents", [a for a, _ in found], "list", lid, "by", actor, flush=True)
        return
    if ok and person:
        raise Denied(403, tr("Only someone who manages all these lists (or owns the agent) can connect them"))
    items, hidden = _names(c, sorted({x for _, bad in found for x in bad}), actor if person else None)
    from ..collab.comments import user_names
    nm = user_names(c, [a for a, _ in found])
    raise AgentBridge(items, hidden, [nm.get(a, "") for a, _ in found])


def bridge_blocks(c, lid, uid):
    """For the automatic ways in (share all, auto-share, shared folders, proposals): True when uid joining lid would create an
    unapproved bridge (the list is skipped)."""
    try:
        bridge_check(c, lid, uid, ok=False)
    except AgentBridge:
        return True
    return False


def agent_bridges_info(c, aid, viewer=None):
    """Every pair of lists agent aid connects although their people differ: [{lists: [{id, name}], approved, by, at}]."""
    from ..collab.comments import user_names
    ls = agent_reach(c, aid)
    circ = {x: list_circle(c, x) for x in ls}
    names = {r[0]: r[1] for r in c.execute(f"SELECT id, name FROM lists WHERE id IN ({','.join('?' * len(ls))})", ls)} if ls else {}
    out = []
    stored = {(r["list_a"], r["list_b"]): r for r in c.execute("SELECT * FROM agent_bridges WHERE agent_id=?", (aid,))}
    # an approval covers the same two circles of people in other lists too (a list with exactly the people of another one)
    same = {frozenset((circ[x], circ[y])): r for (x, y), r in stored.items() if x in circ and y in circ}
    for i, a in enumerate(ls):
        for b in ls[i + 1:]:
            if nested(circ[a], circ[b]):
                continue
            x, y = _pair(a, b)
            r = stored.get((x, y)) or same.get(frozenset((circ[a], circ[b])))
            out.append({"lists": [{"id": z, "name": names.get(z, "") if viewer is None or list_role(c, z, viewer) else None} for z in (x, y)],
                        "approved": bool(r), "by": r["by_id"] if r else None,
                        "by_name": user_names(c, [r["by_id"]]).get(r["by_id"], "") if r and r["by_id"] else "", "at": r["at"] if r else None})
    return out


# ---- least privilege: list restriction of an agent / a token
def list_ids_clean(c, v, may):
    """[ids] | csv | '' / None (= all) -> the stored csv. may(lid) -> bool: may this list be chosen."""
    if v in (None, "", []):
        return ""
    if isinstance(v, str):
        v = [x for x in v.split(",") if x.strip()]
    if not isinstance(v, list) or len(v) > LIST_IDS_MAX:
        raise BadInput(tr("Invalid value: {0}", "list_ids"))
    out = []
    for x in v:
        try:
            n = int(x)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "list_ids")) from None
        if isinstance(x, bool) or n <= 0 or not c.execute("SELECT 1 FROM lists WHERE id=?", (n,)).fetchone() or not may(n):
            raise BadInput(tr("Invalid value: {0}", "list_ids"))
        out.append(n)
    return ",".join(str(n) for n in sorted(set(out)))


def _open_pairs(c, aid):
    return {(b["lists"][0]["id"], b["lists"][1]["id"]) for b in agent_bridges_info(c, aid) if not b["approved"]}


def agent_lists_set(c, aid, v, ok=False):
    """agents.list_ids (and its tokens): only lists the agent is in. The caller checked who may change the agent. Widening the
    limit (or lifting it) must not switch on a bridge nobody approved: 409 agent_bridge, or with ok (bridge_ok from a person
    who may approve every pair) the approvals are stored."""
    reach = {r[0] for r in c.execute("SELECT id FROM lists WHERE owner_id=? OR id IN (SELECT list_id FROM list_members WHERE user_id=?)", (aid, aid))}
    csv_ = list_ids_clean(c, v, lambda n: n in reach)
    before = _open_pairs(c, aid)
    c.execute("UPDATE agents SET list_ids=? WHERE user_id=?", (csv_, aid))
    new = _open_pairs(c, aid) - before
    if new:
        from ..collab.comments import user_names
        actor = me()
        lids = sorted({x for p in new for x in p})
        if ok and may_approve_bridge(c, actor, aid, lids):
            for x, y in new:
                c.execute("INSERT OR REPLACE INTO agent_bridges(agent_id,list_a,list_b,by_id,at) VALUES(?,?,?,?,?)", (aid, x, y, actor, iso(now_utc())))
        elif ok:
            raise Denied(403, tr("Only someone who manages all these lists (or owns the agent) can connect them"))
        else:
            items, hidden = _names(c, lids, actor)
            raise AgentBridge(items, hidden, [user_names(c, [aid]).get(aid, "")])
    c.execute("UPDATE api_tokens SET list_ids=? WHERE user_id=?", (csv_, aid))
    print("agent", aid, "limited to lists", csv_ or "all", flush=True)
    return csv_


def list_ids_out(raw):
    return sorted(ids_parse(raw)) if str(raw or "").strip() else []


def token_list_add(c, lid):
    """A list created with a limited token belongs to that token (and agent) from then on."""
    if not has_request_context() or g.get("auth_via") != "token" or g.get("token") is None:
        return
    t = g.token
    raw = (t["list_ids"] if "list_ids" in t.keys() else "") or ""
    if not raw.strip():
        return
    new = ",".join(str(x) for x in sorted(ids_parse(raw) | {lid}))
    from ..agents.core import is_agent
    if is_agent(g.user):
        c.execute("UPDATE agents SET list_ids=? WHERE user_id=?", (new, g.user["id"]))
        c.execute("UPDATE api_tokens SET list_ids=? WHERE user_id=?", (new, g.user["id"]))
    else:
        c.execute("UPDATE api_tokens SET list_ids=? WHERE id=?", (new, t["id"]))
    g.token = c.execute("SELECT * FROM api_tokens WHERE id=?", (t["id"],)).fetchone()  # this request sees the list too
    g.pop("token_lists", None)


# ---- moving content across circles waits for a person (agents only)
def move_gate(c, moves):
    """moves: [(task id, target list id)] an agent's API request is about to do. Moving into a list whose people circle is
    not part of the source list's circle waits for approval (202, ApprovalPending)."""
    from ..agents.core import is_agent
    if not has_request_context() or g.get("auth_via") != "token" or not is_agent(g.user) or g.get("approved_job"):
        return
    cross = []
    for tid, dst in moves:
        r = c.execute("SELECT list_id, title FROM tasks WHERE id=?", (tid,)).fetchone()
        if not r or not dst or r["list_id"] == dst or not list_role(c, dst) or not list_role(c, r["list_id"]):
            continue  # nothing to move, or lists it cannot use: the normal checks answer (nothing is revealed here)
        if not list_circle(c, dst) <= list_circle(c, r["list_id"]):
            cross.append((tid, r["list_id"], dst, r["title"]))
    if not cross:
        return
    from ..api.scopes import need_approval
    dname = (c.execute("SELECT name FROM lists WHERE id=?", (cross[0][2],)).fetchone() or [""])[0]
    if len(cross) == 1:
        sname = (c.execute("SELECT name FROM lists WHERE id=?", (cross[0][1],)).fetchone() or [""])[0]
        need_approval(c, N_("Move the task “{0}” from “{1}” to “{2}”: other people see it there"), (cross[0][3][:80], sname, dname),
                      list_id=cross[0][1], task_id=cross[0][0])
    need_approval(c, N_("Move {0} tasks to “{1}”: other people see them there"), (len(cross), dname), list_id=cross[0][1])


# ---- the access log
_ACC = {"rows": {}, "lock": threading.Lock(), "thread": None, "clean_at": 0.0}
_ACC_EVT = threading.Event()


def access_events(data):
    """The lists of the events an agent just fetched (they carry tasks, comments, chat of those lists): read access."""
    from ..core.access import access_note
    for ev in data or []:
        d = ev.get("data") if isinstance(ev, dict) else None
        if isinstance(d, dict):
            lid = d.get("list_id") or (d.get("task") or {}).get("list_id") or (d.get("list") or {}).get("id") or (d.get("room") or {}).get("list_id")
            if isinstance(lid, int):
                access_note(lid)


@app.after_request
def access_after(resp):
    acc = g.get("agent_access")
    aid = g.get("audit_aid")
    if not acc or not aid or not (200 <= resp.status_code < 300) or resp.status_code == 202:
        return resp
    try:
        day = local_now().date().isoformat()
        wr = request.method not in ("GET", "HEAD", "OPTIONS")
        with _ACC["lock"]:
            for lid in acc:
                k = (aid, int(lid), day, "write" if wr else "read")  # a change request wrote to the lists it touched
                _ACC["rows"][k] = _ACC["rows"].get(k, 0) + 1
            n = len(_ACC["rows"])
            if _ACC["thread"] is None:
                _ACC["thread"] = threading.Thread(target=_access_loop, daemon=True)
                _ACC["thread"].start()
        if n >= 200:
            _ACC_EVT.set()
    except Exception as e:  # noqa: BLE001  the log must never break a request
        print("access log error:", type(e).__name__, e, flush=True)
    return resp


def access_flush(c=None):
    with _ACC["lock"]:
        rows, _ACC["rows"] = _ACC["rows"], {}
    if not rows:
        return 0
    own = c is None
    c = connect() if own else c
    try:
        c.executemany("""INSERT INTO agent_list_access(agent_id,list_id,day,kind,n) SELECT ?,?,?,?,? WHERE EXISTS(SELECT 1 FROM lists WHERE id=?)
                         ON CONFLICT(list_id,day,agent_id,kind) DO UPDATE SET n=n+excluded.n""",
                      [(a, l, d, k, n, l) for (a, l, d, k), n in rows.items()])
        c.commit()
    finally:
        if own:
            c.close()
    return len(rows)


def _access_loop():
    while True:
        _ACC_EVT.wait(10)
        _ACC_EVT.clear()
        try:
            with GATE.bg():
                access_flush()
                if time.time() - _ACC["clean_at"] > 3600:
                    _ACC["clean_at"] = time.time()
                    c = connect()
                    try:
                        c.execute("DELETE FROM agent_list_access WHERE day<?", ((local_now().date() - timedelta(days=AGENT_ACCESS_DAYS)).isoformat(),))
                        c.commit()
                    finally:
                        c.close()
        except Exception as e:  # noqa: BLE001
            print("access log writer error:", type(e).__name__, e, flush=True)
            time.sleep(5)


@app.get("/api/lists/<int:lid>/agent-access")
def list_agent_access(lid):
    """Which agents read / wrote list lid in the last AGENT_ACCESS_DAYS days, per day (every member of the list sees it)."""
    from ..collab.comments import user_names
    c = db()
    need_list(c, lid, write=False)
    access_flush()
    first = (local_now().date() - timedelta(days=AGENT_ACCESS_DAYS - 1)).isoformat()
    rows = c.execute("""SELECT agent_id, day, SUM(CASE WHEN kind='read' THEN n ELSE 0 END) AS r, SUM(CASE WHEN kind='write' THEN n ELSE 0 END) AS w
                        FROM agent_list_access WHERE list_id=? AND day>=? GROUP BY agent_id, day ORDER BY day DESC, agent_id""", (lid, first)).fetchall()
    nm = user_names(c, sorted({r["agent_id"] for r in rows}))
    return jsonify(days=AGENT_ACCESS_DAYS, data=[{"agent_id": r["agent_id"], "name": nm.get(r["agent_id"], ""), "day": r["day"],
                                                  "read": r["r"], "write": r["w"]} for r in rows])


@app.get("/api/agents/<int:aid>/bridges")
def agent_bridges_get(aid):
    """The lists agent aid connects although their people differ (approved or from before), for the people who reach it."""
    from ..agents.core import agent_row, agent_shares, is_agent
    c = db()
    shared = c.execute("""SELECT 1 FROM list_members m WHERE m.user_id=? AND m.list_id IN (SELECT id FROM lists WHERE owner_id=? UNION
                          SELECT list_id FROM list_members WHERE user_id=?) LIMIT 1""", (aid, me(), me())).fetchone()
    from ..accounts.users import admin_sees
    a = agent_row(c, aid)
    if not a or is_agent(g.user) or (a["owner_id"] and a["owner_id"] != me()):
        raise Denied(404)  # somebody else's personal agent: nothing (also not for admins)
    full = bool(g.user["is_admin"]) and admin_sees(c, aid)
    if not (shared or agent_shares(c, aid, me()) or full):
        raise Denied(404)
    return jsonify(bridges=agent_bridges_info(c, aid, None if full else me()))
