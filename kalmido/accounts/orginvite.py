"""2.115.0 B (#2062): an organisation's admins invite people by e-mail -- Settings > Organisation > Invite by e-mail.

An address without an account becomes a new account (no password, user name made from the address like a registration)
and gets the invitation mail of accounts/invite.py (the link is in the answer, too, to copy without e-mail). An address that
has an account is added as today (PUT /api/orgs/<id>/members: the answer says nothing more). 2.148.1 A (#2480): an existing
account is never added silently: it gets an invitation (org_joins, a News item) and joins when the person accepts
(POST /api/orgs/<id>/join; DELETE declines); only an instance admin still adds directly (self-hosted: a hosted operator
invites too, org_member_put). Both ways answer the same (no "invited" / "user_id"). 2.453.0 (#3780): a new account takes
the same way: an org_joins row besides its org_invites row, no membership until the person accepts, so the member list
shows nothing in either case (accounts made before stay members; only an instance admin adds directly, as above). Its link
lives as long as the invitation (OJN_DAYS, Resend renews both), and setting the password opens OJN_DAYS more to accept
(OJN_LIVE). 2.148.1 A (#2486): the link of a new account goes only
to the invited address (an instance admin gets it when no mail went, logged). At most OINV_RESEND_DAY resends per invitation and day. The instance admins can switch this off (Settings > Users > Sign-in, global setting org_invites;
default on: like the instance admins' own invitations it does not depend on the registration mode of the login page).
Limits: only an admin of THIS organisation (agents never), OINV_DAY new invitations per inviting person and day, the
e-mails count against the daily mail budget (admin/hosting.py). Resend and withdraw only for accounts this organisation
invited (org_invites) that never signed in (no password, no session, the link unused); withdrawing deletes that account.
2.360.2 M (#2561): the list of open invitations has one form for both kinds: an opaque "ref" (sealed, different on every
read) instead of an account or invitation id; resend and withdraw take it for both, and withdrawing an org_joins row needs no
org_invites switch (its admins still see and end what is open).
2.593.0 (#3570): in a company of its own (orgs.self_made) an existing account the inviting admin may not see (may_see), a
disabled account or an agent gets no invitation: a silent org_joins row (ojn_silent) stands in the list like any other (the
answer, the list, Resend and Withdraw stay the same as for a new address), the person never hears of it. The day limit counts
before the address is looked up, for both kinds."""
import hashlib
import json
import re
from datetime import timedelta

from flask import g, jsonify

from ..core.config import APP_NAME, PUBLIC_URL, app, EMAIL_RE
from ..core.i18n import LANGS, N_, lang, short_day, tr
from ..core.mailframe import mail_html  # 2.1062.0 (#5786)
from ..core.db import body, bump, create_user, db, ensure_inbox, err, gsetting, iso, iso_ms, local_now, now_utc, parse_iso, uset, usettings, write_lock
from ..core.access import Denied
from ..accounts.session import me
from ..accounts.login import login_log_who  # 2.239.0 B (#2888)
from ..accounts.login import seal, unseal
from ..api.common import hit_limit  # 2.149.0 G (#2517): pulled up from functions
from ..core.schema import USER_DEFAULTS  # 2.149.0 G (#2517): pulled up from functions
from ..core.serializers import unlink_files  # 2.149.0 G (#2517): pulled up from functions
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions
from ..accounts.orgs import _need_org_admin, _oinv_pending, ORG_ROLES, _operator_apart, instance_mode, may_see, org_member_add, org_member_put  # 2.369.5 (#2517): pulled up from functions
from ..accounts.invite import invite_state, invite_new  # 2.369.5 (#2517): pulled up from functions
from ..accounts.users import user_purge  # 2.369.5 (#2517): pulled up from functions
from ..core.objhooks import person_revoked  # 2.649.0 (#5051)

OINV_DAY = 20  # new invitations per inviting person and day
OINV_RESEND_DAY = 3  # 2.148.1 A (#2486): resends per invitation and day
OJN_DAYS = 14  # 2.148.1 A (#2480): an invitation of an existing account stays open this long
# 2.453.0 (#3780): open: young enough, or the person set up the account with its link lately (a new account's link lasts as
# long as the invitation: whoever uses it on the last day still gets the full time to accept). Params: the same cut twice.
# Only a link of this invitation or newer counts (created_at): an older link does not bring an expired invitation back.
# 2.593.0 (#3570): + never a silent invitation (ojn_silent): it does not exist for the invited person
OJN_LIVE = "j.silent=0 AND (j.created_at>? OR EXISTS (SELECT 1 FROM user_invites v WHERE v.user_id=j.user_id AND v.kind='invite' AND v.used_at>? AND v.created_at>=j.created_at))"
OINV_REF = "org-invite"  # 2.360.2 M (#2561): purpose of the sealed row reference

# 2.985.0 (#4922, review F1): the address of an org_joins row as the list shows it: a silent row the one typed (it never follows
# the account's later address, which the admin must not learn), an ordinary one the account's
OJN_ADDR = "CASE WHEN j.silent=1 THEN COALESCE(NULLIF(j.email, ''), u.email) ELSE COALESCE(u.email, j.email) END"


def oinv_on(c):
    return gsetting(c, "org_invites") != "0"


def oinv_pending(c, uid):
    """The account never signed in: no password, no SSO link, no session, its invitation link unused."""
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["password_hash"] or u["proxy_login"] or u["oidc_subject"] or (u["kind"] or "user") == "agent" or u["oinv_used"]:  # 2.1062.0 (#5786, review F2)
        return False
    if c.execute("SELECT 1 FROM sessions WHERE user_id=?", (uid,)).fetchone():
        return False
    return not c.execute("SELECT 1 FROM user_invites WHERE user_id=? AND used_at IS NOT NULL", (uid,)).fetchone()


def _need(c, oid):
    _need_org_admin(c, oid)
    if not oinv_on(c):
        raise Denied(403, tr("Inviting by e-mail is switched off on this server"))


def _row(c, oid, uid):
    r = c.execute("SELECT * FROM org_invites WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
    if not r or not oinv_pending(c, uid) or not (_acct_join(c, oid, uid) or c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()):
        raise Denied(404)
    return r


def _acct_join(c, oid, uid):
    """2.453.0 (#3780): the org_joins row of account uid (also expired), None for a member: an account made before is one."""
    with system_ctx(c):  # the invited person is no member yet; the caller checked the organisation admin
        return c.execute("""SELECT j.role, j.created_at FROM org_joins j WHERE j.org_id=? AND j.user_id=?
                            AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.org_id=j.org_id AND m.user_id=j.user_id)""", (oid, uid)).fetchone()


def oinv_ref(c, oid, kind, rid):
    """2.360.2 M (#2561): a row of the open invitations for the client: kind u = a new account (id), j = org_joins (id).
    2.593.0 (#3570, review F2): the id with a fixed number of digits: the sealed text's length tells nothing of the kind
    (oinv_unref reads a reference of before the same way)."""
    return seal(c, f"{OINV_REF}:{oid}", f"{kind}{rid:018d}")


def oinv_unref(c, oid, ref):
    """(kind, id) of a row reference; plain digits = an account id (the instance admin's answer, a client of before)."""
    if ref.isdigit():
        return "u", int(ref)
    try:
        v = unseal(c, f"{OINV_REF}:{oid}", ref)
        return v[0], int(v[1:])
    except Exception:  # noqa: BLE001  (not one of ours, or for another organisation)
        raise Denied(404) from None


def oinv_addr(r):
    """2.593.0 (#3570, review F1): an invited address as the list, Resend and Withdraw show it: in small letters, whether it
    is the one typed (a new account) or the one an account holder saved in their own spelling."""
    return (r["email"] or "").strip().lower()


def oinv_list(c, oid):
    """2.360.2 M (#2561): invitations off: only what is open as org_joins (nothing new comes, its admins can still end it)."""
    out = []
    keep_id = g.user["is_admin"]  # an instance admin sees every account anyway (and gets the id in the answer of an invitation)
    since = iso(now_utc() - timedelta(days=OJN_DAYS))
    with system_ctx(c):  # the invited person is no member yet; the caller checked the organisation admin
        # 2.985.0 (#4922): + the neutral rows of a deleted account's silent invitation (user_id NULL, the address kept on the row)
        # 2.985.0 (#4922, review F1): a silent row shows the address the admin typed (j.email), the account's own only for an old row without it
        found = c.execute(f"""SELECT j.id, j.user_id, j.role, j.created_at, {OJN_ADDR} AS email FROM org_joins j LEFT JOIN users u ON u.id=j.user_id
                             WHERE j.org_id=? AND (j.user_id IS NOT NULL OR j.silent=1)
                             AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.org_id=j.org_id AND m.user_id=j.user_id)""", (oid,)).fetchall()
    joins = {r["user_id"]: r for r in found if r["user_id"] is not None}
    neutral = [r for r in found if r["user_id"] is None]
    rows = c.execute("""SELECT i.user_id, i.role, i.created_at, u.email, u.display_name, u.username FROM org_invites i
                        JOIN users u ON u.id=i.user_id WHERE i.org_id=? ORDER BY i.created_at DESC""", (oid,)).fetchall()
    for r in rows:
        if not oinv_pending(c, r["user_id"]):
            continue
        j = joins.pop(r["user_id"], None)  # 2.453.0 (#3780): one row per account: the ref of a new account (withdrawing deletes it), the values of its org_joins row
        if j:
            out.append({"ref": oinv_ref(c, oid, "u", r["user_id"]), "user_id": r["user_id"] if keep_id else None, "email": oinv_addr(j), "name": oinv_addr(j),
                        "role": j["role"], "created_at": j["created_at"], "state": "invited" if j["created_at"] > since else "expired"})
        elif oinv_on(c) and c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, r["user_id"])).fetchone():
            out.append({"ref": oinv_ref(c, oid, "u", r["user_id"]), "user_id": r["user_id"] if keep_id else None, "email": oinv_addr(r),
                        "name": oinv_addr(r) or r["display_name"] or r["username"], "role": r["role"], "created_at": r["created_at"],
                        "state": invite_state(c, r["user_id"]) or "expired"})
    # 2.148.1 H (#2480): the open invitations of existing accounts are listed, too (same form, no account id)
    out += [{"ref": oinv_ref(c, oid, "j", r["id"]), "user_id": None, "email": oinv_addr(r), "name": oinv_addr(r), "role": r["role"],
             "created_at": r["created_at"], "state": "invited" if r["created_at"] > since else "expired"} for r in list(joins.values()) + neutral]
    out.sort(key=lambda v: v["created_at"] or "", reverse=True)
    return out


@app.get("/api/orgs/<int:oid>/invites")
def org_invites_get(oid):
    """Organisation admins: the open invitations of the organisation (accounts it invited that never signed in)."""
    c = db()
    _need_org_admin(c, oid)
    return jsonify(invites=oinv_list(c, oid), enabled=oinv_on(c))


@app.post("/api/orgs/<int:oid>/invites")
def org_invite_new(oid):
    """{email, role?: member | admin, name?, lang?}: a new account for an address without one (invited like an existing
    account, invitation mail; the link in the answer), or -- the address has an account -- added like PUT /members {email}."""
    from ..accounts.signup import _username
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
    since = iso(now_utc() - timedelta(days=1))
    # 2.593.0 (#3570): before the lookup as well, so a full day answers the same for an address with an account and without
    if c.execute("SELECT COUNT(*) FROM org_invites WHERE created_by=? AND created_at>?", (me(), since)).fetchone()[0] >= OINV_DAY:
        c.rollback()
        return err(tr("Too many invitations today (at most {0}). Try again tomorrow.", OINV_DAY), 429)
    if c.execute("SELECT 1 FROM users WHERE lower(email)=lower(?)", (email,)).fetchone():
        c.rollback()
        r = org_member_put(oid, ghost=True)  # the existing path with the same body (an invitation to accept, accounts/orgs.py)
        code = r[1] if isinstance(r, tuple) else r.status_code  # 2.148.1 H (#2480): err() answers (body, code)
        if code >= 400:
            return r
        ojn_neutral_drop(c, oid, email)  # 2.985.0 (#4922): the address has an account (again): its row stands for it now
        c.commit()
        return jsonify(ok=True, by_email=True, invites=oinv_list(c, oid))  # 2.148.1 A (#2480): the same answer as a new account
    name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip()[:60]
    username = _username(c, email)
    uid = create_user(c, username, name or username, None, onboard=True, ask_purpose=me())  # 2.364.0 A (#3032)
    c.execute("UPDATE users SET email=?, oinv_made_at=now() WHERE id=?", (email, uid))  # 2.1062.0 (#5864): made by an organisation invitation
    fs = [x for x in (gsetting(c, "default_features") or USER_DEFAULTS["features"]).split(",") if x]
    uset(c, uid, "features", ",".join(fs + ([] if "agents" in fs else ["agents"])))  # like a new account of the admins
    lg = b.get("lang") or usettings(c, me()).get("lang") or "en"
    uset(c, uid, "lang", lg if lg in LANGS else "en")
    ensure_inbox(c, uid)
    ojn_neutral_drop(c, oid, email)  # 2.985.0 (#4922)
    direct = g.user["is_admin"] and not _operator_apart()  # 2.453.0 (#3780): the same test as org_member_put for an existing account
    if direct:
        org_member_add(c, oid, uid, role)
    else:
        ojn_invite(c, oid, uid, role)
    c.execute("INSERT INTO org_invites(user_id,org_id,role,created_by,created_at) VALUES(?,?,?,?,?)", (uid, oid, role, me(), iso(now_utc())))
    # 2.593.0 (#3570, review F3): an organisation admin's mail goes through the background queue like an existing account's
    inv = _no_link_if_sent(invite_new(c, uid, me(), send=True, days=None if direct else OJN_DAYS, bg=not g.user["is_admin"]), uid)  # job #692 review: always by mail (no "send": false - the link would go to the admin)
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


def _join(c, oid, jid):
    """2.360.2 M (#2561): the open org_joins row jid of organisation oid with the address (404: none)."""
    with system_ctx(c):  # the invited person is no member yet; the caller checked the organisation admin
        # 2.985.0 (#4922): a neutral row (user_id NULL, silent) the same way: its address is on the row
        r = c.execute(f"""SELECT j.id, j.user_id, j.role, j.silent, {OJN_ADDR} AS email FROM org_joins j LEFT JOIN users u ON u.id=j.user_id
                         WHERE j.id=? AND j.org_id=? AND (j.user_id IS NOT NULL OR j.silent=1)
                         AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.org_id=j.org_id AND m.user_id=j.user_id)""", (jid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.post("/api/orgs/<int:oid>/invites/<ref>/resend")
def org_invite_resend(oid, ref):
    """A new link for an open invitation of this organisation (the old one stops working), by e-mail when possible.
    2.360.2 M (#2561): an invitation of an existing account starts again (a News item, at most one a day)."""
    c = db()
    _need(c, oid)
    kind, uid = oinv_unref(c, oid, ref)
    r = _join(c, oid, uid) if kind == "j" else _row(c, oid, uid)
    if hit_limit(f"oinv-resend:{me()}", OINV_DAY, 86400):
        return err(tr("Too many invitations today (at most {0}). Try again tomorrow.", OINV_DAY), 429)
    if hit_limit(f"oinv-resend-u:{oid}:{kind}{uid}", OINV_RESEND_DAY, 86400):  # 2.148.1 A (#2486): per invitation
        return err(tr("This invitation was sent again too often today (at most {0}). Try again tomorrow.", OINV_RESEND_DAY), 429)
    if kind == "j":
        # 2.593.0 (#3570): starts again for the list only, the person still hears nothing. 2.985.0 (#4922): so does a neutral
        # row (no account any more: ojn_hidden says hidden) - the answer is the same as for a silent one
        if r["silent"] and ojn_hidden(c, oid, r["user_id"], r["email"]):
            with system_ctx(c):  # the row of a person who is no member
                c.execute("UPDATE org_joins SET created_at=? WHERE id=?", (iso(now_utc()), r["id"]))
        else:
            ojn_invite(c, oid, r["user_id"], r["role"])
        inv = {"sent": True, "email": oinv_addr(r)}
    else:
        joined = _acct_join(c, oid, uid)
        if joined:  # 2.453.0 (#3780): the invitation starts again with the link (the News item it has stays the one)
            with system_ctx(c):  # the row of a person who is no member
                c.execute("UPDATE org_joins SET created_at=? WHERE org_id=? AND user_id=?", (iso(now_utc()), oid, uid))
        inv = _no_link_if_sent(invite_new(c, uid, me(), send=True, days=OJN_DAYS if joined else None, bg=not g.user["is_admin"]), uid)  # review F3
        if not g.user["is_admin"]:  # 2.453.0 (#3780): the answer of an existing account, it must not tell the two apart (a failed mail: log only)
            if inv.get("error"):
                print("organisation invitation: resend for account", uid, "not mailed:", inv["error"], flush=True)
            inv = {"sent": True, "email": (inv.get("email") or "").strip().lower()}
    bump(c)
    c.commit()
    return jsonify(ok=True, invitation=inv, invites=oinv_list(c, oid))


@app.delete("/api/orgs/<int:oid>/invites/<ref>")
def org_invite_withdraw(oid, ref):
    """Withdraws an open invitation of this organisation: the account (never signed in) is deleted. -> {email, role} for
    the undo (invite again). 2.360.2 M (#2561): an invitation of an existing account just ends (also with invitations
    switched off; the account stays, a News item it still shows answers that the invitation is gone).
    2.458.0 (#3843): so does a new account's while another organisation's open invitation lies on it."""
    c = db()
    _need_org_admin(c, oid)
    kind, uid = oinv_unref(c, oid, ref)
    if kind == "j":
        j = _join(c, oid, uid)
        with system_ctx(c):  # the row of a person who is no member
            c.execute("DELETE FROM org_joins WHERE id=?", (j["id"],))
            c.execute("DELETE FROM org_invites WHERE org_id=? AND user_id=?", (oid, j["user_id"]))  # 2.453.0 (#3780): an account set up meanwhile stays, the invitation ends
        bump(c)
        c.commit()
        print("organisation invitation withdrawn: account", j["user_id"], "organisation", oid, "by", login_log_who(g.user), flush=True)
        return jsonify(ok=True, email=oinv_addr(j), name=oinv_addr(j), role=j["role"], invites=oinv_list(c, oid))
    joined = _acct_join(c, oid, uid)  # 2.453.0 (#3780): like an org_joins row above, an open invitation can end with invitations switched off
    if not joined:
        _need(c, oid)
    write_lock(c, "accounts")
    r = _row(c, oid, uid)
    with system_ctx(c):  # structure, not content: memberships / lists in organisations this admin cannot see count too
        other_org = c.execute("SELECT 1 FROM org_members WHERE user_id=? AND org_id!=?", (uid, oid)).fetchone()
        owns = c.execute("SELECT 1 FROM lists WHERE owner_id=? AND is_inbox=0", (uid,)).fetchone()
        cut = iso(now_utc() - timedelta(days=OJN_DAYS))
        # 2.593.0 (#3570, review F4): a silent invitation of another organisation counts too (also an old one): the account stays,
        # so that row does not vanish from the other admin's list and tell that an account was there
        other_join = c.execute(f"SELECT 1 FROM org_joins j JOIN orgs o ON o.id=j.org_id WHERE j.user_id=? AND j.org_id!=? AND (j.silent=1 OR {OJN_LIVE}) AND o.retired_at IS NULL", (uid, oid, cut, cut)).fetchone()
    if other_org:
        raise Denied(409, tr("The person belongs to another organisation as well"))  # never delete across the boundary
    if owns:
        raise Denied(409, tr("The person owns projects: remove the person from the organisation instead"))  # handed over meanwhile
    u = c.execute("SELECT email, display_name FROM users WHERE id=?", (uid,)).fetchone()
    files = []
    with system_ctx(c):  # the never used account of this organisation's own invitation (its inbox, settings, membership)
        if other_join:  # 2.458.0 (#3843): another organisation's open invitation lies on it: the account stays, only ours ends
            c.execute("DELETE FROM org_joins WHERE org_id=? AND user_id=?", (oid, uid))
            person_revoked(c, uid, oid, "leave")  # 2.649.0 (#5051): what the membership opened goes through the core (obj_revoked)
            c.execute("DELETE FROM org_members WHERE org_id=? AND user_id=?", (oid, uid))
            # 2.1062.0 (#5864): the mark "made by an organisation invitation" outlives this row (orgs.py _oinv_pending): a later
            # invitation of the never used account stays an ordinary one (else the undo, a third organisation's went silent)
            c.execute("UPDATE users SET oinv_made_at=COALESCE(oinv_made_at, ?::timestamptz) WHERE id=?", (r["created_at"], uid))
            c.execute("DELETE FROM org_invites WHERE org_id=? AND user_id=?", (oid, uid))
            # review: this invitation's link ends with it - 2.1062.0 (#5864): unless another organisation's ordinary invitation is
            # still open (OJN_LIVE): the link is the only way into the account to accept that one
            if not c.execute(f"SELECT 1 FROM org_joins j JOIN orgs o ON o.id=j.org_id WHERE j.user_id=? AND j.org_id!=? AND {OJN_LIVE} AND o.retired_at IS NULL",
                             (uid, oid, cut, cut)).fetchone():
                c.execute("DELETE FROM user_invites WHERE user_id=? AND used_at IS NULL", (uid,))
        else:
            files = user_purge(c, uid)
    bump(c)
    c.commit()
    unlink_files(files)
    print("organisation invitation withdrawn: account", uid, "organisation", oid, "by", login_log_who(g.user), flush=True)
    return jsonify(ok=True, email=oinv_addr(u), name=oinv_addr(u) or u["display_name"] or "", role=(joined or r)["role"], invites=oinv_list(c, oid))


# ---- 2.148.1 A (#2480): an existing account invited into an organisation joins only when the person accepts
def ojn_invite(c, oid, uid, role, by=None):
    """An organisation admin (checked by the caller) invites the existing account uid: one open invitation per organisation
    and person (a repeat updates the role); the person gets a News item, a push (row "assign") and a mail, at most one a day
    (2.367.4, #2974: it was only the bell, easily missed). The caller commits.
    2.278.0 A (#3095): by = the inviting admin outside a request (the org import's thread)."""
    now = now_utc()
    by = by or me()
    old = c.execute("SELECT created_at, silent FROM org_joins WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
    with system_ctx(c):  # 2.985.0 (#4922, review F4): every way of inviting (members, import): the address's neutral row gives way
        addr = c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    if addr and addr[0]:
        ojn_neutral_drop(c, oid, addr[0])
    c.execute("""INSERT INTO org_joins(org_id,user_id,role,created_by,created_at) VALUES(?,?,?,?,?)
                 ON CONFLICT(org_id, user_id) DO UPDATE SET role=excluded.role, created_by=excluded.created_by, created_at=excluded.created_at, silent=0""",
              (oid, uid, role, by, iso(now)))
    if old and not old["silent"] and old["created_at"] > iso(now - timedelta(days=1)):  # 2.593.0 (#3570): a silent one was never told
        return
    with system_ctx(c):  # the invitation reaches the person whatever their News settings say (they must answer it)
        name = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()[0]
        c.execute("INSERT INTO notifications(user_id,kind,actor_id,data,created_at) VALUES(?,?,?,?,?)",
                  (uid, "orgjoin", by, json.dumps({"org_id": oid, "name": name, "role": role}, ensure_ascii=False), iso_ms(now)))
        who = (c.execute("SELECT display_name, username FROM users WHERE id=?", (by,)).fetchone() or {"display_name": "", "username": "?"})
        who = who["display_name"] or who["username"]
        from ..accounts.secmail import sec_mail
        sec_mail(c, uid, "orgjoin", who, name)
    ojn_push(c, uid, who, name)
    print("organisation", oid, "invited account", uid, "to join, by", login_log_who(by), flush=True)


def ojn_silent(c, oid, uid, role, email=None):
    """2.593.0 (#3570): the invitation of an existing account the inviting admin may not see (org_member_put, a company of its
    own): an org_joins row with silent=1 -- in the list of open invitations like any other, nothing for the person (no News item,
    mail or push; ojn_open / ojn_mine / ojn_waiting skip it). An ordinary invitation stays as it is (review F5: an expired one
    is not opened again without the person hearing of it - like a new address invited again). The caller commits.
    2.985.0 (#4922, review F1): email = the address the admin typed, kept on the row (the list shows it, never a later one of the
    account; a deletion keeps it, ojn_neutral). Review F4: the address's neutral row gives way."""
    with system_ctx(c):  # the row of a person who is no member and whom the admin may not see
        email = (email or (c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone() or [""])[0] or "").strip().lower() or None
        if email:
            ojn_neutral_drop(c, oid, email)
        c.execute("""INSERT INTO org_joins(org_id,user_id,role,created_by,created_at,silent,email) VALUES(?,?,?,?,?,1,?)
                     ON CONFLICT(org_id, user_id) DO UPDATE SET role=excluded.role, created_by=excluded.created_by, created_at=excluded.created_at,
                     email=excluded.email WHERE org_joins.silent=1""",
                  (oid, uid, role, me(), iso(now_utc()), email))
    print("organisation", oid, "invitation of an account the admin may not see kept silent, by", login_log_who(g.user), flush=True)


def ojn_neutral(c, uid):
    """2.985.0 (#4922): before account uid is deleted (accounts/users.py _user_purge: its own deletion, the clean-up of unconfirmed
    registrations, an instance admin, a restore deleting it again): its silent invitations (ojn_silent) become neutral rows
    without an account - user_id NULL, the address as the list showed it (review F1: the one typed, kept since ojn_silent), the role, the time (they run out like any other and
    stay until an admin withdraws them). Else the row went with the account (ON DELETE CASCADE) while a new address's row
    stays: an admin could tell an account. Not for a row of an organisation the person is a member of (the list does not show
    it, it must not appear now); ordinary invitations go with the account as before. The caller commits."""
    with system_ctx(c):  # the rows of organisations the person is no member of
        n = c.execute("""UPDATE org_joins j SET user_id=NULL, email=COALESCE(NULLIF(j.email, ''), lower(trim(COALESCE(u.email, '')))), pending_lists=''
                         FROM users u WHERE u.id=j.user_id AND j.user_id=? AND j.silent=1
                         AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.org_id=j.org_id AND m.user_id=j.user_id)""", (uid,)).rowcount
    if n:
        print("organisation invitation: kept", n, "silent invitation(s) of a deleted account as neutral rows", flush=True)
    return n


def ojn_neutral_drop(c, oid, email):
    """2.985.0 (#4922): the address is invited again: its neutral row (ojn_neutral) gives way to the new invitation, as a silent
    one is renewed in place when the account is invited again - one row per address in the list. The caller commits."""
    with system_ctx(c):  # the row of no account
        c.execute("DELETE FROM org_joins WHERE org_id=? AND user_id IS NULL AND email=lower(trim(?))", (oid, email))


OJN_PURGE_DAYS = 30  # 2.1005.0 (#5118): an expired invitation stays in the admins' list this long, then the daily clean-up deletes it
# 2.1005.0 (#5118): a text time of org_joins / user_invites as timestamptz (NULL for an empty or broken value: such a row stays)
OJN_TS = "CASE WHEN pg_input_is_valid({0}, 'timestamptz') THEN {0}::timestamptz END"


def ojn_purge(c, now):
    """2.1005.0 (#5118, review F2 of 2.985.0): the daily clean-up (admin/dataretention.py lgc_expired, no switch: an
    invitation is no data of a person once it ran out) deletes the org_joins rows expired OJN_PURGE_DAYS ago (made more than
    OJN_DAYS + OJN_PURGE_DAYS days ago), unless the row is still open for the person (OJN_LIVE: a new account's link used within
    the period).
    2.1062.0 (#5786): every kind alike - an ordinary row, a silent one (ojn_silent), a neutral one (ojn_neutral) and the row of
    a never used new account this organisation made (org_invites). Before, silent and neutral rows stayed for ever because the
    new account's row stayed until withdrawn (2.1005.0 review F1: deleting only some would tell the admin that a typed address
    has an account, or had one). Now the never used account itself is withdrawn after the same period, with a warning first
    (oinv_expire), so all rows fall on the same day; the account keeps its mark (users.oinv_made_at) until then.
    An open (younger) invitation and an accepted one (the row is gone, the membership stays untouched) are not affected.
    Returns the number of rows deleted; the caller commits."""
    cut = now - timedelta(days=OJN_DAYS + OJN_PURGE_DAYS)
    with system_ctx(c):  # rows of every organisation; nobody sees anything
        oinv_mark(c)  # 2.1062.0 (#5786): the mark first - the org_invites row of a set-up account may go below
        n = c.execute(f"""DELETE FROM org_joins j WHERE {OJN_TS.format('j.created_at')} < ?::timestamptz
                          AND NOT EXISTS (SELECT 1 FROM user_invites v WHERE v.user_id=j.user_id AND v.kind='invite'
                                          AND {OJN_TS.format('v.used_at')} >= ?::timestamptz
                                          AND {OJN_TS.format('v.created_at')} >= {OJN_TS.format('j.created_at')})""",
                      (iso(cut), iso(cut))).rowcount or 0
        # 2.1062.0 (#5786): the org_invites row of an account that was set up and whose invitation row went: nothing for the
        # list any more (tenancy.py boundary_check would read it as a crossing once the person belongs to another organisation)
        c.execute(f"""DELETE FROM org_invites i WHERE {OJN_TS.format('i.created_at')} < ?::timestamptz
                      AND NOT EXISTS (SELECT 1 FROM org_joins j WHERE j.org_id=i.org_id AND j.user_id=i.user_id)
                      AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.org_id=i.org_id AND m.user_id=i.user_id)
                      AND (NOT ({OINV_UNUSED.format('i.user_id')})
                           OR EXISTS (SELECT 1 FROM org_members o WHERE o.user_id=i.user_id AND o.org_id<>i.org_id))""", (iso(cut),))  # review F8: kept by another organisation
    if n:
        print("organisation invitation: deleted", n, "invitation(s) expired more than", OJN_PURGE_DAYS, "days ago", flush=True)
    return n


# ---- 2.1062.0 (#5786): a never used account an organisation's invitation set up is withdrawn after the invitation's period
OINV_WARN_DAYS = 7  # the warning mail goes this long before (and the withdrawal waits at least this long after it went)
OINV_MIN_DAYS = 30  # never sooner after the invitation, whatever OJN_DAYS / OJN_PURGE_DAYS say
# the account {0} never signed in (oinv_pending in SQL: no password, SSO link or session, no link used, no agent; review F2:
# users.oinv_used, the durable mark of a sign-in - sessions and used links are deleted later)
OINV_UNUSED = """EXISTS (SELECT 1 FROM users x WHERE x.id={0} AND x.password_hash IS NULL AND x.proxy_login IS NULL AND x.oidc_subject IS NULL
                 AND NOT x.oinv_used AND COALESCE(x.kind, 'user')<>'agent' AND NOT EXISTS (SELECT 1 FROM sessions s WHERE s.user_id=x.id)
                 AND NOT EXISTS (SELECT 1 FROM user_invites v WHERE v.user_id=x.id AND v.used_at IS NOT NULL))"""


def oinv_mark(c):
    """users.oinv_made_at of an account an organisation's invitation set up before the mark existed (#5864): from its
    org_invites row. Daily, idempotent; the caller holds the system context and commits."""
    c.execute(f"""UPDATE users u SET oinv_made_at={OJN_TS.format('i.created_at')} FROM org_invites i
                  WHERE i.user_id=u.id AND u.oinv_made_at IS NULL AND {OJN_TS.format('i.created_at')} IS NOT NULL""")


def oinv_due(c, uid=None):
    """The never used accounts an organisation's invitation set up that may be withdrawn by themselves (uid: only that one):
    [{id, email, username, by, made, warned, last}]. Not: a disabled account (an admin's decision), one that belongs to an
    organisation other than the one that made it (the button Withdraw refuses that, too) or owns projects. last = the newest
    invitation on it (made, the org_invites row, any organisation's org_joins row - a Resend renews them): the period runs from it."""
    with system_ctx(c):  # accounts of every organisation; the clean-up shows nothing to anybody
        rows = c.execute(f"""SELECT u.id, u.email, u.username, u.oinv_made_at AS made, u.oinv_warned_at AS warned,
                   (SELECT i.created_by FROM org_invites i WHERE i.user_id=u.id) AS by,
                   GREATEST(u.oinv_made_at, (SELECT MAX({OJN_TS.format('i.created_at')}) FROM org_invites i WHERE i.user_id=u.id),
                            (SELECT MAX({OJN_TS.format('j.created_at')}) FROM org_joins j WHERE j.user_id=u.id)) AS last
                   FROM users u WHERE u.oinv_made_at IS NOT NULL AND u.disabled=0 AND {OINV_UNUSED.format('u.id')}
                   {"AND u.id=?" if uid else ""}
                   AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.user_id=u.id
                                   AND NOT EXISTS (SELECT 1 FROM org_invites i WHERE i.user_id=u.id AND i.org_id=m.org_id))
                   AND NOT EXISTS (SELECT 1 FROM lists l WHERE l.owner_id=u.id AND l.is_inbox=0)
                   ORDER BY u.id""", (uid,) if uid else ()).fetchall()
    # review F1: a TIMESTAMPTZ reads as ISO text (core/pg.py _TsLoader): times to compute with
    return [dict(r, made=parse_iso(r["made"]), last=parse_iso(r["last"]), warned=parse_iso(r["warned"]) if r["warned"] else None) for r in rows]


def oinv_expire(c, now, budget):
    """2.1062.0 (#5786, decided 12.11.2026): the daily clean-up (admin/dataretention.py lgc_tick) withdraws a never used account
    an organisation's invitation set up, like the button Withdraw (user_purge), OJN_DAYS + OJN_PURGE_DAYS days after its newest
    invitation (never under OINV_MIN_DAYS after it was made) - the day its invitation rows fall (ojn_purge), so silent, neutral
    and these rows all go alike. OINV_WARN_DAYS before, a warning goes to the account's address with the day and a link to set
    the account up (signing in keeps it); without a delivered warning nothing is withdrawn (never silently gone: no outgoing
    mail = the account stays, the warning is tried again the next day) and the withdrawal waits OINV_WARN_DAYS after it.
    A warning counts only while no invitation is newer. budget = admin/hosting.py mail_budget (the daily mail limits; passed in by
    the clean-up, which lives above this module). Commits per account. -> (warned, withdrawn)."""
    keep, warn = timedelta(days=OJN_DAYS + OJN_PURGE_DAYS), timedelta(days=OINV_WARN_DAYS)
    with system_ctx(c):
        oinv_mark(c)
        c.commit()
    warned = gone = 0
    for u in oinv_due(c):
        due = max(u["last"] + keep, u["made"] + timedelta(days=OINV_MIN_DAYS))
        if now < due - warn:
            continue
        if not u["warned"] or u["warned"] < u["last"]:
            warned += oinv_warn(c, u, max(due, now + warn), now, budget)
            continue
        if now < max(due, u["warned"] + warn):
            continue
        files = []
        try:
            with system_ctx(c):  # the never used account and what it holds (its inbox, settings, the invitation rows)
                write_lock(c, "accounts")
                c.execute("SELECT 1 FROM users WHERE id=? FOR UPDATE", (u["id"],))  # review F6: a sign-in on a path without the lock waits
                if oinv_due(c, u["id"]):  # still never used (a sign-in meanwhile keeps it)
                    with c.savepoint():
                        files = user_purge(c, u["id"])
                    gone += 1
                    bump(c)  # review F9: clients refresh (a member row of the inviting organisation went)
            c.commit()
        except Exception as e:  # noqa: BLE001  one account must not stop the others (tried again the next day)
            c.rollback()  # review F4: nothing half done stays in the transaction (and the lock goes)
            print("organisation invitation: never used account not withdrawn:", type(e).__name__, flush=True)
            continue
        unlink_files(files)
        print("organisation invitation: never used account", u["id"], "withdrawn after its period", flush=True)
    return warned, gone


def oinv_warn(c, u, at, now, budget):
    """The warning of oinv_expire: a new link (the invitation's, valid until the day) and the mail, sent right here - only a
    mail the server took counts (users.oinv_warned_at). -> 1 sent, 0 not (no outgoing mail, no address, the day's limit, an
    error)."""
    from ..integrations.mail import MAIL_OUT_ON, mail_send
    if not MAIL_OUT_ON or not (u["email"] or "").strip():
        return 0
    try:
        with system_ctx(c):  # nobody signed in: the account's own rows
            if not budget(c, None, u["email"]):
                c.rollback()
                return 0
            days = max(OINV_WARN_DAYS, (at - now).days)
            inv = invite_new(c, u["id"], u["by"], send=False, days=days)
            tok = hashlib.sha256(inv["link"].rsplit("/", 1)[-1].encode()).hexdigest()  # invite.py _hash
            subject, text, body_html = oinv_warn_mail(c, u, inv["link"], at, days)
            c.commit()  # the link is stored before the mail goes out (as invite_new does)
        mail_send(u["email"].strip(), subject, text, body_html, from_name=APP_NAME)
        with system_ctx(c):
            # a mailed link proves the address - review F5: only this link (not one an admin made meanwhile to copy)
            if not c.execute("UPDATE user_invites SET sent_at=? WHERE user_id=? AND token_hash=?", (iso(now_utc()), u["id"], tok)).rowcount:
                c.rollback()
                return 0
            c.execute("UPDATE users SET oinv_warned_at=?::timestamptz WHERE id=?", (iso(now), u["id"]))
            c.commit()
        print("organisation invitation: never used account", u["id"], "warned before its withdrawal", flush=True)
        return 1
    except Exception as e:  # noqa: BLE001  not delivered: nothing is withdrawn, tried again the next day
        c.rollback()  # review F4: no counted mail or replaced link of an unsent warning stays
        print("organisation invitation: warning mail failed:", type(e).__name__, flush=True)
        return 0


def oinv_warn_mail(c, u, link, at, days):
    """(subject, text, html) of the warning in the account's language (days: how long the link works)."""
    lg = lang(c, u["id"])
    t = lambda s, *a: tr(s, *a, lg=lg)  # noqa: E731
    tz = local_now().tzinfo
    day, made = (short_day(x.astimezone(tz).date(), lg, year=True) for x in (at, u["made"]))
    by = c.execute("SELECT display_name, username FROM users WHERE id=?", (u["by"],)).fetchone() if u["by"] else None
    who = (by["display_name"] or by["username"]) if by else t(N_("An admin"))
    subject = f"{APP_NAME}: " + t(N_("Your unused account will be removed on {0}"), day)
    lines = [t(N_("{0} created the account {1} for you on {2} with an invitation. It has not been used so far."), who, u["username"], made),
             t(N_("Unless you set it up by {0}, it will be removed automatically on that day, together with the invitation."), day),
             t(N_("Setting up the account once keeps it. If you do not need it, there is nothing to do."))]
    button, valid = t(N_("Set up your account")), t(N_("The link works once and for {0} days."), days)
    text = "\n\n".join(lines) + f"\n\n{button}: {link}\n{valid}\n"
    return subject, text, mail_html(subject, lines, button, link, lang=lg, note=valid, logo=False)


def ojn_hidden(c, oid, uid, email=None):
    """2.593.0 (#3570, review F5): a silent invitation stays silent on Resend: a disabled account or an agent, or in a company
    of its own (orgs.self_made) a person the inviting admin may not see (the test of org_member_put). Otherwise -- the admin
    may see the person by now -- Resend makes it an ordinary invitation (ojn_invite)."""
    u = c.execute("SELECT disabled, kind, email, email_proved FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["disabled"] or (u["kind"] or "user") == "agent":
        return True
    if g.user["is_admin"] and not _operator_apart():
        return False
    # 2.1021.0 (#5775): an address nobody proved stays silent on Resend (org_member_put); review 2: the address the admin typed
    # (the row's, kept since #4922) must be the proved one - not a later address of the account. 2.1062.0 (#5864): the same
    # exception as org_member_put - an account an organisation invitation set up that never signed in (its only address is
    # the typed one) - also once that first invitation was withdrawn (users.oinv_made_at)
    typed = (email or u["email"] or "").strip().lower()
    # review F7: the exception only for the address the account still has (never reveal a later one by waking the row)
    if (u["email_proved"] or "") != typed and not (typed == (u["email"] or "").strip().lower() and _oinv_pending(c, uid)):
        return True
    selfm = c.execute("SELECT self_made FROM orgs WHERE id=?", (oid,)).fetchone()
    return bool(selfm and selfm[0]) and not may_see(c, me(), uid)


def ojn_proved(c, uid, email):
    """2.1033.0 (#5790): account uid just proved its address email (integrations/mailproof.py): the silent invitations of exactly
    this address (the one the admin typed, org_joins.email since #4922) that are still open become ordinary ones (ojn_invite in
    the name of the admin who invited: News item, mail, push). One stays silent when the #3570 rule holds - a company of its own
    whose inviting admin may not see the person - or when that admin is no admin of the organisation any more (Resend by a
    current admin wakes it as before, ojn_hidden). Rows silent for another address are not touched; a woken row keeps its date
    (it runs out as it would have). -> how many woke.
    The caller commits."""
    cut = iso(now_utc() - timedelta(days=OJN_DAYS))
    em = (email or "").strip().lower()
    # review F2: like Resend (_need, org_member_put): not with inviting by e-mail switched off, only in workspaces mode
    if not em or not oinv_on(c) or instance_mode(c) != "workspaces":
        return 0
    with system_ctx(c):  # the person is no member of these organisations yet
        rows = c.execute("""SELECT j.org_id, j.role, j.created_by, o.self_made FROM org_joins j JOIN orgs o ON o.id=j.org_id
                            WHERE j.user_id=? AND j.silent=1 AND lower(COALESCE(j.email, ''))=? AND j.created_at>?
                            AND o.retired_at IS NULL AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.org_id=j.org_id AND m.user_id=j.user_id)
                            ORDER BY j.created_at""", (uid, em, cut)).fetchall()
        n = 0
        for r in rows:
            by = r["created_by"]
            if not by or not c.execute("SELECT 1 FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.user_id=? "
                                       "AND m.role='admin' AND u.disabled=0", (r["org_id"], by)).fetchone():
                continue
            if r["self_made"] and not may_see(c, by, uid):  # #3570: a company of its own reaches only people its admin may see
                continue
            # review F7: the row is locked and still silent (an admin withdrawing it meanwhile: nothing comes back)
            row = c.execute("SELECT created_at FROM org_joins WHERE org_id=? AND user_id=? AND silent=1 FOR UPDATE", (r["org_id"], uid)).fetchone()
            if not row:
                continue
            ojn_invite(c, r["org_id"], uid, r["role"], by=by)
            # review F3: the row keeps its date - the admin's list must not tell when (or that) the address was proved
            c.execute("UPDATE org_joins SET created_at=? WHERE org_id=? AND user_id=?", (row["created_at"], r["org_id"], uid))
            n += 1
    return n


def ojn_push(c, uid, who, org):
    """2.367.4 (#2974): the push of an invitation (none in the org import's thread: its people get the mail and the bell)."""
    from flask import has_request_context
    from ..collab.news import notif_ok
    from ..collab.comments import lang_of
    from ..notify.push import push_prio, push_reachable
    if not has_request_context() or g.get("pushes") is None:
        return
    s = usettings(c, uid)
    if notif_ok(c, uid, s, "assign", "push") and push_reachable(c, uid, s):
        g.pushes.append((uid, tr("{0} invites you to join the organisation {1}", who, org, lg=lang_of(s)), "", f"{PUBLIC_URL}/", push_prio(s)))


def ojn_answer(c, r, oid, uid, yes):
    """2.367.4 (#2974): whoever invited hears the answer (row "share"); system context, the person is no member yet or just became one."""
    from ..collab.news import news_add
    name = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()[0]
    if r["created_by"]:
        news_add(c, r["created_by"], "orgjoinres", actor=uid, row="share", data={"org_id": oid, "name": name, "yes": bool(yes)})


def ojn_later(c, oid, uid, by, pairs):
    """2.363.0 (#3132): the org import's projects [(list id, role)] of an invited person, noted on the open invitation (a repeat
    invitation keeps them, a second import adds to them; a declined or withdrawn invitation takes them along)."""
    with system_ctx(c):  # the row of a person who is no member yet
        r = c.execute("SELECT pending_lists FROM org_joins WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
        if r and pairs:
            have = {x[0]: x for x in json.loads(r["pending_lists"] or "[]")}
            have.update({lid: [lid, role, by] for lid, role in pairs})
            c.execute("UPDATE org_joins SET pending_lists=? WHERE org_id=? AND user_id=?", (json.dumps(list(have.values())), oid, uid))


def ojn_drop_later(c, oid, uid, by):
    """2.363.0 (#3132): the undo of an import: an invitation another admin took over meanwhile stays, the notes of "by" go."""
    with system_ctx(c):  # the row of a person who is no member yet
        r = c.execute("SELECT pending_lists FROM org_joins WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
        if r and r["pending_lists"]:
            keep = [x for x in json.loads(r["pending_lists"]) if x[2] != by]
            c.execute("UPDATE org_joins SET pending_lists=? WHERE org_id=? AND user_id=?", (json.dumps(keep), oid, uid))


def ojn_share_later(c, oid, uid, r):
    """2.363.0 (#3132): at the accepted invitation r: the noted projects are shared, as long as each is still there, in this
    organisation and the importing admin's own. -> how many. The caller holds the system context."""
    from ..lists.lists import _folder_member_add
    n = 0
    for lid, role, by in json.loads(r["pending_lists"] or "[]"):
        l = c.execute("SELECT owner_id, org_id, deleted_at FROM lists WHERE id=?", (lid,)).fetchone()
        if l and not l["deleted_at"] and l["org_id"] == oid and l["owner_id"] == by and _folder_member_add(c, lid, uid, role, by):
            n += 1
    return n


def ojn_open(c, oid, uid):
    """The open invitation row of uid into organisation oid (None: none, expired or already a member)."""
    with system_ctx(c):  # the invited person is not a member yet: row-level security would hide the organisation's row
        # 2.223.2 A (#2859): never into a retired organisation (an invitation left from before the retirement)
        cut = iso(now_utc() - timedelta(days=OJN_DAYS))
        r = c.execute(f"SELECT j.* FROM org_joins j JOIN orgs o ON o.id=j.org_id WHERE j.org_id=? AND j.user_id=? AND {OJN_LIVE} "
                      "AND o.retired_at IS NULL", (oid, uid, cut, cut)).fetchone()
        if r and c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone():
            return None
    return r


def ojn_waiting(c, uid, plain=False):
    """2.453.0 (#3780): an organisation's invitation waits for uid (plain: into a role other than admin): the first start
    counts it like the membership it becomes."""
    cut = iso(now_utc() - timedelta(days=OJN_DAYS))
    with system_ctx(c):  # my own invitations: I am not a member of these organisations yet
        return bool(c.execute(f"""SELECT 1 FROM org_joins j JOIN orgs o ON o.id=j.org_id WHERE j.user_id=? AND {OJN_LIVE} AND o.retired_at IS NULL
                                  {"AND j.role<>'admin'" if plain else ""} LIMIT 1""", (uid, cut, cut)).fetchone())


def ojn_org_name(c, uid):
    """2.453.0 (#3780): the organisation of uid's latest open invitation (mail + invitation page of a new account, no member yet)."""
    cut = iso(now_utc() - timedelta(days=OJN_DAYS))
    with system_ctx(c):  # read before any sign-in
        r = c.execute(f"""SELECT o.name FROM org_joins j JOIN orgs o ON o.id=j.org_id WHERE j.user_id=? AND {OJN_LIVE} AND o.retired_at IS NULL
                          ORDER BY j.created_at DESC LIMIT 1""", (uid, cut, cut)).fetchone()
    return r[0] if r else ""


def ojn_mine(c, uid):
    """My open invitations: [{org_id, name, role, by, created_at}] (GET /api/orgs)."""
    from ..collab.comments import user_names
    cut = iso(now_utc() - timedelta(days=OJN_DAYS))
    with system_ctx(c):  # my own invitations: I am not a member of these organisations yet
        rows = c.execute(f"""SELECT j.org_id, j.role, j.created_by, j.created_at, o.name FROM org_joins j JOIN orgs o ON o.id=j.org_id
                            WHERE j.user_id=? AND {OJN_LIVE} AND o.retired_at IS NULL AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.org_id=j.org_id
                            AND m.user_id=j.user_id) ORDER BY j.created_at DESC""", (uid, cut, cut)).fetchall()
    names = user_names(c, [r["created_by"] for r in rows])
    return [{"org_id": r["org_id"], "name": r["name"], "role": r["role"], "by": names.get(r["created_by"], ""),
             "created_at": r["created_at"]} for r in rows]


@app.post("/api/orgs/<int:oid>/join")
def org_join_accept(oid):
    """The invited person accepts the open invitation into organisation oid: member in the invited role (404 without one)."""
    from ..agents.core import need_person
    c, uid = db(), me()
    need_person(404)
    r = ojn_open(c, oid, uid)
    if not r:
        raise Denied(404)
    with system_ctx(c):  # accepting an invitation: the person is not a member yet
        org_member_add(c, oid, uid, r["role"])
        shared = ojn_share_later(c, oid, uid, r)  # 2.363.0 (#3132)
        c.execute("DELETE FROM org_joins WHERE org_id=? AND user_id=?", (oid, uid))
        ojn_answer(c, r, oid, uid, True)
        name = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()[0]
    bump(c)
    c.commit()
    print("organisation", oid, "invitation accepted by", login_log_who(g.user), flush=True)
    return jsonify(ok=True, org_id=oid, name=name, role=r["role"], shared=shared)


@app.delete("/api/orgs/<int:oid>/join")
def org_join_decline(oid):
    """The invited person declines the open invitation into organisation oid (404 without one)."""
    c, uid = db(), me()
    r = ojn_open(c, oid, uid)
    if not r:
        raise Denied(404)
    with system_ctx(c):  # declining an invitation: the person is not a member
        ojn_answer(c, r, oid, uid, False)
        c.execute("DELETE FROM org_joins WHERE org_id=? AND user_id=?", (oid, uid))
        c.execute("DELETE FROM org_invites WHERE org_id=? AND user_id=?", (oid, uid))  # 2.453.0 (#3780): a new account's row ends with it
    c.commit()
    return jsonify(ok=True)
