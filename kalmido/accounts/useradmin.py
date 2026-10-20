"""2.88.0 (#1980): the admin user management for hundreds of accounts -- one page at a time (search, filter, total), the
account dicts of a page read in a fixed number of queries, several accounts at once (disable / enable / add to an
organisation) and deleting an account that still owns lists: hand them over to one person or delete them with it."""
import time

from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import body, db, err, now_utc, parse_iso, USER_DEFAULTS
from ..core.pg import like_escape, system_ctx
from ..core.access import Denied, list_role
from ..accounts.session import me, user_public


UA8_FILTERS = ("people", "active", "disabled", "admin", "invited", "pending", "agents", "all")
UA8_MAX_PAGE = 200
UA8_MAX_BULK = 200
UA8_PRIVATE = N_("The account still has things in its private space (lists, basket, calendars, files ...): only a server admin can delete it. You can remove it from your organisation.")


def ua8_where(q, flt):
    """SQL condition + args of the user management's search (name, user name, e-mail) and filter."""
    cond, args = [], []
    if q:
        p = "%" + like_escape(q.strip()) + "%"
        cond.append("(username ILIKE ? ESCAPE '\\' OR COALESCE(display_name,'') ILIKE ? ESCAPE '\\' "
                    "OR COALESCE(email,'') ILIKE ? ESCAPE '\\')")
        args += [p, p, p]
    if flt != "agents" and flt != "all":
        cond.append("COALESCE(kind,'user')!='agent'")
    cond.append({"active": "disabled=0 AND COALESCE(signup,'')!='pending'", "disabled": "disabled=1", "admin": "is_admin=1",
                 "invited": "id IN (SELECT user_id FROM user_invites WHERE used_at IS NULL)", "pending": "signup='pending'",
                 "agents": "kind='agent'"}.get(flt, "1=1"))
    return " AND ".join(cond), args


def ua8_admin_dicts(c, rows):
    """user_admin_dict (accounts/users.py) for many accounts with a fixed number of queries (not a few per account)."""
    ids = [u["id"] for u in rows]
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    topic = {r[0]: r[1] for r in c.execute(f"SELECT user_id, value FROM user_settings WHERE key='ntfy_topic' AND user_id IN ({q})", ids)}
    passkey = {r[0] for r in c.execute(f"SELECT DISTINCT user_id FROM webauthn_creds WHERE user_id IN ({q})", ids)}
    rcodes = {r[0] for r in c.execute(f"SELECT DISTINCT user_id FROM recovery_codes WHERE used_at IS NULL AND user_id IN ({q})", ids)}
    parents = {}
    for k, p in c.execute(f"""SELECT p.kid_id, p.parent_id FROM kid_parents p JOIN users u ON u.id=p.parent_id
                               WHERE p.kid_id IN ({q}) AND u.disabled=0 ORDER BY p.parent_id""", ids):
        parents.setdefault(k, []).append(p)
    nw = now_utc()
    invite = {r[0]: ("invited" if parse_iso(r[1]) > nw else "expired")
              for r in c.execute(f"SELECT user_id, expires_at FROM user_invites WHERE used_at IS NULL AND user_id IN ({q})", ids)}
    orgs, ag_org, nlists = {}, {}, {}
    with system_ctx(c):  # the same reads as users._admin_struct: ids and a count (structure, no content)
        for uid, oid in c.execute(f"SELECT user_id, org_id FROM org_members WHERE user_id IN ({q}) ORDER BY org_id", ids):
            orgs.setdefault(uid, []).append(oid)
        ag_org = {r[0]: r[1] for r in c.execute(f"SELECT user_id, org_id FROM agents WHERE user_id IN ({q})", ids)}
        nlists = {r[0]: r[1] for r in c.execute(f"SELECT owner_id, COUNT(*) FROM lists WHERE owner_id IN ({q}) AND is_inbox=0 GROUP BY owner_id", ids)}
    used = {}
    for sql in (f"SELECT user_id, COALESCE(SUM(size),0) FROM attachments WHERE user_id IN ({q}) GROUP BY user_id",
                f"SELECT user_id, COALESCE(SUM(size),0) FROM list_files WHERE user_id IN ({q}) GROUP BY user_id",
                f"""SELECT m.user_id, COALESCE(SUM(f.size),0) FROM chat_files f JOIN agent_chat m ON m.id=f.message_id
                    WHERE m.sender='user' AND m.user_id IN ({q}) GROUP BY m.user_id""",
                f"SELECT created_by, COALESCE(SUM(size),0) FROM fs_versions WHERE created_by IN ({q}) GROUP BY created_by",
                f"SELECT user_id, COALESCE(SUM(size),0) FROM budget_files WHERE user_id IN ({q}) GROUP BY user_id",
                f"SELECT created_by, COALESCE(SUM(size),0) FROM wiki_files WHERE created_by IN ({q}) GROUP BY created_by",  # 2.99.0 A (#2182)
                f"SELECT created_by, COALESCE(SUM(size),0) FROM sheet_files WHERE created_by IN ({q}) GROUP BY created_by",  # 2.124.0 B (#2110)
                f"SELECT user_id, COALESCE(SUM(size),0) FROM tchat_files WHERE user_id IN ({q}) GROUP BY user_id"):  # 2.113.1 (#2059)
        for uid, n in c.execute(sql, ids):  # admin/hosting._user_bytes, per account
            used[uid] = used.get(uid, 0) + int(n or 0)
    out = []
    for u in rows:
        uid = u["id"]
        tf = []  # login.twofa_methods
        if u["password_hash"]:
            if u["totp_secret"]:
                tf.append("totp")
            if uid in passkey:
                tf.append("passkey")
            if tf and uid in rcodes:
                tf.append("recovery")
        st = {"orgs": orgs.get(uid, [])}
        if (u["kind"] or "user") == "agent":
            st["org_id"] = ag_org.get(uid)
        st["lists"] = nlists.get(uid, 0)
        out.append({**user_public(u), "kind": u["kind"] or "user", "is_admin": bool(u["is_admin"]), "disabled": bool(u["disabled"]),
                    "has_password": bool(u["password_hash"]), "proxy_login": u["proxy_login"] or "",
                    "created_at": u["created_at"], "ntfy_topic": topic.get(uid, USER_DEFAULTS.get("ntfy_topic", "")),
                    "email": u["email"] or "", "twofa": tf, "oidc_linked": bool(u["oidc_subject"]),
                    "parents": parents.get(uid, []) if u["kid"] else [], "invite": invite.get(uid),
                    "signup": u["signup"] or "", "kid": bool(u["kid"]), **st,
                    "storage": {"used": used.get(uid, 0), "quota_mb": u["storage_quota_mb"]}})
    return out


def ua8_users_page(c):
    """GET /api/users?all=1&limit=50[&offset=&q=&filter=]: one page of the instance admin's user management + the total
    of the search / filter (users_list without limit stays the whole list)."""
    try:
        limit = max(1, min(UA8_MAX_PAGE, int(request.args.get("limit") or 50)))
        offset = max(0, int(request.args.get("offset") or 0))
    except ValueError:
        return err(tr("Invalid value: {0}", "limit"))
    flt = request.args.get("filter") or "people"
    if flt not in UA8_FILTERS:
        return err(tr("Invalid value: {0}", "filter"))
    where, args = ua8_where((request.args.get("q") or "")[:100], flt)
    total = c.execute(f"SELECT COUNT(*) FROM users WHERE {where}", args).fetchone()[0]
    rows = c.execute(f"SELECT * FROM users WHERE {where} ORDER BY lower(COALESCE(display_name, username)), id LIMIT ? OFFSET ?",
                     args + [limit, offset]).fetchall()
    agents = c.execute("SELECT COUNT(*) FROM users WHERE kind='agent'").fetchone()[0]
    from ..integrations.mail import MAIL_OUT_ON
    return jsonify(users=ua8_admin_dicts(c, rows), total=total, offset=offset, limit=limit, filter=flt, agents=agents,
                   mail_out=MAIL_OUT_ON, others=0)


# ---------------------------------------------------------------- deleting an account that owns lists

def ua8_admin_orgs(c):
    from ..accounts.orgs import org_role, user_orgs
    return [o for o in user_orgs(c, me()) if org_role(c, me(), o) == "admin"]


def ua8_may_delete(c, u, uid):
    """Who deletes account uid: 'instance' (an instance admin, as before: users.om_admin_all) or the id of the organisation
    whose admin deletes it -- only an account that belongs to that one organisation alone and is no instance admin (the
    others: only "Remove from the organisation"). Raises Denied (404 = an account the caller must not know)."""
    from ..agents.core import is_agent
    from ..accounts.users import om_admin_all
    if g.user["is_admin"]:
        if not u or not om_admin_all(c, uid):
            raise Denied(404, tr("unknown user"))
        return "instance"
    if is_agent(g.user):
        raise Denied(403)
    mine = ua8_admin_orgs(c)
    if not mine:
        raise Denied(403)
    from ..accounts.orgs import user_orgs
    theirs = user_orgs(c, uid) if u else []
    shared = [o for o in theirs if o in mine]
    if not shared:
        raise Denied(404, tr("unknown user"))
    if len(theirs) != 1 or u["is_admin"] or is_agent(u):
        raise Denied(403, tr("Only a server admin can delete this account (it belongs to another organisation too or is a server admin). You can remove it from your organisation."))
    if ua8_private_left(c, uid):  # review N1: deleting the account would delete its private space too
        raise Denied(403, tr(UA8_PRIVATE))
    return shared[0]


def ua8_owned(c, uid):
    with system_ctx(c):  # every list the account owns, in every organisation (the same count that blocks the deletion)
        return c.execute("SELECT * FROM lists WHERE owner_id=? AND is_inbox=0 ORDER BY lower(name), id", (uid,)).fetchall()


def ua8_candidates(c, lists, uid):
    """The people every one of the lists may go to (lists.ownership.owner_candidates per list: active people, never
    agents, the caller may see them, an organisation's list stays in its organisation) -> [{id, name}]. Review M1: cut with
    the caller's own visibility too (owner_candidates names every list member, under system_ctx also those of another
    organisation)."""
    from ..lists.ownership import owner_candidates
    from ..accounts.orgs import visible_people
    common, names = None, {}
    with system_ctx(c):  # the lists of organisations the instance admin is not in (the rule inside stays the caller's visibility)
        for lr in lists:
            cs = owner_candidates(c, lr["id"], uid)
            names.update({x["id"]: x["name"] for x in cs})
            ids = {x["id"] for x in cs}
            common = ids if common is None else common & ids
    vis = visible_people(c, me())
    if vis is not None and common:
        common &= vis
    ids = list(common or ())
    # 2.92.0 D (#2008): invited accounts that never logged in (open invitation) go to the back
    inv = {r[0] for r in c.execute(f"SELECT user_id FROM user_invites WHERE kind='invite' AND used_at IS NULL AND user_id IN ({','.join('?' * len(ids))})", ids)} if ids else set()
    return [{"id": i, "name": names[i], "invited": i in inv} for i in sorted(ids, key=lambda i: (i in inv, names[i].lower()))]


def ua8_list_info(c, lists, by):
    """What the delete dialog shows of each list: the name only where the caller may see the list (a member / its owner, or
    an admin of its organisation) -- else "private list" / the organisation; the people it is shared with (only people the
    caller may see by name, the rest as a number); whether it has the lock (#1817) and whether nobody else holds its key
    (review M2: then nobody can give the new owner the key); its project receipts (review M3: such a list is only handed
    over); the organisation's name only for an organisation the caller is in (review N2)."""
    from ..accounts.orgs import org_role, visible_people
    from ..collab.liste2e import le2e_mode
    vis = visible_people(c, me())
    out = []
    for lr in lists:
        lid, oid = lr["id"], lr["org_id"]
        with system_ctx(c):  # member ids and names of the organisation (structure); named below only when visible
            mem = c.execute("""SELECT u.id, COALESCE(u.display_name, u.username) FROM list_members m JOIN users u ON u.id=m.user_id
                               WHERE m.list_id=? AND m.user_id!=? ORDER BY u.id""", (lid, lr["owner_id"])).fetchall()
            foreign = ua8_foreign(c, lr)
            oname = (c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone() or [None])[0] if oid and not foreign else None
            locked = bool(le2e_mode(c, lid))
            key_alone = locked and not ua8_key_holders(c, lid, lr["owner_id"])
            receipts = c.execute("SELECT COUNT(*) FROM budget_files WHERE list_id=?", (lid,)).fetchone()[0]
        seen = bool(list_role(c, lid)) or (oid and org_role(c, me(), oid) == "admin")
        named = [n for i, n in mem if vis is None or i in vis]
        out.append({"id": lid, "name": lr["name"] if seen else None, "org_id": oid, "org": oname, "shared": len(mem),
                    "members": named[:8] if seen else [], "locked": locked, "key_alone": key_alone, "receipts": receipts,
                    "foreign": foreign})
    return out


def ua8_key_holders(c, lid, uid):
    """Review M2: how many active members of the locked list lid besides uid hold its key of the current generation (one of
    them can give the new owner the key; liste2e: list_keys per generation, lists.e2e_gen). The caller runs as system."""
    return c.execute("""SELECT COUNT(*) FROM list_keys k JOIN lists l ON l.id=k.list_id AND k.gen=l.e2e_gen
                        JOIN users u ON u.id=k.user_id JOIN list_members m ON m.list_id=k.list_id AND m.user_id=k.user_id
                        WHERE k.list_id=? AND k.user_id!=? AND u.disabled=0""", (lid, uid)).fetchone()[0]


def ua8_private_left(c, uid):
    """Review N1: does account uid still have anything in its private space that user_purge would delete -- private lists, its
    basket, private calendars / address books with entries, private files, knowledge pages, filed mails, habits, time of
    private work? An organisation admin deletes only an account whose private space is empty (privat bleibt privat)."""
    with system_ctx(c):  # existence only, nothing read; the private rows of a person the organisation admin must not see
        return any(c.execute(sql, (uid,)).fetchone() for sql in (
            "SELECT 1 FROM lists WHERE owner_id=? AND is_inbox=0 AND org_id IS NULL LIMIT 1",
            "SELECT 1 FROM tasks t JOIN lists l ON l.id=t.list_id WHERE l.owner_id=? AND l.is_inbox=1 LIMIT 1",
            "SELECT 1 FROM ev_cals k JOIN events e ON e.cal_id=k.id WHERE k.owner_id=? AND k.org_id IS NULL LIMIT 1",
            "SELECT 1 FROM books b JOIN contacts x ON x.book_id=b.id WHERE b.owner_id=? AND b.org_id IS NULL LIMIT 1",
            "SELECT 1 FROM fs_nodes WHERE owner_id=? AND org_id IS NULL AND kind!='folder' LIMIT 1",
            "SELECT 1 FROM wiki_pages WHERE owner_id=? AND org_id IS NULL LIMIT 1",
            "SELECT 1 FROM sheets WHERE owner_id=? AND org_id IS NULL LIMIT 1",  # 2.89.0 (#1916): private tables
            "SELECT 1 FROM hub_mails WHERE owner_id=? AND org_id IS NULL LIMIT 1",
            "SELECT 1 FROM habits WHERE user_id=? LIMIT 1",
            "SELECT 1 FROM time_entries t LEFT JOIN lists l ON l.id=t.list_id WHERE t.user_id=? AND l.org_id IS NULL LIMIT 1"))


@app.get("/api/users/<int:uid>/delete-info")
def ua8_delete_info(uid):
    """2.88.0 (#1980): for the delete dialog -- the account's lists (see ua8_list_info), the people all of them may go to,
    and who deletes (by: instance | org). An organisation admin who may not delete this account gets can_delete false +
    the reason and the organisation's members its lists can go to on "Remove from the organisation"."""
    c = db()
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    base = {"id": uid}
    try:
        by = ua8_may_delete(c, u, uid)
    except Denied as e:
        if e.code != 403 or g.user["is_admin"] or not u:
            raise
        oid = next((o for o in ua8_org_of(c, uid)), None)
        if not oid:
            raise
        return jsonify(**base, can_delete=False, reason=e.text(), org_id=oid, heirs=ua8_heirs(c, oid, uid), lists=[], candidates=[])
    lists = ua8_owned(c, uid)
    return jsonify(**base, can_delete=True, by="instance" if by == "instance" else "org", org_id=None if by == "instance" else by,
                   username=u["username"], lists=ua8_list_info(c, lists, by), candidates=ua8_candidates(c, lists, uid) if lists else [])


def ua8_foreign(c, lr):
    """A list of an organisation the caller does not belong to: it may change hands inside that organisation, but only the
    organisation's own people delete it (the instance admin never deletes another organisation's lists along)."""
    from ..accounts.orgs import user_orgs
    return bool(lr["org_id"]) and lr["org_id"] not in user_orgs(c, me())


def ua8_org_of(c, uid):
    from ..accounts.orgs import user_orgs
    mine = ua8_admin_orgs(c)
    return [o for o in user_orgs(c, uid) if o in mine]


def ua8_heirs(c, oid, uid):
    """Active people of organisation oid (never agents, not uid): who may get the account's lists of the organisation."""
    with system_ctx(c):  # membership structure of the caller's own organisation
        rows = c.execute("""SELECT u.id, COALESCE(u.display_name, u.username) FROM org_members m JOIN users u ON u.id=m.user_id
                            WHERE m.org_id=? AND u.disabled=0 AND COALESCE(u.kind,'user')!='agent' AND u.id!=?""", (oid, uid)).fetchall()
    return sorted([{"id": r[0], "name": r[1]} for r in rows], key=lambda x: x["name"].lower())


def ua8_lists_settle(c, u, by):
    """DELETE /api/users/<id>?lists=transfer&to=<id> | ?lists=delete&confirm=<user name>: the account's lists go to one person
    (every list must be allowed to go there, else nothing happens: 409 with the lists) or are deleted with it (as the owner's
    delete: lists.list_purge). The caller commits and deletes the account in the same transaction.
    -> (None, (icons [(list id, icon)], files, audit text, its args after "who" and "whom")) or (an error response, None)."""
    from ..lists.lists import list_purge
    from ..lists.ownership import owner_transfer
    from ..accounts.orgs import need_visible
    from ..agents.core import is_agent
    from ..core.access import my_inbox
    uid = u["id"]
    lists = ua8_owned(c, uid)
    mode = request.args.get("lists") or ""
    if by != "instance" and any(not lr["org_id"] for lr in lists):  # private stays private (ua8_may_delete refused already)
        raise Denied(403, tr(UA8_PRIVATE))
    if mode == "transfer":
        try:
            to = int(request.args.get("to") or 0)
        except ValueError:
            to = 0
        if not to:
            return err(tr("Invalid value: {0}", "to")), None
        need_visible(c, to)  # a person the caller may not see: as unknown
        t = c.execute("SELECT * FROM users WHERE id=?", (to,)).fetchone()
        if not t:
            return err(tr("unknown user"), 404), None
        if to == uid or t["disabled"] or is_agent(t):
            return err(tr("The lists can only go to another active person (not an agent)")), None
        ok = {x["id"] for x in ua8_candidates(c, lists, uid)}
        if to not in ok:
            from ..lists.ownership import owner_candidates
            with system_ctx(c):  # which of the account's lists the target cannot take (only list ids leave this route)
                bad =[lr for lr in lists if to not in {x["id"] for x in owner_candidates(c, lr["id"], uid)}]
            return (jsonify(error=tr("{0} cannot take over every list (an organisation’s list stays in its organisation). Nothing was changed.",
                                     t["display_name"] or t["username"]), lists=[x["id"] for x in bad]), 409), None
        with system_ctx(c):  # lists in organisations the instance admin is not in (checked above: the target fits every list)
            for lr in lists:
                owner_transfer(c, lr, to, force=True)  # #1817: a list with the lock too (the new owner waits for its key)
                c.execute("DELETE FROM list_members WHERE list_id=? AND user_id=?", (lr["id"], uid))
        return None, ([], [], N_("{0} deleted the account {1}; {2} lists went to {3}."), [len(lists), t["username"]])
    if mode == "delete":
        if (request.args.get("confirm") or "") != u["username"]:
            return err(tr("Type the user name to confirm")), None
        bad = [lr["id"] for lr in lists if ua8_foreign(c, lr)]
        if bad:
            return (jsonify(error=tr("Lists of an organisation you do not belong to cannot be deleted along: hand them over instead."),
                            lists=bad), 409), None
        with system_ctx(c):  # review M3 (#1969: receipts are kept 10 years): a list with project receipts is only handed over
            bad = [lr["id"] for lr in lists if c.execute("SELECT 1 FROM budget_files WHERE list_id=? LIMIT 1", (lr["id"],)).fetchone()]
        if bad:
            return (jsonify(error=tr("Lists with receipts cannot be deleted along (receipts are kept): hand them over instead."),
                            lists=bad), 409), None
        icons, files = [], []
        inbox = my_inbox(c, uid)
        with system_ctx(c):  # the account's lists in every organisation go with it (invoices / documents do not hang on lists)
            for lr in lists:
                icon, lf = list_purge(c, lr["id"], inbox)
                icons.append((lr["id"], icon))
                files += lf
        return None, (icons, files, N_("{0} deleted the account {1} with its {2} lists."), [len(lists)])
    return err(tr("Invalid value: {0}", "lists")), None


def ua8_audit(by_user, gone, text=None, extra=()):
    """The security log / alert of a deleted account (who, whom; with lists: how many and to whom / deleted along)."""
    from ..notify.alerts import aa_now
    aa_now("security", f"userdel:{gone}:{int(time.time())}", text or N_("{0} deleted the account {1}."), [by_user, gone, *extra])


@app.post("/api/users/bulk")
def ua8_bulk():
    """2.88.0 (#1980): {ids: [..], action: disable | enable | org_add, org_id?} -- the instance admin changes several
    accounts at once; each one through the single route (PATCH /api/users/<id>: its checks per account, its own commit).
    -> {ok: [ids], failed: [{id, error}]}."""
    from ..accounts.users import need_admin, user_update
    need_admin()
    b = body()
    ids = b.get("ids")
    act = b.get("action")
    if not isinstance(ids, list) or not ids or len(ids) > UA8_MAX_BULK or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        return err(tr("Invalid value: {0}", "ids"))
    if act not in ("disable", "enable", "org_add"):
        return err(tr("Invalid value: {0}", "action"))
    c = db()
    oid = b.get("org_id")
    if act == "org_add":
        if not isinstance(oid, int) or isinstance(oid, bool):
            return err(tr("Invalid value: {0}", "org_id"))
        with system_ctx(c):  # does the organisation exist (structure)
            if not c.execute("SELECT 1 FROM orgs WHERE id=? AND personal_of IS NULL", (oid,)).fetchone():
                return err(tr("unknown"), 404)
    ok, failed = [], []
    saved = g.get("body")
    try:
        for uid in dict.fromkeys(ids):
            if act == "org_add":
                with system_ctx(c):  # the account's current organisations (PATCH orgs replaces them)
                    have = [r[0] for r in c.execute("SELECT org_id FROM org_members WHERE user_id=? ORDER BY org_id", (uid,))]
                g.body = {"orgs": have + ([oid] if oid not in have else [])}
            else:
                g.body = {"disabled": act == "disable"}
            try:
                r = user_update(uid)
            except Denied as e:
                c.rollback()
                failed.append({"id": uid, "error": e.text()})
                continue
            if isinstance(r, tuple) and r[1] >= 400:
                c.rollback()  # an error after a partial write (user_update returns some errors without rolling back)
                failed.append({"id": uid, "error": (r[0].get_json() or {}).get("error", "")})
            else:
                ok.append(uid)
    finally:
        g.body = saved
    return jsonify(ok=ok, failed=failed)
