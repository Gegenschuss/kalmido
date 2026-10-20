"""2.143.0 A (#2151): organisation roles beyond member / admin -- one place that says what a role may do in an organisation.

    admin       manages the organisation (members, roles, settings) and sees / changes everything in it
    member      sees everything the organisation shares with all its members and changes it (the role every member had)
    readonly    "Read-only": sees what a member sees, changes nothing in the organisation (the team chat stays open)
    guest       "Guest": sees in the organisation only what is shared with them personally (lists, pages, calendars,
                address books they are a member of); no organisation-wide lists, no office, no agents, no invitations
    accounting  "Accounting": like a guest, plus the organisation's office to read and export, and receipts to upload;
                sends nothing, deletes nothing, no master data or settings

The person's private space is untouched (there they are their own admin); a person without organisation sees no change.
Every check sits on the server (routes, API v1, MCP, DAV); the app only hides what a role cannot use.
A server of the version before (2.142) reads an unknown role as member: give the new roles out only on 2.143.0 or later."""
from flask import g, has_request_context, request

from ..core.i18n import N_, tr

ROLE_KEYS = ("member", "admin", "guest", "readonly", "accounting")
FULL_READ = ("admin", "member", "readonly")    # sees the organisation's shared content without a personal share
FULL_WRITE = ("admin", "member")                # changes the organisation's content
OFFICE_READ = ("admin", "member", "readonly", "accounting")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
RO_MSG = N_("Your role in this organisation is read-only")
GUEST_MSG = N_("Your role in this organisation does not include this")
ACC_MSG = N_("The accounting role can read and export the office and upload receipts, nothing else")


def org_roles_of(c, uid):
    """{org id: role} of uid (cached per request; core/access.py acx_drop() forgets it). Unknown values read as member."""
    if not uid:
        return {}
    cache = g.setdefault("org_roles", {}) if has_request_context() else {}
    if uid not in cache:
        from .orgs import instance_mode
        from ..core.pg import system_ctx
        if instance_mode(c) == "shared":
            cache[uid] = {}
        else:
            with system_ctx(c):  # membership structure (also asked for other people)
                cache[uid] = {r[0]: (r[1] if r[1] in ROLE_KEYS else "member")
                              for r in c.execute("SELECT org_id, role FROM org_members WHERE user_id=?", (uid,))}
    return cache[uid]


def org_role_key(c, uid, oid):
    """The role of uid in organisation oid (None: not a member, or oid None / a private object)."""
    return org_roles_of(c, uid).get(oid) if oid else None


def org_sees_all(c, uid, oid):
    """Does uid see organisation oid's shared content without a personal share (member, admin, read-only)?"""
    return org_role_key(c, uid, oid) in FULL_READ


def org_writes(c, uid, oid):
    """May uid change content of organisation oid at all? Private objects (oid None): yes (their own rules decide)."""
    if not oid:
        return True
    r = org_role_key(c, uid, oid)
    return r is None or r in FULL_WRITE  # not a member: the object's own rules / the boundary decide


def org_readonly(c, uid, oid):
    """Is uid read-only in organisation oid? (A guest / accounting keeps the role of a personal share.)"""
    return org_role_key(c, uid, oid) == "readonly"


def org_limited(c, uid, oid):
    """Is uid in organisation oid with a role that limits them (guest, read-only, accounting)?"""
    return org_role_key(c, uid, oid) in ("guest", "readonly", "accounting")


def user_orgs_full(c, uid, write=False):
    """The organisations whose shared content uid sees (write: may change) -- user_orgs without the limited roles."""
    roles = FULL_WRITE if write else FULL_READ
    return [o for o, r in sorted(org_roles_of(c, uid).items()) if r in roles]


def is_write_request():
    return has_request_context() and request.method not in SAFE_METHODS


def need_org_write(c, uid, oid):
    """403 when uid's role in organisation oid does not allow changes (read-only, guest, accounting)."""
    if oid and not org_writes(c, uid, oid):
        from ..core.access import Denied
        raise Denied(403, tr(RO_MSG if org_role_key(c, uid, oid) == "readonly" else GUEST_MSG))


def need_org_area(c, uid, oid, write=None):
    """The gate of an organisation-wide area (pages, tables, bookmarks, clients ...): guests and accounting do not see it
    (404, as for a non-member), read-only people only read. write None = by the request's method."""
    if not oid:
        return
    from ..core.access import Denied
    if not org_sees_all(c, uid, oid):
        raise Denied(404)
    if (is_write_request() if write is None else write):
        need_org_write(c, uid, oid)


def office_allowed(c, uid, oid, write=None):
    """None when uid may use the office of organisation oid for this request, else the refusal text. Read-only and
    accounting: reading (incl. the bookkeeping and the exports, all GET); guests: nothing. Receipts are uploaded in the
    documents area (docs/web.py), not here."""
    r = org_role_key(c, uid, oid)
    if r is None or r in FULL_WRITE:
        return None
    if r == "guest":
        return GUEST_MSG
    if not (is_write_request() if write is None else write):
        return None
    return RO_MSG if r == "readonly" else ACC_MSG


def cap_list_role(c, uid, oid, role):
    """The list role uid has after their organisation role: read-only people view (participants stay participants, their
    writes are refused by list_writable)."""
    if role and oid and role in ("owner", "admin", "edit") and org_role_key(c, uid, oid) == "readonly":
        return "view"
    return role


def roles_public(c):
    """The roles an organisation admin can hand out, with their short explanation (the app's picker)."""
    return [{"key": k, "label": tr(lb), "hint": tr(h)} for k, lb, h in ROLE_TEXTS]


ROLE_TEXTS = (
    ("member", N_("Member"), N_("Sees and changes everything the organisation shares with its members")),
    ("admin", N_("Admin"), N_("Like a member, and manages members, roles and settings")),
    ("readonly", N_("Read-only"), N_("Sees what a member sees, changes nothing (team chat stays open)")),
    ("accounting", N_("Accounting"), N_("Reads and exports the office, uploads receipts; otherwise only what is shared personally")),
    ("guest", N_("Guest"), N_("Sees only what is shared with them personally")),
)
