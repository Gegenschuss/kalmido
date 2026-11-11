"""Users and the own account (admin user management, passwords, deletion)."""
import io
import json
import os
import re
import uuid
import secrets
import zipfile
from flask import g, jsonify, request, Response, send_file
from werkzeug.security import check_password_hash, generate_password_hash

from ..core.objhooks import obj_gone_drop, obj_private_refs, person_revoked  # 2.558.0 (#4709): the shared core without importing the domain layer
from ..core.config import app, COOKIE, EMAIL_RE, MIN_PASSWORD, PUBLIC_URL, USERNAME_RE
from ..core.i18n import lang, LANGS, N_, tr, trn
from ..core.db import body, bump, create_user, db, ensure_inbox, err, gsetting, now_utc, uset, usettings, iso
from ..core.pg import system_ctx
from ..accounts.session import _rate_fail, _rate_keys, _token_hash, login_wait, me, session_gen, user_public
from ..accounts.pictures import (
    AVATAR_DIR, avatar_drop_file, AVATAR_MAX_MB, avatar_path, AVATAR_PRESETS, avatar_process, avatar_url, LIST_ICON_DIR,
    list_icon_cols, list_icon_drop_file, list_icon_path, LIST_ICON_PRESETS, list_icon_process, list_icon_url, list_pic_guard,
)
from ..accounts.login import session_via, twofa_clear, twofa_methods
from ..accounts.sessions import ses_end  # 2.190.0 A (#1991)
from ..core.access import acx_drop, collab_all, Denied, joined_lists_sql, list_role, need_list, vis_sql
from ..core.serializers import unlink_files
from ..core.errors import BadInput
from ..core.orgcrypt import oc_drop_key, oc_list_org, oc_send_file, oc_write_file, rck_admin_gone, rck_admin_orgs  # 2.149.0 G (#2517): pulled up from functions; 2.539.0 (#4373): rck_*
from ..core.tokenhash import tkh_set_drop  # 2.149.0 G (#2517): pulled up from functions
from ..core.schema import USER_DEFAULTS  # 2.369.5 (#2517): pulled up from functions
from .colors import ac_valid  # 2.369.5 (#2517): pulled up from functions
from ..core.errors import BadInput as _BadInput  # 2.369.5 (#2517): pulled up from functions


# ---------------------------------------------------------------- users / account

def need_admin():
    if not g.user["is_admin"]:
        raise Denied(403)


def _invite_state(c, uid):
    from ..accounts.invite import invite_state
    return invite_state(c, uid)


def user_forget_conns(c, uid):
    """A user is deleted / becomes an agent: their own connection rows, stored tokens and grants go (list bells too).
    2.36.0 (#1116): the Paperless connection is gone from the app; its tables stay (the way back), but a deleted person's
    tokens never outlive them."""
    c.execute("DELETE FROM pl_tokens WHERE conn_id IN (SELECT id FROM pl_conns WHERE kind='personal' AND owner_id=?)", (uid,))
    c.execute("DELETE FROM pl_conns WHERE kind='personal' AND owner_id=?", (uid,))
    c.execute("DELETE FROM pl_tokens WHERE user_id=?", (uid,))
    c.execute("DELETE FROM pl_conn_users WHERE user_id=?", (uid,))
    c.execute("DELETE FROM list_bell WHERE user_id=?", (uid,))


def user_admin_dict(c, u):
    from ..family.family import kid_parents
    d = _user_admin_full(c, u, kid_parents)
    return op_account_brief(d) if d.get("apart") else d  # 2.539.0 (#4374)


# 2.539.0 (#4374, audit #2482 F4 + F8): what the operator of a hosted instance (an instance admin) sees of a client's account
# (users._op_foreign: apart) -- the states it manages and a number, never the client's e-mail address, name, photo, sign-in
# methods, organisation ids, parents or invitation (the operator console's promise). Self-hosted: never apart, unchanged.
OP_BRIEF_KEYS = ("id", "username", "kind", "is_admin", "disabled", "signup", "storage", "apart")


def op_account_brief(d):
    out = {k: d[k] for k in OP_BRIEF_KEYS if k in d}
    out.update(display_name=d["username"], avatar="", org_count=len(d.get("orgs") or []))
    if d.get("agent"):
        out["agent"] = True
    return out


def _user_admin_full(c, u, kid_parents):
    return {**user_public(u), "kind": u["kind"] or "user", "is_admin": bool(u["is_admin"]), "disabled": bool(u["disabled"]),
            "has_password": bool(u["password_hash"]), "proxy_login": u["proxy_login"] or "",
            "created_at": u["created_at"],
            **({"ntfy_topic": usettings(c, u["id"])["ntfy_topic"]} if u["id"] == me() else {}),  # 2.306.0 C (#2889): no foreign topics
            "email": u["email"] or "",
            "twofa": twofa_methods(c, u), "oidc_linked": bool(u["oidc_subject"]),
            "parents": kid_parents(c, u["id"]) if u["kid"] else [],  # 2.19.0 (#653)
            "invite": _invite_state(c, u["id"]),  # 2.22.0 (#697): invited | expired | null
            "signup": u["signup"] or "",  # 2.23.0 (#711): confirm (e-mail not confirmed) | pending (waits for approval) | ''
            "kid": bool(u["kid"]),
            **_admin_struct(c, u),  # 2.22.0 (#752) orgs, 2.28.0 (#935) org_id of an agent, number of lists
            "storage": _storage(c, u["id"]),  # 2.24.0 (#910): {used, quota_mb}
            **_op_foreign(c, u["id"])}  # 2.399.0 (#2687): hosted, a customer's account (lock / quota only)


def _op_foreign(c, uid):
    """{apart: true} for a customer's account on a hosted instance; 2.485.0 (#3939): {support_until} while it granted support
    access (listing it is no use of the grant: note=False)."""
    from ..accounts.orgs import _operator_apart, op_foreign_account
    if op_foreign_account(c, uid, note=False):
        return {"apart": True}
    if not _operator_apart() or uid == me():
        return {}
    from ..accounts.supportgrant import sga_until
    t = sga_until(c, uid)
    return {"support_until": t} if t else {}


def _admin_struct(c, u):
    """2.37.0 (#1150): ids and a count for the instance admin's account list -- read as "system" (organisation structure,
    no content), so the admin's own organisations do not narrow them."""
    with system_ctx(c):
        d = {"orgs": [r[0] for r in c.execute("SELECT org_id FROM org_members WHERE user_id=? ORDER BY org_id", (u["id"],))]}
        if (u["kind"] or "user") == "agent":
            d["org_id"] = (c.execute("SELECT org_id FROM agents WHERE user_id=?", (u["id"],)).fetchone() or [None])[0]
        d["lists"] = c.execute("SELECT COUNT(*) FROM lists WHERE owner_id=? AND is_inbox=0", (u["id"],)).fetchone()[0]
    return d


def _storage(c, uid):
    from ..admin.hosting import user_storage
    return user_storage(c, uid)


def admin_sees(c, uid):
    """2.28.0 (#935): in the mode workspaces an instance admin sees only the people they may see (their organisations and
    connections) -- groups, agents. 2.46.0 (#1592): every instance; the user management itself: om_admin_all."""
    from ..accounts.orgs import may_see
    return may_see(c, me(), uid)


# 2.399.0 (#2687): what the instance admin of a hosted instance still changes on a customer's account (users.op_foreign_account):
# lock / unlock, the storage quota, the server admin right -- never its sign-in, address, organisations or notifications
OP_ACCOUNT_KEYS = {"disabled", "storage_quota_mb", "is_admin", "_prev"}
# 2.485.0 (#3939, review F1): what the operator never changes through a client's support access (sign-in data)
OP_SUPPORT_DENY = {"password", "email", "username", "proxy_login", "reset_2fa", "oidc_unlink", "kind", "ntfy_topic"}


def om_admin_all(c, uid):
    """2.46.0 (#1592): what the user management of an instance admin may change (edit, disable, delete, invite, approve,
    sign-in link): the people the admin sees, every account outside all organisations (private space only) and every
    registration that waits for an admin's approval; the members of an organisation the admin is not in stay with that
    organisation's own admins. Listing: GET /api/users?all=1."""
    if not g.user["is_admin"]:
        return False
    with system_ctx(c):  # membership structure
        in_org = c.execute("SELECT 1 FROM org_members WHERE user_id=? LIMIT 1", (uid,)).fetchone()
        pending = c.execute("SELECT 1 FROM users WHERE id=? AND signup='pending'", (uid,)).fetchone()
        # 2.122.4 A (#1724): a private connection no longer counts (it made members of other organisations editable);
        # only a shared organisation, besides accounts outside every organisation and waiting registrations
        shared = uid == me() or c.execute("SELECT 1 FROM org_members a JOIN org_members b ON b.org_id=a.org_id "
                                          "WHERE a.user_id=? AND b.user_id=? LIMIT 1", (me(), uid)).fetchone()
    return not in_org or bool(pending) or bool(shared)


def user_orgs_public(c, uid, within=None):
    """2.627.0 (#4526): within = the organisation ids of the caller (a set) -> only the shared ones (the people list of a
    non-admin: the share dialog needs only the caller's own workspaces, never somebody's other organisations)."""
    with system_ctx(c):  # 2.37.0 (#1150): membership ids (structure)
        ids = [r[0] for r in c.execute("SELECT org_id FROM org_members WHERE user_id=? ORDER BY org_id", (uid,))]
    return ids if within is None else [i for i in ids if i in within]


@app.get("/api/users")
def users_list():
    """Everyone: enabled users (for sharing). Admins: all users with account details (2.28.0, mode workspaces: only the
    people they may see, plus the number of the others; 2.46.0 (#1592): ?all=1 = the user management, every account)."""
    c = db()
    from ..accounts.orgs import visible_people
    if g.user["is_admin"]:
        if request.args.get("all") == "1" and request.args.get("limit"):  # 2.88.0 (#1980): one page + search / filter / total
            from ..accounts.useradmin import ua8_users_page
            return ua8_users_page(c)
        from ..integrations.mail import MAIL_OUT_ON
        vis = None if request.args.get("all") == "1" else visible_people(c, me())
        rows = c.execute("SELECT * FROM users ORDER BY id").fetchall()
        return jsonify(users=[user_admin_dict(c, u) for u in rows if vis is None or u["id"] in vis], mail_out=MAIL_OUT_ON,
                       others=sum(1 for u in rows if vis is not None and u["id"] not in vis))
    if not collab_all():  # nobody to share with
        return jsonify(users=[user_public(g.user)])
    mine = me()  # 2.7.2 (#420): somebody else's personal agent is not in the list
    vis = visible_people(c, mine)  # 2.22.0 (#752): only the people this person may see (organisation / contacts)
    # 2.28.0 (#935): + the organisations of each person (ids), so the share dialog offers only the list's workspace; agents
    # carry the workspace they work in
    with system_ctx(c):  # 2.37.0 (#1150): which accounts are agents and of which workspace (ids, structure; vis filters people)
        ag_org = {r[0]: r[1] for r in c.execute("SELECT user_id, org_id FROM agents")}
        rows = c.execute("""SELECT * FROM users WHERE disabled=0 AND id NOT IN
                            (SELECT user_id FROM agents WHERE owner_id IS NOT NULL AND owner_id!=?) ORDER BY id""", (mine,)).fetchall()
    from ..accounts.orgs import user_orgs
    # 2.627.0 (#4526): the caller's organisations (not retired; an agent: its workspace), once; each person's list is cut to them
    own = set(user_orgs(c, mine)) | ({ag_org[mine]} if ag_org.get(mine) else set())
    return jsonify(users=[{**user_public(u), "orgs": user_orgs_public(c, u["id"], own), **({"org_id": ag_org.get(u["id"])} if u["id"] in ag_org else {})}
                          for u in rows if vis is None or u["id"] in vis])


def om_orgs_arg(c, b):
    """2.46.0 (#1561): body field orgs of POST /api/users -> [(org id, role)], or an error text. Items: {id, role?: member |
    admin} (an organisation id alone = member). Every organisation must exist; a kid account is never an organisation's
    admin; the mode shared has none."""
    from ..accounts.orgs import ORG_ROLES, instance_mode
    v = b.get("orgs")
    if v is None:
        return []
    bad = tr("Invalid value: {0}", "orgs")
    if not isinstance(v, list) or len(v) > 50 or (v and instance_mode(c) == "shared"):
        return bad
    out = {}
    for x in v:
        oid, role = (x, "member") if not isinstance(x, dict) else (x.get("id"), x.get("role", "member"))
        if not isinstance(oid, int) or isinstance(oid, bool) or role not in ORG_ROLES:
            return bad
        if role == "admin" and b.get("kid") is True:
            return tr("A kid account cannot be an admin of an organisation")
        out[oid] = role
    with system_ctx(c):  # the instance admin: which organisations exist (structure)
        for oid in out:
            if not c.execute("SELECT 1 FROM orgs WHERE id=? AND personal_of IS NULL AND retired_at IS NULL", (oid,)).fetchone():  # 2.47.3 (#1360)
                return tr("Unknown organisation")
    return sorted(out.items())


def _proxy_taken(c, login, uid=None):
    return bool(login) and bool(c.execute("SELECT 1 FROM users WHERE lower(proxy_login)=lower(?) AND id IS DISTINCT FROM ?",
                                          (login, uid)).fetchone())


def _active_admins(c, without=None):
    return c.execute("SELECT COUNT(*) FROM users WHERE is_admin=1 AND disabled=0 AND id IS DISTINCT FROM ?", (without,)).fetchone()[0]


@app.post("/api/users")
def user_create():
    from ..notify.push import NTFY_TOPIC_RE
    from ..notify.alerts import aa_now
    from ..family.family import kid_set
    need_admin()
    b = body()
    c = db()
    username = (b.get("username") or "").strip().lower()
    if not USERNAME_RE.fullmatch(username):
        return err(tr("Username: 1-32 characters a-z, 0-9, dot, dash, underscore"))
    if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        return err(tr("Username already exists"), 409)
    pw = b.get("password") or ""
    if pw and len(pw) < MIN_PASSWORD:
        return err(tr("Password: at least {0} characters", MIN_PASSWORD))
    proxy = (b.get("proxy_login") or "").strip() or None
    if _proxy_taken(c, proxy):
        return err(tr("This proxy sign-in is already assigned"), 409)
    topic = str(b.get("ntfy_topic") or "").strip()
    if topic and not NTFY_TOPIC_RE.fullmatch(topic):
        return err(tr("ntfy topic: 1-64 characters a-z, A-Z, 0-9, dash, underscore"))
    orgs = om_orgs_arg(c, b)  # 2.46.0 (#1561): checked before the account exists
    if isinstance(orgs, str):
        return err(orgs)
    from ..accounts.orgs import _operator_apart, op_apart_deny, op_foreign_org
    if any(op_foreign_org(c, o, grant=False) for o, _role in orgs):  # 2.485.0 (#3939): not even through support access  # 2.399.0 (#2687): hosted: nobody new in a customer's organisation by the operator
        op_apart_deny()
    uid = create_user(c, username, (b.get("display_name") or "").strip()[:60] or username, pw or None, proxy,
                      bool(b.get("is_admin")), ntfy_topic=topic or None, onboard=True,
                      ask_purpose=None if b.get("kid") is True else me() if orgs else 0)  # 2.364.0 A (#3032)
    if _operator_apart():  # 2.480.0 (#3944, F8): hosted: the operator's own account until it signs in (orgs.op_foreign_account)
        c.execute("UPDATE users SET op_made_by=? WHERE id=?", (me(), uid))
    email = str(b.get("email") or "").strip()[:200]
    if email and not EMAIL_RE.fullmatch(email):
        c.rollback()
        return err(tr("Invalid value: {0}", "email"))
    if email:
        c.execute("UPDATE users SET email=? WHERE id=?", (email, uid))
    # 2.15.0 (#632): the language given for the person (lang), else the admin's as before; the inbox (and later the
    # "Getting started" list) are created in it
    lg = str(b.get("lang")) if b.get("lang") in LANGS else usettings(c, me())["lang"]
    if b.get("lang") and b["lang"] not in LANGS:
        c.rollback()
        return err(tr("Invalid value: {0}", "lang"))
    uset(c, uid, "lang", lg if lg in LANGS else "en")
    if b.get("kid") is not True:  # 2.22.0 (#739): new people start with the module Agents on (kids not; existing users unchanged)
        fs = [x for x in (gsetting(c, "default_features") or USER_DEFAULTS["features"]).split(",") if x]
        uset(c, uid, "features", ",".join(fs + ([] if "agents" in fs else ["agents"])))
    ensure_inbox(c, uid)
    if b.get("kid") is True:  # 2.19.0 (#653): a kid account (never an admin)
        e = kid_set(c, uid, True, b.get("parents"))
        if e:
            c.rollback()
            return err(e)
    # 2.46.0 (#1561 / #1562): the organisations the admin chose for the new person (none given = none, never the
    # admin's own or the instance's first)
    from ..accounts.orgs import org_member_add
    with system_ctx(c):  # 2.37.0 (#1150): the instance admin places the new account (organisation structure, no content)
        for o, role in orgs:
            org_member_add(c, o, uid, role)
    inv = None
    if b.get("invite") is True and not pw:  # 2.22.0 (#697): no password: a one-time link to set it (by e-mail when possible)
        from ..accounts.invite import invite_new
        inv = invite_new(c, uid, me(), send=b.get("send", True) is not False)
    bump(c)
    c.commit()
    if b.get("is_admin"):
        aa_now("security", f"admin:{username}", N_("{0} is now an admin (set by {1})."), [username, g.user["username"]])
    out = user_admin_dict(c, c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    return jsonify({**out, **({"invitation": inv} if inv else {})})


@app.patch("/api/users/<int:uid>")
def user_update(uid):
    from ..notify.push import NTFY_TOPIC_RE
    from ..notify.alerts import aa_now
    from ..agents.core import agent_row, is_agent
    from ..agents.admin import agent_org_set, make_agent
    from ..family.family import kid_parents, kid_set
    need_admin()
    b = body()
    c = db()
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or not om_admin_all(c, uid):  # 2.46.0 (#1592): the user management: every account
        return err(tr("unknown person"), 404)
    from ..accounts.orgs import op_apart_deny, op_foreign_account, op_foreign_org, op_support_deny, op_support_only
    if op_foreign_account(c, uid) and set(b) - OP_ACCOUNT_KEYS:  # 2.399.0 (#2687): hosted: a customer's account only locked / its quota
        op_apart_deny()
    if set(b) & OP_SUPPORT_DENY and op_support_only(c, uid=uid):  # 2.485.0 (#3939, review F1): no credentials through support access
        op_support_deny()
    prev = b.get("_prev") if isinstance(b.get("_prev"), dict) else {}
    for k in ("orgs", "parents"):  # 2.270.0 A (#3019): with _prev only what the dialog changed (who joined meanwhile stays)
        if all(isinstance(v, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in v) for v in (b.get(k), prev.get(k))):
            cur = set(user_orgs_public(c, uid) if k == "orgs" else kid_parents(c, uid))
            b[k] = sorted((cur | (set(b[k]) - set(prev[k]))) - (set(prev[k]) - set(b[k])))
    if uid == me() and (("is_admin" in b and not b["is_admin"]) or b.get("disabled") or b.get("kind") == "agent"):  # 2.585.0 (#4290, review 4): before the organisation part, nothing runs before the 400
        return err(tr("You cannot remove your own admin rights or disable yourself"))
    from ..accounts.orgs import instance_mode
    if "orgs" in b and instance_mode(c) == "workspaces":  # 2.22.0 (#752): the person's organisations (replaces them); 2.23.0: multi only; 2.28.0: + workspaces
        if not isinstance(b["orgs"], list) or not all(isinstance(x, int) for x in b["orgs"]):
            return err(tr("Invalid value: {0}", "orgs"))
        from ..accounts.orgs import _operator_apart, org_heir_lift, org_join_or_add, org_leave, org_own_admin
        with system_ctx(c):  # 2.37.0 (#1150): the instance admin moves the account between organisations (structure)
            have = {r[0]: r[1] for r in c.execute("SELECT org_id, role FROM org_members WHERE user_id=?", (uid,))}
        if any(op_foreign_org(c, o, grant=False) for o in set(have) ^ set(b["orgs"])):  # 2.485.0 (#3939): not through support access  # 2.399.0 (#2687): hosted: in or out of a customer's organisation
            op_apart_deny()
        with system_ctx(c):
            for o in sorted(set(have) - set(b["orgs"])):  # 2.28.0 (#935): taken out of an organisation = leaving it (lists stay with it)
                if _operator_apart():  # 2.306.0 Fix-1 (#2875 review): hosted: the lists go to an admin of its own, never the operator (409 without one)
                    heir = org_own_admin(c, o, uid)
                    if heir is None:
                        c.rollback()
                        return err(tr("The last admin of an organisation cannot leave it: make somebody else an admin first"), 409)
                    org_leave(c, o, uid, heir)
                    continue
                heir = (c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role='admin' AND u.disabled=0 AND m.user_id!=? ORDER BY m.user_id LIMIT 1", (o, uid)).fetchone() or [me()])[0]
                heir = heir if heir != uid else me()
                if heir == me():
                    org_heir_lift(c, o, heir)  # 2.538.0 (#4371, review 2646 finding 8): in it as guest / read-only: admin first, no 409 halfway
                org_leave(c, o, uid, heir)
            for o in b["orgs"]:
                if o not in have:
                    if c.execute("SELECT 1 FROM orgs WHERE id=? AND personal_of IS NULL AND retired_at IS NULL", (o,)).fetchone():
                        org_join_or_add(c, o, uid)  # 2.306.0 D1 (#2875): hosted: an invitation the person accepts
    if "kind" in b:  # 2.0.0: person <-> agent
        if b["kind"] not in ("user", "agent"):
            return err(tr("Invalid value: {0}", "kind"))
        if b["kind"] == "agent" and not is_agent(u):
            if u["is_admin"] or b.get("is_admin"):
                return err(tr("Remove the admin rights first: an agent is never an admin"))
            from ..accounts.orgs import user_orgs
            was = user_orgs(c, uid)
            make_agent(c, uid)
            if was:  # 2.37.0 (#1150): the converted account keeps working in its organisation (row-level security: a private
                # agent never reads an organisation's lists, not even its own)
                try:
                    with c.savepoint():
                        agent_org_set(c, uid, was[0])
                except _BadInput:
                    pass  # lists in several workspaces: stays private (the boundary check reports it)
        elif b["kind"] == "user" and is_agent(u):
            a = agent_row(c, uid)
            if a and a["webhook_id"]:
                c.execute("DELETE FROM webhooks WHERE id=?", (a["webhook_id"],))
            c.execute("DELETE FROM agents WHERE user_id=?", (uid,))
            c.execute("UPDATE users SET kind='user' WHERE id=?", (uid,))
            acx_drop()  # 2.602.0 (#4729): the account kind is cached per request (office/rights.py _is_agent)
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if is_agent(u) and b.get("is_admin"):
        c.rollback()
        return err(tr("An agent is never an admin"))
    if (("is_admin" in b and not b["is_admin"]) or b.get("disabled")) and u["is_admin"] and not _active_admins(c, uid):
        return err(tr("At least one active admin is needed"))
    if "display_name" in b:
        c.execute("UPDATE users SET display_name=? WHERE id=?", ((b["display_name"] or "").strip()[:60] or u["username"], uid))
    if "proxy_login" in b:
        proxy = (b["proxy_login"] or "").strip() or None
        if _proxy_taken(c, proxy, uid):
            return err(tr("This proxy sign-in is already assigned"), 409)
        c.execute("UPDATE users SET proxy_login=? WHERE id=?", (proxy, uid))
    if "is_admin" in b:
        c.execute("UPDATE users SET is_admin=? WHERE id=?", (1 if b["is_admin"] else 0, uid))
    if "disabled" in b:
        c.execute("UPDATE users SET disabled=? WHERE id=?", (1 if b["disabled"] else 0, uid))
        if b["disabled"]:
            ses_end(c, uid)  # 2.190.0 A (#1991): with the push subscriptions made in them
            if not u["disabled"]:  # 2.539.0 (#4373): a locked admin who saw an organisation's recovery key
                for o in rck_admin_orgs(c, uid):
                    rck_admin_gone(c, o, uid)
    if "password" in b:  # reset ('' = remove the built-in login)
        pw = b["password"] or ""
        if pw and len(pw) < MIN_PASSWORD:
            return err(tr("Password: at least {0} characters", MIN_PASSWORD))
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw) if pw else None, uid))
        ses_end(c, uid)  # 2.190.0 A (#1991)
        # 2.190.0 A (#2496): the app passwords (CalDAV/CardDAV) go too. 2.360.0 A (#2496): and a person's own API tokens
        # (an agent's tokens belong to the agent's account: they stay)
        c.execute("DELETE FROM app_passwords WHERE user_id=?", (uid,))
        c.execute("DELETE FROM api_tokens WHERE user_id IN (SELECT id FROM users WHERE id=? AND COALESCE(kind, 'user')<>'agent')", (uid,))
        from ..docs.scankeys import sk_revoke_all  # 2.237.0 C (#2865): and the scan inbox keys
        sk_revoke_all(c, uid)
    if "ntfy_topic" in b:
        topic = str(b["ntfy_topic"] or "").strip()
        if topic and not NTFY_TOPIC_RE.fullmatch(topic):
            return err(tr("ntfy topic: 1-64 characters a-z, A-Z, 0-9, dash, underscore"))
        uset(c, uid, "ntfy_topic", topic)
    if "avatar_preset" in b:  # 1.9.0: a preset picture or none (e.g. for the bot user of an API integration);
        p = b["avatar_preset"]  # an own photo is uploaded by the user only, an admin can remove it (null)
        if p is not None and p not in AVATAR_PRESETS:
            c.rollback()
            return err(tr("Invalid value: {0}", "avatar_preset"))
        c.execute("UPDATE users SET avatar=? WHERE id=?", (f"p:{p}" if p else None, uid))
        if (u["avatar"] or "") != (f"p:{p}" if p else ""):
            avatar_drop_file(uid, u["avatar"])
    if "email" in b:  # optional; OIDC links a user by it (verified e-mail claim)
        email = str(b["email"] or "").strip()[:200]
        if email and not EMAIL_RE.fullmatch(email):
            c.rollback()
            return err(tr("Invalid value: {0}", "email"))
        c.execute("UPDATE users SET email=? WHERE id=?", (email or None, uid))
        if (email or None) != (u["email"] or None):  # review 2.539.0 (#4375): a link mailed to the old address proves no new one
            c.execute("UPDATE user_invites SET sent_at=NULL WHERE user_id=? AND used_at IS NULL", (uid,))
    if "storage_quota_mb" in b:  # 2.24.0 (#910): the person's own storage quota in MB (null = the server's default, 0 = unlimited)
        q = b["storage_quota_mb"]
        if q is not None and (isinstance(q, bool) or not isinstance(q, int) or not 0 <= q <= 10_000_000):
            c.rollback()
            return err(tr("Invalid value: {0}", "storage_quota_mb"))
        c.execute("UPDATE users SET storage_quota_mb=? WHERE id=?", (q, uid))
    if b.get("oidc_unlink") is True:  # the next OIDC login links again (by user name / e-mail)
        c.execute("UPDATE users SET oidc_subject=NULL WHERE id=?", (uid,))
    if "kid" in b or "parents" in b or (b.get("is_admin") and u["kid"]):  # 2.19.0 (#653): a kid account and who looks after it
        e = kid_set(c, uid, b["kid"] if "kid" in b else bool(u["kid"]), b.get("parents"))
        if e:
            c.rollback()
            return err(e)
    reset = b.get("reset_2fa") is True and bool(twofa_methods(c, u) or u["totp_secret"])
    if reset:  # lost phone and recovery codes: the user logs in with the password alone (or must enrol again)
        twofa_clear(c, uid)
        ses_end(c, uid)  # 2.190.0 A (#1991)
    bump(c)
    c.commit()
    from .secmail import sec_mail  # 2.266.0 (#2963): the person hears of what an admin changed on their account
    nu = c.execute("SELECT email, disabled, password_hash FROM users WHERE id=?", (uid,)).fetchone()
    if "password" in b and b["password"]:  # review: removing the built-in login is no "changed"
        sec_mail(c, uid, "password_admin")
    if u["email"] and u["email"] != (nu["email"] or ""):  # live train fix: a first address is no change (no "from -" mail)
        sec_mail(c, uid, "email", u["email"] or "-", nu["email"] or "-", to=u["email"] or "", also=nu["email"])
    if reset:
        sec_mail(c, uid, "2fa_reset")
    if nu["disabled"] and not u["disabled"] and not u["signup"]:
        sec_mail(c, uid, "disabled")
    if reset:
        aa_now("security", f"2fareset:{u['username']}", N_("{0} reset the two-factor authentication of {1}."),
               [g.user["username"], u["username"]], skip=g.user["id"])  # 2.367.4 (#2974): the key without a time keeps the cooldown; the person gets a mail
    if b.get("is_admin") and not u["is_admin"]:
        aa_now("security", f"admin:{u['username']}", N_("{0} is now an admin (set by {1})."), [u["username"], g.user["username"]])
    return jsonify(user_admin_dict(c, c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()))


@app.delete("/api/users/<int:uid>")
def user_delete(uid):
    """Refused while the user owns lists besides the inbox (the safer option: nothing shared with
    others disappears). Deletes their inbox (+ its tasks), habits, focus sessions, time entries, filters, tags and
    settings; tasks they created in other people's lists stay (creator cleared). 2.88.0 (#1980): ?lists=transfer&to=<id>
    hands the lists to one person first, ?lists=delete&confirm=<user name> deletes them along (useradmin.ua8_lists_settle,
    the same transaction); an organisation admin deletes an account of their organisation alone (useradmin.ua8_may_delete)."""
    from ..accounts.useradmin import ua8_lists_settle, ua8_may_delete
    from ..admin.retexport import rx_lists_how
    c = db()
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    by = ua8_may_delete(c, u, uid)  # 2.46.0 (#1592): an instance admin as om_admin_all; 2.88.0: or the organisation's admin
    if uid == me():
        return err(tr("You cannot delete yourself"))
    mode = request.args.get("lists")
    code, answer, n = user_delete_run(c, uid, g.user["username"], along=mode == "delete",
                                      settle=(lambda: ua8_lists_settle(c, u, by, rx_lists_how())) if mode else None)
    if code == "projects":
        return err(trn("The user still owns {0} project. Delete it or disable the user instead.",
                       "The user still owns {0} projects. Delete them or disable the user instead.", n), 409)
    if code:
        return answer
    return jsonify(ok=True, lists=n)


def user_delete_run(c, uid, actor, along=False, settle=None, how=None):
    """#3939: the core of an account deletion, shared by the user management (DELETE /api/users/<id>) and the hosting
    operator's console (admin/operator.py) -- the caller has checked who may delete. Locks the documents going along, counts
    the account's own projects (settle = None: they block; else settle() hands them on / deletes them, useradmin.ua8_lists_settle),
    passes the retention gate (rx_gate; how: its ?retention=, None = the request's), purges, commits, removes the files and
    writes the security log with actor (a user name or "operator") and the account by number.
    -> (None, None, projects) when deleted, ("projects", None, n) when projects block, ("retention" | "lists", 409 answer, n)."""
    from ..accounts.useradmin import ua8_audit
    from ..admin.retexport import rx_alert, rx_gate, rx_subject
    with system_ctx(c):  # #3090: the documents going along locked before the first write, in one order: a recognition run
        # (docs/store.process, its first write is the document's own row) ends first or waits (else both waited: deadlock, 500)
        c.execute("SELECT node_id FROM doc_meta WHERE node_id IN (SELECT id FROM fs_nodes WHERE owner_id=?) "
                  "OR org_id IN (SELECT id FROM orgs WHERE personal_of=?) ORDER BY node_id FOR UPDATE", (uid, uid)).fetchall()
    with system_ctx(c):  # 2.37.0 (#1150): a count over every organisation (lists the admin cannot see still block the deletion)
        n = c.execute("SELECT COUNT(*) FROM lists WHERE owner_id=? AND is_inbox=0", (uid,)).fetchone()[0]
    icons, lfiles, audit = [], [], (None, ())
    if n and settle is None:
        c.rollback()
        return "projects", None, n
    # 2.146.0 D (#2468): records to keep -> the retention export or its waiver first (counted before the lists go; the lists'
    # own refusals answer first)
    keep, retained = rx_gate(c, rx_subject(c, "user", uid), along=along, how=how)
    if n:
        bad, done = settle()  # 2.186.0 A (#2566)
        if bad:
            c.rollback()
            return "lists", bad, n
        icons, lfiles, audit = done[0], done[1], (done[2], done[3])
    if keep:
        c.rollback()
        return "retention", keep, n
    files = user_purge(c, uid, gated=True)  # 2.152.0 A (#2164): records kept by law retire the personal office instead of blocking (2.148.1 #2479)
    bump(c)
    c.commit()
    unlink_files(files)  # 2.152.0 (#2164): with the photo (user_purge)
    if icons or lfiles:
        from ..lists.projects import list_files_drop
        for lid, icon in icons:
            list_icon_drop_file(lid, icon)
        list_files_drop(lfiles)
    ua8_audit(actor, f"#{uid}", *audit)  # 2.88.0 (#1980): the security log; 2.239.0 C (#2866): by number, not by name
    if retained:  # 2.146.0 D (#2468): deleted after the retention export / with its waiver
        rx_alert(retained[0], [actor, f"#{uid}"])
    return None, None, n


def _up_mail_nodes(c, roots):
    """2.148.1 H (#2488): the filed copies (fs_nodes marked with hub_mail_id) of the mails that go with the account (see the
    hub_mails DELETE in user_purge) go, too -- a folder only when everything in it belongs to those mails. Returns the files.
    2.631.0 (#4584): which ones (roots): admin/purgeshare.py ush_mail_doomed, the one rule for the deletion, the hand-on of
    shared folders (they are not sealed again for the heir first) and the delete dialog."""
    from ..files.store import fs_purge
    paths, done = [], set()
    with system_ctx(c):  # the nodes may lie in an organisation's tree
        for nid in roots:
            if nid in done:
                continue
            gone_ids, gone_paths = fs_purge(c, nid)
            done.update(gone_ids)
            paths += gone_paths
    return paths


def user_purge(c, uid, gated=False):
    """Deletes user uid (no own lists besides the inbox left; the caller checked and commits). Returns the files to unlink
    (2.152.0 A: and clean-ups to run after the commit, see serializers.unlink_files). gated: the caller passed rx_gate
    (2.239.0 D, #2866: only user_delete; every other caller keeps the retention locks)."""
    from ..admin.hosting import hosted
    from ..office.olock import OLK_BYPASS
    tok = OLK_BYPASS.set(bool(gated) and hosted())  # 2.152.0 (#2164, review A2): the hosted instance keeps no booked receipts (rx_gate passed)
    made = []
    try:
        return _user_purge(c, uid, made)
    except BaseException:
        unlink_files(made)  # 2.508.0 (#4301): the caller rolls back: the sealed copies of what was to be handed on go
        raise
    finally:
        OLK_BYPASS.reset(tok)


def _user_purge(c, uid, made):
    from ..accounts.orgretain import upg_personal, upg_rest
    from ..admin.backup import bkr_journal
    bkr_journal(c, uid)  # 2.152.0 B (#2172): the journal of deleted accounts (a restore deletes them again)
    for o in rck_admin_orgs(c, uid):  # 2.539.0 (#4373): an admin who saw an organisation's recovery key goes (before the log forgets the id)
        rck_admin_gone(c, o, uid)
    gone = obj_private_refs(c, uid)  # 2.578.0 (#4796): the core history of its private objects goes with them (obj_gone_drop below)
    person_revoked(c, uid, None, "delete")  # 2.558.0 (#4709): its undo steps and revoked rows, its name in the core's history
    # 2.152.0 A (#2164): the personal office is dismantled with its files, or retired when it keeps invoices / receipts by
    # law; agents, organisation calendars, time of organisation projects, direct messages, mentions, logs, the inbox
    files = upg_personal(c, uid)
    files += upg_rest(c, uid)
    from ..admin.purgeshare import ush_hand_on, ush_mail_doomed
    mail = ush_mail_doomed(c, uid)  # 2.631.0 (#4584): the mail copies that go - computed once, for the hand-on and _up_mail_nodes
    files += ush_hand_on(c, uid, made, mail)  # 2.508.0 (#4301): what it shares privately goes to who may write it, before its tree and key go
    from ..team.clients import cl_user_purge
    cl_user_purge(c, uid)  # 2.223.3 B (#2878): its private clients (kept ones with the retired office, anonymised)
    from ..admin.acctexport import umz_forget
    files.append(lambda: umz_forget(uid))  # 2.306.0 C (#2889): after the commit, the account export folder goes at once
    c.execute("DELETE FROM habits WHERE user_id=?", (uid,))
    c.execute("DELETE FROM pomos WHERE user_id=?", (uid,))
    c.execute("DELETE FROM time_entries WHERE user_id=?", (uid,))  # 2.152.0 A: the private ones (organisation time stays, upg_rest)
    c.execute("DELETE FROM filters WHERE user_id=? AND shared=0", (uid,))
    c.execute("UPDATE filters SET user_id=NULL WHERE user_id=?", (uid,))  # 2.577.0 (#3356): a shared view stays with its project
    c.execute("DELETE FROM obj_tags WHERE scope_kind='user' AND scope_id=?", (str(uid),))  # 2.955.0 (#5276): the personal tags (were task_tags)
    c.execute("UPDATE tasks SET assignee_id=NULL WHERE assignee_id=?", (uid,))
    c.execute("UPDATE tasks SET delegate_agent_id=NULL WHERE delegate_agent_id=?", (uid,))  # 2.473.0 (#3357)
    c.execute("DELETE FROM task_watchers WHERE user_id=?", (uid,))
    c.execute("UPDATE tasks SET created_by=NULL WHERE created_by=?", (uid,))
    c.execute("DELETE FROM task_field_values WHERE value=? AND field_id IN (SELECT id FROM list_fields WHERE type='person')", (str(uid),))
    user_forget_conns(c, uid)  # personal connection rows, stored tokens, grants; list bells
    a = c.execute("SELECT webhook_id FROM agents WHERE user_id=?", (uid,)).fetchone()
    if a and a["webhook_id"]:
        c.execute("DELETE FROM webhooks WHERE id=?", (a["webhook_id"],))
    files += _up_mail_nodes(c, mail[0])  # 2.148.1 H (#2488): before the tree is handed on
    from ..files.store import fs_user_purge
    files += fs_user_purge(c, uid)  # 2.48.0 (#1207): the file store (organisation branches go to an admin, the own tree goes)
    c.execute("DELETE FROM doc_fields WHERE ws=?", (f"u{int(uid)}",))  # 2.153.0 (#2179): the own documents' custom fields
    c.execute("DELETE FROM nl_suppress WHERE ws=? AND org_id IS NULL", (f"u{int(uid)}",))  # 2.186.0 C (#2602): the own newsletter's suppression list
    # 2.84.0 A (#1198): the person's private filed mails and their mails nobody else sees (not assigned) go; an organisation's
    # client / project mails stay with the client / project
    c.execute("DELETE FROM hub_mails WHERE owner_id=? AND (org_id IS NULL OR (client_id IS NULL AND list_id IS NULL))", (uid,))
    from ..hub.hubmail import hbm_user_purge
    hbm_user_purge(c, uid)  # 2.84.0 review: its client / project addresses pass to another person who may receive
    from ..contacts.orgbooks import obk_user_purge
    obk_user_purge(c, uid)  # 2.52.0 C (#1438): the organisations' address books it manages get another manager and stay
    # 2.64.0 (#1864): files sealed with the account key that lie elsewhere now are sealed for their space; then the key row
    # goes with the account (foreign key): what is left sealed with it can no longer be read
    from ..collab.teamchan import tcx_user_purge
    files += tcx_user_purge(c, uid)  # 2.113.1 (#2059): its team chat files sealed with its own key
    from ..lists.tplextra import tx_reown, tx_user_files
    with system_ctx(c):  # 2.609.0 (#3373, review F4): an organisation's templates stay with it: the heir (an admin first) owns them
        # 2.905.0 (#5288): the shared core handed them to the heir already (person_revoked above, kind "template"); their file
        # copies still sealed for this account are sealed for their owner now, before this account's key goes
        for (t, h) in c.execute("SELECT DISTINCT t.id, t.owner_id FROM templates t JOIN template_files f ON f.template_id=t.id "
                                "WHERE f.user_id=? AND t.owner_id<>?", (uid, uid)).fetchall():
            files += tx_reown(c, t, h, made)
    from ..admin.orgcrypt_cli import before_user_delete
    if before_user_delete(c, uid)[1]:  # a file that lives on could not be sealed for its new place: keep the key
        raise Denied(409, tr("Some files could not be encrypted again for their new place. Nothing was deleted; see the server log."))
    oc_drop_key(c, -int(uid))
    from ..wiki.wikiatt import wka_user_files
    files += wka_user_files(c, uid)  # 2.99.0 A (#2182): the files of its private pages (the rows go with the account)
    from ..sheets.shkinds import shk_user_files
    files += shk_user_files(c, uid)  # 2.124.0 B (#2110): the files of its private tables' file cells
    files += tx_user_files(c, uid)  # 2.363.3 (#3134): the files of its templates
    from ..wiki.wikie2e import wke_user_purge
    wke_user_purge(c, uid)  # 2.64.3 A (#1817): knowledge spaces with the lock whose key the person held: rotation pending
    av = (c.execute("SELECT avatar FROM users WHERE id=?", (uid,)).fetchone() or [None])[0]
    if av:  # 2.152.0 (#2164): the own photo goes after the commit for every caller (also the re-delete after a restore)
        files.append(lambda: avatar_drop_file(uid, av))
    with system_ctx(c):  # 2.172.0 (#2677): an organisation's feeds stay with the organisation (next admin), not with their adder
        # 2.239.0 D (#2866): without another admin the heir of the account's organisation things takes them (orgretain.upg_heir);
        # private ones go with the account (cascade). 2.905.0 (#5288): section templates are templates of the core (above)
        from ..accounts.orgretain import upg_heir
        for (o,) in c.execute("SELECT DISTINCT org_id FROM rss_feeds WHERE user_id=? AND org_id IS NOT NULL", (uid,)).fetchall():
            h = upg_heir(c, o, uid)
            if h:
                c.execute("UPDATE rss_items SET user_id=? WHERE user_id=? AND feed_id IN (SELECT id FROM rss_feeds WHERE org_id=? AND user_id=?)", (h, uid, o, uid))
                c.execute("UPDATE rss_feeds SET user_id=? WHERE user_id=? AND org_id=?", (h, uid, o))
        # 2.172.1 A (#2689): an organisation's bookmarks stay with it the same way (private ones go with the account)
        for (o,) in c.execute("SELECT DISTINCT org_id FROM bookmarks WHERE user_id=? AND org_id IS NOT NULL", (uid,)).fetchall():
            h = c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role='admin' AND u.disabled=0 AND m.user_id!=? ORDER BY m.user_id LIMIT 1", (o, uid)).fetchone()
            if h:
                c.execute("UPDATE bookmarks SET user_id=? WHERE user_id=? AND org_id=?", (h[0], uid, o))
        from ..sheets.shshare import shs_forget
        shs_forget(c, uid)  # 2.453.0 (#3781)
    # 2.530.0 (#4315, review K2): the kept texts of the person's deleted comments / channel messages go with the account (their
    # rows keep user_id NULL, nobody may bring the person's words back afterwards; the files go with the trash run)
    c.execute("DELETE FROM comment_trash_text WHERE comment_id IN (SELECT id FROM comments WHERE user_id=? AND deleted_at IS NOT NULL)", (uid,))
    c.execute("DELETE FROM tchat_trash_text WHERE message_id IN (SELECT id FROM tchat_msgs WHERE user_id=? AND deleted_at IS NOT NULL)", (uid,))
    c.execute("DELETE FROM users WHERE id=?", (uid,))  # cascades: settings, memberships, sessions
    obj_gone_drop(c, gone)  # 2.578.0 (#4796): the objects went with the account (cascade): their history / undo rows too
    return files


@app.get("/api/me")
def me_get():
    from ..accounts.orgs import workspaces_for
    from ..accounts.supportgrant import sga_is_support
    c = db()
    u = g.user
    return jsonify({**user_public(u), "is_admin": bool(u["is_admin"]), "auth": g.auth_via,
                    "via": "proxy" if g.auth_via == "proxy" else session_via(c), "twofa": twofa_methods(c, u),
                    "has_password": bool(u["password_hash"]), "proxy_login": u["proxy_login"] or "",
                    # 2.138.0 C (#1907): the upload token is shown only when created (POST /api/me/drop-token); here only
                    # whether one is set and since when. 2.86.0 (N3): /drop takes no child account
                    "drop_token_set": bool(not u["kid"] and u["drop_token_hash"]), "drop_token_at": "" if u["kid"] else (u["drop_token_at"] or ""),
                    "ntfy_topic": usettings(c, u["id"])["ntfy_topic"],
                    "support_session": sga_is_support(c),  # 2.538.0 (#4365): as in /api/state
                    "sgen": session_gen(u, workspaces_for(c, u["id"]))})  # 2.238.0 B (#2872): the sign-in mark (as in /api/state)


FIRST_PW_FRESH = 600  # s: 2.86.0 (N5) a first local password needs a sign-in at most this long ago


def h6a_first_password_check(c):
    """2.86.0 (N5): an account without a local password (single sign-on) sets its first one only right after a fresh
    sign-in of this session (a stolen, older session cannot add a second way in). Behind the login proxy there is no
    session to judge: an admin sets the first password there (Settings > Users). An error response or None."""
    from datetime import timedelta
    if g.auth_via != "session":
        return err(tr("An admin can set a first password for this account."), 403)
    tok = request.cookies.get(COOKIE)
    r = c.execute("SELECT created_at FROM sessions WHERE token_hash=?", (_token_hash(tok),)).fetchone() if tok else None
    if not r or r[0] < iso(now_utc() - timedelta(seconds=FIRST_PW_FRESH)):
        return err(tr("For a first password, please sign out and sign in again (at most {0} minutes ago).", FIRST_PW_FRESH // 60), 403)
    return None


@app.patch("/api/me")
def me_update():
    """Own display name and password (the current password is required when one is set)."""
    b = body()
    c = db()
    u = g.user
    if "display_name" in b:
        c.execute("UPDATE users SET display_name=? WHERE id=?", ((b["display_name"] or "").strip()[:60] or u["username"], u["id"]))
    if "color" in b:  # 2.47.1 (#1721): the own fixed colour (only colours of the palette)
        if (u["kind"] or "user") == "agent":  # an agent's colour is set by its admin / owner (PATCH /api/agents/<aid>/color)
            return err(tr("Not allowed"), 403)
        if not ac_valid(b["color"]):
            return err(tr("Invalid data"))
        c.execute("UPDATE users SET color=? WHERE id=?", (b["color"].lower(), u["id"]))
    if "password" in b:
        keys = _rate_keys(u["username"])
        e = login_wait(keys, u["username"])  # 2.282.0 (#3111): other accounts' failures at this address do not stop it
        if e:
            return e
        if u["password_hash"] and not check_password_hash(u["password_hash"], b.get("current_password") or ""):
            _rate_fail(keys)
            return err(tr("Current password is wrong"), 403)
        if not u["password_hash"]:
            e = h6a_first_password_check(c)
            if e:
                return e
        pw = b["password"] or ""
        if len(pw) < MIN_PASSWORD:
            return err(tr("Password: at least {0} characters", MIN_PASSWORD))
        if not u["password_hash"]:
            from ..notify.alerts import aa_now
            aa_now("security", f"pw-first:{u['username']}",
                   N_("{0} set a first local password (the account signed in by single sign-on before)."), [u["username"]])
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw), u["id"]))
        tok = request.cookies.get(COOKIE)  # other sessions end, this one stays
        ses_end(c, u["id"], keep=_token_hash(tok) if tok else None)  # 2.190.0 A (#1991): with their push subscriptions
        from ..docs.scankeys import sk_revoke_all  # 2.237.0 C (#2865): the scan inbox keys go (a new setup code is made)
        sk_revoke_all(c, u["id"])
        # 2.539.0 B (#4375): the dialog's tick "end all app passwords and API tokens" (set by default); without the field
        # (API) they end too - the safe default. An agent account's own tokens stay, as with the reset.
        if b.get("revoke_tokens", True) is not False:
            c.execute("DELETE FROM app_passwords WHERE user_id=?", (u["id"],))
            c.execute("DELETE FROM api_tokens WHERE user_id IN (SELECT id FROM users WHERE id=? AND COALESCE(kind, 'user')<>'agent')", (u["id"],))
    bump(c)
    c.commit()
    if "password" in b:  # 2.266.0 (#2963)
        from .secmail import sec_mail
        sec_mail(c, u["id"], "password")
    return jsonify(ok=True)


@app.post("/api/me/drop-token")
def me_drop_token():
    if g.user["kid"]:  # 2.86.0 (N3 review): a child account has no upload token (also if KID_WRITE ever widens)
        return err(tr("Not possible with a child account"), 403)
    c = db()
    tok = tkh_set_drop(c, me())  # 2.138.0 C (#1907): only the hash is stored; this answer is the one time the token is shown
    c.commit()
    return jsonify(drop_token=tok, drop_token_at=c.execute("SELECT drop_token_at FROM users WHERE id=?", (me(),)).fetchone()[0])


def httpshortcuts_zip(url, token, lg):
    """Import file for the Android app HTTP Shortcuts (format compatibilityVersion 90): two shortcuts, one for files
    (several at once, form field "file") and one for text / links (form field "text", filled from the share dialog by a
    global variable with "receive value from share dialog"), both POST <url> with the user's upload token."""
    icon = f"custom-icon_{secrets.randbelow(9 * 10 ** 10) + 10 ** 10}_circle.png"
    var_id = str(uuid.uuid4())
    common = {"method": "POST", "url": url, "iconName": icon, "bodyContent": "", "requestBodyType": "form_data",
              "headers": [{"key": "Authorization", "value": "Bearer " + token}],
              "responseHandling": {"actions": ["rerun", "share", "save"]}}
    data = {
        "categories": [{"id": str(uuid.uuid4()), "name": "Kalmido", "shortcuts": [
            {**common, "id": str(uuid.uuid4()), "name": "Kalmido",
             "description": tr("Share files to your Kalmido basket", lg=lg),
             "parameters": [{"key": "file", "type": "file", "fileUploadOptions": {"fileUploadType": "file_picker_multi"}}]},
            {**common, "id": str(uuid.uuid4()), "name": tr("Kalmido text", lg=lg),
             "description": tr("Share text or links to your Kalmido basket", lg=lg), "excludeFromFileSharing": True,
             "parameters": [{"key": "text", "type": "string", "value": "{{" + var_id + "}}"}]},
        ]}],
        "variables": [{"id": var_id, "key": "kalmido_shared_text", "type": "constant", "value": "", "isShareText": True,
                       "isMultiline": True}],
        "compatibilityVersion": 90,
        "version": 91,
        "createdAt": now_utc().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("shortcuts.json", json.dumps(data, ensure_ascii=False, indent=1))
        z.write(os.path.join(app.static_folder, "icon-512.png"), icon)
    return out.getvalue()


def tkh_own_page():
    """2.138.0 C (#1907): a GET with an effect only from this app's own pages: Sec-Fetch-Site none / same-origin; a
    browser without that header must name this host in Origin or Referer (the app sends Referrer-Policy same-origin)."""
    sfs = request.headers.get("Sec-Fetch-Site", "")
    if sfs:
        return sfs in ("none", "same-origin")
    from urllib.parse import urlsplit
    hosts = {request.host.lower(), (urlsplit(PUBLIC_URL).netloc or "").lower()} - {""}
    for h in ("Origin", "Referer"):
        v = (request.headers.get(h) or "").strip()
        if v and v != "null":
            return (urlsplit(v).netloc or "").lower() in hosts
    return False


@app.get("/api/me/share/httpshortcuts.zip")
def me_share_httpshortcuts():
    """1.9.0: my ready-made HTTP Shortcuts import (address + my upload token inside: treat it like a password).
    2.138.0 C (#1907): the token is stored only as a hash, so every download carries a NEW token (the old one and the
    shortcuts made with it stop working; the settings say so before). Only from this app's own pages (not cross-site)."""
    if g.user["kid"]:
        return err(tr("Not possible with a child account"), 403)
    if not tkh_own_page():
        if not any(request.headers.get(h) for h in ("Sec-Fetch-Site", "Origin", "Referer")):
            # 2.144.5 A (#2387, review F8): an older browser that names no origin at all stays refused, but is told why
            return err(tr("This browser does not say which page the download comes from, so it is refused for safety. Use a current browser or allow the referrer for this site."), 403)
        return err(tr("Not allowed"), 403)
    c = db()
    tok = tkh_set_drop(c, me())
    c.commit()
    data = httpshortcuts_zip(PUBLIC_URL.rstrip("/") + "/drop", tok, lang(c, me()))
    r = Response(data, mimetype="application/zip")
    r.headers["Content-Disposition"] = 'attachment; filename="kalmido-http-shortcuts.zip"'
    r.headers["Cache-Control"] = "no-store"
    return r


def _avatar_set(c, uid, value):
    old = c.execute("SELECT avatar FROM users WHERE id=?", (uid,)).fetchone()
    c.execute("UPDATE users SET avatar=? WHERE id=?", (value, uid))
    bump(c)
    c.commit()
    if old and old[0] != value:
        avatar_drop_file(uid, old[0])


@app.put("/api/me/avatar")
def me_avatar_preset():
    """{preset: "coffee" | ... | null}: a preset picture, or none (initials)."""
    p = body().get("preset")
    if p is not None and p not in AVATAR_PRESETS:
        return err(tr("Invalid value: {0}", "preset"))
    c = db()
    _avatar_set(c, me(), f"p:{p}" if p else None)
    return jsonify(avatar=avatar_url(c.execute("SELECT id, avatar, kind FROM users WHERE id=?", (me(),)).fetchone()))


@app.post("/api/me/avatar")
def me_avatar_upload():
    """multipart "file": an own photo (JPEG / PNG / WebP, up to AVATAR_MAX_MB MB), stored as a square JPEG."""
    return avatar_upload(me())


def avatar_upload(uid):
    """The uploaded picture (multipart "file") becomes uid's photo (2.1.2: also an agent's, set by an admin)."""
    f = request.files.get("file")
    if not f:
        return err(tr("No file"))
    raw = f.read(AVATAR_MAX_MB * 1024 * 1024 + 1)
    if len(raw) > AVATAR_MAX_MB * 1024 * 1024:
        return err(tr("The picture is too large (at most {0} MB)", AVATAR_MAX_MB), 413)
    try:
        jpg = avatar_process(raw)
    except BadInput as e:
        return err(str(e))
    tok = secrets.token_urlsafe(12)
    os.makedirs(AVATAR_DIR, exist_ok=True)
    tmp = avatar_path(uid, tok) + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(jpg)
    os.replace(tmp, avatar_path(uid, tok))
    c = db()
    _avatar_set(c, uid, "u:" + tok)
    return jsonify(avatar=avatar_url({"id": uid, "avatar": "u:" + tok}))


@app.delete("/api/me/avatar")
def me_avatar_delete():
    c = db()
    _avatar_set(c, me(), None)
    return jsonify(avatar="")


@app.get("/api/avatar/<int:uid>/<tok>.jpg")
def avatar_get(uid, tok):
    """A user's own photo: for the user, admins and people sharing a list with them."""
    c = db()
    u = c.execute("SELECT id, avatar FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["avatar"] != "u:" + tok or not re.fullmatch(r"[A-Za-z0-9_-]{8,40}", tok):
        raise Denied(404)
    admin_ok = bool(g.user["is_admin"])  # 2.46.0 (#1592): the user management shows every account, with its photo
    if admin_ok and uid != me():  # 2.539.0 (#4374): hosted, not the photo of a client's account (the list shows none)
        from ..accounts.orgs import op_foreign_account
        admin_ok = not op_foreign_account(c, uid, note=False)
    if uid != me() and not admin_ok and not c.execute(
            f"""SELECT 1 FROM lists WHERE id IN {vis_sql()} AND id IN {joined_lists_sql()}
                LIMIT 1""", (me(), me(), uid, uid)).fetchone():
        raise Denied(404)
    p = avatar_path(uid, tok)
    if not os.path.isfile(p):
        raise Denied(404)
    r = send_file(p, mimetype="image/jpeg", max_age=31536000)
    r.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return r


def _list_icon_set(c, lid, value):
    old = c.execute("SELECT icon FROM lists WHERE id=?", (lid,)).fetchone()
    c.execute("UPDATE lists SET icon=?, icon_size=?, icon_by=? WHERE id=?", (value, *list_icon_cols(lid, value, me()), lid))  # 2.498.0 (#3884)
    bump(c)
    c.commit()
    if old and old[0] != value:
        list_icon_drop_file(lid, old[0])
    return jsonify(icon=list_icon_url({"id": lid, "icon": value}))


@app.put("/api/lists/<int:lid>/icon")
def list_icon_preset(lid):
    """{preset: "kalmido" | "coffee" | ... | null} -- the owner (or a list admin) picks a preset icon for the list, or none."""
    c = db()
    need_list(c, lid, manage=True)  # 2.40.0 (#1431): owner and list admins
    p = body().get("preset")
    if p is not None and p not in LIST_ICON_PRESETS:
        return err(tr("Invalid value: {0}", "preset"))
    return _list_icon_set(c, lid, f"p:{p}" if p else None)


@app.post("/api/lists/<int:lid>/icon")
def list_icon_upload(lid):
    """multipart "file": an own picture for the list (JPEG / PNG / WebP, up to AVATAR_MAX_MB MB), stored as a square PNG."""
    c = db()
    need_list(c, lid, manage=True)  # 2.40.0 (#1431): owner and list admins
    v = list_icon_store(lid)
    return v if not isinstance(v, str) else _list_icon_set(c, lid, v)


def list_icon_store(lid):
    """The uploaded picture (multipart "file") of list lid stored as its new icon file -> the icon value "u:<token>", or an
    error response. 2.56.0 (#1795): shared with an organisation admin's icon change (orglists.ole_icon_upload)."""
    f = request.files.get("file")
    if not f:
        return err(tr("No file"))
    raw = f.read(AVATAR_MAX_MB * 1024 * 1024 + 1)
    if len(raw) > AVATAR_MAX_MB * 1024 * 1024:
        return err(tr("The picture is too large (at most {0} MB)", AVATAR_MAX_MB), 413)
    try:
        png = list_icon_process(raw)
    except BadInput as e:
        return err(str(e))
    tok = secrets.token_urlsafe(12)
    os.makedirs(LIST_ICON_DIR, exist_ok=True)
    c = db()  # 2.58.0 (#1805): an organisation list's picture is sealed with its key at rest (private lists plain, as attachments)
    list_pic_guard(c, lid, "icon", me(), len(png))  # 2.498.0 (#3884)
    oc_write_file(c, oc_list_org(c, lid), list_icon_path(lid, tok), png)
    return "u:" + tok


@app.delete("/api/lists/<int:lid>/icon")
def list_icon_delete(lid):
    c = db()
    need_list(c, lid, manage=True)  # 2.40.0 (#1431): owner and list admins
    return _list_icon_set(c, lid, None)


@app.get("/api/list-icon/<int:lid>/<tok>.png")
def list_icon_get(lid, tok):
    """A list's own icon: for everybody who sees the list."""
    c = db()
    r = c.execute("SELECT id, icon FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or r["icon"] != "u:" + tok or not re.fullmatch(r"[A-Za-z0-9_-]{8,40}", tok) or not list_role(c, lid):
        from ..accounts.orglists import ole_org_admin
        if not r or r["icon"] != "u:" + tok or not ole_org_admin(c, lid):  # 2.56.0 (#1795): and the admins of its organisation
            raise Denied(404)
    p = list_icon_path(lid, tok)
    if not os.path.isfile(p):
        raise Denied(404)
    rs = oc_send_file(c, p, mimetype="image/png", max_age=31536000)  # 2.58.0 (#1805): sealed -> decrypted, older plain ones as before
    rs.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return rs
