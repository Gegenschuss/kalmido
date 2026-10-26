"""2.148.1 B (#2483): data of an organisation leaves it (into the private space or another organisation) only through an
admin of that organisation. Every such move is written to the organisation's list log (org_list_log, action "moveout",
the kind and target in detail; list_id only for a list) and told to the organisation's other admins (News kind orglist).
A person without an organisation is never asked: private -> private and private -> organisation stay as they are.

2.361.2 (#2923): the way back for a member. Whoever brought something in or made it (OO_KINDS) asks the admins
(org_out_requests, routes in accounts/orgoutreq.py); an admin releases it with one click and the member then moves that one
thing back into their private space themselves (seeing what the move ends), within OO_GRANT_DAYS. Nothing goes back silently."""
import json
from datetime import timedelta

from ..core.i18n import N_, tr
from ..core.db import iso, now_utc
from ..core.pg import system_ctx
from ..core.access import Denied
from ..accounts.session import me

OO_ADMIN_ONLY = N_("Only organisation admins can move data out of the organisation. Ask an admin of the organisation to do it.")  # 2.190.0 C (#2561)
# 2.361.2 (#2923): the note of every move into an organisation (the dry run / the workspace field)
OO_INTO_NOTE = N_("Back into your private space only after an admin of the organisation releases it (you ask for it).")
OO_GRANT_DAYS = 14  # an approved request is good for this many days

# 2.361.2 (#2923): what a member may ask back -- kind -> (table, name column, the columns naming who brought it in / made it)
OO_KINDS = {
    "list": ("lists", "name", ("owner_id",)),
    "sheet": ("sheets", "title", ("created_by",)),
    "file": ("fs_nodes", "name", ("created_by", "owner_id")),
}


def oo_mine(c, kind, obj, uid):
    """(org_id, name) of thing obj of kind when uid brought it in / made it, else None."""
    k = OO_KINDS.get(kind)
    if not k or not isinstance(obj, int) or isinstance(obj, bool):
        return None
    table, ncol, makers = k
    r = c.execute(f"SELECT org_id, {ncol} AS name, {', '.join(makers)} FROM {table} WHERE id=?", (obj,)).fetchone()
    if not r or not r["org_id"] or not any(r[m] == uid for m in makers):
        return None
    return r["org_id"], str(r["name"] or "")[:200]


def oo_grant(c, oid, kind, obj):
    """The id of the signed-in person's approved, unused request for obj of kind in organisation oid (OO_GRANT_DAYS), or None."""
    if not kind or obj is None:
        return None
    r = c.execute("SELECT id FROM org_out_requests WHERE org_id=? AND kind=? AND obj_id=? AND by_id=? AND state='approved' "
                  "AND decided_at>=? ORDER BY id DESC LIMIT 1", (oid, kind, obj, me(), iso(now_utc() - timedelta(days=OO_GRANT_DAYS)))).fetchone()
    return r[0] if r else None


def oo_into_note(c, from_oid, to_oid):
    """The note of a dry run moving something from from_oid (None = private) into organisation to_oid: a member gets it back
    only through its admins ('' when to_oid is no organisation, the same one, or the person is one of its admins)."""
    if not to_oid or (from_oid or None) == to_oid or _org_name(c, to_oid, None) is None or is_admin_of(c, to_oid):
        return ""
    return tr(OO_INTO_NOTE)


def oo_denied(c, oid, to_oid, kind, obj):
    """The 403 for a move out of oid by a non-admin: for the maker going private it carries what to ask for (the client offers
    "Ask an admin")."""
    data = None
    if to_oid is None and kind and isinstance(obj, int) and oo_mine(c, kind, obj, me()):
        data = {"out_request": {"org": oid, "kind": kind, "id": obj}}
    return Denied(403, tr(OO_ADMIN_ONLY), data=data)


def org_out(c, oid, to_oid, kind, name, list_id=None, obj=None):
    """Data of organisation oid (kind: list | template | file | sheet | contacts | chat, name = what the log shows) goes to
    to_oid (None = private). Nothing to do when oid is no organisation or the target is the same one; else 403 for anybody
    but an admin of oid, and for an admin: log + News to the other admins (the caller commits). 2.361.2 (#2923): obj = the
    id(s) of what goes (kind of OO_KINDS): a member's released request for each of them lets it go private (used up here)."""
    real = _org_name(c, oid, to_oid)
    if real is None:
        return
    objs = obj if isinstance(obj, (list, tuple)) else [obj] if obj is not None else []
    grants = []
    if not is_admin_of(c, oid):
        grants = [oo_grant(c, oid, kind, o) for o in objs] if to_oid is None else []
        if not grants or not all(grants):
            raise oo_denied(c, oid, to_oid, kind, next((o for o, g in zip(objs, grants) if not g), objs[0] if objs else None))
        c.execute(f"UPDATE org_out_requests SET state='used' WHERE id IN ({','.join('?' * len(grants))})", grants)
    detail = {"kind": kind, "to": "org" if to_oid else "private", **({"released": True} if grants else {})}
    c.execute("INSERT INTO org_list_log(org_id,list_id,list_name,action,by_id,owner_id,to_id,created_at,detail) VALUES(?,?,?,?,?,?,?,?,?)",
              (oid, list_id, str(name or "")[:200], "moveout", me(), None, None, iso(now_utc()), json.dumps(detail)))
    with system_ctx(c):  # the organisation's other admins (structure)
        admins = [r[0] for r in c.execute("""SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id
                                             WHERE m.org_id=? AND m.role='admin' AND u.disabled=0 AND m.user_id!=?""", (oid, me()))]
    oo_news(c, admins, {"action": "moveout", "name": str(name or "")[:200], "org": real, "kind": kind})


def oo_news(c, uids, data, list_id=None):
    """A News item "orglist" with data for each of uids (2.361.2, #2923: also the requests of accounts/orgoutreq.py)."""
    from ..collab.news import news_add
    for uid in uids:
        news_add(c, uid, "orglist", list_id=list_id, data=data)


def _org_name(c, oid, to_oid):
    """The name of organisation oid when moving something of it to to_oid leaves it, else None (no organisation, the same
    one, or a personal office -- that is the owner's own)."""
    if not oid or (to_oid or None) == oid:
        return None
    with system_ctx(c):  # structure: is it a real organisation
        r = c.execute("SELECT name FROM orgs WHERE id=? AND personal_of IS NULL", (oid,)).fetchone()
    return r[0] if r else None


def org_out_ok(c, oid, to_oid, kind=None, obj=None):
    """True when the signed-in person may move data of organisation oid to to_oid (None = private): it stays inside, or
    the person is an admin of oid, or (2.361.2, #2923) an admin released the person's request for obj of kind (going private)."""
    if _org_name(c, oid, to_oid) is None or is_admin_of(c, oid):
        return True
    return to_oid is None and oo_grant(c, oid, kind, obj) is not None


def is_admin_of(c, oid):
    from ..accounts.orgs import is_org_admin
    return is_org_admin(c, me(), oid)
