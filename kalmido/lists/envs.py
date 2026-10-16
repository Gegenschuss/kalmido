"""2.60.0 D (#1514): environments of a project list (Staging, Live, ...) and which milestone / version runs where since when.

A deployment is set by hand (the milestone's "Put on ..."), by the token API (set_deployment) or by a deploy webhook:
POST /api/hooks/deploy/<environment id>/<token> {"version": "2.60.0"}. The token is shown once and stored only as its SHA-256
(like the error-report hook); the version finds the milestone by its title (exact, or with / without a leading "v", or as a
word of the title). A version without a milestone is stored too. Optional per environment: "close tasks on arrival" completes
the open tasks of the milestone that reaches it (each one can be reopened as usual). Agents with list access hear `deployed`."""
import hashlib
import hmac
import re
import secrets
from flask import g, jsonify, request

from ..core.config import app, PUBLIC_URL
from ..core.pg import insert_id, system_ctx
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import acx_anon_bind, Denied, MANAGE_ROLES, need_list
from ..tasks.validation import log_act
from ..tasks.lifecycle import do_complete
from ..personal.timetrack import UnknownFields, web_fields
from ..agents.core import agent_emit, is_agent, list_agents
from ..api.v1 import v1_args, v1_call, v1_json, v1_view
from .projects import need_overview

ENV_MAX = 8            # environments per list
ENV_NAME_MAX = 40
ENV_VERSION_MAX = 100
ENV_SUGGEST = (N_("Staging"), N_("Live"))  # offered for a software project, never created unasked
ENV_SOURCES = ("manual", "api", "hook")
ENV_RATE_S = 2         # s between two webhook calls per environment (a deploy script, not a flood)
_ENV_LAST = {}


def env_row(c, eid, write=False, manage=False, trashed=False):
    """The environment row; 404 when the list is not visible, 403 without write right (manage: owner / list admin, no agents)."""
    r = c.execute("SELECT * FROM list_envs WHERE id=?", (eid,)).fetchone()
    if not r or (bool(r["deleted_at"]) != trashed):
        raise Denied(404)
    need_overview(c, r["list_id"], write=write or manage)
    if manage:
        if is_agent(g.user):
            raise Denied(403, tr("Agents cannot connect repositories"))
        need_list(c, r["list_id"], write=False, manage=True)
    return r


def env_norm(s):
    s = re.sub(r"\s+", " ", str(s or "")).strip().lower()
    return s[1:] if re.match(r"^v\d", s) else s


def env_find_ms(c, lid, version):
    """The milestone task of the list that a version belongs to (title equals it, or has it as a word; "v2.60" = "2.60")."""
    v = env_norm(version)
    if not v:
        return None
    rows = c.execute("SELECT id, title FROM tasks WHERE list_id=? AND ms=1 AND deleted_at IS NULL ORDER BY id DESC", (lid,)).fetchall()
    for r in rows:
        if env_norm(r["title"]) == v:
            return r["id"]
    for r in rows:
        if v in {env_norm(w) for w in re.split(r"[\s,;()]+", r["title"] or "") if w}:
            return r["id"]
    return None


def env_current(c, eids):
    """{env id: its latest deployment (with the milestone's title)}."""
    if not eids:
        return {}
    q = ",".join("?" * len(eids))
    out = {}
    for r in c.execute(f"""SELECT d.*, t.title AS ms_title FROM env_deploys d LEFT JOIN tasks t ON t.id=d.milestone_id AND t.deleted_at IS NULL
                           WHERE d.env_id IN ({q}) AND d.id=(SELECT MAX(x.id) FROM env_deploys x WHERE x.env_id=d.env_id)""", eids):
        out[r["env_id"]] = {"id": r["id"], "version": r["version"], "at": r["at"], "milestone_id": r["milestone_id"],
                            "milestone": r["ms_title"], "by_id": r["by_id"], "source": r["source"]}
    return out


def env_dict(r, cur, manage=False):
    d = {"id": r["id"], "list_id": r["list_id"], "name": r["name"], "sort": r["sort"], "auto_close": bool(r["auto_close"]),
         "current": cur}
    if manage:
        d["hook"] = bool(r["token_hash"])
    return d


def env_list(c, lid, manage=False):
    rows = c.execute("SELECT * FROM list_envs WHERE list_id=? AND deleted_at IS NULL ORDER BY sort, id", (lid,)).fetchall()
    cur = env_current(c, [r["id"] for r in rows])
    return [env_dict(r, cur.get(r["id"]), manage) for r in rows]


def env_for_lists(c, lids):
    """{milestone id: [{name, since, version}]} over the given lists: where each milestone runs NOW (its deployment is the
    environment's latest one)."""
    out = {}
    if not lids:
        return out
    for r in c.execute(f"""SELECT e.name, d.milestone_id, d.at, d.version FROM list_envs e
                           JOIN env_deploys d ON d.id=(SELECT MAX(x.id) FROM env_deploys x WHERE x.env_id=e.id)
                           WHERE e.deleted_at IS NULL AND e.list_id IN ({",".join("?" * len(lids))}) AND d.milestone_id IS NOT NULL ORDER BY e.sort, e.id""", list(lids)):
        out.setdefault(r["milestone_id"], []).append({"name": r["name"], "since": r["at"], "version": r["version"]})
    return out


def env_for_milestones(c, lid, ids):
    envs = env_for_lists(c, [lid])
    return {m: envs[m] for m in ids if m in envs}


def env_clean_name(v):
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    if not s or len(s) > ENV_NAME_MAX:
        raise Denied(400, tr("Invalid value: {0}", "name"))
    return s


def env_may_manage(c, lid):
    return not is_agent(g.user) and (need_list(c, lid, write=False) in MANAGE_ROLES)


# ---- the one place a deployment is recorded
def env_deploy(c, e, version="", milestone_id=None, source="manual", uid=None):
    """Records that `version` / the milestone runs in environment e now; the caller commits. Returns the deployment dict."""
    lid = e["list_id"]
    version = str(version or "").strip()[:ENV_VERSION_MAX]
    ms = None
    if milestone_id:
        ms = c.execute("SELECT id, title FROM tasks WHERE id=? AND list_id=? AND ms=1 AND deleted_at IS NULL", (milestone_id, lid)).fetchone()
        if not ms:
            raise Denied(404, tr("Not a milestone"))
    elif version:
        mid = env_find_ms(c, lid, version)
        ms = c.execute("SELECT id, title FROM tasks WHERE id=?", (mid,)).fetchone() if mid else None
    if not version and ms:
        version = (ms["title"] or "")[:ENV_VERSION_MAX]
    if not version and not ms:
        raise Denied(400, tr("Invalid value: {0}", "version"))
    ts = iso(now_utc())
    did = insert_id(c, "INSERT INTO env_deploys(env_id,list_id,milestone_id,version,at,by_id,source) VALUES(?,?,?,?,?,?,?)",
                    (e["id"], lid, ms["id"] if ms else None, version, ts, uid, source))
    closed = []
    if ms and e["auto_close"]:
        closed = env_close_tasks(c, ms["id"], e["name"], uid)
    bump(c)
    out = {"id": did, "env_id": e["id"], "env": e["name"], "version": version, "at": ts, "source": source,
           "milestone_id": ms["id"] if ms else None, "milestone": ms["title"] if ms else None, "closed": closed}
    env_event(c, lid, out)
    return out


def env_close_tasks(c, mid, env_name, uid):
    """The open tasks of milestone mid are completed ("close tasks on arrival"); each can be reopened as usual."""
    ids = [r["id"] for r in c.execute("SELECT id FROM tasks WHERE milestone_id=? AND status=0 AND deleted_at IS NULL ORDER BY id", (mid,))]
    done = []
    prev = g.get("user")
    from ..tasks.review import rvw_gate
    for tid in ids:
        if rvw_gate(c, tid):  # 2.60.0 (#1514 + #1512): a task still waiting for its approval stays open
            continue
        if not g.get("user"):
            g.user = {"id": None, "display_name": "", "username": "", "kind": "person"}  # a hook: nobody's completion
        try:
            do_complete(c, tid, 2, {})
        finally:
            g.user = prev
        log_act(c, tid, "env_done", {"env": env_name, "milestone_id": mid}, uid=uid)
        done.append(tid)
    return done


def env_event(c, lid, dep):
    """Agents with access to the list hear `deployed` (agent_emit keeps list limits, health lists and paused agents out)."""
    data = {"list_id": lid, "environment": {"id": dep["env_id"], "name": dep["env"]}, "version": dep["version"],
            "milestone": {"id": dep["milestone_id"], "title": dep["milestone"]} if dep["milestone_id"] else None,
            "source": dep["source"], "at": dep["at"], "closed_task_ids": dep["closed"]}
    for aid in list_agents(c, lid):
        agent_emit(c, aid, "deployed", data)


# ---- web routes
@app.get("/api/lists/<int:lid>/envs")
def env_get(lid):
    c = db()
    need_overview(c, lid)
    ptype = c.execute("SELECT ptype FROM lists WHERE id=?", (lid,)).fetchone()["ptype"]
    return jsonify(envs=env_list(c, lid, env_may_manage(c, lid)), manage=env_may_manage(c, lid), max=ENV_MAX,
                   suggest=[tr(n) for n in ENV_SUGGEST] if ptype == "software" else [])


@app.post("/api/lists/<int:lid>/envs")
def env_add(lid):
    c = db()
    need_overview(c, lid, write=True)
    b = web_fields(body(), {"name", "auto_close"}, "POST /api/lists/{lid}/envs")
    name = env_clean_name(b.get("name"))
    rows = c.execute("SELECT name FROM list_envs WHERE list_id=? AND deleted_at IS NULL", (lid,)).fetchall()
    if len(rows) >= ENV_MAX:
        return err(tr("At most {0} environments", ENV_MAX), 409)
    if name.lower() in {r["name"].lower() for r in rows}:
        return err(tr("This name is taken"), 409)
    sort = c.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM list_envs WHERE list_id=?", (lid,)).fetchone()[0]
    eid = insert_id(c, "INSERT INTO list_envs(list_id,name,sort,auto_close,created_at) VALUES(?,?,?,?,?)",
                    (lid, name, sort, 1 if b.get("auto_close") else 0, iso(now_utc())))
    bump(c)
    c.commit()
    return jsonify(env_dict(c.execute("SELECT * FROM list_envs WHERE id=?", (eid,)).fetchone(), None, True)), 201


@app.patch("/api/envs/<int:eid>")
def env_update(eid):
    """{name?, auto_close?, hook?: on | rotate | off}. The webhook token is shown once (owner / list admins, never an agent)."""
    c = db()
    b = web_fields(body(), {"name", "auto_close", "hook"}, "PATCH /api/envs/{id}")
    e = env_row(c, eid, write=True, manage="hook" in b)
    out = {}
    if "name" in b:
        name = env_clean_name(b["name"])
        if c.execute("SELECT 1 FROM list_envs WHERE list_id=? AND id!=? AND deleted_at IS NULL AND lower(name)=lower(?)", (e["list_id"], eid, name)).fetchone():
            return err(tr("This name is taken"), 409)
        c.execute("UPDATE list_envs SET name=? WHERE id=?", (name, eid))
    if "auto_close" in b:
        c.execute("UPDATE list_envs SET auto_close=? WHERE id=?", (1 if b["auto_close"] else 0, eid))
    if "hook" in b:
        if b["hook"] not in ("on", "rotate", "off"):
            return err(tr("Invalid value: {0}", "hook"))
        if b["hook"] == "off":
            c.execute("UPDATE list_envs SET token_hash='' WHERE id=?", (eid,))
        else:
            tok = secrets.token_urlsafe(32)
            c.execute("UPDATE list_envs SET token_hash=? WHERE id=?", (hashlib.sha256(tok.encode()).hexdigest(), eid))
            out["url"] = f"{PUBLIC_URL.rstrip('/')}/api/hooks/deploy/{eid}/{tok}"  # the only time it is shown
    bump(c)
    c.commit()
    r = c.execute("SELECT * FROM list_envs WHERE id=?", (eid,)).fetchone()
    return jsonify({**env_dict(r, env_current(c, [eid]).get(eid), env_may_manage(c, e["list_id"])), **out})


@app.delete("/api/envs/<int:eid>")
def env_delete(eid):
    c = db()
    e = env_row(c, eid, write=True)
    c.execute("UPDATE list_envs SET deleted_at=?, token_hash='' WHERE id=?", (iso(now_utc()), eid))  # the webhook stops; Undo restores the rest
    bump(c)
    c.commit()
    return jsonify(ok=True, list_id=e["list_id"])


@app.post("/api/envs/<int:eid>/restore")
def env_restore(eid):
    """Undo of a delete: the environment is back with its history (the webhook stays off until a person switches it on)."""
    c = db()
    e = env_row(c, eid, write=True, trashed=True)
    if c.execute("SELECT 1 FROM list_envs WHERE list_id=? AND deleted_at IS NULL AND lower(name)=lower(?)", (e["list_id"], e["name"])).fetchone():
        return err(tr("This name is taken"), 409)
    c.execute("UPDATE list_envs SET deleted_at=NULL WHERE id=?", (eid,))
    bump(c)
    c.commit()
    return jsonify(env_dict(c.execute("SELECT * FROM list_envs WHERE id=?", (eid,)).fetchone(), env_current(c, [eid]).get(eid), True))


@app.delete("/api/envs/<int:eid>/deploys/<int:did>")
def env_deploy_undo(eid, did):
    """Undo of a deployment: only the latest one of the environment can be taken back (completed tasks stay as they are)."""
    c = db()
    env_row(c, eid, write=True)
    r = c.execute("SELECT MAX(id) FROM env_deploys WHERE env_id=?", (eid,)).fetchone()
    if not r or r[0] != did:
        return err(tr("Changed in the meantime, nothing to undo"), 409)
    c.execute("DELETE FROM env_deploys WHERE id=?", (did,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/envs/<int:eid>/deploy")
def env_deploy_route(eid):
    """{milestone_id?, version?}: this milestone / version runs in the environment now."""
    c = db()
    e = env_row(c, eid, write=True)
    b = web_fields(body(), {"milestone_id", "version"}, "POST /api/envs/{id}/deploy")
    mid = b.get("milestone_id")
    if mid is not None and (not isinstance(mid, int) or isinstance(mid, bool)):
        return err(tr("Invalid value: {0}", "milestone_id"))
    out = env_deploy(c, e, b.get("version"), mid, "api" if g.get("auth_via") == "token" else "manual", me())
    c.commit()
    return jsonify(out), 201


# ---- the deploy webhook: the secret token in the URL is the credential (session.py lets the path through unauthenticated)
@app.post("/api/hooks/deploy/<int:eid>/<token>")
def env_hook(eid, token):
    c = db()
    with system_ctx(c):  # resolve the token (one row) across organisations ...
        r = c.execute("SELECT e.*, l.org_id, l.archived FROM list_envs e JOIN lists l ON l.id=e.list_id WHERE e.id=? AND e.deleted_at IS NULL", (eid,)).fetchone()
    if not r or not r["token_hash"] or len(token) > 200 or not hmac.compare_digest(r["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
        return err(tr("unknown"), 403)
    acx_anon_bind(c, r["org_id"])  # ... then write inside exactly the list's organisation
    import time
    now = time.time()
    if now - _ENV_LAST.get(eid, 0) < ENV_RATE_S:
        return err(tr("Too many attempts, please wait a few minutes"), 429)
    _ENV_LAST[eid] = now
    if len(_ENV_LAST) > 5000:
        _ENV_LAST.clear()
    if (request.content_length or 0) > 8192:
        return err(tr("The report is too large (at most {0} KB)", 8), 413)
    b = request.get_json(silent=True)
    v = b.get("version") if isinstance(b, dict) else None
    if not isinstance(v, str) or not v.strip():
        return err(tr("Invalid value: {0}", "version"))
    g.user = None
    out = env_deploy(c, r, v, None, "hook", None)
    c.commit()
    return jsonify(ok=True, milestone_id=out["milestone_id"], closed=len(out["closed"])), 201


# ---- the token API (agents may read and set deployments with list access; tokens and the webhook stay with people)
@app.get("/api/v1/lists/<int:lid>/environments")
@v1_view
def v1_env_get(lid):
    v1_args(())
    c = db()
    need_overview(c, lid)
    return jsonify(data=env_list(c, lid), next_cursor=None)


@app.post("/api/v1/lists/<int:lid>/deployments")
@v1_view
def v1_env_deploy(lid):
    """{environment: id or name, version?, milestone_id?} -> the deployment."""
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("environment", "version", "milestone_id"))
    if unknown:
        raise UnknownFields(unknown)
    c = db()
    need_overview(c, lid, write=True)
    ref = b.get("environment")
    if isinstance(ref, int) and not isinstance(ref, bool):
        e = c.execute("SELECT * FROM list_envs WHERE id=? AND list_id=? AND deleted_at IS NULL", (ref, lid)).fetchone()
    else:
        e = c.execute("SELECT * FROM list_envs WHERE list_id=? AND deleted_at IS NULL AND lower(name)=lower(?)", (lid, str(ref or ""))).fetchone()
    if not e:
        raise Denied(404, tr("unknown"))
    mid = b.get("milestone_id")
    if mid is not None and (not isinstance(mid, int) or isinstance(mid, bool)):
        raise Denied(400, tr("Invalid value: {0}", "milestone_id"))
    out = env_deploy(c, e, b.get("version"), mid, "api", me())
    c.commit()
    return jsonify(out), 201


def env_spec(paths, schemas, op, ok, errs, ref, pid):
    """2.60.0 D (#1514) additions to the OpenAPI document."""
    lp = pid("id", "List id (a project list)")
    cur = {"type": "object", "properties": {"id": {"type": "integer"}, "version": {"type": "string"}, "at": {"type": "string"},
                                             "milestone_id": {"type": ["integer", "null"]}, "milestone": {"type": ["string", "null"]},
                                             "source": {"type": "string", "enum": list(ENV_SOURCES)}}}
    schemas["Environment"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "list_id": {"type": "integer"}, "name": {"type": "string"}, "sort": {"type": "integer"},
        "auto_close": {"type": "boolean", "description": "a milestone that reaches the environment completes its open tasks"},
        "current": {"oneOf": [cur, {"type": "null"}], "description": "the latest deployment"}}}
    schemas["EnvironmentPage"] = {"type": "object", "required": ["data", "next_cursor"], "properties": {
        "data": {"type": "array", "items": ref("Environment")}, "next_cursor": {"type": ["string", "null"]}}}
    schemas["Deployment"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "env_id": {"type": "integer"}, "env": {"type": "string"}, "version": {"type": "string"},
        "at": {"type": "string"}, "source": {"type": "string"}, "milestone_id": {"type": ["integer", "null"]},
        "milestone": {"type": ["string", "null"]}, "closed": {"type": "array", "items": {"type": "integer"}}}}
    paths.update({
        "/lists/{id}/environments": {"get": op("Environments of a project list (Staging, Live, ...) with the latest deployment of each",
                                               "Lists", ok(ref("EnvironmentPage")) | errs("404", "409"), [lp])},
        "/lists/{id}/deployments": {"post": op(
            "Record that a version / milestone runs in an environment now (the milestone is found by `version` when `milestone_id` is "
            "missing); with 'close tasks on arrival' on, the milestone's open tasks are completed", "Lists",
            ok(ref("Deployment"), "Created", "201") | errs("400", "403", "404", "409"), [lp], scope="write",
            body={"type": "object", "required": ["environment"], "properties": {
                "environment": {"description": "environment id or name", "oneOf": [{"type": "integer"}, {"type": "string"}]},
                "version": {"type": "string", "maxLength": ENV_VERSION_MAX}, "milestone_id": {"type": "integer"}}})},
    })
