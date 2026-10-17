"""2.45.0 (#1515): one-time code for the first setup. As long as no user exists, POST /api/auth/setup needs a code that
only the server's log shows (whoever reaches a fresh server first no longer becomes its admin). The code is made by the
serving process at start (app.py) or on the first request that needs it, kept only as a SHA-256 hash in memory, compared
in constant time and dropped once the first account exists. Wrong codes count against a rate limit per address like
logins. A restart prints a new code. KALMIDO_SETUP_CODE=<code> sets a fixed code, KALMIDO_SETUP_CODE=off turns the check
off (only for tests and automation that create the first account themselves)."""
import hmac
import os
import secrets
import threading

from ..accounts.session import _rate_blocked, _rate_fail, _token_hash, client_ip

SH_CODE_ENV = os.environ.get("KALMIDO_SETUP_CODE", "").strip()
SH_CODE_OFF = SH_CODE_ENV.lower() in ("off", "0", "false", "no")
SH_CODE_RATE = 10  # wrong codes per address within the login window (FAIL_WINDOW)
SH_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: read off a log, typed by hand
_SH = {"hash": ""}
_SH_LOCK = threading.RLock()  # 2.81.0 (#1627): re-entrant, sh_code_ensure holds it while it makes the code


def sh_code_required():
    return not SH_CODE_OFF


def sh_code_new():
    """A fresh code (3 x 4 characters, ~59 bits); printed to the log, only its hash is kept."""
    code = "-".join("".join(secrets.choice(SH_CODE_ALPHABET) for _ in range(4)) for _ in range(3))
    with _SH_LOCK:
        _SH["hash"] = _token_hash(code.replace("-", ""))
    bar = "=" * 64
    print(f"\n{bar}\n  Kalmido first setup: no account exists yet.\n  Setup code: {code}\n"
          "  Enter it on the setup page to create the first (admin) account.\n"
          "  It is valid once; a restart prints a new one.\n" + bar + "\n", flush=True)
    return code


def sh_code_ensure(c):
    """Start and first request: a code exists while the server has no user (nothing with a fixed or no code)."""
    if SH_CODE_OFF or SH_CODE_ENV or c.execute("SELECT 1 FROM users").fetchone():
        return
    with _SH_LOCK:  # 2.81.0 (#1627): check and make in one go, two first requests print one code
        if _SH["hash"]:
            return
        sh_code_new()


def sh_code_startup():
    from ..core.db import connect
    if SH_CODE_OFF:
        print("KALMIDO_SETUP_CODE=off: the first setup needs no code (only for tests and automation).", flush=True)
        return
    c = connect()
    try:
        sh_code_ensure(c)
    finally:
        c.close()


def sh_norm(code):
    """Copied from a log or typed: blanks, dashes and capitals do not matter."""
    return "".join(code.split()).replace("-", "").lower()


def sh_code_check(c, code):
    """None when the code is right (or not needed), else (message, status). Rate limited per client address."""
    from ..core.i18n import tr
    if SH_CODE_OFF:
        return None
    keys = [("setupcode:ip:" + client_ip(), SH_CODE_RATE)]
    if _rate_blocked(keys):
        return tr("Too many failed attempts, please wait a few minutes"), 429
    sh_code_ensure(c)
    want = _token_hash(sh_norm(SH_CODE_ENV)) if SH_CODE_ENV else _SH["hash"]
    code = sh_norm(code) if isinstance(code, str) else ""
    got = _token_hash(code) if code else ""
    if not got or not want or not hmac.compare_digest(got, want):
        _rate_fail(keys)
        print("first setup: wrong or missing setup code from", client_ip(), flush=True)
        return tr("Wrong setup code. It is in the server log (docker compose logs kalmido)."), 403
    return None


def sh_code_used():
    with _SH_LOCK:
        _SH["hash"] = ""
