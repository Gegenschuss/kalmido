"""Who is asking: sessions, the proxy login, trusted proxies, the maintenance gate, login rate limits."""
import contextlib
import hashlib
import ipaddress
import secrets
import threading
import time
from datetime import timedelta
from flask import g, jsonify, redirect, request
from werkzeug.security import generate_password_hash

from ..core.config import (
    API_PREFIX, app, AUTH_HEADER, AUTH_PROXY_PORT, AUTH_TRUSTED, COOKIE, CSRF_HEADER, CSRF_VALUE, ICAL_PREFIX,
    OPEN_PATHS, PROXY_IGNORE, PUB_PREFIX, SESSION_DAYS, TRUSTED_PROXIES, TRUSTED_PROXY_COUNT, TRUSTED_PROXY_HEADERS,
)
from ..core.i18n import LANGS, tr
from ..core.db import db, err, iso, now_utc


# ---------------------------------------------------------------- auth

def me():
    return g.user["id"]


def _peer_trusted():
    """Direct peer is a trusted proxy (and the request came in on the proxy port, if one is set). 2.10.0 (#445): the peer
    and the port as they were BEFORE the forwarded headers were applied (proxy_mw keeps them in the environ)."""
    env = request.environ
    try:
        ip = ipaddress.ip_address(env.get("kalmido.peer", request.remote_addr) or "")
    except ValueError:
        return False
    if not any(ip in n for n in AUTH_TRUSTED):
        return False
    return not AUTH_PROXY_PORT or str(env.get("kalmido.port", env.get("SERVER_PORT", ""))) == AUTH_PROXY_PORT


def proxy_login_value():
    """The trusted proxy header of this request, or '' (not configured / untrusted peer / bypassed path)."""
    if not AUTH_HEADER or request.path in PROXY_IGNORE or request.path.startswith(("/static/", ICAL_PREFIX, API_PREFIX, PUB_PREFIX, "/dav", "/.well-known/")) \
            or request.path.startswith(PT_PREFIXES) or request.path == "/portal":  # 2.63.0 B (#1513): the reporter has no account
        return ""
    v = (request.headers.get(AUTH_HEADER) or "").strip()
    return v if v and _peer_trusted() else ""


PT_PREFIXES = ("/p/", "/portal/")  # 2.63.0 B (#1513): a customer report's status link, the portal's sign-in / sign-out


OPERATOR_PATHS = frozenset(("/api/operator/status", "/api/operator/setup-code", "/api/operator/notice"))  # 2.144.0 D2 (#797)


def _token_hash(t):
    return hashlib.sha256(t.encode()).hexdigest()


def client_ip():
    """The client's address: with a trusted proxy in front (KALMIDO_TRUSTED_PROXIES) the one it forwarded (proxy_mw already
    put it into REMOTE_ADDR), else the direct peer. 2.10.0 (#445): before, waitress dropped X-Forwarded-For, so every
    request behind a proxy had the proxy's address (one lockout for everyone, wrong addresses in logs)."""
    return (request.remote_addr or "")[:64]


def _is_open(path, method):
    return path in OPEN_PATHS or path.startswith(("/static/", ICAL_PREFIX, PUB_PREFIX, "/f/", "/u/")) or (path in ("/share", "/capture") and method == "GET") \
        or path.startswith(PT_PREFIXES) or path == "/portal"  # 2.4.0: /capture (#187); 2.63.0 B (#1513): status links + the customer portal; 2.122.0 A (#2097): /u/ file requests


def rate_ip():
    """Client address for rate limits and alerts (2.10.0: the same as client_ip, see proxy_mw).
    2.126.0 C (#1976): the counter key of an address: IPv4 as it is, IPv6 as its /64 network (one connection usually
    owns a whole /64), an IPv4-mapped IPv6 address as the IPv4 one. Logs and token address checks keep client_ip()."""
    return rate_key_ip(client_ip())


def rate_key_ip(addr):
    """2.126.0 C (#1976): see rate_ip."""
    try:
        a = ipaddress.ip_address((addr or "").split("%")[0])
    except ValueError:
        return addr or ""
    if a.version == 6 and a.ipv4_mapped:
        return str(a.ipv4_mapped)
    if a.version == 6:
        return str(ipaddress.ip_network(f"{a}/64", strict=False).network_address)
    return str(a)


def _ip_in(addr, nets):
    try:
        ip = ipaddress.ip_address((addr or "").split("%")[0])
    except ValueError:
        return False
    return any(ip in n for n in nets)


def proxy_mw(wsgi):
    """2.10.0 (#445): X-Forwarded-For / -Proto / -Host only from a trusted proxy (TRUSTED_PROXIES, networks allowed), parsed
    by waitress' own code (trusted_proxy_count = TRUSTED_PROXY_COUNT): REMOTE_ADDR = the client, wsgi.url_scheme = https
    behind a TLS proxy, Host = the public name. From anyone else every proxy header is removed. The original peer and
    port stay in the environ (kalmido.peer / kalmido.port) for the proxy login (_peer_trusted)."""
    try:
        from waitress.proxy_headers import PROXY_HEADERS, MalformedProxyHeader, clear_untrusted_headers, parse_proxy_headers
    except ImportError:  # no waitress (another WSGI server): never believe forwarded headers
        PROXY_HEADERS, parse_proxy_headers = None, None

    def mw(environ, start_response):
        environ["kalmido.peer"] = environ.get("REMOTE_ADDR", "")
        environ["kalmido.port"] = str(environ.get("SERVER_PORT", ""))
        if parse_proxy_headers is None:
            for k in [k for k in environ if k.startswith("HTTP_X_FORWARDED_") or k == "HTTP_FORWARDED"]:
                del environ[k]
            return wsgi(environ, start_response)
        untrusted = PROXY_HEADERS
        if _ip_in(environ["kalmido.peer"], TRUSTED_PROXIES):
            environ["kalmido.fwd_proto"] = (environ.get("HTTP_X_FORWARDED_PROTO") or "").split(",")[-1].strip().lower()
            try:
                untrusted = parse_proxy_headers(environ, trusted_proxy_count=TRUSTED_PROXY_COUNT,
                                                trusted_proxy_headers=TRUSTED_PROXY_HEADERS)
            except MalformedProxyHeader as ex:
                print("malformed proxy header", ex.header, "from", environ["kalmido.peer"], flush=True)
                start_response("400 Bad Request", [("Content-Type", "text/plain; charset=utf-8")])
                return [b"Malformed proxy header\n"]
        clear_untrusted_headers(environ, untrusted)
        return wsgi(environ, start_response)
    return mw


app.wsgi_app = proxy_mw(app.wsgi_app)


# ---- maintenance gate (restore of a backup). Every request and every background tick is an "active holder"; a
# restore switches maintenance on, waits until it is the only holder left, swaps the data and switches it off.
# Meanwhile new requests get 503 (except the health check and static files) and background threads wait.
_BG_TURN = {"f": None}  # 2.102.0 D (#1997): admin/worker.py wrk_turn -- a background loop runs in one process at a time


class _Gate:
    def __init__(self):
        self.cond = threading.Condition()
        self.active = 0
        self.maint = False

    def enter(self, block):
        with self.cond:
            if self.maint:
                if not block:
                    return False
                self.cond.wait_for(lambda: not self.maint)
            self.active += 1
            return True

    def leave(self):
        with self.cond:
            self.active -= 1
            self.cond.notify_all()

    @contextlib.contextmanager
    def bg(self):
        if _BG_TURN["f"] is not None:  # 2.102.0 D (#1997): waits while another process runs this loop
            _BG_TURN["f"]()
        self.enter(True)
        try:
            yield
        finally:
            self.leave()

    def begin(self, own, timeout):
        """Maintenance on once at most `own` holders (the caller itself) are left; False after `timeout` s."""
        with self.cond:
            if self.maint:
                return False
            self.maint = True
            if not self.cond.wait_for(lambda: self.active <= own, timeout):
                self.maint = False
                self.cond.notify_all()
                return False
            return True

    def end(self):
        with self.cond:
            self.maint = False
            self.cond.notify_all()


GATE = _Gate()


def _accept_lang(default="en"):
    """UI language from the browser (no database access: used while a restore runs). Accept-Language in its order,
    region dropped (fr-CA -> fr); 2.11.0: every language file counts (de, fr, es, it, nl)."""
    for part in (request.headers.get("Accept-Language") or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return default


@app.before_request
def maint_gate():
    g.gate = False
    if request.path == "/api/health" or request.path.startswith("/static/"):
        return None
    if not GATE.enter(False):
        return jsonify(error=tr("The server is restoring a backup, please try again in a minute", lg=_accept_lang()),
                       maint=True), 503
    g.gate = True
    return None


@app.teardown_request
def maint_leave(_):
    if g.pop("gate", False):
        GATE.leave()


@app.before_request
def authenticate():
    from ..api.v1 import api_authenticate
    from ..agents.core import is_agent
    from ..family.family import KID_WRITE
    g.user, g.auth_via, g.auth_error, g.proxy_login, g.pushes = None, None, None, "", []
    if request.path.startswith("/static/") or request.path in ("/sw.js", "/sw-manifest.json", "/robots.txt"):
        return None  # 2.149.0 B (#2505): files that are the same for everyone: no session and no database access
    if request.path.startswith(API_PREFIX) or request.path == API_PREFIX.rstrip("/"):
        return api_authenticate()  # bearer token only (package B)
    if request.path.startswith(("/dav/", "/.well-known/")) or request.path == "/dav":
        return None  # 2.9.0 (#435): CalDAV: HTTP Basic with an app password (dav_login), never a cookie or the proxy header
    if request.path.startswith(("/api/hooks/git/", "/api/hooks/issues/", "/api/hooks/deploy/", "/api/hooks/in/")) and request.method == "POST":
        return None  # 2.2.0: inbound Git webhook: no user, no proxy header, the HMAC signature is the credential
        # (2.18.0: also the error-report webhook: the secret token in its URL is the credential; 2.60.0: and the deploy hook)
        # (2.115.0 A (#2061): and the inbound webhook of a list)
    if request.path in OPERATOR_PATHS:  # 2.144.0 D2 (#797): exact paths, a later route under /api/operator/ is not let through
        return None  # 2.144.0 D (#797): the hosting operator's interface: its own token (admin/operator.py), never a person
    if request.path.startswith(PUB_PREFIX):
        return None  # public list link: no user; the token in the path is the credential (see "public links")
    c = db()
    val = proxy_login_value()
    if val:
        u = c.execute("SELECT * FROM users WHERE lower(proxy_login)=lower(?)", (val,)).fetchone()
        if u and not u["disabled"] and not is_agent(u):
            g.user, g.auth_via = u, "proxy"
        else:
            g.auth_error, g.proxy_login = ("disabled" if u else "no_account"), val
    if not g.user and not g.auth_error:
        tok = request.cookies.get(COOKIE)
        if tok:
            r = c.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                             WHERE s.token_hash=? AND s.expires_at>? AND u.disabled=0 AND u.kind!='agent'""",
                          (_token_hash(tok), iso(now_utc()))).fetchone()
            if r:
                g.user, g.auth_via = r, "session"
                from ..accounts.sessions import ses_touch
                ses_touch(c, _token_hash(tok))  # 2.115.0 B (#2062): last activity, at most every few minutes
    path = request.path
    if request.method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/") \
            and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        return err(tr("Request blocked: header {0} missing", CSRF_HEADER), 403)
    if g.user and g.user["kid"] and request.method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/") \
            and not KID_WRITE.match(path):
        return err(tr("Not possible with a child account"), 403)  # 2.19.0: a child ticks, asks and sets up the account only
    if g.user or _is_open(path, request.method):
        return None
    if path.startswith("/api/"):
        if g.auth_error:
            msg = tr("This account is disabled") if g.auth_error == "disabled" else tr("No account for {0}", g.proxy_login)
            return jsonify(error=msg, auth=g.auth_error, login=g.proxy_login), 403
        if path.startswith("/api/office/") and (request.headers.get("Authorization") or "").lower().startswith("bearer "):
            return err(tr("Tokens cannot use this endpoint"), 403)  # 2.36.2 E (#1146): agent tokens never reach office & finance
        setup = not c.execute("SELECT 1 FROM users").fetchone()
        return jsonify(error=tr("Please log in"), auth="setup" if setup else "login"), 401
    return redirect("/", 303)


_fails, _fail_lock = {}, threading.Lock()
_DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(16))  # same algorithm / parameters as real ones
FAIL_WINDOW = 900  # s


@app.before_request
def acx_bind():
    """2.37.0 (#1150): the signed-in account's access context goes onto the request's database connection (user id,
    organisations, role; core/access.py acx_session_apply). Since 2.37.0 part 2 every statement on a pooled connection also
    asks core/access.py acx_conn_hook, so a route that sets g.user later (DAV, public links, forms, hooks) is covered too;
    a request without an account reads as "anon" (no organisation unless a public path bound one), never as "system"."""
    if getattr(g, "user", None) is not None:
        from ..core.access import acx
        acx()


def _rate_keys(username, pre="", lim=(5, 20, 100)):
    """2.10.0 (#445): failed logins count per user name AND address ("u:name@ip", 5), per address ("ip:", 20) and, as a
    ceiling against slow attacks from many addresses, per user name alone ("uall:", 100). One attacker (one address) can
    no longer lock a person out: only the pair name + attacker's address and the attacker's address are blocked."""
    ip = rate_ip()  # 2.126.0 C (#1976): IPv6 per /64
    return [(pre + "u:" + username + "@" + ip, lim[0]), (pre + "ip:" + ip, lim[1]), (pre + "uall:" + username, lim[2])]


_known = {}       # 2.86.0 (N2): "<pre>uall:<name>" -> {address: time of the last successful login from there}
KNOWN_DAYS = 30


def _rate_reset(username, pre=""):
    """A successful login clears the counter of the pair user name + this address and remembers the address as known."""
    ip = rate_ip()  # 2.126.0 C (#1976)
    with _fail_lock:
        _fails.pop(pre + "u:" + username + "@" + ip, None)
        seen = _known.setdefault(pre + "uall:" + username, {})
        seen[ip] = time.time()
        if len(seen) > 20:  # a handful of addresses per account is enough (home, phone, office)
            for old in sorted(seen, key=seen.get)[:len(seen) - 20]:
                seen.pop(old, None)


def h6a_uall_exempt(k, now):
    """2.86.0 (N2): the per-name ceiling ("uall:", many addresses) does not lock out the account's owner: it is skipped
    for an address this account logged in from successfully before (last KNOWN_DAYS days) and for a request that is
    signed in as this account already (re-authentication). The pair and address limits still apply everywhere."""
    if "uall:" not in k:
        return False
    if (now - _known.get(k, {}).get(rate_ip(), 0)) < KNOWN_DAYS * 86400:
        return True
    u = getattr(g, "user", None)
    return bool(u is not None and k == "uall:" + (u["username"] or ""))


def _rate_blocked(keys):
    now = time.time()
    with _fail_lock:
        for k, limit in keys:
            arr = [t for t in _fails.get(k, []) if now - t < FAIL_WINDOW]
            if arr:
                _fails[k] = arr
            else:  # 2.126.0 review (#1976): a look-up never adds a key (only failures do)
                _fails.pop(k, None)
            if len(arr) >= limit and not h6a_uall_exempt(k, now):
                return True
    return False


_FAILS_MAX, _FAILS_ARR = 20000, 500  # 2.126.0 C (#1976): idle keys are forgotten above this many; per key the newest 500
_fails_swept = [0.0]


def _rate_fail(keys):
    """Records a failure; returns the keys whose limit this failure just reached (the rate limit trips)."""
    out = []
    now = time.time()
    with _fail_lock:
        for k, limit in keys:
            arr = _fails.setdefault(k, [])
            arr.append(now)
            if len(arr) == limit:
                out.append(k)
            if len(arr) > _FAILS_ARR:
                del arr[:len(arr) - _FAILS_ARR]
        if len(_fails) > _FAILS_MAX and now - _fails_swept[0] > 30:  # 2.126.0 C (#1976): forget keys idle for a window
            _fails_swept[0] = now
            for k in [k for k, v in _fails.items() if not v or now - v[-1] >= FAIL_WINDOW]:
                _fails.pop(k, None)
    return out


def start_session(c, uid, remember, via="password"):
    """A new session (always a new random token: a login never adopts a token the browser brought along).
    via: password | 2fa | passkey | oidc."""
    tok = secrets.token_urlsafe(32)
    days = SESSION_DAYS if remember else 1
    c.execute("DELETE FROM sessions WHERE expires_at<?", (iso(now_utc()),))
    from flask import has_request_context
    from ..accounts.sessions import ses_ua  # 2.115.0 B (#2062): last activity + the browser for "Active sessions"
    c.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at,via,last_seen_at,user_agent) VALUES(?,?,?,?,?,?,?)",
              (_token_hash(tok), uid, iso(now_utc()), iso(now_utc() + timedelta(days=days)), via, iso(now_utc()),
               ses_ua() if has_request_context() else ""))
    from ..admin.clientip import login_seen
    login_seen(c, uid)  # 2.33.0 (#834): many accounts from one private address = the proxy hides the client addresses
    from flask import has_request_context
    from ..notify.sev import sev_login
    sev_login(c, uid, client_ip() if has_request_context() else "", via)  # 2.36.2 (#1133): an admin from a new address
    return tok,(days * 86400 if remember else None)


def set_cookie(resp, tok, max_age):
    secure = request.is_secure or request.headers.get("X-Forwarded-Proto", "") == "https"
    resp.set_cookie(COOKIE, tok, max_age=max_age, httponly=True, samesite="Lax", secure=secure, path="/")
    return resp


def user_public(u):
    from ..accounts.pictures import avatar_url
    from ..agents.core import is_agent
    return {"id": u["id"], "username": u["username"], "display_name": u["display_name"] or u["username"],
            "avatar": avatar_url(u), **({"agent": True} if is_agent(u) else {}),
            **({"kid": True} if "kid" in u.keys() and u["kid"] else {})}  # 2.19.0 (#653): a kid account
