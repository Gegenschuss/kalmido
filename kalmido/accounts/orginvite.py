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
org_invites switch (its admins still see and end what is open)."""
import json
import re
from datetime import timedelta

from flask import g, jsonify

from ..core.config import PUBLIC_URL, app, EMAIL_RE
from ..core.i18n import LANGS, tr
from ..core.db import body, bump, create_user, db, ensure_inbox, err, gsetting, iso, iso_ms, now_utc, uset, usettings, write_lock
from ..core.access import Denied
from ..accounts.session import me
from ..accounts.login import login_log_who  # 2.239.0 B (#2888)
from ..accounts.login import seal, unseal
from ..api.common import hit_limit  # 2.149.0 G (#2517): pulled up from functions
from ..core.schema import USER_DEFAULTS  # 2.149.0 G (#2517): pulled up from functions
from ..core.serializers import unlink_files  # 2.149.0 G (#2517): pulled up from functions
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions

OINV_DAY = 20  # new invitations per inviting person and day
OINV_RESEND_DAY = 3  # 2.148.1 A (#2486): resends per invitation and day
OJN_DAYS = 14  # 2.148.1 A (#2480): an invitation of an existing account stays open this long
# 2.453.0 (#3780): open: young enough, or the person set up the account with its link lately (a new account's link lasts as
# long as the invitation: whoever uses it on the last day still gets the full time to accept). Params: the same cut twice.
# Only a link of this invitation or newer counts (created_at): an older link does not bring an expired invitation back.
OJN_LIVE = "(j.created_at>? OR EXISTS (SELECT 1 FROM user_invites v WHERE v.user_id=j.user_id AND v.kind='invite' AND v.used_at>? AND v.created_at>=j.created_at))"
OINV_REF = "org-invite"  # 2.360.2 M (#2561): purpose of the sealed row reference


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
    if not r or not oinv_pending(c, uid) or not (_acct_join(c, oid, uid) or c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()):
        raise Denied(404)
    return r


def _acct_join(c, oid, uid):
    """2.453.0 (#3780): the org_joins row of account uid (also expired), None for a member: an account made before is one."""
    with system_ctx(c):  # the invited person is no member yet; the caller checked the organisation admin
        return c.execute("""SELECT j.role, j.created_at FROM org_joins j WHERE j.org_id=? AND j.user_id=?
                            AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.org_id=j.org_id AND m.user_id=j.user_id)""", (oid, uid)).fetchone()


def oinv_ref(c, oid, kind, rid):
    """2.360.2 M (#2561): a row of the open invitations for the client: kind u = a new account (id), j = org_joins (id)."""
    return seal(c, f"{OINV_REF}:{oid}", f"{kind}{rid}")


def oinv_unref(c, oid, ref):
    """(kind, id) of a row reference; plain digits = an account id (the instance admin's answer, a client of before)."""
    if ref.isdigit():
        return "u", int(ref)
    try:
        v = unseal(c, f"{OINV_REF}:{oid}", ref)
        return v[0], int(v[1:])
    except Exception:  # noqa: BLE001  (not one of ours, or for another organisation)
        raise Denied(404) from None


def oinv_list(c, oid):
    """2.360.2 M (#2561): invitations off: only what is open as org_joins (nothing new comes, its admins can still end it)."""
    from ..accounts.invite import invite_state
    out = []
    keep_id = g.user["is_admin"]  # an instance admin sees every account anyway (and gets the id in the answer of an invitation)
    since = iso(now_utc() - timedelta(days=OJN_DAYS))
    with system_ctx(c):  # the invited person is no member yet; the caller checked the organisation admin
        joins = {r["user_id"]: r for r in c.execute("""SELECT j.id, j.user_id, j.role, j.created_at, u.email FROM org_joins j JOIN users u ON u.id=j.user_id WHERE j.org_id=?
                             AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.org_id=j.org_id AND m.user_id=j.user_id)""", (oid,)).fetchall()}
    rows = c.execute("""SELECT i.user_id, i.role, i.created_at, u.email, u.display_name, u.username FROM org_invites i
                        JOIN users u ON u.id=i.user_id WHERE i.org_id=? ORDER BY i.created_at DESC""", (oid,)).fetchall()
    for r in rows:
        if not oinv_pending(c, r["user_id"]):
            continue
        j = joins.pop(r["user_id"], None)  # 2.453.0 (#3780): one row per account: the ref of a new account (withdrawing deletes it), the values of its org_joins row
        if j:
            out.append({"ref": oinv_ref(c, oid, "u", r["user_id"]), "user_id": r["user_id"] if keep_id else None, "email": j["email"] or "", "name": j["email"] or "",
                        "role": j["role"], "created_at": j["created_at"], "state": "invited" if j["created_at"] > since else "expired"})
        elif oinv_on(c) and c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, r["user_id"])).fetchone():
            out.append({"ref": oinv_ref(c, oid, "u", r["user_id"]), "user_id": r["user_id"] if keep_id else None, "email": r["email"] or "",
                        "name": r["email"] or r["display_name"] or r["username"], "role": r["role"], "created_at": r["created_at"],
                        "state": invite_state(c, r["user_id"]) or "expired"})
    # 2.148.1 H (#2480): the open invitations of existing accounts are listed, too (same form, no account id)
    out += [{"ref": oinv_ref(c, oid, "j", r["id"]), "user_id": None, "email": r["email"] or "", "name": r["email"] or "", "role": r["role"],
             "created_at": r["created_at"], "state": "invited" if r["created_at"] > since else "expired"} for r in joins.values()]
    out.sort(key=lambda v: v["created_at"] or "", reverse=True)
    return out


@app.get("/api/orgs/<int:oid>/invites")
def org_invites_get(oid):
    """Organisation admins: the open invitations of the organisation (accounts it invited that never signed in)."""
    c = db()
    from ..accounts.orgs import _need_org_admin
    _need_org_admin(c, oid)
    return jsonify(invites=oinv_list(c, oid), enabled=oinv_on(c))


@app.post("/api/orgs/<int:oid>/invites")
def org_invite_new(oid):
    """{email, role?: member | admin, name?, lang?}: a new account for an address without one (invited like an existing
    account, invitation mail; the link in the answer), or -- the address has an account -- added like PUT /members {email}."""
    from ..accounts.orgs import ORG_ROLES, _operator_apart, org_member_add
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
    uid = create_user(c, username, name or username, None, onboard=True, ask_purpose=me())  # 2.364.0 A (#3032)
    c.execute("UPDATE users SET email=? WHERE id=?", (email, uid))
    fs = [x for x in (gsetting(c, "default_features") or USER_DEFAULTS["features"]).split(",") if x]
    uset(c, uid, "features", ",".join(fs + ([] if "agents" in fs else ["agents"])))  # like a new account of the admins
    lg = b.get("lang") or usettings(c, me()).get("lang") or "en"
    uset(c, uid, "lang", lg if lg in LANGS else "en")
    ensure_inbox(c, uid)
    direct = g.user["is_admin"] and not _operator_apart()  # 2.453.0 (#3780): the same test as org_member_put for an existing account
    if direct:
        org_member_add(c, oid, uid, role)
    else:
        ojn_invite(c, oid, uid, role)
    c.execute("INSERT INTO org_invites(user_id,org_id,role,created_by,created_at) VALUES(?,?,?,?,?)", (uid, oid, role, me(), iso(now_utc())))
    inv = _no_link_if_sent(invite_new(c, uid, me(), send=True, days=None if direct else OJN_DAYS), uid)  # job #692 review: always by mail (no "send": false - the link would go to the admin)
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
        r = c.execute("""SELECT j.id, j.user_id, j.role, u.email FROM org_joins j JOIN users u ON u.id=j.user_id WHERE j.id=? AND j.org_id=?
                         AND NOT EXISTS (SELECT 1 FROM org_members m WHERE m.org_id=j.org_id AND m.user_id=j.user_id)""", (jid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.post("/api/orgs/<int:oid>/invites/<ref>/resend")
def org_invite_resend(oid, ref):
    """A new link for an open invitation of this organisation (the old one stops working), by e-mail when possible.
    2.360.2 M (#2561): an invitation of an existing account starts again (a News item, at most one a day)."""
    from ..accounts.invite import invite_new
    c = db()
    _need(c, oid)
    kind, uid = oinv_unref(c, oid, ref)
    r = _join(c, oid, uid) if kind == "j" else _row(c, oid, uid)
    if hit_limit(f"oinv-resend:{me()}", OINV_DAY, 86400):
        return err(tr("Too many invitations today (at most {0}). Try again tomorrow.", OINV_DAY), 429)
    if hit_limit(f"oinv-resend-u:{oid}:{kind}{uid}", OINV_RESEND_DAY, 86400):  # 2.148.1 A (#2486): per invitation
        return err(tr("This invitation was sent again too often today (at most {0}). Try again tomorrow.", OINV_RESEND_DAY), 429)
    if kind == "j":
        ojn_invite(c, oid, r["user_id"], r["role"])
        inv = {"sent": True, "email": r["email"] or ""}
    else:
        joined = _acct_join(c, oid, uid)
        if joined:  # 2.453.0 (#3780): the invitation starts again with the link (the News item it has stays the one)
            with system_ctx(c):  # the row of a person who is no member
                c.execute("UPDATE org_joins SET created_at=? WHERE org_id=? AND user_id=?", (iso(now_utc()), oid, uid))
        inv = _no_link_if_sent(invite_new(c, uid, me(), send=True, days=OJN_DAYS if joined else None), uid)
        if not g.user["is_admin"]:  # 2.453.0 (#3780): the answer of an existing account, it must not tell the two apart (a failed mail: log only)
            if inv.get("error"):
                print("organisation invitation: resend for account", uid, "not mailed:", inv["error"], flush=True)
            inv = {"sent": True, "email": inv.get("email") or ""}
    bump(c)
    c.commit()
    return jsonify(ok=True, invitation=inv, invites=oinv_list(c, oid))


@app.delete("/api/orgs/<int:oid>/invites/<ref>")
def org_invite_withdraw(oid, ref):
    """Withdraws an open invitation of this organisation: the account (never signed in) is deleted. -> {email, role} for
    the undo (invite again). 2.360.2 M (#2561): an invitation of an existing account just ends (also with invitations
    switched off; the account stays, a News item it still shows answers that the invitation is gone).
    2.458.0 (#3843): so does a new account's while another organisation's open invitation lies on it."""
    from ..accounts.users import user_purge
    from ..accounts.orgs import _need_org_admin
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
        return jsonify(ok=True, email=j["email"] or "", name=j["email"] or "", role=j["role"], invites=oinv_list(c, oid))
    joined = _acct_join(c, oid, uid)  # 2.453.0 (#3780): like an org_joins row above, an open invitation can end with invitations switched off
    if not joined:
        _need(c, oid)
    write_lock(c, "accounts")
    r = _row(c, oid, uid)
    with system_ctx(c):  # structure, not content: memberships / lists in organisations this admin cannot see count too
        other_org = c.execute("SELECT 1 FROM org_members WHERE user_id=? AND org_id!=?", (uid, oid)).fetchone()
        owns = c.execute("SELECT 1 FROM lists WHERE owner_id=? AND is_inbox=0", (uid,)).fetchone()
        cut = iso(now_utc() - timedelta(days=OJN_DAYS))
        other_join = c.execute(f"SELECT 1 FROM org_joins j JOIN orgs o ON o.id=j.org_id WHERE j.user_id=? AND j.org_id!=? AND {OJN_LIVE} AND o.retired_at IS NULL", (uid, oid, cut, cut)).fetchone()
    if other_org:
        raise Denied(409, tr("The person belongs to another organisation as well"))  # never delete across the boundary
    if owns:
        raise Denied(409, tr("The person owns projects: remove the person from the organisation instead"))  # handed over meanwhile
    u = c.execute("SELECT email, display_name FROM users WHERE id=?", (uid,)).fetchone()
    files = []
    with system_ctx(c):  # the never used account of this organisation's own invitation (its inbox, settings, membership)
        if other_join:  # 2.458.0 (#3843): another organisation's open invitation lies on it: the account stays, only ours ends
            c.execute("DELETE FROM org_joins WHERE org_id=? AND user_id=?", (oid, uid))
            c.execute("DELETE FROM org_members WHERE org_id=? AND user_id=?", (oid, uid))
            c.execute("DELETE FROM org_invites WHERE org_id=? AND user_id=?", (oid, uid))
            c.execute("DELETE FROM user_invites WHERE user_id=? AND used_at IS NULL", (uid,))  # review: this invitation's link ends with it
        else:
            files = user_purge(c, uid)
    bump(c)
    c.commit()
    unlink_files(files)
    print("organisation invitation withdrawn: account", uid, "organisation", oid, "by", login_log_who(g.user), flush=True)
    return jsonify(ok=True, email=u["email"] or "", name=u["email"] or u["display_name"] or "", role=(joined or r)["role"], invites=oinv_list(c, oid))


# ---- 2.148.1 A (#2480): an existing account invited into an organisation joins only when the person accepts
def ojn_invite(c, oid, uid, role, by=None):
    """An organisation admin (checked by the caller) invites the existing account uid: one open invitation per organisation
    and person (a repeat updates the role); the person gets a News item, a push (row "assign") and a mail, at most one a day
    (2.367.4, #2974: it was only the bell, easily missed). The caller commits.
    2.278.0 A (#3095): by = the inviting admin outside a request (the org import's thread)."""
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
        who = (c.execute("SELECT display_name, username FROM users WHERE id=?", (by,)).fetchone() or {"display_name": "", "username": "?"})
        who = who["display_name"] or who["username"]
        from ..accounts.secmail import sec_mail
        sec_mail(c, uid, "orgjoin", who, name)
    ojn_push(c, uid, who, name)
    print("organisation", oid, "invited account", uid, "to join, by", login_log_who(by), flush=True)


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
    from ..agents.core import is_agent
    from ..accounts.orgs import org_member_add
    c, uid = db(), me()
    if is_agent(g.user):
        raise Denied(404)
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
