"""2.148.1 B (#2483): data of an organisation leaves it (into the private space or another organisation) only through an
admin of that organisation. Every such move is written to the organisation's list log (org_list_log, action "moveout",
the kind and target in detail; list_id only for a list) and told to the organisation's other admins (News kind orglist).
A person without an organisation is never asked: private -> private and private -> organisation stay as they are."""
import json

from ..core.i18n import N_, tr
from ..core.db import iso, now_utc
from ..core.pg import system_ctx
from ..core.access import Denied
from ..accounts.session import me

OO_ADMIN_ONLY = N_("Only organisation admins can move data out of the organisation. Ask an admin of the organisation to do it.")  # 2.190.0 C (#2561)


def org_out(c, oid, to_oid, kind, name, list_id=None):
    """Data of organisation oid (kind: list | template | file | sheet | contacts | chat, name = what the log shows) goes to
    to_oid (None = private). Nothing to do when oid is no organisation or the target is the same one; else 403 for anybody
    but an admin of oid, and for an admin: log + News to the other admins (the caller commits)."""
    real = _org_name(c, oid, to_oid)
    if real is None:
        return
    if not org_out_ok(c, oid, to_oid):
        raise Denied(403, tr(OO_ADMIN_ONLY))
    detail = {"kind": kind, "to": "org" if to_oid else "private"}
    c.execute("INSERT INTO org_list_log(org_id,list_id,list_name,action,by_id,owner_id,to_id,created_at,detail) VALUES(?,?,?,?,?,?,?,?,?)",
              (oid, list_id, str(name or "")[:200], "moveout", me(), None, None, iso(now_utc()), json.dumps(detail)))
    from ..collab.news import news_add
    with system_ctx(c):  # the organisation's other admins (structure)
        admins = [r[0] for r in c.execute("""SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id
                                             WHERE m.org_id=? AND m.role='admin' AND u.disabled=0 AND m.user_id!=?""", (oid, me()))]
    for uid in admins:
        news_add(c, uid, "orglist", data={"action": "moveout", "name": str(name or "")[:200], "org": real, "kind": kind})


def _org_name(c, oid, to_oid):
    """The name of organisation oid when moving something of it to to_oid leaves it, else None (no organisation, the same
    one, or a personal office -- that is the owner's own)."""
    if not oid or (to_oid or None) == oid:
        return None
    with system_ctx(c):  # structure: is it a real organisation
        r = c.execute("SELECT name FROM orgs WHERE id=? AND personal_of IS NULL", (oid,)).fetchone()
    return r[0] if r else None


def org_out_ok(c, oid, to_oid):
    """True when the signed-in person may move data of organisation oid to to_oid (None = private): it stays inside, or
    the person is an admin of oid."""
    from ..accounts.orgs import is_org_admin
    return _org_name(c, oid, to_oid) is None or is_org_admin(c, me(), oid)
