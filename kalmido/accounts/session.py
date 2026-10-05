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
    if not AUTH_HEADER or request.path in PROXY_IGNORE or request.path.startswith(("/static/", ICAL_PREFIX, API_PREFIX, PUB_PREFIX, "/dav", "/.well-known/")):
        return ""
    v = (request.headers.get(AUTH_HEADER) or "").strip()
    return v if v and _peer_trusted() else ""


def _token_hash(t):
    return hashlib.sha256(t.encode()).hexdigest()


def client_ip():
    """The client's address: with a trusted proxy in front (KALMIDO_TRUSTED_PROXIES) the one it forwarded (proxy_mw already
    put it into REMOTE_ADDR), else the direct peer. 2.10.0 (#445): before, waitress dropped X-Forwarded-For, so every
    request behind a proxy had the proxy's address (one lockout for everyone, wrong addresses in logs)."""
    return (request.remote_addr or "")[:64]


def _is_open(path, method):
    return path in OPEN_PATHS or path.startswith(("/static/", ICAL_PREFIX, PUB_PREFIX, "/f/")) or (path in ("/share", "/capture") and method == "GET")  # 2.4.0: /capture (#187)


def rate_ip():
    """Client address for rate limits and alerts (2.10.0: the same as client_ip, see proxy_mw)."""
    return client_ip()


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
    if request.path.startswith(API_PREFIX) or request.path == API_PREFIX.rstrip("/"):
        return api_authenticate()  # bearer token only (package B)
    if request.path.startswith(("/dav/", "/.well-known/")) or request.path == "/dav":
        return None  # 2.9.0 (#435): CalDAV: HTTP Basic with an app password (dav_login), never a cookie or the proxy header
    if request.path.startswith(("/api/hooks/git/", "/api/hooks/issues/")) and request.method == "POST":
        return None  # 2.2.0: inbound Git webhook: no user, no proxy header, the HMAC signature is the credential
        # (2.18.0: also the error-report webhook: the secret token in its URL is the credential)
    if request.path.startswith(PUB_PREFIX):
        return None  # public list link: no user; the token in the path is the credential (see "public links")
    c = db()
    val = proxy_login_value()
    if val:
        u = c.execute("SELECT * FROM users WHERE proxy_login=? COLLATE NOCASE", (val,)).fetchone()
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
        setup = not c.execute("SELECT 1 FROM users").fetchone()
        return jsonify(error=tr("Please log in"), auth="setup" if setup else "login"), 401
    return redirect("/", 303)


_fails, _fail_lock = {}, threading.Lock()
_DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(16))  # same algorithm / parameters as real ones
FAIL_WINDOW = 900  # s


def _rate_keys(username, pre="", lim=(5, 20, 100)):
    """2.10.0 (#445): failed logins count per user name AND address ("u:name@ip", 5), per address ("ip:", 20) and, as a
    ceiling against slow attacks from many addresses, per user name alone ("uall:", 100). One attacker (one address) can
    no longer lock a person out: only the pair name + attacker's address and the attacker's address are blocked."""
    ip = client_ip()
    return [(pre + "u:" + username + "@" + ip, lim[0]), (pre + "ip:" + ip, lim[1]), (pre + "uall:" + username, lim[2])]


def _rate_reset(username, pre=""):
    """A successful login clears the counter of the pair user name + this address."""
    with _fail_lock:
        _fails.pop(pre + "u:" + username + "@" + client_ip(), None)


def _rate_blocked(keys):
    now = time.time()
    with _fail_lock:
        for k, limit in keys:
            arr = [t for t in _fails.get(k, []) if now - t < FAIL_WINDOW]
            _fails[k] = arr
            if len(arr) >= limit:
                return True
    return False


def _rate_fail(keys):
    """Records a failure; returns the keys whose limit this failure just reached (the rate limit trips)."""
    out = []
    with _fail_lock:
        for k, limit in keys:
            arr = _fails.setdefault(k, [])
            arr.append(time.time())
            if len(arr) == limit:
                out.append(k)
    return out


def start_session(c, uid, remember, via="password"):
    """A new session (always a new random token: a login never adopts a token the browser brought along).
    via: password | 2fa | passkey | oidc."""
    tok = secrets.token_urlsafe(32)
    days = SESSION_DAYS if remember else 1
    c.execute("DELETE FROM sessions WHERE expires_at<?", (iso(now_utc()),))
    c.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at,via) VALUES(?,?,?,?,?)",
              (_token_hash(tok), uid, iso(now_utc()), iso(now_utc() + timedelta(days=days)), via))
    return tok, (days * 86400 if remember else None)


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
