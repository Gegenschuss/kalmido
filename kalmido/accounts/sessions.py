"""2.115.0 B (#2062): active sessions -- Settings > Account > Active sessions.

A person sees their own browser sessions (device and browser read from the User-Agent, how they signed in, since when,
last activity, until when) and ends one of them or all others. Nothing new about the client is stored beyond a shortened
User-Agent: no address, no location. Outwards a session is named by a short public id (sid, derived from the token hash
with another hash), never by the token hash itself. last_seen_at is written at most every SES_TOUCH seconds per session
(an in-process throttle plus a condition in the UPDATE), not on every request. Ending a session also removes the push
subscriptions made in it (push_subs.session_hash); older subscriptions ('' = unknown session) stay. Agent tokens are no
sessions (agents never get a cookie session, see authenticate) and are not touched here.
A child account reads the list like its other account settings and ends sessions only after the parents' PIN
(family/pin.py PIN_GUARD)."""
import hashlib
import re
import threading
import time
from datetime import timedelta

from flask import g, jsonify, request

from ..core.config import app, COOKIE
from ..core.i18n import tr
from ..core.db import db, err, iso, now_utc
from ..accounts.session import _token_hash, me

SES_TOUCH = 300  # s: last activity is written at most this often per session
SES_UA_MAX = 200
_seen, _seen_lock = {}, threading.Lock()


def ses_sid(token_hash):
    """The public id of a session (16 hex characters; the token hash never leaves the server)."""
    return hashlib.sha256(("sid:" + token_hash).encode()).hexdigest()[:16]


def ses_ua():
    """The request's User-Agent, control characters removed, shortened."""
    return re.sub(r"[\x00-\x1f<>]", "", request.headers.get("User-Agent") or "")[:SES_UA_MAX]


def ses_current_hash():
    """The token hash of this request's cookie session, or None (proxy login, no cookie)."""
    tok = request.cookies.get(COOKIE) if g.get("auth_via") == "session" else None
    return _token_hash(tok) if tok else None


def ses_touch(c, token_hash):
    """Records the activity of a session: at most every SES_TOUCH seconds (no UPDATE per request)."""
    now = time.monotonic()
    with _seen_lock:
        if now - _seen.get(token_hash, -SES_TOUCH) < SES_TOUCH:
            return
        _seen[token_hash] = now
        if len(_seen) > 5000:  # forget idle sessions
            for k in [k for k, v in _seen.items() if now - v >= SES_TOUCH]:
                _seen.pop(k, None)
    t = now_utc()
    n = c.execute("UPDATE sessions SET last_seen_at=? WHERE token_hash=? AND last_seen_at<?",
                  (iso(t), token_hash, iso(t - timedelta(seconds=SES_TOUCH)))).rowcount
    if n:
        c.commit()  # only the session row is written so far in this request


def ses_end(c, uid, hashes=None, keep=None):
    """Ends sessions and the push subscriptions made in them. uid: the account (None = by the hashes alone, the logout);
    hashes: the token hashes to end (None = every session of uid); keep: a token hash that stays. The caller commits.
    Returns the number of sessions ended."""
    q, a = "SELECT token_hash, user_id FROM sessions WHERE 1=1", []
    if uid is not None:
        q, a = q + " AND user_id=?", a + [uid]
    if hashes is not None:
        hashes = [h for h in hashes if h]
        if not hashes:
            return 0
        q, a = q + " AND token_hash IN (" + ",".join("?" * len(hashes)) + ")", a + hashes
    rows = [r for r in c.execute(q, a).fetchall() if r["token_hash"] != keep]
    for r in rows:
        c.execute("DELETE FROM sessions WHERE token_hash=?", (r["token_hash"],))
        c.execute("DELETE FROM push_subs WHERE user_id=? AND session_hash=? AND session_hash!=''", (r["user_id"], r["token_hash"]))
    return len(rows)


def ses_device(ua):
    """(device, browser, system) read from a User-Agent, '' when unknown (a small table, no library)."""
    ua = ua or ""
    browser = next((n for p, n in (("Edg/", "Edge"), ("EdgA/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser/", "Samsung Internet"),
                                   ("Firefox/", "Firefox"), ("FxiOS/", "Firefox"), ("CriOS/", "Chrome"), ("Chrome/", "Chrome"),
                                   ("Safari/", "Safari")) if p in ua), "")
    system = next((n for p, n in (("iPhone", "iOS"), ("iPad", "iPadOS"), ("Android", "Android"), ("CrOS", "ChromeOS"),
                                  ("Windows", "Windows"), ("Mac OS X", "macOS"), ("Macintosh", "macOS"), ("Linux", "Linux")) if p in ua), "")
    device = "phone" if ("Mobile" in ua or "iPhone" in ua) and "iPad" not in ua else "tablet" if ("iPad" in ua or system == "Android") else \
        "computer" if system else ""
    if not browser and ua and not system:
        browser = re.split(r"[/ ]", ua, 1)[0][:40]  # an app or tool (curl, a native client)
    return device, browser, system


def ses_public(r, cur):
    device, browser, system = ses_device(r["user_agent"])
    return {"sid": ses_sid(r["token_hash"]), "device": device, "browser": browser, "system": system, "via": r["via"] or "password",
            "created_at": r["created_at"], "last_seen_at": r["last_seen_at"] or r["created_at"], "expires_at": r["expires_at"],
            "current": r["token_hash"] == cur}


def _mine(c):
    return c.execute("SELECT * FROM sessions WHERE user_id=? AND expires_at>? ORDER BY created_at DESC", (me(), iso(now_utc()))).fetchall()


@app.get("/api/me/sessions")
def me_sessions():
    """The own sessions: [{sid, device, browser, system, via, created_at, last_seen_at, expires_at, current}], newest first,
    the current one first."""
    c, cur = db(), ses_current_hash()
    out = [ses_public(r, cur) for r in _mine(c)]
    out.sort(key=lambda s: not s["current"])
    return jsonify(sessions=out, current=bool(cur))


@app.delete("/api/me/sessions/<sid>")
def me_session_end(sid):
    """Ends one own session; the current one is the ordinary logout (the cookie goes too)."""
    c, cur = db(), ses_current_hash()
    hit = next((r["token_hash"] for r in _mine(c) if ses_sid(r["token_hash"]) == sid), None)
    if not hit:
        return err(tr("Not found"), 404)
    ses_end(c, me(), [hit])
    c.commit()
    resp = jsonify(ok=True, current=hit == cur)
    if hit == cur:
        resp.delete_cookie(COOKIE, path="/")
    return resp


@app.post("/api/me/sessions/others")
def me_sessions_others():
    """Ends every own session except this one -> {ended: n}."""
    c = db()
    n = ses_end(c, me(), None, keep=ses_current_hash())
    c.commit()
    return jsonify(ok=True, ended=n)
