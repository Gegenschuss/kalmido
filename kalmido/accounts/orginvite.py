"""2.115.0 B (#2062): an organisation's admins invite people by e-mail -- Settings > Organisation > Invite by e-mail.

An address without an account becomes a new account (no password, user name made from the address like a registration),
member of the organisation in the chosen role, and gets the invitation mail of accounts/invite.py (the link is in the
answer, too, to copy without e-mail). An address that has an account is added as today (PUT /api/orgs/<id>/members: the
answer says nothing more). 2.148.1 A (#2480): an existing account is never added silently: it gets an invitation (org_joins,
a News item) and joins when the person accepts (POST /api/orgs/<id>/join; DELETE declines); only an instance admin still
adds directly. Both ways answer the same (no "invited" / "user_id"). 2.148.1 A (#2486): the link of a new account goes only
to the invited address (an instance admin gets it when no mail went, logged). At most OINV_RESEND_DAY resends per invitation and day. The instance admins can switch this off (Settings > Users > Sign-in, global setting org_invites;
default on: like the instance admins' own invitations it does not depend on the registration mode of the login page).
Limits: only an admin of THIS organisation (agents never), OINV_DAY new invitations per inviting person and day, the
e-mails count against the daily mail budget (admin/hosting.py). Resend and withdraw only for accounts this organisation
invited (org_invites) that never signed in (no password, no session, the link unused); withdrawing deletes that account."""
import json
import re
from datetime import timedelta

from flask import g, jsonify

from ..core.config import app, EMAIL_RE
from ..core.i18n import LANGS, tr
from ..core.db import body, bump, create_user, db, ensure_inbox, err, gsetting, iso, iso_ms, now_utc, uset, usettings, write_lock
from ..core.access import Denied
from ..accounts.session import me
from ..accounts.login import login_log_who  # 2.239.0 B (#2888)
from ..api.common import hit_limit  # 2.149.0 G (#2517): pulled up from functions
from ..core.schema import USER_DEFAULTS  # 2.149.0 G (#2517): pulled up from functions
from ..core.serializers import unlink_files  # 2.149.0 G (#2517): pulled up from functions
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions

OINV_DAY = 20  # new invitations per inviting person and day
OINV_RESEND_DAY = 3  # 2.148.1 A (#2486): resends per invitation and day
OJN_DAYS = 14  # 2.148.1 A (#2480): an invitation of an existing account stays open this long


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
    # 2.148.1 H (#2480): the open invitations of existing accounts are listed, too (same form, no account id)
    from ..core.pg import system_ctx
    since = iso(now_utc() - timedelta(days=OJN_DAYS))
    with system_ctx(c):  # the invited person is no member yet; the caller checked the organisation admin
        joins = c.execute("""SELECT j.id, j.role, j.created_at, u.email FROM org_joins j JOIN users u ON u.id=j.user_id WHERE j.org_id=?
                             AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.org_id=j.org_id AND m.user_id=j.user_id)""", (oid,)).fetchall()
    out += [{"user_id": None, "join_id": r["id"], "email": r["email"] or "", "name": r["email"] or "", "role": r["role"],
             "created_at": r["created_at"], "state": "invited" if r["created_at"] > since else "expired"} for r in joins]
    out.sort(key=lambda v: v["created_at"] or "", reverse=True)
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
    # 2.115.0 review (L1): a withdraw deletes the row, this counter stays. Job #692 review: counted before the address lookup,
    # so trying addresses (an existing one takes the add path below, a new one gets an invitation) is limited the same way
    if hit_limit(f"oinv:{me()}", OINV_DAY, 86400):
        return err(tr("Too many invitations today (at most {0}). Try again tomorrow.", OINV_DAY), 429)
    write_lock(c, "accounts")  # user names and addresses are checked and taken in one go
    if c.execute("SELECT 1 FROM users WHERE lower(email)=lower(?)", (email,)).fetchone():
        c.rollback()
        from ..accounts.orgs import org_member_put
        r = org_member_put(oid)  # the existing path with the same body (an invitation to accept, accounts/orgs.py)
        code = r[1] if isinstance(r, tuple) else r.status_code  # 2.148.1 H (#2480): err() answers (body, code)
        if code >= 400:
            return r
        return jsonify(ok=True, by_email=True, invites=oinv_list(c, oid))  # 2.148.1 A (#2480): the same answer as a new account
    since = iso(now_utc() - timedelta(days=1))
    if c.execute("SELECT COUNT(*) FROM org_invites WHERE created_by=? AND created_at>?", (me(), since)).fetchone()[0] >= OINV_DAY:
        c.rollback()
        return err(tr("Too many invitations today (at most {0}). Try again tomorrow.", OINV_DAY), 429)
    name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip()[:60]
    username = _username(c, email)
    uid = create_user(c, username, name or username, None, onboard=True)
    c.execute("UPDATE users SET email=? WHERE id=?", (email, uid))
    fs = [x for x in (gsetting(c, "default_features") or USER_DEFAULTS["features"]).split(",") if x]
    uset(c, uid, "features", ",".join(fs + ([] if "agents" in fs else ["agents"])))  # like a new account of the admins
    lg = b.get("lang") or usettings(c, me()).get("lang") or "en"
    uset(c, uid, "lang", lg if lg in LANGS else "en")
    ensure_inbox(c, uid)
    org_member_add(c, oid, uid, role)
    c.execute("INSERT INTO org_invites(user_id,org_id,role,created_by,created_at) VALUES(?,?,?,?,?)", (uid, oid, role, me(), iso(now_utc())))
    inv = _no_link_if_sent(invite_new(c, uid, me(), send=True), uid)  # job #692 review: always by mail (no "send": false - the link would go to the admin)
    bump(c)
    c.commit()
    print("organisation invitation: an account into organisation", oid, "by", login_log_who(g.user), flush=True)
    # 2.148.1 A (#2480): an organisation admin gets the same answer as for an existing account (the mail result only as
    # a notice); an instance admin sees every account anyway and keeps the id (undo) and the link
    if g.user["is_admin"]:
        return jsonify(ok=True, by_email=True, invited=True, user_id=uid, invitation=inv, invites=oinv_list(c, oid))
    return jsonify(ok=True, by_email=True, invites=oinv_list(c, oid))  # 2.148.1 H (#2480): no notice -- the same answer as for an existing account


def _no_link_if_sent(inv, uid=None):
    """2.115.0 review (M2): the link goes only to the invited address once the mail is out. 2.148.1 A (#2486): the link
    goes only to the invited address (an instance admin gets it when no mail went, logged)."""
    if inv.get("sent"):
        inv.pop("link", None)
    elif g.user["is_admin"]:
        print("organisation invitation: link shown to the instance admin", login_log_who(g.user), "for account", uid, flush=True)
    else:
        inv.pop("link", None)
        inv["error"] = tr("The invitation e-mail could not be sent. Try Resend later or ask the server's admin.")
    return inv


@app.post("/api/orgs/<int:oid>/invites/<int:uid>/resend")
def org_invite_resend(oid, uid):
    """A new link for an open invitation of this organisation (the old one stops working), by e-mail when possible."""
    from ..accounts.invite import invite_new
    c = db()
    _need(c, oid)
    _row(c, oid, uid)
    if hit_limit(f"oinv-resend:{me()}", OINV_DAY, 86400):
        return err(tr("Too many invitations today (at most {0}). Try again tomorrow.", OINV_DAY), 429)
    if hit_limit(f"oinv-resend-u:{oid}:{uid}", OINV_RESEND_DAY, 86400):  # 2.148.1 A (#2486): per invitation
        return err(tr("This invitation was sent again too often today (at most {0}). Try again tomorrow.", OINV_RESEND_DAY), 429)
    inv = _no_link_if_sent(invite_new(c, uid, me(), send=True), uid)
    bump(c)
    c.commit()
    return jsonify(ok=True, invitation=inv, invites=oinv_list(c, oid))


@app.delete("/api/orgs/<int:oid>/invites/<int:uid>")
def org_invite_withdraw(oid, uid):
    """Withdraws an open invitation of this organisation: the account (never signed in) is deleted. -> {email, role} for
    the undo (invite again)."""
    from ..accounts.users import user_purge
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
        raise Denied(409, tr("The person owns projects: remove the person from the organisation instead"))  # handed over meanwhile
    u = c.execute("SELECT email, display_name FROM users WHERE id=?", (uid,)).fetchone()
    with system_ctx(c):  # the never used account of this organisation's own invitation (its inbox, settings, membership)
        files = user_purge(c, uid)
    bump(c)
    c.commit()
    unlink_files(files)
    print("organisation invitation withdrawn: account", uid, "organisation", oid, "by", login_log_who(g.user), flush=True)
    return jsonify(ok=True, email=u["email"] or "", name=u["display_name"] or "", role=r["role"], invites=oinv_list(c, oid))


# ---- 2.148.1 A (#2480): an existing account invited into an organisation joins only when the person accepts
def ojn_invite(c, oid, uid, role, by=None):
    """An organisation admin (checked by the caller) invites the existing account uid: one open invitation per organisation
    and person (a repeat updates the role); the person gets a News item (at most one a day), no push. The caller commits.
    2.278.0 A (#3095): by = the inviting admin outside a request (the org import's thread)."""
    from ..core.pg import system_ctx
    now = now_utc()
    by = by or me()
    old = c.execute("SELECT created_at FROM org_joins WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
    c.execute("""INSERT INTO org_joins(org_id,user_id,role,created_by,created_at) VALUES(?,?,?,?,?)
                 ON CONFLICT(org_id, user_id) DO UPDATE SET role=excluded.role, created_by=excluded.created_by, created_at=excluded.created_at""",
              (oid, uid, role, by, iso(now)))
    if old and old[0] > iso(now - timedelta(days=1)):
        return
    with system_ctx(c):  # the invitation reaches the person whatever their News settings say (they must answer it)
        name = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()[0]
        c.execute("INSERT INTO notifications(user_id,kind,actor_id,data,created_at) VALUES(?,?,?,?,?)",
                  (uid, "orgjoin", by, json.dumps({"org_id": oid, "name": name, "role": role}, ensure_ascii=False), iso_ms(now)))
    print("organisation", oid, "invited account", uid, "to join, by", login_log_who(by), flush=True)


def ojn_open(c, oid, uid):
    """The open invitation row of uid into organisation oid (None: none, expired or already a member)."""
    from ..core.pg import system_ctx
    with system_ctx(c):  # the invited person is not a member yet: row-level security would hide the organisation's row
        # 2.223.2 A (#2859): never into a retired organisation (an invitation left from before the retirement)
        r = c.execute("SELECT j.* FROM org_joins j JOIN orgs o ON o.id=j.org_id WHERE j.org_id=? AND j.user_id=? AND j.created_at>? "
                      "AND o.retired_at IS NULL", (oid, uid, iso(now_utc() - timedelta(days=OJN_DAYS)))).fetchone()
        if r and c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone():
            return None
    return r


def ojn_mine(c, uid):
    """My open invitations: [{org_id, name, role, by, created_at}] (GET /api/orgs)."""
    from ..core.pg import system_ctx
    from ..collab.comments import user_names
    with system_ctx(c):  # my own invitations: I am not a member of these organisations yet
        rows = c.execute("""SELECT j.org_id, j.role, j.created_by, j.created_at, o.name FROM org_joins j JOIN orgs o ON o.id=j.org_id
                            WHERE j.user_id=? AND j.created_at>? AND o.retired_at IS NULL AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.org_id=j.org_id
                            AND m.user_id=j.user_id) ORDER BY j.created_at DESC""", (uid, iso(now_utc() - timedelta(days=OJN_DAYS)))).fetchall()
    names = user_names(c, [r["created_by"] for r in rows])
    return [{"org_id": r["org_id"], "name": r["name"], "role": r["role"], "by": names.get(r["created_by"], ""),
             "created_at": r["created_at"]} for r in rows]


@app.post("/api/orgs/<int:oid>/join")
def org_join_accept(oid):
    """The invited person accepts the open invitation into organisation oid: member in the invited role (404 without one)."""
    from ..agents.core import is_agent
    from ..core.pg import system_ctx
    from ..accounts.orgs import org_member_add
    c, uid = db(), me()
    if is_agent(g.user):
        raise Denied(404)
    r = ojn_open(c, oid, uid)
    if not r:
        raise Denied(404)
    with system_ctx(c):  # accepting an invitation: the person is not a member yet
        org_member_add(c, oid, uid, r["role"])
        c.execute("DELETE FROM org_joins WHERE org_id=? AND user_id=?", (oid, uid))
        name = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()[0]
    bump(c)
    c.commit()
    print("organisation", oid, "invitation accepted by", login_log_who(g.user), flush=True)
    return jsonify(ok=True, org_id=oid, name=name, role=r["role"])


@app.delete("/api/orgs/<int:oid>/join")
def org_join_decline(oid):
    """The invited person declines the open invitation into organisation oid (404 without one)."""
    from ..core.pg import system_ctx
    c, uid = db(), me()
    if not ojn_open(c, oid, uid):
        raise Denied(404)
    with system_ctx(c):  # declining an invitation: the person is not a member
        c.execute("DELETE FROM org_joins WHERE org_id=? AND user_id=?", (oid, uid))
    c.commit()
    return jsonify(ok=True)
