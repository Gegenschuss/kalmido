"""2.115.0 B (#2062): an organisation's admins invite people by e-mail -- Settings > Organisation > Invite by e-mail.

An address without an account becomes a new account (no password, user name made from the address like a registration),
member of the organisation in the chosen role, and gets the invitation mail of accounts/invite.py (the link is in the
answer, too, to copy without e-mail). An address that has an account is added as today (PUT /api/orgs/<oid>/members: the
answer says nothing more). The instance admins can switch this off (Settings > Users > Sign-in, global setting org_invites;
default on: like the instance admins' own invitations it does not depend on the registration mode of the login page).
Limits: only an admin of THIS organisation (agents never), OINV_DAY new invitations per inviting person and day, the
e-mails count against the daily mail budget (admin/hosting.py). Resend and withdraw only for accounts this organisation
invited (org_invites) that never signed in (no password, no session, the link unused); withdrawing deletes that account."""
import re
from datetime import timedelta

from flask import g, jsonify

from ..core.config import app, EMAIL_RE
from ..core.i18n import LANGS, tr
from ..core.db import body, bump, create_user, db, ensure_inbox, err, gsetting, iso, now_utc, uset, usettings, write_lock
from ..core.access import Denied
from ..accounts.session import me

OINV_DAY = 20  # new invitations per inviting person and day


def oinv_on(c):
    return gsetting(c, "org_invites") != "0"


def oinv_pending(c, uid):
    """The account never signed in: no password, no SSO link, no session, its invitation link unused."""
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["password_hash"] or u["proxy_login"] or u["oidc_subject"] or (u["kind"] or "user") == "agent":
        return False
    if c.execute("SELECT 1 FROM sessions WHERE user_id=?", (uid,)).fetchone():
        return False
    return not c.execute("SELECT 1 FROM user_invites WHERE user_id=? AND used_at IS NOT NULL", (uid,)).fetchone()


def _need(c, oid):
    from ..accounts.orgs import _need_org_admin
    _need_org_admin(c, oid)
    if not oinv_on(c):
        raise Denied(403, tr("Inviting by e-mail is switched off on this server"))


def _row(c, oid, uid):
    r = c.execute("SELECT * FROM org_invites WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
    if not r or not oinv_pending(c, uid) or not c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone():
        raise Denied(404)
    return r


def oinv_list(c, oid):
    from ..accounts.invite import invite_state
    out = []
    for r in c.execute("""SELECT i.user_id, i.role, i.created_at, u.email, u.display_name, u.username FROM org_invites i
                          JOIN users u ON u.id=i.user_id WHERE i.org_id=? ORDER BY i.created_at DESC""", (oid,)).fetchall():
        if oinv_pending(c, r["user_id"]) and c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, r["user_id"])).fetchone():
            out.append({"user_id": r["user_id"], "email": r["email"] or "", "name": r["display_name"] or r["username"],
                        "role": r["role"], "created_at": r["created_at"], "state": invite_state(c, r["user_id"]) or "expired"})
    return out


@app.get("/api/orgs/<int:oid>/invites")
def org_invites_get(oid):
    """Organisation admins: the open invitations of the organisation (accounts it invited that never signed in)."""
    c = db()
    from ..accounts.orgs import _need_org_admin
    _need_org_admin(c, oid)
    return jsonify(invites=oinv_list(c, oid) if oinv_on(c) else [], enabled=oinv_on(c))


@app.post("/api/orgs/<int:oid>/invites")
def org_invite_new(oid):
    """{email, role?: member | admin, name?, lang?}: a new account for an address without one (member of the organisation,
    invitation mail; the link in the answer), or -- the address has an account -- added like PUT /members {email}."""
    from ..accounts.orgs import ORG_ROLES, org_member_add
    from ..accounts.signup import _username
    from ..accounts.invite import invite_new
    c, b = db(), body()
    _need(c, oid)
    role = b.get("role", "member")
    if role not in ORG_ROLES:
        return err(tr("Invalid value: {0}", "role"))
    email = str(b.get("email") or "").strip()[:200]
    if not EMAIL_RE.fullmatch(email):
        return err(tr("Please enter a valid e-mail address"))
    if b.get("lang") is not None and b.get("lang") not in LANGS:
        return err(tr("Invalid value: {0}", "lang"))
    write_lock(c, "accounts")  # user names and addresses are checked and taken in one go
    if c.execute("SELECT 1 FROM users WHERE lower(email)=lower(?)", (email,)).fetchone():
        c.rollback()
        from ..accounts.orgs import org_member_put
        return org_member_put(oid)  # the existing path with the same body, unchanged (its answer says nothing more)
    since = iso(now_utc() - timedelta(days=1))
    if c.execute("SELECT COUNT(*) FROM org_invites WHERE created_by=? AND created_at>?", (me(), since)).fetchone()[0] >= OINV_DAY:
        c.rollback()
        return err(tr("Too many invitations today (at most {0}). Try again tomorrow.", OINV_DAY), 429)
    from ..api.v1 import hit_limit
    if hit_limit(f"oinv:{me()}", OINV_DAY, 86400):  # 2.115.0 review (L1): a withdraw deletes the row, this counter stays
        c.rollback()
        return err(tr("Too many invitations today (at most {0}). Try again tomorrow.", OINV_DAY), 429)
    name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip()[:60]
    username = _username(c, email)
    uid = create_user(c, username, name or username, None, onboard=True)
    c.execute("UPDATE users SET email=? WHERE id=?", (email, uid))
    from ..core.schema import USER_DEFAULTS
    fs = [x for x in (gsetting(c, "default_features") or USER_DEFAULTS["features"]).split(",") if x]
    uset(c, uid, "features", ",".join(fs + ([] if "agents" in fs else ["agents"])))  # like a new account of the admins
    lg = b.get("lang") or usettings(c, me()).get("lang") or "en"
    uset(c, uid, "lang", lg if lg in LANGS else "en")
    ensure_inbox(c, uid)
    org_member_add(c, oid, uid, role)
    c.execute("INSERT INTO org_invites(user_id,org_id,role,created_by,created_at) VALUES(?,?,?,?,?)", (uid, oid, role, me(), iso(now_utc())))
    inv = _no_link_if_sent(invite_new(c, uid, me(), send=b.get("send", True) is not False))
    bump(c)
    c.commit()
    print("organisation invitation:", username, "into organisation", oid, "by", g.user["username"], flush=True)
    return jsonify(ok=True, by_email=True, invited=True, user_id=uid, invitation=inv, invites=oinv_list(c, oid))


def _no_link_if_sent(inv):
    """2.115.0 review (M2): the link goes only to the invited address once the mail is out; an organisation admin sees it
    only when no mail went (no SMTP / an error), to hand it over by hand. Else the admin could set the password of an
    account that carries somebody else's address."""
    if inv.get("sent"):
        inv.pop("link", None)
    return inv


@app.post("/api/orgs/<int:oid>/invites/<int:uid>/resend")
def org_invite_resend(oid, uid):
    """A new link for an open invitation of this organisation (the old one stops working), by e-mail when possible."""
    from ..accounts.invite import invite_new
    from ..api.v1 import hit_limit
    c = db()
    _need(c, oid)
    _row(c, oid, uid)
    if hit_limit(f"oinv-resend:{me()}", OINV_DAY, 86400):
        return err(tr("Too many invitations today (at most {0}). Try again tomorrow.", OINV_DAY), 429)
    inv = _no_link_if_sent(invite_new(c, uid, me(), send=True))
    bump(c)
    c.commit()
    return jsonify(ok=True, invitation=inv, invites=oinv_list(c, oid))


@app.delete("/api/orgs/<int:oid>/invites/<int:uid>")
def org_invite_withdraw(oid, uid):
    """Withdraws an open invitation of this organisation: the account (never signed in) is deleted. -> {email, role} for
    the undo (invite again)."""
    from ..accounts.users import user_purge
    from ..core.serializers import unlink_files
    from ..core.pg import system_ctx
    c = db()
    _need(c, oid)
    write_lock(c, "accounts")
    r = _row(c, oid, uid)
    with system_ctx(c):  # structure, not content: memberships / lists in organisations this admin cannot see count too
        other_org = c.execute("SELECT 1 FROM org_members WHERE user_id=? AND org_id!=?", (uid, oid)).fetchone()
        owns = c.execute("SELECT 1 FROM lists WHERE owner_id=? AND is_inbox=0", (uid,)).fetchone()
    if other_org:
        raise Denied(409, tr("The person belongs to another organisation as well"))  # never delete across the boundary
    if owns:
        raise Denied(409, tr("The person owns lists: remove the person from the organisation instead"))  # handed over meanwhile
    u = c.execute("SELECT email, display_name FROM users WHERE id=?", (uid,)).fetchone()
    with system_ctx(c):  # the never used account of this organisation's own invitation (its inbox, settings, membership)
        files = user_purge(c, uid)
    bump(c)
    c.commit()
    unlink_files(files)
    print("organisation invitation withdrawn: account", uid, "organisation", oid, "by", g.user["username"], flush=True)
    return jsonify(ok=True, email=u["email"] or "", name=u["display_name"] or "", role=r["role"], invites=oinv_list(c, oid))
