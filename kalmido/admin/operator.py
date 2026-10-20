"""2.144.0 D (#797): the hosting operator's interface. A hoster runs Kalmido instances for customers with a console of its
own (a separate program, no code shared in either direction); the console talks to an instance only through these few
routes. The operator is NOT an account of the instance: it never sees content -- no titles, names, e-mail addresses,
texts or files, only numbers about the running server and two operating actions.

Off by default. KALMIDO_OPERATOR_TOKEN_FILE=<path> names a file holding the operator token (at least 32 characters, one
line); the server reads it at start and keeps only its SHA-256 hash in memory. Without it (or with an unreadable / too
short file) every /api/operator/... route answers 404. With it the console sends "Authorization: Bearer <token>"; a
missing or wrong token answers 401 (compared in constant time, failures count against a limit per address). A session
cookie, the proxy login and personal access tokens never reach these routes (accounts/session.py lets the path through
without a person), so an instance admin cannot use them either.

  GET  /api/operator/status      version, health, numbers of people / organisations / active people, storage, backups,
                                 registration mode, the current notice's level and times (never its text)
  POST /api/operator/setup-code  a fresh one-time setup code for the first admin -- only while no account exists
  PUT  /api/operator/notice      sets / clears the maintenance or info notice every client shows (no push)

Every call is logged with its action and the caller's address (never the token)."""
import hashlib
import hmac
import os
import shutil
from datetime import timedelta

from flask import abort, jsonify, request

from ..core.config import app, APP_VERSION, ATT_DIR, PUBLIC_URL
from ..core.db import body, bump, db, gsetting, iso, now_utc
from ..core.i18n import tr
from ..accounts.session import _rate_blocked, _rate_fail, client_ip, rate_ip

OP_TOKEN_MIN = 32
OP_TOKEN_MAX = 512
OP_RATE = 20  # wrong tokens per address within the login window


def _op_load():
    """The hash of the configured token, or '' (interface off). The token itself is not kept."""
    path = os.environ.get("KALMIDO_OPERATOR_TOKEN_FILE", "").strip()
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            tok = f.read(OP_TOKEN_MAX + 2).strip()
    except OSError as e:
        print("operator interface off: the token file cannot be read (", type(e).__name__, ")", flush=True)
        return ""
    if not OP_TOKEN_MIN <= len(tok) <= OP_TOKEN_MAX or any(ch.isspace() for ch in tok):
        print(f"operator interface off: the token must be {OP_TOKEN_MIN}-{OP_TOKEN_MAX} characters without blanks", flush=True)
        return ""
    print("operator interface on (/api/operator/...)", flush=True)
    return hashlib.sha256(tok.encode()).hexdigest()


OP_HASH = _op_load()


class OpDenied(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@app.errorhandler(OpDenied)
def op_denied(e):
    if e.code == 429:
        return jsonify(error=tr("Too many failed attempts, please wait a few minutes")), 429
    return jsonify(error=tr("Please log in")), 401


def op_gate(action):
    """404 when the interface is off, 401 without the right token; logs the call."""
    if not OP_HASH:
        abort(404)  # exactly like a route that does not exist
    keys = [("operator:ip:" + rate_ip(), OP_RATE)]
    if _rate_blocked(keys):
        raise OpDenied(429)
    auth = request.headers.get("Authorization") or ""
    tok = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    got = hashlib.sha256(tok.encode()).hexdigest() if tok and len(tok) <= OP_TOKEN_MAX else ""
    if not got or not hmac.compare_digest(got, OP_HASH):
        _rate_fail(keys)
        print("operator: refused", action, "from", client_ip(), flush=True)
        raise OpDenied(401)
    print("operator:", action, "from", client_ip(), flush=True)


def _count(c, sql, args=()):
    r = c.execute(sql, args).fetchone()
    return int(r[0] or 0) if r else 0


def _notice(c):
    """Level and times of the current notice -- never its text (an instance admin may have written it)."""
    from .hosting import announce_get
    a = announce_get(c, True)
    if not a:
        return None
    return {"level": a.get("level") or "info", "active": bool(a.get("active")),
            "starts_at": a.get("starts_at") or "", "ends_at": a.get("ends_at") or ""}


def op_status(c):
    """Numbers only. Counting runs as "system" (across organisations): it is what the hoster needs to run the server and
    never leaves the counts."""
    from ..core.pg import system_ctx
    from ..accounts.orgs import instance_mode
    from ..accounts.signup import signup_mode
    from .backup import BK_ON_ENV, bk_db_bytes
    from .hosting import hosted, _user_bytes
    from .worker import wrk_health
    now = now_utc()
    d7, d30 = iso(now - timedelta(days=7)), iso(now - timedelta(days=30))
    with system_ctx(c):
        people = _count(c, "SELECT COUNT(*) FROM users WHERE kind!='agent'")
        disabled = _count(c, "SELECT COUNT(*) FROM users WHERE kind!='agent' AND disabled!=0")
        agents = _count(c, "SELECT COUNT(*) FROM users WHERE kind='agent'")
        orgs = _count(c, "SELECT COUNT(*) FROM orgs WHERE personal_of IS NULL")
        act = "SELECT COUNT(DISTINCT s.user_id) FROM sessions s JOIN users u ON u.id=s.user_id WHERE u.kind!='agent' AND s.last_seen_at>=?"
        active7, active30 = _count(c, act, (d7,)), _count(c, act, (d30,))
        uids = [r[0] for r in c.execute("SELECT id FROM users").fetchall()]
        files = _user_bytes(c, uids)
        mode = signup_mode(c)
    disk = {}
    try:
        du = shutil.disk_usage(ATT_DIR if os.path.isdir(ATT_DIR) else os.path.dirname(ATT_DIR) or "/")
        disk = {"total_bytes": du.total, "free_bytes": du.free}
    except OSError:
        pass
    h = wrk_health(c)
    return {
        "version": APP_VERSION, "ok": True, "url": PUBLIC_URL, "hosted": hosted(), "instance_mode": instance_mode(c),
        "signup_mode": mode, "setup_done": people > 0,
        "people": {"total": people, "disabled": disabled, "agents": agents, "active_7d": active7, "active_30d": active30},
        "organisations": orgs,
        "storage": {"files_bytes": files, "db_bytes": bk_db_bytes(c), "disk": disk},
        "backup": {"available": BK_ON_ENV, "on": gsetting(c, "bk_on") == "1", "last_ok": gsetting(c, "bk_last_ok") or "",
                   "failing": bool(gsetting(c, "bk_last_error"))},
        "health": {"role": h.get("role"), "threads": h.get("threads"), "pool": h.get("pool"),
                   "worker_age_s": (h.get("worker") or {}).get("age_s")},
        "notice": _notice(c),
    }


@app.get("/api/operator/status")
def operator_status():
    op_gate("status")
    return jsonify(op_status(db()))


@app.post("/api/operator/setup-code")
def operator_setup_code():
    """A fresh one-time code for the first setup page (the customer creates the first admin with it). Only while the
    instance has no account at all; afterwards 409. Not possible with a fixed code or the check turned off (409)."""
    op_gate("setup-code")
    from ..accounts.setupcode import SH_CODE_ENV, SH_CODE_OFF, sh_code_new
    from ..core.pg import system_ctx
    c = db()
    with system_ctx(c):
        exists = c.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    if exists:
        return jsonify(error=tr("Setup is already done"), code="setup_done"), 409
    if SH_CODE_OFF or SH_CODE_ENV:
        return jsonify(error=tr("The setup code is fixed on this server"), code="setup_code_fixed"), 409
    code = sh_code_new()  # replaces the code printed at start; valid once
    return jsonify(setup_code=code, url=PUBLIC_URL + "/")


@app.put("/api/operator/notice")
def operator_notice():
    """{level: maintenance | info, text, minutes? | starts_at? / ends_at?}; an empty text clears the notice. No push."""
    op_gate("notice")
    from .hosting import announce_set
    b = body()
    if not isinstance(b, dict):
        b = {}
    b = {k: b[k] for k in ("text", "level", "starts_at", "ends_at", "minutes") if k in b}
    from ..core.pg import system_ctx
    c = db()
    with system_ctx(c):  # an instance-wide setting, written without a person
        e = announce_set(c, b, "operator")
        if not e:
            bump(c)
    if e:
        c.rollback()
        return jsonify(error=e), 400
    c.commit()
    return jsonify(notice=_notice(c))
