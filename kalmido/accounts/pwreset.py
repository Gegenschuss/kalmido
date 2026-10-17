"""2.49.0 (#1531): "Forgot your password?" on the login page. The person enters their e-mail address (or user name) and
gets the same one-time link an admin sends (#697, kind "reset": 256-bit token, only its hash stored, valid INVITE_DAYS
days, used once, redeemed on the page /#invite/<token>). The answer never tells whether an account exists: always the
same status and text, padded to a fixed minimum time, the mail goes out in a background thread. Nothing is sent to
unknown addresses, disabled / unconfirmed accounts, agents, kid accounts (their parents reset them), accounts without a
password (single sign-on only), when the rate limit trips or a link went out in the last PW_GAP seconds. Without outgoing
e-mail the login page hides the link (GET /api/auth/info: forgot) and the route answers the same, sending nothing."""
import os
import random
import threading
import time
from datetime import timedelta

from flask import jsonify

from ..core.config import app, APP_DIR, APP_NAME
from ..core.i18n import tr
from ..core.db import body, connect, db, err, iso, now_utc, parse_iso, write_lock
from ..accounts.session import _accept_lang, _rate_blocked, _rate_fail, _rate_keys, client_ip
from ..integrations.mail import MAIL_OUT_ON, mail_send

PW_LIMITS = (3, 10, 20)  # requests per 15 min: address + sender IP, sender IP, address (any IP)
PW_GAP = 300             # s: at most one self-service link per account in this time
PW_PAD = 0.9             # s: every answer ends at this total time (the found and the unknown path look alike)
# 2.58.0 (#1792): 0.45 -> 0.9 s, so the database part under load stays well inside the padding (L1)


def pw_forgot_on():
    """For GET /api/auth/info: the login page shows the link only when Kalmido can send mail."""
    return bool(MAIL_OUT_ON)


def _pw_eligible(u):
    return bool(u["password_hash"] and u["email"] and not u["disabled"] and not u["kid"] and (u["kind"] or "user") != "agent")


def _pw_mail(uid, to, subject, text, html_body):
    """The background part: talks to the mail server after the answer has gone out."""
    try:
        try:
            logo = {"logo": (open(os.path.join(APP_DIR, "static", "icon-192.png"), "rb").read(), "png")}
        except OSError:
            logo = {}
        mail_send(to, subject, text, html_body, images=logo, from_name=APP_NAME)
        c = connect()
        try:
            c.execute("UPDATE user_invites SET sent_at=? WHERE user_id=?", (iso(now_utc()), uid))
            c.commit()
        finally:
            c.close()
    except Exception as e:  # noqa: BLE001  (nobody waits for this; the person can ask again)
        print("password reset mail failed:", type(e).__name__, flush=True)


def _pw_send(who):
    """Creates the link(s) for the account(s) matching who and returns the mails to send [(uid, to, subject, text, html)]."""
    from ..admin.hosting import mail_budget
    from ..accounts.invite import invite_mail, invite_new
    c = db()
    write_lock(c, "accounts")
    rows = c.execute("SELECT * FROM users WHERE lower(email)=? OR lower(username)=? ORDER BY id LIMIT 3", (who, who)).fetchall()
    out = []
    for u in rows:
        if not _pw_eligible(u):
            continue
        r = c.execute("SELECT kind, created_at, used_at FROM user_invites WHERE user_id=?", (u["id"],)).fetchone()
        if r and r["kind"] == "reset" and not r["used_at"] and parse_iso(r["created_at"]) > now_utc() - timedelta(seconds=PW_GAP):
            continue  # a fresh link is on its way already: no flood of mails, the earlier link stays valid
        if not mail_budget(c, None, u["email"]):  # 2.24.0 (#899): mails per address and day
            continue
        link = invite_new(c, u["id"], None, send=False, kind="reset")["link"]
        out.append((u["id"], u["email"], *invite_mail(c, u, link, "reset", "")))
    c.commit()
    return out


@app.post("/api/auth/forgot")
def pw_forgot():
    """{login: e-mail address or user name}: open. Always {ok: true} for a non-empty request (see the module doc)."""
    t0 = time.monotonic()
    who = str(body().get("login") or "").strip().lower()[:200]
    if not who:
        return err(tr("Please enter your e-mail address or user name", lg=_accept_lang("en")))
    keys = _rate_keys(who, pre="pw:", lim=PW_LIMITS)
    # 2.86.0 (N1): the per-address ceiling ("pw:uall:", any sender) only raises an alarm: requests from many other addresses
    # could otherwise block the owner's own request. Mails stay bounded by PW_GAP (one link per 5 min) and mail_budget.
    blocked = _rate_blocked([k for k in keys if ":uall:" not in k[0]])
    for k in _rate_fail(keys):  # every request counts, found or not
        if ":uall:" in k:
            from ..core.i18n import N_
            from ..notify.alerts import aa_now
            aa_now("security", "ratelimit:pw:uall",
                   N_("Many password reset requests for one address from several senders (at most one link per {0} min goes out)."),
                   [PW_GAP // 60])
    mails = []
    if not blocked and MAIL_OUT_ON:
        try:
            mails = _pw_send(who)
        except Exception as e:  # noqa: BLE001  (the answer must not differ)
            db().heal()
            print("password reset failed:", type(e).__name__, flush=True)
    for m in mails:
        threading.Thread(target=_pw_mail, args=m, daemon=True).start()
    print("password reset asked from", client_ip(), "(blocked)" if blocked else "", flush=True)
    time.sleep(max(0.0, PW_PAD + random.uniform(0, 0.05) - (time.monotonic() - t0)))
    return jsonify(ok=True)
