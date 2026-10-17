"""Family: the parents' PIN of a kid account (2.49.0, #1551).

A parent (kid_parents, or an admin, like every other kid setting) sets a 4 to 6 digit PIN for a kid. With a PIN the kid
cannot change its account (name, picture, password, sign-in, two-factor, passkeys), its settings or log out without it;
ticking tasks off and asking for rewards stay free, and so do the automatic writes of the app (PIN_FREE_SETTINGS, push
subscriptions, the onboarding). A correct PIN opens these for PIN_OPEN seconds in THIS session only (kid_pin_open, keyed
by the session's token hash, gone with the session). The brake counts per kid (kid_pins.fails, not per session or
address): PIN_TRIES wrong PINs lock the PIN for PIN_LOCK seconds and the parents get a family push.
The PIN is stored only as a password hash (werkzeug, like users.password_hash) and never sent back; checks run through
check_password_hash also when there is no PIN / a malformed one (the dummy hash), so the answer time says nothing."""
import re
from datetime import datetime, timedelta
from flask import g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from ..core.config import app, COOKIE
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc, write_lock
from ..accounts.session import _DUMMY_HASH, _token_hash, me
from ..collab.comments import send_pushes, user_names
from ..family.family import h6a_admin_kid_ok, is_kid, kid_dict, kid_parents, kid_push, need_kid

PIN_RE = re.compile(r"^[0-9]{4,6}$")  # 2.49.0 review L6: ASCII digits only (\d takes other scripts too)
PIN_TRIES = 5      # wrong PINs in a row, then the lock
PIN_LOCK = 900     # s: the lock after PIN_TRIES wrong PINs
PIN_OPEN = 300     # s: how long a correct PIN opens account / settings / log out in this session
# what a kid's app writes by itself (#1537): never asks for the PIN
PIN_FREE_SETTINGS = {"tour", "folders_closed", "detail_split", "detail_cm_fold", "fav_suggest"}
# the routes the PIN guards (a kid's other writes are limited by family.KID_WRITE already)
PIN_GUARD = re.compile(r"^/api/(auth/.+|me|me/(avatar|2fa/.+|passkeys(/.*)?))$")


def pin_row(c, kid):
    return c.execute("SELECT * FROM kid_pins WHERE kid_id=?", (kid,)).fetchone()


def pin_has(c, kid):
    return bool(c.execute("SELECT 1 FROM kid_pins WHERE kid_id=?", (kid,)).fetchone())


def _session_hash():
    tok = request.cookies.get(COOKIE) if g.get("auth_via") == "session" else None
    return _token_hash(tok) if tok else None


def pin_open_until(c, kid):
    """The end of this session's PIN opening (ISO) or None."""
    sh = _session_hash()
    if not sh:
        return None
    r = c.execute("SELECT until FROM kid_pin_open WHERE token_hash=? AND kid_id=? AND until>?", (sh, kid, iso(now_utc()))).fetchone()
    return r[0] if r else None


def pin_state(c, kid):
    """kid_dict fields: pin = a PIN is set; for the kid itself also pin_open (until when this session is open) and
    pin_wait (seconds the PIN is still locked)."""
    r = pin_row(c, kid)
    d = {"pin": bool(r)}
    if r and kid == me():
        d["pin_open"] = pin_open_until(c, kid)
        left = _lock_left(r)
        if left:
            d["pin_wait"] = left
    return d


def _lock_left(r):
    if not r or not r["lock_until"]:
        return 0
    try:
        return max(0, int((datetime.fromisoformat(r["lock_until"]) - now_utc()).total_seconds()))
    except ValueError:
        return 0


def _settings_free(b):
    return isinstance(b, dict) and bool(b) and all(k in PIN_FREE_SETTINGS for k in b)


@app.before_request
def pin_guard():
    """A kid with a PIN: account, settings and log out only while this session is open (after the PIN)."""
    u = g.get("user")
    if not u or not u["kid"] or request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    path = request.path
    if path == "/api/settings":
        if _settings_free(request.get_json(silent=True)):
            return None
    elif not PIN_GUARD.match(path):
        return None
    c = db()
    if not pin_has(c, u["id"]) or pin_open_until(c, u["id"]):
        return None
    return jsonify(error=tr("Ask your parents for the PIN"), pin=True), 403


# ---- the kid: open with the PIN, close again
@app.post("/api/me/pin/unlock")
def pin_unlock():
    c, uid = db(), me()
    if not is_kid(c, uid):
        return err(tr("Not found"), 404)
    pin = str(body().get("pin") or "")
    sh = _session_hash()
    if not sh:
        return err(tr("Only with a Kalmido sign-in"), 400)  # proxy sign-in: there is no session to open
    write_lock(c, f"kidpin:{uid}")  # one guess at a time per kid
    r = pin_row(c, uid)
    if not r:
        check_password_hash(_DUMMY_HASH, pin)
        c.rollback()
        return jsonify(ok=True, pin=False, until=None)
    wait = _lock_left(r)
    if wait:
        c.rollback()
        return jsonify(error=tr("Too many wrong PINs. Try again in {0} minutes.", (wait + 59) // 60), wait=wait), 429
    good = check_password_hash(r["pin_hash"] if PIN_RE.match(pin) else _DUMMY_HASH, pin) and bool(PIN_RE.match(pin))
    now = now_utc()
    if good:
        until = iso(now + timedelta(seconds=PIN_OPEN))
        c.execute("UPDATE kid_pins SET fails=0, lock_until='' WHERE kid_id=?", (uid,))
        c.execute("DELETE FROM kid_pin_open WHERE token_hash=?", (sh,))
        c.execute("INSERT INTO kid_pin_open(token_hash,kid_id,until) VALUES(?,?,?)", (sh, uid, until))
        c.commit()
        return jsonify(ok=True, pin=True, until=until)
    fails = (r["fails"] or 0) + 1
    if fails < PIN_TRIES:
        c.execute("UPDATE kid_pins SET fails=? WHERE kid_id=?", (fails, uid))
        c.commit()
        return jsonify(error=tr("Wrong PIN"), left=PIN_TRIES - fails), 403
    c.execute("UPDATE kid_pins SET fails=0, lock_until=? WHERE kid_id=?", (iso(now + timedelta(seconds=PIN_LOCK)), uid))
    who = user_names(c, [uid]).get(uid, "?")
    adm = [x[0] for x in c.execute("SELECT id FROM users WHERE is_admin=1 AND disabled=0")]
    adm = [x for x in adm if h6a_admin_kid_ok(c, x, uid)]  # 2.86.0 (N8): only admins of the kid's own organisation
    g.pushes = []
    for p in dict.fromkeys(kid_parents(c, uid) or adm):
        kid_push(c, p, lambda lg: tr("{0} entered a wrong PIN {1} times", who, PIN_TRIES, lg=lg),
                 lambda lg: tr("Settings stay locked for {0} minutes.", PIN_LOCK // 60, lg=lg))
    c.commit()
    send_pushes(g.pop("pushes", None))  # the answer is a 429: send_queued_pushes would drop them
    g.pushes = []
    return jsonify(error=tr("Too many wrong PINs. Try again in {0} minutes.", PIN_LOCK // 60), wait=PIN_LOCK), 429


@app.post("/api/me/pin/lock")
def pin_lock():
    """The kid (or a parent handing the phone back) closes this session again before the time is up."""
    c = db()
    sh = _session_hash()
    if sh:
        c.execute("DELETE FROM kid_pin_open WHERE token_hash=?", (sh,))
        c.commit()
    return jsonify(ok=True)


# ---- the parents: set, change, remove
@app.put("/api/family/kids/<int:kid>/pin")
def pin_set(kid):
    c = db()
    need_kid(c, kid)  # a parent of this kid (or an admin); the kid itself gets 404
    pin = str(body().get("pin") or "")
    if not PIN_RE.match(pin):
        return err(tr("The PIN has 4 to 6 digits"))
    ts = iso(now_utc())
    c.execute("DELETE FROM kid_pins WHERE kid_id=?", (kid,))
    c.execute("INSERT INTO kid_pins(kid_id,pin_hash,fails,lock_until,set_by,set_at) VALUES(?,?,0,'',?,?)",
              (kid, generate_password_hash(pin), me(), ts))
    c.execute("DELETE FROM kid_pin_open WHERE kid_id=?", (kid,))  # a new PIN closes every open session of the kid
    bump(c)
    c.commit()
    return jsonify(kid_dict(c, kid))


@app.delete("/api/family/kids/<int:kid>/pin")
def pin_remove(kid):
    c = db()
    need_kid(c, kid)
    c.execute("DELETE FROM kid_pins WHERE kid_id=?", (kid,))
    c.execute("DELETE FROM kid_pin_open WHERE kid_id=?", (kid,))
    bump(c)
    c.commit()
    return jsonify(kid_dict(c, kid))
