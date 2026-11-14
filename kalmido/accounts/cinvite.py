"""2.1156.0 (#4550): a person invites someone without an account by a link or a QR code -- whoever opens it creates an account
and is connected with the inviting person at once (the same connection as an accepted request, accounts/discover.py conn_links).

- Who invites: a person (no agent, no kid account, not disabled or waiting), collaboration on, and the instance switch
  "people without an account register with a person's invitation link" on (accounts/signup.py cinv_signup_on: an admin's
  choice, else on exactly when registration is open to anyone). Switch off: the routes answer 403 and the app shows no button.
- One link = one person: a random token of 256 bits, only its SHA-256 is stored (conn_invites), shown once as a link + QR code;
  it works once and for CINV_DAYS days. At most CINV_OPEN open links per account and CINV_DAY new ones per day. The inviting
  person lists the open ones (a note only they see, made, runs out) and takes one back (undo within CINV_UNDO_H hours).
- A link stops working when it was used, taken back, ran out, or its person can no longer invite (disabled, waiting, agent /
  kid, collaboration or the switch off); the page then only says "invalid or expired" (no reason, rate limited per client
  address like the invitation page, accounts/invite.py _limited).
- Opening it without an account: with e-mail sending name + address, the account is a registration to confirm (the mail of
  accounts/signup.py, kind "signup", naming the inviting person); the connection follows the confirmation
  (signup.SIGNUP_CONFIRMED -> cinv_confirmed), no admin approval (the person's link vouches) -- unless by then the person can no
  longer invite, the switch is off or the link was taken back: then it waits for an admin (Fable F3). An address that already
  has an account gets the very same answer (no account, no mail) -- the link is used up either way. Without e-mail: name +
  password only, NO address (nothing proves it; Fable F1/F2), the username from the name, active at once (the link is the
  proof), signed in. The account is always a PRIVATE one: never an organisation by its address, never admin or kid. A name that
  looks like a link is refused (Fable F5).
- Opening it signed in: no registration, the person confirms "Connect with X?" and is connected; the own link says so kindly.
- The inviting person gets the News item + push "X accepted your invitation" (row "share", switchable like sharing).
- Not for agents: no /api/v1 route, no MCP tool (like accounts/discover.py).
"""
import hashlib
import hmac
import re
import secrets
import unicodedata
from datetime import timedelta

import segno
from flask import g, jsonify

from ..core.config import app, EMAIL_RE, MIN_PASSWORD, PUBLIC_URL
from ..core.i18n import LANGS, N_, tr
from ..core.db import body, bump, create_user, db, ensure_inbox, err, gsetting, iso, now_utc, parse_iso, uset, write_lock
from ..core.access import Denied, collab_all, live_sql
from ..core.pg import insert_id, system_ctx
from ..core.schema import USER_DEFAULTS
from ..api.common import hit_limit
from ..accounts.session import _accept_lang, _rate_fail, client_ip, rate_ip
from ..accounts.login import finish_login, login_log_ip, pend_cookie, pend_new
from ..accounts.invite import _limited, invite_new
from ..accounts.discover import _link, _pair, _push
from ..accounts.signup import SIGNUP_CONFIRMED, SIGNUP_RATE, _cleanup, _mail_on, _notify_admins, _username, cinv_signup_on

CINV_DAYS = 14      # a link works this long
CINV_OPEN = 20      # open links per account
CINV_DAY = 10       # new links per account and day
CINV_UNDO_H = 24    # a link taken back can come back this long (while it has not run out)
CINV_KEEP_DAYS = 30  # used / taken back / run out rows stay this long (the day limit, a registration still to confirm), then the clean-up
CINV_BAD = N_("This link is invalid or has expired. Ask for a new one.")


def _hash(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


def _may_invite(u):
    """A person who may invite (and whose links work): no agent, no kid, active, not waiting."""
    return bool(u) and (u["kind"] or "user") == "user" and not u["kid"] and not u["disabled"] and not (u["signup"] or "")


def cinv_on(c):
    return collab_all() and cinv_signup_on(c)


def _need_inviter(c, need_on=True):
    """The signed-in person may make / list / take back links (else 404 like discover's _need_person, 403 when the switch is off).
    need_on=False (the list): also with the switch off -- the own links are only shown (open ones do not work then), on=False says so."""
    u = g.user
    if not u or (u["kind"] or "user") != "user" or u["kid"] or not collab_all():
        raise Denied(404)
    if need_on and not cinv_signup_on(c):
        raise Denied(403, tr("Inviting people without an account is switched off on this server"))
    return u


def _open_sql():
    return "used_at IS NULL AND revoked_at IS NULL AND expires_at>?"


def _item(r):
    return {"id": r["id"], "note": r["note"] or "", "created_at": r["created_at"], "expires_at": r["expires_at"]}


@app.get("/api/disc/invites")
def cinv_list():
    """My open invitation links (no link: only its hash is stored) + the limits."""
    c = db()
    u = _need_inviter(c, need_on=False)  # 2.1156.0 (#4550): the list answers with the switch off too (freelancer sweep: no 403 on a GET)
    rows = c.execute(f"SELECT * FROM conn_invites WHERE user_id=? AND {_open_sql()} ORDER BY id DESC", (u["id"], iso(now_utc()))).fetchall()
    return jsonify(items=[_item(r) for r in rows], limits={"open": CINV_OPEN, "day": CINV_DAY, "days": CINV_DAYS}, mail=_mail_on(), on=cinv_signup_on(c))


@app.post("/api/disc/invites")
def cinv_new():
    """{note?} -> {item, link, qr}: a new one-time link (shown this once) and its QR code."""
    c = db()
    u = _need_inviter(c)
    note = re.sub(r"\s+", " ", str(body().get("note") or "")).strip()[:80]
    write_lock(c, "cinv:" + str(u["id"]))
    now = now_utc()
    n_open = c.execute(f"SELECT COUNT(*) FROM conn_invites WHERE user_id=? AND {_open_sql()}", (u["id"], iso(now))).fetchone()[0]
    if n_open >= CINV_OPEN:
        c.rollback()
        return err(tr("You have {0} open invitation links. Withdraw one before you make a new one.", CINV_OPEN), 429)
    n_day = c.execute("SELECT COUNT(*) FROM conn_invites WHERE user_id=? AND created_at>?", (u["id"], iso(now - timedelta(days=1)))).fetchone()[0]
    if n_day >= CINV_DAY:
        c.rollback()
        return err(tr("That is enough invitation links for today. Try again tomorrow."), 429)
    tok = secrets.token_urlsafe(32)
    iid = insert_id(c, "INSERT INTO conn_invites(user_id, token_hash, note, created_at, expires_at) VALUES(?,?,?,?,?)",
                    (u["id"], _hash(tok), note, iso(now), iso(now + timedelta(days=CINV_DAYS))))
    r = c.execute("SELECT * FROM conn_invites WHERE id=?", (iid,)).fetchone()
    c.commit()
    link = f"{PUBLIC_URL}/#cinv/{tok}"
    return jsonify(item=_item(r), link=link, qr=segno.make(link, error="m").svg_data_uri(scale=6, border=2, dark="#000", light="#fff"))


@app.delete("/api/disc/invites/<int:iid>")
def cinv_withdraw(iid):
    """Take an open link back (it stops working at once)."""
    c = db()
    u = _need_inviter(c)
    write_lock(c, "accounts")  # Fable F4: not between a redemption's look-up and its use (cinv_accept holds the same lock)
    n = c.execute(f"UPDATE conn_invites SET revoked_at=? WHERE id=? AND user_id=? AND {_open_sql()}",
                  (iso(now_utc()), iid, u["id"], iso(now_utc()))).rowcount
    c.commit()
    if not n:
        raise Denied(404)
    return jsonify(ok=True)


@app.post("/api/disc/invites/<int:iid>/restore")
def cinv_restore(iid):
    """Undo of taking a link back: within CINV_UNDO_H hours, while it has not run out (and within the open limit)."""
    c = db()
    u = _need_inviter(c)
    write_lock(c, "cinv:" + str(u["id"]))
    now = now_utc()
    if c.execute(f"SELECT COUNT(*) FROM conn_invites WHERE user_id=? AND {_open_sql()}", (u["id"], iso(now))).fetchone()[0] >= CINV_OPEN:
        c.rollback()
        return err(tr("You have {0} open invitation links. Withdraw one before you make a new one.", CINV_OPEN), 429)
    n = c.execute("UPDATE conn_invites SET revoked_at=NULL WHERE id=? AND user_id=? AND used_at IS NULL AND revoked_at>? AND expires_at>?",
                  (iid, u["id"], iso(now - timedelta(hours=CINV_UNDO_H)), iso(now))).rowcount
    c.commit()
    if not n:
        raise Denied(404)
    return jsonify(ok=True)


# ---------------------------------------------------------------- opening a link (signed in or not)
def _lookup(c, tok):
    """(row, inviting account) of a valid token or None -- the same check for every reason it is not valid."""
    if not isinstance(tok, str) or not 20 <= len(tok) <= 100:
        return None
    h = _hash(tok)
    r = c.execute("SELECT * FROM conn_invites WHERE token_hash=?", (h,)).fetchone()
    if not r or not hmac.compare_digest(r["token_hash"], h) or r["used_at"] or r["revoked_at"] or parse_iso(r["expires_at"]) <= now_utc():
        return None
    with system_ctx(c):  # the inviting person's account: the opener is somebody else (or nobody signed in yet)
        u = c.execute("SELECT * FROM users WHERE id=?", (r["user_id"],)).fetchone()
    if not _may_invite(u) or not cinv_on(c):
        return None
    return r, u


def _name(u):
    return u["display_name"] or u["username"]


def _opener_ok(u):
    """A signed-in opener may connect: a person (no agent, no kid), active."""
    return _may_invite(u)


def _blocked(c, inviter, other):
    """The inviting person blocked the opener: the link does not work for them (as if invalid)."""
    with system_ctx(c):  # a block row of the inviting person about the opener
        return bool(c.execute("SELECT 1 FROM conn_blocks WHERE user_id=? AND blocked_id=?", (inviter, other)).fetchone())


def _connect(c, r, inviter, uid, name):
    """Connect inviter and uid (conn_links, like an accepted request), mark the link, tell the inviting person. Caller commits."""
    _link(c, inviter["id"], uid)
    c.execute("DELETE FROM conn_blocks WHERE user_id=? AND blocked_id=?", (uid, inviter["id"]))  # the opener chose to connect
    c.execute("UPDATE conn_invites SET linked_at=? WHERE id=?", (iso(now_utc()), r["id"]))
    _tell(c, inviter["id"], uid, name)
    bump(c)


def _tell(c, to, actor, name):
    """News item (kind connok, data.via = invite) + push in the row "share" -- both switchable like sharing (discover._push).
    Nobody may be signed in in this request yet (a new account): the new account is the one who acts while it is told."""
    was = g.get("user")
    if not was:
        with system_ctx(c):  # the new account's own row (made in this request)
            g.user = c.execute("SELECT * FROM users WHERE id=?", (actor,)).fetchone()
    try:
        _push(c, to, "cinvok", name, actor=actor)
    finally:
        g.user = was


@app.post("/api/auth/cinv/check")
def cinv_check():
    """{token} -> {name: who invites, signed_in, own, connected, mail, min_password}; open, rate limited."""
    keys, e = _limited()
    if e:
        return e
    c = db()
    hit = _lookup(c, body().get("token"))
    me_ = g.user
    if hit and me_ and me_["id"] != hit[1]["id"] and _blocked(c, hit[1]["id"], me_["id"]):
        hit = None
    if not hit:
        _rate_fail(keys)
        return err(tr(CINV_BAD), 404)
    r, inv = hit
    own = bool(me_) and me_["id"] == inv["id"]
    # an explicit connection (what "Find people" lists under Connections), not only seeing each other through a workspace
    connected = bool(me_) and not own and bool(c.execute(f"SELECT 1 FROM conn_links WHERE a_id=? AND b_id=? AND {live_sql()}",
                                                         _pair(me_["id"], inv["id"])).fetchone())
    return jsonify(name=_name(inv), signed_in=bool(me_), own=own, connected=connected, may=bool(me_) and _opener_ok(me_) and not own,
                   mail=_mail_on(), min_password=MIN_PASSWORD)


@app.post("/api/auth/cinv/accept")
def cinv_accept():
    """{token} signed in: connect. Without a session: a new private account -- with e-mail {token, name, email, lang?}, to confirm
    by the mailed link -> {ok, mail: true}; without {token, name, password, lang?} (an address is ignored), signed in -> the
    login answer + username."""
    keys, e = _limited()
    if e:
        return e
    b = body()
    c = db()
    lg = _accept_lang("en")
    me_ = g.user
    if me_ and not _opener_ok(me_):
        return err(tr("Only people can accept an invitation", lg=lg), 403)
    if not me_:  # the form's checks before anything is used up
        mail = _mail_on()
        # Fable F1/F2: without e-mail no address is asked for or kept -- an unproved address in users.email would be what an
        # OIDC first sign-in or an admin adding a member by address goes by (and the answer told whether it had an account)
        email = str(b.get("email") or "").strip()[:200] if mail else ""
        name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip()[:60]
        pw = b.get("password") if isinstance(b.get("password"), str) else ""
        if not name or _urlish(name):  # Fable F5: the name stands in a mail to the address: no link in it
            return err(tr("Please enter your name", lg=lg))
        if mail and not EMAIL_RE.fullmatch(email):
            return err(tr("Please enter a valid e-mail address", lg=lg))
        if not mail and len(pw) < MIN_PASSWORD:
            return err(tr("Password: at least {0} characters", MIN_PASSWORD, lg=lg))
    write_lock(c, "accounts")  # the redemption and a new account under one lock: a link is used once
    hit = _lookup(c, b.get("token"))
    if hit and me_ and me_["id"] != hit[1]["id"] and _blocked(c, hit[1]["id"], me_["id"]):
        hit = None
    if not hit:
        c.rollback()
        _rate_fail(keys)
        return err(tr(CINV_BAD, lg=lg), 404)
    r, inv = hit
    if me_:
        if me_["id"] == inv["id"]:
            c.rollback()
            return err(tr("This is your own invitation link. Send it to the person you want to invite.", lg=lg), 409)
        n = c.execute("UPDATE conn_invites SET used_at=?, used_by=? WHERE id=? AND used_at IS NULL AND revoked_at IS NULL",
                      (iso(now_utc()), me_["id"], r["id"])).rowcount
        if not n:  # Fable F4: taken back (or used) since the look-up
            c.rollback()
            return err(tr(CINV_BAD, lg=lg), 404)
        _connect(c, r, inv, me_["id"], _name(me_))
        c.commit()
        return jsonify(ok=True, connected=True, name=_name(inv))
    # ---- a new account
    _cleanup(c)
    if hit_limit("signup:" + rate_ip(), SIGNUP_RATE, 3600):  # the registration's own brake per client address
        c.commit()
        return err(tr("Too many attempts, please wait a few minutes", lg=lg), 429)
    n = c.execute("UPDATE conn_invites SET used_at=? WHERE id=? AND used_at IS NULL AND revoked_at IS NULL", (iso(now_utc()), r["id"])).rowcount
    if not n:
        c.rollback()
        return err(tr(CINV_BAD, lg=lg), 404)
    ulang = b.get("lang") if b.get("lang") in LANGS else lg
    if mail:
        if c.execute("SELECT 1 FROM users WHERE lower(email)=lower(?)", (email,)).fetchone():  # the same answer, no mail, no account: nobody learns which addresses have one (the link is used up)
            c.commit()
            print("invitation link: registration ignored (address)", "from", login_log_ip(client_ip()), flush=True)
            return jsonify(ok=True, mail=True)
        uid = _new_account(c, name, None, ulang, email)
        c.execute("UPDATE users SET email=?, disabled=true, signup='confirm' WHERE id=?", (email, uid))
        c.execute("UPDATE conn_invites SET used_by=? WHERE id=?", (uid, r["id"]))
        invite_new(c, uid, inv["id"], send=True, kind="signup", bg=True)  # counts against the inviting person's mail budget
        bump(c)
        c.commit()
        print("invitation link: registration, confirm by mail", "from", login_log_ip(client_ip()), flush=True)
        return jsonify(ok=True, mail=True)
    # without e-mail: active at once, the link is the proof; no address (nothing could prove it), the username from the name
    uid = _new_account(c, name, pw, ulang)
    c.execute("UPDATE conn_invites SET used_by=? WHERE id=?", (uid, r["id"]))
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    _connect(c, r, inv, uid, _name(u))
    c.commit()
    print("invitation link: account made and connected", "from", login_log_ip(client_ip()), flush=True)
    if gsetting(c, "twofa_required") == "1":
        tok = pend_new("enrol", uid, remember=True)
        return pend_cookie(jsonify(ok=False, enrol=True, methods=["totp", "passkey"], username=u["username"]), tok)
    return finish_login(c, u, True, "invite", extra={"username": u["username"]})


def _urlish(name):
    """Fable F5: a name that looks like a link or a web address ("://", "www.", "example.com")."""
    return bool(_URLISH.search(name))


_URLISH = re.compile(r"://|\bwww\.|[^\s./]\.[a-z]{2,24}(?:[/:?#]|$|\s)", re.I)


def _new_account(c, name, pw, ulang, email=""):
    """A private account like a registration (accounts/signup.py auth_signup): no organisation, never admin or kid. The
    username from the address (with e-mail) or the name ("Jörg Müller" -> jorg.muller), made unique."""
    base = email or (unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().replace(" ", ".") + "@x")
    uid = create_user(c, _username(c, base), name, pw or None, onboard=True)
    fs = [x for x in (gsetting(c, "default_features") or USER_DEFAULTS["features"]).split(",") if x]
    uset(c, uid, "features", ",".join(fs + ([] if "agents" in fs else ["agents"])))
    uset(c, uid, "lang", ulang)
    ensure_inbox(c, uid)
    return uid


def cinv_confirmed(c, uid):
    """signup.SIGNUP_CONFIRMED: a registration from an invitation link confirmed its address -> "active": active at once (no
    admin approval) and connected with the inviting person. Fable F3: when that person can no longer invite, the switch is
    off or the link was taken back -> "pending": it waits for an admin like in mode "approval" (News + push), no connection.
    None = not a registration from a link."""
    r = c.execute("SELECT * FROM conn_invites WHERE used_by=? AND linked_at IS NULL", (uid,)).fetchone()
    if not r:
        return None
    with system_ctx(c):  # the inviting person's account (the new one is not signed in yet)
        inv = c.execute("SELECT * FROM users WHERE id=?", (r["user_id"],)).fetchone()
    if r["revoked_at"] or not _may_invite(inv) or not cinv_on(c):
        c.execute("UPDATE users SET signup='pending' WHERE id=?", (uid,))
        _notify_admins(c, uid)
        return "pending"
    c.execute("UPDATE users SET signup='', disabled=false WHERE id=?", (uid,))
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    _connect(c, r, inv, uid, _name(u))
    return "active"


SIGNUP_CONFIRMED.append(cinv_confirmed)


def cinv_purge(c, now):
    """The daily clean-up (admin/dataretention.py): rows used, taken back or run out more than CINV_KEEP_DAYS ago."""
    cut = iso(now - timedelta(days=CINV_KEEP_DAYS))
    return c.execute("DELETE FROM conn_invites WHERE expires_at<? OR revoked_at<? OR (used_at<? AND (linked_at IS NOT NULL OR used_by IS NULL))",
                     (cut, cut, cut)).rowcount or 0
