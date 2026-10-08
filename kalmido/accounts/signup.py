"""Self-registration on the login page (#711) and sign-in links / QR codes for family members without e-mail (#444)."""
import re

import segno
from flask import g, jsonify

from ..core.config import app, EMAIL_RE, MIN_PASSWORD, PUBLIC_URL, USERNAME_RE
from ..core.i18n import LANGS, tr
from ..core.db import body, bump, create_user, db, ensure_inbox, err, gset, gsetting, iso, now_utc, uset, usettings
from ..accounts.session import _accept_lang, _rate_fail, client_ip, me
from ..accounts.login import finish_login, pend_cookie, pend_new, twofa_methods
from ..core.access import Denied
from ..api.v1 import hit_limit


# ---------------------------------------------------------------- 2.23.0 (#711): self-registration
# Settings > Users > Sign-in: "Registration on the login page" (default off):
#   off       nobody registers (as before)
#   domain    only addresses of the listed e-mail domains (and of the organisations' domains); needs e-mail (SMTP)
#   approval  anyone, but an admin approves the account first (News + push to the admins); works without SMTP
#   open      anyone with a confirmed address (a hosted instance); needs e-mail (SMTP)
# Flow with e-mail: name + address -> a one-time link (#697, kind "signup") -> confirm + choose a password -> signed in
# (approval: waits for an admin). Without e-mail (only "approval"): name + address + password -> waits for an admin.
# Never says whether an address already has an account (the same answer, no mail); the user name is made from the
# address (a number added when taken), so the form tells nothing about user names either. Rate limited per address
# (5 per hour). New accounts get no list access (an admin / colleague shares), join the organisation whose e-mail domains
# match (else the instance's first one), never become admins or kid accounts. Unconfirmed registrations are removed
# after the link expired.
SIGNUP_MODES = ("off", "domain", "approval", "open")
SIGNUP_RATE = 5   # registrations per client address and hour


def _mail_on():
    from ..integrations.mail import MAIL_OUT_ON
    return MAIL_OUT_ON


def signup_mode(c):
    """The effective mode: domain / open need outgoing e-mail (else off)."""
    from ..accounts.orgs import instance_mode
    m = gsetting(c, "signup_mode")
    if m not in SIGNUP_MODES:
        return "off"
    if m in ("domain", "open") and not _mail_on():
        return "off"
    if m == "open" and instance_mode(c) == "organisation":  # 2.23.0 (#799): an organisation: only its domains or with approval
        return "off"
    return m


def _domains(v):
    return [d for d in (x.strip().lower().lstrip("@") for x in re.split(r"[,\s;]+", v or "")) if d and "." in d][:50]


def org_for_email(c, email):
    from ..accounts.orgs import instance_mode
    if instance_mode(c) not in ("multi", "workspaces"):  # 2.28.0 (#935): workspaces join by domain too
        return None  # organisation: the one organisation anyway (create_user); shared: none
    dom = email.rsplit("@", 1)[-1].lower()
    for r in c.execute("SELECT id, domains FROM orgs ORDER BY id"):
        if dom in _domains(r["domains"]):
            return r["id"]
    return None


def signup_info(c):
    """For GET /api/auth/info: None (off) or {mode, password: the form asks for a password (no e-mail)}."""
    m = signup_mode(c)
    if m == "off":
        return None
    return {"mode": m, "password": not _mail_on(), "min_password": MIN_PASSWORD}


def _username(c, email):
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@", 1)[0].lower()).strip("._-")[:26] or "user"
    if not USERNAME_RE.fullmatch(base):
        base = "user"
    name, n = base, 1
    while c.execute("SELECT 1 FROM users WHERE username=?", (name,)).fetchone():
        n += 1
        name = f"{base}{n}"
    return name


def _cleanup(c):
    """Registrations whose confirmation link ran out (signup 'confirm', no valid link): removed."""
    from ..accounts.users import user_purge
    from ..core.serializers import unlink_files
    old = [r[0] for r in c.execute("""SELECT u.id FROM users u LEFT JOIN user_invites i ON i.user_id=u.id
                                      WHERE u.signup='confirm' AND (i.expires_at IS NULL OR i.expires_at<?)""", (iso(now_utc()),))]
    files = []
    for uid in old:
        files += user_purge(c, uid)
    unlink_files(files)


def _notify_admins(c, uid):
    """News + push to every admin: a registration waits for approval."""
    from ..collab.news import news_add
    from ..notify.push import push_prio, push_reachable
    from ..collab.comments import lang_of
    u = c.execute("SELECT username, display_name, email FROM users WHERE id=?", (uid,)).fetchone()
    for (aid,) in c.execute("SELECT id FROM users WHERE is_admin=1 AND disabled=0").fetchall():
        s = usettings(c, aid)
        news_add(c, aid, "signup", data={"user_id": uid, "name": u["display_name"], "username": u["username"], "email": u["email"] or ""},
                 actor=uid, s=s)
        if push_reachable(c, aid, s):
            lg = lang_of(s)
            g.pushes.append((aid, tr("Registration waits for approval: {0}", u["display_name"] or u["username"], lg=lg),
                             tr("Settings > Users", lg=lg), f"{PUBLIC_URL}/#settings/users", push_prio(s)))


def signup_confirmed(c, u):
    """The address of registration u is confirmed (password set). True = it now waits for an admin (mode approval)."""
    if gsetting(c, "signup_mode") == "approval":
        c.execute("UPDATE users SET signup='pending' WHERE id=?", (u["id"],))
        _notify_admins(c, u["id"])
        return True
    c.execute("UPDATE users SET signup='', disabled=0 WHERE id=?", (u["id"],))
    return False


@app.post("/api/auth/signup")
def auth_signup():
    """{name, email, password? (only without e-mail), lang?}: open, rate limited. Always the same answer for a valid
    request ({ok, mail: a link was (or would have been) sent, pending: waits for an admin})."""
    from ..accounts.invite import invite_new
    c = db()
    m = signup_mode(c)
    lg = _accept_lang("en")
    if m == "off":
        return err(tr("Registration is not open on this server", lg=lg), 404)
    b = body()
    email = str(b.get("email") or "").strip()[:200]
    name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip()[:60]
    if not EMAIL_RE.fullmatch(email):
        return err(tr("Please enter a valid e-mail address", lg=lg))
    if not name:
        return err(tr("Please enter your name", lg=lg))
    mail = _mail_on()
    pw = b.get("password") if isinstance(b.get("password"), str) else ""
    if not mail and len(pw) < MIN_PASSWORD:
        return err(tr("Password: at least {0} characters", MIN_PASSWORD, lg=lg))
    ulang = b.get("lang") if b.get("lang") in LANGS else lg
    answer = jsonify(ok=True, mail=mail, pending=m == "approval")
    c.execute("BEGIN IMMEDIATE")
    _cleanup(c)
    if hit_limit("signup:" + client_ip(), SIGNUP_RATE, 3600):  # counted for valid requests only
        c.commit()
        return err(tr("Too many attempts, please wait a few minutes", lg=lg), 429)
    dom = email.rsplit("@", 1)[-1].lower()
    allowed = m != "domain" or dom in _domains(gsetting(c, "signup_domains")) or org_for_email(c, email) is not None
    taken = c.execute("SELECT 1 FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
    if not allowed or taken:  # the same answer: nobody learns which addresses exist or are allowed
        c.rollback()
        print("registration ignored (domain or address)", "from", client_ip(), flush=True)
        return answer
    uid = create_user(c, _username(c, email), name, pw if not mail else None, onboard=True)
    c.execute("UPDATE users SET email=?, disabled=1, signup=? WHERE id=?", (email, "confirm" if mail else "pending", uid))
    oid = org_for_email(c, email)
    if oid:
        c.execute("DELETE FROM org_members WHERE user_id=?", (uid,))
        c.execute("INSERT OR IGNORE INTO org_members(org_id,user_id) VALUES(?,?)", (oid, uid))
    from ..core.schema import USER_DEFAULTS
    fs = [x for x in (gsetting(c, "default_features") or USER_DEFAULTS["features"]).split(",") if x]
    uset(c, uid, "features", ",".join(fs + ([] if "agents" in fs else ["agents"])))
    uset(c, uid, "lang", ulang)
    ensure_inbox(c, uid)
    if mail:
        invite_new(c, uid, None, send=True, kind="signup")
    else:
        _notify_admins(c, uid)
    bump(c)
    c.commit()
    print("registration:", "confirm by mail" if mail else "waits for approval", "from", client_ip(), flush=True)
    return answer


@app.post("/api/users/<int:uid>/approve")
def user_approve(uid):
    """Admins: a registration that waits for approval becomes an active account (declining = deleting it)."""
    from ..accounts.users import admin_sees, need_admin, user_admin_dict
    need_admin()
    c = db()
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or not admin_sees(c, uid):  # 2.28.0 (#935)
        raise Denied(404)
    if u["signup"] != "pending":
        return err(tr("This account does not wait for an approval"), 409)
    c.execute("UPDATE users SET signup='', disabled=0 WHERE id=?", (uid,))
    bump(c)
    c.commit()
    return jsonify(user_admin_dict(c, c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()))


def signup_settings(c, b):
    """PATCH /api/admin/settings: signup_mode, signup_domains (admins; the caller commits). An error response or None."""
    if "signup_mode" in b:
        if b["signup_mode"] not in SIGNUP_MODES:
            return err(tr("Invalid value: {0}", "signup_mode"))
        if b["signup_mode"] in ("domain", "open") and not _mail_on():
            return err(tr("This mode needs e-mail sending (SMTP); without it only “with approval by an admin” works"), 409)
        from ..accounts.orgs import instance_mode
        if b["signup_mode"] == "open" and instance_mode(c) == "organisation":
            return err(tr("An organisation's server allows registrations only for its e-mail domains or with approval by an admin"), 409)
        gset(c, "signup_mode", b["signup_mode"])
    if "signup_domains" in b:
        if not isinstance(b["signup_domains"], str):
            return err(tr("Invalid value: {0}", "signup_domains"))
        gset(c, "signup_domains", ", ".join(_domains(b["signup_domains"])))
    return None


def signup_admin(c):
    from ..accounts.orgs import instance_mode
    from ..accounts.orgs import ORG_NAME_ENV
    return {"instance_mode": instance_mode(c), "org_name_env": bool(ORG_NAME_ENV), "signup_mode": gsetting(c, "signup_mode") if gsetting(c, "signup_mode") in SIGNUP_MODES else "off",
            "signup_domains": gsetting(c, "signup_domains"), "signup_effective": signup_mode(c), "mail_out": _mail_on()}


# ---------------------------------------------------------------- 2.23.0 (#444): sign-in link / QR code
# For family members without an e-mail address (kids, grandparents): an admin -- or a parent for their kid -- creates a
# one-time sign-in link (7 days) and shows it as a QR code; opening it on the person's device signs them in there
# (stays signed in) without a password. Never for admins or agents; the link is a credential, so it works once and an
# older one stops when a new one is made. Two-factor accounts still need their second step.
def _may_link(c, uid):
    from ..family.family import parent_of
    from ..accounts.users import admin_sees
    t = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not t or (t["kind"] or "user") == "agent" or not (admin_sees(c, uid) or parent_of(c, me(), uid)):  # 2.28.0 (#935)
        raise Denied(404)
    if not (g.user["is_admin"] or parent_of(c, me(), uid)):
        raise Denied(403)
    if t["is_admin"]:
        raise Denied(409, tr("Admins sign in with their password"))
    if t["disabled"]:
        raise Denied(409, tr("The account is disabled"))
    return t


@app.post("/api/users/<int:uid>/signin-link")
def user_signin_link(uid):
    """Admins (any person but admins / agents) and parents (their kids): a one-time sign-in link + its QR code."""
    from ..accounts.invite import invite_new
    c = db()
    _may_link(c, uid)
    out = invite_new(c, uid, me(), send=False, kind="login")
    out["qr"] = segno.make(out["link"], error="m").svg_data_uri(scale=6, border=2, dark="#000", light="#fff")
    bump(c)
    c.commit()
    return jsonify(out)


@app.post("/api/auth/link")
def auth_link():
    """{token}: signs in with a sign-in link (once); open, rate limited like the invitation page."""
    from ..accounts.invite import _limited, _lookup
    keys, e = _limited()
    if e:
        return e
    c = db()
    c.execute("BEGIN IMMEDIATE")
    hit = _lookup(c, body().get("token"), kinds=("login",))
    if not hit:
        c.rollback()
        _rate_fail(keys)
        return err(tr("This link is invalid or has expired. Ask for a new one."), 404)
    r, u = hit
    c.execute("UPDATE user_invites SET used_at=? WHERE user_id=?", (iso(now_utc()), u["id"]))
    c.commit()
    print("signed in with a sign-in link:", u["username"], "from", client_ip(), flush=True)
    if twofa_methods(c, u):
        tok = pend_new("2fa", u["id"], remember=True)
        return pend_cookie(jsonify(ok=False, twofa=True, methods=twofa_methods(c, u)), tok)
    return finish_login(c, u, True, "link")

