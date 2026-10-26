"""2.44.0 (#1517): set up an agent on a computer with one command.

The owner (or an admin) asks for a one-time setup code (Settings > Agents > (agent) > "Set up on a computer"). The copied
command runs the setup script of this instance (static/agent/setup.sh | setup.ps1), which trades the code for an agent
token here (POST /api/agent-setup/redeem: no login, the code is the credential, rate limited like logins), stores it only
readable for the person, fetches the starter files and sets up the autostart. Every computer gets its own token row
(api_tokens.host / folder / os), so "Remove computer" revokes just that one (POST /api/agent-setup/remove with the token
itself = the setup script's --uninstall). Codes are stored as a hash, live AINS_CODE_TTL_MIN minutes and work once.
"""
import os
import re
import secrets
from datetime import timedelta
from flask import g, jsonify, request, send_from_directory

from ..core.config import app, PUBLIC_URL
from ..core.pg import system_ctx
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc, parse_iso
from ..core.access import Denied
from ..accounts.session import _rate_blocked, _rate_fail, _token_hash, client_ip, rate_ip
from ..api.v1 import API_ON, need_api
from ..agents.core import AGENT_OFFLINE_S, agent_row, agent_shares

AINS_CODE_TTL_MIN = 15
AINS_OS = ("mac", "windows", "linux")
AINS_FOLDER_MAX = 300
AINS_HOST_MAX = 80
AINS_RATE = 10  # failed redeems per address in the login window (15 min)
# where the setup script fetches the starter files (mcp/starter_files.txt lists them); {version} = this instance's version
AINS_STARTER_BASE = os.environ.get("KALMIDO_STARTER_BASE", "https://github.com/Gegenschuss/kalmido/raw/v{version}/mcp/")
_AINS_BAD = re.compile(r"[\x00-\x1f\x7f]")


def ains_version():
    try:
        with open(os.path.join(app.root_path, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def ains_text(v, n, what):
    v = v if isinstance(v, str) else ""
    v = v.strip()
    if len(v) > n or _AINS_BAD.search(v):
        raise Denied(400, tr("Invalid value: {0}", what))
    return v


def ains_machines(c, aid):
    """The computers of agent aid = its tokens (one per setup; a token made by hand counts as one too)."""
    out = []
    for r in c.execute("SELECT * FROM api_tokens WHERE user_id=? ORDER BY id DESC", (aid,)).fetchall():
        k = r.keys()
        seen = r["last_used_at"]
        age = round((now_utc() - parse_iso(seen)).total_seconds()) if seen else None
        out.append({"id": r["id"], "prefix": r["prefix"], "host": (r["host"] if "host" in k else "") or "",
                    "os": (r["os"] if "os" in k else "") or "", "folder": (r["folder"] if "folder" in k else "") or "",
                    "created_at": r["created_at"], "last_used_at": seen, "connected": age is not None and age < AGENT_OFFLINE_S})
    return out


def ains_host_set(c, tok, host):
    """PUT /api/v1/agent/status {host}: the computer name the starter reports, kept on the token it uses."""
    host = ains_text(host, AINS_HOST_MAX, "host")
    if tok is not None and host and ((tok["host"] if "host" in tok.keys() else "") or "") != host:
        c.execute("UPDATE api_tokens SET host=? WHERE id=?", (host, tok["id"]))
        return True
    return False


def _plain(s):
    """2.306.0 (#2927): a name for the starter's env file comment and its console line: no control characters."""
    return _AINS_BAD.sub(" ", str(s or ""))


def ains_operator(c, a, r):
    """2.306.0 E (#2927): who answers the permission questions of a team agent (no owner) by default: the person who made the
    setup code (the starter writes it as KALMIDO_PERM_USER). Only the account id; a personal agent asks its owner anyway."""
    if a["owner_id"] or not r["created_by"]:
        return None
    u = c.execute("SELECT id FROM users WHERE id=? AND kind<>'agent' AND disabled=0", (r["created_by"],)).fetchone()
    if not u:
        return None
    # 2.306.0 (#2927): only someone who reaches the agent can answer in its chat -- a shared list, or (a new agent without
    # lists yet) a member of the agent's organisation; an admin outside it gets none (the starter then says so)
    if agent_shares(c, a["user_id"], u["id"]) or not a["org_id"]:
        return u["id"]
    m = c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (a["org_id"], u["id"])).fetchone()
    return u["id"] if m else None


def ains_code_new(c, aid):
    b = body()
    osn = b.get("os") or ""
    if osn not in AINS_OS:
        raise Denied(400, tr("Invalid value: {0}", "os"))
    folder = ains_text(b.get("folder"), AINS_FOLDER_MAX, "folder")
    code = "ks_" + secrets.token_urlsafe(18)
    t = now_utc()
    exp = iso(t + timedelta(minutes=AINS_CODE_TTL_MIN))
    c.execute("DELETE FROM agent_setup_codes WHERE agent_id=? AND (used_at IS NOT NULL OR expires_at<?)", (aid, iso(t)))
    c.execute("INSERT INTO agent_setup_codes(agent_id,code_hash,os,folder,created_by,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
              (aid, _token_hash(code), osn, folder, g.user["id"], iso(t), exp))
    c.commit()
    return jsonify(code=code, expires_at=exp, ttl_min=AINS_CODE_TTL_MIN, os=osn, folder=folder, url=(PUBLIC_URL or request.host_url).rstrip("/"))


def ains_machine_del(c, aid, tid):
    n = c.execute("DELETE FROM api_tokens WHERE id=? AND user_id=?", (tid, aid)).rowcount
    if not n:
        raise Denied(404)
    bump(c)
    c.commit()
    return jsonify(ok=True, machines=ains_machines(c, aid))


def _my(aid):
    from ..agents.admin import need_own_agent
    need_api()
    c = db()
    need_own_agent(c, aid)
    return c


@app.post("/api/my/agents/<int:aid>/setup-code")
def ains_my_code(aid):
    c = _my(aid)
    return ains_code_new(c, aid)


@app.get("/api/my/agents/<int:aid>/machines")
def ains_my_machines(aid):
    c = _my(aid)
    return jsonify(machines=ains_machines(c, aid))


@app.delete("/api/my/agents/<int:aid>/machines/<int:tid>")
def ains_my_machine_del(aid, tid):
    c = _my(aid)
    return ains_machine_del(c, aid, tid)


@app.post("/api/admin/agents/<int:aid>/setup-code")
def ains_admin_code(aid):
    from ..agents.admin import need_agent_admin
    need_api()
    c = db()
    with system_ctx(c):  # the instance admin manages agent accounts (any organisation; structure, no content), like the token route
        need_agent_admin(c, aid)
        return ains_code_new(c, aid)


@app.get("/api/admin/agents/<int:aid>/machines")
def ains_admin_machines(aid):
    from ..agents.admin import need_agent_admin
    c = db()
    with system_ctx(c):  # the instance admin manages agent accounts (any organisation; structure, no content)
        need_agent_admin(c, aid)
        return jsonify(machines=ains_machines(c, aid))


@app.delete("/api/admin/agents/<int:aid>/machines/<int:tid>")
def ains_admin_machine_del(aid, tid):
    from ..agents.admin import need_agent_admin
    c = db()
    with system_ctx(c):  # the instance admin manages agent accounts (any organisation; structure, no content)
        need_agent_admin(c, aid)
        return ains_machine_del(c, aid, tid)


@app.post("/api/agent-setup/redeem")
def ains_redeem():
    """{code, host?, folder?, os?} -> {token, url, agent, operator_id, starter_base, version}. No login: the one-time code is the credential."""
    from ..agents.admin import agent_token_new
    keys = [("setup:ip:" + rate_ip(), AINS_RATE)]
    if _rate_blocked(keys):
        return err(tr("Too many failed attempts, please wait a few minutes"), 429)
    if not API_ON:
        return err(tr("The API is switched off on this server"), 403)
    b = body()
    code = b.get("code") if isinstance(b.get("code"), str) else ""
    host = ains_text(b.get("host"), AINS_HOST_MAX, "host")
    c = db()
    with system_ctx(c):  # no account yet: the code alone decides which agent; read and written only for that one row
        r = c.execute("SELECT * FROM agent_setup_codes WHERE code_hash=?", (_token_hash(code.strip()),)).fetchone() if code else None
        a = agent_row(c, r["agent_id"]) if r else None
        u = c.execute("SELECT disabled FROM users WHERE id=?", (r["agent_id"],)).fetchone() if r else None
        bad = not r or r["used_at"] or parse_iso(r["expires_at"]) <= now_utc() or not a or not u or u["disabled"]
        if bad:
            _rate_fail(keys)
            return err(tr("This setup code is invalid, used or expired. Create a new one in Kalmido."), 400)
        # once only, also when two redeems race: the UPDATE wins for one of them
        if not c.execute("UPDATE agent_setup_codes SET used_at=? WHERE id=? AND used_at IS NULL", (iso(now_utc()), r["id"])).rowcount:
            _rate_fail(keys)
            return err(tr("This setup code is invalid, used or expired. Create a new one in Kalmido."), 400)
        tok = agent_token_new(c, r["agent_id"])
        tid = c.execute("SELECT id FROM api_tokens WHERE token_hash=?", (_token_hash(tok),)).fetchone()[0]
        folder = ains_text(b.get("folder"), AINS_FOLDER_MAX, "folder") or r["folder"]
        osn = b.get("os") if b.get("os") in AINS_OS else r["os"]
        c.execute("UPDATE api_tokens SET host=?, folder=?, os=? WHERE id=?", (host, folder, osn, tid))
        c.execute("UPDATE agent_setup_codes SET token_id=? WHERE id=?", (tid, r["id"]))
        bump(c)
        c.commit()
        ver = ains_version()
        print("agent setup: code redeemed for agent", r["agent_id"], "token", tid, flush=True)
        return jsonify(token=tok, url=(PUBLIC_URL or request.host_url).rstrip("/"), version=ver,
                       agent={"id": a["user_id"], "name": _plain(a["display_name"] or a["username"]), "username": _plain(a["username"]),
                              "team": not a["owner_id"]},
                       operator_id=ains_operator(c, a, r), starter_base=AINS_STARTER_BASE.replace("{version}", ver or "main"))


@app.post("/api/agent-setup/remove")
def ains_remove():
    """The setup script's --uninstall: the computer's own token (Authorization: Bearer) is revoked. Nothing else."""
    auth = request.headers.get("Authorization") or ""
    tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    keys = [("setup:ip:" + rate_ip(), AINS_RATE)]
    if _rate_blocked(keys):
        return err(tr("Too many failed attempts, please wait a few minutes"), 429)
    c = db()
    with system_ctx(c):  # no session: the token itself is the credential and only its own row goes
        r = c.execute("SELECT t.id, t.user_id FROM api_tokens t JOIN users u ON u.id=t.user_id WHERE t.token_hash=? AND u.kind='agent'",
                      (_token_hash(tok),)).fetchone() if tok else None
        if not r:
            _rate_fail(keys)
            return err(tr("Missing or invalid API token"), 401)
        c.execute("DELETE FROM api_tokens WHERE id=?", (r["id"],))
        bump(c)
        c.commit()
        print("agent setup: computer removed for agent", r["user_id"], "token", r["id"], flush=True)
        return jsonify(ok=True)


@app.get("/agent-setup.sh")
@app.get("/agent-setup.ps1")
def ains_script():
    """The setup scripts (static/agent/setup.sh | setup.ps1), at a short address for the copied command."""
    r = send_from_directory(os.path.join(app.static_folder, "agent"), "setup" + request.path[len("/agent-setup"):], mimetype="text/plain")
    r.headers["Cache-Control"] = "no-cache"
    return r
