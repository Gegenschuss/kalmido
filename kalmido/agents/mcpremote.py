"""2.488.0 (#3363): the hosted MCP access -- an MCP client (a chat app's connector, an editor) connects to Kalmido itself.

/mcp speaks Streamable HTTP of the MCP specification 2025-06-18 in its plain form: POST with JSON-RPC, a JSON answer, no SSE
(GET and DELETE: 405). Kalmido starts no agent; it only answers tool calls. The tools are the ones of mcp/kalmido_mcp.py (the
same file the starter runs, loaded from the image: Dockerfile copies it next to app.py), never a copy: its table, argument
check and JSON-RPC handling run here with an in-process client (_inproc_cls) that sends every call as a request to /api/v1 of
this server, with the agent's token, so the scope / role / list checks of /api/v1 (api/v1.py api_authenticate, api/scopes.py)
decide exactly as for the starter. Without the file /mcp answers 503.

Who may connect: OAuth 2.1 with this server as the authorization server.
 - metadata: /.well-known/oauth-protected-resource (RFC 9728) and /.well-known/oauth-authorization-server (RFC 8414); /mcp
   without a valid token answers 401 with WWW-Authenticate: Bearer resource_metadata="...".
 - /oauth/register: dynamic client registration (RFC 7591), public clients only (no secret; PKCE is the proof), at most
   MCPR_REG_PER_HOUR per address; redirect URIs only https or http on localhost / 127.0.0.1 / [::1], compared exactly.
 - /oauth/authorize: authorization code + PKCE S256 (plain and a missing challenge are refused), state passed through. The
   consent page needs a signed-in person (else the sign-in, then back here: static/js/events.js afterLogin); it names the
   client and the host it returns to, and the person picks one of the agents they may manage (their personal ones; an
   instance admin also the team agents) or makes a new personal one (agents/admin.py my_agent_make). The page's form carries
   the request sealed with the server key (bound to the person, 10 min), so a foreign page can neither forge nor replay it;
   frame-ancestors 'none'.
 - /oauth/token: the code once (a second use revokes the access made with it), within 10 min, with the same client and
   redirect URI and the verifier. The access token is an ordinary API token of the agent (agents/admin.py agent_token_new:
   its scopes, address rule and projects, no token kind of its own) that runs out after MCPR_ACCESS_S; the refresh token
   changes at every use (the previous one used again revokes the access). Both only as SHA-256 in the database.
 - /oauth/revoke (RFC 7009) and Settings > Agents (GET / DELETE /api/my/mcp-grants): revoking ends the access token and the
   refresh token at once.
Limits (2.488.0 review): /mcp never waits in the web process (a 429 / 503 of /api/v1 goes back to the client at once), a
batch has at most MCPR_BATCH_MAX messages, one access runs at most MCPR_PER_GRANT requests at once (of MCPR_CONCURRENT), a
request stops making calls after MCPR_RUN_S, file answers are read in pieces up to max_bytes. A new token of the agent (or
deleting its token) ends the access at the next refresh; a support access opened by a client never lets the operator hand
out the client's agents.
The admin switch "Hosted MCP access" (instance setting mcp_remote, default off; core/instance.py AUTH_SWITCHES, asks for
the password when switched on): off = every /oauth/* route and /mcp answer 404. Tables: core/migrations.d/3363.py."""
import base64
import hashlib
import hmac
import html
import importlib.util
import json
import os
import re
import secrets
import threading
import time
import unicodedata
import urllib.parse
from datetime import timedelta
from flask import g, jsonify, redirect, request, Response

from ..core.config import app, APP_DIR, APP_NAME, PUBLIC_URL, PUBLIC_URL_SET
from ..core.pg import insert_id, system_ctx
from ..core.i18n import tr
from ..core.db import db, gsetting, iso, now_utc, parse_iso
from ..core.access import Denied
from ..core.errors import BadInput
from ..accounts.session import _rate_blocked, _rate_fail, _token_hash, client_ip, me, rate_ip
from ..accounts.login import seal, unseal, WA_ORIGINS_ENV
from ..accounts.orgs import op_foreign_account
from ..agents.core import agent_row, is_agent, need_person
from ..agents.admin import agent_policy, agent_token_new, agent_ws_allowed_any, my_agent_make
from ..api.common import hit_limit
from ..api.v1 import API_ON

MCPR_SWITCH = "mcp_remote"           # instance setting, "1" = on (default off)
MCPR_ACCESS_S = 3600                 # the access token's life
MCPR_REFRESH_DAYS = 30               # a refresh token not used within this runs out (every use gives a new one)
MCPR_GRANT_MAX_DAYS = 90             # 2.674.0 (#4028, review F12): an access ends this long after its first token, used or not
MCPR_CODE_S = 600                    # an authorization code / the consent form
MCPR_REG_PER_HOUR = 20               # client registrations per address and hour
MCPR_REG_KEEP_DAYS = 7               # a registered client without any access is forgotten after this
MCPR_BAD_LIMIT = 30                  # failed token / code attempts per address within the fail window (accounts/session.py)
MCPR_MAX_BODY = 1_000_000            # bytes of one /mcp request (as kalmido_mcp.py --http)
MCPR_CONCURRENT = 16                 # /mcp requests running at once on this process (each holds a thread)
MCPR_PER_GRANT = 4                   # review F3: /mcp requests of one access at once (the rest 429)
MCPR_BATCH_MAX = 20                  # review F3: JSON-RPC messages in one /mcp batch (more: 400)
MCPR_RUN_S = 90                      # review F3: an /mcp request answers 504 after this (the work goes on; its places stay taken)
MCPR_REVOKE_LIMIT = 60               # review F9: /oauth/revoke requests per address within 15 min
MCPR_USED_EVERY = 60                 # s between two last_used_at updates of an access
MCPR_SCOPE = "mcp"                   # the one scope name offered: the rights are the agent's, not the scope's
CLIENT_NAME_MAX, REDIRECTS_MAX, REDIRECT_LEN_MAX = 100, 5, 500
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")      # urlsplit().hostname of http redirect URIs allowed
HOST_RE = re.compile(r"[a-z0-9.-]+")                      # urlsplit().hostname (lower case) of a redirect URI
CHALLENGE_RE = re.compile(r"[A-Za-z0-9_-]{43}")          # base64url of a SHA-256, unpadded
VERIFIER_RE = re.compile(r"[A-Za-z0-9._~-]{43,128}")     # RFC 7636
MCPR_FILES = (os.path.join(APP_DIR, "kalmido_mcp.py"), os.path.join(APP_DIR, "mcp", "kalmido_mcp.py"))  # image, checkout
_MOD, _MOD_LOCK = {}, threading.Lock()
_SEM = threading.BoundedSemaphore(MCPR_CONCURRENT)
_RUNNING, _RUN_LOCK = {}, threading.Lock()   # review F3: grant id -> /mcp requests of that access still running


# ---------------------------------------------------------------- helpers

def mcpr_on(c):
    """The admin switch is on (and the API: every tool call is an /api/v1 request)."""
    return API_ON and gsetting(c, MCPR_SWITCH) == "1"


def mcpr_base():
    """The issuer / the address clients use: PUBLIC_URL. 2.666.0 (#4074 5): without it refused (503), never the address of this
    request (a forged Host header would put another host into the OAuth metadata / the issuer)."""
    if not PUBLIC_URL_SET:
        raise Denied(503, tr("PUBLIC_URL is not set on this server: ask the server admin to set it to the address people open (.env) and restart."))
    return PUBLIC_URL.rstrip("/")


def mcpr_origin_ok(origin):
    """2.674.0 (#4028, review F11): an Origin header the consent form / /mcp accept. With PUBLIC_URL set only it (and the extra
    passkey addresses KALMIDO_WEBAUTHN_ORIGINS, the same server under another name), never the Host header of the request;
    without PUBLIC_URL the address of this request (Administration > Agents warns, static/js/settings.js)."""
    o = origin.rstrip("/")
    if not PUBLIC_URL_SET:
        return o == request.host_url.rstrip("/")
    return o == mcpr_base() or o in WA_ORIGINS_ENV


def mcpr_resource():
    return mcpr_base() + "/mcp"


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _no_store(resp, code=200):
    resp = resp if isinstance(resp, Response) else jsonify(resp)
    resp.status_code = code
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Pragma"] = "no-cache"
    return resp


def _oerr(error, desc, code=400, extra=None):
    """An OAuth error answer (RFC 6749 5.2)."""
    r = _no_store({"error": error, "error_description": desc}, code)
    for k, v in (extra or {}).items():
        r.headers[k] = v
    return r


def _gone():
    return jsonify(error="not found"), 404


def redirect_ok(u):
    """https with a host, or http on this computer (localhost / 127.0.0.1 / [::1], any port); no fragment, no user info."""
    if not isinstance(u, str) or not u or len(u) > REDIRECT_LEN_MAX or any(ch.isspace() for ch in u):
        return False
    try:
        p = urllib.parse.urlsplit(u)
        host = p.hostname or ""
        p.port  # noqa: B018  (a bad port raises ValueError)
    except ValueError:
        return False
    if p.fragment or "#" in u or p.username or p.password or not host:
        return False
    # review F8: a plain ASCII host name (IDN only as punycode), no backslash / control / bidi characters that a browser and
    # this check read differently, or that make the host shown on the consent page look like another one
    if not (HOST_RE.fullmatch(host) or host == "::1"):
        return False
    return p.scheme == "https" or (p.scheme == "http" and host.lower() in LOCAL_HOSTS)


def _origin(u):
    p = urllib.parse.urlsplit(u)
    return f"{p.scheme}://{p.netloc}"


def _with_query(u, params):
    p = urllib.parse.urlsplit(u)
    q = (p.query + "&" if p.query else "") + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, q, ""))


def _resource_ok(v):
    """The resource parameter (RFC 8707) when a client sends it: this server's /mcp (or the server itself)."""
    if not v:
        return True
    v = v.rstrip("/")
    return v in (mcpr_resource(), mcpr_base())


def _client(c, cid):
    if not isinstance(cid, str) or not cid or len(cid) > 100:
        return None
    return c.execute("SELECT * FROM oauth_clients WHERE client_id=?", (cid,)).fetchone()


def _uris(cl):
    try:
        v = json.loads(cl["redirect_uris"] or "[]")
    except ValueError:
        return []
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _bad(ip):
    """The failed-attempt counter of /oauth/token (codes, refresh tokens, unknown clients)."""
    return [("oauthbad:" + ip, MCPR_BAD_LIMIT)]


def _mcp_bad(ip):
    """Review F4: unknown tokens on /mcp count apart, so a connector that keeps sending a revoked token cannot lock the token
    endpoint (the refresh) for everybody behind the same address."""
    return [("mcpbad:" + ip, MCPR_BAD_LIMIT)]


class _AsUser:
    """g.user = u for a block (the token endpoint has no person; op_foreign_account asks me())."""
    def __init__(self, u):
        self.u = u

    def __enter__(self):
        self.prev = g.get("user")
        g.user = self.u

    def __exit__(self, *a):
        g.user = self.prev


def _person_ok(u):
    return bool(u) and not u["disabled"] and not is_agent(u) and not u["kid"]


def mcpr_agents(c, u):
    """[(agent id, name, username, team)] the person may connect: their personal agents; an instance admin also the team
    agents (no owner) that are not a client's on a hosted server."""
    out = [(r["user_id"], r["display_name"] or r["username"], r["username"], False) for r in c.execute(
        """SELECT a.user_id, u.display_name, u.username FROM agents a JOIN users u ON u.id=a.user_id
           WHERE u.kind='agent' AND u.disabled=0 AND a.owner_id=? ORDER BY u.id""", (u["id"],))]
    if u["is_admin"]:
        with system_ctx(c):  # an instance admin picks a team agent: names only, as Settings > Status lists them
            team = c.execute("""SELECT a.user_id, u.display_name, u.username FROM agents a JOIN users u ON u.id=a.user_id
                                WHERE u.kind='agent' AND u.disabled=0 AND a.owner_id IS NULL ORDER BY u.id""").fetchall()
        with _AsUser(u):
            # review F6: a support access the client opened is not enough to hand its agents out (grant=False)
            out += [(r["user_id"], r["display_name"] or r["username"], r["username"], True) for r in team
                    if not op_foreign_account(c, r["user_id"], note=False, grant=False)]
    return out


def mcpr_may(c, uid, aid, support=False):
    """The person uid (still) may hand out agent aid: active, a person, and the agent is theirs or a team agent and they an
    instance admin (not a client's agent on a hosted server). Review F6: giving an access (consent, code) needs the person's own
    right - a support access the client opened (accounts/supportgrant.py) does not count; support=True (the refresh of an
    access given before) lets it count, unlogged."""
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not _person_ok(u):
        return False
    with system_ctx(c):  # owner and organisation of the agent only (who may hand it out), no content
        a = agent_row(c, aid)
    if not a or a["disabled"]:
        return False
    if a["owner_id"]:
        return a["owner_id"] == uid
    if not u["is_admin"]:
        return False
    with _AsUser(u):
        return not op_foreign_account(c, aid, note=False, grant=support)


def mcpr_grant_end(created_at):
    """2.674.0 (#4028, review F12): when an access made at created_at (its first token) ends for good."""
    return parse_iso(created_at) + timedelta(days=MCPR_GRANT_MAX_DAYS)


def _issue(c, grant_id, aid, cname):
    """A new access token (an API token of the agent, MCPR_ACCESS_S) + a new refresh token for grant grant_id -> answer dict.
    The caller removed the old access token and commits. 2.674.0 (#4028, review F12): neither outlives MCPR_GRANT_MAX_DAYS
    after the access was made."""
    with system_ctx(c):  # the grant's own agent: agent_token_new copies its scopes, address rule and projects (no content)
        tok = agent_token_new(c, aid, name=("MCP: " + (cname or "client"))[:80])
    now = now_utc()
    end = mcpr_grant_end(c.execute("SELECT created_at FROM oauth_grants WHERE id=?", (grant_id,)).fetchone()[0])
    exp = min(now + timedelta(seconds=MCPR_ACCESS_S), end)
    tid = c.execute("UPDATE api_tokens SET expires_at=? WHERE token_hash=? RETURNING id", (iso(exp), _token_hash(tok))).fetchone()[0]
    rt = "kmr_" + secrets.token_urlsafe(32)
    c.execute("UPDATE oauth_grants SET token_id=?, refresh_hash=?, refresh_expires_at=?, last_used_at=? WHERE id=?",
              (tid, _token_hash(rt), iso(min(now + timedelta(days=MCPR_REFRESH_DAYS), end)), iso(now), grant_id))
    return {"access_token": tok, "token_type": "Bearer", "expires_in": max(1, int((exp - now).total_seconds())), "refresh_token": rt,
            "scope": MCPR_SCOPE}


def mcpr_revoke(c, gid):
    """Ends access gid at once: its access token goes, its refresh tokens stop. The caller commits."""
    r = c.execute("SELECT token_id FROM oauth_grants WHERE id=?", (gid,)).fetchone()
    if not r:
        return
    if r["token_id"]:
        c.execute("DELETE FROM api_tokens WHERE id=?", (r["token_id"],))
    c.execute("UPDATE oauth_grants SET revoked_at=COALESCE(revoked_at, ?), token_id=NULL, refresh_hash=NULL, prev_refresh_hash=NULL "
              "WHERE id=?", (iso(now_utc()), gid))


# ---------------------------------------------------------------- metadata (RFC 9728, RFC 8414)

def _meta(d):
    if not mcpr_on(db()):
        return _gone()
    r = jsonify(d)
    r.headers["Access-Control-Allow-Origin"] = "*"  # public facts; browser-based clients read them
    r.headers["Cache-Control"] = "max-age=300"
    return r


@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
def mcpr_resource_meta():
    return _meta({"resource": mcpr_resource(), "authorization_servers": [mcpr_base()], "bearer_methods_supported": ["header"],
                  "scopes_supported": [MCPR_SCOPE], "resource_name": APP_NAME})


@app.get("/.well-known/oauth-authorization-server")
@app.get("/.well-known/oauth-authorization-server/mcp")
def mcpr_as_meta():
    b = mcpr_base()
    return _meta({"issuer": b, "authorization_endpoint": b + "/oauth/authorize", "token_endpoint": b + "/oauth/token",
                  "registration_endpoint": b + "/oauth/register", "revocation_endpoint": b + "/oauth/revoke",
                  "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"],
                  "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none"],
                  "revocation_endpoint_auth_methods_supported": ["none"], "scopes_supported": [MCPR_SCOPE],
                  "authorization_response_iss_parameter_supported": True})  # RFC 9207: iss comes with the code


# ---------------------------------------------------------------- registration (RFC 7591)

@app.post("/oauth/register")
def mcpr_register():
    c = db()
    if not mcpr_on(c):
        return _gone()
    if hit_limit("oauthreg:" + rate_ip(), MCPR_REG_PER_HOUR, 3600):
        return _oerr("slow_down", "too many registrations from this address, try again later", 429, {"Retry-After": "600"})
    b = request.get_json(silent=True)
    if not isinstance(b, dict):
        return _oerr("invalid_client_metadata", "a JSON object is needed")
    uris = b.get("redirect_uris")
    if not isinstance(uris, list) or not 1 <= len(uris) <= REDIRECTS_MAX or not all(redirect_ok(u) for u in uris):
        return _oerr("invalid_redirect_uri", f"1 to {REDIRECTS_MAX} redirect URIs: https, or http on localhost / 127.0.0.1")
    gt = b.get("grant_types")
    if gt is not None and (not isinstance(gt, list) or not set(gt) <= {"authorization_code", "refresh_token"}):
        return _oerr("invalid_client_metadata", "grant_types: authorization_code and refresh_token only")
    rt = b.get("response_types")
    if rt is not None and (not isinstance(rt, list) or not set(rt) <= {"code"}):
        return _oerr("invalid_client_metadata", "response_types: code only")
    name = b.get("client_name")
    # review F8: control and format characters (bidi overrides like U+202E) out, so the name cannot look like another one
    name = "".join(ch for ch in name if unicodedata.category(ch) not in ("Cc", "Cf", "Co", "Cs")).strip()[:CLIENT_NAME_MAX] \
        if isinstance(name, str) else ""
    name = name or "MCP client"
    cid = "kmc_" + secrets.token_urlsafe(24)
    now = now_utc()
    c.execute("DELETE FROM oauth_clients WHERE created_at<? AND NOT EXISTS (SELECT 1 FROM oauth_grants g WHERE g.client_id=oauth_clients.client_id)",
              (iso(now - timedelta(days=MCPR_REG_KEEP_DAYS)),))
    uris = list(dict.fromkeys(uris))
    c.execute("INSERT INTO oauth_clients(client_id,name,redirect_uris,created_at,reg_ip) VALUES(?,?,?,?,?)",
              (cid, name, json.dumps(uris), iso(now), rate_ip()))
    c.commit()
    return _no_store({"client_id": cid, "client_id_issued_at": int(time.time()), "client_name": name, "redirect_uris": uris,
                      "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
                      "token_endpoint_auth_method": "none"}, 201)


# ---------------------------------------------------------------- consent page

def _page(title, main, code=200, form_to=None):
    e = html.escape
    doc = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
           '<meta name="robots" content="noindex, nofollow"><meta name="referrer" content="no-referrer">'
           f'<title>{e(title)}</title><link rel="stylesheet" href="/static/public.css">'
           f'<link rel="icon" href="/static/favicon.svg" type="image/svg+xml"></head><body><main>{main}</main></body></html>')
    r = Response(doc, status=code, mimetype="text/html")
    # the form may only go here; the answer to it redirects to the client (some browsers hold redirects to form-action too)
    fa = "'self'" + (" " + form_to if form_to else "")
    r.headers["Content-Security-Policy"] = (f"default-src 'none'; style-src 'self'; img-src 'self'; form-action {fa}; "
                                            "frame-ancestors 'none'; base-uri 'none'")
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["Referrer-Policy"] = "no-referrer"
    r.headers["Cache-Control"] = "no-store"
    r.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return r


def _msg_page(title, text, code=400):
    e = html.escape
    return _page(title, f'<div class="msg"><h1>{e(title)}</h1><p>{e(text)}</p></div>', code)


def _authz_params():
    a = request.args
    return {k: a.get(k, "") for k in ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method",
                                       "state", "scope", "resource")}


@app.get("/oauth/authorize")
def mcpr_authorize():
    c = db()
    if not mcpr_on(c):
        return _gone()
    p = _authz_params()
    cl = _client(c, p["client_id"])
    if not cl:
        return _msg_page(tr("Connection not possible"), tr("This app is not registered here. Start the connection in the app again."))
    uris = _uris(cl)
    ruri = p["redirect_uri"] or (uris[0] if len(uris) == 1 else "")
    if ruri not in uris:  # exact match; never redirected anywhere else
        return _msg_page(tr("Connection not possible"), tr("The return address of this app does not match its registration."))
    # review F5: anybody can register a client with any https return address, so a wrong request is shown here as a page and
    # never sent on (RFC 9700 4.11.2: no open redirector); these are always mistakes of the client's program
    if len(p["state"]) > 500:
        return _msg_page(tr("Connection not possible"), tr("The app sent an invalid request. Start the connection in the app again."))
    if p["response_type"] != "code":
        return _msg_page(tr("Connection not possible"), tr("The app sent an invalid request. Start the connection in the app again."))
    if p["code_challenge_method"] != "S256" or not CHALLENGE_RE.fullmatch(p["code_challenge"]):
        return _msg_page(tr("Connection not possible"), tr("The app sent an invalid request. Start the connection in the app again."))
    if not _resource_ok(p["resource"]):
        return _msg_page(tr("Connection not possible"), tr("The app sent an invalid request. Start the connection in the app again."))
    u = g.get("user")
    if not u or g.get("auth_via") not in ("session", "proxy"):
        return redirect("/?oauth=" + urllib.parse.quote("?" + request.query_string.decode("latin-1"), safe=""), 303)
    if not _person_ok(u):
        return _msg_page(tr("Connection not possible"), tr("This account cannot connect apps."), 403)
    from ..accounts.supportgrant import SGA_REFUSED, sga_is_support  # here: its place in the module order stays
    if sga_is_support(c):  # 2.500.0 (#4070): an access of an app would outlive the client's consent; the POST: sga_guard
        return _msg_page(tr("Connection not possible"), tr(SGA_REFUSED), 403)
    return _consent(c, u, cl, {"c": cl["client_id"], "r": ruri, "ch": p["code_challenge"], "s": p["state"], "res": p["resource"]})


def _consent(c, u, cl, req, problem="", code=200):
    e = html.escape
    req = {**req, "u": u["id"], "x": int(time.time()) + MCPR_CODE_S}
    t = seal(c, "oauth-consent", json.dumps(req))
    host = urllib.parse.urlsplit(req["r"]).netloc
    local = (urllib.parse.urlsplit(req["r"]).hostname or "").lower() in LOCAL_HOSTS
    ags = mcpr_agents(c, u)
    pol = agent_policy(c)
    n = c.execute("SELECT COUNT(*) FROM agents WHERE owner_id=?", (u["id"],)).fetchone()[0]
    may_new = API_ON and agent_ws_allowed_any(c, u["id"]) and n < pol["max_per_user"]
    first = "checked" if ags else ""
    rows = "".join(f'<label class="opt"><input type="radio" name="agent" value="{a[0]}" {first if i == 0 else ""}> <b>{e(a[1])}</b> '
                   f'<span class="muted">{e(a[2])}{" · " + e(tr("team agent")) if a[3] else ""}</span></label>'
                   for i, a in enumerate(ags))
    if may_new:
        rows += (f'<label class="opt"><input type="radio" name="agent" value="new" {"" if ags else "checked"}> '
                 f'<b>{e(tr("Create a new personal agent"))}</b></label>'
                 f'<p><input name="display_name" maxlength="60" placeholder="{e(tr("Display name"))}" aria-label="{e(tr("Display name"))}" '
                 f'value="{e(cl["name"][:60])}"> <input name="username" maxlength="32" autocapitalize="off" autocomplete="off" '
                 f'spellcheck="false" placeholder="{e(tr("Username, e.g. my-claude"))}" aria-label="{e(tr("Username"))}"></p>')
    if not rows:
        return _msg_page(tr("Connection not possible"), tr("You have no agent you can connect, and you cannot create one on this server."), 403)
    main = (f'<form method="post" action="/oauth/authorize" class="consent"><h1>{e(tr("Connect {0}?", cl["name"]))}</h1>'
            f'<p>{e(tr("{0} wants to work in {1} as one of your agents.", cl["name"], APP_NAME))} '
            f'{e(tr("Afterwards it is sent back to {0}.", host))}'
            f'{" " + e(tr("That is a program on this computer.")) if local else ""}</p>'
            f'<p>{e(tr("It gets exactly the permissions of the agent you select: only the projects shared with it. You can disconnect it at any time under Settings > Agents."))}</p>'
            + (f'<p class="err" role="alert">{e(problem)}</p>' if problem else "")
            + f'<fieldset><legend>{e(tr("Which agent?"))}</legend>{rows}</fieldset>'
            f'<input type="hidden" name="t" value="{e(t)}">'
            f'<p><button type="submit" name="decision" value="allow">{e(tr("Connect"))}</button> '
            f'<button type="submit" name="decision" value="deny">{e(tr("Cancel"))}</button></p></form>')
    return _page(tr("Connect {0}?", cl["name"]), main, code, form_to=_origin(req["r"]))


@app.post("/oauth/authorize")
def mcpr_authorize_post():
    c = db()
    if not mcpr_on(c):
        return _gone()
    # a form of this page only: never from another site (the sealed request is the check value, this the second fence)
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site" or \
            (request.headers.get("Origin") and not mcpr_origin_ok(request.headers["Origin"])):  # 2.674.0 (#4028, review F11)
        return _msg_page(tr("Connection not possible"), tr("Request blocked"), 403)
    u = g.get("user")
    if not u or g.get("auth_via") not in ("session", "proxy") or not _person_ok(u):
        return _msg_page(tr("Connection not possible"), tr("Please sign in"), 401)
    try:
        req = json.loads(unseal(c, "oauth-consent", request.form.get("t", "")))
    except Exception:  # noqa: BLE001  (a changed or foreign value, a changed server key)
        req = None
    if not isinstance(req, dict) or req.get("u") != u["id"] or int(req.get("x") or 0) < time.time():
        return _msg_page(tr("Connection not possible"), tr("The page was open too long. Start the connection in the app again."))
    cl = _client(c, req.get("c"))
    if not cl or req.get("r") not in _uris(cl):
        return _msg_page(tr("Connection not possible"), tr("This app is not registered here. Start the connection in the app again."))
    if request.form.get("decision") != "allow":
        return redirect(_with_query(req["r"], {"error": "access_denied", "state": req.get("s")}), 303)
    pick = request.form.get("agent", "")
    if pick == "new":
        try:
            aid = my_agent_make(c, {"username": request.form.get("username", ""), "display_name": request.form.get("display_name", ""),
                                    "provider": cl["name"][:80]})
        except (Denied, BadInput) as ex:
            c.rollback()
            return _consent(c, u, cl, req, ex.text() if isinstance(ex, Denied) else str(ex), 400)
    else:
        try:
            aid = int(pick)
        except ValueError:
            aid = 0
        if aid not in [a[0] for a in mcpr_agents(c, u)] or not mcpr_may(c, u["id"], aid):
            return _consent(c, u, cl, req, tr("Please select an agent."), 400)
    code = secrets.token_urlsafe(32)
    now = now_utc()
    c.execute("DELETE FROM oauth_codes WHERE expires_at<?", (iso(now - timedelta(days=1)),))
    c.execute("""INSERT INTO oauth_codes(code_hash,client_id,user_id,agent_id,redirect_uri,challenge,resource,created_at,expires_at)
                 VALUES(?,?,?,?,?,?,?,?,?)""", (_token_hash(code), cl["client_id"], u["id"], aid, req["r"], req["ch"],
                                                 req.get("res") or "", iso(now), iso(now + timedelta(seconds=MCPR_CODE_S))))
    from .usage import audit_note  # 2.674.0 (#4028, review F12): in the agent's log (Administration > Agents > Log): 201 = made here
    audit_note(c, aid, "POST", "/oauth/authorize", 201 if pick == "new" else 200, MCPR_SCOPE)
    c.commit()
    print("hosted MCP: access for agent", aid, "given by", u["id"], "to client", cl["id"],
          "(agent made on the consent page)" if pick == "new" else "", flush=True)
    return redirect(_with_query(req["r"], {"code": code, "state": req.get("s"), "iss": mcpr_base()}), 303)


# ---------------------------------------------------------------- token, revoke

def _form():
    if request.is_json:
        b = request.get_json(silent=True)
        return {k: v for k, v in b.items() if isinstance(v, str)} if isinstance(b, dict) else {}
    return {k: v for k, v in request.form.items()}


@app.post("/oauth/token")
def mcpr_token():
    c = db()
    if not mcpr_on(c):
        return _gone()
    ip = rate_ip()
    f = _form()

    def fail(error="invalid_grant", desc="the code or token is not valid", code=400):
        # review F4: the lock answers failed attempts only; a valid code / refresh token (32 random bytes) still works behind an
        # address that others (a chat app's shared exit) used for failures
        c.commit()  # what the failure changed (a revoked access) stays, also when the lock answers
        if _rate_blocked(_bad(ip)):
            return _oerr("slow_down", "too many failed attempts, wait a few minutes", 429, {"Retry-After": "900"})
        _rate_fail(_bad(ip))
        c.commit()
        return _oerr(error, desc, code)
    cl = _client(c, f.get("client_id", ""))
    if not cl:
        return fail("invalid_client", "unknown client_id", 401)
    gt = f.get("grant_type", "")
    if gt == "authorization_code":
        return _token_code(c, cl, f, fail)
    if gt == "refresh_token":
        return _token_refresh(c, cl, f, fail)
    return _oerr("unsupported_grant_type", "authorization_code or refresh_token")


def _token_code(c, cl, f, fail):
    h = _token_hash(f.get("code", "") or "-")
    row = c.execute("SELECT * FROM oauth_codes WHERE code_hash=?", (h,)).fetchone()
    if not row or row["client_id"] != cl["client_id"]:
        return fail()
    if row["used_at"] or not c.execute("UPDATE oauth_codes SET used_at=? WHERE code_hash=? AND used_at IS NULL RETURNING code_hash",
                                       (iso(now_utc()), h)).fetchone():
        if row["grant_id"]:  # RFC 6749 4.1.2: a code used twice - the access made with it ends
            mcpr_revoke(c, row["grant_id"])
        return fail()
    if parse_iso(row["expires_at"]) <= now_utc():
        return fail()
    ruri = f.get("redirect_uri", "")
    if (ruri or len(_uris(cl)) != 1) and ruri != row["redirect_uri"]:
        return fail(desc="redirect_uri differs")
    ver = f.get("code_verifier", "")
    if not VERIFIER_RE.fullmatch(ver) or not hmac.compare_digest(_b64u(hashlib.sha256(ver.encode()).digest()), row["challenge"]):
        return fail(desc="code_verifier does not match")
    if not _resource_ok(f.get("resource", "")):
        return fail("invalid_target", "unknown resource")
    if not mcpr_may(c, row["user_id"], row["agent_id"]):
        return fail(desc="the agent cannot be connected")
    gid = insert_id(c, "INSERT INTO oauth_grants(client_id,user_id,agent_id,created_at) VALUES(?,?,?,?)",
                    (cl["client_id"], row["user_id"], row["agent_id"], iso(now_utc())))
    c.execute("UPDATE oauth_codes SET grant_id=? WHERE code_hash=?", (gid, h))
    out = _issue(c, gid, row["agent_id"], cl["name"])
    c.commit()
    return _no_store(out)


def _token_refresh(c, cl, f, fail):
    h = _token_hash(f.get("refresh_token", "") or "-")
    gr = c.execute("SELECT * FROM oauth_grants WHERE refresh_hash=? AND revoked_at IS NULL", (h,)).fetchone()
    if not gr:
        old = c.execute("SELECT id FROM oauth_grants WHERE prev_refresh_hash=? AND revoked_at IS NULL", (h,)).fetchone()
        if old:  # a refresh token used a second time: someone else has it - the access ends (OAuth 2.1 4.3.1)
            mcpr_revoke(c, old["id"])
            print("hosted MCP: refresh token reused, access", old["id"], "revoked", flush=True)
        return fail()
    if gr["client_id"] != cl["client_id"]:
        return fail()
    if not gr["token_id"]:
        # review F1: the access token went outside the refresh ("New token" / deleting the token of the agent, a restore
        # that keeps it revoked): that ends the access, no new token (the refresh itself removes and sets it in one step)
        mcpr_revoke(c, gr["id"])
        print("hosted MCP: the access token of access", gr["id"], "was removed, access revoked", flush=True)
        return fail(desc="the access was ended")
    if mcpr_grant_end(gr["created_at"]) <= now_utc():
        # 2.674.0 (#4028, review F12): the longest life of an access is over (also one given before 2.674 with a later refresh
        # end): it ends; the app connects again through the consent page
        mcpr_revoke(c, gr["id"])
        print("hosted MCP: access", gr["id"], "reached its longest life, revoked", flush=True)
        return fail(desc=f"the access ended after {MCPR_GRANT_MAX_DAYS} days, connect again")
    if not gr["refresh_expires_at"] or parse_iso(gr["refresh_expires_at"]) <= now_utc():
        return fail(desc="the refresh token has expired")
    if not mcpr_may(c, gr["user_id"], gr["agent_id"], support=True):
        mcpr_revoke(c, gr["id"])
        return fail(desc="the agent cannot be connected any more")
    if not c.execute("UPDATE oauth_grants SET prev_refresh_hash=refresh_hash, refresh_hash=NULL WHERE id=? AND refresh_hash=? RETURNING id",
                     (gr["id"], h)).fetchone():
        return fail()  # used at the same moment by another request
    if gr["token_id"]:
        c.execute("DELETE FROM api_tokens WHERE id=?", (gr["token_id"],))
    out = _issue(c, gr["id"], gr["agent_id"], cl["name"])
    c.commit()
    return _no_store(out)


@app.post("/oauth/revoke")
def mcpr_revoke_route():
    """RFC 7009: an access or refresh token of this client; the whole access ends. Always 200 (no oracle)."""
    c = db()
    if not mcpr_on(c):
        return _gone()
    if hit_limit("oauthrev:" + rate_ip(), MCPR_REVOKE_LIMIT, 900):  # review F9
        return _oerr("slow_down", "too many requests from this address, try again later", 429, {"Retry-After": "900"})
    f = _form()
    cl = _client(c, f.get("client_id", ""))
    h = _token_hash(f.get("token", "") or "-")
    if cl:
        r = c.execute("""SELECT g.id FROM oauth_grants g LEFT JOIN api_tokens t ON t.id=g.token_id
                         WHERE g.client_id=? AND g.revoked_at IS NULL AND (g.refresh_hash=? OR t.token_hash=?)""",
                      (cl["client_id"], h, h)).fetchone()
        if r:
            mcpr_revoke(c, r["id"])
            c.commit()
    return _no_store({})


# ---------------------------------------------------------------- /mcp

def mcpr_module():
    """mcp/kalmido_mcp.py, loaded once by its path (the image: next to app.py; a checkout: mcp/), or None."""
    with _MOD_LOCK:
        if "m" not in _MOD:
            m = None
            for p in MCPR_FILES:
                if os.path.isfile(p):
                    spec = importlib.util.spec_from_file_location("kalmido_mcp_hosted", p)
                    m = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(m)
                    break
            _MOD["m"] = m
        return _MOD["m"]


_CLS = {}


_REFUSED = {}  # 2.1045.0 (#5827): token hash -> {step_ref: step} of InProc (Kalmido._keep_refused), the newest MCPR_REFUSED_TOKENS tokens
MCPR_REFUSED_TOKENS = 500


def _inproc_cls(mod):
    """kalmido_mcp.Kalmido whose requests go to this app in-process (Flask test client in a thread without a request of its
    own): the same /api/v1 checks as over the network, the client's address kept for the token's address rule."""
    if mod in _CLS:
        return _CLS[mod]

    class _Now(Exception):
        """review F3: an ApiError that Kalmido.call must not wait for and try again (it catches ApiError only)."""
        def __init__(self, e):
            super().__init__(e.message)
            self.e = e

    class InProc(mod.Kalmido):
        def __init__(self, token, ip, base_url, deadline=None):
            super().__init__("http://kalmido.invalid", token, timeout=mod.WAIT_MAX + 30)
            self.me_cache = {"at": 0.0, "v": None}  # per call of /mcp, never shared between tokens
            self.ip, self.base_url = ip, base_url
            self.environ_extra = {}  # 2.557.0 (#4670, review): a WSGI key no network request can set (headers become HTTP_*)
            self.deadline = deadline or (time.time() + MCPR_RUN_S)
            # 2.1045.0 (#5827): the refused steps (step_ref) outlive one /mcp request: kept per token in this process
            key = hashlib.sha256((token or "").encode()).hexdigest()
            with _RUN_LOCK:
                if key not in _REFUSED and len(_REFUSED) >= MCPR_REFUSED_TOKENS:
                    _REFUSED.pop(next(iter(_REFUSED)))
                self.refused = _REFUSED.setdefault(key, {})

        def call(self, method, path, query=None, body=None, timeout=None, multipart=None, binary_cap=None):
            # review F3: in the web process nothing waits: no sleeping before a call (rate limit) or between tries (429 / 503
            # go back to the client at once with their Retry-After), no call after the request's time is up, and the long poll
            # waits at most until shortly before it
            left = self.deadline - time.time()
            if left <= 1:
                raise mod.ApiError(504, f"HTTP 504: the time of this /mcp request ({MCPR_RUN_S} s) is used up; "
                                        "send the remaining calls in a new request")
            if path.startswith("/agent/events") and query and query.get("wait") is not None:
                try:
                    query = {**query, "wait": max(0, min(int(query["wait"]), int(left) - 5))}
                except (TypeError, ValueError):
                    pass
            try:
                return super().call(method, path, query, body, timeout, multipart, binary_cap)
            except _Now as n:
                raise n.e from None

        def _note_limit(self, headers):  # review F3: no waiting for an exhausted limit; the API answers 429 itself
            self.rl_until = 0.0

        def _send(self, req, timeout, binary_cap):
            u = urllib.parse.urlsplit(req.full_url)
            hdrs = {k: v for k, v in req.header_items() if k.lower() not in ("host", "content-length")}
            r = app.test_client().open(u.path, query_string=u.query, method=req.get_method(), headers=hdrs, data=req.data,
                                       base_url=self.base_url, environ_base={"REMOTE_ADDR": self.ip, **self.environ_extra})
            try:
                if binary_cap and r.status_code < 400:
                    return self._file(r, binary_cap)
                raw = r.get_data()
                if r.status_code >= 400:
                    msg = self._err_msg(r.status_code, raw)  # 2.1045.0 (#5827): + reason / step_ref as kalmido_mcp.py over the network
                    if r.status_code in (429, 503):
                        ra = mod._retry_after(r.headers, None)
                        raise _Now(mod.ApiError(r.status_code, msg + (f" (try again in {int(ra)} s)" if ra is not None else ""), ra))
                    raise mod.ApiError(r.status_code, msg)
                return json.loads(raw) if raw else {"ok": True}
            finally:
                r.close()

        def _file(self, r, cap):
            """review F7: a file answer read piece by piece and given up after cap bytes (as kalmido_mcp.py over the network):
            never the whole file in the memory of the web process before the limit."""
            try:
                n = int(r.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n > cap:
                raise mod.ApiError(413, f"the file has {n} bytes, more than max_bytes={cap}")
            buf, size = [], 0
            for chunk in r.response:
                if isinstance(chunk, str):
                    chunk = chunk.encode()
                size += len(chunk)
                if size > cap:
                    raise mod.ApiError(413, f"the file is larger than max_bytes={cap}")
                buf.append(chunk)
            return {"bytes": b"".join(buf), "mime": (r.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip(),
                    "name": mod._cd_name(r.headers.get("Content-Disposition") or "")}
    _CLS[mod] = InProc
    return InProc


def mcpr_body(limit=MCPR_MAX_BODY):
    """2.674.0 (#4028, review F10): the request body, at most limit + 1 bytes read from the stream in pieces (more = too large).
    request.get_data read a body without Content-Length (Transfer-Encoding: chunked) completely into memory before the cut."""
    s, buf = request.stream, bytearray()
    while len(buf) <= limit:
        b = s.read(min(65536, limit + 1 - len(buf)))
        if not b:
            break
        buf += b
    return bytes(buf)


def _unauth(error=None):
    v = f'Bearer resource_metadata="{mcpr_base()}/.well-known/oauth-protected-resource"'
    if error:
        v += f', error="{error}"'
    r = jsonify(error="unauthorized")
    r.status_code = 401
    r.headers["WWW-Authenticate"] = v
    return r


@app.post("/mcp")
@app.get("/mcp")
@app.delete("/mcp")
def mcpr_mcp():
    c = db()
    if not mcpr_on(c):
        return _gone()
    mod = mcpr_module()
    if mod is None:
        return jsonify(error="the hosted MCP access is not available: mcp/kalmido_mcp.py is missing in this installation"), 503
    origin = request.headers.get("Origin")
    if origin and not mcpr_origin_ok(origin):  # MCP 2025-06-18: Origin is checked; 2.674.0 (#4028, review F11): PUBLIC_URL when set
        return jsonify(error="origin not allowed"), 403
    auth = request.headers.get("Authorization", "")
    tok = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    ip = rate_ip()
    if not tok:
        return _unauth()
    gr = c.execute("""SELECT g.id, g.last_used_at, t.expires_at FROM oauth_grants g JOIN api_tokens t ON t.id=g.token_id
                      WHERE t.token_hash=? AND g.revoked_at IS NULL""", (_token_hash(tok),)).fetchone()
    if not gr or not gr["expires_at"] or parse_iso(gr["expires_at"]) <= now_utc():
        if not gr:  # as /api/v1: only an unknown token counts (and is limited), an expired one asks for the refresh
            if _rate_blocked(_mcp_bad(ip)):
                return jsonify(error="too many invalid tokens"), 429, {"Retry-After": "900"}
            _rate_fail(_mcp_bad(ip))
            c.commit()
        return _unauth("invalid_token")
    if request.method != "POST":  # no server-initiated stream, no sessions
        return jsonify(error="use POST"), 405, {"Allow": "POST"}
    if (request.content_length or 0) > MCPR_MAX_BODY:
        return jsonify(error="too large"), 413
    raw = mcpr_body()  # 2.674.0 (#4028, review F10): a body without Content-Length (chunked) is read in pieces up to the limit
    if len(raw) > MCPR_MAX_BODY:
        return jsonify(error="too large"), 413
    if not gr["last_used_at"] or (now_utc() - parse_iso(gr["last_used_at"])).total_seconds() >= MCPR_USED_EVERY:
        c.execute("UPDATE oauth_grants SET last_used_at=? WHERE id=?", (iso(now_utc()), gr["id"]))
    c.commit()  # nothing of this request stays open while the tools run
    text = raw.decode("utf-8", "replace")
    if text.lstrip()[:1] == "[":  # review F3: a batch runs one call after the other in one place: a few only
        try:
            n = len(json.loads(text))
        except (ValueError, TypeError):
            n = 0
        if n > MCPR_BATCH_MAX:
            return jsonify(jsonrpc="2.0", id=None, error={"code": -32600, "message": f"at most {MCPR_BATCH_MAX} messages in one batch"}), 400
    gid = gr["id"]
    with _RUN_LOCK:  # review F3: one access never takes more than MCPR_PER_GRANT of the places
        if _RUNNING.get(gid, 0) >= MCPR_PER_GRANT:
            return jsonify(error=f"at most {MCPR_PER_GRANT} requests of one access at once, try again"), 429, {"Retry-After": "5"}
        if not _SEM.acquire(blocking=False):
            return jsonify(error="busy, try again"), 503, {"Retry-After": "5"}
        _RUNNING[gid] = _RUNNING.get(gid, 0) + 1
    api = _inproc_cls(mod)(tok, client_ip(), request.host_url, time.time() + MCPR_RUN_S)
    box = {}

    def run():
        try:
            box["r"] = mod.handle_raw(api, text)
        except Exception as ex:  # noqa: BLE001  (an answer, never a hanging client)
            box["e"] = ex
        finally:
            with _RUN_LOCK:  # the places go back when the work really ended (a thread cannot be stopped from outside)
                _RUNNING[gid] -= 1
                if not _RUNNING[gid]:
                    del _RUNNING[gid]
            _SEM.release()
    th = threading.Thread(target=run, name="mcp-remote", daemon=True)  # its own thread: the calls are requests of their own
    th.start()
    th.join(MCPR_RUN_S + 15)  # the calls stop at MCPR_RUN_S (InProc.call); one running call may still finish
    if th.is_alive() or "e" in box:
        if "e" in box:
            print("hosted MCP: error", type(box["e"]).__name__, box["e"], flush=True)
        return jsonify(error="the tool call did not finish in time; a write may still have been made, check before sending it again"
                       if th.is_alive() else "the tool call failed"), 504 if th.is_alive() else 500
    if box.get("r") is None:
        return "", 202
    r = jsonify(box["r"])
    r.headers["Cache-Control"] = "no-store"
    return r


# ---------------------------------------------------------------- Settings > Agents: the accesses given

@app.get("/api/my/mcp-grants")
def mcpr_grants():
    """The hosted MCP accesses I gave or that use one of my agents: client, agent, given at, last used."""
    c = db()
    need_person(403, tr("Agents cannot use this endpoint"))
    rows = c.execute("""SELECT g.id, g.created_at, g.last_used_at, g.agent_id, g.user_id, cl.name AS client, cl.redirect_uris,
                               u.display_name, u.username FROM oauth_grants g JOIN oauth_clients cl ON cl.client_id=g.client_id
                        JOIN users u ON u.id=g.agent_id LEFT JOIN agents a ON a.user_id=g.agent_id
                        WHERE g.revoked_at IS NULL AND (g.user_id=? OR a.owner_id=?) ORDER BY g.id DESC""", (me(), me())).fetchall()
    out = []
    for r in rows:
        uris = _uris(r)
        out.append({"id": r["id"], "client": r["client"], "redirect_host": urllib.parse.urlsplit(uris[0]).netloc if uris else "",
                    "agent": {"id": r["agent_id"], "name": r["display_name"] or r["username"]}, "given_by_me": r["user_id"] == me(),
                    "created_at": r["created_at"], "last_used_at": r["last_used_at"]})
    return jsonify(on=mcpr_on(c), url=mcpr_resource() if PUBLIC_URL_SET else "", grants=out)  # 2.666.0 (#4074 5)


@app.delete("/api/my/mcp-grants/<int:gid>")
def mcpr_grant_delete(gid):
    c = db()
    need_person(403, tr("Agents cannot use this endpoint"))
    r = c.execute("""SELECT g.id FROM oauth_grants g LEFT JOIN agents a ON a.user_id=g.agent_id
                     WHERE g.id=? AND g.revoked_at IS NULL AND (g.user_id=? OR a.owner_id=?)""", (gid, me(), me())).fetchone()
    if not r:
        raise Denied(404)
    mcpr_revoke(c, gid)
    c.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- 2.674.0 (#4028, review F12): Administration > Agents

def _team_grants(c):
    """The open accesses of team agents (no owner) this instance admin may hand out (never a client's agent on a hosted
    server, as mcpr_agents), newest first per agent."""
    with system_ctx(c):  # names, times and the app of the accesses only, no content
        rows = c.execute("""SELECT g.id, g.created_at, g.last_used_at, g.agent_id, g.user_id, cl.name AS client, cl.redirect_uris,
                                   ua.display_name AS agent_name, ua.username AS agent_user, up.display_name AS person_name,
                                   up.username AS person_user
                            FROM oauth_grants g JOIN oauth_clients cl ON cl.client_id=g.client_id JOIN agents a ON a.user_id=g.agent_id
                            JOIN users ua ON ua.id=g.agent_id JOIN users up ON up.id=g.user_id
                            WHERE g.revoked_at IS NULL AND a.owner_id IS NULL ORDER BY g.agent_id, g.id DESC""").fetchall()
    may = {}
    for r in rows:
        if r["agent_id"] not in may:
            may[r["agent_id"]] = not op_foreign_account(c, r["agent_id"], note=False, grant=False)
    return [r for r in rows if may[r["agent_id"]]]


def _need_inst_admin():
    need_person(403, tr("Agents cannot use this endpoint"))
    if not g.user["is_admin"]:
        raise Denied(403)


@app.get("/api/admin/mcp-grants")
def mcpr_admin_grants():
    """The apps connected to team agents (hosted MCP access): agent, app, who gave the access, when, last used, its end."""
    c = db()
    _need_inst_admin()
    out = []
    for r in _team_grants(c):
        uris = _uris(r)
        out.append({"id": r["id"], "client": r["client"], "redirect_host": urllib.parse.urlsplit(uris[0]).netloc if uris else "",
                    "agent": {"id": r["agent_id"], "name": r["agent_name"] or r["agent_user"]},
                    "given_by": {"id": r["user_id"], "name": r["person_name"] or r["person_user"]},
                    "created_at": r["created_at"], "last_used_at": r["last_used_at"], "ends_at": iso(mcpr_grant_end(r["created_at"]))})
    return jsonify(on=mcpr_on(c), grants=out)


@app.delete("/api/admin/mcp-grants/<int:gid>")
def mcpr_admin_grant_delete(gid):
    c = db()
    _need_inst_admin()
    if gid not in {r["id"] for r in _team_grants(c)}:
        raise Denied(404)
    mcpr_revoke(c, gid)
    c.commit()
    print("hosted MCP: access", gid, "of a team agent revoked by admin", me(), flush=True)
    return jsonify(ok=True)
