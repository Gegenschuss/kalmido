"""2.73.0 A (#661): several Kalmido servers in one app (stage 1, no sync, no federation). A person keeps accounts on other
Kalmido servers (work + home); the app shows them together (static/js/msvview.js) and this server -- the "home" server the
app runs on -- talks to the other server's documented /api/v1 on the person's behalf with the person's personal API token
there. The browser only ever talks to this server: no CORS, no CSP change, no token in the browser.

- msv_links: the accounts of one person (private, no org_id). The token is sealed with a key derived from the server key
  per person and never leaves the server (not in answers, logs or the export).
- Nothing of the other server is stored: /data is held in memory for at most MSV_CACHE_S seconds per account (parallel
  requests of the views fall together), at most MSV_PAR requests per person at once.
- Every request goes through the SSRF guard of the calendar subscriptions (_cal_opener: public addresses only, no
  redirects, every resolved address checked). Hosted servers: https only, no internal hosts; self-hosted: the admin's
  allow-list of internal hosts (Settings > Calendars), so company servers in the internal network work -- http only to
  those (review M3).
- Errors of the other side answer 424 {error, code}: offline | auth | denied | notfound | rate | version | invalid.
- People only (cookie session / sign-in proxy): agents and API tokens get 403 -- an agent sees only its own server."""
import base64
import binascii
import functools
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from flask import g, jsonify, request

from ..core.config import app, APP_NAME, APP_VERSION, PUBLIC_URL, SECRET_KEY
from ..core.pg import insert_id
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc, uset, usettings
from ..core.access import Denied, list_role, need_task, WRITE_ROLES
from ..core.serializers import load_tasks
from ..accounts.session import me
from ..accounts.colors import ACCOUNT_COLORS
from ..calendars.subscriptions import _CalHTTPConnection, _CalHTTPSConnection, cal_allow, cal_host_allowed, cal_ip_public, CalError
from ..core.orgcrypt import oc_dec_k, oc_enc_k, OrgCryptError  # 2.149.0 G (#2517): pulled up from functions
from ..api.common import hit_limit, v1_call, V1Error  # 2.149.0 G (#2517): pulled up from functions

MSV_MAX = 10                       # accounts per person
MSV_TIMEOUT = 8                    # s per request to the other server (socket + whole answer)
MSV_ADDRS = 3                      # addresses tried per connect (review 2)
MSV_CONNECT = 3                    # s to connect (review H1: a dead address frees the thread early)
MSV_MAX_BYTES = 8 * 1024 * 1024    # per answer
MSV_ERR_BYTES = 64 * 1024          # of an error answer (only its message is used)
MSV_CACHE_S = 15                   # /data held in memory per account
MSV_PAR = 4                        # requests to other servers per person at once
MSV_PAR_ALL = 6                    # requests to other servers at once on this server (under half of the waitress threads)
MSV_READS = 120                    # reads of other servers per person and minute (review H1)
MSV_TOKEN_KEEP_D = 30               # days a removed account keeps its sealed token (undo); then it is wiped (review N1)
MSV_FRESH_S = 5                    # ?fresh=1 skips the memory at most this often per account
MSV_TASKS_MAX = 3000               # open tasks per account in /data
MSV_TRIES = 60                     # connection tries (a new account / token) per person and hour
MSV_SCOPES = ("read", "tasks:write", "delete", "calendar", "comments")  # what a connection code's token gets
MSV_CODE = "kalmido-link:"
MSV_UA = f"{APP_NAME}/{APP_VERSION} (multi-server)"
MSV_DEFAULT_COLOR = "#6e56cf"      # the violet of ACCOUNT_COLORS: this server's badge by default
MSV_PRIOS = ("none", "low", "medium", "high")
MSV_STATUS = ("open", "done", "wont_do")
MSV_TEXT = {
    "offline": N_("The server cannot be reached"),
    "blocked": N_("This address is in an internal network; this server may not reach it"),
    "https": N_("This server only connects to https:// addresses"),
    "auth": N_("The token is not valid any more (revoked or expired). Connect again with a new token."),
    "denied": N_("The token lacks the permission “{0}”"),
    "notfound": N_("Not found on the other server"),
    "rate": N_("The other server asks to wait a moment ({0} s)"),
    "version": N_("This address is not a Kalmido server (or its API is off)"),
    "invalid": N_("The other server refused it: {0}"),
    "redirect": N_("The address forwards elsewhere – enter the address the app runs on (with https://)"),
    "too_large": N_("The answer of the other server is too large"),
    "busy": N_("Too many requests to other servers at once – try again in a moment"),
}
MSV_LINK_ERRS = ("offline", "auth", "version")  # stored on the account (its state); the others concern one request
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME = re.compile(r"\d{2}:\d{2}")
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_SHORT = re.compile(r"[A-Z0-9]{1,3}")
_TOKEN = re.compile(r"[A-Za-z0-9_.~-]{12,300}")


class MsvError(Exception):
    """A failure of the other server (or of the way there): code + the readable text; never its token."""
    def __init__(self, code, arg="", retry=None, scope=None):
        super().__init__(code)
        self.code, self.arg, self.retry, self.scope = code, arg, retry, scope

    def api_code(self):
        return {"blocked": "offline", "https": "offline", "redirect": "version", "too_large": "invalid"}.get(self.code, self.code)

    def text(self):
        t = MSV_TEXT.get(self.code, MSV_TEXT["offline"])
        if self.code == "denied":
            return tr(t, self.scope or "?")
        if self.code in ("rate", "busy"):
            return tr(t, self.retry or 5)
        if self.code == "invalid":
            return tr(t, self.arg or tr("Error"))
        return tr(t)


@app.errorhandler(MsvError)
def msv_error(e):
    out = {"error": e.text(), "code": e.api_code()}
    if e.retry:
        out["retry_after"] = e.retry
    if e.scope:
        out["scope"] = e.scope
    return jsonify(out), 424


def msv_gate():
    """People only: a cookie session or the sign-in proxy. Agents and API tokens never reach other servers."""
    from ..agents.core import is_agent
    u = g.get("user")
    if not u or g.get("auth_via") not in ("session", "proxy") or is_agent(u):
        raise Denied(403)
    return u["id"]


# ---- the token: sealed with a key derived from the server key per person (like paperless/ngx.py _token_key)
_KEYS = {}


def _msv_key(uid):
    if not SECRET_KEY:
        return None
    k = _KEYS.get(uid)
    if k is None:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        k = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"kalmido-msv-token-v1|" + str(uid).encode()).derive(SECRET_KEY)
        _KEYS[uid] = k
    return k


def msv_seal(uid, tok):
    key = _msv_key(uid)
    return oc_enc_k(key, 0, f"msv_links.token|{uid}", tok) if key and tok else None


def msv_token(r):
    v = r["token_enc"] or ""
    key = _msv_key(r["user_id"])
    if not v or not key:
        return ""
    try:
        out = oc_dec_k(key, 0, f"msv_links.token|{r['user_id']}", v)
    except OrgCryptError:
        return ""
    return "" if out == v else out  # a plain value is never accepted


# ---- addresses
def msv_norm_url(u):
    """'https://host[:port][/path]' (lower-case scheme + host, no trailing / or /api/v1, no query / fragment) or None."""
    u = str(u or "").strip()
    if not u or len(u) > 500 or any(ch.isspace() or ord(ch) < 32 for ch in u):
        return None
    if "://" not in u:
        u = "https://" + u
    p = urllib.parse.urlsplit(u)
    try:
        port = p.port
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not p.hostname or p.username or p.password:
        return None
    path = p.path.rstrip("/")
    if path.lower().endswith("/api/v1"):
        path = path[:-7].rstrip("/")
    if not re.fullmatch(r"(/[A-Za-z0-9._~-]+)*", path) or any(x in (".", "..") for x in path.split("/")):
        return None
    host = p.hostname.lower().rstrip(".")
    return f"{p.scheme.lower()}://{'[' + host + ']' if ':' in host else host}{f':{port}' if port else ''}{path}"


def msv_allow(c, base):
    """The SSRF allow-list for one address: hosted = https only and no internal host; self-hosted = the calendar's."""
    from ..admin.hosting import hosted
    if hosted():
        if not base.startswith("https://"):
            raise MsvError("https")
        return frozenset()
    allow = cal_allow(c)
    if base.startswith("http://"):  # review M3: plain http only to an internal host of the admin's allow-list
        p = urllib.parse.urlsplit(base)
        if not cal_host_allowed(allow, p.hostname, p.port or 80):
            raise MsvError("blocked" if _msv_internal(p.hostname, p.port or 80) else "https")
    return allow


def _msv_internal(host, port):  # noqa: ARG001
    """True when host is plainly internal (the SSRF guard refuses it as 'blocked'), False otherwise: then the token would
    cross the internet unencrypted. Only chooses the message: http never goes out without the allow-list. No DNS lookup
    here (review 2: a silent resolver must not hold the request thread) -- an IP literal or a local name only."""
    h = str(host or "").lower().strip("[]").rstrip(".")
    try:
        ipaddress.ip_address(h.split("%", 1)[0])
        return not cal_ip_public(h)
    except ValueError:
        pass
    return h == "localhost" or h.endswith((".localhost", ".local", ".lan", ".internal", ".home.arpa")) or "." not in h


def msv_is_self(base):
    return base == msv_norm_url(PUBLIC_URL)


# ---- requests to the other server
# 2.73.0 A (#661) review H1: a slow other server must never hold this server's request threads -- the slots are taken
# without waiting (none free = 424 busy at once), per person (MSV_PAR) and for the whole server (MSV_PAR_ALL)
_SEMS, _SEM_LOCK = {}, threading.Lock()
_SEM_ALL = threading.BoundedSemaphore(MSV_PAR_ALL)


def _sem(uid):
    with _SEM_LOCK:
        s = _SEMS.get(uid)
        if s is None:
            s = _SEMS[uid] = threading.BoundedSemaphore(MSV_PAR)
        return s


def _msv_connector(allow):
    """The SSRF guard of _cal_connector (every address checked, connect to exactly a checked one), but with ONE connect
    deadline of MSV_CONNECT over at most MSV_ADDRS addresses (review 2: a name with many silent addresses must not hold a
    slot for addresses x timeout); then the socket waits up to its read timeout."""
    def create(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *a, **k):  # noqa: ARG001
        host, port = address
        trusted = cal_host_allowed(allow, host, port)
        try:
            infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        except (socket.gaierror, UnicodeError) as e:
            raise CalError("network") from e
        end, fail, tried = time.monotonic() + MSV_CONNECT, None, 0
        for fam, typ, proto, _, sa in infos:
            if not trusted and not cal_ip_public(sa[0]):
                fail = fail or CalError("blocked")
                continue
            left = end - time.monotonic()
            if tried >= MSV_ADDRS or left <= 0:
                break
            tried += 1
            sk = socket.socket(fam, typ, proto)
            try:
                sk.settimeout(left)
                sk.connect(sa)  # exactly the checked address
                sk.settimeout(None if timeout is socket._GLOBAL_DEFAULT_TIMEOUT else timeout)
                return sk
            except OSError as e:
                sk.close()
                fail = e
        raise fail or CalError("network")
    return create


class _MsvHTTPConnection(_CalHTTPConnection):
    def __init__(self, *a, cal_allow=frozenset(), **k):
        super().__init__(*a, cal_allow=cal_allow, **k)
        self._create_connection = _msv_connector(cal_allow)


class _MsvHTTPSConnection(_CalHTTPSConnection):
    def __init__(self, *a, cal_allow=frozenset(), **k):
        super().__init__(*a, cal_allow=cal_allow, **k)
        self._create_connection = _msv_connector(cal_allow)


class _MsvHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, allow):
        super().__init__()
        self._allow = allow

    def http_open(self, req):
        return self.do_open(functools.partial(_MsvHTTPConnection, cal_allow=self._allow), req)


class _MsvHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, allow):
        super().__init__(context=ssl.create_default_context())
        self._allow = allow

    def https_open(self, req):
        return self.do_open(functools.partial(_MsvHTTPSConnection, cal_allow=self._allow), req, context=self._context)


def _msv_opener(allow):
    """Like _cal_opener (no proxy, no redirects), with the separate connect timeout."""
    o = urllib.request.OpenerDirector()
    for h in (_MsvHTTPHandler(allow), _MsvHTTPSHandler(allow), urllib.request.HTTPDefaultErrorHandler(),
              urllib.request.HTTPErrorProcessor()):
        o.add_handler(h)
    return o


def _read(r, cap, deadline):
    cl = (r.headers.get("Content-Length") or "") if r.headers else ""
    if cl.isdigit() and int(cl) > cap:
        raise MsvError("too_large")
    chunks, n = [], 0
    while True:
        if time.monotonic() > deadline:
            raise MsvError("offline")
        b = r.read(65536)
        if not b:
            return b"".join(chunks)
        n += len(b)
        if n > cap:
            raise MsvError("too_large")
        chunks.append(b)


_NOJSON = object()


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):  # RecursionError: absurdly nested JSON
        return _NOJSON


def msv_http(base, tok, path, method="GET", query=None, payload=None, allow=frozenset()):
    """One request to base + /api/v1 + path. Returns (status, headers, JSON value | _NOJSON). Network failures raise
    MsvError (offline / blocked); redirects are never followed (the caller sees 3xx)."""
    url = base + "/api/v1" + path + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(payload).encode() if payload is not None else None
    hd = {"Authorization": "Bearer " + tok, "Accept": "application/json", "User-Agent": MSV_UA}
    if data is not None:
        hd["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hd)
    deadline = time.monotonic() + MSV_TIMEOUT
    try:
        r = _msv_opener(allow).open(req, timeout=MSV_TIMEOUT)
    except urllib.error.HTTPError as e:
        try:
            raw = _read(e, MSV_ERR_BYTES, deadline) if e.fp else b""
        except (MsvError, OSError, http.client.HTTPException):
            raw = b""
        finally:
            e.close()
        return e.code, e.headers, _json(raw) if raw else _NOJSON
    except urllib.error.URLError as e:
        rs = e.reason
        raise MsvError("blocked" if isinstance(rs, CalError) and rs.code == "blocked" else "offline") from None
    except CalError as e:
        raise MsvError("blocked" if e.code == "blocked" else "offline") from None
    except (ssl.SSLError, TimeoutError, socket.timeout, OSError, http.client.HTTPException, ValueError):
        raise MsvError("offline") from None
    try:
        with r:
            raw = _read(r, MSV_MAX_BYTES, deadline)
            st, hdrs = r.status, r.headers
    except (ssl.SSLError, TimeoutError, socket.timeout, OSError, http.client.HTTPException, ValueError):
        raise MsvError("offline") from None
    if st == 204 or not raw:
        return st, hdrs, {}
    if "json" not in (hdrs.get("Content-Type") or "").lower():
        return st, hdrs, _NOJSON
    return st, hdrs, _json(raw)


def _err_msg(j):
    e = j.get("error") if isinstance(j, dict) else None
    m = e.get("message") if isinstance(e, dict) else e
    return _txt(m, 200) if isinstance(m, str) else ""


def msv_call(c, link, path, method="GET", query=None, payload=None, base=None, tok=None):
    """A request as the person over there; the answer's JSON (dict) or MsvError. base / tok: an account not stored yet."""
    base = base or link["base_url"]
    tok = tok if tok is not None else msv_token(link)
    if not tok:
        raise MsvError("auth")
    allow = msv_allow(c, base)
    s = _sem(me())
    if not s.acquire(blocking=False):  # review H1: never wait for a slot
        raise MsvError("busy", retry=2)
    try:
        if not _SEM_ALL.acquire(blocking=False):
            raise MsvError("busy", retry=2)
        try:
            st, hdrs, j = msv_http(base, tok, path, method, query, payload, allow)
        finally:
            _SEM_ALL.release()
    finally:
        s.release()
    if 200 <= st < 300:
        if j is _NOJSON or not isinstance(j, dict):
            raise MsvError("version")
        return j
    if 300 <= st < 400:
        raise MsvError("redirect")
    if st == 401:
        raise MsvError("auth")
    if st == 403:
        e = j.get("error") if isinstance(j, dict) else None
        sc = e.get("required_scope") if isinstance(e, dict) else None
        if isinstance(sc, str) and re.fullmatch(r"[a-z:-]{2,30}", sc):
            raise MsvError("denied", scope=sc)
        raise MsvError("invalid", _err_msg(j) or tr("No permission"))
    if st == 404:
        raise MsvError("version" if j is _NOJSON else "notfound")
    if st == 429:
        ra = (hdrs.get("Retry-After") or "") if hdrs else ""
        raise MsvError("rate", retry=max(1, min(int(ra), 3600)) if ra.isdigit() else 30)
    if st >= 500:
        raise MsvError("offline")
    raise MsvError("invalid", _err_msg(j) or str(st))


def msv_req(c, link, path, method="GET", query=None, payload=None):
    """msv_call + the account's state (last_ok / last_err), written only when it changes between ok and an error."""
    try:
        j = msv_call(c, link, path, method, query, payload)
    except MsvError as e:
        code = e.api_code()
        if code in MSV_LINK_ERRS and link["last_err"] != code:
            _state(c, link, code)
        raise
    if link["last_err"] or not link["last_ok"]:
        _state(c, link, "")
    return j


def _state(c, link, code):
    if code:
        c.execute("UPDATE msv_links SET last_err=? WHERE id=?", (code, link["id"]))
    else:
        c.execute("UPDATE msv_links SET last_err='', last_ok=? WHERE id=?", (iso(now_utc()), link["id"]))
    c.commit()


# ---- values of the other server: type-checked and cut down to the fields of the interface (never passed through)
def _txt(v, n=500):
    return _CTRL.sub("", v)[:n] if isinstance(v, str) else ""


def _id(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 < v < 2 ** 62 else None


def msv_t(base, d):
    if not isinstance(d, dict) or _id(d.get("id")) is None:
        return None
    tags = d.get("tags") if isinstance(d.get("tags"), list) else []
    due, dt = d.get("due"), d.get("due_time")
    return {"id": d["id"], "list_id": _id(d.get("list_id")), "parent_id": _id(d.get("parent_id")), "title": _txt(d.get("title")),
            "due": due if isinstance(due, str) and _DATE.fullmatch(due) else None,
            "due_time": dt if isinstance(dt, str) and _TIME.fullmatch(dt) else None,
            "priority": d.get("priority") if d.get("priority") in MSV_PRIOS else "none",
            "status": d.get("status") if d.get("status") in MSV_STATUS else "open",
            "tags": [_txt(x, 100) for x in tags if isinstance(x, str)][:50],
            "updated_at": _txt(d.get("updated_at"), 40) or None, "url": f"{base}/#t/{d['id']}"}


def msv_l(d):
    if not isinstance(d, dict) or _id(d.get("id")) is None or d.get("archived") is True:
        return None
    col = d.get("color")
    return {"id": d["id"], "name": _txt(d.get("name"), 200), "color": col if isinstance(col, str) and _COLOR.fullmatch(col) else "",
            "folder": _txt(d.get("folder"), 200), "inbox": d.get("is_inbox") is True, "can_write": d.get("role") in WRITE_ROLES}


def _rows(j):
    return j.get("data") if isinstance(j.get("data"), list) else []


def msv_me(j):
    """The account over there from GET /api/v1/me: {id, name, email, username} (email: /api/v1/me has none -> null)."""
    if _id(j.get("id")) is None:
        raise MsvError("version")
    if j.get("kind") == "agent":
        raise MsvError("invalid", tr("This is the token of an agent; use a token of your own account"))
    t = j.get("token") if isinstance(j.get("token"), dict) else {}
    eff = [x for x in (t.get("effective_scopes") or []) if isinstance(x, str)] if isinstance(t.get("effective_scopes"), list) else None
    return {"id": j["id"], "name": _txt(j.get("display_name"), 100) or _txt(j.get("username"), 100), "email": None,
            "username": _txt(j.get("username"), 100)}, eff


# ---- the accounts
def msv_row(c, sid, uid=None):
    r = c.execute("SELECT * FROM msv_links WHERE id=? AND user_id=? AND deleted_at IS NULL", (sid, uid or me())).fetchone()
    if not r:
        raise Denied(404)
    return r


def msv_public(r):
    try:
        rm = json.loads(r["remote_me"] or "{}")
    except ValueError:
        rm = {}
    e = r["last_err"] or ""
    return {"id": r["id"], "name": r["name"], "short": r["short"], "color": r["color"], "base_url": r["base_url"],
            "default_inbox": bool(r["default_inbox"]), "position": r["position"],
            "remote_me": {"id": rm.get("id"), "name": rm.get("name") or "", "email": rm.get("email")},
            "ok": not e, "err": e or None, "err_text": tr(MSV_TEXT[e]) if e in MSV_TEXT else None, "at": r["last_ok"]}


def _short_of(name):
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name or "") if w]
    s = "".join(w[0] for w in words[:2]) if len(words) > 1 else (words[0][:2] if words else "")
    return s.upper() or "K"


def msv_self(c, uid):
    try:
        v = json.loads(usettings(c, uid).get("msv_self") or "{}")
    except ValueError:
        v = {}
    v = v if isinstance(v, dict) else {}
    org = c.execute("SELECT o.name FROM orgs o JOIN org_members m ON m.org_id=o.id WHERE m.user_id=? ORDER BY o.id LIMIT 1", (uid,)).fetchone()
    return {"name": v.get("name") or tr("This server"), "short": v.get("short") or _short_of(org[0] if org else ""),
            "color": v.get("color") or MSV_DEFAULT_COLOR}


def _clean_meta(b):
    """name / short / color of an account or this server (400 on a bad value)."""
    out = {}
    if "name" in b:
        n = _txt(b["name"], 60).strip() if isinstance(b["name"], str) else ""
        if not n:
            raise MsvBad(tr("Name missing"))
        out["name"] = n
    if "short" in b:
        s = b["short"].strip().upper() if isinstance(b["short"], str) else ""
        if not _SHORT.fullmatch(s):
            raise MsvBad(tr("The short name has 1 to 3 letters or digits"))
        out["short"] = s
    if "color" in b:
        if not isinstance(b["color"], str) or b["color"].lower() not in ACCOUNT_COLORS:
            raise MsvBad(tr("Invalid value: {0}", "color"))
        out["color"] = b["color"].lower()
    return out


class MsvBad(Exception):
    pass


@app.errorhandler(MsvBad)
def msv_bad(e):
    return err(str(e), 400)


class MsvBusy(Exception):
    pass


@app.errorhandler(MsvBusy)
def msv_busy(e):
    return err(str(e), 429)


def _unknown(b, allowed):
    if not isinstance(b, dict):
        raise MsvBad(tr("Invalid data"))
    extra = sorted(k for k in b if k not in allowed)
    if extra:
        raise MsvBad(tr("Unknown field: {0}", ", ".join(extra)[:200]))


def msv_parse_code(code):
    """'kalmido-link:' + base64url(JSON {u, t}) -> (base_url, token); MsvBad otherwise."""
    bad = MsvBad(tr("This connection code is not valid"))
    s = str(code or "").strip()
    if not s.startswith(MSV_CODE) or len(s) > 4000:
        raise bad
    raw = s[len(MSV_CODE):]
    try:
        j = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError, RecursionError):
        raise bad from None
    if not isinstance(j, dict) or not isinstance(j.get("u"), str) or not isinstance(j.get("t"), str):
        raise bad
    return j["u"], j["t"]


def _free_color(c, uid):
    used = {r[0] for r in c.execute("SELECT color FROM msv_links WHERE user_id=? AND deleted_at IS NULL", (uid,))}
    used.add(msv_self(c, uid)["color"])
    return next((x for x in ACCOUNT_COLORS if x not in used), ACCOUNT_COLORS[0])


def _check_account(c, uid, base, tok, skip=None):
    """GET /api/v1/me over there -> (remote_me, effective scopes); refuses this server and a second link to the same account."""
    if msv_is_self(base):
        raise MsvBad(tr("That is this server. Connect another Kalmido server."))
    if hit_limit(f"msv-try:{uid}", MSV_TRIES, 3600):  # each try is a request to an address the person chose
        raise MsvBusy(tr("Too many requests, please slow down"))
    try:
        j = msv_call(c, None, "/me", base=base, tok=tok)
    except MsvError as e:
        if e.code in ("blocked", "https"):
            raise MsvBad(e.text()) from None
        if e.code == "notfound":  # no /api/v1/me at that address
            raise MsvError("version") from None
        raise
    rm, eff = msv_me(j)
    for r in c.execute("SELECT id, remote_me FROM msv_links WHERE user_id=? AND base_url=? AND deleted_at IS NULL", (uid, base)):
        try:
            same = json.loads(r["remote_me"] or "{}").get("id") == rm["id"]
        except ValueError:
            same = False
        if same and r["id"] != skip:
            raise MsvBad(tr("This account is connected already"))
    return rm, eff


@app.get("/api/servers")
def msv_list():
    uid = msv_gate()
    c = db()
    rows = c.execute("SELECT * FROM msv_links WHERE user_id=? AND deleted_at IS NULL ORDER BY position, id", (uid,)).fetchall()
    return jsonify({"links": [msv_public(r) for r in rows], "self": msv_self(c, uid)})  # "self" cannot be a keyword


@app.post("/api/servers")
def msv_add():
    """{code} or {base_url, token, name?, short?, color?} -> the account (201). Tried with GET /api/v1/me over there first."""
    uid = msv_gate()
    b, c = body(), db()
    _unknown(b, ("code", "base_url", "token", "name", "short", "color"))
    if b.get("code"):
        url, tok = msv_parse_code(b["code"])
    else:
        url, tok = b.get("base_url"), b.get("token")
    base = msv_norm_url(url)
    if not base:
        return err(tr("Invalid address"))
    tok = tok.strip() if isinstance(tok, str) else ""
    if not _TOKEN.fullmatch(tok):
        return err(tr("Token missing or invalid"))
    if c.execute("SELECT COUNT(*) FROM msv_links WHERE user_id=? AND deleted_at IS NULL", (uid,)).fetchone()[0] >= MSV_MAX:
        return err(tr("At most {0} servers", MSV_MAX), 409)
    meta = _clean_meta({k: b[k] for k in ("name", "short", "color") if b.get(k) not in (None, "")})
    sealed = msv_seal(uid, tok)
    if not sealed:
        return err(tr("This server has no server key (KALMIDO_SECRET_KEY), so it cannot keep tokens safe"), 409)
    rm, eff = _check_account(c, uid, base, tok)
    name = meta.get("name") or urllib.parse.urlsplit(base).hostname or base
    now = iso(now_utc())
    pos = c.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM msv_links WHERE user_id=?", (uid,)).fetchone()[0]
    sid = insert_id(c, "INSERT INTO msv_links(user_id,name,short,color,base_url,token_enc,remote_me,position,last_ok,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (uid, name, meta.get("short") or _short_of(name), meta.get("color") or _free_color(c, uid), base, sealed,
                     json.dumps(rm), pos, now, now, now))
    c.commit()
    print("server link", sid, "added for user", uid, flush=True)  # never the token
    out = msv_public(msv_row(c, sid, uid))
    if eff is not None:
        out["missing_scopes"] = [x for x in MSV_SCOPES if x not in eff]
    return jsonify(out), 201


@app.patch("/api/servers/<int:sid>")
def msv_patch(sid):
    """{name?, short?, color?, default_inbox?: bool, position?, token?} (a new token: of the same account over there)."""
    uid = msv_gate()
    b, c = body(), db()
    _unknown(b, ("name", "short", "color", "default_inbox", "position", "token"))
    r = msv_row(c, sid, uid)
    sets = _clean_meta(b)
    if "default_inbox" in b:
        if not isinstance(b["default_inbox"], bool):
            return err(tr("Invalid value: {0}", "default_inbox"))
        sets["default_inbox"] = 1 if b["default_inbox"] else 0
    if "position" in b:
        if not isinstance(b["position"], int) or isinstance(b["position"], bool) or not 0 <= b["position"] <= 10000:
            return err(tr("Invalid value: {0}", "position"))
        sets["position"] = b["position"]
    if b.get("token") not in (None, ""):
        tok = b["token"].strip() if isinstance(b["token"], str) else ""
        if not _TOKEN.fullmatch(tok):
            return err(tr("Token missing or invalid"))
        rm, _eff = _check_account(c, uid, r["base_url"], tok, skip=sid)
        try:
            old = json.loads(r["remote_me"] or "{}").get("id")
        except ValueError:
            old = None
        if old is not None and rm["id"] != old:
            return err(tr("This token belongs to another account over there"), 409)
        sets.update(token_enc=msv_seal(uid, tok), remote_me=json.dumps(rm), last_err="", last_ok=iso(now_utc()))
    if sets.get("default_inbox"):
        c.execute("UPDATE msv_links SET default_inbox=0 WHERE user_id=? AND id!=?", (uid, sid))
    if sets:
        sets["updated_at"] = iso(now_utc())
        c.execute(f"UPDATE msv_links SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), sid))
        c.commit()
    _CACHE.pop(sid, None)
    return jsonify(msv_public(msv_row(c, sid, uid)))


@app.delete("/api/servers/<int:sid>")
def msv_delete(sid):
    uid = msv_gate()
    c = db()
    msv_row(c, sid, uid)
    c.execute("UPDATE msv_links SET deleted_at=?, default_inbox=0 WHERE id=?", (iso(now_utc()), sid))
    c.commit()
    _CACHE.pop(sid, None)
    return jsonify(ok=True, hint=tr("The token stays valid on the other server: revoke it there under Settings > Account > API tokens."))


@app.post("/api/servers/<int:sid>/restore")
def msv_restore(sid):
    uid = msv_gate()
    c = db()
    r = c.execute("SELECT * FROM msv_links WHERE id=? AND user_id=? AND deleted_at IS NOT NULL", (sid, uid)).fetchone()
    if not r:
        raise Denied(404)
    if not r["token_enc"]:  # review N1: wiped MSV_TOKEN_KEEP_D days after removing
        return err(tr("The token of this server was deleted 30 days after removing it. Enter the token again: connect the server anew."), 409)
    if c.execute("SELECT COUNT(*) FROM msv_links WHERE user_id=? AND deleted_at IS NULL", (uid,)).fetchone()[0] >= MSV_MAX:
        return err(tr("At most {0} servers", MSV_MAX), 409)
    try:
        rid = json.loads(r["remote_me"] or "{}").get("id")
    except ValueError:
        rid = None
    for o in c.execute("SELECT remote_me FROM msv_links WHERE user_id=? AND base_url=? AND deleted_at IS NULL", (uid, r["base_url"])):
        try:
            if json.loads(o["remote_me"] or "{}").get("id") == rid:
                return err(tr("This account is connected already"), 409)
        except ValueError:
            pass
    c.execute("UPDATE msv_links SET deleted_at=NULL, updated_at=? WHERE id=?", (iso(now_utc()), sid))
    c.commit()
    return jsonify(msv_public(msv_row(c, sid, uid)))


def msv_cleanup(c):
    """Watchdog (review N1): a removed account keeps its sealed token MSV_TOKEN_KEEP_D days for undo, then it is wiped
    (new backups no longer carry it). msv_links has no org_id: no row-level security to pass."""
    old = iso(now_utc() - timedelta(days=MSV_TOKEN_KEEP_D))
    n = c.execute("UPDATE msv_links SET token_enc='' WHERE deleted_at IS NOT NULL AND deleted_at<? AND token_enc!=''", (old,)).rowcount
    if n:
        c.commit()
    return n


@app.patch("/api/servers/self")
def msv_self_patch():
    """{name?, short?, color?}: how this server is labelled in the combined views (a personal setting)."""
    uid = msv_gate()
    b, c = body(), db()
    _unknown(b, ("name", "short", "color"))
    cur = msv_self(c, uid)
    cur.update(_clean_meta(b))
    uset(c, uid, "msv_self", json.dumps(cur))
    c.commit()
    return jsonify(msv_self(c, uid))


@app.post("/api/servers/code")
def msv_code():
    """{name?} -> {code, token_id}: a personal API token ON THIS server with just the scopes the other app needs (the
    usual limits of Settings > Account > API tokens; visible and revocable there), packed with this server's address."""
    from ..api.v1 import token_create
    msv_gate()
    b = body()
    _unknown(b, ("name",))
    nm = _txt(b.get("name"), 40).strip() if isinstance(b.get("name"), str) else ""
    try:
        j = v1_call(token_create, body={"name": f"Kalmido-App: {nm or tr('other server')}"[:60], "scopes": list(MSV_SCOPES)})
    except V1Error as e:
        if isinstance(e.resp, tuple) and e.resp[1] < 400:  # token_create answers (json, 201): v1_call takes every tuple for an error
            j = e.resp[0].get_json()
        else:
            return _local_err(e)
    except Denied as e:
        return err(e.text(), e.code)
    code = MSV_CODE + base64.urlsafe_b64encode(json.dumps({"u": PUBLIC_URL, "t": j["token"]}, separators=(",", ":")).encode()).decode().rstrip("=")
    return jsonify(code=code, token_id=j["id"], scopes=j.get("effective_scopes") or j.get("scopes") or []), 201


# ---- the data of an account (nothing stored: at most MSV_CACHE_S in memory)
_CACHE, _LOCKS, _LOCKS_LOCK, _FRESH = {}, {}, threading.Lock(), {}


def _link_lock(sid):
    with _LOCKS_LOCK:
        lk = _LOCKS.get(sid)
        if lk is None:
            lk = _LOCKS[sid] = threading.Lock()
        return lk


def msv_read_gate():
    """review H1: the reads of other servers per person and minute (a person, not an agent: msv_gate came first)."""
    if hit_limit(f"msv:{me()}", MSV_READS, 60):
        raise MsvError("busy", retry=10)


def msv_data(c, r):
    sid = r["id"]
    lk = _link_lock(sid)
    if not lk.acquire(blocking=False):  # review H1: a request for this account runs already -- no thread waits for it
        hit = _CACHE.get(sid)
        if hit and hit[1] == r["updated_at"]:
            return hit[2]
        raise MsvError("busy", retry=2)
    try:
        hit = _CACHE.get(sid)
        if hit and time.monotonic() - hit[0] < MSV_CACHE_S and hit[1] == r["updated_at"]:
            return hit[2]
        base = r["base_url"]
        lists = [x for x in (msv_l(d) for d in _rows(msv_req(c, r, "/lists"))) if x]
        tasks, cur = [], None
        while len(tasks) < MSV_TASKS_MAX:
            q = {"status": "open", "fields": "compact", "limit": 500, **({"cursor": cur} if cur else {})}
            j = msv_req(c, r, "/tasks", query=q)
            tasks += [x for x in (msv_t(base, d) for d in _rows(j)) if x]
            cur = j.get("next_cursor")
            if not isinstance(cur, str) or not cur or len(cur) > 200:
                cur = None
                break
        out = {"lists": lists, "tasks": tasks[:MSV_TASKS_MAX], "today": local_now().date().isoformat(), "at": iso(now_utc()),
               "more": bool(cur) or len(tasks) > MSV_TASKS_MAX}
        now = time.monotonic()
        for k in [k for k, v in _CACHE.items() if now - v[0] > MSV_CACHE_S * 4]:
            _CACHE.pop(k, None)
        _CACHE[sid] = (now, r["updated_at"], out)
        return out
    finally:
        lk.release()


@app.get("/api/servers/<int:sid>/data")
def msv_get_data(sid):
    """{lists, tasks (open, at most MSV_TASKS_MAX), today, at}; ?fresh=1 skips the short memory."""
    uid = msv_gate()
    c = db()
    msv_read_gate()
    r = msv_row(c, sid, uid)
    if request.args.get("fresh") == "1" and time.monotonic() - _FRESH.get(sid, -MSV_FRESH_S) >= MSV_FRESH_S:
        _FRESH[sid] = time.monotonic()  # review H1: else the memory answers
        _CACHE.pop(sid, None)
    return jsonify(msv_data(c, r))


@app.get("/api/servers/<int:sid>/tasks/<int:tid>")
def msv_task_get(sid, tid):
    uid = msv_gate()
    msv_read_gate()
    c = db()
    r = msv_row(c, sid, uid)
    j = msv_req(c, r, f"/tasks/{tid}")
    t = msv_t(r["base_url"], j)
    if not t:
        raise MsvError("version")
    subs = [x for x in (msv_t(r["base_url"], d) for d in _rows(msv_req(c, r, f"/tasks/{tid}/subtasks"))) if x]
    cc = j.get("comment_count")
    return jsonify({**t, "notes": _txt(j.get("notes"), 50000), "subtasks": [{"id": x["id"], "title": x["title"], "status": x["status"]} for x in subs],
                    "comments_count": cc if isinstance(cc, int) and not isinstance(cc, bool) else 0,
                    "attachments_count": len(j["attachments"]) if isinstance(j.get("attachments"), list) else 0})


def _task_body(b, create=False):
    """The fields this app writes over there, checked here (the other server checks again)."""
    _unknown(b, ("title", "due", "notes", "priority") + (("list_id",) if create else ()))
    out = {}
    if create or "title" in b:
        t = _txt(b.get("title"), 500).strip() if isinstance(b.get("title"), str) else ""
        if not t:
            raise MsvBad(tr("Title missing"))
        out["title"] = t
    if "due" in b:
        if b["due"] is not None and not (isinstance(b["due"], str) and _DATE.fullmatch(b["due"])):
            raise MsvBad(tr("Invalid value: {0}", "due"))
        out["due"] = b["due"] or None
    if "notes" in b:
        if not isinstance(b["notes"], str) or len(b["notes"]) > 50000:
            raise MsvBad(tr("Invalid value: {0}", "notes"))
        out["notes"] = b["notes"]
    if "priority" in b:
        if b["priority"] not in MSV_PRIOS:
            raise MsvBad(tr("Invalid value: {0}", "priority"))
        out["priority"] = b["priority"]
    if create and b.get("list_id") is not None:
        if _id(b["list_id"]) is None:
            raise MsvBad(tr("Invalid value: {0}", "list_id"))
        out["list_id"] = b["list_id"]
    return out


def _t_or_fail(r, j):
    t = msv_t(r["base_url"], j)
    if not t:
        raise MsvError("version")
    return t


@app.post("/api/servers/<int:sid>/tasks")
def msv_task_create(sid):
    """{list_id?, title, due?, notes?, priority?} -> T (201); without list_id: the inbox over there."""
    uid = msv_gate()
    c = db()
    r = msv_row(c, sid, uid)
    p = _task_body(body(), create=True)
    t = _t_or_fail(r, msv_req(c, r, "/tasks", "POST", payload=p))
    _CACHE.pop(sid, None)
    return jsonify(t), 201


@app.patch("/api/servers/<int:sid>/tasks/<int:tid>")
def msv_task_patch(sid, tid):
    uid = msv_gate()
    c = db()
    r = msv_row(c, sid, uid)
    p = _task_body(body())
    if not p:
        return err(tr("Nothing to change"))
    t = _t_or_fail(r, msv_req(c, r, f"/tasks/{tid}", "PATCH", payload=p))
    _CACHE.pop(sid, None)
    return jsonify(t)


@app.post("/api/servers/<int:sid>/tasks/<int:tid>/<any(complete, reopen):act>")
def msv_task_act(sid, tid, act):
    uid = msv_gate()
    c = db()
    r = msv_row(c, sid, uid)
    t = _t_or_fail(r, msv_req(c, r, f"/tasks/{tid}/{act}", "POST", payload={}))
    _CACHE.pop(sid, None)
    return jsonify(t)


@app.delete("/api/servers/<int:sid>/tasks/<int:tid>")
def msv_task_delete(sid, tid):
    """To the trash over there (restorable there)."""
    uid = msv_gate()
    c = db()
    r = msv_row(c, sid, uid)
    msv_req(c, r, f"/tasks/{tid}", "DELETE")
    _CACHE.pop(sid, None)
    return jsonify(ok=True)


@app.get("/api/servers/<int:sid>/search")
def msv_search(sid):
    uid = msv_gate()
    msv_read_gate()
    c = db()
    r = msv_row(c, sid, uid)
    q = (request.args.get("q") or "").strip()
    if not q or len(q) > 200:
        return err(tr("Invalid value: {0}", "q"))
    j = msv_req(c, r, "/search", query={"q": q, "limit": 100})
    return jsonify(tasks=[x for x in (msv_t(r["base_url"], d) for d in _rows(j)) if x])


@app.get("/api/servers/<int:sid>/events")
def msv_events(sid):
    """?from=&to= (dates) -> {events: [{id, occ, title, start, end, all_day, cal_name, color, url}]}; id + occ = one
    occurrence (a series has one id)."""
    uid = msv_gate()
    msv_read_gate()
    c = db()
    r = msv_row(c, sid, uid)
    lo, hi = request.args.get("from") or "", request.args.get("to") or ""
    if not _DATE.fullmatch(lo) or not _DATE.fullmatch(hi) or hi < lo:
        return err(tr("from/to missing"))
    cals = {}
    for d in _rows(msv_req(c, r, "/event-calendars")):
        if isinstance(d, dict) and _id(d.get("id")) is not None:
            col = d.get("color")
            cals[d["id"]] = (_txt(d.get("name"), 200), col if isinstance(col, str) and _COLOR.fullmatch(col) else "")
    out = []
    for d in _rows(msv_req(c, r, "/events", query={"from": lo, "to": hi}))[:5000]:
        if not isinstance(d, dict) or _id(d.get("eid")) is None:
            continue
        st, en = d.get("start"), d.get("end")
        cal = cals.get(_id(d.get("cal"))) or ("", "")
        out.append({"id": d["eid"], "occ": _txt(str(d.get("occ") or ""), 60), "title": _txt(d.get("title")),
                    "start": _txt(st, 40) if isinstance(st, str) else None, "end": _txt(en, 40) if isinstance(en, str) else None,
                    "all_day": d.get("all_day") is True, "cal_name": cal[0], "color": cal[1], "url": f"{r['base_url']}/#cal"})
    return jsonify(events=out)


@app.get("/api/servers/<int:sid>/news")
def msv_news(sid):
    """?limit= (1..200, default 50) -> {items: [{id, kind, text, task_id, at, read}], unread}."""
    uid = msv_gate()
    msv_read_gate()
    c = db()
    r = msv_row(c, sid, uid)
    lim = request.args.get("limit") or "50"
    if not lim.isdigit() or not 1 <= int(lim) <= 200:
        return err(tr("Invalid value: {0}", "limit"))
    j = msv_req(c, r, "/news")
    items = []
    for d in _rows(j)[:int(lim)]:
        if not isinstance(d, dict) or _id(d.get("id")) is None:
            continue
        data = d.get("data") if isinstance(d.get("data"), dict) else {}
        items.append({"id": d["id"], "kind": _txt(d.get("kind"), 40), "task_id": _id(d.get("task_id")),
                      "text": _txt(d.get("task_title"), 200) or _txt(d.get("excerpt"), 200) or _txt(data.get("title"), 200),
                      "at": _txt(d.get("created_at"), 40) or None, "read": d.get("read") is True})
    un = j.get("unread")
    return jsonify(items=items, unread=un if isinstance(un, int) and not isinstance(un, bool) and un >= 0 else 0)


@app.post("/api/servers/<int:sid>/news/read")
def msv_news_read(sid):
    uid = msv_gate()
    b, c = body(), db()
    _unknown(b, ("ids",))
    r = msv_row(c, sid, uid)
    ids = b.get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > 500 or any(_id(x) is None for x in ids):
        return err(tr("Invalid value: {0}", "ids"))
    j = msv_req(c, r, "/news/read", "POST", payload={"ids": ids})
    un = j.get("unread")
    return jsonify(ok=True, unread=un if isinstance(un, int) and not isinstance(un, bool) else 0)


# ---- moving a task between servers = copy, then the source into the trash (restorable there)
def _local_err(e):
    if isinstance(e, V1Error):
        resp, code = e.resp if isinstance(e.resp, tuple) else (e.resp, e.resp.status_code)
        x = (resp.get_json(silent=True) or {}).get("error")
        return err(x.get("message") if isinstance(x, dict) else str(x or tr("Error")), code)
    return err(e.text(), e.code)


def _src_read(c, uid, srv, tid):
    """The source task: {title, notes, due, due_time, priority, subs, comments, attachments, note_lost}. Needs the right to
    delete it (participants cannot delete tasks), checked before anything is copied."""
    if srv is None:
        from ..api.v1 import v1_one
        need_task(c, tid, write=True)
        lid = c.execute("SELECT list_id, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
        if lid["deleted_at"]:
            raise Denied(404)
        if list_role(c, lid["list_id"]) == "participant":
            raise Denied(403, tr("Participants cannot delete tasks"))
        t = v1_one(c, tid)
        subs = [d["title"] for d in load_tasks(c, "parent_id=? AND deleted_at IS NULL AND status=0 ORDER BY sort, id", (tid,))]
        return {"title": t["title"], "notes": t.get("notes") or "", "due": t.get("due"), "due_time": t.get("due_time"),
                "priority": t.get("priority") or "none", "subs": subs, "comments": t.get("comment_count") or 0,
                "attachments": len(t.get("attachments") or []), "note_lost": bool(t.get("encrypted_note") or t.get("note_locked"))}
    j = msv_req(c, srv, f"/tasks/{tid}")
    t = _t_or_fail(srv, j)
    subs = [x["title"] for x in (msv_t(srv["base_url"], d) for d in _rows(msv_req(c, srv, f"/tasks/{tid}/subtasks"))) if x and x["status"] == "open"]
    cc = j.get("comment_count")
    return {"title": t["title"], "notes": _txt(j.get("notes"), 50000), "due": t["due"], "due_time": t["due_time"], "priority": t["priority"],
            "subs": subs, "comments": cc if isinstance(cc, int) and not isinstance(cc, bool) else 0,
            "attachments": len(j["attachments"]) if isinstance(j.get("attachments"), list) else 0,
            "note_lost": j.get("encrypted_note") is True or j.get("note_locked") is True}


def _dst_create(c, srv, lid, s):
    """The copy -> (its id, how many subtasks could not be created there)."""
    p = {"title": s["title"] or tr("(untitled)"), "priority": s["priority"]}
    if s["notes"]:
        p["notes"] = s["notes"]
    if s["due"]:
        p["due"] = s["due"]
        if s["due_time"]:
            p["due_time"] = s["due_time"]
    if lid is not None:
        p["list_id"] = lid
    if srv is None:
        from ..api.v1 import v1_task_in
        from ..api.common import v1_call
        from ..tasks.tasks import task_create
        if lid is not None and list_role(c, lid) not in WRITE_ROLES:
            raise Denied(403 if list_role(c, lid) else 404)
        nid = v1_call(task_create, body=v1_task_in(p))["id"]
        for st in s["subs"]:
            v1_call(task_create, body={"title": st, "parent_id": nid})
        return nid, 0
    nid = _t_or_fail(srv, msv_req(c, srv, "/tasks", "POST", payload=p))["id"]
    lost = 0
    for st in s["subs"]:
        # review N3: the copy exists over there now -- a failed subtask is counted, never answered as a failed move
        # (the source would stay and a second try make a second copy)
        try:
            msv_req(c, srv, f"/tasks/{nid}/subtasks", "POST", payload={"title": st})
        except MsvError:
            lost += 1
    _CACHE.pop(srv["id"], None)
    return nid, lost


def _src_delete(c, srv, tid):
    try:
        if srv is None:
            from ..tasks.lifecycle import trash_task
            trash_task(c, tid)
            bump(c)
            c.commit()
        else:
            msv_req(c, srv, f"/tasks/{tid}", "DELETE")
            _CACHE.pop(srv["id"], None)
        return True
    except Exception as e:  # noqa: BLE001 -- the copy exists; the answer says the source stayed
        c.rollback()
        print("server move: the source", tid, "stayed:", type(e).__name__, flush=True)
        return False


@app.post("/api/servers/move")
def msv_move():
    """{from: {server: 0 | sid, task}, to: {server: 0 | sid, list_id | null}} -> {ok, task: {server, id}, lost: {comments,
    attachments, note, subtasks (not created over there)}, source_kept?}. Copies title, note, due date, priority and the titles of open subtasks, then moves the source
    into the trash. server 0 = this server; list_id null = the inbox there. Nothing is deleted when the copy fails."""
    uid = msv_gate()
    b, c = body(), db()
    _unknown(b, ("from", "to"))
    f, t = b.get("from"), b.get("to")
    if not isinstance(f, dict) or not isinstance(t, dict):
        return err(tr("Invalid data"))
    _unknown(f, ("server", "task"))
    _unknown(t, ("server", "list_id"))
    fs, ts, tid, lid = f.get("server"), t.get("server"), f.get("task"), t.get("list_id")
    for v in (fs, ts):
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            return err(tr("Invalid value: {0}", "server"))
    if _id(tid) is None or (lid is not None and _id(lid) is None):
        return err(tr("Invalid data"))
    if fs == ts:
        return err(tr("Source and target are on the same server"))
    src = msv_row(c, fs, uid) if fs else None
    dst = msv_row(c, ts, uid) if ts else None
    try:
        s = _src_read(c, uid, src, tid)
        nid, lost_subs = _dst_create(c, dst, lid, s)
    except (V1Error, Denied) as e:
        c.rollback()
        return _local_err(e)
    out = {"ok": True, "task": {"server": ts, "id": nid}, "source": {"server": fs, "id": tid},
           "lost": {"comments": s["comments"], "attachments": s["attachments"], "note": s["note_lost"], "subtasks": lost_subs}}
    if not _src_delete(c, src, tid):
        out["source_kept"] = True
    return jsonify(out)
