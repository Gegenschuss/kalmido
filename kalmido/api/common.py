"""2.149.0 G (#2517): the helpers of the /api/v1 routes (error format, view wrapper, body and argument checks, cursors, rate
counter). They lived in api/v1.py, which re-exports them; the domain modules' v1 routes import them from here. Only core
imports: kalmido/__init__.py puts this module into the core layer (LAYER_OF)."""
import base64
import functools
import threading
import time
from flask import g, has_request_context, jsonify, request, Response

from ..core.config import app
from ..core.i18n import tr
from ..core.db import db, test_seconds, usettings
from ..core.ctx import me
from ..core.errors import BadInput, Denied, UnknownFields
from ..core.ratedb import RATE_SHARED_MIN_S, rate_hit


V1_CODES = {400: "invalid", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
            409: "conflict", 413: "too_large", 429: "rate_limited", 503: "unavailable"}


_HITS, _HITS_LOCK = {}, threading.Lock()


RATE_WINDOW_S = test_seconds("KALMIDO_TEST_RATE_WINDOW_S", 60)  # 2.149.0 E (#2513): the minute of hit_limit (tests only)


def hit_limit(key, limit, window=None):
    """Sliding-window counter: True (= refuse) once `limit` hits of `key` fell into the last `window` seconds (default: a
    minute, RATE_WINDOW_S). 2.306.0 D1 (#2875): a window of RATE_SHARED_MIN_S or more is also counted in the database
    (core/ratedb.py), over every process of the instance."""
    window = window or RATE_WINDOW_S
    now = time.time()
    with _HITS_LOCK:
        arr = [t for t in _HITS.get(key, ()) if now - t < window]
        if len(arr) >= limit:
            _HITS[key] = arr
            return True
        arr.append(now)
        _HITS[key] = arr
        if len(_HITS) > 20000:  # forget idle keys
            for k in [k for k, v in _HITS.items() if not v or now - v[-1] >= window]:
                _HITS.pop(k, None)
    if window >= RATE_SHARED_MIN_S:  # 2.306.0 D1 (#2875): the long limits count for every web process (failed count: this one's)
        return bool(rate_hit(key, limit, window))
    return False


def hit_budget(key, limit, ip, window=3600, share=3):
    """2.126.0 C (#1979 I1): a per-resource budget (a form, a link per hour) of which one address uses at most a share,
    so a single address cannot use it up for everyone else. Refused by the address part = the resource is not counted."""
    return hit_limit(f"{key}@{ip}", max(1, limit // share), window) or hit_limit(key, limit, window)


def act_via():
    """How the current request acts: 'api' (personal access token), 'public_link' or None (the app)."""
    if not has_request_context():
        return None
    v = g.get("auth_via")
    return "api" if v == "token" else "public_link" if v == "public" else "caldav" if v == "dav" else \
        "webhook" if v == "hook_in" else None  # 2.115.0 A (#2061): the inbound webhook of a list


def v1_err(code, msg, headers=None, name=None, **extra):
    """{"error": {"code", "message", **extra}}; name overrides the code's default name (2.2.1: unknown_field + fields)."""
    r = jsonify(error={"code": name or V1_CODES.get(code, "error"), "message": msg, **extra})
    r.status_code = code
    for k, v in (headers or {}).items():
        r.headers[k] = v
    return r


def v1_view(fn):
    """Route wrapper: Denied / BadInput / the internal views' error tuples -> the API's error format."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return v1_out(fn(*a, **k))
        except Denied as e:  # 2.125.0 B (#2119): v1_name = an own error code (month_closed)
            return v1_err(e.code, e.text() if e.code != 404 else tr("Not found"), name=getattr(e, "v1_name", None))
        except UnknownFields as e:  # 2.2.1 (#359): the client can see which of its fields the API does not know
            return v1_err(400, str(e), name="unknown_field", fields=e.fields)
        except BadInput as e:
            return v1_err(400, str(e))
    return wrapper


def v1_out(r):
    if isinstance(r, tuple) and len(r) == 2 and isinstance(r[1], int) and r[1] >= 400:
        resp, code = r
        msg = (resp.get_json(silent=True) or {}).get("error") if isinstance(resp, Response) else str(resp)
        return v1_err(code, str(msg or tr("Error")))
    return r


def v1_call(view, *a, body=None):
    """Runs an internal view with `body` as its JSON body: the web client's endpoint = the business rules.
    Returns the view's JSON; an error response is raised as V1Error (-> the route answers it)."""
    g.body = body if body is not None else {}
    try:
        r = view(*a)
    finally:
        g.body = None
    if isinstance(r, tuple):
        raise V1Error(v1_out(r))
    return r.get_json()


class V1Error(Exception):
    def __init__(self, resp):
        super().__init__("v1")
        self.resp = resp


@app.errorhandler(V1Error)
def v1_error(e):
    return e.resp


def v1_json():
    """The request body as a JSON object (400 otherwise)."""
    if not request.data:
        return {}
    b = request.get_json(silent=True)
    if not isinstance(b, dict):
        raise BadInput(tr("The body must be a JSON object"))
    return b


def v1_args(allowed):
    extra = sorted(k for k in request.args if k not in allowed)
    if extra:
        raise BadInput(tr("Unknown parameter: {0}", ", ".join(extra)[:200]))
    return request.args


def cursor_enc(kind, n):
    return base64.urlsafe_b64encode(f"{kind}:{n}".encode()).decode().rstrip("=")


def cursor_dec(kind, s):
    if not s:
        return 0
    try:
        k, _, n = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode().partition(":")
        if k == kind and n.isdigit():
            return int(n)
    except (ValueError, UnicodeDecodeError):
        pass
    raise BadInput(tr("Invalid value: {0}", "cursor"))


def v1_page(items, offset, limit):
    """Offset pages (search, time entries): {data, next_cursor}."""
    part = items[offset:offset + limit]
    return jsonify(data=part, next_cursor=cursor_enc("o", offset + limit) if len(items) > offset + limit else None)


def v1_feature(f):
    """The API also respects the user's own module switches (Settings > Layout / Collaboration)."""
    if f not in (usettings(db(), me()).get("features") or "").split(","):
        raise Denied(403, tr("Collaboration is turned off in your settings") if f == "collab"
                     else tr("Time tracking is turned off in your settings"))
