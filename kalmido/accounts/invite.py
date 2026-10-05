"""Invitations and reset links (#697): a one-time link by e-mail with which a person sets their own password."""
import hashlib
import hmac
import html
import os
import secrets
from datetime import timedelta

from flask import g, jsonify
from werkzeug.security import generate_password_hash

from ..core.config import app, APP_DIR, APP_NAME, MIN_PASSWORD, PUBLIC_URL
from ..core.i18n import lang, N_, tr
from ..core.db import body, bump, db, err, gsetting, iso, now_utc, parse_iso, usettings
from ..accounts.session import _rate_blocked, _rate_fail, _rate_keys, client_ip
from ..accounts.login import finish_login, pend_cookie, pend_new
from ..core.access import Denied
from ..integrations.mail import MAIL_OUT_ON, mail_send


# ---------------------------------------------------------------- 2.22.0 (#697): invitations
# An admin creates a person without a password and Kalmido sends an invitation: a one-time link (a random token of 256
# bits, only its SHA-256 is stored, valid INVITE_DAYS days, used once) to the page "Set up your account" (the app at
# /#invite/<token>: the fragment never reaches a server log), where the person sets their own password (and, if they
# like, two-factor sign-in) and is signed in. The same link is how an admin resets a forgotten password ("Send a reset
# link" instead of thinking up a password). Without SMTP the admin copies the link. The page is rate limited per address
# like the login; a wrong or used token says only "invalid or expired".
INVITE_DAYS = 7


def _hash(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


def invite_state(c, uid):
    """'invited' (a link that is still valid), 'expired' (one that ran out) or None."""
    r = c.execute("SELECT * FROM user_invites WHERE user_id=? AND used_at IS NULL", (uid,)).fetchone()
    if not r:
        return None
    return "invited" if parse_iso(r["expires_at"]) > now_utc() else "expired"


def invite_new(c, uid, by, send=True):
    """A new link for uid (replaces an older one) -> {link, expires_at, sent, kind, error?}. send: by e-mail when SMTP is
    set up and the person has an address."""
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or (u["kind"] or "user") == "agent":
        raise Denied(404)
    if u["disabled"]:
        raise Denied(409, tr("The account is disabled"))
    tok = secrets.token_urlsafe(32)
    kind = "reset" if u["password_hash"] else "invite"
    now = now_utc()
    exp = iso(now + timedelta(days=INVITE_DAYS))
    c.execute("""INSERT INTO user_invites(user_id,token_hash,kind,created_by,created_at,expires_at) VALUES(?,?,?,?,?,?)
                 ON CONFLICT(user_id) DO UPDATE SET token_hash=excluded.token_hash, kind=excluded.kind, created_by=excluded.created_by,
                 created_at=excluded.created_at, expires_at=excluded.expires_at, sent_at=NULL, used_at=NULL""",
              (uid, _hash(tok), kind, by, iso(now), exp))
    link = f"{PUBLIC_URL}/#invite/{tok}"
    out = {"link": link, "expires_at": exp, "sent": False, "kind": kind, "email": u["email"] or ""}
    if send and MAIL_OUT_ON and u["email"]:
        try:
            inviter = c.execute("SELECT display_name, username FROM users WHERE id=?", (by,)).fetchone()
            subject, text, body_html = invite_mail(c, u, link, kind, (inviter["display_name"] or inviter["username"]) if inviter else "")
            try:
                logo = {"logo": (open(os.path.join(APP_DIR, "static", "icon-192.png"), "rb").read(), "png")}
            except OSError:
                logo = {}
            mail_send(u["email"], subject, text, body_html, images=logo, from_name=APP_NAME)
            c.execute("UPDATE user_invites SET sent_at=? WHERE user_id=?", (iso(now_utc()), uid))
            out["sent"] = True
        except Exception as e:  # noqa: BLE001  (the link still works: the admin can copy it)
            print("invitation mail failed:", type(e).__name__, flush=True)
            out["error"] = tr("The e-mail could not be sent: copy the link instead")
    return out


def invite_mail(c, u, link, kind, inviter):
    """(subject, text, html) of the invitation / reset mail in the person's language (the design of the welcome mail)."""
    lg = lang(c, u["id"])
    t = lambda s, *a: tr(s, *a, lg=lg)  # noqa: E731
    e = html.escape
    name = u["display_name"] or u["username"]
    host = PUBLIC_URL.split("://", 1)[-1].rstrip("/")
    acc, ink, bg, card, muted = "#6d4bd8", "#1b1730", "#f4f2fb", "#ffffff", "#6b6680"
    from ..accounts.orgs import org_names  # 2.22.0 (#752): "Example · Kalmido"
    org = (org_names(c, u["id"]) or [""])[0]
    brand = f"{org} · {APP_NAME}" if org else APP_NAME
    if kind == "reset":
        subject = t(N_("Set a new password for {0}"), APP_NAME)
        head, intro, button = t(N_("Hello {0},"), name), t(N_("{0} sent you a link to set a new password for {1}."), inviter or t(N_("An admin")), APP_NAME), t(N_("Set a new password"))
    else:
        subject = t(N_("Welcome to {0}, {1}"), APP_NAME, name)
        head = t(N_("Hello {0}, welcome to {1}!"), name, APP_NAME)
        intro = t(N_("{0} created an account for you. In {1} we plan tasks, projects and appointments together – in the browser and as an app on the phone."), inviter or t(N_("An admin")), APP_NAME)
        button = t(N_("Set up your account"))
    valid = t(N_("The link works once and for {0} days."), INVITE_DAYS)
    steps = [t(N_("Choose your own password on the page the button opens.")), t(N_("Best right away: turn on two-factor sign-in (an app code or a passkey).")),
             t(N_("On the phone: in the browser “Add to home screen” – then {0} runs like an app, with notifications."), APP_NAME)]
    body_html = f"""<!doctype html><html lang="{lg}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="color-scheme" content="light"><title>{e(subject)}</title></head>
<body style="margin:0;padding:0;background:{bg};font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:{ink}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{bg};padding:32px 12px"><tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background:{card};border-radius:18px;overflow:hidden;box-shadow:0 2px 12px rgba(40,20,90,.08)">
<tr><td style="background:#16141f;padding:28px 32px" align="left">
 <table role="presentation" cellpadding="0" cellspacing="0"><tr>
  <td><img src="cid:logo" width="48" height="48" alt="" style="display:block;border-radius:12px"></td>
  <td style="padding-left:14px;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:.2px">{e(brand)}</td></tr></table>
</td></tr>
<tr><td style="padding:32px 32px 8px">
 <h1 style="margin:0 0 12px;font-size:22px;line-height:1.3">{e(head)}</h1>
 <p style="margin:0 0 16px;font-size:16px;line-height:1.55">{e(intro)}</p>
</td></tr>
<tr><td style="padding:0 32px">
 <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{bg};border-radius:12px">
  <tr><td style="padding:18px 20px;font-size:15px;line-height:1.7">
   <div style="color:{muted};font-size:13px">{e(t(N_("Address")))}</div><div style="font-weight:600"><a href="{e(PUBLIC_URL)}" style="color:{acc};text-decoration:none">{e(host)}</a></div>
   <div style="color:{muted};font-size:13px;margin-top:10px">{e(t(N_("Username")))}</div><div style="font-weight:600;font-family:ui-monospace,Menlo,Consolas,monospace">{e(u["username"])}</div>
  </td></tr></table>
</td></tr>
<tr><td style="padding:24px 32px 8px" align="left">
 <a href="{e(link)}" style="display:inline-block;background:{acc};color:#ffffff;text-decoration:none;font-weight:600;font-size:16px;padding:13px 26px;border-radius:12px">{e(button)}</a>
 <p style="margin:12px 0 0;font-size:13px;line-height:1.5;color:{muted}">{e(valid)}</p>
</td></tr>
{"" if kind == "reset" else f'''<tr><td style="padding:16px 32px 8px">
 <h2 style="margin:0 0 8px;font-size:16px">{e(t(N_("Getting started")))}</h2>
 <ol style="margin:0;padding-left:20px;font-size:15px;line-height:1.6">{"".join(f"<li>{e(x)}</li>" for x in steps)}</ol>
</td></tr>'''}
<tr><td style="border-top:1px solid #ece9f5;padding:18px 32px;font-size:12px;color:{muted}">{e(t(N_("This e-mail was sent by {0}. If you did not expect it, you can ignore it."), APP_NAME))}</td></tr>
</table></td></tr></table></body></html>"""
    text = "\n".join([head, "", intro, "", f"{t('Address')}: {PUBLIC_URL}", f"{t('Username')}: {u['username']}", "", f"{button}: {link}", valid, ""]
                     + ([] if kind == "reset" else [t(N_("Getting started")) + ":"] + [f"{i + 1}. {x}" for i, x in enumerate(steps)]))
    return subject, text, body_html


def _lookup(c, tok):
    """The invitation row of a token (valid, unused) or None; the comparison is on the hash, again in constant time."""
    if not isinstance(tok, str) or not 20 <= len(tok) <= 100:
        return None
    h = _hash(tok)
    r = c.execute("SELECT * FROM user_invites WHERE token_hash=?", (h,)).fetchone()
    if not r or not hmac.compare_digest(r["token_hash"], h) or r["used_at"] or parse_iso(r["expires_at"]) <= now_utc():
        return None
    u = c.execute("SELECT * FROM users WHERE id=?", (r["user_id"],)).fetchone()
    return (r, u) if u and not u["disabled"] else None


def _limited():
    keys = _rate_keys("invite", pre="inv:")
    if _rate_blocked(keys):
        return keys, err(tr("Too many attempts, please wait a few minutes"), 429)
    return keys, None


@app.post("/api/auth/invite/check")
def invite_check():
    """{token} -> who the link is for (the page "Set up your account"); open, rate limited."""
    keys, e = _limited()
    if e:
        return e
    c = db()
    hit = _lookup(c, body().get("token"))
    if not hit:
        _rate_fail(keys)
        return err(tr("This link is invalid or has expired. Ask for a new one."), 404)
    r, u = hit
    return jsonify(username=u["username"], display_name=u["display_name"] or u["username"], kind=r["kind"],
                   lang=usettings(c, u["id"]).get("lang") or "en", min_password=MIN_PASSWORD)


@app.post("/api/auth/invite/accept")
def invite_accept():
    """{token, password}: sets the password, uses the link up, ends other sessions (a reset) and signs in (two-factor
    first when the admins require it)."""
    keys, e = _limited()
    if e:
        return e
    b = body()
    c = db()
    c.execute("BEGIN IMMEDIATE")
    hit = _lookup(c, b.get("token"))
    if not hit:
        c.rollback()
        _rate_fail(keys)
        return err(tr("This link is invalid or has expired. Ask for a new one."), 404)
    r, u = hit
    pw = b.get("password") if isinstance(b.get("password"), str) else ""
    if len(pw) < MIN_PASSWORD:
        c.rollback()
        return err(tr("Password: at least {0} characters", MIN_PASSWORD))
    c.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw), u["id"]))
    c.execute("UPDATE user_invites SET used_at=? WHERE user_id=?", (iso(now_utc()), u["id"]))
    c.execute("DELETE FROM sessions WHERE user_id=?", (u["id"],))
    bump(c)
    c.commit()
    u = c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
    print("account set up with an invitation link:", u["username"], "from", client_ip(), flush=True)
    if gsetting(c, "twofa_required") == "1":
        from ..accounts.login import twofa_methods
        if not twofa_methods(c, u):
            tok = pend_new("enrol", u["id"], remember=True)
            return pend_cookie(jsonify(ok=False, enrol=True, methods=["totp", "passkey"]), tok)
    return finish_login(c, u, True, "invite")


@app.post("/api/users/<int:uid>/invite")
def user_invite(uid):
    """Admins: {send?: true} -> a new invitation (no password yet) or reset link (has one): by e-mail when possible, the
    link always in the answer (to copy without SMTP)."""
    from ..accounts.users import need_admin
    need_admin()
    c = db()
    b = body()
    out = invite_new(c, uid, g.user["id"], send=b.get("send", True) is not False)
    bump(c)
    c.commit()
    return jsonify(out)


