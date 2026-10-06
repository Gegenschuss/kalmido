"""Agent administration and personal agents."""
import json
import secrets
from datetime import timedelta
from flask import g, jsonify

from ..core.config import app, TZ, USERNAME_RE
from ..core.i18n import tr, trn
from ..core.db import body, bump, create_user, db, ensure_inbox, err, gset, gsetting, iso, now_utc, uset, usettings
from ..accounts.session import _token_hash, me
from ..accounts.pictures import avatar_drop_file, AVATAR_PRESETS
from ..accounts.login import seal, unseal
from ..core.access import Denied
from ..core.serializers import unlink_files
from ..core.state import visible_lists
from ..lists.ownership import owner_transfer
from ..tasks.validation import as_int
from ..integrations.paperless import pl_forget_user
from ..collab.comments import user_names
from ..personal.timetrack import BadInput
from ..accounts.users import avatar_upload, need_admin, user_purge
from ..api.v1 import API_ON, need_api, SCOPES, SCOPES_AGENT_DEFAULT, SCOPES_AGENT_NEVER, token_public, WH_ON
from ..integrations.webhooks import need_wh, wh_allow, wh_err_text, wh_log, wh_public, wh_send, wh_url_check
from ..agents.core import (
    agent_active, agent_emit, AGENT_EVENTS, AGENT_NOTE_MAX, agent_public, agent_row, agent_runtime, is_agent,
    runtime_clean, RUNTIME_DEFAULTS,
)


# ---- agents: admin (Settings > Users > Agents)
def agent_admin_dict(c, a):
    from ..agents.proposals import prop_mode
    from ..agents.usage import usage_limits, usage_state
    from ..api.scopes import agent_scope_dict
    last = c.execute("SELECT MAX(created_at) FROM agent_events WHERE agent_id=?", (a["user_id"],)).fetchone()[0]
    w = c.execute("SELECT * FROM webhooks WHERE id=?", (a["webhook_id"],)).fetchone() if a["webhook_id"] else None
    return {**agent_public(c, a), "enabled": bool(a["enabled"]), "disabled": bool(a["disabled"]), "note": a["note"] or "",
            "provider": a["provider"] if "provider" in a.keys() else "",  # 2.24.0 (#896): where it runs (shown when it joins a list)
            "created_at": a["created_at"], "last_event_at": last,
            "tokens": [token_public(r) for r in c.execute("SELECT * FROM api_tokens WHERE user_id=? ORDER BY id DESC", (a["user_id"],))],
            "webhook": wh_public(c, w) if w else None,
            "limits": usage_limits(a), "usage": usage_state(c, a),  # 2.1.1 (#326)
            "proposals": prop_mode(a),  # 2.3.0: off | shared | all
            "runtime": agent_runtime(a),  # 2.4.1 (#377)
            "owner": ({"id": a["owner_id"], "name": user_names(c, [a["owner_id"]]).get(a["owner_id"], "")} if a["owner_id"] else None),  # 2.7.2 (#420)
            "admin_paused": bool(a["admin_paused"]),
            **agent_scope_dict(c, a),  # 2.15.0 (#479): scopes, effective_scopes, allowed_ips
            "lists": [{"id": d["id"], "name": d["name"], "role": d["role"]} for d in visible_lists(c, a["user_id"]) if not d["is_inbox"]]}


def need_agent_admin(c, aid):
    need_admin()
    a = agent_row(c, aid)
    if not a:
        raise Denied(404)
    return a


def agent_token_new(c, aid, days=None):
    """2.15.0 (#479): the token gets the agent's scopes + address restriction; days = expiry (None = never)."""
    a = agent_row(c, aid)
    exp = iso(now_utc() + timedelta(days=as_int(days, tr("Expiry"), 1, 3650))) if days not in (None, "", 0) else None
    tok = "abk_" + secrets.token_urlsafe(32)
    c.execute("INSERT INTO api_tokens(user_id,name,token_hash,prefix,scopes,expires_at,created_at,allowed_ips) VALUES(?,?,?,?,?,?,?,?)",
              (aid, "Agent", _token_hash(tok), tok[:12], (a["scopes"] if a and a["scopes"] else ",".join(SCOPES_AGENT_DEFAULT)), exp,
               iso(now_utc()), (a["allowed_ips"] if a else "") or ""))
    return tok


def agent_hook_set(c, aid, url):
    """Creates / changes / removes (url '') the agent's webhook row; returns a new secret when one was created."""
    a = agent_row(c, aid)
    if not url:
        if a["webhook_id"]:
            c.execute("DELETE FROM webhooks WHERE id=?", (a["webhook_id"],))
            c.execute("UPDATE agents SET webhook_id=NULL WHERE user_id=?", (aid,))
        return None
    need_wh()
    url = wh_url_check(c, url)
    ts = iso(now_utc())
    if a["webhook_id"] and c.execute("SELECT 1 FROM webhooks WHERE id=?", (a["webhook_id"],)).fetchone():
        c.execute("UPDATE webhooks SET url=?, updated_at=? WHERE id=?", (url, ts, a["webhook_id"]))
        return None
    secret = "whsec_" + secrets.token_urlsafe(32)
    wid = c.execute("""INSERT INTO webhooks(user_id,name,url,events,secret,enabled,created_at,updated_at,agent)
                       VALUES(?,?,?,?,'',?,?,?,1)""", (aid, "Agent", url, ",".join(AGENT_EVENTS), 1 if a["enabled"] else 0, ts, ts)).lastrowid
    c.execute("UPDATE webhooks SET secret=? WHERE id=?", (seal(c, f"webhook:{wid}", secret), wid))
    c.execute("UPDATE agents SET webhook_id=? WHERE user_id=?", (wid, aid))
    return secret


def agent_enable(c, aid, on):
    c.execute("UPDATE agents SET enabled=? WHERE user_id=?", (1 if on else 0, aid))
    a = agent_row(c, aid)
    if a["webhook_id"]:
        if on:
            c.execute("UPDATE webhooks SET enabled=1, disabled_reason='', updated_at=? WHERE id=?", (iso(now_utc()), a["webhook_id"]))
        else:
            c.execute("UPDATE webhooks SET enabled=0, updated_at=? WHERE id=?", (iso(now_utc()), a["webhook_id"]))
            c.execute("DELETE FROM webhook_queue WHERE webhook_id=?", (a["webhook_id"],))
    if not on:
        c.execute("UPDATE agents SET status='idle', status_text='', status_at=?, status_task=NULL WHERE user_id=?", (iso(now_utc()), aid))


def make_agent(c, uid):
    """users row uid becomes an agent (never admin, no Paperless, no web sessions); its tokens and lists stay."""
    c.execute("UPDATE users SET kind='agent', is_admin=0, paperless_access=0 WHERE id=?", (uid,))
    pl_forget_user(c, uid)  # 2.1.0: an agent has no Paperless (personal connections, tokens, grants go)
    c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    c.execute("UPDATE list_members SET role='edit', own_role='edit' WHERE user_id=? AND role='admin'", (uid,))
    c.execute("DELETE FROM group_members WHERE user_id=?", (uid,))  # 2.10.0 (#441): agents are never group members
    c.execute("INSERT OR IGNORE INTO agents(user_id,enabled,status,created_at) VALUES(?,1,'idle',?)", (uid, iso(now_utc())))


@app.get("/api/admin/agents")
def admin_agents():
    from ..api.scopes import scopes_offer
    need_admin()
    c = db()
    rows = c.execute("""SELECT a.*, u.username, u.display_name, u.avatar, u.disabled FROM agents a JOIN users u ON u.id=a.user_id
                        WHERE u.kind='agent' ORDER BY u.id""").fetchall()
    return jsonify(agents=[agent_admin_dict(c, a) for a in rows], events=list(AGENT_EVENTS), webhooks=WH_ON, api=API_ON,
                   scopes=scopes_offer(c, g.user, agent=True), default_scopes=list(SCOPES_AGENT_DEFAULT))  # 2.15.0 (#479)


@app.post("/api/admin/agents")
def admin_agent_create():
    """{username, display_name?, note?, webhook_url?, avatar_preset?} -> the agent + its API token (and the webhook's signing
    secret) -- both shown this once."""
    from ..agents.proposals import PROP_MODES
    from ..api.scopes import agent_scopes_set
    need_admin()
    need_api()
    b, c = body(), db()
    username = (b.get("username") or "").strip().lower()
    if not USERNAME_RE.fullmatch(username):
        return err(tr("Username: 1-32 characters a-z, 0-9, dot, dash, underscore"))
    if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        return err(tr("Username already exists"), 409)
    uid = create_user(c, username, (b.get("display_name") or "").strip()[:60] or username, None, None, False, paperless_access=False)
    make_agent(c, uid)
    c.execute("UPDATE agents SET note=?, provider=? WHERE user_id=?", (str(b.get("note") or "")[:AGENT_NOTE_MAX], str(b.get("provider") or "").strip()[:80], uid))
    try:  # 2.15.0 (#479): scopes (default read + tasks:write + comments) and the address restriction
        agent_scopes_set(c, uid, {"scopes": b.get("scopes") or list(SCOPES_AGENT_DEFAULT), **({"allowed_ips": b["allowed_ips"]} if "allowed_ips" in b else {})})
    except BadInput:
        c.rollback()
        raise
    if b.get("proposals") in PROP_MODES:  # 2.3.0
        c.execute("UPDATE agents SET proposals=? WHERE user_id=?", (b["proposals"], uid))
    if b.get("runtime") is not None:  # 2.4.1 (#377)
        try:
            c.execute("UPDATE agents SET runtime=? WHERE user_id=?", (json.dumps(runtime_clean(dict(RUNTIME_DEFAULTS), b["runtime"])), uid))
        except BadInput:
            c.rollback()
            raise
    p = b.get("avatar_preset", "robot")
    if p in AVATAR_PRESETS:
        c.execute("UPDATE users SET avatar=? WHERE id=?", (f"p:{p}", uid))
    uset(c, uid, "lang", usettings(c, me())["lang"])
    ensure_inbox(c, uid)
    try:
        secret = agent_hook_set(c, uid, str(b.get("webhook_url") or "").strip())
    except (BadInput, Denied):
        c.rollback()
        raise
    tok = agent_token_new(c, uid)
    bump(c)
    c.commit()
    print("agent", username, "(id", uid, ") created by", g.user["username"], flush=True)
    return jsonify({**agent_admin_dict(c, agent_row(c, uid)), "token": tok, "webhook_secret": secret}), 201


@app.patch("/api/admin/agents/<int:aid>")
def admin_agent_update(aid):
    """{display_name?, note?, enabled?, webhook_url? ('' removes it), limits? (2.1.1: {period, metric, soft?, hard?}, null = none),
    username? / avatar_preset? (2.1.2 #346: a preset or null = initials; an own photo: POST .../avatar)}"""
    from ..agents.proposals import PROP_MODES
    from ..agents.usage import usage_limits_clean
    from ..api.scopes import agent_scopes_set
    c = db()
    a0 = need_agent_admin(c, aid)
    b = body()
    secret = None
    if "username" in b:
        username = str(b["username"] or "").strip().lower()
        if not USERNAME_RE.fullmatch(username):
            return err(tr("Username: 1-32 characters a-z, 0-9, dot, dash, underscore"))
        if c.execute("SELECT 1 FROM users WHERE username=? AND id!=?", (username, aid)).fetchone():
            return err(tr("Username already exists"), 409)
        if username != a0["username"]:
            c.execute("UPDATE users SET username=? WHERE id=?", (username, aid))
            print("agent", aid, "renamed", a0["username"], "->", username, "by", g.user["username"], flush=True)
    old_avatar = None
    if "avatar_preset" in b:
        p = b["avatar_preset"]
        if p is not None and p not in AVATAR_PRESETS:
            c.rollback()
            return err(tr("Invalid value: {0}", "avatar_preset"))
        old_avatar = c.execute("SELECT avatar FROM users WHERE id=?", (aid,)).fetchone()[0]
        c.execute("UPDATE users SET avatar=? WHERE id=?", (f"p:{p}" if p else None, aid))
    if "limits" in b:
        lim = usage_limits_clean(b["limits"])
        c.execute("UPDATE agents SET usage_limits=?, usage_alerted='' WHERE user_id=?", (lim, aid))
        print("agent", aid, "usage limits", lim or "none", "by", g.user["username"], flush=True)
    if "display_name" in b:
        c.execute("UPDATE users SET display_name=? WHERE id=?", ((b["display_name"] or "").strip()[:60] or
                                                                agent_row(c, aid)["username"], aid))
    if "note" in b:
        c.execute("UPDATE agents SET note=? WHERE user_id=?", (str(b["note"] or "")[:AGENT_NOTE_MAX], aid))
    if "provider" in b:  # 2.24.0 (#896)
        c.execute("UPDATE agents SET provider=? WHERE user_id=?", (str(b["provider"] or "").strip()[:80], aid))
    if "proposals" in b:  # 2.3.0: who may ask it for proposals
        if b["proposals"] not in PROP_MODES:
            c.rollback()
            return err(tr("Invalid value: {0}", "proposals"))
        c.execute("UPDATE agents SET proposals=? WHERE user_id=?", (b["proposals"], aid))
    if "webhook_url" in b:
        try:
            secret = agent_hook_set(c, aid, str(b["webhook_url"] or "").strip())
        except (BadInput, Denied):
            c.rollback()
            raise
    if "runtime" in b:  # 2.4.1 (#377): {model?, autocompact?, autocompact_pct?, nightly_reset?}; only the given keys change
        cur = agent_runtime(a0)
        try:
            new = runtime_clean(cur, b["runtime"])
        except BadInput:
            c.rollback()
            raise
        if any(new[k] != cur[k] for k in RUNTIME_DEFAULTS):
            c.execute("UPDATE agents SET runtime=? WHERE user_id=?", (json.dumps(new), aid))
            agent_emit(c, aid, "runtime_changed", {"runtime": {**new, "reset_seq": cur["reset_seq"], "timezone": str(TZ)}})
            print("agent", aid, "runtime", json.dumps(new), "by", g.user["username"], flush=True)
    if "scopes" in b or "allowed_ips" in b:  # 2.15.0 (#479)
        try:
            agent_scopes_set(c, aid, b)
        except BadInput:
            c.rollback()
            raise
    if "enabled" in b:
        if not isinstance(b["enabled"], bool):
            return err(tr("Invalid value: {0}", "enabled"))
        agent_enable(c, aid, b["enabled"])
        if a0["owner_id"] and a0["owner_id"] != me():  # 2.7.2 (#420): an admin paused somebody's personal agent: only an admin resumes it
            c.execute("UPDATE agents SET admin_paused=? WHERE user_id=?", (0 if b["enabled"] else 1, aid))
        print("agent", aid, "enabled" if b["enabled"] else "PAUSED (kill switch)", "by", g.user["username"], flush=True)
    bump(c)
    c.commit()
    if old_avatar and old_avatar != c.execute("SELECT avatar FROM users WHERE id=?", (aid,)).fetchone()[0]:
        avatar_drop_file(aid, old_avatar)
    return jsonify({**agent_admin_dict(c, agent_row(c, aid)), "webhook_secret": secret})


@app.post("/api/admin/agents/<int:aid>/reset")
def admin_agent_reset(aid):
    """2.4.1 (#377): "Reset now": raises the agent's reset_seq and sends it the event reset; its host restarts it with a
    fresh session (Kalmido itself never starts or stops an agent)."""
    c = db()
    a = need_agent_admin(c, aid)
    if not agent_active(a):
        return err(tr("This agent is paused"), 409)
    c.execute("UPDATE agents SET reset_seq=reset_seq+1 WHERE user_id=?", (aid,))
    rt = agent_runtime(agent_row(c, aid))
    seq = agent_emit(c, aid, "reset", {"reset_seq": rt["reset_seq"], "runtime": {**rt, "timezone": str(TZ)},
                                       "user": {"id": me(), "name": user_names(c, [me()]).get(me(), "")}})
    bump(c)
    c.commit()
    print("agent", aid, "reset", rt["reset_seq"], "by", g.user["username"], flush=True)
    return jsonify(ok=bool(seq), reset_seq=rt["reset_seq"])


@app.post("/api/admin/agents/<int:aid>/avatar")
def admin_agent_avatar(aid):
    """2.1.2 (#346): an own picture for an agent (multipart "file", like Settings > Account), set by an admin."""
    c = db()
    need_agent_admin(c, aid)
    return avatar_upload(aid)


@app.post("/api/admin/agents/<int:aid>/token")
def admin_agent_token(aid):
    """A new API token for the agent; every older token of the agent stops at once. Shown this once."""
    need_api()
    c = db()
    need_agent_admin(c, aid)
    c.execute("DELETE FROM api_tokens WHERE user_id=?", (aid,))
    tok = agent_token_new(c, aid, body().get("expires_days"))
    c.commit()
    return jsonify(token=tok)


@app.post("/api/admin/agents/<int:aid>/secret")
def admin_agent_secret(aid):
    c = db()
    a = need_agent_admin(c, aid)
    if not a["webhook_id"]:
        raise Denied(404)
    secret = "whsec_" + secrets.token_urlsafe(32)
    c.execute("UPDATE webhooks SET secret=?, updated_at=? WHERE id=?", (seal(c, f"webhook:{a['webhook_id']}", secret), iso(now_utc()),
                                                                        a["webhook_id"]))
    c.commit()
    return jsonify(secret=secret)


@app.post("/api/admin/agents/<int:aid>/test")
def admin_agent_test(aid):
    """A 'ping' event into the agent's queue, and to its webhook right now (the result is answered)."""
    c = db()
    a = need_agent_admin(c, aid)
    if not agent_active(a):
        return err(tr("This agent is paused"), 409)
    seq = agent_emit(c, aid, "ping", {"message": "Kalmido agent test"})
    env = json.loads(c.execute("SELECT payload FROM agent_events WHERE id=?", (seq,)).fetchone()[0]) if seq else None
    out = {"ok": bool(seq), "seq": seq, "webhook": None}
    if env and a["webhook_id"]:
        w = c.execute("SELECT * FROM webhooks WHERE id=?", (a["webhook_id"],)).fetchone()
        c.execute("DELETE FROM webhook_queue WHERE webhook_id=? AND delivery=?", (w["id"], env["id"]))  # sent right here instead
        ok, status, ms, errc = wh_send(w["url"], unseal(c, f"webhook:{w['id']}", w["secret"]), "ping", env["id"], 1,
                                       json.dumps({**env, "webhook_id": w["id"]}).encode(), wh_allow(c))
        wh_log(c, w["id"], env["id"], "ping", 1, ok, status, errc, ms)
        out["webhook"] = {"ok": ok, "status": status, "ms": ms, "error": errc, "error_text": wh_err_text(errc, status) if errc else ""}
    c.commit()
    return jsonify(out)


# ---- 2.7.2 (#420): personal agents. An admin allows people to create their own agents (instance setting user_agents, off
# by default; user_agents_max per person, default 2; user_agents_limits = the usage limits every new one starts with).
# A personal agent belongs to its creator (agents.owner_id): only the owner shares lists with it, chats with it and manages
# it (name, note, pause, new token, delete); other people never find it in their share pickers. It is never an admin and
# gets no Paperless (make_agent). Admins see every agent (with its owner) and can pause or delete it.
USER_AGENTS_MAX_DEFAULT, USER_AGENTS_MAX_CAP = 2, 20


def agent_policy(c):
    from ..api.scopes import scope_cap
    try:
        mx = int(gsetting(c, "user_agents_max") or USER_AGENTS_MAX_DEFAULT)
    except ValueError:
        mx = USER_AGENTS_MAX_DEFAULT
    lim = gsetting(c, "user_agents_limits") or ""
    return {"user_agents": gsetting(c, "user_agents") == "1", "max_per_user": max(1, min(USER_AGENTS_MAX_CAP, mx)),
            "limits": json.loads(lim) if lim else None,
            # 2.15.0 (#479): the admin's limit: what agents / personal tokens may get at all
            "scope_limit": {"agents": scope_cap(c, "agents"), "tokens": scope_cap(c, "tokens")},
            "scopes": [s for s in SCOPES if s != "admin-read"]}


def agent_owner(c, aid):
    r = c.execute("SELECT owner_id FROM agents WHERE user_id=?", (aid,)).fetchone() if aid else None
    return r["owner_id"] if r else None


def personal_agent_foreign(c, aid, uid):
    """True if aid is somebody else's personal agent (uid may not share with / find it)."""
    o = agent_owner(c, aid)
    return o is not None and o != uid


@app.get("/api/admin/agent-policy")
def admin_agent_policy_get():
    need_admin()
    return jsonify(agent_policy(db()))


@app.put("/api/admin/agent-policy")
def admin_agent_policy_put():
    """{user_agents?: bool, max_per_user?: 1..20, limits?: usage limits or null} -- who may create personal agents."""
    from ..agents.usage import usage_limits_clean
    need_admin()
    b, c = body(), db()
    unknown = sorted(k for k in b if k not in ("user_agents", "max_per_user", "limits", "scope_limit"))
    if unknown:
        return err(tr("Invalid value: {0}", ", ".join(unknown)))
    if "user_agents" in b:
        if not isinstance(b["user_agents"], bool):
            return err(tr("Invalid value: {0}", "user_agents"))
        gset(c, "user_agents", "1" if b["user_agents"] else "0")
    if "max_per_user" in b:
        v = b["max_per_user"]
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= USER_AGENTS_MAX_CAP:
            return err(tr("Invalid value: {0}", "max_per_user"))
        gset(c, "user_agents_max", str(v))
    if "limits" in b:
        try:
            gset(c, "user_agents_limits", usage_limits_clean(b["limits"]))
        except BadInput as e:
            c.rollback()
            return err(str(e))
    if "scope_limit" in b:  # 2.15.0 (#479): {agents?: [...], tokens?: [...]} (read always stays)
        sl = b["scope_limit"]
        if not isinstance(sl, dict) or any(k not in ("agents", "tokens") for k in sl):
            c.rollback()
            return err(tr("Invalid value: {0}", "scope_limit"))
        for k, v in sl.items():
            if not isinstance(v, list) or any(x not in SCOPES or x == "admin-read" for x in v):
                c.rollback()
                return err(tr("Invalid value: {0}", "scope_limit"))
            full = [s for s in SCOPES if s != "admin-read" and (k != "agents" or s not in SCOPES_AGENT_NEVER)]
            keep = sorted(set(v) | {"read"})
            gset(c, "scope_cap_" + k, "" if set(full) <= set(keep) else ",".join(keep + (["admin-read"] if k == "tokens" else [])))
    bump(c)
    c.commit()
    print("agent policy", json.dumps(agent_policy(c)), "by", g.user["username"], flush=True)
    return jsonify(agent_policy(c))


def need_own_agent(c, aid):
    """A personal agent of the current person (404 otherwise)."""
    a = agent_row(c, aid)
    if not a or is_agent(g.user) or a["owner_id"] != me():
        raise Denied(404)
    return a


def my_agents(c, uid):
    return [agent_admin_dict(c, a) for a in c.execute("""SELECT a.*, u.username, u.display_name, u.avatar, u.disabled FROM agents a
                                                         JOIN users u ON u.id=a.user_id WHERE u.kind='agent' AND a.owner_id=? ORDER BY u.id""", (uid,))]


@app.get("/api/my/agents")
def my_agents_get():
    """My personal agents + whether I may create (more)."""
    from ..api.scopes import scopes_offer
    c = db()
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot use this endpoint"))
    pol = agent_policy(c)
    ags = my_agents(c, me())
    return jsonify(allowed=pol["user_agents"] and API_ON, max=pol["max_per_user"], count=len(ags), agents=ags, api=API_ON,
                   scopes=scopes_offer(c, g.user, agent=True), default_scopes=list(SCOPES_AGENT_DEFAULT))  # 2.15.0 (#479)


@app.post("/api/my/agents")
def my_agent_create():
    """{username, display_name?, note?} -> my new personal agent + its API token (shown this once)."""
    from ..api.scopes import agent_scopes_set
    c = db()
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot use this endpoint"))
    need_api()
    pol = agent_policy(c)
    if not pol["user_agents"]:
        raise Denied(403, tr("Personal agents are switched off on this server"))
    c.execute("BEGIN IMMEDIATE")
    n = c.execute("SELECT COUNT(*) FROM agents WHERE owner_id=?", (me(),)).fetchone()[0]
    if n >= pol["max_per_user"]:
        c.rollback()
        return err(trn("You can have at most {0} personal agent", "You can have at most {0} personal agents", pol["max_per_user"]), 409)
    b = body()
    username = (b.get("username") or "").strip().lower()
    if not USERNAME_RE.fullmatch(username):
        c.rollback()
        return err(tr("Username: 1-32 characters a-z, 0-9, dot, dash, underscore"))
    if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        c.rollback()
        return err(tr("Username already exists"), 409)
    uid = create_user(c, username, (b.get("display_name") or "").strip()[:60] or username, None, None, False, paperless_access=False)
    make_agent(c, uid)
    c.execute("UPDATE agents SET note=?, owner_id=?, usage_limits=?, provider=? WHERE user_id=?",
              (str(b.get("note") or "")[:AGENT_NOTE_MAX], me(), gsetting(c, "user_agents_limits") or "", str(b.get("provider") or "").strip()[:80], uid))
    c.execute("UPDATE users SET avatar=? WHERE id=?", ("p:robot", uid))
    try:  # 2.15.0 (#479)
        agent_scopes_set(c, uid, {"scopes": b.get("scopes") or list(SCOPES_AGENT_DEFAULT), **({"allowed_ips": b["allowed_ips"]} if "allowed_ips" in b else {})})
    except BadInput:
        c.rollback()
        raise
    uset(c, uid, "lang", usettings(c, me())["lang"])
    ensure_inbox(c, uid)
    tok = agent_token_new(c, uid)
    bump(c)
    c.commit()
    print("personal agent", username, "(id", uid, ") created by", g.user["username"], flush=True)
    return jsonify({**agent_admin_dict(c, agent_row(c, uid)), "token": tok}), 201


@app.patch("/api/my/agents/<int:aid>")
def my_agent_update(aid):
    """{display_name?, note?, enabled?} -- the owner renames / pauses / resumes a personal agent."""
    from ..api.scopes import agent_scopes_set
    c = db()
    a = need_own_agent(c, aid)
    b = body()
    unknown = sorted(k for k in b if k not in ("display_name", "note", "enabled", "scopes", "allowed_ips", "provider"))
    if unknown:
        return err(tr("Invalid value: {0}", ", ".join(unknown)))
    if "scopes" in b or "allowed_ips" in b:  # 2.15.0 (#479): the owner decides what the agent may do (within the admin's limit)
        try:
            agent_scopes_set(c, aid, b)
        except BadInput:
            c.rollback()
            raise
    if "enabled" in b and not isinstance(b["enabled"], bool):
        return err(tr("Invalid value: {0}", "enabled"))
    if "display_name" in b:
        c.execute("UPDATE users SET display_name=? WHERE id=?", ((str(b["display_name"] or "")).strip()[:60] or a["username"], aid))
    if "note" in b:
        c.execute("UPDATE agents SET note=? WHERE user_id=?", (str(b["note"] or "")[:AGENT_NOTE_MAX], aid))
    if "provider" in b:  # 2.24.0 (#896)
        c.execute("UPDATE agents SET provider=? WHERE user_id=?", (str(b["provider"] or "").strip()[:80], aid))
    if "enabled" in b:
        if b["enabled"] and a["admin_paused"]:
            c.rollback()
            return err(tr("An admin paused this agent; only an admin can resume it"), 403)
        agent_enable(c, aid, b["enabled"])
        print("personal agent", aid, "enabled" if b["enabled"] else "PAUSED", "by its owner", g.user["username"], flush=True)
    bump(c)
    c.commit()
    return jsonify(agent_admin_dict(c, agent_row(c, aid)))


@app.post("/api/my/agents/<int:aid>/token")
def my_agent_token(aid):
    """A new API token for my personal agent; every older one stops at once. Shown this once."""
    need_api()
    c = db()
    need_own_agent(c, aid)
    c.execute("DELETE FROM api_tokens WHERE user_id=?", (aid,))
    tok = agent_token_new(c, aid, body().get("expires_days"))
    c.commit()
    return jsonify(token=tok)


def agent_delete(c, aid, heir):
    """Deletes agent aid; the lists it owns (besides its inbox) go to heir first. The caller commits; returns files to unlink."""
    for lr in c.execute("SELECT * FROM lists WHERE owner_id=? AND is_inbox=0", (aid,)).fetchall():
        owner_transfer(c, lr, heir)
    return user_purge(c, aid)


@app.delete("/api/my/agents/<int:aid>")
def my_agent_delete(aid):
    c = db()
    a = need_own_agent(c, aid)
    files = agent_delete(c, aid, me())
    bump(c)
    c.commit()
    unlink_files(files)
    avatar_drop_file(aid, a["avatar"])
    print("personal agent", aid, "deleted by its owner", g.user["username"], flush=True)
    return jsonify(ok=True)


@app.delete("/api/admin/agents/<int:aid>")
def admin_agent_delete(aid):
    """An admin deletes any agent; its own lists go to the owner of a personal agent, else to the admin."""
    c = db()
    a = need_agent_admin(c, aid)
    heir = a["owner_id"] if a["owner_id"] and c.execute("SELECT 1 FROM users WHERE id=? AND disabled=0", (a["owner_id"],)).fetchone() else me()
    files = agent_delete(c, aid, heir)
    bump(c)
    c.commit()
    unlink_files(files)
    avatar_drop_file(aid, a["avatar"])
    print("agent", aid, "deleted by", g.user["username"], flush=True)
    return jsonify(ok=True)
